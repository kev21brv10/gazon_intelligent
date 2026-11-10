"""Échelle d'ensemble du panneau (90 %) : le CSS la pose, la mosaïque la compense.

Figé ici : une seule constante règle la taille de tout (page, fenêtre de dialogue, barre « Enregistrer »,
confirmation), et le calcul des rangées de la mosaïque lit la hauteur À L'ÉCRAN (le navigateur applique
le zoom aux mesures) puis la ramène à l'espace de mise en page, sans quoi les cadres se chevaucheraient
d'un dixième. Le vrai JS est exécuté dans Node.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, hauteurs } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console, structuredClone,
  getComputedStyle: () => ({ columnGap: "16px" }),
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const p = Object.create(ctx.Classe.prototype);
const grille = {};
const cases = hauteurs.map((h) => ({ isConnected: true, parentElement: grille, style: {}, getBoundingClientRect: () => ({ height: h }) }));
p._caserMosaique(cases);
process.stdout.write(JSON.stringify(cases.map((c) => c.style.gridRowEnd)));
"""


@unittest.skipUnless(NODE, "Node n'est pas installé")
class EchellePanneauTests(unittest.TestCase):
    def test_une_seule_constante_regle_l_echelle_de_tout_le_panneau(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertRegex(source, r"const ECHELLE_PANNEAU = 0\.9;")
        (regle,) = re.findall(r"^([^\n{]+)\{ zoom: \$\{ECHELLE_PANNEAU\}; \}$", source, flags=re.M)
        for element in (".page", ".dialogue", ".barre-enregistrer", ".toast"):
            self.assertIn(element, regle)

    def test_les_rangees_de_la_mosaique_partent_de_la_hauteur_hors_zoom(self) -> None:
        # À l'écran 90 px = 100 px de mise en page : (100 + 16) / 4 = 29 rangées (et non 27 sur 90 + 16).
        sortie = subprocess.run(
            [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "hauteurs": [90, 180]}),
            capture_output=True, text=True, check=True, timeout=60,
        )
        self.assertEqual(json.loads(sortie.stdout), ["span 29", "span 54"])


if __name__ == "__main__":
    unittest.main()
