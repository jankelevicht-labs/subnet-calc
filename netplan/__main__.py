# -*- coding: utf-8 -*-
"""Point d'entrée : ``python3 -m netplan --port 8080`` (écoute 127.0.0.1 par défaut)."""

import argparse
import ipaddress
import signal
import sys

from .server import creer_serveur


def _port(texte):
    try:
        valeur = int(texte)
    except ValueError:
        raise argparse.ArgumentTypeError(f"port invalide « {texte} » : un entier est attendu") from None
    if not 0 <= valeur <= 65535:
        raise argparse.ArgumentTypeError(f"port invalide {valeur} : il doit être compris entre 0 et 65535")
    return valeur


def _est_local(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv=None):
    analyseur = argparse.ArgumentParser(
        prog="python3 -m netplan",
        description="NetPlan Studio : atelier web local de plan d'adressage IPv4.")
    analyseur.add_argument("--host", default="127.0.0.1",
                           help="adresse d'écoute (défaut : 127.0.0.1, accès local uniquement)")
    analyseur.add_argument("--port", type=_port, default=8080, help="port d'écoute (défaut : 8080)")
    args = analyseur.parse_args(argv)

    try:
        serveur = creer_serveur(args.host, args.port)
    except OSError as exc:
        print(f"Impossible de démarrer le serveur sur {args.host}:{args.port} : {exc.strerror or exc}",
              file=sys.stderr)
        return 1

    if not _est_local(args.host):
        print(f"Attention : {args.host} n'est pas une adresse locale, le serveur est joignable depuis le réseau.",
              file=sys.stderr)

    def _arret(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _arret)
    host, port = serveur.server_address[:2]
    url_host = f"[{host}]" if ":" in host else host
    print(f"NetPlan Studio : http://{url_host}:{port}/ (Ctrl+C pour arrêter)", flush=True)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.", file=sys.stderr)
    finally:
        serveur.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
