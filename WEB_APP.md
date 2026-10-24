# Application web et campagnes Yallah Services

> **Évolution métier :** voir [IMPLEMENTATION.md](IMPLEMENTATION.md) pour le CRM, les candidatures, les missions, les comptes, sauvegardes et webhooks ajoutés. Cette page décrit principalement le moteur de campagnes. Les mises à jour ci-dessous remplacent ses anciennes limites.

## Démarrage

Python 3.11+ recommandé, aucune dépendance externe :

```bash
python3 webapp.py --port 8000
```

Ouvrir `http://localhost:8000`, ou l’aperçu Arena. Le serveur écoute sur `0.0.0.0`.

**Par défaut, aucune campagne n’envoie quoi que ce soit.** Les scripts CLI historiques restent manuels ; l’automatisation est une nouvelle fonction web distincte.

## Fonctions de l’interface

- Tableau de bord, recherche et filtres, création/modification des prospects B2B/B2C.
- Vérification manuelle des sources. Le bouton enregistre votre déclaration et renouvelle les dates ; il ne consulte pas les sites.
- Messages français, darija et arabe, copie et liens de contact manuel, export CSV.
- Historique des envois/réponses déclarés, notes, refus partagés B2B/B2C.
- Besoins d’emploi confirmés, aperçu des annonces et liens de candidature. Les candidats ne peuvent pas être ciblés par une campagne commerciale.
- Matrice B2C de liens de demande entrants. La génération IA reste disponible par le CLI, pas dans l’interface.
- **Campagnes email / WhatsApp Business** : sélection explicite de prospects, simulation et raisons de blocage, activation réelle, pause, reprise et annulation.

## Première campagne : liste à qualifier

1. Dans **Campagnes auto**, préparer une campagne avec un nom, un canal, un signataire, une langue et une sélection de prospects.
2. Lancer la simulation. Elle ne fait **aucun appel fournisseur**. Chaque contact est « Simulation validée » ou « Bloqué » avec les motifs.
3. Dans **Prospects → Ouvrir**, consulter la source, vérifier réellement le contact puis enregistrer cette vérification.
4. Si vous disposez effectivement d’une autorisation adaptée à ce canal et au cadre applicable, la documenter dans **Qualification des campagnes automatiques** : référence de la preuve, date et portée. Ne pas recopier de données personnelles inutiles dans les notes.
5. Recréer une simulation pour voir l’état actualisé. Une coordonnée publique seule n’est pas traitée comme une autorisation.
6. L’activation réelle n’est possible qu’après configuration du serveur et documentation d’une validation du cadre applicable pour la campagne. Cette saisie reste une déclaration de l’opérateur, pas un avis juridique automatisé.

Aucun consentement n’a été attribué aux fiches du dépôt. Les exemples sont exclus. Chaque autorisation est liée au canal **et à la coordonnée exacte** : modifier l’email ou le numéro impose une nouvelle autorisation. Un refus empêche la réactivation depuis l’interface.

## Configuration des fournisseurs — côté serveur uniquement

Voir `.env.example` (valeurs vides, aucun secret). L’application lit les variables d’environnement et **ne charge pas `.env` automatiquement**. Injecter les secrets via le gestionnaire de secrets du serveur, jamais via le navigateur, Git ou une conversation.

Variables communes pour autoriser des envois réels :

| Variable | Rôle |
|---|---|
| `YALLAH_ENABLE_LIVE=1` | Autorisation explicite de l’envoi réel côté serveur |
| `YALLAH_ADMIN_PASSWORD` | Mot de passe administrateur, 16 caractères minimum pour les campagnes réelles |
| `YALLAH_PUBLIC_URL` | URL publique HTTPS de l’application, sans query/fragment, utilisée pour les désinscriptions |

Dès que le mot de passe est défini, l’interface et les API demandent une authentification HTTP Basic : utilisateur **`admin`**, mot de passe défini côté serveur. HTTPS est indispensable en production. Le lien public de désinscription reste accessible sans compte.

### Email — Resend

- `RESEND_API_KEY` : clé serveur Resend disposant du droit d’envoi.
- `YALLAH_FROM_EMAIL` : expéditeur sur un domaine validé chez Resend, par exemple `Yallah <contact@votre-domaine>`.

L’adaptateur appelle `https://api.resend.com/emails`, en texte brut, avec lien de désinscription et clé d’idempotence par tentative. Le domaine, la délivrabilité, les quotas et les obligations applicables restent à configurer chez le fournisseur.

### WhatsApp Business — Meta Cloud API

- `WHATSAPP_ACCESS_TOKEN` : jeton serveur pour le compte WhatsApp Business.
- `WHATSAPP_PHONE_NUMBER_ID` : identifiant numérique du numéro expéditeur.
- `WHATSAPP_GRAPH_VERSION` : version Graph prise en charge par votre compte (défaut `v23.0`, à vérifier chez Meta).
- `WHATSAPP_TEMPLATE_NAME` : nom d’un modèle marketing approuvé.
- `WHATSAPP_TEMPLATE_LANGUAGE` : code exact de la traduction approuvée (`fr`, etc.). Cette valeur doit correspondre à la langue choisie pour le message et au modèle approuvé ; l’opérateur est responsable de cette correspondance.
- `WHATSAPP_TEMPLATE_REVIEWED=1` : confirmation explicite après vérification du contrat ci-dessous.

**Contrat de modèle de cette première intégration** : un modèle sans média ni en-tête paramétré, dont le corps attend **exactement une variable texte**. L’application lui transmet le message généré suivi du lien de désinscription, sur une ligne. Le modèle doit être réellement approuvé par Meta pour cet usage et le contenu doit respecter ses règles. La simple présence d’un nom dans les variables ne vérifie ni son approbation ni sa compatibilité. Si Meta refuse ce format ou exige un modèle différent, adapter l’adaptateur et son test avant activation. Aucun envoi libre hors fenêtre via un compte WhatsApp personnel n’est réalisé.

Les frais, limites et validations des deux fournisseurs sont externes au projet. Aucun abonnement fournisseur n’est créé automatiquement.

## File automatique et limites

Le serveur démarre un worker intégré qui examine la file toutes les cinq secondes. Il fonctionne **uniquement tant que le processus reste en marche**. La file et l’historique sont persistants. Les campagnes réelles déjà activées reprennent après redémarrage, sous réserve des contrôles. Aucune planification à une date future n’est proposée dans cette version.

Avant chaque tentative :

- message qualifié par les moteurs existants, fiche à jour du jour, source valide et non périmée ;
- autorisation active pour la coordonnée et le canal ;
- contrôle des refus et des doublons ;
- configuration réelle toujours présente et validation de campagne conservée ;
- contenu et destination identiques à ceux de la file activée.

Si un contrôle échoue, le contact est bloqué. Requalifier puis préparer une nouvelle simulation. Les paramètres d’une campagne ne sont pas modifiés après création. Pour changer de canal ou de texte, créer une nouvelle campagne.

**15 tentatives réelles maximum par jour au total**, tous canaux et campagnes confondus, et **60 secondes minimum** entre deux tentatives. Le jour est celui du fuseau `Africa/Casablanca`. Les tentatives échouées/incertaines comptent aussi. Une coordonnée ayant déjà fait l’objet d’une tentative automatique n’est pas ressollicitée automatiquement, même depuis une nouvelle campagne. Les relances commerciales répétées ne sont pas implémentées.

Le suivi manuel est maintenant intégré à la chronologie : une conversation enregistrée impose une revue humaine avant un contact automatique. Le plafond automatique ne compte toujours pas les contacts envoyés hors du worker.

Une pause ou annulation empêche les prochaines réservations ; **elle ne peut pas retirer un appel déjà en cours chez le fournisseur**. Annuler est définitif. Reprendre exige une nouvelle confirmation et revalidation.

## Désinscription et statuts

Un lien signé par destinataire est ajouté au départ. Un GET affiche une confirmation sans modifier les données (protection contre les scanners de liens) ; le POST confirme la désinscription. Les coordonnées connues du prospect sont inscrites aux refus pour les deux canaux et les autorisations sont retirées. Le secret de signature est conservé dans la base ; les URL de désinscription ne sont pas journalisées par le serveur applicatif. Configurer également le proxy pour ne pas les enregistrer.

Une réponse par email ou WhatsApp demandant l’arrêt doit être enregistrée manuellement via **Ne plus contacter**. Les demandes d’arrêt reçues par email restent à enregistrer manuellement ; les STOP WhatsApp explicites reçus par le webhook sont traités automatiquement.

| État | Sens |
|---|---|
| Simulation validée | Qualification réussie, aucun appel réseau |
| Bloqué | Conditions manquantes, aucun envoi |
| En attente | File réelle activée, revalidation avant départ |
| Tentative en cours | Appel fournisseur réservé et lancé |
| Accepté par l’API | Fournisseur ayant retourné un identifiant, **pas une preuve de livraison** |
| Refusé par l’API | Erreur HTTP client fournisseur, aucune relance automatique |
| Issue incertaine | Timeout, réponse ambiguë ou interruption du processus ; vérifier chez le fournisseur |
| Annulé | Retiré de la file par l’opérateur |

Les webhooks signés Resend/Meta et les messages texte WhatsApp entrants sont maintenant intégrés ; voir `IMPLEMENTATION.md`. Les réponses email entrantes restent manuelles. Les erreurs réseau ambiguës ne sont jamais réessayées automatiquement pour éviter les doublons. Les appels qui étaient en cours à l’arrêt deviennent « Issue incertaine » au prochain démarrage.

## Données et sauvegarde

Au premier démarrage, les JSON sont importés dans `data/yallah.sqlite3`. Ensuite, les modifications web restent dans SQLite. Les scripts CLI continuent à utiliser leurs JSON : ils ne sont pas synchronisés avec les campagnes.

La base contient des coordonnées, preuves, textes et historique ; elle est ignorée par Git. Pour sauvegarder, arrêter le serveur puis copier le dossier `data/` vers un emplacement privé sécurisé. `YALLAH_DB` permet de choisir un autre chemin. Conserver la base conserve aussi les désinscriptions et leurs signatures. Limiter l’accès aux sauvegardes et définir une durée de conservation adaptée.

## Déploiement et sécurité

Sans `YALLAH_ADMIN_PASSWORD`, le mode privé/de confiance permet de tester la simulation, mais toute personne ayant accès au serveur peut consulter et modifier les données. **Ne pas exposer ce mode publiquement.**

Pour une utilisation réelle : serveur HTTPS avec contrôle d’accès, mot de passe fort, proxy correctement configuré, sauvegardes et validation juridique. Des comptes locaux et rôles mono-équipe sont disponibles via `manage.py` ; il n’y a toujours pas de récupération autonome de mot de passe ni de limite de tentatives intégrées. Prévoir ces protections au niveau du proxy. Un seul processus serveur/worker est recommandé.

Le jeton de session protège les écritures intersites ; ce n’est pas un remplacement de l’authentification. Ne pas distribuer de secrets dans l’interface. Arrêter le worker/serveur constitue un arrêt d’urgence des nouvelles tentatives. Pour basculer globalement hors production, redémarrer avec `YALLAH_ENABLE_LIVE=0`.

Dans le bac à sable Arena de cette session, les domaines des API Resend et Meta ne font pas partie des hôtes réseau autorisés : **aucun envoi réel n’a été testé ici**. Les adaptateurs et callbacks sont couverts par tests simulés. L’accès réseau et un test contrôlé sur vos propres coordonnées autorisées sont nécessaires dans votre environnement de déploiement.

## Tests

```bash
python3 -m unittest discover -s tests -v
node --check web/app.js  # si Node est installé
```

Les tests utilisent des bases temporaires et des appels fournisseurs simulés. Ils couvrent notamment les refus, les autorisations liées aux destinations, les gardes d’activation, la simulation sans réseau, la file, la pause, les limites, la revalidation, les issues incertaines, la désinscription signée et les formats de requêtes.

## Boutons d’accès rapide

La page d’accueil propose un panneau **« Que souhaitez-vous faire ? »** : ajout
B2B/B2C, fiches à vérifier, messages, simulations email et WhatsApp, besoin
confirmé, publications B2C et historique. L’export CSV et l’actualisation sont
également accessibles directement. Chaque rubrique dispose d’une barre de
boutons contextuels ; les listes disposent d’un bouton de réinitialisation des
filtres. **État des fournisseurs** affiche le diagnostic de configuration sans
exposer ni demander de secret. Les raccourcis de campagne ouvrent une simulation
avec le canal présélectionné : ils n’activent jamais un envoi réel.

Tests des boutons dans un DOM simulé (Node.js 18+ et Python disponibles) :

```bash
npm ci
npm test
```

Ces dépendances servent uniquement aux tests de l’interface : le lancement de
l’application Python ne nécessite toujours aucune installation npm.
