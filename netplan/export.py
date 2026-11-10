# -*- coding: utf-8 -*-
"""NetPlan Studio — exports d'un plan VLSM (CSV, JSON, RouterOS), générés côté Python.

Chaque fonction reçoit le dictionnaire renvoyé par :func:`netplan.calc.vlsm`
(``parent``, ``allocations``, ``libres``, ``taux_occupation``) et renvoie le
texte du fichier à télécharger. Aucun calcul d'adresse ici : tout vient du plan.

* CSV : en-tête fixe, une ligne par allocation ; toute cellule texte qui
  commencerait par ``=``, ``+``, ``-``, ``@``, une tabulation ou un retour chariot
  est préfixée d'une apostrophe (neutralisation de l'injection de formules des
  tableurs).
* JSON : le plan complet, tel quel.
* RouterOS : **brouillon à vérifier** — une commande ``/ip address add`` par
  allocation, nom échappé (``"``, ``\\``, ``$``, ``[``, ``]``) et débarrassé de ses
  caractères de contrôle.
"""

import csv
import io
import json
import unicodedata

COLONNES_CSV = ("nom", "hotes_demandes", "reseau", "prefixe", "masque",
                "premier_hote", "dernier_hote", "broadcast", "capacite")

DEBUT_FORMULE = ("=", "+", "-", "@", "\t", "\r")

ENTETE_ROUTEROS = ("# BROUILLON À VÉRIFIER : configuration RouterOS générée par NetPlan Studio ; "
                   "relire, adapter l'interface (A_DEFINIR) et tester avant toute application.")

# Caractères de mise en forme bidirectionnelle : retirés des commentaires RouterOS (affichage trompeur).
_BIDI = frozenset("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def neutraliser_formule(valeur):
    """Texte de la cellule CSV : préfixé d'une apostrophe s'il pourrait être pris pour une formule."""
    texte = str(valeur)
    if texte.startswith(DEBUT_FORMULE):
        return "'" + texte
    return texte


def vers_csv(plan):
    sortie = io.StringIO(newline="")
    ecrivain = csv.writer(sortie, lineterminator="\r\n")
    ecrivain.writerow(COLONNES_CSV)
    for allocation in plan["allocations"]:
        ecrivain.writerow([neutraliser_formule(allocation[c]) for c in COLONNES_CSV])
    return sortie.getvalue()


def vers_json(plan):
    return json.dumps(plan, ensure_ascii=False, indent=2) + "\n"


def echapper_routeros(texte):
    """Contenu sûr pour un commentaire RouterOS entre guillemets (caractères de contrôle retirés)."""
    propre = "".join(
        c for c in str(texte)
        if unicodedata.category(c) not in ("Cc", "Zl", "Zp") and c not in _BIDI)
    resultat = []
    for c in propre:
        if c in '\\"$[]':
            resultat.append("\\")
        resultat.append(c)
    return "".join(resultat)


def vers_routeros(plan):
    lignes = [ENTETE_ROUTEROS]
    for a in plan["allocations"]:
        lignes.append(
            f"/ip address add address={a['premier_hote']}/{a['prefixe']} "
            f"network={a['reseau'].split('/', 1)[0]} "
            f"interface=A_DEFINIR comment=\"{echapper_routeros(a['nom'])}\"")
    return "\n".join(lignes) + "\n"


# format → (fonction, extension, type de contenu)
FORMATS = {
    "csv": (vers_csv, ".csv", "text/csv; charset=utf-8"),
    "json": (vers_json, ".json", "application/json; charset=utf-8"),
    "routeros": (vers_routeros, ".rsc", "text/plain; charset=utf-8"),
}


def nom_fichier(plan, extension):
    """Nom de fichier ASCII sûr construit à partir du parent normalisé (ex. plan-192.168.10.0-24.csv)."""
    base = "".join(c if (c.isascii() and (c.isdigit() or c == ".")) else "-" for c in plan["parent"])
    return f"plan-{base}{extension}"
