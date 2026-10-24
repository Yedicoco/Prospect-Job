"""Tests du module de prospection B2B (aucune dependance externe).

Lancement : python -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import yallah_prospection as yp  # noqa: E402


class TestGardeFou(unittest.TestCase):
    def test_message_propre(self):
        texte = (
            "Bonjour, nous mettons en relation les etablissements avec du personnel "
            "en permanent, temporaire ou renfort journalier."
        )
        self.assertEqual(yp.verifier_message(texte), [])

    def test_prix_detecte(self):
        self.assertTrue(yp.verifier_message("Nos tarifs commencent a 3 000 dh par mois."))

    def test_delai_detecte(self):
        self.assertTrue(yp.verifier_message("Nous vous trouvons quelqu'un en 48h."))

    def test_garantie_detectee(self):
        self.assertTrue(yp.verifier_message("Remplacement garanti sous 24h."))

    def test_verification_detectee(self):
        self.assertTrue(yp.verifier_message("Des profils verifies et experimentes."))

    def test_telephone_detecte(self):
        self.assertTrue(yp.verifier_message("Appelez-moi au 0661 23 45 67."))

    def test_gratuite_detectee(self):
        self.assertTrue(yp.verifier_message("Nous vous offrons un devis gratuit."))


class TestValidation(unittest.TestCase):
    def fiche_valide(self):
        return {
            "nom": "Test",
            "segment": "hotel",
            "ville": "Rabat",
            "zone": "Agdal",
            "source_url": "https://exemple.ma/contact",
            "date_consultation": "2026-10-21",
            "niveau": "A",
            "phase": 1,
            "tel": "+212 5 00 00 00 00",
        }

    def test_fiche_complete_ok(self):
        self.assertEqual(yp.valider_fiche(self.fiche_valide()), [])

    def test_source_manquante(self):
        f = self.fiche_valide()
        f["source_url"] = ""
        self.assertTrue(yp.valider_fiche(f))

    def test_date_mal_formee(self):
        f = self.fiche_valide()
        f["date_consultation"] = "21/10/2026"
        self.assertTrue(yp.valider_fiche(f))

    def test_phase_invalide(self):
        f = self.fiche_valide()
        f["phase"] = 4
        self.assertTrue(yp.valider_fiche(f))

    def test_segment_inconnu(self):
        f = self.fiche_valide()
        f["segment"] = "spa"
        self.assertTrue(yp.valider_fiche(f))

    def test_aucun_contact_sans_niveau_c(self):
        f = self.fiche_valide()
        f["tel"] = ""
        self.assertTrue(yp.valider_fiche(f))
        f["niveau"] = "C"
        self.assertEqual(yp.valider_fiche(f), [])


class TestPriorite(unittest.TestCase):
    def test_zone_phase_1(self):
        self.assertTrue(yp.zone_phase_1("Casablanca", "Anfa"))
        self.assertTrue(yp.zone_phase_1("Marrakech", "Palmeraie"))
        self.assertFalse(yp.zone_phase_1("Casablanca", "Maarif"))

    def test_phase_deduite_de_la_ville(self):
        self.assertEqual(yp.phase_de({"ville": "Tanger"}), 2)
        self.assertEqual(yp.phase_de({"ville": "El Jadida"}), 3)
        self.assertEqual(yp.phase_de({"ville": "Rabat"}), 1)

    def test_phase_declaree_prime(self):
        self.assertEqual(yp.phase_de({"ville": "Tanger", "phase": 1}), 1)

    def test_hotel_en_zone_classe_au_dessus(self):
        base = {
            "segment": "hotel",
            "ville": "Rabat",
            "zone": "Agdal",
            "niveau": "A",
        }
        hors_zone = dict(base, zone="Hors zone phase 1")
        self.assertGreater(yp.priorite(base)[0], yp.priorite(hors_zone)[0])


class TestJeuDeDonnees(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RACINE, "prospects_b2b.json"), encoding="utf-8") as f:
            self.prospects = json.load(f)["prospects"]

    def test_toutes_les_fiches_sources(self):
        for p in self.prospects:
            self.assertEqual(yp.valider_fiche(p), [], p.get("nom"))

    def test_messages_generes_sans_alerte(self):
        for p in self.prospects:
            for langue in ("fr", "darija", "arabe"):
                texte = yp.message_commercial(p, langue)
                self.assertEqual(yp.verifier_message(texte), [], f"{p['nom']} ({langue})")

    def test_aucun_numero_ecrit_dans_les_messages(self):
        for p in self.prospects:
            texte = yp.message_commercial(p, "fr")
            self.assertNotIn("212691733585", texte)

    def test_site_web_officiel_inclus_dans_messages_et_lien(self):
        for p in self.prospects:
            for langue in ("fr", "darija", "arabe"):
                texte = yp.message_commercial(p, langue)
                self.assertIn("https://yallahservices-one.vercel.app", texte)
            self.assertIn("yallahservices-one.vercel.app", yp.lien_whatsapp(p))

    def test_garde_fou_bloque_url_inventee_mais_autorise_site_officiel(self):
        self.assertEqual(
            yp.verifier_message("Decouvrez nos services sur https://yallahservices-one.vercel.app"),
            [],
        )
        self.assertEqual(
            yp.verifier_message("Site : https://yallahservices-one.vercel.app/index.html"),
            [],
        )
        alertes = yp.verifier_message("Visitez https://faux-site-yallah.ma pour en savoir plus.")
        self.assertTrue(any("url non officielle" in a for a in alertes), alertes)


if __name__ == "__main__":
    unittest.main()
