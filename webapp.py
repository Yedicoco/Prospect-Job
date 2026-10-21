"""Interface web Yallah : suivi manuel et campagnes contrôlées, simulation par défaut."""
import base64
import hmac
import html
import campaigns
import operations
import validation
import access
import webhooks
import argparse
import csv
import io
import json
import os
import secrets
import time
import threading
import sqlite3
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import yallah_messages as messages
import yallah_emploi as emploi
import yallah_b2c as b2c
from yallah_prospection import SEGMENTS

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('YALLAH_DB', ROOT / 'data' / 'yallah.sqlite3'))
TOKEN = secrets.token_urlsafe(32)

_intake_hits = {}
_intake_lock = threading.Lock()

def intake_rate_limit(ip):
    with _intake_lock:
        now = time.monotonic()
        for key in list(_intake_hits):
            if now - _intake_hits[key][0] >= 3600:
                del _intake_hits[key]
        stamp, hits = _intake_hits.get(ip, (now, 0))
        if hits >= 10 or len(_intake_hits) >= 10000:
            return False
        _intake_hits[ip] = (stamp, hits + 1)
        return True

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con

def initialize(recover=True):
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript('CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, record_id INTEGER, action TEXT, created TEXT); CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);')
        if not con.execute("SELECT 1 FROM settings WHERE key='initialized'").fetchone():
            for kind, filename, key in [('b2b','prospects_b2b.json','prospects'),('b2c','prospects_b2c.json','prospects'),('emploi','besoins_emploi.json','besoins')]:
                source = json.loads((ROOT / filename).read_text())
                for item in source[key]:
                    con.execute('INSERT INTO records(kind,payload) VALUES (?,?)',(kind,json.dumps(item,ensure_ascii=False)))
                con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('meta_'+kind,json.dumps(source.get('meta',{}))))
            con.execute("INSERT INTO settings VALUES ('initialized','yes')")
    campaigns.configure(connect, state, recover=recover)
    operations.configure(connect)
    access.configure(connect)
    access.production_check()
    DB.chmod(0o600)

def state(prenom='', langue='fr'):
    with connect() as con:
        records = [dict(r) for r in con.execute('SELECT * FROM records ORDER BY id')]
        metas = {r['key']:json.loads(r['value']) for r in con.execute("SELECT * FROM settings WHERE key LIKE 'meta_%'")}
        events = [dict(r) for r in con.execute('SELECT * FROM events ORDER BY id DESC LIMIT 200')]
        suppressed_contacts = [r['contact_key'].split(':', 1)[1] for r in con.execute('SELECT contact_key FROM suppressions')]
        for kind in ('b2b', 'b2c'):
            metas.setdefault('meta_' + kind, {}).setdefault('refus', []).extend(suppressed_contacts)
    groups = {k:[] for k in ['b2b','b2c','emploi']}
    for r in records:
        r['data'] = json.loads(r.pop('payload'))
        groups[r['kind']].append(r['data'])
    lines = messages.construire_lignes([(k,{'meta':metas.get('meta_'+k,{}),'prospects':groups[k]}) for k in ['b2b','b2c']],langue,prenom,validation.today())
    for k in ['b2b','b2c']:
        ids = [r['id'] for r in records if r['kind']==k]
        prefix = messages.TYPES[k]['prefixe']
        for line in lines:
            if line['type']==k:
                line['id'] = ids[int(line['ref'].removeprefix(prefix+'-'))-1]
                if line['statut'] != 'PRET - envoi manuel':
                    line['lien_whatsapp'] = line['lien_email'] = ''
    ads = emploi.construire_lignes(groups['emploi'],langue,True)
    matrix = b2c.construire_matrice()
    for row in matrix:
        row['lien'] = b2c.lien_whatsapp(row)
    return {'records':records,'messages':lines,'annonces':ads,'events':events,'matrice':matrix,'segments':list(SEGMENTS),'today':validation.today().isoformat()}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Les URLs publiques contiennent un jeton de désinscription : ne pas les journaliser.
        path=urlparse(self.path).path
        if path == '/unsubscribe' or path.startswith('/webhooks/'):
            return
        # Ne pas écrire les query strings (noms, jetons, tags) dans les logs.
        if format.startswith('"%s"'):
            return super().log_message('%s %s %s',self.command,path,args[1] if len(args)>1 else '')
        super().log_message('Requête %s',path)

    def authorized(self):
        self.user = access.authenticate(self.headers.get('Authorization', ''))
        if self.user:
            return True
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Yallah", charset="UTF-8"')
        self.end_headers()
        return False

    def permit(self, action):
        if access.allow(self.user['role'], action):
            return True
        self.respond({'error': 'Droits insuffisants pour cette action'}, 403)
        return False

    def json_body(self, limit=100000):
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= limit:
            raise ValueError('Taille de requête invalide')
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise ValueError('Objet JSON attendu')
        return data

    def unsubscribe_page(self, args, apply=False):
        try:
            did = args.get('id', [''])[0]
            token = args.get('token', [''])[0]
            campaigns.unsubscribe(did, token, apply)
            content = ('<h1>Désinscription enregistrée</h1><p>Vous ne recevrez plus de prospection à ces coordonnées.</p>' if apply else
                       '<h1>Ne plus être contacté</h1><p>Confirmez votre retrait des campagnes Yallah Services.</p>'
                       '<form method="post" action="/unsubscribe"><input type="hidden" name="id" value="' + html.escape(did, quote=True) +
                       '"><input type="hidden" name="token" value="' + html.escape(token, quote=True) +
                       '"><button type="submit">Confirmer ma désinscription</button></form>')
            self.respond(('<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="referrer" content="no-referrer"><title>Désinscription — Yallah</title><body style="font:16px system-ui;max-width:620px;margin:70px auto;padding:20px">' + content + '</body></html>').encode(), mime='text/html; charset=utf-8')
        except ValueError:
            self.respond({'error': 'Lien de désinscription invalide.'}, 400)

    def respond(self, value, status=200, mime='application/json; charset=utf-8'):
        raw = value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        url = urlparse(self.path)
        args = parse_qs(url.query)
        if url.path == '/unsubscribe':
            return self.unsubscribe_page(args)
        if url.path == '/webhooks/meta':
            token = os.getenv('WHATSAPP_VERIFY_TOKEN', '')
            if token and hmac.compare_digest(args.get('hub.verify_token', [''])[0], token) and args.get('hub.mode') == ['subscribe']:
                return self.respond(args.get('hub.challenge', [''])[0].encode(), mime='text/plain')
            return self.respond({'error': 'Vérification invalide'}, 403)
        if url.path in ('/demande', '/candidature'):
            return self.respond((ROOT/'web'/'public.html').read_bytes(), mime='text/html; charset=utf-8')
        if url.path == '/public.js':
            return self.respond((ROOT/'web'/'public.js').read_bytes(), mime='text/javascript; charset=utf-8')
        if url.path == '/api/public/jobs':
            return self.respond(operations.public_jobs())
        if not self.authorized():
            return
        if url.path == '/api/operations':
            result = operations.dashboard()
            if self.user['role'] in ('commercial', 'lecture'):
                for key in ('candidates', 'applications', 'assignments'):
                    result[key] = []
                result['intake'] = [r for r in result['intake'] if r['kind'] == 'demande']
            if self.user['role'] != 'admin':
                result['audit_log'] = []
            return self.respond(result)
        if url.path == '/api/matches':
            if self.user['role'] not in ('admin', 'recrutement'):
                return self.respond({'error': 'Accès recrutement requis'}, 403)
            try:
                return self.respond(operations.matches(int(args.get('need_id', ['0'])[0])))
            except (ValueError, KeyError, TypeError) as exc:
                return self.respond({'error': str(exc)}, 400)
        if url.path == '/api/health':
            return self.respond(campaigns.health())
        if url.path == '/api/campaigns':
            return self.respond(campaigns.dashboard())
        if url.path == '/api/state' or url.path == '/api/export':
            langue=args.get('langue',['fr'])[0]
            if langue not in ['fr','darija','arabe']:
                return self.respond({'error':'Langue invalide'},400)
            data=state(args.get('prenom',[''])[0],langue)
            if url.path.endswith('export'):
                out=io.StringIO(); fields=['ref','nom','ville','statut','message','alertes','motifs_non_qualification','lien_whatsapp','lien_email']
                writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore'); writer.writeheader(); writer.writerows({k: ("'" + str(v) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v) for k, v in row.items()} for row in data['messages'])
                return self.respond(('\ufeff'+out.getvalue()).encode(),mime='text/csv; charset=utf-8')
            data['token']=TOKEN
            data['user']=self.user
            return self.respond(data)
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/operations.js':'operations.js'}
        if url.path not in files: return self.respond({'error':'Introuvable'},404)
        file=ROOT/'web'/files[url.path]
        mime={'html':'text/html','js':'text/javascript','css':'text/css'}[file.suffix[1:]]
        self.respond(file.read_bytes(),mime=mime+'; charset=utf-8')
    def do_POST(self):
        public_path = urlparse(self.path).path
        if public_path.startswith('/webhooks/'):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1000000:
                    raise ValueError('Événement trop volumineux')
                raw = self.rfile.read(size)
                return self.respond(webhooks.receive(public_path.rsplit('/', 1)[1], raw, self.headers))
            except (ValueError, TypeError, KeyError) as exc:
                return self.respond({'error': str(exc)}, 400)
        if public_path == '/api/public/intake':
            try:
                if not intake_rate_limit(self.client_address[0]):
                    return self.respond({'error': 'Trop de demandes, réessayez plus tard'}, 429)
                return self.respond(operations.intake_submit(self.json_body(15000)))
            except (ValueError, TypeError, KeyError) as exc:
                return self.respond({'error': str(exc)}, 400)
        if urlparse(self.path).path == '/unsubscribe':
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096:
                    raise ValueError('Taille invalide')
                return self.unsubscribe_page(parse_qs(self.rfile.read(size).decode()), apply=True)
            except (ValueError, UnicodeDecodeError):
                return self.respond({'error': 'Requête invalide'}, 400)
        if not self.authorized():
            return
        if self.headers.get('X-Yallah-Token') != TOKEN:
            return self.respond({'error':'Session invalide. Rechargez la page.'},403)
        try:
            body=self.json_body()
            actor = self.user['username']
            if self.path == '/api/operations':
                action = body.get('action')
                if not self.permit(action): return
                if action=='intake_status':
                    with connect() as con:
                        incoming=operations.require(con,'intake',body['id'])
                    if incoming['kind']=='candidature' and self.user['role'] not in ('admin','recrutement'):
                        return self.respond({'error':'Accès recrutement requis'},403)
                return self.respond(operations.execute(action, body, actor))
            if self.path in ('/api/import', '/api/backup', '/api/campaigns/stop', '/api/campaigns/create', '/api/campaigns/control', '/api/permissions'):
                if not self.permit('admin'): return
            if self.path == '/api/import':
                return self.respond(operations.import_records(body, actor))
            if self.path == '/api/backup':
                return self.respond(operations.backup(DB, actor))
            if self.path == '/api/campaigns/stop':
                return self.respond(campaigns.emergency_stop(body.get('stop') is True, actor))
            if self.path == '/api/campaigns/create':
                return self.respond({'id': campaigns.create(body, actor)})
            if self.path == '/api/campaigns/control':
                campaigns.control(body, actor)
                return self.respond({'ok': True})
            if self.path == '/api/permissions':
                campaigns.set_permission(body, actor)
                return self.respond({'ok': True})
            with connect() as con:
                if self.path=='/api/save':
                    kind=body['kind']; item=body['data']; rid=body.get('id')
                    if not self.permit('need_save' if kind=='emploi' else 'prospect_save'): return
                    if kind not in ['b2b','b2c','emploi'] or not isinstance(item,dict): raise ValueError('Fiche invalide')
                    validation.record(kind, item)
                    if item.get('source_type')=='entrant':
                        incoming=operations.require(con,'intake',int(item['source_reference'].split('-')[1]))
                        if incoming['kind']!='demande': raise ValueError('Provenance entrante client requise')
                    if kind == 'emploi':
                        duplicate=con.execute("SELECT id FROM records WHERE kind='emploi' AND json_extract(payload,'$.ref')=? AND id!=?", (item['ref'], rid or -1)).fetchone()
                        if duplicate: raise ValueError('Référence de poste déjà utilisée')
                    if rid:
                        old=con.execute('SELECT * FROM records WHERE id=? AND kind=?',(rid,kind)).fetchone()
                        if not old: raise ValueError('Fiche introuvable')
                        con.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),rid))
                    else:
                        rid=con.execute('INSERT INTO records(kind,payload) VALUES (?,?)',(kind,json.dumps(item,ensure_ascii=False))).lastrowid
                    action='Fiche enregistrée'
                elif self.path=='/api/action':
                    if not self.permit('manual_action'): return
                    rid=int(body['id']); action=body['action']
                    row=con.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone()
                    if not row: raise ValueError('Fiche introuvable')
                    item=json.loads(row['payload'])
                    if action=='Vérifié aujourd’hui':
                        item.setdefault('date_collecte_originale', item.get('date_consultation', ''))
                        con.execute('INSERT INTO verifications(record_id,source_url,previous_date,actor,created) VALUES (?,?,?,?,?)', (rid,item.get('source_url',''),item.get('date_consultation',''),actor,operations.now()))
                        item['date_derniere_verification']=validation.today().isoformat()
                        item['date_consultation']=validation.today().isoformat()
                        con.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),rid))
                    elif action=='Ne plus contacter':
                        operations.suppress(con, rid, actor)
                    elif action not in ['Contact envoyé manuellement','Réponse reçue','Besoin confirmé','Note']:
                        raise ValueError('Action inconnue')
                    if action in ('Contact envoyé manuellement', 'Réponse reçue'):
                        channel=body.get('channel','interne')
                        if channel not in ('email','whatsapp','telephone','interne'): raise ValueError('Canal invalide')
                        con.execute('INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,?,?,?,?,?)', (rid,channel,'sortant' if action=='Contact envoyé manuellement' else 'entrant',str(body.get('note',''))[:2000] or action,'note' if action=='Contact envoyé manuellement' else 'reponse',operations.now()))
                    if body.get('note'): action+=' — '+str(body['note'])[:1000]
                else: return self.respond({'error':'Introuvable'},404)
                con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)',(rid,action,operations.now()))
                operations.audit(con,actor,action,'records',rid)
            self.respond({'ok':True})
        except (ValueError,KeyError,TypeError,sqlite3.IntegrityError) as e:
            self.respond({'error':str(e)},400)

def scheduled_backups():
    while True:
        try:
            with connect() as con:
                row=con.execute("SELECT value FROM settings WHERE key='last_backup'").fetchone()
            if not row or row[0][:10] != operations.now()[:10]:
                operations.backup(DB)
        except Exception as exc:
            import logging
            logging.error('Sauvegarde automatique : %s',type(exc).__name__)
            try:
                with connect() as con:
                    con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('backup_error',type(exc).__name__))
            except Exception:
                pass
        threading.Event().wait(3600)


def server_lock():
    # Verrou de processus pour éviter deux workers et une restauration pendant le service.
    try:
        import fcntl
    except ImportError:
        raise RuntimeError('Ce mode serveur requiert un environnement POSIX pour le verrou de base')
    DB.parent.mkdir(parents=True, exist_ok=True)
    handle=open(str(DB)+'.lock','a')
    try:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError('Un serveur utilise déjà cette base. Arrêtez-le avant cette opération.')
    return handle

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8000); args=parser.parse_args()
    _lock=server_lock()
    initialize()
    campaigns.start_worker()
    if os.getenv('YALLAH_AUTO_BACKUP','1')=='1':
        threading.Thread(target=scheduled_backups,daemon=True,name='Yallah-backups').start()
    print(f'Yallah Services : http://0.0.0.0:{args.port} — campagnes en simulation par défaut',flush=True)
    ThreadingHTTPServer(('0.0.0.0',args.port),Handler).serve_forever()
