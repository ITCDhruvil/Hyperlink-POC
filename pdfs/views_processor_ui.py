"""
Simple 2-Column Processor UI
Left: Upload & Display | Right: Results & Download
"""
from django.shortcuts import render
from django.http import JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.files.base import ContentFile
from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view
import time
import os
import tempfile
import re
import uuid
import zipfile
from datetime import datetime

from .models import ProcessingHistory, FolderStructureConfig
from processing.smart_folder_detector_configurable import SmartFolderDetectorConfigurable
from processing.word_hyperlink_processor_simple import WordHyperlinkProcessorSimple
from processing.pdf_utils import get_pdf_page_count, split_pdf, merge_pdf_segments
from processing.drive_path_resolver import DrivePathResolver
from processing.drive_utils import get_drive_service


@login_required
def processor_ui(request):
    """Main UI page with 2-column layout"""
    return render(request, 'pdfs/processor_ui.html')


@api_view(['GET'])
@login_required
def processing_history(request):
    """
    Display processing history with pagination
    Shows list of all processed documents with metadata
    """
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

    # Get all processing history, ordered by most recent
    history_list = ProcessingHistory.objects.all().order_by('-uploaded_at')

    # Pagination - 10 items per page
    paginator = Paginator(history_list, 10)
    page = request.GET.get('page', 1)

    try:
        history_items = paginator.page(page)
    except PageNotAnInteger:
        history_items = paginator.page(1)
    except EmptyPage:
        history_items = paginator.page(paginator.num_pages)

    # Get statistics
    total_documents = ProcessingHistory.objects.count()
    successful_documents = ProcessingHistory.objects.filter(status='SUCCESS').count()
    failed_documents = ProcessingHistory.objects.filter(status='FAILED').count()
    pending_documents = ProcessingHistory.objects.filter(status='PENDING').count()

    context = {
        'history_items': history_items,
        'total_documents': total_documents,
        'successful_documents': successful_documents,
        'failed_documents': failed_documents,
        'pending_documents': pending_documents,
        'success_rate': round((successful_documents / total_documents * 100) if total_documents > 0 else 0, 1)
    }

    return render(request, 'pdfs/processing_history.html', context)


@api_view(['POST'])
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


@api_view(['POST'])
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


@api_view(['POST'])
@csrf_exempt
@login_required
def split_pdf_document(request):
    """Upload a PDF and split it into multiple PDFs based on user-provided page ranges."""
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'success': False, 'error': 'No file uploaded'}, status=400)

        uploaded_file = request.FILES['file']
        if not (uploaded_file.name or '').lower().endswith('.pdf'):
            return JsonResponse({'success': False, 'error': 'Please upload a PDF file'}, status=400)

        page_ranges_text = request.POST.get('page_ranges', '')
        try:
            groups = _parse_split_groups(page_ranges_text)
        except ValueError as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

        # Save input PDF to a temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            input_path = tmp.name

        try:
            total_pages = get_pdf_page_count(input_path)

            job_id = uuid.uuid4().hex
            # Store under MEDIA_ROOT so Django can serve it if needed
            from django.conf import settings
            output_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'splits', job_id)
            os.makedirs(output_dir, exist_ok=True)

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
            if os.path.exists(input_path):
                os.unlink(input_path)

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@api_view(['POST'])
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

        pdf_files = [f for f in os.listdir(base_dir) if f.lower().endswith('.pdf')]
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


@api_view(['GET'])
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


@api_view(['POST'])
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


@api_view(['POST'])
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


def progress_generator(session_id, patient_name_override):
    """Generator function that yields progress updates"""
    import json
    from django.conf import settings

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

        yield send_progress('info', f'Patient: {patient_name_key}', 10)

        # Step 1: Split PDF
        yield send_progress('info', 'Preparing to split PDF...', 15)

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

        # Step 2: Upload split PDFs to Drive
        yield send_progress('info', 'Creating patient folder in Drive...', 55)

        config = FolderStructureConfig.get_active_config()
        if not config.root_folder_id:
            yield send_progress('error', 'Drive root folder ID is not configured')
            return

        # Create patient folder
        relative_path = config.get_path_for_patient(patient_name_key)
        resolver = DrivePathResolver(root_folder_id=config.root_folder_id)
        drive_folder_id = resolver.resolve_path(relative_path, create_if_missing=True)

        if not drive_folder_id:
            yield send_progress('error', 'Failed to create patient folder in Drive')
            return

        yield send_progress('success', f'Patient folder created', 60)
        yield send_progress('info', f'Uploading {len(split_files)} PDFs to Drive...', 60)

        # Upload all split PDFs
        drive = get_drive_service()
        uploaded_pdfs = []

        for i, split_file in enumerate(split_files, 1):
            yield send_progress('info', f'Uploading: {split_file["filename"]} ({i}/{len(split_files)})', 60 + (20 * i / len(split_files)))

            file_id, web_view = drive.upload_file(
                split_file['path'],
                drive_folder_id,
                file_name=split_file['filename']
            )
            uploaded_pdfs.append({
                'filename': split_file['filename'],
                'file_id': file_id,
                'webViewLink': web_view,
                'label': split_file['label']
            })

        yield send_progress('success', f'All PDFs uploaded to Drive', 80)

        # Step 3: Get PDFs from Drive folder and process Word document
        yield send_progress('info', 'Fetching PDF links from Drive...', 82)

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
        final_data = {
            'status': 'complete',
            'message': 'Processing complete!',
            'progress': 100,
            'result': {
                'success': True,
                'patient_name': patient_name_key,
                'drive_folder_id': drive_folder_id,
                'total_splits': len(split_files),
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

    except Exception as e:
        import traceback
        error_data = {
            'status': 'error',
            'message': f'Processing failed: {str(e)}',
            'traceback': traceback.format_exc()
        }
        yield f"data: {json.dumps(error_data)}\n\n"


@api_view(['POST'])
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
            progress_generator(session_id, patient_name_override),
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


@api_view(['GET'])
@login_required
def download_split_zip(request, job_id: str):
    """Download all split PDFs for a job as a single zip."""
    try:
        from django.conf import settings
        base_dir = os.path.join(settings.MEDIA_ROOT, 'processing', 'splits', job_id)
        if not os.path.isdir(base_dir):
            return JsonResponse({'success': False, 'error': 'Split job not found'}, status=404)

        pdf_files = [f for f in os.listdir(base_dir) if f.lower().endswith('.pdf')]
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
