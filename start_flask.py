#!/usr/bin/env python3
"""
Startup script for Lotus Electronics Flask Chatbot
This script ensures all services are ready and starts the Flask app.
"""

import subprocess
import sys
import os
import time

def check_redis():
    """Check if Redis is running"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("✅ Redis is running")
        return True
    except Exception as e:
        print(f"❌ Redis not running: {e}")
        return False

def check_dependencies():
    """Check if all dependencies are installed"""
    required_modules = ['flask', 'redis', 'langchain', 'sentence_transformers', 'pinecone']
    missing = []
    
    for module in required_modules:
        try:
            __import__(module.replace('-', '_'))
            print(f"✅ {module} installed")
        except ImportError:
            missing.append(module)
            print(f"❌ {module} missing")
    
    return len(missing) == 0, missing

def test_chat_function():
    """Test the chat function"""
    try:
        from chat import chat_with_agent
        response = chat_with_agent("Hello", "test_session")
        print("✅ Chat function working")
        return True
    except Exception as e:
        print(f"❌ Chat function error: {e}")
        return False

def main():
    print("🏪 Lotus Electronics Flask Chatbot Startup")
    print("="*50)
    
    # Check dependencies
    print("\n📦 Checking dependencies...")
    deps_ok, missing = check_dependencies()
    if not deps_ok:
        print(f"\n❌ Missing dependencies: {', '.join(missing)}")
        print("Run: pip install -r requirements.txt")
        return False
    
    # Check Redis
    print("\n🔌 Checking Redis connection...")
    if not check_redis():
        print("\n❌ Please start Redis server:")
        print("   Docker: docker run -d -p 6379:6379 redis:alpine")
        print("   Local: redis-server")
        return False
    
    # Test chat function
    print("\n🧪 Testing chat function...")
    if not test_chat_function():
        print("\n❌ Chat function not working properly")
        return False
    
    # Everything is ready
    print("\n🎉 All systems ready!")
    print("\n🚀 Starting Flask app...")
    print("   URL: http://localhost:9000")
    print("   Health check: http://localhost:9000/health")
    print("\n📱 Available endpoints:")
    print("   GET  / - Chat interface")
    print("   POST /chat - Chat API")
    print("   GET  /health - Health check")
    
    print("\n" + "="*50)
    print("Press Ctrl+C to stop the server")
    print("="*50)
    
    # Start Flask app
    try:
        os.system("python app.py")
    except KeyboardInterrupt:
        print("\n👋 Flask app stopped")

if __name__ == "__main__":
    main()
