"""Le panneau « L'eau de la semaine » ne doit pas promettre une limite qui n'existe pas.

Relevé en conditions réelles le 23/09/2026 (Sursemis / Germination, 119 % du plafond
hebdomadaire pendant un cycle graines pourtant autorisé) : `guidance._profile_for_sursemis`
ne regarde jamais `weekly_guardrail_mm_max`/`_min` pour sa décision — ce sont de simples valeurs
de contexte qui traversent le payload sans jamais capper la dose. Le panneau affichait pourtant
ce nombre comme une « limite » bloquante (barre rouge, « pour ne pas trop arroser »).

⚠️ Trouvé en revue (PR #63) : la première version de ce correctif ne l'avait vérifié que pour
Semis/Sursemis et traitait tout le reste, y compris Traitement, comme une vraie limite. Vérifié
depuis dans les cinq autres fonctions de profil (`_profile_for_traitement`,
`_profile_for_agro_phases` — Fertilisation/Biostimulant/Agent Mouillant/Scarification —,
`_profile_for_generic`, `_profile_for_blocked` pour l'Hivernage) : aucune ne cappe jamais la
dose sur ce plafond. `_profile_for_normal` est le SEUL profil qui l'applique réellement. Le
garde côté panneau doit donc être un blanchiment de `phase === "Normal"`, pas une liste noire de
Semis/Sursemis. Ce test charge la page dans Node et exécute `_budgetHtml`/`_retenuParLeBudget`
avec les attributs que publient les capteurs. Sans Node, il est sauté.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

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
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  p._hass = {
    states: {
      "sensor.reserve": { state: "0", attributes: { arrosage_recent_7j: c.utilise, arrosage_applique_7j: c.recu ?? c.utilise } },
      "sensor.fenetre": { state: "maintenant", attributes: { weekly_guardrail_mm_max: c.plafond, weekly_guardrail_mm_min: c.plancher ?? null } },
      "sensor.phase": { state: c.phase || "Normal", attributes: {} },
      "sensor.mode": { state: c.mode || c.phase || "Normal", attributes: {} },
      "sensor.prochain": { state: "Maintenant", attributes: { block_reason: c.blockReason || "" } },
    },
  };
  p._donnees = { entites: { reserve: "sensor.reserve", fenetre_optimale: "sensor.fenetre", phase: "sensor.phase", mode: "sensor.mode", prochain_arrosage: "sensor.prochain" } };
  return { html: p._budgetHtml(), retenu: p._retenuParLeBudget() };
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre(cas: list[dict]) -> list[dict]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


def _sans_balises(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


@unittest.skipUnless(NODE, "Node n'est pas installé")
class BudgetSemaineTests(unittest.TestCase):
    def test_le_plafond_normal_reste_une_limite_avec_barre_rouge(self) -> None:
        [sortie] = _rendre([{"phase": "Normal", "utilise": 29.9, "plafond": 25.1, "plancher": 12.0}])
        self.assertIn("limite", sortie["html"])
        self.assertIn("var(--gz-rouge)", sortie["html"])
        self.assertIn("Pour ne pas trop arroser", sortie["html"])
        self.assertTrue(sortie["retenu"])

    def test_le_meme_depassement_en_sursemis_n_est_plus_presente_comme_une_limite(self) -> None:
        [sortie] = _rendre([{"phase": "Sursemis", "utilise": 29.9, "plafond": 25.1, "plancher": 12.0}])
        html = sortie["html"]
        self.assertNotIn("var(--gz-rouge)", html)
        self.assertNotIn("Pour ne pas trop arroser", html)
        self.assertIn("informatif", _sans_balises(html))
        self.assertIn("repère", html)
        self.assertFalse(sortie["retenu"], "le budget Semis/Sursemis ne doit jamais se dire retenu par ce plafond")

    def test_le_semis_a_le_meme_traitement_que_le_sursemis(self) -> None:
        [sortie] = _rendre([{"phase": "Semis", "utilise": 30.0, "plafond": 20.0}])
        self.assertNotIn("var(--gz-rouge)", sortie["html"])
        self.assertFalse(sortie["retenu"])

    def test_le_plancher_ne_s_affiche_plus_en_sursemis(self) -> None:
        # Le plancher n'est pas plus appliqué que le plafond pendant le Semis/Sursemis (même
        # fonction, même absence de lien avec la décision) : son trait et sa note induiraient
        # la même fausse promesse de retenue.
        [normal] = _rendre([{"phase": "Normal", "utilise": 10.0, "plafond": 25.0, "plancher": 12.0}])
        [sursemis] = _rendre([{"phase": "Sursemis", "utilise": 10.0, "plafond": 25.0, "plancher": 12.0}])
        self.assertIn("budget-plancher", normal["html"])
        self.assertNotIn("budget-plancher", sursemis["html"])

    def test_un_motif_de_garde_fou_explicite_reste_prioritaire(self) -> None:
        # Si le moteur cite lui-même le garde-fou hebdomadaire dans son motif de blocage, on le
        # croit sur parole même en Sursemis plutôt que de l'ignorer par principe.
        [sortie] = _rendre([{"phase": "Sursemis", "utilise": 10.0, "plafond": 25.0, "blockReason": "garde_fou_hebdomadaire"}])
        self.assertTrue(sortie["retenu"])

    def test_traitement_fertilisation_et_hivernage_sont_aussi_informatifs(self) -> None:
        # `_profile_for_traitement` et `_profile_for_agro_phases` ne cappent pas plus la dose sur
        # ce plafond que `_profile_for_sursemis` — seul `_profile_for_normal` le fait. Un plafond
        # affiché comme bloquant pendant un Traitement promettrait donc la même fausse sécurité.
        for phase in ("Traitement", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification", "Hivernage"):
            with self.subTest(phase=phase):
                [sortie] = _rendre([{"phase": phase, "utilise": 29.9, "plafond": 17.4}])
                self.assertNotIn("var(--gz-rouge)", sortie["html"])
                self.assertFalse(sortie["retenu"])

    def test_mode_declare_traitement_avec_phase_normale_reste_une_vraie_limite(self) -> None:
        # ⚠️ Le réglage `mode` (déclaré par l'utilisateur) peut afficher une valeur différente de
        # la phase dominante que le moteur utilise réellement pour choisir son profil de décision
        # (`guidance.py`, dispatcher sur `ctx.phase_dominante`) — ex. un mode resté sur l'ancien
        # choix pendant que la phase a déjà basculé. Si la carte se fiait à `mode` plutôt qu'à
        # `phase`, un Traitement déclaré masquerait à tort un plafond qui, lui, s'applique
        # réellement dès que la phase dominante est repassée à Normal.
        [sortie] = _rendre([{"mode": "Traitement", "phase": "Normal", "utilise": 29.9, "plafond": 17.4}])
        html = sortie["html"]
        self.assertIn(">limite", html)
        self.assertIn("var(--gz-rouge)", html)
        self.assertNotIn(">repère", html)
        self.assertTrue(sortie["retenu"])

    def test_le_motif_explicite_ne_contredit_plus_le_texte_informatif(self) -> None:
        # ⚠️ Relevé en revue (PR #61) : `retenu=True` (motif nommé) affichait quand même le texte
        # « cumul informatif, pas une limite qui les retiendrait » ET « Semaine couverte » juste
        # en dessous — deux messages contradictoires sur la même carte. Un motif nommé doit faire
        # basculer la présentation en vraie limite, pas rester « informatif ».
        [sortie] = _rendre([{"phase": "Sursemis", "utilise": 10.0, "plafond": 25.0, "blockReason": "garde_fou_hebdomadaire"}])
        html = _sans_balises(sortie["html"])
        self.assertIn("limite", html)
        self.assertNotIn("informatif", html)
        self.assertIn("Semaine couverte", html)


if __name__ == "__main__":
    unittest.main()
