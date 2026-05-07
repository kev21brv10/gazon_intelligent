from __future__ import annotations

import unittest
from datetime import date
import importlib
from pathlib import Path
import sys
import types


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


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)

seasonal_profile = importlib.import_module("custom_components.gazon_intelligent.seasonal_profile")
get_seasonal_profile = seasonal_profile.get_seasonal_profile


class SeasonalProfileTests(unittest.TestCase):
    def test_profiles_expose_expected_month_labels(self) -> None:
        april = get_seasonal_profile(date(2026, 4, 15))
        september = get_seasonal_profile(date(2026, 9, 15))

        self.assertEqual(april["season"], "shoulder")
        self.assertEqual(april["season_phase"], "reveil_printanier")
        self.assertEqual(april["month_profile"], "relance_vegetative")
        self.assertEqual(september["season_phase"], "reprise_automnale")
        self.assertEqual(september["month_profile"], "reprise_racinaire")

    def test_profiles_vary_weekly_budget_between_winter_and_summer(self) -> None:
        january = get_seasonal_profile(date(2026, 1, 15))
        july = get_seasonal_profile(date(2026, 7, 15))

        self.assertLess(january["weekly_budget_min_mm"], july["weekly_budget_min_mm"])
        self.assertLess(january["weekly_budget_max_mm"], july["weekly_budget_max_mm"])


if __name__ == "__main__":
    unittest.main()
