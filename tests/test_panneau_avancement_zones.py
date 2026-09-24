"""Pendant un arrosage, chaque zone doit être comparée à SA PROPRE dose planifiée.

Relevé en conditions réelles le 24/09/2026 (capture HA : zone 1 « 1,3 / 1,1 mm · fini », zone 2 en
cours, zone 3 à venir) : `target_mm` de la session est `plan.planned_surface_mm` côté moteur — une
MOYENNE entre zones, tirée vers le bas par toute zone en réduction d'ombre (zone 3, 40 % ici) —
jamais la cible d'une zone précise (`watering_plan.py`, propriété `WateringPlan.planned_surface_mm`).
Le panneau comparait pourtant chaque zone à cette moyenne unique, faisant paraître zone 1 en
dépassement de 18 % alors qu'elle atteignait tout juste SA propre cible planifiée (`ZonePlan.mm`,
1,3 mm, débit réel 14 mm/h). Ce test charge la page dans Node et exécute `_avancementZonesHtml`
avec les attributs que publient les capteurs, `zone_target_mm` compris. Sans Node, il est sauté.
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
  const zonesEtats = {};
  for (const z of c.zones) zonesEtats[z.switch] = { state: z.active ? "on" : "off", attributes: {} };
  const debitEntites = {};
  const debitEtats = {};
  for (const z of c.zones) {
    const id = `sensor.debit_zone_${z.numero}`;
    debitEntites[`debit_zone_${z.numero}`] = id;
    debitEtats[id] = { state: String(z.debit), attributes: {} };
  }
  p._hass = {
    states: {
      "sensor.arrosage_en_cours": {
        state: c.active ? "1" : "0",
        attributes: {
          active: c.active,
          target_mm: c.targetMm,
          zone_target_mm: c.zoneTargetMm,
          zone_mm_applied: c.zoneMmApplied,
          passage_count: c.passageCount ?? 1,
          current_passage: c.currentPassage ?? 1,
        },
      },
      ...zonesEtats,
      ...debitEtats,
    },
  };
  p._donnees = {
    entites: { arrosage_en_cours: "sensor.arrosage_en_cours", ...debitEntites },
    zones: c.zones.map((z) => ({ switch: z.switch, numero: z.numero, nom: z.nom })),
  };
  return { html: p._avancementZonesHtml() };
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


def _texte_normalise(html: str) -> str:
    """Balises retirées, `&nbsp;` littéral ET vraie espace insécable fondus en espace normale."""
    sans_balises = re.sub(r"<[^>]+>", " ", html)
    sans_nbsp = sans_balises.replace("&nbsp;", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", sans_nbsp).strip()


_ZONES_REELLES = [
    {"switch": "switch.zone_1", "numero": 1, "nom": "Zone 1", "debit": 14, "active": False},
    {"switch": "switch.zone_2", "numero": 2, "nom": "Zone 2", "debit": 14, "active": True},
    {"switch": "switch.zone_3", "numero": 3, "nom": "Zone 3", "debit": 17, "active": False},
]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class AvancementZonesTests(unittest.TestCase):
    def test_une_zone_sans_reduction_est_comparee_a_sa_propre_cible_pas_a_la_moyenne(self) -> None:
        [sortie] = _rendre([{
            "zones": _ZONES_REELLES,
            "active": True,
            "targetMm": 1.1,
            "zoneTargetMm": {"switch.zone_1": 1.3, "switch.zone_2": 1.3, "switch.zone_3": 0.8},
            "zoneMmApplied": {"switch.zone_1": 1.3, "switch.zone_2": 0.5},
        }])
        texte = _texte_normalise(sortie["html"])
        self.assertIn("Zone 1", texte)
        self.assertIn("1,3 / 1,3 mm", texte)
        # La moyenne de session (1,1 mm) ne doit apparaître nulle part comme cible de zone 1.
        self.assertNotIn("1,3 / 1,1 mm", texte)

    def test_une_zone_a_fini_quand_elle_atteint_sa_propre_cible_pas_la_moyenne(self) -> None:
        # Avant le correctif : 1,3 mm versés >= 1,1 (moyenne) - 0,05 → « fini » aurait été vrai
        # pour la mauvaise raison mais avec la même conclusion ici. Le vrai test est zone 3 :
        # rien versé, cible réduite 0,8 mm → ne doit jamais être « fini ».
        [sortie] = _rendre([{
            "zones": _ZONES_REELLES,
            "active": True,
            "targetMm": 1.1,
            "zoneTargetMm": {"switch.zone_1": 1.3, "switch.zone_2": 1.3, "switch.zone_3": 0.8},
            "zoneMmApplied": {"switch.zone_1": 1.3, "switch.zone_2": 0.5},
        }])
        texte = _texte_normalise(sortie["html"])
        self.assertIn("Zone 1 1,3 / 1,3 mm fini", texte)
        self.assertIn("Zone 3 0 / 0,8 mm à venir", texte)

    def test_zone_sans_cible_propre_publiee_replie_sur_la_moyenne_de_session(self) -> None:
        # Sessions plus anciennes / sans `plan` : `zone_target_mm` peut être vide. Le panneau doit
        # continuer à fonctionner en repliant sur la moyenne de session, comme avant ce correctif.
        [sortie] = _rendre([{
            "zones": _ZONES_REELLES,
            "active": True,
            "targetMm": 1.1,
            "zoneTargetMm": {},
            "zoneMmApplied": {"switch.zone_1": 1.3, "switch.zone_2": 0.5},
        }])
        texte = _texte_normalise(sortie["html"])
        self.assertIn("Zone 1 1,3 / 1,1 mm fini", texte)


if __name__ == "__main__":
    unittest.main()
