# -*- coding: utf-8 -*-
"""Non-régression F1b (revue sécurité S) : S1 préfixe géant, S2 surrogates isolés,
S3 corps > 64 Kio rejeté AVANT toute lecture (drainage éventuel borné, après l'envoi)."""

import http.client
import io
import json
import re
import socket
import threading
import time
from email.message import Message

import pytest

from netplan import calc, server
from netplan.server import ErreurRequete, Gestionnaire, TAILLE_MAX_CORPS, creer_serveur

GEANT = "9" * 5000


@pytest.fixture(scope="module")
def srv():
    serveur = creer_serveur("127.0.0.1", 0, journal=False)
    fil = threading.Thread(target=serveur.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    fil.start()
    yield serveur.server_address[:2]
    serveur.shutdown()
    serveur.server_close()
    fil.join(timeout=5)


def post(srv, chemin, octets):
    cnx = http.client.HTTPConnection(srv[0], srv[1], timeout=10)
    try:
        cnx.request("POST", chemin, body=octets, headers={"Content-Type": "application/json"})
        rep = cnx.getresponse()
        return rep.status, {k.lower(): v for k, v in rep.getheaders()}, rep.read().decode("utf-8")
    finally:
        cnx.close()


def verifier_400(statut, entetes, corps):
    assert statut == 400, corps
    assert entetes["content-type"] == "application/json; charset=utf-8"
    erreur = json.loads(corps)["erreur"]
    assert re.search(r"[éèêàùç]|[Ll]e |[Ll]a |[Ll]es |invalide|incohérent|attendu", erreur)
    assert "Traceback" not in erreur and "Exceeds" not in erreur
    assert len(erreur) < 500
    return erreur


# --------------------------------------------------------------------------- S1

ROUTES_S1 = [
    ("/api/cidr", {"cidr": "10.0.0.0/" + GEANT}),
    ("/api/vlsm", {"parent": "10.0.0.0/" + GEANT, "besoins": [{"nom": "A", "hotes": 2}]}),
    ("/api/decoupage", {"reseau": "10.0.0.0/" + GEANT, "prefixe": 30}),
    ("/api/appartenance", {"ip": "10.0.0.1", "reseau": "10.0.0.0/" + GEANT}),
    ("/api/chevauchement", {"a": "10.0.0.0/" + GEANT, "b": "10.0.0.0/24"}),
    ("/api/export/csv", {"parent": "10.0.0.0/" + GEANT, "besoins": [{"nom": "A", "hotes": 2}]}),
    ("/api/export/json", {"parent": "10.0.0.0/" + GEANT, "besoins": [{"nom": "A", "hotes": 2}]}),
    ("/api/export/routeros", {"parent": "10.0.0.0/" + GEANT, "besoins": [{"nom": "A", "hotes": 2}]}),
]


@pytest.mark.parametrize("route,corps", ROUTES_S1)
def test_s1_prefixe_geant_400_francais(srv, route, corps):
    verifier_400(*post(srv, route, json.dumps(corps).encode("utf-8")))


def test_s1_limite_globale_python_non_relevee():
    import os
    racine = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "netplan")
    for nom in os.listdir(racine):
        if nom.endswith(".py"):
            with open(os.path.join(racine, nom), encoding="utf-8") as f:
                assert "set_int_max_str_digits" not in f.read()


def test_s1_messages_derreur_ne_recopient_pas_un_texte_geant():
    for entree in ("1.2.3." + "9" * 20000 + "/24", "x" * 20000 + "/24", "x" * 20000, "10.0.0.0/" + "9" * 20000):
        with pytest.raises(calc.NetplanError) as exc:
            calc.cidr_info(entree)
        assert len(str(exc.value)) < 400
    with pytest.raises(calc.NetplanError) as exc:
        calc.appartenance("y" * 20000, "10.0.0.0/8")
    assert len(str(exc.value)) < 400
    with pytest.raises(calc.NetplanError) as exc:
        calc.vlsm("10.0.0.0/24", [{"nom": "n" * 20000, "hotes": 0}])
    assert len(str(exc.value)) < 400
    with pytest.raises(calc.NetplanError) as exc:
        calc.vlsm("10.0.0.0/30", [{"nom": "n" * 20000, "hotes": 200}])
    assert len(str(exc.value)) < 400


def test_s1_message_court_inchange():
    with pytest.raises(calc.NetplanError) as exc:
        calc.cidr_info("10.0.0.0")
    assert "« 10.0.0.0 »" in str(exc.value)


# --------------------------------------------------------------------------- S2

S2 = [
    ("/api/cidr", b'{"cidr":"\\ud800/24"}'),
    ("/api/vlsm", b'{"parent":"\\ud800/24","besoins":[{"nom":"a","hotes":2}]}'),
    ("/api/vlsm", b'{"parent":"10.0.0.0/24","besoins":[{"nom":"\\ud800","hotes":2}]}'),
] + [
    (f"/api/export/{f}", c)
    for f in ("csv", "json", "routeros")
    for c in (b'{"parent":"\\ud800/24","besoins":[{"nom":"a","hotes":2}]}',
              b'{"parent":"10.0.0.0/24","besoins":[{"nom":"\\ud800","hotes":2}]}')
]


@pytest.mark.parametrize("route,octets", S2)
def test_s2_surrogate_isole_400_jamais_de_fermeture_silencieuse(srv, route, octets):
    statut, entetes, corps = post(srv, route, octets)   # une fermeture sans réponse lèverait ici
    verifier_400(statut, entetes, corps)


def test_s2_chemin_derreur_toujours_encodable():
    """Même si un surrogate atteignait le message d'erreur, la réponse reste encodable."""
    h = object.__new__(Gestionnaire)
    envoyes = []
    h._envoyer = lambda statut, corps, type_contenu, entetes=(), avec_corps=True: envoyes.append((statut, corps))
    h._envoyer_erreur(400, "Réseau « \ud800 » invalide")
    statut, corps = envoyes[0]
    assert statut == 400 and isinstance(corps, bytes)
    assert json.loads(corps.decode("utf-8"))["erreur"]


# --------------------------------------------------------------------------- S3

class FluxCompte(io.BytesIO):
    """BytesIO qui compte les octets réellement lus."""

    def __init__(self, donnees):
        super().__init__(donnees)
        self.lus = 0

    def read(self, n=-1):
        morceau = super().read(n)
        self.lus += len(morceau)
        return morceau

    read1 = read


class ConnexionFactice:
    def settimeout(self, valeur):
        pass


def gestionnaire_factice(longueur, flux):
    h = object.__new__(Gestionnaire)
    h.headers = Message()
    h.headers["Content-Length"] = str(longueur)
    h.rfile = flux
    h.connection = ConnexionFactice()
    return h


@pytest.mark.parametrize("longueur", [TAILLE_MAX_CORPS + 1, 10_000_000])
def test_s3_lire_corps_rejette_sans_lire_un_seul_octet(longueur):
    flux = FluxCompte(b"x" * min(longueur, 2_000_000))
    h = gestionnaire_factice(longueur, flux)
    with pytest.raises(ErreurRequete) as exc:
        h._lire_corps()
    assert exc.value.statut == 400 and "volumineux" in exc.value.message
    assert flux.lus == 0


def test_s3_octets_lus_avant_lenvoi_du_rejet_egal_zero():
    """Chaîne complète _traiter : au moment où le 400 est écrit, 0 octet de corps a été lu."""
    flux = FluxCompte(b"x" * (TAILLE_MAX_CORPS + 1))
    h = gestionnaire_factice(TAILLE_MAX_CORPS + 1, flux)
    lus_a_lenvoi = []

    def envoyer(statut, corps, type_contenu, entetes=(), avec_corps=True):
        lus_a_lenvoi.append((statut, flux.lus))

    h._envoyer = envoyer
    h.path, h.command = "/api/cidr", "POST"
    h.request_version = "HTTP/1.1"
    h._traiter()
    assert lus_a_lenvoi == [(400, 0)]


def test_s3_drainage_borne_en_octets():
    flux = FluxCompte(b"x" * (3 * server.TAILLE_MAX_DRAIN))
    h = gestionnaire_factice(10_000_000, flux)
    jetes = h._jeter_corps(10_000_000)
    assert jetes == flux.lus == server.TAILLE_MAX_DRAIN
    assert server.TAILLE_MAX_DRAIN <= 1024 * 1024


def test_s3_drainage_borne_en_duree_totale(monkeypatch):
    """Un client qui goutte-à-goutte (chaque lecture < délai d'inactivité) ne dépasse pas 1 s au total."""
    assert server.DUREE_MAX_DRAIN <= 1.0

    class Goutte:
        def read1(self, n):
            time.sleep(0.05)
            return b"x"
        read = read1

    h = gestionnaire_factice(10_000_000, Goutte())
    debut = time.monotonic()
    jetes = h._jeter_corps(10_000_000)
    duree = time.monotonic() - debut
    assert duree < 1.0 + 0.3
    assert 0 < jetes < 100


def _en_tetes_seuls(srv, longueur, chemin="/api/cidr"):
    sock = socket.create_connection(srv, timeout=5)
    try:
        debut = time.monotonic()
        sock.sendall(f"POST {chemin} HTTP/1.1\r\nHost: localhost\r\nContent-Length: {longueur}\r\n\r\n".encode())
        donnees = b""
        while b"\r\n\r\n" not in donnees or b"}" not in donnees:
            morceau = sock.recv(8192)
            if not morceau:
                break
            donnees += morceau
        return donnees, time.monotonic() - debut, sock
    except Exception:
        sock.close()
        raise


@pytest.mark.parametrize("longueur", [TAILLE_MAX_CORPS + 1, 10_000_000])
def test_s3_socket_en_tetes_seuls_400_en_moins_de_200_ms(srv, longueur):
    donnees, duree, sock = _en_tetes_seuls(srv, longueur)
    sock.close()
    assert donnees.startswith(b"HTTP/1.0 400"), donnees
    assert duree < 0.2, duree
    corps = donnees.split(b"\r\n\r\n", 1)[1]
    assert "volumineux" in json.loads(corps.decode("utf-8"))["erreur"]


def test_s3_socket_corps_envoye_ensuite_le_serveur_ferme_dans_la_seconde(srv):
    """Le client continue d'envoyer 2 Mio : le serveur répond tout de suite, jette ≤ 1 Mio
    en ≤ ~1 s puis ferme."""
    donnees, duree, sock = _en_tetes_seuls(srv, 10_000_000)
    assert donnees.startswith(b"HTTP/1.0 400") and duree < 0.2
    debut = time.monotonic()
    envoyes = 0
    try:
        sock.settimeout(3)
        while time.monotonic() - debut < 3:
            sock.sendall(b"x" * 65536)
            envoyes += 65536
            if envoyes > 8 * 1024 * 1024:
                break
    except OSError:
        pass                                   # le serveur a fermé : attendu
    finally:
        sock.close()
    assert time.monotonic() - debut < 2.0
    assert envoyes <= 8 * 1024 * 1024 + 65536


def test_s3_corps_valide_juste_sous_la_limite_inchange(srv):
    base = b'{"cidr":"10.0.0.0/24","x":"'
    corps = base + b"a" * (TAILLE_MAX_CORPS - len(base) - 2) + b'"}'
    assert len(corps) == TAILLE_MAX_CORPS
    statut, _, texte = post(srv, "/api/cidr", corps)
    assert statut == 200, texte


def test_s3_corps_trop_gros_envoye_en_entier_recoit_un_400(srv):
    statut, entetes, texte = post(srv, "/api/cidr", b"x" * (TAILLE_MAX_CORPS + 1))
    verifier_400(statut, entetes, texte)
    assert "volumineux" in json.loads(texte)["erreur"]
