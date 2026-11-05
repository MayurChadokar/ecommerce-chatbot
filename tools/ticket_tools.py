"""Tool: raise a support ticket for a customer.

Collects name, phone and the issue, saves the ticket to SQLite, and returns a
confirmation the customer can reference. The current chat session is supplied by
the request-local session context.
"""

from typing import Any, Dict
import re

from pydantic import BaseModel, Field, field_validator
from langchain_core.tools import tool

import store
from tools.session_context import get_current_session
from tools.ticket_email import queue_ticket_email


class RaiseTicketInput(BaseModel):
    name: str = Field(..., description="The customer's name")
    phone: str = Field(..., description="The customer's phone number")
    issue: str = Field(..., description="A short description of the problem or query")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = " ".join(str(value).split())
        if len(value) < 2 or value.casefold() in {"not provided", "unknown", "customer", "user"}:
            raise ValueError("Please provide the customer's name")
        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        digits = re.sub(r"\D", "", str(value))
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) != 10 or digits[0] not in "6789":
            raise ValueError("Please provide a valid 10-digit Indian mobile number")
        return digits

    @field_validator("issue")
    @classmethod
    def validate_issue(cls, value):
        value = " ".join(str(value).split())
        placeholders = {"general support", "general support or inquiry", "inquiry",
                        "issue", "product issue", "issue with product", "support"}
        if len(value) < 8 or value.casefold() in placeholders:
            raise ValueError("Please describe the specific issue")
        return value


@tool("raise_ticket", args_schema=RaiseTicketInput, return_direct=False)
def raise_ticket_tool(name: str, phone: str, issue: str) -> Dict[str, Any]:
    """
    Raise a support ticket for the customer.

    Only call this AFTER you have collected the customer's name, phone number, and a
    short description of their issue. Returns the created ticket (with a ticket id)
    which you should confirm to the customer.
    """
    if not name or not phone or not issue:
        return {"error": "I still need the name, phone number and a short description of the issue."}

    ticket = store.create_ticket(get_current_session(), name, phone, issue)
    if not ticket.get("error") and ticket.get("ticket_id"):
        queue_ticket_email(ticket)
    return ticket


def normalize_ticket_response(response: dict, ticket: dict, current_message: str = "") -> dict:
    """Expose only a successfully saved ticket from this exact chat turn."""
    model_ticket = response.pop("ticket", None)
    if ticket.get("ticket_id") and not ticket.get("error"):
        response["ticket"] = ticket
        response["answer"] = (f"Your support ticket {ticket['ticket_id']} has been raised successfully. "
                              "The support team has been notified by email.")
        response["end"] = "Is there anything else I can help you with?"
        return response

    asks_for_ticket = bool(re.search(r"\b(?:raise|create|open|need|want)\b.*\bticket\b|\bticket\b.*\b(?:raise|create|open)\b",
                                     current_message, re.I))
    claimed_success = bool(re.search(r"\b(?:successfully|raised|created|ticket\s+id)\b",
                                     str(response.get("answer", "")), re.I))
    if asks_for_ticket and (model_ticket or claimed_success):
        response["answer"] = ("I can raise a support ticket after collecting the required details. "
                              "Please share your name, 10-digit mobile number, and a clear description of the issue.")
        response["end"] = "What name, mobile number, and issue should I use for the ticket?"
    return response
