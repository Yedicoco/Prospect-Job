import unittest
from datetime import date

from crm_quality import (
    audit_insert_sql,
    prepare_action,
    prospect_identity,
    transition_event,
)


class CRMQualityIntegrationTests(unittest.TestCase):
    def test_prepare_action_normalizes_contact_scores_and_is_idempotent(self):
        record = {
            "name": "Hotel Atlas",
            "city": "Rabat",
            "email": " CONTACT@Example.COM ",
            "tel": "0661887766",
            "niveau": "A",
            "besoin_confirme": True,
            "date_derniere_verification": "2026-10-24",
        }
        prepared = prepare_action(
            record,
            entity_type="prospect",
            entity_id=12,
            action="followup",
            step=3,
            today=date(2026, 10, 24),
        )
        same = prepare_action(
            record,
            entity_type="PROSPECT",
            entity_id="12",
            action="FOLLOWUP",
            step="3",
            today=date(2026, 10, 24),
        )
        self.assertTrue(prepared.allowed)
        self.assertEqual(prepared.contact.email, "contact@example.com")
        self.assertEqual(prepared.contact.phone, "+212661887766")
        self.assertIsNotNone(prepared.score)
        self.assertEqual(prepared.idempotency_key, same.idempotency_key)

    def test_prepare_action_blocks_opt_out(self):
        prepared = prepare_action(
            {"email": "contact@example.com", "opt_out": True},
            entity_type="prospect",
            entity_id=1,
            action="contact",
        )
        self.assertFalse(prepared.allowed)
        self.assertIn("Action sortante interdite pour un opt-out", prepared.errors)

    def test_prepare_action_rejects_missing_contact(self):
        prepared = prepare_action(
            {}, entity_type="prospect", entity_id=1, action="contact"
        )
        self.assertFalse(prepared.allowed)
        self.assertIn("Email, téléphone ou WhatsApp requis", prepared.errors)

    def test_identity_is_stable_across_phone_formatting(self):
        first = prospect_identity({"name": "Atlas", "city": "Rabat", "tel": "0661887766"})
        second = prospect_identity({"name": "Other", "city": "Rabat", "tel": "+212 661 88 77 66"})
        self.assertEqual(first, second)

    def test_transition_event_is_auditable(self):
        event = transition_event(
            entity_type="prospect",
            entity_id=12,
            current="contacte",
            target="repondu",
            actor="operator-1",
            reason="Réponse WhatsApp",
            occurred_at="2026-10-24T10:00:00+00:00",
        )
        sql, params = audit_insert_sql(event)
        self.assertIn("INSERT INTO audit_events", sql)
        self.assertEqual(params[1], "12")
        self.assertEqual(params[5:7], ("contacte", "repondu"))

    def test_transition_event_rejects_invalid_transition(self):
        with self.assertRaises(ValueError):
            transition_event(
                entity_type="prospect",
                entity_id=12,
                current="opt_out",
                target="contacte",
                actor="operator-1",
            )


if __name__ == "__main__":
    unittest.main()
