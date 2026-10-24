#!/bin/sh
# Lanceur double-clic macOS / Linux — Yallah Services (sans ouvrir de terminal manuellement)
# Démarre l'ensemble de l'application unifiée (SQLite, CRM, file du jour, ROI, pages SEO /services)
# et ouvre automatiquement l'interface dans votre navigateur par défaut.

set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${YALLAH_PORT:-8000}"

if ! command -v python3 >/dev/null 2>&1; then
    MSG="Python 3 est requis pour lancer Yallah Services (https://www.python.org/downloads/)."
    if command -v osascript >/dev/null 2>&1; then
        osascript -e "display alert \"Yallah Services\" message \"$MSG\" as critical" >/dev/null 2>&1 || true
    fi
    echo "$MSG" >&2
    exit 1
fi

echo "Démarrage de Yallah Services sur http://127.0.0.1:${PORT} ..."
echo "Gardez cette fenêtre réduite pendant votre travail (Ctrl+C ou fermer pour arrêter)."
exec python3 webapp.py --port "$PORT" --open
