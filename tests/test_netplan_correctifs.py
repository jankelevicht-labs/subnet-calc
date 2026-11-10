# -*- coding: utf-8 -*-
"""Non-régression F1a : format de ``cidr_info.reseau``, préfixe géant, surrogates isolés,
géométrie proportionnelle de la carte VLSM."""

import http.client
import json
import os
import re
import sys
import threading

import pytest

from netplan import calc
from netplan.server import creer_serveur

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def post_brut(srv, chemin, octets):
    """POST d'octets JSON bruts ; renvoie (statut, en-têtes, corps décodé en UTF-8 strict)."""
    cnx = http.client.HTTPConnection(srv[0], srv[1], timeout=10)
    try:
        cnx.request("POST", chemin, body=octets, headers={"Content-Type": "application/json"})
        rep = cnx.getresponse()
        return rep.status, {k.lower(): v for k, v in rep.getheaders()}, rep.read().decode("utf-8")
    finally:
        cnx.close()


def verifier_400_francais(statut, entetes, corps):
    assert statut == 400, corps
    assert entetes["content-type"] == "application/json; charset=utf-8"
    donnees = json.loads(corps)
    assert set(donnees) == {"erreur"} and donnees["erreur"]
    assert re.search(r"[éèêàùç]|[Ll]e |[Ll]a |[Ll]es |invalide|incohérent|attendu", donnees["erreur"])
    for anglais in ("Exceeds", "digits for integer", "Traceback"):
        assert anglais not in donnees["erreur"]
    assert len(donnees["erreur"]) < 500           # ne recopie pas les 5000 chiffres
    return donnees["erreur"]


# ------------------------------------------------------------------ E1 : reseau sans préfixe

def test_e1_cidr_info_reseau_sans_prefixe():
    r = calc.cidr_info("192.168.1.10/24")
    assert r["reseau"] == "192.168.1.0" and r["prefixe"] == 24
    assert calc.cidr_info("10.1.2.3/32")["reseau"] == "10.1.2.3"
    assert calc.cidr_info("10.1.2.3/8")["reseau"] == "10.0.0.0"


def test_e1_vlsm_decoupage_gardent_le_cidr():
    r = calc.vlsm("192.168.10.0/24", [{"nom": "A", "hotes": 50}, {"nom": "B", "hotes": 20},
                                      {"nom": "C", "hotes": 10}])
    assert [a["reseau"] for a in r["allocations"]] == [
        "192.168.10.0/26", "192.168.10.64/27", "192.168.10.96/28"]
    assert r["libres"] == ["192.168.10.112/28", "192.168.10.128/25"]
    assert calc.decoupage("10.0.0.0/24", n=2)["sous_reseaux"] == ["10.0.0.0/25", "10.0.0.128/25"]


def test_e1_calculatrice_affiche_le_reseau_avec_prefixe():
    js = open(os.path.join(RACINE, "netplan", "static", "app.js"), encoding="utf-8").read()
    assert re.search(r'fixer\("calc-reseau",\s*rep\.reseau\s*\+\s*"/"\s*\+\s*rep\.prefixe\)', js)


# ------------------------------------------------------------------ E2 : préfixe de 5000 chiffres

def test_e2_calc_prefixe_geant_netplanerror_francais():
    # La limite globale de Python n'est pas relevée : la validation précède int().
    assert 0 < sys.get_int_max_str_digits() < 5000
    for fonction, args in ((calc.cidr_info, ("10.0.0.0/" + GEANT,)),
                           (calc.vlsm, ("10.0.0.0/" + GEANT, [{"nom": "a", "hotes": 2}])),
                           (calc.decoupage, ("10.0.0.0/" + GEANT, 2)),
                           (calc.appartenance, ("10.0.0.1", "10.0.0.0/" + GEANT)),
                           (calc.chevauchement, ("10.0.0.0/" + GEANT, "10.0.0.0/8")),
                           (calc.chevauchement, ("10.0.0.0/8", "10.0.0.0/" + GEANT))):
        with pytest.raises(calc.NetplanError) as exc:
            fonction(*args)
        assert "Préfixe incohérent" in str(exc.value)
        assert "Exceeds" not in str(exc.value) and len(str(exc.value)) < 300


def test_e2_prefixe_valide_avec_zeros_initiaux_inchange():
    assert calc.cidr_info("10.0.0.0/024")["prefixe"] == 24
    assert calc.cidr_info("10.0.0.0/" + "0" * 5000 + "8")["prefixe"] == 8
    with pytest.raises(calc.NetplanError, match="dépasse /32"):
        calc.cidr_info("10.0.0.0/100")


ROUTES_CALCUL_GEANT = [
    ("/api/cidr", {"cidr": "10.0.0.0/" + GEANT}),
    ("/api/vlsm", {"parent": "10.0.0.0/" + GEANT, "besoins": [{"nom": "a", "hotes": 2}]}),
    ("/api/decoupage", {"reseau": "10.0.0.0/" + GEANT, "n": 2}),
    ("/api/appartenance", {"ip": "10.0.0.1", "reseau": "10.0.0.0/" + GEANT}),
    ("/api/chevauchement", {"a": "10.0.0.0/" + GEANT, "b": "10.0.0.0/8"}),
    ("/api/chevauchement", {"a": "10.0.0.0/8", "b": "10.0.0.0/" + GEANT}),
]


@pytest.mark.parametrize("route,corps", ROUTES_CALCUL_GEANT)
def test_e2_api_prefixe_geant_400(srv, route, corps):
    verifier_400_francais(*post_brut(srv, route, json.dumps(corps).encode("utf-8")))


@pytest.mark.parametrize("format_", ["csv", "json", "routeros"])
def test_e2_export_prefixe_geant_400(srv, format_):
    corps = {"parent": "192.168.10.0/" + GEANT, "besoins": [{"nom": "a", "hotes": 2}]}
    verifier_400_francais(*post_brut(srv, f"/api/export/{format_}", json.dumps(corps).encode("utf-8")))


# ------------------------------------------------------------------ E3 : surrogates isolés

SURROGATES = [
    ("/api/cidr", b'{"cidr":"\\ud800/24"}'),
    ("/api/cidr", b'{"cidr":"10.0.0.0/24","\\udc00":1}'),
    ("/api/vlsm", b'{"parent":"10.0.0.0/24","besoins":[{"nom":"\\ud800","hotes":2}]}'),
    ("/api/decoupage", b'{"reseau":"\\udfff/24","n":2}'),
    ("/api/appartenance", b'{"ip":"\\ud800","reseau":"10.0.0.0/8"}'),
    ("/api/chevauchement", b'{"a":"10.0.0.0/8","b":"x\\ud800"}'),
] + [
    (f"/api/export/{f}", c)
    for f in ("csv", "json", "routeros")
    for c in (b'{"parent":"bad\\ud800","besoins":[{"nom":"a","hotes":2}]}',
              b'{"parent":"10.0.0.0/24","besoins":[{"nom":"bad\\ud800","hotes":2}]}')
]


@pytest.mark.parametrize("route,octets", SURROGATES)
def test_e3_surrogate_isole_400_json_francais(srv, route, octets):
    statut, entetes, corps = post_brut(srv, route, octets)   # decode("utf-8") strict : réponse encodable
    erreur = verifier_400_francais(statut, entetes, corps)
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in erreur)
    assert "\\ud8" not in corps and "\\udc" not in corps and "\\udf" not in corps


def test_e3_paire_surrogate_valide_reste_acceptee(srv):
    # \ud83d\ude00 = U+1F600 : une paire valide est du texte légitime.
    statut, _, corps = post_brut(srv, "/api/vlsm",
                                 b'{"parent":"10.0.0.0/24","besoins":[{"nom":"\\ud83d\\ude00","hotes":2}]}')
    assert statut == 200 and "\U0001F600" in json.loads(corps)["allocations"][0]["nom"]


def test_e3_reponse_toujours_encodable_meme_avec_un_surrogate(srv):
    from netplan import server
    d = {"erreur": "x\ud800"}
    assert server._contient_surrogate(d) and server._contient_surrogate([{"k\ud800": 1}])
    assert not server._contient_surrogate({"a": ["é", 1, None, {"b": "\U0001F600"}]})


# ------------------------------------------------------------------ E4 : géométrie de la carte

def _regles_css(css, selecteur):
    """Déclarations (concaténées) des règles dont le sélecteur est exactement ``selecteur``,
    y compris dans les @media."""
    corps = []
    for m in re.finditer(r"(?<![\w-])" + re.escape(selecteur) + r"\s*\{([^}]*)\}", css):
        corps.append(m.group(1))
    return "\n".join(corps)


def test_e4_blocs_proportionnels_sans_effet_sur_la_largeur():
    css = open(os.path.join(RACINE, "netplan", "static", "style.css"), encoding="utf-8").read()
    bloc = _regles_css(css, ".bloc")
    assert bloc, ".bloc introuvable"
    decls = {}
    for d in bloc.split(";"):
        if ":" in d:
            nom, _, val = d.partition(":")
            decls[nom.strip()] = val.strip()
    assert decls.get("min-width", "0") in ("0", "0px")
    assert decls.get("flex") == "none"                        # ni flex-shrink ni flex-grow
    assert "flex-shrink" not in decls and "flex-grow" not in decls and "flex-basis" not in decls
    assert decls.get("box-sizing") == "border-box"
    assert "width" not in decls                              # la largeur vient de style.width
    for nom, val in decls.items():
        if nom.startswith("border") and not nom.startswith("border-radius"):
            assert val in ("0", "none"), (nom, val)
        if nom.startswith("padding"):
            assert re.fullmatch(r"0(px|rem)?(\s+0(px|rem)?)*", val), (nom, val)
