/* NetPlan Studio – thème clair / sombre.
 *
 * Chargé en tête de page (sans defer) pour appliquer le thème mémorisé avant le premier affichage.
 *  - par défaut : le thème du système (prefers-color-scheme), géré par la feuille de style ;
 *  - bouton de bascule : choix « clair » ou « sombre » posé dans l'attribut data-theme de <html> et
 *    mémorisé dans localStorage (clé « netplan.theme ») ;
 *  - localStorage peut être indisponible (navigation privée, stockage bloqué) : tout est protégé.
 */
(function () {
  "use strict";

  var CLE = "netplan.theme";
  var racine = document.documentElement;

  function lire() {
    try {
      var valeur = window.localStorage.getItem(CLE);
      return valeur === "clair" || valeur === "sombre" ? valeur : null;
    } catch (e) {
      return null;
    }
  }

  function ecrire(choix) {
    try { window.localStorage.setItem(CLE, choix); } catch (e) { /* stockage indisponible : choix non mémorisé */ }
  }

  function themeSysteme() {
    var requete = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    return requete && requete.matches ? "sombre" : "clair";
  }

  /** Thème réellement affiché : le choix mémorisé, sinon celui du système. */
  function themeActuel() {
    return lire() || themeSysteme();
  }

  function appliquer(choix) {
    if (choix) {
      racine.setAttribute("data-theme", choix === "sombre" ? "dark" : "light");
    } else {
      racine.removeAttribute("data-theme");
    }
  }

  function majBouton() {
    var bouton = document.getElementById("bascule-theme");
    if (!bouton) { return; }
    bouton.textContent = themeActuel() === "sombre" ? "Passer au thème clair" : "Passer au thème sombre";
  }

  appliquer(lire());

  document.addEventListener("DOMContentLoaded", function () {
    var bouton = document.getElementById("bascule-theme");
    if (!bouton) { return; }
    majBouton();
    bouton.addEventListener("click", function () {
      var suivant = themeActuel() === "sombre" ? "clair" : "sombre";
      appliquer(suivant);
      ecrire(suivant);
      majBouton();
    });
    // Sans choix mémorisé, le libellé suit les changements du thème du système.
    if (window.matchMedia) {
      var requete = window.matchMedia("(prefers-color-scheme: dark)");
      if (requete.addEventListener) { requete.addEventListener("change", majBouton); }
    }
  });
})();
