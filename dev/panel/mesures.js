// Outils de mesure de la mosaïque, pour l'aperçu local. Dans la console de l'aperçu :
//   const m = await import("./mesures.js");
//   await m.bilan();                                  // hauteur de page, chevauchements, trous
//   await m.optimiser(["reglages:tonte"], "--l");     // meilleures répartitions dans les couloirs
// Les largeurs à vérifier (Home Assistant, barre latérale ouverte) : 1 184, 1 384, 1 664, 1 920 px.

const COULOIRS_GRANDS = { gauche: "1 / span 5", milieu: "6 / span 4", droite: "10 / span 3" };
const COULOIRS_MOYENS = { large: "1 / span 7", etroit: "8 / span 5" };

export const CIBLES = [
  "accueil:apercu", "accueil:arrosage", "accueil:tonte", "accueil:gazon", "accueil:produits",
  "reglages:tonte", "reglages:arrosage", "reglages:graines", "reglages:sursemis", "reglages:semis",
  "reglages:modes", "reglages:installation",
];

const attendre = (ms) => new Promise((r) => setTimeout(r, ms));
const panneau = () => document.querySelector("gazon-intelligent-panel");

async function ouvrir(cible) {
  const p = panneau();
  const r = p.shadowRoot;
  const [vue, onglet] = cible.split(":");
  if (p._vue !== vue) {
    r.querySelector(`[data-vue="${vue}"]`).click();
    await attendre(400);
  }
  r.querySelector(vue === "accueil" ? `[data-onglet-accueil="${onglet}"]` : `[data-onglet="${onglet}"]`)?.click();
  await attendre(500);
  return r;
}

// Pour chaque onglet : hauteur de page, largeurs des cadres, chevauchements et trous dans un couloir.
export async function bilan(cibles = CIBLES) {
  const res = {};
  for (const cible of cibles) {
    const r = await ouvrir(cible);
    const cases = [...r.querySelectorAll(".mosaique > .tesselle")].map((c) => c.getBoundingClientRect());
    let chevauchements = 0;
    for (let i = 0; i < cases.length; i++) {
      for (let j = i + 1; j < cases.length; j++) {
        const a = cases[i];
        const b = cases[j];
        if (a.x < b.x + b.width - 1 && b.x < a.x + a.width - 1 && a.y < b.y + b.height - 1 && b.y < a.y + a.height - 1) chevauchements++;
      }
    }
    const parX = {};
    for (const c of cases) (parX[Math.round(c.x)] ||= []).push(c);
    let trous = 0;
    for (const liste of Object.values(parX)) {
      liste.sort((a, b) => a.y - b.y);
      for (let i = 1; i < liste.length; i++) if (liste[i].y - (liste[i - 1].y + liste[i - 1].height) > 20) trous++;
    }
    const page = r.querySelector(".page");
    res[cible] = `${page.scrollHeight} px · largeurs ${[...new Set(cases.map((c) => Math.round(c.width)))].join("/")}`
      + ` · chevauchements ${chevauchements} · trous ${trous}${page.scrollWidth > page.clientWidth ? " · DÉBORDE" : ""}`;
  }
  return res;
}

// Hauteur de chaque cadre dans chaque couloir (sans rien changer à la page).
export async function hauteursParCouloir(cibles, variable = "--l", couloirs = variable === "--l" ? COULOIRS_GRANDS : COULOIRS_MOYENS) {
  const res = {};
  for (const cible of cibles) {
    const r = await ouvrir(cible);
    const t = [...r.querySelectorAll(".mosaique > .tesselle")];
    const avant = t.map((c) => c.style.getPropertyValue(variable));
    res[cible] = t.map((c, i) => {
      const ligne = { titre: (c.querySelector("h3,h2,b")?.textContent || "").trim().slice(0, 18) };
      for (const [nom, v] of Object.entries(couloirs)) {
        c.style.setProperty(variable, v);
        ligne[nom] = Math.round(c.getBoundingClientRect().height);
      }
      c.style.setProperty(variable, avant[i]);
      return ligne;
    });
  }
  return res;
}

// Toutes les répartitions (l'ordre du code est gardé dans chaque couloir), de la plus basse à la
// plus haute. `permis[cible][i]` : les initiales des couloirs autorisés pour le cadre i.
export async function optimiser(cibles, variable = "--l", permis = {}) {
  const couloirs = variable === "--l" ? COULOIRS_GRANDS : COULOIRS_MOYENS;
  const mesures = await hauteursParCouloir(cibles, variable, couloirs);
  const noms = Object.keys(couloirs);
  const res = {};
  for (const [cible, cartes] of Object.entries(mesures)) {
    const classement = [];
    for (let code = 0; code < noms.length ** cartes.length; code++) {
      const h = new Array(noms.length).fill(0);
      const n = new Array(noms.length).fill(0);
      let x = code;
      let ok = true;
      const choix = [];
      cartes.forEach((c, i) => {
        const j = x % noms.length;
        x = Math.floor(x / noms.length);
        if (permis[cible] && !permis[cible][i].includes(noms[j][0])) ok = false;
        choix.push(noms[j][0]);
        h[j] += c[noms[j]] + (n[j] ? 16 : 0);
        n[j]++;
      });
      if (ok) classement.push({ max: Math.max(...h), choix: choix.join(""), hauteurs: h.join("/") });
    }
    classement.sort((a, b) => a.max - b.max);
    res[cible] = {
      cadres: cartes.map((c) => `${c.titre} ${noms.map((nn) => c[nn]).join("/")}`),
      meilleurs: classement.slice(0, 6).map((b) => `${b.max} ${b.choix} (${b.hauteurs})`),
    };
  }
  return res;
}
