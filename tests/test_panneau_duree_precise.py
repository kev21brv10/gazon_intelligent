"""Les délais du garage de la tondeuse se règlent maintenant à la seconde près.

Demande du 21/09/2026 : « pour le volet ça serait bien qu'il y ait des secondes pour que
ce soit plus précis ». `tondeuse_garage_avance_ouverture` et `tondeuse_garage_delai_fermeture`
passent d'un pas d'une minute à un quart de minute (15 s) ; l'affichage (`dureeFr`) doit montrer
ces secondes au lieu de les arrondir en silence.
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
reglages_module = importlib.import_module("custom_components.gazon_intelligent.reglages")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const chemin = JSON.parse(fs.readFileSync(0, "utf8")).chemin;
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: () => {} },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

const dureeFr = vm.runInContext("dureeFr", ctx);
process.stdout.write(JSON.stringify({
  zero: dureeFr(0),
  quinzeSecondes: dureeFr(0.25),
  uneMinuteQuart: dureeFr(1.25),
  deuxMinutesPile: dureeFr(2),
  uneHeureCinq: dureeFr(65),
  uneHeurePile: dureeFr(60),
}));
"""


def _rendre() -> dict[str, str]:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU)}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class DureeAvecSecondesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre()

    def test_les_secondes_sont_affichees_au_lieu_detre_arrondies(self) -> None:
        self.assertEqual(self.rendu["zero"], "0 min")
        self.assertEqual(self.rendu["quinzeSecondes"], "15 s")
        self.assertEqual(self.rendu["uneMinuteQuart"], "1 min 15 s")

    def test_une_duree_ronde_ne_change_pas_daffichage(self) -> None:
        self.assertEqual(self.rendu["deuxMinutesPile"], "2 min")
        self.assertEqual(self.rendu["uneHeurePile"], "1 h")
        self.assertEqual(self.rendu["uneHeureCinq"], "1" + " " + "h" + " " + "05")


class GarageDelaisPasEnSecondesTests(unittest.TestCase):
    def test_les_deux_delais_du_garage_se_reglent_au_quart_de_minute(self) -> None:
        par_cle = {r.cle: r for r in reglages_module.REGLAGES}
        for cle in ("tondeuse_garage_avance_ouverture", "tondeuse_garage_delai_fermeture"):
            with self.subTest(cle=cle):
                self.assertEqual(par_cle[cle].pas, 0.25)
                self.assertEqual(par_cle[cle].genre, "duree")


if __name__ == "__main__":
    unittest.main()
