#!/usr/bin/env python3
"""yallah_connectors.py — Connecteurs modulaires Email (SMTP/IMAP/Resend),
WhatsApp Business Cloud API et recherche web B2B publique (avec robots.txt & garde-fous).

Bibliothèque standard Python uniquement. Aucun scraping de réseaux sociaux privés
(Facebook, Instagram, TikTok, LinkedIn, groupes WhatsApp), aucune devinette d'email/numéro.
"""
from __future__ import annotations

import email as email_lib
from email.header import decode_header
from email.message import EmailMessage
import hashlib
import html as html_lib
import imaplib
import json
import os
import re
import smtplib
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

import yallah_analyzer as analyzer
import yallah_messages as ym
import yallah_sources as sources

USER_AGENT = "YallahServicesBot/1.0 (+https://yallahservices-one.vercel.app; B2B public contact verification)"

FORBIDDEN_SCRAPE_DOMAINS = (
    "facebook.com",
    "fb.com",
    "m.facebook.com",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "chat.whatsapp.com",
    "whatsapp.com",
    "t.me",
    "telegram.me",
    "twitter.com",
    "x.com",
)

DISPOSABLE_EMAIL_DOMAINS = (
    "mailinator.com",
    "yopmail.com",
    "guerrillamail.com",
    "10minutemail.com",
    "tempmail.com",
    "trashmail.com",
)


class ComplianceError(ValueError):
    """Violation d'une règle de conformité (Loi 09-08, Meta WhatsApp, robots.txt ou domaine interdit)."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 1. Connecteur Email (Resend API + SMTP + IMAP)
# ---------------------------------------------------------------------------
def verifier_delivrabilite_email(adresse: str, *, check_dns: bool = False) -> dict[str, Any]:
    """Vérifie la délivrabilité syntaxique et technique d'une adresse email."""
    mail = ym.email_normalise(adresse)
    if not mail:
        return {"valid": False, "email": "", "reason": "Adresse email absente"}
    if not ym.est_email_exploitable(mail):
        return {"valid": False, "email": mail, "reason": "Adresse invalide, technique (noreply) ou domaine de staging"}
    domaine = mail.split("@", 1)[1]
    if domaine in DISPOSABLE_EMAIL_DOMAINS or any(domaine.endswith("." + d) for d in DISPOSABLE_EMAIL_DOMAINS):
        return {"valid": False, "email": mail, "reason": "Domaine jetable non exploitable"}
    if "." not in domaine or domaine.endswith(".invalid") or domaine.endswith(".local"):
        return {"valid": False, "email": mail, "reason": "Domaine non routable"}
    if check_dns:
        try:
            socket.getaddrinfo(domaine, None)
        except OSError:
            return {"valid": False, "email": mail, "reason": f"Domaine introuvable en DNS ({domaine})"}
    return {"valid": True, "email": mail, "reason": "Syntaxe et domaine valides"}


class EmailConnector:
    """Connecteur email modulaire : Resend API ou SMTP sortant + IMAP entrant."""

    @staticmethod
    def status() -> dict[str, Any]:
        resend_ok = bool(os.getenv("RESEND_API_KEY") and os.getenv("YALLAH_FROM_EMAIL"))
        smtp_ok = bool(os.getenv("SMTP_HOST") and os.getenv("YALLAH_FROM_EMAIL"))
        imap_ok = bool(os.getenv("IMAP_HOST") and os.getenv("IMAP_USER") and os.getenv("IMAP_PASSWORD"))
        live = os.getenv("YALLAH_ENABLE_LIVE") == "1"
        tracking = os.getenv("YALLAH_EMAIL_TRACKING", "0") == "1"
        mode = "resend" if resend_ok else ("smtp" if smtp_ok else "non_configure")
        errors = []
        if not live:
            errors.append("Envois réels désactivés (YALLAH_ENABLE_LIVE!=1)")
        if not (resend_ok or smtp_ok):
            errors.append("Configurez RESEND_API_KEY ou SMTP_HOST ainsi que YALLAH_FROM_EMAIL")
        return {
            "provider": mode,
            "ready": live and (resend_ok or smtp_ok),
            "configured": resend_ok or smtp_ok,
            "smtp_configured": smtp_ok,
            "resend_configured": resend_ok,
            "imap_configured": imap_ok,
            "tracking_enabled": tracking,
            "digest_recipient": os.getenv("YALLAH_DIGEST_EMAIL", ""),
            "errors": errors,
        }

    @staticmethod
    def send(
        to_email: str,
        subject: str,
        text_body: str,
        *,
        html_body: str = "",
        unsubscribe_url: str = "",
        idempotency_key: str = "",
        require_live_flag: bool = True,
    ) -> dict[str, Any]:
        check = verifier_delivrabilite_email(to_email)
        if not check["valid"]:
            raise ValueError(f"Email non délivrable : {check['reason']}")
        if require_live_flag and os.getenv("YALLAH_ENABLE_LIVE") != "1":
            raise ComplianceError("Envoi email réel bloqué : YALLAH_ENABLE_LIVE n'est pas activé.")

        from_email = os.getenv("YALLAH_FROM_EMAIL", "").strip()
        if not from_email:
            raise ValueError("YALLAH_FROM_EMAIL non configuré")

        # Priorité Resend si configuré, sinon SMTP standard
        if os.getenv("RESEND_API_KEY"):
            payload: dict[str, Any] = {
                "from": from_email,
                "to": [check["email"]],
                "subject": subject,
                "text": text_body,
            }
            if html_body:
                payload["html"] = html_body
            if unsubscribe_url:
                payload["headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>"}
            headers = {
                "Authorization": "Bearer " + os.environ["RESEND_API_KEY"],
                "Content-Type": "application/json",
            }
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key
            req = Request(
                "https://api.resend.com/emails",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urlopen(req, timeout=25) as resp:
                data = json.load(resp)
            return {"ok": True, "provider": "resend", "provider_id": str(data.get("id", ""))}

        smtp_host = os.getenv("SMTP_HOST", "").strip()
        if not smtp_host:
            raise ValueError("Aucun fournisseur email configuré (RESEND_API_KEY ou SMTP_HOST)")

        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "").strip()
        smtp_pass = os.getenv("SMTP_PASSWORD", "")
        use_tls = os.getenv("SMTP_USE_TLS", "1") == "1"

        msg = EmailMessage()
        msg["From"] = from_email
        msg["To"] = check["email"]
        msg["Subject"] = subject
        if unsubscribe_url:
            msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(smtp_host, smtp_port, timeout=25) as client:
            if use_tls:
                client.starttls(context=ssl.create_default_context())
            if smtp_user and smtp_pass:
                client.login(smtp_user, smtp_pass)
            client.send_message(msg)
        msg_id = hashlib.sha256(f"{check['email']}|{subject}|{_utc_now()}".encode()).hexdigest()[:20]
        return {"ok": True, "provider": "smtp", "provider_id": "smtp-" + msg_id}

    @staticmethod
    def fetch_unseen_imap(limit: int = 20) -> list[dict[str, Any]]:
        """Lit les emails non lus via IMAP (si configuré) pour ingestion réponses & détection STOP."""
        host = os.getenv("IMAP_HOST", "").strip()
        user = os.getenv("IMAP_USER", "").strip()
        password = os.getenv("IMAP_PASSWORD", "")
        if not (host and user and password):
            return []
        port = int(os.getenv("IMAP_PORT", "993"))
        results: list[dict[str, Any]] = []
        with imaplib.IMAP4_SSL(host, port) as mailbox:
            mailbox.login(user, password)
            mailbox.select("INBOX")
            typ, data = mailbox.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()[: max(1, min(50, limit))]
            for mid in ids:
                typ_m, msg_data = mailbox.fetch(mid, "(RFC822)")
                if typ_m != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw_bytes = msg_data[0][1]
                if not isinstance(raw_bytes, bytes):
                    continue
                parsed = email_lib.message_from_bytes(raw_bytes)
                raw_from = parsed.get("From", "")
                raw_subj = parsed.get("Subject", "")
                subject = "".join(
                    (part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else str(part))
                    for part, enc in decode_header(raw_subj)
                )
                body = ""
                if parsed.is_multipart():
                    for part in parsed.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                                break
                else:
                    payload = parsed.get_payload(decode=True)
                    if payload:
                        body = payload.decode(parsed.get_content_charset() or "utf-8", errors="replace")
                m_addr = re.search(r"[^\s<>\"']+@[^\s<>\"']+\.[^\s<>\"']+", raw_from)
                sender_email = ym.email_normalise(m_addr.group(0)) if m_addr else ""
                est_stop, kw = analyzer.detecter_stop(subject + "\n" + body)
                results.append(
                    {
                        "message_id": (parsed.get("Message-ID") or "").strip()[:280],
                        "sender_email": sender_email,
                        "sender_name": raw_from.split("<")[0].strip(" \"'")[:150],
                        "subject": subject[:300],
                        "body": body[:4000],
                        "stop_detecte": est_stop,
                        "stop_mot_cle": kw,
                    }
                )
        return results


# ---------------------------------------------------------------------------
# 2. Connecteur WhatsApp Business Platform / Cloud API
# ---------------------------------------------------------------------------
class WhatsAppConnector:
    """Connecteur WhatsApp Business officiel (Meta Cloud API) avec verrou opt-in strict."""

    @staticmethod
    def status() -> dict[str, Any]:
        token = bool(os.getenv("WHATSAPP_ACCESS_TOKEN"))
        phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        tpl = os.getenv("WHATSAPP_TEMPLATE_NAME", "").strip()
        tpl_lang = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "fr").strip()
        reviewed = os.getenv("WHATSAPP_TEMPLATE_REVIEWED") == "1"
        live = os.getenv("YALLAH_ENABLE_LIVE") == "1"
        errors = []
        if not live:
            errors.append("Envois réels désactivés (YALLAH_ENABLE_LIVE!=1)")
        if not token or not phone_id:
            errors.append("Configurez WHATSAPP_ACCESS_TOKEN et WHATSAPP_PHONE_NUMBER_ID")
        if phone_id and not phone_id.isdigit():
            errors.append("WHATSAPP_PHONE_NUMBER_ID numérique attendu")
        if not tpl or not reviewed:
            errors.append("Modèle WhatsApp Business approuvé requis (WHATSAPP_TEMPLATE_NAME + WHATSAPP_TEMPLATE_REVIEWED=1)")
        return {
            "provider": "meta_cloud_api" if (token and phone_id) else "non_configure",
            "ready": live and token and phone_id.isdigit() and bool(tpl) and reviewed,
            "configured": token and phone_id.isdigit(),
            "template_name": tpl,
            "template_language": tpl_lang,
            "template_reviewed": reviewed,
            "digest_recipient": os.getenv("YALLAH_DIGEST_WHATSAPP", ""),
            "errors": errors,
        }

    @staticmethod
    def send(
        to_phone: str,
        text_body: str,
        *,
        has_opt_in: bool = False,
        is_internal_digest: bool = False,
        use_template: bool = True,
        template_name: str = "",
        template_language: str = "",
        require_live_flag: bool = True,
    ) -> dict[str, Any]:
        if not is_internal_digest and not has_opt_in:
            raise ComplianceError(
                "Envoi WhatsApp interdit : consentement explicite WhatsApp (opt-in) non prouvé."
            )
        if require_live_flag and os.getenv("YALLAH_ENABLE_LIVE") != "1":
            raise ComplianceError("Envoi WhatsApp réel bloqué : YALLAH_ENABLE_LIVE n'est pas activé.")
        dest = ym.tel_normalise(to_phone)
        if not re.fullmatch(r"[1-9]\d{7,14}", dest):
            raise ValueError("Numéro WhatsApp international invalide")

        token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
        phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        version = os.getenv("WHATSAPP_GRAPH_VERSION", "v23.0").strip()
        if not token or not phone_id.isdigit():
            raise ValueError("WhatsApp Cloud API non configuré")

        if use_template:
            tpl = (template_name or os.getenv("WHATSAPP_TEMPLATE_NAME", "")).strip()
            lang = (template_language or os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "fr")).strip()
            if not tpl:
                raise ComplianceError("Template WhatsApp Business approuvé requis")
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": dest,
                "type": "template",
                "template": {
                    "name": tpl,
                    "language": {"code": lang},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": text_body.replace("\n", " ")[:1000]}],
                        }
                    ],
                },
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": dest,
                "type": "text",
                "text": {"preview_url": False, "body": text_body[:4000]},
            }

        req = Request(
            f"https://graph.facebook.com/{version}/{phone_id}/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=25) as resp:
            data = json.load(resp)
        msg_id = str((data.get("messages") or [{}])[0].get("id", ""))
        return {"ok": True, "provider": "meta_cloud_api", "provider_id": msg_id}


# ---------------------------------------------------------------------------
# 3. Connecteur de Recherche Web & Extraction B2B Publique (robots.txt + limites)
# ---------------------------------------------------------------------------
class WebDiscoveryConnector:
    """Extraction structurée de pages publiques B2B (Contact, À propos, Carrières).

    Respecte :
    - Liste noire absolue des réseaux privés (Facebook, Instagram, TikTok, LinkedIn, groupes WhatsApp).
    - Vérification `robots.txt` avant tout téléchargement réseau.
    - Limitation de débit par domaine (`min_delay_seconds`).
    - Conservation systématique de l'URL source, date/heure et preuve textuelle.
    """

    _last_hit: dict[str, float] = {}

    @staticmethod
    def status() -> dict[str, Any]:
        return {
            "google_places_configured": bool(os.getenv("GOOGLE_PLACES_API_KEY")),
            "brave_search_configured": bool(os.getenv("BRAVE_SEARCH_API_KEY")),
            "serpapi_configured": bool(os.getenv("SERPAPI_API_KEY")),
            "public_page_extractor_ready": True,
            "robots_txt_enforced": True,
            "forbidden_domains_blocked": list(FORBIDDEN_SCRAPE_DOMAINS),
        }

    @classmethod
    def verifier_url_autorisee(cls, url: str) -> str:
        clean = (url or "").strip()
        parsed = urlparse(clean)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ComplianceError("URL publique HTTP(S) valide requise.")
        host = parsed.hostname.lower().removeprefix("www.")
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.startswith(("10.", "192.168.", "169.254.")):
            raise ComplianceError("Adresse réseau privée interdite.")
        for bad in FORBIDDEN_SCRAPE_DOMAINS:
            if host == bad or host.endswith("." + bad):
                raise ComplianceError(
                    f"Extraction automatique interdite sur {bad} (respect CGU et Loi 09-08)."
                )
        return clean

    @classmethod
    def verifier_robots_txt(cls, url: str, *, robots_content: str | None = None) -> bool:
        """Vérifie si l'accès à `url` est autorisé par robots.txt."""
        clean = cls.verifier_url_autorisee(url)
        rp = RobotFileParser()
        if robots_content is not None:
            rp.parse(robots_content.splitlines())
            return rp.can_fetch(USER_AGENT, clean)
        parsed = urlparse(clean)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp.set_url(robots_url)
        try:
            req = Request(robots_url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=8) as resp:
                body = resp.read(65536).decode("utf-8", errors="replace")
            rp.parse(body.splitlines())
            return rp.can_fetch(USER_AGENT, clean)
        except HTTPError as exc:
            if exc.code in (401, 403):
                return False
            return True
        except URLError:
            return True

    @classmethod
    def _strip_html(cls, raw_html: str) -> str:
        no_script = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", raw_html or "", flags=re.I | re.S)
        no_tags = re.sub(r"<[^>]+>", " ", no_script)
        return re.sub(r"\s+", " ", html_lib.unescape(no_tags)).strip()

    @classmethod
    def extraire_prospect_depuis_html(
        cls,
        url: str,
        raw_html: str,
        *,
        source_nom: str = "site_web_officiel",
        default_city: str = "",
    ) -> dict[str, Any]:
        """Extrait uniquement les coordonnées professionnelles publiquement affichées sur une page HTML."""
        clean_url = cls.verifier_url_autorisee(url)
        parsed = urlparse(clean_url)
        texte = cls._strip_html(raw_html)
        folded = analyzer._fold_latin(texte)

        # 1. Nom de l'entreprise (<h1>, og:site_name, <title>)
        nom = ""
        for pat in (
            r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']',
            r"<h1[^>]*>(.*?)</h1>",
            r"<title[^>]*>(.*?)</title>",
        ):
            m = re.search(pat, raw_html or "", flags=re.I | re.S)
            if m:
                cand = cls._strip_html(m.group(1)).split("|")[0].split("—")[0].split(" - ")[0].strip()
                if 2 <= len(cand) <= 120:
                    nom = cand
                    break
        if not nom:
            nom = parsed.hostname.removeprefix("www.").split(".")[0].replace("-", " ").title()

        # 2. Email professionnel public (jamais deviné !)
        emails_found = re.findall(r"mailto:([^\s\"'?<>]+@[^\s\"'?<>]+)", raw_html or "", flags=re.I)
        emails_found += re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", texte)
        email_pro = ""
        for em in emails_found:
            check = verifier_delivrabilite_email(em)
            if check["valid"]:
                email_pro = check["email"]
                break

        # 3. Téléphone professionnel public (format Maroc)
        phones = re.findall(r"(?:\+212|00212|0)[\s.-]?[567](?:[\s.-]?\d{2}){4}", texte)
        tel_pro = sources.norm_tel(phones[0]) if phones else ""

        # 4. WhatsApp professionnel public UNIQUEMENT si explicitement publié comme lien/canal WhatsApp
        whatsapp_pro = ""
        m_wa = re.search(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=)\+?(\d{9,15})", raw_html or "", flags=re.I)
        if m_wa:
            whatsapp_pro = sources.norm_tel("+" + m_wa.group(1))
        else:
            m_wa_txt = re.search(
                r"whatsapp[^0-9+]{0,20}((?:\+212|00212|0)[\s.-]?[67](?:[\s.-]?\d{2}){4})",
                texte,
                flags=re.I,
            )
            if m_wa_txt:
                whatsapp_pro = sources.norm_tel(m_wa_txt.group(1))

        # 5. Segment d'établissement
        seg_rules = [
            ("hotel", ("hotel", "hôtel", "suites", "resort", "palace")),
            ("riad", ("riad", "maison d'hotes", "maison d’hôtes")),
            ("traiteur", ("traiteur", "catering")),
            ("evenementiel", ("evenementiel", "événementiel", "organisation d'evenements", "banquet", "salle des fetes")),
            ("conciergerie", ("conciergerie", "residence hoteliere", "résidence hôtelière", "syndic")),
            ("restaurant", ("restaurant", "brasserie", "bistrot", "gastronomie", "cafe restaurant")),
            ("clinique_senior", ("clinique", "centre medical", "soins a domicile", "geriatrie")),
            ("creche_ecole", ("creche", "crèche", "maternelle", "ecole privee")),
            ("agence_immo", ("agence immobiliere", "immobilier", "real estate")),
            ("nettoyage", ("societe de nettoyage", "proprete industrielle")),
            ("entreprise", ("entreprise", "societe", "groupe", "siege social")),
        ]
        type_etab = "entreprise"
        for seg_code, mots in seg_rules:
            if any(analyzer._fold_latin(m) in folded for m in mots):
                type_etab = seg_code
                break

        # 6. Ville & quartier
        ville = default_city
        quartier = ""
        for cle, nom_q in analyzer.QUARTIERS_CASABLANCA.items():
            if not re.search(r"[\u0600-\u06FF]", cle) and re.search(r"\b" + re.escape(analyzer._fold_latin(cle)) + r"\b", folded):
                quartier = nom_q
                if not ville:
                    ville = "Bouskoura" if nom_q in ("Bouskoura", "Ville Verte") else "Casablanca"
                break
        if not ville:
            for cle, (v_nom, _ph) in analyzer.VILLES_CONNUES.items():
                if not re.search(r"[\u0600-\u06FF]", cle) and re.search(r"\b" + re.escape(analyzer._fold_latin(cle)) + r"\b", folded):
                    ville = v_nom
                    break

        # 7. Signaux d'intérêt publics
        signaux: list[str] = []
        signal_map = [
            ("page_carrieres", ("carrieres", "carrières", "rejoignez-nous", "nous rejoindre", "espace recrutement")),
            ("annonce_embauche", ("nous recrutons", "offre d'emploi", "offres d'emploi", "poste a pourvoir", "postes a pourvoir", "recrute")),
            ("ouverture", ("nouvelle ouverture", "ouverture prochaine", "nouveau restaurant", "nouvel hotel")),
            ("extension", ("agrandissement", "nouvelle equipe", "nouvelle filiale", "expansion")),
            ("evenement", ("evenements prives", "seminaires", "banquets", "receptions", "mariages")),
        ]
        for sig, mots in signal_map:
            if any(analyzer._fold_latin(m) in folded for m in mots):
                signaux.append(sig)

        besoins_par_seg = {
            "hotel": "entretien des chambres, cuisine, service en salle",
            "riad": "personnel de maison, cuisine, entretien",
            "restaurant": "cuisine, plonge, service en salle",
            "traiteur": "renfort cuisine, service, extras événementiels",
            "evenementiel": "extras de service, accueil, renfort événementiel",
            "conciergerie": "personnel de maison, ménage, gouvernance",
            "clinique_senior": "aide à domicile, entretien",
            "creche_ecole": "entretien des locaux, accompagnement",
            "agence_immo": "personnel de maison pour résidents, entretien",
            "entreprise": "propreté des locaux, accueil, services généraux",
        }
        besoin_probable = besoins_par_seg.get(type_etab, "renfort en personnel opérationnel")

        # 8. Preuve textuelle sourcée
        preuve_parts = []
        if email_pro:
            preuve_parts.append(f"Email public : {email_pro}")
        if tel_pro:
            preuve_parts.append(f"Tél public : {tel_pro}")
        if whatsapp_pro:
            preuve_parts.append(f"WhatsApp public publié : {whatsapp_pro}")
        if signaux:
            preuve_parts.append("Signaux : " + ", ".join(signaux))
        extrait_court = texte[:200]
        if extrait_court:
            preuve_parts.append(f"Extrait : « {extrait_court} »")

        return {
            "nom_entreprise": nom,
            "type_etablissement": type_etab,
            "ville": ville or "Casablanca",
            "quartier": quartier or "Centre",
            "adresse_publique": "",
            "site_web": f"{parsed.scheme}://{parsed.netloc}",
            "email_pro": email_pro,
            "tel_pro": tel_pro,
            "whatsapp_pro": whatsapp_pro,
            "source_url": clean_url,
            "source_nom": source_nom,
            "date_consultation": _utc_now(),
            "preuve_extrait": " | ".join(preuve_parts)[:600],
            "besoin_probable": besoin_probable,
            "signaux_interet": signaux,
            "niveau": "A" if (email_pro or tel_pro or whatsapp_pro) else "C",
        }

    @classmethod
    def inspecter_page_publique(
        cls,
        url: str,
        *,
        min_delay_seconds: float = 1.5,
        check_robots: bool = True,
    ) -> dict[str, Any]:
        """Télécharge et extrait une page publique B2B dans le strict respect de robots.txt et du rate-limit."""
        clean_url = cls.verifier_url_autorisee(url)
        if check_robots and not cls.verifier_robots_txt(clean_url):
            raise ComplianceError(f"Accès refusé par robots.txt pour {clean_url}")

        host = (urlparse(clean_url).hostname or "").lower()
        now_t = time.monotonic()
        elapsed = now_t - cls._last_hit.get(host, 0.0)
        if elapsed < min_delay_seconds:
            time.sleep(min_delay_seconds - elapsed)
        cls._last_hit[host] = time.monotonic()

        req = Request(clean_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        with urlopen(req, timeout=15) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "application/xhtml" not in ctype:
                raise ValueError(f"Contenu non HTML ({ctype})")
            raw_html = resp.read(512_000).decode("utf-8", errors="replace")
        return cls.extraire_prospect_depuis_html(clean_url, raw_html)


def connectors_status() -> dict[str, Any]:
    """État agrégé des connecteurs techniques modulaires (aucun secret exposé)."""
    return {
        "email": EmailConnector.status(),
        "whatsapp": WhatsAppConnector.status(),
        "web_discovery": WebDiscoveryConnector.status(),
    }
