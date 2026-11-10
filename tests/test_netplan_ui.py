# -*- coding: utf-8 -*-
"""Tests de l'interface web de NetPlan Studio (netplan/static/ : index.html, app.js, style.css).

Statiques servis par un vrai serveur sur un port libre, éléments clés du HTML, et garde-fous
statiques : aucune injection HTML possible, aucune ressource externe, CSP stricte respectée
(pas de script/style en ligne, pas d'attribut style= ni on*=).
"""

import http.client
import os
import re
import shutil
import subprocess
import threading
from html.parser import HTMLParser

import pytest

from netplan.server import ROUTES_API, creer_serveur

REPERTOIRE_PROJET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPERTOIRE_PROJET, "netplan", "static")
FICHIERS = ("index.html", "app.js", "style.css")

# Seule URL « http » tolérée : l'espace de noms XML d'un éventuel SVG (identifiant, pas une ressource).
XMLNS_SVG_TOLERE = "http://www.w3.org/2000/svg"


def lire(nom):
    with open(os.path.join(STATIC, nom), encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------- #
# Analyse du HTML
# --------------------------------------------------------------------------- #

class _Analyse(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.balises = []          # (balise, {attribut: valeur})
        self.contenu_script = []
        self._dans_script = False
        self.texte = []

    def handle_starttag(self, tag, attrs):
        self.balises.append((tag, dict(attrs)))
        self._dans_script = tag in ("script", "style")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._dans_script = False

    def handle_data(self, data):
        if self._dans_script:
            self.contenu_script.append(data)
        else:
            self.texte.append(data)


@pytest.fixture(scope="module")
def html():
    analyse = _Analyse()
    analyse.feed(lire("index.html"))
    analyse.close()
    return analyse


def ids_html(html):
    return {a["id"] for _, a in html.balises if "id" in a}


# --------------------------------------------------------------------------- #
# Serveur réel
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def srv():
    serveur = creer_serveur("127.0.0.1", 0, journal=False)
    fil = threading.Thread(target=serveur.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    fil.start()
    yield serveur.server_address[:2]
    serveur.shutdown()
    serveur.server_close()
    fil.join(timeout=5)


def get(srv, chemin):
    conn = http.client.HTTPConnection(srv[0], srv[1], timeout=10)
    try:
        conn.request("GET", chemin)
        rep = conn.getresponse()
        return rep.status, {k.lower(): v for k, v in rep.getheaders()}, rep.read()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Fichiers et service HTTP
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("nom", FICHIERS)
def test_fichiers_presents_et_non_vides(nom):
    chemin = os.path.join(STATIC, nom)
    assert os.path.isfile(chemin) and os.path.getsize(chemin) > 200


def test_racine_html(srv):
    statut, entetes, corps = get(srv, "/")
    assert statut == 200
    assert entetes["content-type"].startswith("text/html")
    assert corps == open(os.path.join(STATIC, "index.html"), "rb").read()


def test_app_js_type_javascript(srv):
    statut, entetes, corps = get(srv, "/app.js")
    assert statut == 200
    assert "javascript" in entetes["content-type"]
    assert corps == open(os.path.join(STATIC, "app.js"), "rb").read()


def test_style_css_type_css(srv):
    statut, entetes, corps = get(srv, "/style.css")
    assert statut == 200
    assert entetes["content-type"].startswith("text/css")
    assert corps == open(os.path.join(STATIC, "style.css"), "rb").read()


def test_chemins_static_prefixes(srv):
    for chemin in ("/static/app.js", "/static/style.css", "/static/index.html"):
        assert get(srv, chemin)[0] == 200


def test_csp_des_statiques_de_l_interface(srv):
    for chemin in ("/", "/app.js", "/style.css"):
        csp = get(srv, chemin)[1]["content-security-policy"]
        assert "script-src 'self'" in csp and "style-src 'self'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp


# --------------------------------------------------------------------------- #
# Éléments clés de index.html
# --------------------------------------------------------------------------- #

def test_langue_francaise(html):
    racine = [a for t, a in html.balises if t == "html"][0]
    assert racine.get("lang") == "fr"


def test_formulaires_cles(html):
    ids = ids_html(html)
    for formulaire in ("form-vlsm", "form-calculatrice", "form-decoupage",
                       "form-appartenance", "form-chevauchement"):
        assert formulaire in ids
        assert [t for t, a in html.balises if a.get("id") == formulaire] == ["form"]


def test_champs_cles(html):
    ids = ids_html(html)
    for champ in ("vlsm-parent", "vlsm-besoins", "calc-cidr", "dec-reseau", "dec-mode", "dec-valeur",
                  "app-ip", "app-reseau", "chev-a", "chev-b"):
        assert champ in ids


def test_resultats_cles(html):
    ids = ids_html(html)
    for res in ("vlsm-carte", "vlsm-tableau", "vlsm-corps", "vlsm-taux", "vlsm-jauge", "vlsm-libres",
                "calc-reseau", "calc-broadcast", "calc-masque", "calc-prefixe", "calc-plage",
                "calc-nb-hotes", "calc-bin-adresse", "calc-bin-masque", "dec-liste", "dec-tronque",
                "resultat-appartenance", "resultat-chevauchement"):
        assert res in ids


def test_chaque_champ_a_un_libelle(html):
    pour = {a.get("for") for t, a in html.balises if t == "label"}
    for t, a in html.balises:
        if t in ("input", "textarea", "select"):
            assert a.get("id") in pour, a


def test_zones_alerte_par_formulaire(html):
    alertes = {a.get("id") for t, a in html.balises if a.get("role") == "alert"}
    assert alertes >= {"erreur-vlsm", "erreur-calculatrice", "erreur-decoupage",
                       "erreur-appartenance", "erreur-chevauchement"}


def test_tableau_allocation_colonnes(html):
    entetes = re.findall(r"<th[^>]*>([^<]+)</th>", lire("index.html"))
    for colonne in ("Nom", "Hôtes demandés", "Réseau", "Masque", "Plage d'hôtes", "Broadcast", "Capacité"):
        assert colonne in entetes


def test_references_locales_uniquement(html):
    """script src, link href : chemins du site (ou ancres #) ; aucune autre ressource chargée."""
    scripts = [a for t, a in html.balises if t == "script"]
    assert scripts and all(a.get("src", "").startswith("/") and not a["src"].startswith("//") for a in scripts)
    assert any(a.get("src") == "/app.js" for a in scripts)
    liens = [a for t, a in html.balises if t == "link"]
    assert any(a.get("rel") == "stylesheet" and a.get("href") == "/style.css" for a in liens)
    for t, a in html.balises:
        for attr in ("src", "href", "action", "data", "poster", "srcset"):
            if attr in a and t != "a":
                assert a[attr].startswith("/") and not a[attr].startswith("//"), (t, attr, a[attr])
            if t == "a" and attr == "href":
                assert a[attr].startswith("#"), a


def test_html_sans_script_ni_style_en_ligne(html):
    for t, a in html.balises:
        assert t != "style", "balise <style> interdite (CSP)"
        if t == "script":
            assert "src" in a, "script en ligne interdit (CSP)"
        assert "style" not in a, f"attribut style= interdit sur <{t}>"
        for nom in a:
            assert not nom.startswith("on"), f"attribut {nom}= interdit sur <{t}>"
    assert "".join(html.contenu_script).strip() == ""


def test_html_sans_gestionnaire_ou_style_brut():
    brut = lire("index.html").lower()
    assert not re.search(r"\son[a-z]+\s*=", brut)
    assert not re.search(r"\sstyle\s*=", brut)
    assert "javascript:" not in brut


# --------------------------------------------------------------------------- #
# Garde-fous statiques sur tout netplan/static/
# --------------------------------------------------------------------------- #

def fichiers_statiques():
    for racine, _, noms in os.walk(STATIC):
        for nom in noms:
            yield os.path.join(racine, nom)


def test_aucune_url_http_externe():
    for chemin in fichiers_statiques():
        with open(chemin, encoding="utf-8", errors="replace") as f:
            contenu = f.read().replace(XMLNS_SVG_TOLERE, "")
        trouvees = re.findall(r"https?://\S*|//[a-z0-9.-]+\.[a-z]{2,}/\S*", contenu, flags=re.IGNORECASE)
        assert not trouvees, (chemin, trouvees)


def test_css_sans_import_ni_url_externe():
    css = lire("style.css")
    assert "@import" not in css
    for url in re.findall(r"url\(([^)]*)\)", css):
        assert url.strip("'\" ").startswith(("/", "data:image/")), url


INTERDITS_JS = [
    r"innerHTML", r"outerHTML", r"insertAdjacentHTML", r"document\s*\.\s*write", r"\beval\s*\(",
    r"new\s+Function", r"\bFunction\s*\(", r"createContextualFragment", r"DOMParser", r"\.srcdoc",
    r"setTimeout\s*\(\s*[\"'`]", r"setInterval\s*\(\s*[\"'`]", r"document\s*\.\s*cookie",
    r"localStorage", r"sessionStorage", r"XMLHttpRequest", r"WebSocket", r"importScripts",
    r"\bimport\s*\(", r"setAttribute\s*\(\s*[\"'](style|on[a-z]+|href|src|srcdoc|action)[\"']",
    r"\.(href|src|action)\s*=[^=]",
]


@pytest.mark.parametrize("motif", INTERDITS_JS)
def test_app_js_sans_api_dangereuse(motif):
    assert not re.search(motif, lire("app.js"), flags=re.IGNORECASE if motif.islower() else 0), motif


def test_app_js_motifs_de_la_carte():
    """Les commandes de recette de la carte, telles quelles."""
    js = lire("app.js")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function", js)


def test_app_js_utilise_le_cssom_pour_les_largeurs():
    js = lire("app.js")
    assert re.search(r"\.style\.width\s*=", js)
    assert "setAttribute(\"style\"" not in js and "setAttribute('style'" not in js


def test_app_js_n_affiche_que_via_text_content():
    js = lire("app.js")
    assert "textContent" in js and "createElement" in js


def test_app_js_appels_api_post_json_vers_routes_existantes():
    js = lire("app.js")
    assert "fetch(" in js and '"POST"' in js and "application/json" in js
    routes = set(re.findall(r'appeler\("([a-z]+)"', js))
    assert routes == {r[len("/api/"):] for r in ROUTES_API}, routes


def test_app_js_cibles_dom_existent(html):
    """Chaque $("id") du JS correspond à un élément de index.html."""
    js = lire("app.js")
    utilises = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', js))
    assert utilises
    assert not (utilises - ids_html(html)), utilises - ids_html(html)


def test_app_js_ecoute_input_avec_delai():
    js = lire("app.js")
    assert re.search(r'addEventListener\("input"', js)
    assert "setTimeout(" in js and "clearTimeout(" in js


def test_app_js_ne_calcule_pas_d_adresses():
    """Aucune arithmétique d'adresses/masques côté JS : pas de décalages de bits ni d'analyse d'octets."""
    js = re.sub(r"/\*.*?\*/|//[^\n]*", "", lire("app.js"), flags=re.DOTALL)
    assert not re.search(r"<<|>>", js)
    assert "ipaddress" not in js.lower()
    assert not re.search(r"parseInt\([^)]*,\s*2\s*\)|toString\(\s*2\s*\)", js)     # pas de conversion binaire
    assert not re.search(r"split\(\s*[\"']\.[\"']\s*\)", js)      # pas de découpage a.b.c.d en octets


def test_app_js_erreur_api_affichee_depuis_le_champ_erreur():
    js = lire("app.js")
    assert ".erreur" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node absent : contrôle de syntaxe ignoré")
def test_app_js_syntaxe_valide():
    resultat = subprocess.run(["node", "--check", os.path.join(STATIC, "app.js")],
                              capture_output=True, text=True, timeout=60)
    assert resultat.returncode == 0, resultat.stderr


def test_interface_en_francais(html):
    texte = " ".join(html.texte)
    for mot in ("Planificateur VLSM", "Calculatrice CIDR", "Découpage", "Vérifications", "Réseau parent",
                "Taux d'occupation", "Vue binaire", "Planifier"):
        assert mot in texte, mot
