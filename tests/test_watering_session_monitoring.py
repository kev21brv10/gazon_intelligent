from __future__ import annotations

import asyncio
import importlib
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    const_mod = ensure_module("homeassistant.const")
    if not hasattr(const_mod, "EVENT_HOMEASSISTANT_STARTED"):
        const_mod.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"

    config_entries_mod = ensure_module("homeassistant.config_entries")
    if not hasattr(config_entries_mod, "ConfigEntry"):
        class ConfigEntry:
            pass

        config_entries_mod.ConfigEntry = ConfigEntry

    core_mod = ensure_module("homeassistant.core")
    if not hasattr(core_mod, "callback"):
        def callback(func):
            return func

        core_mod.callback = callback
    if not hasattr(core_mod, "CALLBACK_TYPE"):
        core_mod.CALLBACK_TYPE = object
    if not hasattr(core_mod, "Event"):
        class Event:
            pass

        core_mod.Event = Event
    if not hasattr(core_mod, "HomeAssistant"):
        class HomeAssistant:
            pass

        core_mod.HomeAssistant = HomeAssistant

    exceptions_mod = ensure_module("homeassistant.exceptions")
    if not hasattr(exceptions_mod, "HomeAssistantError"):
        class HomeAssistantError(Exception):
            pass

        exceptions_mod.HomeAssistantError = HomeAssistantError

    helpers_mod = ensure_module("homeassistant.helpers")
    event_mod = ensure_module("homeassistant.helpers.event")
    if not hasattr(event_mod, "async_call_later"):
        def async_call_later(*args, **kwargs):
            return lambda: None

        event_mod.async_call_later = async_call_later
    if not hasattr(event_mod, "async_track_state_change_event"):
        def async_track_state_change_event(*args, **kwargs):
            return lambda: None

        event_mod.async_track_state_change_event = async_track_state_change_event

    update_coordinator_mod = ensure_module("homeassistant.helpers.update_coordinator")
    if not hasattr(update_coordinator_mod, "DataUpdateCoordinator"):
        class DataUpdateCoordinator:
            def __class_getitem__(cls, item):
                return cls

            def __init__(self, *args, **kwargs):
                pass

        update_coordinator_mod.DataUpdateCoordinator = DataUpdateCoordinator

    storage_mod = ensure_module("homeassistant.helpers.storage")
    if not hasattr(storage_mod, "Store"):
        class Store:
            def __init__(self, *args, **kwargs):
                pass

        storage_mod.Store = Store


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

coordinator_mod = importlib.import_module("custom_components.gazon_intelligent.coordinator")


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"
    data: dict[str, object] = field(default_factory=dict)
    options: dict[str, object] = field(default_factory=dict)


@dataclass
class _FakeState:
    state: str
    last_changed: datetime
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass
class _FakeStates:
    states: dict[str, _FakeState]

    def get(self, entity_id: str) -> _FakeState | None:
        return self.states.get(entity_id)


@dataclass
class _FakeHass:
    states: _FakeStates


def _build_coordinator() -> object:
    coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
    coord.entry = _FakeEntry(
        data={
            "zone_1": "switch.zone_1",
            "zone_2": "switch.zone_2",
            "debit_zone_1": 60.0,
            "debit_zone_2": 30.0,
            "zone_3": None,
            "zone_4": None,
            "zone_5": None,
        }
        )
    coord._watering_session = None
    coord._unsub_watering_session_finalize = None
    coord._zone_tracking_suspended = 0
    return coord


class WateringSessionMonitoringTests(unittest.TestCase):
    def test_short_impulse_session_is_cleared_on_finalize(self) -> None:
        coordinator = _build_coordinator()
        start = datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc)

        coordinator._track_watering_zone_on("switch.zone_1", start)
        should_finalize = coordinator._track_watering_zone_off(
            "switch.zone_1",
            start + timedelta(seconds=3),
        )

        self.assertTrue(should_finalize)
        asyncio.run(coordinator._async_finalize_watering_session(start + timedelta(seconds=20)))
        self.assertIsNone(coordinator._watering_session)

    def test_zone_session_merges_consecutive_zones(self) -> None:
        coordinator = _build_coordinator()
        start = datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc)

        coordinator._track_watering_zone_on("switch.zone_1", start)
        coordinator._track_watering_zone_off("switch.zone_1", start + timedelta(minutes=2))
        coordinator._track_watering_zone_on("switch.zone_2", start + timedelta(minutes=2, seconds=8))
        coordinator._track_watering_zone_off("switch.zone_2", start + timedelta(minutes=6, seconds=8))

        payload = coordinator._build_watering_session_payload()

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["source"], "zone_session")
        self.assertEqual(payload["objectif_mm"], 4.0)
        self.assertEqual(payload["total_mm"], 4.0)
        self.assertEqual(payload["date_action"], start.date())
        self.assertEqual(len(payload["zones"]), 2)
        self.assertEqual(payload["zones"][0]["zone"], "switch.zone_1")
        self.assertEqual(payload["zones"][1]["zone"], "switch.zone_2")
        self.assertEqual(payload["zones"][0]["mm"], 2.0)
        self.assertEqual(payload["zones"][1]["mm"], 2.0)

    def test_restart_rebuilds_active_zones(self) -> None:
        coordinator = _build_coordinator()
        start = datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc)
        coordinator.hass = _FakeHass(
            states=_FakeStates(
                {
                    "switch.zone_1": _FakeState("on", start, {}),
                    "switch.zone_2": _FakeState("on", start + timedelta(minutes=3), {}),
                }
            )
        )

        coordinator._rebuild_watering_session_from_current_state()

        self.assertIsNotNone(coordinator._watering_session)
        assert coordinator._watering_session is not None
        self.assertIn("switch.zone_1", coordinator._watering_session["active_zones"])
        self.assertIn("switch.zone_2", coordinator._watering_session["active_zones"])
        self.assertEqual(coordinator._watering_session["started_at"], start)
        self.assertEqual(coordinator._watering_session["zones"]["switch.zone_1"]["order"], 1)
        self.assertEqual(coordinator._watering_session["zones"]["switch.zone_2"]["order"], 2)

    def test_plan_sensor_state_can_be_read_from_current_state(self) -> None:
        coordinator = _build_coordinator()
        start = datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc)
        coordinator.hass = _FakeHass(
            states=_FakeStates(
                {
                    "sensor.gazon_intelligent_plan_arrosage": _FakeState(
                        "3.5",
                        start,
                        {
                            "objective_mm": 1.2,
                            "total_duration_min": 3.5,
                            "zone_count": 2,
                            "fractionation": True,
                            "passages": 2,
                            "pause_between_passages_minutes": 25,
                            "zones": [
                                {"zone": "switch.zone_1", "duration_seconds": 60.0},
                                {"zone": "switch.zone_2", "duration_seconds": 150.0},
                            ],
                        },
                    )
                }
            )
        )

        plan = coordinator._build_watering_plan_from_state("sensor.gazon_intelligent_plan_arrosage")

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["passages"], 2)
        self.assertEqual(plan["pause_between_passages_minutes"], 25)
        self.assertEqual(len(plan["zones"]), 2)
        self.assertEqual(plan["zones"][0]["zone"], "switch.zone_1")

    def test_update_data_falls_back_to_history_when_return_sensor_is_zero(self) -> None:
        coordinator = _build_coordinator()
        coordinator._loaded = True
        async def _load_state():
            return None
        coordinator._async_load_state = _load_state
        captured: dict[str, object] = {}

        class _Brain:
            last_result = None

            def compute_snapshot(self, **kwargs):
                captured.update(kwargs)
                return {
                    "mode": "Normal",
                    "phase_active": "Normal",
                    "objectif_mm": 1.2,
                    "tonte_autorisee": True,
                    "tonte_statut": "autorisee",
                    "arrosage_recommande": True,
                    "type_arrosage": "auto",
                    "conseil_principal": "ok",
                    "action_recommandee": "ok",
                    "action_a_eviter": "ok",
                    "niveau_action": "surveiller",
                    "fenetre_optimale": "matin",
                    "risque_gazon": "faible",
                    "phase_dominante": "Normal",
                    "phase_dominante_source": "historique",
                    "sous_phase": "Germination",
                    "sous_phase_detail": "Germination",
                    "sous_phase_age_days": 1,
                    "sous_phase_progression": "early",
                }

        coordinator.brain = _Brain()
        coordinator.history = [
            {
                "type": "arrosage",
                "date": datetime.now(timezone.utc).date().isoformat(),
                "objectif_mm": 4.0,
                "zones": [{"zone": "switch.zone_1", "mm": 2.0}],
            }
        ]
        coordinator._get_conf = lambda key: {
            "capteur_pluie_24h": "sensor.pluie_24h",
            "capteur_pluie_demain": "sensor.pluie_demain",
            "capteur_temperature": "sensor.temperature",
            "capteur_etp": "sensor.etp",
            "capteur_humidite": "sensor.humidity",
            "capteur_humidite_sol": "sensor.soil_humidity",
            "capteur_vent": "sensor.wind",
            "capteur_rosee": "sensor.dew",
            "capteur_hauteur_gazon": "sensor.height",
            "capteur_retour_arrosage": "sensor.return_watering",
            "type_sol": "limoneux",
            "hauteur_min_tondeuse_cm": 3.0,
            "hauteur_max_tondeuse_cm": 6.0,
        }.get(key)
        coordinator._get_float_state = lambda entity_id: {
            "sensor.pluie_24h": 0.0,
            "sensor.pluie_demain": 0.0,
            "sensor.temperature": 24.0,
            "sensor.etp": 4.0,
            "sensor.humidity": 55.0,
            "sensor.soil_humidity": 30.0,
            "sensor.wind": 5.0,
            "sensor.dew": 0.0,
            "sensor.height": 10.0,
            "sensor.return_watering": 0.0,
        }.get(entity_id)
        coordinator._get_weather_profile = lambda entity_id: {}

        async def _forecast_summary(entity_id):  # noqa: ARG001
            return {}

        async def _save_state():
            return None

        coordinator._get_weather_forecast_summary = _forecast_summary
        coordinator._estimate_rosee = lambda weather_profile, temperature, humidite: 0.0  # noqa: ARG001
        coordinator._get_float_conf = lambda key, default: default
        coordinator._async_save_state = _save_state

        result = asyncio.run(coordinator._async_update_data())

        self.assertEqual(captured["retour_arrosage"], 4.0)
        self.assertEqual(result["objectif_mm"], 1.2)
        self.assertEqual(result["phase_dominante"], "Normal")
