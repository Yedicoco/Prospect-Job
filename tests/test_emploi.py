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

    def test_email_de_candidature_present_dans_les_trois_langues(self):
        for langue in ("fr", "darija", "arabe"):
            self.assertIn(ye.CONTACT_EMAIL, ye.annonce(besoin(), langue), langue)

    def test_lien_email_prefill_sujet_et_reference(self):
        lignes = ye.construire_lignes([besoin()], "fr", False)
        lien = lignes[0]["lien_email"]
        self.assertTrue(lien.startswith("mailto:" + ye.CONTACT_EMAIL))
        self.assertIn("EMP-001", lien)

    def test_decision_du_21_10_2026_aucun_frais_candidat(self):
        """Le renoncement aux 100 MAD est ecrit dans les annonces, sans montant."""
        self.assertEqual(ye.POLITIQUE_FRAIS, "aucun")
        for langue in ("fr", "darija", "arabe"):
            texte = ye.annonce(besoin(), langue)
            self.assertIn(ye.PHRASES_FRAIS["aucun"][langue], texte, langue)
            self.assertNotIn("100 MAD", texte, langue)
            self.assertNotIn("Des frais sont", texte, langue)

    def test_trois_langues_sans_alerte(self):
        for langue in ("fr", "darija", "arabe"):
            self.assertEqual(ye.verifier_annonce(ye.annonce(besoin(), langue)), [], langue)


class TestPolitiqueFrais(unittest.TestCase):
    """Trois politiques possibles, jamais devinees a la place de Yallah."""

    def setUp(self):
        self.avant = ye.POLITIQUE_FRAIS
        self.avant_valid = ye.FRAIS_CANDIDAT_VALIDATION

    def tearDown(self):
        ye.POLITIQUE_FRAIS = self.avant
        ye.FRAIS_CANDIDAT_VALIDATION = self.avant_valid

    def test_politique_aucun_ecrit_la_gratuite(self):
        ye.POLITIQUE_FRAIS = "aucun"
        texte = ye.annonce(besoin(), "fr")
        self.assertIn("Aucun frais", texte)

    def test_politique_aucun_ne_declenche_pas_le_garde_fou(self):
        ye.POLITIQUE_FRAIS = "aucun"
        ligne = ye.construire_lignes([besoin()], "fr", False)[0]
        self.assertEqual(ligne["alertes"], "")
        self.assertEqual(ligne["publiable"], "oui")

    def test_politique_factures_sans_montant_source_refuse_la_publication(self):
        ye.POLITIQUE_FRAIS = "factures"
        ligne = ye.construire_lignes([besoin()], "fr", False)[0]
        self.assertEqual(ligne["publiable"], "non")
        self.assertIn("frais", ligne["problemes"])

    def test_politique_factures_avec_montant_source_publie(self):
        ye.POLITIQUE_FRAIS = "factures"
        ye.FRAIS_CANDIDAT_VALIDATION = {"reference": "avis juridique de test", "date": "2026-11-01"}
        b = besoin(
            frais_montant={"valeur": "200 MAD", "source": "decision interne 21/10"},
            frais_moment={"valeur": "à l'inscription", "source": "decision interne 21/10"},
        )
        ligne = ye.construire_lignes([b], "fr", False)[0]
        self.assertEqual(ligne["publiable"], "oui")
        self.assertIn("200 MAD", ligne["annonce"])

    def test_montant_sans_source_napparait_pas(self):
        ye.POLITIQUE_FRAIS = "factures"
        b = besoin(frais_montant={"valeur": "200 MAD", "source": ""})
        self.assertNotIn("200 MAD", ye.annonce(b, "fr"))

    def test_politique_inconnue_est_signalee(self):
        ye.POLITIQUE_FRAIS = "peut-etre"
        self.assertTrue(ye.valider_besoin(besoin()))

    def test_la_politique_est_une_decision_datee_pas_un_defaut(self):
        """'aucun' resulte de la decision du 21/10/2026, pas d'une valeur par defaut."""
        self.assertEqual(ye.POLITIQUE_FRAIS, "aucun")
        self.assertIn("21/10/2026", open(ye.__file__, encoding="utf-8").read())


class TestVerrouJuridiqueFrais(unittest.TestCase):
    """Art. 480 du Code du travail : aucun frais candidat publie sans validation juridique."""

    def setUp(self):
        self.avant = ye.POLITIQUE_FRAIS
        self.avant_valid = ye.FRAIS_CANDIDAT_VALIDATION
        ye.POLITIQUE_FRAIS = "factures"
        ye.FRAIS_CANDIDAT_VALIDATION = None
        self.b = besoin(
            frais_montant={"valeur": "100 MAD", "source": "decision interne"},
            frais_moment={"valeur": "à l'inscription", "source": "decision interne"},
        )

    def tearDown(self):
        ye.POLITIQUE_FRAIS = self.avant
        ye.FRAIS_CANDIDAT_VALIDATION = self.avant_valid

    def test_verrou_actif_par_defaut(self):
        self.assertIsNone(ye.FRAIS_CANDIDAT_VALIDATION)

    def test_frais_bloques_sans_validation_juridique(self):
        ligne = ye.construire_lignes([self.b], "fr", False)[0]
        self.assertEqual(ligne["publiable"], "non")
        self.assertIn("article 480", ligne["problemes"])

    def test_montant_absent_du_texte_tant_que_le_verrou_est_actif(self):
        self.assertNotIn("100 MAD", ye.annonce(self.b, "fr"))

    def test_montant_publie_apres_validation_datee(self):
        ye.FRAIS_CANDIDAT_VALIDATION = {"reference": "avis juridique", "date": "2026-11-01"}
        ligne = ye.construire_lignes([self.b], "fr", False)[0]
        self.assertEqual(ligne["publiable"], "oui")
        self.assertIn("100 MAD", ligne["annonce"])

    def test_le_verrou_ne_bloque_pas_une_politique_sans_frais(self):
        ye.POLITIQUE_FRAIS = "aucun"
        ligne = ye.construire_lignes([besoin()], "fr", False)[0]
        self.assertEqual(ligne["publiable"], "oui")


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
