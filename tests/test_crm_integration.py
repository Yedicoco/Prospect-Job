import sqlite3
import unittest

from crm_integration import prepare_and_reserve
from crm_storage import migrate


class CRMIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        migrate(self.connection)
        self.record = {"email": "contact@example.com", "tel": "0661887766"}

    def tearDown(self):
        self.connection.close()

    def test_action_is_reserved_and_audited_atomically(self):
        prepared = prepare_and_reserve(
            self.connection,
            self.record,
            entity_type="prospect",
            entity_id=12,
            action="followup",
            step=3,
            actor="operator",
            now="2026-10-25T00:00:00+00:00",
        )
        self.assertTrue(prepared.allowed)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM crm_idempotency").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
            1,
        )

    def test_duplicate_action_is_rejected_without_duplicate_audit(self):
        kwargs = {
            "entity_type": "prospect",
            "entity_id": 12,
            "action": "followup",
            "step": 3,
            "actor": "operator",
            "now": "2026-10-25T00:00:00+00:00",
        }
        self.assertTrue(prepare_and_reserve(self.connection, self.record, **kwargs).allowed)
        duplicate = prepare_and_reserve(self.connection, self.record, **kwargs)
        self.assertFalse(duplicate.allowed)
        self.assertIn("Action déjà réservée", duplicate.errors)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
            1,
        )

    def test_invalid_contact_does_not_write(self):
        result = prepare_and_reserve(
            self.connection,
            {},
            entity_type="prospect",
            entity_id=12,
            action="followup",
            actor="operator",
        )
        self.assertFalse(result.allowed)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM crm_idempotency").fetchone()[0],
            0,
        )


if __name__ == "__main__":
    unittest.main()
