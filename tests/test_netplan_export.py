# -*- coding: utf-8 -*-
"""Tests des exports de NetPlan Studio (CSV, JSON, RouterOS) : fonctions et routes /api/export/*."""

import csv
import http.client
import io
import json
import threading

import pytest

from netplan import calc, export
from netplan.server import ROUTES_EXPORT, TAILLE_MAX_CORPS, creer_serveur

ENTETE_CSV = "nom,hotes_demandes,reseau,prefixe,masque,premier_hote,dernier_hote,broadcast,capacite"
CORPS = {"parent": "192.168.10.0/24",
         "besoins": [{"nom": "LAN", "hotes": 50}, {"nom": "Serveurs", "hotes": 20}, {"nom": "Admin", "hotes": 10}]}
ROUTES = ("/api/export/csv", "/api/export/json", "/api/export/routeros")


# --------------------------------------------------------------------------- #
# Serveur réel
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def srv():
    serveur = creer_serveur("127.0.0.1", 0, journal=False)
    fil = threading.Thread(target=serveur.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    fil.start()
    yield serveur.server_address[:2]
    serveur.shutdown()
    serveur.server_close()
    fil.join(timeout=5)


def requete(srv, methode, chemin, corps=None):
    cnx = http.client.HTTPConnection(srv[0], srv[1], timeout=10)
    try:
        if isinstance(corps, (dict, list)):
            corps = json.dumps(corps)
        if isinstance(corps, str):
            corps = corps.encode("utf-8")
        cnx.request(methode, chemin, body=corps, headers={"Content-Type": "application/json"})
        rep = cnx.getresponse()
        return rep.status, {k.lower(): v for k, v in rep.getheaders()}, rep.read()
    finally:
        cnx.close()


def exporter(srv, format_, corps):
    statut, entetes, octets = requete(srv, "POST", f"/api/export/{format_}", corps)
    return statut, entetes, octets.decode("utf-8")


def plan_de(*besoins, parent="192.168.10.0/24"):
    return calc.vlsm(parent, [{"nom": n, "hotes": h} for n, h in besoins])


# --------------------------------------------------------------------------- #
# Fonctions d'export
# --------------------------------------------------------------------------- #

def test_csv_entete_et_lignes():
    plan = calc.vlsm(**CORPS)
    lignes = export.vers_csv(plan).splitlines()
    assert lignes[0] == ENTETE_CSV
    assert len(lignes) == 1 + len(plan["allocations"]) == 4
    assert lignes[1] == "LAN,50,192.168.10.0/26,26,255.255.255.192,192.168.10.1,192.168.10.62,192.168.10.63,62"


def test_csv_relisible_par_le_module_csv():
    plan = plan_de(("A", 100), ("B", 10))
    lignes = list(csv.DictReader(io.StringIO(export.vers_csv(plan), newline="")))
    assert [l["nom"] for l in lignes] == ["A", "B"]
    assert lignes[0]["reseau"] == plan["allocations"][0]["reseau"]
    assert lignes[1]["capacite"] == str(plan["allocations"][1]["capacite"])


@pytest.mark.parametrize("nom", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "=HYPERLINK(\"http://x\")"])
def test_csv_neutralise_les_formules(nom):
    lignes = list(csv.DictReader(io.StringIO(export.vers_csv(plan_de((nom, 10))), newline="")))
    assert lignes[0]["nom"] == "'" + nom


@pytest.mark.parametrize("brut", ["\t=1", "\r=1", "\t", "\rx"])
def test_neutraliser_tabulation_et_retour_chariot(brut):
    assert export.neutraliser_formule(brut) == "'" + brut


def test_csv_ne_touche_pas_aux_cellules_normales():
    assert export.neutraliser_formule("Wi-Fi invités") == "Wi-Fi invités"
    assert export.neutraliser_formule("192.168.10.0/26") == "192.168.10.0/26"
    assert export.neutraliser_formule(50) == "50"
    lignes = list(csv.DictReader(io.StringIO(export.vers_csv(plan_de(("Wi-Fi invités", 10))), newline="")))
    assert lignes[0]["nom"] == "Wi-Fi invités"


def test_csv_nom_avec_virgule_et_guillemets():
    lignes = list(csv.DictReader(io.StringIO(export.vers_csv(plan_de(('A, "B"', 10))), newline="")))
    assert lignes[0]["nom"] == 'A, "B"'
    assert lignes[0]["hotes_demandes"] == "10"


def test_json_plan_complet():
    plan = calc.vlsm(**CORPS)
    relu = json.loads(export.vers_json(plan))
    assert relu == plan
    assert set(relu) >= {"parent", "allocations", "libres", "taux_occupation"}


def test_routeros_adresses_attendues():
    lignes = export.vers_routeros(calc.vlsm(**CORPS)).splitlines()
    assert lignes[0].startswith("# BROUILLON À VÉRIFIER")
    assert lignes[1:] == [
        '/ip address add address=192.168.10.1/26 network=192.168.10.0 interface=A_DEFINIR comment="LAN"',
        '/ip address add address=192.168.10.65/27 network=192.168.10.64 interface=A_DEFINIR comment="Serveurs"',
        '/ip address add address=192.168.10.97/28 network=192.168.10.96 interface=A_DEFINIR comment="Admin"',
    ]


@pytest.mark.parametrize("nom, attendu", [
    ('a"b', 'a\\"b'),
    ("a\\b", "a\\\\b"),
    ("$x", "\\$x"),
    ("[env]", "\\[env\\]"),
    ('"; /system reset-configuration #', '\\"; /system reset-configuration #'),
    ("ligne1\nligne2\r\x00\x1b\x7f", "ligne1ligne2"),
    ("a\u2028b\u202ec", "abc"),
    ("Wi-Fi invités", "Wi-Fi invités"),
])
def test_routeros_echappement_du_nom(nom, attendu):
    assert export.echapper_routeros(nom) == attendu


def test_routeros_nom_hostile_reste_sur_une_ligne():
    plan = plan_de(('x" ; /user add name=pirate\n/system reset', 10), ("$[/file print]", 5))
    lignes = export.vers_routeros(plan).splitlines()
    assert len(lignes) == 1 + 2
    assert all(l.startswith("/ip address add address=") for l in lignes[1:])
    assert 'comment="x\\" ; /user add name=pirate/system reset"' in lignes[1] or \
        'comment="x\\" ; /user add name=pirate/system reset"' in lignes[2]
    assert 'comment="\\$\\[/file print\\]"' in "\n".join(lignes)


def test_nom_fichier_ascii_sur():
    plan = calc.vlsm(**CORPS)
    assert export.nom_fichier(plan, ".csv") == "plan-192.168.10.0-24.csv"


# --------------------------------------------------------------------------- #
# Routes d'export
# --------------------------------------------------------------------------- #

def verifier_securite(entetes):
    assert "default-src" in entetes["content-security-policy"]
    assert entetes["x-content-type-options"] == "nosniff"
    assert entetes["referrer-policy"] == "no-referrer"


def test_routes_declarees():
    assert set(ROUTES_EXPORT) == set(ROUTES)


def test_api_csv_200(srv):
    statut, entetes, texte = exporter(srv, "csv", CORPS)
    assert statut == 200
    assert entetes["content-type"] == "text/csv; charset=utf-8"
    assert entetes["content-disposition"].startswith("attachment")
    assert 'filename="plan-192.168.10.0-24.csv"' in entetes["content-disposition"]
    verifier_securite(entetes)
    lignes = texte.splitlines()
    assert lignes[0] == ENTETE_CSV
    assert len(lignes) == 4


def test_api_csv_neutralise_la_formule(srv):
    corps = {"parent": "10.0.0.0/24", "besoins": [{"nom": "=1+1", "hotes": 10}]}
    statut, _, texte = exporter(srv, "csv", corps)
    assert statut == 200
    assert texte.splitlines()[1].startswith("'=1+1,10,10.0.0.0/28,")


def test_api_json_200_et_valide(srv):
    statut, entetes, texte = exporter(srv, "json", CORPS)
    assert statut == 200
    assert entetes["content-type"] == "application/json; charset=utf-8"
    assert entetes["content-disposition"].startswith("attachment")
    assert entetes["content-disposition"].endswith('.json"')
    verifier_securite(entetes)
    plan = json.loads(texte)
    assert set(plan) == {"parent", "allocations", "libres", "taux_occupation"}
    assert plan["parent"] == "192.168.10.0/24"
    assert len(plan["allocations"]) == 3
    assert plan == requete_vlsm(srv)


def requete_vlsm(srv):
    return json.loads(requete(srv, "POST", "/api/vlsm", CORPS)[2].decode("utf-8"))


def test_api_routeros_200(srv):
    statut, entetes, texte = exporter(srv, "routeros", CORPS)
    assert statut == 200
    assert entetes["content-type"] == "text/plain; charset=utf-8"
    assert entetes["content-disposition"].startswith("attachment")
    verifier_securite(entetes)
    lignes = texte.splitlines()
    assert lignes[0].startswith("# BROUILLON À VÉRIFIER")
    assert len(lignes) == 4
    assert "address=192.168.10.1/26 network=192.168.10.0 " in lignes[1]
    assert "address=192.168.10.65/27 network=192.168.10.64 " in lignes[2]
    assert "address=192.168.10.97/28 network=192.168.10.96 " in lignes[3]
    assert all("interface=A_DEFINIR" in l for l in lignes[1:])


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("corps", [
    {"parent": "pas-un-reseau", "besoins": [{"nom": "A", "hotes": 5}]},
    {"parent": "10.0.0.0/24", "besoins": []},
    {"parent": "10.0.0.0/24", "besoins": [{"nom": "Énorme", "hotes": 100000}]},
    {"parent": "10.0.0.0/24", "besoins": [{"nom": "", "hotes": 5}]},
    {"parent": "10.0.0.0/24"},
    {"besoins": [{"nom": "A", "hotes": 5}]},
    {"parent": "2001:db8::/32", "besoins": [{"nom": "A", "hotes": 5}]},
    [],
    "texte",
], ids=["parent-invalide", "besoins-vides", "trop-grand", "nom-vide", "besoins-absents", "parent-absent",
        "ipv6", "liste", "chaine"])
def test_api_export_entree_invalide_400(srv, route, corps):
    statut, entetes, octets = requete(srv, "POST", route, json.dumps(corps))
    assert statut == 400
    assert entetes["content-type"] == "application/json; charset=utf-8"
    assert "content-disposition" not in entetes
    verifier_securite(entetes)
    reponse = json.loads(octets.decode("utf-8"))
    assert list(reponse) == ["erreur"]
    assert isinstance(reponse["erreur"], str) and len(reponse["erreur"]) > 10
    assert "Traceback" not in reponse["erreur"]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("corps", ["", "pas du json", "{", "[1, 2]"])
def test_api_export_json_mal_forme_400(srv, route, corps):
    statut, _, octets = requete(srv, "POST", route, corps)
    assert statut == 400
    assert "erreur" in json.loads(octets.decode("utf-8"))


@pytest.mark.parametrize("route", ROUTES)
def test_api_export_corps_trop_gros_400(srv, route):
    corps = json.dumps({"parent": "10.0.0.0/8", "besoins": [], "bourrage": "x" * (TAILLE_MAX_CORPS + 10)})
    statut, _, octets = requete(srv, "POST", route, corps)
    assert statut == 400
    assert "erreur" in json.loads(octets.decode("utf-8"))


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("methode", ["GET", "HEAD", "PUT", "DELETE", "PATCH"])
def test_api_export_methode_non_prevue_405(srv, route, methode):
    statut, entetes, _ = requete(srv, methode, route)
    assert statut == 405
    assert entetes["allow"] == "POST"
    verifier_securite(entetes)


def test_api_export_nom_hostile_de_bout_en_bout(srv):
    corps = {"parent": "10.0.0.0/24", "besoins": [{"nom": 'x"\n/system reset $[a]', "hotes": 10}]}
    statut, _, texte = exporter(srv, "routeros", corps)
    assert statut == 200
    lignes = texte.splitlines()
    assert len(lignes) == 2
    assert lignes[1].endswith('comment="x\\"/system reset \\$\\[a\\]"')
