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
