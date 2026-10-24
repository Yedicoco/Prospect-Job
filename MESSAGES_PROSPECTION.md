# Messages de prospection — B2B et B2C

Moteur : `yallah_messages.py`. Il transforme les fiches de prospects en **messages
personnalisés, contrôlés et prêts à envoyer à la main**.

> **Ce script n'envoie rien.** Aucun appel réseau, aucune API WhatsApp, aucun
> serveur mail. Il n'existe aucune option d'envoi : `--envoyer` est refusé
> explicitement. L'envoi reste un geste humain, depuis votre propre compte,
> un contact à la fois.

---

## 1. Deux périmètres, jamais mélangés

| Périmètre | Fichier source | Destinataire | Offre | Fiches aujourd'hui |
|---|---|---|---|---|
| **B2B** | `prospects_b2b.json` | hôtel, riad, restaurant, chantier, commerce… | personnel pour l'établissement | **48** (dont 47 contactables) |
| **B2C** | `prospects_b2c.json` | particulier / famille | personnel de maison | **0 réelle** (1 fiche d'exemple) |

Un même numéro ou email présent dans les deux fichiers est signalé comme
**doublon** et n'est jamais contacté deux fois. Un contact inscrit dans
`meta.refus` est écarté automatiquement, quel que soit le fichier.

Le module **Emploi** (`yallah_emploi.py`) reste séparé : aucune de ces 48 fiches
ne reçoit jamais une annonce d'emploi.

---

## 2. Comment un prospect devient « qualifié »

Une fiche ne reçoit un message que si elle passe **toutes** ces conditions
(`qualifier()` dans `yallah_messages.py`) :

| Condition | Sinon |
|---|---|
| Source : `source_url` commençant par `http` **et** `date_consultation` au format AAAA-MM-JJ | rejetée |
| Niveau de vérification A ou B | niveau C (formulaire seulement) : rejetée |
| Au moins un contact direct publié (téléphone ou email) | rejetée |
| Fiche marquée `exemple: true` | rejetée |
| Contact absent du registre des refus | rejetée |
| Contact non déjà présent sur une autre fiche | doublon, rejetée |

Puis viennent les **réserves** (le message part quand même, mais elles restent
visibles dans la file d'envoi) :

- **source périmée** : plus de 90 jours entre la consultation et aujourd'hui →
  statut bloqué, à reconfirmer d'abord ;
- **niveau B** : coordonnée vue dans un extrait de moteur de recherche, non
  reconfirmée sur la page officielle.

Enfin le **score** (0 à 10) ordonne la file : zone de phase 1, poids du segment
(B2B) ou niveau de contact, phase d'ouverture, niveau de vérification.

---

## 3. Le message

Un message par fiche, dans la langue choisie (`fr`, `darija`, `arabe`), construit
uniquement à partir de faits déjà présents dans la fiche : nom, ville, zone,
besoins rattachés au segment (B2B) ou besoin déclaré (B2C). **Rien n'est ajouté
qui ne soit pas dans la fiche.**

Forme type (B2B, français) :

```
Bonjour,

Je suis Youssef de Yallah Services. Nous accompagnons les établissements de
Casablanca sur leurs besoins en personnel : propreté et entretien des locaux,
cuisine et plonge, service en salle / extra.

Je vous contacte au sujet de Idou Anfa Hotel & Spa, Anfa. Selon votre
organisation, nous travaillons sur trois formats : permanent, temporaire et
renfort journalier.

Auriez-vous dix minutes pour un échange afin que nous comprenions votre
besoin réel ?

Si ce sujet ne vous concerne pas, dites-le-moi simplement : je ne vous
relancerai pas.

Bien à vous,
Youssef — Yallah Services
```

Forme type (B2C, réponse à une annonce publique) :

```
Bonjour,

Je suis Youssef de Yallah Services. J'ai vu votre annonce : nounou à Anfa,
Casablanca.

Nous travaillons avec les familles pour ce type de besoin : femme de ménage,
nounou, cuisinière, aide aux personnes âgées, chauffeur. Selon ce que vous
cherchez, nous proposons du permanent, du temporaire ou un renfort ponctuel.

Auriez-vous dix minutes pour un échange afin de comprendre votre besoin ?

Si ce message ne vous intéresse pas, dites-le-moi simplement : je ne vous
recontacte pas.

Bien à vous,
Youssef — Yallah Services
```

### Rien n'est inventé (garde-fou automatique)

Chaque message passe le garde-fou hérité des modules B2B/B2C, auquel s'ajoutent
trois contrôles :

| Contrôle | Exemple refusé |
|---|---|
| prix, salaire, commission, frais | « à partir de 3 000 dh » |
| délai chiffré / disponibilité | « sous 48 h », « immédiatement » |
| garantie, remplacement assuré | « satisfait ou remplacé » |
| vérification annoncée | « profils vérifiés » |
| certification, agrément, superlatif | « agréé », « n°1 au Maroc » |
| **formule de retrait absente** | message sans « je ne vous relancerai pas » |
| **message trop long** | plus de 900 caractères |
| **URL non officielle** | toute URL autre que `https://yallahservices-one.vercel.app` |
| pression commerciale | « dernière chance », « remise de 20 % » |

Un message qui déclenche un contrôle n'est pas supprimé en silence : il sort en
`BLOQUE - a corriger` avec le motif exact.

---

## 4. Le prénom manquant bloque les liens

Le texte contient `[prenom]`. Tant que `--prenom` n'est pas fourni :

- le statut est `A COMPLETER - prenom manquant` ;
- **aucun lien `wa.me` ni `mailto` n'est créé** — impossible d'envoyer un message
  avec un placeholder par accident.

Dès que le prénom est fourni, chaque ligne reçoit :

- `lien_whatsapp` : `https://wa.me/<numéro du prospect>?text=<message encodé>` ;
- `lien_email` : `mailto:<email>?subject=...&body=<message encodé>`, pour les
  fiches sans téléphone.

Le lien s'ouvre dans **votre** WhatsApp ou **votre** messagerie : vous relisez et
vous appuyez sur envoyer.

---

## 5. Plan d'envoi et cadence

- Tri : fiches prêtes d'abord, puis B2B, phase 1 avant 2 et 3, score décroissant.
- **15 messages prêts maximum par jour** (`MAX_PAR_JOUR`) : le plan répartit
  automatiquement les 47 messages B2B sur 4 jours.
- Une seule relance, **jamais avant 7 jours** sans réponse, **jamais** après un
  refus.

| Jour | Messages prêts |
|---|---|
| 1 | 15 |
| 2 | 15 |
| 3 | 15 |
| 4 | 2 |

---

## 6. Conformité (à valider avant campagne)

Ce module propose des garde-fous, il ne remplace pas un avis juridique.

- **Loi 09-08 / CNDP** : prospection d'un professionnel sur sa coordonnée
  professionnelle publiée, message court, identifié, avec moyen de refus.
  Pour un particulier (B2C), on **répond à une annonce publique** — on ne
  démarche pas à froid.
- **Registre des refus** : `meta.refus` dans chaque fichier JSON ; toute personne
  qui demande à ne plus être contactée y est inscrite et n'est plus jamais
  sollicitée.
- **Minimisation** : on ne stocke que ce qui est nécessaire au contact
  (nom d'usage, ville, zone, téléphone ou email publié, URL source, date).
  Rien sur la vie privée, la famille ou la situation personnelle.
- **Conservation** : décidée le 21/10/2026 — **on conserve, mais on actualise
  chaque jour**. Une fiche non revérifiée le jour même ne peut plus recevoir de
  message (statut `A ACTUALISER`). La durée de conservation définitive et la
  déclaration CNDP restent à confirmer par un juriste.
- **Pas d'envoi de masse** : aucune automatisation d'envoi, aucune API WhatsApp
  Business, aucun routage SMTP.

---

## 6 bis. L'actualisation quotidienne

Chaque fiche porte deux dates :

| Champ | Sens |
|---|---|
| `date_consultation` | quand la fiche a été trouvée et sourcée (péremption à 90 jours) |
| `date_derniere_verification` | quand elle a été revérifiée pour la dernière fois (à défaut : la date de consultation) |

Le matin :

```bash
python3 yallah_messages.py --actualiser actualisation.md
```

Le fichier liste les fiches à revérifier, avec le lien source et le contact à
reconfirmer. Vous ouvrez chaque source, vous vérifiez que le contact est toujours
publié et identique, puis :

```bash
python3 yallah_messages.py --verifie B2B-001 B2B-002 B2B-003
```

Les fiches estampillées deviennent envoyables le jour même ; les autres restent
en `A ACTUALISER`. Une fiche dont le contact a disparu ou changé ne doit pas être
estampillée : corrigez-la ou retirez-la du fichier.

---

## 7. Côté B2C : la collecte manuelle, et son résultat

Collecte manuelle faite le 2026-10-21, source par source :

| Source | Ce qu'on y trouve | Verdict |
|---|---|---|
| [Avito — « demandes » femmes de ménage](https://www.avito.ma/fr/maroc/femme_de_menage--demandes) | quasi exclusivement des **agences** (HOME SERVICE, MG Expert Service, Akla Service…) et des personnes qui **proposent** leurs services | écarté : concurrents ou candidats, pas des clients |
| [MarocAnnonces — emploi femme de ménage](https://www.marocannonces.com/emploi-femme-menage) | annonces d'**employeurs** (sociétés, cliniques, hôtels) | relève du **B2B**, pas du B2C |
| [Nounou.ma — offres d'emploi](https://nounou.ma/en/jobs) | vraies demandes de familles (Casablanca, Rabat), avec budget et quartier | **non retenu** : les coordonnées sont derrière un compte, aucun contact public affiché → niveau C, donc non contactable |
| Souika | annonces de sociétés | B2B |

Aucune annonce de particulier cherchant du personnel **avec un contact public
vérifiable** n'a donc pu être retenue. Le fichier reste vide : **mieux vaut zéro
fiche qu'une fiche inventée.**

### La routine quotidienne qui remplace la collecte automatique

1. **Pendant la journée** : toute demande entrante (WhatsApp, recommandation,
   annonce repérée) est ajoutée à `prospects_b2c.json` dans la minute, avec
   l'URL de l'annonce et la date.
2. **Le matin** : `--actualiser` sort la liste ; `--verifie` estampille ce qui a
   été reconfirmé.
3. **Ensuite seulement** : `--prenom "..." --type b2c` génère les messages.
4. **Une seule relance**, jamais avant 7 jours, jamais après un refus.

### Ajouter une fiche B2C (2 minutes)

Dès qu'une demande arrive (WhatsApp entrant, recommandation, annonce repérée),
ajoutez-la à `prospects_b2c.json` :

```json
{
  "nom": "Annonce Avito du 21/10 (nounou, Anfa)",
  "besoin": "NOU",
  "ville": "Casablanca",
  "zone": "Anfa",
  "tel": "+212 6XX XX XX XX",
  "email": "",
  "source_url": "https://l-url-de-l-annonce-publique",
  "date_consultation": "2026-10-21",
  "niveau": "A",
  "contexte": "Annonce publique : cherche nounou 4 jours/semaine."
}
```

Codes besoin : `MEN` femme de ménage, `NOU` nounou, `CUI` cuisinière,
`CHA` chauffeur, `AGE` aide aux personnes âgées, `GAR` gardien,
`PON` nettoyage ponctuel.

Règles : le particulier doit **avoir publié lui-même** une demande, sur une page
publique et contactable. Pas de numéro trouvé ailleurs, pas de déduction.

---

## 8. Commandes

```bash
# Contrôle seul : aucune écriture, code retour 1 si un message est bloqué
python3 yallah_messages.py --check

# Génère la file d'envoi (CSV) avec les liens préremplis
python3 yallah_messages.py --prenom "Youssef" --langue fr

# File d'envoi lisible, prête à suivre jour par jour
python3 yallah_messages.py --prenom "Youssef" --markdown file_envoi.md

# Uniquement les particuliers, en darija
python3 yallah_messages.py --type b2c --langue darija --prenom "Youssef"

# Inclure aussi les fiches non qualifiées (audit du fichier source)
python3 yallah_messages.py --prenom "Youssef" --tous-les-statuts

# Actualisation quotidienne : checklist puis estampillage
python3 yallah_messages.py --actualiser actualisation.md
python3 yallah_messages.py --verifie B2B-001 B2B-002
```

| Option | Rôle |
|---|---|
| `--type` | `b2b`, `b2c` ou `tous` (défaut) |
| `--langue` | `fr`, `darija`, `arabe` (défaut `fr`) |
| `--prenom` | signataire ; sans lui, aucun lien n'est créé (`YALLAH_PRENOM` accepté) |
| `--markdown` | écrit la file d'envoi détaillée |
| `--tous-les-statuts` | inclut les fiches rejetées dans le CSV |
| `--actualiser FICHIER` | écrit la checklist des fiches à revérifier aujourd'hui |
| `--verifie REF…` | estampille les fiches reconfirmées à la date du jour |
| `--check` | validation seule, code retour exploitable |
| `--envoyer` | **refusé** : ce script ne réalise aucun envoi |

---

## 9. État actuel

```
python3 yallah_messages.py --prenom "Youssef"
→ 47 ligne(s) : 47 prêtes à envoyer à la main, 0 bloquée, 0 à compléter, 2 non qualifiées
→ Plan : 47 messages sur 4 jours, maximum 15 par jour
```

Les deux fiches non qualifiées :

- `B2B-017 The White Palace Rabat` — aucun contact direct publié (formulaire
  seulement, niveau C) ;
- `BC-001 Annonce exemple` — fiche de démonstration, jamais envoyable.

Tests : `tests/test_messages.py`, 36 tests (qualification, non-envoi, liens,
doublons, registre des refus, sources périmées, actualisation quotidienne,
trois langues, cadence). Total du dépôt : **98 tests**.
