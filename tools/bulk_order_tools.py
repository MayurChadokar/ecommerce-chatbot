"""Model-selected corporate/bulk quotation requests, separate from demo orders.

No keyword classifier: intent and clarification are handled by the model. The
tool validates confirmed customer data and commits a request for admin review.
"""
import re
import html
import json
from typing import Annotated, Literal, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

import store

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Requirement = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class BulkEnquiryDetails(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    product_requirement: Requirement = Field(description="Selected product/model or customer's exact product requirements. Never invent a selection.")
    quantity: int = Field(ge=2, le=100000, strict=True, description="Confirmed number of units, explicitly supplied by customer.")
    contact_name: Name = Field(description="Customer's contact name, explicitly supplied.")
    phone: str = Field(description="Customer-provided Indian mobile number for this enquiry.")
    city: Name = Field(description="Customer-provided delivery city; do not default to Indore.")
    purpose: Requirement = Field(description="Customer's intended use, e.g. employee Diwali gifts or office equipment.")
    product_id: Optional[int] = Field(default=None, gt=0, description="Known selected product ID from tool results; omit for an unselected product requirement.")
    company_name: Optional[Name] = Field(default=None, description="Company/organisation if supplied. Ask once; omit when not applicable or declined.")
    budget_per_unit: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False, description="Customer budget per unit in INR, not a quoted price.")
    required_by: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]] = Field(default=None, description="Customer's requested delivery date/deadline, verbatim. Not a delivery promise; omit if undecided.")
    email: Optional[str] = Field(default=None, max_length=254, description="Customer email, or null if declined/not available.")
    pincode: Optional[str] = Field(default=None, pattern=r"^[1-9]\d{5}$", description="Delivery PIN code, or null if undecided/declined.")
    gst_requirement: Optional[str] = Field(default=None, max_length=120, description="Customer's GST invoice requirement, verbatim, or null if undecided/declined. Do not request GSTIN yet.")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        compact = re.sub(r"[\s()-]", "", value)
        match = re.fullmatch(r"(?:\+91|91|0)?([6-9]\d{9})", compact)
        if match is None:
            raise ValueError("Ask for a valid 10-digit Indian mobile number, optionally prefixed with +91.")
        return match.group(1)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Ask for a valid email or allow the customer to skip it.")
        return value


class BulkEnquiryInput(BulkEnquiryDetails):
    confirmed: Literal[True] = Field(description="True only after customer approves the displayed prepared summary.")
    confirmation_message: str = Field(description="Exact current customer message approving the displayed summary, copied verbatim.")


class BulkPreparationInput(BulkEnquiryDetails):
    customer_evidence: dict[str, str] = Field(description=(
        "For EVERY detail except product_id, provide a verbatim quote from a CUSTOMER message supporting it. "
        "Optional null fields also require a customer quote declining/deferring that question. "
        "Never cite assistant/tool messages or invent a quote. Keep names, city, purpose and dates in the customer's own words."
    ))


FIELD_LABELS = {
    "product_requirement": "Product / requirement", "quantity": "Quantity", "contact_name": "Contact name",
    "phone": "Mobile number", "city": "Delivery city", "purpose": "Purpose",
    "company_name": "Company / organisation", "budget_per_unit": "Budget per unit (INR)",
    "required_by": "Requested delivery date", "email": "Email", "pincode": "Delivery PIN code",
    "gst_requirement": "GST invoice requirement",
}


def _canonical(value):
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip().casefold()


def _supports_value(key, value, quote):
    if key in ("quantity", "budget_per_unit"):
        numbers = re.findall(r"(?<!\w)\d+(?:,\d{2,3})*(?:\.\d+)?(?!\w)", quote)
        return float(value) in [float(n.replace(",", "")) for n in numbers]
    if key in ("phone", "pincode"):
        return str(value) in re.sub(r"\D", "", quote)
    return _canonical(value) in quote


def _evidence_errors(details, evidence, messages):
    """Validate provenance, not intent: only customer statements can supply data."""
    customers = [_canonical(m["message"]) for m in messages if m["role"] == "user"]
    errors = []
    for key in FIELD_LABELS:
        quote = _canonical(evidence.get(key, ""))
        value = details.get(key)
        # A copied evidence quote may be malformed even though the value is
        # explicitly present in the real conversation. Recover that provenance
        # from customer messages instead of re-asking an already supplied fact.
        if value is not None and any(_supports_value(key, value, message) for message in customers):
            continue
        if not quote or not any(quote in message for message in customers):
            errors.append(key)
            continue
        if value is None:  # The model interprets an actual customer's decline/deferral.
            continue
        supported = _supports_value(key, value, quote)
        if not supported:
            errors.append(key)
    return errors


@tool("prepare_bulk_order_enquiry", args_schema=BulkPreparationInput)
def prepare_bulk_order_enquiry(config: RunnableConfig, **kwargs) -> dict:
    """Validate customer-supplied bulk details and prepare a review summary, NOT a saved enquiry.

    First ask missing details, 1-2 questions at a time. Ask company, budget, date,
    email, PIN and GST requirement once; allow the customer to skip these. Preserve
    that exact skip reply as evidence. Call this only when all questions are answered.
    Then display the returned summary and wait for a NEW customer confirmation turn.
    Never fill example/default names, quantities, phones or cities. Multiple tool
    calls in one turn cannot approve a summary. For quantities written in words,
    ask the customer to confirm the numeric quantity before preparation.
    """
    sid = config.get("configurable", {}).get("thread_id")
    if not sid or sid == "default_session":
        return {"error": "A unique chat session is needed.", "error_code": "bulk_session_required"}
    validated = BulkPreparationInput(**kwargs)
    details = validated.model_dump(exclude={"customer_evidence"})
    try:
        missing = _evidence_errors(details, validated.customer_evidence, store.get_chat_logs(sid))
        if missing:
            labels = ", ".join(FIELD_LABELS[k] for k in missing[:2])
            return {"error": f"Please share your {labels}. Your enquiry has not been submitted.",
                    "missing_fields": missing, "error_code": "bulk_customer_details_required"}
        return store.save_bulk_draft(sid, details)
    except Exception:
        return {"error": "The enquiry summary could not be prepared. Please try again.", "error_code": "bulk_draft_failed"}


@tool("create_bulk_order_enquiry", args_schema=BulkEnquiryInput)
def create_bulk_order_enquiry(
    product_requirement: str, quantity: int, contact_name: str, phone: str,
    city: str, purpose: str, confirmed: bool, config: RunnableConfig,
    confirmation_message: str,
    product_id: Optional[int] = None, company_name: Optional[str] = None,
    budget_per_unit: Optional[float] = None, required_by: Optional[str] = None,
    email: Optional[str] = None, pincode: Optional[str] = None, gst_requirement: Optional[str] = None,
) -> dict:
    """Save a CONFIRMED bulk/corporate quotation enquiry, never a purchase.

    Use for multiple-unit purchases, employee/staff/client gifts, corporate or
    institutional procurement and team equipment. First help select products,
    collect required details and call prepare_bulk_order_enquiry. That prepared
    summary must have been displayed on a PREVIOUS turn. Only then accept explicit
    approval in a new customer message. All details must match the prepared draft.
    If the customer changes anything, prepare a fresh summary and wait again.
    Never use place_order for this intent. Do not call for gift ideas alone,
    incomplete information, or before the customer confirms the summary.
    Returns a BULK reference after durable save, with quotation pending. It does
    not reserve stock, take payment, contact staff or promise discounts/delivery.
    """
    session_id = config.get("configurable", {}).get("thread_id")
    if not session_id or session_id == "default_session":
        return {"error": "A unique chat session is needed to save this enquiry. Please start a new chat.",
                "error_code": "bulk_session_required"}
    details = BulkEnquiryInput(
        product_requirement=product_requirement, quantity=quantity, contact_name=contact_name,
        phone=phone, city=city, purpose=purpose, confirmed=confirmed,
        product_id=product_id, company_name=company_name, budget_per_unit=budget_per_unit,
        required_by=required_by,
        email=email, pincode=pincode, gst_requirement=gst_requirement,
        confirmation_message=confirmation_message,
    ).model_dump(exclude={"confirmed", "confirmation_message"})
    try:
        draft = store.get_bulk_draft(str(session_id))
        messages = store.get_chat_logs(str(session_id))
        latest = messages[-1] if messages else {}
        assistants = [m for m in messages if m["role"] == "assistant"]
        valid_review = (draft.get("shown_message_id") and assistants
                        and assistants[-1]["id"] == draft["shown_message_id"]
                        and latest.get("role") == "user"
                        and latest["id"] > draft["shown_message_id"]
                        and _canonical(confirmation_message) == _canonical(latest["message"])
                        and details == draft["details"])
        if not valid_review:
            return {"error": "Please provide the missing enquiry details first. A complete summary must be reviewed and approved before submission.",
                    "error_code": "bulk_review_required"}
    except Exception:
        return {"error": "Your bulk enquiry could not be verified or saved. Please try again.",
                "error_code": "bulk_enquiry_save_failed"}
    return store.create_bulk_enquiry(str(session_id), details)


def _validation_question(error):
    fields = list(dict.fromkeys(item['loc'][0] for item in error.errors()))
    return json.dumps({
        "error": "Enquiry not submitted: the tool arguments could not be validated.",
        "error_code": "bulk_arguments_invalid", "invalid_argument_fields": fields,
        "guidance": "These are tool argument errors, not proof that customer details are missing. "
                    "Read the actual customer history. In the end field ask 1-2 genuinely unanswered questions. "
                    "Never repeat supplied product, quantity, name, phone or city. Do not call another tool this turn.",
    })


create_bulk_order_enquiry.handle_validation_error = _validation_question
prepare_bulk_order_enquiry.handle_validation_error = _validation_question


def normalize_bulk_response(response: dict, result: dict) -> dict:
    """Render only the authoritative result from this turn, never model-made IDs."""
    response["bulk_enquiry"] = {}
    response["bulk_draft"] = {}
    if result.get("enquiry_id"):
        response["bulk_enquiry"] = result
        response["order"] = {}
        response["ticket"] = {}
        response["answer"] = (f"Your bulk quotation enquiry {result['enquiry_id']} has been saved. "
                              "Status: Quotation pending. Pricing, stock and delivery await confirmation. No purchase has been placed.")
        response["end"] = ""
    elif result.get("draft_id"):
        lines = ["Please review your bulk quotation enquiry:"]
        lines.extend(f"{label}: {html.escape(str(result['details'].get(key) if result['details'].get(key) is not None else 'Not supplied / deferred'))}"
                     for key, label in FIELD_LABELS.items())
        lines.append("This is a quotation request; pricing, stock and delivery are not confirmed.")
        response.update(answer="<br>".join(lines), bulk_draft=result, order={}, ticket={},
                        end="Are these details correct, and may I submit this enquiry? Please confirm or tell me what to change.")
    elif result.get("error_code") == "bulk_arguments_invalid":
        # Never turn a malformed evidence map into a request to repeat quantity
        # or city. The response-only model sees the transcript and asks the next
        # real question; action success text is replaced deterministically.
        question = response.get("end")
        response.update(answer="Your enquiry has not been submitted yet.", order={}, ticket={},
                        end=question if isinstance(question, str) and question.strip() else
                        "Please confirm the remaining enquiry details so I can prepare your review summary.")
    elif result.get("error"):
        response.update(answer=result["error"], order={}, ticket={},
                        end="")
    return response
