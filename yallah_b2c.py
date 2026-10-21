#!/usr/bin/env python3
"""
Yallah Services - Module B2C (v1)

Ce que fait ce script :
  1. Construit la matrice  zone x besoin  (phase 1 de la fiche de présentation)
  2. Génère pour chaque case une référence et un lien WhatsApp codé (wa.me)
  3. Prépare (ou génère via l'API Claude) un texte de publication par case
  4. Contrôle chaque texte avec les règles de la section 10 (rien d'inventé)
  5. Exporte le tout dans un CSV, statut "à valider"

Utilisation :
  python yallah_b2c.py --dry-run                       # matrice + liens, sans IA
  python yallah_b2c.py --plateforme instagram --langue darija --limit 10
  python yallah_b2c.py --ville Casablanca --besoin NOU --plateforme tiktok

Pour la génération par IA :
  pip install anthropic
  export ANTHROPIC_API_KEY="..."
  export YALLAH_MODEL="claude-sonnet-5-5"   # optionnel
"""

import argparse
import csv
import os
import re
import sys
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Coordonnées officielles (fiche de présentation, section 7) - ne pas modifier
# ---------------------------------------------------------------------------
WHATSAPP_NUMBER = "212691733585"  # +212 691733585

# ---------------------------------------------------------------------------
# Besoins B2C (fiche, section 2.A)
# ---------------------------------------------------------------------------
BESOINS = {
    "MEN": "femme de ménage",
    "NOU": "nounou / garde d'enfants",
    "CUI": "cuisinière à domicile",
    "CHA": "chauffeur",
    "AGE": "aide aux personnes âgées",
    "GAR": "gardien / vigile",
    "PON": "nettoyage ponctuel (grand ménage, après déménagement)",
}

# ---------------------------------------------------------------------------
# Phase 1 (fiche, section 3) : zone -> besoins à fort potentiel indiqués
# Cartographie indicative : à ajuster avec vos chiffres réels de demandes.
# ---------------------------------------------------------------------------
PHASE_1 = {
    "Casablanca": {
        "CAS": {
            "Anfa": ("ANF", ["MEN", "CUI", "CHA"]),
            "Aïn Diab": ("AND", ["MEN", "PON"]),
            "Californie": ("CAL", ["MEN", "NOU"]),
            "Racine": ("RAC", ["MEN"]),
            "Gauthier": ("GAU", ["MEN", "NOU"]),
            "CIL": ("CIL", ["MEN", "NOU"]),
            "CFC": ("CFC", ["NOU", "MEN"]),
        }
    },
    "Bouskoura": {
        "BSK": {
            "Ville Verte": ("VVE", ["MEN", "NOU", "CUI"]),
        }
    },
    "Rabat": {
        "RAB": {
            "Hay Riad": ("HRI", ["NOU", "MEN"]),
            "Souissi": ("SOU", ["MEN", "CHA"]),
            "Les Ambassadeurs": ("AMB", ["MEN", "CUI", "CHA"]),
            "Agdal": ("AGD", ["MEN", "AGE"]),
        }
    },
    "Marrakech": {
        "MAR": {
            "Palmeraie": ("PAL", ["CUI", "MEN"]),
            "Hivernage": ("HIV", ["MEN", "PON"]),
            "Agdal": ("AGM", ["MEN"]),
            "Targa": ("TAR", ["NOU", "MEN"]),
            "Amelkis": ("AME", ["MEN", "PON"]),
        }
    },
}

PLATEFORMES = {
    "tiktok": "script vidéo court (accroche de 2 secondes, 3 phrases maximum, appel à l'action)",
    "instagram": "légende courte et dynamique avec 3 à 5 hashtags locaux",
    "facebook": "publication courte et claire, adaptée à un groupe de quartier ou de ville",
    "whatsapp": "message de statut très court",
}

LANGUES = {
    "francais": "français simple et professionnel",
    "darija": "darija marocaine écrite en lettres latines, ton de proximité, compréhensible par tous",
    "arabe": "arabe standard simple",
}

# ---------------------------------------------------------------------------
# Base de faits (fiche, sections 1, 9, 10) : seule source autorisée pour l'IA
# ---------------------------------------------------------------------------
BASE_DE_FAITS = """\
Yallah Services est une structure spécialisée dans la recherche et la mise en relation de personnel
pour les particuliers et les entreprises au Maroc.
Services aux particuliers : femmes de ménage, nounous et garde d'enfants, aide aux personnes âgées,
cuisinières à domicile, gardiens, chauffeurs, nettoyage ponctuel.
Villes d'intervention : Casablanca, Rabat, Marrakech, Tanger, Agadir, Fès, Kénitra, Mohammedia, Témara, Salé.
Besoins : personnel permanent, temporaire ou renfort journalier, selon la demande du client.
Contact prioritaire : WhatsApp. Signature : « Votre besoin en personnel, notre priorité. »
Ton : professionnel, chaleureux, rassurant, simple, dynamique, local, orienté action.
"""

REGLES = """\
INTERDIT d'inventer ou d'affirmer : prix, salaires, commissions, frais ; délais de recrutement ou de mise en
relation ; garanties de résultat, de fiabilité ou de remplacement ; disponibilité immédiate de candidats ;
qualifications, expériences ou références de candidats ; vérifications d'identité ou contrôles d'antécédents ;
conditions contractuelles et modalités de paiement ; quartiers desservis pour une mission précise ;
certifications ou agréments ; coordonnées autres que celles fournies.
Ne jamais promettre un recrutement. Utiliser uniquement les faits fournis.
Terminer par un appel à l'action vers WhatsApp (sans écrire de numéro dans le texte : le lien est ajouté à part).
"""

# ---------------------------------------------------------------------------
# Garde-fou automatique (section 10)
# ---------------------------------------------------------------------------
PATTERNS_INTERDITS = [
    (r"\b\d[\d\s.,]*\s?(dh|dhs|mad|dirhams?|€|eur|euros?)\b", "prix ou montant"),
    (r"\b(gratuit|gratuite|sans frais|sans commission|à partir de)\b", "promesse tarifaire"),
    (r"\b(24\s?h|48\s?h|72\s?h|\d+\s?(heures?|jours?|semaines?))\b", "délai chiffré"),
    (r"\b(immédiat\w*|dès aujourd'hui|le jour même|rapidement garanti|en un clin d'œil)\b", "disponibilité ou délai"),
    (r"\b(garanti\w*|garantie|satisfait ou|remplacement assuré|remplacé)\b", "garantie"),
    (r"\b(vérifi\w+|contrôl\w+ d'antécédents|casier|identité contrôlée|références vérifiées)\b", "vérification annoncée"),
    (r"\b(certifi\w+|agréé\w*|labellis\w+|autorisé par)\b", "certification ou agrément"),
    (r"(\b100\s?%|\bmeilleur\w* du maroc\b|\bn°\s?1\b|\bnuméro 1\b)", "superlatif non établi"),
    (r"(\+?212|0)[\s.]?[567]\d{2}[\s.]?\d{2}[\s.]?\d{2}[\s.]?\d{2}", "numéro de téléphone dans le texte"),
]


def verifier_contenu(texte: str) -> list:
    """Retourne la liste des alertes ; vide = aucune alerte détectée."""
    alertes = []
    bas = texte.lower()
    for motif, libelle in PATTERNS_INTERDITS:
        trouve = re.search(motif, bas, flags=re.IGNORECASE)
        if trouve:
            alertes.append(f"{libelle} : « {trouve.group(0).strip()} »")
    return alertes


# ---------------------------------------------------------------------------
# Matrice, références, liens
# ---------------------------------------------------------------------------
def construire_matrice(ville=None, besoin=None):
    lignes = []
    for nom_ville, bloc in PHASE_1.items():
        if ville and ville.lower() != nom_ville.lower():
            continue
        for code_ville, zones in bloc.items():
            for nom_zone, (code_zone, besoins) in zones.items():
                for code_besoin in besoins:
                    if besoin and besoin.upper() != code_besoin:
                        continue
                    lignes.append(
                        {
                            "ref": f"{code_ville}-{code_zone}-{code_besoin}",
                            "ville": nom_ville,
                            "zone": nom_zone,
                            "code_besoin": code_besoin,
                            "besoin": BESOINS[code_besoin],
                        }
                    )
    return lignes


def lien_whatsapp(ligne: dict) -> str:
    """Lien wa.me avec message prérempli contenant la référence de la case."""
    message = (
        f"Bonjour, je cherche : {ligne['besoin']} ({ligne['zone']}, {ligne['ville']}). "
        f"Réf. {ligne['ref']}"
    )
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}"


# ---------------------------------------------------------------------------
# Génération de texte
# ---------------------------------------------------------------------------
def construire_prompt(ligne: dict, plateforme: str, langue: str) -> str:
    return f"""Tu rédiges une publication pour Yallah Services (cible : PARTICULIER, B2C).

FAITS AUTORISÉS :
{BASE_DE_FAITS}
RÈGLES ABSOLUES :
{REGLES}
CONSIGNE :
- Besoin visé : {ligne['besoin']}
- Zone ciblée : {ligne['zone']}, {ligne['ville']} (cite la zone comme public visé, sans affirmer que
  tel quartier est desservi pour une mission précise)
- Format : {PLATEFORMES[plateforme]}
- Langue : {LANGUES[langue]}
Réponds uniquement avec le texte final, sans commentaire."""


def generer_texte(prompt: str) -> str:
    try:
        import anthropic
    except ImportError:
        sys.exit("Installez le SDK : pip install anthropic")
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("Variable ANTHROPIC_API_KEY manquante.")
    client = anthropic.Anthropic()
    modele = os.getenv("YALLAH_MODEL", "claude-sonnet-5-5")
    reponse = client.messages.create(
        model=modele,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in reponse.content if b.type == "text").strip()


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Yallah Services - module B2C")
    p.add_argument("--ville", help="Casablanca, Bouskoura, Rabat, Marrakech")
    p.add_argument("--besoin", help="Code : " + ", ".join(BESOINS))
    p.add_argument("--plateforme", choices=PLATEFORMES, default="instagram")
    p.add_argument("--langue", choices=LANGUES, default="francais")
    p.add_argument("--limit", type=int, default=0, help="nombre maximum de cases (0 = toutes)")
    p.add_argument("--dry-run", action="store_true", help="matrice et liens uniquement, sans IA")
    p.add_argument("--sortie", default="contenus_b2c.csv")
    args = p.parse_args()

    if args.besoin and args.besoin.upper() not in BESOINS:
        sys.exit(f"Besoin inconnu. Codes valides : {', '.join(BESOINS)}")

    matrice = construire_matrice(args.ville, args.besoin)
    if not matrice:
        sys.exit("Aucune case ne correspond à ces filtres.")
    if args.limit:
        matrice = matrice[: args.limit]

    colonnes = ["ref", "ville", "zone", "besoin", "plateforme", "langue",
                "texte", "lien_whatsapp", "alertes", "statut"]
    with open(args.sortie, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=colonnes)
        writer.writeheader()
        for ligne in matrice:
            texte, alertes = "", []
            if not args.dry_run:
                texte = generer_texte(construire_prompt(ligne, args.plateforme, args.langue))
                alertes = verifier_contenu(texte)
            statut = "BLOQUÉ - à corriger" if alertes else "à valider"
            writer.writerow(
                {
                    "ref": ligne["ref"],
                    "ville": ligne["ville"],
                    "zone": ligne["zone"],
                    "besoin": ligne["besoin"],
                    "plateforme": args.plateforme,
                    "langue": args.langue,
                    "texte": texte,
                    "lien_whatsapp": lien_whatsapp(ligne),
                    "alertes": " | ".join(alertes),
                    "statut": statut if not args.dry_run else "matrice seule",
                }
            )

    print(f"{len(matrice)} case(s) écrite(s) dans {args.sortie}")


if __name__ == "__main__":
    main()
