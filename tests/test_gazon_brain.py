from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from importlib import util
from pathlib import Path
import sys
import types
from unittest.mock import patch


MODULE_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "gazon_intelligent"
)


def _ensure_package(name: str) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(MODULE_DIR if name.endswith("gazon_intelligent") else MODULE_DIR.parent)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _ensure_homeassistant_dt_module() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
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
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=timezone.utc)  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module


def _load_module(fullname: str, filename: str):
    spec = util.spec_from_file_location(fullname, MODULE_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {filename}")
    module = util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


_ensure_package("custom_components")
_ensure_package("custom_components.gazon_intelligent")
_ensure_homeassistant_dt_module()
_load_module("custom_components.gazon_intelligent.const", "const.py")
_load_module("custom_components.gazon_intelligent.water", "water.py")
_load_module("custom_components.gazon_intelligent.memory", "memory.py")
_load_module("custom_components.gazon_intelligent.soil_balance", "soil_balance.py")
DecisionResult = _load_module(
    "custom_components.gazon_intelligent.decision_models",
    "decision_models.py",
).DecisionResult
_load_module("custom_components.gazon_intelligent.decision", "decision.py")
gazon_brain_module = _load_module(
    "custom_components.gazon_intelligent.gazon_brain",
    "gazon_brain.py",
)
GazonBrain = gazon_brain_module.GazonBrain
decision_risk_module = _load_module(
    "custom_components.gazon_intelligent.decision_risk",
    "decision_risk.py",
)
decision_watering_module = _load_module(
    "custom_components.gazon_intelligent.decision_watering",
    "decision_watering.py",
)
compute_fungal_risk = decision_risk_module.compute_fungal_risk
compute_kc_gazon = decision_watering_module.compute_kc_gazon


class GazonBrainTests(unittest.TestCase):
    def test_load_state_sanitizes_legacy_payload(self) -> None:
        brain = GazonBrain()
        brain.load_state(
            {
                "mode": "Sursemis",
                "date_action": "2026-03-18",
                "history": [
                    {
                        "type": "arrosage",
                        "date": "2026-03-18",
                        "total_mm": 3.6,
                        "zones": [
                            {"zone": "zone_1", "mm": 1.2},
                            {"zone": "zone_2", "mm": 1.1},
                            {"zone": "zone_3", "mm": 1.3},
                        ],
                    }
                ],
                "products": {
                    "humuslight": {
                        "id": "humuslight",
                        "nom": "Humuslight",
                        "sol_compatible": "limoneux",
                    }
                },
                "soil_balance": {
                    "date": "2026-03-18",
                    "reserve_mm": "14.6",
                    "ledger": [],
                },
                "memory": {
                    "historique_total": 0,
                    "catalogue_produits": 0,
                },
            }
        )

        self.assertEqual(brain.mode, "Sursemis")
        self.assertEqual(brain.date_action, date(2026, 3, 18))
        self.assertEqual(brain.memory["historique_total"], 1)
        self.assertEqual(brain.memory["catalogue_produits"], 1)
        self.assertNotIn("sol_compatible", brain.products["humuslight"])

    def test_load_state_copies_nested_state_and_normalizes_memory(self) -> None:
        brain = GazonBrain()
        external_state = {
            "history": [
                {
                    "type": "arrosage",
                    "date": "2026-03-18",
                    "zones": [{"zone": "zone_1", "mm": 1.2}],
                }
            ],
            "products": {
                "bio-1": {
                    "id": "bio-1",
                    "nom": "Bio Boost",
                    "phase_compatible": ["Sursemis", "Croissance"],
                }
            },
            "memory": {
                "selected_product_id": "bio-1",
                "auto_irrigation_enabled": "yes",
                "feedback_observation": {"note": "initiale"},
            },
        }

        brain.load_state(external_state)
        external_state["history"][0]["zones"][0]["mm"] = 9.9
        external_state["products"]["bio-1"]["phase_compatible"].append("Entretien")
        external_state["memory"]["feedback_observation"]["note"] = "modifiee"

        self.assertEqual(brain.history[0]["zones"][0]["mm"], 1.2)
        self.assertEqual(brain.products["bio-1"]["phase_compatible"], ["Sursemis", "Croissance"])
        self.assertEqual(brain.memory["feedback_observation"]["note"], "initiale")
        self.assertTrue(brain.memory["auto_irrigation_enabled"] is not None)
        self.assertEqual(brain.memory["auto_irrigation_enabled"], gazon_brain_module.DEFAULT_AUTO_IRRIGATION_ENABLED)

    def test_dump_state_returns_isolated_copies(self) -> None:
        brain = GazonBrain()
        brain.load_state(
            {
                "history": [
                    {
                        "type": "arrosage",
                        "date": "2026-03-18",
                        "zones": [{"zone": "zone_1", "mm": 1.2}],
                    }
                ],
                "products": {
                    "bio-1": {
                        "id": "bio-1",
                        "nom": "Bio Boost",
                        "phase_compatible": ["Sursemis"],
                    }
                },
                "soil_balance": {"date": "2026-03-18", "reserve_mm": 14.6, "ledger": []},
                "memory": {"selected_product_id": "bio-1"},
            }
        )

        dumped = brain.dump_state()
        dumped["history"][0]["zones"][0]["mm"] = 9.9
        dumped["products"]["bio-1"]["phase_compatible"].append("Entretien")
        dumped["soil_balance"]["reserve_mm"] = 1.0
        dumped["memory"]["selected_product_id"] = None

        self.assertEqual(brain.history[0]["zones"][0]["mm"], 1.2)
        self.assertEqual(brain.products["bio-1"]["phase_compatible"], ["Sursemis"])
        self.assertEqual(brain.soil_balance["reserve_mm"], 14.6)
        self.assertEqual(brain.memory["selected_product_id"], "bio-1")

    def test_dump_state_accepts_date_action_string_from_runtime_snapshot(self) -> None:
        brain = GazonBrain()
        brain.date_action = "2026-04-15"  # type: ignore[assignment]

        dumped = brain.dump_state()

        self.assertEqual(dumped["date_action"], "2026-04-15")
        self.assertEqual(brain.date_action, "2026-04-15")

    def test_record_watering_keeps_rafraichissement_soir_cause(self) -> None:
        # Régression (bug 25-26/06) : la cause `rafraichissement_soir` (cooling du soir) DOIT être
        # écrite dans l'historique. Avant, la liste blanche l'excluait → cause droppée à `None` →
        # le cooling passait pour un arrosage normal (armait le cooldown 24 h + créditait la réserve).
        brain = GazonBrain()
        brain.record_watering(
            date_action=date(2026, 6, 26),
            total_mm=3.0,
            source="auto_irrigation",
            watering_cause="rafraichissement_soir",
        )
        self.assertEqual(brain.history[-1]["watering_cause"], "rafraichissement_soir")
        # L'arrosage hydrique normal reste bien étiqueté.
        brain.record_watering(
            date_action=date(2026, 6, 26),
            total_mm=8.0,
            source="auto_irrigation",
            watering_cause="hydrique",
        )
        self.assertEqual(brain.history[-1]["watering_cause"], "hydrique")

    def test_record_skip_basic(self) -> None:
        brain = GazonBrain()
        result = brain.record_skip(
            reason="recent_watering",
            fenetre="matin",
            objectif_mm=12.0,
            raison_decision="Réserve 5.0/12.0mm sous le seuil MAD",
            date_action=date(2026, 6, 28),
        )
        self.assertEqual(result["type"], "decision_skip")
        self.assertEqual(result["reason"], "recent_watering")
        self.assertEqual(result["fenetre"], "matin")
        self.assertEqual(result["objectif_mm"], 12.0)
        self.assertEqual(result["raison_decision"], "Réserve 5.0/12.0mm sous le seuil MAD")
        self.assertEqual(result["date"], "2026-06-28")
        self.assertIn(result, brain.history)

    def test_record_skip_minimal(self) -> None:
        brain = GazonBrain()
        result = brain.record_skip(reason="irrigation_blocked")
        self.assertEqual(result["type"], "decision_skip")
        self.assertEqual(result["reason"], "irrigation_blocked")
        self.assertNotIn("fenetre", result)
        self.assertNotIn("objectif_mm", result)
        self.assertNotIn("raison_decision", result)

    def test_record_skip_appended_to_history(self) -> None:
        brain = GazonBrain()
        brain.record_watering(date_action=date(2026, 6, 28), total_mm=12.0, source="auto_irrigation")
        brain.record_skip(reason="recent_watering", fenetre="soir", date_action=date(2026, 6, 28))
        self.assertEqual(len(brain.history), 2)
        self.assertEqual(brain.history[0]["type"], "arrosage")
        self.assertEqual(brain.history[1]["type"], "decision_skip")

    def test_set_normal_removes_active_phase_until_inclusive_end_then_keeps_expired_history(self) -> None:
        brain = GazonBrain()
        brain.history = [
            {"type": "Traitement", "date": "2026-04-10"},
            {"type": "arrosage", "date": "2026-04-10", "total_mm": 3.0},
        ]
        brain.mode = "Traitement"
        brain.date_action = date(2026, 4, 10)

        with patch.object(
            gazon_brain_module.dt_util,
            "now",
            return_value=datetime(2026, 4, 11, 8, 0, tzinfo=timezone.utc),
        ):
            brain.set_normal()

        self.assertEqual(len(brain.history), 1)
        self.assertEqual(brain.history[0]["type"], "arrosage")
        self.assertEqual(brain.mode, "Normal")
        self.assertIsNone(brain.date_action)

        brain.history = [
            {"type": "Traitement", "date": "2026-04-10"},
            {"type": "arrosage", "date": "2026-04-10", "total_mm": 3.0},
        ]

        with patch.object(
            gazon_brain_module.dt_util,
            "now",
            return_value=datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc),
        ):
            brain.set_normal()

        self.assertEqual(len(brain.history), 2)
        self.assertEqual(brain.history[0]["type"], "Traitement")

    def test_set_mode_records_phase_without_declaring_product(self) -> None:
        brain = GazonBrain()
        brain.register_product("bio-1", "Bio Boost", "Biostimulant")
        brain.register_product("engrais-printemps", "Engrais Printemps", "Fertilisation")
        brain.selected_product_id = None

        with patch.object(
            gazon_brain_module.dt_util,
            "now",
            return_value=datetime(2026, 4, 26, 8, 0, tzinfo=timezone.utc),
        ):
            brain.set_mode("Fertilisation")

        self.assertEqual(brain.mode, "Fertilisation")
        self.assertEqual(brain.date_action, date(2026, 4, 26))
        self.assertEqual(brain.history[-1]["type"], "Fertilisation")
        self.assertEqual(brain.history[-1]["date"], "2026-04-26")
        self.assertIsNone(brain.selected_product_id)

    def test_record_watering_keeps_session_summary(self) -> None:
        brain = GazonBrain()
        payload = brain.record_watering(
            date_action=date(2026, 3, 18),
            zones=[
                {"zone": "zone_1", "rate_mm_h": 2.4, "duration_min": 30.0, "mm": 1.2},
                {"zone": "zone_2", "rate_mm_h": 1.1, "duration_min": 60.0, "mm": 1.1},
                {"zone": "zone_3", "rate_mm_h": 1.3, "duration_min": 60.0, "mm": 1.3},
            ],
            source="auto_irrigation",
        )

        self.assertEqual(payload["objectif_mm"], 1.2)
        self.assertEqual(payload["objective_mm"], 1.2)
        self.assertEqual(payload["mm_scope"], "global_surface")
        self.assertEqual(payload["mm_interpretation"], "surface_uniform")
        self.assertEqual(payload["total_mm"], 1.2)
        self.assertEqual(payload["session_total_mm"], 1.2)
        self.assertEqual(payload["zones_total_mm"], 3.6)
        self.assertEqual(len(payload["zones"]), 3)
        self.assertEqual(brain.history[-1]["total_mm"], 1.2)

    def test_record_watering_persists_watering_cause_when_canonical(self) -> None:
        brain = GazonBrain()
        payload = brain.record_watering(
            date_action=date(2026, 3, 18),
            objectif_mm=5.0,
            total_mm=5.0,
            source="application_technique_auto",
            watering_cause="post_application",
        )

        self.assertEqual(payload["watering_cause"], "post_application")
        self.assertEqual(brain.history[-1]["watering_cause"], "post_application")

    def test_register_product_persists_application_fields(self) -> None:
        brain = GazonBrain()
        record = brain.register_product(
            "bio-1",
            "Bio Boost",
            "Biostimulant",
            dose_conseillee="3.0 ml / L",
            usage_mode="preventif",
            max_applications_per_year=6,
            reapplication_after_days=14,
            delai_avant_tonte_jours=0,
            phase_compatible="Sursemis, Reprise",
            application_months="3,4,5,9,10",
            application_type="sol",
            application_requires_watering_after=True,
            application_post_watering_mm=1.2,
            application_irrigation_block_hours=0.0,
            application_irrigation_delay_minutes=30.0,
            application_irrigation_mode="auto",
            application_label_notes="Arrosage léger après application",
            note="Produit test",
            temperature_min=8.0,
            temperature_max=28.0,
        )

        self.assertEqual(record["application_type"], "sol")
        self.assertTrue(record["application_requires_watering_after"])
        self.assertEqual(record["application_post_watering_mm"], 1.2)
        self.assertEqual(record["application_irrigation_block_hours"], 0.0)
        self.assertEqual(record["application_irrigation_delay_minutes"], 30.0)
        self.assertEqual(record["application_irrigation_mode"], "auto")
        self.assertEqual(record["application_label_notes"], "Arrosage léger après application")
        self.assertEqual(record["application_months"], [3, 4, 5, 9, 10])
        self.assertEqual(record["application_months_label"], "Mars à Mai, Septembre à Octobre")
        self.assertEqual(record["usage_mode"], "preventif")
        self.assertEqual(record["max_applications_per_year"], 6)
        self.assertEqual(record["temperature_min"], 8.0)
        self.assertEqual(record["temperature_max"], 28.0)

    def test_register_product_accepts_multi_phase_compatibility(self) -> None:
        brain = GazonBrain()
        record = brain.register_product(
            "humuslight",
            "Humuslight",
            "Biostimulant",
            dose_conseillee="1.2 ml / m²",
            phase_compatible=["Sursemis", "Croissance", "Entretien"],
        )

        self.assertEqual(record["phase_compatible"], ["Sursemis", "Croissance", "Entretien"])

    def test_declare_intervention_persists_application_fields(self) -> None:
        brain = GazonBrain()
        brain.register_product(
            "fungi-x",
            "Fongicide X",
            "Traitement",
            dose_conseillee="12 ml",
            application_type="foliaire",
            application_requires_watering_after=False,
            application_post_watering_mm=0.0,
            application_irrigation_block_hours=24.0,
            application_irrigation_delay_minutes=0.0,
            application_irrigation_mode="suggestion",
            application_label_notes="Ne pas arroser pendant 24h",
        )
        item = brain.declare_intervention(
            "Traitement",
            date_action=date(2026, 3, 18),
            produit_id="fungi-x",
            produit="Fongicide X",
            dose="12 ml",
            zone="zone_1",
            reapplication_after_days=21,
            application_type="foliaire",
            application_requires_watering_after=False,
            application_post_watering_mm=0.0,
            application_irrigation_block_hours=24.0,
            application_irrigation_delay_minutes=0.0,
            application_irrigation_mode="suggestion",
            application_label_notes="Ne pas arroser pendant 24h",
            note="Application test",
        )

        self.assertEqual(item["application_type"], "foliaire")
        self.assertFalse(item["application_requires_watering_after"])
        self.assertEqual(item["application_post_watering_mm"], 0.0)
        self.assertEqual(item["application_irrigation_block_hours"], 24.0)
        self.assertEqual(item["application_irrigation_delay_minutes"], 0.0)
        self.assertEqual(item["application_irrigation_mode"], "suggestion")
        self.assertEqual(item["application_label_notes"], "Ne pas arroser pendant 24h")
        self.assertIn("declared_at", item)
        self.assertIsNotNone(item["declared_at"])
        self.assertIn("produit_catalogue", item)

    def test_compute_snapshot_exposes_hydric_observability_fields(self) -> None:
        brain = GazonBrain()

        with patch.object(gazon_brain_module, "update_soil_balance") as update_soil_balance:
            update_soil_balance.return_value = {
                "date": "2026-04-08",
                "reserve_mm": 10.0,
                "previous_reserve_mm": 9.0,
                "pluie_mm": 0.0,
                "arrosage_mm": 0.0,
                "etp_mm": 1.4,
                "delta_mm": -1.0,
                "type_sol": "limoneux",
                "reserve_max_mm": 24.0,
                "reserve_min_mm": 0.0,
                "ledger": [],
            }
            snapshot = brain.compute_snapshot(
                today=date(2026, 4, 8),
                temperature=20.0,
                forecast_temperature_today=24.0,
                temperature_source="capteur",
                temperature_reference_hydrique=22.8,
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=60.0,
                type_sol="limoneux",
                etp_capteur=None,
                humidite_sol=None,
                vent=None,
                rosee=None,
                hauteur_gazon=None,
                retour_arrosage=None,
                pluie_source="capteur_pluie_24h",
                pluie_demain_source="meteo_forecast",
                weather_profile={},
                et0_source="fallback_temperature",
            )

        self.assertEqual(snapshot["temperature_reference_hydrique"], 22.8)
        self.assertEqual(snapshot["et0_source"], "fallback_temperature")
        self.assertEqual(snapshot["forecast_temperature_today"], 24.0)
        self.assertEqual(snapshot["temperature_source"], "capteur")
        self.assertEqual(snapshot["reserve_actuelle_mm"], 10.0)
        self.assertEqual(snapshot["reserve_utile_mm"], 12.0)
        self.assertAlmostEqual(snapshot["depletion_ratio"], 0.167, places=3)

    def _run_snapshot_capturing_ledger_etp(self, brain, *, etp_capteur, weather_profile):
        with patch.object(gazon_brain_module, "update_soil_balance") as usb:
            usb.return_value = {
                "date": "2026-07-25", "reserve_mm": 10.0, "previous_reserve_mm": 10.0,
                "pluie_mm": 0.0, "arrosage_mm": 0.0, "etp_mm": 0.0, "delta_mm": 0.0,
                "type_sol": "limoneux", "reserve_max_mm": 24.0, "reserve_min_mm": 0.0, "ledger": [],
            }
            brain.compute_snapshot(
                today=date(2026, 7, 25), temperature=30.0, forecast_temperature_today=31.0,
                temperature_source="capteur", temperature_reference_hydrique=None,
                pluie_24h=0.0, pluie_demain=0.0, humidite=40.0, type_sol="limoneux",
                etp_capteur=etp_capteur, humidite_sol=None, vent=None, rosee=None, hauteur_gazon=None,
                retour_arrosage=None, pluie_source="capteur_pluie_24h",
                pluie_demain_source="meteo_forecast", weather_profile=weather_profile,
                et0_source="capteur",
            )
            return usb.call_args.kwargs["etp_mm"]

    def test_ledger_debite_etc_pas_et0(self) -> None:
        # Le sol perd son eau au rythme de l'HERBE (ETc = ET0 × Kc), pas de l'ET0 brute. On force
        # ET0 = 10 (etp_capteur) et un Kc du cycle précédent = 0.55 (Hivernage) : le ledger doit
        # recevoir 10 × 0.55 = 5.5, prouvant qu'il applique le Kc du `last_result` (et non l'ET0).
        brain = GazonBrain()
        brain.last_result = DecisionResult(
            phase_dominante="Hivernage", sous_phase="Hivernage",
            action_recommandee="RAS", action_a_eviter="Aucune.", niveau_action="aucune_action",
            fenetre_optimale="attendre", risque_gazon="faible", objectif_arrosage=0.0,
            tonte_autorisee=True, tonte_statut="autorisee", conseil_principal="RAS",
            extra={"kc_gazon": 0.55},
        )
        etp_ledger = self._run_snapshot_capturing_ledger_etp(
            brain, etp_capteur=10.0, weather_profile={"et_elapsed_fraction": 1.0}
        )
        self.assertAlmostEqual(etp_ledger, 5.5, places=3)

    def test_ledger_kc_defaut_08_sans_cycle_precedent(self) -> None:
        # Premier cycle / après redémarrage : pas de `last_result` → repli Kc = 0.8 (Normal).
        # ET0 = 10 → ledger reçoit 8.0.
        brain = GazonBrain()
        brain.last_result = None
        etp_ledger = self._run_snapshot_capturing_ledger_etp(
            brain, etp_capteur=10.0, weather_profile={"et_elapsed_fraction": 1.0}
        )
        self.assertAlmostEqual(etp_ledger, 8.0, places=3)

    def test_compute_snapshot_keeps_last_valid_et0_and_etc_when_weather_is_not_ready(self) -> None:
        brain = GazonBrain()
        brain.last_result = DecisionResult(
            phase_dominante="Normal",
            sous_phase="Normal",
            action_recommandee="Surveille.",
            action_a_eviter="Aucune.",
            niveau_action="aucune_action",
            fenetre_optimale="attendre",
            risque_gazon="faible",
            objectif_arrosage=0.0,
            tonte_autorisee=True,
            tonte_statut="autorisee",
            conseil_principal="RAS",
            extra={"et0_mm": 0.7, "etc_mm": 0.6},
            water_balance={"et0_mm": 0.7},
        )

        with patch.object(gazon_brain_module, "update_soil_balance") as update_soil_balance:
            update_soil_balance.return_value = {
                "date": "2026-04-12",
                "reserve_mm": 10.0,
                "previous_reserve_mm": 10.0,
                "pluie_mm": 0.0,
                "arrosage_mm": 0.0,
                "etp_mm": None,
                "delta_mm": 0.0,
                "type_sol": "limoneux",
                "reserve_max_mm": 24.0,
                "reserve_min_mm": 0.0,
                "ledger": [],
            }
            snapshot = brain.compute_snapshot(
                today=date(2026, 4, 12),
                temperature=None,
                forecast_temperature_today=None,
                temperature_source="non disponible",
                temperature_reference_hydrique=None,
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=None,
                type_sol="limoneux",
                etp_capteur=None,
                humidite_sol=None,
                vent=None,
                rosee=None,
                hauteur_gazon=None,
                retour_arrosage=None,
                pluie_source="non disponible",
                pluie_demain_source="non disponible",
                weather_profile={},
                et0_source="fallback_temperature",
            )

        self.assertEqual(snapshot["et0_mm"], 0.7)
        self.assertEqual(snapshot["etc_mm"], 0.6)
        self.assertEqual(brain.last_result.extra["et0_mm"], 0.7)
        self.assertEqual(brain.last_result.extra["etc_mm"], 0.6)

    def test_compute_snapshot_keeps_persisted_et0_and_etc_when_restarting_without_last_result(self) -> None:
        brain = GazonBrain()
        brain.memory["last_valid_et0_mm"] = 0.7
        brain.memory["last_valid_etc_mm"] = 0.6
        brain.last_result = None

        with patch.object(gazon_brain_module, "update_soil_balance") as update_soil_balance:
            update_soil_balance.return_value = {
                "date": "2026-04-12",
                "reserve_mm": 10.0,
                "previous_reserve_mm": 10.0,
                "pluie_mm": 0.0,
                "arrosage_mm": 0.0,
                "etp_mm": None,
                "delta_mm": 0.0,
                "type_sol": "limoneux",
                "reserve_max_mm": 24.0,
                "reserve_min_mm": 0.0,
                "ledger": [],
            }
            snapshot = brain.compute_snapshot(
                today=date(2026, 4, 12),
                temperature=None,
                forecast_temperature_today=None,
                temperature_source="non disponible",
                temperature_reference_hydrique=None,
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=None,
                type_sol="limoneux",
                etp_capteur=None,
                humidite_sol=None,
                vent=None,
                rosee=None,
                hauteur_gazon=None,
                retour_arrosage=None,
                pluie_source="non disponible",
                pluie_demain_source="non disponible",
                weather_profile={},
                et0_source="fallback_temperature",
            )

        self.assertEqual(snapshot["et0_mm"], 0.7)
        self.assertEqual(snapshot["etc_mm"], 0.6)
        self.assertEqual(brain.memory["last_valid_et0_mm"], 0.7)
        self.assertEqual(brain.memory["last_valid_etc_mm"], 0.6)

    def test_declare_intervention_resolves_registered_product_by_name(self) -> None:
        brain = GazonBrain()
        brain.register_product(
            "bio-1",
            "Bio Boost",
            "Biostimulant",
            dose_conseillee="3.0 ml / L",
            application_type="sol",
            application_requires_watering_after=True,
            application_post_watering_mm=1.2,
            application_irrigation_block_hours=0.0,
            application_irrigation_delay_minutes=30.0,
            application_irrigation_mode="auto",
            application_label_notes="Arrosage léger après application",
        )

        item = brain.declare_intervention(
            "Biostimulant",
            date_action=date(2026, 3, 18),
            produit="Bio Boost",
            zone="zone_1",
        )

        self.assertEqual(item["produit_id"], "bio-1")
        self.assertEqual(item["produit"], "Bio Boost")
        self.assertEqual(item["application_type"], "sol")
        self.assertTrue(item["application_requires_watering_after"])
        self.assertEqual(item["application_post_watering_mm"], 1.2)
        self.assertEqual(item["application_irrigation_mode"], "auto")
        self.assertIn("produit_catalogue", item)
        self.assertEqual(item["produit_catalogue"]["id"], "bio-1")

    def test_declare_intervention_uses_unique_registered_product_without_identifier(self) -> None:
        brain = GazonBrain()
        brain.register_product(
            "engrais-printemps",
            "Engrais Printemps",
            "Fertilisation",
            dose_conseillee="2 g / m²",
            application_type="sol",
            application_requires_watering_after=False,
            application_post_watering_mm=0.0,
            application_irrigation_block_hours=12.0,
            application_irrigation_delay_minutes=0.0,
            application_irrigation_mode="suggestion",
            application_label_notes="Produit saisonnier",
        )

        item = brain.declare_intervention(
            "Fertilisation",
            date_action=date(2026, 3, 18),
            zone="zone_2",
        )

        self.assertEqual(item["produit_id"], "engrais-printemps")
        self.assertEqual(item["produit"], "Engrais Printemps")
        self.assertEqual(item["application_type"], "sol")
        self.assertFalse(item["application_requires_watering_after"])
        self.assertEqual(item["application_irrigation_mode"], "suggestion")
        self.assertIn("produit_catalogue", item)
        self.assertEqual(item["produit_catalogue"]["id"], "engrais-printemps")

    def test_load_state_restores_selected_product_id_only_when_valid(self) -> None:
        brain = GazonBrain()
        brain.load_state(
            {
                "products": {
                    "bio-1": {"id": "bio-1", "nom": "Bio Boost"},
                },
                "memory": {
                    "selected_product_id": "bio-1",
                },
            }
        )

        self.assertEqual(brain.selected_product_id, "bio-1")
        self.assertEqual(brain.selected_product_name, "Bio Boost")
        self.assertEqual(brain.dump_state()["memory"]["selected_product_id"], "bio-1")

        brain.load_state(
            {
                "products": {
                    "bio-1": {"id": "bio-1", "nom": "Bio Boost"},
                    "engrais-printemps": {"id": "engrais-printemps", "nom": "Engrais Printemps"},
                },
                "memory": {
                    "selected_product_id": "unknown",
                },
            }
        )

        self.assertIsNone(brain.selected_product_id)
        self.assertIsNone(brain.selected_product_name)
        self.assertIsNone(brain.dump_state()["memory"]["selected_product_id"])

    def test_selected_product_id_normalizes_after_product_removal(self) -> None:
        brain = GazonBrain()
        brain.register_product("bio-1", "Bio Boost", "Biostimulant")
        brain.register_product("engrais-printemps", "Engrais Printemps", "Fertilisation")
        brain.selected_product_id = "bio-1"

        brain.remove_product("bio-1")

        self.assertEqual(brain.selected_product_id, "engrais-printemps")
        self.assertEqual(brain.selected_product_name, "Engrais Printemps")

        brain.remove_product("engrais-printemps")

        self.assertIsNone(brain.selected_product_id)
        self.assertIsNone(brain.selected_product_name)

    def test_remove_last_application_removes_latest_application_only(self) -> None:
        brain = GazonBrain()
        brain.register_product("bio-1", "Bio Boost", "Biostimulant")
        brain.register_product("engrais-printemps", "Engrais Printemps", "Fertilisation")

        first = brain.declare_intervention(
            "Biostimulant",
            date_action=date(2026, 3, 17),
            produit_id="bio-1",
            zone="zone_1",
        )
        self.assertEqual(first["produit_id"], "bio-1")
        brain.record_watering(date(2026, 3, 18))
        brain.selected_product_id = None
        second = brain.declare_intervention(
            "Fertilisation",
            date_action=date(2026, 3, 19),
            produit_id="engrais-printemps",
            zone="zone_2",
        )
        self.assertEqual(second["produit_id"], "engrais-printemps")
        brain.record_watering(date(2026, 3, 20))

        removed = brain.remove_last_application()

        self.assertEqual(removed["produit_id"], "engrais-printemps")
        self.assertEqual(removed["type"], "Fertilisation")
        self.assertEqual(brain.mode, "Biostimulant")
        self.assertEqual(brain.date_action, date(2026, 3, 17))
        self.assertEqual(brain.memory["historique_total"], 3)
        self.assertIsNotNone(brain.memory["derniere_application"])
        self.assertEqual(brain.memory["derniere_application"]["produit_id"], "bio-1")
        self.assertEqual(brain.memory["derniere_application"]["type"], "Biostimulant")

    def test_remove_last_application_rejects_when_no_application_exists(self) -> None:
        brain = GazonBrain()
        brain.record_mowing(date(2026, 3, 18))
        brain.record_watering(date(2026, 3, 18))

        with self.assertRaises(ValueError) as ctx:
            brain.remove_last_application()

        self.assertIn("Aucune application", str(ctx.exception))

    def test_declare_intervention_uses_persisted_selected_product(self) -> None:
        brain = GazonBrain()
        brain.register_product("bio-1", "Bio Boost", "Biostimulant")
        brain.register_product("engrais-printemps", "Engrais Printemps", "Fertilisation")
        brain.selected_product_id = "bio-1"

        item = brain.declare_intervention(
            "Biostimulant",
            date_action=date(2026, 3, 18),
            zone="zone_1",
        )

        self.assertEqual(item["produit_id"], "bio-1")
        self.assertEqual(item["produit"], "Bio Boost")
        self.assertEqual(item["produit_catalogue"]["id"], "bio-1")

    def test_declare_intervention_requires_exact_product_match(self) -> None:
        brain = GazonBrain()
        brain.register_product("bio-1", "Bio Boost", "Biostimulant")
        brain.register_product("engrais-printemps", "Engrais Printemps", "Fertilisation")
        brain.selected_product_id = None

        with self.assertRaises(ValueError) as ctx:
            brain.declare_intervention(
                "Fertilisation",
                date_action=date(2026, 3, 18),
                produit="Boost",
                zone="zone_2",
            )

        self.assertIn("ID exact ou le nom exact", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx_no_choice:
            brain.declare_intervention(
                "Fertilisation",
                date_action=date(2026, 3, 18),
                zone="zone_2",
            )

        self.assertIn("Plusieurs produits sont enregistrés", str(ctx_no_choice.exception))

    def test_declare_intervention_rejects_conflicting_ui_selection(self) -> None:
        brain = GazonBrain()
        brain.register_product("bio-1", "Bio Boost", "Biostimulant")
        brain.register_product("engrais-printemps", "Engrais Printemps", "Fertilisation")
        brain.selected_product_id = "bio-1"

        with self.assertRaises(ValueError) as ctx:
            brain.declare_intervention(
                "Fertilisation",
                date_action=date(2026, 3, 18),
                produit_id="engrais-printemps",
                zone="zone_2",
            )

        self.assertIn("source de vérité", str(ctx.exception))

    def test_declare_intervention_keeps_catalog_snapshot_frozen(self) -> None:
        brain = GazonBrain()
        brain.register_product(
            "bio-1",
            "Bio Boost",
            "Biostimulant",
            dose_conseillee="3.0 ml / L",
            application_type="sol",
            application_requires_watering_after=True,
            application_post_watering_mm=1.2,
            application_irrigation_block_hours=0.0,
            application_irrigation_delay_minutes=30.0,
            application_irrigation_mode="auto",
            application_label_notes="Arrosage léger après application",
        )

        item = brain.declare_intervention(
            "Biostimulant",
            date_action=date(2026, 3, 18),
            produit_id="bio-1",
            zone="zone_1",
        )

        original_snapshot = dict(item["produit_catalogue"])
        brain.register_product(
            "bio-1",
            "Bio Boost 2",
            "Biostimulant",
            dose_conseillee="1.0 ml / L",
            application_type="foliaire",
            application_requires_watering_after=False,
            application_post_watering_mm=0.0,
            application_irrigation_block_hours=12.0,
            application_irrigation_delay_minutes=0.0,
            application_irrigation_mode="suggestion",
            application_label_notes="Nouvelle version",
        )

        self.assertEqual(item["produit_catalogue"], original_snapshot)
        self.assertEqual(item["produit_catalogue"]["nom"], "Bio Boost")
        self.assertEqual(item["produit_catalogue"]["application_type"], "sol")
        self.assertEqual(brain.products["bio-1"]["nom"], "Bio Boost 2")
        self.assertEqual(brain.products["bio-1"]["application_type"], "foliaire")

    def test_record_user_action_is_persisted(self) -> None:
        brain = GazonBrain()
        summary = brain.record_user_action(
            action="Plan d'arrosage lancé",
            state="ok",
            reason="Plan lancé immédiatement.",
            plan_type="multi_zone",
            zone_count=2,
            passages=1,
        )

        self.assertEqual(summary["state"], "ok")
        self.assertEqual(brain.memory["derniere_action_utilisateur"]["action"], "Plan d'arrosage lancé")
        self.assertEqual(brain.memory["derniere_action_utilisateur"]["plan_type"], "multi_zone")

        reloaded = GazonBrain()
        reloaded.load_state(brain.dump_state())
        self.assertEqual(reloaded.memory["derniere_action_utilisateur"]["state"], "ok")
        self.assertEqual(reloaded.memory["derniere_action_utilisateur"]["zone_count"], 2)

    def test_compute_snapshot_updates_and_persists_soil_balance(self) -> None:
        brain = GazonBrain()
        brain.register_product(
            "humuslight",
            "Humuslight",
            type_produit="Biostimulant",
            usage_mode="preventif",
            max_applications_per_year=2,
            reapplication_after_days=25,
            phase_compatible=["Sursemis", "Croissance", "Entretien"],
            application_months=[3, 4, 5, 9, 10],
            temperature_min=8,
            temperature_max=28,
        )
        brain.record_watering(
            date_action=date(2026, 3, 18),
            total_mm=3.6,
            zones=[
                {"zone": "zone_1", "rate_mm_h": 2.4, "duration_min": 30.0, "mm": 1.2},
                {"zone": "zone_2", "rate_mm_h": 1.1, "duration_min": 60.0, "mm": 1.1},
                {"zone": "zone_3", "rate_mm_h": 1.3, "duration_min": 60.0, "mm": 1.3},
            ],
            source="auto_irrigation",
        )
        snapshot = brain.compute_snapshot(
            today=date(2026, 4, 10),
            temperature=20.0,
            pluie_24h=1.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=2.0,
            humidite_sol=None,
            vent=None,
            rosee=None,
            hauteur_gazon=None,
            retour_arrosage=None,
            pluie_source="capteur_pluie_24h",
            pluie_demain_source="meteo_forecast",
            weather_profile={},
        )
        reloaded = GazonBrain()
        reloaded.load_state(brain.dump_state())

        self.assertGreater(snapshot["reserve_hydrique_sol_mm"], 10.0)
        self.assertIn("bilan_hydrique_mm", snapshot)
        self.assertIn("bilan_hydrique_mm", brain.last_result.extra)
        self.assertIn("soil_balance", brain.last_result.extra)
        self.assertEqual(snapshot["soil_balance"]["reserve_mm"], reloaded.soil_balance["reserve_mm"])
        self.assertEqual(reloaded.soil_balance["reserve_mm"], brain.soil_balance["reserve_mm"])
        self.assertIsNotNone(brain.last_result)
        self.assertEqual(brain.last_result.phase_active, snapshot["phase_active"])
        self.assertEqual(brain.last_result.extra["configuration"]["type_sol"], "limoneux")
        self.assertEqual(brain.last_result.extra["pluie_demain_source"], "meteo_forecast")
        self.assertIn("assistant", snapshot)
        recommendation = snapshot["intervention_recommendation"]
        self.assertEqual(recommendation["context"]["current_month"], 4)
        phase_constraint = next(item for item in recommendation["constraints"] if item.get("code") == "phase_compatibility")
        self.assertEqual(phase_constraint["value"]["current"], "Normal")
        month_constraint = next(item for item in recommendation["constraints"] if item.get("code") == "application_months")
        self.assertEqual(month_constraint["value"]["current_month"], 4)
        self.assertEqual(
            set(snapshot["assistant"].keys()),
            {"action", "moment", "quantity_mm", "status", "reason"},
        )

    def test_compute_snapshot_adds_temperature_note_to_watering_conseil(self) -> None:
        brain = GazonBrain()
        fake_result = DecisionResult(
            phase_dominante="Normal",
            sous_phase="Normal",
            action_recommandee="Arroser maintenant en un passage.",
            action_a_eviter="Aucune",
            niveau_action="a_faire",
            fenetre_optimale="maintenant",
            risque_gazon="modere",
            objectif_arrosage=1.0,
            tonte_autorisee=True,
            conseil_principal="Arroser maintenant en un passage.",
            tonte_statut="autorisee",
            arrosage_recommande=True,
            arrosage_auto_autorise=True,
            type_arrosage="auto",
            arrosage_conseille="auto",
            watering_passages=1,
            watering_pause_minutes=25,
            phase_dominante_source="historique_actif",
            sous_phase_detail="Normal",
            sous_phase_age_days=0,
            sous_phase_progression=0,
            prochaine_reevaluation="dans 24 h",
            urgence="moyenne",
            raison_decision="Test",
            score_hydrique=42,
            score_stress=33,
            score_tonte=12,
            advanced_context={"niveau_action": "a_faire"},
            water_balance={"bilan_hydrique_mm": 1.0},
            phase_context=None,
            extra={"configuration": {"type_sol": "limoneux"}},
        )

        with patch.object(gazon_brain_module, "build_decision_result", return_value=fake_result):
            snapshot = brain.compute_snapshot(
                today=date(2026, 6, 15),
                hour_of_day=7,
                temperature=20.0,
                forecast_temperature_today=18.2,
                temperature_source="capteur",
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=60.0,
                type_sol="limoneux",
                etp_capteur=3.0,
                humidite_sol=None,
                vent=None,
                rosee=None,
                hauteur_gazon=None,
                retour_arrosage=None,
                pluie_source="capteur_pluie_24h",
                pluie_demain_source="meteo_forecast",
                weather_profile={},
            )

        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertIn("température réelle 20.0°C", snapshot["conseil_principal"])
        self.assertIn("prévision du jour 18.2°C", snapshot["conseil_principal"])
        self.assertEqual(
            brain.last_result.extra["temperature_note"],
            "température réelle 20.0°C, prévision du jour 18.2°C",
        )


class FungalRiskTests(unittest.TestCase):
    def test_fungal_risk_high_conditions(self) -> None:
        result = compute_fungal_risk(
            temperature=18.0,
            humidite=90.0,
            rosee=1.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            hour_of_day=7,
        )
        self.assertEqual(result["fungal_risk_level"], "high")
        self.assertTrue(result["fungal_risk_evening_block"])
        self.assertTrue(result["fungal_risk_reduce_watering"])

    def test_fungal_risk_no_conditions(self) -> None:
        result = compute_fungal_risk(
            temperature=30.0,
            humidite=50.0,
            rosee=0.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            hour_of_day=14,
        )
        self.assertEqual(result["fungal_risk_level"], "none")
        self.assertFalse(result["fungal_risk_evening_block"])
        self.assertFalse(result["fungal_risk_reduce_watering"])


class KcPostMowingTests(unittest.TestCase):
    def test_kc_post_mowing_j3(self) -> None:
        kc_base = compute_kc_gazon("Normal")
        kc_post = compute_kc_gazon("Normal", days_since_mowing=3)
        self.assertGreater(kc_post, kc_base)

    def test_kc_post_mowing_j10(self) -> None:
        kc_base = compute_kc_gazon("Normal")
        kc_post = compute_kc_gazon("Normal", days_since_mowing=10)
        self.assertGreater(kc_post, kc_base)

    def test_kc_post_mowing_j20(self) -> None:
        kc_base = compute_kc_gazon("Normal")
        kc_post = compute_kc_gazon("Normal", days_since_mowing=20)
        self.assertEqual(kc_post, kc_base)


class LedgerOnlyCountsMeasuredRainTests(unittest.TestCase):
    """`pluie_24h` est une valeur RÉSOLUE : elle bascule silencieusement sur la prévision météo
    quand le capteur de pluie est indisponible. Créditer la réserve avec de la pluie ANNONCÉE mais
    jamais tombée provoque un sous-arrosage durable — et le capteur ici est la station Netatmo
    d'un voisin, hors de tout contrôle, qui peut disparaître à tout moment."""

    def _reserve(self, *, pluie, source):
        brain = GazonBrain()
        brain.soil_balance = {
            "date": "2026-07-22", "reserve_mm": 6.0, "previous_reserve_mm": 6.0,
            "pluie_mm": 0.0, "arrosage_mm": 0.0, "etp_mm": 0.0, "delta_mm": 0.0,
            "type_sol": "limoneux", "reserve_max_mm": 24.0, "reserve_min_mm": 0.0,
            "ledger": [],
        }
        brain.compute_snapshot(
            today=date(2026, 7, 23), hour_of_day=8,
            temperature=20.0, pluie_24h=pluie, pluie_demain=0.0, humidite=55.0,
            etp_capteur=0.0, type_sol="limoneux",
            pluie_source=source, pluie_demain_source="meteo_forecast",
            humidite_sol=None, vent=None, rosee=None, hauteur_gazon=None,
            retour_arrosage=None, weather_profile={},
        )
        return brain.soil_balance["ledger"][-1]["pluie_mm"]

    def test_pluie_mesuree_est_creditee(self) -> None:
        self.assertEqual(self._reserve(pluie=8.0, source="capteur"), 8.0)

    def test_variante_de_nom_de_source_capteur_reconnue(self) -> None:
        # La source s'écrit "capteur" côté coordinateur, "capteur_pluie_24h" ailleurs.
        self.assertEqual(self._reserve(pluie=8.0, source="capteur_pluie_24h"), 8.0)

    def test_pluie_prevue_nest_pas_creditee(self) -> None:
        self.assertEqual(self._reserve(pluie=8.0, source="meteo_forecast"), 0.0)

    def test_source_indisponible_nest_pas_creditee(self) -> None:
        self.assertEqual(self._reserve(pluie=8.0, source="non disponible"), 0.0)
