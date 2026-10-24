"""Gestion serveur : aucun secret sur la ligne de commande ou dans les logs."""
import argparse
import getpass
import json
import os
import sqlite3
from pathlib import Path

import access
import operations
import webapp


def main():
    parser=argparse.ArgumentParser(description='Administration Yallah (comptes, sauvegarde, restauration)')
    sub=parser.add_subparsers(dest='command',required=True)
    user=sub.add_parser('user-add');user.add_argument('username');user.add_argument('--role',choices=access.ROLES,default='lecture')
    sub.add_parser('backup')
    restore=sub.add_parser('restore');restore.add_argument('file');restore.add_argument('--confirm',action='store_true')
    export_cmd=sub.add_parser('export-json');export_cmd.add_argument('--dir',required=True);export_cmd.add_argument('--overwrite',action='store_true')
    ingest=sub.add_parser('email-ingest');ingest.add_argument('--from',dest='sender_email',required=True);ingest.add_argument('--name',default='');ingest.add_argument('--subject',required=True);ingest.add_argument('--body',required=True);ingest.add_argument('--id',dest='message_id',default='')
    sub.add_parser('check')
    args=parser.parse_args()
    if args.command=='restore':
        if not args.confirm: parser.error('Restauration destructive : sauvegarder la base actuelle et ajouter --confirm')
        source=Path(args.file).resolve()
        if not source.is_file() or source==webapp.DB.resolve(): parser.error('Fichier de sauvegarde distinct requis')
        lock=webapp.server_lock()
        temporary=Path(str(webapp.DB)+'.restoring')
        try:
            with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as src:
                if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or not src.execute("SELECT 1 FROM sqlite_master WHERE name='records'").fetchone():
                    raise ValueError('Sauvegarde SQLite Yallah valide requise')
                with sqlite3.connect(temporary) as target: src.backup(target)
            temporary.chmod(0o600)
            os.replace(temporary,webapp.DB)
            print('Base restaurée. Redémarrer le serveur pour appliquer les migrations.')
        finally:
            if temporary.exists(): temporary.unlink()
            lock.close()
        return
    # Une commande de maintenance ne marque pas les envois du serveur comme interrompus.
    # La création du premier compte doit rester possible avant le démarrage production.
    production=os.environ.pop('YALLAH_ENV',None)
    try: webapp.initialize(recover=False)
    finally:
        if production is not None: os.environ['YALLAH_ENV']=production
    if args.command=='user-add':
        password=getpass.getpass('Mot de passe (16 caractères minimum) : ')
        if password!=getpass.getpass('Confirmation : '): raise ValueError('Confirmation différente')
        access.add_user(args.username,password,args.role)
        with webapp.connect() as con: operations.audit(con,'cli','compte_configure','users',detail=args.username+' / '+args.role)
        print('Compte enregistré ; mot de passe non affiché.')
    elif args.command=='backup': print(json.dumps(operations.backup(webapp.DB,'cli'),ensure_ascii=False))
    elif args.command=='export-json': print(json.dumps(operations.export_json(args.dir,args.overwrite,'cli'),ensure_ascii=False))
    elif args.command=='email-ingest': print(json.dumps(operations.execute('email_ingest',{'sender_email':args.sender_email,'sender_name':args.name,'subject':args.subject,'body':args.body,'message_id':args.message_id},'cli'),ensure_ascii=False))
    else:
        with webapp.connect() as con:
            print('Intégrité :',con.execute('PRAGMA integrity_check').fetchone()[0])
            print('Version :',con.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0])


if __name__=='__main__':
    main()
