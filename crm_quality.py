"""Façade d'intégration entre les opérations CRM et ``quality_engine``.

Cette couche fournit un seam stable pour intégrer progressivement les routes
web et les opérations SQLite sans dupliquer les règles métier dans plusieurs
handlers. Elle ne réalise aucun envoi externe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from quality_engine import (
    LeadScore,
    NormalizedContact,
    action_idempotency_key,
    normalize_contact,
    prospect_deduplication_key,
    score_prospect,
    validate_contact_record,
    validate_transition,
)


@dataclass(frozen=True)
class AuditEvent:
    entity_type: str
    entity_id: str
    action: str
    actor: str
    occurred_at: str
    old_value: str = ""
    new_value: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "action": self.action,
            "actor": self.actor,
            "occurred_at": self.occurred_at,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PreparedAction:
    allowed: bool
    action: str
    idempotency_key: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    contact: NormalizedContact = NormalizedContact()
    score: LeadScore | None = None


def normalize_prospect_contact(record: Mapping[str, object]) -> NormalizedContact:
    """Retourne les coordonnées normalisées d'une fiche CRM."""
    return normalize_contact(
        str(record.get("email", "")),
        str(record.get("tel", record.get("phone", ""))),
        str(record.get("whatsapp", "")),
    )


def prospect_identity(record: Mapping[str, object]) -> str:
    """Retourne la clé de rapprochement stable d'une fiche."""
    contact = normalize_prospect_contact(record)
    return prospect_deduplication_key(
        name=str(record.get("nom", record.get("name", ""))),
        city=str(record.get("ville", record.get("city", ""))),
        domain=str(record.get("domain", record.get("site", ""))),
        contact=contact,
    )


def prepare_action(
    record: Mapping[str, object],
    *,
    entity_type: str,
    entity_id: str | int,
    action: str,
    step: str | int = "",
    today=None,
) -> PreparedAction:
    """Valide et prépare une action sans l'exécuter.

    La fonction bloque les fiches invalides et les opt-out. La clé retournée
    doit être persistée avant création d'une tâche ou d'une relance afin de
    rendre l'opération idempotente.
    """
    validation = validate_contact_record(record)
    errors = list(validation.errors)
    warnings = list(validation.warnings)
    if record.get("opt_out"):
        errors.append("Action sortante interdite pour un opt-out")
    score = None
    try:
        score = score_prospect(record, today=today)
    except (TypeError, ValueError) as exc:
        errors.append(f"Scoring impossible : {exc}")
    key = action_idempotency_key(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        step=step,
    )
    return PreparedAction(
        allowed=not errors,
        action=action,
        idempotency_key=key,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        contact=validation.normalized,
        score=score,
    )


def transition_event(
    *,
    entity_type: str,
    entity_id: str | int,
    current: str,
    target: str,
    actor: str,
    reason: str = "",
    occurred_at: str | None = None,
) -> AuditEvent:
    """Valide une transition et retourne l'événement d'audit correspondant."""
    validate_transition(current, target)
    timestamp = occurred_at or datetime.now(timezone.utc).isoformat()
    return AuditEvent(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action="status_changed",
        actor=actor,
        occurred_at=timestamp,
        old_value=current,
        new_value=target,
        reason=reason,
    )


def audit_insert_sql(event: AuditEvent) -> tuple[str, tuple[str, ...]]:
    """Prépare une insertion paramétrée, sans exécuter de SQL."""
    return (
        """INSERT INTO audit_events
           (entity_type, entity_id, action, actor, occurred_at,
            old_value, new_value, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event.entity_type,
            event.entity_id,
            event.action,
            event.actor,
            event.occurred_at,
            event.old_value,
            event.new_value,
            event.reason,
        ),
    )
