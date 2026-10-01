"""Browse indexed SQL products; never fall back to the demo catalog."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

import json
from tools.product_search_tool import product_search_instance


class BrowseInput(BaseModel):
    city: str = Field("INDORE", min_length=1, max_length=100, description="Customer city for live verification")
    category: Optional[str] = Field(
        None,
        description="Category to browse, e.g. smartphone, television, laptop, ac, audio",
    )
    budget: Optional[float] = Field(
        None, description="Maximum budget in rupees, e.g. 30000"
    )


@tool("browse_catalog", args_schema=BrowseInput, return_direct=False)
def browse_catalog_tool(
    category: Optional[str] = None, budget: Optional[float] = None, city: str = "INDORE"
) -> Any:
    """
    Browse products available in the Lotus in-store catalog.

    Use this to show products when the customer wants to browse a category, or as a
    search by category. Returns real indexed products or an availability error.
    Do not use this to bypass search errors: it uses the same Pinecone index.
    """
    query = category or "electronics appliances"
    results = product_search_instance.search_products(query, top_k=6, price_max=budget, city=city)
    response = json.loads(product_search_instance.format_results(results, query, price_max=budget))
    if response.get("error"):
        return response
    products = response["products"]
    if not products:
        return {"error": "No products found in the catalog for those preferences."}
    return products
