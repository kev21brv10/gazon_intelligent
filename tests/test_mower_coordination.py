from __future__ import annotations

import unittest
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

from custom_components.gazon_intelligent.mower_adapter import build_mower_context
from custom_components.gazon_intelligent.mower_coordination import build_mower_coordination_context


class MowerCoordinationTests(unittest.TestCase):
    def test_charging_is_considered_safe_for_watering(self) -> None:
        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "charging",
                "tondeuse_statut": "en_charge",
                "tondeuse_en_charge": True,
            },
            enabled=True,
        )

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertEqual(payload["mower_operation_state"], "charging")
        self.assertEqual(payload["mower_presence_state"], "dockee")
        self.assertTrue(payload["mower_is_safe_for_watering"])

    def test_idle_counts_as_stowed_when_mower_is_resting(self) -> None:
        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "idle",
                "tondeuse_statut": "au_repos",
            },
            enabled=True,
        )

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertEqual(payload["mower_presence_state"], "dockee")
        self.assertTrue(payload["mower_is_safe_for_watering"])
        self.assertEqual(payload["mower_reason_code"], "none")

    def test_edgecut_counts_as_mowing_outside(self) -> None:
        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "edgecut",
                "tondeuse_statut": "tonte_en_cours",
            },
            enabled=True,
        )

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertEqual(payload["mower_operation_state"], "tonte")
        self.assertEqual(payload["mower_operation_label"], "Coupe des bordures")
        self.assertEqual(payload["mower_presence_state"], "dehors")
        self.assertFalse(payload["mower_is_safe_for_watering"])
        self.assertEqual(payload["mower_reason_code"], "mower_mowing")
        self.assertEqual(payload["mower_reason_label"], "Tondeuse en cours de tonte.")

    def test_edgecut_keeps_specific_status_label(self) -> None:
        payload = build_mower_context(
            entity_id="lawn_mower.robot",
            entity_name="Robot",
            raw_state="edgecut",
            available=True,
        )

        self.assertEqual(payload["tondeuse_statut"], "tonte_en_cours")
        self.assertEqual(payload["tondeuse_statut_libelle"], "Coupe des bordures")

    def test_disabled_coordination_neutralizes_constraints(self) -> None:
        payload = build_mower_coordination_context({}, enabled=False)

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertTrue(payload["mower_is_safe_for_watering"])
        self.assertEqual(payload["mower_reason_code"], "disabled")


if __name__ == "__main__":
    unittest.main()
