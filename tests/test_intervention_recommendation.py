from __future__ import annotations

from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _ensure_homeassistant_dt_module() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
    homeassistant = sys.modules.get("homeassistant")
    if homeassistant is None:
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant"] = homeassistant
    util = sys.modules.get("homeassistant.util")
    if util is None:
        util = types.ModuleType("homeassistant.util")
        util.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant.util"] = util
    dt_module = types.ModuleType("homeassistant.util.dt")
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=timezone.utc)  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_ensure_homeassistant_dt_module()

intervention = importlib.import_module(
    "custom_components.gazon_intelligent.intervention_recommendation"
)


class OpportunityEvaluationTests(unittest.TestCase):
    def test_zero_soil_reserve_not_overridden_by_positive_rolling_balance(self) -> None:
        # Régression : une réserve sol réellement 0 mm (sol sec) ne doit PAS être ignorée au
        # profit du bilan hydrique glissant positif (l'ancien `X or Y` traitait 0 comme falsy).
        result = intervention._opportunity_evaluation(
            {"reserve_hydrique_sol_mm": 0.0, "bilan_hydrique_mm": 8.0}
        )
        self.assertEqual(result["score_delta"], 0)
        self.assertNotIn("Contexte hydrique équilibré", result["reasons"])
        self.assertNotIn("Contexte hydrique excédentaire", result["reasons"])

    def test_real_soil_reserve_still_marks_balanced(self) -> None:
        # Garde-fou : une réserve sol renseignée (≥ 5 mm) reste classée « équilibré ».
        result = intervention._opportunity_evaluation(
            {"reserve_hydrique_sol_mm": 8.0, "bilan_hydrique_mm": 8.0}
        )
        self.assertEqual(result["score_delta"], -2)
        self.assertIn("Contexte hydrique équilibré", result["reasons"])

    def test_missing_soil_reserve_falls_back_to_rolling_balance(self) -> None:
        # Quand la réserve sol est absente (None), on retombe bien sur le bilan glissant.
        result = intervention._opportunity_evaluation(
            {"reserve_hydrique_sol_mm": None, "bilan_hydrique_mm": 20.0}
        )
        self.assertEqual(result["score_delta"], -3)
        self.assertIn("Contexte hydrique excédentaire", result["reasons"])


if __name__ == "__main__":
    unittest.main()
