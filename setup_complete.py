#!/usr/bin/env python3
"""
Complete setup script for the Chat Application with Redis Memory and Product Search
This script sets up all dependencies and services needed to run the application.
"""

import subprocess
import sys
import os
import importlib

def install_requirements():
    """Install all required packages from requirements.txt"""
    try:
        print("📦 Installing Python dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ All Python packages installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing packages: {e}")
        return False

def check_dependencies():
    """Check if all required dependencies are available"""
    required_packages = [
        "redis", "langchain", "sentence_transformers", 
        "pinecone", "geopy", "requests", "pydantic"
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            importlib.import_module(package.replace("-", "_"))
            print(f"✅ {package} - OK")
        except ImportError:
            print(f"❌ {package} - Missing")
            missing_packages.append(package)
    
    return len(missing_packages) == 0

def test_redis_connection():
    """Test Redis connection"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("✅ Redis connection - OK")
        return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False

def test_pinecone_connection():
    """Test Pinecone connection"""
    try:
        from pinecone import Pinecone
        from tools.product_search_tool import ProductSearchTool
        
        # Try to initialize the product search tool
        tool = ProductSearchTool()
        print("✅ Pinecone connection - OK")
        return True
    except Exception as e:
        print(f"❌ Pinecone connection failed: {e}")
        print("   Note: Make sure your Pinecone API key is correct")
        return False

def create_directories():
    """Create necessary directories"""
    directories = ["tools", "logs", "data"]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"📁 Created directory: {directory}")
        else:
            print(f"✅ Directory exists: {directory}")

def run_tests():
    """Run basic functionality tests"""
    print("\n🧪 Running functionality tests...")
    
    # Test 1: Redis Memory
    try:
        from chat import redis_memory
        test_user = "test_user_123"
        redis_memory.save_user_messages(test_user, ["test message"])
        messages = redis_memory.get_user_messages(test_user)
        redis_memory.clear_user_messages(test_user)
        print("✅ Redis memory functionality - OK")
    except Exception as e:
        print(f"❌ Redis memory test failed: {e}")
    
    # Test 2: Product Search
    try:
        from tools.product_search_tool import search_products
        result = search_products.invoke({
            "query": "test product",
            "top_k": 1
        })
        print("✅ Product search functionality - OK")
    except Exception as e:
        print(f"❌ Product search test failed: {e}")

def main():
    """Main setup function"""
    print("🚀 Chat Application Setup")
    print("=" * 50)
    
    # Create directories
    print("\n📁 Creating directories...")
    create_directories()
    
    # Install dependencies
    print("\n📦 Checking and installing dependencies...")
    if not check_dependencies():
        if not install_requirements():
            print("❌ Setup failed: Could not install dependencies")
            return False
    
    # Test connections
    print("\n🔌 Testing connections...")
    redis_ok = test_redis_connection()
    pinecone_ok = test_pinecone_connection()
    
    if not redis_ok:
        print("\n⚠️  Redis is not running. Please start Redis server:")
        print("   - Docker: docker run -d -p 6379:6379 redis:alpine")
        print("   - Local: Download from https://redis.io/download")
        print("   - WSL: sudo apt install redis-server && redis-server")
    
    if not pinecone_ok:
        print("\n⚠️  Pinecone connection failed. Please check:")
        print("   - API key is correct")
        print("   - Index name and host are valid")
        print("   - Internet connection is working")
    
    # Run tests
    if redis_ok and pinecone_ok:
        run_tests()
        print("\n🎉 Setup completed successfully!")
        print("\nYou can now run the chat application:")
        print("   python chat.py")
    else:
        print("\n⚠️  Setup completed with warnings.")
        print("Please fix the connection issues before running the application.")
    
    return True

if __name__ == "__main__":
    main()
