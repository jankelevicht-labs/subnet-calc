/* NetPlan Studio – interface (JavaScript pur, sans framework ni ressource externe).
 *
 * Règles de ce fichier :
 *  - le JS ne calcule aucune adresse : il envoie les saisies à l'API (fetch POST JSON vers /api/...)
 *    et affiche les réponses ; seul le découpage du texte des besoins « Nom 50, Autre 120 » en
 *    {nom, hotes} est fait ici (analyse syntaxique, aucun calcul d'adresse) ;
 *  - tout affichage passe par createElement / textContent / setAttribute (jamais de HTML construit
 *    à partir de saisies ou de réponses) ;
 *  - les largeurs de la carte visuelle sont posées par propriétés CSSOM (element.style.width).
 */
(function () {
  "use strict";

  var DELAI_CALCULATRICE_MS = 250;
  var NOMBRE_COULEURS = 6;

  // ------------------------------------------------------------------ outils DOM

  function $(id) {
    return document.getElementById(id);
  }

  /** Crée un élément ; `classe` et `texte` sont optionnels (texte posé via textContent). */
  function el(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) { e.className = classe; }
    if (texte !== undefined && texte !== null) { e.textContent = String(texte); }
    return e;
  }

  function vider(noeud) {
    while (noeud.firstChild) { noeud.removeChild(noeud.firstChild); }
  }

  function montrer(noeud, visible) {
    if (visible) { noeud.removeAttribute("hidden"); } else { noeud.setAttribute("hidden", ""); }
  }

  function fixer(id, texte) {
    $(id).textContent = String(texte);
  }

  function pourcent(nombre) {
    return String(nombre).replace(".", ",") + " %";
  }

  // ------------------------------------------------------------------ appels à l'API

  var MESSAGE_RESEAU = "Impossible de joindre le serveur NetPlan : vérifiez qu'il est démarré.";

  /** POST JSON vers /api/<route> ; résout avec la réponse, rejette avec Error(message français). */
  function appeler(route, donnees) {
    return fetch("/api/" + route, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(donnees),
      cache: "no-store",
      credentials: "same-origin"
    }).then(function (reponse) {
      return reponse.json().then(function (corps) {
        if (reponse.ok) { return corps; }
        var message = corps && typeof corps.erreur === "string" ? corps.erreur
          : "Erreur inattendue du serveur (code " + reponse.status + ").";
        throw new Error(message);
      }, function () {
        throw new Error("Réponse illisible du serveur (code " + reponse.status + ").");
      });
    }, function () {
      throw new Error(MESSAGE_RESEAU);
    });
  }

  /**
   * Associe à un formulaire une zone d'erreur (role="alert") et un compteur : seule la réponse de la
   * dernière requête envoyée est affichée (les réponses tardives sont ignorées).
   */
  function nouvelleZone(idErreur) {
    var compteur = 0;
    return {
      lancer: function (promesse, succes) {
        compteur += 1;
        var mien = compteur;
        promesse.then(function (corps) {
          if (mien !== compteur) { return; }
          $(idErreur).textContent = "";
          succes(corps);
        }, function (erreur) {
          if (mien !== compteur) { return; }
          $(idErreur).textContent = erreur.message;
        });
      },
      annuler: function () {
        compteur += 1;
        $(idErreur).textContent = "";
      }
    };
  }

  // ------------------------------------------------------------------ planificateur VLSM

  /**
   * Découpe « Voix 50, Data 120, Wi-Fi invités 200 » en [{nom, hotes}] : séparateurs `,` `;` ou
   * retour à la ligne ; le dernier mot de chaque élément est le nombre d'hôtes (un « : » ou « = »
   * devant lui est toléré). Aucune validation ici : une valeur non numérique est transmise telle
   * quelle et c'est l'API qui répond en français.
   */
  function analyserBesoins(texte) {
    var besoins = [];
    texte.split(/[,;\n\r]+/).forEach(function (morceau) {
      var element = morceau.trim();
      if (!element) { return; }
      var m = /^(.+?)\s*[:=]\s*(\S+)$/.exec(element) || /^(.*\S)\s+(\S+)$/.exec(element);
      var seulNombre = !m && /^\d+$/.test(element);       // « 50 » : nombre sans nom
      var nom = m ? m[1].trim() : (seulNombre ? "" : element);
      var brut = m ? m[2] : (seulNombre ? element : "");  // « Admin » : nom sans nombre d'hôtes
      var hotes = brut;
      if (/^\d+$/.test(brut) && Number.isSafeInteger(Number(brut))) { hotes = Number(brut); }
      besoins.push({ nom: nom, hotes: hotes });
    });
    return besoins;
  }

  /** Rang du préfixe d'un CIDR « a.b.c.d/p » (affichage seulement : positionnement des blocs). */
  function prefixeDe(cidr) {
    return parseInt(String(cidr).split("/")[1], 10);
  }

  function blocCarte(classe, libelle, detail, prefixe, prefixeParent) {
    var bloc = el("div", "bloc " + classe);
    // Largeur proportionnelle : un bloc /p occupe 1 / 2^(p - préfixe du parent) de la carte.
    var largeur = 100 / Math.pow(2, prefixe - prefixeParent);
    bloc.style.width = largeur + "%";
    bloc.setAttribute("title", libelle + " – " + detail);
    bloc.appendChild(el("span", "bloc-nom", libelle));
    bloc.appendChild(el("span", "bloc-detail", detail));
    return bloc;
  }

  function afficherVlsm(rep) {
    var prefixeParent = prefixeDe(rep.parent);
    var carte = $("vlsm-carte");
    var legende = $("vlsm-legende");
    var corps = $("vlsm-corps");
    vider(carte); vider(legende); vider(corps);

    // Taux d'occupation
    var jauge = $("vlsm-jauge");
    jauge.setAttribute("aria-valuenow", String(rep.taux_occupation));
    jauge.setAttribute("aria-valuetext", pourcent(rep.taux_occupation));
    $("vlsm-jauge-remplie").style.width = Math.min(100, Math.max(0, rep.taux_occupation)) + "%";
    fixer("vlsm-taux", pourcent(rep.taux_occupation) + " de l'espace " + rep.parent + " est alloué");
    fixer("vlsm-legende-parent", "Espace parent : " + rep.parent
      + ". La largeur de chaque bloc est proportionnelle à son nombre d'adresses ; les blocs libres sont hachurés.");

    // Tableau + carte (blocs alloués, dans l'ordre d'allocation, puis blocs libres)
    rep.allocations.forEach(function (a, i) {
      var tr = el("tr");
      tr.appendChild(el("th", "", a.nom));
      tr.lastChild.setAttribute("scope", "row");
      tr.appendChild(el("td", "num", a.hotes_demandes));
      tr.appendChild(el("td", "mono", a.reseau));
      tr.appendChild(el("td", "mono", a.masque));
      tr.appendChild(el("td", "mono", a.premier_hote + " – " + a.dernier_hote));
      tr.appendChild(el("td", "mono", a.broadcast));
      tr.appendChild(el("td", "num", a.capacite));
      corps.appendChild(tr);

      var classe = "alloue couleur-" + (i % NOMBRE_COULEURS);
      carte.appendChild(blocCarte(classe, a.nom, a.reseau, a.prefixe, prefixeParent));

      var item = el("li");
      item.appendChild(el("span", "pastille " + classe));
      item.appendChild(el("span", "", a.nom + " : " + a.reseau + " (" + a.capacite + " hôtes utilisables)"));
      legende.appendChild(item);
    });

    rep.libres.forEach(function (cidr) {
      carte.appendChild(blocCarte("libre", "Libre", cidr, prefixeDe(cidr), prefixeParent));
      var item = el("li");
      item.appendChild(el("span", "pastille libre"));
      item.appendChild(el("span", "", "Libre : " + cidr));
      legende.appendChild(item);
    });

    fixer("vlsm-libres", rep.libres.length
      ? rep.libres.join(", ")
      : "Aucun : l'espace parent est entièrement alloué.");
    montrer($("resultat-vlsm"), true);
  }

  // ------------------------------------------------------------------ calculatrice CIDR

  function remplirBits(id, binaire, masque) {
    var cible = $(id);
    vider(cible);
    for (var i = 0; i < binaire.length; i += 1) {
      var c = binaire.charAt(i);
      if (c === ".") {
        cible.appendChild(el("span", "bits-sep", "."));
      } else {
        // Bit de réseau si le même bit du masque vaut 1 (pure mise en forme de la réponse de l'API).
        cible.appendChild(el("span", masque.charAt(i) === "1" ? "bit bit-reseau" : "bit bit-hote", c));
      }
    }
    cible.setAttribute("aria-label", binaire.replace(/\./g, " "));
  }

  function afficherCidr(rep) {
    fixer("calc-adresse", rep.adresse);
    fixer("calc-reseau", rep.reseau);
    fixer("calc-broadcast", rep.broadcast);
    fixer("calc-masque", rep.masque);
    fixer("calc-prefixe", "/" + rep.prefixe);
    fixer("calc-plage", rep.premier_hote + " – " + rep.dernier_hote);
    fixer("calc-nb-hotes", rep.nb_hotes);
    remplirBits("calc-bin-adresse", rep.binaire_adresse, rep.binaire_masque);
    remplirBits("calc-bin-masque", rep.binaire_masque, rep.binaire_masque);
    montrer($("resultat-calculatrice"), true);
  }

  // ------------------------------------------------------------------ découpage

  function afficherDecoupage(rep) {
    var liste = $("dec-liste");
    vider(liste);
    rep.sous_reseaux.forEach(function (cidr) {
      liste.appendChild(el("li", "mono", cidr));
    });
    fixer("dec-resume", rep.reseau + " découpé en " + rep.nombre_total + " sous-réseau"
      + (rep.nombre_total > 1 ? "x" : "") + " /" + rep.prefixe_cible + ".");
    var avert = $("dec-tronque");
    if (rep.tronque) {
      avert.textContent = "Liste tronquée : seuls les " + rep.sous_reseaux.length + " premiers sous-réseaux sur "
        + rep.nombre_total + " sont affichés.";
    } else {
      avert.textContent = "";
    }
    montrer(avert, rep.tronque === true);
    montrer($("resultat-decoupage"), true);
  }

  // ------------------------------------------------------------------ vérifications

  function afficherVerdict(id, vrai, texteOui, texteNon) {
    var p = $(id);
    p.textContent = vrai ? texteOui : texteNon;
    p.className = "verdict " + (vrai ? "verdict-oui" : "verdict-non");
    montrer(p, true);
  }

  // ------------------------------------------------------------------ câblage

  function demarrer() {
    // --- VLSM
    var zoneVlsm = nouvelleZone("erreur-vlsm");
    function planifier() {
      montrer($("resultat-vlsm"), false);
      zoneVlsm.lancer(appeler("vlsm", {
        parent: $("vlsm-parent").value,
        besoins: analyserBesoins($("vlsm-besoins").value)
      }), afficherVlsm);
    }
    $("form-vlsm").addEventListener("submit", function (evt) {
      evt.preventDefault();
      planifier();
    });

    // --- Calculatrice (mise à jour à la saisie, avec un léger délai)
    var zoneCalc = nouvelleZone("erreur-calculatrice");
    var minuteur = null;
    function calculer() {
      var valeur = $("calc-cidr").value;
      if (!valeur.trim()) {
        zoneCalc.annuler();
        montrer($("resultat-calculatrice"), false);
        return;
      }
      zoneCalc.lancer(appeler("cidr", { cidr: valeur }), afficherCidr);
    }
    $("calc-cidr").addEventListener("input", function () {
      if (minuteur !== null) { clearTimeout(minuteur); }
      minuteur = setTimeout(function () { minuteur = null; calculer(); }, DELAI_CALCULATRICE_MS);
    });
    $("form-calculatrice").addEventListener("submit", function (evt) {
      evt.preventDefault();
      if (minuteur !== null) { clearTimeout(minuteur); minuteur = null; }
      calculer();
    });

    // --- Découpage
    var zoneDec = nouvelleZone("erreur-decoupage");
    function majModeDecoupage() {
      var parPrefixe = $("dec-mode").value === "prefixe";
      fixer("dec-valeur-libelle", parPrefixe ? "Préfixe cible (0 à 32)" : "Nombre de sous-réseaux (N)");
      $("dec-valeur").setAttribute("placeholder", parPrefixe ? "26" : "8");
    }
    $("dec-mode").addEventListener("change", majModeDecoupage);
    function decouper() {
      montrer($("resultat-decoupage"), false);
      var brut = $("dec-valeur").value.trim();
      // Un entier est transmis comme nombre JSON ; tout le reste tel quel (l'API répondra en français).
      var valeur = /^\d+$/.test(brut) && Number.isSafeInteger(Number(brut)) ? Number(brut) : brut;
      var corps = { reseau: $("dec-reseau").value };
      corps[$("dec-mode").value === "prefixe" ? "prefixe" : "n"] = valeur;
      zoneDec.lancer(appeler("decoupage", corps), afficherDecoupage);
    }
    $("form-decoupage").addEventListener("submit", function (evt) {
      evt.preventDefault();
      decouper();
    });
    majModeDecoupage();

    // --- Appartenance
    var zoneApp = nouvelleZone("erreur-appartenance");
    $("form-appartenance").addEventListener("submit", function (evt) {
      evt.preventDefault();
      montrer($("resultat-appartenance"), false);
      zoneApp.lancer(appeler("appartenance", {
        ip: $("app-ip").value,
        reseau: $("app-reseau").value
      }), function (rep) {
        afficherVerdict("resultat-appartenance", rep.appartient,
          "Oui : " + rep.ip + " appartient à " + rep.reseau + ".",
          "Non : " + rep.ip + " n'appartient pas à " + rep.reseau + ".");
      });
    });

    // --- Chevauchement
    var zoneChev = nouvelleZone("erreur-chevauchement");
    $("form-chevauchement").addEventListener("submit", function (evt) {
      evt.preventDefault();
      montrer($("resultat-chevauchement"), false);
      zoneChev.lancer(appeler("chevauchement", {
        a: $("chev-a").value,
        b: $("chev-b").value
      }), function (rep) {
        afficherVerdict("resultat-chevauchement", rep.chevauchement,
          "Oui : " + rep.a + " et " + rep.b + " se chevauchent.",
          "Non : " + rep.a + " et " + rep.b + " ne se chevauchent pas.");
      });
    });

    // Résultats initiaux avec les valeurs d'exemple
    calculer();
    planifier();
    decouper();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", demarrer);
  } else {
    demarrer();
  }
})();
