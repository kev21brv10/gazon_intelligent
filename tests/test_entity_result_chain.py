from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date
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
    history: list[dict[str, object]] | None = None
    memory: dict[str, object] | None = None


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
        watering_passages=2,
        watering_pause_minutes=25,
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
            "temperature_source": "capteur",
            "forecast_temperature_today": 18.2,
            "bilan_hydrique_mm": -1.8,
            "deficit_3j": 1.2,
            "deficit_7j": 2.4,
            "pluie_demain": 0.8,
            "temperature": 26.5,
            "etp": 3.1,
            "watering_target_date": "2026-03-18",
            "watering_window_start_minute": 360,
            "watering_window_end_minute": 570,
            "watering_evening_start_minute": 1080,
            "watering_evening_end_minute": 1260,
            "watering_window_profile": "mild",
            "watering_evening_allowed": False,
        },
    )


class DecisionResultChainTests(unittest.TestCase):
    def test_watering_sensors_return_explicit_defaults_without_history(self) -> None:
        coordinator = _FakeCoordinator(entry=_FakeEntry(), data={}, result=None, history=[], memory={})

        plan_sensor = sensor.GazonPlanArrosageSensor(coordinator)
        last_watering_sensor = sensor.GazonDernierArrosageDetecteSensor(coordinator)
        last_application_sensor = sensor.GazonDerniereApplicationSensor(coordinator)
        last_user_action_sensor = sensor.GazonDerniereActionUtilisateurSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(plan_sensor.native_value, 0.0)
        self.assertEqual(plan_sensor.extra_state_attributes["objective_mm"], 0.0)
        self.assertEqual(plan_sensor.extra_state_attributes["zone_count"], 0)
        self.assertEqual(plan_sensor.extra_state_attributes["total_duration_min"], 0.0)
        self.assertEqual(plan_sensor.extra_state_attributes["duration_human"], "0 min")
        self.assertEqual(plan_sensor.extra_state_attributes["source"], "no_plan")
        self.assertEqual(plan_sensor.extra_state_attributes["reason"], "objective_non_positive")
        self.assertEqual(plan_sensor.extra_state_attributes["plan_type"], "no_plan")
        self.assertEqual(plan_sensor.extra_state_attributes["summary"], "Aucun plan d'arrosage")
        self.assertFalse(plan_sensor.extra_state_attributes["fractionation"])

        self.assertEqual(last_watering_sensor.native_value, 0.0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["source"], "none")
        self.assertEqual(last_watering_sensor.extra_state_attributes["zone_count"], 0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["objectif_mm"], 0.0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["total_mm"], 0.0)
        self.assertEqual(last_application_sensor.native_value, "Aucune application")
        self.assertEqual(last_user_action_sensor.native_value, "none")
        self.assertEqual(last_user_action_sensor.extra_state_attributes["summary"], "Aucune action récente")
        self.assertFalse(application_allowed_sensor.is_on)
        self.assertNotIn("application_type", application_allowed_sensor.extra_state_attributes)

    def test_plan_sensor_distinguishes_single_zone_without_fractionation(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "objectif_mm": 1.0,
                "zone_1": "switch.zone_1",
                "debit_zone_1": 60.0,
            },
            result=None,
            history=[],
            memory={},
        )

        plan_sensor = sensor.GazonPlanArrosageSensor(coordinator)

        self.assertEqual(plan_sensor.native_value, 1.0)
        self.assertEqual(plan_sensor.extra_state_attributes["plan_type"], "single_zone")
        self.assertFalse(plan_sensor.extra_state_attributes["fractionation"])
        self.assertEqual(plan_sensor.extra_state_attributes["zone_count"], 1)

    def test_watering_window_sensor_exposes_contextual_status(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=_make_result(),
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.native_value, "demain_matin")
        self.assertEqual(window_sensor.extra_state_attributes["status"], "auto")
        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Aucune action requise")
        self.assertEqual(window_sensor.extra_state_attributes["summary"], "Arrosage prévu demain matin (auto)")

    def test_watering_window_sensor_exposes_morning_same_day_status(self) -> None:
        result = _make_result()
        result.fenetre_optimale = "ce_matin"
        result.extra["watering_target_date"] = date(2026, 3, 17).isoformat()

        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.native_value, "ce_matin")
        self.assertEqual(window_sensor.extra_state_attributes["summary"], "Arrosage prévu ce matin (auto)")
        self.assertEqual(window_sensor.extra_state_attributes["watering_target_date"], "2026-03-17")

    def test_watering_window_sensor_uses_manual_immediate_wording(self) -> None:
        result = _make_result()
        result.extra["application_irrigation_mode"] = "manuel"
        result.extra["application_type"] = "sol"
        result.extra["application_requires_watering_after"] = True
        result.extra["application_post_watering_pending"] = True
        result.extra["application_post_watering_ready"] = True
        result.extra["application_block_active"] = False
        result.extra["objective_mm"] = 1.0
        result.extra["watering_target_date"] = "2026-03-18"
        result.extra["derniere_application"] = {
            "libelle": "Engrais granulé",
            "application_type": "sol",
            "application_requires_watering_after": True,
        }
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Arrosage manuel immédiat")
        self.assertNotIn("Forcer", window_sensor.extra_state_attributes["next_action"])

    def test_auto_irrigation_switch_off_blocks_auto_window_and_application_sensor(self) -> None:
        result = _make_result()
        result.extra["auto_irrigation_enabled"] = False
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={"auto_irrigation_enabled": False},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(window_sensor.extra_state_attributes["status"], "bloque")
        self.assertEqual(window_sensor.extra_state_attributes["summary"], "Arrosage automatique désactivé")
        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Réactiver l'arrosage automatique")
        self.assertFalse(window_sensor.extra_state_attributes["auto_irrigation_enabled"])
        self.assertFalse(application_allowed_sensor.is_on)
        self.assertFalse(application_allowed_sensor.extra_state_attributes["auto_irrigation_enabled"])

    def test_watering_window_sensor_blocks_unknown_application_type(self) -> None:
        result = _make_result()
        result.extra["derniere_application"] = {
            "libelle": "Produit inconnu",
            "type": "Traitement",
            "application_type": "autre",
            "application_requires_watering_after": True,
        }
        result.extra["application_type"] = "autre"
        result.extra["application_requires_watering_after"] = True
        result.extra["application_block_active"] = False
        result.extra["application_post_watering_pending"] = False
        result.extra["arrosage_recommande"] = False
        result.extra["objectif_mm"] = 0.0
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=result,
            history=[],
            memory={},
        )

        window_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)

        self.assertEqual(window_sensor.extra_state_attributes["status"], "bloque")
        self.assertIn("type d'application inconnu", window_sensor.extra_state_attributes["summary"])
        self.assertEqual(window_sensor.extra_state_attributes["next_action"], "Vérifier le type d'application")

    def test_application_entities_surface_latest_application_state(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=None,
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit_id": "humuslight",
                    "produit": "Humuslight",
                    "dose": "12.5",
                    "source": "service",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "auto",
                    "application_label_notes": "Bien arroser après application",
                }
            ],
        )

        last_application_sensor = sensor.GazonDerniereApplicationSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(last_application_sensor.native_value, "Humuslight")
        self.assertEqual(last_application_sensor.extra_state_attributes["application_type"], "sol")
        self.assertEqual(last_application_sensor.extra_state_attributes["application_irrigation_mode"], "auto")
        self.assertTrue(application_allowed_sensor.is_on)
        self.assertEqual(application_allowed_sensor.extra_state_attributes["application_post_watering_mm"], 1.0)

    def test_application_state_falls_back_to_history_without_memory(self) -> None:
        coordinator = _FakeCoordinator(
            entry=_FakeEntry(),
            data={},
            result=None,
            history=[
                {
                    "type": "Fertilisation",
                    "date": "2026-03-18",
                    "declared_at": "2026-03-18T08:00:00+00:00",
                    "produit": "Engrais printemps",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "auto",
                }
            ],
            memory=None,
        )

        last_application_sensor = sensor.GazonDerniereApplicationSensor(coordinator)
        application_allowed_sensor = binary_sensor.GazonApplicationArrosageAutoriseBinarySensor(coordinator)

        self.assertEqual(last_application_sensor.native_value, "Engrais printemps")
        self.assertTrue(application_allowed_sensor.is_on)
        self.assertEqual(application_allowed_sensor.extra_state_attributes["application_type"], "sol")

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
                "zone_1": "switch.zone_1",
                "zone_2": "switch.zone_2",
                "debit_zone_1": 60.0,
                "debit_zone_2": 30.0,
            },
            result=_make_result(),
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-03-18",
                    "source": "zone_session",
                    "detected_at": "2026-03-18T06:14:00+00:00",
                    "objectif_mm": 4.0,
                    "total_mm": 4.0,
                    "session_total_mm": 4.0,
                    "zone_count": 2,
                    "zones": [
                        {
                            "order": 1,
                            "zone": "switch.zone_1",
                            "entity_id": "switch.zone_1",
                            "rate_mm_h": 60.0,
                            "duration_min": 2.0,
                            "duration_seconds": 120,
                            "mm": 2.0,
                        },
                        {
                            "order": 2,
                            "zone": "switch.zone_2",
                            "entity_id": "switch.zone_2",
                            "rate_mm_h": 30.0,
                            "duration_min": 4.0,
                            "duration_seconds": 240,
                            "mm": 2.0,
                        },
                    ],
                }
            ],
        )

        phase_sensor = sensor.GazonPhaseActiveSensor(coordinator)
        sous_phase_sensor = sensor.GazonSousPhaseSensor(coordinator)
        objectif_sensor = sensor.GazonObjectifMmSensor(coordinator)
        fenetre_sensor = sensor.GazonFenetreOptimaleSensor(coordinator)
        type_arrosage_sensor = sensor.GazonTypeArrosageSensor(coordinator)
        plan_sensor = sensor.GazonPlanArrosageSensor(coordinator)
        last_watering_sensor = sensor.GazonDernierArrosageDetecteSensor(coordinator)
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
        self.assertEqual(objectif_sensor.extra_state_attributes["bilan_hydrique_mm"], -1.8)
        self.assertEqual(objectif_sensor.extra_state_attributes["deficit_3j"], 1.2)
        self.assertEqual(objectif_sensor.extra_state_attributes["deficit_7j"], 2.4)
        self.assertEqual(objectif_sensor.extra_state_attributes["pluie_demain"], 0.8)
        self.assertEqual(objectif_sensor.extra_state_attributes["temperature"], 26.5)
        self.assertEqual(objectif_sensor.extra_state_attributes["forecast_temperature_today"], 18.2)
        self.assertEqual(objectif_sensor.extra_state_attributes["temperature_source"], "capteur")
        self.assertEqual(objectif_sensor.extra_state_attributes["etp"], 3.1)
        self.assertEqual(fenetre_sensor.native_value, "demain_matin")
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_target_date"], "2026-03-18")
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_window_start_minute"], 360)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_window_end_minute"], 570)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_evening_start_minute"], 1080)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_evening_end_minute"], 1260)
        self.assertEqual(fenetre_sensor.extra_state_attributes["watering_window_profile"], "mild")
        self.assertFalse(fenetre_sensor.extra_state_attributes["watering_evening_allowed"])
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
                "Arrosage technique",
                "Arrosage automatique",
            ],
        )
        self.assertEqual(plan_sensor.native_value, 3.5)
        self.assertEqual(plan_sensor.extra_state_attributes["objective_mm"], 1.2)
        self.assertEqual(plan_sensor.extra_state_attributes["zone_count"], 2)
        self.assertTrue(plan_sensor.extra_state_attributes["fractionation"])
        self.assertEqual(plan_sensor.extra_state_attributes["plan_type"], "multi_zone")
        self.assertEqual(plan_sensor.extra_state_attributes["source"], "calculated_from_objective")
        self.assertEqual(plan_sensor.extra_state_attributes["total_duration_min"], 3.5)
        self.assertEqual(plan_sensor.extra_state_attributes["duration_human"], "3 min 30")
        self.assertEqual(plan_sensor.extra_state_attributes["summary"], "2 zones • 1.2 mm • 3 min 30")
        self.assertEqual(plan_sensor.extra_state_attributes["passages"], 2)
        self.assertEqual(plan_sensor.extra_state_attributes["pause_between_passages_minutes"], 25)
        self.assertEqual(plan_sensor.extra_state_attributes["zones"][0]["zone"], "switch.zone_1")
        self.assertEqual(plan_sensor.extra_state_attributes["zones"][0]["duration_min"], 1.0)
        self.assertEqual(plan_sensor.extra_state_attributes["zones"][1]["duration_min"], 2.5)
        self.assertEqual(last_watering_sensor.native_value, 4.0)
        self.assertEqual(last_watering_sensor.extra_state_attributes["source"], "zone_session")
        self.assertEqual(last_watering_sensor.extra_state_attributes["date_action"], "2026-03-18")
        self.assertEqual(last_watering_sensor.extra_state_attributes["detected_at"], "2026-03-18T06:14:00+00:00")
        self.assertEqual(last_watering_sensor.extra_state_attributes["zone_count"], 2)
        self.assertEqual(last_watering_sensor.extra_state_attributes["zones_used"], ["switch.zone_1", "switch.zone_2"])
        self.assertEqual(last_watering_sensor.extra_state_attributes["zones"][0]["order"], 1)
        self.assertEqual(last_watering_sensor.extra_state_attributes["zones"][1]["order"], 2)
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
