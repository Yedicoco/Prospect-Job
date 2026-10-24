"""Vérification locale des signatures Meta et Svix/Resend, sans appel réseau."""
import base64
import hashlib
import hmac
import json
import os
import time

import operations
import yallah_messages as messages
import validation


def verify(provider, raw, headers):
    if provider == 'meta':
        secret = os.getenv('WHATSAPP_APP_SECRET', '')
        expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, headers.get('X-Hub-Signature-256', '')):
            raise ValueError('Signature Meta invalide')
    elif provider == 'resend':
        secret = os.getenv('RESEND_WEBHOOK_SECRET', '')
        event_id = headers.get('svix-id', '')
        stamp = headers.get('svix-timestamp', '')
        try:
            if abs(time.time() - int(stamp)) > 300 or not secret or not event_id:
                raise ValueError()
            key = base64.b64decode(secret.removeprefix('whsec_'), validate=True)
            signed = event_id.encode() + b'.' + stamp.encode() + b'.' + raw
            expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
            signatures = headers.get('svix-signature', '').split()
            if not any(hmac.compare_digest('v1,' + expected, signature) for signature in signatures):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('Signature Resend invalide ou périmée')
    else:
        raise ValueError('Fournisseur inconnu')
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Événement invalide')
    if provider=='resend' and not isinstance(data.get('data',{}),dict):
        raise ValueError('Données fournisseur invalides')
    if provider=='meta':
        entries=data.get('entry',[])
        if not isinstance(entries,list): raise ValueError('Liste d’événements attendue')
        for entry in entries:
            if not isinstance(entry,dict) or not isinstance(entry.get('changes',[]),list): raise ValueError('Événement Meta invalide')
            for change in entry.get('changes',[]):
                if not isinstance(change,dict) or not isinstance(change.get('value',{}),dict): raise ValueError('Événement Meta invalide')
                value=change.get('value',{})
                for key in ('messages','statuses'):
                    if not isinstance(value.get(key,[]),list) or any(not isinstance(r,dict) for r in value.get(key,[])): raise ValueError('Événement Meta invalide')
    return data


def status_event(con, provider, event_id, event_type, provider_id, state):
    validation.text(provider_id,'Identifiant fournisseur',True,300)
    validation.text(event_id,'Identifiant événement',True,500)
    delivery = con.execute('SELECT * FROM deliveries WHERE provider_id=? AND provider_id!=?', (provider_id, '')).fetchone()
    inserted = con.execute('INSERT OR IGNORE INTO provider_events(provider,event_id,event_type,delivery_id,received,provider_message_id,state) VALUES (?,?,?,?,?,?,?)', (provider, event_id, event_type, delivery['id'] if delivery else None, operations.now(), provider_id, state)).rowcount
    if not inserted or not delivery:
        return False
    priority = {'accepted': 0, 'unknown': 0, 'delivered': 1, 'read': 2, 'failed': 3, 'bounced': 4, 'complained': 5}
    if priority.get(state, 0) >= priority.get(delivery['status'], 0):
        con.execute('UPDATE deliveries SET status=?,reason=? WHERE id=?', (state, 'État reçu par webhook signé : ' + event_type, delivery['id']))
    if state in ('bounced', 'complained'):
        operations.suppress(con, delivery['record_id'], 'webhook:' + provider)
    operations.audit(con, 'webhook:' + provider, event_type, 'deliveries', delivery['id'])
    return True


def receive(provider, raw, headers):
    data = verify(provider, raw, headers)
    processed = 0
    with operations.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if provider == 'resend':
            mapping = {'email.delivered': 'delivered', 'email.bounced': 'bounced', 'email.complained': 'complained', 'email.failed': 'failed'}
            event_type = data.get('type', '')
            if event_type in mapping:
                processed += status_event(con, provider, headers.get('svix-id', ''), event_type, data.get('data', {}).get('email_id', ''), mapping[event_type])
        else:
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    for status in value.get('statuses', []):
                        state = status.get('status')
                        if state not in ('sent', 'delivered', 'read', 'failed'):
                            continue
                        eid = str(status.get('id', '')) + ':' + state + ':' + str(status.get('timestamp', ''))
                        processed += status_event(con, provider, eid, state, status.get('id', ''), 'accepted' if state == 'sent' else state)
                    for message in value.get('messages', []):
                        eid = message.get('id', '')
                        if not eid:
                            continue
                        inserted = con.execute('INSERT OR IGNORE INTO provider_events(provider,event_id,event_type,received) VALUES (?,?,?,?)', (provider, eid, 'incoming', operations.now())).rowcount
                        if not inserted:
                            continue
                        sender = messages.tel_normalise(str(message.get('from', '')))
                        content=message.get('text',{})
                        if not isinstance(content,dict) or not isinstance(content.get('body',''),str): raise ValueError('Texte entrant invalide')
                        text = content.get('body','')[:2000]
                        if not sender or not text:
                            continue
                        matched=False
                        refusal = text.strip().casefold().strip('.!؟?') in ('stop', 'unsubscribe', 'arrêt', 'arret', 'désinscription', 'desinscription', 'إلغاء الاشتراك')
                        for row in con.execute("SELECT * FROM records WHERE kind IN ('b2b','b2c')").fetchall():
                            item = json.loads(row['payload'])
                            nums = {messages.tel_normalise(item.get('tel', '')), messages.tel_normalise(item.get('whatsapp', ''))}
                            if sender not in nums:
                                continue
                            matched=True
                            if refusal:
                                operations.suppress(con, row['id'], 'webhook:meta')
                            con.execute("INSERT INTO conversations(record_id,channel,direction,body,outcome,provider_id,created) VALUES (?,'whatsapp','entrant',?,?,?,?)", (row['id'], text, 'refus' if refusal else 'reponse', eid, operations.now()))
                            operations.audit(con, 'webhook:meta', 'message_entrant', 'records', row['id'])
                            processed += 1
                        if not matched:
                            if refusal:
                                con.execute('INSERT OR IGNORE INTO suppressions VALUES (?,?)',('tel:'+sender,operations.now()))
                                operations.audit(con,'webhook:meta','refus_contact_inconnu','suppressions')
                            else:
                                profile_name='Contact WhatsApp à qualifier'
                                for contact in (value.get('contacts',[]) if isinstance(value.get('contacts',[]),list) else []):
                                    if isinstance(contact,dict) and messages.tel_normalise(str(contact.get('wa_id','')))==sender:
                                        profile=contact.get('profile',{})
                                        if isinstance(profile,dict) and isinstance(profile.get('name'),str): profile_name=profile['name'][:150]
                                payload={'name':profile_name,'email':'','tel':sender,'city':'','message':text,'acknowledge':False,'notice_version':'','origin':'whatsapp_entrant'}
                                con.execute("INSERT INTO intake(kind,payload,source,created) VALUES ('a_qualifier',?,'whatsapp_entrant',?)",(json.dumps(payload),operations.now()))
                                operations.audit(con,'webhook:meta','demande_inconnue_a_qualifier','intake')
                            processed+=1
    return {'ok': True, 'processed': processed}
