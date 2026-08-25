import os
import uuid
import re
from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.memory import InMemorySaver
from collections import deque
from datetime import datetime, timedelta
import json
import redis
import pickle
from langchain.chat_models import init_chat_model

from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages



tavily_api_key = os.getenv("TAVILY_API_KEY","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")
google_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

from typing import Annotated,Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages # helper function to add messages to the state


class AgentState(TypedDict):
    """The state of the agent."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    number_of_steps: int
    user_id: str

class RedisMemory:
    """Redis-based memory for storing user conversations with TTL."""
    
    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=0, ttl_seconds=3600):
        """
        Initialize Redis memory.
        
        Args:
            redis_host: Redis server host
            redis_port: Redis server port
            redis_db: Redis database number
            ttl_seconds: Time to live for stored conversations (default: 1 hour)
        """
        self.redis_client = redis.Redis(
            host=redis_host, 
            port=redis_port, 
            db=redis_db, 
            decode_responses=False
        )
        self.ttl_seconds = ttl_seconds
        
    def get_user_messages(self, user_id: str) -> list:
        """Retrieve user's message history from Redis."""
        try:
            # Test connection before attempting operation
            self.redis_client.ping()
            key = f"user_messages:{user_id}"
            data = self.redis_client.get(key)
            if data:
                return pickle.loads(data)
            return []
        except redis.ConnectionError as e:
            print(f"❌ Redis connection error for user {user_id}: {e}")
            return []
        except Exception as e:
            print(f"❌ Error retrieving messages for user {user_id}: {type(e).__name__}: {e}")
            return []
    
    def save_user_messages(self, user_id: str, messages: list):
        """Save user's message history to Redis with TTL."""
        try:
            # Test connection before attempting operation
            self.redis_client.ping()
            key = f"user_messages:{user_id}"
            serialized_data = pickle.dumps(messages)
            self.redis_client.setex(key, self.ttl_seconds, serialized_data)
        except redis.ConnectionError as e:
            print(f"❌ Redis connection error when saving for user {user_id}: {e}")
        except Exception as e:
            print(f"❌ Error saving messages for user {user_id}: {type(e).__name__}: {e}")
    
    def add_message_to_user(self, user_id: str, message):
        """Add a single message to user's conversation history."""
        try:
            messages = self.get_user_messages(user_id)
            
            # Only store HumanMessage and AIMessage for context
            # Skip ToolMessage to avoid conversation flow issues
            if hasattr(message, 'type') and message.type in ['human', 'ai']:
                messages.append(message)
                # Keep only last 30 messages to prevent memory overflow
                if len(messages) > 30:
                    messages = messages[-30:]
                self.save_user_messages(user_id, messages)
        except Exception as e:
            print(f"❌ Error adding message for user {user_id}: {type(e).__name__}: {e}")
    
    def clear_user_messages(self, user_id: str):
        """Clear all messages for a specific user."""
        try:
            key = f"user_messages:{user_id}"
            self.redis_client.delete(key)
        except Exception as e:
            print(f"Error clearing messages for user {user_id}: {e}")
    
    def get_active_users(self) -> list:
        """Get list of all active users with stored conversations."""
        try:
            self.redis_client.ping()  # Test connection first
            keys = self.redis_client.keys("user_messages:*")
            return [key.decode('utf-8').split(':')[1] for key in keys]
        except redis.ConnectionError as e:
            print(f"❌ Redis connection error getting active users: {e}")
            return []
        except Exception as e:
            print(f"❌ Error getting active users: {type(e).__name__}: {e}")
            return []
    
    def test_connection(self) -> bool:
        """Test Redis connection health."""
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            print(f"❌ Redis connection test failed: {type(e).__name__}: {e}")
            return False

# Initialize Redis memory with improved error handling
def initialize_redis():
    """Initialize Redis with proper error handling."""
    try:
        redis_memory = RedisMemory(ttl_seconds=1800)  # 30 minutes TTL
        
        # Test Redis connection
        if redis_memory.test_connection():
            print("✅ Redis connected successfully!")
            return redis_memory
        else:
            print("❌ Redis connection test failed")
            return None
            
    except redis.ConnectionError as e:
        print(f"❌ Redis connection failed: {e}")
        print("💡 Please make sure Redis server is running on localhost:6379")
        print("🚀 Start Redis using: redis-server")
        return None
    except Exception as e:
        print(f"❌ Redis initialization failed: {type(e).__name__}: {e}")
        print("💡 Please check your Redis installation and configuration")
        return None

# Try to initialize Redis, but don't exit if it fails
redis_memory = initialize_redis()
if not redis_memory:
    print("⚠️  Running without Redis memory - conversations won't be persistent")
    # Create a fallback memory class that doesn't use Redis
    class FallbackMemory:
        def get_user_messages(self, user_id: str) -> list: return []
        def add_message_to_user(self, user_id: str, message): pass
        def save_user_messages(self, user_id: str, messages: list): pass
        def clear_user_messages(self, user_id: str): pass
        def get_active_users(self) -> list: return []
        def test_connection(self) -> bool: return False
    redis_memory = FallbackMemory()

from langchain_core.tools import tool
from geopy.geocoders import Nominatim
from pydantic import BaseModel, Field
import requests

geolocator = Nominatim(user_agent="weather-app")

class SearchInput(BaseModel):
    location:str = Field(description="The city and state, e.g., San Francisco")
    date:str = Field(description="the forecasting date for when to get the weather format (yyyy-mm-dd)")

# @tool("get_weather_forecast", args_schema=SearchInput, return_direct=True)
# def get_weather_forecast(location: str, date: str):
#     """Retrieves the weather using Open-Meteo API for a given location (city) and a date (yyyy-mm-dd). Returns a list dictionary with the time and temperature for each hour."""
#     location = geolocator.geocode(location)
#     if location:
#         try:
#             response = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={location.latitude}&longitude={location.longitude}&hourly=temperature_2m&start_date={date}&end_date={date}")
#             data = response.json()
#             return {time: temp for time, temp in zip(data["hourly"]["time"], data["hourly"]["temperature_2m"])}
#         except Exception as e:
#             return {"error": str(e)}
#     else:
#         return {"error": "Location not found"}
    


# Import the new product search tool
from tools.product_search_tool import search_products
# Import the store location tool
from tools.get_nearby_store import get_near_store
# Import the product details tool
from tools.Product_details import get_filtered_product_details_tool
# Import the terms & conditions search tool
from tools.search_terms_conditions import search_terms_conditions
# Compare, recommend and order tools (backed by the local catalog + SQLite store)
from tools.compare_products import compare_products_tool
from tools.recommend_products import recommend_products_tool
from tools.browse_catalog import browse_catalog_tool
from tools.order_tools import place_order_tool, track_order_tool, set_current_session
from tools.ticket_tools import raise_ticket_tool

# SQLite persistence for chat logs, sessions and orders
import store
store.init_db()
store.seed_orders()

# from langchain_tavily import TavilySearch

# tavily_tool = TavilySearch(max_results=2,tavily_api_key=tavily_api_key)

tools = [
    search_products,
    get_near_store,
    get_filtered_product_details_tool,
    search_terms_conditions,
    compare_products_tool,
    recommend_products_tool,
    browse_catalog_tool,
    place_order_tool,
    track_order_tool,
    raise_ticket_tool,
]

from datetime import datetime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage

# System prompt for Lotus Electronics chatbot
SYSTEM_PROMPT = """You are Lotus Electronics Sales Assistant - helping customers find electronics products and store locations in India.

CRITICAL RESPONSE FORMAT REQUIREMENT:
You MUST respond with EXACTLY this JSON structure - NO nested JSON strings, NO escaped quotes, NO additional wrapping:

{
  "answer": "your conversational response only - NO product details or store details here",
  "products": [array of product objects if search_products was used],
  "product_details": {product object if get_filtered_product_details_tool was used},
  "stores": [array of store objects if get_near_store was used],
  "policy_info": {policy object if search_terms_conditions was used},
  "comparison": [comparison object if compare_products was used],
  "recommendations": [array of product objects if recommend_products was used],
  "order": {order object if place_order or track_order was used},
  "ticket": {ticket object if raise_ticket was used},
  "end": "follow-up question to continue conversation"
}

TOOL USAGE RULES:
1. Use search_products ONLY when user asks for NEW products they haven't seen yet
2. Use get_near_store ONLY when user asks about store locations by city or zipcode
3. Use get_filtered_product_details_tool ONLY when the user wants MORE DETAILS about
   ONE specific product from previous results (extract product_id from context). NEVER
   use it to gather specs for a comparison — use compare_products for that instead.
4. Use search_terms_conditions when user asks about:
   - Return policy ("return", "return it", "want to return")
   - Refund policy ("refund", "money back", "refund conditions")
   - Warranty terms ("warranty", "guarantee", "warranty terms")
   - Privacy policy ("privacy", "data protection", "personal information")
   - Terms and conditions ("terms", "conditions", "policy")
   - Cancellation policy ("cancel", "cancellation")
   - Shipping/delivery terms ("shipping policy", "delivery terms")
5. Use compare_products when the user wants to COMPARE two products ("compare", "vs",
   "difference between", "which is better", "compare last two"). Extract BOTH
   product_ids from the previous search results and pass them together as a list in
   ONE single call, e.g. compare_products(product_ids=[40097, 39721]). This tool
   fetches all the details itself — DO NOT call get_filtered_product_details to
   gather specs for a comparison, and NEVER call tools repeatedly for each product.
   Put the tool result in the "comparison" field (as a one-item array) and write a
   short conversational summary in "answer".
6. Use recommend_products when the user asks for SUGGESTIONS or ALTERNATIVES
   ("recommend", "suggest", "what else", "alternatives", "something similar",
   "best phone under 20000"). Pass a category and/or budget, or based_on_product_id.
   Put the returned list in the "recommendations" field.
7. Use place_order when the user wants to BUY/ORDER a specific product ("order this",
   "buy", "place an order", "I want to purchase"). Extract the product_id. Put the
   returned order object in the "order" field and confirm warmly in "answer".
8. Use track_order when the user wants the STATUS of an order ("track my order",
   "where is my order", "order status") and gives an order id like LOTUS1001. Put
   the returned order object in the "order" field.
9. Use browse_catalog to show products from our in-store catalog when the user wants
   to browse a category (e.g. "show me phones", "what TVs do you have") or as a
   FALLBACK whenever search_products returns no results. Pass a category and/or
   budget, and put the returned items in the "products" field.
10. SUPPORT TICKETS — when a customer reports a PROBLEM, complaint or issue (e.g.
    "my product is defective", "order not delivered", "I have a complaint",
    "something is broken", "I need help with an issue"):
    a) FIRST try to genuinely help — answer their question or suggest a solution.
    b) THEN offer: "If you'd like, I can raise a support ticket so our team follows
       up with you. Would you like me to do that?"
    c) If they agree, collect these ONE or two at a time (don't overwhelm): their
       NAME, PHONE NUMBER, and a short description of the ISSUE. Ask only for the
       details you don't already have from the conversation.
    d) Once you have all three, call raise_ticket(name, phone, issue). Put the
       returned ticket object in the "ticket" field and confirm the ticket id warmly.
    Only call raise_ticket when you actually have name, phone AND issue.
11. DON'T use tools when discussing general product info that doesn't need specific details

IMPORTANT POLICY RESPONSE RULE:
When using search_terms_conditions, DO NOT put raw policy sections in policy_info field. Instead:
- Summarize the policy information in a clear, conversational way in the "answer" field
- Set policy_info to empty object {}
- Make the answer comprehensive and user-friendly based on the tool results

MANDATORY: If user mentions "return", "refund", "warranty", "policy", "terms", or "conditions" - YOU MUST use search_terms_conditions tool and summarize the results in your answer.

IMPORTANT: When user refers to a specific product from previous search results (like "tell me more about that Samsung phone"), you MUST:
- Extract the product_id from the previous search results in conversation context
- Use the product_id with get_filtered_product_details_tool
- Use user's city preference for accurate stock information
- If user Say other Search for other brand products with same product category like smartphone the search result give smartphone of Samsung company if user say other then search fro Onepluse Smartphone or Oppo Vivo or iPhone.

CRITICAL JSON RESPONSE RULES:
❌ NEVER create nested JSON strings inside JSON
❌ NEVER wrap responses in additional data objects
❌ NEVER escape quotes in JSON values
❌ NEVER put JSON as string values
✅ Return clean, direct JSON structure
✅ Put actual objects/arrays in fields, not strings

CRITICAL ANSWER FIELD RULES:
❌ NEVER put product names, prices, or specs in "answer"
❌ NEVER put store names, addresses, or timings in "answer"
❌ NEVER put detailed product specifications in "answer"
❌ NEVER put policy text or terms content in "answer"
✅ Only put conversational guidance and insights in "answer"
✅ Set unused fields to empty arrays [] or objects {} as appropriate

EXAMPLES OF CORRECT RESPONSES:
When user asks "show me phones":
{
  "answer": "I found some great smartphones for you! These offer excellent value and modern features.",
  "products": [{"product_id": "123", "product_url":"https://www.lotuselectronics.com/product/smartphones/samsung-android-smartphone-a36-5g-8gb-ram-128gb-storagerom-a366ej-awesome-lavender/39721", "product_name": "Samsung Galaxy A36", "product_mrp": "30999", ...}],
  "stores": [],
  "product_details": {},
  "end": "What's your budget range?"
}

When user asks "tell me more about that Samsung phone" (referring to product_id from previous results):
{
  "answer": "Here are the complete specifications and availability details for that Samsung smartphone.",
  "products": [],
  "product_details": {"product_id": "123","product_url":"https://www.lotuselectronics.com/product/smartphones/samsung-android-smartphone-a36-5g-8gb-ram-128gb-storagerom-a366ej-awesome-lavender/39721", "product_name": "Samsung Galaxy A36", "product_specification": [...], ...},
  "stores": [],
  "end": "Would you like to check availability at a nearby store?"
}

When user asks "find store in Delhi":
{
  "answer": "Perfect! I found several Lotus stores in Delhi where you can visit.",
  "products": [],
  "product_details": {},
  "stores": [{"store_name": "Lotus CP", "address": "Connaught Place", ...}],
  "policy_info": {},
  "end": "Which area is most convenient for you?"
}

When user asks "what is your return policy":
{
  "answer": "Our return policy allows you to return unopened items in original packaging within 7 days of delivery for a full refund (excluding shipping costs). For damaged or defective products, contact us within 7 days for a replacement at no cost. Please note that used or tampered items may incur deduction charges of 5% to full value depending on condition. Refunds are processed to your original payment method.",
  "products": [],
  "product_details": {},
  "stores": [],
  "policy_info": {},
  "end": "Do you have a specific product you'd like to return or any other questions about our policies?"
}

When user asks "compare the last two phones" (extract both product_ids, e.g. 39422 and 39831):
{
  "answer": "Here's a side-by-side comparison of the two Redmi phones to help you decide.",
  "products": [],
  "product_details": {},
  "stores": [],
  "policy_info": {},
  "comparison": [{"name": "Redmi 14C 5G", "vs_name": "Redmi A5 4G", "differences": ["Network: Redmi has 5G vs Redmi 4G", "Storage: 64GB vs 128GB"], "spec_table": [{"feature": "Price", "a": "₹9,499", "b": "₹7,499"}], "verdict": "..."}],
  "end": "Would you like to order one of these?"
}

When user asks "recommend me a smartphone under 20000":
{
  "answer": "Based on your budget, here are some smartphones I'd recommend.",
  "products": [],
  "recommendations": [{"product_id": "38210", "product_name": "OnePlus Nord CE4 Lite 5G", "product_mrp": "₹19,999", "product_image": "...", "product_url": "...", "features": ["8GB RAM", "5500 mAh"]}],
  "end": "Would you like to compare any of these or place an order?"
}

When user asks "place an order for product 39422":
{
  "answer": "Great choice! I've placed your order for the Redmi 14C 5G. You can track it anytime using the order id below.",
  "products": [],
  "order": {"order_id": "LOTUS54321", "product_name": "Redmi 14C 5G", "status": "Processing", "order_date": "16 Jul 2026", "expected_delivery": "20 Jul 2026", "timeline": [{"stage": "Order Placed", "state": "done"}, {"stage": "Processing", "state": "current"}]},
  "end": "Is there anything else you'd like to add to your order?"
}

When user asks "track my order LOTUS1001":
{
  "answer": "Here's the latest status of your order.",
  "products": [],
  "order": {"order_id": "LOTUS1001", "product_name": "Samsung Galaxy A26 5G", "status": "Delivered", "order_date": "07 Jul 2026", "expected_delivery": "11 Jul 2026", "timeline": [...]},
  "end": "Can I help you with anything else?"
}

When a user reports an issue (e.g. "my TV screen is flickering"), FIRST help, THEN offer a ticket:
{
  "answer": "I'm sorry to hear that. A flickering screen is often fixed by checking the cable connections and updating the TV software. If that doesn't help, I can raise a support ticket so our team follows up with you.",
  "products": [],
  "end": "Would you like me to raise a support ticket for this?"
}

After the user agrees and provides details, once you have name, phone and issue, call raise_ticket and respond:
{
  "answer": "Thank you, Rahul! I've raised a support ticket for your flickering TV screen. Our team will reach out to you shortly on the number provided.",
  "products": [],
  "ticket": {"ticket_id": "TCKT48210", "name": "Rahul", "phone": "9876543210", "issue": "TV screen flickering", "status": "Open"},
  "end": "Is there anything else I can help you with in the meantime?"
}

CRITICAL POLICY_INFO RULES:
❌ NEVER nest policy tool results in additional objects like "search_terms_conditions_response"
❌ NEVER wrap policy data in extra fields
✅ Put the search_terms_conditions tool result DIRECTLY in the policy_info field
✅ Use the exact JSON structure returned by the tool without modification

CONVERSATION INTELLIGENCE:
- Remember what products/stores were already shown
- When user says "tell me more about that Samsung phone" - use get_filtered_product_details_tool with the product_id
- When user says "what about the store timings" - answer from previous store results
- Track user preferences (budget, brands, features) across conversation
- Extract product_id from previous search results when user asks for specific product details
- Always use the user's city preference for stock availability when getting product details
- Sort The Product Based on user Query.

SALES APPROACH:
- Be helpful and conversational
- Guide users toward purchase decisions
- Suggest visiting stores for hands-on experience
- Ask relevant follow-up questions
- Focus on customer needs and value
- Highlight stock availability and delivery options

REMEMBER: Return ONLY the JSON structure above. NO additional text, NO markdown formatting, NO nested JSON strings."""

# Create LLM class
llm = ChatGoogleGenerativeAI(
    model= "gemini-3.5-flash",
    temperature=0.7,
    max_retries=2,
    google_api_key=google_api_key,
    # Disable "thinking" so Gemini stops attaching large thought-signature blobs
    # to messages. Those get stored in history and re-sent, wasting tokens.
    thinking_budget=0,
    include_thoughts=False,
)

# Bind tools to the model
model = llm.bind_tools(tools)

# Test the model with tools
# res=model.invoke(f"What is the weather in Berlin on {datetime.today()}?")

# print(res)

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

tools_by_name = {tool.name: tool for tool in tools}

def call_tool(state: AgentState):
    outputs = []
    user_id = state.get("user_id", "default_user")
    
    print(f"🔧 Executing tool calls for user: {user_id}")
    
    # Iterate over the tool calls in the last message
    for tool_call in state["messages"][-1].tool_calls:
        print(f"🛠️  Calling tool: {tool_call['name']} with args: {tool_call['args']}")
        # Get the tool by name
        tool_result = tools_by_name[tool_call["name"]].invoke(tool_call["args"])
        print(f"📋 Tool result length: {len(str(tool_result))} characters")
        
        tool_message = ToolMessage(
            content=tool_result,
            name=tool_call["name"],
            tool_call_id=tool_call["id"],
        )
        outputs.append(tool_message)
        
        # Don't save ToolMessage to Redis to avoid conversation flow issues
        # redis_memory.add_message_to_user(user_id, tool_message)
    
    print(f"🎯 Returning {len(outputs)} tool message(s)")
    return {"messages": outputs}


def call_model(
    state: AgentState,
    config: RunnableConfig,
):
    # Get user ID from state
    user_id = state.get("user_id", "default_user")
    
    # Get the current conversation messages from state
    messages = state["messages"]
    
    # Get the latest user message for debugging
    latest_user_message = None
    conversation_context = []
    
    # Analyze conversation history to extract product context
    for msg in reversed(messages):
        if hasattr(msg, 'type') and msg.type == 'human':
            if latest_user_message is None:
                latest_user_message = msg.content
            conversation_context.append(msg.content)
            if len(conversation_context) >= 3:  # Get last 3 user messages for context
                break
    
    if latest_user_message:
        print(f"🔍 Processing user query: '{latest_user_message}'")
        # Add context awareness to debug output
        if len(conversation_context) > 1:
            print(f"📝 Conversation context: {conversation_context[-2::-1]}")  # Show previous messages
        
        # Debug: Show current message types in state
        message_types = []
        for msg in messages:
            if hasattr(msg, 'type'):
                message_types.append(msg.type)
        print(f"🗂️  Current message types in state: {message_types}")
    
    # For Gemini, we need to ensure proper message sequence
    # Use only the current conversation state messages with system prompt
    messages_with_system = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    
    try:
        # Invoke the model with the system prompt and the messages
        response = model.invoke(messages_with_system, config)
        
        # Debug: Check if the model called any tools
        if hasattr(response, 'tool_calls') and response.tool_calls:
            print(f"✅ Model called {len(response.tool_calls)} tool(s): {[tc['name'] for tc in response.tool_calls]}")
            # Debug: Show tool parameters
            for tool_call in response.tool_calls:
                print(f"🔧 Tool parameters: {tool_call['args']}")
        else:
            print("⚠️  Model did not call any tools")
            # Debug: Show response content preview
            if hasattr(response, 'content'):
                content_preview = response.content[:100] + "..." if len(response.content) > 100 else response.content
                print(f"📝 Response content preview: {content_preview}")
        
        # Gemini requires the original AI tool-call message, including its
        # thought_signature, when the tool result is sent back to the model.
        # Do not mutate ``response`` before LangGraph finishes this tool cycle.

        # Persist only final assistant text. Saving an AI tool-call without its
        # matching ToolMessage creates an invalid/incomplete history on the next
        # request (ToolMessages are intentionally not stored in Redis).
        if (
            hasattr(response, 'type')
            and response.type == 'ai'
            and not getattr(response, 'tool_calls', None)
        ):
            redis_memory.add_message_to_user(user_id, response)

        # We return a list, because this will get added to the existing messages state using the add_messages reducer
        return {"messages": [response]}
        
    except Exception as e:
        print(f"❌ Error in call_model: {e}")
        # Create a simple error response
        from langchain_core.messages import AIMessage
        error_response = AIMessage(content=json.dumps({
            "answer": "I'm sorry, I encountered an error while processing your request. Please try again.",
            "end": "How else can I help you with Lotus Electronics products?"
        }))
        return {"messages": [error_response]}


# Define the conditional edge that determines whether to continue or not
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    
    # Debug: show what type of message we're evaluating
    print(f"🔍 Evaluating message type: {getattr(last_message, 'type', 'unknown')}")
    
    # If called after LLM node and the last message has tool_calls, continue to tools
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print("🔄 AI made tool calls - continuing to tool execution...")
        return "continue"
    
    # If called after tools node and the last message is a tool result, continue back to LLM
    # for intelligent processing of the tool results
    if hasattr(last_message, 'type') and last_message.type == 'tool':
        print("🔄 Tool execution complete - continuing to LLM for intelligent response")
        return "continue"
        
    # If the last message is an AI message without tool calls, end
    if hasattr(last_message, 'type') and last_message.type == 'ai' and not hasattr(last_message, 'tool_calls'):
        print("🏁 AI response without tools - ending conversation")
        return "end"
    
    # Default fallback - end conversation
    print("🏁 Default case - ending conversation")
    return "end"


from langgraph.graph import StateGraph, END

# Define a new graph with our state
workflow = StateGraph(AgentState)

# 1. Add our nodes 
workflow.add_node("llm", call_model)
workflow.add_node("tools",  call_tool)
# 2. Set the entrypoint as `agent`, this is the first node called
workflow.set_entry_point("llm")
# 3. Add a conditional edge after the `llm` node is called.
workflow.add_conditional_edges(
    # Edge is used after the `llm` node is called.
    "llm",
    # The function that will determine which node is called next.
    should_continue,
    # Mapping for where to go next, keys are strings from the function return, and the values are other nodes.
    # END is a special node marking that the graph is finish.
    {
        # If `tools`, then we call the tool node.
        "continue": "tools",
        # Otherwise we finish.
        "end": END,
    },
)
# 4. Add a conditional edge after `tools` is called to continue back to LLM for processing
workflow.add_conditional_edges(
    # Edge is used after the `tools` node is called.
    "tools",
    # The function that will determine what happens after tool execution
    should_continue,
    # Tools now return data to LLM for intelligent processing
    {
        # Continue back to LLM for intelligent response creation
        "continue": "llm",
        # End only when LLM creates final response
        "end": END,
    },
)

# Add checkpointing for better state management and recovery
from langgraph.checkpoint.memory import MemorySaver
checkpointer = MemorySaver()

# Now we can compile and visualize our graph with checkpointing
graph = workflow.compile(checkpointer=checkpointer)

from datetime import datetime

def get_or_create_user_id():
    """Get user ID from input or create a new one."""
    user_input = input("Enter your user ID (or press Enter for new user): ").strip()
    if user_input:
        return user_input
    else:
        new_user_id = str(uuid.uuid4())[:8]  # Short UUID
        print(f"Created new user ID: {new_user_id}")
        return new_user_id

def display_user_stats(user_id: str):
    """Display user conversation statistics."""
    messages = redis_memory.get_user_messages(user_id)
    print(f"\n--- User {user_id} Stats ---")
    print(f"Stored messages: {len(messages)}")
    print(f"Active users: {len(redis_memory.get_active_users())}")
    print("-" * 30)

def _run_agent(message: str, session_id: str = "default_session") -> str:
    """
    Chat with the Lotus Electronics agent for Flask integration.

    Args:
        message: User's message
        session_id: Unique session identifier for conversation memory

    Returns:
        JSON string response from the agent
    """
    try:
        # Use session_id as user_id for Redis memory
        user_id = session_id

        # Make the session available to order tools and log the user's message
        set_current_session(session_id)
        try:
            store.log_message(session_id, "user", message)
        except Exception as log_err:
            print(f"⚠️  Failed to log user message: {log_err}")

        # Check Redis connection health
        redis_available = hasattr(redis_memory, 'test_connection') and redis_memory.test_connection()
        if not redis_available:
            print("⚠️  Redis not available - running without conversation memory")

        # Create user message
        from langchain_core.messages import HumanMessage
        user_msg = HumanMessage(content=message)
        
        # Load previous conversation context (limited for Gemini compatibility)
        previous_messages = []
        if redis_available:
            previous_messages = redis_memory.get_user_messages(user_id)
        
        # Filter and limit conversation history for better Gemini compatibility
        context_messages = []
        for msg in previous_messages[-6:]:  # Only last 6 messages for context
            if hasattr(msg, 'type') and msg.type in ['human', 'ai']:
                context_messages.append(msg)
        
        # Save user message to Redis memory if available
        if redis_available:
            redis_memory.add_message_to_user(user_id, user_msg)
        
        # Prepare inputs for the graph with conversation context
        all_messages = context_messages + [user_msg]
        inputs = {
            "messages": all_messages,
            "user_id": user_id,
            "number_of_steps": 0
        }
        
        # Configure checkpointing with thread ID based on session.
        # recursion_limit caps how many graph steps run before LangGraph stops,
        # a hard guard against tool-call loops.
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 25,
        }

        # Process through the graph
        final_response = None
        last_tool_result = None
        response_count = 0
        max_iterations = 20  # Prevent infinite loops

        try:
            for state in graph.stream(inputs, config=config, stream_mode="values"):
                response_count += 1
                if response_count > max_iterations:
                    print("⚠️  Max iterations reached - stopping graph stream")
                    break

                # Get the last message from the final state
                if "messages" in state and state["messages"]:
                    last_message = state["messages"][-1]
                    msg_type = getattr(last_message, "type", None)
                    # Remember the most recent tool output for fallback recovery
                    if msg_type == "tool" and getattr(last_message, "content", None):
                        last_tool_result = last_message.content
                    if hasattr(last_message, 'content') and msg_type is not None:
                        # Accept AI responses as final (tools feed data to LLM)
                        if msg_type == 'ai' and last_message.content:
                            content = last_message.content
                            # Gemini can return content as a list of parts
                            if isinstance(content, list):
                                content = "".join(
                                    part.get("text", "") if isinstance(part, dict) else str(part)
                                    for part in content
                                )
                            if content and content.strip():
                                print(f"🤖 Got AI response: {len(content)} chars")
                                final_response = content
                                # Don't break - allow further tool calls to refine
        except Exception as stream_err:
            # e.g. GraphRecursionError from a tool loop — degrade gracefully
            print(f"⚠️  Graph stream stopped early: {type(stream_err).__name__}: {stream_err}")

        # Clean and validate the response
        if final_response:
            # Clean the response from any markdown formatting
            clean_response = final_response.strip()
            if clean_response.startswith('```json'):
                clean_response = clean_response.replace('```json', '').replace('```', '').strip()
            
            try:
                # Check if it's already valid JSON
                parsed_json = json.loads(clean_response)
                print(f"🔧 Initial parsing successful. Keys: {list(parsed_json.keys()) if isinstance(parsed_json, dict) else 'Not a dict'}")
                
                # Handle deeply nested JSON structure from data.answer field
                def parse_nested_structure(data_dict):
                    """Recursively parse nested JSON structures and product details output"""
                    if isinstance(data_dict, dict):
                        # Check for data.answer structure first (most complex nesting)
                        if 'data' in data_dict and isinstance(data_dict['data'], dict):
                            data_content = data_dict['data']
                            if 'answer' in data_content and isinstance(data_content['answer'], str):
                                try:
                                    # Parse the nested JSON in data.answer
                                    nested_json = json.loads(data_content['answer'])
                                    if isinstance(nested_json, dict):
                                        # Recursively process any further nesting
                                        nested_json = parse_nested_structure(nested_json)
                                        return nested_json
                                except (json.JSONDecodeError, TypeError) as e:
                                    print(f"🔧 Failed to parse data.answer as JSON: {e}")
                            # If data.answer parsing fails, return the data content
                            return data_content
                        
                        # Check for direct answer field with nested JSON
                        if 'answer' in data_dict and isinstance(data_dict['answer'], str):
                            try:
                                # Try to parse answer as JSON first
                                nested_json = json.loads(data_dict['answer'])
                                if isinstance(nested_json, dict):
                                    # Recursively process the nested JSON
                                    nested_json = parse_nested_structure(nested_json)
                                    return nested_json
                            except (json.JSONDecodeError, TypeError) as e:
                                print(f"🔧 Failed to parse direct answer as JSON: {e}")
                        
                        # Process product_details output field if present at any level
                        if 'product_details' in data_dict and isinstance(data_dict['product_details'], dict):
                            if 'output' in data_dict['product_details']:
                                try:
                                    import ast
                                    output_str = data_dict['product_details']['output']
                                    print(f"🔧 Parsing product_details output: {output_str[:100]}...")
                                    product_details_obj = ast.literal_eval(output_str)
                                    data_dict['product_details'] = product_details_obj
                                    print(f"✅ Successfully parsed product details")
                                except (ValueError, SyntaxError) as e:
                                    print(f"❌ Error parsing product details output: {e}")
                                    # If parsing fails, keep the original structure
                                    pass
                    
                    return data_dict
                
                # Apply nested structure parsing
                print(f"🔧 Original response structure: {list(parsed_json.keys()) if isinstance(parsed_json, dict) else type(parsed_json)}")
                parsed_json = parse_nested_structure(parsed_json)
                print(f"🔧 Final response structure: {list(parsed_json.keys()) if isinstance(parsed_json, dict) else type(parsed_json)}")
                
                # Ensure we have the expected structure - if it's missing top-level fields, try to extract them
                if isinstance(parsed_json, dict):
                    # If we don't have expected keys, the LLM might have wrapped everything in a data field
                    expected_keys = {'answer', 'products', 'product_details', 'stores', 'end'}
                    current_keys = set(parsed_json.keys())
                    
                    if not any(key in current_keys for key in expected_keys):
                        print("⚠️  Response doesn't have expected structure. Trying to extract from nested fields...")
                        # Try to find the actual response structure in nested fields
                        if 'data' in parsed_json:
                            parsed_json = parsed_json['data']
                            print(f"🔧 Extracted from data field. New keys: {list(parsed_json.keys())}")
                
                # Return properly formatted JSON
                return json.dumps(parsed_json, ensure_ascii=False, indent=2)
                
            except json.JSONDecodeError:
                # Try to extract JSON from the response
                import re
                json_match = re.search(r'\{.*\}', clean_response, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json_match.group(0)
                        parsed_json = json.loads(extracted_json)
                        
                        # Apply the same nested structure parsing to extracted JSON
                        parsed_json = parse_nested_structure(parsed_json)
                        
                        return json.dumps(parsed_json, ensure_ascii=False, indent=2)
                    except:
                        pass
                
                # Wrap non-JSON response in JSON format with contextual handling
                # Provide contextual responses based on user message
                user_msg_lower = message.lower() if message else ""
                
                if any(greeting in user_msg_lower for greeting in ['hello', 'hi', 'hey', 'helo']):
                    fallback_response = {
                        "answer": "Hello! Welcome to Lotus Electronics! I'm here to help you find the perfect electronics products. What are you looking for today?",
                        "products": [],
                        "product_details": {},
                        "stores": [],
                        "policy_info": {},
                        "end": "I can help you find TVs, smartphones, laptops, home appliances, and more. What interests you?"
                    }
                elif any(help_word in user_msg_lower for help_word in ['help', 'assist', 'support']):
                    fallback_response = {
                        "answer": "I'd be happy to help! I can assist you with finding products, getting detailed specifications, locating nearby stores, and checking availability.",
                        "products": [],
                        "product_details": {},
                        "stores": [],
                        "policy_info": {},
                        "end": "What would you like to explore - TVs, smartphones, laptops, or something else?"
                    }
                elif any(thanks in user_msg_lower for thanks in ['thanks', 'thank you', 'thx']):
                    fallback_response = {
                        "answer": "You're welcome! I'm glad I could help.",
                        "products": [],
                        "product_details": {},
                        "stores": [],
                        "policy_info": {},
                        "end": "Is there anything else you'd like to know about our electronics collection?"
                    }
                else:
                    # Generic fallback with the original response
                    fallback_response = {
                        "answer": clean_response if clean_response else "I understand. How can I help you with Lotus Electronics products?",
                        "products": [],
                        "product_details": {},
                        "stores": [],
                        "policy_info": {},
                        "end": "Are you looking for any specific electronics or need help finding a store?"
                    }
                
                return json.dumps(fallback_response, ensure_ascii=False, indent=2)
        else:
            # No final AI text (e.g. the model looped on tool calls). Try to
            # recover something useful from the last tool result before giving up.
            recovery = {
                "answer": "Here's what I found for you.",
                "products": [],
                "product_details": {},
                "stores": [],
                "policy_info": {},
                "comparison": [],
                "recommendations": [],
                "order": {},
                "end": "Is there anything else I can help you with?"
            }
            recovered = False
            tool_data = last_tool_result
            if isinstance(tool_data, str):
                try:
                    tool_data = json.loads(tool_data)
                except Exception:
                    tool_data = None
            if isinstance(tool_data, dict) and not tool_data.get("error"):
                if tool_data.get("spec_table"):
                    recovery["comparison"] = [tool_data]
                    recovery["answer"] = "Here's a side-by-side comparison of the two products."
                    recovered = True
                elif tool_data.get("order_id"):
                    recovery["order"] = tool_data
                    recovery["answer"] = "Here are your order details."
                    recovered = True
            elif isinstance(tool_data, list) and tool_data:
                recovery["products"] = tool_data
                recovery["answer"] = "Here are some products that match your request."
                recovered = True

            if not recovered:
                recovery["answer"] = (
                    "I had a little trouble putting that together. Could you rephrase "
                    "or tell me the specific products you'd like to compare or view?"
                )
            return json.dumps(recovery, ensure_ascii=False, indent=2)
            
    except Exception as e:
        print(f"❌ Error in chat_with_agent: {type(e).__name__}: {str(e)}")
        
        # Specific handling for different error types
        if "Input/output error" in str(e) or "Errno 5" in str(e):
            error_message = "I'm experiencing connectivity issues. Please check if Redis server is running and try again."
        elif "Redis" in str(e):
            error_message = "Database connection issue. Please ensure Redis server is running on localhost:6379."
        else:
            error_message = f"Technical issue occurred: {str(e)}. Please try again in a moment."
        
        # Error response in JSON format
        error_response = {
            "answer": f"I'm sorry, there was a technical issue. {error_message}",
            "products": [],
            "product_details": {},
            "stores": [],
            "policy_info": {},
            "end": "Is there anything else I can help you with from our electronics collection?"
        }
        return json.dumps(error_response, ensure_ascii=False, indent=2)


def chat_with_agent(message: str, session_id: str = "default_session") -> str:
    """Public entry point: run the agent and persist the assistant reply.

    Wraps `_run_agent` so every turn's assistant answer is logged to SQLite for
    the admin portal. Logging failures never affect the returned response.
    """
    response = _run_agent(message, session_id)
    try:
        answer_text = response
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and parsed.get("answer"):
                answer_text = parsed["answer"]
        except Exception:
            pass
        store.log_message(session_id, "assistant", answer_text)
    except Exception as log_err:
        print(f"⚠️  Failed to log assistant message: {log_err}")
    return response


# Main execution - only run when script is executed directly
if __name__ == "__main__":
    # Get user ID
    user_id = get_or_create_user_id()
    display_user_stats(user_id)

    # Welcome message
    print("\n" + "="*60)
    print("🏪 Welcome to Lotus Electronics Official Chatbot! 🏪")
    print("Your trusted partner for all electronics needs")
    print("="*60)
    print("\n💡 Available commands:")
    print("   • Ask about any electronics products")
    print("   • Ask about store locations ('find store in [city]')")
    print("   • Ask for product details ('tell me more about that Samsung phone')")
    print("   • 'stats' - View your conversation stats")  
    print("   • 'clear' - Clear conversation history")
    print("   • 'quit'/'exit'/'bye' - End conversation")
    print("\n🔍 Example queries:")
    print("   • 'Show me Samsung ACs under 50000'")
    print("   • 'Find gaming laptops between 60000 and 100000'")
    print("   • 'I need wireless headphones'")
    print("   • 'Tell me more about that iPhone' (after seeing product list)")
    print("   • 'Find store in Indore'")
    print("   • 'Show me stores near 452001'")
    print("   • 'What is your return policy?'")
    print("   • 'Tell me about warranty terms'")
    print("   • 'How do you protect my privacy?'")
    print("   • 'What are the refund conditions?'")
    print("-"*60)

    # Chat loop
    while True:
        try:
            # Create our initial message dictionary
            input_message = input("\n🛍️ Lotus Electronics Customer: ")
            
            if input_message.lower() in ['quit', 'exit', 'bye']:
                print("Thank you for visiting Lotus Electronics! Have a great day! 🙏")
                break
            elif input_message.lower() == 'clear':
                redis_memory.clear_user_messages(user_id)
                print("✅ Conversation history cleared!")
                continue
            elif input_message.lower() == 'stats':
                display_user_stats(user_id)
                continue
            
            # Use the chat_with_agent function
            response = chat_with_agent(input_message, user_id)
            
            # Parse and display the response
            try:
                # Clean the response if it contains markdown formatting
                clean_response = response.strip()
                if clean_response.startswith('```json'):
                    # Remove markdown json formatting
                    clean_response = clean_response.replace('```json', '').replace('```', '').strip()
                
                parsed_json = json.loads(clean_response)
                
                # Display formatted response
                print(f"\n🤖 Lotus Electronics Assistant:")
                print(f"💬 {parsed_json.get('answer', '')}")
                
                if 'products' in parsed_json and parsed_json['products']:
                    print(f"\n📦 Products Found ({len(parsed_json['products'])}):")
                    for i, product in enumerate(parsed_json['products'], 1):
                        print(f"\n{i}. 🏷️ {product.get('product_name', 'N/A')}")
                        print(f"   💰 Price: {product.get('product_mrp', 'N/A')}")
                        if product.get('features'):
                            print(f"   ✨ Features: {', '.join(product['features'][:2])}")
                        if product.get('product_url'):
                            print(f"   🔗 URL: {product['product_url']}")
                
                if 'product_details' in parsed_json and parsed_json['product_details']:
                    details = parsed_json['product_details']
                    print(f"\n🔍 Product Details:")
                    print(f"📱 {details.get('product_name', 'N/A')}")
                    print(f"💰 Price: ₹{details.get('product_mrp', 'N/A')}")
                    print(f"📦 SKU: {details.get('product_sku', 'N/A')}")
                    if details.get('instock'):
                        stock_status = "✅ In Stock" if details['instock'].lower() == 'yes' else "❌ Out of Stock"
                        print(f"📦 Stock: {stock_status}")
                    
                    # Display top 5 specifications with priority for warranty
                    if details.get('product_specification') and isinstance(details['product_specification'], list):
                        specs = details['product_specification']
                        
                        # Look for warranty and move to front
                        warranty_spec = None
                        filtered_specs = []
                        for spec in specs:
                            if isinstance(spec, dict) and spec.get('fkey') and 'warranty' in spec['fkey'].lower():
                                warranty_spec = spec
                            else:
                                filtered_specs.append(spec)
                        
                        # Create final specs list with warranty first
                        final_specs = []
                        if warranty_spec:
                            final_specs.append(warranty_spec)
                        final_specs.extend(filtered_specs[:4] if warranty_spec else filtered_specs[:5])
                        
                        print(f"📋 Key Specifications:")
                        for spec in final_specs:
                            if isinstance(spec, dict) and spec.get('fkey') and spec.get('fvalue'):
                                print(f"   • {spec['fkey']}: {spec['fvalue']}")
                    
                    if details.get('meta_desc'):
                        desc = details['meta_desc'][:150] + "..." if len(details['meta_desc']) > 150 else details['meta_desc']
                        print(f"📝 Description: {desc}")
                    
                    if details.get('del'):
                        delivery = details['del']
                        print(f"🚚 Delivery Options:")
                        if delivery.get('std'):
                            print(f"   • Standard: {delivery['std']}")
                        if delivery.get('t3h'):
                            print(f"   • Express: {delivery['t3h']}")
                        if delivery.get('stp'):
                            print(f"   • Store Pickup: {delivery['stp']}")
                
                if 'stores' in parsed_json and parsed_json['stores']:
                    print(f"\n🏪 Stores Found ({len(parsed_json['stores'])}):")
                    for i, store in enumerate(parsed_json['stores'], 1):
                        print(f"\n{i}. 🏬 {store.get('store_name', 'N/A')}")
                        print(f"   📍 {store.get('address', 'N/A')}, {store.get('city', 'N/A')} - {store.get('zipcode', 'N/A')}, {store.get('state', 'N/A')}")
                        print(f"   🕒 {store.get('timing', 'N/A')}")
                
                if 'end' in parsed_json and parsed_json['end']:
                    print(f"\n❓ {parsed_json['end']}")
                    
            except json.JSONDecodeError as e:
                print(f"\n🤖 Lotus Electronics Assistant:")
                # Try to extract JSON from the response if it's wrapped in other text
                try:
                    # Look for JSON pattern in the response
                    import re
                    json_match = re.search(r'\{.*\}', response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                        parsed_json = json.loads(json_str)
                        print(f"💬 {parsed_json.get('answer', '')}")
                        
                        if 'products' in parsed_json and parsed_json['products']:
                            print(f"\n📦 Products Found ({len(parsed_json['products'])}):")
                            for i, product in enumerate(parsed_json['products'], 1):
                                print(f"\n{i}. 🏷️ {product.get('product_name', 'N/A')}")
                                print(f"   💰 Price: {product.get('product_mrp', 'N/A')}")
                                if product.get('features'):
                                    print(f"   ✨ Features: {', '.join(product['features'][:2])}")
                        
                        if 'product_details' in parsed_json and parsed_json['product_details']:
                            details = parsed_json['product_details']
                            print(f"\n🔍 Product Details:")
                            print(f"📱 {details.get('product_name', 'N/A')}")
                            print(f"💰 Price: ₹{details.get('product_mrp', 'N/A')}")
                            if details.get('instock'):
                                stock_status = "✅ In Stock" if details['instock'].lower() == 'yes' else "❌ Out of Stock"
                                print(f"📦 Stock: {stock_status}")
                            
                            # Display key specifications
                            if details.get('product_specification') and isinstance(details['product_specification'], list):
                                specs = details['product_specification'][:5]  # Top 5 specs
                                print(f"📋 Key Specifications:")
                                for spec in specs:
                                    if isinstance(spec, dict) and spec.get('fkey') and spec.get('fvalue'):
                                        print(f"   • {spec['fkey']}: {spec['fvalue']}")
                        
                        if 'stores' in parsed_json and parsed_json['stores']:
                            print(f"\n🏪 Stores Found ({len(parsed_json['stores'])}):")
                            for i, store in enumerate(parsed_json['stores'], 1):
                                print(f"\n{i}. 🏬 {store.get('store_name', 'N/A')}")
                                print(f"   📍 {store.get('address', 'N/A')}")
                        
                        if 'end' in parsed_json and parsed_json['end']:
                            print(f"\n❓ {parsed_json['end']}")
                    else:
                        # Fallback: display raw response
                        print(response)
                except:
                    print(response)
                
        except KeyboardInterrupt:
            print("\nThank you for visiting Lotus Electronics! Have a great day! 🙏")
            break
        except Exception as e:
            print(f"❌ An error occurred: {e}")
            print("Please try again or contact our support team.")
            continue
