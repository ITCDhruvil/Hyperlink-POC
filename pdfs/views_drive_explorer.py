from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.csrf import csrf_exempt
from googleapiclient.http import MediaIoBaseDownload
import io
import os
import tempfile
import json

from django.conf import settings
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

from processing.drive_utils import get_active_drive_root_folder_id
from .views_auth import is_admin


_drive_authed_session = None


def get_drive_authed_session() -> AuthorizedSession:
    global _drive_authed_session
    if _drive_authed_session is not None:
        return _drive_authed_session

    credentials_path = getattr(settings, 'GOOGLE_DRIVE_CREDENTIALS_PATH', None)
    if not credentials_path or not os.path.exists(credentials_path):
        raise FileNotFoundError(f"Google Drive credentials not found at: {credentials_path}")

    scopes = [
        'https://www.googleapis.com/auth/drive.file',
        'https://www.googleapis.com/auth/drive.metadata.readonly',
    ]
    creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=scopes)
    _drive_authed_session = AuthorizedSession(creds)
    return _drive_authed_session


def drive_api_get_json(url: str, params: dict | None = None) -> dict:
    sess = get_drive_authed_session()
    r = sess.get(url, params=params, timeout=60)
    if r.status_code >= 400:
        raise Exception(f"Drive API error {r.status_code}: {r.text}")
    return r.json()


@login_required
@user_passes_test(is_admin)
def drive_explorer_page(request):
    return render(request, 'pdfs/drive_explorer.html', {
        'profile_id': '',
    })


@login_required
@user_passes_test(is_admin)
def drive_status(request):
    root_folder_id = get_active_drive_root_folder_id()

    connected = True
    error = None
    account = None
    root_folder = None
    scopes = []

    try:
        sess = get_drive_authed_session()
        scopes = list(getattr(getattr(sess, 'credentials', None), 'scopes', []) or [])

        about = drive_api_get_json(
            'https://www.googleapis.com/drive/v3/about',
            params={'fields': 'user(displayName,emailAddress)'}
        )
        user = (about or {}).get('user', {})
        account = {
            'displayName': user.get('displayName'),
            'emailAddress': user.get('emailAddress'),
        }

        if root_folder_id:
            root_folder = drive_api_get_json(
                f'https://www.googleapis.com/drive/v3/files/{root_folder_id}',
                params={
                    'fields': 'id,name,mimeType,createdTime,modifiedTime,size,owners(displayName,emailAddress),capabilities(canAddChildren,canDelete,canEdit,canMoveChildrenOutOfDrive,canRemoveChildren,canRename,canShare)',
                    'supportsAllDrives': 'true',
                }
            )
    except Exception as e:
        connected = False
        error = {'message': str(e)}

    return JsonResponse({
        'connected': connected,
        'account': account if isinstance(account, dict) else None,
        'rootFolder': root_folder if isinstance(root_folder, dict) else None,
        'rootFolderId': root_folder_id,
        'profileName': None,
        'scopes': scopes,
        'error': error,
    })


@login_required
@user_passes_test(is_admin)
def drive_list(request):
    default_root = get_active_drive_root_folder_id()

    folder_id = request.GET.get('folder_id') or default_root
    page_token = request.GET.get('pageToken') or None

    page_size = 12
    

    if not folder_id:
        return JsonResponse({
            'success': False,
            'error': 'GOOGLE_DRIVE_ROOT_FOLDER_ID is not configured and folder_id was not provided',
        }, status=400)

    try:
        query = f"'{folder_id}' in parents and trashed=false"
        params = {
            'q': query,
            'spaces': 'drive',
            'fields': 'nextPageToken, files(id,name,mimeType,createdTime,modifiedTime,size,owners(displayName,emailAddress))',
            'pageSize': page_size,
            'includeItemsFromAllDrives': 'true',
            'supportsAllDrives': 'true',
        }
        if page_token:
            params['pageToken'] = page_token

        result = drive_api_get_json('https://www.googleapis.com/drive/v3/files', params=params)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'folderId': folder_id,
            'error': {'message': str(e)},
        }, status=502)

    items = []
    for f in (result.get('files', []) or []):
        mime_type = f.get('mimeType')
        is_folder = mime_type == 'application/vnd.google-apps.folder'
        size = f.get('size')
        try:
            size = int(size) if size is not None else None
        except (TypeError, ValueError):
            size = None

        owners = []
        for o in f.get('owners', []) or []:
            owners.append({
                'displayName': o.get('displayName'),
                'emailAddress': o.get('emailAddress'),
            })

        items.append({
            'id': f.get('id'),
            'name': f.get('name'),
            'mimeType': mime_type,
            'isFolder': is_folder,
            'createdTime': f.get('createdTime'),
            'modifiedTime': f.get('modifiedTime'),
            'size': size,
            'owners': owners,
        })

    return JsonResponse({
        'success': True,
        'folderId': folder_id,
        'pageSize': page_size,
        'items': items,
        'nextPageToken': result.get('nextPageToken'),
    })


@login_required
@user_passes_test(is_admin)
def drive_file_proxy(request, file_id: str):
    """Stream a Drive file (intended for PDFs) through Django for same-origin iframe viewing."""
    sess = get_drive_authed_session()
    range_header = request.headers.get('Range') or request.META.get('HTTP_RANGE')
    headers = {}
    if range_header:
        headers['Range'] = range_header

    url = f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true'
    r = sess.get(url, headers=headers, stream=True, timeout=120)

    status = r.status_code
    if status >= 400:
        return JsonResponse({'success': False, 'error': r.text}, status=502)

    def body_iter():
        for chunk in r.iter_content(chunk_size=1024 * 256):
            if chunk:
                yield chunk

    out = StreamingHttpResponse(body_iter(), status=status, content_type='application/pdf')
    out['X-Content-Type-Options'] = 'nosniff'
    out['Content-Disposition'] = 'inline'
    if r.headers.get('Content-Range'):
        out['Content-Range'] = r.headers.get('Content-Range')
    if r.headers.get('Accept-Ranges'):
        out['Accept-Ranges'] = r.headers.get('Accept-Ranges')
    if r.headers.get('Content-Length'):
        out['Content-Length'] = r.headers.get('Content-Length')
    return out


@login_required
@user_passes_test(is_admin)
@csrf_exempt
def drive_upload_original(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)

    folder_id = (request.POST.get('folder_id') or '').strip()
    if not folder_id:
        return JsonResponse({'success': False, 'error': 'folder_id is required'}, status=400)

    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'success': False, 'error': 'file is required'}, status=400)

    if not (uploaded.name or '').lower().endswith('.pdf'):
        return JsonResponse({'success': False, 'error': 'Please upload a PDF file'}, status=400)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            for chunk in uploaded.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        sess = get_drive_authed_session()
        metadata = {
            'name': 'original.pdf',
            'parents': [folder_id],
        }
        with open(tmp_path, 'rb') as f:
            pdf_bytes = f.read()

        boundary = '----pdfautomationboundary'
        parts = []
        parts.append(f'--{boundary}\r\n'.encode('utf-8'))
        parts.append(b'Content-Type: application/json; charset=UTF-8\r\n\r\n')
        parts.append(json.dumps(metadata).encode('utf-8'))
        parts.append(b'\r\n')
        parts.append(f'--{boundary}\r\n'.encode('utf-8'))
        parts.append(b'Content-Type: application/pdf\r\n\r\n')
        parts.append(pdf_bytes)
        parts.append(b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode('utf-8'))

        body = b''.join(parts)
        upload_url = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true&fields=id,webViewLink'
        r = sess.post(upload_url, data=body, headers={'Content-Type': f'multipart/related; boundary={boundary}'}, timeout=120)
        if r.status_code >= 400:
            return JsonResponse({'success': False, 'error': r.text}, status=502)

        data = r.json()
        return JsonResponse({
            'success': True,
            'folder_id': folder_id,
            'file_id': data.get('id'),
            'webViewLink': data.get('webViewLink'),
            'filename': 'original.pdf',
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    finally:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
