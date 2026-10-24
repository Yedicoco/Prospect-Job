import base64
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import access
import operations
import validation
import webapp


class OperationsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=webapp.DB
        webapp.DB=Path(self.temp.name)/'http.sqlite3';webapp.initialize()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),webapp.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        webapp._intake_hits.clear()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();webapp.DB=self.old;self.temp.cleanup()

    def request(self,path,body=None,login=None):
        headers={'X-Yallah-Token':webapp.TOKEN,'Content-Type':'application/json'}
        if login: headers['Authorization']='Basic '+base64.b64encode(login.encode()).decode()
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urlopen(req) as r: return r.status,r.read()

    def test_opportunity_api_and_audit_actor(self):
        _,raw=self.request('/api/operations',{'action':'opportunity','record_id':1,'title':'Test HTTP','stage':'prospect','owner':'Équipe','next_action':'Appeler','due':validation.today().isoformat()})
        self.assertTrue(json.loads(raw)['id'])
        _,raw=self.request('/api/operations');data=json.loads(raw)
        self.assertEqual(data['opportunities'][0]['title'],'Test HTTP')
        self.assertEqual(data['audit_log'][0]['actor'],'local')

    def test_staff_roles_reject_campaign_and_candidate_writes(self):
        access.add_user('sales','test-password-commercial','commercial')
        for path,body in [('/api/campaigns/stop',{'stop':True}),('/api/operations',{'action':'candidate'})]:
            with self.assertRaises(HTTPError) as ctx: self.request(path,body,'sales:test-password-commercial')
            self.assertEqual(ctx.exception.code,403)

    def test_readonly_role_cannot_update_tasks(self):
        access.add_user('read','test-password-readonly','lecture')
        with self.assertRaises(HTTPError) as ctx: self.request('/api/operations',{'action':'task'},'read:test-password-readonly')
        self.assertEqual(ctx.exception.code,403)

    def test_public_forms_remain_public_and_intake_is_rate_limited(self):
        with patch.dict(os.environ,{'YALLAH_ADMIN_PASSWORD':'test-admin-password-protected'}):
            self.assertEqual(self.request('/demande')[0],200)
            self.assertEqual(self.request('/candidature')[0],200)
            body={'kind':'demande','name':'Client','email':'test@example.invalid','tel':'','city':'Rabat','message':'Un besoin à étudier','acknowledge':True}
            self.assertTrue(json.loads(self.request('/api/public/intake',body)[1])['ok'])
            # Aucun consentement marketing n'est créé.
            with webapp.connect() as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM permissions').fetchone()[0],0)
            webapp._intake_hits['127.0.0.1']=(webapp.time.monotonic(),10)
            with self.assertRaises(HTTPError) as ctx: self.request('/api/public/intake',body)
            self.assertEqual(ctx.exception.code,429)

    def test_invalid_confirmation_date_rejected_by_save_api(self):
        item={'ref':'EMP-HTTP','metier':'MEN','ville':'Rabat','zone':'Agdal','format':'permanent','statut':'ouvert','source_confirmation':'Confirmation de test','date_confirmation':''}
        with self.assertRaises(HTTPError) as ctx: self.request('/api/save',{'kind':'emploi','data':item})
        self.assertEqual(ctx.exception.code,400)

    def test_backup_route_and_private_files(self):
        self.assertEqual(json.loads(self.request('/api/backup',{})[1])['integrity'],'ok')
        with self.assertRaises(HTTPError) as ctx: self.request('/data/http.sqlite3')
        self.assertEqual(ctx.exception.code,404)

    def test_invalid_webhook_signature_has_no_effect(self):
        with self.assertRaises(HTTPError) as ctx: self.request('/webhooks/meta',{'entry':[]})
        self.assertEqual(ctx.exception.code,400)
        self.assertEqual(operations.dashboard()['conversations'],[])

    def test_manual_send_pipeline_j7_cap_daily_quota_and_presentation_rbac(self):
        # 1er envoi manuel -> opportunité 'qualifie' + tâche 'Relance J+3' + quota = 1/15
        self.request('/api/action',{'id':1,'action':'Contact envoyé manuellement','channel':'email'})
        st=json.loads(self.request('/api/state?prenom=Youssef&langue=fr')[1])
        self.assertEqual(st['daily_quota']['used'],1)
        self.assertEqual(st['daily_quota']['remaining'],14)

        # Relances graduées J+3, J+7, J+14 (total = 4 envois manuels max) ; 5e envoi -> bloqué (400)
        self.request('/api/action',{'id':1,'action':'Contact envoyé manuellement','channel':'whatsapp'})
        self.request('/api/action',{'id':1,'action':'Contact envoyé manuellement','channel':'whatsapp'})
        self.request('/api/action',{'id':1,'action':'Contact envoyé manuellement','channel':'whatsapp'})
        with self.assertRaises(HTTPError) as ctx5:
            self.request('/api/action',{'id':1,'action':'Contact envoyé manuellement','channel':'whatsapp'})
        self.assertEqual(ctx5.exception.code,400)

        # Plafond quotidien de 15 contacts distincts par jour
        for rid in range(2,16):
            self.request('/api/action',{'id':rid,'action':'Contact envoyé manuellement','channel':'email'})
        st_full=json.loads(self.request('/api/state?prenom=Youssef&langue=fr')[1])
        self.assertEqual(st_full['daily_quota']['used'],15)
        self.assertEqual(st_full['daily_quota']['remaining'],0)
        with self.assertRaises(HTTPError) as ctx16:
            self.request('/api/action',{'id':16,'action':'Contact envoyé manuellement','channel':'email'})
        self.assertEqual(ctx16.exception.code,400)

        # Qualification 10 min autorisée au rôle commercial ; /api/presentation réservé à recrutement / admin
        today=validation.today().isoformat()
        cand=json.loads(self.request('/api/operations',{
            'action':'candidate','name':'Fatima Zahra Alaoui','email':'','tel':'+212662112233',
            'city':'Casablanca','skills':['SRV'],'languages':'Français, Arabe',
            'available_from':today,'available_until':'2026-12-31','availability_verified':today,
            'consent_proof':'Accord écrit candidat',
        })[1])
        access.add_user('sales','test-password-commercial','commercial')
        access.add_user('recruiter','test-password-recrutement','recrutement')
        with patch.dict(os.environ,{'YALLAH_ADMIN_PASSWORD':'test-admin-password-protected'}):
            qn=json.loads(self.request('/api/operations',{
                'action':'qualify_need','record_id':1,'metier':'SRV','format':'renfort journalier',
                'postes':2,'source_confirmation':'Email direction banquet du '+today,'confirm':True,
            },'sales:test-password-commercial')[1])
            with self.assertRaises(HTTPError) as ctx_forb:
                self.request(f"/api/presentation?candidate_id={cand['id']}&need_id={qn['id']}&langue=fr",login='sales:test-password-commercial')
            self.assertEqual(ctx_forb.exception.code,403)
            pres=json.loads(self.request(f"/api/presentation?candidate_id={cand['id']}&need_id={qn['id']}&langue=fr",login='recruiter:test-password-recrutement')[1])
            self.assertEqual(pres['anonymized_name'],'Fatima A.')
            self.assertNotIn('Alaoui',pres['presentation'])
            self.assertNotIn('662112233',pres['presentation'])

