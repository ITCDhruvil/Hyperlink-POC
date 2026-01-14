"""
Simple 2-Column Processor UI
Left: Upload & Display | Right: Results & Download
"""
from django.shortcuts import render
from django.http import JsonResponse, FileResponse
from django.http import Http404
from django.db.models import Avg
from django.db.models import Count
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_http_methods
import time
import os
import tempfile
import re
import uuid
import zipfile
from datetime import datetime

from .models import ProcessingHistory, FolderStructureConfig, ProcessingRun, ProcessingStep
from processing.smart_folder_detector_configurable import SmartFolderDetectorConfigurable
from processing.word_hyperlink_processor_simple import WordHyperlinkProcessorSimple
from processing.pdf_utils import get_pdf_page_count, split_pdf, merge_pdf_segments
from processing.drive_path_resolver import DrivePathResolver
from processing.drive_utils import get_drive_service
from processing.tasks import preflight_split_job, split_pdf_job, upload_split_job
from .analytics_utils import get_or_create_run, start_step, finish_step, finish_run


@login_required
def processor_ui(request):
    """Main UI page with 2-column layout"""
    return render(request, 'pdfs/processor_ui.html')


def _analytics_dashboard_allowed(request) -> bool:
    email = (getattr(request.user, 'email', '') or '').strip().lower()
    return email in {
        'hyperlink@itcube.net',
        'hyperlink@itcbube.net',
    }


def _async_capacity_allows_new_job() -> tuple[bool, dict]:
    from django.conf import settings

    max_running_total = int(getattr(settings, 'MAX_RUNNING_JOBS_TOTAL', 4) or 4)
    max_running_async = int(getattr(settings, 'MAX_RUNNING_JOBS_ASYNC', 3) or 3)

    running_total = ProcessingRun.objects.filter(status='RUNNING').count()
    running_async = ProcessingRun.objects.filter(status='RUNNING', run_mode='ASYNC').count()

    if running_total >= max_running_total or running_async >= max_running_async:
        return False, {
            'success': False,
            'error': 'System is busy. Please try again in a few minutes.',
            'busy': True,
            'running_total': running_total,
            'running_async': running_async,
            'limits': {
                'max_running_total': max_running_total,
                'max_running_async': max_running_async,
            }
        }

    return True, {}


@require_http_methods(["GET"])
@login_required
def analytics_dashboard(request):
    if not _analytics_dashboard_allowed(request):
        raise Http404()

    runs_qs = (
        ProcessingRun.objects
        .prefetch_related('steps')
        .order_by('-started_at')
    )
    total_runs = runs_qs.count()
    success_runs = runs_qs.filter(status='SUCCESS').count()
    failed_runs = runs_qs.filter(status='FAILED').count()
    partial_runs = runs_qs.filter(status='PARTIAL_SUCCESS').count()
    running_runs = runs_qs.filter(status='RUNNING').count()

    completed_runs_qs = runs_qs.filter(finished_at__isnull=False)
    overall_avg_duration_ms = completed_runs_qs.aggregate(v=Avg('duration_ms')).get('v')
    avg_duration_ms_by_mode = {
        it['run_mode']: it['avg_ms']
        for it in (
            completed_runs_qs
            .values('run_mode')
            .annotate(avg_ms=Avg('duration_ms'), cnt=Count('id'))
        )
    }

    step_avg_ms = {
        it['step']: it['avg_ms']
        for it in (
            ProcessingStep.objects
            .filter(run__in=completed_runs_qs, finished_at__isnull=False)
            .values('step')
            .annotate(avg_ms=Avg('duration_ms'), cnt=Count('id'))
        )
    }

    recent_runs_raw = list(runs_qs[:80])

    # If a job_id has both a SYNC "full" run and an ASYNC upload-only run, show only the SYNC run
    # to avoid confusing the dashboard view.
    best_by_job: dict[str, ProcessingRun] = {}
    passthrough: list[ProcessingRun] = []
    for r in recent_runs_raw:
        jid = (r.job_id or '').strip()
        if not jid:
            passthrough.append(r)
            continue

        cur = best_by_job.get(jid)
        if cur is None:
            best_by_job[jid] = r
            continue

        # Prefer SYNC over ASYNC for same job_id, otherwise keep most recent (already sorted).
        if cur.run_mode != 'SYNC' and r.run_mode == 'SYNC':
            best_by_job[jid] = r

    recent_runs = list(best_by_job.values()) + passthrough
    recent_runs = sorted(recent_runs, key=lambda x: x.started_at, reverse=True)[:50]

    # Derived fields for UI
    for r in recent_runs:
        r.duration_s = (int(r.duration_ms or 0) / 1000.0) if r.duration_ms is not None else None

    context = {
        'total_runs': total_runs,
        'success_runs': success_runs,
        'failed_runs': failed_runs,
        'partial_runs': partial_runs,
        'running_runs': running_runs,
        'runs': recent_runs,
        'overall_avg_duration_s': (float(overall_avg_duration_ms) / 1000.0) if overall_avg_duration_ms is not None else None,
        'avg_duration_sync_s': (float(avg_duration_ms_by_mode.get('SYNC') or 0) / 1000.0) if avg_duration_ms_by_mode.get('SYNC') is not None else None,
        'avg_duration_async_s': (float(avg_duration_ms_by_mode.get('ASYNC') or 0) / 1000.0) if avg_duration_ms_by_mode.get('ASYNC') is not None else None,
        'avg_step_preflight_s': (float(step_avg_ms.get('PREFLIGHT') or 0) / 1000.0) if step_avg_ms.get('PREFLIGHT') is not None else None,
        'avg_step_split_s': (float(step_avg_ms.get('SPLIT') or 0) / 1000.0) if step_avg_ms.get('SPLIT') is not None else None,
        'avg_step_upload_s': (float(step_avg_ms.get('UPLOAD') or 0) / 1000.0) if step_avg_ms.get('UPLOAD') is not None else None,
        'avg_step_word_process_s': (float(step_avg_ms.get('WORD_PROCESS') or 0) / 1000.0) if step_avg_ms.get('WORD_PROCESS') is not None else None,
    }
    return render(request, 'pdfs/analytics_dashboard.html', context)


@require_http_methods(["GET"])
@login_required
def analytics_run_detail(request, run_id: str):
    if not _analytics_dashboard_allowed(request):
        raise Http404()

    run = ProcessingRun.objects.filter(id=run_id).first()
    if run is None:
        raise Http404()

    steps = list(ProcessingStep.objects.filter(run=run).order_by('started_at'))

    # If the user opened an ASYNC upload-only run, also show the SYNC run's steps for the same job_id.
    jid = (run.job_id or '').strip()
    if jid and run.run_mode == 'ASYNC':
        if len(steps) == 1 and steps[0].step == 'UPLOAD':
            related_sync = (
                ProcessingRun.objects
                .filter(job_id=jid, run_mode='SYNC')
                .order_by('-started_at')
                .first()
            )
            if related_sync is not None:
                sync_steps = list(ProcessingStep.objects.filter(run=related_sync).order_by('started_at'))
                # Prefer showing SPLIT/WORD_PROCESS from SYNC, and UPLOAD from ASYNC (current run).
                merged = [s for s in sync_steps if s.step != 'UPLOAD'] + steps
                steps = merged
    for s in steps:
        s.duration_s = (int(s.duration_ms or 0) / 1000.0) if s.duration_ms is not None else None

    run.duration_s = (int(run.duration_ms or 0) / 1000.0) if run.duration_ms is not None else None

    context = {
        'run': run,
        'steps': steps,
    }
    return render(request, 'pdfs/analytics_run_detail.html', context)


@require_http_methods(["GET"])
@login_required
def processing_history(request):
    """
    Display processing history with pagination
    Shows list of all processed documents with metadata
    """
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

    # Admins see all history; regular users see only their own
    if request.user.is_staff or request.user.is_superuser:
        history_list = ProcessingHistory.objects.all().order_by('-uploaded_at')
    else:
        history_list = ProcessingHistory.objects.filter(user=request.user).order_by('-uploaded_at')

    # Pagination - 10 items per page
    paginator = Paginator(history_list, 10)
    page = request.GET.get('page', 1)

    try:
        history_items = paginator.page(page)
    except PageNotAnInteger:
        history_items = paginator.page(1)
    except EmptyPage:
        history_items = paginator.page(paginator.num_pages)

    # Get statistics (respect same scope as list)
    total_documents = history_list.count()

    successful_documents = history_list.filter(status='SUCCESS').count()
    failed_documents = history_list.filter(status='FAILED').count()
    pending_documents = history_list.filter(status='PENDING').count()

    context = {
        'history_items': history_items,
        'total_documents': total_documents,
        'successful_documents': successful_documents,
        'failed_documents': failed_documents,
        'pending_documents': pending_documents,
        'success_rate': round((successful_documents / total_documents * 100) if total_documents > 0 else 0, 1)
    }

    return render(request, 'pdfs/processing_history.html', context)


@require_POST
@csrf_exempt
@login_required
def start_preflight_split(request):
    """Start an async preflight for a large PDF split job (Celery + Redis)."""
    try:
        allowed, payload = _async_capacity_allows_new_job()
        if not allowed:
            return JsonResponse(payload, status=429)

        if 'file' not in request.FILES:
            return JsonResponse({'success': False, 'error': 'No PDF uploaded. Please upload a PDF.'}, status=400)

        uploaded_file = request.FILES['file']
        if not (uploaded_file.name or '').lower().endswith('.pdf'):
            return JsonResponse({'success': False, 'error': 'Please upload a PDF file'}, status=400)

        page_ranges_text = request.POST.get('page_ranges', '')
        patient_name = (request.POST.get('patient_name') or '').strip()
        if not (page_ranges_text or '').strip():
            return JsonResponse({'success': False, 'error': 'Page ranges are required'}, status=400)

        from django.conf import settings
        job_id = uuid.uuid4().hex
        job_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'preflight', job_id)
        os.makedirs(job_dir, exist_ok=True)
        input_pdf_path = os.path.join(job_dir, 'input.pdf')

        with open(input_pdf_path, 'wb') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        # Persist request inputs so later tasks (split/upload) can reuse them by job_id
        import json
        with open(os.path.join(job_dir, 'request.json'), 'w', encoding='utf-8') as f:
            json.dump({'page_ranges': page_ranges_text, 'patient_name': patient_name}, f, ensure_ascii=False)

        task = preflight_split_job.delay(job_id, input_pdf_path, page_ranges_text)
        return JsonResponse({'success': True, 'job_id': job_id, 'task_id': task.id})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
@login_required
def retry_async_split(request, job_id: str):
    """Retry async split for a job_id. Resumable: skips outputs already completed."""
    try:
        allowed, payload = _async_capacity_allows_new_job()
        if not allowed:
            return JsonResponse(payload, status=429)

        task = split_pdf_job.delay(job_id)
        return JsonResponse({'success': True, 'job_id': job_id, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
@login_required
def retry_async_upload(request, job_id: str):
    """Retry async upload for a job_id. Resumable: skips files already uploaded."""
    try:
        allowed, payload = _async_capacity_allows_new_job()
        if not allowed:
            return JsonResponse(payload, status=429)

        patient_name = (request.POST.get('patient_name') or '').strip()
        if not patient_name:
            from django.conf import settings
            req_path = os.path.join(settings.MEDIA_ROOT, 'processing', 'preflight', job_id, 'request.json')
            if os.path.exists(req_path):
                import json
                with open(req_path, 'r', encoding='utf-8') as f:
                    req = json.load(f)
                patient_name = (req.get('patient_name') or '').strip()

        batch_size = request.POST.get('batch_size')
        batch_size_int = int(batch_size) if batch_size and str(batch_size).isdigit() else 25

        task = upload_split_job.delay(job_id, patient_name, batch_size_int)
        return JsonResponse({'success': True, 'job_id': job_id, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
@login_required
def start_async_upload(request, job_id: str):
    """Start async upload of split outputs to Drive for an existing job_id."""
    try:
        allowed, payload = _async_capacity_allows_new_job()
        if not allowed:
            return JsonResponse(payload, status=429)

        # Prefer patient name from request (explicit), fallback to preflight request.json
        patient_name = (request.POST.get('patient_name') or '').strip()
        if not patient_name:
            from django.conf import settings
            req_path = os.path.join(settings.MEDIA_ROOT, 'processing', 'preflight', job_id, 'request.json')
            if os.path.exists(req_path):
                import json
                with open(req_path, 'r', encoding='utf-8') as f:
                    req = json.load(f)
                patient_name = (req.get('patient_name') or '').strip()

        batch_size = request.POST.get('batch_size')
        batch_size_int = int(batch_size) if batch_size and str(batch_size).isdigit() else 25

        task = upload_split_job.delay(job_id, patient_name, batch_size_int)
        return JsonResponse({'success': True, 'job_id': job_id, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["GET"])
@login_required
def async_upload_status(request, job_id: str):
    """Poll status for async upload job."""
    try:
        from django.conf import settings
        state_path = os.path.join(settings.MEDIA_ROOT, 'processing', 'uploads', job_id, 'state.json')
        if not os.path.exists(state_path):
            return JsonResponse({'success': True, 'job_id': job_id, 'status': 'PENDING'})

        import json
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)

        # If upload is running with parallel fan-out, compute live progress from per-file status JSONs.
        if state.get('stage') == 'UPLOAD' and state.get('status') == 'RUNNING':
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'uploads', job_id)
            manifest_path = os.path.join(upload_dir, 'manifest.json')
            files_dir = os.path.join(upload_dir, 'files')

            total = int((state.get('counts') or {}).get('total') or 0)
            done = 0
            failed = 0

            try:
                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r', encoding='utf-8') as mf:
                        manifest = json.load(mf)
                    total = int(len(manifest.get('files') or []) or total)

                if os.path.isdir(files_dir):
                    for name in os.listdir(files_dir):
                        if not name.lower().endswith('.json'):
                            continue
                        fp = os.path.join(files_dir, name)
                        try:
                            with open(fp, 'r', encoding='utf-8') as sf:
                                rec = json.load(sf)
                            if rec.get('status') == 'SUCCESS':
                                done += 1
                            elif rec.get('status') == 'FAILED':
                                failed += 1
                        except Exception:
                            continue

                state['counts'] = {'total': total, 'done': done, 'failed': failed}
                state['progress'] = int(((done + failed) / max(1, total)) * 100)
            except Exception:
                pass

        state['success'] = True
        return JsonResponse(state)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@require_POST
@csrf_exempt
@login_required
def start_async_split(request, job_id: str):
    """Start async split for an existing preflight job_id."""
    try:
        allowed, payload = _async_capacity_allows_new_job()
        if not allowed:
            return JsonResponse(payload, status=429)

        task = split_pdf_job.delay(job_id)
        return JsonResponse({'success': True, 'job_id': job_id, 'task_id': task.id})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["GET"])
@login_required
def async_split_status(request, job_id: str):
    """Poll status for async split job."""
    try:
        from django.conf import settings
        state_path = os.path.join(settings.MEDIA_ROOT, 'processing', 'splits', job_id, 'state.json')
        if not os.path.exists(state_path):
            return JsonResponse({'success': True, 'job_id': job_id, 'status': 'PENDING'})

        import json
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)

        # If split is running in parallel fan-out mode, state.json is an orchestrator snapshot.
        # Compute live progress by reading manifest.json and per-output status files.
        if state.get('stage') == 'SPLIT' and state.get('status') == 'RUNNING':
            split_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'splits', job_id)
            manifest_path = os.path.join(split_dir, 'manifest.json')
            output_status_dir = os.path.join(split_dir, 'output_status')

            total = int((state.get('counts') or {}).get('total') or 0)
            try:
                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r', encoding='utf-8') as mf:
                        manifest = json.load(mf)
                    total = int(manifest.get('total_outputs') or total)
                    if manifest.get('backend'):
                        state['backend'] = manifest.get('backend')
                    if manifest.get('total_pages') is not None:
                        state['total_pages'] = manifest.get('total_pages')
            except Exception:
                pass

            done = 0
            failed = 0
            outputs_preview = []

            try:
                if os.path.isdir(output_status_dir):
                    files = sorted([p for p in os.listdir(output_status_dir) if p.lower().endswith('.json')])
                    for name in files:
                        pth = os.path.join(output_status_dir, name)
                        try:
                            with open(pth, 'r', encoding='utf-8') as sf:
                                it = json.load(sf)
                            st = it.get('status')
                            if st == 'SUCCESS':
                                done += 1
                            elif st == 'FAILED':
                                failed += 1
                            if len(outputs_preview) < 20:
                                outputs_preview.append(it)
                        except Exception:
                            continue
            except Exception:
                pass

            if not total:
                total = max(1, done + failed)

            state['counts'] = {'total': total, 'done': done, 'failed': failed}
            state['progress'] = int(((done + failed) / max(1, total)) * 100)
            state['outputs_preview'] = outputs_preview

        state['success'] = True
        return JsonResponse(state)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["GET"])
@login_required
def preflight_split_status(request, job_id: str):
    """Poll status for a preflight split job."""
    try:
        from django.conf import settings
        state_path = os.path.join(settings.MEDIA_ROOT, 'processing', 'preflight', job_id, 'state.json')
        if not os.path.exists(state_path):
            return JsonResponse({'success': True, 'job_id': job_id, 'status': 'PENDING'})

        import json
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        state['success'] = True
        return JsonResponse(state)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
@login_required
def upload_document(request):
    """
    Upload Word document
    Returns: document ID and preview info
    """
    try:
        if 'file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No file uploaded'
            }, status=400)

        uploaded_file = request.FILES['file']

        # Validate file type
        if not uploaded_file.name.endswith('.docx'):
            return JsonResponse({
                'success': False,
                'error': 'Please upload a Word document (.docx file)'
            }, status=400)

        # Create processing history record
        history = ProcessingHistory.objects.create(
            input_filename=uploaded_file.name,
            input_file=uploaded_file,
            user=request.user,
            status='PENDING'
        )

        return JsonResponse({
            'success': True,
            'document_id': history.id,
            'filename': uploaded_file.name,
            'size': uploaded_file.size,
            'uploaded_at': history.uploaded_at.strftime('%Y-%m-%d %H:%M:%S')
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Upload failed: {str(e)}'
        }, status=500)


@require_POST
@csrf_exempt
@login_required
def process_document(request, document_id):
    """
    Process uploaded document
    Returns: processing results with user-friendly error messages
    """
    start_time = time.time()

    try:
        # Get document history
        history = ProcessingHistory.objects.get(id=document_id)
        if history.user_id is None:
            history.user = request.user
            history.save(update_fields=['user'])
        history.status = 'PROCESSING'
        history.save()

        # Get input file path
        input_path = history.input_file.path

        # Step 1: Get configuration
        config = FolderStructureConfig.get_active_config()

        # Step 2: Detect folder
        detector = SmartFolderDetectorConfigurable(config=config)

        patient_name_override = (request.POST.get('patient_name') or '').strip()
        if patient_name_override:
            patient_name_override = patient_name_override.title().replace(' ', '_')

        try:
            if patient_name_override:
                folder_id = detector.find_patient_folder(patient_name_override)
            else:
                folder_id = detector.find_pdf_folder_for_document(input_path)
        except Exception as e:
            history.status = 'FAILED'
            history.error_message = str(e)
            history.user_friendly_error = "Could not find patient folder in Google Drive. Please check if the patient name in the document matches a folder in your Drive."
            history.save()

            return JsonResponse({
                'success': False,
                'error': history.user_friendly_error,
                'details': str(e)
            })

        if not folder_id:
            history.status = 'FAILED'
            history.user_friendly_error = "Patient folder not found in Google Drive. Please make sure a folder exists with the patient's name."
            history.save()

            return JsonResponse({
                'success': False,
                'error': history.user_friendly_error
            })

        history.folder_id = folder_id

        # Step 3: Fetch PDFs
        processor = WordHyperlinkProcessorSimple()

        try:
            pdf_links = processor.get_pdfs_from_drive_folder(folder_id)
        except Exception as e:
            history.status = 'FAILED'
            history.error_message = str(e)
            history.user_friendly_error = "Could not access PDFs from Google Drive. Please check folder permissions."
            history.save()

            return JsonResponse({
                'success': False,
                'error': history.user_friendly_error,
                'details': str(e)
            })

        if len(pdf_links) == 0:
            history.status = 'FAILED'
            history.user_friendly_error = "No PDF files found in the patient folder. Please upload split PDFs to the folder."
            history.save()

            return JsonResponse({
                'success': False,
                'error': history.user_friendly_error
            })

        # Extract patient name from document
        from docx import Document
        doc = Document(input_path)
        patient_name = processor.extract_patient_name_from_document(doc)
        if patient_name_override:
            history.patient_name = patient_name_override
        else:
            history.patient_name = patient_name or "Unknown"
        history.save()

        # Step 4: Process document
        # Create temporary output file
        output_filename = history.input_filename.replace('.docx', '_PROCESSED.docx')
        temp_output = tempfile.NamedTemporaryFile(delete=False, suffix='.docx')
        temp_output_path = temp_output.name
        temp_output.close()

        try:
            result = processor.process_word_document(
                input_docx_path=input_path,
                pdf_links=pdf_links,
                output_docx_path=temp_output_path
            )
        except Exception as e:
            history.status = 'FAILED'
            history.error_message = str(e)
            history.user_friendly_error = f"Document processing failed: {str(e)}"
            history.save()

            return JsonResponse({
                'success': False,
                'error': history.user_friendly_error,
                'details': str(e)
            })

        # Save output file
        with open(temp_output_path, 'rb') as f:
            history.output_file.save(output_filename, ContentFile(f.read()), save=False)

        # Clean up temp file
        os.unlink(temp_output_path)

        # Calculate processing time
        processing_time = time.time() - start_time

        # Update history
        history.status = 'SUCCESS'
        history.output_filename = output_filename
        history.processing_time_seconds = round(processing_time, 2)
        history.total_statements = result['total_statements']
        history.linked_statements = result['linked_statements']
        history.unlinked_statements = result['unlinked_statements']
        history.processed_at = datetime.now()
        history.save()

        # Prepare user-friendly messages for unlinked statements
        unlinked_messages = []
        if result['unlinked_statements'] > 0:
            for stmt in result['statements']:
                if stmt['status'] != 'linked':
                    page_range = stmt['page_range']
                    unlinked_messages.append(
                        f"Page {page_range}: Your split PDF '{page_range}.pdf' is missing from the Drive folder"
                    )

        return JsonResponse({
            'success': True,
            'document_id': history.id,
            'processing_time': processing_time,
            'patient_name': history.patient_name,
            'results': {
                'total_statements': result['total_statements'],
                'linked_statements': result['linked_statements'],
                'unlinked_statements': result['unlinked_statements'],
                'success_rate': round(result['linked_statements'] / result['total_statements'] * 100) if result['total_statements'] > 0 else 0
            },
            'unlinked_messages': unlinked_messages,
            'output_filename': output_filename,
            'pdf_count': len(pdf_links)
        })

    except ProcessingHistory.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Document not found'
        }, status=404)


def _normalize_split_spec(s: str) -> str:
    s = (s or '').replace('\u00a0', ' ').strip()
    s = s.replace('–', '-').replace('—', '-').replace('‑', '-')
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*,\s*', ', ', s)
    return s.strip()


def _parse_split_groups(ranges_text: str):
    ranges_text = _normalize_split_spec(ranges_text)
    if not ranges_text:
        raise ValueError('Page ranges are required')

    groups_raw = [g.strip() for g in re.split(r'[;\n]+', ranges_text) if g.strip()]
    if not groups_raw:
        raise ValueError('Page ranges are required')

    groups = []
    for group_raw in groups_raw:
        parts = [p.strip() for p in group_raw.split(',') if p.strip()]
        if not parts:
            raise ValueError(f"Invalid group: '{group_raw}'")

        segments = []
        normalized_parts = []
        for part in parts:
            part = _normalize_split_spec(part)
            m_range = re.match(r'^(\d+)\s*-\s*(\d+)$', part)
            m_single = re.match(r'^(\d+)$', part)
            if m_range:
                start = int(m_range.group(1))
                end = int(m_range.group(2))
            elif m_single:
                start = int(m_single.group(1))
                end = start
            else:
                raise ValueError(f"Invalid segment: '{part}'. Use 1-4 or 55")

            if start < 1 or end < 1 or end < start:
                raise ValueError(f"Invalid segment: '{part}'. Ensure start/end are positive and end >= start")

            segments.append((start, end))
            normalized_parts.append(f"{start}-{end}" if start != end else f"{start}")

        label = ', '.join(normalized_parts)
        groups.append({'label': label, 'segments': segments})

    return groups


@require_POST
@csrf_exempt
@login_required
def split_pdf_document(request):
    """Upload a PDF and split it into multiple PDFs based on user-provided page ranges."""
    try:
        session_id = (request.POST.get('session_id') or '').strip()

        input_path = None
        should_cleanup_input = False

        max_bytes = 1 * 1024 * 1024 * 1024
        max_pages = 20000
        max_outputs = 2000
        max_total_extracted_pages = 100000

        if 'file' in request.FILES:
            uploaded_file = request.FILES['file']
            if not (uploaded_file.name or '').lower().endswith('.pdf'):
                return JsonResponse({'success': False, 'error': 'Please upload a PDF file'}, status=400)

            if getattr(uploaded_file, 'size', 0) and uploaded_file.size > max_bytes:
                return JsonResponse({'success': False, 'error': 'PDF file is too large. Maximum allowed size is 1GB.'}, status=400)

            # Save input PDF to a temp location
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                for chunk in uploaded_file.chunks():
                    tmp.write(chunk)
                input_path = tmp.name
            should_cleanup_input = True
        elif session_id:
            from django.conf import settings
            session_pdf_path = os.path.join(settings.MEDIA_ROOT, 'processing', 'sessions', session_id, 'input.pdf')
            if not os.path.exists(session_pdf_path):
                return JsonResponse({'success': False, 'error': 'Original PDF for this session was not found. Please upload a PDF.'}, status=400)
            try:
                if os.path.getsize(session_pdf_path) > max_bytes:
                    return JsonResponse({'success': False, 'error': 'PDF file is too large. Maximum allowed size is 1GB.'}, status=400)
            except Exception:
                pass
            input_path = session_pdf_path
            should_cleanup_input = False
        else:
            return JsonResponse({'success': False, 'error': 'No PDF uploaded. Please upload a PDF or use an existing session.'}, status=400)

        page_ranges_text = request.POST.get('page_ranges', '')
        try:
            groups = _parse_split_groups(page_ranges_text)
        except ValueError as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

        try:
            total_pages = get_pdf_page_count(input_path)

            if total_pages > max_pages:
                return JsonResponse({'success': False, 'error': f'PDF has too many pages ({total_pages}). Maximum allowed is {max_pages}.'}, status=400)

            job_id = uuid.uuid4().hex
            # Store under MEDIA_ROOT so Django can serve it if needed
            from django.conf import settings
            output_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'splits', job_id)
            os.makedirs(output_dir, exist_ok=True)

            if len(groups) > max_outputs:
                return JsonResponse({'success': False, 'error': f'Too many split outputs requested ({len(groups)}). Maximum allowed is {max_outputs}.'}, status=400)

            total_extracted_pages = 0
            for grp in groups:
                for start, end in grp['segments']:
                    total_extracted_pages += (end - start + 1)
                    if total_extracted_pages > max_total_extracted_pages:
                        return JsonResponse({'success': False, 'error': f'Too many total pages requested across splits. Maximum allowed is {max_total_extracted_pages}.'}, status=400)

            outputs = []
            for grp in groups:
                label = grp['label']
                segments = grp['segments']

                for start, end in segments:
                    if end > total_pages:
                        return JsonResponse({
                            'success': False,
                            'error': f"Segment {start}-{end} exceeds total pages ({total_pages})"
                        }, status=400)

                out_name = f"{label}.pdf"
                out_path = os.path.join(output_dir, out_name)
                merge_pdf_segments(input_path, out_path, segments)

                outputs.append({
                    'page_range': label,
                    'filename': out_name,
                    'download_url': f"{settings.MEDIA_URL}processing/splits/{job_id}/{out_name}",
                })

            return JsonResponse({
                'success': True,
                'job_id': job_id,
                'total_pages': total_pages,
                'count': len(outputs),
                'files': outputs,
                'download_all_url': f"/download-split-zip/{job_id}/"
            })

        finally:
            if should_cleanup_input and input_path and os.path.exists(input_path):
                os.unlink(input_path)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_POST
@csrf_exempt
@login_required
def upload_split_to_drive(request, job_id: str):
    """Upload all split PDFs for a job to Google Drive under a patient-named folder (create if missing)."""
    try:
        patient_name = (request.POST.get('patient_name') or '').strip()
        if not patient_name:
            return JsonResponse({'success': False, 'error': 'Patient name is required'}, status=400)

        # Match existing naming convention used in folder detection
        patient_name_key = patient_name.title().replace(' ', '_')

        from django.conf import settings
        base_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'splits', job_id)
        if not os.path.isdir(base_dir):
            return JsonResponse({'success': False, 'error': 'Split job not found'}, status=404)

        # Do not upload the original input PDF; only upload split outputs
        pdf_files = [
            f
            for f in os.listdir(base_dir)
            if f.lower().endswith('.pdf') and f.lower() != 'original.pdf'
        ]
        if not pdf_files:
            return JsonResponse({'success': False, 'error': 'No split PDFs found'}, status=404)

        config = FolderStructureConfig.get_active_config()
        if not config.root_folder_id:
            return JsonResponse({'success': False, 'error': 'Drive root folder ID is not configured'}, status=400)

        # Create folder path based on config (FLAT/WITH_SPLITS/YEAR_MONTH/CUSTOM)
        relative_path = config.get_path_for_patient(patient_name_key)
        resolver = DrivePathResolver(root_folder_id=config.root_folder_id)
        drive_folder_id = resolver.resolve_path(relative_path, create_if_missing=True)
        if not drive_folder_id:
            return JsonResponse({'success': False, 'error': 'Failed to create/find patient folder in Drive'}, status=500)

        drive = get_drive_service()

        uploaded = []
        for name in sorted(pdf_files):
            local_path = os.path.join(base_dir, name)
            file_id, web_view = drive.upload_file(local_path, drive_folder_id, file_name=name)
            uploaded.append({'filename': name, 'file_id': file_id, 'webViewLink': web_view})

        return JsonResponse({
            'success': True,
            'job_id': job_id,
            'patient_name': patient_name_key,
            'drive_folder_id': drive_folder_id,
            'count': len(uploaded),
            'files': uploaded,
        })

    except Exception as e:
        msg = str(e)
        if 'Service Accounts do not have storage quota' in msg or 'storageQuotaExceeded' in msg:
            return JsonResponse({
                'success': False,
                'error': 'Google Drive upload failed: the service account has no storage quota. Uploads must go to a Shared Drive (and the service account must be added as a member), or you must use OAuth domain-wide delegation.',
                'details': msg,
            }, status=500)

        return JsonResponse({'success': False, 'error': msg}, status=500)


@require_http_methods(["GET"])
@login_required
def download_document(request, document_id):
    """
    Download processed document
    """
    try:
        history = ProcessingHistory.objects.get(id=document_id)

        if history.status != 'SUCCESS' or not history.output_file:
            return JsonResponse({
                'success': False,
                'error': 'Processed document not available'
            }, status=404)

        response = FileResponse(
            history.output_file.open('rb'),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        response['Content-Disposition'] = f'attachment; filename="{history.output_filename}"'

        return response

    except ProcessingHistory.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Document not found'
        }, status=404)


@require_POST
@csrf_exempt
@login_required
def extract_page_ranges_from_word(request):
    """
    Extract page ranges from an uploaded Word document
    Returns: List of page ranges for PDF splitting
    """
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'success': False, 'error': 'No file uploaded'}, status=400)

        uploaded_file = request.FILES['file']

        # Validate file type
        if not uploaded_file.name.endswith('.docx'):
            return JsonResponse({
                'success': False,
                'error': 'Please upload a Word document (.docx file)'
            }, status=400)

        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        try:
            # Use processor to extract page ranges
            processor = WordHyperlinkProcessorSimple()
            ranges = processor.extract_page_ranges_from_file(temp_path)

            # Format for split: semicolon-separated
            formatted = ';'.join(ranges)

            return JsonResponse({
                'success': True,
                'total_ranges': len(ranges),
                'ranges': ranges,
                'formatted': formatted
            })

        finally:
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Extraction failed: {str(e)}'
        }, status=500)


@require_POST
@csrf_exempt
@login_required
def unified_process_preview(request):
    """
    Step 1: Preview - Extract metadata from Word document
    Returns: Patient name, statements count, page ranges for verification
    """
    try:
        if 'word_file' not in request.FILES or 'pdf_file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'Both Word and PDF files are required'
            }, status=400)

        word_file = request.FILES['word_file']
        pdf_file = request.FILES['pdf_file']

        # Validate file types
        if not word_file.name.endswith('.docx'):
            return JsonResponse({
                'success': False,
                'error': 'Word file must be .docx format'
            }, status=400)

        if not pdf_file.name.endswith('.pdf'):
            return JsonResponse({
                'success': False,
                'error': 'PDF file must be .pdf format'
            }, status=400)

        # Save both files temporarily
        word_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.docx')
        for chunk in word_file.chunks():
            word_temp.write(chunk)
        word_temp.close()
        word_path = word_temp.name

        pdf_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        for chunk in pdf_file.chunks():
            pdf_temp.write(chunk)
        pdf_temp.close()
        pdf_path = pdf_temp.name

        try:
            # Extract page ranges from Word
            processor = WordHyperlinkProcessorSimple()
            ranges = processor.extract_page_ranges_from_file(word_path)

            # Get PDF info
            total_pages = get_pdf_page_count(pdf_path)

            # Extract patient name from Word
            from docx import Document
            doc = Document(word_path)
            patient_name = processor.extract_patient_name_from_document(doc)

            # Format ranges for split
            formatted_ranges = ';'.join(ranges)

            # Generate session ID for temporary storage
            session_id = uuid.uuid4().hex

            # Store file paths in session or temp directory with session ID
            from django.conf import settings
            session_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'sessions', session_id)
            os.makedirs(session_dir, exist_ok=True)

            # Move temp files to session directory
            import shutil
            session_word_path = os.path.join(session_dir, 'input.docx')
            session_pdf_path = os.path.join(session_dir, 'input.pdf')
            shutil.move(word_path, session_word_path)
            shutil.move(pdf_path, session_pdf_path)

            # Store metadata
            metadata = {
                'word_path': session_word_path,
                'pdf_path': session_pdf_path,
                'patient_name': patient_name or 'Unknown',
                'total_statements': len(ranges),
                'page_ranges': ranges,
                'formatted_ranges': formatted_ranges,
                'pdf_total_pages': total_pages,
                'word_filename': word_file.name,
                'pdf_filename': pdf_file.name
            }

            import json
            with open(os.path.join(session_dir, 'metadata.json'), 'w') as f:
                json.dump(metadata, f)

            return JsonResponse({
                'success': True,
                'session_id': session_id,
                'patient_name': patient_name or 'Unknown',
                'total_statements': len(ranges),
                'page_ranges': ranges,
                'formatted_ranges': formatted_ranges,
                'pdf_total_pages': total_pages,
                'word_filename': word_file.name,
                'pdf_filename': pdf_file.name
            })

        except Exception as e:
            # Cleanup on error
            if os.path.exists(word_path):
                os.unlink(word_path)
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
            raise

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Preview failed: {str(e)}'
        }, status=500)


def progress_generator(session_id, patient_name_override, user=None):
    """Generator function that yields progress updates"""
    import json
    from django.conf import settings
    from pathlib import Path
    import time

    run = None
    split_step = None
    upload_step = None
    word_step = None

    def send_progress(status, message, progress=None):
        """Send progress update as JSON"""
        data = {'status': status, 'message': message}
        if progress is not None:
            data['progress'] = progress
        return f"data: {json.dumps(data)}\n\n"

    try:
        yield send_progress('info', 'Loading session...', 5)

        # Load session metadata
        session_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'sessions', session_id)
        metadata_path = os.path.join(session_dir, 'metadata.json')

        if not os.path.exists(metadata_path):
            yield send_progress('error', 'Session not found or expired')
            return

        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

        word_path = metadata['word_path']
        pdf_path = metadata['pdf_path']
        page_ranges = metadata['page_ranges']
        patient_name = patient_name_override if patient_name_override else metadata['patient_name']

        # Normalize patient name
        patient_name_key = patient_name.title().replace(' ', '_')

        run = get_or_create_run(job_id=session_id, run_mode='SYNC', user=user, patient_name=patient_name_key)
        run.input_docx_name = metadata.get('word_filename') or ''
        run.input_pdf_name = metadata.get('pdf_filename') or ''
        try:
            run.input_docx_size_bytes = os.path.getsize(word_path) if word_path and os.path.exists(word_path) else None
        except Exception:
            run.input_docx_size_bytes = None
        try:
            run.input_pdf_size_bytes = os.path.getsize(pdf_path) if pdf_path and os.path.exists(pdf_path) else None
        except Exception:
            run.input_pdf_size_bytes = None
        run.page_count_total = metadata.get('pdf_total_pages')
        run.outputs_requested = len(page_ranges or [])
        run.save(update_fields=[
            'patient_name',
            'input_docx_name',
            'input_pdf_name',
            'input_docx_size_bytes',
            'input_pdf_size_bytes',
            'page_count_total',
            'outputs_requested',
        ])

        yield send_progress('info', f'Patient: {patient_name_key}', 10)

        # Step 1: Split PDF
        yield send_progress('info', 'Preparing to split PDF...', 15)

        split_step = start_step(run, 'SPLIT', extra={'session_id': session_id})

        split_dir = os.path.join(session_dir, 'splits')
        os.makedirs(split_dir, exist_ok=True)

        # Parse page ranges and split
        ranges_text = ';'.join(page_ranges)
        groups = _parse_split_groups(ranges_text)

        yield send_progress('info', f'Splitting PDF into {len(groups)} files...', 20)

        split_files = []
        for i, grp in enumerate(groups, 1):
            label = grp['label']
            segments = grp['segments']

            yield send_progress('info', f'Splitting: {label}.pdf ({i}/{len(groups)})', 20 + (30 * i / len(groups)))

            out_name = f"{label}.pdf"
            out_path = os.path.join(split_dir, out_name)
            merge_pdf_segments(pdf_path, out_path, segments)
            split_files.append({'filename': out_name, 'path': out_path, 'label': label})

        yield send_progress('success', f'Split complete: {len(split_files)} files created', 50)

        finish_step(split_step, status='SUCCESS', count_total=len(groups), count_done=len(split_files), count_failed=0)

        # Step 2: Upload split PDFs to Drive
        yield send_progress('info', 'Creating patient folder in Drive...', 55)

        upload_step = start_step(run, 'UPLOAD', extra={'session_id': session_id})

        config = FolderStructureConfig.get_active_config()
        if not config.root_folder_id:
            yield send_progress('error', 'Drive root folder ID is not configured')
            finish_step(upload_step, status='FAILED', error_message='Drive root folder ID is not configured')
            finish_run(run, status='FAILED', error_message='Drive root folder ID is not configured')
            return

        # Create patient folder
        relative_path = config.get_path_for_patient(patient_name_key)
        resolver = DrivePathResolver(root_folder_id=config.root_folder_id)
        drive_folder_id = resolver.resolve_path(relative_path, create_if_missing=True)

        if not drive_folder_id:
            yield send_progress('error', 'Failed to create patient folder in Drive')
            finish_step(upload_step, status='FAILED', error_message='Failed to create patient folder in Drive')
            finish_run(run, status='FAILED', error_message='Failed to create patient folder in Drive')
            return

        yield send_progress('success', f'Patient folder created', 60)
        yield send_progress('info', f'Uploading {len(split_files)} PDFs to Drive (parallel)...', 60)

        # Bridge SYNC flow -> ASYNC upload pipeline:
        # upload_split_job expects split PDFs under MEDIA_ROOT/processing/splits/<job_id>/
        job_id = session_id
        split_job_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'splits' / job_id
        split_job_dir.mkdir(parents=True, exist_ok=True)
        for it in split_files:
            try:
                src = Path(it['path'])
                dst = split_job_dir / src.name
                if src.exists() and not dst.exists():
                    import shutil
                    shutil.copyfile(str(src), str(dst))
            except Exception:
                pass

        from processing.tasks import upload_split_job
        upload_split_job.delay(job_id, patient_name_key, 25)

        # Poll upload state written by Celery until completion.
        upload_state_path = Path(settings.MEDIA_ROOT) / 'processing' / 'uploads' / job_id / 'state.json'
        upload_manifest_path = Path(settings.MEDIA_ROOT) / 'processing' / 'uploads' / job_id / 'manifest.json'
        last_progress = -1
        while True:
            if upload_state_path.exists():
                try:
                    with open(upload_state_path, 'r', encoding='utf-8') as f:
                        up_state = json.load(f)
                except Exception:
                    up_state = {}

                status = (up_state.get('status') or 'RUNNING').upper()
                progress = int(up_state.get('progress') or 0)
                counts = up_state.get('counts') or {}
                done = int(counts.get('done') or 0)
                total = int(counts.get('total') or 0)
                failed = int(counts.get('failed') or 0)

                if progress != last_progress:
                    last_progress = progress
                    yield send_progress('info', f'Uploading to Drive: {done}/{total} done ({failed} failed)', 60 + int(20 * (progress / 100)))

                if status in {'SUCCESS', 'PARTIAL_SUCCESS', 'FAILED'}:
                    if status == 'FAILED':
                        msg = up_state.get('error') or 'Drive upload failed'
                        yield send_progress('error', msg)
                        finish_step(upload_step, status='FAILED', error_message=msg)
                        finish_run(run, status='FAILED', error_message=msg)
                        return
                    break

            time.sleep(1.0)

        # Read uploaded file results for UI output (best-effort)
        uploaded_pdfs = []
        try:
            upload_files_dir = Path(settings.MEDIA_ROOT) / 'processing' / 'uploads' / job_id / 'files'
            if upload_files_dir.exists():
                for p in sorted(upload_files_dir.iterdir()):
                    if p.is_file() and p.suffix.lower() == '.json':
                        try:
                            with open(p, 'r', encoding='utf-8') as f:
                                rec = json.load(f)
                            if rec.get('status') == 'SUCCESS':
                                uploaded_pdfs.append({
                                    'filename': rec.get('filename'),
                                    'file_id': rec.get('file_id'),
                                    'webViewLink': rec.get('webViewLink'),
                                })
                        except Exception:
                            continue

            if upload_manifest_path.exists():
                with open(upload_manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                drive_folder_id = manifest.get('drive_folder_id') or drive_folder_id
        except Exception:
            pass

        yield send_progress('success', f'Upload complete (parallel)', 80)
        finish_step(upload_step, status='SUCCESS', count_total=len(split_files), count_done=len(uploaded_pdfs), count_failed=0)

        # Step 3: Get PDFs from Drive folder and process Word document
        yield send_progress('info', 'Fetching PDF links from Drive...', 82)

        word_step = start_step(run, 'WORD_PROCESS', extra={'session_id': session_id})

        processor = WordHyperlinkProcessorSimple()
        pdf_links = processor.get_pdfs_from_drive_folder(drive_folder_id)

        yield send_progress('info', 'Processing Word document...', 85)
        yield send_progress('info', 'Inserting hyperlinks...', 87)

        # Process Word document
        output_filename = metadata['word_filename'].replace('.docx', '_PROCESSED.docx')
        output_path = os.path.join(session_dir, output_filename)

        result = processor.process_word_document(
            input_docx_path=word_path,
            pdf_links=pdf_links,
            output_docx_path=output_path
        )

        yield send_progress('success', f'Links inserted: {result["linked_statements"]}/{result["total_statements"]}', 92)

        finish_step(
            word_step,
            status='SUCCESS',
            count_total=int(result.get('total_statements') or 0),
            count_done=int(result.get('linked_statements') or 0),
            count_failed=int(result.get('unlinked_statements') or 0),
        )

        # Move output to downloads location
        yield send_progress('info', 'Preparing download...', 95)

        from datetime import datetime
        downloads_dir = os.path.join(settings.MEDIA_ROOT, 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)

        final_filename = f"{patient_name_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_PROCESSED.docx"
        final_path = os.path.join(downloads_dir, final_filename)
        import shutil
        shutil.copy(output_path, final_path)

        # Generate download URL
        relative_download_path = os.path.join('downloads', final_filename)
        download_url = f"{settings.MEDIA_URL}{relative_download_path}"

        # Send final result
        original_pdf = metadata.get('pdf_filename') or (os.path.basename(pdf_path) if pdf_path else '')
        final_data = {
            'status': 'complete',
            'message': 'Processing complete!',
            'progress': 100,
            'result': {
                'success': True,
                'patient_name': patient_name_key,
                'drive_folder_id': drive_folder_id,
                'total_splits': len(split_files),
                'original_pdf': original_pdf,
                'uploaded_pdfs': uploaded_pdfs,
                'word_result': {
                    'total_statements': result['total_statements'],
                    'linked_statements': result['linked_statements'],
                    'unlinked_statements': result['unlinked_statements'],
                    'success_rate': round(result['linked_statements'] / result['total_statements'] * 100) if result['total_statements'] > 0 else 0
                },
                'download_url': download_url,
                'output_filename': final_filename
            }
        }
        yield f"data: {json.dumps(final_data)}\n\n"

        finish_run(
            run,
            status='SUCCESS',
            extra={
                'drive_folder_id': drive_folder_id,
                'total_splits': len(split_files),
                'word_result': {
                    'total_statements': int(result.get('total_statements') or 0),
                    'linked_statements': int(result.get('linked_statements') or 0),
                    'unlinked_statements': int(result.get('unlinked_statements') or 0),
                },
            },
        )

    except Exception as e:
        import traceback
        if word_step is not None and getattr(word_step, 'status', None) == 'RUNNING':
            finish_step(word_step, status='FAILED', error_message=str(e))
        if upload_step is not None and getattr(upload_step, 'status', None) == 'RUNNING':
            finish_step(upload_step, status='FAILED', error_message=str(e))
        if split_step is not None and getattr(split_step, 'status', None) == 'RUNNING':
            finish_step(split_step, status='FAILED', error_message=str(e))
        if run is not None:
            finish_run(run, status='FAILED', error_message=str(e))
        error_data = {
            'status': 'error',
            'message': f'Processing failed: {str(e)}',
            'traceback': traceback.format_exc()
        }
        yield f"data: {json.dumps(error_data)}\n\n"


@require_POST
@csrf_exempt
@login_required
def unified_process_complete(request):
    """
    Step 2: Complete Processing with real-time progress updates
    Returns: Streaming response with progress updates
    """
    try:
        session_id = request.POST.get('session_id')
        patient_name_override = request.POST.get('patient_name', '').strip()

        if not session_id:
            return JsonResponse({
                'success': False,
                'error': 'Session ID is required'
            }, status=400)

        # Return streaming response with real-time progress
        from django.http import StreamingHttpResponse

        response = StreamingHttpResponse(
            progress_generator(session_id, patient_name_override, user=request.user),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'

        return response

    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': f'Processing failed: {str(e)}',
            'traceback': traceback.format_exc()
        }, status=500)


@require_http_methods(["GET"])
@login_required
def download_split_zip(request, job_id: str):
    """Download all split PDFs for a job as a single zip."""
    try:
        from django.conf import settings
        base_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'splits', job_id)
        if not os.path.isdir(base_dir):
            return JsonResponse({'success': False, 'error': 'Split job not found'}, status=404)

        pdf_files = [f for f in os.listdir(base_dir) if f.lower().endswith('.pdf') and f.lower() != 'original.pdf']
        if not pdf_files:
            return JsonResponse({'success': False, 'error': 'No split PDFs found'}, status=404)

        tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        tmp_zip_path = tmp_zip.name
        tmp_zip.close()

        try:
            with zipfile.ZipFile(tmp_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                for name in sorted(pdf_files):
                    full_path = os.path.join(base_dir, name)
                    zf.write(full_path, arcname=name)

            resp = FileResponse(open(tmp_zip_path, 'rb'), content_type='application/zip')
            resp['Content-Disposition'] = f'attachment; filename="splits_{job_id}.zip"'
            return resp
        finally:
            try:
                os.unlink(tmp_zip_path)
            except Exception:
                pass

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
