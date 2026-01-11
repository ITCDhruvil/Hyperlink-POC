"""
API Endpoints for Folder Structure Configuration

Allows frontend to:
1. View current configuration
2. Update configuration
3. Test configuration with a patient name
"""
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache
from .models import FolderStructureConfig
import json


@api_view(['GET'])
def get_folder_config(request):
    """
    GET /api/folder-config/

    Get current active folder structure configuration
    """
    try:
        config = FolderStructureConfig.get_active_config()

        return Response({
            'success': True,
            'config': {
                'config_name': config.config_name,
                'structure_type': config.structure_type,
                'structure_type_display': config.get_structure_type_display(),
                'root_folder_id': config.root_folder_id,
                'path_template': config.path_template,
                'pdf_subfolder': config.pdf_subfolder,
                'description': config.description,
                'is_active': config.is_active,
            }
        })

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def update_folder_config(request):
    """
    POST /api/folder-config/update/

    Update folder structure configuration

    Request Body:
    {
        "structure_type": "FLAT",  // or "WITH_SPLITS", "YEAR_MONTH", "CUSTOM"
        "root_folder_id": "1GyZj...",
        "pdf_subfolder": "",  // e.g., "splits" or empty
        "path_template": "",  // for CUSTOM type
        "description": "..."
    }
    """
    try:
        # Get or create default config
        config, created = FolderStructureConfig.objects.get_or_create(
            config_name='default',
            defaults={
                'structure_type': 'FLAT',
                'root_folder_id': '',
                'is_active': True
            }
        )

        # Update fields
        if 'structure_type' in request.data:
            config.structure_type = request.data['structure_type']

        if 'root_folder_id' in request.data:
            config.root_folder_id = request.data['root_folder_id']

        if 'pdf_subfolder' in request.data:
            config.pdf_subfolder = request.data['pdf_subfolder']

        if 'path_template' in request.data:
            config.path_template = request.data['path_template']

        if 'description' in request.data:
            config.description = request.data['description']

        config.save()

        # Clear cache
        cache.delete('active_folder_structure_config')

        return Response({
            'success': True,
            'message': 'Configuration updated successfully',
            'config': {
                'config_name': config.config_name,
                'structure_type': config.structure_type,
                'structure_type_display': config.get_structure_type_display(),
                'root_folder_id': config.root_folder_id,
                'pdf_subfolder': config.pdf_subfolder,
                'path_template': config.path_template,
                'description': config.description,
            }
        })

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def test_folder_config(request):
    """
    POST /api/folder-config/test/

    Test configuration with a patient name

    Request Body:
    {
        "patient_name": "Carl_Mayfield",
        "year": "2025",  // optional
        "month": "December"  // optional
    }

    Response:
    {
        "success": true,
        "expected_path": "Carl_Mayfield",
        "folder_found": true,
        "folder_id": "...",
        "pdf_count": 9
    }
    """
    try:
        patient_name = request.data.get('patient_name')

        if not patient_name:
            return Response({
                'success': False,
                'error': 'patient_name required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Get config
        config = FolderStructureConfig.get_active_config()

        # Get expected path
        expected_path = config.get_path_for_patient(
            patient_name,
            year=request.data.get('year', ''),
            month=request.data.get('month', '')
        )

        # Try to find folder
        from processing.smart_folder_detector_configurable import SmartFolderDetectorConfigurable

        detector = SmartFolderDetectorConfigurable(config=config)
        folder_id = detector.find_patient_folder(
            patient_name,
            year=request.data.get('year'),
            month=request.data.get('month')
        )

        folder_found = folder_id is not None

        # Count PDFs if folder found
        pdf_count = 0
        if folder_found:
            from processing.word_hyperlink_processor_new_format import WordHyperlinkProcessorNewFormat
            processor = WordHyperlinkProcessorNewFormat()
            pdf_links = processor.get_pdfs_from_drive_folder(folder_id)
            pdf_count = len(pdf_links)

        return Response({
            'success': True,
            'config': {
                'structure_type': config.structure_type,
                'structure_type_display': config.get_structure_type_display()
            },
            'expected_path': expected_path,
            'folder_found': folder_found,
            'folder_id': folder_id if folder_found else None,
            'pdf_count': pdf_count
        })

    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_available_structure_types(request):
    """
    GET /api/folder-config/structure-types/

    Get list of available structure types
    """
    return Response({
        'success': True,
        'structure_types': [
            {
                'value': choice[0],
                'label': choice[1],
                'description': _get_structure_description(choice[0])
            }
            for choice in FolderStructureConfig.STRUCTURE_TYPES
        ]
    })


def _get_structure_description(structure_type):
    """Get detailed description for structure type"""
    descriptions = {
        'FLAT': 'Simple flat structure. PDFs directly in patient folder.\nExample: Root/Carl_Mayfield/3-4.pdf',
        'WITH_SPLITS': 'PDFs in a subfolder. Typically Root/PatientName/splits/*.pdf\nExample: Root/Carl_Mayfield/splits/3-4.pdf',
        'YEAR_MONTH': 'Organized by year and month.\nExample: Root/2025/December/Carl_Mayfield/3-4.pdf',
        'CUSTOM': 'Custom path template using placeholders.\nExample: {year}/{month}/{patient_name}/splits'
    }
    return descriptions.get(structure_type, '')
