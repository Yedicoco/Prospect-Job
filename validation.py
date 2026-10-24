"""Validation partagée des entrées métier ; aucune donnée externe n'est consultée."""
import re
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Africa/Casablanca')


def today():
    return datetime.now(ZONE).date()


def text(value, label, required=False, limit=2000):
    if not isinstance(value, str):
        raise ValueError(f'{label} : texte attendu')
    value = value.strip()
    if (required and not value) or len(value) > limit or '\x00' in value:
        raise ValueError(f'{label} : champ requis ou longueur maximale {limit} dépassée')
    return value


def day(value, label='Date', required=True, past=False):
    value = text(value, label, required, 10)
    if not value and not required:
        return ''
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value or (past and parsed > today()):
            raise ValueError()
    except ValueError:
        raise ValueError(f'{label} : date réelle AAAA-MM-JJ attendue' + (', non future' if past else ''))
    return value


def url(value):
    value = text(value, 'URL', True, 2000)
    try:
        parts = urlparse(value)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or any(c.isspace() for c in value):
            raise ValueError()
        _ = parts.port
    except ValueError:
        raise ValueError('URL HTTP(S) valide attendue, sans identifiants')
    return value


def contact(email, tel):
    email = text(email, 'Email', False, 254).lower()
    tel = text(tel, 'Téléphone', False, 40)
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Email invalide')
    if tel and not re.fullmatch(r'\+?[0-9 ()-]{7,40}', tel):
        raise ValueError('Téléphone invalide')
    if not email and not tel:
        raise ValueError('Email ou téléphone requis')
    return email, tel


def number(value, label, minimum=0, maximum=10000000):
    if isinstance(value, bool):
        raise ValueError(label + ' : nombre attendu')
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(label + ' : nombre attendu')
    if not minimum <= number <= maximum:
        raise ValueError(label + ' : nombre hors limites')
    return number


def record(kind, item):
    import yallah_messages as messages
    import yallah_emploi as emploi
    if kind not in ('b2b', 'b2c', 'emploi') or not isinstance(item, dict):
        raise ValueError('Fiche invalide')
    for key, value in item.items():
        if key in ('remuneration', 'horaires', 'frais_montant', 'frais_moment'):
            if not isinstance(value, dict):
                raise ValueError(key + ' : valeur et source attendues')
            for k in ('valeur', 'source'):
                text(value.get(k, ''), key + '.' + k)
        elif key in ('besoins_probables',):
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ValueError(key + ' : liste de codes attendue')
        elif key == 'exemple':
            if not isinstance(value, bool):
                raise ValueError('exemple : booléen attendu')
        elif key in ('phase', 'client_id', 'opportunity_id'):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(key + ' : entier attendu')
        else:
            text(value, key, limit=6000)
    if kind == 'emploi':
        if item.get('statut') not in ('ouvert', 'ferme', 'pourvu', 'annule'):
            raise ValueError('Statut du besoin invalide')
        # La fermeture est valide en stockage, mais reste non publiable dans le moteur d'annonce.
        check = dict(item, statut='ouvert')
        problems = emploi.valider_besoin(check)
        if not item.get('exemple'):
            day(item.get('date_confirmation', ''), 'Date de confirmation', past=True)
    else:
        problems = messages.valider_fiche(item, kind)
        if item.get('source_type') != 'entrant':
            url(item.get('source_url', ''))
        elif not re.fullmatch(r'ENT-\d{6,}',item.get('source_reference','')):
            raise ValueError('Référence de provenance entrante invalide')
        day(item.get('date_consultation', ''), 'Date de consultation', past=True)
        if item.get('date_derniere_verification'):
            day(item['date_derniere_verification'], 'Dernière vérification', past=True)
        if item.get('tel') or item.get('email'):
            contact(item.get('email', ''), item.get('tel', ''))
    if problems:
        raise ValueError(' ; '.join(problems))
    return item
