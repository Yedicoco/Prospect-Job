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

# Canaux de reception des candidatures, fournis par Yallah Services (21/10/2026).
# WhatsApp : meme numero que la fiche. Email : adresse dediee au service.
CONTACT_EMAIL = "servicesyallah@gmail.com"

# ---------------------------------------------------------------------------
# Politique de frais applicables aux CANDIDATS (decision Yallah, pas du client).
# Trois etats seulement, et un seul peut etre actif :
#   "aucun"    -> les annonces ecrivent noir sur blanc qu'aucun frais n'est demande
#   "factures" -> les annonces doivent afficher le montant source, sinon rien n'est publiable
#   "inconnu"  -> silence total sur les frais : ni promesse, ni omission trompeuse
# Ne jamais passer a "aucun" si ce n'est pas vrai : c'est un engagement public.
#
# DECISION YALLAH DU 21/10/2026 : renoncement aux 100 MAD a l'inscription, pour
# respecter l'article 480 du Code du travail (voir le verrou ci-dessous). D'ou
# POLITIQUE_FRAIS = "aucun" : les annonces disent noir sur blanc qu'aucun frais
# n'est demande. Ce n'est pas une valeur par defaut technique, c'est une decision
# datee ; si la politique change, la ligne ci-dessous et ce commentaire changent
# ensemble.
# ---------------------------------------------------------------------------
POLITIQUE_FRAIS = "aucun"

# ---------------------------------------------------------------------------
# VERROU JURIDIQUE - frais demandes aux candidats
#
# L'article 480 du Code du travail marocain (loi 65-99) interdit aux agences de
# recrutement privees de percevoir, directement ou indirectement, des demandeurs
# d'emploi des emoluments ou frais, en partie ou en totalite.
# L'article 477 definit l'agence de recrutement privee comme toute personne morale
# dont l'activite consiste notamment a rapprocher les demandes et les offres d'emploi.
#
# Consequence pour ce module : aucune annonce affichant des frais candidats ne peut
# etre publiee tant qu'une validation juridique datee n'est pas enregistree ici.
# Renseigner ce champ ne rend PAS l'annonce legale : cela documente seulement que
# la question a ete tranchee par un professionnel du droit.
#
#   FRAIS_CANDIDAT_VALIDATION = {"reference": "avocat X, avis du ...", "date": "AAAA-MM-JJ"}
# ---------------------------------------------------------------------------
FRAIS_CANDIDAT_VALIDATION = None

MOTIF_VERROU_FRAIS = (
    "publication bloquee : l'article 480 du Code du travail (loi 65-99) interdit aux "
    "agences de recrutement privees de percevoir des emoluments ou frais aupres des "
    "demandeurs d'emploi, directement ou indirectement. Aucune annonce affichant des "
    "frais candidats ne peut etre publiee sans validation juridique datee "
    "(FRAIS_CANDIDAT_VALIDATION dans yallah_emploi.py)."
)

PHRASES_FRAIS = {
    "aucun": {
        "fr": "Aucun frais n'est demandé au candidat, à aucune étape de la mise en relation.",
        "darija": "Ma kayn 7ta khols 3la lkandidat, f 7ta mar7ala mn lmowasala.",
        "arabe": "لا تُطلب أي مصاريف من المرشح في أي مرحلة من مراحل الربط.",
    },
    "factures": {
        "fr": "Des frais sont demandés au candidat : {montant} ({moment}). Ils sont annoncés avant tout engagement.",
        "darija": "Kayn khols 3la lkandidat : {montant} ({moment}). Kayt3aref bih 9bel ay iltizam.",
        "arabe": "تُطلب مصاريف من المرشح: {montant} ({moment}). ويُعلم بها قبل أي التزام.",
    },
}
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
CHAMPS_SOURCES = ("remuneration", "horaires", "frais_montant", "frais_moment")

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
    if POLITIQUE_FRAIS == "aucun":
        # Notre propre phrase sur les frais est une information, pas une promesse
        # commerciale : on la neutralise avant le passage du garde-fou, sinon elle
        # se signale elle-meme ("aucun frais" ressemble a une gratuite annoncee).
        for phrase in PHRASES_FRAIS["aucun"].values():
            texte = (texte or "").replace(phrase, "[PHRASE-FRAIS-INTERNE]")
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
def bloc_frais(besoin: dict) -> dict:
    """Bloc 'frais' du besoin, ou un bloc vide."""
    return besoin.get("frais") or {}


def frais_annoncables(b: dict) -> tuple:
    """Retourne (montant, moment) si et seulement si la politique et les sources le permettent.

    - politique "aucun"    : rien a afficher, la phrase de gratuite suffit ;
    - politique "factures" : le montant ET le moment doivent etre sources ;
    - sinon                : rien n'est affiche, quel que soit le contenu du fichier.
    """
    if POLITIQUE_FRAIS != "factures":
        return None, None
    montant, src_montant = lire_champ_source(b, "frais_montant")
    moment, src_moment = lire_champ_source(b, "frais_moment")
    if not montant or not moment or not src_montant or not src_moment:
        return None, None
    return montant, moment


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
        from validation import day
        try:
            day(b.get("date_confirmation", ""), "date_confirmation", past=True)
        except ValueError as exc:
            problemes.append(str(exc))
        if b.get("statut") != "ouvert":
            problemes.append("statut non ouvert")

    for champ in CHAMPS_SOURCES:
        bloc = b.get(champ) or {}
        if str(bloc.get("valeur", "")).strip() and not str(bloc.get("source", "")).strip():
            problemes.append(f"{champ} sans source : valeur refusee")

    # Frais : la coherence entre la politique et les sources conditionne la publication.
    if not b.get("exemple"):
        if POLITIQUE_FRAIS == "factures" and not FRAIS_CANDIDAT_VALIDATION:
            problemes.append(MOTIF_VERROU_FRAIS)
        elif POLITIQUE_FRAIS == "factures":
            montant, moment = frais_annoncables(b)
            if not montant or not moment:
                problemes.append(
                    "frais factures mais montant ou moment non source : annonce refusee "
                    "(un candidat doit connaitre les frais avant de postuler)"
                )
        elif POLITIQUE_FRAIS not in ("aucun", "inconnu"):
            problemes.append(f"politique de frais inconnue : {POLITIQUE_FRAIS}")

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


def ligne_frais(b: dict, langue: str) -> str:
    """Phrase sur les frais, ou chaine vide si la politique impose le silence."""
    if POLITIQUE_FRAIS == "aucun":
        return PHRASES_FRAIS["aucun"][langue]
    if POLITIQUE_FRAIS == "factures" and FRAIS_CANDIDAT_VALIDATION:
        montant, moment = frais_annoncables(b)
        if montant and moment:
            return PHRASES_FRAIS["factures"][langue].format(montant=montant, moment=moment)
    return ""


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

    # Frais : construits uniquement si la politique l'autorise.
    phrase_frais = ligne_frais(b, langue)

    if langue == "fr":
        return (
            f"{metier.capitalize()} — {ville} ({zone})\n\n"
            f"Type de besoin : {format_libelle}.\n"
            f"Horaires : {ligne_hor}.\n"
            f"Rémunération : {ligne_rem}.\n\n"
            + (f"{phrase_frais}\n\n" if phrase_frais else "")
            + f"Yallah Services met en relation des employeurs et des candidats au Maroc."
            + (" Ce besoin a été confirmé par un employeur ; les éléments ci-dessus sont "
               "ceux qu'il a communiqués, sans ajout de notre part." if confirme else "")
            + "\n\n"
            f"Pour proposer votre candidature, écrivez-nous sur WhatsApp ou par email à "
            f"{CONTACT_EMAIL}, en précisant la référence {ref} et le poste."
        )

    if langue == "darija":
        return (
            f"{metier.capitalize()} — {ville} ({zone})\n\n"
            f"Naw3 lkhedma : {format_libelle}.\n"
            f"Lwqiyat : {ligne_hor}.\n"
            f"L2ajr : {ligne_rem}.\n\n"
            + (f"{phrase_frais}\n\n" if phrase_frais else "")
            + f"Yallah Services kantwesel bin l2arbab lkhedma w lkandidates f lMaghrib."
            + (" Had lkhdma m2ekda mn 3and chi mchghl, w lma3lomat li foq hiya li 3tana, "
               "bla ma nzido 7ta haja mn 3andna." if confirme else "")
            + "\n\n"
            f"Ila bghiti t9edem, sift message f WhatsApp wla f email l {CONTACT_EMAIL}, "
            f"w kteb fih raqm {ref} w smit lkhedma."
        )

    return (
        f"{metier} — {ville} ({zone})\n\n"
        f"نوع الحاجة: {format_libelle}.\n"
        f"التوقيت: {ligne_hor}.\n"
        f"الأجر: {ligne_rem}.\n\n"
        + (f"{phrase_frais}\n\n" if phrase_frais else "")
        + f"Yallah Services تعمل على الربط بين أصحاب العمل والمرشحين في المغرب."
        + (" هذه الحاجة مؤكدة من طرف صاحب عمل، والمعطيات أعلاه هي التي قدمها دون أي إضافة منا."
           if confirme else "")
        + "\n\n"
        f"لتقديم ترشيحك، أرسل رسالة على واتساب أو عبر البريد الإلكتروني {CONTACT_EMAIL} "
        f"مع ذكر المرجع {ref} والمنصب."
    )


def lien_whatsapp(b: dict) -> str:
    metier = METIERS.get(b.get("metier", ""), b.get("metier", ""))
    message = f"Bonjour, je souhaite postuler au poste de {metier} (réf {b.get('ref', '')})."
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}"


def lien_email(b: dict) -> str:
    metier = METIERS.get(b.get("metier", ""), b.get("metier", ""))
    sujet = f"Candidature - {metier} (ref {b.get('ref', '')})"
    return f"mailto:{CONTACT_EMAIL}?subject={quote(sujet)}"


# ---------------------------------------------------------------------------
# Construction des lignes
# ---------------------------------------------------------------------------
COLONNES = [
    "ref", "poste", "ville", "zone", "format", "statut", "publiable",
    "remuneration", "horaires", "informations_non_communiquees", "annonce",
    "alertes", "problemes", "source_confirmation", "date_confirmation",
    "lien_whatsapp", "lien_email",
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
        montant, _ = frais_annoncables(b)
        # Les phrases de frais sont adossees a une politique ou a une source :
        # elles ne doivent pas declencher le garde-fou sur leurs propres mots.
        valeurs_sourcees = [v for v in (remun, hor, montant, ligne_frais(b, langue)) if v]
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
            "lien_email": lien_email(b),
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
