# Prospect-Job — Module B2C Yallah Services

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

## Contact

WhatsApp prioritaire : +212 691 733 585 (lien généré automatiquement par case,
sans numéro écrit dans les textes de publication).
