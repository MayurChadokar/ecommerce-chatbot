import json
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from chat_fast_path import fast_budget_recommendation, parse_budget_range


class BudgetParserTests(unittest.TestCase):
    def test_around_is_a_real_range_not_an_exact_price(self):
        value = parse_budget_range("best options around 50,000")
        self.assertEqual((value.minimum, value.maximum), (45000, 55000))

    def test_k_lakh_and_between(self):
        self.assertEqual(parse_budget_range("under 50k").maximum, 50000)
        value = parse_budget_range("between Rs 0.4 lakh and 60k")
        self.assertEqual((value.minimum, value.maximum), (40000, 60000))


class FastRecommendationTests(unittest.TestCase):
    def test_uses_recent_category_and_both_around_bounds(self):
        search = MagicMock()
        search.search_products.return_value = [{"product_id": "7"}]
        search.format_results.return_value = json.dumps(
            {"products": [{"product_id": "7", "product_name": "Phone"}]})
        module = ModuleType("tools.product_search_tool")
        module.product_search_instance = search
        with patch.dict("sys.modules", {"tools.product_search_tool": module}):
            response = fast_budget_recommendation(
                "suggest me some of the best options around 50,000", ["show me smartphones"])
        search.search_products.assert_called_once_with(
            query="best smartphone", top_k=5, price_min=45000,
            price_max=55000, city="INDORE", category="smartphone")
        self.assertEqual(response["recommendations"][0]["product_id"], "7")
        self.assertIn("\u20b945,000\u2013\u20b955,000", response["answer"])

    def test_ambiguous_request_stays_on_agent_path(self):
        self.assertIsNone(fast_budget_recommendation("suggest something around 50,000"))


if __name__ == "__main__":
    unittest.main()
