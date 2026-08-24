# app.py

import os
from functools import wraps
from dotenv import load_dotenv
from flask import (
    Flask, request, jsonify, render_template, send_from_directory,
    session, redirect, url_for,
)

load_dotenv()

# from agenticai_lotus import  LotusElectronicsBot
# from try_agentic import chat_with_agent

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET", "lotus-dev-secret-change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# SQLite store for chat logs, sessions and orders
import store
store.init_db()
store.seed_orders()
# allow all origins; adjust in production as needed


def admin_required(view):
    """Gate admin API/pages behind a simple session login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            if request.path.startswith("/admin/api"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("admin"))
        return view(*args, **kwargs)
    return wrapped

@app.route("/static")
def serve_static(path):
    return send_from_directory("static", path)

@app.route("/", methods=["GET"])
def index():
    # Renders templates/chatbot.html
    return render_template("chat.html")

from chat import chat_with_agent, redis_memory
from tools.product_search_tool import ProductSearchTool
import json

# Initialize the product search tool
search_tool = ProductSearchTool()

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    try:
        # Redis is optional; FallbackMemory has no redis_client attribute
        redis_status = "disconnected"
        if hasattr(redis_memory, "test_connection") and redis_memory.test_connection():
            redis_status = "connected"

        # Check search tool availability
        pinecone_status = "connected" if search_tool.is_available else "disconnected"

        return jsonify({
            "status": "healthy",
            "service": "Lotus Electronics Chatbot",
            "redis": redis_status,
            "search_methods": {
                "pinecone_vector": pinecone_status
            },
            "active_users": len(redis_memory.get_active_users())
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 500



@app.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json(force=True)
    message = payload.get("message")
    session_id = payload.get("session_id", "default_session")
    
    if not message:
        return jsonify({"error": "Missing 'message' in request"}), 400

    try:
        ai_reply = chat_with_agent(message, session_id)
        data = json.loads(ai_reply)
        
        response = {
            "status": "success",
            "data": data
        }
        return jsonify(response)
    except json.JSONDecodeError as e:
        app.logger.error(f"JSON decode error: {e}")
        return jsonify({"error": "Invalid JSON response from agent"}), 500
    except Exception as e:
        app.logger.exception("Error in chat_with_agent")
        return jsonify({"error": str(e)}), 500

@app.route("/search", methods=["POST"])
def direct_search():
    """Direct product search endpoint using hybrid search"""
    payload = request.get_json(force=True)
    query = payload.get("query")
    top_k = payload.get("top_k", 5)
    price_min = payload.get("price_min")
    price_max = payload.get("price_max")
    
    if not query:
        return jsonify({"error": "Missing 'query' in request"}), 400
    
    try:
        # Use the hybrid search directly
        results = search_tool.search_products(
            query=query,
            top_k=min(top_k, 20),  # Limit to 20 max
            price_min=price_min,
            price_max=price_max
        )
        
        # Format results for response
        formatted_response = search_tool.format_results(results)
        data = json.loads(formatted_response)
        
        response = {
            "status": "success",
            "search_method": "hybrid",
            "query": query,
            "total_results": len(results),
            "data": data
        }
        return jsonify(response)
        
    except Exception as e:
        app.logger.exception("Error in direct_search")
        return jsonify({
            "status": "error",
            "error": str(e),
            "data": {
                "answer": "I'm sorry, I couldn't search for products at the moment. Please try again later.",
                "end": "Is there anything else I can help you with?"
            }
        }), 500

@app.route("/search/api", methods=["POST"])
def api_search_only():
    """Direct API search endpoint for testing real-time data"""
    payload = request.get_json(force=True)
    query = payload.get("query")
    limit = payload.get("limit", 10)
    
    if not query:
        return jsonify({"error": "Missing 'query' in request"}), 400
    
    try:
        # Use only API search
        results = search_tool.search_products_api(query, limit)
        
        if not results:
            return jsonify({
                "status": "no_results",
                "query": query,
                "message": "No products found or API unavailable"
            })
        
        response = {
            "status": "success",
            "search_method": "api_only",
            "query": query,
            "total_results": len(results),
            "results": results
        }
        return jsonify(response)
        
    except Exception as e:
        app.logger.exception("Error in api_search_only")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500



# ----------------------------------------------------------------------------- #
# Admin portal
# ----------------------------------------------------------------------------- #
@app.route("/admin", methods=["GET"])
def admin():
    """Render the admin dashboard (or the login screen if not authenticated)."""
    return render_template("admin.html", logged_in=bool(session.get("is_admin")))


@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = (request.form.get("password") or "").strip()
    if password == ADMIN_PASSWORD:
        session["is_admin"] = True
        return redirect(url_for("admin"))
    return render_template("admin.html", logged_in=False, error="Incorrect password")


@app.route("/admin/logout", methods=["GET"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin"))


@app.route("/admin/api/stats", methods=["GET"])
@admin_required
def admin_stats():
    return jsonify(store.get_stats())


@app.route("/admin/api/sessions", methods=["GET"])
@admin_required
def admin_sessions():
    return jsonify(store.get_sessions())


@app.route("/admin/api/sessions/<session_id>", methods=["GET"])
@admin_required
def admin_session_detail(session_id):
    return jsonify({
        "session_id": session_id,
        "messages": store.get_chat_logs(session_id),
    })


@app.route("/admin/api/orders", methods=["GET"])
@admin_required
def admin_orders():
    return jsonify(store.get_orders())


@app.route("/admin/api/tickets", methods=["GET"])
@admin_required
def admin_tickets():
    return jsonify(store.get_tickets())


if __name__ == "__main__":
    # Load PORT from env or default to 8001
    port = int(os.environ.get("PORT", 8001))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
