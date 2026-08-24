@echo off
REM Uvicorn startup script for Windows - Lotus Electronics Chatbot API

echo 🚀 Starting Lotus Electronics Chatbot API with Uvicorn...

REM Set environment variables if needed
REM set GOOGLE_API_KEY=your_google_api_key_here
REM set TAVILY_API_KEY=your_tavily_api_key_here

REM Run with Uvicorn
uvicorn main:app --host 0.0.0.0 --port 8001 --reload --log-level info

echo ✅ Server started at http://localhost:8001
echo 📖 API docs available at http://localhost:8001/docs
pause
