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


class ComparisonRulesFirstMatchTests(unittest.TestCase):
    """`_apply_comparison_rules` CUMULAIT toutes les règles satisfaites, alors que les tables sont
    écrites en cascade (du palier le plus sévère au moins sévère), comme celles de
    `_threshold_score` qui, lui, s'arrête au premier match. Une humidité de 30 % déclenchait donc
    `<=35` ET `<=45` : 28 au lieu de 18. Le score de stress était gonflé de +10 en permanence par
    temps sec, et de +6 au-dessus de 90 % d'humidité."""

    TABLE = (
        ("<=", 35.0, 18.0),
        ("<=", 45.0, 10.0),
        (">=", 90.0, 10.0),
        (">=", 82.0, 6.0),
    )

    def test_le_palier_le_plus_severe_gagne_seul(self) -> None:
        for valeur, attendu in ((25.0, 18.0), (30.0, 18.0), (35.0, 18.0)):
            with self.subTest(humidite=valeur):
                self.assertEqual(scores._apply_comparison_rules(valeur, self.TABLE), attendu)

    def test_le_palier_intermediaire_reste_correct(self) -> None:
        for valeur in (40.0, 45.0):
            with self.subTest(humidite=valeur):
                self.assertEqual(scores._apply_comparison_rules(valeur, self.TABLE), 10.0)

    def test_cote_humide_ne_cumule_plus(self) -> None:
        for valeur, attendu in ((85.0, 6.0), (90.0, 10.0), (95.0, 10.0)):
            with self.subTest(humidite=valeur):
                self.assertEqual(scores._apply_comparison_rules(valeur, self.TABLE), attendu)

    def test_zone_neutre_ne_score_pas(self) -> None:
        for valeur in (50.0, 60.0, 70.0, 81.0):
            with self.subTest(humidite=valeur):
                self.assertEqual(scores._apply_comparison_rules(valeur, self.TABLE), 0.0)

    def test_meme_semantique_que_threshold_score(self) -> None:
        # Les deux helpers coexistent dans le module : ils doivent s'arrêter au premier match.
        table_seuils = ((90.0, 10.0), (82.0, 6.0))
        table_comparaisons = ((">=", 90.0, 10.0), (">=", 82.0, 6.0))
        for valeur in (95.0, 90.0, 85.0, 82.0, 70.0):
            with self.subTest(valeur=valeur):
                self.assertEqual(
                    scores._apply_comparison_rules(valeur, table_comparaisons),
                    scores._threshold_score(valeur, table_seuils),
                )


class WateringThresholdStrictlyPositiveTests(unittest.TestCase):
    """Avant le refactor 0.7.0 (8b226ff) les règles étaient `elif arrosage_recent > 0`,
    STRICTEMENT positives. Leur conversion en tables lues par `_threshold_score` (qui compare
    avec `>=`) a mué `> 0` en `>= 0` : le palier bas se déclenchait donc même SANS arrosage
    récent, ajoutant +6 en permanence au score de tonte et -3 au score hydrique."""

    def test_sans_arrosage_recent_aucun_palier_ne_sapplique(self) -> None:
        self.assertEqual(scores._threshold_score(0.0, scores._TONTE_WATERING_WEIGHTS), 0.0)
        self.assertEqual(scores._threshold_score(0.0, scores._HYDRIC_WATERING_MALUS), 0.0)

    def test_le_plus_petit_arrosage_reel_declenche_le_palier(self) -> None:
        # water.py arrondit à 1 décimale : 0.1 mm est la plus petite valeur non nulle.
        self.assertEqual(scores._threshold_score(0.1, scores._TONTE_WATERING_WEIGHTS), 6.0)
        self.assertEqual(scores._threshold_score(0.1, scores._HYDRIC_WATERING_MALUS), -3.0)

    def test_les_paliers_hauts_sont_inchanges(self) -> None:
        self.assertEqual(scores._threshold_score(3.0, scores._TONTE_WATERING_WEIGHTS), 12.0)
        self.assertEqual(scores._threshold_score(4.0, scores._HYDRIC_WATERING_MALUS), -8.0)
        self.assertEqual(scores._threshold_score(8.0, scores._HYDRIC_WATERING_MALUS), -14.0)

    def test_aucune_table_narrose_le_zero(self) -> None:
        # Garde générique : aucun palier ne doit avoir 0.0 comme seuil, sans quoi il est
        # inconditionnel avec la sémantique `>=` de _threshold_score.
        for nom in ("_TONTE_WATERING_WEIGHTS", "_HYDRIC_WATERING_MALUS"):
            with self.subTest(table=nom):
                seuils = [s for s, _ in getattr(scores, nom)]
                self.assertNotIn(0.0, seuils)
