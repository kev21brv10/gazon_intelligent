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

soil_balance = importlib.import_module("custom_components.gazon_intelligent.soil_balance")


class SoilBalanceTests(unittest.TestCase):
    def test_update_soil_balance_initializes_from_soil_type(self) -> None:
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 3, 18),
            pluie_mm=1.2,
            arrosage_mm=3.6,
            etp_mm=2.0,
            type_sol="limoneux",
        )

        self.assertEqual(state["date"], "2026-03-18")
        self.assertEqual(state["previous_reserve_mm"], 12.0)
        self.assertEqual(state["reserve_mm"], 14.8)
        self.assertEqual(state["delta_mm"], 2.8)
        self.assertEqual(len(state["ledger"]), 1)
        self.assertEqual(state["ledger"][0]["reserve_mm"], 14.8)

    def test_update_soil_balance_replaces_same_day_entry(self) -> None:
        initial = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 3, 18),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=2.0,
            type_sol="limoneux",
        )
        updated = soil_balance.update_soil_balance(
            previous_state=initial,
            today=date(2026, 3, 18),
            pluie_mm=2.0,
            arrosage_mm=1.0,
            etp_mm=1.0,
            type_sol="limoneux",
        )

        self.assertEqual(len(updated["ledger"]), 1)
        self.assertEqual(updated["reserve_mm"], 14.0)
        self.assertEqual(updated["previous_reserve_mm"], 12.0)
        self.assertEqual(updated["ledger"][0]["pluie_mm"], 2.0)
        self.assertEqual(updated["ledger"][0]["arrosage_mm"], 1.0)
        self.assertEqual(updated["ledger"][0]["etp_mm"], 1.0)

    def test_normalize_soil_balance_state_keeps_legacy_ledger(self) -> None:
        state = soil_balance.normalize_soil_balance_state(
            {
                "date": "2026-03-18",
                "reserve_mm": "13.2",
                "ledger": [
                    {
                        "date": "2026-03-17",
                        "reserve_mm": "12.0",
                        "previous_reserve_mm": "11.0",
                        "pluie_mm": "1.0",
                        "arrosage_mm": "2.0",
                        "etp_mm": "1.5",
                        "delta_mm": "1.5",
                        "type_sol": "limoneux",
                    }
                ],
            }
        )

        self.assertEqual(state["reserve_mm"], 13.2)
        self.assertEqual(state["ledger"][0]["reserve_mm"], 12.0)
        self.assertEqual(state["ledger"][0]["delta_mm"], 1.5)
