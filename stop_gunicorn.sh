#!/bin/bash
# Stop Gunicorn server script

echo "🛑 Stopping Lotus Electronics Chatbot API..."

# Find and kill Gunicorn processes
PIDS=$(pgrep -f "gunicorn.*app:app")

if [ -z "$PIDS" ]; then
    echo "ℹ️  No Gunicorn processes found running"
else
    echo "🔍 Found Gunicorn processes: $PIDS"
    
    # Try graceful shutdown first
    echo "🔄 Attempting graceful shutdown..."
    kill -TERM $PIDS
    
    # Wait a few seconds
    sleep 3
    
    # Check if processes are still running
    REMAINING=$(pgrep -f "gunicorn.*app:app")
    if [ ! -z "$REMAINING" ]; then
        echo "⚠️  Processes still running, forcing shutdown..."
        kill -KILL $REMAINING
        sleep 1
    fi
    
    # Final check
    FINAL_CHECK=$(pgrep -f "gunicorn.*app:app")
    if [ -z "$FINAL_CHECK" ]; then
        echo "✅ All Gunicorn processes stopped successfully"
    else
        echo "❌ Some processes may still be running: $FINAL_CHECK"
    fi
fi

# Also kill any processes using port 8001
PORT_PIDS=$(lsof -ti:8001 2>/dev/null)
if [ ! -z "$PORT_PIDS" ]; then
    echo "🔍 Found processes using port 8001: $PORT_PIDS"
    kill -9 $PORT_PIDS 2>/dev/null
    echo "✅ Freed port 8001"
fi

echo "🏁 Server shutdown complete"
