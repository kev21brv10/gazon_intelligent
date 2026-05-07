from __future__ import annotations

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
    sys.modules["homeassistant.util.dt"] = dt_module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_ensure_homeassistant_dt_module()

const = importlib.import_module("custom_components.gazon_intelligent.const")
phases = importlib.import_module("custom_components.gazon_intelligent.phases")


class ConstReferentialTests(unittest.TestCase):
    def test_modes_gazon_derives_from_phase_referential(self) -> None:
        self.assertEqual(const.MODES_GAZON, tuple(phases.PHASE_DURATIONS_DAYS.keys()))

    def test_public_referentials_are_immutable_sequences(self) -> None:
        self.assertIsInstance(const.TYPES_SOL, tuple)
        self.assertIsInstance(const.INTERVENTIONS_ACTIONS, tuple)
        self.assertIsInstance(const.APPLICATION_INTERVENTIONS, tuple)
        self.assertIsInstance(const.APPLICATION_IRRIGATION_MODES, tuple)
        self.assertIsInstance(const.PRODUCT_USAGE_MODES, tuple)
        self.assertIsInstance(const.MODES_GAZON, tuple)

    def test_irrigation_mode_aliases_are_explicit(self) -> None:
        self.assertEqual(
            const.APPLICATION_IRRIGATION_MODE_ALIASES["manual"],
            const.APPLICATION_IRRIGATION_MODE_MANUAL,
        )
        self.assertEqual(
            const.APPLICATION_IRRIGATION_MODE_ALIASES["manuel"],
            const.APPLICATION_IRRIGATION_MODE_MANUAL,
        )
        self.assertEqual(
            const.APPLICATION_IRRIGATION_MODE_ALIASES["suggestion"],
            const.APPLICATION_IRRIGATION_MODE_SUGGESTION,
        )


if __name__ == "__main__":
    unittest.main()
