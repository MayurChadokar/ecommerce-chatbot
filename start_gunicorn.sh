#!/bin/bash
# Gunicorn startup script for Lotus Electronics Chatbot API (Production)

echo "🚀 Starting Lotus Electronics Chatbot API with Gunicorn..."

# Create logs directory if it doesn't exist
mkdir -p logs

# Disable Hugging Face tokenizer parallelism warning
export TOKENIZERS_PARALLELISM=false

# Set environment variables for production
export FLASK_ENV=production
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Calculate optimal worker count (CPU cores * 2 + 1)
WORKERS=$(python -c "import multiprocessing; print(multiprocessing.cpu_count() * 2 + 1)")
echo "📊 Using $WORKERS workers for optimal performance"

# Kill any existing processes on port 8001
echo "🔍 Checking for existing processes on port 8001..."
lsof -ti:8001 | xargs kill -9 2>/dev/null || true

# Run with Gunicorn for production (WSGI for Flask)
gunicorn app:app \
  --bind 0.0.0.0:8001 \
  --workers $WORKERS \
  --worker-class sync \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --timeout 30 \
  --keep-alive 5 \
  --preload \
  --log-level info \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  --daemon

# Check if server started successfully
sleep 2
if pgrep -f "gunicorn.*app:app" > /dev/null; then
    echo "✅ Production server started successfully!"
    echo "📍 Server running at: http://0.0.0.0:8001"
    echo "📊 Workers: $WORKERS"
    echo "📝 Access logs: logs/access.log"
    echo "📝 Error logs: logs/error.log"
    echo "🔍 Process ID: $(pgrep -f 'gunicorn.*app:app' | head -1)"
else
    echo "❌ Failed to start server!"
    echo "📝 Check error logs: tail -f logs/error.log"
    exit 1
fi
