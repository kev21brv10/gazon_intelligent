"""La page « Gazon » dessine un arrosage exactement comme le moteur l'exécute.

La page porte une copie JavaScript de `build_watering_plan` et de `zone_for_passage` : elle sert à
montrer la durée de chaque zone, les passages et la pause, avant de lancer un arrosage. Ce test
exécute cette copie avec Node et compare chaque étape, à la seconde, au plan du moteur. Sans Node,
il est sauté (le moteur, lui, reste testé partout ailleurs).
"""

from __future__ import annotations

import itertools
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

watering_plan = __import__("custom_components.gazon_intelligent.watering_plan", fromlist=["_"])

DEBUT_BLOC = "// ─── Le plan d'arrosage, construit comme le moteur"
NODE = shutil.which("node")


def _bloc_du_plan() -> str:
    """Le morceau de la page qui construit un plan, de son titre à la section suivante."""
    lignes = PANNEAU.read_text(encoding="utf-8").splitlines()
    debut = next(i for i, ligne in enumerate(lignes) if ligne.startswith(DEBUT_BLOC))
    fin = next(i for i in range(debut + 1, len(lignes)) if lignes[i].startswith("// ───"))
    return "\n".join(lignes[debut:fin])


def _plan_de_la_page(cas: list[dict]) -> list:
    script = _bloc_du_plan() + """
const cas = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(cas.map((c) => {
  const zones = c.zones.map(([id, debit]) => ({ switch: id, debit }));
  const plan = planArrosage(c.mm, zones, c.passages, c.pause_s);
  if (!plan) return null;
  return {
    etapes: plan.etapes.map((e) => [e.genre, e.passage, e.zone ? e.zone.switch : null, e.secondes]),
    eau: plan.eauS,
    pause: plan.pauseS,
    total: plan.totalS,
  };
})));
"""
    sortie = subprocess.run(
        [NODE, "-e", script], input=json.dumps(cas), capture_output=True, text=True, check=True, timeout=60
    )
    return json.loads(sortie.stdout)


def _plan_du_moteur(c: dict):
    """Les étapes dans l'ordre où `_execute_canonical_watering_plan` ouvre les vannes."""
    plan = watering_plan.build_watering_plan(
        c["mm"], c["zones"], passages=c["passages"], pause_minutes=c["pause_s"] // 60
    )
    if plan is None:
        return None
    etapes = []
    for passage in range(1, plan.passage_count + 1):
        for index, zone in enumerate(plan.zones):
            segment = plan.zone_for_passage(index, passage)
            if segment.duration_s > 0:
                etapes.append(["zone", passage, zone.zone, segment.duration_s])
        if passage < plan.passage_count and plan.pause_between_passages_s > 0:
            etapes.append(["pause", passage, None, plan.pause_between_passages_s])
    # Une pause n'existe qu'ENTRE deux passages : avec un seul, la page ne doit pas en parler.
    pause = plan.pause_between_passages_s if plan.passage_count > 1 else 0
    return {"etapes": etapes, "eau": plan.watering_duration_s, "pause": pause, "total": plan.total_duration_s}


def _cas() -> list[dict]:
    doses = [0, -2, 0.1, 0.25, 0.5, 1, 2, 2.5, 4.9, 5, 5.2, 5.25, 5.3, 6.8, 7.5, 10, 10.01, 12, 15, 30, 100, 1000]
    # Débits réels observés (14 / 14 / 17), des débits ronds, et des cas limites (nul, négatif, minuscule).
    installations = [
        [("z1", 14.0), ("z2", 14.0), ("z3", 17.0)],
        [("z1", 12.0), ("z2", 12.0)],
        [("z1", 24.0)],
        [("z1", 0.0), ("z2", -3.0), ("z3", 7.0)],
        [("z1", 0.5), ("z2", 60.0), ("z3", 200.0)],
        [("z1", 33.0), ("z2", 3.0), ("z3", 1.0), ("z4", 19.0), ("z5", 41.0)],
        [("z1", 0.0)],
    ]
    decoupages = [(1, 0), (2, 1500), (2, 0), (3, 1500), (0, 1500), (4, 600)]
    return [
        {"mm": mm, "zones": zones, "passages": passages, "pause_s": pause_s}
        for mm, zones, (passages, pause_s) in itertools.product(doses, installations, decoupages)
    ]


@unittest.skipIf(NODE is None, "Node.js absent : la copie JavaScript ne peut pas être exécutée")
class LaPageDessineLePlanDuMoteurTests(unittest.TestCase):
    def test_chaque_etape_dure_ce_que_le_moteur_executera(self) -> None:
        cas = _cas()
        page = _plan_de_la_page(cas)
        self.assertEqual(len(page), len(cas))
        for c, obtenu in zip(cas, page):
            with self.subTest(mm=c["mm"], zones=c["zones"], passages=c["passages"], pause_s=c["pause_s"]):
                self.assertEqual(obtenu, _plan_du_moteur(c))

    def test_les_moities_exactes_s_arrondissent_comme_python(self) -> None:
        # À 24 mm/h, 0,5 / 0,9 / 2,5 mm tombent PILE entre deux demi-minutes (2,5 / 4,5 / 12,5
        # crans). Python va vers le cran pair : 60 / 120 / 360 s. Un arrondi « vers le haut »,
        # celui de Math.round, donnerait 90 / 150 / 390 s.
        cas = [{"mm": mm, "zones": [("z", 24.0)], "passages": 1, "pause_s": 0} for mm in (0.5, 0.9, 2.5)]
        page = _plan_de_la_page(cas)
        self.assertEqual(page, [_plan_du_moteur(c) for c in cas])
        self.assertEqual([p["etapes"][0][3] for p in page], [60, 120, 360])

    def test_le_bloc_copie_existe_et_ne_depend_de_rien_d_autre(self) -> None:
        bloc = _bloc_du_plan()
        self.assertIn("function planArrosage(", bloc)
        self.assertIn("function planDepuisZones(", bloc)
        self.assertIn("function arrondiPython(", bloc)


if __name__ == "__main__":
    unittest.main()
