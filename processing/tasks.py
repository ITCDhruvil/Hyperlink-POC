"""Celery tasks for async PDF processing"""
from celery import shared_task, group, chord
from django.conf import settings
from pathlib import Path
from datetime import datetime
import os
import json
import tempfile
import shutil
import subprocess

from pdfs.models import PDFSet, DriveFolderCache
from pdfs.analytics_utils import get_or_create_run, start_step, finish_step, finish_run
from .pdf_utils import split_pdf, create_folder_structure
from .drive_utils import get_drive_service
from .pdf_utils import get_pdf_page_count
from .pdf_utils import merge_pdf_segments
from .split_spec import parse_split_groups
from pdfs.models import FolderStructureConfig
from .drive_path_resolver import DrivePathResolver
import time


def _write_job_state(job_dir: Path, state: dict) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix='state_', suffix='.json', dir=str(job_dir))
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp_path, str(job_dir / 'state.json'))
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=path.stem + '_', suffix='.json', dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


def _upload_state_paths(job_id: str) -> tuple[Path, Path, Path]:
    upload_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'uploads' / job_id
    files_dir = upload_dir / 'files'
    state_path = upload_dir / 'state.json'
    return upload_dir, files_dir, state_path


def _qpdf_available() -> bool:
    return shutil.which('qpdf') is not None


def _qpdf_extract_segments(input_pdf: str, output_pdf: str, segments: list[tuple[int, int]]) -> None:
    # qpdf uses 1-based page numbers; our segments are already 1-based.
    page_args: list[str] = []
    for start, end in segments:
        if start == end:
            page_args.append(str(start))
        else:
            page_args.append(f"{start}-{end}")

    cmd = ['qpdf', input_pdf, '--pages', '.', *page_args, '--', output_pdf]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or '').strip()
        raise RuntimeError(err or f"qpdf failed with return code {proc.returncode}")


def _safe_output_filename(label: str) -> str:
    # Keep it simple and consistent: label already normalized to digits/,- ; but may contain spaces.
    name = (label or '').strip()
    name = name.replace(' ', '_')
    return f"{name}.pdf"


@shared_task(bind=True, max_retries=3)
def process_pdf_set(self, pdfset_id: int):
    """
    Process a PDF set: split, upload to Drive, set permissions
    
    Args:
        pdfset_id: ID of the PDFSet to process
    """
    try:
        # Get PDF set with lock
        pdfset = PDFSet.objects.select_for_update().get(id=pdfset_id)
        
        # Update state
        pdfset.state = 'PROCESSING'
        pdfset.save()
        
        # Get original PDF path
        original_pdf_path = pdfset.original_pdf.file_path.path

        # Get metadata for folder structure
        date = pdfset.date or datetime.now().date()
        patient_name = pdfset.patient.name.replace(' ', '_')
        section_type = pdfset.section_type or 'Medical_Records'
        doctor_name = pdfset.doctor_name or ''

        # Create organized local folder structure: media/split_pdfs/Year/Month/Date/PatientName/
        output_folder = (
            Path(settings.MEDIA_ROOT) /
            'split_pdfs' /
            str(date.year) /
            f"{date.month:02d}" /
            f"{date.day:02d}" /
            patient_name
        )
        output_folder.mkdir(parents=True, exist_ok=True)

        # Generate descriptive output filename
        # Format: SectionType_DoctorName_Pages.pdf or SectionType_Pages.pdf
        if doctor_name:
            # Sanitize doctor name for filesystem
            safe_doctor_name = doctor_name.replace(' ', '_').replace(',', '').replace('.', '')
            output_filename = f"{section_type}_{safe_doctor_name}_{pdfset.start_page}-{pdfset.end_page}.pdf"
        else:
            output_filename = f"{section_type}_{pdfset.start_page}-{pdfset.end_page}.pdf"

        output_path = output_folder / output_filename
        
        # Split PDF
        local_path, sha256 = split_pdf(
            original_pdf_path,
            str(output_path),
            pdfset.start_page,
            pdfset.end_page
        )
        
        pdfset.local_path = str(local_path)
        pdfset.sha256 = sha256

        # If doctor_name not set, extract it from the PDF section
        if not pdfset.doctor_name:
            from .pdf_utils import generate_section_summary
            try:
                _, doctor_name = generate_section_summary(
                    original_pdf_path,
                    pdfset.start_page,
                    pdfset.end_page,
                    max_length=100
                )
                if doctor_name:
                    pdfset.doctor_name = doctor_name
            except Exception as e:
                print(f"Could not extract doctor name: {e}")

        pdfset.save()
        
        # Check for duplicates - TEMPORARILY DISABLED to test new folder structure
        # existing = PDFSet.objects.filter(
        #     sha256=sha256
        # ).exclude(id=pdfset_id).first()
        # 
        # if existing and existing.drive_file_id:
        #     # Reuse existing Drive link
        #     pdfset.drive_file_id = existing.drive_file_id
        #     pdfset.drive_webview_link = existing.drive_webview_link
        #     pdfset.state = 'DUPLICATE'
        #     pdfset.save()
        #     return {
        #         'status': 'duplicate',
        #         'pdfset_id': pdfset_id,
        #         'drive_link': pdfset.drive_webview_link
        #     }
        
        # Upload to Google Drive
        drive_service = get_drive_service()

        # Month name mapping
        month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                       'July', 'August', 'September', 'October', 'November', 'December']
        month_name = month_names[date.month - 1]

        # Create date folder name: "12 December 2025"
        date_folder_name = f"{date.day} {month_name} {date.year}"

        # SIMPLIFIED Drive folder hierarchy: Year/Month/Date/PatientName/splits/
        # Example: 2025/December/12_December_2025/Carl_Mayfield/splits/
        # This matches the user's requirement and removes unnecessary hospital level
        path_components = [
            str(date.year),
            month_name,
            date_folder_name,  # "12 December 2025"
            patient_name,
            'splits'  # All split PDFs for this patient in one folder
        ]
        
        # Check cache for folder ID
        folder_path_str = '/'.join(path_components)
        cached_folder = DriveFolderCache.objects.filter(folder_path=folder_path_str).first()
        
        if cached_folder:
            splits_folder_id = cached_folder.drive_folder_id
        else:
            splits_folder_id = drive_service.create_folder_hierarchy(path_components)
            # Cache the folder ID
            DriveFolderCache.objects.create(
                folder_path=folder_path_str,
                drive_folder_id=splits_folder_id
            )
        
        # Upload split PDF to 'splits' folder
        file_id, webview_link = drive_service.upload_file(
            local_path,
            splits_folder_id,
            output_filename
        )
        
        # Set permissions (domain-restricted or user-specific)
        # Uncomment and configure based on your needs:
        # drive_service.set_domain_permission(file_id, 'yourcompany.com')
        # OR
        # drive_service.set_user_permission(file_id, 'user@example.com')
        
        # Update PDF set
        pdfset.drive_file_id = file_id
        pdfset.drive_webview_link = webview_link
        pdfset.drive_folder_path = folder_path_str
        pdfset.state = 'UPLOADED'
        pdfset.save()
        
        return {
            'status': 'success',
            'pdfset_id': pdfset_id,
            'drive_link': webview_link
        }
        
    except Exception as exc:
        # Update state to failed
        pdfset = PDFSet.objects.get(id=pdfset_id)
        pdfset.state = 'FAILED'
        pdfset.error_message = str(exc)
        pdfset.save()
        
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task
def process_multiple_pdf_sets(pdfset_ids: list):
    """
    Process multiple PDF sets in parallel
    
    Args:
        pdfset_ids: List of PDFSet IDs to process
    """
    results = []
    for pdfset_id in pdfset_ids:
        result = process_pdf_set.delay(pdfset_id)
        results.append(result.id)
    
    return {
        'task_ids': results,
        'count': len(results)
    }


@shared_task(bind=True, max_retries=0)
def preflight_split_job(self, job_id: str, input_pdf_path: str, page_ranges_text: str):
    """Preflight checks for large PDF split jobs.

    Writes job state to: MEDIA_ROOT/processing/preflight/<job_id>/state.json
    """
    job_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'preflight' / job_id

    limits = {
        'max_bytes': 1 * 1024 * 1024 * 1024,
        'max_pages': 20000,
        'max_outputs': 2000,
        'max_total_extracted_pages': 100000,
    }

    state = {
        'job_id': job_id,
        'status': 'RUNNING',
        'stage': 'PREFLIGHT',
        'progress': 0,
        'limits': limits,
        'error': None,
        'input_pdf_path': input_pdf_path,
    }
    _write_job_state(job_dir, state)

    run = get_or_create_run(job_id=job_id, run_mode='ASYNC')
    step_rec = start_step(run, 'PREFLIGHT')

    try:
        if not input_pdf_path or not os.path.exists(input_pdf_path):
            raise ValueError('Input PDF not found for preflight')

        size_bytes = os.path.getsize(input_pdf_path)
        state.update({'progress': 10, 'file_size_bytes': size_bytes})
        _write_job_state(job_dir, state)

        if size_bytes > limits['max_bytes']:
            raise ValueError('PDF file is too large. Maximum allowed size is 1GB.')

        total_pages = get_pdf_page_count(input_pdf_path)
        run.page_count_total = total_pages
        run.outputs_requested = len(parse_split_groups(page_ranges_text))
        run.split_chunk_size = int(getattr(settings, 'SPLIT_TASK_CHUNK_SIZE', 10) or 10)
        run.split_backend = 'qpdf' if _qpdf_available() else 'pypdf2'
        run.save(update_fields=['page_count_total', 'outputs_requested', 'split_chunk_size', 'split_backend'])
        state.update({'progress': 30, 'page_count': total_pages})
        _write_job_state(job_dir, state)

        if total_pages > limits['max_pages']:
            raise ValueError(f"PDF has too many pages ({total_pages}). Maximum allowed is {limits['max_pages']}.")

        groups = parse_split_groups(page_ranges_text)
        state.update({'progress': 60, 'outputs_requested': len(groups)})
        _write_job_state(job_dir, state)

        if len(groups) > limits['max_outputs']:
            raise ValueError(f"Too many split outputs requested ({len(groups)}). Maximum allowed is {limits['max_outputs']}.")

        total_extracted_pages = 0
        for grp in groups:
            for start, end in grp['segments']:
                if end > total_pages:
                    raise ValueError(f"Segment {start}-{end} exceeds total pages ({total_pages})")
                total_extracted_pages += (end - start + 1)
                if total_extracted_pages > limits['max_total_extracted_pages']:
                    raise ValueError(
                        f"Too many total pages requested across splits. Maximum allowed is {limits['max_total_extracted_pages']}."
                    )

        state.update({
            'progress': 100,
            'status': 'SUCCESS',
            'total_extracted_pages': total_extracted_pages,
        })
        _write_job_state(job_dir, state)
        run.total_extracted_pages = total_extracted_pages
        run.save(update_fields=['total_extracted_pages'])
        finish_step(
            step_rec,
            status='SUCCESS',
            count_total=len(groups),
            count_done=len(groups),
            count_failed=0,
            extra={'total_pages': total_pages, 'file_size_bytes': size_bytes},
        )
        return state

    except Exception as exc:
        state.update({
            'status': 'FAILED',
            'progress': 100,
            'error': str(exc),
        })
        _write_job_state(job_dir, state)
        finish_step(step_rec, status='FAILED', error_message=str(exc))
        finish_run(run, status='FAILED', error_message=str(exc))
        return state


@shared_task(bind=True, max_retries=0)
def split_pdf_job(self, job_id: str):
    """Orchestrate parallel split of a PDF using an existing preflight job.

    This task writes a manifest and fans out one Celery task per output.
    Per-output status is written to:
      MEDIA_ROOT/processing/splits/<job_id>/output_status/<index>.json

    Final aggregated status is written to:
      MEDIA_ROOT/processing/splits/<job_id>/state.json
    """
    preflight_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'preflight' / job_id
    split_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'splits' / job_id
    split_dir.mkdir(parents=True, exist_ok=True)

    output_status_dir = split_dir / 'output_status'
    manifest_path = split_dir / 'manifest.json'
    state_path = split_dir / 'state.json'

    run = get_or_create_run(job_id=job_id, run_mode='ASYNC')
    step_rec = start_step(run, 'SPLIT')

    state = {
        'job_id': job_id,
        'status': 'RUNNING',
        'stage': 'SPLIT',
        'progress': 0,
        'error': None,
        'counts': {
            'total': 0,
            'done': 0,
            'failed': 0,
        },
        'backend': 'qpdf' if _qpdf_available() else 'pypdf2',
    }
    _write_job_state(split_dir, state)

    try:
        preflight_state_path = preflight_dir / 'state.json'
        if not preflight_state_path.exists():
            raise ValueError('Preflight has not been run for this job_id')

        with open(preflight_state_path, 'r', encoding='utf-8') as f:
            preflight_state = json.load(f)
        if preflight_state.get('status') != 'SUCCESS':
            raise ValueError(f"Preflight not successful: {preflight_state.get('error') or preflight_state.get('status')}")

        input_pdf_path = preflight_dir / 'input.pdf'
        if not input_pdf_path.exists():
            fallback_path = (preflight_state.get('input_pdf_path') or '').strip()
            if fallback_path and os.path.exists(fallback_path):
                input_pdf_path = Path(fallback_path)
            else:
                raise ValueError('Input PDF not found for this preflight job')

        req_path = preflight_dir / 'request.json'
        if not req_path.exists():
            fallback_path = (preflight_state.get('input_pdf_path') or '').strip()
            fallback_dir = Path(fallback_path).parent if fallback_path else None
            if fallback_dir and (fallback_dir / 'request.json').exists():
                req_path = fallback_dir / 'request.json'
            else:
                raise ValueError('Preflight request.json not found for this job')

        with open(req_path, 'r', encoding='utf-8') as f:
            req = json.load(f)
        page_ranges_text = (req.get('page_ranges') or '').strip()
        if not page_ranges_text:
            raise ValueError('Missing page_ranges in request.json')

        groups = parse_split_groups(page_ranges_text)
        total_pages = get_pdf_page_count(str(input_pdf_path))
        run.page_count_total = total_pages

        outputs = []
        for idx, grp in enumerate(groups, 1):
            label = grp['label']
            segments = grp['segments']
            out_name = _safe_output_filename(label)
            out_path = split_dir / out_name
            status_path = output_status_dir / f"{idx:06d}.json"

            outputs.append({
                'index': idx,
                'page_range': label,
                'filename': out_name,
                'segments': segments,
                'status_path': str(status_path),
                'output_path': str(out_path),
            })

        # Chunking reduces Celery/Redis overhead when outputs are large (e.g., 200+).
        chunk_size = int(getattr(settings, 'SPLIT_TASK_CHUNK_SIZE', 10) or 10)
        if chunk_size < 1:
            chunk_size = 10

        manifest = {
            'job_id': job_id,
            'created_at': datetime.utcnow().isoformat(),
            'total_pages': total_pages,
            'total_outputs': len(outputs),
            'backend': 'qpdf' if _qpdf_available() else 'pypdf2',
            'chunk_size': chunk_size,
            'outputs': outputs,
        }
        _write_json_atomic(manifest_path, manifest)

        state['counts']['total'] = len(outputs)
        state['total_pages'] = total_pages
        _write_job_state(split_dir, state)

        # Fan out chunk tasks. Each chunk writes per-output status JSON files.
        header = []
        for start in range(0, len(outputs), chunk_size):
            chunk = outputs[start:start + chunk_size]
            header.append(
                split_pdf_chunk_job.s(
                    job_id=job_id,
                    outputs_chunk=chunk,
                    input_pdf=str(input_pdf_path),
                    total_pages=total_pages,
                )
            )

        run.outputs_requested = len(outputs)
        run.split_chunk_size = chunk_size
        run.split_backend = manifest.get('backend') or ''
        run.save(update_fields=['page_count_total', 'outputs_requested', 'split_chunk_size', 'split_backend'])

        # This step measures orchestration (manifest + fanout scheduling). Actual completion is in finalize.
        finish_step(step_rec, status='SUCCESS', count_total=len(outputs), extra={'fanout_chunks': len(header)})

        callback = finalize_split_job.s(job_id=job_id)
        chord(group(header))(callback)
        return state

    except Exception as exc:
        state.update({'status': 'FAILED', 'progress': 100, 'error': str(exc)})
        _write_job_state(split_dir, state)
        finish_step(step_rec, status='FAILED', error_message=str(exc))
        finish_run(run, status='FAILED', error_message=str(exc))
        return state


@shared_task(bind=True, max_retries=0)
def finalize_split_job(job_id: str, results: list | None = None):
    """Aggregate output statuses and write final split state.json."""
    split_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'splits' / job_id
    output_status_dir = split_dir / 'output_status'
    manifest_path = split_dir / 'manifest.json'

    total = 0
    try:
        if manifest_path.exists():
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            total = int(manifest.get('total_outputs') or 0)
    except Exception:
        total = 0

    done = 0
    failed = 0
    outputs = []

    # Prefer reading status files (authoritative), not the chord results list.
    if output_status_dir.exists():
        status_files = sorted([p for p in output_status_dir.iterdir() if p.is_file() and p.suffix.lower() == '.json'])
        for p in status_files:
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    it = json.load(f)
                outputs.append(it)
                if it.get('status') == 'SUCCESS':
                    done += 1
                elif it.get('status') == 'FAILED':
                    failed += 1
            except Exception:
                continue

    if total == 0:
        total = max(len(outputs), len(results or []))

    final_state = {
        'job_id': job_id,
        'status': 'SUCCESS' if failed == 0 else 'PARTIAL_SUCCESS',
        'stage': 'SPLIT',
        'progress': 100,
        'error': None,
        'counts': {
            'total': total,
            'done': done,
            'failed': failed,
        },
        'outputs': outputs,
        'finished_at': datetime.utcnow().isoformat(),
    }
    _write_job_state(split_dir, final_state)
    run = get_or_create_run(job_id=job_id, run_mode='ASYNC')
    status = final_state.get('status') or 'FAILED'
    finish_run(
        run,
        status=status,
        extra={
            'split_counts': final_state.get('counts') or {},
        },
    )
    return final_state


@shared_task(bind=True, max_retries=3)
def upload_split_job(self, job_id: str, patient_name: str, batch_size: int = 25):
    upload_dir, files_dir, state_path = _upload_state_paths(job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    run = get_or_create_run(job_id=job_id, run_mode='ASYNC', patient_name=patient_name or '')
    step_rec = start_step(run, 'UPLOAD', extra={'batch_size': batch_size})

    split_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'splits' / job_id
    if not split_dir.exists():
        state = {'job_id': job_id, 'status': 'FAILED', 'progress': 100, 'error': 'Split job folder not found'}
        _write_json_atomic(state_path, state)
        finish_step(step_rec, status='FAILED', error_message=state['error'])
        finish_run(run, status='FAILED', error_message=state['error'])
        return state

    pdf_files = [
        p for p in split_dir.iterdir()
        if p.is_file() and p.suffix.lower() == '.pdf' and p.name.lower() != 'original.pdf'
    ]
    pdf_files.sort(key=lambda p: p.name.lower())
    if not pdf_files:
        state = {'job_id': job_id, 'status': 'FAILED', 'progress': 100, 'error': 'No split PDFs found'}
        _write_json_atomic(state_path, state)
        finish_step(step_rec, status='FAILED', error_message=state['error'])
        finish_run(run, status='FAILED', error_message=state['error'])
        return state

    config = FolderStructureConfig.get_active_config()
    if not config.root_folder_id:
        state = {'job_id': job_id, 'status': 'FAILED', 'progress': 100, 'error': 'Drive root folder ID is not configured'}
        _write_json_atomic(state_path, state)
        finish_step(step_rec, status='FAILED', error_message=state['error'])
        finish_run(run, status='FAILED', error_message=state['error'])
        return state

    relative_path = config.get_path_for_patient(patient_name or '')
    resolver = DrivePathResolver(root_folder_id=config.root_folder_id)
    drive_folder_id = resolver.resolve_path(relative_path, create_if_missing=True)
    if not drive_folder_id:
        state = {'job_id': job_id, 'status': 'FAILED', 'progress': 100, 'error': 'Failed to create/find patient folder in Drive'}
        _write_json_atomic(state_path, state)
        finish_step(step_rec, status='FAILED', error_message=state['error'])
        finish_run(run, status='FAILED', error_message=state['error'])
        return state

    manifest = {
        'job_id': job_id,
        'created_at': datetime.utcnow().isoformat(),
        'drive_folder_id': drive_folder_id,
        'patient_name': patient_name,
        'files': [
            {
                'index': idx,
                'filename': p.name,
                'local_path': str(p),
                'status_path': str(files_dir / f"{idx:06d}.json"),
            }
            for idx, p in enumerate(pdf_files, 1)
        ],
    }
    _write_json_atomic(upload_dir / 'manifest.json', manifest)

    state = {
        'job_id': job_id,
        'status': 'RUNNING',
        'stage': 'UPLOAD',
        'progress': 0,
        'error': None,
        'counts': {
            'total': len(pdf_files),
            'done': 0,
            'failed': 0,
        },
        'patient_name': patient_name,
        'drive_folder_id': drive_folder_id,
    }
    _write_json_atomic(state_path, state)

    try:
        header = []
        for idx, p in enumerate(pdf_files, 1):
            status_file = files_dir / f"{idx:06d}.json"
            if status_file.exists():
                try:
                    with open(status_file, 'r', encoding='utf-8') as f:
                        prev = json.load(f)
                    if prev.get('status') == 'SUCCESS':
                        continue
                except Exception:
                    pass

            header.append(
                upload_split_file_job.s(
                    job_id=job_id,
                    index=idx,
                    local_path=str(p),
                    filename=p.name,
                    drive_folder_id=drive_folder_id,
                )
            )

        if header:
            group(header).apply_async(queue='upload')

        finalize_upload_job.apply_async(
            kwargs={'job_id': job_id, 'patient_name': patient_name},
            countdown=2,
            queue='upload',
        )

        finish_step(step_rec, status='SUCCESS', count_total=len(pdf_files), extra={'fanout_files': len(header)})
        return state

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def upload_split_file_job(
    self,
    job_id: str,
    index: int,
    local_path: str,
    filename: str,
    drive_folder_id: str,
):
    upload_dir, files_dir, _ = _upload_state_paths(job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)
    status_path = files_dir / f"{int(index):06d}.json"

    if not local_path or not os.path.exists(local_path):
        payload = {
            'index': index,
            'filename': filename,
            'local_path': local_path,
            'status': 'FAILED',
            'error': 'Local file not found',
            'attempts': 0,
        }
        _write_json_atomic(status_path, payload)
        return payload

    drive = get_drive_service()

    last_err = None
    for attempt in range(1, 4):
        try:
            file_id, web_view = drive.upload_file(local_path, drive_folder_id, file_name=filename)
            payload = {
                'index': index,
                'filename': filename,
                'local_path': local_path,
                'status': 'SUCCESS',
                'error': None,
                'file_id': file_id,
                'webViewLink': web_view,
                'attempts': attempt,
                'finished_at': datetime.utcnow().isoformat(),
            }
            _write_json_atomic(status_path, payload)
            return payload
        except Exception as e:
            last_err = str(e)
            if attempt < 3:
                time.sleep(min(8, 2 ** attempt))

    payload = {
        'index': index,
        'filename': filename,
        'local_path': local_path,
        'status': 'FAILED',
        'error': last_err,
        'attempts': 3,
        'finished_at': datetime.utcnow().isoformat(),
    }
    _write_json_atomic(status_path, payload)
    return payload


@shared_task(bind=True, max_retries=0)
def finalize_upload_job(self, job_id: str, patient_name: str = ''):
    upload_dir, files_dir, state_path = _upload_state_paths(job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = upload_dir / 'manifest.json'
    if not manifest_path.exists():
        state = {'job_id': job_id, 'status': 'FAILED', 'progress': 100, 'error': 'Upload manifest not found'}
        _write_json_atomic(state_path, state)
        run = get_or_create_run(job_id=job_id, run_mode='ASYNC', patient_name=patient_name or '')
        finish_run(run, status='FAILED', error_message=state['error'])
        return state

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    files = manifest.get('files') or []

    done = 0
    failed = 0
    outputs: list[dict] = []
    for file_item in files:
        sp = file_item.get('status_path')
        if not sp:
            continue
        try:
            if not os.path.exists(sp):
                continue
            with open(sp, 'r', encoding='utf-8') as sf:
                rec = json.load(sf)
            outputs.append(rec)
            if rec.get('status') == 'SUCCESS':
                done += 1
            elif rec.get('status') == 'FAILED':
                failed += 1
        except Exception:
            continue

    total = len(files)
    progress = int((done + failed) / max(1, total) * 100)
    running = (done + failed) < total

    state = {
        'job_id': job_id,
        'status': 'RUNNING' if running else ('SUCCESS' if failed == 0 else 'PARTIAL_SUCCESS'),
        'stage': 'UPLOAD',
        'progress': progress if running else 100,
        'error': None,
        'counts': {
            'total': total,
            'done': done,
            'failed': failed,
        },
    }
    _write_json_atomic(state_path, state)

    if running:
        finalize_upload_job.apply_async(kwargs={'job_id': job_id, 'patient_name': patient_name}, countdown=2, queue='upload')
        return state

    run = get_or_create_run(job_id=job_id, run_mode='ASYNC', patient_name=patient_name or '')
    step_qs = run.steps.filter(step='UPLOAD').order_by('-started_at')
    step_rec = step_qs.first()
    if step_rec:
        finish_step(step_rec, status=state['status'], count_total=total, count_done=done, count_failed=failed)
    finish_run(run, status=state['status'], extra={'upload_counts': state.get('counts') or {}})
    return state
