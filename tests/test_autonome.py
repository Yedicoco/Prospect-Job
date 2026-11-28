"""Tests complets du moteur d'acquisition autonome, conformité Loi 09-08, scoring, digest, Auto-pilot & RBAC."""
import base64
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import access
import webapp
import yallah_analyzer as analyzer
import yallah_autonome as autonome
import yallah_connectors as connectors


def _auth_header(username: str, password: str) -> str:
    raw = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return 'Basic ' + raw


class AnalyzerAndScoringTests(unittest.TestCase):
    def test_analyse_multilingue_exemples_prompt_sans_invention(self):
        cases = [
            ('Bonjour, je cherche une femme de ménage à Anfa 3 fois par semaine.', ('menage',), 'hebdomadaire', 'Anfa', 'fr'),
            ('Salam bghit mrabia l benti f Maarif men lundi tal vendredi.', ('garde_enfants',), 'temps_plein', 'Maârif', 'darija'),
            ('Je cherche une cuisinière à domicile à Californie Casablanca.', ('cuisine',), '', 'Californie', 'fr'),
            ('Besoin urgent d’une aide à domicile pour ma mère à Bouskoura.', ('aide_domicile',), '', 'Bouskoura', 'fr'),
            ('السلام عليكم، كنقلب على مساعدة منزلية للطبخ والتنظيف فكاليفورنيا.', ('cuisine', 'menage'), '', 'Californie', 'arabe'),
            ('Bonjour, quels sont vos services ?', ('autre',), '', '', 'fr'),
            ('Je veux quelqu’un pour la maison.', ('autre', 'personnel_maison', 'menage'), '', '', 'fr'),
        ]
        for msg, exp_besoins, exp_freq, exp_quartier, exp_lang in cases:
            with self.subTest(msg=msg):
                res = analyzer.analyser_demande_b2c(msg)
                self.assertIn(res['type_prestation'], exp_besoins)
                self.assertEqual(res['frequence'], exp_freq)
                self.assertEqual(res['quartier'], exp_quartier)
                self.assertEqual(res['langue_preferee'], exp_lang)
                # Aucune donnée inventée si absente du texte
                self.assertEqual(res['budget_indicatif'], '')
                self.assertEqual(res['date_souhaitee'], '')
                if 'urgent' not in msg.lower():
                    self.assertEqual(res['urgence'], '')

    def test_detection_stop_tous_mots_cles(self):
        for txt in (
            'STOP', 'stop sms', 'Merci de faire une désinscription',
            'Veuillez ne plus me contacter svp', 'Retirez-moi de votre liste',
            'Arrêtez vos messages', 'إلغاء الاشتراك', 'Unsubscribe',
        ):
            with self.subTest(txt=txt):
                est_stop, kw = analyzer.detecter_stop(txt)
                self.assertTrue(est_stop)
                self.assertTrue(bool(kw))
        self.assertEqual(analyzer.detecter_stop('Bonjour je suis intéressé pour demain'), (False, ''))

    def test_generation_messages_et_garde_fou_anti_invention(self):
        analyse = analyzer.analyser_demande_b2c('Bonjour, je cherche une femme de ménage à Anfa 3 fois par semaine.')
        demande = {'nom': 'Nadia', 'ville': 'Casablanca', 'quartier': 'Anfa'}
        for lang in ('fr', 'darija', 'arabe'):
            corps = analyzer.generer_message_famille(demande, analyse, lang)
            alertes = analyzer.verifier_message_autonome(corps)
            self.assertEqual(alertes, [], f'Alertes inattendues en {lang}: {alertes}')
            self.assertIn('STOP', corps.upper())
            # Max 4 questions courtes
            self.assertLessEqual(corps.count('?') + corps.count('؟'), 4)

        pro_corps = analyzer.generer_message_pro({
            'nom_entreprise': 'Hôtel Corniche', 'type_etablissement': 'hotel', 'ville': 'Casablanca',
            'besoin_probable': 'renfort en personnel de ménage et service',
        }, 'fr')
        self.assertEqual(analyzer.verifier_message_autonome(pro_corps), [])
        self.assertIn('STOP', pro_corps.upper())

        # Le garde-fou bloque les prix, garanties, délais inventés et faux numéros
        bad = analyzer.verifier_message_autonome('Tarif 3000 MAD garanti 100%, disponible sous 24h, appelez +212612345678')
        self.assertGreaterEqual(len(bad), 4)

    def test_scoring_b2c_et_b2b(self):
        analyse_a = analyzer.analyser_demande_b2c('Besoin urgent femme de ménage à Anfa Casablanca 3 fois par semaine dès lundi.')
        sc_a = analyzer.scorer_demande_b2c(
            {'nom': 'Nadia', 'tel': '+212661112233', 'email': 'nadia@exemple.ma', 'consentement_recontact': True},
            analyse_a,
        )
        self.assertEqual(sc_a['classification'], 'A')
        self.assertGreaterEqual(sc_a['score'], 75)

        analyse_vague = analyzer.analyser_demande_b2c('Bonjour, quels sont vos services ?')
        sc_c = analyzer.scorer_demande_b2c({'nom': 'Curieux', 'email': 'curieux@exemple.ma', 'consentement_recontact': True}, analyse_vague)
        self.assertIn(sc_c['classification'], ('B', 'C'))
        self.assertLess(sc_c['score'], 75)

        sc_pro_a = analyzer.scorer_prospect_pro({
            'nom_entreprise': 'Hôtel Anfa Royal', 'type_etablissement': 'hotel', 'ville': 'Casablanca', 'quartier': 'Anfa',
            'source_nom': 'site_web_officiel', 'source_url': 'https://hotel-anfa-royal.ma/contact',
            'date_consultation': '2026-11-28T09:00:00+00:00',
            'email_pro': 'rh@hotel-anfa-royal.ma', 'besoin_probable': 'Recrutement femmes de chambre et serveurs',
            'preuve_extrait': 'Offre recrutement hôtellerie ouverte', 'signaux_interet': ['annonce_embauche'], 'niveau': 'A',
        })
        self.assertEqual(sc_pro_a['classification'], 'A')
        self.assertGreaterEqual(sc_pro_a['score'], 75)

        # Source interdite (Facebook scraping) -> Exclu
        sc_pro_exclu = analyzer.scorer_prospect_pro({
            'nom_entreprise': 'Hotel FB', 'type_etablissement': 'hotel', 'ville': 'Casablanca',
            'source_url': 'https://www.facebook.com/hotelfb',
            'email_pro': 'a@b.ma',
        })
        self.assertEqual(sc_pro_exclu['classification'], 'Exclu')
        self.assertEqual(sc_pro_exclu['score'], 0)


class ConnectorsComplianceTests(unittest.TestCase):
    def test_web_discovery_bloque_reseaux_prives_et_extrait_html_public(self):
        for bad_url in (
            'https://www.facebook.com/groups/casablanca',
            'https://instagram.com/monhotel',
            'https://www.tiktok.com/@resto',
            'https://www.linkedin.com/in/manager',
            'https://chat.whatsapp.com/ABC123',
        ):
            with self.subTest(bad_url=bad_url):
                ok_src, _ = analyzer.est_source_pro_autorisee(bad_url)
                self.assertFalse(ok_src)
                with self.assertRaises(connectors.ComplianceError):
                    connectors.WebDiscoveryConnector.extraire_prospect_depuis_html(bad_url, '<html></html>')

        html_sample = """
        <html><head><title>Riad &amp; Hôtel Anfa Casablanca — Recrutement</title></head>
        <body>
          <h1>Hôtel Anfa Casablanca</h1>
          <p>Nous recrutons du personnel de ménage et des serveurs en cuisine pour notre établissement à Anfa, Casablanca.</p>
          <p>Contact RH : recrutement@hotel-anfa-test.ma · Tél : +212 522 12 34 56</p>
        </body></html>
        """
        extracted = connectors.WebDiscoveryConnector.extraire_prospect_depuis_html(
            'https://hotel-anfa-test.ma/carrieres',
            html_sample,
        )
        self.assertEqual(extracted['type_etablissement'], 'hotel')
        self.assertEqual(extracted['email_pro'], 'recrutement@hotel-anfa-test.ma')
        self.assertEqual(extracted['ville'], 'Casablanca')
        self.assertEqual(extracted['quartier'], 'Anfa')
        self.assertTrue(extracted['preuve_extrait'])
        self.assertTrue(extracted['date_consultation'])

    def test_whatsapp_connector_exige_opt_in_et_live_flag(self):
        with self.assertRaises(connectors.ComplianceError):
            connectors.WhatsAppConnector.send('+212661000111', 'Bonjour', has_opt_in=False)
        with self.assertRaises(connectors.ComplianceError):
            connectors.WhatsAppConnector.send('+212661000111', 'Bonjour', has_opt_in=True, require_live_flag=True)

    def test_email_connector_delivrabilite_et_garde_live(self):
        self.assertFalse(connectors.verifier_delivrabilite_email('not-an-email', check_dns=False)['valid'])
        self.assertFalse(connectors.verifier_delivrabilite_email('user@mailinator.com', check_dns=False)['valid'])
        self.assertTrue(connectors.verifier_delivrabilite_email('direction@hotel-casa.ma', check_dns=False)['valid'])
        with self.assertRaises(connectors.ComplianceError):
            connectors.EmailConnector.send('direction@hotel-casa.ma', 'Test', 'Bonjour\nRépondez STOP.', require_live_flag=True)


class AutonomeWorkflowAndHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_db = webapp.DB
        self.orig_live = os.environ.get('YALLAH_ENABLE_LIVE')
        self.orig_admin_pw = os.environ.get('YALLAH_ADMIN_PASSWORD')
        os.environ['YALLAH_ENABLE_LIVE'] = '0'
        os.environ['YALLAH_ADMIN_PASSWORD'] = 'AdminSecretPassword2026!'
        webapp.DB = Path(self.tmp.name) / 'yallah_test.sqlite3'
        webapp._intake_hits.clear()
        webapp.initialize()

        access.add_user('sales', 'SalesPassword2026!!', 'commercial')
        access.add_user('recr', 'RecruteurPassword26!', 'recruteur')
        access.add_user('reader', 'ReaderPassword2026!', 'lecture')

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), webapp.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        webapp.DB = self.orig_db
        if self.orig_live is None:
            os.environ.pop('YALLAH_ENABLE_LIVE', None)
        else:
            os.environ['YALLAH_ENABLE_LIVE'] = self.orig_live
        if self.orig_admin_pw is None:
            os.environ.pop('YALLAH_ADMIN_PASSWORD', None)
        else:
            os.environ['YALLAH_ADMIN_PASSWORD'] = self.orig_admin_pw
        self.tmp.cleanup()

    def _req(self, method, path, body=None, user=('admin', 'AdminSecretPassword2026!'), token=True):
        headers = {}
        if user:
            headers['Authorization'] = _auth_header(*user)
        if token and method == 'POST':
            headers['X-Yallah-Token'] = webapp.TOKEN
        data = None
        if body is not None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(body).encode('utf-8')
        req = Request(f'http://127.0.0.1:{self.port}{path}', data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=5) as resp:
                raw = resp.read()
                ct = resp.headers.get('Content-Type', '')
                return resp.status, json.loads(raw) if 'json' in ct else raw.decode('utf-8')
        except HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except Exception:
                return exc.code, raw.decode('utf-8', errors='replace')

    def test_14_tables_minimales_sqlite_et_schema_postgresql(self):
        expected = {
            'sources', 'contacts', 'consentements', 'demandes_clients', 'prospects',
            'messages', 'campagnes', 'envois', 'reponses', 'blocages', 'relances',
            'daily_digests', 'audit_log', 'settings',
        }
        with webapp.connect() as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertTrue(expected.issubset(tables), f'Tables manquantes SQLite: {expected - tables}')

        pg_sql = (Path(__file__).resolve().parent.parent / 'schema_postgresql.sql').read_text(encoding='utf-8')
        for tbl in expected:
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {tbl}', pg_sql)

    def test_b2c_formulaire_public_deux_cases_consentement_et_interdictions(self):
        # 1) Page /demande contient les 2 cases décochées et la mention STOP exacte
        st_html, page_html = self._req('GET', '/demande', user=None)
        self.assertEqual(st_html, 200)
        self.assertIn('J’accepte que Yallah Services me recontacte au sujet de ma demande.', page_html)
        self.assertIn('J’accepte de recevoir des messages de Yallah Services sur WhatsApp.', page_html)
        self.assertIn('Vous pouvez demander l’arrêt des communications à tout moment en répondant STOP.', page_html)
        self.assertNotIn('name="consentement_recontact" type="checkbox" checked', page_html)
        self.assertNotIn('name="consentement_whatsapp" type="checkbox" checked', page_html)

        # 2) Refus si consentement recontact non coché
        st_bad, _ = self._req('POST', '/api/public/intake', {
            'kind': 'demande', 'name': 'Karim', 'city': 'Casablanca',
            'email': 'karim@exemple.ma', 'message': 'Ménage Anfa',
            'consentement_recontact': False, 'consentement_whatsapp': False,
        }, user=None, token=False)
        self.assertEqual(st_bad, 400)

        # 3) Soumission valide sans consentement WhatsApp -> capturée en demandes_clients, 0 marketing permissions
        st_ok, resp = self._req('POST', '/api/public/intake', {
            'kind': 'demande', 'name': 'Salma Benali', 'city': 'Casablanca', 'quartier': 'Anfa',
            'email': 'salma@exemple.ma', 'whatsapp': '+212661223344',
            'message': 'Bonjour, je cherche une femme de ménage à Anfa 3 fois par semaine dès cette semaine.',
            'consentement_recontact': True, 'consentement_whatsapp': False,
        }, user=None, token=False)
        self.assertEqual(st_ok, 200)
        self.assertEqual(resp['classification'], 'A')
        self.assertGreaterEqual(resp['score'], 75)
        with webapp.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM permissions').fetchone()[0], 0)

        # 4) Tentative d'envoi WhatsApp SANS consentement WhatsApp -> strictement bloquée !
        dem_id = resp['demande_id']
        st_wa_block, err_wa = self._req('POST', '/api/autonome/validate', {
            'entity_type': 'demande_b2c', 'entity_id': dem_id, 'action': 'envoyer_maintenant',
            'canal': 'whatsapp', 'confirm': True, 'simulation': True,
        })
        self.assertEqual(st_wa_block, 400)
        self.assertIn('WhatsApp', err_wa['error'])

        # 5) Sources B2C interdites (prospection froide / appel manqué / scraping) rejetées
        for forbidden_src in ('scraping_facebook', 'liste_achetee', 'appel_manque', 'like_instagram'):
            st_forb, _ = self._req('POST', '/api/autonome/demandes', {
                'nom': 'Test Interdit', 'ville': 'Casablanca', 'tel': '+212661998877',
                'message_brut': 'Ménage Anfa', 'source': forbidden_src,
                'consentement_recontact': False,
            })
            self.assertEqual(st_forb, 400)

    def test_workflow_9_boutons_relances_j3_j7_j14_et_stop_immediat(self):
        # Créer une demande B2C avec consentements Email + WhatsApp
        st, dem = self._req('POST', '/api/autonome/demandes', {
            'nom': 'Amine El Fassi', 'ville': 'Casablanca', 'quartier': 'Californie',
            'email': 'amine@exemple.ma', 'whatsapp': '+212661334455',
            'message_brut': 'Besoin urgent d’une cuisinière à domicile à Californie Casablanca temps plein.',
            'source': 'formulaire_prestation',
            'consentement_recontact': True, 'consentement_whatsapp': True,
        })
        self.assertEqual(st, 200)
        did = dem['id']

        # Doublon détecté sur même email/besoin dans les 7 jours
        st_dup, dem_dup = self._req('POST', '/api/autonome/demandes', {
            'nom': 'Amine El Fassi', 'ville': 'Casablanca', 'quartier': 'Californie',
            'email': 'AMINE@exemple.ma', 'message_brut': 'Rappel cuisinière Californie',
            'source': 'formulaire_contact', 'consentement_recontact': True,
        })
        self.assertEqual(st_dup, 200)
        self.assertTrue(dem_dup['duplicate'])

        # Action 1 : demander_verification
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'demander_verification', 'motif': 'Vérifier horaires'})[0], 200)
        # Action 2 : modifier_message
        new_msg = 'Bonjour Amine, merci pour votre demande à Californie. Pouvez-vous préciser vos horaires souhaités ?\nPour ne plus recevoir de messages, répondez STOP.'
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'modifier_message', 'message': new_msg})[0], 200)
        # Action 3 : valider
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'valider'})[0], 200)
        # Action 4 : appeler
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'appeler', 'note': 'Appel de qualification'})[0], 200)
        # Action 5 : repondre_whatsapp
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'repondre_whatsapp'})[0], 200)
        # Action 6 : envoyer_maintenant sans confirm=True -> 400
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'envoyer_maintenant', 'canal': 'email'})[0], 400)
        # Action 6 bis : envoyer_maintenant AVEC confirm=True -> 200 + planifie relances J+3, J+7, J+14
        st_send, res_send = self._req('POST', '/api/autonome/validate', {
            'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'envoyer_maintenant',
            'canal': 'email', 'confirm': True, 'simulation': True,
        })
        self.assertEqual(st_send, 200)
        self.assertEqual(len(res_send['relances_planifiees']), 3)
        self.assertEqual([r['delai_jours'] for r in res_send['relances_planifiees']], [3, 7, 14])

        # Règle anti-spam : jamais 2 messages le même jour au même contact !
        st_same_day, err_sd = self._req('POST', '/api/autonome/validate', {
            'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'envoyer_maintenant',
            'canal': 'whatsapp', 'confirm': True, 'simulation': True,
        })
        self.assertEqual(st_same_day, 400)
        self.assertIn('aujourd’hui', err_sd['error'])

        # Action 7 : programmer_envoi sur une autre demande
        _, dem_prog = self._req('POST', '/api/autonome/demandes', {
            'nom': 'Laila Chraibi', 'ville': 'Casablanca', 'quartier': 'Anfa',
            'email': 'laila@exemple.ma', 'message_brut': 'Besoin ménage hebdomadaire Anfa',
            'source': 'formulaire_prestation', 'consentement_recontact': True,
        })
        st_prog, _ = self._req('POST', '/api/autonome/validate', {
            'entity_type': 'demande_b2c', 'entity_id': dem_prog['id'], 'action': 'programmer_envoi',
            'canal': 'email', 'confirm': True, 'scheduled_at': '2026-12-05T09:00',
        })
        self.assertEqual(st_prog, 200)

        # Réponse STOP entrante -> blocage immédiat définitif + annulation relances
        st_stop, res_stop = self._req('POST', '/api/autonome/reponses', {
            'canal': 'whatsapp', 'expediteur': '+212661334455', 'contenu': 'STOP SMS retirez-moi svp',
        })
        self.assertEqual(st_stop, 200)
        self.assertTrue(res_stop['stop_detecte'])
        with webapp.connect() as con:
            active_rel = con.execute("SELECT COUNT(*) FROM relances WHERE entity_type='demande_b2c' AND entity_id=? AND statut='prevue'", (did,)).fetchone()[0]
            self.assertEqual(active_rel, 0)
            self.assertGreater(con.execute('SELECT COUNT(*) FROM blocages').fetchone()[0], 0)

        # Après STOP, toute nouvelle action sur ce contact échoue définitivement
        st_after_stop, _ = self._req('POST', '/api/autonome/validate', {
            'entity_type': 'demande_b2c', 'entity_id': did, 'action': 'programmer_envoi',
            'canal': 'email', 'confirm': True, 'scheduled_at': '2026-12-06T09:00',
        })
        self.assertEqual(st_after_stop, 400)

        # Actions 8 & 9 (rejeter / bloquer) sur une autre demande
        _, dem2 = self._req('POST', '/api/autonome/demandes', {
            'nom': 'Test Rejet', 'ville': 'Casablanca', 'email': 'rejet@exemple.ma',
            'message_brut': 'Bonjour', 'source': 'formulaire_contact', 'consentement_recontact': True,
        })
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': dem2['id'], 'action': 'rejeter', 'motif': 'Hors périmètre'})[0], 200)
        self.assertEqual(self._req('POST', '/api/autonome/validate', {'entity_type': 'demande_b2c', 'entity_id': dem2['id'], 'action': 'bloquer', 'motif': 'Demande client'})[0], 200)

    def test_prospection_b2b_decouverte_pipeline_et_daily_digest_whatsapp_sans_fuite(self):
        # Découverte B2B depuis HTML public
        html_doc = """
        <html><head><title>Hôtel Océan Anfa Casablanca — Carrières</title></head>
        <body><h1>Hôtel Océan Anfa</h1><p>Recrutement de personnel de ménage et serveurs à Anfa Casablanca. Contact : rh@hotel-ocean-anfa.ma / +212 522 99 88 77</p></body></html>
        """
        st_disc, disc = self._req('POST', '/api/autonome/prospects/discover', {
            'url': 'https://hotel-ocean-anfa.ma/carrieres', 'raw_html': html_doc,
        })
        self.assertEqual(st_disc, 200)
        pro = disc['saved']
        self.assertEqual(pro['classification'], 'A')
        self.assertGreaterEqual(pro['score'], 75)

        # Mise à jour pipeline Professionnels
        st_pipe, res_pipe = self._req('POST', '/api/autonome/pipeline', {
            'entity_type': 'prospect_pro', 'entity_id': pro['id'],
            'pipeline_stage': 'contact_valide', 'notes': 'Contact RH confirmé',
        })
        self.assertEqual(st_pipe, 200)
        self.assertEqual(res_pipe['pipeline_stage'], 'contact_valide')

        # Générer Daily Prospect Digest + vérifier que WhatsApp n'expose pas les emails/tels sensibles
        _, dem_priv = self._req('POST', '/api/autonome/demandes', {
            'nom': 'Famille Bennani', 'ville': 'Casablanca', 'quartier': 'Anfa',
            'email': 'bennani.prive@secretmail.ma', 'whatsapp': '+212661778899',
            'message_brut': 'Besoin urgent femme de ménage à Anfa 3 fois par semaine.',
            'source': 'formulaire_prestation', 'consentement_recontact': True, 'consentement_whatsapp': True,
            'sensible': True,
        })
        self.assertEqual(dem_priv['classification'], 'A')

        st_dig, dig = self._req('POST', '/api/autonome/digest', {'limit': 10})
        self.assertEqual(st_dig, 200)
        self.assertIn('kpis', dig)
        self.assertGreaterEqual(dig['kpis']['demandes_qualifiees_a'], 1)
        self.assertGreaterEqual(dig['kpis']['prospects_pro_qualifies_a'], 1)
        # Confidentialité WhatsApp : jamais d'email ou téléphone personnel dans whatsapp_text
        self.assertNotIn('bennani.prive@secretmail.ma', dig['whatsapp_text'])
        self.assertNotIn('+212661778899', dig['whatsapp_text'])
        self.assertIn('Famille Bennani', dig['whatsapp_text'])
        self.assertIn('fiche sensible', dig['whatsapp_text'])

    def test_autopilot_admin_only_defaut_off_plafonds_kill_switch_et_audit_export(self):
        # 1) Par défaut Auto-pilot est DÉSACTIVÉ
        st_dash, dash = self._req('GET', '/api/autonome/dashboard')
        self.assertEqual(st_dash, 200)
        self.assertFalse(dash['autopilot']['enabled'])

        # 2) Commercial, recruteur et lecture reçoivent 403 sur Auto-pilot ET sur /api/audit/export
        for creds in (('sales', 'SalesPassword2026!!'), ('recr', 'RecruteurPassword26!'), ('reader', 'ReaderPassword2026!')):
            self.assertEqual(self._req('POST', '/api/autonome/autopilot', {'action': 'config', 'enabled': True, 'confirm': True}, user=creds)[0], 403)
            self.assertEqual(self._req('GET', '/api/audit/export?format=csv', user=creds)[0], 403)

        # 3) Le rôle 'recruteur' fonctionne bien sur les routes recrutement
        self.assertNotEqual(self._req('GET', '/api/matches?need_id=999999', user=('recr', 'RecruteurPassword26!'))[0], 403)

        # 4) Admin crée 2 demandes B2C classe A avec consentement recontact
        _, d1 = self._req('POST', '/api/autonome/demandes', {
            'nom': 'Client A1', 'ville': 'Casablanca', 'quartier': 'Anfa', 'email': 'a1@exemple.ma',
            'message_brut': 'Besoin urgent femme de ménage Anfa 3 fois par semaine',
            'source': 'formulaire_prestation', 'consentement_recontact': True,
        })
        _, d2 = self._req('POST', '/api/autonome/demandes', {
            'nom': 'Client A2', 'ville': 'Casablanca', 'quartier': 'Maarif', 'email': 'a2@exemple.ma',
            'message_brut': 'Besoin urgent cuisinière Maarif temps plein',
            'source': 'formulaire_prestation', 'consentement_recontact': True,
        })
        self.assertEqual(d1['classification'], 'A')
        self.assertEqual(d2['classification'], 'A')

        # 5) Auto-pilot désactivé -> cycle bloqué (0 envoi)
        st_off, res_off = self._req('POST', '/api/autonome/autopilot', {'action': 'run', 'dry_run': True})
        self.assertEqual(st_off, 200)
        self.assertFalse(res_off['ran'])

        # 6) Activation sans confirm=True -> 400
        self.assertEqual(self._req('POST', '/api/autonome/autopilot', {'action': 'config', 'enabled': True})[0], 400)

        # 7) Admin active Auto-pilot avec plafond=1 -> 1 seul contact traité
        st_cfg, cfg = self._req('POST', '/api/autonome/autopilot', {'action': 'config', 'enabled': True, 'confirm': True, 'max_first_contacts_per_day': 1})
        self.assertEqual(st_cfg, 200)
        self.assertTrue(cfg['enabled'])
        self.assertEqual(cfg['max_first_contacts_per_day'], 1)

        st_run, res_run = self._req('POST', '/api/autonome/autopilot', {'action': 'run', 'dry_run': True})
        self.assertEqual(st_run, 200)
        self.assertTrue(res_run['ran'])
        self.assertEqual(res_run['sent'], 1)

        # 8) Kill Switch en un clic désactive immédiatement
        st_kill, res_kill = self._req('POST', '/api/autonome/autopilot', {'action': 'kill_switch', 'motif': 'Test arrêt urgence'})
        self.assertEqual(st_kill, 200)
        self.assertFalse(res_kill['enabled'])

        # 9) Admin exporte le journal d'audit CSV et JSON
        st_csv, csv_body = self._req('GET', '/api/audit/export?format=csv')
        self.assertEqual(st_csv, 200)
        self.assertIn('autopilot_kill_switch', csv_body)
        st_json, json_body = self._req('GET', '/api/audit/export?format=json')
        self.assertEqual(st_json, 200)
        self.assertIsInstance(json_body, list)
        self.assertGreater(len(json_body), 0)


if __name__ == '__main__':
    unittest.main()
