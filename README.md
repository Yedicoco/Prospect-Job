# Prospect-Job — Yallah Services

## Application web

**Nouveau :** pipeline commercial, tâches, relances manuelles J+7, conversations et import d’emails entrants, demandes publiques, recrutement, missions, coûts et supervision. Guide du parcours : [IMPLEMENTATION.md](IMPLEMENTATION.md) · Kit pilote terrain B2B/B2C : [PILOTE_LANCEMENT.md](PILOTE_LANCEMENT.md).

Une interface web en français est maintenant disponible : tableau de bord, gestion des prospects, préparation des messages, suivi manuel, refus et besoins d’emploi. Les **campagnes automatiques email et WhatsApp Business** sont disponibles, en simulation par défaut ; les envois réels exigent qualification des contacts, configuration des fournisseurs et activation explicite.

```bash
python3 webapp.py --port 8000
```

Ouvrez `http://localhost:8000` (ou l’aperçu Arena). Aucune dépendance externe. Les données sont importées dans une base SQLite privée, séparée des JSON utilisés par les scripts CLI.

**Accès privé de confiance par défaut.** Une authentification administrateur par variable d’environnement et HTTPS sont requis pour l’envoi réel ; ne pas exposer le mode sans authentification sur Internet. Guide et limites : [WEB_APP.md](WEB_APP.md).


Trois modules distincts, et une frontière à ne jamais franchir : **une offre
commerciale s'adresse à un client, une offre d'emploi s'adresse à un candidat.**

| Module | Fichier | Objet |
|---|---|---|
| **B2C** (particuliers) | `yallah_b2c.py` | Contenus de publication à destination des particuliers |
| **B2B** (entreprises clientes) | `yallah_prospection.py` | Prospection d'entreprises, à partir d'un fichier de prospects sourcés |
| **Messages** (B2B + B2C) | `yallah_messages.py` | Messages de prospection personnalisés, contrôlés, avec liens préremplis — **aucun envoi automatique** |
| **Emploi** (candidats) | `yallah_emploi.py` | Annonces d'emploi, uniquement pour des besoins confirmés par un employeur |

La recherche de prospects et la synthèse sont dans **`PROSPECTION_B2B.md`**
(48 établissements : 26 en phase 1 à Casablanca, Rabat, Marrakech et Bouskoura,
11 en phase 2 à Tanger, Agadir, Mohammedia et Kénitra, 11 en phase 3 à Fès,
El Jadida et Témara/Harhoura, chacun avec URL source et date de consultation).

## Module Messages (prospection B2B + B2C)

`yallah_messages.py` transforme les fiches sourcées en messages prêts à envoyer
**à la main**, un contact à la fois. Il ne fait aucun appel réseau : `--envoyer`
est refusé explicitement. Voir **`MESSAGES_PROSPECTION.md`**.

```bash
python3 yallah_messages.py --check                              # contrôle seul
python3 yallah_messages.py --prenom "Youssef" --markdown file_envoi.md
python3 yallah_messages.py --type b2c --langue darija --prenom "Youssef"
```

État actuel : 47 messages B2B prêts (48 fiches, dont 1 sans contact direct),
0 fiche B2C réelle (voir la section 7 de `MESSAGES_PROSPECTION.md`), 15 envois
manuels maximum par jour, plan réparti sur 4 jours.

**Actualisation quotidienne** : les fiches sont conservées, mais une fiche non
revérifiée le jour même ne peut plus recevoir de message.

```bash
python3 yallah_messages.py --actualiser actualisation.md   # checklist du matin
python3 yallah_messages.py --verifie B2B-001 B2B-002      # fiches reconfirmées
```

## Module B2C

`yallah_b2c.py` prépare les contenus de publication B2C (particuliers) de
Yallah Services, structure de recherche et de mise en relation de personnel
au Maroc.

## Principe

Le script construit la matrice **zone × besoin** (phase 1), génère pour chaque
case une référence et un lien WhatsApp précodé (wa.me), et peut générer un
texte de publication par case via l'API Claude. Chaque texte généré est passé
au garde-fou automatique de la section 10 (rien d'inventé : pas de prix, de
délais, de garanties, de numéros de téléphone dans le texte, etc.).

## Utilisation

```bash
# Matrice + liens WhatsApp uniquement, sans IA (recommandé pour valider d'abord)
python yallah_b2c.py --dry-run

# Génération de textes (nécessite une clé API Claude)
python yallah_b2c.py --plateforme instagram --langue darija --limit 10

# Filtrer par ville et/ou besoin
python yallah_b2c.py --ville Casablanca --besoin NOU --plateforme tiktok

python yallah_b2c.py --ville Rabat --besoin MEN --langue francais --sortie rabat_men.csv
```

### Options

| Option | Rôle |
|--------|------|
| `--ville` | Casablanca, Bouskoura, Rabat ou Marrakech |
| `--besoin` | Code besoin : MEN, NOU, CUI, CHA, AGE, GAR, PON |
| `--plateforme` | tiktok, instagram, facebook, whatsapp (défaut : instagram) |
| `--langue` | francais, darija, arabe (défaut : francais) |
| `--limit N` | Nombre maximum de cases traitées (0 = toutes) |
| `--dry-run` | Matrice et liens uniquement, sans génération IA |
| `--sortie FICHIER` | Fichier CSV de sortie (défaut : `contenus_b2c.csv`) |

## Règles absolues (section 10 de la fiche)

Ne jamais inventer ni affirmer : prix, salaires, commissions, frais ; délais de
recrutement ou de mise en relation ; garanties de résultat, de fiabilité ou de
remplacement ; disponibilité immédiate de candidats ; qualifications,
expériences ou références de candidats ; vérifications d'identité ou contrôles
d'antécédents ; conditions contractuelles et modalités de paiement ; quartiers
déservis pour une mission précise ; certifications ou agréments ; coordonnées
autres que celles fournies (WhatsApp officiel et site vitrine officiel
`https://yallahservices-one.vercel.app`, configurable via `YALLAH_SITE_WEB`,
inclus automatiquement dans les messages clients et prospects B2B / B2C).

Chaque texte généré par IA est contrôlé automatiquement : en cas d'alerte, le
statut passe à "BLOQUÉ - à corriger" dans le CSV.

## Fichiers générés

Le CSV de sortie (`contenus_b2c.csv` par défaut) est un artefact de travail :
il ne doit pas être commité dans Git (voir `.gitignore`).

## Module B2B — prospection d'entreprises clientes

`yallah_prospection.py` lit `prospects_b2b.json` (fiches **sourcées** : URL +
date de consultation obligatoires), calcule une priorité, génère un message
**commercial** par segment et par langue, puis applique le garde-fou. Une fiche
sans source est refusée : aucune coordonnée ne peut entrer sans provenance.

```bash
python yallah_prospection.py --check                     # validation, code retour 1 si anomalie
python yallah_prospection.py                             # CSV complet
python yallah_prospection.py --phase 1
python yallah_prospection.py --phase 2 --ville Tanger
python yallah_prospection.py --phase 3 --niveau A
python yallah_prospection.py --ville Rabat --niveau A
python yallah_prospection.py --segment hotel --langue darija
python yallah_prospection.py --sans-messages             # contacts seuls
python -m unittest discover -s tests -v                  # 98 tests
```

### Niveaux de vérification

| Niveau | Signification |
|---|---|
| `A` | Coordonnée lue sur la page officielle consultée |
| `B` | Coordonnée vue dans un extrait de recherche / page sociale, à reconfirmer |
| `C` | Aucun contact direct publié (formulaire uniquement) |

### Périmètre de collecte

Uniquement des **coordonnées professionnelles publiées par l'établissement
lui-même**, pour le contacter au sujet d'une prestation. Pas d'annuaire acheté,
pas d'extraction de données personnelles, pas d'envoi automatisé en masse.
Les messages générés sont des **offres commerciales** : ils ne doivent jamais
être envoyés comme des offres d'emploi (voir `PROSPECTION_B2B.md`, § 10).

## Module emploi — annonces pour candidats

`yallah_emploi.py` transforme un besoin de recrutement **réellement confirmé par
un employeur** en annonce pour candidats. Il ne publie rien tant qu'aucun besoin
n'est enregistré : `besoins_emploi.json` ne contient aujourd'hui qu'une fiche
d'exemple, que le script refuse de publier.

Règle centrale : **toute valeur chiffrée doit porter sa source**. Une
rémunération ou des horaires sans source sont supprimés de l'annonce, qui dit
alors « non communiqué dans cette annonce ».

```bash
python yallah_emploi.py --check              # validation
python yallah_emploi.py --avec-exemples      # aperçu du format
python yallah_emploi.py --langue darija
```

Les candidatures sont reçues sur **WhatsApp** (+212 691 733 585) et sur
**servicesyallah@gmail.com** : les deux liens sont préremplis avec la référence
du poste.

**Frais candidats : aucun** (décision du 21/10/2026, pour respecter l'article 480
du Code du travail). `POLITIQUE_FRAIS = "aucun"` : chaque annonce écrit qu'aucun
frais n'est demandé au candidat, et aucun montant n'y figure. Le verrou
`FRAIS_CANDIDAT_VALIDATION` reste armé : toute réactivation de frais sans
validation juridique datée bloque la publication. Voir `OFFRES_EMPLOI.md`, § 9.

⚠️ Les contacts de `prospects_b2b.json` sont des **clients** : ils ne doivent
jamais recevoir une annonce d'emploi. Détail et questions ouvertes dans
`OFFRES_EMPLOI.md`.

## Contact

WhatsApp prioritaire : +212 691 733 585 (lien généré automatiquement par case,
sans numéro écrit dans les textes de publication).
