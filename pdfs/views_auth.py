"""
Authentication views for user login, signup, and user management
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import re

from .models import ProcessingHistory


def is_admin(user):
    """Check if user is staff/admin"""
    return user.is_staff or user.is_superuser


@login_required
@user_passes_test(is_admin)
def user_processing_history(request, user_id: int):
    """Admin-only: show processing history for a specific user."""
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    from django.db.models import Q

    target_user = get_object_or_404(User, id=user_id)

    include_unassigned = request.GET.get('include_unassigned') in ('1', 'true', 'yes')
    if include_unassigned:
        history_list = ProcessingHistory.objects.filter(
            Q(user=target_user) | Q(user__isnull=True)
        ).order_by('-uploaded_at')
    else:
        history_list = ProcessingHistory.objects.filter(user=target_user).order_by('-uploaded_at')

    paginator = Paginator(history_list, 10)
    page = request.GET.get('page', 1)

    try:
        history_items = paginator.page(page)
    except PageNotAnInteger:
        history_items = paginator.page(1)
    except EmptyPage:
        history_items = paginator.page(paginator.num_pages)

    total_documents = history_list.count()
    successful_documents = history_list.filter(status='SUCCESS').count()
    failed_documents = history_list.filter(status='FAILED').count()
    pending_documents = history_list.filter(status='PENDING').count()

    context = {
        'history_items': history_items,
        'total_documents': total_documents,
        'successful_documents': successful_documents,
        'failed_documents': failed_documents,
        'pending_documents': pending_documents,
        'success_rate': round((successful_documents / total_documents * 100) if total_documents > 0 else 0, 1),
        'filter_user': target_user,
        'include_unassigned': include_unassigned,
    }

    return render(request, 'pdfs/processing_history.html', context)


def login_view(request):
    """User login view"""
    if request.user.is_authenticated:
        return redirect('pdfs:index')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        # Find user by email
        try:
            user_obj = User.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)

            if user is not None:
                if user.is_active:
                    login(request, user)
                    next_url = request.GET.get('next', 'pdfs:index')
                    return redirect(next_url)
                else:
                    messages.error(request, 'Your account has been deactivated. Please contact the administrator.')
            else:
                messages.error(request, 'Invalid email or password.')
        except User.DoesNotExist:
            messages.error(request, 'Invalid email or password.')

    return render(request, 'pdfs/login.html')


def signup_view(request):
    """User signup view"""
    if request.user.is_authenticated:
        return redirect('pdfs:index')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # Validate email format
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            messages.error(request, 'Please enter a valid email address.')
            return render(request, 'pdfs/signup.html')

        # Check if email already exists
        if User.objects.filter(email=email).exists():
            messages.error(request, 'An account with this email already exists.')
            return render(request, 'pdfs/signup.html')

        # Validate password match
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'pdfs/signup.html')

        # Validate password length
        if len(password) < 6:
            messages.error(request, 'Password must be at least 6 characters long.')
            return render(request, 'pdfs/signup.html')

        # Create user
        username = email.split('@')[0]  # Use email prefix as username
        base_username = username
        counter = 1

        # Ensure unique username
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        user.is_active = True
        user.save()

        messages.success(request, 'Account created successfully! Please log in.')
        return redirect('pdfs:login')

    return render(request, 'pdfs/signup.html')


def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('pdfs:login')


@login_required
@user_passes_test(is_admin)
def user_management(request):
    """User management page - admin only"""
    users = User.objects.all().order_by('-is_superuser', '-is_staff', 'email')

    context = {
        'users': users,
        'total_users': users.count(),
        'admin_users': users.filter(is_staff=True).count(),
        'active_users': users.filter(is_active=True).count(),
    }

    return render(request, 'pdfs/user_management.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def create_user(request):
    """Create new user - admin only"""
    email = request.POST.get('email', '').strip()
    password = request.POST.get('password', '')
    is_admin_user = request.POST.get('is_admin') == 'true'

    # Validate email format
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_regex, email):
        return JsonResponse({'success': False, 'error': 'Please enter a valid email address.'})

    # Check if email already exists
    if User.objects.filter(email=email).exists():
        return JsonResponse({'success': False, 'error': 'An account with this email already exists.'})

    # Validate password length
    if len(password) < 6:
        return JsonResponse({'success': False, 'error': 'Password must be at least 6 characters long.'})

    # Create user
    username = email.split('@')[0]
    base_username = username
    counter = 1

    # Ensure unique username
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password
    )
    user.is_active = True
    user.is_staff = is_admin_user
    user.save()

    return JsonResponse({
        'success': True,
        'message': f'User {email} created successfully.',
        'user': {
            'id': user.id,
            'email': user.email,
            'is_admin': user.is_staff,
            'is_active': user.is_active,
        }
    })


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def delete_user(request, user_id):
    """Delete user - admin only"""
    if request.user.id == user_id:
        return JsonResponse({'success': False, 'error': 'You cannot delete your own account.'})

    user = get_object_or_404(User, id=user_id)

    if user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Cannot delete superuser account.'})

    email = user.email
    user.delete()

    return JsonResponse({'success': True, 'message': f'User {email} deleted successfully.'})


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def toggle_user_active(request, user_id):
    """Activate/deactivate user - admin only"""
    if request.user.id == user_id:
        return JsonResponse({'success': False, 'error': 'You cannot deactivate your own account.'})

    user = get_object_or_404(User, id=user_id)

    if user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Cannot deactivate superuser account.'})

    user.is_active = not user.is_active
    user.save()

    status = 'activated' if user.is_active else 'deactivated'
    return JsonResponse({
        'success': True,
        'message': f'User {user.email} {status} successfully.',
        'is_active': user.is_active
    })


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def toggle_user_admin(request, user_id):
    """Promote/demote user to admin - admin only"""
    if request.user.id == user_id:
        return JsonResponse({'success': False, 'error': 'You cannot modify your own admin status.'})

    user = get_object_or_404(User, id=user_id)

    if user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Cannot modify superuser status.'})

    user.is_staff = not user.is_staff
    user.save()

    status = 'promoted to admin' if user.is_staff else 'demoted to regular user'
    return JsonResponse({
        'success': True,
        'message': f'User {user.email} {status} successfully.',
        'is_admin': user.is_staff
    })
