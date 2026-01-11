"""
Django Views for Word Document Hyperlink Processing
API endpoints for the production workflow
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.core.files.storage import default_storage
from django.conf import settings
from django.shortcuts import render
from pathlib import Path
import tempfile
import os

from .word_hyperlink_processor import WordHyperlinkProcessor
from .word_hyperlink_processor_enhanced import WordHyperlinkProcessorEnhanced
from .drive_url_utils import extract_drive_id


def word_hyperlink_ui(request):
    """
    Render the Word Hyperlink Processor UI
    Modern interface supporting three input methods:
    1. Patient Name (automatic folder resolution)
    2. Drive Path (readable path)
    3. Folder ID (traditional method)
    """
    return render(request, 'word_hyperlink_processor.html')


@api_view(['POST'])
def process_word_with_hyperlinks(request):
    """
    API Endpoint: Process Word document with PDF hyperlinks

    Request Body (JSON):
    {
        "drive_folder_id": "1ABC...",  # Google Drive folder ID containing PDFs
        "word_file_id": "1XYZ...",     # Google Drive ID of Word document
        "output_folder_id": "1ABC..."  # Optional: Drive folder for output (defaults to input folder)
    }

    OR (NEW: Using Paths)

    {
        "drive_folder_path": "2025/December/Carl_Mayfield/splits",  # Drive path instead of ID
        "word_file_id": "1XYZ...",
        "output_folder_path": "2025/December/Carl_Mayfield"  # Optional
    }

    OR (NEW: Patient-based)

    {
        "patient_name": "Carl_Mayfield",  # System finds folder automatically
        "word_file_id": "1XYZ...",
        "year": "2025",          # Optional: defaults to current
        "month": "December"      # Optional: defaults to current
    }

    OR (Upload)

    {
        "drive_folder_id": "1ABC...",  # Google Drive folder to upload PDFs and output
        "word_file": <uploaded file>,  # Word document uploaded via form
        "pdf_folder": <folder path>    # Local folder with PDFs (optional, for local upload)
    }

    Response:
    {
        "success": true,
        "message": "Word document processed successfully",
        "statistics": {
            "total_statements": 10,
            "linked_statements": 8,
            "unlinked_statements": 2,
            "pdf_count": 9,
            "success_rate": 80.0
        },
        "output": {
            "file_id": "1XYZ...",
            "webview_link": "https://drive.google.com/...",
            "filename": "document.docx"
        },
        "details": [
            {
                "page_range": "3-4",
                "text": "Statement text...",
                "status": "linked",
                "drive_link": "https://..."
            },
            ...
        ]
    }
    """
    try:
        # Check if Word file was uploaded
        word_file = request.FILES.get('word_file')
        word_file_id = request.data.get('word_file_id')

        # Extract ID from URL if it's a URL
        if word_file_id:
            word_file_id = extract_drive_id(word_file_id)

        # If file uploaded, we need to upload it to Drive first
        temp_word_file_id = None
        if word_file:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_word:
                for chunk in word_file.chunks():
                    temp_word.write(chunk)
                temp_word_path = temp_word.name

            try:
                # Upload to Drive - we need a folder to upload to
                # For now, we'll use a temp location or the patient folder if we can resolve it
                from .drive_utils import DriveService
                from .drive_path_resolver import StandardDriveStructure
                from django.conf import settings

                drive_service = DriveService()

                # Try to determine upload folder
                patient_name = request.data.get('patient_name')
                if patient_name:
                    # Upload to patient folder
                    structure = StandardDriveStructure()
                    year = request.data.get('year')
                    month = request.data.get('month')

                    if not year or not month:
                        from datetime import datetime
                        now = datetime.now()
                        year = year or str(now.year)
                        month = month or now.strftime('%B')

                    folders = structure.get_or_create_patient_structure(year, month, patient_name)
                    upload_folder_id = folders['patient_folder_id']
                else:
                    # Use root folder from settings or first provided folder
                    upload_folder_id = getattr(settings, 'GOOGLE_DRIVE_ROOT_FOLDER_ID', None)
                    if not upload_folder_id:
                        upload_folder_id = request.data.get('drive_folder_id') or request.data.get('output_folder_id')

                if not upload_folder_id:
                    raise Exception("Cannot determine upload folder. Please provide patient_name or drive_folder_id")

                # Upload file to Drive
                temp_word_file_id, _ = drive_service.upload_file(
                    temp_word_path,
                    upload_folder_id,
                    word_file.name
                )

                # Use this file ID for processing
                word_file_id = temp_word_file_id

            finally:
                # Clean up temp file
                if os.path.exists(temp_word_path):
                    os.unlink(temp_word_path)

        # Check if using patient-based workflow
        patient_name = request.data.get('patient_name')

        if patient_name and word_file_id:
            # Workflow: Patient-based (automatic folder resolution)
            processor = WordHyperlinkProcessorEnhanced()

            year = request.data.get('year')
            month = request.data.get('month')

            with tempfile.TemporaryDirectory() as temp_dir:
                if year and month:
                    result = processor.process_patient_document(
                        patient_name=patient_name,
                        word_file_id=word_file_id,
                        year=year,
                        month=month,
                        temp_dir=temp_dir
                    )
                else:
                    result = processor.process_patient_document_auto(
                        patient_name=patient_name,
                        word_file_id=word_file_id,
                        temp_dir=temp_dir
                    )

            return Response({
                'success': True,
                'message': 'Word document processed successfully',
                'statistics': {
                    'total_statements': result['total_statements'],
                    'linked_statements': result['linked_statements'],
                    'unlinked_statements': result['unlinked_statements'],
                    'pdf_count': result.get('pdf_count', 0),
                    'success_rate': round(
                        (result['linked_statements'] / max(result['total_statements'], 1)) * 100,
                        2
                    )
                },
                'output': {
                    'file_id': result.get('output_file_id'),
                    'webview_link': result.get('output_webview_link'),
                    'filename': 'processed_document.docx'
                },
                'details': result.get('statements', [])
            }, status=status.HTTP_200_OK)

        # Check if using path-based workflow
        drive_folder_path = request.data.get('drive_folder_path')

        if drive_folder_path and word_file_id:
            # Workflow: Path-based
            processor = WordHyperlinkProcessorEnhanced()
            output_folder_path = request.data.get('output_folder_path')

            with tempfile.TemporaryDirectory() as temp_dir:
                result = processor.process_with_path(
                    drive_folder_path=drive_folder_path,
                    word_file_id=word_file_id,
                    output_folder_path=output_folder_path,
                    temp_dir=temp_dir
                )

            return Response({
                'success': True,
                'message': 'Word document processed successfully',
                'statistics': {
                    'total_statements': result['total_statements'],
                    'linked_statements': result['linked_statements'],
                    'unlinked_statements': result['unlinked_statements'],
                    'pdf_count': result.get('pdf_count', 0),
                    'success_rate': round(
                        (result['linked_statements'] / max(result['total_statements'], 1)) * 100,
                        2
                    )
                },
                'output': {
                    'file_id': result.get('output_file_id'),
                    'webview_link': result.get('output_webview_link'),
                    'filename': 'processed_document.docx'
                },
                'details': result.get('statements', [])
            }, status=status.HTTP_200_OK)

        # Check if it's a Drive-to-Drive workflow (with IDs)
        processor = WordHyperlinkProcessor()
        drive_folder_id = request.data.get('drive_folder_id')
        output_folder_id = request.data.get('output_folder_id')

        # Extract IDs from URLs if needed
        if drive_folder_id:
            drive_folder_id = extract_drive_id(drive_folder_id)
        if output_folder_id:
            output_folder_id = extract_drive_id(output_folder_id)

        if drive_folder_id and word_file_id:
            # Workflow 1: Drive folder with PDFs + Drive Word document
            with tempfile.TemporaryDirectory() as temp_dir:
                result = processor.process_from_drive_folder(
                    drive_folder_id=drive_folder_id,
                    word_file_id=word_file_id,
                    output_folder_id=output_folder_id,
                    temp_dir=temp_dir
                )

            return Response({
                'success': True,
                'message': 'Word document processed successfully',
                'statistics': {
                    'total_statements': result['total_statements'],
                    'linked_statements': result['linked_statements'],
                    'unlinked_statements': result['unlinked_statements'],
                    'pdf_count': result.get('pdf_count', 0),
                    'success_rate': round(
                        (result['linked_statements'] / max(result['total_statements'], 1)) * 100,
                        2
                    )
                },
                'output': {
                    'file_id': result.get('output_file_id'),
                    'webview_link': result.get('output_webview_link'),
                    'filename': 'processed_document.docx'
                },
                'details': result.get('statements', [])
            }, status=status.HTTP_200_OK)

        # Check if it's an upload workflow
        word_file = request.FILES.get('word_file')
        pdf_folder_path = request.data.get('pdf_folder_path')

        if drive_folder_id and word_file:
            # Workflow 2: Uploaded Word file + PDFs in local folder or Drive folder

            # Save uploaded Word file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_word:
                for chunk in word_file.chunks():
                    temp_word.write(chunk)
                temp_word_path = temp_word.name

            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_output:
                    temp_output_path = temp_output.name

                # If PDFs are in a local folder, upload them first
                if pdf_folder_path:
                    result = processor.process_local_workflow(
                        word_file_path=temp_word_path,
                        pdf_folder_path=pdf_folder_path,
                        output_word_path=temp_output_path,
                        upload_to_drive=True,
                        drive_folder_id=drive_folder_id
                    )
                else:
                    # PDFs are already in the Drive folder
                    # Get PDFs from Drive
                    pdf_links = processor.get_pdfs_from_drive_folder(drive_folder_id)

                    # Process document
                    result = processor.process_word_document(
                        temp_word_path,
                        pdf_links,
                        temp_output_path
                    )

                    # Upload processed document
                    output_file_id, output_webview_link = processor.upload_processed_word_to_drive(
                        temp_output_path,
                        drive_folder_id,
                        filename=word_file.name
                    )

                    result['output_file_id'] = output_file_id
                    result['output_webview_link'] = output_webview_link
                    result['pdf_count'] = len(pdf_links)

                return Response({
                    'success': True,
                    'message': 'Word document processed successfully',
                    'statistics': {
                        'total_statements': result['total_statements'],
                        'linked_statements': result['linked_statements'],
                        'unlinked_statements': result['unlinked_statements'],
                        'pdf_count': result.get('pdf_count', 0),
                        'success_rate': round(
                            (result['linked_statements'] / max(result['total_statements'], 1)) * 100,
                            2
                        )
                    },
                    'output': {
                        'file_id': result.get('output_file_id'),
                        'webview_link': result.get('output_webview_link'),
                        'filename': word_file.name
                    },
                    'details': result.get('statements', [])
                }, status=status.HTTP_200_OK)

            finally:
                # Cleanup
                if os.path.exists(temp_word_path):
                    os.unlink(temp_word_path)
                if os.path.exists(temp_output_path):
                    os.unlink(temp_output_path)

        return Response({
            'success': False,
            'error': 'Invalid request. Provide either (drive_folder_id + word_file_id) or (drive_folder_id + word_file)'
        }, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        error_msg = str(e)
        if "No PDF files found" in error_msg:
            return Response({
                'success': False,
                'error': f"{error_msg}. Please ensure you have run the PDF Splitter for the target folder first."
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_drive_folder_pdfs(request):
    """
    API Endpoint: List PDFs in a Google Drive folder

    Query Parameters:
    - folder_id: Google Drive folder ID

    Response:
    {
        "success": true,
        "pdf_count": 9,
        "pdfs": [
            {
                "page_range": "3-4",
                "filename": "3-4.pdf",
                "webview_link": "https://..."
            },
            ...
        ]
    }
    """
    try:
        folder_id = request.query_params.get('folder_id')

        if not folder_id:
            return Response({
                'success': False,
                'error': 'folder_id parameter required'
            }, status=status.HTTP_400_BAD_REQUEST)

        processor = WordHyperlinkProcessor()
        pdf_links = processor.get_pdfs_from_drive_folder(folder_id)

        pdfs = [
            {
                'page_range': page_range,
                'filename': f"{page_range}.pdf",
                'webview_link': link
            }
            for page_range, link in pdf_links.items()
        ]

        return Response({
            'success': True,
            'pdf_count': len(pdfs),
            'pdfs': pdfs
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def upload_word_to_drive(request):
    """
    API Endpoint: Upload Word document to Google Drive

    Request Body (multipart/form-data):
    - word_file: Word document file
    - folder_id: Google Drive folder ID

    Response:
    {
        "success": true,
        "file_id": "1XYZ...",
        "webview_link": "https://...",
        "filename": "document.docx"
    }
    """
    try:
        word_file = request.FILES.get('word_file')
        folder_id = request.data.get('folder_id')

        if not word_file or not folder_id:
            return Response({
                'success': False,
                'error': 'word_file and folder_id required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Save temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
            for chunk in word_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name

        try:
            processor = WordHyperlinkProcessor()
            file_id, webview_link = processor.upload_processed_word_to_drive(
                temp_path,
                folder_id,
                filename=word_file.name
            )

            return Response({
                'success': True,
                'file_id': file_id,
                'webview_link': webview_link,
                'filename': word_file.name
            }, status=status.HTTP_200_OK)

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
