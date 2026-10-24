# Plan d'Exécution Opérationnel — Pilote Yallah Services
**Date de préparation : 24 octobre 2026** · **Objectif : 1er besoin employeur confirmé, 1re offre publiée, 1res demandes B2C entrantes**

> **Rappel d'intégrité :** aucune coordonnée n'a été marquée « revérifiée au 24/10/2026 » automatiquement (le bac à sable n'accède pas aux sites des hôtels) et aucun email commercial n'a été envoyé sans votre validation. Ce document vous donne tout clé en main pour exécuter la séquence pilote en moins de 45 minutes par jour.

---

## 1. Exploitation de la boîte Gmail reconnectée (`servicesyallah@gmail.com`)

### État vérifié au 24/10/2026
- **0 envoi commercial** sur les 7 derniers jours (`in:sent`).
- **0 candidature reçue** (`EMP-…`) et **0 réponse prospect B2B/B2C**.
- **3 anciens brouillons personnels** déjà présents dans le compte : **conservés intacts**.

### Libellés créés sur `servicesyallah@gmail.com`
Pour séparer les flux entrants (clients entreprises, familles, candidats et retraits), 5 libellés ont été créés sur votre boîte Gmail :
- `Yallah Services`
- `Yallah Services/Prospects B2B`
- `Yallah Services/Demandes B2C`
- `Yallah Services/Candidatures EMP`
- `Yallah Services/Refus - Ne plus contacter`

### Comment enregistrer un email reçu dans l'application web
Dans **Conversations → `+ Importer un email reçu`** (ou en CLI `python3 manage.py email-ingest`) :
1. Un **STOP / demande de retrait** inscrit immédiatement l'adresse au registre des refus et bloque tout futur contact.
2. Une **réponse d'un prospect connu** s'ajoute automatiquement à sa chronologie omnicanale.
3. Un email mentionnant une référence d'annonce ouverte (ex. `EMP-001`) crée une **candidature à traiter** liée au poste.
4. Tout autre email arrive dans la file **`À qualifier`** sans créer d'autorisation marketing.

---

## 2. Cadrage de l'offre commerciale employeur (à figer avant le 1er appel)

Conformément à l'**article 480 du Code du travail** (`POLITIQUE_FRAIS = "aucun"`), **aucun frais n'est demandé aux candidats**. Le modèle économique repose exclusivement sur la facturation côté client (entreprise B2B ou particulier employeur B2C).

### Grille de décision interne à remplir par la direction
> ⚠️ *Tant que ces montants ne sont pas arrêtés par vous, ne citez aucun tarif dans les messages de prise de contact (le garde-fou les bloque volontairement).*

| Format de besoin | Cible | Modèle de facturation à fixer | Conditions de règlement & suivi |
|---|---|---|---|
| **Poste permanent** | Hôtel, restaurant, famille | Forfait fixe de recherche **ou** % du salaire mensuel/annuel convenu | À définir (ex. acompte commande / solde démarrage) |
| **Besoin temporaire** | Surcroît saisonnier, remplacement congé | Forfait de mise en relation selon durée | À définir par devis signé (`Propositions` dans le CRM) |
| **Renfort journalier / extra** | Séminaire, mariage, traiteur, fin de chantier | Forfait par intervenant / journée | À définir par bon d'accord avant démarrage |

### Les 6 questions de qualification au 1er échange client (pour créer la fiche `besoins_emploi`)
Chaque information chiffrée saisie dans **Offres d'emploi** exige une **source explicite** (ex. *« Appel M. X, Directeur Exploitation, 24/10/2026 »*) :
1. **Métier exact** (`MEN`, `SRV`, `PLG`, `CUI`, `NET`, `GAR`, `NOU`, `CHA`, `AGE`, `COM`, `PON`) et **nombre de personnes**.
2. **Format souhaité** : `permanent`, `temporaire` ou `renfort journalier` *(ne jamais qualifier CDI/CDD sans confirmation écrite de l'employeur)*.
3. **Lieu précis** : ville + quartier/établissement.
4. **Horaires / jours de présence** *(noter qui les a communiqués et quand)*.
5. **Rémunération proposée par l'employeur** *(noter qui l'a communiquée et quand ; sinon l'annonce indiquera honnêtement « non communiquée dans cette annonce »)*.
6. **Date souhaitée de démarrage** et **interlocuteur décideur** (Direction / Exploitation / RH).

---

## 3. Pilote B2B — Lot Prioritaire Jour 1 (Phase 1 : 12 Niveau A + 3 Niveau B)

Toutes les fiches étant datées du `2026-10-21`, elles sont en statut `A ACTUALISER`.
**Procédure du matin (15 min) :**
1. Cliquez chaque lien officiel ci-dessous pour vérifier que le numéro/email affiché n'a pas changé.
2. Cochez « ✓ Source et contact revérifiés » dans l'application web **ou** lancez la commande CLI d'estampillage ci-dessous.
3. Contactez manuellement (max 15/jour) et notez le retour dans **Pipeline commercial** / **Conversations**.

### A. Les 8 cibles « Score 10/10 · Niveau A · Zone Phase 1 » (à contacter en premier)

| # | Réf | Établissement | Ville / Zone | Contact publié à revérifier | Source officielle | Angle d'approche recommandé |
|---|---|---|---|---|---|---|
| 1 | `B2B-024` | **La Plaza de Bouskoura** | Bouskoura (Ville Verte) | `+212 661 71 73 54` · `contact@laplazadebouskoura.com` | [Ouvrir](https://www.laplazadebouskoura.com/contacts/) | Entretien parties communes + passerelle vers enseignes du centre |
| 2 | `B2B-001` | **Idou Anfa Hôtel & Spa** | Casablanca (Anfa) | `+212 522 20 02 35` · `reservation@hotelidouanfa.com` | [Ouvrir](https://hotelidouanfacasablanca.com/contact) | Entrer par le pôle **Banquet / Séminaire** (renforts salle, plonge, chambres) |
| 3 | `B2B-003` | **Le Casablanca Hôtel** | Casablanca (Anfa) | `+212 522 64 97 97` · `resa@lecasablanca-hotel.com` | [Ouvrir](https://www.lecasablanca-hotel.com/) | Hôtel 68 chambres à taille humaine : demander l'exploitation / gouvernante |
| 4 | `B2B-018` | **Dar Challa** | Marrakech (Palmeraie) | `+212 707 29 67 70` · `constance@dar-challa.com` | [Ouvrir](https://www.dar-challa.com/) | Villa d'hôtes 8 chambres : personnel polyvalent maison + cuisine |
| 5 | `B2B-019` | **Hivernage Hôtel & Spa** | Marrakech (Hivernage) | `+212 524 42 41 00` · `reservation@hivernage-hotel.com` | [Ouvrir](https://www.hivernage-hotel.com/en/write-us/) | Approche groupe (couvre aussi *Riad Marrakech by Hivernage* `B2B-020`) |
| 6 | `B2B-022` | **Maison Ayda** | Marrakech (Palmeraie) | `+33 6 58 60 22 64` · `rubenmameri05@gmail.com` | [Ouvrir](https://www.maisonayda.com/contact) | Numéro français : privilégier email ou WhatsApp sur horaires ouvrés |
| 7 | `B2B-012` | **Atlantic Hôtel Agdal** | Rabat (Agdal) | `+212 537 27 33 00` *(pas d'email valide)* | [Ouvrir](https://atlanticagdal.com/en/contact/) | Appel téléphonique uniquement (email du site en domaine de test) |
| 8 | `B2B-013` | **Gardenia Boutique Hôtel** | Rabat (Agdal) | `+212 537 77 76 00` · `contact@gardeniarabat.com` | [Ouvrir](https://gardeniarabat.com/en/access-contact/) | Meilleur point d'entrée vérifié sur Rabat Agdal (chambres & réception) |

### B. Les 4 autres cibles « Niveau A · Casablanca (Traiteurs, Nettoyage, Chantier) »

| # | Réf | Établissement | Segment | Contact publié à revérifier | Source officielle | Point d'attention |
|---|---|---|---|---|---|---|
| 9 | `B2B-009` | **Le Prunier Traiteur** | Événementiel (Maârif) | `+212 661 13 46 51` · `contact@lepruniertraiteur.ma` | [Ouvrir](https://www.lepruniertraiteur.ma/) | Forte demande en extras service & plonge le week-end |
| 10 | `B2B-010` | **Rahal Maître Traiteur** | Événementiel (Maârif) | `+212 522 25 25 13` · `contact@rahalmaitretraiteur.com` | [Ouvrir](https://rahalmaitretraiteur.com/fr/contact/) | Opère Casa/Rabat/Marrakech — *ne jamais reprendre leur délai 48h* |
| 11 | `B2B-006` | **I-Klean** | Société de nettoyage | `+212 522 22 47 05` · `contact@i-klean.ma` | [Ouvrir](https://iklean.ma/) | Angle **sous-traitance / renfort ponctuel d'agents** |
| 12 | `B2B-007` | **SBTH** | Construction | `+212 522 48 10 89` | [Ouvrir](https://www.sbth.ma/en/contact) | **Appeler uniquement** (ne pas utiliser leur formulaire web) |

### C. Complément à 15 pour le Jour 1 (3 cibles « Score 9/10 · Niveau B » à reconfirmer sur page officielle)

| # | Réf | Établissement | Ville / Zone | Contact vu en extrait (à confirmer) | Source officielle |
|---|---|---|---|---|---|
| 13 | `B2B-004` | **Boutique Hôtel Gauthier** | Casablanca (Gauthier) | `+212 522 22 32 24` · `contact@hotelgauthier.com` | [Ouvrir](https://hotelgauthier.com/) |
| 14 | `B2B-002` | **Le Palace d'Anfa** | Casablanca (Anfa) | `+212 522 95 42 00` · `reservation@lepalacedanfa.com` | [Ouvrir](https://www.lepalacedanfa.com/index.html) |
| 15 | `B2B-015` | **Afrah Ryad Traiteur** | Rabat (Hay Riad) | `+212 537 71 07 87` · `contact@afrahryadtraiteur.com` | [Ouvrir](https://web.facebook.com/ryadtraiteur/) |

### Commande CLI une fois ces fiches vérifiées visuellement par vous :
```bash
# 1. Estampiller uniquement les références dont le contact est toujours identique :
python3 yallah_messages.py --verifie B2B-024 B2B-001 B2B-003 B2B-018 B2B-019 B2B-022 B2B-012 B2B-013 B2B-009 B2B-010 B2B-006 B2B-007

# 2. Générer la file d'envoi manuelle avec votre prénom signataire :
python3 yallah_messages.py --prenom "VotrePrenom" --langue fr --markdown file_envoi.md
```
*(Si vous travaillez dans l'interface web, utilisez `python3 manage.py export-json --dir ./export` pour répercuter vos mises à jour et refus SQLite vers les JSON CLI.)*

---

## 4. Kit d'Acquisition Entrante B2C — Phase 1 (10 publications prêtes & contrôlées)

Puisque la recherche d'annonces publiques B2C ne donne aucun numéro direct exploitable (voir `MESSAGES_PROSPECTION.md` §7), **la priorité B2C consiste à faire venir les familles à vous** via des publications locales associées aux liens WhatsApp préremplis de la matrice (`yallah_b2c.py`).

Tous les textes ci-dessous ont été passés au garde-fou automatique `verifier_contenu()` : **0 alerte** (aucun prix, délai, garantie, vérification annoncée ni numéro dans le corps du texte ; seul le site officiel `https://yallahservices-one.vercel.app` est autorisé). Ajoutez le lien `wa.me` correspondant et/ou le site officiel `https://yallahservices-one.vercel.app` en bouton / bio / premier commentaire.

### 1. Casablanca — Anfa · Femme de ménage (`CAS-ANF-MEN` · Instagram / Facebook · Français)
> Vous habitez du côté d'Anfa à Casablanca et vous cherchez une femme de ménage selon le rythme de votre foyer (permanent, temporaire ou renfort ponctuel) ?
> Yallah Services vous accompagne dans la recherche et la mise en relation de personnel de maison adapté à votre demande.
> Découvrez nos services sur https://yallahservices-one.vercel.app ou écrivez-nous directement via notre lien WhatsApp !
> `#Casablanca` `#Anfa` `#MaisonCasablanca` `#YallahServices`
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp traçable :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20femme%20de%20m%C3%A9nage%20%28Anfa%2C%20Casablanca%29.%20R%C3%A9f.%20CAS-ANF-MEN`

### 2. Casablanca — CFC & Californie · Nounou / Garde d'enfants (`CAS-CFC-NOU` · Instagram / Groupes quartier · Français)
> Familles de Casa Finance City et Californie : vous recherchez une nounou pour la garde de vos enfants, en besoin permanent, temporaire ou ponctuel ?
> Yallah Services organise la recherche et la mise en relation de personnel familial selon vos critères et vos horaires.
> Consultez https://yallahservices-one.vercel.app ou cliquez sur notre lien WhatsApp pour nous partager votre recherche !
> `#Casablanca` `#CasaFinanceCity` `#CalifornieCasablanca` `#GardeEnfants` `#YallahServices`
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp CFC :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20nounou%20/%20garde%20d%27enfants%20%28CFC%2C%20Casablanca%29.%20R%C3%A9f.%20CAS-CFC-NOU`
- **Lien WhatsApp Californie :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20nounou%20/%20garde%20d%27enfants%20%28Californie%2C%20Casablanca%29.%20R%C3%A9f.%20CAS-CAL-NOU`

### 3. Casablanca — Gauthier · Femme de ménage (`CAS-GAU-MEN` · TikTok / Reels · Darija)
> Saken f Gauthier f Casa w katqelleb 3la mra dyal chghol l dar, b chkel da2im wla مؤقت wla nhar b nhar ?
> Yallah Services kat3awnek f lba7t w rabt m3a nass li ynasbo talab dyalek b kol bassata.
> Chouf khadamatna 3la https://yallahservices-one.vercel.app wla cliquez 3la lien WhatsApp f bio !
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp traçable :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20femme%20de%20m%C3%A9nage%20%28Gauthier%2C%20Casablanca%29.%20R%C3%A9f.%20CAS-GAU-MEN`

### 4. Bouskoura — Ville Verte · Ménage & Nounou (`BSK-VVE-MEN` / `BSK-VVE-NOU` · Facebook / WhatsApp · Français)
> Résidents de Bouskoura Ville Verte : besoin d'une femme de ménage, d'une nounou ou d'une cuisinière à domicile, en format permanent ou ponctuel ?
> Yallah Services écoute votre demande et assure la recherche ainsi que la mise en relation de personnel pour votre foyer.
> Découvrez nos services sur https://yallahservices-one.vercel.app ou contactez-nous via le lien WhatsApp ci-dessous !
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp Ménage :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20femme%20de%20m%C3%A9nage%20%28Ville%20Verte%2C%20Bouskoura%29.%20R%C3%A9f.%20BSK-VVE-MEN`
- **Lien WhatsApp Nounou :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20nounou%20/%20garde%20d%27enfants%20%28Ville%20Verte%2C%20Bouskoura%29.%20R%C3%A9f.%20BSK-VVE-NOU`

### 5. Rabat — Hay Riad · Nounou / Garde d'enfants (`RAB-HRI-NOU` · Instagram · Français)
> Parents à Hay Riad (Rabat) : vous cherchez une nounou pour accompagner le quotidien de votre famille ?
> En format permanent, temporaire ou renfort ponctuel, Yallah Services vous accompagne dans la recherche et la mise en relation.
> Plus d'informations sur https://yallahservices-one.vercel.app ou écrivez-nous sur WhatsApp via le lien dédié !
> `#Rabat` `#HayRiad` `#FamilleRabat` `#YallahServices`
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp traçable :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20nounou%20/%20garde%20d%27enfants%20%28Hay%20Riad%2C%20Rabat%29.%20R%C3%A9f.%20RAB-HRI-NOU`

### 6. Rabat — Souissi · Chauffeur (`RAB-SOU-CHA` · LinkedIn / Facebook · Français)
> À Rabat Souissi et Les Ambassadeurs, vous souhaitez recruter un chauffeur privé en besoin permanent, temporaire ou journalier ?
> Yallah Services structure votre recherche et vous met en relation selon vos besoins réels.
> Présentation sur https://yallahservices-one.vercel.app et prise de contact directe via notre lien WhatsApp !
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp traçable :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20chauffeur%20%28Souissi%2C%20Rabat%29.%20R%C3%A9f.%20RAB-SOU-CHA`

### 7. Rabat — Agdal · Aide aux personnes âgées (`RAB-AGD-AGE` · Facebook / Arabe)
> للعائلات في أكدال بالرباط: هل تبحثون عن مساعدة لكبار السن بشكل دائم أو مؤقت حسب احتياج أسرتكم؟
> تواكبكم Yallah Services في البحث والربط مع المستخدمين وفق طلبكم بكل عناية ووضوح.
> اطلعوا على خدماتنا عبر https://yallahservices-one.vercel.app أو تواصلوا معنا مباشرة عبر رابط واتساب المرفق!
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp traçable :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20aide%20aux%20personnes%20%C3%A2g%C3%A9es%20%28Agdal%2C%20Rabat%29.%20R%C3%A9f.%20RAB-AGD-AGE`

### 8. Marrakech — Palmeraie · Cuisinière à domicile (`MAR-PAL-CUI` · Instagram · Français)
> Résidences et villas du secteur Palmeraie à Marrakech : vous cherchez une cuisinière à domicile, à l'année ou pour un besoin temporaire ?
> Yallah Services assure la recherche et la mise en relation de personnel de maison selon vos attentes.
> Consultez https://yallahservices-one.vercel.app ou envoyez-nous votre demande via notre lien WhatsApp !
> `#Marrakech` `#Palmeraie` `#MaisonMarrakech` `#YallahServices`
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp traçable :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20cuisini%C3%A8re%20%C3%A0%20domicile%20%28Palmeraie%2C%20Marrakech%29.%20R%C3%A9f.%20MAR-PAL-CUI`

### 9. Marrakech — Hivernage · Ménage & Nettoyage ponctuel (`MAR-HIV-MEN` · TikTok / Instagram · Darija)
> F Marrakech جهة l'Hivernage w bghiti mra dyal chghol wla tnadif mawqati l dar ?
> Yallah Services katwakbek f lba7t w rabt 3la 7ssab talab dyalek, b chkel da2im wla mawqati.
> Chouf https://yallahservices-one.vercel.app wla dkhel l lien WhatsApp w 9ol lina chno katqelleb 3lih !
- **Site officiel :** `https://yallahservices-one.vercel.app`
- **Lien WhatsApp traçable :** `https://wa.me/212691733585?text=Bonjour%2C%20je%20cherche%20%3A%20femme%20de%20m%C3%A9nage%20%28Hivernage%2C%20Marrakech%29.%20R%C3%A9f.%20MAR-HIV-MEN`
