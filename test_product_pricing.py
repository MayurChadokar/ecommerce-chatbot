"""Offline tests for authoritative MRP/selling price propagation."""
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from product_pricing import price_number, pricing_fields, pricing_metadata
from product_index import EMBEDDING_MODEL
from scripts.extract_products import extract
from scripts.backfill_product_prices import validate_additions

with patch.dict(os.environ, {'ENABLE_VECTOR_SEARCH': 'false'}):
    from tools.product_search_tool import ProductSearchTool


class PricingTests(unittest.TestCase):
    def test_confirmed_storefront_mapping_keeps_conditional_offer_separate(self):
        fields = pricing_fields({'product_msrp': '25999', 'product_mrp': '23499', 'eff_price': '21999', 'wprice2': '22999'})
        self.assertEqual(fields, {'mrp': 25999, 'selling_price': 23499, 'store_offer_price': 21999,
                                 'discount_amount': 2500, 'discount_percent': 9.6})

    def test_missing_mrp_does_not_invent_discount(self):
        self.assertEqual(pricing_fields({'price': 1000, 'price_field': 'product_mrp'}), {'selling_price': 1000})
        self.assertEqual(pricing_fields({'price': 1000}), {})

    def test_equal_and_reversed_prices(self):
        self.assertEqual(pricing_fields({'product_msrp': 100, 'product_mrp': 100})['discount_amount'], 0)
        self.assertNotIn('discount_amount', pricing_fields({'product_msrp': 100, 'product_mrp': 200}))

    def test_numeric_validation_and_paise(self):
        self.assertEqual(price_number('₹1,00,000.50'), 100000.5)
        for value in (None, True, False, 0, -1, 'NaN', float('inf'), '<script>', 'Call for price'):
            self.assertIsNone(price_number(value))
        self.assertEqual(pricing_fields({'mrp': 100.50, 'selling_price': 99.25})['discount_amount'], 1.25)

    def test_extractor_retains_all_source_prices_without_changing_selected_price(self):
        sql = "INSERT INTO `les_products` (`product_id`,`product_name`,`uri_slug`,`status`,`web_display`,`product_mrp`,`product_msrp`,`eff_price`,`wprice2`) VALUES (7,'Phone','phone','Active','YES',23499,25999,21999,22999);\n"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path = Path(folder) / 'fixture.sql'
            path.write_text(sql, encoding='utf-8')
            records, _ = extract(path)
        metadata = records[0]['metadata']
        self.assertEqual(metadata['price'], 23499)
        self.assertEqual(metadata['price_field'], 'product_mrp')
        self.assertEqual(metadata['mrp'], 25999)
        self.assertEqual(metadata['selling_price'], 23499)
        self.assertEqual(metadata['discount_amount'], 2500)
        self.assertEqual(metadata['store_offer_price'], 21999)

    def test_pinecone_record_and_public_response_keep_price_fields(self):
        meta = {'product_name': 'Phone', 'url': 'phone', 'price': 23499, 'price_field': 'product_mrp',
                'source': 'sql_snapshot', 'embedding_model': EMBEDDING_MODEL,
                **pricing_metadata({'product_msrp': 25999, 'product_mrp': 23499})}
        record = ProductSearchTool._record('7', meta)
        tool = ProductSearchTool.__new__(ProductSearchTool)
        tool.last_error = None
        product = json.loads(tool.format_results([record]))['products'][0]
        self.assertEqual(product['mrp'], 25999)
        self.assertEqual(product['selling_price'], 23499)
        self.assertEqual(product['discount_amount'], 2500)
        self.assertEqual(product['product_mrp'], '₹23,499')

    def test_cached_products_preserve_pricing_for_comparison(self):
        import catalog
        product = {'product_id': 'pricing-test', 'product_name': 'Phone', 'product_mrp': '₹23,499',
                   'mrp': 25999, 'selling_price': 23499}
        try:
            catalog.remember_products([product])
            seen = catalog.get_seen('pricing-test')
            result = catalog.build_comparison(seen, seen)
            self.assertEqual(result['mrp_a'], 25999)
            self.assertEqual(result['selling_price_b'], 23499)
            self.assertEqual(result['discount_amount_a'], 2500)
        finally:
            catalog._SEEN.pop('pricing-test', None)

    def test_additive_update_guard_and_idempotency(self):
        original = {'price': 23499, 'product_name': 'Phone'}
        additions = pricing_metadata({'product_msrp': 25999, 'product_mrp': 23499})
        validate_additions(original, original, additions)
        validate_additions({**original, **additions}, original, additions)
        with self.assertRaises(ValueError):
            validate_additions({**original, 'price': 1}, original, additions)
        with self.assertRaises(ValueError):
            validate_additions({**original, 'mrp': 1}, original, additions)


if __name__ == '__main__':
    unittest.main()
