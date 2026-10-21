# Prospect-Job — Yallah Services

Trois modules distincts, et une frontière à ne jamais franchir : **une offre
commerciale s'adresse à un client, une offre d'emploi s'adresse à un candidat.**

| Module | Fichier | Objet |
|---|---|---|
| **B2C** (particuliers) | `yallah_b2c.py` | Contenus de publication à destination des particuliers |
| **B2B** (entreprises clientes) | `yallah_prospection.py` | Prospection d'entreprises, à partir d'un fichier de prospects sourcés |
| **Emploi** (candidats) | `yallah_emploi.py` | Annonces d'emploi, uniquement pour des besoins confirmés par un employeur |

La recherche de prospects et la synthèse sont dans **`PROSPECTION_B2B.md`**
(48 établissements : 26 en phase 1 à Casablanca, Rabat, Marrakech et Bouskoura,
11 en phase 2 à Tanger, Agadir, Mohammedia et Kénitra, 11 en phase 3 à Fès,
El Jadida et Témara/Harhoura, chacun avec URL source et date de consultation).

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
autres que celles fournies.

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
python -m unittest discover -s tests -v                  # 20 tests
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

⚠️ Les contacts de `prospects_b2b.json` sont des **clients** : ils ne doivent
jamais recevoir une annonce d'emploi. Détail et questions ouvertes dans
`OFFRES_EMPLOI.md`.

## Contact

WhatsApp prioritaire : +212 691 733 585 (lien généré automatiquement par case,
sans numéro écrit dans les textes de publication).
