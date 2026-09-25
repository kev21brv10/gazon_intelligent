"""Les cartes de débit par zone, dans l'onglet Installation, tiennent en une ligne par zone.

Demande directe (25/09/2026) : avec 4-5 zones, la carte « Arroseurs » alignait une question
complète, son aide et un curseur pleine largeur pour CHAQUE zone — répété presque à
l'identique zone par zone, sans rien ajouter d'utile après la première. Ce test charge
`_installationHtml()` avec de vraies entités de débit simulées et vérifie que chaque zone
rend une ligne compacte (nom + valeur + curseur), pas la question complète répétée, tout en
gardant les mêmes attributs `data-cle`/`data-entite` et le même curseur interactif que le
reste de la page (`_pas`/`_surCurseur` s'y attendent).
"""

from __future__ import annotations

import importlib
import json
import re
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
p._donnees = {
  registre,
  entites: {
    debit_zone_1: "number.debit_zone_1", debit_zone_2: "number.debit_zone_2", debit_zone_3: "number.debit_zone_3",
    arrosage_automatique: "switch.arrosage_auto",
  },
  zones: [{ numero: 1, nom: "Vanne devant" }, { numero: 2, nom: "Vanne derrière" }],
};
p._hass = {
  user: { is_admin: true },
  states: {
    "number.debit_zone_1": { state: "14", attributes: { min: 0, max: 200, step: 1, unit_of_measurement: "mm/h" } },
    "number.debit_zone_2": { state: "14", attributes: { min: 0, max: 200, step: 1, unit_of_measurement: "mm/h" } },
    "number.debit_zone_3": { state: "0", attributes: { min: 0, max: 200, step: 1, unit_of_measurement: "mm/h" } },
    "switch.arrosage_auto": { state: "on", attributes: {} },
  },
};
p._brouillon = {};
p._brouillonEntites = {};
p._brouillonChoix = {};
p._brouillonAlertes = {};
p._attenteEntites = {};
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
class ZonesDebitCompactesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = _rendre()["html"]

    def test_chaque_zone_branchee_est_rendue(self) -> None:
        for cle in ("debit_zone_1", "debit_zone_2", "debit_zone_3"):
            self.assertIn(f'data-cle="{cle}"', self.html)

    def test_les_lignes_de_zone_sont_compactes(self) -> None:
        lignes = re.findall(r'<div class="ligne ligne-compacte[^"]*"[^>]*data-cle="debit_zone_\d"[^>]*>', self.html)
        self.assertEqual(len(lignes), 3)

    def test_la_question_complete_ne_se_repete_plus_par_zone(self) -> None:
        self.assertNotIn("combien de millimètres d'eau en une heure", self.html)

    def test_le_pied_de_ligne_min_max_revenir_a_disparu(self) -> None:
        bloc = re.search(r'data-cle="debit_zone_1".*?</div>\s*</div>', self.html, re.S)
        self.assertIsNotNone(bloc)
        self.assertNotIn("ligne-pied", bloc.group(0))

    def test_le_nom_de_zone_remplace_le_numero_quand_il_existe(self) -> None:
        self.assertIn("Vanne devant", self.html)
        self.assertIn("Vanne derrière", self.html)

    def test_le_curseur_garde_ses_bornes_et_reste_interactif(self) -> None:
        bloc = re.search(r'data-cle="debit_zone_1".*?</div>\s*</div>', self.html, re.S).group(0)
        self.assertIn('type="range"', bloc)
        self.assertIn('min="0"', bloc)
        self.assertIn('max="200"', bloc)
        self.assertIn('data-action="moins"', bloc)
        self.assertIn('data-action="plus"', bloc)

    def test_les_lignes_non_zone_restent_completes(self) -> None:
        # Un interrupteur classique de l'onglet Installation ne doit pas devenir compact :
        # la compaction cible uniquement les zones de débit répétées.
        self.assertIn('data-cle="arrosage_automatique"', self.html)
        bloc = re.search(r'data-cle="arrosage_automatique".*?</div>\s*</div>', self.html, re.S)
        self.assertIsNotNone(bloc)
        self.assertNotIn("ligne-compacte", bloc.group(0))


if __name__ == "__main__":
    unittest.main()
