import sqlite3
import unittest

from crm_quality import transition_event
from crm_storage import audit_events, migrate, record_audit, reserve_idempotency, mark_idempotency_result


class CRMStorageTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        migrate(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_migration_is_idempotent(self):
        migrate(self.connection)
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("audit_events", tables)
        self.assertIn("crm_idempotency", tables)

    def test_audit_event_is_persisted_with_parameters(self):
        event = transition_event(
            entity_type="prospect",
            entity_id=12,
            current="contacte",
            target="repondu",
            actor="operator",
            reason="Réponse reçue",
            occurred_at="2026-10-25T00:00:00+00:00",
        )
        event_id = record_audit(self.connection, event)
        self.assertGreater(event_id, 0)
        rows = audit_events(self.connection, entity_type="prospect", entity_id=12)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["new_value"], "repondu")
        self.assertEqual(rows[0]["reason"], "Réponse reçue")

    def test_idempotency_reservation_only_succeeds_once(self):
        kwargs = {
            "idempotency_key": "stable-key",
            "entity_type": "prospect",
            "entity_id": 12,
            "action": "followup",
            "step": 3,
            "created_at": "2026-10-25T00:00:00+00:00",
        }
        self.assertTrue(reserve_idempotency(self.connection, **kwargs))
        self.assertFalse(reserve_idempotency(self.connection, **kwargs))
        mark_idempotency_result(self.connection, "stable-key", "queued")
        result = self.connection.execute(
            "SELECT result FROM crm_idempotency WHERE idempotency_key=?",
            ("stable-key",),
        ).fetchone()[0]
        self.assertEqual(result, "queued")

    def test_unknown_idempotency_key_cannot_be_marked(self):
        with self.assertRaises(KeyError):
            mark_idempotency_result(self.connection, "missing", "sent")


if __name__ == "__main__":
    unittest.main()
