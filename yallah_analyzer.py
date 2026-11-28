#!/usr/bin/env python3
"""yallah_analyzer.py — Analyse multilingue (FR / Darija / Arabe), scoring B2C & B2B (0–100),
détection STOP (Loi 09-08 / CNDP) et rédaction de messages contrôlés pour Yallah Services.

Principes absolus :
- Zéro invention : ne jamais inventer budget, urgence, disponibilité, contraintes familiales,
  préférences religieuses ou personnelles, type de contrat ou besoins non exprimés.
- Chaque information extraite doit être justifiée par un extrait explicite du texte ou un champ
  volontairement saisi par le demandeur.
- Aucun appel réseau ; 100 % bibliothèque standard Python.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import Any, Mapping

import yallah_b2c as b2c
import yallah_messages as ym
import yallah_prospection as yp

# ---------------------------------------------------------------------------
# 1. Détection STOP / Retrait immédiat (Loi 09-08 & CNDP)
# ---------------------------------------------------------------------------
STOP_EXACT_WORDS = {
    "stop",
    "stop sms",
    "stopsms",
    "arret",
    "arretez",
    "arrete",
    "desinscription",
    "desinscrire",
    "unsubscribe",
    "optout",
    "opt-out",
    "retirez-moi",
    "retirez moi",
    "supprimez-moi",
    "supprimez moi",
    "توقف",
    "قف",
    "إلغاء الاشتراك",
    "الغاء الاشتراك",
    "حبس",
    "وقف",
}

STOP_PHRASES = (
    "stop sms",
    "ne plus me contacter",
    "ne plus nous contacter",
    "ne me contactez plus",
    "ne nous contactez plus",
    "retirez-moi",
    "retirez moi",
    "retirer mon numero",
    "retirer mon email",
    "supprimez mon adresse",
    "supprimez mon numero",
    "veuillez me desinscrire",
    "je souhaite me desinscrire",
    "demande de desinscription",
    "desinscription",
    "arretez de m'ecrire",
    "arretez de me contacter",
    "arretez vos messages",
    "arretez",
    "ma t3awdch tkellemni",
    "ma tbqach tsift",
    "لا تتواصلوا معي",
    "إلغاء الاشتراك",
    "الغاء الاشتراك",
    "أوقف الرسائل",
    "توقف عن مراسلتي",
)


def _fold_latin(texte: str) -> str:
    decomp = unicodedata.normalize("NFKD", (texte or "").strip())
    sans_accents = "".join(c for c in decomp if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents).casefold().strip()


def detecter_stop(texte: str) -> tuple[bool, str]:
    """Détecte toute demande d'arrêt / retrait / STOP (FR, Darija, Arabe, EN).

    Retourne ``(est_stop, mot_cle_detecte)``.
    """
    brut = (texte or "").strip()
    if not brut:
        return False, ""
    # Retirer les lignes citées d'un email (>) pour éviter de déclencher sur notre propre footer STOP.
    non_cite = "\n".join(
        ligne for ligne in brut.splitlines() if not ligne.lstrip().startswith(">")
    ).strip()
    if not non_cite:
        return False, ""

    # Nettoyer la ponctuation périphérique pour un test exact sur message court.
    propre_orig = non_cite.strip(" \t\r\n.!?,;:'\"()[]{}؟،")
    propre_fold = _fold_latin(propre_orig)
    if propre_orig in STOP_EXACT_WORDS or propre_fold in STOP_EXACT_WORDS:
        return True, propre_orig[:80]

    # Mot "stop" isolé en début ou fin d'un message court (ex. "STOP merci" ou "merci, STOP").
    if re.fullmatch(r"(?:merci\s*,?\s*)?stop(?:\s+sms)?(?:\s+merci)?", propre_fold):
        return True, "STOP"

    # Première ligne égale à STOP / STOP SMS / Arrêtez.
    premiere_ligne = _fold_latin(non_cite.splitlines()[0].strip(" .!?,;:'\"؟،"))
    if premiere_ligne in STOP_EXACT_WORDS:
        return True, premiere_ligne.upper() if premiere_ligne.startswith("stop") else premiere_ligne

    # Phrases explicites de retrait (ignorer notre propre mention type "répondez STOP").
    sans_mention_footer = re.sub(
        r"si vous ne souhaitez (?:pas|plus) recevoir de messages[^.\n]*",
        "",
        propre_fold,
    )
    sans_mention_footer = re.sub(
        r"vous pouvez demander l['’]arret des communications[^.\n]*",
        "",
        sans_mention_footer,
    )
    for phrase in STOP_PHRASES:
        if phrase in sans_mention_footer or phrase in non_cite:
            return True, phrase

    return False, ""


# ---------------------------------------------------------------------------
# 2. Référentiels géographiques & services Yallah Services (Casablanca + Maroc)
# ---------------------------------------------------------------------------
QUARTIERS_CASABLANCA = {
    "anfa": "Anfa",
    "ain diab": "Aïn Diab",
    "aïn diab": "Aïn Diab",
    "californie": "Californie",
    "racine": "Racine",
    "gauthier": "Gauthier",
    "cil": "CIL",
    "cfc": "CFC",
    "casa finance city": "CFC",
    "maarif": "Maârif",
    "maârif": "Maârif",
    "bourgogne": "Bourgogne",
    "oasis": "Oasis",
    "palmiers": "Palmiers",
    "riviera": "Riviera",
    "beausejour": "Beauséjour",
    "beauséjour": "Beauséjour",
    "polo": "Polo",
    "sidi maarouf": "Sidi Maârouf",
    "sidi maârouf": "Sidi Maârouf",
    "val fleuri": "Val Fleuri",
    "2 mars": "2 Mars",
    "mers sultan": "Mers Sultan",
    "abdelmoumen": "Abdelmoumen",
    "hay hassani": "Hay Hassani",
    "oulfa": "Oulfa",
    "ain sebaa": "Aïn Sebaâ",
    "aïn sebaâ": "Aïn Sebaâ",
    "sidi bernoussi": "Sidi Bernoussi",
    "dar bouazza": "Dar Bouazza",
    "tamaris": "Tamaris",
    "bouskoura": "Bouskoura",
    "ville verte": "Ville Verte",
    "corniche": "Aïn Diab",
    "أنفا": "Anfa",
    "عين الذئاب": "Aïn Diab",
    "المعاريف": "Maârif",
    "كاليفورنيا": "Californie",
    "بوسكورة": "Bouskoura",
}

QUARTIERS_AUTRES_VILLES = {
    "hay riad": ("Rabat", "Hay Riad"),
    "souissi": ("Rabat", "Souissi"),
    "les ambassadeurs": ("Rabat", "Les Ambassadeurs"),
    "agdal": ("Rabat", "Agdal"),
    "palmeraie": ("Marrakech", "Palmeraie"),
    "hivernage": ("Marrakech", "Hivernage"),
    "targa": ("Marrakech", "Targa"),
    "amelkis": ("Marrakech", "Amelkis"),
    "gueliz": ("Marrakech", "Guéliz"),
}

VILLES_CONNUES = {
    "casablanca": ("Casablanca", 1),
    "casa": ("Casablanca", 1),
    "الدار البيضاء": ("Casablanca", 1),
    "كازا": ("Casablanca", 1),
    "bouskoura": ("Bouskoura", 1),
    "بوسكورة": ("Bouskoura", 1),
    "dar bouazza": ("Casablanca", 1),
    "rabat": ("Rabat", 1),
    "الرباط": ("Rabat", 1),
    "marrakech": ("Marrakech", 1),
    "مراكش": ("Marrakech", 1),
    "tanger": ("Tanger", 2),
    "طنجة": ("Tanger", 2),
    "agadir": ("Agadir", 2),
    "أكادير": ("Agadir", 2),
    "mohammedia": ("Mohammedia", 2),
    "المحمدية": ("Mohammedia", 2),
    "kenitra": ("Kénitra", 2),
    "kénitra": ("Kénitra", 2),
    "القنيطرة": ("Kénitra", 2),
    "fes": ("Fès", 3),
    "fès": ("Fès", 3),
    "فاس": ("Fès", 3),
    "el jadida": ("El Jadida", 3),
    "الجديدة": ("El Jadida", 3),
    "temara": ("Témara/Harhoura", 3),
    "témara": ("Témara/Harhoura", 3),
    "harhoura": ("Témara/Harhoura", 3),
    "تمارة": ("Témara/Harhoura", 3),
}

TYPES_PRESTATION = {
    "menage": {"libelle": "ménage / aide-ménagère", "code_b2c": "MEN"},
    "cuisine": {"libelle": "cuisine / aide-cuisinière", "code_b2c": "CUI"},
    "garde_enfants": {"libelle": "garde d'enfants / baby-sitter", "code_b2c": "NOU"},
    "aide_domicile": {"libelle": "aide à domicile (parent / proche)", "code_b2c": "AGE"},
    "personnel_maison": {"libelle": "personnel de maison", "code_b2c": "MEN"},
    "evenement": {"libelle": "événement / réception / renfort", "code_b2c": "PON"},
    "autre": {"libelle": "autre besoin en personnel", "code_b2c": "MEN"},
}

FREQUENCES_VALIDES = ("ponctuelle", "hebdomadaire", "temps_partiel", "temps_plein", "")
URGENCES_VALIDES = ("urgente", "cette_semaine", "planifiee", "")

# Motifs ordonnés du plus spécifique au plus général
_SERVICE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "garde_enfants",
        (
            "baby-sitter",
            "babysitter",
            "baby sitter",
            "garde d'enfant",
            "garde d’enfant",
            "garder mes enfant",
            "garder mon enfant",
            "garder les enfant",
            "garder un bebe",
            "garder mon bebe",
            "nounou",
            "nourrice",
            "mrabia",
            "mrabiya",
            "morabia",
            "morabiya",
            "l benti",
            "l weldi",
            "l wlidati",
            "assistante maternelle",
            "جليسة أطفال",
            "جليسة اطفال",
            "مربية",
            "حضانة",
            "لوليدات",
            "تشد ليا الدراري",
            "تشد لوليدات",
            "7adana",
        ),
    ),
    (
        "aide_domicile",
        (
            "aide a domicile",
            "aide à domicile",
            "personne agee",
            "personne âgée",
            "personnes agees",
            "pour ma mere",
            "pour ma mère",
            "pour mon pere",
            "pour mon père",
            "pour mes parents",
            "pour un parent",
            "pour un proche",
            "auxiliaire de vie",
            "garde-malade",
            "garde malade",
            "senior",
            "كبار السن",
            "مساعدة منزلية للوالدة",
            "للوالدة",
            "للوالد",
            "مرافقة",
            "m3awna l kbar",
        ),
    ),
    (
        "cuisine",
        (
            "aide-cuisiniere",
            "aide cuisiniere",
            "aide-cuisinier",
            "cuisiniere",
            "cuisinier",
            "cuisine",
            "tayaba",
            "tbakha",
            "preparer les repas",
            "préparer les repas",
            "طباخة",
            "الطبخ",
            "طيابة",
            "تطيب",
        ),
    ),
    (
        "menage",
        (
            "femme de menage",
            "femme de ménage",
            "aide-menagere",
            "aide menagere",
            "aide-ménagère",
            "menage",
            "ménage",
            "nettoyage",
            "mnada",
            "m3awna f dar",
            "t3awenni f dar",
            "تساعدني فالدار",
            "تساعدني في الدار",
            "تعاوني فالدار",
            "تعاونني فالدار",
            "عاملة منزل",
            "عاملة منزلية",
            "التنظيف",
            "تنظيف",
            "شغالة",
            "خدامة فالدار",
            "خدامة في الدار",
            "للمنزل",
            "فالدار",
        ),
    ),
    (
        "evenement",
        (
            "evenement",
            "événement",
            "reception",
            "réception",
            "mariage",
            "fete",
            "fête",
            "buffet",
            "banquet",
            "serveur",
            "serveuse",
            "extra",
            "مناسبة",
            "حفلة",
            "عرس",
        ),
    ),
    (
        "personnel_maison",
        (
            "personnel de maison",
            "employe de maison",
            "employée de maison",
            "gouvernante",
            "majordome",
            "chauffeur",
            "gardien",
            "vigile",
            "سائق",
            "حارس",
        ),
    ),
]

_CONTRAT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "ponctuelle",
        (
            "ponctuel",
            "ponctuelle",
            "pour un evenement",
            "pour un événement",
            "pour une reception",
            "pour une réception",
            "une fois",
            "un jour",
            "une journee",
            "une journée",
            "temporaire",
            "grand menage",
            "grand ménage",
            "demenagement",
            "déménagement",
            "مناسبة",
            "مؤقت",
            "نهار واحد",
            "مرة واحدة",
        ),
    ),
    (
        "hebdomadaire",
        (
            "hebdomadaire",
            "par semaine",
            "chaque semaine",
            "toutes les semaines",
            "1 fois par semaine",
            "2 fois par semaine",
            "3 fois par semaine",
            "fois/semaine",
            "أسبوعي",
            "كل سيمانة",
            "كل أسبوع",
        ),
    ),
    (
        "temps_partiel",
        (
            "temps partiel",
            "demi-journee",
            "demi journee",
            "demi-journée",
            "matinee",
            "matinée",
            "apres-midi",
            "après-midi",
            "quelques heures",
            "دوام جزئي",
            "نصف نهار",
        ),
    ),
    (
        "temps_plein",
        (
            "temps plein",
            "a temps plein",
            "à temps plein",
            "du lundi au vendredi",
            "du lundi au samedi",
            "men lundi tal vendredi",
            "mn lundi tal vendredi",
            "men lundi tal samedi",
            "lundi tal vendredi",
            "permanent",
            "permanente",
            "a demeure",
            "à demeure",
            "tous les jours",
            "logee",
            "logée",
            "دوام كامل",
            "دائم",
            "كل يوم",
        ),
    ),
]

_URGENCE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "urgente",
        (
            "urgent",
            "urgente",
            "urgence",
            "aujourd'hui",
            "aujourdhui",
            "demain",
            "des que possible",
            "dès que possible",
            "tout de suite",
            "immediatement",
            "immédiatement",
            "asap",
            "مستعجل",
            "عاجل",
            "دابا",
            "غدا",
            "اليوم",
        ),
    ),
    (
        "cette_semaine",
        (
            "cette semaine",
            "fin de semaine",
            "ce week-end",
            "ce weekend",
            "prochainement",
            "dans quelques jours",
            "هاد السيمانة",
            "هذا الأسبوع",
            "نهاية الأسبوع",
        ),
    ),
    (
        "planifiee",
        (
            "mois prochain",
            "le mois prochain",
            "semaine prochaine",
            "la semaine prochaine",
            "dans un mois",
            "الشهر الجاي",
            "الشهر القادم",
            "الأسبوع القادم",
        ),
    ),
]

_DARIJA_ARABIC_MARKERS = (
    "بغيت",
    "فالدار",
    "باش",
    "عافاك",
    "دابا",
    "واحد",
    "تساعدني",
    "تعاوني",
    "بزاف",
    "ديال",
    "لوليدات",
    "السيمانة",
    "خدامة",
    "كاين",
    "واش",
    "محتاج",
    "محتاجة",
)

_DARIJA_LATIN_MARKERS = (
    "bghit",
    "3afak",
    "salam",
    "wach",
    "mnada",
    "tbakha",
    "f dar",
    "dyal",
    "khdma",
    "khedma",
    "m3awna",
    "daba",
    "chokran",
    "l3a2ila",
)

_SPAM_MARKERS = (
    "bitcoin",
    "crypto",
    "casino",
    "viagra",
    "gagnez 10000",
    "cliquez ici pour gagner",
    "seo backlinks",
    "investissez maintenant",
)

_UNRELATED_MARKERS = (
    "vendre une voiture",
    "acheter un iphone",
    "location appartement",
    "reparation telephone",
    "cours de maths",
)


def detecter_langue(texte: str, langue_declaree: str = "") -> str:
    """Détecte la langue préférée (`fr`, `darija`, `arabe`) sans écraser une préférence déclarée."""
    decl = (langue_declaree or "").strip().lower()
    if decl in ("fr", "francais", "français"):
        return "fr"
    if decl in ("darija", "dr"):
        return "darija"
    if decl in ("arabe", "ar", "arabic"):
        return "arabe"

    brut = (texte or "").strip()
    if not brut:
        return "fr"

    has_arabic = bool(re.search(r"[\u0600-\u06FF]", brut))
    if has_arabic:
        if any(m in brut for m in _DARIJA_ARABIC_MARKERS):
            return "darija"
        return "arabe"

    folded = _fold_latin(brut)
    if sum(1 for m in _DARIJA_LATIN_MARKERS if re.search(r"\b" + re.escape(m) + r"\b", folded)) >= 2:
        return "darija"
    if any(re.search(r"\b" + re.escape(m) + r"\b", folded) for m in ("bghit", "mnada", "tbakha", "3afak", "m3awna")):
        return "darija"
    return "fr"


def _extraire_date_souhaitee(texte: str, ref_date: date | None = None) -> tuple[str, str]:
    """Extrait une date souhaitée UNIQUEMENT si explicitement communiquée."""
    brut = (texte or "").strip()
    if not brut:
        return "", ""
    base = ref_date or date.today()

    m_iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", brut)
    if m_iso:
        try:
            date.fromisoformat(m_iso.group(1))
            return m_iso.group(1), m_iso.group(1)
        except ValueError:
            pass

    m_fr = re.search(r"\b([0-3]?\d)[/-]([01]?\d)[/-](20\d{2})\b", brut)
    if m_fr:
        d, mo, y = int(m_fr.group(1)), int(m_fr.group(2)), int(m_fr.group(3))
        try:
            return date(y, mo, d).isoformat(), m_fr.group(0)
        except ValueError:
            pass

    folded = _fold_latin(brut)
    if "aujourd'hui" in folded or "aujourdhui" in folded or "اليوم" in brut:
        return base.isoformat(), "aujourd'hui"
    if re.search(r"\bdemain\b", folded) or "غدا" in brut:
        return (base + timedelta(days=1)).isoformat(), "demain"
    return "", ""


def analyser_demande_b2c(
    texte: str,
    champs_volontaires: Mapping[str, Any] | None = None,
    ref_date: date | None = None,
) -> dict[str, Any]:
    """Analyse une demande B2C (FR / Darija / Arabe) sans jamais inventer d'information absente.

    Retourne un dictionnaire structuré et traçable avec les preuves textuelles.
    """
    vol = dict(champs_volontaires or {})
    brut = (texte or "").strip()
    folded = _fold_latin(brut)
    preuves: dict[str, str] = {}

    # 1. Langue préférée
    langue = detecter_langue(brut, str(vol.get("langue_preferee", "")))
    if vol.get("langue_preferee"):
        preuves["langue_preferee"] = "déclarée dans le formulaire"
    elif brut:
        preuves["langue_preferee"] = f"détectée depuis le message ({langue})"

    # 2. Type de prestation
    type_prestation = ""
    type_decl = str(vol.get("type_besoin") or vol.get("type_prestation") or "").strip().lower()
    if type_decl in TYPES_PRESTATION:
        type_prestation = type_decl
        preuves["type_prestation"] = f"déclaré : {type_decl}"
    else:
        for code_srv, mots in _SERVICE_PATTERNS:
            for mot in mots:
                if (re.search(r"[\u0600-\u06FF]", mot) and mot in brut) or (
                    not re.search(r"[\u0600-\u06FF]", mot) and _fold_latin(mot) in folded
                ):
                    type_prestation = code_srv
                    preuves["type_prestation"] = f"extrait : « {mot} »"
                    break
            if type_prestation:
                break

    # Vérifier aussi une référence B2C codée (ex. CAS-CAL-MEN)
    dec_ref = b2c.decoder_reference_b2c(str(vol.get("b2c_ref", "")) + " " + brut)
    if dec_ref and not type_prestation:
        code_map = {
            "MEN": "menage",
            "CUI": "cuisine",
            "NOU": "garde_enfants",
            "AGE": "aide_domicile",
            "PON": "evenement",
            "CHA": "personnel_maison",
            "GAR": "personnel_maison",
        }
        type_prestation = code_map.get(dec_ref["code_besoin"], "autre")
        preuves["type_prestation"] = f"référence B2C {dec_ref['ref']}"

    # 3. Type de contrat / fréquence (uniquement si déclaré ou explicitement écrit)
    frequence = ""
    freq_decl = str(vol.get("frequence") or vol.get("type_contrat") or "").strip().lower()
    freq_alias = {
        "ponctuel": "ponctuelle",
        "ponctuelle": "ponctuelle",
        "hebdomadaire": "hebdomadaire",
        "temps_partiel": "temps_partiel",
        "temps partiel": "temps_partiel",
        "temps_plein": "temps_plein",
        "temps plein": "temps_plein",
        "permanent": "temps_plein",
    }
    if freq_decl in freq_alias:
        frequence = freq_alias[freq_decl]
        preuves["frequence"] = f"déclarée : {frequence}"
    else:
        for freq_code, mots in _CONTRAT_PATTERNS:
            for mot in mots:
                if (re.search(r"[\u0600-\u06FF]", mot) and mot in brut) or (
                    not re.search(r"[\u0600-\u06FF]", mot) and _fold_latin(mot) in folded
                ):
                    frequence = freq_code
                    preuves["frequence"] = f"extrait : « {mot} »"
                    break
            if frequence:
                break

    # 4. Ville & quartier (uniquement si déclarés ou mentionnés)
    ville = str(vol.get("ville") or vol.get("city") or "").strip()
    quartier = str(vol.get("quartier") or vol.get("zone") or "").strip()
    if quartier.lower() in ("a preciser", "à préciser"):
        quartier = ""

    if not quartier:
        for cle, nom_q in QUARTIERS_CASABLANCA.items():
            if (re.search(r"[\u0600-\u06FF]", cle) and cle in brut) or (
                not re.search(r"[\u0600-\u06FF]", cle) and re.search(r"\b" + re.escape(_fold_latin(cle)) + r"\b", folded)
            ):
                quartier = nom_q
                if not ville:
                    ville = "Bouskoura" if nom_q in ("Bouskoura", "Ville Verte") else "Casablanca"
                preuves["quartier"] = f"extrait : « {nom_q} »"
                break
        if not quartier:
            for cle, (v_nom, q_nom) in QUARTIERS_AUTRES_VILLES.items():
                if re.search(r"\b" + re.escape(_fold_latin(cle)) + r"\b", folded):
                    quartier = q_nom
                    if not ville:
                        ville = v_nom
                    preuves["quartier"] = f"extrait : « {q_nom} »"
                    break

    if not ville:
        for cle, (v_nom, _phase) in VILLES_CONNUES.items():
            if (re.search(r"[\u0600-\u06FF]", cle) and cle in brut) or (
                not re.search(r"[\u0600-\u06FF]", cle) and re.search(r"\b" + re.escape(_fold_latin(cle)) + r"\b", folded)
            ):
                ville = v_nom
                preuves["ville"] = f"extrait : « {v_nom} »"
                break

    if dec_ref:
        if not ville:
            ville = dec_ref["ville"]
            preuves["ville"] = f"référence B2C {dec_ref['ref']}"
        if not quartier:
            quartier = dec_ref["zone"]
            preuves["quartier"] = f"référence B2C {dec_ref['ref']}"

    # 5. Date souhaitée & Urgence (JAMAIS inventées)
    date_souhaitee = str(vol.get("date_souhaitee") or "").strip()
    if date_souhaitee:
        preuves["date_souhaitee"] = f"déclarée : {date_souhaitee}"
    else:
        date_ext, date_src = _extraire_date_souhaitee(brut, ref_date=ref_date)
        if date_ext:
            date_souhaitee = date_ext
            preuves["date_souhaitee"] = f"extrait : « {date_src} »"

    urgence = ""
    urg_decl = str(vol.get("urgence") or "").strip().lower()
    if urg_decl in ("urgente", "cette_semaine", "planifiee"):
        urgence = urg_decl
        preuves["urgence"] = f"déclarée : {urg_decl}"
    else:
        for urg_code, mots in _URGENCE_PATTERNS:
            for mot in mots:
                if (re.search(r"[\u0600-\u06FF]", mot) and mot in brut) or (
                    not re.search(r"[\u0600-\u06FF]", mot) and _fold_latin(mot) in folded
                ):
                    urgence = urg_code
                    preuves["urgence"] = f"extrait : « {mot} »"
                    break
            if urgence:
                break
        if not urgence and date_souhaitee:
            try:
                delta = (date.fromisoformat(date_souhaitee) - (ref_date or date.today())).days
                if 0 <= delta <= 2:
                    urgence = "urgente"
                elif 3 <= delta <= 7:
                    urgence = "cette_semaine"
                elif delta > 7:
                    urgence = "planifiee"
                if urgence:
                    preuves["urgence"] = f"déduite de la date communiquée ({date_souhaitee})"
            except ValueError:
                pass

    # 6. Canal préféré (uniquement si déclaré ou mentionné)
    canal_prefere = str(vol.get("canal_prefere") or "").strip().lower()
    if canal_prefere not in ("whatsapp", "email", "appel"):
        canal_prefere = ""
        if "whatsapp" in folded or "واتساب" in brut:
            canal_prefere = "whatsapp"
            preuves["canal_prefere"] = "mentionné dans le message (WhatsApp)"
        elif re.search(r"\b(appelez|appeler|par telephone|par téléphone|appel)\b", folded):
            canal_prefere = "appel"
            preuves["canal_prefere"] = "mentionné dans le message (appel)"
        elif re.search(r"\b(par email|par mail|e-mail)\b", folded):
            canal_prefere = "email"
            preuves["canal_prefere"] = "mentionné dans le message (email)"
    else:
        preuves["canal_prefere"] = f"déclaré : {canal_prefere}"

    # 7. Contraintes volontairement communiquées (JAMAIS inventées)
    contraintes: list[str] = []
    _CONTRAINTES_CHECKS = [
        ("pour ma mere", "Pour un parent (mère)"),
        ("pour mon pere", "Pour un parent (père)"),
        ("pour un evenement", "Pour un événement"),
        ("pour une reception", "Pour une réception"),
        ("non logee", "Non logée"),
        ("logee", "Logée"),
        ("chez moi", "À domicile"),
        ("matin", "Créneau matin mentionné"),
        ("soir", "Créneau soir mentionné"),
        ("week-end", "Week-end mentionné"),
        ("weekend", "Week-end mentionné"),
    ]
    for motif, lib in _CONTRAINTES_CHECKS:
        if motif in folded and lib not in contraintes:
            if motif == "logee" and "non logee" in folded:
                continue
            contraintes.append(lib)

    # 8. Budget indicatif : STRICTEMENT uniquement si fourni spontanément dans le champ dédié
    budget_indicatif = str(vol.get("budget_indicatif") or "").strip()
    if budget_indicatif:
        preuves["budget_indicatif"] = "indiqué spontanément par le demandeur"

    # 9. Détection spam / hors-sujet / STOP
    est_stop, stop_kw = detecter_stop(brut)
    est_spam = any(m in folded for m in _SPAM_MARKERS)
    est_hors_sujet = (not type_prestation) and any(m in folded for m in _UNRELATED_MARKERS)

    champs_manquants = []
    if not type_prestation:
        champs_manquants.append("type_prestation")
    if not quartier and not ville:
        champs_manquants.append("localisation")
    elif not quartier:
        champs_manquants.append("quartier")
    if not frequence:
        champs_manquants.append("frequence")
    if not date_souhaitee and not urgence:
        champs_manquants.append("date_ou_urgence")

    return {
        "type_prestation": type_prestation or "autre",
        "besoin_detecte": bool(type_prestation),
        "code_b2c": TYPES_PRESTATION.get(type_prestation or "autre", TYPES_PRESTATION["autre"])["code_b2c"],
        "libelle_prestation": TYPES_PRESTATION.get(type_prestation or "autre", TYPES_PRESTATION["autre"])["libelle"],
        "frequence": frequence,
        "ville": ville,
        "quartier": quartier,
        "urgence": urgence,
        "date_souhaitee": date_souhaitee,
        "budget_indicatif": budget_indicatif,
        "langue_preferee": langue,
        "canal_prefere": canal_prefere,
        "contraintes_volontaires": contraintes,
        "champs_manquants": champs_manquants,
        "preuves": preuves,
        "stop_detecte": est_stop,
        "stop_mot_cle": stop_kw,
        "spam_detecte": est_spam,
        "hors_sujet": est_hors_sujet,
    }


# ---------------------------------------------------------------------------
# 3. Score de qualification B2C — “Besoin Client Score” (0 à 100)
# ---------------------------------------------------------------------------
def _zone_desservie_points(ville: str, quartier: str) -> tuple[int, str]:
    v_fold = _fold_latin(ville)
    q_fold = _fold_latin(quartier)
    if v_fold in ("casablanca", "casa", "bouskoura", "dar bouazza") or q_fold in QUARTIERS_CASABLANCA:
        return 20, "Zone prioritaire desservie (Casablanca / Bouskoura)"
    if v_fold in ("rabat", "marrakech") or q_fold in QUARTIERS_AUTRES_VILLES:
        return 18, f"Zone Phase 1 desservie ({ville or quartier})"
    if v_fold in ("tanger", "agadir", "mohammedia", "kenitra", "fes", "el jadida", "temara", "temara/harhoura", "harhoura"):
        return 12, f"Zone Phase 2/3 desservie ({ville})"
    if ville or quartier:
        return 0, f"Hors zone de service ({ville or quartier})"
    return 0, "Localisation non précisée"


def scorer_demande_b2c(
    demande: Mapping[str, Any],
    analyse: Mapping[str, Any],
    *,
    is_duplicate: bool = False,
    is_blocked: bool = False,
) -> dict[str, Any]:
    """Calcule le score « Besoin Client Score » (0 à 100) et la classification A / B / C / Exclu."""
    motifs_exclusion: list[str] = []
    if is_blocked:
        motifs_exclusion.append("Contact bloqué définitivement (registre STOP / CNDP)")
    if analyse.get("stop_detecte"):
        motifs_exclusion.append(f"Demande de retrait STOP détectée ({analyse.get('stop_mot_cle', 'STOP')})")
    if is_duplicate:
        motifs_exclusion.append("Doublon détecté")
    if analyse.get("spam_detecte"):
        motifs_exclusion.append("Spam détecté")
    if analyse.get("hors_sujet"):
        motifs_exclusion.append("Demande non liée aux services Yallah Services")

    email = ym.email_normalise(str(demande.get("email", "")))
    tel = ym.tel_normalise(str(demande.get("tel", "")))
    wa = ym.tel_normalise(str(demande.get("whatsapp", "")))
    has_valid_email = ym.est_email_exploitable(email)
    has_valid_phone = len(tel) >= 9
    has_valid_wa = len(wa) >= 9 or ym.est_numero_mobile(str(demande.get("tel", "")))
    has_any_contact = has_valid_email or has_valid_phone or has_valid_wa

    msg_brut = str(demande.get("message_brut") or demande.get("message") or "").strip()
    if not has_any_contact and not analyse.get("besoin_detecte") and len(msg_brut) < 10:
        motifs_exclusion.append("Informations insuffisantes (ni besoin ni contact)")

    # 1. Besoin clairement exprimé : 30 points
    besoin_detecte = bool(analyse.get("besoin_detecte"))
    type_p = str(analyse.get("type_prestation") or "autre")
    if besoin_detecte and type_p in ("menage", "cuisine", "garde_enfants", "aide_domicile", "personnel_maison", "evenement"):
        pts_besoin = 30
    elif len(msg_brut) >= 25:
        pts_besoin = 15
    else:
        pts_besoin = 0

    # 2. Localisation dans la zone de service : 20 points
    ville = str(analyse.get("ville") or demande.get("ville") or "")
    quartier = str(analyse.get("quartier") or demande.get("quartier") or "")
    pts_loc, motif_loc = _zone_desservie_points(ville, quartier)

    # 3. Canal de contact valide : 15 points
    consent_recontact = bool(demande.get("consentement_recontact"))
    consent_wa = bool(demande.get("consentement_whatsapp"))
    if has_any_contact and (consent_recontact or consent_wa):
        pts_canal = 15
    elif has_any_contact:
        pts_canal = 8
    else:
        pts_canal = 0

    # 4. Urgence ou échéance détectée : 10 points
    urg = str(analyse.get("urgence") or "")
    date_s = str(analyse.get("date_souhaitee") or "")
    if urg == "urgente":
        pts_urgence = 10
    elif urg == "cette_semaine":
        pts_urgence = 8
    elif urg == "planifiee" or date_s:
        pts_urgence = 5
    else:
        pts_urgence = 0

    # 5. Compatibilité avec les services Yallah Services : 15 points
    if besoin_detecte and type_p in ("menage", "cuisine", "garde_enfants", "aide_domicile", "personnel_maison", "evenement"):
        pts_compat = 15
    elif not analyse.get("hors_sujet") and not analyse.get("spam_detecte") and len(msg_brut) >= 10:
        pts_compat = 6
    else:
        pts_compat = 0

    # 6. Complétude de la demande : 10 points
    pts_completude = 0
    if str(demande.get("nom") or "").strip():
        pts_completude += 2
    if quartier:
        pts_completude += 3
    if analyse.get("frequence"):
        pts_completude += 3
    if len(msg_brut) >= 20 or demande.get("budget_indicatif") or analyse.get("contraintes_volontaires"):
        pts_completude += 2
    pts_completude = min(10, pts_completude)

    total = pts_besoin + pts_loc + pts_canal + pts_urgence + pts_compat + pts_completude
    details = {
        "besoin_exprime": pts_besoin,
        "localisation": pts_loc,
        "canal_contact": pts_canal,
        "urgence_echeance": pts_urgence,
        "compatibilite_services": pts_compat,
        "completude": pts_completude,
        "motif_localisation": motif_loc,
    }

    if motifs_exclusion:
        classification = "Exclu"
        total = 0
        action_recommandee = "Ne pas contacter (exclu)"
    elif (
        total >= 75
        and pts_besoin >= 30
        and pts_loc >= 12
        and has_any_contact
        and (pts_urgence >= 5 or pts_completude >= 7)
    ):
        classification = "A"
        action_recommandee = (
            "Appeler immédiatement ou répondre sur WhatsApp"
            if urg == "urgente"
            else "Répondre rapidement et proposer un appel / RDV"
        )
    elif total >= 45 and has_any_contact:
        classification = "B"
        action_recommandee = "Qualifier les informations manquantes"
    else:
        classification = "C"
        action_recommandee = "Faible priorité — vérifier ou archiver"

    return {
        "score": total,
        "classification": classification,
        "details": details,
        "motifs_exclusion": motifs_exclusion,
        "action_recommandee": action_recommandee,
    }


# ---------------------------------------------------------------------------
# 4. Score de qualification B2B — “Prospect Pro Score” (0 à 100)
# ---------------------------------------------------------------------------
SEGMENTS_PRO_SCORE = {
    "hotel": 25,
    "traiteur": 25,
    "evenementiel": 25,
    "conciergerie": 25,
    "residence": 23,
    "riad": 23,
    "restaurant": 20,
    "relocation_rh": 22,
    "clinique_senior": 22,
    "agence_immo": 18,
    "creche_ecole": 18,
    "entreprise": 18,
    "nettoyage": 16,
    "commerce": 15,
    "construction": 15,
    "porteur_projet": 12,
}

SIGNAUX_FORTS_B2B = {
    "annonce_embauche",
    "recrutement_actif",
    "ouverture",
    "extension",
    "evenement",
    "page_carrieres",
    "besoin_declare",
    "formulaire_entrant",
    "recommandation_partenaire",
}

DOMAINES_SOURCES_INTERDITS = (
    "facebook.com",
    "fb.com",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "chat.whatsapp.com",
    "t.me",
)


def est_source_pro_autorisee(source_url: str) -> tuple[bool, str]:
    """Vérifie qu'une source B2B publique n'est pas issue d'un scraping interdit."""
    url_low = (source_url or "").strip().lower()
    if not url_low:
        return False, "Lien de source manquant"
    for dom in DOMAINES_SOURCES_INTERDITS:
        if dom in url_low:
            return False, f"Source non autorisée pour extraction automatique ({dom})"
    if not (url_low.startswith("http://") or url_low.startswith("https://") or url_low.startswith("ent-")):
        return False, "URL source publique invalide"
    return True, "Source publique autorisée"


def scorer_prospect_pro(
    prospect: Mapping[str, Any],
    *,
    ref_date: date | None = None,
    is_duplicate: bool = False,
    is_blocked: bool = False,
) -> dict[str, Any]:
    """Calcule le score « Prospect Pro Score » (0 à 100) et la classification A / B / C / Exclu."""
    today_d = ref_date or date.today()
    motifs_exclusion: list[str] = []

    if is_blocked:
        motifs_exclusion.append("Contact bloqué définitivement (STOP / refus)")
    if is_duplicate:
        motifs_exclusion.append("Doublon détecté")

    source_url = str(prospect.get("source_url") or "")
    source_type = str(prospect.get("source_type") or "")
    if source_type != "entrant":
        ok_src, motif_src = est_source_pro_autorisee(source_url)
        if not ok_src:
            motifs_exclusion.append(motif_src)

    email_pro = ym.email_normalise(str(prospect.get("email_pro") or prospect.get("email") or ""))
    tel_pro = ym.tel_normalise(str(prospect.get("tel_pro") or prospect.get("tel") or ""))
    wa_pro = ym.tel_normalise(str(prospect.get("whatsapp_pro") or prospect.get("whatsapp") or ""))
    has_email = ym.est_email_exploitable(email_pro)
    has_tel = len(tel_pro) >= 9
    has_wa = len(wa_pro) >= 9
    has_contact = has_email or has_tel or has_wa

    if not has_contact:
        motifs_exclusion.append("Aucune coordonnée professionnelle directe valide")

    # 1. Pertinence du segment : 25 points
    seg = str(prospect.get("type_etablissement") or prospect.get("segment") or "").strip().lower()
    pts_segment = SEGMENTS_PRO_SCORE.get(seg, 10 if seg else 0)

    # 2. Besoin probable détecté : 25 points
    signaux = prospect.get("signaux_interet") or []
    if isinstance(signaux, str):
        signaux = [s.strip() for s in signaux.split(",") if s.strip()]
    signaux_norm = {str(s).strip().lower() for s in signaux}
    besoin_prob = str(prospect.get("besoin_probable") or "").strip()
    if signaux_norm & SIGNAUX_FORTS_B2B:
        pts_besoin = 25
    elif signaux_norm or (besoin_prob and len(besoin_prob) >= 6):
        pts_besoin = 18
    elif seg in SEGMENTS_PRO_SCORE:
        pts_besoin = 12
    else:
        pts_besoin = 0

    if pts_besoin == 0:
        motifs_exclusion.append("Aucun besoin plausible détecté")

    # 3. Qualité des coordonnées : 20 points
    niveau = str(prospect.get("niveau") or "A").strip().upper()
    preuve = str(prospect.get("preuve_extrait") or "").strip()
    if has_email and (has_tel or has_wa) and niveau == "A":
        pts_coord = 20
    elif (has_email or has_tel or has_wa) and niveau == "A":
        pts_coord = 17
    elif has_contact and niveau == "B":
        pts_coord = 12
    else:
        pts_coord = 0

    # 4. Localisation : 15 points
    ville = str(prospect.get("ville") or "")
    quartier = str(prospect.get("quartier") or prospect.get("zone") or "")
    v_fold = _fold_latin(ville)
    if v_fold in ("casablanca", "casa", "bouskoura", "dar bouazza") or _fold_latin(quartier) in QUARTIERS_CASABLANCA:
        pts_loc = 15
    elif v_fold in ("rabat", "marrakech"):
        pts_loc = 12
    elif v_fold in ("tanger", "agadir", "mohammedia", "kenitra", "fes", "el jadida", "temara", "temara/harhoura"):
        pts_loc = 8
    else:
        pts_loc = 0
        if ville:
            motifs_exclusion.append(f"Hors zone couverte ({ville})")

    # 5. Potentiel estimé : 10 points
    if seg in ("hotel", "traiteur", "evenementiel", "conciergerie", "residence", "relocation_rh", "clinique_senior"):
        pts_potentiel = 10
    elif seg in ("restaurant", "riad", "entreprise", "agence_immo", "creche_ecole"):
        pts_potentiel = 7
    else:
        pts_potentiel = 4

    # 6. Fraîcheur du signal : 5 points
    date_raw = str(prospect.get("date_derniere_verification") or prospect.get("date_consultation") or "")[:10]
    pts_fraicheur = 0
    if date_raw:
        try:
            age = (today_d - date.fromisoformat(date_raw)).days
            if 0 <= age <= 7:
                pts_fraicheur = 5
            elif 8 <= age <= 30:
                pts_fraicheur = 3
            elif 31 <= age <= 90:
                pts_fraicheur = 1
        except ValueError:
            pts_fraicheur = 0

    total = pts_segment + pts_besoin + pts_coord + pts_loc + pts_potentiel + pts_fraicheur
    details = {
        "pertinence_segment": pts_segment,
        "besoin_probable": pts_besoin,
        "qualite_coordonnees": pts_coord,
        "localisation": pts_loc,
        "potentiel_estime": pts_potentiel,
        "fraicheur_signal": pts_fraicheur,
        "preuve_presente": bool(preuve),
    }

    if motifs_exclusion:
        classification = "Exclu"
        total = 0
        action_recommandee = "Exclu — ne pas contacter"
    elif total >= 75 and has_contact and niveau == "A" and pts_besoin >= 12:
        classification = "A"
        action_recommandee = "Valider et préparer la prise de contact B2B"
    elif total >= 50:
        classification = "B"
        action_recommandee = "Vérifier la fiche et compléter le besoin"
    else:
        classification = "C"
        action_recommandee = "Faible priorité — garder en veille"

    return {
        "score": total,
        "classification": classification,
        "details": details,
        "motifs_exclusion": motifs_exclusion,
        "action_recommandee": action_recommandee,
    }


# ---------------------------------------------------------------------------
# 5. Génération de messages multilingues (FR / Darija / Arabe) + Garde-fou
# ---------------------------------------------------------------------------
OPT_OUT_AUTONOME_MARQUEURS = ym.OPT_OUT_MARQUEURS + (
    "répondez stop",
    "repondez stop",
    "répondez simplement stop",
    "repondez simplement stop",
    "jawb b stop",
    "jawbo b stop",
    "ردوا بكلمة stop",
    "أرسلوا stop",
    "توقف",
)


def verifier_message_autonome(texte: str) -> list[str]:
    """Garde-fou strict : zéro prix/délai/garantie/disponibilité inventée + mention STOP obligatoire."""
    alertes = list(yp.verifier_message(texte or ""))
    bas = (texte or "").lower()
    for motif, libelle in ym.PATTERNS_PRESUPPLEMENT:
        trouve = re.search(motif, bas, flags=re.IGNORECASE)
        if trouve:
            alertes.append(f"{libelle} : « {trouve.group(0).strip()} »")
    if texte and not any(m in bas for m in OPT_OUT_AUTONOME_MARQUEURS):
        alertes.append("mention de retrait / STOP absente")
    if texte and len(texte) > ym.LONGUEUR_MAX:
        alertes.append(f"message trop long ({len(texte)} caractères, maximum {ym.LONGUEUR_MAX})")
    return alertes


def generer_message_famille(
    demande: Mapping[str, Any],
    analyse: Mapping[str, Any],
    langue: str = "",
    prenom_conseiller: str = "l'équipe",
) -> str:
    """Rédige une réponse chaleureuse et rassurante pour une famille (2 à 4 questions max + RDV + STOP)."""
    lang = langue or str(analyse.get("langue_preferee") or demande.get("langue_preferee") or "fr")
    if lang not in ("fr", "darija", "arabe"):
        lang = "fr"
    nom = str(demande.get("nom") or "").strip()
    prenom_client = nom.split()[0] if nom and nom.lower() not in ("client", "contact whatsapp à qualifier") else ""
    manquants = list(analyse.get("champs_manquants") or [])
    type_p = str(analyse.get("libelle_prestation") or "personnel de maison")

    if lang == "darija":
        salut = f"Salam {prenom_client}," if prenom_client else "Salam,"
        questions = []
        if "type_prestation" in manquants:
            questions.append("ach men khdma m7tajin (mnada, tbakha, nounou, m3awna f dar)")
        if "localisation" in manquants or "quartier" in manquants:
            questions.append("l-quartier f Casablanca aw l-mdina")
        if "frequence" in manquants:
            questions.append("wach bghitouha b l-wa9t l-kamel, nos nhar aw ghir mawqati")
        if "date_ou_urgence" in manquants:
            questions.append("imta m7tajin tbda")
        if not questions:
            questions = ["l-aw9at li mnasbinkom", "imta n9dro ndiro mokala qssira"]
        q_txt = " w ".join(questions[:3])
        return (
            f"{salut}\n"
            f"Chokran 3la risaltkom l Yallah Services.\n"
            f"Twsselna b talabkom b khoussous {type_p}. "
            f"Bach nwjhokom mzyan, wach t9dro t2kkdo lina {q_txt} ?\n"
            f"N9dro aydan ndiro wahed mokala aw maw3id mli ynasbkom.\n"
            f"Ila ma b9itouch baghyin twsslo b rassail mn 3ndna, jawbo b STOP."
        )

    if lang == "arabe":
        salut = f"مرحبا {prenom_client}،" if prenom_client else "مرحبا،"
        questions = []
        if "type_prestation" in manquants:
            questions.append("نوع المساعدة المطلوبة")
        if "localisation" in manquants or "quartier" in manquants:
            questions.append("الحي أو المدينة")
        if "frequence" in manquants:
            questions.append("طبيعة الدوام (دائم، جزئي أو عرضي)")
        if "date_ou_urgence" in manquants:
            questions.append("التاريخ المناسب للبدء")
        if not questions:
            questions = ["الأوقات المناسبة لكم", "الوقت المناسب لمكالمة قصيرة أو موعد"]
        q_txt = " و".join(questions[:3])
        return (
            f"{salut}\n"
            f"شكراً لتواصلكم مع Yallah Services.\n"
            f"توصلنا بطلبكم، ولمساعدتكم بشكل أفضل هل يمكنكم توضيح {q_txt}؟\n"
            f"يسعدنا أيضاً تحديد مكالمة أو موعد في الوقت الذي يناسبكم.\n"
            f"إذا كنتم لا ترغبون في تلقي رسائل منا مستقبلاً، أرسلوا STOP."
        )

    salut = f"Bonjour {prenom_client}," if prenom_client else "Bonjour,"
    questions = []
    if "type_prestation" in manquants:
        questions.append("le type d’aide recherchée")
    if "localisation" in manquants or "quartier" in manquants:
        questions.append("le quartier")
    if "frequence" in manquants:
        questions.append("la fréquence souhaitée (ponctuelle, temps partiel ou temps plein)")
    if "date_ou_urgence" in manquants:
        questions.append("la date à laquelle vous en avez besoin")
    if not questions:
        questions = ["vos créneaux souhaités", "un moment qui vous convient pour un appel ou un rendez-vous"]
    if len(questions) == 1:
        q_txt = questions[0]
    else:
        q_txt = ", ".join(questions[:3][:-1]) + " et " + questions[:3][-1]
    return (
        f"{salut}\n"
        f"Merci pour votre message à Yallah Services.\n"
        f"Pour mieux vous orienter, pouvez-vous me préciser {q_txt} ?\n"
        f"Nous pouvons également convenir d’un court appel ou d’un rendez-vous selon votre disponibilité.\n"
        f"Si vous ne souhaitez plus recevoir de messages de notre part, répondez STOP."
    )


def generer_message_pro(
    prospect: Mapping[str, Any],
    langue: str = "fr",
    prenom_conseiller: str = "Youssef",
) -> str:
    """Rédige un message B2B professionnel, direct et respectueux (FR / Darija / Arabe + STOP)."""
    lang = langue if langue in ("fr", "darija", "arabe") else "fr"
    nom = str(prospect.get("nom_entreprise") or prospect.get("nom") or "").strip()
    seg = str(prospect.get("type_etablissement") or prospect.get("segment") or "entreprise").strip().lower()
    seg_info = yp.SEGMENTS.get(seg, {})
    type_etab = seg_info.get("libelle", seg or "établissements")
    ville = str(prospect.get("ville") or "Casablanca").strip()
    besoin = str(prospect.get("besoin_probable") or seg_info.get("accroche") or "personnel opérationnel").strip()
    signataire = (prenom_conseiller or "le service commercial").strip()

    if lang == "darija":
        return (
            f"Salam {nom},\n"
            f"Ana {signataire} mn Yallah Services, agence dyal mise en relation d l-personnel f {ville}.\n"
            f"Kan3awno les {type_etab} bach yl9aw profils l l-i7tiyajat dyalhom f {besoin}.\n"
            f"Wach 3ndkom 7aliyan chi 7aja dyal recrutement aw renfort f l-personnel ?\n"
            f"Ila ma bghitouch twsslo b rassail mn 3ndna, jawbo b STOP."
        )

    if lang == "arabe":
        return (
            f"مرحبا {nom}،\n"
            f"أنا {signataire} من Yallah Services، وكالة للوساطة وتوفير الموظفين في {ville}.\n"
            f"نساعد المؤسسات في قطاع {type_etab} على إيجاد مرشحين لاحتياجاتهم من الموظفين.\n"
            f"هل لديكم حالياً حاجة لتوظيف أو تعزيز فريق العمل لديكم؟\n"
            f"إذا كنتم لا ترغبون في تلقي رسائل منا، ردوا بكلمة STOP."
        )

    return (
        f"Bonjour {nom},\n"
        f"Je suis {signataire} de Yallah Services, agence de mise en relation de personnel à {ville}.\n"
        f"Nous aidons les établissements ({type_etab}) à identifier des profils pour leurs besoins en {besoin}.\n"
        f"Avez-vous actuellement un besoin de recrutement ou de renfort en personnel ?\n"
        f"Si vous ne souhaitez pas recevoir de messages de notre part, répondez simplement STOP."
    )


def generer_message_relance_autonome(
    nom: str,
    entity_type: str,
    etape: int = 1,
    langue: str = "fr",
    prenom_conseiller: str = "Youssef",
) -> str:
    """Génère une relance courtoise J+3 (étape 1), J+7 (étape 2) ou J+14 (étape 3, finale)."""
    lang = langue if langue in ("fr", "darija", "arabe") else "fr"
    step = max(1, min(3, int(etape or 1)))
    derniere = step == 3
    signataire = (prenom_conseiller or "Yallah Services").strip()
    cible = nom.strip() or "Madame, Monsieur"

    if lang == "darija":
        intro = (
            "Hadi akher mtb3a dyali b khoussous risalti s-sab9a."
            if derniere
            else "Kanrj3 3ndkom b ikhtissar b3d risalti s-sab9a."
        )
        return (
            f"Salam {cible},\n"
            f"Ana {signataire} mn Yallah Services. {intro}\n"
            f"Wach mazal 3ndkom chi 7aja f l-personnel bach ndiro mokala qssira ?\n"
            f"Ila ma bghitouch twsslo b rassail mn 3ndna, jawbo b STOP."
        )

    if lang == "arabe":
        intro = (
            "هذه متابعتي الأخيرة بخصوص رسالتي السابقة."
            if derniere
            else "أعود إليكم باختصار بخصوص رسالتي السابقة."
        )
        return (
            f"مرحبا {cible}،\n"
            f"أنا {signataire} من Yallah Services. {intro}\n"
            f"هل ما زالت لديكم حاجة حالية لموظفين لنتحدث في مكالمة قصيرة؟\n"
            f"إذا كنتم لا ترغبون في تلقي رسائل منا، أرسلوا STOP."
        )

    intro = (
        "Je me permets un dernier court suivi à la suite de mon précédent message."
        if derniere
        else "Je me permets un court suivi à la suite de mon précédent message."
    )
    sujet = (
        "votre recherche d’aide à domicile"
        if entity_type == "demande_b2c"
        else "un besoin éventuel en personnel ou en renfort"
    )
    return (
        f"Bonjour {cible},\n"
        f"Je suis {signataire} de Yallah Services. {intro}\n"
        f"Souhaitez-vous que nous fassions un point rapide par téléphone au sujet de {sujet} ?\n"
        f"Si vous ne souhaitez plus recevoir de messages de notre part, répondez STOP."
    )
