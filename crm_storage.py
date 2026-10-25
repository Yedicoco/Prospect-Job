"""Persistance SQLite des garde-fous CRM."""
from __future__ import annotations

import sqlite3

from crm_quality import AuditEvent


SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity
    ON audit_events(entity_type, entity_id, id);
CREATE TABLE IF NOT EXISTS crm_idempotency (
    id INTEGER PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    step TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    result TEXT NOT NULL DEFAULT 'reserved'
);
CREATE INDEX IF NOT EXISTS idx_crm_idempotency_entity
    ON crm_idempotency(entity_type, entity_id, action);
"""


def migrate(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def record_audit(connection: sqlite3.Connection, event: AuditEvent) -> int:
    cursor = connection.execute(
        """INSERT INTO audit_events
        (entity_type, entity_id, action, actor, occurred_at,
         old_value, new_value, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event.entity_type, event.entity_id, event.action, event.actor,
         event.occurred_at, event.old_value, event.new_value, event.reason),
    )
    return int(cursor.lastrowid)


def reserve_idempotency(
    connection: sqlite3.Connection,
    *,
    idempotency_key: str,
    entity_type: str,
    entity_id: str | int,
    action: str,
    step: str | int = "",
    created_at: str,
) -> bool:
    cursor = connection.execute(
        """INSERT OR IGNORE INTO crm_idempotency
        (idempotency_key, entity_type, entity_id, action, step, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (idempotency_key, entity_type, str(entity_id), action, str(step), created_at),
    )
    return cursor.rowcount == 1


def mark_idempotency_result(connection: sqlite3.Connection, idempotency_key: str, result: str) -> None:
    if not result.strip():
        raise ValueError("Le résultat d'idempotence ne peut pas être vide")
    cursor = connection.execute(
        "UPDATE crm_idempotency SET result=? WHERE idempotency_key=?",
        (result.strip(), idempotency_key),
    )
    if cursor.rowcount != 1:
        raise KeyError("Clé d'idempotence inconnue")


def audit_events(connection: sqlite3.Connection, *, entity_type: str, entity_id: str | int) -> list[sqlite3.Row]:
    return list(connection.execute(
        "SELECT * FROM audit_events WHERE entity_type=? AND entity_id=? ORDER BY id",
        (entity_type, str(entity_id)),
    ))
