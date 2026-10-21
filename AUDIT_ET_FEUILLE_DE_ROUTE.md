# Audit fonctionnel et technique — Prospect-Job / Yallah Services

Date : 21 octobre 2026. Périmètre : code et documentation de la branche de travail, interface et tests présents. Cet audit n’est ni un audit juridique, ni un test d’intrusion, ni une vérification des coordonnées sur les sites externes.

## 1. Conclusion exécutive

Le projet dispose d’une base opérationnelle pour préparer la prospection et simuler des campagnes. Il ne constitue pas encore un CRM de vente et de recrutement complet. Son principal manque n’est pas le nombre de boutons ou la cadence d’envoi : c’est l’absence d’un circuit structuré qui relie contact, conversation, besoin confirmé, candidature, mission, satisfaction et revenu.

**Objectif recommandé : obtenir des besoins réels et convertir ceux-ci en prestations réussies et rentables, avec un traitement licite et maîtrisé des contacts.** Le volume de messages est un indicateur d’activité, pas une mesure de succès.

Aucune fonction ne garantit des clients ou des placements. On peut rendre les opérations plus fiables et mesurer les résultats ; l’efficacité commerciale devra être démontrée sur un pilote.

## 2. État constaté

### Inventaire des fichiers sources, pas des résultats commerciaux

- `prospects_b2b.json` : 48 fiches, dont 18 de niveau A, 29 de niveau B, 1 de niveau C. Le niveau B reste à reconfirmer ; le niveau C ne dispose pas de contact direct.
- `prospects_b2c.json` : aucune fiche réelle, une démonstration.
- `besoins_emploi.json` : aucun besoin réel, une démonstration.
- Ces chiffres décrivent les JSON versionnés, pas nécessairement la base SQLite locale après exploitation.
- 122 tests Python et 5 tests DOM passent lors de l’audit. Les tests DOM ne remplacent pas un navigateur réel, et les tests fournisseurs simulés ne prouvent pas la délivrabilité.

### Déjà disponible

- Interface française, accès rapides, filtres, création et modification des fiches.
- Messages français, darija et arabe, garde-fous et export CSV.
- Sources datées, vérification déclarative quotidienne, exclusions, détection de doublons.
- Campagnes email / WhatsApp Business simulées par défaut.
- Autorisations par canal et coordonnée, activation explicite, pause et annulation.
- File persistante, plafond de 15 tentatives/jour, intervalle de 60 secondes.
- Désinscription signée et refus partagés, absence de relance automatique après issue incertaine.
- Préparation d’annonces d’emploi et liens entrants B2C.

### Non démontré à ce stade

Envois réels fonctionnels dans l’environnement final, livraison effective, lecture, réponse, rendez-vous, acquisition d’un client, placement et rentabilité. L’audit ne transforme pas ces éléments en résultats acquis.

## 3. Points techniques à traiter en priorité

| Priorité | Constat vérifié dans le code | Action recommandée |
|---|---|---|
| P0 | `webapp.py:Handler.authorized()` autorise l’accès si le mot de passe est absent. | Ajouter un mode de déploiement explicite ; refuser le démarrage en production sans authentification et contrôle TLS au proxy. Garder un mode local de démonstration clairement distinct. |
| P0 | `campaigns.py:runtime_errors()` vérifie surtout des variables, pas les droits effectifs chez les fournisseurs. | Diagnostic fournisseur contrôlé, compte de test et envoi pilote sur une coordonnée autorisée ; distinguer « renseigné », « authentifié », « modèle validé » et « opérationnel ». |
| P0 | Pas de réception des réponses ni de webhooks de livraison/plaintes/rebonds. | Ajouter des événements fournisseurs signés, dédupliqués et associés aux conversations. Arrêter immédiatement les prochains contacts après refus ou plainte. |
| P0 | Les messages manuels et les tentatives automatiques n’utilisent pas un historique de pression commerciale commun. | Construire un registre de contact unifié par personne/coordonnée, consulté par tous les canaux et par l’envoi manuel. |
| P0 | `campaigns.py:worker()` masque toutes les exceptions par `except Exception: pass`. | Journaliser un code d’erreur expurgé, conserver un état de santé, notifier les incidents et afficher la dernière exécution réussie. Ne pas exposer les secrets. |
| P0 | La date de confirmation n’est pas obligatoire dans `yallah_emploi.py:valider_besoin()` : elle est contrôlée seulement si renseignée. | Exiger une vraie date de confirmation, non future, pour tout besoin réel. La présence du champ dans le formulaire ne suffit pas à sécuriser l’API. |
| P0 | Validation de plusieurs dates par expression régulière et d’URL par préfixe `http`. | Utiliser des dates calendaires strictes et des URL HTTP(S) analysées ; schémas typés et erreurs métier explicites pour toutes les API. |
| P1 | `campaigns.py:transport()` dépend d’un seul modèle WhatsApp configuré, avec une variable contenant le texte complet. | Gérer des modèles approuvés par usage/langue, mapper leurs paramètres structurés et vérifier la compatibilité de la campagne. Le format actuel doit être validé chez Meta avant usage réel. |
| P1 | `permissions` écrase la preuve précédente ; `legal_proof` est un texte déclaratif. | Versionner les autorisations, leur portée, leur preuve, leur révocation et l’identité du validateur. Aucun champ texte ne vaut validation juridique. |
| P1 | `state()` recharge toutes les fiches ; `eligibility()` reconstruit cet état pour chaque destinataire. | Évaluer une fiche sans reconstruire toute l’application, ajouter pagination, index et tests de charge. Le coût d’une simulation augmente inutilement avec la base. |
| P1 | Fiches stockées comme JSON dans `records`, références d’affichage dérivées de l’ordre des listes. | Conserver les identifiants SQLite existants, introduire des références métier stables et des relations structurées ; imposer l’unicité des références de poste. |
| P1 | La validation d’un besoin impose `statut=ouvert` pour les fiches réelles, alors que le formulaire propose aussi une fermeture. | Séparer validation de stockage et autorisation de publication : un poste fermé doit rester enregistrable, mais non publiable. |
| P1 | Les statuts de campagne ne sont pas encadrés par une table stricte de transitions. | Autoriser uniquement les transitions prévues, journaliser les changements, traiter explicitement les états terminaux et les appels déjà en vol. |
| P1 | SQLite web et JSON CLI constituent deux sources distinctes sans synchronisation. | Choisir SQLite comme référence opérationnelle du MVP, proposer import/export validé ; faire évoluer les CLI pour utiliser les mêmes services. Ne pas synchroniser implicitement deux bases concurrentes. |
| P1 | Worker dans le serveur HTTP ; états en cours rendus incertains au redémarrage. | Garder le principe anti-doublon, ajouter supervision et rapprochement fournisseur ; séparer processus web et worker lorsque l’exploitation le justifie. |

Le serveur HTTP standard et le compte administrateur unique sont adaptés à une première version privée, pas à un produit multiutilisateur exposé sans protections supplémentaires. SQLite peut rester pertinent pour un petit déploiement mono-équipe ; une migration PostgreSQL n’est pas une obligation immédiate.

## 4. Backlog fonctionnel recommandé

P0 : nécessaire avant une exploitation réelle autonome. P1 : nécessaire au parcours commercial/recrutement complet. P2 : optimisation après obtention de données fiables.

### A. Acquisition et qualité des contacts

| ID | Fonction | Priorité | Critère de réussite |
|---|---|---|---|
| A1 | Formulaire public de demande client B2B/B2C | P1 | Une demande crée une fiche et une opportunité, avec source, objet, canal demandé et horodatage. |
| A2 | Import CSV/JSON avec aperçu et validation | P1 | L’opérateur voit les erreurs et doublons avant import ; aucune autorisation n’est déduite de l’import. |
| A3 | Plusieurs interlocuteurs par établissement | P1 | Direction, RH et achats sont distingués, avec rôle et coordonnées par contact ; pas trois prospects artificiels pour la même entreprise. |
| A4 | Normalisation et fusion de doublons assistée | P1 | Numéros internationaux, emails et établissements identiques sont rapprochés ; historique et refus survivent à la fusion. |
| A5 | Provenance et fraîcheur des informations | P0 | Chaque changement garde la source, la date, la personne et le résultat de vérification. Une collecte d’origine n’est pas écrasée par une revérification. |
| A6 | Qualification métier | P1 | Besoin supposé et besoin déclaré restent distincts ; pertinence, décideur identifié, localisation et capacité de service sont renseignés. |
| A7 | Contrôle de sources assisté | P2 | Détection de pages devenues indisponibles/changements, avec validation humaine ; pas de collecte derrière authentification ou contournement. Toute consultation serveur d’URL exige une protection SSRF. |
| A8 | Gestion des autorisations entrantes | P0 | Preuve du canal, finalité, date, portée et retrait consultables ; la publication d’un numéro ne constitue pas une autorisation automatique. |

### B. CRM de vente et suivi quotidien

| ID | Fonction | Priorité | Critère de réussite |
|---|---|---|---|
| B1 | Pipeline commercial structuré | P1 | Étapes prospect, qualifié, conversation, rendez-vous, besoin confirmé, proposition, gagné/perdu, avec dates et motif de perte. |
| B2 | Tâches, rappels et agenda | P1 | Chaque opportunité active a un responsable et une prochaine action datée ; vue des retards. |
| B3 | Création d’un besoin depuis une opportunité | P1 | Un bouton crée un besoin lié au client ; validation explicite avant publication ; aucun besoin inventé à partir du segment. |
| B4 | Fiche de découverte du besoin | P1 | Métier, lieu, effectif, tâches, calendrier, horaires, rémunération sourcée, conditions, responsable et confirmation structurés. |
| B5 | Propositions commerciales et versions | P1 | Offre rattachée au besoin, validée par une personne habilitée ; conditions et tarifs réels, jamais générés arbitrairement. |
| B6 | Chronologie omnicanale | P0 | Emails, WhatsApp, appels déclarés et notes figurent dans la même conversation. |
| B7 | Raisons de perte et retour d’expérience | P1 | Analyse des refus, absence de besoin, délai, prix, capacité insuffisante et autres motifs contrôlés. |

### C. Messages et campagnes fiables

| ID | Fonction | Priorité | Critère de réussite |
|---|---|---|---|
| C1 | Webhooks signés et idempotents | P0 | Même événement reçu deux fois sans doublon ; signature invalide rejetée ; livré/rejeté/échec distingués. |
| C2 | Boîte de réception et refus entrants | P0 | Un refus bloque toute nouvelle tentative concernée ; classification assistée avec traitement humain des cas ambigus. |
| C3 | Règles globales de pression de contact | P0 | Une même personne n’est pas sollicitée successivement par email, WhatsApp et envoi manuel sans règle commune. |
| C4 | Planification selon `Africa/Casablanca` | P1 | Créneaux configurables, calendrier réel, dates UTC en stockage ; pas de décalage silencieux lié au fuseau du serveur. |
| C5 | Bibliothèque de modèles validés | P1 | Version, langue, segment, finalité et validateur visibles ; un changement de texte impose une nouvelle validation. |
| C6 | Objets email et variantes contextualisés | P1 | Variables limitées aux faits sourcés, aperçu exact et destinataire de test ; pas de fausse personnalisation. |
| C7 | Budget et réputation d’envoi | P1 | Limites par campagne/canal, suivi des rebonds/plaintes ; suspension automatique sur seuils définis avec le fournisseur. |
| C8 | Gestion d’incidents et rapprochement | P0 | Toute tentative incertaine est recherchée chez le fournisseur avant décision ; aucune répétition aveugle après timeout. |
| C9 | Arrêt d’urgence global | P0 | Bouton administrateur suspendant les nouvelles réservations pour tous les canaux, avec avertissement sur les appels déjà lancés. |
| C10 | Relances encadrées | P2 | Une relance seulement si autorisée, sans réponse ni refus, après délai validé et avec plafond global ; pas avant réception fiable des réponses. |
| C11 | Désinscription simple et auditée | P0 | Retrait propagé à toutes les files et aux doublons, état cohérent même après import ; format adapté aux exigences fournisseurs applicables. |

### D. Recrutement et réalisation de la prestation

| ID | Fonction | Priorité | Critère de réussite |
|---|---|---|---|
| D1 | Formulaire de candidature rattaché à une annonce | P1 | Candidature liée à une référence réelle, information sur le traitement et absence de frais candidats. |
| D2 | Dossier candidat minimisé | P1 | Compétences déclarées, langues, disponibilités, mobilité et expérience utile ; données sensibles évitées et accès restreint. |
| D3 | Pipeline de candidature | P1 | Reçu, contacté, entretien, proposé, accepté, placé, clos avec motif ; pas de candidat utilisé comme prospect commercial. |
| D4 | Rapprochement besoin/candidat explicable | P1 | Correspondance sur critères professionnels : compétences, horaires, zone et disponibilité ; décision humaine, sans discrimination. |
| D5 | Disponibilité et réservation | P1 | Pas de double affectation à des missions incompatibles ; alerte si la disponibilité n’a pas été reconfirmée. |
| D6 | Entretiens et documents contrôlés | P1 | Rendez-vous, comptes rendus et justificatifs nécessaires ; une vérification n’est affichée que si elle a réellement été effectuée. |
| D7 | Missions et affectations | P1 | Accord documenté, début/fin, parties concernées, statut et responsable ; rappel avant démarrage. |
| D8 | Qualité après placement | P1 | Retours client et intervenant, incidents, résolution, fin de mission et éventuel nouveau besoin ; aucune garantie de remplacement inventée. |

### E. Acquisition B2C et visibilité

| ID | Fonction | Priorité | Critère de réussite |
|---|---|---|---|
| E1 | Pages de service locales avec formulaire | P1 | Demandes entrantes par ville/besoin et consentements adaptés, sans promesses commerciales non prouvées. |
| E2 | Liens et QR codes attribués à une publication | P1 | Chaque demande est associée à sa source, campagne et référence ; pas seulement au quartier. |
| E3 | Calendrier éditorial et validation | P2 | Brouillon, vérification, validation, publication déclarée ; l’IA reste une aide à la rédaction. |
| E4 | Génération IA dans l’interface | P2 | Coût et limites visibles, modèle configurable et testé, garde-fous, relecture ; aucune invention de prix, profils ou disponibilité. |
| E5 | Publication via canaux officiels | P2 | Autorisations de compte et retour fournisseur contrôlés ; ne pas présenter une publication programmée comme réellement publiée. |

### F. Pilotage, finances et gouvernance

| ID | Fonction | Priorité | Critère de réussite |
|---|---|---|---|
| F1 | Tableau de conversion par cohorte | P1 | Prospects → conversations → besoins confirmés → missions, avec dénominateurs distincts et dates. |
| F2 | Coûts, chiffre d’affaires et marge | P1 | Dépenses fournisseurs, temps commercial et prestations réelles ; revenu facturé distingué de l’encaissé, frais imputés au bon acteur. |
| F3 | Comptes et rôles | P0 | Administrateur, commercial et recrutement avec accès appropriés ; secrets jamais exposés, comptes individuels et journal des validations. |
| F4 | Conservation, droits et pièces | P0 | Politique validée, export rectification/retrait, purge et archivage maîtrisés ; conservation minimale des refus à cadrer juridiquement. |
| F5 | Sauvegarde et restauration | P0 | Sauvegarde automatique protégée ; restauration testée avec refus, campagnes et signatures conservés. |
| F6 | Supervision et audit | P0 | Santé web/worker, erreurs expurgées, alertes, dernière tentative, opérations sensibles et auteur. |
| F7 | Migrations et données structurées | P1 | Versions de schéma, contraintes, relations et identifiants stables ; migration testée depuis la base existante. |
| F8 | Tests continus et navigateur réel | P0 | CI Python/JS, tests de parcours, mobile/clavier, migrations, webhooks rejoués, échec fournisseur, redémarrage et restauration. |

## 5. Modèle de données cible

Évolution conseillée, sans supprimer les données existantes :

- `organizations`, `contacts`, `contact_points` : établissements et personnes distincts.
- `sources`, `verifications` : provenance et vérifications historisées.
- `authorizations`, `authorization_events`, `suppressions` : portée, preuve et retraits.
- `opportunities`, `tasks`, `appointments`, `commercial_proposals` : vente.
- `conversations`, `messages`, `provider_events`, `campaigns`, `deliveries` : échanges et automatisation.
- `recruitment_needs`, `candidates`, `applications`, `interviews`, `assignments` : recrutement et missions.
- `invoices`, `payments`, `costs` : uniquement si leur gestion entre dans le périmètre métier validé.
- `users`, `roles`, `audit_events` : gouvernance et traçabilité.

Ne pas tout créer en une seule migration. Commencer par les relations client → opportunité → besoin et la chronologie de contact. Utiliser des migrations réversibles et des sauvegardes.

## 6. Mesurer l’efficacité réelle

| Indicateur | Définition proposée |
|---|---|
| Qualité des fiches | Fiches sourcées, à jour et sans anomalie / fiches évaluées. |
| Contacts autorisés | Coordonnées disposant d’une autorisation active / coordonnées ciblées, par canal. |
| Livraison | Messages effectivement livrés / messages acceptés, seulement si l’événement fournisseur existe. |
| Réponse utile | Contacts uniques ayant exprimé un besoin ou accepté un échange / contacts uniques sollicités sur la cohorte. |
| Conversion besoin | Opportunités avec besoin confirmé / opportunités qualifiées de la cohorte. |
| Couverture recrutement | Besoins pourvus / besoins ouverts de la cohorte, avec distinction des annulations. |
| Délai opérationnel | Temps entre confirmation du besoin et affectation acceptée ; médiane et valeurs extrêmes utiles. |
| Qualité de service | Missions terminées sans incident non résolu ; satisfaction client et intervenant avec taille de l’échantillon. |
| Rentabilité | Marge de contribution et coût d’acquisition par client ayant réellement acheté. |
| Protection des contacts | Refus/plaintes, temps de propagation d’un retrait, contacts évités grâce aux exclusions. |

Ne pas utiliser les ouvertures email comme mesure principale : elles peuvent être peu fiables. Ne pas afficher un taux de livraison si l’on ne dispose que de l’acceptation API. Ne fixer aucun objectif de conversion arbitraire avant le pilote.

## 7. Ordre d’exécution recommandé

### Lot 1 — Sécurité et vérité des données

Validation API stricte, dates, statut de fermeture des besoins, accès production, sauvegarde/restauration, journal et santé worker, tests CI. Critère de sortie : aucune donnée métier invalide acceptée dans les cas couverts, restauration démontrée, incident visible.

### Lot 2 — Boucle commerciale minimale

Pipeline, tâches, fiche de découverte, relation client/besoin et historique omnicanal commun. Critère de sortie : toute opportunité ouverte possède un responsable, une prochaine action et une issue documentée.

### Lot 3 — Canaux réellement maîtrisés

Configuration testée en environnement approprié, modèles WhatsApp validés, webhooks signés, réponses/refus, pression de contact globale, arrêt d’urgence et créneaux. Critère de sortie : un message test autorisé est accepté puis rapproché d’un état fournisseur ; un refus bloque la file et ses doublons.

### Lot 4 — Recrutement et suivi de mission

Candidatures, candidats, disponibilités, rapprochement explicable, affectation et suivi qualité. Critère de sortie : un parcours de test complet relie demande confirmée, candidature et mission sans perte de traçabilité.

### Lot 5 — Acquisition et optimisation

Formulaires entrants, attribution B2C, contenu, indicateurs de conversion et coûts, puis variantes et relances autorisées. Critère de sortie : les décisions de ciblage reposent sur des résultats observés plutôt que sur le volume d’envoi.

Les durées et coûts de ces lots ne sont pas estimables sérieusement sans connaître l’équipe, l’hébergement, les comptes fournisseurs et les contraintes légales. Il faut choisir un périmètre de pilote et chiffrer chaque lot ensuite.

## 8. Ce qu’il ne faut pas prioriser

- Augmenter immédiatement le nombre d’envois.
- Acheter des listes ou extraire des numéros privés.
- Contourner les restrictions des plateformes ou automatiser un compte WhatsApp personnel.
- Déclarer automatiquement des contacts consentants ou des candidats vérifiés.
- Ajouter un classement IA des personnes sans critères professionnels explicables et contrôle humain.
- Multiplier les villes alors que la capacité de servir et les résultats locaux ne sont pas mesurés.
- Refaire toute l’architecture avant de fermer la boucle commerciale minimale.

## 9. Décisions métier à obtenir avant développement massif

1. Qui paie quelle prestation, et dans quel cadre contractuel ? Conserver la politique actuelle sans frais candidats tant qu’un changement n’a pas été valablement établi.
2. Quel territoire, segment et métier pour le pilote ? Choisir selon la capacité réelle à servir.
3. Qui prospecte, valide une campagne, recrute et suit la mission ?
4. Quelles demandes et preuves de contact existent réellement ?
5. Quels comptes fournisseurs et quel environnement de déploiement sont disponibles ?
6. Quelles données doivent être conservées, pour combien de temps et avec quels accès ?
7. Quels événements définiront un client acquis, un besoin confirmé, une mission réussie et un revenu ?

**Recommandation finale : investir d’abord dans le CRM de conversion, la réception des réponses et le suivi des besoins/candidats. L’automatisation doit accélérer un processus maîtrisé, pas amplifier une liste non qualifiée.**
