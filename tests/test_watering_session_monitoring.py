from __future__ import annotations

import asyncio
import importlib
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock, patch


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

    ensure_module("homeassistant.helpers")  # effet de bord seul : crée le module stub
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
shared_state_mod = importlib.import_module("custom_components.gazon_intelligent.shared_state")
watering_plan_mod = importlib.import_module("custom_components.gazon_intelligent.watering_plan")
mower_adapter_mod = importlib.import_module("custom_components.gazon_intelligent.mower_adapter")
water_mod = importlib.import_module("custom_components.gazon_intelligent.water")


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


def _ready_launch_snapshot(coordinator: object, **overrides: object) -> dict[str, object]:
    """Snapshot qui passe toutes les gardes de `_should_launch_auto_irrigation`."""
    snapshot = {
        "objectif_mm": 8.0,
        "arrosage_recommande": True,
        "arrosage_auto_autorise": True,
        "irrigation_execution_allowed": True,
        "type_arrosage": "auto",
        "fenetre_optimale": "matin",
        "watering_target_date": coordinator._current_date().isoformat(),
        "watering_window_start_minute": 0,
        "watering_window_end_minute": 1440,
        "watering_evening_start_minute": 1,
        "watering_evening_end_minute": 1440,
        "watering_evening_allowed": True,
    }
    snapshot.update(overrides)
    return snapshot


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
    # Les vannes existent et répondent, comme en production. Sans elles, le garde de
    # disponibilité ajouté à `_execute_canonical_watering_plan` annule le cycle avant de
    # commander quoi que ce soit — c'est justement son rôle : ne jamais comptabiliser une dose
    # qu'aucune vanne n'a reçue. Les tests qui simulent une panne surchargent cet état.
    for _idx in range(1, 6):
        states[f"switch.zone_{_idx}"] = _FakeState("off", datetime.now(timezone.utc))
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


class GardeConfirmationUtilisateurRetireTests(unittest.TestCase):
    """`auto_irrigation_user_confirmed` a été retirée le 29/07/2026 — elle ne doit pas revenir.

    Elle était lue pour refuser l'arrosage automatique, mais n'était écrite NULLE PART dans les
    39 modules et absente du stockage réel : la clé valait toujours None, et `None is False` est
    faux. La garde ne s'est donc jamais déclenchée en production.

    Les deux tests qu'elle avait ne prouvaient rien : ils fournissaient la clé À LA MAIN à False,
    une valeur que la production ne produit jamais. Fausse confiance typique.

    L'interrupteur « arrosage automatique » remplit ce rôle, lui bien câblé et vérifié en amont.
    """

    def test_une_memoire_sans_confirmation_ne_bloque_plus_l_arrosage(self) -> None:
        coordinator = _build_coordinator()
        coordinator.history = []
        # État RÉEL : la clé n'existe pas. Avant comme après, la garde ne se déclenchait pas —
        # ce test verrouille qu'on ne la réintroduise pas sous une forme qui, elle, mordrait.
        coordinator.memory = {"auto_irrigation_enabled": True}

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            _ready_launch_snapshot(coordinator)
        )

        self.assertNotEqual(reason, "user_confirmation_required")
        self.assertTrue(should_launch)

    def test_le_motif_de_refus_n_existe_plus_dans_le_code(self) -> None:
        # Lecture du FICHIER, pas `inspect.getsource` : dans la suite complète, les stubs
        # installés par d'autres fichiers de test privent le module de son `__file__` et
        # l'introspection lève. On cherche le MOTIF DE REFUS et non le nom de la clé, qui
        # subsiste volontairement dans le commentaire expliquant la suppression.
        source = (
            Path(__file__).resolve().parents[1]
            / "custom_components" / "gazon_intelligent" / "coordinator.py"
        ).read_text()
        self.assertNotIn(
            '"user_confirmation_required"',
            source,
            "la garde inerte a été réintroduite",
        )


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

    def test_relaunch_cooldown_blocks_back_to_back_cycle(self) -> None:
        # Un cycle auto vient de finir → pas de nouveau gros cycle tout de suite.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(coordinator)
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = (
            coordinator._current_utc_datetime() - timedelta(minutes=10)
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "relaunch_cooldown")

    def test_relaunch_cooldown_clears_after_delay(self) -> None:
        # Au-delà du cooldown (6 h), un nouveau cycle est de nouveau autorisé.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(coordinator)
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = (
            coordinator._current_utc_datetime() - timedelta(hours=8)
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

    def test_post_application_incorporation_auto_launches_even_if_soil_humid(self) -> None:
        # Incorporation post-application (produit sol type Humuslight) en mode auto : arrosage
        # TECHNIQUE (faire pénétrer le produit via l'eau, cf. fertigation). Un sol déjà humide ne
        # doit PAS le bloquer — sinon « rien ne se lance ». Il doit partir.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(
            coordinator,
            type_arrosage="application_technique_auto",
            application_post_watering_status="autorise",
            objectif_mm=3.0,
            block_reason="sol_deja_humide",
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "post_application_ready")

    def test_normal_watering_still_blocked_by_soil_humid(self) -> None:
        # Garde-fou : l'exemption « sol humide » ne concerne QUE l'incorporation technique.
        # Un arrosage hydrique normal reste bloqué par un sol déjà humide.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(
            coordinator,
            type_arrosage="auto",
            block_reason="sol_deja_humide",
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "irrigation_blocked")

    def test_post_application_incorporation_still_blocked_by_rain(self) -> None:
        # L'exemption ne vaut QUE pour « sol déjà humide » : un autre motif (pluie) bloque toujours
        # l'incorporation auto (inutile d'arroser si la pluie va incorporer le produit).
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(
            coordinator,
            type_arrosage="application_technique_auto",
            application_post_watering_status="autorise",
            objectif_mm=3.0,
            block_reason="pluie_proche",
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "irrigation_blocked")

    def test_relaunch_cooldown_blocks_evening_recharge_rerun(self) -> None:
        # Un arrosage du soir NON-rafraîchissement (recharge hydrique du soir) reste soumis au
        # cooldown anti-relance : s'il vient de finir (10 min), pas de relance. (Le rafraîchissement
        # canicule, lui, en est exempté — cf. tests dédiés ci-dessous.)
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(
            coordinator, fenetre_optimale="soir", watering_cause="hydrique"
        )
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = (
            coordinator._current_utc_datetime() - timedelta(minutes=10)
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "relaunch_cooldown")

    def test_evening_cooling_exempt_from_relaunch_cooldown(self) -> None:
        # Le rafraîchissement du soir (cause rafraichissement_soir) est EXEMPTÉ du cooldown anti-
        # relance : même avec un arrosage normal qui vient de finir (10 min), il peut partir.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(
            coordinator, fenetre_optimale="soir", watering_cause="rafraichissement_soir"
        )
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = (
            coordinator._current_utc_datetime() - timedelta(minutes=10)
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

    def test_evening_cooling_runs_once_per_evening(self) -> None:
        # Garde anti-boucle : si un rafraîchissement du soir a déjà eu lieu aujourd'hui, il ne
        # repart pas (même exempté du cooldown anti-relance).
        coordinator = _build_coordinator()
        coordinator.history = [
            {
                "type": "arrosage",
                "recorded_at": coordinator._current_datetime().isoformat(),
                "total_mm": 3.0,
                "watering_cause": "rafraichissement_soir",
            }
        ]
        snapshot = _ready_launch_snapshot(
            coordinator, fenetre_optimale="soir", watering_cause="rafraichissement_soir"
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "evening_cooling_done")

    def test_evening_window_uses_cooling_debug_over_stale_keys(self) -> None:
        # La vraie fenêtre du soir (coucher-30→coucher) est portée de façon fiable par
        # evening_cooling_debug ; les clés watering_evening_*_minute arrivent souvent au défaut
        # figé 18-20 h (chemin advanced_context). Le coordinateur doit privilégier la fenêtre du
        # debug, sinon il bloquerait à tort le lancement du cooling ~30 min avant le coucher.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(
            coordinator,
            fenetre_optimale="soir",
            watering_cause="rafraichissement_soir",
            watering_evening_start_minute=0,
            watering_evening_end_minute=1,  # fenêtre figée qui EXCLUT l'heure courante
            evening_cooling_debug={"evening_window_minutes": [0, 1440]},  # vraie fenêtre : couvre tout
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

    def test_evening_window_blocked_outside_cooling_debug_window(self) -> None:
        # Hors de la vraie fenêtre du soir (debug), le lancement est refusé même si les clés figées
        # seraient permissives — la fenêtre du debug fait foi dans les deux sens.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(
            coordinator,
            fenetre_optimale="soir",
            watering_cause="rafraichissement_soir",
            watering_evening_start_minute=0,
            watering_evening_end_minute=1440,  # figée permissive
            evening_cooling_debug={"evening_window_minutes": [0, 1]},  # vraie fenêtre : EXCLUT l'heure
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "outside_evening_window")

    def test_evening_cooling_launches_after_morning_cycle(self) -> None:
        # Le rafraîchissement du soir reste autorisé malgré l'eau du matin : l'écart
        # matin→soir (> 6 h) dépasse le cooldown, et l'eau déjà appliquée ne le bloque pas
        # (son but est de refroidir, pas de combler un déficit).
        coordinator = _build_coordinator()
        coordinator.history = [
            {"type": "arrosage", "recorded_at": coordinator._current_date().isoformat(), "total_mm": 17.0},
        ]
        snapshot = _ready_launch_snapshot(coordinator, fenetre_optimale="soir", objectif_mm=4.0)
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = (
            coordinator._current_utc_datetime() - timedelta(hours=8)
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

    def test_relaunch_cooldown_exempts_semis_frequent(self) -> None:
        # Sursemis : cycles fréquents (~90 min) → le cooldown 6 h NE doit PAS bloquer.
        coordinator = _build_coordinator()
        coordinator.history = []
        coordinator._semis_cycle_progress = lambda snapshot: {
            "cycles_remaining_today": 2,
            "state": "ready",
        }
        snapshot = _ready_launch_snapshot(coordinator)
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = (
            coordinator._current_utc_datetime() - timedelta(minutes=10)
        )
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

    def test_relaunch_cooldown_absent_timestamp_allows(self) -> None:
        # Sans cycle précédent (timestamp None), aucun blocage de cooldown.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(coordinator)
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = None
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

    def test_live_session_water_runtime_in_progress(self) -> None:
        # Cycle piloté : 2 passages terminés (3 mm chacun) + zone_1 active depuis 5 min à 12 mm/h.
        now = datetime(2026, 6, 17, 4, 30, tzinfo=timezone.utc)
        session = {
            "status": "running",
            "zones_done": [
                {"zone": "switch.zone_1", "mm": 3.0},
                {"zone": "switch.zone_2", "mm": 3.0},
            ],
            "active_zones": ["switch.zone_1"],
            "last_activity_at": now - timedelta(minutes=5),
        }
        rates = {"switch.zone_1": 12.0, "switch.zone_2": 12.0}
        result = water_mod.compute_live_session_water(
            session, now=now, rate_fn=lambda z: rates.get(z, 0.0)
        )
        # zone_1 : 3.0 + 12*5/60 = 4.0 ; zone_2 : 3.0
        self.assertEqual(result["zone_mm"]["switch.zone_1"], 4.0)
        self.assertEqual(result["zone_mm"]["switch.zone_2"], 3.0)
        self.assertEqual(result["surface_mm"], 3.5)  # moyenne (4.0 + 3.0) / 2
        self.assertEqual(result["total_mm"], 7.0)

    def test_live_session_water_passive_dict_zones(self) -> None:
        # Moniteur passif : zone déjà créditée 2 mm + active depuis 5 min à 12 mm/h.
        now = datetime(2026, 6, 17, 4, 30, tzinfo=timezone.utc)
        session = {
            "status": "running",
            "zones": {"switch.zone_1": {"mm": 2.0}},
            "active_zones": {"switch.zone_1": now - timedelta(minutes=5)},
        }
        result = water_mod.compute_live_session_water(
            session, now=now, rate_fn=lambda z: 12.0
        )
        self.assertEqual(result["zone_mm"]["switch.zone_1"], 3.0)  # 2.0 + 1.0

    def test_live_session_water_paused_ignores_in_progress(self) -> None:
        # En pause : aucun segment en cours ne doit être ajouté.
        now = datetime(2026, 6, 17, 4, 30, tzinfo=timezone.utc)
        session = {
            "status": "paused",
            "zones_done": [{"zone": "switch.zone_1", "mm": 5.0}],
            "active_zones": [],
            "last_activity_at": now - timedelta(minutes=10),
        }
        result = water_mod.compute_live_session_water(
            session, now=now, rate_fn=lambda z: 12.0
        )
        self.assertEqual(result["zone_mm"]["switch.zone_1"], 5.0)
        self.assertEqual(result["surface_mm"], 5.0)

    def test_live_session_water_handles_none_session(self) -> None:
        now = datetime(2026, 6, 17, 4, 30, tzinfo=timezone.utc)
        result = water_mod.compute_live_session_water(None, now=now, rate_fn=lambda z: 12.0)
        self.assertEqual(result["zone_mm"], {})
        self.assertEqual(result["surface_mm"], 0.0)
        self.assertEqual(result["total_mm"], 0.0)

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
                # Le veilleur de vanne (0.31.2) fait partie du chemin d'exécution réel :
                # sans lui, ce double testerait un code que la production n'emprunte plus.
                self._zone_semble_ouverte = (
                    coordinator_mod.GazonIntelligentCoordinator._zone_semble_ouverte.__get__(self)
                )
                self._attendre_zone_ouverte = (
                    coordinator_mod.GazonIntelligentCoordinator._attendre_zone_ouverte.__get__(self)
                )

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

            async def _wait_for_zones_available(self, zone_ids, **kwargs):
                # Vannes présentes et disponibles : ce test couvre la séquence, pas la panne.
                return True

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
        # La reprise au boot attend que la vanne soit disponible avant d'agir.
        coordinator.hass.states.states["switch.zone_1"] = _FakeState("on", datetime.now(timezone.utc), {})
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

    def test_restart_mid_zone_resumes_remaining_time(self) -> None:
        # Zone interrompue en plein arrosage (vanne restée ouverte pendant le reboot) : au boot,
        # on reprend cette MÊME zone pour son TEMPS RESTANT (durée 90 s, démarrée il y a 30 s →
        # reste ~60 s), au lieu de la sauter.
        plan = watering_plan_mod.build_watering_plan(
            1.5, [("switch.zone_1", 60.0)], passages=1, pause_minutes=0
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session["status"] = "running"
        session["current_passage"] = 1
        session["current_zone_index"] = 0
        session["current_zone"] = "switch.zone_1"
        session["current_zone_started_at"] = datetime.now(timezone.utc) - timedelta(seconds=30)
        coordinator.hass.states.states["switch.zone_1"] = _FakeState("on", datetime.now(timezone.utc), {})
        coordinator._runtime_state["active_irrigation_session"] = session

        sleeps: list[float] = []

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                sleeps.append(float(args[0]) if args else 0.0)
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

        # La zone a été reprise pour ~60 s (temps restant), pas 90 s (durée pleine) ni sautée.
        # Le veilleur de vanne découpe l'attente en tranches de 15 s : c'est le CUMUL qui
        # doit valoir le temps restant du segment, pas une tranche isolée.
        total = sum(sleeps)
        self.assertTrue(55.0 <= total <= 65.0, f"total={total} sleeps={sleeps}")
        self.assertFalse(85.0 <= total <= 95.0, f"total={total} sleeps={sleeps}")
        coordinator.async_record_watering.assert_awaited()

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


class CoordinatorSnapshotPlumbingTests(unittest.TestCase):
    """Deux clés étaient lues dans self.data sans y être jamais publiées, et la température
    capteur alimentait la référence hydrique sans passer par le validateur."""

    def test_le_fractionnement_est_publie_dans_le_snapshot(self) -> None:
        # _get_canonical_watering_plan et la construction des sessions lisent ces deux clés
        # dans self.data : sans elles, repli silencieux sur 1 passage / 0 pause.
        for key in ("watering_passages", "watering_pause_minutes"):
            with self.subTest(key=key):
                self.assertIn(key, coordinator_mod._COORDINATOR_SNAPSHOT_KEYS)

    def test_le_plan_canonique_respecte_le_fractionnement(self) -> None:
        coord = _build_coordinator()
        coord.data = {"watering_passages": 2, "watering_pause_minutes": 25}
        plan = coordinator_mod.GazonIntelligentCoordinator._get_canonical_watering_plan(
            coord, objectif_mm=10.0
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.passage_count, 2)
        self.assertEqual(plan.pause_between_passages_s, 25 * 60)

    def test_temperature_capteur_aberrante_est_rejetee(self) -> None:
        # Un capteur qui déraille à 80 °C ne doit pas contaminer temperature_reference_hydrique,
        # qui pilote seule l'ET0 et donc les doses.
        coord = _build_coordinator()
        coord.entry = _FakeEntry(data={"capteur_temperature": "sensor.temp"})
        coord._get_float_state = lambda entity_id: 80.0
        temperature, source, reference = (
            coordinator_mod.GazonIntelligentCoordinator._resolve_temperature_inputs(
                coord, weather_profile={}, forecast_summary={"forecast_temperature_today": 28.0}
            )
        )
        # Le capteur aberrant est rejeté : on retombe sur la prévision, pas sur 80 °C.
        self.assertEqual(temperature, 28.0)
        self.assertEqual(source, "meteo_forecast")
        # Référence hydrique = prévision seule. Sans la validation elle valait
        # 0.3 x 28 + 0.7 x 80 = 64,4 °C l'après-midi, d'où une ET0 délirante.
        self.assertEqual(reference, 28.0)

    def test_prevision_aberrante_est_rejetee(self) -> None:
        coord = _build_coordinator()
        coord.entry = _FakeEntry(data={"capteur_temperature": "sensor.temp"})
        coord._get_float_state = lambda entity_id: 24.0
        _, _, reference = (
            coordinator_mod.GazonIntelligentCoordinator._resolve_temperature_inputs(
                coord, weather_profile={}, forecast_summary={"forecast_temperature_today": 120.0}
            )
        )
        self.assertEqual(reference, 24.0)


class ZoneResolutionResilienceTests(unittest.TestCase):
    """Défense en profondeur : même si entry.options contient déjà des clés de zone à None
    (installations polluées par l'ancien options flow), le coordinateur doit retomber sur
    entry.data. `opts.get(k, data.get(k))` ne le faisait pas — le défaut de `get` ne s'applique
    que si la clé est ABSENTE, pas si elle vaut None."""

    def _zones(self, *, data, options):
        coord = _build_coordinator()
        coord.entry = _FakeEntry(data=data, options=options)
        return [entity_id for entity_id, _ in
                coordinator_mod.GazonIntelligentCoordinator._iter_zones_with_rate(coord)]

    DATA = {
        "zone_1": "switch.z1", "debit_zone_1": 60.0,
        "zone_2": "switch.z2", "debit_zone_2": 60.0,
        "zone_3": "switch.z3", "debit_zone_3": 60.0,
    }

    def test_zones_resolues_sans_options(self) -> None:
        self.assertEqual(self._zones(data=self.DATA, options={}),
                         ["switch.z1", "switch.z2", "switch.z3"])

    def test_zones_a_none_dans_les_options_ne_masquent_plus_entry_data(self) -> None:
        zones = self._zones(data=self.DATA, options={"zone_2": None, "zone_3": None})
        self.assertEqual(zones, ["switch.z1", "switch.z2", "switch.z3"])

    def test_une_zone_reellement_redefinie_dans_les_options_gagne(self) -> None:
        zones = self._zones(data=self.DATA, options={"zone_2": "switch.autre"})
        self.assertIn("switch.autre", zones)
        self.assertNotIn("switch.z2", zones)

    def test_un_debit_a_none_retombe_sur_entry_data(self) -> None:
        zones = self._zones(data=self.DATA, options={"debit_zone_2": None})
        self.assertIn("switch.z2", zones)

    def test_un_debit_a_zero_desactive_bien_la_zone(self) -> None:
        # RÉGRESSION : `opts.get(k) or data.get(k)` traitait 0.0 comme absent et ressuscitait
        # l'ancien débit d'entry.data, RÉACTIVANT une zone que l'utilisateur avait neutralisée.
        # Cas réel : l'instance « Gazon Potager » pointe zone_1 sur la vanne de la zone 3 de la
        # pelouse principale, mise hors service par un débit à 0 — elle redevenait pilotable.
        zones = self._zones(data=self.DATA, options={"debit_zone_2": 0})
        self.assertNotIn("switch.z2", zones)
        self.assertIn("switch.z1", zones, "les autres zones ne doivent pas être affectées")

    def test_zero_est_distingue_de_absent(self) -> None:
        for valeur, attendu in ((0, False), (0.0, False), (None, True)):
            with self.subTest(debit=valeur):
                zones = self._zones(data=self.DATA, options={"debit_zone_3": valeur})
                self.assertEqual("switch.z3" in zones, attendu)

    def test_toutes_zones_a_zero_ne_donne_aucune_zone(self) -> None:
        zones = self._zones(
            data=self.DATA,
            options={"debit_zone_1": 0, "debit_zone_2": 0, "debit_zone_3": 0},
        )
        self.assertEqual(zones, [])


class SensorHealthPluieTests(unittest.TestCase):
    """`pluie_valid` testait la valeur RÉSOLUE (`pluie_24h`), qui reprend le capteur quand il
    répond et retombe sur la prévision sinon : l'expression était donc toujours vraie et le
    voyant ne pouvait jamais signaler un capteur pluie en panne."""

    def _pluie_valid(self, *, capteur_configure, capteur_repond):
        # Reproduit l'expression de coordinator._build_public_snapshot_data.
        pluie_24h_sensor = 3.2 if (capteur_configure and capteur_repond) else None
        conf = "sensor.pluie" if capteur_configure else None
        return pluie_24h_sensor is not None or conf is None

    def test_capteur_configure_et_fonctionnel(self) -> None:
        self.assertTrue(self._pluie_valid(capteur_configure=True, capteur_repond=True))

    def test_capteur_configure_en_panne_est_signale(self) -> None:
        # C'est LE cas que l'ancienne expression ne pouvait pas produire.
        self.assertFalse(self._pluie_valid(capteur_configure=True, capteur_repond=False))

    def test_aucun_capteur_configure_reste_valide(self) -> None:
        self.assertTrue(self._pluie_valid(capteur_configure=False, capteur_repond=False))

    def test_lexpression_nest_plus_une_tautologie(self) -> None:
        resultats = {
            self._pluie_valid(capteur_configure=c, capteur_repond=r)
            for c in (True, False) for r in (True, False)
        }
        self.assertEqual(resultats, {True, False}, "le voyant doit pouvoir valoir False")


class ZoneAvailabilityGuardTests(unittest.TestCase):
    """`switch.turn_on` sur une entité `unavailable` ne lève AUCUNE erreur : la commande part
    dans le vide, aucune goutte n'est délivrée, et la dose complète est pourtant comptabilisée en
    fin de cycle. Le gazon reste sec pendant que l'intégration affiche un arrosage réussi et
    crédite la réserve. `_wait_for_zones_available` existait mais n'était branchée que sur le
    chemin de reprise après redémarrage."""

    def _coord(self, zone_states):
        coord = _build_coordinator()
        etats = {
            zid: _FakeState(val, datetime.now(timezone.utc))
            for zid, val in zone_states.items()
            if val is not None
        }
        coord.hass = types.SimpleNamespace(
            services=types.SimpleNamespace(async_call=lambda *a, **k: None),
            async_create_task=lambda coro, name=None: asyncio.create_task(coro),
            bus=types.SimpleNamespace(async_fire=lambda e, p=None: None),
            states=_FakeStates(etats),
        )
        return coord

    def _attend(self, coord, zones, timeout=0.05):
        return asyncio.run(
            coordinator_mod.GazonIntelligentCoordinator._wait_for_zones_available(
                coord, zones, timeout_s=timeout, poll_s=0.01
            )
        )

    def test_vannes_disponibles_passent(self) -> None:
        coord = self._coord({"switch.z1": "off", "switch.z2": "on"})
        self.assertTrue(self._attend(coord, ["switch.z1", "switch.z2"]))

    def test_une_vanne_unavailable_bloque(self) -> None:
        coord = self._coord({"switch.z1": "off", "switch.z2": "unavailable"})
        self.assertFalse(self._attend(coord, ["switch.z1", "switch.z2"]))

    def test_une_vanne_unknown_bloque(self) -> None:
        coord = self._coord({"switch.z1": "unknown"})
        self.assertFalse(self._attend(coord, ["switch.z1"]))

    def test_une_vanne_absente_du_registre_bloque(self) -> None:
        coord = self._coord({"switch.z1": "off", "switch.z2": None})
        self.assertFalse(self._attend(coord, ["switch.z1", "switch.z2"]))

    def test_aucune_zone_ne_bloque_pas(self) -> None:
        self.assertTrue(self._attend(self._coord({}), []))

    def test_le_garde_est_branche_sur_le_lancement_normal(self) -> None:
        # Le défaut n'était pas l'absence du garde mais son absence de branchement : il ne
        # protégeait que la reprise après redémarrage, jamais le lancement auto ou manuel.
        import inspect
        src = inspect.getsource(
            coordinator_mod.GazonIntelligentCoordinator._execute_canonical_watering_plan
        )
        self.assertIn("_wait_for_zones_available", src)


class PendingSegmentsFractionationTests(unittest.TestCase):
    """`_build_pending_zone_segments` stockait la dose PLEINE (`zone.duration_s`/`zone.mm`) pour
    CHAQUE passage : sur un cycle fractionné (passages > 1), la liste `zones_pending` surestimait
    chaque segment (2 passages → 2× la dose par segment). Inerte à ce jour — l'exécution, le mm
    crédité et la reprise recalculent tous via `zone_for_passage` — mais c'était un piège : un futur
    code lisant ces valeurs pour la reprise aurait double-dosé."""

    def _segments(self, *, objectif, rate, passages):
        plan = watering_plan_mod.build_watering_plan(
            objectif, [("switch.z1", rate)], passages=passages, pause_minutes=25
        )
        coord = _build_coordinator()
        return plan, coordinator_mod.GazonIntelligentCoordinator._build_pending_zone_segments(coord, plan)

    def test_mm_des_segments_somme_a_lobjectif(self):
        _, seg = self._segments(objectif=12.0, rate=14.0, passages=2)
        self.assertEqual(round(sum(s["mm"] for s in seg), 1), 12.0)

    def test_duree_des_segments_somme_a_la_duree_pleine(self):
        plan, seg = self._segments(objectif=12.0, rate=14.0, passages=2)
        self.assertEqual(sum(s["duration_s"] for s in seg), plan.zones[0].duration_s)

    def test_deux_passages_produisent_deux_segments_a_demi_dose(self):
        _, seg = self._segments(objectif=12.0, rate=14.0, passages=2)
        self.assertEqual(len(seg), 2)
        for s in seg:
            self.assertAlmostEqual(s["mm"], 6.0, places=1)

    def test_un_seul_passage_donne_la_dose_pleine(self):
        _, seg = self._segments(objectif=10.0, rate=14.0, passages=1)
        self.assertEqual(len(seg), 1)
        self.assertAlmostEqual(seg[0]["mm"], 10.0, places=1)


# ---------------------------------------------------------------------------
# BANC DE TEST — reprise après coupure de HA en plein cycle d'arrosage.
# Objectif : caractériser le comportement à différents instants d'interruption
# AVANT de corriger les bugs, pour que chaque correctif ait un filet.
# Les tests marqués @expectedFailure exposent un bug connu (encore ouvert) :
# la suite reste verte ; retirer le marqueur quand le bug est corrigé.
# ---------------------------------------------------------------------------
class RestartFinishHeuristicBenchTests(unittest.TestCase):
    """`_is_finished_irrigation_session` déclare un cycle terminé dès que
    `elapsed >= planned_total_seconds`, MÊME s'il reste des passages en attente. Si HA coupe
    pendant la pause inter-passages et reste indisponible plus longtemps que la durée planifiée,
    le cycle est clôturé et le 2ᵉ passage abandonné (6 mm délivrés au lieu de 12) — bug 2212."""

    NOW = datetime(2026, 7, 23, 6, 0, tzinfo=timezone.utc)

    def _verdict(self, session):
        fake = types.SimpleNamespace(_current_utc_datetime=lambda: self.NOW)
        return coordinator_mod.GazonIntelligentCoordinator._is_finished_irrigation_session(fake, session)

    def _session_mid_pause(self, *, down_seconds):
        # Passage 1 terminé, en pause avant le passage 2, vanne fermée. HA down `down_seconds`.
        return {
            "status": "running",
            "current_passage": 1,
            "passage_count": 2,
            "planned_total_seconds": 6330,  # 2 passages (4830) + pause 25 min (1500)
            "started_at": self.NOW - timedelta(seconds=down_seconds),
            "active_zones": [],
            "current_zone": None,
            "zones_pending": [
                {"passage": 2, "zone_index": 0, "zone": "switch.z1", "duration_s": 1545, "mm": 6.0},
                {"passage": 2, "zone_index": 1, "zone": "switch.z2", "duration_s": 1545, "mm": 6.0},
            ],
        }

    # --- Contrôles positifs : comportement correct existant (doivent passer) ---
    def test_session_completed_est_terminee(self):
        self.assertTrue(self._verdict({"status": "completed"}))

    def test_session_failed_est_terminee(self):
        self.assertTrue(self._verdict({"status": "failed"}))

    def test_zone_active_nest_pas_terminee(self):
        self.assertFalse(self._verdict({
            "status": "running", "active_zones": ["switch.z1"], "current_zone": "switch.z1",
        }))

    def test_tous_passages_faits_pending_vide_est_termine(self):
        s = self._session_mid_pause(down_seconds=7000)
        s["current_passage"], s["zones_pending"] = 2, []
        self.assertTrue(self._verdict(s))

    def test_coupure_courte_pendant_la_pause_nest_pas_terminee(self):
        # HA down 10 min (< planned 6330 s) : elapsed < planned, l'heuristique ne se déclenche pas.
        self.assertFalse(self._verdict(self._session_mid_pause(down_seconds=600)))

    # --- Bug 2212 CORRIGÉ : coupure longue pendant la pause ne clôture plus le cycle ---
    def test_coupure_longue_pendant_la_pause_ne_termine_pas_le_cycle(self):
        # HA down 2 h (> planned 6330 s) alors que le passage 2 reste à faire.
        s = self._session_mid_pause(down_seconds=7200)
        self.assertFalse(
            self._verdict(s),
            "un cycle avec des passages en attente ne doit PAS être déclaré terminé",
        )


class RestartPhantomSessionBenchTests(unittest.TestCase):
    """Bug 1578 (session fantôme) est CONNECTÉ au 2212 : `_get_active_irrigation_session` efface la
    session persistée si `_is_finished_irrigation_session` la déclare terminée. Après une coupure
    longue pendant la pause, l'ancienne heuristique la déclarait terminée → session effacée →
    `_get_active_irrigation_session()` renvoyait None → la garde de reconstruction de session
    passive sautait → session fantôme qui verrouille l'arrosage. Le correctif du 2212 (ne pas
    déclarer terminé s'il reste des segments) referme aussi cette racine."""

    NOW = datetime(2026, 7, 23, 6, 0, tzinfo=timezone.utc)

    def _coord_with_session(self, session):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {"active_irrigation_session": session}
        coord._irrigation_launch_lock = None
        coord._current_utc_datetime = lambda: self.NOW
        return coord

    def _mid_pause_session(self, *, down_seconds):
        return {
            "status": "running",
            "current_passage": 1,
            "passage_count": 2,
            "planned_total_seconds": 6330,
            "started_at": self.NOW - timedelta(seconds=down_seconds),
            "active_zones": [],
            "current_zone": None,
            "plan": {"objective_mm": 12.0},
            "zones_pending": [
                {"passage": 2, "zone_index": 0, "zone": "switch.z1", "duration_s": 1545, "mm": 6.0},
            ],
        }

    def test_session_mid_pause_est_conservee_apres_coupure_longue(self):
        # HA down 2 h : la session à reprendre doit être CONSERVÉE (pas effacée → pas de fantôme).
        coord = self._coord_with_session(self._mid_pause_session(down_seconds=7200))
        got = coordinator_mod.GazonIntelligentCoordinator._get_active_irrigation_session(coord)
        self.assertIsNotNone(got, "la session à reprendre ne doit pas être effacée")
        self.assertEqual(got.get("current_passage"), 1)

    def test_session_vraiment_terminee_est_bien_effacee(self):
        # Contrôle : un cycle réellement fini (dernier passage, pending vide) doit être effacé.
        s = self._mid_pause_session(down_seconds=7200)
        s["current_passage"], s["zones_pending"], s["status"] = 2, [], "completed"
        coord = self._coord_with_session(s)
        # _set_active_irrigation_session + _persist_execution_snapshot appelés sur session finie :
        coord._set_active_irrigation_session = lambda v: coord._runtime_state.__setitem__("active_irrigation_session", v)
        coord._persist_execution_snapshot = lambda *a, **k: None
        got = coordinator_mod.GazonIntelligentCoordinator._get_active_irrigation_session(coord)
        self.assertIsNone(got)


class SharedStateLoadRaceBenchTests(unittest.TestCase):
    """État partagé par les DEUX instances (singleton). HA peut initialiser les deux entrées du
    même domaine en parallèle → deux `async_load` concurrents. Sans sérialisation, les deux
    passaient la garde `_loaded` avant l'await du Store puis réassignaient `products` → un cerveau
    tenant une référence à l'ancien dict se retrouvait avec un catalogue orphelin (bug shared_state:126)."""

    def _make_state(self, store):
        st = object.__new__(shared_state_mod.GazonIntelligentSharedState)
        st._store = store
        st._loaded = False
        st._load_lock = asyncio.Lock()
        st.shared_config = {}
        st.products = {}
        return st

    def test_chargements_concurrents_ne_chargent_quune_fois(self):
        loads = {"n": 0}

        class _Store:
            async def async_load(self):
                loads["n"] += 1
                await asyncio.sleep(0)  # point de bascule de la boucle événementielle
                return {"products": {"p1": {"id": "p1", "nom": "Bio"}}}

        st = self._make_state(_Store())

        async def _run():
            await asyncio.gather(st.async_load(), st.async_load())

        asyncio.run(_run())
        self.assertEqual(loads["n"], 1, "le Store ne doit être chargé qu'une fois malgré 2 appels concurrents")
        self.assertEqual(set(st.products), {"p1"})

    def test_products_nest_pas_reassigne_au_second_load(self):
        class _Store:
            async def async_load(self):
                await asyncio.sleep(0)
                return {"products": {"p1": {"id": "p1"}}}

        st = self._make_state(_Store())

        async def _run():
            await st.async_load()
            ref = st.products  # un cerveau garderait cette référence
            await st.async_load()  # 2e appel : garde `_loaded` → pas de réassignation
            return ref is st.products

        self.assertTrue(asyncio.run(_run()), "products ne doit pas être réassigné (référence orpheline)")


class SharedValveMutualExclusionBenchTests(unittest.TestCase):
    """Deux pelouses peuvent piloter le même relais (Sonoff 4CH). Le garde local
    `_watering_session_active` ne voit que ses propres sessions ;
    `_shared_valve_busy_elsewhere` le complète en LECTURE SEULE de l'état des sœurs
    pour refuser un lancement si une autre instance arrose déjà une vanne partagée
    (coordinator:2457). Garde purement ADDITIVE : au pire elle refuse (jamais de
    double-arrosage). En config réelle, la vanne partagée du Potager est neutralisée
    (débit 0) → `_iter_zones_with_rate` ne la yield pas → garde DORMANT."""

    NOW = datetime(2026, 7, 23, 6, 0, tzinfo=timezone.utc)
    DOMAIN = coordinator_mod.DOMAIN

    def _coord(self, *, data, active_session=None):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.entry = _FakeEntry(data=data)
        coord._runtime_state = {"active_irrigation_session": active_session}
        coord._current_utc_datetime = lambda: self.NOW
        return coord

    def _running_session(self, *, zone="switch.shared"):
        return {
            "status": "running",
            "current_passage": 1,
            "passage_count": 1,
            "planned_total_seconds": 600,
            "started_at": self.NOW - timedelta(seconds=30),
            "active_zones": [zone],
            "current_zone": zone,
            "zones_pending": [],
        }

    def _busy(self, me, *others):
        """Place `me` + les sœurs dans un `hass.data[DOMAIN]` commun et évalue le garde."""
        domain_data = {"me": me}
        for idx, other in enumerate(others):
            domain_data[f"other{idx}"] = other
        hass = types.SimpleNamespace(data={self.DOMAIN: domain_data})
        for coord in (me, *others):
            coord.hass = hass
        return coordinator_mod.GazonIntelligentCoordinator._shared_valve_busy_elsewhere(me)

    def test_soeur_active_sur_vanne_partagee_bloque(self):
        # Les DEUX instances déclarent switch.shared à débit > 0 → collision réelle possible.
        me = self._coord(data={"zone_1": "switch.shared", "debit_zone_1": 60.0})
        sister = self._coord(
            data={"zone_1": "switch.shared", "debit_zone_1": 60.0},
            active_session=self._running_session(),
        )
        self.assertTrue(self._busy(me, sister), "une sœur arrosant la vanne partagée doit bloquer")

    def test_soeur_inactive_ne_bloque_pas(self):
        me = self._coord(data={"zone_1": "switch.shared", "debit_zone_1": 60.0})
        sister = self._coord(
            data={"zone_1": "switch.shared", "debit_zone_1": 60.0},
            active_session=None,
        )
        self.assertFalse(self._busy(me, sister))

    def test_pas_de_vanne_partagee_ne_bloque_pas(self):
        # Sœur active mais sur une AUTRE vanne : aucune intersection → pas de blocage.
        me = self._coord(data={"zone_1": "switch.a", "debit_zone_1": 60.0})
        sister = self._coord(
            data={"zone_1": "switch.b", "debit_zone_1": 60.0},
            active_session=self._running_session(zone="switch.b"),
        )
        self.assertFalse(self._busy(me, sister))

    def test_vanne_partagee_neutralisee_cote_soeur_reste_dormant(self):
        # CONFIG RÉELLE : le Potager pointe la vanne partagée mais à débit 0 (neutralisée).
        # `_iter_zones_with_rate` ne la yield pas → intersection vide → garde dormant. « Ne casse rien. »
        me = self._coord(data={"zone_1": "switch.shared", "debit_zone_1": 60.0})
        potager = self._coord(
            data={"zone_1": "switch.shared", "debit_zone_1": 0.0},
            active_session=self._running_session(),
        )
        self.assertFalse(
            self._busy(me, potager),
            "une vanne partagée neutralisée (débit 0) ne doit jamais bloquer l'instance principale",
        )

    def test_session_soeur_reellement_terminee_ne_bloque_pas(self):
        # Session au statut "running" mais en réalité finie (elapsed >= planned, aucun segment
        # en attente) : le prédicat pur `_is_finished_irrigation_session` la neutralise → pas de
        # blocage à tort (sinon une session fantôme d'une sœur gèlerait l'arrosage principal).
        me = self._coord(data={"zone_1": "switch.shared", "debit_zone_1": 60.0})
        stale = self._running_session()
        stale["started_at"] = self.NOW - timedelta(hours=2)  # elapsed 7200 s >> planned 600 s
        stale["active_zones"] = []
        stale["current_zone"] = None
        sister = self._coord(
            data={"zone_1": "switch.shared", "debit_zone_1": 60.0},
            active_session=stale,
        )
        self.assertFalse(self._busy(me, sister))

    def test_instance_unique_court_circuite(self):
        # Une seule entrée dans le domaine → aucun voisin possible → False immédiat.
        me = self._coord(data={"zone_1": "switch.shared", "debit_zone_1": 60.0})
        hass = types.SimpleNamespace(data={self.DOMAIN: {"me": me}})
        me.hass = hass
        self.assertFalse(
            coordinator_mod.GazonIntelligentCoordinator._shared_valve_busy_elsewhere(me)
        )

    def test_garde_bloque_reellement_la_decision_de_lancement(self):
        # Preuve d'intégration : à travers `_should_launch_auto_irrigation`, une sœur arrosant une
        # vanne partagée fait retourner (False, "watering_in_progress").
        me = _build_coordinator()
        me.history = []
        # switch.zone_1 est déclaré à débit 60 par `_build_coordinator` → vanne partagée.
        sister = self._coord(
            data={"zone_1": "switch.zone_1", "debit_zone_1": 60.0},
            active_session=self._running_session(zone="switch.zone_1"),
        )
        me.hass = types.SimpleNamespace(
            data={self.DOMAIN: {"me": me, "sister": sister}},
            states=types.SimpleNamespace(get=lambda _entity_id: None),
        )
        sister.hass = me.hass
        should_launch, reason = me._should_launch_auto_irrigation(_ready_launch_snapshot(me))
        self.assertFalse(should_launch)
        self.assertEqual(reason, "watering_in_progress")


class MowerDistressOverrideTests(unittest.TestCase):
    """L'arrosage de détresse contourne le blocage tondeuse ET la fenêtre horaire.

    Un mécanisme capable d'arroser à 3 h du matin méritait des tests : il n'en avait aucun
    depuis son ajout en 0.20.0.
    """

    @staticmethod
    def _blocked_snapshot(coordinator: object, **overrides: object) -> dict[str, object]:
        snapshot = _ready_launch_snapshot(
            coordinator,
            # Le blocage tondeuse force lui-même la fenêtre à « attendre » : c'est la situation
            # réelle que l'exception doit lever.
            fenetre_optimale="attendre",
            arrosage_auto_autorise=False,
            watering_blocked_by_mower=True,
            irrigation_blocked_but_critical=True,
            watering_block_reason_code="mower_not_stowed",
            block_reason="mower_not_stowed",
            critical_deficit_mm=-4.8,
        )
        snapshot.update(overrides)
        return snapshot

    def _coordinator_with_block_age(self, minutes: float, reason: str = "mower_not_stowed") -> object:
        coordinator = _build_coordinator()
        coordinator.history = []
        coordinator._runtime_state["mower_block_watch"] = {
            "reason": reason,
            "since": (
                coordinator._current_utc_datetime() - timedelta(minutes=minutes)
            ).isoformat(),
        }
        return coordinator

    def test_blocage_tout_juste_apparu_ne_declenche_pas(self) -> None:
        # LA course au démarrage du 29/07/2026 : Home Assistant redémarre, l'intégration lit la
        # tondeuse avant que la sienne ait publié l'entité, et le motif « persistant » s'arme sur
        # une absence de quelques secondes. Le robot était à la station, batterie 100 %.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = self._blocked_snapshot(coordinator, watering_block_reason_code="configured_missing", block_reason="configured_missing")

        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)

        self.assertFalse(should_launch)
        self.assertEqual(reason, "irrigation_blocked")

    def test_blocage_persistant_declenche_larrosage_de_detresse(self) -> None:
        # Robot réellement coincé dehors depuis des heures + déficit critique : un robot mouillé
        # vaut mieux qu'un gazon grillé. L'exception doit bien lever la fenêtre horaire.
        coordinator = self._coordinator_with_block_age(180.0)

        should_launch, _reason = coordinator._should_launch_auto_irrigation(
            self._blocked_snapshot(coordinator)
        )

        self.assertTrue(should_launch)

    def test_changement_de_motif_remet_le_compteur_a_zero(self) -> None:
        # Un motif qui change n'est pas le même blocage qui dure : le compteur repart.
        coordinator = self._coordinator_with_block_age(180.0, reason="ambiguous")

        should_launch, reason = coordinator._should_launch_auto_irrigation(
            self._blocked_snapshot(coordinator)
        )

        self.assertFalse(should_launch)
        self.assertEqual(reason, "irrigation_blocked")

    def test_fin_du_blocage_efface_le_compteur(self) -> None:
        # Le robot rentre : le compteur doit être purgé, sinon un blocage ultérieur hériterait
        # de l'ancienneté du précédent et déclencherait immédiatement.
        coordinator = self._coordinator_with_block_age(180.0)

        coordinator._should_launch_auto_irrigation(_ready_launch_snapshot(coordinator))

        self.assertIsNone(coordinator._runtime_state.get("mower_block_watch"))

    def test_motif_transitoire_jamais_contourne_meme_apres_des_heures(self) -> None:
        # « Tonte en cours » se résout seul : arroser alors tremperait le robot en plein cycle.
        # L'ancienneté ne doit rien y changer.
        coordinator = self._coordinator_with_block_age(180.0, reason="mowing_in_progress")
        snapshot = self._blocked_snapshot(
            coordinator,
            watering_block_reason_code="mowing_in_progress",
            block_reason="mowing_in_progress",
        )

        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)

        self.assertFalse(should_launch)
        self.assertEqual(reason, "irrigation_blocked")


class EtElapsedFractionTests(unittest.TestCase):
    """La fraction d'ET écoulée amorce le DÉBIT du bilan sol, pas seulement l'affichage.

    Son ancien repli à 1.0 quand le soleil est inconnu a débité 6,2 mm d'ETc d'un coup à
    03:11 le 29/07/2026, faisant tomber la réserve de 8,0 à 1,8 mm.
    """

    def _fraction_at(
        self,
        hour: int,
        minute: int,
        sun_context: dict,
        *,
        sunrise: int | None = None,
        sunset: int | None = None,
    ) -> float:
        coordinator = _build_coordinator()
        coordinator._current_datetime = lambda: datetime(
            2026, 7, 29, hour, minute, tzinfo=timezone.utc
        )
        if sunrise is not None or sunset is not None:
            # Le stub `dt_util` des tests n'a pas `parse_datetime` : on injecte directement les
            # minutes, ce qui teste bien la logique de `_et_elapsed_fraction` elle-même.
            coordinator._sunrise_minute_from_context = lambda _ctx: sunrise
            coordinator._sunset_minute_from_context = lambda _ctx: sunset
        return coordinator._et_elapsed_fraction(sun_context)

    def test_soleil_inconnu_en_pleine_nuit_ne_debite_rien(self) -> None:
        # LE défaut : contexte solaire vide (sun.sun pas encore publié au démarrage) à 3 h du
        # matin. L'ancien repli répondait 1.0 = « toute la journée est écoulée ».
        self.assertEqual(self._fraction_at(3, 11, {}), 0.0)

    def test_soleil_inconnu_en_milieu_de_journee_reste_plausible(self) -> None:
        # Repli sur la journée civile 06:00-21:00 : à 13:30 on attend environ la moitié.
        fraction = self._fraction_at(13, 30, {})
        self.assertGreater(fraction, 0.4)
        self.assertLess(fraction, 0.6)

    def test_soleil_inconnu_apres_la_journee_civile_vaut_bien_un(self) -> None:
        # Tard le soir, « journée écoulée » redevient la bonne réponse.
        self.assertEqual(self._fraction_at(22, 30, {}), 1.0)

    def test_soleil_connu_avant_le_lever(self) -> None:
        # Lever 06:33, coucher 21:35 (le vrai 29/07/2026).
        self.assertEqual(self._fraction_at(3, 11, {}, sunrise=393, sunset=1295), 0.0)

    def test_soleil_connu_apres_le_coucher(self) -> None:
        self.assertEqual(self._fraction_at(23, 0, {}, sunrise=393, sunset=1295), 1.0)

    def test_soleil_connu_a_midi(self) -> None:
        fraction = self._fraction_at(12, 0, {}, sunrise=393, sunset=1295)
        self.assertAlmostEqual(fraction, (720 - 393) / (1295 - 393), places=3)


class PlanCanoniqueSnapshotFraisTests(unittest.TestCase):
    """Le plan doit lire le fractionnement du snapshot FRAIS, pas du cycle précédent.

    `_maybe_schedule_auto_irrigation` tourne à l'intérieur de `_async_update_data`, donc avant que
    Home Assistant n'affecte le nouveau `self.data`. Pendant le lancement, `self.data` porte encore
    le cycle précédent — alors que l'objectif vient du snapshot frais.

    Le biais allait toujours dans le mauvais sens : le fractionnement n'apparaît qu'au-delà du
    seuil, et c'est la transition « dose nulle → grosse dose » (expiration du cooldown 24 h dans la
    fenêtre du matin, cas quotidien) qui le perdait.
    """

    def test_le_fractionnement_frais_prime_sur_le_cycle_precedent(self) -> None:
        coordinator = _build_coordinator()
        coordinator.history = []
        # Cycle PRÉCÉDENT : dose nulle (cooldown actif) → aucun fractionnement publié.
        coordinator.data = {
            "objectif_mm": 0.0,
            "watering_passages": 1,
            "watering_pause_minutes": 0,
        }
        # Cycle qui DÉCLENCHE : cooldown expiré, grosse dose → 2 passages + pause.
        snapshot = _ready_launch_snapshot(
            coordinator,
            objectif_mm=11.2,
            watering_passages=2,
            watering_pause_minutes=25,
        )

        plan = coordinator._get_canonical_watering_plan(objectif_mm=11.2, snapshot=snapshot)

        self.assertIsNotNone(plan, "aucun plan construit")
        self.assertEqual(plan.passage_count, 2, "le plan a repris le cycle précédent (1 passage)")
        self.assertEqual(plan.pause_between_passages_s, 25 * 60)

    def test_repli_sur_self_data_quand_le_snapshot_ne_porte_pas_le_fractionnement(self) -> None:
        # Non-régression : les appelants qui ne passent pas de snapshot doivent continuer à lire
        # `self.data` (c'est le cas du service d'arrosage manuel).
        coordinator = _build_coordinator()
        coordinator.history = []
        coordinator.data = {
            "objectif_mm": 11.2,
            "watering_passages": 2,
            "watering_pause_minutes": 25,
        }

        plan = coordinator._get_canonical_watering_plan(objectif_mm=11.2)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.passage_count, 2)
        self.assertEqual(plan.pause_between_passages_s, 25 * 60)


class TestStopIrrigation(unittest.IsolatedAsyncioTestCase):
    """Service `stop_irrigation` — arrêt d'un cycle en cours.

    Trois propriétés doivent tenir ENSEMBLE, sinon l'arrêt laisse le système dans un état
    pire que l'arrosage qu'il interrompt : vanne fermée, session purgée, eau enregistrée.
    """

    def _coordinateur(self) -> object:
        coordinator = _build_coordinator()
        coordinator.history = []
        coordinator._persist_runtime_state = AsyncMock()
        coordinator.async_record_watering = AsyncMock()
        coordinator.async_record_user_action = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        coordinator._auto_irrigation_task = None
        return coordinator

    def _session(self, coordinator, *, ecoule_s: float = 0.0) -> dict:
        """Session à mi-parcours : zone 1 terminée (4 mm), zone 2 en cours."""
        return {
            "source": "auto_irrigation",
            "current_passage": 1,
            "current_zone": "switch.zone_2",
            "current_zone_index": 1,
            "current_zone_started_at": coordinator._current_utc_datetime()
            - timedelta(seconds=ecoule_s),
            "zones_done": [
                {"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 4.0, "duration_s": 240}
            ],
            "zones_pending": [
                {"passage": 1, "zone_index": 1, "zone": "switch.zone_2", "duration_s": 600, "mm": 6.0}
            ],
        }

    async def test_sans_arrosage_en_cours_ne_fait_rien(self) -> None:
        """Idempotence : appeler le service au repos ne doit rien enregistrer ni rien casser."""
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(None)

        resultat = await coordinator.async_stop_irrigation()

        self.assertFalse(resultat["stopped"])
        self.assertEqual(resultat["reason"], "aucun_arrosage_en_cours")
        coordinator.async_record_watering.assert_not_awaited()

    async def test_la_session_est_purgee(self) -> None:
        """Le `finally` de l'exécuteur NE purge PAS la session quand la tâche est annulée
        (c'est voulu : l'arrêt de Home Assistant doit pouvoir reprendre au redémarrage).
        Un arrêt volontaire veut l'inverse — sans purge ici, la reprise relancerait le cycle."""
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(self._session(coordinator))

        await coordinator.async_stop_irrigation()

        self.assertIsNone(coordinator._get_active_irrigation_session())
        self.assertIsNone(coordinator._auto_irrigation_task)

    async def test_leau_deja_versee_est_enregistree(self) -> None:
        """Sans ça, le bilan du sol ne voit pas cette eau et le système réarrose."""
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(self._session(coordinator))

        resultat = await coordinator.async_stop_irrigation()

        self.assertTrue(resultat["stopped"])
        coordinator.async_record_watering.assert_awaited_once()
        kwargs = coordinator.async_record_watering.await_args.kwargs
        self.assertEqual(kwargs["total_mm"], 4.0)
        self.assertEqual(kwargs["watering_cause"], "arret_manuel")
        # La source d'origine est conservée : les garde-fous comptent cette eau comme les autres.
        self.assertEqual(kwargs["source"], "auto_irrigation")

    async def test_la_zone_interrompue_est_creditee_au_prorata(self) -> None:
        """Elle n'est PAS dans `zones_done` (l'enregistrement se fait après le try/finally).
        Sans reconstitution, arrêter à mi-zone perdrait cette eau."""
        coordinator = self._coordinateur()
        # 300 s écoulées sur un segment de 600 s valant 6 mm -> 3 mm.
        coordinator._set_active_irrigation_session(self._session(coordinator, ecoule_s=300.0))

        resultat = await coordinator.async_stop_irrigation()

        self.assertEqual(resultat["applied_mm"], 7.0)  # 4 (zone 1) + 3 (zone 2 à moitié)
        zones = coordinator.async_record_watering.await_args.kwargs["zones"]
        self.assertEqual(len(zones), 2)
        self.assertTrue(zones[1]["interrupted"])
        self.assertEqual(zones[1]["mm"], 3.0)

    async def test_le_prorata_ne_depasse_jamais_le_segment_prevu(self) -> None:
        """Une horloge qui saute ne doit pas créditer plus que ce que la vanne pouvait délivrer."""
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(self._session(coordinator, ecoule_s=99_999.0))

        resultat = await coordinator.async_stop_irrigation()

        self.assertEqual(resultat["applied_mm"], 10.0)  # 4 + 6 (segment plein, pas plus)

    async def test_un_arret_immediat_nenregistre_rien(self) -> None:
        """Zéro seconde écoulée sur la zone en cours et aucune zone terminée : rien à créditer."""
        coordinator = self._coordinateur()
        session = self._session(coordinator, ecoule_s=0.0)
        session["zones_done"] = []
        coordinator._set_active_irrigation_session(session)

        resultat = await coordinator.async_stop_irrigation()

        self.assertTrue(resultat["stopped"])
        self.assertEqual(resultat["applied_mm"], 0.0)
        coordinator.async_record_watering.assert_not_awaited()

    async def test_la_tache_en_cours_est_annulee(self) -> None:
        """C'est l'annulation qui déclenche le `finally` fermant la vanne."""
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(self._session(coordinator))

        async def _cycle_sans_fin() -> None:
            await asyncio.sleep(3600)

        tache = asyncio.get_running_loop().create_task(_cycle_sans_fin())
        coordinator._auto_irrigation_task = tache

        await coordinator.async_stop_irrigation()

        self.assertTrue(tache.cancelled())


class TestVeilleurDeVanne(unittest.IsolatedAsyncioTestCase):
    """L'exécuteur ne dort plus en aveugle pendant un segment d'arrosage.

    Il comptait la dose entière même si le relais retombait — sécurité firmware, coupure,
    commande externe. Des millimètres fantômes étaient crédités au bilan du sol pour de l'eau
    jamais versée, et le gazon séchait pendant que le modèle le croyait arrosé.
    """

    def _coordinateur(self, etats: dict[str, str]):
        coordinator = _build_coordinator()
        appels: list[dict] = []

        async def _async_call(domain, service, data=None, blocking=False):
            appels.append({"domain": domain, "service": service, "data": dict(data or {})})
            if service == "turn_on":
                etats[str((data or {}).get("entity_id"))] = "on"

        coordinator.hass = types.SimpleNamespace(
            services=types.SimpleNamespace(async_call=_async_call),
            states=types.SimpleNamespace(
                get=lambda eid: types.SimpleNamespace(state=etats.get(eid))
                if eid in etats
                else None
            ),
        )
        coordinator._appels = appels
        return coordinator

    async def test_vanne_qui_reste_ouverte_compte_tout_le_temps(self) -> None:
        etats = {"switch.zone_1": "on"}
        coordinator = self._coordinateur(etats)
        with patch.object(coordinator_mod.asyncio, "sleep", new=AsyncMock()):
            ouverte = await coordinator._attendre_zone_ouverte("switch.zone_1", 60.0, {})
        self.assertAlmostEqual(ouverte, 60.0, places=1)

    async def test_vanne_qui_retombe_est_relancee_une_fois(self) -> None:
        etats = {"switch.zone_1": "off"}      # elle a été vue ouverte, puis retombe
        coordinator = self._coordinateur(etats)
        vues = {"n": 0}

        def _get(eid):
            vues["n"] += 1
            # Ouverte aux deux premiers contrôles, fermée ensuite.
            return types.SimpleNamespace(state="on" if vues["n"] <= 2 else etats.get(eid))

        coordinator.hass.states = types.SimpleNamespace(get=_get)
        with patch.object(coordinator_mod.asyncio, "sleep", new=AsyncMock()):
            ouverte = await coordinator._attendre_zone_ouverte("switch.zone_1", 300.0, {})

        relances = [a for a in coordinator._appels if a["service"] == "turn_on"]
        self.assertEqual(len(relances), 1, "la vanne doit être relancée exactement une fois")
        self.assertLess(ouverte, 300.0, "le temps vanne fermée ne doit pas être compté")

    async def test_sans_preuve_douverture_le_veilleur_ne_fait_rien(self) -> None:
        """Un interrupteur qui ne rapporte pas son état ne doit PAS abréger l'arrosage.

        Sinon tous les segments seraient coupés et plus rien ne serait arrosé — une régression
        bien pire que le défaut corrigé.
        """
        etats = {"switch.zone_1": "off"}      # jamais vue ouverte
        coordinator = self._coordinateur(etats)
        with patch.object(coordinator_mod.asyncio, "sleep", new=AsyncMock()):
            ouverte = await coordinator._attendre_zone_ouverte("switch.zone_1", 60.0, {})
        self.assertAlmostEqual(ouverte, 60.0, places=1)
        self.assertEqual([a for a in coordinator._appels if a["service"] == "turn_on"], [])

    async def test_entite_indisponible_ne_vaut_pas_fermee(self) -> None:
        """Vanne VUE OUVERTE, puis entité indisponible : c'est le scénario du redémarrage.

        Le relais n'a pas bougé, seule l'entité a disparu. Conclure « fermée » couperait le
        comptage d'une eau réellement versée ET déclencherait une relance inutile.

        ⚠️ Le scénario doit commencer OUVERT : en partant d'emblée sur `unavailable`, la garde
        « jamais vue ouverte » couvre le cas et le test ne prouve plus rien — vérifié par
        mutation, il passait aussi avec `unavailable` traité comme fermée.
        """
        coordinator = self._coordinateur({})
        vues = {"n": 0}

        def _get(eid):
            vues["n"] += 1
            return types.SimpleNamespace(state="on" if vues["n"] <= 1 else "unavailable")

        coordinator.hass.states = types.SimpleNamespace(get=_get)
        with patch.object(coordinator_mod.asyncio, "sleep", new=AsyncMock()):
            ouverte = await coordinator._attendre_zone_ouverte("switch.zone_1", 60.0, {})

        self.assertAlmostEqual(ouverte, 60.0, places=1)
        self.assertEqual(
            [a for a in coordinator._appels if a["service"] == "turn_on"], [],
            "une entité indisponible ne doit pas provoquer de relance",
        )

    def test_la_dose_suit_le_temps_reellement_ouvert(self) -> None:
        coordinator = _build_coordinator()
        zone = types.SimpleNamespace(zone="switch.zone_1", rate_mm_h=12.0, duration_s=600.0, mm=2.0)

        plein = coordinator._build_zone_execution_record(zone=zone, passage=1, order=1)
        moitie = coordinator._build_zone_execution_record(
            zone=zone, passage=1, order=1, effective_duration_s=300.0
        )

        self.assertEqual(plein["mm"], 2.0)
        self.assertNotIn("interrupted", plein)
        self.assertEqual(moitie["mm"], 1.0)        # moitié du temps -> moitié de la dose
        self.assertTrue(moitie["interrupted"])
        self.assertEqual(moitie["planned_duration_s"], 600)


class SessionPayloadPorteLeDebutTests(unittest.TestCase):
    """Le payload de fin de session doit transporter le DÉBUT du cycle.

    ⚠️ Une première série de tests ne vérifiait que la LECTURE (`_session_when_text` sur un
    dictionnaire écrit à la main). Supprimer l'écriture de `started_at` côté coordinateur
    passait au vert : le calcul était juste, la valeur n'était jamais enregistrée. C'est le
    piège récurrent de la semaine — tester la déclaration au lieu du câblage.
    """

    def test_le_payload_contient_debut_ET_fin(self) -> None:
        from datetime import datetime, timezone

        debut = datetime(2026, 8, 4, 1, 45, 13, tzinfo=timezone.utc)
        fin = datetime(2026, 8, 4, 3, 18, 13, tzinfo=timezone.utc)
        coord = _build_coordinator()
        _bind_irrigation_runtime_methods(coord, "_build_watering_session_payload", "_round_runtime_mm")
        coord._watering_session = {
            "started_at": debut,
            "last_inactive_at": fin,
            "active_zones": {},
            "target_mm": 7.7,
            "zones": {
                "switch.zone_1": {
                    "order": 1, "zone": "switch.zone_1", "entity_id": "switch.zone_1",
                    "rate_mm_h": 14.0, "duration_seconds": 1980.0, "mm": 7.7,
                },
            },
        }
        payload = coord._build_watering_session_payload()
        self.assertIsNotNone(payload, "la session n'a produit aucun enregistrement")
        self.assertEqual(payload["started_at"], debut,
                         "le début du cycle n'est pas transporté")
        self.assertEqual(payload["ended_at"], fin)
        self.assertEqual(payload["date_action"], fin.date())


class LeCoordinateurTransmetLEtatMeteoTests(unittest.TestCase):
    """Le test de CÂBLAGE — c'est son absence qui a laissé le défaut vivre cinq mois.

    `_get_weather_profile` appelait `profile_from_attributes(state.attributes)` sans jamais
    transmettre `state.state`. Or chez Home Assistant, la condition d'une entité `weather.*`
    est son ÉTAT. Des tests existaient bien sur `extract_weather_profile`, mais ils lui
    passaient un dictionnaire contenant `"condition"` — une forme que la production ne produit
    jamais. Ils vérifiaient une DÉCLARATION, pas le CHEMIN RÉEL.
    """

    class _EtatMeteo:
        """Ce que Home Assistant expose vraiment pour une entité `weather.*`."""

        def __init__(self, etat: str) -> None:
            self.state = etat
            self.attributes = {
                "temperature": 17.0,
                "humidity": 92,
                "wind_speed": 11.0,
                "cloud_coverage": 98,
            }

    def _coordinateur(self, etat_meteo: str | None):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        etats = {"weather.forecast_maison": self._EtatMeteo(etat_meteo)} if etat_meteo else {}
        coord.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=etats.get)
        )
        return coord

    def test_la_condition_arrive_jusqu_au_profil(self) -> None:
        coord = self._coordinateur("rainy")
        profil = coord._get_weather_profile("weather.forecast_maison")
        self.assertEqual(
            profil.get("weather_condition"), "rainy",
            "l'état de l'entité météo ne traverse pas le coordinateur",
        )

    def test_le_garde_pluie_s_arme_de_bout_en_bout(self) -> None:
        """De l'entité Home Assistant jusqu'au booléen qui bloque l'arrosage."""
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        coord = self._coordinateur("rainy")
        profil = coord._get_weather_profile("weather.forecast_maison")
        self.assertTrue(guidance.is_active_rain_weather(profil))

        clair = self._coordinateur("sunny")
        self.assertFalse(
            guidance.is_active_rain_weather(clair._get_weather_profile("weather.forecast_maison"))
        )

    def test_une_entite_absente_ne_casse_rien(self) -> None:
        coord = self._coordinateur(None)
        self.assertEqual(coord._get_weather_profile("weather.forecast_maison"), {})
        self.assertEqual(coord._get_weather_profile(None), {})
