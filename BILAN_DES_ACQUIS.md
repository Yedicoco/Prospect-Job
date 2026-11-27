# Bilan des acquis et propositions d'amélioration — Prospect-Job / Yallah Services

**Date :** 27 novembre 2026 · **Périmètre :** code, documentation et tests de la branche de travail.
**Objectif du projet (rappel) :** obtenir des besoins réels d'employeurs et les convertir en prestations
de mise en relation réussies et rentables (B2B hôtellerie/restauration, B2C familles, emploi candidats),
avec un traitement licite et maîtrisé des contacts au Maroc.

**Vérifié aujourd'hui :** `python3 -m unittest discover -s tests` → **205 tests OK** · `npm test` → **11 tests OK**.

---

## 1. Bilan des acquis

### 1.1 Socle applicatif et exploitation — ✅ acquis solides

| Acquis | Détail |
|---|---|
| Application web unifiée | `webapp.py` (Python stdlib, **zéro dépendance**), interface française : tableau de bord, prospects, campagnes, conversations, recrutement, supervision |
| Stockage | Base **SQLite unifiée** (`data/yallah.sqlite3`), relations et clés étrangères, migrations idempotentes, index, verrou POSIX anti-double-ouverture |
| Déploiement multi-choix | Double-clic local (`Lancer_Yallah.command` / `.bat`), **Render 1-clic** (`render.yaml` avec disque persistant et mot de passe généré), **Dockerfile** (utilisateur non-root, health check) |
| Comptes et rôles | `manage.py` : admin, commercial, recrutement, lecture ; mots de passe **PBKDF2-SHA256, 600 000 itérations**, sel individuel ; `YALLAH_ENV=production` refuse de démarrer sans admin fort et URL HTTPS |
| Traçabilité | Journal d'audit horodaté avec auteur sur toutes les opérations sensibles ; preuves d'autorisation conservées et historisées |
| Supervision et résilience | Sauvegardes automatiques quotidiennes (permissions 0600, contrôle d'intégrité), **restauration testée en aller-retour**, arrêt d'urgence global des campagnes, santé worker |
| Qualité logicielle | **205 tests Python + 11 tests DOM/Node**, CI GitHub Actions (`.github/workflows/tests.yml`) |

### 1.2 Données prospects et qualité — ✅ acquis réels

- **48 fiches B2B sourcées** (Casablanca, Rabat, Marrakech, Bouskoura, Tanger, Agadir…) : 18 niveau A, 29 niveau B, 1 niveau C — chacune avec **URL source et date de consultation obligatoires** ; une fiche sans provenance est refusée.
- **Import JSON/CSV contrôlé** (aperçu des erreurs et doublons, import atomique 1–200 fiches) et **export de synchronisation** vers les CLI (`manage.py export-json`, refus SQLite fusionnés).
- **Dédoublonnage** : normalisation +212, emails, clés `nom|ville`.
- **`quality_engine.py` + façade `crm_quality.py`** : normalisation des contacts (email/téléphone/WhatsApp), scoring explicable 0–100 avec raisons, transitions CRM validées, clés d'idempotence, **ROI réalisé sur encaissements réels uniquement**.
- **Registre des refus partagé** B2B/B2C : un STOP bloque tout futur contact sur tous les canaux.

### 1.3 Messages et prospection — ✅ préparation complète, envoi volontairement manuel

- `yallah_messages.py` : messages **français, darija et arabe**, un contact à la fois, garde-fous éditoriaux stricts (aucun prix, délai, garantie, disponibilité ou qualification inventés).
- **Plafond de 15 prises de contact/jour**, relances graduées **J+3 / J+7 / J+14** servies avant les premiers contacts, fiches non revérifiées depuis 7 jours exclues.
- `yallah_prospection.py` : segmentation B1–B4, priorisation, niveaux de vérification A/B/C.
- **35 pages SEO locales publiques** (`/services/<slug>`, quartiers × besoins à Casablanca phase 1) reliées au formulaire entrant et aux liens WhatsApp précodés (`wa.me`).

### 1.4 Campagnes automatisées — ✅ moteur prêt, simulation par défaut

- Campagnes **email (Resend)** et **WhatsApp Business (Meta)** : sélection explicite, simulation avec motifs de blocage, activation réelle conditionnée à `YALLAH_ENABLE_LIVE=1` + qualification + documentation de l'autorisation.
- **Autorisations par canal ET par coordonnée exacte**, désinscription signée, plafonds journaliers en `Africa/Casablanca`, intervalle anti-spam, worker avec file persistante.
- **Webhooks signés** : Resend (Svix, fenêtre 5 min, déduplication) et Meta (challenge + HMAC SHA256) ; événements livré/rebonds/plaintes/échec ; STOP multilingue reconnu ; messages de numéros inconnus routés « à qualifier » sans création d'autorisation.

### 1.5 CRM, recrutement et missions — ✅ parcours complets tracés

- **Pipeline commercial** en 8 étapes (prospect → qualifié → conversation → rendez-vous → besoin confirmé → proposition → gagné/perdu), avec responsable, prochaine action datée et **motif obligatoire de perte**.
- Opportunités liées aux clients, **création d'un besoin confirmé** depuis l'opportunité (source + date de confirmation exigées), propositions commerciales versionnées.
- **Besoins d'emploi** : toute valeur chiffrée exige sa source ; `POLITIQUE_FRAIS = "aucun"` (art. 480 du Code du travail) verrouillé ; fermeture = non publiable mais restant stockable.
- **Candidats → candidatures → affectations/missions** : rapprochement explicable (métier, ville, disponibilité), anti-chevauchement de missions, disponibilité à reconfirmer le jour même, retours et incidents non résolus tracés.
- **Chronologie omnicanale** : emails, WhatsApp, téléphone, notes dans une seule conversation ; import d'emails reçus dédupliqué (`Message-ID`) avec détection STOP hors citations.

### 1.6 Acquisition entrante — ✅ formulaires et attribution

- `/demande` et `/candidature` publics : données minimales, honeypot, limite 10 requêtes/heure/IP, attribution déclarative `?source=`, conversion d'une demande en contact + opportunité avec rapprochement des doublons.
- **ROI par source en MAD/h réel** (12 sources d'acquisition A1–C : formulaire, WhatsApp entrant, GBP, Avito, groupes FB, parrain, RH relocation, cliniques, agences immo…) avec suivi du temps opérateur en minutes.

### 1.7 Documentation et conformité — ✅ patrimoine méthodologique rare

10 documents métier cohérents : `AUDIT_ET_FEUILLE_DE_ROUTE` (47 fonctions backlog), `IMPLEMENTATION`, `PILOTE_LANCEMENT` (kit terrain prêt à exécuter), `PROSPECTION_B2B`, `MESSAGES_PROSPECTION`, `OFFRES_EMPLOI`, `WEB_APP`, `QUALITY_ENGINE`, `CRM_INTEGRATION`. Frontière « offre commerciale ≠ offre d'emploi » maintenue partout ; références légales cadrées (Loi 09-08 art. 10, art. 480).

### 1.8 Ce qui n'est PAS encore acquis (franchise)

| Point | État |
|---|---|
| Résultats commerciaux | **0 envoi commercial réel, 0 réponse, 0 besoin réel confirmé, 0 encaissement** au dernier état documenté — l'outil est prêt, la boucle n'est pas encore exécutée |
| Envois réels | Fournisseurs (Resend/Meta) non recettés en réel ; aucun webhook validé chez un fournisseur |
| Réponses email IMAP | Import manuel uniquement, pas de synchro continue |
| Décisions métier | **Grille tarifaire non figée** (bloquant pour toute proposition), périmètre pilote et rôles à arrêter |
| Multi-interlocuteurs / fusion complète | Détection de doublons OK ; modèle multi-contacts par établissement et fusion assistée non terminés |
| Pagination complète | Vues limitées aux 1 000 derniers éléments |
| Alertes externes | Supervision locale uniquement |

> **Lecture du bilan :** les acquis sont **techniques, organisationnels et juridiques** — la plateforme couvre la préparation, la traçabilité et la conformité. Le goulot d'étranglement n'est plus le code : c'est l'**exécution du pilote terrain** et les **décisions commerciales** (tarifs, cadrage) qui débloquent la conversion.

---

## 2. Propositions d'amélioration pour l'efficacité

Classées par **levier réel sur l'objectif** (besoins réels → prestations réussies → rentabilité), pas par complexité technique.

### 🔴 Priorité 1 — Fermer la boucle commerciale (levier maximal, coût quasi nul)

| # | Action | Pourquoi c'est efficace |
|---|---|---|
| 1 | **Exécuter le pilote `PILOTE_LANCEMENT.md`** : revérifier les 8 cibles score 10/10 le matin (15 min), contacter manuellement (≤ 15/j), tout retour saisi dans Pipeline/Conversations | C'est la seule action qui produit des données réelles. Tant qu'elle n'est pas faite, aucun indicateur ne peut guider les efforts suivants |
| 2 | **Figer la grille tarifaire** (forfait recherche / % salaire / forfait mise en relation — cf. §2 du pilote) | Décision bloquante : sans tarifs, aucune proposition ne peut être envoyée (le garde-fou le bloque volontairement) |
| 3 | **Rituel quotidien de 45 min** : file du jour `--file` le matin, saisie des temps `--temps`, ROI `--roi` chaque vendredi | Transforme l'outil en habitude ; c'est la condition pour que les indicateurs soient alimentés |

### 🟠 Priorité 2 — Rendre les canaux réellement opérationnels

| # | Action | Gain attendu |
|---|---|---|
| 4 | **Recette fournisseur réelle** : compte Resend + WhatsApp Business API, envoi pilote sur 1 coordonnée autorisée, vérification des webhooks signés (livré/rebonds/plaintes) | Passe de « simulation » à « canal maîtrisé » ; indispensable avant tout volume |
| 5 | **Connecter la boîte Gmail** (`servicesyallah@gmail.com`) : activer la synchro ou au minimum l'import quotidien des réponses via l'outil existant ; les libellés du pilote sont déjà créés | Les réponses sont la matière première de la conversion ; l'outil d'ingestion existe déjà, il faut l'alimenter |
| 6 | **Bibliothèque de modèles validés** (version, langue, segment, validateur) + objets email contextualisés (C5/C6) | Multiplie la qualité des messages sans toucher au volume ; permet des tests A/B honnêtes |
| 7 | **Créneaux horaires `Africa/Casablanca`** configurables (C4) | Évite les contacts hors heures ouvrées (meilleur taux de réponse, meilleure image) |

### 🟡 Priorité 3 — Piloter par les résultats, pas par le volume

| # | Action | Gain attendu |
|---|---|---|
| 8 | **Tableau de conversion par cohorte** (F1) : prospects → conversations → besoins confirmés → missions, avec dénominateurs distincts | Permet d'allouer le temps sur les sources qui convertissent (le ROI par source existe déjà, il lui manque la vue cohorte) |
| 9 | **Distinguer facturé / encaissé / marge** dans `Résultats et coûts` (F2) | La rentabilité réelle par prestation guide les décisions de prix |
| 10 | **Alertes externes simples** (email admin sur incident worker, échec webhook, arrêt d'urgence) | La supervision existe mais reste locale ; une alerte évite de rater une réponse client |
| 11 | **Expérimenter sur 2–3 sources seulement** (ex. `site_formulaire` + pages SEO locales + `partenaire_parrain`) et comparer les MAD/h | Concentre l'effort là où le retour est mesuré ; interdit la dispersion multi-villes prématurée |

### 🟢 Priorité 4 — Efficacité opérateur au quotidien

| # | Action | Gain attendu |
|---|---|---|
| 12 | **Pagination et recherche complètes** des listes (au-delà des 1 000 derniers éléments) | Confort dès que le volume de conversations/candidatures monte |
| 13 | **Multi-interlocuteurs par établissement** (A3) : distinguer Direction / RH / Achats | Évite de créer 3 prospects artificiels pour un hôtel ; augmente le taux de réponse (bon interlocuteur) |
| 14 | **Fusion assistée de doublons** (A4) avec survie de l'historique et des refus | Base propre = pression commerciale maîtrisée = protection des contacts |
| 15 | **Relances J+7 en semi-automatique** : file préparée, validation humaine puis envoi (C10) | Économise le temps opérateur sans casser le principe « aucun envoi sans contrôle » |
| 16 | **Faire évoluer les CLI sur la base SQLite unique** (aujourd'hui `export-json` synchronise à sens unique) | Supprime la double source de vérité JSON/SQLite, source future d'erreurs |

### 🔵 Priorité 5 — Robustesse long terme (quand les précédentes sont faites)

| # | Action |
|---|---|
| 17 | Tests de parcours en **navigateur réel** (Playwright) sur les 5 flux clés : demande entrante → opportunité, candidature → affectation, refus → blocage, campagne simulée, restauration |
| 18 | **Externalisation/chiffrement des sauvegardes** (un coffre Supabase Storage ou équivalent, ou réplication PostgreSQL/Supabase si le déploiement passe en multi-poste) |
| 19 | Modèle multi-interlocuteurs complet + pièces jointes contrôlées (D6), calendrier des entretiens |
| 20 | Purge/export individuel (RGPD/Loi 09-08) dès qu'un vrai volume de données personnelles est collecté |

### ⛔ Ce qu'il ne faut PAS prioriser (rappel de l'audit, toujours valide)

- Augmenter le nombre d'envois avant d'avoir des réponses exploitables.
- Acheter des listes ou extraire des numéros privés.
- Automatiser un compte WhatsApp personnel ou contourner les plateformes.
- Un classement IA des personnes sans critères professionnels explicables.
- Multiplier les villes avant d'avoir mesuré la capacité à servir et les résultats locaux.
- Refondre l'architecture (passage PostgreSQL, microservices…) avant d'avoir fermé la boucle commerciale.

---

## 3. Plan d'action suggéré sur 30 jours

| Semaine | Actions | Critère de sortie |
|---|---|---|
| **S1** | Figer la grille tarifaire + arrêter le périmètre pilote (1 ville, 2 segments) ; revérifier les 8 cibles score 10/10 | Décisions actées, contacts actualisés dans l'app |
| **S2** | Pilote terrain : 15 contacts/j max, saisie systématique dans Pipeline + Conversations + `--temps` | ≥ 30 contacts tracés, premières réponses enregistrées |
| **S3** | Recette Resend/Meta : configuration, 1 envoi pilote autorisé, vérification webhooks, import quotidien Gmail | Un message test livré et rapproché d'un événement fournisseur |
| **S4** | Revue des indicateurs (réponse utile, conversion par source, MAD/h) ; ajuster le message et le ciblage | Un tableau de bord alimenté par du réel, plan du mois 2 décidé sur les données |

---

## 4. Conclusion

**Acquis majeurs :** une plateforme complète, testée (216 tests au total), conforme et documentée, qui couvre le cycle acquisition → prospection → conversation → besoin → candidature → mission → ROI, avec des garde-fous rares pour un projet de cette taille (provenance obligatoire, zéro frais candidat, aucun envoi non contrôlé).

**Manque principal :** la preuve par le réel. Aucune fonction ne remplace les 45 minutes quotidiennes du pilote : c'est là que se joue l'atteinte des objectifs.

**Recommandation synthétique :** *exécuter d'abord le pilote avec l'outil existant (Priorité 1), instrumenter les canaux (Priorité 2), puis piloter par la conversion et les MAD/h (Priorité 3) — toute amélioration technique au-delà doit être justifiée par un obstacle observé sur le terrain.*
