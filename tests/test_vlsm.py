# -*- coding: utf-8 -*-
"""Tests pytest du mode VLSM (``--vlsm``) de ``subnet-calc`` — SPEC.md v1.1.

Vérifie la conformité du mode ``--vlsm`` (SPEC.md §3.3, §4.3 et cas de
test V1–V4 de la §6) au niveau de la CLI : chaque cas est exécuté par
sous-processus, comme un utilisateur, avec des assertions strictes —
sortie stdout exacte, stderr exact, code de sortie exact.

Cas de la mission de vérification :

* V1 — cas de référence : besoins 50, 20, 10 dans un /24 (code 0,
  trois lignes exactes en ordre d'allocation, la plus grande d'abord) ;
* V2 — ajustement exact puis bloc minimal : ``62,1`` → un /26
  (62 + 2 = 64, ajustement parfait) puis un /30 pour le besoin 1 ;
* V3 — sortie JSON d'un seul objet (``--vlsm 50 --format json``),
  gabarit exact de la SPEC §4.2 (``plage_hotes`` inline sur une ligne),
  redondé par un contrôle sémantique via :func:`json.loads` ;
* V4 — capacité dépassée : ``200,100`` → code 2, stdout vide, stderr
  exact « Erreur : découpage impossible » (SPEC §3.3, règle 4) ;
* V5 — validations complémentaires (code 1, stdout vide, une ligne
  unique « Erreur : <raison> » sur stderr, SPEC §3.2/§3.3) : token non
  entier, exclusivité avec ``-n``, besoin ``0``.

S'ajoutent deux contrôles de non-régression documentaire :

* ``--help`` documente le mode ``--vlsm`` avec un exemple (SPEC §2.3, §2.5) ;
* SPEC.md est en version 1.1 et porte la section VLSM (§3.3, §4.3).

Aucune modification du code source ni de SPEC.md : ce fichier ajoute
uniquement des tests.
"""

import json
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
# V1 — Cas de référence : 3 besoins 50,20,10 dans un /24 (code 0)
# ---------------------------------------------------------------------------

def test_v1_vlsm_reference_trois_besoins():
    """V1 : ``192.168.1.0/24 --vlsm 50,20,10`` → en-tête + 3 lignes exactes.

    Allocation décroissante (SPEC §4.3) : 50 → /26 (52 ≤ 64), 20 → /27
    (22 ≤ 32), 10 → /28 (12 ≤ 16) ; blocs séquentiels depuis la base.
    """
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50,20,10")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "3 sous-réseaux de 192.168.1.0/24 :\n"
        "192.168.1.0/26 | 255.255.255.192 | 192.168.1.1-192.168.1.62"
        " | 192.168.1.63\n"
        "192.168.1.64/27 | 255.255.255.224 | 192.168.1.65-192.168.1.94"
        " | 192.168.1.95\n"
        "192.168.1.96/28 | 255.255.255.240 | 192.168.1.97-192.168.1.110"
        " | 192.168.1.111\n"
    ), "stdout V1 différent des 4 lignes exactes de la mission (SPEC §6 V1)"


# ---------------------------------------------------------------------------
# V2 — Ajustement exact (62 → /26) puis bloc minimal (1 → /30)
# ---------------------------------------------------------------------------

def test_v2_vlsm_ajustement_exact_puis_bloc_minimal():
    """V2 : ``10.0.0.0/24 --vlsm 62,1`` → un /26 (62+2=64 exactement)
    à 10.0.0.0 puis un /30 à 10.0.0.64 (hôtes .65-.66, broadcast .67)."""
    rc, out, err = run_calc("10.0.0.0/24", "--vlsm", "62,1")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    assert out == (
        "2 sous-réseaux de 10.0.0.0/24 :\n"
        "10.0.0.0/26 | 255.255.255.192 | 10.0.0.1-10.0.0.62 | 10.0.0.63\n"
        "10.0.0.64/30 | 255.255.255.252 | 10.0.0.65-10.0.0.66 | 10.0.0.67\n"
    ), "stdout V2 différent des 3 lignes exactes attendues"


# ---------------------------------------------------------------------------
# V3 — Sortie JSON d'un seul objet (gabarit exact SPEC §4.2)
# ---------------------------------------------------------------------------

def test_v3_vlsm_json_un_seul_objet():
    """V3 : ``192.168.1.0/24 --vlsm 50 --format json`` → un objet /26.

    Gabarit exact de la SPEC §4.2 : indent 2, clés indentées de 4,
    ``plage_hotes`` en tableau inline sur une seule ligne ; redondé par
    un contrôle sémantique :func:`json.loads` (tableau d'un seul objet,
    clés et valeurs attendues).
    """
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50", "--format", "json")
    assert rc == 0, "code de sortie attendu 0, obtenu %d" % rc
    assert err == "", "stderr attendu vide, obtenu : %r" % err
    # Gabarit exact §4.2 (plage_hotes inline sur une ligne).
    assert out == (
        "[\n"
        "  {\n"
        '    "cidr": "192.168.1.0/26",\n'
        '    "masque": "255.255.255.192",\n'
        '    "plage_hotes": ["192.168.1.1", "192.168.1.62"],\n'
        '    "broadcast": "192.168.1.63"\n'
        "  }\n"
        "]\n"
    ), "stdout V3 différent du gabarit JSON exact de SPEC §4.2"
    # Contrôle sémantique redondant : JSON valide, un seul objet /26.
    donnees = json.loads(out)
    assert donnees == [
        {
            "cidr": "192.168.1.0/26",
            "masque": "255.255.255.192",
            "plage_hotes": ["192.168.1.1", "192.168.1.62"],
            "broadcast": "192.168.1.63",
        }
    ], "JSON V3 différent de l'objet /26 attendu (SPEC §4.2)"


# ---------------------------------------------------------------------------
# V4 — Capacité dépassée : découpage impossible (code 2)
# ---------------------------------------------------------------------------

def test_v4_vlsm_decoupage_impossible():
    """V4 : ``192.168.1.0/24 --vlsm 200,100`` → code 2, stderr exact.

    200 hôtes → /24 entier (256 adresses), le /25 requis pour 100 ne
    tient plus (SPEC §3.3, règle 4) : stdout vide, une seule ligne
    « Erreur : découpage impossible » sur stderr, code 2.
    """
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "200,100")
    assert rc == 2, "code de sortie attendu 2 (découpage impossible), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err == "Erreur : découpage impossible\n", (
        "stderr V4 différent du message exact : %r" % err
    )


# ---------------------------------------------------------------------------
# V5 — Validations complémentaires : code 1, une ligne « Erreur : … »
# ---------------------------------------------------------------------------

def test_v5_vlsm_besoin_non_entier():
    """V5a : ``--vlsm 50,abc`` → code 1, stdout vide, une ligne « Erreur : … »
    citant le token fautif (SPEC §3.3 : chaque token doit être un entier)."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50,abc")
    assert rc == 1, "code de sortie attendu 1 (entrée invalide), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err.startswith("Erreur : "), (
        "stderr attendu sur une ligne « Erreur : <raison> », obtenu : %r" % err
    )
    assert err.count("\n") == 1, (
        "stderr attendu sur une seule ligne, obtenu : %r" % err
    )
    assert "abc" in err, (
        "stderr attendu citant le token fautif « abc », obtenu : %r" % err
    )


def test_v5_vlsm_exclusif_avec_n():
    """V5b : ``--vlsm 50 -n 2`` → code 1 : --vlsm est exclusif avec -n
    (SPEC §2.3 et §3.3)."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "50", "-n", "2")
    assert rc == 1, "code de sortie attendu 1 (entrée invalide), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err.startswith("Erreur : "), (
        "stderr attendu sur une ligne « Erreur : <raison> », obtenu : %r" % err
    )
    assert err.count("\n") == 1, (
        "stderr attendu sur une seule ligne, obtenu : %r" % err
    )
    assert "exclusif" in err or "exclusives" in err, (
        "stderr attendu mentionnant l'exclusivité des options, obtenu : %r" % err
    )


def test_v5_vlsm_besoin_zero():
    """V5c : ``--vlsm 0`` → code 1 : un besoin doit être strictement
    positif (SPEC §3.3)."""
    rc, out, err = run_calc("192.168.1.0/24", "--vlsm", "0")
    assert rc == 1, "code de sortie attendu 1 (entrée invalide), obtenu %d" % rc
    assert out == "", "stdout attendu vide, obtenu : %r" % out
    assert err.startswith("Erreur : "), (
        "stderr attendu sur une ligne « Erreur : <raison> », obtenu : %r" % err
    )
    assert err.count("\n") == 1, (
        "stderr attendu sur une seule ligne, obtenu : %r" % err
    )


# ---------------------------------------------------------------------------
# Non-régression documentaire : --help et SPEC.md v1.1
# ---------------------------------------------------------------------------

def test_help_documente_mode_vlsm():
    """``--help`` sort avec 0 et documente --vlsm avec un exemple
    (SPEC §2.3, §2.5)."""
    rc, out, err = run_calc("--help")
    assert rc == 0, "code de sortie attendu 0 pour --help, obtenu %d" % rc
    assert err == "", "stderr attendu vide pour --help, obtenu : %r" % err
    assert "--vlsm BESOINS" in out, (
        "l'usage dans --help doit présenter --vlsm BESOINS, obtenu : %r" % out
    )
    assert "50,20,10" in out, (
        "l'aide de --vlsm doit donner un exemple de besoins, obtenu : %r" % out
    )
    assert "exclusif avec -n et -m" in out, (
        "l'aide de --vlsm doit documenter son exclusivité, obtenu : %r" % out
    )


def test_spec_v1_1_documente_vlsm():
    """SPEC.md est en version 1.1 et porte la section VLSM (§3.3, §4.3,
    cas V1–V4 de §6)."""
    spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    assert "Version : 1.1" in spec, (
        "SPEC.md doit être en version 1.1 (en-tête « Version : 1.1 »)"
    )
    assert "### 3.3 Mode VLSM" in spec, (
        "SPEC.md doit porter la section §3.3 « Mode VLSM (--vlsm BESOINS) »"
    )
    assert "### 4.3 Ordre de sortie en mode VLSM" in spec, (
        "SPEC.md doit porter la section §4.3 (ordre d'allocation)"
    )
    for cas in ("V1 (v1.1)", "V2 (v1.1)", "V3 (v1.1)", "V4 (v1.1)"):
        assert cas in spec, (
            "SPEC.md §6 doit porter le cas de test %s" % cas
        )
