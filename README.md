# subnet-calc

Outils de calcul de sous-réseaux IPv4, en Python (bibliothèque standard uniquement).

- **`subnet_calc.py`** : outil en ligne de commande qui découpe un réseau CIDR en N sous-réseaux
  égaux (`-n`) ou par préfixe cible (`-m`), au format texte ou JSON. Voir [SPEC.md](SPEC.md).

  ```bash
  python3 subnet_calc.py 192.168.1.0/24 -n 4
  ```

- **NetPlan Studio** : atelier web local de plan d'adressage (section ci-dessous).

## NetPlan Studio

Atelier web local de plan d'adressage IPv4 : planificateur VLSM, calculatrice CIDR, découpage en
sous-réseaux, vérifications, et exports. Interface en français ; tous les calculs sont faits en Python
par un petit serveur local (`http.server`), le navigateur ne fait qu'afficher les réponses. Aucune
dépendance, aucune ressource externe, aucune requête sortante.

### Lancer

```bash
python3 -m netplan --port 8080
```

puis ouvrir <http://127.0.0.1:8080>. Le serveur n'écoute par défaut que sur `127.0.0.1` (option
`--host` pour changer ; l'application n'a ni authentification ni HTTPS, ne l'exposez pas sur un réseau
non fiable). `Ctrl+C` arrête le serveur.

Les tests (depuis la racine du dépôt) : `python3 -m pytest tests -q`.

### Fonctions

- **Planificateur VLSM** : un réseau parent et une liste de besoins (`Voix 50, Data 120, Admin 10`,
  séparés par des virgules, des points-virgules ou des retours à la ligne). Les besoins sont alloués du
  plus grand au plus petit, sans chevauchement. Résultat : tableau d'allocation (réseau, masque, plage
  d'hôtes, broadcast, capacité), carte proportionnelle de l'espace d'adresses, blocs libres et taux
  d'occupation.
- **Exports** du plan VLSM, générés par le serveur et téléchargés depuis les boutons de l'interface :
  - **CSV** (`text/csv`) : colonnes `nom,hotes_demandes,reseau,prefixe,masque,premier_hote,dernier_hote,broadcast,capacite`,
    une ligne par allocation. Toute cellule commençant par `=`, `+`, `-`, `@`, une tabulation ou un retour
    chariot est préfixée d'une apostrophe (protection contre l'injection de formules dans les tableurs).
  - **JSON** : le plan complet (`parent`, `allocations`, `libres`, `taux_occupation`).
  - **RouterOS** (`text/plain`) : **brouillon à vérifier**. Première ligne `# BROUILLON À VÉRIFIER …`, puis
    une commande par allocation :
    `/ip address add address=192.168.10.1/26 network=192.168.10.0 interface=A_DEFINIR comment="LAN"`.
    L'interface (`A_DEFINIR`) est à renseigner ; le nom est échappé (`"`, `\`, `$`, `[`, `]`) et débarrassé
    de ses caractères de contrôle. Relisez toujours le fichier avant de l'appliquer à un routeur.
- **Calculatrice CIDR** : adresse, réseau, broadcast, masque, plage d'hôtes, nombre d'hôtes et vue binaire,
  mis à jour à la saisie.
- **Découpage** d'un réseau en N sous-réseaux égaux ou par préfixe cible.
- **Vérifications** : appartenance d'une adresse à un réseau, chevauchement de deux réseaux.
- **Confort** : thème clair et sombre (celui du système par défaut, bouton de bascule dont le choix est
  mémorisé dans le navigateur), utilisable au clavier (lien d'évitement, focus visible, champs étiquetés)
  et sur un écran de 360 px, plan partageable par lien, dernier plan retrouvé à la réouverture.

### Lien partageable

Après chaque calcul VLSM réussi, l'adresse de la page contient le plan dans son **fragment** (la partie
après `#`, jamais envoyée au serveur) :

```
http://127.0.0.1:8080/#reseau=<CIDR parent>&besoins=<texte des besoins>
```

- `reseau` : le réseau parent, tel que saisi ;
- `besoins` : le texte du champ « Besoins », tel que saisi (retours à la ligne compris) ;
- les deux valeurs sont encodées comme dans une chaîne de requête (`application/x-www-form-urlencoded` :
  `/` → `%2F`, `,` → `%2C`, espace → `+`).

Exemple, pour `192.168.10.0/24` avec `LAN 50, Serveurs 20, Admin 10` :

```
http://127.0.0.1:8080/#reseau=192.168.10.0%2F24&besoins=LAN+50%2C+Serveurs+20%2C+Admin+10
```

Ouvrir le lien (ou modifier le fragment dans la barre d'adresse) remplit les champs et recalcule le plan
via l'API. Les valeurs lues dans l'URL sont traitées comme des saisies : placées dans les champs, envoyées
à l'API, affichées en texte brut (jamais interprétées comme du HTML). Une valeur invalide donne l'erreur
de l'API, en français. Un clic sur un lien de navigation interne (`#section-…`) ne fait pas perdre le plan
dans l'adresse.

Sans fragment, la page restaure le **dernier plan** calculé, gardé dans le `localStorage` du navigateur
(clé `netplan.dernierPlan`) ; le thème choisi est gardé sous la clé `netplan.theme`. Ces données restent
dans votre navigateur.

### API

`POST` JSON, réponses JSON (`Content-Type: application/json; charset=utf-8`) ; en cas d'entrée invalide :
`400 {"erreur": "<message en français>"}`.

| Route | Corps | Réponse |
|---|---|---|
| `/api/cidr` | `{"cidr": "192.168.1.10/24"}` | réseau, broadcast, masque, plage, binaire… |
| `/api/vlsm` | `{"parent": "192.168.10.0/24", "besoins": [{"nom": "LAN", "hotes": 50}]}` | `parent`, `allocations`, `libres`, `taux_occupation` |
| `/api/decoupage` | `{"reseau": "10.0.0.0/16", "n": 8}` ou `{"reseau": …, "prefixe": 26}` | sous-réseaux (256 au plus) |
| `/api/appartenance` | `{"ip": …, "reseau": …}` | `appartient` |
| `/api/chevauchement` | `{"a": …, "b": …}` | `chevauchement` |
| `/api/export/csv`, `/api/export/json`, `/api/export/routeros` | même corps que `/api/vlsm` | fichier en pièce jointe (`Content-Disposition: attachment`) |

Exemple :

```bash
curl -s -X POST http://127.0.0.1:8080/api/export/routeros \
  -H 'Content-Type: application/json' \
  -d '{"parent": "192.168.10.0/24", "besoins": [{"nom": "LAN", "hotes": 50}]}'
```

Toutes les réponses portent une politique de sécurité de contenu stricte (`script-src 'self'`,
`style-src 'self'`, aucun script ni style en ligne), `X-Content-Type-Options: nosniff` et
`Referrer-Policy: no-referrer`. Corps de requête limité à 64 Kio.

### Limites connues

- **IPv4 uniquement** : pas d'IPv6.
- **Découpage** : au plus **256 sous-réseaux renvoyés** ; le total réel est indiqué et l'interface signale
  que la liste est tronquée.
- **VLSM** : au plus 256 besoins ; un bloc est au plus un `/30` (2 hôtes) ; les blocs sont posés les uns
  après les autres depuis le début du réseau parent (pas d'alignement optimisé ni de réservation de
  plages précises) ; plan limité à un seul réseau parent.
- **RouterOS** : brouillon à vérifier ; seules des commandes `/ip address add` sont produites (ni routes,
  ni VLAN, ni DHCP, ni pare-feu), avec `interface=A_DEFINIR` à remplacer. Le caractère `?` n'est pas échappé.
- **Lien partageable** : il contient les saisies en clair ; il ne s'agit pas d'un stockage côté serveur
  (le serveur ne garde rien). Un très long texte de besoins donne un très long lien.
- **Stockage navigateur** : si `localStorage` est indisponible (navigation privée, stockage bloqué), le
  dernier plan et le thème ne sont simplement pas mémorisés.
- Serveur local de démonstration (`http.server`) : ni authentification, ni HTTPS, pas prévu pour être exposé.
