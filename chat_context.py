"""Build one conversation from durable messages, without replaying tool calls."""
import json
from langchain_core.messages import AIMessage, HumanMessage


def message_text(content):
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


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
