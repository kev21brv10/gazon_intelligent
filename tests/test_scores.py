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


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)

scores = importlib.import_module("custom_components.gazon_intelligent.scores")


class ScoresContractTests(unittest.TestCase):
    def test_classify_stress_level_keeps_same_thresholds(self) -> None:
        self.assertEqual(
            scores.classify_stress_level(
                score_hydrique=80,
                score_stress=10,
                water_balance={},
                temperature=20.0,
                etp=2.0,
            ),
            "fort",
        )
        self.assertEqual(
            scores.classify_stress_level(
                score_hydrique=10,
                score_stress=45,
                water_balance={},
                temperature=20.0,
                etp=2.0,
            ),
            "modere",
        )
        self.assertEqual(
            scores.classify_stress_level(
                score_hydrique=10,
                score_stress=10,
                water_balance={"deficit_jour": 0.5, "deficit_3j": 1.0, "deficit_7j": 1.0},
                temperature=20.0,
                etp=2.0,
            ),
            "leger",
        )

    def test_compute_internal_scores_preserves_structured_keys(self) -> None:
        result = scores.compute_internal_scores(
            history=[],
            today=None,
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "deficit_jour": 1.0,
                "deficit_3j": 2.0,
                "deficit_7j": 3.0,
                "pluie_efficace": 0.0,
                "arrosage_recent": 0.0,
            },
            advanced_context={"humidite_sol": 35.0, "hauteur_gazon": 10.0},
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=55.0,
            temperature=28.0,
            etp=3.5,
        )
        self.assertEqual(set(result), {"score_hydrique", "score_stress", "score_tonte"})
        self.assertGreaterEqual(result["score_hydrique"], 0)
        self.assertLessEqual(result["score_tonte"], 100)

    def test_stress_transfer_to_tonte_remains_explicit(self) -> None:
        base = scores.compute_internal_scores(
            history=[],
            today=None,
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={"deficit_jour": 0.0, "deficit_3j": 0.0, "deficit_7j": 0.0},
            advanced_context={"hauteur_gazon": 6.0},
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=60.0,
            temperature=20.0,
            etp=2.0,
        )
        stressed = scores.compute_internal_scores(
            history=[],
            today=None,
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={"deficit_jour": 0.0, "deficit_3j": 0.0, "deficit_7j": 0.0},
            advanced_context={"hauteur_gazon": 6.0},
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=30.0,
            temperature=34.0,
            etp=5.0,
        )
        self.assertGreater(stressed["score_stress"], base["score_stress"])
        self.assertGreater(stressed["score_tonte"], base["score_tonte"])


if __name__ == "__main__":
    unittest.main()
