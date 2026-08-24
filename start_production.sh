#!/bin/bash

# High-Scale Production Gunicorn Startup Script
# This script provides better scalability and monitoring

# Create logs directory if it doesn't exist
mkdir -p logs

# Set environment variables for production
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export FLASK_ENV=production
export WORKERS=$(python3 -c "import multiprocessing; print(multiprocessing.cpu_count() * 2 + 1)")

echo "Starting Lotus Chatbot API Server..."
echo "Workers: $WORKERS"
echo "Timestamp: $(date)"

# Kill any existing processes on port 8001
echo "Checking for existing processes on port 8001..."
lsof -ti:8001 | xargs kill -9 2>/dev/null || true

# Start Gunicorn with production configuration
gunicorn app:app \
  --config gunicorn.conf.py \
  --bind 0.0.0.0:8001 \
  --workers $WORKERS \
  --worker-class gevent \
  --worker-connections 1000 \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --timeout 30 \
  --keepalive 5 \
  --preload \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  --log-level info \
  --capture-output \
  --enable-stdio-inheritance \
  --daemon

# Check if server started successfully
sleep 2
if pgrep -f "gunicorn.*app:app" > /dev/null; then
    echo "✓ Server started successfully!"
    echo "✓ PID: $(pgrep -f 'gunicorn.*app:app' | head -1)"
    echo "✓ Access logs: logs/access.log"
    echo "✓ Error logs: logs/error.log"
    echo "✓ Server running on: http://0.0.0.0:8001"
else
    echo "✗ Failed to start server!"
    echo "Check error logs: tail -f logs/error.log"
    exit 1
fi
