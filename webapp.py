"""Interface web Yallah : suivi manuel et campagnes contrôlées, simulation par défaut."""
import base64
import hmac
import html
import campaigns
import argparse
import csv
import io
import json
import os
import secrets
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

def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def initialize():
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
    campaigns.configure(connect, state)

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
    lines = messages.construire_lignes([(k,{'meta':metas.get('meta_'+k,{}),'prospects':groups[k]}) for k in ['b2b','b2c']],langue,prenom,date.today())
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
    return {'records':records,'messages':lines,'annonces':ads,'events':events,'matrice':matrix,'segments':list(SEGMENTS),'today':date.today().isoformat()}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Les URLs publiques contiennent un jeton de désinscription : ne pas les journaliser.
        if urlparse(self.path).path == '/unsubscribe':
            return
        super().log_message(format, *args)

    def authorized(self):
        password = os.getenv('YALLAH_ADMIN_PASSWORD', '')
        if not password:
            return True
        expected = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()
        if hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            return True
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Yallah", charset="UTF-8"')
        self.end_headers()
        return False

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
        self.end_headers()
        self.wfile.write(raw)
    def do_GET(self):
        url = urlparse(self.path)
        args = parse_qs(url.query)
        if url.path == '/unsubscribe':
            return self.unsubscribe_page(args)
        if not self.authorized():
            return
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
            return self.respond(data)
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if url.path not in files: return self.respond({'error':'Introuvable'},404)
        file=ROOT/'web'/files[url.path]
        mime={'html':'text/html','js':'text/javascript','css':'text/css'}[file.suffix[1:]]
        self.respond(file.read_bytes(),mime=mime+'; charset=utf-8')
    def do_POST(self):
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
            size=int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 100000: raise ValueError('Taille de requête invalide')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Objet JSON attendu')
            if self.path == '/api/campaigns/create':
                return self.respond({'id': campaigns.create(body)})
            if self.path == '/api/campaigns/control':
                campaigns.control(body)
                return self.respond({'ok': True})
            if self.path == '/api/permissions':
                campaigns.set_permission(body)
                return self.respond({'ok': True})
            with connect() as con:
                if self.path=='/api/save':
                    kind=body['kind']; item=body['data']; rid=body.get('id')
                    if kind not in ['b2b','b2c','emploi'] or not isinstance(item,dict): raise ValueError('Fiche invalide')
                    problems=emploi.valider_besoin(item) if kind=='emploi' else messages.valider_fiche(item,kind)
                    if problems: raise ValueError(' ; '.join(problems))
                    if rid:
                        old=con.execute('SELECT * FROM records WHERE id=? AND kind=?',(rid,kind)).fetchone()
                        if not old: raise ValueError('Fiche introuvable')
                        con.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),rid))
                    else:
                        rid=con.execute('INSERT INTO records(kind,payload) VALUES (?,?)',(kind,json.dumps(item,ensure_ascii=False))).lastrowid
                    action='Fiche enregistrée'
                elif self.path=='/api/action':
                    rid=int(body['id']); action=body['action']
                    row=con.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone()
                    if not row: raise ValueError('Fiche introuvable')
                    item=json.loads(row['payload'])
                    if action=='Vérifié aujourd’hui':
                        item['date_derniere_verification']=date.today().isoformat()
                        item['date_consultation']=date.today().isoformat()
                        con.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),rid))
                    elif action=='Ne plus contacter':
                        for kind in ['b2b','b2c']:
                            key='meta_'+kind
                            meta=json.loads(con.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()[0])
                            meta.setdefault('refus',[]).extend([item[k] for k in ['tel','email'] if item.get(k)])
                            con.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(meta),key))
                    elif action not in ['Contact envoyé manuellement','Réponse reçue','Besoin confirmé','Note']:
                        raise ValueError('Action inconnue')
                    if body.get('note'): action+=' — '+str(body['note'])[:1000]
                else: return self.respond({'error':'Introuvable'},404)
                con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)',(rid,action,datetime.now().isoformat(timespec='seconds')))
            self.respond({'ok':True})
        except (ValueError,KeyError,TypeError) as e:
            self.respond({'error':str(e)},400)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8000); args=parser.parse_args()
    initialize()
    campaigns.start_worker()
    print(f'Yallah Services : http://0.0.0.0:{args.port} — campagnes en simulation par défaut',flush=True)
    ThreadingHTTPServer(('0.0.0.0',args.port),Handler).serve_forever()
