import os
import uuid
import re
import logging
from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.memory import InMemorySaver
from collections import deque
from datetime import datetime, timedelta
import json
import redis
from chat_context import build_chat_context, message_text, empty_product_search_response
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
    bulk_enquiry: dict

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
            decode_responses=False,
            protocol=2,
            socket_connect_timeout=2,
            socket_timeout=2,
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
from tools.bulk_order_tools import create_bulk_order_enquiry, prepare_bulk_order_enquiry, normalize_bulk_response

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
    create_bulk_order_enquiry,
    prepare_bulk_order_enquiry,
]

from datetime import datetime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage

# System prompt for Lotus Electronics chatbot
SYSTEM_PROMPT = """You are Lotus Electronics Sales Assistant - helping customers find electronics products and store locations in India.
Preserve all tool-provided pricing fields on product objects: mrp, selling_price,
discount_amount, discount_percent and store_offer_price. product_mrp is the legacy
ONLINE SELLING price, not list MRP; mrp is list MRP. Store offer prices are conditional
in-store offers and must not replace the online selling price. Do not invent prices
or omit the supplied pricing fields from products, recommendations or product_details.

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
  "bulk_enquiry": {saved enquiry object if create_bulk_order_enquiry succeeded},
  "end": "follow-up question to continue conversation"
}

TOOL USAGE RULES:
1. Use search_products ONLY when user asks for NEW products they haven't seen yet
2. Use get_near_store ONLY when user asks about store locations by city or zipcode
3. Use get_filtered_product_details_tool ONLY when the user wants MORE DETAILS about
   ONE specific product. Use a product_id provided by the user or from previous results;
   if no ID can be resolved, ask which product instead of inventing details. NEVER
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
7. Use place_order ONLY for an INDIVIDUAL personal purchase, never for bulk,
   employee gifting, corporate or institutional procurement. For those requests
   use the BULK ENQUIRY FLOW below even when the customer says "place order".
   For an individual purchase of a specific product ("order this",
   "buy", "place an order", "I want to purchase"). Extract the product_id. Put the
   returned order object in the "order" field ONLY if it has an order_id and no error.
   On an error, leave order empty and explain the actual error_code. Never translate
   availability_unverified or a failed product lookup into "out of stock".
   Pass the user's city when known. The current order tool creates local demo orders:
   if is_demo is true, explicitly call it a demo order, never a real retailer purchase.
8. Use track_order when the user wants the STATUS of an order ("track my order",
   "where is my order", "order status") and gives an order id like LOTUS1001. Put
   the returned order object in the "order" field.
9. Use browse_catalog to browse indexed products by category and budget.
   Search, recommendations and browsing use the same Pinecone product index.
   Once the customer supplies a budget/use case (e.g. "office work, 45000" after
   asking for a laptop), search the previous category with that exact budget and
   use case. Do not ask for those details again. Pass category="laptop" for laptop
   computers, or a requested subtype (gaming, Windows, MacBook, convertible, thin
   and light); include the full family for a broad laptop request.
   Preserve category, brand and use case on follow-ups such as "other" or "HP".
   An explicitly changed budget replaces the old budget; never silently exceed it.
   If no in-stock product fits, explain the checked budget/stock limits and offer
   another brand/store within that budget or an explicitly labelled budget change.
   If a tool returns an availability error, explain it; do not retry through another
   product tool or invent products, specifications, prices or URLs. Empty results
   mean no matches among the catalogue records checked, not proof that a product
   is unreleased, discontinued, nonexistent or unavailable everywhere. Never infer
   launch dates or release status from empty results, past replies or model memory.
   Search the requested model even if it is newer than your training knowledge.
   Prices/stock are from a SQL snapshot, not live guarantees.
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

BULK ENQUIRY FLOW - applies when the CURRENT request is to arrange a bulk purchase:
- A pending enquiry is not a lock on the conversation. Answer the CURRENT request
  first: specifications -> product details; nearby store -> store lookup; compare
  -> comparison. Do not call any bulk tool on those turns. Resume collection only
  when the customer returns to their quotation request or supplies its details.
- A customer message may both identify a product/quantity and ask for specifications.
  Show the specifications first and remember the supplied details for later.
  Example: "Show details for Morphy Richards 60 RCSS, 20" during bulk collection:
  use the product details tool, NOT prepare_bulk_order_enquiry. Do not repeatedly
  ask for the product/name/mobile already present in the customer messages.
- Understand intent from the WHOLE conversation, not individual keywords. Employee,
  staff/client gifting, corporate/institutional purchases, team equipment and bulk
  units belong here. A single gift for one person is not automatically a bulk enquiry.
- Gift ideas alone mean discovery: use existing search/recommendation tools. Do not
  create any enquiry just because a company or employees were mentioned.
- When the customer wants to proceed with a bulk purchase, collect the selected
  product or product requirement, quantity, delivery city, contact name and phone.
  Use known information. Ask one or two missing questions at a time in the user's
  language. Never invent a quantity, city, name, phone, product ID or confirmation.
- Ask company name, per-unit budget, desired delivery date, email, delivery PIN
  and GST invoice requirement, 1-2 questions per turn. Each may be explicitly
  declined/deferred; do not silently skip them. Do not ask for GSTIN or payment.
  Reuse details already supplied; never repeatedly ask answered questions.
  Preserve a known per-unit budget, but never call it a bulk quotation.
- Never use placeholders such as "Corporate Customer", a default phone, 50 units
  or Indore. Assistant messages, product examples and previous demo orders are NOT
  evidence for customer details. A "yes" after product specs is product interest,
  not a quantity, contact detail or approval of an enquiry summary.
- Once every detail is supplied or explicitly deferred, call prepare_bulk_order_enquiry
  with a verbatim customer quote for each field. Use the customer's wording for names,
  city, purpose and deadline. The tool verifies quotes against the actual transcript.
  Wait for a NEW customer turn after the prepared summary; never prepare and submit
  in the same turn. If preparation fails, ask the missing questions and stop.
- Show a short summary of product/requirement, units, city, contact and any supplied
  company/budget/date. Explain this submits a quotation enquiry, not a confirmed
  purchase. Ask explicit permission to submit. A previous "order this" or "okay"
  before this summary is NOT approval of the completed summary.
- After approval of the prepared summary call create_bulk_order_enquiry with
  confirmed=true and confirmation_message copied from the CURRENT user message.
  Never call it before prepare_bulk_order_enquiry. Any change needs a fresh prepared
  summary and new approval. Use exactly the prepared details. Put its exact
  successful object in bulk_enquiry; leave order and ticket empty. Confirm the BULK
  enquiry reference and quotation-pending status, not "order successfully placed".
- No successful tool result means no confirmation. On validation/save failure ask
  for the missing detail or explain failure; NEVER fall back to place_order or
  raise_ticket. Never invent dispatch/delivery dates, bulk discounts or reservations.
- The enquiry is saved for admin review. There is no automatic team notification,
  callback SLA or checkout integration: do not claim that staff were contacted.
  Do not promise a call, a reply soon, or that the team will get back to the customer.
  Say the enquiry is saved and pricing, stock and delivery await confirmation.
- Example: "i want to giving the bulk order on this product" after Noise headphone
  details -> ask "Kitne pieces chahiye, aur delivery kis city mein hogi?" (only ask
  missing fields), NOT a demo order. "Haan" after a complete summary -> submit enquiry.

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
- Requests like "tell me aviable", "which one is avaivle", "available options",
  or agreement to an offer of alternatives mean SEARCH FOR AVAILABLE ALTERNATIVES.
  Call recommend_products(in_stock_only=True) with the previous category, budget,
  city and rejected product as based_on_product_id when known. Do not repeat the
  rejected item's stock message or ask again whether they want recommendations.
- For individual purchases only, "okay/yes/haan" after offering to order ONE specific product means call place_order
  for that product. If several products were offered without a single selection,
  ask which one. Resolve context from the immediately preceding exchange.
- Only claim "in stock"/"out of stock" from stock_verified=true live tool results
  for the customer's city. Snapshot listings, lookup errors and unknown values do
  not establish current stock. Never say "order right away" from search results.
- For availability_unverified, explain that stock could not be checked. Offer the
  supplied product link or a stock recheck; do not invent availability for another item.
- When the user has already requested alternatives or accepted an offer, act on it.
  Do not repeat the same question in both answer and end.
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

PRIMARY_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
FALLBACK_GEMINI_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
logger = logging.getLogger(__name__)


def _build_model(model_name):
    """Build a tool-capable Gemini client with bounded SDK retries."""
    return ChatGoogleGenerativeAI(
        model=model_name,
        temperature=0.2,
        max_retries=3,
        google_api_key=google_api_key,
    ).bind_tools(tools)


# Use a second model only when the primary provider request fails. This keeps
# tool schemas and the customer-facing JSON contract unchanged.
model = _build_model(PRIMARY_GEMINI_MODEL)
fallback_model = (
    _build_model(FALLBACK_GEMINI_MODEL)
    if FALLBACK_GEMINI_MODEL != PRIMARY_GEMINI_MODEL else None
)
# Render tool results with a client that has no tools bound. A prompt saying
# "do not call tools again" alone did not prevent a second, unrelated bulk call.
response_model = model.bound
fallback_response_model = fallback_model.bound if fallback_model else None

# Test the model with tools
# res=model.invoke(f"What is the weather in Berlin on {datetime.today()}?")

# print(res)

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig

tools_by_name = {tool.name: tool for tool in tools}

def call_tool(state: AgentState, config: RunnableConfig):
    outputs = []
    structured = {}
    user_id = state.get("user_id", "default_user")
    bulk_tools = {"create_bulk_order_enquiry", "prepare_bulk_order_enquiry"}
    selected_tools = {call["name"] for call in state["messages"][-1].tool_calls}
    mixed_bulk_turn = bool(selected_tools & bulk_tools and selected_tools - bulk_tools)
    
    print(f"🔧 Executing tool calls for user: {user_id}")
    
    # Iterate over the tool calls in the last message
    for tool_call in state["messages"][-1].tool_calls:
        print(f"Calling tool: {tool_call['name']}; argument fields: {list(tool_call['args'])}")
        # Get the tool by name
        if mixed_bulk_turn and tool_call["name"] in bulk_tools:
            tool_result = json.dumps({"error": "Bulk submission/preparation is deferred. Answer the product/store/information request from the other tool results first."})
        else:
            tool_result = tools_by_name[tool_call["name"]].invoke(tool_call["args"], config=config)
        if tool_call["name"] in bulk_tools and not mixed_bulk_turn:
            if isinstance(tool_result, str):
                try:
                    tool_result = json.loads(tool_result)
                except ValueError:
                    pass
            structured["bulk_enquiry"] = tool_result if isinstance(tool_result, dict) else {
                "error": tool_result, "error_code": "bulk_validation_failed"}
            tool_result = json.dumps(structured["bulk_enquiry"], ensure_ascii=False)
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
    return {"messages": outputs, **structured}


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
    rendering_tools = bool(messages and getattr(messages[-1], "type", None) == "tool")
    messages_for_model = messages
    if rendering_tools:
        # Keep every result when the first decision selected multiple tools. Do
        # not replay historical tool calls or expose tools in this response phase.
        start = len(messages) - 1
        while start >= 0 and getattr(messages[start], "type", None) == "tool":
            start -= 1
        results = [{"tool": m.name, "result": message_text(m.content)} for m in messages[start + 1:]]
        empty_response = empty_product_search_response(results)
        if empty_response is not None:
            from langchain_core.messages import AIMessage
            return {"messages": [AIMessage(content=json.dumps(empty_response, ensure_ascii=False))]}
        messages_for_model = list(messages[:start]) + [HumanMessage(content=(
            "Answer the customer's latest request using these tool results as data. "
            "Do not restart another flow or claim a successful action on an error. "
            "For validation errors, ask only genuinely missing details, using the customer history. "
            "Return JSON only. Results: " + json.dumps(results, ensure_ascii=False)))]
    from live_product_enrichment import enabled as live_enabled
    system_prompt = SYSTEM_PROMPT
    if live_enabled():
        system_prompt += (
            "\nLIVE CATALOGUE MODE: For current prices or availability, call a product tool "
            "on this turn using the customer's city. Current-turn tool price_verified, "
            "stock_verified and checked_at fields override historical/snapshot values. "
            "Do not quote a current price when price_verified is false; say it could not "
            "be verified. Unknown stock is not out of stock. Preserve the exact product "
            "IDs and backend card fields. Budget results cover only the checked candidates. "
            "When catalogue_fallback is true, show the real catalogue product cards and View product links. "
            "catalogue_price is a last-known price, never a verified current price or guaranteed budget match. "
            "Show catalogue_products as unconfirmed catalogue options, not in-stock recommendations. "
            "Explain the verification notice; do not replace available catalogue cards with a generic apology "
            "or invent alternatives above the customer's budget."
        )
    messages_with_system = [SystemMessage(content=system_prompt)] + messages_for_model
    selected_model = response_model if rendering_tools else model
    selected_fallback = fallback_response_model if rendering_tools else fallback_model
    
    try:
        # Invoke the primary model, then make one model-level fallback attempt
        # for temporary provider failures such as 503 or exhausted model quota.
        try:
            response = selected_model.invoke(messages_with_system, config)
        except Exception as primary_error:
            if not selected_fallback:
                raise
            logger.warning("Primary Gemini model %s failed (%s); using fallback %s",
                           PRIMARY_GEMINI_MODEL, type(primary_error).__name__,
                           FALLBACK_GEMINI_MODEL)
            response = selected_fallback.invoke(messages_with_system, config)
        
        # Debug: Check if the model called any tools
        if hasattr(response, 'tool_calls') and response.tool_calls:
            print(f"✅ Model called {len(response.tool_calls)} tool(s): {[tc['name'] for tc in response.tool_calls]}")
            # Debug: Show tool parameters
            for tool_call in response.tool_calls:
                print(f"Tool parameter fields: {list(tool_call['args'])}")
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
        # Only the final normalized response is persisted by chat_with_agent.

        # We return a list, because this will get added to the existing messages state using the add_messages reducer
        return {"messages": [response]}
        
    except Exception as e:
        logger.exception("Gemini request failed after configured fallbacks")
        print(f"❌ Error in call_model: {type(e).__name__}", flush=True)
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
workflow.add_node("respond", call_model)
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
workflow.add_edge("tools", "respond")
workflow.add_edge("respond", END)

# SQLite/Redis supply the conversation once per request. Retaining the same
# history in a graph checkpoint appended duplicates and replayed old tool turns.
graph = workflow.compile()

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

def _run_agent(message: str, session_id: str = "default_session", *, actions=None) -> str:
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
            current_message_id = store.log_message(session_id, "user", message)
        except Exception as log_err:
            current_message_id = None
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
        
        # Use each actual message exactly once, including the fields/cards the
        # customer has already supplied or seen. Cache is only a legacy fallback.
        try:
            rows = store.get_chat_context(session_id)
            rows = [row for row in rows if current_message_id is None or row['id'] < current_message_id]
            context_messages = build_chat_context(rows, previous_messages)
        except Exception:
            context_messages = [msg for msg in previous_messages[-40:]
                                if getattr(msg, 'type', None) in ('human', 'ai')
                                and not getattr(msg, 'tool_calls', None)]
        
        # Save user message to Redis memory if available
        if redis_available:
            redis_memory.add_message_to_user(user_id, user_msg)
        
        # Prepare inputs for the graph with conversation context
        all_messages = context_messages + [user_msg]
        inputs = {
            "messages": all_messages,
            "user_id": user_id,
            "number_of_steps": 0,
            "bulk_enquiry": {},
        }
        
        # Pass the session to tools; conversation state comes from durable logs.
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
                from live_product_enrichment import enabled as live_enabled, collect_live_products
                if actions is not None and live_enabled():
                    actions["live_products"] = collect_live_products(state.get("messages", []))
                if actions is not None and state.get("bulk_enquiry"):
                    actions["bulk_enquiry"] = state["bulk_enquiry"]
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


def chat_with_agent(message: str, session_id: str = "default_session", *,
                    product_id: int = None, city: str = "INDORE") -> str:
    """Resolve card selections directly, or run the agent, and persist the reply.

    Wraps `_run_agent` so every turn's assistant answer is logged to SQLite for
    the admin portal. Logging failures never affect the returned response.
    """
    actions = {}
    if product_id is None:
        response = _run_agent(message, session_id, actions=actions)
    else:
        # Ask-about is a fixed detail action. Preserve all API fields without
        # relying on model tool selection, model rendering, or Redis history.
        try:
            store.log_message(session_id, "user", message)
            from langchain_core.messages import HumanMessage
            redis_memory.add_message_to_user(session_id, HumanMessage(content=message))
        except Exception as log_err:
            print(f"Failed to log product detail request: {log_err}")
        try:
            detail = get_filtered_product_details_tool.invoke({"product_id": product_id, "city": city})
        except Exception as detail_error:
            print(f"Product detail lookup failed: {type(detail_error).__name__}")
            detail = {}
        valid_detail = (isinstance(detail, dict) and not detail.get("error")
                        and str(detail.get("product_id")) == str(product_id)
                        and bool(detail.get("product_name")))
        if valid_detail:
            if detail.get("source") != "live_api" and not detail.get("catalogue_fallback"):
                from live_product_enrichment import merge_live, live_card_fields
                detail = merge_live(detail, None, city)
                detail.update(live_card_fields(detail))
            actions["live_products"] = {str(product_id): detail}
        response = json.dumps({
            "answer": ("Here are the details for your selected product." if valid_detail else
                       "Product details could not be retrieved. Please try again in a moment."),
            "products": [], "product_details": detail if valid_detail else {},
            "stores": [], "recommendations": [],
            "end": "Stock availability is specific to the selected city." if valid_detail else "",
        }, ensure_ascii=False)
    try:
        parsed_response = json.loads(response)
        if isinstance(parsed_response, dict):
            from live_product_enrichment import enabled as live_enabled, normalize_live_response
            if live_enabled() or product_id is not None:
                parsed_response = normalize_live_response(parsed_response, actions.get("live_products", {}))
            response = json.dumps(normalize_bulk_response(
                parsed_response, actions.get("bulk_enquiry", {})), ensure_ascii=False)
    except (ValueError, TypeError):
        pass
    try:
        answer_text = response
        parsed = None
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and parsed.get("answer"):
                answer_text = parsed["answer"]
        except Exception:
            pass
        message_id = store.log_message(session_id, "assistant", answer_text, response_json=response)
        from langchain_core.messages import AIMessage
        redis_memory.add_message_to_user(session_id, AIMessage(content=response))
        draft = parsed.get("bulk_draft", {}) if isinstance(parsed, dict) else {}
        if draft.get("draft_id") and message_id:
            store.mark_bulk_draft_shown(session_id, draft["draft_id"], message_id)
    except Exception as log_err:
        print(f"Failed to log assistant message: {log_err}")
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
