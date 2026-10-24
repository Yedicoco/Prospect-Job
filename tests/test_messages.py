#!/usr/bin/env python3
"""Tests du moteur de messages (B2B + B2C)."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import date

RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import yallah_messages as ym  # noqa: E402


def fiche(**remplacements):
    base = {
        "nom": "Famille Test",
        "besoin": "MEN",
        "ville": "Casablanca",
        "zone": "Anfa",
        "tel": "+212 600 00 00 00",
        "email": "",
        "source_url": "https://exemple.invalid/annonce/1",
        "date_consultation": "2026-10-21",
        "niveau": "A",
    }
    base.update(remplacements)
    return base


def jeu(fiches, refus=None):
    return {"meta": {"refus": refus or []}, "prospects": fiches}


AUJOURDHUI = date(2026, 10, 21)


class TestSourcesReelles(unittest.TestCase):
    def setUp(self):
        self.b2b = ym.charger(str(RACINE / "prospects_b2b.json"))
        self.b2c = ym.charger(str(RACINE / "prospects_b2c.json"))
        self.lignes = ym.construire_lignes(
            [("b2b", self.b2b), ("b2c", self.b2c)], "fr", "Youssef", AUJOURDHUI)

    def test_les_deux_fichiers_existent_et_sont_separes(self):
        self.assertEqual(len(self.b2b["prospects"]), 48)
        self.assertIn("prospects", self.b2c)

    def test_toutes_les_fiches_b2b_traitees(self):
        self.assertEqual(sum(1 for l in self.lignes if l["type"] == "b2b"), 48)

    def test_seule_la_fiche_sans_contact_direct_est_rejetee(self):
        rejetes = [l for l in self.lignes if l["statut"] == "NON QUALIFIE" and l["type"] == "b2b"]
        self.assertEqual(len(rejetes), 1)
        self.assertIn("formulaire", rejetes[0]["motifs_non_qualification"])

    def test_la_fiche_exemple_b2c_n_est_jamais_envoyee(self):
        exemple = [l for l in self.lignes if l["type"] == "b2c"][0]
        self.assertEqual(exemple["statut"], "NON QUALIFIE")
        self.assertIn("exemple", exemple["motifs_non_qualification"])

    def test_aucun_message_ne_part_avec_une_alerte(self):
        for ligne in self.lignes:
            if ligne["statut"] == "PRET - envoi manuel":
                self.assertEqual(ligne["alertes"], "", ligne["ref"])

    def test_toutes_les_fiches_qualifiees_recoivent_un_message(self):
        prets = [l for l in self.lignes if l["statut"] == "PRET - envoi manuel"]
        self.assertEqual(len(prets), 47)
        for ligne in prets:
            self.assertIn("Yallah Services", ligne["message"])
            self.assertNotIn(ym.PLACEHOLDER_PRENOM, ligne["message"])

    def test_plan_d_envoi_respecte_la_cadence(self):
        prets = [l for l in self.lignes if l["statut"] == "PRET - envoi manuel"]
        par_jour = {}
        for ligne in prets:
            par_jour[ligne["jour"]] = par_jour.get(ligne["jour"], 0) + 1
        self.assertTrue(all(n <= ym.MAX_PAR_JOUR for n in par_jour.values()), par_jour)
        self.assertEqual(sum(par_jour.values()), len(prets))


class TestQualification(unittest.TestCase):
    def qualifier(self, p, refus=None, contacts=None):
        return ym.qualifier(p, "b2c", contacts if contacts is not None else {},
                            set(refus or []), AUJOURDHUI)

    def test_fiche_complete_qualifiee(self):
        verdict = self.qualifier(fiche())
        self.assertTrue(verdict["qualifie"], verdict)

    def test_fiche_sans_source_refusee(self):
        verdict = self.qualifier(fiche(source_url=""))
        self.assertFalse(verdict["qualifie"])
        self.assertIn("champ manquant : source_url", verdict["motifs"])

    def test_source_non_url_refusee(self):
        verdict = self.qualifier(fiche(source_url="vu sur facebook"))
        self.assertFalse(verdict["qualifie"])

    def test_date_mal_formee_refusee(self):
        verdict = self.qualifier(fiche(date_consultation="21/10/2026"))
        self.assertFalse(verdict["qualifie"])

    def test_besoin_inconnu_refuse(self):
        verdict = self.qualifier(fiche(besoin="PIZZA"))
        self.assertFalse(verdict["qualifie"])

    def test_niveau_c_refuse(self):
        verdict = self.qualifier(fiche(tel="", email="", niveau="C"))
        self.assertFalse(verdict["qualifie"])

    def test_registre_des_refus_respecte(self):
        verdict = self.qualifier(fiche(), refus={"tel:212600000000"})
        self.assertFalse(verdict["qualifie"])
        self.assertIn("refus", verdict["motifs"][0])

    def test_doublon_de_contact_detecte_entre_b2b_et_b2c(self):
        contacts = {"tel:212600000000": "Un hotel"}
        verdict = self.qualifier(fiche(), contacts=contacts)
        self.assertFalse(verdict["qualifie"])
        self.assertIn("doublon", verdict["motifs"][0])

    def test_source_perimee_bloquante(self):
        verdict = self.qualifier(fiche(date_consultation="2025-01-01",
                                       date_derniere_verification="2026-10-21"))
        self.assertTrue(verdict["qualifie"])
        self.assertTrue(any("reconfirmer" in a for a in verdict["alertes"]))

    def test_fiche_non_verifiee_aujourdhui_non_envoyable(self):
        """Actualisation quotidienne : une fiche non revérifiée aujourd'hui est bloquée."""
        verdict = self.qualifier(fiche(date_derniere_verification="2026-10-20"))
        self.assertFalse(verdict["qualifie"])
        self.assertIn("actualisation", verdict["motifs"][0])

    def test_fiche_verifiee_aujourdhui_envoyable(self):
        verdict = self.qualifier(fiche(date_derniere_verification="2026-10-21"))
        self.assertTrue(verdict["qualifie"], verdict)

    def test_niveau_b_est_une_reserve_pas_un_blocage(self):
        verdict = self.qualifier(fiche(niveau="B"))
        self.assertTrue(verdict["qualifie"])
        self.assertEqual(verdict["alertes"], [])
        self.assertTrue(verdict["reserves"])


class TestMessages(unittest.TestCase):
    def setUp(self):
        self.b2b = ym.charger(str(RACINE / "prospects_b2b.json"))["prospects"]
        self.b2c = fiche()

    def test_aucune_alerte_sur_les_48_fiches_dans_les_trois_langues(self):
        for p in self.b2b:
            for langue in ("fr", "darija", "arabe"):
                texte = ym.generer_message(p, "b2b", langue, "Youssef")
                self.assertEqual(ym.verifier_message(texte), [], f"{p['nom']} ({langue})")

    def test_formule_de_retrait_obligatoire(self):
        alertes = ym.verifier_message("Bonjour, nous proposons du personnel.")
        self.assertIn("formule de retrait absente", alertes)
        for langue in ("fr", "darija", "arabe"):
            texte = ym.generer_message(self.b2c, "b2c", langue, "Youssef")
            self.assertNotIn("formule de retrait absente", ym.verifier_message(texte), langue)

    def test_aucun_prix_ni_numero_dans_les_messages(self):
        for p in self.b2b:
            texte = ym.generer_message(p, "b2b", "fr", "Youssef")
            self.assertNotIn("+212", texte)
            self.assertNotIn("dh", texte.lower())
            self.assertNotIn("MAD", texte)

    def test_message_b2c_parle_du_besoin_et_de_la_zone(self):
        texte = ym.generer_message(self.b2c, "b2c", "fr", "Youssef")
        self.assertIn("femme de ménage", texte)
        self.assertIn("Anfa", texte)
        self.assertNotIn("établissements", texte)

    def test_message_trop_long_detecte(self):
        texte = ym.generer_message(self.b2c, "b2c", "fr", "Youssef") + " a" * 600
        self.assertTrue(any("trop long" in a for a in ym.verifier_message(texte)))

    def test_pression_commerciale_detectee(self):
        self.assertTrue(ym.verifier_message(
            "Dernière chance, je ne vous relancerai pas."))
        self.assertTrue(ym.verifier_message(
            "Remise de 20 % et je ne vous relancerai pas."))


class TestLiens(unittest.TestCase):
    def test_pas_de_lien_sans_prenom(self):
        p = fiche()
        texte = ym.generer_message(p, "b2c", "fr")
        self.assertIn(ym.PLACEHOLDER_PRENOM, texte)
        self.assertEqual(ym.lien_whatsapp(p, texte), "")
        self.assertEqual(ym.lien_email(p, texte, "b2c"), "")

    def test_lien_whatsapp_construit_avec_le_message(self):
        p = fiche()
        texte = ym.generer_message(p, "b2c", "fr", "Youssef")
        lien = ym.lien_whatsapp(p, texte)
        self.assertTrue(lien.startswith("https://wa.me/212600000000?text="))
        self.assertNotIn(" ", lien)

    def test_lien_email_pour_fiche_sans_telephone(self):
        p = fiche(tel="", email="f.amrani@exemple.invalid")
        texte = ym.generer_message(p, "b2c", "fr", "Youssef")
        lien = ym.lien_email(p, texte, "b2c")
        self.assertTrue(lien.startswith("mailto:f.amrani@exemple.invalid?subject="))


class TestAucunEnvoi(unittest.TestCase):
    def test_le_module_n_importe_aucune_bibliotheque_reseau(self):
        source = (RACINE / "yallah_messages.py").read_text(encoding="utf-8")
        for interdit in ("import requests", "import smtplib", "import socket",
                         "twilio", "selenium", "urllib.request", "openai", "anthropic"):
            self.assertNotIn(interdit, source, interdit)

    def test_option_envoyer_refusee(self):
        resultat = subprocess.run(
            [sys.executable, "yallah_messages.py", "--envoyer"],
            cwd=str(RACINE), capture_output=True, text=True)
        self.assertNotEqual(resultat.returncode, 0)
        self.assertIn("Envoi automatique refuse", resultat.stdout + resultat.stderr)

    def test_check_sort_un_code_retour_exploitable(self):
        resultat = subprocess.run(
            [sys.executable, "yallah_messages.py", "--check"],
            cwd=str(RACINE), capture_output=True, text=True)
        self.assertEqual(resultat.returncode, 0, resultat.stdout + resultat.stderr)
        self.assertIn("fiche(s)", resultat.stdout)

    def test_generation_ecrit_csv_et_markdown(self):
        with tempfile.TemporaryDirectory() as dossier:
            src_path = os.path.join(dossier, "b2c.json")
            csv_path = os.path.join(dossier, "file.csv")
            md_path = os.path.join(dossier, "file.md")
            pathlib.Path(src_path).write_text(
                json.dumps(jeu([fiche(date_consultation=date.today().isoformat())]),
                           ensure_ascii=False), encoding="utf-8")
            resultat = subprocess.run(
                [sys.executable, "yallah_messages.py", "--type", "b2c",
                 "--source-b2c", src_path, "--prenom", "Youssef",
                 "--sortie", csv_path, "--markdown", md_path],
                cwd=str(RACINE), capture_output=True, text=True)
            self.assertEqual(resultat.returncode, 0, resultat.stderr)
            contenu = pathlib.Path(csv_path).read_text(encoding="utf-8-sig")
            self.assertIn("lien_whatsapp", contenu.splitlines()[0])
            self.assertIn("PRE", contenu)
            self.assertIn("Jour 1", pathlib.Path(md_path).read_text(encoding="utf-8"))


class TestActualisationQuotidienne(unittest.TestCase):
    def test_checklist_du_jour_et_estamplillage(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "b2c.json")
            pathlib.Path(chemin).write_text(
                json.dumps(jeu([fiche(date_consultation="2026-10-19"),
                                fiche(tel="+212 700 00 00 00", nom="Autre famille",
                                      date_consultation="2026-10-19")]),
                           ensure_ascii=False), encoding="utf-8")

            hier = date(2026, 10, 20)
            lignes = ym.construire_lignes([("b2c", ym.charger(chemin))], "fr", "Youssef", hier)
            self.assertTrue(all(l["statut"] == "A ACTUALISER" for l in lignes))

            md = os.path.join(dossier, "actu.md")
            n = ym.ecrire_actualisation(md, lignes, hier)
            self.assertEqual(n, 2)
            texte = pathlib.Path(md).read_text(encoding="utf-8")
            self.assertIn("2026-10-20", texte)
            self.assertIn("BC-001", texte)
            self.assertIn("--verifie", texte)

            marquees = ym.marquer_verifie({"b2c": chemin}, ["BC-001"], hier)
            self.assertEqual(marquees, ["BC-001"])
            donnees = json.loads(pathlib.Path(chemin).read_text(encoding="utf-8"))
            self.assertEqual(donnees["prospects"][0]["date_derniere_verification"], "2026-10-20")
            self.assertNotIn("date_derniere_verification", donnees["prospects"][1])
            self.assertEqual(donnees["meta"]["date_maj"], "2026-10-20")

            lignes = ym.construire_lignes([("b2c", ym.charger(chemin))], "fr", "Youssef", hier)
            self.assertEqual(lignes[0]["statut"], "PRET - envoi manuel")
            self.assertEqual(lignes[1]["statut"], "A ACTUALISER")

    def test_reference_inconnue_ignoree(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "b2c.json")
            pathlib.Path(chemin).write_text(json.dumps(jeu([fiche()]), ensure_ascii=False),
                                            encoding="utf-8")
            self.assertEqual(ym.marquer_verifie({"b2c": chemin}, ["BC-999"], AUJOURDHUI), [])

    def test_fiches_non_qualifiees_restent_non_qualifiees_apres_changement_de_jour(self):
        lendemain = date(2026, 10, 25)
        donnees = jeu(
            [
                fiche(nom="Contact en refus", tel="+212 611 11 11 11", date_consultation="2026-10-21"),
                fiche(nom="Fiche exemple", tel="+212 622 22 22 22", exemple=True, date_consultation="2026-10-21"),
                fiche(nom="Formulaire seul", tel="", email="", niveau="C", date_consultation="2026-10-21"),
                fiche(nom="Prospect valide ancien", tel="+212 633 33 33 33", date_consultation="2026-10-21"),
            ],
            refus=["+212 611 11 11 11"],
        )
        lignes = ym.construire_lignes([("b2c", donnees)], "fr", "Youssef", lendemain)
        par_nom = {l["nom"]: l["statut"] for l in lignes}
        self.assertEqual(par_nom["Contact en refus"], "NON QUALIFIE")
        self.assertEqual(par_nom["Fiche exemple"], "NON QUALIFIE")
        self.assertEqual(par_nom["Formulaire seul"], "NON QUALIFIE")
        self.assertEqual(par_nom["Prospect valide ancien"], "A ACTUALISER")
        with tempfile.TemporaryDirectory() as dossier:
            md = os.path.join(dossier, "actu.md")
            self.assertEqual(ym.ecrire_actualisation(md, lignes, lendemain), 1)
            texte = pathlib.Path(md).read_text(encoding="utf-8")
            self.assertNotIn("Contact en refus", texte)
            self.assertIn("Prospect valide ancien", texte)


class TestJeuB2C(unittest.TestCase):
    def test_une_fiche_b2c_valide_produit_un_message_pret(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "b2c.json")
            pathlib.Path(chemin).write_text(
                json.dumps(jeu([fiche()]), ensure_ascii=False), encoding="utf-8")
            donnees = ym.charger(chemin)
            lignes = ym.construire_lignes([("b2c", donnees)], "darija", "Youssef", AUJOURDHUI)
            self.assertEqual(lignes[0]["statut"], "PRET - envoi manuel")
            self.assertEqual(lignes[0]["canal"], "whatsapp")
            self.assertEqual(lignes[0]["jour"], 1)
            self.assertIn("Salam", lignes[0]["message"])

    def test_score_b2c_plus_eleve_en_zone_phase_1(self):
        dedans = ym.score_prospect(fiche(zone="Anfa", ville="Casablanca"), "b2c")[0]
        dehors = ym.score_prospect(fiche(zone="Hay Hassani", ville="Casablanca"), "b2c")[0]
        self.assertGreater(dedans, dehors)

    def test_site_web_officiel_inclus_dans_messages_b2b_b2c_et_suivi_client(self):
        site = "https://yallahservices-one.vercel.app"
        prospect_b2b = {
            "nom": "Hotel Test",
            "segment": "hotel",
            "phase": 1,
            "ville": "Casablanca",
            "zone": "Anfa",
            "tel": "+212 522 00 11 22",
            "email": "contact@hoteltest.ma",
            "source_url": "https://hoteltest.ma/contact",
            "date_consultation": AUJOURDHUI.isoformat(),
            "niveau": "A",
        }
        prospect_b2c_entrant = fiche(source_type="entrant", source_url="", source_reference="ENT-1")
        for langue in ("fr", "darija", "arabe"):
            msg_b2b = ym.generer_message(prospect_b2b, "b2b", langue, "Youssef")
            msg_b2c = ym.generer_message(fiche(), "b2c", langue, "Youssef")
            msg_entrant = ym.generer_message(prospect_b2c_entrant, "b2c", langue, "Youssef")
            msg_suivi_b2b = ym.message_client_suivi(
                prospect_b2b, "b2b", langue, "Youssef", "Renfort salle", "Point telephonique"
            )
            msg_suivi_b2c = ym.message_client_suivi(
                fiche(), "b2c", langue, "Youssef", "Nounou Anfa", "Confirmer horaires"
            )
            for texte in (msg_b2b, msg_b2c, msg_entrant, msg_suivi_b2b, msg_suivi_b2c):
                self.assertIn(site, texte, langue)
                self.assertEqual(ym.verifier_message(texte), [], langue)
            self.assertIn("yallahservices-one.vercel.app", ym.lien_whatsapp(fiche(), msg_b2c))
            self.assertIn("yallahservices-one.vercel.app", ym.lien_email(prospect_b2b, msg_b2b, "b2b"))

    def test_url_non_officielle_bloquee_par_garde_fou(self):
        texte = ym.generer_message(fiche(), "b2c", "fr", "Youssef").replace(
            "https://yallahservices-one.vercel.app", "https://site-invente.example.com"
        )
        alertes = ym.verifier_message(texte)
        self.assertTrue(any("url non officielle" in a for a in alertes), alertes)


if __name__ == "__main__":
    unittest.main()
