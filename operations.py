"""Parcours commercial et recrutement, partagé par les API web et outils de gestion.
Les transactions conservent les relations et n'envoient aucun message.
"""
import csv
import io
import json
import re
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path

import validation as v
import yallah_emploi as emploi
import yallah_messages as messages

connect = None
STAGES = ['prospect', 'qualifie', 'conversation', 'rendez_vous', 'besoin_confirme', 'proposition', 'gagne', 'perdu']
APPLICATION_STAGES = ['recu', 'contacte', 'entretien', 'propose', 'accepte', 'refuse', 'retire']
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
CREATE INDEX IF NOT EXISTS opportunities_stage ON opportunities(stage);
CREATE INDEX IF NOT EXISTS tasks_due ON tasks(status,due);
CREATE INDEX IF NOT EXISTS conversations_record ON conversations(record_id,created);
CREATE INDEX IF NOT EXISTS delivery_destination ON deliveries(destination,attempted_at);
CREATE INDEX IF NOT EXISTS assignment_application ON assignments(application_id,start,end);
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
            if channel not in ('email', 'whatsapp', 'telephone', 'interne') or direction not in ('entrant', 'sortant', 'note') or outcome not in ('note', 'reponse', 'refus', 'besoin'):
                raise ValueError('Type de conversation invalide')
            if outcome == 'refus':
                suppress(con, rid, actor)
            cid = con.execute('INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,?,?,?,?,?)', (rid, channel, direction, field(body, 'body'), outcome, now())).lastrowid
            con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)', (rid, f'Conversation {direction} · {channel} · {outcome}', now()))
            result = {'id': cid}
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
        elif action == 'intake_opportunity':
            incoming=require(con,'intake',body['intake_id'])
            if incoming['kind']!='demande' or incoming['status']!='nouveau':
                raise ValueError('Demande client nouvelle requise')
            d=json.loads(incoming['payload'])
            d['name']=v.text(body.get('name') or d.get('name',''),'Nom client',True,150)
            d['city']=v.text(body.get('city') or d.get('city',''),'Ville client',True,100)
            due=v.day(body.get('due',''),'Échéance')
            owner,next_action=field(body,'owner'),field(body,'next_action')
            # Provenance interne réelle, sans inventer de page publique. Le moteur de
            # campagne maintient son blocage source/autorisation tant qu'il n'est pas qualifié.
            kind=body.get('kind')
            if kind not in ('b2b','b2c'): raise ValueError('Choisissez entreprise ou particulier')
            item={'nom':d['name'],'ville':d['city'],'zone':'À préciser','tel':d['tel'],'email':d['email'],
                  'niveau':'B','source_url':'','date_consultation':v.today().isoformat(),
                  'source_type':'entrant','source_reference':f'ENT-{incoming["id"]:06d}',
                  'contexte':d['message']}
            if kind=='b2b': item.update(segment=body.get('segment'),phase=1)
            else: item['besoin']=body.get('besoin')
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
            stop_words = {'stop', 'unsubscribe', 'arrêt', 'arret', 'désinscription', 'desinscription', 'إلغاء الاشتراك'}
            stop_phrases = ('ne plus me contacter', 'ne plus nous contacter', 'veuillez me désinscrire', 'veuillez me desinscrire', 'retirez-moi de votre liste', 'supprimez mon adresse')
            refusal = bool(probe_exact & stop_words) or any(p in probe_text for p in stop_phrases)
            full_text = f'Objet : {subject}\n\n{raw_body}'[:4000]
            matched_ids = []
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
            if matched_ids:
                result = {'id': matched_ids[0], 'classification': 'refus' if refusal else 'reponse_prospect', 'record_ids': matched_ids}
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
                payload = {'name': sender_name, 'email': sender_email, 'tel': '', 'city': '',
                           'message': full_text, 'acknowledge': False, 'notice_version': '', 'origin': 'email_entrant'}
                if len(open_matches) == 1:
                    payload['need_id'] = open_matches[0]
                    iid = con.execute("INSERT INTO intake(kind,payload,source,created) VALUES ('candidature',?,'email_entrant',?)", (json.dumps(payload), now())).lastrowid
                    result = {'id': iid, 'classification': 'candidature', 'need_id': open_matches[0]}
                else:
                    iid = con.execute("INSERT INTO intake(kind,payload,source,created) VALUES ('a_qualifier',?,'email_entrant',?)", (json.dumps(payload), now())).lastrowid
                    result = {'id': iid, 'classification': 'a_qualifier'}
        else:
            raise ValueError('Action métier inconnue')
        audit(con, actor, action, 'operations', result.get('id'))
    return result


def dashboard():
    tables = ('opportunities', 'tasks', 'candidates', 'applications', 'assignments', 'conversations', 'proposals', 'ledger', 'intake', 'audit_log')
    with connect() as con:
        result = {table: [dict(r) for r in con.execute(f'SELECT * FROM {table} ORDER BY id DESC LIMIT 1000')] for table in tables}
        totals = {r['kind']: r['amount'] for r in con.execute('SELECT kind,SUM(amount_cents) amount FROM ledger GROUP BY kind')}
        counts = dict(con.execute('SELECT stage,COUNT(*) FROM opportunities GROUP BY stage').fetchall())
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
        }
        suppressed = {r['contact_key'] for r in con.execute('SELECT contact_key FROM suppressions')}
        followups = []
        today_date = v.today()
        for rec in con.execute("SELECT id,payload FROM records WHERE kind IN ('b2b','b2c')").fetchall():
            item = json.loads(rec['payload'])
            if item.get('exemple') or (set(messages.cles_contact(item)) & suppressed):
                continue
            inbound = con.execute("SELECT 1 FROM conversations WHERE record_id=? AND (direction='entrant' OR outcome='refus')", (rec['id'],)).fetchone()
            if inbound:
                continue
            out_conv = [r['created'] for r in con.execute("SELECT created FROM conversations WHERE record_id=? AND direction='sortant'", (rec['id'],))]
            out_deliv = [r['attempted_at'] for r in con.execute("SELECT attempted_at FROM deliveries WHERE record_id=? AND attempted_at!='' AND status IN ('accepted','delivered','read','unknown')", (rec['id'],))]
            outbounds = sorted(ts for ts in (out_conv + out_deliv) if len(ts) >= 10)
            if len(outbounds) == 1:
                try:
                    days_since = (today_date - date.fromisoformat(outbounds[0][:10])).days
                    if days_since >= 7:
                        followups.append({'record_id': rec['id'], 'days_since': days_since, 'last_outbound': outbounds[0][:10]})
                except ValueError:
                    pass
    for row in result['candidates']:
        row['skills'] = json.loads(row['skills'])
    result.update(metrics=metrics, followups=followups, stages=STAGES, application_stages=APPLICATION_STAGES, metiers=emploi.METIERS, formats=emploi.FORMATS, today=v.today().isoformat())
    return result


def matches(need_id):
    with connect() as con:
        item = need(con, need_id)
        rows = con.execute("SELECT * FROM candidates WHERE status='actif'").fetchall()
        result = []
        for row in rows:
            reasons = []
            if item['metier'] in json.loads(row['skills']):
                reasons.append('Métier déclaré correspondant')
            if item['ville'].casefold() == row['city'].casefold():
                reasons.append('Même ville déclarée')
            if row['available_until'] >= v.today().isoformat() and row['availability_verified'] == v.today().isoformat():
                reasons.append('Disponibilité reconfirmée aujourd’hui')
            result.append({'candidate_id': row['id'], 'name': row['name'], 'score': len(reasons), 'reasons': reasons,
                           'warning': 'Suggestion explicable, pas une vérification des compétences ni une décision de recrutement.'})
    return sorted(result, key=lambda r: (-r['score'], r['candidate_id']))


def import_records(body, actor='local'):
    if isinstance(body.get('csv'), str) and body['csv'].strip():
        kind = body.get('kind')
        if kind not in ('b2b', 'b2c'):
            raise ValueError('Choisissez B2B ou B2C pour un import CSV')
        reader = csv.DictReader(io.StringIO(v.text(body['csv'], 'Contenu CSV', True, 200000).lstrip('\ufeff')))
        if not reader.fieldnames:
            raise ValueError('En-têtes CSV manquants')
        allowed = {'nom', 'ville', 'zone', 'adresse', 'tel', 'email', 'source_url', 'date_consultation',
                   'date_derniere_verification', 'niveau', 'contexte', 'segment', 'phase', 'besoin'}
        items = []
        for row in reader:
            if None in row:
                raise ValueError('Colonnes CSV en surnombre sur une ligne')
            data = {str(k).strip(): str(val or '').strip() for k, val in row.items()
                    if k and str(k).strip() in allowed and str(val or '').strip() != ''}
            if not data:
                continue
            if kind == 'b2b' and 'phase' in data:
                try:
                    data['phase'] = int(data['phase'])
                except ValueError:
                    pass
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
            seen.update(messages.cles_contact(json.loads(row[0])))
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
                if keys & seen:
                    raise ValueError('Doublon de coordonnée : rapprocher la fiche existante')
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
    item = {'name': field(body, 'name', limit=150), 'email': email, 'tel': tel,
            'city': field(body, 'city', limit=100), 'message': field(body, 'message'),
            'acknowledge': True, 'notice_version': '2026-10-21'}
    source = field(body, 'source', False, 200) or 'formulaire_public'
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
