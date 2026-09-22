"""La surface du gazon doit être modifiable depuis l'onglet Installation.

P1 signalé en relecture automatique sur la PR #53 : `surface_gazon_m2` a été ajouté au
registre des réglages avec `groupe="installation"`, mais l'onglet Installation n'est PAS
rendu par le mécanisme générique `_groupeHtml` (qui lit les réglages par groupe) — il a son
propre rendu `_installationHtml`, entièrement composé de cartes câblées à la main (entités,
choix, pilotage, garage, alertes). Un réglage seulement déclaré dans le registre y restait
donc invisible : personne ne pouvait renseigner sa surface depuis la page, contrairement à ce
que suggérait le réglage. Ce test charge `_installationHtml()` avec le VRAI registre de
`reglages.py` (pas un registre inventé) et vérifie que la ligne existe bel et bien dans le
HTML produit.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
PANNEAU = PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
reglages = importlib.import_module("custom_components.gazon_intelligent.reglages")
REGISTRE = reglages.exporter()

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, registre } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

const p = Object.create(ctx.Classe.prototype);
p._donnees = { registre, entites: {} };
p._brouillon = {};
p._brouillonEntites = {};
p._brouillonChoix = {};
p._brouillonAlertes = {};
p._narrow = false;

const html = p._installationHtml();
process.stdout.write(JSON.stringify({ html }));
"""


def _rendre() -> dict[str, str]:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "registre": REGISTRE}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class SurfaceGazonDansInstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _rendre()["html"]

    def test_le_reglage_de_surface_est_rendu_dans_installation(self) -> None:
        self.assertIn('data-cle="surface_gazon_m2"', self.html)

    def test_le_titre_et_laide_du_reglage_sont_visibles(self) -> None:
        self.assertIn("Quelle est la surface totale du gazon", self.html)


SCRIPT_BROUILLON = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, registre } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

const p = Object.create(ctx.Classe.prototype);
p._donnees = { registre, entites: {}, entry_id: "test" };
p._brouillon = { surface_gazon_m2: 255 };
p._brouillonEntites = {};
p._brouillonChoix = {};
p._brouillonAlertes = {};
p._narrow = false;
p._fenetre = { contains: () => false };
p._rendre = () => {};

const groupeInstallation = registre.groupes.find((g) => g.cle === "installation") || { cle: "installation", icone: "" };
const badgeAvant = /<span class="compteur"[^>]*>(\d+)<\/span>/.exec(p._ongletHtml(groupeInstallation, false));
const annulerHtmlAvant = p._installationHtml();
const boutonActif = !/data-action="annuler-installation"[^>]*disabled/.test(annulerHtmlAvant);

// Simule le clic sur « Annuler les changements » : un bouton sans data-cle englobant,
// exactement la structure réelle du bouton dans _installationHtml.
const bouton = {
  dataset: { action: "annuler-installation" },
  disabled: false,
  closest: (sel) => (sel === "[data-cle]" ? null : null),
};
const cible = {
  closest: (sel) => (sel === "[data-action]" ? bouton : null),
};
const evenement = { target: cible };
p._surClic(evenement);

process.stdout.write(JSON.stringify({
  badgeAvant: badgeAvant ? Number(badgeAvant[1]) : 0,
  boutonActifAvant: boutonActif,
  brouillonApres: p._brouillon,
}));
"""


def _rendre_brouillon() -> dict:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT_BROUILLON],
        input=json.dumps({"chemin": str(PANNEAU), "registre": REGISTRE}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class SurfaceGazonComptabiliteBrouillonTests(unittest.TestCase):
    """P2 signalé en relecture automatique : le compteur de l'onglet Installation et son
    bouton « Annuler les changements » ne comptaient que les brouillons d'entités, de choix
    et d'alertes — jamais les réglages génériques comme `surface_gazon_m2`, qui passent par
    `_brouillon`. Une modification de la surface seule restait donc invisible au compteur et
    le bouton « Annuler » ne l'effaçait pas.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.resultat = _rendre_brouillon()

    def test_le_badge_de_longlet_compte_le_brouillon_de_surface(self) -> None:
        self.assertEqual(self.resultat["badgeAvant"], 1)

    def test_le_bouton_annuler_est_actif_avec_un_brouillon_de_surface(self) -> None:
        self.assertTrue(self.resultat["boutonActifAvant"])

    def test_annuler_installation_efface_le_brouillon_de_surface(self) -> None:
        self.assertNotIn("surface_gazon_m2", self.resultat["brouillonApres"])


if __name__ == "__main__":
    unittest.main()
