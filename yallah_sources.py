#!/usr/bin/env python3
"""yallah_sources.py — Registre de sources A1–C, score, file du jour (J+3/J+7/J+14),
suivi du temps et ROI réel par source, greffé sur la base SQLite unifiée Yallah Services.

Stdlib uniquement, aucun module réseau, aucun envoi automatique : produit une file
à traiter À LA MAIN et mesure les encaissements réels enregistrés dans le CRM.
"""

import argparse
import csv
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

import validation as v
import yallah_b2c as b2c
import yallah_messages as messages
from yallah_prospection import SEGMENTS, phase_de

ROOT = Path(__file__).resolve().parent
PLAFOND = messages.MAX_PAR_JOUR          # 15 prises de contact sortantes max / jour
MAX_AGE = 7                              # fraîcheur max (jours) avant revalidation d'un 1er contact
RELANCES = (3, 7, 14)                    # relances manuelles J+3, J+7, J+14 servies avant les 1ers contacts
MAX_CONTACTS_MANUELS = 1 + len(RELANCES) # 1er contact + 3 relances = 4 maximum

ETAPES = (
    "nouveau",
    "contacte",
    "repondu",
    "qualifie",
    "candidat_presente",
    "contrat_valide",
    "perdu",
    "opt_out",
)
ETAPES_REPONSE = {"repondu", "qualifie", "candidat_presente", "contrat_valide"}

# Notes ordinales 1–5 = HYPOTHÈSES initiales d'ordonnancement.
# Les confronter aux mesures réelles via `--roi` (et dans Résultats et coûts).
SOURCES = {
    "site_formulaire": {
        "rang": "A1",
        "libelle": "Formulaire du site (quartier × besoin)",
        "intention": 5,
        "joignabilite": 5,
        "sollicite": True,
    },
    "whatsapp_entrant": {
        "rang": "A1",
        "libelle": "WhatsApp entrant traçable",
        "intention": 5,
        "joignabilite": 5,
        "sollicite": True,
    },
    "avito_demande": {
        "rang": "A2",
        "libelle": "Demande publique Avito.ma",
        "intention": 5,
        "joignabilite": 3,
        "sollicite": True,
    },
    "fb_groupe_demande": {
        "rang": "A3",
        "libelle": "Groupe Facebook (participation manuelle)",
        "intention": 5,
        "joignabilite": 2,
        "sollicite": True,
    },
    "gbp_entrant": {
        "rang": "A4",
        "libelle": "Fiche Google Business Profile",
        "intention": 5,
        "joignabilite": 4,
        "sollicite": True,
    },
    "partenaire_parrain": {
        "rang": "B1",
        "libelle": "Partenaire / prescripteur avec parrainage",
        "intention": 4,
        "joignabilite": 4,
        "sollicite": False,
    },
    "relocation_rh": {
        "rang": "B1",
        "libelle": "Relocation / RH multinationale / club expats",
        "intention": 4,
        "joignabilite": 2,
        "sollicite": False,
    },
    "clinique_senior": {
        "rang": "B2",
        "libelle": "Clinique / gériatre / kiné à domicile",
        "intention": 4,
        "joignabilite": 2,
        "sollicite": False,
    },
    "agence_immo": {
        "rang": "B3",
        "libelle": "Agence immobilière / syndic de résidence",
        "intention": 3,
        "joignabilite": 3,
        "sollicite": False,
    },
    "conciergerie": {
        "rang": "B3",
        "libelle": "Conciergerie privée",
        "intention": 3,
        "joignabilite": 3,
        "sollicite": False,
    },
    "creche_ecole": {
        "rang": "B4",
        "libelle": "Crèche / école maternelle privée",
        "intention": 2,
        "joignabilite": 3,
        "sollicite": False,
    },
    "liste_froide_b2b": {
        "rang": "C",
        "libelle": "Liste froide B2B sourcée",
        "intention": 1,
        "joignabilite": 3,
        "sollicite": False,
    },
}

ORDRE_RANGS = {"A1": 1, "A2": 2, "A3": 3, "A4": 4, "B1": 5, "B2": 6, "B3": 7, "B4": 8, "C": 9}


def norm_tel(t: str) -> str:
    """Normalise un téléphone marocain au format +212XXXXXXXXX (ou +indicatif international)."""
    d = re.sub(r"\D", "", t or "")
    if d.startswith("002120") and len(d) == 15:
        d = d[6:]
    elif d.startswith("00212"):
        d = d[5:]
    elif d.startswith("2120") and len(d) == 13:
        d = d[4:]
    elif d.startswith("212") and len(d) == 12:
        d = d[3:]
    elif d.startswith("0") and len(d) == 10:
        d = d[1:]
    if len(d) == 9:
        return "+212" + d
    if d.startswith("00") and len(d) > 10:
        return "+" + d[2:]
    if len(d) >= 10:
        return "+" + d
    return ""


normaliser_tel = norm_tel
normaliser_email = messages.email_normalise


def _ascii_slug_words(s: str) -> str:
    txt = unicodedata.normalize("NFKD", (s or "").strip()).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", txt).strip()


def cle_nom_ville(nom: str, ville: str) -> str:
    """Clé de dédoublonnage de repli nom|ville (lorsqu'aucun téléphone/email ne recoupe)."""
    n = _ascii_slug_words(nom)
    vl = _ascii_slug_words(ville)
    return f"nv:{n}|{vl}" if n and vl else ""


def cles_dedoublonnage(item: dict) -> list:
    """Clés de dédoublonnage ordonnées : téléphone (+212), email, puis nom|ville."""
    cles = []
    for champ in ("tel", "whatsapp"):
        nt = norm_tel(item.get(champ, ""))
        if nt:
            cles.append("tel:" + nt.lstrip("+"))
    mail = messages.email_normalise(item.get("email", ""))
    if mail:
        cles.append("mail:" + mail)
    nv = cle_nom_ville(item.get("nom", ""), item.get("ville", ""))
    if nv:
        cles.append(nv)
    return list(dict.fromkeys(cles))


def resoudre_source(kind: str, item: dict) -> str:
    """Résout la clé de source A1–C déclarée ou déduite du schéma existant."""
    explicite = str(item.get("source", "")).strip()
    if explicite in SOURCES:
        return explicite
    if item.get("source_type") == "entrant":
        origine = " ".join(
            str(item.get(k, "")) for k in ("origin", "canal_entrant", "source_canal", "contexte")
        ).lower()
        if "whatsapp" in origine:
            return "whatsapp_entrant"
        if "gbp" in origine or "google business" in origine:
            return "gbp_entrant"
        return "site_formulaire"
    url = str(item.get("source_url", "")).lower()
    if kind == "b2c":
        if "avito.ma" in url:
            return "avito_demande"
        if "facebook.com" in url or "fb.com" in url:
            return "fb_groupe_demande"
        return "avito_demande"
    seg = str(item.get("segment", "")).strip()
    if seg in ("relocation_rh", "clinique_senior", "agence_immo", "conciergerie", "creche_ecole"):
        return seg
    return "liste_froide_b2b"


def contact_manuel_autorise(
    kind: str,
    item: dict,
    has_active_permission: bool = False,
    is_suppressed: bool = False,
) -> tuple:
    """Verrou Loi 09-08 art. 10 adapté au choix opérationnel :
    - Refus / opt-out : toujours bloqué.
    - Sollicitation entrante ou consentement enregistré : autorisé.
    - Coordonnée professionnelle B2B publiée par l'établissement : autorisée en envoi manuel 1-à-1.
    - Particulier B2C non sollicité et sans consentement : bloqué.
    """
    if is_suppressed:
        return False, "contact inscrit au registre des refus"
    if item.get("exemple"):
        return False, "fiche d'exemple"
    if item.get("niveau") == "C" or not any(
        str(item.get(k, "")).strip() for k in ("tel", "whatsapp", "email")
    ):
        return False, "aucun contact direct publié"
    src_key = resoudre_source(kind, item)
    src = SOURCES[src_key]
    has_consent = bool(item.get("consentement_declare")) or bool(has_active_permission)
    if src["sollicite"] or has_consent:
        return True, "sollicitation ou consentement enregistré"
    if kind == "b2b":
        return True, "coordonnée professionnelle publique B2B (envoi manuel 1-à-1)"
    return False, "bloqué Loi 09-08 art. 10 : particulier non sollicité sans consentement"


def age_fiche(item: dict, today_date: date) -> int:
    """Âge en jours depuis la dernière vérification (ou la date de consultation initiale)."""
    ref = str(item.get("date_derniere_verification") or item.get("date_consultation") or "").strip()
    if not ref:
        return 999
    try:
        return (today_date - date.fromisoformat(ref[:10])).days
    except ValueError:
        return 999


def score_lead(kind: str, item: dict, today_date: date, source_key: str | None = None) -> int:
    """Score d'ordonnancement : intention × 3 + joignabilité × 2 + fraîcheur + niveau."""
    s = SOURCES[source_key or resoudre_source(kind, item)]
    age = age_fiche(item, today_date)
    fraicheur = 3 if 0 <= age <= 1 else 2 if 0 <= age <= MAX_AGE else 0
    verif = {"A": 3, "B": 1, "C": 0}.get(item.get("niveau", "B"), 0)
    return s["intention"] * 3 + s["joignabilite"] * 2 + fraicheur + verif


def _suppressed_set(con) -> set:
    suppressed = {r["contact_key"] for r in con.execute("SELECT contact_key FROM suppressions").fetchall()}
    for row in con.execute("SELECT value FROM settings WHERE key IN ('meta_b2b','meta_b2c')").fetchall():
        suppressed |= messages.exclusions_globales({"meta": json.loads(row["value"])})
    return suppressed


def _references_map(con) -> tuple:
    """Construit la correspondance bidirectionnelle id SQLite <-> référence métier (B2B-001, BC-001)."""
    id_to_ref = {}
    ref_to_id = {}
    counters = {"b2b": 0, "b2c": 0}
    for row in con.execute("SELECT id,kind FROM records WHERE kind IN ('b2b','b2c') ORDER BY id").fetchall():
        k = row["kind"]
        counters[k] += 1
        prefix = messages.TYPES[k]["prefixe"]
        ref = f"{prefix}-{counters[k]:03d}"
        id_to_ref[row["id"]] = ref
        ref_to_id[ref] = row["id"]
    return id_to_ref, ref_to_id


def construire_file_du_jour(
    con,
    today_date: date | None = None,
    plafond: int = PLAFOND,
    prenom: str = "",
    langue: str = "fr",
) -> dict:
    """Construit la file manuelle du jour :
    - Relances J+3 / J+7 / J+14 servies AVANT les 1ers contacts (prio 0 < prio 1).
    - Tri décroissant par score (intention × 3 + joignabilité × 2 + fraîcheur + niveau).
    - Respect strict du plafond quotidien partagé (15/jour) et du verrou Loi 09-08.
    """
    jour = today_date or v.today()
    iso = jour.isoformat()
    suppressed = _suppressed_set(con)
    id_to_ref, _ = _references_map(con)

    active_perms = {
        r["record_id"]
        for r in con.execute("SELECT DISTINCT record_id FROM permissions WHERE active=1").fetchall()
    }
    convs_by_rec = {}
    for c in con.execute(
        "SELECT record_id,channel,direction,outcome,created FROM conversations ORDER BY id"
    ).fetchall():
        convs_by_rec.setdefault(c["record_id"], []).append(dict(c))

    delivs_by_rec = {}
    for d in con.execute(
        "SELECT d.record_id,c.channel,d.status,d.attempted_at "
        "FROM deliveries d JOIN campaigns c ON c.id=d.campaign_id "
        "WHERE d.attempted_at!='' AND d.status IN ('accepted','delivered','read','unknown') ORDER BY d.id"
    ).fetchall():
        delivs_by_rec.setdefault(d["record_id"], []).append(dict(d))

    opps_by_rec = {}
    for o in con.execute("SELECT record_id,stage FROM opportunities ORDER BY id DESC").fetchall():
        opps_by_rec.setdefault(o["record_id"], []).append(o["stage"])

    mins_by_rec = dict(
        con.execute("SELECT record_id, COALESCE(SUM(minutes),0) FROM time_logs GROUP BY record_id").fetchall()
    ) if con.execute("SELECT 1 FROM sqlite_master WHERE name='time_logs'").fetchone() else {}

    used_ids = {
        rid
        for rid, cs in convs_by_rec.items()
        if any(c["direction"] == "sortant" and c["created"][:10] == iso for c in cs)
    } | {
        rid
        for rid, ds in delivs_by_rec.items()
        if any((d["attempted_at"] or "")[:10] == iso for d in ds)
    }
    used_today = len(used_ids)
    remaining_today = max(0, plafond - used_today)

    eligible_rows = []
    blocked_consent = 0
    stale_count = 0
    signataire = prenom.strip() or "Service Commercial"

    for rec in con.execute("SELECT id,kind,payload FROM records WHERE kind IN ('b2b','b2c') ORDER BY id").fetchall():
        rid = rec["id"]
        kind = rec["kind"]
        item = json.loads(rec["payload"])
        if item.get("exemple"):
            continue

        is_sup = bool(set(messages.cles_contact(item)) & suppressed)
        ok_consent, motif_consent = contact_manuel_autorise(
            kind, item, rid in active_perms, is_sup
        )
        if not ok_consent:
            if "Loi 09-08" in motif_consent:
                blocked_consent += 1
            continue

        convs = convs_by_rec.get(rid, [])
        if any(c["outcome"] == "refus" for c in convs):
            continue
        if any(c["direction"] == "entrant" and c["outcome"] in ("reponse", "besoin") for c in convs):
            continue

        stages = opps_by_rec.get(rid, [])
        if any(st in ("rendez_vous", "besoin_confirme", "proposition", "gagne", "perdu") for st in stages):
            continue

        outbounds = sorted(
            [(c["created"], c["channel"]) for c in convs if c["direction"] == "sortant" and len(c["created"]) >= 10]
            + [(d["attempted_at"], d["channel"]) for d in delivs_by_rec.get(rid, []) if len(d["attempted_at"]) >= 10],
            key=lambda x: x[0],
        )
        if rid in used_ids:
            continue

        n_out = len(outbounds)
        src_key = resoudre_source(kind, item)
        src_info = SOURCES[src_key]

        if n_out == 0:
            age = age_fiche(item, jour)
            if age > MAX_AGE or age < 0:
                stale_count += 1
                continue
            prio = 1
            action_kind = "1er contact"
            relance_step = 0
            days_since = 0
            msg = messages.generer_message(item, kind, langue, signataire)
            alertes = messages.verifier_message(msg)
            canal = messages.canal_recommande(item)
            bascule_mobile = False
            wa = messages.lien_whatsapp(item, msg) if not alertes else ""
            mail = messages.lien_email(item, msg, kind) if not alertes else ""
        elif 1 <= n_out <= len(RELANCES):
            if any(st == "conversation" for st in stages):
                continue
            delai = RELANCES[n_out - 1]
            last_ts = outbounds[-1][0]
            first_ch = outbounds[0][1] or "email"
            try:
                days_since = (jour - date.fromisoformat(last_ts[:10])).days
            except ValueError:
                continue
            if days_since < delai:
                continue
            prio = 0
            action_kind = f"Relance J+{delai}"
            relance_step = n_out
            pack = messages.liens_relance(item, kind, langue, signataire, first_ch, etape_relance=n_out)
            msg = pack["message"]
            canal = pack["canal_recommande"]
            bascule_mobile = pack["bascule_mobile"]
            wa = pack["lien_whatsapp"]
            mail = pack["lien_email"]
        else:
            continue

        sc = score_lead(kind, item, jour, src_key)
        contact_affiche = (
            item.get("email")
            or item.get("whatsapp")
            or item.get("tel")
            or ""
        )
        eligible_rows.append(
            {
                "prio": prio,
                "score": sc,
                "record_id": rid,
                "ref": id_to_ref.get(rid, f"#{rid}"),
                "kind": kind,
                "action_kind": action_kind,
                "relance_step": relance_step,
                "days_since": days_since,
                "nom": item.get("nom", ""),
                "ville": item.get("ville", ""),
                "zone": item.get("zone", ""),
                "niveau": item.get("niveau", "B"),
                "source": src_key,
                "source_rang": src_info["rang"],
                "source_libelle": src_info["libelle"],
                "source_url": item.get("source_url") or item.get("source_reference", ""),
                "contact": contact_affiche,
                "canal_recommande": canal,
                "bascule_mobile": bascule_mobile,
                "lien_whatsapp": wa,
                "lien_email": mail,
                "message": msg,
                "minutes": int(mins_by_rec.get(rid, 0)),
            }
        )

    eligible_rows.sort(key=lambda r: (r["prio"], -r["score"], r["record_id"]))
    shown = eligible_rows[:remaining_today]
    return {
        "date": iso,
        "plafond": plafond,
        "used_today": used_today,
        "remaining_today": remaining_today,
        "eligible_total": len(eligible_rows),
        "blocked_consent": blocked_consent,
        "stale_count": stale_count,
        "items": shown,
    }


def calculer_roi_sources(con) -> list:
    """Calcule le ROI réel par source A1–C uniquement sur les montants saisis dans `ledger` (0 MAD sinon)."""
    recs = {}
    for r in con.execute("SELECT id,kind,payload FROM records WHERE kind IN ('b2b','b2c')").fetchall():
        item = json.loads(r["payload"])
        if item.get("exemple"):
            continue
        recs[r["id"]] = {"kind": r["kind"], "data": item, "source": resoudre_source(r["kind"], item)}

    convs_by_rec = {}
    for c in con.execute("SELECT record_id,direction,outcome FROM conversations").fetchall():
        convs_by_rec.setdefault(c["record_id"], []).append(dict(c))

    deliv_recs = {
        r["record_id"]
        for r in con.execute(
            "SELECT DISTINCT record_id FROM deliveries WHERE status IN ('accepted','delivered','read','unknown')"
        ).fetchall()
    }

    opps_by_rec = {}
    for o in con.execute("SELECT id,record_id,stage FROM opportunities").fetchall():
        opps_by_rec.setdefault(o["record_id"], []).append(dict(o))

    ledger_by_opp = {}
    for l in con.execute(
        "SELECT opportunity_id,kind,amount_cents FROM ledger WHERE opportunity_id IS NOT NULL"
    ).fetchall():
        b = ledger_by_opp.setdefault(l["opportunity_id"], {"facture": 0, "encaissement": 0, "cout": 0})
        if l["kind"] in b:
            b[l["kind"]] += l["amount_cents"]

    mins_by_rec = dict(
        con.execute("SELECT record_id, COALESCE(SUM(minutes),0) FROM time_logs GROUP BY record_id").fetchall()
    ) if con.execute("SELECT 1 FROM sqlite_master WHERE name='time_logs'").fetchone() else {}

    # Missions actives/terminées rattachées à un client via un besoin emploi
    mission_clients = set()
    for need_row in con.execute("SELECT id,payload FROM records WHERE kind='emploi'").fetchall():
        nd = json.loads(need_row["payload"])
        cid = nd.get("client_id")
        if not cid:
            continue
        has_mission = con.execute(
            "SELECT 1 FROM assignments m JOIN applications a ON a.id=m.application_id "
            "WHERE a.need_id=? AND m.status IN ('planifiee','en_cours','terminee')",
            (need_row["id"],),
        ).fetchone()
        if has_mission:
            mission_clients.add(int(cid))

    buckets = {}
    for rid, info in recs.items():
        s_key = info["source"]
        s_meta = SOURCES[s_key]
        b = buckets.setdefault(
            s_key,
            {
                "source": s_key,
                "rang": s_meta["rang"],
                "libelle": s_meta["libelle"],
                "hypothese_intention": s_meta["intention"],
                "hypothese_joignabilite": s_meta["joignabilite"],
                "sollicite": s_meta["sollicite"],
                "leads": 0,
                "contacted": 0,
                "replied": 0,
                "confirmed": 0,
                "contracts": 0,
                "minutes": 0,
                "hours": 0.0,
                "invoiced_cents": 0,
                "received_cents": 0,
                "cost_cents": 0,
            },
        )
        b["leads"] += 1
        convs = convs_by_rec.get(rid, [])
        opps = opps_by_rec.get(rid, [])

        is_contacted = (
            any(c["direction"] == "sortant" for c in convs)
            or rid in deliv_recs
            or info["data"].get("source_type") == "entrant"
        )
        has_reply = (
            any(c["direction"] == "entrant" and c["outcome"] in ("reponse", "besoin") for c in convs)
            or any(o["stage"] in ("conversation", "rendez_vous", "besoin_confirme", "proposition", "gagne") for o in opps)
        )
        has_confirmed = any(o["stage"] in ("besoin_confirme", "proposition", "gagne") for o in opps)
        has_contract = any(o["stage"] == "gagne" for o in opps) or (rid in mission_clients)

        if is_contacted:
            b["contacted"] += 1
        if has_reply:
            b["replied"] += 1
        if has_confirmed:
            b["confirmed"] += 1
        if has_contract:
            b["contracts"] += 1

        b["minutes"] += int(mins_by_rec.get(rid, 0))
        for o in opps:
            lb = ledger_by_opp.get(o["id"])
            if lb:
                b["invoiced_cents"] += lb["facture"]
                b["received_cents"] += lb["encaissement"]
                b["cost_cents"] += lb["cout"]

    rows = []
    for b in buckets.values():
        invoiced = round(b["invoiced_cents"] / 100.0, 2)
        received = round(b["received_cents"] / 100.0, 2)
        cost = round(b["cost_cents"] / 100.0, 2)
        net = round(received - cost, 2)
        hours = round(b["minutes"] / 60.0, 2)
        mad_per_hour = round(received / (b["minutes"] / 60.0), 2) if b["minutes"] > 0 else 0.0
        reply_rate = round(b["replied"] * 100.0 / b["contacted"], 1) if b["contacted"] else 0.0
        rows.append(
            {
                "source": b["source"],
                "rang": b["rang"],
                "libelle": b["libelle"],
                "hypothese_intention": b["hypothese_intention"],
                "hypothese_joignabilite": b["hypothese_joignabilite"],
                "sollicite": b["sollicite"],
                "leads": b["leads"],
                "contacted": b["contacted"],
                "replied": b["replied"],
                "reply_rate": reply_rate,
                "confirmed": b["confirmed"],
                "contracts": b["contracts"],
                "minutes": b["minutes"],
                "hours": hours,
                "invoiced_mad": invoiced,
                "received_mad": received,
                "cost_mad": cost,
                "net_mad": net,
                "mad_per_hour": mad_per_hour,
            }
        )

    rows.sort(
        key=lambda r: (
            -r["received_mad"],
            -r["contracts"],
            -r["replied"],
            ORDRE_RANGS.get(r["rang"], 99),
            r["source"],
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Connexion SQLite unifiée (sans import d'aucune bibliothèque réseau)
# ---------------------------------------------------------------------------
def default_db_path() -> Path:
    return Path(os.environ.get("YALLAH_DB", ROOT / "data" / "yallah.sqlite3"))


def connect_db(db_path: Path | None = None):
    target = Path(db_path or default_db_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con


def ensure_db(db_path: Path | None = None) -> Path:
    """Initialise la base SQLite unifiée Yallah si absente, sans démarrer de serveur ni de réseau."""
    import operations

    target = Path(db_path or default_db_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect_db(target) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, record_id INTEGER, action TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS permissions (
                record_id INTEGER NOT NULL, channel TEXT NOT NULL, destination TEXT NOT NULL,
                proof TEXT NOT NULL, confirmed_at TEXT NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY(record_id, channel));
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, channel TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'simulation', status TEXT NOT NULL DEFAULT 'draft',
                signer TEXT NOT NULL, language TEXT NOT NULL, created TEXT NOT NULL,
                legal_proof TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL, record_id INTEGER NOT NULL,
                destination TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '', provider_id TEXT NOT NULL DEFAULT '',
                attempted_at TEXT, created TEXT NOT NULL,
                UNIQUE(campaign_id, record_id));
            CREATE TABLE IF NOT EXISTS suppressions (contact_key TEXT PRIMARY KEY, created TEXT NOT NULL);
            """
        )
        if not con.execute("SELECT 1 FROM settings WHERE key='initialized'").fetchone():
            for kind, filename, key in [
                ("b2b", "prospects_b2b.json", "prospects"),
                ("b2c", "prospects_b2c.json", "prospects"),
                ("emploi", "besoins_emploi.json", "besoins"),
            ]:
                source = json.loads((ROOT / filename).read_text(encoding="utf-8"))
                for item in source[key]:
                    con.execute(
                        "INSERT INTO records(kind,payload) VALUES (?,?)",
                        (kind, json.dumps(item, ensure_ascii=False)),
                    )
                con.execute(
                    "INSERT OR REPLACE INTO settings VALUES (?,?)",
                    ("meta_" + kind, json.dumps(source.get("meta", {}))),
                )
            con.execute("INSERT INTO settings VALUES ('initialized','yes')")
    operations.configure(lambda: connect_db(target))
    target.chmod(0o600)
    return target


def resoudre_identifiant(con, ident: str) -> int:
    """Accepte soit un ID numérique SQLite ('12'), soit une référence métier ('B2B-001', 'BC-002')."""
    brut = str(ident or "").strip()
    if brut.isdigit():
        rid = int(brut)
        row = con.execute("SELECT id FROM records WHERE id=? AND kind IN ('b2b','b2c')", (rid,)).fetchone()
        if not row:
            raise ValueError(f"Prospect introuvable : #{rid}")
        return rid
    _, ref_to_id = _references_map(con)
    rid = ref_to_id.get(brut.upper())
    if not rid:
        raise ValueError(f"Référence prospect introuvable : {brut}")
    return rid


def importer_csv(path: str, db_path: Path | None = None, actor: str = "cli") -> dict:
    """Importe un CSV de veille (ex. veille.csv) dans la base SQLite unifiée avec dédoublonnage +212/email/nom|ville."""
    import operations

    target = ensure_db(db_path)
    ajoutes, doublons, refuses = 0, 0, 0
    erreurs = []

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        lignes_csv = list(reader)

    with connect_db(target) as con:
        con.execute("BEGIN IMMEDIATE")
        seen_contacts = set()
        seen_nv = set()
        for row in con.execute("SELECT payload FROM records WHERE kind IN ('b2b','b2c')").fetchall():
            existing = json.loads(row["payload"])
            if existing.get("exemple"):
                continue
            for ck in cles_dedoublonnage(existing):
                if ck.startswith("nv:"):
                    seen_nv.add(ck)
                else:
                    seen_contacts.add(ck)

        for idx, r in enumerate(lignes_csv, start=1):
            source = (r.get("source") or "").strip()
            url_source = (r.get("url_source") or r.get("source_url") or "").strip()
            date_source = (r.get("date_source") or r.get("date_consultation") or "").strip()
            nom = (r.get("nom") or "").strip()
            ville = (r.get("ville") or "").strip()

            if not (nom and ville and url_source and date_source) or source not in SOURCES:
                refuses += 1
                erreurs.append(f"Ligne {idx} : nom, ville, source reconnue, url_source et date_source requis")
                continue

            try:
                v.url(url_source)
                v.day(date_source, "date_source", past=True)
            except ValueError as exc:
                refuses += 1
                erreurs.append(f"Ligne {idx} : {exc}")
                continue

            tel = norm_tel(r.get("tel") or "")
            whatsapp = norm_tel(r.get("whatsapp") or "")
            email = (r.get("email") or "").strip().lower()
            niveau = (r.get("niveau") or "B").strip().upper()
            try:
                consent_flag = bool(int(r.get("consentement") or 0))
            except ValueError:
                refuses += 1
                erreurs.append(f"Ligne {idx} : consentement invalide (0 ou 1 attendu)")
                continue

            seg_raw = (r.get("segment") or "").strip().lower()
            besoin_raw = (r.get("besoin") or "").strip().upper()

            if seg_raw == "b2c" or (not seg_raw and source in ("avito_demande", "fb_groupe_demande", "site_formulaire", "whatsapp_entrant", "gbp_entrant")):
                kind = "b2c"
                code_besoin = besoin_raw if besoin_raw in b2c.BESOINS else "MEN"
                item = {
                    "nom": nom,
                    "besoin": code_besoin,
                    "ville": ville,
                    "zone": (r.get("zone") or "À préciser").strip(),
                    "tel": tel,
                    "whatsapp": whatsapp,
                    "email": email,
                    "source": source,
                    "source_url": url_source,
                    "date_consultation": date_source,
                    "date_derniere_verification": date_source,
                    "niveau": niveau,
                    "consentement_declare": consent_flag,
                }
                if r.get("contexte"):
                    item["contexte"] = str(r["contexte"]).strip()
            else:
                kind = "b2b"
                seg = seg_raw if seg_raw in SEGMENTS else (source if source in SEGMENTS else "commerce")
                item = {
                    "nom": nom,
                    "segment": seg,
                    "phase": int(r["phase"]) if str(r.get("phase") or "").isdigit() else phase_de({"ville": ville}),
                    "ville": ville,
                    "zone": (r.get("zone") or "Ville entière").strip(),
                    "tel": tel,
                    "whatsapp": whatsapp,
                    "email": email,
                    "source": source,
                    "source_url": url_source,
                    "date_consultation": date_source,
                    "date_derniere_verification": date_source,
                    "niveau": niveau,
                    "consentement_declare": consent_flag,
                }

            try:
                v.record(kind, item)
            except ValueError as exc:
                refuses += 1
                erreurs.append(f"Ligne {idx} : {exc}")
                continue

            dedup_keys = cles_dedoublonnage(item)
            contact_keys = [k for k in dedup_keys if not k.startswith("nv:")]
            nv_keys = [k for k in dedup_keys if k.startswith("nv:")]

            if (contact_keys and (set(contact_keys) & seen_contacts)) or (
                not contact_keys and nv_keys and (set(nv_keys) & seen_nv)
            ) or (nv_keys and (set(nv_keys) & seen_nv) and not contact_keys):
                doublons += 1
                continue

            # Dédoublonnage secondaire nom|ville si même établissement sans recouvrement téléphonique
            if nv_keys and (set(nv_keys) & seen_nv) and contact_keys:
                # Même nom et même ville déjà en base -> doublon
                doublons += 1
                continue

            con.execute(
                "INSERT INTO records(kind,payload) VALUES (?,?)",
                (kind, json.dumps(item, ensure_ascii=False)),
            )
            seen_contacts.update(contact_keys)
            seen_nv.update(nv_keys)
            ajoutes += 1

        if ajoutes:
            operations.audit(con, actor, "import_sources_csv", "records", detail=f"{ajoutes} ajoutés ({Path(path).name})")

    return {"added": ajoutes, "duplicates": doublons, "rejected": refuses, "errors": erreurs}


def marquer_etape(ident: str, etape: str, db_path: Path | None = None, actor: str = "cli") -> dict:
    """Met à jour l'étape d'un prospect dans la base SQLite unifiée (conversations, opportunités, refus)."""
    import operations

    if etape not in ETAPES:
        raise ValueError(f"Étape inconnue : {etape} (attendu : {', '.join(ETAPES)})")
    target = ensure_db(db_path)
    today_iso = v.today().isoformat()

    with connect_db(target) as con:
        con.execute("BEGIN IMMEDIATE")
        rid = resoudre_identifiant(con, ident)
        row = operations.prospect(con, rid)
        item = json.loads(row["payload"])

        if etape == "opt_out":
            operations.suppress(con, rid, actor)
            con.execute(
                "INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,'interne','entrant','Retrait / opt-out déclaré en CLI','refus',?)",
                (rid, operations.now()),
            )
            operations.audit(con, actor, "etape_opt_out", "records", rid)
            return {"record_id": rid, "etape": etape}

        if etape == "contacte":
            suppressed = _suppressed_set(con)
            has_perm = bool(
                con.execute("SELECT 1 FROM permissions WHERE record_id=? AND active=1", (rid,)).fetchone()
            )
            ok_consent, motif = contact_manuel_autorise(
                row["kind"], item, has_perm, bool(set(messages.cles_contact(item)) & suppressed)
            )
            if not ok_consent:
                raise ValueError(motif)
            out_cnt = con.execute(
                "SELECT COUNT(*) FROM conversations WHERE record_id=? AND direction='sortant'",
                (rid,),
            ).fetchone()[0]
            if out_cnt >= MAX_CONTACTS_MANUELS:
                raise ValueError(
                    f"Limite atteinte : 1er contact + {len(RELANCES)} relances ({'/'.join('J+'+str(d) for d in RELANCES)}) maximum"
                )
            already_today = con.execute(
                "SELECT 1 FROM conversations WHERE record_id=? AND direction='sortant' AND substr(created,1,10)=?",
                (rid, today_iso),
            ).fetchone()
            if not already_today and operations.quota_journalier(con)["remaining"] <= 0:
                raise ValueError(f"Plafond quotidien atteint : {PLAFOND} prises de contact maximum par jour")
            res = operations.enregistrer_envoi_manuel(con, rid, "", "Envoi manuel enregistré (CLI --etape)", actor)
            operations.audit(con, actor, "etape_contacte", "records", rid)
            return {"record_id": rid, "etape": etape, **res}

        if etape == "repondu":
            ch = messages.canal_recommande(item) or "interne"
            con.execute(
                "INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,?,'entrant','Réponse reçue (CLI --etape)','reponse',?)",
                (rid, ch, operations.now()),
            )
            rep = operations.traiter_reponse_entrante(con, rid, ch, "Réponse reçue", actor)
            operations.audit(con, actor, "etape_repondu", "records", rid)
            return {"record_id": rid, "etape": etape, **rep}

        stage_map = {
            "nouveau": ("prospect", "Vérifier et préparer le 1er contact", ""),
            "qualifie": ("besoin_confirme", "Présenter un premier profil candidat", ""),
            "candidat_presente": ("proposition", "Recueillir le retour sur le profil présenté", ""),
            "contrat_valide": ("gagne", "Suivre le démarrage de la prestation", ""),
            "perdu": ("perdu", "Dossier clôturé", "Perdu (déclaré via CLI --etape)"),
        }
        new_stage, next_act, loss = stage_map[etape]
        opp = con.execute(
            "SELECT * FROM opportunities WHERE record_id=? ORDER BY id DESC LIMIT 1",
            (rid,),
        ).fetchone()
        if opp:
            oid = opp["id"]
            con.execute(
                "UPDATE opportunities SET stage=?,next_action=?,due=?,loss_reason=?,updated=? WHERE id=?",
                (new_stage, next_act, today_iso, loss or opp["loss_reason"], operations.now(), oid),
            )
        else:
            oid = con.execute(
                "INSERT INTO opportunities(record_id,title,stage,owner,next_action,due,loss_reason,created,updated) VALUES (?,?,?,'Service Commercial',?,?,?,? ,?)",
                (
                    rid,
                    f"Suivi {row['kind'].upper()} — {item.get('nom', 'Prospect')}",
                    new_stage,
                    next_act,
                    today_iso,
                    loss,
                    operations.now(),
                    operations.now(),
                ),
            ).lastrowid
        if etape in ETAPES_REPONSE or etape == "perdu":
            con.execute(
                "UPDATE tasks SET status='annulee' WHERE opportunity_id=? AND status='a_faire' AND title LIKE 'Relance J+%'",
                (oid,),
            )
        operations.audit(con, actor, f"etape_{etape}", "opportunities", oid)
        return {"record_id": rid, "opportunity_id": oid, "etape": etape, "stage": new_stage}


def marquer_verifie_db(idents: list, db_path: Path | None = None, actor: str = "cli") -> list:
    """Estampille `date_derniere_verification` à aujourd'hui pour les IDs ou références indiqués."""
    import operations

    target = ensure_db(db_path)
    today_iso = v.today().isoformat()
    stamped = []
    with connect_db(target) as con:
        con.execute("BEGIN IMMEDIATE")
        for ident in idents:
            rid = resoudre_identifiant(con, ident)
            row = con.execute("SELECT payload FROM records WHERE id=?", (rid,)).fetchone()
            item = json.loads(row["payload"])
            prev = item.get("date_consultation", "")
            item.setdefault("date_collecte_originale", prev)
            con.execute(
                "INSERT INTO verifications(record_id,source_url,previous_date,actor,created) VALUES (?,?,?,?,?)",
                (rid, item.get("source_url", ""), prev, actor, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            item["date_derniere_verification"] = today_iso
            item["date_consultation"] = today_iso
            con.execute(
                "UPDATE records SET payload=? WHERE id=?",
                (json.dumps(item, ensure_ascii=False), rid),
            )
            operations.audit(con, actor, "verifie_cli", "records", rid)
            stamped.append(rid)
    return stamped


def enregistrer_temps_db(
    ident: str,
    minutes: int,
    note: str = "",
    db_path: Path | None = None,
    actor: str = "cli",
) -> dict:
    """Enregistre des minutes de travail sur un prospect dans `time_logs`."""
    import operations

    target = ensure_db(db_path)
    mins = int(v.number(minutes, "Minutes", minimum=1, maximum=600))
    with connect_db(target) as con:
        rid = resoudre_identifiant(con, ident)
    old_connect = operations.connect
    operations.connect = lambda: connect_db(target)
    try:
        return operations.execute(
            "time_log",
            {"record_id": rid, "minutes": mins, "note": note, "day": v.today().isoformat()},
            actor,
        )
    finally:
        operations.connect = old_connect


# ---------------------------------------------------------------------------
# Affichage CLI
# ---------------------------------------------------------------------------
def afficher_sources() -> None:
    print(f"{'rang':<5}{'source':<22}{'int.':>5}{'joign.':>7}{'sollicité':>11}  libellé")
    print("-" * 86)
    for k, s in sorted(SOURCES.items(), key=lambda x: (ORDRE_RANGS[x[1]["rang"]], x[0])):
        sol = "oui" if s["sollicite"] else "non"
        print(f"{s['rang']:<5}{k:<22}{s['intention']:>5}{s['joignabilite']:>7}{sol:>11}  {s['libelle']}")
    print("\nNote : les notes 1–5 sont des hypothèses d'ordonnancement à confronter à `--roi`.")


def afficher_file(db_path: Path | None, prenom: str, langue: str) -> None:
    target = ensure_db(db_path)
    with connect_db(target) as con:
        res = construire_file_du_jour(con, v.today(), PLAFOND, prenom, langue)
    for r in res["items"]:
        canal = r["canal_recommande"] or "—"
        bascule = "->WA" if r["bascule_mobile"] else ""
        print(
            f"#{r['record_id']:<4} ({r['ref']:<7}) {r['action_kind']:<13} "
            f"{r['score']:>2} pts  {r['nom']} ({r['ville']}) "
            f"[{r['source_rang']}:{r['source']}] {canal}{bascule} {r['contact']} <{r['source_url']}>"
        )
    print(
        f"-- {len(res['items'])}/{res['eligible_total']} affichés "
        f"(quota du jour : {res['used_today']}/{res['plafond']} envoyés, "
        f"{res['remaining_today']} restant(s) · {res['stale_count']} >{MAX_AGE}j à revérifier · "
        f"{res['blocked_consent']} bloqué(s) Loi 09-08)"
    )


def afficher_roi(db_path: Path | None) -> None:
    target = ensure_db(db_path)
    with connect_db(target) as con:
        rows = calculer_roi_sources(con)
    print(
        f"{'rang':<5}{'source':<20}{'leads':>6}{'contact':>8}{'rép.':>6}"
        f"{'contrats':>9}{'heures':>8}{'facturé':>10}{'encaissé':>10}{'MAD/h':>9}"
    )
    print("-" * 91)
    for r in rows:
        print(
            f"{r['rang']:<5}{r['source']:<20}{r['leads']:>6}{r['contacted']:>8}{r['replied']:>6}"
            f"{r['contracts']:>9}{r['hours']:>8.2f}{r['invoiced_mad']:>10.0f}"
            f"{r['received_mad']:>10.0f}{r['mad_per_hour']:>9.0f}"
        )
    print(
        "\nNote : montants calculés uniquement sur les factures/encaissements réels saisis "
        "dans le CRM (0 MAD tant que non facturé/encaissé)."
    )


def main():
    p = argparse.ArgumentParser(
        description="Yallah Services — Registre de sources A1–C, file du jour et ROI réel (aucun envoi)"
    )
    p.add_argument("--db", help="chemin de la base SQLite (défaut : data/yallah.sqlite3 ou YALLAH_DB)")
    p.add_argument("--sources", action="store_true", help="affiche le référentiel des sources A1–C")
    p.add_argument("--importer", metavar="CSV", help="importe un CSV de veille dans la base unifiée")
    p.add_argument("--file", action="store_true", help="affiche la file manuelle du jour (plafond 15)")
    p.add_argument("--prenom", default=os.getenv("YALLAH_PRENOM", ""), help="signataire des messages préparés")
    p.add_argument("--langue", choices=["fr", "darija", "arabe"], default="fr")
    p.add_argument("--etape", nargs=2, metavar=("ID_OU_REF", "ETAPE"), help="met à jour l'étape d'un prospect")
    p.add_argument("--verifie", nargs="+", metavar="ID_OU_REF", help="marque les fiches revérifiées aujourd'hui")
    p.add_argument("--temps", nargs=2, metavar=("ID_OU_REF", "MIN"), help="ajoute des minutes passées sur un dossier")
    p.add_argument("--note", default="", help="note optionnelle pour --temps")
    p.add_argument("--roi", action="store_true", help="affiche le tableau de ROI réel par source")
    p.add_argument("--envoyer", action="store_true", help="refusé : aucun envoi automatique")
    args = p.parse_args()

    if args.envoyer:
        sys.exit(
            "Envoi automatique refusé : yallah_sources.py produit une file à traiter À LA MAIN, "
            "il n'effectue aucun envoi réseau."
        )

    db_path = Path(args.db) if args.db else None

    if not any([args.sources, args.importer, args.file, args.etape, args.verifie, args.temps, args.roi]):
        p.print_help()
        return

    if args.sources:
        afficher_sources()
    if args.importer:
        res = importer_csv(args.importer, db_path)
        print(
            f"{res['added']} ajoutés, {res['duplicates']} doublons, "
            f"{res['rejected']} refusés (source/provenance manquante ou invalide)"
        )
        for err in res["errors"][:10]:
            print(f"  - {err}")
    if args.verifie:
        stamped = marquer_verifie_db(args.verifie, db_path)
        print(f"{len(stamped)} fiche(s) reconfirmée(s) au {v.today().isoformat()} : {', '.join('#'+str(i) for i in stamped)}")
    if args.etape:
        out = marquer_etape(args.etape[0], args.etape[1], db_path)
        print(f"Prospect #{out['record_id']} -> étape '{out['etape']}' enregistrée.")
    if args.temps:
        out = enregistrer_temps_db(args.temps[0], int(args.temps[1]), args.note, db_path)
        print(f"{args.temps[1]} min enregistrées (entrée #{out['id']}).")
    if args.file:
        afficher_file(db_path, args.prenom, args.langue)
    if args.roi:
        afficher_roi(db_path)


if __name__ == "__main__":
    main()
