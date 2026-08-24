@echo off
REM Gunicorn startup script for Windows - Lotus Electronics Chatbot API (Production)

echo 🚀 Starting Lotus Electronics Chatbot API with Gunicorn...

REM Set environment variables if needed
REM set GOOGLE_API_KEY=your_google_api_key_here
REM set TAVILY_API_KEY=your_tavily_api_key_here

REM Run with Gunicorn for production
gunicorn main:app ^
  --bind 0.0.0.0:8001 ^
  --workers 4 ^
  --worker-class uvicorn.workers.UvicornWorker ^
  --max-requests 1000 ^
  --max-requests-jitter 100 ^
  --timeout 30 ^
  --keep-alive 2 ^
  --log-level info ^
  --access-logfile - ^
  --error-logfile -

echo ✅ Production server started at http://localhost:8001
pause
