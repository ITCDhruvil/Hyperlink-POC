"""
Google Drive Path Resolver
Automatically resolve folder IDs from paths like "2025/December/Carl_Mayfield"
"""
from typing import Optional, List, Dict
from .drive_utils import get_drive_service


class DrivePathResolver:
    """
    Resolve Google Drive folder IDs from human-readable paths
    """

    def __init__(self, root_folder_id: Optional[str] = None):
        """
        Initialize resolver

        Args:
            root_folder_id: Root folder ID to start from (uses settings if None)
        """
        self.drive_service = get_drive_service()

        if root_folder_id is None:
            from django.conf import settings
            root_folder_id = settings.GOOGLE_DRIVE_ROOT_FOLDER_ID

        self.root_folder_id = root_folder_id

    def resolve_path(self, path: str, create_if_missing: bool = False) -> Optional[str]:
        """
        Resolve a path to a folder ID

        Args:
            path: Path like "2025/December/Carl_Mayfield" or "Carl_Mayfield/splits"
            create_if_missing: Create folders if they don't exist

        Returns:
            Folder ID if found/created, None if not found and not creating

        Examples:
            >>> resolver = DrivePathResolver()
            >>> folder_id = resolver.resolve_path("2025/December/Carl_Mayfield")
            >>> folder_id
            '1ABC123xyz...'
        """
        # Clean path
        path = path.strip().strip('/')

        if not path:
            return self.root_folder_id

        # Split into parts
        parts = [p for p in path.split('/') if p]

        # Start from root
        current_folder_id = self.root_folder_id

        # Navigate through each part
        for part in parts:
            next_folder_id = self._find_subfolder(current_folder_id, part)

            if next_folder_id:
                current_folder_id = next_folder_id
            elif create_if_missing:
                # Create the folder
                current_folder_id = self.drive_service.create_folder(part, current_folder_id)
            else:
                # Folder not found and not creating
                return None

        return current_folder_id

    def _find_subfolder(self, parent_folder_id: str, folder_name: str) -> Optional[str]:
        """
        Find a subfolder by name within a parent folder

        Args:
            parent_folder_id: Parent folder ID
            folder_name: Name of subfolder to find

        Returns:
            Folder ID if found, None otherwise
        """
        try:
            query = (
                f"name='{folder_name}' and "
                f"'{parent_folder_id}' in parents and "
                f"mimeType='application/vnd.google-apps.folder' and "
                f"trashed=false"
            )

            results = self.drive_service.service.files().list(
                q=query,
                fields="files(id, name)",
                pageSize=10
            ).execute()

            folders = results.get('files', [])

            if folders:
                return folders[0]['id']

            return None

        except Exception as e:
            raise Exception(f"Failed to find subfolder '{folder_name}': {str(e)}")

    def get_or_create_path(self, path: str) -> str:
        """
        Get folder ID for path, creating folders if they don't exist

        Args:
            path: Path like "2025/December/Carl_Mayfield"

        Returns:
            Folder ID (always succeeds)
        """
        return self.resolve_path(path, create_if_missing=True)

    def list_subfolders(self, folder_id: Optional[str] = None) -> List[Dict]:
        """
        List all subfolders in a folder

        Args:
            folder_id: Folder ID to list (uses root if None)

        Returns:
            List of dicts with 'id', 'name' keys
        """
        if folder_id is None:
            folder_id = self.root_folder_id

        try:
            query = (
                f"'{folder_id}' in parents and "
                f"mimeType='application/vnd.google-apps.folder' and "
                f"trashed=false"
            )

            results = self.drive_service.service.files().list(
                q=query,
                fields="files(id, name, modifiedTime)",
                pageSize=100,
                orderBy="name"
            ).execute()

            folders = results.get('files', [])

            return [
                {
                    'id': f['id'],
                    'name': f['name'],
                    'modified': f.get('modifiedTime')
                }
                for f in folders
            ]

        except Exception as e:
            raise Exception(f"Failed to list subfolders: {str(e)}")

    def build_path_from_id(self, folder_id: str) -> str:
        """
        Build a path string from a folder ID (reverse lookup)

        Args:
            folder_id: Folder ID

        Returns:
            Path like "2025/December/Carl_Mayfield"
        """
        try:
            path_parts = []
            current_id = folder_id

            # Walk up the tree until we reach root
            while current_id and current_id != self.root_folder_id:
                # Get folder metadata
                file_metadata = self.drive_service.service.files().get(
                    fileId=current_id,
                    fields='name, parents'
                ).execute()

                path_parts.insert(0, file_metadata['name'])

                # Get parent
                parents = file_metadata.get('parents', [])
                current_id = parents[0] if parents else None

            return '/'.join(path_parts)

        except Exception as e:
            raise Exception(f"Failed to build path: {str(e)}")


class StandardDriveStructure:
    """
    Standard Drive folder structure for the application
    Provides convenient methods for common paths
    """

    def __init__(self):
        self.resolver = DrivePathResolver()

    def get_patient_folder(
        self,
        year: str,
        month: str,
        patient_name: str,
        create: bool = False
    ) -> Optional[str]:
        """
        Get patient folder ID from standard structure

        Structure: {year}/{month}/{patient_name}
        Example: 2025/December/Carl_Mayfield

        Args:
            year: Year (e.g., "2025")
            month: Month name (e.g., "December")
            patient_name: Patient name (e.g., "Carl_Mayfield")
            create: Create folders if they don't exist

        Returns:
            Folder ID or None
        """
        path = f"{year}/{month}/{patient_name}"
        return self.resolver.resolve_path(path, create_if_missing=create)

    def get_splits_folder(
        self,
        year: str,
        month: str,
        patient_name: str,
        create: bool = False
    ) -> Optional[str]:
        """
        Get splits subfolder for patient

        Structure: {year}/{month}/{patient_name}/splits

        Args:
            year: Year
            month: Month name
            patient_name: Patient name
            create: Create folders if they don't exist

        Returns:
            Folder ID or None
        """
        path = f"{year}/{month}/{patient_name}/splits"
        return self.resolver.resolve_path(path, create_if_missing=create)

    def get_or_create_patient_structure(
        self,
        year: str,
        month: str,
        patient_name: str
    ) -> Dict[str, str]:
        """
        Create complete patient folder structure

        Creates:
        - {year}/{month}/{patient_name}
        - {year}/{month}/{patient_name}/splits

        Args:
            year: Year
            month: Month name
            patient_name: Patient name

        Returns:
            Dict with 'patient_folder_id' and 'splits_folder_id'
        """
        # Create patient folder
        patient_folder_id = self.get_patient_folder(year, month, patient_name, create=True)

        # Create splits subfolder
        splits_folder_id = self.get_splits_folder(year, month, patient_name, create=True)

        return {
            'patient_folder_id': patient_folder_id,
            'splits_folder_id': splits_folder_id
        }

    def resolve_patient_path(self, patient_name: str) -> Optional[Dict[str, str]]:
        """
        Search for patient folder by name across all year/month folders

        Args:
            patient_name: Patient name to search for

        Returns:
            Dict with folder IDs and path, or None if not found
        """
        # This is a simplified version - you might want to add more sophisticated search
        # For now, assume current year/month or search recent months

        from datetime import datetime
        current_year = str(datetime.now().year)
        current_month = datetime.now().strftime('%B')

        # Try current month first
        folder_id = self.get_patient_folder(current_year, current_month, patient_name)

        if folder_id:
            splits_id = self.get_splits_folder(current_year, current_month, patient_name)
            return {
                'patient_folder_id': folder_id,
                'splits_folder_id': splits_id,
                'path': f"{current_year}/{current_month}/{patient_name}"
            }

        return None
