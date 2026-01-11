"""
Processing History Model
Track document processing with timing and status
"""
from django.db import models


class ProcessingHistory(models.Model):
    """Track document processing history"""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    # Input document
    input_filename = models.CharField(max_length=500)
    input_file = models.FileField(upload_to='processing/inputs/%Y/%m/%d/')

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
