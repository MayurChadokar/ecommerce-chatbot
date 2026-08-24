# Flask Integration for Lotus Electronics Chatbot

This document explains how to integrate the Lotus Electronics chatbot with Flask web applications.

## 🚀 Quick Start

### 1. Start the Flask App
```bash
python start_flask.py
```

This will:
- Check all dependencies
- Verify Redis connection
- Test the chat function
- Start Flask on port 9000

### 2. Access the Chatbot
- **Web Interface**: http://localhost:9000
- **API Endpoint**: POST http://localhost:9000/chat
- **Health Check**: GET http://localhost:9000/health

## 📡 API Usage

### Chat Endpoint
**POST** `/chat`

**Request:**
```json
{
  "message": "I need Samsung ACs under 50000",
  "session_id": "unique_user_session"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "answer": "Great! I found excellent Samsung ACs from Lotus Electronics...",
    "products": [
      {
        "product_name": "Samsung 1.5 Ton Split AC",
        "product_mrp": "₹45,000",
        "product_url": "https://www.lotuselectronics.com/product/...",
        "product_image": "https://image-url.jpg",
        "features": ["Energy Efficient", "Fast Cooling", "Smart Control", "5 Star Rating"]
      }
    ],
    "end": "Would you like more details about any of these ACs?"
  }
}
```

### Health Check
**GET** `/health`

**Response:**
```json
{
  "status": "healthy",
  "service": "Lotus Electronics Chatbot",
  "redis": "connected",
  "active_users": 5
}
```

## 🔧 Integration Function

### `chat_with_agent(message, session_id)`

The core function that powers the Flask integration:

```python
from chat import chat_with_agent

# Basic usage
response = chat_with_agent("Show me gaming laptops", "user_123")
print(response)  # Returns JSON string
```

**Parameters:**
- `message` (str): User's message
- `session_id` (str): Unique identifier for conversation memory

**Returns:**
- JSON string with `answer`, optional `products`, and optional `end` fields

## 🧪 Testing

### Test Flask Integration
```bash
python test_flask_integration.py
```

### Test Individual Functions
```python
from chat import chat_with_agent
import json

response = chat_with_agent("Hello from Lotus Electronics", "test_session")
data = json.loads(response)
print(data)
```

## 🔒 Error Handling

The Flask integration includes comprehensive error handling:

1. **Redis Connection Errors**: Automatic fallback responses
2. **JSON Parsing Errors**: Wrapped in proper JSON format  
3. **Tool Execution Errors**: Graceful error messages
4. **Network Timeouts**: Proper HTTP status codes

## 🌐 Production Deployment

### Environment Variables
```bash
export GOOGLE_API_KEY="your-gemini-api-key"
export PINECONE_API_KEY="your-pinecone-key"
export REDIS_HOST="your-redis-host"
export PORT=8080
```

### Docker Deployment
```dockerfile
FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["python", "app.py"]
```

### CORS Configuration
For cross-origin requests, add to `app.py`:
```python
from flask_cors import CORS
CORS(app, origins=["https://your-domain.com"])
```

## 📊 Session Management

- Each `session_id` maintains separate conversation history
- Redis TTL of 30 minutes for automatic cleanup
- Up to 50 messages per session stored
- Context window of 15 messages for AI processing

## 🛡️ Security Considerations

1. **Input Validation**: Messages limited to 500 characters
2. **Rate Limiting**: Consider implementing rate limits for production
3. **Session Validation**: Validate session IDs in production
4. **API Keys**: Use environment variables, never hardcode

## 🔍 Monitoring

### Health Check Endpoint
Monitor your deployment with:
```bash
curl http://localhost:9000/health
```

### Redis Monitoring
```bash
redis-cli info memory
redis-cli keys "user_messages:*"
```

## 🐛 Troubleshooting

### Common Issues

1. **Redis Connection Failed**
   ```bash
   docker run -d -p 6379:6379 redis:alpine
   ```

2. **Import Errors**
   ```bash
   pip install -r requirements.txt
   ```

3. **Pinecone API Errors**
   - Check API key validity
   - Verify index name and host

4. **JSON Parse Errors**
   - Function automatically wraps non-JSON responses
   - Check system prompt configuration

### Debug Mode
Enable Flask debug mode:
```python
app.run(host="0.0.0.0", port=port, debug=True)
```

## 🚀 Example Integration

```python
from flask import Flask, request, jsonify
from chat import chat_with_agent
import json

app = Flask(__name__)

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message")
    session = data.get("session", "default")
    
    try:
        response = chat_with_agent(message, session)
        return jsonify(json.loads(response))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run()
```

Your Flask integration is now ready for production use! 🎉
