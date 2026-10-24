import base64
import os
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import campaigns
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import webapp


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.old_db = webapp.DB
        webapp.DB = Path(cls.temp.name) / 'test.sqlite3'
        webapp.initialize()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), webapp.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        webapp.DB = cls.old_db
        cls.temp.cleanup()

    def request(self, path, body=None, token=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Yallah-Token'] = webapp.TOKEN
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urlopen(req) as response:
            return json.load(response)

    def test_basic_authentication_protects_api(self):
        with patch.dict(os.environ, {'YALLAH_ADMIN_PASSWORD': 'test-password-for-http-auth'}):
            with self.assertRaises(HTTPError) as ctx:
                self.request('/api/state')
            self.assertEqual(ctx.exception.code, 401)
            credentials = base64.b64encode(b'admin:test-password-for-http-auth').decode()
            request = Request(self.base + '/api/state', headers={'Authorization': 'Basic ' + credentials})
            with urlopen(request) as response:
                self.assertTrue(json.load(response)['records'])

    def test_campaign_http_simulation(self):
        result = self.request('/api/campaigns/create', {
            'name': 'HTTP simulation', 'channel': 'email', 'signer': 'Youssef', 'ids': [2]})
        result = next(d for d in self.request('/api/campaigns')['deliveries'] if d['campaign_id'] == result['id'])
        self.assertEqual(result['status'], 'blocked')
        self.assertIsNone(result['attempted_at'])

    def test_public_unsubscribe_flow_with_auth_enabled(self):
        cid = campaigns.create({'name': 'Public unsubscribe', 'channel': 'email', 'signer': 'Youssef', 'ids': [3]})
        delivery = next(d for d in campaigns.dashboard()['deliveries'] if d['campaign_id'] == cid)
        args = urlparse(campaigns.unsubscribe_url(delivery['id'])).query
        with patch.dict(os.environ, {'YALLAH_ADMIN_PASSWORD': 'test-password-for-http-auth'}):
            with urlopen(self.base + '/unsubscribe?' + args) as response:
                self.assertIn('Confirmer'.encode(), response.read())
            with webapp.connect() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM suppressions').fetchone()[0], 0)
            request = Request(self.base + '/unsubscribe', data=args.encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
            with urlopen(request) as response:
                self.assertIn('enregistrée'.encode(), response.read())
            with webapp.connect() as con:
                self.assertGreater(con.execute('SELECT COUNT(*) FROM suppressions').fetchone()[0], 0)

    def test_seed_and_messages(self):
        data = self.request('/api/state?prenom=Youssef')
        self.assertEqual(len(data['messages']), 49)
        self.assertEqual(len(data['annonces']), 1)
        self.assertEqual(data['annonces'][0]['publiable'], 'non')
        for m in data['messages']:
            if m['statut'] != 'PRET - envoi manuel':
                self.assertFalse(m['lien_whatsapp'])
                self.assertFalse(m['lien_email'])

    def test_write_requires_token(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request('/api/action', {'id': 1, 'action': 'Note'}, token=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_verify_history_and_refusal(self):
        self.request('/api/action', {'id': 1, 'action': 'Vérifié aujourd’hui'})
        data = self.request('/api/state?prenom=Youssef')
        self.assertEqual(next(m for m in data['messages'] if m['id'] == 1)['statut'], 'PRET - envoi manuel')
        self.request('/api/action', {'id': 1, 'action': 'Ne plus contacter'})
        data = self.request('/api/state?prenom=Youssef')
        row = next(m for m in data['messages'] if m['id'] == 1)
        self.assertEqual(row['statut'], 'NON QUALIFIE')
        self.assertFalse(row['lien_whatsapp'])
        self.assertTrue(data['events'])

    def test_invalid_record(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request('/api/save', {'kind': 'b2b', 'data': {}})
        self.assertEqual(ctx.exception.code, 400)

    def test_seed_is_not_duplicated(self):
        webapp.initialize()
        self.assertEqual(len(self.request('/api/state')['records']), 50)

    def test_unknown_route(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request('/prospects_b2b.json')
        self.assertEqual(ctx.exception.code, 404)

    def test_site_web_and_client_followup_messages(self):
        self.request('/api/action', {'id': 2, 'action': 'Vérifié aujourd’hui'})
        opp = self.request('/api/operations', {
            'action': 'opportunity',
            'record_id': 2,
            'title': 'Renfort banquet',
            'stage': 'conversation',
            'owner': 'Youssef',
            'next_action': 'Point telephonique',
            'due': webapp.validation.today().isoformat(),
        })
        data = self.request('/api/state?prenom=Youssef&langue=fr')
        self.assertEqual(data['site_web'], 'https://yallahservices-one.vercel.app')
        row = next(m for m in data['messages'] if m['id'] == 2)
        self.assertIn('https://yallahservices-one.vercel.app', row['_brut'])
        fu = data['client_followups'][str(opp['id'])]
        self.assertTrue(fu['pret'])
        self.assertIn('https://yallahservices-one.vercel.app', fu['message'])
        self.assertTrue(fu['lien_whatsapp'] or fu['lien_email'])

        self.request('/api/action', {'id': 2, 'action': 'Ne plus contacter'})
        after_refusal = self.request('/api/state?prenom=Youssef&langue=fr')['client_followups'][str(opp['id'])]
        self.assertTrue(after_refusal['refuse'])
        self.assertFalse(after_refusal['pret'])
        self.assertEqual(after_refusal['lien_whatsapp'], '')
        self.assertEqual(after_refusal['lien_email'], '')

