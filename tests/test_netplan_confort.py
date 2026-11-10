# -*- coding: utf-8 -*-
"""Tests D4 de NetPlan Studio : lien partageable, dernier plan, thème, exports côté interface, accessibilité.

* Contrôles statiques de index.html, app.js, theme.js et style.css (CSP stricte, pas d'injection HTML,
  contrastes des deux thèmes, focus visible, adaptation à 360 px, ordre de tabulation).
* Scénarios de comportement : app.js et theme.js exécutés par Node (tests/harnais_netplan.js, faux DOM
  minimal) contre un vrai serveur ; ignorés si ``node`` est absent.
"""

import json
import os
import re
import shutil
import subprocess
import threading
from html.parser import HTMLParser

import pytest

from netplan.server import creer_serveur

REPERTOIRE_TESTS = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(REPERTOIRE_TESTS), "netplan", "static")
HARNAIS = os.path.join(REPERTOIRE_TESTS, "harnais_netplan.js")


def lire(nom):
    with open(os.path.join(STATIC, nom), encoding="utf-8") as f:
        return f.read()


class _Analyse(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.balises = []

    def handle_starttag(self, tag, attrs):
        self.balises.append((tag, dict(attrs)))


@pytest.fixture(scope="module")
def html():
    analyse = _Analyse()
    analyse.feed(lire("index.html"))
    analyse.close()
    return analyse


# --------------------------------------------------------------------------- #
# Contrastes (WCAG) et thèmes
# --------------------------------------------------------------------------- #

def _luminance(couleur):
    couleur = couleur.lstrip("#")
    r, g, b = (int(couleur[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contraste(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _variables(bloc):
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", bloc))


def _blocs_css():
    css = lire("style.css")
    clair = re.search(r"^:root\s*\{(.*?)^\}", css, re.S | re.M).group(1)
    systeme = re.search(
        r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme=\"light\"\]\)\s*\{(.*?)\}\s*\}",
        css, re.S).group(1)
    sombre = re.search(r":root\[data-theme=\"dark\"\]\s*\{(.*?)\}", css, re.S).group(1)
    return _variables(clair), _variables(systeme), _variables(sombre)


def test_theme_sombre_identique_pour_systeme_et_bascule():
    clair, systeme, sombre = _blocs_css()
    assert systeme and systeme == sombre
    cles_clair = {k for k in clair if k not in ("--c0", "--c1", "--c2", "--c3", "--c4", "--c5")}
    assert set(sombre) == cles_clair          # tout ce qui change de thème est redéfini en sombre


PAIRES_TEXTE = [          # (texte, fond) : rapport minimal WCAG AA du texte normal = 4,5
    ("--texte", "--carte"), ("--texte", "--fond"), ("--texte-doux", "--carte"), ("--texte-doux", "--fond"),
    ("--texte-doux", "--libre-fond"), ("--accent", "--carte"), ("--accent", "--fond"),
    ("--accent-texte", "--accent"), ("--erreur-texte", "--erreur-fond"), ("--ok", "--carte"),
    ("--ko", "--carte"), ("--reseau-bit", "--carte"), ("--hote-bit", "--carte"), ("--texte", "--libre-fond"),
]


@pytest.mark.parametrize("theme", ["clair", "sombre"])
def test_contrastes_du_texte_des_deux_themes(theme):
    clair, _, sombre = _blocs_css()
    couleurs = dict(clair)
    if theme == "sombre":
        couleurs.update(sombre)
    for texte, fond in PAIRES_TEXTE:
        assert contraste(couleurs[texte], couleurs[fond]) >= 4.5, (theme, texte, fond)


def test_blocs_colores_lisibles_avec_texte_blanc():
    clair, _, sombre = _blocs_css()
    for i in range(6):
        assert contraste("#ffffff", clair[f"--c{i}"]) >= 4.5, i      # --cN n'est pas redéfini en sombre


def test_css_prefers_color_scheme_et_data_theme():
    css = lire("style.css")
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="light"]' in css and ':root[data-theme="dark"]' in css


# --------------------------------------------------------------------------- #
# Clavier, focus, libellés, 360 px
# --------------------------------------------------------------------------- #

def test_focus_visible_style_pour_tous_les_controles():
    css = lire("style.css")
    bloc = re.search(r"(input:focus-visible[^{]*)\{([^}]*)\}", css)
    assert bloc
    selecteurs = bloc.group(1)
    for cible in ("input", "textarea", "select", "button", "a"):
        assert f"{cible}:focus-visible" in selecteurs, cible
    assert "outline" in bloc.group(2) and "none" not in bloc.group(2)
    assert not re.search(r"outline\s*:\s*(none|0)\s*;", css.replace("main:focus { outline: none; }", ""))


def test_champs_etiquetes_et_boutons_natifs(html):
    pour = {a.get("for") for t, a in html.balises if t == "label"}
    for t, a in html.balises:
        if t in ("input", "textarea", "select"):
            assert a.get("id") in pour, a
        if t == "button":
            assert a.get("type") in ("button", "submit"), a
        if t == "div" or t == "span":
            assert a.get("role") != "button" and "onclick" not in a, (t, a)
            assert "tabindex" not in a or a.get("role") == "region", (t, a)    # conteneur de tableau défilant


def test_aucun_tabindex_positif(html):
    for t, a in html.balises:
        if "tabindex" in a:
            assert int(a["tabindex"]) <= 0, (t, a)


def test_ordre_de_tabulation_logique(html):
    """Lien d'évitement, bascule de thème, navigation, puis formulaires dans l'ordre de la page."""
    ordre = [a.get("id") or a.get("href") for t, a in html.balises
             if t in ("a", "button", "input", "textarea", "select")]
    attendu = ["#contenu", "bascule-theme", "#section-vlsm", "#section-calculatrice", "#section-decoupage",
               "#section-verifications", "vlsm-parent", "vlsm-besoins", "vlsm-envoyer",
               "exp-csv", "exp-json", "exp-routeros", "calc-cidr", "dec-reseau", "dec-mode", "dec-valeur",
               "dec-envoyer", "app-ip", "app-reseau", "app-envoyer", "chev-a", "chev-b", "chev-envoyer"]
    assert ordre == attendu


def test_viewport_et_defilement_horizontal_maitrise(html):
    metas = {a.get("name"): a.get("content") for t, a in html.balises if t == "meta"}
    assert "width=device-width" in metas["viewport"]
    css = lire("style.css")
    assert re.search(r"\.tableau-defilant\s*\{[^}]*overflow-x\s*:\s*auto", css)
    assert re.search(r"main\s*\{[^}]*minmax\(0,\s*1fr\)", css)
    assert "@media (max-width: 30rem)" in css
    # Aucune largeur fixe en pixels supérieure à 360 px
    for valeur in re.findall(r"(?:min-)?width\s*:\s*(\d+)px", css):
        assert int(valeur) <= 360, valeur


def test_tableau_dans_un_conteneur_defilant_accessible(html):
    conteneurs = [a for t, a in html.balises if "tableau-defilant" in (a.get("class") or "")]
    assert conteneurs and all(c.get("tabindex") == "0" and c.get("aria-label") for c in conteneurs)


# --------------------------------------------------------------------------- #
# Interface d'export
# --------------------------------------------------------------------------- #

def test_boutons_export_presents(html):
    boutons = {a["id"]: a for t, a in html.balises if t == "button" and "id" in a}
    for id_ in ("exp-csv", "exp-json", "exp-routeros", "bascule-theme"):
        assert boutons[id_]["type"] == "button"
    texte = lire("index.html")
    assert "brouillon" in texte.lower() and "A_DEFINIR" in texte


def test_app_js_telecharge_la_reponse_de_l_api_sans_rien_generer():
    js = lire("app.js")
    assert '"/api/export/" + format' in js
    assert "URL.createObjectURL" in js and "URL.revokeObjectURL" in js and ".blob()" in js
    assert ".download =" in js
    # Aucun format de fichier construit côté JS
    for motif in ("hotes_demandes,reseau", "/ip address", "BROUILLON", "text/csv", "JSON.stringify(rep"):
        assert motif not in js, motif


def test_app_js_etat_du_plan():
    js = lire("app.js")
    for motif in ("window.location.hash", "URLSearchParams", "history.replaceState", "hashchange",
                  "localStorage", "netplan.dernierPlan"):
        assert motif in js, motif


def test_scripts_sans_api_dangereuse():
    motifs = [r"innerHTML", r"outerHTML", r"insertAdjacentHTML", r"document\s*\.\s*write", r"\beval\s*\(",
              r"new\s+Function", r"\bFunction\s*\(", r"createContextualFragment", r"DOMParser", r"\.srcdoc",
              r"document\s*\.\s*cookie", r"sessionStorage", r"XMLHttpRequest", r"WebSocket", r"\.(src|action)\s*=[^=]",
              r"setAttribute\s*\(\s*[\"'](style|on[a-z]+|href|src|srcdoc|action)[\"']",
              r"https?://"]
    for nom in ("app.js", "theme.js"):
        source = re.sub(r"/\*.*?\*/", "", lire(nom), flags=re.S)
        for motif in motifs:
            assert not re.search(motif, source), (nom, motif)


def test_theme_js_cibles_dom_existent(html):
    ids = {a["id"] for _, a in html.balises if "id" in a}
    utilises = set(re.findall(r'getElementById\("([A-Za-z0-9_-]+)"\)', lire("theme.js")))
    assert utilises == {"bascule-theme"} and utilises <= ids


def test_theme_js_charge_en_tete_sans_defer(html):
    scripts = [a for t, a in html.balises if t == "script"]
    assert [s["src"] for s in scripts] == ["/theme.js", "/app.js"]
    assert "defer" not in scripts[0] and "defer" in scripts[1]


# --------------------------------------------------------------------------- #
# Comportement (Node + faux DOM + vrai serveur)
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def serveur():
    srv = creer_serveur("127.0.0.1", 0, journal=False)
    fil = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    fil.start()
    yield "http://%s:%d" % srv.server_address[:2]
    srv.shutdown()
    srv.server_close()
    fil.join(timeout=5)


def jouer(serveur, scenario):
    sortie = subprocess.run(["node", HARNAIS, serveur, STATIC, json.dumps(scenario)],
                            capture_output=True, text=True, timeout=60)
    assert sortie.returncode == 0, sortie.stderr
    return json.loads(sortie.stdout)


node = pytest.mark.skipif(shutil.which("node") is None, reason="node absent : scénarios JS ignorés")

PARENT = "192.168.10.0/24"
BESOINS = "Serveurs 50, Wi-Fi 20\nAdmin 10"


@node
def test_fragment_recharge_et_recalcule_le_plan(serveur):
    etat = jouer(serveur, {"hash": "#reseau=192.168.10.0%2F24&besoins=LAN+50%2C+Voix+20%2C+Admin+10"})
    assert etat["champs"] == {"parent": PARENT, "besoins": "LAN 50, Voix 20, Admin 10"}
    assert [l[0] for l in etat["lignes"]] == ["LAN", "Voix", "Admin"]
    assert [l[2] for l in etat["lignes"]] == ["192.168.10.0/26", "192.168.10.64/27", "192.168.10.96/28"]
    assert etat["erreur_vlsm"] == ""


@node
def test_fragment_gagne_sur_le_stockage(serveur):
    stockage = {"netplan.dernierPlan": json.dumps({"reseau": "10.0.0.0/24", "besoins": "Ancien 5"})}
    etat = jouer(serveur, {"hash": "#reseau=172.16.0.0%2F24&besoins=Neuf+10", "stockage": stockage})
    assert etat["champs"]["parent"] == "172.16.0.0/24"
    assert [l[0] for l in etat["lignes"]] == ["Neuf"]


@node
def test_plan_calcule_ecrit_dans_le_fragment_et_le_navigateur(serveur):
    etat = jouer(serveur, {"etapes": [
        {"saisir": "vlsm-parent", "valeur": PARENT}, {"saisir": "vlsm-besoins", "valeur": BESOINS},
        {"evenement": "form-vlsm", "type": "submit"}]})
    from urllib.parse import parse_qs
    assert etat["hash"].startswith("#")
    params = parse_qs(etat["hash"][1:])
    assert params == {"reseau": [PARENT], "besoins": [BESOINS]}
    assert json.loads(etat["stockage"]["netplan.dernierPlan"]) == {"reseau": PARENT, "besoins": BESOINS}


@node
def test_dernier_plan_restaure_sans_fragment(serveur):
    stockage = {"netplan.dernierPlan": json.dumps({"reseau": PARENT, "besoins": BESOINS})}
    etat = jouer(serveur, {"stockage": stockage})
    assert etat["champs"] == {"parent": PARENT, "besoins": BESOINS}
    assert [l[0] for l in etat["lignes"]] == ["Serveurs", "Wi-Fi", "Admin"]


@pytest.mark.parametrize("brut", ["pas du json", "[1,2]", '{"reseau": 5, "besoins": "x"}', "null", '{"reseau": "a"}'])
@node
def test_stockage_corrompu_ignore(serveur, brut):
    etat = jouer(serveur, {"stockage": {"netplan.dernierPlan": brut}})
    assert etat["champs"]["parent"] == "192.168.0.0/22"             # valeurs d'exemple
    assert len(etat["lignes"]) == 4


@node
def test_plan_invalide_non_memorise_et_erreur_en_francais(serveur):
    etat = jouer(serveur, {"etapes": [
        {"saisir": "vlsm-parent", "valeur": "pas-un-reseau"}, {"evenement": "form-vlsm", "type": "submit"}]})
    assert "réseau parent" in etat["erreur_vlsm"].lower()
    assert "pas-un-reseau" not in etat["stockage"].get("netplan.dernierPlan", "")


@node
def test_fragment_hostile_reste_du_texte(serveur):
    hostile = "<img src=x onerror=alert(1)> 10"
    from urllib.parse import quote
    etat = jouer(serveur, {"hash": "#reseau=10.1.0.0%2F24&besoins=" + quote(hostile)})
    assert etat["champs"]["besoins"] == hostile
    assert etat["lignes"][0][0] == "<img src=x onerror=alert(1)>"


@node
def test_fragment_invalide_donne_une_erreur_francaise(serveur):
    etat = jouer(serveur, {"hash": "#reseau=zzz&besoins=A+5"})
    assert etat["erreur_vlsm"] and "zzz" in etat["erreur_vlsm"]
    assert etat["resultat_cache"] is True


@node
def test_ancre_de_navigation_conserve_le_lien_partageable(serveur):
    etat = jouer(serveur, {"etapes": [{"hash": "#section-calculatrice"}]})
    assert etat["hash"].startswith("#reseau=")


@node
def test_modification_du_fragment_recalcule(serveur):
    etat = jouer(serveur, {"etapes": [{"hash": "#reseau=10.9.0.0%2F24&besoins=Seul+100", "attendre": 700}]})
    assert etat["champs"]["parent"] == "10.9.0.0/24"
    assert [l[0] for l in etat["lignes"]] == ["Seul"]


@node
@pytest.mark.parametrize("format_, extension, debut, type_", [
    ("csv", ".csv", "nom,hotes_demandes,reseau,prefixe,masque,premier_hote,dernier_hote,broadcast,capacite", "text/csv"),
    ("json", ".json", "{", "application/json"),
    ("routeros", ".rsc", "# BROUILLON À VÉRIFIER", "text/plain"),
])
def test_boutons_export_telechargent_la_reponse_de_l_api(serveur, format_, extension, debut, type_):
    etat = jouer(serveur, {"hash": "#reseau=192.168.10.0%2F24&besoins=LAN+50%2C+Serveurs+20%2C+Admin+10",
                           "etapes": [{"evenement": "exp-" + format_, "type": "click", "attendre": 800}]})
    assert etat["erreur_export"] == ""
    assert len(etat["telechargements"]) == 1
    fichier = etat["telechargements"][0]
    assert fichier["download"] == "plan-192.168.10.0-24" + extension
    assert fichier["href"].startswith("blob:")
    assert fichier["texte"].startswith(debut)
    assert fichier["type"].startswith(type_)
    if format_ == "routeros":
        assert "address=192.168.10.65/27 network=192.168.10.64 " in fichier["texte"]


@node
def test_theme_par_defaut_systeme_et_bascule_memorisee(serveur):
    etat = jouer(serveur, {"systeme_sombre": True})
    assert etat["theme"] is None and etat["bouton_theme"] == "Passer au thème clair"
    etat = jouer(serveur, {"systeme_sombre": True, "etapes": [{"evenement": "bascule-theme", "type": "click"}]})
    assert etat["theme"] == "light" and etat["stockage"]["netplan.theme"] == "clair"
    assert etat["bouton_theme"] == "Passer au thème sombre"
    etat = jouer(serveur, {"systeme_sombre": False, "etapes": [{"evenement": "bascule-theme", "type": "click"}]})
    assert etat["theme"] == "dark" and etat["stockage"]["netplan.theme"] == "sombre"


@node
def test_theme_memorise_applique_au_chargement(serveur):
    etat = jouer(serveur, {"systeme_sombre": False, "stockage": {"netplan.theme": "sombre"}})
    assert etat["theme"] == "dark" and etat["bouton_theme"] == "Passer au thème clair"
    etat = jouer(serveur, {"systeme_sombre": True, "stockage": {"netplan.theme": "clair"}})
    assert etat["theme"] == "light"
    etat = jouer(serveur, {"systeme_sombre": False, "stockage": {"netplan.theme": "n'importe quoi"}})
    assert etat["theme"] is None


# --------------------------------------------------------------------------- #
# README
# --------------------------------------------------------------------------- #

def test_readme_section_netplan_studio():
    racine = os.path.dirname(REPERTOIRE_TESTS)
    with open(os.path.join(racine, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert re.search(r"^## NetPlan Studio$", readme, re.M)
    section = readme[readme.index("## NetPlan Studio"):]
    for attendu in ("python3 -m netplan --port 8080", "http://127.0.0.1:8080", "#reseau=", "besoins=",
                    "IPv4 uniquement", "256", "brouillon à vérifier", "/api/export/csv", "localStorage",
                    "Limites connues"):
        assert attendu in section, attendu
