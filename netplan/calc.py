# -*- coding: utf-8 -*-
"""Calculs d'adressage IPv4 de NetPlan Studio (bibliothèque standard uniquement).

Toutes les fonctions publiques renvoient des ``dict`` sérialisables en JSON et
signalent toute entrée invalide par :class:`NetplanError` (sous-classe de
``ValueError``) dont le message est rédigé en français.

Fonctions publiques
-------------------
``cidr_info(cidr)``, ``vlsm(parent, besoins)``,
``decoupage(reseau, n=None, prefixe=None)``, ``appartenance(ip, reseau)``,
``chevauchement(a, b)``.

Cas particuliers des préfixes /31 et /32 (voir :func:`cidr_info`)
-----------------------------------------------------------------
* ``/31`` (RFC 3021, liaison point à point) : 2 adresses, toutes deux
  utilisables comme hôtes. Par convention du projet, ``premier_hote`` est
  l'adresse du réseau et ``dernier_hote`` l'adresse de broadcast ; ``nb_hotes`` = 2.
* ``/32`` (hôte unique) : 1 adresse ; réseau, broadcast, ``premier_hote`` et
  ``dernier_hote`` sont identiques ; ``nb_hotes`` = 1.
* Pour tout préfixe de /0 à /30 : ``nb_hotes`` = 2^(32−p) − 2, ``premier_hote`` =
  réseau + 1 et ``dernier_hote`` = broadcast − 1.

Plafonds
--------
* ``LIMITE_SOUS_RESEAUX`` (256) : nombre maximal de sous-réseaux *renvoyés* par
  :func:`decoupage` (le total réel reste indiqué dans ``nombre_total`` et
  ``tronque`` vaut alors ``True``).
* ``LIMITE_BESOINS`` (256) : nombre maximal de besoins acceptés par :func:`vlsm`.
"""

import ipaddress
from itertools import islice

LIMITE_SOUS_RESEAUX = 256
LIMITE_BESOINS = 256


class NetplanError(ValueError):
    """Entrée invalide ; le message est destiné à l'utilisateur, en français."""


# --------------------------------------------------------------------------- #
# Utilitaires internes
# --------------------------------------------------------------------------- #

def _reseau(valeur, nom="réseau"):
    """Analyse un CIDR ``a.b.c.d/p`` (bits d'hôte tolérés) et renvoie
    ``(adresse, IPv4Network)``. Le préfixe est obligatoire et doit être un
    entier décimal de 0 à 32."""
    if not isinstance(valeur, str):
        raise NetplanError(f"Le {nom} doit être du texte au format CIDR, par exemple 192.168.1.0/24.")
    texte = valeur.strip()
    if not texte:
        raise NetplanError(f"Le {nom} est vide : saisissez un CIDR, par exemple 192.168.1.0/24.")
    if "/" not in texte:
        raise NetplanError(
            f"Le {nom} « {texte} » n'a pas de préfixe : ajoutez /0 à /32, par exemple 192.168.1.0/24.")
    adr_txt, _, pref_txt = texte.partition("/")
    try:
        adresse = ipaddress.IPv4Address(adr_txt)
    except ValueError:
        raise NetplanError(
            f"Le {nom} « {texte} » est invalide : « {adr_txt} » n'est pas une adresse IPv4 correcte.") from None
    if not (pref_txt.isascii() and pref_txt.isdigit()):
        raise NetplanError(
            f"Préfixe incohérent dans « {texte} » : « {pref_txt} » n'est pas un entier entre 0 et 32.")
    prefixe = int(pref_txt)
    if prefixe > 32:
        raise NetplanError(f"Préfixe incohérent dans « {texte} » : /{prefixe} dépasse /32.")
    return adresse, ipaddress.IPv4Network((adresse, prefixe), strict=False)


def _adresse(valeur, nom="adresse IP"):
    if not isinstance(valeur, str):
        raise NetplanError(f"L'{nom} doit être du texte, par exemple 192.168.1.10.")
    texte = valeur.strip()
    try:
        return ipaddress.IPv4Address(texte)
    except ValueError:
        raise NetplanError(f"L'{nom} « {texte} » est invalide : attendu une adresse IPv4 comme 192.168.1.10.") from None


def _entier(valeur, nom):
    """Entier strict (les booléens, flottants et textes sont refusés)."""
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        raise NetplanError(f"{nom} doit être un nombre entier.")
    return valeur


def _binaire(entier):
    bits = format(int(entier), "032b")
    return ".".join(bits[i:i + 8] for i in range(0, 32, 8))


def _hotes(reseau):
    """(premier_hote, dernier_hote, nb_hotes) selon le préfixe (cf. docstring du module)."""
    p = reseau.prefixlen
    if p == 32:
        return reseau.network_address, reseau.network_address, 1
    if p == 31:
        return reseau.network_address, reseau.broadcast_address, 2
    return (reseau.network_address + 1, reseau.broadcast_address - 1, reseau.num_addresses - 2)


# --------------------------------------------------------------------------- #
# Fonctions publiques
# --------------------------------------------------------------------------- #

def cidr_info(cidr):
    """Informations complètes sur un CIDR IPv4.

    Les bits d'hôte sont acceptés : ``192.168.1.10/24`` donne le réseau
    ``192.168.1.0``. Cas particuliers : ``/31`` → 2 hôtes (RFC 3021, premier
    hôte = adresse réseau, dernier hôte = broadcast) ; ``/32`` → 1 hôte
    (premier = dernier = réseau = broadcast).

    Renvoie : adresse, reseau (CIDR), broadcast, masque, prefixe, premier_hote,
    dernier_hote, nb_hotes, binaire_adresse, binaire_masque (4 octets séparés
    par des points).
    """
    adresse, reseau = _reseau(cidr, "CIDR")
    premier, dernier, nb = _hotes(reseau)
    return {
        "adresse": str(adresse),
        "reseau": str(reseau),
        "broadcast": str(reseau.broadcast_address),
        "masque": str(reseau.netmask),
        "prefixe": reseau.prefixlen,
        "premier_hote": str(premier),
        "dernier_hote": str(dernier),
        "nb_hotes": nb,
        "binaire_adresse": _binaire(adresse),
        "binaire_masque": _binaire(reseau.netmask),
    }


def _prefixe_pour_hotes(hotes):
    """Plus petit préfixe p tel que 2^(32−p) − 2 ≥ hotes (donc au plus /30), ou None."""
    bits = (hotes + 1).bit_length()  # plus petit b tel que 2^b >= hotes + 2
    return 32 - bits if bits <= 32 else None


def _valider_besoins(besoins):
    if not isinstance(besoins, (list, tuple)):
        raise NetplanError("Liste de besoins invalide : elle doit contenir des éléments {\"nom\": ..., \"hotes\": ...}.")
    if not besoins:
        raise NetplanError("Aucun besoin saisi : ajoutez au moins un besoin (nom et nombre d'hôtes).")
    if len(besoins) > LIMITE_BESOINS:
        raise NetplanError(
            f"Trop de besoins ({len(besoins)}) : le maximum est de {LIMITE_BESOINS}.")
    resultat = []
    for i, b in enumerate(besoins, start=1):
        if not isinstance(b, dict):
            raise NetplanError(f"Le besoin n° {i} est invalide : attendu {{\"nom\": ..., \"hotes\": ...}}.")
        nom = b.get("nom")
        if not isinstance(nom, str) or not nom.strip():
            raise NetplanError(f"Le besoin n° {i} n'a pas de nom : le nom ne peut pas être vide.")
        hotes = b.get("hotes")
        if isinstance(hotes, bool) or not isinstance(hotes, int):
            raise NetplanError(f"Le besoin « {nom.strip()} » : le nombre d'hôtes doit être un entier.")
        if hotes <= 0:
            raise NetplanError(
                f"Le besoin « {nom.strip()} » : le nombre d'hôtes doit être strictement positif (reçu {hotes}).")
        resultat.append((nom.strip(), hotes))
    return resultat


def vlsm(parent, besoins):
    """Allocation VLSM dans un réseau parent.

    ``besoins`` : liste de ``{"nom": str, "hotes": int}`` (1 à 256 éléments,
    nom non vide, hôtes ≥ 1). Les besoins sont alloués du plus grand au plus
    petit nombre d'hôtes (à égalité : ordre de saisie), chacun dans le plus
    petit bloc suffisant : plus petit préfixe p tel que 2^(32−p) − 2 ≥ hôtes
    (donc au plus /30). Les blocs sont posés les uns après les autres depuis
    le début du parent, sans chevauchement.

    Renvoie : parent (CIDR normalisé), allocations (nom, hotes_demandes,
    reseau, prefixe, masque, premier_hote, dernier_hote, broadcast, capacite),
    libres (CIDR libres agrégés, triés), taux_occupation (adresses allouées /
    adresses du parent × 100, arrondi à 1 décimale).

    Lève NetplanError si l'entrée est invalide ou si les besoins ne tiennent
    pas dans le parent.
    """
    _, reseau_parent = _reseau(parent, "réseau parent")
    liste = _valider_besoins(besoins)
    ordonnes = sorted(liste, key=lambda nh: -nh[1])  # tri stable : égalité = ordre de saisie

    blocs = []
    total = 0
    for nom, hotes in ordonnes:
        p = _prefixe_pour_hotes(hotes)
        if p is None or p < reseau_parent.prefixlen:
            raise NetplanError(
                f"Besoins impossibles : « {nom} » ({hotes} hôtes) ne tient pas dans {reseau_parent}.")
        blocs.append((nom, hotes, p))
        total += 1 << (32 - p)
    if total > reseau_parent.num_addresses:
        raise NetplanError(
            f"Besoins impossibles : il faut {total} adresses (blocs compris) mais {reseau_parent} "
            f"n'en contient que {reseau_parent.num_addresses}.")

    allocations = []
    courant = int(reseau_parent.network_address)
    for nom, hotes, p in blocs:
        net = ipaddress.IPv4Network((courant, p))
        premier, dernier, nb = _hotes(net)
        allocations.append({
            "nom": nom,
            "hotes_demandes": hotes,
            "reseau": str(net),
            "prefixe": p,
            "masque": str(net.netmask),
            "premier_hote": str(premier),
            "dernier_hote": str(dernier),
            "broadcast": str(net.broadcast_address),
            "capacite": nb,
        })
        courant += net.num_addresses

    fin = int(reseau_parent.broadcast_address)
    libres = []
    if courant <= fin:
        libres = [str(n) for n in ipaddress.summarize_address_range(
            ipaddress.IPv4Address(courant), ipaddress.IPv4Address(fin))]
    return {
        "parent": str(reseau_parent),
        "allocations": allocations,
        "libres": libres,
        "taux_occupation": round(total / reseau_parent.num_addresses * 100, 1),
    }


def decoupage(reseau, n=None, prefixe=None):
    """Découpe un réseau en sous-réseaux égaux, soit en ``n`` parts, soit par
    préfixe cible (exactement un des deux paramètres).

    ``n`` est arrondi à la puissance de 2 supérieure (5 → 8). Au plus
    ``LIMITE_SOUS_RESEAUX`` (256) sous-réseaux sont renvoyés ; ``nombre_total``
    donne le total réel et ``tronque`` vaut ``True`` si la liste est coupée.

    Renvoie : reseau (CIDR normalisé), prefixe_cible, nombre_total,
    sous_reseaux, tronque. Lève NetplanError si n ≤ 0, si n est trop grand
    (préfixe cible > 32) ou si le préfixe cible est < préfixe du réseau ou > 32.
    """
    _, net = _reseau(reseau)
    if (n is None) == (prefixe is None):
        raise NetplanError("Indiquez exactement un des deux paramètres : le nombre de sous-réseaux (n) "
                           "ou le préfixe cible.")
    if n is not None:
        n = _entier(n, "Le nombre de sous-réseaux")
        if n <= 0:
            raise NetplanError(f"Nombre de sous-réseaux impossible : n doit être supérieur à 0 (reçu {n}).")
        cible = net.prefixlen + (n - 1).bit_length()
        if cible > 32:
            raise NetplanError(
                f"Nombre de sous-réseaux impossible : {net} ne peut pas être découpé en {n} "
                f"(au plus {net.num_addresses} sous-réseaux, de /32).")
    else:
        cible = _entier(prefixe, "Le préfixe cible")
        if cible > 32 or cible < 0:
            raise NetplanError(f"Préfixe cible incohérent : /{cible} n'est pas compris entre /0 et /32.")
        if cible < net.prefixlen:
            raise NetplanError(
                f"Préfixe cible incohérent : /{cible} est plus court que le préfixe du réseau ({net}).")
    total = 1 << (cible - net.prefixlen)
    liste = [str(s) for s in islice(net.subnets(new_prefix=cible), LIMITE_SOUS_RESEAUX)]
    return {
        "reseau": str(net),
        "prefixe_cible": cible,
        "nombre_total": total,
        "sous_reseaux": liste,
        "tronque": total > LIMITE_SOUS_RESEAUX,
    }


def appartenance(ip, reseau):
    """Indique si l'adresse ``ip`` appartient au ``reseau`` (CIDR)."""
    adresse = _adresse(ip)
    _, net = _reseau(reseau)
    return {"ip": str(adresse), "reseau": str(net), "appartient": adresse in net}


def chevauchement(a, b):
    """Indique si les réseaux ``a`` et ``b`` (CIDR) se chevauchent."""
    _, na = _reseau(a, "réseau A")
    _, nb = _reseau(b, "réseau B")
    return {"a": str(na), "b": str(nb), "chevauchement": na.overlaps(nb)}
