from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest


MODULE_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "gazon_intelligent"
)


def _ensure_package(name: str) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(MODULE_DIR if name.endswith("gazon_intelligent") else MODULE_DIR.parent)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _load_module(fullname: str, filename: str):
    spec = importlib.util.spec_from_file_location(fullname, MODULE_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


_ensure_package("custom_components")
_ensure_package("custom_components.gazon_intelligent")
watering_plan = _load_module(
    "custom_components.gazon_intelligent.watering_plan",
    "watering_plan.py",
)


class WateringPlanTests(unittest.TestCase):
    def test_build_watering_plan_returns_none_when_objective_is_not_positive(self) -> None:
        self.assertIsNone(watering_plan.build_watering_plan(0, [("switch.zone_1", 20.0)]))
        self.assertIsNone(watering_plan.build_watering_plan(-1, [("switch.zone_1", 20.0)]))

    def test_build_watering_plan_distinguishes_target_from_effective_zone_mm(self) -> None:
        plan = watering_plan.build_watering_plan(1.0, [("switch.zone_1", 22.0)])

        assert plan is not None
        self.assertEqual(plan.objective_mm, 1.0)
        self.assertLess(plan.zones[0].mm, plan.objective_mm)
        self.assertEqual(plan.as_dict()["objective_mm"], 1.0)
        self.assertEqual(plan.as_dict()["zones"][0]["mm"], 0.9)

    def test_normalize_existing_plan_reconstructs_missing_objective_from_max_zone_mm(self) -> None:
        plan = watering_plan.normalize_existing_plan(
            {
                "zones": [
                    {"entity_id": "switch.zone_1", "duration_seconds": 120, "rate_mm_h": 20.0, "mm": 0.7},
                    {"zone": "switch.zone_2", "duration_s": 180, "rate_mm_h": 20.0, "mm": 1.2},
                ],
                "passages": 2,
            }
        )

        assert plan is not None
        self.assertEqual(plan.objective_mm, 1.2)
        self.assertEqual(plan.passage_count, 2)
        self.assertEqual(plan.source, watering_plan.PLAN_SOURCE_NORMALIZED)

    def test_normalize_existing_plan_accepts_incomplete_zone_when_mm_is_present(self) -> None:
        plan = watering_plan.normalize_existing_plan(
            {
                "objective_mm": 1.1,
                "zones": [
                    {"entity_id": "switch.zone_1", "duration_min": 6.0, "rate_mm_h": 0, "mm": 1.1},
                ],
            }
        )

        assert plan is not None
        self.assertEqual(plan.zones[0].rate_mm_h, 0.0)
        self.assertEqual(plan.zones[0].mm, 1.1)

    def test_serialized_plan_keeps_canonical_and_compatibility_aliases(self) -> None:
        plan = watering_plan.build_watering_plan(1.5, [("switch.zone_1", 60.0)])

        assert plan is not None
        serialized = plan.as_dict()
        zone = serialized["zones"][0]
        self.assertEqual(serialized["objective_mm"], serialized["objectif_mm"])
        self.assertEqual(zone["duration_seconds"], zone["duration_s"])

    def test_fractionated_plan_keeps_total_zone_duration_and_splits_runtime_segments(self) -> None:
        plan = watering_plan.build_watering_plan(
            5.0,
            [("switch.zone_1", 10.0), ("switch.zone_2", 20.0)],
            passages=4,
            pause_minutes=20,
        )

        assert plan is not None
        self.assertEqual(plan.total_duration_min, 45.0)
        self.assertEqual(plan.zones[0].duration_s, 1800)
        self.assertEqual(plan.zones[1].duration_s, 900)

        zone1_passage = plan.zone_for_passage(0, 1)
        zone2_passage = plan.zone_for_passage(1, 1)
        self.assertEqual(zone1_passage.duration_s, 450)
        self.assertEqual(zone2_passage.duration_s, 225)
        self.assertEqual(zone1_passage.mm, 1.3)
        self.assertEqual(zone2_passage.mm, 1.3)

        self.assertEqual(plan.total_duration_s, (45 * 60) + (3 * 20 * 60))

    def test_semis_plan_preserves_strategy_and_cycle_metadata(self) -> None:
        plan = watering_plan.build_watering_plan(
            1.5,
            [("switch.zone_1", 14.0)],
            watering_strategy="semis_frequent",
            objective_scope="surface_cycle",
            watering_stage="germination",
            surface_cycle_mm=1.5,
            daily_cycles_target=3,
            cycle_spacing_minutes=120,
            surface_moisture_target="surface_moist",
            surface_dryness_risk="moderate",
            runoff_risk="low",
            seeding_transition_ready=False,
            seeding_block_reason="too_dry",
        )

        assert plan is not None
        serialized = plan.as_dict()
        runtime = plan.as_runtime_dict()
        self.assertEqual(serialized["watering_strategy"], "semis_frequent")
        self.assertEqual(serialized["objective_scope"], "surface_cycle")
        self.assertEqual(serialized["watering_stage"], "germination")
        self.assertEqual(serialized["surface_cycle_mm"], 1.5)
        self.assertEqual(serialized["daily_cycles_target"], 3)
        self.assertEqual(serialized["cycle_spacing_minutes"], 120)
        self.assertEqual(serialized["surface_moisture_target"], "surface_moist")
        self.assertEqual(serialized["surface_dryness_risk"], "moderate")
        self.assertEqual(serialized["runoff_risk"], "low")
        self.assertFalse(serialized["seeding_transition_ready"])
        self.assertEqual(serialized["seeding_block_reason"], "too_dry")
        self.assertEqual(runtime["daily_cycles_target"], 3)
        self.assertEqual(runtime["cycle_spacing_minutes"], 120)


if __name__ == "__main__":
    unittest.main()
