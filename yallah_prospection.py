#!/usr/bin/env python3
"""
Yallah Services - Module prospection B2B (phase 1)

Ce que fait ce script :
  1. Charge le fichier de prospects source (prospects_b2b.json)
  2. Refuse toute fiche non sourcee (URL + date obligatoires) -> aucune donnee inventee
  3. Calcule une priorite (zone phase 1 x segment x niveau de verification)
  4. Genere un message d'approche COMMERCIAL par prospect (offre destinee a un client)
  5. Controle chaque message avec le garde-fou (prix, delais, garanties, verifications...)
  6. Exporte un CSV de travail pret a l'emploi

Distinction a conserver :
  - ce module produit des messages COMMERCIAUX (prospection d'entreprises clientes) ;
  - il ne produit jamais d'offre d'emploi destinee a un candidat (voir module dedie a venir).

Utilisation :
  python yallah_prospection.py --check                  # valide les fiches, code retour 1 si anomalie
  python yallah_prospection.py --ville Casablanca        # CSV filtre
  python yallah_prospection.py --segment hotel --langue darija
  python yallah_prospection.py --sans-messages           # contacts seuls, sans texte

Le CSV de sortie est un artefact de travail : il est ignore par Git (*.csv dans .gitignore).
"""

import argparse
import csv
import json
import os
import re
import sys
from urllib.parse import quote

from yallah_b2c import PATTERNS_INTERDITS as PATTERNS_B2C

# ---------------------------------------------------------------------------
# Coordonnees officielles Yallah Services (identiques au module B2C)
# ---------------------------------------------------------------------------
WHATSAPP_NUMBER = "212691733585"

SOURCE_PAR_DEFAUT = "prospects_b2b.json"
DATE_ATTENDUE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CHAMPS_REQUIS = ["nom", "segment", "ville", "zone", "source_url", "date_consultation", "niveau"]

# ---------------------------------------------------------------------------
# Zones de la phase 1 (source unique : la fiche de presentation, reprise du
# module B2C pour eviter toute divergence entre les deux modules).
# ---------------------------------------------------------------------------
try:
    from yallah_b2c import PHASE_1, PHASE_2, PHASE_3
except ImportError:  # pragma: no cover
    PHASE_1, PHASE_2, PHASE_3 = {}, (), ()

ZONES_PHASE_1 = {
    ville: set(bloc[villes].keys())
    for ville, bloc in PHASE_1.items()
    for villes in bloc
}

# ---------------------------------------------------------------------------
# Segments B2B : libelle, poids commercial, besoins types
# ---------------------------------------------------------------------------
SEGMENTS = {
    "hotel": {
        "libelle": "hotel",
        "poids": 3,
        "besoins": ["PRP", "CUI", "SRV", "REN"],
        "accroche": "l'entretien des chambres et des espaces communs, la cuisine et le service",
    },
    "riad": {
        "libelle": "riad / maison d'hotes",
        "poids": 3,
        "besoins": ["MAI", "CUI", "PRP"],
        "accroche": "l'entretien de la maison et la cuisine",
    },
    "restaurant": {
        "libelle": "restaurant / cafe",
        "poids": 2,
        "besoins": ["CUI", "SRV", "PRP"],
        "accroche": "la plonge, le service en salle et l'entretien",
    },
    "construction": {
        "libelle": "construction / chantier",
        "poids": 2,
        "besoins": ["NET", "GAR"],
        "accroche": "le nettoyage de fin de chantier et le gardiennage",
    },
    "nettoyage": {
        "libelle": "societe de nettoyage",
        "poids": 2,
        "besoins": ["NET", "PRP"],
        "accroche": "des renforts d'agents pour vos prestations",
    },
    "commerce": {
        "libelle": "commerce / centre commercial",
        "poids": 2,
        "besoins": ["PRP", "GAR", "REN"],
        "accroche": "l'entretien des espaces et le gardiennage",
    },
    "evenementiel": {
        "libelle": "evenementiel / traiteur",
        "poids": 3,
        "besoins": ["REN", "SRV", "CUI"],
        "accroche": "les extras de service, la plonge et le renfort evenementiel",
    },
    "porteur_projet": {
        "libelle": "porteur de projet",
        "poids": 1,
        "besoins": ["NET", "GAR"],
        "accroche": "la main-d'oeuvre pour vos travaux et la mise en service de vos locaux",
    },
}

BESOINS_B2B = {
    "PRP": "proprete et entretien des locaux",
    "CUI": "cuisine et plonge",
    "SRV": "service en salle / extra",
    "NET": "nettoyage de fin de chantier",
    "GAR": "gardiennage",
    "MAI": "personnel de maison",
    "REN": "renfort journalier evenementiel",
}

# ---------------------------------------------------------------------------
# Garde-fou : on reprend les motifs du B2C et on ajoute les promesses
# commerciales typiques d'un message de prospection.
# ---------------------------------------------------------------------------
PATTERNS_SPECIFIQUES = [
    (r"\b(nos tarifs|notre tarif|prix attractifs?|pas cher|le moins cher|tarif preferentiel)\b", "promesse tarifaire"),
    (r"\b(devis (gratuit|immediat)|etude gratuite|audit gratuit)\b", "gratuite annoncee"),
    (r"\b(disponibles? immediatement|sous \d+ h|en \d+ h)\b", "disponibilite ou delai"),
    (r"\b(profils? verifies?|candidats? verifies?|personnel (verifie|qualifie|experimente))\b", "qualification ou verification annoncee"),
    (r"\b(sans engagement|satisfaction garantie|vous garantit|nous garantissons)\b", "engagement commercial"),
    (r"\b(partenaire (numero 1|n° ?1)|leader du secteur|reference absolue)\b", "superlatif non etabli"),
]

PATTERNS_INTERDITS = PATTERNS_B2C + PATTERNS_SPECIFIQUES


def verifier_message(texte: str) -> list:
    """Retourne la liste des alertes ; vide = aucune alerte detectee."""
    alertes = []
    bas = (texte or "").lower()
    for motif, libelle in PATTERNS_INTERDITS:
        trouve = re.search(motif, bas, flags=re.IGNORECASE)
        if trouve:
            alertes.append(f"{libelle} : « {trouve.group(0).strip()} »")
    return alertes


# ---------------------------------------------------------------------------
# Chargement et validation
# ---------------------------------------------------------------------------
def charger(chemin: str) -> dict:
    if not os.path.exists(chemin):
        sys.exit(f"Fichier source introuvable : {chemin}")
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def valider_fiche(p: dict) -> list:
    """Anomalies bloquantes d'une fiche prospect."""
    anomalies = []
    for champ in CHAMPS_REQUIS:
        if not str(p.get(champ, "")).strip():
            anomalies.append(f"champ manquant : {champ}")

    url = str(p.get("source_url", ""))
    if url and not url.startswith("http"):
        anomalies.append("source_url n'est pas une URL")

    date = str(p.get("date_consultation", ""))
    if date and not DATE_ATTENDUE.match(date):
        anomalies.append("date_consultation attendue au format AAAA-MM-JJ")

    if p.get("niveau") not in {"A", "B", "C"}:
        anomalies.append("niveau attendu : A, B ou C")

    if p.get("phase") not in (1, 2, 3):
        anomalies.append("phase attendue : 1, 2 ou 3")

    if p.get("segment") not in SEGMENTS:
        anomalies.append(f"segment inconnu : {p.get('segment')}")

    if not str(p.get("tel", "")).strip() and not str(p.get("email", "")).strip():
        if p.get("niveau") != "C":
            anomalies.append("aucun contact direct : niveau C attendu")

    return anomalies


# ---------------------------------------------------------------------------
# Priorisation
# ---------------------------------------------------------------------------
def zone_phase_1(ville: str, zone: str) -> bool:
    return zone in ZONES_PHASE_1.get(ville, set())


def phase_de(p: dict) -> int:
    """Phase déclarée dans la fiche, sinon déduite de la ville."""
    if p.get("phase") in (1, 2, 3):
        return p["phase"]
    if p.get("ville") in PHASE_2:
        return 2
    if p.get("ville") in PHASE_3:
        return 3
    return 1


def priorite(p: dict) -> tuple:
    """Score de 0 a 10 + libelle. Heuristique d'ordonnancement, pas une prevision."""
    score = 2
    score += SEGMENTS.get(p.get("segment"), {}).get("poids", 0)
    score += 3 if zone_phase_1(p.get("ville", ""), p.get("zone", "")) else 0
    score += {1: 1, 2: 0, 3: 0}.get(phase_de(p), 0)
    score += {"A": 2, "B": 1, "C": 0}.get(p.get("niveau"), 0)
    if p.get("anomalies"):
        score -= 1
    score = max(0, min(10, score))
    libelle = "haute" if score >= 8 else ("moyenne" if score >= 6 else "basse")
    return score, libelle


# ---------------------------------------------------------------------------
# Message commercial (offre destinee a un client entreprise)
# ---------------------------------------------------------------------------
def message_commercial(p: dict, langue: str) -> str:
    segment = SEGMENTS.get(p["segment"], {})
    accroche = segment.get("accroche", "vos besoins en personnel")
    besoins = ", ".join(BESOINS_B2B[c] for c in segment.get("besoins", [])[:3])
    etab = p["nom"]

    if langue == "fr":
        return (
            f"Bonjour {etab},\n\n"
            f"Je suis [prenom] de Yallah Services. Nous mettons en relation les etablissements "
            f"de {p['ville']} avec du personnel pour {accroche} : {besoins}.\n\n"
            f"Nous travaillons sur trois formats : permanent, temporaire et renfort journalier, "
            f"selon ce dont vous avez besoin.\n\n"
            f"Seriez-vous disponible pour un echange de dix minutes afin que nous comprenions "
            f"votre organisation et verifiions si nous pouvons y repondre ?\n\n"
            f"Bien a vous,\n[signature]\nVotre besoin en personnel, notre priorite."
        )

    if langue == "darija":
        return (
            f"Salam {etab},\n\n"
            f"Ana [smiya] mn Yallah Services. Kantkhelo m3a l2etablissements f {p['ville']} "
            f"bach nwefro lihom personnel l {accroche} : {besoins}.\n\n"
            f"Khanghdmo b tlata formats : permanent, temporaire, w renfort b nhar.\n\n"
            f"Ila 3ndkom chi haja f had lmajal, n9dro ndiro m3a b3dna wahed mokala "
            f"d 10 daqiqat bach nfahmo lkhedma dyalkom.\n\n"
            f"Chokran, [signature]\nVotre besoin en personnel, notre priorite."
        )

    return (
        f"مرحبا {etab}،\n\n"
        f"أنا [الاسم] من Yallah Services. نعمل مع المؤسسات في {p['ville']} "
        f"لتوفير الموظفين من أجل {accroche}: {besoins}.\n\n"
        f"نعمل بثلاث صيغ: دائم، مؤقت، وتعزيز يومي، حسب حاجتكم.\n\n"
        f"هل يمكننا التحدث عشر دقائق لفهم طريقة عملكم ومعرفة إن كان بإمكاننا تلبية حاجتكم؟\n\n"
        f"مع التحية، [التوقيع]\nVotre besoin en personnel, notre priorite."
    )


def lien_whatsapp(p: dict) -> str:
    message = f"Bonjour, je vous contacte de la part de Yallah Services au sujet de {p['nom']}."
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
COLONNES = [
    "ref", "nom", "segment", "phase", "ville", "zone", "zone_phase1", "adresse",
    "tel", "email", "site", "source_url", "date_consultation", "niveau",
    "besoins_probables", "angle", "score", "priorite", "anomalies_fiche",
    "message", "alertes_message", "statut", "lien_whatsapp",
]


def construire_lignes(prospects: list, langue: str, avec_messages: bool) -> list:
    lignes = []
    for i, p in enumerate(prospects, start=1):
        score, libelle = priorite(p)
        anomalies = valider_fiche(p)
        message = message_commercial(p, langue) if avec_messages else ""
        alertes = verifier_message(message) if message else []

        if anomalies:
            statut = "A CORRIGER - fiche non sourcee"
        elif alertes:
            statut = "BLOQUE - message a corriger"
        else:
            statut = "a valider"

        lignes.append({
            "ref": f"B2B-{i:03d}",
            "nom": p.get("nom", ""),
            "segment": SEGMENTS.get(p.get("segment"), {}).get("libelle", p.get("segment", "")),
            "phase": phase_de(p),
            "ville": p.get("ville", ""),
            "zone": p.get("zone", ""),
            "zone_phase1": "oui" if zone_phase_1(p.get("ville", ""), p.get("zone", "")) else "non",
            "adresse": p.get("adresse", ""),
            "tel": p.get("tel", ""),
            "email": p.get("email", ""),
            "site": p.get("site", ""),
            "source_url": p.get("source_url", ""),
            "date_consultation": p.get("date_consultation", ""),
            "niveau": p.get("niveau", ""),
            "besoins_probables": ", ".join(BESOINS_B2B.get(c, c) for c in p.get("besoins_probables", [])),
            "angle": p.get("angle", ""),
            "score": score,
            "priorite": libelle,
            "anomalies_fiche": " | ".join(anomalies),
            "message": message.replace("\n", " / ") if message else "",
            "alertes_message": " | ".join(alertes),
            "statut": statut,
            "lien_whatsapp": lien_whatsapp(p),
        })
    return lignes


def main():
    parser = argparse.ArgumentParser(description="Yallah Services - prospection B2B phase 1")
    parser.add_argument("--source", default=SOURCE_PAR_DEFAUT, help="fichier JSON de prospects")
    parser.add_argument("--sortie", default="prospects_b2b.csv", help="CSV de sortie")
    parser.add_argument("--ville", help="filtrer par ville")
    parser.add_argument("--segment", choices=sorted(SEGMENTS), help="filtrer par segment")
    parser.add_argument("--niveau", choices=["A", "B", "C"], help="filtrer par niveau de verification")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], help="filtrer par phase (1, 2 ou 3)")
    parser.add_argument("--langue", choices=["fr", "darija", "arabe"], default="fr")
    parser.add_argument("--sans-messages", action="store_true", help="contacts seuls, sans texte")
    parser.add_argument("--check", action="store_true", help="validation seule, sans ecriture CSV")
    args = parser.parse_args()

    data = charger(args.source)
    prospects = data.get("prospects", [])
    if not prospects:
        sys.exit("Aucun prospect dans le fichier source.")

    if args.ville:
        prospects = [p for p in prospects if p.get("ville", "").lower() == args.ville.lower()]
    if args.segment:
        prospects = [p for p in prospects if p.get("segment") == args.segment]
    if args.niveau:
        prospects = [p for p in prospects if p.get("niveau") == args.niveau]
    if args.phase:
        prospects = [p for p in prospects if phase_de(p) == args.phase]
    if not prospects:
        sys.exit("Aucun prospect ne correspond a ces filtres.")

    lignes = construire_lignes(prospects, args.langue, not args.sans_messages)
    lignes.sort(key=lambda l: (l["phase"], -l["score"], l["ville"], l["nom"]))

    bloquantes = [l for l in lignes if l["statut"] != "a valider"]

    if args.check:
        print(f"{len(lignes)} fiche(s) verifiee(s), {len(bloquantes)} a corriger.")
        for l in bloquantes:
            print(f"  - {l['ref']} {l['nom']} : {l['statut']} ({l['anomalies_fiche'] or l['alertes_message']})")
        sys.exit(1 if bloquantes else 0)

    with open(args.sortie, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLONNES)
        writer.writeheader()
        writer.writerows(lignes)

    print(f"{len(lignes)} prospect(s) ecrit(s) dans {args.sortie}")
    if bloquantes:
        print(f"Attention : {len(bloquantes)} fiche(s) a corriger ou message(s) bloque(s) avant envoi.")


if __name__ == "__main__":
    main()
