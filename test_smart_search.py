"""Offline checks: no provider, catalogue writes, chat history or actions."""
import ast
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from flask import Flask
from live_product_enrichment import enrich
from product_availability import availability_fields
from product_index import EMBEDDING_MODEL
from smart_search import (SmartSearch, SearchUnavailable, Interpretation,
                          AIInterpretation, ai_interpret, deterministic, provider_schema, interpretation_prompt)
from search_taxonomy import category_families
from smart_search_api import create_smart_search_blueprint
with patch.dict(os.environ, {"ENABLE_VECTOR_SEARCH": "false"}):
    from tools.product_search_tool import ProductSearchTool


TAXONOMY = {"namespace": "test", "version": "v1", "brands": ["Samsung", "Voltas", "Voltas Beko", "LG"],
            "categories": ["Double Door Refrigerator", "Single Door Refrigerator", "Gaming Laptop", "Windows Laptop"]}


def match(pid="1", brand="Samsung", sku="RT1", name="Samsung 5 Star Double Door Refrigerator RT1"):
    return SimpleNamespace(id=pid, score=.9, metadata={"product_name": name,
        "brand": brand, "category": "Double Door Refrigerator", "sku": sku,
        "url": "samsung-fridge", "price": 99999, "product_mrp": 99999,
        "features": ["Capacity: 301 Litres", "Inverter Compressor"],
        "source": "sql_snapshot", "embedding_model": EMBEDDING_MODEL})


def detail(pid, city="INDORE", price=39999):
    return {"product_id": str(pid), "product_sku": "", "selling_price": price,
            "source": "live_api", **availability_fields("Yes", live=True, city=city)}


class SmartTests(unittest.TestCase):
    def test_selected_category_filters_and_cannot_be_overridden(self):
        intent = Interpretation(brands=["Samsung"], categories=[], price_min=None,
                                price_max=None, model="", attributes=[], preferences=[])
        with patch.object(self.search, "interpret", return_value=(intent, "samsung", [], None, "ai")):
            result = self.search.search("Samsung", category="Double Door Refrigerator")
        self.assertEqual(result["appliedFilters"]["categories"], ["Double Door Refrigerator"])
        self.assertEqual(self.catalogue.index.query.call_args.kwargs["filter"]["category"],
                         {"$in": ["Double Door Refrigerator"]})
        self.assertEqual(len(result["products"]), 1)
        self.assertEqual(intent.categories, [])

    def test_category_all_preserves_normal_search(self):
        intent = Interpretation(brands=[], categories=[], price_min=None,
                                price_max=None, model="", attributes=[], preferences=[])
        with patch.object(self.search, "interpret", return_value=(intent, "electronics", [], None, "ai")):
            self.search.search("electronics", category="all")
        self.assertNotIn("category", self.catalogue.index.query.call_args.kwargs["filter"])

    def test_unknown_or_conflicting_category_clarifies_without_querying_index(self):
        for query, category in [("Samsung", "Imaginary category"),
                                ("gaming laptop", "Double Door Refrigerator")]:
            result = self.search.search(query, category=category)
            self.assertTrue(result["clarificationRequired"])
            self.assertEqual(result["products"], [])
        self.catalogue.index.query.assert_not_called()

    def test_broad_category_maps_to_catalogue_group(self):
        intent = Interpretation(brands=[], categories=[], price_min=None,
                                price_max=None, model="", attributes=[], preferences=[])
        with patch.object(self.search, "interpret", return_value=(intent, "fridge", [], None, "ai")):
            result = self.search.search("fridge", category="Refrigerator")
        self.assertEqual(result["appliedFilters"]["categories"],
                         ["Double Door Refrigerator", "Single Door Refrigerator"])

    def setUp(self):
        self.catalogue = ProductSearchTool.__new__(ProductSearchTool)
        self.catalogue.is_available = True
        self.catalogue.settings = SimpleNamespace(namespace="test")
        self.catalogue.index = Mock()
        self.catalogue.index.query.return_value = SimpleNamespace(matches=[match()])
        self.catalogue.model = Mock()
        self.catalogue.model.encode.return_value.tolist.return_value = [.1] * 384
        self.catalogue.last_error = "Other request error must not leak"
        self.ai = Mock()
        self.fetch = Mock(side_effect=detail)
        self.verifier = lambda records, **kwargs: enrich(records, fetch=self.fetch, **kwargs)
        self.search = SmartSearch(self.catalogue, self.ai, TAXONOMY, self.verifier)

    def test_hinglish_amounts(self):
        for q, expected in [("40k", 40000), ("40 hazar", 40000), ("1 lakh", 100000),
                            ("1.5 lakh", 150000), ("40 हजार", 40000)]:
            with self.subTest(q=q):
                intent, _, _ = deterministic("Samsung fridge " + q + " ke andar", TAXONOMY)
                self.assertEqual(intent.price_max, expected)
                self.assertFalse(intent.attributes)

    def test_typo_keeps_strict_brand_and_category(self):
        self.catalogue.index.query.return_value.matches = []
        self.ai.with_structured_output.return_value.invoke.return_value = AIInterpretation(
            brands=["Voltas"], categories=["Double Door Refrigerator", "Single Door Refrigerator"],
            price_min=None, price_max=None, model="", attributes=[], preferences=[],
            resolutions=[{"source": "voltus", "kind": "brand", "values": ["Voltas"]},
                         {"source": "refregistor", "kind": "category", "values": ["Double Door Refrigerator", "Single Door Refrigerator"]}]).model_dump()
        result = self.search.search("voltus refregistor")
        filters = self.catalogue.index.query.call_args.kwargs["filter"]
        self.assertEqual(filters["brand"], {"$in": ["Voltas"]})
        self.assertIn("Double Door Refrigerator", filters["category"]["$in"])
        self.assertEqual(result["products"], [])
        self.assertEqual(result["searchMode"], "smart")
        self.ai.with_structured_output.assert_called_once()

    def test_related_brand_not_substituted(self):
        intent, _, _ = deterministic("Voltas Beko fridge", TAXONOMY)
        self.assertEqual(intent.brands, ["Voltas Beko"])

    def configure_laptops(self):
        categories = ["Convertible Laptop", "Gaming Laptop", "Laptops",
                      "MacBook Laptop", "Thin & Light Laptop", "Windows Laptop"]
        self.search.taxonomy = {**TAXONOMY, "brands": [*TAXONOMY["brands"], "Asus", "HP"],
                                "categories": [*categories, "Double Door Refrigerator"]}
        matches = []
        for index, category in enumerate(categories, 1):
            record = match(str(index), brand="Asus", name="Asus " + category)
            record.metadata["category"] = category
            matches.append(record)
        self.catalogue.index.query.return_value.matches = matches
        self.ai.with_structured_output.return_value.invoke.return_value = AIInterpretation(
            brands=[], categories=categories, price_min=None, price_max=None,
            model="", attributes=[], preferences=[], resolutions=[]).model_dump()
        return categories

    def test_plural_laptops_uses_the_ai_family_selection(self):
        categories = self.configure_laptops()
        result = self.search.search("laptops", page_size=6)
        self.assertEqual(result["appliedFilters"]["categories"], categories)
        self.assertEqual({p["category"] for p in result["products"]}, set(categories))
        self.assertEqual(result["interpretationSource"], "ai")
        self.ai.with_structured_output.assert_called_once()
        # A recognized product category should not cause an extra SKU lookup.
        self.catalogue.index.query.assert_called_once()

    def test_ambiguous_source_label_is_repaired_by_ai_not_expanded_in_code(self):
        categories = self.configure_laptops()
        invoke = self.ai.with_structured_output.return_value.invoke
        valid = invoke.return_value
        invoke.side_effect = [{**valid, "categories": ["Laptops"]}, valid]
        result = self.search.search("laptops", page_size=6)
        self.assertEqual(result["appliedFilters"]["categories"], categories)
        self.assertEqual(result["interpretationSource"], "ai")
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("omits sibling categories", invoke.call_args.args[0][0].content)

    def test_repeated_ambiguous_ai_label_is_not_reported_as_smart(self):
        self.configure_laptops()
        self.ai.with_structured_output.return_value.invoke.return_value["categories"] = ["Laptops"]
        result = self.search.search("laptops", page_size=6)
        self.assertEqual(result["fallbackReason"], "invalid_ai_output")
        self.assertEqual(result["interpretationSource"], "keyword")

    def test_laptops_timeout_fallback_returns_the_full_family(self):
        categories = self.configure_laptops()
        self.ai.with_structured_output.return_value.invoke.side_effect = TimeoutError()
        result = self.search.search("laptops", page_size=6)
        self.assertEqual(result["fallbackReason"], "ai_timeout")
        self.assertEqual(result["appliedFilters"]["categories"], categories)
        self.assertEqual(len(result["products"]), 6)

    def test_explicit_laptop_subtype_stays_narrow(self):
        self.configure_laptops()
        self.ai.with_structured_output.return_value.invoke.return_value["categories"] = ["Gaming Laptop"]
        result = self.search.search("gaming laptop", page_size=6)
        self.assertEqual(result["appliedFilters"]["categories"], ["Gaming Laptop"])
        self.assertEqual([p["category"] for p in result["products"]], ["Gaming Laptop"])

    def test_selected_exact_laptops_category_stays_narrow(self):
        self.configure_laptops()
        result = self.search.search("laptops", category="Laptops", page_size=6)
        self.assertEqual(result["appliedFilters"]["categories"], ["Laptops"])
        self.assertEqual([p["category"] for p in result["products"]], ["Laptops"])

    def test_broad_laptop_request_cannot_infer_the_narrow_category_brand(self):
        self.configure_laptops()
        self.search.taxonomy["brandCategories"] = {"Asus": ["Laptops"], "HP": ["Windows Laptop"]}
        self.ai.with_structured_output.return_value.invoke.return_value["brands"] = ["Asus"]
        result = self.search.search("laptops", page_size=6)
        self.assertEqual(result["fallbackReason"], "invalid_ai_output")
        self.assertEqual(result["appliedFilters"]["brands"], [])
        self.assertEqual(len(result["products"]), 6)

    def test_even_simple_mobile_queries_go_through_llm(self):
        categories = ["Android Smartphone", "iPhone Mobile", "Feature Mobile Phone", "Mobile Accessories"]
        self.search.taxonomy = {**TAXONOMY, "categories": categories}
        phone = match(name="Samsung Android Smartphone A55")
        phone.metadata.update(category="Android Smartphone")
        self.catalogue.index.query.return_value.matches = [phone]
        self.fetch.side_effect = lambda pid, city: detail(pid, city, 34999)
        for term in ("mobile", "mobiles", "mobile phone", "mobile phones", "phones", "मोबाइल"):
            with self.subTest(term=term):
                self.ai.with_structured_output.return_value.invoke.return_value = AIInterpretation(
                    brands=[], categories=categories[:3], price_min=None, price_max=35000.0, model="",
                    attributes=[], preferences=[], resolutions=[]).model_dump()
                result = self.search.search(term + " under 35000")
                self.assertEqual(len(result["products"]), 1)
                self.assertEqual(result["appliedFilters"]["attributes"], [])
                self.assertEqual(result["appliedFilters"]["price_max"], 35000)
                self.assertNotIn("Mobile Accessories", result["appliedFilters"]["categories"])
                self.assertNotIn("fallbackReason", result)
                self.assertEqual(result["interpretationSource"], "ai")
        self.assertEqual(self.ai.with_structured_output.call_count, 6)

    def test_current_price_budget_not_snapshot_price(self):
        result = self.search.search("Samsung double door fridge under 40k")
        self.assertEqual(result["products"][0]["selling_price"], 39999)
        self.assertNotIn("price", self.catalogue.index.query.call_args.kwargs["filter"])
        self.assertEqual(result["products"][0]["brand"], "Samsung")

    def test_strict_budget_excludes_even_one_rupee_over(self):
        self.fetch.side_effect = lambda pid, city: detail(pid, city, 40001)
        result = self.search.search("Samsung fridge under 40k")
        self.assertEqual(result["products"], [])
        self.assertTrue(result["verification"]["complete"])

    def test_boundary_budget_included(self):
        self.fetch.side_effect = lambda pid, city: detail(pid, city, 40000)
        self.assertEqual(len(self.search.search("fridge under 40k")["products"]), 1)

    def test_snapshot_budget_only_ranks_does_not_exclude(self):
        expensive, affordable = match("1"), match("2")
        affordable.metadata.update(price=30000, product_mrp=30000)
        self.catalogue.index.query.return_value.matches = [expensive, affordable]
        first = self.search.search("Samsung fridge under 40k", page_size=1)
        self.assertEqual(first["products"][0]["product_id"], "2")
        second = self.search.search("Samsung fridge under 40k", page=2, page_size=1)
        self.assertEqual(second["products"][0]["product_id"], "1")

    def test_invalid_schema_falls_back_with_literal_spec(self):
        self.ai.with_structured_output.return_value.invoke.return_value = {"sql": "DROP TABLE products"}
        result = self.search.search("Samsung 5 star fridge under 40k")
        self.assertEqual(result["searchMode"], "keyword")
        self.assertEqual(result["fallbackReason"], "invalid_ai_output")
        self.assertEqual(len(result["products"]), 1)
        self.catalogue.index.upsert.assert_not_called()

    def test_valid_ai_cannot_drop_literal_attribute(self):
        self.ai.with_structured_output.return_value.invoke.return_value = Interpretation(
            brands=["Samsung"], categories=["Double Door Refrigerator"], price_min=None,
            price_max=None, model="", attributes=[], preferences=[]).model_dump()
        self.assertEqual(self.search.search("Samsung red fridge")["products"], [])

    def test_timeout_fallback_is_bounded(self):
        def slow(_, **kwargs):
            time.sleep(.15)
            return {}
        self.ai.with_structured_output.return_value.invoke.side_effect = slow
        with patch.dict(os.environ, {"SMART_SEARCH_AI_TIMEOUT": ".01"}):
            started = time.monotonic()
            result = self.search.search("Samsung 5 star fridge")
        self.assertLess(time.monotonic() - started, .14)
        self.assertEqual(result["fallbackReason"], "ai_timeout")

    def test_provider_failure_fallback(self):
        self.ai.with_structured_output.return_value.invoke.side_effect = RuntimeError("secret not returned")
        result = self.search.search("Samsung 5 star fridge")
        self.assertEqual(result["fallbackReason"], "ai_provider_failure")
        self.assertNotIn("secret", json.dumps(result))

    def test_remote_protocol_failure_retries_once_and_recovers(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        valid = AIInterpretation(brands=["Samsung"], categories=["Double Door Refrigerator", "Single Door Refrigerator"],
                                 price_min=None, price_max=None, model="", attributes=[], preferences=[], resolutions=[]).model_dump()
        invoke.side_effect = [httpx.RemoteProtocolError("SECRET_CONNECTION_DETAIL"), valid]
        with self.assertLogs("smart_search", level="WARNING") as logs:
            result = self.search.search("Samsung fridge")
        self.assertEqual(result["interpretationSource"], "ai")
        self.assertNotIn("fallbackReason", result)
        self.assertEqual(invoke.call_count, 2)
        self.assertNotIn("SECRET_CONNECTION_DETAIL", " ".join(logs.output))
        timeouts = [call.kwargs["timeout"] for call in invoke.call_args_list]
        self.assertLess(timeouts[1], timeouts[0])
        self.assertTrue(all(call.kwargs["max_retries"] == 1 for call in invoke.call_args_list))

    def test_repeated_connection_failure_remains_bounded(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        invoke.side_effect = httpx.RemoteProtocolError("SECRET_CONNECTION_DETAIL")
        result = self.search.search("Samsung 5 star fridge")
        self.assertEqual(result["fallbackReason"], "ai_provider_failure")
        self.assertEqual(invoke.call_count, 2)
        self.assertNotIn("SECRET_CONNECTION_DETAIL", json.dumps(result))

    def test_transport_retry_does_not_start_with_insufficient_time(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        invoke.side_effect = httpx.RemoteProtocolError("lost connection")
        with patch("smart_search.ai_timeout", return_value=1.5):
            result = self.search.search("Samsung 5 star fridge")
        self.assertEqual(result["fallbackReason"], "ai_provider_failure")
        self.assertEqual(invoke.call_count, 1)

    def test_wrapped_transport_failure_can_recover(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        wrapper = RuntimeError("SDK wrapped the transport failure")
        wrapper.__cause__ = httpx.RemoteProtocolError("lost connection")
        valid = AIInterpretation(brands=["Samsung"], categories=["Double Door Refrigerator", "Single Door Refrigerator"],
                                 price_min=None, price_max=None, model="", attributes=[], preferences=[], resolutions=[]).model_dump()
        invoke.side_effect = [wrapper, valid]
        result = self.search.search("Samsung fridge")
        self.assertNotIn("fallbackReason", result)
        self.assertEqual(invoke.call_count, 2)

    def test_transport_retry_and_schema_repair_share_two_total_attempts(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        invoke.side_effect = [httpx.RemoteProtocolError("lost connection"), {}]
        result = self.search.search("Samsung fridge")
        self.assertEqual(result["fallbackReason"], "invalid_ai_output")
        self.assertEqual(invoke.call_count, 2)

    def test_transport_retry_shares_the_original_caller_deadline(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        def respond(*args, **kwargs):
            if invoke.call_count == 1:
                raise httpx.RemoteProtocolError("lost connection")
            time.sleep(2.4)
            return {}
        invoke.side_effect = respond
        with patch("smart_search.ai_timeout", return_value=2.1):
            started = time.monotonic()
            result = self.search.search("Samsung fridge")
        self.assertLess(time.monotonic() - started, 2.3)
        self.assertEqual(result["fallbackReason"], "ai_timeout")
        self.assertEqual(invoke.call_count, 2)

    def test_auth_failure_is_not_retried_as_a_transport_error(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        request = httpx.Request("POST", "https://example.invalid")
        invoke.side_effect = httpx.HTTPStatusError("unauthorized", request=request,
                                                response=httpx.Response(401, request=request))
        result = self.search.search("Samsung 5 star fridge")
        self.assertEqual(result["fallbackReason"], "ai_provider_failure")
        self.assertEqual(invoke.call_count, 1)

    def test_unknown_brand_mapping_rejected(self):
        value = Interpretation(brands=["Invented"], categories=[], price_min=None, price_max=None,
                               model="", attributes=[], preferences=[]).model_dump()
        self.ai.with_structured_output.return_value.invoke.return_value = value
        self.assertEqual(ai_interpret(self.ai, "fridge", TAXONOMY)[1], "invalid_ai_output")

    def test_ai_structured_output_without_history_or_tools(self):
        self.ai.with_structured_output.return_value.invoke.return_value = {}
        self.search.search("Samsung red fridge")
        args = self.ai.with_structured_output.call_args
        self.assertEqual(args.kwargs["method"], "json_schema")
        messages = self.ai.with_structured_output.return_value.invoke.call_args.args[0]
        self.assertEqual([m.type for m in messages], ["system", "human"])
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_args.kwargs["max_retries"], 1)
        self.assertGreater(self.ai.with_structured_output.return_value.invoke.call_args.kwargs["timeout"], 0)
        self.ai.bind_tools.assert_not_called()

    def test_service_outage_is_not_zero_matches(self):
        self.catalogue.index.query.side_effect = RuntimeError("down")
        with self.assertRaises(SearchUnavailable):
            self.search.search("Samsung fridge")

    def test_live_outage_is_not_zero_matches(self):
        self.fetch.side_effect = lambda *_: {"error": "down"}
        with self.assertRaises(SearchUnavailable):
            self.search.search("Samsung fridge under 40k")

    def test_prices_refreshed_each_request(self):
        self.search.search("Samsung fridge")
        self.fetch.side_effect = lambda pid, city: detail(pid, city, 30000)
        self.assertEqual(self.search.search("Samsung fridge")["products"][0]["selling_price"], 30000)
        self.assertEqual(self.fetch.call_count, 2)

    def test_pagination_deduplicates_and_does_not_invent_total(self):
        self.catalogue.index.query.return_value.matches = [match("1"), match("1"), match("2"), match("3")]
        result = self.search.search("Samsung fridge", page_size=2)
        self.assertEqual([r["product_id"] for r in result["products"]], ["1", "2"])
        self.assertEqual(result["pagination"]["nextPage"], 2)
        self.assertIsNone(result["pagination"]["total"])

    def test_default_page_size_24_enriches_all(self):
        self.catalogue.index.query.return_value.matches = [match(str(i)) for i in range(1, 26)]
        result = self.search.search("Samsung fridge")
        self.assertEqual(len(result["products"]), 24)

    def test_taxonomy_namespace_mismatch(self):
        self.catalogue.settings.namespace = "different"
        with self.assertRaises(SearchUnavailable):
            self.search.search("fridge")

    def test_exact_sku_query_is_prioritized(self):
        self.ai.with_structured_output.return_value.invoke.return_value = {}
        self.catalogue.index.query.side_effect = [SimpleNamespace(matches=[]), SimpleNamespace(matches=[match()])]
        result = self.search.search("RT1")
        self.assertEqual(result["products"][0]["sku"], "RT1")
        self.assertEqual(self.catalogue.index.query.call_args.kwargs["filter"]["sku"], {"$eq": "RT1"})

    def test_no_chat_imports_in_search_path(self):
        for path in ("smart_search.py", "smart_search_api.py"):
            tree = ast.parse(Path(path).read_text(encoding="utf-8"))
            imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            self.assertNotIn("chat", imports)
            self.assertNotIn("store", imports)

    def test_reversed_budget_rejected(self):
        with self.assertRaises(ValueError):
            self.search.search("fridge between 50k and 40k")

    def test_multiple_category_words_reach_llm_before_fallback(self):
        result = self.search.search("fridge laptop")
        self.ai.with_structured_output.assert_called_once()
        self.assertEqual(result["products"], [])
        self.assertEqual(result["fallbackReason"], "invalid_ai_output")


class SemanticInterpretationTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy = {**TAXONOMY, "categories": ["Android Smartphone", "iPhone Mobile", "Feature Mobile Phone",
                           "Front Load Washing Machine", "Top Load Washing Machine", "Semi Automatic Washing Machine"]}
        self.catalogue = Mock()
        self.catalogue.settings.namespace = "test"
        self.ai = Mock()
        self.search = SmartSearch(self.catalogue, self.ai, self.taxonomy)

    def output(self, resolutions, **kwargs):
        value = dict(brands=[], categories=["Android Smartphone", "iPhone Mobile"], price_min=None,
                     price_max=35000.0, model="", attributes=[], preferences=[], resolutions=resolutions)
        value.update(kwargs)
        self.ai.with_structured_output.return_value.invoke.return_value = AIInterpretation(**value).model_dump()

    def mapping(self, source, kind, *values):
        return {"source": source, "kind": kind, "values": list(values)}

    def test_smart_phone_consumes_smart_without_requiring_literal_title(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone", "iPhone Mobile")])
        intent, _, _, fallback, source = self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual(source, "ai")
        self.assertIsNone(fallback)
        self.assertEqual(intent.attributes, [])
        self.assertNotIn("Feature Mobile Phone", intent.categories)

    def test_redundant_filler_does_not_undo_valid_category_mapping(self):
        self.output([self.mapping("smart", "filler"),
                     self.mapping("smart phone", "category", "Android Smartphone", "iPhone Mobile")])
        intent, _, _, fallback, source = self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual((intent.attributes, fallback, source), ([], None, "ai"))

    def test_atomic_spec_resolutions_support_combined_attribute(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone", "iPhone Mobile"),
                     self.mapping("smart", "attribute", "smart"), self.mapping("8gb", "attribute", "8gb"),
                     self.mapping("ram", "attribute", "ram")], attributes=["8gb ram"])
        intent, _, _, fallback, source = self.search.interpret("smart phone with 8gb ram under 35000", self.taxonomy)
        self.assertEqual((intent.attributes, fallback, source), (["8gb ram"], None, "ai"))

    def test_brand_and_category_typos_can_be_resolved_by_ai(self):
        self.output([self.mapping("samsng", "brand", "Samsung"),
                     self.mapping("mobail", "category", "Android Smartphone", "iPhone Mobile")], brands=["Samsung"])
        intent, _, corrections, fallback, source = self.search.interpret("samsng mobail under 35000", self.taxonomy)
        self.assertEqual((intent.brands, intent.attributes, source, fallback), (["Samsung"], [], "ai", None))
        self.assertTrue(any(c["from"] == "samsng" for c in corrections))

    def test_hinglish_description_maps_to_catalogue(self):
        cats = ["Front Load Washing Machine", "Top Load Washing Machine", "Semi Automatic Washing Machine"]
        self.output([self.mapping("kapde dhone ki machine", "category", *cats)], categories=cats, price_max=20000.0)
        intent, _, _, fallback, _ = self.search.interpret("kapde dhone ki machine 20 hazar ke andar", self.taxonomy)
        self.assertIsNone(fallback)
        self.assertEqual(intent.categories, cats)
        self.assertEqual(intent.price_max, 20000)
        self.assertEqual(intent.attributes, [])

    def test_camera_use_case_is_ranking_not_invented_specification(self):
        self.output([self.mapping("good camera", "preference", "camera")], preferences=["camera"])
        intent, _, _, fallback, _ = self.search.interpret("phone with good camera under 35000", self.taxonomy)
        self.assertIsNone(fallback)
        self.assertEqual(intent.preferences, ["camera"])
        self.assertEqual(intent.attributes, [])

    def test_omitted_colour_is_rejected(self):
        self.output([])
        intent, _, _, fallback, _ = self.search.interpret("red phone under 35000", self.taxonomy)
        self.assertEqual(fallback, "invalid_ai_output")
        self.assertIn("red", intent.attributes)

    def test_colour_cannot_be_filler_or_category_or_change_colour(self):
        for mapping in [self.mapping("red", "filler"), self.mapping("red", "category", "Android Smartphone"),
                        self.mapping("red", "attribute", "blue")]:
            self.output([mapping], attributes=["blue"] if mapping["kind"] == "attribute" else [])
            self.assertEqual(self.search.interpret("red phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_budget_cannot_be_relaxed(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone")], price_max=40000.0)
        intent, _, _, fallback, _ = self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual((intent.price_max, fallback), (35000, "invalid_ai_output"))

    def test_exact_brand_cannot_be_replaced(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone")], brands=["LG"])
        intent, _, _, fallback, _ = self.search.interpret("Samsung smart phone under 35000", self.taxonomy)
        self.assertEqual((intent.brands, fallback), (["Samsung"], "invalid_ai_output"))

    def test_unrelated_unknown_brand_cannot_be_replaced(self):
        self.output([self.mapping("xyzbrand", "brand", "Samsung")], brands=["Samsung"])
        self.assertEqual(self.search.interpret("xyzbrand phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_numeric_spec_cannot_become_a_preference(self):
        self.output([self.mapping("8gb", "preference", "gaming")], preferences=["gaming"])
        self.assertEqual(self.search.interpret("8gb phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_numeric_spec_cannot_change_units(self):
        self.output([self.mapping("8gb", "attribute", "8MP")], attributes=["8MP"])
        self.assertEqual(self.search.interpret("8gb phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_inverter_cannot_become_a_preference(self):
        self.output([self.mapping("inverter", "preference", "efficient")], preferences=["efficient"])
        self.assertEqual(self.search.interpret("inverter phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_source_not_in_query_rejected(self):
        self.output([self.mapping("smart mobile", "category", "Android Smartphone")])
        self.assertEqual(self.search.interpret("smart phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_linguistic_filler_is_consumed(self):
        self.output([self.mapping("can you recommend", "filler")])
        intent, _, _, fallback, _ = self.search.interpret("can you recommend a phone under 35000", self.taxonomy)
        self.assertEqual((intent.attributes, fallback), ([], None))

    def test_cache_contains_only_interpretation_and_uses_version(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone", "iPhone Mobile")])
        self.search.interpret("smart phone under 35000", self.taxonomy)
        cached = self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual(cached[4], "ai_cache")
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 1)
        cached[0].attributes.append("must not mutate cache")
        self.assertEqual(self.search.interpret("smart phone under 35000", self.taxonomy)[0].attributes, [])
        self.search.interpret("smart phone under 35000", {**self.taxonomy, "version": "v2"})
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 2)

    def test_invalid_output_not_cached(self):
        self.ai.with_structured_output.return_value.invoke.return_value = {}
        for _ in range(2):
            self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 4)

    def test_concurrent_identical_queries_share_one_ai_call(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone", "iPhone Mobile")])
        invoke = self.ai.with_structured_output.return_value.invoke
        value = invoke.return_value
        started, release = threading.Event(), threading.Event()
        barrier = threading.Barrier(6)

        def respond(*args, **kwargs):
            started.set()
            if not release.wait(2):
                raise RuntimeError("Test provider did not release")
            return value

        def request():
            barrier.wait(2)
            return self.search.interpret("smart phone under 35000", self.taxonomy)

        invoke.side_effect = respond
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(request) for _ in range(6)]
            self.assertTrue(started.wait(2))
            release.set()
            results = [f.result(timeout=3) for f in futures]
        self.assertEqual(invoke.call_count, 1)
        self.assertTrue(all(r[3] is None for r in results))
        results[0][0].categories.clear()
        self.assertTrue(all(r[0].categories for r in results[1:]))

    def test_provider_failure_does_not_poison_next_request(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone", "iPhone Mobile")])
        invoke = self.ai.with_structured_output.return_value.invoke
        invoke.side_effect = [RuntimeError("Provider down"), invoke.return_value]
        first = self.search.interpret("smart phone under 35000", self.taxonomy)
        second = self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual(first[3], "ai_provider_failure")
        self.assertEqual((second[3], second[4]), (None, "ai"))
        self.assertEqual(invoke.call_count, 2)

    def test_catalogue_family_context_is_derived_for_new_category_names(self):
        categories = ["Compact Widget", "Pro Widget", "Widgets", "Widget Covers"]
        taxonomy = {**self.taxonomy, "categories": categories}
        families = category_families(categories)
        self.assertEqual(families["widget"], ["Compact Widget", "Pro Widget", "Widgets"])
        self.assertNotIn("Widget Covers", families["widget"])
        prompt = interpretation_prompt("widgets", taxonomy, [], "family")
        self.assertIn('"ambiguousSourceCategories": ["Widgets"]', prompt)
        self.assertIn('"categoryFamilies"', prompt)

    def test_semantic_property_can_select_category_without_literal_hinglish_filter(self):
        taxonomy = {**self.taxonomy, "categories": ["Thin & Light Laptop", "Gaming Laptop", "Windows Laptop"]}
        self.output([self.mapping("halka", "category", "Thin & Light Laptop"),
                     self.mapping("office ke liye", "preference", "office")],
                    categories=["Thin & Light Laptop"], price_max=50000, preferences=["office"])
        intent, _, _, fallback, source = self.search.interpret(
            "office ke liye halka laptop 50 hazar tak", taxonomy)
        self.assertEqual((fallback, source), (None, "ai"))
        self.assertEqual(intent.categories, ["Thin & Light Laptop"])
        self.assertEqual(intent.attributes, [])

    def test_subtype_resolution_cannot_leave_other_family_members_in_results(self):
        taxonomy = {**self.taxonomy, "categories": ["Thin & Light Laptop", "Gaming Laptop", "Windows Laptop"]}
        self.output([self.mapping("halka", "category", "Thin & Light Laptop")],
                    categories=taxonomy["categories"], price_max=None)
        result = self.search.interpret("halka laptop", taxonomy)
        self.assertEqual(result[3], "invalid_ai_output")

    def test_family_and_property_evidence_accepts_ai_selected_intersection(self):
        taxonomy = {**self.taxonomy, "categories": ["Thin & Light Laptop", "Gaming Laptop", "Windows Laptop"]}
        self.output([self.mapping("halka", "category", "Thin & Light Laptop"),
                     self.mapping("laptop", "category", *taxonomy["categories"])],
                    categories=["Thin & Light Laptop"], price_max=None)
        result = self.search.interpret("halka laptop", taxonomy)
        self.assertEqual((result[0].categories, result[3], result[4]), (["Thin & Light Laptop"], None, "ai"))
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 1)

    def test_provider_schema_restricts_brand_and_category_labels_to_catalogue(self):
        schema = provider_schema(self.taxonomy)
        for field in ("brands", "categories"):
            self.assertEqual(schema["properties"][field]["items"]["enum"], self.taxonomy[field])

    def test_large_catalogue_keeps_provider_schema_simple(self):
        taxonomy = {"brands": [f"Brand {i}" for i in range(114)],
                    "categories": [f"Category {i}" for i in range(124)]}
        schema = provider_schema(taxonomy)
        for field in ("brands", "categories"):
            self.assertNotIn("enum", schema["properties"][field]["items"])

    def test_label_formatting_is_canonicalized_without_semantic_rewriting(self):
        self.output([self.mapping("smart phone", "category", "AndroidSmartphone")],
                    categories=["android smartphone"], price_max=None)
        result = self.search.interpret("smart phone", self.taxonomy)
        self.assertEqual((result[0].categories, result[3]), (["Android Smartphone"], None))

    def test_unknown_category_is_not_corrected_by_fuzzy_label_matching(self):
        self.output([self.mapping("smart phone", "category", "Imaginary Smartphone")],
                    categories=["Imaginary Smartphone"], price_max=None)
        self.assertEqual(self.search.interpret("smart phone", self.taxonomy)[3], "invalid_ai_output")

    def test_known_empty_brand_category_is_repaired_by_ai(self):
        self.taxonomy["brandCategories"] = {"Voltas": ["Wall Mounted Split AC"],
                                          "Voltas Beko": ["Front Load Washing Machine"]}
        self.output([self.mapping("voltas", "brand", "Voltas Beko")], brands=["Voltas Beko"],
                    categories=["Front Load Washing Machine"], price_max=None)
        invoke = self.ai.with_structured_output.return_value.invoke
        valid = invoke.return_value
        invoke.side_effect = [{**valid, "brands": ["Voltas"], "resolutions": []}, valid]
        result = self.search.interpret("voltas washing machine", self.taxonomy)
        self.assertEqual((result[0].brands, result[3]), (["Voltas Beko"], None))
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("Known-empty brand/category pair", invoke.call_args.args[0][0].content)

    def test_exact_mode_permits_empty_pair_without_compound_substitution(self):
        self.taxonomy["brandCategories"] = {"Voltas": ["Wall Mounted Split AC"],
                                          "Voltas Beko": ["Front Load Washing Machine"]}
        self.output([], brands=["Voltas"], categories=["Front Load Washing Machine"], price_max=None)
        result = self.search.interpret("voltas washing machine", self.taxonomy, brand_match="exact")
        self.assertEqual((result[0].brands, result[3], result[4]), (["Voltas"], None, "ai"))

    def test_native_schema_inlines_nested_refs_but_backend_keeps_limits(self):
        schema = provider_schema()
        self.assertNotIn("$ref", json.dumps(schema))
        self.assertNotIn("$defs", schema)
        item = schema["properties"]["resolutions"]["items"]
        self.assertEqual(item["type"], "object")
        self.assertFalse(item["additionalProperties"])
        self.output([self.mapping("smart phone", "category", "Android Smartphone")])
        self.ai.with_structured_output.return_value.invoke.return_value["resolutions"] *= 31
        self.assertEqual(self.search.interpret("smart phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_cache_expires_and_namespace_changes_invalidate_it(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone")], categories=["Android Smartphone"])
        with patch("smart_search.time.monotonic", return_value=100):
            self.search.interpret("smart phone under 35000", self.taxonomy)
        with patch("smart_search.time.monotonic", return_value=401):
            self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 2)
        self.catalogue.settings.namespace = "test-new"
        self.search.interpret("smart phone under 35000", self.taxonomy)
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 3)

    def test_ai_cannot_add_unrequested_specification(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone")], attributes=["16GB RAM"])
        self.assertEqual(self.search.interpret("smart phone under 35000", self.taxonomy)[3], "invalid_ai_output")

    def test_provider_request_uses_remaining_caller_budget(self):
        self.output([self.mapping("smart phone", "category", "Android Smartphone")])
        with patch.dict(os.environ, {"SMART_SEARCH_AI_TIMEOUT": "1"}):
            self.search.interpret("smart phone under 35000", self.taxonomy)
        timeout = self.ai.with_structured_output.return_value.invoke.call_args.kwargs["timeout"]
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 1)
        headers = self.ai.with_structured_output.return_value.invoke.call_args.kwargs["http_options"]["headers"]
        self.assertEqual(headers["X-Server-Timeout"], "10")

    def test_llm_selects_compound_brand_using_catalogue_pairs(self):
        self.taxonomy["brandCategories"] = {"Voltas": ["Wall Mounted Split AC"],
                                          "Voltas Beko": ["Front Load Washing Machine"]}
        self.output([self.mapping("voltas", "brand", "Voltas Beko"),
                     self.mapping("washing machine", "category", "Front Load Washing Machine")],
                    brands=["Voltas Beko"], categories=["Front Load Washing Machine"], price_max=None)
        intent, _, _, fallback, source = self.search.interpret("voltas washing machine", self.taxonomy)
        self.assertEqual((intent.brands, source, fallback), (["Voltas Beko"], "ai", None))
        prompt = self.ai.with_structured_output.return_value.invoke.call_args.args[0][0].content
        self.assertIn('"Voltas Beko": ["Front Load Washing Machine"]', prompt)

    def test_compound_brand_mapping_is_generic_not_voltas_special_case(self):
        self.taxonomy["brands"] = [*self.taxonomy["brands"], "Example", "Example Home"]
        self.taxonomy["brandCategories"] = {"Example Home": ["Front Load Washing Machine"]}
        self.output([self.mapping("example", "brand", "Example Home")], brands=["Example Home"],
                    categories=["Front Load Washing Machine"], price_max=None)
        intent, _, _, fallback, _ = self.search.interpret("example washing machine", self.taxonomy)
        self.assertEqual((intent.brands, fallback), (["Example Home"], None))

    def test_exact_brand_mode_cannot_reuse_family_interpretation(self):
        self.taxonomy["brandCategories"] = {"Voltas Beko": ["Front Load Washing Machine"]}
        self.output([self.mapping("voltas", "brand", "Voltas Beko")], brands=["Voltas Beko"],
                    categories=["Front Load Washing Machine"], price_max=None)
        self.search.interpret("voltas washing machine", self.taxonomy)
        result = self.search.interpret("voltas washing machine", self.taxonomy, brand_match="exact")
        self.assertEqual(result[0].brands, ["Voltas"])
        self.assertEqual(result[3], "invalid_ai_output")
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 3)

    def test_inconsistent_brand_output_repaired_once_before_fallback(self):
        self.taxonomy["brandCategories"] = {"Voltas Beko": ["Front Load Washing Machine"]}
        self.output([self.mapping("voltas", "brand", "Voltas Beko")], brands=["Voltas Beko"],
                    categories=["Front Load Washing Machine"], price_max=None)
        valid = self.ai.with_structured_output.return_value.invoke.return_value
        invalid = {**valid, "brands": []}
        invoke = self.ai.with_structured_output.return_value.invoke
        invoke.side_effect = [invalid, valid]
        result = self.search.interpret("voltas washing machine", self.taxonomy)
        self.assertEqual((result[0].brands, result[3], result[4]), (["Voltas Beko"], None, "ai"))
        self.assertEqual(invoke.call_count, 2)
        messages = invoke.call_args.args[0]
        self.assertEqual([m.type for m in messages], ["system", "human"])
        self.assertIn("Resolution does not match output filters", messages[0].content)
        self.assertEqual(messages[1].content, "voltas washing machine")
        self.assertEqual(self.search.interpret("voltas washing machine", self.taxonomy)[4], "ai_cache")
        self.assertEqual(invoke.call_count, 2)

    def test_inferred_brand_needs_unique_explicit_category_catalogue_evidence(self):
        self.taxonomy["brands"] = [*self.taxonomy["brands"], "Apple"]
        self.taxonomy["brandCategories"] = {"Apple": ["iPhone Mobile"], "Samsung": ["Android Smartphone"]}
        self.output([self.mapping("iphone", "brand", "Apple")], brands=["Apple"],
                    categories=["iPhone Mobile"], price_max=None)
        self.assertIsNone(self.search.interpret("iphone", self.taxonomy)[3])
        self.taxonomy = {**self.taxonomy, "version": "ambiguous", "brandCategories": {
            "Apple": ["iPhone Mobile"], "Samsung": ["iPhone Mobile"]}}
        self.assertEqual(self.search.interpret("iphone", self.taxonomy)[3], "invalid_ai_output")

    def test_availability_question_retains_product_family(self):
        self.output([self.mapping("pixels", "attribute", "pixel"),
                     self.mapping("pixels", "category", "Android Smartphone"),
                     self.mapping("avaible hai kya", "filler")],
                    attributes=["pixel"], categories=["Android Smartphone"], price_max=None)
        result = self.search.interpret("pixels avaible hai kya", self.taxonomy)
        self.assertEqual((result[0].attributes, result[3]), (["pixel"], None))

    def test_repair_shares_overall_timeout(self):
        invoke = self.ai.with_structured_output.return_value.invoke
        def respond(*args, **kwargs):
            if invoke.call_count == 1:
                return {}
            time.sleep(2.4)
            return {}
        invoke.side_effect = respond
        with patch("smart_search.ai_timeout", return_value=2.1):
            started = time.monotonic()
            result = self.search.interpret("phone", self.taxonomy)
        self.assertLess(time.monotonic() - started, 2.3)
        self.assertEqual(result[3], "ai_timeout")
        self.assertEqual(invoke.call_count, 2)

    def test_validation_logging_does_not_include_provider_input(self):
        self.ai.with_structured_output.return_value.invoke.side_effect = ValueError("SECRET_PROVIDER_INPUT")
        with self.assertLogs("smart_search", level="WARNING") as logs:
            self.search.interpret("phone", self.taxonomy)
        self.assertNotIn("SECRET_PROVIDER_INPUT", " ".join(logs.output))
        self.assertIn("reason=ValueError", " ".join(logs.output))

    def test_compound_brand_without_matching_catalogue_category_rejected(self):
        self.taxonomy["brandCategories"] = {"Voltas Beko": ["Solo Microwave Oven"]}
        self.output([self.mapping("voltas", "brand", "Voltas Beko")], brands=["Voltas Beko"],
                    categories=["Front Load Washing Machine"], price_max=None)
        self.assertEqual(self.search.interpret("voltas washing machine", self.taxonomy)[3], "invalid_ai_output")

    def test_llm_can_narrow_generic_phone_without_lexical_override(self):
        self.output([], categories=["Android Smartphone"])
        result = self.search.interpret("phone under 35000", self.taxonomy)
        self.assertEqual(result[0].categories, ["Android Smartphone"])
        self.assertEqual(result[4], "ai")

    def test_conversational_query_reaches_llm_without_attribute_count_failure(self):
        query = "Could you please help recommend something suitable for my family that would work well every day and be easy to use at home"
        self.ai.with_structured_output.return_value.invoke.return_value = {}
        self.search.interpret(query, self.taxonomy)
        messages = self.ai.with_structured_output.return_value.invoke.call_args.args[0]
        self.assertEqual(messages[1].content, query)

    def test_understood_budget_filler_does_not_discard_valid_ai_result(self):
        self.output([self.mapping("ke andar", "filler")])
        result = self.search.interpret("phone 35 hazar ke andar", self.taxonomy)
        self.assertEqual((result[0].price_max, result[3], result[4]), (35000, None, "ai"))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(create_smart_search_blueprint(Mock(), Mock()))
        self.client = self.app.test_client()

    def test_validation(self):
        for body in [[], {}, {"query": "x"}, {"query": "x"*301}, {"query": "fridge", "page": True},
                     {"query": "fridge", "pageSize": 49}, {"query": "fridge", "page": 0},
                     {"query": "fridge", "city": ""}, {"query": "fridge", "brand": "LG"}]:
            self.assertEqual(self.client.post("/api/search/smart", json=body).status_code, 400)

    @patch("smart_search_api.SmartSearch.search")
    def test_envelope_and_no_store(self, search):
        search.return_value = {"products": [], "searchMode": "smart"}
        response = self.client.post("/api/search/smart", json={"query": "fridge"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "success")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    @patch("smart_search_api.SmartSearch.search", side_effect=SearchUnavailable("Unavailable"))
    def test_error_envelope(self, _):
        response = self.client.post("/api/search/smart", json={"query": "fridge"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("products", response.json)


if __name__ == "__main__":
    unittest.main()
