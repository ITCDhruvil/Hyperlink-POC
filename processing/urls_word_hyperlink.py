"""
URL routes for Word Document Hyperlink Processing API
"""
from django.urls import path
from .views_word_hyperlink import (
    word_hyperlink_ui,
    process_word_with_hyperlinks,
    get_drive_folder_pdfs,
    upload_word_to_drive
)

urlpatterns = [
    # UI endpoint
    path('word-processor/', word_hyperlink_ui, name='word_hyperlink_ui'),

    # Main processing endpoint
    path('api/word/process-hyperlinks/', process_word_with_hyperlinks, name='process_word_hyperlinks'),

    # Helper endpoints
    path('api/word/list-pdfs/', get_drive_folder_pdfs, name='list_drive_pdfs'),
    path('api/word/upload/', upload_word_to_drive, name='upload_word_to_drive'),
]
