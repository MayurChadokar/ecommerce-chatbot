@echo off
REM High-Scale Production Gunicorn Startup Script for Windows
REM This script provides better scalability and monitoring

REM Create logs directory if it doesn't exist
if not exist "logs" mkdir logs

REM Set environment variables for production
set FLASK_ENV=production

echo Starting Lotus Chatbot API Server...
echo Timestamp: %date% %time%

REM Kill any existing processes on port 8001
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8001') do (
    taskkill /f /pid %%a 2>nul
)

REM Calculate optimal worker count (CPU cores * 2 + 1)
for /f %%i in ('wmic cpu get NumberOfCores /value ^| findstr "="') do set %%i
set /a WORKERS=%NumberOfCores% * 2 + 1
echo Workers: %WORKERS%

REM Start Gunicorn with production configuration
gunicorn app:app ^
  --config gunicorn.conf.py ^
  --bind 0.0.0.0:8001 ^
  --workers %WORKERS% ^
  --worker-class gevent ^
  --worker-connections 1000 ^
  --max-requests 1000 ^
  --max-requests-jitter 50 ^
  --timeout 30 ^
  --keepalive 5 ^
  --preload ^
  --access-logfile logs/access.log ^
  --error-logfile logs/error.log ^
  --log-level info ^
  --capture-output

if %ERRORLEVEL% EQU 0 (
    echo ✓ Server started successfully!
    echo ✓ Access logs: logs/access.log
    echo ✓ Error logs: logs/error.log
    echo ✓ Server running on: http://0.0.0.0:8001
) else (
    echo ✗ Failed to start server!
    echo Check error logs: type logs\error.log
)
