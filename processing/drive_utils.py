"""
Google Drive API utilities for file upload and folder management
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import httplib2
from google_auth_httplib2 import AuthorizedHttp
from django.conf import settings
from typing import Tuple, Optional, Dict
import os


class DriveService:
    """Google Drive API service wrapper"""
    
    def __init__(self, credentials_path: str, root_folder_id: Optional[str] = None):
        self.credentials = None
        self.service = None
        self.credentials_path = credentials_path
        self.root_folder_id = root_folder_id
        self._initialize_service()
    
    def _initialize_service(self):
        """Initialize Google Drive API service"""
        try:
            credentials_path = self.credentials_path
            
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"Google Drive credentials not found at: {credentials_path}\n"
                    "Please place your service account JSON key file there."
                )
            
            SCOPES = [
                'https://www.googleapis.com/auth/drive.file',
                'https://www.googleapis.com/auth/drive.metadata.readonly',
            ]
            
            self.credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=SCOPES
            )

            for k in ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy', 'NO_PROXY', 'no_proxy'):
                if k in os.environ:
                    os.environ.pop(k, None)

            http = httplib2.Http(proxy_info=None)
            authed_http = AuthorizedHttp(self.credentials, http=http)
            self.service = build('drive', 'v3', http=authed_http, cache_discovery=False)
            
        except Exception as e:
            print(f"Error initializing Drive service: {e}")
            raise
    
    def get_account_info(self) -> Dict:
        """Get authenticated account display name and email (service account or delegated user)."""
        try:
            about = self.service.about().get(
                fields='user(displayName,emailAddress)'
            ).execute()
            user = about.get('user', {})
            return {
                'displayName': user.get('displayName'),
                'emailAddress': user.get('emailAddress'),
            }
        except HttpError as error:
            return {
                'error': {
                    'message': str(error),
                    'status_code': getattr(error, 'status_code', None),
                }
            }

    def get_folder_metadata(self, folder_id: str) -> Dict:
        """Get folder metadata for a given folder_id."""
        try:
            folder = self.service.files().get(
                fileId=folder_id,
                fields='id,name,mimeType,createdTime,modifiedTime,size,owners(displayName,emailAddress),capabilities(canAddChildren,canDelete,canEdit,canMoveChildrenOutOfDrive,canRemoveChildren,canRename,canShare)',
                supportsAllDrives=True
            ).execute()
            return folder
        except HttpError as error:
            return {
                'error': {
                    'message': str(error),
                    'status_code': getattr(error, 'status_code', None),
                }
            }

    def list_folder_children(
        self,
        folder_id: str,
        page_token: Optional[str] = None,
        page_size: int = 100,
    ) -> Dict:
        """List files/folders directly under folder_id with pagination."""
        try:
            query = f"'{folder_id}' in parents and trashed=false"
            result = self.service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id,name,mimeType,createdTime,modifiedTime,size,owners(displayName,emailAddress))',
                pageSize=page_size,
                pageToken=page_token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute()
            return {
                'files': result.get('files', []),
                'nextPageToken': result.get('nextPageToken'),
            }
        except HttpError as error:
            return {
                'error': {
                    'message': str(error),
                    'status_code': getattr(error, 'status_code', None),
                }
            }
    
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
            elif self.root_folder_id:
                file_metadata['parents'] = [self.root_folder_id]
            
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
            elif self.root_folder_id:
                query += f" and '{self.root_folder_id}' in parents"
            
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
        parent_id = self.root_folder_id or None
        
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


def get_active_drive_root_folder_id() -> Optional[str]:
    return getattr(settings, 'GOOGLE_DRIVE_ROOT_FOLDER_ID', None)


def get_active_drive_credentials_path() -> str:
    return settings.GOOGLE_DRIVE_CREDENTIALS_PATH

def get_drive_service() -> DriveService:
    """Get or create Drive service singleton"""
    global _drive_service

    if _drive_service is None:
        credentials_path = get_active_drive_credentials_path()
        root_folder_id = get_active_drive_root_folder_id()
        _drive_service = DriveService(credentials_path=credentials_path, root_folder_id=root_folder_id)

    return _drive_service
