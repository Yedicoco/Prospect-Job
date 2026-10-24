# Moteur de qualité CRM

Le fichier `quality_engine.py` fournit des primitives métier autonomes pour
améliorer progressivement Prospect-Job sans modifier les interfaces actuelles.

## Capacités

| Fonction | Rôle |
|---|---|
| `normalize_contact` | Normalise email, téléphone et WhatsApp en conservant les trois canaux |
| `prospect_deduplication_key` | Produit une clé stable de rapprochement |
| `freshness_factor` | Calcule une confiance décroissante selon l'ancienneté |
| `score_prospect` | Calcule un score entre 0 et 100 avec raisons et avertissements |
| `validate_transition` | Bloque les transitions CRM incohérentes |
| `action_idempotency_key` | Empêche la création répétée d'une même action |
| `realized_roi` | Calcule le résultat sur les revenus effectivement reçus |
| `realized_mad_per_hour` | Calcule le revenu réel par heure opérateur |
| `validate_contact_record` | Retourne erreurs, avertissements et données normalisées |

## Principes

1. Le module ne réalise aucun envoi et ne modifie aucune base.
2. Une valeur absente n'est jamais inventée.
3. Une identité de contact est préférée au nom seul pour la déduplication.
4. Un opt-out doit toujours empêcher les actions sortantes.
5. Le scoring est explicable : il renvoie ses raisons et avertissements.
6. Le ROI réalisé utilise les encaissements, pas les montants simplement estimés.
7. Les fonctions sont conçues pour être appelées depuis la CLI, la webapp ou les
   futurs repositories SQLite.

## Exemple de validation

```python
from quality_engine import validate_contact_record

result = validate_contact_record({
    "email": "contact@example.com",
    "whatsapp": "0661887766",
})

if not result.valid:
    raise ValueError(" ; ".join(result.errors))

normalized_phone = result.normalized.whatsapp
```

## Exemple de scoring

```python
from datetime import date
from quality_engine import score_prospect

score = score_prospect(prospect, today=date.today())
print(score.total)
print(score.reasons)
print(score.warnings)
```

## Intégration progressive recommandée

1. Utiliser `validate_contact_record` avant les imports ou la préparation d'un
   message.
2. Enregistrer la clé retournée par `prospect_deduplication_key` dans le CRM.
3. Appeler `validate_transition` dans la fonction unique de changement d'état.
4. Enregistrer `action_idempotency_key` avant de créer une relance.
5. Afficher le détail du score dans le tableau de bord.
6. Ajouter ensuite les événements d'audit et les contraintes SQLite.

Cette première tranche reste volontairement additive : elle ne remplace pas les
fonctions existantes tant qu'une intégration et ses tests de caractérisation
n'ont pas été réalisées.
