#!/usr/bin/env python3
"""yallah_autonome.py — Moteur commercial autonome Yallah Services (Casablanca, Maroc).

Implémente :
- Les 14 tables SQLite (prêtes pour PostgreSQL) : prospects, demandes_clients, contacts,
  sources, consentements, messages, campagnes, envois, reponses, blocages, relances,
  audit_log, daily_digests, settings.
- Capture B2C (Familles & Particuliers) + analyse auto FR/Darija/Arabe + Besoin Client Score (0-100).
- Prospection B2B publique + Prospect Pro Score (0-100) + conservation preuve & source.
- Workflow de validation humaine en 5 étapes avec les 9 actions obligatoires.
- File d'envoi (`envois`) + relances J+3 / J+7 / J+14 (max 3, jamais 2 messages le même jour).
- Mode Auto-pilot optionnel (désactivé par défaut, admin uniquement, coupe-circuit qualité).
- Daily Prospect Digest (Email complet + WhatsApp court sans exposition de données sensibles).
- Double pipeline CRM (Familles 8 étapes / Professionnels 9 étapes) + Tableau de bord Acquisition.
- Conformité stricte Loi marocaine 09-08 / CNDP et règles Meta WhatsApp Business.
"""
from __future__ import annotations

import csv
import html as html_lib
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote

import validation as v
import yallah_analyzer as analyzer
import yallah_b2c as b2c
import yallah_connectors as connectors
import yallah_messages as ym
import yallah_prospection as yp
import yallah_sources as ysources

connect: Callable | None = None

# ---------------------------------------------------------------------------
# Référentiels officiels (Sources autorisées, Pipelines CRM, Plafonds)
# ---------------------------------------------------------------------------
SOURCES_B2C_AUTORISEES = {
    "formulaire_prestation": ("Formulaire public « Demande de prestation »", "b2c", "sollicite"),
    "formulaire_contact": ("Formulaire de contact du site", "b2c", "sollicite"),
    "bouton_whatsapp": ("Bouton WhatsApp prérempli", "b2c", "sollicite"),
    "whatsapp_entrant": ("Message WhatsApp Business reçu", "b2c", "sollicite"),
    "email_officiel": ("Email reçu sur adresse officielle Yallah Services", "b2c", "sollicite"),
    "appel_entrant": ("Appel entrant (avec note ou transcription)", "b2c", "sollicite"),
    "social_entrant": ("Message volontaire Facebook / Instagram / TikTok / Google Business Profile", "b2c", "sollicite"),
    "campagne_formulaire": ("Réponse à une publicité / campagne avec formulaire", "b2c", "sollicite"),
    "recommandation_client": ("Recommandation client avec accord explicite", "b2c", "consentement_requis"),
    "partenaire_local": ("Partenaire local (résidence, conciergerie, agence immo, école, crèche, pharmacie…)", "b2c", "consentement_requis"),
}

SOURCES_B2B_AUTORISEES = {
    "google_maps_places": ("Google Maps / Places", "b2b", "public_pro"),
    "site_web_officiel": ("Site web officiel (Contact / À propos / Carrières)", "b2b", "public_pro"),
    "annonce_emploi_publique": ("Annonce d’emploi publique", "b2b", "public_pro"),
    "reseau_pro_public": ("Information publique de réseau professionnel", "b2b", "public_pro"),
    "annuaire_registre_public": ("Annuaire / registre public", "b2b", "public_pro"),
    "formulaire_entrant_b2b": ("Formulaire entrant site Yallah Services", "b2b", "sollicite"),
    "recommandation_partenaire_b2b": ("Recommandation partenaire autorisée", "b2b", "consentement_requis"),
    "catalogue_b2b_source": ("Catalogue B2B sourcé Yallah Services", "b2b", "public_pro"),
}

PIPELINE_FAMILLES = (
    "demande_recue",
    "qualifiee",
    "rdv_programme",
    "besoin_confirme",
    "candidats_proposes",
    "mission_confirmee",
    "gagnee",
    "perdue",
)

PIPELINE_PRO = (
    "prospect_identifie",
    "contact_valide",
    "message_envoye",
    "reponse_recue",
    "rdv_programme",
    "besoin_confirme",
    "proposition_envoyee",
    "gagne",
    "perdu",
)

AUTOPILOT_DEFAULTS = {
    "enabled": False,
    "max_first_contacts_per_day": 15,
    "max_followups": 3,
    "followup_days": [3, 7, 14],
    "bounce_threshold_pct": 10.0,
    "complaint_threshold": 1,
    "max_consecutive_errors": 3,
    "digest_hour": "08:00",
    "circuit_breaker_tripped": False,
    "circuit_breaker_reason": "",
}

AUTONOME_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    code TEXT PRIMARY KEY,
    libelle TEXT NOT NULL,
    categorie TEXT NOT NULL,
    base_legale TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    contact_key TEXT NOT NULL UNIQUE,
    type_contact TEXT NOT NULL,
    nom TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    tel TEXT NOT NULL DEFAULT '',
    whatsapp TEXT NOT NULL DEFAULT '',
    ville TEXT NOT NULL DEFAULT '',
    quartier TEXT NOT NULL DEFAULT '',
    langue_preferee TEXT NOT NULL DEFAULT 'fr',
    canal_prefere TEXT NOT NULL DEFAULT '',
    sensible INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consentements (
    id INTEGER PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id),
    contact_key TEXT NOT NULL,
    canal TEXT NOT NULL,
    finalite TEXT NOT NULL,
    consenti INTEGER NOT NULL,
    source TEXT NOT NULL,
    preuve TEXT NOT NULL,
    date_consentement TEXT NOT NULL,
    revoque_le TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'system'
);
CREATE TABLE IF NOT EXISTS demandes_clients (
    id INTEGER PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    contact_id INTEGER REFERENCES contacts(id),
    intake_id INTEGER,
    record_id INTEGER,
    nom TEXT NOT NULL DEFAULT '',
    whatsapp TEXT NOT NULL DEFAULT '',
    tel TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    ville TEXT NOT NULL DEFAULT '',
    quartier TEXT NOT NULL DEFAULT '',
    type_besoin TEXT NOT NULL DEFAULT 'autre',
    frequence TEXT NOT NULL DEFAULT '',
    date_souhaitee TEXT NOT NULL DEFAULT '',
    urgence TEXT NOT NULL DEFAULT '',
    budget_indicatif TEXT NOT NULL DEFAULT '',
    langue_preferee TEXT NOT NULL DEFAULT 'fr',
    canal_prefere TEXT NOT NULL DEFAULT '',
    consentement_recontact INTEGER NOT NULL DEFAULT 0,
    consentement_whatsapp INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    message_brut TEXT NOT NULL DEFAULT '',
    analyse_json TEXT NOT NULL DEFAULT '{}',
    score INTEGER NOT NULL DEFAULT 0,
    score_details_json TEXT NOT NULL DEFAULT '{}',
    classification TEXT NOT NULL DEFAULT 'B',
    motifs_exclusion TEXT NOT NULL DEFAULT '',
    action_recommandee TEXT NOT NULL DEFAULT '',
    workflow_step INTEGER NOT NULL DEFAULT 4,
    workflow_status TEXT NOT NULL DEFAULT 'en_attente_validation',
    pipeline_stage TEXT NOT NULL DEFAULT 'demande_recue',
    loss_reason TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    sensible INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prospects (
    id INTEGER PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    contact_id INTEGER REFERENCES contacts(id),
    record_id INTEGER,
    nom_entreprise TEXT NOT NULL,
    type_etablissement TEXT NOT NULL DEFAULT 'entreprise',
    ville TEXT NOT NULL DEFAULT '',
    quartier TEXT NOT NULL DEFAULT '',
    adresse_publique TEXT NOT NULL DEFAULT '',
    site_web TEXT NOT NULL DEFAULT '',
    email_pro TEXT NOT NULL DEFAULT '',
    tel_pro TEXT NOT NULL DEFAULT '',
    whatsapp_pro TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_nom TEXT NOT NULL DEFAULT 'site_web_officiel',
    date_consultation TEXT NOT NULL,
    preuve_extrait TEXT NOT NULL DEFAULT '',
    besoin_probable TEXT NOT NULL DEFAULT '',
    signaux_interet_json TEXT NOT NULL DEFAULT '[]',
    niveau TEXT NOT NULL DEFAULT 'A',
    score INTEGER NOT NULL DEFAULT 0,
    score_details_json TEXT NOT NULL DEFAULT '{}',
    classification TEXT NOT NULL DEFAULT 'B',
    motifs_exclusion TEXT NOT NULL DEFAULT '',
    action_recommandee TEXT NOT NULL DEFAULT '',
    workflow_step INTEGER NOT NULL DEFAULT 4,
    workflow_status TEXT NOT NULL DEFAULT 'en_attente_validation',
    pipeline_stage TEXT NOT NULL DEFAULT 'prospect_identifie',
    loss_reason TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    sensible INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    langue TEXT NOT NULL DEFAULT 'fr',
    canal TEXT NOT NULL DEFAULT 'whatsapp',
    sujet TEXT NOT NULL DEFAULT '',
    corps TEXT NOT NULL,
    alertes_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    statut TEXT NOT NULL DEFAULT 'prepare',
    valide_par TEXT NOT NULL DEFAULT '',
    valide_le TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campagnes (
    id INTEGER PRIMARY KEY,
    nom TEXT NOT NULL,
    canal TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'manuel',
    statut TEXT NOT NULL DEFAULT 'brouillon',
    plafond_jour INTEGER NOT NULL DEFAULT 15,
    cadre_legal TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS envois (
    id INTEGER PRIMARY KEY,
    campagne_id INTEGER REFERENCES campagnes(id),
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    contact_id INTEGER REFERENCES contacts(id),
    message_id INTEGER REFERENCES messages(id),
    canal TEXT NOT NULL,
    destination TEXT NOT NULL DEFAULT '',
    message_final TEXT NOT NULL,
    scheduled_at TEXT NOT NULL DEFAULT '',
    sent_at TEXT NOT NULL DEFAULT '',
    statut TEXT NOT NULL DEFAULT 'en_attente_validation',
    resultat TEXT NOT NULL DEFAULT 'en_attente',
    consentement_id INTEGER REFERENCES consentements(id),
    consentement_preuve TEXT NOT NULL DEFAULT '',
    provider_id TEXT NOT NULL DEFAULT '',
    error_detail TEXT NOT NULL DEFAULT '',
    step_number INTEGER NOT NULL DEFAULT 1,
    autopilot INTEGER NOT NULL DEFAULT 0,
    historique_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reponses (
    id INTEGER PRIMARY KEY,
    envoi_id INTEGER REFERENCES envois(id),
    contact_id INTEGER REFERENCES contacts(id),
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id INTEGER,
    canal TEXT NOT NULL,
    expediteur TEXT NOT NULL DEFAULT '',
    contenu TEXT NOT NULL,
    stop_detecte INTEGER NOT NULL DEFAULT 0,
    stop_mot_cle TEXT NOT NULL DEFAULT '',
    analyse_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocages (
    id INTEGER PRIMARY KEY,
    contact_key TEXT NOT NULL UNIQUE,
    canal TEXT NOT NULL,
    motif TEXT NOT NULL,
    mot_cle TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'system',
    actor TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relances (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    contact_id INTEGER REFERENCES contacts(id),
    canal TEXT NOT NULL,
    etape INTEGER NOT NULL,
    delai_jours INTEGER NOT NULL,
    scheduled_for TEXT NOT NULL,
    statut TEXT NOT NULL DEFAULT 'prevue',
    envoi_id INTEGER REFERENCES envois(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, etape)
);
CREATE TABLE IF NOT EXISTS daily_digests (
    id INTEGER PRIMARY KEY,
    digest_date TEXT NOT NULL,
    kpis_json TEXT NOT NULL,
    items_json TEXT NOT NULL,
    email_subject TEXT NOT NULL,
    email_html TEXT NOT NULL,
    email_text TEXT NOT NULL,
    whatsapp_text TEXT NOT NULL,
    email_status TEXT NOT NULL DEFAULT 'prepare',
    whatsapp_status TEXT NOT NULL DEFAULT 'prepare',
    sent_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_demandes_class ON demandes_clients(classification, workflow_status);
CREATE INDEX IF NOT EXISTS idx_prospects_class ON prospects(classification, workflow_status);
CREATE INDEX IF NOT EXISTS idx_envois_statut ON envois(statut, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_relances_sched ON relances(statut, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_consentements_key ON consentements(contact_key, canal, consenti);
CREATE INDEX IF NOT EXISTS idx_daily_digests_date ON daily_digests(digest_date);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _audit(con, actor: str, action: str, entity: str, entity_id: int | None = None, detail: str = "") -> None:
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='audit_log'").fetchone():
        con.execute(
            "INSERT INTO audit_log(actor,action,entity,entity_id,detail,created) VALUES (?,?,?,?,?,?)",
            (actor or "system", action, entity, entity_id, str(detail)[:2000], utc_now()),
        )


def configure(factory: Callable) -> None:
    """Initialise les 14 tables autonomes, les sources autorisées et synchronise les fiches B2B existantes."""
    global connect
    connect = factory
    with connect() as con:
        con.executescript(AUTONOME_SCHEMA)
        ts = utc_now()
        for code, (lib, cat, base) in {**SOURCES_B2C_AUTORISEES, **SOURCES_B2B_AUTORISEES}.items():
            con.execute(
                "INSERT OR IGNORE INTO sources(code,libelle,categorie,base_legale,active,created_at) VALUES (?,?,?,?,1,?)",
                (code, lib, cat, base, ts),
            )
        if not con.execute("SELECT 1 FROM settings WHERE key='autopilot_config'").fetchone():
            con.execute(
                "INSERT INTO settings(key,value) VALUES ('autopilot_config',?)",
                (json.dumps(AUTOPILOT_DEFAULTS, ensure_ascii=False),),
            )
        if not con.execute("SELECT 1 FROM settings WHERE key='autonome_b2b_synced'").fetchone():
            _sync_existing_b2b_records(con)
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('autonome_b2b_synced','1')")
        # Mettre à jour le numéro de migration si la table existe
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
            con.execute("INSERT OR IGNORE INTO schema_migrations VALUES (4,?)", (ts,))


# ---------------------------------------------------------------------------
# Gestion unifiée des contacts, dédoublonnage, consentements & blocages STOP
# ---------------------------------------------------------------------------
def _contact_keys(email: str = "", tel: str = "", whatsapp: str = "", nom: str = "", ville: str = "") -> list[str]:
    keys: list[str] = []
    mail = ym.email_normalise(email)
    if ym.est_email_exploitable(mail):
        keys.append("mail:" + mail)
    for raw in (whatsapp, tel):
        nt = ym.tel_normalise(raw)
        if len(nt) >= 9:
            k = "tel:" + nt
            if k not in keys:
                keys.append(k)
    if not keys and nom.strip() and ville.strip():
        nv = ysources.cle_nom_ville(nom, ville)
        if nv:
            keys.append(nv)
    return keys


def est_contact_bloque(con, email: str = "", tel: str = "", whatsapp: str = "") -> tuple[bool, str]:
    """Vérifie blocages + suppressions + meta refus."""
    keys = _contact_keys(email=email, tel=tel, whatsapp=whatsapp)
    for k in keys:
        row = con.execute("SELECT motif, created_at FROM blocages WHERE contact_key=?", (k,)).fetchone()
        if row:
            return True, f"Bloqué ({row['motif']}) le {row['created_at'][:10]}"
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='suppressions'").fetchone():
            if con.execute("SELECT 1 FROM suppressions WHERE contact_key=?", (k,)).fetchone():
                return True, "Contact au registre des suppressions / refus"
    return False, ""


def bloquer_contact(
    con,
    *,
    email: str = "",
    tel: str = "",
    whatsapp: str = "",
    contact_keys: list[str] | None = None,
    canal: str = "tous",
    motif: str = "Demande de retrait STOP",
    mot_cle: str = "",
    source: str = "system",
    actor: str = "system",
) -> list[str]:
    """Bloque définitivement un contact sur tous les canaux et annule tout envoi / relance."""
    keys = list(dict.fromkeys((contact_keys or []) + _contact_keys(email=email, tel=tel, whatsapp=whatsapp)))
    ts = utc_now()
    for k in keys:
        con.execute(
            "INSERT OR REPLACE INTO blocages(contact_key,canal,motif,mot_cle,source,actor,created_at) VALUES (?,?,?,?,?,?,?)",
            (k, canal, motif[:500], mot_cle[:80], source[:100], actor[:100], ts),
        )
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='suppressions'").fetchone():
            con.execute("INSERT OR IGNORE INTO suppressions(contact_key,created) VALUES (?,?)", (k, ts))
        con.execute(
            "UPDATE consentements SET consenti=0, revoque_le=? WHERE contact_key=? AND consenti=1",
            (ts, k),
        )
        # Annuler tous les envois en attente / programmés et toutes les relances liées à ce contact
        contact_rows = con.execute("SELECT id FROM contacts WHERE contact_key=?", (k,)).fetchall()
        for cr in contact_rows:
            cid = cr["id"]
            con.execute(
                "UPDATE envois SET statut='bloque', resultat='bloque', error_detail=?, updated_at=? "
                "WHERE contact_id=? AND statut IN ('en_attente_validation','valide','programme')",
                (f"Blocage définitif : {motif}", ts, cid),
            )
            con.execute(
                "UPDATE relances SET statut='bloquee', updated_at=? WHERE contact_id=? AND statut='prevue'",
                (ts, cid),
            )
            con.execute(
                "UPDATE demandes_clients SET classification='Exclu', workflow_status='bloque', "
                "motifs_exclusion=?, updated_at=? WHERE contact_id=?",
                (motif[:500], ts, cid),
            )
            con.execute(
                "UPDATE prospects SET classification='Exclu', workflow_status='bloque', "
                "motifs_exclusion=?, updated_at=? WHERE contact_id=?",
                (motif[:500], ts, cid),
            )
    # Bloquer également les destinations directes dans envois / deliveries
    destinations = [k.split(":", 1)[1] for k in keys if ":" in k]
    for dest in destinations:
        con.execute(
            "UPDATE envois SET statut='bloque', resultat='bloque', error_detail=?, updated_at=? "
            "WHERE destination=? AND statut IN ('en_attente_validation','valide','programme')",
            (f"Blocage définitif : {motif}", ts, dest),
        )
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='deliveries'").fetchone():
            con.execute(
                "UPDATE deliveries SET status='blocked', reason=? WHERE destination=? AND status='queued'",
                (f"Blocage définitif : {motif}", dest),
            )
    _audit(con, actor, "blocage_definitif", "blocages", detail=f"{', '.join(keys)} | {canal} | {motif}")
    return keys


def _upsert_contact(
    con,
    *,
    type_contact: str,
    nom: str,
    email: str = "",
    tel: str = "",
    whatsapp: str = "",
    ville: str = "",
    quartier: str = "",
    langue_preferee: str = "fr",
    canal_prefere: str = "",
    sensible: bool = False,
) -> tuple[int | None, str, bool]:
    """Trouve ou crée un contact normalisé. Retourne ``(contact_id, primary_key, existed_before)``."""
    keys = _contact_keys(email=email, tel=tel, whatsapp=whatsapp, nom=nom, ville=ville)
    if not keys:
        return None, "", False
    # Vérifier si l'une des clés existe déjà dans contacts
    for k in keys:
        row = con.execute("SELECT * FROM contacts WHERE contact_key=?", (k,)).fetchone()
        if row:
            con.execute(
                "UPDATE contacts SET nom=COALESCE(NULLIF(?,''),nom), email=COALESCE(NULLIF(?,''),email), "
                "tel=COALESCE(NULLIF(?,''),tel), whatsapp=COALESCE(NULLIF(?,''),whatsapp), "
                "ville=COALESCE(NULLIF(?,''),ville), quartier=COALESCE(NULLIF(?,''),quartier), "
                "langue_preferee=COALESCE(NULLIF(?,''),langue_preferee), updated_at=? WHERE id=?",
                (
                    nom,
                    ym.email_normalise(email),
                    ysources.norm_tel(tel),
                    ysources.norm_tel(whatsapp),
                    ville,
                    quartier,
                    langue_preferee,
                    utc_now(),
                    row["id"],
                ),
            )
            return row["id"], row["contact_key"], True

    # Vérifier aussi les autres champs normalisés (ex. même WhatsApp déjà stocké sous un contact créé par email)
    wa_norm = ysources.norm_tel(whatsapp)
    tel_norm = ysources.norm_tel(tel)
    mail_norm = ym.email_normalise(email)
    for field_name, val in (("email", mail_norm), ("whatsapp", wa_norm), ("tel", tel_norm)):
        if val:
            row = con.execute(f"SELECT * FROM contacts WHERE {field_name}=?", (val,)).fetchone()
            if row:
                return row["id"], row["contact_key"], True

    primary = keys[0]
    ts = utc_now()
    cid = con.execute(
        "INSERT INTO contacts(contact_key,type_contact,nom,email,tel,whatsapp,ville,quartier,langue_preferee,canal_prefere,sensible,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            primary,
            type_contact,
            nom[:160],
            mail_norm,
            tel_norm,
            wa_norm,
            ville[:100],
            quartier[:100],
            langue_preferee[:20],
            canal_prefere[:20],
            int(bool(sensible)),
            ts,
            ts,
        ),
    ).lastrowid
    return cid, primary, False


def enregistrer_consentement(
    con,
    *,
    contact_id: int | None,
    contact_key: str,
    canal: str,
    finalite: str,
    consenti: bool,
    source: str,
    preuve: str,
    actor: str = "public",
) -> int:
    ts = utc_now()
    return con.execute(
        "INSERT INTO consentements(contact_id,contact_key,canal,finalite,consenti,source,preuve,date_consentement,revoque_le,actor) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (contact_id, contact_key, canal, finalite, int(bool(consenti)), source[:120], preuve[:1000], ts, "" if consenti else ts, actor[:100]),
    ).lastrowid


def verifier_consentement_envoi(
    con,
    *,
    entity_type: str,
    entity_row: dict[str, Any],
    canal: str,
    is_autopilot: bool = False,
) -> tuple[bool, int | None, str]:
    """Vérifie strictement le consentement Loi 09-08 & Meta WhatsApp Business avant tout envoi.

    Retourne ``(autorise, consentement_id, preuve_ou_motif)``.
    """
    email = entity_row.get("email") or entity_row.get("email_pro") or ""
    tel = entity_row.get("tel") or entity_row.get("tel_pro") or ""
    wa = entity_row.get("whatsapp") or entity_row.get("whatsapp_pro") or ""
    blocked, block_reason = est_contact_bloque(con, email=email, tel=tel, whatsapp=wa)
    if blocked:
        return False, None, block_reason

    keys = _contact_keys(email=email, tel=tel, whatsapp=wa)

    if entity_type == "demande_b2c":
        # Particulier : consentement explicite OBLIGATOIRE (et consentement WhatsApp distinct pour WhatsApp)
        if not entity_row.get("consentement_recontact"):
            return False, None, "Conformité Loi 09-08 : consentement explicite de recontact absent pour ce particulier."
        if canal == "whatsapp" and not entity_row.get("consentement_whatsapp"):
            return False, None, "Conformité WhatsApp Business : opt-in WhatsApp explicite non coché par le particulier."
        for k in keys:
            row = con.execute(
                "SELECT id, preuve, date_consentement FROM consentements "
                "WHERE contact_key=? AND canal=? AND consenti=1 AND revoque_le='' ORDER BY id DESC LIMIT 1",
                (k, "whatsapp" if canal == "whatsapp" else "recontact"),
            ).fetchone()
            if row:
                return True, row["id"], f"{row['preuve']} ({row['date_consentement'][:10]})"
        return True, None, f"Consentement enregistré sur demande {entity_row.get('reference', '')} ({entity_row.get('source', '')})"

    # Prospect B2B professionnel
    if canal == "whatsapp":
        # Sur WhatsApp : opt-in explicite requis (en Auto-pilot toujours strict ; en manuel vérifier opt-in ou WA public publié)
        for k in keys:
            row = con.execute(
                "SELECT id, preuve, date_consentement FROM consentements "
                "WHERE contact_key=? AND canal='whatsapp' AND consenti=1 AND revoque_le='' ORDER BY id DESC LIMIT 1",
                (k,),
            ).fetchone()
            if row:
                return True, row["id"], f"Opt-in WhatsApp documenté : {row['preuve']} ({row['date_consentement'][:10]})"
        if is_autopilot:
            return False, None, "Auto-pilot WhatsApp bloqué : aucun opt-in WhatsApp explicite documenté pour ce contact."
        if not str(entity_row.get("whatsapp_pro") or "").strip():
            return False, None, "Aucun numéro WhatsApp professionnel explicitement publié ni opt-in documenté."
        return False, None, "Validation humaine requise : aucun opt-in WhatsApp formel (numéro pro public uniquement)."

    # B2B Email ou Appel : vérifier consentement explicite (requis en Auto-pilot) ou coordonnée pro publique sourcée
    for k in keys:
        row = con.execute(
            "SELECT id, preuve, date_consentement FROM consentements "
            "WHERE contact_key=? AND canal IN (?,'recontact') AND consenti=1 AND revoque_le='' ORDER BY id DESC LIMIT 1",
            (k, canal),
        ).fetchone()
        if row:
            return True, row["id"], f"Consentement pro documenté : {row['preuve']} ({row['date_consentement'][:10]})"
    if is_autopilot:
        return False, None, "Auto-pilot bloqué : consentement explicite requis pour ce canal (Loi 09-08)."
    if entity_row.get("source_url") and entity_row.get("preuve_extrait"):
        return True, None, f"Coordonnée pro publique sourcée ({entity_row['source_url']})"
    return False, None, "Source publique ou consentement pro manquant."


# ---------------------------------------------------------------------------
# FONCTIONNALITÉ 1, 2, 3, 4 — Capture, Analyse, Scoring et Réponse B2C
# ---------------------------------------------------------------------------
def _choisir_canal_b2c(demande: dict[str, Any], analyse: dict[str, Any]) -> tuple[str, str]:
    """Détermine le canal d'envoi recommandé et la destination normalisée pour une demande B2C."""
    wa = ym.tel_normalise(str(demande.get("whatsapp") or ""))
    tel = ym.tel_normalise(str(demande.get("tel") or ""))
    mail = ym.email_normalise(str(demande.get("email") or ""))
    wa_dest = wa or (tel if ym.est_numero_mobile(str(demande.get("tel") or "")) else "")
    pref = str(analyse.get("canal_prefere") or demande.get("canal_prefere") or "").lower()

    if pref == "whatsapp" and wa_dest and demande.get("consentement_whatsapp"):
        return "whatsapp", wa_dest
    if pref == "email" and ym.est_email_exploitable(mail):
        return "email", mail
    if pref == "appel" and (tel or wa):
        return "appel", tel or wa
    if wa_dest and demande.get("consentement_whatsapp"):
        return "whatsapp", wa_dest
    if ym.est_email_exploitable(mail):
        return "email", mail
    if tel or wa:
        return "appel", tel or wa
    return "email", ""


def capturer_demande_b2c(
    body: dict[str, Any],
    *,
    actor: str = "public",
    intake_id: int | None = None,
    con=None,
) -> dict[str, Any]:
    """Centralise, analyse, score (0–100), dédoublonne et prépare la réponse d'une demande famille B2C."""
    source_raw = str(body.get("source") or "formulaire_prestation").strip().split(":")[0]
    source_map = {
        "site_formulaire": "formulaire_prestation",
        "whatsapp_entrant": "whatsapp_entrant",
        "whatsapp_bouton_site": "whatsapp_bouton",
        "gbp_entrant": "social_entrant",
        "google_business_message": "social_entrant",
        "facebook_message": "social_entrant",
        "instagram_message": "social_entrant",
        "tiktok_message": "social_entrant",
        "email_entrant": "email_officiel",
        "publicite_formulaire": "campagne_formulaire",
        "recommandation_consentie": "recommandation_client",
        "partenaire_local_consenti": "partenaire_local",
    }
    source = source_raw if source_raw in SOURCES_B2C_AUTORISEES else source_map.get(source_raw, "")
    if not source:
        raise connectors.ComplianceError(
            f"Source B2C non autorisée ou interdite (Loi 09-08 / zéro prospection froide) : {source_raw}"
        )

    nom = str(body.get("nom") or body.get("name") or "").strip()[:160]
    whatsapp = str(body.get("whatsapp") or "").strip()[:40]
    tel = str(body.get("tel") or "").strip()[:40]
    email = str(body.get("email") or "").strip().lower()[:254]
    message_brut = str(body.get("message_brut") or body.get("message") or "").strip()[:4000]
    consent_recontact = bool(body.get("consentement_recontact") if "consentement_recontact" in body else body.get("acknowledge", False))
    consent_whatsapp = bool(body.get("consentement_whatsapp", False))
    sensible = bool(body.get("sensible", False))

    if source in ("recommandation_client", "partenaire_local") and not consent_recontact:
        raise ValueError(
            "Recommandation ou partenaire : l’accord explicite de la personne recommandée est obligatoire."
        )

    analyse = analyzer.analyser_demande_b2c(
        message_brut,
        champs_volontaires={
            "ville": body.get("ville") or body.get("city") or "",
            "quartier": body.get("quartier") or body.get("zone") or "",
            "type_besoin": body.get("type_besoin") or body.get("type_prestation") or "",
            "frequence": body.get("frequence") or body.get("type_contrat") or "",
            "date_souhaitee": body.get("date_souhaitee") or "",
            "urgence": body.get("urgence") or "",
            "budget_indicatif": body.get("budget_indicatif") or "",
            "langue_preferee": body.get("langue_preferee") or "",
            "canal_prefere": body.get("canal_prefere") or "",
            "b2c_ref": body.get("b2c_ref") or "",
        },
        ref_date=v.today(),
    )

    def _run(db_con):
        # 1. STOP prioritaire absolu
        is_blocked, _ = est_contact_bloque(db_con, email=email, tel=tel, whatsapp=whatsapp)
        if analyse["stop_detecte"]:
            bloquer_contact(
                db_con,
                email=email,
                tel=tel,
                whatsapp=whatsapp,
                canal=source,
                motif=f"Mot-clé STOP détecté ({analyse['stop_mot_cle']})",
                mot_cle=analyse["stop_mot_cle"],
                source=source,
                actor=actor,
            )
            is_blocked = True

        # 2. Dédoublonnage contact (même contact ayant déjà une demande active non clôturée dans les 7 jours)
        cid, ckey, existed = _upsert_contact(
            db_con,
            type_contact="particulier",
            nom=nom or "Famille",
            email=email,
            tel=tel,
            whatsapp=whatsapp,
            ville=analyse["ville"],
            quartier=analyse["quartier"],
            langue_preferee=analyse["langue_preferee"],
            canal_prefere=analyse["canal_prefere"],
            sensible=sensible,
        )
        is_duplicate = False
        if existed and cid:
            dup_row = db_con.execute(
                "SELECT id FROM demandes_clients WHERE contact_id=? AND type_besoin=? "
                "AND workflow_status NOT IN ('rejete','bloque') AND created_at>=?",
                (cid, analyse["type_prestation"], (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")),
            ).fetchone()
            if dup_row:
                is_duplicate = True

        demande_payload = {
            "nom": nom,
            "email": email,
            "tel": tel,
            "whatsapp": whatsapp,
            "ville": analyse["ville"],
            "quartier": analyse["quartier"],
            "budget_indicatif": analyse["budget_indicatif"],
            "consentement_recontact": consent_recontact,
            "consentement_whatsapp": consent_whatsapp,
            "message_brut": message_brut,
            "canal_prefere": analyse["canal_prefere"],
            "langue_preferee": analyse["langue_preferee"],
        }
        scoring = scorer_b2c_result = analyzer.scorer_demande_b2c(
            demande_payload,
            analyse,
            is_duplicate=is_duplicate,
            is_blocked=is_blocked,
        )

        # 3. Enregistrement consentements granulaires Loi 09-08 (jamais créés si non cochés !)
        consent_id_rec = None
        consent_id_wa = None
        if ckey and not is_blocked:
            if consent_recontact:
                consent_id_rec = enregistrer_consentement(
                    db_con,
                    contact_id=cid,
                    contact_key=ckey,
                    canal="recontact",
                    finalite="traitement_demande_prestation",
                    consenti=True,
                    source=source,
                    preuve=f"Case « J’accepte que Yallah Services me recontacte au sujet de ma demande » cochée ({source})",
                    actor=actor,
                )
            if consent_whatsapp:
                consent_id_wa = enregistrer_consentement(
                    db_con,
                    contact_id=cid,
                    contact_key=ckey,
                    canal="whatsapp",
                    finalite="messages_whatsapp_demande",
                    consenti=True,
                    source=source,
                    preuve=f"Case « J’accepte de recevoir des messages de Yallah Services sur WhatsApp » cochée ({source})",
                    actor=actor,
                )

        ts = utc_now()
        seq = db_con.execute("SELECT COALESCE(MAX(id),0)+1 FROM demandes_clients").fetchone()[0]
        ref = f"DEM-{v.today().strftime('%Y%m%d')}-{seq:04d}"
        wf_status = "bloque" if is_blocked else ("exclu" if scoring["classification"] == "Exclu" else "en_attente_validation")
        pipe_stage = "qualifiee" if scoring["classification"] == "A" else "demande_recue"

        did = db_con.execute(
            """INSERT INTO demandes_clients(
                reference,contact_id,intake_id,nom,whatsapp,tel,email,ville,quartier,
                type_besoin,frequence,date_souhaitee,urgence,budget_indicatif,
                langue_preferee,canal_prefere,consentement_recontact,consentement_whatsapp,
                source,message_brut,analyse_json,score,score_details_json,classification,
                motifs_exclusion,action_recommandee,workflow_step,workflow_status,pipeline_stage,
                sensible,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref,
                cid,
                intake_id,
                nom,
                ysources.norm_tel(whatsapp) or whatsapp,
                ysources.norm_tel(tel) or tel,
                ym.email_normalise(email),
                analyse["ville"],
                analyse["quartier"],
                analyse["type_prestation"],
                analyse["frequence"],
                analyse["date_souhaitee"],
                analyse["urgence"],
                analyse["budget_indicatif"],
                analyse["langue_preferee"],
                analyse["canal_prefere"],
                int(consent_recontact),
                int(consent_whatsapp),
                source,
                message_brut,
                json.dumps(analyse, ensure_ascii=False),
                scoring["score"],
                json.dumps(scoring["details"], ensure_ascii=False),
                scoring["classification"],
                " | ".join(scoring["motifs_exclusion"]),
                scoring["action_recommandee"],
                4,
                wf_status,
                pipe_stage,
                int(sensible),
                ts,
                ts,
            ),
        ).lastrowid

        # 4. Préparation du message de réponse (étape 4 : en attente de validation humaine)
        canal_rec, dest = _choisir_canal_b2c(demande_payload, analyse)
        msg_body = analyzer.generer_message_famille(demande_payload, analyse, analyse["langue_preferee"])
        alertes = analyzer.verifier_message_autonome(msg_body)
        mid = db_con.execute(
            "INSERT INTO messages(entity_type,entity_id,langue,canal,sujet,corps,alertes_json,version,statut,created_at) "
            "VALUES ('demande_b2c',?,?,?,?,?,?,1,?,?)",
            (
                did,
                analyse["langue_preferee"],
                canal_rec,
                f"Yallah Services — prise en charge de votre demande ({ref})",
                msg_body,
                json.dumps(alertes, ensure_ascii=False),
                "bloque" if (is_blocked or alertes) else "prepare",
                ts,
            ),
        ).lastrowid

        if scoring["classification"] != "Exclu" and not is_blocked:
            consent_id_used = consent_id_wa if canal_rec == "whatsapp" else consent_id_rec
            consent_preuve = (
                "Opt-in WhatsApp explicite enregistré"
                if (canal_rec == "whatsapp" and consent_whatsapp)
                else ("Consentement recontact enregistré" if consent_recontact else "Consentement à vérifier avant envoi")
            )
            db_con.execute(
                """INSERT INTO envois(
                    entity_type,entity_id,contact_id,message_id,canal,destination,message_final,
                    statut,resultat,consentement_id,consentement_preuve,historique_json,created_at,updated_at
                ) VALUES ('demande_b2c',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    did,
                    cid,
                    mid,
                    canal_rec,
                    dest,
                    msg_body,
                    "en_attente_validation",
                    "en_attente",
                    consent_id_used,
                    consent_preuve,
                    json.dumps([{"ts": ts, "event": "prepare", "actor": actor}], ensure_ascii=False),
                    ts,
                    ts,
                ),
            )

        _audit(
            db_con,
            actor,
            "demande_b2c_capturee",
            "demandes_clients",
            did,
            detail=f"{ref} | {scoring['classification']} ({scoring['score']}/100) | {source}",
        )
        return {
            "id": did,
            "reference": ref,
            "analyse": analyse,
            "score": scoring["score"],
            "classification": scoring["classification"],
            "score_details": scoring["details"],
            "motifs_exclusion": scoring["motifs_exclusion"],
            "workflow_status": wf_status,
            "message_prepare": msg_body,
            "message_alertes": alertes,
            "canal_recommande": canal_rec,
            "duplicate": is_duplicate,
            "blocked": is_blocked,
        }

    if con is not None:
        return _run(con)
    with connect() as db_con:
        db_con.execute("BEGIN IMMEDIATE")
        return _run(db_con)


# ---------------------------------------------------------------------------
# FONCTIONNALITÉ 5 — Prospection B2B Professionnelle
# ---------------------------------------------------------------------------
def enregistrer_prospect_pro(
    body: dict[str, Any],
    *,
    actor: str = "system",
    record_id: int | None = None,
    langue: str = "fr",
    prenom_conseiller: str = "Youssef",
    con=None,
) -> dict[str, Any]:
    """Enregistre, dédoublonne, score (0–100) et prépare le message d'un prospect B2B public sourcé."""
    nom = str(body.get("nom_entreprise") or body.get("nom") or "").strip()[:160]
    if not nom:
        raise ValueError("Nom de l’entreprise requis")

    source_url = str(body.get("source_url") or "").strip()
    source_type = str(body.get("source_type") or "").strip()
    if source_type != "entrant":
        ok_src, motif_src = analyzer.est_source_pro_autorisee(source_url)
        if not ok_src:
            raise connectors.ComplianceError(motif_src)

    source_nom = str(body.get("source_nom") or "site_web_officiel").strip()
    if source_nom not in SOURCES_B2B_AUTORISEES:
        source_nom = "site_web_officiel"

    type_etab = str(body.get("type_etablissement") or body.get("segment") or "entreprise").strip().lower()
    ville = str(body.get("ville") or "Casablanca").strip()[:100]
    quartier = str(body.get("quartier") or body.get("zone") or "").strip()[:100]
    adresse = str(body.get("adresse_publique") or body.get("adresse") or "").strip()[:240]
    site_web = str(body.get("site_web") or "").strip()[:300]
    email_pro = ym.email_normalise(str(body.get("email_pro") or body.get("email") or ""))
    tel_pro = ysources.norm_tel(str(body.get("tel_pro") or body.get("tel") or "")) or str(body.get("tel_pro") or body.get("tel") or "").strip()
    wa_pro = ysources.norm_tel(str(body.get("whatsapp_pro") or body.get("whatsapp") or "")) or ""
    date_consult = str(body.get("date_consultation") or utc_now())[:30]
    preuve = str(body.get("preuve_extrait") or f"Source publique consultée : {source_url}").strip()[:600]
    besoin_prob = str(body.get("besoin_probable") or "").strip()[:300]
    signaux = body.get("signaux_interet") or []
    if isinstance(signaux, str):
        signaux = [s.strip() for s in signaux.split(",") if s.strip()]
    niveau = str(body.get("niveau") or ("A" if (email_pro or tel_pro or wa_pro) else "C")).strip().upper()
    if niveau not in ("A", "B", "C"):
        niveau = "B"
    sensible = bool(body.get("sensible", False))

    def _run(db_con):
        is_blocked, _ = est_contact_bloque(db_con, email=email_pro, tel=tel_pro, whatsapp=wa_pro)
        cid, ckey, existed = _upsert_contact(
            db_con,
            type_contact="professionnel",
            nom=nom,
            email=email_pro,
            tel=tel_pro,
            whatsapp=wa_pro,
            ville=ville,
            quartier=quartier,
            langue_preferee=langue,
            canal_prefere="email" if ym.est_email_exploitable(email_pro) else ("whatsapp" if wa_pro else "appel"),
            sensible=sensible,
        )
        is_duplicate = False
        if existed and cid:
            if db_con.execute("SELECT 1 FROM prospects WHERE contact_id=?", (cid,)).fetchone():
                is_duplicate = True
        if not is_duplicate:
            nv = ysources.cle_nom_ville(nom, ville)
            if nv:
                for row in db_con.execute("SELECT nom_entreprise, ville FROM prospects").fetchall():
                    if ysources.cle_nom_ville(row["nom_entreprise"], row["ville"]) == nv:
                        is_duplicate = True
                        break

        prospect_dict = {
            "nom_entreprise": nom,
            "type_etablissement": type_etab,
            "ville": ville,
            "quartier": quartier,
            "email_pro": email_pro,
            "tel_pro": tel_pro,
            "whatsapp_pro": wa_pro,
            "source_url": source_url,
            "source_type": source_type,
            "date_consultation": date_consult,
            "preuve_extrait": preuve,
            "besoin_probable": besoin_prob,
            "signaux_interet": signaux,
            "niveau": niveau,
        }
        scoring = analyzer.scorer_prospect_pro(
            prospect_dict,
            ref_date=v.today(),
            is_duplicate=is_duplicate,
            is_blocked=is_blocked,
        )

        ts = utc_now()
        seq = db_con.execute("SELECT COALESCE(MAX(id),0)+1 FROM prospects").fetchone()[0]
        ref = f"PRO-{v.today().strftime('%Y%m%d')}-{seq:04d}"
        wf_status = "bloque" if is_blocked else ("exclu" if scoring["classification"] == "Exclu" else "en_attente_validation")

        pid = db_con.execute(
            """INSERT INTO prospects(
                reference,contact_id,record_id,nom_entreprise,type_etablissement,ville,quartier,
                adresse_publique,site_web,email_pro,tel_pro,whatsapp_pro,source_url,source_nom,
                date_consultation,preuve_extrait,besoin_probable,signaux_interet_json,niveau,
                score,score_details_json,classification,motifs_exclusion,action_recommandee,
                workflow_step,workflow_status,pipeline_stage,sensible,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ref,
                cid,
                record_id,
                nom,
                type_etab,
                ville,
                quartier,
                adresse,
                site_web,
                email_pro,
                tel_pro,
                wa_pro,
                source_url,
                source_nom,
                date_consult,
                preuve,
                besoin_prob,
                json.dumps(signaux, ensure_ascii=False),
                niveau,
                scoring["score"],
                json.dumps(scoring["details"], ensure_ascii=False),
                scoring["classification"],
                " | ".join(scoring["motifs_exclusion"]),
                scoring["action_recommandee"],
                4,
                wf_status,
                "prospect_identifie",
                int(sensible),
                ts,
                ts,
            ),
        ).lastrowid

        canal_rec = "email" if ym.est_email_exploitable(email_pro) else ("whatsapp" if wa_pro else "appel")
        dest = email_pro if canal_rec == "email" else (ym.tel_normalise(wa_pro) if canal_rec == "whatsapp" else ym.tel_normalise(tel_pro))
        msg_body = analyzer.generer_message_pro(prospect_dict, langue=langue, prenom_conseiller=prenom_conseiller)
        alertes = analyzer.verifier_message_autonome(msg_body)
        mid = db_con.execute(
            "INSERT INTO messages(entity_type,entity_id,langue,canal,sujet,corps,alertes_json,version,statut,created_at) "
            "VALUES ('prospect_pro',?,?,?,?,?,?,1,?,?)",
            (
                pid,
                langue,
                canal_rec,
                f"Yallah Services — besoin en personnel pour {nom}",
                msg_body,
                json.dumps(alertes, ensure_ascii=False),
                "bloque" if (is_blocked or alertes) else "prepare",
                ts,
            ),
        ).lastrowid

        if scoring["classification"] != "Exclu" and not is_blocked:
            db_con.execute(
                """INSERT INTO envois(
                    entity_type,entity_id,contact_id,message_id,canal,destination,message_final,
                    statut,resultat,consentement_preuve,historique_json,created_at,updated_at
                ) VALUES ('prospect_pro',?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pid,
                    cid,
                    mid,
                    canal_rec,
                    dest,
                    msg_body,
                    "en_attente_validation",
                    "en_attente",
                    f"Source pro publique : {source_url} ({date_consult[:10]})",
                    json.dumps([{"ts": ts, "event": "prepare", "actor": actor}], ensure_ascii=False),
                    ts,
                    ts,
                ),
            )

        _audit(
            db_con,
            actor,
            "prospect_pro_enregistre",
            "prospects",
            pid,
            detail=f"{ref} | {nom} | {scoring['classification']} ({scoring['score']}/100)",
        )
        return {
            "id": pid,
            "reference": ref,
            "score": scoring["score"],
            "classification": scoring["classification"],
            "score_details": scoring["details"],
            "motifs_exclusion": scoring["motifs_exclusion"],
            "workflow_status": wf_status,
            "message_prepare": msg_body,
            "message_alertes": alertes,
            "canal_recommande": canal_rec,
            "duplicate": is_duplicate,
        }

    if con is not None:
        return _run(con)
    with connect() as db_con:
        db_con.execute("BEGIN IMMEDIATE")
        return _run(db_con)


def _sync_existing_b2b_records(con) -> int:
    """Importe les fiches B2B réelles existantes dans la table `prospects` avec score 0–100."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='records'").fetchone():
        return 0
    count = 0
    for row in con.execute("SELECT id, payload FROM records WHERE kind='b2b' ORDER BY id").fetchall():
        item = json.loads(row["payload"])
        if item.get("exemple"):
            continue
        if con.execute("SELECT 1 FROM prospects WHERE record_id=?", (row["id"],)).fetchone():
            continue
        try:
            enregistrer_prospect_pro(
                {
                    "nom_entreprise": item.get("nom", ""),
                    "type_etablissement": item.get("segment", "entreprise"),
                    "ville": item.get("ville", "Casablanca"),
                    "quartier": item.get("zone", ""),
                    "adresse_publique": item.get("adresse", ""),
                    "email_pro": item.get("email", ""),
                    "tel_pro": item.get("tel", ""),
                    "whatsapp_pro": item.get("whatsapp", ""),
                    "source_url": item.get("source_url", ""),
                    "source_nom": "catalogue_b2b_source",
                    "date_consultation": item.get("date_derniere_verification") or item.get("date_consultation") or v.today().isoformat(),
                    "preuve_extrait": f"Fiche sourcée B2B ({item.get('source_url', '')})",
                    "besoin_probable": ym.besoins_libelles(item, "b2b", "fr"),
                    "signaux_interet": ["besoin_declare"] if item.get("besoins_probables") else [],
                    "niveau": item.get("niveau", "A"),
                },
                actor="system_sync",
                record_id=row["id"],
                con=con,
            )
            count += 1
        except (ValueError, connectors.ComplianceError):
            continue
    return count


def decouvrir_prospect_public(
    *,
    url: str,
    raw_html: str | None = None,
    actor: str = "system",
    check_robots: bool = True,
) -> dict[str, Any]:
    """Découvre un prospect B2B à partir d'une URL publique (ou HTML fourni) avec robots.txt et preuve."""
    if raw_html is not None:
        extracted = connectors.WebDiscoveryConnector.extraire_prospect_depuis_html(url, raw_html)
    else:
        extracted = connectors.WebDiscoveryConnector.inspecter_page_publique(url, check_robots=check_robots)
    saved = enregistrer_prospect_pro(extracted, actor=actor)
    return {"extracted": extracted, "saved": saved}


# ---------------------------------------------------------------------------
# FONCTIONNALITÉ 8 & 9 — Workflow de validation, File d'envoi, Relances & Auto-pilot
# ---------------------------------------------------------------------------
def get_autopilot_config(con=None) -> dict[str, Any]:
    def _read(db_con):
        row = db_con.execute("SELECT value FROM settings WHERE key='autopilot_config'").fetchone()
        cfg = dict(AUTOPILOT_DEFAULTS)
        if row:
            try:
                cfg.update(json.loads(row["value"]))
            except json.JSONDecodeError:
                pass
        return cfg

    if con is not None:
        return _read(con)
    with connect() as db_con:
        return _read(db_con)


def set_autopilot_config(updates: dict[str, Any], *, actor: str = "admin", role: str = "admin") -> dict[str, Any]:
    """Seul un administrateur peut activer Auto-pilot ou modifier les plafonds."""
    if role != "admin":
        raise PermissionError("Seul un administrateur peut activer Auto-pilot ou modifier les plafonds.")
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        cfg = get_autopilot_config(con)
        if "enabled" in updates:
            enabled = bool(updates["enabled"])
            if enabled:
                if updates.get("confirm") is not True:
                    raise ValueError("Confirmation explicite requise pour activer le mode Auto-pilot.")
                cfg["circuit_breaker_tripped"] = False
                cfg["circuit_breaker_reason"] = ""
            cfg["enabled"] = enabled
        if "max_first_contacts_per_day" in updates:
            cap = int(v.number(updates["max_first_contacts_per_day"], "Plafond contacts/jour", minimum=1, maximum=50))
            cfg["max_first_contacts_per_day"] = cap
        if "max_followups" in updates:
            mf = int(v.number(updates["max_followups"], "Nombre max de relances", minimum=0, maximum=3))
            cfg["max_followups"] = mf
        if "followup_days" in updates:
            days = updates["followup_days"]
            if not isinstance(days, list) or not all(isinstance(x, int) and 1 <= x <= 30 for x in days) or len(days) > 3:
                raise ValueError("Jours de relance invalides (ex. [3, 7, 14])")
            cfg["followup_days"] = sorted(days)
        if "bounce_threshold_pct" in updates:
            cfg["bounce_threshold_pct"] = float(v.number(updates["bounce_threshold_pct"], "Seuil rebond %", minimum=1, maximum=50))
        if "digest_hour" in updates:
            dh = str(updates["digest_hour"]).strip()
            if not re.fullmatch(r"[0-2]\d:[0-5]\d", dh):
                raise ValueError("Heure digest attendue au format HH:MM")
            cfg["digest_hour"] = dh
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('autopilot_config',?)", (json.dumps(cfg, ensure_ascii=False),))
        _audit(con, actor, "autopilot_config_maj", "settings", detail=json.dumps(cfg, ensure_ascii=False))
    return cfg


def _normalize_entity_type(entity_type: str) -> str:
    et = str(entity_type or "").strip()
    if et in ("demande", "demande_b2c"):
        return "demande_b2c"
    if et in ("prospect", "prospect_pro"):
        return "prospect_pro"
    return et


def _get_entity(con, entity_type: str, entity_id: int) -> dict[str, Any]:
    entity_type = _normalize_entity_type(entity_type)
    if entity_type == "demande_b2c":
        row = con.execute("SELECT * FROM demandes_clients WHERE id=?", (int(entity_id),)).fetchone()
    elif entity_type == "prospect_pro":
        row = con.execute("SELECT * FROM prospects WHERE id=?", (int(entity_id),)).fetchone()
    else:
        raise ValueError("Type d’entité invalide (demande_b2c ou prospect_pro attendu)")
    if not row:
        raise ValueError("Fiche introuvable")
    return dict(row)


def desactiver_autopilot_urgence(motif: str = "Arrêt en un clic", *, actor: str = "admin", role: str = "admin") -> dict[str, Any]:
    """Arrêt d'urgence en un clic du mode Auto-pilot (réservé administrateur)."""
    if role != "admin":
        raise PermissionError("Seul un administrateur peut désactiver le mode Auto-pilot.")
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        cfg = get_autopilot_config(con)
        cfg["enabled"] = False
        cfg["circuit_breaker_tripped"] = True
        cfg["circuit_breaker_reason"] = str(motif or "Arrêt en un clic")[:300]
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('autopilot_config',?)", (json.dumps(cfg, ensure_ascii=False),))
        _audit(con, actor, "autopilot_kill_switch", "settings", detail=cfg["circuit_breaker_reason"])
    return cfg


def fiche_detail(entity_type: str, entity_id: int) -> dict[str, Any]:
    """Retourne le dossier complet d'une demande B2C ou d'un prospect B2B pour la revue humaine."""
    etype = _normalize_entity_type(entity_type)
    with connect() as con:
        item = _get_entity(con, etype, entity_id)
        cid = item.get("contact_id")
        contact = dict(con.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()) if cid else None
        msgs = [dict(r) for r in con.execute("SELECT * FROM messages WHERE entity_type=? AND entity_id=? ORDER BY id DESC", (etype, int(entity_id))).fetchall()]
        envois = [dict(r) for r in con.execute("SELECT * FROM envois WHERE entity_type=? AND entity_id=? ORDER BY id DESC", (etype, int(entity_id))).fetchall()]
        relances = [dict(r) for r in con.execute("SELECT * FROM relances WHERE entity_type=? AND entity_id=? ORDER BY etape", (etype, int(entity_id))).fetchall()]
        consentements = [dict(r) for r in con.execute("SELECT * FROM consentements WHERE contact_id=? ORDER BY id DESC", (cid,)).fetchall()] if cid else []
        reponses = [dict(r) for r in con.execute("SELECT * FROM reponses WHERE entity_type=? AND entity_id=? ORDER BY id DESC", (etype, int(entity_id))).fetchall()]
        email = item.get("email") or item.get("email_pro") or ""
        tel = item.get("tel") or item.get("tel_pro") or ""
        wa = item.get("whatsapp") or item.get("whatsapp_pro") or ""
        bloque, motif_blocage = est_contact_bloque(con, email=email, tel=tel, whatsapp=wa)
    analyse = json.loads(item.get("analyse_json") or "{}") if etype == "demande_b2c" else {}
    score_details = json.loads(item.get("score_details_json") or "{}")
    return {
        "entity_type": etype,
        "item": item,
        "contact": contact,
        "messages": msgs,
        "envois": envois,
        "relances": relances,
        "consentements": consentements,
        "reponses": reponses,
        "bloque": bloque,
        "motif_blocage": motif_blocage,
        "analyse": analyse,
        "score_details": score_details,
    }


def _first_contacts_sent_today(con, jour: date | None = None) -> int:
    iso = (jour or v.today()).isoformat()
    envois_cnt = con.execute(
        "SELECT COUNT(DISTINCT contact_id) FROM envois "
        "WHERE step_number=1 AND statut='envoye' AND substr(sent_at,1,10)=?",
        (iso,),
    ).fetchone()[0]
    return int(envois_cnt)


def _sent_today_to_contact(con, contact_id: int | None, jour: date | None = None) -> bool:
    """Règle absolue : jamais deux messages le même jour au même contact."""
    if not contact_id:
        return False
    iso = (jour or v.today()).isoformat()
    return bool(
        con.execute(
            "SELECT 1 FROM envois WHERE contact_id=? AND statut='envoye' AND substr(sent_at,1,10)=?",
            (contact_id, iso),
        ).fetchone()
    )


def planifier_relances_pour_envoi(
    con,
    *,
    entity_type: str,
    entity_id: int,
    contact_id: int | None,
    canal: str,
    base_date: date | None = None,
) -> list[dict[str, Any]]:
    """Planifie les relances J+3, J+7, J+14 (max 3 relances au total, annulées dès réponse ou STOP)."""
    cfg = get_autopilot_config(con)
    jours = list(cfg.get("followup_days") or [3, 7, 14])[: int(cfg.get("max_followups", 3))]
    base = base_date or v.today()
    ts = utc_now()
    created = []
    for idx, delai in enumerate(jours, start=1):
        sched = (base + timedelta(days=int(delai))).isoformat()
        con.execute(
            "INSERT OR IGNORE INTO relances(entity_type,entity_id,contact_id,canal,etape,delai_jours,scheduled_for,statut,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,'prevue',?,?)",
            (entity_type, entity_id, contact_id, canal, idx, int(delai), sched, ts, ts),
        )
        created.append({"etape": idx, "delai_jours": int(delai), "scheduled_for": sched})
    return created


def _executer_envoi_effectif(
    con,
    envoi_row: dict[str, Any],
    entity_row: dict[str, Any],
    *,
    actor: str,
    mode: str = "auto",
    is_autopilot: bool = False,
) -> dict[str, Any]:
    """Effectue toutes les vérifications de conformité au moment T puis envoie (live ou manuel tracé)."""
    cfg = get_autopilot_config(con)
    canal = envoi_row["canal"]
    dest = envoi_row["destination"]
    msg_final = envoi_row["message_final"]
    contact_id = envoi_row["contact_id"]
    step = int(envoi_row.get("step_number") or 1)
    ts = utc_now()

    # 1. Garde-fou contenu
    alertes = analyzer.verifier_message_autonome(msg_final)
    if alertes:
        raise ValueError("Message bloqué par le garde-fou : " + " | ".join(alertes))

    # 2. Consentement & STOP re-vérifiés au moment de l'envoi
    ok_cons, cons_id, cons_msg = verifier_consentement_envoi(
        con,
        entity_type=envoi_row["entity_type"],
        entity_row=entity_row,
        canal=canal,
        is_autopilot=is_autopilot,
    )
    if not ok_cons:
        con.execute(
            "UPDATE envois SET statut='bloque', resultat='bloque', error_detail=?, updated_at=? WHERE id=?",
            (cons_msg, ts, envoi_row["id"]),
        )
        raise connectors.ComplianceError(cons_msg)

    # 3. Jamais deux messages le même jour au même contact
    if _sent_today_to_contact(con, contact_id):
        raise ValueError("Règle anti-spam : un message a déjà été envoyé aujourd’hui à ce contact.")

    # 4. Plafond quotidien de premiers contacts (15/jour par défaut)
    if step == 1 and _first_contacts_sent_today(con) >= int(cfg.get("max_first_contacts_per_day", 15)):
        raise ValueError(f"Plafond quotidien atteint ({cfg['max_first_contacts_per_day']} premiers contacts/jour).")

    # 5. Maximum 1 message initial + 3 relances = 4 messages max
    max_total = 1 + int(cfg.get("max_followups", 3))
    already_sent = con.execute(
        "SELECT COUNT(*) FROM envois WHERE entity_type=? AND entity_id=? AND statut='envoye'",
        (envoi_row["entity_type"], envoi_row["entity_id"]),
    ).fetchone()[0]
    if already_sent >= max_total:
        raise ValueError(f"Limite atteinte : 1 message initial + {cfg['max_followups']} relances maximum.")

    # 6. Transport réel si demandé et configuré, sinon enregistrement manuel explicite (si mode='manuel')
    provider_id = ""
    if mode == "live" or is_autopilot:
        if canal == "email":
            res = connectors.EmailConnector.send(
                dest,
                f"Yallah Services — {entity_row.get('reference', '')}",
                msg_final,
                idempotency_key=f"yallah-envoi-{envoi_row['id']}",
            )
            provider_id = res["provider_id"]
        elif canal == "whatsapp":
            res = connectors.WhatsAppConnector.send(
                dest,
                msg_final,
                has_opt_in=True,
                use_template=True,
            )
            provider_id = res["provider_id"]
        else:
            raise ValueError("L’envoi automatique ne supporte pas le canal appel ; utilisez l’action Appeler.")
    elif mode == "manuel":
        provider_id = f"manuel-{envoi_row['id']}-{v.today().strftime('%Y%m%d')}"
    else:
        raise ValueError("Mode d’envoi invalide (manuel ou live attendu)")

    hist = json.loads(envoi_row.get("historique_json") or "[]")
    hist.append({"ts": ts, "event": "envoye", "mode": mode, "actor": actor, "provider_id": provider_id})

    con.execute(
        "UPDATE envois SET statut='envoye', resultat='envoye', sent_at=?, consentement_id=COALESCE(?,consentement_id), "
        "consentement_preuve=?, provider_id=?, autopilot=?, historique_json=?, updated_at=? WHERE id=?",
        (ts, cons_id, cons_msg, provider_id, int(is_autopilot), json.dumps(hist, ensure_ascii=False), ts, envoi_row["id"]),
    )

    # Avancer le workflow & pipeline + programmer relances J+3/J+7/J+14 si 1er contact
    if envoi_row["entity_type"] == "demande_b2c":
        con.execute(
            "UPDATE demandes_clients SET workflow_step=5, workflow_status='envoye', updated_at=? WHERE id=?",
            (ts, envoi_row["entity_id"]),
        )
    else:
        con.execute(
            "UPDATE prospects SET workflow_step=5, workflow_status='envoye', "
            "pipeline_stage=CASE WHEN pipeline_stage IN ('prospect_identifie','contact_valide') THEN 'message_envoye' ELSE pipeline_stage END, "
            "updated_at=? WHERE id=?",
            (ts, envoi_row["entity_id"]),
        )

    relances = []
    if step == 1:
        relances = planifier_relances_pour_envoi(
            con,
            entity_type=envoi_row["entity_type"],
            entity_id=envoi_row["entity_id"],
            contact_id=contact_id,
            canal=canal,
        )
        if relances:
            con.execute("UPDATE envois SET resultat='relance_prevue' WHERE id=?", (envoi_row["id"],))

    _audit(
        con,
        actor,
        "envoi_effectue",
        "envois",
        envoi_row["id"],
        detail=f"{envoi_row['entity_type']}#{envoi_row['entity_id']} | {canal} | {mode} | {provider_id}",
    )
    return {
        "envoi_id": envoi_row["id"],
        "statut": "envoye",
        "provider_id": provider_id,
        "relances_planifiees": relances,
    }


def executer_action_validation(body: dict[str, Any], *, actor: str = "local") -> dict[str, Any]:
    """Exécute l'une des 9 actions du workflow de validation humaine sur une demande B2C ou un prospect B2B."""
    entity_type = _normalize_entity_type(str(body.get("entity_type") or ""))
    entity_id = int(body["entity_id"])
    action = str(body.get("action") or "")
    valid_actions = {
        "valider",
        "modifier_message",
        "rejeter",
        "bloquer",
        "demander_verification",
        "appeler",
        "repondre_whatsapp",
        "envoyer_maintenant",
        "programmer_envoi",
    }
    if action not in valid_actions:
        raise ValueError(f"Action de validation inconnue : {action}")

    ts = utc_now()
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        entity = _get_entity(con, entity_type, entity_id)
        table = "demandes_clients" if entity_type == "demande_b2c" else "prospects"
        envoi = con.execute(
            "SELECT * FROM envois WHERE entity_type=? AND entity_id=? ORDER BY id DESC LIMIT 1",
            (entity_type, entity_id),
        ).fetchone()
        envoi_dict = dict(envoi) if envoi else None

        if action == "valider":
            if entity["workflow_status"] == "bloque":
                raise connectors.ComplianceError("Fiche bloquée définitivement : validation impossible.")
            con.execute(
                f"UPDATE {table} SET workflow_step=4, workflow_status='valide', "
                + ("pipeline_stage=CASE WHEN pipeline_stage='demande_recue' THEN 'qualifiee' ELSE pipeline_stage END"
                   if entity_type == "demande_b2c"
                   else "pipeline_stage=CASE WHEN pipeline_stage='prospect_identifie' THEN 'contact_valide' ELSE pipeline_stage END")
                + ", updated_at=? WHERE id=?",
                (ts, entity_id),
            )
            if envoi_dict:
                hist = json.loads(envoi_dict.get("historique_json") or "[]")
                hist.append({"ts": ts, "event": "valide", "actor": actor})
                con.execute(
                    "UPDATE envois SET statut='valide', historique_json=?, updated_at=? WHERE id=?",
                    (json.dumps(hist, ensure_ascii=False), ts, envoi_dict["id"]),
                )
            con.execute(
                "UPDATE messages SET statut='valide', valide_par=?, valide_le=? WHERE entity_type=? AND entity_id=?",
                (actor, ts, entity_type, entity_id),
            )
            _audit(con, actor, "validation_humaine", table, entity_id)
            return {"ok": True, "action": action, "workflow_status": "valide"}

        if action == "modifier_message":
            nouveau = v.text(body.get("message") or body.get("body") or "", "Message", True, 2000)
            langue = str(body.get("langue") or entity.get("langue_preferee") or "fr")
            if langue not in ("fr", "darija", "arabe"):
                langue = "fr"
            canal = str(body.get("canal") or (envoi_dict["canal"] if envoi_dict else "whatsapp"))
            if canal == "telephone":
                canal = "appel"
            if canal not in ("whatsapp", "email", "appel"):
                raise ValueError("Canal invalide")
            alertes = analyzer.verifier_message_autonome(nouveau)
            if alertes:
                raise ValueError("Message refusé par le garde-fou : " + " | ".join(alertes))
            ver = con.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM messages WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            ).fetchone()[0]
            mid = con.execute(
                "INSERT INTO messages(entity_type,entity_id,langue,canal,corps,alertes_json,version,statut,valide_par,valide_le,created_at) "
                "VALUES (?,?,?,?,?,'[]',?,'modifie',?,?,?)",
                (entity_type, entity_id, langue, canal, nouveau, ver, actor, ts, ts),
            ).lastrowid
            if envoi_dict:
                hist = json.loads(envoi_dict.get("historique_json") or "[]")
                hist.append({"ts": ts, "event": "message_modifie", "version": ver, "actor": actor})
                con.execute(
                    "UPDATE envois SET message_id=?, canal=?, message_final=?, historique_json=?, updated_at=? WHERE id=?",
                    (mid, canal, nouveau, json.dumps(hist, ensure_ascii=False), ts, envoi_dict["id"]),
                )
            _audit(con, actor, "message_modifie", table, entity_id, detail=f"v{ver} ({langue}/{canal})")
            return {"ok": True, "action": action, "message_id": mid, "version": ver}

        if action == "rejeter":
            motif = str(body.get("motif") or "Rejeté lors de la revue humaine").strip()[:400]
            con.execute(
                f"UPDATE {table} SET workflow_status='rejete', notes=CASE WHEN notes='' THEN ? ELSE notes || '\n' || ? END, updated_at=? WHERE id=?",
                (motif, motif, ts, entity_id),
            )
            con.execute(
                "UPDATE envois SET statut='annule', resultat='annule', error_detail=?, updated_at=? "
                "WHERE entity_type=? AND entity_id=? AND statut IN ('en_attente_validation','valide','programme')",
                (motif, ts, entity_type, entity_id),
            )
            con.execute(
                "UPDATE relances SET statut='annulee', updated_at=? WHERE entity_type=? AND entity_id=? AND statut='prevue'",
                (ts, entity_type, entity_id),
            )
            _audit(con, actor, "rejet_humain", table, entity_id, detail=motif)
            return {"ok": True, "action": action, "workflow_status": "rejete"}

        if action == "bloquer":
            motif = str(body.get("motif") or "Blocage définitif demandé par l’opérateur").strip()[:400]
            keys = bloquer_contact(
                con,
                email=entity.get("email") or entity.get("email_pro") or "",
                tel=entity.get("tel") or entity.get("tel_pro") or "",
                whatsapp=entity.get("whatsapp") or entity.get("whatsapp_pro") or "",
                canal="tous",
                motif=motif,
                mot_cle="BLOCAGE_MANUEL",
                source="validation_humaine",
                actor=actor,
            )
            con.execute(
                f"UPDATE {table} SET classification='Exclu', workflow_status='bloque', motifs_exclusion=?, updated_at=? WHERE id=?",
                (motif, ts, entity_id),
            )
            return {"ok": True, "action": action, "workflow_status": "bloque", "blocked_keys": keys}

        if action == "demander_verification":
            motif = str(body.get("motif") or "Vérification complémentaire des coordonnées / du consentement").strip()[:400]
            con.execute(
                f"UPDATE {table} SET workflow_status='verification_demandee', notes=CASE WHEN notes='' THEN ? ELSE notes || '\n' || ? END, updated_at=? WHERE id=?",
                (motif, motif, ts, entity_id),
            )
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
                label_nom = entity.get("nom") or entity.get("nom_entreprise") or entity["reference"]
                con.execute(
                    "INSERT INTO tasks(opportunity_id,title,owner,due,status,created) VALUES (NULL,?,?,?,'a_faire',?)",
                    (f"Vérifier fiche {entity['reference']} — {label_nom} : {motif}"[:300], actor, v.today().isoformat(), ts),
                )
            _audit(con, actor, "verification_demandee", table, entity_id, detail=motif)
            return {"ok": True, "action": action, "workflow_status": "verification_demandee"}

        if action == "appeler":
            phone = entity.get("tel") or entity.get("whatsapp") or entity.get("tel_pro") or entity.get("whatsapp_pro") or ""
            norm_p = ysources.norm_tel(phone)
            if not norm_p:
                raise ValueError("Aucun numéro de téléphone disponible sur cette fiche.")
            blocked, block_reason = est_contact_bloque(con, tel=norm_p, whatsapp=norm_p)
            if blocked:
                raise connectors.ComplianceError(block_reason)
            note = str(body.get("note") or f"Appel initié vers {norm_p}").strip()[:400]
            con.execute(
                f"UPDATE {table} SET notes=CASE WHEN notes='' THEN ? ELSE notes || '\n' || ? END, updated_at=? WHERE id=?",
                (f"[Appel {ts[:16]}] {note}", f"[Appel {ts[:16]}] {note}", ts, entity_id),
            )
            _audit(con, actor, "appel_initie", table, entity_id, detail=norm_p)
            return {"ok": True, "action": action, "tel_link": f"tel:{norm_p}", "phone": norm_p}

        if action == "repondre_whatsapp":
            wa_raw = entity.get("whatsapp") or entity.get("tel") or entity.get("whatsapp_pro") or entity.get("tel_pro") or ""
            wa_num = ym.tel_normalise(wa_raw)
            if len(wa_num) < 9:
                raise ValueError("Aucun numéro WhatsApp valide disponible.")
            ok_cons, _, cons_msg = verifier_consentement_envoi(
                con, entity_type=entity_type, entity_row=entity, canal="whatsapp", is_autopilot=False
            )
            # Pour B2B avec whatsapp_pro explicitement publié, autoriser l'ouverture manuelle avec rappel de prudence
            b2b_public_wa = entity_type == "prospect_pro" and bool(str(entity.get("whatsapp_pro") or "").strip()) and not est_contact_bloque(con, whatsapp=wa_raw)[0]
            if not ok_cons and not b2b_public_wa:
                raise connectors.ComplianceError(cons_msg)
            msg_txt = envoi_dict["message_final"] if envoi_dict else ""
            wa_url = f"https://wa.me/{wa_num}?text={quote(msg_txt)}" if msg_txt else f"https://wa.me/{wa_num}"
            _audit(con, actor, "ouverture_whatsapp", table, entity_id, detail=wa_num)
            return {"ok": True, "action": action, "whatsapp_link": wa_url, "consent_note": cons_msg}

        if action == "envoyer_maintenant":
            if body.get("confirm") is not True:
                raise ValueError("Confirmation explicite requise avant « Envoyer maintenant ».")
            if not envoi_dict:
                raise ValueError("Aucun message préparé en file d’envoi pour cette fiche.")
            req_canal = str(body.get("canal") or "").strip().lower()
            if req_canal == "telephone":
                req_canal = "appel"
            if req_canal in ("email", "whatsapp", "appel") and req_canal != envoi_dict["canal"]:
                envoi_dict["canal"] = req_canal
                if req_canal == "email":
                    envoi_dict["destination"] = entity.get("email") or entity.get("email_pro") or ""
                elif req_canal == "whatsapp":
                    envoi_dict["destination"] = ym.tel_normalise(entity.get("whatsapp") or entity.get("whatsapp_pro") or entity.get("tel") or entity.get("tel_pro") or "")
                else:
                    envoi_dict["destination"] = ym.tel_normalise(entity.get("tel") or entity.get("tel_pro") or entity.get("whatsapp") or "")
            if body.get("simulation") is True:
                mode = "manuel"
            else:
                mode = str(body.get("mode") or ("live" if os.getenv("YALLAH_ENABLE_LIVE") == "1" else "manuel"))
            return _executer_envoi_effectif(con, envoi_dict, entity, actor=actor, mode=mode, is_autopilot=False)

        if action == "programmer_envoi":
            if body.get("confirm") is not True:
                raise ValueError("Confirmation explicite requise avant « Programmer l’envoi ».")
            sched = str(body.get("scheduled_at") or "").strip()
            if not sched or len(sched) < 10:
                raise ValueError("Date prévue d’envoi requise (AAAA-MM-JJ ou ISO).")
            v.day(sched[:10], "Date prévue")
            if not envoi_dict:
                raise ValueError("Aucun message préparé en file d’envoi pour cette fiche.")
            req_canal = str(body.get("canal") or envoi_dict["canal"]).strip().lower()
            if req_canal == "telephone":
                req_canal = "appel"
            ok_cons, cons_id, cons_msg = verifier_consentement_envoi(
                con, entity_type=entity_type, entity_row=entity, canal=req_canal, is_autopilot=False
            )
            if not ok_cons:
                raise connectors.ComplianceError(cons_msg)
            hist = json.loads(envoi_dict.get("historique_json") or "[]")
            hist.append({"ts": ts, "event": "programme", "scheduled_at": sched, "actor": actor})
            con.execute(
                "UPDATE envois SET canal=?, statut='programme', scheduled_at=?, consentement_id=COALESCE(?,consentement_id), "
                "consentement_preuve=?, historique_json=?, updated_at=? WHERE id=?",
                (req_canal, sched, cons_id, cons_msg, json.dumps(hist, ensure_ascii=False), ts, envoi_dict["id"]),
            )
            con.execute(f"UPDATE {table} SET workflow_status='programme', updated_at=? WHERE id=?", (ts, entity_id))
            _audit(con, actor, "envoi_programme", "envois", envoi_dict["id"], detail=sched)
            return {"ok": True, "action": action, "envoi_id": envoi_dict["id"], "scheduled_at": sched}

    raise ValueError("Action non traitée")


# ---------------------------------------------------------------------------
# Réception des réponses & détection STOP (annule relances automatiquement)
# ---------------------------------------------------------------------------
def enregistrer_reponse(body: dict[str, Any], *, actor: str = "system") -> dict[str, Any]:
    """Enregistre une réponse entrante, détecte STOP immédiatement et annule les relances."""
    canal = str(body.get("canal") or "whatsapp").lower()
    if canal == "telephone":
        canal = "appel"
    if canal not in ("whatsapp", "email", "appel"):
        raise ValueError("Canal de réponse invalide")
    contenu = v.text(body.get("contenu") or body.get("body") or "", "Contenu", True, 4000)
    expediteur = str(body.get("expediteur") or body.get("sender") or "").strip()[:254]
    entity_type = _normalize_entity_type(str(body.get("entity_type") or ""))
    entity_id = int(body["entity_id"]) if body.get("entity_id") else None
    envoi_id = int(body["envoi_id"]) if body.get("envoi_id") else None

    est_stop, mot_cle = analyzer.detecter_stop(contenu)
    ts = utc_now()
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        contact_id = None
        if entity_type and entity_id:
            ent = _get_entity(con, entity_type, entity_id)
            contact_id = ent.get("contact_id")
            if not expediteur:
                expediteur = ent.get("email") or ent.get("email_pro") or ent.get("whatsapp") or ent.get("tel") or ""
        elif expediteur:
            # Résolution automatique du contact par email / téléphone / WhatsApp normalisé
            if "@" in expediteur:
                crow = con.execute("SELECT id FROM contacts WHERE email=?", (ym.email_normalise(expediteur),)).fetchone()
            else:
                norm_e = ysources.norm_tel(expediteur)
                crow = con.execute("SELECT id FROM contacts WHERE tel=? OR whatsapp=?", (norm_e, norm_e)).fetchone()
            if crow:
                contact_id = crow["id"]
                drow = con.execute("SELECT id FROM demandes_clients WHERE contact_id=? ORDER BY id DESC LIMIT 1", (contact_id,)).fetchone()
                if drow:
                    entity_type, entity_id = "demande_b2c", drow["id"]
                else:
                    prow = con.execute("SELECT id FROM prospects WHERE contact_id=? ORDER BY id DESC LIMIT 1", (contact_id,)).fetchone()
                    if prow:
                        entity_type, entity_id = "prospect_pro", prow["id"]

        rid = con.execute(
            "INSERT INTO reponses(envoi_id,contact_id,entity_type,entity_id,canal,expediteur,contenu,stop_detecte,stop_mot_cle,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (envoi_id, contact_id, entity_type, entity_id, canal, expediteur, contenu, int(est_stop), mot_cle, ts),
        ).lastrowid

        if est_stop:
            bloquer_contact(
                con,
                email=expediteur if "@" in expediteur else "",
                tel=expediteur if "@" not in expediteur else "",
                whatsapp=expediteur if ("@" not in expediteur and canal == "whatsapp") else "",
                canal=canal,
                motif=f"Retrait STOP reçu par {canal} ({mot_cle})",
                mot_cle=mot_cle,
                source="reponse_entrante",
                actor=actor,
            )
            if entity_type and entity_id:
                ent = _get_entity(con, entity_type, entity_id)
                bloquer_contact(
                    con,
                    email=ent.get("email") or ent.get("email_pro") or "",
                    tel=ent.get("tel") or ent.get("tel_pro") or "",
                    whatsapp=ent.get("whatsapp") or ent.get("whatsapp_pro") or "",
                    canal=canal,
                    motif=f"Retrait STOP reçu par {canal} ({mot_cle})",
                    mot_cle=mot_cle,
                    source="reponse_entrante",
                    actor=actor,
                )
        else:
            # Réponse positive / normale : annuler toutes les relances prévues et marquer l'envoi comme répondu
            if entity_type and entity_id:
                con.execute(
                    "UPDATE relances SET statut='annulee_reponse', updated_at=? WHERE entity_type=? AND entity_id=? AND statut='prevue'",
                    (ts, entity_type, entity_id),
                )
                con.execute(
                    "UPDATE envois SET resultat='repondu', updated_at=? WHERE entity_type=? AND entity_id=? AND statut='envoye'",
                    (ts, entity_type, entity_id),
                )
                if entity_type == "prospect_pro":
                    con.execute(
                        "UPDATE prospects SET pipeline_stage=CASE WHEN pipeline_stage IN ('prospect_identifie','contact_valide','message_envoye') "
                        "THEN 'reponse_recue' ELSE pipeline_stage END, updated_at=? WHERE id=?",
                        (ts, entity_id),
                    )
        _audit(con, actor, "reponse_stop" if est_stop else "reponse_recue", "reponses", rid, detail=mot_cle or canal)
    return {"id": rid, "stop_detecte": est_stop, "stop_mot_cle": mot_cle}


# ---------------------------------------------------------------------------
# Mode Auto-pilot & Coupe-circuit qualité
# ---------------------------------------------------------------------------
def verifier_coupe_circuit_autopilot(con) -> tuple[bool, str]:
    """Arrête immédiatement Auto-pilot en cas de rebond élevé, plainte, ou série d'erreurs fournisseur."""
    cfg = get_autopilot_config(con)
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")

    # 1. Plaintes / signalements dans deliveries ou envois
    complaints = 0
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='deliveries'").fetchone():
        complaints += con.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status='complained' AND created>=?", (since,)
        ).fetchone()[0]
    complaints += con.execute(
        "SELECT COUNT(*) FROM envois WHERE resultat='plainte' AND created_at>=?", (since,)
    ).fetchone()[0]
    if complaints >= int(cfg.get("complaint_threshold", 1)):
        return True, f"Plainte / signalement détecté ({complaints}) — arrêt immédiat Auto-pilot."

    # 2. Taux de rebond élevé
    total_sent = con.execute("SELECT COUNT(*) FROM envois WHERE statut='envoye' AND sent_at>=?", (since,)).fetchone()[0]
    bounces = con.execute("SELECT COUNT(*) FROM envois WHERE resultat='rebond' AND updated_at>=?", (since,)).fetchone()[0]
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='deliveries'").fetchone():
        total_sent += con.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status IN ('accepted','delivered','read','bounced') AND created>=?",
            (since,),
        ).fetchone()[0]
        bounces += con.execute(
            "SELECT COUNT(*) FROM deliveries WHERE status='bounced' AND created>=?", (since,)
        ).fetchone()[0]
    if total_sent >= 3 and bounces > 0:
        rate = (bounces * 100.0) / total_sent
        if rate >= float(cfg.get("bounce_threshold_pct", 10.0)):
            return True, f"Taux de rebond critique ({rate:.1f}% >= {cfg['bounce_threshold_pct']}%) — arrêt immédiat Auto-pilot."

    # 3. Série d'erreurs fournisseur consécutives
    recent = con.execute("SELECT statut FROM envois ORDER BY id DESC LIMIT ?", (int(cfg.get("max_consecutive_errors", 3)),)).fetchall()
    if len(recent) >= int(cfg.get("max_consecutive_errors", 3)) and all(r["statut"] == "echec" for r in recent):
        return True, "Erreurs fournisseur consécutives — arrêt immédiat Auto-pilot."

    return False, ""


def executer_cycle_autopilot(*, actor: str = "autopilot", dry_run: bool = False) -> dict[str, Any]:
    """Exécute un cycle sécurisé Auto-pilot :
    - Ne fait rien si Auto-pilot est désactivé.
    - Vérifie le coupe-circuit qualité et désactive immédiatement en cas d'alerte.
    - Ne sélectionne QUE les fiches niveau A avec consentement valide pour le canal exact.
    - Respecte strictement plafond quotidien (15), max 3 relances (J+3/J+7/J+14), jamais 2 messages le même jour.
    """
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        cfg = get_autopilot_config(con)
        if not cfg.get("enabled"):
            return {"ran": False, "reason": "Mode Auto-pilot désactivé (comportement par défaut).", "sent": 0, "skipped": []}

        tripped, reason = verifier_coupe_circuit_autopilot(con)
        if tripped:
            cfg["enabled"] = False
            cfg["circuit_breaker_tripped"] = True
            cfg["circuit_breaker_reason"] = reason
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('autopilot_config',?)", (json.dumps(cfg, ensure_ascii=False),))
            _audit(con, actor, "autopilot_coupe_circuit", "settings", detail=reason)
            return {"ran": False, "circuit_breaker": True, "reason": reason, "sent": 0, "skipped": []}

        sent_items = []
        skipped = []
        cap = int(cfg.get("max_first_contacts_per_day", 15))
        used = _first_contacts_sent_today(con)
        today_iso = v.today().isoformat()

        # A. Traiter d'abord les relances J+3/J+7/J+14 arrivées à échéance (uniquement si pas de réponse ni STOP)
        due_relances = con.execute(
            "SELECT * FROM relances WHERE statut='prevue' AND scheduled_for<=? ORDER BY scheduled_for, etape",
            (today_iso,),
        ).fetchall()
        for rel in due_relances:
            ent = _get_entity(con, rel["entity_type"], rel["entity_id"])
            if ent.get("classification") != "A" or ent.get("workflow_status") in ("bloque", "rejete"):
                con.execute("UPDATE relances SET statut='annulee', updated_at=? WHERE id=?", (utc_now(), rel["id"]))
                continue
            ok_c, cons_id, cons_msg = verifier_consentement_envoi(
                con, entity_type=rel["entity_type"], entity_row=ent, canal=rel["canal"], is_autopilot=True
            )
            if not ok_c or _sent_today_to_contact(con, rel["contact_id"]):
                skipped.append({"entity": f"{rel['entity_type']}#{rel['entity_id']}", "reason": cons_msg or "Déjà contacté aujourd’hui"})
                continue
            nom = ent.get("nom") or ent.get("nom_entreprise") or ""
            lang = ent.get("langue_preferee") or "fr"
            msg_rel = analyzer.generer_message_relance_autonome(nom, rel["entity_type"], rel["etape"], lang)
            dest = (
                (ent.get("email") or ent.get("email_pro") or "")
                if rel["canal"] == "email"
                else ym.tel_normalise(ent.get("whatsapp") or ent.get("whatsapp_pro") or ent.get("tel") or "")
            )
            ts = utc_now()
            eid = con.execute(
                """INSERT INTO envois(
                    entity_type,entity_id,contact_id,canal,destination,message_final,
                    statut,resultat,consentement_id,consentement_preuve,step_number,autopilot,
                    historique_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,'valide','en_attente',?,?,?,1,?,?,?)""",
                (
                    rel["entity_type"],
                    rel["entity_id"],
                    rel["contact_id"],
                    rel["canal"],
                    dest,
                    msg_rel,
                    cons_id,
                    cons_msg,
                    int(rel["etape"]) + 1,
                    json.dumps([{"ts": ts, "event": f"relance_J+{rel['delai_jours']}", "actor": actor}], ensure_ascii=False),
                    ts,
                    ts,
                ),
            ).lastrowid
            envoi_row = dict(con.execute("SELECT * FROM envois WHERE id=?", (eid,)).fetchone())
            if dry_run:
                sent_items.append({"envoi_id": eid, "type": f"relance_J+{rel['delai_jours']}", "dry_run": True})
            else:
                try:
                    res = _executer_envoi_effectif(con, envoi_row, ent, actor=actor, mode="live", is_autopilot=True)
                    con.execute("UPDATE relances SET statut='envoyee', envoi_id=?, updated_at=? WHERE id=?", (eid, utc_now(), rel["id"]))
                    sent_items.append(res)
                except Exception as exc:
                    con.execute("UPDATE envois SET statut='echec', resultat='echec', error_detail=?, updated_at=? WHERE id=?", (str(exc)[:400], utc_now(), eid))
                    skipped.append({"entity": f"{rel['entity_type']}#{rel['entity_id']}", "reason": str(exc)})

        # B. Premiers contacts de niveau A (demandes B2C consenties + prospects B2B consentis)
        candidates = con.execute(
            "SELECT * FROM envois WHERE step_number=1 AND statut IN ('en_attente_validation','valide','programme') "
            "AND (scheduled_at='' OR substr(scheduled_at,1,10)<=?) ORDER BY id",
            (today_iso,),
        ).fetchall()
        for row in candidates:
            if used >= cap:
                skipped.append({"envoi_id": row["id"], "reason": f"Plafond quotidien ({cap}/jour) atteint"})
                break
            envoi_dict = dict(row)
            ent = _get_entity(con, envoi_dict["entity_type"], envoi_dict["entity_id"])
            if ent.get("classification") != "A" or ent.get("workflow_status") in ("bloque", "rejete", "exclu"):
                continue
            ok_c, _, cons_msg = verifier_consentement_envoi(
                con, entity_type=envoi_dict["entity_type"], entity_row=ent, canal=envoi_dict["canal"], is_autopilot=True
            )
            if not ok_c:
                skipped.append({"envoi_id": row["id"], "reason": cons_msg})
                continue
            if _sent_today_to_contact(con, envoi_dict["contact_id"]):
                skipped.append({"envoi_id": row["id"], "reason": "Jamais deux messages le même jour"})
                continue
            if dry_run:
                sent_items.append({"envoi_id": row["id"], "entity": f"{envoi_dict['entity_type']}#{envoi_dict['entity_id']}", "dry_run": True})
                used += 1
            else:
                try:
                    res = _executer_envoi_effectif(con, envoi_dict, ent, actor=actor, mode="live", is_autopilot=True)
                    sent_items.append(res)
                    used += 1
                except Exception as exc:
                    con.execute("UPDATE envois SET statut='echec', resultat='echec', error_detail=?, updated_at=? WHERE id=?", (str(exc)[:400], utc_now(), row["id"]))
                    skipped.append({"envoi_id": row["id"], "reason": str(exc)})

        _audit(con, actor, "autopilot_cycle", "envois", detail=f"sent={len(sent_items)}, skipped={len(skipped)}, dry_run={dry_run}")
        return {"ran": True, "dry_run": dry_run, "sent": len(sent_items), "items": sent_items, "skipped": skipped}


# ---------------------------------------------------------------------------
# FONCTIONNALITÉ 10 — Double Pipeline CRM (Familles & Professionnels)
# ---------------------------------------------------------------------------
def mettre_a_jour_pipeline(body: dict[str, Any], *, actor: str = "local") -> dict[str, Any]:
    """Met à jour l'étape CRM dédiée (Familles 8 étapes ou Professionnels 9 étapes) avec motif de perte obligatoire."""
    entity_type = _normalize_entity_type(str(body.get("entity_type") or ""))
    entity_id = int(body["entity_id"])
    stage = str(body.get("pipeline_stage") or body.get("etape") or "").strip()
    loss_reason = str(body.get("loss_reason") or body.get("motif_perte") or "").strip()[:500]
    notes = str(body.get("notes") or body.get("note") or "").strip()[:2000]

    if entity_type == "demande_b2c":
        if stage not in PIPELINE_FAMILLES:
            raise ValueError("Étape pipeline Familles invalide : " + ", ".join(PIPELINE_FAMILLES))
        if stage == "perdue" and not loss_reason:
            raise ValueError("Motif de perte obligatoire pour une demande perdue.")
        table = "demandes_clients"
    elif entity_type == "prospect_pro":
        if stage not in PIPELINE_PRO:
            raise ValueError("Étape pipeline Professionnels invalide : " + ", ".join(PIPELINE_PRO))
        if stage == "perdu" and not loss_reason:
            raise ValueError("Motif de perte obligatoire pour un prospect perdu.")
        table = "prospects"
    else:
        raise ValueError("entity_type attendu : demande_b2c ou prospect_pro")

    ts = utc_now()
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        _get_entity(con, entity_type, entity_id)
        con.execute(
            f"UPDATE {table} SET pipeline_stage=?, loss_reason=CASE WHEN ?!='' THEN ? ELSE loss_reason END, "
            "notes=CASE WHEN ?!='' THEN ? ELSE notes END, updated_at=? WHERE id=?",
            (stage, loss_reason, loss_reason, notes, notes, ts, entity_id),
        )
        # Ne plus relancer dès qu'il y a RDV, mission confirmée, gagné ou perdu
        if stage in ("rdv_programme", "besoin_confirme", "candidats_proposes", "mission_confirmee", "gagnee", "perdue", "proposition_envoyee", "gagne", "perdu"):
            con.execute(
                "UPDATE relances SET statut='annulee_pipeline', updated_at=? WHERE entity_type=? AND entity_id=? AND statut='prevue'",
                (ts, entity_type, entity_id),
            )
        _audit(con, actor, "pipeline_stage_maj", table, entity_id, detail=f"{stage} {loss_reason}".strip())
    return {"ok": True, "entity_type": entity_type, "entity_id": entity_id, "pipeline_stage": stage}


# ---------------------------------------------------------------------------
# FONCTIONNALITÉ 7 — Daily Prospect Digest (Email complet + WhatsApp court)
# ---------------------------------------------------------------------------
def generer_daily_digest(
    *,
    jour: date | None = None,
    base_url: str = "",
    limit: int = 10,
    actor: str = "system",
) -> dict[str, Any]:
    """Génère et persiste le rapport matinal « Daily Prospect Digest » (Email + WhatsApp + Dashboard).

    Règle stricte confidentialité WhatsApp : ne jamais inclure les coordonnées complètes
    (téléphone, email, adresse) d'un contact sensible sur WhatsApp — uniquement nom, score et lien sécurisé.
    """
    target_day = jour or v.today()
    iso = target_day.isoformat()
    root_url = (base_url or os.getenv("YALLAH_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")

    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        nouvelles_demandes = con.execute(
            "SELECT COUNT(*) FROM demandes_clients WHERE substr(created_at,1,10)=?", (iso,)
        ).fetchone()[0]
        demandes_a = con.execute(
            "SELECT COUNT(*) FROM demandes_clients WHERE classification='A' AND workflow_status NOT IN ('rejete','bloque')"
        ).fetchone()[0]
        prospects_a = con.execute(
            "SELECT COUNT(*) FROM prospects WHERE classification='A' AND workflow_status NOT IN ('rejete','bloque')"
        ).fetchone()[0]
        doublons_evites = (
            con.execute("SELECT COUNT(*) FROM demandes_clients WHERE motifs_exclusion LIKE '%Doublon%'").fetchone()[0]
            + con.execute("SELECT COUNT(*) FROM prospects WHERE motifs_exclusion LIKE '%Doublon%'").fetchone()[0]
        )
        contacts_rejetes = (
            con.execute("SELECT COUNT(*) FROM demandes_clients WHERE classification='Exclu' OR workflow_status='rejete'").fetchone()[0]
            + con.execute("SELECT COUNT(*) FROM prospects WHERE classification='Exclu' OR workflow_status='rejete'").fetchone()[0]
        )
        demandes_stop = con.execute("SELECT COUNT(*) FROM blocages").fetchone()[0]

        kpis = {
            "date": iso,
            "nouvelles_demandes": int(nouvelles_demandes),
            "demandes_qualifiees_a": int(demandes_a),
            "prospects_pro_qualifies_a": int(prospects_a),
            "doublons_evites": int(doublons_evites),
            "contacts_rejetes": int(contacts_rejetes),
            "demandes_stop": int(demandes_stop),
        }

        priorities: list[dict[str, Any]] = []

        # 1. Demandes B2C prioritaires (A puis B)
        for row in con.execute(
            "SELECT * FROM demandes_clients WHERE classification IN ('A','B') "
            "AND workflow_status IN ('en_attente_validation','valide','verification_demandee') "
            "ORDER BY CASE classification WHEN 'A' THEN 0 ELSE 1 END, score DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall():
            r = dict(row)
            msg_row = con.execute(
                "SELECT corps, canal FROM messages WHERE entity_type='demande_b2c' AND entity_id=? ORDER BY id DESC LIMIT 1",
                (r["id"],),
            ).fetchone()
            fiche_url = f"{root_url}/?page=demandes&fiche=demande_b2c:{r['id']}"
            canal = (msg_row["canal"] if msg_row else "") or r["canal_prefere"] or ("whatsapp" if r["consentement_whatsapp"] else "email")
            priorities.append(
                {
                    "entity_type": "demande_b2c",
                    "entity_id": r["id"],
                    "reference": r["reference"],
                    "nom": r["nom"] or "Famille",
                    "type_label": "Famille B2C",
                    "quartier_ville": ", ".join(x for x in (r["quartier"], r["ville"]) if x) or "À préciser",
                    "score": int(r["score"]),
                    "classification": r["classification"],
                    "besoin": analyzer.TYPES_PRESTATION.get(r["type_besoin"], {}).get("libelle", r["type_besoin"]),
                    "urgence": r["urgence"] or "à préciser",
                    "canal": canal,
                    "source": r["source"],
                    "message_recommande": msg_row["corps"] if msg_row else "",
                    "action_recommandee": r["action_recommandee"] or "Répondre et proposer un appel / RDV",
                    "sensible": bool(r["sensible"]),
                    "fiche_url": fiche_url,
                    "actions": {
                        "valider": f"{fiche_url}&action=valider",
                        "modifier": f"{fiche_url}&action=modifier_message",
                        "rejeter": f"{fiche_url}&action=rejeter",
                        "bloquer": f"{fiche_url}&action=bloquer",
                        "appeler": f"{fiche_url}&action=appeler",
                        "repondre_whatsapp": f"{fiche_url}&action=repondre_whatsapp",
                    },
                }
            )

        # 2. Prospects professionnels B2B prioritaires (A puis B)
        for row in con.execute(
            "SELECT * FROM prospects WHERE classification IN ('A','B') "
            "AND workflow_status IN ('en_attente_validation','valide','verification_demandee') "
            "ORDER BY CASE classification WHEN 'A' THEN 0 ELSE 1 END, score DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall():
            r = dict(row)
            msg_row = con.execute(
                "SELECT corps, canal FROM messages WHERE entity_type='prospect_pro' AND entity_id=? ORDER BY id DESC LIMIT 1",
                (r["id"],),
            ).fetchone()
            fiche_url = f"{root_url}/?page=b2b_pro&fiche=prospect_pro:{r['id']}"
            canal = (msg_row["canal"] if msg_row else "") or ("email" if r["email_pro"] else "appel")
            priorities.append(
                {
                    "entity_type": "prospect_pro",
                    "entity_id": r["id"],
                    "reference": r["reference"],
                    "nom": r["nom_entreprise"],
                    "type_label": f"Pro B2B ({r['type_etablissement']})",
                    "quartier_ville": ", ".join(x for x in (r["quartier"], r["ville"]) if x) or "Casablanca",
                    "score": int(r["score"]),
                    "classification": r["classification"],
                    "besoin": r["besoin_probable"] or "recrutement / renfort personnel",
                    "urgence": "planifiée",
                    "canal": canal,
                    "source": r["source_url"] or r["source_nom"],
                    "message_recommande": msg_row["corps"] if msg_row else "",
                    "action_recommandee": r["action_recommandee"] or "Valider et contacter",
                    "sensible": bool(r["sensible"]),
                    "fiche_url": fiche_url,
                    "actions": {
                        "valider": f"{fiche_url}&action=valider",
                        "modifier": f"{fiche_url}&action=modifier_message",
                        "rejeter": f"{fiche_url}&action=rejeter",
                        "bloquer": f"{fiche_url}&action=bloquer",
                        "appeler": f"{fiche_url}&action=appeler",
                        "repondre_whatsapp": f"{fiche_url}&action=repondre_whatsapp",
                    },
                }
            )

        # Classer : B2C A d'abord, puis B2B A, puis B par score décroissant — Top 5 à 10
        priorities.sort(
            key=lambda it: (
                0 if it["classification"] == "A" else 1,
                0 if it["entity_type"] == "demande_b2c" else 1,
                -it["score"],
            )
        )
        top_items = priorities[: max(5, min(10, limit))]

        # Format WhatsApp court (jamais de coordonnées complètes sur WhatsApp ; fiche sensible = nom + score + lien)
        wa_lines = [f"📋 Opportunités du jour — Yallah Services ({iso})"]
        wa_lines.append(
            f"Demandes : {kpis['nouvelles_demandes']} | B2C A : {kpis['demandes_qualifiees_a']} | "
            f"Pro A : {kpis['prospects_pro_qualifies_a']} | Doublons évités : {kpis['doublons_evites']} | STOP : {kpis['demandes_stop']}"
        )
        if not top_items:
            wa_lines.append("Aucune opportunité prioritaire en attente de validation aujourd’hui.")
        for idx, it in enumerate(top_items, start=1):
            if it["sensible"]:
                wa_lines.append(
                    f"\n{idx}. {it['nom']} — Score {it['score']}/100 (fiche sensible)\n"
                    f"Lien : {it['fiche_url']}"
                )
            else:
                wa_lines.append(
                    f"\n{idx}. {it['nom']} — {it['quartier_ville']} ({it['type_label']}) — Score {it['score']}/100\n"
                    f"Besoin : {it['besoin']}\n"
                    f"Urgence : {it['urgence']}\n"
                    f"Canal : {it['canal']}\n"
                    f"Action recommandée : {it['action_recommandee']}\n"
                    f"Lien : {it['fiche_url']}"
                )
        whatsapp_text = "\n".join(wa_lines)

        # Format Email complet (texte + HTML)
        email_subject = f"Yallah Services — Daily Prospect Digest ({iso}) : {kpis['demandes_qualifiees_a']} B2C A, {kpis['prospects_pro_qualifies_a']} Pro A"
        text_lines = [
            f"YALLAH SERVICES — RAPPORT QUOTIDIEN ({iso})",
            "=" * 50,
            f"- Nouvelles demandes reçues : {kpis['nouvelles_demandes']}",
            f"- Demandes familles qualifiées A : {kpis['demandes_qualifiees_a']}",
            f"- Prospects professionnels qualifiés A : {kpis['prospects_pro_qualifies_a']}",
            f"- Doublons évités : {kpis['doublons_evites']}",
            f"- Contacts invalides ou rejetés : {kpis['contacts_rejetes']}",
            f"- Demandes STOP / blocages : {kpis['demandes_stop']}",
            "",
            f"TOP {len(top_items)} PRIORITÉS DU JOUR",
            "-" * 50,
        ]
        html_cards = []
        for idx, it in enumerate(top_items, start=1):
            text_lines.append(
                f"{idx}. [{it['classification']} · {it['score']}/100] {it['nom']} ({it['type_label']} — {it['quartier_ville']})\n"
                f"   Besoin : {it['besoin']} | Urgence : {it['urgence']} | Canal : {it['canal']} | Source : {it['source']}\n"
                f"   Action recommandée : {it['action_recommandee']}\n"
                f"   Message préparé :\n   {it['message_recommande'].replace(chr(10), ' / ')}\n"
                f"   Fiche : {it['fiche_url']}\n"
            )
            html_cards.append(
                f"<div style='border:1px solid #dce5d4;border-radius:8px;padding:14px;margin:12px 0;background:#fafcf8'>"
                f"<strong>{idx}. {html_lib.escape(it['nom'])}</strong> — {html_lib.escape(it['type_label'])} — "
                f"{html_lib.escape(it['quartier_ville'])} — <strong>Score {it['score']}/100 ({html_lib.escape(it['classification'])})</strong><br>"
                f"<small>Besoin : {html_lib.escape(it['besoin'])} · Urgence : {html_lib.escape(it['urgence'])} · "
                f"Canal : {html_lib.escape(it['canal'])} · Source : {html_lib.escape(str(it['source']))}</small>"
                f"<p style='background:#f2f6ee;padding:10px;border-radius:6px;white-space:pre-wrap;font-size:13px'>{html_lib.escape(it['message_recommande'])}</p>"
                f"<p><strong>Action recommandée :</strong> {html_lib.escape(it['action_recommandee'])}</p>"
                f"<p>"
                f"<a href='{html_lib.escape(it['actions']['valider'], quote=True)}'>Valider</a> · "
                f"<a href='{html_lib.escape(it['actions']['modifier'], quote=True)}'>Modifier</a> · "
                f"<a href='{html_lib.escape(it['actions']['rejeter'], quote=True)}'>Rejeter</a> · "
                f"<a href='{html_lib.escape(it['actions']['bloquer'], quote=True)}'>Bloquer</a> · "
                f"<a href='{html_lib.escape(it['actions']['appeler'], quote=True)}'>Appeler</a> · "
                f"<a href='{html_lib.escape(it['actions']['repondre_whatsapp'], quote=True)}'>Répondre sur WhatsApp</a>"
                f"</p></div>"
            )
        email_text = "\n".join(text_lines)
        email_html = (
            "<!doctype html><html lang='fr'><body style='font-family:system-ui,sans-serif;color:#18352d;max-width:740px;margin:auto;padding:20px'>"
            f"<h1>Yallah Services — Opportunités du jour ({html_lib.escape(iso)})</h1>"
            f"<ul>"
            f"<li>Nouvelles demandes reçues : <strong>{kpis['nouvelles_demandes']}</strong></li>"
            f"<li>Demandes qualifiées A : <strong>{kpis['demandes_qualifiees_a']}</strong></li>"
            f"<li>Prospects pro qualifiés A : <strong>{kpis['prospects_pro_qualifies_a']}</strong></li>"
            f"<li>Doublons évités : <strong>{kpis['doublons_evites']}</strong></li>"
            f"<li>Contacts invalides / rejetés : <strong>{kpis['contacts_rejetes']}</strong></li>"
            f"<li>Demandes STOP / retraits : <strong>{kpis['demandes_stop']}</strong></li>"
            f"</ul>"
            + ("".join(html_cards) if html_cards else "<p>Aucune opportunité prioritaire en attente aujourd’hui.</p>")
            + "</body></html>"
        )

        ts = utc_now()
        dg_id = con.execute(
            """INSERT INTO daily_digests(
                digest_date,kpis_json,items_json,email_subject,email_html,email_text,whatsapp_text,
                email_status,whatsapp_status,created_at
            ) VALUES (?,?,?,?,?,?,?,'prepare','prepare',?)""",
            (
                iso,
                json.dumps(kpis, ensure_ascii=False),
                json.dumps(top_items, ensure_ascii=False),
                email_subject,
                email_html,
                email_text,
                whatsapp_text,
                ts,
            ),
        ).lastrowid
        _audit(con, actor, "daily_digest_genere", "daily_digests", dg_id, detail=f"{iso} · {len(top_items)} priorités")

    return {
        "id": dg_id,
        "digest_date": iso,
        "kpis": kpis,
        "items": top_items,
        "email_subject": email_subject,
        "email_html": email_html,
        "email_text": email_text,
        "whatsapp_text": whatsapp_text,
        "email_status": "prepare",
        "whatsapp_status": "prepare",
    }


def envoyer_daily_digest(
    digest_id: int | None = None,
    *,
    email_to: str = "",
    whatsapp_to: str = "",
    actor: str = "system",
) -> dict[str, Any]:
    """Envoie le Daily Prospect Digest interne à Yallah Services par Email et/ou WhatsApp si configuré."""
    with connect() as con:
        if digest_id:
            row = con.execute("SELECT * FROM daily_digests WHERE id=?", (int(digest_id),)).fetchone()
        else:
            row = con.execute("SELECT * FROM daily_digests ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            gen = generer_daily_digest(actor=actor)
            row = con.execute("SELECT * FROM daily_digests WHERE id=?", (gen["id"],)).fetchone()
        dg = dict(row)

    target_email = (email_to or os.getenv("YALLAH_DIGEST_EMAIL") or "").strip()
    target_wa = (whatsapp_to or os.getenv("YALLAH_DIGEST_WHATSAPP") or "").strip()

    email_status = "non_configure"
    wa_status = "non_configure"
    details = {}

    if target_email and connectors.EmailConnector.status()["configured"]:
        try:
            res = connectors.EmailConnector.send(
                target_email,
                dg["email_subject"],
                dg["email_text"],
                html_body=dg["email_html"],
                require_live_flag=True,
            )
            email_status = "envoye"
            details["email_provider_id"] = res["provider_id"]
        except Exception as exc:
            email_status = f"bloque: {exc}"
    elif target_email:
        email_status = "fournisseur_email_non_configure"

    if target_wa and connectors.WhatsAppConnector.status()["configured"]:
        try:
            res = connectors.WhatsAppConnector.send(
                target_wa,
                dg["whatsapp_text"],
                is_internal_digest=True,
                use_template=bool(os.getenv("WHATSAPP_TEMPLATE_NAME")),
                require_live_flag=True,
            )
            wa_status = "envoye"
            details["whatsapp_provider_id"] = res["provider_id"]
        except Exception as exc:
            wa_status = f"bloque: {exc}"
    elif target_wa:
        wa_status = "fournisseur_whatsapp_non_configure"

    ts = utc_now()
    with connect() as con:
        con.execute(
            "UPDATE daily_digests SET email_status=?, whatsapp_status=?, sent_at=? WHERE id=?",
            (email_status, wa_status, ts if (email_status == "envoye" or wa_status == "envoye") else "", dg["id"]),
        )
        _audit(con, actor, "daily_digest_envoi", "daily_digests", dg["id"], detail=f"email={email_status} | wa={wa_status}")

    return {"id": dg["id"], "email_status": email_status, "whatsapp_status": wa_status, **details}


# ---------------------------------------------------------------------------
# FONCTIONNALITÉ 11 — Tableau de bord “Acquisition autonome” & Export Audit
# ---------------------------------------------------------------------------
def tableau_bord_acquisition(con=None) -> dict[str, Any]:
    """Construit la vue complète de la page « Acquisition autonome », Demandes Clients, B2B Pro et File d'envoi."""

    def _build(db_con):
        today_iso = v.today().isoformat()
        demandes = [dict(r) for r in db_con.execute("SELECT * FROM demandes_clients ORDER BY CASE classification WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2 ELSE 3 END, score DESC, id DESC LIMIT 300").fetchall()]
        prospects = [dict(r) for r in db_con.execute("SELECT * FROM prospects ORDER BY CASE classification WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2 ELSE 3 END, score DESC, id DESC LIMIT 300").fetchall()]
        envois = [dict(r) for r in db_con.execute("SELECT * FROM envois ORDER BY id DESC LIMIT 300").fetchall()]
        relances = [dict(r) for r in db_con.execute("SELECT * FROM relances ORDER BY scheduled_for, etape LIMIT 300").fetchall()]
        blocages = [dict(r) for r in db_con.execute("SELECT * FROM blocages ORDER BY id DESC LIMIT 300").fetchall()]
        consentements = [dict(r) for r in db_con.execute("SELECT * FROM consentements ORDER BY id DESC LIMIT 300").fetchall()]
        reponses = [dict(r) for r in db_con.execute("SELECT * FROM reponses ORDER BY id DESC LIMIT 200").fetchall()]

        # Joindre dernier message préparé à chaque demande / prospect
        last_msgs: dict[tuple[str, int], dict[str, Any]] = {}
        for m in db_con.execute("SELECT * FROM messages ORDER BY id ASC").fetchall():
            last_msgs[(m["entity_type"], m["entity_id"])] = dict(m)
        for d in demandes:
            d["analyse"] = json.loads(d.pop("analyse_json", "{}") or "{}")
            d["score_details"] = json.loads(d.pop("score_details_json", "{}") or "{}")
            msg = last_msgs.get(("demande_b2c", d["id"]))
            d["message_prepare"] = msg["corps"] if msg else ""
            d["message_canal"] = msg["canal"] if msg else (d["canal_prefere"] or "whatsapp")
            d["message_langue"] = msg["langue"] if msg else d["langue_preferee"]
        for p in prospects:
            p["signaux_interet"] = json.loads(p.pop("signaux_interet_json", "[]") or "[]")
            p["score_details"] = json.loads(p.pop("score_details_json", "{}") or "{}")
            msg = last_msgs.get(("prospect_pro", p["id"]))
            p["message_prepare"] = msg["corps"] if msg else ""
            p["message_canal"] = msg["canal"] if msg else ("email" if p["email_pro"] else "appel")
            p["message_langue"] = msg["langue"] if msg else "fr"

        demandes_map = {d["id"]: d for d in demandes}
        prospects_map = {p["id"]: p for p in prospects}
        for e in envois:
            e["historique"] = json.loads(e.pop("historique_json", "[]") or "[]")
            if e["entity_type"] == "demande_b2c":
                ent = demandes_map.get(e["entity_id"], {})
                e["entity_nom"] = ent.get("nom") or ent.get("reference") or f"Demande #{e['entity_id']}"
                e["entity_ref"] = ent.get("reference", "")
            else:
                ent = prospects_map.get(e["entity_id"], {})
                e["entity_nom"] = ent.get("nom_entreprise") or ent.get("reference") or f"Prospect #{e['entity_id']}"
                e["entity_ref"] = ent.get("reference", "")

        # KPIs Acquisition autonome (14 indicateurs demandés)
        demandes_aujourdhui = sum(1 for d in demandes if d["created_at"][:10] == today_iso)
        demandes_a = sum(1 for d in demandes if d["classification"] == "A" and d["workflow_status"] not in ("rejete", "bloque"))
        prospects_a = sum(1 for p in prospects if p["classification"] == "A" and p["workflow_status"] not in ("rejete", "bloque"))
        messages_prets = sum(1 for e in envois if e["statut"] in ("en_attente_validation", "valide", "programme"))
        messages_envoyes = sum(1 for e in envois if e["statut"] == "envoye")
        reponses_recues = sum(1 for r in reponses if not r["stop_detecte"])
        if db_con.execute("SELECT 1 FROM sqlite_master WHERE name='conversations'").fetchone():
            messages_envoyes += db_con.execute("SELECT COUNT(*) FROM conversations WHERE direction='sortant'").fetchone()[0]
            reponses_recues += db_con.execute("SELECT COUNT(*) FROM conversations WHERE direction='entrant' AND outcome IN ('reponse','besoin')").fetchone()[0]
        taux_reponse = round((reponses_recues * 100.0 / messages_envoyes), 1) if messages_envoyes else 0.0

        rdv_obtenus = (
            sum(1 for d in demandes if d["pipeline_stage"] in ("rdv_programme", "besoin_confirme", "candidats_proposes", "mission_confirmee", "gagnee"))
            + sum(1 for p in prospects if p["pipeline_stage"] in ("rdv_programme", "besoin_confirme", "proposition_envoyee", "gagne"))
        )
        if db_con.execute("SELECT 1 FROM sqlite_master WHERE name='opportunities'").fetchone():
            rdv_obtenus += db_con.execute("SELECT COUNT(*) FROM opportunities WHERE stage IN ('rendez_vous','besoin_confirme','proposition','gagne')").fetchone()[0]

        missions_confirmees = sum(1 for d in demandes if d["pipeline_stage"] in ("mission_confirmee", "gagnee"))
        if db_con.execute("SELECT 1 FROM sqlite_master WHERE name='assignments'").fetchone():
            missions_confirmees += db_con.execute("SELECT COUNT(*) FROM assignments WHERE status IN ('planifiee','en_cours','terminee')").fetchone()[0]

        contacts_bloques = len(blocages)
        if db_con.execute("SELECT 1 FROM sqlite_master WHERE name='suppressions'").fetchone():
            contacts_bloques = max(contacts_bloques, db_con.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0])

        # Sources les plus performantes (B2C + B2B)
        src_counts: dict[str, dict[str, Any]] = {}
        for d in demandes:
            b = src_counts.setdefault(d["source"], {"source": d["source"], "total": 0, "qualifies_a": 0, "type": "B2C"})
            b["total"] += 1
            if d["classification"] == "A":
                b["qualifies_a"] += 1
        for p in prospects:
            b = src_counts.setdefault(p["source_nom"], {"source": p["source_nom"], "total": 0, "qualifies_a": 0, "type": "B2B"})
            b["total"] += 1
            if p["classification"] == "A":
                b["qualifies_a"] += 1
        top_sources = sorted(src_counts.values(), key=lambda x: (-x["qualifies_a"], -x["total"], x["source"]))[:8]

        # ROI par source en MAD/h réel (réutilise le grand livre réel de yallah_sources)
        roi_sources = ysources.calculer_roi_sources(db_con) if db_con.execute("SELECT 1 FROM sqlite_master WHERE name='ledger'").fetchone() else []

        # Estimation transparente du temps opérateur économisé :
        # ~4 min par demande analysée & scorée + ~3 min par message préparé + ~2 min par doublon évité
        doublons_evites = sum(1 for d in demandes if "Doublon" in d["motifs_exclusion"]) + sum(1 for p in prospects if "Doublon" in p["motifs_exclusion"])
        temps_economise_min = len(demandes) * 4 + len(prospects) * 2 + len(envois) * 3 + doublons_evites * 2

        # Alertes de conformité
        alertes_conformite: list[dict[str, str]] = []
        cfg = get_autopilot_config(db_con)
        if cfg.get("circuit_breaker_tripped"):
            alertes_conformite.append({"niveau": "critique", "message": cfg.get("circuit_breaker_reason", "Coupe-circuit Auto-pilot déclenché")})
        sans_consent_b2c = sum(1 for d in demandes if not d["consentement_recontact"] and d["workflow_status"] not in ("bloque", "rejete", "exclu"))
        if sans_consent_b2c:
            alertes_conformite.append({"niveau": "attention", "message": f"{sans_consent_b2c} demande(s) B2C sans consentement de recontact explicite — envoi bloqué (Loi 09-08)."})
        sans_wa_optin = sum(1 for d in demandes if d["message_canal"] == "whatsapp" and not d["consentement_whatsapp"] and d["workflow_status"] not in ("bloque", "rejete", "exclu"))
        if sans_wa_optin:
            alertes_conformite.append({"niveau": "attention", "message": f"{sans_wa_optin} demande(s) B2C sans opt-in WhatsApp distinct — utiliser email ou appel."})
        if contacts_bloques:
            alertes_conformite.append({"niveau": "info", "message": f"{contacts_bloques} contact(s) au registre permanent des blocages STOP / CNDP."})
        conn_st = connectors.connectors_status()
        if not conn_st["email"]["ready"] and not conn_st["whatsapp"]["ready"]:
            alertes_conformite.append({"niveau": "info", "message": "Mode simulation / validation manuelle actif : aucun fournisseur live activé côté serveur."})

        latest_digest_row = db_con.execute("SELECT * FROM daily_digests ORDER BY id DESC LIMIT 1").fetchone()
        latest_digest = None
        if latest_digest_row:
            dg = dict(latest_digest_row)
            dg["kpis"] = json.loads(dg.pop("kpis_json", "{}") or "{}")
            dg["items"] = json.loads(dg.pop("items_json", "[]") or "[]")
            latest_digest = dg

        return {
            "kpis": {
                "demandes_aujourdhui": demandes_aujourdhui,
                "demandes_qualifiees_a": demandes_a,
                "prospects_pro_qualifies_a": prospects_a,
                "messages_prets": messages_prets,
                "messages_envoyes": messages_envoyes,
                "reponses_recues": reponses_recues,
                "taux_reponse": taux_reponse,
                "rdv_obtenus": rdv_obtenus,
                "missions_confirmees": missions_confirmees,
                "contacts_bloques": contacts_bloques,
                "doublons_evites": doublons_evites,
                "temps_economise_minutes": temps_economise_min,
                "temps_economise_heures": round(temps_economise_min / 60.0, 1),
                "first_contacts_today": _first_contacts_sent_today(db_con),
                "max_first_contacts_per_day": int(cfg.get("max_first_contacts_per_day", 15)),
            },
            "top_sources": top_sources,
            "roi_sources": roi_sources,
            "alertes_conformite": alertes_conformite,
            "autopilot": cfg,
            "connectors": conn_st,
            "latest_digest": latest_digest,
            "demandes_clients": demandes,
            "prospects": prospects,
            "envois": envois,
            "relances": relances,
            "blocages": blocages,
            "consentements": consentements,
            "reponses": reponses,
            "sources_b2c": {k: v_info[0] for k, v_info in SOURCES_B2C_AUTORISEES.items()},
            "sources_b2b": {k: v_info[0] for k, v_info in SOURCES_B2B_AUTORISEES.items()},
            "pipeline_familles": list(PIPELINE_FAMILLES),
            "pipeline_pro": list(PIPELINE_PRO),
            "types_prestation": {k: v_info["libelle"] for k, v_info in analyzer.TYPES_PRESTATION.items()},
        }

    if con is not None:
        return _build(con)
    with connect() as db_con:
        return _build(db_con)


def exporter_audit(fmt: str = "csv") -> tuple[bytes, str]:
    """Exporte le journal d'audit (CSV anti-injection de formule ou JSON)."""
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT id, actor, action, entity, entity_id, detail, created FROM audit_log ORDER BY id DESC").fetchall()]
    if fmt == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8"
    out = io.StringIO()
    fields = ["id", "created", "actor", "action", "entity", "entity_id", "detail"]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        safe_row = {}
        for k in fields:
            val = "" if row.get(k) is None else str(row.get(k))
            if val.lstrip().startswith(("=", "+", "-", "@")):
                val = "'" + val
            safe_row[k] = val
        writer.writerow(safe_row)
    return ("\ufeff" + out.getvalue()).encode("utf-8"), "text/csv; charset=utf-8"
