"""Campagnes persistantes : simulation par défaut, transport officiel activé explicitement.

Les états « accepté » signifient accepté par l'API, pas livré. Une tentative dont
l'issue réseau est ambiguë n'est jamais relancée automatiquement.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import yallah_messages as messages

connect = None
snapshot = None
wake = threading.Event()
MAX_DAILY = 15
MIN_INTERVAL = 60


def configure(connection_factory, state_factory):
    global connect, snapshot
    connect, snapshot = connection_factory, state_factory
    with connect() as con:
        con.executescript('''
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
        CREATE TABLE IF NOT EXISTS suppressions (
            contact_key TEXT PRIMARY KEY, created TEXT NOT NULL);
        ''')
        if not con.execute("SELECT 1 FROM settings WHERE key='unsubscribe_secret'").fetchone():
            con.execute('INSERT INTO settings VALUES (?,?)', ('unsubscribe_secret', secrets.token_hex(32)))
        # Un arrêt de processus en plein appel réseau ne doit jamais provoquer un doublon.
        con.execute("UPDATE deliveries SET status='unknown', reason='Processus interrompu : vérifier chez le fournisseur avant toute nouvelle prise de contact.' WHERE status='sending'")


def now():
    return datetime.now().isoformat(timespec='seconds')


def destination(item, channel):
    return (messages.email_normalise(str(item.get('email', ''))) if channel == 'email'
            else messages.tel_normalise(str(item.get('tel', ''))))


def contact_key(dest, channel):
    return ('mail:' if channel == 'email' else 'tel:') + dest


def validate_channel(channel):
    if channel not in ('email', 'whatsapp'):
        raise ValueError('Canal attendu : email ou whatsapp')


def runtime_errors(channel):
    errors = []
    if os.getenv('YALLAH_ENABLE_LIVE') != '1':
        errors.append('Envois réels désactivés côté serveur (YALLAH_ENABLE_LIVE).')
    if not os.getenv('YALLAH_ADMIN_PASSWORD') or len(os.getenv('YALLAH_ADMIN_PASSWORD', '')) < 16:
        errors.append('Protection administrateur requise (mot de passe de 16 caractères minimum).')
    base = urlparse(os.getenv('YALLAH_PUBLIC_URL', ''))
    if base.scheme != 'https' or not base.netloc or base.query or base.fragment or base.username:
        errors.append('URL publique HTTPS requise pour la désinscription.')
    fields = (['RESEND_API_KEY', 'YALLAH_FROM_EMAIL'] if channel == 'email' else
              ['WHATSAPP_ACCESS_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_TEMPLATE_NAME', 'WHATSAPP_TEMPLATE_LANGUAGE'])
    if any(not os.getenv(key) for key in fields):
        errors.append('Fournisseur non configuré : ' + ', '.join(fields))
    if channel == 'whatsapp':
        if os.getenv('WHATSAPP_TEMPLATE_REVIEWED') != '1':
            errors.append('Confirmer la validation du modèle WhatsApp et de sa variable de texte.')
        phone_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID', '')
        if phone_id and not phone_id.isdigit():
            errors.append('Identifiant WhatsApp invalide.')
        version = os.getenv('WHATSAPP_GRAPH_VERSION', 'v23.0')
        if not re.fullmatch(r'v\d+\.\d+', version):
            errors.append('Version Graph invalide.')
    return errors


def permitted(con, rid, channel, dest):
    row = con.execute('SELECT * FROM permissions WHERE record_id=? AND channel=?', (rid, channel)).fetchone()
    return bool(row and row['active'] and row['destination'] == dest and row['proof'].strip())


def suppressed(con, dest, channel):
    key = contact_key(dest, channel)
    if con.execute('SELECT 1 FROM suppressions WHERE contact_key=?', (key,)).fetchone():
        return True
    for row in con.execute("SELECT value FROM settings WHERE key IN ('meta_b2b','meta_b2c')"):
        if key in messages.exclusions_globales({'meta': json.loads(row['value'])}):
            return True
    return False


def eligibility(con, rid, channel, signer, language):
    """Revalidation complète, y compris au moment du départ effectif."""
    row = con.execute('SELECT * FROM records WHERE id=?', (rid,)).fetchone()
    if not row or row['kind'] not in ('b2b', 'b2c'):
        return '', '', ['Prospect introuvable ou candidat : campagne interdite.']
    item = json.loads(row['payload'])
    dest = destination(item, channel)
    errors = []
    if channel == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', dest):
        errors.append('Adresse email absente ou invalide.')
    if channel == 'whatsapp' and not re.fullmatch(r'[1-9]\d{7,14}', dest):
        errors.append('Téléphone international absent ou invalide ; disponibilité WhatsApp à confirmer.')
    if not signer.strip():
        errors.append('Prénom du signataire manquant.')
    if not permitted(con, rid, channel, dest):
        errors.append('Autorisation par canal non documentée pour cette coordonnée.')
    if suppressed(con, dest, channel):
        errors.append('Contact au registre des refus.')
    # Réutiliser les règles existantes : exemples, sources, fraîcheur, doublons et refus.
    data = snapshot(signer, language)
    line = next((line for line in data['messages'] if line['id'] == rid), None)
    if not line or line['statut'] != 'PRET - envoi manuel':
        errors.append((line or {}).get('motifs_non_qualification') or (line or {}).get('alertes') or 'Message non qualifié.')
    text = (line or {}).get('_brut', '')
    return dest, text, errors


def dashboard():
    with connect() as con:
        campaigns = [dict(row) for row in con.execute('SELECT * FROM campaigns ORDER BY id DESC')]
        deliveries = [dict(row) for row in con.execute('SELECT * FROM deliveries ORDER BY id DESC')]
        permissions = [dict(row) for row in con.execute('SELECT * FROM permissions')]
    return {'campaigns': campaigns, 'deliveries': deliveries, 'permissions': permissions,
            'providers': {c: {'ready': not runtime_errors(c), 'errors': runtime_errors(c)} for c in ('email', 'whatsapp')},
            'max_daily': MAX_DAILY, 'min_interval': MIN_INTERVAL}


def set_permission(body):
    rid = int(body['id'])
    channel = body['channel']
    validate_channel(channel)
    proof = str(body.get('proof', '')).strip()
    active = body.get('active') is True
    if active and len(proof) < 12:
        raise ValueError('Documentez la preuve, la date et la portée de l’autorisation (12 caractères minimum).')
    with connect() as con:
        row = con.execute('SELECT * FROM records WHERE id=?', (rid,)).fetchone()
        if not row or row['kind'] not in ('b2b', 'b2c'):
            raise ValueError('Prospect introuvable.')
        item = json.loads(row['payload'])
        dest = destination(item, channel)
        if not dest:
            raise ValueError('Coordonnée absente pour ce canal.')
        if active and (item.get('exemple') or suppressed(con, dest, channel)):
            raise ValueError('Exemple ou contact ayant refusé : autorisation impossible.')
        con.execute('INSERT OR REPLACE INTO permissions VALUES (?,?,?,?,?,?)',
                    (rid, channel, dest, proof, now(), int(active)))
        con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)',
                    (rid, ('Autorisation documentée : ' if active else 'Autorisation retirée : ') + channel, now()))


def create(body):
    channel = body['channel']
    validate_channel(channel)
    signer = str(body.get('signer', '')).strip()[:100]
    language = body.get('language', 'fr')
    if language not in ('fr', 'darija', 'arabe'):
        raise ValueError('Langue invalide.')
    name = str(body.get('name', '')).strip()[:160]
    if not name or not signer:
        raise ValueError('Nom de campagne et prénom requis.')
    ids = list(dict.fromkeys(int(rid) for rid in body.get('ids', [])))
    if not ids or len(ids) > 200:
        raise ValueError('Sélectionnez entre 1 et 200 prospects.')
    with connect() as con:
        cid = con.execute('INSERT INTO campaigns(name,channel,signer,language,created) VALUES (?,?,?,?,?)',
                          (name, channel, signer, language, now())).lastrowid
        seen = set()
        for rid in ids:
            dest, text, errors = eligibility(con, rid, channel, signer, language)
            if dest in seen:
                errors.append('Coordonnée en double dans cette campagne.')
            seen.add(dest)
            con.execute('INSERT INTO deliveries(campaign_id,record_id,destination,body,status,reason,created) VALUES (?,?,?,?,?,?,?)',
                        (cid, rid, dest, text, 'blocked' if errors else 'simulated', ' | '.join(errors) or 'Simulation réussie — aucun appel fournisseur.', now()))
    return cid


def control(body):
    cid = int(body['id'])
    action = body['action']
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        campaign = con.execute('SELECT * FROM campaigns WHERE id=?', (cid,)).fetchone()
        if not campaign:
            raise ValueError('Campagne introuvable.')
        if action in ('pause', 'cancel'):
            con.execute('UPDATE campaigns SET status=? WHERE id=?', ('paused' if action == 'pause' else 'cancelled', cid))
            if action == 'cancel':
                con.execute("UPDATE deliveries SET status='cancelled', reason='Campagne annulée.' WHERE campaign_id=? AND status IN ('queued','blocked','simulated')", (cid,))
        elif action == 'activate':
            if campaign['status'] in ('cancelled', 'completed'):
                raise ValueError('Campagne terminée : créez une nouvelle simulation.')
            errors = runtime_errors(campaign['channel'])
            legal = str(body.get('legal_proof', '')).strip()
            if len(legal) < 20:
                errors.append('Documentez la validation du cadre applicable et la référence datée (20 caractères minimum).')
            if body.get('confirm') is not True:
                errors.append('Confirmation explicite requise pour activer les envois réels.')
            if errors:
                raise ValueError(' '.join(errors))
            count = 0
            for row in con.execute("SELECT * FROM deliveries WHERE campaign_id=? AND status IN ('simulated','blocked','queued')", (cid,)).fetchall():
                dest, text, reasons = eligibility(con, row['record_id'], campaign['channel'], campaign['signer'], campaign['language'])
                con.execute('UPDATE deliveries SET destination=?, body=?, status=?, reason=? WHERE id=?',
                            (dest, text, 'blocked' if reasons else 'queued', ' | '.join(reasons), row['id']))
                count += not reasons
            if not count:
                raise ValueError('Aucun destinataire autorisé et qualifié. Corrigez les fiches et recréez une simulation.')
            con.execute("UPDATE campaigns SET status='running', mode='live', legal_proof=? WHERE id=?", (legal, cid))
        else:
            raise ValueError('Action inconnue.')
    wake.set()


def secret(con):
    return con.execute("SELECT value FROM settings WHERE key='unsubscribe_secret'").fetchone()[0]


def unsubscribe_url(delivery_id):
    with connect() as con:
        signature = hmac.new(secret(con).encode(), str(delivery_id).encode(), hashlib.sha256).hexdigest()
    return os.getenv('YALLAH_PUBLIC_URL', '').rstrip('/') + '/unsubscribe?' + urlencode({'id': delivery_id, 'token': signature})


def unsubscribe(delivery_id, signature, apply=False):
    try:
        delivery_id = int(delivery_id)
    except (ValueError, TypeError):
        raise ValueError('Lien invalide.')
    with connect() as con:
        expected = hmac.new(secret(con).encode(), str(delivery_id).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(signature)):
            raise ValueError('Lien invalide.')
        row = con.execute('SELECT d.*, c.channel FROM deliveries d JOIN campaigns c ON c.id=d.campaign_id WHERE d.id=?', (delivery_id,)).fetchone()
        if not row:
            raise ValueError('Lien invalide.')
        if not apply:
            return
        # Révoquer toutes les coordonnées connues du prospect, pas seulement le canal du lien.
        record = con.execute('SELECT payload FROM records WHERE id=?', (row['record_id'],)).fetchone()
        keys = [contact_key(row['destination'], row['channel'])]
        if record:
            item = json.loads(record['payload'])
            keys.extend(messages.cles_contact(item))
            for kind in ('b2b', 'b2c'):
                setting = 'meta_' + kind
                meta_row = con.execute('SELECT value FROM settings WHERE key=?', (setting,)).fetchone()
                meta = json.loads(meta_row[0]) if meta_row else {}
                meta.setdefault('refus', []).extend([item[k] for k in ('email', 'tel') if item.get(k)])
                con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (setting, json.dumps(meta)))
        for key in keys:
            con.execute('INSERT OR IGNORE INTO suppressions VALUES (?,?)', (key, now()))
        con.execute('UPDATE permissions SET active=0 WHERE record_id=?', (row['record_id'],))
        con.execute("UPDATE deliveries SET status='blocked', reason='Désinscription du destinataire.' WHERE record_id=? AND status='queued'", (row['record_id'],))
        con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)', (row['record_id'], 'Désinscription via lien public', now()))


def send_http(url, token, payload, extra=None):
    request = Request(url, data=json.dumps(payload).encode(), headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', **(extra or {})}, method='POST')
    # Aucune journalisation des jetons, des réponses brutes ou des messages privés.
    with urlopen(request, timeout=25) as response:
        return json.load(response)


def transport(delivery, campaign):
    link = unsubscribe_url(delivery['id'])
    text = delivery['body'] + '\n\nNe plus être contacté / إلغاء الاشتراك : ' + link
    if campaign['channel'] == 'email':
        response = send_http('https://api.resend.com/emails', os.environ['RESEND_API_KEY'], {
            'from': os.environ['YALLAH_FROM_EMAIL'], 'to': [delivery['destination']],
            'subject': 'Yallah Services — échange sur vos besoins en personnel', 'text': text,
            'headers': {'List-Unsubscribe': '<' + link + '>'}},
            {'Idempotency-Key': 'yallah-delivery-' + str(delivery['id']) + '-' + hashlib.sha256(delivery['created'].encode()).hexdigest()[:16]})
        return str(response['id'])
    version = os.getenv('WHATSAPP_GRAPH_VERSION', 'v23.0')
    phone = os.environ['WHATSAPP_PHONE_NUMBER_ID']
    response = send_http(f'https://graph.facebook.com/{version}/{phone}/messages', os.environ['WHATSAPP_ACCESS_TOKEN'], {
        'messaging_product': 'whatsapp', 'to': delivery['destination'], 'type': 'template',
        'template': {'name': os.environ['WHATSAPP_TEMPLATE_NAME'],
                     'language': {'code': os.environ['WHATSAPP_TEMPLATE_LANGUAGE']},
                     'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': text.replace('\n', ' ')}]}]}})
    return str(response['messages'][0]['id'])


def tick():
    """Une tentative maximum par tick. Réservation atomique avant tout appel réseau."""
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute("SELECT COUNT(*) FROM deliveries WHERE attempted_at LIKE ?", (date.today().isoformat() + '%',)).fetchone()[0] >= MAX_DAILY:
            return
        latest = con.execute('SELECT MAX(attempted_at) FROM deliveries').fetchone()[0]
        if latest and datetime.now() - datetime.fromisoformat(latest) < timedelta(seconds=MIN_INTERVAL):
            return
        row = con.execute("SELECT d.* FROM deliveries d JOIN campaigns c ON c.id=d.campaign_id WHERE d.status='queued' AND c.status='running' ORDER BY d.id LIMIT 1").fetchone()
        if not row:
            con.execute("UPDATE campaigns SET status='completed' WHERE status='running' AND NOT EXISTS (SELECT 1 FROM deliveries WHERE campaign_id=campaigns.id AND status IN ('queued','sending'))")
            return
        delivery = dict(row)
        campaign = dict(con.execute('SELECT * FROM campaigns WHERE id=?', (row['campaign_id'],)).fetchone())
        dest, text, errors = eligibility(con, row['record_id'], campaign['channel'], campaign['signer'], campaign['language'])
        errors += runtime_errors(campaign['channel'])
        if not campaign['legal_proof']:
            errors.append('Validation du cadre applicable absente.')
        if dest != row['destination'] or text != row['body']:
            errors.append('Fiche ou message modifié depuis la validation : nouvelle simulation requise.')
        # Évite les doublons intercampagnes et les relances répétées, y compris après une issue incertaine.
        last = con.execute("SELECT MAX(attempted_at) FROM deliveries WHERE destination=? AND id!=? AND attempted_at IS NOT NULL", (dest, row['id'])).fetchone()[0]
        if last:
            errors.append('Coordonnée déjà sollicitée : aucune répétition automatique. Consulter l’historique.')
        if errors:
            con.execute("UPDATE deliveries SET status='blocked', reason=? WHERE id=?", (' | '.join(errors), row['id']))
            return
        con.execute("UPDATE deliveries SET status='sending', attempted_at=?, reason='' WHERE id=?", (now(), row['id']))
    try:
        provider_id = transport(delivery, campaign)
        result, reason = 'accepted', 'Accepté par le fournisseur ; livraison non confirmée.'
    except HTTPError as exc:
        provider_id = ''
        result = 'failed' if 400 <= exc.code < 500 and exc.code != 408 else 'unknown'
        reason = f'Réponse fournisseur HTTP {exc.code}. Aucune relance automatique.'
    except Exception:
        provider_id, result, reason = '', 'unknown', 'Issue réseau ou réponse incertaine : vérifier chez le fournisseur. Aucune relance automatique.'
    with connect() as con:
        con.execute('UPDATE deliveries SET status=?, reason=?, provider_id=? WHERE id=?', (result, reason, provider_id, delivery['id']))
        con.execute('INSERT INTO events(record_id,action,created) VALUES (?,?,?)',
                    (delivery['record_id'], f'Campagne {campaign["id"]} · {campaign["channel"]} · {result}', now()))


def worker():
    while True:
        try:
            tick()
        except Exception:
            # Pas d’exposition de détails privés dans les logs ; le prochain tick revalidera.
            pass
        wake.wait(5)
        wake.clear()


def start_worker():
    thread = threading.Thread(target=worker, daemon=True, name='Yallah-campaigns')
    thread.start()
    return thread
