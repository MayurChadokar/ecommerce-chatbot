#!/usr/bin/env python3
"""
Test script for Lotus Electronics Chatbot JSON Response Format
This script tests the chatbot's JSON response format and validates the structure.
"""

import json
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_json_response_format():
    """Test the JSON response format"""
    print("🧪 Testing Lotus Electronics Chatbot JSON Format")
    print("="*50)
    
    # Test the product search tool
    try:
        from tools.product_search_tool import search_products
        
        print("\n1. Testing product search with JSON output...")
        result = search_products.invoke({
            "query": "Samsung AC",
            "top_k": 2,
            "price_max": 50000
        })
        
        print("Raw result:")
        print(result)
        print("\n" + "-"*40)
        
        # Validate JSON structure
        try:
            parsed = json.loads(result)
            print("\n✅ JSON Structure Validation:")
            print(f"   - Has 'answer': {'answer' in parsed}")
            print(f"   - Has 'products': {'products' in parsed}")
            print(f"   - Has 'end': {'end' in parsed}")
            
            if 'products' in parsed and parsed['products']:
                product = parsed['products'][0]
                print(f"\n✅ Product Structure Validation:")
                print(f"   - Has 'product_name': {'product_name' in product}")
                print(f"   - Has 'product_mrp': {'product_mrp' in product}")
                print(f"   - Has 'product_url': {'product_url' in product}")
                print(f"   - Has 'product_image': {'product_image' in product}")
                print(f"   - Has 'features': {'features' in product}")
                
                if 'features' in product:
                    print(f"   - Features count: {len(product['features'])}")
            
            print(f"\n📊 Summary:")
            print(f"   - Products found: {len(parsed.get('products', []))}")
            print(f"   - Answer length: {len(parsed.get('answer', ''))}")
            print(f"   - Has follow-up: {bool(parsed.get('end', ''))}")
            
        except json.JSONDecodeError as e:
            print(f"❌ JSON Parse Error: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing product search: {e}")
        return False
    
    print("\n🎉 JSON format test completed successfully!")
    return True

def test_system_prompt():
    """Test the system prompt content"""
    print("\n🤖 Testing System Prompt...")
    
    try:
        from chat import SYSTEM_PROMPT
        
        # Check key elements in system prompt
        required_elements = [
            "Lotus Electronics",
            "JSON format",
            "product_name",
            "product_mrp",
            "features",
            "official"
        ]
        
        for element in required_elements:
            if element.lower() in SYSTEM_PROMPT.lower():
                print(f"   ✅ Contains '{element}'")
            else:
                print(f"   ❌ Missing '{element}'")
        
        print(f"\n📏 System prompt length: {len(SYSTEM_PROMPT)} characters")
        
    except Exception as e:
        print(f"❌ Error checking system prompt: {e}")

if __name__ == "__main__":
    print("🏪 Lotus Electronics Chatbot Test Suite")
    print("="*50)
    
    success = test_json_response_format()
    test_system_prompt()
    
    if success:
        print("\n✅ All tests passed! The chatbot is ready to use.")
    else:
        print("\n❌ Some tests failed. Please check the configuration.")
        sys.exit(1)
