# -*- coding: utf-8 -*-
"""Tests des calculs de NetPlan Studio (netplan/calc.py)."""

import ipaddress
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from netplan import calc  # noqa: E402
from netplan.calc import (  # noqa: E402
    LIMITE_SOUS_RESEAUX,
    NetplanError,
    appartenance,
    chevauchement,
    cidr_info,
    decoupage,
    vlsm,
)

MOTS_FR = ("invalide", "incohérent", "impossible", "vide", "doit", "ajoutez", "Aucun", "Trop", "Indiquez")


def message_fr(exc_info):
    """Message d'erreur : non vide et en français (mots français, pas de message anglais d'ipaddress)."""
    msg = str(exc_info.value)
    assert msg
    assert any(m in msg for m in MOTS_FR), msg
    for anglais in ("does not appear", "Invalid", "invalid network", "Expected"):
        assert anglais not in msg
    return msg


# ------------------------------------------------------------------ cidr_info

def test_cidr_info_24():
    r = cidr_info("192.168.1.0/24")
    assert r == {
        "adresse": "192.168.1.0",
        "reseau": "192.168.1.0",
        "broadcast": "192.168.1.255",
        "masque": "255.255.255.0",
        "prefixe": 24,
        "premier_hote": "192.168.1.1",
        "dernier_hote": "192.168.1.254",
        "nb_hotes": 254,
        "binaire_adresse": "11000000.10101000.00000001.00000000",
        "binaire_masque": "11111111.11111111.11111111.00000000",
    }


def test_cidr_info_bits_hote_acceptes():
    r = cidr_info("192.168.1.10/24")
    assert r["adresse"] == "192.168.1.10"
    assert r["reseau"] == "192.168.1.0" and r["prefixe"] == 24
    assert r["binaire_adresse"] == "11000000.10101000.00000001.00001010"


def test_cidr_info_30():
    r = cidr_info("10.0.0.4/30")
    assert (r["premier_hote"], r["dernier_hote"], r["nb_hotes"]) == ("10.0.0.5", "10.0.0.6", 2)
    assert r["broadcast"] == "10.0.0.7"


def test_cidr_info_31_rfc3021():
    r = cidr_info("10.0.0.0/31")
    assert r["nb_hotes"] == 2
    assert r["premier_hote"] == "10.0.0.0"
    assert r["dernier_hote"] == r["broadcast"] == "10.0.0.1"


def test_cidr_info_32():
    r = cidr_info("10.0.0.7/32")
    assert r["nb_hotes"] == 1
    assert r["premier_hote"] == r["dernier_hote"] == r["broadcast"] == "10.0.0.7"
    assert r["masque"] == "255.255.255.255"


def test_cidr_info_0():
    r = cidr_info("0.0.0.0/0")
    assert r["nb_hotes"] == 2 ** 32 - 2
    assert r["masque"] == "0.0.0.0"
    assert r["binaire_masque"] == "00000000.00000000.00000000.00000000"


def test_cidr_info_espaces_tolere():
    assert cidr_info("  10.0.0.0/8 ")["reseau"] == "10.0.0.0"


@pytest.mark.parametrize("valeur", ["", "   ", "abc", "300.1.1.0/24", "10.0.0/24", "10.0.0.0", None, 24,
                                    "::1/64", "10.0.0.0/24/8", "/24"])
def test_cidr_info_reseau_invalide(valeur):
    with pytest.raises(NetplanError) as e:
        cidr_info(valeur)
    message_fr(e)


@pytest.mark.parametrize("valeur", ["10.0.0.0/33", "10.0.0.0/-1", "10.0.0.0/abc", "10.0.0.0/",
                                    "10.0.0.0/255.255.255.0", "10.0.0.0/24.5"])
def test_cidr_info_prefixe_incoherent(valeur):
    with pytest.raises(NetplanError) as e:
        cidr_info(valeur)
    assert "Préfixe incohérent" in message_fr(e)


def test_netplan_error_est_valueerror():
    assert issubclass(NetplanError, ValueError)


# ----------------------------------------------------------------------- vlsm

def test_vlsm_exemple_reference():
    r = vlsm("192.168.10.0/24", [
        {"nom": "Serveurs", "hotes": 50},
        {"nom": "Postes", "hotes": 20},
        {"nom": "Admin", "hotes": 10},
    ])
    assert r["parent"] == "192.168.10.0/24"
    assert [a["reseau"] for a in r["allocations"]] == [
        "192.168.10.0/26", "192.168.10.64/27", "192.168.10.96/28"]
    assert r["allocations"][0] == {
        "nom": "Serveurs", "hotes_demandes": 50, "reseau": "192.168.10.0/26", "prefixe": 26,
        "masque": "255.255.255.192", "premier_hote": "192.168.10.1", "dernier_hote": "192.168.10.62",
        "broadcast": "192.168.10.63", "capacite": 62,
    }
    assert r["libres"] == ["192.168.10.112/28", "192.168.10.128/25"]
    assert r["taux_occupation"] == 43.8  # 112 / 256


def test_vlsm_ordre_decroissant_et_egalite_ordre_saisie():
    r = vlsm("10.0.0.0/24", [
        {"nom": "petit", "hotes": 5},
        {"nom": "A", "hotes": 20},
        {"nom": "gros", "hotes": 100},
        {"nom": "B", "hotes": 20},
    ])
    assert [a["nom"] for a in r["allocations"]] == ["gros", "A", "B", "petit"]
    assert [a["reseau"] for a in r["allocations"]] == [
        "10.0.0.0/25", "10.0.0.128/27", "10.0.0.160/27", "10.0.0.192/29"]


def test_vlsm_plus_petit_bloc_suffisant():
    attendu = {1: 30, 2: 30, 3: 29, 6: 29, 7: 28, 14: 28, 15: 27, 30: 27, 31: 26, 62: 26, 63: 25, 126: 25,
               127: 24, 254: 24, 255: 23}
    for hotes, pref in attendu.items():
        r = vlsm("10.0.0.0/16", [{"nom": "x", "hotes": hotes}])
        assert r["allocations"][0]["prefixe"] == pref, hotes
        assert 2 ** (32 - pref) - 2 >= hotes


def test_vlsm_parent_complet_sans_libre():
    r = vlsm("10.0.0.0/24", [{"nom": "a", "hotes": 126}, {"nom": "b", "hotes": 126}])
    assert r["libres"] == []
    assert r["taux_occupation"] == 100.0


def test_vlsm_pas_de_chevauchement_et_dans_parent():
    besoins = [{"nom": f"n{i}", "hotes": h} for i, h in enumerate([3, 70, 12, 1, 30, 9, 2, 40])]
    r = vlsm("172.16.0.0/22", besoins)
    parent = ipaddress.ip_network(r["parent"])
    reseaux = [ipaddress.ip_network(a["reseau"]) for a in r["allocations"]]
    reseaux += [ipaddress.ip_network(x) for x in r["libres"]]
    for i, a in enumerate(reseaux):
        assert a.subnet_of(parent)
        for b in reseaux[i + 1:]:
            assert not a.overlaps(b)
    assert sum(n.num_addresses for n in reseaux) == parent.num_addresses


def test_vlsm_parent_avec_bits_hote_normalise():
    assert vlsm("192.168.10.77/24", [{"nom": "a", "hotes": 10}])["parent"] == "192.168.10.0/24"


def test_vlsm_taux_arrondi_une_decimale():
    r = vlsm("10.0.0.0/22", [{"nom": "a", "hotes": 2}])  # 4 / 1024 = 0,39 %
    assert r["taux_occupation"] == 0.4


def test_vlsm_nom_espaces_retires():
    assert vlsm("10.0.0.0/24", [{"nom": "  Wifi ", "hotes": 5}])["allocations"][0]["nom"] == "Wifi"


def test_vlsm_besoins_impossibles_total():
    with pytest.raises(NetplanError) as e:
        vlsm("192.168.10.0/24", [{"nom": "a", "hotes": 100}, {"nom": "b", "hotes": 100}, {"nom": "c", "hotes": 10}])
    assert "impossibles" in message_fr(e)


def test_vlsm_besoin_trop_gros_pour_parent():
    with pytest.raises(NetplanError) as e:
        vlsm("192.168.10.0/24", [{"nom": "gros", "hotes": 300}])
    assert "impossibles" in message_fr(e)
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/8", [{"nom": "énorme", "hotes": 10 ** 12}])
    assert "impossibles" in message_fr(e)


def test_vlsm_parent_trop_petit():
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/32", [{"nom": "a", "hotes": 1}])
    assert "impossibles" in message_fr(e)


@pytest.mark.parametrize("hotes", [0, -5])
def test_vlsm_besoin_nul_ou_negatif(hotes):
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/24", [{"nom": "a", "hotes": hotes}])
    assert "strictement positif" in message_fr(e)


@pytest.mark.parametrize("nom", ["", "   ", None, 5])
def test_vlsm_nom_vide(nom):
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/24", [{"nom": nom, "hotes": 5}])
    assert "nom" in message_fr(e)


def test_vlsm_nom_absent():
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/24", [{"hotes": 5}])
    message_fr(e)


@pytest.mark.parametrize("hotes", ["10", 2.5, True, None])
def test_vlsm_hotes_type_invalide(hotes):
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/24", [{"nom": "a", "hotes": hotes}])
    assert "entier" in message_fr(e)


def test_vlsm_reseau_parent_invalide():
    with pytest.raises(NetplanError) as e:
        vlsm("pas-un-reseau", [{"nom": "a", "hotes": 5}])
    message_fr(e)


def test_vlsm_prefixe_parent_incoherent():
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/40", [{"nom": "a", "hotes": 5}])
    assert "Préfixe incohérent" in message_fr(e)


@pytest.mark.parametrize("besoins", [[], None, "x", {"nom": "a"}, [3], [None]])
def test_vlsm_liste_besoins_invalide(besoins):
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/24", besoins)
    message_fr(e)


def test_vlsm_limite_256_besoins():
    ok = [{"nom": f"n{i}", "hotes": 1} for i in range(256)]
    assert len(vlsm("10.0.0.0/16", ok)["allocations"]) == 256
    with pytest.raises(NetplanError) as e:
        vlsm("10.0.0.0/8", ok + [{"nom": "de trop", "hotes": 1}])
    assert "Trop de besoins" in message_fr(e)


# ------------------------------------------------------------------ decoupage

def test_decoupage_par_n():
    r = decoupage("192.168.0.0/24", n=4)
    assert r == {
        "reseau": "192.168.0.0/24",
        "prefixe_cible": 26,
        "nombre_total": 4,
        "sous_reseaux": ["192.168.0.0/26", "192.168.0.64/26", "192.168.0.128/26", "192.168.0.192/26"],
        "tronque": False,
    }


def test_decoupage_n_arrondi_puissance_de_2():
    r = decoupage("192.168.0.0/24", n=5)
    assert r["prefixe_cible"] == 27
    assert r["nombre_total"] == 8
    assert len(r["sous_reseaux"]) == 8
    assert decoupage("10.0.0.0/24", n=1)["sous_reseaux"] == ["10.0.0.0/24"]
    assert decoupage("10.0.0.0/24", n=3)["prefixe_cible"] == 26


def test_decoupage_par_prefixe():
    r = decoupage("10.0.0.0/16", prefixe=18)
    assert r["prefixe_cible"] == 18
    assert r["nombre_total"] == 4
    assert r["sous_reseaux"] == ["10.0.0.0/18", "10.0.64.0/18", "10.0.128.0/18", "10.0.192.0/18"]


def test_decoupage_prefixe_egal_reseau():
    assert decoupage("10.0.0.0/24", prefixe=24)["sous_reseaux"] == ["10.0.0.0/24"]


def test_decoupage_reseau_normalise():
    assert decoupage("10.0.0.9/24", n=2)["reseau"] == "10.0.0.0/24"


def test_decoupage_plafond_tronque():
    assert LIMITE_SOUS_RESEAUX == 256
    r = decoupage("10.0.0.0/8", prefixe=24)
    assert r["nombre_total"] == 65536
    assert len(r["sous_reseaux"]) == 256
    assert r["tronque"] is True
    assert r["sous_reseaux"][0] == "10.0.0.0/24" and r["sous_reseaux"][-1] == "10.0.255.0/24"
    exact = decoupage("10.0.0.0/16", prefixe=24)
    assert exact["nombre_total"] == 256 and len(exact["sous_reseaux"]) == 256 and exact["tronque"] is False


def test_decoupage_enorme_rapide():
    r = decoupage("0.0.0.0/0", prefixe=32)
    assert r["nombre_total"] == 2 ** 32
    assert len(r["sous_reseaux"]) == 256 and r["tronque"] is True


@pytest.mark.parametrize("n", [0, -3])
def test_decoupage_n_impossible_nul_negatif(n):
    with pytest.raises(NetplanError) as e:
        decoupage("10.0.0.0/24", n=n)
    assert "impossible" in message_fr(e)


def test_decoupage_n_trop_grand():
    with pytest.raises(NetplanError) as e:
        decoupage("10.0.0.0/24", n=257)
    assert "impossible" in message_fr(e)
    assert decoupage("10.0.0.0/24", n=256)["prefixe_cible"] == 32
    with pytest.raises(NetplanError):
        decoupage("10.0.0.1/32", n=2)


@pytest.mark.parametrize("n", ["4", 2.0, True])
def test_decoupage_n_type_invalide(n):
    with pytest.raises(NetplanError) as e:
        decoupage("10.0.0.0/24", n=n)
    assert "entier" in message_fr(e)


@pytest.mark.parametrize("prefixe", [33, 64, -1, 23, 8])
def test_decoupage_prefixe_incoherent(prefixe):
    with pytest.raises(NetplanError) as e:
        decoupage("10.0.0.0/24", prefixe=prefixe)
    assert "incohérent" in message_fr(e)


def test_decoupage_prefixe_type_invalide():
    with pytest.raises(NetplanError) as e:
        decoupage("10.0.0.0/24", prefixe="26")
    message_fr(e)


def test_decoupage_exactement_un_parametre():
    with pytest.raises(NetplanError) as e:
        decoupage("10.0.0.0/24")
    assert "exactement" in message_fr(e)
    with pytest.raises(NetplanError):
        decoupage("10.0.0.0/24", n=2, prefixe=26)


def test_decoupage_reseau_invalide():
    with pytest.raises(NetplanError) as e:
        decoupage("10.0.0.0/99", n=2)
    message_fr(e)
    with pytest.raises(NetplanError) as e:
        decoupage("zzz", prefixe=24)
    message_fr(e)


# ---------------------------------------------------------------- appartenance

def test_appartenance_oui_non():
    assert appartenance("192.168.1.77", "192.168.1.0/24") == {
        "ip": "192.168.1.77", "reseau": "192.168.1.0/24", "appartient": True}
    assert appartenance("192.168.2.1", "192.168.1.0/24")["appartient"] is False


def test_appartenance_bornes_et_normalisation():
    assert appartenance("192.168.1.0", "192.168.1.5/24")["appartient"] is True
    assert appartenance("192.168.1.255", "192.168.1.0/24")["appartient"] is True
    assert appartenance("192.168.1.5", "192.168.1.5/24")["reseau"] == "192.168.1.0/24"
    assert appartenance("10.1.2.3", "0.0.0.0/0")["appartient"] is True


@pytest.mark.parametrize("ip", ["", "10.0.0", "10.0.0.256", "abc", "10.0.0.1/24", None, "::1"])
def test_appartenance_ip_invalide(ip):
    with pytest.raises(NetplanError) as e:
        appartenance(ip, "10.0.0.0/8")
    assert "adresse" in message_fr(e)


def test_appartenance_reseau_invalide():
    with pytest.raises(NetplanError) as e:
        appartenance("10.0.0.1", "10.0.0.0/40")
    assert "Préfixe incohérent" in message_fr(e)
    with pytest.raises(NetplanError) as e:
        appartenance("10.0.0.1", "nimporte")
    message_fr(e)


# --------------------------------------------------------------- chevauchement

def test_chevauchement_inclusion_et_disjoint():
    assert chevauchement("10.0.0.0/8", "10.1.0.0/16") == {
        "a": "10.0.0.0/8", "b": "10.1.0.0/16", "chevauchement": True}
    assert chevauchement("10.1.0.0/16", "10.0.0.0/8")["chevauchement"] is True
    assert chevauchement("10.0.0.0/24", "10.0.0.0/24")["chevauchement"] is True
    assert chevauchement("10.0.0.0/24", "10.0.1.0/24")["chevauchement"] is False
    assert chevauchement("192.168.0.0/16", "172.16.0.0/12")["chevauchement"] is False


def test_chevauchement_adjacents_et_normalisation():
    assert chevauchement("10.0.0.0/25", "10.0.0.128/25")["chevauchement"] is False
    r = chevauchement("10.0.0.5/24", "10.0.0.200/25")
    assert r["a"] == "10.0.0.0/24" and r["b"] == "10.0.0.128/25" and r["chevauchement"] is True


def test_chevauchement_invalide():
    with pytest.raises(NetplanError) as e:
        chevauchement("10.0.0.0/24", "n'importe quoi")
    assert "réseau B" in message_fr(e)
    with pytest.raises(NetplanError) as e:
        chevauchement("10.0.0.0/24/3", "10.0.0.0/24")
    message_fr(e)
    with pytest.raises(NetplanError) as e:
        chevauchement("10.0.0.0/35", "10.0.0.0/24")
    assert "Préfixe incohérent" in message_fr(e)


# ------------------------------------------------------------------- structure

def test_calc_stdlib_uniquement():
    source = Path(calc.__file__).read_text(encoding="utf-8")
    imports = [l.split()[1] for l in source.splitlines() if l.startswith(("import ", "from "))]
    assert set(imports) <= {"ipaddress", "itertools"}
