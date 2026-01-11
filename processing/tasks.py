"""
Celery tasks for async PDF processing
"""
from celery import shared_task
from django.conf import settings
from pathlib import Path
from datetime import datetime
import os

from pdfs.models import PDFSet, DriveFolderCache
from .pdf_utils import split_pdf, create_folder_structure
from .drive_utils import get_drive_service


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
