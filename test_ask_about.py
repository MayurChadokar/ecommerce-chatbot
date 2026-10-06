"""Selected-product chat checks without loading the model or external services."""
import ast
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request
from product_availability import availability_fields


def load_function(filename, name, scope):
    tree = ast.parse(Path(filename).read_text(encoding="utf-8"))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, "exec"), scope)
    return scope[name]


def live_detail(stock="Yes", city="BHOPAL"):
    return {
        "product_id": "41237", "product_name": "Samsung F17 5G",
        "source": "live_api", "mrp": 30999, "product_msrp": 30999,
        "selling_price": 25999, "product_mrp": 25999, "price_verified": True,
        "price_source": "live_api", "checked_at": "2026-10-06T12:00:00+00:00",
        "product_url": "https://www.lotuselectronics.com/product/smartphones/samsung-f17/41237",
        "product_specification": [{"fkey": f"Feature {i}", "fvalue": f"Value {i}"} for i in range(19)],
        **availability_fields(stock, live=True, city=city),
    }


class SelectedProductTests(unittest.TestCase):
    def setUp(self):
        self.store, self.memory, self.tool, self.agent = Mock(), Mock(), Mock(), Mock()
        self.scope = dict(json=json, store=self.store, redis_memory=self.memory,
                          get_filtered_product_details_tool=self.tool, _run_agent=self.agent,
                          normalize_bulk_response=lambda response, actions: response)
        self.chat = load_function("chat.py", "chat_with_agent", self.scope)
        self.env = patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def selected_response(self, detail):
        self.tool.invoke.return_value = detail
        response = self.chat("Show me details", "fresh-session", product_id=41237, city="BHOPAL")
        return json.loads(response)

    def test_selection_preserves_complete_live_facts_and_logs_both_roles(self):
        detail = live_detail()
        response = self.selected_response(detail)
        self.assertEqual(response["product_details"], detail)
        self.tool.invoke.assert_called_once_with({"product_id": 41237, "city": "BHOPAL"})
        self.agent.assert_not_called()
        self.assertEqual([call.args[1] for call in self.store.log_message.call_args_list], ["user", "assistant"])
        saved = json.loads(self.store.log_message.call_args.kwargs["response_json"])
        self.assertEqual(saved["product_details"], detail)
        self.assertEqual([call.args[1].type for call in self.memory.add_message_to_user.call_args_list], ["human", "ai"])

    def test_stock_no_remains_visible_on_explicit_detail_request(self):
        response = self.selected_response(live_detail(stock="No"))
        self.assertEqual(response["product_details"]["availability_status"], "out_of_stock")
        self.assertEqual(response["product_details"]["mrp"], 30999)

    def test_logging_failure_does_not_drop_product_fields(self):
        self.store.log_message.side_effect = RuntimeError("storage unavailable")
        self.assertEqual(self.selected_response(live_detail())["product_details"], live_detail())
        self.agent.assert_not_called()

    def test_redis_failure_does_not_drop_product_fields_or_sqlite_history(self):
        self.memory.add_message_to_user.side_effect = RuntimeError("Redis disconnected")
        self.assertEqual(self.selected_response(live_detail())["product_details"], live_detail())
        self.assertEqual([call.args[1] for call in self.store.log_message.call_args_list], ["user", "assistant"])
        self.agent.assert_not_called()

    def test_live_selection_works_when_search_enrichment_flag_is_disabled(self):
        with patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT": "false"}):
            self.assertEqual(self.selected_response(live_detail())["product_details"], live_detail())

    def test_unverified_snapshot_price_is_never_presented_as_current(self):
        snapshot = {"product_id": "41237", "product_name": "Indexed Samsung F17",
                    "source": "sql_snapshot", "product_mrp": 27000, "instock": "Yes",
                    "product_url": live_detail()["product_url"], "product_specification": live_detail()["product_specification"]}
        with patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT": "false"}):
            response = self.selected_response(snapshot)
        detail = response["product_details"]
        self.assertEqual(detail["catalogue_price"], 27000)
        self.assertFalse(detail["price_verified"])
        self.assertEqual(detail["instock"], "Unknown")
        self.assertEqual(detail["stock_city"], "BHOPAL")
        self.assertNotIn("selling_price", detail)
        self.assertIn("verification_notice", response)

    def test_already_normalized_fallback_keeps_last_known_price_and_specs(self):
        from live_product_enrichment import merge_live, live_card_fields
        snapshot = {"product_id": "41237", "product_name": "Indexed Samsung F17",
                    "source": "sql_snapshot", "product_mrp": 27000,
                    "product_specification": live_detail()["product_specification"]}
        fallback = merge_live(snapshot, None, "BHOPAL")
        fallback.update(live_card_fields(fallback))
        result = self.selected_response(fallback)["product_details"]
        self.assertEqual(result["catalogue_price"], 27000)
        self.assertEqual(len(result["product_specification"]), 19)

    def test_failed_or_mismatched_lookup_never_returns_invented_details(self):
        for detail in ({"error": "unverified"}, {}, {**live_detail(), "product_id": "999"}):
            with self.subTest(detail=detail):
                response = self.selected_response(detail)
                self.assertEqual(response["product_details"], {})
                self.assertIn("could not be retrieved", response["answer"])
        self.tool.invoke.side_effect = RuntimeError("provider unavailable")
        self.assertEqual(json.loads(self.chat("details", product_id=41237))["product_details"], {})
        self.agent.assert_not_called()

    def test_regular_chat_keeps_existing_agent_behavior(self):
        self.agent.return_value = json.dumps({"answer": "Hello", "products": []})
        self.assertEqual(json.loads(self.chat("Hi", "regular"))["answer"], "Hello")
        self.agent.assert_called_once_with("Hi", "regular", actions={})
        self.tool.invoke.assert_not_called()


class ChatRouteTests(unittest.TestCase):
    def setUp(self):
        self.agent = Mock(return_value=json.dumps({"answer": "Details"}))
        self.app = Flask("ask-about-route")
        load_function("app.py", "chat", dict(app=self.app, request=request, jsonify=jsonify,
                                            json=json, chat_with_agent=self.agent))
        self.client = self.app.test_client()

    def test_selected_product_id_and_city_reach_detail_handler(self):
        response = self.client.post("/chat", json={"message": "details", "session_id": "fresh",
                                                  "product_id": "41237", "city": " bhopal "})
        self.assertEqual(response.status_code, 200)
        self.agent.assert_called_once_with("details", "fresh", product_id=41237, city="BHOPAL")

    def test_selection_defaults_to_indore_and_normal_messages_have_no_selection(self):
        self.client.post("/chat", json={"message": "details", "product_id": 41237})
        self.agent.assert_called_with("details", "default_session", product_id=41237, city="INDORE")
        self.client.post("/chat", json={"message": "Hi"})
        self.agent.assert_called_with("Hi", "default_session")

    def test_invalid_selection_is_rejected_before_model_or_api_call(self):
        for product_id in (None, True, 0, -1, 1.5, "1.5", [], {}, "", "١", "9" * 20):
            with self.subTest(product_id=product_id):
                response = self.client.post("/chat", json={"message": "details", "product_id": product_id})
                self.assertEqual(response.status_code, 400)
        for city in (None, [], "", "   ", "x" * 101):
            with self.subTest(city=city):
                self.assertEqual(self.client.post("/chat", json={"message": "details", "product_id": 41237, "city": city}).status_code, 400)
        self.agent.assert_not_called()

    def test_non_object_request_is_rejected(self):
        self.assertEqual(self.client.post("/chat", json=[]).status_code, 400)
        self.agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
