"""Orchestration transactionnelle des actions CRM contrôlées."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from crm_quality import AuditEvent, PreparedAction, prepare_action
from crm_storage import record_audit, reserve_idempotency


def prepare_and_reserve(
    connection,
    record: Mapping[str, object],
    *,
    entity_type: str,
    entity_id: str | int,
    action: str,
    actor: str,
    step: str | int = "",
    now: str | None = None,
    today=None,
) -> PreparedAction:
    """Valide une action et réserve sa clé dans la même transaction.

    La fonction ne déclenche aucun envoi externe. L'appelant doit effectuer
    l'écriture métier et l'envoi contrôlé dans la transaction du handler, puis
    journaliser le résultat. Une action invalide ou déjà réservée est refusée.
    """
    prepared = prepare_action(
        record,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        step=step,
        today=today,
    )
    if not prepared.allowed:
        return prepared

    timestamp = now or datetime.now(timezone.utc).isoformat()
    with connection:
        reserved = reserve_idempotency(
            connection,
            idempotency_key=prepared.idempotency_key,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            step=step,
            created_at=timestamp,
        )
        if not reserved:
            return PreparedAction(
                allowed=False,
                action=prepared.action,
                idempotency_key=prepared.idempotency_key,
                errors=("Action déjà réservée",),
                warnings=prepared.warnings,
                contact=prepared.contact,
                score=prepared.score,
            )
        record_audit(
            connection,
            AuditEvent(
                entity_type=entity_type,
                entity_id=str(entity_id),
                action="action_reserved",
                actor=actor,
                occurred_at=timestamp,
                reason=action,
            ),
        )
    return prepared
