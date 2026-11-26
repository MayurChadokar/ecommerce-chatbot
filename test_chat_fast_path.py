import json
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from chat_fast_path import (fast_budget_recommendation, fast_model_code_search,
                            fast_replacement_policy, fast_return_policy,
                            fast_unclear_message, parse_budget_range)


class ReplacementPolicyTests(unittest.TestCase):
    def test_replacement_policy_is_available_without_external_search(self):
        response = fast_replacement_policy("what is the replacement policy of lotus")
        self.assertIsNotNone(response)
        self.assertNotIn("24 hours", response["answer"])
        self.assertNotIn("7 days", response["answer"])
        self.assertNotIn("7-day", response["answer"])
        self.assertIn("return-policy", response["answer"])
        self.assertNotIn("unable to access", response["answer"].lower())

    def test_unrelated_question_stays_on_normal_path(self):
        self.assertIsNone(fast_replacement_policy("show me a washing machine"))

    def test_return_policy_does_not_quote_a_time_period(self):
        response = fast_return_policy("what is the return policy?")
        self.assertIsNotNone(response)
        self.assertNotRegex(response["answer"], r"\b(?:hour|hours|day|days|week|weeks)\b")
        self.assertIn("original packaging", response["answer"])


class UnclearMessageTests(unittest.TestCase):
    def test_mixed_hindi_and_keyboard_junk_is_handled_locally(self):
        message = ("g7mgsm nuggr pomkmlkpl vkmvvvbn mom hgmhbgpmolo. xrzgg m "
                   "nvdm m bvbv vhnvvn b mlmb nbbnnbn, zsrn हाँ m. सब बन नजर")
        response = fast_unclear_message(message)
        self.assertIsNotNone(response)
        self.assertIn("आपका संदेश स्पष्ट नहीं है", response["answer"])

    def test_latin_hinglish_junk_gets_english_default(self):
        response = fast_unclear_message(
            "nuggr pomkmlkpl vkmvvvbn hgmhbgpmolo xrzgg nvdm vhnvvn nbbnnbn")
        self.assertIsNotNone(response)
        self.assertEqual(
            response["answer"],
            "Your message was not clear. Please describe your product or support question in a little more detail.")

    def test_short_latin_keyboard_junk_gets_english_default(self):
        response = fast_unclear_message(", yrsegsy. Z nnk. M")
        self.assertIsNotNone(response)
        self.assertTrue(response["answer"].startswith("Your message was not clear"))

    def test_valid_hindi_and_hinglish_are_not_blocked(self):
        valid_messages = [
            "भाई मुझे पचास हजार में अच्छा laptop बताओ",
            "bhai mujhe Samsung S24 ka price batao",
            "washing machine chahiye Indore me",
        ]
        for message in valid_messages:
            with self.subTest(message=message):
                self.assertIsNone(fast_unclear_message(message))

    def test_product_model_code_is_not_blocked(self):
        self.assertIsNone(fast_unclear_message("Samsung QA55Q60DAULXL price"))


class ModelCodeSearchTests(unittest.TestCase):
    @patch("tools.product_search_tool.product_search_instance")
    def test_single_f35_query_searches_without_llm(self, search):
        search.search_products.return_value = [{"product_id": "43253"}]
        search.format_results.return_value = json.dumps({
            "products": [{"product_id": "43253", "product_name": "Oppo F35 5G"}]
        })
        response = fast_model_code_search("f35", city="INDORE")
        search.search_products.assert_called_once_with("f35", top_k=5, city="INDORE")
        self.assertEqual(response["products"][0]["product_id"], "43253")

    def test_sentence_stays_on_normal_agent_path(self):
        self.assertIsNone(fast_model_code_search("show me an f35 phone"))


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
