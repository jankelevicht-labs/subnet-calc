#!/usr/bin/env python3
"""subnet-calc — découpage d'un réseau IPv4 en sous-réseaux (SPEC.md §1).

Outil en ligne de commande qui découpe un réseau IPv4 en notation CIDR
soit en un nombre N de sous-réseaux de taille égale (N puissance de 2,
option ``-n``), soit en sous-réseaux d'un masque cible donné (option
``-m``), soit en sous-réseaux de tailles adaptées à des besoins en hôtes
donnés (option ``--vlsm``, allocation du plus grand au plus petit), et
affiche pour chaque sous-réseau son adresse CIDR, son masque décimal, sa
plage d'hôtes utilisable et son adresse de broadcast, au format texte
(défaut) ou JSON (``-f json``).

Usage (SPEC.md §2.2) ::

    python3 subnet_calc.py NETWORK [-n COUNT | -m MASK | --vlsm BESOINS]
        [-f {text,json}]

Le nom commercial de la commande est ``subnet-calc`` : c'est lui
qu'affichent l'usage et l'aide (SPEC.md §2.1), quelle que soit la façon
d'invoquer le script.

Codes de sortie (SPEC.md §3.2) : 0 succès, 1 entrée invalide, 2
découpage impossible. Toute erreur est signalée sur stderr par une ligne
unique « Erreur : <raison> » ; stdout reste vide en cas d'erreur.

Implémentation autonome : bibliothèque standard uniquement, Python >= 3.8
(SPEC.md §5.1–§5.2), le module :mod:`ipaddress` réalise l'analyse CIDR.
"""

import argparse
import ipaddress
import json
import re
import sys

# Nom commercial de la commande (SPEC.md §2.1).
PROG = "subnet-calc"

# Codes de sortie (SPEC.md §3.2).
CODE_OK = 0
CODE_ENTREE_INVALIDE = 1
CODE_DECOUPAGE_IMPOSSIBLE = 2

# Formats de sortie acceptés (SPEC.md §2.3).
FORMATS = ("text", "json")


class ErreurEntree(Exception):
    """Entrée invalide → code de sortie 1 (SPEC.md §3.2)."""


class DecoupageImpossible(Exception):
    """Découpage infaisable → code de sortie 2 (SPEC.md §3.2, §5.4)."""


# ---------------------------------------------------------------------------
# Validation des entrées (SPEC.md §3)
# ---------------------------------------------------------------------------


def parse_reseau(texte):
    """Valide ``NETWORK`` et retourne un :class:`ipaddress.IPv4Network`.

    La notation doit être un CIDR IPv4 strict : ``A.B.C.D/P`` avec
    0 <= P <= 32, préfixe obligatoire, bits d'hôte à zéro ; les espaces
    de début/fin sont tolérés (SPEC.md §3.1).

    Args:
        texte: valeur brute de l'argument positionnel ``NETWORK``.

    Returns:
        L'objet :class:`ipaddress.IPv4Network` correspondant.

    Raises:
        ErreurEntree: réseau mal formé, préfixe absent ou bits d'hôte
            non nuls (code de sortie 1, SPEC.md §3.2).
    """
    valeur = texte.strip()
    if "/" not in valeur:
        # ipaddress accepterait ``192.168.1.0`` comme /32 : le préfixe est
        # pourtant obligatoire (SPEC.md §3.1), d'où ce contrôle explicite.
        raise ErreurEntree(
            "notation CIDR IPv4 invalide : « %s » (préfixe /P obligatoire)"
            % valeur
        )
    try:
        # strict=True (défaut) : refuse les bits d'hôte non nuls.
        return ipaddress.IPv4Network(valeur)
    except ValueError as exc:
        if "has host bits set" in str(exc):
            raise ErreurEntree("bits d'hôte non nuls dans %s" % valeur)
        raise ErreurEntree("notation CIDR IPv4 invalide : « %s »" % valeur)


def _entier_ou_erreur(texte, option):
    """Convertit ``texte`` en ``int`` ; lève :class:`ErreurEntree` sinon.

    Args:
        texte: valeur brute de l'option (``-n`` ou ``-m``).
        option: libellé de l'option pour le message d'erreur.

    Returns:
        L'entier correspondant.
    """
    try:
        return int(texte)
    except (TypeError, ValueError):
        raise ErreurEntree(
            "l'option %s attend un entier, « %s » fourni" % (option, texte)
        )


def _besoins_ou_erreur(texte):
    """Analyse la liste ``BESOINS`` de ``--vlsm`` en entiers positifs.

    Chaque élément séparé par des virgules est trimé puis converti en
    ``int`` ; tout élément vide, non entier ou <= 0 est invalide.

    Args:
        texte: valeur brute de ``--vlsm`` (chaîne).

    Returns:
        La liste des besoins (``int`` strictement positifs), dans l'ordre
        de saisie.

    Raises:
        ErreurEntree: élément vide, non entier ou <= 0 (code de sortie 1,
            SPEC.md §3.2).
    """
    besoins = []
    for element in texte.split(","):
        try:
            nombre = int(element.strip())
        except ValueError:
            raise ErreurEntree(
                "l'option --vlsm attend une liste d'entiers strictement "
                "positifs séparés par des virgules, « %s » fourni" % texte
            )
        if nombre <= 0:
            raise ErreurEntree(
                "l'option --vlsm attend une liste d'entiers strictement "
                "positifs séparés par des virgules, « %s » fourni" % texte
            )
        besoins.append(nombre)
    return besoins


def valider_options(count, mask, vlsm, format_sortie):
    """Valide la cohérence des options et normalise le mode de découpage.

    Ordre des contrôles (SPEC.md §3.2) : exclusivité des modes
    ``-n``/``-m``/``--vlsm``, présence d'un mode, choix du format, puis
    type et domaine de la valeur du mode choisi. Les erreurs de
    conversion/choix sont volontairement détectées ici et non par
    argparse, afin que la validation de ``NETWORK`` (§3.2) soit toujours
    signalée en premier.

    Args:
        count: valeur brute de ``-n/--count`` (chaîne) ou ``None``.
        mask: valeur brute de ``-m/--mask`` (chaîne) ou ``None``.
        vlsm: valeur brute de ``--vlsm`` (chaîne) ou ``None``.
        format_sortie: valeur de ``-f/--format``.

    Returns:
        Un tuple ``(genre, valeur)`` : ``("count", N)`` ou
        ``("mask", P)`` avec ``valeur`` un ``int``, ou ``("vlsm", B)``
        avec ``B`` la liste des besoins (``int`` strictement positifs).

    Raises:
        ErreurEntree: options inconnues côté valeurs, ``-n``/``-m``/
            ``--vlsm`` fournis deux à deux, aucun mode fourni, ``COUNT``
            non entier / non puissance de 2 / <= 0, ``MASK`` non entier
            ou hors [1, 32], ``BESOINS`` mal formé, format de sortie
            invalide (code de sortie 1).
    """
    if count is not None and mask is not None:
        raise ErreurEntree(
            "les options -n/--count et -m/--mask sont mutuellement exclusives"
        )
    if count is not None and vlsm is not None:
        raise ErreurEntree(
            "les options -n/--count et --vlsm sont mutuellement exclusives"
        )
    if mask is not None and vlsm is not None:
        raise ErreurEntree(
            "les options -m/--mask et --vlsm sont mutuellement exclusives"
        )
    if count is None and mask is None and vlsm is None:
        raise ErreurEntree(
            "aucun mode de découpage fourni : utiliser -n/--count, "
            "-m/--mask ou --vlsm"
        )
    if format_sortie not in FORMATS:
        raise ErreurEntree(
            "format de sortie invalide : « %s » (choix possibles : %s)"
            % (format_sortie, ", ".join(FORMATS))
        )
    if count is not None:
        nombre = _entier_ou_erreur(count, "-n/--count")
        # Puissance de 2 stricte et positive : un seul bit à 1 (SPEC §5.3).
        if nombre <= 0 or nombre & (nombre - 1):
            raise ErreurEntree(
                "-n/--count doit être une puissance de 2 (1, 2, 4, 8, …), "
                "« %s » fourni" % count
            )
        return ("count", nombre)
    if vlsm is not None:
        return ("vlsm", _besoins_ou_erreur(vlsm))
    prefixe = _entier_ou_erreur(mask, "-m/--mask")
    if not 1 <= prefixe <= 32:
        raise ErreurEntree(
            "-m/--mask doit être compris entre 1 et 32, « %s » fourni" % mask
        )
    return ("mask", prefixe)


def planifier_decoupage(prefixe_source, mode):
    """Vérifie la faisabilité du découpage et calcule ses paramètres.

    Args:
        prefixe_source: préfixe ``P`` du réseau source (0–32).
        mode: couple ``(genre, valeur)`` produit par
            :func:`valider_options`.

    Returns:
        Un tuple ``(nouveau_prefixe, total)`` : préfixe des sous-réseaux
        et nombre de sous-réseaux produits (SPEC.md §2.4).

    Raises:
        DecoupageImpossible: ``MASK`` <= préfixe source (mode ``-m``) ou
            nombre de sous-réseaux > 2^(32 - P) (mode ``-n``) — code de
            sortie 2, SPEC.md §3.2 et §5.4.
    """
    genre, valeur = mode
    if genre == "count":
        total = valeur
        if total > 1 << (32 - prefixe_source):
            raise DecoupageImpossible("découpage impossible")
        nouveau_prefixe = prefixe_source + (total.bit_length() - 1)
    else:
        if valeur <= prefixe_source:
            raise DecoupageImpossible("découpage impossible")
        nouveau_prefixe = valeur
        total = 1 << (nouveau_prefixe - prefixe_source)
    return nouveau_prefixe, total


def _taille_bloc(besoin):
    """Calcule la taille de bloc (en adresses) pour un besoin en hôtes.

    Plus petite puissance de 2 >= ``besoin + 2`` (les adresses réseau et
    broadcast du sous-réseau sont réservées), avec un minimum de 4 :
    jamais plus fin qu'un /30 (SPEC.md §2.4, mode --vlsm).

    Args:
        besoin: nombre d'hôtes requis (``int`` strictement positif).

    Returns:
        La taille de bloc en adresses (``int``, puissance de 2 >= 4).
    """
    requis = besoin + 2
    # Plus petite puissance de 2 >= requis : (requis - 1).bit_length() donne
    # l'exposant (ex. requis 52 -> (51).bit_length() = 6 -> 2^6 = 64).
    return max(4, 1 << (requis - 1).bit_length())


def planifier_vlsm(reseau, besoins):
    """Alloue un sous-réseau par besoin en hôtes, du plus grand au plus petit.

    Tri décroissant stable des besoins (les besoins égaux gardent l'ordre
    d'entrée) ; pour chaque besoin ``N`` : taille de bloc = plus petite
    puissance de 2 >= ``N + 2``, minimum 4 (jamais plus fin qu'un /30),
    préfixe = 32 - log2(taille). Placement séquentiel depuis le réseau
    source : chaque bloc démarre au premier multiple de sa taille >= au
    curseur (l'alignement relatif à la base source équivaut à
    l'alignement absolu car le bloc est <= à la taille du réseau source),
    le bloc suivant juste derrière le précédent, sans chevauchement. Un
    préfixe égal au préfixe source est autorisé (besoin 254 sur /24 →
    le réseau lui-même, analogue à ``-n 1``, SPEC.md §3.2 code 0).

    Args:
        reseau: :class:`ipaddress.IPv4Network` du réseau source.
        besoins: liste d'entiers strictement positifs (déjà validée par
            :func:`valider_options`), dans l'ordre de saisie.

    Returns:
        La liste des sous-réseaux alloués, en ordre d'allocation :
        tailles décroissantes, égalités dans l'ordre d'entrée.

    Raises:
        DecoupageImpossible: si un bloc ne tient pas dans le réseau
            source (préfixe nécessaire < préfixe source, ou espace
            insuffisant pour l'ensemble des besoins) — code de sortie 2,
            SPEC.md §3.2.
    """
    allocations = []
    curseur = int(reseau.network_address)
    fin_source = int(reseau.broadcast_address) + 1
    # sorted() est stable : à besoins égaux, l'ordre d'entrée est conservé.
    for besoin in sorted(besoins, reverse=True):
        taille = _taille_bloc(besoin)
        prefixe = 32 - (taille.bit_length() - 1)
        # Premier multiple de la taille de bloc >= au curseur.
        depart = (curseur + taille - 1) // taille * taille
        if depart + taille > fin_source:
            raise DecoupageImpossible("découpage impossible")
        allocations.append(ipaddress.IPv4Network((depart, prefixe)))
        curseur = depart + taille
    return allocations


# ---------------------------------------------------------------------------
# Mise en forme des résultats (SPEC.md §4)
# ---------------------------------------------------------------------------


def plage_hotes(reseau):
    """Retourne la plage d'hôtes utilisable du sous-réseau.

    De l'adresse réseau + 1 à l'adresse broadcast - 1 ; pour un /31 la
    plage couvre les deux adresses ; pour un /32 elle est vide
    (SPEC.md §4.1).

    Args:
        reseau: :class:`ipaddress.IPv4Network` du sous-réseau.

    Returns:
        Un couple ``(première, dernière)`` de chaînes, ou ``None`` si la
        plage est vide (/32).
    """
    if reseau.prefixlen == 32:
        return None
    if reseau.prefixlen == 31:
        return (str(reseau.network_address), str(reseau.broadcast_address))
    return (
        str(reseau.network_address + 1),
        str(reseau.broadcast_address - 1),
    )


def ligne_texte(reseau):
    """Formate un sous-réseau sur une ligne texte (SPEC.md §4.1).

    Args:
        reseau: :class:`ipaddress.IPv4Network` du sous-réseau.

    Returns:
        ``<CIDR> | <masque décimal> | <première>-<dernière> | <broadcast>``
        (la plage vaut ``-`` pour un /32).
    """
    plage = plage_hotes(reseau)
    texte_plage = "%s-%s" % plage if plage else "-"
    return "%s | %s | %s | %s" % (
        str(reseau),
        str(reseau.netmask),
        texte_plage,
        str(reseau.broadcast_address),
    )


def fiche_json(reseau):
    """Construit l'objet JSON décrivant un sous-réseau (SPEC.md §4.2).

    Args:
        reseau: :class:`ipaddress.IPv4Network` du sous-réseau.

    Returns:
        Un dict aux clés ordonnées ``cidr``, ``masque``, ``plage_hotes``
        (couple de chaînes, ou tableau vide pour un /32) et ``broadcast``.
    """
    plage = plage_hotes(reseau)
    return {
        "cidr": str(reseau),
        "masque": str(reseau.netmask),
        "plage_hotes": list(plage) if plage else [],
        "broadcast": str(reseau.broadcast_address),
    }


def ecrire_texte(sous_reseaux, total, source, flux):
    """Écrit les résultats au format texte (SPEC.md §4.1).

    En-tête puis une ligne par sous-réseau, ordre croissant ; l'écriture
    est en flux (aucune matérialisation de la liste, utile pour les très
    grands découpages).

    Args:
        sous_reseaux: itérateur des sous-réseaux (ordre croissant).
        total: nombre de sous-réseaux (l'en-tête l'annonce).
        source: réseau source (affiché dans l'en-tête).
        flux: flux de sortie (stdout).
    """
    flux.write("%d sous-réseaux de %s :\n" % (total, str(source)))
    for sous in sous_reseaux:
        flux.write(ligne_texte(sous) + "\n")


def ecrire_json(sous_reseaux, flux):
    """Écrit le tableau JSON des résultats (SPEC.md §4.2).

    Construction incrémentale (aucune matérialisation de la liste) au
    format exact de l'exemple §4.2 : structure indentée de 2 espaces,
    clés indentées de 4, et ``plage_hotes`` en tableau « inline » sur une
    seule ligne (``["a", "b"]``), ce que ne produit pas
    ``json.dumps(..., indent=2)`` qui éclaterait le tableau.

    Args:
        sous_reseaux: itérateur des sous-réseaux (ordre croissant).
        flux: flux de sortie (stdout).
    """
    flux.write("[\n")
    premier = True
    for sous in sous_reseaux:
        if premier:
            premier = False
        else:
            flux.write(",\n")
        fiche = fiche_json(sous)
        flux.write("\n".join((
            "  {",
            '    "cidr": %s,' % json.dumps(fiche["cidr"], ensure_ascii=False),
            '    "masque": %s,' % json.dumps(fiche["masque"], ensure_ascii=False),
            '    "plage_hotes": %s,'
            % json.dumps(fiche["plage_hotes"], ensure_ascii=False),
            '    "broadcast": %s'
            % json.dumps(fiche["broadcast"], ensure_ascii=False),
            "  }",
        )))
    if premier:  # inatteignable : total >= 1 ; tableau vide par prudence
        flux.write("[]\n")
        return
    flux.write("\n]\n")


# ---------------------------------------------------------------------------
# Interface en ligne de commande (SPEC.md §2)
# ---------------------------------------------------------------------------


class _ParserSpec(argparse.ArgumentParser):
    """``ArgumentParser`` dont les erreurs respectent la SPEC.md §3.2.

    Toute erreur d'usage (option inconnue, argument positionnel
    manquant, valeur attendue absente…) est signalée sur stderr par une
    ligne unique « Erreur : <raison> » et sort avec le code 1 —
    l'usage détaillé reste réservé à ``--help``, qui sort avec 0 (§2.5).
    """

    def error(self, message):
        raise SystemExit(_signaler_erreur_usage(message))


# Traduction des messages d'erreur argparse les plus courants ; toute
# variante non reconnue passe telle quelle (préfixe et code conformes).
_MOTIF_ARGS_REQUIS = re.compile(r"^the following arguments are required: (.+)$")
_MOTIF_ARGS_INCONNUS = re.compile(r"^unrecognized arguments: (.+)$")
_MOTIF_UN_ARG = re.compile(r"^argument (.+?): expected one argument$")


def traduire_erreur_usage(message):
    """Traduit en français un message d'erreur argparse courant.

    Args:
        message: message technique produit par argparse (en anglais).

    Returns:
        La raison à afficher après le préfixe « Erreur : ».
    """
    correspondance = _MOTIF_ARGS_REQUIS.match(message)
    if correspondance:
        return "argument(s) requis manquant(s) : %s" % correspondance.group(1)
    correspondance = _MOTIF_ARGS_INCONNUS.match(message)
    if correspondance:
        return "argument(s) inconnu(s) : %s" % correspondance.group(1).strip()
    correspondance = _MOTIF_UN_ARG.match(message)
    if correspondance:
        return "valeur attendue pour l'option %s" % correspondance.group(1)
    return message


def _signaler_erreur_usage(message):
    """Affiche l'erreur d'usage et retourne le code de sortie 1 (§3.2)."""
    print("Erreur : %s" % traduire_erreur_usage(message), file=sys.stderr)
    return CODE_ENTREE_INVALIDE


def build_parser():
    """Construit l'analyseur d'arguments (SPEC.md §2).

    Returns:
        Un :class:`_ParserSpec` prêt à recevoir
        ``NETWORK [-n COUNT | -m MASK] [-f {text,json}]``.

    Note:
        ``-n``, ``-m`` et ``--vlsm`` sont volontairement lus comme des
        chaînes (pas ``type=int``) et ``-f`` sans ``choices`` : la SPEC §3.2 impose
        l'ordre « validation de NETWORK → cohérence des options », or
        argparse convertirait pendant l'analyse, avant tout contrôle du
        réseau. La conversion est donc déléguée à
        :func:`valider_options`.
    """
    parser = _ParserSpec(
        prog=PROG,
        usage="%(prog)s [-h] [-n COUNT | -m MASK | --vlsm BESOINS] "
              "[-f {text,json}] NETWORK",
        description=(
            "Découpe un réseau IPv4 (notation CIDR stricte) : soit un "
            "nombre N de sous-réseaux de taille égale (N puissance de 2, "
            "-n), soit un masque cible donné (-m), soit une allocation "
            "VLSM avec un sous-réseau par besoin en hôtes (--vlsm, du "
            "plus grand au plus petit), et affiche pour chacun son CIDR, "
            "son masque, sa plage d'hôtes et son broadcast."
        ),
        epilog=(
            "Exemples :\n"
            "  subnet-calc 192.168.1.0/24 -n 2\n"
            "  subnet-calc 10.0.0.0/16 --count 8\n"
            "  subnet-calc 192.168.1.0/24 -m 26\n"
            "  subnet-calc 192.168.1.0/24 --vlsm 50,20,10\n"
            "  subnet-calc 192.168.1.0/24 -n 4 --format json"
        ),
    )
    parser.add_argument(
        "network",
        metavar="NETWORK",
        help="réseau source en notation CIDR IPv4 stricte, ex. 192.168.1.0/24",
    )
    parser.add_argument(
        "-n", "--count",
        metavar="COUNT", default=None,
        help="nombre de sous-réseaux de taille égale, puissance de 2 "
             "(1, 2, 4, 8, …) — exclusif avec -m et --vlsm",
    )
    parser.add_argument(
        "-m", "--mask",
        metavar="MASK", default=None,
        help="longueur du préfixe cible des sous-réseaux, ex. 26 pour des "
             "/26 (strictement supérieure au préfixe de NETWORK, 32 au "
             "plus) — exclusif avec -n et --vlsm",
    )
    parser.add_argument(
        "--vlsm",
        metavar="BESOINS", default=None,
        help="allocation VLSM : liste d'entiers strictement positifs "
             "séparés par des virgules (ex. 50,20,10) donnant les besoins "
             "en hôtes ; un sous-réseau est alloué par besoin, du plus "
             "grand au plus petit (code 2 si le réseau source est trop "
             "petit) — exclusif avec -n et -m",
    )
    parser.add_argument(
        "-f", "--format",
        metavar="{text,json}", default="text",
        help="format de sortie des résultats : %s (défaut : text)"
             % ", ".join(FORMATS),
    )
    return parser


def configurer_sorties():
    """Force l'encodage UTF-8 de stdout et stderr (SPEC.md §4.2).

    Les libellés contiennent des accents (« sous-réseaux », « Erreur : ») ;
    sous une locale non UTF-8, l'encodage par défaut des flux pourrait
    lever UnicodeEncodeError. Le repli silencieux conserve le comportement
    par défaut si le flux n'est pas reconfigurable (flux de test, fermé…).
    """
    for flux in (sys.stdout, sys.stderr):
        reconfigure = getattr(flux, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass


def main(argv=None):
    """Point d'entrée de la CLI ; retourne le code de sortie (SPEC.md §3.2).

    Ordre de traitement des erreurs imposé par la SPEC §3.2 : validation
    de NETWORK, puis cohérence des options, puis faisabilité du
    découpage — la première erreur rencontrée est la seule signalée, et
    stdout reste vide en cas d'erreur (aucune écriture avant validation
    complète).

    Args:
        argv: arguments à analyser ; ``None`` (défaut) lit ``sys.argv[1:]``.

    Returns:
        ``0`` succès, ``1`` entrée invalide, ``2`` découpage impossible.
        Les erreurs d'usage argparse sortent par ``SystemExit(1)`` avant
        tout retour.
    """
    configurer_sorties()
    args = build_parser().parse_args(argv)
    try:
        reseau = parse_reseau(args.network)
        mode = valider_options(args.count, args.mask, args.vlsm, args.format)
        if mode[0] == "vlsm":
            sous_reseaux = planifier_vlsm(reseau, mode[1])
            total = len(sous_reseaux)
        else:
            nouveau_prefixe, total = planifier_decoupage(reseau.prefixlen, mode)
            # ``subnets(new_prefix=P)`` renvoie le réseau lui-même quand P
            # est égal au préfixe source (cas -n 1), et itère en ordre
            # croissant ; en mode --vlsm, ``sous_reseaux`` est la liste en
            # ordre d'allocation (tailles décroissantes).
            sous_reseaux = reseau.subnets(new_prefix=nouveau_prefixe)
    except ErreurEntree as exc:
        print("Erreur : %s" % exc, file=sys.stderr)
        return CODE_ENTREE_INVALIDE
    except DecoupageImpossible as exc:
        print("Erreur : %s" % exc, file=sys.stderr)
        return CODE_DECOUPAGE_IMPOSSIBLE

    if args.format == "json":
        ecrire_json(sous_reseaux, sys.stdout)
    else:
        ecrire_texte(sous_reseaux, total, reseau, sys.stdout)
    return CODE_OK


if __name__ == "__main__":
    sys.exit(main())
