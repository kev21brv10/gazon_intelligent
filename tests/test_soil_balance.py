from __future__ import annotations

import unittest
from datetime import date
from importlib import util
from pathlib import Path
import sys


def _load_soil_balance_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "gazon_intelligent"
        / "soil_balance.py"
    )
    spec = util.spec_from_file_location("gazon_intelligent_soil_balance", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {module_path}")
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


soil_balance = _load_soil_balance_module()


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

