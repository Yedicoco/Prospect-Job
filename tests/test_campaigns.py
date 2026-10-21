"""Tests d'automatisation avec fournisseurs simulés : aucun réseau externe."""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import campaigns
import webapp


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = webapp.DB
        webapp.DB = Path(self.tmp.name) / 'campaigns.sqlite3'
        self.env = patch.dict(os.environ, {
            'YALLAH_ENABLE_LIVE': '1', 'YALLAH_ADMIN_PASSWORD': 'test-password-not-a-real-secret',
            'YALLAH_PUBLIC_URL': 'https://example.invalid', 'RESEND_API_KEY': 'test-key',
            'YALLAH_FROM_EMAIL': 'Yallah <test@example.invalid>', 'WHATSAPP_ACCESS_TOKEN': 'test-token',
            'WHATSAPP_PHONE_NUMBER_ID': '12345', 'WHATSAPP_TEMPLATE_NAME': 'approved_example',
            'WHATSAPP_TEMPLATE_LANGUAGE': 'fr', 'WHATSAPP_TEMPLATE_REVIEWED': '1',
        })
        self.env.start()
        webapp.initialize()
        with webapp.connect() as con:
            item = json.loads(con.execute('SELECT payload FROM records WHERE id=1').fetchone()[0])
            item['date_consultation'] = item['date_derniere_verification'] = date.today().isoformat()
            con.execute('UPDATE records SET payload=? WHERE id=1', (json.dumps(item),))

    def tearDown(self):
        self.env.stop()
        webapp.DB = self.old_db
        self.tmp.cleanup()

    def permission(self, channel='email'):
        campaigns.set_permission({'id': 1, 'channel': channel, 'active': True,
                                  'proof': 'Preuve de test : accord documenté au canal et date.'})

    def create(self, channel='email', ids=None):
        return campaigns.create({'name': 'Campagne test', 'channel': channel, 'signer': 'Youssef',
                                 'language': 'fr', 'ids': ids or [1]})

    def activate(self, cid):
        campaigns.control({'id': cid, 'action': 'activate', 'confirm': True,
                           'legal_proof': 'Référence datée de validation pour ce périmètre de test.'})

    def delivery(self, cid):
        return next(d for d in campaigns.dashboard()['deliveries'] if d['campaign_id'] == cid)

    def test_simulation_never_sends_and_flags_missing_permission(self):
        with patch('campaigns.transport') as transport:
            cid = self.create()
            campaigns.tick()
            self.assertEqual(self.delivery(cid)['status'], 'blocked')
            self.assertIn('Autorisation', self.delivery(cid)['reason'])
            transport.assert_not_called()

    def test_simulated_qualified_campaign_stays_offline(self):
        self.permission()
        cid = self.create()
        self.assertEqual(self.delivery(cid)['status'], 'simulated')
        with patch('campaigns.transport') as transport:
            campaigns.tick()
            transport.assert_not_called()

    def test_activation_requires_server_configuration_and_confirmation(self):
        self.permission()
        cid = self.create()
        with patch.dict(os.environ, {'YALLAH_ENABLE_LIVE': '0'}):
            with self.assertRaises(ValueError):
                self.activate(cid)
        with self.assertRaises(ValueError):
            campaigns.control({'id': cid, 'action': 'activate', 'legal_proof': 'validation suffisamment longue', 'confirm': False})
        self.assertEqual(self.delivery(cid)['status'], 'simulated')

    def test_worker_sends_once_and_marks_provider_acceptance(self):
        self.permission()
        cid = self.create()
        self.activate(cid)
        with patch('campaigns.transport', return_value='provider-test-id') as transport:
            campaigns.tick()
            campaigns.tick()
            transport.assert_called_once()
        self.assertEqual(self.delivery(cid)['status'], 'accepted')
        self.assertIn('non confirmée', self.delivery(cid)['reason'])

    def test_revocation_is_checked_at_send_time(self):
        self.permission()
        cid = self.create()
        self.activate(cid)
        campaigns.set_permission({'id': 1, 'channel': 'email', 'active': False})
        with patch('campaigns.transport') as transport:
            campaigns.tick()
            transport.assert_not_called()
        self.assertEqual(self.delivery(cid)['status'], 'blocked')

    def test_unknown_network_outcome_is_not_retried(self):
        self.permission()
        cid = self.create()
        self.activate(cid)
        with patch('campaigns.transport', side_effect=TimeoutError) as transport:
            campaigns.tick()
            campaigns.tick()
            transport.assert_called_once()
        self.assertEqual(self.delivery(cid)['status'], 'unknown')

    def test_pause_and_cancel(self):
        self.permission()
        cid = self.create()
        self.activate(cid)
        campaigns.control({'id': cid, 'action': 'pause'})
        with patch('campaigns.transport') as transport:
            campaigns.tick()
            transport.assert_not_called()
        campaigns.control({'id': cid, 'action': 'cancel'})
        self.assertEqual(self.delivery(cid)['status'], 'cancelled')
        with self.assertRaises(ValueError):
            self.activate(cid)

    def test_signed_unsubscribe_get_is_read_only_and_post_suppresses(self):
        self.permission()
        self.permission('whatsapp')
        cid = self.create()
        delivery = self.delivery(cid)
        args = parse_qs(urlparse(campaigns.unsubscribe_url(delivery['id'])).query)
        campaigns.unsubscribe(args['id'][0], args['token'][0])
        self.assertTrue(any(p['active'] for p in campaigns.dashboard()['permissions']))
        campaigns.unsubscribe(args['id'][0], args['token'][0], apply=True)
        self.assertFalse(any(p['active'] for p in campaigns.dashboard()['permissions']))
        self.assertEqual(next(m for m in webapp.state('Youssef')['messages'] if m['id'] == 1)['statut'], 'NON QUALIFIE')
        with self.assertRaises(ValueError):
            campaigns.unsubscribe(delivery['id'], 'bad-token', apply=True)
        with self.assertRaises(ValueError):
            self.permission()

    def test_permission_is_bound_to_destination(self):
        self.permission()
        with webapp.connect() as con:
            item = json.loads(con.execute('SELECT payload FROM records WHERE id=1').fetchone()[0])
            item['email'] = 'different@example.invalid'
            con.execute('UPDATE records SET payload=? WHERE id=1', (json.dumps(item),))
        self.assertEqual(self.delivery(self.create())['status'], 'blocked')

    def test_sources_rechecked_before_send(self):
        self.permission()
        cid = self.create()
        self.activate(cid)
        with webapp.connect() as con:
            item = json.loads(con.execute('SELECT payload FROM records WHERE id=1').fetchone()[0])
            item['date_derniere_verification'] = (date.today() - timedelta(days=1)).isoformat()
            con.execute('UPDATE records SET payload=? WHERE id=1', (json.dumps(item),))
        with patch('campaigns.transport') as transport:
            campaigns.tick()
            transport.assert_not_called()
        self.assertEqual(self.delivery(cid)['status'], 'blocked')

    def test_restart_does_not_retry_in_flight_delivery(self):
        self.permission()
        cid = self.create()
        with webapp.connect() as con:
            con.execute("UPDATE deliveries SET status='sending', attempted_at=?", (campaigns.now(),))
        campaigns.configure(webapp.connect, webapp.state)
        self.assertEqual(self.delivery(cid)['status'], 'unknown')

    def test_daily_limit(self):
        self.permission()
        cid = self.create()
        self.activate(cid)
        with patch('campaigns.MAX_DAILY', 0), patch('campaigns.transport') as transport:
            campaigns.tick()
            transport.assert_not_called()
        self.assertEqual(self.delivery(cid)['status'], 'queued')

    def test_email_transport_payload(self):
        self.permission()
        cid = self.create()
        with patch('campaigns.send_http', return_value={'id': 'email-id'}) as send:
            result = campaigns.transport(self.delivery(cid), {'channel': 'email'})
        self.assertEqual(result, 'email-id')
        args = send.call_args.args
        self.assertEqual(args[0], 'https://api.resend.com/emails')
        self.assertIn('/unsubscribe?', args[2]['text'])
        self.assertIn('Idempotency-Key', args[3])

    def test_whatsapp_transport_uses_template(self):
        self.permission('whatsapp')
        cid = self.create('whatsapp')
        with patch('campaigns.send_http', return_value={'messages': [{'id': 'wa-id'}]}) as send:
            campaigns.transport(self.delivery(cid), {'channel': 'whatsapp'})
        payload = send.call_args.args[2]
        self.assertEqual(payload['type'], 'template')
        self.assertEqual(payload['template']['name'], 'approved_example')
        self.assertIn('/unsubscribe?', payload['template']['components'][0]['parameters'][0]['text'])

    def test_cross_campaign_duplicate_is_not_resent(self):
        self.permission()
        first, second = self.create(), self.create()
        self.activate(first)
        self.activate(second)
        with patch('campaigns.MIN_INTERVAL', 0), patch('campaigns.transport', return_value='id') as send:
            campaigns.tick()
            campaigns.tick()
            send.assert_called_once()
        self.assertEqual(self.delivery(second)['status'], 'blocked')
