"""Parcours métier transactionnels, sauvegardes et callbacks signés (sans réseau)."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import access
import campaigns
import operations
import validation as v
import webapp
import webhooks


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = webapp.DB
        webapp.DB = Path(self.temp.name) / 'work.sqlite3'
        webapp.initialize()

    def tearDown(self):
        webapp.DB = self.old_db
        self.temp.cleanup()

    def execute(self, action, **body):
        return operations.execute(action, body, 'test-admin')

    def opportunity(self, stage='besoin_confirme'):
        return self.execute('opportunity', record_id=1, title='Personnel hôtel', owner='Responsable', next_action='Confirmer les horaires', due=v.today().isoformat(), stage=stage)['id']

    def need(self, opportunity_id=None):
        opp = opportunity_id or self.opportunity()
        item = {'ref': 'EMP-TEST-'+str(opp), 'metier': 'MEN', 'ville': 'Casablanca', 'zone': 'Anfa', 'format': 'permanent', 'statut': 'ouvert', 'source_confirmation': 'Accord client de test', 'date_confirmation': v.today().isoformat(), 'remuneration': {'valeur': '', 'source': ''}, 'horaires': {'valeur': '', 'source': ''}}
        return self.execute('need_from_opportunity', opportunity_id=opp, data=item, confirm=True)['id']

    def candidate(self):
        return self.execute('candidate', name='Candidate de test', city='Casablanca', email='candidate@example.invalid', tel='', skills=['MEN'], languages='Français', available_from=v.today().isoformat(), available_until='2027-12-31', availability_verified=v.today().isoformat(), consent_proof='Demande explicite de traitement de candidature')['id']

    def test_full_commercial_recruitment_path(self):
        opp=self.opportunity(); nid=self.need(opp); cid=self.candidate()
        app=self.execute('application', candidate_id=cid, need_id=nid, stage='accepte')['id']
        mission=self.execute('assignment', application_id=app, start=v.today().isoformat(), end=v.today().isoformat(), agreement='Accord écrit de test')['id']
        self.execute('assignment_update', id=mission, status='en_cours', feedback='Démarrage confirmé', incident='')
        self.execute('assignment_update', id=mission, status='terminee', feedback='Mission réalisée', incident='')
        data=operations.dashboard()
        self.assertEqual(data['assignments'][0]['status'], 'terminee')
        self.assertTrue(data['audit_log'])
        with webapp.connect() as con:
            item=json.loads(con.execute('SELECT payload FROM records WHERE id=?',(nid,)).fetchone()[0])
        self.assertEqual(item['client_id'],1)
        self.assertEqual(item['opportunity_id'],opp)

    def test_need_requires_confirmed_stage(self):
        with self.assertRaises(ValueError): self.need(self.opportunity('prospect'))

    def test_loss_reason_is_required(self):
        with self.assertRaises(ValueError): self.opportunity('perdu')

    def test_missing_dates_and_invalid_urls_rejected(self):
        with self.assertRaises(ValueError): v.day('2026-02-30')
        with self.assertRaises(ValueError): v.url('http-not-a-url')
        with self.assertRaises(ValueError): v.url('https://user:secret@example.invalid')
        item={'ref':'EMP-X','metier':'MEN','ville':'Rabat','zone':'Agdal','format':'permanent','statut':'ouvert','source_confirmation':'Accord réel','date_confirmation':''}
        with self.assertRaises(ValueError): v.record('emploi',item)

    def test_closed_need_can_be_stored_but_is_not_published(self):
        nid=self.need()
        with webapp.connect() as con:
            item=json.loads(con.execute('SELECT payload FROM records WHERE id=?',(nid,)).fetchone()[0])
            item['statut']='ferme'
            v.record('emploi',item)
            con.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(item),nid))
        self.assertEqual(operations.public_jobs(),[])

    def test_double_assignment_is_blocked(self):
        nid=self.need(); cid=self.candidate()
        app=self.execute('application', candidate_id=cid, need_id=nid, stage='accepte')['id']
        values={'application_id':app,'start':v.today().isoformat(),'end':v.today().isoformat(),'agreement':'Accord réel'}
        self.execute('assignment',**values)
        with self.assertRaisesRegex(ValueError,'Double affectation'): self.execute('assignment',**values)

    def test_matching_is_explicable(self):
        nid=self.need();self.candidate()
        match=operations.matches(nid)[0]
        self.assertEqual(match['score'],3)
        self.assertEqual(len(match['reasons']),3)
        self.assertIn('pas une vérification',match['warning'])

    def test_financial_metrics_do_not_conflate_invoicing_and_receipts(self):
        self.execute('ledger',kind='facture',amount=1000,reference='Facture test',day=v.today().isoformat())
        self.execute('ledger',kind='encaissement',amount=400,reference='Reçu test',day=v.today().isoformat())
        self.execute('ledger',kind='cout',amount=100,reference='Coût test',day=v.today().isoformat())
        m=operations.dashboard()['metrics']
        self.assertEqual((m['invoiced'],m['received'],m['cash_contribution']),(1000,400,300))

    def test_proposals_are_versioned(self):
        oid=self.opportunity()
        values={'opportunity_id':oid,'description':'Prestation réelle','amount':500,'source':'Montant confirmé','status':'validee'}
        self.execute('proposal',**values);self.execute('proposal',**values)
        self.assertEqual([p['version'] for p in operations.dashboard()['proposals']],[2,1])

    def test_intake_does_not_authorize_marketing_and_can_convert(self):
        body={'kind':'demande','name':'Client entrant','email':'incoming@example.invalid','tel':'','city':'Rabat','message':'Demande de personnel','acknowledge':True,'source':'publication-test'}
        operations.intake_submit(body)
        self.assertEqual(campaigns.dashboard()['permissions'],[])
        iid=operations.dashboard()['intake'][0]['id']
        result=self.execute('intake_opportunity',intake_id=iid,kind='b2c',besoin='MEN',owner='Équipe',next_action='Rappeler',due=v.today().isoformat())
        self.assertIsNotNone(result['record_id'])
        self.assertEqual(operations.dashboard()['opportunities'][0]['stage'],'conversation')
        with self.assertRaises(ValueError): self.execute('intake_opportunity',intake_id=iid,kind='b2c',besoin='MEN',owner='Équipe',next_action='Rappeler',due=v.today().isoformat())

    def test_candidate_intake_requires_real_open_job(self):
        body={'kind':'candidature','name':'Candidate','email':'applicant@example.invalid','tel':'','city':'Rabat','message':'Je propose ma candidature','acknowledge':True,'need_id':50}
        with self.assertRaises(ValueError): operations.intake_submit(body)
        body['need_id']=self.need()
        self.assertTrue(operations.intake_submit(body)['ok'])

    def test_import_preview_and_atomic_validation(self):
        item={'kind':'b2c','data':{'nom':'Demande publique','besoin':'MEN','ville':'Rabat','zone':'Agdal','niveau':'A','email':'unique@example.invalid','tel':'','source_url':'https://example.invalid/demande','date_consultation':v.today().isoformat()}}
        self.assertFalse(operations.import_records({'items':[item]})['applied'])
        self.assertTrue(operations.import_records({'items':[item],'apply':True})['applied'])
        self.assertFalse(operations.import_records({'items':[item]})['rows'][0]['ok'])
        self.assertEqual(campaigns.dashboard()['permissions'],[])

    def test_backup_is_restorable_and_preserves_secret(self):
        self.opportunity()
        result=operations.backup(webapp.DB,'test')
        path=webapp.DB.parent/'backups'/result['filename']
        with sqlite3.connect(path) as restored,webapp.connect() as original:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(restored.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0],1)
            self.assertEqual(restored.execute("SELECT value FROM settings WHERE key='unsubscribe_secret'").fetchone()[0],original.execute("SELECT value FROM settings WHERE key='unsubscribe_secret'").fetchone()[0])
        self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_restore_command_round_trip(self):
        self.opportunity()
        saved=operations.backup(webapp.DB,'test')
        backup_path=webapp.DB.parent/'backups'/saved['filename']
        self.opportunity('conversation')
        environment=dict(os.environ,YALLAH_DB=str(webapp.DB))
        subprocess.run([sys.executable,'manage.py','restore',str(backup_path),'--confirm'],env=environment,check=True,capture_output=True,text=True)
        with webapp.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0],1)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_accounts_and_roles(self):
        access.add_user('commercial-test','test-password-for-business','commercial')
        header='Basic '+base64.b64encode(b'commercial-test:test-password-for-business').decode()
        self.assertEqual(access.authenticate(header)['role'],'commercial')
        self.assertTrue(access.allow('commercial','opportunity'))
        self.assertFalse(access.allow('commercial','candidate'))
        self.assertFalse(access.allow('lecture','task'))
        self.assertIsNone(access.authenticate('Basic invalid'))
        with webapp.connect() as con:
            row=con.execute('SELECT * FROM users').fetchone()
        self.assertNotIn('test-password',row['digest'])

    def test_production_fails_without_protection(self):
        with patch.dict(os.environ,{'YALLAH_ENV':'production','YALLAH_ADMIN_PASSWORD':'','YALLAH_PUBLIC_URL':'https://example.invalid'}):
            with self.assertRaises(ValueError): access.production_check()

    def test_emergency_stop(self):
        campaigns.emergency_stop(True,'test')
        self.assertTrue(campaigns.health()['emergency_stop'])
        campaigns.emergency_stop(False,'test')
        self.assertFalse(campaigns.health()['emergency_stop'])

    def test_refusal_in_conversation_propagates(self):
        self.execute('conversation',record_id=1,channel='email',direction='entrant',body='Merci de ne plus me contacter',outcome='refus')
        line=next(m for m in webapp.state('Youssef')['messages'] if m['id']==1)
        self.assertEqual(line['statut'],'NON QUALIFIE')

    def test_meta_signature_and_replay_safe_incoming_refusal(self):
        with webapp.connect() as con:
            item=json.loads(con.execute('SELECT payload FROM records WHERE id=1').fetchone()[0])
        sender=campaigns.destination(item,'whatsapp')
        data={'entry':[{'changes':[{'value':{'messages':[{'id':'msg-1','from':sender,'text':{'body':'STOP'}}]}}]}]}
        raw=json.dumps(data).encode()
        with patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'test-secret'}):
            signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
            self.assertEqual(webhooks.receive('meta',raw,{'X-Hub-Signature-256':signature})['processed'],1)
            self.assertEqual(webhooks.receive('meta',raw,{'X-Hub-Signature-256':signature})['processed'],0)
            with self.assertRaises(ValueError): webhooks.receive('meta',raw,{'X-Hub-Signature-256':'bad'})
        self.assertEqual(operations.dashboard()['conversations'][0]['outcome'],'refus')

    def test_unknown_whatsapp_message_is_queued_without_marketing_permission(self):
        data={'entry':[{'changes':[{'value':{'messages':[{'id':'new-msg','from':'212600000001','text':{'body':'Bonjour, je souhaite un échange'}}]}}]}]}
        raw=json.dumps(data).encode()
        with patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'test-secret'}):
            signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
            webhooks.receive('meta',raw,{'X-Hub-Signature-256':signature})
            webhooks.receive('meta',raw,{'X-Hub-Signature-256':signature})
        incoming=operations.dashboard()['intake']
        self.assertEqual(len(incoming),1)
        self.assertEqual(incoming[0]['kind'],'a_qualifier')
        self.assertEqual(campaigns.dashboard()['permissions'],[])
        self.execute('intake_classify',id=incoming[0]['id'],kind='demande')
        self.assertEqual(operations.dashboard()['intake'][0]['kind'],'demande')

    def test_unknown_whatsapp_stop_preserves_refusal_without_creating_lead(self):
        data={'entry':[{'changes':[{'value':{'messages':[{'id':'unknown-stop','from':'212600000002','text':{'body':'STOP'}}]}}]}]}
        raw=json.dumps(data).encode()
        with patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'test-secret'}):
            signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
            webhooks.receive('meta',raw,{'X-Hub-Signature-256':signature})
        self.assertEqual(operations.dashboard()['intake'],[])
        with webapp.connect() as con:
            self.assertTrue(con.execute("SELECT 1 FROM suppressions WHERE contact_key='tel:212600000002'").fetchone())

    def test_resend_signed_callback_replay_and_monotonic_state(self):
        cid=campaigns.create({'name':'Test','channel':'email','signer':'Youssef','ids':[1]})
        did=campaigns.dashboard()['deliveries'][0]['id']
        with webapp.connect() as con:
            con.execute("UPDATE deliveries SET provider_id='email-1',status='accepted' WHERE id=?",(did,))
        raw=json.dumps({'type':'email.delivered','data':{'email_id':'email-1'}}).encode()
        stamp=str(int(time.time()));eid='evt-1';key=b'test-webhook-key'
        signed=eid.encode()+b'.'+stamp.encode()+b'.'+raw
        signature=base64.b64encode(hmac.new(key,signed,hashlib.sha256).digest()).decode()
        headers={'svix-id':eid,'svix-timestamp':stamp,'svix-signature':'v1,'+signature}
        with patch.dict(os.environ,{'RESEND_WEBHOOK_SECRET':'whsec_'+base64.b64encode(key).decode()}):
            self.assertEqual(webhooks.receive('resend',raw,headers)['processed'],1)
            self.assertEqual(webhooks.receive('resend',raw,headers)['processed'],0)
        self.assertEqual(campaigns.dashboard()['deliveries'][0]['status'],'delivered')

    def test_authorization_history_preserves_changes(self):
        base={'id':1,'channel':'email','active':True,'proof':'Accord daté et documenté de test'}
        campaigns.set_permission(base,'test-admin')
        campaigns.set_permission(dict(base,active=False),'test-admin')
        with webapp.connect() as con:
            rows=con.execute('SELECT * FROM authorization_history').fetchall()
        self.assertEqual(len(rows),2)

    def test_state_transitions_do_not_reopen_cancelled_campaigns(self):
        cid=campaigns.create({'name':'Test','channel':'email','signer':'Youssef','ids':[1]})
        campaigns.control({'id':cid,'action':'cancel'})
        with self.assertRaises(ValueError): campaigns.control({'id':cid,'action':'pause'})

    def test_email_ingest_routing_refusal_dedup_and_quoted_text(self):
        with webapp.connect() as con:
            prospect_email=json.loads(con.execute('SELECT payload FROM records WHERE id=1').fetchone()[0])['email']
        res=self.execute('email_ingest',sender_email=prospect_email,sender_name='Direction',subject='Re: Partenariat',body='Bonjour, appelons-nous demain.\n> Si vous souhaitez ne plus me contacter...',message_id='<msg-1@example.test>')
        self.assertEqual(res['classification'],'reponse_prospect')
        dup=self.execute('email_ingest',sender_email=prospect_email,subject='Re: Partenariat',body='Doublon',message_id='<msg-1@example.test>')
        self.assertTrue(dup.get('deduplicated'))
        stop_unknown=self.execute('email_ingest',sender_email='inconnu@example.test',subject='STOP',body='Merci de ne plus me contacter',message_id='<msg-2@example.test>')
        self.assertEqual(stop_unknown['classification'],'refus_inconnu')
        with webapp.connect() as con:
            self.assertTrue(con.execute("SELECT 1 FROM suppressions WHERE contact_key='mail:inconnu@example.test'").fetchone())
        today=v.today().isoformat()
        opp=self.execute('opportunity',record_id=1,title='Serveur extra',stage='besoin_confirme',owner='Youssef',next_action='Publier',due=today)
        need=self.execute('need_from_opportunity',opportunity_id=opp['id'],confirm=True,data={'ref':'EMP-100','metier':'SRV','ville':'Casablanca','zone':'Anfa','format':'renfort journalier','statut':'ouvert','source_confirmation':'Direction email','date_confirmation':today,'remuneration':{'valeur':'','source':''},'horaires':{'valeur':'','source':''}})
        cand_mail=self.execute('email_ingest',sender_email='candidat1@example.test',sender_name='Karim',subject='Candidature EMP-100',body='Bonjour, voici ma candidature pour EMP-100.')
        self.assertEqual(cand_mail['classification'],'candidature')
        self.assertEqual(cand_mail['need_id'],need['id'])
        unk_mail=self.execute('email_ingest',sender_email='famille@example.test',sender_name='Famille',subject='Question garde enfants',body='Bonjour, cherchez-vous sur Rabat ?')
        self.assertEqual(unk_mail['classification'],'a_qualifier')
        self.assertEqual(campaigns.dashboard()['permissions'],[])
        stop_known=self.execute('email_ingest',sender_email=prospect_email,subject='Désinscription',body='Veuillez me désinscrire.')
        self.assertEqual(stop_known['classification'],'refus')

    def test_csv_import_preview_and_atomic_apply(self):
        today=v.today().isoformat()
        bad_csv='nom,ville,zone,tel,email,source_url,date_consultation,niveau,segment,phase\nHotel CSV,Casablanca,Anfa,+212 699 00 11 22,,https://example.invalid/h1,'+today+',A,hotel,abc\n'
        preview_bad=operations.import_records({'kind':'b2b','csv':bad_csv,'apply':False})
        self.assertFalse(preview_bad['rows'][0]['ok'])
        good_csv='nom,ville,zone,tel,email,source_url,date_consultation,niveau,segment,phase\nHotel CSV,Casablanca,Anfa,+212 699 00 11 22,contact@hotelcsv.invalid,https://example.invalid/h1,'+today+',A,hotel,1\n'
        preview_ok=operations.import_records({'kind':'b2b','csv':good_csv,'apply':False})
        self.assertTrue(preview_ok['rows'][0]['ok'])
        applied=operations.import_records({'kind':'b2b','csv':good_csv,'apply':True})
        self.assertTrue(applied['applied'])
        self.assertEqual(campaigns.dashboard()['permissions'],[])

    def test_export_json_merges_suppressions_and_guards_overwrite(self):
        self.execute('conversation',record_id=1,channel='email',direction='entrant',body='STOP',outcome='refus')
        with tempfile.TemporaryDirectory() as out_dir:
            res=operations.export_json(out_dir,overwrite=False,actor='test')
            self.assertEqual(res['files']['prospects_b2b.json'],48)
            exported=json.loads((Path(out_dir)/'prospects_b2b.json').read_text(encoding='utf-8'))
            self.assertTrue(len(exported['meta']['refus'])>=1)
            with self.assertRaises(ValueError):
                operations.export_json(out_dir,overwrite=False,actor='test')
            res2=operations.export_json(out_dir,overwrite=True,actor='test')
            self.assertEqual(res2['files']['prospects_b2b.json'],48)

    def test_j7_followup_eligibility(self):
        today=v.today().isoformat()
        with webapp.connect() as con:
            con.execute("INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (1,'whatsapp','sortant','Premier contact','note','2026-10-10T09:00:00+00:00')")
            con.execute("INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (2,'whatsapp','sortant','Contact récent','note',?)",(today+'T09:00:00+00:00',))
        fups=operations.dashboard()['followups']
        self.assertEqual([f['record_id'] for f in fups],[1])
        self.assertEqual(fups[0]['followup_step'],1)
        self.assertEqual(fups[0]['followup_label'],'J+3')
        self.execute('conversation',record_id=1,channel='whatsapp',direction='entrant',body='Merci, rappelons-nous',outcome='reponse')
        self.assertEqual(operations.dashboard()['followups'],[])

    def test_inbound_reply_auto_advances_cancels_j7_and_detects_metiers(self):
        with webapp.connect() as con:
            out=operations.enregistrer_envoi_manuel(con,1,'email','Premier email envoyé','Service Commercial')
        oid=out['opportunity_id']
        self.assertEqual(out['next_relance'],'Relance J+3')
        dash1=operations.dashboard()
        self.assertEqual(next(o for o in dash1['opportunities'] if o['id']==oid)['stage'],'qualifie')
        self.assertTrue(any(t['opportunity_id']==oid and t['status']=='a_faire' and t['title'].startswith('Relance J+3') for t in dash1['tasks']))

        rep=self.execute('conversation',record_id=1,channel='email',direction='entrant',body='Bonjour, nous cherchons 2 serveurs extra pour un banquet samedi et un plongeur.',outcome='reponse')
        self.assertIn('SRV',rep['suggested_metiers'])
        self.assertIn('PLG',rep['suggested_metiers'])
        dash2=operations.dashboard()
        opp=next(o for o in dash2['opportunities'] if o['id']==oid)
        self.assertEqual(opp['stage'],'conversation')
        self.assertEqual(opp['due'],v.today().isoformat())
        self.assertTrue(all(t['status']=='annulee' for t in dash2['tasks'] if t['opportunity_id']==oid and t['title'].startswith('Relance J+')))
        self.assertTrue(any(t['opportunity_id']==oid and t['status']=='a_faire' and t['title'].startswith('Réponse reçue') for t in dash2['tasks']))

    def test_qualify_need_10min_creates_publishable_job_and_matches(self):
        cid=self.candidate()
        res=self.execute(
            'qualify_need',
            record_id=1,
            metier='MEN',
            format='permanent',
            postes=2,
            ville='Casablanca',
            zone='Anfa',
            horaires='08h30 - 16h30 du lundi au samedi',
            horaires_source='Appel découverte Direction RH du '+v.today().isoformat(),
            source_confirmation='Confirmé par téléphone avec la gouvernante générale le '+v.today().isoformat(),
            confirm=True,
        )
        self.assertTrue(res['ref'].startswith('EMP-'))
        self.assertTrue(any(m['candidate_id']==cid for m in res['matches']))
        dash=operations.dashboard()
        opp=next(o for o in dash['opportunities'] if o['id']==res['opportunity_id'])
        self.assertEqual(opp['stage'],'besoin_confirme')
        self.assertTrue(any(j['id']==res['id'] for j in operations.public_jobs()))

    def test_b2c_reference_decoding_in_intake_webhook_and_email_ingest(self):
        sub=operations.intake_submit({
            'kind':'demande',
            'name':'Famille Alami',
            'email':'',
            'tel':'+212 661 88 77 66',
            'city':'',
            'message':'Bonjour, réf CAS-ANF-MEN, nous cherchons une aide-ménagère régulière.',
            'acknowledge':True,
        })
        self.assertTrue(sub['ok'])
        inc=operations.dashboard()['intake'][0]
        self.assertEqual(inc['b2c_decoded']['ref'],'CAS-ANF-MEN')
        self.assertIn('https://wa.me/212661887766?text=',inc['qualification_whatsapp'])
        conv=self.execute('intake_opportunity',intake_id=inc['id'],owner='Service Commercial',next_action='Appeler en 10 min',due=v.today().isoformat())
        with webapp.connect() as con:
            created_b2c=json.loads(con.execute('SELECT payload FROM records WHERE id=?',(conv['record_id'],)).fetchone()[0])
        self.assertEqual(created_b2c['ville'],'Casablanca')
        self.assertIn('Anfa',created_b2c['zone'])
        self.assertEqual(created_b2c['besoin'],'MEN')
        self.assertEqual(campaigns.dashboard()['permissions'],[])

        # Même décodage via webhook WhatsApp Meta entrant.
        data={'entry':[{'changes':[{'value':{'messages':[{'id':'wa-b2c-1','from':'212677112233','text':{'body':'Salam, réf BSK-VVE-NOU svp'}}]}}]}]}
        raw=json.dumps(data).encode()
        with patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'test-secret'}):
            sig='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
            webhooks.receive('meta',raw,{'X-Hub-Signature-256':sig})
        wa_inc=operations.dashboard()['intake'][0]
        self.assertEqual(wa_inc['kind'],'demande')
        self.assertEqual(wa_inc['b2c_decoded']['ref'],'BSK-VVE-NOU')

    def test_multi_criteria_matching_commuter_basin_and_anonymized_sheet(self):
        today=v.today().isoformat()
        # Besoin à Bouskoura avec langue souhaitée Français.
        res=self.execute(
            'qualify_need',
            record_id=1,
            metier='MEN',
            format='permanent',
            ville='Bouskoura',
            zone='Ville Verte',
            langues='Français',
            source_confirmation='Validation écrite direction du '+today,
            confirm=True,
        )
        c1=self.execute('candidate',name='Khadija El Mansouri',email='',tel='+212661009988',city='Casablanca',skills=['MEN'],languages='Arabe, Français',available_from=today,available_until='2026-12-31',availability_verified=today,consent_proof='Accord écrit C1')['id']
        m_list=operations.matches(res['id'])
        m1=next(m for m in m_list if m['candidate_id']==c1)
        self.assertEqual(m1['anonymized_name'],'Khadija M.')
        self.assertGreaterEqual(m1['score'],3)
        self.assertTrue(any('Bassin géographique proche' in r for r in m1['reasons']))
        self.assertIn('Langue déclarée compatible',m1['reasons'])

        sheet=operations.fiche_presentation_candidat(c1,res['id'],'fr')
        self.assertIn('Khadija M.',sheet['presentation'])
        self.assertNotIn('Mansouri',sheet['presentation'])
        self.assertNotIn('661009988',sheet['presentation'])
        self.assertIn('art. 480',sheet['presentation'])
        self.assertIn('https://yallahservices-one.vercel.app',sheet['presentation'])

    def test_email_bounce_invalidates_email_and_triggers_whatsapp_fallback(self):
        today=v.today().isoformat()
        imp=operations.import_records({'kind':'b2b','items':[{'kind':'b2b','data':{
            'nom':'Traiteur Bounce Test','segment':'evenementiel','phase':1,'ville':'Casablanca','zone':'Maarif',
            'tel':'+212 664 55 44 33','email':'contact-mort@traiteurbounce.invalid',
            'source_url':'https://traiteurbounce.invalid/contact','date_consultation':today,'niveau':'A',
        }}],'apply':True})
        self.assertTrue(imp['applied'])
        with webapp.connect() as con:
            rid=con.execute("SELECT id FROM records WHERE kind='b2b' ORDER BY id DESC LIMIT 1").fetchone()[0]
            operations.enregistrer_envoi_manuel(con,rid,'email','Envoi initial email','Service Commercial')
        bounce=self.execute(
            'email_ingest',
            sender_email='mailer-daemon@googlemail.com',
            subject='Delivery Status Notification (Failure)',
            body='Address not found: Your message was not delivered to contact-mort@traiteurbounce.invalid because the domain does not exist.',
            message_id='<dsn-bounce-1@example.test>',
        )
        self.assertEqual(bounce['classification'],'rebond_email')
        self.assertEqual(bounce['bounced'][0]['fallback_channel'],'whatsapp')
        with webapp.connect() as con:
            updated=json.loads(con.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0])
        self.assertEqual(updated['email'],'')
        self.assertEqual(updated['email_invalide'],'contact-mort@traiteurbounce.invalid')
        dash=operations.dashboard()
        self.assertTrue(any(t['status']=='a_faire' and 'Rebond email' in t['title'] for t in dash['tasks']))
        self.assertEqual(dash['funnel']['by_channel']['email']['bounced'],1)

