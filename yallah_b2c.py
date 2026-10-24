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
import html
import os
import re
import sys
import unicodedata
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Coordonnées officielles (fiche de présentation, section 7) - ne pas modifier
# ---------------------------------------------------------------------------
WHATSAPP_NUMBER = "212691733585"  # +212 691733585
SITE_WEB_DEFAUT = "https://yallahservices-one.vercel.app"


def site_web_officiel() -> str:
    """URL canonique du site web officiel Yallah Services (sans slash final)."""
    valeur = os.getenv("YALLAH_SITE_WEB", SITE_WEB_DEFAUT).strip().rstrip("/")
    if valeur.endswith("/index.html"):
        valeur = valeur[: -len("/index.html")]
    return valeur or SITE_WEB_DEFAUT


SITE_WEB = site_web_officiel()

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

BESOINS_SLUGS = {
    "MEN": "femme-de-menage",
    "NOU": "nounou-garde-enfants",
    "CUI": "cuisiniere-a-domicile",
    "CHA": "chauffeur",
    "AGE": "aide-personnes-agees",
    "GAR": "gardien-vigile",
    "PON": "nettoyage-ponctuel",
}


def slugify_ascii(texte: str) -> str:
    """Convertit un libellé français en segment d'URL ASCII propre."""
    decomp = unicodedata.normalize("NFKD", texte or "")
    sans_accents = "".join(c for c in decomp if not unicodedata.combining(c))
    propre = re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")
    return propre

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

# ---------------------------------------------------------------------------
# Phases 2 et 3 (fiche, section 3) : villes entières, quartiers non précisés
# ---------------------------------------------------------------------------
PHASE_2 = ("Tanger", "Agadir", "Mohammedia", "Kénitra")
PHASE_3 = ("Fès", "El Jadida", "Témara/Harhoura")

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
Zones d'intervention phase 1 : Casablanca (Anfa, Aïn Diab, Californie, Racine, Gauthier, CIL, CFC),
Bouskoura (Ville Verte), Rabat (Hay Riad, Souissi, Les Ambassadeurs, Agdal),
Marrakech (Palmeraie, Hivernage, Agdal, Targa, Amelkis).
Villes phase 2 : Tanger, Agadir, Mohammedia, Kénitra.
Villes phase 3 : Fès, El Jadida, Témara/Harhoura.
Besoins : personnel permanent, temporaire ou renfort journalier, selon la demande du client.
Contact prioritaire : WhatsApp. Site web officiel : https://yallahservices-one.vercel.app
Signature : « Votre besoin en personnel, notre priorité. »
Ton : professionnel, chaleureux, rassurant, simple, dynamique, local, orienté action.
"""

REGLES = """\
INTERDIT d'inventer ou d'affirmer : prix, salaires, commissions, frais ; délais de recrutement ou de mise en
relation ; garanties de résultat, de fiabilité ou de remplacement ; disponibilité immédiate de candidats ;
qualifications, expériences ou références de candidats ; vérifications d'identité ou contrôles d'antécédents ;
conditions contractuelles et modalités de paiement ; quartiers desservis pour une mission précise ;
certifications ou agréments ; coordonnées autres que celles fournies (seul le site officiel fourni est autorisé).
Ne jamais promettre un recrutement. Utiliser uniquement les faits fournis.
Terminer par un appel à l'action vers WhatsApp (sans écrire de numéro dans le texte : le lien WhatsApp est ajouté à part ; le lien du site officiel https://yallahservices-one.vercel.app peut être mentionné tel quel).
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


def urls_non_officielles(texte: str) -> list:
    """Signale toute URL présente dans le texte qui n'est pas le site officiel Yallah Services."""
    officiel = site_web_officiel().lower()
    autorisees = {officiel, officiel + "/index.html"}
    alertes = []
    for brut in re.findall(r"https?://\S+", texte or "", flags=re.IGNORECASE):
        propre = brut.rstrip(".,;:!?)\"'>/").lower()
        if propre not in autorisees:
            alertes.append(f"url non officielle : « {brut} »")
    return alertes


def verifier_contenu(texte: str) -> list:
    """Retourne la liste des alertes ; vide = aucune alerte détectée."""
    alertes = []
    bas = texte.lower()
    for motif, libelle in PATTERNS_INTERDITS:
        trouve = re.search(motif, bas, flags=re.IGNORECASE)
        if trouve:
            alertes.append(f"{libelle} : « {trouve.group(0).strip()} »")
    alertes.extend(urls_non_officielles(texte))
    return alertes


# ---------------------------------------------------------------------------
# Matrice, références, liens et pages locales SEO (canal entrant A1)
# ---------------------------------------------------------------------------
def slug_case(code_besoin: str, nom_zone: str, nom_ville: str) -> str:
    """Construit le slug SEO lisible d'une case quartier × besoin (ex. femme-de-menage-californie-casablanca)."""
    base_besoin = BESOINS_SLUGS.get(code_besoin, slugify_ascii(BESOINS.get(code_besoin, code_besoin)))
    return f"{base_besoin}-{slugify_ascii(nom_zone)}-{slugify_ascii(nom_ville)}"


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
                    ref = f"{code_ville}-{code_zone}-{code_besoin}"
                    slug = slug_case(code_besoin, nom_zone, nom_ville)
                    lignes.append(
                        {
                            "ref": ref,
                            "slug": slug,
                            "url_locale": f"/services/{slug}",
                            "lien_demande": f"/demande?ref={ref}&source=site_formulaire",
                            "ville": nom_ville,
                            "zone": nom_zone,
                            "code_besoin": code_besoin,
                            "besoin": BESOINS[code_besoin],
                            "site_web": site_web_officiel(),
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


def trouver_case_b2c(identifiant: str):
    """Résout une case quartier × besoin par référence (CAS-CAL-MEN) ou par slug SEO."""
    cle = (identifiant or "").strip().strip("/")
    if not cle:
        return None
    cle_upper = cle.upper()
    cle_lower = cle.lower()
    for ligne in construire_matrice():
        if ligne["ref"] == cle_upper or ligne["slug"] == cle_lower:
            res = dict(ligne)
            res["lien"] = lien_whatsapp(res)
            return res
    dec = decoder_reference_b2c(cle_upper)
    if dec:
        dec["lien"] = lien_whatsapp(dec)
        return dec
    return None


def decoder_reference_b2c(texte: str):
    """Extrait une référence B2C (ex. CAS-ANF-MEN) d'un texte entrant et retourne ville/zone/besoin."""
    if not texte:
        return None
    par_ref = {ligne["ref"]: dict(ligne) for ligne in construire_matrice()}
    villes_zones = {}
    for nom_ville, bloc in PHASE_1.items():
        for code_ville, zones in bloc.items():
            for nom_zone, (code_zone, _) in zones.items():
                villes_zones[(code_ville, code_zone)] = (nom_ville, nom_zone)
    for candidat in re.findall(r"\b([A-Z]{3})-([A-Z]{3})-([A-Z]{3})\b", texte.upper()):
        complet = "-".join(candidat)
        if complet in par_ref:
            return par_ref[complet]
        code_ville, code_zone, code_besoin = candidat
        if (code_ville, code_zone) in villes_zones and code_besoin in BESOINS:
            nom_ville, nom_zone = villes_zones[(code_ville, code_zone)]
            slug = slug_case(code_besoin, nom_zone, nom_ville)
            return {
                "ref": complet,
                "slug": slug,
                "url_locale": f"/services/{slug}",
                "lien_demande": f"/demande?ref={complet}&source=site_formulaire",
                "ville": nom_ville,
                "zone": nom_zone,
                "code_besoin": code_besoin,
                "besoin": BESOINS[code_besoin],
                "site_web": site_web_officiel(),
            }
    return None


_STYLE_PUBLIC_SEO = (
    "body{font:15px/1.6 system-ui;background:#f4f7f0;color:#18352d;margin:0;padding:30px 16px}"
    "main{max-width:760px;margin:auto;background:white;padding:30px;border:1px solid #e1e8dc;border-radius:12px}"
    "h1{font-size:27px;line-height:1.25;margin-bottom:8px}h2{font-size:19px;margin-top:26px}"
    "label{display:block;margin:14px 0}input,textarea,select{box-sizing:border-box;width:100%;font:inherit;border:1px solid #cbd6c4;border-radius:6px;padding:10px}"
    "input[type=checkbox]{width:auto}button,.cta{display:inline-block;text-decoration:none;background:#236b50;color:white;border:0;border-radius:6px;padding:12px 18px;font:inherit;cursor:pointer}"
    ".cta-outline{display:inline-block;text-decoration:none;background:#edf3e7;color:#18352d;border:1px solid #cbd6c4;border-radius:6px;padding:10px 15px;font-size:14px}"
    ".notice{background:#edf3e7;padding:15px;border-radius:8px;font-size:13px;margin:16px 0}"
    ".tag{display:inline-block;background:#edf3e7;color:#236b50;padding:3px 9px;border-radius:999px;font-size:12px;font-weight:600}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin:14px 0}"
    ".tile{border:1px solid #e1e8dc;border-radius:8px;padding:12px;background:#fafcf8}"
    ".tile a{color:#236b50;font-weight:600;text-decoration:none}"
    ".trap{display:none}#result{white-space:pre-wrap;margin-top:20px;font-weight:600}small{color:#657361}textarea{min-height:110px}"
)


def rendre_catalogue_services_html() -> bytes:
    """Page publique /services listant les pages SEO locales par ville, quartier et besoin (canal A1)."""
    matrice = construire_matrice()
    par_ville = {}
    for ligne in matrice:
        par_ville.setdefault(ligne["ville"], []).append(ligne)
    site = html.escape(site_web_officiel(), quote=True)
    sections = []
    for nom_ville, lignes in par_ville.items():
        tuiles = "".join(
            f'<div class="tile"><span class="tag">{html.escape(l["ref"])}</span>'
            f'<div><a href="{html.escape(l["url_locale"], quote=True)}">'
            f'{html.escape(l["besoin"].capitalize())} — {html.escape(l["zone"])}</a></div>'
            f'<small>{html.escape(l["ville"])} · <a href="{html.escape(lien_whatsapp(l), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">WhatsApp direct ↗</a></small></div>'
            for l in lignes
        )
        sections.append(f'<h2>{html.escape(nom_ville)}</h2><div class="grid">{tuiles}</div>')

    doc = (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        '<title>Services aux particuliers par quartier — Yallah Services</title>'
        '<meta name="description" content="Recherche et mise en relation de personnel de maison par quartier à Casablanca, Bouskoura, Rabat et Marrakech.">'
        f'<style>{_STYLE_PUBLIC_SEO}</style></head><body><main>'
        f'<div><strong>yallah ↗ · Services</strong> · <a href="{site}" target="_blank" rel="noopener noreferrer" style="color:#236b50;font-size:13px">Site officiel ↗</a>'
        ' · <a href="/demande" style="color:#236b50;font-size:13px">Formulaire général</a></div>'
        '<h1>Personnel de maison par quartier et besoin</h1>'
        '<p>Sélectionnez votre quartier et le besoin de votre foyer pour transmettre votre demande avec une référence dédiée ou nous écrire directement sur WhatsApp.</p>'
        + "".join(sections)
        + '<div class="notice"><strong>Cadre Yallah Services</strong>'
        '<p>Structure de recherche et de mise en relation de personnel en format permanent, temporaire ou renfort journalier, selon votre demande. '
        "Aucun frais n'est demandé aux candidats (Code du travail, art. 480). "
        "Chaque demande est étudiée par notre équipe ; elle ne constitue pas une promesse de disponibilité.</p></div>"
        '</main></body></html>'
    )
    return doc.encode("utf-8")


def rendre_page_service_html(case: dict) -> bytes:
    """Page publique SEO par quartier × besoin (canal entrant A1 : formulaire prérempli + WhatsApp codé)."""
    besoin_cap = case["besoin"][:1].upper() + case["besoin"][1:]
    titre = f"{besoin_cap} — {case['zone']}, {case['ville']}"
    ref = case["ref"]
    wa = lien_whatsapp(case)
    site = site_web_officiel()
    autres = [
        l for l in construire_matrice(ville=case["ville"])
        if l["ref"] != ref
    ][:6]
    liens_autres = "".join(
        f'<div class="tile"><span class="tag">{html.escape(l["ref"])}</span> '
        f'<a href="{html.escape(l["url_locale"], quote=True)}">{html.escape(l["besoin"].capitalize())} — {html.escape(l["zone"])}</a></div>'
        for l in autres
    )
    msg_defaut = f"Bonjour, je souhaite vous confier une recherche de {case['besoin']} secteur {case['zone']} ({case['ville']}). Réf. {ref}"
    doc = (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f'<title>{html.escape(titre)} | Yallah Services</title>'
        f'<meta name="description" content="{html.escape(besoin_cap)} secteur {html.escape(case["zone"])} à {html.escape(case["ville"])} : partagez votre besoin avec Yallah Services (permanent, temporaire ou renfort journalier).">'
        f'<style>{_STYLE_PUBLIC_SEO}</style></head><body><main>'
        f'<div><strong>yallah ↗ · Services</strong> · <a href="/services" style="color:#236b50;font-size:13px">Tous les quartiers</a>'
        f' · <a href="{html.escape(site, quote=True)}" target="_blank" rel="noopener noreferrer" style="color:#236b50;font-size:13px">Site officiel ↗</a></div>'
        f'<p style="margin:14px 0 4px"><span class="tag">Référence {html.escape(ref)}</span></p>'
        f'<h1 id="title">{html.escape(titre)}</h1>'
        f'<p id="intro">Vous habitez du côté de {html.escape(case["zone"])} ({html.escape(case["ville"])}) et vous cherchez : '
        f'<strong>{html.escape(case["besoin"])}</strong> ? Yallah Services organise la recherche et la mise en relation de personnel '
        'selon le rythme de votre foyer : permanent, temporaire ou renfort journalier.</p>'
        f'<p><a class="cta" href="{html.escape(wa, quote=True)}" target="_blank" rel="noopener noreferrer">'
        f'Écrire sur WhatsApp ({html.escape(ref)}) ↗</a> '
        f'<a class="cta-outline" href="#public-form">Remplir le formulaire en ligne ↓</a></p>'
        f'<form id="public-form" data-b2c-ref="{html.escape(ref, quote=True)}" data-default-source="site_formulaire:{html.escape(ref, quote=True)}">'
        '<h2>Décrire votre besoin en ligne</h2>'
        '<div id="need-field"></div>'
        '<label>Nom<input name="name" maxlength="150" autocomplete="name" required></label>'
        f'<label>Ville<input name="city" maxlength="100" value="{html.escape(case["ville"], quote=True)}" required></label>'
        f'<label>Quartier / secteur<input name="zone" maxlength="100" value="{html.escape(case["zone"], quote=True)}" required></label>'
        '<label>Email<input type="email" name="email" maxlength="254" autocomplete="email"></label>'
        '<label>Téléphone<input name="tel" maxlength="40" autocomplete="tel"></label>'
        f'<label id="message-label">Votre besoin ({html.escape(ref)})<textarea name="message" maxlength="2000" required>{html.escape(msg_defaut)}</textarea></label>'
        '<label class="trap" aria-hidden="true">Site web<input name="website" tabindex="-1" autocomplete="off"></label>'
        '<div class="notice"><strong>Traitement de votre demande</strong>'
        '<p>Les informations sont utilisées par Yallah Services pour étudier votre demande et vous répondre. '
        'Ne transmettez pas de pièce d’identité, d’information de santé ou d’autre donnée sensible dans ce formulaire. '
        'Cette demande n’autorise pas des campagnes marketing. Pour toute question sur vos données : servicesyallah@gmail.com. '
        'Aucun frais n’est demandé aux candidats (Code du travail, art. 480).</p>'
        '<label><input name="acknowledge" type="checkbox" required> J’ai lu cette information et j’accepte le traitement nécessaire à ma demande.</label></div>'
        '<button type="submit">Transmettre ma demande</button></form>'
        '<div id="result" role="status"></div>'
        '<p><small>Votre demande est examinée par une personne de notre équipe ; elle ne constitue pas une promesse d’embauche ni de disponibilité. '
        f'Présentation générale sur {html.escape(site)}.</small></p>'
        + (f'<h2>Autres recherches à {html.escape(case["ville"])}</h2><div class="grid">{liens_autres}</div>' if liens_autres else '')
        + '<script src="/public.js"></script></main></body></html>'
    )
    return doc.encode("utf-8")


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
