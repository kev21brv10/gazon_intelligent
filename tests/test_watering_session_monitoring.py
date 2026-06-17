from __future__ import annotations

import asyncio
import importlib
import unittest
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock


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
    if not hasattr(event_mod, "async_track_time_interval"):
        def async_track_time_interval(*args, **kwargs):
            return lambda: None

        event_mod.async_track_time_interval = async_track_time_interval
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

    util_mod = ensure_module("homeassistant.util")
    dt_mod = ensure_module("homeassistant.util.dt")
    if not hasattr(dt_mod, "now"):
        dt_mod.now = lambda: datetime.now(timezone.utc)
    if not hasattr(dt_mod, "utcnow"):
        dt_mod.utcnow = lambda: datetime.now(timezone.utc)
    if not hasattr(util_mod, "dt"):
        util_mod.dt = dt_mod


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

coordinator_mod = importlib.import_module("custom_components.gazon_intelligent.coordinator")
watering_plan_mod = importlib.import_module("custom_components.gazon_intelligent.watering_plan")
mower_adapter_mod = importlib.import_module("custom_components.gazon_intelligent.mower_adapter")


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
class _FakeSharedState:
    shared_config: dict[str, object] = field(default_factory=dict)

    def get_conf(self, key: str) -> object | None:
        return self.shared_config.get(key)


@dataclass
class _FakeHass:
    states: _FakeStates


@dataclass
class _FakeMowerState:
    entity_id: str
    state: str
    name: str | None = None


@dataclass
class _FakeStatesWithAll:
    states: dict[str, _FakeState]
    mower_states: list[_FakeMowerState] = field(default_factory=list)

    def get(self, entity_id: str) -> _FakeState | None:
        return self.states.get(entity_id)

    def async_all(self, domain: str | None = None) -> list[_FakeMowerState]:
        if domain in (None, "lawn_mower"):
            return list(self.mower_states)
        return []


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
    coord.brain = types.SimpleNamespace(
        memory={
            "auto_irrigation_enabled": True,
            "auto_irrigation_user_confirmed": True,
        },
        last_result=None,
    )
    coord._watering_session = None
    coord._unsub_watering_session_finalize = None
    coord._zone_tracking_suspended = 0
    coord._zone_tracking_resumed_at = None
    coord._runtime_state = {
        "active_irrigation_session": None,
        "last_irrigation_execution": None,
        "last_auto_irrigation_reason": None,
        "auto_irrigation_safety_lock": False,
        "auto_irrigation_bootstrap_complete": True,
    }
    return coord


def _bind_irrigation_runtime_methods(target: object, *names: str) -> None:
    shared_names = {
        "_current_datetime",
        "_current_utc_datetime",
        "_current_date",
        "_current_snapshot",
        "_normalize_watering_cause",
        "_round_runtime_mm",
        "_build_execution_plan_metrics",
        "_build_execution_reconciliation",
        "_detect_execution_anomalies",
    }
    for name in set(names) | shared_names:
        method = getattr(coordinator_mod.GazonIntelligentCoordinator, name)
        if name in {"_round_runtime_mm", "_normalize_watering_cause"}:
            setattr(target, name, method)
        else:
            setattr(target, name, method.__get__(target, type(target)))


def _build_runtime_ready_coordinator(
    *,
    plan_attrs: dict[str, object] | None = None,
    service_handler=None,
) -> object:
    coord = _build_coordinator()
    coord.brain.history = []
    coord.brain.mode = "Normal"
    coord.brain.date_action = None
    coord.memory = {
        "auto_irrigation_enabled": True,
        "auto_irrigation_user_confirmed": True,
    }
    coord.data = {
        "objectif_mm": float((plan_attrs or {}).get("objective_mm") or 1.5),
        "watering_passages": int((plan_attrs or {}).get("passages") or 1),
        "watering_pause_minutes": int((plan_attrs or {}).get("pause_between_passages_minutes") or 0),
    }
    coord._async_save_state = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    coord.async_record_user_action = AsyncMock()
    coord.async_record_watering = AsyncMock()
    coord._auto_irrigation_task = None
    coord._auto_irrigation_scheduler_task = None
    events: list[tuple[str, dict[str, object]]] = []
    service_calls: list[tuple[str, str, dict[str, object]]] = []

    async def _async_call(domain: str, service: str, data: dict[str, object], blocking: bool = True):
        service_calls.append((domain, service, dict(data)))
        if service_handler is not None:
            result = service_handler(domain, service, data, blocking)
            if asyncio.iscoroutine(result):
                return await result
            return result
        return None

    states: dict[str, _FakeState] = {}
    if plan_attrs is not None:
        states["sensor.gazon_intelligent_plan_arrosage"] = _FakeState(
            str(plan_attrs.get("total_duration_min") or "0"),
            datetime.now(timezone.utc),
            dict(plan_attrs),
        )
    coord.hass = types.SimpleNamespace(
        services=types.SimpleNamespace(async_call=_async_call),
        async_create_task=lambda coro, name=None: asyncio.create_task(coro),
        bus=types.SimpleNamespace(
            async_fire=lambda event, payload=None: events.append((event, dict(payload or {})))
        ),
        states=_FakeStates(states),
    )
    coord._events = events
    coord._service_calls = service_calls
    return coord


def _build_update_data_coordinator(*, weather_temperature: float | None) -> object:
    """Coordinator prêt à exécuter `_async_update_data`, avec température pilotable.

    `auto_irrigation_bootstrap_complete` est mis à False au départ pour observer son
    armement par le cycle. `fenetre_optimale = "attendre"` isole l'armement (aucun
    lancement réel d'arrosage déclenché).
    """
    coordinator = _build_coordinator()
    coordinator._loaded = True
    coordinator._auto_irrigation_task = None
    coordinator._auto_irrigation_scheduler_task = None
    coordinator._runtime_state["auto_irrigation_bootstrap_complete"] = False

    async def _load_state():
        return None

    class _Brain:
        last_result = None
        memory = {}

        def compute_snapshot(self, **kwargs):  # noqa: ARG002
            return {
                "mode": "Normal",
                "phase_active": "Normal",
                "objectif_mm": 5.0,
                "tonte_autorisee": True,
                "tonte_statut": "autorisee",
                "arrosage_recommande": True,
                "type_arrosage": "auto",
                "fenetre_optimale": "attendre",
                "conseil_principal": "ok",
                "action_recommandee": "ok",
                "action_a_eviter": "ok",
                "niveau_action": "surveiller",
                "risque_gazon": "faible",
                "phase_dominante": "Normal",
                "phase_dominante_source": "historique",
                "sous_phase": "Normal",
                "sous_phase_detail": "Normal",
                "sous_phase_age_days": 1,
                "sous_phase_progression": "early",
            }

    coordinator._async_load_state = _load_state
    coordinator.brain = _Brain()
    coordinator.history = []
    coordinator._get_conf = lambda key: {
        "capteur_temperature": "sensor.temperature",
        "type_sol": "limoneux",
    }.get(key)
    coordinator._get_float_state = lambda entity_id: None
    coordinator._get_weather_profile = lambda entity_id: {  # noqa: ARG005
        "weather_temperature": weather_temperature,
        "weather_apparent_temperature": weather_temperature,
        "weather_humidity": 55.0,
    }

    async def _forecast_summary(entity_id):  # noqa: ARG001
        return {}

    async def _save_state():
        return None

    coordinator._get_weather_forecast_summary = _forecast_summary
    coordinator._estimate_rosee = lambda weather_profile, temperature, humidite: 0.0  # noqa: ARG005
    coordinator._get_float_conf = lambda key, default: default  # noqa: ARG005
    coordinator._async_save_state = _save_state
    return coordinator


class WateringSessionMonitoringTests(unittest.TestCase):
    def test_get_conf_prefers_local_option_over_shared_state(self) -> None:
        coordinator = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coordinator.entry = _FakeEntry(
            data={"capteur_temperature": "sensor.temp_data"},
            options={"capteur_temperature": "sensor.temp_locale"},
        )
        coordinator.shared_state = _FakeSharedState(
            {"capteur_temperature": "sensor.temp_partagee"}
        )

        value = coordinator_mod.GazonIntelligentCoordinator._get_conf(
            coordinator,
            "capteur_temperature",
        )

        self.assertEqual(value, "sensor.temp_locale")

    def test_get_conf_uses_shared_state_as_fallback_before_entry_data(self) -> None:
        coordinator = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coordinator.entry = _FakeEntry(
            data={"entite_meteo": "weather.data"},
            options={},
        )
        coordinator.shared_state = _FakeSharedState({"entite_meteo": "weather.partagee"})

        value = coordinator_mod.GazonIntelligentCoordinator._get_conf(
            coordinator,
            "entite_meteo",
        )

        self.assertEqual(value, "weather.partagee")

    def test_get_conf_falls_back_to_entry_data_then_default(self) -> None:
        coordinator = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coordinator.entry = _FakeEntry(
            data={"capteur_temperature": "sensor.temp_data"},
            options={},
        )
        coordinator.shared_state = _FakeSharedState({})

        self.assertEqual(
            coordinator_mod.GazonIntelligentCoordinator._get_conf(
                coordinator,
                "capteur_temperature",
            ),
            "sensor.temp_data",
        )
        self.assertEqual(
            coordinator_mod.GazonIntelligentCoordinator._get_conf(coordinator, "type_sol"),
            "limoneux",
        )

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

    def test_trailing_off_after_auto_cycle_is_not_double_counted(self) -> None:
        # Régression : le OFF du dernier passage d'un cycle auto arrive juste APRÈS la
        # levée de la garde. Son segment a démarré pendant la fenêtre gelée → il doit
        # être ignoré (sinon doublon `zone_session`).
        coordinator = _build_coordinator()
        coordinator.hass = _FakeHass(states=_FakeStates({}))
        passage_start = datetime(2026, 6, 17, 2, 51, 52, tzinfo=timezone.utc)
        cycle_end = datetime(2026, 6, 17, 2, 57, 42, tzinfo=timezone.utc)
        # Le cycle piloté vient de finir : garde relâchée, instant de reprise mémorisé.
        coordinator._zone_tracking_suspended = 0
        coordinator._zone_tracking_resumed_at = cycle_end

        event = types.SimpleNamespace(
            data={
                "entity_id": "switch.zone_1",
                "old_state": _FakeState("on", passage_start),
                "new_state": _FakeState("off", cycle_end + timedelta(milliseconds=200)),
            }
        )
        coordinator._handle_zone_state_change(event)

        # Aucune session passive fantôme ne doit avoir été créée.
        self.assertIsNone(coordinator._watering_session)

    def test_off_started_after_resume_is_tracked_normally(self) -> None:
        # Un arrosage manuel/externe qui démarre APRÈS la reprise du moniteur reste tracé.
        coordinator = _build_coordinator()
        coordinator.hass = _FakeHass(states=_FakeStates({}))
        cycle_end = datetime(2026, 6, 17, 2, 57, 42, tzinfo=timezone.utc)
        coordinator._zone_tracking_suspended = 0
        coordinator._zone_tracking_resumed_at = cycle_end

        on_at = cycle_end + timedelta(minutes=5)
        off_at = on_at + timedelta(minutes=4)
        coordinator._handle_zone_state_change(
            types.SimpleNamespace(
                data={
                    "entity_id": "switch.zone_1",
                    "old_state": _FakeState("off", cycle_end),
                    "new_state": _FakeState("on", on_at),
                }
            )
        )
        self.assertIsNotNone(coordinator._watering_session)

        coordinator._handle_zone_state_change(
            types.SimpleNamespace(
                data={
                    "entity_id": "switch.zone_1",
                    "old_state": _FakeState("on", on_at),
                    "new_state": _FakeState("off", off_at),
                }
            )
        )

        payload = coordinator._build_watering_session_payload()
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(len(payload["zones"]), 1)
        self.assertEqual(payload["zones"][0]["zone"], "switch.zone_1")

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
        self.assertEqual(payload["mm_scope"], "global_surface")
        self.assertEqual(payload["mm_interpretation"], "surface_uniform")
        self.assertEqual(payload["objectif_mm"], 2.0)
        self.assertEqual(payload["objective_mm"], 2.0)
        self.assertEqual(payload["total_mm"], 2.0)
        self.assertEqual(payload["session_total_mm"], 2.0)
        self.assertEqual(payload["zones_total_mm"], 4.0)
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
                    "sensor.gazon_intelligent_plan_d_arrosage": _FakeState(
                        "32.0",
                        start,
                        {
                            "objective_mm": 1.6,
                            "total_duration_min": 32.0,
                            "zone_count": 2,
                            "passages": 2,
                            "pause_between_passages_minutes": 25,
                            "zones": [
                                {"zone": "switch.zone_1", "duration_seconds": 60.0},
                                {"zone": "switch.zone_2", "duration_seconds": 150.0},
                            ],
                        },
                    ),
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
        self.assertGreater(coordinator._watering_session.get("planned_total_seconds", 0.0), 0.0)

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
        coordinator._auto_irrigation_task = None
        coordinator._auto_irrigation_scheduler_task = None
        async def _load_state():
            return None
        coordinator._async_load_state = _load_state
        captured: dict[str, object] = {}

        class _Brain:
            last_result = None
            memory = {}

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
                "date": coordinator._current_date().isoformat(),
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

        self.assertEqual(captured["retour_arrosage"], 2.0)
        self.assertEqual(result["objectif_mm"], 1.2)
        self.assertEqual(result["phase_dominante"], "Normal")

    def test_update_data_keeps_zero_temperature_from_weather_profile(self) -> None:
        coordinator = _build_coordinator()
        coordinator._loaded = True
        coordinator._auto_irrigation_task = None
        coordinator._auto_irrigation_scheduler_task = None

        async def _load_state():
            return None

        coordinator._async_load_state = _load_state
        captured: dict[str, object] = {}

        class _Brain:
            last_result = None
            memory = {}

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
        coordinator.history = []
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
            "sensor.temperature": None,
            "sensor.etp": 4.0,
            "sensor.humidity": 55.0,
            "sensor.soil_humidity": 30.0,
            "sensor.wind": 5.0,
            "sensor.dew": 0.0,
            "sensor.height": 10.0,
            "sensor.return_watering": 0.0,
        }.get(entity_id)
        coordinator._get_weather_profile = lambda entity_id: {
            "weather_temperature": 0.0,
            "weather_apparent_temperature": 24.0,
            "weather_humidity": 55.0,
            "weather_wind_speed": 5.0,
            "weather_dew_point": 0.0,
            "weather_condition": "clear",
        }

        async def _forecast_summary(entity_id):  # noqa: ARG001
            return {}

        async def _save_state():
            return None

        coordinator._get_weather_forecast_summary = _forecast_summary
        coordinator._estimate_rosee = lambda weather_profile, temperature, humidite: 0.0  # noqa: ARG001
        coordinator._get_float_conf = lambda key, default: default
        coordinator._async_save_state = _save_state

        result = asyncio.run(coordinator._async_update_data())

        self.assertEqual(captured["temperature"], 0.0)
        self.assertEqual(captured["temperature_source"], "weather")
        self.assertEqual(result["objectif_mm"], 1.2)

    def test_update_data_arms_auto_irrigation_after_healthy_snapshot(self) -> None:
        # Premier cycle sain (température + objectif présents) → le startup_guard se lève.
        coordinator = _build_update_data_coordinator(weather_temperature=18.0)
        self.assertFalse(coordinator._runtime_state["auto_irrigation_bootstrap_complete"])

        asyncio.run(coordinator._async_update_data())

        self.assertTrue(coordinator._runtime_state["auto_irrigation_bootstrap_complete"])
        _, reason = coordinator._should_launch_auto_irrigation(coordinator._latest_full_snapshot)
        self.assertNotEqual(reason, "startup_guard")

    def test_update_data_keeps_startup_guard_when_sensors_unavailable(self) -> None:
        # Capteurs encore unavailable au démarrage (température None) → on n'arme PAS.
        coordinator = _build_update_data_coordinator(weather_temperature=None)

        asyncio.run(coordinator._async_update_data())

        self.assertFalse(coordinator._runtime_state["auto_irrigation_bootstrap_complete"])
        _, reason = coordinator._should_launch_auto_irrigation(coordinator._latest_full_snapshot)
        self.assertEqual(reason, "startup_guard")

    def test_async_set_normal_clears_safety_lock(self) -> None:
        # « Retour au mode normal » (bouton/service) lève le verrou de sécurité.
        coordinator = _build_coordinator()
        coordinator._runtime_state["auto_irrigation_safety_lock"] = True
        coordinator.brain.set_normal = lambda: None
        coordinator._async_save_state = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()

        asyncio.run(coordinator.async_set_normal())

        self.assertFalse(coordinator._runtime_state["auto_irrigation_safety_lock"])

    def test_update_data_exposes_startup_guard_block_reason(self) -> None:
        # Capteurs unavailable → non armé → la raison de blocage exposée est "startup_guard".
        coordinator = _build_update_data_coordinator(weather_temperature=None)
        result = asyncio.run(coordinator._async_update_data())
        self.assertEqual(result.get("auto_irrigation_block_reason"), "startup_guard")
        self.assertFalse(result.get("auto_irrigation_safety_lock"))

    def test_recent_watering_block_ignores_yesterday_session_total(self) -> None:
        coordinator = _build_coordinator()
        today = coordinator._current_date()
        coordinator.history = [
            {
                "type": "arrosage",
                "date": (today - timedelta(days=1)).isoformat(),
                "total_mm": 1.5,
            }
        ]

        self.assertFalse(coordinator._recent_watering_block_active(0.5))

    def test_auto_irrigation_is_blocked_when_watering_session_active(self) -> None:
        coordinator = _build_coordinator()
        coordinator._watering_session = {
            "active_zones": {"switch.zone_1": datetime.now(timezone.utc)},
        }

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            {
                "objectif_mm": 0.5,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": True,
                "fenetre_optimale": "ce_matin",
                "watering_target_date": coordinator._current_date().isoformat(),
                "watering_window_start_minute": 0,
                "watering_window_end_minute": 1440,
                "watering_evening_start_minute": 1080,
                "watering_evening_end_minute": 1260,
                "watering_evening_allowed": True,
            }
        )

        self.assertFalse(should_launch)
        self.assertEqual(reason, "watering_in_progress")

    def test_auto_irrigation_is_blocked_before_bootstrap_completes(self) -> None:
        coordinator = _build_coordinator()
        coordinator._runtime_state["auto_irrigation_bootstrap_complete"] = False

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            {
                "objectif_mm": 1.0,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": True,
                "fenetre_optimale": "maintenant",
                "watering_target_date": coordinator._current_date().isoformat(),
            }
        )

        self.assertFalse(should_launch)
        self.assertEqual(reason, "startup_guard")

    def test_auto_irrigation_requires_explicit_user_confirmation(self) -> None:
        coordinator = _build_coordinator()
        coordinator.memory = {
            "auto_irrigation_enabled": True,
            "auto_irrigation_user_confirmed": False,
        }

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            {
                "objectif_mm": 1.0,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": True,
                "fenetre_optimale": "maintenant",
                "watering_target_date": coordinator._current_date().isoformat(),
            }
        )

        self.assertFalse(should_launch)
        self.assertEqual(reason, "user_confirmation_required")

    def test_post_application_auto_ready_bypasses_standard_window_checks(self) -> None:
        coordinator = _build_coordinator()
        today = coordinator._current_date()

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            {
                "objectif_mm": 1.2,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": True,
                "fenetre_optimale": "attendre",
                "type_arrosage": "application_technique_auto",
                "application_post_watering_status": "autorise",
                "watering_target_date": today.isoformat(),
                "watering_window_start_minute": 240,
                "watering_window_end_minute": 600,
                "watering_evening_start_minute": 1080,
                "watering_evening_end_minute": 1260,
                "watering_evening_allowed": False,
            }
        )

        self.assertTrue(should_launch)
        self.assertEqual(reason, "post_application_ready")

    def test_post_application_auto_ready_ignores_recent_watering_guard(self) -> None:
        coordinator = _build_coordinator()
        today = coordinator._current_date()
        coordinator.history = [
            {
                "type": "arrosage",
                "date": today.isoformat(),
                "total_mm": 1.5,
            }
        ]

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            {
                "objectif_mm": 0.8,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": True,
                "fenetre_optimale": "attendre",
                "type_arrosage": "application_technique_auto",
                "application_post_watering_status": "autorise",
                "watering_target_date": today.isoformat(),
                "watering_window_start_minute": 240,
                "watering_window_end_minute": 600,
                "watering_evening_start_minute": 1080,
                "watering_evening_end_minute": 1260,
                "watering_evening_allowed": False,
            }
        )

        self.assertTrue(should_launch)
        self.assertEqual(reason, "post_application_ready")

    def test_post_application_manual_ready_never_auto_launches(self) -> None:
        coordinator = _build_coordinator()
        today = coordinator._current_date()

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            {
                "objectif_mm": 1.2,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": False,
                "fenetre_optimale": "maintenant",
                "type_arrosage": "application_technique",
                "application_post_watering_status": "autorise",
                "watering_target_date": today.isoformat(),
                "watering_window_start_minute": 1,
                "watering_window_end_minute": 1,
            }
        )

        self.assertFalse(should_launch)
        self.assertEqual(reason, "auto_not_allowed")

    def test_auto_irrigation_never_launches_when_snapshot_is_blocked(self) -> None:
        coordinator = _build_coordinator()

        for updates, expected_reason in (
            ({"type_arrosage": "bloque"}, "irrigation_blocked"),
            ({"irrigation_blocked": True}, "irrigation_blocked"),
            ({"watering_blocked_by_mower": True}, "irrigation_blocked"),
            ({"block_reason": "pluie_prevue_suffisante"}, "irrigation_blocked"),
            ({"arrosage_auto_autorise": False}, "auto_not_allowed"),
            ({"irrigation_execution_allowed": False}, "execution_not_allowed"),
        ):
            snapshot = {
                "objectif_mm": 1.2,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": True,
                "irrigation_execution_allowed": True,
                "fenetre_optimale": "maintenant",
                "type_arrosage": "auto",
                "watering_target_date": coordinator._current_date().isoformat(),
                "watering_window_start_minute": 0,
                "watering_window_end_minute": 1440,
            }
            snapshot.update(updates)

            should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)

            self.assertFalse(should_launch)
            self.assertEqual(reason, expected_reason)

    def test_post_application_auto_ready_is_rejected_while_session_is_active(self) -> None:
        coordinator = _build_coordinator()
        today = coordinator._current_date()
        coordinator._watering_session = {
            "active_zones": {"switch.zone_1": datetime.now(timezone.utc)}
        }

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            {
                "objectif_mm": 1.2,
                "arrosage_recommande": True,
                "arrosage_auto_autorise": True,
                "fenetre_optimale": "attendre",
                "type_arrosage": "application_technique_auto",
                "application_post_watering_status": "autorise",
                "watering_target_date": today.isoformat(),
            }
        )

        self.assertFalse(should_launch)
        self.assertEqual(reason, "watering_in_progress")

    def test_auto_irrigation_service_refuses_when_watering_session_active(self) -> None:
        coordinator = _build_coordinator()
        coordinator._watering_session = {
            "active_zones": {"switch.zone_1": datetime.now(timezone.utc)},
        }

        with self.assertRaises(coordinator_mod.HomeAssistantError):
            asyncio.run(
                coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    0.5,
                )
            )

    def test_recent_watering_block_keeps_same_day_session(self) -> None:
        coordinator = _build_coordinator()
        today = coordinator._current_date()
        coordinator.history = [
            {
                "type": "arrosage",
                "date": today.isoformat(),
                "total_mm": 1.5,
            }
        ]

        self.assertTrue(coordinator._recent_watering_block_active(0.5))

    def test_recent_watering_block_ignores_yesterday_timestamp(self) -> None:
        coordinator = _build_coordinator()
        yesterday = coordinator._current_date() - timedelta(days=1)
        coordinator.history = [
            {
                "type": "arrosage",
                "date": yesterday.isoformat(),
                "recorded_at": f"{yesterday.isoformat()}T23:30:00+00:00",
                "total_mm": 1.5,
            }
        ]

        self.assertFalse(coordinator._recent_watering_block_active(0.5))

    def test_auto_irrigation_is_blocked_when_global_switch_is_off(self) -> None:
        coordinator = _build_coordinator()
        coordinator.memory = {
            "auto_irrigation_enabled": False,
            "auto_irrigation_user_confirmed": True,
        }
        coordinator._auto_irrigation_task = None
        coordinator.hass = _FakeHass(states=_FakeStates({}))

        with self.assertRaises(coordinator_mod.HomeAssistantError):
            asyncio.run(
                coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.0,
                    source="auto_irrigation",
                )
            )

    def test_auto_irrigation_start_requires_explicit_user_confirmation(self) -> None:
        coordinator = _build_coordinator()
        coordinator.memory = {
            "auto_irrigation_enabled": True,
            "auto_irrigation_user_confirmed": False,
        }
        coordinator._auto_irrigation_task = None
        coordinator.hass = _FakeHass(states=_FakeStates({}))

        with self.assertRaises(coordinator_mod.HomeAssistantError) as err:
            asyncio.run(
                coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.0,
                    source="auto_irrigation",
                )
            )
        self.assertIn("explicitement", str(err.exception))

    def test_manual_irrigation_service_launches_real_sequence(self) -> None:
        class _ManualIrrigationCoordinator:
            def __init__(self) -> None:
                self.entry = _FakeEntry()
                self.entry.data.update(
                    {
                        "zone_1": "switch.zone_1",
                        "zone_2": "switch.zone_2",
                        "debit_zone_1": 60.0,
                        "debit_zone_2": 30.0,
                    }
                )
                self.memory = {"auto_irrigation_enabled": False}
                self.data = {"objectif_mm": 1.0}
                self.history = []
                self.mode = "Sursemis"
                self.date_action = None
                self._auto_irrigation_task = None
                self._auto_irrigation_scheduler_task = None
                self._zone_tracking_suspended = 0
                self._runtime_state = {
                    "active_irrigation_session": None,
                    "last_irrigation_execution": None,
                    "last_auto_irrigation_reason": None,
                    "auto_irrigation_safety_lock": False,
                }
                self._recorded_actions: list[dict[str, object]] = []
                self._events: list[tuple[str, dict[str, object]]] = []
                self._watering_calls: list[dict[str, object]] = []

                async def _noop_async_call(*args, **kwargs):
                    return None

                self.hass = types.SimpleNamespace(
                    services=types.SimpleNamespace(async_call=_noop_async_call),
                    async_create_task=lambda coro, name=None: asyncio.create_task(coro),
                    bus=types.SimpleNamespace(
                        async_fire=lambda event, payload=None: self._events.append(
                            (event, dict(payload or {}))
                        )
                    )
                )
                self.async_start_auto_irrigation = (
                    coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation.__get__(
                        self, type(self)
                    )
                )
                _bind_irrigation_runtime_methods(
                    self,
                    "_ensure_irrigation_runtime_bootstrap",
                    "_serialize_runtime_value",
                    "_auto_irrigation_safety_lock_active",
                    "_get_active_irrigation_session",
                    "_set_active_irrigation_session",
                    "_set_last_auto_irrigation_reason",
                    "_set_last_irrigation_execution",
                    "_persist_runtime_state",
                    "_emit_irrigation_event",
                    "_build_runtime_payload_for_event",
                    "_new_runtime_id",
                    "_build_pending_zone_segments",
                    "_build_zone_execution_record",
                    "_build_active_irrigation_session",
                    "_persist_execution_snapshot",
                    "_safe_turn_off_zone",
                    "_get_canonical_watering_plan",
                    "_execute_canonical_watering_plan",
                )

            def _build_watering_plan_summary_for_user_action(
                self,
                objectif_mm: float | None = None,
                plan: dict[str, object] | None = None,
            ) -> dict[str, object]:
                if plan is not None:
                    return dict(plan)
                return {
                    "objective_mm": float(objectif_mm or 0.0),
                    "zones": [
                        {"zone": "switch.zone_1", "duration_seconds": 60},
                        {"zone": "switch.zone_2", "duration_seconds": 120},
                    ],
                    "zone_count": 2,
                    "fractionation": False,
                    "passages": 1,
                    "pause_between_passages_minutes": 0,
                    "plan_type": "multi_zone",
                }

            async def async_record_user_action(self, **kwargs):
                self._recorded_actions.append(kwargs)
                return kwargs

            async def async_record_watering(self, *args, **kwargs):
                self._watering_calls.append({"args": args, "kwargs": kwargs})

            def _iter_zones_with_rate(self):
                return iter(
                    [
                        ("switch.zone_1", 60.0 / 60.0),
                        ("switch.zone_2", 30.0 / 60.0),
                    ]
                )

            def _watering_session_active(self):
                return False

            def _clear_watering_session(self):
                return None

        coordinator = _ManualIrrigationCoordinator()

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_manual_irrigation(
                    coordinator,
                    1.0,
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        self.assertEqual(len(coordinator._watering_calls), 1)
        watering_call = coordinator._watering_calls[0]
        self.assertEqual(watering_call["kwargs"]["source"], "manual_irrigation")
        self.assertEqual(watering_call["kwargs"]["objectif_mm"], 1.0)
        self.assertEqual(len(watering_call["kwargs"]["zones"]), 2)
        self.assertEqual(coordinator._recorded_actions[0]["state"], "en_attente")
        self.assertEqual(coordinator._recorded_actions[-1]["state"], "ok")
        self.assertIn(
            (
                "gazon_intelligent_manual_irrigation_requested",
                {
                    "objectif_mm": 1.0,
                    "mode": "Sursemis",
                    "date_action": None,
                    "source": "manual_irrigation",
                },
            ),
            coordinator._events,
        )

    def test_auto_scheduler_launch_records_pending_then_final_state(self) -> None:
        class _AutoSchedulerCoordinator:
            def __init__(self) -> None:
                self.entry = _FakeEntry()
                self.memory = {"auto_irrigation_enabled": True}
                self.data = {}
                self.history = []
                self._auto_irrigation_task = None
                self._auto_irrigation_scheduler_task = None
                self._runtime_state = {
                    "active_irrigation_session": None,
                    "last_irrigation_execution": None,
                    "last_auto_irrigation_reason": None,
                    "auto_irrigation_safety_lock": False,
                }
                self._recorded_actions: list[dict[str, object]] = []
                self._calls: list[tuple[float | None, str | None, str, str | None, dict[str, object] | None]] = []
                self.hass = types.SimpleNamespace(
                    async_create_task=lambda coro, name=None: asyncio.create_task(coro)
                )
                _bind_irrigation_runtime_methods(
                    self,
                    "_ensure_irrigation_runtime_bootstrap",
                    "_serialize_runtime_value",
                    "_set_last_auto_irrigation_reason",
                    "_set_last_irrigation_execution",
                    "_persist_runtime_state",
                    "_get_canonical_watering_plan",
                    "_emit_irrigation_event",
                )

            def _should_launch_auto_irrigation(self, snapshot: dict[str, object]):
                return True, "ready"

            def _plan_arrosage_entity_id(self) -> str:
                return "sensor.gazon_intelligent_plan_arrosage"

            def _build_watering_plan_from_state(
                self, plan_arrosage_entity_id: str
            ) -> dict[str, object] | None:
                return {
                    "objective_mm": 1.5,
                    "zones": [{"zone": "switch.zone_1", "duration_seconds": 180}],
                    "zone_count": 1,
                    "fractionation": False,
                    "passages": 1,
                    "pause_between_passages_minutes": 0,
                    "plan_type": "single_zone",
                }

            def _iter_zones_with_rate(self):
                return iter([("switch.zone_1", 60.0 / 60.0)])

            def _build_watering_plan_summary_for_user_action(
                self,
                objectif_mm: float | None = None,
                plan: dict[str, object] | None = None,
            ) -> dict[str, object]:
                if plan is not None:
                    return dict(plan)
                return {
                    "objective_mm": float(objectif_mm or 0.0),
                    "zones": [{"zone": "switch.zone_1", "duration_seconds": 180}],
                    "zone_count": 1,
                    "fractionation": False,
                    "passages": 1,
                    "pause_between_passages_minutes": 0,
                    "plan_type": "single_zone",
                }

            async def async_record_user_action(self, **kwargs):
                self._recorded_actions.append(kwargs)
                return kwargs

            async def async_start_auto_irrigation(
                self,
                objectif_mm,
                plan_arrosage_entity_id=None,
                source="auto_irrigation",
                watering_cause=None,
                user_action_context=None,
            ):
                self._calls.append((objectif_mm, plan_arrosage_entity_id, source, watering_cause, user_action_context))
                if isinstance(user_action_context, dict) and user_action_context.get("action"):
                    self._recorded_actions.append(
                        {
                            "action": user_action_context["action"],
                            "state": "ok",
                            "reason": user_action_context.get("success_reason"),
                            "plan_type": user_action_context.get("plan_type"),
                            "zone_count": user_action_context.get("zone_count"),
                            "passages": user_action_context.get("passages"),
                        }
                    )

        coordinator = _AutoSchedulerCoordinator()

        async def _run() -> None:
            await coordinator_mod.GazonIntelligentCoordinator._maybe_schedule_auto_irrigation(
                coordinator,
                {
                    "objectif_mm": 1.5,
                    "watering_evening_allowed": True,
                    "watering_window_start_min": 0,
                    "watering_window_end_min": 1440,
                    "watering_evening_window_start_min": 0,
                    "watering_evening_window_end_min": 1440,
                    "watering_current_minute": 10,
                    "watering_fenetre": "matin",
                },
            )
            task = coordinator._auto_irrigation_scheduler_task
            self.assertIsNotNone(task)
            assert task is not None
            await task

        asyncio.run(_run())

        self.assertEqual(
            coordinator._calls,
            [
                (
                    1.5,
                    "sensor.gazon_intelligent_plan_arrosage",
                    "auto_irrigation",
                    "hydrique",
                    {
                        "action": "Arrosage automatique",
                        "success_reason": "Arrosage automatique exécuté avec succès.",
                        "plan_type": "single_zone",
                        "zone_count": 1,
                        "passages": 1,
                    },
                )
            ],
        )
        self.assertGreaterEqual(len(coordinator._recorded_actions), 2)
        self.assertEqual(coordinator._recorded_actions[0]["state"], "en_attente")
        self.assertEqual(coordinator._recorded_actions[-1]["state"], "ok")
        self.assertEqual(
            coordinator._runtime_state["last_auto_irrigation_reason"]["reason"],
            "ready",
        )
        self.assertIsNone(coordinator._runtime_state["last_irrigation_execution"])

    def test_auto_scheduler_launch_records_refuse_on_immediate_failure(self) -> None:
        class _AutoSchedulerFailureCoordinator:
            def __init__(self) -> None:
                self.entry = _FakeEntry()
                self.memory = {"auto_irrigation_enabled": True}
                self.data = {}
                self.history = []
                self._auto_irrigation_task = None
                self._auto_irrigation_scheduler_task = None
                self._runtime_state = {
                    "active_irrigation_session": None,
                    "last_irrigation_execution": None,
                    "last_auto_irrigation_reason": None,
                    "auto_irrigation_safety_lock": False,
                }
                self._recorded_actions: list[dict[str, object]] = []
                self._calls: list[tuple[float | None, str | None, str, str | None, dict[str, object] | None]] = []
                self.hass = types.SimpleNamespace(
                    async_create_task=lambda coro, name=None: asyncio.create_task(coro)
                )
                _bind_irrigation_runtime_methods(
                    self,
                    "_ensure_irrigation_runtime_bootstrap",
                    "_serialize_runtime_value",
                    "_set_last_auto_irrigation_reason",
                    "_set_last_irrigation_execution",
                    "_persist_runtime_state",
                    "_get_canonical_watering_plan",
                    "_emit_irrigation_event",
                )

            def _should_launch_auto_irrigation(self, snapshot: dict[str, object]):
                return True, "ready"

            def _plan_arrosage_entity_id(self) -> str:
                return "sensor.gazon_intelligent_plan_arrosage"

            def _build_watering_plan_from_state(
                self, plan_arrosage_entity_id: str
            ) -> dict[str, object] | None:
                return {
                    "objective_mm": 1.5,
                    "zones": [{"zone": "switch.zone_1", "duration_seconds": 180}],
                    "zone_count": 1,
                    "fractionation": False,
                    "passages": 1,
                    "pause_between_passages_minutes": 0,
                    "plan_type": "single_zone",
                }

            def _iter_zones_with_rate(self):
                return iter([("switch.zone_1", 60.0 / 60.0)])

            def _build_watering_plan_summary_for_user_action(
                self,
                objectif_mm: float | None = None,
                plan: dict[str, object] | None = None,
            ) -> dict[str, object]:
                if plan is not None:
                    return dict(plan)
                return {
                    "objective_mm": float(objectif_mm or 0.0),
                    "zones": [{"zone": "switch.zone_1", "duration_seconds": 180}],
                    "zone_count": 1,
                    "fractionation": False,
                    "passages": 1,
                    "pause_between_passages_minutes": 0,
                    "plan_type": "single_zone",
                }

            async def async_record_user_action(self, **kwargs):
                self._recorded_actions.append(kwargs)
                return kwargs

            async def async_start_auto_irrigation(
                self,
                objectif_mm,
                plan_arrosage_entity_id=None,
                source="auto_irrigation",
                watering_cause=None,
                user_action_context=None,
            ):
                self._calls.append((objectif_mm, plan_arrosage_entity_id, source, watering_cause, user_action_context))
                raise coordinator_mod.HomeAssistantError("plan unavailable")

        coordinator = _AutoSchedulerFailureCoordinator()

        async def _run() -> None:
            await coordinator_mod.GazonIntelligentCoordinator._maybe_schedule_auto_irrigation(
                coordinator,
                {
                    "objectif_mm": 1.5,
                    "watering_evening_allowed": True,
                    "watering_window_start_min": 0,
                    "watering_window_end_min": 1440,
                    "watering_evening_window_start_min": 0,
                    "watering_evening_window_end_min": 1440,
                    "watering_current_minute": 10,
                    "watering_fenetre": "matin",
                },
            )
            task = coordinator._auto_irrigation_scheduler_task
            self.assertIsNotNone(task)
            assert task is not None
            await task

        asyncio.run(_run())

        self.assertEqual(
            coordinator._calls,
            [
                (
                    1.5,
                    "sensor.gazon_intelligent_plan_arrosage",
                    "auto_irrigation",
                    "hydrique",
                    {
                        "action": "Arrosage automatique",
                        "success_reason": "Arrosage automatique exécuté avec succès.",
                        "plan_type": "single_zone",
                        "zone_count": 1,
                        "passages": 1,
                    },
                )
            ],
        )
        self.assertGreaterEqual(len(coordinator._recorded_actions), 2)
        self.assertEqual(coordinator._recorded_actions[0]["state"], "en_attente")
        self.assertEqual(coordinator._recorded_actions[-1]["state"], "refuse")
        self.assertEqual(coordinator._recorded_actions[-1]["reason"], "plan unavailable")

    def test_semis_scheduler_waits_for_spacing_then_allows_launch(self) -> None:
        coordinator = _build_coordinator()
        snapshot = {
            "objectif_mm": 1.5,
            "objective_mm": 1.5,
            "arrosage_recommande": True,
            "arrosage_auto_autorise": True,
            "type_arrosage": "manuel_frequent",
            "fenetre_optimale": "matin",
            "watering_window_start_minute": 0,
            "watering_window_end_minute": 1440,
            "watering_evening_allowed": True,
            "watering_evening_start_minute": 0,
            "watering_evening_end_minute": 1440,
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.5,
            "daily_cycles_target": 3,
            "cycle_spacing_minutes": 90,
            "surface_moisture_target": "surface_moist",
            "surface_dryness_risk": "moderate",
            "runoff_risk": "low",
            "seeding_transition_ready": False,
        }
        coordinator.history = [
            {
                "type": "arrosage",
                "date": "2026-04-27",
                "recorded_at": "2026-04-27T10:00:00+00:00",
                "watering_strategy": "semis_frequent",
                "objective_scope": "surface_cycle",
                "watering_stage": "germination",
                "surface_cycle_mm": 1.5,
                "daily_cycles_target": 3,
                "cycle_spacing_minutes": 90,
                "objectif_mm": 1.5,
                "total_mm": 1.5,
                "session_total_mm": 1.5,
                "mm_scope": "surface_cycle",
                "mm_interpretation": "surface_cycle",
            }
        ]
        current = datetime(2026, 4, 27, 11, 0, tzinfo=timezone.utc)
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current
        coordinator._current_date = lambda: current.date()

        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "semis_cycle_pending")
        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        self.assertEqual(progress["state"], "waiting")
        self.assertEqual(progress["cycles_completed_today"], 1)
        self.assertEqual(progress["cycles_remaining_today"], 2)

        current = datetime(2026, 4, 27, 12, 5, tzinfo=timezone.utc)
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

        coordinator.history.extend(
            [
                {
                    "type": "arrosage",
                    "date": "2026-04-27",
                    "recorded_at": "2026-04-27T12:05:00+00:00",
                    "watering_strategy": "semis_frequent",
                    "objective_scope": "surface_cycle",
                    "watering_stage": "germination",
                    "surface_cycle_mm": 1.5,
                    "daily_cycles_target": 3,
                    "cycle_spacing_minutes": 90,
                    "objectif_mm": 1.5,
                    "total_mm": 1.5,
                    "session_total_mm": 1.5,
                    "mm_scope": "surface_cycle",
                    "mm_interpretation": "surface_cycle",
                },
                {
                    "type": "arrosage",
                    "date": "2026-04-27",
                    "recorded_at": "2026-04-27T14:05:00+00:00",
                    "watering_strategy": "semis_frequent",
                    "objective_scope": "surface_cycle",
                    "watering_stage": "germination",
                    "surface_cycle_mm": 1.5,
                    "daily_cycles_target": 3,
                    "cycle_spacing_minutes": 90,
                    "objectif_mm": 1.5,
                    "total_mm": 1.5,
                    "session_total_mm": 1.5,
                    "mm_scope": "surface_cycle",
                    "mm_interpretation": "surface_cycle",
                },
            ]
        )
        current = datetime(2026, 4, 27, 15, 0, tzinfo=timezone.utc)
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "semis_target_reached")

    def test_semis_cycle_progress_uses_local_display_time(self) -> None:
        coordinator = _build_coordinator()
        snapshot = {
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.5,
            "daily_cycles_target": 3,
            "cycle_spacing_minutes": 90,
            "objectif_mm": 1.5,
            "total_mm": 1.5,
            "session_total_mm": 1.5,
            "mm_scope": "surface_cycle",
            "mm_interpretation": "surface_cycle",
        }
        coordinator.history = [
            {
                "type": "arrosage",
                "date": "2026-04-27",
                "recorded_at": "2026-04-27T10:05:00+00:00",
                "watering_strategy": "semis_frequent",
                "objective_scope": "surface_cycle",
                "watering_stage": "germination",
                "surface_cycle_mm": 1.5,
                "daily_cycles_target": 3,
                "cycle_spacing_minutes": 90,
                "objectif_mm": 1.5,
                "total_mm": 1.5,
                "session_total_mm": 1.5,
                "mm_scope": "surface_cycle",
                "mm_interpretation": "surface_cycle",
            }
        ]
        current = datetime(2026, 4, 27, 13, 0, tzinfo=timezone(timedelta(hours=2)))
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current.astimezone(timezone.utc)
        coordinator._current_date = lambda: current.date()

        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        self.assertEqual(progress["state"], "waiting")
        self.assertEqual(progress["last_cycle_display"], "27/04/2026 à 12:05")
        self.assertEqual(progress["next_due_display"], "27/04/2026 à 13:35")

    def test_source_monitoring_refreshes_on_external_entity_change(self) -> None:
        coordinator = _build_coordinator()
        coordinator._unsub_source_listeners = []
        coordinator._source_refresh_task = None
        coordinator.hass = types.SimpleNamespace(
            async_create_task=lambda coro, name=None: asyncio.create_task(coro)
        )
        refresh_calls: list[str] = []

        async def _async_request_refresh():
            refresh_calls.append("refresh")

        coordinator.async_request_refresh = _async_request_refresh
        coordinator._get_conf = lambda key: {
            "entite_meteo": "weather.backyard",
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
        }.get(key)

        captured: dict[str, object] = {}
        old_track = coordinator_mod.async_track_state_change_event

        def _fake_track_state_change_event(hass, entity_ids, handler):  # noqa: ANN001
            captured["entity_ids"] = list(entity_ids)
            captured["handler"] = handler

            def _unsubscribe():
                captured["unsubscribed"] = True

            return _unsubscribe

        coordinator_mod.async_track_state_change_event = _fake_track_state_change_event
        try:
            async def _run() -> None:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_source_monitoring(coordinator)
                self.assertEqual(
                    set(captured["entity_ids"]),
                    {
                        "weather.backyard",
                        "sensor.pluie_24h",
                        "sensor.pluie_demain",
                        "sensor.temperature",
                        "sensor.etp",
                        "sensor.humidity",
                        "sensor.soil_humidity",
                        "sensor.wind",
                        "sensor.dew",
                        "sensor.height",
                        "sensor.return_watering",
                    },
                )
                handler = captured["handler"]
                assert callable(handler)
                handler(types.SimpleNamespace(data={"entity_id": "sensor.pluie_24h"}))
                task = coordinator._source_refresh_task
                self.assertIsNotNone(task)
                assert task is not None
                await task
                self.assertEqual(refresh_calls, ["refresh"])
                coordinator_mod.GazonIntelligentCoordinator._cancel_source_monitoring(coordinator)
                self.assertTrue(captured.get("unsubscribed"))

            asyncio.run(_run())
        finally:
            coordinator_mod.async_track_state_change_event = old_track

    def test_auto_irrigation_monitoring_triggers_internal_tick(self) -> None:
        coordinator = _build_coordinator()
        coordinator.data = {
            "objectif_mm": 1.5,
            "arrosage_recommande": True,
            "fenetre_optimale": "ce_matin",
            "watering_target_date": coordinator._current_date().isoformat(),
            "watering_window_start_minute": 0,
            "watering_window_end_minute": 1440,
            "watering_evening_start_minute": 0,
            "watering_evening_end_minute": 1440,
            "watering_evening_allowed": True,
        }
        coordinator._auto_irrigation_task = None
        coordinator._auto_irrigation_scheduler_task = None
        coordinator._auto_irrigation_monitor_task = None
        coordinator._unsub_auto_irrigation_monitor = None
        coordinator.memory = {"auto_irrigation_enabled": True}
        coordinator._should_launch_auto_irrigation = lambda snapshot: (True, "ready")
        captured: dict[str, object] = {}

        def _record_schedule(snapshot: dict[str, object]) -> None:
            captured["snapshot"] = dict(snapshot)

        coordinator._maybe_schedule_auto_irrigation = _record_schedule

        old_track = coordinator_mod.async_track_time_interval

        def _fake_track_time_interval(hass, handler, interval):  # noqa: ANN001
            captured["interval"] = interval
            captured["handler"] = handler

            def _unsubscribe():
                captured["unsubscribed"] = True

            return _unsubscribe

        coordinator_mod.async_track_time_interval = _fake_track_time_interval
        coordinator.hass = types.SimpleNamespace(
            async_create_task=lambda coro, name=None: asyncio.create_task(coro)
        )
        try:
            async def _run() -> None:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation_monitoring(coordinator)
                self.assertEqual(captured["interval"], coordinator_mod.AUTO_IRRIGATION_CHECK_INTERVAL)
                handler = captured["handler"]
                assert callable(handler)
                handler(datetime.now(timezone.utc))
                task = coordinator._auto_irrigation_monitor_task
                self.assertIsNotNone(task)
                assert task is not None
                await task
                self.assertEqual(captured["snapshot"]["objectif_mm"], 1.5)
                self.assertTrue(captured.get("snapshot"))
                coordinator_mod.GazonIntelligentCoordinator._cancel_auto_irrigation_monitoring(coordinator)
                self.assertTrue(captured.get("unsubscribed"))

            asyncio.run(_run())
        finally:
            coordinator_mod.async_track_time_interval = old_track

    def test_current_snapshot_prefers_internal_full_snapshot_over_public_data(self) -> None:
        coordinator = _build_coordinator()
        coordinator.data = {
            "objectif_mm": 5.0,
            "arrosage_recommande": True,
            "fenetre_optimale": "maintenant",
            "type_arrosage": "application_technique_auto",
            "application_post_watering_status": "autorise",
        }
        coordinator._latest_full_snapshot = {
            "objectif_mm": 5.0,
            "arrosage_recommande": True,
            "fenetre_optimale": "maintenant",
            "type_arrosage": "application_technique_auto",
            "application_post_watering_status": "autorise",
            "arrosage_auto_autorise": True,
            "watering_window_start_minute": 240,
            "watering_window_end_minute": 600,
            "watering_evening_start_minute": 1080,
            "watering_evening_end_minute": 1260,
            "watering_evening_allowed": False,
        }

        snapshot = coordinator._current_snapshot()

        self.assertTrue(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["watering_window_start_minute"], 240)

    def test_application_irrigation_blocks_unknown_application_type(self) -> None:
        class _UnknownApplicationCoordinator:
            def __init__(self) -> None:
                self.history = [
                    {
                        "type": "Traitement",
                        "date": "2026-03-18",
                        "declared_at": "2026-03-18T08:00:00+00:00",
                        "produit": "Produit inconnu",
                        "application_type": "autre",
                        "application_requires_watering_after": True,
                        "application_post_watering_mm": 1.0,
                        "application_irrigation_block_hours": 12.0,
                        "application_irrigation_delay_minutes": 0.0,
                        "application_irrigation_mode": "auto",
                    }
                ]
                self._recorded_actions: list[dict[str, object]] = []

            def _build_watering_plan_summary_for_user_action(
                self,
                objectif_mm: float | None = None,
                plan: dict[str, object] | None = None,
            ) -> dict[str, object]:
                if plan is not None:
                    return dict(plan)
                return {
                    "objective_mm": float(objectif_mm or 0.0),
                    "zones": [],
                    "zone_count": 0,
                    "fractionation": False,
                    "passages": 1,
                    "pause_between_passages_minutes": 0,
                    "plan_type": "no_plan",
                }

            async def async_record_user_action(self, **kwargs):
                self._recorded_actions.append(kwargs)
                return kwargs

        coordinator = _UnknownApplicationCoordinator()

        with self.assertRaises(coordinator_mod.HomeAssistantError):
            asyncio.run(
                coordinator_mod.GazonIntelligentCoordinator.async_start_application_irrigation(
                    coordinator
                )
            )

        self.assertEqual(coordinator._recorded_actions[-1]["state"], "refuse")
        self.assertIn("type d'application est inconnu", coordinator._recorded_actions[-1]["reason"])

    def test_plan_execution_persists_recorded_watering(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            1.5,
            [("switch.zone_1", 60.0), ("switch.zone_2", 30.0)],
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.5,
                    plan_arrosage_entity_id="sensor.gazon_intelligent_plan_arrosage",
                    source="auto_irrigation",
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        coordinator.async_record_watering.assert_awaited_once()
        call = coordinator.async_record_watering.await_args
        self.assertEqual(call.kwargs["source"], "auto_irrigation")
        self.assertEqual(len(call.kwargs["zones"]), 2)
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(execution["strategy"], "plan")
        self.assertEqual(execution["completion_status"], "completed")
        self.assertEqual(execution["execution_confidence"], "high")
        self.assertEqual(execution["reconciliation"]["planned_mm"], 3.0)
        self.assertEqual(execution["reconciliation"]["executed_mm"], 3.0)
        self.assertEqual(execution["reconciliation"]["detected_mm"], 3.0)
        self.assertEqual(execution["execution_anomalies"], [])

    def test_active_irrigation_session_includes_live_progress_metadata(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            1.5,
            [("switch.zone_1", 60.0)],
            passages=2,
            pause_minutes=25,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="auto_irrigation",
            strategy="plan",
        )
        self.assertEqual(session["planned_total_seconds"], float(plan.total_duration_s))
        self.assertIsInstance(session["started_at"], datetime)
        self.assertEqual(session["last_activity_at"], session["started_at"])
        self.assertEqual(session["watering_cause"], "hydrique")

    def test_fractionated_execution_splits_zone_duration_across_passages(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            1.5,
            [("switch.zone_1", 60.0)],
            passages=2,
            pause_minutes=25,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.5,
                    plan_arrosage_entity_id="sensor.gazon_intelligent_plan_arrosage",
                    source="auto_irrigation",
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(len(execution["zones_done"]), 2)
        self.assertEqual(execution["zones_done"][0]["duration_seconds"], 45)
        self.assertEqual(execution["zones_done"][1]["duration_seconds"], 45)
        self.assertEqual(execution["zones_done"][0]["passage"], 1)
        self.assertEqual(execution["zones_done"][1]["passage"], 2)
        self.assertEqual(execution["reconciliation"]["planned_mm"], 1.5)
        self.assertEqual(execution["reconciliation"]["executed_mm"], 1.5)

    def test_auto_cycle_suspends_passive_zone_tracking(self) -> None:
        # Anti double-comptage : pendant un cycle piloté (fractionné, avec pauses), le
        # moniteur passif de sessions doit être suspendu, sinon il enregistre un doublon
        # `zone_session` à chaque pause inter-passage (la garde _zone_tracking_suspended
        # n'était jamais armée → l'arrosage était sur-compté).
        plan = watering_plan_mod.build_watering_plan(
            1.5,
            [("switch.zone_1", 60.0)],
            passages=2,
            pause_minutes=25,
        )
        assert plan is not None
        suspended_at_turn_on: list[int] = []

        def _capture(domain, service, data, blocking):
            if domain == "switch" and service == "turn_on":
                suspended_at_turn_on.append(coordinator._zone_tracking_suspended)
            return None

        coordinator = _build_runtime_ready_coordinator(
            plan_attrs=plan.as_dict(), service_handler=_capture
        )

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.5,
                    plan_arrosage_entity_id="sensor.gazon_intelligent_plan_arrosage",
                    source="auto_irrigation",
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        # Le moniteur passif était suspendu à chaque ouverture de vanne (2 passages)…
        self.assertTrue(suspended_at_turn_on)
        self.assertTrue(all(value > 0 for value in suspended_at_turn_on))
        # …et la garde est relâchée proprement en fin de cycle (pas de fuite du compteur).
        self.assertEqual(coordinator._zone_tracking_suspended, 0)
        # Un seul enregistrement d'arrosage (le cycle lui-même), pas de doublon passif.
        coordinator.async_record_watering.assert_awaited_once()

    def test_active_irrigation_session_keeps_post_application_cause(self) -> None:
        plan = watering_plan_mod.build_watering_plan(1.5, [("switch.zone_1", 60.0)])
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())

        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="application_technique_auto",
            strategy="plan",
            watering_cause="post_application",
        )

        self.assertEqual(session["source"], "application_technique_auto")
        self.assertEqual(session["watering_cause"], "post_application")

    def test_async_load_state_restores_runtime_state_with_helpers(self) -> None:
        coordinator = _build_coordinator()
        load_calls: list[dict[str, object]] = []
        coordinator.brain = types.SimpleNamespace(
            load_state=lambda payload, *, shared_products=None: load_calls.append(dict(payload)),
            dump_state=lambda: {},
            memory={},
            last_result=None,
        )
        paused_until = datetime(2026, 3, 18, 6, 25, tzinfo=timezone.utc)
        coordinator._store = types.SimpleNamespace(
            async_load=AsyncMock(
                return_value={
                    "mode": "Normal",
                    "runtime": {
                        "active_irrigation_session": {
                            "status": "paused",
                            "started_at": "2026-03-18T06:00:00+00:00",
                            "paused_until": paused_until.isoformat(),
                            "last_update": "2026-03-18T06:05:00+00:00",
                            "ended_at": None,
                        },
                        "last_irrigation_execution": {"status": "completed", "date": "2026-03-18"},
                        "last_auto_irrigation_reason": {"reason": "ready"},
                        "auto_irrigation_safety_lock": True,
                    },
                }
            )
        )

        asyncio.run(coordinator._async_load_state())

        self.assertEqual(load_calls[0]["mode"], "Normal")
        session = coordinator._runtime_state["active_irrigation_session"]
        self.assertIsInstance(session, dict)
        assert isinstance(session, dict)
        self.assertEqual(session["status"], "paused")
        self.assertEqual(session["paused_until"], paused_until)
        self.assertTrue(coordinator._runtime_state["auto_irrigation_safety_lock"])
        self.assertEqual(
            coordinator._runtime_state["last_irrigation_execution"]["status"],
            "completed",
        )

    def test_async_save_state_serializes_runtime_state_with_helpers(self) -> None:
        coordinator = _build_coordinator()
        started_at = datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc)
        coordinator.brain = types.SimpleNamespace(
            load_state=lambda payload, *, shared_products=None: None,
            dump_state=lambda: {"mode": "Normal"},
            memory={},
            last_result=None,
        )
        coordinator._runtime_state = {
            "active_irrigation_session": {
                "status": "running",
                "started_at": started_at,
                "last_update": started_at + timedelta(minutes=5),
            },
            "last_irrigation_execution": {
                "status": "completed",
                "executed_at": started_at + timedelta(minutes=10),
            },
            "last_auto_irrigation_reason": {"reason": "ready", "updated_at": started_at},
            "auto_irrigation_safety_lock": False,
        }
        coordinator._store = types.SimpleNamespace(async_save=AsyncMock())

        asyncio.run(coordinator._async_save_state())

        payload = coordinator._store.async_save.await_args.args[0]
        self.assertEqual(payload["mode"], "Normal")
        self.assertEqual(
            payload["runtime"]["active_irrigation_session"]["started_at"],
            started_at.isoformat(),
        )
        self.assertEqual(
            payload["runtime"]["last_irrigation_execution"]["executed_at"],
            (started_at + timedelta(minutes=10)).isoformat(),
        )
        self.assertEqual(
            payload["runtime"]["last_auto_irrigation_reason"]["updated_at"],
            started_at.isoformat(),
        )
        self.assertFalse(payload["runtime"]["auto_irrigation_safety_lock"])

    def test_restart_during_fractionation_pause_restores_session_and_reschedules(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            1.5,
            [("switch.zone_1", 60.0)],
            passages=2,
            pause_minutes=25,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="auto_irrigation",
            strategy="plan",
        )
        self.assertEqual(session["plan"]["objective_mm"], 1.5)
        self.assertEqual(session["plan"]["passages"], 2)
        self.assertEqual(session["plan"]["pause_between_passages_s"], 1500)
        self.assertEqual(
            session["plan"]["zones"],
            [
                {
                    "zone": "switch.zone_1",
                    "rate_mm_h": 60.0,
                    "duration_s": 90,
                    "mm": 1.5,
                }
            ],
        )
        self.assertIsNone(session["plan"]["watering_strategy"])
        self.assertIsNone(session["plan"]["objective_scope"])
        session["status"] = "paused"
        session["current_passage"] = 2
        session["current_zone_index"] = 0
        session["paused_until"] = datetime.now(timezone.utc) + timedelta(minutes=25)
        coordinator._runtime_state["active_irrigation_session"] = session

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator._restore_active_irrigation_session()
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        coordinator.async_record_watering.assert_awaited_once()
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["status"], "completed")
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])

    def test_restart_restore_clears_finished_session_without_active_zone(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            5.0,
            [
                ("switch.zone_1", 10.0),
                ("switch.zone_2", 10.0),
                ("switch.zone_3", 20.0),
            ],
            passages=3,
            pause_minutes=20,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator._persist_runtime_state = AsyncMock()

        def _persist_execution_snapshot(session, *, status, error=None):
            coordinator._runtime_state["last_irrigation_execution"] = {
                "status": status,
                "last_error": error,
                "session_id": session.get("session_id"),
            }

        coordinator._persist_execution_snapshot = _persist_execution_snapshot
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="application_technique_auto",
            strategy="plan",
            watering_cause="post_application",
        )
        session["status"] = "running"
        session["active_zones"] = []
        session["current_zone"] = None
        session["current_zone_index"] = len(plan.zones)
        session["current_passage"] = plan.passage_count
        session["zones_pending"] = []
        session["started_at"] = datetime.now(timezone.utc) - timedelta(seconds=plan.total_duration_s + 60)
        session["last_activity_at"] = datetime.now(timezone.utc) - timedelta(seconds=30)
        coordinator._runtime_state["active_irrigation_session"] = session

        asyncio.run(coordinator._restore_active_irrigation_session())

        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        self.assertEqual(
            coordinator._runtime_state["last_irrigation_execution"]["status"],
            "completed",
        )
        coordinator._persist_runtime_state.assert_awaited_once()

    def test_restart_restore_finalizes_pending_user_action_when_session_is_done(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            5.0,
            [
                ("switch.zone_1", 10.0),
                ("switch.zone_2", 10.0),
            ],
            passages=3,
            pause_minutes=20,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator.memory["derniere_action_utilisateur"] = {
            "action": "Arrosage post-produit automatique",
            "state": "en_attente",
            "reason": "Arrosage post-produit automatique lancé, attente de la fin de la séquence.",
            "plan_type": "multi_zone",
            "zone_count": 2,
            "passages": 3,
        }
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="application_technique_auto",
            strategy="plan",
            watering_cause="post_application",
        )
        session["status"] = "running"
        session["active_zones"] = []
        session["current_zone"] = None
        session["current_zone_index"] = len(plan.zones)
        session["current_passage"] = plan.passage_count
        session["zones_pending"] = []
        session["started_at"] = datetime.now(timezone.utc) - timedelta(seconds=plan.total_duration_s + 60)
        session["last_activity_at"] = datetime.now(timezone.utc) - timedelta(seconds=30)
        coordinator._runtime_state["active_irrigation_session"] = session

        asyncio.run(coordinator._restore_active_irrigation_session())

        coordinator.async_record_user_action.assert_awaited_once()
        kwargs = coordinator.async_record_user_action.await_args.kwargs
        self.assertEqual(kwargs["action"], "Arrosage post-produit automatique")
        self.assertEqual(kwargs["state"], "ok")
        self.assertIn("exécuté avec succès", kwargs["reason"])

    def test_finalize_pending_user_action_from_completed_execution_without_active_session(self) -> None:
        coordinator = _build_runtime_ready_coordinator()
        coordinator.memory["derniere_action_utilisateur"] = {
            "action": "Arrosage post-produit automatique",
            "state": "en_attente",
            "reason": "Arrosage post-produit automatique lancé, attente de la fin de la séquence.",
            "plan_type": "multi_zone",
            "zone_count": 3,
            "passages": 1,
        }
        recorded: list[dict[str, object]] = []

        def _record_user_action(**kwargs):
            recorded.append(kwargs)
            coordinator.memory["derniere_action_utilisateur"] = dict(kwargs)
            return kwargs

        coordinator.brain.record_user_action = _record_user_action
        execution = {
            "status": "completed",
            "completion_status": "completed",
            "source": "application_technique_auto",
        }

        async def _run() -> None:
            await coordinator._finalize_pending_irrigation_user_action(
                execution=execution,
                persist_only=True,
            )

        asyncio.run(_run())

        self.assertEqual(len(recorded), 1)
        kwargs = recorded[0]
        self.assertEqual(kwargs["action"], "Arrosage post-produit automatique")
        self.assertEqual(kwargs["state"], "ok")
        self.assertIn("exécuté avec succès", kwargs["reason"])

    def test_restart_restore_keeps_post_application_cause(self) -> None:
        plan = watering_plan_mod.build_watering_plan(1.5, [("switch.zone_1", 60.0)])
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="application_technique_auto",
            strategy="plan",
            watering_cause="post_application",
        )
        session["status"] = "paused"
        session["paused_until"] = datetime.now(timezone.utc)
        coordinator._runtime_state["active_irrigation_session"] = session

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator._restore_active_irrigation_session()
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["source"], "application_technique_auto")
        self.assertEqual(execution["watering_cause"], "post_application")

    def test_manual_launch_rejected_while_auto_launch_lock_held(self) -> None:
        coordinator = _build_runtime_ready_coordinator()

        async def _run() -> None:
            coordinator._ensure_irrigation_runtime_bootstrap()
            if coordinator._irrigation_launch_lock is None:
                coordinator._irrigation_launch_lock = asyncio.Lock()
            async with coordinator._irrigation_launch_lock:
                with self.assertRaises(coordinator_mod.HomeAssistantError):
                    await coordinator_mod.GazonIntelligentCoordinator.async_start_manual_irrigation(
                        coordinator,
                        1.0,
                    )

        asyncio.run(_run())

    def test_double_auto_schedule_creates_single_run(self) -> None:
        plan = watering_plan_mod.build_watering_plan(1.5, [("switch.zone_1", 60.0)])
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator.async_start_auto_irrigation = AsyncMock()
        coordinator._should_launch_auto_irrigation = lambda snapshot: (True, "ready")

        async def _run() -> None:
            snapshot = {"objectif_mm": 1.5}
            await asyncio.gather(
                coordinator_mod.GazonIntelligentCoordinator._maybe_schedule_auto_irrigation(
                    coordinator, snapshot
                ),
                coordinator_mod.GazonIntelligentCoordinator._maybe_schedule_auto_irrigation(
                    coordinator, snapshot
                ),
            )
            task = coordinator._auto_irrigation_scheduler_task
            if task is not None:
                await task

        asyncio.run(_run())

        coordinator.async_start_auto_irrigation.assert_awaited_once()
        self.assertEqual(
            coordinator._runtime_state["last_auto_irrigation_reason"]["reason"],
            "ready",
        )
        self.assertIsNone(coordinator._runtime_state["last_irrigation_execution"])

    def test_post_application_events_and_history_keep_cause(self) -> None:
        plan = watering_plan_mod.build_watering_plan(1.5, [("switch.zone_1", 60.0)])
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator.async_record_watering = AsyncMock()

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.5,
                    plan_arrosage_entity_id="sensor.gazon_intelligent_plan_arrosage",
                    source="application_technique_auto",
                    watering_cause="post_application",
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        call = coordinator.async_record_watering.await_args
        self.assertEqual(call.kwargs["source"], "application_technique_auto")
        self.assertEqual(call.kwargs["watering_cause"], "post_application")
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["source"], "application_technique_auto")
        self.assertEqual(execution["watering_cause"], "post_application")
        event_names = [event for event, _payload in coordinator._events]
        self.assertIn("gazon_intelligent_auto_irrigation_started", event_names)
        self.assertIn("gazon_intelligent_auto_irrigation_zone_started", event_names)
        self.assertIn("gazon_intelligent_auto_irrigation_completed", event_names)
        for event_name, payload in coordinator._events:
            if event_name.startswith("gazon_intelligent_auto_irrigation_"):
                self.assertEqual(payload.get("watering_cause"), "post_application")

    def test_turn_on_failure_marks_failed_and_persists_partial_progress(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            1.5,
            [("switch.zone_1", 60.0), ("switch.zone_2", 30.0)],
        )
        assert plan is not None

        async def _service_handler(domain: str, service: str, data: dict[str, object], blocking: bool) -> None:
            if service == "turn_on" and data.get("entity_id") == "switch.zone_2":
                raise RuntimeError("zone 2 unavailable")

        coordinator = _build_runtime_ready_coordinator(
            plan_attrs=plan.as_dict(),
            service_handler=_service_handler,
        )

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.5,
                    plan_arrosage_entity_id="sensor.gazon_intelligent_plan_arrosage",
                    source="auto_irrigation",
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        coordinator.async_record_watering.assert_not_awaited()
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(len(execution["zones_done"]), 1)
        self.assertEqual(execution["zones_done"][0]["zone"], "switch.zone_1")
        self.assertEqual(execution["zones_failed"][0]["zone"], "switch.zone_2")
        self.assertEqual(execution["completion_status"], "failed_partial")
        self.assertIn("zone_failures", execution["execution_anomalies"])
        self.assertIn("executed_below_plan", execution["execution_anomalies"])
        self.assertEqual(execution["reconciliation"]["planned_mm"], 3.0)
        self.assertEqual(execution["reconciliation"]["executed_mm"], 1.5)

    def test_turn_off_failure_retries_then_sets_safety_lock(self) -> None:
        plan = watering_plan_mod.build_watering_plan(1.5, [("switch.zone_1", 60.0)])
        assert plan is not None

        async def _service_handler(domain: str, service: str, data: dict[str, object], blocking: bool) -> None:
            if service == "turn_off":
                raise RuntimeError("stuck valve")

        coordinator = _build_runtime_ready_coordinator(
            plan_attrs=plan.as_dict(),
            service_handler=_service_handler,
        )

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator,
                    1.5,
                    plan_arrosage_entity_id="sensor.gazon_intelligent_plan_arrosage",
                    source="auto_irrigation",
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        turn_off_calls = [
            call for call in coordinator._service_calls if call[1] == "turn_off"
        ]
        self.assertEqual(len(turn_off_calls), 3)
        self.assertTrue(coordinator._runtime_state["auto_irrigation_safety_lock"])
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["status"], "failed")
        self.assertIn("Echec arrêt zone", execution["last_error"])


class CoordinatorMowerResolutionTests(unittest.TestCase):
    def _build_coordinator(
        self,
        *,
        entry_data: dict[str, object] | None = None,
        mower_states: list[_FakeMowerState] | None = None,
        entity_states: dict[str, _FakeState] | None = None,
        memory: dict[str, object] | None = None,
    ) -> object:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.entry = _FakeEntry(data=entry_data or {}, options={})
        coord.brain = types.SimpleNamespace(memory={}, last_result=None)
        coord.memory = memory or {"mower_coordination_enabled": True}
        coord.data = {}
        coord._watering_session = None
        coord._runtime_state = {
            "active_irrigation_session": None,
            "last_irrigation_execution": None,
            "last_auto_irrigation_reason": None,
            "auto_irrigation_safety_lock": False,
        }
        coord.hass = types.SimpleNamespace(
            states=_FakeStatesWithAll(
                states=entity_states or {},
                mower_states=mower_states or [],
            )
        )
        return coord

    def test_single_discovered_mower_is_selected_and_related_entities_are_monitored(self) -> None:
        coord = self._build_coordinator(
            mower_states=[
                _FakeMowerState(entity_id="lawn_mower.esperance_jr", state="docked", name="Esperance Jr"),
            ],
            entity_states={
                "lawn_mower.esperance_jr": _FakeState("docked", datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)),
                "sensor.esperance_jr_batterie": _FakeState("94", datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)),
                "binary_sensor.esperance_jr_en_charge": _FakeState("off", datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)),
                "binary_sensor.esperance_jr_capteur_de_pluie": _FakeState("off", datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)),
                "sensor.esperance_jr_erreur": _FakeState("no_error", datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)),
                "sensor.esperance_jr_prochain_programme": _FakeState("2026-04-18T11:00:00+00:00", datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)),
                "number.esperance_jr_hauteur_de_coupe": _FakeState("45", datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)),
            },
        )

        selection = coord._resolve_mower_selection()
        snapshot = coord._build_mower_snapshot()
        source_ids = coord._source_entity_ids()

        self.assertEqual(selection["entity_id"], "lawn_mower.esperance_jr")
        self.assertEqual(selection["resolution_state"], "fallback_single")
        self.assertEqual(snapshot["tondeuse_resolution_state"], "fallback_single")
        self.assertEqual(snapshot["mower_resolution_state"], "fallback_single")
        self.assertEqual(
            snapshot["tondeuse_prochain_depart_display"],
            mower_adapter_mod._human_datetime_text("2026-04-18T11:00:00+00:00"),
        )
        self.assertTrue(snapshot["mower_coordination_ready"])
        self.assertIn("lawn_mower.esperance_jr", source_ids)
        self.assertIn("sensor.esperance_jr_batterie", source_ids)
        self.assertIn("sensor.esperance_jr_prochain_programme", source_ids)
        self.assertIn("number.esperance_jr_hauteur_de_coupe", source_ids)

    def test_manual_cutting_height_is_used_when_mower_height_is_missing(self) -> None:
        coord = self._build_coordinator(
            entry_data={"hauteur_coupe_tondeuse_mm": 48},
        )

        snapshot = coord._build_mower_snapshot()

        self.assertEqual(snapshot["tondeuse_hauteur_coupe_mm"], 48)
        self.assertFalse(snapshot["tondeuse_prete"])
        self.assertEqual(snapshot["tondeuse_statut"], "inconnu")

    def test_multiple_discovered_mowers_do_not_select_silently(self) -> None:
        coord = self._build_coordinator(
            mower_states=[
                _FakeMowerState(entity_id="lawn_mower.alpha", state="docked"),
                _FakeMowerState(entity_id="lawn_mower.bravo", state="idle"),
            ],
        )

        selection = coord._resolve_mower_selection()
        snapshot = coord._build_mower_snapshot()
        source_ids = coord._source_entity_ids()

        self.assertIsNone(selection["entity_id"])
        self.assertEqual(selection["resolution_state"], "ambiguous")
        self.assertEqual(selection["resolution_candidate_count"], 2)
        self.assertEqual(snapshot["tondeuse_resolution_state"], "ambiguous")
        self.assertEqual(snapshot["mower_resolution_state"], "ambiguous")
        self.assertEqual(snapshot["tondeuse_statut"], "inconnu")
        self.assertFalse(snapshot["tondeuse_prete"])
        self.assertFalse(snapshot["mower_coordination_ready"])
        self.assertEqual(snapshot["mower_reason_code"], "ambiguous")
        self.assertFalse(any(item.startswith("sensor.alpha") or item.startswith("sensor.bravo") for item in source_ids))

    def test_explicitly_configured_missing_mower_is_diagnosed(self) -> None:
        coord = self._build_coordinator(
            entry_data={"entite_tondeuse": "lawn_mower.missing"},
            mower_states=[
                _FakeMowerState(entity_id="lawn_mower.alpha", state="docked"),
            ],
        )

        selection = coord._resolve_mower_selection()
        snapshot = coord._build_mower_snapshot()

        self.assertEqual(selection["entity_id"], "lawn_mower.missing")
        self.assertEqual(selection["resolution_state"], "configured_missing")
        self.assertEqual(snapshot["tondeuse_resolution_state"], "configured_missing")
        self.assertEqual(snapshot["mower_resolution_state"], "configured_missing")
        self.assertFalse(snapshot["tondeuse_prete"])
        self.assertFalse(snapshot["mower_coordination_ready"])
        self.assertEqual(snapshot["mower_reason_code"], "configured_missing")
