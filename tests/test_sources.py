import ast
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import access
import campaigns
import operations
import validation as v
import webapp
import webhooks
import yallah_b2c as b2c
import yallah_messages as messages
import yallah_prospection as prospection
import yallah_sources as sources

ROOT = Path(__file__).resolve().parents[1]


class SourcesAndAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old_db = webapp.DB
        self.db_path = Path(self.dir.name) / 'shared.sqlite3'
        webapp.DB = self.db_path
        webapp.initialize()

    def tearDown(self):
        webapp.DB = self.old_db
        self.dir.cleanup()

    def test_catalogue_sources_a1_a_c_et_prescripteurs(self):
        expected = {
            'site_formulaire', 'whatsapp_entrant', 'gbp_entrant',
            'avito_demande', 'fb_groupe_demande', 'partenaire_parrain',
            'relocation_rh', 'clinique_senior', 'agence_immo',
            'conciergerie', 'creche_ecole', 'liste_froide_b2b',
        }
        self.assertEqual(set(sources.SOURCES.keys()), expected)
        for key, info in sources.SOURCES.items():
            self.assertIn(info['intention'], range(1, 6), key)
            self.assertIn(info['joignabilite'], range(1, 6), key)

        today = v.today().isoformat()
        for seg in ('relocation_rh', 'clinique_senior', 'agence_immo', 'conciergerie', 'creche_ecole'):
            self.assertIn(seg, prospection.SEGMENTS)
            prospect = {
                'nom': f'Partenaire {seg}',
                'segment': seg,
                'phase': 1,
                'ville': 'Casablanca',
                'zone': 'Anfa',
                'tel': '+212661112233',
                'email': f'contact@{seg.replace("_", "")}.ma',
                'source': seg,
                'source_url': 'https://exemple-pro.ma/contact',
                'date_consultation': today,
                'niveau': 'A',
            }
            v.record('b2b', prospect)
            for langue in ('fr', 'darija', 'arabe'):
                msg = messages.generer_message(prospect, 'b2b', langue, 'Youssef')
                self.assertEqual(messages.verifier_message(msg), [])

    def test_normalisation_maroc_et_dedoublonnage_csv_et_web(self):
        self.assertEqual(sources.normaliser_tel('06 61-23.45.67'), '+212661234567')
        self.assertEqual(sources.normaliser_tel('+212 (0)6 61 23 45 67'), '+212661234567')
        self.assertEqual(sources.normaliser_email('  Contact@AgenceImmo.MA '), 'contact@agenceimmo.ma')
        self.assertEqual(sources.cle_nom_ville('Résidence   Anfa!', ' Casablanca '), 'nv:residence anfa|casablanca')

        today = v.today().isoformat()
        csv_text = (
            'nom,ville,zone,tel,email,source,url_source,date_source,segment,niveau\n'
            f'Agence Immo Anfa,Casablanca,Anfa,06 61 99 88 77,contact@immoanfa.ma,agence_immo,https://immoanfa.ma/contact,{today},agence_immo,A\n'
        )
        res1 = operations.import_records({'kind': 'b2b', 'csv': csv_text, 'apply': True}, actor='test')
        self.assertTrue(res1['applied'])

        # Même numéro au format +212 -> doublon détecté
        dup_tel_csv = (
            'nom,ville,zone,tel,email,source,url_source,date_source,segment,niveau\n'
            f'Autre Nom,Casablanca,Maarif,+212661998877,autre@immoanfa.ma,agence_immo,https://immoanfa.ma/maarif,{today},agence_immo,A\n'
        )
        preview_dup_tel = operations.import_records({'kind': 'b2b', 'csv': dup_tel_csv, 'apply': False}, actor='test')
        self.assertFalse(preview_dup_tel['rows'][0]['ok'])
        self.assertIn('Doublon', preview_dup_tel['rows'][0]['error'])

        # Même couple nom + ville avec autres coordonnées -> doublon détecté
        dup_nv_csv = (
            'nom,ville,zone,tel,email,source,url_source,date_source,segment,niveau\n'
            f'Agence Immo Anfa,Casablanca,Gauthier,0662001122,direction@immoanfa.ma,agence_immo,https://immoanfa.ma/direction,{today},agence_immo,A\n'
        )
        preview_dup_nv = operations.import_records({'kind': 'b2b', 'csv': dup_nv_csv, 'apply': False}, actor='test')
        self.assertFalse(preview_dup_nv['rows'][0]['ok'])

    def test_verrou_loi_09_08_b2b_autorise_et_b2c_non_sollicite_bloque(self):
        today = v.today().isoformat()
        # B2B public pro -> autorisé en contact 1-à-1 manuel
        ok_b2b, _ = sources.contact_manuel_autorise('b2b', {'source': 'relocation_rh', 'tel': '+212661112233'})
        self.assertTrue(ok_b2b)

        # B2C annonce publique de recherche active -> autorisé en réponse directe
        ok_avito, _ = sources.contact_manuel_autorise('b2c', {'source': 'avito_demande', 'tel': '+212661112234'})
        self.assertTrue(ok_avito)

        # B2C non sollicité sans consentement explicite -> bloqué Loi 09-08
        unsolicited_b2c = {
            'nom': 'Particulier Annuaire',
            'besoin': 'MEN',
            'ville': 'Casablanca',
            'zone': 'Anfa',
            'tel': '+212663445566',
            'source': 'partenaire_parrain',
            'source_url': 'https://exemple.ma/post',
            'date_consultation': today,
            'niveau': 'B',
            'consentement_declare': False,
        }
        ok_b2c, motif = sources.contact_manuel_autorise('b2c', unsolicited_b2c)
        self.assertFalse(ok_b2c)
        self.assertIn('09-08', motif)

        with webapp.connect() as con:
            rid = con.execute('INSERT INTO records(kind,payload) VALUES (?,?)', ('b2c', json.dumps(unsolicited_b2c))).lastrowid
            q = sources.construire_file_du_jour(con, today_date=v.today(), prenom='Youssef')
            self.assertNotIn(rid, [it['record_id'] for it in q['items']])
            self.assertGreaterEqual(q['blocked_consent'], 1)

        # Avec consentement déclaré -> débloqué
        consented_b2c = dict(unsolicited_b2c, tel='+212663778899', nom='Particulier Parrainé', consentement_declare=True)
        ok_consented, _ = sources.contact_manuel_autorise('b2c', consented_b2c)
        self.assertTrue(ok_consented)

    def test_file_du_jour_relances_j3_j7_j14_avant_premiers_contacts_et_fraicheur(self):
        today = v.today()
        with webapp.connect() as con:
            # Fiche B2B fraîche mais jamais contactée avec score élevé (relocation_rh, niveau A)
            r_first = con.execute('INSERT INTO records(kind,payload) VALUES (?,?)', ('b2b', json.dumps({
                'nom': 'Cabinet Relocation Casa',
                'segment': 'relocation_rh',
                'phase': 1,
                'ville': 'Casablanca',
                'zone': 'Anfa',
                'tel': '+212664112233',
                'email': 'rh@reloccasa.ma',
                'source': 'relocation_rh',
                'source_url': 'https://reloccasa.ma/contact',
                'date_consultation': today.isoformat(),
                'niveau': 'A',
            }))).lastrowid

            # Fiche B2B avec 1er envoi il y a 4 jours -> éligible Relance J+3 (doit passer AVANT r_first)
            r_relance = con.execute('INSERT INTO records(kind,payload) VALUES (?,?)', ('b2b', json.dumps({
                'nom': 'Hôtel Corniche',
                'segment': 'hotel',
                'phase': 1,
                'ville': 'Casablanca',
                'zone': 'Ain Diab',
                'tel': '+212664223344',
                'email': 'direction@hotelcorniche.ma',
                'source': 'liste_froide_b2b',
                'source_url': 'https://hotelcorniche.ma',
                'date_consultation': today.isoformat(),
                'niveau': 'B',
            }))).lastrowid
            d4 = (today - timedelta(days=4)).isoformat() + 'T10:00:00+00:00'
            con.execute(
                "INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,'email','sortant','1er envoi','note',?)",
                (r_relance, d4),
            )

            # Fiche B2B périmée (> 7 jours) -> exclue tant que non revérifiée
            stale_day = (today - timedelta(days=12)).isoformat()
            r_stale = con.execute('INSERT INTO records(kind,payload) VALUES (?,?)', ('b2b', json.dumps({
                'nom': 'Clinique Ancienne Fiche',
                'segment': 'clinique_senior',
                'phase': 1,
                'ville': 'Casablanca',
                'zone': 'Maarif',
                'tel': '+212664334455',
                'source': 'clinique_senior',
                'source_url': 'https://cliniqueancienne.ma',
                'date_consultation': stale_day,
                'niveau': 'A',
            }))).lastrowid

            queue = sources.construire_file_du_jour(con, today_date=today, prenom='Youssef')
            ids = [it['record_id'] for it in queue['items']]
            self.assertIn(r_relance, ids)
            self.assertIn(r_first, ids)
            self.assertNotIn(r_stale, ids)
            self.assertGreaterEqual(queue['stale_count'], 1)
            # La relance J+3 est servie avant le 1er contact malgré un score intrinsèque plus bas
            self.assertLess(ids.index(r_relance), ids.index(r_first))
            rel_item = next(it for it in queue['items'] if it['record_id'] == r_relance)
            self.assertEqual(rel_item['action_kind'], 'Relance J+3')
            self.assertTrue(rel_item['bascule_mobile'])

            # Progression J+3 -> J+7 -> J+14 -> fin après 4e envoi
            d8 = (today - timedelta(days=8)).isoformat() + 'T10:00:00+00:00'
            con.execute("UPDATE conversations SET created=? WHERE record_id=?", ((today - timedelta(days=15)).isoformat() + 'T10:00:00+00:00', r_relance))
            con.execute("INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,'whatsapp','sortant','Relance 1','note',?)", (r_relance, d8))
            q2 = sources.construire_file_du_jour(con, today_date=today, prenom='Youssef')
            rel2 = next(it for it in q2['items'] if it['record_id'] == r_relance)
            self.assertEqual(rel2['action_kind'], 'Relance J+7')

            con.execute("UPDATE conversations SET created=? WHERE record_id=?", ((today - timedelta(days=20)).isoformat() + 'T10:00:00+00:00', r_relance))
            con.execute("INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,'whatsapp','sortant','Relance 2','note',?)", (r_relance, (today - timedelta(days=15)).isoformat() + 'T10:00:00+00:00'))
            q3 = sources.construire_file_du_jour(con, today_date=today, prenom='Youssef')
            rel3 = next(it for it in q3['items'] if it['record_id'] == r_relance)
            self.assertEqual(rel3['action_kind'], 'Relance J+14')

            con.execute("INSERT INTO conversations(record_id,channel,direction,body,outcome,created) VALUES (?,'whatsapp','sortant','Relance 3 finale','note',?)", (r_relance, (today - timedelta(days=15)).isoformat() + 'T11:00:00+00:00'))
            q4 = sources.construire_file_du_jour(con, today_date=today, prenom='Youssef')
            self.assertNotIn(r_relance, [it['record_id'] for it in q4['items']])

        # Revérification de la fiche périmée -> devient éligible
        sources.marquer_verifie_db([str(r_stale)], db_path=self.db_path)
        with webapp.connect() as con:
            q5 = sources.construire_file_du_jour(con, today_date=today, prenom='Youssef')
            self.assertIn(r_stale, [it['record_id'] for it in q5['items']])

    def test_temps_operateur_et_roi_reel_strictement_sur_grand_livre(self):
        today = v.today().isoformat()
        with webapp.connect() as con:
            rid = con.execute('INSERT INTO records(kind,payload) VALUES (?,?)', ('b2b', json.dumps({
                'nom': 'Clinique Senior Californie',
                'segment': 'clinique_senior',
                'phase': 1,
                'ville': 'Casablanca',
                'zone': 'Californie',
                'tel': '+212665112233',
                'email': 'direction@cliniquesenior.ma',
                'source': 'clinique_senior',
                'source_url': 'https://cliniquesenior.ma/contact',
                'date_consultation': today,
                'niveau': 'A',
            }))).lastrowid

        # 30 minutes d'opérateur (0,5 h) + contrat gagné MAIS encore 0 MAD dans ledger
        operations.execute('time_log', {
            'record_id': rid, 'minutes': 30, 'day': today, 'note': 'Qualification téléphonique',
        }, 'test')
        opp = operations.execute('opportunity', {
            'record_id': rid, 'title': 'Garde-malade Californie',
            'stage': 'gagne', 'owner': 'Youssef', 'next_action': 'Démarrage mission', 'due': today,
        }, 'test')
        operations.execute('conversation', {
            'record_id': rid, 'channel': 'telephone',
            'direction': 'sortant', 'outcome': 'note', 'body': 'Appel initial',
        }, 'test')
        operations.execute('conversation', {
            'record_id': rid, 'channel': 'telephone',
            'direction': 'entrant', 'outcome': 'reponse', 'body': 'Accord de principe',
        }, 'test')

        dash_zero = operations.dashboard()
        self.assertEqual(dash_zero['metrics']['total_minutes'], 30)
        row_zero = next(r for r in dash_zero['source_roi'] if r['source'] == 'clinique_senior')
        self.assertEqual(row_zero['contracts'], 1)
        self.assertEqual(row_zero['minutes'], 30)
        # Strictement 0 MAD tant qu'aucune facture ni encaissement réel n'est enregistré
        self.assertEqual(row_zero['invoiced_mad'], 0.0)
        self.assertEqual(row_zero['received_mad'], 0.0)
        self.assertEqual(row_zero['mad_per_hour'], 0.0)

        # Ajout d'un encaissement réel de 1 400 MAD sur 0,5 h -> 2 800 MAD / heure
        operations.execute('ledger', {
            'opportunity_id': opp['id'], 'kind': 'encaissement',
            'amount': 1400, 'day': today, 'reference': 'VIR-2026-0042',
        }, 'test')
        dash_paid = operations.dashboard()
        row_paid = next(r for r in dash_paid['source_roi'] if r['source'] == 'clinique_senior')
        self.assertEqual(row_paid['received_mad'], 1400.0)
        self.assertEqual(row_paid['mad_per_heure'] if 'mad_per_heure' in row_paid else row_paid['mad_per_hour'], 2800.0)

    def test_pages_seo_locales_services_et_attribution_formulaire_b2c(self):
        matrice = b2c.construire_matrice()
        self.assertEqual(len(matrice), 35)
        self.assertEqual(len({m['slug'] for m in matrice}), 35)
        def visible_text(raw):
            s = raw.decode('utf-8') if isinstance(raw, bytes) else raw
            s = re.sub(r'<style[^>]*>.*?</style>', ' ', s, flags=re.S | re.I)
            s = re.sub(r'<script[^>]*>.*?</script>', ' ', s, flags=re.S | re.I)
            return re.sub(r'<[^>]+>', ' ', s)

        import re
        self.assertEqual(b2c.verifier_contenu(visible_text(b2c.rendre_catalogue_services_html())), [])
        for case in matrice:
            self.assertEqual(b2c.verifier_contenu(visible_text(b2c.rendre_page_service_html(case))), [], case['ref'])

        with patch.dict(os.environ, {'YALLAH_ENV': 'development', 'YALLAH_ADMIN_PASSWORD': 'secret-password-123'}):
            server = ThreadingHTTPServer(('127.0.0.1', 0), webapp.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                # Catalogue /services et page /services/<slug> accessibles publiquement sans auth Basic
                cat_html = urlopen(base + '/services').read().decode('utf-8')
                self.assertIn('femme-de-menage-californie-casablanca', cat_html)
                page_html = urlopen(base + '/services/femme-de-menage-californie-casablanca').read().decode('utf-8')
                self.assertIn('CAS-CAL-MEN', page_html)
                page_by_ref = urlopen(base + '/services/CAS-CAL-MEN').read().decode('utf-8')
                self.assertIn('Californie', page_by_ref)

                with self.assertRaises(HTTPError) as ctx404:
                    urlopen(base + '/services/quartier-inexistant-xyz')
                self.assertEqual(ctx404.exception.code, 404)

                # Soumission entrante depuis la page SEO -> attribution site_formulaire + ref B2C
                req = Request(
                    base + '/api/public/intake',
                    data=json.dumps({
                        'kind': 'demande',
                        'name': 'Mme Bennani',
                        'tel': '0661445566',
                        'city': 'Casablanca',
                        'zone': 'Californie',
                        'b2c_ref': 'CAS-CAL-MEN',
                        'source': 'site_formulaire:CAS-CAL-MEN',
                        'message': 'Bonjour, besoin hebdomadaire pour villa à Californie.',
                        'acknowledge': True,
                    }).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                resp = json.loads(urlopen(req).read().decode('utf-8'))
                self.assertTrue(resp['ok'])
            finally:
                server.shutdown()
                server.server_close()

        dash = operations.dashboard()
        intake_row = dash['intake'][0]
        self.assertEqual(intake_row['b2c_decoded']['ref'], 'CAS-CAL-MEN')
        conv = operations.execute('intake_opportunity', {
            'intake_id': intake_row['id'],
            'kind': 'b2c',
            'name': 'Mme Bennani',
            'city': 'Casablanca',
            'zone': 'Californie',
            'besoin': 'MEN',
            'owner': 'Youssef',
            'next_action': 'Appeler pour qualifier horaires',
            'due': v.today().isoformat(),
        }, 'test')
        with webapp.connect() as con:
            rec = json.loads(con.execute('SELECT payload FROM records WHERE id=?', (conv['record_id'],)).fetchone()[0])
        self.assertEqual(rec['source'], 'site_formulaire')
        self.assertEqual(rec['source_type'], 'entrant')
        self.assertTrue(sources.contact_manuel_autorise('b2c', rec)[0])

    def test_cli_yallah_sources_zero_envoi_et_commandes(self):
        tree = ast.parse((ROOT / 'yallah_sources.py').read_text(encoding='utf-8'))
        forbidden = {'urllib.request', 'http.client', 'socket', 'smtplib', 'requests', 'httpx'}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertEqual(imported & forbidden, set())

        # Toute option --envoyer est refusée par argparse
        bad = subprocess.run(
            [sys.executable, str(ROOT / 'yallah_sources.py'), '--envoyer'],
            capture_output=True, text=True,
        )
        self.assertNotEqual(bad.returncode, 0)

        csv_path = Path(self.dir.name) / 'import_cli.csv'
        today = v.today().isoformat()
        csv_path.write_text(
            'nom,ville,zone,tel,email,source,url_source,date_source,segment,niveau\n'
            f'Conciergerie Dar Bouazza,Casablanca,Dar Bouazza,0668112233,contact@conciergeriedb.ma,conciergerie,https://conciergeriedb.ma,{today},conciergerie,A\n',
            encoding='utf-8',
        )
        cmd_base = [sys.executable, str(ROOT / 'yallah_sources.py'), '--db', str(self.db_path)]
        r_imp = subprocess.run(cmd_base + ['--importer', str(csv_path)], capture_output=True, text=True, check=True)
        self.assertIn('1 ajoutés', r_imp.stdout)

        with webapp.connect() as con:
            rid = con.execute("SELECT id FROM records ORDER BY id DESC LIMIT 1").fetchone()[0]

        r_file = subprocess.run(cmd_base + ['--file', '--prenom', 'Youssef'], capture_output=True, text=True, check=True)
        self.assertIn('Conciergerie Dar Bouazza', r_file.stdout)

        r_temps = subprocess.run(cmd_base + ['--temps', str(rid), '15'], capture_output=True, text=True, check=True)
        self.assertIn('15 min', r_temps.stdout)

        r_etape = subprocess.run(cmd_base + ['--etape', str(rid), 'contacte'], capture_output=True, text=True, check=True)
        self.assertIn('contacte', r_etape.stdout)

        r_roi = subprocess.run(cmd_base + ['--roi'], capture_output=True, text=True, check=True)
        self.assertIn('conciergerie', r_roi.stdout)
        self.assertIn('0 MAD tant que non facturé', r_roi.stdout)

    def test_lanceurs_sans_terminal_et_deploiement_cloud(self):
        cmd_launcher = ROOT / 'Lancer_Yallah.command'
        bat_launcher = ROOT / 'Lancer_Yallah.bat'
        dockerfile = ROOT / 'Dockerfile'
        dockerignore = ROOT / '.dockerignore'
        render_yaml = ROOT / 'render.yaml'

        for p in (cmd_launcher, bat_launcher, dockerfile, dockerignore, render_yaml):
            self.assertTrue(p.is_file(), f'Fichier manquant : {p.name}')
        self.assertTrue(os.access(cmd_launcher, os.X_OK))
        subprocess.run(['sh', '-n', str(cmd_launcher)], check=True)

        # Vérifie que data/ et .env sont exclus de l'image Docker
        di_txt = dockerignore.read_text(encoding='utf-8')
        self.assertIn('data/', di_txt)
        self.assertIn('.env', di_txt)

        # Vérifie Dockerfile et render.yaml (persistance SQLite + healthcheck public /services)
        df_txt = dockerfile.read_text(encoding='utf-8')
        self.assertIn('YALLAH_DB=/data/yallah.sqlite3', df_txt)
        self.assertIn('/services', df_txt)
        ry_txt = render_yaml.read_text(encoding='utf-8')
        self.assertIn('healthCheckPath: /services', ry_txt)
        self.assertIn('YALLAH_DB', ry_txt)
        self.assertIn('generateValue: true', ry_txt)

        # Vérifie l'auto-détection d'URL HTTPS PaaS (Render / Railway) pour production_check()
        with patch.dict(os.environ, {
            'YALLAH_ENV': 'production',
            'YALLAH_PUBLIC_URL': '',
            'RENDER_EXTERNAL_URL': 'https://yallah-services.onrender.com',
            'YALLAH_ADMIN_PASSWORD': 'mot-de-passe-admin-fort-12345',
        }, clear=False):
            webapp._autofill_cloud_public_url()
            self.assertEqual(os.environ['YALLAH_PUBLIC_URL'], 'https://yallah-services.onrender.com')
            access.production_check()

        # Si le serveur détient déjà le verrou SQLite, `webapp.py --open` quitte proprement (code 0)
        lock_handle = webapp.server_lock()
        try:
            env = dict(os.environ, YALLAH_DB=str(self.db_path), BROWSER='true')
            res = subprocess.run(
                [sys.executable, str(ROOT / 'webapp.py'), '--port', '8765', '--open'],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn('déjà actif', res.stdout)
        finally:
            lock_handle.close()


if __name__ == '__main__':
    unittest.main()
