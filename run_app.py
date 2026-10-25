"""Lanceur unifié de l'application Yallah.

Initialise les schémas historiques et les tables de qualité CRM avant de
servir l'interface HTTP. Utiliser ce fichier en développement et en production.
"""
from __future__ import annotations

import argparse
import os
from http.server import ThreadingHTTPServer

import crm_storage
import webapp


def main() -> None:
    parser = argparse.ArgumentParser(description="Serveur web Yallah Services")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    args = parser.parse_args()

    webapp.initialize()
    with webapp.connect() as connection:
        crm_storage.migrate(connection)

    server = ThreadingHTTPServer((args.host, args.port), webapp.Handler)
    print(f"Yallah Services disponible sur http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
