#!/usr/bin/env python3
"""
Redis setup script for Windows
This script helps set up Redis for the chat application
"""

import subprocess
import sys
import os
import requests
import zipfile
import shutil

def download_redis_for_windows():
    """Download and extract Redis for Windows"""
    redis_url = "https://github.com/microsoftarchive/redis/releases/download/win-3.2.100/Redis-x64-3.2.100.zip"
    redis_zip = "redis.zip"
    redis_dir = "redis"
    
    try:
        print("Downloading Redis for Windows...")
        response = requests.get(redis_url)
        with open(redis_zip, 'wb') as f:
            f.write(response.content)
        
        print("Extracting Redis...")
        with zipfile.ZipFile(redis_zip, 'r') as zip_ref:
            zip_ref.extractall(redis_dir)
        
        os.remove(redis_zip)
        print(f"✅ Redis extracted to {redis_dir}")
        print(f"To start Redis, run: {redis_dir}\\redis-server.exe")
        
    except Exception as e:
        print(f"❌ Error downloading Redis: {e}")

def install_redis_python():
    """Install Redis Python package"""
    try:
        print("Installing Redis Python package...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "redis"])
        print("✅ Redis Python package installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing Redis package: {e}")

def test_redis_connection():
    """Test Redis connection"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("✅ Redis is running and accessible!")
        return True
    except Exception as e:
        print(f"❌ Cannot connect to Redis: {e}")
        return False

def main():
    print("🔧 Redis Setup for Chat Application")
    print("=" * 40)
    
    # Check if Redis Python package is installed
    try:
        import redis
        print("✅ Redis Python package is already installed")
    except ImportError:
        install_redis_python()
    
    # Test Redis connection
    if not test_redis_connection():
        print("\n📝 Redis Setup Instructions:")
        print("1. Download Redis from: https://github.com/microsoftarchive/redis/releases")
        print("2. Extract and run redis-server.exe")
        print("3. Or use Docker: docker run -d -p 6379:6379 redis:alpine")
        print("4. Or install WSL and use: sudo apt install redis-server")
        
        choice = input("\nWould you like to download Redis automatically? (y/n): ")
        if choice.lower() == 'y':
            download_redis_for_windows()
    
    print("\n🚀 Setup complete! You can now run the chat application.")

if __name__ == "__main__":
    main()
