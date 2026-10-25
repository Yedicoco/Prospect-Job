# Utiliser l'application Yallah Services

## Démarrage local

Depuis la racine du dépôt :

```bash
python3 run_app.py --port 8000
```

Puis ouvrir `http://127.0.0.1:8000`.

Sous Windows, utiliser `Lancer_Yallah.bat`. Sous macOS/Linux, utiliser
`Lancer_Yallah.command` après lui avoir donné le droit d'exécution.

Le lanceur initialise automatiquement les tables historiques ainsi que les
tables `audit_events` et `crm_idempotency`.

## Parcours opérateur

1. Ouvrir le tableau de bord.
2. Vérifier les fiches de la file du jour.
3. Contrôler la source, la date de vérification et le canal de contact.
4. Ouvrir la fiche prospect et préparer le message.
5. Envoyer manuellement depuis le canal choisi.
6. Enregistrer l'action ou la relance dans l'interface.
7. Suivre les tâches, opportunités et conversations.
8. Ajouter le temps passé et les encaissements réels pour calculer le ROI.

Les campagnes restent en simulation par défaut. Ne pas activer les envois réels
sans fournisseur configuré, autorisation vérifiée et consentement documenté.

## Administration

```bash
python3 manage.py user-add nom_utilisateur --role commercial
python3 manage.py check
python3 manage.py backup
```

## Déploiement Render

Le service démarre avec `run_app.py`, qui applique les migrations CRM avant de
lancer le serveur. Configurer un disque persistant pour `YALLAH_DB`, un mot de
passe administrateur fort et `YALLAH_ENABLE_LIVE=0` tant que les fournisseurs
sortants ne sont pas validés.

## Limites actuelles

Les nouvelles tables sont initialisées automatiquement. Les handlers CRM
historiques restent conservés ; leur branchement détaillé à chaque workflow
sera réalisé progressivement avec des tests HTTP dédiés, sans remplacement
aveugle de `operations.py`.
