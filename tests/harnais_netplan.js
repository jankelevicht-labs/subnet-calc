// Harnais de test (Node, sans dépendance) : exécute theme.js et app.js avec un faux DOM minimal contre
// un vrai serveur NetPlan, rejoue des étapes et affiche l'état final en JSON.
//
//   node harnais_netplan.js <URL du serveur> <dossier static> '<scénario JSON>'
//
// Scénario : {"hash": "#...", "stockage": {clé: valeur}, "systeme_sombre": bool, "etapes": [...]}
// Étapes : {"saisir": id, "valeur": texte} | {"evenement": id, "type": "submit|click|input|change"}
//          | {"hash": "#..."} (hashchange) | {"attendre": ms}
// Le contenu des fichiers téléchargés (clic sur une ancre « download » dont l'URL est un Blob) est lu.
"use strict";
const fs = require("fs");

const [BASE, STATIC, SCENARIO_JSON] = process.argv.slice(2);
const scenario = JSON.parse(SCENARIO_JSON || "{}");
const html = fs.readFileSync(STATIC + "/index.html", "utf8");
const attendre = (ms) => new Promise((r) => setTimeout(r, ms));

class Element {
  constructor(balise) {
    this.tag = balise; this.children = []; this.attrs = {}; this.style = {}; this.listeners = {};
    this._texte = ""; this.className = ""; this.value = "";
  }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  set textContent(t) { this.children = []; this._texte = String(t); }
  get textContent() { return this._texte + this.children.map((c) => c.textContent).join(""); }
  declencher(type) { (this.listeners[type] || []).forEach((f) => f({ preventDefault() {}, type })); }
  click() {
    if (this.tag === "a" && this.download !== undefined) { telechargements.push({ href: this.href, download: this.download }); }
    this.declencher("click");
  }
}

const parId = {};
for (const m of html.matchAll(/<(\w+)([^>]*?)\bid="([^"]+)"([^>]*)>/g)) {
  const e = new Element(m[1]); parId[m[3]] = e;
  const attrs = m[2] + " " + m[4];
  if (/\bhidden\b/.test(attrs)) { e.attrs.hidden = ""; }
  const v = /\bvalue="([^"]*)"/.exec(attrs); if (v) { e.value = v[1]; }
  const tb = e.tag === "button" ? />([^<]*)</.exec(html.slice(m.index + m[0].length - 1)) : null;
  if (tb) { e._texte = tb[1]; }
}
parId["vlsm-besoins"].value = /<textarea[^>]*id="vlsm-besoins"[^>]*>([^<]*)<\/textarea>/.exec(html)[1];
parId["dec-mode"].value = "n";

const telechargements = [];
const blobs = new Map();
let compteurBlob = 0;
URL.createObjectURL = (blob) => { const u = "blob:test/" + (++compteurBlob); blobs.set(u, blob); return u; };
URL.revokeObjectURL = () => {};

const stockage = new Map(Object.entries(scenario.stockage || {}));
const ecouteursDoc = {};
const ecouteursFenetre = {};
const racine = new Element("html");
const corps = new Element("body");
const historique = [];

global.document = {
  readyState: "loading",
  documentElement: racine,
  body: corps,
  getElementById: (id) => { if (!parId[id]) { throw new Error("id absent " + id); } return parId[id]; },
  createElement: (t) => new Element(t),
  addEventListener: (t, f) => { (ecouteursDoc[t] = ecouteursDoc[t] || []).push(f); },
};
global.window = {
  location: { hash: scenario.hash || "" },
  history: { replaceState: (_e, _t, url) => { historique.push(url); if (String(url).startsWith("#")) { global.window.location.hash = url; } } },
  localStorage: {
    getItem: (k) => (stockage.has(k) ? stockage.get(k) : null),
    setItem: (k, v) => { stockage.set(k, String(v)); },
  },
  matchMedia: () => ({ matches: !!scenario.systeme_sombre, addEventListener() {} }),
  addEventListener: (t, f) => { (ecouteursFenetre[t] = ecouteursFenetre[t] || []).push(f); },
};
const realFetch = fetch;
global.fetch = (u, o) => realFetch(BASE + u, o);

(async () => {
  (0, eval)(fs.readFileSync(STATIC + "/theme.js", "utf8"));   // exécution des scripts de l'interface (harnais de test uniquement)
  (0, eval)(fs.readFileSync(STATIC + "/app.js", "utf8"));
  document.readyState = "complete";
  (ecouteursDoc.DOMContentLoaded || []).forEach((f) => f());
  await attendre(scenario.attente_initiale || 700);

  for (const etape of scenario.etapes || []) {
    if (etape.saisir) { parId[etape.saisir].value = etape.valeur; }
    if (etape.evenement) { parId[etape.evenement].declencher(etape.type); }
    if (etape.hash !== undefined) {
      global.window.location.hash = etape.hash;
      (ecouteursFenetre.hashchange || []).forEach((f) => f({ type: "hashchange" }));
    }
    await attendre(etape.attendre || 500);
  }

  const contenus = [];
  for (const t of telechargements) { contenus.push({ download: t.download, href: t.href, texte: await blobs.get(t.href).text(), type: blobs.get(t.href).type }); }
  const lignes = parId["vlsm-corps"].children.map((tr) => tr.children.map((c) => c.textContent));
  console.log(JSON.stringify({
    champs: { parent: parId["vlsm-parent"].value, besoins: parId["vlsm-besoins"].value },
    hash: global.window.location.hash,
    stockage: Object.fromEntries(stockage),
    lignes,
    resultat_cache: "hidden" in parId["resultat-vlsm"].attrs,
    erreur_vlsm: parId["erreur-vlsm"].textContent,
    erreur_export: parId["erreur-export"].textContent,
    theme: racine.getAttribute("data-theme"),
    bouton_theme: parId["bascule-theme"].textContent,
    telechargements: contenus,
    historique,
  }));
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(2); });
