"""Couverture des réglages complets des programmes Semis et Sursemis.

Les paramètres d'arrosage du groupe ``graines`` sont communs aux deux programmes. Ils doivent
être visibles dans chacun de leurs onglets, sans copie de valeur ni doublon, aux côtés des
réglages de tonte propres au Semis ou au Sursemis.
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
    module.__path__ = [str(path)]
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
p._donnees = { registre, valeurs: {} };
p._brouillon = {};
p._hass = { user: { is_admin: true }, states: {} };
p._ligneHtml = (r) => `<div class="ligne" data-cle="${r.cle}"></div>`;
p._dessinHtml = () => "";

const rendre = (cle) => {
  const groupe = registre.groupes.find((g) => g.cle === cle);
  return p._groupeHtml(groupe);
};
p._narrow = false;
const bureau = { semis: rendre("semis"), sursemis: rendre("sursemis"), tonte: rendre("tonte") };
p._narrow = true;
const mobile = { semis: rendre("semis"), sursemis: rendre("sursemis"), tonte: rendre("tonte") };
process.stdout.write(JSON.stringify({ ...bureau, bureau, mobile }));
"""


def _rendre() -> dict[str, str]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "registre": REGISTRE}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(sortie.stdout)


def _cles(html: str) -> list[str]:
    return re.findall(r'data-cle="([^"]+)"', html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class ProgrammesSemisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre()

    def test_semis_affiche_tous_les_reglages_reels_sans_doublon(self) -> None:
        attendues = {
            r["cle"] for r in REGISTRE["reglages"] if r["groupe"] in {"graines", "semis"}
        }
        affichees = _cles(self.rendu["semis"])
        self.assertEqual(set(affichees), attendues)
        self.assertEqual(len(affichees), len(attendues), "un réglage Semis est affiché deux fois")

    def test_sursemis_affiche_tous_les_reglages_reels_sans_doublon(self) -> None:
        attendues = {
            r["cle"] for r in REGISTRE["reglages"] if r["groupe"] in {"graines", "sursemis"}
        }
        affichees = _cles(self.rendu["sursemis"])
        self.assertEqual(set(affichees), attendues)
        self.assertEqual(len(affichees), len(attendues), "un réglage Sursemis est affiché deux fois")

    def test_les_reglages_communs_sont_expliques_comme_tels(self) -> None:
        communs = sum(1 for r in REGISTRE["reglages"] if r["groupe"] == "graines")
        sections_communes = len(re.findall(r"Commun Semis / Sursemis", self.rendu["semis"]))
        self.assertGreater(communs, 0)
        self.assertGreater(sections_communes, 0)
        self.assertIn('data-groupes="graines,semis"', self.rendu["semis"])
        self.assertIn('data-groupes="graines,sursemis"', self.rendu["sursemis"])

    def test_graines_n_est_plus_un_onglet_separe(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn('this._registre.groupes.filter((g) => g.cle !== "graines")', source)
        self.assertNotIn('Semis: [["graines", "Graines"]', source)
        self.assertNotIn('Sursemis: [["graines", "Graines"]', source)

    def test_les_groupes_sont_ouverts_sur_grand_ecran(self) -> None:
        for onglet in ("semis", "sursemis", "tonte"):
            details = re.findall(r"<details[^>]*>", self.rendu["bureau"][onglet])
            self.assertTrue(details, onglet)
            self.assertTrue(all(" open" in detail for detail in details), onglet)

    def test_les_groupes_sont_replies_sur_mobile(self) -> None:
        for onglet in ("semis", "sursemis", "tonte"):
            details = re.findall(r"<details[^>]*>", self.rendu["mobile"][onglet])
            self.assertTrue(details, onglet)
            self.assertTrue(all(" open" not in detail for detail in details), onglet)


if __name__ == "__main__":
    unittest.main()
