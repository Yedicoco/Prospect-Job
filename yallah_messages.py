#!/usr/bin/env python3
"""
Yallah Services - Moteur de messages de prospection (B2B entreprises + B2C particuliers)

Ce que fait ce script :
  1. Charge deux jeux de fiches SEPARES : prospects_b2b.json (entreprises clientes)
     et prospects_b2c.json (particuliers)
  2. Refuse toute fiche non sourcee (URL + date obligatoires) et tout contact absent
  3. QUALIFIE chaque prospect : score, priorite, motifs de non-qualification
  4. Genere un message personnalise par prospect qualifie, dans la langue demandee
  5. Controle chaque message avec le garde-fou (prix, delais, garanties, verifications,
     promesses commerciales, formule de retrait obligatoire, longueur)
  6. Produit une FILE D'ENVOI : CSV + Markdown, avec liens wa.me / mailto preremplis

Ce que ce script NE fait PAS, volontairement :
  - il n'envoie rien : aucun appel reseau, aucune API WhatsApp, aucun SMTP ;
  - il ne cree aucun lien d'envoi tant que [prenom] n'est pas remplace ;
  - il ne fusionne jamais les deux jeux de fiches : un contact present des deux cotes
    est signale comme doublon, pas envoye deux fois.

Usage :
  python yallah_messages.py --check
  python yallah_messages.py --prenom "Youssef" --langue fr
  python yallah_messages.py --prenom "Youssef" --type b2c --langue darija
  python yallah_messages.py --prenom "Youssef" --markdown file_envoi.md

Le CSV et le Markdown de sortie sont des artefacts de travail (ignores par Git).
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from urllib.parse import quote

from yallah_b2c import BESOINS as BESOINS_B2C
from yallah_prospection import (
    BESOINS_B2B, SEGMENTS, verifier_message as verifier_message_b2b,
)

# ---------------------------------------------------------------------------
# Coordonnees officielles Yallah Services
# ---------------------------------------------------------------------------
WHATSAPP_NUMBER = "212691733585"

PEREMPTION_JOURS = 90          # au-dela, la source doit etre reconfirmee
MAX_PAR_JOUR = 15              # cadence manuelle : au-dela, on considere que c'est du volume
LONGUEUR_MAX = 900             # caracteres ; au-dela, le message est trop long pour un premier contact

DATE_ATTENDUE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PLACEHOLDER_PRENOM = "[prenom]"

TYPES = {
    "b2b": {
        "fichier": "prospects_b2b.json",
        "prefixe": "B2B",
        "libelle": "entreprise cliente",
        "champs_requis": ["nom", "segment", "ville", "zone", "source_url",
                          "date_consultation", "niveau"],
    },
    "b2c": {
        "fichier": "prospects_b2c.json",
        "prefixe": "BC",
        "libelle": "particulier",
        "champs_requis": ["nom", "besoin", "ville", "zone", "source_url",
                          "date_consultation", "niveau"],
    },
}

# La formule de retrait est obligatoire dans chaque message (loi 09-08 / usage).
OPT_OUT_MARQUEURS = (
    "ne vous relancerai pas",
    "ne vous recontacte pas",
    "ma n3awdch",
    "لن أتواصل معكم",
)

# Motifs de pression commerciale, en plus des motifs B2B deja en place.
PATTERNS_PRESUPPLEMENT = [
    (r"\b(derni[eè]re chance|offre limit[ée]e|aujourd'hui seulement|places limit[ée]es)\b", "pression commerciale"),
    (r"\b(promo|promotion|remise|\d+\s?%)\b", "remise annoncee"),
    (r"\b(relance[s]? automatique|mailing|newsletter)\b", "envoi de masse annonce"),
]


def verifier_message(texte: str) -> list:
    """Alertes d'un message : garde-fou B2B + pression commerciale + retrait + longueur."""
    alertes = list(verifier_message_b2b(texte or ""))
    bas = (texte or "").lower()
    for motif, libelle in PATTERNS_PRESUPPLEMENT:
        trouve = re.search(motif, bas, flags=re.IGNORECASE)
        if trouve:
            alertes.append(f"{libelle} : « {trouve.group(0).strip()} »")
    if texte and not any(m in bas for m in OPT_OUT_MARQUEURS):
        alertes.append("formule de retrait absente")
    if texte and len(texte) > LONGUEUR_MAX:
        alertes.append(f"message trop long ({len(texte)} caracteres, maximum {LONGUEUR_MAX})")
    return alertes


# ---------------------------------------------------------------------------
# Normalisation des contacts
# ---------------------------------------------------------------------------
def tel_normalise(tel: str) -> str:
    """Chiffres seuls, prefixe 212 pour un numero marocain."""
    chiffres = re.sub(r"\D", "", tel or "")
    if chiffres.startswith("0"):
        chiffres = "212" + chiffres[1:]
    return chiffres


def email_normalise(email: str) -> str:
    return (email or "").strip().lower()


def cles_contact(p: dict) -> list:
    cles = []
    tel = tel_normalise(p.get("tel", ""))
    if len(tel) >= 9:
        cles.append("tel:" + tel)
    mail = email_normalise(p.get("email", ""))
    if "@" in mail:
        cles.append("mail:" + mail)
    return cles


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------
def date_verification(p: dict) -> str:
    """Date de la derniere verification de la fiche (a defaut, date de consultation)."""
    return str(p.get("date_derniere_verification") or p.get("date_consultation", ""))


def age_source(p: dict, date_reference: date) -> int:
    """Age de la source d'origine (date de consultation), en jours."""
    try:
        annee, mois, jour = (int(x) for x in str(p.get("date_consultation", "")).split("-"))
        return (date_reference - date(annee, mois, jour)).days
    except (ValueError, TypeError):
        return -1


def a_actualiser(p: dict, date_reference: date) -> bool:
    """Vrai si la fiche n'a pas ete revérifiée le jour meme (actualisation quotidienne)."""
    return date_verification(p) != date_reference.isoformat()


def valider_fiche(p: dict, type_prospect: str) -> list:
    """Anomalies bloquantes d'une fiche, avant meme de parler de message."""
    anomalies = []
    for champ in TYPES[type_prospect]["champs_requis"]:
        if champ == "source_url" and p.get("source_type") == "entrant" and re.fullmatch(r"ENT-\d{6,}", str(p.get("source_reference", ""))):
            continue  # provenance de première partie, vérifiée par l'API web
        if not str(p.get(champ, "")).strip():
            anomalies.append(f"champ manquant : {champ}")

    url = str(p.get("source_url", ""))
    if url and not url.startswith("http"):
        anomalies.append("source_url n'est pas une URL")

    d = str(p.get("date_consultation", ""))
    if d and not DATE_ATTENDUE.match(d):
        anomalies.append("date_consultation attendue au format AAAA-MM-JJ")

    if p.get("niveau") not in {"A", "B", "C"}:
        anomalies.append("niveau attendu : A, B ou C")

    if type_prospect == "b2b":
        if p.get("segment") not in SEGMENTS:
            anomalies.append(f"segment inconnu : {p.get('segment')}")
        if p.get("phase") not in (1, 2, 3):
            anomalies.append("phase attendue : 1, 2 ou 3")
    else:
        if p.get("besoin") not in BESOINS_B2C:
            anomalies.append(f"besoin inconnu : {p.get('besoin')}")

    if not str(p.get("tel", "")).strip() and not str(p.get("email", "")).strip():
        if p.get("niveau") != "C":
            anomalies.append("aucun contact direct : niveau C attendu")

    return anomalies


def score_prospect(p: dict, type_prospect: str) -> tuple:
    """Score 0-10 + libelle. Heuristique d'ordonnancement, pas une prevision."""
    from yallah_prospection import priorite as priorite_b2b

    if type_prospect == "b2b":
        return priorite_b2b(p)

    score = 2
    from yallah_b2c import PHASE_1
    zones_p1 = {ville: set(bloc[villes].keys()) for ville, bloc in PHASE_1.items() for villes in bloc}
    if p.get("zone") in zones_p1.get(p.get("ville", ""), set()):
        score += 4
    score += {"A": 2, "B": 1, "C": 0}.get(p.get("niveau"), 0)
    score = max(0, min(10, score))
    libelle = "haute" if score >= 8 else ("moyenne" if score >= 6 else "basse")
    return score, libelle


def qualifier(p: dict, type_prospect: str, contacts_vus: dict,
              exclusions: set, date_reference: date) -> dict:
    """Retourne {qualifie, motifs, alertes bloquantes, reserves informatives}."""
    motifs = valider_fiche(p, type_prospect)
    alertes = []
    reserves = []

    if p.get("exemple"):
        motifs.append("fiche d'exemple, jamais envoyable")

    cles = cles_contact(p)
    for cle in cles:
        if cle in exclusions:
            motifs.append("contact au registre des refus (ne plus contacter)")
        elif cle in contacts_vus:
            motifs.append(f"doublon de contact avec {contacts_vus[cle]}")
        else:
            contacts_vus[cle] = p.get("nom", "?")

    if p.get("niveau") == "C":
        motifs.append("aucun contact direct publie : formulaire uniquement, message non prepare")

    if a_actualiser(p, date_reference):
        motifs.append(f"actualisation du jour non faite (derniere verification : "
                      f"{date_verification(p) or 'aucune'})")

    age = age_source(p, date_reference)
    if age > PEREMPTION_JOURS:
        alertes.append(f"source datee de {age} jours : a reconfirmer avant envoi")
    elif age < 0:
        alertes.append("date de consultation incoherente (posterieure a la date de reference)")

    if p.get("niveau") == "B":
        reserves.append("coordonnee vue en extrait, non reconfirmee sur la page officielle")

    return {"qualifie": not motifs, "motifs": motifs,
            "alertes": alertes, "reserves": reserves}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
AFFICHAGE_BESOINS_B2B = {
    "PRP": "propreté et entretien des locaux",
    "CUI": "cuisine et plonge",
    "SRV": "service en salle / extra",
    "NET": "nettoyage de fin de chantier",
    "GAR": "gardiennage",
    "MAI": "personnel de maison",
    "REN": "renfort journalier événementiel",
}


AFFICHAGE_BESOINS_B2B_DARIJA = {
    "PRP": "tnadif w tarteeb dyal lma7al",
    "CUI": "tbakh w l7ella",
    "SRV": "khedma f ssalle / extra",
    "NET": "tnadif mora lbina",
    "GAR": "7arassa",
    "MAI": "khedma f dar",
    "REN": "renfort b nhar l lmounasabat",
}

AFFICHAGE_BESOINS_B2B_ARABE = {
    "PRP": "النظافة والعناية بالمكان",
    "CUI": "الطبخ والجلي",
    "SRV": "الخدمة في القاعة / الضيافة",
    "NET": "تنظيف نهاية الأشغال",
    "GAR": "الحراسة",
    "MAI": "العمل في المنازل",
    "REN": "تعزيز يومي للمناسبات",
}

AFFICHAGE_BESOINS_B2C = {
    "darija": {
        "MEN": "mnada", "NOU": "nounou", "CUI": "tbakha",
        "CHA": "chauffeur", "AGE": "m3awna l kbar", "GAR": "gardien",
        "PON": "tnadif mawqati",
    },
    "arabe": {
        "MEN": "عاملة منزل", "NOU": "جليسة أطفال", "CUI": "طباخة",
        "CHA": "سائق", "AGE": "مساعدة كبار السن", "GAR": "حارس",
        "PON": "تنظيف عرضي",
    },
}


def besoins_libelles(p: dict, type_prospect: str, langue: str = "fr") -> str:
    if type_prospect == "b2b":
        segment = SEGMENTS.get(p.get("segment"), {})
        codes = p.get("besoins_probables") or segment.get("besoins", [])
        table = {"fr": AFFICHAGE_BESOINS_B2B,
                 "darija": AFFICHAGE_BESOINS_B2B_DARIJA,
                 "arabe": AFFICHAGE_BESOINS_B2B_ARABE}[langue]
        return ", ".join(table.get(c, BESOINS_B2B.get(c, c)) for c in codes[:3])
    if langue in AFFICHAGE_BESOINS_B2C:
        code = p.get("besoin", "")
        return AFFICHAGE_BESOINS_B2C[langue].get(code, BESOINS_B2C.get(code, "personnel"))
    return BESOINS_B2C.get(p.get("besoin", ""), p.get("besoin", "personnel"))


def message_b2b(p: dict, langue: str) -> str:
    nom = p["nom"]
    ville = p["ville"]
    zone = p.get("zone", "")
    ou = f", {zone}" if zone else ""
    besoins = besoins_libelles(p, "b2b", langue)

    if langue == "darija":
        return (
            f"Salam,\n\n"
            f"Ana {PLACEHOLDER_PRENOM} mn Yallah Services. Kankhdmo m3a l2etablissements "
            f"f {ville} bach nwefro lihom personnel : {besoins}.\n\n"
            f"Kantawessal m3akom 3la {nom}{ou}. Kayn tlata formats : permanent, temporaire, "
            f"w renfort b nhar, 3la 7sab lkhedma dyalek.\n\n"
            f"Wach 3ndkom 10 daqiqat bach nfahmo l7aja li m7tajin biha?\n\n"
            f"Ila had lmawdo3 ma 3ndkomch bih, goulha liya bsouhoula w ma n3awdch nkellemkom.\n\n"
            f"Chokran,\n{PLACEHOLDER_PRENOM} — Yallah Services"
        )
    if langue == "arabe":
        return (
            f"مرحبا،\n\n"
            f"أنا {PLACEHOLDER_PRENOM} من Yallah Services. نعمل مع المؤسسات في {ville} "
            f"لتوفير الموظفين من أجل: {besoins}.\n\n"
            f"أتواصل معكم بخصوص {nom}{ou}. لدينا ثلاث صيغ: دائم، مؤقت، وتعزيز يومي، حسب حاجتكم.\n\n"
            f"هل لديكم عشر دقائق لنفهم حاجتكم بدقة؟\n\n"
            f"إن لم يكن هذا الموضوع يهمكم، أخبروني ببساطة ولن أتواصل معكم مرة أخرى.\n\n"
            f"مع التحية،\n{PLACEHOLDER_PRENOM} — Yallah Services"
        )
    return (
        f"Bonjour,\n\n"
        f"Je suis {PLACEHOLDER_PRENOM} de Yallah Services. Nous accompagnons les établissements "
        f"de {ville} sur leurs besoins en personnel : {besoins}.\n\n"
        f"Je vous contacte au sujet de {nom}{ou}. Selon votre organisation, nous travaillons sur "
        f"trois formats : permanent, temporaire et renfort journalier.\n\n"
        f"Auriez-vous dix minutes pour un échange afin que nous comprenions votre besoin réel ?\n\n"
        f"Si ce sujet ne vous concerne pas, dites-le-moi simplement : je ne vous relancerai pas.\n\n"
        f"Bien à vous,\n{PLACEHOLDER_PRENOM} — Yallah Services"
    )


def message_b2c(p: dict, langue: str) -> str:
    besoin = besoins_libelles(p, "b2c", langue)
    zone = p.get("zone", "")
    ville = p.get("ville", "")

    if langue == "darija":
        return (
            f"Salam,\n\n"
            f"Ana {PLACEHOLDER_PRENOM} mn Yallah Services. Chaft l'annonce dyalek: {besoin} "
            f"f {zone}, {ville}.\n\n"
            f"Kankhdmo m3a l3a2ilat bach nl9aw lihom personnel: mnada, nounou, tbakh, "
            f"m3awna l kbar, chauffeur. Kayn permanent, temporaire, w renfort b nhar.\n\n"
            f"Wach n9dro ndiro wahed mokala d 10 daqiqat bach nfahmo chno m7tajin?\n\n"
            f"Ila ma bghitich, goulha liya w ma n3awdch nkellemek.\n\n"
            f"Chokran,\n{PLACEHOLDER_PRENOM} — Yallah Services"
        )
    if langue == "arabe":
        return (
            f"مرحبا،\n\n"
            f"أنا {PLACEHOLDER_PRENOM} من Yallah Services. رأيت إعلانكم بخصوص {besoin} "
            f"في {zone}، {ville}.\n\n"
            f"نعمل مع الأسر لتوفير الموظفين: عاملة منزل، جليسة أطفال، طباخة، مساعدة لكبار السن، سائق. "
            f"ونعمل بصيغة دائمة أو مؤقتة أو تعزيز ليوم واحد.\n\n"
            f"هل يمكننا التحدث عشر دقائق لفهم حاجتكم؟\n\n"
            f"إن لم يكن هذا الأمر يهمكم، أخبروني بذلك ولن أتواصل معكم مرة أخرى.\n\n"
            f"مع التحية،\n{PLACEHOLDER_PRENOM} — Yallah Services"
        )
    return (
        f"Bonjour,\n\n"
        f"Je suis {PLACEHOLDER_PRENOM} de Yallah Services. J'ai vu votre annonce : {besoin} "
        f"à {zone}, {ville}.\n\n"
        f"Nous travaillons avec les familles pour ce type de besoin : femme de ménage, nounou, "
        f"cuisinière, aide aux personnes âgées, chauffeur. Selon ce que vous cherchez, nous "
        f"proposons du permanent, du temporaire ou un renfort ponctuel.\n\n"
        f"Auriez-vous dix minutes pour un échange afin de comprendre votre besoin ?\n\n"
        f"Si ce message ne vous intéresse pas, dites-le-moi simplement : je ne vous recontacte pas.\n\n"
        f"Bien à vous,\n{PLACEHOLDER_PRENOM} — Yallah Services"
    )


def generer_message(p: dict, type_prospect: str, langue: str, prenom: str = "") -> str:
    texte = message_b2b(p, langue) if type_prospect == "b2b" else message_b2c(p, langue)
    if p.get("source_type") == "entrant" and type_prospect == "b2c":
        texte = texte.replace("J'ai vu votre annonce :", "Nous avons reçu votre demande :")
        texte = texte.replace("Chaft l'annonce dyalek:", "Twesselna b talab dyalek:")
        texte = texte.replace("رأيت إعلانكم بخصوص", "توصلنا بطلبكم بخصوص")
    if prenom:
        texte = texte.replace(PLACEHOLDER_PRENOM, prenom)
    return texte


# ---------------------------------------------------------------------------
# Liens preremplis (jamais envoyes par le script)
# ---------------------------------------------------------------------------
def lien_whatsapp(p: dict, message: str) -> str:
    tel = tel_normalise(p.get("tel", ""))
    if len(tel) < 9 or PLACEHOLDER_PRENOM in message:
        return ""
    return f"https://wa.me/{tel}?text={quote(message)}"


def lien_email(p: dict, message: str, type_prospect: str) -> str:
    mail = email_normalise(p.get("email", ""))
    if "@" not in mail or PLACEHOLDER_PRENOM in message:
        return ""
    objet = "Yallah Services - personnel de maison" if type_prospect == "b2c" else "Yallah Services - personnel pour votre etablissement"
    return f"mailto:{mail}?subject={quote(objet)}&body={quote(message)}"


# ---------------------------------------------------------------------------
# Construction de la file d'envoi
# ---------------------------------------------------------------------------
COLONNES = [
    "jour", "ref", "type", "nom", "categorie", "ville", "zone", "phase", "adresse",
    "tel", "email", "source_url", "date_consultation", "niveau", "score", "priorite",
    "qualifie", "motifs_non_qualification", "alertes", "reserves", "langue", "canal",
    "message", "lien_whatsapp", "lien_email", "statut",
]


def charger(chemin: str) -> dict:
    if not os.path.exists(chemin):
        sys.exit(f"Fichier source introuvable : {chemin}")
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def exclusions_globales(donnees: dict) -> set:
    """Numeros et emails au registre des refus (meta.refus), tous fichiers confondus."""
    refus = set()
    for cle in ("refus", "opt_out", "ne_plus_contacter"):
        for valeur in donnees.get("meta", {}).get(cle, []) or []:
            if "@" in str(valeur):
                refus.add("mail:" + email_normalise(str(valeur)))
            else:
                refus.add("tel:" + tel_normalise(str(valeur)))
    return refus


def construire_lignes(jeux: list, langue: str, prenom: str, date_reference: date) -> list:
    """jeux = [(type, donnees), ...] ; les contacts sont suivis tous fichiers confondus."""
    contacts_vus = {}
    refus = set()
    for _, donnees in jeux:
        refus |= exclusions_globales(donnees)

    lignes = []
    for type_prospect, donnees in jeux:
        for i, p in enumerate(donnees.get("prospects", []), start=1):
            verdict = qualifier(p, type_prospect, contacts_vus, refus, date_reference)
            score, libelle = score_prospect(p, type_prospect)
            message = generer_message(p, type_prospect, langue, prenom) if verdict["qualifie"] else ""
            alertes = verdict["alertes"] + (verifier_message(message) if message else [])

            canal = ("whatsapp" if tel_normalise(p.get("tel", ""))
                     else ("email" if "@" in email_normalise(p.get("email", "")) else ""))
            wa = lien_whatsapp(p, message) if message else ""
            mail = lien_email(p, message, type_prospect) if message else ""

            if not verdict["qualifie"]:
                statut = ("A ACTUALISER"
                          if verdict["motifs"] and all(m.startswith("actualisation") for m in verdict["motifs"])
                          else "NON QUALIFIE")
            elif PLACEHOLDER_PRENOM in message:
                statut = "A COMPLETER - prenom manquant"
            elif alertes:
                statut = "BLOQUE - a corriger"
            else:
                statut = "PRET - envoi manuel"

            categorie = (SEGMENTS.get(p.get("segment"), {}).get("libelle", p.get("segment", ""))
                         if type_prospect == "b2b" else BESOINS_B2C.get(p.get("besoin", ""), p.get("besoin", "")))

            lignes.append({
                "jour": 0,
                "ref": f"{TYPES[type_prospect]['prefixe']}-{i:03d}",
                "type": type_prospect,
                "nom": p.get("nom", ""),
                "categorie": categorie,
                "ville": p.get("ville", ""),
                "zone": p.get("zone", ""),
                "phase": p.get("phase", "") if type_prospect == "b2b" else "",
                "adresse": p.get("adresse", ""),
                "tel": p.get("tel", ""),
                "email": p.get("email", ""),
                "source_url": p.get("source_url", ""),
                "date_consultation": p.get("date_consultation", ""),
                "niveau": p.get("niveau", ""),
                "score": score,
                "priorite": libelle,
                "qualifie": "oui" if verdict["qualifie"] else "non",
                "motifs_non_qualification": " | ".join(verdict["motifs"]),
                "alertes": " | ".join(alertes),
                "reserves": " | ".join(verdict["reserves"]),
                "langue": langue,
                "canal": canal,
                "message": message.replace("\n", " / "),
                "_brut": message,
                "lien_whatsapp": wa,
                "lien_email": mail,
                "statut": statut,
            })

    # Ordonnancement : phase 1 d'abord, puis score decroissant, puis ville.
    lignes.sort(key=lambda l: (l["statut"] != "PRET - envoi manuel",
                               l["type"],
                               int(l["phase"] or 0),
                               -l["score"], l["ville"], l["nom"]))
    # Plan d'envoi : MAX_PAR_JOUR contacts prets par jour (cadence manuelle).
    jour, compte = 1, 0
    for ligne in lignes:
        if ligne["statut"] != "PRET - envoi manuel":
            continue
        if compte >= MAX_PAR_JOUR:
            jour, compte = jour + 1, 0
        ligne["jour"] = jour
        compte += 1
    return lignes


def ecrire_markdown(chemin: str, lignes: list, langue: str) -> None:
    prets = [l for l in lignes if l["statut"] == "PRET - envoi manuel"]
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("# File d'envoi Yallah Services\n\n")
        f.write(f"{len(prets)} message(s) pret(s), envoi **manuel**, un par un.\n\n")
        f.write("Regle : on envoie depuis son propre WhatsApp ou sa boite mail, jamais par un outil d'envoi de masse. ")
        f.write("Pas de relance avant 7 jours, une seule relance maximum, et jamais apres un refus.\n\n")
        for jour in sorted({l["jour"] for l in prets}):
            f.write(f"## Jour {jour}\n\n")
            for l in [x for x in prets if x["jour"] == jour]:
                f.write(f"### {l['ref']} - {l['nom']} ({l['categorie']}, {l['zone']}, {l['ville']})\n\n")
                f.write(f"- Contact : {l['tel'] or '—'} / {l['email'] or '—'}  \n")
                f.write(f"- Source : {l['source_url']} ({l['date_consultation']}, niveau {l['niveau']})  \n")
                f.write(f"- Priorite : {l['priorite']} ({l['score']}/10)\n")
                if l["reserves"]:
                    f.write(f"- Reserve : {l['reserves']}\n")
                f.write("\n")
                f.write("```text\n" + l.get("_brut", l["message"]) + "\n```\n\n")
                if l["lien_whatsapp"]:
                    f.write(f"[Ouvrir dans WhatsApp]({l['lien_whatsapp']})  \n")
                if l["lien_email"]:
                    f.write(f"[Ouvrir dans la messagerie]({l['lien_email']})  \n")
                f.write("\n")


def marquer_verifie(chemins: dict, refs: list, jour: date) -> list:
    """Inscrit la date du jour comme date de verification des refs indiquees."""
    refs = {r.strip().upper() for r in refs if r.strip()}
    marquees = []
    for type_prospect, chemin in chemins.items():
        if not os.path.exists(chemin):
            continue
        with open(chemin, encoding="utf-8") as f:
            donnees = json.load(f)
        prefixe = TYPES[type_prospect]["prefixe"]
        modifie = False
        for i, p in enumerate(donnees.get("prospects", []), start=1):
            ref = f"{prefixe}-{i:03d}"
            if ref in refs:
                p["date_derniere_verification"] = jour.isoformat()
                marquees.append(ref)
                modifie = True
        if modifie:
            donnees.setdefault("meta", {})["date_maj"] = jour.isoformat()
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(donnees, f, ensure_ascii=False, indent=2)
                f.write("\n")
    return marquees


def ecrire_actualisation(chemin: str, lignes: list, jour: date) -> int:
    """Checklist du jour : fiches a revérifier avant tout envoi."""
    a_faire = [l for l in lignes if l["statut"] == "A ACTUALISER"]
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(f"# Actualisation des fiches - {jour.isoformat()}\n\n")
        f.write("Regle : une fiche non revérifiée le jour même ne reçoit aucun message.\n")
        f.write("Ouvrez chaque source, vérifiez que le contact est toujours publié et identique, ")
        f.write("puis estampillez la fiche. Si le contact a disparu ou changé, corrigez la fiche ")
        f.write("dans le JSON avant de l'estampiller.\n\n")
        f.write(f"**{len(a_faire)} fiche(s) à revérifier aujourd'hui.**\n\n")
        for l in a_faire:
            f.write(f"- [ ] **{l['ref']}** - {l['nom']} ({l['ville']}, {l['zone']})  \n")
            f.write(f"      source : {l['source_url']}  \n")
            f.write(f"      contact à reconfirmer : {l['tel'] or '—'} / {l['email'] or '—'}\n")
        if a_faire:
            f.write("\nUne fois les fiches vérifiées une par une :\n\n")
            f.write("```bash\n")
            f.write("python3 yallah_messages.py --verifie " + " ".join(l["ref"] for l in a_faire[:5]))
            f.write((" ..." if len(a_faire) > 5 else "") + "\n")
            f.write("```\n")
    return len(a_faire)


def main():
    parser = argparse.ArgumentParser(
        description="Yallah Services - messages de prospection (aucun envoi automatique)")
    parser.add_argument("--type", choices=["b2b", "b2c", "tous"], default="tous")
    parser.add_argument("--langue", choices=["fr", "darija", "arabe"], default="fr")
    parser.add_argument("--prenom", default=os.getenv("YALLAH_PRENOM", ""),
                        help="prenom du signataire ; sans lui, aucun lien d'envoi n'est cree")
    parser.add_argument("--source-b2b", default=TYPES["b2b"]["fichier"])
    parser.add_argument("--source-b2c", default=TYPES["b2c"]["fichier"])
    parser.add_argument("--sortie", default="file_envoi.csv")
    parser.add_argument("--markdown", help="ecrit aussi la file d'envoi en Markdown")
    parser.add_argument("--tous-les-statuts", action="store_true",
                        help="inclure les fiches non qualifiees dans le CSV")
    parser.add_argument("--check", action="store_true", help="validation seule, sans ecriture")
    parser.add_argument("--actualiser", help="ecrit la checklist du jour (fiches a revérifier)")
    parser.add_argument("--verifie", nargs="+", metavar="REF",
                        help="estampille les fiches verifiees aujourd'hui (ex. B2B-001 B2B-002)")
    parser.add_argument("--envoyer", action="store_true",
                        help="refuse : ce script ne realise aucun envoi")
    args = parser.parse_args()

    if args.envoyer:
        sys.exit("Envoi automatique refuse : ce script prepare des messages, il n'en envoie aucun.\n"
                 "Ouvrez le lien wa.me / mailto de la ligne voulue depuis votre propre compte.")

    chemins = {}
    if args.type in ("b2b", "tous"):
        chemins["b2b"] = args.source_b2b
    if args.type in ("b2c", "tous"):
        chemins["b2c"] = args.source_b2c

    if args.verifie:
        marquees = marquer_verifie(chemins, args.verifie, date.today())
        inconnues = sorted({r.upper() for r in args.verifie} - set(marquees))
        print(f"{len(marquees)} fiche(s) estampillee(s) au {date.today().isoformat()} : "
              f"{', '.join(marquees) or '—'}")
        if inconnues:
            print(f"Reference(s) introuvable(s) : {', '.join(inconnues)}")

    jeux = []
    if args.type in ("b2b", "tous"):
        jeux.append(("b2b", charger(args.source_b2b)))
    if args.type in ("b2c", "tous"):
        jeux.append(("b2c", charger(args.source_b2c)))

    lignes = construire_lignes(jeux, args.langue, args.prenom, date.today())
    prets = [l for l in lignes if l["statut"] == "PRET - envoi manuel"]
    bloques = [l for l in lignes if l["statut"] == "BLOQUE - a corriger"]
    incomplets = [l for l in lignes if l["statut"] == "A COMPLETER - prenom manquant"]
    rejetes = [l for l in lignes if l["statut"] == "NON QUALIFIE"]
    a_jour = [l for l in lignes if l["statut"] == "A ACTUALISER"]

    if args.actualiser:
        n = ecrire_actualisation(args.actualiser, lignes, date.today())
        print(f"Checklist du jour ecrite dans {args.actualiser} : {n} fiche(s) a revérifier.")
        return

    if args.check:
        print(f"{len(lignes)} fiche(s) : {len(prets)} prete(s), {len(bloques)} bloquee(s), "
              f"{len(incomplets)} a completer, {len(a_jour)} a actualiser, "
              f"{len(rejetes)} non qualifiee(s).")
        for l in bloques + rejetes:
            print(f"  - {l['ref']} {l['nom']} : {l['motifs_non_qualification'] or l['alertes']}")
        if incomplets:
            print("  Rappel : sans --prenom, aucun lien d'envoi n'est genere.")
        sys.exit(1 if bloques else 0)

    ecrites = lignes if args.tous_les_statuts else prets + bloques + incomplets + a_jour
    with open(args.sortie, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ecrites)

    if args.markdown:
        ecrire_markdown(args.markdown, lignes, args.langue)

    print(f"{len(ecrites)} ligne(s) ecrite(s) dans {args.sortie}")
    print(f"  {len(prets)} prete(s) a envoyer a la main, {len(bloques)} bloquee(s), "
          f"{len(incomplets)} a completer, {len(a_jour)} a actualiser, "
          f"{len(rejetes)} non qualifiee(s).")
    if prets:
        jours = sorted({l["jour"] for l in prets})
        print(f"  Plan : {len(prets)} message(s) sur {len(jours)} jour(s), "
              f"maximum {MAX_PAR_JOUR} par jour.")
    if args.markdown:
        print(f"  File d'envoi detaillee : {args.markdown}")


if __name__ == "__main__":
    main()
