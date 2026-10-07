"""Build one conversation from durable messages, without replaying tool calls."""
import json
from langchain_core.messages import AIMessage, HumanMessage
from product_pricing import price_number


def message_text(content):
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


def empty_product_search_response(results):
    """An empty search proves no match, never a product's release status."""
    if not results or any(result.get("tool") != "search_products" for result in results):
        return None
    queries = []
    payloads = []
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
        payloads.append(payload)
    subject = f' for "{queries[0]}"' if len(queries) == 1 else " for these preferences"
    response = {
        "answer": f"I couldn't find matching products{subject} among the catalogue records checked.",
        "products": [], "product_details": {}, "stores": [], "policy_info": {},
        "comparison": [], "recommendations": [], "order": {}, "ticket": {}, "bulk_enquiry": {},
        "end": "Would you like to try another model or change the search filters?",
    }
    if len(payloads) == 1:
        payload = payloads[0]
        filters = payload.get("price_filter") or {}
        verification = payload.get("live_verification") or {}
        if not isinstance(filters, dict) or not isinstance(verification, dict):
            return response
        ceiling = price_number(filters.get("max"))
        floor = price_number(filters.get("min"))
        def money(value):
            return "\u20b9" + (f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}")
        if ceiling is not None or floor is not None:
            limit = (f"between {money(floor)} and {money(ceiling)}" if floor is not None and ceiling is not None
                     else f"within your {money(ceiling)} budget" if ceiling is not None
                     else f"at or above {money(floor)}")
            stock = "in-stock" if verification.get("enabled") and verification.get("complete") else "matching"
            response["answer"] = f"I couldn't find {stock} products{subject} {limit} among the catalogue options checked."
            nearest = verification.get("nearest_above_budget")
            if ceiling is not None and isinstance(nearest, dict):
                price = price_number(nearest.get("selling_price"))
                if price is not None and price > ceiling:
                    response["answer"] += (f" The nearest in-stock option checked costs {money(price)}"
                                            f" ({money(round(price - ceiling, 2))} above your budget).")
            response["end"] = (f"Would you like to check another brand or a nearby store {limit}, "
                               "or would you prefer to change the budget?")
    return response


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
