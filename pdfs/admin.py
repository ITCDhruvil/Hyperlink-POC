from django.contrib import admin
from .models import Patient, OriginalPDF, PDFSet, DriveFolderCache, SummaryDocument

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('patient_id', 'name', 'contact', 'created_at')
    search_fields = ('patient_id', 'name', 'contact')
    list_filter = ('created_at',)

@admin.register(OriginalPDF)
class OriginalPDFAdmin(admin.ModelAdmin):
    list_display = ('filename', 'sha256', 'total_pages', 'uploaded_at')
    search_fields = ('filename', 'sha256')
    list_filter = ('uploaded_at',)
    readonly_fields = ('sha256', 'total_pages', 'uploaded_at')

@admin.register(PDFSet)
class PDFSetAdmin(admin.ModelAdmin):
    list_display = ('patient', 'original_pdf', 'start_page', 'end_page', 'state', 'created_at')
    search_fields = ('patient__name', 'patient__patient_id')
    list_filter = ('state', 'created_at')
    readonly_fields = ('sha256', 'drive_file_id', 'drive_webview_link')

@admin.register(DriveFolderCache)
class DriveFolderCacheAdmin(admin.ModelAdmin):
    list_display = ('folder_path', 'drive_folder_id', 'created_at')
    search_fields = ('folder_path', 'drive_folder_id')

@admin.register(SummaryDocument)
class SummaryDocumentAdmin(admin.ModelAdmin):
    list_display = ('patient', 'generated_at', 'file_path')
    search_fields = ('patient__name', 'patient__patient_id')
    list_filter = ('generated_at',)
