"""Product retrieval from the configured Pinecone namespace, without demo fallback."""
import json
import logging
import math
import os
import re
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from product_index import EMBEDDING_MODEL, IndexSettings, connect_index, product_url
from product_pricing import pricing_fields
from product_availability import availability_fields
from live_product_enrichment import enabled as live_enabled, enrich, live_card_fields, VERIFICATION_NOTICE

logger = logging.getLogger(__name__)


class ProductSearchInput(BaseModel):
    query: str = Field(description="Product description, brand or category to search")
    top_k: int = Field(default=5, ge=1, le=20)
    price_min: Optional[float] = Field(default=None, ge=0)
    price_max: Optional[float] = Field(default=None, ge=0)
    city: str = Field(default="INDORE", min_length=1, max_length=100,
                      description="Customer city for current price/stock verification")


class ProductSearchTool:
    def __init__(self):
        self.model = self.index = self.settings = None
        self.is_available = False
        self.last_error = None
        self._initialize()

    def _initialize(self):
        if os.getenv("ENABLE_VECTOR_SEARCH", "false").lower() != "true":
            self.last_error = "Product vector search is disabled."
            return
        try:
            self.settings = IndexSettings.from_env()
            self.index, stats = connect_index(self.settings)
            namespace = stats.namespaces.get(self.settings.namespace)
            if not namespace or not namespace.vector_count:
                raise ValueError("Configured product namespace is empty; import validated products first.")
            from sentence_transformers import SentenceTransformer
            # Use a downloaded model cache in production; no implicit startup downloads.
            self.model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
            self.is_available = True
            self.last_error = None
        except ValueError as error:
            self.last_error = str(error)
            logger.warning("Product search configuration: %s", self.last_error)
        except Exception as error:
            self.last_error = "Product search could not initialize; check connection and local model cache."
            logger.warning("Product search initialization failed (%s)", type(error).__name__)

    @staticmethod
    def _record(pid, metadata, score=0.0):
        name = str(metadata.get("product_name") or "").strip()
        link = product_url(metadata.get("product_url") or metadata.get("url"), pid)
        try:
            price = float(metadata.get("price", 0))
        except (ValueError, TypeError):
            return None
        if not name or not link or not math.isfinite(price) or price <= 0:
            return None
        if (metadata.get("source") != "sql_snapshot"
                or metadata.get("embedding_model") != EMBEDDING_MODEL):
            return None
        return {
            "id": str(pid), "product_id": str(pid), "score": round(score, 4),
            "product_name": name, "price": price,
            "sku": metadata.get("sku", ""), "url": metadata.get("url", ""),
            "product_url": link, "image_url": metadata.get("image_url", ""),
            "description": metadata.get("text", ""), "features": metadata.get("features", []),
            "brand": metadata.get("brand", ""), "category": metadata.get("category", ""),
            "instock": metadata.get("instock", "Unknown"), "source": "sql_snapshot",
            **pricing_fields(metadata),
        }

    @staticmethod
    def _apply_query_intent_filter(records, query):
        """Keep iPhone searches limited to actual iPhone products.

        Vector similarity alone groups Apple accessories, iPads and other phones
        with iPhone requests. A requested generation (for example, "iPhone 17")
        must also occur in the product title; otherwise report no match instead
        of substituting a different model.
        """
        normalized_query = str(query or "").lower()
        if "iphone" not in normalized_query:
            return records

        iphone_records = [
            record for record in records
            if "iphone" in str(record.get("product_name", "")).lower()
        ]
        # Catalogue titles include "iPhone Mobile 18 Pro" as well as the
        # customer's usual "iPhone 18 Pro" spelling. Match their model identity
        # rather than requiring those words to be adjacent in the title.
        model_pattern = r"\biphone\s*(?:mobile\s+)?(\d{1,2})(?:\s*(pro\s+max|pro|plus|mini|air|e))?\b"
        requested = re.search(model_pattern, normalized_query)
        if requested:
            def matches_model(record):
                model = re.search(model_pattern, str(record.get("product_name", "")).lower())
                return bool(model and model.group(1) == requested.group(1)
                            and (not requested.group(2)
                                 or re.sub(r"\s+", " ", model.group(2) or "")
                                 == re.sub(r"\s+", " ", requested.group(2))))

            iphone_records = [
                record for record in iphone_records
                if matches_model(record)
            ]
        return iphone_records

    def get_product_record(self, product_id):
        if not self.is_available:
            return None
        self.last_error = None
        try:
            result = self.index.fetch(ids=[str(product_id)], namespace=self.settings.namespace)
            item = result.vectors.get(str(product_id))
            return self._record(product_id, item.metadata or {}) if item else None
        except Exception as error:
            self.last_error = "Product lookup is temporarily unavailable."
            logger.warning("Product lookup failed (%s)", type(error).__name__)
            return None

    def search_products(self, query, top_k=5, price_min=None, price_max=None, city="INDORE"):
        if not self.is_available:
            return []
        if not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        for price in (price_min, price_max):
            if price is not None and (not math.isfinite(float(price)) or float(price) < 0):
                raise ValueError("Price filters must be finite and non-negative")
        if price_min is not None and price_max is not None and price_min > price_max:
            raise ValueError("Minimum price must not exceed maximum price")
        self.last_error = None
        try:
            filters = {"source": {"$eq": "sql_snapshot"},
                       "embedding_model": {"$eq": EMBEDDING_MODEL}}
            price_filter = {}
            if price_min is not None:
                price_filter["$gte"] = float(price_min)
            if price_max is not None:
                price_filter["$lte"] = float(price_max)
            verify_live = live_enabled()
            if price_filter and not verify_live:
                filters["price"] = price_filter
            vector = self.model.encode(query, normalize_embeddings=True).tolist()
            # Fetch a wider candidate set before applying strict intent filters.
            # The final public result remains limited to the requested top_k.
            response = self.index.query(vector=vector, namespace=self.settings.namespace,
                                        top_k=max(top_k, 20), include_metadata=True, filter=filters)
            results = []
            for match in response.matches:
                record = self._record(match.id, match.metadata or {}, match.score)
                if record:
                    results.append(record)
            results = self._apply_query_intent_filter(results, query)
            if verify_live:
                return enrich(results, top_k=top_k, city=city,
                              price_min=price_min, price_max=price_max)
            return results[:top_k]
        except Exception as error:
            self.last_error = "Product search is temporarily unavailable. Please try again later."
            logger.warning("Product query failed (%s)", type(error).__name__)
            return []

    def format_results(self, results, query="", top_k=5, price_min=None, price_max=None):
        products = [{
            "product_id": r["product_id"], "product_name": r["product_name"],
            "product_mrp": f"₹{r['price']:,.0f}" if r.get("price") is not None else "Price unavailable", "product_url": r["product_url"],
            "product_image": r.get("image_url", ""),
            "features": r.get("features", [])[:4],
            "snapshot_instock": r.get("instock", "Unknown"),
            **availability_fields(),
            "source": "sql_snapshot",
            **pricing_fields(r),
            **live_card_fields(r),
        } for r in results]
        response = {
            "search_query": query, "total_found": len(products), "products": products,
            "price_filter": {"min": price_min, "max": price_max},
            "source": "pinecone_sql_snapshot",
            "search_metadata": {"top_k_requested": top_k, "no_results": not products},
        }
        if self.last_error:
            response["error"] = self.last_error
            response["error_code"] = "product_search_unavailable"
        if hasattr(results, "verification"):
            response["source"] = "pinecone_with_live_verification"
            response["live_verification"] = results.verification
            if any(p.get("catalogue_fallback") for p in products):
                response["verification_notice"] = dict(VERIFICATION_NOTICE)
            if results.verification_error:
                response["error"] = results.verification_error
                response["error_code"] = "price_unverified"
        return json.dumps(response, ensure_ascii=False)


product_search_instance = ProductSearchTool()


@tool("search_products", args_schema=ProductSearchInput, return_direct=False)
def search_products(query: str, top_k: int = 5, price_min: Optional[float] = None,
                    price_max: Optional[float] = None, city: str = "INDORE") -> str:
    """Search real indexed products by description and budget. Never returns demo products.
    If unavailable, explain the error; do not invent products, prices or links.
    With live verification enabled, respect price_verified/stock_verified and city.
    Otherwise prices and stock are from an imported snapshot, not guaranteed live inventory.
    """
    results = product_search_instance.search_products(query, top_k, price_min, price_max, city=city)
    return product_search_instance.format_results(results, query, top_k, price_min, price_max)


__all__ = ["search_products", "ProductSearchTool", "ProductSearchInput"]
