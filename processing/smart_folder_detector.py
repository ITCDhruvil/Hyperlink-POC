"""
Smart Folder Detector - Auto-detect the correct splits folder based on OT_number
"""
import re
from typing import Optional, Dict
from docx import Document
from .drive_utils import get_drive_service


class SmartFolderDetector:
    """
    Automatically detect the correct Google Drive folder for a document
    based on its OT_number identifier
    """

    def __init__(self):
        self.drive_service = get_drive_service()

    def extract_ot_number_from_word(self, word_file_path: str) -> Optional[str]:
        """
        Extract OT_number from Word document

        Looks for patterns like: OT_8896048, OT_8896047, etc.

        Args:
            word_file_path: Path to Word document

        Returns:
            OT_number if found, else None
        """
        try:
            doc = Document(word_file_path)

            # Search through all paragraphs
            for paragraph in doc.paragraphs:
                text = paragraph.text

                # Look for OT_number pattern
                match = re.search(r'(OT_\d+)', text, re.IGNORECASE)
                if match:
                    ot_number = match.group(1).upper()
                    print(f"Found OT_number in document: {ot_number}")
                    return ot_number

            print("No OT_number found in document")
            return None

        except Exception as e:
            print(f"Error extracting OT_number: {e}")
            return None

    def search_drive_for_ot_number(self, ot_number: str, root_folder_id: str) -> Dict:
        """
        Search Google Drive for folders/files matching the OT_number

        Args:
            ot_number: OT identifier (e.g., "OT_8896048")
            root_folder_id: Root Drive folder to search in

        Returns:
            Dict with matching folders and files
        """
        results = {
            'folders': [],
            'files': [],
            'splits_folders': []
        }

        try:
            # Search for files/folders containing OT_number
            query = f"name contains '{ot_number}' and trashed=false"

            search_results = self.drive_service.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, mimeType, parents, webViewLink)',
                pageSize=100,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()

            files = search_results.get('files', [])

            print(f"\nFound {len(files)} items matching '{ot_number}':")

            for file in files:
                is_folder = file['mimeType'] == 'application/vnd.google-apps.folder'

                if is_folder:
                    results['folders'].append(file)
                    print(f"  [FOLDER] {file['name']} (ID: {file['id']})")

                    # Check if this folder contains a "splits" subfolder
                    splits_folder = self._find_splits_subfolder(file['id'])
                    if splits_folder:
                        results['splits_folders'].append({
                            'parent_folder': file,
                            'splits_folder': splits_folder
                        })
                        print(f"    -> Has 'splits' subfolder! (ID: {splits_folder['id']})")
                else:
                    results['files'].append(file)
                    print(f"  [FILE] {file['name']}")

            return results

        except Exception as e:
            print(f"Error searching Drive: {e}")
            return results

    def _find_splits_subfolder(self, parent_folder_id: str) -> Optional[Dict]:
        """
        Check if a folder has a 'splits' subfolder

        Args:
            parent_folder_id: Parent folder ID

        Returns:
            Splits folder info if found, else None
        """
        try:
            query = f"'{parent_folder_id}' in parents and name = 'splits' and mimeType='application/vnd.google-apps.folder' and trashed=false"

            results = self.drive_service.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, mimeType)',
                pageSize=1,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()

            files = results.get('files', [])
            return files[0] if files else None

        except Exception as e:
            return None

    def find_splits_folder_for_document(
        self,
        word_file_path: str,
        root_folder_id: str
    ) -> Optional[str]:
        """
        Complete workflow: Extract OT_number and find splits folder

        Args:
            word_file_path: Path to Word document
            root_folder_id: Root Drive folder to search in

        Returns:
            Splits folder ID if found, else None
        """
        print("=" * 80)
        print("SMART FOLDER DETECTION")
        print("=" * 80)

        # Step 1: Extract OT_number from Word document
        print("\nStep 1: Extracting OT_number from Word document...")
        ot_number = self.extract_ot_number_from_word(word_file_path)

        if not ot_number:
            print("ERROR: Could not extract OT_number from document")
            return None

        # Step 2: Search Google Drive for matching folders
        print(f"\nStep 2: Searching Google Drive for '{ot_number}'...")
        search_results = self.search_drive_for_ot_number(ot_number, root_folder_id)

        # Step 3: Find the best splits folder
        print("\nStep 3: Looking for 'splits' folder...")

        if search_results['splits_folders']:
            # Use the first splits folder found
            best_match = search_results['splits_folders'][0]
            splits_folder_id = best_match['splits_folder']['id']

            print(f"\nFOUND SPLITS FOLDER!")
            print(f"  Parent: {best_match['parent_folder']['name']}")
            print(f"  Splits Folder ID: {splits_folder_id}")
            print("=" * 80)

            return splits_folder_id
        else:
            print("\nWARNING: No 'splits' folder found for this OT_number")
            print("=" * 80)
            return None

    def find_splits_folder_by_ot_number(
        self,
        ot_number: str,
        root_folder_id: str
    ) -> Optional[str]:
        """
        Find splits folder directly by OT_number (when already extracted)

        Args:
            ot_number: OT identifier (e.g., "OT_8896048")
            root_folder_id: Root Drive folder to search in

        Returns:
            Splits folder ID if found, else None
        """
        print(f"Searching for splits folder with OT_number: {ot_number}")

        search_results = self.search_drive_for_ot_number(ot_number, root_folder_id)

        if search_results['splits_folders']:
            best_match = search_results['splits_folders'][0]
            splits_folder_id = best_match['splits_folder']['id']
            print(f"Found splits folder: {splits_folder_id}")
            return splits_folder_id

        return None
