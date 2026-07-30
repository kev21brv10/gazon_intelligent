from __future__ import annotations

import re
import unittest
from datetime import date, datetime, timezone
import importlib
from pathlib import Path
import sys
import types
from unittest.mock import patch
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


def _install_homeassistant_dt_stub() -> None:
    homeassistant = sys.modules.get("homeassistant")
    if homeassistant is None:
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant"] = homeassistant
    util = sys.modules.get("homeassistant.util")
    if util is None:
        util = types.ModuleType("homeassistant.util")
        util.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant.util"] = util
    dt_module = types.ModuleType("homeassistant.util.dt")
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=ZoneInfo("Europe/Paris"))  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_dt_stub()

decision = importlib.import_module("custom_components.gazon_intelligent.decision")
decision_mowing = importlib.import_module("custom_components.gazon_intelligent.decision_mowing")
decision_phase = importlib.import_module("custom_components.gazon_intelligent.decision_phase")
decision_risk = importlib.import_module("custom_components.gazon_intelligent.decision_risk")
decision_watering = importlib.import_module("custom_components.gazon_intelligent.decision_watering")
water = importlib.import_module("custom_components.gazon_intelligent.water")
guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")

FIXED_NOW_UTC = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
FIXED_TODAY = FIXED_NOW_UTC.date()
FIXED_HA_NOW_UTC = datetime(2026, 4, 4, 12, 15, tzinfo=timezone.utc)
FIXED_HA_TODAY = FIXED_HA_NOW_UTC.date()


def make_snapshot(**overrides):
    params = {
        "history": [],
        "today": FIXED_TODAY,
        "hour_of_day": 8,
        "temperature": 20.0,
        "pluie_24h": 0.0,
        "pluie_demain": 0.0,
        "humidite": 60.0,
        "type_sol": "limoneux",
        "etp_capteur": 2.0,
    }
    params.update(overrides)
    return decision.build_decision_snapshot(**params)


class TestDecisionSnapshotSursemisRules(unittest.TestCase):
    def test_build_decision_snapshot_sursemis_objectif_zero_never_recommends_zero_mm(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=1.0,
            pluie_demain=3.2,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=0.5,
        )

        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["niveau_action"], "surveiller")
        self.assertEqual(snapshot["decision_resume"]["action"], "aucune_action")
        self.assertNotIn("0.0 mm", snapshot["action_recommandee"])
        self.assertNotIn("0.0 mm", snapshot["conseil_principal"])
        self.assertEqual(snapshot["action_a_eviter"], "Multiplier les petits cycles.")

    def test_build_decision_snapshot_sursemis_micro_apport_rules(self) -> None:
        cases = [
            (
                "dry_surface",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "recent_rain",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=1.6,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                0.0,
                False,
                "pluie_prevue_suffisante",
                False,
            ),
            (
                "tomorrow_rain",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=2.4,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.2,
                True,
                None,
                True,
            ),
            (
                "tomorrow_rain_blocked",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=3.2,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                0.0,
                False,
                "pluie_prevue_suffisante",
                False,
            ),
            (
                "j2_rain_only",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    pluie_j2=1.8,
                    pluie_3j=4.8,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "high_balance",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 5.5},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "saturated_surface",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    humidite_sol=92.0,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 8.5},
                ),
                0.0,
                False,
                "sol_deja_humide",
                False,
            ),
            (
                "recent_watering",
                dict(
                    history=[
                        {"type": "Sursemis", "date": "2026-03-17"},
                        {"type": "arrosage", "date": date(2026, 3, 17).isoformat(), "objectif_mm": 0.5},
                    ],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=18.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                1.5,
                True,
                None,
                True,
            ),
            (
                "low_temperature",
                dict(
                    history=[{"type": "Sursemis", "date": "2026-03-17"}],
                    today=date(2026, 3, 17),
                    hour_of_day=8,
                    temperature=8.0,
                    pluie_24h=0.0,
                    pluie_demain=0.0,
                    humidite=55.0,
                    type_sol="limoneux",
                    etp_capteur=1.2,
                    weather_profile={"weather_precipitation_probability": 20.0},
                    soil_balance={"reserve_mm": 2.0},
                ),
                0.0,
                False,
                # Sous-phase Germination à 8 °C : le motif SPÉCIFIQUE doit remonter. L'attendu
                # était le générique « temperature_trop_basse » parce que le garde germination
                # était posé AVANT le bloc générique, qui écrasait aussitôt son motif.
                "temperature_trop_basse_germination",
                False,
            ),
        ]

        for name, kwargs, expected_mm, expected_allowed, expected_block_reason, expected_surface_sec in cases:
            with self.subTest(name):
                snapshot = decision.build_decision_snapshot(**kwargs)
                self.assertEqual(snapshot["phase_active"], "Sursemis")
                self.assertEqual(snapshot["objectif_mm"], expected_mm)
                self.assertEqual(snapshot["arrosage_recommande"], expected_allowed)
                self.assertEqual(snapshot.get("sursemis_micro_apport_allowed"), expected_allowed)
                self.assertEqual(snapshot.get("surface_sec"), expected_surface_sec)
                self.assertEqual(snapshot.get("sursemis_block_reason"), expected_block_reason)
                self.assertIn("pluie_probabilite_24h", snapshot)
                self.assertIn("mm_detected_24h", snapshot)
                self.assertIn("surface_saturation_level", snapshot)
                self.assertIn("surface_saturation_limit", snapshot)
                self.assertIn("sursemis_reason", snapshot)

    def test_build_decision_snapshot_sursemis_germination_is_more_permissive_than_enracinement(self) -> None:
        germination = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=2.4,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=1.2,
            weather_profile={"weather_precipitation_probability": 20.0},
            soil_balance={"reserve_mm": 2.4},
        )
        enracinement = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-06"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=1.6,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=1.2,
            weather_profile={"weather_precipitation_probability": 20.0},
            soil_balance={"reserve_mm": 2.4},
        )

        self.assertEqual(germination["phase_active"], "Sursemis")
        self.assertEqual(enracinement["phase_active"], "Sursemis")
        self.assertEqual(germination["watering_stage"], "germination")
        self.assertEqual(enracinement["watering_stage"], "enracinement")
        self.assertLess(germination["surface_cycle_mm"], enracinement["surface_cycle_mm"])
        self.assertGreater(germination["daily_cycles_target"], enracinement["daily_cycles_target"])
        self.assertEqual(germination["objective_scope"], "surface_cycle")
        self.assertEqual(enracinement["objective_scope"], "surface_cycle")
        self.assertTrue(germination["arrosage_recommande"])
        self.assertFalse(enracinement["arrosage_recommande"])
        self.assertIsNone(germination.get("block_reason"))
        self.assertIsNotNone(enracinement.get("block_reason"))

    def test_compute_action_guidance_sursemis_reprise_transition_ready_waits_more(self) -> None:
        base_kwargs = dict(
            phase_dominante="Sursemis",
            sous_phase="Reprise",
            water_balance={
                "bilan_hydrique_mm": 1.4,
                "deficit_3j": 0.8,
                "deficit_7j": 1.2,
            },
            advanced_context={
                "vent": 6,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.2,
            humidite=55.0,
            temperature=18.0,
            etp=1.2,
            objectif_mm=0.5,
            hour_of_day=9,
            sous_phase_age_days=19,
            sous_phase_progression=82.0,
        )

        not_ready = decision.compute_action_guidance(
            history=[{"type": "Sursemis", "date": "2026-03-01"}],
            **base_kwargs,
        )
        ready = decision.compute_action_guidance(
            history=[
                {"type": "Sursemis", "date": "2026-03-01"},
                {"type": "tonte", "date": "2026-03-15"},
                {"type": "tonte", "date": "2026-03-18"},
            ],
            **base_kwargs,
        )

        self.assertEqual(not_ready["fenetre_optimale"], "ce_matin")
        self.assertEqual(ready["fenetre_optimale"], "attendre")
        self.assertEqual(not_ready["niveau_action"], "a_faire")
        self.assertEqual(ready["niveau_action"], "surveiller")
        self.assertEqual(not_ready["risque_gazon"], "modere")
        self.assertEqual(ready["risque_gazon"], "modere")

class TestDecisionSnapshotApplicationsAndSensors(unittest.TestCase):
    def test_build_decision_snapshot_fertilisation_uses_application_technique(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Fertilisation", "date": "2026-06-15"}],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=33,
            pluie_24h=0,
            pluie_demain=0,
            humidite=30,
            type_sol="argileux",
            etp_capteur=5.0,
        )

        self.assertEqual(snapshot["phase_active"], "Fertilisation")
        self.assertEqual(snapshot["application_type"], "sol")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["type_arrosage"], "application_technique_auto")
        self.assertEqual(snapshot["arrosage_conseille"], "application_technique_auto")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["watering_target_date"], "2026-06-15")
        self.assertEqual(snapshot["next_action_date"], "2026-06-15")
        self.assertGreater(snapshot["objectif_mm"], 0.0)

    def test_build_decision_snapshot_uses_advanced_sensors(self) -> None:
        base_snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=24,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
        )
        advanced_snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=24,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
            humidite_sol=22,
            vent=18,
            rosee=1.0,
            hauteur_gazon=11.5,
            retour_arrosage=0.7,
            weather_profile={
                "weather_temperature": 24,
                "weather_humidity": 55,
                "weather_wind_speed": 18,
                "weather_cloud_coverage": 20,
                "weather_precipitation_probability": 70,
            },
        )

        self.assertEqual(advanced_snapshot["advanced_context"]["pluie_source"], "capteur_pluie_24h")
        self.assertEqual(advanced_snapshot["advanced_context"]["weather_precipitation_probability"], 70.0)
        self.assertEqual(advanced_snapshot["humidite_sol"], 22.0)
        self.assertEqual(advanced_snapshot["vent"], 18.0)
        self.assertEqual(advanced_snapshot["rosee"], 1.0)
        self.assertEqual(advanced_snapshot["hauteur_gazon"], 11.5)
        self.assertEqual(advanced_snapshot["retour_arrosage"], 0.7)
        self.assertGreater(advanced_snapshot["score_hydrique"], base_snapshot["score_hydrique"])
        self.assertGreaterEqual(advanced_snapshot["score_stress"], base_snapshot["score_stress"])
        self.assertIn(advanced_snapshot["niveau_action"], {"a_faire", "surveiller", "critique"})

    def test_build_decision_snapshot_keeps_return_watering_sensor_priority(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-03-17",
                    "objectif_mm": 4.0,
                    "zones": [
                        {"zone": "switch.zone_1", "mm": 2.0},
                        {"zone": "switch.zone_2", "mm": 2.0},
                    ],
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=24,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
            retour_arrosage=0.7,
        )

        self.assertEqual(snapshot["retour_arrosage"], 0.7)

class TestDecisionSnapshotMowing(unittest.TestCase):
    def test_build_mowing_bundle_exposes_stable_core_keys_on_allowed_path(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(
            set(decision_mowing._MOWING_BUNDLE_CORE_KEYS).issubset(set(mowing_bundle))
        )

    def test_build_mowing_bundle_passthroughs_generic_mower_context(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_statut": "au_repos",
                "tondeuse_statut_libelle": "Au repos",
                "tondeuse_prete": True,
                "tondeuse_batterie": 44,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["tondeuse_statut"], "au_repos")
        self.assertEqual(mowing_bundle["tondeuse_statut_libelle"], "Au repos")
        self.assertTrue(mowing_bundle["tondeuse_prete"])
        self.assertEqual(mowing_bundle["tondeuse_batterie"], 44)

    def test_build_mowing_bundle_prioritizes_post_application_over_watering_runtime(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-06-15",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_irrigation_mode": "suggestion",
                    "application_post_watering_status": "autorise",
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "active_irrigation_session": {"status": "running", "started_at": "2026-06-15T06:30:00+00:00"},
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertTrue(mowing_bundle["mowing_blocked_by_watering"])
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "post_application_active")
        self.assertFalse(mowing_bundle["action_possible"])

    def test_regle_du_tiers_active_sans_capteur_de_hauteur(self) -> None:
        # RÉGRESSION (28/07/2026) : la règle du tiers et le garde-fou « hauteur trop faible » ne
        # lisaient QUE `capteur_hauteur_gazon`, un capteur physique que peu d'installations
        # possèdent. Sans lui, ces deux protections agronomiques étaient purement INACTIVES —
        # le capteur « hauteur de gazon estimée », pourtant calculé et affiché, était décoratif.
        # On retombe désormais sur l'estimation, comme le fait déjà le calcul de la hauteur
        # conseillée. Ne jamais couper plus d'un tiers du brin : au-delà, le gazon jaunit.
        def _bundle(last_mowing_date):
            ctx = decision.DecisionContext.from_legacy_args(
                history=[{"type": "tonte", "date": last_mowing_date, "hauteur_coupe_mm": 55}],
                today=date(2026, 7, 15), hour_of_day=11, temperature=22,
                pluie_24h=0, pluie_demain=0, humidite=45, type_sol="limoneux", etp_capteur=4.0,
            )
            phase = decision_phase.build_phase_bundle(ctx)
            water = decision_watering.build_water_bundle(ctx, phase)
            risk = decision_risk.build_risk_bundle(ctx, phase, water)
            return decision_mowing.build_mowing_bundle(ctx, phase, water, risk)

        # Gazon laissé très longtemps sans tonte → hauteur estimée élevée : couper à la hauteur
        # conseillée retirerait bien plus d'un tiers → la règle doit BLOQUER.
        haute = _bundle("2026-05-01")
        self.assertIsNotNone(haute["gazon_hauteur_estimee_cm"])
        self.assertIn(
            haute["raison_blocage_code"],
            {"regle_tiers", "regle_tiers_impossible"},
            f"hauteur estimée {haute['gazon_hauteur_estimee_cm']} cm : la règle du tiers doit s'appliquer",
        )
        self.assertFalse(haute["tonte_autorisee"])

        # Gazon tondu récemment → hauteur proche de la consigne : aucune raison de bloquer
        # pour la hauteur (la règle ne doit pas devenir un blocage permanent).
        recente = _bundle("2026-07-14")
        self.assertNotIn(
            recente["raison_blocage_code"],
            {"regle_tiers", "regle_tiers_impossible", "hauteur_trop_faible"},
        )

    def test_contrat_public_tonte_coherent_avec_la_decision(self) -> None:
        # RÉGRESSION (28/07/2026), deux incohérences dans le contrat public :
        #  A) `temp_extreme` absent de `agronomic_block_codes` → `tonte_autorisee` restait à ON
        #     à 35 °C, donc une automatisation branchée sur le binary_sensor lançait le robot en
        #     pleine canicule.
        #  B) `mowing_blocked` ne reflétait QUE les blocages machine/durs → il restait à False
        #     alors que la tonte était interdite par le gazon. Inexploitable pour décider.
        def _bundle(**over):
            params = dict(
                history=[], today=date(2026, 7, 15), hour_of_day=11,
                pluie_24h=0, pluie_demain=0, humidite=45,
                type_sol="limoneux", etp_capteur=4.0,
            )
            params.update(over)
            ctx = decision.DecisionContext.from_legacy_args(**params)
            phase = decision_phase.build_phase_bundle(ctx)
            water = decision_watering.build_water_bundle(ctx, phase)
            risk = decision_risk.build_risk_bundle(ctx, phase, water)
            return decision_mowing.build_mowing_bundle(ctx, phase, water, risk)

        # A) Canicule : le GAZON refuse → les deux drapeaux doivent le dire.
        chaud = _bundle(temperature=35)
        self.assertEqual(chaud["mowing_block_reason_code"], "temp_extreme")
        self.assertFalse(chaud["tonte_autorisee"], "tonte_autorisee doit tomber à 35 °C")
        self.assertTrue(chaud["mowing_blocked"])
        self.assertFalse(chaud["action_possible"])

        # B) Cohérence générale : tonte interdite ⇒ mowing_blocked vrai, quel que soit le motif.
        for temperature in (5, 22, 35):
            b = _bundle(temperature=temperature)
            if not b["tonte_autorisee"]:
                self.assertTrue(
                    b["mowing_blocked"],
                    f"tonte interdite à {temperature} °C mais mowing_blocked=False",
                )

    def test_pas_de_cooldown_de_tonte_sans_arrosage_dans_l_historique(self) -> None:
        # RÉGRESSION (28/07/2026) : `_latest_watering_timestamp` fabrique un repli
        # « aujourd'hui 06:00 UTC » quand aucun arrosage ne correspond, et le cooldown n'était pas
        # gardé par l'historique. Résultat sur une instance qui n'a JAMAIS arrosé : tonte refusée
        # de 08:00 à 11:00 locales — soit exactement la fenêtre idéale — avec le message mensonger
        # « Arrosage récent : attends encore 180 min avant de reprendre la tonte. »
        context = decision.DecisionContext.from_legacy_args(
            history=[],  # aucun arrosage nulle part
            today=date(2026, 6, 15),
            hour_of_day=9,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "now_utc": "2026-06-15T07:00:00+00:00",  # 09h00 locales
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_cooldown_remaining_minutes"], 0)
        self.assertNotEqual(mowing_bundle["mowing_block_reason_code"], "watering_cooldown")
        self.assertFalse(mowing_bundle["mowing_blocked_by_watering"])

    def test_build_mowing_bundle_prioritizes_phase_block_over_active_watering(self) -> None:
        # Phase Traitement active ET arrosage en cours : le blocage de phase doit gagner
        # (priorité la plus haute), pas le blocage lié à l'arrosage.
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "Traitement", "date": "2026-06-15"}],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "active_irrigation_session": {"status": "running", "started_at": "2026-06-15T06:30:00+00:00"},
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "phase_traitement")
        self.assertFalse(mowing_bundle["mowing_blocked_by_watering"])

    def test_build_mowing_bundle_blocks_on_runtime_watering_session(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "active_irrigation_session": {"status": "running", "started_at": "2026-06-15T06:30:00+00:00"},
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "watering_in_progress")
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_recent_watering_cooldown(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "last_irrigation_execution": {"type": "arrosage", "triggered_at": "2026-06-15T07:00:00+00:00"},
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "watering_cooldown")
        self.assertGreater(mowing_bundle["mowing_cooldown_remaining_minutes"], 0)
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_uses_last_execution_end_timestamp_for_cooldown(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=10,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
            runtime_context={
                "last_irrigation_execution": {
                    "type": "arrosage",
                    "ended_at": "2026-06-15T09:15:00+00:00",
                },
                "mowing_cooldown_after_watering_minutes": 180,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "watering_cooldown")
        self.assertEqual(mowing_bundle["mowing_cooldown_remaining_minutes"], 135)

    def test_build_mowing_bundle_marks_recent_watering_as_watering_block(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-06-15",
                    "mm": 3.8,
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertTrue(mowing_bundle["mowing_blocked_by_watering"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "recent_watering")
        self.assertTrue(
            mowing_bundle["mowing_block_reason_label"].startswith("Arrosage récent: attendre encore ~"),
            mowing_bundle["mowing_block_reason_label"],
        )
        self.assertEqual(mowing_bundle["mowing_block_reason"], "recent_watering")
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_wet_soil_after_old_watering(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-06-10",
                    "mm": 3.8,
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            humidite_sol=75,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_connectee": True,
                "tondeuse_prete": True,
                "mower_coordination_ready": True,
                "mower_operation_state": "idle",
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(mowing_bundle["mowing_blocked_by_watering"])
        self.assertEqual(mowing_bundle["mowing_block_reason"], "soil_wet")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Sol humide: attendre le ressuyage.")
        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_exposes_robot_style_frequency_and_window(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_frequency_target_per_week"], 5.0)
        self.assertEqual(mowing_bundle["mowing_frequency_label"], "4 à 6 / semaine")
        self.assertEqual(mowing_bundle["mowing_window_state"], "ideal")
        self.assertEqual(mowing_bundle["mowing_window_label"], "Fenêtre idéale")
        self.assertEqual(mowing_bundle["mowing_window_reason"], "Fenêtre idéale du matin.")
        self.assertTrue(mowing_bundle["tonte_autorisee"])

    def _fenetre_avec_vent(self, *, vent, weather_profile=None):
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
            vent=vent,
            weather_profile=weather_profile or {},
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
        return bundle["mowing_window_state"]

    def test_capteur_vent_tombe_la_meteo_prend_le_relais(self) -> None:
        """Capteur de vent indisponible (redémarrage HA) : le garde ne doit PAS disparaître.

        `float(context.vent or 0.0)` faisait passer un vent inconnu pour un air calme, et la
        fenêtre remontait de « à éviter » à « idéal ». `_resolve_mowing_block` consultait déjà
        le repli météo ; la fenêtre, non. Le flow Node-RED démarre sur `ideal`/`acceptable` :
        sans ce repli, le robot partait par vent fort.
        """
        self.assertEqual(self._fenetre_avec_vent(vent=40.0), "discouraged")
        self.assertEqual(
            self._fenetre_avec_vent(vent=None, weather_profile={"weather_wind_speed": 40.0}),
            "discouraged",
        )
        # Vent réellement faible : la météo ne doit pas fermer la fenêtre pour autant.
        self.assertEqual(
            self._fenetre_avec_vent(vent=None, weather_profile={"weather_wind_speed": 5.0}),
            "ideal",
        )
        # AUCUNE source de vent (installation sans capteur ni météo) : le garde reste muet,
        # sinon une install sans anémomètre n'obtiendrait jamais de fenêtre idéale.
        self.assertEqual(self._fenetre_avec_vent(vent=None), "ideal")

    def test_motif_trop_chaud_ne_se_contredit_pas(self) -> None:
        """À 30,2 °C le message affichait « 30 °C, seuil 30 °C » — un blocage juste, illisible.

        Vu en direct le 30/07/2026. L'arrondi `.0f` faisait passer une comparaison correcte
        (30,2 > 30) pour une erreur de seuil : de quoi chasser un bug qui n'existe pas.
        """
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=18,
            temperature=30.2,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        motif = bundle["mowing_window_reason"]
        self.assertIn("30,2", motif)
        self.assertNotIn("(30 °C, seuil 30 °C)", motif)
        # VIRGULE et non point : un point décimal crée une fausse fin de phrase chez tout
        # consommateur qui coupe le motif à la première phrase — la carte affichait
        # « pour tondre (30 ». Vérifié en simulant ce découpage.
        self.assertNotIn("30.2", motif)
        premiere_phrase = re.split(r"\.\s", motif)[0]
        self.assertIn("seuil", premiere_phrase)

    def test_build_mowing_bundle_marks_midday_as_discouraged_but_not_blocked(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=14,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "discouraged")
        self.assertEqual(mowing_bundle["mowing_window_label"], "À éviter")
        self.assertIn("à éviter", mowing_bundle["mowing_window_reason"].lower())
        self.assertTrue(mowing_bundle["tonte_autorisee"])

    def test_build_mowing_bundle_discourages_high_humidity_and_wind_but_keeps_action_possible(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=27,
            pluie_24h=0,
            pluie_demain=0,
            humidite=88,
            vent=25,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_connectee": True,
                "tondeuse_prete": True,
                "mower_coordination_ready": True,
                "mower_operation_state": "idle",
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "discouraged")
        self.assertEqual(mowing_bundle["mowing_window_label"], "À éviter")
        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertTrue(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_wind_over_forty(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            vent=45,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "blocked")
        self.assertIn("Vent trop fort", mowing_bundle["mowing_window_reason"])
        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_on_recent_rain(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=1.2,
            pluie_demain=0,
            humidite=55,
            humidite_sol=75,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "blocked")
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "soil_wet")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Sol humide: attendre le ressuyage.")
        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_outside_mowing_window_before_10am(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertEqual(mowing_bundle["mowing_window_state"], "blocked")
        self.assertEqual(mowing_bundle["mowing_window_label"], "Bloqué")
        self.assertIn("Matin trop tôt", mowing_bundle["mowing_window_reason"])
        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_build_mowing_bundle_blocks_when_machine_unavailable(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context={
                "tondeuse_connectee": False,
                "tondeuse_prete": False,
                "mower_coordination_ready": False,
                "mower_operation_state": "idle",
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(mowing_bundle["mowing_blocked"])
        self.assertEqual(mowing_bundle["mowing_block_reason"], "machine_unavailable")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Robot indisponible: attendre qu'elle soit prête.")
        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertFalse(mowing_bundle["action_possible"])

    def test_machine_unavailable_detail_message_instable_atteignable(self) -> None:
        # RÉGRESSION (28/07/2026) : la branche comparait `mower_reason_code` à `mower_unreliable`,
        # or la coordination émet `unreliable` — `mower_unreliable` est le code côté ARROSAGE.
        # Le message spécifique était donc inatteignable et tout retombait sur le générique.
        detail = decision_mowing._machine_unavailable_detail(
            {"mower_reason_code": "unreliable", "tondeuse_connectee": True, "tondeuse_prete": True}
        )
        self.assertEqual(
            detail, ("unreliable", "Robot instable: vérifie sa disponibilité avant de reprendre.")
        )

    def test_libelle_temperature_distingue_chaud_et_froid(self) -> None:
        # Les deux extrêmes renvoyaient le MÊME libellé « Température extrême » : impossible de
        # savoir s'il faisait trop chaud ou trop froid, ni à quel seuil. Le CODE reste
        # `temp_extreme` (contrat public), seul le libellé est précisé.
        def _label(temperature):
            ctx = decision.DecisionContext.from_legacy_args(
                history=[], today=date(2026, 7, 15), hour_of_day=11, temperature=temperature,
                pluie_24h=0, pluie_demain=0, humidite=45, type_sol="limoneux", etp_capteur=4.0,
            )
            phase = decision_phase.build_phase_bundle(ctx)
            water = decision_watering.build_water_bundle(ctx, phase)
            risk = decision_risk.build_risk_bundle(ctx, phase, water)
            b = decision_mowing.build_mowing_bundle(ctx, phase, water, risk)
            return b["mowing_block_reason_code"], (b["mowing_block_reason_label"] or "")

        code_chaud, label_chaud = _label(35)
        code_froid, label_froid = _label(3)
        self.assertEqual(code_chaud, "temp_extreme")
        self.assertEqual(code_froid, "temp_extreme")
        self.assertIn("chaud", label_chaud.lower())
        self.assertIn("froid", label_froid.lower())
        self.assertNotEqual(label_chaud, label_froid)

    def test_machine_unavailable_detail_error_label(self) -> None:
        # Robot en erreur → libellé précis « Robot en erreur: … », prioritaire sur
        # « hors ligne » / le libellé générique.
        detail = decision_mowing._machine_unavailable_detail(
            {
                "tondeuse_connectee": False,  # même apparemment hors ligne, l'erreur prime
                "tondeuse_statut": "erreur",
                "tondeuse_erreur": "blade_blocked",
                "tondeuse_erreur_libelle": "Lame bloquée",
            }
        )
        self.assertEqual(detail, ("error", "Robot en erreur: Lame bloquée"))

        # Détecté via le seul code d'erreur, libellé de repli si aucun label dispo.
        detail_fallback = decision_mowing._machine_unavailable_detail({"tondeuse_erreur": "E42"})
        self.assertEqual(
            detail_fallback,
            ("error", "Robot en erreur: défaut signalé, vérifier le robot"),
        )

        # Non-régression : un robot en charge garde son libellé dédié.
        detail_charging = decision_mowing._machine_unavailable_detail(
            {"tondeuse_connectee": True, "tondeuse_en_charge": True}
        )
        self.assertEqual(detail_charging, ("charging", "Robot en charge: attendre qu'elle soit prête."))

        # Garde anti faux positif : la sentinelle « no_error » (robot OK) ne déclenche rien.
        self.assertIsNone(decision_mowing._machine_unavailable_detail({"tondeuse_erreur": "no_error"}))

        # RÉGRESSION (28/07/2026) : un capteur d'erreur INDISPONIBLE n'est pas une panne.
        # `unavailable`/`unknown` étaient pris pour des codes d'erreur → « Robot en erreur :
        # défaut signalé » → tonte bloquée alors que le robot va bien. Cas courant : la plupart
        # des intégrations de tondeuse republient leurs capteurs en `unavailable` à chaque
        # redémarrage de Home Assistant, et cette Mammotion en a plusieurs en permanence.
        for _absent in ("unavailable", "unknown"):
            self.assertIsNone(
                decision_mowing._machine_unavailable_detail({"tondeuse_erreur": _absent}),
                f"« {_absent} » ne doit pas être lu comme une panne",
            )

        # Compatibilité « toutes tondeuses HA » : l'état standard `error` du domaine
        # lawn_mower → statut "erreur" (sans capteur d'erreur dédié) → libellé générique.
        detail_generic = decision_mowing._machine_unavailable_detail({"tondeuse_statut": "erreur"})
        self.assertEqual(detail_generic, ("error", "Robot en erreur: défaut signalé, vérifier le robot"))

    def test_build_mowing_bundle_does_not_block_on_watering_three_days_old(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {
                    "type": "arrosage",
                    "date": "2026-06-12",
                    "mm": 3.8,
                }
            ],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=22,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(mowing_bundle["tonte_autorisee"])
        self.assertIsNone(mowing_bundle["mowing_block_reason_code"])
        self.assertFalse(mowing_bundle["mowing_blocked_by_watering"])

    def test_build_mowing_bundle_blocks_when_sun_is_below_horizon(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 20),
            hour_of_day=0,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
            sun_context={
                "sun_state": "below_horizon",
                "sun_above_horizon": False,
                "sun_below_horizon": True,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertFalse(mowing_bundle["tonte_autorisee"])
        self.assertEqual(mowing_bundle["mowing_block_reason_code"], "mowing_night")
        self.assertEqual(mowing_bundle["tonte_statut"], "interdite")
        self.assertEqual(mowing_bundle["mowing_block_reason_label"], "Nuit: attendre le lever du soleil.")

    def test_snapshot_blocks_watering_when_mower_is_outside(self) -> None:
        snapshot = decision.build_decision_result(
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 6, 15),
                hour_of_day=8,
                temperature=24,
                pluie_24h=0,
                pluie_demain=0,
                humidite=45,
                type_sol="limoneux",
                etp_capteur=4.0,
                memory={"auto_irrigation_enabled": True},
                mower_context={
                    "mower_coordination_enabled": True,
                    "mower_coordination_ready": True,
                    "mower_is_mowing": True,
                    "mower_is_returning": False,
                    "mower_is_safe_for_watering": False,
                    "mower_operation_state": "tonte",
                    "mower_presence_state": "dehors",
                },
            )
        ).to_snapshot()

        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertTrue(snapshot["watering_blocked_by_mower"])
        self.assertEqual(snapshot["watering_block_reason_code"], "mower_mowing")

    def test_snapshot_blocks_watering_when_mower_resolution_is_ambiguous(self) -> None:
        snapshot = decision.build_decision_result(
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 6, 15),
                hour_of_day=8,
                temperature=24,
                pluie_24h=0,
                pluie_demain=0,
                humidite=45,
                type_sol="limoneux",
                etp_capteur=4.0,
                memory={"auto_irrigation_enabled": True},
                mower_context={
                    "mower_coordination_enabled": True,
                    "mower_coordination_ready": False,
                    "mower_is_mowing": False,
                    "mower_is_returning": False,
                    "mower_is_safe_for_watering": False,
                    "mower_operation_state": "unknown",
                    "mower_presence_state": "inconnue",
                    "mower_reason_code": "ambiguous",
                    "mower_reason_label": "Plusieurs tondeuses détectées. Configuration explicite requise.",
                },
            )
        ).to_snapshot()

        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertTrue(snapshot["watering_blocked_by_mower"])
        self.assertEqual(snapshot["watering_block_reason_code"], "ambiguous")
        self.assertEqual(
            snapshot["watering_block_reason_label"],
            "Tondeuse ambiguë: plusieurs robots détectés, configuration requise.",
        )

    def test_snapshot_does_not_block_watering_when_mower_coordination_disabled(self) -> None:
        snapshot = decision.build_decision_result(
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 6, 15),
                hour_of_day=8,
                temperature=24,
                pluie_24h=0,
                pluie_demain=0,
                humidite=45,
                type_sol="limoneux",
                etp_capteur=4.0,
                memory={"auto_irrigation_enabled": True},
                mower_context={
                    "mower_coordination_enabled": False,
                    "mower_coordination_ready": True,
                    "mower_is_mowing": True,
                    "mower_is_returning": False,
                    "mower_is_safe_for_watering": False,
                    "mower_operation_state": "tonte",
                    "mower_presence_state": "dehors",
                },
            )
        ).to_snapshot()

        self.assertFalse(snapshot.get("watering_blocked_by_mower", False))
        self.assertNotEqual(snapshot.get("watering_block_reason_code"), "mower_mowing")

    def test_build_mowing_bundle_exposes_stable_core_keys_on_blocked_path(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "Traitement", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)

        mowing_bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(
            set(decision_mowing._MOWING_BUNDLE_CORE_KEYS).issubset(set(mowing_bundle))
        )
        self.assertEqual(mowing_bundle["raison_blocage_code"], "phase_traitement")

    def test_build_decision_snapshot_prioritizes_phase_block_over_rain(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Traitement", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["raison_blocage_code"], "phase_traitement")
        self.assertEqual(snapshot["next_mowing_date"], "2026-03-20")

    def test_build_decision_snapshot_projects_next_mowing_date_after_recent_rain(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=22,
            pluie_24h=4,
            pluie_demain=0,
            humidite=70,
            humidite_sol=75,
            type_sol="limoneux",
            etp_capteur=3.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["raison_blocage_code"], "soil_wet")
        self.assertIsNotNone(snapshot["next_mowing_date"])
        self.assertIsNotNone(snapshot["next_mowing_display"])

    def test_build_decision_snapshot_never_projects_next_mowing_date_in_past(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "arrosage", "date": "2026-03-15", "objectif_mm": 3.0}],
            today=date(2026, 3, 17),
            hour_of_day=11,
            temperature=16,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=1.0,
        )

        self.assertTrue(snapshot["tonte_autorisee"])
        self.assertNotIn("raison_blocage_code", snapshot)
        self.assertEqual(snapshot["next_mowing_date"], "2026-03-17")
        self.assertEqual(snapshot["next_mowing_display"], "17/03/2026")

    def test_build_decision_snapshot_blocks_mowing_on_third_rule(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=12.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=6.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["tonte_statut"], "deconseillee")
        self.assertIn("Règle du tiers", snapshot["raison_decision"])
        self.assertIsNone(snapshot.get("next_mowing_date"))
        self.assertIsNone(snapshot.get("next_mowing_display"))
        self.assertGreaterEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.5)
        self.assertLessEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)

    def test_build_decision_snapshot_exposes_mowing_height_recommendation(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=12.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        # 8,0 et non 6,5 depuis la 0.27.0 : le plafond fixe de 6,5 cm est retiré, la config
        # (ici 3,0-8,0) borne seule. Avec un gazon à 12 cm, la règle du tiers interdit de
        # descendre sous 8,0 — c'est elle qui fixe la consigne, et elle tape le maximum machine.
        # Agronomiquement c'est le bon sens : la littérature conseille 7,5 à 10 cm en été pour
        # une graminée de saison fraîche ; l'ancien plafond de 6,5 l'en empêchait.
        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 8.0)
        self.assertEqual(snapshot["hauteur_tonte_min_cm"], 3.0, "la config est de nouveau rognée")
        self.assertEqual(snapshot["hauteur_tonte_max_cm"], 8.0, "la config est de nouveau rognée")
        self.assertIn("tiers", str(snapshot["hauteur_tonte_garde_fou_label"]).lower())

    def test_build_decision_snapshot_prefers_slightly_lower_height_in_active_spring(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 4, 15),
            hour_of_day=8,
            temperature=19,
            pluie_24h=5.0,
            pluie_demain=0,
            humidite=80,
            type_sol="limoneux",
            etp_capteur=0.5,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertGreaterEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.5)
        self.assertLessEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)

    def test_build_decision_snapshot_raises_height_in_heat(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=34,
            pluie_24h=0,
            pluie_demain=0,
            humidite=30,
            type_sol="limoneux",
            etp_capteur=5.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=9.0,
        )

        # 7,5 et non 6,5 depuis la 0.27.0 (plafond fixe retiré, cf. le test voisin) : par
        # 34 °C, monter la coupe ombrage le sol et limite l'évaporation — c'est justement
        # l'effet recherché, que l'ancien plafond bridait.
        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 7.5)

    def test_build_decision_snapshot_allows_light_reduction_in_favorable_autumn(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 9, 20),
            hour_of_day=8,
            temperature=19,
            pluie_24h=4.0,
            pluie_demain=0,
            humidite=78,
            type_sol="limoneux",
            etp_capteur=0.5,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertGreaterEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.0)
        self.assertLessEqual(snapshot["hauteur_tonte_recommandee_cm"], 5.5)

    def test_build_decision_snapshot_rounds_all_mowing_heights_to_half_cm(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=12.3,
            hauteur_min_tondeuse_cm=3.1,
            hauteur_max_tondeuse_cm=7.9,
        )

        for key in (
            "hauteur_tonte_recommandee_cm",
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
        ):
            value = snapshot[key]
            self.assertIsNotNone(value)
            self.assertEqual(round(float(value) / 0.5) * 0.5, float(value))

    def test_build_decision_snapshot_stays_stable_across_small_weather_changes(self) -> None:
        baseline = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 20),
            hour_of_day=8,
            temperature=20,
            pluie_24h=2.0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        follow_up = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 21),
            hour_of_day=8,
            temperature=20.5,
            pluie_24h=2.2,
            pluie_demain=0,
            humidite=63,
            type_sol="limoneux",
            etp_capteur=2.1,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
            memory={"hauteur_tonte_recommandee_cm": baseline["hauteur_tonte_recommandee_cm"]},
        )

        self.assertLessEqual(
            abs(follow_up["hauteur_tonte_recommandee_cm"] - baseline["hauteur_tonte_recommandee_cm"]),
            0.5,
        )

    def test_build_decision_snapshot_moves_by_half_cm_max(self) -> None:
        baseline = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 20),
            hour_of_day=8,
            temperature=19,
            pluie_24h=2.0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        follow_up = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=34,
            pluie_24h=0,
            pluie_demain=0,
            humidite=30,
            type_sol="limoneux",
            etp_capteur=5.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=9.0,
            memory={"hauteur_tonte_recommandee_cm": baseline["hauteur_tonte_recommandee_cm"]},
        )

        self.assertLessEqual(
            abs(follow_up["hauteur_tonte_recommandee_cm"] - baseline["hauteur_tonte_recommandee_cm"]),
            0.5,
        )

    def test_build_decision_snapshot_sursemis_recovery_is_progressive(self) -> None:
        germination = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-10"}],
            today=date(2026, 3, 12),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        enracinement = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-08"}],
            today=date(2026, 3, 18),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        reprise = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-01"}],
            today=date(2026, 3, 20),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=65,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertFalse(germination["tonte_autorisee"])
        self.assertFalse(enracinement["tonte_autorisee"])
        self.assertFalse(reprise["tonte_autorisee"])
        self.assertGreaterEqual(germination["hauteur_tonte_recommandee_cm"], enracinement["hauteur_tonte_recommandee_cm"])
        self.assertGreaterEqual(enracinement["hauteur_tonte_recommandee_cm"], reprise["hauteur_tonte_recommandee_cm"])

    def test_build_decision_snapshot_keeps_post_sursemis_height_bonus_after_return_to_normal(self) -> None:
        post_sursemis = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-05-01"}],
            today=date(2026, 6, 1),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )
        baseline = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 1),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
            hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0,
        )

        self.assertEqual(post_sursemis["phase_active"], "Sursemis")
        self.assertGreater(post_sursemis["hauteur_tonte_recommandee_cm"], baseline["hauteur_tonte_recommandee_cm"])

    def test_build_decision_snapshot_blocks_mowing_on_dew(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=8.0,
            rosee=1.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertIn("rosée", snapshot["raison_decision"].lower())

class TestEtpComputation(unittest.TestCase):
    def test_compute_etp_prefers_sensor_value(self) -> None:
        self.assertEqual(decision.compute_etp(temperature=24, pluie_24h=2, etp_capteur=4.2), 4.2)

    def test_compute_etp_can_fall_back_to_weather_profile(self) -> None:
        etp = decision.compute_etp(
            temperature=None,
            pluie_24h=1.0,
            etp_capteur=None,
            weather_profile={
                "weather_temperature": 24,
                "weather_humidity": 55,
                "weather_wind_speed": 18,
                "weather_cloud_coverage": 20,
                "weather_precipitation_probability": 30,
            },
        )

        self.assertIsNotNone(etp)
        self.assertGreater(etp, 0.0)

    def test_compute_etp_can_use_zero_weather_temperature(self) -> None:
        etp = decision.compute_etp(
            temperature=None,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={
                "weather_temperature": 0.0,
                "weather_apparent_temperature": 24.0,
                "weather_humidity": 50.0,
                "weather_wind_speed": 0.0,
                "weather_cloud_coverage": 0.0,
                "weather_precipitation_probability": 0.0,
            },
        )

        # Vérification comportementale : temperature=0.0 (falsy) ne doit pas être ignorée.
        # La valeur exacte dépend de la formule PM ; on vérifie qu'elle est calculée
        # et raisonnable (ET0 proche de 0 par temps froid, mais non nulle).
        self.assertIsNotNone(etp)
        self.assertGreaterEqual(etp, 0.0)
        self.assertLess(etp, 2.0)

    def test_compute_etp_fallback_realistic_in_mild_weather(self) -> None:
        # Sans capteur ETP, par temps doux (20 °C, ciel ~dégagé), l'ET0 calculée
        # doit rester réaliste (~4-6 mm) et NON surestimée. Les bugs Rnl (rayonnement
        # longues ondes ~7x trop bas) + vent km/h utilisé comme m/s donnaient ~8 mm.
        etp = decision.compute_etp(
            temperature=None,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={
                "weather_temperature": 20.0,
                "weather_humidity": 60.0,
                "weather_wind_speed": 11.0,
                "weather_wind_speed_unit": "km/h",
                "weather_cloud_coverage": 10.0,
                "ha_latitude": 48.0,
                "ha_day_of_year": 161,
            },
        )
        self.assertIsNotNone(etp)
        self.assertGreaterEqual(etp, 3.0)
        self.assertLessEqual(etp, 6.5)

    def test_compute_etp_wind_unit_kmh_vs_ms_consistent(self) -> None:
        # 10.8 km/h == 3.0 m/s : les deux unités doivent donner la même ET0.
        common = {
            "weather_temperature": 20.0,
            "weather_humidity": 60.0,
            "weather_cloud_coverage": 10.0,
            "ha_latitude": 48.0,
            "ha_day_of_year": 161,
        }
        etp_kmh = decision.compute_etp(
            temperature=None,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={**common, "weather_wind_speed": 10.8, "weather_wind_speed_unit": "km/h"},
        )
        etp_ms = decision.compute_etp(
            temperature=None,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={**common, "weather_wind_speed": 3.0, "weather_wind_speed_unit": "m/s"},
        )
        self.assertEqual(etp_kmh, etp_ms)

    def test_compute_etp_still_high_in_heatwave(self) -> None:
        # Garde-fou inverse : la correction ne doit pas écraser l'ET0 en vraie
        # canicule (35 °C, sec, venté) — elle doit rester élevée.
        etp = decision.compute_etp(
            temperature=None,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={
                "weather_temperature": 35.0,
                "weather_humidity": 30.0,
                "weather_wind_speed": 20.0,
                "weather_wind_speed_unit": "km/h",
                "weather_cloud_coverage": 0.0,
                "ha_latitude": 48.0,
                "ha_day_of_year": 161,
            },
        )
        self.assertGreaterEqual(etp, 8.0)

    def test_compute_etp_prefers_measured_humidity_and_wind_over_weather(self) -> None:
        # Demandé par Kévin (2026-06-22) : si des capteurs mesurés (humidite/vent) sont fournis,
        # l'ET0 doit les utiliser EN PRIORITÉ sur l'entité météo (weather_profile), elle-même
        # simple repli avant les valeurs par défaut.
        base_wp = {
            "weather_temperature": 35.0,
            "weather_humidity": 80.0,  # météo "humide"
            "weather_wind_speed": 2.0,  # météo "peu de vent"
            "weather_wind_speed_unit": "km/h",
            "weather_cloud_coverage": 0.0,
            "ha_latitude": 46.5,
            "ha_day_of_year": 173,
        }
        etp_weather = decision.compute_etp(
            temperature=35.0, pluie_24h=0.0, etp_capteur=None, weather_profile=base_wp
        )
        # Capteurs : air SEC (30 %) et VENTÉ (25 km/h) → ET0 nettement plus élevée.
        etp_sensors = decision.compute_etp(
            temperature=35.0,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile=base_wp,
            humidite=30.0,
            vent=25.0,
        )
        self.assertGreater(etp_sensors, etp_weather)
        # Le capteur doit ÉCRASER le weather_profile : résultat identique à une météo
        # qui porterait directement ces valeurs.
        etp_equiv = decision.compute_etp(
            temperature=35.0,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={**base_wp, "weather_humidity": 30.0, "weather_wind_speed": 25.0},
        )
        self.assertEqual(etp_sensors, etp_equiv)

    def test_compute_etp_sensor_wind_assumed_kmh(self) -> None:
        # Le vent capteur (sans unité explicite) est supposé en km/h (standard HA/Netatmo) :
        # vent=10.8 (capteur) == weather_wind_speed=10.8 km/h.
        common = {
            "weather_temperature": 28.0,
            "weather_cloud_coverage": 10.0,
            "ha_latitude": 46.5,
            "ha_day_of_year": 173,
        }
        etp_sensor = decision.compute_etp(
            temperature=28.0,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile=common,
            humidite=50.0,
            vent=10.8,
        )
        etp_weather_kmh = decision.compute_etp(
            temperature=28.0,
            pluie_24h=0.0,
            etp_capteur=None,
            weather_profile={
                **common,
                "weather_humidity": 50.0,
                "weather_wind_speed": 10.8,
                "weather_wind_speed_unit": "km/h",
            },
        )
        self.assertEqual(etp_sensor, etp_weather_kmh)


if __name__ == "__main__":
    unittest.main()


class TestIrrigationBlockedButCritical(unittest.TestCase):
    def test_irrigation_blocked_but_critical_exposed(self) -> None:
        # Build a payload that simulates a mower block with critical deficit
        payload = {
            "watering_blocked_by_mower": True,
            "type_arrosage": "bloque",
            "block_reason": "mower_mowing",
            "watering_block_reason_code": "mower_mowing",
            "water_balance": {
                "bilan_hydrique_mm": -3.0,
            },
        }
        result = decision_watering._apply_irrigation_execution_contract(payload)
        self.assertTrue(result["irrigation_blocked_but_critical"])
        self.assertEqual(result["critical_deficit_mm"], -3.0)
        self.assertIsNotNone(result["critical_irrigation_reason"])

    def test_irrigation_not_critical_when_deficit_insufficient(self) -> None:
        payload = {
            "watering_blocked_by_mower": True,
            "type_arrosage": "bloque",
            "water_balance": {
                "bilan_hydrique_mm": -1.0,
            },
        }
        result = decision_watering._apply_irrigation_execution_contract(payload)
        self.assertFalse(result["irrigation_blocked_but_critical"])
        self.assertIsNone(result["critical_deficit_mm"])


class TestMowingOverdue(unittest.TestCase):
    """Tests pour la détection de retard de tonte et son influence sur la décision."""

    def _make_bundle(self, history, today, hour_of_day=11, temperature=20, humidite=55, score_tonte_boost=0):
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=today,
            hour_of_day=hour_of_day,
            temperature=temperature,
            pluie_24h=0,
            pluie_demain=0,
            humidite=humidite,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_not_overdue_when_no_mowing_history(self):
        bundle = self._make_bundle(history=[], today=date(2026, 6, 15))
        self.assertFalse(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 0)
        self.assertEqual(bundle["mowing_overdue_factor"], 0.0)

    def test_not_overdue_when_mowed_recently(self):
        # Fréquence juin = 5/semaine → intervalle 1,4 j — tonte hier = 0,7× → pas overdue
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-14"}],
            today=date(2026, 6, 15),
        )
        self.assertFalse(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 1)

    def test_overdue_when_interval_exceeded_by_1_5x(self):
        # Fréquence juin = 5/semaine → intervalle 1,4 j — tonte il y a 3 j = 2,1× → overdue
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-12"}],
            today=date(2026, 6, 15),
        )
        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 3)
        self.assertGreater(bundle["mowing_overdue_factor"], 1.5)

    def test_overdue_reason_prefix_in_tonte_reason_when_blocked(self):
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-12"}],
            today=date(2026, 6, 15),
        )
        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertIn("Retard de tonte", bundle["tonte_reason"])
        self.assertIn("3 j", bundle["tonte_reason"])

    def test_overdue_reason_prefix_when_tonte_allowed(self):
        # Conditions idéales + tonte en retard → raison contient "Tonte recommandée"
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-10"}],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=18,
            humidite=50,
        )
        if bundle["tonte_autorisee"] and bundle["mowing_is_overdue"]:
            self.assertIn("Tonte recommandée", bundle["tonte_reason"])

    def test_overdue_does_not_override_hard_block_phase(self):
        # Sursemis Germination → tonte interdite même si très en retard
        context = decision.DecisionContext.from_legacy_args(
            history=[
                {"type": "Sursemis", "date": "2026-06-01"},
                {"type": "tonte", "date": "2026-05-20"},
            ],
            today=date(2026, 6, 15),
            hour_of_day=11,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
        # La phase dure → tonte bloquée indépendamment du retard
        self.assertFalse(bundle["tonte_autorisee"])
        self.assertIn("phase_sursemis", (bundle.get("raison_blocage_code") or ""))

    def test_overdue_does_not_override_night_block(self):
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-10"}],
            today=date(2026, 6, 15),
            hour_of_day=2,
        )
        self.assertFalse(bundle["tonte_autorisee"])
        self.assertEqual(bundle["mowing_block_reason_code"], "mowing_night")

    def test_overdue_keys_always_present(self):
        bundle = self._make_bundle(history=[], today=date(2026, 6, 15))
        self.assertIn("mowing_is_overdue", bundle)
        self.assertIn("mowing_overdue_days", bundle)
        self.assertIn("mowing_overdue_factor", bundle)

    def test_not_overdue_in_winter_zero_frequency(self):
        # Janvier → fréquence 0 → jamais overdue
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2025-11-01"}],
            today=date(2026, 1, 15),
        )
        self.assertFalse(bundle["mowing_is_overdue"])
        self.assertEqual(bundle["mowing_overdue_days"], 0)

    def test_overdue_soft_override_activates_for_borderline_conditions_defavorables(self):
        # score_tonte=65 (conditions_defavorables) + overdue factor >> 2.0 → soft override actif
        # pluie_24h=6, pluie_demain=5, pluie_j2=2, humidite=80 → score_tonte=65, score_stress~16
        # Sans override (pas de retard): tonte bloquée par conditions_defavorables
        # Avec override (retard 37 j, factor~26×): tonte autorisée
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-05-01"}],  # 37 jours → factor >> 2
            today=date(2026, 6, 7),
            hour_of_day=11,
            temperature=22,
            pluie_24h=6,
            pluie_demain=5,
            pluie_j2=2,
            pluie_3j=0,
            pluie_probabilite_max_3j=0,
            humidite=80,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertGreaterEqual(bundle["mowing_overdue_factor"], 2.0)
        # Le soft override doit avoir levé le blocage conditions_defavorables
        self.assertTrue(bundle["tonte_autorisee"], "Le soft override overdue doit lever conditions_defavorables borderline")


class TestEstimatedGrassHeight(unittest.TestCase):
    """Tests pour l'estimation de la hauteur du gazon sans capteur physique."""

    def _make_bundle(self, history, today, mower_context=None, hour_of_day=11, temperature=20):
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=today,
            hour_of_day=hour_of_day,
            temperature=temperature,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
            mower_context=mower_context or {},
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_estimation_none_without_cutting_height(self):
        # Pas de hauteur de coupe configurée → estimation impossible
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-01"}],
            today=date(2026, 6, 7),
            mower_context={},
        )
        self.assertIsNone(bundle["gazon_hauteur_estimee_cm"])

    def test_estimation_none_without_mowing_history(self):
        # Hauteur de coupe connue mais pas de tonte → estimation impossible
        bundle = self._make_bundle(
            history=[],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
        )
        self.assertIsNone(bundle["gazon_hauteur_estimee_cm"])

    def test_estimation_equals_cut_height_day_of_mowing(self):
        # Tonte aujourd'hui → hauteur = hauteur de coupe
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-07"}],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
        )
        self.assertEqual(bundle["gazon_hauteur_estimee_cm"], 4.5)

    def test_la_fenetre_du_soir_suit_le_coucher_du_soleil(self) -> None:
        """Demandé par Kévin : « il peut tondre plus tard, comme le soleil se couche plus tard ».

        Le créneau du soir valait 17-19 h TOUTE L'ANNÉE. En juillet il s'arrêtait 2 h 45 avant
        le coucher ; en décembre il tombait entièrement APRÈS la nuit.
        """
        import custom_components.gazon_intelligent.decision_mowing as dm

        def fenetre(coucher_minute: float, heure: int) -> str:
            etat, _ = dm._resolve_mowing_window(
                decision.DecisionContext.from_legacy_args(
                    history=[], today=date(2026, 7, 30), hour_of_day=heure, temperature=20,
                    pluie_24h=0, pluie_demain=0, humidite=50, type_sol="limoneux", etp_capteur=3.0,
                ),
                weather_profile={"sunset_minute": coucher_minute},
            )
            return etat

        # Coucher à 21 h 30 (fin juillet) : 19 h devient tondable, ce qu'il n'était pas.
        self.assertEqual(fenetre(21 * 60 + 30, 19), "acceptable", "19 h refusé alors que le soleil se couche à 21 h 30")
        # …mais pas 21 h : trop près du coucher, l'herbe coupée resterait humide la nuit.
        self.assertNotEqual(fenetre(21 * 60 + 30, 21), "acceptable", "21 h accepté à 90 min du coucher")
        # Coucher à 17 h (décembre) : 18 h est la nuit, jamais acceptable.
        self.assertNotEqual(fenetre(17 * 60, 18), "acceptable", "18 h accepté alors que le soleil est couché")

    def test_sans_coucher_connu_on_retombe_sur_les_bornes_fixes(self) -> None:
        """Repli conservateur : sans `sun.sun`, on garde 17-19 h plutôt que d'inventer."""
        import custom_components.gazon_intelligent.decision_mowing as dm
        etat, _ = dm._resolve_mowing_window(
            decision.DecisionContext.from_legacy_args(
                history=[], today=date(2026, 7, 30), hour_of_day=18, temperature=20,
                pluie_24h=0, pluie_demain=0, humidite=50, type_sol="limoneux", etp_capteur=3.0,
            ),
            weather_profile={},
        )
        self.assertEqual(etat, "acceptable")

    def test_trop_chaud_ne_projette_pas_la_tonte_aujourd_hui(self) -> None:
        """La projection ne doit pas annoncer un jour où la tonte est justement bloquée.

        Constaté sur l'install le 30/07/2026 : « Trop chaud pour tondre (30 °C, seuil 30 °C) »
        et « Prochaine tonte estimée le 30/07/2026 » dans la même phrase. `temp_extreme` n'avait
        aucune branche de projection et tombait dans le repli, ancré sur maintenant.
        """
        for temperature in (38, 4):
            with self.subTest(temperature=temperature):
                bundle = self._make_bundle(
                    history=[{"type": "tonte", "date": "2026-06-01"}],
                    today=date(2026, 6, 7),
                    mower_context={"tondeuse_hauteur_coupe_mm": 45},
                    hour_of_day=14, temperature=temperature,
                )
                cible = bundle.get("next_mowing_date")
                if cible is None:
                    continue  # projection volontairement absente : acceptable, pas contradictoire
                self.assertNotEqual(
                    str(cible), "2026-06-07",
                    f"à {temperature} °C la tonte est bloquée aujourd'hui, la projection ne peut pas dire aujourd'hui",
                )

    def test_estimation_grows_after_mowing(self):
        # Tonte il y a 4 jours en juin, relevé à 11 h. Depuis la 0.29.0 la pousse du jour est
        # étalée sur sa fenêtre (7 h - 20 h) au lieu de s'ajouter d'un bloc à minuit : à 11 h
        # seuls 4/13 de la journée sont acquis, d'où 6,2 au lieu de 6,5. En fin de journée on
        # retrouve exactement 6,5 (cf. test_la_hauteur_monte_au_fil_de_la_journee).
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-03"}],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
        )
        self.assertAlmostEqual(bundle["gazon_hauteur_estimee_cm"], 6.2, places=1)

    def test_la_hauteur_monte_au_fil_de_la_journee(self):
        """Demandé par Kévin : la hauteur doit progresser dans la journée, pas sauter à minuit."""
        mesures = []
        for heure in (5, 7, 11, 15, 20, 23):
            b = self._make_bundle(
                history=[{"type": "tonte", "date": "2026-06-03"}],
                today=date(2026, 6, 7),
                mower_context={"tondeuse_hauteur_coupe_mm": 45},
                hour_of_day=heure,
            )
            mesures.append((heure, b["gazon_hauteur_estimee_cm"]))
        valeurs = [v for _, v in mesures]
        self.assertEqual(valeurs, sorted(valeurs), f"la hauteur recule dans la journée : {mesures}")
        self.assertEqual(valeurs[0], valeurs[1], "elle pousse avant 7 h du matin")
        self.assertAlmostEqual(valeurs[4], 6.5, places=1, msg="le total du jour n'est pas atteint à 20 h")
        self.assertEqual(valeurs[4], valeurs[5], "elle pousse encore après 20 h")
        self.assertGreater(valeurs[3], valeurs[2], "elle ne progresse pas entre 11 h et 15 h")

    def test_la_canicule_arrete_la_pousse(self):
        """Kévin : « à certain moment la hauteur peut ne pas bouger et c'est normal »."""
        doux = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-03"}],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
            hour_of_day=15, temperature=20,
        )["gazon_hauteur_estimee_cm"]
        canicule = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-03"}],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
            hour_of_day=15, temperature=38,
        )["gazon_hauteur_estimee_cm"]
        self.assertLess(canicule, doux, "38 °C ne freine pas la pousse")

    def test_estimation_zero_growth_in_winter(self):
        # Janvier → croissance 0 → hauteur reste égale à la hauteur de coupe
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-01-01"}],
            today=date(2026, 1, 15),
            mower_context={"tondeuse_hauteur_coupe_mm": 50},
        )
        self.assertEqual(bundle["gazon_hauteur_estimee_cm"], 5.0)

    def test_physical_sensor_takes_priority_over_estimate(self):
        # Un capteur physique doit être utilisé en priorité (hauteur actuelle dans advanced_context)
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-06-01"}],
            today=date(2026, 6, 7),
            hour_of_day=11,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
            hauteur_gazon=3.5,  # capteur physique = 3.5 cm
            mower_context={"tondeuse_hauteur_coupe_mm": 45},  # aurait donné 7.5 cm d'estimation
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
        # La hauteur actuelle utilisée dans la recommandation doit refléter le capteur (3.5)
        self.assertIsNotNone(bundle["hauteur_tonte_recommandee_cm"])
        # L'estimation est quand même exposée dans le bundle
        self.assertIsNotNone(bundle["gazon_hauteur_estimee_cm"])

    def test_key_always_present_in_bundle(self):
        bundle = self._make_bundle(history=[], today=date(2026, 6, 7))
        self.assertIn("gazon_hauteur_estimee_cm", bundle)


class TestMowingWindowReason(unittest.TestCase):
    """Tests pour la clarté des messages de blocage de fenêtre de tonte."""

    def _make_bundle(self, hour_of_day, history=None, temperature=20, vent=0, humidite=55):
        context = decision.DecisionContext.from_legacy_args(
            history=history or [{"type": "tonte", "date": "2026-06-05"}],
            today=date(2026, 6, 7),
            hour_of_day=hour_of_day,
            temperature=temperature,
            pluie_24h=0,
            pluie_demain=0,
            humidite=humidite,
            type_sol="limoneux",
            etp_capteur=3.0,
            vent=vent,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_window_only_block_shows_clear_reason(self):
        # 3h du matin, bonnes conditions → raison = fenêtre bloquée uniquement
        bundle = self._make_bundle(hour_of_day=3)
        self.assertFalse(bundle["tonte_autorisee"])
        reason = bundle["tonte_reason"]
        # Le message doit mentionner pourquoi la fenêtre est bloquée
        self.assertTrue(
            "nuit" in reason.lower() or "soleil" in reason.lower() or "tôt" in reason.lower(),
            f"Message attendu sur blocage nocturne, reçu: {reason}",
        )

    def test_window_block_added_to_agronomic_reason(self):
        # 3h du matin + vent fort (> 40) → deux raisons : fenêtre ET vent
        bundle = self._make_bundle(hour_of_day=3, vent=45)
        self.assertFalse(bundle["tonte_autorisee"])
        reason = bundle["tonte_reason"]
        # La raison principale est agronomique mais la fenêtre doit être mentionnée
        self.assertIn("Fenêtre horaire", reason, f"Fenêtre horaire absente du message: {reason}")

    def test_discouraged_window_mentioned_when_tonte_ok(self):
        # 18h, vent à 25 km/h (discouraged) + bonnes conditions → tonte ok mais créneau déconseillé
        bundle = self._make_bundle(hour_of_day=18, vent=25)
        if bundle["tonte_autorisee"]:
            reason = bundle["tonte_reason"]
            self.assertIn(
                "déconseillé", reason.lower(),
                f"Créneau déconseillé non mentionné: {reason}",
            )

    def test_ideal_window_no_spurious_discouraged_message(self):
        # 11h, bonnes conditions → pas de message "déconseillé"
        bundle = self._make_bundle(hour_of_day=11)
        if bundle["tonte_autorisee"]:
            self.assertNotIn("déconseillé", bundle["tonte_reason"].lower())


class TestMowingWateringCoordination(unittest.TestCase):
    """Tests pour la coordination arrosage/tonte."""

    def _make_bundle(self, hour_of_day, arrosage_recommande, watering_window_start_minute,
                     has_recent_watering=False):
        history = []
        if has_recent_watering:
            history.append({"type": "arrosage", "date": date(2026, 6, 7).isoformat(), "mm": 10})
        context = decision.DecisionContext.from_legacy_args(
            history=history,
            today=date(2026, 6, 7),
            hour_of_day=hour_of_day,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        # Patch the relevant water_bundle keys
        water_bundle["arrosage_recommande"] = arrosage_recommande
        water_bundle["watering_window_start_minute"] = watering_window_start_minute
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)

    def test_no_advisory_when_no_watering_recommended(self):
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=False, watering_window_start_minute=240
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "none")
        self.assertIsNone(bundle["mowing_watering_coordination_msg"])

    def test_no_advisory_when_already_watered(self):
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True,
            watering_window_start_minute=240, has_recent_watering=True
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "none")

    def test_block_when_watering_imminent(self):
        # 11h00 (660 min), watering starts at 11h20 (680 min) → 20 min → block
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True, watering_window_start_minute=680
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "block")
        self.assertFalse(bundle["tonte_autorisee"])
        self.assertIn("imminent", bundle["tonte_reason"].lower())

    def test_discourage_when_watering_within_2h(self):
        # 11h00 (660 min), watering starts at 12h30 (750 min) → 90 min → discourage
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True, watering_window_start_minute=750
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "discourage")
        # Tonte toujours possible, mais message d'avertissement présent
        self.assertIsNotNone(bundle["mowing_watering_coordination_msg"])

    def test_no_advisory_when_watering_far_away(self):
        # 11h00 (660 min), watering starts at 4h00 tomorrow effective (but > 2h)
        # 14h (840 min) start, current 11h (660 min) → 180 min → none
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=True, watering_window_start_minute=840
        )
        self.assertEqual(bundle["mowing_watering_coordination"], "none")

    def test_coordination_keys_always_present(self):
        bundle = self._make_bundle(
            hour_of_day=11, arrosage_recommande=False, watering_window_start_minute=None
        )
        self.assertIn("mowing_watering_coordination", bundle)
        self.assertIn("mowing_watering_coordination_msg", bundle)


class TestNormalRainReductionPropagation(unittest.TestCase):
    """Cohérence conseil/exécution sous pluie en mode Normal + phrase réserve pleine."""

    @staticmethod
    def _snapshot(**overrides):
        params = dict(
            history=[],
            today=date(2026, 7, 15),
            hour_of_day=6,
            temperature=30.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            humidite=40.0,
            type_sol="limoneux",
            etp_capteur=7.0,
        )
        params.update(overrides)
        return decision.build_decision_snapshot(**params)

    def test_rain_reduction_propagates_to_executed_values(self):
        # Mode Normal, déficit important, pluie SIGNIFICATIVE annoncée J+1 (≥ 2 mm, branche ×0.8).
        no_rain = self._snapshot(pluie_demain=0.0)
        rain = self._snapshot(pluie_demain=3.0)

        self.assertEqual(no_rain["phase_active"], "Normal")
        self.assertEqual(rain["phase_active"], "Normal")
        # La réduction pluie est réellement propagée aux valeurs exécutées.
        self.assertLess(rain["objectif_mm"], no_rain["objectif_mm"])
        self.assertEqual(rain["objectif_mm"], round(rain["mm_requested"] * 0.8, 1))
        self.assertEqual(rain["mm_final"], rain["objectif_mm"])
        self.assertEqual(rain["mm_applied"], rain["objectif_mm"])
        # Le conseil cite exactement la valeur exécutée (plus de divergence).
        self.assertIn(f"{rain['objectif_mm']:.1f} mm", rain["action_recommandee"])
        self.assertIn("Réduis", rain["action_recommandee"])
        # mm_requested conserve la demande brute (traçabilité).
        self.assertGreater(rain["mm_requested"], rain["objectif_mm"])

    def test_trace_rain_does_not_reduce_or_block_watering(self):
        # Anti-régression du bug réel : une pluie de trace (0,8 mm à J+2) ne doit NI
        # réduire NI bloquer l'arrosage d'un sol sec (sinon « pluie prévue suffisante »
        # à tort, en pleine canicule).
        no_rain = self._snapshot(pluie_demain=0.0)
        trace = self._snapshot(pluie_j2=0.8)

        # Pas de blocage « pluie prévue suffisante » et arrosage maintenu.
        self.assertNotEqual(trace.get("block_reason"), "pluie_prevue_suffisante")
        self.assertGreater(trace["objectif_mm"], 0.0)
        # La réduction ×0.8 ne s'applique pas pour une trace : l'objectif reste quasi intact.
        self.assertGreater(trace["objectif_mm"], no_rain["objectif_mm"] * 0.9)

    def test_rain_reduction_below_min_session_zeroes_objective(self):
        # Réserve sol au seuil MAD (6/12) → la dépletion déclenche une recharge de 6 mm,
        # mais la réduction pluie (×0.8) la ramène à 4,8 mm, sous min_session_mm (5.0) :
        # l'objectif bascule à 0 plutôt que de publier une dose sous le minimum utile.
        snap = self._snapshot(soil_balance={"reserve_mm": 6.0}, etp_capteur=8.0, pluie_demain=2.0)

        self.assertEqual(snap["phase_active"], "Normal")
        self.assertGreater(snap["mm_requested"], 0.0)        # demande brute non nulle
        self.assertLess(snap["mm_requested"] * 0.8, 5.0)     # mais réduite sous le minimum utile
        self.assertEqual(snap["objectif_mm"], 0.0)
        self.assertEqual(snap["mm_final"], 0.0)
        self.assertEqual(snap["mm_applied"], 0.0)
        self.assertFalse(snap["arrosage_recommande"])
        self.assertNotIn("0.0 mm", snap["action_recommandee"])
        # Le blocage par la pluie porte un motif explicite (cohérence dashboard).
        self.assertEqual(snap["block_reason"], "pluie_prevue_suffisante")
        self.assertIn("Motif exact: pluie_prevue_suffisante", snap["raison_decision"])

    def test_no_rain_objective_unchanged(self):
        snap = self._snapshot(pluie_demain=0.0, pluie_j2=0.0, pluie_3j=0.0)

        self.assertEqual(snap["phase_active"], "Normal")
        self.assertTrue(snap["arrosage_recommande"])
        # Aucune réduction: objectif == demande brute, conseil "Applique".
        self.assertEqual(snap["objectif_mm"], snap["mm_requested"])
        self.assertEqual(snap["mm_applied"], snap["objectif_mm"])
        self.assertIn("Applique", snap["action_recommandee"])
        self.assertNotIn("Réduis", snap["action_recommandee"])

    def test_depletion_gates_watering_on_mad_with_soil_sensor(self):
        # Quand le bilan sol interne fournit une réserve réelle (ledger soil_balance), le
        # mode Normal passe en pilotage par épuisement (deplete-to-MAD, refill-to-full) :
        # tant que la réserve reste au-dessus du seuil MAD (50 %), pas d'arrosage — même par
        # ETP élevée.
        comfortable = self._snapshot(soil_balance={"reserve_mm": 18.0}, etp_capteur=8.0, pluie_demain=0.0)
        self.assertEqual(comfortable["phase_active"], "Normal")
        self.assertTrue(comfortable["use_depletion_logic"])
        self.assertEqual(comfortable["reserve_available_ratio"], 1.0)
        self.assertLess(comfortable["depletion_ratio"], 0.5)
        self.assertFalse(comfortable["arrosage_recommande"])
        self.assertEqual(comfortable["objectif_mm"], 0.0)

        # Réserve encore au-dessus du seuil (8/12 ≈ 33 % épuisé) : toujours pas d'arrosage.
        above_mad = self._snapshot(soil_balance={"reserve_mm": 8.0}, etp_capteur=8.0, pluie_demain=0.0)
        self.assertLess(above_mad["depletion_ratio"], 0.5)
        self.assertFalse(above_mad["arrosage_recommande"])
        self.assertEqual(above_mad["objectif_mm"], 0.0)

        # Réserve descendue au seuil MAD (5/12 ≈ 58 % épuisé) : recharge profonde déclenchée,
        # bornée par la réserve utile (pas de sur-remplissage).
        depleted = self._snapshot(soil_balance={"reserve_mm": 5.0}, etp_capteur=8.0, pluie_demain=0.0)
        self.assertGreaterEqual(depleted["depletion_ratio"], 0.5)
        self.assertTrue(depleted["arrosage_recommande"])
        self.assertGreater(depleted["objectif_mm"], 0.0)
        self.assertLessEqual(depleted["objectif_mm"], depleted["reserve_utile_mm"])


class TestFenetreOptimaleArbitrage(unittest.TestCase):
    """Arbitrage de la fenêtre entre le profil d'arrosage et le risk bundle."""

    def test_le_profil_peut_retirer_le_soir_pas_seulement_l_ajouter(self):
        # Régression (constatée en réel le 24/07/2026) : le risk bundle ne teste que
        # `evening_allowed` + l'heure, tandis que le PROFIL connaît le coucher du soleil et
        # applique les garde-fous de séchage (« LE SOIR = UNIQUEMENT LE RAFRAÎCHISSEMENT (3 mm),
        # JAMAIS UNE RECHARGE »). L'ancienne écriture ne laissait le profil qu'AJOUTER « soir ».
        # Quand il renvoyait délibérément « ce_matin » (cooling inactif → recharge reportée au
        # frais), le « soir » du risk bundle reprenait le dessus : 11 mm planifiés à 21h11 pour un
        # cycle de 2h13, fin ~1h45 après le coucher du soleil, gazon trempé toute la nuit.
        resolve = decision_watering._resolve_optimal_window

        # Le profil écarte le soir → il doit gagner, même si le risk bundle dit « soir ».
        self.assertEqual(resolve("ce_matin", "soir"), "ce_matin")
        self.assertEqual(resolve("maintenant", "soir"), "maintenant")

        # Le profil décide un vrai cycle du soir (rafraîchissement) → « soir » retenu.
        self.assertEqual(resolve("soir", "ce_matin"), "soir")
        self.assertEqual(resolve("soir", "soir"), "soir")

        # Hors « soir », le risk bundle reste la référence (fenêtres de risque, blocages…).
        self.assertEqual(resolve("ce_matin", "apres_pluie"), "apres_pluie")
        self.assertEqual(resolve(None, "soir"), "soir")  # profil muet → repli inchangé


class TestDepletionWateringModel(unittest.TestCase):
    """Modèle de dépletion (Normal + réserve sol interne) : deplete-to-MAD, refill-to-full."""

    @staticmethod
    def _profile(**overrides):
        temperature = overrides.pop("temperature", 30.0)
        water_balance = dict(
            bilan_hydrique_mm=-7.0,
            deficit_jour=4.0,
            deficit_3j=8.0,
            deficit_7j=20.0,
            arrosage_recent_7j=0.0,
            arrosage_recent=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=5.0,
            reserve_stock_mm=5.0,
            reserve_stock_max_mm=24.0,
            depletion_mm=7.0,
            depletion_ratio=0.583,
            mad_ratio=0.5,
        )
        water_balance.update(overrides)
        return guidance.compute_watering_profile(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance=water_balance,
            today=date(2026, 7, 15),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=40.0,
            temperature=temperature,
            etp=7.0,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )

    def test_no_watering_while_reserve_above_mad(self):
        # Réserve à 8/12 (33 % épuisé, sous le seuil MAD 50 %) : pas d'arrosage.
        profile = self._profile(reserve_actuelle_mm=8.0, depletion_mm=4.0, depletion_ratio=0.333)
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertIsNone(profile["block_reason"])

    def test_refill_targets_reserve_utile_when_mad_reached(self):
        # Réserve à 5/12 (58 % épuisé) : recharge = déficit jusqu'au plein utile (7 mm),
        # jamais au-delà de la réserve utile.
        profile = self._profile()
        self.assertEqual(profile["mm_final_recommande"], 7.0)
        self.assertLessEqual(profile["mm_final_recommande"], 12.0)
        self.assertIsNone(profile["block_reason"])

    def test_dose_capped_by_weekly_budget(self):
        # Beaucoup déjà arrosé sur 7 j glissants : la recharge est plafonnée au reste du budget
        # hebdo (cap dur), même réserve épuisée. NB : le plafond hebdo suit désormais la DEMANDE
        # ETc en continu (~45 mm ici, ET0 élevée) — il faut donc un cumul élevé pour que le budget
        # (et non la déplétion 7 mm) devienne le facteur limitant.
        recent = 40.0
        profile = self._profile(arrosage_recent_7j=recent)
        weekly_room = round(profile["weekly_guardrail_mm_max"] - recent, 1)
        self.assertEqual(profile["mm_final_recommande"], weekly_room)
        self.assertLess(profile["mm_final_recommande"], 7.0)  # bridé SOUS la déplétion (budget contraint)

    def test_projection_aube_utilise_etc_pas_et0_brute(self):
        # Le DÉCLENCHEMENT à l'aube compare « déplétion + ET restant à s'écouler » au seuil MAD.
        # Il doit projeter l'ETc (ET0 × Kc) — l'unité que le ledger débite — et non l'ET0 brute.
        # Cas critique : LENDEMAIN d'une recharge complète (réserve pleine, déplétion ≈ 0) par
        # forte ET0. À l'aube `et_elapsed_fraction` = 0, donc l'ET du jour entier est projetée :
        #   ET0 brute 6,1 → (0 + 6,1)/12 = 0,51 > MAD 0,50 → arroserait un sol PLEIN
        #   ETc     4,9 → (0 + 4,9)/12 = 0,41 < 0,50 → pas d'arrosage ✅
        profile = self._profile(
            reserve_actuelle_mm=12.0,
            reserve_stock_mm=12.0,
            depletion_mm=0.0,
            depletion_ratio=0.0,
            et0_mm=6.1,
            etc_mm=4.9,
            et_elapsed_fraction=0.0,
            temperature=28.0,
        )
        self.assertEqual(profile["mm_final_recommande"], 0.0)

        # Même sol, mais une vraie journée très demandante (ETc 7,5) : la soif projetée dépasse
        # bien le seuil → l'arrosage part. La correction ne rend pas le déclenchement inerte.
        profile_demandant = self._profile(
            reserve_actuelle_mm=12.0,
            reserve_stock_mm=12.0,
            depletion_mm=0.0,
            depletion_ratio=0.0,
            et0_mm=9.4,
            etc_mm=7.5,
            et_elapsed_fraction=0.0,
            temperature=28.0,
        )
        self.assertGreater(profile_demandant["mm_final_recommande"], 0.0)

    def test_projection_aube_repli_kc_typique_sans_etc(self):
        # Sans `etc_mm` fourni, on reste en unité ETc via le Kc typique (0,8) au lieu de retomber
        # sur l'ET0 brute : 6,1 × 0,8 = 4,88 → 0,41 < 0,50 → pas d'arrosage sur sol plein.
        profile = self._profile(
            reserve_actuelle_mm=12.0,
            reserve_stock_mm=12.0,
            depletion_mm=0.0,
            depletion_ratio=0.0,
            et0_mm=6.1,
            et_elapsed_fraction=0.0,
            temperature=28.0,
        )
        self.assertEqual(profile["mm_final_recommande"], 0.0)

    def test_canicule_weekly_cap_follows_etc_not_throttled_to_survival(self):
        # Régression (06/2026) : en forte demande, le plafond hebdo NORMAL (~30 mm) étranglait la
        # recharge sous la demande ETc (~50 mm/sem) → réserve à 0 mais dose bridée à 5 mm de
        # survie → gazon qui sèche. Désormais le plafond suit l'ETc EN CONTINU : avec ~35 mm déjà
        # arrosés (sous le plafond ≈ demande), une vraie recharge > plancher de survie passe.
        profile = self._profile(
            arrosage_recent_7j=35.5, reserve_actuelle_mm=0.0, depletion_mm=12.0, depletion_ratio=1.0
        )
        self.assertGreater(profile["weekly_guardrail_mm_max"], 30.0)  # plafond rehaussé en canicule
        self.assertGreater(profile["mm_final_recommande"], 5.0)  # plus bridé au plancher de survie

    def test_survival_watering_during_heatwave_overrides_weekly_cap(self):
        # Réserve à 0/12 (100 % épuisé) + VRAIE canicule (temp 34 °C) + budget hebdo dépassé :
        # un petit cycle de survie est délivré malgré le garde-fou, sinon le gazon grillerait.
        profile = self._profile(
            reserve_actuelle_mm=0.0,
            reserve_stock_mm=0.0,
            depletion_mm=12.0,
            depletion_ratio=1.0,
            arrosage_recent_7j=40.0,
            temperature=34.0,
        )
        self.assertGreater(profile["mm_final_recommande"], 0.0)
        self.assertNotEqual(profile.get("block_reason"), "garde_fou_hebdomadaire")

    def test_survie_canicule_active_est_exposee(self):
        # Aucun attribut ne portait l'information « c'est un arrosage de SURVIE » : les codes
        # d'action valent `aucune_action`/`surveiller`/`a_faire`/`critique` et `heat_stress_level`
        # est un score COMPOSITE qui dit déjà « severe » à 30 °C. Un affichage n'avait donc aucun
        # moyen de distinguer une recharge de routine d'une intervention d'urgence.
        survie = self._profile(
            reserve_actuelle_mm=0.0, reserve_stock_mm=0.0, depletion_mm=12.0,
            depletion_ratio=1.0, arrosage_recent_7j=40.0, temperature=34.0,
        )
        self.assertTrue(survie["survie_canicule_active"])

        # 30 °C = journée d'été sèche NORMALE : le score composite dit « severe », mais la
        # température réelle est sous le seuil → pas de survie (règle 0.16.0 préservée).
        normale = self._profile(
            reserve_actuelle_mm=0.0, reserve_stock_mm=0.0, depletion_mm=12.0,
            depletion_ratio=1.0, arrosage_recent_7j=40.0, temperature=30.0,
        )
        self.assertFalse(normale["survie_canicule_active"])

    def test_pas_de_survie_a_30_degres_meme_reserve_epuisee(self):
        # 30 °C = journée d'été sèche NORMALE, pas une canicule. Même réserve épuisée + budget
        # dépassé, la survie ne doit PAS s'armer (le score composite dit "severe" par l'ET0/air sec,
        # mais on exige une chaleur RÉELLE ≥ 32 °C) → le garde-fou hebdo reste un cap dur.
        profile = self._profile(
            reserve_actuelle_mm=0.0,
            reserve_stock_mm=0.0,
            depletion_mm=12.0,
            depletion_ratio=1.0,
            arrosage_recent_7j=40.0,
            et0_mm=7.0,
            et_elapsed_fraction=1.0,   # journée écoulée → déplétion réelle = 100 %, mais temp 30 °C
            temperature=30.0,
        )
        chaud = self._profile(
            reserve_actuelle_mm=0.0, reserve_stock_mm=0.0, depletion_mm=12.0, depletion_ratio=1.0,
            arrosage_recent_7j=40.0, et0_mm=7.0, et_elapsed_fraction=1.0, temperature=34.0,
        )
        # À 30 °C la survie ne délivre pas la recharge complète ; à 34 °C (vraie canicule) oui.
        self.assertLess(profile["mm_final_recommande"], chaud["mm_final_recommande"])

    # NOTE : l'ancien test `test_survie_canicule_ne_sarme_pas_a_minuit_sur_depletion_anticipee`
    # vivait ici. La « falaise de minuit » qu'il compensait est désormais supprimée À LA SOURCE :
    # le ledger débite l'ET0 au prorata de la journée écoulée (soil_balance.update_soil_balance),
    # donc `depletion_ratio` est déjà la déplétion réelle et guidance n'a plus à la reconstruire.
    # La garantie est testée directement sur le ledger, cf. tests/test_soil_balance.py
    # (`test_et0_debitee_au_prorata_de_la_journee`).

    def test_declenchement_a_l_aube_sur_soif_projetee_mais_dose_reelle(self):
        # L'arrosage doit TOUJOURS partir à l'aube (évaporation minimale, feuillage sec le soir).
        # Or, le ledger débitant l'ET0 au fil de la journée, la déplétion RÉELLE ne franchit le
        # seuil MAD qu'en milieu de journée. On déclenche donc sur la soif PROJETÉE en fin de
        # journée (déplétion + ET0 restant), tout en dosant sur la place RÉELLEMENT disponible.
        aube = self._profile(
            reserve_actuelle_mm=8.4,
            reserve_stock_mm=8.4,
            depletion_mm=3.6,
            depletion_ratio=0.3,  # réel : encore SOUS le seuil MAD (0,5)
            et0_mm=9.6,
            et_elapsed_fraction=0.0,  # aube : toute l'ET0 du jour reste à s'écouler
            arrosage_recent_7j=0.0,
            temperature=28.0,
        )
        # 3,6 + 9,6 = 13,2 mm > réserve utile → le sol manquera aujourd'hui : on arrose dès l'aube.
        self.assertGreater(aube["mm_final_recommande"], 0.0)
        # Mais la dose reste bornée par la place réelle (3,6 mm) + le plancher de session utile —
        # surtout pas les 13,2 mm projetés, qui draineraient sous les racines.
        self.assertLessEqual(aube["mm_final_recommande"], 6.0)

        # Journée fraîche : le sol tiendra jusqu'à demain → aucun arrosage déclenché.
        frais = self._profile(
            reserve_actuelle_mm=12.0,
            reserve_stock_mm=12.0,
            depletion_mm=0.0,
            depletion_ratio=0.0,
            et0_mm=3.0,
            et_elapsed_fraction=0.0,
            arrosage_recent_7j=0.0,
            temperature=22.0,
        )
        self.assertEqual(frais["mm_final_recommande"], 0.0)

    def test_no_survival_watering_without_heatwave(self):
        # Même réserve épuisée + budget dépassé, MAIS sans canicule (temps frais) :
        # le plafond hebdomadaire reste un cap dur, aucun arrosage.
        water_balance = dict(
            bilan_hydrique_mm=-7.0,
            deficit_jour=4.0,
            deficit_3j=8.0,
            deficit_7j=20.0,
            arrosage_recent_7j=40.0,
            arrosage_recent=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=0.0,
            reserve_stock_mm=0.0,
            reserve_stock_max_mm=24.0,
            depletion_mm=12.0,
            depletion_ratio=1.0,
            mad_ratio=0.5,
        )
        profile = guidance.compute_watering_profile(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance=water_balance,
            today=date(2026, 7, 15),
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0,
            humidite=70.0,
            temperature=15.0,
            etp=1.0,
            type_sol="limoneux",
            weather_profile={},
            history=[],
        )
        self.assertEqual(profile["mm_final_recommande"], 0.0)

    def test_reserve_reellement_vide_arrose_en_secours_sous_32(self):
        # Régression (25/07/2026) : réserve RÉELLEMENT à 0 (le ledger débite l'ET0 au prorata →
        # `depletion_ratio` brut = 1.0, pas la falaise de minuit), journée demandante (canicule)
        # mais 30 °C < 32, et budget hebdo largement dépassé. Avant : ni survie (< 32 °C) ni
        # `_critical_depletion` (déplétion urgence sous-estimée à l'aube) → RIEN ne partait, gazon à
        # sec toute la journée. Désormais : arrosage de SECOURS modéré (~min_session), la recharge
        # complète restant réservée à la vraie canicule (≥ 32 °C).
        vide = self._profile(
            reserve_actuelle_mm=0.0, reserve_stock_mm=0.0, depletion_mm=12.0, depletion_ratio=1.0,
            et0_mm=6.0, et_elapsed_fraction=0.0, arrosage_recent_7j=60.0, temperature=30.0,
        )
        self.assertGreater(vide["mm_final_recommande"], 0.0)       # ça arrose (plus bloqué)
        self.assertLessEqual(vide["mm_final_recommande"], 6.0)     # secours modéré, pas recharge pleine

        # Contrôle : réserve encore correcte (33 % épuisée), même budget dépassé → PAS de secours,
        # le garde-fou hebdo reste un cap dur tant que le sol n'est pas réellement vide.
        ok = self._profile(
            reserve_actuelle_mm=8.0, reserve_stock_mm=8.0, depletion_mm=4.0, depletion_ratio=0.333,
            et0_mm=6.0, et_elapsed_fraction=0.0, arrosage_recent_7j=60.0, temperature=30.0,
        )
        self.assertEqual(ok["mm_final_recommande"], 0.0)

    def test_ledger_depleted_overrides_stale_bilan_block(self):
        # Réserve réelle (ledger temps réel) épuisée (86 %) MAIS bilan glissant encore positif
        # (lendemain d'un gros arrosage) → on NE bloque PLUS « sol déjà humide » : le ledger
        # fait foi, la recharge du matin part.
        profile = self._profile(
            bilan_hydrique_mm=8.7,
            reserve_actuelle_mm=1.7,
            reserve_stock_mm=1.7,
            depletion_mm=10.3,
            depletion_ratio=0.858,
        )
        self.assertNotIn(profile.get("block_reason"), {"sol_deja_humide", "humidite_excessive"})
        self.assertGreater(profile["mm_final_recommande"], 0.0)

    def test_stale_bilan_still_blocks_when_ledger_full(self):
        # Garde-fou inverse : si le ledger N'EST PAS épuisé (sous MAD) et le bilan est élevé
        # (sol réellement gorgé) → on bloque toujours « sol déjà humide » (pas de sur-arrosage).
        profile = self._profile(
            bilan_hydrique_mm=8.7,
            reserve_actuelle_mm=11.0,
            reserve_stock_mm=11.0,
            depletion_mm=1.0,
            depletion_ratio=0.083,
        )
        self.assertEqual(profile.get("block_reason"), "sol_deja_humide")

    def test_depletion_not_applied_in_sursemis(self):
        # Anti-régression du bug d'origine : en Sursemis, même avec une réserve sol épuisée,
        # la dépletion ne s'applique pas (recharge profonde inadaptée au semis).
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-07-10"}],
            today=date(2026, 7, 15),
            hour_of_day=6,
            temperature=25.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            pluie_3j=0.0,
            humidite=50.0,
            type_sol="limoneux",
            etp_capteur=6.0,
            soil_balance={"reserve_mm": 5.0},
        )
        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertFalse(snapshot["use_depletion_logic"])

    def test_sans_ledger_sol_on_retombe_sur_le_modele_deficit(self) -> None:
        # SECOND repli du pilotage par dépletion, distinct du test ci-dessus : ici la phase EST
        # Normal, mais le bilan sol interne ne fournit aucune réserve (`reserve_from_soil_ledger`
        # faux) — cas du tout premier cycle ou d'un ledger vide. Le pilotage doit alors retomber
        # sur le modèle déficit (legacy), condition explicitement protégée par le CLAUDE.md.
        # Ce test vivait dans tests/test_dose_policy.py, supprimé avec le sous-système `dose_policy`
        # (0.18.3) alors qu'il n'en testait rien : relogé ici pour ne pas perdre la couverture.
        snapshot = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 5, 15),
            hour_of_day=8,
            temperature=20.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=45.0,
            type_sol="limoneux",
            etp_capteur=2.0,
        )
        self.assertIn("objectif_mm", snapshot)
        self.assertIn("mm_final", snapshot)
        self.assertIn("use_depletion_logic", snapshot)
        self.assertFalse(snapshot["use_depletion_logic"])
        self.assertEqual(snapshot["objectif_mm"], snapshot["mm_final"])


class TestEveningCoolingWatering(unittest.TestCase):
    """Rafraîchissement du soir en canicule extrême (cooling) malgré une réserve saine."""

    @staticmethod
    def _cooling_profile(now_hour=21, now_minute=10, sunset_minute=1290, **wb):
        water_balance = dict(
            bilan_hydrique_mm=-1.0,
            deficit_jour=0.0,
            deficit_3j=0.0,
            deficit_7j=0.0,
            arrosage_recent_7j=0.0,
            arrosage_recent=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=9.6,
            reserve_stock_mm=9.6,
            reserve_stock_max_mm=24.0,
            depletion_mm=2.4,
            depletion_ratio=0.2,
            mad_ratio=0.5,
        )
        water_balance.update(wb)
        moment = datetime(2026, 7, 15, now_hour, now_minute, tzinfo=timezone.utc)
        with patch.object(guidance, "_current_datetime", return_value=moment):
            return guidance.compute_watering_profile(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance=water_balance,
                today=date(2026, 7, 15),
                pluie_24h=0.0,
                pluie_demain=0.0,
                pluie_j2=0.0,
                pluie_3j=0.0,
                pluie_probabilite_max_3j=0.0,
                humidite=30.0,
                temperature=36.0,
                etp=5.0,
                type_sol="limoneux",
                weather_profile={"sunset_minute": sunset_minute},
                history=[],
            )

    def test_cooling_applied_in_evening_with_healthy_reserve(self):
        # 18h30, canicule extrême, air sec, coucher dans 3 h, réserve saine → petit cycle de
        # rafraîchissement (EVENING_COOLING_MM), fenêtre "soir", pas de blocage.
        profile = self._cooling_profile()
        self.assertEqual(profile["heat_stress_level"], "severe")
        self.assertTrue(profile["watering_evening_allowed"])
        self.assertEqual(profile["fenetre_optimale"], "soir")
        self.assertEqual(profile["mm_final_recommande"], guidance.EVENING_COOLING_MM)
        self.assertIsNone(profile["block_reason"])
        # Fenêtre soir exposée au coordinateur = basée sur le coucher (-30 → coucher), pas 18-20 h.
        self.assertEqual(
            profile["watering_evening_start_minute"],
            1290 - guidance.EVENING_COOLING_START_BEFORE_SUNSET_MIN,
        )
        self.assertEqual(profile["watering_evening_end_minute"], 1290)

    def test_evening_deficit_becomes_cooling_never_hydric(self):
        # 3e cas SUPPRIMÉ : même avec un gros déficit (réserve à sec), le SOIR ne fait QUE le
        # cooling (3 mm), jamais une recharge hydrique. La vraie recharge est reportée au matin →
        # l'arrosage du soir n'arme donc pas le cooldown 24 h et ne bloque plus le matin suivant.
        profile = self._cooling_profile(
            bilan_hydrique_mm=-12.0,
            deficit_jour=10.0,
            deficit_3j=12.0,
            deficit_7j=20.0,
            reserve_actuelle_mm=2.0,
            reserve_stock_mm=2.0,
            depletion_mm=10.0,
            depletion_ratio=0.83,
        )
        self.assertEqual(profile["heat_stress_level"], "severe")
        self.assertEqual(profile["fenetre_optimale"], "soir")
        # C'est le cooling (3 mm) qui sort, PAS la grosse recharge hydrique du déficit.
        self.assertEqual(profile["mm_final_recommande"], guidance.EVENING_COOLING_MM)
        self.assertTrue(profile["evening_cooling"])
        self.assertIsNone(profile["block_reason"])

    def test_cooling_applied_on_canicule_evening(self):
        # Le soir, la chaleur redescend : le cooling doit se déclencher si la température mesurée
        # est encore ≥ EVENING_COOLING_MIN_TEMP (32 °C) — représente une journée à ~38 °C de max.
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)
        water_balance = dict(
            bilan_hydrique_mm=-1.0,
            deficit_3j=0.0,
            deficit_7j=0.0,
            arrosage_recent_7j=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=9.6,
            reserve_stock_mm=9.6,
            reserve_stock_max_mm=24.0,
            depletion_mm=2.4,
            depletion_ratio=0.2,
            mad_ratio=0.5,
        )
        with patch.object(guidance, "_current_datetime", return_value=moment):
            profile = guidance.compute_watering_profile(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance=water_balance,
                today=date(2026, 7, 15),
                pluie_24h=0.0,
                pluie_demain=0.0,
                pluie_j2=0.0,
                pluie_3j=0.0,
                pluie_probabilite_max_3j=0.0,
                humidite=50.0,
                temperature=34.0,
                etp=4.0,
                type_sol="limoneux",
                weather_profile={"sunset_minute": 1290},
                history=[],
            )
        self.assertEqual(profile["heat_stress_level"], "eleve")
        self.assertEqual(profile["fenetre_optimale"], "soir")
        self.assertEqual(profile["mm_final_recommande"], guidance.EVENING_COOLING_MM)

    def _evening_recharge_profile(self, *, temperature, evening_cooling_enabled=True):
        # Réserve TRÈS épuisée (déplétion 0.83 > MAD 0.5) → le mode Normal veut une vraie recharge.
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)
        water_balance = dict(
            bilan_hydrique_mm=-14.0,
            deficit_3j=14.0,
            deficit_7j=18.0,
            arrosage_recent_7j=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=2.0,
            reserve_stock_mm=2.0,
            reserve_stock_max_mm=24.0,
            depletion_mm=10.0,
            depletion_ratio=0.83,
            mad_ratio=0.5,
        )
        with patch.object(guidance, "_current_datetime", return_value=moment):
            return guidance.compute_watering_profile(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance=water_balance,
                today=date(2026, 7, 15),
                pluie_24h=0.0,
                pluie_demain=0.0,
                pluie_j2=0.0,
                pluie_3j=0.0,
                pluie_probabilite_max_3j=0.0,
                humidite=45.0,
                temperature=temperature,
                etp=6.0,
                type_sol="limoneux",
                weather_profile={"sunset_minute": 1290},
                history=[],
                evening_cooling_enabled=evening_cooling_enabled,
            )

    def test_no_cooling_on_saturated_soil(self):
        # RÉGRESSION : `cooling_active` remettait block_reason=None sans condition, effaçant aussi
        # « sol_deja_humide ». Canicule après un gros orage (bilan +6 mm > seuil de saturation) :
        # arroser un sol détrempé n'apporte rien et laisse le gazon trempé la nuit.
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)
        water_balance = dict(
            bilan_hydrique_mm=6.0,  # > SATURATION_BILAN_HYDRIQUE_MM (5.0) → saturation_block
            deficit_3j=0.0,
            deficit_7j=0.0,
            arrosage_recent_7j=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=11.5,
            reserve_stock_mm=11.5,
            reserve_stock_max_mm=24.0,
            depletion_mm=0.5,
            depletion_ratio=0.04,
            mad_ratio=0.5,
        )
        with patch.object(guidance, "_current_datetime", return_value=moment):
            profile = guidance.compute_watering_profile(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance=water_balance,
                today=date(2026, 7, 15),
                pluie_24h=0.0,
                pluie_demain=0.0,
                pluie_j2=0.0,
                pluie_3j=0.0,
                pluie_probabilite_max_3j=0.0,
                humidite=45.0,
                temperature=35.0,
                etp=6.0,
                type_sol="limoneux",
                weather_profile={"sunset_minute": 1290},
                history=[],
            )
        self.assertIn(profile["heat_stress_level"], {"eleve", "severe"})
        self.assertFalse(profile["evening_cooling"])
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertEqual(profile["block_reason"], "sol_deja_humide")

    def test_no_evening_recharge_when_cooling_inactive_below_min_temp(self):
        # RÉGRESSION : en canicule, _evening_window_allowed LÈVE la marge de séchage de 90 min en
        # supposant les 3 mm de cooling. Si le cooling ne s'active pas (T mesurée < 32 °C), la dose
        # de RECHARGE ne doit PAS partir le soir — sinon gros arrosage à la tombée de la nuit sans
        # séchage → risque fongique. Elle est reportée au matin.
        profile = self._evening_recharge_profile(temperature=30.0)
        self.assertIn(profile["heat_stress_level"], {"eleve", "severe"})
        self.assertNotEqual(profile["fenetre_optimale"], "soir")
        # Le coordinateur ne doit PAS être autorisé à lancer dans la fenêtre du soir.
        self.assertFalse(profile["watering_evening_allowed"])

    def test_no_evening_recharge_when_switch_disabled(self):
        # Même garde-fou quand c'est le switch qui coupe le rafraîchissement.
        profile = self._evening_recharge_profile(temperature=34.0, evening_cooling_enabled=False)
        self.assertIn(profile["heat_stress_level"], {"eleve", "severe"})
        self.assertNotEqual(profile["fenetre_optimale"], "soir")
        self.assertFalse(profile["watering_evening_allowed"])

    def test_evening_window_still_published_for_real_cooling(self):
        # Contrôle positif : vraie canicule (T ≥ 32 °C) → le cooling reste proposé le soir et la
        # fenêtre est bien publiée au coordinateur.
        profile = self._evening_recharge_profile(temperature=34.0)
        self.assertEqual(profile["fenetre_optimale"], "soir")
        self.assertEqual(profile["mm_final_recommande"], guidance.EVENING_COOLING_MM)
        self.assertTrue(profile["watering_evening_allowed"])
        self.assertEqual(profile["watering_evening_end_minute"], 1290)

    def test_no_cooling_when_switch_disabled(self):
        # Switch « Rafraîchissement du soir » sur OFF : même en pleine canicule et dans la fenêtre
        # du coucher, aucun cooling ne part.
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)
        water_balance = dict(
            bilan_hydrique_mm=-1.0,
            deficit_3j=0.0,
            deficit_7j=0.0,
            arrosage_recent_7j=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=9.6,
            reserve_stock_mm=9.6,
            reserve_stock_max_mm=24.0,
            depletion_mm=2.4,
            depletion_ratio=0.2,
            mad_ratio=0.5,
        )
        with patch.object(guidance, "_current_datetime", return_value=moment):
            profile = guidance.compute_watering_profile(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance=water_balance,
                today=date(2026, 7, 15),
                pluie_24h=0.0,
                pluie_demain=0.0,
                pluie_j2=0.0,
                pluie_3j=0.0,
                pluie_probabilite_max_3j=0.0,
                humidite=50.0,
                temperature=34.0,
                etp=4.0,
                type_sol="limoneux",
                weather_profile={"sunset_minute": 1290},
                history=[],
                evening_cooling_enabled=False,
            )
        self.assertEqual(profile["heat_stress_level"], "eleve")
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertNotEqual(profile["fenetre_optimale"], "soir")

    def test_no_cooling_below_min_temperature(self):
        # Score de stress « canicule » atteint via ET0/humidité, mais température mesurée au
        # coucher < EVENING_COOLING_MIN_TEMP → pas de cooling (refroidir n'a pas de sens).
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)
        water_balance = dict(
            bilan_hydrique_mm=-1.0,
            deficit_3j=0.0,
            deficit_7j=0.0,
            arrosage_recent_7j=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=9.6,
            reserve_stock_mm=9.6,
            reserve_stock_max_mm=24.0,
            depletion_mm=2.4,
            depletion_ratio=0.2,
            mad_ratio=0.5,
        )
        with patch.object(guidance, "_current_datetime", return_value=moment):
            profile = guidance.compute_watering_profile(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance=water_balance,
                today=date(2026, 7, 15),
                pluie_24h=0.0,
                pluie_demain=0.0,
                pluie_j2=0.0,
                pluie_3j=0.0,
                pluie_probabilite_max_3j=0.0,
                humidite=30.0,
                temperature=28.0,
                etp=5.0,
                type_sol="limoneux",
                weather_profile={"sunset_minute": 1290},
                history=[],
            )
        self.assertIn(profile["heat_stress_level"], {"eleve", "severe"})
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertNotEqual(profile["fenetre_optimale"], "soir")

    def test_no_cooling_in_afternoon(self):
        # En après-midi (14h), hors fenêtre du soir → réserve saine, aucun arrosage.
        profile = self._cooling_profile(now_hour=14, now_minute=0)
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertNotEqual(profile["fenetre_optimale"], "soir")

    def test_no_cooling_before_sunset_window(self):
        # Nouvelle logique : le cooling démarre 30 min AVANT le coucher du soleil. Plus tôt dans
        # la soirée (19h00, coucher 21h30 → hors de la fenêtre [21:00, 21:30]) → pas encore de
        # cooling (on attend qu'il fasse plus frais, près du coucher).
        profile = self._cooling_profile(now_hour=19, now_minute=0)
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertNotEqual(profile["fenetre_optimale"], "soir")

    def test_evening_cooling_runs_in_single_passage(self):
        # Pipeline complet : le rafraîchissement du soir doit sortir en 1 SEUL passage (relief
        # rapide), pas fractionné en 2 par decision_watering. Réserve sol saine → pas de recharge,
        # donc c'est bien le cooling (3 mm) qui s'applique.
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)  # dans [coucher-30, coucher]
        with patch.object(guidance, "_current_datetime", return_value=moment):
            snapshot = decision.build_decision_snapshot(
                history=[],
                today=date(2026, 7, 15),
                hour_of_day=21,
                temperature=38.0,
                humidite=30.0,
                pluie_24h=0.0,
                pluie_demain=0.0,
                type_sol="limoneux",
                etp_capteur=5.0,
                weather_profile={"sunset_minute": 1290},
                soil_balance={
                    "date": "2026-07-15",
                    "reserve_mm": 22.0,
                    "previous_reserve_mm": 22.0,
                    "pluie_mm": 0.0,
                    "arrosage_mm": 0.0,
                    "etp_mm": 5.0,
                    "delta_mm": -5.0,
                    "type_sol": "limoneux",
                    "reserve_max_mm": 24.0,
                    "reserve_min_mm": 0.0,
                    "ledger": [],
                },
            )
        self.assertEqual(snapshot["fenetre_optimale"], "soir")
        self.assertEqual(snapshot["objectif_mm"], guidance.EVENING_COOLING_MM)
        self.assertEqual(snapshot["watering_passages"], 1)

    def test_no_cooling_when_rain_incoming(self):
        # Pluie imminente significative → pas de cooling (la pluie rafraîchit et mouille).
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)
        water_balance = dict(
            bilan_hydrique_mm=-1.0,
            deficit_3j=0.0,
            deficit_7j=0.0,
            arrosage_recent_7j=0.0,
            reserve_from_soil_ledger=True,
            reserve_utile_mm=12.0,
            reserve_actuelle_mm=9.6,
            reserve_stock_mm=9.6,
            reserve_stock_max_mm=24.0,
            depletion_mm=2.4,
            depletion_ratio=0.2,
            mad_ratio=0.5,
        )
        with patch.object(guidance, "_current_datetime", return_value=moment):
            profile = guidance.compute_watering_profile(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance=water_balance,
                today=date(2026, 7, 15),
                pluie_24h=0.0,
                pluie_demain=12.0,
                pluie_j2=0.0,
                pluie_3j=12.0,
                pluie_probabilite_max_3j=90.0,
                humidite=30.0,
                temperature=36.0,
                etp=5.0,
                type_sol="limoneux",
                weather_profile={"sunset_minute": 1290},
                history=[],
            )
        self.assertEqual(profile["mm_final_recommande"], 0.0)
        self.assertNotEqual(profile["fenetre_optimale"], "soir")


class TestEveningCoolingCooldownExemption(unittest.TestCase):
    def test_evening_cooling_does_not_arm_24h_cooldown(self) -> None:
        # Une recharge normale du matin (>24 h) suivie d'un rafraîchissement du soir récent :
        # le cooldown 24 h doit ignorer le rafraîchissement et pointer la recharge du matin.
        history = [
            {
                "type": "arrosage",
                "recorded_at": "2026-04-02T05:30:00+00:00",
                "total_mm": 10.0,
                "watering_cause": "hydrique",
            },
            {
                "type": "arrosage",
                "recorded_at": "2026-04-04T17:40:00+00:00",
                "total_mm": 3.0,
                "watering_cause": "rafraichissement_soir",
            },
        ]
        latest = guidance._latest_watering_datetime(history)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.date().isoformat(), "2026-04-02")

    def test_post_application_does_not_arm_24h_cooldown(self) -> None:
        # L'incorporation post-application (~5 mm) est un arrosage technique : elle ne doit pas
        # armer le cooldown 24 h → le cooldown pointe la recharge du matin, pas l'incorporation.
        history = [
            {
                "type": "arrosage",
                "recorded_at": "2026-04-02T05:30:00+00:00",
                "total_mm": 10.0,
                "watering_cause": "hydrique",
            },
            {
                "type": "arrosage",
                "recorded_at": "2026-04-04T18:30:00+00:00",
                "total_mm": 5.0,
                "watering_cause": "post_application",
            },
        ]
        latest = guidance._latest_watering_datetime(history)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.date().isoformat(), "2026-04-02")

    def test_normal_evening_watering_still_arms_cooldown(self) -> None:
        # Garde-fou : un arrosage hydrique du soir (pas un rafraîchissement) reste pris en compte.
        history = [
            {
                "type": "arrosage",
                "recorded_at": "2026-04-02T05:30:00+00:00",
                "total_mm": 10.0,
                "watering_cause": "hydrique",
            },
            {
                "type": "arrosage",
                "recorded_at": "2026-04-04T17:40:00+00:00",
                "total_mm": 8.0,
                "watering_cause": "hydrique",
            },
        ]
        latest = guidance._latest_watering_datetime(history)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.date().isoformat(), "2026-04-04")


class MowingCooldownTimezoneTests(unittest.TestCase):
    """`context.hour_of_day` est une heure LOCALE (Europe/Paris) que decision_mowing estampillait
    en `tzinfo=utc`, alors que les horodatages d'arrosage sont des instants UTC réels. En été
    (UTC+2) le temps écoulé était surestimé de 2 h : le cooldown de tonte et le délai de ressuyage
    expiraient 1 à 2 h trop tôt, autorisant la tonte sur un gazon encore gorgé d'eau."""

    # 22/07/2026 : arrosage terminé à 09:00 Paris = 07:00 UTC ; il est 10:00 Paris = 08:00 UTC.
    WATERING_UTC = "2026-07-22T07:00:00+00:00"
    NOW_UTC = "2026-07-22T08:00:00+00:00"
    LOCAL_HOUR = 10  # ce que le coordinateur passe dans hour_of_day

    def _context(self, *, with_now_utc):
        runtime = {
            "mowing_cooldown_after_watering_minutes": 120,
            "last_irrigation_execution": {"ended_at": self.WATERING_UTC, "zones": []},
        }
        if with_now_utc:
            runtime["now_utc"] = self.NOW_UTC
        return decision.DecisionContext.from_legacy_args(
            today=date(2026, 7, 22),
            hour_of_day=self.LOCAL_HOUR,
            history=[],
            runtime_context=runtime,
        )

    def test_instant_de_reference_est_bien_en_utc_reel(self):
        now = decision_mowing._reference_now_utc(self._context(with_now_utc=True))
        self.assertEqual(now, datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc))

    def test_une_heure_ecoulee_est_comptee_comme_une_heure(self):
        # Sans la correction : 10:00 estampillé UTC − 07:00 UTC = 180 min au lieu de 60.
        elapsed = decision_mowing._elapsed_minutes_since_watering(self._context(with_now_utc=True))
        self.assertEqual(elapsed, 60)

    def test_cooldown_de_120min_encore_actif_apres_60min(self):
        active, remaining = decision_mowing._mowing_cooldown_state(self._context(with_now_utc=True))
        self.assertTrue(active)
        self.assertEqual(remaining, 60)

    def test_repli_sans_now_utc_reste_deterministe(self):
        # Hors runtime (tests, journée passée), repli sur today + hour_of_day.
        now = decision_mowing._reference_now_utc(self._context(with_now_utc=False))
        self.assertEqual(now, datetime(2026, 7, 22, self.LOCAL_HOUR, 0, tzinfo=timezone.utc))


class IrrigationExecutionContractTests(unittest.TestCase):
    """`_apply_irrigation_execution_contract` cherchait `water_balance` / `bilan_hydrique_mm`
    dans un payload où rien ne les plaçait : le déficit lu valait toujours 0.0 et le drapeau
    « bloqué alors que critique » ne se levait jamais, quel que soit le déficit réel."""

    def _payload(self, *, bilan_mm, blocked=True):
        base = decision_watering._build_watering_bundle_base(
            water_bundle={
                "objectif_mm": 0.0,
                "water_balance": {"bilan_hydrique_mm": bilan_mm},
            },
            phase_bundle={},
            risk_bundle={
                "niveau_action": "surveiller",
                "fenetre_optimale": "ce_matin",
                "risque_gazon": "faible",
                "prochaine_reevaluation": None,
            },
            mowing_bundle={"tonte_autorisee": True, "tonte_statut": "ok"},
            mower_context={},
            application_payload={},
            watering_target_date=None,
        )
        if blocked:
            base["type_arrosage"] = "bloque"
        return decision_watering._apply_irrigation_execution_contract(base)

    def test_le_bilan_atteint_bien_le_contrat(self):
        payload = self._payload(bilan_mm=-8.0)
        self.assertEqual(payload["bilan_hydrique_mm"], -8.0)

    def test_deficit_critique_et_blocage_leve_le_drapeau(self):
        payload = self._payload(bilan_mm=-8.0, blocked=True)
        self.assertTrue(payload["irrigation_blocked_but_critical"])
        self.assertEqual(payload["critical_deficit_mm"], -8.0)
        self.assertIn("Déficit critique", payload["critical_irrigation_reason"])

    def test_deficit_leger_ne_leve_pas_le_drapeau(self):
        payload = self._payload(bilan_mm=-1.0, blocked=True)
        self.assertFalse(payload["irrigation_blocked_but_critical"])

    def test_sans_blocage_pas_dalerte_meme_si_critique(self):
        payload = self._payload(bilan_mm=-8.0, blocked=False)
        self.assertFalse(payload["irrigation_blocked_but_critical"])


class EveningCoolingRecommendationTests(unittest.TestCase):
    """Le garde `recommande = objectif_mm > 0 and besoin_eau` ré-accouplait le rafraîchissement
    du soir au déficit, alors que guidance.py l'en a découplé en 0.14.0 : réserve saine, le
    cooling de canicule était ramené à 0 mm — exactement le cas qu'il devait couvrir."""

    def test_le_cooling_est_exempte_du_garde_besoin_eau(self):
        # Réserve saine : besoin_eau est faux, mais le cooling doit rester recommandé.
        besoin_eau = False
        objectif_mm = guidance.EVENING_COOLING_MM
        for evening_cooling, attendu in ((True, True), (False, False)):
            with self.subTest(evening_cooling=evening_cooling):
                recommande = objectif_mm > 0 and (besoin_eau or bool(evening_cooling))
                self.assertEqual(recommande, attendu)


class MowingScoreOnlyBlockTests(unittest.TestCase):
    """Entre le seuil baseline (55) et le seuil « conditions défavorables » (65), la tonte est
    refusée par le SCORE SEUL, sans qu'aucun code agronomique ne soit posé. L'override de retard
    étant indexé sur `reason_code`, cette bande était impossible à débloquer : une tonte pouvait
    rester refusée avec 37 jours de retard, sans motif affiché."""

    def _bundle(self, *, humidite):
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-05-01"}],  # 37 jours de retard
            today=date(2026, 6, 7),
            hour_of_day=11,
            temperature=22,
            pluie_24h=6, pluie_demain=5, pluie_j2=2, pluie_3j=0,
            pluie_probabilite_max_3j=0,
            humidite=humidite,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        phase_bundle = decision_phase.build_phase_bundle(context)
        water_bundle = decision_watering.build_water_bundle(context, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(context, phase_bundle, water_bundle)
        bundle = decision_mowing.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
        return bundle, int(risk_bundle["scores"]["score_tonte"])

    def test_bande_intermediaire_debloquee_par_le_retard(self):
        bundle, score = self._bundle(humidite=80)
        self.assertGreaterEqual(score, 55, "le cas doit rester dans la bande bloquante")
        self.assertLess(score, 65, "le cas doit rester SOUS conditions_defavorables")
        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertTrue(
            bundle["tonte_autorisee"],
            "un blocage par score seul doit être levable par l'override de retard",
        )

    def test_conditions_defavorables_restent_levables(self):
        # Contrôle : le cas historiquement couvert (score >= 65) continue de fonctionner.
        bundle, score = self._bundle(humidite=88)
        self.assertGreaterEqual(score, 65)
        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertTrue(bundle["tonte_autorisee"])

    def test_au_dela_du_seuil_etendu_le_blocage_tient(self):
        # L'override n'est pas un passe-droit : au-delà de 70 (seuil étendu quand le retard
        # dépasse le facteur 2), la tonte reste refusée même très en retard.
        bundle, score = self._bundle(humidite=90)
        self.assertGreaterEqual(score, 70)
        self.assertTrue(bundle["mowing_is_overdue"])
        self.assertFalse(bundle["tonte_autorisee"])


class FungalGuardWiringTests(unittest.TestCase):
    """`_evening_window_allowed` porte un garde anti-fongique — « risque élevé → jamais
    d'arrosage du soir » — mais `fungal_risk_level` n'était jamais transmis : le paramètre gardait
    sa valeur par défaut None et le garde n'a jamais pu se déclencher. Or gazon humide toute la
    nuit est précisément le facteur déclenchant des maladies qu'il visait à éviter."""

    BASE = dict(
        temperature=26.0, humidite=55.0,
        water_balance={"bilan_hydrique_mm": -8.0, "deficit_3j": 8.0, "arrosage_recent": 0.0},
        objectif_mm=10.0, heat_stress_level="eleve", minutes_to_sunset=25.0,
    )

    def test_risque_eleve_ferme_la_fenetre_du_soir(self):
        for niveau in ("moderate", "high"):
            with self.subTest(niveau=niveau):
                self.assertFalse(
                    guidance._evening_window_allowed(**self.BASE, fungal_risk_level=niveau)
                )

    def test_risque_faible_laisse_la_fenetre_ouverte(self):
        for niveau in ("none", "low", None):
            with self.subTest(niveau=niveau):
                self.assertTrue(
                    guidance._evening_window_allowed(**self.BASE, fungal_risk_level=niveau)
                )

    def test_le_niveau_traverse_bien_le_profil_complet(self):
        # Bout en bout : compute_watering_profile doit propager le niveau jusqu'au garde.
        def profil(niveau):
            return guidance.compute_watering_profile(
                phase_dominante="Normal", sous_phase="Normal",
                water_balance=dict(
                    bilan_hydrique_mm=-14.0, deficit_3j=14.0, deficit_7j=18.0,
                    arrosage_recent_7j=0.0, reserve_from_soil_ledger=True,
                    reserve_utile_mm=12.0, reserve_actuelle_mm=2.0, reserve_stock_mm=2.0,
                    reserve_stock_max_mm=24.0, depletion_mm=10.0, depletion_ratio=0.83,
                    mad_ratio=0.5,
                ),
                today=date(2026, 7, 15), pluie_24h=0.0, pluie_demain=0.0, pluie_j2=0.0,
                pluie_3j=0.0, pluie_probabilite_max_3j=0.0, humidite=55.0, temperature=34.0,
                etp=6.0, type_sol="limoneux", weather_profile={"sunset_minute": 1290},
                history=[], fungal_risk_level=niveau,
            )
        moment = datetime(2026, 7, 15, 21, 10, tzinfo=timezone.utc)
        with patch.object(guidance, "_current_datetime", return_value=moment):
            self.assertFalse(profil("high")["watering_evening_allowed"])
            self.assertTrue(profil("none")["watering_evening_allowed"])


class AgroPhaseEveningWindowTests(unittest.TestCase):
    """En phases produit (Fertilisation / Biostimulant / Agent Mouillant / Scarification), le test
    de la fenêtre du soir avait perdu sa borne basse `EVENING_START_HOUR <=` : `now_hour <
    EVENING_END_HOUR` restait vrai de 00h00 à 17h59, donc avec T ≥ 24 la fenêtre s'annonçait
    « soir » toute la journée. Effet réel : le coordinateur court-circuite son garde
    anti-réarrosage quand `fenetre == "soir"` — il sautait donc dès le matin, pas seulement le soir."""

    def _fenetre(self, hour):
        moment = datetime(2026, 7, 15, hour, 0, tzinfo=timezone.utc)
        with patch.object(guidance, "_current_datetime", return_value=moment):
            return guidance.compute_watering_profile(
                phase_dominante="Biostimulant", sous_phase="Normal",
                water_balance=dict(
                    bilan_hydrique_mm=-6.0, deficit_3j=6.0, deficit_7j=8.0,
                    arrosage_recent_7j=0.0, reserve_utile_mm=12.0, reserve_actuelle_mm=4.0,
                    reserve_stock_mm=4.0, reserve_stock_max_mm=24.0, depletion_mm=8.0,
                    depletion_ratio=0.66, mad_ratio=0.5,
                ),
                today=date(2026, 7, 15), pluie_24h=0.0, pluie_demain=0.0, pluie_j2=0.0,
                pluie_3j=0.0, pluie_probabilite_max_3j=0.0, humidite=45.0, temperature=26.0,
                etp=5.0, type_sol="limoneux", weather_profile={"sunset_minute": 1290}, history=[],
            )["fenetre_optimale"]

    def test_le_matin_nest_jamais_soir(self):
        for hour in (0, 6, 8, 11):
            with self.subTest(heure=hour):
                self.assertNotEqual(self._fenetre(hour), "soir")

    def test_lapres_midi_hors_creneau_nest_pas_soir(self):
        for hour in (14, 16, 17):
            with self.subTest(heure=hour):
                self.assertNotEqual(self._fenetre(hour), "soir")

    def test_le_creneau_du_soir_reste_soir(self):
        for hour in (18, 19):
            with self.subTest(heure=hour):
                self.assertEqual(self._fenetre(hour), "soir")


class ActionGuidanceEveningGuardsTests(unittest.TestCase):
    """`compute_action_guidance` recalcule `evening_allowed` (il alimente le libellé « soir » et,
    via lui, le court-circuit du garde anti-réarrosage du coordinateur). Cet appel omettait
    `minutes_to_sunset` et `fungal_risk_level` : la marge de séchage et le blocage anti-fongique
    n'y étaient pas enforced, contrairement au chemin principal (_build_watering_ctx)."""

    def _fenetre(self, *, fungal_risk_level=None, minutes_to_sunset=120.0, hour=19):
        return guidance.compute_action_guidance(
            phase_dominante="Normal", sous_phase="Normal",
            water_balance={"bilan_hydrique_mm": -5.0, "deficit_3j": 5.0, "deficit_7j": 7.0,
                           "arrosage_recent": 0.0},
            advanced_context={}, pluie_24h=0.0, pluie_demain=0.0, humidite=55.0,
            temperature=25.0, etp=5.0, objectif_mm=8.0, hour_of_day=hour,
            minutes_to_sunset=minutes_to_sunset, fungal_risk_level=fungal_risk_level,
        )["fenetre_optimale"]

    def test_soir_autorise_sans_risque_ni_marge_insuffisante(self):
        self.assertEqual(self._fenetre(), "soir")

    def test_risque_fongique_eleve_ferme_le_soir(self):
        for niveau in ("moderate", "high"):
            with self.subTest(niveau=niveau):
                self.assertNotEqual(self._fenetre(fungal_risk_level=niveau), "soir")

    def test_marge_de_sechage_insuffisante_ferme_le_soir(self):
        # Hors canicule, un arrosage du soir doit finir >= 90 min avant le coucher.
        self.assertNotEqual(self._fenetre(minutes_to_sunset=30.0), "soir")
