#!/usr/bin/env python3
"""
Test script for Flask integration with Lotus Electronics Chatbot
This script tests the chat_with_agent function for Flask app integration.
"""

import json
import sys
import os

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_chat_with_agent():
    """Test the chat_with_agent function"""
    print("🧪 Testing Flask Integration for Lotus Electronics Chatbot")
    print("="*60)
    
    try:
        from chat import chat_with_agent
        
        # Test cases
        test_cases = [
            {
                "message": "Hello, I'm looking for Samsung ACs",
                "session_id": "test_session_1",
                "description": "Product search query"
            },
            {
                "message": "What's your name?",
                "session_id": "test_session_2", 
                "description": "General conversation"
            },
            {
                "message": "Show me gaming laptops under 80010",
                "session_id": "test_session_3",
                "description": "Price-filtered search"
            }
        ]
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n🔍 Test {i}: {test_case['description']}")
            print(f"📝 Message: '{test_case['message']}'")
            print(f"🆔 Session: {test_case['session_id']}")
            print("-" * 40)
            
            try:
                # Call the function
                response = chat_with_agent(test_case['message'], test_case['session_id'])
                
                # Validate JSON response
                parsed_response = json.loads(response)
                
                print("✅ JSON Response Valid!")
                print(f"📄 Answer: {parsed_response.get('answer', 'N/A')[:100]}...")
                
                if 'products' in parsed_response:
                    products_count = len(parsed_response.get('products', []))
                    print(f"🛍️ Products: {products_count} items")
                
                if 'end' in parsed_response and parsed_response['end']:
                    print(f"❓ Follow-up: {parsed_response['end'][:50]}...")
                
                print("✅ Test passed!")
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON Parse Error: {e}")
                print(f"Raw response: {response[:200]}...")
                
            except Exception as e:
                print(f"❌ Function Error: {e}")
        
        print(f"\n🎉 Flask integration testing completed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("Make sure chat.py is in the same directory and Redis is running.")
        return False
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return False

def test_flask_endpoint_simulation():
    """Simulate Flask endpoint behavior"""
    print(f"\n🌐 Simulating Flask Endpoint Behavior")
    print("="*50)
    
    try:
        from chat import chat_with_agent
        
        # Simulate Flask request payload
        payload = {
            "message": "I need wireless headphones under 5000",
            "session_id": "web_user_12345"
        }
        
        print(f"📥 Incoming Request:")
        print(f"   Message: {payload['message']}")
        print(f"   Session ID: {payload['session_id']}")
        
        # Process the request
        ai_reply = chat_with_agent(payload["message"], payload["session_id"])
        data = json.loads(ai_reply)
        
        # Format Flask response
        response = {
            "status": "success",
            "data": data
        }
        
        print(f"\n📤 Flask Response:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        
        print("✅ Flask endpoint simulation successful!")
        return True
        
    except Exception as e:
        print(f"❌ Flask simulation error: {e}")
        return False

if __name__ == "__main__":
    print("🏪 Lotus Electronics - Flask Integration Test Suite")
    print("="*60)
    
    success1 = test_chat_with_agent()
    success2 = test_flask_endpoint_simulation()
    
    if success1 and success2:
        print("\n✅ All tests passed! Flask integration is ready.")
        print("\n🚀 You can now run your Flask app with:")
        print("   python app.py")
    else:
        print("\n❌ Some tests failed. Please check the configuration.")
        sys.exit(1)
