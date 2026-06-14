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

    def test_soil_balance_clamps_aberrant_rain(self) -> None:
        state = soil_balance.update_soil_balance(
            {},
            pluie_mm=120.0,
            arrosage_mm=0.0,
            etp_mm=2.0,
        )
        # La pluie aberrante (> 100mm) doit être clampée à 30mm
        self.assertTrue(state["ledger"][-1].get("pluie_suspect"))
        # La réserve doit être <= max raisonnable (pas de recharge à 120mm)
        self.assertLessEqual(state["reserve_mm"], state["reserve_max_mm"])
        # Vérifier que pluie utilisée est 30mm (clampée)
        self.assertEqual(state["ledger"][-1]["pluie_mm"], 30.0)

    def test_set_reserve_mm_anchors_and_survives_same_day_recompute(self) -> None:
        # Réserve « polluée » au départ.
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.2,
            type_sol="limoneux",
        )
        # Recalage manuel à 8 mm → ancre posée.
        state = soil_balance.set_reserve_mm(state, 8.0, today=date(2026, 6, 14))
        self.assertEqual(state["reserve_mm"], 8.0)
        self.assertTrue(state["ledger"][-1].get("manual_anchor"))

        # Cycle suivant le MÊME jour : l'ancre tient, pas de recalcul depuis l'historique.
        recomputed = soil_balance.update_soil_balance(
            state,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.5,
            type_sol="limoneux",
        )
        self.assertEqual(recomputed["reserve_mm"], 8.0)

    def test_manual_anchor_releases_next_day(self) -> None:
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.2,
            type_sol="limoneux",
        )
        state = soil_balance.set_reserve_mm(state, 8.0, today=date(2026, 6, 14))
        # Lendemain : l'évolution normale reprend depuis 8 mm (− ETc).
        nextday = soil_balance.update_soil_balance(
            state,
            today=date(2026, 6, 15),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=5.0,
            type_sol="limoneux",
        )
        self.assertEqual(nextday["previous_reserve_mm"], 8.0)
        self.assertEqual(nextday["reserve_mm"], 3.0)
        self.assertFalse(nextday["ledger"][-1].get("manual_anchor"))

    def test_set_reserve_mm_clamps_to_bounds(self) -> None:
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=0.0,
            type_sol="limoneux",
        )
        high = soil_balance.set_reserve_mm(state, 999.0, today=date(2026, 6, 14))
        self.assertLessEqual(high["reserve_mm"], high["reserve_max_mm"])
        low = soil_balance.set_reserve_mm(state, -5.0, today=date(2026, 6, 14))
        self.assertGreaterEqual(low["reserve_mm"], 0.0)

    def test_manual_anchor_survives_normalize_round_trip(self) -> None:
        # Simule une sauvegarde→restauration (passage par normalize) : l'ancre doit
        # survivre, sinon le recalage serait perdu au redémarrage de Home Assistant.
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.2,
            type_sol="limoneux",
        )
        state = soil_balance.set_reserve_mm(state, 8.0, today=date(2026, 6, 14))
        restored = soil_balance.normalize_soil_balance_state(state)
        self.assertTrue(restored["ledger"][-1].get("manual_anchor"))
        # Et l'ancre reste honorée après restauration (même jour).
        recomputed = soil_balance.update_soil_balance(
            restored,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=9.0,
            type_sol="limoneux",
        )
        self.assertEqual(recomputed["reserve_mm"], 8.0)
