# Processing History Page - User Guide

## Overview

The Processing History page provides a comprehensive view of all processed documents with detailed metadata and statistics.

## Features

### 1. **Statistics Dashboard**
- **Total Documents**: Shows total number of processed documents
- **Successful**: Count of successfully processed documents
- **Failed**: Count of failed processing attempts
- **Pending**: Count of documents waiting to be processed
- **Success Rate**: Percentage of successful processing

### 2. **Document List**
Each document entry displays:
- **Filename**: Original input filename
- **Upload Date**: When the document was uploaded
- **Status Badge**: Visual indicator (SUCCESS, FAILED, PENDING, PROCESSING)
- **Patient Name**: Extracted patient name (if available)
- **Processing Metrics**:
  - Total Statements
  - Linked Statements (for successful processing)
  - Unlinked Statements (if any)
  - Processing Time (in seconds)
  - Processed Date

### 3. **Error Messages**
For failed documents, detailed error messages are displayed to help troubleshoot issues.

### 4. **Download Actions**
- **Download Output**: Download the processed document (if successful)
- **Download Input**: Download the original uploaded document

### 5. **Pagination**
- Shows 10 documents per page
- Navigation: First, Previous, Next, Last buttons
- Page indicator shows current page and total pages
- Example: "Page 2 of 5"

## Access

### From Processor UI
URL: `http://127.0.0.1:8004/history/`

Or click the **"View History"** link in the Processor UI navigation

### From Main Dashboard
Navigate to History from the main dashboard

## UI Design

### Visual Elements
- **Gradient Background**: Purple gradient for modern look
- **Card-based Layout**: Clean white cards with shadows
- **Status Badges**: Color-coded for quick status identification
  - Green: SUCCESS
  - Red: FAILED
  - Yellow: PENDING
  - Blue: PROCESSING
- **Hover Effects**: Interactive elements highlight on hover
- **Responsive Grid**: Adapts to different screen sizes

### Color Scheme
- **Success**: Green (#16a34a)
- **Failed**: Red (#dc2626)
- **Pending**: Orange (#f59e0b)
- **Processing**: Blue (#1e40af)
- **Primary**: Dark Gray (#111827)
- **Secondary**: Light Gray (#6b7280)

## Example Data Display

```
┌─────────────────────────────────────────────────────────┐
│ Statistics                                               │
├─────────────────────────────────────────────────────────┤
│  Total: 156    Success: 142    Failed: 8    Pending: 6  │
│  Success Rate: 91.0%                                     │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Patient_Records_2026.docx          [SUCCESS]            │
│ Jan 10, 2026 - 14:23:45                                 │
├─────────────────────────────────────────────────────────┤
│ Patient: Ahmad Al Yabroudi                              │
│ Total Statements: 13                                     │
│ Linked: 13                                              │
│ Processing Time: 24.56s                                 │
│ Processed: Jan 10, 2026 - 14:24:10                     │
├─────────────────────────────────────────────────────────┤
│ [Download Output] [Download Input]                     │
└─────────────────────────────────────────────────────────┘
```

## Pagination Example

When you have more than 10 documents:

```
[First] [Previous]  Page 2 of 5  [Next] [Last]
```

- Click **First** to go to page 1
- Click **Previous** to go to the previous page
- Click **Next** to go to the next page
- Click **Last** to go to the final page

## Technical Details

### Backend
- **View**: `processing_history()` in `views_processor_ui.py`
- **Model**: Uses `ProcessingHistory` model
- **Pagination**: Django Paginator (10 items per page)
- **URL**: `/history/`

### Template
- **File**: `pdfs/templates/pdfs/processing_history.html`
- **Framework**: Bootstrap 5.3.0
- **Style**: Custom CSS with modern design

### Database Fields Used
- `input_filename`: Original file name
- `output_filename`: Processed file name
- `patient_name`: Extracted patient name
- `status`: Processing status
- `processing_time_seconds`: Time taken to process
- `total_statements`: Total statements found
- `linked_statements`: Successfully linked statements
- `unlinked_statements`: Failed to link statements
- `uploaded_at`: Upload timestamp
- `processed_at`: Processing completion timestamp
- `error_message`: Error details (for failed documents)
- `user_friendly_error`: User-friendly error message

## Empty State

When no documents have been processed, the page displays:

```
    📄

    No Processing History

    Start processing documents to see them here
```

## Benefits

1. **Audit Trail**: Complete history of all processing activities
2. **Troubleshooting**: Easy identification of failed documents with error messages
3. **Performance Monitoring**: Track processing times and success rates
4. **Data Recovery**: Download original and processed files at any time
5. **Quality Assurance**: Review linked vs unlinked statements
6. **Patient Tracking**: Quick search by patient name
7. **Pagination**: Efficient handling of large document lists

## Future Enhancements

Potential features to add:
- Search and filter functionality
- Date range filtering
- Export to CSV/Excel
- Bulk actions (reprocess, delete)
- Sorting by columns
- Status filtering (show only failed, etc.)
- Patient name filtering
- Processing time charts
- Success rate trends over time

## Navigation

### Available Routes
- **From Processor**: Click "View History" link
- **To Processor**: Click "Back to Processor" button
- **To Dashboard**: Click "Main Dashboard" button

---

**Last Updated**: January 2026
**Version**: 1.0.0
