from __future__ import annotations

import unittest
from datetime import date
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

        self.assertEqual(payload["total_mm"], 3.6)
        self.assertEqual(payload["session_total_mm"], 3.6)
        self.assertEqual(len(payload["zones"]), 3)
        self.assertEqual(brain.history[-1]["total_mm"], 3.6)

    def test_register_product_persists_application_fields(self) -> None:
        brain = GazonBrain()
        record = brain.register_product(
            "bio-1",
            "Bio Boost",
            "Biostimulant",
            dose_conseillee="3.0 ml / L",
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
            today=date(2026, 3, 18),
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

        self.assertGreater(snapshot["bilan_hydrique_mm"], 12.0)
        self.assertEqual(snapshot["soil_balance"]["reserve_mm"], reloaded.soil_balance["reserve_mm"])
        self.assertEqual(reloaded.soil_balance["reserve_mm"], brain.soil_balance["reserve_mm"])
        self.assertIsNotNone(brain.last_result)
        self.assertEqual(brain.last_result.phase_active, snapshot["phase_active"])
        self.assertEqual(brain.last_result.extra["configuration"]["type_sol"], "limoneux")
        self.assertEqual(brain.last_result.extra["pluie_demain_source"], "meteo_forecast")
        self.assertIn("assistant", snapshot)
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
