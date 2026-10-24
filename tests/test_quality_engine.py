import unittest
from datetime import date

from quality_engine import (
    NormalizedContact,
    action_idempotency_key,
    contact_identity,
    freshness_factor,
    normalize_contact,
    normalize_phone,
    prospect_deduplication_key,
    realized_mad_per_hour,
    realized_roi,
    score_prospect,
    transition_allowed,
    validate_contact_record,
    validate_transition,
)


class QualityEngineTests(unittest.TestCase):
    def test_normalizes_moroccan_phone_variants_to_same_identity(self):
        self.assertEqual(normalize_phone("06 61 88 77 66"), "+212661887766")
        self.assertEqual(normalize_phone("+212 661 88 77 66"), "+212661887766")
        self.assertEqual(normalize_phone("00212 661 88 77 66"), "+212661887766")

    def test_normalized_contact_preserves_whatsapp(self):
        contact = normalize_contact(
            " CONTACT@Example.COM ", "0661887766", "+212661887766"
        )
        self.assertEqual(contact.email, "contact@example.com")
        self.assertEqual(contact.phone, "+212661887766")
        self.assertEqual(contact.whatsapp, "+212661887766")
        self.assertEqual(contact_identity(contact), "contact@example.com")

    def test_deduplication_prefers_contact_identity(self):
        contact = NormalizedContact(email="contact@example.com")
        self.assertEqual(
            prospect_deduplication_key(name="Hotel Atlas", city="Rabat", contact=contact),
            "contact:contact@example.com",
        )

    def test_deduplication_falls_back_to_organization_identity(self):
        self.assertEqual(
            prospect_deduplication_key(
                name="  Hotel   Atlas ", city=" Rabat ", domain="www.hotel-atlas.ma"
            ),
            "org:hotel atlas|rabat|hotel-atlas.ma",
        )

    def test_freshness_decays_and_future_dates_are_not_trusted(self):
        reference = date(2026, 10, 24)
        self.assertEqual(freshness_factor(reference, today=reference), 1.0)
        self.assertEqual(freshness_factor(date(2026, 10, 10), today=reference), 0.5)
        self.assertEqual(freshness_factor(date(2026, 10, 25), today=reference), 0.0)

    def test_score_is_bounded_and_explainable(self):
        score = score_prospect(
            {
                "email": "contact@example.com",
                "niveau": "A",
                "besoin_confirme": True,
                "date_derniere_verification": "2026-10-24",
                "value_score": 90,
            },
            today=date(2026, 10, 24),
        )
        self.assertGreater(score.total, 0)
        self.assertLessEqual(score.total, 100)
        self.assertIn("Besoin confirmé", score.reasons)

    def test_opt_out_is_visible_as_warning(self):
        score = score_prospect(
            {"email": "contact@example.com", "opt_out": True},
            today=date(2026, 10, 24),
        )
        self.assertIn("Opt-out actif", score.warnings)

    def test_state_machine_rejects_invalid_transition(self):
        self.assertTrue(transition_allowed("nouveau", "qualifie"))
        self.assertFalse(transition_allowed("opt_out", "contacte"))
        with self.assertRaises(ValueError):
            validate_transition("opt_out", "contacte")

    def test_idempotency_key_is_stable(self):
        first = action_idempotency_key(
            entity_type="prospect", entity_id=12, action="followup", step=3
        )
        second = action_idempotency_key(
            entity_type="PROSPECT", entity_id="12", action="FOLLOWUP", step="3"
        )
        self.assertEqual(first, second)

    def test_realized_roi_uses_received_revenue(self):
        self.assertEqual(realized_roi(1200, 300), 900)
        self.assertEqual(realized_mad_per_hour(900, 90), 600.0)
        self.assertIsNone(realized_mad_per_hour(900, 0))

    def test_contact_validation_returns_normalized_data(self):
        result = validate_contact_record({"tel": "0661887766"})
        self.assertTrue(result.valid)
        self.assertEqual(result.normalized.phone, "+212661887766")

    def test_contact_validation_rejects_empty_record(self):
        result = validate_contact_record({})
        self.assertFalse(result.valid)
        self.assertIn("Email, téléphone ou WhatsApp requis", result.errors)


if __name__ == "__main__":
    unittest.main()
