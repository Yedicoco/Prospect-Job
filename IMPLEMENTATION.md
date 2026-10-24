# Parcours métier implémentés et limites

Cette version met en œuvre un premier ensemble transversal de l’audit. **Les 47 fonctions ne sont pas toutes terminées.** Les fonctions opérationnelles et les dépendances restantes sont séparées ci-dessous.

## Utilisation

```bash
python3 webapp.py --port 8000
```

Le serveur web/worker utilise un verrou POSIX pour empêcher deux processus d’utiliser la même base. Déploiement Linux/macOS ; un portage du verrou est nécessaire pour Windows natif.

### 1. Acquisition, file quotidienne scorée et ROI réel par source

- **Référentiel de sources A1–C (`yallah_sources.py`)** : `site_formulaire`, `whatsapp_entrant`, `gbp_entrant`, `avito_demande`, `fb_groupe_demande`, `partenaire_parrain`, `relocation_rh`, `clinique_senior`, `agence_immo`, `conciergerie`, `creche_ecole` et `liste_froide_b2b`. Les notes ordinales `intention` et `joignabilite` (1–5) sont des hypothèses initiales d’ordonnancement à confronter aux résultats réels.
- **File du jour (`Tâches et rappels` et `yallah_sources.py --file`)** : sert les **relances graduées J+3, J+7 puis J+14** avant les premiers contacts, dans la limite partagée de **15 prises de contact par jour**, triée par `intention × 3 + joignabilité × 2 + fraîcheur + niveau`. Les fiches de plus de 7 jours non revérifiées et les particuliers B2C non sollicités sans consentement (verrou Loi 09-08 art. 10) sont exclus.
- Depuis l’accueil : **Pipeline commercial → Nouvelle opportunité** ou depuis une fiche prospect : **Opportunité commerciale**.
- Choisir un client réel, un objet, une étape, un responsable, une prochaine action et une date.
- Les étapes couvrent prospect, qualification, conversation, rendez-vous, besoin confirmé, proposition, gagné et perdu. Un motif est exigé pour une perte.
- **Suivi du temps et ROI réel (`Résultats et coûts` et `yallah_sources.py --temps` / `--roi`)** : permet de noter les minutes opérateur par prospect (`1` à `600` min) et calcule par source les leads, contacts, réponses, besoins confirmés, contrats, heures passées, **MAD facturés/encaissés réels** et **MAD / heure réel** uniquement à partir des écritures réelles du grand livre (`0 MAD` tant qu’aucune facture ni encaissement réel n’est enregistré). Ce n’est ni un outil d’émission de factures légales ni une comptabilité.
- Sur une opportunité confirmée : **Créer le besoin confirmé** conserve le lien au client et à l’opportunité ; il faut une source et une date de confirmation et une confirmation explicite.

### 2. Pages SEO locales A1 et demandes entrantes

- `/services` et `/services/<slug>` (ex. `/services/femme-de-menage-californie-casablanca` ou `/services/CAS-CAL-MEN`) : **35 pages publiques Phase 1 (`quartier × besoin`)** conformes aux garde-fous éditoriaux (aucun prix, délai, garantie ni chiffre non vérifié ; mention explicite de gratuité candidat art. 480 du Code du travail), reliées au formulaire entrant (`site_formulaire` + `b2c_ref`) et à un lien WhatsApp précodé.
- `/demande` : formulaire public client (accepte aussi `?ref=CAS-CAL-MEN` pour préremplir le besoin localisé).
- `/candidature` : formulaire public affichant uniquement les besoins réels publiables ; aucune candidature ouverte si aucun besoin réel n’existe.
- Les formulaires recueillent les données minimales et l’accord de traitement de la demande, **pas une autorisation marketing**. Ils comprennent un honeypot et une limite de dix requêtes par heure et IP vue par le serveur ; derrière un proxy, compléter cette limitation en amont. Ne pas faire confiance à des en-têtes IP fournis par le client.
- **Conversations → demandes entrantes** : examiner, traiter ou rejeter. Les déclarations reçues ne créent pas automatiquement des candidats vérifiés ni des contacts autorisés.
- Une demande client peut être convertie en contact + opportunité après choix du type client et du métier/segment par l’opérateur. Une coordonnée existante est rapprochée au lieu de créer un doublon. La provenance interne `ENT-...` est conservée sans inventer d’URL publique. Le message B2C répond à une « demande », pas à une prétendue annonce.
- Pour une candidature : **Préparer le dossier candidat** préremplit les coordonnées. L’équipe doit renseigner compétences, dates, disponibilité et preuve du traitement avant validation, puis lier explicitement la candidature au besoin. Les disponibilités ne sont pas déduites du message entrant.
- Le paramètre `?source=publication-xxx` permet une attribution déclarative de la demande. Ce n’est pas un suivi publicitaire ou une preuve automatique de l’origine.

### 3. Candidats, candidatures et missions

- **Recrutement → Nouveau candidat** : métiers déclarés, ville, langues, contact, plage de disponibilité, date de vérification et accord de traitement.
- Création de candidatures sur les besoins ouverts : reçu, contacté, entretien, proposé, accepté, refusé ou retiré ; notes de suivi.
- Rapprochement explicable sur métier, ville et disponibilité ; il ne vérifie ni les compétences ni les références et ne décide pas du recrutement.
- Une affectation exige un candidat actif, une candidature acceptée, un besoin ouvert, des dates compatibles et une disponibilité reconfirmée le jour même. Une mission chevauchante est refusée.
- Suivi planifiée → en cours → terminée ou annulée, avec retours et incidents déclarés. Les incidents ne sont pas automatiquement considérés comme résolus.
- Les besoins fermés/pourvus/annulés restent stockables mais non publiables. Les références de poste sont contrôlées contre les doublons.

### 4. Conversations, callbacks et refus

- **Conversations → Noter un échange** : email, WhatsApp, téléphone ou note ; entrant/sortant ; réponse, refus ou besoin.
- Un refus est propagé aux exclusions et bloque les futures tentatives ; les autorisations sont retirées et historisées.
- Les actions manuelles existantes alimentent aussi la chronologie. Une conversation existante entraîne une revue humaine avant un nouveau contact automatique ; les liens manuels affichent une confirmation lorsque des échanges existent.
- La réception d’un message ne déclenche jamais de réponse automatique.
- **Resend** : POST `/webhooks/resend`, signature Svix avec `RESEND_WEBHOOK_SECRET`, fenêtre de cinq minutes et déduplication. États delivered/bounced/complained/failed ; rebonds/plaintes bloquent le contact.
- **Meta** : GET `/webhooks/meta` pour le challenge avec `WHATSAPP_VERIFY_TOKEN` ; POST pour les événements avec vérification HMAC SHA256 via `WHATSAPP_APP_SECRET`. États sent/delivered/read/failed et messages texte entrants pour les contacts connus. Les messages texte de numéros inconnus arrivent dans une file « à qualifier », sans création d’autorisation ni déduction client/candidat : un opérateur les oriente. Un STOP d’un numéro inconnu est conservé comme refus, sans créer de prospect.
- Les STOP explicites reconnus (dont `STOP`, `unsubscribe`, `désinscription`, `إلغاء الاشتراك`) entraînent le refus. Les formulations ambiguës sont à traiter humainement ; aucune classification IA n’est présentée comme infaillible.
- Les callbacks sont idempotents, ne rétrogradent pas une livraison connue et peuvent être rapprochés si le callback précède la réponse HTTP du fournisseur.
- **Les réponses email entrantes ne sont pas ingérées.** Elles doivent être enregistrées manuellement. Les pièces jointes et messages WhatsApp non textuels ne sont pas intégrés.
- Aucun de ces connecteurs n’a été validé en réel dans le bac à sable : signatures et formats sont testés avec événements simulés. Configurer les URL, secrets et abonnements aux événements chez les fournisseurs, puis effectuer un pilote autorisé.

### 5. Sécurité, traçabilité et exploitation

- Mode de démonstration/de confiance : comportement local existant, sans authentification si aucun compte/mot de passe n’est configuré. Ne pas l’exposer publiquement avec des données réelles.
- Créer des comptes locaux (mots de passe PBKDF2-SHA256, sel individuel, 600 000 itérations) :

```bash
python3 manage.py user-add mon-admin --role admin
python3 manage.py user-add commercial-1 --role commercial
python3 manage.py user-add recruteur-1 --role recrutement
python3 manage.py user-add lecteur-1 --role lecture
```

- Les mots de passe sont saisis par invite masquée, jamais en argument. La même commande remplace un compte existant pour changer son mot de passe/rôle. L’authentification HTTP Basic impose HTTPS en production. Pas de SSO, MFA, sessions navigateur, récupération autonome ou limitation de tentatives intégrés ; les protections réseau/rate limits doivent être ajoutées au proxy.
- `YALLAH_ENV=production` refuse le démarrage sans administrateur fort et sans `YALLAH_PUBLIC_URL` HTTPS. Cette vérification de configuration ne prouve pas la terminaison TLS réelle : configurer le proxy.
- Les écritures de campagne, imports, sauvegardes et arrêt global sont administrateur uniquement. Commercial : CRM et échanges ; recrutement : candidats, candidatures et missions ; lecture : pas d’écriture. Les dossiers candidats/candidatures sont masqués dans la réponse métier pour les rôles commercial/lecture. C’est un contrôle mono-équipe, pas une isolation multi-entreprise.
- Le mot de passe de secours `YALLAH_ADMIN_PASSWORD`, s’il est conservé, reste un accès administrateur. Les campagnes réelles gardent actuellement leur contrôle sur cette variable : un administrateur SQLite seul ne remplace pas encore ce verrou de configuration.
- Journal d’audit avec auteur pour les opérations métier, changements de campagne, autorisations et vérifications. La preuve précédente d’autorisation est conservée. Les dates et URL sont validées côté API ; la date initiale de collecte est conservée lors d’une revérification.
- **Supervision** : dernière exécution réussie, diagnostic expurgé, sauvegarde, journal d’audit. Une erreur conservée produit un avertissement dans l’interface ; pas d’alerte externe.
- **Arrêt global** : suspend les campagnes actives et bloque leur activation. Le lever ne les relance pas ; une réactivation explicite par campagne reste nécessaire. Un appel déjà en vol ne peut pas être rappelé.
- Horloge des plafonds d’envoi en `Africa/Casablanca` ; événements métier/audit en UTC. Les anciens horodatages naïfs ne sont pas automatiquement réinterprétés en cas de migration historique.
- Sauvegardes automatiques au premier contrôle puis quotidiennement en UTC, contrôle horaire tant que le serveur fonctionne ; désactivation possible par `YALLAH_AUTO_BACKUP=0`. Sauvegarde manuelle dans **Supervision** ou via `python3 manage.py backup`.
- Les sauvegardes SQLite cohérentes sont placées dans `data/backups/`, permissions 0600, avec contrôle d’intégrité. Elles ne sont ni chiffrées ni externalisées automatiquement ; aucun effacement automatique n’est effectué sans politique validée.
- Restauration, serveur arrêté :

```bash
python3 manage.py restore data/backups/nom-de-sauvegarde.sqlite3 --confirm
python3 manage.py check
```

Le verrou empêche la restauration si le nouveau serveur utilise la base. Le test de restauration effectue un aller-retour réel de la commande sur une base temporaire. Toujours conserver une sauvegarde avant écrasement.

### 6. Import et données

- **Supervision → Import JSON / CSV** : aperçu des erreurs et doublons (JSON ou CSV B2B/B2C), puis import atomique de 1 à 200 prospects sourcés publiquement. Aucune autorisation n’est importée. Les demandes privées sont traitées via leur file dédiée, pas via un faux lien source.
- **Conversations → Importer un email reçu** (`email_ingest` / `python3 manage.py email-ingest`) : déduplication par `Message-ID`, détection des STOP/refus hors citations `>`, rattachement aux prospects connus, routage des références d’annonces ouvertes vers `candidature`, et mise en file `a_qualifier` des expéditeurs inconnus.
- **Tâches et rappels → Relances manuelles éligibles (J+7)** : liste des contacts ayant reçu exactement 1 envoi sortant depuis au moins 7 jours sans réponse ni refus (aucun envoi automatique).
- **Synchronisation vers les scripts CLI** : `python3 manage.py export-json --dir ./export` exporte les fiches publiques et fusionne les refus SQLite (`suppressions`) dans `meta.refus`.
- Les relations opérationnelles utilisent les identifiants SQLite et clés étrangères ; migrations idempotentes enregistrées, index pour les recherches courantes.
- Les vues métier sont limitées aux 1 000 derniers éléments par catégorie, tandis que les indicateurs de volume/finance sont agrégés en base. Une pagination complète reste à développer.

## Couverture de l’audit : ce qui reste à développer

| Groupe | État dans cette livraison |
|---|---|
| A1 acquisition entrante | Formulaires, traitement et conversion opérationnels. |
| A2 import | JSON et CSV contrôlés avec aperçu et import atomique. |
| A3/A4 contacts multiples et fusion | Détection/rapprochement de coordonnées ; pas de modèle multi-interlocuteurs ni de fusion complète. |
| A5/A6/A8 provenance, qualification, autorisations | Historique de vérification/autorisation et pipeline ; scope/expiration structurés, capacité de service et pièces de preuve restent à compléter. |
| A7 surveillance de sites | Non implémentée ; aucun scraping ajouté. |
| B1/B3/B5/B7 vente | Pipeline, besoin lié, propositions versionnées et motif de perte opérationnels. |
| B2/B4/B6 suivi | Tâches/rappels, relances éligibles J+7, découverte via besoin/notes, chronologie et import d’emails reçus ; synchronisation IMAP automatique et calendrier externe restent à compléter. |
| C1/C9/C11 callbacks, arrêt, refus | Implémentés, tests simulés ; recette fournisseur réelle indispensable. |
| C2/C3/C8 échanges et incidents | WhatsApp texte, import d’email entrant dédupliqué et refus, historique commun, rapprochement callback/HTTP ; pas de connecteur IMAP continu ni de recherche automatique d’un timeout chez le fournisseur. |
| C4/C5/C6/C7/C10 optimisation d’envoi | Fuseau, garde-fous et indicateur de relance manuelle J+7 existants ; créneaux horaires, bibliothèque de modèles, objets email éditables et relances automatiques non implémentés. |
| D1/D2/D3/D4/D5/D7/D8 recrutement | Candidatures, dossiers minimisés, étapes, suggestions, disponibilités, affectations et retours opérationnels. Pas de contrôle réel des compétences ni de gestion juridique de contrats. |
| D6 entretiens et documents | Étape entretien et notes ; pas de calendrier ni de stockage de pièces sensibles. |
| E1/E2 acquisition B2C | Formulaire et source déclarée ; pages locales et QR codes non implémentés. |
| E3/E4/E5 contenu | Calendrier éditorial, IA web et publication sociale non implémentés ; le CLI B2C reste disponible. |
| F1/F2 pilotage | Indicateurs actuels et écritures déclarées ; pas de cohortes historiques, coût du temps ou comptabilité complète. |
| F3 comptes | Comptes/roles mono-équipe ; protections de proxy et recette de déploiement nécessaires. |
| F4 droits et conservation | Pas de moteur de purge, export de dossier individuel ou procédures juridiques automatisées. À définir avec la politique applicable avant collecte réelle importante. |
| F5/F6 exploitation | Sauvegarde/restauration testées, santé et audit ; chiffrement, externalisation et alertes externes à configurer. |
| F7/F8 architecture/tests | Migrations, relations, tests Python/HTTP/DOM et workflow CI ajoutés ; les JSON initiaux subsistent et les tests en navigateur réel/charge restent à faire. |

## Validation

```bash
python3 -m unittest discover -s tests -v
npm ci
npm test
node --check web/app.js
node --check web/operations.js
node --check web/public.js
```

La CI est décrite dans `.github/workflows/tests.yml` ; sa présence n’est pas une preuve qu’un run GitHub a déjà réussi. Aucun message commercial réel n’a été envoyé par ces tests.
