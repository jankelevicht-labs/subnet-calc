# -*- coding: utf-8 -*-
"""Tests pytest de l'option ``--vlsm`` — carte t_f59d4d5d (vérification).

Couverture TV-1 à TV-12 (SPEC v1.1 §6) : chaque cas est testé au niveau
de la CLI par sous-processus, comme un utilisateur, avec des assertions
strictes — stdout exact (jamais partiel), stderr exact, code de sortie
exact. S'ajoutent deux contrôles bonus (TV-11 : espaces tolérés dans
BESOINS ; TV-12 : ``--help`` documente l'option).

Ce fichier n'ajoute que des tests : aucune modification de
``subnet_calc.py`` ni de ``SPEC.md``.
"""

import subprocess
from pathlib import Path

# Racine du dépôt : là où vivent subnet_calc.py et SPEC.md.
ROOT = Path(__file__).resolve().parents[1]


def run_calc(*args):
    """Exécute ``python3 subnet_calc.py <args>`` depuis la racine du dépôt.

    Returns:
        (code de sortie, stdout, stderr) décodés en UTF-8 (la CLI force
        l'UTF-8 sur ses flux, SPEC §4.2).
    """
    proc = subprocess.run(
        ["python3", "subnet_calc.py", *args],
        cwd=str(ROOT),
        capture_output=True,
    )
    return (
        proc.returncode,
        proc.stdout.decode("utf-8"),
        proc.stderr.decode("utf-8"),
    )


# Sortie exacte attendue pour 3 sous-réseaux 50,20,10 (TV-1 / TV-2 / TV-11).
_SORTIE_VLSM_3 = (
    "3 sous-réseaux de 192.168.1.0/24 :\n"
    "192.168.1.0/26 | 255.255.255.192 | 192.168.1.1-192.168.1.62"
    " | 192.168.1.63\n"
    "192.168.1.64/27 | 255.255.255.224 | 192.168.1.65-192.168.1.94"
    " | 192.168.1.95\n"
    "192.168.1.96/28 | 255.255.255.240 | 192.168.1.97-192.168.1.110"
    " | 192.168.1.111\n"
)


# ---------------------------------------------------------------------------
# TV-1 — Allocation VLSM du plus grand au plus petit (SPEC §6, TV-1)
# ---------------------------------------------------------------------------

def test_tv1_vlsm_descending_allocation():
    """TV-1 : ``192.168.1.0/24 --vlsm 50,20,10`` → /26, /27, /28, code 0."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50,20,10")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == _SORTIE_VLSM_3, (
        "stdout TV-1 différent de la sortie exacte de SPEC §6 : %r" % out
    )


# ---------------------------------------------------------------------------
# TV-2 — L'ordre d'entrée des besoins n'a pas d'importance (SPEC §6, TV-2)
# ---------------------------------------------------------------------------

def test_tv2_input_order_irrelevant():
    """TV-2 : ``--vlsm 10,50,20`` → stdout identique à TV-1 (tri décroissant)."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "10,50,20")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == _SORTIE_VLSM_3, (
        "stdout TV-2 attendu identique à TV-1 (tri décroissant), obtenu : %r"
        % out
    )


# ---------------------------------------------------------------------------
# TV-3 — Sortie JSON (schéma existant : indent 2, plage_hotes inline)
# ---------------------------------------------------------------------------

def test_tv3_json_output_exact():
    """TV-3 : ``--vlsm 50,20,10 -f json`` → JSON exact, code 0."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50,20,10",
                            "-f", "json")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "[\n"
        "  {\n"
        '    "cidr": "192.168.1.0/26",\n'
        '    "masque": "255.255.255.192",\n'
        '    "plage_hotes": ["192.168.1.1", "192.168.1.62"],\n'
        '    "broadcast": "192.168.1.63"\n'
        "  },\n"
        "  {\n"
        '    "cidr": "192.168.1.64/27",\n'
        '    "masque": "255.255.255.224",\n'
        '    "plage_hotes": ["192.168.1.65", "192.168.1.94"],\n'
        '    "broadcast": "192.168.1.95"\n'
        "  },\n"
        "  {\n"
        '    "cidr": "192.168.1.96/28",\n'
        '    "masque": "255.255.255.240",\n'
        '    "plage_hotes": ["192.168.1.97", "192.168.1.110"],\n'
        '    "broadcast": "192.168.1.111"\n'
        "  }\n"
        "]\n"
    ), "stdout TV-3 (JSON) différent de la sortie exacte attendue : %r" % out


# ---------------------------------------------------------------------------
# TV-4 (cas impossible) — Capacité insuffisante (SPEC §6, TV-4)
# ---------------------------------------------------------------------------

def test_tv4_impossible_insufficient_capacity():
    """TV-4 : ``--vlsm 300`` → code 2, stdout vide, stderr exact."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "300")
    assert rc == 2, "code de sortie attendu 2 (découpage impossible), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err == "Erreur : découpage impossible\n", (
        "stderr TV-4 différent du message exact de SPEC §6 : %r" % err
    )


# ---------------------------------------------------------------------------
# TV-5 (cas impossible) — Échec par accumulation (SPEC §6, TV-5)
# ---------------------------------------------------------------------------

def test_tv5_impossible_by_accumulation():
    """TV-5 : ``--vlsm 100,100,100`` → code 2, même stderr, stdout vide."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "100,100,100")
    assert rc == 2, "code de sortie attendu 2 (découpage impossible), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err == "Erreur : découpage impossible\n", (
        "stderr TV-5 différent du message exact de SPEC §6 : %r" % err
    )


# ---------------------------------------------------------------------------
# TV-6 — Exclusivité -n/--count et --vlsm (SPEC §3.2, code 1)
# ---------------------------------------------------------------------------

def test_tv6_mutually_exclusive_with_count():
    """TV-6 : ``--vlsm 50 -n 2`` → code 1, stdout vide, stderr exact."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50", "-n", "2")
    assert rc == 1, "code de sortie attendu 1, obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err == (
        "Erreur : les options -n/--count et --vlsm sont mutuellement "
        "exclusives\n"
    ), "stderr TV-6 différent du message exact : %r" % err


# ---------------------------------------------------------------------------
# TV-7 — BESOINS mal formés (3 variantes, SPEC §3.2, code 1)
# ---------------------------------------------------------------------------

def test_tv7_malformed_needs():
    """TV-7 : ``50,abc``, ``0``, ``50,,10`` → code 1, message exact citant
    la chaîne brute fournie."""
    for brut in ("50,abc", "0", "50,,10"):
        rc, out, err = run_calc("192.168.1.0/24", "--vlsm", brut)
        assert rc == 1, "code attendu 1 pour %r, obtenu %d" % (brut, rc)
        assert out == "", "stdout attendu vide pour %r" % brut
        attendu = (
            "Erreur : l'option --vlsm attend une liste d'entiers "
            "strictement positifs séparés par des virgules, "
            "« %s » fourni\n" % brut
        )
        assert err == attendu, (
            "stderr attendu exact pour %r, obtenu : %r" % (brut, err)
        )


# ---------------------------------------------------------------------------
# TV-8 — Jusqu'au /30 : besoin de 2 hôtes (SPEC §6, TV-8)
# ---------------------------------------------------------------------------

def test_tv8_down_to_slash30():
    """TV-8 : ``--vlsm 62,30,14,2`` → 4 sous-réseaux /26../30, code 0."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "62,30,14,2")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "4 sous-réseaux de 192.168.1.0/24 :\n"
        "192.168.1.0/26 | 255.255.255.192 | 192.168.1.1-192.168.1.62"
        " | 192.168.1.63\n"
        "192.168.1.64/27 | 255.255.255.224 | 192.168.1.65-192.168.1.94"
        " | 192.168.1.95\n"
        "192.168.1.96/28 | 255.255.255.240 | 192.168.1.97-192.168.1.110"
        " | 192.168.1.111\n"
        "192.168.1.112/30 | 255.255.255.252 | 192.168.1.113-192.168.1.114"
        " | 192.168.1.115\n"
    ), "stdout TV-8 différent de la sortie exacte de SPEC §6 : %r" % out


# ---------------------------------------------------------------------------
# TV-9 — Autre réseau source : 10.0.0.0/24 (SPEC §6, TV-9)
# ---------------------------------------------------------------------------

def test_tv9_other_source_network():
    """TV-9 : ``10.0.0.0/24 --vlsm 120,60`` → /25 + /26, code 0."""
    rc, out, err = run_calc("10.0.0.0/24", "--vlsm", "120,60")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "2 sous-réseaux de 10.0.0.0/24 :\n"
        "10.0.0.0/25 | 255.255.255.128 | 10.0.0.1-10.0.0.126"
        " | 10.0.0.127\n"
        "10.0.0.128/26 | 255.255.255.192 | 10.0.0.129-10.0.0.190"
        " | 10.0.0.191\n"
    ), "stdout TV-9 différent de la sortie exacte de SPEC §6 : %r" % out


# ---------------------------------------------------------------------------
# TV-10 — Cas limite : préfixe égal au préfixe source (SPEC §6, TV-10)
# ---------------------------------------------------------------------------

def test_tv10_prefix_equal_to_source():
    """TV-10 : ``--vlsm 254`` → le réseau lui-même, analogue à ``-n 1``."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "254")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "1 sous-réseaux de 192.168.1.0/24 :\n"
        "192.168.1.0/24 | 255.255.255.0 | 192.168.1.1-192.168.1.254"
        " | 192.168.1.255\n"
    ), "stdout TV-10 différent de la sortie exacte de SPEC §6 : %r" % out


# ---------------------------------------------------------------------------
# TV-11 (bonus) — Espaces tolérés autour des virgules (SPEC §6, TV-11)
# ---------------------------------------------------------------------------

def test_tv11_spaces_tolerated():
    """TV-11 : ``--vlsm "50, 20, 10"`` → stdout identique à TV-1."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50, 20, 10")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == _SORTIE_VLSM_3, (
        "stdout TV-11 attendu identique à TV-1 (espaces tolérés), "
        "obtenu : %r" % out
    )


# ---------------------------------------------------------------------------
# TV-12 (bonus) — ``--help`` documente --vlsm (SPEC §2.5)
# ---------------------------------------------------------------------------

def test_tv12_help_documents_vlsm():
    """TV-12 : ``--help`` → code 0 et stdout contient ``--vlsm`` et ``BESOINS``."""
    rc, out, err = run_calc("--help")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert "--vlsm" in out, "--help attendu sans mention de --vlsm"
    assert "BESOINS" in out, "--help attendu sans metavar BESOINS"
