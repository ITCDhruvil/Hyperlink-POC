from django.urls import path
from . import views
from . import api_folder_config
from . import views_processor_ui
from . import views_auth
from . import views_drive_explorer

app_name = 'pdfs'

urlpatterns = [
    # Authentication
    path('login/', views_auth.login_view, name='login'),
    path('logout/', views_auth.logout_view, name='logout'),

    # User Management (Admin Only)
    path('users/', views_auth.user_management, name='user_management'),
    path('users/<int:user_id>/history/', views_auth.user_processing_history, name='user_processing_history'),
    path('users/create/', views_auth.create_user, name='create_user'),
    path('users/<int:user_id>/delete/', views_auth.delete_user, name='delete_user'),
    path('users/<int:user_id>/toggle-active/', views_auth.toggle_user_active, name='toggle_user_active'),
    path('users/<int:user_id>/toggle-admin/', views_auth.toggle_user_admin, name='toggle_user_admin'),

    # Main Application: Processor UI
    path('', views_processor_ui.processor_ui, name='index'),
    path('history/', views_processor_ui.processing_history, name='processing_history'),

    # Analytics Dashboard
    path('analytics/', views_processor_ui.analytics_dashboard, name='analytics_dashboard'),
    path('analytics/run/<str:run_id>/', views_processor_ui.analytics_run_detail, name='analytics_run_detail'),

    # Drive Explorer
    path('drive-explorer/', views_drive_explorer.drive_explorer_page, name='drive_explorer_page'),
    path('api/drive/status/', views_drive_explorer.drive_status, name='api_drive_status'),
    path('api/drive/list/', views_drive_explorer.drive_list, name='api_drive_list'),
    path('api/drive/file/<str:file_id>/', views_drive_explorer.drive_file_proxy, name='api_drive_file_proxy'),
    path('api/drive/upload-original/', views_drive_explorer.drive_upload_original, name='api_drive_upload_original'),

    # Processor UI endpoints
    path('upload-document/', views_processor_ui.upload_document, name='upload_document'),
    path('process-document/<int:document_id>/', views_processor_ui.process_document, name='process_document'),
    path('download-document/<int:document_id>/', views_processor_ui.download_document, name='download_document'),
    path('preflight-split/', views_processor_ui.start_preflight_split, name='start_preflight_split'),
    path('preflight-split-status/<str:job_id>/', views_processor_ui.preflight_split_status, name='preflight_split_status'),
    path('start-async-split/<str:job_id>/', views_processor_ui.start_async_split, name='start_async_split'),
    path('async-split-status/<str:job_id>/', views_processor_ui.async_split_status, name='async_split_status'),
    path('start-async-upload/<str:job_id>/', views_processor_ui.start_async_upload, name='start_async_upload'),
    path('async-upload-status/<str:job_id>/', views_processor_ui.async_upload_status, name='async_upload_status'),
    path('retry-async-split/<str:job_id>/', views_processor_ui.retry_async_split, name='retry_async_split'),
    path('retry-async-upload/<str:job_id>/', views_processor_ui.retry_async_upload, name='retry_async_upload'),
    path('split-pdf/', views_processor_ui.split_pdf_document, name='split_pdf_document'),
    path('extract-page-ranges/', views_processor_ui.extract_page_ranges_from_word, name='extract_page_ranges'),
    path('unified-preview/', views_processor_ui.unified_process_preview, name='unified_preview'),
    path('unified-complete/', views_processor_ui.unified_process_complete, name='unified_complete'),
    path('download-split-zip/<str:job_id>/', views_processor_ui.download_split_zip, name='download_split_zip'),
    path('upload-split-to-drive/<str:job_id>/', views_processor_ui.upload_split_to_drive, name='upload_split_to_drive'),

    # Folder Configuration API
    path('api/folder-config/', api_folder_config.get_folder_config, name='api_get_folder_config'),
    path('api/folder-config/update/', api_folder_config.update_folder_config, name='api_update_folder_config'),
    path('api/folder-config/test/', api_folder_config.test_folder_config, name='api_test_folder_config'),
    path('api/folder-config/structure-types/', api_folder_config.get_available_structure_types, name='api_get_structure_types'),
]
