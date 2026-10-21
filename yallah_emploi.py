#!/usr/bin/env python3
"""
Yallah Services - Module OFFRE D'EMPLOI (v1)

A quoi sert ce script :
  transformer un besoin de recrutement REELLEMENT confirme par un employeur
  en une annonce destinee aux CANDIDATS.

Ce que ce module n'est pas :
  ce n'est pas le module commercial (yallah_prospection.py). Une annonce
  d'emploi ne s'envoie JAMAIS aux 48 etablissements du fichier de prospection :
  ce sont des clients, pas des candidats.

Regle de base : le script ne peut pas inventer.
  - un besoin sans source de confirmation n'est pas publiable ;
  - une valeur chiffree (remuneration, horaires) sans source n'apparait pas ;
  - le garde-fou bloque salaire non source, urgence, promesse d'embauche,
    exigence de diplome ou d'experience, gratuite annoncee, numero ecrit.

Utilisation :
  python yallah_emploi.py --check                 # validation, code retour 1 si probleme
  python yallah_emploi.py --avec-exemples         # apercu incluant la fiche d'exemple
  python yallah_emploi.py --langue darija
  python yallah_emploi.py --ref EMP-001 --langue arabe
"""

import argparse
import csv
import json
import os
import re
import sys
from urllib.parse import quote

from yallah_b2c import BESOINS as BESOINS_B2C
from yallah_b2c import PATTERNS_INTERDITS as PATTERNS_B2C
from yallah_b2c import WHATSAPP_NUMBER

SOURCE_PAR_DEFAUT = "besoins_emploi.json"
DATE_ATTENDUE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# Metiers : vocabulaire de la fiche (B2C) + metiers d'execution cote entreprises
# ---------------------------------------------------------------------------
METIERS = dict(BESOINS_B2C)
METIERS.update({
    "SRV": "serveur / extra de service",
    "PLG": "plongeur",
    "NET": "agent de nettoyage de fin de chantier",
    "COM": "vendeur / employe de commerce",
})

FORMATS = {
    "permanent": "poste permanent",
    "temporaire": "mission temporaire",
    "renfort journalier": "renfort journalier",
}

# Champs dont une valeur chiffree doit toujours etre sourcee.
CHAMPS_SOURCES = ("remuneration", "horaires")

CHAMPS_REQUIS = ["ref", "metier", "ville", "zone", "format"]

# ---------------------------------------------------------------------------
# Garde-fou propre a l'annonce d'emploi
# ---------------------------------------------------------------------------
PATTERNS_SPECIFIQUES = [
    (r"\b(urgent|urgence|des que possible|au plus vite)\b", "urgence commerciale"),
    (r"\b(salaire attractif|tres bon salaire|bien paye|remuneration interessante)\b", "promesse de remuneration"),
    (r"\b(embauche (immediate|garantie)|poste garanti|nous vous garantissons un poste)\b", "promesse d'embauche"),
    (r"\b(experience (exigee|requise)|minimum \d+ ans?|diplome (exige|requis)|bac \+ ?\d)\b", "exigence non confirmee"),
    (r"\b(places limitees?|derniere chance|nombre de places limite)\b", "pression a la candidature"),
    (r"\b(sans frais|aucun frais|totalement gratuit|inscription gratuite)\b", "gratuite annoncee"),
    (r"\b(cdi|cdd)\b", "qualification contractuelle non confirmee"),
]

PATTERNS_INTERDITS = PATTERNS_B2C + PATTERNS_SPECIFIQUES


def verifier_annonce(texte: str) -> list:
    alertes = []
    bas = (texte or "").lower()
    for motif, libelle in PATTERNS_INTERDITS:
        trouve = re.search(motif, bas, flags=re.IGNORECASE)
        if trouve:
            alertes.append(f"{libelle} : « {trouve.group(0).strip()} »")
    return alertes


# ---------------------------------------------------------------------------
# Lecture d'un champ "valeur + source"
# ---------------------------------------------------------------------------
def lire_champ_source(besoin: dict, champ: str) -> tuple:
    """Retourne (valeur, source). Une valeur sans source est refusee."""
    bloc = besoin.get(champ) or {}
    valeur = str(bloc.get("valeur", "")).strip()
    source = str(bloc.get("source", "")).strip()
    if valeur and not source:
        return None, None
    return valeur, source


def masquer(valeurs: list, texte: str) -> str:
    """Neutralise les valeurs sourcees avant le passage du garde-fou."""
    for i, v in enumerate(valeurs):
        if v:
            texte = texte.replace(v, f"[VALEUR-SOURCEE-{i}]")
    return texte


def demasquer(valeurs: list, texte: str) -> str:
    for i, v in enumerate(valeurs):
        if v:
            texte = texte.replace(f"[VALEUR-SOURCEE-{i}]", v)
    return texte


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def valider_besoin(b: dict) -> list:
    problemes = []
    for champ in CHAMPS_REQUIS:
        if not str(b.get(champ, "")).strip():
            problemes.append(f"champ manquant : {champ}")

    if b.get("metier") and b["metier"] not in METIERS:
        problemes.append(f"metier inconnu : {b['metier']}")

    if b.get("format") and b["format"] not in FORMATS:
        problemes.append(f"format inconnu : {b['format']}")

    if not b.get("exemple"):
        if not str(b.get("source_confirmation", "")).strip():
            problemes.append("aucune source de confirmation : besoin non publiable")
        date = str(b.get("date_confirmation", ""))
        if date and not DATE_ATTENDUE.match(date):
            problemes.append("date_confirmation attendue au format AAAA-MM-JJ")
        if b.get("statut") != "ouvert":
            problemes.append("statut non ouvert")

    for champ in CHAMPS_SOURCES:
        bloc = b.get(champ) or {}
        if str(bloc.get("valeur", "")).strip() and not str(bloc.get("source", "")).strip():
            problemes.append(f"{champ} sans source : valeur refusee")

    return problemes


# ---------------------------------------------------------------------------
# Redaction de l'annonce
# ---------------------------------------------------------------------------
LIGNES_NON_COMMUNIQUEES = {
    "fr": {
        "remuneration": "non communiquée dans cette annonce",
        "horaires": "non communiqués dans cette annonce",
    },
    "darija": {
        "remuneration": "ma t3atatnach f had l3lan",
        "horaires": "ma t3atawch f had l3lan",
    },
    "arabe": {
        "remuneration": "غير مذكور في هذا الإعلان",
        "horaires": "غير مذكورة في هذا الإعلان",
    },
}


def annonce(b: dict, langue: str) -> str:
    metier = METIERS.get(b.get("metier", ""), b.get("metier", ""))
    format_libelle = FORMATS.get(b.get("format", ""), b.get("format", ""))
    ville, zone = b.get("ville", ""), b.get("zone", "")
    ref = b.get("ref", "")

    remuneration, _ = lire_champ_source(b, "remuneration")
    horaires, _ = lire_champ_source(b, "horaires")
    defauts = LIGNES_NON_COMMUNIQUEES.get(langue, LIGNES_NON_COMMUNIQUEES["fr"])
    ligne_rem = remuneration or defauts["remuneration"]
    ligne_hor = horaires or defauts["horaires"]
    # La phrase de confirmation n'apparait que si le besoin est reellement adosse a une source.
    confirme = bool(str(b.get("source_confirmation", "")).strip())

    if langue == "fr":
        return (
            f"{metier.capitalize()} — {ville} ({zone})\n\n"
            f"Type de besoin : {format_libelle}.\n"
            f"Horaires : {ligne_hor}.\n"
            f"Rémunération : {ligne_rem}.\n\n"
            f"Yallah Services met en relation des employeurs et des candidats au Maroc."
            + (" Ce besoin a été confirmé par un employeur ; les éléments ci-dessus sont "
               "ceux qu'il a communiqués, sans ajout de notre part." if confirme else "")
            + "\n\n"
            f"Pour proposer votre candidature, écrivez sur WhatsApp en précisant la "
            f"référence {ref} et le poste."
        )

    if langue == "darija":
        return (
            f"{metier.capitalize()} — {ville} ({zone})\n\n"
            f"Naw3 lkhedma : {format_libelle}.\n"
            f"Lwqiyat : {ligne_hor}.\n"
            f"L2ajr : {ligne_rem}.\n\n"
            f"Yallah Services kantwesel bin l2arbab lkhedma w lkandidates f lMaghrib."
            + (" Had lkhdma m2ekda mn 3and chi mchghl, w lma3lomat li foq hiya li 3tana, "
               "bla ma nzido 7ta haja mn 3andna." if confirme else "")
            + "\n\n"
            f"Ila bghiti t9edem, sift message f WhatsApp w kteb fih raqm {ref} w smit lkhedma."
        )

    return (
        f"{metier} — {ville} ({zone})\n\n"
        f"نوع الحاجة: {format_libelle}.\n"
        f"التوقيت: {ligne_hor}.\n"
        f"الأجر: {ligne_rem}.\n\n"
        f"Yallah Services تعمل على الربط بين أصحاب العمل والمرشحين في المغرب."
        + (" هذه الحاجة مؤكدة من طرف صاحب عمل، والمعطيات أعلاه هي التي قدمها دون أي إضافة منا."
           if confirme else "")
        + "\n\n"
        f"لتقديم ترشيحك، أرسل رسالة على واتساب مع ذكر المرجع {ref} والمنصب."
    )


def lien_whatsapp(b: dict) -> str:
    metier = METIERS.get(b.get("metier", ""), b.get("metier", ""))
    message = f"Bonjour, je souhaite postuler au poste de {metier} (réf {b.get('ref', '')})."
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}"


# ---------------------------------------------------------------------------
# Construction des lignes
# ---------------------------------------------------------------------------
COLONNES = [
    "ref", "poste", "ville", "zone", "format", "statut", "publiable",
    "remuneration", "horaires", "informations_non_communiquees", "annonce",
    "alertes", "problemes", "source_confirmation", "date_confirmation", "lien_whatsapp",
]


def construire_lignes(besoins: list, langue: str, avec_exemples: bool) -> list:
    lignes = []
    for b in besoins:
        exemple = bool(b.get("exemple"))
        if exemple and not avec_exemples:
            continue

        problemes = valider_besoin(b)
        if exemple:
            problemes.append("fiche d'exemple : non publiable")

        texte = annonce(b, langue)

        remun, _ = lire_champ_source(b, "remuneration")
        hor, _ = lire_champ_source(b, "horaires")
        valeurs_sourcees = [v for v in (remun, hor) if v]
        alertes = verifier_annonce(masquer(valeurs_sourcees, texte))
        texte = demasquer(valeurs_sourcees, texte)

        non_communique = [lib for lib, v in (("rémunération", remun), ("horaires", hor)) if not v]
        publiable = not problemes and not b.get("exemple")

        lignes.append({
            "ref": b.get("ref", ""),
            "poste": METIERS.get(b.get("metier", ""), b.get("metier", "")),
            "ville": b.get("ville", ""),
            "zone": b.get("zone", ""),
            "format": FORMATS.get(b.get("format", ""), b.get("format", "")),
            "statut": "EXEMPLE" if exemple else b.get("statut", ""),
            "publiable": "oui" if publiable and not alertes else "non",
            "remuneration": remun or "",
            "horaires": hor or "",
            "informations_non_communiquees": ", ".join(non_communique),
            "annonce": texte.replace("\n", " / "),
            "alertes": " | ".join(alertes),
            "problemes": " | ".join(problemes),
            "source_confirmation": b.get("source_confirmation", ""),
            "date_confirmation": b.get("date_confirmation", ""),
            "lien_whatsapp": lien_whatsapp(b),
        })
    return lignes


def main():
    parser = argparse.ArgumentParser(description="Yallah Services - offres d'emploi")
    parser.add_argument("--source", default=SOURCE_PAR_DEFAUT)
    parser.add_argument("--sortie", default="offres_emploi.csv")
    parser.add_argument("--langue", choices=["fr", "darija", "arabe"], default="fr")
    parser.add_argument("--ref", help="ne traiter qu'un seul besoin")
    parser.add_argument("--avec-exemples", action="store_true", help="inclure les fiches d'exemple")
    parser.add_argument("--check", action="store_true", help="validation seule, sans ecriture")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        sys.exit(f"Fichier source introuvable : {args.source}")

    with open(args.source, encoding="utf-8") as f:
        data = json.load(f)

    besoins = data.get("besoins", [])
    if args.ref:
        besoins = [b for b in besoins if b.get("ref") == args.ref]
    if not besoins:
        sys.exit("Aucun besoin a traiter.")

    lignes = construire_lignes(besoins, args.langue, args.avec_exemples)
    if not lignes:
        print("Aucun besoin publiable : toutes les fiches sont des exemples ou ont été écartées.")
        print("Rien n'a été publié. C'est le comportement attendu tant qu'aucun employeur n'a confirmé de besoin.")
        return

    bloquantes = [l for l in lignes if l["publiable"] != "oui"]

    if args.check:
        print(f"{len(lignes)} besoin(s) examiné(s), {len(bloquantes)} non publiable(s).")
        for l in bloquantes:
            print(f"  - {l['ref']} : {l['problemes'] or l['alertes']}")
        sys.exit(1 if bloquantes else 0)

    with open(args.sortie, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES)
        writer.writeheader()
        writer.writerows(lignes)

    publiables = [l for l in lignes if l["publiable"] == "oui"]
    print(f"{len(lignes)} besoin(s) écrit(s) dans {args.sortie} — {len(publiables)} publiable(s).")


if __name__ == "__main__":
    main()
