# -*- coding: utf-8 -*-
"""Tests pytest de ``subnet-calc`` — reproduits de SPEC.md §6 (v1.0, 2026-11-05).

Chaque cas de test de la SPEC (TC-1 à TC-5) est testé au niveau de la CLI
(par sous-processus, comme un utilisateur) avec des assertions strictes :
sortie stdout exacte, stderr exact, code de sortie exact — valeur entière,
jamais une vérification partielle. S'ajoutent :

* TC-6 (bonus de la SPEC §6) — découpage impossible (code 2) ;
* un test d'entrée invalide supplémentaire (IP hors plage ``300.1.1.0/24``)
  vérifiant le contrat d'erreur de SPEC §3.2 : une ligne unique
  « Erreur : <raison> » sur stderr, stdout vide, code de sortie 1.

Aucune modification du code source ni de SPEC.md : ce fichier ajoute
uniquement des tests.
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


# ---------------------------------------------------------------------------
# TC-1 — Découpage simple en 2 sous-réseaux (SPEC §6, sortie exacte)
# ---------------------------------------------------------------------------

def test_tc1_simple_split_into_two_subnets():
    """TC-1 : ``192.168.1.0/24 -n 2`` → 2 lignes pipe, en-tête, code 0."""
    rc, out, err = run_calc("192.168.1.0/24", "-n", "2")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "2 sous-réseaux de 192.168.1.0/24 :\n"
        "192.168.1.0/25 | 255.255.255.128 | 192.168.1.1-192.168.1.126"
        " | 192.168.1.127\n"
        "192.168.1.128/25 | 255.255.255.128 | 192.168.1.129-192.168.1.254"
        " | 192.168.1.255\n"
    ), "stdout TC-1 différent de la sortie exacte de SPEC §6"


# ---------------------------------------------------------------------------
# TC-2 — Découpage en 4 sous-réseaux (SPEC §6, sortie exacte)
# ---------------------------------------------------------------------------

def test_tc2_split_into_four_subnets():
    """TC-2 : ``10.0.0.0/24 -n 4`` → 4 lignes pipe ordonnées, code 0."""
    rc, out, err = run_calc("10.0.0.0/24", "-n", "4")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "4 sous-réseaux de 10.0.0.0/24 :\n"
        "10.0.0.0/26 | 255.255.255.192 | 10.0.0.1-10.0.0.62 | 10.0.0.63\n"
        "10.0.0.64/26 | 255.255.255.192 | 10.0.0.65-10.0.0.126 | 10.0.0.127\n"
        "10.0.0.128/26 | 255.255.255.192 | 10.0.0.129-10.0.0.190 | 10.0.0.191\n"
        "10.0.0.192/26 | 255.255.255.192 | 10.0.0.193-10.0.0.254 | 10.0.0.255\n"
    ), "stdout TC-2 différent de la sortie exacte de SPEC §6"


# ---------------------------------------------------------------------------
# TC-3 — /24 en /26, mode masque (SPEC §6 : identique à TC-2)
# ---------------------------------------------------------------------------

def test_tc3_target_mask_mode_matches_tc2():
    """TC-3 : ``192.168.1.0/24 -m 26`` → la même sortie exacte que TC-2."""
    rc, out, err = run_calc("192.168.1.0/24", "-m", "26")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "4 sous-réseaux de 192.168.1.0/24 :\n"
        "192.168.1.0/26 | 255.255.255.192 | 192.168.1.1-192.168.1.62"
        " | 192.168.1.63\n"
        "192.168.1.64/26 | 255.255.255.192 | 192.168.1.65-192.168.1.126"
        " | 192.168.1.127\n"
        "192.168.1.128/26 | 255.255.255.192 | 192.168.1.129-192.168.1.190"
        " | 192.168.1.191\n"
        "192.168.1.192/26 | 255.255.255.192 | 192.168.1.193-192.168.1.254"
        " | 192.168.1.255\n"
    ), "stdout TC-3 différent de la sortie exacte de SPEC §6 (≡ TC-2)"


# ---------------------------------------------------------------------------
# TC-4 — Cas limite : découpage en 1 sous-réseau (SPEC §6, sortie exacte)
# ---------------------------------------------------------------------------

def test_tc4_split_into_one_subnet():
    """TC-4 : ``192.168.1.0/24 -n 1`` → un bloc identique au réseau."""
    rc, out, err = run_calc("192.168.1.0/24", "-n", "1")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "1 sous-réseaux de 192.168.1.0/24 :\n"
        "192.168.1.0/24 | 255.255.255.0 | 192.168.1.1-192.168.1.254"
        " | 192.168.1.255\n"
    ), "stdout TC-4 différent de la sortie exacte de SPEC §6"


# ---------------------------------------------------------------------------
# TC-5 — Entrée invalide : bits d'hôte non nuls (SPEC §6, erreur exacte)
# ---------------------------------------------------------------------------

def test_tc5_invalid_cidr_host_bits():
    """TC-5 : ``192.168.1.5/24 -n 2`` → stderr exact, stdout vide, code 1."""
    rc, out, err = run_calc("192.168.1.5/24", "-n", "2")
    assert rc == 1, "code de sortie attendu 1 (entrée invalide), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err == "Erreur : bits d'hôte non nuls dans 192.168.1.5/24\n", (
        "stderr TC-5 différent du message exact de SPEC §6 : %r" % err
    )


# ---------------------------------------------------------------------------
# TC-6 (bonus) — Découpage impossible (SPEC §6, erreur exacte)
# ---------------------------------------------------------------------------

def test_tc6_decoupage_impossible():
    """TC-6 : ``192.168.1.0/24 -m 24`` → stderr exact, stdout vide, code 2."""
    rc, out, err = run_calc("192.168.1.0/24", "-m", "24")
    assert rc == 2, "code de sortie attendu 2 (découpage impossible), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err == "Erreur : découpage impossible\n", (
        "stderr TC-6 différent du message exact de SPEC §6 : %r" % err
    )


# ---------------------------------------------------------------------------
# Entrée invalide supplémentaire : IP hors plage (contrat SPEC §3.2)
# ---------------------------------------------------------------------------

def test_extra_invalid_ip_octet_out_of_range():
    """``300.1.1.0/24 -n 2`` → erreur propre : code 1, stdout vide,
    ligne unique « Erreur : <raison> » sur stderr (SPEC §3.2)."""
    rc, out, err = run_calc("300.1.1.0/24", "-n", "2")
    assert rc == 1, "code de sortie attendu 1 (entrée invalide), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err.startswith("Erreur : "), (
        "stderr attendu sur une ligne « Erreur : <raison> », obtenu : %r" % err
    )
    assert err.count("\n") == 1, (
        "stderr attendu sur une seule ligne, obtenu : %r" % err
    )
    assert "300.1.1.0/24" in err, (
        "stderr attendu citant l'entrée fautive, obtenu : %r" % err
    )
