"""Recommend products from the configured Pinecone SQL-product namespace."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

import json
from concurrent.futures import ThreadPoolExecutor
from tools.product_search_tool import product_search_instance
from tools.Product_details import fetch_live_details
from live_product_enrichment import enabled as live_enabled, LiveResults


class RecommendInput(BaseModel):
    in_stock_only: bool = Field(False, description="True when asking for available/in-stock alternatives")
    city: str = Field("INDORE", description="Customer's city for live stock checks")
    category: Optional[str] = Field(
        None,
        description="Product category to recommend from, e.g. smartphone, television, "
        "laptop, ac, audio",
    )
    budget: Optional[float] = Field(
        None, description="Maximum budget in rupees, e.g. 20000"
    )
    based_on_product_id: Optional[int] = Field(
        None,
        description="Recommend products similar to this product id (from previous results)",
    )


@tool("recommend_products", args_schema=RecommendInput, return_direct=False)
def recommend_products_tool(
    category: Optional[str] = None,
    budget: Optional[float] = None,
    based_on_product_id: Optional[int] = None,
    in_stock_only: bool = False,
    city: str = "INDORE",
) -> Any:
    """
    Recommend suitable products to the customer.

    Use when the user asks for suggestions, alternatives, "what else", "recommend
    me...", or "something similar". Provide a category and/or budget, or a
    based_on_product_id to find similar items. Returns a list of recommended
    product objects. Set in_stock_only=True for 'available', 'aviable', 'avaivle',
    or in-stock alternatives; this verifies live city-specific stock.
    """
    query = category or "electronics appliances"
    if based_on_product_id is not None:
        base = product_search_instance.get_product_record(based_on_product_id)
        if not base:
            return {"error": product_search_instance.last_error or "Original indexed product not found."}
        query = f"{category or base.get('category', '')} {base['product_name']}"
    results = product_search_instance.search_products(query, top_k=20 if in_stock_only else 6, price_max=budget, city=city)
    if based_on_product_id is not None:
        filtered = [r for r in results if r["product_id"] != str(based_on_product_id)]
        results = LiveResults(filtered, results.verification, results.verification_error) if isinstance(results, LiveResults) else filtered
    if live_enabled():
        response = json.loads(product_search_instance.format_results(results, query, price_max=budget))
        if response.get("error"):
            return response
        products = response["products"]
        if in_stock_only:
            products = [p for p in products if p.get("stock_verified") and p.get("availability_status") == "in_stock"]
        if products:
            return products[:5]
        unknown = response.get("live_verification", {}).get("stock_unverified_count", 0)
        return {"products": [], "error_code": "availability_unverified" if unknown else "no_verified_matches",
                "error": "Live availability could not be verified." if unknown else "No matching products among the candidates checked.",
                "live_verification": response.get("live_verification", {})}
    if in_stock_only:
        if product_search_instance.last_error:
            return {"error": product_search_instance.last_error, "error_code": "product_search_unavailable"}
        # Check a bounded candidate set concurrently, preserving search ranking.
        candidates = results[:12]
        with ThreadPoolExecutor(max_workers=4) as executor:
            details = list(executor.map(lambda r: fetch_live_details(int(r["product_id"]), city), candidates))
        verified = []
        unknown = 0
        for record, detail in zip(candidates, details):
            if detail.get("error") or detail.get("availability_status") == "unknown":
                unknown += 1
                continue
            if detail.get("availability_status") != "in_stock":
                continue
            price = detail.get("selling_price")
            if budget is not None and (price is None or price > budget):
                continue
            verified.append({**detail, "product_url": record["product_url"],
                             "features": record.get("features", [])})
        if verified:
            return verified[:5]
        return {
            "products": [],
            "error_code": "availability_unverified" if unknown else "no_verified_matches",
            "error": ("Live stock could not be verified for some matching products. Do not claim they are out of stock."
                      if unknown else "No matching in-stock products within the budget were found among the products checked."),
            "checked_count": len(candidates), "unverified_count": unknown, "stock_city": city,
        }
    response = json.loads(product_search_instance.format_results(results[:5], query, price_max=budget))
    if response.get("error"):
        return response
    recs = response["products"]
    if not recs:
        return {"error": "No matching products found for those preferences."}
    return recs
