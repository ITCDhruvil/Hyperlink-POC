@echo off
setlocal

REM Start all services for Hyperlink-POC (Windows)
REM Adjust these values if you run on a different machine/path.

pushd "%~dp0.."
set "PROJECT_DIR=%CD%"
popd

REM Optional: unify MEDIA_ROOT across Django/Celery (recommended)
if not defined DJANGO_MEDIA_ROOT (
  set "DJANGO_MEDIA_ROOT=%PROJECT_DIR%\media"
)

echo PROJECT_DIR=%PROJECT_DIR%
echo DJANGO_MEDIA_ROOT=%DJANGO_MEDIA_ROOT%

REM Start Redis (if redis-server is on PATH). If you run Redis as a Windows service, you can remove this.
start "Redis" cmd /k "redis-server"

REM Start Django
start "Django" cmd /k "cd /d \"%PROJECT_DIR%\" ^&^& call venv\Scripts\activate.bat ^&^& set \"DJANGO_MEDIA_ROOT=%DJANGO_MEDIA_ROOT%\" ^&^& python manage.py runserver 0.0.0.0:8000"

REM Start Celery workers
start "Celery Split" cmd /k "cd /d \"%PROJECT_DIR%\" ^&^& call venv\Scripts\activate.bat ^&^& set \"DJANGO_MEDIA_ROOT=%DJANGO_MEDIA_ROOT%\" ^&^& celery -A pdf_automation worker -P solo -l info -Q split --hostname=split@%%h"

REM Upload workers (parallel)
start "Celery Upload 1" cmd /k "cd /d \"%PROJECT_DIR%\" ^&^& call venv\Scripts\activate.bat ^&^& set \"DJANGO_MEDIA_ROOT=%DJANGO_MEDIA_ROOT%\" ^&^& celery -A pdf_automation worker -P solo -l info -Q upload --hostname=upload1@%%h"
start "Celery Upload 2" cmd /k "cd /d \"%PROJECT_DIR%\" ^&^& call venv\Scripts\activate.bat ^&^& set \"DJANGO_MEDIA_ROOT=%DJANGO_MEDIA_ROOT%\" ^&^& celery -A pdf_automation worker -P solo -l info -Q upload --hostname=upload2@%%h"
start "Celery Upload 3" cmd /k "cd /d \"%PROJECT_DIR%\" ^&^& call venv\Scripts\activate.bat ^&^& set \"DJANGO_MEDIA_ROOT=%DJANGO_MEDIA_ROOT%\" ^&^& celery -A pdf_automation worker -P solo -l info -Q upload --hostname=upload3@%%h"

REM Optional default queue worker (uncomment if you have tasks routed to default)
REM start "Celery Default" cmd /k "cd /d %PROJECT_DIR% ^&^& venv\Scripts\activate ^&^& set DJANGO_MEDIA_ROOT=%DJANGO_MEDIA_ROOT% ^&^& celery -A pdf_automation worker -P solo -l info -Q default --hostname=default@%%h"

echo.
echo Started: Redis, Django, Celery(split), Celery(upload x3)
echo.
endlocal
