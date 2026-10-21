# Offres d'emploi — module candidats
### Yallah Services · séparation stricte avec l'offre commerciale
**Créé le 21 octobre 2026** · 0 besoin réel en base · 62 tests

---

## 1. Pourquoi un module séparé

Jusqu'ici le dépôt produisait des **offres commerciales** : des messages adressés à des entreprises pour leur vendre une prestation de mise en relation. Il manquait le pendant : l'**offre d'emploi**, adressée à un candidat.

Les deux ne peuvent pas cohabiter dans un même fichier ni dans un même canal.

| | Offre commerciale (`yallah_prospection.py`) | Offre d'emploi (`yallah_emploi.py`) |
|---|---|---|
| Destinataire | L'établissement, en tant que **client** | Le **candidat** |
| Objectif | Obtenir un échange sur un besoin | Recevoir des candidatures |
| Contenu | Services, formats, demande de rendez-vous | Poste, ville, format, conditions connues, canal de candidature |
| Fichier source | `prospects_b2b.json` (48 établissements) | `besoins_emploi.json` (0 besoin réel) |
| Garde-fou | Prix, délais, garanties, vérifications | + urgence, promesse d'embauche, exigence de diplôme, CDI/CDD |

**La règle opérationnelle qui découle de ce tableau :** les 48 contacts de `prospects_b2b.json` ne reçoivent **jamais** une annonce d'emploi. Ce sont des clients, pas des candidats. Envoyer « nous recrutons une femme de ménage » à un hôtel client brouillerait les deux positions et abîmerait la relation.

---

## 2. Point de départ : il n'y a rien à publier aujourd'hui

`besoins_emploi.json` ne contient **aucun besoin réel**. Il contient une fiche d'exemple, marquée `exemple: true`, que le script refuse de publier.

C'est volontaire. Publier une annonce suppose qu'un employeur ait réellement dit « j'ai besoin de quelqu'un ». Aucun employeur n'a été contacté à ce jour (la prospection vient d'être livrée). Inventer une offre — même pour tester — reviendrait à annoncer un poste qui n'existe pas, ce qui est exactement ce que la règle « ne jamais inventer » interdit.

Le module est donc **prêt mais vide**, et il le dit :

```
$ python yallah_emploi.py
Aucun besoin publiable : toutes les fiches sont des exemples ou ont été écartées.
Rien n'a été publié. C'est le comportement attendu tant qu'aucun employeur n'a confirmé de besoin.
```

---

## 3. La règle « valeur ⇒ source »

Une annonce d'emploi contient naturellement des éléments sensibles : rémunération, horaires. Ce sont précisément les informations que la règle absolue interdit d'inventer.

Le module applique donc une règle simple : **toute valeur chiffrée doit porter sa source**. Dans le fichier, ces champs ne sont pas des chaînes mais des couples :

```json
"remuneration": { "valeur": "4 500 MAD brut mensuel", "source": "client, email du 21/10/2026" }
```

Trois comportements en découlent :

| Situation | Ce que fait le script |
|---|---|
| Valeur + source | La valeur apparaît dans l'annonce, et le garde-fou ne la bloque pas |
| Valeur sans source | **La valeur est supprimée**, remplacée par « non communiquée dans cette annonce », et le besoin devient non publiable |
| Pas de valeur | L'annonce dit honnêtement « non communiquée dans cette annonce » |

Une annonce qui dit « rémunération non communiquée » est moins vendeuse qu'une annonce qui affiche un chiffre. Mais c'est la seule version vraie tant que l'employeur n'a rien dit. Et c'est un signal utile : chaque mention « non communiquée » vous indique exactement quoi demander au client au prochain appel.

---

## 4. Structure d'un besoin

```json
{
  "ref": "EMP-001",
  "metier": "MEN",
  "ville": "Rabat",
  "zone": "Agdal",
  "format": "permanent",
  "statut": "ouvert",
  "source_confirmation": "Hôtel X, appel du 22/10/2026",
  "date_confirmation": "2026-10-22",
  "remuneration":  { "valeur": "", "source": "" },
  "horaires":      { "valeur": "", "source": "" },
  "frais_montant": { "valeur": "", "source": "" },
  "frais_moment":  { "valeur": "", "source": "" }
}
```

Les deux champs `frais_*` ne servent que si `POLITIQUE_FRAIS = "factures"` : ils sont alors obligatoires, et sans source ils bloquent la publication.

**Champs obligatoires pour être publiable :** `ref`, `metier`, `ville`, `zone`, `format`, `statut` = `ouvert`, `source_confirmation`, `date_confirmation`.

**Métiers disponibles** (`--metier`) : ceux de la fiche, plus les métiers d'exécution côté entreprises.

| Code | Métier | Code | Métier |
|---|---|---|---|
| `MEN` | femme de ménage | `CHA` | chauffeur |
| `NOU` | nounou / garde d'enfants | `GAR` | gardien / vigile |
| `CUI` | cuisinière à domicile | `PON` | nettoyage ponctuel |
| `AGE` | aide aux personnes âgées | `SRV` | serveur / extra |
| `PLG` | plongeur | `NET` | agent de nettoyage de fin de chantier |
| `COM` | vendeur / employé de commerce | | |

**Formats** : `permanent`, `temporaire`, `renfort journalier` — les trois seuls que la fiche autorise.

⚠️ Le module **refuse** `CDI` et `CDD`. Ce sont des qualifications contractuelles que Yallah n'a pas communiquées : « permanent » décrit un besoin, « CDI » décrit un contrat de travail. Confondre les deux peut créer un engagement.

---

## 5. Ce que produit l'annonce

### Français

> **Femme de ménage — Rabat (Agdal)**
>
> Type de besoin : poste permanent.
> Horaires : non communiqués dans cette annonce.
> Rémunération : non communiquée dans cette annonce.
>
> Yallah Services met en relation des employeurs et des candidats au Maroc. Ce besoin a été confirmé par un employeur ; les éléments ci-dessus sont ceux qu'il a communiqués, sans ajout de notre part.
>
> Pour proposer votre candidature, écrivez-nous sur WhatsApp ou par email à servicesyallah@gmail.com, en précisant la référence EMP-001 et le poste.

### Darija (lettres latines)

> **Femme de ménage — Rabat (Agdal)**
>
> Naw3 lkhedma : poste permanent.
> Lwqiyat : ma t3atawch f had l3lan.
> L2ajr : ma t3atatnach f had l3lan.
>
> Yallah Services kantwesel bin l2arbab lkhedma w lkandidates f lMaghrib. Had lkhdma m2ekda mn 3and chi mchghl, w lma3lomat li foq hiya li 3tana, bla ma nzido 7ta haja mn 3andna.
>
> Ila bghiti t9edem, sift message f WhatsApp wla f email l servicesyallah@gmail.com, w kteb fih raqm EMP-001 w smit lkhedma.

### Arabe

> **عاملة منزل — الرباط (أكدال)**
>
> نوع الحاجة: poste permanent.
> التوقيت: غير مذكورة في هذا الإعلان.
> الأجر: غير مذكور في هذا الإعلان.
>
> Yallah Services تعمل على الربط بين أصحاب العمل والمرشحين في المغرب. هذه الحاجة مؤكدة من طرف صاحب عمل، والمعطيات أعلاه هي التي قدمها دون أي إضافة منا.
>
> لتقديم ترشيحك، أرسل رسالة على واتساب أو عبر البريد الإلكتروني servicesyallah@gmail.com مع ذكر المرجع EMP-001 والمنصب.

**La phrase de confirmation est conditionnelle.** Elle n'apparaît que si `source_confirmation` est rempli. Une fiche sans source ne dit jamais « ce besoin a été confirmé ».

**Deux canaux de candidature, décidés le 21/10/2026 :**

| Canal | Valeur | Usage |
|---|---|---|
| WhatsApp | +212 691 733 585 (numéro de la fiche) | Lien `wa.me` prérempli avec la référence du poste |
| Email | servicesyallah@gmail.com | Lien `mailto:` avec objet prérempli « Candidature — [poste] (réf …) » |

Les deux figurent dans le texte de l'annonce et dans deux colonnes séparées du CSV (`lien_whatsapp`, `lien_email`), pour que la publication sur un canal donné n'oblige pas à réécrire le texte.

---

## 6. Garde-fou

Le module hérite du garde-fou B2C et y ajoute six interdits spécifiques aux annonces d'emploi.

| Interdit | Pourquoi | Exemple bloqué |
|---|---|---|
| Urgence commerciale | Crée une pression artificielle | « urgent », « dès que possible » |
| Promesse de rémunération | Aucun engagement tarifaire n'a été pris | « salaire attractif », « bien payé » |
| Promesse d'embauche | Yallah met en relation, elle n'embauche pas | « poste garanti » |
| Exigence non confirmée | Le client n'a rien dit des profils | « expérience requise », « diplôme exigé » |
| Pression à la candidature | Manipulation | « places limitées » |
| Qualification contractuelle | « permanent » ≠ CDI | « CDI », « CDD » |

S'y ajoutent les interdits hérités : prix et montants non sourcés, délais chiffrés, garanties, vérifications annoncées, certifications, superlatifs, numéro de téléphone écrit dans le texte, gratuité annoncée.

**Cas particulier des frais :** « sans frais », « aucun frais », « inscription gratuite » restent **bloqués** quand ils seraient écrits par improvisation. La seule exception est la phrase de politique `"aucun"`, explicitement activée par vous : elle est neutralisée avant le passage du garde-fou parce qu'elle découle d'une décision, pas d'une génération. Voir la question 1 en section 9.

---

## 7. Enchaînement avec le module commercial

Le cycle complet, une fois un client intéressé :

```
1. Prospection B2B          →  yallah_prospection.py
   un établissement répond et exprime un besoin
                              ↓
2. Le besoin est qualifié    →  vous notez : métier, ville, zone, format
   (c'est vous, pas le script)  + QUI a confirmé et QUAND
                              ↓
3. Besoin ajouté            →  besoins_emploi.json
                              ↓
4. python yallah_emploi.py --check
   → refuse tant que la source de confirmation manque
                              ↓
5. python yallah_emploi.py --langue darija
   → annonce prête, statut « publiable : oui »
                              ↓
6. Publication par vos soins  →  canal à définir (section 9)
```

**L'étape 2 est la seule qui ne peut pas être automatisée.** C'est celle où une personne décide que le besoin est réel. Le script ne peut pas vérifier qu'un employeur a vraiment besoin de quelqu'un ; il peut seulement vérifier que **vous avez écrit qui l'a dit et quand**.

---

## 8. Ce que le module ne fera jamais

- **Il n'invente pas de poste.** Sans entrée dans `besoins_emploi.json`, il ne produit rien.
- **Il n'invente pas de condition.** Un salaire ou des horaires sans source sont supprimés, pas complétés.
- **Il ne qualifie pas le contrat.** « Permanent » oui, « CDI » non.
- **Il ne promet rien.** Ni embauche, ni délai, ni remplacement.
- **Il n'écrit pas de numéro dans le texte.** Le lien WhatsApp est ajouté à côté.
- **Il ne publie pas les fiches d'exemple.** `exemple: true` = jamais publiable, testé automatiquement.

---

## 9. Les quatre questions, et où elles en sont

Elles bloquent la publication réelle, pas le développement.

**État au 21 octobre 2026 :** question 1 **tranchée : aucun frais** · question 2 tranchée · question 3 tranchée · question 4 tranchée (conservation + actualisation quotidienne).

### 1. Frais demandés aux candidats — **tranché : aucun frais**

**Décision transmise le 21/10/2026 :** « Des frais, 100 MAD à l'inscription. »
**Décision finale le 21/10/2026 :** « ignorer pour respecter la loi. »

Les 100 MAD sont abandonnés. `POLITIQUE_FRAIS` est réglé sur `"aucun"` : chaque
annonce écrit désormais noir sur blanc qu'aucun frais n'est demandé au candidat,
et aucun montant n'apparaît nulle part.

#### Pourquoi ce revirement

L'article 480 du Code du travail marocain (loi 65-99) dispose qu'« il est
interdit aux agences de recrutement privées de percevoir, directement ou
indirectement, des demandeurs d'emploi des émoluments ou frais, en partie ou en
totalité ». L'article 477 définit l'agence de recrutement privée comme toute
personne morale dont l'activité consiste notamment à « rapprocher les demandes et
les offres d'emploi ». Facturer 100 MAD à l'inscription d'un candidat entre très
probablement dans le champ de cette interdiction.

**Sources consultées le 21 octobre 2026 :**

| Source | Ce qu'elle établit |
|---|---|
| [Fiscamaroc — Intermédiation en matière de recrutement](https://www.fiscamaroc.com/fr/travail/lintermediation-en-matiere-de-recrutement-et-dembauchage-790/lintermediation-en-matiere-de-recrutement-859.htm) | Texte de l'article 480 : interdiction de percevoir des émoluments ou frais auprès des demandeurs d'emploi |
| [DRH.ma — Code du travail](https://drh.ma/legislation-travail-maroc/code-du-travail-maroc/) | Sommaire du Livre IV : « Interdiction aux agences de recrutement privées de percevoir des émoluments (Article 480) » |
| [Rekrute — sanctions Code du travail](https://www.rekrute.com/emplois-les-sanctions-que-vous-encourez-en-cas-de-non-respect-du-code-du-travail-xvii-conseils-carriere-918.html) | Reprise de l'article 480 ; amendes évoquées jusqu'à 60 000 DH en cas de manquement |
| [Ministère de l'emploi — agences de recrutement privées](https://miepeec.gov.ma/mtip-espace-emploi/intermediation-en-matiere-demploi/agences-de-recrutement-privees/apercu/?lang=fr) | L'activité d'intermédiation est soumise à autorisation préalable |
| [OIT — guide pour les agences d'emploi privées](https://www.ilo.org/sites/default/files/wcmsp5/groups/public/@ed_norm/@declaration/documents/instructionalmaterial/wcms_103883.pdf) | Convention n° 181, art. 7 : même principe d'interdiction de faire payer les travailleurs |

**Ce que je ne dis pas :** je ne suis pas juriste et je n'affirme pas que la
situation de Yallah tombe avec certitude sous cet article. Cette qualification
dépend de son statut exact et de son activité réelle. Le renoncement reste
néanmoins la position la plus sûre, et la seule qui permette d'écrire une phrase
vraie dans chaque annonce.

#### Ce que fait le code

```python
POLITIQUE_FRAIS = "aucun"          # décision du 21/10/2026, pas une valeur par défaut
FRAIS_CANDIDAT_VALIDATION = None   # verrou toujours armé
```

- La phrase d'annonce est : « Aucun frais n'est demandé au candidat, à aucune
  étape de la mise en relation » — traduite en darija et en arabe.
- Le garde-fou ne se signale plus lui-même : cette phrase interne est neutralisée
  avant analyse, alors que « sans frais » ou « inscription gratuite » improvisés
  restent bloqués.
- **Le verrou juridique reste en place.** Si la politique repassait un jour sur
  `"factures"` sans validation juridique datée, aucune annonce affichant des
  frais ne serait publiable, avec un motif citant l'article 480.
- « 100 MAD » n'apparaît dans aucune annonce, dans aucune langue. C'est testé.

#### Les deux autres voies restent ouvertes

1. **Facturer l'employeur plutôt que le candidat.** C'est le modèle dominant des
   cabinets de recrutement au Maroc : honoraires de 15 à 25 % du salaire annuel
   brut, payés par l'entreprise ([Jobsquare, 2026](https://www.jobsquare.ma/blog/agences-recrutement-maroc-cabinets-chasse-tetes/)).
   L'article 480 ne protège que les demandeurs d'emploi.
2. **Revenir aux frais candidats** si un avis juridique daté écartait
   l'interdiction : il suffira alors de renseigner `FRAIS_CANDIDAT_VALIDATION`.

### 2. Canal de candidature — **tranché : WhatsApp + email**

Décision du 21/10/2026 : les candidatures arrivent sur **WhatsApp** (+212 691 733 585) et sur **servicesyallah@gmail.com**. Les deux canaux sont intégrés au module et apparaissent dans les trois langues.

Deux conséquences à garder en tête :

- **La boîte WhatsApp est partagée** avec les clients. Un candidat et un hôtel client écrivent au même endroit. Ce n'est pas bloquant, mais il faudra trier — un message qui commence par « réf EMP-… » est une candidature, le reste est du commercial.
- **L'adresse email semble avoir été créée pour ce module.** Si elle reçoit aussi des demandes clients, la même règle de tri s'applique.

### 3. Où publier — **partiellement tranché**

L'email fourni est un **canal de réception**, pas un lieu de publication. Le module produit le texte et les liens ; il ne diffuse rien.

Restent à définir : groupes Facebook de quartier, Instagram, TikTok, affichage physique, bouche-à-oreille. Chaque canal impose son format et ses règles.

### 4. Conservation des candidatures — **tranché : conserver + actualiser chaque jour**

Une annonce génère des CV, des numéros et des adresses : ce sont des données personnelles. La loi 09-08 et les obligations déclaratives auprès de la CNDP s'appliquent probablement à ce traitement, mais **je ne l'affirme pas** — c'est à faire vérifier par un juriste avant d'ouvrir un fichier de candidatures.

**Décision du 21/10/2026 :** « conserver mais faire l'actualisation chaque jour. »
Autrement dit : on garde les fiches et les échanges, mais on revérifie chaque jour
ce qui est encore vrai. Côté prospection, cette règle est déjà outillée : une
fiche non revérifiée le jour même ne peut recevoir aucun message, et
`--actualiser` produit la checklist du jour (voir `MESSAGES_PROSPECTION.md`,
section 6). Côté candidatures, la même discipline s'applique à la main : la
boîte `servicesyallah@gmail.com` et le WhatsApp sont relus chaque jour, et une
candidature sans suite est archivée ou supprimée plutôt que laissée en vrac.

**Ce qui reste à faire vérifier :** la durée de conservation et la déclaration
CNDP applicable à ce traitement. Je ne l'affirme pas — c'est à faire confirmer
par un juriste.

**Point rassurant sur l'outil lui-même :** les scripts ne stockent aucune candidature. Ils produisent du texte ; les messages restent dans WhatsApp et dans la boîte email. Il n'y a donc pas, aujourd'hui, de fichier de candidats créé par ce dépôt. La question portera sur ce que vous ferez de ces messages (recherche, relance, archivage), pas sur ce que fait le code.

---

## 10. Commandes

```bash
python yallah_emploi.py --check                  # validation ; code retour 1 si un besoin est mal formé
python yallah_emploi.py                          # CSV des besoins publiables (vide aujourd'hui)
python yallah_emploi.py --avec-exemples          # aperçu incluant la fiche de démonstration
python yallah_emploi.py --langue darija
python yallah_emploi.py --langue arabe --ref EMP-001
python -m unittest discover -s tests -v          # 98 tests (20 prospection + 42 emploi + 32 messages + 4 B2C)
```

**Colonnes du CSV :** `ref`, `poste`, `ville`, `zone`, `format`, `statut`, `publiable`, `remuneration`, `horaires`, `informations_non_communiquees`, `annonce`, `alertes`, `problemes`, `source_confirmation`, `date_confirmation`, `lien_whatsapp`, `lien_email`.

La colonne `informations_non_communiquees` est votre liste de relance : chaque champ qui y figure est une question à poser au client.

---

## 11. Fichiers

| Fichier | Rôle |
|---|---|
| `besoins_emploi.json` | Besoins de recrutement confirmés — **aucun à ce jour**, une fiche d'exemple |
| `yallah_emploi.py` | Validation, règle « valeur ⇒ source », rédaction des annonces, garde-fou |
| `tests/test_emploi.py` | 42 tests : garde-fou emploi, règle de sourçage, politiques de frais, verrou juridique art. 480, canaux |
| `offres_emploi.csv` | Artefact de travail généré (ignoré par Git) |
