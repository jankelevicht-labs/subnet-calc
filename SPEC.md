# SPEC.md — subnet-calc

Spécification fonctionnelle et technique de l'outil CLI `subnet-calc`.
Version : 1.1 — 2026-11-05

---

## 1. Objectif

`subnet-calc` est un outil Python en ligne de commande qui découpe un réseau IPv4 donné en notation CIDR soit en un nombre N de sous-réseaux de taille égale (N puissance de 2), soit en sous-réseaux d'un masque cible donné, et affiche pour chaque sous-réseau son adresse CIDR, son masque décimal, sa plage d'hôtes utilisable et son adresse de broadcast.

## 2. Interface en ligne de commande

### 2.1 Point d'entrée

- Fichier : `subnet_calc.py`, à la racine du dépôt.
- Invocation : `python3 subnet_calc.py [OPTIONS] NETWORK`
- Le nom commercial de la commande est `subnet-calc` ; toute la documentation (message `--help`, README) utilise ce nom.

### 2.2 Syntaxe

```
python3 subnet_calc.py NETWORK [-n COUNT | -m MASK] [-f {text,json}]
```

### 2.3 Arguments et options

| Élément | Forme | Type | Obligatoire | Description |
|---|---|---|---|---|
| `NETWORK` | positionnel | `str` | oui | Adresse du réseau source en notation CIDR IPv4, ex. `192.168.1.0/24` |
| `-n`, `--count` | option | `int` | alternative à `-m` | Nombre de sous-réseaux de taille égale souhaités. Doit être une puissance de 2 (1, 2, 4, 8, …) |
| `-m`, `--mask` | option | `int` | alternative à `-n` | Longueur du préfixe cible des sous-réseaux, ex. `26` pour des /26. Doit être strictement supérieur au préfixe de `NETWORK` et ≤ 32 |
| `--vlsm` | option | `str` (liste `B1,B2,…`) | alternative à `-n`/`-m` | Liste d'entiers positifs séparés par des virgules, ex. `50,20,10` : un sous-réseau par besoin en hôtes, alloué du plus grand au plus petit (règles en §3.3). Mutuellement exclusive avec `-n` et `-m` |
| `-f`, `--format` | option | choix parmi `text`, `json` | non (défaut `text`) | Format de sortie des résultats |

### 2.4 Règles de cohérence des arguments

1. `-n` et `-m` sont **mutuellement exclusifs** : fournir les deux est une erreur.
2. Fournir **ni** `-n` **ni** `-m` est une erreur (aucun découpage par défaut).
3. Si `-m` est fourni sans `/`, la valeur est un entier seul (ex. `-m 26`, **pas** `-m /26`).
4. Le découpage est recalculé comme suit :
   - Mode `-n COUNT` : nouveau préfixe = préfixe de `NETWORK` + log2(COUNT).
   - Mode `-m MASK` : nouveau préfixe = MASK ; nombre de sous-réseaux = 2^(MASK - préfixe de `NETWORK`).

### 2.5 Message d'aide

`--help` (ou `-h`) affiche l'usage ci-dessus et sort avec le code 0.

### 2.6 Exemples d'invocation

```bash
# Découper 192.168.1.0/24 en 2 sous-réseaux
python3 subnet_calc.py 192.168.1.0/24 -n 2

# Découper 10.0.0.0/16 en 8 sous-réseaux
python3 subnet_calc.py 10.0.0.0/16 --count 8

# Découper 192.168.1.0/24 en sous-réseaux de masque /26
python3 subnet_calc.py 192.168.1.0/24 -m 26

# Sortie JSON
python3 subnet_calc.py 192.168.1.0/24 -n 4 --format json
```

## 3. Entrées

### 3.1 Format accepté

- `NETWORK` doit être une **notation CIDR IPv4 stricte** : `A.B.C.D/P` avec 0 ≤ P ≤ 32.
- **Strict sur les bits d'hôte** : les bits au-delà du préfixe doivent être à zéro. Ex. `192.168.1.5/24` est refusé.
- Le préfixe `/P` est **obligatoire**. Ex. `192.168.1.0` seul est refusé.
- Les espaces de début/fin éventuels sur l'argument sont tolérés (trim avant validation).

### 3.2 Validation et erreurs

Toute erreur est signalée sur **stderr** par une ligne unique au format :

```
Erreur : <raison>
```

`stdout` reste vide en cas d'erreur. Deux codes de sortie distincts :

| Code | Signification | Cas |
|---|---|---|
| `0` | Succès | Découpage effectué (y compris N=1 ou masque égal : renvoie le réseau inchangé). |
| `1` | Entrée invalide | Réseau mal formé, bits d'hôte non nuls, préfixe absent, COUNT non entier, non-puissance de 2 ou ≤ 0, MASK non entier ou hors [1, 32], options inconnues, `-n` et `-m` fournis ensemble, ni `-n` ni `-m` fourni. |
| `2` | Découpage impossible | MASK ≤ préfixe du réseau source (ex. demander des /24 à partir d'un /24). |

Ordre d'évaluation des erreurs : validation du réseau d'abord, puis cohérence des options, puis faisabilité du découpage. La première erreur rencontrée est la seule signalée.

### 3.3 Mode VLSM (`--vlsm BESOINS`)

`--vlsm` active le découpage à taille variable (VLSM) : un sous-réseau est alloué pour chaque besoin en hôtes de la liste.

Validation (code de sortie 1, même contrat que §3.2) :

- `--vlsm` vide (chaîne vide ou ne contenant que des espaces) est refusé.
- Chaque token séparé par des virgules doit être un **entier** ; un token non entier est refusé.
- Chaque besoin doit être un entier **strictement positif** ; un entier ≤ 0 est refusé.
- `--vlsm` est **mutuellement exclusif** avec `-n/--count` et `-m/--mask` (dans les deux sens) ; fournir plusieurs options de découpage est une erreur.

Règles d'allocation :

1. **Préfixe d'un besoin** : pour un besoin `B`, le sous-réseau alloué a pour préfixe `P = 32 − ⌈log2(B + 2)⌉`, c'est-à-dire le plus petit bloc dont le nombre d'hôtes utilisables `2^(32−P) − 2` couvre `B`. Pour `B ≥ 1`, `P ≤ 30` toujours : aucun cas /31 ni /32 n'est à gérer.
2. **Ordre d'allocation** : les besoins sont traités en ordre **décroissant** (le plus grand d'abord).
3. **Position des blocs** : allocation séquentielle depuis la première adresse du réseau source, le curseur avançant de la taille de chaque bloc (`curseur += 2^(32−P)`). L'alignement est garanti par construction (somme de puissances de 2 depuis la base du réseau) : aucun chevauchement possible.
4. **Capacité dépassée** : si un bloc ne tient plus dans le réseau source (`curseur + taille > fin du réseau`) — ou si un besoin excède 2^30 − 2 hôtes, taille qu'aucun bloc IPv4 ne peut couvrir — le découpage est impossible : code de sortie `2`, message `Erreur : découpage impossible`, stdout vide.

## 4. Sorties

### 4.1 Format texte (défaut)

Une ligne par sous-réseau, ordre **croissant des adresses**, avec 4 champs séparés par ` | ` :

```
<CIDR> | <masque décimal> | <première_hôte>-<dernière_hôte> | <broadcast>
```

- `<CIDR>` : `A.B.C.D/P`.
- `<masque décimal>` : notation pointée, ex. `255.255.255.128`.
- `<plage d'hôtes utilisable>` : de l'adresse réseau +1 à l'adresse broadcast −1. Pour un /31, la plage couvre les deux adresses ; pour un /32, elle est vide (affichée `-`).
- `<broadcast>` : adresse de broadcast du sous-réseau.

En-tête au-dessus de la liste :

```
<nombre> sous-réseaux de <réseau source> :
```

### 4.2 Format JSON (`-f json`)

Un tableau JSON contenant un objet par sous-réseau, ordre croissant :

```json
[
  {
    "cidr": "192.168.1.0/25",
    "masque": "255.255.255.128",
    "plage_hotes": ["192.168.1.1", "192.168.1.126"],
    "broadcast": "192.168.1.127"
  }
]
```

- Champ `plage_hotes` : tableau de deux chaînes `[première, dernière]`, ou tableau vide `[]` pour un /32.
- Encodage UTF-8, indent 2, sortie sur **stdout**.

### 4.3 Ordre de sortie en mode VLSM

En mode `--vlsm`, les sous-réseaux sont listés en **ordre d'allocation** : le besoin le plus grand d'abord (ordre décroissant des besoins). Les formats texte (§4.1) et JSON (§4.2) utilisent les mêmes gabarits qu'en mode `-n`/`-m` (même en-tête « <nombre> sous-réseaux de <réseau source> : », mêmes clés JSON) ; seul l'ordre de la liste diffère. Les modes `-n`/`-m` conservent l'ordre croissant (§4.1–§4.2) et ne sont pas affectés par ce mode.

## 5. Contraintes

1. **Version Python** : ≥ 3.8 (utilisation de f-strings et `ipaddress` standard).
2. **Dépendances** : bibliothèque standard **uniquement**. Le module `ipaddress` est autorisé et recommandé ; aucun paquet tiers.
3. **Puissance de 2** : `-n` n'accepte que 2^k, k ≥ 0 (1, 2, 4, 8, … 2^k ≤ 2^(32 − P)).
4. **Découpage impossible** : si le nombre de sous-réseaux demandé dépasse 2^(32 − P), sortie code 2 avec message `Erreur : découpage impossible` ; aucune ligne de résultat n'est émise.
5. **Déterminisme** : à entrée égale, la sortie est toujours identique (ordre croissant, mêmes séparateurs).
6. **Portabilité** : le code fonctionne sur Linux et macOS sans modification.
7. Hors périmètre : IPv6, notation de masque en entrée (`/24` uniquement, pas `255.255.255.0`), agrégation de réseaux, lecture depuis fichier.

## 6. Cas de test

### TC-1 — Découpage simple en 2 sous-réseaux

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 -n 2
```

**Sortie exacte (stdout, code 0) :**

```
2 sous-réseaux de 192.168.1.0/24 :
192.168.1.0/25 | 255.255.255.128 | 192.168.1.1-192.168.1.126 | 192.168.1.127
192.168.1.128/25 | 255.255.255.128 | 192.168.1.129-192.168.1.254 | 192.168.1.255
```

### TC-2 — Découpage en 4 sous-réseaux

**Commande :**

```bash
python3 subnet_calc.py 10.0.0.0/24 -n 4
```

**Sortie exacte (stdout, code 0) :**

```
4 sous-réseaux de 10.0.0.0/24 :
10.0.0.0/26 | 255.255.255.192 | 10.0.0.1-10.0.0.62 | 10.0.0.63
10.0.0.64/26 | 255.255.255.192 | 10.0.0.65-10.0.0.126 | 10.0.0.127
10.0.0.128/26 | 255.255.255.192 | 10.0.0.129-10.0.0.190 | 10.0.0.191
10.0.0.192/26 | 255.255.255.192 | 10.0.0.193-10.0.0.254 | 10.0.0.255
```

### TC-3 — /24 en /26 (mode masque)

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 -m 26
```

**Sortie exacte (stdout, code 0) :** identique à TC-2 (mêmes 4 sous-réseaux /26, même ordre). Cette égalité vérifie la cohérence des deux modes.

### TC-4 — Cas limite : découpage en 1 sous-réseau

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 -n 1
```

**Sortie exacte (stdout, code 0) :** un seul bloc, identique au réseau d'origine :

```
1 sous-réseaux de 192.168.1.0/24 :
192.168.1.0/24 | 255.255.255.0 | 192.168.1.1-192.168.1.254 | 192.168.1.255
```

### TC-5 — Cas d'erreur : entrée invalide (bits d'hôte non nuls)

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.5/24 -n 2
```

**Sortie exacte :**

- **stdout** : vide (aucun octet).
- **stderr** : `Erreur : bits d'hôte non nuls dans 192.168.1.5/24`
- **code de sortie** : `1`

### TC-6 (bonus) — Découpage impossible

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 -m 24
```

**Sortie exacte :**

- **stdout** : vide.
- **stderr** : `Erreur : découpage impossible`
- **code de sortie** : `2`

### V1 (v1.1) — VLSM : besoins 50, 20, 10 hôtes dans un /24

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 50,20,10
```

**Sortie exacte (stdout, code 0) :** 3 sous-réseaux en ordre d'allocation (§4.3) : le besoin 50 exige un /26 (62 hôtes utilisables), le besoin 20 un /27 (30), le besoin 10 un /28 (14) :

```
3 sous-réseaux de 192.168.1.0/24 :
192.168.1.0/26 | 255.255.255.192 | 192.168.1.1-192.168.1.62 | 192.168.1.63
192.168.1.64/27 | 255.255.255.224 | 192.168.1.65-192.168.1.94 | 192.168.1.95
192.168.1.96/28 | 255.255.255.240 | 192.168.1.97-192.168.1.110 | 192.168.1.111
```

### V2 (v1.1) — VLSM : cas limite, besoin minimal (1 hôte)

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 1
```

**Sortie exacte (stdout, code 0) :** le besoin 1 exige un /30 (`2^(32−30) − 2 = 2` hôtes utilisables), plus petit bloc allouable :

```
1 sous-réseaux de 192.168.1.0/24 :
192.168.1.0/30 | 255.255.255.252 | 192.168.1.1-192.168.1.2 | 192.168.1.3
```

### V3 (v1.1) — VLSM : sortie JSON

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 50,20,10 --format json
```

**Sortie exacte (stdout, code 0) :** mêmes sous-réseaux que V1, gabarit JSON §4.2, ordre d'allocation §4.3 :

```json
[
  {
    "cidr": "192.168.1.0/26",
    "masque": "255.255.255.192",
    "plage_hotes": ["192.168.1.1", "192.168.1.62"],
    "broadcast": "192.168.1.63"
  },
  {
    "cidr": "192.168.1.64/27",
    "masque": "255.255.255.224",
    "plage_hotes": ["192.168.1.65", "192.168.1.94"],
    "broadcast": "192.168.1.95"
  },
  {
    "cidr": "192.168.1.96/28",
    "masque": "255.255.255.240",
    "plage_hotes": ["192.168.1.97", "192.168.1.110"],
    "broadcast": "192.168.1.111"
  }
]
```

### V4 (v1.1) — VLSM : capacité dépassée

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 200,100
```

**Sortie exacte :**

- **stdout** : vide.
- **stderr** : `Erreur : découpage impossible`
- **code de sortie** : `2`

Le besoin 200 exige un /24 (`2^(32−24) − 2 = 254` hôtes utilisables), dont le bloc de 256 adresses consomme la totalité du réseau source ; le bloc /25 requis pour 100 hôtes (`2^(32−25) − 2 = 126`) ne tient alors plus (§3.3, règle 4).

---

*Fin de la spécification. Tout comportement non décrit ici est considéré hors périmètre et ne doit pas être implémenté.*
