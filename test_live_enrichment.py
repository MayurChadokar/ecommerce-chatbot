"""Offline tests for live verification without changing vectors or chat history."""
import ast
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from product_availability import availability_fields
from product_index import EMBEDDING_MODEL
from live_product_enrichment import (enrich, merge_live, collect_live_products,
                                     normalize_live_response)
with patch.dict(os.environ, {"ENABLE_VECTOR_SEARCH": "false"}):
    from tools.product_search_tool import ProductSearchTool
    from tools.Product_details import get_filtered_product_details_tool
    from tools.recommend_products import recommend_products_tool
    from tools.browse_catalog import browse_catalog_tool
    from tools.compare_products import compare_products_tool


def metadata(pid="1", price=36999):
    return {"product_id": pid, "product_name": "Samsung Double Door Refrigerator RT1",
            "brand": "Samsung", "category": "Double Door Refrigerator", "sku": "RT" + pid,
            "url": "samsung-fridge", "features": ["Capacity: 301 Litres"], "price": price,
            "price_field": "product_mrp", "product_mrp": price, "product_msrp": 50000,
            "eff_price": 30000, "source": "sql_snapshot", "embedding_model": EMBEDDING_MODEL,
            "instock": "Yes"}


def live(pid=1, price=34999, stock="Yes", city="INDORE", **extra):
    return {"product_id": str(pid), "product_name": "Samsung Double Door Refrigerator RT1",
            "product_sku": "RT" + str(pid), "product_mrp": price, "selling_price": price,
            "source": "live_api", "price_verified": price is not None,
            "checked_at": "2026-09-30T12:00:00+00:00",
            **availability_fields(stock, live=True, city=city), **extra}


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT": "true", "LOTUS_LIVE_ENRICHMENT_TIMEOUT": "2"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.search = ProductSearchTool.__new__(ProductSearchTool)
        self.search.is_available = True
        self.search.last_error = None
        self.search.settings = SimpleNamespace(namespace="existing-sql-namespace")
        self.search.index = Mock()
        self.search.model = Mock()
        self.search.model.encode.return_value.tolist.return_value = [0.1] * 384
        self.search.index.query.return_value.matches = [SimpleNamespace(id="1", score=.9, metadata=metadata())]

    def run_search(self, detail, **kwargs):
        with patch("tools.Product_details.fetch_live_details", return_value=detail) as fetch:
            results = self.search.search_products("Samsung fridge", **kwargs)
        return results, json.loads(self.search.format_results(results)), fetch

    def test_discounted_product_is_not_lost_to_snapshot_budget_filter(self):
        results, response, fetch = self.run_search(live(), price_max=35000)
        self.assertNotIn("price", self.search.index.query.call_args.kwargs["filter"])
        card = response["products"][0]
        self.assertEqual(card["selling_price"], 34999)
        self.assertEqual(card["product_mrp"], "₹34,999.00")
        self.assertTrue(card["price_verified"])
        self.assertTrue(card["stock_verified"])
        # Missing live MRP/store offer must not inherit the snapshot's values.
        for field in ("mrp", "discount_percent", "store_offer_price"):
            self.assertNotIn(field, card)
        self.search.index.upsert.assert_not_called()
        self.search.index.update.assert_not_called()
        self.search.index.delete.assert_not_called()

    def test_price_increase_and_minimum_budget_checked_against_live_price(self):
        for detail, filters in ((live(price=40000), {"price_max": 35000}),
                                (live(price=10000), {"price_min": 20000})):
            results, response, _ = self.run_search(detail, **filters)
            self.assertEqual(results, [])
            self.assertNotIn("error", response)
            self.assertTrue(response["live_verification"]["complete"])

    def test_boundary_is_inclusive(self):
        self.assertEqual(len(self.run_search(live(price=35000), price_max=35000)[0]), 1)

    def test_api_failure_hides_old_price_and_marks_stock_unknown(self):
        _, response, _ = self.run_search({"error": "unavailable"})
        card = response["products"][0]
        self.assertEqual(card["product_mrp"], "Price unavailable")
        self.assertNotIn("selling_price", card)
        self.assertEqual(card["instock"], "Unknown")
        self.assertEqual(card["snapshot_instock"], "Yes")
        self.assertFalse(card["price_verified"])
        self.assertFalse(card["stock_verified"])
        self.assertEqual(card["product_id"], "1")

    def test_api_failure_with_budget_is_not_successful_zero_matches(self):
        _, response, _ = self.run_search({"error": "unavailable"}, price_max=35000)
        self.assertEqual(response["error_code"], "price_unverified")
        self.assertEqual(response["products"], [])

    def test_identity_and_location_mismatch_fail_closed(self):
        for detail in (live(pid=2), live(product_sku="OTHER"), live(city="BHOPAL"),
                       live(source="sql_snapshot"), []):
            _, response, _ = self.run_search(detail)
            self.assertFalse(response["products"][0]["price_verified"])

    def test_city_propagates_to_api_and_card(self):
        _, response, fetch = self.run_search(live(city="BHOPAL"), city="BHOPAL")
        fetch.assert_called_once_with(1, "BHOPAL")
        self.assertEqual(response["products"][0]["stock_city"], "BHOPAL")

    def test_no_live_price_does_not_become_snapshot_price(self):
        _, response, _ = self.run_search(live(price=None))
        self.assertFalse(response["products"][0]["price_verified"])
        self.assertTrue(response["products"][0]["stock_verified"])

    def test_unknown_stock_does_not_erase_valid_live_price(self):
        _, response, _ = self.run_search(live(stock="Unknown"))
        self.assertTrue(response["products"][0]["price_verified"])
        self.assertFalse(response["products"][0]["stock_verified"])

    def test_feature_flag_off_preserves_existing_vector_filters_and_cards(self):
        with patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT": "false"}):
            _, response, fetch = self.run_search(live(), price_max=40000)
        fetch.assert_not_called()
        self.assertEqual(self.search.index.query.call_args.kwargs["filter"]["price"], {"$lte": 40000})
        self.assertEqual(response["products"][0]["selling_price"], 36999)
        self.assertNotIn("live_verification", response)
        self.assertNotIn("price_verified", response["products"][0])

    def test_budget_error_metadata_is_isolated_between_calls(self):
        failed = self.run_search({"error": "unavailable"}, price_max=35000)[0]
        self.run_search(live(), price_max=35000)
        self.assertEqual(json.loads(self.search.format_results(failed))["error_code"], "price_unverified")

    def test_deadline_does_not_wait_for_background_requests(self):
        release = threading.Event()
        def slow(*args):
            release.wait(2)
            return live()
        start = time.monotonic()
        try:
            with patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT_TIMEOUT": "0.02"}):
                result = enrich([self.search._record("1", metadata())], top_k=1, city="INDORE", fetch=slow)
            self.assertLess(time.monotonic() - start, .5)
            self.assertFalse(result[0]["price_verified"])
        finally:
            release.set()

    def test_worker_failure_and_capacity_limit_use_safe_fallback(self):
        record = self.search._record("1", metadata())
        failed = enrich([record], top_k=1, city="INDORE", fetch=Mock(side_effect=RuntimeError("private")))
        self.assertFalse(failed[0]["price_verified"])
        with patch("live_product_enrichment._slots") as slots:
            slots.acquire.return_value = False
            fetch = Mock()
            result = enrich([record], top_k=1, city="INDORE", fetch=fetch)
            fetch.assert_not_called()
            self.assertFalse(result[0]["stock_verified"])

    def test_ranking_preserved_and_candidate_count_bounded(self):
        records = [self.search._record(str(i), metadata(str(i))) for i in range(1, 30)]
        fetch = Mock(side_effect=lambda pid, city: live(pid=pid, city=city))
        result = enrich(records, top_k=5, city="INDORE", fetch=fetch)
        self.assertEqual([r["product_id"] for r in result], ["1", "2", "3", "4", "5"])
        self.assertEqual(fetch.call_count, 10)

    def test_recommendations_do_not_make_duplicate_live_calls(self):
        with patch("tools.recommend_products.product_search_instance", self.search), \
             patch("tools.Product_details.fetch_live_details", return_value=live()) as fetch, \
             patch("tools.recommend_products.fetch_live_details") as duplicate:
            result = recommend_products_tool.invoke({"category": "fridge", "in_stock_only": True, "budget": 35000})
        self.assertEqual(result[0]["selling_price"], 34999)
        fetch.assert_called_once()
        duplicate.assert_not_called()

    def test_browse_and_recommend_preserve_budget_failure(self):
        with patch("tools.browse_catalog.product_search_instance", self.search), \
             patch("tools.recommend_products.product_search_instance", self.search), \
             patch("tools.Product_details.fetch_live_details", return_value={"error": "down"}):
            for tool in (browse_catalog_tool, recommend_products_tool):
                result = tool.invoke({"category": "fridge", "budget": 35000})
                self.assertEqual(result["error_code"], "price_unverified")

    def test_comparison_uses_live_prices_instead_of_dummy_catalogue(self):
        with patch("tools.compare_products.get_filtered_product_details_tool") as details, \
             patch("catalog.get_product", side_effect=AssertionError("demo")):
            details.invoke.side_effect = [live(price=34999.50), live(pid=2, price=35999.75)]
            result = compare_products_tool.invoke({"product_ids": [1, 2], "city": "BHOPAL"})
        self.assertEqual(result["selling_price_a"], 34999.50)
        self.assertTrue(all(c.args[0]["city"] == "BHOPAL" for c in details.invoke.call_args_list))

    def test_direct_details_fallback_hides_snapshot_price(self):
        with patch("tools.Product_details.fetch_live_details", return_value={"error": "unavailable"}), \
             patch("tools.product_search_tool.product_search_instance") as search:
            search.get_product_record.return_value = self.search._record("1", metadata())
            detail = get_filtered_product_details_tool.invoke({"product_id": 1})
        self.assertFalse(detail["price_verified"])
        self.assertEqual(detail["product_mrp"], "Price unavailable")
        self.assertNotIn("selling_price", detail)

    def test_search_endpoint_city_and_unavailable_status(self):
        tree = ast.parse(Path("app.py").read_text(encoding="utf-8"))
        route = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "direct_search")
        app = Flask("live-test")
        scope = dict(app=app, request=request, jsonify=jsonify, json=json, search_tool=self.search)
        exec(compile(ast.Module(body=[route], type_ignores=[]), "app.py", "exec"), scope)
        with patch("tools.Product_details.fetch_live_details", return_value={"error": "down"}):
            response = app.test_client().post("/search", json={"query": "fridge", "city": "BHOPAL", "price_max": 35000})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["data"]["error_code"], "price_unverified")
        self.assertEqual(app.test_client().post("/search", json={"query": "fridge", "city": []}).status_code, 400)


class CardTests(unittest.TestCase):
    def test_chat_persists_verified_card_instead_of_model_price(self):
        fact = live()
        def run(message, session_id, *, actions):
            actions["live_products"] = {"1": fact}
            return json.dumps({"answer": "Product found", "products": [{"product_id": "1", "selling_price": 1}]})
        tree = ast.parse(Path("chat.py").read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "chat_with_agent")
        store, memory = Mock(), Mock()
        scope = dict(json=json, _run_agent=run, store=store, redis_memory=memory,
                     normalize_bulk_response=lambda response, actions: response)
        exec(compile(ast.Module(body=[function], type_ignores=[]), "chat.py", "exec"), scope)
        with patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT": "true"}):
            response = scope["chat_with_agent"]("price?", "test-session")
        self.assertEqual(json.loads(response)["products"], [fact])
        self.assertEqual(store.log_message.call_args.kwargs["response_json"], response)
        self.assertEqual(memory.add_message_to_user.call_args.args[1].content, response)

    def test_current_turn_cards_override_model_prices_and_exclude_old_history(self):
        fact = live()
        messages = [ToolMessage(content=json.dumps({"products": [live(price=1)]}), name="search_products", tool_call_id="old"),
                    HumanMessage(content="current price"),
                    ToolMessage(content=json.dumps({"products": [fact]}), name="search_products", tool_call_id="now"),
                    AIMessage(content="done")]
        known = collect_live_products(messages)
        rendered = normalize_live_response({"answer": "Results", "products": [{"product_id": "1", "selling_price": 1}]}, known)
        self.assertEqual(rendered["products"], [fact])
        self.assertEqual(rendered["answer"], "Results")
        self.assertEqual(collect_live_products(messages + [HumanMessage(content="next")]), {})

    def test_missing_current_verification_cannot_replay_a_price(self):
        result = normalize_live_response({"products": [live()]}, {})
        self.assertNotIn("selling_price", result["products"][0])
        self.assertFalse(result["products"][0]["stock_verified"])

    def test_malformed_tool_payload_is_ignored(self):
        messages = [ToolMessage(content="broken", name="search_products", tool_call_id="x")]
        self.assertEqual(collect_live_products(messages), {})


if __name__ == "__main__":
    unittest.main()
