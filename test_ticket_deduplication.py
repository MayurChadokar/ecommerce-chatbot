import os
import unittest
import uuid
from contextlib import closing
from unittest.mock import patch

import store
from tools.ticket_tools import DUPLICATE_TICKET_MESSAGE, normalize_ticket_response


class TicketDeduplicationTests(unittest.TestCase):
    def ticket_count(self):
        with closing(store._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]

    def setUp(self):
        self.db_path = os.path.join(
            os.path.dirname(__file__), f"test-tickets-{uuid.uuid4().hex}.db")
        self.db_patch = patch.object(store, "DB_PATH", self.db_path)
        self.db_patch.start()
        store.init_db()

    def tearDown(self):
        self.db_patch.stop()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_same_mobile_only_creates_one_ticket_per_day(self):
        first = store.create_ticket("one", "Rahul", "98765 43210", "TV screen flickering")
        second = store.create_ticket("two", "Rahul", "+91-98765-43210", "TV will not start")

        self.assertFalse(first.get("duplicate", False))
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["ticket_id"], first["ticket_id"])
        self.assertEqual(self.ticket_count(), 1)

    def test_today_lookup_normalises_country_code_and_separators(self):
        first = store.create_ticket(
            "one", "Rahul", "98765 43210", "TV screen flickering")

        found = store.get_todays_ticket_by_phone("+91-98765-43210")

        self.assertEqual(found["ticket_id"], first["ticket_id"])

    def test_different_mobile_can_create_ticket_same_day(self):
        first = store.create_ticket("one", "Rahul", "9876543210", "TV screen flickering")
        second = store.create_ticket("two", "Aman", "8765432109", "AC is not cooling")

        self.assertNotEqual(second["ticket_id"], first["ticket_id"])
        self.assertEqual(self.ticket_count(), 2)

    def test_sales_enquiry_does_not_block_support_ticket(self):
        sales = store.create_ticket(
            "sales", "Rahul", "9876543210", "Sales Enquiry")
        support = store.create_ticket(
            "support", "Rahul", "9876543210", "TV screen flickering")

        self.assertNotEqual(support["ticket_id"], sales["ticket_id"])
        self.assertFalse(support.get("duplicate", False))

    def test_duplicate_response_does_not_expose_ticket_as_new(self):
        duplicate = {
            "ticket_id": "TCKT-001001", "phone": "9876543210",
            "duplicate": True,
        }
        response = normalize_ticket_response(
            {"answer": "made up", "ticket": {"ticket_id": "TCKT-999999"}},
            duplicate, "please raise it",
        )

        self.assertNotIn("ticket", response)
        self.assertEqual(response["answer"], DUPLICATE_TICKET_MESSAGE)


if __name__ == "__main__":
    unittest.main()
