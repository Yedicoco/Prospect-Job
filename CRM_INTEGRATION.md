# Intégration progressive du moteur de qualité CRM

La façade `crm_quality.py` constitue le point d'entrée commun entre les
handlers de la webapp, les opérations CLI et le stockage SQLite.

## Pourquoi une façade

`operations.py` et `webapp.py` contiennent déjà des workflows historiques et
des interfaces publiques couvertes par les tests. La façade évite de dupliquer
les nouvelles règles dans chaque route et permet une migration progressive.

## Pipeline recommandé

```text
requête CRM
  -> prepare_action(...)
  -> vérifier PreparedAction.allowed
  -> vérifier l'idempotency_key en base
  -> créer l'action ou la tâche dans une transaction
  -> enregistrer transition_event(...)
  -> exécuter uniquement l'action validée
```

`prepare_action` ne réalise aucun envoi et ne modifie aucune donnée.

## Règles garanties

- email, téléphone et WhatsApp sont normalisés avant utilisation ;
- une fiche sans canal de contact est refusée ;
- une fiche `opt_out` est toujours bloquée pour une action sortante ;
- le score est calculé avec raisons et avertissements ;
- la clé d'idempotence est stable pour un même dossier, une même action et une
  même étape ;
- les transitions invalides sont refusées ;
- l'audit est produit avec des paramètres SQL séparés, jamais par interpolation.

## Intégration SQLite

La table d'audit pourra être créée par une migration dédiée :

```sql
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
```

La prochaine tranche pourra brancher cette façade sur le point précis de
création des opérations et des relances, après vérification du schéma SQLite
actuel.
