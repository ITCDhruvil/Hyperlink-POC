from django.db import models
from django.core.validators import MinValueValidator
from django.conf import settings
import uuid

class Patient(models.Model):
    """Patient information"""
    patient_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    contact = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Patient'
        verbose_name_plural = 'Patients'

    def __str__(self):
        return f"{self.patient_id} - {self.name}"


class OriginalPDF(models.Model):
    """Original uploaded PDF file"""
    filename = models.CharField(max_length=500)
    file_path = models.FileField(upload_to='originals/%Y/%m/%d/')
    sha256 = models.CharField(max_length=64, unique=True, db_index=True)
    total_pages = models.IntegerField(validators=[MinValueValidator(1)])
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Original PDF'
        verbose_name_plural = 'Original PDFs'

    def __str__(self):
        return f"{self.filename} ({self.total_pages} pages)"


class PDFSet(models.Model):
    """Individual patient PDF section split from original"""
    STATE_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('UPLOADED', 'Uploaded'),
        ('DUPLICATE', 'Duplicate'),
        ('FAILED', 'Failed'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='pdf_sets')
    original_pdf = models.ForeignKey(OriginalPDF, on_delete=models.CASCADE, related_name='pdf_sets')
    
    # Page range in original PDF
    start_page = models.IntegerField(validators=[MinValueValidator(1)])
    end_page = models.IntegerField(validators=[MinValueValidator(1)])
    
    # Local storage
    local_path = models.CharField(max_length=1000, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    
    # Google Drive info
    drive_file_id = models.CharField(max_length=255, blank=True)
    drive_webview_link = models.URLField(max_length=500, blank=True)
    drive_folder_path = models.CharField(max_length=1000, blank=True)
    
    # Processing state
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True)
    
    # Metadata
    date = models.DateField(null=True, blank=True)
    hospital = models.CharField(max_length=255, blank=True)
    section_type = models.CharField(max_length=100, blank=True, default='Medical_Records')  # e.g., 'Cover_Letter', 'Attestation', etc.
    doctor_name = models.CharField(max_length=255, blank=True)  # Extracted doctor name for file naming

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'PDF Set'
        verbose_name_plural = 'PDF Sets'
        indexes = [
            models.Index(fields=['state']),
            models.Index(fields=['patient', 'created_at']),
        ]

    def __str__(self):
        return f"{self.patient.name} - Pages {self.start_page}-{self.end_page} ({self.state})"


class DriveFolderCache(models.Model):
    """Cache for Google Drive folder IDs to reduce API calls"""
    folder_path = models.CharField(max_length=1000, unique=True, db_index=True)
    drive_folder_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Drive Folder Cache'
        verbose_name_plural = 'Drive Folder Caches'

    def __str__(self):
        return f"{self.folder_path} -> {self.drive_folder_id}"


class DriveProfile(models.Model):
    name = models.CharField(max_length=200, unique=True)
    credentials_file = models.FileField(upload_to='drive_credentials/')
    root_folder_id = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', 'name']
        verbose_name = 'Drive Profile'
        verbose_name_plural = 'Drive Profiles'

    def __str__(self):
        return self.name

    @classmethod
    def get_active_profile(cls):
        return cls.objects.filter(is_active=True).first()


class SummaryDocument(models.Model):
    """Generated Word document with hyperlinks"""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='summaries')
    file_path = models.CharField(max_length=1000)
    generated_at = models.DateTimeField(auto_now_add=True)
    pdf_sets_included = models.ManyToManyField(PDFSet, related_name='summaries')

    class Meta:
        ordering = ['-generated_at']
        verbose_name = 'Summary Document'
        verbose_name_plural = 'Summary Documents'

    def __str__(self):
        return f"Summary for {self.patient.name} - {self.generated_at.strftime('%Y-%m-%d')}"


class FolderStructureConfig(models.Model):
    """
    Configurable folder structure settings
    Can be updated from frontend/API without code changes
    """

    STRUCTURE_TYPES = [
        ('FLAT', 'Flat: Root/PatientName/*.pdf'),
        ('WITH_SPLITS', 'With Splits: Root/PatientName/splits/*.pdf'),
        ('YEAR_MONTH', 'Year/Month: Root/Year/Month/PatientName/*.pdf'),
        ('CUSTOM', 'Custom structure'),
    ]

    config_name = models.CharField(max_length=100, unique=True, default='default')
    structure_type = models.CharField(max_length=20, choices=STRUCTURE_TYPES, default='FLAT')
    root_folder_id = models.CharField(max_length=255, help_text="Google Drive root folder ID")
    path_template = models.CharField(max_length=500, blank=True, help_text="Path template for CUSTOM type")
    pdf_subfolder = models.CharField(max_length=100, blank=True, help_text="Subfolder for PDFs (e.g., 'splits') or empty")
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', 'config_name']
        verbose_name = 'Folder Structure Configuration'
        verbose_name_plural = 'Folder Structure Configurations'

    def __str__(self):
        return f"{self.config_name} ({self.get_structure_type_display()})"

    def get_path_for_patient(self, patient_name: str, **kwargs) -> str:
        """Generate folder path for a patient based on configuration"""
        if self.structure_type == 'FLAT':
            return patient_name
        elif self.structure_type == 'WITH_SPLITS':
            return f"{patient_name}/{self.pdf_subfolder}" if self.pdf_subfolder else patient_name
        elif self.structure_type == 'YEAR_MONTH':
            year = kwargs.get('year', '')
            month = kwargs.get('month', '')
            path = f"{year}/{month}/{patient_name}"
            if self.pdf_subfolder:
                path = f"{path}/{self.pdf_subfolder}"
            return path
        elif self.structure_type == 'CUSTOM':
            return self.path_template.format(
                patient_name=patient_name,
                year=kwargs.get('year', ''),
                month=kwargs.get('month', ''),
                ot_number=kwargs.get('ot_number', '')
            )
        return patient_name

    def save(self, *args, **kwargs):
        """Clear cache when configuration changes"""
        from django.core.cache import cache
        super().save(*args, **kwargs)
        cache.delete('active_folder_structure_config')

    @classmethod
    def get_active_config(cls):
        """Get the active folder structure configuration"""
        from django.core.cache import cache
        from django.conf import settings

        config = cache.get('active_folder_structure_config')
        if config is None:
            config = cls.objects.filter(is_active=True).first()
            if config is None:
                config, _ = cls.objects.get_or_create(
                    config_name='default',
                    defaults={
                        'structure_type': 'FLAT',
                        'root_folder_id': '',
                        'is_active': True,
                        'description': 'Default flat structure: Root/PatientName/*.pdf'
                    }
                )

        # Keep DB config in sync with current settings (single source of truth)
        desired_root = getattr(settings, 'GOOGLE_DRIVE_ROOT_FOLDER_ID', '') or ''
        if desired_root and config.root_folder_id != desired_root:
            old_root = config.root_folder_id
            config.root_folder_id = desired_root
            config.save(update_fields=['root_folder_id', 'updated_at'])

            # Clear folder cache because it can contain IDs from the previous root tree
            if old_root and old_root != desired_root:
                try:
                    DriveFolderCache.objects.all().delete()
                except Exception:
                    pass

            cache.delete('active_folder_structure_config')

        cache.set('active_folder_structure_config', config, 3600)
        return config


class ProcessingHistory(models.Model):
    """Track document processing history with timing and status"""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    # Input document
    input_filename = models.CharField(max_length=500)
    input_file = models.FileField(upload_to='processing/inputs/%Y/%m/%d/')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processing_histories'
    )

    # Output document
    output_filename = models.CharField(max_length=500, blank=True)
    output_file = models.FileField(upload_to='processing/outputs/%Y/%m/%d/', blank=True, null=True)

    # Patient info
    patient_name = models.CharField(max_length=255, blank=True)
    folder_id = models.CharField(max_length=255, blank=True)

    # Processing details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    processing_time_seconds = models.FloatField(null=True, blank=True)

    # Results
    total_statements = models.IntegerField(default=0)
    linked_statements = models.IntegerField(default=0)
    unlinked_statements = models.IntegerField(default=0)

    # Error handling
    error_message = models.TextField(blank=True)
    user_friendly_error = models.TextField(blank=True)

    # Timestamps
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Processing History'
        verbose_name_plural = 'Processing Histories'

    def __str__(self):
        return f"{self.input_filename} - {self.status} ({self.processing_time_seconds}s)"


class ProcessingRun(models.Model):
    MODE_CHOICES = [
        ('ASYNC', 'Async'),
        ('SYNC', 'Sync'),
    ]

    STATUS_CHOICES = [
        ('RUNNING', 'Running'),
        ('SUCCESS', 'Success'),
        ('PARTIAL_SUCCESS', 'Partial Success'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identifiers
    job_id = models.CharField(max_length=64, blank=True, db_index=True)
    run_mode = models.CharField(max_length=10, choices=MODE_CHOICES)

    # Link to existing history record when applicable
    processing_history = models.ForeignKey(
        ProcessingHistory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='runs',
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processing_runs',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RUNNING')

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.BigIntegerField(null=True, blank=True)

    # High-level metadata for filtering/analysis
    patient_name = models.CharField(max_length=255, blank=True)
    input_pdf_name = models.CharField(max_length=500, blank=True)
    input_pdf_size_bytes = models.BigIntegerField(null=True, blank=True)
    input_docx_name = models.CharField(max_length=500, blank=True)
    input_docx_size_bytes = models.BigIntegerField(null=True, blank=True)

    page_count_total = models.IntegerField(null=True, blank=True)
    outputs_requested = models.IntegerField(null=True, blank=True)
    total_extracted_pages = models.IntegerField(null=True, blank=True)
    split_chunk_size = models.IntegerField(null=True, blank=True)
    split_backend = models.CharField(max_length=32, blank=True)

    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)

    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.run_mode} {self.job_id or self.id} - {self.status}"


class ProcessingStep(models.Model):
    STEP_CHOICES = [
        ('PREFLIGHT', 'Preflight'),
        ('SPLIT', 'Split'),
        ('UPLOAD', 'Upload'),
        ('WORD_PROCESS', 'Word Process'),
    ]

    STATUS_CHOICES = [
        ('RUNNING', 'Running'),
        ('SUCCESS', 'Success'),
        ('PARTIAL_SUCCESS', 'Partial Success'),
        ('FAILED', 'Failed'),
        ('SKIPPED', 'Skipped'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(ProcessingRun, on_delete=models.CASCADE, related_name='steps')

    step = models.CharField(max_length=20, choices=STEP_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RUNNING')

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.BigIntegerField(null=True, blank=True)

    count_total = models.IntegerField(null=True, blank=True)
    count_done = models.IntegerField(null=True, blank=True)
    count_failed = models.IntegerField(null=True, blank=True)

    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['run', 'started_at']
        indexes = [
            models.Index(fields=['step', 'status']),
        ]

    def __str__(self):
        return f"{self.run_id} {self.step} - {self.status}"
