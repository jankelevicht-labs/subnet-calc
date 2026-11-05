# SPEC.md — subnet-calc

Spécification fonctionnelle et technique de l'outil CLI `subnet-calc`.
Version : 1.1 — 2026-11-05

---

## 1. Objectif

`subnet-calc` est un outil Python en ligne de commande qui découpe un réseau IPv4 donné en notation CIDR soit en un nombre N de sous-réseaux de taille égale (N puissance de 2), soit en sous-réseaux d'un masque cible donné, soit en une allocation VLSM : un sous-réseau par besoin en hôtes de la liste `BESOINS`, alloué du plus grand au plus petit sans chevauchement, et affiche pour chaque sous-réseau son adresse CIDR, son masque décimal, sa plage d'hôtes utilisable et son adresse de broadcast.

## 2. Interface en ligne de commande

### 2.1 Point d'entrée

- Fichier : `subnet_calc.py`, à la racine du dépôt.
- Invocation : `python3 subnet_calc.py [OPTIONS] NETWORK`
- Le nom commercial de la commande est `subnet-calc` ; toute la documentation (message `--help`, README) utilise ce nom.

### 2.2 Syntaxe

```
python3 subnet_calc.py NETWORK [-n COUNT | -m MASK | --vlsm BESOINS] [-f {text,json}]
```

### 2.3 Arguments et options

| Élément | Forme | Type | Obligatoire | Description |
|---|---|---|---|---|
| `NETWORK` | positionnel | `str` | oui | Adresse du réseau source en notation CIDR IPv4, ex. `192.168.1.0/24` |
| `-n`, `--count` | option | `int` | alternative à `-m`/`--vlsm` | Nombre de sous-réseaux de taille égale souhaités. Doit être une puissance de 2 (1, 2, 4, 8, …) |
| `-m`, `--mask` | option | `int` | alternative à `-n`/`--vlsm` | Longueur du préfixe cible des sous-réseaux, ex. `26` pour des /26. Doit être strictement supérieur au préfixe de `NETWORK` et ≤ 32 |
| `--vlsm` | option | `str` | alternative à `-n`/`-m` | `BESOINS` : liste d'entiers strictement positifs séparés par des virgules, ex. `50,20,10` — besoins en hôtes à allouer en VLSM. Espaces tolérés autour de chaque nombre (trim par élément) |
| `-f`, `--format` | option | choix parmi `text`, `json` | non (défaut `text`) | Format de sortie des résultats |

### 2.4 Règles de cohérence des arguments

1. `-n`, `-m` et `--vlsm` sont **mutuellement exclusifs** deux à deux : fournir deux modes quelconques est une erreur.
2. Fournir **aucun** mode est une erreur (aucun découpage par défaut).
3. Si `-m` est fourni sans `/`, la valeur est un entier seul (ex. `-m 26`, **pas** `-m /26`).
4. Le découpage est recalculé comme suit :
   - Mode `-n COUNT` : nouveau préfixe = préfixe de `NETWORK` + log2(COUNT).
   - Mode `-m MASK` : nouveau préfixe = MASK ; nombre de sous-réseaux = 2^(MASK - préfixe de `NETWORK`).
5. Mode `--vlsm BESOINS` :
   - `BESOINS` = liste d'entiers strictement positifs séparés par des virgules ; chaque élément est trimé avant conversion (espaces autour des nombres tolérés) ;
   - les besoins sont traités par **tri décroissant stable** : à besoins égaux, l'ordre d'entrée est conservé ;
   - pour chaque besoin `N` : taille de bloc = plus petite puissance de 2 ≥ `N + 2`, minimum 4 (jamais plus fin que /30) ; préfixe du sous-réseau = `32 − log2(taille)` ;
   - placement séquentiel depuis le réseau source : départ = premier multiple de la taille de bloc ≥ curseur (l'alignement relatif à la base source équivaut à l'alignement absolu car le bloc est ≤ à la taille du réseau source) ; le bloc suivant est placé juste derrière le précédent, sans chevauchement ;
   - un préfixe **égal** au préfixe source est autorisé (besoin 254 sur un /24 → le réseau lui-même, analogue à `-n 1`, code 0) ;
   - si un bloc ne tient pas dans le réseau source (préfixe nécessaire < préfixe source, ou espace insuffisant pour l'ensemble des besoins) → code 2 « découpage impossible ».

### 2.5 Message d'aide

`--help` (ou `-h`) affiche l'usage ci-dessus et sort avec le code 0. Il documente l'option `--vlsm` : syntaxe des virgules de `BESOINS`, exclusivité avec `-n` et `-m`, allocation du plus grand au plus petit, et code 2 en cas de capacité insuffisante du réseau source.

### 2.6 Exemples d'invocation

```bash
# Découper 192.168.1.0/24 en 2 sous-réseaux
python3 subnet_calc.py 192.168.1.0/24 -n 2

# Découper 10.0.0.0/16 en 8 sous-réseaux
python3 subnet_calc.py 10.0.0.0/16 --count 8

# Découper 192.168.1.0/24 en sous-réseaux de masque /26
python3 subnet_calc.py 192.168.1.0/24 -m 26

# Allocation VLSM : un /26, un /27 et un /28 pour 50, 20 puis 10 hôtes
python3 subnet_calc.py 192.168.1.0/24 --vlsm 50,20,10

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
| `0` | Succès | Découpage effectué (y compris N=1, masque égal, ou besoin VLSM 254 sur un /24 : renvoie le réseau inchangé). |
| `1` | Entrée invalide | Réseau mal formé, bits d'hôte non nuls, préfixe absent, COUNT non entier, non-puissance de 2 ou ≤ 0, MASK non entier ou hors [1, 32], `--vlsm` mal formé (élément vide, non entier ou ≤ 0) ou combiné à `-n`/`-m`, options inconnues, `-n` et `-m` fournis ensemble, aucun mode fourni. |
| `2` | Découpage impossible | MASK ≤ préfixe du réseau source (ex. demander des /24 à partir d'un /24) ; en VLSM, besoin exigeant un préfixe < préfixe du réseau source, ou espace insuffisant pour l'ensemble des besoins. |

Ordre d'évaluation des erreurs : validation du réseau d'abord, puis cohérence des options, puis faisabilité du découpage. La première erreur rencontrée est la seule signalée.

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

**Mode `--vlsm`** : mêmes formats ; les sous-réseaux sont affichés en **ordre d'allocation** (tailles décroissantes, du plus grand besoin au plus petit), qui correspond aussi à l'ordre croissant des adresses.

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
- **Mode `--vlsm`** : schéma JSON identique (aucune clé nouvelle) ; ordre d'allocation comme en §4.1.

## 5. Contraintes

1. **Version Python** : ≥ 3.8 (utilisation de f-strings et `ipaddress` standard).
2. **Dépendances** : bibliothèque standard **uniquement**. Le module `ipaddress` est autorisé et recommandé ; aucun paquet tiers.
3. **Puissance de 2** : `-n` n'accepte que 2^k, k ≥ 0 (1, 2, 4, 8, … 2^k ≤ 2^(32 − P)).
4. **Découpage impossible** : si le nombre de sous-réseaux demandé dépasse 2^(32 − P), ou si MASK ≤ préfixe source, ou — en VLSM — si un bloc dépasse la capacité du réseau source, sortie code 2 avec message `Erreur : découpage impossible` ; aucune ligne de résultat n'est émise.
5. **Déterminisme** : à entrée égale, la sortie est toujours identique (ordre croissant / ordre d'allocation, mêmes séparateurs).
6. **Portabilité** : le code fonctionne sur Linux et macOS sans modification.
7. Hors périmètre : IPv6, notation de masque en entrée (`/24` uniquement, pas `255.255.255.0`), agrégation de réseaux, lecture depuis fichier.

## 6. Cas de test

### Valeurs de référence VLSM (TV)

| Valeur | BESOINS | Résultat attendu |
|---|---|---|
| TV-1 | `50,20,10` | 3 sous-réseaux /26, /27, /28 (code 0) |
| TV-2 | `10,50,20` | sortie identique à TV-1 (tri décroissant stable) |
| TV-4 | `300` | code 2, « Erreur : découpage impossible » |
| TV-8 | `62,30,14,2` | 4 sous-réseaux /26, /27, /28, /30 (code 0) |

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

### TC-7 — VLSM : allocation du plus grand au plus petit (TV-1)

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 50,20,10
```

**Sortie exacte (stdout, code 0, stderr vide) :**

```
3 sous-réseaux de 192.168.1.0/24 :
192.168.1.0/26 | 255.255.255.192 | 192.168.1.1-192.168.1.62 | 192.168.1.63
192.168.1.64/27 | 255.255.255.224 | 192.168.1.65-192.168.1.94 | 192.168.1.95
192.168.1.96/28 | 255.255.255.240 | 192.168.1.97-192.168.1.110 | 192.168.1.111
```

### TC-8 — VLSM : l'ordre d'entrée n'a pas d'importance (TV-2)

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 10,50,20
```

**Sortie exacte (stdout, code 0) :** identique à TC-7. Cette égalité vérifie le tri décroissant stable des besoins.

### TC-9 — VLSM : capacité insuffisante (TV-4)

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 300
```

**Sortie exacte :**

- **stdout** : vide.
- **stderr** : `Erreur : découpage impossible`
- **code de sortie** : `2`

### TC-10 — VLSM : jusqu'au /30 (TV-8)

**Commande :**

```bash
python3 subnet_calc.py 192.168.1.0/24 --vlsm 62,30,14,2
```

**Sortie exacte (stdout, code 0, stderr vide) :**

```
4 sous-réseaux de 192.168.1.0/24 :
192.168.1.0/26 | 255.255.255.192 | 192.168.1.1-192.168.1.62 | 192.168.1.63
192.168.1.64/27 | 255.255.255.224 | 192.168.1.65-192.168.1.94 | 192.168.1.95
192.168.1.96/28 | 255.255.255.240 | 192.168.1.97-192.168.1.110 | 192.168.1.111
192.168.1.112/30 | 255.255.255.252 | 192.168.1.113-192.168.1.114 | 192.168.1.115
```

Cas limite (règle §2.4) : `python3 subnet_calc.py 192.168.1.0/24 --vlsm 254` → code 0, `1 sous-réseaux de 192.168.1.0/24 :` puis la ligne du réseau lui-même (comme TC-4).

---

*Fin de la spécification. Tout comportement non décrit ici est considéré hors périmètre et ne doit pas être implémenté.*
