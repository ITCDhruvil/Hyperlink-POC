"""
Configurable Smart Folder Detector

Uses database configuration for folder structure
Can be updated from frontend without code changes
"""
import re
import os
from typing import Optional, Dict
from docx import Document
from .drive_utils import get_drive_service


class SmartFolderDetectorConfigurable:
    """
    Configurable folder detector that adapts to different folder structures
    """

    def __init__(self, config=None):
        """
        Initialize with optional configuration

        Args:
            config: FolderStructureConfig instance (if None, uses active config)
        """
        self.drive_service = get_drive_service()

        # Get configuration
        if config is None:
            from pdfs.folder_structure_config import FolderStructureConfig
            self.config = FolderStructureConfig.get_active_config()
        else:
            self.config = config

    def extract_patient_name_from_document(self, doc: Document) -> Optional[str]:
        """
        Extract patient name from document header

        Looks for: "PATIENT NAME: CARL MAYFIELD"
        """
        for paragraph in doc.paragraphs[:10]:
            text = paragraph.text.strip()

            match = re.search(r'PATIENT\s+NAME:?\s+(.+)', text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                name = name.title().replace(' ', '_')
                return name

            match = re.search(r'^Name:?\s+(.+)', text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                name = name.title().replace(' ', '_')
                return name

        return None

    def extract_patient_name_from_filename(self, word_file_path: str) -> Optional[str]:
        """Extract patient name from filename"""
        filename = os.path.basename(word_file_path)

        # Pattern: OT_number_PatientName_...
        match = re.search(r'OT_\d+_(.+?)_(?:ROR|Report|Summary)', filename, re.IGNORECASE)
        if match:
            return match.group(1).replace(' ', '_')

        # Pattern: PatientName_...
        match = re.search(r'^([A-Z][a-z]+_[A-Z][a-z]+)', filename)
        if match:
            return match.group(1)

        return None

    def find_patient_folder(self, patient_name: str, **kwargs) -> Optional[str]:
        """
        Find patient folder based on configuration

        Args:
            patient_name: Patient name (e.g., "Carl_Mayfield")
            **kwargs: Additional variables (year, month, ot_number)

        Returns:
            Folder ID containing PDFs, or None
        """
        try:
            # Get expected path from configuration
            expected_path = self.config.get_path_for_patient(patient_name, **kwargs)

            print(f"  Looking for path: {expected_path}")

            # For FLAT structure: Search directly for patient folder
            if self.config.structure_type == 'FLAT':
                return self._find_folder_by_name(patient_name, self.config.root_folder_id)

            # For WITH_SPLITS: Find patient folder, then subfolder
            elif self.config.structure_type == 'WITH_SPLITS':
                patient_folder_id = self._find_folder_by_name(patient_name, self.config.root_folder_id)
                if patient_folder_id and self.config.pdf_subfolder:
                    return self._find_subfolder(patient_folder_id, self.config.pdf_subfolder)
                return patient_folder_id

            # For YEAR_MONTH: Navigate Year -> Month -> Patient
            elif self.config.structure_type == 'YEAR_MONTH':
                year = kwargs.get('year')
                month = kwargs.get('month')

                if year and month:
                    year_folder = self._find_folder_by_name(year, self.config.root_folder_id)
                    if year_folder:
                        month_folder = self._find_subfolder(year_folder, month)
                        if month_folder:
                            patient_folder = self._find_subfolder(month_folder, patient_name)
                            if patient_folder and self.config.pdf_subfolder:
                                return self._find_subfolder(patient_folder, self.config.pdf_subfolder)
                            return patient_folder

            # For CUSTOM: Use template-based search
            elif self.config.structure_type == 'CUSTOM':
                # Navigate through path components
                folder_id = self.config.root_folder_id
                path_parts = expected_path.split('/')

                for part in path_parts:
                    folder_id = self._find_subfolder(folder_id, part)
                    if not folder_id:
                        return None

                return folder_id

            return None

        except Exception as e:
            print(f"  Error finding folder: {e}")
            return None

    def _find_folder_by_name(self, folder_name: str, parent_folder_id: str) -> Optional[str]:
        """
        Find folder by name within parent folder
        If multiple folders found, returns the LATEST one (by creation date)
        """
        try:
            # Search for exact match
            query = f"'{parent_folder_id}' in parents and name = '{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"

            results = self.drive_service.service.files().list(
                q=query,
                fields='files(id, name, createdTime)',
                orderBy='createdTime desc',  # Sort by newest first
                pageSize=10,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()

            files = results.get('files', [])
            if files:
                if len(files) > 1:
                    print(f"    Found {len(files)} folders with name '{folder_name}', using LATEST: {files[0]['name']} (Created: {files[0]['createdTime']})")
                return files[0]['id']  # Return the latest (first in sorted list)

            # Try contains match
            query = f"'{parent_folder_id}' in parents and name contains '{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"

            results = self.drive_service.service.files().list(
                q=query,
                fields='files(id, name, createdTime)',
                orderBy='createdTime desc',  # Sort by newest first
                pageSize=10,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()

            files = results.get('files', [])
            if files:
                print(f"    Found {len(files)} matching folders: {[f['name'] for f in files]}")
                print(f"    Using LATEST: {files[0]['name']} (Created: {files[0]['createdTime']})")
                return files[0]['id']  # Return the latest (first in sorted list)

            return None

        except Exception as e:
            print(f"    Error searching: {e}")
            return None

    def _find_subfolder(self, parent_id: str, subfolder_name: str) -> Optional[str]:
        """Find subfolder within parent"""
        return self._find_folder_by_name(subfolder_name, parent_id)

    def find_pdf_folder_for_document(self, word_file_path: str, **kwargs) -> Optional[str]:
        """
        Complete workflow: Find folder containing PDFs

        Args:
            word_file_path: Path to Word document
            **kwargs: Additional variables (year, month, ot_number)

        Returns:
            Folder ID containing PDFs
        """
        from docx import Document

        print("=" * 80)
        print(f"SMART FOLDER DETECTION")
        print(f"Configuration: {self.config.config_name} ({self.config.get_structure_type_display()})")
        print("=" * 80)

        # Extract patient name from document
        print("\nExtracting patient name from document...")
        doc = Document(word_file_path)
        patient_name = self.extract_patient_name_from_document(doc)

        if not patient_name:
            print("  Not found in document, trying filename...")
            patient_name = self.extract_patient_name_from_filename(word_file_path)

        if not patient_name:
            print("  ERROR: Could not extract patient name")
            return None

        print(f"  Found: {patient_name}")

        # Find folder
        print(f"\nSearching for folder (Structure: {self.config.structure_type})...")
        folder_id = self.find_patient_folder(patient_name, **kwargs)

        if folder_id:
            print(f"\n[SUCCESS] Found folder!")
            print(f"  Folder ID: {folder_id}")
            print("=" * 80)
            return folder_id
        else:
            print(f"\n[FAILED] Could not find folder")
            print("=" * 80)
            return None
