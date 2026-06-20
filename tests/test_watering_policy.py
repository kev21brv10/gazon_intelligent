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

policy = __import__(
    "custom_components.gazon_intelligent.watering_policy",
    fromlist=["resolve_watering_policy"],
)


class WateringPolicyTests(unittest.TestCase):
    def test_registry_contains_expected_modes(self) -> None:
        self.assertEqual(
            set(policy.WATERING_POLICIES),
            {
                "normal",
                "sursemis",
                "fertilisation",
                "biostimulant",
                "agent_mouillant",
                "scarification",
                "traitement",
                "hivernage",
            },
        )

    def test_biostimulant_policy_exposes_expected_range(self) -> None:
        resolved = policy.resolve_watering_policy(phase_dominante="Biostimulant")

        self.assertEqual(resolved.selected_mode, "biostimulant")
        self.assertFalse(resolved.blocking.is_blocked)
        self.assertEqual(resolved.target_range.min_mm, 3.0)
        self.assertEqual(resolved.target_range.max_mm, 7.0)
        self.assertEqual(resolved.target_range.optimal_mm, 5.0)

    def test_sursemis_stage_programs_expose_expected_rain_thresholds(self) -> None:
        germination_stage, germination_program = policy.resolve_semis_stage_program("Germination")
        levee_stage, levee_program = policy.resolve_semis_stage_program("Reprise", transition_ready=False)
        enracinement_stage, enracinement_program = policy.resolve_semis_stage_program("Enracinement")
        transition_stage, transition_program = policy.resolve_semis_stage_program("Reprise", transition_ready=True)

        self.assertEqual(germination_stage, "germination")
        self.assertEqual(germination_program.surface_cycle_mm_min, 1.2)
        self.assertEqual(germination_program.surface_cycle_mm_max, 1.8)
        self.assertEqual(germination_program.surface_cycle_mm_optimal, 1.5)

        self.assertEqual(levee_stage, "levee")
        self.assertEqual(levee_program.surface_cycle_mm_min, 2.0)
        self.assertEqual(levee_program.surface_cycle_mm_max, 3.0)
        self.assertEqual(levee_program.surface_cycle_mm_optimal, 2.5)

        self.assertEqual(enracinement_stage, "enracinement")
        self.assertEqual(enracinement_program.surface_cycle_mm_min, 2.5)
        self.assertEqual(enracinement_program.surface_cycle_mm_max, 4.0)
        self.assertEqual(enracinement_program.surface_cycle_mm_optimal, 3.0)

        self.assertEqual(transition_stage, "enracinement")
        self.assertEqual(transition_program.surface_cycle_mm_min, 2.5)
        self.assertEqual(transition_program.surface_cycle_mm_max, 4.0)
        self.assertEqual(transition_program.surface_cycle_mm_optimal, 3.0)


    def test_fertilisation_weather_guard_blocks_on_heavy_rain(self) -> None:
        resolved = policy.resolve_watering_policy(
            phase_dominante="Fertilisation",
            weather={"heavy_rain_expected": True},
        )

        self.assertEqual(resolved.selected_mode, "fertilisation")
        self.assertTrue(resolved.blocking.is_blocked)
        self.assertEqual(resolved.blocking.reason, "heavy_rain_expected")

    def test_biostimulant_shares_fertilisation_weather_guard(self) -> None:
        # Biostimulant et Fertilisation partagent le même garde météo : « bloquer » = ne PAS
        # arroser l'incorporation, la pluie s'en charge (le biostimulant s'incorpore très bien
        # avec la pluie). Une pluie compensatrice bloque donc l'arrosage technique des deux.
        compensating = policy.resolve_watering_policy(
            phase_dominante="Biostimulant",
            weather={"rain_compensating": True},
        )
        self.assertEqual(compensating.selected_mode, "biostimulant")
        self.assertTrue(compensating.blocking.is_blocked)
        self.assertEqual(compensating.blocking.reason, "rain_compensating")

        heavy = policy.resolve_watering_policy(
            phase_dominante="Biostimulant",
            weather={"heavy_rain_expected": True},
        )
        self.assertTrue(heavy.blocking.is_blocked)
        self.assertEqual(heavy.blocking.reason, "heavy_rain_expected")

    def test_traitement_requires_known_application_type(self) -> None:
        resolved = policy.resolve_watering_policy(phase_dominante="Traitement")

        self.assertEqual(resolved.selected_mode, "traitement")
        self.assertTrue(resolved.blocking.is_blocked)
        self.assertEqual(resolved.blocking.reason, "application_type_required")

    def test_traitement_foliaire_blocks_watering(self) -> None:
        resolved = policy.resolve_watering_policy(
            phase_dominante="Traitement",
            application_type="foliaire",
        )

        self.assertEqual(resolved.selected_mode, "traitement")
        self.assertFalse(resolved.blocking.is_blocked)
        self.assertEqual(resolved.override_behavior, "block_watering")
        self.assertEqual(resolved.target_range.min_mm, 0.0)
        self.assertEqual(resolved.target_range.max_mm, 0.0)

    def test_traitement_sol_is_mapped_to_racinaire_rule(self) -> None:
        resolved = policy.resolve_watering_policy(
            phase_dominante="Traitement",
            application_type="sol",
        )

        self.assertEqual(resolved.selected_mode, "traitement")
        self.assertFalse(resolved.blocking.is_blocked)
        self.assertEqual(resolved.override_behavior, "targeted_override")
        self.assertEqual(resolved.target_range.min_mm, 3.0)
        self.assertEqual(resolved.target_range.max_mm, 6.0)

    def test_hivernage_blocks_by_default(self) -> None:
        resolved = policy.resolve_watering_policy(phase_dominante="Hivernage")

        self.assertEqual(resolved.selected_mode, "hivernage")
        self.assertTrue(resolved.blocking.is_blocked)
        self.assertEqual(resolved.blocking.reason, "blocked_by_default")

    def test_sursemis_overrides_hivernage_when_both_are_active(self) -> None:
        resolved = policy.resolve_watering_policy(
            phase_dominante="Hivernage",
            active_modes=["Hivernage", "Sursemis"],
        )

        self.assertEqual(resolved.selected_mode, "sursemis")
        self.assertEqual(resolved.override_behavior, "replace_all")
        self.assertFalse(resolved.blocking.is_blocked)

    def test_resolver_tolerates_scalar_active_mode_input(self) -> None:
        resolved = policy.resolve_watering_policy(
            phase_dominante="Normal",
            active_modes="Biostimulant",
        )

        self.assertEqual(resolved.requested_mode, "normal")
        self.assertEqual(resolved.selected_mode, "biostimulant")
        self.assertEqual(resolved.active_modes, ("biostimulant", "normal"))

    def test_resolver_tolerates_non_mapping_weather_payload(self) -> None:
        resolved = policy.resolve_watering_policy(
            phase_dominante="Fertilisation",
            weather="heavy rain",
        )

        self.assertEqual(resolved.selected_mode, "fertilisation")
        self.assertFalse(resolved.blocking.is_blocked)
        self.assertIsNotNone(resolved.target_range)

    def test_traitement_application_type_aliases_are_normalized(self) -> None:
        resolved = policy.resolve_watering_policy(
            phase_dominante="Traitement",
            application_type=" SOL ",
        )

        self.assertEqual(resolved.application_type, "racinaire")
        self.assertEqual(resolved.target_range.min_mm, 3.0)
        self.assertEqual(resolved.target_range.max_mm, 6.0)


if __name__ == "__main__":
    unittest.main()
