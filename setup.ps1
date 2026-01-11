$ErrorActionPreference = "Stop"

Write-Host "🛠️  Setting up PDF Automation System..." -ForegroundColor Cyan

# Check Python
try {
    python --version
} catch {
    Write-Host "❌ Python is not installed or not in PATH." -ForegroundColor Red
    exit 1
}

# Create/Activate Venv
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
}

Write-Host "Activating virtual environment..." -ForegroundColor Yellow
. .\venv\Scripts\activate

# Install Requirements
Write-Host "Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt

# Create .env if not exists
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env file from example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "⚠️  Please edit .env and add your Google Drive credentials!" -ForegroundColor Magenta
}

# Run Migrations
Write-Host "Running database migrations..." -ForegroundColor Yellow
python manage.py makemigrations
python manage.py migrate

# Create Credentials Directory
if (-not (Test-Path "credentials")) {
    New-Item -ItemType Directory -Force -Path "credentials" | Out-Null
}

Write-Host "`n✅ Setup Complete!" -ForegroundColor Green
Write-Host "1. Place your 'service-account-key.json' in the 'credentials' folder."
Write-Host "2. Update '.env' with your Google Drive Folder ID."
Write-Host "3. Run '.\start_app.ps1' to start the system."
