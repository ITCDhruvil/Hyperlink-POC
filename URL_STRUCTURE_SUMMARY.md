# Application URL Structure

## Overview

The PDF Automation System now has a simple, streamlined URL structure with only two main pages.

## Available Pages

### 1. Processor UI (Homepage)
- **URL**: `http://127.0.0.1:8004/`
- **Purpose**: Main application interface
- **Features**:
  - Three processing modes:
    - **One-Click**: Complete automation (Word + PDF upload)
    - **Auto Link**: Link Word documents to existing Drive PDFs
    - **Split PDF**: Manual PDF splitting with optional auto-extraction
  - Real-time progress tracking
  - Direct file uploads and downloads

### 2. Processing History
- **URL**: `http://127.0.0.1:8004/history/`
- **Purpose**: View all processed documents
- **Features**:
  - Complete document history
  - Pagination (10 items per page)
  - Statistics dashboard
  - Download processed and original files
  - Error tracking and messages

## Navigation

### From Processor UI
- **View History** → Links to `/history/`

### From History Page
- **Back to Processor** → Links to `/` (homepage)

## What Was Removed

The old "Advanced Dashboard" that was previously at `/` has been completely removed. This included:
- Batch PDF processing interface
- Auto-detect sections feature
- PDF sets management
- Patient management

## Current Architecture

```
Application Structure:
├── / (Processor UI - Default homepage)
│   ├── One-Click Mode
│   ├── Auto Link Mode
│   └── Split PDF Mode
└── /history/ (Processing History)
    ├── Document list (paginated)
    ├── Statistics
    └── Download options
```

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/` | Main Processor UI |
| `/history/` | Processing history page |
| `/extract-page-ranges/` | Extract page ranges from Word |
| `/unified-preview/` | One-Click preview step |
| `/unified-complete/` | One-Click processing with SSE |
| `/split-and-upload/` | Split PDF mode |
| `/auto-link/` | Auto link mode |
| `/upload-document/` | Upload document |
| `/process-document/<id>/` | Process document |
| `/download-document/<id>/` | Download result |

## File Changes Made

### 1. URL Configuration ([pdfs/urls.py](d:\hyperlink_POC\pdfs\urls.py))
- Set `/` to `processor_ui` view
- Removed all old dashboard routes (`/dashboard/`, `/upload/`, `/pdf/<id>/`, etc.)
- Kept only processor-related endpoints

### 2. Templates Updated

#### Processor UI ([processor_ui.html](d:\hyperlink_POC\pdfs\templates\pdfs\processor_ui.html))
- Removed "Advanced Dashboard" navigation link
- Kept only "View History" link

#### History Page ([processing_history.html](d:\hyperlink_POC\pdfs\templates\pdfs\processing_history.html))
- Removed "Advanced Dashboard" navigation button
- "Back to Processor" now links to `/` (homepage)

### 3. Documentation ([README.md](d:\hyperlink_POC\README.md))
- Updated Quick Start section
- Updated "Access the Application" section
- Removed "Workflow D: Advanced Dashboard"
- Simplified API Endpoints table
- Updated all URL references

## Benefits of New Structure

1. **Simplicity**: Only two pages to navigate
2. **Focus**: All processing features in one place
3. **Clarity**: Clear separation between processing and history
4. **Performance**: Removed unused dashboard code
5. **Maintainability**: Fewer routes to manage

## User Workflow

### Typical Usage
1. Start at `/` (Processor UI)
2. Choose a processing mode
3. Upload files and process
4. Download results
5. Check `/history/` to review past processing

### Quick Access
- Processor: `http://localhost:8004/`
- History: `http://localhost:8004/history/`

---

**Last Updated**: January 2026
**Version**: 2.1.0 (Simplified Structure)
