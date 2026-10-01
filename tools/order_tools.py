"""Tools: place a dummy order and track an existing order.

The current chat session id is injected via `set_current_session()` (called by
chat.py before running the graph) so `place_order` can attribute the order to the
right session without the LLM needing to know it.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

import store
from tools.Product_details import fetch_live_details

# Set per-request by chat.py so place_order can tie the order to a session.
_current_session_id: Optional[str] = None


def set_current_session(session_id: Optional[str]) -> None:
    global _current_session_id
    _current_session_id = session_id


class PlaceOrderInput(BaseModel):
    product_id: int = Field(..., description="The product id the customer wants to order")
    city: str = Field("INDORE", description="Customer's city for the live stock check")


class TrackOrderInput(BaseModel):
    order_id: str = Field(
        ..., description="The order id to track, e.g. LOTUS1001 (with or without the LOTUS prefix)"
    )


@tool("place_order", args_schema=PlaceOrderInput, return_direct=False)
def place_order_tool(product_id: int, city: str = "INDORE") -> Dict[str, Any]:
    """
    Verify live stock and create a local demo order, not a real retailer purchase.

    INDIVIDUAL personal purchases only. Never use for bulk quantities, employee
    gifts or corporate/institutional procurement; collect details and use
    create_bulk_order_enquiry for those requests, even for one selected model.

    Use when the customer wants to buy/order a specific product (extract the
    product_id from previous results). Returns the new order id, status and a
    delivery timeline the customer can track later.
    """
    product = fetch_live_details(product_id, city)
    status = product.get("availability_status", "unknown")
    if product.get("error") or status == "unknown":
        return {"error": "I couldn't verify current stock, so no order was created. This does not mean the product is out of stock.",
                "error_code": "availability_unverified", "product_id": str(product_id)}
    if status == "out_of_stock":
        return {"error": f"This product is currently out of stock in {city}.",
                "error_code": "out_of_stock", "product_id": str(product_id), "stock_city": city}
    if not product.get("selling_price"):
        return {"error": "The current selling price could not be verified; no order was created.",
                "error_code": "price_unverified", "product_id": str(product_id)}
    product["product_mrp"] = f"₹{product['selling_price']:,.2f}"
    order = store.create_order(_current_session_id, product)
    if not order.get("error"):
        order["is_demo"] = True
    return order


@tool("track_order", args_schema=TrackOrderInput, return_direct=False)
def track_order_tool(order_id: str) -> Dict[str, Any]:
    """
    Track the status of an existing order by its order id (e.g. LOTUS1001).

    Returns the current status, order/delivery dates and a stage-by-stage timeline.
    """
    order = store.get_order(order_id)
    if not order:
        return {"error": f"No order found with id {order_id}. Please check the order id."}
    return order
