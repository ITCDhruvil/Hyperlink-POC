"""
Google Drive API utilities for file upload and folder management
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from django.conf import settings
from typing import Tuple, Optional
import os


class DriveService:
    """Google Drive API service wrapper"""
    
    def __init__(self):
        self.credentials = None
        self.service = None
        self._initialize_service()
    
    def _initialize_service(self):
        """Initialize Google Drive API service"""
        try:
            credentials_path = settings.GOOGLE_DRIVE_CREDENTIALS_PATH
            
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Google Drive credentials not found at: {credentials_path}\n"
                    "Please place your service account JSON key file there."
                )
            
            SCOPES = ['https://www.googleapis.com/auth/drive.file']
            
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=SCOPES
            )
            
            self.service = build('drive', 'v3', credentials=self.credentials)
            
        except Exception as e:
            print(f"Error initializing Drive service: {e}")
            raise
    
    def create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        """
        Create a folder in Google Drive
        Returns the folder ID
        """
        try:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            
            if parent_id:
                file_metadata['parents'] = [parent_id]
            elif settings.GOOGLE_DRIVE_ROOT_FOLDER_ID:
                file_metadata['parents'] = [settings.GOOGLE_DRIVE_ROOT_FOLDER_ID]
            
            folder = self.service.files().create(
                body=file_metadata,
                fields='id',
                supportsAllDrives=True
            ).execute()
            
            return folder.get('id')
            
        except HttpError as error:
            print(f"Error creating folder: {error}")
            raise
    
    def find_folder(self, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """
        Find a folder by name in a parent folder
        Returns folder ID if found, None otherwise
        """
        try:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            
            if parent_id:
                query += f" and '{parent_id}' in parents"
            elif settings.GOOGLE_DRIVE_ROOT_FOLDER_ID:
                query += f" and '{settings.GOOGLE_DRIVE_ROOT_FOLDER_ID}' in parents"
            
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)',
                pageSize=1,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                return files[0]['id']
            return None
            
        except HttpError as error:
            print(f"Error finding folder: {error}")
            return None
    
    def get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        """
        Get existing folder or create new one
        Returns folder ID
        """
        folder_id = self.find_folder(folder_name, parent_id)
        
        if folder_id:
            return folder_id
        
        return self.create_folder(folder_name, parent_id)
    
    def create_folder_hierarchy(self, path_components: list) -> str:
        """
        Create a hierarchical folder structure
        Args:
            path_components: List of folder names in order (e.g., ['2025', '12', '03', 'Hospital', 'Patient'])
        Returns:
            ID of the deepest folder
        """
        parent_id = settings.GOOGLE_DRIVE_ROOT_FOLDER_ID or None
        
        for folder_name in path_components:
            parent_id = self.get_or_create_folder(folder_name, parent_id)
        
        return parent_id
    
    def upload_file(self, file_path: str, drive_parent_id: str, file_name: Optional[str] = None) -> Tuple[str, str]:
        """
        Upload a file to Google Drive
        Args:
            file_path: Local path to file
            drive_parent_id: Parent folder ID in Drive
            file_name: Optional custom name (defaults to original filename)
        Returns:
            Tuple of (file_id, webViewLink)
        """
        try:
            if not file_name:
                file_name = os.path.basename(file_path)
            
            file_metadata = {
                'name': file_name,
                'parents': [drive_parent_id]
            }
            
            media = MediaFileUpload(
                file_path,
                mimetype='application/pdf',
                resumable=True
            )
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink',
                supportsAllDrives=True
            ).execute()
            
            file_id = file.get('id')
            web_view_link = file.get('webViewLink')
            
            return file_id, web_view_link
            
        except HttpError as error:
            print(f"Error uploading file: {error}")
            raise
    
    def set_domain_permission(self, file_id: str, domain: str, role: str = 'reader'):
        """
        Set domain-wide permission for a file
        Args:
            file_id: Google Drive file ID
            domain: Domain name (e.g., 'yourcompany.com')
            role: Permission role ('reader', 'writer', 'commenter')
        """
        try:
            permission = {
                'type': 'domain',
                'role': role,
                'domain': domain
            }
            
            self.service.permissions().create(
                fileId=file_id,
                body=permission,
                fields='id',
                supportsAllDrives=True
            ).execute()
            
        except HttpError as error:
            print(f"Error setting permission: {error}")
            raise
    
    def set_user_permission(self, file_id: str, email: str, role: str = 'reader'):
        """
        Set user-specific permission for a file
        Args:
            file_id: Google Drive file ID
            email: User email address
            role: Permission role ('reader', 'writer', 'commenter')
        """
        try:
            permission = {
                'type': 'user',
                'role': role,
                'emailAddress': email
            }
            
            self.service.permissions().create(
                fileId=file_id,
                body=permission,
                fields='id',
                sendNotificationEmail=False,
                supportsAllDrives=True
            ).execute()
            
        except HttpError as error:
            print(f"Error setting permission: {error}")
            raise
    
    def verify_file_exists(self, file_id: str) -> bool:
        """
        Verify that a file exists and is not trashed
        Returns True if file is accessible, False otherwise
        """
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields='id, trashed',
                supportsAllDrives=True
            ).execute()
            
            return not file.get('trashed', False)
            
        except HttpError:
            return False


# Singleton instance
_drive_service = None

def get_drive_service() -> DriveService:
    """Get or create Drive service singleton"""
    global _drive_service
    if _drive_service is None:
        _drive_service = DriveService()
    return _drive_service
