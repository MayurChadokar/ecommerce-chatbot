#!/usr/bin/env python3
"""
Test JSON handling for Lotus Electronics Chatbot
This script tests different response formats and JSON parsing.
"""

import json
import sys
import os
import re

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_json_cleaning():
    """Test JSON cleaning functionality"""
    print("🧪 Testing JSON Cleaning and Parsing")
    print("="*50)
    
    # Test cases for different response formats
    test_responses = [
        # Case 1: Pure JSON
        '{"answer": "Hello from Lotus!", "end": "How can I help?"}',
        
        # Case 2: JSON wrapped in markdown
        '```json\n{"answer": "Hello from Lotus!", "end": "How can I help?"}\n```',
        
        # Case 3: JSON with extra text
        'Here is the response: {"answer": "Hello from Lotus!", "end": "How can I help?"} Hope this helps!',
        
        # Case 4: Malformed response
        'Hello from Lotus Electronics! How can I help you today?',
        
        # Case 5: JSON with newlines and spaces
        '```json\n  {\n    "answer": "Hello from Lotus!",\n    "end": "How can I help?"\n  }\n```'
    ]
    
    for i, response in enumerate(test_responses, 1):
        print(f"\n🔍 Test Case {i}:")
        print(f"Input: {response[:50]}...")
        
        try:
            # Clean the response
            clean_response = response.strip()
            if clean_response.startswith('```json'):
                clean_response = clean_response.replace('```json', '').replace('```', '').strip()
            
            # Try to parse directly
            try:
                parsed_json = json.loads(clean_response)
                print("✅ Direct JSON parse successful")
                print(f"Answer: {parsed_json.get('answer', 'N/A')}")
            except json.JSONDecodeError:
                # Try regex extraction
                json_match = re.search(r'\{.*\}', clean_response, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json_match.group(0)
                        parsed_json = json.loads(extracted_json)
                        print("✅ Regex extraction successful")
                        print(f"Answer: {parsed_json.get('answer', 'N/A')}")
                    except:
                        print("❌ Regex extraction failed")
                        # Fallback
                        fallback_response = {
                            "answer": clean_response,
                            "end": "Is there anything else I can help you with?"
                        }
                        print("✅ Fallback JSON created")
                        print(f"Answer: {fallback_response['answer'][:50]}...")
                else:
                    print("❌ No JSON pattern found")
                    
        except Exception as e:
            print(f"❌ Error: {e}")

def test_chat_function():
    """Test the actual chat function"""
    print(f"\n🤖 Testing chat_with_agent function")
    print("="*50)
    
    try:
        from chat import chat_with_agent
        
        # Test simple greeting
        response = chat_with_agent("Hello", "test_json_session")
        print(f"Raw response: {response[:100]}...")
        
        # Parse and display
        try:
            parsed = json.loads(response)
            print("✅ JSON parsing successful")
            print(f"Answer: {parsed.get('answer', 'N/A')}")
            print(f"End: {parsed.get('end', 'N/A')}")
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing failed: {e}")
            
    except Exception as e:
        print(f"❌ Function test failed: {e}")

if __name__ == "__main__":
    print("🏪 Lotus Electronics - JSON Handling Test Suite")
    print("="*60)
    
    test_json_cleaning()
    test_chat_function()
    
    print("\n🎉 JSON handling tests completed!")
    print("\nNote: If you see raw JSON in your chat, the improved parsing should now handle it correctly.")
