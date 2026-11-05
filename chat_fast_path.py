"""Deterministic low-latency handling for common budget recommendations."""

import json
import re
from dataclasses import dataclass
from typing import Iterable, Optional

_AMOUNT = r"(?:\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)\s*(?:k|thousand|lakh|lac)?"


def fast_replacement_policy(message):
    """Answer replacement-policy questions from verified local policy text."""
    if not isinstance(message, str):
        return None
    text = message.strip()
    if not re.search(r"\b(?:replacement|replace|replaced)\b", text, re.I):
        return None

    answer = (
        "Lotus Electronics asks customers to check the product and accessories when accepting delivery. "
        "A replacement may be requested for a short shipment or defective product, subject to product availability, "
        "and only for products sold by Lotus Electronics. Contact Lotus customer service promptly to report the issue "
        "and confirm whether the product qualifies for replacement. "
        "A product may be ineligible if it has physical damage, is missing its original packaging or accessories, "
        "has a missing or altered serial number, or has had its UPC removed. Final replacement approval remains with "
        "Lotus Electronics. Official policies: https://www.lotuselectronics.com/return-policy and "
        "https://www.lotuselectronics.com/terms-condition"
    )
    return {
        "answer": answer,
        "products": [], "product_details": {}, "stores": [], "policy_info": {},
        "comparison": [], "recommendations": [], "ticket": {}, "bulk_enquiry": {},
        "end": "For confirmation, contact Lotus customer service at 0731 4265577 or customerservices@lotuselectronics.com.",
    }


def fast_return_policy(message):
    """Answer return/refund-policy questions without quoting disputed deadlines."""
    if not isinstance(message, str):
        return None
    text = message.strip()
    if not re.search(r"\b(?:return|refund)\b", text, re.I):
        return None

    answer = (
        "Lotus Electronics may accept an unopened product in its original packaging with the original invoice. "
        "Shipping costs are not refunded and return transportation charges may be deducted. If a returned product "
        "is found used or tampered with, Lotus may deduct charges based on its condition. Approved refunds are made "
        "through the original payment method or the applicable Lotus account or wallet. Eligibility and final approval "
        "remain with Lotus Electronics. Official policy: https://www.lotuselectronics.com/return-policy"
    )
    return {
        "answer": answer,
        "products": [], "product_details": {}, "stores": [], "policy_info": {},
        "comparison": [], "recommendations": [], "ticket": {}, "bulk_enquiry": {},
        "end": "For confirmation, contact Lotus customer service at 0731 4265577 or customerservices@lotuselectronics.com.",
    }


def fast_unclear_message(message):
    """Catch obvious keyboard noise without language models or dictionary guesses."""
    if not isinstance(message, str) or not message.strip():
        return None
    text = message.strip()
    noise = not any(char.isalnum() for char in text)
    # Inspect Latin words even when they are mixed with Hindi or another script.
    # Product model codes containing digits are excluded from the ratio so a
    # legitimate query such as "Samsung S24 price" is not rejected.
    if not noise:
        words = re.findall(r"(?<![a-z0-9])[a-z]+(?![a-z0-9])", text.lower())
        # Common abbreviations and Roman Hindi must not count as keyboard noise.
        allowed = set("lg tv hp bpl tcl tcl qled oled led lcd hdr hdmi usb ssd hdd ram gb tb "
                      "ac pc cpu gpu ups jbl dth emi mrp gst rs pls plz thx hmm hm hn "
                      "h m kr krr pr b hi ji bhi nhi nh yr kya kyu bhai haan hai na "
                      "aur se ko ka ki ke me main mera chahiye batao dikhao".split())
        suspicious = [word for word in words if len(word) >= 2
                      and word not in allowed
                      and (not re.search(r"[aeiou]", word)
                           or re.search(r"[^aeiou]{4,}", word)
                           or (len(word) >= 5
                               and len(re.findall(r"[aeiou]", word)) / len(word) <= .2))]
        letters = sum(map(len, words))
        noise = (letters >= 8 and len(suspicious) >= 2
                 and sum(map(len, suspicious)) / letters >= 0.65)
    if not noise:
        return None
    has_hindi = bool(re.search(r"[\u0900-\u097f]", text))
    answer = (
        "आपका संदेश स्पष्ट नहीं है। कृपया प्रोडक्ट या सहायता से जुड़ा अपना सवाल थोड़ा विस्तार से लिखें।"
        if has_hindi else
        "Your message was not clear. Please describe your product or support question in a little more detail."
    )
    return {
        "answer": answer,
        "products": [], "product_details": {}, "stores": [], "policy_info": {},
        "comparison": [], "recommendations": [], "ticket": {}, "bulk_enquiry": {},
        "end": "",
    }
_CATEGORIES = {
    "smartphone": ("smartphone", "smartphones", "smart phone", "mobile", "mobiles", "phone", "phones"),
    "laptop": ("laptop", "laptops", "notebook", "notebooks"),
    "television": ("television", "televisions", "tv", "tvs"),
    "refrigerator": ("refrigerator", "refrigerators", "fridge", "fridges"),
    "washing machine": ("washing machine", "washing machines", "washer", "washers"),
    "air conditioner": ("air conditioner", "air conditioners", "ac", "acs"),
}
_RECOMMENDATION = re.compile(
    r"\b(?:recommend|suggest|suggestion|best options?|options?|dikhao|batao)\b", re.I)
_PORTABLE_AC = re.compile(r"\bportable\s+(?:ac|air\s*conditioners?)\b", re.I)


@dataclass(frozen=True)
class BudgetRange:
    minimum: Optional[float]
    maximum: Optional[float]
    label: str


def _number(value: str) -> float:
    compact = value.lower().replace(",", "").replace(" ", "")
    multiplier = 1
    for suffix, factor in (("thousand", 1_000), ("lakh", 100_000),
                           ("lac", 100_000), ("k", 1_000)):
        if compact.endswith(suffix):
            compact, multiplier = compact[:-len(suffix)], factor
            break
    return float(compact) * multiplier


def parse_budget_range(text: str) -> Optional[BudgetRange]:
    money = rf"(?:\u20b9|rs\.?|inr)?\s*({_AMOUNT})"
    between = re.search(
        rf"\b(?:between|from)\s+{money}\s+(?:to|and|se)\s+{money}", text, re.I)
    if between:
        low, high = sorted((_number(between.group(1)), _number(between.group(2))))
        return BudgetRange(low, high, f"\u20b9{low:,.0f}\u2013\u20b9{high:,.0f}")
    around = re.search(
        rf"\b(?:around|about|approx(?:imately)?|near)\s+{money}", text, re.I)
    if around:
        centre = _number(around.group(1))
        low, high = round(centre * .9), round(centre * 1.1)
        label = f"around \u20b9{centre:,.0f} (\u20b9{low:,.0f}\u2013\u20b9{high:,.0f})"
        return BudgetRange(low, high, label)
    upper = re.search(
        rf"\b(?:under|below|upto|up\s+to|within|budget(?:\s+of)?)\s+{money}", text, re.I)
    if upper:
        value = _number(upper.group(1))
        return BudgetRange(None, value, f"up to \u20b9{value:,.0f}")
    return None


def _category(texts: Iterable[str]) -> Optional[str]:
    for text in texts:
        normalized = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
        for category, aliases in _CATEGORIES.items():
            if any(f" {alias} " in normalized for alias in aliases):
                return category
    return None


def fast_budget_recommendation(message: str, previous_user_messages=(), city="INDORE"):
    if not isinstance(message, str) or not _RECOMMENDATION.search(message):
        return None
    budget = parse_budget_range(message)
    category = _category([message, *reversed(list(previous_user_messages)[-6:])])
    if budget is None or category is None:
        return None

    from tools.product_search_tool import product_search_instance
    results = product_search_instance.search_products(
        query=f"best {category}", top_k=5, price_min=budget.minimum,
        price_max=budget.maximum, city=city, category=category)
    payload = json.loads(product_search_instance.format_results(
        results, query=f"best {category}", top_k=5,
        price_min=budget.minimum, price_max=budget.maximum))
    products = payload.get("products", [])
    base = {
        "products": [], "product_details": {}, "stores": [], "policy_info": {},
        "comparison": [], "recommendations": products, "ticket": {},
        "bulk_enquiry": {},
    }
    if payload.get("error"):
        return {**base,
                "answer": f"I couldn't complete the {category} catalogue check for {budget.label} right now.",
                "end": "Please try again in a moment."}
    if products:
        return {**base,
                "answer": f"Here are the best matching {category} options {budget.label} from the catalogue.",
                "end": "Want me to compare any two of these?"}
    return {**base,
            "answer": f"I checked the catalogue for {category} options {budget.label}, but found no matches among the products checked.",
            "end": "Would you like to keep this range and try another brand, or change the budget?"}


def fast_portable_ac_alternatives(message: str, city="INDORE"):
    """Ground an unavailable Portable AC request and show labelled AC alternatives."""
    if not isinstance(message, str) or not _PORTABLE_AC.search(message):
        return None
    from tools.product_search_tool import product_search_instance
    results = product_search_instance.search_products(
        query="wall mounted split ac", top_k=6, city=city)
    payload = json.loads(product_search_instance.format_results(
        results, query="wall mounted split ac", top_k=6))
    alternatives = payload.get("products", [])
    base = {
        "products": [], "product_details": {}, "stores": [], "policy_info": {},
        "comparison": [], "recommendations": alternatives, "ticket": {},
        "bulk_enquiry": {},
    }
    if payload.get("error"):
        return {**base,
                "answer": "I couldn't verify Portable AC availability in the catalogue right now.",
                "end": "Please try again shortly or check with a Lotus store."}
    if alternatives:
        return {**base,
                "answer": ("I checked the catalogue and found no Portable AC products in the current indexed range. "
                           "These are Wall Mounted Split AC alternatives; they are not Portable AC units."),
                "end": "Would you like details or a comparison of any of these alternatives?"}
    return {**base,
            "answer": "I checked the catalogue and found no Portable AC products or matching AC alternatives in the current indexed range.",
            "end": "You can check with a Lotus store for availability outside the online catalogue."}


__all__ = ["BudgetRange", "fast_unclear_message", "fast_replacement_policy", "fast_return_policy",
           "parse_budget_range", "fast_budget_recommendation",
           "fast_portable_ac_alternatives"]
