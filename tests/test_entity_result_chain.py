from __future__ import annotations

import unittest
from dataclasses import dataclass
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


def _install_homeassistant_stubs() -> None:
    def ensure_module(name: str) -> types.ModuleType:
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        return module

    ensure_module("homeassistant")
    ensure_module("homeassistant.components")
    ensure_module("homeassistant.helpers")

    sensor_mod = ensure_module("homeassistant.components.sensor")
    if not hasattr(sensor_mod, "SensorEntity"):
        sensor_mod.SensorEntity = type("SensorEntity", (), {"__init__": lambda self, *args, **kwargs: None})
    if not hasattr(sensor_mod, "SensorStateClass"):
        sensor_mod.SensorStateClass = type("SensorStateClass", (), {"MEASUREMENT": "measurement"})

    binary_sensor_mod = ensure_module("homeassistant.components.binary_sensor")
    if not hasattr(binary_sensor_mod, "BinarySensorEntity"):
        binary_sensor_mod.BinarySensorEntity = type("BinarySensorEntity", (), {"__init__": lambda self, *args, **kwargs: None})

    helpers_entity_mod = ensure_module("homeassistant.helpers.entity")
    if not hasattr(helpers_entity_mod, "DeviceInfo"):
        class DeviceInfo(dict):
            pass

        helpers_entity_mod.DeviceInfo = DeviceInfo

    update_coordinator_mod = ensure_module("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator_mod, "CoordinatorEntity"):
        class CoordinatorEntity:
            def __init__(self, coordinator):
                self.coordinator = coordinator

        update_coordinator_mod.CoordinatorEntity = CoordinatorEntity


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

decision_models = __import__("custom_components.gazon_intelligent.decision_models", fromlist=["DecisionResult"])
sensor = __import__("custom_components.gazon_intelligent.sensor", fromlist=["GazonPhaseActiveSensor"])
binary_sensor = __import__("custom_components.gazon_intelligent.binary_sensor", fromlist=["GazonTonteAutoriseeBinarySensor"])


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"


@dataclass
class _FakeCoordinator:
    entry: _FakeEntry
    data: dict[str, object]
    result: object | None = None
    last_result: object | None = None


def _make_result():
    return decision_models.DecisionResult(
        phase_dominante="Sursemis",
        sous_phase="Enracinement",
        action_recommandee="Arroser demain matin en 2 passages courts.",
        action_a_eviter="Tondre avant levée complète.",
        niveau_action="critique",
        fenetre_optimale="demain_matin",
        risque_gazon="eleve",
        objectif_arrosage=1.2,
        tonte_autorisee=True,
        hauteur_tonte_recommandee_cm=7.0,
        hauteur_tonte_min_cm=3.0,
        hauteur_tonte_max_cm=8.0,
        conseil_principal="Arroser demain matin.",
        tonte_statut="autorisee",
        arrosage_recommande=True,
        arrosage_auto_autorise=True,
        type_arrosage="fractionne",
        arrosage_conseille="fractionne",
        phase_dominante_source="historique_actif",
        sous_phase_detail="Sursemis / Enracinement",
        sous_phase_age_days=12,
        sous_phase_progression=57,
        prochaine_reevaluation="dans 24 h",
        urgence="moyenne",
        raison_decision="Test DecisionResult-first.",
        score_hydrique=42,
        score_stress=33,
        score_tonte=12,
        extra={
            "configuration": {"type_sol": "argileux"},
            "pluie_demain_source": "meteo_forecast",
        },
    )


class DecisionResultChainTests(unittest.TestCase):
    def test_entities_read_decision_result_before_legacy_snapshot(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "phase_active": "Normal",
                "sous_phase_age_days": 20,
                "objectif_mm": 9.9,
                "tonte_autorisee": False,
                "arrosage_recommande": False,
                "tonte_statut": "interdite",
                "niveau_action": "faible",
                "fenetre_optimale": "attendre",
                "risque_gazon": "faible",
                "phase_dominante_source": "legacy",
                "pluie_demain_source": "legacy",
                "configuration": {"type_sol": "sableux"},
            },
            result=_make_result(),
        )

        phase_sensor = sensor.GazonPhaseActiveSensor(coordinator)
        sous_phase_sensor = sensor.GazonSousPhaseSensor(coordinator)
        objectif_sensor = sensor.GazonObjectifMmSensor(coordinator)
        type_arrosage_sensor = sensor.GazonTypeArrosageSensor(coordinator)
        hauteur_sensor = sensor.GazonHauteurTonteSensor(coordinator)
        tonte_sensor = binary_sensor.GazonTonteAutoriseeBinarySensor(coordinator)
        arrosage_sensor = binary_sensor.GazonArrosageRecommandeBinarySensor(coordinator)

        self.assertEqual(phase_sensor.native_value, "Sursemis")
        self.assertEqual(phase_sensor.extra_state_attributes["phase_dominante_source"], "historique_actif")
        self.assertEqual(phase_sensor.extra_state_attributes["pluie_demain_source"], "meteo_forecast")
        self.assertEqual(phase_sensor.extra_state_attributes["configuration"]["type_sol"], "argileux")
        self.assertEqual(sous_phase_sensor.native_value, "Enracinement")
        self.assertEqual(sous_phase_sensor.extra_state_attributes["sous_phase_age_days"], 12)
        self.assertEqual(objectif_sensor.native_value, 1.2)
        self.assertEqual(type_arrosage_sensor.native_value, "Arrosage fractionné")
        self.assertEqual(hauteur_sensor.native_value, 7.0)
        self.assertEqual(hauteur_sensor.extra_state_attributes["hauteur_tonte_min_cm"], 3.0)
        self.assertEqual(hauteur_sensor.extra_state_attributes["hauteur_tonte_max_cm"], 8.0)
        self.assertEqual(hauteur_sensor.extra_state_attributes["tonte_statut"], "autorisee")
        self.assertEqual(hauteur_sensor.extra_state_attributes["phase_active"], "Sursemis")
        self.assertEqual(
            type_arrosage_sensor.extra_state_attributes["possible_values"],
            [
                "Arrosage bloqué",
                "Réglage personnalisé",
                "Arrosage manuel fréquent",
                "Arrosage fractionné",
                "Arrosage automatique",
            ],
        )
        self.assertTrue(tonte_sensor.is_on)
        self.assertTrue(arrosage_sensor.is_on)
        self.assertEqual(
            tonte_sensor.extra_state_attributes["hauteur_tonte_recommandee_cm"],
            7.0,
        )
        self.assertEqual(tonte_sensor.extra_state_attributes["hauteur_tonte_min_cm"], 3.0)
        self.assertEqual(tonte_sensor.extra_state_attributes["hauteur_tonte_max_cm"], 8.0)
        self.assertNotIn("pas_hauteur_tondeuse_cm", tonte_sensor.extra_state_attributes)
        self.assertIn("possible_values", phase_sensor.extra_state_attributes)
        self.assertIn("possible_values", sous_phase_sensor.extra_state_attributes)

        self.assertEqual(
            phase_sensor.extra_state_attributes["possible_values"],
            [
                "Normal",
                "Sursemis",
                "Traitement",
                "Fertilisation",
                "Biostimulant",
                "Agent Mouillant",
                "Scarification",
                "Hivernage",
            ],
        )
        self.assertIn("Germination", sous_phase_sensor.extra_state_attributes["possible_values"])
        self.assertEqual(
            decision_models.DecisionResult(
                phase_dominante="Normal",
                sous_phase="Normal",
                action_recommandee="",
                action_a_eviter="",
                niveau_action="a_faire",
                fenetre_optimale="maintenant",
                risque_gazon="faible",
                objectif_arrosage=0.0,
                tonte_autorisee=True,
            ).possible_values["niveau_action"],
            ("aucune_action", "surveiller", "a_faire", "critique"),
        )

    def test_sous_phase_is_not_recomputed_locally(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "phase_active": "Sursemis",
                "sous_phase_age_days": 20,
            },
            result=_make_result(),
        )
        result = sensor.GazonSousPhaseSensor(coordinator).native_value

        self.assertEqual(result, "Enracinement")

    def test_pluie_demain_source_is_normalized_when_legacy_snapshot_uses_indisponible(self) -> None:
        result = _make_result()
        result.extra["pluie_demain_source"] = "indisponible"
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={"pluie_demain_source": "indisponible"},
            result=result,
        )

        phase_sensor = sensor.GazonPhaseActiveSensor(coordinator)

        self.assertEqual(phase_sensor.extra_state_attributes["pluie_demain_source"], "non disponible")


if __name__ == "__main__":
    unittest.main()
