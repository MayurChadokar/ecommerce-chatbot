#!/bin/bash
# Uvicorn startup script for Lotus Electronics Chatbot API

echo "🚀 Starting Lotus Electronics Chatbot API with Uvicorn..."

# Set environment variables if needed
# export GOOGLE_API_KEY="your_google_api_key_here"
# export TAVILY_API_KEY="your_tavily_api_key_here"

# Run with Uvicorn
uvicorn main:app --host 0.0.0.0 --port 8001 --reload --log-level info

echo "✅ Server started at http://localhost:8001"
echo "📖 API docs available at http://localhost:8001/docs"
