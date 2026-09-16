from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types
import unittest
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


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)

coordinator_helpers = importlib.import_module(
    "custom_components.gazon_intelligent.coordinator_helpers"
)
coordinator_irrigation = importlib.import_module(
    "custom_components.gazon_intelligent.coordinator_irrigation"
)
coordinator_runtime = importlib.import_module(
    "custom_components.gazon_intelligent.coordinator_runtime"
)
coordinator_observability = importlib.import_module(
    "custom_components.gazon_intelligent.coordinator_observability"
)
coordinator_states = importlib.import_module(
    "custom_components.gazon_intelligent.coordinator_states"
)
coordinator_weather = importlib.import_module(
    "custom_components.gazon_intelligent.coordinator_weather"
)


class _Logger:
    def __init__(self) -> None:
        self.debugs: list[tuple[object, ...]] = []
        self.warnings: list[tuple[object, ...]] = []

    def debug(self, *args: object, **_kwargs: object) -> None:
        self.debugs.append(args)

    def warning(self, *args: object, **_kwargs: object) -> None:
        self.warnings.append(args)


class _State:
    def __init__(self, state: object, attributes: dict[str, object] | None = None) -> None:
        self.state = state
        self.attributes = attributes or {}


class _States:
    def __init__(self, values: dict[str, _State]) -> None:
        self._values = values

    def get(self, entity_id: str) -> _State | None:
        return self._values.get(entity_id)


class _Hass:
    def __init__(self, values: dict[str, _State]) -> None:
        self.states = _States(values)


class CoordinatorHelpersTests(unittest.TestCase):
    def test_clean_empty_attrs_returns_none_when_everything_is_empty(self) -> None:
        self.assertIsNone(
            coordinator_helpers._clean_empty_attrs(
                {"none": None, "empty": "", "dict": {}, "list": []}
            )
        )

    def test_clean_empty_attrs_keeps_false_and_zero(self) -> None:
        self.assertEqual(
            coordinator_helpers._clean_empty_attrs(
                {"zero": 0, "false": False, "none": None, "text": "ok"}
            ),
            {"zero": 0, "false": False, "text": "ok"},
        )

    def test_to_float_or_none_rejects_bool_and_nan(self) -> None:
        self.assertIsNone(coordinator_helpers._to_float_or_none(True))
        self.assertIsNone(coordinator_helpers._to_float_or_none("nan"))
        self.assertEqual(coordinator_helpers._to_float_or_none("12.5"), 12.5)

    def test_float_conf_value_uses_default_and_logs_invalid_values(self) -> None:
        logger = _Logger()

        self.assertEqual(
            coordinator_helpers._float_conf_value("12.5", key="test", default=1.0, logger=logger),
            12.5,
        )
        self.assertEqual(
            coordinator_helpers._float_conf_value(None, key="test", default=1.0, logger=logger),
            1.0,
        )
        self.assertEqual(
            coordinator_helpers._float_conf_value("bad", key="test", default=1.0, logger=logger),
            1.0,
        )
        self.assertTrue(logger.debugs)

    def test_mediane_handles_odd_and_even_lengths(self) -> None:
        self.assertEqual(coordinator_helpers._mediane([5.0, 1.0, 3.0]), 3.0)
        self.assertEqual(coordinator_helpers._mediane([10.0, 2.0, 4.0, 8.0]), 6.0)

    def test_passe_a_retenir_keeps_unknown_or_blocked_passes(self) -> None:
        self.assertTrue(coordinator_helpers._passe_a_retenir({"minutes_tondues": None}))
        self.assertTrue(
            coordinator_helpers._passe_a_retenir(
                {"minutes_tondues": 0.0, "minutes_bloquees": 0.0, "fin_motif": "bloquee"}
            )
        )
        self.assertFalse(
            coordinator_helpers._passe_a_retenir(
                {"minutes_tondues": 0.0, "minutes_bloquees": 0.0, "fin_motif": "garage"}
            )
        )


class CoordinatorStatesTests(unittest.TestCase):
    def test_validate_sensor_value_rejects_outliers_and_keeps_zero(self) -> None:
        logger = _Logger()

        self.assertIsNone(coordinator_states.validate_sensor_value(80.0, "temperature", logger))
        self.assertEqual(coordinator_states.validate_sensor_value(0.0, "pluie", logger), 0.0)

        self.assertTrue(logger.warnings)

    def test_validate_sensor_value_garde_les_bornes_temperature_et_pluie(self) -> None:
        logger = _Logger()

        self.assertEqual(coordinator_states.validate_sensor_value(-20.0, "temperature", logger), -20.0)
        self.assertEqual(coordinator_states.validate_sensor_value(55.0, "temperature", logger), 55.0)
        self.assertIsNone(coordinator_states.validate_sensor_value(-20.1, "temperature", logger))
        self.assertIsNone(coordinator_states.validate_sensor_value(55.1, "temperature", logger))
        self.assertEqual(coordinator_states.validate_sensor_value(0.0, "pluie", logger), 0.0)
        self.assertEqual(coordinator_states.validate_sensor_value(150.0, "pluie", logger), 150.0)
        self.assertIsNone(coordinator_states.validate_sensor_value(-0.1, "pluie", logger))
        self.assertIsNone(coordinator_states.validate_sensor_value(150.1, "pluie", logger))

    def test_validate_sensor_value_garde_les_bornes_etp_et_humidite(self) -> None:
        # Ces deux branches tournent en production : `_calculer_donnees` valide le capteur ETP et
        # le capteur d'humidité à chaque cycle. Les avoir dites « code mort » était faux.
        logger = _Logger()

        self.assertEqual(coordinator_states.validate_sensor_value(0.0, "etp", logger), 0.0)
        self.assertEqual(coordinator_states.validate_sensor_value(15.0, "etp", logger), 15.0)
        self.assertIsNone(coordinator_states.validate_sensor_value(-0.1, "etp", logger))
        self.assertIsNone(coordinator_states.validate_sensor_value(15.1, "etp", logger))
        self.assertEqual(coordinator_states.validate_sensor_value(0.0, "humidite", logger), 0.0)
        self.assertEqual(coordinator_states.validate_sensor_value(100.0, "humidite", logger), 100.0)
        self.assertIsNone(coordinator_states.validate_sensor_value(-0.1, "humidite", logger))
        self.assertIsNone(coordinator_states.validate_sensor_value(100.1, "humidite", logger))

    def test_get_float_state_reads_comma_decimal_and_rejects_non_finite(self) -> None:
        logger = _Logger()
        hass = _Hass(
            {
                "sensor.temp": _State("12,5"),
                "sensor.bad": _State("nan"),
            }
        )

        self.assertEqual(coordinator_states.get_float_state(hass, "sensor.temp", logger), 12.5)
        self.assertIsNone(coordinator_states.get_float_state(hass, "sensor.bad", logger))
        self.assertTrue(logger.debugs)

    def test_get_text_state_treats_unavailable_as_absence(self) -> None:
        hass = _Hass(
            {
                "sensor.ok": _State(" ready "),
                "sensor.unknown": _State("unavailable"),
            }
        )

        self.assertEqual(coordinator_states.get_text_state(hass, "sensor.ok"), "ready")
        self.assertIsNone(coordinator_states.get_text_state(hass, "sensor.unknown"))

    def test_get_bool_state_standardizes_home_assistant_states(self) -> None:
        hass = _Hass(
            {
                "binary_sensor.motion": _State("detected"),
                "binary_sensor.clear": _State("clear"),
                "sensor.other": _State("maybe"),
            }
        )

        self.assertIs(coordinator_states.get_bool_state(hass, "binary_sensor.motion"), True)
        self.assertIs(coordinator_states.get_bool_state(hass, "binary_sensor.clear"), False)
        self.assertIsNone(coordinator_states.get_bool_state(hass, "sensor.other"))

    def test_get_state_unit_is_tolerant_when_hass_is_missing(self) -> None:
        hass = _Hass({"sensor.wind": _State("4.2", {"unit_of_measurement": "m/s"})})

        self.assertEqual(coordinator_states.get_state_unit(hass, "sensor.wind"), "m/s")
        self.assertIsNone(coordinator_states.get_state_unit(None, "sensor.wind"))


class CoordinatorObservabilityTests(unittest.TestCase):
    def test_extract_block_reason_compacts_known_markers(self) -> None:
        self.assertEqual(
            coordinator_observability.extract_block_reason(
                {"raison_decision": "Arrosage bloqué: pluie prévue suffisante demain"}
            ),
            "pluie prévue suffisante",
        )
        self.assertEqual(
            coordinator_observability.extract_block_reason({"block_reason": "custom_reason"}),
            "custom_reason",
        )
        self.assertIsNone(coordinator_observability.extract_block_reason({}))

    def test_build_observability_payload_filters_empty_values_and_adds_recent_water(self) -> None:
        today = date(2026, 9, 14)
        history = [
            {
                "type": "arrosage",
                "date": today.isoformat(),
                "mm": 3.2,
            }
        ]

        payload = coordinator_observability.build_observability_payload(
            {
                "phase_active": "Normal",
                "sous_phase": None,
                "watering_cause": "hydrique",
                "block_reason": "mode bloqué par l'utilisateur",
            },
            history=history,
            today=today,
            feedback_observation="ok",
        )

        self.assertEqual(payload["phase"], "Normal")
        self.assertEqual(payload["watering_cause"], "hydrique")
        self.assertEqual(payload["block_reason"], "mode bloqué")
        self.assertEqual(payload["feedback_observation"], "ok")
        self.assertNotIn("sous_phase", payload)
        self.assertIn("mm_applied_today", payload)

    def test_etp_ecoulee_du_jour_reads_current_ledger_entry(self) -> None:
        today = date(2026, 8, 6)
        result = coordinator_observability.etp_ecoulee_du_jour(
            {
                "ledger": [
                    {"date": "2026-08-05", "etp_elapsed_mm": 3.1, "etp_mm": 5.0},
                    {"date": "2026-08-06", "etp_elapsed_mm": 4.237, "etp_mm": 6.1},
                ]
            },
            today=today,
        )

        self.assertEqual(
            result,
            {"etp_ecoulee_mm": 4.237, "etp_jour_estime_mm": 6.1},
        )

    def test_etp_ecoulee_du_jour_ignores_stale_or_malformed_ledgers(self) -> None:
        empty = {"etp_ecoulee_mm": None, "etp_jour_estime_mm": None}
        today = date(2026, 8, 6)

        for soil_balance in (
            None,
            {},
            {"ledger": None},
            {"ledger": []},
            {"ledger": ["pas un dict"]},
            {"ledger": [{"date": "2026-08-05", "etp_elapsed_mm": 3.1, "etp_mm": 5.0}]},
            "pas un dict",
        ):
            with self.subTest(soil_balance=soil_balance):
                self.assertEqual(
                    coordinator_observability.etp_ecoulee_du_jour(soil_balance, today=today),
                    empty,
                )


class CoordinatorIrrigationTests(unittest.TestCase):
    OUVERTURE = 3 * 60 + 45
    LEVER = 7 * 60 + 34  # un lever de mi-septembre

    def _depart(self, **over):
        kw = dict(window_start_minute=self.OUVERTURE, sunrise_minute=self.LEVER,
                  duration_s=3810, margin_minutes=15)
        kw.update(over)
        return coordinator_irrigation.plan_morning_departure(**kw)

    def test_plan_morning_departure_finit_quinze_minutes_avant_le_lever(self) -> None:
        # Cycle réel du 15/09 : 63,5 min, comptées 64. Fin 07:19 (lever − 15), départ 06:15.
        self.assertEqual(
            self._depart(),
            {"departure_minute": 6 * 60 + 15, "end_minute": 7 * 60 + 19},
        )

    def test_plan_morning_departure_n_a_plus_de_plafond_pour_la_tonte(self) -> None:
        # Le premier jet plafonnait la fin à 07:00 (10:00 − 180 min de délai de reprise), sur une
        # prémisse fausse : retiré le 15/09/2026. Lever à 08:20 : la fin suit le lever, 08:05.
        depart = self._depart(sunrise_minute=8 * 60 + 20)
        self.assertEqual(depart["end_minute"], 8 * 60 + 5)
        self.assertEqual(depart["departure_minute"], 7 * 60 + 1)

    def test_plan_morning_departure_en_ete_suit_le_lever(self) -> None:
        depart = self._depart(sunrise_minute=6 * 60 + 10)
        self.assertEqual(depart["end_minute"], 5 * 60 + 55)
        self.assertEqual(depart["departure_minute"], 4 * 60 + 51)

    def test_plan_morning_departure_ne_part_jamais_avant_l_ouverture(self) -> None:
        # 4 h de cycle ne tiennent pas avant 07:19 : départ à l'ouverture, fin plus tard.
        depart = self._depart(duration_s=4 * 3600)
        self.assertEqual(depart["departure_minute"], self.OUVERTURE)
        self.assertEqual(depart["end_minute"], self.OUVERTURE + 240)

    def test_plan_morning_departure_compte_la_minute_entamee(self) -> None:
        # Cycle réel du 11/09 : 3990 s, soit 66,5 min, comptées 67. Arrondir au plus proche donnerait
        # 66 et finirait une demi-minute après l'heure visée. Les 63,5 min du 15/09 ne départagent
        # pas les deux arrondis : 64 dans les deux cas.
        depart = self._depart(duration_s=3990)
        self.assertEqual(depart["end_minute"] - depart["departure_minute"], 67)
        self.assertEqual(depart["departure_minute"], 6 * 60 + 12)

    def test_plan_morning_departure_marge_negative_ramenee_a_zero(self) -> None:
        self.assertEqual(self._depart(margin_minutes=-30)["end_minute"], self.LEVER)

    def test_plan_morning_departure_sans_lever_connu_rend_la_main(self) -> None:
        self.assertIsNone(self._depart(sunrise_minute=None))

    def test_zone_rate_mm_min_requires_entity_and_numeric_rate(self) -> None:
        self.assertEqual(coordinator_irrigation.zone_rate_mm_min("switch.zone_1", 120.0), 2.0)
        self.assertEqual(coordinator_irrigation.zone_rate_mm_min(None, 120.0), 0.0)
        self.assertEqual(coordinator_irrigation.zone_rate_mm_min("switch.zone_1", "bad"), 0.0)

    def test_zone_rate_mm_h_requires_entity_and_keeps_zero(self) -> None:
        self.assertEqual(coordinator_irrigation.zone_rate_mm_h("switch.zone_1", "12.5"), 12.5)
        self.assertEqual(coordinator_irrigation.zone_rate_mm_h("switch.zone_1", 0.0), 0.0)
        self.assertEqual(coordinator_irrigation.zone_rate_mm_h(None, 12.5), 0.0)

    def test_build_pending_zone_segments_uses_per_passage_values(self) -> None:
        zone = types.SimpleNamespace(zone="switch.zone_1", duration_s=600.0, mm=4.0)

        class _Plan:
            passage_count = 2
            zones = [zone]

            @staticmethod
            def zone_for_passage(zone_index: int, _passage: int) -> object:
                return types.SimpleNamespace(
                    zone=f"switch.zone_{zone_index + 1}",
                    duration_s=300.0,
                    mm=2.0,
                )

        self.assertEqual(
            coordinator_irrigation.build_pending_zone_segments(_Plan()),
            [
                {
                    "passage": 1,
                    "zone_index": 0,
                    "zone": "switch.zone_1",
                    "duration_s": 300.0,
                    "mm": 2.0,
                },
                {
                    "passage": 2,
                    "zone_index": 0,
                    "zone": "switch.zone_1",
                    "duration_s": 300.0,
                    "mm": 2.0,
                },
            ],
        )

    def test_build_zone_execution_record_prorates_interrupted_segment(self) -> None:
        zone = types.SimpleNamespace(zone="switch.zone_1", rate_mm_h=12.0, duration_s=600.0, mm=2.0)

        full = coordinator_irrigation.build_zone_execution_record(zone=zone, passage=1, order=1)
        half = coordinator_irrigation.build_zone_execution_record(
            zone=zone,
            passage=1,
            order=1,
            effective_duration_s=300.0,
        )

        self.assertEqual(full["mm"], 2.0)
        self.assertNotIn("interrupted", full)
        self.assertEqual(half["mm"], 1.0)
        self.assertTrue(half["interrupted"])
        self.assertEqual(half["planned_duration_s"], 600)

    def test_is_matching_zone_segment_reconnait_l_index_zero(self) -> None:
        self.assertTrue(
            coordinator_irrigation.is_matching_zone_segment(
                {"passage": 1, "zone_index": 0},
                passage=1,
                zone_index=0,
            )
        )
        self.assertTrue(
            coordinator_irrigation.is_matching_zone_segment(
                {"passage": "2", "zone_index": "0"},
                passage=2,
                zone_index=0,
            )
        )
        self.assertFalse(
            coordinator_irrigation.is_matching_zone_segment(
                {"passage": None, "zone_index": 0},
                passage=1,
                zone_index=0,
            )
        )
        self.assertFalse(
            coordinator_irrigation.is_matching_zone_segment(
                {"passage": 1, "zone_index": "illisible"},
                passage=1,
                zone_index=0,
            )
        )


class CoordinatorRuntimeTests(unittest.TestCase):
    def test_local_datetime_text_formats_date_and_datetime_values(self) -> None:
        tz = timezone(timedelta(hours=2))

        self.assertEqual(
            coordinator_runtime.local_datetime_text("2026-09-14T10:30:00Z", local_timezone=tz),
            "14/09/2026 à 12:30",
        )
        self.assertEqual(
            coordinator_runtime.local_datetime_text(date(2026, 9, 14), local_timezone=tz),
            "14/09/2026",
        )

    def test_local_datetime_text_falls_back_to_date_prefix_or_original_text(self) -> None:
        tz = timezone.utc

        self.assertEqual(
            coordinator_runtime.local_datetime_text("2026-09-14 pas iso", local_timezone=tz),
            "14/09/2026",
        )
        self.assertEqual(
            coordinator_runtime.local_datetime_text("pas une date", local_timezone=tz),
            "pas une date",
        )
        self.assertIsNone(coordinator_runtime.local_datetime_text("", local_timezone=tz))

    def test_local_date_of_uses_home_assistant_local_conversion_when_available(self) -> None:
        moment = datetime(2026, 9, 14, 22, 30, tzinfo=timezone.utc)

        self.assertEqual(
            coordinator_runtime.local_date_of(
                moment,
                as_local=lambda value: value.astimezone(timezone(timedelta(hours=2))),
            ),
            date(2026, 9, 15),
        )

    def test_new_runtime_id_uses_timestamp_and_short_token(self) -> None:
        self.assertEqual(
            coordinator_runtime.new_runtime_id(
                "sess",
                datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc),
                token_factory=lambda: "abcdef123456",
            ),
            "sess_20260914T103000Z_abcdef12",
        )

    def test_current_objective_mm_prefers_result_then_extra_then_data(self) -> None:
        result = types.SimpleNamespace(objectif_arrosage="4.2", extra={"objectif_mm": 3.0})
        self.assertEqual(coordinator_runtime.current_objective_mm(result, {"objectif_mm": 2.0}), 4.2)

        result = types.SimpleNamespace(objectif_arrosage=None, extra={"objectif_mm": "3.5"})
        self.assertEqual(coordinator_runtime.current_objective_mm(result, {"objectif_mm": 2.0}), 3.5)

        self.assertEqual(coordinator_runtime.current_objective_mm(None, {"objectif_mm": "2.5"}), 2.5)
        self.assertEqual(coordinator_runtime.current_objective_mm(None, {"objectif_mm": "-1"}), 0.0)
        self.assertEqual(coordinator_runtime.current_objective_mm(None, {"objectif_mm": "bad"}), 0.0)

    def test_parse_datetime_value_normalizes_z_and_naive_values_to_utc(self) -> None:
        self.assertEqual(
            coordinator_runtime.parse_datetime_value("2026-09-14T10:30:00Z"),
            datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            coordinator_runtime.parse_datetime_value("2026-09-14T10:30:00"),
            datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc),
        )

    def test_parse_datetime_value_rejects_empty_and_invalid_values(self) -> None:
        self.assertIsNone(coordinator_runtime.parse_datetime_value(""))
        self.assertIsNone(coordinator_runtime.parse_datetime_value("pas une date"))

    def test_minutes_creditables_keeps_only_small_forward_gaps(self) -> None:
        now = datetime(2026, 9, 14, 8, 15, tzinfo=timezone.utc)

        self.assertEqual(
            coordinator_runtime.minutes_creditables(
                "2026-09-14T08:00:00+00:00",
                now,
                parser=coordinator_runtime.parse_datetime_value,
                max_minutes=15.0,
            ),
            15.0,
        )
        self.assertEqual(
            coordinator_runtime.minutes_creditables(
                "2026-09-14T07:59:00+00:00",
                now,
                parser=coordinator_runtime.parse_datetime_value,
                max_minutes=15.0,
            ),
            0.0,
        )
        self.assertEqual(
            coordinator_runtime.minutes_creditables(
                "2026-09-14T08:16:00+00:00",
                now,
                parser=coordinator_runtime.parse_datetime_value,
                max_minutes=15.0,
            ),
            0.0,
        )
        self.assertEqual(
            coordinator_runtime.minutes_creditables(
                "pas une date",
                now,
                parser=coordinator_runtime.parse_datetime_value,
                max_minutes=15.0,
            ),
            0.0,
        )

    def test_serialize_runtime_value_recurses_through_dicts_and_lists(self) -> None:
        value = {
            "at": datetime(2026, 9, 14, 12, 0, tzinfo=timezone(timedelta(hours=2))),
            "date": date(2026, 9, 14),
            "items": [datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)],
        }

        self.assertEqual(
            coordinator_runtime.serialize_runtime_value(value),
            {
                "at": "2026-09-14T10:00:00+00:00",
                "date": "2026-09-14",
                "items": ["2026-09-14T10:00:00+00:00"],
            },
        )

    def test_build_runtime_payload_for_event_filters_and_serializes(self) -> None:
        session = {
            "session_id": "sess_1",
            "run_id": "",
            "source": "auto_irrigation",
            "status": "running",
            "watering_cause": "hydrique",
            "ignored": "hors payload",
        }
        happened_at = datetime(2026, 9, 14, 12, 0, tzinfo=timezone(timedelta(hours=2)))

        self.assertEqual(
            coordinator_runtime.build_runtime_payload_for_event(
                session,
                {"happened_at": happened_at, "empty": None, "zones": []},
            ),
            {
                "session_id": "sess_1",
                "source": "auto_irrigation",
                "status": "running",
                "watering_cause": "hydrique",
                "happened_at": "2026-09-14T10:00:00+00:00",
            },
        )

    def test_deserialize_active_irrigation_session_parses_datetime_fields(self) -> None:
        session = coordinator_runtime.deserialize_active_irrigation_session(
            {
                "started_at": "2026-09-14T10:30:00Z",
                "current_zone_started_at": "illisible",
                "source": "auto_irrigation",
            }
        )

        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session["started_at"], datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc))
        self.assertIsNone(session["current_zone_started_at"])
        self.assertEqual(session["source"], "auto_irrigation")

    def test_is_finished_irrigation_session_respects_status_and_active_zone(self) -> None:
        now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

        self.assertTrue(
            coordinator_runtime.is_finished_irrigation_session({"status": "completed"}, now_utc=now)
        )
        self.assertFalse(
            coordinator_runtime.is_finished_irrigation_session(
                {"status": "running", "active_zones": ["switch.zone_1"]},
                now_utc=now,
            )
        )

    def test_is_finished_irrigation_session_keeps_mid_pause_with_pending_segments_open(self) -> None:
        now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
        session = {
            "status": "running",
            "current_passage": 1,
            "passage_count": 2,
            "planned_total_seconds": 600,
            "started_at": now - timedelta(hours=2),
            "active_zones": [],
            "current_zone": None,
            "zones_pending": [{"passage": 2, "zone": "switch.zone_1"}],
        }

        self.assertFalse(
            coordinator_runtime.is_finished_irrigation_session(session, now_utc=now)
        )

    def test_is_finished_irrigation_session_finishes_when_no_pending_work_remains(self) -> None:
        now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

        self.assertTrue(
            coordinator_runtime.is_finished_irrigation_session(
                {
                    "status": "running",
                    "current_passage": 2,
                    "passage_count": 2,
                    "zones_pending": [],
                },
                now_utc=now,
            )
        )

    def test_is_finished_irrigation_session_attend_que_l_eau_soit_enregistree(self) -> None:
        """Liste d'attente vide + zones jouées sans marqueur : l'eau n'est pas encore inscrite."""
        now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
        base = {
            "status": "running",
            "current_passage": 2,
            "passage_count": 2,
            "active_zones": [],
            "current_zone": None,
            "zones_pending": [],
            "zones_done": [{"passage": 1, "zone": "switch.zone_1", "mm": 3.0}],
        }
        # Branche « dernier passage » et branche « durée planifiée écoulée ».
        variantes = {
            "dernier_passage": dict(base),
            "duree_ecoulee": {
                **base,
                "current_passage": 1,
                "planned_total_seconds": 600,
                "started_at": now - timedelta(hours=2),
            },
        }
        for nom, session in variantes.items():
            with self.subTest(nom):
                self.assertFalse(
                    coordinator_runtime.is_finished_irrigation_session(session, now_utc=now)
                )
                enregistree = {**session, coordinator_runtime.WATERING_RECORDED_KEY: True}
                self.assertTrue(
                    coordinator_runtime.is_finished_irrigation_session(enregistree, now_utc=now)
                )

    def test_is_finished_irrigation_session_sans_zone_jouee_n_attend_aucun_marqueur(self) -> None:
        now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

        self.assertTrue(
            coordinator_runtime.is_finished_irrigation_session(
                {
                    "status": "running",
                    "current_passage": 2,
                    "passage_count": 2,
                    "zones_pending": [],
                    "zones_done": [],
                },
                now_utc=now,
            )
        )

    def test_is_finished_irrigation_session_le_marqueur_clot_meme_avec_segment_restant(self) -> None:
        """Une eau déjà enregistrée ne doit pas être réenregistrée à cause d'un segment zombie."""
        now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

        self.assertTrue(
            coordinator_runtime.is_finished_irrigation_session(
                {
                    "status": "recovery_required",
                    "current_zone": None,
                    "active_zones": [],
                    "last_error": "restart_recovery",
                    coordinator_runtime.WATERING_RECORDED_KEY: True,
                    "zones_done": [{"passage": 1, "zone": "switch.zone_1", "mm": 3.0}],
                    "zones_pending": [
                        {"passage": 1, "zone_index": 1, "zone": "switch.zone_2"}
                    ],
                },
                now_utc=now,
            )
        )

    def test_is_finished_irrigation_session_le_marqueur_ne_couvre_pas_une_zone_active(self) -> None:
        now = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)

        self.assertFalse(
            coordinator_runtime.is_finished_irrigation_session(
                {
                    "status": "running",
                    "current_zone": "switch.zone_1",
                    "active_zones": ["switch.zone_1"],
                    coordinator_runtime.WATERING_RECORDED_KEY: True,
                },
                now_utc=now,
            )
        )

    def test_normalize_watering_cause_preserves_known_manual_stop(self) -> None:
        self.assertEqual(
            coordinator_runtime.normalize_watering_cause(
                "arret_manuel",
                known_causes={"hydrique", "post_application", "rafraichissement_soir", "arret_manuel"},
            ),
            "arret_manuel",
        )

    def test_normalize_watering_cause_maps_application_sources_and_falls_back(self) -> None:
        known_causes = {"hydrique", "post_application", "rafraichissement_soir", "arret_manuel"}

        self.assertEqual(
            coordinator_runtime.normalize_watering_cause(
                "inconnu",
                source="manual_application",
                known_causes=known_causes,
            ),
            "post_application",
        )
        self.assertEqual(
            coordinator_runtime.normalize_watering_cause("inconnu", known_causes=known_causes),
            "hydrique",
        )

    def test_round_runtime_mm_clamps_and_rounds_values(self) -> None:
        self.assertEqual(coordinator_runtime.round_runtime_mm(1.26), 1.3)
        self.assertEqual(coordinator_runtime.round_runtime_mm(-5), 0.0)
        self.assertEqual(coordinator_runtime.round_runtime_mm("illisible"), 0.0)

    def test_build_execution_plan_metrics_counts_segments_and_rounds_plan(self) -> None:
        metrics = coordinator_runtime.build_execution_plan_metrics(
            {
                "plan": {
                    "passages": 2,
                    "zones": [{"mm": 1.24}, {"mm": 2.26}],
                },
                "planned_total_seconds": 123.6,
            }
        )

        self.assertEqual(
            metrics,
            {
                "planned_mm": 3.5,
                "planned_zone_count": 2,
                "planned_zone_segments": 4,
                "planned_total_seconds": 124,
            },
        )

    def test_build_execution_plan_metrics_handles_missing_plan(self) -> None:
        self.assertEqual(
            coordinator_runtime.build_execution_plan_metrics({"planned_total_seconds": "12.6"}),
            {
                "planned_mm": 0.0,
                "planned_zone_count": 0,
                "planned_zone_segments": 0,
                "planned_total_seconds": 12.6,
            },
        )

    def test_build_active_irrigation_session_populates_runtime_defaults(self) -> None:
        now = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
        plan = types.SimpleNamespace(
            watering_strategy=None,
            objective_scope="daily",
            watering_stage="surface",
            surface_cycle_mm=2.0,
            daily_cycles_target=3,
            cycle_spacing_minutes=90,
            surface_moisture_target="stable",
            surface_dryness_risk="low",
            runoff_risk="none",
            seeding_transition_ready=True,
            seeding_block_reason=None,
            objective_mm=6.04,
            passage_count=2,
            total_duration_s=360.0,
            as_runtime_dict=lambda: {"objective_mm": 6.04, "zones": []},
        )
        zones_pending = [{"passage": 1, "zone": "switch.zone_1"}]

        session = coordinator_runtime.build_active_irrigation_session(
            plan=plan,
            source="auto_irrigation",
            strategy="fractionne",
            watering_cause="hydrique",
            run_id="irrig_1",
            session_id="sess_1",
            now=now,
            zones_pending=zones_pending,
        )

        self.assertEqual(session["session_id"], "sess_1")
        self.assertEqual(session["run_id"], "irrig_1")
        self.assertEqual(session["watering_strategy"], "fractionne")
        self.assertEqual(session["target_mm"], 6.0)
        self.assertEqual(session["passage_count"], 2)
        self.assertEqual(session["zones_pending"], zones_pending)
        self.assertEqual(session["started_at"], now)
        self.assertEqual(session["last_update"], now)
        self.assertEqual(session["status"], "running")


class _DtUtilParis:
    """`dt_util` au vrai fuseau de Paris : les changements d'heure y existent, un décalage fixe non."""

    PARIS = ZoneInfo("Europe/Paris")

    @staticmethod
    def parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @classmethod
    def as_local(cls, value: datetime) -> datetime:
        return value.astimezone(cls.PARIS)


class CoucherDuJourTests(unittest.TestCase):
    """`sunset_today_minute_from_context` : le coucher du JOUR, même une fois le soleil couché.

    Revue du 15/09/2026. Lu sur `next_setting`, le coucher du lendemain à l'heure du lendemain, le
    soir de la veille d'un changement d'heure sautait d'une heure : la nuit de la tonte
    (coucher + 30 min) tombait une heure trop tard avant l'heure d'été, une minute après le
    coucher avant l'heure d'hiver.
    """

    def _coucher(self, next_setting: str | None, today: date) -> int | None:
        contexte = {} if next_setting is None else {"sun_next_setting": next_setting}
        return coordinator_weather.sunset_today_minute_from_context(contexte, _DtUtilParis, today)

    def test_avant_le_coucher_c_est_le_prochain(self) -> None:
        self.assertEqual(self._coucher("2026-09-15T18:12:00Z", date(2026, 9, 15)), 20 * 60 + 12)

    def test_une_fois_le_soleil_couche_c_est_toujours_celui_du_jour(self) -> None:
        # À 20:30, `next_setting` est celui du 16/09 (20:10) : on recule de 24 h.
        self.assertEqual(self._coucher("2026-09-16T18:10:00Z", date(2026, 9, 15)), 20 * 60 + 10)

    def test_veille_du_passage_a_l_heure_d_ete(self) -> None:
        # Coucher du 28/03/2027 : 18:13 UTC, soit 20:13 en heure d'été. Le soir du 27/03 (heure
        # d'hiver), lu tel quel il annonçait 20:13 ; le coucher du jour tombe vers 19:13.
        self.assertEqual(
            coordinator_weather.sun_event_minute_from_context(
                {"sun_next_setting": "2027-03-28T18:13:00Z"}, "sun_next_setting", _DtUtilParis
            ),
            20 * 60 + 13,
            "prémisse : la lecture brute saute bien d'une heure",
        )
        self.assertEqual(self._coucher("2027-03-28T18:13:00Z", date(2027, 3, 27)), 19 * 60 + 13)

    def test_veille_du_passage_a_l_heure_d_hiver(self) -> None:
        # Coucher du 25/10/2026 : 16:37 UTC, soit 17:37 en heure d'hiver. Le soir du 24/10, le
        # coucher du jour tombe vers 18:37 (heure d'été), pas 17:37.
        self.assertEqual(self._coucher("2026-10-25T16:37:00Z", date(2026, 10, 24)), 18 * 60 + 37)

    def test_coucher_absent_ou_illisible(self) -> None:
        self.assertIsNone(self._coucher(None, date(2026, 9, 15)))
        self.assertIsNone(
            coordinator_weather.sunset_today_minute_from_context("pas un dict", _DtUtilParis, date(2026, 9, 15))
        )
        self.assertIsNone(self._coucher("pas une date", date(2026, 9, 15)))


class CoordinatorWeatherTests(unittest.TestCase):
    def test_sun_event_minute_from_context_convertit_utc_en_heure_locale(self) -> None:
        class _DtUtil:
            @staticmethod
            def parse_datetime(value: str) -> datetime:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))

            @staticmethod
            def as_local(value: datetime) -> datetime:
                return value.astimezone(timezone(timedelta(hours=2)))

        self.assertEqual(
            coordinator_weather.sun_event_minute_from_context(
                {"sun_next_rising": "2026-07-29T04:30:00Z"},
                "sun_next_rising",
                _DtUtil,
            ),
            6 * 60 + 30,
        )

    def test_sun_event_minute_from_context_ignore_les_valeurs_absentes_ou_invalides(self) -> None:
        class _DtUtil:
            @staticmethod
            def parse_datetime(value: str) -> datetime | None:
                if value == "aucune-date":
                    return None
                return datetime.fromisoformat(value)

            @staticmethod
            def as_local(value: datetime) -> datetime:
                return value

        self.assertIsNone(coordinator_weather.sun_event_minute_from_context({}, "sun_next_rising", _DtUtil))
        self.assertIsNone(
            coordinator_weather.sun_event_minute_from_context(
                {"sun_next_rising": "aucune-date"},
                "sun_next_rising",
                _DtUtil,
            )
        )

    def test_et_elapsed_fraction_uses_civil_fallback_when_sun_is_unknown(self) -> None:
        self.assertEqual(
            coordinator_weather.et_elapsed_fraction(
                now=datetime(2026, 7, 29, 3, 11, tzinfo=timezone.utc),
                sunrise_minute=None,
                sunset_minute=None,
                fallback_day_start_minute=6 * 60,
                fallback_day_end_minute=21 * 60,
            ),
            0.0,
        )
        self.assertAlmostEqual(
            coordinator_weather.et_elapsed_fraction(
                now=datetime(2026, 7, 29, 13, 30, tzinfo=timezone.utc),
                sunrise_minute=None,
                sunset_minute=None,
                fallback_day_start_minute=6 * 60,
                fallback_day_end_minute=21 * 60,
            ),
            0.5,
            places=2,
        )
        self.assertEqual(
            coordinator_weather.et_elapsed_fraction(
                now=datetime(2026, 7, 29, 22, 30, tzinfo=timezone.utc),
                sunrise_minute=None,
                sunset_minute=None,
                fallback_day_start_minute=6 * 60,
                fallback_day_end_minute=21 * 60,
            ),
            1.0,
        )

    def test_et_elapsed_fraction_uses_sunrise_and_sunset_minutes(self) -> None:
        self.assertAlmostEqual(
            coordinator_weather.et_elapsed_fraction(
                now=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
                sunrise_minute=6 * 60,
                sunset_minute=18 * 60,
                fallback_day_start_minute=6 * 60,
                fallback_day_end_minute=21 * 60,
            ),
            0.5,
            places=2,
        )

    def test_estimate_rosee_uses_dew_point_first(self) -> None:
        self.assertEqual(
            coordinator_weather.estimate_rosee(
                {"weather_dew_point": "18.5", "weather_condition": "clear"},
                20.0,
                50.0,
            ),
            1.0,
        )

    def test_estimate_rosee_verrouille_les_seuils_et_priorites(self) -> None:
        self.assertEqual(
            coordinator_weather.estimate_rosee({"weather_dew_point": 18.0}, 20.0, 50.0),
            1.0,
        )
        self.assertIsNone(
            coordinator_weather.estimate_rosee({"weather_dew_point": 17.99}, 20.0, 50.0)
        )
        self.assertEqual(coordinator_weather.estimate_rosee({}, 20.0, 88.0), 0.8)
        self.assertIsNone(coordinator_weather.estimate_rosee({}, 20.0, 87.9))
        self.assertEqual(
            coordinator_weather.estimate_rosee(
                {"weather_dew_point": 18.0, "weather_condition": "fog"},
                20.0,
                88.0,
            ),
            1.0,
        )
        self.assertEqual(
            coordinator_weather.estimate_rosee({"weather_condition": "fog"}, 20.0, 88.0),
            0.8,
        )

    def test_estimate_rosee_reconnait_chaque_condition_mouillante(self) -> None:
        # Ni point de rosée ni humidité au-dessus de 88 % : seule la condition météo peut répondre.
        for condition in ("fog", "rainy", "pouring"):
            with self.subTest(condition):
                self.assertEqual(
                    coordinator_weather.estimate_rosee({"weather_condition": condition}, 20.0, 50.0),
                    1.0,
                )

    def test_estimate_rosee_falls_back_to_humidity_and_weather_condition(self) -> None:
        self.assertEqual(coordinator_weather.estimate_rosee({}, 20.0, 88.0), 0.8)
        self.assertEqual(
            coordinator_weather.estimate_rosee({"weather_condition": "fog"}, 20.0, 50.0),
            1.0,
        )
        self.assertIsNone(
            coordinator_weather.estimate_rosee({"weather_condition": "clear"}, 20.0, 50.0)
        )
        self.assertIsNone(
            coordinator_weather.estimate_rosee(
                {"weather_dew_point": "illisible", "weather_condition": "clear"},
                20.0,
                "illisible",
            )
        )


if __name__ == "__main__":
    unittest.main()
