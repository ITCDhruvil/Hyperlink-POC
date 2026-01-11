$ErrorActionPreference = "Stop"

Write-Host "🚀 Starting PDF Automation System..." -ForegroundColor Cyan

# Check if venv exists
if (-not (Test-Path "venv")) {
    Write-Host "❌ Virtual environment not found! Please run setup.ps1 first." -ForegroundColor Red
    exit 1
}

# Check if Redis is running (basic check)
try {
    $redis = Get-Process redis-server -ErrorAction SilentlyContinue
    if (-not $redis) {
        Write-Host "⚠️  Redis server process not found. Please ensure Redis is running for background tasks." -ForegroundColor Yellow
        Write-Host "   You can run it via Docker: docker run -d -p 6379:6379 redis" -ForegroundColor Gray
    } else {
        Write-Host "✅ Redis is running." -ForegroundColor Green
    }
} catch {
    Write-Host "⚠️  Could not check Redis status." -ForegroundColor Yellow
}

# Start Celery Worker in a new window
Write-Host "Starting Celery Worker..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& { . .\venv\Scripts\activate; celery -A pdf_automation worker --loglevel=info --pool=solo }"

# Start Django Server in current window
Write-Host "Starting Django Server..." -ForegroundColor Green
. .\venv\Scripts\activate
python manage.py runserver
