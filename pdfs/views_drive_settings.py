from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, user_passes_test

from .views_auth import is_admin
from .models import DriveProfile
from processing.drive_utils import DriveService


@login_required
@user_passes_test(is_admin)
def drive_settings_page(request):
    profiles = DriveProfile.objects.all().order_by('-is_active', 'name')
    active = DriveProfile.get_active_profile()
    return render(request, 'pdfs/drive_settings.html', {
        'profiles': profiles,
        'active_profile': active,
    })


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def create_drive_profile(request):
    name = (request.POST.get('name') or '').strip()
    root_folder_id = (request.POST.get('root_folder_id') or '').strip()
    set_active = (request.POST.get('set_active') == 'on')

    credentials_file = request.FILES.get('credentials_file')
    if not name:
        return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)
    if not credentials_file:
        return JsonResponse({'success': False, 'error': 'credentials_file is required'}, status=400)

    profile = DriveProfile.objects.create(
        name=name,
        credentials_file=credentials_file,
        root_folder_id=root_folder_id,
        is_active=False,
    )

    if set_active:
        DriveProfile.objects.exclude(id=profile.id).update(is_active=False)
        profile.is_active = True
        profile.save(update_fields=['is_active'])

    return JsonResponse({'success': True, 'profile_id': profile.id})


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def activate_drive_profile(request, profile_id: int):
    profile = get_object_or_404(DriveProfile, id=profile_id)
    DriveProfile.objects.exclude(id=profile.id).update(is_active=False)
    profile.is_active = True
    profile.save(update_fields=['is_active'])
    return JsonResponse({'success': True, 'active_profile_id': profile.id})


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def update_drive_root_folder(request, profile_id: int):
    profile = get_object_or_404(DriveProfile, id=profile_id)
    root_folder_id = (request.POST.get('root_folder_id') or '').strip()
    if not root_folder_id:
        return JsonResponse({'success': False, 'error': 'root_folder_id is required'}, status=400)

    profile.root_folder_id = root_folder_id
    profile.save(update_fields=['root_folder_id'])
    return JsonResponse({'success': True})


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def create_and_set_root_folder(request, profile_id: int):
    profile = get_object_or_404(DriveProfile, id=profile_id)
    folder_name = (request.POST.get('folder_name') or '').strip()
    parent_id = (request.POST.get('parent_id') or '').strip() or None

    if not folder_name:
        return JsonResponse({'success': False, 'error': 'folder_name is required'}, status=400)

    drive = DriveService(credentials_path=profile.credentials_file.path, root_folder_id=profile.root_folder_id or None)
    new_folder_id = drive.create_folder(folder_name, parent_id=parent_id)

    profile.root_folder_id = new_folder_id
    profile.save(update_fields=['root_folder_id'])

    return JsonResponse({'success': True, 'root_folder_id': new_folder_id})


@login_required
@user_passes_test(is_admin)
def drive_settings_redirect(request):
    return redirect('pdfs:drive_settings')
