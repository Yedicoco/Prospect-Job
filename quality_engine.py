"""Moteur métier autonome pour fiabiliser les opérations CRM.

Ce module ne modifie aucune donnée et ne dépend pas de la webapp. Il fournit
les primitives réutilisables pour normaliser les contacts, évaluer la fraîcheur
et la priorité, contrôler les transitions, rendre les relances idempotentes et
calculer le ROI réellement encaissé.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from hashlib import sha256
import re
from typing import Iterable, Mapping


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DIGITS_RE = re.compile(r"\D+")


@dataclass(frozen=True)
class NormalizedContact:
    """Coordonnées normalisées, sans inventer de valeur absente."""

    email: str = ""
    phone: str = ""
    whatsapp: str = ""


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    normalized: NormalizedContact = field(default_factory=NormalizedContact)


def normalize_email(value: str | None) -> str:
    """Nettoie un email sans le considérer valide automatiquement."""
    value = (value or "").strip().casefold()
    if value and not EMAIL_RE.fullmatch(value):
        raise ValueError("Email invalide")
    return value


def normalize_phone(value: str | None, *, country_code: str = "212") -> str:
    """Retourne un numéro marocain comparable au format +212XXXXXXXXX.

    Un numéro vide reste vide. Les numéros non marocains sont conservés dans
    une forme internationale comparable, mais aucune validité commerciale
    n'est déduite de la normalisation.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    digits = DIGITS_RE.sub("", raw)
    if raw.startswith("+") and not digits:
        raise ValueError("Téléphone invalide")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and not digits.startswith("00"):
        digits = country_code + digits[1:]
    elif not digits.startswith(country_code) and len(digits) in (9, 10):
        digits = country_code + digits
    if len(digits) < 8 or len(digits) > 15:
        raise ValueError("Téléphone invalide")
    return "+" + digits


def normalize_contact(
    email: str | None = "",
    phone: str | None = "",
    whatsapp: str | None = "",
) -> NormalizedContact:
    """Normalise les canaux et conserve explicitement WhatsApp."""
    return NormalizedContact(
        email=normalize_email(email),
        phone=normalize_phone(phone),
        whatsapp=normalize_phone(whatsapp),
    )


def contact_identity(contact: NormalizedContact) -> str:
    """Produit une identité stable pour déduplication et idempotence."""
    for value in (contact.email, contact.phone, contact.whatsapp):
        if value:
            return value
    return ""


def prospect_deduplication_key(
    *,
    name: str = "",
    city: str = "",
    domain: str = "",
    contact: NormalizedContact | None = None,
) -> str:
    """Construit une clé stable, sans utiliser le nom seul comme identifiant."""
    identity = contact_identity(contact or NormalizedContact())
    if identity:
        return f"contact:{identity}"
    parts = [
        " ".join(name.casefold().split()),
        " ".join(city.casefold().split()),
        domain.casefold().strip().removeprefix("www."),
    ]
    return "org:" + "|".join(parts)


def freshness_factor(
    checked_on: date | str | None,
    *,
    today: date | None = None,
    half_life_days: int = 14,
) -> float:
    """Retourne une confiance décroissante entre 0 et 1."""
    if half_life_days <= 0:
        raise ValueError("half_life_days doit être positif")
    if checked_on is None or checked_on == "":
        return 0.0
    if isinstance(checked_on, str):
        try:
            checked_on = date.fromisoformat(checked_on)
        except ValueError as exc:
            raise ValueError("Date de vérification invalide") from exc
    today = today or date.today()
    age = (today - checked_on).days
    if age < 0:
        return 0.0
    return round(0.5 ** (age / half_life_days), 6)


@dataclass(frozen=True)
class LeadScore:
    fit: float = 0.0
    intent: float = 0.0
    reachability: float = 0.0
    freshness: float = 0.0
    value: float = 0.0
    effort: float = 0.0
    compliance_risk: float = 0.0
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def total(self) -> float:
        raw = (
            self.fit * 0.25
            + self.intent * 0.25
            + self.reachability * 0.15
            + self.freshness * 0.10
            + self.value * 0.15
            - self.effort * 0.05
            - self.compliance_risk * 0.05
        )
        return round(max(0.0, min(100.0, raw)), 2)


def _bounded(value: float | int | None) -> float:
    return max(0.0, min(100.0, float(value or 0)))


def score_prospect(prospect: Mapping[str, object], *, today: date | None = None) -> LeadScore:
    """Calcule un score explicable sur une échelle de 0 à 100."""
    contact = normalize_contact(
        str(prospect.get("email", "")),
        str(prospect.get("tel", prospect.get("phone", ""))),
        str(prospect.get("whatsapp", "")),
    )
    freshness = freshness_factor(
        prospect.get("date_derniere_verification") or prospect.get("date_consultation"),
        today=today,
    ) * 100
    level_points = {"A": 100.0, "B": 65.0, "C": 25.0}
    reachability = 100.0 if contact.phone or contact.whatsapp else 55.0 if contact.email else 0.0
    fit = _bounded(prospect.get("fit_score", prospect.get("adequation", 0)))
    intent = _bounded(prospect.get("intent_score", prospect.get("intention", 0)))
    value = _bounded(prospect.get("value_score", prospect.get("valeur", 0)))
    effort = _bounded(prospect.get("effort_score", prospect.get("effort", 0)))
    risk = _bounded(prospect.get("compliance_risk", 0))
    if not fit and prospect.get("segment_prioritaire"):
        fit = 75.0
    if not intent and prospect.get("besoin_confirme"):
        intent = 90.0

    reasons: list[str] = []
    warnings: list[str] = []
    level = str(prospect.get("niveau", "")).upper()
    if level in level_points:
        reachability = max(reachability, level_points[level])
        reasons.append(f"Niveau de source {level}")
    if prospect.get("besoin_confirme"):
        reasons.append("Besoin confirmé")
    if freshness >= 75:
        reasons.append("Fiche fraîche")
    elif freshness < 35:
        warnings.append("Fiche ancienne ou non vérifiée")
    if prospect.get("opt_out"):
        warnings.append("Opt-out actif")
    if not contact.email and not contact.phone and not contact.whatsapp:
        warnings.append("Aucun canal direct")

    return LeadScore(
        fit=fit,
        intent=intent,
        reachability=reachability,
        freshness=freshness,
        value=value,
        effort=effort,
        compliance_risk=risk,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "nouveau": frozenset({"qualifie", "ignore", "opt_out"}),
    "qualifie": frozenset({"contacte", "ignore", "opt_out"}),
    "contacte": frozenset({"repondu", "sans_reponse", "opt_out"}),
    "sans_reponse": frozenset({"relance_planifiee", "perdu", "opt_out"}),
    "relance_planifiee": frozenset({"repondu", "sans_reponse", "perdu", "opt_out"}),
    "repondu": frozenset({"qualifie", "rendez_vous", "perdu", "opt_out"}),
    "rendez_vous": frozenset({"proposition", "perdu", "opt_out"}),
    "proposition": frozenset({"gagne", "perdu", "opt_out"}),
    "gagne": frozenset(),
    "perdu": frozenset(),
    "ignore": frozenset(),
    "opt_out": frozenset(),
}


def transition_allowed(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_transition(current: str, target: str) -> None:
    if not transition_allowed(current, target):
        raise ValueError(f"Transition interdite : {current} -> {target}")


def action_idempotency_key(
    *, entity_type: str, entity_id: str | int, action: str, step: str | int = ""
) -> str:
    """Clé stable pour empêcher les doublons d'actions."""
    raw = "|".join(str(v).strip().casefold() for v in (entity_type, entity_id, action, step))
    return sha256(raw.encode("utf-8")).hexdigest()


def realized_mad_per_hour(revenue: float, minutes: float) -> float | None:
    if revenue < 0 or minutes < 0:
        raise ValueError("Le revenu et le temps ne peuvent pas être négatifs")
    if minutes == 0:
        return None
    return round(revenue / (minutes / 60), 2)


def realized_roi(revenue: float, costs: float) -> float:
    if revenue < 0 or costs < 0:
        raise ValueError("Le revenu et les coûts ne peuvent pas être négatifs")
    return round(revenue - costs, 2)


def validate_contact_record(record: Mapping[str, object]) -> ValidationResult:
    """Validation légère réutilisable avant insertion ou envoi."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        normalized = normalize_contact(
            str(record.get("email", "")),
            str(record.get("tel", record.get("phone", ""))),
            str(record.get("whatsapp", "")),
        )
    except ValueError as exc:
        normalized = NormalizedContact()
        errors.append(str(exc))
    if not contact_identity(normalized):
        errors.append("Email, téléphone ou WhatsApp requis")
    if record.get("opt_out"):
        warnings.append("Contact opt-out : aucune action sortante autorisée")
    return ValidationResult(
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        normalized=normalized,
    )
