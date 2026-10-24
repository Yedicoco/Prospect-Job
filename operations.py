"""Parcours commercial et recrutement, partagé par les API web et outils de gestion.
Les transactions conservent les relations et n'envoient aucun message.
"""
import csv
import io
import json
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import validation as v
import yallah_b2c as b2c
import yallah_emploi as emploi
import yallah_messages as messages
import yallah_prospection as prospection
import yallah_sources as sources

connect = None
STAGES = ['prospect', 'qualifie', 'conversation', 'rendez_vous', 'besoin_confirme', 'proposition', 'gagne', 'perdu']
APPLICATION_STAGES = ['recu', 'contacte', 'entretien', 'propose', 'accepte', 'refuse', 'retire']

BASSINS_PROCHES = {
    'casablanca': {'bouskoura', 'mohammedia', 'nouaceur', 'dar bouazza'},
    'bouskoura': {'casablanca', 'nouaceur', 'dar bouazza'},
    'mohammedia': {'casablanca', 'benslimane'},
    'rabat': {'témara/harhoura', 'temara/harhoura', 'témara', 'temara', 'harhoura', 'salé', 'sale'},
    'témara/harhoura': {'rabat', 'salé', 'sale'},
    'temara/harhoura': {'rabat', 'salé', 'sale'},
    'témara': {'rabat', 'harhoura', 'salé', 'sale'},
    'temara': {'rabat', 'harhoura', 'salé', 'sale'},
    'salé': {'rabat', 'témara', 'temara'},
    'sale': {'rabat', 'témara', 'temara'},
    'agadir': {'inezgane', 'ait melloul'},
    'el jadida': {'azemmour', 'haouzia'},
    'tanger': {'tétouan', 'tetouan'},
    'fès': {'meknès', 'meknes'},
    'fes': {'meknes', 'meknès'},
}

MOTS_CLES_METIERS = [
    ('SRV', ('serveur', 'serveuse', 'service en salle', 'extra', 'banquet', 'réception', 'reception', 'traiteur')),
    ('PLG', ('plonge', 'plongeur', 'vaisselle')),
    ('CUI', ('cuisin', 'commis', 'chef', 'pâtiss', 'patiss', 'tayaba')),
    ('MEN', ('ménage', 'menage', 'femme de chambre', 'chambre', 'gouvernante', 'entretien')),
    ('NOU', ('nounou', 'garde d’enfant', "garde d'enfant", 'enfants', 'baby')),
    ('CHA', ('chauffeur', 'conducteur', 'permis')),
    ('AGE', ('personne âgée', 'personnes âgées', 'personne agee', 'auxiliaire', 'senior')),
    ('GAR', ('gardien', 'vigile', 'sécurité', 'securite', 'concierge')),
    ('PON', ('grand ménage', 'grand menage', 'ponctuel', 'déménagement', 'demenagement')),
    ('NET', ('fin de chantier', 'chantier', 'remise en état', 'remise en etat')),
    ('COM', ('vendeur', 'vendeuse', 'caisse', 'caissier', 'magasin', 'boutique', 'accueil')),
]
SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL, entity_id INTEGER, detail TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunities(id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES records(id), title TEXT NOT NULL, stage TEXT NOT NULL, owner TEXT NOT NULL, next_action TEXT NOT NULL, due TEXT NOT NULL, loss_reason TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, opportunity_id INTEGER REFERENCES opportunities(id), title TEXT NOT NULL, owner TEXT NOT NULL, due TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, tel TEXT NOT NULL, city TEXT NOT NULL, skills TEXT NOT NULL, languages TEXT NOT NULL, available_from TEXT NOT NULL, available_until TEXT NOT NULL, availability_verified TEXT NOT NULL, consent_proof TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'actif', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications(id INTEGER PRIMARY KEY, candidate_id INTEGER NOT NULL REFERENCES candidates(id), need_id INTEGER NOT NULL REFERENCES records(id), stage TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, UNIQUE(candidate_id,need_id));
CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES applications(id), start TEXT NOT NULL, end TEXT NOT NULL, status TEXT NOT NULL, agreement TEXT NOT NULL, feedback TEXT NOT NULL DEFAULT '', incident TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations(id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES records(id), channel TEXT NOT NULL, direction TEXT NOT NULL, body TEXT NOT NULL, outcome TEXT NOT NULL, provider_id TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY, opportunity_id INTEGER NOT NULL REFERENCES opportunities(id), version INTEGER NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(opportunity_id,version));
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, opportunity_id INTEGER REFERENCES opportunities(id), kind TEXT NOT NULL, amount_cents INTEGER NOT NULL, reference TEXT NOT NULL, day TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS authorization_history(id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL, channel TEXT NOT NULL, destination TEXT NOT NULL, proof TEXT NOT NULL, active INTEGER NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS verifications(id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES records(id), source_url TEXT NOT NULL, previous_date TEXT NOT NULL, actor TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provider_events(id INTEGER PRIMARY KEY, provider TEXT NOT NULL, event_id TEXT NOT NULL, event_type TEXT NOT NULL, delivery_id INTEGER, received TEXT NOT NULL, UNIQUE(provider,event_id));
CREATE TABLE IF NOT EXISTS intake(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'nouveau', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS time_logs(id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES records(id), minutes INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL, day TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS opportunities_stage ON opportunities(stage);
CREATE INDEX IF NOT EXISTS tasks_due ON tasks(status,due);
CREATE INDEX IF NOT EXISTS conversations_record ON conversations(record_id,created);
CREATE INDEX IF NOT EXISTS delivery_destination ON deliveries(destination,attempted_at);
CREATE INDEX IF NOT EXISTS assignment_application ON assignments(application_id,start,end);
CREATE INDEX IF NOT EXISTS time_logs_record ON time_logs(record_id);
'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def configure(factory):
    global connect
    connect = factory
    with connect() as con:
        con.executescript(SCHEMA)
        columns={r['name'] for r in con.execute('PRAGMA table_info(provider_events)')}
        for name in ('provider_message_id','state'):
            if name not in columns:
                con.execute(f"ALTER TABLE provider_events ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        con.execute('INSERT OR IGNORE INTO schema_migrations VALUES (1,?)', (now(),))
        con.execute('INSERT OR IGNORE INTO schema_migrations VALUES (2,?)', (now(),))
        con.execute('INSERT OR IGNORE INTO schema_migrations VALUES (3,?)', (now(),))


def audit(con, actor, action, entity, entity_id=None, detail=''):
    con.execute('INSERT INTO audit_log(actor,action,entity,entity_id,detail,created) VALUES (?,?,?,?,?,?)',
                (actor, action, entity, entity_id, detail[:2000], now()))


def require(con, table, rid):
    # table n'est jamais issu directement de la requête.
    row = con.execute(f'SELECT * FROM {table} WHERE id=?', (int(rid),)).fetchone()
    if not row:
        raise ValueError('Élément introuvable : ' + table)
    return dict(row)


def prospect(con, rid):
    row = require(con, 'records', rid)
    if row['kind'] not in ('b2b', 'b2c') or json.loads(row['payload']).get('exemple'):
        raise ValueError('Client potentiel réel requis')
    return row


def need(con, rid, open_only=True):
    row = require(con, 'records', rid)
    item = json.loads(row['payload'])
    if row['kind'] != 'emploi' or item.get('exemple') or (open_only and item.get('statut') != 'ouvert'):
        raise ValueError('Besoin réel ouvert requis')
    return item


def field(body, key, required=True, limit=1000):
    return v.text(body.get(key, ''), key, required, limit)


def suppress(con, rid, actor='system'):
    item = json.loads(require(con, 'records', rid)['payload'])
    for key in messages.cles_contact(item):
        con.execute('INSERT OR IGNORE INTO suppressions VALUES (?,?)', (key, now()))
    for permission in con.execute('SELECT * FROM permissions WHERE record_id=? AND active=1',(rid,)).fetchall():
        con.execute('INSERT INTO authorization_history(record_id,channel,destination,proof,active,actor,created) VALUES (?,?,?,?,0,?,?)',(rid,permission['channel'],permission['destination'],'Retrait : '+permission['proof'],actor,now()))
    con.execute('UPDATE permissions SET active=0 WHERE record_id=?', (rid,))
    for kind in ('b2b', 'b2c'):
        key = 'meta_' + kind
        row = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        meta = json.loads(row[0]) if row else {}
        meta.setdefault('refus', []).extend(item[k] for k in ('email', 'tel', 'whatsapp') if item.get(k))
        con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(meta)))
    # Les doublons sont également bloqués au départ via suppressions.
    con.execute("UPDATE deliveries SET status='blocked',reason='Refus du contact' WHERE record_id=? AND status='queued'", (rid,))
    audit(con, actor, 'refus', 'records', rid)


def detecter_metiers_dans_texte(texte: str) -> list:
    """Détecte de façon déterministe les codes métiers évoqués dans un message (suggestion humaine uniquement)."""
    bas = (texte or '').casefold()
    trouves = []
    for code, mots in MOTS_CLES_METIERS:
        if code in emploi.METIERS and any(m in bas for m in mots):
            trouves.append(code)
    return trouves


def quota_journalier(con, jour: date | None = None) -> dict:
    """Compteur unifié des prises de contact sortantes du jour (manuel + API) vs plafond MAX_PAR_JOUR (15)."""
    iso = (jour or v.today()).isoformat()
    conv_ids = {
        r['record_id']
        for r in con.execute(
            "SELECT record_id FROM conversations WHERE direction='sortant' AND substr(created,1,10)=?",
            (iso,),
        ).fetchall()
    }
    deliv_ids = {
        r['record_id']
        for r in con.execute(
            "SELECT record_id FROM deliveries WHERE substr(attempted_at,1,10)=? AND status IN ('accepted','delivered','read','unknown')",
            (iso,),
        ).fetchall()
    }
    used = len(conv_ids | deliv_ids)
    plafond = messages.MAX_PAR_JOUR
    return {
        'date': iso,
        'used': used,
        'max': plafond,
        'remaining': max(0, plafond - used),
    }


def enregistrer_envoi_manuel(con, rid: int, channel: str = '', note_text: str = '', actor: str = 'local') -> dict:
    """Enregistre un envoi manuel, déduit le vrai canal, crée l'opportunité et programme les relances J+3 / J+7 / J+14."""
    row = prospect(con, rid)
    item = json.loads(row['payload'])
    eff_channel = channel if channel in ('email', 'whatsapp', 'telephone') else (messages.canal_recommande(item) or 'interne')
    corps = (note_text or '').strip()[:2000] or f'Contact envoyé manuellement ({eff_channel})'
    con.execute(
        "INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,?,'sortant',?,'note',?)",
        (rid, eff_channel, corps, now()),
    )
    nb_sortants = con.execute(
        "SELECT COUNT(*) FROM conversations WHERE record_id=? AND direction='sortant'",
        (rid,),
    ).fetchone()[0]
    proprio = actor if actor and actor not in ('local', 'system') else 'Service Commercial'
    if nb_sortants <= len(sources.RELANCES):
        prochain_delai = sources.RELANCES[nb_sortants - 1]
        echeance_relance = (v.today() + timedelta(days=prochain_delai)).isoformat()
        libelle_relance = f'Relance J+{prochain_delai}'
        prochaine_action = f'Attendre retour ({eff_channel}) ou {libelle_relance.lower()}'
    else:
        prochain_delai = None
        echeance_relance = (v.today() + timedelta(days=7)).isoformat()
        libelle_relance = ''
        prochaine_action = 'Dernière relance J+14 envoyée — clôturer si sans retour'

    opp = con.execute(
        "SELECT * FROM opportunities WHERE record_id=? AND stage NOT IN ('gagne','perdu') ORDER BY id DESC LIMIT 1",
        (rid,),
    ).fetchone()
    if not opp:
        oid = con.execute(
            "INSERT INTO opportunities(record_id,title,stage,owner,next_action,due,loss_reason,created,updated) VALUES (?,?,'qualifie',?,?,?,'',?,?)",
            (
                rid,
                f"Prospection {row['kind'].upper()} — {item.get('nom', 'Prospect')}",
                proprio,
                prochaine_action,
                echeance_relance,
                now(),
                now(),
            ),
        ).lastrowid
    else:
        oid = opp['id']
        if opp['stage'] in ('prospect', 'qualifie'):
            con.execute(
                'UPDATE opportunities SET stage=?,next_action=?,due=?,updated=? WHERE id=?',
                ('qualifie', prochaine_action, echeance_relance, now(), oid),
            )
    # Toute relance antérieure ouverte passe en terminée, puis la prochaine échéance (J+3 / J+7 / J+14) est créée.
    con.execute(
        "UPDATE tasks SET status='terminee' WHERE opportunity_id=? AND status='a_faire' AND title LIKE 'Relance J+%'",
        (oid,),
    )
    if libelle_relance:
        con.execute(
            "INSERT INTO tasks(opportunity_id,title,owner,due,status,created) VALUES (?,?,?,?,'a_faire',?)",
            (oid, f"{libelle_relance} — {item.get('nom', 'Prospect')}", proprio, echeance_relance, now()),
        )
    return {'channel': eff_channel, 'opportunity_id': oid, 'outbound_count': nb_sortants, 'next_relance': libelle_relance}


def traiter_reponse_entrante(con, rid: int, channel: str, body_text: str, actor: str = 'system') -> dict:
    """Fait avancer automatiquement le dossier à la réception d'une réponse positive/neutre d'un prospect."""
    row = require(con, 'records', rid)
    item = json.loads(row['payload'])
    today_iso = v.today().isoformat()
    suggested = detecter_metiers_dans_texte(body_text)
    proprio = actor if actor and actor not in ('local', 'system') and not actor.startswith('webhook:') else 'Service Commercial'
    opp = con.execute(
        "SELECT * FROM opportunities WHERE record_id=? AND stage NOT IN ('gagne','perdu') ORDER BY id DESC LIMIT 1",
        (rid,),
    ).fetchone()
    indice_metiers = (' · métiers évoqués : ' + ', '.join(suggested)) if suggested else ''
    prochaine = f'Qualifier le besoin en 10 min ({channel}){indice_metiers}'[:1000]
    if opp:
        oid = opp['id']
        new_stage = 'conversation' if opp['stage'] in ('prospect', 'qualifie') else opp['stage']
        con.execute(
            'UPDATE opportunities SET stage=?,next_action=?,due=?,updated=? WHERE id=?',
            (new_stage, prochaine, today_iso, now(), oid),
        )
    else:
        oid = con.execute(
            "INSERT INTO opportunities(record_id,title,stage,owner,next_action,due,loss_reason,created,updated) VALUES (?,?,'conversation',?,?,?,'',?,?)",
            (rid, f"Réponse {channel} — {item.get('nom', 'Prospect')}", proprio, prochaine, today_iso, now(), now()),
        ).lastrowid
    # Une réponse reçue annule toute relance froide (J+3 / J+7 / J+14) en attente.
    con.execute(
        "UPDATE tasks SET status='annulee' WHERE opportunity_id=? AND status='a_faire' AND title LIKE 'Relance J+%'",
        (oid,),
    )
    open_qualif = con.execute(
        "SELECT 1 FROM tasks WHERE opportunity_id=? AND status='a_faire' AND title LIKE 'Réponse reçue%'",
        (oid,),
    ).fetchone()
    if not open_qualif:
        con.execute(
            "INSERT INTO tasks(opportunity_id,title,owner,due,status,created) VALUES (?,?,?,?,'a_faire',?)",
            (oid, f"Réponse reçue ({channel}) — qualifier le besoin — {item.get('nom', 'Prospect')}", proprio, today_iso, now()),
        )
    return {'opportunity_id': oid, 'suggested_metiers': suggested}


def traiter_rebond_email(con, bounced_email: str, full_text: str, msg_id: str = '', actor: str = 'system') -> list:
    """Invalide un email revenu en erreur (bounce) et bascule automatiquement la fiche sur son canal de repli."""
    cible = messages.email_normalise(bounced_email)
    if not cible:
        return []
    today_iso = v.today().isoformat()
    touched = []
    for row in con.execute("SELECT id,payload FROM records WHERE kind IN ('b2b','b2c')").fetchall():
        item = json.loads(row['payload'])
        if item.get('exemple') or messages.email_normalise(item.get('email', '')) != cible:
            continue
        rid = row['id']
        item['email_invalide'] = item.get('email', '')
        item['email'] = ''
        con.execute('UPDATE records SET payload=? WHERE id=?', (json.dumps(item, ensure_ascii=False), rid))
        con.execute(
            "INSERT INTO conversations(record_id,channel,direction,body,outcome,provider_id,created) VALUES (?,'email','entrant',?,'rebond',?,?)",
            (rid, full_text[:4000], msg_id, now()),
        )
        repli = messages.canal_recommande(item)
        con.execute(
            'INSERT INTO events(record_id,action,created) VALUES (?,?,?)',
            (rid, f"Email en rebond ({cible}) — bascule vers {repli or 'vérification manuelle'}", now()),
        )
        opp = con.execute(
            "SELECT id,owner FROM opportunities WHERE record_id=? AND stage NOT IN ('gagne','perdu') ORDER BY id DESC LIMIT 1",
            (rid,),
        ).fetchone()
        if opp and repli == 'whatsapp':
            con.execute(
                'UPDATE opportunities SET next_action=?,due=?,updated=? WHERE id=?',
                ('Email en rebond — contacter via repli WhatsApp mobile', today_iso, now(), opp['id']),
            )
            con.execute(
                "INSERT INTO tasks(opportunity_id,title,owner,due,status,created) VALUES (?,?,?,?,'a_faire',?)",
                (opp['id'], f"Rebond email — repli WhatsApp mobile — {item.get('nom', 'Prospect')}", opp['owner'], today_iso, now()),
            )
        audit(con, actor, 'rebond_email', 'records', rid, detail=f'{cible} -> {repli}')
        touched.append({'record_id': rid, 'fallback_channel': repli})
    return touched


def anonymiser_nom(nom: str) -> str:
    """Anonymise l'identité d'un candidat selon la Loi 09-08 (Prénom + initiale uniquement)."""
    morceaux = [m for m in re.split(r'\s+', (nom or '').strip()) if m]
    if not morceaux:
        return 'Profil candidat'
    if len(morceaux) == 1:
        return morceaux[0]
    return f"{morceaux[0]} {morceaux[-1][0].upper()}."


def _construire_fiche_presentation(candidate_row: dict, need_item: dict, clean_missions: int = 0, langue: str = 'fr') -> str:
    """Génère une fiche de présentation candidat anonymisée, factuelle et conforme à l'art. 480 du Code du travail."""
    identite = anonymiser_nom(candidate_row['name'])
    skills = candidate_row['skills'] if isinstance(candidate_row['skills'], list) else json.loads(candidate_row['skills'])
    metiers_txt = ', '.join(emploi.METIERS.get(s, s) for s in skills)
    langues_txt = (candidate_row.get('languages') or '').strip() or 'non précisées'
    dispo_txt = f"{candidate_row['available_from']} → {candidate_row['available_until']} (confirmée le {candidate_row['availability_verified']})"
    poste_txt = emploi.METIERS.get(need_item.get('metier', ''), need_item.get('metier', ''))
    site = messages.site_web_officiel()
    hist_fr = f"\n- Suivi interne : {clean_missions} mission(s) terminée(s) sans incident déclaré" if clean_missions > 0 else ""

    if langue == 'darija':
        return (
            f"Fiche profil (m7tarma l-khoussoussiya) — {need_item.get('ref', '')}\n"
            f"- Profil : {identite} ({candidate_row['city']})\n"
            f"- Poste : {poste_txt} ({need_item.get('format', '')})\n"
            f"- Métiers déclarés : {metiers_txt}\n"
            f"- Langues déclarées : {langues_txt}\n"
            f"- Disponibilité déclarée : {dispo_txt}\n"
            f"Note : M3loumat m2khoda mn tassri7 l-kandidat ; ma kayn 7ta khols 3la l-kandidat (Code du travail, art. 480).\n"
            f"{site}"
        )
    if langue == 'arabe':
        return (
            f"بطاقة تقديم مرشح (محمية الهوية) — {need_item.get('ref', '')}\n"
            f"- المرشح: {identite} ({candidate_row['city']})\n"
            f"- المنصب المطلوب: {poste_txt} ({need_item.get('format', '')})\n"
            f"- المهن المصرح بها: {metiers_txt}\n"
            f"- اللغات المصرح بها: {langues_txt}\n"
            f"- التوفر المصرح به: {dispo_txt}\n"
            f"ملاحظة: معطيات مصرح بها من طرف المرشح؛ لا تُطلب أي مصاريف من المرشح (مدونة الشغل، المادة 480).\n"
            f"{site}"
        )
    return (
        f"Présentation de profil anonymisée — Besoin {need_item.get('ref', '')}\n"
        f"- Profil : {identite} (ville déclarée : {candidate_row['city']})\n"
        f"- Besoin visé : {poste_txt} · {need_item.get('format', '')} ({need_item.get('ville', '')})\n"
        f"- Métiers déclarés : {metiers_txt}\n"
        f"- Langues déclarées : {langues_txt}\n"
        f"- Disponibilité déclarée : {dispo_txt}{hist_fr}\n"
        f"Cadre Yallah Services : données déclaratives communiquées sans coordonnées personnelles avant accord d'entretien (Loi 09-08). "
        f"Aucun frais n'est demandé au candidat, à aucune étape de la mise en relation (Code du travail, art. 480).\n"
        f"{site}"
    )


def fiche_presentation_candidat(candidate_id: int, need_id: int, langue: str = 'fr') -> dict:
    """API publique de génération d'une fiche candidat anonymisée pour un besoin ouvert."""
    if langue not in ('fr', 'darija', 'arabe'):
        raise ValueError('Langue invalide')
    with connect() as con:
        cand = require(con, 'candidates', candidate_id)
        need_item = need(con, need_id, open_only=False)
        clean_missions = con.execute(
            "SELECT COUNT(*) FROM assignments m JOIN applications a ON a.id=m.application_id WHERE a.candidate_id=? AND m.status='terminee' AND m.incident=''",
            (cand['id'],),
        ).fetchone()[0]
    texte = _construire_fiche_presentation(cand, need_item, clean_missions, langue)
    return {
        'candidate_id': cand['id'],
        'need_id': int(need_id),
        'anonymized_name': anonymiser_nom(cand['name']),
        'presentation': texte,
    }


def execute(action, body, actor='local'):
    if not isinstance(body, dict):
        raise ValueError('Objet JSON attendu')
    result = {}
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if action == 'opportunity':
            rid = int(body['record_id']); prospect(con, rid)
            title, owner = field(body, 'title'), field(body, 'owner', limit=100)
            next_action = field(body, 'next_action')
            due = v.day(body.get('due', ''), 'Prochaine action')
            stage = body.get('stage', 'prospect')
            if stage not in STAGES:
                raise ValueError('Étape commerciale invalide')
            loss = field(body, 'loss_reason', stage == 'perdu')
            oid = body.get('id')
            if oid:
                old = require(con, 'opportunities', oid)
                if old['record_id'] != rid:
                    raise ValueError('Impossible de changer le client d’une opportunité')
                con.execute('UPDATE opportunities SET title=?,stage=?,owner=?,next_action=?,due=?,loss_reason=?,updated=? WHERE id=?',
                            (title, stage, owner, next_action, due, loss, now(), oid))
            else:
                oid = con.execute('INSERT INTO opportunities(record_id,title,stage,owner,next_action,due,loss_reason,created,updated) VALUES (?,?,?,?,?,?,?,?,?)',
                                  (rid, title, stage, owner, next_action, due, loss, now(), now())).lastrowid
            result = {'id': oid}
        elif action == 'task':
            oid = body.get('opportunity_id') or None
            if oid:
                require(con, 'opportunities', oid)
            status = body.get('status', 'a_faire')
            if status not in ('a_faire', 'terminee', 'annulee'):
                raise ValueError('Statut de tâche invalide')
            values = (oid, field(body, 'title'), field(body, 'owner', limit=100), v.day(body.get('due', ''), 'Échéance'), status)
            if body.get('id'):
                require(con, 'tasks', body['id'])
                con.execute('UPDATE tasks SET opportunity_id=?,title=?,owner=?,due=?,status=? WHERE id=?', (*values, body['id']))
                result = {'id': body['id']}
            else:
                result = {'id': con.execute('INSERT INTO tasks(opportunity_id,title,owner,due,status,created) VALUES (?,?,?,?,?,?)', (*values, now())).lastrowid}
        elif action == 'need_from_opportunity':
            opp = require(con, 'opportunities', body['opportunity_id'])
            if opp['stage'] not in ('besoin_confirme', 'proposition', 'gagne') or body.get('confirm') is not True:
                raise ValueError('Besoin confirmé et validation explicite requis')
            item = body.get('data')
            v.record('emploi', item)
            if item.get('exemple'):
                raise ValueError('Une démonstration ne peut pas devenir un besoin client')
            if con.execute("SELECT 1 FROM records WHERE kind='emploi' AND json_extract(payload,'$.ref')=?", (item['ref'],)).fetchone():
                raise ValueError('Référence de besoin déjà utilisée')
            item.update(client_id=opp['record_id'], opportunity_id=opp['id'])
            nid = con.execute("INSERT INTO records(kind,payload) VALUES ('emploi',?)", (json.dumps(item),)).lastrowid
            result = {'id': nid}
        elif action == 'qualify_need':
            if body.get('confirm') is not True:
                raise ValueError('Confirmation explicite du besoin employeur requise')
            today_iso = v.today().isoformat()
            proprio = field(body, 'owner', False, 100) or (actor if actor not in ('local', 'system') else 'Service Commercial')
            if body.get('opportunity_id'):
                opp = require(con, 'opportunities', body['opportunity_id'])
                rid = opp['record_id']
                row = prospect(con, rid)
            else:
                rid = int(body['record_id'])
                row = prospect(con, rid)
                opp = con.execute(
                    "SELECT * FROM opportunities WHERE record_id=? AND stage NOT IN ('gagne','perdu') ORDER BY id DESC LIMIT 1",
                    (rid,),
                ).fetchone()
            client_data = json.loads(row['payload'])
            metier = field(body, 'metier', True, 20).upper()
            if metier not in emploi.METIERS:
                raise ValueError('Métier inconnu')
            fmt = field(body, 'format', True, 40)
            if fmt not in emploi.FORMATS:
                raise ValueError('Format de besoin invalide')
            ville = field(body, 'ville', False, 100) or client_data.get('ville', '')
            zone = field(body, 'zone', False, 100) or client_data.get('zone', '') or 'Centre'
            source_conf = field(body, 'source_confirmation', True, 500)
            date_conf = v.day(body.get('date_confirmation') or today_iso, 'Date de confirmation')
            postes = int(v.number(body.get('postes', 1), 'Nombre de postes'))
            if not 1 <= postes <= 200:
                raise ValueError('Nombre de postes invalide (1 à 200)')
            ref = field(body, 'ref', False, 80).upper()
            if not ref:
                seq = con.execute("SELECT COUNT(*)+1 FROM records WHERE kind='emploi'").fetchone()[0]
                ref = f"EMP-{today_iso.replace('-', '')}-{seq:03d}"
                while con.execute("SELECT 1 FROM records WHERE kind='emploi' AND json_extract(payload,'$.ref')=?", (ref,)).fetchone():
                    seq += 1
                    ref = f"EMP-{today_iso.replace('-', '')}-{seq:03d}"
            elif con.execute("SELECT 1 FROM records WHERE kind='emploi' AND json_extract(payload,'$.ref')=?", (ref,)).fetchone():
                raise ValueError('Référence de besoin déjà utilisée')
            rem_val = field(body, 'remuneration', False, 200)
            rem_src = field(body, 'remuneration_source', bool(rem_val), 300)
            hor_val = field(body, 'horaires', False, 200)
            hor_src = field(body, 'horaires_source', bool(hor_val), 300)
            langues_req = field(body, 'langues', False, 200)
            opp_title = field(body, 'title', False, 200) or f"Besoin confirmé {emploi.METIERS[metier]} ({postes}) — {client_data.get('nom', '')}"[:200]
            if opp:
                oid = opp['id']
                new_stage = opp['stage'] if opp['stage'] in ('proposition', 'gagne') else 'besoin_confirme'
                con.execute(
                    'UPDATE opportunities SET title=?,stage=?,owner=?,next_action=?,due=?,updated=? WHERE id=?',
                    (opp_title, new_stage, proprio, f'Présenter des candidats ({ref})', today_iso, now(), oid),
                )
            else:
                oid = con.execute(
                    "INSERT INTO opportunities(record_id,title,stage,owner,next_action,due,loss_reason,created,updated) VALUES (?,?,'besoin_confirme',?,?,?,'',?,?)",
                    (rid, opp_title, proprio, f'Présenter des candidats ({ref})', today_iso, now(), now()),
                ).lastrowid
            need_item = {
                'ref': ref,
                'metier': metier,
                'ville': ville,
                'zone': zone,
                'format': fmt,
                'statut': 'ouvert',
                'postes': str(postes),
                'langues': langues_req,
                'source_confirmation': source_conf,
                'date_confirmation': date_conf,
                'remuneration': {'valeur': rem_val, 'source': rem_src},
                'horaires': {'valeur': hor_val, 'source': hor_src},
            }
            v.record('emploi', need_item)
            need_item.update(client_id=rid, opportunity_id=oid)
            nid = con.execute("INSERT INTO records(kind,payload) VALUES ('emploi',?)", (json.dumps(need_item, ensure_ascii=False),)).lastrowid
            con.execute(
                "UPDATE tasks SET status='terminee' WHERE opportunity_id=? AND status='a_faire' AND (title LIKE 'Réponse reçue%' OR title LIKE 'Relance J+%')",
                (oid,),
            )
            result = {'id': nid, 'opportunity_id': oid, 'ref': ref, 'matches': _matches_in_con(con, nid)}
        elif action == 'candidate':
            email, tel = v.contact(body.get('email', ''), body.get('tel', ''))
            skills = body.get('skills', [])
            if not isinstance(skills, list) or not skills or any(s not in emploi.METIERS for s in skills):
                raise ValueError('Sélectionnez au moins un métier reconnu')
            start = v.day(body.get('available_from', ''), 'Disponible du')
            end = v.day(body.get('available_until', ''), 'Disponible au')
            verified = v.day(body.get('availability_verified', ''), 'Vérification de disponibilité', past=True)
            if start > end:
                raise ValueError('Plage de disponibilité inversée')
            proof = field(body, 'consent_proof')
            cid = body.get('id')
            for row in con.execute("SELECT * FROM candidates WHERE status='actif'"):
                if row['id'] != cid and ((email and row['email'] == email) or (tel and messages.tel_normalise(row['tel']) == messages.tel_normalise(tel))):
                    raise ValueError('Candidat déjà enregistré à cette coordonnée')
            values = (field(body, 'name', limit=150), email, tel, field(body, 'city', limit=100), json.dumps(skills), field(body, 'languages', False, 200), start, end, verified, proof)
            if cid:
                existing = require(con, 'candidates', cid)
                if existing['status'] != 'actif':
                    raise ValueError('Dossier archivé : modification interdite')
                con.execute('UPDATE candidates SET name=?,email=?,tel=?,city=?,skills=?,languages=?,available_from=?,available_until=?,availability_verified=?,consent_proof=? WHERE id=?', (*values, cid))
            else:
                cid = con.execute('INSERT INTO candidates(name,email,tel,city,skills,languages,available_from,available_until,availability_verified,consent_proof,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (*values, now())).lastrowid
            result = {'id': cid}
        elif action == 'application':
            candidate = require(con, 'candidates', body['candidate_id'])
            need_item=need(con, body['need_id'],open_only=not bool(body.get('id')))
            if candidate['status'] != 'actif':
                raise ValueError('Candidat archivé')
            stage = body.get('stage', 'recu')
            if stage not in APPLICATION_STAGES:
                raise ValueError('Étape candidature invalide')
            if need_item.get('statut')!='ouvert' and stage not in ('refuse','retire'):
                raise ValueError('Besoin fermé : clôturez la candidature')
            note = field(body, 'note', False)
            if body.get('id'):
                old = require(con, 'applications', body['id'])
                if old['candidate_id'] != candidate['id'] or old['need_id'] != int(body['need_id']):
                    raise ValueError('Liens de candidature immuables')
                con.execute('UPDATE applications SET stage=?,note=? WHERE id=?', (stage, note, old['id']))
                result = {'id': old['id']}
            else:
                if con.execute('SELECT 1 FROM applications WHERE candidate_id=? AND need_id=?', (candidate['id'], body['need_id'])).fetchone():
                    raise ValueError('Candidature déjà enregistrée')
                result = {'id': con.execute('INSERT INTO applications(candidate_id,need_id,stage,note,created) VALUES (?,?,?,?,?)', (candidate['id'], body['need_id'], stage, note, now())).lastrowid}
        elif action == 'assignment':
            app = require(con, 'applications', body['application_id'])
            need(con, app['need_id'])
            candidate = require(con, 'candidates', app['candidate_id'])
            if candidate['status'] != 'actif' or app['stage'] != 'accepte':
                raise ValueError('Candidat actif et candidature acceptée requis')
            start, end = v.day(body.get('start', ''), 'Début'), v.day(body.get('end', ''), 'Fin')
            if start > end or start < candidate['available_from'] or end > candidate['available_until']:
                raise ValueError('Dates incompatibles avec la disponibilité du candidat')
            if candidate['availability_verified'] != v.today().isoformat():
                raise ValueError('Reconfirmez la disponibilité du candidat aujourd’hui')
            if con.execute("SELECT 1 FROM assignments m JOIN applications a ON a.id=m.application_id WHERE a.candidate_id=? AND m.status IN ('planifiee','en_cours') AND m.start<=? AND m.end>=?", (candidate['id'], end, start)).fetchone():
                raise ValueError('Double affectation : une mission chevauche ces dates')
            result = {'id': con.execute("INSERT INTO assignments(application_id,start,end,status,agreement,created) VALUES (?,?,?,'planifiee',?,?)", (app['id'], start, end, field(body, 'agreement'), now())).lastrowid}
        elif action == 'assignment_update':
            old = require(con, 'assignments', body['id'])
            status = body.get('status')
            transitions = {'planifiee': ['en_cours', 'annulee'], 'en_cours': ['terminee', 'annulee'], 'terminee': [], 'annulee': []}
            if status != old['status'] and status not in transitions[old['status']]:
                raise ValueError('Transition de mission interdite')
            con.execute('UPDATE assignments SET status=?,feedback=?,incident=? WHERE id=?', (status, field(body, 'feedback', False), field(body, 'incident', False), old['id']))
            result = {'id': old['id']}
        elif action == 'conversation':
            rid = int(body['record_id']); prospect(con, rid)
            channel = body.get('channel')
            direction = body.get('direction')
            outcome = body.get('outcome', 'note')
            if channel not in ('email', 'whatsapp', 'telephone', 'interne') or direction not in ('entrant', 'sortant', 'note') or outcome not in ('note', 'reponse', 'refus', 'besoin', 'rebond'):
                raise ValueError('Type de conversation invalide')
            corps = field(body, 'body')
            if outcome == 'refus':
                suppress(con, rid, actor)
            cid = con.execute('INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,?,?,?,?,?)', (rid, channel, direction, corps, outcome, now())).lastrowid
            con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)', (rid, f'Conversation {direction} · {channel} · {outcome}', now()))
            extra = {}
            if direction == 'entrant' and outcome in ('reponse', 'besoin'):
                extra = traiter_reponse_entrante(con, rid, channel, corps, actor)
            result = {'id': cid, **extra}
        elif action == 'proposal':
            opp = require(con, 'opportunities', body['opportunity_id'])
            version = con.execute('SELECT COALESCE(MAX(version),0)+1 FROM proposals WHERE opportunity_id=?', (opp['id'],)).fetchone()[0]
            amount = round(v.number(body.get('amount'), 'Montant MAD') * 100)
            status = body.get('status', 'brouillon')
            if status not in ('brouillon', 'validee', 'acceptee', 'refusee'):
                raise ValueError('Statut de proposition invalide')
            result = {'id': con.execute('INSERT INTO proposals(opportunity_id,version,description,amount_cents,source,status,created) VALUES (?,?,?,?,?,?,?)', (opp['id'], version, field(body, 'description'), amount, field(body, 'source'), status, now())).lastrowid}
        elif action == 'ledger':
            oid = body.get('opportunity_id') or None
            if oid:
                require(con, 'opportunities', oid)
            kind = body.get('kind')
            if kind not in ('cout', 'facture', 'encaissement'):
                raise ValueError('Type d’écriture invalide')
            result = {'id': con.execute('INSERT INTO ledger(opportunity_id,kind,amount_cents,reference,day,created) VALUES (?,?,?,?,?,?)', (oid, kind, round(v.number(body.get('amount'), 'Montant MAD') * 100), field(body, 'reference'), v.day(body.get('day', ''), 'Date', past=True), now())).lastrowid}
        elif action == 'time_log':
            rid = int(body['record_id'])
            prospect(con, rid)
            mins = int(v.number(body.get('minutes'), 'Minutes', minimum=1, maximum=600))
            day_iso = v.day(body.get('day') or v.today().isoformat(), 'Date', past=True)
            note_txt = field(body, 'note', False, 500)
            tid = con.execute(
                'INSERT INTO time_logs(record_id,minutes,note,actor,day,created) VALUES (?,?,?,?,?,?)',
                (rid, mins, note_txt, actor, day_iso, now()),
            ).lastrowid
            con.execute(
                'INSERT INTO events(record_id,action,created) VALUES (?,?,?)',
                (rid, f'Temps passé enregistré : {mins} min', now()),
            )
            result = {'id': tid, 'record_id': rid, 'minutes': mins}
        elif action == 'intake_opportunity':
            incoming=require(con,'intake',body['intake_id'])
            if incoming['kind']!='demande' or incoming['status']!='nouveau':
                raise ValueError('Demande client nouvelle requise')
            d=json.loads(incoming['payload'])
            decoded = b2c.decoder_reference_b2c(d.get('b2c_ref', '') or d.get('message', '') or incoming.get('source', ''))
            d['name']=v.text(body.get('name') or d.get('name',''),'Nom client',True,150)
            d['city']=v.text(body.get('city') or d.get('city') or (decoded['ville'] if decoded else ''),'Ville client',True,100)
            zone_client = v.text(body.get('zone') or d.get('zone') or (decoded['zone'] if decoded else 'À préciser'), 'Zone client', True, 100)
            due=v.day(body.get('due',''),'Échéance')
            owner,next_action=field(body,'owner'),field(body,'next_action')
            # Provenance interne réelle, sans inventer de page publique. Le moteur de
            # campagne maintient son blocage source/autorisation tant qu'il n'est pas qualifié.
            kind=body.get('kind') or ('b2c' if decoded else '')
            if kind not in ('b2b','b2c'): raise ValueError('Choisissez entreprise ou particulier')
            inc_src = (incoming.get('source') or '').lower()
            orig = str(d.get('origin') or '').lower()
            if 'whatsapp' in inc_src or 'whatsapp' in orig:
                src_key = 'whatsapp_entrant'
            elif 'gbp' in inc_src or 'google' in inc_src:
                src_key = 'gbp_entrant'
            else:
                src_key = 'site_formulaire'
            item={'nom':d['name'],'ville':d['city'],'zone':zone_client,'tel':d['tel'],'email':d['email'],
                  'niveau':'B','source':src_key,'source_url':'','date_consultation':v.today().isoformat(),
                  'source_type':'entrant','source_reference':f'ENT-{incoming["id"]:06d}',
                  'contexte':d['message']}
            if decoded:
                item['b2c_ref'] = decoded['ref']
            if kind=='b2b': item.update(segment=body.get('segment'),phase=1)
            else: item['besoin']=body.get('besoin') or d.get('besoin') or (decoded['code_besoin'] if decoded else '')
            v.record(kind,item)
            existing=None
            keys=set(messages.cles_contact(item))
            for row in con.execute("SELECT * FROM records WHERE kind IN ('b2b','b2c')"):
                if keys.intersection(messages.cles_contact(json.loads(row['payload']))):
                    existing=row['id'];break
            rid=existing or con.execute("INSERT INTO records(kind,payload) VALUES (?,?)",(kind,json.dumps(item))).lastrowid
            oid=con.execute("INSERT INTO opportunities(record_id,title,stage,owner,next_action,due,created,updated) VALUES (?,?,'conversation',?,?,?,?,?)",(rid,'Demande '+incoming['kind']+' '+item['source_reference'],owner,next_action,due,now(),now())).lastrowid
            con.execute("UPDATE intake SET status='traite' WHERE id=?",(incoming['id'],))
            result={'id':oid,'record_id':rid}
        elif action == 'intake_classify':
            row=require(con,'intake',body['id'])
            if row['kind']!='a_qualifier' or row['status']!='nouveau': raise ValueError('Message à qualifier requis')
            kind=body.get('kind')
            if kind not in ('demande','candidature'): raise ValueError('Orientation invalide')
            payload=json.loads(row['payload'])
            if kind=='candidature':
                need(con,body.get('need_id'))
                payload['need_id']=int(body['need_id'])
            con.execute('UPDATE intake SET kind=?,payload=? WHERE id=?',(kind,json.dumps(payload),row['id']))
            result={'id':row['id']}
        elif action == 'intake_status':
            require(con, 'intake', body['id'])
            if body.get('status') not in ('nouveau', 'traite', 'rejete'):
                raise ValueError('Statut entrant invalide')
            con.execute('UPDATE intake SET status=? WHERE id=?', (body['status'], body['id']))
            result = {'id': body['id']}
        elif action == 'email_ingest':
            sender_email, _ = v.contact(body.get('sender_email', ''), '')
            sender_name = field(body, 'sender_name', False, 150) or sender_email
            subject = field(body, 'subject', True, 300)
            raw_body = field(body, 'body', True, 4000)
            msg_id = field(body, 'message_id', False, 300)
            if msg_id:
                inserted = con.execute("INSERT OR IGNORE INTO provider_events(provider,event_id,event_type,received) VALUES ('email_ingest',?,'incoming',?)", (msg_id, now())).rowcount
                if not inserted:
                    return {'deduplicated': True, 'classification': 'deja_traite'}
            unquoted = '\n'.join(line for line in raw_body.splitlines() if not line.lstrip().startswith('>')).strip()
            probe_exact = {s.strip().casefold().strip('.!؟?') for s in (subject, unquoted) if s.strip()}
            probe_text = (subject + '\n' + unquoted).casefold()
            full_text = f'Objet : {subject}\n\n{raw_body}'[:4000]
            # Détection automatique des rebonds (mailer-daemon / postmaster / DSN) et bascule vers WhatsApp mobile.
            bounce_senders = ('mailer-daemon@', 'postmaster@')
            bounce_subjects = ('undelivered mail', 'undeliverable', 'delivery status notification', 'mail delivery failed', 'failure notice', 'adresse introuvable', 'non remis')
            bounced_param = field(body, 'bounced_email', False, 254).lower()
            is_bounce = bool(bounced_param) or sender_email.startswith(bounce_senders) or any(bs in subject.casefold() for bs in bounce_subjects)
            if is_bounce:
                candidates_mail = [bounced_param] if bounced_param else re.findall(r'[^\s<>,"\'()]+@[^\s<>,"\'()]+\.[^\s<>,"\'()]+', raw_body)
                touched = []
                for addr in dict.fromkeys(candidates_mail):
                    if messages.email_normalise(addr) != sender_email:
                        touched.extend(traiter_rebond_email(con, addr, full_text, msg_id, actor))
                if touched:
                    result = {'id': touched[0]['record_id'], 'classification': 'rebond_email', 'bounced': touched}
                    audit(con, actor, action, 'operations', result.get('id'))
                    return result
            stop_words = {'stop', 'unsubscribe', 'arrêt', 'arret', 'désinscription', 'desinscription', 'إلغاء الاشتراك'}
            stop_phrases = ('ne plus me contacter', 'ne plus nous contacter', 'veuillez me désinscrire', 'veuillez me desinscrire', 'retirez-moi de votre liste', 'supprimez mon adresse')
            refusal = bool(probe_exact & stop_words) or any(p in probe_text for p in stop_phrases)
            matched_ids = []
            reply_meta = {}
            for row in con.execute("SELECT * FROM records WHERE kind IN ('b2b','b2c')").fetchall():
                item = json.loads(row['payload'])
                if item.get('exemple') or messages.email_normalise(item.get('email', '')) != sender_email:
                    continue
                matched_ids.append(row['id'])
                if refusal:
                    suppress(con, row['id'], actor)
                con.execute("INSERT INTO conversations(record_id,channel,direction,body,outcome,provider_id,created) VALUES (?,'email','entrant',?,?,?,?)",
                            (row['id'], full_text, 'refus' if refusal else 'reponse', msg_id, now()))
                con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)',
                            (row['id'], 'Email entrant · ' + ('refus' if refusal else 'réponse'), now()))
                if not refusal:
                    reply_meta = traiter_reponse_entrante(con, row['id'], 'email', unquoted or raw_body, actor)
            if matched_ids:
                result = {'id': matched_ids[0], 'classification': 'refus' if refusal else 'reponse_prospect', 'record_ids': matched_ids, **reply_meta}
            elif refusal:
                con.execute('INSERT OR IGNORE INTO suppressions VALUES (?,?)', ('mail:' + sender_email, now()))
                result = {'id': None, 'classification': 'refus_inconnu'}
            else:
                open_matches = []
                haystack = (subject + ' ' + unquoted).upper()
                for row in con.execute("SELECT id,payload FROM records WHERE kind='emploi'").fetchall():
                    job = json.loads(row['payload'])
                    ref = str(job.get('ref', '')).strip().upper()
                    if not ref or job.get('exemple') or job.get('statut') != 'ouvert':
                        continue
                    if not any(r['publiable'] == 'oui' for r in emploi.construire_lignes([job], 'fr', False)):
                        continue
                    if re.search(r'(?<![A-Z0-9-])' + re.escape(ref) + r'(?![A-Z0-9-])', haystack):
                        open_matches.append(row['id'])
                decoded_b2c = b2c.decoder_reference_b2c(subject + ' ' + unquoted)
                payload = {'name': sender_name, 'email': sender_email, 'tel': '', 'city': decoded_b2c['ville'] if decoded_b2c else '',
                           'message': full_text, 'acknowledge': False, 'notice_version': '', 'origin': 'email_entrant'}
                if decoded_b2c:
                    payload.update(zone=decoded_b2c['zone'], besoin=decoded_b2c['code_besoin'], b2c_ref=decoded_b2c['ref'])
                if len(open_matches) == 1:
                    payload['need_id'] = open_matches[0]
                    iid = con.execute("INSERT INTO intake(kind,payload,source,created) VALUES ('candidature',?,'email_entrant',?)", (json.dumps(payload), now())).lastrowid
                    result = {'id': iid, 'classification': 'candidature', 'need_id': open_matches[0]}
                elif decoded_b2c:
                    iid = con.execute("INSERT INTO intake(kind,payload,source,created) VALUES ('demande',?,'email_entrant',?)", (json.dumps(payload), now())).lastrowid
                    result = {'id': iid, 'classification': 'demande_b2c', 'b2c_ref': decoded_b2c['ref']}
                else:
                    iid = con.execute("INSERT INTO intake(kind,payload,source,created) VALUES ('a_qualifier',?,'email_entrant',?)", (json.dumps(payload), now())).lastrowid
                    result = {'id': iid, 'classification': 'a_qualifier'}
        else:
            raise ValueError('Action métier inconnue')
        audit(con, actor, action, 'operations', result.get('id'))
    return result


def calculer_entonnoir(con) -> dict:
    """Calcule l'entonnoir de conversion par canal, par segment et par référence B2C entrante."""
    recs = {}
    for r in con.execute("SELECT id,kind,payload FROM records WHERE kind IN ('b2b','b2c')").fetchall():
        data = json.loads(r['payload'])
        if data.get('exemple'):
            continue
        recs[r['id']] = {'kind': r['kind'], 'data': data}

    convs_by_rec = {}
    for c in con.execute('SELECT record_id,channel,direction,outcome,created FROM conversations ORDER BY id').fetchall():
        convs_by_rec.setdefault(c['record_id'], []).append(dict(c))

    delivs_by_rec = {}
    for d in con.execute("SELECT d.record_id,c.channel,d.status,d.attempted_at FROM deliveries d JOIN campaigns c ON c.id=d.campaign_id WHERE d.status IN ('accepted','delivered','read','unknown')").fetchall():
        delivs_by_rec.setdefault(d['record_id'], []).append(dict(d))

    opps_by_rec = {}
    for o in con.execute('SELECT id,record_id,stage,created,updated FROM opportunities').fetchall():
        opps_by_rec.setdefault(o['record_id'], []).append(dict(o))

    ledger_by_opp = {}
    for l in con.execute('SELECT opportunity_id,kind,amount_cents FROM ledger WHERE opportunity_id IS NOT NULL').fetchall():
        entry = ledger_by_opp.setdefault(l['opportunity_id'], {'encaissement': 0, 'cout': 0})
        if l['kind'] in entry:
            entry[l['kind']] += l['amount_cents']

    by_channel = {
        ch: {'contacted': 0, 'replied': 0, 'refused': 0, 'bounced': 0, 'confirmed': 0, 'won': 0, 'reply_rate': 0.0}
        for ch in ('email', 'whatsapp', 'telephone')
    }
    by_segment = {}

    for rid, info in recs.items():
        seg = info['data'].get('segment', 'b2c') if info['kind'] == 'b2b' else 'b2c'
        seg_bucket = by_segment.setdefault(seg, {
            'total_records': 0, 'contacted': 0, 'replied': 0, 'confirmed': 0, 'won': 0, 'cash_mad': 0.0,
        })
        seg_bucket['total_records'] += 1

        convs = convs_by_rec.get(rid, [])
        delivs = delivs_by_rec.get(rid, [])
        opps = opps_by_rec.get(rid, [])

        # Canal primaire d'approche = premier canal sortant enregistré (sinon canal recommandé si contacté).
        primary_ch = ''
        for c in convs:
            if c['direction'] == 'sortant' and c['channel'] in by_channel:
                primary_ch = c['channel']
                break
        if not primary_ch and delivs:
            ch0 = delivs[0]['channel']
            if ch0 in by_channel:
                primary_ch = ch0
        if not primary_ch and any(c['direction'] == 'sortant' for c in convs):
            rec_ch = messages.canal_recommande(info['data'])
            if rec_ch in by_channel:
                primary_ch = rec_ch

        has_reply = any(c['direction'] == 'entrant' and c['outcome'] in ('reponse', 'besoin') for c in convs)
        has_refusal = any(c['outcome'] == 'refus' for c in convs)
        has_bounce = any(c['outcome'] == 'rebond' for c in convs) or bool(info['data'].get('email_invalide'))
        has_confirmed = any(o['stage'] in ('besoin_confirme', 'proposition', 'gagne') for o in opps)
        has_won = any(o['stage'] == 'gagne' for o in opps)
        cash_cents = sum(ledger_by_opp.get(o['id'], {}).get('encaissement', 0) - ledger_by_opp.get(o['id'], {}).get('cout', 0) for o in opps)

        if primary_ch:
            b = by_channel[primary_ch]
            b['contacted'] += 1
            if has_reply:
                b['replied'] += 1
            if has_refusal:
                b['refused'] += 1
            if has_bounce:
                b['bounced'] += 1
            if has_confirmed:
                b['confirmed'] += 1
            if has_won:
                b['won'] += 1
            seg_bucket['contacted'] += 1

        if has_reply:
            seg_bucket['replied'] += 1
        if has_confirmed:
            seg_bucket['confirmed'] += 1
        if has_won:
            seg_bucket['won'] += 1
        seg_bucket['cash_mad'] = round(seg_bucket['cash_mad'] + cash_cents / 100.0, 2)

    for b in by_channel.values():
        b['reply_rate'] = round((b['replied'] * 100.0 / b['contacted']), 1) if b['contacted'] else 0.0

    b2c_refs = {}
    for row in con.execute('SELECT payload,status FROM intake').fetchall():
        p = json.loads(row['payload'])
        ref = p.get('b2c_ref')
        if not ref:
            dec = b2c.decoder_reference_b2c(p.get('message', ''))
            ref = dec['ref'] if dec else ''
        if ref:
            entry = b2c_refs.setdefault(ref, {'total': 0, 'converted': 0})
            entry['total'] += 1
            if row['status'] == 'traite':
                entry['converted'] += 1

    return {'by_channel': by_channel, 'by_segment': by_segment, 'b2c_refs': b2c_refs}


def dashboard():
    tables = ('opportunities', 'tasks', 'candidates', 'applications', 'assignments', 'conversations', 'proposals', 'ledger', 'intake', 'time_logs', 'audit_log')
    with connect() as con:
        result = {table: [dict(r) for r in con.execute(f'SELECT * FROM {table} ORDER BY id DESC LIMIT 1000')] for table in tables}
        totals = {r['kind']: r['amount'] for r in con.execute('SELECT kind,SUM(amount_cents) amount FROM ledger GROUP BY kind')}
        counts = dict(con.execute('SELECT stage,COUNT(*) FROM opportunities GROUP BY stage').fetchall())
        total_minutes = int(con.execute('SELECT COALESCE(SUM(minutes),0) FROM time_logs').fetchone()[0])
        metrics = {
            'opportunities': con.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0],
            'confirmed': sum(counts.get(stage, 0) for stage in ('besoin_confirme', 'proposition', 'gagne')),
            'won': counts.get('gagne', 0),
            'overdue': con.execute("SELECT COUNT(*) FROM tasks WHERE status='a_faire' AND due<?", (v.today().isoformat(),)).fetchone()[0],
            'active_assignments': con.execute("SELECT COUNT(*) FROM assignments WHERE status IN ('planifiee','en_cours')").fetchone()[0],
            'invoiced': totals.get('facture', 0) / 100,
            'received': totals.get('encaissement', 0) / 100,
            'cost': totals.get('cout', 0) / 100,
            'cash_contribution': (totals.get('encaissement', 0) - totals.get('cout', 0)) / 100,
            'total_minutes': total_minutes,
            'total_hours': round(total_minutes / 60.0, 2),
        }
        suppressed = {r['contact_key'] for r in con.execute('SELECT contact_key FROM suppressions')}
        active_perms = {r['record_id'] for r in con.execute('SELECT DISTINCT record_id FROM permissions WHERE active=1').fetchall()}
        followups = []
        today_date = v.today()
        for rec in con.execute("SELECT id,kind,payload FROM records WHERE kind IN ('b2b','b2c')").fetchall():
            item = json.loads(rec['payload'])
            is_sup = bool(set(messages.cles_contact(item)) & suppressed)
            ok_consent, _ = sources.contact_manuel_autorise(rec['kind'], item, rec['id'] in active_perms, is_sup)
            if not ok_consent:
                continue
            inbound = con.execute("SELECT 1 FROM conversations WHERE record_id=? AND ((direction='entrant' AND outcome!='rebond') OR outcome='refus')", (rec['id'],)).fetchone()
            if inbound:
                continue
            closed_opp = con.execute("SELECT 1 FROM opportunities WHERE record_id=? AND stage IN ('conversation','rendez_vous','besoin_confirme','proposition','gagne','perdu')", (rec['id'],)).fetchone()
            if closed_opp:
                continue
            out_conv_rows = con.execute("SELECT created,channel FROM conversations WHERE record_id=? AND direction='sortant' ORDER BY id", (rec['id'],)).fetchall()
            out_deliv_rows = con.execute("SELECT d.attempted_at,c.channel FROM deliveries d JOIN campaigns c ON c.id=d.campaign_id WHERE d.record_id=? AND d.attempted_at!='' AND d.status IN ('accepted','delivered','read','unknown') ORDER BY d.id", (rec['id'],)).fetchall()
            outbounds = sorted(
                [(r['created'], r['channel']) for r in out_conv_rows if len(r['created']) >= 10]
                + [(r['attempted_at'], r['channel']) for r in out_deliv_rows if len(r['attempted_at']) >= 10],
                key=lambda x: x[0],
            )
            if 1 <= len(outbounds) <= len(sources.RELANCES):
                try:
                    step = len(outbounds)
                    req_days = sources.RELANCES[step - 1]
                    ts_last, _ = outbounds[-1]
                    _, ch0 = outbounds[0]
                    days_since = (today_date - date.fromisoformat(ts_last[:10])).days
                    if days_since >= req_days:
                        rel_pack = messages.liens_relance(item, rec['kind'], 'fr', 'Service Commercial', ch0 or 'email', etape_relance=step)
                        followups.append({
                            'record_id': rec['id'],
                            'kind': rec['kind'],
                            'nom': item.get('nom', ''),
                            'followup_step': step,
                            'followup_label': rel_pack['libelle_relance'],
                            'days_since': days_since,
                            'last_outbound': ts_last[:10],
                            'initial_channel': ch0,
                            'recommended_channel': rel_pack['canal_recommande'],
                            'switch_to_whatsapp': rel_pack['bascule_mobile'],
                            'whatsapp': rel_pack['lien_whatsapp'],
                            'mailto': rel_pack['lien_email'],
                            'corps': rel_pack['message'],
                        })
                except ValueError:
                    pass
        daily_quota = quota_journalier(con, today_date)
        daily_queue = sources.construire_file_du_jour(con, today_date, sources.PLAFOND, 'Service Commercial', 'fr')
        source_roi = sources.calculer_roi_sources(con)
        funnel = calculer_entonnoir(con)
    for row in result['candidates']:
        row['skills'] = json.loads(row['skills'])
    for inc in result['intake']:
        try:
            ip = json.loads(inc['payload'])
        except json.JSONDecodeError:
            ip = {}
        dec = b2c.decoder_reference_b2c(ip.get('b2c_ref', '') or ip.get('message', '') or inc.get('source', ''))
        if dec:
            inc['b2c_decoded'] = dec
            if inc['kind'] in ('demande', 'a_qualifier'):
                rep_txt = messages.generer_reponse_qualification_b2c(
                    {'name': ip.get('name', ''), 'city': dec['ville'], 'zone': dec['zone'], 'besoin': dec['code_besoin'], 'ref': dec['ref']},
                    'fr',
                    'Service Commercial',
                )
                inc['qualification_reply'] = rep_txt
                inc['qualification_whatsapp'] = messages.lien_whatsapp({'tel': ip.get('tel', '')}, rep_txt)
                inc['qualification_mailto'] = messages.lien_email({'email': ip.get('email', '')}, rep_txt, 'b2c')
    result.update(
        metrics=metrics,
        followups=followups,
        daily_quota=daily_quota,
        daily_queue=daily_queue,
        source_roi=source_roi,
        sources_catalog=sources.SOURCES,
        relances_delais=list(sources.RELANCES),
        funnel=funnel,
        stages=STAGES,
        application_stages=APPLICATION_STAGES,
        metiers=emploi.METIERS,
        formats=emploi.FORMATS,
        today=v.today().isoformat(),
    )
    return result


def _matches_in_con(con, need_id):
    item = need(con, need_id)
    today_iso = v.today().isoformat()
    ville_besoin = item['ville'].strip().casefold()
    proches = BASSINS_PROCHES.get(ville_besoin, set())
    langues_besoin = {t.strip().casefold() for t in re.split(r'[,;/|]+', str(item.get('langues', ''))) if t.strip()}
    rows = con.execute("SELECT * FROM candidates WHERE status='actif'").fetchall()
    result = []
    for row in rows:
        reasons = []
        skills = json.loads(row['skills'])
        if item['metier'] in skills:
            reasons.append('Métier déclaré correspondant')
        ville_cand = row['city'].strip().casefold()
        if ville_besoin == ville_cand:
            reasons.append('Même ville déclarée')
        elif ville_cand in proches:
            reasons.append(f"Bassin géographique proche ({row['city']})")
        if row['available_until'] >= today_iso and row['availability_verified'] == today_iso:
            reasons.append('Disponibilité reconfirmée aujourd’hui')
        if langues_besoin:
            langues_cand = {t.strip().casefold() for t in re.split(r'[,;/|]+', str(row['languages'] or '')) if t.strip()}
            if langues_besoin & langues_cand:
                reasons.append('Langue déclarée compatible')
        clean_missions = con.execute(
            "SELECT COUNT(*) FROM assignments m JOIN applications a ON a.id=m.application_id WHERE a.candidate_id=? AND m.status='terminee' AND m.incident=''",
            (row['id'],),
        ).fetchone()[0]
        if clean_missions > 0:
            reasons.append(f'{clean_missions} mission(s) terminée(s) sans incident')
        conflict = bool(con.execute(
            "SELECT 1 FROM assignments m JOIN applications a ON a.id=m.application_id WHERE a.candidate_id=? AND m.status IN ('planifiee','en_cours') AND m.start<=? AND m.end>=?",
            (row['id'], today_iso, today_iso),
        ).fetchone())
        cand_dict = dict(row)
        cand_dict['skills'] = skills
        result.append({
            'candidate_id': row['id'],
            'name': row['name'],
            'anonymized_name': anonymiser_nom(row['name']),
            'score': len(reasons),
            'reasons': reasons,
            'conflict': conflict,
            'clean_missions': clean_missions,
            'presentation': _construire_fiche_presentation(cand_dict, item, clean_missions, 'fr'),
            'warning': 'Suggestion explicable, pas une vérification des compétences ni une décision de recrutement.',
        })
    return sorted(result, key=lambda r: (r['conflict'], -r['score'], r['candidate_id']))


def matches(need_id):
    with connect() as con:
        return _matches_in_con(con, need_id)


def import_records(body, actor='local'):
    if isinstance(body.get('csv'), str) and body['csv'].strip():
        kind = body.get('kind')
        if kind not in ('b2b', 'b2c'):
            raise ValueError('Choisissez B2B ou B2C pour un import CSV')
        reader = csv.DictReader(io.StringIO(v.text(body['csv'], 'Contenu CSV', True, 200000).lstrip('\ufeff')))
        if not reader.fieldnames:
            raise ValueError('En-têtes CSV manquants')
        allowed = {'nom', 'ville', 'zone', 'adresse', 'tel', 'whatsapp', 'email', 'source', 'source_url', 'url_source',
                   'date_consultation', 'date_source', 'date_derniere_verification', 'niveau', 'contexte',
                   'segment', 'phase', 'besoin', 'consentement'}
        items = []
        for row in reader:
            if None in row:
                raise ValueError('Colonnes CSV en surnombre sur une ligne')
            data = {str(k).strip(): str(val or '').strip() for k, val in row.items()
                    if k and str(k).strip() in allowed and str(val or '').strip() != ''}
            if not data:
                continue
            if 'url_source' in data and 'source_url' not in data:
                data['source_url'] = data.pop('url_source')
            else:
                data.pop('url_source', None)
            if 'date_source' in data and 'date_consultation' not in data:
                data['date_consultation'] = data.pop('date_source')
            else:
                data.pop('date_source', None)
            if 'consentement' in data:
                raw_c = data.pop('consentement')
                if raw_c not in ('0', '1'):
                    data['consentement_declare'] = raw_c  # déclenchera une erreur explicite dans v.record
                else:
                    data['consentement_declare'] = (raw_c == '1')
            if kind == 'b2b':
                if 'phase' in data:
                    try:
                        data['phase'] = int(data['phase'])
                    except ValueError:
                        pass
                else:
                    data['phase'] = prospection.phase_de(data)
                data.setdefault('zone', 'Ville entière')
            elif kind == 'b2c':
                data.setdefault('zone', 'À préciser')
            items.append({'kind': kind, 'data': data})
    else:
        items = body.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError('Entre 1 et 200 fiches attendues')
    apply = body.get('apply') is True
    result, seen = [], set()
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for row in con.execute("SELECT payload FROM records WHERE kind IN ('b2b','b2c')"):
            existing = json.loads(row[0])
            if not existing.get('exemple'):
                seen.update(messages.cles_contact(existing))
                nv = sources.cle_nom_ville(existing.get('nom', ''), existing.get('ville', ''))
                if nv:
                    seen.add(nv)
        for index, entry in enumerate(items):
            try:
                if not isinstance(entry, dict):
                    raise ValueError('Fiche invalide')
                kind, item = entry.get('kind'), entry.get('data')
                if kind not in ('b2b', 'b2c'):
                    raise ValueError('Import de prospects B2B/B2C uniquement')
                v.record(kind, item)
                if item.get('source_type')=='entrant':
                    raise ValueError('Importer des sources publiques seulement ; traiter les demandes dans leur file dédiée')
                keys = set(messages.cles_contact(item))
                nv = sources.cle_nom_ville(item.get('nom', ''), item.get('ville', ''))
                if nv:
                    keys.add(nv)
                if keys & seen:
                    raise ValueError('Doublon de coordonnée ou établissement : rapprocher la fiche existante')
                seen.update(keys)
                result.append({'index': index + 1, 'ok': True})
            except (ValueError, TypeError, KeyError) as exc:
                result.append({'index': index + 1, 'ok': False, 'error': str(exc)})
        if apply:
            if not all(r['ok'] for r in result):
                raise ValueError('Import annulé : corrigez toutes les lignes dans l’aperçu')
            for entry in items:
                # Les champs d'autorisation ne sont pas importés dans permissions.
                con.execute('INSERT INTO records(kind,payload) VALUES (?,?)', (entry['kind'], json.dumps(entry['data'])))
            audit(con, actor, 'import', 'records', detail=str(len(items)) + ' fiches')
    return {'applied': apply, 'rows': result}


def intake_submit(body):
    """File entrante : ni prospect autorisé ni candidat actif créé automatiquement."""
    kind = body.get('kind')
    if kind not in ('demande', 'candidature') or body.get('acknowledge') is not True:
        raise ValueError('Type et accord de traitement de la demande requis')
    if body.get('website'):
        raise ValueError('Soumission refusée')
    email, tel = v.contact(body.get('email', ''), body.get('tel', ''))
    source = field(body, 'source', False, 200) or 'site_formulaire'
    msg_txt = field(body, 'message')
    city_txt = field(body, 'city', False, 100)
    zone_txt = field(body, 'zone', False, 100)
    ref_txt = field(body, 'b2c_ref', False, 40)
    decoded = b2c.decoder_reference_b2c(ref_txt + ' ' + msg_txt + ' ' + source) if kind == 'demande' else None
    if not city_txt and decoded:
        city_txt = decoded['ville']
    if not city_txt:
        city_txt = field(body, 'city', limit=100)
    item = {'name': field(body, 'name', limit=150), 'email': email, 'tel': tel,
            'city': city_txt, 'message': msg_txt,
            'acknowledge': True, 'notice_version': '2026-10-21'}
    if zone_txt:
        item['zone'] = zone_txt
    if decoded:
        item.update(
            zone=zone_txt or decoded['zone'],
            besoin=decoded['code_besoin'],
            b2c_ref=decoded['ref'],
            origin='site_formulaire',
        )
    if kind == 'candidature':
        with connect() as con:
            job = need(con, body['need_id'])
            if not any(r['publiable'] == 'oui' for r in emploi.construire_lignes([job], 'fr', False)):
                raise ValueError('Annonce non ouverte aux candidatures')
        item['need_id'] = int(body['need_id'])
    with connect() as con:
        iid = con.execute('INSERT INTO intake(kind,payload,source,created) VALUES (?,?,?,?)', (kind, json.dumps(item), source, now())).lastrowid
        audit(con, 'public', 'soumission', 'intake', iid)
    return {'ok': True, 'reference': f'ENT-{iid:06d}'}


def public_jobs():
    result = []
    with connect() as con:
        rows = con.execute("SELECT id,payload FROM records WHERE kind='emploi'").fetchall()
    for row in rows:
        item = json.loads(row['payload'])
        for line in emploi.construire_lignes([item], 'fr', False):
            if line['publiable'] == 'oui':
                result.append({'id': row['id'], 'ref': line['ref'], 'poste': line['poste'], 'ville': line['ville'], 'annonce': line['annonce']})
    return result


BACKUP_LOCK = threading.Lock()


def backup(db_path, actor='system'):
    with BACKUP_LOCK:
        directory = Path(db_path).parent / 'backups'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / ('yallah-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
        # backup SQLite cohérent même avec un serveur actif ; pas de copie de fichiers en écriture.
        with connect() as source, sqlite3.connect(path) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Contrôle de sauvegarde échoué')
        path.chmod(0o600)
        with connect() as con:
            con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('last_backup', now()))
            con.execute("DELETE FROM settings WHERE key='backup_error'")
            audit(con, actor, 'backup', 'system', detail=path.name)
        return {'filename': path.name, 'integrity': 'ok'}


def export_json(output_dir, overwrite=False, actor='cli'):
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    mapping = [('b2b', 'prospects_b2b.json', 'prospects'),
               ('b2c', 'prospects_b2c.json', 'prospects'),
               ('emploi', 'besoins_emploi.json', 'besoins')]
    if not overwrite:
        for _, filename, _ in mapping:
            if (target / filename).exists():
                raise ValueError(f'Fichier déjà présent ({filename}) : utilisez un dossier vide ou --overwrite')
    counts = {}
    with connect() as con:
        suppressed = [r['contact_key'].split(':', 1)[1] for r in con.execute('SELECT contact_key FROM suppressions ORDER BY contact_key')]
        for kind, filename, list_key in mapping:
            row = con.execute('SELECT value FROM settings WHERE key=?', ('meta_' + kind,)).fetchone()
            meta = json.loads(row[0]) if row else {}
            if kind in ('b2b', 'b2c'):
                merged_refus = list(dict.fromkeys(list(meta.get('refus', [])) + suppressed))
                meta['refus'] = merged_refus
                meta['date_maj'] = v.today().isoformat()
            rows = [json.loads(r['payload']) for r in con.execute('SELECT payload FROM records WHERE kind=? ORDER BY id', (kind,))]
            if kind in ('b2b', 'b2c'):
                # Seules les fiches sourcées publiquement sont exportées vers les JSON CLI.
                rows = [r for r in rows if r.get('source_type') != 'entrant']
            payload = {'meta': meta, list_key: rows}
            (target / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            counts[filename] = len(rows)
        audit(con, actor, 'export_json', 'system', detail=str(target))
    return {'directory': str(target), 'files': counts}
