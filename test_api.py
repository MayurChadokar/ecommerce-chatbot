"""
Simple client to test the Lotus Electronics Chatbot API
"""
import requests
import json
import time

API_BASE_URL = "http://localhost:8001"

def test_api():
    """Test the chatbot API with various queries"""
    
    print("🧪 Testing Lotus Electronics Chatbot API")
    print("=" * 50)
    
    # Test health check
    try:
        response = requests.get(f"{API_BASE_URL}/health")
        print(f"✅ Health check: {response.json()}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return
    
    # Test chat functionality
    session_id = "test_session_123"
    
    test_messages = [
        "Hello! I'm looking for smartphones",
        "Show me phones under 20000",
        "okay",
        "What about Samsung phones?",
        "above 25k"
    ]
    
    print("\n💬 Testing chat conversation:")
    print("-" * 30)
    
    for i, message in enumerate(test_messages, 1):
        try:
            payload = {
                "message": message,
                "session_id": session_id
            }
            
            print(f"\n{i}. User: {message}")
            
            response = requests.post(f"{API_BASE_URL}/chat", json=payload)
            
            if response.status_code == 200:
                data = response.json()
                bot_response = data["response"]
                
                print(f"🤖 Bot: {bot_response.get('answer', '')}")
                
                if 'products' in bot_response and bot_response['products']:
                    print(f"📦 Found {len(bot_response['products'])} products")
                    for j, product in enumerate(bot_response['products'][:2], 1):
                        print(f"   {j}. {product.get('product_name', 'N/A')} - {product.get('product_mrp', 'N/A')}")
                
                if bot_response.get('end'):
                    print(f"❓ Follow-up: {bot_response['end']}")
                    
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
                
            time.sleep(1)  # Small delay between requests
            
        except Exception as e:
            print(f"❌ Request failed: {e}")
    
    # Test session stats
    try:
        print(f"\n📊 Session Statistics:")
        response = requests.get(f"{API_BASE_URL}/sessions/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"   Active sessions: {stats.get('active_sessions', 0)}")
        else:
            print(f"   Could not retrieve stats: {response.status_code}")
    except Exception as e:
        print(f"   Stats request failed: {e}")
    
    # Test session clearing
    try:
        print(f"\n🧹 Clearing test session:")
        response = requests.get(f"{API_BASE_URL}/sessions/{session_id}/clear")
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ {result.get('message', 'Session cleared')}")
        else:
            print(f"   ❌ Clear failed: {response.status_code}")
    except Exception as e:
        print(f"   Clear request failed: {e}")

def interactive_test():
    """Interactive testing mode"""
    print("\n🔄 Interactive Mode - Type 'quit' to exit")
    print("-" * 40)
    
    session_id = f"interactive_{int(time.time())}"
    
    while True:
        try:
            message = input("\n💬 You: ").strip()
            if message.lower() in ['quit', 'exit', 'q']:
                break
            
            if not message:
                continue
                
            payload = {
                "message": message,
                "session_id": session_id
            }
            
            response = requests.post(f"{API_BASE_URL}/chat", json=payload)
            
            if response.status_code == 200:
                data = response.json()
                bot_response = data["response"]
                
                print(f"🤖 Bot: {bot_response.get('answer', '')}")
                
                if 'products' in bot_response and bot_response['products']:
                    print(f"\n📦 Products Found ({len(bot_response['products'])}):")
                    for i, product in enumerate(bot_response['products'], 1):
                        print(f"   {i}. {product.get('product_name', 'N/A')}")
                        print(f"      💰 {product.get('product_mrp', 'N/A')}")
                        if product.get('features'):
                            features = ', '.join(product['features'][:2])
                            print(f"      ✨ {features}")
                
                if bot_response.get('end'):
                    print(f"\n❓ {bot_response['end']}")
                    
            else:
                print(f"❌ Error: {response.status_code} - {response.text}")
                
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("Choose testing mode:")
    print("1. Automated test")
    print("2. Interactive test")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    if choice == "1":
        test_api()
    elif choice == "2":
        interactive_test()
    else:
        print("Invalid choice. Running automated test...")
        test_api()
