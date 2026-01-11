from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.files.storage import default_storage
from pathlib import Path
import json
from datetime import datetime

from .models import Patient, OriginalPDF, PDFSet, SummaryDocument
from processing.pdf_utils import (
    compute_sha256, get_pdf_page_count, 
    detect_section_boundaries, extract_text_from_page
)
from processing.tasks import process_pdf_set
from processing.docx_utils import generate_patient_summary


def index(request):
    """Main dashboard view"""
    context = {
        'total_pdfs': OriginalPDF.objects.count(),
        'total_patients': Patient.objects.count(),
        'total_sets': PDFSet.objects.count(),
        'uploaded_sets': PDFSet.objects.filter(state='UPLOADED').count(),
    }
    return render(request, 'index.html', context)


@csrf_exempt
def upload_pdf(request):
    """Upload original PDF"""
    if request.method == 'POST' and request.FILES.get('pdf_file'):
        pdf_file = request.FILES['pdf_file']
        
        # Save file temporarily
        file_path = default_storage.save(
            f'originals/{datetime.now().strftime("%Y/%m/%d")}/{pdf_file.name}',
            pdf_file
        )
        full_path = Path(settings.MEDIA_ROOT) / file_path
        
        # Compute hash and page count
        sha256 = compute_sha256(str(full_path))
        total_pages = get_pdf_page_count(str(full_path))
        
        # Check if already exists
        existing = OriginalPDF.objects.filter(sha256=sha256).first()
        if existing:
            return JsonResponse({
                'status': 'duplicate',
                'message': 'This PDF has already been uploaded',
                'pdf_id': existing.id
            })
        
        # Create OriginalPDF record
        original_pdf = OriginalPDF.objects.create(
            filename=pdf_file.name,
            file_path=file_path,
            sha256=sha256,
            total_pages=total_pages
        )
        
        return JsonResponse({
            'status': 'success',
            'pdf_id': original_pdf.id,
            'filename': original_pdf.filename,
            'total_pages': total_pages
        })
    
    return JsonResponse({'status': 'error', 'message': 'No file uploaded'}, status=400)


def auto_detect(request, pdf_id):
    """Auto-detect patient sections in PDF"""
    original_pdf = get_object_or_404(OriginalPDF, id=pdf_id)
    
    # Run detection
    sections = detect_section_boundaries(original_pdf.file_path.path)
    
    return JsonResponse({
        'status': 'success',
        'sections': sections,
        'total_sections': len(sections)
    })


def get_pdf_pages(request, pdf_id):
    """Get page previews and text for a PDF"""
    original_pdf = get_object_or_404(OriginalPDF, id=pdf_id)
    
    pages = []
    for page_num in range(min(original_pdf.total_pages, 10)):  # Limit to first 10 pages
        text = extract_text_from_page(original_pdf.file_path.path, page_num)
        # Get first 200 characters
        preview = text[:200] + '...' if len(text) > 200 else text
        
        pages.append({
            'page_number': page_num + 1,
            'preview_text': preview
        })
    
    return JsonResponse({
        'status': 'success',
        'pages': pages,
        'total_pages': original_pdf.total_pages
    })


@csrf_exempt
def create_pdf_sets(request):
    """Create PDF sets from detected sections"""
    if request.method == 'POST':
        data = json.loads(request.body)
        pdf_id = data.get('pdf_id')
        sections = data.get('sections', [])
        
        original_pdf = get_object_or_404(OriginalPDF, id=pdf_id)
        created_sets = []
        
        for section in sections:
            patient_info = section.get('patient_info', {})

            # Get or create patient
            patient, created = Patient.objects.get_or_create(
                patient_id=patient_info.get('patient_id', f'AUTO_{datetime.now().timestamp()}'),
                defaults={
                    'name': patient_info.get('name', 'Unknown'),
                    'address': patient_info.get('address', ''),
                    'contact': patient_info.get('contact', '')
                }
            )

            # Parse date
            date_str = patient_info.get('date', '')
            try:
                date_obj = datetime.strptime(date_str, '%m/%d/%Y').date()
            except:
                date_obj = datetime.now().date()

            # Extract section type and doctor name from section (added by detect_section_boundaries)
            section_type = section.get('section_type', 'Medical_Records')
            doctor_name = section.get('doctor_name', '')  # Will be extracted during processing if not available

            # Create PDF set
            pdf_set = PDFSet.objects.create(
                patient=patient,
                original_pdf=original_pdf,
                start_page=section.get('start_page'),
                end_page=section.get('end_page'),
                date=date_obj,
                hospital=section.get('hospital', 'Unknown Hospital'),
                section_type=section_type,
                doctor_name=doctor_name,
                state='PENDING'
            )
            
            created_sets.append({
                'id': pdf_set.id,
                'patient_name': patient.name,
                'pages': f"{pdf_set.start_page}-{pdf_set.end_page}"
            })
        
        return JsonResponse({
            'status': 'success',
            'created_sets': created_sets,
            'count': len(created_sets)
        })
    
    return JsonResponse({'status': 'error'}, status=400)


@csrf_exempt
def process_set(request, set_id):
    """Trigger processing of a PDF set"""
    pdf_set = get_object_or_404(PDFSet, id=set_id)
    
    # Enqueue Celery task
    task = process_pdf_set.delay(set_id)
    
    return JsonResponse({
        'status': 'queued',
        'task_id': task.id,
        'set_id': set_id
    })


def get_set_status(request, set_id):
    """Get processing status of a PDF set"""
    pdf_set = get_object_or_404(PDFSet, id=set_id)
    
    return JsonResponse({
        'status': 'success',
        'set_id': set_id,
        'state': pdf_set.state,
        'drive_link': pdf_set.drive_webview_link,
        'error': pdf_set.error_message
    })


@csrf_exempt
def generate_summary(request, patient_id):
    """Generate Word document summary for a patient"""
    patient = get_object_or_404(Patient, patient_id=patient_id)
    
    # Get all uploaded PDF sets for this patient
    pdf_sets = PDFSet.objects.filter(
        patient=patient,
        state='UPLOADED'
    ).order_by('date')
    
    if not pdf_sets.exists():
        return JsonResponse({
            'status': 'error',
            'message': 'No uploaded PDF sets found for this patient'
        }, status=400)
    
    # Generate summary document
    output_dir = Path(settings.MEDIA_ROOT) / 'summaries'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    doc_path = generate_patient_summary(patient, pdf_sets, str(output_dir))
    
    # Create SummaryDocument record
    summary = SummaryDocument.objects.create(
        patient=patient,
        file_path=doc_path
    )
    summary.pdf_sets_included.set(pdf_sets)
    
    # Get relative path for URL
    relative_path = Path(doc_path).relative_to(settings.MEDIA_ROOT)
    download_url = f"{settings.MEDIA_URL}{relative_path}"
    
    return JsonResponse({
        'status': 'success',
        'summary_id': summary.id,
        'download_url': download_url,
        'file_path': doc_path
    })


def list_patients(request):
    """List all patients with their PDF sets"""
    patients = Patient.objects.all().prefetch_related('pdf_sets')

    data = []
    for patient in patients:
        sets = patient.pdf_sets.all()
        data.append({
            'patient_id': patient.patient_id,
            'name': patient.name,
            'address': patient.address,
            'contact': patient.contact,
            'total_sets': sets.count(),
            'uploaded_sets': sets.filter(state='UPLOADED').count()
        })

    return JsonResponse({
        'status': 'success',
        'patients': data
    })


@csrf_exempt
def link_word_document(request):
    """
    Upload a Word document and attach Drive links to medical statements
    NEW WORKFLOW: Reverse linking - finds PDFs based on statements in Word doc
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=400)

    try:
        if 'word_file' not in request.FILES:
            return JsonResponse({'status': 'error', 'message': 'No word_file provided'}, status=400)

        word_file = request.FILES['word_file']
        patient_name = request.POST.get('patient_name', '')

        # Save uploaded file temporarily
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_input:
            for chunk in word_file.chunks():
                tmp_input.write(chunk)
            input_path = tmp_input.name

        from processing.word_parser import process_word_document_with_links

        output_dir = Path(settings.MEDIA_ROOT) / 'linked_documents'
        output_dir.mkdir(parents=True, exist_ok=True)

        output_filename = f"linked_{word_file.name}"
        output_path = output_dir / output_filename

        stats = process_word_document_with_links(
            input_path,
            str(output_path),
            patient_name=patient_name if patient_name else None
        )

        import os
        os.unlink(input_path)

        relative_path = output_path.relative_to(Path(settings.MEDIA_ROOT))
        download_url = f"{settings.MEDIA_URL}{relative_path}"

        return JsonResponse({
            'status': 'success',
            'patient_name': stats['patient_name'],
            'total_statements': stats['total_statements'],
            'linked_statements': stats['linked_statements'],
            'unlinked_statements': stats['unlinked_statements'],
            'download_url': download_url,
            'file_path': str(output_path),
            'statements': stats['statements']
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
