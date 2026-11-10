# -*- coding: utf-8 -*-
"""Tests de l'API JSON et des statiques de NetPlan Studio (serveur réel sur un port libre)."""

import http.client
import json
import os
import socket
import threading

import pytest

from netplan import calc
from netplan.server import TAILLE_MAX_CORPS, creer_serveur

REPERTOIRE_PROJET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #

class _Lance:
    def __init__(self, serveur):
        self.serveur = serveur
        self.host, self.port = serveur.server_address[:2]
        self.fil = threading.Thread(target=serveur.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.fil.start()

    def arreter(self):
        self.serveur.shutdown()
        self.serveur.server_close()
        self.fil.join(timeout=5)


@pytest.fixture(scope="module")
def srv():
    lance = _Lance(creer_serveur("127.0.0.1", 0, journal=False))
    yield lance
    lance.arreter()


@pytest.fixture
def srv_statique(tmp_path):
    racine = tmp_path / "static"
    racine.mkdir()
    (racine / "index.html").write_text("<!DOCTYPE html><title>t</title>", encoding="utf-8")
    (racine / "app.js").write_text("console.log('ok');", encoding="utf-8")
    (racine / "style.css").write_text("body{margin:0}", encoding="utf-8")
    (racine / "notes.txt").write_text("interdit", encoding="utf-8")
    (racine / "sous").mkdir()
    (racine / "sous" / "page.html").write_text("<p>sous</p>", encoding="utf-8")
    (tmp_path / "secret.html").write_text("SECRET", encoding="utf-8")
    try:
        (racine / "lien.html").symlink_to(tmp_path / "secret.html")
    except OSError:
        pass
    lance = _Lance(creer_serveur("127.0.0.1", 0, dossier_statique=str(racine), journal=False))
    yield lance
    lance.arreter()


def requete(lance, methode, chemin, corps=None, entetes=None):
    """Renvoie (statut, en-têtes dict en minuscules, octets du corps)."""
    cnx = http.client.HTTPConnection(lance.host, lance.port, timeout=10)
    try:
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps)
        if isinstance(corps, str):
            corps = corps.encode("utf-8")
        cnx.request(methode, chemin, body=corps, headers=entetes or {})
        rep = cnx.getresponse()
        return rep.status, {k.lower(): v for k, v in rep.getheaders()}, rep.read()
    finally:
        cnx.close()


def post(lance, chemin, donnees):
    statut, entetes, corps = requete(lance, "POST", chemin, donnees, {"Content-Type": "application/json"})
    return statut, entetes, json.loads(corps.decode("utf-8"))


def brut(lance, octets, demi_fermeture=True):
    """Envoie des octets bruts et renvoie (statut, en-têtes, corps) de la réponse."""
    with socket.create_connection((lance.host, lance.port), timeout=10) as s:
        s.sendall(octets)
        if demi_fermeture:
            s.shutdown(socket.SHUT_WR)
        donnees = b""
        while True:
            try:
                morceau = s.recv(65536)
            except ConnectionResetError:
                break
            if not morceau:
                break
            donnees += morceau
    tete, _, corps = donnees.partition(b"\r\n\r\n")
    lignes = tete.decode("iso-8859-1").split("\r\n")
    statut = int(lignes[0].split()[1])
    entetes = {l.split(":", 1)[0].lower(): l.split(":", 1)[1].strip() for l in lignes[1:] if ":" in l}
    return statut, entetes, corps


def verifier_entetes_securite(entetes):
    csp = entetes["content-security-policy"]
    directives = {d.strip().split(" ", 1)[0]: d.strip().split(" ", 1)[1] for d in csp.split(";") if " " in d.strip()}
    assert directives["default-src"] in ("'none'", "'self'")
    assert directives["script-src"] == "'self'"
    assert directives["style-src"] == "'self'"
    assert directives["base-uri"] == "'none'"
    assert directives["frame-ancestors"] == "'none'"
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert entetes["x-content-type-options"] == "nosniff"
    assert entetes["referrer-policy"] == "no-referrer"
    assert "python" not in entetes.get("server", "").lower()


def verifier_erreur_json(statut, entetes, donnees, attendu):
    assert statut == attendu
    assert entetes["content-type"] == "application/json; charset=utf-8"
    assert set(donnees) == {"erreur"}
    assert isinstance(donnees["erreur"], str) and donnees["erreur"]
    assert "Traceback" not in donnees["erreur"] and 'File "' not in donnees["erreur"]
    verifier_entetes_securite(entetes)


# --------------------------------------------------------------------------- #
# Cas nominaux de l'API
# --------------------------------------------------------------------------- #

def test_cidr(srv):
    statut, entetes, donnees = post(srv, "/api/cidr", {"cidr": "192.168.1.10/24"})
    assert statut == 200
    assert entetes["content-type"] == "application/json; charset=utf-8"
    assert donnees == calc.cidr_info("192.168.1.10/24")
    assert donnees["reseau"] == "192.168.1.0/24" and donnees["nb_hotes"] == 254
    verifier_entetes_securite(entetes)


def test_vlsm_exemple_du_cahier_des_charges(srv):
    corps = {"parent": "192.168.10.0/24",
             "besoins": [{"nom": "Voix", "hotes": 50}, {"nom": "Data", "hotes": 20}, {"nom": "Admin", "hotes": 10}]}
    statut, entetes, donnees = post(srv, "/api/vlsm", corps)
    assert statut == 200
    assert [a["reseau"] for a in donnees["allocations"]] == ["192.168.10.0/26", "192.168.10.64/27", "192.168.10.96/28"]
    assert donnees == calc.vlsm(corps["parent"], corps["besoins"])
    assert donnees["libres"] == ["192.168.10.112/28", "192.168.10.128/25"]
    verifier_entetes_securite(entetes)


def test_decoupage_par_n_et_par_prefixe(srv):
    statut, _, par_n = post(srv, "/api/decoupage", {"reseau": "10.0.0.0/24", "n": 4})
    assert statut == 200
    assert par_n["sous_reseaux"] == ["10.0.0.0/26", "10.0.0.64/26", "10.0.0.128/26", "10.0.0.192/26"]
    assert par_n == calc.decoupage("10.0.0.0/24", n=4)
    statut, _, par_prefixe = post(srv, "/api/decoupage", {"reseau": "10.0.0.0/24", "prefixe": 26})
    assert statut == 200
    assert par_prefixe == par_n


def test_decoupage_tronque(srv):
    statut, _, donnees = post(srv, "/api/decoupage", {"reseau": "10.0.0.0/16", "prefixe": 24})
    assert statut == 200
    assert donnees["nombre_total"] == 256 and len(donnees["sous_reseaux"]) == 256 and donnees["tronque"] is False
    statut, _, donnees = post(srv, "/api/decoupage", {"reseau": "10.0.0.0/8", "prefixe": 24})
    assert donnees["nombre_total"] == 65536 and len(donnees["sous_reseaux"]) == 256 and donnees["tronque"] is True


def test_appartenance(srv):
    statut, _, oui = post(srv, "/api/appartenance", {"ip": "192.168.1.77", "reseau": "192.168.1.0/24"})
    assert statut == 200 and oui["appartient"] is True and oui == calc.appartenance("192.168.1.77", "192.168.1.0/24")
    _, _, non = post(srv, "/api/appartenance", {"ip": "192.168.2.77", "reseau": "192.168.1.0/24"})
    assert non["appartient"] is False


def test_chevauchement(srv):
    statut, _, oui = post(srv, "/api/chevauchement", {"a": "10.0.0.0/8", "b": "10.1.0.0/16"})
    assert statut == 200 and oui["chevauchement"] is True and oui == calc.chevauchement("10.0.0.0/8", "10.1.0.0/16")
    _, _, non = post(srv, "/api/chevauchement", {"a": "10.0.0.0/24", "b": "10.0.1.0/24"})
    assert non["chevauchement"] is False


def test_utf8_non_ascii_dans_la_reponse(srv):
    statut, entetes, corps = requete(srv, "POST", "/api/vlsm",
                                     json.dumps({"parent": "10.0.0.0/24", "besoins": [{"nom": "Téléphonie é€", "hotes": 5}]}))
    assert statut == 200
    assert json.loads(corps.decode("utf-8"))["allocations"][0]["nom"] == "Téléphonie é€"


def test_chaine_de_requete_ignoree(srv):
    statut, _, corps = requete(srv, "POST", "/api/cidr?x=1", {"cidr": "10.0.0.1/8"})
    assert statut == 200


# --------------------------------------------------------------------------- #
# Entrées invalides → 400 en français
# --------------------------------------------------------------------------- #

CAS_400 = [
    ("/api/cidr", b"{pas du json", "JSON"),
    ("/api/cidr", b"", "vide"),
    ("/api/cidr", b"[1, 2]", "objet"),
    ("/api/cidr", b'"texte"', "objet"),
    ("/api/cidr", b"\xff\xfe", "UTF-8"),
    ("/api/cidr", b'{"cidr": NaN}', "JSON"),
    ("/api/cidr", b"[" * 5000, "JSON"),
    ("/api/cidr", b'{"autre": 1}', "manquant"),
    ("/api/cidr", b'{"cidr": 12}', "texte"),
    ("/api/cidr", b'{"cidr": null}', "texte"),
    ("/api/cidr", b'{"cidr": "192.168.1.0/33"}', "33"),
    ("/api/cidr", b'{"cidr": "pas-une-ip/24"}', "invalide"),
    ("/api/cidr", b'{"cidr": "192.168.1.0"}', "préfixe"),
    ("/api/vlsm", b'{"parent": "10.0.0.0/24"}', "manquant"),
    ("/api/vlsm", b'{"parent": "10.0.0.0/24", "besoins": "x"}', "besoins"),
    ("/api/vlsm", b'{"parent": "10.0.0.0/24", "besoins": []}', "besoin"),
    ("/api/vlsm", b'{"parent": "10.0.0.0/24", "besoins": [{"nom": "A", "hotes": "50"}]}', "entier"),
    ("/api/vlsm", b'{"parent": "10.0.0.0/24", "besoins": [{"nom": "A", "hotes": -3}]}', "positif"),
    ("/api/vlsm", b'{"parent": "10.0.0.0/24", "besoins": [{"nom": "A", "hotes": 1' + b"0" * 5000 + b"}]}", ""),
    ("/api/vlsm", b'{"parent": "10.0.0.0/30", "besoins": [{"nom": "A", "hotes": 100}]}', "impossible"),
    ("/api/decoupage", b'{"reseau": "10.0.0.0/24"}', "exactement"),
    ("/api/decoupage", b'{"reseau": "10.0.0.0/24", "n": 2, "prefixe": 26}', "exactement"),
    ("/api/decoupage", b'{"reseau": "10.0.0.0/24", "n": "4"}', "entier"),
    ("/api/decoupage", b'{"reseau": "10.0.0.0/24", "n": true}', "entier"),
    ("/api/decoupage", b'{"reseau": "10.0.0.0/24", "prefixe": 40}', "incohérent"),
    ("/api/decoupage", b'{"n": 4}', "manquant"),
    ("/api/appartenance", b'{"ip": "300.1.1.1", "reseau": "10.0.0.0/8"}', "invalide"),
    ("/api/appartenance", b'{"ip": "10.0.0.1"}', "manquant"),
    ("/api/chevauchement", b'{"a": "10.0.0.0/8"}', "manquant"),
    ("/api/chevauchement", b'{"a": "10.0.0.0/8", "b": ["x"]}', "texte"),
]


@pytest.mark.parametrize("route, corps, fragment", CAS_400)
def test_entree_invalide_400(srv, route, corps, fragment):
    statut, entetes, brutes = requete(srv, "POST", route, corps)
    donnees = json.loads(brutes.decode("utf-8"))
    verifier_erreur_json(statut, entetes, donnees, 400)
    assert fragment.lower() in donnees["erreur"].lower()


def test_messages_en_francais(srv):
    _, _, d = post(srv, "/api/cidr", {"cidr": "192.168.1.0/33"})
    assert "Préfixe" in d["erreur"] or "préfixe" in d["erreur"]
    _, _, d = post(srv, "/api/cidr", {})
    assert "Champ manquant" in d["erreur"]
    _, _, d = post(srv, "/api/vlsm", {"parent": "10.0.0.0/30", "besoins": [{"nom": "A", "hotes": 100}]})
    assert "Besoins impossibles" in d["erreur"]


def test_corps_trop_gros_400(srv):
    base = b'{"cidr": "10.0.0.0/8", "bourrage": "'
    corps = base + b"x" * (TAILLE_MAX_CORPS - len(base) + 10) + b'"}'
    assert len(corps) > TAILLE_MAX_CORPS
    statut, entetes, brutes = requete(srv, "POST", "/api/cidr", corps)
    verifier_erreur_json(statut, entetes, json.loads(brutes), 400)
    assert "volumineux" in json.loads(brutes)["erreur"]


def test_corps_a_la_limite_accepte(srv):
    base = b'{"cidr": "10.0.0.0/8", "bourrage": "'
    corps = base + b"x" * (TAILLE_MAX_CORPS - len(base) - 2) + b'"}'
    assert len(corps) == TAILLE_MAX_CORPS
    statut, _, _ = requete(srv, "POST", "/api/cidr", corps)
    assert statut == 200


def test_corps_enorme_annonce_sans_etre_envoye(srv):
    requete_http = (b"POST /api/cidr HTTP/1.1\r\nHost: x\r\nContent-Length: 999999999\r\n\r\n")
    statut, entetes, corps = brut(srv, requete_http, demi_fermeture=False)
    verifier_erreur_json(statut, entetes, json.loads(corps), 400)


def test_content_length_absent_400(srv):
    statut, entetes, corps = brut(srv, b"POST /api/cidr HTTP/1.1\r\nHost: x\r\n\r\n")
    verifier_erreur_json(statut, entetes, json.loads(corps), 400)
    assert "Content-Length" in json.loads(corps)["erreur"]


@pytest.mark.parametrize("valeur", ["abc", "-1", "12x", "1.5", "", "+5", "0x10", "١٢"])
def test_content_length_invalide_400(srv, valeur):
    requete_http = f"POST /api/cidr HTTP/1.1\r\nHost: x\r\nContent-Length: {valeur}\r\n\r\n{{}}".encode("utf-8")
    statut, entetes, corps = brut(srv, requete_http)
    verifier_erreur_json(statut, entetes, json.loads(corps), 400)


def test_content_length_contradictoires_400(srv):
    statut, entetes, corps = brut(
        srv, b'POST /api/cidr HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\nContent-Length: 20\r\n\r\n{}')
    verifier_erreur_json(statut, entetes, json.loads(corps), 400)


def test_transfer_encoding_refuse_400(srv):
    statut, entetes, corps = brut(
        srv, b'POST /api/cidr HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n')
    verifier_erreur_json(statut, entetes, json.loads(corps), 400)


def test_corps_incomplet_400(srv):
    statut, entetes, corps = brut(
        srv, b'POST /api/cidr HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{"cidr"')
    verifier_erreur_json(statut, entetes, json.loads(corps), 400)


def test_requete_mal_formee_reste_en_json(srv):
    statut, entetes, corps = brut(srv, b"N'IMPORTE QUOI\r\n\r\n")
    verifier_erreur_json(statut, entetes, json.loads(corps), 400)
    statut, entetes, corps = brut(srv, b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n")
    verifier_erreur_json(statut, entetes, json.loads(corps), 414)


def test_aucune_trace_python_dans_les_reponses(srv):
    for route, corps, _ in CAS_400:
        _, _, brutes = requete(srv, "POST", route, corps)
        texte = brutes.decode("utf-8")
        assert "Traceback" not in texte and 'File "' not in texte


# --------------------------------------------------------------------------- #
# 404 / 405
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("methode", ["POST", "PUT", "DELETE", "PATCH"])
def test_route_api_inconnue_404(srv, methode):
    statut, entetes, corps = requete(srv, methode, "/api/inconnue", "{}")
    verifier_erreur_json(statut, entetes, json.loads(corps), 404)


@pytest.mark.parametrize("chemin", ["/api", "/api/", "/api/cidr/", "/api/CIDR", "/api/export", "/api/export/", "/api/export/xml",
                                    "/api/export/CSV", "/api/export/csv/", "/introuvable"])
def test_chemins_inconnus_404(srv, chemin):
    statut, entetes, corps = requete(srv, "POST", chemin, "{}")
    verifier_erreur_json(statut, entetes, json.loads(corps), 404)


@pytest.mark.parametrize("methode", ["GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"])
@pytest.mark.parametrize("route", sorted(["/api/cidr", "/api/vlsm", "/api/decoupage", "/api/appartenance",
                                          "/api/chevauchement"]))
def test_methode_non_prevue_sur_l_api_405(srv, methode, route):
    statut, entetes, corps = requete(srv, methode, route, None)
    assert statut == 405
    assert entetes["allow"] == "POST"
    assert entetes["content-type"] == "application/json; charset=utf-8"
    verifier_entetes_securite(entetes)
    if methode != "HEAD":
        verifier_erreur_json(statut, entetes, json.loads(corps), 405)
    else:
        assert corps == b""


@pytest.mark.parametrize("methode", ["POST", "PUT", "DELETE"])
def test_methode_non_prevue_sur_un_statique_405(srv, methode):
    statut, entetes, corps = requete(srv, methode, "/", "{}")
    verifier_erreur_json(statut, entetes, json.loads(corps), 405)
    assert entetes["allow"] == "GET, HEAD"


def test_methode_inconnue_reste_en_json(srv):
    statut, entetes, corps = brut(srv, b"FOO /api/cidr HTTP/1.1\r\nHost: x\r\n\r\n")
    verifier_erreur_json(statut, entetes, json.loads(corps), 501)


# --------------------------------------------------------------------------- #
# Statiques
# --------------------------------------------------------------------------- #

def test_racine_sert_index_html(srv):
    statut, entetes, corps = requete(srv, "GET", "/")
    assert statut == 200
    assert entetes["content-type"] == "text/html; charset=utf-8"
    with open(os.path.join(REPERTOIRE_PROJET, "netplan", "static", "index.html"), "rb") as f:
        assert corps == f.read()
    verifier_entetes_securite(entetes)
    statut, entetes2, corps2 = requete(srv, "GET", "/index.html")
    assert statut == 200 and corps2 == corps
    statut, _, corps3 = requete(srv, "GET", "/static/index.html")
    assert statut == 200 and corps3 == corps


def test_index_html_sans_script_ni_style_en_ligne():
    with open(os.path.join(REPERTOIRE_PROJET, "netplan", "static", "index.html"), encoding="utf-8") as f:
        html = f.read().lower()
    assert "<script>" not in html and "<style" not in html and " style=" not in html and " onclick" not in html


def test_head_statique_sans_corps(srv):
    statut, entetes, corps = requete(srv, "HEAD", "/")
    assert statut == 200 and corps == b""
    assert int(entetes["content-length"]) > 0
    verifier_entetes_securite(entetes)


def test_types_de_contenu(srv_statique):
    cas = {"/": "text/html; charset=utf-8", "/index.html": "text/html; charset=utf-8",
           "/style.css": "text/css", "/static/style.css": "text/css",
           "/app.js": "javascript", "/static/app.js": "javascript"}
    for chemin, attendu in cas.items():
        statut, entetes, corps = requete(srv_statique, "GET", chemin)
        assert statut == 200, chemin
        assert attendu in entetes["content-type"], chemin
        assert corps
        verifier_entetes_securite(entetes)
    assert requete(srv_statique, "GET", "/app.js")[1]["content-type"] in (
        "application/javascript", "application/javascript; charset=utf-8",
        "text/javascript", "text/javascript; charset=utf-8")


def test_sous_dossier_autorise_mais_pas_son_listing(srv_statique):
    assert requete(srv_statique, "GET", "/sous/page.html")[0] == 200
    for chemin in ["/sous", "/sous/", "/static", "/static/", "/static//", "/sous//page.html"]:
        statut, entetes, corps = requete(srv_statique, "GET", chemin)
        verifier_erreur_json(statut, entetes, json.loads(corps), 404)


def test_extension_non_listee_refusee(srv_statique):
    statut, entetes, corps = requete(srv_statique, "GET", "/notes.txt")
    verifier_erreur_json(statut, entetes, json.loads(corps), 404)
    assert b"interdit" not in corps


def test_lien_symbolique_sortant_refuse(srv_statique):
    statut, _, corps = requete(srv_statique, "GET", "/lien.html")
    assert statut == 404 and b"SECRET" not in corps


CHEMINS_TRAVERSEE = [
    "/../subnet_calc.py",
    "/static/../subnet_calc.py",
    "/static/..%2f..%2fsubnet_calc.py",
    "/static/..%2F..%2Fsubnet_calc.py",
    "/%2e%2e/",
    "/%2e%2e/subnet_calc.py",
    "/%2e%2e%2fsubnet_calc.py",
    "/static/%2e%2e/%2e%2e/subnet_calc.py",
    "/..%5csubnet_calc.py",
    "/static/..%5c..%5csubnet_calc.py",
    "/..%00/subnet_calc.py",
    "/index.html%00.css",
    "/%252e%252e/subnet_calc.py",
    "/./index.html/../../subnet_calc.py",
    "/../../../../../../etc/passwd",
    "/static/../../etc/passwd",
    "/calc.py",
    "/static/../calc.py",
    "/__init__.py",
    "/.git/config",
    "/.hidden.html",
]


@pytest.mark.parametrize("chemin", CHEMINS_TRAVERSEE)
def test_traversee_refusee(srv, chemin):
    statut, entetes, corps = requete(srv, "GET", chemin)
    assert statut in (400, 404)
    assert b"def " not in corps and b"import " not in corps and b"root:" not in corps
    donnees = json.loads(corps)
    assert set(donnees) == {"erreur"}
    verifier_entetes_securite(entetes)


# --------------------------------------------------------------------------- #
# En-têtes sur chaque type de réponse
# --------------------------------------------------------------------------- #

def test_entetes_sur_chaque_type_de_reponse(srv):
    reponses = [
        requete(srv, "GET", "/"),                                                    # 200 statique
        requete(srv, "POST", "/api/cidr", {"cidr": "10.0.0.0/8"}),                   # 200 API
        requete(srv, "POST", "/api/cidr", "pas du json"),                            # 400
        requete(srv, "POST", "/api/inconnue", "{}"),                                 # 404 API
        requete(srv, "GET", "/introuvable.css"),                                     # 404 statique
        requete(srv, "GET", "/api/cidr"),                                            # 405
        requete(srv, "HEAD", "/"),                                                   # HEAD
    ]
    assert [r[0] for r in reponses] == [200, 200, 400, 404, 404, 405, 200]
    for _, entetes, _ in reponses:
        verifier_entetes_securite(entetes)


def test_en_tete_server_sans_version_de_python(srv):
    _, entetes, _ = requete(srv, "GET", "/")
    valeur = entetes.get("server", "")
    assert "Python" not in valeur and "BaseHTTP" not in valeur


# --------------------------------------------------------------------------- #
# Serveur
# --------------------------------------------------------------------------- #

def test_ecoute_sur_127_0_0_1_par_defaut():
    import inspect
    from netplan.server import creer_serveur as fabrique
    assert inspect.signature(fabrique).parameters["host"].default == "127.0.0.1"
    lance = _Lance(creer_serveur(port=0, journal=False))
    try:
        assert lance.host == "127.0.0.1"
    finally:
        lance.arreter()


def test_arret_propre_libere_le_port():
    lance = _Lance(creer_serveur("127.0.0.1", 0, journal=False))
    port = lance.port
    assert requete(lance, "GET", "/")[0] == 200
    lance.arreter()
    assert not lance.fil.is_alive()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


def test_requetes_concurrentes(srv):
    resultats = []

    def appel():
        resultats.append(post(srv, "/api/cidr", {"cidr": "172.16.0.5/12"})[0])

    fils = [threading.Thread(target=appel) for _ in range(12)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=10)
    assert resultats == [200] * 12
