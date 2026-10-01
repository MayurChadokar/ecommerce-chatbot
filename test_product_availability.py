"""Offline regressions for discovery -> availability -> order consistency."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import requests
from product_availability import availability_fields, stock_status

with patch.dict(os.environ, {"ENABLE_VECTOR_SEARCH": "false"}):
    from tools.Product_details import fetch_live_details, get_filtered_product_details_tool
    from tools.product_search_tool import ProductSearchTool
    from tools.recommend_products import recommend_products_tool
    from tools.order_tools import place_order_tool
    import store


def detail(pid, stock="Yes", price=1399):
    return {"product_id": str(pid), "product_name": f"Watch {pid}",
            "product_mrp": price, "selling_price": price,
            **availability_fields(stock, live=True, city="INDORE")}


def record(pid):
    return {"product_id": str(pid), "product_name": f"Watch {pid}", "price": 1399,
            "instock": "Yes", "product_url": f"https://www.lotuselectronics.com/product/watch/{pid}"}


class LiveAvailabilityTests(unittest.TestCase):
    def test_stock_flags_and_unknown_values(self):
        for value in ("YES", "yes", True, 1, "in stock"):
            self.assertEqual(stock_status(value), "in_stock")
        for value in ("NO", False, 0, "out of stock"):
            self.assertEqual(stock_status(value), "out_of_stock")
        for value in (None, "", "Unknown", "unavailable", [], 2):
            self.assertEqual(stock_status(value), "unknown")

    @patch.dict(os.environ, {"LOTUS_AUTH_TOKEN": "test-token"})
    @patch("tools.Product_details.requests.post")
    def test_live_stock_and_city_are_preserved(self, post):
        post.return_value.json.return_value = {"data": {"product_detail": {
            **detail(29133), "product_image": [], "instock": "Yes"}}}
        result = fetch_live_details(29133, "BHOPAL")
        self.assertTrue(result["stock_verified"])
        self.assertEqual(result["stock_city"], "BHOPAL")
        self.assertEqual(result["product_image"], "")
        self.assertEqual(post.call_args.kwargs["data"]["city"], "BHOPAL")
        self.assertEqual(post.call_args.kwargs["timeout"], (3, 8))

    @patch.dict(os.environ, {"LOTUS_AUTH_TOKEN": "test-token"})
    @patch("tools.Product_details.requests.post")
    def test_auth_missing_malformed_and_wrong_product_are_not_out_of_stock(self, post):
        for payload in ({"error": "1", "data": ""}, [], {"data": {}},
                        {"data": {"product_detail": "bad"}},
                        {"data": {"product_detail": detail(40637)}}):
            with self.subTest(payload=payload):
                post.return_value.json.return_value = payload
                result = fetch_live_details(29133)
                self.assertEqual(result["error_code"], "availability_unverified")
                self.assertFalse(result["stock_verified"])

    @patch.dict(os.environ, {"LOTUS_AUTH_TOKEN": "test-token"})
    @patch("tools.Product_details.requests.post")
    def test_timeout_and_invalid_json_are_unknown(self, post):
        post.side_effect = requests.Timeout()
        self.assertEqual(fetch_live_details(29133)["instock"], "Unknown")
        post.side_effect = None
        post.return_value.json.side_effect = ValueError()
        self.assertEqual(fetch_live_details(29133)["instock"], "Unknown")

    @patch.dict(os.environ, {"LOTUS_AUTH_TOKEN": ""})
    @patch("tools.Product_details.requests.post")
    def test_missing_token_does_not_use_expired_hardcoded_token(self, post):
        self.assertEqual(fetch_live_details(29133)["error_code"], "availability_unverified")
        post.assert_not_called()

    @patch("tools.product_search_tool.product_search_instance")
    @patch("tools.Product_details.fetch_live_details")
    def test_details_fallback_uses_index_and_does_not_invent_stock(self, live, search):
        live.return_value = {"error": "Cannot verify stock", **availability_fields()}
        search.get_product_record.return_value = record(29133)
        result = get_filtered_product_details_tool.invoke({"product_id": 29133})
        self.assertEqual(result["product_name"], "Watch 29133")
        self.assertEqual(result["instock"], "Unknown")
        self.assertFalse(result["stock_verified"])

    def test_search_snapshot_yes_is_not_live_stock(self):
        search = ProductSearchTool.__new__(ProductSearchTool)
        search.last_error = None
        product = json.loads(search.format_results([record(29133)]))["products"][0]
        self.assertEqual(product["snapshot_instock"], "Yes")
        self.assertEqual(product["instock"], "Unknown")
        self.assertFalse(product["stock_verified"])


class RecommendationOrderTests(unittest.TestCase):
    @patch("tools.recommend_products.product_search_instance")
    @patch("tools.recommend_products.fetch_live_details")
    def test_available_alternatives_exclude_rejected_sold_out_unknown_and_over_budget(self, live, search):
        search.last_error = None
        search.get_product_record.return_value = record(100)
        search.search_products.return_value = [record(pid) for pid in (100, 29133, 40637, 4, 5)]
        fixtures = {29133: detail(29133, "No"), 40637: detail(40637, "Yes", 1499),
                    4: detail(4, "Unknown"), 5: detail(5, "Yes", 1600)}
        live.side_effect = lambda pid, city: fixtures[pid]
        products = recommend_products_tool.invoke({"category": "smartwatch", "budget": 1500,
                    "based_on_product_id": 100, "in_stock_only": True, "city": "BHOPAL"})
        self.assertEqual([p["product_id"] for p in products], ["40637"])
        self.assertEqual(search.search_products.call_args.kwargs["price_max"], 1500)
        self.assertTrue(all(call.args[1] == "BHOPAL" for call in live.call_args_list))

    @patch("tools.recommend_products.product_search_instance")
    @patch("tools.recommend_products.fetch_live_details")
    def test_unverified_alternatives_do_not_claim_all_products_sold_out(self, live, search):
        search.last_error = None
        search.search_products.return_value = [record(29133), record(40637)]
        live.return_value = {"error": "API unavailable", **availability_fields()}
        result = recommend_products_tool.invoke({"category": "smartwatch", "in_stock_only": True})
        self.assertEqual(result["error_code"], "availability_unverified")
        self.assertEqual(result["unverified_count"], 2)
        self.assertEqual(result["products"], [])

    @patch("tools.order_tools.store.create_order")
    @patch("tools.order_tools.fetch_live_details")
    def test_both_real_watch_ids_can_order_without_dummy_catalog(self, live, create):
        create.return_value = {"order_id": "LOTUS12345"}
        for pid in (29133, 40637):
            live.return_value = detail(pid)
            result = place_order_tool.invoke({"product_id": pid, "city": "BHOPAL"})
            self.assertEqual(result["order_id"], "LOTUS12345")
            self.assertTrue(result["is_demo"])
            self.assertEqual(create.call_args.args[1]["product_id"], str(pid))
            live.assert_called_with(pid, "BHOPAL")

    @patch("tools.order_tools.store.create_order")
    @patch("tools.order_tools.fetch_live_details")
    def test_order_rechecks_and_distinguishes_sold_out_unknown_and_missing_price(self, live, create):
        for product, code in ((detail(29133, "No"), "out_of_stock"),
                              (detail(29133, "Unknown"), "availability_unverified"),
                              (detail(29133, price=None), "price_unverified")):
            live.return_value = product
            result = place_order_tool.invoke({"product_id": 29133})
            self.assertEqual(result["error_code"], code)
            self.assertNotIn("order_id", result)
        create.assert_not_called()

    @patch("tools.recommend_products.product_search_instance")
    @patch("tools.Product_details.requests.post")
    @patch("tools.order_tools.store.create_order")
    @patch.dict(os.environ, {"LOTUS_AUTH_TOKEN": "test-token"})
    def test_recommended_watch_stock_changes_before_order(self, create, post, search):
        search.last_error = None
        search.search_products.return_value = [record(29133)]
        post.return_value.json.side_effect = [
            {"data": {"product_detail": detail(29133, "Yes")}},
            {"data": {"product_detail": detail(29133, "No")}},
        ]
        products = recommend_products_tool.invoke({"category": "smartwatch", "budget": 1500, "in_stock_only": True})
        self.assertEqual(products[0]["product_id"], "29133")
        result = place_order_tool.invoke({"product_id": 29133})
        self.assertEqual(result["error_code"], "out_of_stock")
        create.assert_not_called()

    @patch("store._connect", side_effect=RuntimeError("DB unavailable"))
    def test_database_failure_never_returns_confirmation(self, connect):
        with patch("builtins.print"):
            result = store.create_order("test", detail(29133))
        self.assertEqual(result["error_code"], "order_creation_failed")
        self.assertNotIn("order_id", result)


if __name__ == "__main__":
    unittest.main()
