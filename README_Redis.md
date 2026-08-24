# Lotus Electronics Official Chatbot

Welcome to the official Lotus Electronics chatbot - your AI-powered assistant for finding the perfect electronics products with advanced Redis memory management and AI-powered product search using Pinecone vector database.

## 🏪 Brand Identity

This chatbot officially represents **Lotus Electronics** - a leading electronics retailer in India. It provides:
- Professional customer service experience
- Electronics product recommendations
- Price-based filtering and search
- Detailed product information with features

## 🔧 Core Features

### 🧠 **Advanced Memory Management**
- **Multi-user support**: Each customer gets isolated conversation history
- **Persistent memory**: Conversations stored in Redis with 30-minute TTL
- **Context awareness**: Maintains conversation flow across sessions
- **Auto-cleanup**: Prevents memory overflow with smart message management

### 🛍️ **AI-Powered Product Search**
- **Semantic Search**: Natural language queries like "Samsung AC under 50000"
- **Price Filtering**: Filter by minimum and maximum price ranges
- **Rich Product Data**: Name, price, features, images, and direct links
- **Vector Database**: Lightning-fast search powered by Pinecone

### 📋 **Structured JSON Response Format**
All responses follow this exact format:
```json
{
  "answer": "Natural language response from Lotus Electronics assistant",
  "products": [
    {
      "product_name": "Product Name",
      "product_mrp": "₹Price",
      "product_url": "Direct product page URL",
      "product_image": "Product image URL", 
      "features": ["Feature 1", "Feature 2", "Feature 3", "Feature 4"]
    }
  ],
  "end": "Follow-up question to continue conversation"
}
```

### 🌤️ **Additional Services**  
- Weather forecasts for any location and date
- Location-based services using geolocation

## 🚀 Quick Start

### 1. **Complete Setup**
```bash
python setup_complete.py
```

### 2. **Test Configuration**
```bash  
python test_chatbot.py
```

### 3. **Run Lotus Electronics Chatbot**
```bash
python chat.py
```

## Usage

1. **Start the application**: Run `python chat.py`
2. **User identification**: 
   - Enter an existing user ID to continue previous conversation
   - Press Enter to create a new user ID
3. **Chat commands**:
   - Type your message normally
   - `stats` - Show user statistics
   - `clear` - Clear conversation history
   - `quit`/`exit`/`bye` - Exit application

## Redis Memory Configuration

You can customize the Redis memory settings by modifying the `RedisMemory` initialization:

```python
redis_memory = RedisMemory(
    redis_host='localhost',    # Redis server host
    redis_port=6379,          # Redis server port  
    redis_db=0,               # Redis database number
    ttl_seconds=1800          # Conversation expiry time (30 minutes)
)
```

## Memory Management

- **TTL (Time To Live)**: Conversations automatically expire after 30 minutes
- **Message limit**: Only last 50 messages per user are stored
- **Context window**: AI uses last 20 messages for generating responses
- **Multiple users**: Each user ID gets isolated conversation history

## Troubleshooting

1. **Redis connection error**: Make sure Redis server is running on localhost:6379
2. **Memory issues**: Check Redis memory usage with `redis-cli info memory`
3. **Permission errors**: Ensure Redis has write permissions

## Redis CLI Commands

Useful Redis commands for debugging:
```bash
# Connect to Redis CLI
redis-cli

# List all user keys
KEYS user_messages:*

# Get user conversation
GET user_messages:your_user_id

# Delete user conversation  
DEL user_messages:your_user_id

# Check TTL of a key
TTL user_messages:your_user_id
```
