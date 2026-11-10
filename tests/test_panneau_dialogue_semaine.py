"""La fenêtre « Arroser maintenant » dit ce que l'arrosage demandé ajoute à l'eau de la semaine.

Elle ne dit que l'arithmétique et le dépassement d'un plafond, jamais ce que le moteur en ferait ;
hors de la phase Normal le plafond n'est qu'un repère et aucun dépassement n'est signalé.
Le vrai JS est exécuté dans Node, comme les autres tests du panneau.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, cas } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console, structuredClone,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  p._a = (cle, nom) => ({ reserve: { arrosage_recent_7j: c.utilise }, fenetre_optimale: { weekly_guardrail_mm_max: c.plafond } })[cle]?.[nom];
  p._budgetEstInformatifSeul = () => Boolean(c.informatif);
  return p._semaineDialogueHtml(c.mm);
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre(cas: list[dict]) -> list[str]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return [html.replace(" ", " ") for html in json.loads(sortie.stdout)]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class DialogueSemaineTests(unittest.TestCase):
    def test_sous_la_limite_la_fenetre_montre_le_nouveau_total_sans_alerte(self) -> None:
        (html,) = _rendre([{"utilise": 12, "plafond": 26, "mm": 3}])
        self.assertIn("Eau de la semaine : 12 mm → <b>15 mm</b> sur 26 mm (limite)", html)
        self.assertIn("width:57.7%", html)
        self.assertIn("var(--gz-eau)", html)
        self.assertNotIn("dépasse", html)
        self.assertNotIn("note alerte", html)

    def test_au_dela_de_la_limite_elle_le_dit_et_vire_au_rouge(self) -> None:
        (html,) = _rendre([{"utilise": 24, "plafond": 26, "mm": 5}])
        self.assertIn("<b>29 mm</b> sur 26 mm", html)
        self.assertIn("Cela dépasse la limite de la semaine (26 mm)", html)
        self.assertIn("var(--gz-rouge)", html)
        self.assertIn("width:100.0%", html)

    def test_pile_a_la_limite_ne_depasse_pas(self) -> None:
        (html,) = _rendre([{"utilise": 21, "plafond": 26, "mm": 5}])
        self.assertNotIn("dépasse", html)

    def test_hors_phase_normal_le_plafond_n_est_qu_un_repere(self) -> None:
        (html,) = _rendre([{"utilise": 24, "plafond": 26, "mm": 5, "informatif": True}])
        self.assertIn("(repère)", html)
        self.assertNotIn("dépasse", html)
        self.assertNotIn("var(--gz-rouge)", html)

    def test_sans_chiffres_ou_sans_quantite_rien_ne_s_affiche(self) -> None:
        sans_cumul, sans_plafond, plafond_nul, sans_quantite = _rendre([
            {"plafond": 26, "mm": 3},
            {"utilise": 12, "mm": 3},
            {"utilise": 12, "plafond": 0, "mm": 3},
            {"utilise": 12, "plafond": 26},
        ])
        for html in (sans_cumul, sans_plafond, plafond_nul, sans_quantite):
            self.assertEqual(html, "")

    def test_la_fenetre_appelle_ce_bloc_et_surligne_la_quantite_choisie(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn("${this._semaineDialogueHtml(d.mm)}", source)
        self.assertIn('data-mm="${v}" aria-pressed="${v === d.mm}"', source)


if __name__ == "__main__":
    unittest.main()
