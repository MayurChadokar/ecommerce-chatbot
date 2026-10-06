"""Offline regression tests: python -m unittest test_product_index -v"""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from product_index import EMBEDDING_MODEL, IndexSettings, connect_index, product_url
from scripts.extract_products import ValuesParser, clean, extract, iter_product_rows
from scripts.pinecone_products import load_records, validate_upload

with patch.dict(os.environ, {"ENABLE_VECTOR_SEARCH": "false"}):
    from tools.product_search_tool import ProductSearchTool
    from tools.browse_catalog import browse_catalog_tool
    from tools.recommend_products import recommend_products_tool


def metadata(pid="7"):
    return {"product_id": pid, "product_name": "Real phone", "url": "real-phone",
            "product_url": product_url("real-phone", pid), "text": "Real phone specifications",
            "price": 14999, "price_field": "product_mrp", "source": "sql_snapshot",
            "embedding_model": EMBEDDING_MODEL, "features": ["RAM: 8GB"]}


class SqlParserTests(unittest.TestCase):
    def test_quoted_delimiters_escapes_null_and_hex(self):
        parser = ValuesParser()
        rows = list(parser.feed("(1,'Bob\\'s phone, (new);',NULL,0x4142),\n"))
        rows += list(parser.feed("(2,'it''s fine','a\\nb',-1.5);"))
        self.assertTrue(parser.done)
        self.assertEqual(rows[0], ["1", "Bob's phone, (new);", None, "AB"])
        self.assertEqual(rows[1], ["2", "it's fine", "a\nb", "-1.5"])

    def test_chunk_boundary_inside_string(self):
        parser = ValuesParser()
        self.assertEqual(list(parser.feed("('phone'")), [])
        self.assertEqual(list(parser.feed("'s',3);")), [["phone's", "3"]])

    def test_sql_expressions_rejected(self):
        with self.assertRaises(ValueError):
            list(ValuesParser().feed("(1,LOAD_FILE('/private'));"))

    def test_allowlist_does_not_export_users_or_backups(self):
        dump = ("INSERT INTO `les_user` (`id`,`email`) VALUES (1,'private@example.test');\n"
                "INSERT INTO `les_products_backup` (`product_id`) VALUES (999);\n"
                "INSERT INTO `les_products` (`product_id`,`product_name`) VALUES (7,'Phone');\n")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path = Path(folder) / "fixture.sql"
            path.write_text(dump, encoding="utf-8")
            rows = list(iter_product_rows(path))
        self.assertEqual(rows, [("les_products", {"product_id": "7", "product_name": "Phone"})])

    def test_truncated_statement_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path = Path(folder) / "fixture.sql"
            path.write_text("INSERT INTO `les_products` (`product_id`) VALUES (7)", encoding="utf-8")
            with self.assertRaises(ValueError):
                list(iter_product_rows(path))

    def test_extract_joins_filters_and_does_not_fallback_price(self):
        dump = """INSERT INTO `les_products` (`product_id`,`product_name`,`uri_slug`,`status`,`web_display`,`product_mrp`,`eff_price`,`product_brand`,`cat_id`,`product_image`) VALUES
(7,'Phone','phone','Active','YES',10000,9000,2,3,'https://cdn.example.test/p.webp'),
(8,'Old','old','Inactive','YES',10000,9000,2,3,NULL),
(9,'Hidden','hidden','Active','NO',10000,9000,2,3,NULL),
(10,'No price','no-price','Active','YES',0,9000,2,3,NULL);
INSERT INTO `les_brand` (`brand_id`,`brand_name`,`contact_no`) VALUES (2,'Brand','private-contact');
INSERT INTO `les_category` (`cat_id`,`cat_name`) VALUES (3,'Smartphones');
INSERT INTO `les_product_features` (`pid`,`f_name`,`f_value`) VALUES (7,'RAM','8GB');
"""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path = Path(folder) / "fixture.sql"
            path.write_text(dump, encoding="utf-8")
            records, report = extract(path)
        self.assertEqual(len(records), 1)
        record = records[0]["metadata"]
        self.assertEqual(record["brand"], "Brand")
        self.assertEqual(record["category"], "Smartphones")
        self.assertEqual(record["price"], 10000)
        self.assertEqual(record["features"], ["RAM: 8GB"])
        self.assertNotIn("private-contact", json.dumps(records))
        self.assertEqual(report["skipped"]["missing_positive_selected_price"], 1)

    def test_html_cleaning(self):
        self.assertEqual(clean("<p>8GB&nbsp;RAM</p><script>steal()</script>"), "8GB RAM")


class ConfigAndVectorTests(unittest.TestCase):
    def test_missing_config_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "PINECONE_API_KEY"):
                IndexSettings.from_env()

    def test_rejects_non_pinecone_host(self):
        env = dict(PINECONE_API_KEY="test", PINECONE_INDEX_NAME="test",
                   PINECONE_HOST="https://attacker.example", PINECONE_NAMESPACE="products")
        with patch.dict(os.environ, env):
            with self.assertRaises(ValueError):
                IndexSettings.from_env()

    def test_product_link(self):
        self.assertEqual(product_url("real-phone", "7"),
                         "https://www.lotuselectronics.com/product/real-phone/7")
        self.assertEqual(product_url("javascript:bad/slug", "7"), "")
        self.assertEqual(product_url("https://attacker.example/product/p/7", "7"), "")
        self.assertEqual(product_url("", "7"), "")
        self.assertEqual(product_url("iphones/real-phone", "7"),
                         "https://www.lotuselectronics.com/product/iphones/real-phone/7")
        for slug in ("../phone", "iphones/../phone", "/iphones/phone", "iphones//phone", "iphones/phone?x=1"):
            self.assertEqual(product_url(slug, "7"), "")

    def test_integrated_model_is_rejected_even_with_same_dimension(self):
        desc = SimpleNamespace(host="https://test.svc.pinecone.io", dimension=384,
                               metric="cosine", vector_type="dense", embed={"model": "llama"})
        with patch("pinecone.Pinecone") as client:
            client.return_value.describe_index.return_value = desc
            with self.assertRaisesRegex(ValueError, "integrated"):
                connect_index(IndexSettings("test", "test", desc.host, "products"))
            client.return_value.Index.assert_not_called()

    def test_vectors_validate_dimension_and_model(self):
        record = {"id": "7", "metadata": metadata(), "values": [0.1] * 384}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path = Path(folder) / "vectors.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            self.assertEqual(len(load_records(path, vectors=True)), 1)
            record["values"] = [0.1] * 383
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(path, vectors=True)

    def test_price_confirmation_must_match(self):
        with self.assertRaises(ValueError):
            validate_upload([{"metadata": metadata()}], "eff_price")
        validate_upload([{"metadata": metadata()}], "product_mrp")


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.search = ProductSearchTool.__new__(ProductSearchTool)
        self.search.settings = SimpleNamespace(namespace="test-products")
        self.search.index = MagicMock()
        self.search.model = MagicMock()
        self.search.model.encode.return_value.tolist.return_value = [0.1] * 384
        self.search.is_available = True
        self.search.last_error = None

    def test_search_filters_server_side_and_preserves_source_url(self):
        self.search.index.query.return_value.matches = [
            SimpleNamespace(id="7", score=0.9, metadata=metadata())]
        results = self.search.search_products("phone", price_max=20000)
        kwargs = self.search.index.query.call_args.kwargs
        self.assertEqual(kwargs["namespace"], "test-products")
        self.assertEqual(kwargs["filter"]["price"], {"$lte": 20000})
        result = json.loads(self.search.format_results(results))
        self.assertEqual(result["products"][0]["product_url"], metadata()["product_url"])
        self.assertEqual(result["products"][0]["features"], ["RAM: 8GB"])

    def test_no_fabricated_features(self):
        data = metadata()
        data.pop("features")
        record = self.search._record("7", data)
        self.assertEqual(json.loads(self.search.format_results([record]))["products"][0]["features"], [])

    def test_iphone_generation_accepts_catalogue_mobile_word(self):
        titles = ["Apple iPhone Mobile 18 Pro (1TB ROM) Black",
                  "Apple iPhone 18 Pro (256GB ROM) Silver",
                  "Apple iPhone Mobile 17 Pro Black", "Apple iPad Pro 18"]
        self.search.index.query.return_value.matches = [
            SimpleNamespace(id=str(i), score=.9, metadata={**metadata(str(i)), "product_name": title})
            for i, title in enumerate(titles)]
        with patch.dict(os.environ, {"LOTUS_LIVE_ENRICHMENT": "false"}):
            results = self.search.search_products("iphone 18 pro")
        self.assertEqual([r["product_name"] for r in results], titles[:2])
        self.assertEqual(json.loads(self.search.format_results(results))["total_found"], 2)

    def test_iphone_variant_does_not_substitute_another_model(self):
        titles = ["Apple iPhone Mobile 18 Pro", "Apple iPhone Mobile 18 Pro Max",
                  "Apple iPhone Mobile 18", "Apple iPhone Mobile 18 Air",
                  "Apple iPhone Mobile 17 Pro"]
        records = [{"product_name": title} for title in titles]
        for query, expected in (("iphone 18", titles[:4]), ("iphone 18 pro", titles[:1]),
                                ("iphone 18 pro max", titles[1:2]), ("iphone 18 air", titles[3:4]),
                                ("iphone 19 pro", []), ("IPHONE MOBILE 18 PRO?", titles[:1])):
            with self.subTest(query=query):
                filtered = self.search._apply_query_intent_filter(records, query)
                self.assertEqual([r["product_name"] for r in filtered], expected)

    def test_failure_returns_error_not_empty_success(self):
        self.search.index.query.side_effect = RuntimeError("private request details")
        self.assertEqual(self.search.search_products("phone"), [])
        result = json.loads(self.search.format_results([]))
        self.assertEqual(result["error_code"], "product_search_unavailable")
        self.assertNotIn("private", result["error"])

    def test_disabled_browse_and_recommend_do_not_call_demo_catalog(self):
        self.search.is_available = False
        self.search.last_error = "Not configured"
        with patch("catalog.browse", side_effect=AssertionError("demo called")), \
             patch("catalog.recommend", side_effect=AssertionError("demo called")), \
             patch("tools.browse_catalog.product_search_instance", self.search), \
             patch("tools.recommend_products.product_search_instance", self.search):
            self.assertIn("error", browse_catalog_tool.invoke({"category": "phone"}))
            self.assertIn("error", recommend_products_tool.invoke({"category": "phone"}))

    def test_similar_recommendation_excludes_original(self):
        self.search.index.fetch.return_value.vectors = {"7": SimpleNamespace(metadata=metadata())}
        self.search.index.query.return_value.matches = [
            SimpleNamespace(id="7", score=1.0, metadata=metadata()),
            SimpleNamespace(id="8", score=0.9, metadata=metadata("8"))]
        with patch("tools.recommend_products.product_search_instance", self.search):
            products = recommend_products_tool.invoke({"based_on_product_id": 7})
        self.assertEqual([p["product_id"] for p in products], ["8"])


if __name__ == "__main__":
    unittest.main()
