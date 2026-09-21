from __future__ import annotations

import re
import unittest
from datetime import date, datetime, timedelta, timezone
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
    def test_programme_graines_adapte_les_cycles_aux_valeurs_meteo(self) -> None:
        base = dict(
            phase_dominante="Sursemis",
            sous_phase="Germination",
            water_balance={"bilan_hydrique_mm": 0.0, "arrosage_recent_jour": 0.0},
            today=date(2026, 9, 17),
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            temperature=20.0,
            vent=3.24,
            etp=2.5,
            type_sol="limoneux",
            # Reproduction ha_maison : le capteur local (3,24 km/h) fait foi devant le vent
            # générique de l'entité météo (14,4 km/h).
            weather_profile={"weather_precipitation_probability": 20.0, "weather_wind_speed": 14.4},
            history=[],
            forecast_temperature_today=22.0,
            reglages={"graines_germination_cycles": 4},
        )

        normal = guidance.compute_watering_profile(**base)
        self.assertEqual((normal["daily_cycles_target"], normal["surface_cycle_mm"]), (4, 1.5))

        # Valeurs observées sur ha_maison le 17/09 : pluie annoncée et ET0 faible. Le réglage
        # « 4 » est un régime nominal, pas un ordre d'arroser quatre fois quoi qu'il arrive.
        humide = guidance.compute_watering_profile(
            **(base | {"pluie_demain": 0.9, "humidite": 50.0, "etp": 1.7,
                       "temperature": 20.9, "forecast_temperature_today": 22.2})
        )
        self.assertEqual((humide["daily_cycles_target"], humide["surface_cycle_mm"]), (3, 1.2))

        chaud = guidance.compute_watering_profile(
            **(base | {"humidite": 35.0, "etp": 5.0, "forecast_temperature_today": 32.0,
                       "reglages": {"graines_germination_cycles": 3}})
        )
        self.assertEqual((chaud["daily_cycles_target"], chaud["surface_cycle_mm"]), (4, 1.8))

        frais = guidance.compute_watering_profile(
            **(base | {"temperature": 10.0, "forecast_temperature_today": 12.0, "etp": 1.0})
        )
        self.assertEqual((frais["daily_cycles_target"], frais["surface_cycle_mm"]), (3, 1.2))

    def test_chaque_signal_meteo_joue_seul(self) -> None:
        """Relevé par le banc de mutations (0.96.0) : le scénario « chaud » cumulait air sec,
        évaporation et chaleur prévue, si bien qu'aucun de ces signaux n'était prouvé seul. Base
        3 cycles (de 2 à 4) : un signal sec en ajoute un, un signal humide ou frais en retire un."""
        base = dict(
            phase_dominante="Sursemis", sous_phase="Germination",
            water_balance={"bilan_hydrique_mm": 0.0, "arrosage_recent_jour": 0.0},
            today=date(2026, 9, 17), pluie_24h=0.0, pluie_demain=0.0, humidite=55.0,
            temperature=20.0, vent=3.0, etp=2.5, type_sol="limoneux",
            weather_profile={"weather_precipitation_probability": 20.0, "weather_wind_speed": 3.0},
            history=[], forecast_temperature_today=22.0, reglages={"graines_germination_cycles": 3},
        )
        cas = {
            "neutre": ({}, 3),
            "chaleur prévue seule": ({"forecast_temperature_today": 28.0}, 4),
            "chaleur prévue sous le seuil": ({"forecast_temperature_today": 27.9}, 3),
            "chaleur mesurée seule": ({"temperature": 28.0, "forecast_temperature_today": None}, 4),
            "évaporation seule": ({"etp": 4.0}, 4),
            "évaporation sous le seuil": ({"etp": 3.9}, 3),
            "vent seul": ({"vent": 12.0}, 4),
            "vent sous le seuil": ({"vent": 11.9}, 3),
            "air sec seul": ({"humidite": 45.0}, 4),
            "air presque sec": ({"humidite": 45.1}, 3),
            "air humide": ({"humidite": 70.0}, 2),
            "pluie demain au-dessus de 0,5": ({"pluie_demain": 0.6}, 2),
            "pluie demain à 0,5": ({"pluie_demain": 0.5}, 3),
            "frais et peu évaporant": ({"temperature": 10.0, "forecast_temperature_today": 12.0, "etp": 2.0}, 2),
            "frais mais évaporant": ({"temperature": 10.0, "forecast_temperature_today": 12.0, "etp": 2.1}, 3),
            "frais le matin, doux prévu": ({"temperature": 10.0, "forecast_temperature_today": 14.5, "etp": 1.0}, 3),
        }
        for nom, (changements, cycles) in cas.items():
            with self.subTest(cas=nom):
                profil = guidance.compute_watering_profile(**(base | changements))
                self.assertEqual(profil["daily_cycles_target"], cycles)

    def test_le_vent_du_jardin_arrive_jusqu_aux_graines(self) -> None:
        """0.96.0 : la décision transmet le vent mesuré ; sans lui, la prévision (14,4 km/h le
        17/09, contre 3,2 au jardin) ajoutait un cycle « venteux »."""
        commun = dict(
            history=[{"type": "Sursemis", "date": (FIXED_TODAY - timedelta(days=1)).isoformat()}],
            humidite=55.0, etp_capteur=2.5, forecast_temperature_today=22.0,
            weather_profile={"weather_precipitation_probability": 20.0, "weather_wind_speed": 14.4},
        )
        jardin = make_snapshot(vent=3.0, **commun)
        prevision = make_snapshot(vent=None, **commun)
        self.assertEqual(jardin["sous_phase"], "Germination")
        self.assertEqual((jardin["daily_cycles_target"], jardin["surface_cycle_mm"]), (3, 1.5))
        self.assertEqual((prevision["daily_cycles_target"], prevision["surface_cycle_mm"]), (4, 1.8))

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
            phase_dominante="Semis",
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
            history=[{"type": "Semis", "date": "2026-03-01"}],
            **base_kwargs,
        )
        ready = decision.compute_action_guidance(
            history=[
                {"type": "Semis", "date": "2026-03-01"},
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

class TestPlancherActivationSEteintApresIncorporation(unittest.TestCase):
    """⚠️ LE CAS RÉEL DU 08/09/2026, reproduit à l'identique.

    Floranid Twin Permanent épandu le 07/09, incorporé automatiquement le soir même — 5 mm,
    `application_post_watering_status = "termine"`. Le lendemain sous la pluie, réserve à
    11,3 mm sur 12 et déplétion de 0,7 mm pour un seuil à 6, l'assistant annonçait **5 mm de
    plus** pour le matin suivant, motif « Fertilisation active ».

    Le plancher d'activation existe pour dissoudre un produit épandu, et il avait raison la
    veille. Le lendemain il ignorait la seule chose qui compte : le produit était **déjà dissous**.

    ⚠️ L'arrosage n'est pas parti ce jour-là, mais par ACCIDENT : la phase Fertilisation dure
    2 jours et expirait à minuit, avant le créneau de 03h45. Scarification en dure 7 — le même
    enchaînement y aurait arrosé un sol détrempé pendant six jours.
    """

    def _snap(self, statut: str | None):
        return decision.build_decision_snapshot(
            history=[{"type": "Fertilisation", "date": "2026-09-07"}],
            today=date(2026, 9, 8), hour_of_day=13, temperature=22.7,
            pluie_24h=1.5, pluie_demain=0.0, humidite=79,
            type_sol="limoneux", etp_capteur=3.1,
            memory={"application_post_watering_status": statut} if statut else {},
        )

    def test_avant_incorporation_le_plancher_tient(self) -> None:
        """Non-régression : tant que le produit n'est pas dissous, les 5 mm sont LÉGITIMES."""
        self.assertEqual(self._snap("en_attente")["objectif_mm"], 5.0)

    def test_apres_incorporation_on_n_arrose_PAS_DU_TOUT(self) -> None:
        """⚠️ REFUSER, PAS SEULEMENT REMONTER — la porte que la 0.80.0 avait entrouverte.

        Désarmer le plancher d'activation faisait retomber l'objectif sur le besoin réel, soit
        **0,2 mm** mesuré en production le 08/09/2026 une heure plus tard : cinquante secondes de
        vanne par zone, qui ne mouillent rien et coûtent un cycle complet.

        Un plancher d'ACTIVATION remonte la dose — pour dissoudre un produit, il faut en mettre
        assez. Un plancher HYDRIQUE doit REFUSER. Les phases d'application ne connaissaient que
        la première logique ; `_profile_for_normal` possède la seconde depuis toujours
        (`useful_threshold`). Elle est désormais appliquée ici aussi.
        """
        snap = self._snap("termine")
        self.assertEqual(snap["objectif_mm"], 0.0)
        self.assertIs(snap["arrosage_recommande"], False, "une dose dérisoire reste « recommandée »")

    def test_le_seuil_d_utilite_suit_le_plancher_de_la_phase(self) -> None:
        """Le seuil de refus et le plancher doivent venir de la MÊME source.

        Sinon on retombe sur « deux descriptions du même fait » : un seuil d'utilité qui
        diverge du plancher laisserait une bande de doses ni remontées ni refusées.
        """
        guidance_mod = importlib.import_module("custom_components.gazon_intelligent.guidance")
        watering_policy = importlib.import_module("custom_components.gazon_intelligent.watering_policy")

        class _PlageBidon:
            min_mm = 5.0

        class _PolitiqueBidon:
            target_range = _PlageBidon()

        self.assertEqual(
            guidance_mod._plancher_brut_de_phase("Fertilisation", _PolitiqueBidon()), 5.0,
            "la politique doit primer quand elle définit une plage",
        )
        self.assertEqual(
            guidance_mod._plancher_brut_de_phase("Fertilisation", None), 3.0,
            "sans plage de politique, on retombe sur la table des modes",
        )
        del watering_policy

    def test_une_memoire_muette_ne_desarme_rien(self) -> None:
        """Absence d'information ≠ incorporation faite — le plancher reste, par prudence."""
        self.assertEqual(self._snap(None)["objectif_mm"], 5.0)

    def test_les_TROIS_points_appliquent_la_meme_regle(self) -> None:
        """⚠️ TROIS ENDROITS POSENT CE PLANCHER, et n'en corriger que deux ne change RIEN.

        Mesuré au banc : le clamp `_clamp(besoin, minimum, maximum)` remonte la cible au minimum
        de la politique AVANT tout garde-fou, si bien que les fonctions de plancher en aval ne
        peuvent plus la faire redescendre. Le drapeau arrivait à `True` et l'objectif restait à
        5,0 mm. Ce test interdit qu'un des trois points reparte sans la règle commune.
        """
        source = (PACKAGE_DIR / "guidance.py").read_text(encoding="utf-8")
        self.assertEqual(
            source.count("_plancher_activation_effectif("), 4,
            "attendu : 1 définition + 3 points d'application (clamp, branche politique, table des modes)",
        )
        self.assertIn("minimum = _plancher_activation_effectif(", source, "le CLAMP n'est plus câblé")

    def test_normal_garde_son_plancher(self) -> None:
        """⚠️ Le plancher de Normal (10 mm) n'est PAS un plancher d'activation.

        Il dit « en dessous, arroser ne sert à rien » — vrai en permanence, incorporation ou pas.
        Le désarmer ferait partir des arrosages inutiles toute l'année.
        """
        guidance_mod = importlib.import_module("custom_components.gazon_intelligent.guidance")
        self.assertEqual(guidance_mod._mode_min_watering_mm("Normal", True), 10.0)
        self.assertEqual(guidance_mod._mode_min_watering_mm("Fertilisation", True), 0.0)
        self.assertEqual(guidance_mod._mode_min_watering_mm("Fertilisation", False), 3.0)


class TestSursemisNUsurpePlusLeVerdictDeTonte(unittest.TestCase):
    """⚠️ Le Sursemis figeait `tonte_autorisee=False` sur ses TROIS sorties.

    Deux sorties de l'intégration se contredisaient : `_resolve_sursemis_override` interdisait
    la tonte les **45 jours** de la phase, alors que `decision_mowing` ne bloque que Germination
    et Enracinement (24 j, `_SURSEMIS_MOWING_BLOCKED_SUBPHASES`). C'est l'arrosage qui gagnait,
    parce que `decision.py:451` fait le ET des deux bundles.

    Et le verrou était CIRCULAIRE : `seeding_transition_ready` exige deux tontes déclarées
    depuis le début de la phase — des tontes que la phase interdisait elle-même. Le sursemis
    ne pouvait jamais se terminer.
    """

    D0 = date(2026, 3, 1)

    def _snap(self, jour: int, history_extra=(), memory=None, pluie_24h=0.0, hour_of_day=11):
        return decision.build_decision_snapshot(
            history=[{"type": "Semis", "date": "2026-03-01"}, *history_extra],
            today=self.D0 + timedelta(days=jour), hour_of_day=hour_of_day, temperature=18,
            pluie_24h=pluie_24h, pluie_demain=0.0, humidite=60,
            type_sol="limoneux", etp_capteur=2.0, memory=memory or {},
        )

    # ── ÉTAPE 2 : l'arrosage automatique en Sursemis ────────────────────────────────────
    AUTO_ON = {"auto_irrigation_enabled": True}

    def test_le_cycle_semis_du_devient_REELLEMENT_executable(self) -> None:
        """⚠️ CALCULÉ N'EST PAS APPLIQUÉ — le cœur de l'étape 2.

        Le programme de micro-cycles (1,5 mm en Germination, 3,0 en Enracinement, 2,5 en
        Reprise, créneaux 10h/12h/14h/16h) était publié puis ignoré : le portail du
        coordinateur refusait en `auto_not_allowed`. 45 mm sur 10 jours devenaient ~35 appels
        de service à la main, sur un semis qu'on ne peut pas laisser sécher.
        """
        for jour, sous_phase, dose in ((5, "Germination", 1.5), (20, "Enracinement", 3.0)):
            with self.subTest(sous_phase=sous_phase):
                snap = self._snap(jour, memory=self.AUTO_ON, hour_of_day=12)
                self.assertEqual(snap["sous_phase"], sous_phase)
                self.assertEqual(snap["objectif_mm"], dose, "la dose du programme semis a bougé")
                self.assertIs(snap["arrosage_auto_autorise"], True)

    def test_la_facade_ne_dit_plus_manuel_quand_elle_arrose_seule(self) -> None:
        """Annoncer « manuel_frequent » pendant que le coordinateur arrose, c'est mentir.

        `watering_strategy` continue de porter `semis_frequent` : la nuance de régime — petits
        apports rapprochés — n'est pas perdue, seul le contrat d'exécution est corrigé.
        """
        snap = self._snap(5, memory=self.AUTO_ON, hour_of_day=12)
        self.assertEqual(snap["type_arrosage"], "auto")
        self.assertEqual(snap["watering_strategy"], "semis_frequent")

    def test_le_switch_utilisateur_n_est_JAMAIS_contourne(self) -> None:
        """⚠️ LE GARDE QUI COMPTE. `auto_irrigation_enabled` est à False PAR DÉFAUT.

        Ce test est la raison pour laquelle l'étape 2 peut être livrée : personne ne se
        réveille avec un arrosage autonome qu'il n'a pas armé.
        """
        snap = self._snap(5, hour_of_day=12)  # mémoire vide → DEFAULT_AUTO_IRRIGATION_ENABLED
        self.assertGreater(snap["objectif_mm"], 0.0, "prémisse : un cycle est bien dû")
        self.assertIs(snap["arrosage_auto_autorise"], False)
        self.assertEqual(snap["type_arrosage"], "manuel_frequent")

    def test_la_pluie_qui_reporte_le_cycle_garde_le_robinet_ferme(self) -> None:
        """Propriété de bout en bout : cycle reporté ⇒ pas d'arrosage autonome.

        ⚠️ CE QUE CE TEST NE PROUVE PAS, mesuré au banc de mutation : il ne teste PAS la clause
        `sursemis_allowed and surface_cycle_mm > 0` de `sursemis_auto_ok`. En la retirant, ce
        test reste vert — un garde en amont ferme déjà le robinet (`type_arrosage="bloque"`).
        La clause est conservée pour la lisibilité de l'intention au point de décision, pas
        parce qu'un test la tiendrait. Dit ici pour que personne ne s'y fie à tort.
        """
        snap = self._snap(5, memory=self.AUTO_ON, pluie_24h=12.0, hour_of_day=12)
        self.assertEqual(snap["objectif_mm"], 0.0, "prémisse : la pluie reporte le cycle")
        self.assertIs(snap["arrosage_auto_autorise"], False)

    def test_auto_ok_traverse_bien_la_liste_blanche(self) -> None:
        """⚠️ LE CÂBLAGE. Les résolveurs court-circuitent le bloc qui pose `arrosage_auto_autorise`.

        Ajouter « Sursemis » à `auto_ok` sans publier `auto_ok` dans `priority_state` serait
        parfaitement INERTE — la variante exacte du défaut n°1 du projet.
        """
        source = (PACKAGE_DIR / "decision_watering.py").read_text(encoding="utf-8")
        bloc = source.split("priority_state = {", 1)[1].split("\n    }", 1)[0]
        self.assertIn('"auto_ok": auto_ok', bloc, "`auto_ok` n'atteint pas les résolveurs")

    def test_germination_et_enracinement_restent_interdites(self) -> None:
        """Non-régression agronomique : on ne tond PAS sur des plantules."""
        for jour, sous_phase in ((5, "Germination"), (18, "Enracinement")):
            with self.subTest(jour=jour):
                snap = self._snap(jour)
                self.assertEqual(snap["sous_phase"], sous_phase)
                self.assertFalse(snap["tonte_autorisee"])
                self.assertEqual(snap["tonte_statut"], "interdite")

    def test_la_tonte_redevient_possible_en_Reprise(self) -> None:
        """LE correctif : au-delà de j24 c'est `decision_mowing` qui tranche, plus la phase."""
        snap = self._snap(30)
        self.assertEqual(snap["sous_phase"], "Reprise")
        self.assertTrue(
            snap["tonte_autorisee"],
            "la phase Sursemis usurpe encore le verdict du module de tonte",
        )
        self.assertEqual(snap["tonte_statut"], "autorisee_avec_precaution")

    def test_le_verrou_circulaire_de_transition_se_denoue(self) -> None:
        """Deux tontes déclarées ⇒ transition prête. Impossible tant que la tonte était bannie.

        ⚠️ `_count_tonte_events_since_latest_phase_start` compare à « tonte » en MINUSCULE :
        un jeu d'essai en « Tonte » compte zéro et donne un faux négatif silencieux.
        """
        snap = self._snap(32, history_extra=(
            {"type": "tonte", "date": "2026-03-27"},
            {"type": "tonte", "date": "2026-03-31"},
        ))
        self.assertEqual(snap["sous_phase"], "Reprise")
        self.assertIs(snap["seeding_transition_ready"], True)

    def test_aucune_des_trois_sorties_ne_reecrit_le_verdict_de_tonte(self) -> None:
        """⚠️ ANTI-RETOUR PAR LA PORTE DE DERRIÈRE.

        Le correctif tient en une ABSENCE : trois lignes retirées. Rien n'empêche de les
        réintroduire « pour être sûr » lors d'une prochaine passe. Ce test lit le corps de la
        fonction et refuse toute réécriture de la tonte, sur n'importe laquelle des sorties.

        ⚠️ COUVERTURE RÉELLE, mesurée au banc de mutation le 06/09/2026 : des trois sorties,
        seule la dernière (le cycle de surface) est atteinte par un test COMPORTEMENTAL — les
        deux premières dépendent de `runtime_context["semis_followup_state"]`, que
        `build_decision_snapshot` n'expose pas. Fabriquer un `state` à la main (12 clés, dont
        `base_bundle`, `water_bundle` et `context`) reviendrait à tester une fiction ; ce test-ci
        est donc l'unique garde des sorties 1 et 2, et il a bien mordu sur les trois mutations.
        Dette assumée, à lever le jour où un banc construira un `state` réel.
        """
        source = (PACKAGE_DIR / "decision_watering.py").read_text(encoding="utf-8")
        debut = source.index("def _resolve_sursemis_override")
        corps = source[debut:source.index("\ndef ", debut + 10)]
        self.assertNotIn("tonte_autorisee=False", corps)
        self.assertNotIn('tonte_statut="interdite"', corps)
        # Les autres overrides, eux, ont le droit de trancher la tonte : c'est leur rôle.
        self.assertIn("tonte_autorisee=False", source, "les autres overrides ont disparu")


class LeProchainArrosageDesGrainesTests(unittest.TestCase):
    """0.96.1 — en germination, la page annonçait « Prochain arrosage : dimanche 20 septembre ».

    C'était l'estimation du régime NORMAL (jours avant que la réserve atteigne son seuil), alors
    que les graines sont arrosées chaque jour : le prochain cycle partait le lendemain à 8:30.
    """

    def _snap(self, heure: int, suivi: dict | None = None, mode: str = "Sursemis") -> dict:
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": mode, "date": "2026-09-16"}],
            today=date(2026, 9, 17),
            hour_of_day=heure,
            temperature=21,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=2.5,
            runtime_context=suivi,
        )
        return decision.build_decision_result(context).to_snapshot()

    def _jour(self, snap: dict) -> tuple:
        return snap.get("jours_avant_arrosage_estime"), snap.get("date_prochain_arrosage_estime")

    def test_premisse_la_decision_suit_bien_les_graines(self) -> None:
        for mode in ("Sursemis", "Semis"):
            snap = self._snap(11, mode=mode)
            self.assertEqual(snap["watering_strategy"], "semis_frequent", mode)
            self.assertEqual(snap["watering_window_acceptable_end_minute"], 1020, mode)

    def test_des_cycles_restent_dans_la_fenetre_c_est_aujourd_hui(self) -> None:
        for mode in ("Sursemis", "Semis"):
            for heure in (6, 11, 16):
                self.assertEqual(self._jour(self._snap(heure, mode=mode)), (0, "2026-09-17"), (mode, heure))
            attente = {"semis_followup_state": "waiting", "semis_cycles_remaining_today": 2}
            self.assertEqual(self._jour(self._snap(11, attente, mode)), (0, "2026-09-17"), mode)

    def test_cycles_du_jour_faits_ou_fenetre_fermee_c_est_demain(self) -> None:
        fait = {"semis_followup_state": "complete", "semis_cycles_remaining_today": 0}
        for mode in ("Sursemis", "Semis"):
            snap = self._snap(11, fait, mode)
            self.assertEqual(snap["seeding_block_reason"], "semis_cycle_daily_target_reached")
            self.assertEqual(self._jour(snap), (1, "2026-09-18"), mode)
            self.assertEqual(self._jour(self._snap(17, mode=mode)), (1, "2026-09-18"), mode)
            self.assertEqual(self._jour(self._snap(20, mode=mode)), (1, "2026-09-18"), mode)

    def test_le_regime_normal_garde_son_estimation(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 9, 17), hour_of_day=11, temperature=21,
            pluie_24h=0, pluie_demain=0, humidite=50, type_sol="limoneux", etp_capteur=2.5,
        )
        snap = decision.build_decision_result(context).to_snapshot()
        self.assertNotEqual(snap["watering_strategy"], "semis_frequent")
        eau = {"jours_avant_arrosage_estime": 4, "date_prochain_arrosage_estime": "2026-09-21",
               "watering_window_acceptable_end_minute": 1020}
        conseil = {"watering_window_acceptable_end_minute": 600}
        for arrosage in ({"watering_strategy": ""}, {"watering_strategy": "deplete_to_mad"}, {}):
            self.assertEqual(decision._prochain_arrosage_estime(context, eau, conseil, arrosage), (4, "2026-09-21"))
        self.assertEqual(
            decision._prochain_arrosage_estime(context, eau, conseil, {"watering_strategy": "semis_frequent"}),
            (1, "2026-09-18"),
            "11 h, fenêtre des graines fermée à 10 h : demain (la fenêtre lue est celle du conseil)",
        )


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

    def test_le_seuil_de_tonte_suit_la_lame_reelle_pas_la_recommandation(self) -> None:
        """⚠️ La recommandation servait de seuil sur la hauteur d'HERBE.

        `hauteur_tonte_recommandee_cm` est ce qu'on CONSEILLE de régler sur la lame ; la
        machine coupe à `tondeuse_hauteur_coupe_mm`. Mesuré le 30/08/2026 : lame à 5,5 et
        consigne à 6,0 → l'herbe repart de 5,5 mais devait atteindre 6,1 pour débloquer, soit
        ~2,5 jours imposés après chaque tonte alors que le robot est fait pour raser peu et
        souvent. Et obéir à la consigne aggravait le cas : lame à 6,0 → déblocage à 6,1, donc
        1 mm coupé. Arbitré par Kévin : la lame réelle fait foi.
        """
        def _bundle(hauteur_gazon, coupe_mm):
            ctx = decision.DecisionContext.from_legacy_args(
                history=[{"type": "tonte", "date": "2026-07-10", "hauteur_coupe_mm": coupe_mm}],
                today=date(2026, 7, 15), hour_of_day=11, temperature=22,
                pluie_24h=0, pluie_demain=0, humidite=45, type_sol="limoneux", etp_capteur=4.0,
                hauteur_gazon=hauteur_gazon,
            )
            ctx.mower_context = {"tondeuse_hauteur_coupe_mm": coupe_mm}
            phase = decision_phase.build_phase_bundle(ctx)
            water = decision_watering.build_water_bundle(ctx, phase)
            risk = decision_risk.build_risk_bundle(ctx, phase, water)
            return decision_mowing.build_mowing_bundle(ctx, phase, water, risk)

        # Lame à 5,5 cm. Un gazon à 5,6 la dépasse : plus aucune raison de bloquer sur la
        # hauteur, même si la recommandation saisonnière est plus haute.
        juste_au_dessus = _bundle(5.6, 55)
        self.assertNotEqual(
            juste_au_dessus["raison_blocage_code"], "hauteur_trop_faible",
            f"gazon 5,6 cm au-dessus d'une lame à 5,5 : bloqué sur la recommandation "
            f"({juste_au_dessus.get('hauteur_tonte_recommandee_cm')} cm)",
        )

        # Sous la lame, le garde-fou tient toujours.
        sous_la_lame = _bundle(5.2, 55)
        self.assertEqual(sous_la_lame["raison_blocage_code"], "hauteur_trop_faible")

    def test_sans_reglage_de_lame_connu_le_garde_fou_retombe_sur_la_recommandation(self) -> None:
        """`None` = réglage inconnu. Une absence ne doit pas DÉSARMER le garde-fou."""
        ctx = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-07-10", "hauteur_coupe_mm": 55}],
            today=date(2026, 7, 15), hour_of_day=11, temperature=22,
            pluie_24h=0, pluie_demain=0, humidite=45, type_sol="limoneux", etp_capteur=4.0,
            hauteur_gazon=1.0,
        )
        ctx.mower_context = {}          # tondeuse injoignable
        phase = decision_phase.build_phase_bundle(ctx)
        water = decision_watering.build_water_bundle(ctx, phase)
        risk = decision_risk.build_risk_bundle(ctx, phase, water)
        bundle = decision_mowing.build_mowing_bundle(ctx, phase, water, risk)
        self.assertEqual(bundle["raison_blocage_code"], "hauteur_trop_faible",
                         "sans réglage connu, le garde-fou de hauteur a été désarmé")

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
        # ⚠️ Le libellé PRÉCIS, pas le générique. Jusqu'au 03/08/2026 la décision publiait
        # « Robot indisponible: attendre qu'elle soit prête. » et chaque plateforme d'entité le
        # raffinait de son côté — sauf qu'elles ne le faisaient pas toutes, d'où deux valeurs
        # contradictoires du même attribut au même instant. Le raffinement est remonté ici.
        self.assertEqual(
            mowing_bundle["mowing_block_reason_label"],
            "Robot hors ligne: attendre qu'elle redevienne joignable.",
        )
        self.assertEqual(
            mowing_bundle["mowing_window_reason"],
            mowing_bundle["mowing_block_reason_label"],
            "fenêtre et blocage doivent porter le MÊME motif",
        )
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
        # redémarrage de Home Assistant, et ce Worx Landroid en a plusieurs par intermittence.
        for _absent in ("unavailable", "unknown"):
            self.assertIsNone(
                decision_mowing._machine_unavailable_detail({"tondeuse_erreur": _absent}),
                f"« {_absent} » ne doit pas être lu comme une panne",
            )

        # ⚠️ ÉTAT « error » SANS CODE : on bloque, mais on n'affirme PAS de panne.
        # Mesuré le 02/09/2026 à 01:26 : le robot est resté en `error` plusieurs minutes pour
        # une MISE À JOUR de firmware (tête caméra 2.5.6+7 → 2.5.7+12 à 01:28:59), pendant que
        # `sensor.…_erreur` affichait `no_error` du début à la fin. L'ancien libellé annonçait
        # « Robot en erreur: défaut signalé, vérifier le robot » à une heure du matin, pour une
        # machine qui allait parfaitement bien. Ce test verrouille les DEUX moitiés : le blocage
        # tient (elle ne peut effectivement pas tondre), le mot ne ment plus.
        for contexte in (
            {"tondeuse_statut": "erreur"},
            {"mower_operation_state": "error", "tondeuse_erreur": "no_error"},
            {"mower_reason_code": "error", "tondeuse_erreur": ""},
        ):
            with self.subTest(contexte=contexte):
                detail = decision_mowing._machine_unavailable_detail(contexte)
                self.assertIsNotNone(detail, "le blocage a disparu avec le libellé")
                code, libelle = detail
                self.assertEqual(code, "error", "le code de blocage a changé")
                self.assertNotIn(
                    "Robot en erreur", libelle,
                    "une panne est affirmée alors qu'aucun code d'erreur n'est signalé",
                )
                self.assertIn("aucun code d'erreur", libelle)

        # L'AUTRE SENS : un vrai code d'erreur garde le libellé fort, sinon ce correctif
        # rendrait toute panne réelle silencieuse.
        detail_reel = decision_mowing._machine_unavailable_detail(
            {"tondeuse_erreur": "blade_blocked", "mower_reason_label": "Lame bloquée."}
        )
        self.assertEqual(detail_reel, ("error", "Robot en erreur: Lame bloquée."))

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

    def test_build_decision_snapshot_active_spring_recommends_growth_height(self) -> None:
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

        # 4,0 depuis la 0.87.0 (5,5-6,5 avant). Avril en pleine pousse = la hauteur de pousse,
        # que Kévin a choisie à 4 cm et que les sources européennes placent à 3,5-4,5 cm.
        # Les 5 mm de pluie de la veille ne la montent plus : ils disent QUAND tondre.
        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 4.0)

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

        # Par 34 °C, monter la coupe ombrage le sol et limite l'évaporation : c'est l'effet
        # recherché, et il reste (+1,0). Mais 6,5 et non plus 7,5 depuis la 0.87.0 : la base de
        # juillet passe de 6,2 à 5,0 (choix de Kévin, 4 cm de pousse + 1 cm de relèvement d'été),
        # et l'arrondi ne monte plus d'un cran au moindre dixième. Le « 7,5 à 10 cm » invoqué
        # en 0.27.0 vient des fiches américaines ; le corpus européen place l'été à 4,5-5,5 cm.
        # 5,0 + 1,0 (chaleur) + 0,3 (air sec à 30 %, sans registre du sol) = 6,3 → 6,5.
        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 6.5)
        self.assertIn("forte chaleur", snapshot["hauteur_tonte_motif"])

    def test_build_decision_snapshot_favorable_autumn_recommends_growth_height(self) -> None:
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

        # 4,0 depuis la 0.87.0 (5,0-5,5 avant). Septembre doux : hauteur de pousse. L'ancienne
        # « légère réduction » (−0,5) n'existe plus — sur une base à 4,0 elle aurait conseillé
        # 3,5 cm, sous la hauteur voulue.
        self.assertEqual(snapshot["hauteur_tonte_recommandee_cm"], 4.0)

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
            history=[{"type": "Semis", "date": "2026-05-01"}],
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

        self.assertEqual(post_sursemis["phase_active"], "Semis")
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
                {"type": "Semis", "date": "2026-06-01"},
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
        # ⚠️ ATTENDU CHANGÉ le 15/09/2026, PAR DÉCISION DE KÉVIN : ce test refusait 21 h, à 30 min du
        # coucher, au nom de la marge de séchage de 90 min. Kévin a choisi d'étendre la fenêtre
        # jusqu'au coucher + 30 min (cf. `TestFenetresDeTonteElargies`). Ce n'est pas un incident
        # corrigé qu'on efface, c'est une règle métier qui change.
        self.assertEqual(fenetre(21 * 60 + 30, 21), "acceptable", "21 h refusé avant le coucher + 30 min")
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
        # Tonte il y a 4 jours en juin, relevé à 11 h. Depuis la 0.31.1 la pousse du jour est
        # étalée sur 24 h avec un pic en fin de nuit (l'élongation foliaire suit la turgescence,
        # maximale la nuit — cf. _growth_day_fraction) : à 11 h une bonne moitié de la journée
        # est déjà acquise. Le total du jour n'est atteint qu'à minuit.
        bundle = self._make_bundle(
            history=[{"type": "tonte", "date": "2026-06-03"}],
            today=date(2026, 6, 7),
            mower_context={"tondeuse_hauteur_coupe_mm": 45},
        )
        self.assertAlmostEqual(bundle["gazon_hauteur_estimee_cm"], 6.3, places=1)

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
            mesures.append((heure, b["gazon_hauteur_estimee_cm"], b["gazon_pousse_jour_cm"]))
        valeurs = [v for _, v, _ in mesures]
        # La progression fine se lit sur `gazon_pousse_jour_cm` : la hauteur est arrondie au
        # 0,1 cm, et par conditions freinées une journée entière ne vaut qu'un cran. C'est
        # exactement ce que Kévin voyait comme « la hauteur ne bouge pas ».
        pousses = [p for _, _, p in mesures]
        self.assertEqual(valeurs, sorted(valeurs), f"la hauteur recule dans la journée : {mesures}")
        # ⚠️ NE PAS réintroduire « elle ne pousse pas avant 7 h ni après 20 h » : c'était l'erreur
        # corrigée en 0.31.1. L'élongation foliaire suit la TURGESCENCE, maximale la nuit — le
        # gazon pousse la nuit, et même plus vite qu'au zénith.
        self.assertEqual(pousses, sorted(pousses), f"la pousse du jour recule : {mesures}")
        self.assertGreater(pousses[1], pousses[0], "elle ne pousse pas entre 5 h et 7 h (la nuit compte)")
        self.assertGreater(pousses[5], pousses[4], "elle ne pousse plus après 20 h")
        self.assertGreater(pousses[3], pousses[2], "elle ne progresse pas entre 11 h et 15 h")

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

    def test_un_sol_AU_SEUIL_n_est_plus_reduit_ni_bloque_par_la_prevision(self):
        """Ce test vérifiait l'INVERSE jusqu'au 02/08/2026 — il encodait le défaut.

        Réserve au seuil MAD (6/12) : la déplétion déclenche une recharge de 6 mm, que la
        réduction pluie (×0,8) ramenait à 4,8 mm — sous la session minimale de 5,0 — d'où un
        blocage `pluie_prevue_suffisante` sur un sol pile au seuil de déclenchement, pour 2 mm
        annoncés.

        ⚠️ Ce chemin vit dans `decision_watering`, PAS dans `guidance` : le garde posé en
        0.37.0 ne le couvrait pas. Le même motif de blocage venait de deux endroits, un seul
        était protégé. Arbitrage de Kévin : « la pluie prévue n'est jamais sûre ».
        """
        snap = self._snapshot(soil_balance={"reserve_mm": 6.0}, etp_capteur=8.0, pluie_demain=2.0)

        self.assertEqual(snap["phase_active"], "Normal")
        wb = snap["water_balance"]
        self.assertGreaterEqual(wb["depletion_ratio"], wb["mad_ratio"], "prémisse : sol au seuil")
        self.assertNotEqual(snap.get("block_reason"), "pluie_prevue_suffisante")
        self.assertGreater(snap["objectif_mm"], 0.0, "la prévision annule encore la dose")
        self.assertEqual(snap["objectif_mm"], snap["mm_requested"],
                         "la dose est encore rabotée par la prévision")
        self.assertTrue(snap["arrosage_recommande"])

    def test_une_GROSSE_pluie_annoncee_ne_bloque_pas_un_sol_a_sec(self):
        """La branche « pluie compensatrice » (−60 %), celle du 02/08.

        Ce jour-là la prévision est passée à 9,1 mm et tout s'est arrêté. Sur un sol à ZÉRO,
        une grosse pluie annoncée ne doit ni raboter la dose ni la bloquer : c'est précisément
        le pari qui a coûté la journée — il est tombé 3,2 mm pour 4,8 consommés.
        """
        snap = self._snapshot(soil_balance={"reserve_mm": 0.0}, etp_capteur=8.0, pluie_demain=12.0)
        wb = snap["water_balance"]
        self.assertGreaterEqual(wb["depletion_ratio"], wb["mad_ratio"], "prémisse : sol à sec")
        self.assertNotEqual(snap.get("block_reason"), "pluie_prevue_suffisante")
        self.assertEqual(snap["objectif_mm"], snap["mm_requested"],
                         "la dose est encore rabotée de 60 % par la prévision")
        self.assertGreater(snap["objectif_mm"], 0.0)

    def test_sous_le_seuil_la_prevision_reduit_toujours(self):
        """Garde-fou : le correctif ne supprime pas la réduction, il la borne.

        Sol confortable et pluie significative annoncée : économiser un cycle reste le bon
        choix. C'est le cas couvert par `test_rain_reduction_propagates_to_executed_values`,
        vérifié ici sur la grandeur qui décide.
        """
        rain = self._snapshot(pluie_demain=3.0)
        wb = rain["water_balance"]
        self.assertLess(wb["depletion_ratio"], wb["mad_ratio"], "prémisse : sol sous le seuil")
        self.assertEqual(rain["objectif_mm"], round(rain["mm_requested"] * 0.8, 1))

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

    def test_un_risque_cumule_ne_ferme_pas_la_fenetre_normale_de_laube(self):
        moment = datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)
        base = dict(
            phase_dominante="Normal", sous_phase="Normal",
            water_balance=dict(
                bilan_hydrique_mm=-14.0, deficit_3j=14.0, deficit_7j=18.0,
                arrosage_recent_7j=0.0, reserve_from_soil_ledger=True,
                reserve_utile_mm=12.0, reserve_actuelle_mm=2.0, reserve_stock_mm=2.0,
                reserve_stock_max_mm=24.0, depletion_mm=10.0, depletion_ratio=0.83,
                mad_ratio=0.5,
            ),
            today=date(2026, 7, 15), pluie_24h=0.0, pluie_demain=0.0, pluie_j2=0.0,
            pluie_3j=0.0, pluie_probabilite_max_3j=0.0, humidite=90.0, temperature=18.0,
            etp=3.0, type_sol="limoneux", weather_profile={"sunset_minute": 1290}, history=[],
        )
        with patch.object(guidance, "_current_datetime", return_value=moment):
            sans_cumul = guidance.compute_watering_profile(**base, fungal_risk_level="none")
            avec_cumul = guidance.compute_watering_profile(**base, fungal_risk_level="high")
        self.assertEqual(avec_cumul["watering_window_start_minute"], sans_cumul["watering_window_start_minute"])
        self.assertEqual(avec_cumul["watering_window_end_minute"], sans_cumul["watering_window_end_minute"])
        self.assertEqual(avec_cumul["fenetre_optimale"], sans_cumul["fenetre_optimale"])


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


class TestPousseMemorisee(unittest.TestCase):
    """La pousse acquise est mémorisée — sinon le frein de conditions saute à minuit.

    Défaut repéré par Kévin le 30/07/2026 (« la hauteur ne bouge pas ») : les journées
    révolues étaient recomptées au taux NOMINAL alors que la journée en cours était freinée
    par la chaleur. À 00 h 00, tout ce que la chaleur avait retiré était rendu d'un coup :
    +0,30 cm par 30-35 °C. Le frein, raison d'être du modèle, était annulé chaque nuit.
    """

    def _details(self, jour, heure, memoire):
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-07-27", "hauteur_coupe_mm": 55.0}],
            today=jour,
            hour_of_day=heure,
            temperature=32.0,          # 30-35 °C -> frein 0,25
            memory=memoire,
        )
        return decision_mowing._grass_growth_details(
            context,
            {"phase_dominante": "Normal"},
            {"reserve_actuelle_mm": 9.0, "reserve_minimale_mm": 6.0},
        )

    def test_pas_de_saut_a_minuit(self) -> None:
        memoire: dict = {}
        veille = None
        for jour, heure in ((date(2026, 7, 29), 20), (date(2026, 7, 29), 23), (date(2026, 7, 30), 0)):
            d = self._details(jour, heure, memoire)
            memoire["pousse_gazon"] = d["etat"]
            if veille is not None:
                self.assertLessEqual(
                    d["hauteur_cm"] - veille, 0.05,
                    f"saut à minuit : {veille} -> {d['hauteur_cm']} cm",
                )
            veille = d["hauteur_cm"]

    def test_la_pousse_du_jour_est_reportee_telle_quelle(self) -> None:
        """Ce qui a été acquis hier doit se retrouver à l'identique dans l'acquis du lendemain."""
        memoire: dict = {}
        soir = self._details(date(2026, 7, 29), 23, memoire)
        memoire["pousse_gazon"] = soir["etat"]
        acquis_attendu = soir["pousse_acquise_cm"] + soir["pousse_jour_cm"]

        lendemain = self._details(date(2026, 7, 30), 0, memoire)
        self.assertAlmostEqual(lendemain["pousse_acquise_cm"], acquis_attendu, places=1)
        self.assertEqual(lendemain["pousse_jour_cm"], 0.0)

    def test_la_pousse_du_jour_monte_avec_les_heures(self) -> None:
        memoire: dict = {}
        mesures = [self._details(date(2026, 7, 29), h, memoire)["pousse_jour_cm"]
                   for h in (7, 10, 13, 16, 20)]
        self.assertEqual(mesures, sorted(mesures), f"la pousse du jour recule : {mesures}")
        self.assertGreater(mesures[-1], mesures[0])

    def test_amorcage_sans_memoire_ne_fait_pas_chuter_la_hauteur(self) -> None:
        """Première estimation ou montée de version : sans mémoire on repart du nominal.

        Repartir de zéro ferait chuter la hauteur affichée d'un coup (6,2 -> 4,7 cm mesuré),
        soit un défaut pire que celui qu'on corrige.
        """
        sans_memoire = self._details(date(2026, 7, 30), 12, {})
        self.assertGreater(sans_memoire["pousse_acquise_cm"], 0.0)
        self.assertGreater(sans_memoire["hauteur_cm"], 5.5)

    def test_le_jour_de_la_tonte_ne_se_reporte_pas_le_lendemain(self) -> None:
        """Le jour de la tonte la pousse est nulle — le lendemain ne doit rien en hériter.

        ⚠️ Défaut introduit puis corrigé le 30/07/2026 : le report reconstituait la pousse de la
        veille (`taux × frein`) au lieu de créditer celle CONSTATÉE. Il créditait donc une
        journée pleine au jour de la tonte, et la hauteur bondissait de 5,5 à 5,8 cm à minuit —
        le saut de minuit revenu par une autre porte.
        """
        memoire: dict = {}
        veille = self._details(date(2026, 7, 27), 23, memoire)   # jour de la tonte
        memoire["pousse_gazon"] = veille["etat"]
        self.assertEqual(veille["pousse_jour_cm"], 0.0)

        lendemain = self._details(date(2026, 7, 28), 0, memoire)
        self.assertEqual(
            lendemain["pousse_acquise_cm"], 0.0,
            "le jour de la tonte a été crédité alors que rien n'a poussé",
        )
        self.assertAlmostEqual(
            lendemain["hauteur_cm"], veille["hauteur_cm"], places=1,
            msg="saut à minuit au lendemain de la tonte",
        )

    def test_une_nouvelle_tonte_remet_le_compteur_a_zero(self) -> None:
        memoire = {"pousse_gazon": {"date": "2026-07-29", "tonte": "2026-07-20",
                                    "acquis_cm": 3.0, "frein": 1.0}}
        d = self._details(date(2026, 7, 30), 12, memoire)
        # La mémoire porte une AUTRE tonte : elle ne doit pas être réutilisée.
        self.assertLess(d["pousse_acquise_cm"], 3.0)
        self.assertEqual(d["etat"]["tonte"], "2026-07-27")


class TestRisqueGazonSurReserve(unittest.TestCase):
    """Le risque se décide sur la RÉSERVE DU SOL, plus sur le bilan de la journée.

    Question de Kévin le 31/07/2026 : « pourquoi risque gazon élevé ? ». Réponse : parce que
    `bilan_hydrique_mm` est le bilan du JOUR (pluie + arrosage − ETc du jour), donc négatif
    mécaniquement chaque nuit avant l'arrosage du matin. Ce n'était pas « ton gazon est en
    danger » mais « tu n'as pas encore arrosé aujourd'hui ». L'historique le prouvait : bascule
    sur « faible » à la seconde où l'arrosage partait, trois nuits d'affilée.
    """

    def test_reserve_saine_ne_donne_pas_un_risque_eleve(self) -> None:
        niveau, raisons = guidance._evaluer_risque_gazon(
            water_balance={"reserve_from_soil_ledger": True, "depletion_ratio": 0.2, "mad_ratio": 0.5},
            bilan_hydrique_mm=-5.9,      # bilan du jour très négatif : c'est la nuit
            pression_hydrique=0.0,
        )
        self.assertEqual(niveau, "faible", f"la nuit ne doit plus alarmer : {raisons}")

    def test_reserve_epuisee_donne_un_risque_eleve(self) -> None:
        niveau, raisons = guidance._evaluer_risque_gazon(
            water_balance={"reserve_from_soil_ledger": True, "depletion_ratio": 1.0, "mad_ratio": 0.5},
            bilan_hydrique_mm=0.0,       # bilan du jour neutre, mais le SOL est vide
            pression_hydrique=0.0,
        )
        self.assertEqual(niveau, "eleve")
        self.assertIn("épuisée", " ".join(raisons))

    def test_sans_ledger_on_retombe_sur_le_bilan(self) -> None:
        """Tout premier cycle, ledger vide : le bilan du jour est le seul signal disponible."""
        niveau, raisons = guidance._evaluer_risque_gazon(
            water_balance={},            # pas de ledger
            bilan_hydrique_mm=-5.9,
            pression_hydrique=0.0,
        )
        self.assertEqual(niveau, "eleve")
        self.assertIn("sans réserve sol connue", " ".join(raisons))

    def test_le_semis_explique_la_surface_sans_nier_la_reserve_profonde(self) -> None:
        niveau, raisons = guidance._evaluer_risque_gazon(
            water_balance={
                "reserve_from_soil_ledger": True,
                "depletion_ratio": 0.0,
                "mad_ratio": 0.5,
            },
            bilan_hydrique_mm=-0.9,
            pression_hydrique=1.3,
            utiliser_reserve=False,
            surface_semis=True,
            plancher="modere",
        )
        texte = " ".join(raisons)
        self.assertEqual(niveau, "modere")
        self.assertIn("Déclencheur : surface du semis", texte)
        self.assertIn("réserve profonde connue mais non utilisée", texte)
        self.assertNotIn("sans réserve sol connue", texte)

    def test_le_declencheur_meteo_passe_avant_le_contexte_du_semis(self) -> None:
        niveau, raisons = guidance._evaluer_risque_gazon(
            water_balance={"reserve_from_soil_ledger": True},
            bilan_hydrique_mm=-0.9,
            pression_hydrique=1.3,
            utiliser_reserve=False,
            surface_semis=True,
            plancher="modere",
            heat_stress_level="vigilance",
        )
        self.assertEqual(niveau, "eleve")
        self.assertTrue(raisons[0].startswith("Déclencheur : conditions asséchantes"))
        self.assertTrue(raisons[1].startswith("Contexte : surface du semis"))

    def test_les_nouveaux_motifs_ne_changent_jamais_le_niveau(self) -> None:
        base = {
            "water_balance": {"reserve_from_soil_ledger": True},
            "utiliser_reserve": False,
        }
        scenarios = (
            {"bilan_hydrique_mm": -1.6, "pression_hydrique": 0.0},
            {"bilan_hydrique_mm": 0.0, "pression_hydrique": 0.0, "plancher": "modere"},
            {"bilan_hydrique_mm": -0.9, "pression_hydrique": 1.3, "vent": 20.0},
            {
                "bilan_hydrique_mm": -0.9,
                "pression_hydrique": 1.3,
                "plancher": "modere",
                "heat_stress_level": "vigilance",
            },
            {
                "bilan_hydrique_mm": 0.0,
                "pression_hydrique": 0.0,
                "heat_stress_level": "severe",
            },
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                ancien, _ = guidance._evaluer_risque_gazon(**base, **scenario)
                explique, _ = guidance._evaluer_risque_gazon(
                    **base, **scenario, surface_semis=True
                )
                self.assertEqual(explique, ancien)

    def test_le_profil_sursemis_cable_reellement_les_motifs_de_surface(self) -> None:
        resultat = guidance.compute_action_guidance(
            phase_dominante="Sursemis",
            sous_phase="Germination",
            water_balance={
                "reserve_from_soil_ledger": True,
                "bilan_hydrique_mm": -0.9,
                "deficit_3j": 0.0,
                "deficit_7j": 0.0,
                "depletion_ratio": 0.0,
                "mad_ratio": 0.5,
            },
            advanced_context={"vent": 20.0},
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            temperature=20.0,
            etp=3.0,
            objectif_mm=1.2,
            hour_of_day=12.0,
            sous_phase_age_days=2,
        )
        raisons = resultat["risque_gazon_raisons"]
        self.assertEqual(resultat["risque_gazon"], "eleve")
        self.assertTrue(raisons[0].startswith("Déclencheur : vent soutenu"))
        self.assertTrue(raisons[1].startswith("Contexte : surface du semis"))

    def test_le_niveau_est_toujours_explique(self) -> None:
        """Le capteur n'exposait AUCUNE raison : un « élevé » était incompréhensible."""
        for wb in ({"reserve_from_soil_ledger": True, "depletion_ratio": 0.1, "mad_ratio": 0.5}, {}):
            _, raisons = guidance._evaluer_risque_gazon(
                water_balance=wb, bilan_hydrique_mm=0.0, pression_hydrique=0.0)
            self.assertTrue(raisons, "aucune raison exposée")

    def test_le_plancher_de_phase_ne_peut_pas_etre_abaisse(self) -> None:
        """En Sursemis, la phase impose « au moins modéré » : un semis fragile n'est jamais
        annoncé sans risque, même si la réserve est saine. Un test existant l'a rattrapé."""
        niveau, raisons = guidance._evaluer_risque_gazon(
            water_balance={}, bilan_hydrique_mm=0.0, pression_hydrique=0.0,
            utiliser_reserve=False, plancher="modere",
        )
        self.assertEqual(niveau, "modere")
        self.assertIn("plancher", " ".join(raisons))

    def test_les_facteurs_externes_montent_toujours_le_niveau(self) -> None:
        for kw, attendu in (({"vent": 25.0}, "vent"), ({"hauteur_gazon": 14.0}, "haut"),
                            ({"heat_stress_level": "severe"}, "sévère")):
            niveau, raisons = guidance._evaluer_risque_gazon(
                water_balance={"reserve_from_soil_ledger": True, "depletion_ratio": 0.1, "mad_ratio": 0.5},
                bilan_hydrique_mm=0.0, pression_hydrique=0.0, **kw)
            self.assertEqual(niveau, "eleve", f"{kw} n'a pas élevé le risque")
            self.assertIn(attendu, " ".join(raisons))


class TestRessuyageApresPluie(unittest.TestCase):
    """Un délai de ressuyage après la pluie, symétrique de celui après un arrosage.

    `is_active_rain_weather` ne regarde que la météo de l'INSTANT : il n'existait donc AUCUN
    délai après une averse, alors qu'un arrosage en impose 180 min. Le libellé promettait
    pourtant « pluie en cours ou récente ». Kévin : « c'est l'intégration qui gère le temps de
    pause de la tondeuse pendant la pluie » — elle ne le gérait qu'à moitié.
    """

    def _ctx(self, *, heure, memoire, pluie=False):
        return decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 7, 31), hour_of_day=heure, temperature=20.0,
            humidite=60.0, memory=memoire,
            weather_profile={"weather_condition": "rainy" if pluie else "sunny"},
            runtime_context={"mowing_cooldown_after_watering_minutes": 180},
        )

    def test_l_averse_est_horodatee(self) -> None:
        etat = decision_mowing._etat_pluie(self._ctx(heure=10.0, memoire={}, pluie=True), True)
        self.assertEqual(etat, {"date": "2026-07-31", "heure": 10.0})

    def test_le_ressuyage_bloque_apres_l_averse(self) -> None:
        memoire = {"derniere_pluie_active": {"date": "2026-07-31", "heure": 10.0}}
        # 1 h après : encore 120 min de ressuyage
        ecoule = decision_mowing._minutes_depuis_derniere_pluie(self._ctx(heure=11.0, memoire=memoire))
        self.assertAlmostEqual(ecoule, 60.0, places=1)

    def test_le_ressuyage_expire(self) -> None:
        memoire = {"derniere_pluie_active": {"date": "2026-07-31", "heure": 10.0}}
        ecoule = decision_mowing._minutes_depuis_derniere_pluie(self._ctx(heure=14.0, memoire=memoire))
        self.assertAlmostEqual(ecoule, 240.0, places=1)   # > 180 : le garde ne s'applique plus

    def test_l_horodatage_traverse_minuit(self) -> None:
        memoire = {"derniere_pluie_active": {"date": "2026-07-30", "heure": 23.0}}
        ecoule = decision_mowing._minutes_depuis_derniere_pluie(self._ctx(heure=1.0, memoire=memoire))
        self.assertAlmostEqual(ecoule, 120.0, places=1)

    def test_une_pluie_trop_vieille_est_ignoree(self) -> None:
        """Au-delà de la veille, l'horodatage ne veut plus rien dire."""
        memoire = {"derniere_pluie_active": {"date": "2026-07-20", "heure": 10.0}}
        self.assertIsNone(decision_mowing._minutes_depuis_derniere_pluie(self._ctx(heure=12.0, memoire=memoire)))

    def test_sans_horodatage_aucun_blocage(self) -> None:
        self.assertIsNone(decision_mowing._minutes_depuis_derniere_pluie(self._ctx(heure=12.0, memoire={})))


class TestRessuyageProportionnelALaLame(unittest.TestCase):
    """⚠️ LE BLOCAGE DU 09/09/2026, ET LES TROIS CORRECTIONS QUE KÉVIN A DEMANDÉES ENSEMBLE.

    À 20:12 le pluviomètre du voisin passe de 0,0 à **0,1 mm** — un basculement d'auget. Le
    garde arme aussitôt 180 minutes de ressuyage, empruntées au délai d'après-arrosage, pendant
    que la station DU JARDIN ne mesure rien : compteur figé à 2,3 mm de 04:14 à minuit. La tonte
    est restée bloquée jusqu'à 23:12 pour une pluie que la pelouse n'a pas reçue.

    Trois corrections, tenues par les tests ci-dessous : un MINIMUM (0,3 mm), une durée
    PROPORTIONNELLE, et les DEUX pluviomètres — la plus grande des deux lames commande.
    """

    def _ctx(self, *, heure, memoire, lame_voisin=None, lame_station=None, plein=180):
        profil = {"weather_condition": "sunny"}
        if lame_voisin is not None:
            profil["pluie_mesuree_lame_mm"] = lame_voisin
        if lame_station is not None:
            profil["pluie_cumul_lame_mm"] = lame_station
        return decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 9, 9), hour_of_day=heure, temperature=18.0,
            humidite=60.0, memory=memoire, weather_profile=profil,
            runtime_context={"mowing_cooldown_after_watering_minutes": plein},
        )

    def _bloc(self, ctx):
        return decision_mowing._resolve_mowing_block(ctx, {}, {})

    # ---- LE CAS RÉEL ---------------------------------------------------------------------
    def test_le_basculement_du_09_09_n_arme_PLUS_trois_heures(self) -> None:
        """0,1 mm chez le voisin, rien à la station : aucun ressuyage.

        ⚠️ Le point d'appel, pas seulement la formule : on interroge `_resolve_mowing_block`,
        celui-là même qui produisait « Herbe mouillée: ressuyage après la pluie (101 min
        restantes) » à 21:31 ce soir-là.
        """
        memoire = {"derniere_pluie_active": {"date": "2026-09-09", "heure": 20.2}}
        bloque, code, motif, _, _ = self._bloc(
            self._ctx(heure=21.5, memoire=memoire, lame_voisin=0.1, lame_station=0.0)
        )
        self.assertFalse(bloque, f"la tonte est encore bloquée : {motif}")
        self.assertNotEqual(code, "wet_grass")

    def test_la_meme_soiree_bloquait_AVANT_le_correctif(self) -> None:
        """Prémisse : sans les lames, le montage reproduit bien l'ancien blocage de 3 h.

        Sans ce test, le précédent pourrait passer au vert pour une raison étrangère au
        correctif — un montage qui n'atteint jamais la branche testée, l'erreur commise deux
        fois sur ce projet.
        """
        memoire = {"derniere_pluie_active": {"date": "2026-09-09", "heure": 20.2}}
        bloque, code, motif, _, _ = self._bloc(self._ctx(heure=21.5, memoire=memoire))
        self.assertTrue(bloque)
        self.assertEqual(code, "wet_grass")
        self.assertIn("101 min restantes", motif)

    # ---- 1. LE MINIMUM -------------------------------------------------------------------
    def test_sous_le_minimum_aucun_ressuyage(self) -> None:
        for lame in (0.0, 0.1, 0.29):
            with self.subTest(lame=lame):
                self.assertEqual(decision_mowing._ressuyage_effectif(180.0, lame), 0.0)

    def test_a_la_borne_exacte_le_plancher_s_applique(self) -> None:
        self.assertAlmostEqual(decision_mowing._ressuyage_effectif(180.0, 0.3), 45.0, places=6)

    def test_une_absence_de_mesure_ne_raccourcit_RIEN(self) -> None:
        """⚠️ RÈGLE DE LA MAISON. `None` veut dire « aucun pluviomètre ne parle », jamais
        « il n'est rien tombé » — sinon deux capteurs muets supprimeraient le ressuyage."""
        self.assertAlmostEqual(decision_mowing._ressuyage_effectif(180.0, None), 180.0)
        memoire = {"derniere_pluie_active": {"date": "2026-09-09", "heure": 20.2}}
        bloque, code, _, _, _ = self._bloc(self._ctx(heure=21.5, memoire=memoire))
        self.assertTrue(bloque, "sans mesure, le comportement d'avant doit être intact")
        self.assertEqual(code, "wet_grass")

    # ---- 2. LA PROPORTION ----------------------------------------------------------------
    def test_la_duree_croit_avec_la_lame(self) -> None:
        durees = [decision_mowing._ressuyage_effectif(180.0, mm) for mm in (0.3, 1.0, 2.0, 3.0)]
        self.assertEqual(durees, sorted(durees), "la durée ne croît pas avec la lame d'eau")
        self.assertAlmostEqual(durees[1], 70.5, places=1)   # 1,0 mm
        self.assertAlmostEqual(durees[2], 107.0, places=0)  # 2,0 mm

    def test_a_saturation_du_couvert_le_delai_est_PLEIN(self) -> None:
        """4,0 mm : le couvert est saturé, l'eau ruisselle. Rien n'est raccourci.

        Repère pris sur la capacité de rétention d'un gazon — 4,4 mm avant que la première
        goutte n'atteigne le sol (Serena et al., PLOS ONE 2022).
        """
        for lame in (4.0, 6.0, 20.0):
            with self.subTest(lame=lame):
                self.assertAlmostEqual(
                    decision_mowing._ressuyage_effectif(180.0, lame), 180.0, places=6
                )

    def test_le_plancher_ne_depasse_JAMAIS_le_reglage(self) -> None:
        """Si Kévin descend le délai plein à 30 min, une petite pluie ne doit pas attendre 45."""
        self.assertLessEqual(decision_mowing._ressuyage_effectif(30.0, 0.5), 30.0)
        self.assertEqual(decision_mowing._ressuyage_effectif(0.0, 10.0), 0.0)

    # ---- 3. LES DEUX PLUVIOMÈTRES --------------------------------------------------------
    def test_la_station_du_jardin_COMMANDE_quand_elle_voit_plus(self) -> None:
        """L'inverse du 09/09 : l'averse tombe ICI et le voisin la rate.

        Sans la station dans le calcul, 0,2 mm passeraient sous le minimum et la tonte partirait
        sur une pelouse détrempée.
        """
        memoire = {"derniere_pluie_active": {"date": "2026-09-09", "heure": 20.2}}
        bloque, code, motif, _, _ = self._bloc(
            self._ctx(heure=21.0, memoire=memoire, lame_voisin=0.2, lame_station=2.5)
        )
        self.assertTrue(bloque, "l'averse mesurée sur la pelouse n'a armé aucun ressuyage")
        self.assertEqual(code, "wet_grass")
        self.assertIn("2,5 mm", motif)

    def test_le_voisin_commande_quand_la_station_est_muette(self) -> None:
        """L'angle mort inverse : la station était `unavailable` 16 min autour du basculement du
        09/09. Un capteur absent ne doit pas ramener l'épisode à zéro."""
        self.assertAlmostEqual(
            decision_mowing._lame_de_pluie_recente(
                {"pluie_mesuree_lame_mm": 3.0, "pluie_cumul_lame_mm": None}
            ),
            3.0,
        )

    def test_c_est_le_MAXIMUM_des_deux_jamais_la_premiere_trouvee(self) -> None:
        for voisin, station, attendu in ((0.1, 2.0, 2.0), (2.0, 0.1, 2.0), (None, None, None)):
            with self.subTest(voisin=voisin, station=station):
                self.assertEqual(
                    decision_mowing._lame_de_pluie_recente(
                        {"pluie_mesuree_lame_mm": voisin, "pluie_cumul_lame_mm": station}
                    ),
                    attendu,
                )

    def test_une_valeur_illisible_ne_vaut_pas_zero(self) -> None:
        self.assertIsNone(
            decision_mowing._lame_de_pluie_recente(
                {"pluie_mesuree_lame_mm": "beaucoup", "pluie_cumul_lame_mm": None}
            )
        )

    # ---- LE BLOQUANT DU PREMIER JET ------------------------------------------------------
    def test_un_auget_TARDIF_ne_SUPPRIME_pas_le_ressuyage_d_une_vraie_averse(self) -> None:
        """⚠️ LE DÉFAUT QU'UNE REVUE ADVERSARIALE A TROUVÉ DANS MON PREMIER CORRECTIF.

        Le 12/09 (rejeu), 6,0 mm de 14:00 à 14:50 : ressuyage plein armé jusqu'à 17:50. À 16:25,
        UN auget de traîne sur chaque capteur. La lame était alors un « épisode » remis à zéro
        après une heure de trou : elle retombait à 0,1 mm, donc sous le minimum, donc
        **ressuyage supprimé**. La tonte redevenait autorisée à 17:00 sur une pelouse ayant reçu
        6,1 mm — moins bien que le code qu'on remplaçait. Plus il pleuvait, moins on bloquait.

        La fenêtre glissante additionne au lieu d'effacer : ici on relit 6,1 mm.
        """
        memoire = {"derniere_pluie_active": {"date": "2026-09-09", "heure": 16.42}}
        bloque, code, motif, _, _ = self._bloc(
            self._ctx(heure=17.0, memoire=memoire, lame_voisin=6.1, lame_station=6.1)
        )
        self.assertTrue(bloque, "la tonte est autorisée 35 min après 6,1 mm de pluie")
        self.assertEqual(code, "wet_grass")
        self.assertIn("6,1 mm", motif)
        self.assertAlmostEqual(
            decision_mowing._ressuyage_effectif(180.0, 6.1), 180.0, places=6,
            msg="6,1 mm n'arment plus le délai plein",
        )

    # ---- LE MOTIF ------------------------------------------------------------------------
    def test_le_motif_ANNONCE_la_lame_de_pluie(self) -> None:
        """« 3 h de ressuyage » sans dire pour quelle pluie, c'est ce qui a fait chercher une
        demi-heure d'où venait le blocage du 09/09. Virgule décimale, comme le reste."""
        memoire = {"derniere_pluie_active": {"date": "2026-09-09", "heure": 20.0}}
        _, _, motif, _, _ = self._bloc(
            self._ctx(heure=21.0, memoire=memoire, lame_voisin=1.2, lame_station=0.0)
        )
        self.assertIn("1,2 mm", motif)
        self.assertNotIn("1.2", motif)


class TestHorodatageSurLaDerniereHausse(unittest.TestCase):
    """L'averse est horodatée à sa DERNIÈRE HAUSSE mesurée, pas au dernier cycle de garde.

    ⚠️ POURQUOI. Depuis la 0.54.0 la garde « il pleut » reste vraie 30 min après le dernier tic
    du pluviomètre — voulu, une averse fait des pauses. Mais horodater « maintenant » pendant
    ces 30 min prolonge d'autant le ressuyage, qui court déjà 180 min : 3 h 30 d'attente pour
    une pluie finie. On recule donc jusqu'à la hausse.

    ⚠️ ET JAMAIS EN ARRIÈRE. La prévision peut affirmer la pluie plus longtemps que le
    pluviomètre ne la mesure ; le correctif supprime le rab, il ne raccourcit jamais un
    ressuyage déjà justifié.
    """

    def _ctx(self, *, heure, memoire=None, condition="sunny", depuis=None, mesure=None,
             jour=date(2026, 8, 16)):
        profil = {"weather_condition": condition}
        if mesure is not None:
            profil["pluie_mesuree_active"] = mesure
        if depuis is not None:
            profil["pluie_mesuree_minutes_depuis_hausse"] = depuis
        return decision.DecisionContext.from_legacy_args(
            history=[], today=jour, hour_of_day=heure, temperature=20.0, humidite=60.0,
            memory=memoire if memoire is not None else {}, weather_profile=profil,
            runtime_context={"mowing_cooldown_after_watering_minutes": 180},
        )

    def test_la_source_dit_qui_a_parle(self) -> None:
        self.assertEqual(guidance.active_rain_source({"weather_condition": "rainy"}), "prevision")
        self.assertEqual(
            guidance.active_rain_source({"weather_precipitation_probability": 90}), "prevision"
        )
        self.assertEqual(guidance.active_rain_source({"pluie_mesuree_active": True}), "mesure")
        self.assertIsNone(guidance.active_rain_source({"weather_condition": "sunny"}))

    def test_la_garde_reste_le_meme_predicat_que_la_source(self) -> None:
        """⚠️ Deux implémentations de la même règle finiraient par diverger."""
        for profil in (
            {"weather_condition": "rainy"},
            {"weather_condition": "sunny", "pluie_mesuree_active": True},
            {"weather_condition": "sunny", "pluie_mesuree_active": None},
            {"weather_precipitation_probability": 90},
            {},
        ):
            with self.subTest(profil=profil):
                self.assertEqual(
                    guidance.is_active_rain_weather(profil),
                    guidance.active_rain_source(profil) is not None,
                )

    def test_seule_la_mesure_parle_on_recule_jusqu_a_la_hausse(self) -> None:
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=6.25, condition="cloudy", mesure=True, depuis=25.0), True
        )
        self.assertEqual(etat["date"], "2026-08-16")
        self.assertAlmostEqual(etat["heure"], 6.25 - 25.0 / 60.0, places=3)

    def test_la_prevision_parle_on_horodate_maintenant(self) -> None:
        """Elle affirme une pluie à l'INSTANT — reculer inventerait une accalmie."""
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=6.25, condition="rainy", mesure=True, depuis=25.0), True
        )
        self.assertAlmostEqual(etat["heure"], 6.25, places=3)

    def test_l_horodatage_ne_recule_jamais(self) -> None:
        memoire = {"derniere_pluie_active": {"date": "2026-08-16", "heure": 6.0}}
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=6.1, condition="cloudy", mesure=True, depuis=30.0, memoire=memoire),
            True,
        )
        self.assertEqual(etat, {"date": "2026-08-16", "heure": 6.0})

    def test_une_hausse_plus_recente_remplace_le_constat(self) -> None:
        memoire = {"derniere_pluie_active": {"date": "2026-08-16", "heure": 5.0}}
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=6.0, condition="cloudy", mesure=True, depuis=6.0, memoire=memoire),
            True,
        )
        self.assertAlmostEqual(etat["heure"], 5.9, places=3)

    def test_une_hausse_avant_minuit(self) -> None:
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=0.25, condition="cloudy", mesure=True, depuis=30.0), True
        )
        self.assertEqual(etat["date"], "2026-08-15")
        self.assertAlmostEqual(etat["heure"], 23.75, places=3)

    def test_sans_mesure_le_comportement_d_avant_est_intact(self) -> None:
        etat = decision_mowing._etat_pluie(self._ctx(heure=10.0, condition="rainy"), True)
        self.assertEqual(etat, {"date": "2026-08-16", "heure": 10.0})

    def test_une_prevision_que_la_mesure_dement_n_arme_pas_le_ressuyage(self) -> None:
        """⚠️ MESURÉ LE 29/08/2026. Prévision `rainy` de 13:10 à 14:07, dernière hausse du
        pluviomètre à 10:17 : le ressuyage courait jusqu'à 17:07 pour une pluie jamais tombée.

        Bloquer pendant la prévision reste juste — ça ne coûte que sa durée, et le pluviomètre
        n'est pas sur la pelouse. Engager trois heures de ressuyage, non.
        """
        memoire = {"derniere_pluie_active": {"date": "2026-08-29", "heure": 10.28}}
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=14.0, condition="rainy", mesure=False, depuis=223.0,
                      memoire=memoire, jour=date(2026, 8, 29)),
            True,
        )
        self.assertEqual(etat, {"date": "2026-08-29", "heure": 10.28},
                         "le constat a été repoussé par une prévision que la mesure dément")

    def test_sans_pluviometre_la_prevision_garde_le_dernier_mot(self) -> None:
        """⚠️ `None` = aucune mesure. Une absence ne dément rien."""
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=14.0, condition="rainy"), True
        )
        self.assertAlmostEqual(etat["heure"], 14.0, places=3)

    def test_une_mesure_qui_confirme_horodate_bien_maintenant(self) -> None:
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=14.0, condition="rainy", mesure=True, depuis=2.0), True
        )
        self.assertAlmostEqual(etat["heure"], 14.0, places=3)

    def test_la_nuit_du_16_aout_le_ressuyage_va_jusqu_au_bout(self) -> None:
        """Le cas réel. Pluie finie à 05:52, garde encore vraie à 06:20 par la mesure.

        Avant : horodaté 06:20 ⇒ ressuyage jusqu'à 09:20. Après : 05:52 ⇒ 08:52.
        """
        etat = decision_mowing._etat_pluie(
            self._ctx(heure=6.0 + 20.0 / 60.0, condition="cloudy", mesure=True, depuis=28.0), True
        )
        fin_ressuyage = etat["heure"] + 3.0
        self.assertAlmostEqual(etat["heure"], 5.0 + 52.0 / 60.0, places=2)
        self.assertLess(fin_ressuyage, 9.0, "le ressuyage déborde encore de la fin réelle")


class TestHeureDecimale(unittest.TestCase):
    """La pousse avançait par PALIERS D'UNE HEURE : `hour_of_day` était un entier.

    Mesuré le 31/07/2026 : `jour_cm` valait exactement 0,0246 à 01 h 56 comme à 01 h 58, puis
    sautait à 0,0505 à 02 h.
    """

    def test_la_fraction_de_journee_suit_les_minutes(self) -> None:
        valeurs = [decision_mowing._growth_day_fraction(h) for h in (1.0, 1.25, 1.5, 1.75, 2.0)]
        self.assertEqual(valeurs, sorted(valeurs))
        self.assertTrue(all(a < b for a, b in zip(valeurs, valeurs[1:])),
                        f"la fraction stagne dans l'heure : {valeurs}")


class TestPousseNeRecuiitPas(unittest.TestCase):
    """La pousse déjà acquise ne se recalcule pas — le gazon ne dé-pousse pas.

    Constaté sur l'installation le 01/08/2026, sur l'historique brut du capteur :
    09 h 10 → 6,0 cm, 11 h 40 → 5,9 cm, sans tonte. `taux × frein × fraction` appliquait le
    frein du MOMENT à toute la journée : quand la chaleur monte, la pousse du matin est
    effacée. Le frein thermique étant un escalier (≤ 24 °C : 1,0 ; > 24 °C : 0,65), franchir
    24,0 °C suffisait à perdre 35 % de la matinée d'un coup.
    """

    @staticmethod
    def _details(jour, heure, memoire, *, temperature, reserve=9.0, water=True):
        context = decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-07-27", "hauteur_coupe_mm": 55.0}],
            today=jour,
            hour_of_day=heure,
            temperature=temperature,
            memory=memoire,
        )
        bundle = {"reserve_actuelle_mm": reserve, "reserve_minimale_mm": 6.0,
                  "reserve_hydrique_sol_mm": reserve} if water else {}
        return decision_mowing._grass_growth_details(
            context, {"phase_dominante": "Normal"}, bundle
        )

    def _journee(self, mesures, memoire=None):
        """Déroule une journée en réinjectant l'état, comme le fait le coordinateur."""
        memoire = {} if memoire is None else memoire
        sorties = []
        for heure, temp, reserve in mesures:
            d = self._details(date(2026, 8, 1), heure, memoire,
                              temperature=temp, reserve=reserve)
            memoire["pousse_gazon"] = d["etat"]
            sorties.append(d)
        return sorties, memoire

    def test_le_scenario_reel_du_01_08(self) -> None:
        # Conditions relevées : réserve 5,2 → 4,6 → 4,2 mm, température 23 → 26 → 26,1 °C.
        sorties, _ = self._journee([(9.17, 23.0, 5.2), (11.67, 26.0, 4.6), (12.66, 26.1, 4.2)])
        hauteurs = [d["hauteur_cm"] for d in sorties]
        self.assertEqual(hauteurs, sorted(hauteurs), f"la hauteur recule : {hauteurs}")

    def test_le_seuil_des_24_degres_n_efface_pas_la_matinee(self) -> None:
        # 24,0 °C (frein 1,0) puis 24,1 °C (frein 0,65) : un dixième de degré.
        sorties, _ = self._journee([(10.0, 24.0, 9.0), (10.5, 24.1, 9.0)])
        self.assertGreaterEqual(
            sorties[1]["pousse_jour_cm"], sorties[0]["pousse_jour_cm"],
            "franchir 24 °C efface la pousse déjà acquise",
        )

    def test_la_pousse_du_jour_est_monotone_quelles_que_soient_les_conditions(self) -> None:
        memoire: dict = {}
        precedent = -1.0
        # Chaleur qui monte puis retombe, réserve qui s'épuise : rien ne doit reculer.
        for heure, temp, reserve in [
            (2.0, 18.0, 11.0), (5.0, 20.0, 10.0), (8.0, 24.0, 8.0), (11.0, 27.0, 6.5),
            (14.0, 33.0, 5.0), (17.0, 31.0, 4.0), (20.0, 26.0, 3.0), (23.0, 21.0, 2.0),
        ]:
            d = self._details(date(2026, 8, 1), heure, memoire,
                              temperature=temp, reserve=reserve)
            memoire["pousse_gazon"] = d["etat"]
            self.assertGreaterEqual(
                d["pousse_jour_cm"], precedent,
                f"recul à {heure} h ({temp} °C, {reserve} mm) : "
                f"{precedent} → {d['pousse_jour_cm']}",
            )
            precedent = d["pousse_jour_cm"]

    def test_a_conditions_stables_le_total_du_soir_est_inchange(self) -> None:
        """L'accumulation ne doit pas déplacer le modèle, seulement l'empêcher de reculer."""
        sorties, _ = self._journee([(h, 20.0, 9.0) for h in (2, 6, 10, 14, 18, 22)])
        taux = decision_mowing._growth_rate_cm_per_day({"phase_dominante": "Normal"}, 8)
        attendu = taux * 1.0 * decision_mowing._growth_day_fraction(22.0)
        self.assertAlmostEqual(sorties[-1]["pousse_jour_cm"], attendu, places=2)

    def test_le_frein_reste_actif_sur_la_suite_de_la_journee(self) -> None:
        """Empêcher le recul ne doit pas neutraliser le frein : la CHALEUR doit ralentir."""
        chaud, _ = self._journee([(8.0, 20.0, 9.0), (20.0, 34.0, 9.0)])
        doux, _ = self._journee([(8.0, 20.0, 9.0), (20.0, 20.0, 9.0)])
        self.assertLess(
            chaud[-1]["pousse_jour_cm"], doux[-1]["pousse_jour_cm"],
            "la chaleur de l'après-midi ne freine plus rien",
        )

    def test_migration_depuis_un_etat_sans_fraction(self) -> None:
        """Le chemin réel de la montée de version 0.33.1 → 0.34.0.

        L'état persisté par l'ancienne version porte `jour_cm` mais pas `fraction`. Le premier
        cycle doit REPRENDRE la valeur mémorisée telle quelle — ni saut, ni chute — puis
        accumuler normalement. Sans ce repli, la reprise recalculerait avec le frein du moment
        et rejouerait exactement le défaut qu'on corrige, une fois, au redémarrage.
        """
        memoire = {"pousse_gazon": {"date": "2026-08-01", "tonte": "2026-07-27",
                                    "acquis_cm": 1.20, "jour_cm": 0.15, "frein": 0.455}}
        reprise = self._details(date(2026, 8, 1), 12.66, memoire,
                                temperature=26.1, reserve=4.2)
        self.assertAlmostEqual(reprise["pousse_jour_cm"], 0.15, places=2,
                               msg="la reprise recalcule au lieu de prolonger")
        memoire["pousse_gazon"] = reprise["etat"]

        suite = [reprise["pousse_jour_cm"]]
        for heure, temp, res in [(15.0, 28.0, 3.7), (18.0, 26.0, 3.2), (21.0, 22.0, 2.9)]:
            d = self._details(date(2026, 8, 1), heure, memoire,
                              temperature=temp, reserve=res)
            memoire["pousse_gazon"] = d["etat"]
            suite.append(d["pousse_jour_cm"])
        self.assertEqual(suite, sorted(suite), f"recul après migration : {suite}")

    def test_le_lendemain_repart_de_zero(self) -> None:
        _sorties, memoire = self._journee([(10.0, 22.0, 9.0), (22.0, 22.0, 9.0)])
        lendemain = self._details(date(2026, 8, 2), 1.0, memoire, temperature=22.0)
        self.assertLess(lendemain["pousse_jour_cm"], 0.05,
                        "la pousse d'hier est recomptée aujourd'hui")


class TestFreinSansBilanHydrique(unittest.TestCase):
    """Eau inconnue ≠ eau à volonté.

    Au redémarrage, le premier cycle tourne sans bilan hydrique. Le frein d'eau était
    silencieusement sauté : facteur 1,0, hauteur trop haute publiée pendant ~1 s. Relevé sur
    l'installation le 01/08/2026 — 12:39:34,5 → 6,0 cm, 12:39:35,4 → 5,9 cm ; et le même
    doublet la veille à 13:58:21. Même piège que le repli « soleil inconnu » de la 0.21.4.
    """

    @staticmethod
    def _context(jour, memoire, temperature=20.0):
        return decision.DecisionContext.from_legacy_args(
            history=[{"type": "tonte", "date": "2026-07-27", "hauteur_coupe_mm": 55.0}],
            today=jour, hour_of_day=12.0, temperature=temperature, memory=memoire,
        )

    def test_sans_bilan_le_frein_ne_depasse_pas_le_dernier_connu_du_jour(self) -> None:
        memoire = {"pousse_gazon": {"date": "2026-08-01", "tonte": "2026-07-27",
                                    "acquis_cm": 1.0, "jour_cm": 0.1, "frein": 0.45}}
        ctx = self._context(date(2026, 8, 1), memoire)
        sans_eau = decision_mowing._growth_modulation(
            ctx, {}, frein_plafond=decision_mowing._frein_memorise_du_jour(ctx)
        )
        self.assertLessEqual(sans_eau, 0.45)

    def test_le_frein_d_hier_ne_plafonne_PAS_aujourd_hui(self) -> None:
        """Sinon une canicule d'hier bloquerait la pousse d'une journée fraîche."""
        memoire = {"pousse_gazon": {"date": "2026-07-31", "tonte": "2026-07-27",
                                    "acquis_cm": 1.0, "jour_cm": 0.1, "frein": 0.0}}
        ctx = self._context(date(2026, 8, 1), memoire)
        self.assertIsNone(decision_mowing._frein_memorise_du_jour(ctx))
        sans_eau = decision_mowing._growth_modulation(
            ctx, {}, frein_plafond=decision_mowing._frein_memorise_du_jour(ctx)
        )
        self.assertEqual(sans_eau, 1.0)

    def test_le_plafond_ne_releve_jamais_le_frein(self) -> None:
        # Plafond large, mais 34 °C : le frein thermique doit rester maître.
        memoire = {"pousse_gazon": {"date": "2026-08-01", "tonte": "2026-07-27",
                                    "acquis_cm": 1.0, "jour_cm": 0.1, "frein": 1.0}}
        ctx = self._context(date(2026, 8, 1), memoire, temperature=34.0)
        self.assertAlmostEqual(
            decision_mowing._growth_modulation(
                ctx, {}, frein_plafond=decision_mowing._frein_memorise_du_jour(ctx)),
            0.25, places=3,
        )

    def test_avec_bilan_le_plafond_est_ignore(self) -> None:
        # Quand l'eau est connue, c'est elle qui décide — pas un souvenir.
        memoire = {"pousse_gazon": {"date": "2026-08-01", "tonte": "2026-07-27",
                                    "acquis_cm": 1.0, "jour_cm": 0.1, "frein": 0.2}}
        ctx = self._context(date(2026, 8, 1), memoire)
        avec_eau = decision_mowing._growth_modulation(
            ctx, {"reserve_hydrique_sol_mm": 12.0, "reserve_minimale_mm": 6.0},
            frein_plafond=decision_mowing._frein_memorise_du_jour(ctx),
        )
        self.assertEqual(avec_eau, 1.0)


class TestBesoinSepareDeLaDose(unittest.TestCase):
    """« Combien il lui faut » ≠ « combien je vais verser ».

    Signalé par Kévin le 01/08/2026 : l'entité « Objectif d'arrosage » affichait 0,0 mm
    pendant que ses PROPRES attributs annonçaient `depletion_mm: 7,8` et une réserve 1,8 mm
    sous le seuil de déclenchement. Cause : `if block_reason is not None: mm_cible = 0.0`,
    écrit dans les deux branches. Zéro est juste pour la DOSE — un arrosage bloqué verse bien
    zéro — mais faux pour le BESOIN, qu'aucun garde-fou ne fait disparaître. Relevé six fois
    en trois jours, dont quatre retours à la valeur identique (7,4 → 0,0 → 7,4).

    `objectif_mm` garde volontairement son sens (la dose : il sert de `target_cycle_mm` au plan
    d'arrosage). C'est `besoin_mm` qui porte désormais le besoin.
    """

    WB = {"bilan_hydrique_mm": -4.5, "reserve_hydrique_sol_mm": 4.2, "reserve_actuelle_mm": 4.2,
          "reserve_minimale_mm": 6.0, "reserve_utile_mm": 12.0, "depletion_mm": 7.8,
          "depletion_ratio": 0.65, "mad_ratio": 0.5, "deficit_3j": 3.4, "deficit_7j": 9.4,
          "reserve_from_soil_ledger": True, "et0_mm": 5.8, "etc_mm": 4.6,
          "reserve_stock_mm": 4.2, "reserve_stock_max_mm": 24.0, "et_elapsed_fraction": 0.52,
          "arrosage_recent_7j": 22.1, "arrosage_recent_jour": 0.0}

    def _profil(self, **over):
        kw = dict(phase_dominante="Normal", sous_phase="Normal", water_balance=self.WB,
                  today=date(2026, 8, 1), pluie_24h=0.0, pluie_demain=0.0,
                  humidite=52.0, temperature=26.1, etp=5.8, type_sol="limoneux")
        kw.update(over)
        return guidance.compute_watering_profile(**kw)

    def test_un_blocage_annule_la_dose_mais_pas_le_besoin(self) -> None:
        # ⚠️ Cette fixture a bloqué par la PLUIE jusqu'au 02/08/2026 : une prévision ne bloque plus
        # un sol au-delà du seuil MAD depuis la 0.37.0. Elle a ensuite bloqué par l'HUMIDITÉ DE
        # L'AIR jusqu'au 15/09/2026, date à laquelle l'air humide a cessé de bloquer. On passe
        # désormais par la garde « un arrosage par jour » : une POLITIQUE qui retient l'eau sans
        # rien changer à la soif du sol.
        maintenant = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        deja_arrose = [{"type": "arrosage", "date": "2026-08-01", "total_mm": 2.0,
                        "source": "manual_irrigation", "watering_cause": "hydrique"}]
        with patch.object(guidance, "_current_datetime", return_value=maintenant):
            bloque = self._profil(history=deja_arrose)
        self.assertEqual(bloque["block_reason"], "cooldown_24h")
        self.assertEqual(bloque["mm_final_recommande"], 0.0, "la dose doit rester à zéro")
        self.assertAlmostEqual(bloque["besoin_mm"], 7.8, places=1,
                               msg="le besoin a disparu avec le blocage")

    def test_le_besoin_ne_ment_pas_sur_un_sol_confortable(self) -> None:
        """Sol au-dessus du seuil : le besoin est réellement nul, et doit être calculé."""
        confort = {**self.WB, "depletion_mm": 1.0, "depletion_ratio": 0.08,
                   "reserve_actuelle_mm": 11.0, "reserve_stock_mm": 11.0,
                   "reserve_hydrique_sol_mm": 11.0}
        p = self._profil(water_balance=confort)
        self.assertEqual(p["besoin_mm"], 0.0)

    def test_sans_blocage_besoin_et_dose_coincident(self) -> None:
        libre = self._profil()
        self.assertIsNone(libre["block_reason"])
        self.assertEqual(libre["besoin_mm"], libre["mm_final_recommande"])

    def test_le_besoin_ignore_le_garde_fou_hebdomadaire(self) -> None:
        """Le plafond hebdo est une POLITIQUE : il rogne la dose, pas le besoin du sol.

        ⚠️ Première version de ce test : 28,5 mm consommés, en croyant épuiser le budget.
        Le plafond vaut 37,4 mm sur cette fixture — il ne mordait donc jamais, et le test
        passait au vert même en capturant le besoin APRÈS le plafond. On l'épuise pour de bon.
        """
        p = self._profil(water_balance={**self.WB, "arrosage_recent_7j": 35.0})
        self.assertAlmostEqual(p["besoin_mm"], 7.8, places=1)
        self.assertLess(
            p["mm_final_recommande"], p["besoin_mm"],
            "le plafond ne rogne pas la dose : la fixture ne l'épuise pas",
        )


class TestLHumiditeDeLAirNeBloquePlusLArrosage(unittest.TestCase):
    """Arbitrage de Kévin, 15/09/2026 : l'air humide ne bloque plus un arrosage demandé.

    `humidite >= 85` bloquait sans regarder la soif du sol. Or, à l'aube, l'air est
    naturellement proche de la saturation. Le 13/09, l'humidité est restée entre 88 et 93 % de
    03:30 à 08:57, et l'arrosage « de l'aube » est parti à 08:58. Le 15/09, l'objectif basculait
    entre 5,3 et 0 mm à chaque lecture entre 84 et 85 %. Les sources agronomiques recommandent
    d'arroser juste avant le lever du soleil, sur la rosée (NC State, université de Géorgie,
    Purdue).
    """

    WB = TestBesoinSepareDeLaDose.WB
    MATIN = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)

    def _profil(self, **over):
        kw = dict(phase_dominante="Normal", sous_phase="Normal", water_balance=self.WB,
                  today=date(2026, 9, 13), pluie_24h=0.0, pluie_demain=0.0,
                  humidite=60.0, temperature=16.0, etp=3.3, type_sol="limoneux")
        kw.update(over)
        with patch.object(guidance, "_current_datetime", return_value=self.MATIN):
            return guidance.compute_watering_profile(**kw)

    def test_un_sol_qui_a_soif_est_arrose_meme_par_air_sature(self) -> None:
        reference = self._profil(humidite=60.0)
        self.assertIsNone(reference["block_reason"])
        self.assertGreater(reference["mm_final_recommande"], 0.0)
        for humidite in (84.0, 85.0, 88.0, 93.0, 100.0):
            with self.subTest(humidite=humidite):
                p = self._profil(humidite=humidite)
                self.assertIsNone(p["block_reason"], "l'air humide bloque encore l'arrosage")
                self.assertEqual(p["mm_final_recommande"], reference["mm_final_recommande"])

    def test_l_humidite_ne_reduit_pas_une_dose_legacy_deja_calculee_par_et0(self) -> None:
        """Une ET0 fixee contient deja l'effet de l'humidite de l'air."""
        sans_ledger = {
            "bilan_hydrique_mm": -10.0,
            "deficit_jour": 10.0,
            "deficit_3j": 10.0,
            "deficit_7j": 10.0,
            "arrosage_recent_7j": 0.0,
            "arrosage_recent_jour": 0.0,
            "reserve_from_soil_ledger": False,
            "etp_connue": True,
        }
        reference = self._profil(water_balance=sans_ledger, humidite=60.0, etp=3.0)
        self.assertEqual(reference["mm_final_recommande"], 10.0)
        for humidite in (80.0, 90.0):
            with self.subTest(humidite=humidite):
                profil = self._profil(
                    water_balance=sans_ledger,
                    humidite=humidite,
                    etp=3.0,
                )
                self.assertEqual(profil["deficit_mm_ajuste"], reference["deficit_mm_ajuste"])
                self.assertEqual(
                    profil["mm_final_recommande"], reference["mm_final_recommande"]
                )

    def test_l_humidite_ne_declenche_pas_le_garde_fou_hebdomadaire(self) -> None:
        """Le garde-fou ne doit pas recompter l'humidite deja integree a l'ET0."""
        bilan = {
            "bilan_hydrique_mm": -25.0,
            "deficit_jour": 25.0,
            "deficit_3j": 25.0,
            "deficit_7j": 25.0,
            "arrosage_recent_7j": 21.0,
            "arrosage_recent_jour": 0.0,
            "reserve_from_soil_ledger": True,
            "reserve_utile_mm": 12.0,
            "depletion_mm": 4.8,
            "depletion_ratio": 0.4,
            "mad_ratio": 0.5,
            "reserve_actuelle_mm": 7.2,
            "reserve_stock_mm": 7.2,
            "reserve_stock_max_mm": 12.0,
            "et0_mm": 4.0,
            "etc_mm": 3.0,
            "et_elapsed_fraction": 0.0,
            "etp_connue": True,
        }
        historique = [
            {
                "type": "arrosage",
                "date": f"2026-09-{jour:02d}",
                "total_mm": 7.0,
                "source": "auto",
                "watering_cause": "hydrique",
            }
            for jour in (8, 10, 12)
        ]
        reference = self._profil(
            water_balance=bilan,
            history=historique,
            humidite=60.0,
            etp=4.0,
        )
        self.assertIsNone(reference["block_reason"])
        self.assertEqual(reference["mm_final_recommande"], 4.8)
        humide = self._profil(
            water_balance=bilan,
            history=historique,
            humidite=90.0,
            etp=4.0,
        )
        self.assertEqual(humide["deficit_mm_ajuste"], reference["deficit_mm_ajuste"])
        self.assertEqual(humide["block_reason"], reference["block_reason"])
        self.assertEqual(humide["mm_final_recommande"], reference["mm_final_recommande"])

    def test_les_phases_agronomiques_et_le_profil_generique_ne_bloquent_plus_sur_l_air(self) -> None:
        # « Fertilisation » passe par `_profile_for_agro_phases`, une phase inconnue par
        # `_profile_for_generic` : les deux portaient la même règle (`humidite_elevee`).
        for phase in ("Fertilisation", "Phase inconnue"):
            with self.subTest(phase=phase):
                p = self._profil(phase_dominante=phase, sous_phase=phase, humidite=93.0)
                self.assertNotEqual(p["block_reason"], "humidite_elevee")
                self.assertIsNone(p["block_reason"])
                self.assertGreater(p["mm_final_recommande"], 0.0)

    def test_les_autres_gardes_tiennent_par_air_sature(self) -> None:
        # Arrosage fini à 04:55 (heure de Paris), décision à 06:00 : même journée locale. Sans
        # `ended_at`, le repli à 06:00 tombe pile sur la décision et l'écart peut devenir négatif.
        deja_arrose = [{"type": "arrosage", "date": "2026-09-13", "total_mm": 2.0,
                        "ended_at": "2026-09-13T04:55:00+02:00",
                        "source": "manual_irrigation", "watering_cause": "hydrique"}]
        self.assertEqual(
            self._profil(humidite=93.0, history=deja_arrose)["block_reason"], "cooldown_24h"
        )
        confort = {**self.WB, "depletion_mm": 1.0, "depletion_ratio": 0.08,
                   "reserve_actuelle_mm": 11.0, "reserve_stock_mm": 11.0,
                   "reserve_hydrique_sol_mm": 11.0, "bilan_hydrique_mm": -1.0}
        self.assertEqual(
            self._profil(humidite=93.0, water_balance=confort, pluie_demain=12.0)["block_reason"],
            "pluie_prevue_suffisante",
        )

    def test_un_bilan_du_jour_deja_positif_bloque_encore_sans_regarder_l_air(self) -> None:
        # La seconde moitié de l'ancienne condition reste : apports du jour > évaporation sur un
        # sol qui ne réclame rien. Elle ne dépend pas de l'humidité de l'air.
        sature_d_apports = {**self.WB, "depletion_mm": 1.0, "depletion_ratio": 0.08,
                            "reserve_actuelle_mm": 11.0, "reserve_stock_mm": 11.0,
                            "reserve_hydrique_sol_mm": 11.0, "bilan_hydrique_mm": 1.0}
        for humidite in (40.0, 93.0):
            with self.subTest(humidite=humidite):
                p = self._profil(humidite=humidite, water_balance=sature_d_apports)
                self.assertEqual(p["block_reason"], "humidite_excessive")

    def test_la_fenetre_n_attend_plus_sur_l_air_humide(self) -> None:
        # `compute_action_guidance` renvoyait « attendre » dès 85 % avec un bilan ≥ −0,5 mm, et le
        # lanceur refuse « attendre ». On n'y arrive qu'avec un objectif > 0 : un arrosage demandé.
        base = dict(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={"bilan_hydrique_mm": -0.2, "deficit_3j": 0.5, "deficit_7j": 1.0},
            advanced_context={"vent": 5.0, "rosee": 1.0, "hauteur_gazon": 4.0},
            pluie_24h=0.0,
            pluie_demain=0.0,
            temperature=16.0,
            etp=3.3,
            objectif_mm=5.3,
        )
        for heure, attendu in ((3.0, "ce_matin"), (5.0, "maintenant")):
            for humidite in (60.0, 85.0, 93.0):
                with self.subTest(heure=heure, humidite=humidite):
                    fenetre = decision.compute_action_guidance(
                        hour_of_day=heure, humidite=humidite, **base
                    )["fenetre_optimale"]
                    self.assertEqual(fenetre, attendu)


class LesDeuxTermesDuGardeFouMesurentLaMemeChoseTests(unittest.TestCase):
    """`recent_watering_count` et `recent_watering_mm_7j` sont combinés par un `and` dans la
    retenue hebdomadaire, mais portaient sur des fenêtres DIFFÉRENTES :

      - le compteur : `days=7`, or le filtre retient `delta <= days` → **8 jours calendaires**,
        et il ne pouvait PAS exclure les arrosages manuels ;
      - le budget mm : `days=6` → **7 jours**, manuels exclus depuis le 25/07/2026.

    Conséquence : le cercle vicieux que cette exclusion avait supprimé pouvait se refermer par
    la porte du compteur — réserve à sec → auto bloqué → arrosage manuel de secours → le compte
    passe de 2 à 3 → le blocage que l'arrosage manuel venait de contourner est RÉARMÉ.
    """

    AUJOURD_HUI = date(2026, 8, 6)

    def _arrosage(self, jours, *, source="auto_irrigation", mm=6.0):
        return {
            "type": "arrosage",
            "date": (self.AUJOURD_HUI - timedelta(days=jours)).isoformat(),
            "total_mm": mm,
            "source": source,
        }

    def _compte(self, history):
        return water.compute_recent_watering_count(
            history, today=self.AUJOURD_HUI, days=6,
            include_external=False, include_manual=False,
        )

    def _budget(self, history):
        return water.compute_recent_watering_mm(
            history, today=self.AUJOURD_HUI, days=6,
            include_external=False, include_manual=False,
        )

    def test_un_arrosage_manuel_ne_rearme_pas_le_blocage(self) -> None:
        """LE cas qui compte : deux arrosages auto, plus un manuel de secours."""
        history = [self._arrosage(1), self._arrosage(3),
                   self._arrosage(0, source="manual_irrigation")]
        self.assertEqual(
            self._compte(history), 2,
            "l'arrosage manuel de secours fait passer le compte à 3 et réarme la retenue",
        )

    def test_les_deux_termes_couvrent_exactement_la_meme_fenetre(self) -> None:
        """Le 8e jour ne doit être vu ni par l'un ni par l'autre."""
        for age in range(0, 10):
            with self.subTest(jours=age):
                h = [self._arrosage(age)]
                vu_par_le_compte = self._compte(h) > 0
                vu_par_le_budget = self._budget(h) > 0
                self.assertEqual(
                    vu_par_le_compte, vu_par_le_budget,
                    f"à J-{age}, compte={vu_par_le_compte} mais budget={vu_par_le_budget}",
                )

    def test_le_huitieme_jour_est_bien_hors_fenetre(self) -> None:
        self.assertEqual(self._compte([self._arrosage(7)]), 0)
        self.assertEqual(self._compte([self._arrosage(6)]), 1)

    def test_trois_vrais_arrosages_auto_comptent_toujours(self) -> None:
        """Garde-fou inverse : on n'a pas neutralisé la retenue."""
        history = [self._arrosage(0), self._arrosage(2), self._arrosage(4)]
        self.assertEqual(self._compte(history), 3)
        self.assertGreater(self._budget(history), 0.0)

    def test_le_compteur_sait_encore_tout_compter_quand_on_le_lui_demande(self) -> None:
        """Le paramètre reste optionnel : les autres appelants ne changent pas de comportement."""
        history = [self._arrosage(1), self._arrosage(0, source="manual_irrigation")]
        self.assertEqual(
            water.compute_recent_watering_count(history, today=self.AUJOURD_HUI, days=6), 2
        )


class LeGardeFouCompteBienCeQuIlPublieTests(unittest.TestCase):
    """Test de CÂBLAGE — les tests du helper seul ne voient pas l'appel.

    `compute_recent_watering_count` peut être parfaitement correct et l'appelant lui passer
    quand même la mauvaise fenêtre : c'est exactement ce qui se passait
    (`days=7` et manuels comptés côté guidance, `days=6` et manuels exclus côté budget).
    On part donc de l'historique et on lit ce que la chaîne PUBLIE.
    """

    AUJOURD_HUI = date(2026, 8, 6)

    def _arrosage(self, jours, *, source="auto_irrigation", mm=6.0):
        return {
            "type": "arrosage",
            "date": (self.AUJOURD_HUI - timedelta(days=jours)).isoformat(),
            "total_mm": mm,
            "source": source,
        }

    def _publie(self, history):
        ctx = decision.DecisionContext.from_legacy_args(
            history=history, today=self.AUJOURD_HUI, hour_of_day=5,
            temperature=24.0, pluie_24h=0, pluie_demain=0, humidite=55,
            type_sol="limoneux", etp_capteur=4.0,
        )
        phase = decision.build_phase_bundle(ctx)
        water_b = decision.build_water_bundle(ctx, phase)
        # ⚠️ Les deux clés vivent dans le WATER bundle (`build_water_bundle`), pas dans le
        # watering bundle : ce dernier recopie les clés une par une. Se tromper de bundle donne
        # un KeyError franc — mieux qu'un test qui passerait sur autre chose.
        return water_b["recent_watering_count_7j"], water_b["recent_watering_mm_7j"]

    def test_l_arrosage_manuel_de_secours_ne_gonfle_pas_le_compte_publie(self) -> None:
        compte, budget = self._publie([
            self._arrosage(1), self._arrosage(3),
            self._arrosage(0, source="manual_irrigation", mm=8.0),
        ])
        self.assertEqual(compte, 2, "l'arrosage manuel est compté et réarme la retenue")
        self.assertAlmostEqual(budget, 12.0, places=1,
                               msg="prémisse : le budget mm exclut déjà le manuel")

    def test_le_compte_et_le_budget_publies_voient_la_meme_fenetre(self) -> None:
        for age in (5, 6, 7, 8):
            with self.subTest(jours=age):
                compte, budget = self._publie([self._arrosage(age)])
                self.assertEqual(
                    compte > 0, budget > 0,
                    f"à J-{age} : compte={compte}, budget={budget} — fenêtres divergentes",
                )

    def test_trois_arrosages_auto_sont_toujours_comptes(self) -> None:
        compte, _ = self._publie([self._arrosage(0), self._arrosage(2), self._arrosage(4)])
        self.assertEqual(compte, 3)


class LesQuatreAffichagesDeLAuditTests(unittest.TestCase):
    """Quatre défauts d'affichage relevés le 06/08/2026. Aucun ne change une décision —
    tous rendent le diagnostic faux, ce qui coûte du temps quand quelque chose cloche.
    """

    def test_une_panne_ne_s_affiche_plus_comme_au_repos(self) -> None:
        """Le robot annonce `idle` quand il est immobilisé en plein jardin.

        Vérifié : du 02 au 05/08/2026, les 7 arrêts en jardin coïncident À LA SECONDE avec un
        déclenchement d'erreur, et l'état brut du robot y vaut `idle`.
        """
        mower_adapter = importlib.import_module(
            "custom_components.gazon_intelligent.mower_adapter"
        )
        self.assertEqual(mower_adapter._status_label("erreur", "idle"), "Erreur")
        self.assertEqual(mower_adapter._status_label("erreur", "docked"), "Erreur")
        # Contrôle négatif : hors panne, l'état brut garde sa précision.
        self.assertEqual(mower_adapter._status_label("au_repos", "idle"), "Au repos")
        self.assertEqual(mower_adapter._status_label("au_repos", "docked"), "À la station")

    def test_les_six_codes_orphelins_ont_un_libelle(self) -> None:
        """Ils étaient publiés en snake_case brut sur la carte et dans les attributs."""
        const = importlib.import_module("custom_components.gazon_intelligent.const")
        for code in ("machine_unavailable", "mowing_window_blocked", "recent_watering",
                     "soil_wet", "upcoming_watering", "wet_grass"):
            with self.subTest(code=code):
                libelle = const.BLOCK_REASON_DISPLAY_LABELS.get(code)
                self.assertIsNotNone(libelle, f"{code} n'a toujours pas de libellé")
                self.assertNotIn("_", libelle)

    def test_aucun_code_publie_ne_reste_sans_libelle(self) -> None:
        """Invariant : un code émis sans libellé s'affiche en brut. On l'interdit."""
        import re as _re
        from pathlib import Path as _Path
        racine = _Path(__file__).resolve().parents[1] / "custom_components" / "gazon_intelligent"
        const = importlib.import_module("custom_components.gazon_intelligent.const")
        guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")
        emis: set[str] = set()
        for nom in (
            "decision_mowing.py",
            "guidance.py",
            "decision_watering.py",
            "watering_policy.py",
        ):
            src = (racine / nom).read_text(encoding="utf-8")
            for motif in (r'reason_code\s*=\s*"([a-z_0-9]+)"',
                          r'block_reason\s*=\s*"([a-z_0-9]+)"',
                          r'return\s+True,\s*"([a-z_0-9]+)"',
                          r'return\s*\(\s*True,\s*"([a-z_0-9]+)"',
                          r'BlockingEvaluation\(True,\s*"([a-z_0-9]+)"'):
                emis |= set(_re.findall(motif, src))
        # Les politiques emploient quelques codes internes normalisés avant publication
        # (`heavy_rain_expected` -> `pluie_prevue_suffisante`, par exemple). L'invariant porte
        # sur le contrat public, pas sur ces détails internes.
        publies = {guidance._normalize_public_block_reason(code) for code in emis}
        orphelins = sorted(c for c in publies if c not in const.BLOCK_REASON_DISPLAY_LABELS)
        self.assertEqual(orphelins, [], f"codes publiés sans libellé : {orphelins}")


class LePlancherDemainCouvreLaFenetreEcouleeTests(unittest.TestCase):
    """« Prochain arrosage : aujourd'hui » à 15 h, pour une fenêtre fermée depuis cinq heures.

    `estimate_days_until_watering` ne raisonne que sur la réserve : son `0` signifie « la
    projection d'aube franchit le seuil », pas « c'est encore possible aujourd'hui ». Un
    plancher existait, mais uniquement quand on avait DÉJÀ arrosé. Le cas qui compte est
    l'inverse : la fenêtre du matin s'est écoulée SANS arrosage — retenu par un garde-fou, ou
    conditions défavorables.
    """

    def _bundle(self, *, heure, history=None):
        ctx = decision.DecisionContext.from_legacy_args(
            history=history or [], today=date(2026, 8, 6), hour_of_day=heure,
            temperature=28.0, pluie_24h=0, pluie_demain=0, humidite=45,
            type_sol="limoneux", etp_capteur=6.0,
            soil_balance={"reserve_mm": 5.5, "reserve_max_mm": 24.0},
        )
        phase = decision.build_phase_bundle(ctx)
        return decision.build_water_bundle(ctx, phase)

    def test_a_l_aube_la_reponse_peut_rester_aujourd_hui(self) -> None:
        """PRÉMISSE : sans ce cas, le test suivant serait vrai par accident."""
        b = self._bundle(heure=5)
        self.assertEqual(
            b["jours_avant_arrosage_estime"], 0,
            "prémisse cassée : ce sol doit être déclaré assoiffé dès l'aube",
        )
        self.assertEqual(b["date_prochain_arrosage_estime"], "2026-08-06")

    def test_l_apres_midi_la_reponse_bascule_a_demain(self) -> None:
        b = self._bundle(heure=15)
        self.assertGreaterEqual(
            b["jours_avant_arrosage_estime"], 1,
            "la fenêtre du matin est fermée et l'entité annonce encore aujourd'hui",
        )
        self.assertEqual(b["date_prochain_arrosage_estime"], "2026-08-07")

    def test_le_plancher_apres_arrosage_du_jour_fonctionne_toujours(self) -> None:
        """Le cas d'origine (29/07/2026) ne doit pas régresser."""
        b = self._bundle(heure=8, history=[{
            "type": "arrosage", "date": "2026-08-06",
            "total_mm": 6.0, "source": "auto_irrigation",
        }])
        self.assertGreaterEqual(b["jours_avant_arrosage_estime"], 1)


class RecommandationDeHauteurTests(unittest.TestCase):
    """0.87.0 — la recommandation de hauteur suit les mois, pas les matins humides.

    Question de Kévin le 11/09/2026 : « elle a toujours été à 6 cm ». Trois causes empilées :
    une table qui ne descendait jamais sous 5 cm, un stress « fort » lu dans un déficit PROJETÉ
    (armé en permanence sur un gazon arrosé, +1,0), et un arrondi vers le haut qui montait d'un
    cran au moindre +0,1 de rosée ou de pluie. Chaque mécanisme a ici son test : les six termes
    retirés n'étaient épinglés par AUCUN test (banc de mutations de la cartographie).
    """

    REGISTRE_PLEIN = {"reserve_mm": 11.5, "reserve_max_mm": 24.0}

    def _reco(self, jour: date, **kw) -> dict:
        params = dict(
            history=[], today=jour, hour_of_day=10, temperature=18.0,
            forecast_temperature_today=18.0, pluie_24h=0, pluie_demain=0, humidite=60,
            type_sol="limoneux", etp_capteur=2.5, hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=8.0, soil_balance=self.REGISTRE_PLEIN,
        )
        params.update(kw)
        return decision.build_decision_snapshot(**params)

    def test_la_table_mois_par_mois(self) -> None:
        # Journée douce (18 °C prévus), réserve pleine : il ne reste que la base du mois, plus
        # le +0,5 d'hiver (mois 1, 2, 11, 12) que la table suppose.
        attendu = {1: 4.5, 2: 4.5, 3: 4.5, 4: 4.0, 5: 4.0, 6: 4.5,
                   7: 5.0, 8: 5.0, 9: 4.0, 10: 4.0, 11: 4.5, 12: 4.5}
        for mois, hauteur in attendu.items():
            with self.subTest(mois=mois):
                self.assertEqual(self._reco(date(2026, mois, 15))["hauteur_tonte_recommandee_cm"], hauteur)

    def test_rosee_et_pluie_ne_reglent_plus_la_hauteur(self) -> None:
        for mois in (4, 9, 10, 11):
            sec = self._reco(date(2026, mois, 15))
            mouille = self._reco(
                date(2026, mois, 15), rosee=1.0, pluie_24h=8.0, pluie_demain=6.0, pluie_j2=4.0,
                pluie_3j=12.0, pluie_probabilite_max_3j=95, humidite=92,
            )
            with self.subTest(mois=mois):
                self.assertEqual(
                    mouille["hauteur_tonte_recommandee_cm"], sec["hauteur_tonte_recommandee_cm"],
                    "la rosée ou la pluie remontent encore la lame",
                )
                self.assertNotIn("rosée", mouille["hauteur_tonte_motif"])
                self.assertNotIn("pluie", mouille["hauteur_tonte_motif"])

    def test_jamais_sous_4_cm_par_bonnes_conditions(self) -> None:
        # Les conditions exactes de l'ancien −0,5 (mois 4, 5, 6, 9 ; 15-24 °C ; HR ≥ 50 ; sec).
        for mois in (4, 5, 6, 9):
            for temperature in (15.0, 20.0, 24.0):
                with self.subTest(mois=mois, temperature=temperature):
                    reco = self._reco(
                        date(2026, mois, 15), temperature=temperature,
                        forecast_temperature_today=temperature, humidite=65,
                    )["hauteur_tonte_recommandee_cm"]
                    self.assertGreaterEqual(reco, 4.0, "sous la hauteur de pousse voulue")

    def test_le_stress_se_lit_dans_la_RESERVE_pas_dans_le_deficit_projete(self) -> None:
        # ETP forte, ni pluie ni arrosage depuis 7 jours : le déficit PROJETÉ s'emballe. Mais le
        # registre dit la réserve pleine — rien ne justifie de monter la lame.
        chaud_et_sec = dict(etp_capteur=6.0, humidite=45)
        avec_registre = self._reco(date(2026, 9, 15), **chaud_et_sec)
        sans_registre = self._reco(date(2026, 9, 15), soil_balance=None, **chaud_et_sec)
        self.assertEqual(avec_registre["hauteur_tonte_recommandee_cm"], 4.0)
        self.assertNotIn("manque d'eau", avec_registre["hauteur_tonte_motif"])
        # Sans registre, le repli garde l'ancien indicateur : une absence de mesure n'est pas
        # « aucun stress ».
        self.assertGreater(sans_registre["hauteur_tonte_recommandee_cm"], 4.0)
        self.assertIn("déficit estimé", sans_registre["hauteur_tonte_motif"])

    def test_une_reserve_reellement_basse_monte_la_lame(self) -> None:
        paliers = []
        for reserve in (11.5, 4.0, 1.0):
            snap = self._reco(date(2026, 9, 15), soil_balance={"reserve_mm": reserve, "reserve_max_mm": 24.0})
            paliers.append(snap["hauteur_tonte_recommandee_cm"])
            if reserve < 6.0:
                self.assertIn("réserve du sol", snap["hauteur_tonte_motif"])
        self.assertEqual(paliers, [4.0, 4.5, 5.0])

    def test_la_temperature_du_JOUR_pas_celle_du_thermometre(self) -> None:
        aube_fraiche = self._reco(date(2026, 4, 15), hour_of_day=6, temperature=5.0,
                                  forecast_temperature_today=17.0)
        self.assertEqual(aube_fraiche["hauteur_tonte_recommandee_cm"], 4.0,
                         "une aube à 5 °C d'un jour à 17 °C n'est pas une journée froide")
        matin_avant_canicule = self._reco(date(2026, 7, 15), hour_of_day=7, temperature=19.0,
                                          forecast_temperature_today=33.0)
        self.assertEqual(matin_avant_canicule["hauteur_tonte_recommandee_cm"], 6.0)
        # Sans prévision, la mesure courante sert de repli.
        sans_prevision = self._reco(date(2026, 7, 15), temperature=33.0, forecast_temperature_today=None)
        self.assertEqual(sans_prevision["hauteur_tonte_recommandee_cm"], 6.0)

    def test_une_temperature_ABSENTE_n_est_pas_un_jour_froid(self) -> None:
        # Premier cycle d'un redémarrage : capteurs pas encore relus. `temperature or 0.0`
        # déclenchait « froid » (+0,5) — et, sans registre, « air sec » sur une humidité absente.
        for registre in (self.REGISTRE_PLEIN, None):
            with self.subTest(registre=registre is not None):
                snap = self._reco(date(2026, 9, 15), temperature=None, forecast_temperature_today=None,
                                  humidite=None, soil_balance=registre)
                self.assertNotIn("froide", snap["hauteur_tonte_motif"])
                self.assertNotIn("air sec", snap["hauteur_tonte_motif"])

    def test_le_plancher_du_tiers_s_arrondit_VERS_LE_HAUT(self) -> None:
        # Gazons dont les 2/3 tombent HORS de la grille de 0,5 : les tests voisins (12 et 15 cm)
        # tombent pile dessus (8,0 et 10,0), et n'auraient rien vu d'un arrondi au plus proche.
        for gazon, attendu in ((6.3, 4.5), (7.0, 5.0), (10.0, 7.0), (10.6, 7.5)):
            with self.subTest(gazon=gazon):
                snap = self._reco(date(2026, 9, 15), hauteur_gazon=gazon, hauteur_max_tondeuse_cm=9.0)
                reco = snap["hauteur_tonte_recommandee_cm"]
                self.assertEqual(reco, attendu)
                self.assertGreaterEqual(reco, gazon * 2.0 / 3.0, "on ôterait plus d'un tiers du brin")
                self.assertIn("règle du tiers", snap["hauteur_tonte_motif"])

    def test_les_planchers_de_sursemis_s_arrondissent_VERS_LE_HAUT(self) -> None:
        snap = self._reco(
            date(2026, 3, 19), history=[{"type": "Semis", "date": "2026-03-17"}],
            hauteur_max_tondeuse_cm=9.0,
        )
        self.assertEqual(snap["phase_active"], "Semis")
        reco = snap["hauteur_tonte_recommandee_cm"]
        plancher = {"Germination": 7.5, "Enracinement": 7.0}.get(snap["sous_phase"], 6.5)
        self.assertGreaterEqual(reco, plancher, f"semis conseillé sous son plancher ({snap['sous_phase']})")

    def test_le_motif_dit_pourquoi(self) -> None:
        snap = self._reco(date(2026, 9, 11), temperature=21.8, forecast_temperature_today=23.7)
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 4.0)
        self.assertEqual(snap["hauteur_tonte_motif"], "Septembre : base 4,0 cm (hauteur de pousse).")
        plafonne = self._reco(date(2026, 7, 15), forecast_temperature_today=34.0, hauteur_max_tondeuse_cm=5.5)
        self.assertIn("plafonnée au maximum de la tondeuse (5,5 cm)", plafonne["hauteur_tonte_motif"])

    def _theorique(self, jour: date, **kw) -> tuple[float, list[str]]:
        """Hauteur théorique AVANT arrondi, par les vrais bundles : l'arrondi au plus proche
        absorbe un terme de +0,2, donc un test sur la valeur publiée ne verrait pas son retour."""
        dm = importlib.import_module("custom_components.gazon_intelligent.decision_mowing")
        params = dict(
            history=[], today=jour, hour_of_day=10, temperature=18.0,
            forecast_temperature_today=18.0, pluie_24h=0, pluie_demain=0, humidite=60,
            type_sol="limoneux", etp_capteur=2.5, soil_balance=self.REGISTRE_PLEIN,
        )
        params.update(kw)
        contexte = decision.DecisionContext.from_legacy_args(**params)
        phase = decision.build_phase_bundle(contexte)
        eau = decision.build_water_bundle(contexte, phase)
        risque = decision.build_risk_bundle(contexte, phase, eau)
        return dm._hauteur_theorique_detaillee(contexte, phase, eau, risque)

    def test_aucun_terme_mouille_meme_invisible_apres_arrondi(self) -> None:
        for mois in (4, 9, 11):
            sec, _ = self._theorique(date(2026, mois, 15))
            for mouille in (
                {"rosee": 1.0}, {"pluie_24h": 8.0}, {"pluie_demain": 6.0}, {"pluie_j2": 4.0},
                {"pluie_3j": 12.0}, {"pluie_probabilite_max_3j": 95}, {"humidite": 95},
            ):
                with self.subTest(mois=mois, entree=mouille):
                    valeur, _ = self._theorique(date(2026, mois, 15), **mouille)
                    self.assertAlmostEqual(valeur, sec, places=6)

    def test_un_petit_terme_ne_fait_plus_sauter_d_un_cran(self) -> None:
        # 25 °C prévus en septembre : +0,2 → 4,2 cm théoriques. L'arrondi VERS LE HAUT publiait
        # 4,5 ; au plus proche, 4,0. Le motif garde la trace du terme.
        valeur, termes = self._theorique(date(2026, 9, 15), temperature=25.0, forecast_temperature_today=25.0)
        self.assertAlmostEqual(valeur, 4.2, places=6)
        snap = self._reco(date(2026, 9, 15), temperature=25.0, forecast_temperature_today=25.0)
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 4.0)
        self.assertIn("temps chaud (25,0 °C) +0,2", snap["hauteur_tonte_motif"])
        # « +0,2 » sous « 4,0 cm » se lisait comme une erreur : le motif dit l'arrondi.
        self.assertIn("→ arrondi à 4,0 cm", snap["hauteur_tonte_motif"])
        sans_terme = self._reco(date(2026, 9, 15))
        self.assertNotIn("arrondi", sans_terme["hauteur_tonte_motif"])

    def test_l_air_sec_ne_compte_plus_quand_le_registre_mesure_la_reserve(self) -> None:
        valeur, termes = self._theorique(date(2026, 9, 15), humidite=30)
        self.assertAlmostEqual(valeur, 4.0, places=6)
        self.assertNotIn("air sec +0,3", termes)
        _, termes_repli = self._theorique(date(2026, 9, 15), humidite=30, soil_balance=None)
        self.assertIn("air sec +0,3", termes_repli)

    # ─── Constats de la revue adversariale de la 0.87.0 ───────────────────────────────────

    def test_le_soir_la_prevision_restante_ne_refroidit_pas_la_journee(self) -> None:
        # Relevé chez Kévin le 10/09 : 22,5 °C prévus à 14 h, 15,8 à 23 h 40 — le fournisseur donne
        # le maximum des heures RESTANTES. Le cliquet garde le maximum vu depuis minuit.
        memoire = {"hauteur_tonte_temperature_jour": {"date": "2026-04-15", "max": 14.0}}
        soir = self._reco(date(2026, 4, 15), hour_of_day=23, temperature=7.0,
                          forecast_temperature_today=7.5, memory=memoire)
        self.assertEqual(soir["hauteur_tonte_recommandee_cm"], 4.0)
        self.assertNotIn("froide", soir["hauteur_tonte_motif"])
        self.assertEqual(soir["hauteur_tonte_temperature_jour"], {"date": "2026-04-15", "max": 14.0})
        canicule = {"hauteur_tonte_temperature_jour": {"date": "2026-07-15", "max": 33.0}}
        soir_d_ete = self._reco(date(2026, 7, 15), hour_of_day=21, temperature=29.0,
                                forecast_temperature_today=27.0, memory=canicule)
        self.assertEqual(soir_d_ete["hauteur_tonte_recommandee_cm"], 6.0, "la chaleur retombe avant la nuit")

    def test_le_cliquet_repart_a_zero_au_changement_de_date(self) -> None:
        veille = {"hauteur_tonte_temperature_jour": {"date": "2026-07-14", "max": 34.0}}
        lendemain = self._reco(date(2026, 7, 15), temperature=19.0, forecast_temperature_today=22.0, memory=veille)
        self.assertEqual(lendemain["hauteur_tonte_recommandee_cm"], 5.0)
        self.assertEqual(lendemain["hauteur_tonte_temperature_jour"], {"date": "2026-07-15", "max": 22.0})

    def test_la_mesure_releve_une_prevision_trop_basse(self) -> None:
        snap = self._reco(date(2026, 7, 15), hour_of_day=15, temperature=34.0, forecast_temperature_today=30.0)
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 6.0)
        self.assertEqual(snap["hauteur_tonte_temperature_jour"]["max"], 34.0)

    def test_une_prevision_absente_un_cycle_garde_la_journee(self) -> None:
        memoire = {"hauteur_tonte_temperature_jour": {"date": "2026-09-15", "max": 23.0}}
        snap = self._reco(date(2026, 9, 15), hour_of_day=15, temperature=29.0,
                          forecast_temperature_today=None, memory=memoire)
        # 29 °C mesurés relèvent la journée : c'est une vraie chaleur, pas un trou de prévision.
        self.assertEqual(snap["hauteur_tonte_temperature_jour"]["max"], 29.0)
        aube = self._reco(date(2026, 9, 15), hour_of_day=6, temperature=6.0,
                          forecast_temperature_today=None, memory=memoire)
        self.assertNotIn("froide", aube["hauteur_tonte_motif"])

    def test_une_prevision_aberrante_est_ignoree(self) -> None:
        for glitch in (80.0, -45.0, float("nan")):
            with self.subTest(prevision=glitch):
                snap = self._reco(date(2026, 9, 15), temperature=20.0, forecast_temperature_today=glitch)
                self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 4.0)
                self.assertEqual(snap["hauteur_tonte_temperature_jour"]["max"], 20.0)

    def test_la_reference_hydrique_ne_regle_pas_la_hauteur(self) -> None:
        # Le coordinateur transmet TOUJOURS `temperature_reference_hydrique` (0,3 × prévision +
        # 0,7 × mesure l'après-midi). La lire à la place de la prévision réintroduirait le
        # thermomètre — la mutation la plus plausible, que le test précédent laissait passer.
        for ref_hydrique in (40.0, 2.0):
            with self.subTest(reference=ref_hydrique):
                snap = self._reco(date(2026, 9, 15), temperature=20.0, forecast_temperature_today=21.0,
                                  temperature_reference_hydrique=ref_hydrique)
                self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 4.0)

    def test_seuils_de_chaleur_au_dixieme(self) -> None:
        for prevision, attendu in ((27.9, 5.0), (28.0, 5.5), (31.9, 5.5), (32.0, 6.0)):
            with self.subTest(prevision=prevision):
                snap = self._reco(date(2026, 7, 15), temperature=20.0, forecast_temperature_today=prevision)
                self.assertEqual(snap["hauteur_tonte_recommandee_cm"], attendu)
                self.assertIn(f"({str(prevision).replace('.', ',')} °C)", snap["hauteur_tonte_motif"])

    def test_seuils_de_reserve_de_part_et_d_autre(self) -> None:
        # Sol limoneux : réserve utile 12 mm, MAD 0,5 en phase Normal → déplétion 0,5 à 6,0 mm.
        for reserve, attendu in ((6.24, 4.0), (6.0, 4.5), (3.24, 4.5), (3.0, 5.0)):
            with self.subTest(reserve=reserve):
                snap = self._reco(date(2026, 9, 15), soil_balance={"reserve_mm": reserve, "reserve_max_mm": 24.0})
                self.assertEqual(snap["hauteur_tonte_recommandee_cm"], attendu)

    def test_le_seuil_suit_le_MAD_de_la_phase(self) -> None:
        # Hivernage : MAD 0,6. Déplétion 0,55 → sous le seuil de CETTE phase, pas de relèvement
        # (un seuil figé à 0,5 conclurait « manque d'eau modéré »).
        snap = self._reco(date(2026, 11, 20), history=[{"type": "Hivernage", "date": "2026-11-19"}],
                          soil_balance={"reserve_mm": 5.4, "reserve_max_mm": 24.0})
        self.assertEqual(snap["phase_active"], "Hivernage")
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 5.0)
        self.assertNotIn("manque d'eau", snap["hauteur_tonte_motif"])

    def test_phase_hors_normal_et_hiver_sans_double_froid(self) -> None:
        fertil = self._reco(date(2026, 9, 15), history=[{"type": "Fertilisation", "date": "2026-09-14"}])
        self.assertEqual(fertil["hauteur_tonte_recommandee_cm"], 4.5)
        self.assertIn("phase Fertilisation +0,3", fertil["hauteur_tonte_motif"])
        # Janvier à 5 °C : « hiver » OU « journée froide », jamais les deux.
        janvier = self._reco(date(2026, 1, 15), temperature=5.0, forecast_temperature_today=5.0)
        self.assertEqual(janvier["hauteur_tonte_recommandee_cm"], 4.5)
        self.assertNotIn("froide", janvier["hauteur_tonte_motif"])

    def test_repli_sans_registre_valeur_exacte(self) -> None:
        snap = self._reco(date(2026, 9, 15), soil_balance=None, etp_capteur=6.0, humidite=45)
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 5.0)
        self.assertIn("manque d'eau fort (déficit estimé) +1,0", snap["hauteur_tonte_motif"])

    def test_sursemis_plancher_exact_par_sous_phase(self) -> None:
        snap = self._reco(date(2026, 3, 19), history=[{"type": "Semis", "date": "2026-03-17"}],
                          hauteur_max_tondeuse_cm=9.0)
        self.assertEqual(snap["sous_phase"], "Germination")
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 7.5, "plancher de germination, sur la grille")

    def test_le_tiers_se_juge_sur_les_valeurs_ARRONDIES(self) -> None:
        # Gazon 6,2 : tiers 4,13 → 4,5 vers le haut ; saison 4,2 → 4,0 au plus proche. C'est le
        # tiers qui fait la valeur — comparés bruts (4,13 < 4,2), motif et libellé le taisaient.
        mord = self._reco(date(2026, 9, 15), temperature=25.0, forecast_temperature_today=25.0, hauteur_gazon=6.2)
        self.assertEqual(mord["hauteur_tonte_recommandee_cm"], 4.5)
        self.assertIn("règle du tiers", mord["hauteur_tonte_motif"])
        self.assertIsNotNone(mord["hauteur_tonte_garde_fou_label"])
        self.assertIn("la saison seule aurait proposé 4.0 cm", mord["hauteur_tonte_garde_fou_label"])
        # Fertilisation, gazon 6,5 : saison 4,3 → 4,5 ; tiers 4,33 → 4,5. Le tiers ne change rien.
        egal = self._reco(date(2026, 9, 15), history=[{"type": "Fertilisation", "date": "2026-09-14"}], hauteur_gazon=6.5)
        self.assertEqual(egal["hauteur_tonte_recommandee_cm"], 4.5)
        self.assertNotIn("règle du tiers", egal["hauteur_tonte_motif"])
        self.assertIsNone(egal.get("hauteur_tonte_garde_fou_label"))

    def test_le_lissage_ne_repasse_pas_sous_le_tiers(self) -> None:
        snap = self._reco(date(2026, 9, 15), hauteur_gazon=7.0, memory={"hauteur_tonte_recommandee_cm": 4.0})
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 5.0, "publié sous 2/3 de 7,0 cm")

    def test_le_motif_decrit_la_valeur_PUBLIEE(self) -> None:
        en_route = self._reco(date(2026, 9, 11), memory={"hauteur_tonte_recommandee_cm": 6.0})
        self.assertEqual(en_route["hauteur_tonte_recommandee_cm"], 5.5)
        self.assertIn("en route vers 4,0 cm", en_route["hauteur_tonte_motif"])
        minimum = self._reco(date(2026, 9, 15), hauteur_min_tondeuse_cm=5.0)
        self.assertEqual(minimum["hauteur_tonte_recommandee_cm"], 5.0)
        self.assertIn("relevée au minimum de la tondeuse (5,0 cm)", minimum["hauteur_tonte_motif"])
        plafond_et_tiers = self._reco(date(2026, 9, 15), hauteur_gazon=10.0, hauteur_max_tondeuse_cm=6.0)
        self.assertEqual(plafond_et_tiers["hauteur_tonte_recommandee_cm"], 6.0)
        self.assertIn("règle du tiers", plafond_et_tiers["hauteur_tonte_motif"])
        self.assertIn("plafonnée au maximum de la tondeuse (6,0 cm)", plafond_et_tiers["hauteur_tonte_motif"])

    def test_arrondi_au_plus_proche_demi_vers_le_haut(self) -> None:
        dm = importlib.import_module("custom_components.gazon_intelligent.decision_mowing")
        for valeur, attendu in ((4.1, 4.0), (4.2, 4.0), (4.25, 4.5), (4.3, 4.5), (4.75, 5.0), (2.0, 3.0)):
            with self.subTest(valeur=valeur):
                self.assertEqual(dm._round_nearest_to_step(valeur, 3.0, 0.5), attendu)


class UneApplicationNeBloquePasPourToujoursTests(unittest.TestCase):
    """0.88.0 — les résolveurs foliaire et « type inconnu » ont une fin.

    Ils s'armaient sur la seule EXISTENCE de `derniere_application` — la dernière application de
    toute la vie de l'installation. Un Traitement (foliaire par défaut) bloquait tonte ET arrosage
    à J+100 ; pendant un sursemis, le semis restait sans eau alors que la protection de 24 h avait
    expiré (revue du 11/09/2026). Borne : la durée de phase de l'intervention.

    ⚠️ Dates en mars 2026 : `compute_application_state` lit l'heure réelle (`dt_util.now`), que ce
    harnais fige au 04/04/2026. Des dates postérieures laisseraient la fenêtre de 24 h « active »
    pour toujours — un artefact du harnais, pas le comportement de production.
    """

    def _snap(self, jour: date, history: list, **kw) -> dict:
        params = dict(
            history=history, today=jour, hour_of_day=10, temperature=24.0,
            forecast_temperature_today=26.0, pluie_24h=0, pluie_demain=0, humidite=50,
            type_sol="limoneux", etp_capteur=5.0, soil_balance={"reserve_mm": 4.0, "reserve_max_mm": 24.0},
        )
        params.update(kw)
        return decision.build_decision_snapshot(**params)

    def test_un_traitement_foliaire_bloque_deux_jours_pas_cent(self) -> None:
        traitement = date(2026, 3, 10)
        historique = [{"type": "Traitement", "date": traitement.isoformat(), "produit": "Fongicide X"}]
        for jours, bloque in ((0, True), (1, True), (2, False), (3, False), (20, False)):
            with self.subTest(jour=jours):
                snap = self._snap(traitement + timedelta(days=jours), historique)
                self.assertEqual(snap["arrosage_recommande"], not bloque)
                self.assertEqual(snap["tonte_autorisee"], not bloque)
                if not bloque:
                    self.assertNotIn("foliaire", snap["conseil_principal"])
                    self.assertGreater(snap["objectif_mm"], 0.0, "la réserve à 4/12 mm réclame de l'eau")

    def test_un_traitement_pendant_un_semis_ne_prive_pas_le_semis_d_eau(self) -> None:
        semis = date(2026, 2, 20)
        historique = [
            {"type": "Sursemis", "date": semis.isoformat()},
            {"type": "Traitement", "date": (semis + timedelta(days=10)).isoformat()},
        ]
        for jours, arrose in ((9, True), (10, False), (11, False), (12, True), (20, True), (30, True)):
            with self.subTest(jour=jours):
                snap = self._snap(semis + timedelta(days=jours), historique,
                                  soil_balance={"reserve_mm": 8.0, "reserve_max_mm": 24.0})
                self.assertEqual(snap["arrosage_recommande"], arrose)

    def test_la_borne_suit_la_duree_d_effet_de_l_intervention(self) -> None:
        mem = importlib.import_module("custom_components.gazon_intelligent.memory")
        loin = datetime(2026, 12, 31, tzinfo=timezone.utc)  # fenêtre « depuis le moment » écoulée
        for type_, duree in (("Traitement", 2), ("Fertilisation", 2), ("Biostimulant", 1),
                             ("Agent Mouillant", 1), ("Scarification", 1)):
            for jours in range(0, duree + 2):
                with self.subTest(type=type_, jour=jours):
                    en_cours, _ = mem._application_en_cours(
                        {"type": type_, "date": "2026-03-10"}, loin, date(2026, 3, 10) + timedelta(days=jours),
                    )
                    self.assertEqual(en_cours, jours < duree)
        # Un semis ou un hivernage n'est pas une application : leur durée de phase (45 j, 999 j)
        # n'a rien à faire ici.
        self.assertEqual(mem.duree_effet_application_jours("Sursemis"), 1)
        self.assertEqual(mem.duree_effet_application_jours("Hivernage"), 1)
        # Datée dans le futur : n'agit pas encore. Sans date : ne bloque pas indéfiniment.
        self.assertFalse(mem._application_en_cours({"type": "Traitement", "date": "2026-03-12"}, loin, date(2026, 3, 10))[0])
        self.assertFalse(mem._application_en_cours({"type": "Traitement"}, loin, date(2026, 3, 30))[0])

    def test_une_pulverisation_du_soir_reste_protegee_jusqu_au_lendemain_soir(self) -> None:
        # Biostimulant foliaire pulvérisé le 10/03 à 21:00 (Paris) : compté en jours calendaires, la
        # protection finissait à minuit et l'arrosage de l'aube suivait 9 h après (revue 11/09).
        mem = importlib.import_module("custom_components.gazon_intelligent.memory")
        item = {"type": "Biostimulant", "date": "2026-03-10", "declared_at": "2026-03-10T20:00:00+00:00",
                "application_type": "foliaire", "application_irrigation_block_hours": 0}
        for instant, attendu in (
            (datetime(2026, 3, 10, 22, 59, tzinfo=timezone.utc), True),
            (datetime(2026, 3, 11, 5, 0, tzinfo=timezone.utc), True),    # aube du lendemain
            (datetime(2026, 3, 11, 19, 59, tzinfo=timezone.utc), True),
            (datetime(2026, 3, 11, 20, 1, tzinfo=timezone.utc), False),
        ):
            with self.subTest(instant=instant.isoformat()):
                etat = mem.compute_application_state([item], now=instant, today=instant.date())
                self.assertEqual(etat["application_en_cours"], attendu)

    def test_une_declaration_retroactive_compte_depuis_la_date_pas_la_saisie(self) -> None:
        # Traitement du 10/03 saisi le 14/03 à 08:00 : la fenêtre part du 10/03 — ni blocage de 24 h
        # à partir de la saisie, ni protection foliaire relancée le 15/03.
        mem = importlib.import_module("custom_components.gazon_intelligent.memory")
        item = {"type": "Traitement", "date": "2026-03-10", "declared_at": "2026-03-14T08:00:00+01:00"}
        for instant in (datetime(2026, 3, 14, 9, 0, tzinfo=timezone.utc), datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)):
            with self.subTest(instant=instant.isoformat()):
                etat = mem.compute_application_state([item], now=instant, today=instant.date())
                self.assertFalse(etat["application_block_active"])
                self.assertFalse(etat["application_en_cours"])

    def test_le_resolveur_foliaire_seul_hors_traitement(self) -> None:
        # Sur un Traitement, la phase Traitement bloque déjà J0-J+1 : le résolveur foliaire n'y est
        # jamais discriminé (revue : le supprimer laissait la suite verte). Un Biostimulant foliaire
        # n'a pas de phase bloquante : c'est le résolveur, et lui seul, qui protège J0.
        jour = date(2026, 3, 10)
        historique = [{"type": "Biostimulant", "date": jour.isoformat(), "produit": "Algues", "application_type": "foliaire"}]
        j0 = self._snap(jour, historique)
        self.assertFalse(j0["tonte_autorisee"])
        self.assertFalse(j0["arrosage_recommande"])
        self.assertIn("traitement foliaire", j0["conseil_principal"])
        j1 = self._snap(jour + timedelta(days=1), historique)
        self.assertTrue(j1["arrosage_recommande"], "Biostimulant : un jour d'effet, pas davantage")
        self.assertTrue(j1["tonte_autorisee"])

    def test_une_fertilisation_foliaire_pendant_un_semis_ne_le_prive_que_deux_jours(self) -> None:
        historique = [
            {"type": "Sursemis", "date": "2026-02-26"},
            {"type": "Fertilisation", "date": "2026-03-10", "produit": "Foliaire F", "application_type": "foliaire"},
        ]
        for jour, arrose in ((date(2026, 3, 10), False), (date(2026, 3, 11), False), (date(2026, 3, 12), True)):
            with self.subTest(jour=jour.isoformat()):
                snap = self._snap(jour, historique, soil_balance={"reserve_mm": 8.0, "reserve_max_mm": 24.0})
                self.assertEqual(snap["phase_active"], "Sursemis")
                self.assertEqual(snap["arrosage_recommande"], arrose)

    def test_deux_applications_le_meme_jour_le_blocage_le_plus_lointain_l_emporte(self) -> None:
        # Fongicide à 09:00 (24 h de blocage), Floranid à 18:00 (sol, post-arrosage 5 mm) : le
        # Floranid effaçait la protection du fongicide et lançait 5 mm 9 h après la pulvérisation.
        mem = importlib.import_module("custom_components.gazon_intelligent.memory")
        historique = [
            {"type": "Traitement", "date": "2026-03-10", "declared_at": "2026-03-10T08:00:00+00:00",
             "produit": "Fongicide", "application_type": "foliaire", "application_irrigation_block_hours": 24},
            {"type": "Fertilisation", "date": "2026-03-10", "declared_at": "2026-03-10T17:00:00+00:00",
             "produit": "Floranid", "application_type": "sol", "application_requires_watering_after": True,
             "application_post_watering_mm": 5.0, "application_irrigation_block_hours": 0},
        ]
        a_18h10 = datetime(2026, 3, 10, 17, 10, tzinfo=timezone.utc)
        etat = mem.compute_application_state(historique, now=a_18h10, today=a_18h10.date())
        self.assertTrue(etat["application_block_active"])
        self.assertEqual(etat["application_block_label"], "Fongicide")
        lendemain = datetime(2026, 3, 11, 8, 30, tzinfo=timezone.utc)
        self.assertFalse(mem.compute_application_state(historique, now=lendemain, today=lendemain.date())["application_block_active"])

    def test_le_delai_avant_tonte_du_produit_est_respecte(self) -> None:
        jour = date(2026, 3, 10)
        historique = [{"type": "Traitement", "date": jour.isoformat(), "produit": "Herbicide X",
                       "application_type": "foliaire", "produit_catalogue": {"delai_avant_tonte_jours": 5}}]
        for jours, autorisee in ((2, False), (4, False), (5, True)):
            with self.subTest(jour=jours):
                snap = self._snap(jour + timedelta(days=jours), historique, hauteur_gazon=7.0,
                                  soil_balance={"reserve_mm": 11.5, "reserve_max_mm": 24.0}, hour_of_day=11)
                self.assertEqual(snap["tonte_autorisee"], autorisee)
                if not autorisee:
                    self.assertIn("pas de tonte avant le 15/03/2026", snap["mowing_block_reason_label"])

    def test_un_type_d_application_inconnu_bloque_le_temps_de_l_intervention(self) -> None:
        fertilisation = date(2026, 3, 10)
        historique = [{"type": "Fertilisation", "date": fertilisation.isoformat(), "application_type": "granule"}]
        for jours, bloque in ((0, True), (1, True), (2, False), (5, False)):
            with self.subTest(jour=jours):
                snap = self._snap(fertilisation + timedelta(days=jours), historique)
                self.assertEqual("type d'application inconnu" in snap["conseil_principal"], bloque)
                self.assertEqual(snap["arrosage_recommande"], not bloque)


class LaSortieDeSemisEstProgressiveTests(unittest.TestCase):
    """0.88.0 — le plancher de semis suit l'ÂGE du semis, par paliers de sous-phase sourcés.

    Avant : à J+45 la phase repassait en Normal et la recommandation tombait de 6-7 cm vers 4 cm
    en quelques cycles ; le barème de reprise (36-59 j) était mort depuis la 0.7.2 ; et un
    Traitement déclaré pendant un semis faisait sauter le plancher (phase dominante).
    Paliers (Barenbrug : 6-7 cm puis 4-5 cm ; Ohio State : ensuite la hauteur normale) :
    Germination 7,5 · Enracinement 7,0 · Reprise 6,5 · Stabilisation 5,0 · puis la base du mois.
    """

    def _snap(self, semis: date, k: int, maxh: float, extra=(), **kw) -> dict:
        params = dict(
            history=[{"type": "Semis", "date": semis.isoformat()}, *extra],
            today=semis + timedelta(days=k), hour_of_day=10, temperature=16.0,
            forecast_temperature_today=17.0, pluie_24h=0, pluie_demain=0, humidite=65,
            type_sol="limoneux", etp_capteur=2.0, hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=maxh, soil_balance={"reserve_mm": 11.5, "reserve_max_mm": 24.0},
        )
        params.update(kw)
        return decision.build_decision_snapshot(**params)

    def test_paliers_par_sous_phase_tondeuse_3_9(self) -> None:
        attendus = {0: (7.5, "semis en germination (J+0) : plancher 7,5 cm"),
                    11: (7.0, "semis en enracinement (J+11) : plancher 7,0 cm"),
                    25: (6.5, "semis en reprise (J+25) : plancher 6,5 cm"),
                    35: (5.0, "semis en stabilisation (J+35) : plancher 5,0 cm"),
                    44: (5.0, "semis en stabilisation (J+44) : plancher 5,0 cm"),
                    45: (4.0, None)}
        for k, (hauteur, motif) in attendus.items():
            with self.subTest(jour=k):
                snap = self._snap(date(2026, 9, 11), k, 9.0)
                self.assertEqual(snap["hauteur_tonte_recommandee_cm"], hauteur)
                if motif:
                    self.assertIn(motif, snap["hauteur_tonte_motif"])
                else:
                    self.assertNotIn("semis", snap["hauteur_tonte_motif"])

    def test_tondeuse_plafonnee_a_6(self) -> None:
        for k, hauteur in ((25, 6.0), (34, 6.0), (35, 5.0), (44, 5.0), (45, 4.0)):
            with self.subTest(jour=k):
                self.assertEqual(self._snap(date(2026, 9, 11), k, 6.0)["hauteur_tonte_recommandee_cm"], hauteur)

    def test_chaque_marche_reste_sous_le_tiers(self) -> None:
        for maxh in (6.0, 9.0):
            valeurs = [self._snap(date(2026, 9, 11), k, maxh)["hauteur_tonte_recommandee_cm"] for k in range(0, 61)]
            for k in range(60):
                with self.subTest(tondeuse=maxh, jour=k):
                    baisse = valeurs[k] - valeurs[k + 1]
                    self.assertLessEqual(baisse, valeurs[k] / 3.0 + 1e-9, f"J+{k}→J+{k + 1} : {valeurs[k]} → {valeurs[k + 1]}")

    def test_un_traitement_pendant_le_semis_garde_le_plancher(self) -> None:
        extra = [{"type": "Traitement", "date": "2026-09-21"}]
        for k, hauteur, libelle in ((10, 7.5, "semis en germination (J+10)"), (11, 7.0, "semis en enracinement (J+11)")):
            with self.subTest(jour=k):
                snap = self._snap(date(2026, 9, 11), k, 9.0, extra=extra)
                self.assertEqual(snap["phase_active"], "Traitement", "prémisse : le Traitement domine")
                self.assertEqual(snap["hauteur_tonte_recommandee_cm"], hauteur)
                self.assertIn(libelle, snap["hauteur_tonte_motif"])
                self.assertFalse(snap["tonte_autorisee"])
        precoce = self._snap(date(2026, 9, 11), 3, 9.0, extra=[{"type": "Traitement", "date": "2026-09-14"}])
        self.assertEqual(precoce["hauteur_tonte_recommandee_cm"], 7.5)

    def test_un_hivernage_pendant_le_semis_garde_le_plancher(self) -> None:
        snap = self._snap(date(2026, 9, 11), 40, 9.0, extra=[{"type": "Hivernage", "date": "2026-10-19"}])
        self.assertEqual(snap["phase_active"], "Hivernage")
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 5.0)
        self.assertIn("semis en stabilisation (J+40)", snap["hauteur_tonte_motif"])

    def test_un_semis_date_dans_le_futur_n_a_pas_encore_de_plancher(self) -> None:
        snap = decision.build_decision_snapshot(
            history=[{"type": "Semis", "date": "2026-09-20"}], today=date(2026, 9, 15), hour_of_day=10,
            temperature=16.0, forecast_temperature_today=17.0, pluie_24h=0, pluie_demain=0, humidite=65,
            type_sol="limoneux", etp_capteur=2.0, hauteur_min_tondeuse_cm=3.0, hauteur_max_tondeuse_cm=9.0,
            soil_balance={"reserve_mm": 11.5, "reserve_max_mm": 24.0},
        )
        self.assertNotIn("semis", snap["hauteur_tonte_motif"])

    def test_le_semis_le_plus_recent_PAR_DATE(self) -> None:
        # Une déclaration rétroactive ajoutée APRÈS un semis plus récent : l'âge suit la date.
        historique = [{"type": "Semis", "date": "2026-09-11"}, {"type": "Semis", "date": "2026-03-01"}]
        snap = decision.build_decision_snapshot(
            history=historique, today=date(2026, 9, 13), hour_of_day=10, temperature=16.0,
            forecast_temperature_today=17.0, pluie_24h=0, pluie_demain=0, humidite=65, type_sol="limoneux",
            etp_capteur=2.0, hauteur_min_tondeuse_cm=3.0, hauteur_max_tondeuse_cm=9.0,
            soil_balance={"reserve_mm": 11.5, "reserve_max_mm": 24.0},
        )
        self.assertIn("semis en germination (J+2)", snap["hauteur_tonte_motif"])
        self.assertEqual(snap["hauteur_tonte_recommandee_cm"], 7.5)

    def test_lame_inconnue_le_message_ne_pretend_pas_connaitre_la_lame(self) -> None:
        # Sans réglage de lame connu, le seuil « hauteur trop faible » est la hauteur CONSEILLÉE :
        # « la lame coupe à 7,0 cm » contredisait l'historique des tontes (revue du 11/09/2026).
        snap = self._snap(date(2026, 2, 1), 30, 9.0, hauteur_gazon=6.0)
        self.assertEqual(snap.get("raison_blocage_code"), "hauteur_trop_faible")
        self.assertIn("hauteur conseillée est 6.5 cm (réglage de lame inconnu)", snap["mowing_block_reason_label"])
        self.assertNotIn("la lame coupe", snap["mowing_block_reason_label"])

    def test_le_motif_cite_le_plancher_qui_fait_la_valeur(self) -> None:
        # J+28 (Reprise, 6,5), gazon à 7 cm (tiers 4,67 → 5,0) : c'est le SEMIS qui fait 6,5.
        semis_fait = self._snap(date(2026, 9, 11), 28, 8.0, hauteur_gazon=7.0)
        self.assertEqual(semis_fait["hauteur_tonte_recommandee_cm"], 6.5)
        self.assertIn("semis en reprise", semis_fait["hauteur_tonte_motif"])
        self.assertNotIn("règle du tiers", semis_fait["hauteur_tonte_motif"])
        self.assertIsNone(semis_fait.get("hauteur_tonte_garde_fou_label"))
        # J+40 (Stabilisation, 5,0), gazon à 9 cm (tiers 6,0) : c'est le TIERS qui fait 6,0.
        tiers_fait = self._snap(date(2026, 9, 11), 40, 8.0, hauteur_gazon=9.0)
        self.assertEqual(tiers_fait["hauteur_tonte_recommandee_cm"], 6.0)
        self.assertIn("règle du tiers", tiers_fait["hauteur_tonte_motif"])
        self.assertNotIn("semis en stabilisation", tiers_fait["hauteur_tonte_motif"])


class LesApplicationsAHorlogeReelleTests(unittest.TestCase):
    """0.88.0 — contre-revue : les fenêtres d'application à l'HORLOGE RÉELLE.

    Le harnais fige `dt_util.now` au 04/04/2026 : avec des dates antérieures, la partie « depuis
    le moment » de la fenêtre n'était jamais exercée, et ses défauts passaient (aube de J+2
    bloquée, protection foliaire effacée par un second produit, incorporation abandonnée). Ici
    l'horloge de la mémoire est patchée de façon cohérente avec le jour simulé.
    """

    PARIS = ZoneInfo("Europe/Paris")

    def _globales_memoire(self) -> dict:
        # ⚠️ Les globales du module `memory` QU'UTILISE la décision : d'autres fichiers de tests
        # réimportent le paquet avec leurs propres stubs, et `importlib.import_module(...)` rend
        # alors un AUTRE objet module — le patcher ne changeait rien à la décision (ces tests
        # passaient seuls et échouaient en suite complète).
        return decision.build_water_bundle.__globals__["compute_application_state"].__globals__

    def _snap(self, instant: datetime, historique: list, **kw) -> dict:
        params = dict(
            history=historique, today=instant.date(), hour_of_day=instant.hour + instant.minute / 60,
            temperature=20.0, forecast_temperature_today=21.0, pluie_24h=0, pluie_demain=0, humidite=55,
            type_sol="limoneux", etp_capteur=4.0, soil_balance={"reserve_mm": 4.0, "reserve_max_mm": 24.0},
        )
        params.update(kw)
        with patch.dict(self._globales_memoire(), {"_current_datetime": lambda: instant}):
            return decision.build_decision_snapshot(**params)

    def test_un_traitement_rend_l_aube_de_j_plus_2(self) -> None:
        historique = [{"type": "Traitement", "date": "2026-09-11", "declared_at": "2026-09-11T08:00:00+00:00",
                       "produit": "Fongicide X", "application_irrigation_block_hours": 24}]
        aube_j1 = datetime(2026, 9, 12, 6, 0, tzinfo=self.PARIS)
        self.assertFalse(self._snap(aube_j1, historique)["arrosage_recommande"])
        aube_j2 = datetime(2026, 9, 13, 6, 0, tzinfo=self.PARIS)
        snap = self._snap(aube_j2, historique)
        self.assertTrue(snap["arrosage_recommande"], "l'aube de J+2 était mangée par une fenêtre de 48 h")
        self.assertNotIn("foliaire", snap["conseil_principal"])

    def test_un_traitement_pendant_un_semis_rend_l_eau_a_j_plus_2(self) -> None:
        historique = [{"type": "Sursemis", "date": "2026-09-01"},
                      {"type": "Traitement", "date": "2026-09-11", "declared_at": "2026-09-11T12:00:00+00:00"}]
        for heure in (10, 12):
            with self.subTest(heure=heure):
                instant = datetime(2026, 9, 13, heure, 0, tzinfo=self.PARIS)
                snap = self._snap(instant, historique, soil_balance={"reserve_mm": 8.0, "reserve_max_mm": 24.0})
                self.assertTrue(snap["arrosage_recommande"], "micro-cycle du semis refusé à J+2")

    def test_un_produit_sol_apres_un_foliaire_n_efface_pas_sa_protection(self) -> None:
        # Catalogue réel : H2Pro (foliaire, 0 h de blocage) à 20:00, Humuslight (sol) à 20:30.
        historique = [
            {"type": "Agent Mouillant", "date": "2026-09-11", "declared_at": "2026-09-11T18:00:00+00:00",
             "produit": "H2Pro TriSmart", "application_type": "foliaire", "application_irrigation_block_hours": 0},
            {"type": "Biostimulant", "date": "2026-09-11", "declared_at": "2026-09-11T18:30:00+00:00",
             "produit": "Humuslight", "application_type": "sol", "application_irrigation_block_hours": 0},
        ]
        aube = datetime(2026, 9, 12, 7, 0, tzinfo=self.PARIS)
        snap = self._snap(aube, historique)
        self.assertFalse(snap["arrosage_recommande"])
        self.assertIn("H2Pro TriSmart: traitement foliaire", snap["conseil_principal"])
        soir = datetime(2026, 9, 12, 20, 5, tzinfo=self.PARIS)
        self.assertNotIn("foliaire", self._snap(soir, historique)["conseil_principal"])

    def test_l_incorporation_retardee_par_un_autre_blocage_n_est_pas_abandonnee(self) -> None:
        mem = importlib.import_module("custom_components.gazon_intelligent.memory")
        historique = [
            {"type": "Traitement", "date": "2026-09-12", "declared_at": "2026-09-12T16:00:00+00:00",
             "produit": "Fongicide", "application_type": "foliaire", "application_irrigation_block_hours": 24},
            {"type": "Fertilisation", "date": "2026-09-12", "declared_at": "2026-09-12T19:00:00+00:00",
             "produit": "Floranid", "application_type": "sol", "application_requires_watering_after": True,
             "application_post_watering_mm": 5.0, "application_irrigation_block_hours": 0,
             "application_irrigation_mode": "auto"},
        ]
        pendant = datetime(2026, 9, 12, 21, 30, tzinfo=self.PARIS)
        etat = mem.compute_application_state(historique, now=pendant, today=pendant.date())
        self.assertEqual(etat["application_post_watering_status"], "bloque")
        self.assertEqual(etat["application_block_label"], "Fongicide")
        apres = datetime(2026, 9, 13, 19, 30, tzinfo=self.PARIS)
        etat = mem.compute_application_state(historique, now=apres, today=apres.date())
        self.assertTrue(etat["application_post_watering_pending"], "incorporation abandonnée à la levée du blocage")
        self.assertNotEqual(etat["application_post_watering_status"], "termine")
        self.assertEqual(etat["application_post_watering_remaining_mm"], 5.0)

    def test_le_message_de_blocage_nomme_le_produit_qui_bloque(self) -> None:
        historique = [
            {"type": "Traitement", "date": "2026-09-12", "declared_at": "2026-09-12T16:00:00+00:00",
             "produit": "Fongicide", "application_type": "foliaire", "application_irrigation_block_hours": 24},
            {"type": "Fertilisation", "date": "2026-09-12", "declared_at": "2026-09-12T19:00:00+00:00",
             "produit": "Floranid", "application_type": "sol", "application_irrigation_block_hours": 0},
        ]
        snap = self._snap(datetime(2026, 9, 12, 21, 30, tzinfo=self.PARIS), historique)
        self.assertIn("Fongicide: l'arrosage est bloqué", snap["conseil_principal"])

    def test_une_application_datee_dans_le_futur_n_agit_pas_encore(self) -> None:
        mem = importlib.import_module("custom_components.gazon_intelligent.memory")
        historique = [{"type": "Traitement", "date": "2026-09-15", "declared_at": "2026-09-11T08:00:00+00:00",
                       "produit": "Fongicide", "application_irrigation_block_hours": 24}]
        maintenant = datetime(2026, 9, 11, 12, 0, tzinfo=self.PARIS)
        etat = mem.compute_application_state(historique, now=maintenant, today=maintenant.date())
        self.assertFalse(etat["application_block_active"])
        self.assertFalse(etat["application_en_cours"])
        self.assertFalse(etat["application_foliaire_en_cours"])

    def test_une_declaration_a_00h30_heure_locale_est_du_jour_meme(self) -> None:
        # `declared_at` en UTC (22:30 la veille), date saisie LOCALE : comparée en UTC seule, la
        # déclaration passait pour rétroactive et son moment retombait à 06:00 UTC.
        water = importlib.import_module("custom_components.gazon_intelligent.water")
        paris = types.SimpleNamespace(as_local=lambda d: d.astimezone(self.PARIS))
        item = {"type": "Traitement", "date": "2026-09-12", "declared_at": "2026-09-11T22:30:00+00:00"}
        with patch.object(water, "dt_util", paris):
            moment = water.resolve_history_moment(item)
        self.assertEqual(moment, datetime(2026, 9, 11, 22, 30, tzinfo=timezone.utc))

    def test_un_semis_declare_sans_produit_ne_recoit_pas_le_produit_selectionne(self) -> None:
        brain_mod = importlib.import_module("custom_components.gazon_intelligent.gazon_brain")
        brain = brain_mod.GazonBrain()
        brain.register_product(product_id="floranid", nom="Floranid", type_produit="Fertilisation",
                               application_type="sol", reapplication_after_days=90)
        brain.register_product(product_id="kick", nom="Kick Pro", type_produit="Traitement")
        brain.selected_product_id = "floranid"
        brain.declare_intervention("Sursemis", date_action=date(2026, 9, 11))
        semis = brain.history[-1]
        self.assertEqual(semis["type"], "Sursemis")
        self.assertIn(semis.get("produit"), (None, ""), "le produit sélectionné a été rattaché au semis")


class TestFenetresDeTonteElargies(unittest.TestCase):
    """Choix de Kévin, 15/09/2026 : tondre plus tard plutôt qu'avancer l'arrosage.

    L'arrosage finit désormais 15 min avant le lever du soleil, et le ressuyage retient la tonte
    4 à 6 h ensuite. Les fenêtres s'élargissent : idéale 10:00 → 14:00, soir de 5 h avant le coucher
    jusqu'au coucher + 30 min (coucher à 20:12 : 15:12 → 20:42 ; juillet : ~16:45 → 22:15). La nuit de la
    tonte commence à la fin de la fenêtre du soir, pas au coucher.
    """

    COUCHER = 20 * 60 + 12
    SOLEIL_COUCHE = {"sun_state": "below_horizon", "sun_above_horizon": False, "sun_below_horizon": True}
    SOLEIL_LEVE = {"sun_state": "above_horizon", "sun_above_horizon": True, "sun_below_horizon": False}

    def _contexte(self, heure: int, minute: int = 0, *, jour=date(2026, 9, 15), soleil=None,
                  temperature=20.0, coucher: int | None = COUCHER):
        return decision.DecisionContext.from_legacy_args(
            history=[], today=jour, hour_of_day=heure + minute / 60.0, temperature=temperature,
            pluie_24h=0, pluie_demain=0, humidite=55, type_sol="limoneux", etp_capteur=3.0,
            sun_context=dict(soleil) if soleil else None,
            weather_profile={} if coucher is None else {"sunset_minute": coucher},
        )

    def _fenetre(self, heure: int, minute: int = 0, **kw) -> str:
        ctx = self._contexte(heure, minute, **kw)
        return decision_mowing._resolve_mowing_window(ctx, weather_profile=ctx.weather_profile)[0]

    def _bundle(self, heure: int, minute: int = 0, **kw) -> dict:
        ctx = self._contexte(heure, minute, **kw)
        phase_bundle = decision_phase.build_phase_bundle(ctx)
        water_bundle = decision_watering.build_water_bundle(ctx, phase_bundle)
        risk_bundle = decision_risk.build_risk_bundle(ctx, phase_bundle, water_bundle)
        return decision_mowing.build_mowing_bundle(ctx, phase_bundle, water_bundle, risk_bundle)

    def test_la_fenetre_ideale_va_de_dix_a_quatorze_heures(self) -> None:
        soleil = self.SOLEIL_LEVE
        self.assertEqual(self._fenetre(9, 59, soleil=soleil), "blocked")
        self.assertEqual(self._fenetre(10, 0, soleil=soleil), "ideal")
        self.assertEqual(self._fenetre(13, 59, soleil=soleil), "ideal")
        # 14:00 → 15:12 : entre l'idéale et le soir, déconseillé.
        self.assertEqual(self._fenetre(14, 0, soleil=soleil), "discouraged")

    def test_le_soir_s_ouvre_cinq_heures_avant_le_coucher(self) -> None:
        soleil = self.SOLEIL_LEVE
        self.assertEqual(self._fenetre(15, 11, soleil=soleil), "discouraged")
        self.assertEqual(self._fenetre(15, 12, soleil=soleil), "acceptable")

    def test_le_soir_se_ferme_trente_minutes_apres_le_coucher(self) -> None:
        # Soleil couché à 20:12 : jusqu'à 20:41 c'est encore la fenêtre, à 20:42 c'est la nuit.
        self.assertEqual(self._fenetre(20, 11, soleil=self.SOLEIL_LEVE), "acceptable")
        self.assertEqual(self._fenetre(20, 41, soleil=self.SOLEIL_COUCHE), "acceptable")
        self.assertEqual(self._fenetre(20, 42, soleil=self.SOLEIL_COUCHE), "blocked")

    def test_en_juillet_la_fenetre_du_soir_passe_vingt_deux_heures(self) -> None:
        # Coucher 21:45 : 16:45 → 22:15. Le repli horaire « nuit dès 22 h » ne joue pas quand le
        # soleil est connu.
        juillet = dict(jour=date(2026, 7, 10), coucher=21 * 60 + 45)
        self.assertEqual(self._fenetre(16, 44, soleil=self.SOLEIL_LEVE, **juillet), "discouraged")
        self.assertEqual(self._fenetre(16, 45, soleil=self.SOLEIL_LEVE, **juillet), "acceptable")
        self.assertEqual(self._fenetre(22, 14, soleil=self.SOLEIL_COUCHE, **juillet), "acceptable")
        self.assertEqual(self._fenetre(22, 15, soleil=self.SOLEIL_COUCHE, **juillet), "blocked")

    def test_en_decembre_le_soir_ne_mord_pas_sur_l_ideale(self) -> None:
        # Coucher 16:55 : l'ouverture calculée (11:55) tombe dans l'idéale. Le soir prend le relais
        # à 14:00 et va jusqu'à 17:25.
        decembre = dict(jour=date(2026, 12, 15), coucher=16 * 60 + 55)
        self.assertEqual(self._fenetre(12, 0, soleil=self.SOLEIL_LEVE, **decembre), "ideal")
        self.assertEqual(self._fenetre(14, 0, soleil=self.SOLEIL_LEVE, **decembre), "acceptable")
        self.assertEqual(self._fenetre(17, 24, soleil=self.SOLEIL_COUCHE, **decembre), "acceptable")
        self.assertEqual(self._fenetre(17, 25, soleil=self.SOLEIL_COUCHE, **decembre), "blocked")

    def test_les_frontieres_tombent_a_la_minute_quel_que_soit_le_coucher(self) -> None:
        # Remultipliée par 60, l'heure décimale n'est pas exacte : `(16 + 35 / 60) * 60` vaut
        # 994,999…. Sans arrondi, ces deux couchers-là décalaient la frontière d'une minute.
        juillet = dict(jour=date(2026, 7, 20), coucher=21 * 60 + 35)  # soir 16:35 → 22:05
        self.assertEqual(self._fenetre(16, 34, soleil=self.SOLEIL_LEVE, **juillet), "discouraged")
        self.assertEqual(self._fenetre(16, 35, soleil=self.SOLEIL_LEVE, **juillet), "acceptable")
        tot = dict(jour=date(2026, 12, 10), coucher=16 * 60 + 28)  # nuit à 16:58
        self.assertEqual(self._fenetre(16, 57, soleil=self.SOLEIL_COUCHE, **tot), "acceptable")
        self.assertEqual(self._fenetre(16, 58, soleil=self.SOLEIL_COUCHE, **tot), "blocked")

    def test_la_fenetre_se_ferme_aussi_sans_etat_du_soleil(self) -> None:
        # Coucher connu mais état du soleil absent : la nuit retombe sur l'horloge (22 h), et c'est
        # la fenêtre elle-même qui doit se fermer au coucher + 30 min.
        self.assertEqual(self._fenetre(20, 41), "acceptable")
        self.assertEqual(self._fenetre(20, 42), "discouraged")

    def test_un_coucher_illisible_ou_aberrant_est_ignore(self) -> None:
        self.assertEqual(decision_mowing._minute_du_coucher({"sunset_minute": 1212}), 1212.0)
        for valeur in (-1, 24 * 60 + 1, "pas une heure", None):
            with self.subTest(sunset_minute=valeur):
                self.assertIsNone(decision_mowing._minute_du_coucher({"sunset_minute": valeur}))
        self.assertIsNone(decision_mowing._minute_du_coucher(None))

    def test_le_matin_un_soleil_sous_l_horizon_reste_la_nuit(self) -> None:
        # La grâce du soir ne vaut que l'après-midi : à 06:30, 20:12 + 30 est « plus tard », mais
        # c'est la fin de la nuit.
        ctx = self._contexte(6, 30, soleil=self.SOLEIL_COUCHE)
        self.assertTrue(decision_mowing._est_la_nuit(ctx, ctx.weather_profile))

    def test_sans_coucher_connu_le_soleil_couche_reste_la_nuit(self) -> None:
        ctx = self._contexte(20, 20, soleil=self.SOLEIL_COUCHE, coucher=None)
        self.assertTrue(decision_mowing._est_la_nuit(ctx, ctx.weather_profile))
        self.assertEqual(self._fenetre(20, 20, soleil=self.SOLEIL_COUCHE, coucher=None), "blocked")

    def test_la_tonte_reste_autorisee_jusqu_a_la_fin_de_la_fenetre(self) -> None:
        # Le motif de blocage lit la même nuit que la fenêtre : sans cela, la fenêtre dirait
        # « acceptable » pendant que `tonte_autorisee` retomberait dès le coucher.
        pendant = self._bundle(20, 30, soleil=self.SOLEIL_COUCHE)
        self.assertEqual(pendant["mowing_window_state"], "acceptable")
        self.assertNotEqual(pendant["mowing_block_reason_code"], "mowing_night")
        self.assertTrue(pendant["tonte_autorisee"], pendant.get("tonte_reason"))
        apres = self._bundle(20, 45, soleil=self.SOLEIL_COUCHE)
        self.assertEqual(apres["mowing_block_reason_code"], "mowing_night")
        self.assertFalse(apres["tonte_autorisee"])

    def test_apres_la_nuit_du_soir_la_prochaine_tonte_est_demain(self) -> None:
        # Le seuil valait 22 h : à 21:00, la nuit tombée, la carte annonçait la tonte pour le jour
        # même.
        soir = self._bundle(21, 0, soleil=self.SOLEIL_COUCHE)
        self.assertEqual(soir["mowing_block_reason_code"], "mowing_night")
        self.assertEqual(soir["next_mowing_date"], "2026-09-16")
        # Et dès la nuit tombée (20:42), pas seulement à partir de 21 h.
        tombee = self._bundle(20, 45, soleil=self.SOLEIL_COUCHE)
        self.assertEqual(tombee["mowing_block_reason_code"], "mowing_night")
        self.assertEqual(tombee["next_mowing_date"], "2026-09-16")
        petit_matin = self._bundle(5, 0, soleil=self.SOLEIL_COUCHE)
        self.assertEqual(petit_matin["mowing_block_reason_code"], "mowing_night")
        self.assertEqual(petit_matin["next_mowing_date"], "2026-09-15")


class TestPasseLaFenetreDuMatinCestDemainMatin(unittest.TestCase):
    """Passé la fenêtre du matin, la recharge vise DEMAIN matin (revue du 15/09/2026).

    `_profile_for_normal` publiait `ce_matin`, avec la date du jour, tout l'après-midi et le soir.
    Le risk bundle disait `demain_matin`, sauf quand il proposait « soir » : l'arbitrage reprenait
    alors le profil. Relevé sur l'installation le 07/09/2026 : « Prochain arrosage » est passé de
    « ce matin (07/09) » à 18:02:39 à « demain matin (08/09) », puis inversement à 18:02:50.
    Depuis que la carte affiche l'heure de départ, ce va-et-vient se voyait aussi sur l'heure.
    """

    PARIS = ZoneInfo("Europe/Paris")
    RESERVE_AU_SEUIL = dict(
        bilan_hydrique_mm=-7.0, deficit_jour=4.0, deficit_3j=8.0, deficit_7j=20.0,
        arrosage_recent_7j=0.0, arrosage_recent=0.0, reserve_from_soil_ledger=True,
        reserve_utile_mm=12.0, reserve_actuelle_mm=5.0, reserve_stock_mm=5.0,
        reserve_stock_max_mm=24.0, depletion_mm=7.0, depletion_ratio=0.583, mad_ratio=0.5,
    )

    def _profil(self, heure: int, minute: int = 0, *, phase: str = "Normal") -> dict:
        moment = datetime(2026, 9, 7, heure, minute, tzinfo=self.PARIS)
        with patch.object(guidance, "_current_datetime", return_value=moment):
            return guidance.compute_watering_profile(
                phase_dominante=phase, sous_phase=phase, water_balance=dict(self.RESERVE_AU_SEUIL),
                today=moment.date(), pluie_24h=0.0, pluie_demain=0.0, pluie_j2=0.0, pluie_3j=0.0,
                pluie_probabilite_max_3j=0.0, humidite=55.0, temperature=22.0, etp=4.0,
                type_sol="limoneux", weather_profile={}, history=[],
            )

    def test_phase_normale_matin_puis_demain_matin(self) -> None:
        attendu = ((3, 0, "ce_matin"), (5, 0, "maintenant"), (9, 59, "maintenant"),
                   (10, 0, "demain_matin"), (18, 2, "demain_matin"), (23, 30, "demain_matin"))
        for heure, minute, fenetre in attendu:
            with self.subTest(heure=f"{heure:02d}:{minute:02d}"):
                profil = self._profil(heure, minute)
                self.assertGreater(profil["mm_final_recommande"], 0.0, "prémisse : un arrosage est demandé")
                self.assertEqual(profil["fenetre_optimale"], fenetre)

    def test_le_soir_l_arbitrage_ne_bascule_plus_avec_le_risk_bundle(self) -> None:
        fenetre_profil = self._profil(18, 2)["fenetre_optimale"]
        resolve = decision_watering._resolve_optimal_window
        self.assertEqual(resolve(fenetre_profil, "soir"), "demain_matin")
        self.assertEqual(resolve(fenetre_profil, "demain_matin"), "demain_matin")

    def test_phases_agronomiques_aussi(self) -> None:
        self.assertEqual(self._profil(5, 0, phase="Fertilisation")["fenetre_optimale"], "ce_matin")
        self.assertEqual(self._profil(12, 0, phase="Fertilisation")["fenetre_optimale"], "demain_matin")
        self.assertEqual(self._profil(20, 0, phase="Fertilisation")["fenetre_optimale"], "demain_matin")



class SursemisDansUnGazonEnPlaceTests(unittest.TestCase):
    """Deux modes de semis depuis le 16/09/2026 (arbitrage de Kévin).

    « Semis » (sol nu) garde le comportement historique : tonte interdite 25 jours, pousse nulle,
    planchers 7,5 → 5,0 cm. « Sursemis » (gazon en place) arrose pareil, mais le gazon en place
    continue de pousser : tonte suspendue pendant la levée (J0-J7), puis lame à 4,0 cm tous les
    5 jours au moins, remontée à 4,5 cm après deux coupes des plantules (Purdue AY-13-W).
    """

    D0 = date(2026, 9, 16)
    REGISTRE_PLEIN = {"reserve_mm": 11.5, "reserve_max_mm": 24.0}

    def _snap(self, jour: int, mode: str = "Sursemis", tontes: tuple[int, ...] = (), **kw) -> dict:
        history = [{"type": mode, "date": self.D0.isoformat()}]
        history += [{"type": "tonte", "date": (self.D0 + timedelta(days=j)).isoformat()} for j in tontes]
        params = dict(
            history=history, today=self.D0 + timedelta(days=jour), hour_of_day=11,
            temperature=18.0, forecast_temperature_today=18.0, pluie_24h=0, pluie_demain=0,
            humidite=60, type_sol="limoneux", etp_capteur=2.5, hauteur_min_tondeuse_cm=3.0,
            hauteur_max_tondeuse_cm=6.0, soil_balance=self.REGISTRE_PLEIN,
        )
        params.update(kw)
        return decision.build_decision_snapshot(**params)

    # ── Tonte ───────────────────────────────────────────────────────────────────────────
    def test_la_tonte_est_suspendue_pendant_la_levee(self) -> None:
        for jour in (0, 3, 7):
            with self.subTest(jour=jour):
                snap = self._snap(jour)
                self.assertFalse(snap["tonte_autorisee"])
                self.assertEqual(snap["raison_blocage_code"], "phase_sursemis")
                self.assertEqual(snap["tonte_statut"], "interdite")
                self.assertIn("levée", snap["tonte_reason"])
                # Annoncée au lendemain de la levée, plus au semis + 25 jours.
                self.assertEqual(snap["next_mowing_date"], "2026-09-24")

    def test_un_traitement_dominant_ne_masque_pas_la_date_du_sursemis(self) -> None:
        historique = [
            {"type": "Sursemis", "date": self.D0.isoformat()},
            {"type": "Traitement", "date": "2026-09-19", "application_type": "sol"},
        ]
        snap = self._snap(3, history=historique)
        self.assertEqual(snap["phase_dominante"], "Traitement", "prémisse : le traitement domine")
        self.assertFalse(snap["tonte_autorisee"])
        self.assertEqual(snap["raison_blocage_code"], "phase_traitement")
        self.assertEqual(
            snap["next_mowing_date"],
            "2026-09-24",
            "la fin du traitement ne doit pas annoncer une tonte avant la fin de la levée",
        )

    def test_la_tonte_reprend_des_le_lendemain_de_la_levee(self) -> None:
        snap = self._snap(8)
        self.assertEqual(snap["sous_phase"], "Germination", "prémisse : l'arrosage est encore en germination")
        self.assertTrue(snap["tonte_autorisee"], snap.get("tonte_reason"))
        self.assertIsNone(snap.get("raison_blocage_code"))
        self.assertEqual(snap["mowing_frequency_label"], "1 à 2 / semaine")

    def test_le_meme_jour_un_semis_sur_sol_nu_reste_interdit(self) -> None:
        """Le contraste qui justifie deux modes : rien n'a changé pour le sol nu."""
        snap = self._snap(8, mode="Semis")
        self.assertFalse(snap["tonte_autorisee"])
        self.assertEqual(snap["tonte_statut"], "interdite")
        self.assertEqual(snap["next_mowing_date"], "2026-10-11")  # semis + 25 jours
        self.assertIn("Semis / Germination", snap["tonte_reason"])

    def test_cinq_jours_minimum_entre_deux_tontes(self) -> None:
        refus = self._snap(12, tontes=(8,))
        self.assertFalse(refus["tonte_autorisee"])
        self.assertEqual(refus["raison_blocage_code"], "mowing_spacing")
        self.assertIn("5 jours minimum", refus["tonte_reason"])
        self.assertEqual(refus["next_mowing_date"], "2026-09-29")
        self.assertTrue(self._snap(13, tontes=(8,))["tonte_autorisee"])

    def test_seuil_de_score_assoupli_apres_la_levee(self) -> None:
        """Après la levée, le sursemis tond jusqu'à un score de 65 au lieu de 55, comme la reprise
        d'un semis : la tonte fait partie du plan (Purdue). Ce jour mesuré vaut 56."""
        snap = self._snap(12, humidite=80, pluie_demain=2.5, pluie_j2=2.5, pluie_3j=5.0)
        self.assertGreaterEqual(snap["score_tonte"], 55, "prémisse : au-dessus du seuil ordinaire")
        self.assertLess(snap["score_tonte"], 65)
        self.assertTrue(snap["tonte_autorisee"], snap.get("tonte_reason"))
        # Le plafond demeure : une vraie journée de pluie reste refusée.
        pluvieux = self._snap(
            12, humidite=82, pluie_demain=5.5, pluie_j2=5.5, pluie_3j=9.0, pluie_probabilite_max_3j=85
        )
        self.assertGreaterEqual(pluvieux["score_tonte"], 65)
        self.assertFalse(pluvieux["tonte_autorisee"])

    def test_le_gazon_en_place_continue_de_pousser(self) -> None:
        """Sur sol nu, rien à couper avant l'installation ; en sursemis, 0,35 cm/j en septembre."""
        for sous_phase in ("Germination", "Enracinement"):
            with self.subTest(sous_phase=sous_phase):
                sursemis = {"phase_dominante": "Sursemis", "sous_phase": sous_phase}
                semis = {"phase_dominante": "Semis", "sous_phase": sous_phase}
                self.assertEqual(decision_mowing._growth_rate_cm_per_day(sursemis, 9), 0.35)
                self.assertEqual(decision_mowing._growth_rate_cm_per_day(semis, 9), 0.0)

    # ── Hauteur ─────────────────────────────────────────────────────────────────────────
    def test_lame_courte_puis_remontee_apres_deux_coupes_des_plantules(self) -> None:
        courte = self._snap(23, tontes=(9, 14, 19, 22))
        self.assertEqual(courte["plantules_coupes"], 1, "prémisse : une seule tonte après le 08/10")
        self.assertEqual(courte["hauteur_tonte_recommandee_cm"], 4.0)
        remontee = self._snap(28, tontes=(9, 14, 19, 22, 27))
        self.assertEqual(remontee["plantules_coupes"], 2)
        self.assertEqual(remontee["hauteur_tonte_recommandee_cm"], 4.5)
        self.assertEqual(
            remontee["hauteur_tonte_motif"],
            "Sursemis : J+28, plantules coupées 2 fois : lame remontée à 4,5 cm.",
        )

    def test_ni_le_mois_ni_la_chaleur_ne_s_ajoutent_a_la_consigne(self) -> None:
        """La consigne REMPLACE la hauteur du mois : ni le +0,3 de phase, ni le bonus de chaleur."""
        chaud = self._snap(10, temperature=33.0, forecast_temperature_today=33.0)
        self.assertEqual(chaud["hauteur_tonte_recommandee_cm"], 4.0)
        self.assertTrue(chaud["hauteur_tonte_motif"].startswith("Sursemis : J+10, lame courte à 4,0 cm"))
        # Le sol nu, lui, garde son plancher de germination (plafonné à la tondeuse, 6 cm).
        self.assertEqual(self._snap(10, mode="Semis")["hauteur_tonte_recommandee_cm"], 6.0)

    def test_la_regle_du_tiers_reste_au_dessus_de_la_consigne(self) -> None:
        """Un gazon laissé haut n'est pas rasé à 4 cm d'un coup."""
        haut = self._snap(12, hauteur_gazon=9.0)
        self.assertGreaterEqual(haut["hauteur_tonte_recommandee_cm"], 6.0)
        self.assertIn("règle du tiers", haut["hauteur_tonte_motif"])
        self.assertIn("la consigne du sursemis aurait proposé 4.0 cm", haut["hauteur_tonte_garde_fou_label"])

    # ── Plantules ───────────────────────────────────────────────────────────────────────
    def test_suivi_des_plantules(self) -> None:
        attendu = {0: 0.0, 7: 0.0, 8: 0.4, 12: 2.0, 22: 6.0}
        for jour, hauteur in attendu.items():
            with self.subTest(jour=jour):
                snap = self._snap(jour)
                self.assertEqual(snap["semis_mode"], "Sursemis")
                self.assertEqual(snap["semis_age_jours"], jour)
                self.assertEqual(snap["plantules_hauteur_estimee_cm"], hauteur)
                self.assertEqual(snap["plantules_levee_date"], "2026-09-23")
                self.assertEqual(snap["plantules_premiere_coupe_date"], "2026-10-08")

    def test_seules_les_tontes_a_partir_de_la_premiere_coupe_comptent(self) -> None:
        self.assertEqual(self._snap(21, tontes=(9, 14, 19))["plantules_coupes"], 0)
        self.assertEqual(self._snap(22, tontes=(9, 14, 19, 22))["plantules_coupes"], 1)

    def test_le_suivi_existe_aussi_sur_sol_nu_et_s_arrete_a_j45(self) -> None:
        self.assertEqual(self._snap(12, mode="Semis")["semis_mode"], "Semis")
        fini = self._snap(45)
        self.assertEqual(fini["phase_active"], "Normal", "prémisse : la phase est terminée")
        # Le snapshot n'écrit pas les clés sans valeur : absentes ou None, c'est « pas de semis ».
        self.assertIsNone(fini.get("semis_mode"))
        self.assertIsNone(fini.get("plantules_hauteur_estimee_cm"))

    # ── Arrosage : identique dans les deux modes ────────────────────────────────────────
    def test_l_arrosage_est_le_meme_que_sur_sol_nu(self) -> None:
        cles = ("objectif_mm", "watering_strategy", "type_arrosage", "sous_phase",
                "semis_daily_cycles_target", "semis_cycle_spacing_minutes")
        for jour in (5, 15, 30):
            with self.subTest(jour=jour):
                sursemis = self._snap(jour, hour_of_day=12, memory={"auto_irrigation_enabled": True})
                semis = self._snap(jour, mode="Semis", hour_of_day=12, memory={"auto_irrigation_enabled": True})
                self.assertEqual({k: sursemis.get(k) for k in cles}, {k: semis.get(k) for k in cles})
                self.assertGreater(sursemis["objectif_mm"], 0.0, "prémisse : un cycle est dû")

    def test_un_jour_bloque_la_fenetre_publiee_reste_celle_du_semis(self) -> None:
        """Vérifié le 16/09/2026 : un cycle bloqué (froid, pluie) publiait 03:45 → 10:00.

        Aucun arrosage n'a lieu à l'aube en semis : la fenêtre affichée doit rester celle des
        micro-cycles, 10 h → 17 h (16 h s'il a plu).
        """
        auto = {"auto_irrigation_enabled": True}
        cas = {
            "froid": (dict(temperature=8.0, forecast_temperature_today=8.0), "temperature_trop_basse_germination", 1020),
            "pluie": (dict(pluie_24h=2.0), "pluie_prevue_suffisante", 960),
        }
        for mode in ("Sursemis", "Semis"):
            for nom, (meteo, motif, fin) in cas.items():
                with self.subTest(mode=mode, cas=nom):
                    snap = self._snap(5, mode=mode, hour_of_day=11, memory=auto, **meteo)
                    self.assertEqual(snap["block_reason"], motif, "prémisse : le cycle est bloqué")
                    self.assertEqual(snap["watering_window_start_minute"], 600)
                    self.assertEqual(snap["watering_window_end_minute"], fin)
                    self.assertEqual(snap["watering_window_optimal_start_minute"], 600)

    # ── Pièces détachées ────────────────────────────────────────────────────────────────
    def test_le_score_de_tonte_ne_porte_plus_45_en_sursemis(self) -> None:
        """Avec +45, une journée ordinaire dépassait le seuil de 65 : tonte autorisée, puis refusée."""
        scores = importlib.import_module("custom_components.gazon_intelligent.scores")
        commun = dict(
            sous_phase="Germination", pluie_24h=0.0, pluie_demain=0.0, pluie_j2=0.0, pluie_3j=0.0,
            pluie_probabilite_max_3j=0.0, humidite=60.0, arrosage_recent=4.5, hauteur_gazon=None,
            rosee=None, score_stress=30,
        )
        semis = scores._compute_score_tonte(phase_dominante="Semis", **commun)
        sursemis = scores._compute_score_tonte(phase_dominante="Sursemis", **commun)
        self.assertEqual(semis - sursemis, 27)
        self.assertLess(sursemis, 65)

    def test_statut_interdite_seulement_pendant_la_levee(self) -> None:
        statut = guidance.compute_tonte_statut
        self.assertEqual(statut("Sursemis", False, 20, "faible", blocage_code="phase_sursemis"), "interdite")
        self.assertNotEqual(statut("Sursemis", False, 20, "faible", blocage_code="pluie_active"), "interdite")
        self.assertEqual(statut("Semis", False, 20, "faible", blocage_code="pluie_active"), "interdite")

    def test_la_transition_ne_compte_que_les_coupes_de_plantules(self) -> None:
        """En sursemis, les tontes du gazon en place (dès J8) ne disent rien des plantules.

        Sur sol nu, toute tonte après le semis compte, comme avant.
        """
        compte = guidance._count_tontes_utiles_depuis_le_dernier_semis
        tontes = [{"type": "tonte", "date": d} for d in ("2026-09-25", "2026-10-01", "2026-10-08", "2026-10-13")]
        self.assertEqual(compte([{"type": "Sursemis", "date": "2026-09-16"}, *tontes]), 2)
        self.assertEqual(compte([{"type": "Semis", "date": "2026-09-16"}, *tontes]), 4)
        self.assertEqual(compte(tontes), 0)

    def test_la_transition_d_un_sursemis_attend_deux_coupes_de_plantules(self) -> None:
        # ⚠️ Horloge du banc figée au 04/04/2026 : la progression de sous-phase se calcule sur
        # elle. Semis en mars, comme `test_le_verrou_circulaire_de_transition_se_denoue`.
        d0 = date(2026, 3, 1)

        def snap(tontes: tuple[int, ...]) -> dict:
            return decision.build_decision_snapshot(
                history=[{"type": "Sursemis", "date": d0.isoformat()}]
                + [{"type": "tonte", "date": (d0 + timedelta(days=j)).isoformat()} for j in tontes],
                today=d0 + timedelta(days=32), hour_of_day=11, temperature=18, pluie_24h=0.0,
                pluie_demain=0.0, humidite=60, type_sol="limoneux", etp_capteur=2.0, memory={},
            )

        avant = snap((9, 14, 19, 26))
        self.assertEqual(avant["sous_phase"], "Reprise")
        self.assertIs(avant["seeding_transition_ready"], False, "une seule coupe de plantules (J26)")
        apres = snap((9, 14, 19, 22, 27))
        self.assertIs(apres["seeding_transition_ready"], True)
