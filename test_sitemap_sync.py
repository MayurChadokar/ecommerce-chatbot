import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from scripts.sync_sitemap_to_pinecone import detail_record, missing_ids, sitemap_products


class SitemapSyncTests(unittest.TestCase):
    def test_extracts_only_valid_lotus_product_urls(self):
        xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://www.lotuselectronics.com/product/iphones/apple-phone/42365</loc><lastmod>2026-11-25</lastmod></url>
          <url><loc>https://www.lotuselectronics.com/contact-us</loc></url>
          <url><loc>https://evil.example/product/x/9</loc></url>
        </urlset>"""
        self.assertEqual(sitemap_products(xml), {
            "42365": {"url": "https://www.lotuselectronics.com/product/iphones/apple-phone/42365",
                      "lastmod": "2026-11-25"}
        })

    def test_finds_missing_ids_in_batches(self):
        index = Mock()
        index.fetch.side_effect = [SimpleNamespace(vectors={"1": object()}),
                                   SimpleNamespace(vectors={"3": object(), "4": object()})]
        self.assertEqual(missing_ids(index, "live", {"1", "2", "3", "4"}, batch_size=2), ["2"])

    def test_builds_runtime_compatible_metadata(self):
        entry = {"url": "https://www.lotuselectronics.com/product/iphones/apple-phone/42365",
                 "lastmod": "2026-11-25"}
        detail = {"product_id": "42365", "product_name": "Apple iPhone 17 512GB",
                  "product_mrp": "99999", "product_msrp": "109999", "brand_name": "Apple",
                  "cat_name": "iPhones", "product_sku": "ABC17", "instock": "Yes",
                  "product_specification": [{"fkey": "Storage", "fvalue": "512GB"}]}
        record = detail_record("42365", entry, detail)
        self.assertEqual(record["metadata"]["price"], 99999.0)
        self.assertEqual(record["metadata"]["sync_source"], "website_sitemap")
        self.assertIn("iPhone 17", record["metadata"]["text"])


if __name__ == "__main__":
    unittest.main()
