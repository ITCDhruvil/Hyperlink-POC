"""
Smart Folder Detector V2 - Multi-strategy auto-detection
"""
import re
import os
from typing import Optional, Dict
from docx import Document
from .drive_utils import get_drive_service


class SmartFolderDetectorV2:
    """
    Multi-strategy folder detection:
    1. OT_number from document content
    2. Patient name from filename
    3. Flexible Drive search
    """

    def __init__(self):
        self.drive_service = get_drive_service()

    def extract_ot_number_from_word(self, word_file_path: str) -> Optional[str]:
        """Extract OT_number from Word document"""
        try:
            doc = Document(word_file_path)
            for paragraph in doc.paragraphs:
                match = re.search(r'(OT_\d+)', paragraph.text, re.IGNORECASE)
                if match:
                    return match.group(1).upper()
            return None
        except Exception as e:
            print(f"Error extracting OT_number: {e}")
            return None

    def extract_patient_name_from_filename(self, word_file_path: str) -> Optional[str]:
        """
        Extract patient name from filename

        Examples:
        - "OT_8896047_Carl Mayfield_ROR_..." -> "Carl_Mayfield"
        - "Carl_Mayfield_Report.docx" -> "Carl_Mayfield"
        """
        filename = os.path.basename(word_file_path)

        # Pattern 1: OT_number_PatientName_...
        match = re.search(r'OT_\d+_(.+?)_(?:ROR|Report|Summary)', filename, re.IGNORECASE)
        if match:
            return match.group(1).replace(' ', '_')

        # Pattern 2: PatientName_...
        match = re.search(r'^([A-Z][a-z]+_[A-Z][a-z]+)', filename)
        if match:
            return match.group(1)

        return None

    def search_by_patient_name(self, patient_name: str) -> Optional[str]:
        """
        Search for patient folder with splits subfolder

        Looks for: Carl_Mayfield/splits, Test_Carl_Mayfield/splits, etc.
        """
        try:
            query = f"name contains '{patient_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"

            results = self.drive_service.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)',
                pageSize=20,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()

            folders = results.get('files', [])
            print(f"  Found {len(folders)} folders matching '{patient_name}'")

            # Check each for splits subfolder
            for folder in folders:
                print(f"    Checking: {folder['name']}")
                splits_id = self._find_splits_subfolder(folder['id'])
                if splits_id:
                    print(f"      -> Found 'splits'! (ID: {splits_id})")
                    return splits_id

            return None

        except Exception as e:
            print(f"  Error: {e}")
            return None

    def _find_splits_subfolder(self, parent_folder_id: str) -> Optional[str]:
        """Check if folder has 'splits' subfolder"""
        try:
            query = f"'{parent_folder_id}' in parents and name = 'splits' and mimeType='application/vnd.google-apps.folder' and trashed=false"

            results = self.drive_service.service.files().list(
                q=query,
                fields='files(id)',
                pageSize=1,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()

            files = results.get('files', [])
            return files[0]['id'] if files else None

        except:
            return None

    def find_splits_folder_for_document(self, word_file_path: str) -> Optional[str]:
        """
        Multi-strategy folder detection

        Tries:
        1. OT_number from document
        2. Patient name from filename
        """
        print("=" * 80)
        print("SMART FOLDER DETECTION (Multi-Strategy)")
        print("=" * 80)

        # Strategy 1: OT_number
        print("\n[Strategy 1] OT_number from document content...")
        ot_number = self.extract_ot_number_from_word(word_file_path)
        if ot_number:
            print(f"  Found: {ot_number}")
            # Could implement OT search here if needed
        else:
            print("  Not found")

        # Strategy 2: Patient name from filename
        print("\n[Strategy 2] Patient name from filename...")
        patient_name = self.extract_patient_name_from_filename(word_file_path)

        if patient_name:
            print(f"  Found: {patient_name}")
            splits_id = self.search_by_patient_name(patient_name)

            if splits_id:
                print(f"\n[SUCCESS]")
                print(f"  Splits Folder ID: {splits_id}")
                print("=" * 80)
                return splits_id

        print("\n[FAILED] Could not find splits folder")
        print("=" * 80)
        return None
