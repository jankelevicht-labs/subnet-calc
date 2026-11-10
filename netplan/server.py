# -*- coding: utf-8 -*-
"""NetPlan Studio — serveur HTTP local et API JSON (bibliothèque standard uniquement).

* API : ``POST /api/cidr|vlsm|decoupage|appartenance|chevauchement`` (corps JSON,
  réponse ``application/json; charset=utf-8``). Entrée invalide → 400
  ``{"erreur": "<message en français>"}``, route inconnue → 404, méthode non
  prévue → 405, jamais de trace Python dans une réponse.
* Exports : ``POST /api/export/csv|json|routeros`` (même corps que ``/api/vlsm``), réponse en
  pièce jointe (``Content-Disposition: attachment``) générée par :mod:`netplan.export`.
* Statiques : fichiers de ``netplan/static/`` uniquement (liste blanche
  d'extensions, aucune traversée, aucun listing de répertoire).
* Toutes les réponses portent les en-têtes de sécurité (CSP stricte, nosniff,
  Referrer-Policy: no-referrer).
* Le serveur n'émet aucune requête sortante.
"""

import json
import os
import socket
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from . import calc, export

TAILLE_MAX_CORPS = 64 * 1024          # 64 Kio
TAILLE_MAX_DRAIN = 1024 * 1024        # octets lus et jetés avant de répondre à un corps trop gros
DELAI_SOCKET = 10                     # secondes (client lent / connexion muette)
DELAI_DRAIN = 0.5                     # secondes d'inactivité tolérées en jetant un corps trop gros
DOSSIER_STATIQUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

TYPES_STATIQUES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

EN_TETES_SECURITE = (
    ("Content-Security-Policy",
     "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
     "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)

MESSAGES_HTTP = {
    400: "Requête invalide.",
    404: "Ressource introuvable.",
    405: "Méthode non autorisée pour cette ressource.",
    408: "Délai dépassé : la requête n'a pas été reçue à temps.",
    414: "Adresse de requête trop longue.",
    431: "En-têtes de requête trop volumineux.",
    500: "Erreur interne du serveur.",
    501: "Méthode non prise en charge.",
    505: "Version HTTP non prise en charge.",
}


class ErreurRequete(Exception):
    """Erreur HTTP à renvoyer au client (message en français, sans trace)."""

    def __init__(self, statut, message, entetes=()):
        super().__init__(message)
        self.statut = statut
        self.message = message
        self.entetes = tuple(entetes)


# --------------------------------------------------------------------------- #
# Routes de l'API : nom de route → (fonction de calcul, champs requis, champs optionnels)
# --------------------------------------------------------------------------- #

ROUTES_API = {
    "/api/cidr": (calc.cidr_info, ("cidr",), ()),
    "/api/vlsm": (calc.vlsm, ("parent", "besoins"), ()),
    "/api/decoupage": (calc.decoupage, ("reseau",), ("n", "prefixe")),
    "/api/appartenance": (calc.appartenance, ("ip", "reseau"), ()),
    "/api/chevauchement": (calc.chevauchement, ("a", "b"), ()),
}


# Routes d'export : même corps que /api/vlsm ; réponse en pièce jointe générée par netplan.export.
ROUTES_EXPORT = {f"/api/export/{nom}": nom for nom in export.FORMATS}


def _rejeter_constante(nom):
    raise ValueError(nom)


def decoder_json(octets):
    """Décode un corps JSON qui doit être un objet ; lève ErreurRequete (400) sinon."""
    try:
        texte = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise ErreurRequete(400, "Le corps de la requête n'est pas du texte UTF-8 valide.") from None
    if not texte.strip():
        raise ErreurRequete(400, "Le corps de la requête est vide : un objet JSON est attendu.")
    try:
        donnees = json.loads(texte, parse_constant=_rejeter_constante)
    except RecursionError:
        raise ErreurRequete(400, "JSON invalide : imbrication trop profonde.") from None
    except ValueError:
        raise ErreurRequete(400, "JSON mal formé : le corps de la requête n'est pas un JSON valide.") from None
    if not isinstance(donnees, dict):
        raise ErreurRequete(400, "JSON invalide : un objet {\"champ\": valeur} est attendu.")
    if _contient_surrogate(donnees):
        raise ErreurRequete(
            400, "Texte invalide : le JSON contient un caractère Unicode isolé (surrogate) "
                 "qui ne peut pas être encodé en UTF-8.")
    return donnees


def _contient_surrogate(donnees):
    """Vrai si une clé ou une valeur texte contient un surrogate Unicode isolé (U+D800 à U+DFFF).

    ``json.loads`` accepte ``"\\ud800"`` ; ce texte ne s'encode pas en UTF-8 et ferait échouer
    l'envoi de la réponse. Parcours itératif (pas de récursion Python)."""
    pile = [donnees]
    while pile:
        valeur = pile.pop()
        if isinstance(valeur, str):
            try:
                valeur.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(valeur, dict):
            pile.extend(valeur.keys())
            pile.extend(valeur.values())
        elif isinstance(valeur, list):
            pile.extend(valeur)
    return False


def executer_route(chemin, donnees):
    """Valide les champs de ``donnees`` puis appelle la fonction de calcul de ``chemin``."""
    fonction, requis, optionnels = ROUTES_API[chemin]
    for champ in requis:
        if champ not in donnees:
            raise ErreurRequete(400, f"Champ manquant : « {champ} » est obligatoire.")
    arguments = {champ: donnees[champ] for champ in requis + optionnels if champ in donnees}
    try:
        return fonction(**arguments)
    except calc.NetplanError as exc:
        raise ErreurRequete(400, str(exc)) from None


class Gestionnaire(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"      # une requête par connexion : pas de corps résiduel à gérer
    timeout = DELAI_SOCKET
    server_version = "NetPlan"
    sys_version = ""

    # -- en-têtes / réponses ------------------------------------------------

    def version_string(self):
        return self.server_version

    def _envoyer(self, statut, corps, type_contenu, entetes=(), avec_corps=True):
        if self.request_version == "HTTP/0.9":      # http.server n'enverrait alors aucun en-tête
            self.request_version = "HTTP/1.0"
        self.send_response(statut)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(corps)))
        for nom, valeur in EN_TETES_SECURITE:
            self.send_header(nom, valeur)
        for nom, valeur in entetes:
            self.send_header(nom, valeur)
        self.send_header("Connection", "close")
        self.end_headers()
        if avec_corps and self.command != "HEAD":
            self.wfile.write(corps)
        self.close_connection = True

    def _envoyer_json(self, statut, donnees, entetes=(), avec_corps=True):
        try:
            corps = json.dumps(donnees, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError:
            # Défense en profondeur : une réponse doit toujours être encodable (surrogate isolé
            # échappé en \udXXX plutôt que connexion fermée sans réponse).
            corps = json.dumps(donnees, ensure_ascii=True).encode("ascii")
        self._envoyer(statut, corps, "application/json; charset=utf-8",
                      (("Cache-Control", "no-store"),) + tuple(entetes), avec_corps)

    def _envoyer_erreur(self, statut, message, entetes=()):
        self._envoyer_json(statut, {"erreur": message}, entetes)

    def send_error(self, code, message=None, explain=None):
        """Remplace la page d'erreur HTML de http.server par une erreur JSON sans détail technique."""
        texte = MESSAGES_HTTP.get(int(code))
        if texte is None:
            texte = HTTPStatus(code).phrase if code in HTTPStatus._value2member_map_ else "Erreur."
        try:
            self._envoyer_erreur(int(code), texte)
        except OSError:
            self.close_connection = True

    def log_message(self, format, *args):
        if getattr(self.server, "journal", True):
            sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    # -- aiguillage ---------------------------------------------------------

    def _chemin(self):
        cible = self.path
        for sep in ("?", "#"):
            cible = cible.split(sep, 1)[0]
        return cible

    def _traiter(self):
        try:
            chemin = self._chemin()
            methode = self.command
            if chemin in ROUTES_API:
                if methode != "POST":
                    raise ErreurRequete(405, MESSAGES_HTTP[405], (("Allow", "POST"),))
                self._api(chemin)
            elif chemin in ROUTES_EXPORT:
                if methode != "POST":
                    raise ErreurRequete(405, MESSAGES_HTTP[405], (("Allow", "POST"),))
                self._exporter(ROUTES_EXPORT[chemin])
            elif chemin.startswith("/api/") or chemin == "/api":
                raise ErreurRequete(404, MESSAGES_HTTP[404])
            else:
                if methode not in ("GET", "HEAD"):
                    if self._fichier_statique(chemin) is None:
                        raise ErreurRequete(404, MESSAGES_HTTP[404])
                    raise ErreurRequete(405, MESSAGES_HTTP[405], (("Allow", "GET, HEAD"),))
                self._statique(chemin)
        except ErreurRequete as exc:
            self._envoyer_erreur(exc.statut, exc.message, exc.entetes)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, TimeoutError):
            self.close_connection = True
        except Exception:                                  # jamais de trace dans la réponse
            try:
                import traceback
                if getattr(self.server, "journal", True):
                    traceback.print_exc(file=sys.stderr)
                self._envoyer_erreur(500, MESSAGES_HTTP[500])
            except Exception:
                self.close_connection = True

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _traiter

    # -- API ----------------------------------------------------------------

    def _lire_corps(self):
        valeurs = self.headers.get_all("Content-Length") or []
        if self.headers.get("Transfer-Encoding") is not None:
            raise ErreurRequete(400, "Encodage de transfert non pris en charge : envoyez un en-tête Content-Length.")
        if not valeurs:
            raise ErreurRequete(400, "En-tête Content-Length manquant : la longueur du corps est obligatoire.")
        brut = valeurs[0].strip()
        if len(set(v.strip() for v in valeurs)) != 1 or not (brut.isascii() and brut.isdigit()) or len(brut) > 12:
            raise ErreurRequete(400, "En-tête Content-Length invalide : un entier positif est attendu.")
        longueur = int(brut)
        if longueur > TAILLE_MAX_CORPS:
            self._jeter_corps(longueur)
            raise ErreurRequete(400, f"Corps de requête trop volumineux : {TAILLE_MAX_CORPS // 1024} Kio au maximum.")
        corps = self.rfile.read(longueur) if longueur else b""
        if len(corps) < longueur:
            raise ErreurRequete(400, "Corps de requête incomplet : moins d'octets reçus que Content-Length.")
        return corps

    def _jeter_corps(self, longueur):
        """Lit (sans le garder) un corps trop gros pour que le client puisse lire la réponse 400."""
        restant = min(longueur, TAILLE_MAX_DRAIN)
        try:
            self.connection.settimeout(DELAI_DRAIN)      # un client qui n'envoie plus rien n'est pas attendu
            while restant > 0:
                morceau = self.rfile.read(min(restant, 65536))
                if not morceau:
                    break
                restant -= len(morceau)
        except (OSError, ValueError):
            pass

    def _api(self, chemin):
        donnees = decoder_json(self._lire_corps())
        self._envoyer_json(200, executer_route(chemin, donnees))

    def _exporter(self, format_):
        """Export d'un plan VLSM (même corps que /api/vlsm) en pièce jointe : csv, json ou routeros."""
        donnees = decoder_json(self._lire_corps())
        plan = executer_route("/api/vlsm", donnees)
        fonction, extension, type_contenu = export.FORMATS[format_]
        corps = fonction(plan).encode("utf-8")
        nom = export.nom_fichier(plan, extension)
        self._envoyer(200, corps, type_contenu, (
            ("Content-Disposition", f'attachment; filename="{nom}"'),
            ("Cache-Control", "no-store"),
        ))

    # -- statiques ----------------------------------------------------------

    def _fichier_statique(self, chemin):
        """Chemin absolu du fichier statique demandé, ou None (liste blanche stricte)."""
        racine = os.path.realpath(self.server.dossier_statique)
        if chemin == "/":
            segments = ["index.html"]
        else:
            segments = chemin[1:].split("/")
            if segments[0] == "static" and len(segments) > 1:
                segments = segments[1:]
        decodes = []
        for seg in segments:
            if not seg:
                return None
            seg = unquote(seg, errors="strict") if _decodable(seg) else None
            if (seg is None or seg in (".", "..") or seg.startswith(".")
                    or any(c in seg for c in ("/", "\\", "\x00", ":"))
                    or any(ord(c) < 32 or ord(c) == 127 for c in seg)):
                return None
            decodes.append(seg)
        extension = os.path.splitext(decodes[-1])[1].lower()
        if extension not in TYPES_STATIQUES:
            return None
        candidat = os.path.realpath(os.path.join(racine, *decodes))
        if os.path.commonpath([racine, candidat]) != racine or not os.path.isfile(candidat):
            return None
        return candidat

    def _statique(self, chemin):
        fichier = self._fichier_statique(chemin)
        if fichier is None:
            raise ErreurRequete(404, MESSAGES_HTTP[404])
        try:
            with open(fichier, "rb") as f:
                corps = f.read()
        except OSError:
            raise ErreurRequete(404, MESSAGES_HTTP[404]) from None
        type_contenu = TYPES_STATIQUES[os.path.splitext(fichier)[1].lower()]
        self._envoyer(200, corps, type_contenu, (("Cache-Control", "no-cache"),))


def _decodable(segment):
    try:
        unquote(segment, errors="strict")
        return True
    except UnicodeDecodeError:
        return False


class ServeurNetPlan(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, adresse, gestionnaire=Gestionnaire, *, dossier_statique=DOSSIER_STATIQUE, journal=True):
        self.dossier_statique = dossier_statique
        self.journal = journal
        if ":" in adresse[0]:
            self.address_family = socket.AF_INET6
        super().__init__(adresse, gestionnaire)

    def handle_error(self, request, client_address):
        # Pas de trace Python ; l'erreur n'atteint jamais le client.
        if self.journal:
            sys.stderr.write("Erreur de connexion avec %s\n" % (client_address[0],))


def creer_serveur(host="127.0.0.1", port=8080, *, dossier_statique=DOSSIER_STATIQUE, journal=True):
    """Crée (sans le démarrer) le serveur ; ``port=0`` choisit un port libre."""
    return ServeurNetPlan((host, port), dossier_statique=dossier_statique, journal=journal)
