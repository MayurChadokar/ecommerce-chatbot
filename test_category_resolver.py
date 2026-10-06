"""Category hierarchy, semantic mapping and honest alternatives; no network."""
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from search_taxonomy import CategoryCatalogue
from smart_search import AIInterpretation, SmartSearch, deterministic
from smart_search_api import create_smart_search_blueprint
from test_smart_search import ProductSearchTool, detail, match
from live_product_enrichment import enrich
from scripts.extract_products import iter_product_rows


class CategoryResolverTests(unittest.TestCase):
    def setUp(self):
        self.taxonomy = json.loads(Path("smart_search_taxonomy.json").read_text(encoding="utf-8"))
        self.taxonomy["namespace"] = "test"
        self.categories = CategoryCatalogue(self.taxonomy)
        self.catalogue = ProductSearchTool.__new__(ProductSearchTool)
        self.catalogue.is_available = True
        self.catalogue.settings = SimpleNamespace(namespace="test")
        self.catalogue.last_error = None
        self.catalogue.model = Mock()
        self.catalogue.model.encode.return_value.tolist.return_value = [.1] * 384
        self.catalogue.index = Mock()
        self.catalogue.index.query.return_value = SimpleNamespace(matches=[])
        self.ai = Mock()
        self.fetch = Mock(side_effect=lambda pid, city: detail(pid, city, 39999))
        self.search = SmartSearch(self.catalogue, self.ai, self.taxonomy,
                                  lambda rows, **kw: enrich(rows, fetch=self.fetch, **kw))

    def output(self, categories, attributes=None, resolutions=None, **extra):
        value = dict(brands=[], categories=categories, price_min=None, price_max=None,
                     model="", attributes=attributes or [], preferences=[], resolutions=resolutions or [])
        value.update(extra)
        self.ai.with_structured_output.return_value.invoke.return_value = AIInterpretation(**value).model_dump()

    @staticmethod
    def resolution(source, kind, *values):
        return {"source": source, "kind": kind, "values": list(values)}

    def records(self, *rows):
        records = []
        for pid, category, name, brand in rows:
            record = match(pid, brand=brand, name=name)
            record.metadata.update(category=category, sku="")
            records.append(record)
        self.catalogue.index.query.return_value.matches = records

    def subtype(self, name, attributes=None, **extra):
        scope = self.categories.describe(name)
        attrs = attributes or scope["requiredTerms"]
        self.output(scope["matchedCategories"], attrs,
                    [self.resolution(name, "category", *scope["matchedCategories"]),
                     self.resolution(name, "attribute", *attrs)], **extra)

    def test_active_master_has_the_176_user_categories(self):
        self.assertEqual(sum(n["active"] for n in self.taxonomy["categoryTree"]), 176)
        self.assertEqual(len(self.taxonomy["categories"]), 124)

    def test_parent_includes_its_own_products_and_children(self):
        scope = self.categories.describe("Laptops")
        self.assertEqual(scope["matchType"], "family")
        self.assertIn("Laptops", scope["matchedCategories"])
        self.assertIn("Gaming Laptop", scope["matchedCategories"])
        self.output(scope["matchedCategories"])
        self.records(("1", "Laptops", "Asus Chromebook", "Asus"),
                     ("2", "Gaming Laptop", "Asus Gaming Laptop", "Asus"))
        result = self.search.search("show products", category="Laptops")
        self.assertEqual(len(result["products"]), 2)
        self.assertEqual(result["categoryResolution"]["matchType"], "family")

    def test_computers_parent_does_not_include_televisions(self):
        scope = self.categories.describe("Computers")
        self.output(scope["matchedCategories"])
        self.records(("1", "Windows Laptop", "HP Windows Laptop", "HP"),
                     ("2", "OLED TV", "Samsung OLED TV", "Samsung"))
        result = self.search.search("show products", category="Computers")
        self.assertEqual([p["product_id"] for p in result["products"]], ["1"])
        self.assertNotIn("OLED TV", result["appliedFilters"]["categories"])

    def test_water_purifiers_maps_to_ro_and_uv(self):
        scope = self.categories.describe("Water Purifiers")
        self.assertEqual(scope["matchedCategories"], ["Water Purifier RO", "Water Purifier UV"])

    def test_disc_and_disk_master_spelling_is_an_equivalent_category(self):
        taxonomy = {"categories": ["Hard Disk"], "categoryTree": [
            {"id": "a", "parentId": "0", "name": "Computer Accessories", "active": True},
            {"id": "b", "parentId": "a", "name": "Hard disc", "active": True},
            {"id": "c", "parentId": "a", "name": "Hard Disk", "active": True}]}
        scope = CategoryCatalogue(taxonomy).describe("Hard disc")
        self.assertEqual(scope["matchType"], "equivalent")
        self.assertEqual(scope["matchedCategories"], ["Hard Disk"])

    def test_missing_storage_does_not_offer_mouse_or_keyboard(self):
        scope = self.categories.describe("Hard disc")
        self.assertEqual(scope["matchType"], "attribute")
        self.assertFalse(scope["_allowAlternatives"])
        self.subtype("Hard disc")
        self.records(("1", "Mouse", "HP Mouse", "HP"))
        result = self.search.search("show products", category="Hard disc")
        self.assertEqual(result["products"], [])
        self.assertEqual(result["alternatives"], [])

    def test_missing_resolution_is_not_a_spelling_correction(self):
        scope = self.categories.describe("8K Ultra HD TV")
        self.assertEqual(scope["matchType"], "attribute")
        self.assertEqual(scope["requiredTerms"], ["8k"])

    def test_android_category_does_not_require_redundant_title_words(self):
        self.output(["Android Smartphone"], resolutions=[self.resolution("Android", "category", "Android Smartphone")])
        self.records(("1", "Android Smartphone", "Samsung Galaxy Phone", "Samsung"))
        result = self.search.search("show products", category="Android")
        self.assertEqual([p["product_id"] for p in result["products"]], ["1"])
        self.assertEqual(result["appliedFilters"]["attributes"], [])
        self.assertNotIn("fallbackReason", result)

    def test_parent_with_more_than_25_categories_is_supported(self):
        scope = self.categories.describe("Home Appliances")
        self.assertGreater(len(scope["matchedCategories"]), 25)
        self.output(scope["matchedCategories"])
        result = self.search.search("show products", category="Home Appliances")
        self.assertEqual(result["appliedFilters"]["categories"], scope["matchedCategories"])
        self.assertNotIn("fallbackReason", result)

    def test_parent_can_be_narrowed_by_query_subtype(self):
        self.output(["Gaming Laptop"])
        result = self.search.search("gaming laptop", category="Computers")
        self.assertEqual(result["appliedFilters"]["categories"], ["Gaming Laptop"])

    def test_washing_machine_function_excludes_adjacent_dryers(self):
        cats = [c for c in self.taxonomy["categories"] if "Washing Machine" in c]
        self.records(("1", "Front Load Washing Machine", "Voltas Beko Front Load Washing Machine", "Voltas Beko"),
                     ("2", "Cloth Dryer", "Samsung Cloth Dryer", "Samsung"))
        for query in ("washing machine", "Washing Machines"):
            with self.subTest(query=query):
                self.output(cats, resolutions=[self.resolution(query, "category", *cats)])
                result = self.search.search(query)
                self.assertEqual([p["product_id"] for p in result["products"]], ["1"])
                self.assertNotIn("fallbackReason", result)
        self.assertEqual(set(deterministic("washing machine", self.taxonomy)[0].categories), set(cats))

    def test_unavailable_function_has_no_unrelated_department_alternatives(self):
        scope = self.categories.describe("DVD")
        self.assertEqual(scope["matchType"], "attribute")
        self.assertEqual(scope["suggestedCategories"], [])
        self.subtype("DVD")
        self.records(("1", "Projectors", "Samsung Projector", "Samsung"))
        result = self.search.search("show products", category="DVD")
        self.assertEqual(result["products"], [])
        self.assertEqual(result["alternatives"], [])

    def test_category_cycles_do_not_hang_resolution(self):
        taxonomy = {"categories": ["Gaming Laptop"], "categoryTree": [
            {"id": "a", "parentId": "b", "name": "Computers", "active": True},
            {"id": "b", "parentId": "a", "name": "Gaming Laptop", "active": True}]}
        self.assertEqual(CategoryCatalogue(taxonomy).describe("Computers")["matchedCategories"], ["Gaming Laptop"])

    def test_category_import_reads_only_the_requested_public_table(self):
        sql = ("INSERT INTO `les_products` (`product_id`) VALUES (7);\n"
               "INSERT INTO `les_category` (`cat_id`,`cat_name`,`cat_parent_id`,`is_active`) VALUES (1,'Laptops',0,1);\n"
               "INSERT INTO `les_users` (`email`) VALUES ('private@example.invalid');\n")
        with patch.object(Path, "open", return_value=StringIO(sql)):
            rows = list(iter_product_rows("unused.sql", allowed_tables={"les_category"}))
        self.assertEqual(rows, [("les_category", {"cat_id": "1", "cat_name": "Laptops", "cat_parent_id": "0", "is_active": "1"})])
        with self.assertRaises(ValueError):
            list(iter_product_rows("unused.sql", allowed_tables={"les_users"}))

    def test_unknown_synonym_goes_to_ai_once(self):
        cats = self.categories.describe("Laptops")["matchedCategories"]
        self.output(cats, resolutions=[self.resolution("notebook", "category", *cats)])
        result = self.search.search("show products", category="notebook")
        self.assertEqual(result["categoryResolution"]["matchType"], "semantic")
        self.assertEqual(result["appliedFilters"]["categories"], cats)
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 1)
        self.assertEqual(result["normalizedQuery"], "show products")

    def test_parent_label_is_valid_evidence_for_ai_selected_descendants(self):
        cats = self.categories.describe("Laptops")["matchedCategories"]
        self.output(cats, resolutions=[self.resolution("notebook", "category", "Laptops")])
        result = self.search.search("notebook under 50000")
        self.assertEqual(result["appliedFilters"]["categories"], cats)
        self.assertNotIn("fallbackReason", result)
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 1)

    def test_generic_synonym_cannot_select_only_the_generic_bucket(self):
        self.output(["Laptops"], resolutions=[self.resolution("notebook", "category", "Laptops")])
        result = self.search.search("notebook")
        self.assertEqual(result["fallbackReason"], "invalid_ai_output")

    def test_parent_label_evidence_keeps_a_requested_child_narrow(self):
        self.output(["Gaming Laptop"], resolutions=[self.resolution("notebook", "category", "Laptops"),
                                                   self.resolution("gaming", "category", "Gaming Laptop")])
        result = self.search.search("gaming notebook")
        self.assertEqual(result["appliedFilters"]["categories"], ["Gaming Laptop"])
        self.assertNotIn("fallbackReason", result)

    def test_unambiguous_category_typo_keeps_the_real_parent_scope(self):
        scope = self.categories.describe("Televsion")
        self.assertEqual(scope["canonicalCategory"], "Television")
        self.assertEqual(scope["matchedCategories"], self.categories.describe("Television")["matchedCategories"])

    def test_linux_category_requires_linux_even_under_windows_metadata(self):
        self.subtype("Linux Laptop")
        self.records(("1", "Windows Laptop", "HP Linux Laptop", "HP"),
                     ("2", "Windows Laptop", "HP Windows 11 Laptop", "HP"))
        result = self.search.search("show products", category="Linux Laptop")
        self.assertEqual([p["product_id"] for p in result["products"]], ["1"])
        self.assertIn("linux", result["appliedFilters"]["attributes"])
        self.assertEqual(result["alternatives"], [])

    def test_linux_in_query_returns_separately_labelled_alternatives(self):
        self.subtype("Linux Laptop")
        self.records(("1", "Windows Laptop", "HP Windows 11 Laptop", "HP"))
        result = self.search.search("Linux Laptop")
        self.assertEqual(result["products"], [])
        self.assertEqual(len(result["alternatives"]), 1)
        self.assertEqual(result["categoryResolution"]["status"], "alternatives")
        self.assertIn("do not meet", result["message"])
        self.assertIn("linux", result["categoryResolution"]["relaxedAttributes"])

    def test_alternatives_preserve_brand_budget_and_ram(self):
        scope = self.categories.describe("Linux Laptop")
        self.output(scope["matchedCategories"], ["linux", "16gb ram"],
                    [self.resolution("Linux Laptop", "category", *scope["matchedCategories"]),
                     self.resolution("Linux Laptop", "attribute", "linux"),
                     self.resolution("16gb ram", "attribute", "16gb ram")],
                    brands=["HP"], price_max=50000)
        self.records(("1", "Windows Laptop", "HP Windows Laptop 16GB RAM", "HP"),
                     ("2", "Windows Laptop", "HP Windows Laptop 8GB RAM", "HP"),
                     ("3", "Windows Laptop", "Asus Windows Laptop 16GB RAM", "Asus"),
                     ("4", "Windows Laptop", "HP Windows Laptop 16GB RAM Expensive", "HP"))
        self.fetch.side_effect = lambda pid, city: detail(pid, city, 60000 if str(pid) == "4" else 39999)
        result = self.search.search("HP 16gb ram under 50000", category="Linux Laptop")
        self.assertEqual(result["products"], [])
        self.assertEqual([p["product_id"] for p in result["alternatives"]], ["1"])
        self.assertEqual(result["appliedFilters"]["price_max"], 50000)

    def test_combined_linux_ram_attribute_is_never_relaxed_wholesale(self):
        self.subtype("Linux Laptop", ["linux 16gb ram"])
        self.ai.with_structured_output.return_value.invoke.return_value["resolutions"][-1]["source"] = "Linux Laptop 16gb ram"
        self.records(("1", "Windows Laptop", "HP Windows Laptop 8GB RAM", "HP"))
        result = self.search.search("Linux Laptop 16gb ram")
        self.assertEqual(result["alternatives"], [])

    def test_linux_timeout_cannot_return_windows_as_exact_results(self):
        self.ai.with_structured_output.return_value.invoke.side_effect = TimeoutError()
        self.records(("1", "Windows Laptop", "HP Windows 11 Laptop", "HP"))
        result = self.search.search("show products", category="Linux Laptop")
        self.assertEqual(result["products"], [])
        self.assertIn("linux", result["appliedFilters"]["attributes"])
        self.assertEqual(result["fallbackReason"], "ai_timeout")

    def test_display_resolution_is_not_a_price(self):
        for query in ("8K Ultra HD TV", "8K TV", "4K TV", "TV 8k"):
            with self.subTest(query=query):
                intent = deterministic(query, self.taxonomy)[0]
                self.assertIsNone(intent.price_max)
        self.assertEqual(deterministic("TV under 8k", self.taxonomy)[0].price_max, 8000)
        self.assertEqual(deterministic("8k TV under 50k", self.taxonomy)[0].price_max, 50000)

    def test_8k_tv_does_not_return_4k_as_a_match(self):
        self.subtype("8K Ultra HD TV")
        self.records(("1", "4K Ultra HD TV", "Samsung 4K Ultra HD TV", "Samsung"))
        result = self.search.search("show products", category="8K Ultra HD TV")
        self.assertEqual(result["products"], [])
        self.assertEqual(len(result["alternatives"]), 1)
        self.assertIsNone(result["appliedFilters"]["price_max"])

    def test_smart_tv_preserves_smart_requirement(self):
        self.subtype("Smart TV")
        self.records(("1", "HD LED TV", "Samsung Smart HD LED TV", "Samsung"),
                     ("2", "HD LED TV", "Samsung Basic HD LED TV", "Samsung"))
        result = self.search.search("show products", category="Smart TV")
        self.assertEqual([p["product_id"] for p in result["products"]], ["1"])

    def test_unsupported_category_returns_successful_empty_response(self):
        self.output([], ["Imaginary Device"], [self.resolution("Imaginary Device", "attribute", "Imaginary Device")],
                    category_status="unsupported")
        result = self.search.search("show products", category="Imaginary Device")
        self.assertEqual(result["products"], [])
        self.assertEqual(result["categoryResolution"]["status"], "unavailable")
        self.catalogue.index.query.assert_not_called()

    def test_ambiguous_function_requests_clarification(self):
        cats = ["Front Load Washing Machine", "Dishwasher"]
        self.output(cats, resolutions=[self.resolution("machine", "category", *cats)], category_status="ambiguous")
        result = self.search.search("show products", category="machine")
        self.assertTrue(result["clarificationRequired"])
        self.assertEqual(result["categoryResolution"]["suggestedCategories"], cats)
        self.catalogue.index.query.assert_not_called()

    def test_ambiguity_does_not_require_inventing_a_product_filter(self):
        self.output([], resolutions=[self.resolution("machine", "category", "machine")], category_status="ambiguous")
        result = self.search.search("machine under 50000")
        self.assertTrue(result["clarificationRequired"])
        self.assertEqual(result["appliedFilters"]["price_max"], 50000)
        self.assertNotIn("fallbackReason", result)
        self.assertEqual(self.ai.with_structured_output.return_value.invoke.call_count, 1)
        self.catalogue.index.query.assert_not_called()

    def test_ai_cannot_mark_a_clear_indexed_category_unsupported(self):
        self.output([], category_status="unsupported")
        result = self.search.search("gaming laptop")
        self.assertEqual(result["fallbackReason"], "invalid_ai_output")
        self.assertEqual(result["appliedFilters"]["categories"], ["Gaming Laptop"])

    def test_conflicting_selected_category_is_a_clarification(self):
        result = self.search.search("gaming laptop", category="Television")
        self.assertTrue(result["clarificationRequired"])
        self.catalogue.index.query.assert_not_called()
        self.ai.with_structured_output.assert_not_called()

    def test_conflicting_query_functions_reach_ai_for_clarification(self):
        self.output([], ["laptop", "tv"], [self.resolution("laptop", "attribute", "laptop"),
                                          self.resolution("tv", "attribute", "tv")], category_status="ambiguous")
        result = self.search.search("laptop tv")
        self.assertTrue(result["clarificationRequired"])
        self.assertNotIn("fallbackReason", result)
        self.catalogue.index.query.assert_not_called()

    def test_all_176_master_categories_have_graceful_endpoint_responses(self):
        self.catalogue.settings.namespace = json.loads(Path("smart_search_taxonomy.json").read_text(encoding="utf-8"))["namespace"]
        app = Flask(__name__)
        app.register_blueprint(create_smart_search_blueprint(self.catalogue, self.ai))
        client = app.test_client()
        for node in self.taxonomy["categoryTree"]:
            if not node["active"]:
                continue
            with self.subTest(category=node["name"]):
                scope = self.categories.describe(node["name"])
                attrs = scope["requiredTerms"]
                resolutions = ([self.resolution(node["name"], "category", *scope["matchedCategories"])]
                               if scope["matchedCategories"] else [])
                if attrs:
                    resolutions.append(self.resolution(node["name"], "attribute", *attrs))
                self.output(scope["matchedCategories"], attrs, resolutions)
                response = client.post("/smart/search", json={"query": "show products", "category": node["name"]})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["status"], "success")
                self.assertIn("categoryResolution", response.json["data"])

    def test_both_endpoint_paths_support_semantic_categories(self):
        cats = self.categories.describe("Laptops")["matchedCategories"]
        self.output(cats, resolutions=[self.resolution("notebook", "category", *cats)])
        self.catalogue.settings.namespace = json.loads(Path("smart_search_taxonomy.json").read_text(encoding="utf-8"))["namespace"]
        app = Flask(__name__)
        app.register_blueprint(create_smart_search_blueprint(self.catalogue, self.ai))
        for path in ("/smart/search", "/api/search/smart"):
            response = app.test_client().post(path, json={"query": "show products", "category": "notebook"})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["data"]["clarificationRequired"])


if __name__ == "__main__":
    unittest.main()
