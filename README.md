# PDF Automation System

Intelligent PDF sectioning and Google Drive integration for medical document management with **three powerful workflows**.

## Workflows

### **Workflow 1: One-Click Processing** ✨ NEW
Upload Word + PDF → Auto-extract page ranges → Split → Upload → Link → Download (All in one step!)

### **Workflow 2: Auto Link Mode**
Upload Word docs with medical statements → Parse statements → Find matching PDFs → Attach Drive hyperlinks

### **Workflow 3: Split PDF Mode**
Upload PDFs → Split into sections → Upload to Drive → Generate Word summaries with hyperlinks

📖 **[View Detailed Workflows Overview](WORKFLOWS_OVERVIEW.md)**

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up Google Drive (see detailed instructions below)
# 3. Configure environment variables in .env

# 4. Run the server
python manage.py runserver 8004

# 5. Access UI
# Processor UI: http://127.0.0.1:8004/
# Processing History: http://127.0.0.1:8004/history/
```

## Features

✅ **Smart PDF Upload** - Upload large medical PDFs with multiple patient records
✅ **Auto-Detection** - AI-powered patient section detection with document type classification
✅ **PDF Splitting** - Automatically split PDFs by patient sections with descriptive naming
✅ **Google Drive Integration** - Organized Year/Month/Date/Patient folder hierarchy
✅ **Deduplication** - SHA-256 based duplicate detection
✅ **Word Document Generation** - Create summaries with verified hyperlinks
✅ **Reverse Linking** - Upload Word docs and auto-attach Drive links to statements
✅ **Background Processing** - Celery-based async task queue
✅ **Beautiful UI** - Modern, responsive dark-themed interface  

## Tech Stack

- **Backend**: Django 4.2
- **Task Queue**: Celery + Redis
- **PDF Processing**: PyPDF2, pikepdf
- **OCR**: Tesseract (optional)
- **ML**: Sentence Transformers
- **Cloud**: Google Drive API
- **Document Generation**: python-docx
- **Frontend**: HTML5, CSS3, Vanilla JavaScript

## Setup Instructions

### 1. Install Dependencies

```bash
# Activate virtual environment (already created)
.\venv\Scripts\activate

# Install packages (if not already done)
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and update:

```env
# Django Settings
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Google Drive API
GOOGLE_DRIVE_CREDENTIALS_PATH=credentials/service-account-key.json
GOOGLE_DRIVE_ROOT_FOLDER_ID=your-root-folder-id

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# File Upload
UPLOAD_MAX_SIZE=104857600
```

### 3. Google Drive API Setup (Complete Guide)

#### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click on the project dropdown at the top
3. Click "New Project"
4. Enter project name (e.g., "PDF-Automation")
5. Click "Create"
6. Wait for project creation to complete

#### Step 2: Enable Google Drive API

1. In the Google Cloud Console, select your project
2. Go to "APIs & Services" > "Library"
3. Search for "Google Drive API"
4. Click on it and press "Enable"
5. Wait for the API to be enabled

#### Step 3: Create Service Account

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Fill in the details:
   - Service account name: `pdf-automation-service`
   - Service account ID: (auto-generated)
   - Description: "Service account for PDF automation Drive access"
4. Click "Create and Continue"
5. Grant role: "Editor" (or custom role with Drive permissions)
6. Click "Continue" then "Done"

#### Step 4: Generate Service Account Key (JSON Credentials)

1. In "APIs & Services" > "Credentials"
2. Find your service account in the list
3. Click on the service account email
4. Go to the "Keys" tab
5. Click "Add Key" > "Create new key"
6. Select "JSON" format
7. Click "Create"
8. The JSON file will download automatically
9. Rename it to `service-account-key.json`
10. Place it in `credentials/` folder in your project

**IMPORTANT**: Keep this file secure! It provides full access to the service account.

#### Step 5: Set Up Google Drive Storage

You have two options:

**Option A: Shared Drive (Recommended for Teams)**

Why use Shared Drive:
- Storage quota counts against the organization, not the service account
- Service accounts have 15GB personal limit (fills up quickly)
- Better for collaboration and shared access
- More reliable for production use

Steps:
1. In Google Drive, click "Shared drives" in left sidebar
2. Click "New" button
3. Enter name (e.g., "PDF Automation Storage")
4. Click "Create"
5. Click "Manage members"
6. Add the service account email (found in JSON credentials file):
   - Look for the `client_email` field in your JSON file
   - Example: `pdf-automation-service@project-id.iam.gserviceaccount.com`
7. Grant "Content Manager" or "Manager" role
8. Click "Send"
9. Open the Shared Drive
10. Create a root folder (e.g., "Medical Records")
11. Get the folder ID from the URL:
    - URL format: `https://drive.google.com/drive/folders/FOLDER_ID_HERE`
    - Copy the `FOLDER_ID_HERE` part
12. Update `.env` file with this folder ID

**Option B: Personal Drive (Not Recommended for Production)**

Limitations:
- Service account has only 15GB storage quota
- Fills up quickly with medical documents
- Not suitable for long-term use

Steps:
1. Open Google Drive with your personal account
2. Create a folder (e.g., "PDF Automation Root")
3. Right-click the folder > "Share"
4. Add the service account email (from JSON credentials)
5. Grant "Editor" permission
6. Click "Send"
7. Open the folder and copy its ID from URL
8. Update `.env` file with this folder ID

#### Step 6: Configure Application

Update your `.env` file:

```env
# Path to the JSON credentials file
GOOGLE_DRIVE_CREDENTIALS_PATH=credentials/service-account-key.json

# The root folder ID from Step 5
GOOGLE_DRIVE_ROOT_FOLDER_ID=1a2b3c4d5e6f7g8h9i0j

# Example folder structure will be created as:
# Root Folder/
#   └── 2026/
#       └── 01_January/
#           └── 2026-01-10/
#               └── Patient Name/
#                   ├── 1-3.pdf
#                   ├── 4-6.pdf
#                   └── ...
```

#### Step 7: Verify Setup

Test your configuration:

```bash
python manage.py shell

>>> from processing.drive_utils import DriveAPIHandler
>>> handler = DriveAPIHandler()
>>> result = handler.test_connection()
>>> print(result)
# Should print: {'success': True, 'message': 'Connected successfully'}
```

Common issues:
- "Invalid credentials" - Check JSON file path and format
- "Folder not found" - Verify folder ID and service account has access
- "Insufficient permissions" - Grant "Content Manager" role to service account

### 4. Install Redis (for Celery)

**Windows:**
```bash
# Download Redis for Windows from:
# https://github.com/microsoftarchive/redis/releases

# Or use Docker:
docker run -d -p 6379:6379 redis:latest
```

**Linux/Mac:**
```bash
# Ubuntu/Debian
sudo apt-get install redis-server

# Mac
brew install redis
```

### 5. Run Database Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Create Superuser (Optional)

```bash
python manage.py createsuperuser
```

### 7. Start the Application

#### Option A: Start everything via the batch script (Windows)

```bat
scripts\start_all.bat
```

#### Option B: Start services manually (Windows)

Open **multiple PowerShell terminals** from the project root.

**Terminal 0 - Activate venv + set media root (recommended for consistency):**
```powershell
.\venv\Scripts\activate
$env:DJANGO_MEDIA_ROOT="D:\hyperlink_POC\Sample"
```

**Terminal 1 - Redis**
```powershell
redis-server
```

**Terminal 2 - Django backend**
```powershell
.\venv\Scripts\activate
$env:DJANGO_MEDIA_ROOT="D:\hyperlink_POC\Sample"
python manage.py runserver 8004
```

**Terminal 3 - Celery worker (split queue)**
```powershell
.\venv\Scripts\activate
$env:DJANGO_MEDIA_ROOT="D:\hyperlink_POC\Sample"
celery -A pdf_automation worker -l info -P solo -Q split -n split@%h
```

**Terminal 4/5/6 - Celery workers (upload queue x3 for parallel uploads)**
```powershell
.\venv\Scripts\activate
$env:DJANGO_MEDIA_ROOT="D:\hyperlink_POC\Sample"
celery -A pdf_automation worker -l info -P solo -Q upload -n upload1@%h
```

```powershell
.\venv\Scripts\activate
$env:DJANGO_MEDIA_ROOT="D:\hyperlink_POC\Sample"
celery -A pdf_automation worker -l info -P solo -Q upload -n upload2@%h
```

```powershell
.\venv\Scripts\activate
$env:DJANGO_MEDIA_ROOT="D:\hyperlink_POC\Sample"
celery -A pdf_automation worker -l info -P solo -Q upload -n upload3@%h
```

#### Verify Celery is connected

```powershell
.\venv\Scripts\activate
celery -A pdf_automation inspect ping
celery -A pdf_automation inspect active
```

### 8. Access the Application

Open your browser and navigate to:
- **Processor UI**: http://localhost:8004/
- **Processing History**: http://localhost:8004/history/
- **Admin Panel**: http://localhost:8004/admin

## Usage Workflows

### Workflow A: One-Click Processing (Recommended) ✨

**URL**: `http://127.0.0.1:8004/` (Default homepage)

**Best for**: Complete automation from upload to download

**Steps**:

1. **Upload Files**
   - Upload Word document (.docx) containing patient statements
   - Upload PDF file with medical records
   - Both files are uploaded simultaneously

2. **Preview & Verify**
   - Click "Preview & Verify" button
   - System extracts:
     - Patient name
     - Number of statements detected
     - Page ranges (e.g., "1-3", "4-6", "7-8")
   - Review the metadata before processing

3. **Process Everything**
   - Click "Process Everything" button
   - Watch real-time progress:
     - "Splitting: 1-3.pdf (1/13)" (20-50%)
     - "Uploading: 4-6.pdf (2/13)" (60-80%)
     - "Inserting hyperlinks..." (85-92%)
     - "Finalizing document..." (95-100%)
   - Progress bar shows exact percentage

4. **Download**
   - Processed Word document downloads automatically
   - Contains all hyperlinks to Drive PDFs
   - Patient folder created on Drive with all split PDFs

**Real-Time Status Updates**:
- File-by-file progress tracking
- Current operation displayed
- Visual progress bar (0-100%)
- Estimated completion shown

### Workflow B: Auto Link Mode

**Best for**: Linking existing Word documents to existing Drive PDFs

**Steps**:

1. Select "Auto Link" mode
2. Upload Word document with statements
3. System finds matching PDFs on Drive
4. Inserts hyperlinks automatically
5. Download processed document

### Workflow C: Split PDF Mode

**Best for**: Manual control over splitting and uploading

**Steps**:

1. Select "Split PDF" mode
2. Upload PDF file
3. **Auto-Extract** (Optional):
   - Click "Auto-Extract Page Ranges"
   - System reads page ranges from uploaded Word doc
   - Automatically populates the page ranges field
4. Enter or verify page ranges (format: `1-3;4-6;7-8`)
5. Enter patient name
6. Click "Split & Upload"
7. PDFs split and uploaded to Drive
8. Download summary document

## Document Format Requirements

### Word Document Format

Your Word document should contain medical statements in this format:

```
Date, Name, Address, Contact

Example:
01/15/2026, John Doe, 123 Main St, (555) 123-4567
02/20/2026, Jane Smith, 456 Oak Ave, (555) 987-6543
```

**Supported patterns**:
- With page ranges: `01/15/2026, John Doe, 123 Main St, (555) 123-4567 (Pages 1-3)`
- Without page ranges: `01/15/2026, John Doe, 123 Main St, (555) 123-4567`
- Various date formats: `MM/DD/YYYY`, `MM-DD-YYYY`, `YYYY-MM-DD`

### PDF Format

- Can be single or multi-page
- Should contain medical records
- Text-based (OCR support available for scanned documents)

## Real-Time Progress Tracking

The One-Click workflow provides detailed progress updates:

**Progress Phases**:
- **Initialization** (0-10%): Loading files, validating inputs
- **Extraction** (10-20%): Extracting page ranges from Word document
- **Splitting** (20-50%): Creating individual PDF files
  - Shows: "Splitting: 1-3.pdf (1/13)"
- **Uploading** (60-80%): Uploading to Google Drive
  - Shows: "Uploading: 4-6.pdf (2/13)"
- **Linking** (85-92%): Inserting hyperlinks into Word document
- **Finalization** (95-100%): Preparing final document

**Technical Implementation**:
- Server-Sent Events (SSE) for streaming updates
- Real-time DOM updates via JavaScript ReadableStream
- No page refresh required

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Processor UI (Main application) |
| `/history/` | GET | Processing history with pagination |
| `/extract-page-ranges/` | POST | Extract page ranges from Word doc |
| `/unified-preview/` | POST | Preview metadata (One-Click step 1) |
| `/unified-complete/` | POST | Complete processing with SSE progress |
| `/split-and-upload/` | POST | Split PDF and upload to Drive |
| `/auto-link/` | POST | Auto-link Word doc to Drive PDFs |
| `/upload-document/` | POST | Upload document for processing |
| `/process-document/<id>/` | POST | Process uploaded document |
| `/download-document/<id>/` | GET | Download processed document |

## Folder Structure

```
hyperlink_POC/
├── pdf_automation/          # Django project
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
│   └── __init__.py
├── pdfs/                    # Main app
│   ├── models.py           # Database models
│   ├── views.py            # API views
│   ├── admin.py            # Admin configuration
│   └── urls.py             # URL routing
├── processing/              # Processing utilities
│   ├── pdf_utils.py        # PDF operations
│   ├── drive_utils.py      # Google Drive API
│   ├── docx_utils.py       # Word generation
│   └── tasks.py            # Celery tasks
├── static/                  # Static files
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js
├── templates/               # HTML templates
│   └── index.html
├── media/                   # Uploaded files
│   ├── originals/          # Original PDFs
│   ├── split_pdfs/         # Split PDFs
│   └── summaries/          # Generated Word docs
├── credentials/             # Google API credentials
│   └── service-account-key.json
├── requirements.txt
├── .env
└── README.md
```

## Security Considerations

⚠️ **IMPORTANT for PHI/Medical Data:**

1. **Encryption**: Service account keys are encrypted at rest
2. **Access Control**: Domain-restricted Drive permissions only
3. **Network Security**: Run in secure network segment
4. **Audit Logs**: All operations tracked in database
5. **Data Retention**: Implement automatic purge policies
6. **No Public Links**: NEVER use `anyoneWithLink` for PHI
7. **Compliance**: Ensure HIPAA/GDPR compliance

## Troubleshooting

### Google Drive Issues

**Issue**: "Invalid credentials" error
**Solution**:
- Verify `credentials/service-account-key.json` exists and is valid JSON
- Check `GOOGLE_DRIVE_CREDENTIALS_PATH` in `.env` file
- Re-download service account key from Google Cloud Console

**Issue**: "Folder not found" or "Insufficient permissions"
**Solution**:
- Verify `GOOGLE_DRIVE_ROOT_FOLDER_ID` is correct
- Ensure service account email is added to the folder/Shared Drive
- Grant "Content Manager" or "Manager" role to service account
- Check if folder was deleted or moved

**Issue**: "Storage quota exceeded"
**Solution**:
- If using personal Drive, switch to Shared Drive
- Service accounts have 15GB limit on personal storage
- Shared Drive uses organization quota

**Issue**: Upload succeeds but files not visible
**Solution**:
- Check if files are in "Trash"
- Verify you're looking in the correct folder
- Service account creates files that may not be visible in "My Drive"
- Access via Shared Drive or shared folder

### Application Issues

**Issue**: Celery not processing tasks
**Solution**:
- Ensure Redis is running: `redis-cli ping` (should return "PONG")
- Start Celery worker: `celery -A pdf_automation worker --loglevel=info --pool=solo`
- Check Celery logs for errors

**Issue**: PDF detection not working
**Solution**:
- Check PDF is text-based (not scanned images)
- For scanned PDFs, install Tesseract OCR
- Adjust detection patterns in [pdf_utils.py](processing/pdf_utils.py)

**Issue**: Module not found errors
**Solution**:
- Activate virtual environment: `.\venv\Scripts\activate`
- Reinstall requirements: `pip install -r requirements.txt`

**Issue**: Real-time progress not updating
**Solution**:
- Check browser console for JavaScript errors
- Verify Server-Sent Events are not blocked by proxy/firewall
- Try different browser (Chrome/Firefox recommended)

**Issue**: "Session expired" error in One-Click mode
**Solution**:
- Session timeout after 1 hour of inactivity
- Re-upload files and start again
- Temporary files are cleaned up automatically

**Issue**: Page ranges not extracted correctly
**Solution**:
- Verify Word document follows format: "Date, Name, Address, Contact (Pages 1-3)"
- Check that page ranges are in parentheses
- Use semicolon separator for manual entry: `1-3;4-6;7-8`

### Performance Issues

**Issue**: Slow processing with large PDFs
**Solution**:
- Split large PDFs into smaller batches
- Use Shared Drive for faster uploads
- Increase timeout values in settings
- Monitor network bandwidth

**Issue**: High memory usage
**Solution**:
- Process PDFs in smaller batches
- Reduce `UPLOAD_MAX_SIZE` in `.env`
- Monitor Celery worker memory

### Windows-Specific Issues

**Issue**: Redis installation on Windows
**Solution**:
- Use Docker: `docker run -d -p 6379:6379 redis:latest`
- Or download from: https://github.com/microsoftarchive/redis/releases
- Or use WSL2 with Linux Redis

**Issue**: Path issues with backslashes
**Solution**:
- Use forward slashes in `.env`: `credentials/service-account-key.json`
- Or escape backslashes: `credentials\\service-account-key.json`

## Architecture

### System Overview

```
┌─────────────┐
│   Browser   │
│   (User)    │
└──────┬──────┘
       │ HTTP/SSE
       ▼
┌─────────────────────────────────────────┐
│          Django Application             │
│  ┌────────────────────────────────────┐ │
│  │    Views (views_processor_ui.py)   │ │
│  │  - One-Click workflow              │ │
│  │  - Real-time progress (SSE)        │ │
│  │  - Session management              │ │
│  └─────────────┬──────────────────────┘ │
│                │                         │
│  ┌─────────────▼──────────────────────┐ │
│  │  Processing Layer                   │ │
│  │  - word_hyperlink_processor_simple  │ │
│  │  - PDF splitting (pikepdf)          │ │
│  │  - Page range extraction            │ │
│  └─────────────┬──────────────────────┘ │
└────────────────┼─────────────────────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
┌────────┐  ┌─────────┐  ┌──────────┐
│ Redis  │  │  Drive  │  │  Local   │
│ (Queue)│  │   API   │  │  Storage │
└────────┘  └─────────┘  └──────────┘
```

### Data Flow (One-Click Workflow)

```
1. Upload Phase
   User uploads Word + PDF → Stored in session → Temporary storage

2. Preview Phase
   Word doc → Extract page ranges → Extract patient name → Return metadata

3. Processing Phase (with SSE)
   ├─ Split PDF by page ranges (20-50%)
   ├─ Create folder structure on Drive (55-60%)
   ├─ Upload split PDFs to Drive (60-80%)
   ├─ Get Drive links for each PDF (82-85%)
   ├─ Insert hyperlinks into Word doc (85-92%)
   └─ Save final document (95-100%)

4. Download Phase
   Final Word doc → User downloads → Session cleanup
```

### Technology Stack Details

**Backend**:
- Django 4.2 - Web framework
- Django REST Framework - API endpoints
- Celery - Background task processing (Dashboard workflow)
- Server-Sent Events - Real-time progress streaming (One-Click)

**Storage & Queue**:
- Redis - Celery broker and result backend
- Local filesystem - Temporary file storage
- Google Drive - Permanent document storage

**Document Processing**:
- python-docx - Word document manipulation
- pikepdf - PDF splitting and manipulation
- PyPDF2 - PDF reading and analysis
- Sentence Transformers - ML-based text matching (optional)

**Cloud Integration**:
- Google Drive API v3 - File upload and folder management
- Google Cloud Service Accounts - Authentication
- OAuth 2.0 - Authorization flow

**Frontend**:
- Vanilla JavaScript - UI interactions
- ReadableStream API - SSE message parsing
- HTML5 + CSS3 - Modern responsive design

## Performance Benchmarks

**One-Click Workflow** (13 statements, 100-page PDF):
- Extraction: ~2 seconds
- Splitting: ~5-8 seconds
- Upload to Drive: ~10-15 seconds (depends on network)
- Link insertion: ~3 seconds
- **Total**: ~20-30 seconds

**Factors affecting performance**:
- PDF size and complexity
- Number of splits
- Network bandwidth to Google Drive
- Drive API rate limits (1000 requests/100 seconds)

## Customization

### Adjust Detection Patterns
Edit [processing/word_hyperlink_processor_simple.py](processing/word_hyperlink_processor_simple.py:98) → `extract_page_ranges_from_document()` function

### Change Folder Structure
Edit [processing/drive_utils.py](processing/drive_utils.py) → `create_folder_structure()` function

### Modify Word Template
Edit [processing/word_hyperlink_processor_simple.py](processing/word_hyperlink_processor_simple.py:200) → `insert_hyperlinks_batch()` function

### Customize Progress Messages
Edit [pdfs/views_processor_ui.py](pdfs/views_processor_ui.py:631) → `progress_generator()` function

### Adjust Progress Percentages
```python
# In progress_generator() function:
PHASE_SPLITTING = (20, 50)    # 30% of total progress
PHASE_UPLOADING = (60, 80)     # 20% of total progress
PHASE_LINKING = (85, 92)       # 7% of total progress
```

## Development

### Running in Development Mode

```bash
# Enable debug mode in .env
DEBUG=True

# Run with auto-reload
python manage.py runserver 8004

# Run with Celery for background tasks
celery -A pdf_automation worker --loglevel=debug --pool=solo

# View Celery task logs
celery -A pdf_automation events
```

### Testing

```bash
# Run all tests
python manage.py test

# Run specific test
python manage.py test pdfs.tests.test_processor

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

### Database Management

```bash
# Create new migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Reset database (WARNING: deletes all data)
python manage.py flush

# Create superuser
python manage.py createsuperuser
```

### Debugging

**Enable verbose logging** in `settings.py`:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
}
```

**Test Drive API connection**:

```python
from processing.drive_utils import DriveAPIHandler

handler = DriveAPIHandler()
result = handler.test_connection()
print(result)
```

**Test page range extraction**:

```python
from processing.word_hyperlink_processor_simple import WordHyperlinkProcessorSimple

processor = WordHyperlinkProcessorSimple()
ranges = processor.extract_page_ranges_from_file('path/to/document.docx')
print(ranges)
```

## Deployment

### Production Checklist

- [ ] Set `DEBUG=False` in `.env`
- [ ] Use strong `SECRET_KEY`
- [ ] Configure `ALLOWED_HOSTS`
- [ ] Set up HTTPS/SSL
- [ ] Use production database (PostgreSQL recommended)
- [ ] Configure Gunicorn/uWSGI
- [ ] Set up Nginx reverse proxy
- [ ] Enable Celery with supervisor/systemd
- [ ] Configure proper logging
- [ ] Set up monitoring (Sentry, etc.)
- [ ] Implement backup strategy
- [ ] Use Shared Drive (not personal Drive)
- [ ] Restrict service account permissions
- [ ] Enable audit logging
- [ ] Configure rate limiting
- [ ] Set up automated testing

### Example Production Setup (Ubuntu)

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install python3-pip python3-venv nginx redis-server postgresql

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install gunicorn psycopg2-binary

# Collect static files
python manage.py collectstatic

# Set up Gunicorn service
sudo nano /etc/systemd/system/pdfautomation.service

# Set up Nginx
sudo nano /etc/nginx/sites-available/pdfautomation

# Enable and start services
sudo systemctl enable pdfautomation
sudo systemctl start pdfautomation
sudo systemctl enable nginx
sudo systemctl restart nginx
```

## Security Best Practices

### For Medical/PHI Data

1. **Authentication & Authorization**
   - Implement user authentication (Django's built-in auth)
   - Use role-based access control (RBAC)
   - Require MFA for admin access
   - Audit all access logs

2. **Data Encryption**
   - HTTPS/TLS for all connections
   - Encrypt service account credentials at rest
   - Use encrypted database connections
   - Consider encrypting PDFs before upload

3. **Google Drive Security**
   - Use Shared Drive (better access control)
   - Restrict service account to specific folders
   - Never use `anyoneWithLink` sharing
   - Domain-restricted sharing only
   - Regular permission audits

4. **Application Security**
   - Keep dependencies updated: `pip list --outdated`
   - Use Django security middleware
   - Configure CSRF protection
   - Sanitize user inputs
   - Implement rate limiting

5. **Compliance (HIPAA/GDPR)**
   - Implement data retention policies
   - Provide data deletion capabilities
   - Maintain audit trails
   - Regular security assessments
   - Business Associate Agreements (BAA) with Google

6. **Network Security**
   - Run in isolated network segment
   - Use firewall rules
   - Whitelist IP addresses
   - VPN access for remote users
   - Monitor for suspicious activity

## Related Documentation

- **[ONE_CLICK_WORKFLOW_GUIDE.md](ONE_CLICK_WORKFLOW_GUIDE.md)** - Detailed One-Click workflow guide
- **[REAL_TIME_PROGRESS_GUIDE.md](REAL_TIME_PROGRESS_GUIDE.md)** - Real-time progress implementation
- **[AUTO_EXTRACT_DJANGO_UI_GUIDE.md](AUTO_EXTRACT_DJANGO_UI_GUIDE.md)** - Auto-extraction feature guide
- **[API_EXTRACTION_GUIDE.md](API_EXTRACTION_GUIDE.md)** - API integration examples
- **[WORKFLOWS_OVERVIEW.md](WORKFLOWS_OVERVIEW.md)** - Complete workflows overview
- **[WHATS_NEW.md](WHATS_NEW.md)** - Latest features and updates

## FAQ

**Q: Can I use this without Google Drive?**
A: No, the system is designed for Google Drive integration. You could modify it to use other storage (S3, Azure Blob), but significant code changes would be required.

**Q: What's the difference between Shared Drive and personal Drive?**
A: Shared Drives are recommended for production as they use organization storage quota. Service accounts have only 15GB personal storage which fills quickly with medical documents.

**Q: Can I process scanned PDFs?**
A: Yes, but you need to install Tesseract OCR. The system will automatically OCR scanned documents.

**Q: How many documents can I process at once?**
A: The One-Click workflow processes one document at a time. For batch processing, use the Dashboard workflow which supports multiple PDFs.

**Q: What happens if processing fails mid-way?**
A: Files uploaded to Drive remain there. The Word document won't have all hyperlinks. You can reprocess the same files - the system will skip duplicate PDFs on Drive.

**Q: Can I customize the folder structure on Drive?**
A: Yes, edit the `create_folder_structure()` function in [drive_utils.py](processing/drive_utils.py). Default structure is Year/Month/Date/Patient Name.

**Q: Is this HIPAA compliant?**
A: The application provides security features, but HIPAA compliance depends on your deployment, policies, and Google Workspace BAA. Consult with compliance officers.

**Q: Can multiple users use this simultaneously?**
A: Yes, sessions are isolated. Each user's uploads and processing are independent.

## License

This project is for internal use. Ensure compliance with healthcare data regulations (HIPAA, GDPR, etc.).

## Support

For issues or questions:
1. Check this README and related documentation
2. Review troubleshooting section above
3. Check Django logs: `python manage.py runserver --verbosity 3`
4. Check Celery logs: `celery -A pdf_automation worker --loglevel=debug`
5. Contact your system administrator

## Contributors

Built with Django, Google Drive API, and modern web technologies for efficient medical document management.

---

**Last Updated**: January 2026
**Version**: 2.0.0 (One-Click Workflow)
