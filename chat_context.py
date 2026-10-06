"""Build one conversation from durable messages, without replaying tool calls."""
import json
from langchain_core.messages import AIMessage, HumanMessage


def message_text(content):
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


def empty_product_search_response(results):
    """An empty search proves no match, never a product's release status."""
    if not results or any(result.get("tool") != "search_products" for result in results):
        return None
    queries = []
    for result in results:
        try:
            payload = json.loads(result["result"])
        except (KeyError, TypeError, ValueError):
            return None
        if (not isinstance(payload, dict) or payload.get("error")
                or payload.get("error_code") or payload.get("products") != []):
            return None
        if payload.get("search_query"):
            queries.append(str(payload["search_query"]))
    subject = f' for "{queries[0]}"' if len(queries) == 1 else " for these preferences"
    return {
        "answer": f"I couldn't find matching products{subject} among the catalogue records checked.",
        "products": [], "product_details": {}, "stores": [], "policy_info": {},
        "comparison": [], "recommendations": [], "order": {}, "ticket": {}, "bulk_enquiry": {},
        "end": "Would you like to try another model or change the search filters?",
    }


def build_chat_context(rows, cached_messages=()):
    # Recover structured cards from the old Redis cache for pre-migration rows.
    # A cached response must match the assistant text actually logged to SQLite.
    legacy = {}
    for message in cached_messages:
        if getattr(message, "type", None) != "ai" or getattr(message, "tool_calls", None):
            continue
        content = message_text(message.content)
        try:
            data = json.loads(content)
            if isinstance(data, dict) and isinstance(data.get("answer"), str):
                legacy[data["answer"]] = content
        except (TypeError, ValueError):
            continue
    output = []
    for row in rows:
        role = row["role"]
        if role == "user":
            output.append(HumanMessage(content=row["message"], id=f"chat-{row['id']}"))
        elif role == "assistant":
            content = row.get("response_json") or legacy.get(row["message"]) or row["message"]
            output.append(AIMessage(content=content, id=f"chat-{row['id']}"))
    return output
