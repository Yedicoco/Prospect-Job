# Guide d’utilisation — Moteur d’acquisition autonome & CRM (Yallah Services, Casablanca)

Ce guide décrit le fonctionnement complet de la couche d’**acquisition commerciale autonome** ajoutée à **Yallah Services**, sans rompre aucun module existant (`prospects`, `campagnes`, `messages`, `CRM`, `conversations`, `recrutement`, `tableau de bord`).

---

## 1. Architecture & modules ajoutés

| Fichier | Rôle |
|---|---|
| `yallah_analyzer.py` | Analyseur multilingue **Français / Darija / Arabe** sans invention (extraction avec preuves textuelles), détecteur **STOP** immédiat, scoring **Besoin Client (0–100)**, scoring **Prospect Pro (0–100)**, génération de messages (familles, pros, relances J+3/J+7/J+14) et garde-fou anti-invention. |
| `yallah_connectors.py` | Connecteurs modulaires sans dépendance externe : **Email** (Resend API + SMTP + lecture IMAP + vérification délivrabilité, tracking désactivé), **WhatsApp Business Cloud API** (opt-in + modèles approuvés obligatoires) et **Découverte Web publique** (`robots.txt`, limitation de débit, blocage strict des réseaux privés). |
| `yallah_autonome.py` | Moteur SQLite (schéma prêt PostgreSQL) : 14 tables minimales, capture B2C, prospection B2B publique, dédoublonnage unifié, workflow de validation en 5 étapes (9 boutons), file d’envoi, relances automatiques J+3/J+7/J+14, **Daily Prospect Digest** (Email + WhatsApp sans exposition de coordonnées sensibles), **Mode Auto-pilot** sécurisé avec arrêt en 1 clic, pipelines Familles & Pros, KPIs et export d’audit. |
| `schema_postgresql.sql` | Schéma PostgreSQL complet correspondant aux 14 tables minimales. |
| `web/autonome.js` | 4 pages dans l’interface web privée : **Acquisition autonome**, **Demandes Clients**, **Prospection B2B** et **File d’envoi**. |

---

## 2. Conformité juridique & règles anti-abus (Loi 09-08 / CNDP / WhatsApp Business)

Le moteur applique ces règles au niveau du code (non contournables côté interface) :

1. **Particuliers (B2C) — zéro prospection froide** :
   - Seules les demandes volontaires entrantes (formulaire `/demande`, pages `/services/<slug>`, WhatsApp entrant, email officiel, appel entrant, message volontaire sur les réseaux, formulaire publicitaire, recommandation ou partenaire avec accord explicite) sont acceptées.
   - Les formulaires publics affichent **2 cases distinctes non précochées** :
     - `J’accepte que Yallah Services me recontacte au sujet de ma demande.`
     - `J’accepte de recevoir des messages de Yallah Services sur WhatsApp.`
   - Mention visible sur tous les formulaires :
     > *Vous pouvez demander l’arrêt des communications à tout moment en répondant STOP.*
2. **WhatsApp Business** :
   - Aucun envoi WhatsApp sans numéro fourni + consentement WhatsApp explicite documenté.
   - En cas de doute, l’envoi est bloqué et une validation humaine est demandée.
   - Hors fenêtre de réponse 24 h, un modèle WhatsApp approuvé (`WHATSAPP_TEMPLATE_NAME` + `WHATSAPP_TEMPLATE_REVIEWED=1`) est requis.
3. **Interdictions strictes (bloquées techniquement)** :
   - Aucun scraping de Facebook, Instagram, TikTok, LinkedIn ou de groupes WhatsApp.
   - Aucune liste achetée, aucune devinette d’email ou de numéro.
   - Un appel manqué, un like, un commentaire ou une visite de site ne vaut **jamais** consentement.
   - Aucune publicité commerciale envoyée aux candidats.
   - Aucune invention de tarif, salaire, délai garanti, disponibilité, budget, urgence ou préférence personnelle/religieuse.
4. **Détection STOP & blocage immédiat définitif** :
   - Mots-clés détectés automatiquement (insensibles à la casse et aux accents) : `STOP`, `STOP SMS`, `désinscription`, `desinscription`, `ne plus me contacter`, `ne plus nous contacter`, `retirez-moi`, `arrêtez`, `arretez`, `unsubscribe`, `إلغاء الاشتراك`, `توقف`, `حبس`, etc.
   - Effet immédiat : inscription dans `blocages` et `suppressions`, révocation des consentements actifs, annulation de tous les envois en file et de toutes les relances planifiées, journalisation dans `audit_log` (date, heure, canal, motif).

---

## 3. Capture & analyse des Demandes Clients (B2C)

### Sources entrantes autorisées
`formulaire_prestation`, `formulaire_contact`, `whatsapp_bouton_site`, `whatsapp_entrant`, `email_officiel`, `appel_entrant`, `facebook_message`, `instagram_message`, `tiktok_message`, `google_business_message`, `publicite_formulaire`, `recommandation_consentie`, `partenaire_local_consenti`.

### Analyse automatique multilingue (FR / Darija / Arabe)
Exemples reconnus sans rien inventer :
- *« Bonjour, je cherche une femme de ménage à Anfa 3 fois par semaine. »* → `menage`, `hebdomadaire`, `Anfa` (Casablanca), langue `fr`.
- *« Salam bghit mrabia l benti f Maarif men lundi tal vendredi. »* → `garde_enfants`, `temps_plein`, `Maarif` (Casablanca), langue `darija`.
- *« السلام عليكم، كنقلب على مساعدة منزلية للطبخ والتنظيف فكاليفورنيا. »* → `cuisine` / `menage`, `Californie` (Casablanca), langue `arabe`.

### Scoring « Besoin Client Score » (0 à 100)
| Critère | Points max |
|---|---|
| Clarté du besoin | 30 |
| Zone desservie (Casablanca / Bouskoura / Mohammedia / Rabat / Marrakech) | 20 |
| Moyen de contact valide | 15 |
| Urgence ou date précisée | 10 |
| Compatibilité avec les services Yallah Services | 15 |
| Complétude générale | 10 |

- **Classe A (Prioritaire)** : score ≥ 75 (et contact valide + non bloqué).
- **Classe B (À qualifier)** : score 50–74 ou informations incomplètes.
- **Classe C (Faible priorité)** : score < 50.
- **Exclu** : contact bloqué / STOP ou source interdite.

### Première réponse automatique (strictement réactive)
Préparée automatiquement pour toute demande entrante avec consentement recontact. Elle :
1. Confirme la réception de la demande ;
2. Pose 2 à 4 questions courtes maximum (uniquement sur les champs non précisés) ;
3. Propose un appel ou rendez-vous ;
4. N’invente ni tarif, ni délai, ni disponibilité ;
5. Inclut une mention STOP claire dans la langue du client.

---

## 4. Prospection B2B (Professionnels)

### Sources publiques autorisées uniquement
`google_maps_places`, `site_officiel`, `page_contact_carrieres`, `offre_emploi_publique`, `reseau_pro_public`, `annuaire_pro_public`, `formulaire_entrant_pro`, `recommandation_partenaire_pro`.

Pour chaque prospect, la base conserve l’URL source, la date/heure de consultation, l’extrait/preuve publique et les signaux d’intérêt.

### Scoring « Prospect Pro Score » (0 à 100)
| Critère | Points max |
|---|---|
| Pertinence du segment (hôtels, restaurants, traiteurs, événementiel, conciergeries, entreprises) | 25 |
| Probabilité de besoin en personnel | 25 |
| Qualité et vérifiabilité du contact | 20 |
| Localisation (Casablanca et zones desservies) | 15 |
| Potentiel estimé | 10 |
| Fraîcheur du signal | 5 |

- **Classe A** : score ≥ 75 + contact vérifié + source publique fiable + besoin plausible.
- **Classe B** : score 50–74 ou dossier incomplet.
- **Classe C** : score < 50.
- **Exclu** : source interdite ou contact bloqué.

---

## 5. Workflow de validation en 5 étapes & 9 actions sur fiche

1. **Demande entrante ou prospect public découvert**
2. **Analyse automatique** (sans invention)
3. **Qualification & scoring 0–100** (A / B / C / Exclu)
4. **Validation humaine** dans l’interface web (ou digest quotidien)
5. **Envoi manuel ou automatique contrôlé**

Sur chaque fiche B2C ou B2B, 9 boutons d’action sont disponibles :
- **Valider** · **Modifier le message** · **Rejeter** · **Bloquer définitivement** · **Demander une vérification** · **Appeler** · **Répondre sur WhatsApp** · **Envoyer maintenant** *(avec confirmation explicite)* · **Programmer l’envoi** *(avec date/heure et confirmation explicite)*.

Toutes les opérations passent par la page **File d’envoi** (`envois`), accompagnée des **Relances planifiées** (`J+3`, `J+7`, `J+14` — maximum 3, annulées dès qu’une réponse, un RDV ou un STOP arrive).

---

## 6. Daily Prospect Digest (Matin)

Chaque matin (et à la demande depuis la page **Acquisition autonome** ou en CLI), le digest présente :
- Compteurs : nouvelles demandes, qualifiées A B2C, qualifiés A B2B, doublons évités, invalides/rejetés, STOP/retraits ;
- Top 5 à 10 priorités avec nom, type, quartier, score, besoin, canal, source, message recommandé et liens d’action ;
- **Sécurité WhatsApp** : la version WhatsApp du digest ne contient **jamais** d’email ni de numéro personnel sensible — uniquement le nom, le score et le lien sécurisé vers la fiche interne.

---

## 7. Mode Auto-pilot (optionnel & réservé aux administrateurs)

- **Désactivé par défaut** (`enabled = false`).
- **Réservé au rôle `admin`** : activation, modification des plafonds (`15` premiers contacts/jour par défaut, max `3` relances J+3/J+7/J+14, jamais 2 messages le même jour) et exécution.
- **Arrêt en un clic (Kill Switch)** : bouton rouge dédié dans l’interface ou appel API `/api/autonome/autopilot` (`action: "kill_switch"`).
- **Garde-fous automatiques (Circuit-breaker)** : s’arrête immédiatement en cas de taux de rebond anormal (≥ 8 %), plainte/STOP élevé ou erreurs API répétées.
- Sélectionne **uniquement les fiches de niveau A** disposant d’un consentement valide pour le canal retenu.

---

## 8. Rôles, sauvegarde, audit & commandes CLI

### Rôles disponibles (`access.py`)
- `admin` : accès complet, Auto-pilot, modification des plafonds, export du journal d’audit (`/api/audit/export?format=csv|json`), sauvegardes.
- `commercial` : gestion des demandes clients B2C, prospection B2B, validation, digest, pipeline commercial.
- `recruteur` (et alias `recrutement`) : besoins d’emploi, candidats, matching, missions.
- `lecture` : consultation en lecture seule.

### Commandes CLI (`manage.py`)
```bash
# Générer ou envoyer le Daily Prospect Digest
python3 manage.py daily-digest
python3 manage.py daily-digest --send                     # simulation par défaut
python3 manage.py daily-digest --send --live              # envoi réel (si fournisseurs configurés)

# Exécuter un cycle Auto-pilot (simulation par défaut)
python3 manage.py autopilot-run
python3 manage.py autopilot-run --live                    # uniquement si Auto-pilot activé + YALLAH_ENABLE_LIVE=1

# Exporter le journal d'audit (CSV ou JSON)
python3 manage.py audit-export --format csv --out audit.csv
python3 manage.py audit-export --format json --out audit.json

# Relever les réponses entrantes / STOP via IMAP
python3 manage.py imap-poll

# Sauvegarde SQLite manuelle (en plus de la sauvegarde quotidienne automatique)
python3 manage.py backup
```

### Migration vers PostgreSQL
Le fichier `schema_postgresql.sql` fournit le DDL PostgreSQL prêt à l’emploi pour les 14 tables minimales (`sources`, `contacts`, `consentements`, `demandes_clients`, `prospects`, `messages`, `campagnes`, `envois`, `reponses`, `blocages`, `relances`, `daily_digests`, `audit_log`, `settings`).

---

## 9. Lancer les tests automatisés

```bash
# Compilation statique de tous les modules Python
python3 -m py_compile webapp.py operations.py campaigns.py access.py validation.py webhooks.py yallah_sources.py yallah_b2c.py yallah_messages.py yallah_prospection.py yallah_emploi.py yallah_analyzer.py yallah_connectors.py yallah_autonome.py manage.py

# Suite Python complète (modules existants + moteur autonome)
python3 -m unittest discover -s tests -v

# Tests DOM de l'interface web (existants + pages autonomes)
npm test
node --test tests/test_autonome_ui.cjs
```
