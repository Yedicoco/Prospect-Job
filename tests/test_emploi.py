"""Tests du module offre d'emploi (aucune dependance externe).

Lancement : python -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

import yallah_emploi as ye  # noqa: E402


def besoin(**extra):
    base = {
        "ref": "EMP-001",
        "metier": "MEN",
        "ville": "Rabat",
        "zone": "Agdal",
        "format": "permanent",
        "statut": "ouvert",
        "source_confirmation": "client, email du 21/10/2026",
        "date_confirmation": "2026-10-21",
        "remuneration": {"valeur": "", "source": ""},
        "horaires": {"valeur": "", "source": ""},
    }
    base.update(extra)
    return base


class TestGardeFouEmploi(unittest.TestCase):
    def test_annonce_propre(self):
        self.assertEqual(ye.verifier_annonce(ye.annonce(besoin(), "fr")), [])

    def test_urgence_bloquee(self):
        self.assertTrue(ye.verifier_annonce("Poste urgent, disponible immédiatement."))

    def test_promesse_embauche_bloquee(self):
        self.assertTrue(ye.verifier_annonce("Poste garanti pour vous."))

    def test_salaire_attractif_bloque(self):
        self.assertTrue(ye.verifier_annonce("Salaire attractif et bien payé."))

    def test_exigence_non_confirmee_bloquee(self):
        self.assertTrue(ye.verifier_annonce("Expérience requise : minimum 2 ans."))

    def test_gratuite_bloquee(self):
        self.assertTrue(ye.verifier_annonce("Inscription gratuite, sans frais."))

    def test_contrat_non_confirme_bloque(self):
        self.assertTrue(ye.verifier_annonce("Nous proposons un CDI."))

    def test_telephone_dans_le_texte_bloque(self):
        self.assertTrue(ye.verifier_annonce("Appelez le 0661 23 45 67."))


class TestValeurSourcee(unittest.TestCase):
    def test_valeur_sans_source_refusee(self):
        b = besoin(remuneration={"valeur": "4 500 MAD", "source": ""})
        self.assertEqual(ye.lire_champ_source(b, "remuneration"), (None, None))

    def test_valeur_sans_source_napparait_pas(self):
        b = besoin(remuneration={"valeur": "4 500 MAD", "source": ""})
        self.assertNotIn("4 500", ye.annonce(b, "fr"))
        self.assertIn("non communiquée", ye.annonce(b, "fr"))

    def test_valeur_sourcee_apparait(self):
        b = besoin(remuneration={"valeur": "4 500 MAD", "source": "client, email 21/10"})
        self.assertIn("4 500 MAD", ye.annonce(b, "fr"))

    def test_valeur_sourcee_ne_declenche_pas_le_garde_fou(self):
        b = besoin(remuneration={"valeur": "4 500 MAD", "source": "client"})
        texte = ye.annonce(b, "fr")
        masque = ye.masquer(["4 500 MAD"], texte)
        self.assertEqual(ye.verifier_annonce(masque), [])

    def test_valeur_sans_source_rend_le_besoin_non_publiable(self):
        b = besoin(horaires={"valeur": "08h-17h", "source": ""})
        self.assertTrue(ye.valider_besoin(b))


class TestValidation(unittest.TestCase):
    def test_besoin_complet_ok(self):
        self.assertEqual(ye.valider_besoin(besoin()), [])

    def test_sans_source_confirmation(self):
        self.assertTrue(ye.valider_besoin(besoin(source_confirmation="")))

    def test_metier_inconnu(self):
        self.assertTrue(ye.valider_besoin(besoin(metier="ASTRONAUTE")))

    def test_format_inconnu(self):
        self.assertTrue(ye.valider_besoin(besoin(format="stage")))

    def test_statut_non_ouvert(self):
        self.assertTrue(ye.valider_besoin(besoin(statut="pourvu")))

    def test_date_mal_formee(self):
        self.assertTrue(ye.valider_besoin(besoin(date_confirmation="21/10/2026")))


class TestPublication(unittest.TestCase):
    def test_exemple_jamais_publiable(self):
        lignes = ye.construire_lignes([besoin(exemple=True)], "fr", avec_exemples=True)
        self.assertEqual(lignes[0]["publiable"], "non")

    def test_exemple_exclu_par_defaut(self):
        self.assertEqual(ye.construire_lignes([besoin(exemple=True)], "fr", False), [])

    def test_besoin_complet_publiable(self):
        lignes = ye.construire_lignes([besoin()], "fr", False)
        self.assertEqual(lignes[0]["publiable"], "oui")

    def test_informations_non_communiquees_signalees(self):
        lignes = ye.construire_lignes([besoin()], "fr", False)
        self.assertIn("rémunération", lignes[0]["informations_non_communiquees"])

    def test_lien_whatsapp_contient_la_reference(self):
        lignes = ye.construire_lignes([besoin()], "fr", False)
        self.assertIn("EMP-001", lignes[0]["lien_whatsapp"])

    def test_trois_langues_sans_alerte(self):
        for langue in ("fr", "darija", "arabe"):
            self.assertEqual(ye.verifier_annonce(ye.annonce(besoin(), langue)), [], langue)


class TestFichierFourni(unittest.TestCase):
    def test_le_fichier_ne_contient_aucun_besoin_reel(self):
        """Tant qu'aucun employeur n'a confirme de besoin, seules des fiches d'exemple existent."""
        with open(os.path.join(RACINE, "besoins_emploi.json"), encoding="utf-8") as f:
            besoins = json.load(f)["besoins"]
        for b in besoins:
            self.assertTrue(b.get("exemple"), f"{b.get('ref')} n'est pas marque exemple")

    def test_aucune_fiche_du_fichier_nest_publiable(self):
        with open(os.path.join(RACINE, "besoins_emploi.json"), encoding="utf-8") as f:
            besoins = json.load(f)["besoins"]
        lignes = ye.construire_lignes(besoins, "fr", avec_exemples=True)
        self.assertTrue(all(l["publiable"] == "non" for l in lignes))


if __name__ == "__main__":
    unittest.main()
