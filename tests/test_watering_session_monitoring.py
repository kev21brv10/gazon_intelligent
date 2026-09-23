from __future__ import annotations

import asyncio
import importlib
import json
import unittest
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import types
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo


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
brain_mod = importlib.import_module("custom_components.gazon_intelligent.gazon_brain")
shared_state_mod = importlib.import_module("custom_components.gazon_intelligent.shared_state")
watering_plan_mod = importlib.import_module("custom_components.gazon_intelligent.watering_plan")
mower_adapter_mod = importlib.import_module("custom_components.gazon_intelligent.mower_adapter")
# ⚠️ Importé ICI et pas dans un test : `test_init.py` remplace des entrées de `sys.modules`
# par de faux modules. Une réimportation tardive récupère le faux — le test passe seul et
# tombe (ou pire, ment) quand toute la suite tourne.
mower_coordination_mod = importlib.import_module(
    "custom_components.gazon_intelligent.mower_coordination"
)
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


def _dt_util_avec_fuseau(fonction, *, heures: int):
    """Donne au `dt_util` lu par `fonction` un vrai parseur de dates et un fuseau fixe.

    Le stub des tests n'a pas `parse_datetime`. On patche les globales du module qui LIT le nom
    (piège du réimport) ; tout le reste (`now`, `utcnow`…) est délégué au stub d'origine.
    """
    reel = fonction.__globals__["dt_util"]
    fuseau = timezone(timedelta(hours=heures))

    class _DtUtil:
        def __getattr__(self, nom: str):
            return getattr(reel, nom)

        @staticmethod
        def parse_datetime(valeur):
            try:
                return datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
            except ValueError:
                return None

        @staticmethod
        def as_local(valeur):
            return valeur.astimezone(fuseau)

    return patch.dict(fonction.__globals__, {"dt_util": _DtUtil()})


class CoordinatorFacadeExtractionTests(unittest.TestCase):
    def test_les_lectures_etat_tolerent_un_coordinateur_sans_hass_si_entite_absente(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)

        self.assertIsNone(coord._get_float_state(None))
        self.assertIsNone(coord._get_text_state(None))
        self.assertIsNone(coord._get_bool_state(None))

    def test_minutes_creditables_garde_le_plafond_unique_de_quinze_minutes(self) -> None:
        coord = _build_coordinator()
        maintenant = datetime(2026, 9, 14, 8, 40, tzinfo=timezone.utc)

        self.assertEqual(coord._minutes_creditables("2026-09-14T08:30:00Z", maintenant), 10.0)
        self.assertEqual(coord._minutes_creditables("2026-09-14T08:00:00Z", maintenant), 0.0)
        # Frontière exacte (`0 < écart <= plafond`) : 15 min se créditent, une seconde de plus non.
        self.assertEqual(coord._minutes_creditables("2026-09-14T08:25:00Z", maintenant), 15.0)
        self.assertEqual(coord._minutes_creditables("2026-09-14T08:24:59Z", maintenant), 0.0)

    def test_feedback_observation_survit_dans_la_charge_debug(self) -> None:
        coord = _build_coordinator()
        coord.history = []
        coord.memory = {"feedback_observation": "vu par l'utilisateur"}
        coord._current_date = lambda: date(2026, 9, 14)

        payload = coord._build_observability_payload({"phase_active": "Normal"})

        self.assertEqual(payload["feedback_observation"], "vu par l'utilisateur")

    def test_runtime_id_utilise_l_horodatage_utc_pas_local_suffixe_z(self) -> None:
        coord = _build_coordinator()
        coord._current_datetime = lambda: datetime(2026, 9, 14, 12, 30, tzinfo=timezone(timedelta(hours=2)))
        coord._current_utc_datetime = lambda: datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc)

        identifiant = coord._new_runtime_id("sess")

        self.assertIn("_20260914T103000Z_", identifiant)
        self.assertNotIn("_20260914T123000Z_", identifiant)

    def test_objectif_courant_lit_self_result_avant_self_data(self) -> None:
        coord = _build_coordinator()
        coord.brain.last_result = types.SimpleNamespace(
            objectif_arrosage="4.2",
            extra={"objectif_mm": 3.0},
        )
        coord.data = {"objectif_mm": 2.0}

        self.assertEqual(coord._current_objective_mm(), 4.2)

    def test_estimation_rosee_passe_par_la_facade_du_coordinateur(self) -> None:
        coord = _build_coordinator()

        self.assertEqual(coord._estimate_rosee({"weather_dew_point": 18.0}, 20.0, 50.0), 1.0)
        # Chemin humidité : l'argument doit traverser la façade.
        self.assertEqual(coord._estimate_rosee({}, 20.0, 92.0), 0.8)
        self.assertIsNone(coord._estimate_rosee({}, 20.0, 50.0))

    def test_facades_soleil_lisent_lever_et_coucher_en_heure_locale(self) -> None:
        # Ces minutes fixent la fraction d'ET écoulée, donc le débit du bilan du sol. Les tests de
        # `_et_elapsed_fraction` remplacent ces deux façades par des lambdas : rien ne les tenait.
        coord = _build_coordinator()
        contexte = {
            "sun_next_rising": "2026-09-15T05:21:00Z",
            "sun_next_setting": "2026-09-15T17:58:00Z",
        }

        with _dt_util_avec_fuseau(type(coord)._sun_event_minute_from_context, heures=2):
            self.assertEqual(coord._sunrise_minute_from_context(contexte), 7 * 60 + 21)
            self.assertEqual(coord._sunset_minute_from_context(contexte), 19 * 60 + 58)

    def test_cycle_de_donnees_transmet_le_coucher_du_soleil_et_la_rosee_estimee(self) -> None:
        """Les points d'appel de `_calculer_donnees`, pas seulement les façades.

        Le coucher du soleil nourrit le garde-fou « séchage avant la nuit » de l'arrosage du
        soir ; la rosée estimée nourrit le risque fongique. Lire la clé du lever à la place, ou
        perdre l'estimation, laissait toute la suite verte.
        """
        coordinator = _build_update_data_coordinator(weather_temperature=20.0)
        captures: dict[str, object] = {}
        calcul_original = coordinator.brain.compute_snapshot

        def _capturer(**kwargs):
            captures.update(kwargs)
            return calcul_original(**kwargs)

        coordinator.brain.compute_snapshot = _capturer
        coordinator._get_sun_context = lambda: {
            "sun_next_rising": "2026-09-15T05:21:00Z",
            "sun_next_setting": "2026-09-15T17:58:00Z",
        }
        appels_rosee: list[tuple[object, object]] = []

        def _rosee(weather_profile, temperature, humidite, point_de_rosee=None):  # noqa: ARG001
            appels_rosee.append((temperature, humidite))
            return 0.42

        coordinator._estimate_rosee = _rosee

        with _dt_util_avec_fuseau(type(coordinator)._sun_event_minute_from_context, heures=2):
            asyncio.run(coordinator._async_update_data())

        self.assertEqual(captures["weather_profile"]["sunset_minute"], 19 * 60 + 58)
        self.assertEqual(captures["rosee"], 0.42)
        # Sans capteur d'humidité, c'est l'humidité de la météo (55 %) qui doit arriver.
        self.assertEqual(appels_rosee, [(captures["temperature"], 55.0)])

    def test_evenement_runtime_passe_ses_valeurs_au_serialiseur(self) -> None:
        coord = _build_coordinator()
        debut = datetime(2026, 9, 15, 5, 45, tzinfo=timezone(timedelta(hours=2)))

        payload = coord._build_runtime_payload_for_event(
            {"session_id": "sess_1", "status": "running"},
            zone="switch.zone_1",
            started_at=debut,
        )

        self.assertEqual(payload["session_id"], "sess_1")
        self.assertEqual(payload["zone"], "switch.zone_1")
        # Une date part en ISO UTC, comme dans l'état runtime persisté.
        self.assertEqual(payload["started_at"], "2026-09-15T03:45:00+00:00")


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
    # ⚠️ Depuis la 0.84.0 une action de l'utilisateur passe par `async_refresh` (immédiat).
    coord.async_refresh = AsyncMock()
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
    coordinator._estimate_rosee = lambda weather_profile, temperature, humidite, point_de_rosee=None: 0.0  # noqa: ARG005
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

    def test_le_cycle_confie_au_cerveau_les_reglages_de_l_entree(self) -> None:
        # Le chemin de production : options de l'entrée → nettoyage → `brain.reglages`, AVANT le
        # calcul. Une valeur égale au conseil n'est pas transmise (elle ne change rien).
        coordinator = _build_update_data_coordinator(weather_temperature=20.0)
        brain = coordinator.brain
        calcul = type(brain).compute_snapshot
        vus: list[dict[str, object]] = []

        def compute_snapshot(**kwargs):
            vus.append(dict(getattr(brain, "reglages", {}) or {}))
            return calcul(brain, **kwargs)

        brain.compute_snapshot = compute_snapshot
        coordinator.entry.options = {"reglages": {"tonte_max_par_jour": 3, "tonte_vent_a_eviter": 20}}
        asyncio.run(coordinator._async_update_data())
        self.assertEqual(vus, [{"tonte_max_par_jour": 3}])

    def test_relaunch_cooldown_suit_le_reglage_de_la_page(self) -> None:
        # Page « Gazon » : délai de relance réglé à 1 h dans les options de l'entrée. Un cycle fini
        # il y a 2 h ne bloque plus ; sans le réglage, les 6 h du moteur le bloquent encore.
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = _ready_launch_snapshot(coordinator)
        coordinator._runtime_state["last_auto_irrigation_completed_at"] = (
            coordinator._current_utc_datetime() - timedelta(hours=2)
        )
        coordinator.entry.options = {"reglages": {"arrosage_delai_relance": 1}}
        self.assertEqual(coordinator._should_launch_auto_irrigation(snapshot), (True, "ready"))
        coordinator.entry.options = {}
        self.assertEqual(coordinator._should_launch_auto_irrigation(snapshot), (False, "relaunch_cooldown"))

    def test_les_creneaux_des_graines_suivent_l_ouverture_reglee(self) -> None:
        coordinator = _build_coordinator()
        coordinator.history = []
        snapshot = {
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.5,
            "daily_cycles_target": 3,
            "cycle_spacing_minutes": 120,
            "seeding_transition_ready": False,
        }
        current = datetime(2026, 4, 27, 7, 30, tzinfo=timezone.utc)
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current
        coordinator._current_date = lambda: current.date()
        coordinator._local_datetime_text = lambda moment: moment.isoformat()
        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        self.assertEqual((progress["next_due_at"].hour, progress["next_due_at"].minute), (10, 0))
        coordinator.entry.options = {"reglages": {"graines_fenetre_debut": 8 * 60}}
        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        self.assertEqual((progress["next_due_at"].hour, progress["next_due_at"].minute), (8, 0))
        self.assertEqual(progress["cycle_slots_minutes"], (480, 720, 960))

    def test_le_suivi_des_graines_est_publie(self) -> None:
        # 0.96.1 : les neuf clés `semis_*` valaient toujours None dans les données publiées,
        # `DecisionResult` ne les portant pas.
        coordinator = _build_coordinator()
        current = datetime(2026, 9, 17, 16, 30, tzinfo=timezone.utc)
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current
        coordinator._current_date = lambda: current.date()
        coordinator._local_datetime_text = lambda moment: moment.isoformat()
        coordinator.history = [
            {
                "type": "arrosage", "date": "2026-09-17",
                "started_at": f"2026-09-17T{heure}:00+00:00", "recorded_at": f"2026-09-17T{heure}:00+00:00",
                "watering_strategy": "semis_frequent", "objective_scope": "surface_cycle",
            }
            for heure in ("06:30", "08:44", "10:58", "13:12")
        ]
        graines = {
            "watering_strategy": "semis_frequent", "objective_scope": "surface_cycle",
            "watering_stage": "germination", "surface_cycle_mm": 1.2, "daily_cycles_target": 3,
            "cycle_spacing_minutes": 120, "seeding_transition_ready": False,
        }
        publie = coordinator._build_public_snapshot_data(
            graines, pluie_demain_source="meteo_forecast", temperature=21.0, temperature_source="capteur",
            temperature_reference_hydrique=21.0, forecast_summary={}, et0_source="capteur",
        )
        self.assertEqual(publie["semis_followup_state"], "complete")
        self.assertEqual(publie["semis_cycles_completed_today"], 4)
        self.assertEqual(publie["semis_cycles_remaining_today"], 0)
        self.assertEqual(publie["semis_daily_cycles_target"], 3)
        self.assertEqual(publie["semis_last_cycle_at"], "2026-09-17T13:12:00+00:00")
        self.assertEqual(publie["semis_followup_due_at"], "2026-09-18T10:00:00+00:00")
        self.assertEqual(publie["semis_followup_due_display"], "2026-09-18T10:00:00+00:00")

        coordinator.history = coordinator.history[:2]
        publie = coordinator._build_public_snapshot_data(
            graines, pluie_demain_source="meteo_forecast", temperature=21.0, temperature_source="capteur",
            temperature_reference_hydrique=21.0, forecast_summary={}, et0_source="capteur",
        )
        self.assertEqual(publie["semis_cycles_remaining_today"], 1)
        self.assertEqual(publie["semis_followup_state"], "ready")

        normal = coordinator._build_public_snapshot_data(
            {"watering_strategy": "deplete_to_mad"}, pluie_demain_source="meteo_forecast", temperature=21.0,
            temperature_source="capteur", temperature_reference_hydrique=21.0, forecast_summary={}, et0_source="capteur",
        )
        self.assertFalse([cle for cle, valeur in normal.items() if cle.startswith("semis_") and valeur is not None])

    def test_l_espacement_des_graines_part_du_debut_du_cycle(self) -> None:
        coordinator = _build_coordinator()
        snapshot = {
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.8,
            "daily_cycles_target": 4,
            "cycle_spacing_minutes": 120,
            "seeding_transition_ready": False,
        }
        coordinator.history = [{
            "type": "arrosage",
            "date": "2026-04-27",
            "started_at": "2026-04-27T10:00:00+00:00",
            "recorded_at": "2026-04-27T10:21:00+00:00",
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "surface_cycle_mm": 1.8,
        }]
        current = datetime(2026, 4, 27, 11, 0, tzinfo=timezone.utc)
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current
        coordinator._current_date = lambda: current.date()

        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        self.assertEqual(progress["last_cycle_at"], datetime(2026, 4, 27, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(progress["next_due_at"], datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc))

    def test_un_redemarrage_pendant_l_attente_garde_le_vrai_prochain_cycle(self) -> None:
        """Le suivi est reconstruit depuis l'historique persisté, pas depuis un minuteur en RAM."""
        snapshot = {
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.5,
            "daily_cycles_target": 4,
            "cycle_spacing_minutes": 120,
            "seeding_transition_ready": False,
        }
        historique = [{
            "type": "arrosage",
            "date": "2026-09-18",
            "started_at": "2026-09-18T08:30:00+00:00",
            "recorded_at": "2026-09-18T08:48:00+00:00",
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "surface_cycle_mm": 1.5,
        }]
        maintenant = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)

        def progression_apres_demarrage():
            coord = _build_coordinator()
            coord.entry.options = {
                "reglages": {"graines_fenetre_debut": 8 * 60 + 30, "graines_fenetre_fin": 16 * 60}
            }
            coord.history = [dict(evenement) for evenement in historique]
            coord._current_datetime = lambda: maintenant
            coord._current_utc_datetime = lambda: maintenant
            coord._current_date = lambda: maintenant.date()
            return coord._semis_cycle_progress(snapshot)

        avant = progression_apres_demarrage()
        apres = progression_apres_demarrage()
        assert avant is not None and apres is not None
        self.assertEqual(avant["state"], "waiting")
        self.assertEqual(avant["next_due_at"], datetime(2026, 9, 18, 10, 40, tzinfo=timezone.utc))
        self.assertEqual(avant["cycle_slots_minutes"], (510, 640, 770, 900))
        self.assertEqual(
            {cle: apres[cle] for cle in ("state", "next_due_at", "cycles_completed_today", "cycles_remaining_today")},
            {cle: avant[cle] for cle in ("state", "next_due_at", "cycles_completed_today", "cycles_remaining_today")},
        )

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
        coordinator._estimate_rosee = lambda weather_profile, temperature, humidite, point_de_rosee=None: 0.0  # noqa: ARG001
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
        coordinator._estimate_rosee = lambda weather_profile, temperature, humidite, point_de_rosee=None: 0.0  # noqa: ARG001
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

    def test_async_set_normal_preserves_safety_lock(self) -> None:
        # Changer de mode n'est pas confirmer que les vannes ont ete verifiees.
        coordinator = _build_coordinator()
        coordinator._runtime_state["auto_irrigation_safety_lock"] = True
        coordinator.brain.set_normal = lambda: None
        coordinator._async_save_state = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        coordinator.async_refresh = AsyncMock()

        asyncio.run(coordinator.async_set_normal())

        self.assertTrue(coordinator._runtime_state["auto_irrigation_safety_lock"])

    def test_clear_irrigation_safety_lock_preserves_seed_mode(self) -> None:
        coordinator = _build_coordinator()
        maintenant = datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)
        coordinator.hass = types.SimpleNamespace(
            states=_FakeStatesWithAll(
                {
                    "switch.zone_1": _FakeState("off", maintenant),
                    "switch.zone_2": _FakeState("off", maintenant),
                }
            )
        )
        coordinator._runtime_state["auto_irrigation_safety_lock"] = True
        coordinator.brain.set_normal = unittest.mock.Mock()
        coordinator._async_save_state = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        coordinator.async_refresh = AsyncMock()

        asyncio.run(coordinator.async_clear_irrigation_safety_lock())

        self.assertFalse(coordinator._runtime_state["auto_irrigation_safety_lock"])
        coordinator.brain.set_normal.assert_not_called()

    def test_clear_irrigation_safety_lock_refuses_an_active_zone(self) -> None:
        coordinator = _build_coordinator()
        maintenant = datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)
        coordinator.hass = types.SimpleNamespace(
            states=_FakeStatesWithAll(
                {
                    "switch.zone_1": _FakeState("on", maintenant),
                    "switch.zone_2": _FakeState("off", maintenant),
                }
            )
        )
        coordinator._runtime_state["auto_irrigation_safety_lock"] = True
        coordinator._async_save_state = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        coordinator.async_refresh = AsyncMock()

        with self.assertRaisesRegex(Exception, "zone d.arrosage est encore active"):
            asyncio.run(coordinator.async_clear_irrigation_safety_lock())

        self.assertTrue(coordinator._runtime_state["auto_irrigation_safety_lock"])
        coordinator._async_save_state.assert_not_awaited()

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

        # ── Deuxième passage : un relais qui retombe à mi-segment ─────────────────────
        # ⚠️ La proratisation de `_build_zone_execution_record` ne servait à RIEN ici : la
        # fin de cycle enregistrait `plan.objective_mm`, l'objectif PRÉVU. L'historique, le
        # bilan du sol et le budget hebdomadaire créditaient donc l'eau qui n'a pas coulé, et
        # le système sous-arrosait ensuite — exactement ce que la surveillance de vanne
        # devait éviter. Ce scénario passe par la VRAIE séquence, pas par le helper.
        partiel = _ManualIrrigationCoordinator()

        async def _vanne_qui_retombe(zone_id, duree_s, *args, **kwargs):
            return float(duree_s) / 2.0

        partiel._attendre_zone_ouverte = _vanne_qui_retombe

        async def _run_partiel() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _noop_sleep(*args, **kwargs):
                return None

            coordinator_mod.asyncio.sleep = _noop_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_manual_irrigation(
                    partiel,
                    1.0,
                )
                task = partiel._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run_partiel())

        self.assertEqual(len(partiel._watering_calls), 1)
        dose_partielle = partiel._watering_calls[0]["kwargs"]["objectif_mm"]
        self.assertEqual(dose_partielle, 0.5, "les deux zones ont coulé moitié moins : 0,5 mm")
        self.assertNotEqual(dose_partielle, 1.0, "l'objectif PRÉVU a été réenregistré tel quel")

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
        self.assertEqual(progress["cycle_spacing_minutes"], 120)

        current = datetime(2026, 4, 27, 12, 59, tzinfo=timezone.utc)
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertFalse(should_launch)
        self.assertEqual(reason, "semis_cycle_pending")

        current = datetime(2026, 4, 27, 13, 0, tzinfo=timezone.utc)
        should_launch, reason = coordinator._should_launch_auto_irrigation(snapshot)
        self.assertTrue(should_launch)
        self.assertEqual(reason, "ready")

        coordinator.history.extend(
            [
                {
                    "type": "arrosage",
                    "date": "2026-04-27",
                    "recorded_at": "2026-04-27T13:05:00+00:00",
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
                    "recorded_at": "2026-04-27T16:05:00+00:00",
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
        current = datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc)
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
        self.assertEqual(progress["next_due_display"], "27/04/2026 à 14:05")
        self.assertEqual(progress["cycle_spacing_minutes"], 120)

    def test_deux_cycles_de_germination_sont_repartis_a_deux_heures(self) -> None:
        coordinator = _build_coordinator()
        snapshot = {
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.2,
            "daily_cycles_target": 2,
            "cycle_spacing_minutes": 90,
        }
        current = datetime(2026, 4, 27, 8, 0, tzinfo=timezone.utc)
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current
        coordinator._current_date = lambda: current.date()

        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        slots = progress["cycle_slots_minutes"]
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots, (10 * 60, 16 * 60))
        self.assertGreaterEqual(slots[1] - slots[0], 120)
        self.assertEqual(progress["cycle_spacing_minutes"], 120)

    def test_deux_cycles_regles_sont_repartis_du_matin_a_l_apres_midi(self) -> None:
        coordinator = _build_coordinator()
        coordinator.entry.options = {
            "reglages": {
                "graines_fenetre_debut": 8 * 60 + 30,
                "graines_fenetre_fin": 16 * 60,
            }
        }
        snapshot = {
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.2,
            "daily_cycles_target": 2,
            "cycle_spacing_minutes": 120,
        }
        current = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current
        coordinator._current_date = lambda: current.date()

        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        self.assertEqual(progress["cycle_slots_minutes"], (510, 900))
        self.assertEqual(progress["next_due_at"].strftime("%H:%M"), "08:30")

    def test_programme_termine_publie_le_vrai_premier_creneau_du_lendemain(self) -> None:
        coordinator = _build_coordinator()
        coordinator.entry.options = {"reglages": {"graines_fenetre_debut": 8 * 60 + 30}}
        snapshot = {
            "watering_strategy": "semis_frequent",
            "objective_scope": "surface_cycle",
            "watering_stage": "germination",
            "surface_cycle_mm": 1.2,
            "daily_cycles_target": 2,
            "cycle_spacing_minutes": 120,
        }
        coordinator.history = [
            {
                "type": "arrosage",
                "date": "2026-09-18",
                "started_at": f"2026-09-18T{heure}:00+00:00",
                "watering_strategy": "semis_frequent",
                "objective_scope": "surface_cycle",
            }
            for heure in ("08:30", "10:30")
        ]
        current = datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc)
        coordinator._current_datetime = lambda: current
        coordinator._current_utc_datetime = lambda: current
        coordinator._current_date = lambda: current.date()

        progress = coordinator._semis_cycle_progress(snapshot)
        assert progress is not None
        self.assertEqual(progress["state"], "complete")
        self.assertEqual(
            progress["next_due_at"],
            datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc),
        )

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
        # ⚠️ ON NE STUBBE PAS `async_refresh` ICI, ET C'EST DÉLIBÉRÉ — relevé par la revue du
        # 10/09/2026. Ce banc vérifie que le chemin des CAPTEURS reste débouncé : lui donner un
        # `async_refresh` utilisable le rendrait aveugle au jour où ce chemin basculerait sur
        # l'immédiat. S'il est appelé, le test doit tomber.
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

    def _application_inconnue(self, jours_avant: int) -> list[dict[str, object]]:
        # Datée selon l'horloge de la MÉMOIRE : depuis 0.88.0 le refus ne dure que le temps de
        # l'intervention (`application_en_cours`), il ne peut plus être testé sur une date figée.
        maintenant = importlib.import_module("custom_components.gazon_intelligent.memory")._current_datetime()
        jour = (maintenant - timedelta(days=jours_avant)).date()
        return [{
            "type": "Traitement",
            "date": jour.isoformat(),
            "declared_at": (maintenant - timedelta(days=jours_avant)).isoformat(),
            "produit": "Produit inconnu",
            "application_type": "autre",
            "application_requires_watering_after": True,
            "application_post_watering_mm": 1.0,
            "application_irrigation_block_hours": 0.0,
            "application_irrigation_delay_minutes": 0.0,
            "application_irrigation_mode": "auto",
        }]

    def test_application_irrigation_blocks_unknown_application_type(self) -> None:
        test = self

        class _UnknownApplicationCoordinator:
            def __init__(self) -> None:
                self.history = test._application_inconnue(0)
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

    def test_une_application_inconnue_ANCIENNE_ne_bloque_plus_l_arrosage_technique(self) -> None:
        # Avant 0.88.0, ce refus durait à vie : la troisième copie de la règle non bornée.
        test = self

        class _Coordinateur:
            def __init__(self) -> None:
                self.history = test._application_inconnue(30)
                self._recorded_actions: list[dict[str, object]] = []

            def _build_watering_plan_summary_for_user_action(self, objectif_mm=None, plan=None):
                return {"objective_mm": float(objectif_mm or 0.0), "zones": [], "zone_count": 0,
                        "fractionation": False, "passages": 1, "pause_between_passages_minutes": 0,
                        "plan_type": "no_plan"}

            async def async_record_user_action(self, **kwargs):
                self._recorded_actions.append(kwargs)
                return kwargs

        coordinator = _Coordinateur()
        with self.assertRaises(coordinator_mod.HomeAssistantError):
            asyncio.run(coordinator_mod.GazonIntelligentCoordinator.async_start_application_irrigation(coordinator))
        self.assertNotIn("type d'application est inconnu", coordinator._recorded_actions[-1]["reason"])

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

    def test_completed_shaded_plan_is_not_reported_as_partial(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            10.0,
            [
                ("switch.zone_1", 60.0, 0.0),
                ("switch.zone_2", 60.0, 30.0),
            ],
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
                    10.0,
                    plan_arrosage_entity_id="sensor.gazon_intelligent_plan_arrosage",
                    source="auto_irrigation",
                )
                task = coordinator._auto_irrigation_task
                assert task is not None
                await task
            finally:
                coordinator_mod.asyncio.sleep = original_sleep

        asyncio.run(_run())

        call = coordinator.async_record_watering.await_args
        self.assertEqual(call.kwargs["objectif_mm"], 8.5)
        self.assertEqual(call.kwargs["zones"][0]["mm"], 10.0)
        self.assertEqual(call.kwargs["zones"][1]["mm"], 7.0)
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["target_mm"], 8.5)
        self.assertEqual(execution["completion_status"], "completed")
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
        self.assertEqual(coordinator.async_record_watering.await_args.kwargs["total_mm"], 1.5)

    def test_restart_mid_zone_finished_during_downtime_credits_zone(self) -> None:
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
        session["current_zone_started_at"] = datetime.now(timezone.utc) - timedelta(seconds=120)
        coordinator.hass.states.states["switch.zone_1"] = _FakeState("on", datetime.now(timezone.utc), {})
        coordinator._runtime_state["active_irrigation_session"] = session

        async def _run() -> None:
            await coordinator._restore_active_irrigation_session()
            task = coordinator._auto_irrigation_task
            assert task is not None
            await task

        asyncio.run(_run())

        coordinator.async_record_watering.assert_awaited_once()
        kwargs = coordinator.async_record_watering.await_args.kwargs
        self.assertEqual(kwargs["total_mm"], 1.5)
        self.assertTrue(kwargs["zones"][0]["recovered_during_downtime"])
        turn_on_calls = [call for call in coordinator._service_calls if call[1] == "turn_on"]
        self.assertEqual(turn_on_calls, [])

    def test_restart_with_unavailable_zones_records_done_water_before_failure(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            3.0,
            [("switch.zone_1", 60.0), ("switch.zone_2", 60.0)],
            passages=1,
            pause_minutes=0,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session["status"] = "paused"
        session["zones_done"] = [
            {"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 3.0}
        ]
        coordinator.hass.states.states["switch.zone_1"] = _FakeState("unavailable", datetime.now(timezone.utc), {})
        coordinator._runtime_state["active_irrigation_session"] = session
        # L'attente réelle dure 60 s (toute la suite passait de 2 s à 62 s). Son verdict est testé
        # avec un délai court par `ZoneAvailabilityGuardTests` ; ici seul compte ce qui suit un refus.
        coordinator._wait_for_zones_available = AsyncMock(return_value=False)

        asyncio.run(coordinator._resume_active_irrigation_session(session))

        coordinator.async_record_watering.assert_awaited_once()
        kwargs = coordinator.async_record_watering.await_args.kwargs
        self.assertEqual(kwargs["total_mm"], 1.5)
        self.assertEqual(kwargs["watering_cause"], "hydrique")
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(execution["last_error"], "device_unavailable_on_resume")

    def test_restart_with_safety_lock_records_done_water_before_closing(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            3.0,
            [("switch.zone_1", 60.0), ("switch.zone_2", 60.0)],
            passages=1,
            pause_minutes=0,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator._runtime_state["auto_irrigation_safety_lock"] = True
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session["status"] = "paused"
        session["zones_done"] = [
            {"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 3.0}
        ]
        coordinator._runtime_state["active_irrigation_session"] = session

        asyncio.run(coordinator._restore_active_irrigation_session())

        coordinator.async_record_watering.assert_awaited_once()
        self.assertEqual(coordinator.async_record_watering.await_args.kwargs["total_mm"], 1.5)
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        execution = coordinator._runtime_state["last_irrigation_execution"]
        self.assertEqual(execution["status"], "failed")
        self.assertEqual(execution["last_error"], "safety_lock_active")

    def test_restart_post_application_auto_disabled_is_cancelled_like_auto(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            3.0,
            [("switch.zone_1", 60.0), ("switch.zone_2", 60.0)],
            passages=1,
            pause_minutes=0,
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator.memory["auto_irrigation_enabled"] = False
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="application_technique_auto",
            strategy="plan",
            watering_cause="post_application",
        )
        session["status"] = "paused"
        session["zones_done"] = [
            {"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 3.0}
        ]
        coordinator._runtime_state["active_irrigation_session"] = session

        asyncio.run(coordinator._restore_active_irrigation_session())

        coordinator.async_record_watering.assert_awaited_once()
        kwargs = coordinator.async_record_watering.await_args.kwargs
        self.assertEqual(kwargs["source"], "application_technique_auto")
        self.assertEqual(kwargs["watering_cause"], "post_application")
        self.assertEqual(kwargs["total_mm"], 1.5)
        self.assertIsNone(coordinator._auto_irrigation_task)
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        self.assertEqual(coordinator._runtime_state["last_irrigation_execution"]["status"], "cancelled")

    @staticmethod
    def _plan_deux_zones():
        plan = watering_plan_mod.build_watering_plan(
            3.0,
            [("switch.zone_1", 60.0), ("switch.zone_2", 60.0)],
            passages=1,
            pause_minutes=0,
        )
        assert plan is not None
        return plan

    def test_restart_closes_marked_session_as_completed_despite_recovery_error(self) -> None:
        """Clôture AU REDÉMARRAGE d'une session dont l'eau est déjà inscrite : « terminée ».

        `restart_recovery` ne doit pas la faire passer pour un échec. Aucun test ne tenait ce
        statut sur la voie du redémarrage (mutation X4).
        """
        plan = self._plan_deux_zones()
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session[coordinator_mod.WATERING_RECORDED_KEY] = True
        session["status"] = "recovery_required"
        session["last_error"] = "restart_recovery"
        session["zones_done"] = [{"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 3.0}]
        coordinator._runtime_state["active_irrigation_session"] = session

        asyncio.run(coordinator._restore_active_irrigation_session())

        coordinator.async_record_watering.assert_not_awaited()
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        self.assertEqual(coordinator._runtime_state["last_irrigation_execution"]["status"], "completed")

    def test_zone_finished_during_downtime_leaves_the_pending_queue(self) -> None:
        """La zone finie pendant la coupure est créditée ET retirée de la file d'attente.

        Avant D3, son segment restait « en attente » : c'est le segment zombie qui, avant C10,
        gardait active une session dont l'eau était déjà inscrite. C10 règle ce cas dans le
        prédicat ; ce test tient la file elle-même (mutation Y3).
        """
        plan = self._plan_deux_zones()
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session["status"] = "running"
        session["current_passage"] = 1
        session["current_zone_index"] = 0
        session["current_zone"] = "switch.zone_1"
        session["current_zone_started_at"] = datetime.now(timezone.utc) - timedelta(seconds=1000)
        coordinator.hass.states.states["switch.zone_1"] = _FakeState("on", datetime.now(timezone.utc), {})
        coordinator._runtime_state["active_irrigation_session"] = session
        self.assertEqual(
            {(seg["passage"], seg["zone_index"]) for seg in session["zones_pending"]},
            {(1, 0), (1, 1)},
            "prémisse : les deux segments sont en attente",
        )
        repris: dict[str, object] = {}

        async def _executer(**kwargs) -> None:
            repris.update(kwargs)

        coordinator._execute_canonical_watering_plan = _executer

        asyncio.run(coordinator._resume_active_irrigation_session(session))

        suite = repris["session"]
        self.assertEqual({(seg["passage"], seg["zone_index"]) for seg in suite["zones_pending"]}, {(1, 1)})
        self.assertTrue(suite["zones_done"][0]["recovered_during_downtime"])

    def test_degraded_close_marks_the_session_before_writing_its_water(self) -> None:
        """Même atomicité que la fin de cycle (C1) : la sauvegarde qui écrit l'eau porte déjà le
        marqueur. Sans lui, un redémarrage entre cette écriture et la sauvegarde qui efface la
        session relançait la clôture dégradée, qui inscrivait la même eau une deuxième fois (Y7)."""
        plan = self._plan_deux_zones()
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator._runtime_state["auto_irrigation_safety_lock"] = True
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session["status"] = "paused"
        session["zones_done"] = [{"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 3.0}]
        coordinator._runtime_state["active_irrigation_session"] = session
        etat_a_l_ecriture: list[tuple[bool, str | None, str | None]] = []

        async def _ecrire(*_args, **_kwargs) -> None:
            courante = coordinator._runtime_state.get("active_irrigation_session")
            etat_a_l_ecriture.append(
                (
                    isinstance(courante, dict) and bool(courante.get(coordinator_mod.WATERING_RECORDED_KEY)),
                    courante.get("status") if isinstance(courante, dict) else None,
                    courante.get("last_error") if isinstance(courante, dict) else None,
                )
            )

        coordinator.async_record_watering = AsyncMock(side_effect=_ecrire)

        asyncio.run(coordinator._restore_active_irrigation_session())

        self.assertEqual(etat_a_l_ecriture, [(True, "failed", "safety_lock_active")])

    def test_failed_shutdown_during_downtime_records_done_water_and_keeps_lock(self) -> None:
        """Vanne impossible à fermer pendant la reprise : l'eau des zones faites est inscrite (Y8).

        Avant, un simple `return` : `_safe_turn_off_zone` avait déjà passé la session en
        « failed », elle se fermait à la lecture suivante SANS inscrire l'eau de la zone 1.
        """
        plan = self._plan_deux_zones()

        def _refuser_fermeture(domain, service, data, blocking):
            if service == "turn_off":
                raise RuntimeError("relais injoignable")

        coordinator = _build_runtime_ready_coordinator(
            plan_attrs=plan.as_dict(), service_handler=_refuser_fermeture
        )
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session["status"] = "running"
        session["zones_done"] = [{"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 3.0}]
        session["zones_pending"] = [seg for seg in session["zones_pending"] if seg["zone_index"] == 1]
        session["current_passage"] = 1
        session["current_zone_index"] = 1
        session["current_zone"] = "switch.zone_2"
        session["current_zone_started_at"] = datetime.now(timezone.utc) - timedelta(seconds=1000)
        coordinator.hass.states.states["switch.zone_2"] = _FakeState("on", datetime.now(timezone.utc), {})
        coordinator._runtime_state["active_irrigation_session"] = session

        asyncio.run(coordinator._resume_active_irrigation_session(session))

        fermetures = [call for call in coordinator._service_calls if call[1] == "turn_off"]
        self.assertTrue(fermetures, "prémisse : la fermeture a été tentée")
        self.assertEqual({call[2]["entity_id"] for call in fermetures}, {"switch.zone_2"})
        # Seule l'eau des zones terminées et fermées est inscrite.
        coordinator.async_record_watering.assert_awaited_once()
        self.assertEqual(coordinator.async_record_watering.await_args.kwargs["total_mm"], 1.5)
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        self.assertTrue(coordinator._runtime_state["auto_irrigation_safety_lock"])
        self.assertEqual(coordinator._runtime_state["last_irrigation_execution"]["status"], "failed")

    def test_degraded_close_does_not_rewrite_already_recorded_water(self) -> None:
        """Session dont l'eau est déjà inscrite, close par un chemin dégradé : pas de deuxième
        écriture (Y9)."""
        plan = self._plan_deux_zones()
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        session = coordinator._build_active_irrigation_session(
            plan=plan, source="auto_irrigation", strategy="plan"
        )
        session[coordinator_mod.WATERING_RECORDED_KEY] = True
        session["zones_done"] = [{"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 3.0}]
        coordinator._runtime_state["active_irrigation_session"] = session

        asyncio.run(
            coordinator._close_degraded_irrigation_session(
                session, status="failed", error="safety_lock_active", plan=plan
            )
        )

        coordinator.async_record_watering.assert_not_awaited()
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        self.assertEqual(coordinator._runtime_state["last_irrigation_execution"]["status"], "failed")

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

    def _coord_idle_dans_le_jardin(self):
        """Le robot annonce `idle`, sans code d'erreur, batterie à 52 % et pas en charge."""
        instant = datetime(2026, 9, 2, 21, 54, tzinfo=timezone.utc)
        return self._build_coordinator(
            mower_states=[
                _FakeMowerState(entity_id="lawn_mower.esperance_jr", state="idle", name="Esperance Jr"),
            ],
            entity_states={
                "lawn_mower.esperance_jr": _FakeState("idle", instant),
                "sensor.esperance_jr_batterie": _FakeState("52", instant),
                "binary_sensor.esperance_jr_en_charge": _FakeState("off", instant),
                "binary_sensor.esperance_jr_capteur_de_pluie": _FakeState("off", instant),
                "sensor.esperance_jr_erreur": _FakeState("no_error", instant),
            },
        )

    def test_le_carnet_ouvert_atteint_REELLEMENT_la_coordination(self) -> None:
        """⚠️ LE CÂBLAGE, PAS LA FONCTION — le banc a montré que je testais la seconde sans la
        première : neutraliser `_passe_tondeuse_ouverte` ou retirer l'argument des TROIS points
        d'appel ne faisait tomber aucun test.

        Ce test part de l'état de la tondeuse et va jusqu'à la présence publiée.
        """
        coord = self._coord_idle_dans_le_jardin()

        # Carnet vide : `idle` vaut une rentrée, comme avant.
        coord._runtime_state["mower_passes"] = {"en_cours": None, "journal": []}
        self.assertEqual(coord._build_mower_snapshot()["mower_presence_state"], "dockee",
                         "prémisse : sans passe ouverte, `idle` reste une rentrée")

        # Une passe est ouverte : elle est sortie et n'est pas revenue.
        # ⚠️ `dock_signal_vu` est la prémisse, pas un détail de fixture : le cliquet ne vaut
        # que pour une machine dont on a DÉJÀ vu un signal fort de station. Celle utilisée ici
        # annonce `docked` et la charge, elle est donc dans ce cas.
        coord._runtime_state["mower_passes"] = {
            "en_cours": {"debut": "2026-09-02T22:40:31+02:00", "batterie_debut": 91},
            "journal": [],
            "dock_signal_vu": True,
        }
        snapshot = coord._build_mower_snapshot()
        self.assertEqual(
            snapshot["mower_presence_state"], "dehors",
            "la passe ouverte n'atteint pas la coordination : `idle` referme la passe à tort",
        )
        self.assertFalse(snapshot["mower_is_docked"])

    def test_une_tondeuse_qui_ne_dit_que_idle_ne_reste_pas_dehors_pour_toujours(self) -> None:
        """⚠️ LE VERROU CIRCULAIRE (revue Codex, PR #48).

        `mower_is_docked` dérive de la présence, `au_garage` en dérive, et une passe ne se
        ferme QUE si `au_garage`. Sur une machine dont `idle` est le seul état de repos, le
        cliquet de la 0.70.0 se refermait sur lui-même : la passe ne pouvait plus jamais être
        fermée, `mower_is_safe_for_watering` restait faux, et plus AUCUN arrosage ne partait.
        """
        coord = self._coord_idle_dans_le_jardin()
        en_cours = {"debut": "2026-09-02T22:40:31+02:00", "batterie_debut": 91}

        # Jamais vu de signal fort : `idle` est la seule rentrée qu'elle sache annoncer.
        coord._runtime_state["mower_passes"] = {"en_cours": dict(en_cours), "journal": []}
        snapshot = coord._build_mower_snapshot()
        self.assertEqual(
            snapshot["mower_presence_state"], "dockee",
            "sans signal fort connu, le cliquet enferme la tondeuse dehors pour toujours",
        )
        self.assertTrue(
            snapshot["mower_is_docked"],
            "la passe ne pourra jamais se fermer si la présence ne repasse pas `dockee`",
        )

        # Le drapeau est collant : une fois le signal fort vu, le cliquet reprend ses droits.
        coord._runtime_state["mower_passes"] = {
            "en_cours": dict(en_cours),
            "journal": [],
            "dock_signal_vu": True,
        }
        self.assertEqual(
            coord._build_mower_snapshot()["mower_presence_state"], "dehors",
            "le drapeau posé, la protection de la 0.70.0 doit revenir intacte",
        )

    def test_le_drapeau_dock_est_REELLEMENT_pose_par_un_signal_fort(self) -> None:
        """⚠️ POSER, PAS SEULEMENT LIRE. Un drapeau lu partout et écrit nulle part reste faux
        pour toujours : le cliquet de la 0.70.0 serait mort-né sans que rien ne le signale.
        """
        coord = self._coord_idle_dans_le_jardin()
        coord._runtime_state["mower_passes"] = {"en_cours": None, "journal": []}
        self.assertFalse(coord._dock_signal_tondeuse_vu(), "prémisse : rien de vu au départ")

        coord._suivre_passes_tondeuse(
            {"tondeuse_connectee": True, "mower_dock_signal_fort": True, "mower_battery": 100}
        )
        self.assertTrue(
            coord._dock_signal_tondeuse_vu(),
            "un signal fort de station doit armer le drapeau, sinon le cliquet ne sert jamais",
        )

        # Et il ne se retire pas au premier `idle` venu.
        coord._suivre_passes_tondeuse(
            {"tondeuse_connectee": True, "mower_dock_signal_fort": False, "mower_battery": 88}
        )
        self.assertTrue(coord._dock_signal_tondeuse_vu(), "le drapeau doit être collant")

    def test_le_helper_lit_bien_le_carnet(self) -> None:
        coord = self._coord_idle_dans_le_jardin()
        for carnet, attendu in (
            (None, False),
            ({}, False),
            ({"en_cours": None}, False),
            ({"en_cours": {"debut": "x"}}, True),
        ):
            with self.subTest(carnet=carnet):
                coord._runtime_state["mower_passes"] = carnet
                self.assertIs(coord._passe_tondeuse_ouverte(), attendu)

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

    def test_le_plan_canonique_applique_la_reduction_de_la_zone_ombragee(self) -> None:
        coordinator = _build_coordinator()
        coordinator.history = []
        coordinator.data = {"objectif_mm": 10.0}
        coordinator.entry.options = {
            "reglages": {"arrosage_reduction_ombre_zone_2": 30.0},
        }

        plan = coordinator._get_canonical_watering_plan(objectif_mm=10.0)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.zones[0].mm, 10.0)
        self.assertEqual(plan.zones[1].mm, 7.0)
        self.assertEqual(plan.zones[1].water_reduction_pct, 30.0)
        self.assertEqual(plan.planned_surface_mm, 8.5)

    def test_chacune_des_cinq_zones_peut_avoir_sa_propre_reduction(self) -> None:
        cles = (
            "arrosage_reduction_ombre_zone_1",
            "arrosage_reduction_ombre_zone_2",
            "arrosage_reduction_ombre_zone_3",
            "arrosage_reduction_ombre_zone_4",
            "arrosage_reduction_ombre_zone_5",
        )
        for numero, cle in enumerate(cles, start=1):
            with self.subTest(zone=numero):
                coordinator = _build_coordinator()
                coordinator.history = []
                coordinator.data = {"objectif_mm": 10.0}
                coordinator.entry.data.update({
                    f"zone_{idx}": f"switch.zone_{idx}" for idx in range(1, 6)
                })
                coordinator.entry.data.update({
                    f"debit_zone_{idx}": 60.0 for idx in range(1, 6)
                })
                coordinator.entry.options = {"reglages": {cle: 25.0}}

                plan = coordinator._get_canonical_watering_plan(objectif_mm=10.0)

                self.assertIsNotNone(plan)
                self.assertEqual(plan.zones[numero - 1].water_reduction_pct, 25.0)
                self.assertEqual(plan.zones[numero - 1].duration_s, 450)
                self.assertTrue(all(
                    zone.duration_s == (450 if idx == numero else 600)
                    for idx, zone in enumerate(plan.zones, start=1)
                ))


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
        coordinator.async_refresh = AsyncMock()
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

    def _session_zone_zero(self, coordinator, *, passage: int, ecoule_s: float = 300.0) -> dict:
        zones_done = []
        if passage == 2:
            zones_done = [
                {
                    "order": 1,
                    "passage": 1,
                    "zone": "switch.zone_1",
                    "mm": 4.0,
                    "duration_s": 240,
                }
            ]
        return {
            "source": "auto_irrigation",
            "current_passage": passage,
            "current_zone": "switch.zone_1",
            "current_zone_index": 0,
            "current_zone_started_at": coordinator._current_utc_datetime()
            - timedelta(seconds=ecoule_s),
            "zones_done": zones_done,
            "zones_pending": [
                {
                    "passage": passage,
                    "zone_index": 0,
                    "zone": "switch.zone_1",
                    "duration_s": 600,
                    "mm": 6.0,
                }
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
        # 4 mm sur la zone 1, la zone 2 prévue mais jamais ouverte : la moitié du gazon n'a
        # rien reçu, la lame moyenne vaut donc 2 mm. Créditer 4 ferait croire au bilan du sol
        # que toute la pelouse a bu — et la zone restée sèche attendrait d'autant plus.
        self.assertEqual(kwargs["total_mm"], 2.0)
        self.assertEqual(kwargs["watering_cause"], "arret_manuel")
        # La source d'origine est conservée : les garde-fous comptent cette eau comme les autres.
        self.assertEqual(kwargs["source"], "auto_irrigation")

    async def test_une_seule_sauvegarde_porte_la_session_effacee_et_l_eau(self) -> None:
        """D1 : ni session active sur disque avec son eau, ni session effacée sans son eau.

        Premier correctif (Codex) : sauvegarder la session effacée PUIS écrire l'eau. Plus de
        vannes rouvertes, mais un redémarrage entre les deux sauvegardes perdait l'arrêt. L'eau
        est désormais écrite par la sauvegarde même qui efface la session.
        """
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(self._session(coordinator))
        ordre: list[tuple[str, bool]] = []

        async def _persist() -> None:
            ordre.append(
                (
                    "save",
                    isinstance(coordinator._runtime_state.get("active_irrigation_session"), dict),
                )
            )

        async def _record(*_args, **_kwargs) -> None:
            ordre.append(
                (
                    "record",
                    isinstance(coordinator._runtime_state.get("active_irrigation_session"), dict),
                )
            )

        coordinator._persist_runtime_state = _persist
        coordinator.async_record_watering = AsyncMock(side_effect=_record)

        await coordinator.async_stop_irrigation()

        # Session déjà effacée quand l'eau est écrite, et aucune sauvegarde intermédiaire.
        self.assertEqual(ordre[0], ("record", False))
        self.assertNotIn(("save", True), ordre)

    async def test_sans_eau_la_session_effacee_est_sauvegardee_seule(self) -> None:
        coordinator = self._coordinateur()
        session = self._session(coordinator)
        session["zones_done"] = []
        coordinator._set_active_irrigation_session(session)
        sauvegardes: list[bool] = []

        async def _persist() -> None:
            sauvegardes.append(isinstance(coordinator._runtime_state.get("active_irrigation_session"), dict))

        coordinator._persist_runtime_state = _persist

        resultat = await coordinator.async_stop_irrigation()

        self.assertEqual(resultat["applied_mm"], 0.0)
        coordinator.async_record_watering.assert_not_awaited()
        self.assertEqual(sauvegardes, [False])

    async def test_ecriture_de_l_eau_en_echec_sauve_quand_meme_l_arret(self) -> None:
        """Si l'écriture de l'eau lève avant d'atteindre le disque, la session effacée est
        sauvée à part : le disque ne doit pas garder un cycle que la reprise relancerait."""
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(self._session(coordinator))
        sauvegardes: list[bool] = []

        async def _persist() -> None:
            sauvegardes.append(isinstance(coordinator._runtime_state.get("active_irrigation_session"), dict))

        coordinator._persist_runtime_state = _persist
        coordinator.async_record_watering = AsyncMock(side_effect=RuntimeError("historique illisible"))

        with self.assertRaises(RuntimeError):
            await coordinator.async_stop_irrigation()

        self.assertEqual(sauvegardes, [False])

    async def test_le_disque_ne_voit_jamais_un_arret_a_moitie(self) -> None:
        """Vrai cerveau et vraie sauvegarde : à chaque écriture, session active OU eau de l'arrêt.

        Les deux ensemble, la reprise rouvrirait les zones restantes ; ni l'une ni l'autre, l'eau
        de l'arrêt serait perdue.
        """
        coordinator = self._coordinateur()
        coordinator.brain = brain_mod.GazonBrain()
        for nom in ("async_record_watering", "_async_save_state", "_persist_runtime_state"):
            methode = getattr(coordinator_mod.GazonIntelligentCoordinator, nom)
            setattr(coordinator, nom, methode.__get__(coordinator, type(coordinator)))
        ecrits: list[dict[str, object]] = []

        class _Store:
            async def async_save(self, payload: dict[str, object]) -> None:
                ecrits.append(json.loads(json.dumps(payload)))

        coordinator._store = _Store()
        coordinator._set_active_irrigation_session(self._session(coordinator))
        await coordinator._async_save_state()  # avant l'arrêt : session active, pas d'eau

        await coordinator.async_stop_irrigation()

        etats = []
        for payload in ecrits:
            runtime = payload.get("runtime")
            session_active = isinstance(runtime, dict) and isinstance(
                runtime.get("active_irrigation_session"), dict
            )
            eau_arret = any(
                item.get("type") == "arrosage" and item.get("watering_cause") == "arret_manuel"
                for item in payload.get("history", [])
                if isinstance(item, dict)
            )
            etats.append((session_active, eau_arret))
        self.assertEqual(etats[0], (True, False), "prémisse : la session active se lit bien sur disque")
        self.assertNotIn((True, True), etats, "session active ET eau de l'arrêt : zones rouvertes")
        self.assertNotIn((False, False), etats, "ni session ni eau : l'arrêt est perdu")
        self.assertEqual(etats[-1], (False, True))

    async def test_la_zone_interrompue_est_creditee_au_prorata(self) -> None:
        """Elle n'est PAS dans `zones_done` (l'enregistrement se fait après le try/finally).
        Sans reconstitution, arrêter à mi-zone perdrait cette eau."""
        coordinator = self._coordinateur()
        # 300 s écoulées sur un segment de 600 s valant 6 mm -> 3 mm.
        coordinator._set_active_irrigation_session(self._session(coordinator, ecoule_s=300.0))

        resultat = await coordinator.async_stop_irrigation()

        # 4 mm sur la zone 1, 3 mm sur la zone 2 : chaque carré d'herbe concerné a reçu
        # SA lame, la pelouse n'a pas reçu 7 mm. Dose surface = moyenne des zones = 3,5.
        self.assertEqual(resultat["applied_mm"], 3.5)
        zones = coordinator.async_record_watering.await_args.kwargs["zones"]
        self.assertEqual(len(zones), 2)
        self.assertTrue(zones[1]["interrupted"])
        self.assertEqual(zones[1]["mm"], 3.0)

    async def test_la_premiere_zone_interrompue_est_reconstituee(self) -> None:
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(
            self._session_zone_zero(coordinator, passage=1, ecoule_s=300.0)
        )

        resultat = await coordinator.async_stop_irrigation()

        self.assertGreater(resultat["applied_mm"], 0.0)
        zones = coordinator.async_record_watering.await_args.kwargs["zones"]
        self.assertEqual(len(zones), 1)
        self.assertTrue(zones[0]["interrupted"])
        self.assertEqual(zones[0]["passage"], 1)
        self.assertEqual(zones[0]["mm"], 3.0)

    async def test_la_zone_zero_du_deuxieme_passage_est_reconstituee(self) -> None:
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(
            self._session_zone_zero(coordinator, passage=2, ecoule_s=300.0)
        )

        resultat = await coordinator.async_stop_irrigation()

        self.assertGreater(resultat["applied_mm"], 0.0)
        zones = coordinator.async_record_watering.await_args.kwargs["zones"]
        self.assertEqual(len(zones), 2)
        self.assertTrue(zones[1]["interrupted"])
        self.assertEqual(zones[1]["passage"], 2)
        self.assertEqual(zones[1]["mm"], 3.0)

    async def test_le_prorata_ne_depasse_jamais_le_segment_prevu(self) -> None:
        """Une horloge qui saute ne doit pas créditer plus que ce que la vanne pouvait délivrer."""
        coordinator = self._coordinateur()
        coordinator._set_active_irrigation_session(self._session(coordinator, ecoule_s=99_999.0))

        resultat = await coordinator.async_stop_irrigation()

        # Le segment plein plafonne à 6 mm (pas plus), et la dose surface reste la moyenne
        # des deux zones : (4 + 6) / 2 = 5.
        self.assertEqual(resultat["applied_mm"], 5.0)

    async def test_la_dose_enregistree_est_une_lame_de_surface_pas_un_cumul(self) -> None:
        """Trois zones à 5 mm : la pelouse a reçu 5 mm, pas 15.

        Sommer les segments enregistrait la lame × le nombre de zones. Le bilan du sol se
        croyait crédité au triple, le budget hebdomadaire se croyait dépassé, et le système
        sous-arrosait ensuite — l'inverse exact de ce que cet enregistrement protège.
        Les trois autres voies disaient déjà la bonne chose : fin de cycle normale
        (`plan.objective_mm`), affichage temps réel (`compute_live_session_water`) et
        `_zone_session_surface_mm`. Seul l'arrêt manuel divergeait.
        """
        coordinator = self._coordinateur()
        session = self._session(coordinator, ecoule_s=0.0)
        session["zones_done"] = [
            {"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 5.0, "duration_s": 300},
            {"order": 2, "passage": 1, "zone": "switch.zone_2", "mm": 5.0, "duration_s": 300},
            {"order": 3, "passage": 1, "zone": "switch.zone_3", "mm": 5.0, "duration_s": 300},
        ]
        session["zones_pending"] = []
        coordinator._set_active_irrigation_session(session)

        resultat = await coordinator.async_stop_irrigation()

        self.assertEqual(resultat["applied_mm"], 5.0)
        self.assertNotEqual(resultat["applied_mm"], 15.0, "la somme des zones a été réenregistrée")
        kwargs = coordinator.async_record_watering.await_args.kwargs
        self.assertEqual(kwargs["total_mm"], 5.0)
        self.assertEqual(kwargs["objectif_mm"], 5.0)

    async def test_les_zones_jamais_ouvertes_comptent_pour_zero(self) -> None:
        """Arrêter après la première de trois zones n'arrose pas la pelouse à 5 mm.

        Deux tiers du gazon n'ont rien reçu. Ne moyenner que les zones qui ont tourné
        créditait le bilan du sol au triple, et les zones restées sèches — celles qui ont le
        plus soif — attendaient d'autant plus longtemps le prochain cycle.
        """
        coordinator = self._coordinateur()
        session = self._session(coordinator, ecoule_s=0.0)
        session["zones_done"] = [
            {"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 5.0, "duration_s": 300},
        ]
        session["zones_pending"] = [
            {"passage": 1, "zone_index": 1, "zone": "switch.zone_2", "duration_s": 300, "mm": 5.0},
            {"passage": 1, "zone_index": 2, "zone": "switch.zone_3", "duration_s": 300, "mm": 5.0},
        ]
        coordinator._set_active_irrigation_session(session)

        resultat = await coordinator.async_stop_irrigation()

        # 5 mm sur une zone, trois zones au plan → 5 / 3 ≈ 1,7 mm de lame moyenne.
        self.assertEqual(resultat["applied_mm"], 1.7)
        self.assertNotEqual(resultat["applied_mm"], 5.0,
                            "les zones jamais ouvertes ont été exclues de la moyenne")

    async def test_la_cause_arret_manuel_survit_a_l_enregistrement(self) -> None:
        """Elle traversait DEUX listes blanches et mourait dans la seconde.

        `_normalize_watering_cause` puis `GazonBrain.record_watering` filtrent chacune les
        causes reconnues. `arret_manuel` manquait aux deux : l'historique retombait sur
        « hydrique » et ne distinguait plus un cycle interrompu d'un arrosage normal — la
        trace d'audit que le service était censé laisser.
        """
        coordinator = self._coordinateur()
        self.assertEqual(coordinator._normalize_watering_cause("arret_manuel"), "arret_manuel")

    async def test_deux_passages_sur_une_zone_s_additionnent(self) -> None:
        """Le même carré d'herbe arrosé deux fois a bien reçu les deux lames.

        C'est la moitié de la règle que la moyenne seule casserait : moyenner les six
        segments d'un cycle à 2 passages × 3 zones rendrait la dose d'UN passage — le
        sous-comptage que `_watering_item_mm` met déjà en garde de réintroduire.
        """
        coordinator = self._coordinateur()
        session = self._session(coordinator, ecoule_s=0.0)
        session["zones_done"] = [
            {"order": 1, "passage": 1, "zone": "switch.zone_1", "mm": 2.5, "duration_s": 150},
            {"order": 2, "passage": 1, "zone": "switch.zone_2", "mm": 2.5, "duration_s": 150},
            {"order": 3, "passage": 2, "zone": "switch.zone_1", "mm": 2.5, "duration_s": 150},
            {"order": 4, "passage": 2, "zone": "switch.zone_2", "mm": 2.5, "duration_s": 150},
        ]
        session["zones_pending"] = []
        coordinator._set_active_irrigation_session(session)

        resultat = await coordinator.async_stop_irrigation()

        # 2,5 + 2,5 par zone = 5 mm par zone ; moyenne des deux zones = 5 mm.
        self.assertEqual(resultat["applied_mm"], 5.0)
        self.assertNotEqual(resultat["applied_mm"], 2.5, "les passages ont été moyennés au lieu d'être cumulés")
        self.assertNotEqual(resultat["applied_mm"], 10.0, "les zones ont été sommées")

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


class TestPurgeSegmentsZoneZero(unittest.IsolatedAsyncioTestCase):
    async def test_fin_normale_de_zone_zero_retire_le_segment_pending(self) -> None:
        coordinator = _build_runtime_ready_coordinator()
        plan = watering_plan_mod.build_watering_plan(
            6.0,
            [("switch.zone_1", 60.0)],
            passages=1,
            pause_minutes=0,
        )
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="auto_irrigation",
            strategy="normal",
            watering_cause="hydrique",
        )
        self.assertTrue(
            any(
                segment.get("passage") == 1 and segment.get("zone_index") == 0
                for segment in session["zones_pending"]
            )
        )
        coordinator._attendre_zone_ouverte = AsyncMock(return_value=plan.zones[0].duration_s)

        await coordinator._execute_canonical_watering_plan(
            plan=plan,
            source="auto_irrigation",
            strategy="normal",
            watering_cause="hydrique",
            session=session,
        )

        self.assertFalse(
            any(
                segment.get("passage") == 1 and segment.get("zone_index") == 0
                for segment in session["zones_pending"]
            ),
            "le segment (passage 1, zone 0) doit être purgé après une fin normale",
        )


class TestFinDeCycleEauEnregistreeUneFois(unittest.IsolatedAsyncioTestCase):
    """Fin d'un cycle piloté : l'eau doit être enregistrée UNE fois, quoi qu'il arrive.

    Deux fenêtres, sur le vrai exécuteur et le vrai `async_stop_irrigation` :
    - A, la dernière zone est purgée et sauvegardée, mais l'eau n'est pas encore enregistrée.
      La session vidée était jugée terminée : un arrêt ou un redémarrage la clôturait sans rien
      enregistrer (0 mm) ;
    - B, l'eau est enregistrée mais la session n'est pas encore effacée. Avant la purge de la
      zone 0, la session restait active et un arrêt réenregistrait le cycle.
    """

    OBJECTIF_MM = 6.0

    def _plan(self):
        plan = watering_plan_mod.build_watering_plan(
            self.OBJECTIF_MM,
            [("switch.zone_1", 60.0), ("switch.zone_2", 60.0)],
            passages=2,
            pause_minutes=0,
        )
        assert plan is not None
        return plan

    def _coordinateur(self, plan):
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())
        coordinator._attendre_zone_ouverte = AsyncMock(
            side_effect=lambda entity_id, duration_s, session: duration_s
        )
        return coordinator

    def _lancer(self, coordinator, plan):
        task = asyncio.create_task(
            coordinator._execute_canonical_watering_plan(
                plan=plan,
                source="auto_irrigation",
                strategy="plan",
                watering_cause="hydrique",
            )
        )
        coordinator._auto_irrigation_task = task
        return task

    def _suspendre_une_finalisation_deja_enregistree(self, coordinator, plan):
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="auto_irrigation",
            strategy="plan",
            watering_cause="hydrique",
        )
        session[coordinator_mod.WATERING_RECORDED_KEY] = True
        session["zones_done"] = [
            {"passage": 1, "zone": "switch.zone_1", "mm": self.OBJECTIF_MM}
        ]
        session["zones_pending"] = []
        session["current_zone"] = None
        session["active_zones"] = {}
        coordinator._set_active_irrigation_session(session)

        attente = asyncio.Event()
        task = asyncio.create_task(attente.wait())
        coordinator._auto_irrigation_task = task
        return task

    def _bloquer_la_sauvegarde_finale(self, coordinator):
        """Suspend la sauvegarde qui suit la dernière zone (fenêtre A) et photographie l'état persisté."""
        atteinte = asyncio.Event()
        liberation = asyncio.Event()
        photo: dict[str, object] = {}

        async def _persist() -> None:
            session = coordinator._runtime_state.get("active_irrigation_session")
            if (
                not atteinte.is_set()
                and isinstance(session, dict)
                and session.get("zones_pending") == []
                and session.get("zones_done")
                and not session.get(coordinator_mod.WATERING_RECORDED_KEY)
            ):
                photo["session"] = json.loads(json.dumps(coordinator_mod.serialize_runtime_value(session)))
                atteinte.set()
                await liberation.wait()

        coordinator._persist_runtime_state = _persist
        return atteinte, photo

    async def _redemarrer_depuis(self, plan, session_persistee):
        coordinator = self._coordinateur(plan)
        coordinator._runtime_state["active_irrigation_session"] = (
            coordinator_mod.deserialize_active_irrigation_session(session_persistee)
        )
        await coordinator._restore_active_irrigation_session()
        task = coordinator._auto_irrigation_task
        if task is not None:
            await task
        return coordinator

    async def test_arret_pendant_la_sauvegarde_finale_enregistre_l_eau_une_fois(self) -> None:
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        atteinte, _photo = self._bloquer_la_sauvegarde_finale(coordinator)
        self._lancer(coordinator, plan)
        await asyncio.wait_for(atteinte.wait(), timeout=5)

        resultat = await coordinator.async_stop_irrigation()

        self.assertEqual(coordinator.async_record_watering.await_count, 1)
        kwargs = coordinator.async_record_watering.await_args.kwargs
        self.assertAlmostEqual(kwargs["total_mm"], self.OBJECTIF_MM, places=1)
        self.assertAlmostEqual(resultat["applied_mm"], self.OBJECTIF_MM, places=1)
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])

    async def test_redemarrage_depuis_la_sauvegarde_finale_enregistre_l_eau_une_fois(self) -> None:
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        atteinte, photo = self._bloquer_la_sauvegarde_finale(coordinator)
        tache = self._lancer(coordinator, plan)
        await asyncio.wait_for(atteinte.wait(), timeout=5)
        # Coupure de Home Assistant pendant l'écriture : la tâche meurt, le disque garde la photo.
        tache.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await tache
        coordinator.async_record_watering.assert_not_awaited()

        redemarre = await self._redemarrer_depuis(plan, photo["session"])

        self.assertEqual(redemarre.async_record_watering.await_count, 1)
        kwargs = redemarre.async_record_watering.await_args.kwargs
        self.assertAlmostEqual(kwargs["total_mm"], self.OBJECTIF_MM, places=1)
        self.assertEqual(kwargs["watering_cause"], "hydrique")
        self.assertIsNone(redemarre._runtime_state["active_irrigation_session"])
        # Toutes les zones avaient tourné : la reprise enregistre sans rouvrir la moindre vanne.
        redemarre._attendre_zone_ouverte.assert_not_awaited()
        self.assertFalse(
            [appel for appel in redemarre._service_calls if appel[1] == "turn_on"],
            "aucune vanne ne doit être rouverte à la reprise",
        )

    async def test_arret_apres_enregistrement_ne_double_pas_l_eau(self) -> None:
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        atteinte = asyncio.Event()
        liberation = asyncio.Event()
        photo: dict[str, object] = {}

        async def _enregistrer(*args, **kwargs) -> None:
            if not atteinte.is_set():
                session = coordinator._runtime_state.get("active_irrigation_session")
                photo["session"] = json.loads(json.dumps(coordinator_mod.serialize_runtime_value(session)))
                atteinte.set()
                await liberation.wait()

        coordinator.async_record_watering = AsyncMock(side_effect=_enregistrer)
        self._lancer(coordinator, plan)
        await asyncio.wait_for(atteinte.wait(), timeout=5)
        self.assertTrue(photo["session"].get(coordinator_mod.WATERING_RECORDED_KEY))

        stop_task = asyncio.create_task(coordinator.async_stop_irrigation())
        await asyncio.sleep(0)
        self.assertFalse(stop_task.done())
        liberation.set()
        resultat = await stop_task

        # Seul l'enregistrement du cycle lui-même : aucun « arret_manuel » par-dessus.
        self.assertEqual(coordinator.async_record_watering.await_count, 1)
        self.assertEqual(coordinator.async_record_watering.await_args.kwargs["watering_cause"], "hydrique")
        self.assertEqual(resultat["applied_mm"], self.OBJECTIF_MM)
        self.assertIn(
            "gazon_intelligent_auto_irrigation_completed",
            [event for event, _payload in coordinator._events],
        )
        self.assertIsNotNone(coordinator._runtime_state["last_auto_irrigation_completed_at"])

        # Même fenêtre, redémarrage : la session marquée est clôturée sans réenregistrer.
        redemarre = await self._redemarrer_depuis(plan, photo["session"])
        redemarre.async_record_watering.assert_not_awaited()
        self.assertIsNone(redemarre._runtime_state["active_irrigation_session"])
        self.assertEqual(redemarre._runtime_state["last_irrigation_execution"]["status"], "completed")

    async def test_finalisation_bloquee_rend_la_main_sans_tuer_la_tache(self) -> None:
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        finalisation = self._suspendre_une_finalisation_deja_enregistree(coordinator, plan)

        with patch.object(
            coordinator_mod,
            "_STOP_FINALIZATION_TIMEOUT_SECONDS",
            0.01,
            create=True,
        ):
            resultat = await asyncio.wait_for(coordinator.async_stop_irrigation(), timeout=0.2)

        self.assertTrue(resultat["finalization_pending"])
        self.assertFalse(finalisation.done(), "le délai maximal a annulé la finalisation en cours")
        finalisation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await finalisation

    async def test_annuler_l_appel_n_est_pas_avale_et_ne_tue_pas_la_finalisation(self) -> None:
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        finalisation = self._suspendre_une_finalisation_deja_enregistree(coordinator, plan)

        arret = asyncio.create_task(coordinator.async_stop_irrigation())
        await asyncio.sleep(0)
        arret.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await arret

        self.assertFalse(finalisation.done(), "annuler l'appel a aussi annulé la finalisation")
        finalisation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await finalisation

    async def test_session_marquee_est_cloturee_comme_complete_meme_avec_erreur_reprise(self) -> None:
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        session = coordinator._build_active_irrigation_session(
            plan=plan,
            source="auto_irrigation",
            strategy="plan",
            watering_cause="hydrique",
        )
        session[coordinator_mod.WATERING_RECORDED_KEY] = True
        session["last_error"] = "restart_recovery"
        session["status"] = "recovery_required"
        session["zones_done"] = [{"passage": 1, "zone": "switch.zone_1", "mm": 3.0}]
        session["zones_pending"] = [{"passage": 1, "zone_index": 1, "zone": "switch.zone_2"}]
        coordinator._set_active_irrigation_session(session)

        self.assertIsNone(coordinator._get_active_irrigation_session())
        self.assertIsNone(coordinator._runtime_state["active_irrigation_session"])
        self.assertEqual(coordinator._runtime_state["last_irrigation_execution"]["status"], "completed")

    async def test_marqueur_et_historique_sont_sauvegardes_ensemble(self) -> None:
        """Vrai cerveau + vraie sauvegarde : le disque ne voit jamais le marqueur sans l'eau."""
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        coordinator.brain = brain_mod.GazonBrain()
        coordinator.async_record_watering = (
            coordinator_mod.GazonIntelligentCoordinator.async_record_watering.__get__(
                coordinator,
                type(coordinator),
            )
        )
        coordinator._async_save_state = (
            coordinator_mod.GazonIntelligentCoordinator._async_save_state.__get__(
                coordinator,
                type(coordinator),
            )
        )
        coordinator.async_request_refresh = AsyncMock()

        class _Store:
            def __init__(self) -> None:
                self.payloads: list[dict[str, object]] = []

            async def async_save(self, payload: dict[str, object]) -> None:
                self.payloads.append(json.loads(json.dumps(payload)))

        store = _Store()
        coordinator._store = store

        await coordinator._execute_canonical_watering_plan(
            plan=plan,
            source="auto_irrigation",
            strategy="plan",
            watering_cause="hydrique",
        )

        payload_marque = None
        for payload in store.payloads:
            runtime = payload.get("runtime")
            session = runtime.get("active_irrigation_session") if isinstance(runtime, dict) else None
            historique = [
                item for item in payload.get("history", []) if item.get("type") == "arrosage"
            ]
            if isinstance(session, dict) and session.get(coordinator_mod.WATERING_RECORDED_KEY):
                self.assertTrue(historique)
                payload_marque = payload
            if historique and isinstance(session, dict):
                self.assertTrue(session.get(coordinator_mod.WATERING_RECORDED_KEY))

        self.assertIsNotNone(payload_marque)
        relu = self._coordinateur(plan)
        relu.brain = brain_mod.GazonBrain()
        assert payload_marque is not None
        relu.brain.load_state(payload_marque)
        relu._restore_runtime_state(payload_marque.get("runtime"))

        self.assertTrue(
            relu._runtime_state["active_irrigation_session"].get(
                coordinator_mod.WATERING_RECORDED_KEY
            )
        )
        self.assertEqual(
            len([item for item in relu.brain.history if item.get("type") == "arrosage"]),
            1,
        )

    async def test_la_purge_retire_exactement_chaque_segment_joue(self) -> None:
        """Plan 2 zones × 2 passages : chaque fin de zone retire SON segment, et seulement lui."""
        plan = self._plan()
        coordinator = self._coordinateur(plan)
        etats: list[list[tuple[int, int]]] = []

        async def _persist() -> None:
            session = coordinator._runtime_state.get("active_irrigation_session")
            if not isinstance(session, dict):
                return
            etat = [(int(s["passage"]), int(s["zone_index"])) for s in session.get("zones_pending") or []]
            if not etats or etats[-1] != etat:
                etats.append(etat)

        coordinator._persist_runtime_state = _persist
        await self._lancer(coordinator, plan)

        self.assertEqual(
            etats,
            [
                [(1, 0), (1, 1), (2, 0), (2, 1)],
                [(1, 1), (2, 0), (2, 1)],
                [(2, 0), (2, 1)],
                [(2, 1)],
                [],
            ],
        )
        coordinator.async_record_watering.assert_awaited_once()


class TestDepartCaleSurLeLeverDuSoleil(unittest.TestCase):
    """Étape 2, arbitrage du 15/09/2026 : l'arrosage du matin finit 15 min avant le lever.

    La nuit l'ET est quasi nulle : partir plus tard qu'à 03:45 ne coûte rien au sol, et l'eau
    tombe sur la rosée. Aucun plafond lié à la tonte : choix retenu de tondre plus tard, dans
    des fenêtres élargies (`decision_mowing`), plutôt que d'avancer l'arrosage.
    """

    LEVER = {"sun_next_rising": "2026-09-15T05:34:00Z"}  # 07:34 à Paris
    PARIS = timezone(timedelta(hours=2))
    PLAN = "sensor.gazon_intelligent_plan_arrosage"

    def _coordinateur(self, *, heure: int, minute: int = 0, lever: dict | None = None,
                      delai_tonte: float | None = None):
        coordinator = _build_coordinator()
        coordinator.history = []
        memoire: dict[str, object] = {"auto_irrigation_enabled": True}
        if delai_tonte is not None:
            memoire["mowing_cooldown_after_watering_minutes"] = delai_tonte
        coordinator.memory = memoire
        contexte = dict(self.LEVER if lever is None else lever)
        coordinator._get_sun_context = lambda: dict(contexte)
        coordinator._current_datetime = lambda: datetime(2026, 9, 15, heure, minute, tzinfo=self.PARIS)
        return coordinator

    def _snapshot(self, coordinator, **over):
        # `maintenant` : la VRAIE valeur publiée de 03:45 à 10:00 en phase Normal. La fixture
        # partagée dit `matin`, qui n'existe pas (revue du 15/09) : un lanceur qui n'attendrait plus
        # sur `maintenant` passait toute la classe au vert.
        base = {
            "watering_window_start_minute": 225,
            "watering_window_end_minute": 600,
            "fenetre_optimale": "maintenant",
        }
        base.update(over)
        return _ready_launch_snapshot(coordinator, **base)

    def _decision(self, coordinator, **over):
        with _dt_util_avec_fuseau(type(coordinator)._sun_event_minute_from_context, heures=2):
            return coordinator._should_launch_auto_irrigation(self._snapshot(coordinator, **over))

    def _publie(self, coordinator, **over):
        with _dt_util_avec_fuseau(type(coordinator)._sun_event_minute_from_context, heures=2):
            return coordinator._build_public_snapshot_data(
                self._snapshot(coordinator, **over),
                pluie_demain_source="test",
                temperature=16.0,
                temperature_source="test",
                temperature_reference_hydrique=None,
                forecast_summary={},
                et0_source="test",
            )

    def test_la_fixture_dure_vingt_quatre_minutes(self) -> None:
        # 8 mm : zone 1 à 60 mm/h (8 min) + zone 2 à 30 mm/h (16 min). Départ attendu 07:19 − 24.
        coordinator = self._coordinateur(heure=5)
        plan = coordinator._get_canonical_watering_plan(objectif_mm=8.0, snapshot=self._snapshot(coordinator))
        self.assertEqual(plan.total_duration_s, 24 * 60)

    def test_avant_l_heure_calee_l_arrosage_attend(self) -> None:
        self.assertEqual(
            self._decision(self._coordinateur(heure=5)), (False, "waiting_sunrise_departure")
        )

    def test_frontiere_exacte_du_depart(self) -> None:
        # 07:34 − 15 − 24 = 06:55. Elle épingle la marge : sans elle, le départ glisserait à 07:10.
        self.assertEqual(
            self._decision(self._coordinateur(heure=6, minute=54)),
            (False, "waiting_sunrise_departure"),
        )
        self.assertEqual(self._decision(self._coordinateur(heure=6, minute=55)), (True, "ready"))

    def test_la_pause_entre_passages_compte_dans_la_duree(self) -> None:
        # Deux passages et 25 min de pause : 24 min d'eau + 25 min d'attente = 49 min, départ
        # 06:30. En oubliant la pause, le cycle partirait à 06:55 et finirait à 07:44.
        fractionne = {"watering_passages": 2, "watering_pause_minutes": 25}
        coordinator = self._coordinateur(heure=6, minute=29)
        plan = coordinator._get_canonical_watering_plan(
            objectif_mm=8.0, snapshot=self._snapshot(coordinator, **fractionne)
        )
        self.assertEqual(plan.total_duration_s, 49 * 60)
        self.assertEqual(self._decision(coordinator, **fractionne), (False, "waiting_sunrise_departure"))
        self.assertEqual(
            self._decision(self._coordinateur(heure=6, minute=30), **fractionne), (True, "ready")
        )

    def test_le_delai_de_reprise_de_tonte_ne_decale_plus_le_depart(self) -> None:
        # Le premier jet plafonnait la fin à 10:00 − délai (07:00 avec 180 min). Retiré le 15/09 :
        # quel que soit le délai réglé, le départ reste 06:55.
        for delai in (0, 120, 180, 240):
            with self.subTest(delai_tonte=delai):
                self.assertEqual(
                    self._decision(self._coordinateur(heure=6, minute=54, delai_tonte=delai)),
                    (False, "waiting_sunrise_departure"),
                )
                self.assertEqual(
                    self._decision(self._coordinateur(heure=6, minute=55, delai_tonte=delai)),
                    (True, "ready"),
                )

    def test_le_plan_publie_par_l_entite_fait_foi(self) -> None:
        # Même résolution que l'exécuteur : le plan de l'entité d'abord. Ici 60 min au lieu des 24
        # du plan recalculé depuis l'objectif : départ 06:19, et non 06:55.
        coordinator = self._coordinateur(heure=6, minute=30)
        coordinator._plan_arrosage_entity_id = lambda: self.PLAN
        coordinator.hass = _FakeHass(
            states=_FakeStates(
                {
                    self.PLAN: _FakeState(
                        state="8.0",
                        last_changed=datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc),
                        attributes={
                            "objective_mm": 8.0,
                            "zones": [
                                {"entity_id": "switch.zone_1", "duration_s": 1800, "rate_mm_h": 16.0},
                                {"entity_id": "switch.zone_2", "duration_s": 1800, "rate_mm_h": 16.0},
                            ],
                        },
                    )
                }
            )
        )
        self.assertEqual(self._decision(coordinator), (True, "ready"))
        self.assertEqual(self._publie(coordinator)["watering_departure_minute"], 6 * 60 + 19)

    def test_la_marge_avant_le_lever_suit_le_reglage_de_la_page(self) -> None:
        # Marge réglée à 30 min : 07:34 − 30 − 24 = 06:40, pour le lanceur ET pour l'heure publiée.
        def avec_marge(heure: int, minute: int = 0):
            coordinator = self._coordinateur(heure=heure, minute=minute)
            coordinator.entry.options = {"reglages": {"arrosage_marge_avant_lever": 30}}
            return coordinator

        self.assertEqual(self._decision(avec_marge(6, 39)), (False, "waiting_sunrise_departure"))
        self.assertEqual(self._decision(avec_marge(6, 40)), (True, "ready"))
        self.assertEqual(self._publie(avec_marge(5))["watering_departure_minute"], 6 * 60 + 40)

    def test_sans_lever_connu_on_part_a_l_ouverture_comme_avant(self) -> None:
        self.assertEqual(self._decision(self._coordinateur(heure=4, lever={})), (True, "ready"))

    def test_le_semis_n_attend_pas_le_lever(self) -> None:
        coordinator = self._coordinateur(heure=5)
        coordinator._semis_cycle_progress = lambda snapshot: {"cycles_remaining_today": 3, "state": "ready"}
        self.assertEqual(self._decision(coordinator), (True, "ready"))

    def test_la_detresse_tondeuse_n_attend_pas_le_lever(self) -> None:
        coordinator = self._coordinateur(heure=5)
        coordinator._mower_block_age_minutes = lambda snapshot: 90.0
        decision = self._decision(
            coordinator,
            watering_blocked_by_mower=True,
            irrigation_blocked_but_critical=True,
            watering_block_reason_code="mower_not_stowed",
            block_reason="mower_not_stowed",
        )
        self.assertEqual(decision, (True, "ready"))

    def test_le_rafraichissement_du_soir_n_est_pas_concerne(self) -> None:
        coordinator = self._coordinateur(heure=20, minute=30)
        decision = self._decision(
            coordinator, fenetre_optimale="soir", watering_cause="rafraichissement_soir"
        )
        self.assertEqual(decision, (True, "ready"))

    def test_l_heure_publiee_est_celle_du_lanceur(self) -> None:
        payload = self._publie(self._coordinateur(heure=5))
        self.assertEqual(payload["watering_departure_minute"], 6 * 60 + 55)
        self.assertEqual(payload["watering_end_minute"], 7 * 60 + 19)
        # Et le lanceur part bien à cette minute-là, pas une de plus ni de moins.
        self.assertEqual(self._decision(self._coordinateur(heure=6, minute=55)), (True, "ready"))

    def test_un_cycle_trop_long_est_annonce_a_l_ouverture(self) -> None:
        # 80 mm : 240 min de cycle, fin visée 07:19 → départ théorique 03:19, avant l'ouverture.
        # L'heure publiée est l'ouverture (03:45), celle où les vannes s'ouvriront vraiment.
        payload = self._publie(self._coordinateur(heure=2), objectif_mm=80.0)
        self.assertEqual(payload["watering_departure_minute"], 225)
        self.assertEqual(payload["watering_end_minute"], 225 + 240)

    def test_rien_n_est_publie_sans_arrosage_demande(self) -> None:
        payload = self._publie(self._coordinateur(heure=5), objectif_mm=0.0)
        self.assertIsNone(payload["watering_departure_minute"])
        self.assertIsNone(payload["watering_end_minute"])

    def test_aucun_depart_cale_n_est_annonce_quand_le_lanceur_en_est_exempte(self) -> None:
        # Revue du 15/09 : la publication ignorait les exemptions du lanceur. Un semis prêt à 04:00
        # se voyait annoncer un départ calé sur le lever, qu'il n'attendrait jamais.
        cas = {
            "semis": ({}, lambda c: setattr(
                c, "_semis_cycle_progress",
                lambda snapshot: {"cycles_remaining_today": 3, "state": "ready"},
            )),
            # Un semis entre deux cycles n'attend pas davantage le lever : ses créneaux sont les siens.
            "semis_en_attente": ({}, lambda c: setattr(
                c, "_semis_cycle_progress",
                lambda snapshot: {"cycles_remaining_today": 2, "state": "waiting"},
            )),
            "post_produit": ({
                "type_arrosage": "application_technique_auto",
                "application_post_watering_status": "autorise",
            }, None),
            "soir": ({"fenetre_optimale": "soir", "watering_cause": "rafraichissement_soir"}, None),
            "tondeuse": ({"watering_blocked_by_mower": True}, None),
        }
        for nom, (surcharge, preparer) in cas.items():
            with self.subTest(exemption=nom):
                coordinator = self._coordinateur(heure=4)
                if preparer is not None:
                    preparer(coordinator)
                payload = self._publie(coordinator, **surcharge)
                self.assertIsNone(payload["watering_departure_minute"])
                self.assertIsNone(payload["watering_end_minute"])
        # Contrôle : sans exemption, la même heure est bien publiée.
        self.assertEqual(self._publie(self._coordinateur(heure=4))["watering_departure_minute"], 6 * 60 + 55)
        # Et un produit dont l'arrosage n'est pas encore autorisé n'exempte rien : seul le statut
        # « autorise » fait partir l'incorporation.
        en_attente = self._publie(
            self._coordinateur(heure=4),
            type_arrosage="application_technique_auto",
            application_post_watering_status="en_attente",
        )
        self.assertEqual(en_attente["watering_departure_minute"], 6 * 60 + 55)

    def test_la_veille_au_soir_l_heure_est_publiee_pour_demain(self) -> None:
        # 21:00 : la décision publie `demain_matin`. L'heure calée doit déjà être annoncée.
        payload = self._publie(self._coordinateur(heure=21), fenetre_optimale="demain_matin")
        self.assertEqual(payload["watering_departure_minute"], 6 * 60 + 55)
        self.assertEqual(payload["watering_end_minute"], 7 * 60 + 19)

    def test_aucune_heure_n_est_annoncee_quand_l_arrosage_auto_ne_partira_pas(self) -> None:
        # Revue du 15/09 : verrou de sécurité actif, « Prochain arrosage » et la carte annonçaient
        # « 06:15 → 07:19 » pendant que « Blocage arrosage auto » disait « Bloqué (sécurité) ».
        def verrou(c):
            c._runtime_state["auto_irrigation_safety_lock"] = True

        def interrupteur_coupe(c):
            c.memory["auto_irrigation_enabled"] = False

        cas = {
            "verrou_de_securite": ({}, verrou),
            "arrosage_auto_coupe": ({}, interrupteur_coupe),
            "arrosage_auto_non_autorise": ({"arrosage_auto_autorise": False}, None),
            "execution_refusee": ({"irrigation_execution_allowed": False}, None),
            "fenetre_attendre": ({"fenetre_optimale": "attendre"}, None),
        }
        for nom, (surcharge, preparer) in cas.items():
            with self.subTest(cas=nom):
                coordinator = self._coordinateur(heure=4)
                if preparer is not None:
                    preparer(coordinator)
                payload = self._publie(coordinator, **surcharge)
                self.assertIsNone(payload["watering_departure_minute"])
                self.assertIsNone(payload["watering_end_minute"])
                # Et le lanceur refuse bien, lui aussi : les deux sorties disent la même chose.
                self.assertFalse(self._decision(coordinator, **surcharge)[0])

    def test_le_coucher_publie_est_celui_du_jour_la_veille_du_passage_a_l_heure_d_ete(self) -> None:
        # Le coucher nourrit la nuit de la tonte (coucher + 30 min). Le soir du 27/03/2027, lu sur
        # `next_setting` (le 28/03, déjà en heure d'été), il annonçait 20:13 au lieu de ~19:13.
        coordinator = self._coordinateur(heure=5)
        coordinator._current_datetime = lambda: datetime(2027, 3, 27, 19, 50, tzinfo=ZoneInfo("Europe/Paris"))
        reel = type(coordinator)._sun_event_minute_from_context.__globals__["dt_util"]

        class _DtUtilParis:
            def __getattr__(self, nom):
                return getattr(reel, nom)

            @staticmethod
            def parse_datetime(valeur):
                return datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))

            @staticmethod
            def as_local(valeur):
                return valeur.astimezone(ZoneInfo("Europe/Paris"))

        with patch.dict(type(coordinator)._sun_event_minute_from_context.__globals__, {"dt_util": _DtUtilParis()}):
            coucher = coordinator._sunset_minute_from_context({"sun_next_setting": "2027-03-28T18:13:00Z"})
        self.assertEqual(coucher, 19 * 60 + 13)

    def test_attendre_le_depart_n_est_pas_trace_comme_un_refus(self) -> None:
        # « Derniers refus » : attendre l'heure prévue n'en est pas un. Sans ce filtre, un refus
        # s'écrirait chaque matin d'arrosage.
        coordinator = self._coordinateur(heure=5)
        traces: list[str] = []
        coordinator.brain.record_skip = lambda **kw: traces.append(kw["reason"])
        snapshot = self._snapshot(coordinator, fenetre_optimale="maintenant")
        coordinator._maybe_record_skip(snapshot, "waiting_sunrise_departure")
        self.assertEqual(traces, [])
        # Contrôle : un vrai refus, lui, est bien tracé.
        coordinator._maybe_record_skip(snapshot, "irrigation_blocked")
        self.assertEqual(traces, ["irrigation_blocked"])


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

    def test_la_proratisation_atteint_vraiment_la_dose_enregistree(self) -> None:
        """⚠️ Elle ne servait à rien : la fin de cycle enregistrait l'objectif PRÉVU.

        `_build_zone_execution_record` proratise bien `zones_done` quand un relais retombe,
        mais la voie nominale appelait `async_record_watering` avec `plan.objective_mm`.
        L'historique, le bilan du sol et le budget hebdomadaire créditaient donc l'eau qui
        n'a pas coulé — et le système sous-arrosait ensuite, exactement ce que la
        surveillance de vanne devait éviter. Ce test part des enregistrements d'exécution,
        pas du plan.
        """
        # Trois zones prévues à 5 mm ; la deuxième n'a coulé qu'à moitié.
        executes = [
            {"zone": "switch.zone_1", "mm": 5.0},
            {"zone": "switch.zone_2", "mm": 2.5, "interrupted": True},
            {"zone": "switch.zone_3", "mm": 5.0},
        ]
        water = importlib.import_module("custom_components.gazon_intelligent.water")
        surface = water.surface_mm_depuis_segments(executes, zones_prevues=3)
        self.assertEqual(surface, 4.2)          # (5 + 2,5 + 5) / 3
        self.assertNotEqual(surface, 5.0, "la dose prévue a été réenregistrée telle quelle")

        # Et sans chute de vanne, la voie nominale doit rendre l'objectif exact.
        complets = [{"zone": f"switch.zone_{i}", "mm": 5.0} for i in (1, 2, 3)]
        self.assertEqual(water.surface_mm_depuis_segments(complets, zones_prevues=3), 5.0)


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


class LesDrapeauxDeSanteTestentLaSourceTests(unittest.TestCase):
    """Les voyants doivent tomber quand le CAPTEUR tombe, pas quand le repli tombe aussi.

    Mesuré sur 144 h, trois drapeaux alimentés par LA MÊME station physique :
    `pluie_valid` faux 2,19 h · `eto_pressure_measured` 1,16 h · `temperature_valid` **0,08 h**
    · `humidity_valid` **0,08 h**. Les deux derniers testaient la valeur RÉSOLUE, donc
    post-repli. Instant citable : 29/07/2026 17:57:46, `temperature_valid: true` alors que le
    capteur de température était indisponible depuis 17:52:53 et que l'ET0 tournait sur le
    repli météo.
    """

    def _sante(self, *, temperature_source, humidite_capteur, vent_capteur, weather_profile,
               conf=("sensor.t", "sensor.h", "sensor.v"),
               temperature=None, humidite=None, vent=None):
        """Appelle la VRAIE méthode du coordinateur, pas une reproduction de son expression."""
        conf_t, conf_h, conf_v = conf
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._get_conf = lambda cle: {
            "capteur_temperature": conf_t,
            "capteur_humidite": conf_h,
            "capteur_vent": conf_v,
            "capteur_pluie_24h": "sensor.pluie",
            "capteur_etp": "sensor.etp",
        }.get(cle)
        coord._etp_ecoulee_du_jour = lambda: {"etp_ecoulee_mm": None, "etp_jour_estime_mm": None}
        return coord._build_sensor_health(
            temperature_source=temperature_source,
            humidite_capteur=humidite_capteur,
            vent_capteur=vent_capteur,
            etp_capteur=3.0,
            pluie_24h_sensor=0.0,
            weather_profile=weather_profile,
            eto_hourly={"radiation_source": "capteur", "pressure_source": "capteur", "value": 0.3},
            temperature=temperature,
            humidite=humidite,
            vent=vent,
        )

    def test_les_valeurs_utilisees_sont_publiees_avec_leur_unite(self) -> None:
        """⚠️ LE DRAPEAU DIT D'OÙ, LA VALEUR DIT QUOI — les deux sont nécessaires.

        Sans la valeur, impossible de décomposer une ET0 surprenante, de vérifier qu'un
        changement de capteur a bougé le nombre, ni de contrôler une conversion d'unité :
        `wind_speed_to_kmh` et `pression_vers_hpa` transforment selon l'unité DÉCLARÉE, et une
        unité inattendue passe avec tous les voyants au vert (le WS90 publie des kPa).
        """
        s = self._sante(temperature_source="capteur", humidite_capteur=55.0,
                        vent_capteur=6.0, weather_profile={"weather_temperature": 24.0},
                        temperature=28.34, humidite=55.27, vent=6.049)
        self.assertEqual(s["temperature_utilisee_c"], 28.3)
        self.assertEqual(s["humidite_utilisee_pct"], 55.3)
        self.assertEqual(s["vent_utilise_kmh"], 6.05)

    def test_la_valeur_publiee_est_la_RESOLUE_pas_celle_du_capteur(self) -> None:
        """Sous repli, le drapeau tombe au rouge MAIS la valeur reste lisible.

        C'est tout l'intérêt de la paire : on voit que la mesure vient de la météo, ET on voit
        sur quel nombre la décision a été prise. Le 29/07, deux secondes de repli du vent ont
        posé le pic d'ET0 du jour à 12,4 — invisible sans cette valeur.
        """
        s = self._sante(temperature_source="weather", humidite_capteur=None,
                        vent_capteur=None, weather_profile={"weather_temperature": 24.0},
                        temperature=24.0, humidite=70.0, vent=12.1)
        self.assertFalse(s["temperature_valid"], "prémisse : on est bien sur un repli")
        self.assertEqual(s["temperature_utilisee_c"], 24.0)
        self.assertEqual(s["vent_utilise_kmh"], 12.1, "la valeur du repli doit rester visible")

    def test_le_point_d_APPEL_transmet_bien_les_trois_valeurs(self) -> None:
        """⚠️ LE CÂBLAGE, PAS LA FONCTION — défaut n°1 du projet, payé cinq fois.

        Les trois paramètres ont un défaut `None` : un point d'appel qui ne les passe pas
        laisserait les clés publiées mais TOUJOURS nulles, et aucun test de la fonction seule
        ne le verrait. On lit donc le point d'appel réel dans le code source.
        """
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        bloc = source.split("self._build_sensor_health(", 1)
        self.assertEqual(len(bloc), 2, "le point d'appel a disparu")
        appel = bloc[1].split(")", 1)[0]
        for kwarg in ("temperature=temperature", "humidite=humidite", "vent=vent"):
            with self.subTest(kwarg=kwarg):
                self.assertIn(kwarg, appel, f"{kwarg} n'est pas transmis au point d'appel")

    def test_une_mesure_absente_publie_None_pas_zero(self) -> None:
        """« Absent » et « zéro » ne sont pas la même chose — piège récurrent du projet."""
        s = self._sante(temperature_source="non disponible", humidite_capteur=None,
                        vent_capteur=None, weather_profile={},
                        temperature=None, humidite=None, vent=None)
        for cle in ("temperature_utilisee_c", "humidite_utilisee_pct", "vent_utilise_kmh"):
            with self.subTest(cle=cle):
                self.assertIsNone(s[cle])

    def test_le_repli_meteo_ne_maintient_plus_les_voyants_au_vert(self) -> None:
        """Le cas du 29/07 : capteur tombé, valeur résolue depuis la météo."""
        s = self._sante(temperature_source="weather", humidite_capteur=None,
                        vent_capteur=None, weather_profile={"weather_temperature": 24.0})
        self.assertFalse(s["temperature_valid"])
        self.assertFalse(s["humidity_valid"])
        self.assertFalse(s["wind_measured"])

    def test_les_capteurs_sains_restent_au_vert(self) -> None:
        s = self._sante(temperature_source="capteur", humidite_capteur=55.0,
                        vent_capteur=6.0, weather_profile={"weather_temperature": 24.0})
        for drapeau in ("temperature_valid", "humidity_valid", "wind_measured", "wind_valid",
                        "weather_profile_available", "pluie_valid", "etp_valid"):
            with self.subTest(drapeau=drapeau):
                self.assertTrue(s[drapeau], f"{drapeau} au rouge alors que tout est mesuré")

    def test_une_installation_sans_capteur_configure_nest_pas_en_alarme(self) -> None:
        """Sans capteur déclaré, le repli est le fonctionnement NORMAL, pas une panne."""
        s = self._sante(temperature_source="weather", humidite_capteur=None, vent_capteur=None,
                        weather_profile={"x": 1}, conf=(None, None, None))
        self.assertTrue(s["temperature_valid"])
        self.assertTrue(s["humidity_valid"])
        self.assertTrue(s["wind_valid"])
        self.assertFalse(s["wind_measured"], "wind_measured reste factuel : rien n'est mesuré")

    def test_la_perte_de_l_entite_meteo_est_visible(self) -> None:
        """03/08/2026 : indisponible 64 min hors redémarrage, tous les voyants au vert."""
        self.assertFalse(
            self._sante(temperature_source="capteur", humidite_capteur=55.0,
                        vent_capteur=6.0, weather_profile={})["weather_profile_available"]
        )


class LEtpEcouleeDuJourEstExposeeTests(unittest.TestCase):
    """L'ET réellement débitée n'était visible nulle part — seule l'estimation l'était.

    Sur 8 jours : 36,7 mm débités contre 49,1 mm estimés, +33,8 %, 8 jours sur 8 dans le même
    sens. C'est ce chiffre qui aurait montré d'un coup d'œil la marche du 29/07 (+1,0 mm en
    68 secondes, soit 53 mm/h, quand l'ET0 horaire réelle plafonne vers 0,6).
    """

    def _coord(self, soil_balance):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.brain = types.SimpleNamespace(soil_balance=soil_balance)
        coord._current_date = lambda: date(2026, 8, 6)
        return coord

    def test_l_entree_du_jour_est_lue(self) -> None:
        c = self._coord({"ledger": [
            {"date": "2026-08-05", "etp_elapsed_mm": 3.1, "etp_mm": 5.0},
            {"date": "2026-08-06", "etp_elapsed_mm": 4.237, "etp_mm": 6.1},
        ]})
        self.assertEqual(
            c._etp_ecoulee_du_jour(),
            {"etp_ecoulee_mm": 4.237, "etp_jour_estime_mm": 6.1},
        )

    def test_une_entree_d_hier_n_est_pas_presentee_comme_celle_du_jour(self) -> None:
        c = self._coord({"ledger": [{"date": "2026-08-05", "etp_elapsed_mm": 3.1, "etp_mm": 5.0}]})
        self.assertEqual(
            c._etp_ecoulee_du_jour(),
            {"etp_ecoulee_mm": None, "etp_jour_estime_mm": None},
        )

    def test_un_journal_absent_ou_corrompu_ne_prive_pas_des_autres_voyants(self) -> None:
        """Ce bloc alimente sensor_health : une exception ici masquerait TOUS les voyants."""
        for etat in (None, {}, {"ledger": None}, {"ledger": []}, {"ledger": ["pas un dict"]},
                     {"ledger": [{"date": None}]}, "pas un dict"):
            with self.subTest(soil_balance=etat):
                resultat = self._coord(etat)._etp_ecoulee_du_jour()
                self.assertEqual(set(resultat), {"etp_ecoulee_mm", "etp_jour_estime_mm"})


class LHorodatageEstBrancheSurLesDeuxVoiesTests(unittest.TestCase):
    """Un correctif livré mais non exécuté est pire qu'un correctif absent : on le croit fait.

    Le correctif du 04/08/2026 — enregistrer le DÉBUT de l'arrosage et non sa fin — n'avait été
    branché que sur la voie de DÉTECTION. Sur la voie PILOTÉE, celle des cycles lancés par
    l'intégration donc de l'arrosage automatique de tous les matins, l'historique recevait
    toujours l'instant de fin : l'affichage annonçait « arrosé à 05:18 » pour un cycle parti à
    03:45:13. Vérifié sur les vannes : Z1 03:45→04:18, Z2 04:18→04:51, Z3 04:51→05:18.
    """

    def test_la_voie_pilotee_transmet_le_debut_de_session(self) -> None:
        plan = watering_plan_mod.build_watering_plan(
            1.5, [("switch.zone_1", 60.0), ("switch.zone_2", 30.0)]
        )
        assert plan is not None
        coordinator = _build_runtime_ready_coordinator(plan_attrs=plan.as_dict())

        async def _run() -> None:
            original_sleep = coordinator_mod.asyncio.sleep

            async def _no_sleep(_delay: float) -> None:
                return None

            coordinator_mod.asyncio.sleep = _no_sleep
            try:
                await coordinator_mod.GazonIntelligentCoordinator.async_start_auto_irrigation(
                    coordinator, 1.5,
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
        kwargs = coordinator.async_record_watering.await_args.kwargs
        self.assertIn(
            "started_at", kwargs,
            "la voie pilotée n'enregistre toujours que l'instant de fin",
        )
        self.assertIsNotNone(
            kwargs["started_at"],
            "le début de session est transmis mais vide",
        )

    def test_aucune_voie_interne_n_oublie_le_debut(self) -> None:
        """Invariant de source : le défaut de cette famille, c'est le correctif À MOITIÉ appliqué.

        Trois voies enregistrent un arrosage dans le coordinateur (détection, cycle piloté,
        cycle interrompu). Le correctif n'en couvrait qu'une. Ce test échouera si une
        quatrième voie apparaît sans transmettre le début — c'est précisément le mode de
        défaillance qu'on veut interdire.
        """
        source = (
            Path(coordinator_mod.__file__).read_text(encoding="utf-8").split("\n")
        )
        oublis: list[int] = []
        for i, ligne in enumerate(source):
            if "await self.async_record_watering(" not in ligne:
                continue
            bloc: list[str] = []
            for suite in source[i + 1: i + 40]:
                bloc.append(suite)
                if suite.strip() == ")":
                    break
            if not any("started_at=" in x for x in bloc):
                oublis.append(i + 1)
        self.assertEqual(
            oublis, [],
            f"appel(s) à async_record_watering sans `started_at=` aux lignes {oublis}",
        )


class LaTraceDuCycleTests(unittest.TestCase):
    """Instrumentation de l'objectif non reproductible — on mesure avant de corriger.

    Le 06/08/2026, `objectif_d_arrosage` est passé de 5,0 à 0,0 avec réserve, déficits, ETP,
    température, `depletion_ratio` et `block_reason` **tous identiques** : 9 bascules en une
    heure, aucun `unavailable` dans la fenêtre. La sortie n'est donc pas reconstructible depuis
    ce que le système publie. Deux passes concurrentes (événement de capteur / intervalle de
    2 min) sont la piste — encore faut-il savoir laquelle a produit une publication donnée.
    """

    def _coord(self):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._current_datetime = lambda: datetime(2026, 8, 6, 13, 41, 44, tzinfo=timezone.utc)
        return coord

    def test_sans_evenement_l_origine_est_l_intervalle(self) -> None:
        trace = self._coord()._tracer_cycle()
        self.assertEqual(trace["cycle_origine"], "intervalle")
        self.assertEqual(trace["cycle_sequence"], 1)
        self.assertTrue(trace["cycle_at"])

    def test_un_changement_de_capteur_est_nomme(self) -> None:
        coord = self._coord()
        coord._marquer_origine_cycle("capteur:sensor.meteo_netatmo_temperature")
        self.assertEqual(
            coord._tracer_cycle()["cycle_origine"],
            "capteur:sensor.meteo_netatmo_temperature",
        )

    def test_l_origine_est_consommee_une_seule_fois(self) -> None:
        """Sinon un événement unique teinterait tous les cycles suivants."""
        coord = self._coord()
        coord._marquer_origine_cycle("capteur:sensor.x")
        self.assertEqual(coord._tracer_cycle()["cycle_origine"], "capteur:sensor.x")
        self.assertEqual(coord._tracer_cycle()["cycle_origine"], "intervalle")

    def test_le_premier_evenement_gagne(self) -> None:
        """Plusieurs capteurs peuvent bouger avant que le cycle ne parte."""
        coord = self._coord()
        coord._marquer_origine_cycle("capteur:sensor.a")
        coord._marquer_origine_cycle("capteur:sensor.b")
        self.assertEqual(coord._tracer_cycle()["cycle_origine"], "capteur:sensor.a")

    def test_la_sequence_s_incremente(self) -> None:
        """Deux publications de la même seconde se distinguent par leur numéro."""
        coord = self._coord()
        self.assertEqual(
            [coord._tracer_cycle()["cycle_sequence"] for _ in range(3)], [1, 2, 3]
        )

    def test_une_trace_ne_casse_jamais_un_cycle(self) -> None:
        """Aucune décision ne dépend de cette trace : elle doit échouer en silence."""
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)

        def _horloge_cassee():
            raise RuntimeError("horloge indisponible")

        coord._current_datetime = _horloge_cassee
        trace = coord._tracer_cycle()
        self.assertEqual(set(trace), {"cycle_origine", "cycle_sequence", "cycle_at"})
        self.assertEqual(trace["cycle_origine"], "inconnue")


class LaFiabiliteDeLaTondeuseEstSuivieTests(unittest.TestCase):
    """L'intégration voyait chaque erreur passer sans en garder trace.

    Impossible, sans rejouer l'historique à la main, de découvrir que le robot passait plus de
    temps coincé qu'à tondre. Mesuré du 02 au 05/08/2026 :

        jour     tondu     bloqué   épisodes
        02/08    130 min   123 min      3
        03/08    174 min   318 min      2      ← bloquée ~2× plus qu'elle ne tond
        04/08    286 min   321 min      6
        05/08    302 min    53 min      3

    contre ZÉRO blocage les 26, 28 et 30/07.
    """

    def _coord(self, instant):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {}
        coord._current_datetime = lambda: instant
        coord._current_date = lambda: instant.date()
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        return coord

    def _ctx(self, *, erreur=None, tonte=False, connectee=True):
        return {
            "tondeuse_connectee": connectee,
            "tondeuse_erreur": erreur,
            "mower_is_mowing": tonte,
        }

    def _rejouer(self, sequence, *, depart=None):
        """Rejoue une suite (minutes, contexte) et rend le dernier état publié."""
        t0 = depart or datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
        coord = self._coord(t0)
        sortie = {}
        for minutes, ctx in sequence:
            coord._current_datetime = lambda t=t0 + timedelta(minutes=minutes): t
            coord._current_date = lambda t=t0 + timedelta(minutes=minutes): t.date()
            sortie = coord._suivre_fiabilite_tondeuse(dict(ctx))
        return sortie

    def test_le_temps_bloque_et_le_temps_tondu_sont_cumules(self) -> None:
        r = self._rejouer([
            (0, self._ctx(tonte=True)),
            (5, self._ctx(tonte=True)),          # 5 min de tonte
            (10, self._ctx(erreur="lifted")),    # 5 min de tonte de plus
            (14, self._ctx(erreur="lifted")),    # 4 min bloquée
            (18, self._ctx(tonte=True)),         # 4 min bloquée de plus
        ])
        self.assertAlmostEqual(r["mower_mowing_minutes_today"], 10.0, places=1)
        self.assertAlmostEqual(r["mower_blocked_minutes_today"], 8.0, places=1)
        self.assertEqual(r["mower_block_count_today"], 1)

    def test_chaque_blocage_distinct_est_compte(self) -> None:
        r = self._rejouer([
            (0, self._ctx(tonte=True)),
            (2, self._ctx(erreur="lifted")),
            (4, self._ctx(tonte=True)),
            (6, self._ctx(erreur="trapped_timeout")),
            (8, self._ctx(tonte=True)),
        ])
        self.assertEqual(r["mower_block_count_today"], 2)

    def test_bloquee_plus_qu_elle_ne_tond_est_critique(self) -> None:
        """Le 03/08 : 174 min tondues contre 318 bloquées."""
        r = self._rejouer([
            (0, self._ctx(tonte=True)),
            (10, self._ctx(erreur="wheel_motor_blocked")),
            (14, self._ctx(erreur="wheel_motor_blocked")),
            (24, self._ctx(tonte=True)),
        ])
        self.assertEqual(r["mower_reliability_today"], "critique")

    def test_une_journee_sans_incident_reste_normale(self) -> None:
        """Les 26, 28 et 30/07 : zéro blocage."""
        r = self._rejouer([(0, self._ctx(tonte=True)), (10, self._ctx(tonte=True))])
        self.assertEqual(r["mower_reliability_today"], "normale")
        self.assertEqual(r["mower_block_count_today"], 0)

    def test_une_tondeuse_injoignable_n_est_PAS_une_journee_parfaite(self) -> None:
        """RÈGLE DE LA MAISON : une absence de mesure n'est pas une absence de blocage."""
        r = self._rejouer([
            (0, self._ctx(erreur="lifted")),
            (5, self._ctx(connectee=False)),   # liaison perdue
            (30, self._ctx(connectee=False)),
            (35, self._ctx(tonte=True)),
        ])
        self.assertAlmostEqual(r["mower_blocked_minutes_today"], 5.0, places=1,
                               msg="le trou de liaison a été crédité comme du temps sain")
        self.assertAlmostEqual(r["mower_mowing_minutes_today"], 0.0, places=1)

    def test_un_arret_de_home_assistant_ne_cree_pas_des_heures_fictives(self) -> None:
        """Au-delà de 15 min entre deux cycles, c'est un trou, pas une durée."""
        r = self._rejouer([
            (0, self._ctx(erreur="lifted")),
            (240, self._ctx(erreur="lifted")),   # 4 h plus tard : redémarrage
        ])
        self.assertAlmostEqual(r["mower_blocked_minutes_today"], 0.0, places=1)

    def test_le_compteur_repart_a_zero_le_lendemain(self) -> None:
        t0 = datetime(2026, 8, 6, 23, 50, tzinfo=timezone.utc)
        coord = self._coord(t0)
        coord._suivre_fiabilite_tondeuse(self._ctx(erreur="lifted"))
        coord._current_datetime = lambda: t0 + timedelta(minutes=20)
        coord._current_date = lambda: (t0 + timedelta(minutes=20)).date()
        r = coord._suivre_fiabilite_tondeuse(self._ctx(tonte=True))
        self.assertEqual(r["mower_block_count_today"], 0)
        self.assertAlmostEqual(r["mower_blocked_minutes_today"], 0.0, places=1)

    def test_un_compteur_ne_casse_jamais_un_cycle(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        r = coord._suivre_fiabilite_tondeuse({"tondeuse_connectee": True})
        self.assertEqual(set(r), {
            "mower_blocked_minutes_today", "mower_mowing_minutes_today",
            "mower_block_count_today", "mower_reliability_today",
        })


class LaBandeMorteDEt0SurvitAuRedemarrageTests(unittest.TestCase):
    """La mémoire de la bande morte doit faire l'aller-retour complet jusqu'au disque.

    ⚠️ TROISIÈME FOIS SUR CETTE FAMILLE DE CLÉS. `mower_health` (0.50.0) puis
    `risque_amortissement` (0.65.0) ont tous deux été produits, rangés, et perdus faute
    d'une liste blanche. Une mémoire non persistée repart vide à chaque redémarrage — et sur
    cette installation les redémarrages sont fréquents.
    """

    def _coord(self, palier, montee=None):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {
            "active_irrigation_session": None,
            "last_irrigation_execution": None,
            "last_auto_irrigation_reason": None,
            "last_auto_irrigation_completed_at": None,
            "auto_irrigation_safety_lock": False,
            "stress_palier_et0": palier,
            "stress_palier_et0_montee": montee,
        }
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        return coord

    def test_le_palier_atteint_le_disque(self) -> None:
        serialise = self._coord(2)._serialized_runtime_state()
        self.assertIn("stress_palier_et0", serialise,
                      "le palier d'ET0 n'est jamais persisté : bande morte perdue au redémarrage")
        self.assertEqual(serialise["stress_palier_et0"], 2)

    def test_le_palier_est_relu_au_demarrage(self) -> None:
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state({"stress_palier_et0": 2})
        self.assertEqual(relu._runtime_state.get("stress_palier_et0"), 2,
                         "le palier est écrit sur le disque puis ignoré au rechargement")

    def test_aller_retour_complet(self) -> None:
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(self._coord(3)._serialized_runtime_state())
        self.assertEqual(relu._runtime_state["stress_palier_et0"], 3)

    def test_la_montee_candidate_survit_au_redemarrage(self) -> None:
        montee = {"palier": 2, "depuis": "2026-09-20T16:44:00+00:00"}
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(self._coord(0, montee)._serialized_runtime_state())
        self.assertEqual(relu._runtime_state["stress_palier_et0_montee"], montee)

    def test_le_palier_traverse_la_SECONDE_liste_blanche(self) -> None:
        """⚠️ LE PIÈGE DU PROJET, TROISIÈME FOIS SUR CETTE FAMILLE DE CLÉS.

        Atteindre le snapshot de la décision ne suffit pas : le coordinateur RECOPIE ensuite
        clé par clé, et seules celles de `_COORDINATOR_SNAPSHOT_KEYS` passent. C'est là que
        `risque_amortissement` s'était perdu en 0.65.0 — persisté `null`, amortissement
        inopérant, tout en ayant l'air parfaitement branché.

        Le banc l'a reconfirmé sur cette clé-ci : la retirer de la liste ne faisait tomber
        aucun test. On rejoue donc la recopie RÉELLE du coordinateur, pas une appartenance.
        """
        snapshot = {
            "stress_palier_et0": 2,
            "stress_palier_et0_montee": {"palier": 3, "depuis": "maintenant"},
            "risque_gazon": "modere",
        }
        recopie = {cle: snapshot.get(cle) for cle in coordinator_mod._COORDINATOR_SNAPSHOT_KEYS}
        self.assertIn(
            "stress_palier_et0", recopie,
            "la clé meurt dans la recopie du coordinateur : la mémoire repartira vide",
        )
        self.assertEqual(recopie["stress_palier_et0"], 2)
        self.assertEqual(recopie["stress_palier_et0_montee"]["palier"], 3)

    def test_un_palier_a_ZERO_n_est_pas_une_absence(self) -> None:
        """⚠️ 0 est un palier MESURÉ (ET0 sous 3 mm), pas une mémoire vide. Un garde en
        `if palier:` le confondrait avec l'absence et relancerait le clignotement bas."""
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(self._coord(0)._serialized_runtime_state())
        self.assertEqual(relu._runtime_state["stress_palier_et0"], 0,
                         "un palier à zéro est traité comme une absence")


class LAjustementMeteoDesGrainesSurvitAuRedemarrageTests(unittest.TestCase):
    def _coord(self, ajustement: str):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {
            "active_irrigation_session": None,
            "last_irrigation_execution": None,
            "last_auto_irrigation_reason": None,
            "last_auto_irrigation_completed_at": None,
            "auto_irrigation_safety_lock": False,
            "semis_meteo_ajustement": ajustement,
        }
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        return coord

    def test_aller_retour_disque_complet(self) -> None:
        serialise = self._coord("chaud_sec")._serialized_runtime_state()
        self.assertEqual(serialise["semis_meteo_ajustement"], "chaud_sec")

        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(relu._runtime_state["semis_meteo_ajustement"], "chaud_sec")


class LeCumulHumideFongiqueSurvitAuRedemarrageTests(unittest.TestCase):
    ETAT = {
        "status": "wet",
        "source": "sensor",
        "observed_at": "2026-09-18T06:00:00+00:00",
        "wet_minutes": 420.0,
        "dry_minutes": 0.0,
    }

    def test_aller_retour_disque_complet(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {"fungal_wetness": dict(self.ETAT)}
        coord._ensure_irrigation_runtime_bootstrap = lambda: None

        serialise = coord._serialized_runtime_state()
        self.assertEqual(serialise.get("fungal_wetness"), self.ETAT)

        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(relu._runtime_state.get("fungal_wetness"), self.ETAT)


class LeCumulTondeuseSurvitAuRedemarrageTests(unittest.TestCase):
    """Un cumul de la JOURNÉE qui ne survit pas au redémarrage ne vaut rien.

    `_serialized_runtime_state` est une liste blanche clé par clé : une clé absente n'atteint
    jamais le disque. `mower_health` (0.50.0) y manquait — découvert en relisant l'état persisté
    juste après le déploiement de la 0.51.0. Le compteur accumulait en mémoire et repartait de
    zéro à chaque redémarrage, or les redémarrages sont fréquents sur cette installation.
    """

    ETAT = {
        "date": "2026-08-07", "blocked_minutes": 123.4, "mowing_minutes": 130.0,
        "block_count": 3, "last_seen_at": "2026-08-07T13:41:44+00:00", "last_kind": "bloquee",
    }

    def _coord(self):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {
            "active_irrigation_session": None,
            "last_irrigation_execution": None,
            "last_auto_irrigation_reason": None,
            "last_auto_irrigation_completed_at": None,
            "auto_irrigation_safety_lock": False,
            "mower_health": dict(self.ETAT),
        }
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        return coord

    def test_le_cumul_atteint_le_disque(self) -> None:
        serialise = self._coord()._serialized_runtime_state()
        self.assertIn("mower_health", serialise,
                      "le cumul du jour n'est jamais persisté")
        self.assertEqual(serialise["mower_health"]["block_count"], 3)
        self.assertAlmostEqual(serialise["mower_health"]["blocked_minutes"], 123.4, places=1)

    def test_le_cumul_est_relu_au_demarrage(self) -> None:
        """Sérialiser sans relire serait pire qu'absent : invisible."""
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._restore_runtime_state({"mower_health": dict(self.ETAT)})
        self.assertEqual(
            coord._runtime_state.get("mower_health", {}).get("block_count"), 3,
            "le cumul est écrit sur le disque puis ignoré au rechargement",
        )

    def test_aller_retour_complet(self) -> None:
        serialise = self._coord()._serialized_runtime_state()
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(relu._runtime_state["mower_health"], self.ETAT)

    def test_un_etat_absent_ne_casse_pas_la_restauration(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._restore_runtime_state({})
        self.assertIsNone(coord._runtime_state.get("mower_health"))


class AutoDeclarationTonteTests(unittest.TestCase):
    """L'intégration inscrit elle-même la tonte du jour, sans attendre un déclarant externe.

    ⚠️ CE QUE CES TESTS PROTÈGENT. Jusqu'en 0.52.0 la tonte n'était déclarée que par un flow
    Node-RED, à 23:50. Deux défauts vécus :

    - le nœud qui déclarait est resté DÉSACTIVÉ du 30/07 au 06/08/2026 — sept jours de retard
      accumulés sans un seul signal ;
    - le 08/08/2026 la tondeuse a franchi le seuil vers 12 h et l'intégration a affiché
      « 2 jours de retard » jusqu'au soir, alors que le retard PILOTE des décisions
      (`overdue_relaxed_baseline`, decision_mowing.py, relâche les blocages agronomiques).

    Une déclaration est une ÉCRITURE : une fausse tonte inscrite remet le compteur de retard à
    zéro et endort la surveillance. C'est plus grave qu'une tonte non déclarée, d'où les gardes.
    """

    JOUR = date(2026, 8, 6)

    def _coord(self, *, active=True, seuil=None, historique=None):
        brain_mod = importlib.import_module("custom_components.gazon_intelligent.gazon_brain")
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.brain = brain_mod.GazonBrain()
        coord.brain.memory["auto_mowing_declaration_enabled"] = active
        if seuil is not None:
            coord.brain.memory["auto_mowing_declaration_minutes"] = seuil
        if historique:
            coord.brain.history = list(historique)
        coord._current_date = lambda: self.JOUR
        coord._runtime_state = {}
        return coord

    def _ctx(self, minutes, *, hauteur=None, progression=100.0, tache="tache-1", vu_inacheve=True):
        """Par défaut : un travail SUIVI depuis l'inachevé qui vient d'atteindre 100 %.

        ⚠️ C'est la nouvelle unité de la déclaration. Les minutes ne déclenchent plus rien —
        elles ne font que qualifier un travail terminé (plancher anti coupe-de-bordure).
        `vu_inacheve` reproduit la mémoire du cycle précédent, celle qui distingue un travail
        qu'on a vu s'accomplir de la valeur 100 au repos.
        """
        return {
            "mower_mowing_minutes_today": minutes,
            "tondeuse_hauteur_coupe_mm": hauteur,
            "mower_job_progress_pct": progression,
            "mower_job_id": tache,
            "_vu_inacheve": vu_inacheve,
        }

    def _declarer(self, coord, ctx):
        """Pose la mémoire de suivi attendue, puis déclare — comme deux cycles successifs."""
        if ctx.pop("_vu_inacheve", False) and ctx.get("mower_job_id"):
            coord._runtime_state["mower_job_suivi"] = {
                "task_id": str(ctx["mower_job_id"]),
                "vu_inacheve": True,
            }
        return coord._declarer_tonte_du_jour(ctx)

    def _tontes(self, coord):
        return [i for i in coord.brain.history if i.get("type") == "tonte"]

    # ---- PRÉMISSE : le montage mord vraiment -------------------------------------------
    def test_premisse_le_montage_declare_bien_quand_tout_est_reuni(self) -> None:
        """Sans ce test, un montage qui n'atteint jamais le code testé rendrait tous les
        autres verts pour rien — l'erreur commise deux fois sur ce projet."""
        coord = self._coord()
        self.assertEqual(self._tontes(coord), [], "l'historique de départ n'était pas vierge")
        trace = self._declarer(coord, self._ctx(120.0))
        self.assertEqual(trace["mower_auto_declaration_state"], "declaree")
        self.assertEqual(len(self._tontes(coord)), 1)

    # ---- Minuit ------------------------------------------------------------------------
    def test_un_travail_qui_traverse_MINUIT_reste_declarable(self) -> None:
        """⚠️ RELEVÉ PAR LA REVUE DE LA PR #47 — le trou creusé par la 0.62.0.

        `mower_mowing_minutes_today` est un compteur de JOURNÉE : il repart à zéro à minuit.
        Un travail de 4 à 5 h démarré à 20 h — ce que la tondeuse a fait le 31/08/2026 —
        atteint 100 % après minuit avec quelques dizaines de minutes au compteur du jour.

        Le plancher le jugeait « trop court » ET brûlait la complétion. La veille n'avait rien
        déclaré non plus, puisque depuis la 0.62.0 la déclaration attend la fin du travail :
        le travail entier disparaissait, en silence, exactement comme s'il n'avait pas eu lieu.
        """
        coord = self._coord(seuil=90)
        veille = self.JOUR - timedelta(days=1)

        # 20:00 la veille : la tâche NAÎT, compteur du jour quasi vide.
        coord._current_date = lambda: veille
        coord._runtime_state = {}
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 3.0, "mower_job_id": "nuit-1",
             "mower_mowing_minutes_today": 2.0}
        )
        # 22:00 : le travail tourne depuis deux heures, il n'est pas fini.
        en_cours = coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 60.0, "mower_job_id": "nuit-1",
             "mower_mowing_minutes_today": 118.0}
        )
        self.assertEqual(en_cours["mower_job_completion_state"], "en_cours", "prémisse")
        self.assertAlmostEqual(en_cours["mower_job_minutes_total"], 116.0, places=1,
                               msg="les 2 min déjà au compteur à la naissance sont comptées")

        # 00:30 : MÊME tâche, compteur du jour remis à zéro puis reparti à 34 min.
        coord._current_date = lambda: self.JOUR
        ctx = {"mower_mowing_minutes_today": 34.0, "tondeuse_hauteur_coupe_mm": 55,
               "mower_job_progress_pct": 100.0, "mower_job_id": "nuit-1"}
        trace = coord._declarer_tonte_du_jour(ctx)

        self.assertEqual(
            trace["mower_auto_declaration_state"], "declaree",
            "un travail de 2 h 32 réparti sur minuit est jugé trop court : il est perdu",
        )
        # 116 min la veille (118 mesurées − 2 de base) + 34 après minuit.
        self.assertAlmostEqual(trace["mower_job_minutes_total"], 150.0, places=1)
        self.assertEqual(len(self._tontes(coord)), 1)

    def test_le_cumul_du_travail_ne_sauve_PAS_une_coupe_de_bordure(self) -> None:
        """L'autre sens : le plancher doit continuer d'écarter un travail réellement court,
        minuit ou pas. Sans ce test, cumuler reviendrait à supprimer le plancher."""
        coord = self._coord(seuil=90)
        veille = self.JOUR - timedelta(days=1)
        coord._current_date = lambda: veille
        coord._runtime_state = {}
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 40.0, "mower_job_id": "bord-1",
             "mower_mowing_minutes_today": 8.0}
        )
        coord._current_date = lambda: self.JOUR
        trace = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 5.0, "mower_job_progress_pct": 100.0,
             "mower_job_id": "bord-1"}
        )
        self.assertEqual(trace["mower_auto_declaration_state"], "travail_trop_court")
        # 8 min étaient déjà au compteur à la naissance de la tâche : elles ne lui appartiennent
        # pas. Son travail propre vaut donc 5 min, pas 13.
        self.assertAlmostEqual(trace["mower_job_minutes_total"], 5.0, places=1)
        self.assertEqual(self._tontes(coord), [])

    def test_le_cumul_est_borne_au_TRAVAIL_pas_a_la_semaine(self) -> None:
        """Une NOUVELLE tâche repart de zéro : le cumul suit un travail, pas un calendrier.

        ⚠️ Le premier jet de ce test faisait démarrer les deux tâches le MÊME jour — et la
        mutation qui fait fuiter le suivi d'une tâche à l'autre y survivait, parce que le
        report ne se déclenche qu'au changement de date. La fuite réelle est celle-là : le
        travail d'hier reversé dans celui d'aujourd'hui.
        """
        coord = self._coord(seuil=90)
        coord._runtime_state = {}
        veille = self.JOUR - timedelta(days=1)
        coord._current_date = lambda: veille
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 50.0, "mower_job_id": "t-1",
             "mower_mowing_minutes_today": 200.0}
        )
        coord._current_date = lambda: self.JOUR
        suite = coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 10.0, "mower_job_id": "t-2",
             "mower_mowing_minutes_today": 12.0}
        )
        self.assertAlmostEqual(
            suite["mower_job_minutes_total"], 0.0, places=1,
            msg="les 200 min du travail de la veille sont reversées dans le travail du jour",
        )

    def test_une_tache_nee_en_cours_de_journee_N_HERITE_PAS_du_compteur(self) -> None:
        """⚠️ LE DÉFAUT MESURÉ SUR L'INSTALLATION LE 03/09/2026, et c'est MON correctif qui l'a
        créé — la 0.66.0, avec une hypothèse que j'avais écrite noir sur blanc dans le code.

        Chaîne relevée en production :
          02/09 21:00  tâche 345a423c née vers 20:31 → minutes_total = 185,8 dès sa naissance
          03/09 01:00  tâche 67ba4fa7 née vers 23:58 → minutes_total = 328,5 pour 39,4 du jour
          03/09 19:20  même tâche → 337,1 min annoncées pour ~48 min de travail réel

        86 % du cumul appartenait à la veille, dont à un travail DÉJÀ déclaré. Le plancher de
        90 min était donc franchi en permanence : une coupe de bordure de 16 min l'a passé le
        02/09, et la tonte du 03/09 a été déclarée sur une sortie de 8,7 minutes.
        """
        coord = self._coord(seuil=90)
        coord._runtime_state = {}

        # Un vrai travail de la journée : 200 minutes déjà au compteur.
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 100.0, "mower_job_id": "vrai-travail",
             "mower_mowing_minutes_today": 200.0}
        )
        # Puis une COUPE DE BORDURE démarre : nouvelle tâche, même journée.
        bordure = coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 5.0, "mower_job_id": "bordure",
             "mower_mowing_minutes_today": 200.0}
        )
        self.assertAlmostEqual(
            bordure["mower_job_minutes_total"], 0.0, places=1,
            msg="la bordure hérite des minutes du travail précédent",
        )

        # Seize minutes plus tard elle atteint 100 % — le cas exact du 02/09 à 20:29.
        trace = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 216.0, "mower_job_progress_pct": 100.0,
             "mower_job_id": "bordure"}
        )
        self.assertAlmostEqual(
            trace["mower_job_minutes_total"], 16.0, places=1,
            msg="le cumul de la bordure compte encore les minutes du vrai travail",
        )
        # ⚠️ ATTENDU MAINTENU EN 0.82.0, APRÈS L'AVOIR CASSÉ. Le premier jet du correctif
        # qualifiait sur `max(travail, mower_mowing_minutes_today)` : les 216 minutes de lame
        # de la journée franchissaient le plancher et la bordure DÉCLARAIT. Une revue
        # adversariale l'a repris — les 200 minutes appartiennent à une tâche vue à 100 % dès
        # sa naissance, donc jamais vue s'accomplir. La version retenue ne cumule que les
        # travaux TERMINÉS : ces 200 minutes ne sont versées nulle part, et la bordure ne peut
        # plus s'en servir. L'attendu d'origine est donc le bon.
        self.assertEqual(
            trace["mower_auto_declaration_state"], "travail_trop_court",
            "une coupe de bordure de 16 min franchit le plancher de 90",
        )
        self.assertEqual(self._tontes(coord), [],
                         "une coupe de bordure a été inscrite comme une tonte")

    def test_une_bordure_un_jour_SANS_tonte_ne_declare_toujours_rien(self) -> None:
        """⚠️ LA GARDE QUE LE TEST PRÉCÉDENT PORTAIT, ISOLÉE — sans quoi ouvrir le plancher à
        la journée reviendrait à supprimer le plancher.

        Même scénario, une seule différence : la journée n'a PAS 216 minutes de lame, elle en
        a 16. Aucun des deux cumuls n'atteint le plancher, rien n'est inscrit.
        """
        coord = self._coord(seuil=90)
        coord._runtime_state = {}
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 5.0, "mower_job_id": "bordure",
             "mower_mowing_minutes_today": 0.0}
        )
        trace = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 16.0, "mower_job_progress_pct": 100.0,
             "mower_job_id": "bordure"}
        )
        self.assertEqual(trace["mower_auto_declaration_state"], "travail_trop_court")
        self.assertEqual(self._tontes(coord), [],
                         "une coupe de bordure a été inscrite comme une tonte")

    # ---- La JOURNÉE qualifie aussi (0.82.0) ----------------------------------------------
    def test_une_journee_DECOUPEE_en_travaux_courts_est_enfin_declaree(self) -> None:
        """⚠️ LA SOIRÉE DU 08/09/2026, REJOUÉE MINUTE PAR MINUTE.

        La tondeuse est sortie trois fois : 15:29→16:27, 19:47→20:07, 20:44→22:11. Les
        fenêtres d'états donnent 57,8 + 19,4 + 87,2 min ; l'intégration, qui crédite le temps
        de tonte cycle par cycle, a compté 88,1 min pour la dernière — d'où le
        `mower_job_minutes_total` de 88 relevé le lendemain, raté de DEUX minutes sur le
        plancher de 90. Trois travaux distincts, chacun sous le plancher : rien n'a été inscrit
        pour ~165 minutes de lame.

        Le 09/09 au matin : hauteur estimée montée de 5,1 à 5,3 cm, `mowing_is_overdue` à
        `true` avec 3 jours de retard annoncés, sur une pelouse qui venait de recevoir 2 h 45
        de lame. Le retard PILOTE des décisions (`overdue_relaxed_baseline` relâche les
        blocages agronomiques) : se croire en retard ouvre des vannes qui devaient rester
        fermées.
        """
        coord = self._coord(seuil=90)
        coord._runtime_state = {}

        # 15:29 — premier travail, la journée démarre à zéro.
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 4.0, "mower_job_id": "t-1529",
             "mower_mowing_minutes_today": 0.0}
        )
        premier = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 58.0, "mower_job_progress_pct": 100.0,
             "mower_job_id": "t-1529"}
        )
        self.assertEqual(premier["mower_auto_declaration_state"], "travail_trop_court",
                         "prémisse : 58 min de travail terminé ne suffisent pas")
        self.assertAlmostEqual(premier["mower_travail_termine_minutes_jour"], 58.0, places=1)

        # 19:47 — deuxième travail. La journée n'atteint toujours pas le plancher.
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 6.0, "mower_job_id": "t-1947",
             "mower_mowing_minutes_today": 58.0}
        )
        second = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 77.4, "mower_job_progress_pct": 100.0,
             "mower_job_id": "t-1947"}
        )
        self.assertEqual(second["mower_auto_declaration_state"], "travail_trop_court",
                         "77,4 min de travaux terminés : le plancher n'est pas franchi")
        self.assertAlmostEqual(
            second["mower_travail_termine_minutes_jour"], 77.4, places=1,
            msg="les deux travaux terminés ne s'additionnent pas",
        )
        self.assertEqual(self._tontes(coord), [])

        # 20:44 — troisième travail : 87,2 min propres, mais 164,6 dans la journée.
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 2.0, "mower_job_id": "t-2044",
             "mower_mowing_minutes_today": 77.4}
        )
        troisieme = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 164.6, "mower_job_progress_pct": 100.0,
             "mower_job_id": "t-2044", "tondeuse_hauteur_coupe_mm": 45}
        )
        self.assertAlmostEqual(
            troisieme["mower_job_minutes_total"], 87.2, places=1,
            msg="le travail propre du soir n'est toujours que de 87,2 min — il ne triche pas",
        )
        self.assertAlmostEqual(
            troisieme["mower_travail_termine_minutes_jour"], 164.6, places=1,
            msg="les trois travaux terminés du soir ne totalisent pas 164,6 min",
        )
        self.assertEqual(
            troisieme["mower_auto_declaration_state"], "declaree",
            "164 min de travaux terminés et la tonte n'est toujours pas inscrite",
        )
        self.assertEqual(len(self._tontes(coord)), 1)
        self.assertEqual(self._tontes(coord)[0]["date"], self.JOUR.isoformat())

    def test_les_minutes_dun_travail_JAMAIS_TERMINE_ne_qualifient_RIEN(self) -> None:
        """⚠️ LE DÉFAUT QU'UNE REVUE ADVERSARIALE A TROUVÉ DANS MON PREMIER CORRECTIF, le
        09/09/2026 — quatre relecteurs indépendants ont convergé dessus.

        Le premier jet qualifiait sur `max(travail, mower_mowing_minutes_today)`. Or ce
        compteur-là mesure du temps de lame TOUTES TÂCHES CONFONDUES, abouties ou non :

            09:00  la tâche A naît
            11:40  A à 55 %, journée 160 min → puis elle se bloque et rentre. Elle
                   n'atteindra JAMAIS 100 %. 45 % de la pelouse reste haute.
            18:00  coupe de bordure B
            18:12  B à 100 %, journée 172 → max(12, 172) = 172 ≥ 90 → **DÉCLARÉE**

        Une bordure de douze minutes inscrivait la tonte du jour avec les minutes d'un travail
        abandonné : hauteur ré-ancrée sur la lame, retard remis à zéro, surveillance endormie.
        C'était le défaut du 30/08/2026 revenu par une autre porte.
        """
        coord = self._coord(seuil=90)
        coord._runtime_state = {}

        # 09:00 — le vrai travail démarre.
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 3.0, "mower_job_id": "A",
             "mower_mowing_minutes_today": 0.0}
        )
        # 11:40 — 160 min de lame, mais A n'est qu'à 55 %. Elle rentrera sans finir.
        en_cours = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 160.0, "mower_job_progress_pct": 55.0,
             "mower_job_id": "A"}
        )
        self.assertEqual(en_cours["mower_auto_declaration_state"], "travail_en_cours",
                         "prémisse : le vrai travail n'est pas terminé")

        # 18:00 — une coupe de bordure démarre, la journée porte déjà 160 min.
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 4.0, "mower_job_id": "B",
             "mower_mowing_minutes_today": 160.0}
        )
        # 18:12 — elle atteint 100 % : douze minutes de travail propre.
        trace = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 172.0, "mower_job_progress_pct": 100.0,
             "mower_job_id": "B", "tondeuse_hauteur_coupe_mm": 45}
        )
        self.assertAlmostEqual(trace["mower_job_minutes_total"], 12.0, places=1,
                               msg="prémisse : la bordure vaut bien 12 min propres")
        self.assertAlmostEqual(
            trace["mower_travail_termine_minutes_jour"], 12.0, places=1,
            msg="les 160 min du travail ABANDONNÉ ont été versées au cumul des travaux terminés",
        )
        self.assertEqual(
            trace["mower_auto_declaration_state"], "travail_trop_court",
            "une bordure de 12 min a déclaré la tonte d'un travail resté inachevé",
        )
        self.assertEqual(self._tontes(coord), [],
                         "une pelouse tondue à 55 % a été enregistrée comme tondue")

    def test_une_meme_complétion_ne_verse_ses_minutes_qu_UNE_fois(self) -> None:
        """Le cumul est une addition : une complétion re-offerte le doublerait.

        La progression reste à 100 % pendant deux à trois jours entre deux travaux. Sans
        l'extinction de la fin de travail (0.61.0), la même tâche re-verserait ses minutes à
        chaque cycle — et deux cycles suffiraient à franchir n'importe quel plancher.
        """
        coord = self._coord(seuil=90)
        coord._runtime_state = {}
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 10.0, "mower_job_id": "t-1",
             "mower_mowing_minutes_today": 0.0}
        )
        ctx = {"mower_mowing_minutes_today": 60.0, "mower_job_progress_pct": 100.0,
               "mower_job_id": "t-1"}
        premier = coord._declarer_tonte_du_jour(dict(ctx))
        self.assertAlmostEqual(premier["mower_travail_termine_minutes_jour"], 60.0, places=1)

        # Cycle suivant, MÊME tâche toujours à 100 % : ce n'est plus un événement.
        second = coord._declarer_tonte_du_jour(dict(ctx))
        self.assertEqual(second["mower_auto_declaration_state"], "travail_au_repos")
        self.assertAlmostEqual(
            second["mower_travail_termine_minutes_jour"], 60.0, places=1,
            msg="la complétion a été recomptée : le cumul a bougé hors de la branche terminée",
        )
        self.assertAlmostEqual(
            float(coord._runtime_state["mower_travaux_termines"]["minutes"]), 60.0, places=1,
            msg="60 min versées deux fois : deux cycles suffiraient à franchir le plancher",
        )

    def test_le_cumul_annonce_ZERO_tant_que_rien_n_est_termine(self) -> None:
        """⚠️ VÉRIFIÉ SUR L'INSTALLATION, une heure après la mise en service de la 0.82.0.

        L'attribut n'apparaissait NULLE PART sur le capteur de tonte. La clé était pourtant dans
        les trois listes blanches et les tests de câblage étaient verts : `_attrs_from_data`
        (entity_base.py) **filtre les valeurs `None`**, et aucun travail ne s'était terminé
        depuis le redémarrage. Publier `None` par défaut, c'est ne rien publier du tout — la
        variante « entité éteinte » du défaut n°1 du projet.
        """
        coord = self._coord()
        coord._runtime_state = {}
        self.assertEqual(coord._travail_termine_du_jour(), 0.0,
                         "sans rien de terminé, l'attribut disparaît du capteur")
        trace = coord._declarer_tonte_du_jour(self._ctx(10.0, progression=20.0))
        self.assertEqual(trace["mower_travail_termine_minutes_jour"], 0.0,
                         "la trace d'un travail en cours n'annonce aucun cumul")

    def test_le_cumul_de_la_VEILLE_ne_deborde_pas_sur_aujourd_hui(self) -> None:
        coord = self._coord()
        coord._runtime_state = {
            "mower_travaux_termines": {"date": (self.JOUR - timedelta(days=1)).isoformat(),
                                       "minutes": 150.0}
        }
        self.assertEqual(coord._travail_termine_du_jour(), 0.0)

    def test_le_cumul_des_travaux_termines_est_persiste_des_DEUX_cotes(self) -> None:
        """⚠️ LE PIÈGE DU PROJET, quatrième fois sur cette famille de clés.

        Sauvegardé sans être restauré, le cumul serait écrit sur le disque puis ignoré au
        rechargement — pire qu'absent, car invisible. Non persisté du tout, un redémarrage en
        milieu de journée oublierait les travaux déjà terminés et une soirée découpée
        redeviendrait indéclarable : exactement le défaut que la 0.82.0 corrige, sur une
        installation qui redémarre souvent.
        """
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        sauvegarde = source.split("def _serialized_runtime_state")[1].split("def ")[0]
        restauration = source.split("def _restore_runtime_state")[1].split("\n    def ")[0]
        self.assertIn("mower_travaux_termines", sauvegarde, "le cumul n'est pas SAUVEGARDÉ")
        self.assertIn("mower_travaux_termines", restauration, "le cumul n'est pas RESTAURÉ")

    def test_le_cumul_des_travaux_termines_repart_a_zero_le_lendemain(self) -> None:
        """Sinon il grossirait sans fin et le plancher serait franchi en permanence — le
        mécanisme exact du défaut du 03/09/2026, à l'échelle de la semaine."""
        coord = self._coord(seuil=90)
        coord._runtime_state = {}
        veille = self.JOUR - timedelta(days=1)
        coord._current_date = lambda: veille
        self.assertAlmostEqual(coord._cumuler_travail_termine_du_jour(80.0), 80.0, places=1)
        coord._current_date = lambda: self.JOUR
        self.assertAlmostEqual(
            coord._cumuler_travail_termine_du_jour(20.0), 20.0, places=1,
            msg="les 80 min de la veille sont reversées dans la journée du lendemain",
        )

    def test_des_minutes_SANS_travail_termine_ne_DECLENCHENT_rien(self) -> None:
        """⚠️ LA GARDE DE LA 0.62.0, QUI DOIT SURVIVRE À L'OUVERTURE.

        Le 30/08/2026 la tonte a été déclarée à 14:32 avec 102,8 min tondues et le travail à
        **49 %** : hauteur remise à la lame, retard remis à zéro, prochaine tonte repoussée de
        trois jours — pendant que la moitié de la pelouse restait haute.

        Élargir le plancher à la journée ne doit RIEN changer à cela : sans travail terminé,
        le compteur peut afficher cinq heures de lame, il ne se passe rien — et rien n'est
        versé au cumul.
        """
        coord = self._coord(seuil=90)
        trace = self._declarer(coord, self._ctx(300.0, progression=49.0))
        self.assertEqual(trace["mower_auto_declaration_state"], "travail_en_cours")
        self.assertEqual(trace["mower_travail_termine_minutes_jour"], 0.0,
                         "un travail en cours a versé ses minutes au cumul des terminés")
        self.assertEqual(self._tontes(coord), [],
                         "300 min dans la journée ont déclaré une tonte sans travail terminé")

    def test_la_journee_ne_peut_RIEN_emprunter_a_la_veille(self) -> None:
        """⚠️ LE DÉFAUT DU 03/09/2026 NE DOIT PAS RENAÎTRE PAR L'AUTRE PORTE.

        Ce jour-là le cumul du travail annonçait 337 min pour ~48 min de travail réel, dont
        86 % appartenaient à un travail de la veille DÉJÀ déclaré : la tonte fut inscrite sur
        une sortie de 8,7 minutes. Le cumul des travaux terminés est structurellement incapable
        de cela — il est indexé sur la date, et chaque travail n'y verse que ses minutes
        propres, base du jour retranchée. Ce test le prouve au lieu de l'affirmer.
        """
        coord = self._coord(seuil=90)
        coord._runtime_state = {}
        veille = self.JOUR - timedelta(days=1)

        # 23:58 la veille : la tâche naît alors que la journée compte déjà 289 min de lame.
        coord._current_date = lambda: veille
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 3.0, "mower_job_id": "nuit-03-09",
             "mower_mowing_minutes_today": 289.0}
        )
        # Lendemain 19:20 : 48 min de lame dans la journée, le travail atteint 100 %.
        coord._current_date = lambda: self.JOUR
        trace = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 48.0, "mower_job_progress_pct": 100.0,
             "mower_job_id": "nuit-03-09"}
        )
        self.assertEqual(
            trace["mower_auto_declaration_state"], "travail_trop_court",
            "les 289 min de la veille ont été rejouées dans la journée du lendemain",
        )
        self.assertEqual(self._tontes(coord), [])

    def test_le_journal_NOMME_le_travail_declare(self) -> None:
        """⚠️ « Déclarer n'est pas câbler », version journal. La ligne lisait
        `suivi.get("mower_job_id")` — une clé que `_suivre_travail_tondeuse` n'a JAMAIS
        produite ; elle s'appelle `mower_job_followed_id`. Depuis la 0.61.0 — commit 0d8c4e8,
        « la tonte se déclare sur le travail terminé, plus sur une durée » — le journal écrivait
        donc « travail ? » à chaque déclaration, exactement au moment où l'identifiant sert.
        """
        coord = self._coord(seuil=90)
        with self.assertLogs("custom_components.gazon_intelligent.coordinator",
                             level="INFO") as journal:
            self._declarer(coord, self._ctx(126.6, tache="tache-nommee"))
        ligne = "\n".join(journal.output)
        self.assertIn("tache-nommee", ligne, "le journal n'identifie pas le travail déclaré")
        self.assertNotIn("travail ?", ligne)

    def test_le_travail_PROPRE_reste_declarable_apres_une_bordure(self) -> None:
        """L'autre sens, et c'est lui qui coûte : sans ce test, retrancher la base pourrait
        rendre indéclarable un vrai travail qui suit une bordure dans la même journée."""
        coord = self._coord(seuil=90)
        coord._runtime_state = {}
        # Une bordure de 12 min, puis le vrai travail de la journée.
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 100.0, "mower_job_id": "bordure",
             "mower_mowing_minutes_today": 12.0}
        )
        coord._suivre_travail_tondeuse(
            {"mower_job_progress_pct": 2.0, "mower_job_id": "vrai",
             "mower_mowing_minutes_today": 12.0}
        )
        trace = coord._declarer_tonte_du_jour(
            {"mower_mowing_minutes_today": 145.0, "mower_job_progress_pct": 100.0,
             "mower_job_id": "vrai", "tondeuse_hauteur_coupe_mm": 55}
        )
        self.assertAlmostEqual(trace["mower_job_minutes_total"], 133.0, places=1)
        self.assertEqual(trace["mower_auto_declaration_state"], "declaree",
                         "un vrai travail de 133 min n'est plus déclaré")
        self.assertEqual(len(self._tontes(coord)), 1)

    # ---- Le seuil ----------------------------------------------------------------------
    def test_le_seuil_franchi_inscrit_la_tonte_du_jour(self) -> None:
        """Le 08/08/2026 : 126,6 min tondues, largement au-dessus des 90 min."""
        coord = self._coord()
        self._declarer(coord, self._ctx(126.6))
        self.assertEqual(self._tontes(coord)[0]["date"], self.JOUR.isoformat())

    def test_sous_le_seuil_rien_n_est_inscrit(self) -> None:
        """Une sortie avortée (le 08/08 à 13:59 : 3 secondes) n'est pas une tonte."""
        coord = self._coord()
        trace = self._declarer(coord, self._ctx(12.0))
        # Le plancher ne DÉCLENCHE plus, il QUALIFIE : un travail terminé en 12 min n'est pas
        # une tonte, c'est une coupe de bordure ou une sortie avortée.
        self.assertEqual(trace["mower_auto_declaration_state"], "travail_trop_court")
        self.assertEqual(self._tontes(coord), [])

    def test_la_borne_exacte_du_seuil_declare(self) -> None:
        coord = self._coord(seuil=90)
        self.assertEqual(
            self._declarer(coord, self._ctx(90.0))["mower_auto_declaration_state"],
            "declaree",
        )

    def test_juste_en_dessous_de_la_borne_ne_declare_pas(self) -> None:
        coord = self._coord(seuil=90)
        self.assertEqual(
            self._declarer(coord, self._ctx(89.9))["mower_auto_declaration_state"],
            "travail_trop_court",
        )

    def test_le_seuil_est_reellement_configurable(self) -> None:
        coord = self._coord(seuil=30)
        trace = self._declarer(coord, self._ctx(45.0))
        self.assertEqual(trace["mower_auto_declaration_state"], "declaree")
        self.assertEqual(trace["mower_auto_declaration_threshold_minutes"], 30)

    # ---- Le TRAVAIL, pas la durée --------------------------------------------------------
    def test_un_travail_a_100_jamais_vu_inacheve_ne_declare_rien(self) -> None:
        """⚠️ LE PIÈGE QUI AURAIT TOUT CASSÉ : 100 % est l'état de REPOS, pas un événement.

        Relevé sur huit jours de `progression_de_la_tonte` : la valeur reste à 100 entre deux
        travaux — 51 h après celui du 25/08/2026, 62 h après celui du 27/08. Un test `== 100`
        serait donc vrai la quasi-totalité du temps, et déclarerait une tonte chaque jour.
        """
        coord = self._coord()
        trace = self._declarer(coord, self._ctx(600.0, vu_inacheve=False))
        self.assertEqual(trace["mower_auto_declaration_state"], "travail_au_repos")
        self.assertEqual(self._tontes(coord), [], "une tonte a été inscrite sur l'état de repos")

    def test_une_tache_deja_suivie_mais_jamais_vue_inachevee_reste_au_repos(self) -> None:
        """Second chemin du même piège, et celui que le premier test ne traversait pas.

        Une tâche déjà mémorisée, à 100, dont on n'a JAMAIS vu la progression sous 100 :
        c'est le repos qui dure (51 h après le travail du 25/08, 62 h après celui du 27/08).
        Sans ce test, déclarer sur la seule valeur 100 passait le banc de mutations.
        """
        coord = self._coord()
        coord._runtime_state["mower_job_suivi"] = {"task_id": "tache-1", "vu_inacheve": False}
        trace = coord._declarer_tonte_du_jour(
            self._ctx(600.0) | {"_vu_inacheve": None}
        )
        self.assertEqual(trace["mower_auto_declaration_state"], "travail_au_repos")
        self.assertEqual(self._tontes(coord), [])

    def test_un_travail_en_cours_ne_declare_rien_meme_avec_beaucoup_de_minutes(self) -> None:
        """Le 30/08/2026 : déclarée à 14:32 avec 102,8 min tondues et le travail à 49 %.

        Hauteur estimée remise à 5,5 cm, retard remis à 0, prochaine tonte repoussée de trois
        jours — pendant que la moitié de la pelouse restait haute et que la tondeuse tondait
        encore. C'est ce cas précis que la nouvelle règle refuse.
        """
        coord = self._coord()
        trace = self._declarer(coord, self._ctx(102.8, progression=49.0))
        self.assertEqual(trace["mower_auto_declaration_state"], "travail_en_cours")
        self.assertEqual(self._tontes(coord), [])

    def test_un_travail_inacheve_a_quai_est_en_pause_sans_etre_declare(self) -> None:
        """Le cloud peut garder une tâche à 0 % après le retour de la tondeuse à sa base.

        Ce n'est ni une tonte terminée ni une machine encore en train de travailler. L'état
        publié doit décrire la pause à quai sans consommer la tâche : elle peut encore reprendre.
        """
        coord = self._coord()
        pause = coord._declarer_tonte_du_jour(
            self._ctx(2.1, progression=0.0, tache="travail-pause")
            | {"_vu_inacheve": None, "mower_is_docked": True}
        )
        self.assertEqual(pause["mower_job_completion_state"], "en_pause")
        self.assertEqual(pause["mower_auto_declaration_state"], "travail_en_pause")
        self.assertEqual(self._tontes(coord), [])

        reprise = coord._declarer_tonte_du_jour(
            self._ctx(45.0, progression=35.0, tache="travail-pause")
            | {"_vu_inacheve": None, "mower_is_docked": False}
        )
        self.assertEqual(reprise["mower_job_completion_state"], "en_cours")
        self.assertEqual(reprise["mower_auto_declaration_state"], "travail_en_cours")

        fin = coord._declarer_tonte_du_jour(
            self._ctx(120.0, progression=100.0, tache="travail-pause")
            | {"_vu_inacheve": None, "mower_is_docked": True}
        )
        self.assertEqual(fin["mower_auto_declaration_state"], "declaree")
        self.assertEqual(len(self._tontes(coord)), 1)

    def test_un_ancien_travail_a_quai_est_au_repos_mais_reste_recuperable(self) -> None:
        coord = self._coord()
        maintenant = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
        coord._current_datetime = lambda: maintenant

        pause = coord._declarer_tonte_du_jour(
            self._ctx(25.0, progression=18.0, tache="travail-ancien")
            | {"_vu_inacheve": None, "mower_is_docked": True}
        )
        self.assertEqual(pause["mower_job_completion_state"], "en_pause")
        pause_depuis = pause["mower_job_paused_since"]

        # Le délai ne repart pas à zéro après un redémarrage de Home Assistant.
        persiste = coord._serialized_runtime_state()
        relu = self._coord()
        relu._restore_runtime_state(persiste)
        coord = relu
        maintenant += timedelta(minutes=60)
        coord._current_datetime = lambda: maintenant
        ancien = coord._declarer_tonte_du_jour(
            self._ctx(25.0, progression=18.0, tache="travail-ancien")
            | {"_vu_inacheve": None, "mower_is_docked": True}
        )
        self.assertEqual(ancien["mower_job_completion_state"], "repos")
        self.assertEqual(ancien["mower_auto_declaration_state"], "travail_au_repos")
        self.assertTrue(ancien["mower_job_resume_possible"])
        self.assertEqual(ancien["mower_job_paused_since"], pause_depuis)
        self.assertEqual(self._tontes(coord), [])

        maintenant += timedelta(hours=5)
        reprise = coord._declarer_tonte_du_jour(
            self._ctx(40.0, progression=32.0, tache="travail-ancien")
            | {"_vu_inacheve": None, "mower_is_docked": False}
        )
        self.assertEqual(reprise["mower_job_completion_state"], "en_cours")
        self.assertFalse(reprise["mower_job_resume_possible"])
        self.assertIsNone(reprise["mower_job_paused_since"])

    def test_un_signal_d_activite_interdit_de_ranger_le_travail(self) -> None:
        maintenant = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)
        for activite in ({"mower_is_mowing": True}, {"mower_pass_in_progress": True}):
            with self.subTest(activite=activite):
                coord = self._coord()
                coord._current_datetime = lambda: maintenant
                coord._runtime_state["mower_job_suivi"] = {
                    "task_id": "travail-actif",
                    "vu_inacheve": True,
                    "pause_a_quai_depuis": (maintenant - timedelta(hours=5)).isoformat(),
                }
                trace = coord._declarer_tonte_du_jour(
                    self._ctx(40.0, progression=32.0, tache="travail-actif")
                    | {"_vu_inacheve": None, "mower_is_docked": True}
                    | activite
                )
                self.assertEqual(trace["mower_job_completion_state"], "en_cours")
                self.assertFalse(trace["mower_job_resume_possible"])
                self.assertIsNone(trace["mower_job_paused_since"])

    def test_le_passage_a_100_dun_travail_suivi_declare(self) -> None:
        coord = self._coord()
        # ⚠️ PRÉMISSE CORRIGÉE le 03/09/2026 : la tâche naît AU DÉBUT du travail, compteur du
        # jour proche de zéro. L'ancienne version la faisait naître à 120 min déjà au compteur —
        # un cas qui n'arrive que si on découvre un travail en cours de route, et qui masquait
        # justement le défaut : la tâche héritait de ces 120 minutes sans les avoir produites.
        naissance = coord._declarer_tonte_du_jour(
            self._ctx(0.5, progression=4.0) | {"_vu_inacheve": None}
        )
        self.assertEqual(naissance["mower_auto_declaration_state"], "travail_en_cours")
        # Cycle 2 : le travail avance.
        en_cours = coord._declarer_tonte_du_jour(
            self._ctx(120.0, progression=87.0) | {"_vu_inacheve": None}
        )
        self.assertEqual(en_cours["mower_auto_declaration_state"], "travail_en_cours")
        self.assertEqual(self._tontes(coord), [])
        # Cycle 3 : la même tâche atteint 100 — c'est le PASSAGE qui déclare.
        fin = coord._declarer_tonte_du_jour(self._ctx(150.0, progression=100.0) | {"_vu_inacheve": None})
        self.assertEqual(fin["mower_auto_declaration_state"], "declaree")
        self.assertEqual(len(self._tontes(coord)), 1)

    def test_une_progression_absente_ne_vaut_pas_travail_inacheve(self) -> None:
        """`None` est une absence : tondeuse injoignable, entité absente, ou autre langue."""
        coord = self._coord()
        trace = self._declarer(coord, self._ctx(600.0, progression=None))
        self.assertEqual(trace["mower_auto_declaration_state"], "sans_mesure")
        self.assertEqual(self._tontes(coord), [])

    def test_le_suivi_du_travail_est_persiste_des_deux_cotes(self) -> None:
        """Un travail dure 4 à 5 h et traverse les recharges ET les redémarrages.

        Non persisté, le suivi repartirait vide au milieu : le passage à 100 serait alors lu
        comme un état de repos, et plus AUCUNE tonte ne serait déclarée. Un silence total,
        indiscernable d'un capteur muet.
        """
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        sauvegarde = source.split("def _serialized_runtime_state")[1].split("def ")[0]
        restauration = source.split("def _restore_runtime_state")[1].split("\n    def ")[0]
        self.assertIn("mower_job_suivi", sauvegarde, "le suivi n'est pas SAUVEGARDÉ")
        self.assertIn("mower_job_suivi", restauration, "le suivi n'est pas RESTAURÉ")

    def test_une_fin_de_travail_ne_vaut_qu_une_fois(self) -> None:
        """⚠️ DÉFAUT DE LA 0.61.0, trouvé le 01/09/2026 en auditant le passage de minuit.

        La progression reste à 100 % pendant 2 à 3 jours entre deux travaux. La fin de travail
        était donc RE-OFFERTE à chaque cycle : le lendemain, `mower_job_completion_state` valait
        encore `termine` et le seul rempart restant était le plancher de minutes. Dès 90 min
        tondues, la journée aurait été déclarée sur une complétion de LA VEILLE.
        """
        coord = self._coord()
        ctx = self._ctx(120.0) | {"_vu_inacheve": None}
        coord._runtime_state["mower_job_suivi"] = {"task_id": "tache-1", "vu_inacheve": True}

        premiere = coord._declarer_tonte_du_jour(dict(ctx))
        self.assertEqual(premiere["mower_auto_declaration_state"], "declaree")
        self.assertEqual(len(self._tontes(coord)), 1)

        # Cycle suivant, MÊME tâche toujours à 100 % : ce n'est plus un événement.
        seconde = coord._declarer_tonte_du_jour(dict(ctx))
        self.assertEqual(seconde["mower_job_completion_state"], "repos",
                         "la fin de travail est toujours offerte au cycle suivant")

    def test_une_fin_ecartee_comme_trop_courte_ne_revient_pas_le_lendemain(self) -> None:
        """Une fin de travail appartient au jour où elle a eu lieu.

        Écartée parce que trop courte, elle ne doit pas ressurgir le lendemain quand le
        compteur de minutes est reparti de zéro puis a franchi le plancher.
        """
        coord = self._coord()
        coord._runtime_state["mower_job_suivi"] = {"task_id": "tache-1", "vu_inacheve": True}

        court = coord._declarer_tonte_du_jour(self._ctx(12.0) | {"_vu_inacheve": None})
        self.assertEqual(court["mower_auto_declaration_state"], "travail_trop_court")
        self.assertEqual(self._tontes(coord), [])

        # Lendemain simulé : minutes repassées au-dessus du plancher, même tâche à 100 %.
        lendemain = coord._declarer_tonte_du_jour(self._ctx(200.0) | {"_vu_inacheve": None})
        self.assertEqual(lendemain["mower_auto_declaration_state"], "travail_au_repos")
        self.assertEqual(self._tontes(coord), [],
                         "une tonte a été inscrite sur une complétion de la veille")

    # ---- Les gardes contre une FAUSSE déclaration ----------------------------------------
    def test_l_interrupteur_coupe_interdit_toute_ecriture(self) -> None:
        coord = self._coord(active=False)
        trace = self._declarer(coord, self._ctx(600.0))
        self.assertEqual(trace["mower_auto_declaration_state"], "desactivee")
        self.assertEqual(self._tontes(coord), [])

    def test_une_tondeuse_injoignable_n_inscrit_RIEN(self) -> None:
        """RÈGLE DE LA MAISON : `None` est une absence de mesure, PAS zéro minute — et surtout
        pas une raison d'écrire quoi que ce soit."""
        coord = self._coord()
        trace = self._declarer(coord, self._ctx(None))
        self.assertEqual(trace["mower_auto_declaration_state"], "sans_mesure")
        self.assertEqual(self._tontes(coord), [])

    def test_un_booleen_n_est_pas_une_duree(self) -> None:
        """`True` vaut 1 en Python : sans garde explicite il passerait pour une mesure."""
        coord = self._coord(seuil=1)
        trace = self._declarer(coord, self._ctx(True))
        self.assertEqual(trace["mower_auto_declaration_state"], "sans_mesure")
        self.assertEqual(self._tontes(coord), [])

    def test_une_journee_deja_declaree_ne_l_est_pas_deux_fois(self) -> None:
        """Le filet Node-RED de 23:50 peut avoir devancé l'intégration."""
        coord = self._coord(historique=[{"type": "tonte", "date": self.JOUR.isoformat()}])
        trace = self._declarer(coord, self._ctx(200.0))
        self.assertEqual(trace["mower_auto_declaration_state"], "deja_declaree")
        self.assertEqual(len(self._tontes(coord)), 1)

    def test_dix_cycles_au_dessus_du_seuil_n_ecrivent_qu_une_ligne(self) -> None:
        """Le cycle tourne toutes les 2 min : sans idempotence, ~300 lignes par après-midi."""
        coord = self._coord()
        for _ in range(10):
            self._declarer(coord, self._ctx(126.6))
        self.assertEqual(len(self._tontes(coord)), 1)

    def test_une_tonte_de_la_veille_n_empeche_pas_celle_du_jour(self) -> None:
        veille = (self.JOUR - timedelta(days=1)).isoformat()
        coord = self._coord(historique=[{"type": "tonte", "date": veille}])
        self._declarer(coord, self._ctx(126.6))
        self.assertEqual(
            sorted(i["date"] for i in self._tontes(coord)),
            [veille, self.JOUR.isoformat()],
        )

    # ---- Les deux horloges ---------------------------------------------------------------
    def test_la_date_inscrite_est_celle_du_compteur_pas_l_horloge_systeme(self) -> None:
        """⚠️ Le cumul est indexé sur `_current_date()`, mais `record_mowing` retombe sinon sur
        `dt_util.now().date()`. Deux horloges pour un même fait = une tonte déclarée le mauvais
        jour. La date est passée EXPLICITEMENT."""
        coord = self._coord()
        self._declarer(coord, self._ctx(126.6))
        self.assertEqual(self._tontes(coord)[0]["date"], "2026-08-06")
        self.assertNotEqual(
            self._tontes(coord)[0]["date"],
            date.today().isoformat(),
            msg="le montage doit distinguer la date du compteur de la date réelle",
        )

    # ---- Ce qui est inscrit ---------------------------------------------------------------
    def test_la_hauteur_de_coupe_du_moment_est_conservee(self) -> None:
        coord = self._coord()
        self._declarer(coord, self._ctx(126.6, hauteur=60.0))
        self.assertAlmostEqual(self._tontes(coord)[0]["hauteur_coupe_mm"], 60.0)

    # ---- Robustesse -----------------------------------------------------------------------
    def test_une_declaration_ratee_ne_casse_jamais_un_cycle(self) -> None:
        """Un coordinator dégradé rend une trace INERTE mais COMPLÈTE.

        ⚠️ Le jeu de clés est vérifié en entier, à l'égalité : une clé publiée seulement sur le
        chemin nominal ferait un attribut intermittent sur le capteur, et un consommateur qui
        la lit tomberait un cycle sur deux sans que rien ne le dise.
        """
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        trace = coord._declarer_tonte_du_jour({"mower_mowing_minutes_today": 120.0})
        self.assertEqual(set(trace), {
            "mower_auto_declaration_state",
            "mower_auto_declaration_threshold_minutes",
            "mower_auto_declared_today",
            "mower_travail_termine_minutes_jour",
        })
        self.assertIsNone(trace["mower_travail_termine_minutes_jour"],
                          "une trace inerte annonce un cumul qu'elle n'a pas calculé")


class RecordMowingIdempotentTests(unittest.TestCase):
    """`_append_history` ne déduplique pas : deux déclarations le même jour faisaient deux lignes.

    Sans gravité pour `derniere_tonte` (qui prend la plus récente), mais PAS neutre pour
    `_count_tonte_events_since_latest_phase_start` (guidance.py), qui COMPTE les entrées pour
    décider de la transition de sursemis : un doublon y valait une tonte qui n'a jamais eu lieu.
    """

    def _brain(self):
        brain_mod = importlib.import_module("custom_components.gazon_intelligent.gazon_brain")
        return brain_mod.GazonBrain()

    def test_deux_declarations_le_meme_jour_ne_font_qu_une_entree(self) -> None:
        brain = self._brain()
        brain.record_mowing(date(2026, 8, 6))
        brain.record_mowing(date(2026, 8, 6))
        self.assertEqual(len([i for i in brain.history if i.get("type") == "tonte"]), 1)

    def test_la_derniere_ecriture_precise_la_hauteur(self) -> None:
        """L'auto-déclaration peut inscrire sans hauteur, le filet de 23:50 la préciser après."""
        brain = self._brain()
        brain.record_mowing(date(2026, 8, 6))
        brain.record_mowing(date(2026, 8, 6), hauteur_coupe_mm=55.0)
        tontes = [i for i in brain.history if i.get("type") == "tonte"]
        self.assertEqual(len(tontes), 1)
        self.assertAlmostEqual(tontes[0]["hauteur_coupe_mm"], 55.0)

    def test_une_hauteur_deja_connue_n_est_pas_effacee_par_un_appel_nu(self) -> None:
        brain = self._brain()
        brain.record_mowing(date(2026, 8, 6), hauteur_coupe_mm=55.0)
        brain.record_mowing(date(2026, 8, 6))
        tontes = [i for i in brain.history if i.get("type") == "tonte"]
        self.assertAlmostEqual(tontes[0]["hauteur_coupe_mm"], 55.0)

    def test_deux_jours_distincts_font_bien_deux_entrees(self) -> None:
        brain = self._brain()
        brain.record_mowing(date(2026, 8, 5))
        brain.record_mowing(date(2026, 8, 6))
        self.assertEqual(len([i for i in brain.history if i.get("type") == "tonte"]), 2)

    def test_la_dedup_ne_touche_pas_les_autres_types(self) -> None:
        brain = self._brain()
        brain.history = [{"type": "arrosage", "date": "2026-08-06", "total_mm": 5.7}]
        brain.record_mowing(date(2026, 8, 6))
        self.assertEqual(len(brain.history), 2)


class AutoDeclarationCablageTests(unittest.TestCase):
    """⚠️ LE PIÈGE DU PROJET : une clé qui n'est pas dans TOUTES les listes blanches disparaît
    en silence. `mower_health` (0.50.0) n'atteignait jamais le disque faute d'y figurer.

    Et un correctif branché nulle part est un correctif qui n'existe pas : la déclaration doit
    être APPELÉE dans le cycle, pas seulement définie.
    """

    CLES = (
        "mower_auto_declaration_state",
        "mower_auto_declaration_threshold_minutes",
        "mower_auto_declared_today",
        # Ajoutées en 0.61.0 : sans elles dans CETTE liste, retirer une clé du capteur ne
        # faisait tomber aucun test — le trou que le banc de mutations a trouvé.
        "mower_job_completion_state",
        "mower_job_followed_id",
        "mower_job_seen_incomplete",
        # Ajoutée en 0.66.0 : le cumul du travail à travers minuit. Le banc a montré que la
        # retirer de `_MOWER_CONTEXT_KEYS` ne faisait tomber AUCUN test — le piège du projet,
        # pour la deuxième fois sur cette même famille de clés.
        "mower_job_minutes_total",
        "mower_job_resume_possible",
        "mower_job_paused_since",
        # Ajoutée en 0.82.0 : les minutes des travaux TERMINÉS du jour, c'est-à-dire la
        # grandeur réellement comparée au plancher. Troisième clé de cette famille à traverser
        # ce banc — les deux précédentes y sont entrées après avoir manqué une liste.
        "mower_travail_termine_minutes_jour",
    )

    def test_les_cles_traversent_la_liste_blanche_du_coordinator(self) -> None:
        for cle in self.CLES:
            with self.subTest(cle=cle):
                self.assertIn(cle, coordinator_mod._COORDINATOR_SNAPSHOT_KEYS)

    def test_les_cles_traversent_REELLEMENT_toute_la_chaine(self) -> None:
        """⚠️ LE TEST QUI MANQUAIT, ET LE DÉFAUT QU'IL A ATTRAPÉ.

        Les trois clés s'appelaient d'abord `mowing_auto_*`. Elles étaient bien déclarées dans
        `_COORDINATOR_SNAPSHOT_KEYS` ET dans la liste d'attributs du capteur — et elles
        n'arrivaient JAMAIS : deux filtres successifs ne recopient du contexte tondeuse que les
        préfixes `tondeuse_` et `mower_` (decision_mowing.py et decision.py). Tout ce qui
        commence par `mowing_` y meurt en silence.

        Vérifier qu'une clé est DÉCLARÉE quelque part ne prouve rien. Ce test la suit du
        contexte tondeuse jusqu'au snapshot publié.
        """
        decision = importlib.import_module("custom_components.gazon_intelligent.decision")
        contexte = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-08-06"}],
            today=date(2026, 8, 6),
            hour_of_day=13,
            temperature=22.0,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
        )
        # ⚠️ Les clés viennent de la SORTIE RÉELLE du coordinator, jamais recopiées à la main :
        # un test qui se donne lui-même les noms survivrait à un renommage du code, donc ne
        # testerait plus rien.
        brain_mod = importlib.import_module("custom_components.gazon_intelligent.gazon_brain")
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.brain = brain_mod.GazonBrain()
        coord.brain.memory["auto_mowing_declaration_enabled"] = True
        coord._current_date = lambda: date(2026, 8, 6)
        coord._runtime_state = {"mower_job_suivi": {"task_id": "t1", "vu_inacheve": True}}
        trace = coord._declarer_tonte_du_jour({
            "mower_mowing_minutes_today": 126.6,
            "mower_job_progress_pct": 100.0,
            "mower_job_id": "t1",
        })
        self.assertEqual(trace["mower_auto_declaration_state"], "declaree",
                         msg="prémisse : la trace exercée doit être celle d'une déclaration")

        # Un travail terminé publie logiquement un horodatage de pause nul, ensuite filtré.
        # On prend donc sa valeur non nulle sur une seconde sortie RÉELLE du coordinateur.
        pause = coord._declarer_tonte_du_jour({
            "mower_mowing_minutes_today": 126.6,
            "mower_job_progress_pct": 30.0,
            "mower_job_id": "t2",
            "mower_is_docked": True,
        })
        trace["mower_job_paused_since"] = pause["mower_job_paused_since"]

        contexte.mower_context = dict(trace)
        snapshot = decision.build_decision_result(contexte).to_snapshot()
        for cle in trace:
            with self.subTest(cle=cle):
                self.assertIn(
                    cle,
                    snapshot,
                    msg=f"{cle} n'atteint pas le snapshot — filtre de préfixe ?",
                )

    def test_le_prefixe_des_cles_est_celui_qui_passe_les_filtres(self) -> None:
        """Garde explicite : renommer une clé en `mowing_…` la ferait disparaître en silence."""
        for cle in self.CLES:
            with self.subTest(cle=cle):
                self.assertTrue(cle.startswith(("mower_", "tondeuse_")))

    def test_les_cles_atteignent_les_attributs_du_capteur_de_tonte(self) -> None:
        source = (PACKAGE_DIR / "sensor.py").read_text(encoding="utf-8")
        for cle in self.CLES:
            with self.subTest(cle=cle):
                self.assertIn(f'"{cle}"', source)

    def test_la_declaration_est_appelee_dans_le_cycle_de_mise_a_jour(self) -> None:
        """Vérifie le CÂBLAGE, pas la déclaration : sans cet appel, tout le reste est mort."""
        import inspect

        source = inspect.getsource(
            coordinator_mod.GazonIntelligentCoordinator._calculer_donnees
        )
        self.assertIn("_declarer_tonte_du_jour(mower_context)", source)

    def test_la_declaration_precede_le_calcul_du_snapshot(self) -> None:
        """Déclarer APRÈS `compute_snapshot` repousserait la correction du retard d'un cycle."""
        import inspect

        source = inspect.getsource(
            coordinator_mod.GazonIntelligentCoordinator._calculer_donnees
        )
        self.assertLess(
            source.index("_declarer_tonte_du_jour"),
            source.index("self.brain.compute_snapshot"),
        )


class CarnetDePassesTondeuseTests(unittest.TestCase):
    """Le carnet des passes garage → garage : l'unité de travail réelle du robot.

    ⚠️ POURQUOI IL EXISTE. Le cumul de minutes de la journée ne dit pas si le jardin a été
    tondu — plus la machine se bloque, plus elle repart, plus elle accumule. Mesuré du 30/07
    au 08/08/2026 : 302 min le jour à trois blocages, 127 min la journée parfaite.

    ⚠️ CE CARNET N'ALIMENTE AUCUNE DÉCISION. Il observe. Les tests le vérifient aussi.
    """

    def _coord(self, instant, runtime=None):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = runtime if runtime is not None else {}
        coord._current_datetime = lambda: instant
        coord._current_date = lambda: instant.date()
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        coord._minutes_creditables = (
            coordinator_mod.GazonIntelligentCoordinator._minutes_creditables.__get__(coord)
        )
        return coord

    def _ctx(self, *, garage=False, tonte=False, batterie=None, erreur=None, connectee=True):
        return {
            "tondeuse_connectee": connectee,
            "tondeuse_erreur": erreur,
            "mower_is_mowing": tonte,
            "mower_is_docked": garage,
            "mower_battery": batterie,
        }

    def _rejouer(self, sequence, *, depart=None, coord=None):
        """Rejoue une suite (minutes, contexte) et rend la dernière sortie publiée."""
        t0 = depart or datetime(2026, 8, 8, 10, 30, tzinfo=timezone.utc)
        coord = coord or self._coord(t0)
        sortie = {}
        for minutes, ctx in sequence:
            instant = t0 + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            coord._current_date = lambda t=instant: t.date()
            sortie = coord._suivre_passes_tondeuse(dict(ctx))
        return sortie, coord

    def _journal(self, coord):
        return coord._runtime_state["mower_passes"]["journal"]

    # ---- LA SORTIE DU 02/09/2026, DE BOUT EN BOUT ----------------------------------------
    def _rejouer_avec_presence(self, sequence, coord):
        """Rejoue une séquence en passant par le VRAI résolveur de présence.

        ⚠️ `_ctx` fournit `mower_is_docked` à la main : il court-circuite exactement le code
        qu'on veut exercer. Ici la présence est calculée par `build_mower_coordination_context`,
        avec la mémoire de passe ouverte — la chaîne complète.
        """
        t0 = datetime(2026, 9, 2, 20, 40, tzinfo=timezone.utc)
        sortie = {}
        for minutes, brut, statut, erreur, batterie in sequence:
            instant = t0 + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            coord._current_date = lambda t=instant: t.date()
            base = {
                "tondeuse_source_entity": "lawn_mower.esperance_jr",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": brut,
                "tondeuse_statut": statut,
                "tondeuse_erreur": erreur,
                "tondeuse_en_charge": brut == "charging",
                "tondeuse_batterie": batterie,
                "mower_battery": batterie,
            }
            contexte = {
                **base,
                **mower_coordination_mod.build_mower_coordination_context(
                    base, enabled=True, passe_ouverte=coord._passe_tondeuse_ouverte()
                ),
            }
            sortie = coord._suivre_passes_tondeuse(contexte)
        return sortie, coord

    def test_la_sortie_du_2_septembre_ne_fait_plus_QU_UNE_passe(self) -> None:
        """⚠️ LE CAS RÉEL, rejoué de bout en bout.

            22:40:18  starting → mowing      ┐ une seule sortie
            23:53:51  idle    (dans le jardin)│ jamais `docked`
            23:54:12  idle    ⚠️ fausse rentrée mesurée
            23:56:12  erreur  trapped_timeout │ jamais en charge
            23:56:58  idle    ⚠️ seconde fausse rentrée → passe fantôme
            23:57:12  mowing                  │ batterie 91 → 10
            00:39:52  docked                  ┘ la SEULE vraie rentrée

        L'installation a inscrit TROIS entrées (73,2 · 0,0 · 42,3 min) et fait tomber
        `mower_autonomous_return_battery_median` de 85 à 78 — un retour autonome inventé.
        """
        coord = self._coord(datetime(2026, 9, 2, 20, 40, tzinfo=timezone.utc))
        sortie, coord = self._rejouer_avec_presence([
            (0, "docked", "au_repos", None, 100),
            (1, "mowing", "tonte_en_cours", None, 91),
            (73, "idle", "au_repos", None, 52),          # fausse rentrée n°1
            (76, "idle", "erreur", "trapped_timeout", 52),
            (78, "idle", "au_repos", None, 52),          # fausse rentrée n°2
            (79, "mowing", "tonte_en_cours", None, 52),
            (119, "docked", "au_repos", None, 10),       # la vraie rentrée
        ], coord)

        journal = self._journal(coord)
        self.assertEqual(
            len(journal), 1,
            f"la sortie est découpée en {len(journal)} passes au lieu d'une seule",
        )
        passe = journal[0]
        # ⚠️ La passe couvre TOUTE la sortie : elle démarre batterie pleine et finit à plat.
        # Sans le correctif, `journal[0]` s'arrête à 52 % — le tronçon avant la fausse rentrée.
        self.assertAlmostEqual(passe["batterie_fin"], 10.0, places=1,
                               msg="la passe s'arrête à la fausse rentrée au lieu du vrai retour")
        self.assertEqual(passe["fin_motif"], "bloquee",
                         "elle a été coincée pendant la sortie : le fait doit rester au carnet")
        self.assertGreater(passe["minutes_bloquees"], 0.0,
                           "le blocage réel a disparu du carnet")
        self.assertEqual(sortie["mower_passes_observed"], 1)
        # ⚠️ ET SURTOUT : aucun « retour autonome » ne doit être inventé. C'est ce faux retour à
        # 52 % qui a fait tomber la médiane publiée de 85 à 78 sur l'installation.
        self.assertIsNone(
            sortie["mower_autonomous_return_battery_median"],
            "un « retour autonome » a été inventé au milieu de la sortie",
        )

    # ---- PRÉMISSE ------------------------------------------------------------------------
    def test_premisse_une_passe_se_ferme_bien(self) -> None:
        """Sans ça, tous les tests de cette classe seraient verts sans rien exercer."""
        sortie, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (20, self._ctx(tonte=True, batterie=90)),
            (21, self._ctx(garage=True, batterie=90)),
        ])
        self.assertEqual(len(self._journal(coord)), 1, "aucune passe n'a été enregistrée")
        self.assertEqual(sortie["mower_passes_observed"], 1)
        self.assertFalse(sortie["mower_pass_in_progress"])

    # ---- LA VRAIE JOURNÉE DU 08/08/2026 ---------------------------------------------------
    def test_la_journee_du_8_aout_donne_deux_passes_de_natures_differentes(self) -> None:
        """Le fait qui a motivé tout ce carnet.

            10:35 → 10:55   18 min, retour à ~96 %   → la machine a décidé
            10:55 → 12:44  109 min, retour à  10 %   → batterie vide

        Deux retours au garage, deux causes sans rapport. Le cumul de minutes les confond.
        """
        sequence = [(0, self._ctx(garage=True, batterie=100))]
        for m in range(5, 24):                       # 10:35 → 10:54, tonte, batterie ~96 %
            sequence.append((m, self._ctx(tonte=True, batterie=100 if m < 15 else 96)))
        sequence.append((25, self._ctx(garage=True, batterie=96)))       # rentrée à 96 %
        for m in range(26, 134):                     # repart, tonte jusqu'à vider
            batt = max(10, 100 - (m - 26))
            sequence.append((m, self._ctx(tonte=True, batterie=batt)))
        sequence.append((135, self._ctx(garage=True, batterie=10)))      # rentrée à 10 %

        sortie, coord = self._rejouer(sequence)
        journal = self._journal(coord)
        self.assertEqual(len(journal), 2, "les deux passes doivent être distinguées")

        courte, longue = journal
        self.assertEqual(courte["fin_motif"], "retour_autonome",
                         msg="rentrer à 96 % n'est PAS un retour batterie")
        self.assertAlmostEqual(courte["minutes_tondues"], 19.0, delta=2.0)
        self.assertEqual(courte["batterie_fin"], 96)

        self.assertEqual(longue["fin_motif"], "batterie_vide")
        self.assertAlmostEqual(longue["minutes_tondues"], 108.0, delta=3.0)
        self.assertEqual(longue["batterie_fin"], 10)
        self.assertEqual(sortie["mower_pass_count_today"], 2)

    def test_une_passe_bloquee_est_etiquetee_comme_telle(self) -> None:
        """Une passe immobilisée en plein jardin n'est pas un tour de jardin."""
        sortie, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (10, self._ctx(erreur="lifted", batterie=95)),
            (20, self._ctx(erreur="lifted", batterie=95)),
            (21, self._ctx(garage=True, batterie=95)),
        ])
        passe = self._journal(coord)[0]
        self.assertEqual(passe["fin_motif"], "bloquee")
        self.assertGreater(passe["minutes_bloquees"], 0.0)

    def test_le_blocage_prime_sur_la_batterie_pleine(self) -> None:
        """Sinon une passe bloquée à 95 % passerait pour une décision de la machine."""
        _, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (5, self._ctx(erreur="trapped_timeout", batterie=98)),
            (6, self._ctx(garage=True, batterie=98)),
        ])
        self.assertEqual(self._journal(coord)[0]["fin_motif"], "bloquee")

    # ---- CE QUI NE DOIT PAS DEVENIR UNE PASSE ---------------------------------------------
    def test_une_passe_en_cours_n_est_pas_comptee(self) -> None:
        sortie, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (30, self._ctx(tonte=True, batterie=80)),
        ])
        self.assertTrue(sortie["mower_pass_in_progress"])
        self.assertEqual(self._journal(coord), [])
        self.assertEqual(sortie["mower_pass_count_today"], 0)

    def test_une_tondeuse_injoignable_n_ouvre_pas_de_passe(self) -> None:
        """RÈGLE DE LA MAISON : une absence de mesure n'est pas une sortie au jardin."""
        sortie, coord = self._rejouer([
            (0, self._ctx(connectee=False)),
            (10, self._ctx(connectee=False)),
        ])
        self.assertFalse(sortie["mower_pass_in_progress"])
        self.assertEqual(self._journal(coord), [])

    def test_un_arret_de_home_assistant_ne_gonfle_pas_la_passe(self) -> None:
        """Au-delà du plafond d'échantillon, l'écart est un trou, pas du temps tondu."""
        _, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (241, self._ctx(tonte=True, batterie=40)),   # 4 h plus tard : redémarrage
            (242, self._ctx(garage=True, batterie=40)),
        ])
        self.assertLess(self._journal(coord)[0]["minutes_tondues"], 10.0)

    # ---- LE PROFIL APPRIS ------------------------------------------------------------------
    def test_rien_n_est_appris_avant_d_avoir_assez_observe(self) -> None:
        """⚠️ Une médiane tirée de deux passes ressemble à une mesure sans en être une."""
        sortie, _ = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (60, self._ctx(tonte=True, batterie=10)),
            (61, self._ctx(garage=True, batterie=10)),
        ])
        self.assertIsNone(sortie["mower_full_pass_minutes_median"])
        self.assertIsNone(sortie["mower_passes_per_day_median"])

    def test_la_duree_d_une_passe_pleine_s_apprend(self) -> None:
        coord = self._coord(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
        journal = [
            {"date": f"2026-08-0{j}", "minutes_tondues": duree, "batterie_debut": 100,
             "batterie_fin": 10, "fin_motif": "batterie_vide"}
            for j, duree in enumerate((109.0, 134.0, 113.0, 133.0), start=2)
        ]
        profil = coord._profil_appris_tondeuse(journal)
        self.assertAlmostEqual(profil["mower_full_pass_minutes_median"], 123.0, places=1)

    def test_la_mediane_resiste_a_une_journee_aberrante(self) -> None:
        """La moyenne suivrait la valeur folle ; la médiane non. C'est le but."""
        coord = self._coord(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
        journal = [
            {"date": f"2026-08-0{j}", "minutes_tondues": duree, "batterie_debut": 100,
             "batterie_fin": 10, "fin_motif": "batterie_vide"}
            for j, duree in enumerate((110.0, 112.0, 111.0, 900.0), start=2)
        ]
        profil = coord._profil_appris_tondeuse(journal)
        self.assertLess(profil["mower_full_pass_minutes_median"], 200.0)

    def test_la_batterie_du_retour_autonome_s_apprend(self) -> None:
        """La réponse mesurée à « à quel niveau décide-t-elle que c'est fini ? »."""
        coord = self._coord(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
        journal = [
            {"date": f"2026-08-0{j}", "minutes_tondues": 18.0, "batterie_debut": 100,
             "batterie_fin": batt, "fin_motif": "retour_autonome"}
            for j, batt in enumerate((96.0, 95.0, 97.0), start=2)
        ]
        profil = coord._profil_appris_tondeuse(journal)
        self.assertAlmostEqual(profil["mower_autonomous_return_battery_median"], 96.0, places=1)

    def test_les_passes_bloquees_ne_comptent_pas_dans_le_rythme_quotidien(self) -> None:
        """Deux sorties par jour sont attendues ; une passe bloquée n'en est pas une."""
        coord = self._coord(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
        journal = []
        for jour in ("2026-08-02", "2026-08-03", "2026-08-04"):
            journal += [
                {"date": jour, "minutes_tondues": 110.0, "batterie_fin": 10, "fin_motif": "batterie_vide"},
                {"date": jour, "minutes_tondues": 115.0, "batterie_fin": 12, "fin_motif": "batterie_vide"},
                {"date": jour, "minutes_tondues": 5.0, "batterie_fin": 90, "fin_motif": "bloquee"},
            ]
        profil = coord._profil_appris_tondeuse(journal)
        self.assertAlmostEqual(profil["mower_passes_per_day_median"], 2.0, places=1)

    # ---- PERSISTANCE ------------------------------------------------------------------------
    def test_le_carnet_survit_a_un_redemarrage(self) -> None:
        """⚠️ Le carnet s'accumule sur des SEMAINES : non persisté, il n'apprend jamais rien.
        C'est exactement le défaut qui avait rendu `mower_health` inutile en 0.50.0."""
        _, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (60, self._ctx(tonte=True, batterie=10)),
            (61, self._ctx(garage=True, batterie=10)),
        ])
        # ⚠️ On passe par `_serialized_runtime_state()`, la VRAIE méthode qui construit le dict
        # persisté — pas par `_serialize_runtime_value` sur la valeur. Sérialiser la valeur à la
        # main prouve qu'elle est sérialisable, PAS qu'elle figure dans la liste blanche : mon
        # premier test faisait ça et il survivait à la suppression de la clé.
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        coord._runtime_state.setdefault("active_irrigation_session", None)
        coord._runtime_state.setdefault("last_irrigation_execution", None)
        serialise = coord._serialized_runtime_state()
        self.assertIn("mower_passes", serialise, "le carnet n'atteint pas le disque")

        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(
            len(relu._runtime_state["mower_passes"]["journal"]), 1,
            msg="le carnet a été écrit puis ignoré au rechargement — pire qu'absent",
        )

    def test_le_journal_ne_grossit_pas_sans_fin(self) -> None:
        coord = self._coord(datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc))
        coord._runtime_state["mower_passes"] = {
            "en_cours": None,
            "journal": [{"date": "2026-07-01", "minutes_tondues": 1.0, "fin_motif": "bloquee"}] * 200,
        }
        self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (30, self._ctx(tonte=True, batterie=50)),
            (31, self._ctx(garage=True, batterie=50)),
        ], coord=coord)
        self.assertLessEqual(len(self._journal(coord)), 60)

    # ---- ROBUSTESSE ET NON-INGÉRENCE --------------------------------------------------------
    def test_un_carnet_ne_casse_jamais_un_cycle(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        sortie = coord._suivre_passes_tondeuse({"tondeuse_connectee": True})
        self.assertIn("mower_pass_in_progress", sortie)
        self.assertIsNone(sortie["mower_pass_in_progress"])

    def test_un_carnet_persiste_abime_ne_casse_rien(self) -> None:
        coord = self._coord(datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc))
        coord._runtime_state["mower_passes"] = "n'importe quoi"
        sortie = coord._suivre_passes_tondeuse(self._ctx(garage=True, batterie=100))
        self.assertEqual(sortie["mower_passes_observed"], 0)

    def test_une_sortie_sans_une_minute_tondue_n_entre_pas_au_carnet(self) -> None:
        """⚠️ QUATRE ENTRÉES SUR TRENTE étaient des rebonds d'état, mesuré le 30/08/2026.

        L'intégration de la tondeuse publie une séquence qui rebondit au démarrage —
        `starting` → `docked` 9 s → `starting` → `mowing` — et chaque rebond ouvrait puis
        refermait une passe. Deux entrées de DIX SECONDES, 0,0 min tondue, batterie 100 → 100.

        Elles ne sont pas neutres : rentrant à ~100 % de batterie, elles tirent
        `mower_autonomous_return_battery_median` vers le haut, et gonflent
        `mower_passes_per_day_median` — le 30/08 comptait 7 passes pour 4 réelles.
        """
        # ⚠️ `coordinator_mod`, PAS `importlib.import_module` : test_init.py remplace l'entrée
        # du coordinator dans `sys.modules` par un faux module. Une réimportation récupère le
        # faux et le test tombe — mais seulement quand toute la suite tourne, jamais seul.
        fantome = {"minutes_tondues": 0.0, "minutes_bloquees": 0.0, "fin_motif": "retour_autonome"}
        self.assertFalse(coordinator_mod._passe_a_retenir(fantome),
                         "une sortie de 10 s sans tonte est enregistrée comme une passe")

    def test_les_fantomes_DEJA_au_carnet_ne_polluent_plus_ce_qui_est_publie(self) -> None:
        """⚠️ LE FILTRE N'EXISTAIT QU'À L'ÉCRITURE — mesuré en production le 01/09/2026.

        La 0.64.0 écartait les rebonds au moment de les inscrire, mais les TROIS déjà au carnet
        continuaient d'alimenter tout ce qu'on publie. Sur le journal réel de l'installation,
        `mower_autonomous_return_battery_median` sortait **96,5 % au lieu de 85,0** : trois
        retours à 99-100 % de batterie s'ajoutaient aux cinq vrais.

        Le journal ci-dessous EST celui de l'installation, réduit aux retours autonomes qui
        entrent dans cette médiane — trois fantômes du 30/08 compris.
        """
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        reels = [
            {"date": "2026-08-18", "minutes_tondues": 51.0, "batterie_fin": 48.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-30", "minutes_tondues": 31.7, "batterie_fin": 85.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-30", "minutes_tondues": 21.4, "batterie_fin": 94.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-30", "minutes_tondues": 23.6, "batterie_fin": 100.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-30", "minutes_tondues": 14.2, "batterie_fin": 71.0, "fin_motif": "retour_autonome"},
        ]
        fantomes = [
            {"date": "2026-08-30", "minutes_tondues": 0.0, "minutes_bloquees": 0.0, "batterie_fin": 100.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-30", "minutes_tondues": 0.0, "minutes_bloquees": 0.0, "batterie_fin": 100.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-30", "minutes_tondues": 0.0, "minutes_bloquees": 0.0, "batterie_fin": 99.0, "fin_motif": "retour_autonome"},
        ]
        journal = reels + fantomes

        # Prémisse : le journal BRUT donne bien la valeur fausse observée en production.
        self.assertAlmostEqual(
            coord._profil_appris_tondeuse(journal)["mower_autonomous_return_battery_median"],
            96.5, places=1,
            msg="prémisse : ce journal doit reproduire les 96,5 % publiés à tort",
        )

        # ⚠️ ET ON PASSE PAR LE POINT D'APPEL RÉEL, pas par `_profil_appris_tondeuse` nourri
        # d'une liste filtrée à la main : le banc a montré qu'un test qui filtre lui-même
        # survit à la suppression du filtre AU POINT D'APPEL. C'est le défaut que ce projet
        # documente sous « muter le point d'appel, pas la fonction ».
        coord._current_datetime = lambda: datetime(2026, 8, 30, 23, 30, tzinfo=timezone.utc)
        coord._current_date = lambda: date(2026, 8, 30)
        coord._tonte_autorisee_au_cycle_precedent = lambda: True
        coord._runtime_state = {"mower_passes": {"en_cours": None, "journal": list(journal)}}
        publie = coord._suivre_passes_tondeuse(
            {"mower_is_docked": True, "mower_operation_state": "idle", "tondeuse_batterie": 100}
        )
        self.assertAlmostEqual(
            publie["mower_autonomous_return_battery_median"], 85.0, places=1,
            msg="la médiane publiée reste tirée vers le haut par les rebonds",
        )
        self.assertEqual(publie["mower_passes_observed"], 5,
                         "les trois fantômes comptent encore parmi les passes observées")

        # Le carnet PERSISTÉ, lui, n'est pas amputé : on filtre ce qu'on publie, on n'efface pas.
        self.assertEqual(
            len(coord._runtime_state["mower_passes"]["journal"]), 8,
            "le filtre de publication a effacé l'historique au lieu de le masquer",
        )

    def test_un_fantome_deja_au_carnet_ne_devient_pas_la_DERNIERE_passe(self) -> None:
        """⚠️ SITE DE LECTURE OUBLIÉ AU PREMIER JET, trouvé en relisant la revue.

        `derniere = journal[-1]` alimente quatre attributs. Aujourd'hui la dernière entrée est
        réelle, donc rien ne se voyait ; si un rebond avait clôturé en dernier, la carte aurait
        annoncé une passe de 0,0 min rentrée à 100 % de batterie.
        """
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._current_datetime = lambda: datetime(2026, 8, 30, 23, 30, tzinfo=timezone.utc)
        coord._current_date = lambda: date(2026, 8, 30)
        coord._tonte_autorisee_au_cycle_precedent = lambda: True
        coord._runtime_state = {
            "mower_passes": {
                "en_cours": None,
                "journal": [
                    {"date": "2026-08-30", "minutes_tondues": 14.2, "batterie_debut": 100.0,
                     "batterie_fin": 71.0, "fin_motif": "retour_autonome"},
                    {"date": "2026-08-30", "minutes_tondues": 0.0, "minutes_bloquees": 0.0,
                     "batterie_debut": 100.0, "batterie_fin": 100.0, "fin_motif": "retour_autonome"},
                ],
            }
        }
        sortie = coord._suivre_passes_tondeuse(
            {"mower_is_docked": True, "mower_operation_state": "idle", "tondeuse_batterie": 100}
        )
        self.assertAlmostEqual(
            sortie["mower_last_pass_minutes"], 14.2, places=1,
            msg="un rebond de 0,0 min est publié comme la dernière passe",
        )
        self.assertAlmostEqual(sortie["mower_last_pass_battery_end"], 71.0, places=1)
        self.assertEqual(sortie["mower_passes_observed"], 1,
                         "le fantôme est encore compté dans le nombre de passes observées")

    def test_le_carnet_lui_meme_refuse_la_passe_fantome(self) -> None:
        """⚠️ LE PRÉDICAT NE PROUVE RIEN S'IL N'EST PAS CÂBLÉ.

        Le banc de mutations l'a montré : supprimer le filtre au point d'appel ne faisait
        tomber AUCUN test, parce que je ne testais que la fonction. Ce test-ci rejoue une
        vraie séquence — sortie puis retour immédiat, sans une seconde de tonte — et regarde
        ce qui atterrit dans le journal.
        """
        sortie, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (0.1, self._ctx(garage=False, batterie=100)),   # elle sort — rebond d'état
            (0.2, self._ctx(garage=True, batterie=100)),    # ...et rentre aussitôt
        ])
        self.assertEqual(self._journal(coord), [],
                         "un aller-retour de garage sans tonte est entré au carnet")
        self.assertEqual(sortie.get("mower_pass_count_today"), 0)

    def test_le_carnet_garde_une_vraie_passe(self) -> None:
        """Prémisse du test précédent : le montage doit savoir enregistrer une passe."""
        _sortie, coord = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(garage=False, tonte=True, batterie=100)),
            (30, self._ctx(garage=False, tonte=True, batterie=70)),
            (31, self._ctx(garage=True, batterie=68)),
        ])
        journal = self._journal(coord)
        self.assertEqual(len(journal), 1, "une passe réellement tondue n'a pas été enregistrée")
        self.assertGreater(journal[0]["minutes_tondues"], 0.0)

    def test_une_passe_bloquee_sans_tonte_reste_au_carnet(self) -> None:
        """Un blocage sans tonte est le fait le PLUS intéressant du carnet : on le garde."""
        for passe in (
            {"minutes_tondues": 0.0, "minutes_bloquees": 6.0, "fin_motif": "bloquee"},
            {"minutes_tondues": 0.0, "minutes_bloquees": 0.0, "fin_motif": "bloquee"},
            {"minutes_tondues": 14.2, "minutes_bloquees": 0.0, "fin_motif": "retour_autonome"},
            {"minutes_tondues": None, "minutes_bloquees": None, "fin_motif": "inconnue"},
        ):
            with self.subTest(passe=passe.get("fin_motif")):
                self.assertTrue(coordinator_mod._passe_a_retenir(passe))

    def test_le_carnet_n_alimente_AUCUNE_decision(self) -> None:
        """Promesse explicite : il observe, il ne tranche pas. Le jour où une décision lira
        ces clés, ce test doit tomber et forcer une discussion."""
        # ⚠️ `decision_watering.py` manquait ici alors que les quatre autres verrous
        # « observation seule » le couvrent : une clé du carnet lue par la décision
        # d'arrosage serait passée sans bruit. Cinq verrous, la même liste de modules.
        source = (PACKAGE_DIR / "decision_mowing.py").read_text(encoding="utf-8")
        source += (PACKAGE_DIR / "decision_watering.py").read_text(encoding="utf-8")
        source += (PACKAGE_DIR / "guidance.py").read_text(encoding="utf-8")
        source += (PACKAGE_DIR / "decision.py").read_text(encoding="utf-8")
        for cle in ("mower_full_pass_minutes_median", "mower_passes_per_day_median",
                    "mower_last_pass_end_reason", "mower_pass_count_today"):
            with self.subTest(cle=cle):
                self.assertNotIn(cle, source)


class CarnetDePassesCablageTests(unittest.TestCase):
    """⚠️ Vérifier qu'une clé est DÉCLARÉE dans une liste ne prouve rien — c'est ce qui a
    laissé passer le défaut de préfixe des clés d'auto-déclaration le 08/08/2026. Ce test
    part de la sortie RÉELLE du coordinator et la suit jusqu'au snapshot publié.
    """

    def _trace(self):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        instant = datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc)
        coord._runtime_state = {}
        coord._current_datetime = lambda: instant
        coord._current_date = lambda: instant.date()
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        coord._minutes_creditables = (
            coordinator_mod.GazonIntelligentCoordinator._minutes_creditables.__get__(coord)
        )
        return coord._suivre_passes_tondeuse({
            "tondeuse_connectee": True, "mower_is_docked": True, "mower_battery": 100,
        })

    def test_les_cles_traversent_reellement_jusqu_au_snapshot(self) -> None:
        decision = importlib.import_module("custom_components.gazon_intelligent.decision")
        trace = self._trace()
        # Les valeurs `None` sont légitimement filtrées en route : on n'exige la traversée
        # que des clés réellement renseignées.
        renseignees = {k: v for k, v in trace.items() if v is not None}
        self.assertTrue(renseignees, "prémisse : la trace exercée est entièrement vide")

        contexte = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-08-06"}],
            today=date(2026, 8, 6), hour_of_day=13, temperature=22.0,
            pluie_24h=0, pluie_demain=0, humidite=55, type_sol="limoneux", etp_capteur=4.0,
        )
        contexte.mower_context = dict(renseignees)
        snapshot = decision.build_decision_result(contexte).to_snapshot()
        for cle in renseignees:
            with self.subTest(cle=cle):
                self.assertIn(cle, snapshot, msg=f"{cle} n'atteint pas le snapshot")

    def test_toutes_les_cles_portent_le_prefixe_qui_passe_les_filtres(self) -> None:
        for cle in self._trace():
            with self.subTest(cle=cle):
                self.assertTrue(
                    cle.startswith(("mower_", "tondeuse_")),
                    msg="une clé `mowing_…` meurt en silence dans les filtres de recopie",
                )

    def test_le_carnet_est_appele_dans_le_cycle(self) -> None:
        import inspect

        source = inspect.getsource(
            coordinator_mod.GazonIntelligentCoordinator._calculer_donnees
        )
        self.assertIn("_suivre_passes_tondeuse(mower_context)", source)


class PasseRappeleeParLaCoordinationTests(unittest.TestCase):
    """⚠️ LA QUATRIÈME FIN, OUBLIÉE À LA LIVRAISON DU CARNET — et la plus fréquente ici.

    Le 13/08/2026, mesuré à la seconde :

        10:40:43,774   tonte_autorisee → off   (34,9 °C, seuil 30)
        10:40:45,244   la tondeuse rentre      ← 1,5 seconde plus tard

    Elle est rentrée avec **58 %** de batterie, RAPPELÉE par la coordination — pas parce
    qu'elle avait fini. Le carnet l'a étiquetée `retour_autonome`, c'est-à-dire « elle a
    décidé toute seule ». Une étiquette qui ment, et qui nourrit ensuite
    `mower_autonomous_return_battery_median` : la mesure même censée dire à quel niveau la
    machine juge son travail terminé.
    """

    JOUR = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)

    def _coord(self, autorisee=True):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {}
        coord._current_datetime = lambda: self.JOUR
        coord._current_date = lambda: self.JOUR.date()
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        coord._minutes_creditables = (
            coordinator_mod.GazonIntelligentCoordinator._minutes_creditables.__get__(coord)
        )
        coord._tonte_autorisee_au_cycle_precedent = lambda: autorisee
        return coord

    def _ctx(self, *, garage=False, tonte=False, batterie=None, erreur=None):
        return {
            "tondeuse_connectee": True, "tondeuse_erreur": erreur,
            "mower_is_mowing": tonte, "mower_is_docked": garage, "mower_battery": batterie,
        }

    def _rejouer(self, sequence, *, autorisee_par_pas):
        """Rejoue une passe en faisant varier l'autorisation au fil des échantillons."""
        coord = self._coord()
        for (minutes, ctx), autorisee in zip(sequence, autorisee_par_pas):
            instant = self.JOUR + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            coord._current_date = lambda t=instant: t.date()
            coord._tonte_autorisee_au_cycle_precedent = lambda a=autorisee: a
            coord._suivre_passes_tondeuse(dict(ctx))
        return coord._runtime_state["mower_passes"]["journal"]

    def test_la_journee_du_13_aout_est_une_passe_RAPPELEE(self) -> None:
        """Le cas réel : 40 min, retour à 58 %, tonte interdite au moment du retour."""
        journal = self._rejouer(
            [(0, self._ctx(garage=True, batterie=100)),
             (1, self._ctx(tonte=True, batterie=100)),
             (14, self._ctx(tonte=True, batterie=80)),
             (27, self._ctx(tonte=True, batterie=68)),
             (40, self._ctx(tonte=True, batterie=58)),
             (42, self._ctx(garage=True, batterie=58))],
            autorisee_par_pas=[True, True, True, True, False, False],
        )
        passe = journal[0]
        self.assertEqual(passe["fin_motif"], "rappelee",
                         msg="rentrer à 58 % pendant une interdiction n'est PAS une décision de la machine")
        self.assertEqual(passe["batterie_fin"], 58)
        self.assertIs(passe["tonte_autorisee_fin"], False)

    def test_le_meme_retour_reste_autonome_si_la_tonte_est_restee_autorisee(self) -> None:
        """PRÉMISSE MIROIR : seule l'autorisation distingue les deux cas, rien d'autre."""
        journal = self._rejouer(
            [(0, self._ctx(garage=True, batterie=100)),
             (1, self._ctx(tonte=True, batterie=100)),
             (40, self._ctx(tonte=True, batterie=58)),
             (42, self._ctx(garage=True, batterie=58))],
            autorisee_par_pas=[True, True, True, True],
        )
        self.assertEqual(journal[0]["fin_motif"], "retour_autonome")

    def test_une_batterie_vide_prime_sur_le_rappel(self) -> None:
        """⚠️ Une machine à 10 % rentre de toute façon : lui coller le rappel effacerait la
        cause réelle. L'ordre des cas est le coeur de la méthode."""
        journal = self._rejouer(
            [(0, self._ctx(garage=True, batterie=100)),
             (1, self._ctx(tonte=True, batterie=100)),
             (100, self._ctx(tonte=True, batterie=10)),
             (102, self._ctx(garage=True, batterie=10))],
            autorisee_par_pas=[True, True, False, False],
        )
        self.assertEqual(journal[0]["fin_motif"], "batterie_vide")

    def test_un_blocage_prime_sur_tout(self) -> None:
        journal = self._rejouer(
            [(0, self._ctx(garage=True, batterie=100)),
             (1, self._ctx(tonte=True, batterie=100)),
             (10, self._ctx(erreur="lifted", batterie=90)),
             (12, self._ctx(garage=True, batterie=90))],
            autorisee_par_pas=[True, True, False, False],
        )
        self.assertEqual(journal[0]["fin_motif"], "bloquee")

    def test_une_autorisation_inconnue_ne_cree_pas_de_faux_rappel(self) -> None:
        """RÈGLE DE LA MAISON : `None` est une absence de mesure, pas une interdiction."""
        journal = self._rejouer(
            [(0, self._ctx(garage=True, batterie=100)),
             (1, self._ctx(tonte=True, batterie=100)),
             (40, self._ctx(tonte=True, batterie=58)),
             (42, self._ctx(garage=True, batterie=58))],
            autorisee_par_pas=[None, None, None, None],
        )
        self.assertEqual(journal[0]["fin_motif"], "retour_autonome")
        self.assertIsNone(journal[0]["tonte_autorisee_fin"])

    def test_le_fait_brut_est_conserve_a_cote_de_l_etiquette(self) -> None:
        """Si le classement se révèle mauvais, tout doit pouvoir se rejouer sur le journal."""
        journal = self._rejouer(
            [(0, self._ctx(garage=True, batterie=100)),
             (1, self._ctx(tonte=True, batterie=100)),
             (40, self._ctx(tonte=True, batterie=58)),
             (42, self._ctx(garage=True, batterie=58))],
            autorisee_par_pas=[True, True, False, False],
        )
        self.assertIn("tonte_autorisee_fin", journal[0])

    # ---- La médiane que le défaut faussait -------------------------------------------------
    def test_les_passes_rappelees_ne_polluent_plus_la_mediane_des_retours_autonomes(self) -> None:
        """LE POINT DE TOUT LE CORRECTIF. Sans lui, les rappels météo (~58 %) se mélangeaient
        aux vraies décisions (~96 %) et la médiane ne mesurait plus rien."""
        coord = self._coord()
        journal = [
            {"date": "2026-08-02", "minutes_tondues": 18.0, "batterie_fin": 96.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-03", "minutes_tondues": 18.0, "batterie_fin": 95.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-04", "minutes_tondues": 18.0, "batterie_fin": 97.0, "fin_motif": "retour_autonome"},
            {"date": "2026-08-13", "minutes_tondues": 40.0, "batterie_fin": 58.0, "fin_motif": "rappelee"},
            {"date": "2026-08-14", "minutes_tondues": 35.0, "batterie_fin": 61.0, "fin_motif": "rappelee"},
        ]
        profil = coord._profil_appris_tondeuse(journal)
        self.assertAlmostEqual(profil["mower_autonomous_return_battery_median"], 96.0, places=1)

    def test_une_passe_rappelee_reste_un_vrai_tour_de_jardin(self) -> None:
        """Elle a bien tondu 40 minutes : ça compte dans le rythme quotidien, contrairement
        à une passe bloquée."""
        coord = self._coord()
        journal = []
        for jour in ("2026-08-13", "2026-08-14", "2026-08-15"):
            journal += [
                {"date": jour, "minutes_tondues": 40.0, "batterie_fin": 58.0, "fin_motif": "rappelee"},
                {"date": jour, "minutes_tondues": 110.0, "batterie_fin": 10.0, "fin_motif": "batterie_vide"},
                {"date": jour, "minutes_tondues": 3.0, "batterie_fin": 92.0, "fin_motif": "bloquee"},
            ]
        self.assertAlmostEqual(coord._profil_appris_tondeuse(journal)["mower_passes_per_day_median"], 2.0)

    # ---- Lecture de l'autorisation ---------------------------------------------------------
    def test_l_autorisation_est_lue_sur_le_cycle_precedent(self) -> None:
        """Le carnet tourne AVANT compute_snapshot : la décision du cycle courant n'existe pas
        encore. C'est bien celle qui a été PUBLIÉE qui a provoqué le retour."""
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.brain = types.SimpleNamespace(last_result=types.SimpleNamespace(tonte_autorisee=False))
        self.assertIs(coord._tonte_autorisee_au_cycle_precedent(), False)

    def test_sans_decision_calculee_l_autorisation_est_inconnue(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.brain = types.SimpleNamespace(last_result=None)
        self.assertIsNone(coord._tonte_autorisee_au_cycle_precedent())

    def test_un_cerveau_absent_ne_casse_pas_le_cycle(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        self.assertIsNone(coord._tonte_autorisee_au_cycle_precedent())


class ResetDuCarnetDePassesTests(unittest.TestCase):
    """Les motifs de fin sont une INTERPRÉTATION, et elle a déjà changé une fois.

    Jusqu'en 0.53.1, un rappel par la coordination était enregistré comme une décision de la
    tondeuse. Les passes écrites sous l'ancienne règle ne portent pas le fait brut qui
    permettrait de les rejuger : elles sont invérifiables, et fausseraient les médianes sans
    qu'on puisse le voir. Vider le carnet est le seul moyen honnête de repartir.
    """

    def _coord(self, journal):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {"mower_passes": {"en_cours": {"date": "2026-08-13"}, "journal": journal}}
        coord._async_save_state = AsyncMock()
        coord.async_request_refresh = AsyncMock()
        # ⚠️ Depuis la 0.84.0 une action de l'utilisateur passe par `async_refresh` (immédiat).
        coord.async_refresh = AsyncMock()
        return coord

    def test_le_carnet_repart_vide(self) -> None:
        coord = self._coord([{"date": "2026-08-13", "fin_motif": "retour_autonome"}])
        asyncio.run(coord.async_reset_mower_passes())
        carnet = coord._runtime_state["mower_passes"]
        self.assertEqual(carnet["journal"], [])
        self.assertIsNone(carnet["en_cours"], "une passe en cours doit être abandonnée aussi")

    def test_le_vidage_est_persiste(self) -> None:
        """⚠️ Sans écriture, le carnet reviendrait au premier redémarrage."""
        coord = self._coord([{"date": "2026-08-13", "fin_motif": "retour_autonome"}])
        asyncio.run(coord.async_reset_mower_passes())
        coord._async_save_state.assert_awaited()

    def test_le_carnet_vide_ne_publie_aucune_mediane(self) -> None:
        coord = self._coord([{"date": "2026-08-13", "fin_motif": "retour_autonome"}])
        asyncio.run(coord.async_reset_mower_passes())
        profil = coordinator_mod.GazonIntelligentCoordinator._profil_appris_tondeuse(
            coord, coord._runtime_state["mower_passes"]["journal"]
        )
        self.assertIsNone(profil["mower_full_pass_minutes_median"])
        self.assertIsNone(profil["mower_autonomous_return_battery_median"])

    def test_le_service_est_declare_et_cable(self) -> None:
        """Un service défini dans services.yaml mais jamais enregistré n'existe pas."""
        import importlib as _il

        init = _il.import_module("custom_components.gazon_intelligent.__init__")
        self.assertEqual(init.SERVICE_RESET_MOWER_PASSES, "reset_mower_passes")
        self.assertTrue(hasattr(init, "_handle_reset_mower_passes"))
        yaml_src = (PACKAGE_DIR / "services.yaml").read_text(encoding="utf-8")
        self.assertIn("reset_mower_passes:", yaml_src)
        init_src = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("SERVICE_RESET_MOWER_PASSES,\n        _handle_reset_mower_passes,", init_src)


class PluieMesureeTests(unittest.TestCase):
    """La garde « il pleut » reçoit enfin une MESURE, pas seulement une prévision.

    ⚠️ POURQUOI CES TESTS EXISTENT. Nuit du 16/08/2026, mesuré à la seconde :

        00:12      pluviomètre 0,1 mm — la pluie commence     météo : partlycloudy
        02:05:42   1,2 mm, il pleut toujours                  météo : clear-night
                   └→ 45 ms plus tard : 5 mm autorisés, `execution_autorisee: true`
        03:59:47   2,4 mm                                     météo : rainy

    3 h 47 pendant lesquelles la seule entrée de la garde s'est trompée, et c'est la
    PRÉVISION qui a débloqué pendant qu'une mesure disait le contraire.
    """

    def _coord(self, instant, runtime=None):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = runtime if runtime is not None else {}
        coord._current_datetime = lambda: instant
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        # 0.95.0 : le suivi retient QUEL capteur il suit (un autre repart de sa propre lecture).
        coord._entite_pluie = "sensor.pluie_du_jour"
        coord._get_conf = lambda cle: coord._entite_pluie if cle == "capteur_pluie_24h" else None
        return coord

    def _rejouer(self, lectures, *, depart=None, coord=None):
        """Rejoue une suite (minutes, cumul_mm) et rend la dernière sortie publiée."""
        t0 = depart or datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
        coord = coord or self._coord(t0)
        sortie = {}
        for minutes, cumul in lectures:
            instant = t0 + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            sortie = coord._suivre_pluie_mesuree(cumul)
        return sortie, coord

    # ── un autre capteur (0.95.0 : la page change les entrées) ──────────────────────────
    def test_un_autre_capteur_plus_HAUT_n_est_pas_une_averse(self) -> None:
        _, coord = self._rejouer([(0, 1.0), (10, 1.0)])
        coord._entite_pluie = "sensor.station_pluie"
        sortie, _ = self._rejouer([(20, 3.5)], coord=coord)
        self.assertFalse(sortie["pluie_mesuree_active"], "2,5 mm d'écart entre deux capteurs ne sont pas une averse")
        self.assertEqual(sortie["pluie_mesuree_lame_mm"], 0.0)
        sortie, _ = self._rejouer([(30, 3.8)], coord=coord)
        self.assertTrue(sortie["pluie_mesuree_active"], "la pluie du nouveau capteur est vue")
        self.assertAlmostEqual(sortie["pluie_mesuree_lame_mm"], 0.3, places=2)

    # ── le détecteur de hausse ────────────────────────────────────────────────────────
    def test_sans_capteur_la_reponse_est_inconnue_jamais_un_non(self) -> None:
        """⚠️ Le cœur du correctif : une absence ne doit pas devenir « il ne pleut pas »."""
        sortie, _ = self._rejouer([(0, None)])
        self.assertIsNone(sortie["pluie_mesuree_active"])
        self.assertIsNone(sortie["pluie_mesuree_cumul_mm"])

    def test_premiere_lecture_ne_conclut_rien(self) -> None:
        sortie, _ = self._rejouer([(0, 1.2)])
        self.assertIsNone(sortie["pluie_mesuree_active"])
        self.assertEqual(sortie["pluie_mesuree_cumul_mm"], 1.2)

    def test_une_hausse_signe_une_pluie_en_cours(self) -> None:
        sortie, _ = self._rejouer([(0, 1.2), (6, 1.8)])
        self.assertIs(sortie["pluie_mesuree_active"], True)
        self.assertEqual(sortie["pluie_mesuree_minutes_depuis_hausse"], 0.0)

    def test_un_cumul_stable_n_est_pas_une_pluie(self) -> None:
        """Le cumul reste affiché toute la journée après l'averse : la VALEUR ne dit rien."""
        sortie, _ = self._rejouer([(0, 3.2), (6, 3.2), (12, 3.2)])
        self.assertIs(sortie["pluie_mesuree_active"], False)

    def test_l_averse_expire_apres_la_fenetre(self) -> None:
        sortie, _ = self._rejouer([(0, 1.2), (6, 1.8), (6 + 31, 1.8)])
        self.assertIs(sortie["pluie_mesuree_active"], False)
        self.assertEqual(sortie["pluie_mesuree_minutes_depuis_hausse"], 31.0)

    def test_l_averse_tient_pendant_toute_la_fenetre(self) -> None:
        sortie, _ = self._rejouer([(0, 1.2), (6, 1.8), (6 + 29, 1.8)])
        self.assertIs(sortie["pluie_mesuree_active"], True)

    def test_une_baisse_n_est_pas_une_pluie_et_le_pic_tient(self) -> None:
        """⚠️ Mesuré 10 fois le 04/08/2026 en une journée : le capteur redescend.

        Une baisse ne compte pas comme une averse et n'efface pas la fraîcheur de la
        précédente. Surtout, le PIC du jour est conservé : sinon la remontée d'après se
        comparerait à un plancher et passerait pour une hausse fantôme.
        """
        sortie, coord = self._rejouer([(0, 2.2), (6, 2.3), (12, 1.8)])
        self.assertIs(sortie["pluie_mesuree_active"], True)
        self.assertEqual(sortie["pluie_mesuree_minutes_depuis_hausse"], 6.0)
        self.assertEqual(coord._runtime_state["pluie_mesuree"]["pic"], 2.3)
        # Le cumul PUBLIÉ suit le cliquet lui aussi : afficher la lecture brute montrerait
        # au diagnostic une valeur que ni la garde ni le bilan sol n'utilisent.
        self.assertEqual(sortie["pluie_mesuree_cumul_mm"], 2.3)

    def test_une_remontee_sous_le_pic_du_jour_n_est_pas_une_averse(self) -> None:
        """⚠️ LE DÉFAUT DU 16/08/2026, trouvé deux heures après la livraison.

        Comparer à la LECTURE PRÉCÉDENTE prenait chaque remontée de bruit pour une pluie.
        Journée réelle, sans une goutte après 05:52 — le détecteur criait « il pleut »
        QUATRE fois (08:33, 12:38, 13:07, 14:25).
        """
        journee = [
            (0, 3.6), (30, 3.5), (161, 4.2), (220, 3.7), (280, 3.6), (334, 3.5),
            (388, 3.3), (394, 3.1), (406, 3.3), (435, 3.4), (447, 3.3), (453, 3.2),
            (513, 3.6),
        ]
        sortie, coord = self._rejouer(journee)
        # Seul le franchissement du maximum (4,2 à +161 min) horodate. La dernière lecture
        # est à +513 min, soit 352 min après — bien au-delà de la fenêtre de 30 min.
        self.assertIs(sortie["pluie_mesuree_active"], False)
        self.assertEqual(sortie["pluie_mesuree_minutes_depuis_hausse"], 352.0)
        self.assertEqual(coord._runtime_state["pluie_mesuree"]["pic"], 4.2)

    def test_une_vraie_remise_a_zero_repart_de_la_nouvelle_base(self) -> None:
        """La chute vers ~0 (minuit) relâche le cliquet, sinon il figerait la veille."""
        sortie, coord = self._rejouer([(0, 3.6), (6, 0.0), (12, 0.4)])
        self.assertEqual(coord._runtime_state["pluie_mesuree"]["pic"], 0.4)
        self.assertIs(sortie["pluie_mesuree_active"], True)

    def test_le_cliquet_n_est_pas_reecrit_ici(self) -> None:
        """⚠️ Deux implémentations de la même règle : l'une a déjà menti. Une seule source."""
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn("appliquer_cliquet_pluie(cumul, precedent)", source)
        self.assertIn("from .soil_balance import appliquer_cliquet_pluie", source)

    def test_la_nuit_du_16_aout(self) -> None:
        """Le cas réel : la garde doit mordre AVANT que la prévision ne bascule."""
        t0 = datetime(2026, 8, 16, 0, 12, tzinfo=timezone.utc)
        sortie, _ = self._rejouer(
            [(0, 0.1), (7, 0.3), (25, 0.6), (97, 1.0), (103, 1.2), (113, 1.8)],
            depart=t0,
        )
        self.assertIs(sortie["pluie_mesuree_active"], True)

    def test_un_suivi_casse_ne_fait_pas_tomber_le_cycle(self) -> None:
        coord = self._coord(datetime(2026, 8, 16, 2, 0, tzinfo=timezone.utc))
        coord._runtime_state = {"pluie_mesuree": {"dernier_cumul": "n'importe quoi"}}
        sortie = coord._suivre_pluie_mesuree(1.8)
        self.assertIn("pluie_mesuree_active", sortie)

    # ── la garde elle-même ────────────────────────────────────────────────────────────
    def test_la_mesure_prime_sur_une_prevision_qui_annonce_ciel_clair(self) -> None:
        """⚠️ LE DÉFAUT DU 16/08 : `clear-night` pendant qu'il pleut pour de bon."""
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        profil = {"weather_condition": "clear-night", "pluie_mesuree_active": True}
        self.assertTrue(guidance.is_active_rain_weather(profil))

    def test_sans_mesure_les_bras_meteo_decident_encore(self) -> None:
        """Aucune régression : le correctif AJOUTE une entrée, il n'en retire aucune."""
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        self.assertTrue(
            guidance.is_active_rain_weather(
                {"weather_condition": "rainy", "pluie_mesuree_active": None}
            )
        )
        self.assertTrue(
            guidance.is_active_rain_weather(
                {"weather_condition": "sunny", "weather_precipitation_probability": 90}
            )
        )

    def test_une_mesure_inconnue_ne_bloque_pas_a_elle_seule(self) -> None:
        """⚠️ `None` traité comme vrai bloquerait l'arrosage sur un capteur muet."""
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        for absence in (None, "unknown", ""):
            with self.subTest(absence=absence):
                self.assertFalse(
                    guidance.is_active_rain_weather(
                        {"weather_condition": "sunny", "pluie_mesuree_active": absence}
                    )
                )

    def test_une_mesure_seche_ne_debloque_pas_une_pluie_annoncee(self) -> None:
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        self.assertTrue(
            guidance.is_active_rain_weather(
                {"weather_condition": "pouring", "pluie_mesuree_active": False}
            )
        )

    # ── la LAME de l'épisode (0.83.0) ─────────────────────────────────────────────────
    def test_les_hausses_d_un_meme_episode_s_ADDITIONNENT(self) -> None:
        """« Il pleut » ne dit pas combien. La lame, si — et c'est elle qui dose le ressuyage."""
        sortie, _ = self._rejouer([(0, 1.0), (5, 1.3), (12, 1.9)])
        self.assertAlmostEqual(sortie["pluie_mesuree_lame_mm"], 0.9, places=2)

    def test_un_auget_TARDIF_ajoute_a_la_lame_au_lieu_de_l_EFFACER(self) -> None:
        """⚠️ LE BLOQUANT DU PREMIER JET, TROUVÉ PAR UNE REVUE ADVERSARIALE LE 09/09/2026.

        La lame était alors un « épisode » remis à zéro dès qu'une hausse arrivait après un trou
        d'une heure. Rejoué sur du code réel : 6,0 mm de 14:00 à 14:50, ressuyage armé jusqu'à
        17:50 — puis UN auget de traîne à 16:25 ramenait la lame à 0,1 mm, donc sous le minimum
        de 0,3, donc **ressuyage supprimé**. La tonte redevenait autorisée à 17:00 sur une
        pelouse ayant reçu 6,1 mm. Plus il pleuvait, moins on bloquait.

        Une hausse ne peut plus qu'AJOUTER. Ce qui sort du calcul en sort par le temps.
        """
        sortie, _ = self._rejouer([(0, 0.0), (50, 6.0), (145, 6.1)])
        self.assertAlmostEqual(
            sortie["pluie_mesuree_lame_mm"], 6.1, places=2,
            msg="l'auget de traîne a effacé les 6 mm de l'averse",
        )

    def test_une_bruine_FRACTIONNEE_s_additionne(self) -> None:
        """Trois augets séparés de plus d'une heure : aucun n'atteint le minimum, leur somme si.
        Avec l'ancien « épisode », chaque morceau repartait de zéro et rien n'armait jamais."""
        sortie, _ = self._rejouer([(0, 0.0), (30, 0.1), (110, 0.2), (190, 0.3)])
        self.assertAlmostEqual(sortie["pluie_mesuree_lame_mm"], 0.3, places=2)

    def test_la_lame_NE_MAIGRIT_PAS_pendant_le_delai_qu_elle_a_arme(self) -> None:
        """⚠️ RELEVÉ PAR LA REVUE CODEX SUR LA PR #49 — le trou de ma fenêtre glissante.

        Elle se mesurait depuis CHAQUE goutte, alors que le ressuyage court depuis la DERNIÈRE.
        Une averse qui dure voyait donc son début expirer pendant que le délai tournait encore :
        4 mm entre 12:00 et 14:00, puis à 16:00 la première moitié sort de la fenêtre, la lame
        retombe à ~2 mm, le délai calculé passe de 180 à ~107 min — déjà écoulés — et la tonte
        repart **une heure trop tôt**. La lame maigrissait pendant le délai qu'elle avait armé.

        On remonte désormais le temps depuis la dernière hausse jusqu'au premier trou plus long
        que la fenêtre : l'averse est prise entière, quelle que soit sa durée.
        """
        # 12:00 → 14:00, 4 mm par paliers réguliers (l'auget tique toutes les 20 min).
        lectures = [(0, 0.0)] + [(20 * i, round(0.667 * i, 2)) for i in range(1, 7)]
        pendant, coord = self._rejouer(lectures)
        self.assertAlmostEqual(pendant["pluie_mesuree_lame_mm"], 4.0, places=1,
                               msg="prémisse : les 4 mm de l'averse sont bien comptés")
        # ⚠️ ON LIT À t+330, PAS À t+240 — le premier jet du test ne mordait PAS. À deux heures
        # d'écart, les hausses de l'averse ont encore moins de 240 min et l'ancienne règle les
        # gardait aussi : le test passait au vert avec le défaut. Il faut se placer assez loin
        # pour que le DÉBUT de l'averse soit sorti de la fenêtre comptée depuis maintenant,
        # alors que la DERNIÈRE goutte (t+120) y est toujours — c'est exactement la situation
        # où le délai court encore et où la lame se mettait à maigrir.
        apres, _ = self._rejouer([(330, 4.0)], coord=coord)
        self.assertAlmostEqual(
            apres["pluie_mesuree_lame_mm"], 4.0, places=1,
            msg="la lame a maigri pendant le ressuyage : la tonte repart une heure trop tôt",
        )

    def test_une_averse_qui_DURE_reste_UN_evenement(self) -> None:
        """Six heures de pluie continue : un seul événement, pas quatre morceaux de fenêtre."""
        lectures = [(0, 0.0)] + [(30 * i, round(0.5 * i, 2)) for i in range(1, 13)]
        sortie, _ = self._rejouer(lectures)
        self.assertAlmostEqual(sortie["pluie_mesuree_lame_mm"], 6.0, places=1)

    def test_la_lame_SORT_de_la_fenetre_glissante(self) -> None:
        """⚠️ La borne est PINNÉE des deux côtés : sans ça, 8 min comme 64 min passeraient au
        vert et la fenêtre ne voudrait plus rien dire (relevé par la revue)."""
        dedans, _ = self._rejouer([(0, 0.0), (5, 3.0), (5 + 239, 3.0)])
        self.assertAlmostEqual(dedans["pluie_mesuree_lame_mm"], 3.0, places=2,
                               msg="la lame est sortie AVANT la fin de la fenêtre")
        dehors, _ = self._rejouer([(0, 0.0), (5, 3.0), (5 + 241, 3.0)])
        self.assertEqual(dehors["pluie_mesuree_lame_mm"], 0.0,
                         "la lame est restée APRÈS la fin de la fenêtre")

    def test_la_lame_du_voisin_SURVIT_a_une_coupure(self) -> None:
        _, coord = self._rejouer([(0, 0.0), (10, 2.0)])
        coupure, _ = self._rejouer([(20, None)], coord=coord)
        self.assertAlmostEqual(coupure["pluie_mesuree_lame_mm"], 2.0, places=2)
        self.assertIsNone(coupure["pluie_mesuree_active"], "prémisse : la lecture manque bien")

    def test_la_lame_SURVIT_jusqu_au_bout_du_ressuyage(self) -> None:
        """⚠️ Le ressuyage court jusqu'à trois heures APRÈS la dernière goutte : si la lame
        s'évanouissait avant, elle supprimerait le délai qu'elle a elle-même armé."""
        sortie, _ = self._rejouer([(0, 1.0), (5, 2.5), (185, 2.5)])
        self.assertAlmostEqual(sortie["pluie_mesuree_lame_mm"], 1.5, places=2)
        self.assertFalse(sortie["pluie_mesuree_active"], "prémisse : il ne pleut plus")

    def test_une_baisse_parasite_n_ajoute_RIEN_a_la_lame(self) -> None:
        """Le cliquet vaut pour la lame comme pour le reste : ce pluviomètre oscille (mesuré
        quatre fausses averses le 16/08/2026 en comparant à la lecture précédente).

        ⚠️ `0.0` et non `None` : le capteur RÉPOND, et ce qu'il dit c'est « rien dans la
        fenêtre ». L'absence de mesure, elle, se signale ailleurs — c'est le suivi entier qui
        est muet. La seconde moitié du test le prouve autrement : après le bruit, seule la
        vraie hausse entre dans la lame.
        """
        bruit, coord = self._rejouer([(0, 3.6), (5, 3.5), (10, 3.6), (15, 3.3), (20, 3.6)])
        self.assertEqual(bruit["pluie_mesuree_lame_mm"], 0.0)
        vraie, _ = self._rejouer([(25, 4.0)], coord=coord)
        self.assertAlmostEqual(
            vraie["pluie_mesuree_lame_mm"], 0.4, places=2,
            msg="le bruit des quatre oscillations s'est ajouté à la vraie hausse",
        )

    def test_les_deux_lames_sont_VISIBLES_et_pas_croisees(self) -> None:
        """⚠️ Sans elles à l'écran, « herbe mouillée » ne dit pas de quelle pluie il parle : le
        blocage du 09/09 a coûté une demi-heure de recherche pour cette seule raison. Et un test
        qui ne vérifie que leur PRÉSENCE laisse passer une inversion des deux sources."""
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._get_conf = lambda _cle: None
        sante = coordinator_mod.GazonIntelligentCoordinator._build_sensor_health(
            coord,
            temperature_source="capteur", humidite_capteur=None, vent_capteur=None,
            etp_capteur=None, pluie_24h_sensor=None, eto_hourly={},
            weather_profile={"pluie_mesuree_lame_mm": 0.1, "pluie_cumul_lame_mm": 4.2},
        )
        self.assertEqual(sante["pluie_lame_voisin_mm"], 0.1, "les deux sources sont croisées")
        self.assertEqual(sante["pluie_lame_station_mm"], 4.2, "les deux sources sont croisées")

    # ── le câblage, depuis la SORTIE RÉELLE ───────────────────────────────────────────
    def test_les_cles_publiees_traversent_advanced_context(self) -> None:
        """⚠️ On part des clés que le coordinateur produit VRAIMENT, pas d'une liste écrite ici.

        `compute_advanced_context` recopie la météo clé par clé (piège n°2 du projet) :
        une clé oubliée là meurt en silence, tests verts.
        """
        _, coord = self._rejouer([(0, 1.2), (6, 1.8)])
        produites = set(coord._suivre_pluie_mesuree(1.9))
        contexte = water_mod.compute_advanced_context(
            weather_profile={cle: True for cle in produites}
        )
        self.assertTrue(
            produites <= set(contexte),
            f"clés perdues dans advanced_context : {sorted(produites - set(contexte))}",
        )

    def test_la_garde_mord_par_le_chemin_advanced_context(self) -> None:
        """Le bout du câblage : de la mesure jusqu'au booléen, via le contexte réellement bâti."""
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        _, coord = self._rejouer([(0, 1.2), (6, 1.8)])
        profil = {"weather_condition": "clear-night", **coord._suivre_pluie_mesuree(1.9)}
        contexte = water_mod.compute_advanced_context(weather_profile=profil)
        self.assertTrue(guidance.is_active_rain_weather(contexte))

    def test_le_suivi_survit_a_un_redemarrage(self) -> None:
        """Non persisté, la garde repartirait aveugle en pleine averse."""
        _, coord = self._rejouer([(0, 1.2), (6, 1.8)])
        # ⚠️ Par `_serialized_runtime_state()`, la VRAIE méthode qui bâtit le dict persisté :
        # sérialiser la valeur à la main prouverait qu'elle est sérialisable, pas qu'elle
        # figure dans la liste blanche — un test qui survit à la suppression de la clé.
        coord._serialize_runtime_value = (
            coordinator_mod.GazonIntelligentCoordinator._serialize_runtime_value.__get__(coord)
        )
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        coord._runtime_state.setdefault("active_irrigation_session", None)
        coord._runtime_state.setdefault("last_irrigation_execution", None)
        serialise = coordinator_mod.GazonIntelligentCoordinator._serialized_runtime_state(coord)
        self.assertIn("pluie_mesuree", serialise, "le suivi n'atteint pas le disque")

        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(
            relu._runtime_state["pluie_mesuree"]["pic"],
            coord._runtime_state["pluie_mesuree"]["pic"],
        )
        self.assertIsNotNone(relu._runtime_state["pluie_mesuree"]["derniere_hausse"])

    def test_la_garde_mesuree_est_visible_dans_sensor_health(self) -> None:
        """Un garde muet est indiscernable d'un garde cassé — celui-ci l'a été des mois."""
        _, coord = self._rejouer([(0, 1.2), (6, 1.8)])
        coord._get_conf = lambda _cle: None
        profil = coord._suivre_pluie_mesuree(1.9)
        sante = coordinator_mod.GazonIntelligentCoordinator._build_sensor_health(
            coord,
            temperature_source="capteur",
            humidite_capteur=None,
            vent_capteur=None,
            etp_capteur=None,
            pluie_24h_sensor=1.9,
            weather_profile=profil,
            eto_hourly={},
        )
        self.assertIs(sante["pluie_mesuree_active"], True)
        self.assertEqual(sante["pluie_mesuree_minutes_depuis_hausse"], 0.0)

    def test_la_garde_est_nourrie_par_le_capteur_pas_par_la_prevision(self) -> None:
        """⚠️ Le repli prévision de `pluie_24h` ramènerait l'aveuglement qu'on vient de corriger."""
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn(
            "weather_profile.update(self._suivre_pluie_mesuree(pluie_24h_sensor))",
            source,
        )


class RecommandationIgnoreeTests(unittest.TestCase):
    """Le compteur du SILENCE D'EN FACE : recommandé, prêt, au garage… et rien ne part.

    ⚠️ POURQUOI. Le déclencheur de la tonte vit dans Node-RED, hors de cette intégration.
    Coupé, l'intégration recommande dans le vide et rien ne le signale. Deux fois en 2026 :
    le nœud de déclaration éteint du 30/07 au 06/08, et l'onglet Tondeuse désactivé qui a
    laissé filer 1 h 49 de fenêtre idéale le 21/08 — `action_possible` vrai à 10:01, machine
    prête et au garage, aucun départ jusqu'à 11:50.

    ⚠️ IL N'ALIMENTE AUCUNE DÉCISION. Un compteur de silence qui relâcherait un garde-fou
    serait pire que le silence. Un test le verrouille.
    """

    def _coord(self, instant, *, action_possible=True, runtime=None):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = runtime if runtime is not None else {}
        coord._current_datetime = lambda: instant
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        coord._booleen_publie_au_cycle_precedent = lambda _cle: action_possible
        return coord

    def _ctx(self, *, garage=True, coordination=True):
        return {"mower_is_docked": garage, "mower_coordination_enabled": coordination}

    def _rejouer(self, etapes, *, action_possible=True, depart=None):
        t0 = depart or datetime(2026, 8, 21, 10, 1, tzinfo=timezone.utc)
        coord = self._coord(t0, action_possible=action_possible)
        sortie = {}
        for minutes, ctx in etapes:
            instant = t0 + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            sortie = coord._suivre_recommandation_ignoree(dict(ctx))
        return sortie, coord

    def test_le_premier_cycle_demarre_le_compteur_a_zero(self) -> None:
        sortie, _ = self._rejouer([(0, self._ctx())])
        self.assertEqual(sortie["mower_recommendation_ignored_minutes"], 0.0)
        self.assertIs(sortie["mower_recommendation_ignored"], False)

    def test_la_latence_normale_ne_declenche_rien(self) -> None:
        """Mesurée le 16/08 et le 19/08 : 6 minutes entre l'autorisation et le départ."""
        sortie, _ = self._rejouer([(0, self._ctx()), (6, self._ctx())])
        self.assertEqual(sortie["mower_recommendation_ignored_minutes"], 6.0)
        self.assertIs(sortie["mower_recommendation_ignored"], False)

    def test_la_matinee_du_21_aout(self) -> None:
        """1 h 49 de fenêtre idéale sans départ : c'est exactement ce qu'il doit voir."""
        sortie, _ = self._rejouer([(0, self._ctx()), (30, self._ctx()), (109, self._ctx())])
        self.assertEqual(sortie["mower_recommendation_ignored_minutes"], 109.0)
        self.assertIs(sortie["mower_recommendation_ignored"], True)

    def test_le_seuil_mord_a_trente_minutes(self) -> None:
        for minutes, attendu in ((29.0, False), (30.0, True)):
            with self.subTest(minutes=minutes):
                sortie, _ = self._rejouer([(0, self._ctx()), (minutes, self._ctx())])
                self.assertIs(sortie["mower_recommendation_ignored"], attendu)

    def test_elle_sort_et_le_compteur_repart(self) -> None:
        """Quelqu'un a écouté : plus rien à signaler, et le silence suivant repart de zéro."""
        sortie, coord = self._rejouer([
            (0, self._ctx()), (40, self._ctx()), (41, self._ctx(garage=False)),
        ])
        self.assertIs(sortie["mower_recommendation_ignored"], False)
        self.assertNotIn("mower_recommendation_ignored_since", coord._runtime_state)

    def test_coordination_coupee_le_compteur_se_tait(self) -> None:
        """⚠️ Couper la coordination est une DÉCISION de l'utilisateur, pas une panne."""
        sortie, coord = self._rejouer([
            (0, self._ctx()), (40, self._ctx()), (41, self._ctx(coordination=False)),
        ])
        self.assertIsNone(sortie["mower_recommendation_ignored"])
        self.assertIsNone(sortie["mower_recommendation_ignored_minutes"])
        self.assertNotIn("mower_recommendation_ignored_since", coord._runtime_state)

    def test_sans_decision_publiee_on_ne_conclut_rien(self) -> None:
        """⚠️ `None` = aucune décision calculée. Une absence, pas « rien n'est recommandé »."""
        sortie, _ = self._rejouer([(0, self._ctx())], action_possible=None)
        self.assertIsNone(sortie["mower_recommendation_ignored"])

    def test_rien_de_recommande_n_est_pas_un_silence(self) -> None:
        sortie, _ = self._rejouer([(0, self._ctx())], action_possible=False)
        self.assertIs(sortie["mower_recommendation_ignored"], False)
        self.assertIsNone(sortie["mower_recommendation_ignored_minutes"])

    def test_le_compteur_survit_a_un_redemarrage(self) -> None:
        """C'est sur la DURÉE qu'il alerte : un redémarrage ne doit pas la remettre à zéro."""
        _, coord = self._rejouer([(0, self._ctx()), (40, self._ctx())])
        coord._serialize_runtime_value = (
            coordinator_mod.GazonIntelligentCoordinator._serialize_runtime_value.__get__(coord)
        )
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        coord._runtime_state.setdefault("active_irrigation_session", None)
        coord._runtime_state.setdefault("last_irrigation_execution", None)
        serialise = coordinator_mod.GazonIntelligentCoordinator._serialized_runtime_state(coord)
        self.assertIn("mower_recommendation_ignored_since", serialise)

        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(
            relu._runtime_state["mower_recommendation_ignored_since"],
            coord._runtime_state["mower_recommendation_ignored_since"],
        )

    def test_les_cles_atteignent_le_capteur(self) -> None:
        """⚠️ On part des clés RÉELLEMENT produites, pas d'une liste recopiée ici.

        Le contexte tondeuse traverse deux filtres qui ne gardent que `mower_`/`tondeuse_` :
        une clé mal préfixée meurt en silence, déclarée partout et absente du capteur.
        """
        sortie, _ = self._rejouer([(0, self._ctx()), (40, self._ctx())])
        produites = set(sortie)
        self.assertTrue(
            all(cle.startswith("mower_") for cle in produites),
            f"préfixe fatal : {sorted(c for c in produites if not c.startswith('mower_'))}",
        )
        coord_src = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        capteur_src = (PACKAGE_DIR / "sensor.py").read_text(encoding="utf-8")
        for cle in produites:
            with self.subTest(cle=cle):
                self.assertIn(f'"{cle}",', coord_src)
                self.assertIn(f'"{cle}",', capteur_src)

    def test_la_lecture_du_cycle_precedent_va_chercher_dans_extra(self) -> None:
        """⚠️ `action_possible` n'est PAS un membre de `DecisionResult` : il vit dans `extra`.

        Sans la lecture de `extra`, le détecteur lirait `None` à chaque cycle et ne se
        déclencherait JAMAIS — muet, donc indiscernable d'un détecteur qui marche.
        """
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        lire = coordinator_mod.GazonIntelligentCoordinator._booleen_publie_au_cycle_precedent

        class _Resultat:
            tonte_autorisee = True          # membre direct
            extra = {"action_possible": True}   # uniquement dans extra

        coord.brain = types.SimpleNamespace(last_result=_Resultat())
        self.assertIs(lire(coord, "action_possible"), True, "extra n'est pas lu")
        self.assertIs(lire(coord, "tonte_autorisee"), True, "l'attribut direct n'est plus lu")
        self.assertIsNone(lire(coord, "cle_inexistante"))

        coord.brain = types.SimpleNamespace(last_result=None)
        self.assertIsNone(lire(coord, "action_possible"))

    def test_il_est_appele_dans_le_cycle(self) -> None:
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn(
            "mower_context.update(self._suivre_recommandation_ignoree(mower_context))", source
        )

    def test_il_n_alimente_aucune_decision(self) -> None:
        """⚠️ Le jour où une décision voudra le lire, ce test tombera et forcera la discussion."""
        for module in ("decision_mowing.py", "guidance.py", "decision.py", "decision_watering.py"):
            with self.subTest(module=module):
                self.assertNotIn(
                    "mower_recommendation_ignored",
                    (PACKAGE_DIR / module).read_text(encoding="utf-8"),
                )


class PasseHorsCoordinationTests(unittest.TestCase):
    """« Rappelée » suppose qu'il y ait eu une autorisation À RETIRER.

    ⚠️ POURQUOI. Mesuré le 22/08/2026 : passe de 73 min lancée à la main le soir, coordination
    coupée, `tonte_autorisee` faux du début à la fin. Elle est rentrée à **51 %** sur un
    travail réellement terminé — la seule réponse mesurée à « à quel niveau estime-t-elle
    avoir fini ». Le carnet l'a étiquetée `rappelee`, donc exclue de
    `mower_autonomous_return_battery_median`, qui est resté vide.
    """

    def _coord(self, instant, *, autorisee=None):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = {}
        coord._current_datetime = lambda: instant
        coord._current_date = lambda: instant.date()
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        coord._minutes_creditables = (
            coordinator_mod.GazonIntelligentCoordinator._minutes_creditables.__get__(coord)
        )
        coord._tonte_autorisee_au_cycle_precedent = lambda: autorisee
        return coord

    def _ctx(self, *, garage=False, tonte=False, batterie=None):
        return {"tondeuse_connectee": True, "tondeuse_erreur": None,
                "mower_is_mowing": tonte, "mower_is_docked": garage, "mower_battery": batterie}

    def _rejouer(self, etapes, *, autorisee):
        t0 = datetime(2026, 8, 22, 19, 50, tzinfo=timezone.utc)
        coord = self._coord(t0, autorisee=autorisee)
        for minutes, ctx in etapes:
            instant = t0 + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            coord._current_date = lambda t=instant: t.date()
            coord._suivre_passes_tondeuse(dict(ctx))
        return coord._runtime_state["mower_passes"]["journal"][-1]

    def test_jamais_autorisee_n_est_pas_un_rappel(self) -> None:
        """⚠️ LE CAS DU 22/08 : personne ne l'a rappelée, elle a fini son travail."""
        passe = self._rejouer([
            (0, self._ctx(garage=True, batterie=97)),
            (1, self._ctx(tonte=True, batterie=97)),
            (72, self._ctx(tonte=True, batterie=51)),
            (73, self._ctx(garage=True, batterie=51)),
        ], autorisee=False)
        self.assertEqual(passe["fin_motif"], "retour_autonome")
        self.assertIs(passe["hors_coordination"], True)
        self.assertEqual(passe["batterie_fin"], 51)

    def test_autorisee_puis_interdite_reste_un_rappel(self) -> None:
        """⚠️ Le cas du 13/08 ne doit PAS régresser : autorisée, puis la chaleur l'interdit."""
        t0 = datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc)
        coord = self._coord(t0, autorisee=True)
        etapes = [
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (39, self._ctx(tonte=True, batterie=58)),
        ]
        for minutes, ctx in etapes:
            instant = t0 + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            coord._current_date = lambda t=instant: t.date()
            coord._suivre_passes_tondeuse(dict(ctx))
        # L'autorisation tombe, puis elle rentre.
        coord._tonte_autorisee_au_cycle_precedent = lambda: False
        for minutes, ctx in [(40, self._ctx(tonte=True, batterie=58)),
                             (41, self._ctx(garage=True, batterie=58))]:
            instant = t0 + timedelta(minutes=minutes)
            coord._current_datetime = lambda t=instant: t
            coord._current_date = lambda t=instant: t.date()
            coord._suivre_passes_tondeuse(dict(ctx))
        passe = coord._runtime_state["mower_passes"]["journal"][-1]
        self.assertEqual(passe["fin_motif"], "rappelee")
        self.assertIs(passe["hors_coordination"], False)

    def test_la_batterie_vide_prime_toujours(self) -> None:
        passe = self._rejouer([
            (0, self._ctx(garage=True, batterie=100)),
            (1, self._ctx(tonte=True, batterie=100)),
            (88, self._ctx(tonte=True, batterie=11)),
            (89, self._ctx(garage=True, batterie=11)),
        ], autorisee=False)
        self.assertEqual(passe["fin_motif"], "batterie_vide")


class ProgressionTonteTests(unittest.TestCase):
    """La progression du TRAVAIL, publiée sans qu'elle décide de rien.

    ⚠️ Le carnet compte des PASSES ; il n'a jamais su ce qu'est un TRAVAIL. Le `task_id`
    survit à la recharge, donc il recolle deux passes en un seul travail.
    """

    def _coord(self, etat, *, mower="lawn_mower.esperance_jr"):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._resolve_mower_selection = lambda: {"entity_id": mower}
        coord.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda eid: etat.get(eid))
        )
        return coord

    def test_la_progression_est_lue_sur_l_entite_derivee(self) -> None:
        etat = {"sensor.esperance_jr_progression_de_la_tonte": types.SimpleNamespace(
            state="100", attributes={"task_id": "a7de6def", "task_status": 2})}
        sortie = coordinator_mod.GazonIntelligentCoordinator._lire_progression_tonte(self._coord(etat))
        self.assertEqual(sortie["mower_job_progress_pct"], 100.0)
        self.assertEqual(sortie["mower_job_id"], "a7de6def")
        self.assertEqual(sortie["mower_job_status_raw"], 2)

    def test_sans_entite_la_reponse_est_une_absence(self) -> None:
        """⚠️ Le suffixe dépend de la langue : absente, on ne conclut rien."""
        sortie = coordinator_mod.GazonIntelligentCoordinator._lire_progression_tonte(self._coord({}))
        self.assertIsNone(sortie["mower_job_progress_pct"])
        self.assertIsNone(sortie["mower_job_id"])

    def test_une_valeur_illisible_ne_devient_pas_zero(self) -> None:
        etat = {"sensor.esperance_jr_progression_de_la_tonte": types.SimpleNamespace(
            state="unavailable", attributes={})}
        sortie = coordinator_mod.GazonIntelligentCoordinator._lire_progression_tonte(self._coord(etat))
        self.assertIsNone(sortie["mower_job_progress_pct"])

    def test_les_cles_atteignent_le_capteur(self) -> None:
        etat = {"sensor.esperance_jr_progression_de_la_tonte": types.SimpleNamespace(
            state="34", attributes={"task_id": "x", "task_status": 2})}
        produites = set(coordinator_mod.GazonIntelligentCoordinator._lire_progression_tonte(self._coord(etat)))
        self.assertTrue(all(c.startswith("mower_") for c in produites), sorted(produites))
        coord_src = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        capteur_src = (PACKAGE_DIR / "sensor.py").read_text(encoding="utf-8")
        for cle in produites:
            with self.subTest(cle=cle):
                self.assertIn(f'"{cle}",', coord_src)
                self.assertIn(f'"{cle}",', capteur_src)

    def test_elle_est_appelee_dans_le_cycle(self) -> None:
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn("mower_context.update(self._lire_progression_tonte())", source)

    def test_elle_n_alimente_aucune_decision(self) -> None:
        """⚠️ Deux inconnues l'interdisent : le vocabulaire de `task_status`, et le
        comportement sur une coupe de bordure. Ce test tombera si on l'oublie."""
        for module in ("decision_mowing.py", "guidance.py", "decision.py", "decision_watering.py"):
            with self.subTest(module=module):
                self.assertNotIn("mower_job_", (PACKAGE_DIR / module).read_text(encoding="utf-8"))


class PluieActuelleTests(unittest.TestCase):
    """Pleut-il MAINTENANT — dit par un capteur, pas déduit d'un cumul.

    ⚠️ POURQUOI ELLE EXISTE. Tout l'appareillage actuel — détecteur de hausse, cliquet,
    horodatage sur la dernière hausse — approxime « pleut-il ? » à partir d'un CUMUL
    journalier. Un cumul ne le dit pas : 3,6 mm y restent affichés toute la journée après
    l'averse. De là viennent la fausse averse du 16/08 et celle du 29/08.

    ⚠️ OBSERVATION SEULE : publiée à côté de `pluie_mesuree_active` pour comparaison, elle
    n'alimente aucune décision tant qu'on ne l'a pas vue vivre sur plusieurs averses.
    """

    def _coord(self, etat, *, configure="sensor.pluie_actuelle"):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._get_conf = lambda cle: configure if cle == "capteur_pluie_actuelle" else None
        coord._get_float_state = lambda eid: etat.get(eid)
        return coord

    def _lire(self, coord):
        return coordinator_mod.GazonIntelligentCoordinator._lire_pluie_actuelle(coord)

    def test_zero_veut_dire_il_ne_pleut_pas(self) -> None:
        sortie = self._lire(self._coord({"sensor.pluie_actuelle": 0.0}))
        self.assertIs(sortie["pluie_actuelle_active"], False)
        self.assertEqual(sortie["pluie_actuelle_mm"], 0.0)

    def test_une_valeur_non_nulle_veut_dire_il_pleut(self) -> None:
        sortie = self._lire(self._coord({"sensor.pluie_actuelle": 0.3}))
        self.assertIs(sortie["pluie_actuelle_active"], True)
        self.assertEqual(sortie["pluie_actuelle_mm"], 0.3)

    def test_le_29_aout_elle_aurait_evite_la_fausse_averse(self) -> None:
        """⚠️ À 12:23 le cliquet a cru à une averse ; ce capteur affichait 0,0 depuis 10:11."""
        sortie = self._lire(self._coord({"sensor.pluie_actuelle": 0.0}))
        self.assertIs(sortie["pluie_actuelle_active"], False)

    def test_sans_capteur_configure_on_ne_conclut_rien(self) -> None:
        """⚠️ Une absence n'est pas « il ne pleut pas »."""
        sortie = self._lire(self._coord({}, configure=None))
        self.assertIsNone(sortie["pluie_actuelle_active"])
        self.assertIsNone(sortie["pluie_actuelle_mm"])

    def test_un_capteur_illisible_ne_devient_pas_zero(self) -> None:
        sortie = self._lire(self._coord({"sensor.pluie_actuelle": None}))
        self.assertIsNone(sortie["pluie_actuelle_active"])

    def test_elle_est_lue_dans_le_cycle_et_publiee(self) -> None:
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn("weather_profile.update(self._lire_pluie_actuelle())", source)
        for cle in ("pluie_actuelle_mm", "pluie_actuelle_active"):
            with self.subTest(cle=cle):
                self.assertIn(f'"{cle}": weather_profile.get("{cle}")', source)

    def test_elle_n_alimente_aucune_decision(self) -> None:
        """⚠️ Le jour où une décision voudra la lire, ce test tombera et forcera la discussion."""
        for module in ("decision_mowing.py", "guidance.py", "decision.py", "decision_watering.py"):
            with self.subTest(module=module):
                self.assertNotIn("pluie_actuelle", (PACKAGE_DIR / module).read_text(encoding="utf-8"))

    def test_l_entree_de_configuration_est_offerte_dans_les_deux_formulaires(self) -> None:
        """Sans ça, la clé existe dans le code mais reste inatteignable depuis l'interface."""
        flow = (PACKAGE_DIR / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("CONF_CAPTEUR_PLUIE_ACTUELLE", flow)
        self.assertIn("vol.Optional(CONF_CAPTEUR_PLUIE_ACTUELLE", flow)


class UnitesDesCapteursTests(unittest.TestCase):
    """Le vent et la pression sont normalisés À LA LECTURE, d'après l'unité déclarée.

    ⚠️ DÉFAUT PRÉEXISTANT. `wind_unit_raw = "km/h" if vent is not None else ...` : dès qu'un
    capteur de vent était configuré, le code SUPPOSAIT des km/h et ne lisait jamais son unité.
    Juste par chance avec le Netatmo. Avec un capteur en m/s — le Shelly WS90 publie ainsi —
    l'ET0 divisait par 3,6 une valeur déjà en m/s, et les seuils de tonte (20 et 40 km/h)
    devenaient inatteignables : un vent réel de 40 km/h vaut 11 m/s.
    """

    def _coord(self, valeur, unite, *, cle):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        etat = types.SimpleNamespace(
            state=str(valeur),
            attributes={"unit_of_measurement": unite} if unite else {},
        )
        coord.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda eid: etat if eid == cle else None)
        )
        return coord

    def _unite(self, coord, cle):
        return coordinator_mod.GazonIntelligentCoordinator._get_state_unit(coord, cle)

    def test_l_unite_declaree_est_lue(self) -> None:
        coord = self._coord(11.1, "m/s", cle="sensor.vent")
        self.assertEqual(self._unite(coord, "sensor.vent"), "m/s")

    def test_une_unite_absente_ne_casse_rien(self) -> None:
        coord = self._coord(20.0, None, cle="sensor.vent")
        self.assertIsNone(self._unite(coord, "sensor.vent"))
        self.assertIsNone(self._unite(coord, "sensor.inexistant"))

    # ── vent ──────────────────────────────────────────────────────────────────────────
    def test_un_vent_en_ms_devient_des_kmh(self) -> None:
        """⚠️ LE PIÈGE DU WS90 : 11,1 m/s = 40 km/h, soit le seuil de blocage."""
        self.assertAlmostEqual(water_mod.wind_speed_to_kmh(11.1, "m/s"), 39.96, places=2)

    def test_un_vent_deja_en_kmh_ne_bouge_pas(self) -> None:
        for unite in ("km/h", None, "", "unité inconnue"):
            with self.subTest(unite=unite):
                self.assertAlmostEqual(water_mod.wind_speed_to_kmh(20.0, unite), 20.0, places=6)

    def test_le_plancher_de_penman_ne_fuit_pas_dans_les_seuils_de_tonte(self) -> None:
        """⚠️ Les 0,5 m/s de `wind_speed_to_ms` servent la formule, pas la décision de tondre."""
        self.assertAlmostEqual(water_mod.wind_speed_to_kmh(0.0, "km/h"), 0.0, places=6)
        self.assertAlmostEqual(water_mod.wind_speed_to_ms(0.0, "km/h"), 0.5, places=6)

    def test_la_conversion_vers_les_ms_est_inchangee(self) -> None:
        """Garde-fou de non-régression : l'ET0 doit voir exactement ce qu'elle voyait."""
        for valeur, unite, attendu in (
            (36.0, "km/h", 10.0), (10.0, "m/s", 10.0), (10.0, "mph", 4.4704), (36.0, None, 10.0),
        ):
            with self.subTest(unite=unite):
                self.assertAlmostEqual(water_mod.wind_speed_to_ms(valeur, unite), attendu, places=4)

    # ── pression ──────────────────────────────────────────────────────────────────────
    def test_une_pression_en_kpa_devient_des_hpa(self) -> None:
        """⚠️ Le WS90 publie des kPa ; la chaîne ET0 divise par 10 en supposant des hPa."""
        self.assertAlmostEqual(water_mod.pression_vers_hpa(101.3, "kPa"), 1013.0, places=3)

    def test_une_pression_deja_en_hpa_ne_bouge_pas(self) -> None:
        for unite in ("hPa", "mbar", None, "", "inconnue"):
            with self.subTest(unite=unite):
                self.assertAlmostEqual(water_mod.pression_vers_hpa(1013.0, unite), 1013.0, places=6)

    # ── câblage ───────────────────────────────────────────────────────────────────────
    def test_les_deux_sont_normalises_a_la_lecture(self) -> None:
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn("_wind_speed_to_kmh(vent_capteur, self._get_state_unit(_vent_entite))", source)
        self.assertIn("_pression_vers_hpa(pressure, self._get_state_unit(_pression_entite))", source)

    def test_la_table_d_unites_n_est_pas_dupliquee(self) -> None:
        """⚠️ Deux tables d'unités finiraient par diverger : une seule source."""
        src = (PACKAGE_DIR / "water.py").read_text(encoding="utf-8")
        self.assertEqual(src.count('"mph", "mi/h"'), 1, "la table de vent est écrite deux fois")
        self.assertIn("facteur_vent_vers_ms(unit)", src)


class PluieDuJourDepuisCumulTests(unittest.TestCase):
    """Total du jour dérivé d'un compteur cumulatif qui ne se réinitialise jamais.

    ⚠️ POURQUOI. Le compteur du WS90 ne repart pas à zéro à minuit, ET il chute parfois
    brutalement à 0 avant de revenir à sa valeur — trames corrompues documentées, simultanées
    à des rafales à plus de 25 000 km/h. Un `utility_meter` branché dessus compte ces
    remontées comme de la pluie : 250 mm d'un coup.
    """

    T0 = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

    def _coord(self, jour=date(2026, 9, 1), runtime=None):
        """⚠️ L'HORLOGE EST PILOTÉE, et ce n'était pas le cas au premier jet. Sans elle, toutes
        les lectures d'un même test tombaient à la même seconde réelle : la branche qui fait
        VIEILLIR la lame n'était jamais atteinte, et trois tests passaient au vert sans jamais
        l'exercer. Faux vert relevé par la revue du 09/09/2026."""
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord._runtime_state = runtime if runtime is not None else {}
        coord._current_date = lambda: jour
        coord._instant = self.T0
        coord._current_datetime = lambda: coord._instant
        coord._parse_datetime_value = (
            coordinator_mod.GazonIntelligentCoordinator._parse_datetime_value.__get__(coord)
        )
        coord._get_conf = lambda cle: "sensor.cumul" if cle == "capteur_pluie_cumul" else None
        coord._lectures = []
        coord._get_float_state = lambda _e: coord._lectures.pop(0) if coord._lectures else None
        return coord

    def _rejouer(self, lectures, *, coord=None, jour=date(2026, 9, 1)):
        """`lectures` : des valeurs, ou des couples (minutes depuis T0, valeur)."""
        coord = coord or self._coord(jour)
        sortie = {}
        for item in lectures:
            if isinstance(item, tuple):
                minutes, v = item
                coord._instant = self.T0 + timedelta(minutes=minutes)
            else:
                v = item
            coord._lectures = [v]
            sortie = coordinator_mod.GazonIntelligentCoordinator._suivre_pluie_du_jour(coord)
        return sortie, coord

    def test_une_vraie_pluie_est_comptee(self) -> None:
        sortie, _ = self._rejouer([250.0, 250.4, 251.0])
        self.assertAlmostEqual(sortie["pluie_cumul_jour_mm"], 1.0, places=2)

    def test_la_lame_de_l_episode_est_comptee_pour_la_station(self) -> None:
        """⚠️ C'est CETTE station qui est sur la pelouse. Le 09/09/2026 elle n'a rien mesuré
        pendant que celle du voisin armait trois heures de ressuyage ; l'inverse arrivera, et
        alors c'est elle qui doit commander la durée."""
        sortie, _ = self._rejouer([250.0, 250.4, 251.0])
        self.assertAlmostEqual(sortie["pluie_cumul_lame_mm"], 1.0, places=2)

    def test_la_lame_de_la_station_ignore_un_gain_ABERRANT(self) -> None:
        """Un saut impossible en deux minutes n'entre pas plus dans la lame que dans le total :
        sinon le ressuyage partirait au maximum sur une trame corrompue."""
        sortie, _ = self._rejouer([250.0, 400.0])
        self.assertEqual(
            sortie["pluie_cumul_lame_mm"], 0.0,
            "un gain rejeté a quand même nourri la lame",
        )
        self.assertGreater(sortie["pluie_gain_rejete_mm"], 0.0, "prémisse : le gain est rejeté")

    def test_le_total_derive_NE_PRIME_PAS_sans_reference(self) -> None:
        """⚠️ RELEVÉ PAR LA REVUE CODEX SUR LA PR #49, et c'est un vrai trou.

        Au tout premier cycle — installation neuve, ou état d'exécution persisté perdu — le
        compteur s'initialise sur la lecture courante et le total du jour vaut 0. Or depuis la
        0.79.0 ce total a la PRIORITÉ sur `capteur_pluie_24h` : un zéro sans référence écrasait
        donc un capteur qui savait, lui, qu'il était tombé 10 mm le matin. Le bilan du sol
        perdait la pluie de la journée entière, et pouvait lancer un arrosage inutile.
        """
        premier, coord = self._rejouer([(0, 250.0)])
        self.assertIsNone(
            premier["pluie_cumul_jour_mm"],
            "un total de zéro SANS référence écrase le capteur 24 h qui, lui, sait",
        )
        # Dès le cycle suivant la référence existe : le total dérivé redevient légitime.
        suivant, _ = self._rejouer([(2, 250.0)], coord=coord)
        self.assertEqual(suivant["pluie_cumul_jour_mm"], 0.0,
                         "avec une référence, un vrai zéro doit être annoncé")
        pluie, _ = self._rejouer([(10, 251.4)], coord=coord)
        self.assertAlmostEqual(pluie["pluie_cumul_jour_mm"], 1.4, places=2)

    def test_la_lame_de_la_station_SURVIT_a_une_coupure(self) -> None:
        """⚠️ DEUXIÈME BLOQUANT TROUVÉ PAR LA REVUE. La station tombe en `unavailable` par
        à-coups — 16 minutes autour du basculement du 09/09, justement. Tant que la lame
        disparaissait avec la lecture, le maximum des deux retombait sur le seul voisin : une
        averse mesurée ICI s'évanouissait, et le ressuyage qu'elle avait armé avec elle."""
        _, coord = self._rejouer([(0, 250.0), (10, 252.5)])
        coupure, _ = self._rejouer([(20, None)], coord=coord)
        self.assertAlmostEqual(
            coupure["pluie_cumul_lame_mm"], 2.5, places=2,
            msg="la coupure du capteur a effacé 2,5 mm réellement mesurés",
        )
        self.assertIsNone(coupure["pluie_cumul_jour_mm"], "prémisse : la lecture manque bien")

    def test_la_lame_de_la_station_VIEILLIT_et_sort_de_la_fenetre(self) -> None:
        sortie, coord = self._rejouer([(0, 250.0), (5, 253.0)])
        self.assertAlmostEqual(sortie["pluie_cumul_lame_mm"], 3.0, places=2)
        vieux, _ = self._rejouer([(300, None)], coord=coord)
        self.assertEqual(vieux["pluie_cumul_lame_mm"], 0.0,
                         "une pluie de cinq heures pèse encore sur le ressuyage")

    def test_la_chute_parasite_a_zero_ne_compte_rien(self) -> None:
        """⚠️ LE PIÈGE DU WS90 : 250 → 0 → 250 ne doit ajouter aucun millimètre."""
        sortie, _ = self._rejouer([250.0, 0.0, 250.0])
        self.assertEqual(sortie["pluie_cumul_jour_mm"], 0.0)
        self.assertEqual(sortie["pluie_cumul_pic_mm"], 250.0, "le maximum ne doit pas redescendre")

    def test_la_pluie_apres_une_chute_parasite_est_bien_comptee(self) -> None:
        sortie, _ = self._rejouer([250.0, 0.0, 250.0, 250.6])
        self.assertAlmostEqual(sortie["pluie_cumul_jour_mm"], 0.6, places=2)

    def test_une_chute_parasite_SOUS_le_plafond_ne_compte_rien(self) -> None:
        """⚠️ Le cas qui prouve que c'est bien le MAXIMUM qui protège, pas le plafond.

        Avec 250 → 0 → 250, le plafond de plausibilité (30 mm) rejette la remontée et masque
        l'absence de maximum : le test passe même si le maximum est cassé. Avec 20 → 0 → 20,
        la remontée est sous le plafond — seul le maximum peut l'écarter.
        """
        sortie, _ = self._rejouer([20.0, 0.0, 20.0])
        self.assertEqual(sortie["pluie_cumul_jour_mm"], 0.0)
        self.assertEqual(sortie["pluie_gain_rejete_mm"], 0.0, "rien ne devait être rejeté non plus")
        self.assertEqual(sortie["pluie_cumul_pic_mm"], 20.0)

    def test_elle_est_appelee_dans_le_cycle(self) -> None:
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn("weather_profile.update(self._suivre_pluie_du_jour())", source)

    def test_un_saut_impossible_est_rejete_mais_trace(self) -> None:
        """⚠️ Un rejet silencieux serait indiscernable d'une panne : on garde la trace."""
        sortie, _ = self._rejouer([250.0, 900.0])
        self.assertEqual(sortie["pluie_cumul_jour_mm"], 0.0)
        self.assertAlmostEqual(sortie["pluie_gain_rejete_mm"], 650.0, places=1)

    def test_le_total_repart_a_zero_a_notre_minuit(self) -> None:
        """⚠️ NOTRE horloge : le capteur, lui, ne se réinitialise jamais."""
        _sortie, coord = self._rejouer([250.0, 252.0])
        coord._current_date = lambda: date(2026, 9, 2)
        sortie, _ = self._rejouer([253.0], coord=coord)
        self.assertAlmostEqual(sortie["pluie_cumul_jour_mm"], 1.0, places=2)
        self.assertEqual(sortie["pluie_cumul_pic_mm"], 253.0, "le maximum, lui, ne se remet pas à zéro")

    def test_sans_capteur_on_ne_conclut_rien(self) -> None:
        coord = self._coord(); coord._get_conf = lambda _c: None
        sortie = coordinator_mod.GazonIntelligentCoordinator._suivre_pluie_du_jour(coord)
        self.assertIsNone(sortie["pluie_cumul_jour_mm"])

    def test_les_deux_memoires_survivent_a_un_redemarrage(self) -> None:
        """Sans persistance, une chute parasite suivie d'un redémarrage recompterait tout."""
        _sortie, coord = self._rejouer([250.0, 251.0])
        coord._serialize_runtime_value = (
            coordinator_mod.GazonIntelligentCoordinator._serialize_runtime_value.__get__(coord)
        )
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        coord._runtime_state.setdefault("active_irrigation_session", None)
        coord._runtime_state.setdefault("last_irrigation_execution", None)
        serialise = coordinator_mod.GazonIntelligentCoordinator._serialized_runtime_state(coord)
        self.assertIn("pluie_cumul", serialise, "le suivi n'atteint pas le disque")
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(relu._runtime_state["pluie_cumul"]["pic"], 251.0)

    def test_elle_alimente_MAINTENANT_le_bilan_du_sol(self) -> None:
        """⚠️ CE TEST EN REMPLACE UN AUTRE, ET IL FAUT DIRE POURQUOI.

        Il existait ici `test_elle_n_alimente_aucune_decision`, qui vérifiait l'absence de
        `pluie_cumul_jour_mm` dans les quatre modules de décision, avec cette promesse :
        « le jour où une décision voudra la lire, ce test tombera et forcera la discussion ».

        Ce jour est le 08/09/2026 — et **il n'est PAS tombé**. La valeur est devenue la source
        de pluie du bilan sol par le COORDINATEUR (`_resolve_precipitation_inputs`), soit le
        cinquième fichier, que ce test ne regardait pas. Un faux vert, exactement ce que le
        projet traque : une garde qui surveille la mauvaise porte.

        Il est donc remplacé par l'affirmation du NOUVEAU contrat. La condition posée à
        l'origine — « tant qu'on ne l'a pas vue vivre sur une vraie station » — a été remplie
        le 08/09 : pluie réelle, `precipitation` 0 → 1,4 mm par pas de 0,1, total dérivé exact,
        réserve créditée de +0,3 mm, aucun gain rejeté.
        """
        coord = self._coord()
        resolu = coordinator_mod.GazonIntelligentCoordinator._resolve_precipitation_inputs(
            coord, pluie_24h_sensor=0.7, pluie_demain_sensor=None,
            forecast_summary={}, pluie_cumul_jour=1.4,
        )
        pluie_24h, source = resolu[0], resolu[1]
        self.assertEqual(pluie_24h, 1.4, "le total dérivé doit primer sur le cumul fourni")
        self.assertTrue(
            source.startswith("capteur"),
            "⚠️ `gazon_brain` teste ce PRÉFIXE pour décider de créditer le sol : sans lui, "
            "la pluie serait lue comme une prévision et n'atteindrait jamais la réserve",
        )

    def test_sans_compteur_le_comportement_est_inchange(self) -> None:
        """Une installation sans `capteur_pluie_cumul` ne doit RIEN voir changer."""
        coord = self._coord()
        avec_capteur = coordinator_mod.GazonIntelligentCoordinator._resolve_precipitation_inputs(
            coord, pluie_24h_sensor=0.7, pluie_demain_sensor=None,
            forecast_summary={}, pluie_cumul_jour=None,
        )
        self.assertEqual((avec_capteur[0], avec_capteur[1]), (0.7, "capteur"))
        sans_rien = coordinator_mod.GazonIntelligentCoordinator._resolve_precipitation_inputs(
            coord, pluie_24h_sensor=None, pluie_demain_sensor=None,
            forecast_summary={"forecast_pluie_24h": 2.0}, pluie_cumul_jour=None,
        )
        self.assertEqual((sans_rien[0], sans_rien[1]), (2.0, "meteo_forecast"))

    def test_le_point_d_APPEL_transmet_le_total_derive(self) -> None:
        """⚠️ LE CÂBLAGE. Le paramètre a un défaut `None` : oublier de le passer laisserait
        la priorité inerte, sans qu'aucun test de la fonction seule ne le voie."""
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        # Fenêtre après le marqueur d'appel plutôt qu'un découpage sur « ) » : un commentaire
        # à l'intérieur de l'appel contient des parenthèses et tronquerait la lecture.
        appel = source.split("self._resolve_precipitation_inputs(", 1)[1][:900]
        self.assertIn('pluie_cumul_jour=weather_profile.get("pluie_cumul_jour_mm")', appel)

    def test_l_entree_de_configuration_existe(self) -> None:
        flow = (PACKAGE_DIR / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("vol.Optional(CONF_CAPTEUR_PLUIE_CUMUL", flow)

    # ── un autre compteur (0.95.0 : la page change les entrées) ──────────────────────────
    @staticmethod
    def _brancher(coord, entite):
        coord._get_conf = lambda cle: entite if cle == "capteur_pluie_cumul" else None

    def test_un_compteur_plus_BAS_compte_sa_propre_pluie(self) -> None:
        """Comparé au maximum de l'ancien, il ne comptait plus rien tant qu'il ne l'avait pas
        dépassé : des semaines de pluie perdues, pour un compteur qui ne repart jamais à zéro."""
        sortie, coord = self._rejouer([250.0, 251.0])
        self._brancher(coord, "sensor.nouveau")
        sortie, _ = self._rejouer([3.0], coord=coord)
        self.assertAlmostEqual(sortie["pluie_cumul_jour_mm"], 1.0, places=2, msg="rien n'est compté au changement")
        sortie, _ = self._rejouer([3.4], coord=coord)
        self.assertAlmostEqual(sortie["pluie_cumul_jour_mm"], 1.4, places=2, msg="la pluie du nouveau compteur compte")

    def test_un_compteur_plus_HAUT_n_est_pas_une_averse(self) -> None:
        sortie, coord = self._rejouer([250.0, 250.5])
        self._brancher(coord, "sensor.nouveau")
        sortie, _ = self._rejouer([262.0], coord=coord)
        self.assertAlmostEqual(sortie["pluie_cumul_jour_mm"], 0.5, places=2, msg="11,5 mm d'écart ne sont pas tombés")
        self.assertAlmostEqual(sortie["pluie_cumul_lame_mm"], 0.5, places=2)
        self.assertEqual(sortie["pluie_gain_rejete_mm"], 0.0, "ni une trame corrompue")

    def test_un_suivi_d_AVANT_la_0_95_garde_sa_reference(self) -> None:
        runtime = {"pluie_cumul": {"date": "2026-09-01", "total_jour": 0.3, "pic": 250.0, "gain_rejete": 0.0}}
        sortie, _ = self._rejouer([250.4], coord=self._coord(runtime=runtime))
        self.assertAlmostEqual(sortie["pluie_cumul_jour_mm"], 0.7, places=2)
        self.assertEqual(runtime["pluie_cumul"]["entite"], "sensor.cumul")

    def test_sans_reference_un_changement_n_invente_pas_de_total(self) -> None:
        runtime = {"pluie_cumul": {"date": "2026-09-01", "total_jour": 0.0, "entite": "sensor.ancien"}}
        sortie, _ = self._rejouer([3.0], coord=self._coord(runtime=runtime))
        self.assertIsNone(sortie["pluie_cumul_jour_mm"], "aucune référence = aucun total (PR #49)")


class ChangerLesEntreesDepuisLaPageTests(unittest.TestCase):
    """0.95.0 : une entrée changée sur la page, avec le même résultat que « Configurer ».

    ⚠️ `async_update_config` relance la surveillance de CE coordinateur pendant que l'écriture
    des options déclenche son rechargement : croisés, les deux laisseraient des minuteries sur un
    coordinateur arrêté. Ces tests verrouillent l'autre chemin.
    """

    def _monter(self, *, options=None, data=None, recharge=True, partage=True):
        journal: list = []
        entree = types.SimpleNamespace(entry_id="e1", options=dict(options or {}), data=dict(data or {}))

        def async_update_entry(e, **kwargs):
            journal.append(("entrée", {k: dict(v) for k, v in kwargs.items()}))
            for cle, valeur in kwargs.items():
                setattr(e, cle, valeur)
            return True

        taches: list = []
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_get_entry=lambda entry_id: entree if entry_id == "e1" else None,
                async_update_entry=async_update_entry,
                async_reload=lambda entry_id: ("recharger", entry_id),
            ),
            data={},
            async_create_task=taches.append,
        )
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.hass = hass
        coord.entry = entree
        coord.source_config_changed = lambda: recharge
        coord._rafraichir_apres_action_utilisateur = AsyncMock()
        coord.async_update_config = AsyncMock()

        async def async_update_shared_config(maj):
            journal.append(("partagé", dict(maj)))

        coord.shared_state = types.SimpleNamespace(async_update_shared_config=async_update_shared_config) if partage else None
        hass.data[coordinator_mod.DOMAIN] = {"e1": coord}
        return coord, entree, journal, taches

    def _autre(self, *, recharge):
        autre = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        autre.entry = types.SimpleNamespace(entry_id="e2")
        autre.source_config_changed = lambda: recharge
        autre.async_request_refresh = lambda: ("rafraichir", "e2")
        return autre

    def test_le_partage_d_abord_puis_les_options_puis_le_rechargement(self) -> None:
        coord, entree, journal, taches = self._monter(options={"reglages": {"x": 1}, "capteur_vent": "sensor.a"})
        recharge = asyncio.run(coord.async_changer_entrees({"capteur_vent": "sensor.b"}))
        self.assertTrue(recharge)
        self.assertEqual(journal, [
            ("partagé", {"capteur_vent": "sensor.b"}),
            ("entrée", {"options": {"reglages": {"x": 1}, "capteur_vent": "sensor.b"}}),
        ])
        coord._rafraichir_apres_action_utilisateur.assert_not_awaited()
        coord.async_update_config.assert_not_awaited()
        self.assertEqual(taches, [])

    def test_une_entree_du_sol_n_est_pas_partagee(self) -> None:
        coord, _, journal, _ = self._monter()
        asyncio.run(coord.async_changer_entrees({"capteur_humidite_sol": "sensor.sonde"}))
        self.assertEqual([j[0] for j in journal], ["entrée"])

    def test_sans_etat_partage_les_options_suffisent(self) -> None:
        coord, entree, journal, _ = self._monter(partage=False)
        asyncio.run(coord.async_changer_entrees({"capteur_vent": "sensor.b"}))
        self.assertEqual(entree.options, {"capteur_vent": "sensor.b"})
        self.assertEqual([j[0] for j in journal], ["entrée"])

    def test_retirer_efface_aussi_la_configuration_d_origine(self) -> None:
        """Sinon la valeur d'origine reprendrait sa place : options > partagé > origine."""
        coord, entree, journal, _ = self._monter(data={"capteur_vent": "sensor.vieux", "zone_1": "switch.v1"})
        asyncio.run(coord.async_changer_entrees({"capteur_vent": None}))
        self.assertEqual(journal[-1], ("entrée", {
            "options": {"capteur_vent": None},
            "data": {"capteur_vent": None, "zone_1": "switch.v1"},
        }))

    def test_la_configuration_d_origine_n_est_touchee_que_si_besoin(self) -> None:
        coord, _, journal, _ = self._monter(data={"capteur_vent": None, "capteur_pression": "sensor.p"})
        asyncio.run(coord.async_changer_entrees({"capteur_vent": None, "capteur_pression": "sensor.q"}))
        self.assertNotIn("data", journal[-1][1])

    def test_sans_rechargement_un_cycle_part_tout_de_suite(self) -> None:
        coord, _, _, _ = self._monter(recharge=False)
        self.assertFalse(asyncio.run(coord.async_changer_entrees({"capteur_pluie_cumul": "sensor.compteur"})))
        coord._rafraichir_apres_action_utilisateur.assert_awaited_once()

    def test_l_autre_pelouse_suit_une_entree_partagee(self) -> None:
        for recharge_autre, attendu in ((True, ("recharger", "e2")), (False, ("rafraichir", "e2"))):
            with self.subTest(recharge_autre=recharge_autre):
                coord, _, _, taches = self._monter()
                coord.hass.data[coordinator_mod.DOMAIN]["e2"] = self._autre(recharge=recharge_autre)
                coord.hass.data[coordinator_mod.DOMAIN]["pas_un_coordinateur"] = object()
                asyncio.run(coord.async_changer_entrees({"capteur_vent": "sensor.b"}))
                self.assertEqual(taches, [attendu])
                taches.clear()
                asyncio.run(coord.async_changer_entrees({"capteur_hauteur_gazon": "sensor.h"}))
                self.assertEqual(taches, [], "une entrée propre à cette pelouse ne touche pas l'autre")

    def test_rien_a_changer(self) -> None:
        coord, _, journal, taches = self._monter()
        self.assertFalse(asyncio.run(coord.async_changer_entrees({})))
        self.assertEqual((journal, taches), ([], []))
        coord._rafraichir_apres_action_utilisateur.assert_not_awaited()

    def test_arrosage_en_cours(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        fini = types.SimpleNamespace(done=lambda: True)
        lance = types.SimpleNamespace(done=lambda: False)
        cas = [
            ((True, False, None), True),
            ((False, True, None), True),
            ((False, False, lance), True),
            ((False, False, fini), False),
            ((False, False, None), False),
        ]
        for (session, vanne, tache), attendu in cas:
            with self.subTest(session=session, vanne=vanne, tache=tache):
                coord._watering_session_active = lambda s=session: s
                coord._shared_valve_busy_elsewhere = lambda v=vanne: v
                coord._auto_irrigation_scheduler_task = tache
                self.assertIs(coord.arrosage_en_cours(), attendu)


class RoseeLueSurLHerbeTests(unittest.TestCase):
    """0.96.0 : un point de rosée branché sur « Rosée sur l'herbe » est ignoré.

    Le moteur lit « au-dessus de 0 = herbe mouillée » (tonte bloquée, ressuyage, maladies). Le
    17/09/2026, le point de rosée de la station (9,2 °C) y était branché par « Configurer ».
    """

    def _coord(self, entite, etat):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda e: etat if e == entite else None))
        coord._get_conf = lambda cle: entite if cle == "capteur_rosee" else None
        coord._get_float_state = lambda e: float(etat.state) if etat is not None and e == entite else None
        return coord

    def test_un_point_de_rosee_est_ignore_et_signale_une_fois(self) -> None:
        for attributs in ({"unit_of_measurement": "°C", "device_class": "temperature"}, {"unit_of_measurement": "°F"}, {"device_class": "temperature"}):
            with self.subTest(attributs=attributs):
                coord = self._coord("sensor.point_de_rosee", types.SimpleNamespace(state="9.2", attributes=attributs))
                with self.assertLogs(coordinator_mod._LOGGER, level="WARNING") as journal:
                    self.assertIsNone(coord._lire_rosee())
                    self.assertIsNone(coord._lire_rosee())
                self.assertEqual(len(journal.output), 1, "une seule fois par entité")
                self.assertIn("sensor.point_de_rosee", journal.output[0])
                self.assertIn("Réglages → Installation", journal.output[0])

    def test_une_humidite_du_feuillage_est_lue(self) -> None:
        for etat, attendu in (("0", 0.0), ("1", 1.0), ("35", 35.0)):
            with self.subTest(etat=etat):
                coord = self._coord("sensor.feuillage", types.SimpleNamespace(state=etat, attributes={"unit_of_measurement": "%"}))
                self.assertEqual(coord._lire_rosee(), attendu)

    def test_sans_entree_ni_entite(self) -> None:
        self.assertIsNone(self._coord(None, None)._lire_rosee())
        self.assertIsNone(self._coord("sensor.disparue", None)._lire_rosee())

    def test_le_cycle_passe_par_cette_lecture(self) -> None:
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        self.assertIn("rosee = self._lire_rosee()\n", source)
        self.assertNotIn("self._get_float_state(self._get_conf(CONF_CAPTEUR_ROSEE))", source)


class RafraichissementApresActionTests(unittest.TestCase):
    """⚠️ « Quand je clique j'ai quelques secondes avant que ça se mette à jour »,
    10/09/2026.

    Le coordinateur s'initialise sans debouncer personnalisé : il hérite de celui de Home
    Assistant, `REQUEST_REFRESH_DEFAULT_COOLDOWN = 10 s` avec `immediate=True` (HA 2026.2.3).
    Le premier appel passe, puis la porte reste fermée dix secondes. Or les capteurs suivis
    (station météo, tondeuse, vannes) en demandent aussi : le debouncer est presque toujours
    dans sa fenêtre, et un clic attendait le reste des dix secondes.

    Le clic passait, le service s'exécutait, le cerveau était à jour — seule la REPUBLICATION
    attendait. Une attente invisible se lit « ça n'a pas marché ».
    """

    ACTIONS = (
        "async_set_auto_irrigation_enabled", "async_set_evening_cooling_enabled",
        "async_set_mower_coordination_enabled",
        "async_set_mowing_cooldown_after_watering_minutes",
        "async_set_auto_mowing_declaration_enabled", "async_set_auto_mowing_declaration_minutes",
        "async_set_selected_product", "async_set_mode", "async_set_date_action",
        "async_set_normal", "async_declare_intervention", "async_record_mowing",
        "async_recalibrate_reserve", "async_remove_last_application",
        "async_reset_mower_passes", "async_stop_irrigation", "async_update_config",
        # Oubliés au premier jet, trouvés par la revue du 10/09/2026.
        "async_register_product", "async_remove_product",
        # 0.95.0 : une entrée changée sur la page (quand rien ne se recharge).
        "async_changer_entrees",
    )

    # ⚠️ CHEMINS MIXTES — ils servent une action utilisateur **et** l'exécuteur d'arrosage.
    # Les brancher sur l'immédiat ferait tourner un cycle complet, en ligne, à l'intérieur de la
    # tâche d'arrosage. C'est le point d'entrée utilisateur qui rafraîchit, pas eux.
    MIXTES = ("async_record_watering", "async_record_user_action")

    def _coord(self):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.async_refresh = AsyncMock()
        coord.async_request_refresh = AsyncMock()
        return coord

    # ---- LE COMPORTEMENT ----------------------------------------------------------------
    def test_une_action_utilisateur_rafraichit_TOUT_DE_SUITE(self) -> None:
        coord = self._coord()
        coord._dans_le_cycle = False
        asyncio.run(coord._rafraichir_apres_action_utilisateur())
        coord.async_refresh.assert_awaited_once()
        coord.async_request_refresh.assert_not_awaited()

    def test_depuis_le_CYCLE_on_retombe_sur_le_chemin_debounce(self) -> None:
        """⚠️ RÉENTRANCE. Rafraîchir depuis l'intérieur du cycle se rappellerait lui-même.

        Le piège est connu ici : c'est lui qui a imposé l'écriture synchrone dans le cerveau
        pour la déclaration automatique de tonte. La promesse tenait par la discipline ; elle
        tient désormais par une garde, et ce test la verrouille.
        """
        coord = self._coord()
        coord._dans_le_cycle = True
        asyncio.run(coord._rafraichir_apres_action_utilisateur())
        coord.async_refresh.assert_not_awaited()
        coord.async_request_refresh.assert_awaited_once()

    def test_le_drapeau_retombe_MEME_si_le_cycle_leve(self) -> None:
        """Sans le `finally`, une exception au milieu du cycle laisserait le drapeau levé pour
        toujours — et TOUTES les actions retomberaient définitivement sur le chemin lent."""
        coord = self._coord()
        coord._dans_le_cycle = False

        async def _boum():
            raise RuntimeError("cycle cassé")

        coord._calculer_donnees = _boum
        with self.assertRaises(RuntimeError):
            asyncio.run(
                coordinator_mod.GazonIntelligentCoordinator._async_update_data(coord)
            )
        self.assertFalse(coord._dans_le_cycle, "le drapeau est resté levé après une exception")

    def test_le_cycle_leve_le_drapeau_pendant_son_execution(self) -> None:
        coord = self._coord()
        coord._dans_le_cycle = False
        vu = {}

        async def _corps():
            vu["pendant"] = coord._dans_le_cycle
            return {}

        coord._calculer_donnees = _corps
        asyncio.run(coordinator_mod.GazonIntelligentCoordinator._async_update_data(coord))
        self.assertTrue(vu["pendant"], "le cycle n'a pas levé le drapeau de réentrance")
        self.assertFalse(coord._dans_le_cycle)

    # ---- LE CÂBLAGE ---------------------------------------------------------------------
    def test_TOUTES_les_actions_passent_par_le_chemin_immediat(self) -> None:
        """⚠️ Le piège du projet : un correctif câblé à moitié.

        ⚠️ PORTÉE EXACTE, et la revue a eu raison de me reprendre : cette liste est ÉCRITE ICI.
        Elle verrouille les points connus contre une régression ; elle ne peut PAS voir une
        action ajoutée demain. La revue a d'ailleurs trouvé ainsi deux services oubliés au
        premier jet (`register_product`, `remove_product`) — que ce test ne voyait pas.
        """
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        for nom in self.ACTIONS:
            with self.subTest(action=nom):
                debut = source.index(f"def {nom}(")
                suite = source.find("\n    async def ", debut + 1)
                autre = source.find("\n    def ", debut + 1)
                fin = min(x for x in (suite, autre, len(source)) if x > 0)
                corps = source[debut:fin]
                self.assertIn("_rafraichir_apres_action_utilisateur()", corps,
                              f"{nom} attend encore le debouncer de 10 s")
                self.assertNotIn("await self.async_request_refresh()", corps,
                                 f"{nom} garde un appel débouncé")

    def test_les_chemins_MIXTES_restent_debounces(self) -> None:
        """⚠️ TROUVÉ PAR LA REVUE, et mon premier jet avait tort.

        `async_record_watering` et `async_record_user_action` servent bien un service appelé par
        l'utilisateur — mais elles sont aussi appelées par l'exécuteur d'arrosage à chaque étape
        (en_attente, démarrage, fin, arrêt), soit une quinzaine de points internes. Les brancher
        sur l'immédiat faisait tourner un cycle complet, en ligne, DANS la tâche d'arrosage.
        """
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        for nom in self.MIXTES:
            with self.subTest(methode=nom):
                debut = source.index(f"async def {nom}(")
                suite = source.find("\n    async def ", debut + 1)
                autre = source.find("\n    def ", debut + 1)
                fin = min(x for x in (suite, autre, len(source)) if x > 0)
                corps = source[debut:fin]
                self.assertIn("await self.async_request_refresh()", corps,
                              f"{nom} est un chemin mixte : il doit rester débouncé")
                self.assertNotIn("_rafraichir_apres_action_utilisateur", corps,
                                 f"{nom} fait tourner un cycle complet dans la tâche d'arrosage")

    def test_le_POINT_D_ENTREE_utilisateur_rafraichit_lui(self) -> None:
        """La contrepartie : « J'ai arrosé à la main » doit quand même répondre tout de suite.
        Le rafraîchissement vit dans le gestionnaire de service, pas dans la méthode mixte."""
        source = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
        bloc = source.split("async def _handle_declare_watering")[1].split("\nasync def ")[0]
        self.assertIn("_rafraichir_apres_action_utilisateur()", bloc,
                      "le service declare_watering attend encore le debouncer de 10 s")

    def test_le_chemin_des_CAPTEURS_reste_debounce(self) -> None:
        """⚠️ On ne touche pas à ce chemin-là, et c'est délibéré : un capteur météo qui bouge
        peut attendre dix secondes, et c'est même ce qui protège cette installation d'un
        recalcul en boucle. Seules les actions de l'utilisateur passent devant."""
        source = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        bloc = source.split("def _handle_source_state_change")[1].split("\n    @callback")[0]
        self.assertIn("self.async_request_refresh()", bloc)
        self.assertNotIn("_rafraichir_apres_action_utilisateur", bloc)

    def test_le_cycle_delegue_bien_a_son_corps(self) -> None:
        """Garde du découpage : si `_async_update_data` cessait d'appeler `_calculer_donnees`,
        les tests qui inspectent le corps du cycle deviendraient verts sur du vide."""
        import inspect
        source = inspect.getsource(
            coordinator_mod.GazonIntelligentCoordinator._async_update_data
        )
        self.assertIn("await self._calculer_donnees()", source)
        self.assertIn("finally:", source)


class PilotageTondeuseCoordinateurTests(unittest.TestCase):
    def _coord(
        self,
        mode: str,
        *,
        bootstrap: bool = True,
        service_error: Exception | None = None,
        start_window_policy: str | None = None,
    ):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        async_call = AsyncMock(side_effect=service_error)
        coord.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda _entity_id: None),
            services=types.SimpleNamespace(async_call=async_call),
        )
        coord._runtime_state = {}
        coord._mower_control_bootstrap_complete = bootstrap
        coord._get_conf = lambda cle: (
            mode
            if cle == "pilotage_tondeuse"
            else start_window_policy if cle == "tondeuse_creneaux_depart" else None
        )
        coord._reglages_instance = lambda: {}
        coord.arrosage_en_cours = lambda: False
        coord._current_datetime = lambda: datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
        return coord, async_call

    @staticmethod
    def _snapshot() -> dict[str, object]:
        return {
            "tondeuse_source_entity": "lawn_mower.esperance_jr",
            "tondeuse_connectee": True,
            "tondeuse_prete": True,
            "mower_is_docked": True,
            "mower_is_outside": False,
            "mower_is_mowing": False,
            "mower_is_returning": False,
            "mower_operation_state": "docked",
            "mower_dock_signal_fort": True,
            "mower_battery": 100,
            "mower_pass_count_today": 0,
            "mowing_daily_session_limit": 2,
            "mowing_window_state": "ideal",
            "gazon_permet_tonte": True,
            "action_possible": True,
        }

    def test_observation_publie_le_depart_sans_appeler_de_service(self) -> None:
        coord, service = self._coord("observation")
        snapshot = self._snapshot()
        asyncio.run(coord._async_apply_mower_control(snapshot))
        self.assertEqual(snapshot["mower_control_state"], "observation")
        self.assertEqual(snapshot["mower_control_pending_action"], "start_mowing")
        service.assert_not_awaited()

    def test_actif_envoie_une_unique_commande_complete(self) -> None:
        coord, service = self._coord("actif")
        snapshot = self._snapshot()
        asyncio.run(coord._async_apply_mower_control(snapshot))
        service.assert_awaited_once_with(
            "lawn_mower", "start_mowing", {"entity_id": "lawn_mower.esperance_jr"}, blocking=True
        )
        self.assertIsNone(snapshot["mower_control_pending_action"])
        self.assertEqual(snapshot["mower_control_last_action"], "start_mowing")
        self.assertEqual(snapshot["mower_control_cycle_state"], "depart_envoye")

        # Tant que la sortie n'est pas observée, la commande acceptée n'est jamais répétée.
        asyncio.run(coord._async_apply_mower_control(snapshot))
        service.assert_awaited_once()
        self.assertEqual(snapshot["mower_control_state"], "depart_envoye")

    def test_une_commande_envoyee_memorise_une_reference_pour_confirmer_le_depart(self) -> None:
        """Signalé en relecture de la PR #52 (21/09/2026) : sans référence mémorisée au moment de la
        commande, un vieux pourcentage de travail suffisait à confirmer un départ jamais
        réellement observé."""
        coord, service = self._coord("actif")
        snapshot = self._snapshot() | {
            "mower_job_progress_pct": 18,
            "mower_job_id": "ancien-job",
        }

        asyncio.run(coord._async_apply_mower_control(snapshot))

        service.assert_awaited_once()
        runtime = coord._runtime_state["mower_control"]
        self.assertEqual(runtime["managed_start_baseline_job_id"], "ancien-job")
        self.assertEqual(runtime["managed_start_baseline_progress"], 18)

        # Même relevé exactement (tondeuse toujours à quai, même vieux pourcentage) au cycle
        # suivant : la commande ne doit ni se répéter, ni être prise pour un départ confirmé.
        asyncio.run(coord._async_apply_mower_control(snapshot))
        service.assert_awaited_once()
        self.assertEqual(snapshot["mower_control_state"], "depart_envoye")
        self.assertIsNot(coord._runtime_state["mower_control"].get("managed_cycle_active"), True)

    def test_position_partielle_du_volet_est_transmise_au_pilote(self) -> None:
        coord, service = self._coord("actif")
        coord._get_conf = lambda cle: (
            "actif"
            if cle == "pilotage_tondeuse"
            else "cover.garage_tondeuse"
            if cle == "entite_volet_garage_tondeuse"
            else None
        )
        coord.hass.states.get = lambda _entity_id: types.SimpleNamespace(
            state="open", attributes={"current_position": 70}
        )
        snapshot = self._snapshot()

        asyncio.run(coord._async_apply_mower_control(snapshot))

        service.assert_awaited_once_with(
            "cover", "open_cover", {"entity_id": "cover.garage_tondeuse"}, blocking=True
        )
        self.assertEqual(snapshot["mower_garage_position"], 70)
        self.assertEqual(snapshot["mower_control_state"], "ouverture_garage")

    def test_un_rappel_du_cycle_gere_cree_une_unique_reprise(self) -> None:
        coord, service = self._coord("actif")
        coord._runtime_state["mower_control"] = {
            "managed_cycle_active": True,
            "managed_start_pending": False,
        }
        dehors = self._snapshot() | {
            "mower_is_docked": False,
            "mower_is_outside": True,
            "mower_is_mowing": True,
            "mower_operation_state": "mowing",
            "gazon_permet_tonte": False,
            "action_possible": False,
            "mowing_block_reason_label": "Pluie en cours",
            "mower_job_progress_pct": 42,
            "mower_job_completion_state": "en_cours",
        }
        asyncio.run(coord._async_apply_mower_control(dehors))
        service.assert_awaited_once_with(
            "lawn_mower", "dock", {"entity_id": "lawn_mower.esperance_jr"}, blocking=True
        )
        runtime = coord._runtime_state["mower_control"]
        self.assertTrue(runtime["resume_required"])
        self.assertEqual(runtime["resume_reason"], "Pluie en cours")
        self.assertEqual(dehors["mower_control_cycle_state"], "reprise_attendue")

        retour = self._snapshot() | {
            "mower_job_progress_pct": 42,
            "mower_job_completion_state": "en_pause",
        }
        asyncio.run(coord._async_apply_mower_control(retour))
        self.assertEqual(service.await_count, 2)
        self.assertEqual(service.await_args.args[:2], ("lawn_mower", "start_mowing"))
        self.assertFalse(runtime["resume_required"])
        self.assertTrue(runtime["managed_start_pending"])

        # Même état cloud encore à quai au cycle suivant : aucun second start_mowing. Avec le
        # signal frais exigé depuis la 0.97.25, un relevé identique (toujours à quai, même
        # progression, même état) ne confirme plus le départ à sa place — corrigé après une
        # relecture qui a montré que ce relevé inchangé reproduisait exactement le faux positif
        # signalé lors d'une relecture.
        asyncio.run(coord._async_apply_mower_control(retour))
        self.assertEqual(service.await_count, 2)
        self.assertEqual(retour["mower_control_cycle_state"], "depart_envoye")

        # Une fois la sortie réellement observée, le départ est enfin confirmé.
        sorti = self._snapshot() | {
            "mower_is_docked": False,
            "mower_is_outside": True,
            "mower_is_mowing": True,
            "mower_operation_state": "mowing",
            "mower_job_progress_pct": 43,
            "mower_job_completion_state": "en_cours",
        }
        asyncio.run(coord._async_apply_mower_control(sorti))
        self.assertEqual(service.await_count, 2)
        self.assertEqual(sorti["mower_control_cycle_state"], "cycle_autonome")
        self.assertTrue(runtime["managed_cycle_active"])

    def test_pluie_pendant_recharge_cree_la_dette_apres_dock_reussi(self) -> None:
        coord, service = self._coord("actif")
        coord._runtime_state["mower_control"] = {
            "managed_cycle_active": True,
            "managed_start_pending": False,
        }
        recharge_bloquee = self._snapshot() | {
            "mower_operation_state": "charging",
            "mower_battery": 35,
            "gazon_permet_tonte": False,
            "action_possible": False,
            "mowing_block_reason_label": "Pluie en cours",
            "mower_job_progress_pct": 42,
            "mower_job_completion_state": "en_pause",
        }

        asyncio.run(coord._async_apply_mower_control(recharge_bloquee))

        service.assert_awaited_once_with(
            "lawn_mower", "dock", {"entity_id": "lawn_mower.esperance_jr"}, blocking=True
        )
        runtime = coord._runtime_state["mower_control"]
        self.assertTrue(runtime["managed_cycle_active"])
        self.assertTrue(runtime["resume_required"])
        self.assertEqual(runtime["resume_reason"], "Pluie en cours")
        self.assertEqual(recharge_bloquee["mower_control_cycle_state"], "reprise_attendue")

    def test_la_reprise_due_survit_au_redemarrage(self) -> None:
        source, _service = self._coord("actif")
        source._runtime_state["mower_control"] = {
            "managed_cycle_active": True,
            "managed_start_pending": False,
            "resume_required": True,
            "resume_reason": "Vent fort",
            "resume_requested_at": "2026-09-19T09:30:00+00:00",
        }
        payload = source._serialized_runtime_state()

        relu, service = self._coord("actif")
        relu._restore_runtime_state(payload)
        retour = self._snapshot() | {
            "mower_job_progress_pct": 42,
            "mower_job_completion_state": "en_pause",
        }
        asyncio.run(relu._async_apply_mower_control(retour))
        service.assert_awaited_once_with(
            "lawn_mower", "start_mowing", {"entity_id": "lawn_mower.esperance_jr"}, blocking=True
        )
        self.assertFalse(relu._runtime_state["mower_control"]["resume_required"])

    def test_un_rappel_refuse_ou_seulement_observe_ne_cree_pas_de_reprise(self) -> None:
        dehors = self._snapshot() | {
            "mower_is_docked": False,
            "mower_is_outside": True,
            "mower_is_mowing": True,
            "mower_operation_state": "mowing",
            "gazon_permet_tonte": False,
            "action_possible": False,
            "mower_job_progress_pct": 42,
            "mower_job_completion_state": "en_cours",
        }
        for mode, erreur in (
            ("observation", None),
            ("actif", RuntimeError("dock refusé")),
        ):
            with self.subTest(mode=mode):
                coord, _service = self._coord(mode, service_error=erreur)
                coord._runtime_state["mower_control"] = {"managed_cycle_active": True}
                asyncio.run(coord._async_apply_mower_control(dict(dehors)))
                self.assertIsNot(
                    coord._runtime_state["mower_control"].get("resume_required"),
                    True,
                )

    def test_le_choix_de_creneau_arrive_jusqu_a_la_commande_reelle(self) -> None:
        snapshot = self._snapshot()
        snapshot["mowing_window_state"] = "acceptable"

        strict, service_strict = self._coord("actif")
        asyncio.run(strict._async_apply_mower_control(dict(snapshot)))
        service_strict.assert_not_awaited()

        souple, service_souple = self._coord("actif", start_window_policy="ideal_acceptable")
        asyncio.run(souple._async_apply_mower_control(dict(snapshot)))
        service_souple.assert_awaited_once_with(
            "lawn_mower", "start_mowing", {"entity_id": "lawn_mower.esperance_jr"}, blocking=True
        )

    def test_premier_cycle_et_mode_desactive_n_appellent_jamais_de_service(self) -> None:
        for mode, bootstrap in (("actif", False), ("desactive", True)):
            with self.subTest(mode=mode, bootstrap=bootstrap):
                coord, service = self._coord(mode, bootstrap=bootstrap)
                snapshot = self._snapshot()
                asyncio.run(coord._async_apply_mower_control(snapshot))
                service.assert_not_awaited()

    def test_erreur_de_service_est_publiee_sans_remonter(self) -> None:
        coord, service = self._coord("actif", service_error=RuntimeError("service indisponible"))
        snapshot = self._snapshot()
        asyncio.run(coord._async_apply_mower_control(snapshot))
        service.assert_awaited_once()
        self.assertEqual(snapshot["mower_control_state"], "erreur")
        self.assertEqual(snapshot["mower_control_last_error"], "service indisponible")


class ArrosageZoneTemporiseTests(unittest.TestCase):
    """Le bouton 5 min appartient au moteur HA, jamais au cycle de vie du navigateur."""

    def test_le_service_construit_un_plan_exact_d_une_seule_zone(self) -> None:
        async def _run() -> None:
            coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
            coord._irrigation_launch_lock = asyncio.Lock()
            coord._auto_irrigation_task = None
            coord._auto_irrigation_scheduler_task = None
            coord._runtime_state = {
                "active_irrigation_session": None,
                "auto_irrigation_safety_lock": False,
            }
            coord._iter_zones_with_rate = lambda: iter(
                [("switch.zone_1", 14.0 / 60.0), ("switch.zone_2", 17.0 / 60.0)]
            )
            coord._watering_session_active = lambda: False
            coord._shared_valve_busy_elsewhere = lambda: False
            coord._auto_irrigation_safety_lock_active = lambda: False
            coord._get_conf = lambda key: "switch.pompe" if key == "entite_pompe" else None
            coord._build_active_irrigation_session = lambda **kwargs: {
                "source": kwargs["source"],
                "strategy": kwargs["strategy"],
                "zones_pending": [{"zone": "switch.zone_2"}],
            }
            coord.async_record_user_action = AsyncMock()
            coord._execute_canonical_watering_plan = AsyncMock()
            events: list[tuple[str, dict[str, object]]] = []
            coord.hass = types.SimpleNamespace(
                async_create_task=lambda coro, name=None: asyncio.create_task(coro),
                bus=types.SimpleNamespace(
                    async_fire=lambda event, payload=None: events.append((event, dict(payload or {})))
                ),
            )

            await coordinator_mod.GazonIntelligentCoordinator.async_run_zone_for_duration(
                coord, "switch.zone_2", duration_minutes=5
            )
            assert coord._auto_irrigation_task is not None
            await coord._auto_irrigation_task

            kwargs = coord._execute_canonical_watering_plan.await_args.kwargs
            plan = kwargs["plan"]
            self.assertEqual(plan.plan_type, "single_zone")
            self.assertEqual(plan.zones[0].zone, "switch.zone_2")
            self.assertEqual(plan.zones[0].duration_s, 300)
            self.assertAlmostEqual(plan.zones[0].mm, 17.0 * 5.0 / 60.0)
            self.assertEqual(kwargs["source"], "manual_timed_zone")
            self.assertEqual(kwargs["session"]["managed_pump_entity_id"], "switch.pompe")
            self.assertFalse(kwargs["session"]["managed_pump_started_by_integration"])
            self.assertEqual(events[0][1]["duration_seconds"], 300)

        asyncio.run(_run())

    def test_une_zone_non_configuree_est_refusee_avant_toute_commande(self) -> None:
        async def _run() -> None:
            coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
            coord._iter_zones_with_rate = lambda: iter([("switch.zone_1", 1.0)])
            with self.assertRaises(coordinator_mod.HomeAssistantError):
                await coordinator_mod.GazonIntelligentCoordinator.async_run_zone_for_duration(
                    coord, "switch.inconnue", duration_minutes=5
                )

        asyncio.run(_run())

    def test_la_pompe_est_arretee_seulement_si_le_cycle_l_a_demarree(self) -> None:
        async def _run(initial_state: str) -> tuple[list[str], dict[str, object]]:
            calls: list[str] = []

            async def _call(_domain, service, _data, blocking=True):  # noqa: ARG001
                calls.append(service)

            coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
            coord.hass = types.SimpleNamespace(
                states=_FakeStates(
                    {"switch.pompe": _FakeState(initial_state, datetime.now(timezone.utc))}
                ),
                services=types.SimpleNamespace(async_call=_call),
            )
            coord._persist_runtime_state = AsyncMock()
            session: dict[str, object] = {
                "managed_pump_entity_id": "switch.pompe",
                "managed_pump_started_by_integration": False,
            }
            await coordinator_mod.GazonIntelligentCoordinator._ensure_managed_irrigation_pump(
                coord, session
            )
            closed = await coordinator_mod.GazonIntelligentCoordinator._safe_turn_off_managed_irrigation_pump(
                coord, session
            )
            self.assertTrue(closed)
            return calls, session

        calls_off, session_off = asyncio.run(_run("off"))
        self.assertEqual(calls_off, ["turn_on", "turn_off"])
        self.assertFalse(session_off["managed_pump_started_by_integration"])

        calls_on, session_on = asyncio.run(_run("on"))
        self.assertEqual(calls_on, [])
        self.assertFalse(session_on["managed_pump_started_by_integration"])

    def test_une_session_terminee_au_redemarrage_ferme_la_pompe_avant_d_etre_purgee(self) -> None:
        async def _run() -> None:
            coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
            session = {
                "status": "running",
                "managed_pump_entity_id": "switch.pompe",
                "managed_pump_started_by_integration": True,
                coordinator_mod.WATERING_RECORDED_KEY: True,
            }
            coord._runtime_state = {
                "active_irrigation_session": session,
                "auto_irrigation_safety_lock": False,
            }
            coord._is_finished_irrigation_session = lambda _session: True
            coord._auto_irrigation_safety_lock_active = lambda: False
            coord._persist_execution_snapshot = lambda *args, **kwargs: None
            coord._set_active_irrigation_session = lambda value: coord._runtime_state.__setitem__(
                "active_irrigation_session", value
            )
            coord._finalize_pending_irrigation_user_action = AsyncMock()
            coord._persist_runtime_state = AsyncMock()

            with patch.object(
                coordinator_mod.GazonIntelligentCoordinator,
                "_safe_turn_off_managed_irrigation_pump",
                new=AsyncMock(return_value=True),
            ) as close_pump:
                await coordinator_mod.GazonIntelligentCoordinator._restore_active_irrigation_session(
                    coord
                )

            close_pump.assert_awaited_once_with(coord, session)
            self.assertIsNone(coord._runtime_state["active_irrigation_session"])

        asyncio.run(_run())

    def test_le_panneau_n_utilise_plus_de_minuteur_navigateur(self) -> None:
        source = (PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('"gazon_intelligent", "run_zone_for_duration"', source)
        self.assertIn("duration_minutes: 5", source)
        self.assertNotIn("_arretsDifferes", source)
        self.assertIn('"gazon_intelligent", "stop_irrigation"', source)
        apercu = (ROOT / "dev" / "panel" / "index.html").read_text(encoding="utf-8")
        self.assertIn('service === "run_zone_for_duration"', apercu)
        chemin_services_apercu = ROOT / "dev" / "panel" / "services.json"
        if chemin_services_apercu.exists():
            services_apercu = json.loads(
                chemin_services_apercu.read_text(encoding="utf-8")
            )
            self.assertEqual(
                services_apercu["run_zone_for_duration"],
                ["duration_minutes", "entity_id", "zone_entity_id"],
            )

    def test_le_service_est_declare_et_enregistre(self) -> None:
        yaml_source = (PACKAGE_DIR / "services.yaml").read_text(encoding="utf-8")
        init_source = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("run_zone_for_duration:", yaml_source)
        self.assertIn('SERVICE_RUN_ZONE_FOR_DURATION = "run_zone_for_duration"', init_source)
        self.assertIn("SERVICE_RUN_ZONE_FOR_DURATION,\n        _handle_run_zone_for_duration,", init_source)
