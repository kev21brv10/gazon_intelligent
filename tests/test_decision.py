from __future__ import annotations

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
    # `as_local` MANQUAIT au stub : le code de production qui convertit un instant en heure murale
    # retombait donc silencieusement sur son repli, et les tests ne pouvaient pas voir la
    # différence entre « converti » et « pas converti ». C'est ce qui avait laissé passer la
    # projection de tonte calée sur des heures UTC.
    dt_module.as_local = lambda d: d.astimezone(ZoneInfo("Europe/Paris"))  # type: ignore[attr-defined]
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
guidance_mod = importlib.import_module("custom_components.gazon_intelligent.guidance")
guidance_module = importlib.import_module("custom_components.gazon_intelligent.guidance")

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


class TestEtoHourly(unittest.TestCase):
    """ET0 horaire FAO-56 Eq. 53 — port de la chaîne template `eto_fao56.yaml`.

    Valeurs verrouillées contre les capteurs réels du 28/07/2026 (station Netatmo
    + rayonnement Open-Meteo) : Rs, ETo et Ra doivent matcher la chaîne HA.
    """

    LAT = 46.5757513
    LON = 0.3559245
    J = 209  # 28 juillet

    def test_ra_hourly_est_astronomique(self) -> None:
        # Ra ne dépend que de la position + date/heure (aucun capteur, jamais indispo).
        ra = water._ra_hourly(self.LAT, self.LON, self.J, 14.74)
        self.assertAlmostEqual(ra, 3.4951, places=3)
        # Nuit : soleil sous l'horizon → Ra nul.
        self.assertEqual(water._ra_hourly(self.LAT, self.LON, self.J, 1.0), 0.0)

    def test_rs_horaire_utilise_la_radiation_mesuree(self) -> None:
        ra = water._ra_hourly(self.LAT, self.LON, self.J, 14.74)
        rs, ratio = water._rs_hourly(ra, 756.0, 0.0)
        # 756 W/m² × 0.0036 = 2.7216 MJ/m²/h (identique au capteur `eto_rs_horaire`).
        self.assertAlmostEqual(rs, 2.7216, places=4)
        self.assertAlmostEqual(ratio, 1.0, places=3)

    def test_rs_horaire_repli_modele_nuages_sans_radiation(self) -> None:
        # Sans capteur radiation → Rso × facteur nuages (Kasten-Czeplak). Ciel clair
        # (n=0) → r_nu=1 → Rs = 0.7524·Ra (plafonné 0.85·Ra, non atteint).
        ra = water._ra_hourly(self.LAT, self.LON, self.J, 12.0)
        rs, ratio = water._rs_hourly(ra, None, 0.0)
        self.assertAlmostEqual(rs, 0.7524 * ra, places=3)
        self.assertAlmostEqual(ratio, 1.0, places=3)

    def test_eto_horaire_reproduit_le_capteur_reel(self) -> None:
        # 28/07 ~16:44 (14:44 UTC) : ~34 °C, air très sec, 756 W/m², vent 5.8 km/h.
        # Le capteur `sensor.eto_horaire` affichait 0.6108 mm/h → on doit retomber dessus.
        eto = water.compute_eto_hourly(
            temperature=34.0, humidity=20.0, pressure_hpa=1016.9, wind_kmh=5.8,
            radiation_wm2=756.0, cloud_pct=0.0,
            latitude=self.LAT, longitude=self.LON, day_of_year=self.J, hour_utc=14.74,
        )
        self.assertAlmostEqual(eto, 0.6116, places=3)
        # Cas médian déterministe (midi, ciel clair, 30 °C).
        eto_midi = water.compute_eto_hourly(
            temperature=30.0, humidity=35.0, pressure_hpa=1015.0, wind_kmh=6.0,
            radiation_wm2=750.0, cloud_pct=0.0,
            latitude=self.LAT, longitude=self.LON, day_of_year=self.J, hour_utc=12.0,
        )
        self.assertAlmostEqual(eto_midi, 0.581, places=3)

    def test_eto_horaire_normalise_l_unite_de_vent(self) -> None:
        # L'ET0 JOURNALIÈRE lisait déjà `weather_wind_speed_unit` (m/s, mph…) ; l'horaire, elle,
        # divisait par 3,6 sans condition. Une entité météo en m/s voyait donc son vent divisé
        # par 3,6 en trop → ET0 horaire sous-estimée d'environ 12 %, et comme ce taux pilote le
        # ledger depuis la 0.19.0, un sol qui paraît sécher trop lentement.
        kwargs = dict(
            temperature=30.0, humidity=35.0, pressure_hpa=1015.0,
            radiation_wm2=750.0, cloud_pct=0.0,
            latitude=self.LAT, longitude=self.LON, day_of_year=self.J, hour_utc=12.0,
        )
        # 5 m/s = 18 km/h : les deux expressions du MÊME vent doivent donner la même ET0.
        en_ms = water.compute_eto_hourly(wind_kmh=5.0, wind_unit="m/s", **kwargs)
        en_kmh = water.compute_eto_hourly(wind_kmh=18.0, wind_unit="km/h", **kwargs)
        self.assertAlmostEqual(en_ms, en_kmh, places=4)
        # Et un vent en m/s pris pour des km/h sous-estime bien l'ET0 (le défaut corrigé).
        mal_interprete = water.compute_eto_hourly(wind_kmh=5.0, wind_unit="km/h", **kwargs)
        self.assertLess(mal_interprete, en_ms)
        # Unité absente ou inconnue → repli km/h (défaut Home Assistant), comportement historique.
        self.assertAlmostEqual(
            water.compute_eto_hourly(wind_kmh=5.0, wind_unit=None, **kwargs), mal_interprete, places=4
        )

    def test_eto_horaire_nulle_la_nuit(self) -> None:
        # Radiation nulle la nuit → Rn négatif, ETo bornée à 0 (pas d'évaporation).
        eto = water.compute_eto_hourly(
            temperature=18.0, humidity=80.0, pressure_hpa=1015.0, wind_kmh=4.0,
            radiation_wm2=0.0, cloud_pct=50.0,
            latitude=self.LAT, longitude=self.LON, day_of_year=self.J, hour_utc=1.0,
        )
        self.assertEqual(eto, 0.0)


class TestPhaseLogic(unittest.TestCase):
    def test_compute_phase_active_prefers_highest_priority(self) -> None:
        today = date(2026, 3, 17)
        history = [
            {"type": "Sursemis", "date": "2026-03-10"},
            {"type": "Traitement", "date": "2026-03-16"},
        ]

        phase, start, end = decision.compute_phase_active(history, today=today)

        self.assertEqual(phase, "Traitement")
        self.assertEqual(start, date(2026, 3, 16))
        self.assertEqual(end, date(2026, 3, 17))

    def test_compute_phase_active_stays_normal_without_active_history_even_when_cold(self) -> None:
        phase, start, end = decision.compute_phase_active([], today=date(2026, 1, 15))

        self.assertEqual(phase, "Normal")
        self.assertIsNone(start)
        self.assertIsNone(end)

        phase, start, end = decision.compute_phase_active([], today=date(2026, 4, 14))

        self.assertEqual(phase, "Normal")
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_compute_recent_watering_mm_respects_window(self) -> None:
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 2.5},
            {"type": "arrosage", "date": "2026-03-16", "objectif_mm": 1.5},
            {"type": "arrosage", "date": "2026-03-13", "objectif_mm": 9.0},
        ]

        total = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=2)

        self.assertEqual(total, 4.0)

    def test_compute_recent_watering_mm_uses_canonical_surface_total(self) -> None:
        # Régression : un cycle 3 passages × 2 zones enregistre une liste `zones` de 6
        # entrées (une par passage×zone, ~1,7 mm chacune). La dose surface du cycle complet
        # est `total_mm` = 5,2 mm — PAS la moyenne des 6 entrées (~1,7 = un seul passage).
        # Le comptage doit créditer 5,2, sinon la réserve et le budget hebdo sont
        # sous-crédités d'un facteur ≈ nombre de passages.
        history = [
            {
                "type": "arrosage",
                "date": "2026-03-17",
                "objectif_mm": 5.2,
                "total_mm": 5.2,
                "zones_total_mm": 10.4,
                "zones": [
                    {"zone": "zone_1", "mm": 1.8},
                    {"zone": "zone_2", "mm": 1.8},
                    {"zone": "zone_1", "mm": 1.7},
                    {"zone": "zone_2", "mm": 1.7},
                    {"zone": "zone_1", "mm": 1.7},
                    {"zone": "zone_2", "mm": 1.7},
                ],
            }
        ]

        total = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=2)

        self.assertEqual(total, 5.2)

    def test_compute_recent_watering_mm_single_pass_surface_depth(self) -> None:
        # Arrosage simple multi-zones (1 passage, 3 zones) : `total_mm` = dose surface
        # (moyenne par zone, chaque zone couvrant une part) = 1,2 mm, et non la somme (3,6).
        history = [
            {
                "type": "arrosage",
                "date": "2026-03-17",
                "objectif_mm": 1.2,
                "total_mm": 1.2,
                "zones_total_mm": 3.6,
                "zones": [
                    {"zone": "zone_1", "mm": 1.2},
                    {"zone": "zone_2", "mm": 1.1},
                    {"zone": "zone_3", "mm": 1.3},
                ],
            }
        ]

        total = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=2)

        self.assertEqual(total, 1.2)

    def test_compute_recent_watering_mm_excludes_technical_cooling(self) -> None:
        # Régression : le rafraîchissement du soir (canicule) et l'incorporation post-application
        # sont des arrosages TECHNIQUES — ils ne rechargent pas la réserve, donc ne doivent PAS
        # compter dans l'eau récente (ni réserve, ni garde-fou hebdo). Sinon le cooling grignote
        # le budget ET gonfle la réserve → gazon qui sèche en canicule alors que tout paraît plein.
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 5.0},  # vraie recharge
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 3.0, "watering_cause": "rafraichissement_soir"},
            {"type": "arrosage", "date": "2026-03-16", "objectif_mm": 2.0, "watering_cause": "post_application"},
        ]

        total = decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=7)

        self.assertEqual(total, 5.0)  # seul l'arrosage de vraie recharge est compté

    def test_compute_recent_watering_mm_can_exclude_external_sessions(self) -> None:
        # Régression (garde-fou hebdo) : une session EXTERNE (`zone_session` = vannes ouvertes
        # hors intégration : Assist/voix, raccourci, toggle manuel) ne doit pas gonfler le budget
        # hebdo. include_external=False l'exclut ; par défaut (True) elle reste comptée (rétro-compat).
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 5.0, "source": "auto_irrigation"},
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 22.5, "source": "zone_session"},
        ]
        # Budget hebdo (exclut l'externe) → seule la recharge pilotée par l'intégration compte.
        self.assertEqual(
            decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=7, include_external=False),
            5.0,
        )
        # Par défaut → tout compte (rétro-compat préservée).
        self.assertEqual(
            decision.compute_recent_watering_mm(history, today=date(2026, 3, 17), days=7),
            27.5,
        )

    def test_compute_recent_watering_mm_can_exclude_manual_sessions(self) -> None:
        # Régression (cercle vicieux, constaté 25/07/2026) : un arrosage MANUEL de secours
        # (start_manual_irrigation) ne doit pas gonfler le garde-fou hebdo, sinon plus l'utilisateur
        # arrose à la main pour compenser un auto bloqué, plus l'auto reste bloqué. Le manuel doit
        # rester dans l'eau RÉELLEMENT reçue (crédit de la réserve), mais sortir du budget de l'auto.
        history = [
            {"type": "arrosage", "date": "2026-03-17", "total_mm": 8.0, "source": "auto_irrigation"},
            {"type": "arrosage", "date": "2026-03-16", "total_mm": 3.0, "source": "manual_irrigation"},
            {"type": "arrosage", "date": "2026-03-15", "total_mm": 5.0, "source": "manual_force"},
        ]
        today = date(2026, 3, 17)
        # Garde-fou hebdo (include_manual=False) → seuls les 8 mm auto comptent.
        self.assertEqual(
            decision.compute_recent_watering_mm(history, today=today, days=7, include_manual=False),
            8.0,
        )
        # Eau réellement reçue (défaut) → manuel inclus (l'eau est bien tombée).
        self.assertEqual(
            decision.compute_recent_watering_mm(history, today=today, days=7),
            16.0,
        )

    def test_compute_recent_watering_count_can_exclude_external_sessions(self) -> None:
        # Le COMPTE hebdo doit aussi pouvoir ignorer les sessions externes (cohérence garde-fou).
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 5.0, "source": "auto_irrigation"},
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 22.5, "source": "zone_session"},
        ]
        self.assertEqual(
            water.compute_recent_watering_count(history, today=date(2026, 3, 17), days=7, include_external=False), 1
        )
        self.assertEqual(water.compute_recent_watering_count(history, today=date(2026, 3, 17), days=7), 2)

    def test_latest_watering_datetime_ignores_external_sessions(self) -> None:
        # Choix Kévin (25/06/2026) : un arrosage EXTERNE (`zone_session`) n'arme PAS le cooldown 24 h.
        # _latest_watering_datetime (l'ancre du cooldown) doit donc ignorer l'externe et renvoyer la
        # dernière session PILOTÉE par l'intégration, même si une session externe est plus récente.
        piloted_at = datetime(2026, 3, 16, 6, 0, tzinfo=timezone.utc)
        external_at = datetime(2026, 3, 17, 23, 51, tzinfo=timezone.utc)
        history = [
            {"type": "arrosage", "recorded_at": piloted_at.isoformat(), "total_mm": 5.0, "source": "auto_irrigation"},
            {"type": "arrosage", "recorded_at": external_at.isoformat(), "total_mm": 5.8, "source": "zone_session"},
        ]
        latest = guidance_module._latest_watering_datetime(history)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.date(), date(2026, 3, 16))  # l'auto du 16, pas l'externe du 17

    def test_latest_watering_datetime_external_only_returns_none(self) -> None:
        # Si la SEULE session est externe → aucune ancre de cooldown (l'externe n'arme pas le cooldown).
        history = [
            {
                "type": "arrosage",
                "recorded_at": datetime(2026, 3, 17, 23, 51, tzinfo=timezone.utc).isoformat(),
                "total_mm": 5.8,
                "source": "zone_session",
            },
        ]
        self.assertIsNone(guidance_module._latest_watering_datetime(history))

    def test_compute_recent_watering_count_still_counts_technical_events(self) -> None:
        # Le COMPTE d'arrosages (fréquence) reste inchangé : un cooling reste un événement
        # d'arrosage. Seul le total en mm (réserve + budget) exclut les arrosages techniques.
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 5.0},
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 3.0, "watering_cause": "rafraichissement_soir"},
        ]

        self.assertEqual(water.compute_recent_watering_count(history, today=date(2026, 3, 17), days=7), 2)

    def test_compute_recent_watering_count_shares_recent_filtering_rules(self) -> None:
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 2.5},
            {"type": "arrosage", "date": "invalid", "objectif_mm": 1.5},
            {"type": "arrosage", "date": "2026-03-15", "zones": [{"zone": "z1", "mm": 1.0}]},
            {"type": "arrosage", "date": "2026-03-10", "objectif_mm": 9.0},
            {"type": "arrosage", "date": "2026-03-16"},
        ]

        count = water.compute_recent_watering_count(history, today=date(2026, 3, 17), days=2)

        self.assertEqual(count, 2)

    def test_compute_dominant_phase_prefers_highest_priority_active_window(self) -> None:
        history = [
            {"type": "Sursemis", "date": "2026-03-10"},
            {"type": "Scarification", "date": "2026-03-16"},
            {"type": "Traitement", "date": "2026-03-17"},
        ]

        dominant = decision.compute_dominant_phase(history, today=date(2026, 3, 17))

        self.assertEqual(dominant["phase_dominante"], "Traitement")
        self.assertEqual(dominant["source"], "historique_actif")
        self.assertEqual(dominant["date_debut"], date(2026, 3, 17))
        self.assertEqual(dominant["date_fin"], date(2026, 3, 18))

    def test_compute_dominant_phase_expires_single_day_phase_on_next_day(self) -> None:
        dominant = decision.compute_dominant_phase(
            [{"type": "Biostimulant", "date": "2026-03-17"}],
            today=date(2026, 3, 18),
        )

        self.assertEqual(dominant["phase_dominante"], "Normal")
        self.assertEqual(dominant["source"], "absence_phase")

    def test_compute_subphase_tracks_sursemis_progression(self) -> None:
        # Règle Sursemis: Germination <= 10j → jour 10 = dernier jour Germination, jour 11 = Enracinement
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 7),
            date_fin=date(2026, 3, 27),
            today=date(2026, 3, 18),
        )

        self.assertEqual(subphase["sous_phase"], "Enracinement")
        self.assertEqual(subphase["age_jours"], 11)

    def test_compute_subphase_progression_moves_with_time(self) -> None:
        # Règle Sursemis: Germination <= 10j, Enracinement <= 24j → jour 11 = Enracinement
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 3, 7),
            date_fin=date(2026, 3, 27),
            today=date(2026, 3, 18),
            now=datetime(2026, 3, 18, 6, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(subphase["sous_phase"], "Enracinement")
        self.assertEqual(subphase["age_jours"], 11)
        self.assertEqual(subphase["detail"], "Sursemis / Enracinement")

    def test_compute_subphase_terminal_progression_bounded_by_phase_duration(self) -> None:
        # Stabilisation = jours 35-45 d'un Sursemis de 45j. Au jour 44, la
        # progression doit être proche de la fin (~85-95 %), pas ~1 % comme
        # lorsque la sentinelle 999 était prise pour une durée réelle.
        subphase = decision.compute_subphase(
            phase_dominante="Sursemis",
            date_debut=date(2026, 4, 26),
            date_fin=date(2026, 6, 10),
            today=date(2026, 6, 9),
            now=datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(subphase["sous_phase"], "Stabilisation")
        self.assertEqual(subphase["age_jours"], 44)
        self.assertGreaterEqual(subphase["progression"], 80.0)
        self.assertLessEqual(subphase["progression"], 100.0)

    def test_compute_subphase_hivernage_terminal_stays_open_ended(self) -> None:
        # Hivernage (durée 999): la sous-phase Repos reste volontairement
        # ouverte, le cap par durée de phase ne doit pas s'appliquer.
        subphase = decision.compute_subphase(
            phase_dominante="Hivernage",
            date_debut=date(2026, 1, 1),
            date_fin=None,
            today=date(2026, 1, 11),
            now=datetime(2026, 1, 11, 6, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(subphase["sous_phase"], "Repos")
        self.assertLess(subphase["progression"], 5.0)

class TestHydricCoreAndMemory(unittest.TestCase):
    def test_arrosage_recent_jour_ne_compte_que_le_jour_meme(self) -> None:
        # Régression : la fenêtre « jour » retenait aussi la VEILLE (filtre `delta <= days` avec
        # days=1). Le bilan journalier créditait donc 2 jours d'arrosage contre 1 seul jour d'ET0
        # → bilan surestimé d'un arrosage entier (vu en réel : 24 mm affichés pour 12 mm appliqués).
        # Le ledger sol utilise déjà days=0 : on s'aligne. Les fenêtres 3j/7j suivent désormais la
        # MÊME règle (K jours = days=K-1) — cf. test_fenetres_3j_7j_sont_de_vraies_fenetres.
        history = [
            {"type": "arrosage", "date": "2026-03-17", "total_mm": 12.0},
            {"type": "arrosage", "date": "2026-03-16", "total_mm": 12.0},
        ]

        balance = decision.compute_water_balance(
            history=history,
            today=date(2026, 3, 17),
            etp=6.3,
            pluie_24h=0.0,
            pluie_demain=0.0,
            type_sol="limoneux",
        )

        self.assertEqual(balance["arrosage_recent_jour"], 12.0)  # et non 24.0 (la veille exclue)
        self.assertEqual(balance["arrosage_recent_3j"], 24.0)  # la veille reste bien dans 3j
        self.assertEqual(balance["arrosage_recent_7j"], 24.0)

    def test_fenetres_3j_7j_sont_de_vraies_fenetres(self) -> None:
        # Correction du décalage d'un jour : `days=N` retient `delta <= N` = N+1 jours calendaires.
        # Les fenêtres 3j/7j passaient days=3/7 (soit 4/8 jours) alors que la fenêtre journalière
        # avait déjà été ramenée à days=0. Elles utilisent désormais days=2/6 → 3 et 7 jours PILE.
        # Effet réel constaté (27/07/2026) : le garde-fou hebdo gardait un arrosage un jour de trop,
        # le budget mettait un jour de plus à retomber sous le plafond.
        history = [
            {"type": "arrosage", "date": "2026-03-15", "total_mm": 5.0},   # delta 2 → dans 3j ET 7j
            {"type": "arrosage", "date": "2026-03-14", "total_mm": 7.0},   # delta 3 → HORS 3j, dans 7j
            {"type": "arrosage", "date": "2026-03-11", "total_mm": 9.0},   # delta 6 → dans 7j (bord)
            {"type": "arrosage", "date": "2026-03-10", "total_mm": 11.0},  # delta 7 → HORS 7j
        ]

        balance = decision.compute_water_balance(
            history=history,
            today=date(2026, 3, 17),
            etp=5.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            type_sol="limoneux",
        )

        # 3j = days=2 : seul delta 2 compte (delta 3 exclu).
        self.assertEqual(balance["arrosage_recent_3j"], 5.0)
        # 7j = days=6 : delta 2+3+6 comptent, delta 7 exclu (avant : aurait inclus les 11 mm → 32).
        self.assertEqual(balance["arrosage_recent_7j"], 21.0)

    def test_arrosage_applique_7j_inclut_les_arrosages_techniques(self) -> None:
        # `arrosage_recent_7j` sert au GARDE-FOU : il exclut les arrosages techniques
        # (rafraîchissement du soir, incorporation post-produit). L'eau réellement reçue par le
        # gazon est donc supérieure — écart invisible jusqu'ici, ce qui a masqué un sur-arrosage
        # durable. `arrosage_applique_7j` expose ce total réel.
        history = [
            {"type": "arrosage", "date": "2026-03-17", "total_mm": 12.0, "watering_cause": "hydrique"},
            {"type": "arrosage", "date": "2026-03-16", "total_mm": 3.0,
             "watering_cause": "rafraichissement_soir"},
            {"type": "arrosage", "date": "2026-03-15", "total_mm": 3.0,
             "watering_cause": "post_application"},
        ]

        balance = decision.compute_water_balance(
            history=history,
            today=date(2026, 3, 17),
            etp=5.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            type_sol="limoneux",
        )

        self.assertEqual(balance["arrosage_recent_7j"], 12.0)     # budget : technique exclu
        self.assertEqual(balance["arrosage_applique_7j"], 18.0)   # réel : 12 + 3 + 3

    def test_arrosage_recent_7j_ne_seffondre_pas_sur_larrosage_du_jour(self) -> None:
        # Régression (28/07/2026) : les jours d'arrosage, `retour_arrosage` (l'arrosage du JOUR)
        # REMPLAÇAIT la somme 7 j au lieu de la plancher → le budget hebdo se refermait sur le seul
        # arrosage du jour (12 mm) alors que 36 mm d'AUTO avaient été appliqués sur 7 j. Le
        # garde-fou en devenait trop permissif et l'affichage « budget » faux (27 % au lieu de 81 %).
        history = [
            {"type": "arrosage", "date": "2026-03-17", "total_mm": 12.0, "watering_cause": "hydrique"},
            {"type": "arrosage", "date": "2026-03-14", "total_mm": 3.0,
             "source": "manual_irrigation", "watering_cause": "hydrique"},  # manuel : hors budget
            {"type": "arrosage", "date": "2026-03-12", "total_mm": 12.0, "watering_cause": "hydrique"},
            {"type": "arrosage", "date": "2026-03-11", "total_mm": 3.0,
             "watering_cause": "rafraichissement_soir"},  # technique : hors budget
            {"type": "arrosage", "date": "2026-03-11", "total_mm": 12.0, "watering_cause": "hydrique"},
        ]

        balance = decision.compute_water_balance(
            history=history,
            today=date(2026, 3, 17),
            etp=6.9,
            pluie_24h=0.0,
            pluie_demain=0.0,
            type_sol="limoneux",
            recent_watering_mm_override=12.0,  # arrosage du jour (retour_arrosage)
            advanced_context={"retour_arrosage": 12.0},
        )

        # 3 arrosages AUTO hydriques de 12 mm sur 7 j = 36 (manuel + technique exclus du budget),
        # et NON 12 : l'arrosage du jour ne doit pas écraser la somme des jours précédents.
        self.assertEqual(balance["arrosage_recent_7j"], 36.0)
        # Total réellement reçu (technique ET manuel inclus, externe exclu) = 12+3+12+3+12 = 42.
        self.assertEqual(balance["arrosage_applique_7j"], 42.0)

    def test_retour_arrosage_planche_sans_ecraser_quand_absent_de_lhistorique(self) -> None:
        # L'arrosage du jour peut ne pas encore être dans l'historique : `retour_arrosage` doit
        # alors servir de PLANCHER (il est compté), sans rien inventer au-delà.
        balance = decision.compute_water_balance(
            history=[],
            today=date(2026, 3, 17),
            etp=6.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            type_sol="limoneux",
            recent_watering_mm_override=12.0,
            advanced_context={"retour_arrosage": 12.0},
        )

        self.assertEqual(balance["arrosage_recent_jour"], 12.0)
        self.assertEqual(balance["arrosage_recent_7j"], 12.0)

    def test_compute_water_balance_returns_detailed_metrics(self) -> None:
        history = [
            {"type": "arrosage", "date": "2026-03-17", "objectif_mm": 0.5},
        ]

        balance = decision.compute_water_balance(
            history=history,
            today=date(2026, 3, 17),
            etp=5.0,
            pluie_24h=1.0,
            pluie_demain=0.0,
            type_sol="sableux",
        )

        self.assertEqual(balance["pluie_efficace"], 0.9)
        self.assertEqual(balance["arrosage_recent"], 0.5)
        self.assertEqual(balance["arrosage_recent_jour"], 0.5)
        self.assertEqual(balance["arrosage_recent_3j"], 0.5)
        self.assertEqual(balance["arrosage_recent_7j"], 0.5)
        self.assertEqual(balance["deficit_jour"], 5.4)
        self.assertEqual(balance["deficit_3j"], 19.9)
        self.assertEqual(balance["deficit_7j"], 48.5)

    def test_compute_water_balance_prefers_persisted_soil_balance_reserve(self) -> None:
        balance = decision.compute_water_balance(
            history=[],
            today=date(2026, 3, 17),
            etp=3.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            type_sol="limoneux",
            soil_balance={
                "reserve_mm": 14.0,
                "reserve_max_mm": 24.0,
            },
        )

        self.assertEqual(balance["reserve_stock_mm"], 14.0)
        self.assertEqual(balance["reserve_actuelle_mm"], 12.0)
        self.assertEqual(balance["reserve_stock_max_mm"], 24.0)
        self.assertEqual(balance["reserve_surplus_mm"], 2.0)

    def test_display_reserve_matches_decision_when_depleted(self) -> None:
        # Anti-incohérence (choix 25/06/2026) : la réserve AFFICHÉE = la réserve de DÉCISION,
        # quelle que soit l'heure. Avant, l'affichage rajoutait l'ET du jour et montrait « pas
        # soif » (10,4) alors que la décision était « a soif » (2,2) → carte ≠ cerveau. Corrigé.
        common = dict(
            history=[],
            today=date(2026, 7, 15),
            etp=8.2,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            type_sol="limoneux",
            soil_balance={"reserve_mm": 2.2, "reserve_max_mm": 24.0},
        )
        for frac in (0.0, 0.5, 1.0):
            wb = decision.compute_water_balance(**common, weather_profile={"et_elapsed_fraction": frac})
            self.assertAlmostEqual(wb["reserve_actuelle_affichee_mm"], wb["reserve_actuelle_mm"], places=2)
            self.assertAlmostEqual(wb["depletion_ratio_affiche"], wb["depletion_ratio"], places=3)
        # Réserve très basse → l'affichage montre BIEN « soif » (≥ seuil MAD), comme la décision.
        wb = decision.compute_water_balance(**common, weather_profile={"et_elapsed_fraction": 0.0})
        self.assertEqual(wb["reserve_stock_mm"], 2.2)
        self.assertGreater(wb["depletion_ratio_affiche"], 0.5)

    def test_display_reserve_matches_decision_when_well_supplied(self) -> None:
        # Sol bien pourvu (décision 9/12) : l'affichage colle à la décision à toute heure (fini
        # le « plein » trompeur du matin). La jauge bouge avec la vraie réserve, sans mentir.
        common = dict(
            history=[],
            today=date(2026, 7, 15),
            etp=7.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            type_sol="limoneux",
            soil_balance={"reserve_mm": 9.0, "reserve_max_mm": 24.0},
        )
        for frac in (0.0, 0.5, 1.0):
            wb = decision.compute_water_balance(**common, weather_profile={"et_elapsed_fraction": frac})
            self.assertAlmostEqual(wb["reserve_actuelle_affichee_mm"], wb["reserve_actuelle_mm"], places=2)
            self.assertAlmostEqual(wb["reserve_actuelle_affichee_mm"], 9.0, places=1)
            self.assertAlmostEqual(wb["depletion_ratio_affiche"], wb["depletion_ratio"], places=3)

    def test_display_reserve_frozen_when_recalibrated_today(self) -> None:
        # Régression carte : après un recalage manuel (service recalibrate_reserve) la réserve du jour
        # est ANCRÉE — l'ET du jour n'est PAS projetée dessus. L'affichage doit montrer la valeur
        # recalée TELLE QUELLE, sans reconstruction « + ET du matin » (sinon recalage à 4 → carte à 12).
        today = date(2026, 7, 15)
        base = dict(
            history=[],
            today=today,
            etp=8.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.0,
            type_sol="limoneux",
        )
        anchored = decision.compute_water_balance(
            **base,
            soil_balance={
                "reserve_mm": 4.0,
                "reserve_max_mm": 24.0,
                "ledger": [{"date": today.isoformat(), "reserve_mm": 4.0, "manual_anchor": True}],
            },
            weather_profile={"et_elapsed_fraction": 0.5},
        )
        # Cœur du correctif : même en milieu de journée, l'affichage est figé sur la décision.
        self.assertAlmostEqual(anchored["reserve_actuelle_affichee_mm"], anchored["reserve_actuelle_mm"], places=2)
        self.assertAlmostEqual(anchored["depletion_ratio_affiche"], anchored["depletion_ratio"], places=2)
        # Depuis l'anti-incohérence (25/06/2026) : avec OU sans recalage, l'affichage colle à la
        # décision. Même réserve (4,0) sans recalage → même affichage que la version ancrée.
        not_anchored = decision.compute_water_balance(
            **base,
            soil_balance={"reserve_mm": 4.0, "reserve_max_mm": 24.0},
            weather_profile={"et_elapsed_fraction": 0.5},
        )
        self.assertAlmostEqual(
            not_anchored["reserve_actuelle_affichee_mm"], not_anchored["reserve_actuelle_mm"], places=2
        )
        self.assertAlmostEqual(
            not_anchored["reserve_actuelle_affichee_mm"], anchored["reserve_actuelle_affichee_mm"], places=2
        )

    def test_build_decision_snapshot_uses_persistent_soil_balance(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            etp_capteur=3.0,
            soil_balance={
                "date": "2026-03-17",
                "reserve_mm": 14.0,
                "previous_reserve_mm": 11.0,
                "pluie_mm": 1.0,
                "arrosage_mm": 5.0,
                "etp_mm": 3.0,
                "delta_mm": 3.0,
                "type_sol": "limoneux",
                "reserve_max_mm": 24.0,
                "reserve_min_mm": 0.0,
                "ledger": [],
            },
        )

        self.assertEqual(snapshot["reserve_hydrique_sol_mm"], 14.0)
        # Le bilan brut vaut exactement -3.0 (ETP 3.0, ni pluie ni arrosage sur l'horizon jour).
        # L'attendu était -2.9 : il figeait le bug de troncature de water._round_half_up_1, qui
        # ramenait les négatifs VERS zéro (int(-30.0 + 0.5) = -29 → -2.9). Une fois l'arrondi
        # aligné sur celui de soil_balance, la valeur correcte est -3.0.
        self.assertAlmostEqual(snapshot["bilan_hydrique_mm"], -3.0, places=1)
        self.assertEqual(snapshot["bilan_hydrique_precedent_mm"], 11.0)
        self.assertEqual(snapshot["type_sol"], "limoneux")
        self.assertEqual(snapshot["soil_balance"]["reserve_mm"], 14.0)

    def test_build_decision_snapshot_exposes_hydric_observability_metrics(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 4, 8),
            hour_of_day=9,
            temperature=20.0,
            forecast_temperature_today=24.0,
            temperature_source="capteur",
            temperature_reference_hydrique=22.8,
            etp_capteur=None,
            soil_balance={
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
            },
            et0_source="fallback_temperature",
        )

        self.assertEqual(snapshot["temperature_reference_hydrique"], 22.8)
        self.assertEqual(snapshot["et0_source"], "fallback_temperature")
        self.assertGreater(snapshot["et0_mm"], 0.0)
        self.assertEqual(snapshot["kc_gazon"], 0.8)
        self.assertGreater(snapshot["etc_mm"], 0.0)
        self.assertEqual(snapshot["reserve_actuelle_mm"], 10.0)
        # RÉSERVOIR DE RÉFÉRENCE = le stock max du ledger (capacité au champ), pas la réserve
        # d'ouverture de 12 mm : la déplétion se mesure depuis la capacité au champ (FAO-56).
        # Avant ce ré-ancrage, tout stock ≥ 12 affichait une déplétion NULLE et le MAD tombait
        # à 6 mm — l'arrosage revenait chaque jour avec la dose plancher.
        self.assertEqual(snapshot["reserve_utile_mm"], 12.0)
        self.assertEqual(snapshot["depletion_mm"], 2.0)
        self.assertAlmostEqual(snapshot["depletion_ratio"], 0.167, places=3)

    def test_compute_advanced_context_uses_weather_probability(self) -> None:
        context = decision.compute_advanced_context(
            humidite_sol=22,
            vent=18,
            rosee=1.0,
            hauteur_gazon=11.5,
            retour_arrosage=0.7,
            weather_profile={
                "weather_precipitation_probability": 70,
                "weather_condition": "cloudy",
            },
        )

        self.assertEqual(context["humidite_sol"], 22.0)
        self.assertEqual(context["vent"], 18.0)
        self.assertEqual(context["rosee"], 1.0)
        self.assertEqual(context["hauteur_gazon"], 11.5)
        self.assertEqual(context["retour_arrosage"], 0.7)
        self.assertEqual(context["weather_precipitation_probability"], 70.0)
        self.assertGreater(context["soil_factor"], 1.0)
        self.assertGreater(context["wind_factor"], 1.0)
        self.assertLess(context["dew_factor"], 1.0)
        self.assertLess(context["rain_factor"], 1.0)

    def test_compute_advanced_context_normalizes_weather_probability_strings(self) -> None:
        context = decision.compute_advanced_context(
            weather_profile={"weather_precipitation_probability": "70"},
        )

        self.assertEqual(context["weather_precipitation_probability"], 70.0)

    def test_compute_memory_tracks_last_useful_events(self) -> None:
        history = [
            {"type": "tonte", "date": "2026-03-12"},
            {"type": "arrosage", "date": "2026-03-13", "objectif_mm": 1.0},
            {
                "type": "arrosage",
                "date": "2026-03-16",
                "objectif_mm": 0.8,
                "total_mm": 1.5,
                "zones_total_mm": 3.0,
                "zones": [
                    {"zone": "zone_1", "mm": 1.2},
                    {"zone": "zone_2", "mm": 1.8},
                ],
            },
            {"type": "Sursemis", "date": "2026-03-10"},
            {
                "type": "Fertilisation",
                "date": "2026-03-17",
                "produit": "Engrais printemps",
                "dose": "12.5",
                "zone": "zone_1",
                "reapplication_after_days": 21,
                "note": "Test",
                "source": "service",
            },
        ]

        memory = decision.compute_memory(
            history=history,
            current_phase="Sursemis",
            decision={
                "phase_active": "Sursemis",
                "objectif_mm": 2.8,
                "conseil_principal": "Arroser ce matin",
                "action_recommandee": "Appliquer 2.8 mm",
                "action_a_eviter": "Tondre",
                "niveau_action": "a_faire",
                "fenetre_optimale": "maintenant",
                "risque_gazon": "modere",
                "prochaine_reevaluation": "dans 24 h",
                "raison_decision": "Test",
            },
            today=date(2026, 3, 17),
        )

        self.assertEqual(memory["derniere_tonte"]["date"], "2026-03-12")
        self.assertEqual(memory["dernier_arrosage"]["date"], "2026-03-16")
        self.assertIsNone(memory["dernier_arrosage_significatif"])
        self.assertEqual(memory["derniere_phase_active"], "Sursemis")
        self.assertEqual(memory["derniere_application"]["libelle"], "Engrais printemps")
        self.assertEqual(memory["derniere_application"]["type"], "Fertilisation")
        self.assertEqual(memory["derniere_application"]["dose"], "12.5")
        self.assertEqual(memory["prochaine_reapplication"], "2026-04-07")
        self.assertEqual(memory["dernier_conseil"]["conseil_principal"], "Arroser ce matin")
        self.assertEqual(memory["dernier_conseil"]["prochaine_reevaluation"], "dans 24 h")

class TestDecisionSnapshotWatering(unittest.TestCase):
    def test_build_decision_snapshot_normal_recommends_watering(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=20,
            etp_capteur=3.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["phase_dominante"], "Normal")
        self.assertEqual(snapshot["sous_phase"], "Normal")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["type_arrosage"], "personnalise")
        self.assertEqual(snapshot["arrosage_conseille"], "personnalise")
        self.assertIn(snapshot["tonte_statut"], {"autorisee", "autorisee_avec_precaution", "a_surveiller"})
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertEqual(snapshot["fenetre_optimale"], "demain_matin")
        self.assertEqual(snapshot["risque_gazon"], "modere")
        self.assertEqual(snapshot["prochaine_reevaluation"], "dans 24 h")
        self.assertGreater(snapshot["objectif_mm"], 0)
        self.assertLessEqual(snapshot["objectif_mm"], snapshot["objectif_mm_brut"])
        self.assertLess(snapshot["bilan_hydrique_mm"], 0)
        self.assertEqual(snapshot["decision_resume"]["action"], "arrosage")
        self.assertTrue(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["heat_stress_level"], "vigilance")
        self.assertGreaterEqual(snapshot["deficit_mm_ajuste"], 0.0)
        self.assertGreaterEqual(snapshot["mm_final"], snapshot["mm_cible"])
        self.assertEqual(snapshot["niveau_confiance"], "high")
        self.assertIn("weekly_guardrail_reason", snapshot)

    def test_build_decision_snapshot_normal_suppresses_micro_watering(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=20,
            etp_capteur=1.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["type_arrosage"], "aucune_action")
        self.assertEqual(snapshot["arrosage_conseille"], "aucune_action")
        self.assertEqual(snapshot["niveau_action"], "aucune_action")
        self.assertNotIn("0.0 mm", snapshot["conseil_principal"])
        self.assertNotIn("0.0 mm", snapshot["action_recommandee"])
        self.assertEqual(snapshot["action_a_eviter"], "Éviter tout arrosage inutile.")

    def test_build_decision_snapshot_reduces_watering_when_rain_compensates(self) -> None:
        dry_snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            etp_capteur=3.0,
        )
        rainy_snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_demain=3.0,
            etp_capteur=3.0,
        )

        self.assertTrue(rainy_snapshot["arrosage_recommande"])
        self.assertLess(rainy_snapshot["objectif_mm"], dry_snapshot["objectif_mm"])
        self.assertEqual(rainy_snapshot["objectif_mm"], rainy_snapshot["decision_resume"]["objectif_mm"])
        self.assertLessEqual(rainy_snapshot["objectif_mm"], rainy_snapshot["objectif_mm_brut"])
        self.assertNotEqual(rainy_snapshot["action_recommandee"], dry_snapshot["action_recommandee"])

    def test_build_decision_snapshot_blocks_when_forecast_rain_covers_need(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=20,
            pluie_demain=10.0,
            etp_capteur=3.0,
        )

        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["fenetre_optimale"], "apres_pluie")
        self.assertEqual(snapshot["block_reason"], "pluie_prevue_suffisante")

    def test_build_decision_snapshot_normal_uses_soil_fractionation(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=30,
            humidite=45,
            type_sol="argileux",
            etp_capteur=4.5,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertGreaterEqual(snapshot["watering_passages"], 2)
        self.assertGreater(snapshot["watering_pause_minutes"], 0)

    def test_build_decision_snapshot_treatment_blocks_actions(self) -> None:
        snapshot = make_snapshot(
            history=[{"type": "Traitement", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            humidite=50,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["phase_active"], "Traitement")
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertEqual(snapshot["tonte_statut"], "interdite")
        self.assertEqual(snapshot["niveau_action"], "surveiller")
        self.assertEqual(snapshot["fenetre_optimale"], "attendre")
        self.assertEqual(snapshot["risque_gazon"], "faible")
        self.assertEqual(snapshot["prochaine_reevaluation"], "dans 24 h")
        self.assertEqual(snapshot["objectif_mm"], 0.0)

    def test_build_decision_snapshot_application_block_has_priority_over_traitement_phase(self) -> None:
        with patch.object(
            decision_watering,
            "compute_application_state",
            return_value={
                "derniere_application": {"type": "Traitement", "libelle": "Produit test"},
                "application_type": "sol",
                "application_requires_watering_after": False,
                "application_post_watering_mm": 0.0,
                "application_irrigation_block_hours": 24.0,
                "application_irrigation_delay_minutes": 0.0,
                "application_irrigation_mode": "auto",
                "application_label_notes": None,
                "application_post_watering_status": "bloque",
                "application_block_until": "2026-04-05T12:15:00+00:00",
                "application_block_active": True,
                "application_block_remaining_minutes": 60.0,
                "application_post_watering_pending": False,
                "application_post_watering_ready_at": None,
                "application_post_watering_delay_remaining_minutes": 0.0,
                "application_post_watering_ready": False,
                "application_post_watering_remaining_mm": 0.0,
            },
        ):
            snapshot = make_snapshot(
                history=[{"type": "Traitement", "date": "2026-04-04"}],
                today=date(2026, 4, 4),
                hour_of_day=10,
                temperature=18,
                humidite=50,
                etp_capteur=2.0,
            )

        self.assertTrue(snapshot["application_block_active"])
        self.assertIn("fenêtre de protection", snapshot["conseil_principal"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")

    def test_build_decision_snapshot_blocks_watering_and_mowing_when_raining(self) -> None:
        snapshot = make_snapshot(
            today=date(2026, 3, 17),
            hour_of_day=7,
            temperature=18,
            humidite=55,
            etp_capteur=2.0,
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )

        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["fenetre_optimale"], "apres_pluie")
        self.assertFalse(snapshot["tonte_autorisee"])

    def test_build_decision_snapshot_foliar_application_blocks_auto_watering(self) -> None:
        now = FIXED_HA_NOW_UTC
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Traitement",
                    "date": now.date().isoformat(),
                    "declared_at": (now - timedelta(hours=2)).isoformat(),
                    "produit": "Fongicide X",
                    "application_type": "foliaire",
                    "application_requires_watering_after": False,
                    "application_post_watering_mm": 0.0,
                    "application_irrigation_block_hours": 24.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "suggestion",
                    "application_label_notes": "Pas d'arrosage après application",
                }
            ],
            today=now.date(),
            hour_of_day=10,
            temperature=18,
            humidite=50,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_type"], "foliaire")
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["application_label_notes"], "Pas d'arrosage après application")
        self.assertEqual(snapshot["application_irrigation_mode"], "suggestion")

    def test_build_decision_snapshot_sol_application_uses_application_technique(self) -> None:
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Fertilisation",
                    "date": "2026-03-17",
                    "declared_at": "2026-03-17T08:00:00+00:00",
                    "produit": "Engrais printemps",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.2,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "auto",
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            humidite=55,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_type"], "sol")
        self.assertFalse(snapshot["application_block_active"])
        self.assertTrue(snapshot["application_post_watering_ready"])
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertTrue(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["type_arrosage"], "application_technique_auto")
        self.assertEqual(snapshot["arrosage_conseille"], "application_technique_auto")
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["decision_resume"]["type_arrosage"], "application_technique_auto")
        self.assertEqual(snapshot["decision_resume"]["moment"], "maintenant")
        self.assertEqual(snapshot["application_irrigation_mode"], "auto")

    def test_build_decision_snapshot_post_application_caps_passages_and_short_pause(self) -> None:
        # Canicule (temp 34, air sec, ETP élevé) : le fractionnement anti-ruissellement voudrait
        # 3 passages pour 5 mm. En post-application on plafonne à 2 passages avec une pause de 5 min
        # (incorporation produit, pas un déficit ; l'agent mouillant réduit déjà le ruissellement).
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Agent Mouillant",
                    "date": "2026-07-15",
                    "declared_at": "2026-07-15T08:00:00+00:00",
                    "produit": "H2Pro TriSmart",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 5.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "auto",
                }
            ],
            today=date(2026, 7, 15),
            hour_of_day=8,
            temperature=34,
            humidite=25,
            etp_capteur=6.0,
        )

        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["type_arrosage"], "application_technique_auto")
        self.assertLessEqual(snapshot["watering_passages"], 2)
        self.assertEqual(snapshot["watering_pause_minutes"], 5)

    def test_build_decision_snapshot_sol_application_manual_mode_requires_button(self) -> None:
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-17",
                    "declared_at": "2026-03-17T08:00:00+00:00",
                    "produit": "Bio Boost",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "manuel",
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            humidite=55,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_irrigation_mode"], "manuel")
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["type_arrosage"], "application_technique")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertIn("arrosage manuel immédiat", snapshot["conseil_principal"].lower())

    def test_build_decision_snapshot_sol_application_suggestion_mode_no_wait_zero(self) -> None:
        # Régression : application sol en mode "suggestion", délai d'incorporation écoulé (0 min).
        # Le drapeau `post_watering_ready` est TOUJOURS faux en suggestion (jamais de lancement auto),
        # donc l'ancienne branche affichait un absurde "attendre encore 0 min avant l'arrosage
        # technique". On doit à la place obtenir le message de suggestion "sans lancement automatique".
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Biostimulant",
                    "date": "2026-03-17",
                    "declared_at": "2026-03-17T08:00:00+00:00",
                    "produit": "Humuslight",
                    "application_type": "sol",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 3.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "suggestion",
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            humidite=55,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["application_irrigation_mode"], "suggestion")
        self.assertFalse(snapshot["application_block_active"])
        self.assertFalse(snapshot["application_post_watering_ready"])
        self.assertEqual(snapshot["application_post_watering_delay_remaining_minutes"], 0.0)
        self.assertEqual(snapshot["watering_cause"], "post_application")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        # Le bon message (suggestion) — et surtout PAS le "attendre encore 0 min".
        self.assertIn("suggéré, sans lancement automatique", snapshot["conseil_principal"])
        self.assertNotIn("attendre encore", snapshot["conseil_principal"])

    def test_build_decision_snapshot_unknown_application_type_blocks_auto_watering(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[
                {
                    "type": "Sursemis",
                    "date": "2026-03-17",
                    "declared_at": "2026-03-17T08:00:00+00:00",
                    "produit": "Produit inconnu",
                    "application_requires_watering_after": True,
                    "application_post_watering_mm": 1.0,
                    "application_irrigation_block_hours": 0.0,
                    "application_irrigation_delay_minutes": 0.0,
                }
            ],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertNotIn("application_type", snapshot)
        self.assertFalse(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertIn("type d'application inconnu", snapshot["conseil_principal"].lower())

class TestDecisionSnapshotSursemisAndHeatStress(unittest.TestCase):
    def test_build_decision_snapshot_sursemis_mentions_passage_interval(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertEqual(snapshot["type_arrosage"], "manuel_frequent")
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertLessEqual(snapshot["objectif_mm"], snapshot["objectif_mm_brut"])
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["watering_target_date"], "2026-03-17")
        self.assertEqual(snapshot["next_action_date"], "2026-03-17")
        self.assertEqual(snapshot["next_action_display"], "17/03/2026")
        self.assertIn("cycle de surface", snapshot["action_recommandee"])
        self.assertIn("1.5 mm", snapshot["action_recommandee"])

    def test_build_decision_snapshot_sursemis_projects_next_mowing_date(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Sursemis", "date": "2026-03-17"}],
            today=date(2026, 3, 17),
            hour_of_day=10,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        self.assertFalse(snapshot["tonte_autorisee"])
        self.assertEqual(snapshot["next_mowing_date"], "2026-04-11")
        self.assertEqual(snapshot["next_mowing_display"], "11/04/2026")
        self.assertEqual(snapshot["raison_blocage_code"], "phase_sursemis")

    def test_build_decision_snapshot_distinguishes_canicule_phases(self) -> None:
        short = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=31,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=40,
            type_sol="limoneux",
            etp_capteur=4.2,
        )
        prolonged = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=35,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=25,
            type_sol="limoneux",
            etp_capteur=5.5,
        )
        recovery = decision.build_decision_snapshot(
            history=[],
            today=date(2026, 7, 20),
            hour_of_day=8,
            temperature=35,
            pluie_24h=0.0,
            pluie_demain=8.0,
            humidite=25,
            type_sol="limoneux",
            etp_capteur=5.5,
            pluie_3j=8.0,
        )

        self.assertEqual(short["heat_stress_phase"], "stress_court")
        self.assertEqual(prolonged["heat_stress_phase"], "stress_prolonge")
        self.assertEqual(recovery["heat_stress_phase"], "sortie_de_stress")
        self.assertGreater(short["objectif_mm"], 0.0)
        self.assertGreater(prolonged["objectif_mm"], short["objectif_mm"])
        self.assertEqual(recovery["objectif_mm"], 0.0)
        self.assertEqual(recovery["type_arrosage"], "bloque")

    def test_build_watering_bundle_exposes_stable_core_keys_across_paths(self) -> None:
        expected_keys = {
            "objectif_mm",
            "objectif_mm_brut",
            "deficit_brut_mm",
            "deficit_mm_brut",
            "deficit_mm_ajuste",
            "mm_cible",
            "mm_final_recommande",
            "mm_final",
            "mm_requested",
            "mm_applied",
            "mm_detected",
            "arrosage_recommande",
            "arrosage_auto_autorise",
            "type_arrosage",
            "arrosage_conseille",
            "decision_resume",
            "raison_decision",
            "watering_passages",
            "watering_pause_minutes",
            "watering_target_date",
            "block_reason",
            "weekly_guardrail_mm_min",
            "weekly_guardrail_mm_max",
            "weekly_guardrail_reason",
            "soil_profile",
            "soil_retention_factor",
            "soil_drainage_factor",
            "soil_infiltration_factor",
            "soil_need_factor",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_window_optimal_start_minute",
            "watering_window_optimal_end_minute",
            "watering_window_acceptable_end_minute",
            "application_type",
            "application_post_watering_status",
        }

        contexts = [
            decision.DecisionContext.from_legacy_args(
                history=[],
                today=date(2026, 3, 17),
                hour_of_day=8,
                temperature=20,
                pluie_24h=0,
                pluie_demain=0,
                humidite=60,
                type_sol="limoneux",
                etp_capteur=3.0,
            ),
            decision.DecisionContext.from_legacy_args(
                history=[{"type": "Traitement", "date": "2026-03-17"}],
                today=date(2026, 3, 17),
                hour_of_day=8,
                temperature=18,
                pluie_24h=0,
                pluie_demain=0,
                humidite=55,
                type_sol="limoneux",
                etp_capteur=2.0,
            ),
        ]

        for context in contexts:
            phase_bundle = decision.build_phase_bundle(context)
            water_bundle = decision.build_water_bundle(context, phase_bundle)
            risk_bundle = decision.build_risk_bundle(context, phase_bundle, water_bundle)
            mowing_bundle = decision.build_mowing_bundle(context, phase_bundle, water_bundle, risk_bundle)
            bundle = decision_watering.build_watering_bundle(
                context, phase_bundle, water_bundle, risk_bundle, mowing_bundle
            )
            self.assertTrue(expected_keys.issubset(bundle.keys()))
    def test_build_water_bundle_dynamic_guardrail_varies_with_season(self) -> None:
        winter_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 1, 15),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        summer_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 7, 15),
            hour_of_day=7,
            temperature=20,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=3.0,
        )
        winter_phase = decision.build_phase_bundle(winter_context)
        summer_phase = decision.build_phase_bundle(summer_context)
        winter_water = decision.build_water_bundle(winter_context, winter_phase)
        summer_water = decision.build_water_bundle(summer_context, summer_phase)

        self.assertLess(winter_water["weekly_guardrail_mm_min"], summer_water["weekly_guardrail_mm_min"])
        self.assertLess(winter_water["weekly_guardrail_mm_max"], summer_water["weekly_guardrail_mm_max"])
        self.assertIn("saison=winter", winter_water["weekly_guardrail_reason"])
        self.assertIn("saison=summer", summer_water["weekly_guardrail_reason"])

    def test_build_water_bundle_exposes_month_profile_metadata(self) -> None:
        spring_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 15),
            hour_of_day=7,
            temperature=18,
            pluie_24h=0,
            pluie_demain=0,
            humidite=60,
            type_sol="limoneux",
            etp_capteur=2.0,
        )
        summer_context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 7, 15),
            hour_of_day=7,
            temperature=28,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=3.5,
        )

        spring_phase = decision.build_phase_bundle(spring_context)
        spring_water = decision.build_water_bundle(spring_context, spring_phase)
        spring_risk = decision.build_risk_bundle(spring_context, spring_phase, spring_water)
        spring_mowing = decision.build_mowing_bundle(spring_context, spring_phase, spring_water, spring_risk)
        spring_watering = decision_watering.build_watering_bundle(
            spring_context, spring_phase, spring_water, spring_risk, spring_mowing
        )

        summer_phase = decision.build_phase_bundle(summer_context)
        summer_water = decision.build_water_bundle(summer_context, summer_phase)
        summer_risk = decision.build_risk_bundle(summer_context, summer_phase, summer_water)
        summer_mowing = decision.build_mowing_bundle(summer_context, summer_phase, summer_water, summer_risk)
        summer_watering = decision_watering.build_watering_bundle(
            summer_context, summer_phase, summer_water, summer_risk, summer_mowing
        )

        self.assertEqual(spring_watering["season_phase"], "reveil_printanier")
        self.assertEqual(spring_watering["month_profile"], "relance_vegetative")
        self.assertEqual(summer_watering["season_phase"], "defense_estivale")
        self.assertEqual(summer_watering["month_profile"], "defense_thermique")
        self.assertIn("mois=relance_vegetative", spring_watering["weekly_guardrail_reason"])
        self.assertIn("mois=defense_thermique", summer_watering["weekly_guardrail_reason"])


class TestDecisionResultConstruction(unittest.TestCase):
    def test_build_decision_result_snapshot_matches_legacy_snapshot(self) -> None:
        kwargs = {
            "history": [{"type": "Traitement", "date": "2026-03-17"}],
            "today": date(2026, 3, 17),
            "hour_of_day": 8,
            "temperature": 18.0,
            "forecast_temperature_today": 19.5,
            "temperature_source": "capteur",
            "temperature_reference_hydrique": 18.8,
            "pluie_24h": 0.0,
            "pluie_demain": 0.0,
            "humidite": 55.0,
            "type_sol": "limoneux",
            "etp_capteur": 2.0,
            "rosee": 0.5,
            "weather_profile": {
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        }
        context = decision.DecisionContext.from_legacy_args(**kwargs)

        expected = decision.build_decision_snapshot(**kwargs)
        actual = decision.build_decision_result(context).to_snapshot()

        self.assertEqual(actual, expected)

    def test_compute_decision_preserves_legacy_output_contract(self) -> None:
        result = decision.compute_decision(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.2,
                "deficit_jour": 1.2,
                "deficit_3j": 2.0,
                "deficit_7j": 3.5,
            },
            advanced_context={
                "niveau_action": "a_faire",
                "fenetre_optimale": "maintenant",
                "risque_gazon": "modere",
                "prochaine_reevaluation": "dans 24 h",
                "urgence": "moyenne",
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            temperature=20.0,
            etp=2.0,
            objectif_mm=1.0,
            jours_restants=0,
            score_hydrique=42,
            score_stress=33,
            score_tonte=12,
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=8,
        )

        snapshot = result.to_snapshot()
        self.assertEqual(result.phase_dominante, "Normal")
        self.assertEqual(result.sous_phase, "Normal")
        self.assertEqual(snapshot["objectif_mm"], 1.0)
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertEqual(snapshot["fenetre_optimale"], "maintenant")
        self.assertEqual(snapshot["risque_gazon"], "modere")
        self.assertEqual(snapshot["jours_restants"], 0)

    def test_compute_decision_legacy_facade_preserves_window_metadata(self) -> None:
        result = decision.compute_decision(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -0.8,
                "deficit_jour": 0.8,
                "deficit_3j": 1.5,
                "deficit_7j": 2.5,
            },
            advanced_context={
                "niveau_action": "surveiller",
                "fenetre_optimale": "ce_matin",
                "risque_gazon": "faible",
                "prochaine_reevaluation": "dans 12 h",
                "urgence": "faible",
                "watering_window_start_minute": 240,
                "watering_window_end_minute": 600,
                "watering_window_profile": "mild",
                "watering_evening_allowed": False,
                "heat_stress_level": "normal",
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=50.0,
            temperature=18.0,
            etp=1.8,
            objectif_mm=0.5,
            jours_restants=1,
            score_hydrique=21,
            score_stress=10,
            score_tonte=5,
            history=[],
            today=date(2026, 3, 17),
            hour_of_day=7,
        )

        snapshot = result.to_snapshot()
        self.assertEqual(snapshot["fenetre_optimale"], "ce_matin")
        self.assertEqual(snapshot["watering_window_start_minute"], 240)
        self.assertEqual(snapshot["watering_window_end_minute"], 600)
        self.assertEqual(snapshot["watering_window_profile"], "mild")
        self.assertFalse(snapshot["watering_evening_allowed"])
        self.assertEqual(snapshot["heat_stress_level"], "normal")

    def test_decision_result_extra_cannot_override_canonical_snapshot_fields(self) -> None:
        result = decision.DecisionResult(
            phase_dominante="Normal",
            sous_phase="Normal",
            action_recommandee="Rien",
            action_a_eviter="Trop arroser",
            niveau_action="a_faire",
            fenetre_optimale="maintenant",
            risque_gazon="faible",
            objectif_arrosage=1.0,
            tonte_autorisee=True,
            extra={
                "phase_dominante": "Traitement",
                "objectif_mm": 9.9,
                "niveau_action": "critique",
                "custom_flag": True,
            },
        )

        snapshot = result.to_snapshot()

        self.assertEqual(snapshot["phase_dominante"], "Normal")
        self.assertEqual(snapshot["objectif_mm"], 1.0)
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertTrue(snapshot["custom_flag"])

    def test_decision_result_normalizes_invalid_structured_values_defensively(self) -> None:
        result = decision.DecisionResult(
            phase_dominante="bad-phase",
            sous_phase="bad-subphase",
            action_recommandee="Rien",
            action_a_eviter="Trop arroser",
            niveau_action="bad-level",
            fenetre_optimale="bad-window",
            risque_gazon="faible",
            objectif_arrosage=0.0,
            tonte_autorisee=True,
            tonte_statut="bad-mowing",
            type_arrosage="bad-watering",
            arrosage_conseille="",
        )

        snapshot = result.to_snapshot()

        self.assertEqual(result.phase_dominante, "Normal")
        self.assertEqual(result.sous_phase, "Normal")
        self.assertEqual(result.niveau_action, "a_faire")
        self.assertEqual(result.tonte_statut, "a_surveiller")
        self.assertEqual(result.fenetre_optimale, "attendre")
        self.assertEqual(result.type_arrosage, "personnalise")
        self.assertEqual(result.arrosage_conseille, "personnalise")
        self.assertEqual(snapshot["phase_dominante"], "Normal")
        self.assertEqual(snapshot["sous_phase"], "Normal")
        self.assertEqual(snapshot["niveau_action"], "a_faire")
        self.assertEqual(snapshot["fenetre_optimale"], "attendre")
        self.assertEqual(snapshot["type_arrosage"], "personnalise")

    def test_decision_result_aligns_arrosage_conseille_with_canonical_branch(self) -> None:
        result = decision.DecisionResult(
            phase_dominante="Normal",
            sous_phase="Normal",
            action_recommandee="Applique 5 mm",
            action_a_eviter="Rien",
            niveau_action="a_faire",
            fenetre_optimale="maintenant",
            risque_gazon="faible",
            objectif_arrosage=5.0,
            tonte_autorisee=True,
            type_arrosage="auto",
            arrosage_conseille="personnalise",
        )

        self.assertEqual(result.type_arrosage, "auto")
        self.assertEqual(result.arrosage_conseille, "auto")
        self.assertEqual(result.display_label_for("arrosage_conseille"), "Arrosage automatique")


class TestDecisionPhaseBundleRobustness(unittest.TestCase):
    def test_build_phase_bundle_clamps_incoherent_progression_and_age(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            temperature=18.0,
        )
        with patch.object(
            decision_phase,
            "compute_dominant_phase",
            return_value={
                "phase_dominante": "",
                "date_debut": "2026-04-04",
                "date_fin": "2026-04-10",
                "age_jours": -3,
                "source": None,
            },
        ), patch.object(
            decision_phase,
            "compute_subphase",
            return_value={
                "sous_phase": "",
                "detail": None,
                "age_jours": -7,
                "progression": 145.0,
            },
        ):
            bundle = decision_phase.build_phase_bundle(context)

        self.assertEqual(bundle["phase_dominante"], "Normal")
        self.assertEqual(bundle["phase_dominante_source"], "inconnu")
        self.assertEqual(bundle["phase_age_days"], 0)
        self.assertEqual(bundle["sous_phase"], "Normal")
        self.assertEqual(bundle["sous_phase_detail"], "Normal")
        self.assertEqual(bundle["sous_phase_age_days"], 0)
        self.assertEqual(bundle["sous_phase_progression"], 100.0)

    def test_build_phase_bundle_never_exposes_negative_remaining_days_or_invalid_end_date(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            temperature=18.0,
        )
        with patch.object(
            decision_phase,
            "compute_dominant_phase",
            return_value={
                "phase_dominante": "Traitement",
                "date_debut": "2026-04-01",
                "date_fin": "not-a-date",
                "age_jours": 3,
                "source": "historique_actif",
            },
        ), patch.object(
            decision_phase,
            "compute_subphase",
            return_value={
                "sous_phase": "Application",
                "detail": "Traitement / Application",
                "age_jours": 1,
                "progression": -12.0,
            },
        ), patch.object(
            decision_phase,
            "compute_jours_restants_for",
            return_value=-5,
        ):
            bundle = decision_phase.build_phase_bundle(context)

        self.assertIsNone(bundle["date_fin"])
        self.assertEqual(bundle["jours_restants"], 0)
        self.assertEqual(bundle["sous_phase_progression"], 0.0)


class TestDecisionRiskRobustness(unittest.TestCase):
    def test_build_risk_bundle_tolerates_partial_input_bundles(self) -> None:
        context = decision.DecisionContext.from_legacy_args(
            history=[],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=18.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            type_sol="limoneux",
            etp_capteur=2.0,
        )

        risk_bundle = decision.build_risk_bundle(
            context,
            {"phase_dominante": "Normal"},
            {"objectif_mm": 0.0},
        )

        self.assertIn("scores", risk_bundle)
        self.assertIn("niveau_action", risk_bundle)
        self.assertIn("fenetre_optimale", risk_bundle)
        self.assertIn("risque_gazon", risk_bundle)
        self.assertIn("urgence", risk_bundle)
        self.assertEqual(risk_bundle["urgence"], "faible")

    def test_decision_urgence_normalizes_unknown_text_inputs(self) -> None:
        urgence = decision_risk._decision_urgence(
            phase_dominante="Normal",
            arrosage_recommande=False,
            niveau_action="BAD_LEVEL",
            risque_gazon="UNKNOWN",
            bilan_hydrique_mm=0.1,
            pluie_demain=None,
        )

        self.assertEqual(urgence, "faible")


class TestObjectiveAndGuidance(unittest.TestCase):
    def test_compute_objectif_mm_sursemis_returns_micro_apport_when_conditions_are_met(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": 0.8,
                "deficit_3j": 1.5,
                "deficit_7j": 3.0,
            },
            today=date(2026, 3, 17),
            pluie_24h=0.0,
            pluie_demain=0,
            humidite=50,
            temperature=18.0,
            etp=1.4,
            type_sol="limoneux",
            weather_profile={
                "weather_precipitation_probability": 40.0,
            },
        )

        self.assertEqual(objectif, 3.0)

    def test_compute_objectif_mm_blocks_sursemis_when_balance_is_high(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": 10.8,
                "deficit_3j": 2.8,
                "deficit_7j": 8.6,
            },
            today=date(2026, 3, 17),
            pluie_24h=0.0,
            pluie_demain=0,
            humidite=50,
            temperature=18.7,
            etp=1.4,
            type_sol="limoneux",
            weather_profile={
                "weather_precipitation_probability": 20.0,
            },
        )

        self.assertEqual(objectif, 0.0)

    def test_compute_objectif_mm_returns_zero_when_weather_is_rainy(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.2,
                "deficit_3j": 2.0,
                "deficit_7j": 3.5,
            },
            today=date(2026, 3, 17),
            pluie_demain=0.0,
            humidite=55.0,
            temperature=18.0,
            etp=2.0,
            type_sol="limoneux",
            weather_profile={
                "weather_condition": "rainy",
                "weather_precipitation_probability": 90.0,
            },
        )

        self.assertEqual(objectif, 0.0)

    def test_build_decision_snapshot_normal_blocks_with_24h_cooldown(self) -> None:
        now = FIXED_HA_NOW_UTC
        today = FIXED_HA_TODAY
        snapshot = make_snapshot(
            history=[
                {"type": "Normal", "date": today.isoformat()},
                {
                    "type": "arrosage",
                    "date": today.isoformat(),
                    "recorded_at": (now - timedelta(hours=12)).isoformat(),
                    "total_mm": 12.0,
                },
            ],
            today=today,
            hour_of_day=8,
            temperature=18.0,
            humidite=55.0,
            etp_capteur=2.0,
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["type_arrosage"], "bloque")
        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertIn(snapshot["block_reason"], {"cooldown_24h", "sol_deja_humide"})
        self.assertIn("Cooldown", snapshot["raison_decision"])

    def test_build_decision_snapshot_normal_uses_daily_balance_even_with_positive_soil_reserve(self) -> None:
        today = date(2026, 3, 17)
        snapshot = make_snapshot(
            history=[{"type": "Normal", "date": today.isoformat()}],
            today=today,
            hour_of_day=8,
            temperature=18.0,
            humidite=55.0,
            etp_capteur=2.0,
            soil_balance={"reserve_mm": 6.0},
        )

        self.assertEqual(snapshot["phase_active"], "Normal")
        self.assertEqual(snapshot["reserve_hydrique_sol_mm"], 6.0)
        self.assertLess(snapshot["bilan_hydrique_mm"], 0.0)
        self.assertEqual(snapshot["type_arrosage"], "personnalise")
        self.assertIsNone(snapshot.get("block_reason"))
        self.assertGreater(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["watering_strategy"], "adult_deep")
        self.assertEqual(snapshot["objective_scope"], "global_surface")
        self.assertEqual(snapshot["watering_stage"], "normal")
        self.assertNotIn("surface_cycle_mm", snapshot)
        self.assertNotIn("daily_cycles_target", snapshot)
        self.assertNotIn("cycle_spacing_minutes", snapshot)
        self.assertNotIn("Sol déjà humide", snapshot["raison_decision"])
        self.assertNotIn("sol_deja_humide", snapshot["raison_decision"])

    def test_build_decision_snapshot_normal_urgence_uses_daily_balance_when_soil_reserve_is_positive(self) -> None:
        snapshot = decision.build_decision_snapshot(
            history=[{"type": "Normal", "date": "2026-04-04"}],
            today=date(2026, 4, 4),
            hour_of_day=8,
            temperature=14.6,
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=60.0,
            type_sol="limoneux",
            etp_capteur=0.9,
            soil_balance={
                "reserve_mm": 15.8,
                "previous_reserve_mm": 16.7,
                "pluie_mm": 0.0,
                "arrosage_mm": 0.0,
                "etp_mm": 0.9,
                "delta_mm": -0.9,
            },
        )

        self.assertEqual(snapshot["objectif_mm"], 0.0)
        self.assertEqual(snapshot["type_arrosage"], "aucune_action")
        self.assertEqual(snapshot["arrosage_conseille"], "aucune_action")
        self.assertLess(snapshot["bilan_hydrique_mm"], 0.0)
        self.assertGreater(snapshot["reserve_hydrique_sol_mm"], 0.0)
        self.assertEqual(snapshot["urgence"], "moyenne")

    def test_compute_objectif_mm_blocks_when_three_day_rain_horizon_is_significant(self) -> None:
        objectif = decision.compute_objectif_mm(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -0.6,
                "deficit_3j": 2.1,
                "deficit_7j": 3.5,
            },
            today=date(2026, 3, 17),
            pluie_demain=0.0,
            humidite=55.0,
            temperature=18.0,
            etp=2.0,
            type_sol="limoneux",
            pluie_j2=1.8,
            pluie_3j=4.8,
        )

        self.assertEqual(objectif, 0.0)

    def test_build_decision_snapshot_sursemis_is_capped_by_mode_floor(self) -> None:
        today = date(2026, 3, 17)
        snapshot = make_snapshot(
            history=[{"type": "Sursemis", "date": today.isoformat()}],
            today=today,
            hour_of_day=10,
            temperature=18.0,
            etp_capteur=0.0,
            soil_balance={"reserve_mm": -1.0},
        )

        self.assertEqual(snapshot["phase_active"], "Sursemis")
        self.assertEqual(snapshot["type_arrosage"], "manuel_frequent")
        self.assertEqual(snapshot["objectif_mm"], 1.5)
        self.assertFalse(snapshot["arrosage_auto_autorise"])
        self.assertIsNone(snapshot.get("block_reason"))
        self.assertEqual(snapshot["watering_strategy"], "semis_frequent")
        self.assertEqual(snapshot["objective_scope"], "surface_cycle")
        self.assertIn("semis_frequent", snapshot["raison_decision"])
        self.assertIn("cycle de surface", snapshot["raison_decision"])

    def test_compute_action_guidance_sursemis_allows_daytime_micro_cycles(self) -> None:
        base_kwargs = dict(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "deficit_3j": 1.2,
                "deficit_7j": 2.4,
            },
            advanced_context={
                "vent": 8,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            temperature=18.0,
            etp=1.2,
            objectif_mm=0.5,
        )

        early = decision.compute_action_guidance(hour_of_day=3, **base_kwargs)
        acceptable = decision.compute_action_guidance(hour_of_day=6, **base_kwargs)
        afternoon = decision.compute_action_guidance(hour_of_day=14, **base_kwargs)
        evening = decision.compute_action_guidance(hour_of_day=19, **base_kwargs)

        self.assertEqual(early["fenetre_optimale"], "ce_matin")
        self.assertEqual(acceptable["fenetre_optimale"], "ce_matin")
        self.assertEqual(afternoon["fenetre_optimale"], "maintenant")
        self.assertEqual(evening["fenetre_optimale"], "demain_matin")

    def test_compute_action_guidance_adjusts_window_with_temperature(self) -> None:
        base_kwargs = dict(
            phase_dominante="Sursemis",
            sous_phase="Enracinement",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "deficit_3j": 1.2,
                "deficit_7j": 2.4,
            },
            advanced_context={
                "vent": 8,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=55.0,
            etp=1.2,
            objectif_mm=0.5,
            hour_of_day=6,
        )

        cool = decision.compute_action_guidance(temperature=8.0, **base_kwargs)
        hot = decision.compute_action_guidance(temperature=24.0, **base_kwargs)

        self.assertEqual(cool["watering_window_start_minute"], 600)
        self.assertEqual(cool["watering_window_end_minute"], 1020)
        self.assertEqual(cool["watering_window_optimal_start_minute"], 600)
        self.assertEqual(cool["watering_window_optimal_end_minute"], 1020)
        self.assertEqual(hot["watering_window_start_minute"], 600)
        self.assertEqual(hot["watering_window_end_minute"], 1020)
        self.assertEqual(hot["watering_window_optimal_start_minute"], 600)
        self.assertEqual(hot["watering_window_optimal_end_minute"], 1020)
        self.assertEqual(cool["watering_window_profile"], "cool")
        self.assertEqual(hot["watering_window_profile"], "hot")

    def test_compute_action_guidance_allows_evening_when_conditions_match(self) -> None:
        # En avril, le soir n'est autorisé qu'en cas de déficit critique (< -3.0 mm)
        guidance = decision.compute_action_guidance(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -3.5,  # Déficit critique pour autoriser le soir en avril
                "deficit_3j": 4.0,
                "deficit_7j": 7.0,
            },
            advanced_context={
                "vent": 6,
                "rosee": 0.0,
                "hauteur_gazon": 8.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=42.0,
            temperature=27.0,
            etp=4.4,
            objectif_mm=4.0,
            hour_of_day=19,
        )

        self.assertEqual(guidance["fenetre_optimale"], "soir")
        self.assertTrue(guidance["watering_evening_allowed"])
        self.assertEqual(guidance["watering_evening_start_minute"], 1080)
        self.assertEqual(guidance["watering_evening_end_minute"], 1200)

    def test_compute_action_guidance_prefers_after_rain_when_three_day_horizon_is_wet(self) -> None:
        guidance = decision.compute_action_guidance(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.0,
                "deficit_3j": 2.4,
                "deficit_7j": 4.2,
            },
            advanced_context={
                "vent": 6,
                "rosee": 0.0,
                "hauteur_gazon": 7.0,
            },
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=2.2,
            pluie_3j=5.0,
            pluie_probabilite_max_3j=85.0,
            humidite=55.0,
            temperature=18.0,
            etp=1.2,
            objectif_mm=0.5,
            hour_of_day=6,
        )

        self.assertEqual(guidance["fenetre_optimale"], "apres_pluie")

    def test_rain_signals_ignore_high_probability_when_quantity_is_trace(self) -> None:
        # Une averse de trace (0,8 mm) annoncée à 95 % ne doit PAS bloquer l'arrosage
        # d'un sol sec — c'était la cause d'un faux « pluie prévue suffisante ».
        compensatrice, proche = guidance_module._rain_signals(
            objective_reference_mm=12.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=0.8,
            pluie_3j=0.8,
            pluie_probabilite_max_3j=95.0,
        )
        self.assertFalse(compensatrice)
        self.assertFalse(proche)

    def test_rain_signals_block_when_high_probability_and_real_quantity(self) -> None:
        # Forte probabilité + quantité réelle (5 mm) → on considère la pluie suffisante.
        compensatrice, proche = guidance_module._rain_signals(
            objective_reference_mm=12.0,
            pluie_24h=0.0,
            pluie_demain=0.0,
            pluie_j2=2.2,
            pluie_3j=5.0,
            pluie_probabilite_max_3j=85.0,
        )
        self.assertTrue(compensatrice or proche)

    def test_evening_cooling_allowed_in_extreme_heat_with_drying_margin(self) -> None:
        # Chaleur extrême + air sec + coucher du soleil dans 2 h → petit arrosage de
        # rafraîchissement du soir autorisé (l'herbe sèchera avant la nuit).
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=30.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="severe",
            minutes_to_sunset=120,
        )
        self.assertTrue(allowed)

    def test_evening_cooling_allowed_even_with_healthy_reserve(self) -> None:
        # Canicule extrême + réserve SAINE (bilan positif) : le rafraîchissement du soir reste
        # autorisé (son but est de refroidir, pas de combler un déficit). Avant, le garde-fou
        # saison avril-septembre le bloquait dès que le bilan dépassait -3 mm.
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=35.0,
            water_balance={"bilan_hydrique_mm": 9.9, "deficit_3j": 0.0},
            objectif_mm=0.0,
            heat_stress_level="severe",
            minutes_to_sunset=180,
        )
        self.assertTrue(allowed)

    def test_evening_non_extreme_still_blocked_in_season_when_reserve_healthy(self) -> None:
        # Hors canicule, en saison de végétation, réserve saine → toujours bloqué (anti-maladies).
        allowed = guidance_module._evening_window_allowed(
            temperature=26.0,
            humidite=45.0,
            water_balance={"bilan_hydrique_mm": 9.9, "deficit_3j": 0.0},
            objectif_mm=0.0,
            heat_stress_level="fort",
            minutes_to_sunset=180,
        )
        self.assertFalse(allowed)

    def test_evening_window_allowed_close_to_sunset_in_canicule(self) -> None:
        # Nouvelle logique : en canicule, le rafraîchissement vise le coucher (-30 min) → être
        # proche du coucher n'est PLUS bloquant (la marge de séchage de 90 min ne vaut qu'hors
        # canicule, choix assumé : arroser au frais).
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=30.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="severe",
            minutes_to_sunset=30,
        )
        self.assertTrue(allowed)

    def test_evening_window_blocked_too_close_to_sunset_outside_canicule(self) -> None:
        # Hors canicule, la marge de séchage de 90 min reste impérative.
        allowed = guidance_module._evening_window_allowed(
            temperature=26.0,
            humidite=30.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="normal",
            minutes_to_sunset=60,
        )
        self.assertFalse(allowed)

    def test_evening_cooling_blocked_when_sunset_unknown(self) -> None:
        # Coucher du soleil inconnu (pas de capteur) → on s'abstient le soir en canicule.
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=30.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="severe",
            minutes_to_sunset=None,
        )
        self.assertFalse(allowed)

    def test_evening_cooling_blocked_when_humidity_high(self) -> None:
        # Air humide → séchage trop lent → pas d'arrosage du soir (risque maladie).
        allowed = guidance_module._evening_window_allowed(
            temperature=36.0,
            humidite=80.0,
            water_balance={"bilan_hydrique_mm": -10.0, "deficit_3j": 9.0},
            objectif_mm=4.0,
            heat_stress_level="severe",
            minutes_to_sunset=120,
        )
        self.assertFalse(allowed)

    def test_compute_action_guidance_exposes_stable_window_keys_across_paths(self) -> None:
        expected_keys = {
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
            "heat_stress_level",
            "heat_stress_phase",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_window_optimal_start_minute",
            "watering_window_optimal_end_minute",
            "watering_window_acceptable_end_minute",
            "watering_evening_start_minute",
            "watering_evening_end_minute",
            "watering_window_profile",
            "watering_evening_allowed",
        }
        variants = [
            dict(
                phase_dominante="Traitement",
                sous_phase="Application",
                water_balance={"bilan_hydrique_mm": 0.0, "deficit_3j": 0.0, "deficit_7j": 0.0},
                advanced_context={},
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=60.0,
                temperature=18.0,
                etp=1.0,
                objectif_mm=0.0,
                hour_of_day=10,
            ),
            dict(
                phase_dominante="Normal",
                sous_phase="Normal",
                water_balance={"bilan_hydrique_mm": -1.6, "deficit_3j": 2.1, "deficit_7j": 3.9},
                advanced_context={"vent": 6, "rosee": 0.0, "hauteur_gazon": 8.0},
                pluie_24h=0.0,
                pluie_demain=0.0,
                humidite=42.0,
                temperature=27.0,
                etp=4.4,
                objectif_mm=2.0,
                hour_of_day=19,
            ),
        ]

        for kwargs in variants:
            guidance = decision.compute_action_guidance(**kwargs)
            self.assertTrue(expected_keys.issubset(guidance.keys()))

    def test_fractionation_expands_above_two_mm(self) -> None:
        passages = decision_watering._soil_fractionation_passages(
            phase_dominante="Normal",
            sous_phase="Normal",
            type_sol="limoneux",
            objectif_mm=3.0,
            stress_level="modere",
            temperature=18.0,
            humidite=55.0,
            etp=2.0,
        )

        self.assertEqual(passages, 2)

    def test_fractionation_is_capped_to_three_passages(self) -> None:
        passages = decision_watering._soil_fractionation_passages(
            phase_dominante="Fertilisation",
            sous_phase="Reponse",
            type_sol="argileux",
            objectif_mm=10.0,
            stress_level="fort",
            temperature=32.0,
            humidite=30.0,
            etp=4.5,
        )

        self.assertEqual(passages, 3)


class TestAuditMinorFixes(unittest.TestCase):
    """Tests de non-régression des correctifs mineurs (audit 0.16.x)."""

    def test_phase_produit_type_arrosage_suit_auto_ok(self) -> None:
        # [17] Les branches phase produit (Scarification/Fertilisation/Agent Mouillant/Biostimulant)
        # figeaient type_arrosage="auto" ; elles doivent suivre auto_ok comme la branche générique
        # → "personnalise" quand l'arrosage auto est désactivé (config par défaut). Cas reproductible :
        # phase Scarification active, arrosage post-application NON requis (sinon chemin technique),
        # déficit réel → une des 4 branches identiques est exercée.
        snapshot = make_snapshot(
            history=[{"type": "Scarification", "date": "2026-03-16", "application_requires_watering_after": False}],
            today=date(2026, 3, 17),
            hour_of_day=8,
            temperature=28,
            humidite=30,
            etp_capteur=7.0,
        )
        self.assertEqual(snapshot["phase_active"], "Scarification")
        self.assertEqual(snapshot["watering_cause"], "hydrique")  # pas le chemin post-application
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertFalse(snapshot["arrosage_auto_autorise"])  # auto désactivé par défaut
        self.assertEqual(snapshot["type_arrosage"], "personnalise")  # et non "auto" figé

    def test_upcoming_watering_coordination_suit_heure_reelle(self) -> None:
        # [20] Le message affichait "ce matin" dès que la fenêtre était passée, y compris le soir.
        # Le moment doit suivre l'heure réelle (la fenêtre du soir de canicule existe aussi).
        water_bundle = {"arrosage_recommande": True, "watering_window_start_minute": 60}
        soir = decision_mowing.DecisionContext(history=[], today=date(2026, 7, 23), hour_of_day=20)
        niveau, message_soir = decision_mowing._upcoming_watering_coordination(soir, water_bundle)
        self.assertEqual(niveau, "discourage")
        self.assertIn("ce soir", message_soir)
        self.assertNotIn("ce matin", message_soir)
        matin = decision_mowing.DecisionContext(history=[], today=date(2026, 7, 23), hour_of_day=8)
        _, message_matin = decision_mowing._upcoming_watering_coordination(matin, water_bundle)
        self.assertIn("ce matin", message_matin)

    def test_raison_blocage_tonte_pas_de_motif_positif_si_blocage_arrosage(self) -> None:
        # [21] Application foliaire en phase Fertilisation : l'arrosage bloque la tonte alors que la
        # phase, elle, l'autorise. raison_blocage_tonte ne doit PAS afficher le motif POSITIF de
        # tonte ("Fenêtre tonte acceptable.") sur une tonte "interdite".
        now = FIXED_HA_NOW_UTC
        snapshot = make_snapshot(
            history=[
                {
                    "type": "Fertilisation",
                    "date": now.date().isoformat(),
                    "declared_at": (now - timedelta(hours=2)).isoformat(),
                    "produit": "Foliaire X",
                    "application_type": "foliaire",
                    "application_requires_watering_after": False,
                    "application_post_watering_mm": 0.0,
                    "application_irrigation_block_hours": 24.0,
                    "application_irrigation_delay_minutes": 0.0,
                    "application_irrigation_mode": "suggestion",
                }
            ],
            today=now.date(),
            hour_of_day=10,
            temperature=18,
            humidite=50,
            etp_capteur=2.0,
        )
        self.assertEqual(snapshot["application_type"], "foliaire")
        self.assertEqual(snapshot["tonte_statut"], "interdite")
        self.assertNotEqual(snapshot.get("raison_blocage_tonte"), "Fenêtre tonte acceptable.")
        self.assertTrue(snapshot.get("raison_blocage_tonte"))


class TestNextWateringEstimate(unittest.TestCase):
    """Estimation indicative du prochain jour d'arrosage (déplétion réserve → MAD)."""

    # ⚠️ L'estimation tient compte du DÉCLENCHEMENT À L'AUBE : l'arrosage part le matin du jour
    # où la réserve VA franchir le seuil MAD dans la journée (projection `déplétion + ETc
    # restant`), pas le lendemain. La marge utile est donc `réserve − MAD − une journée d'ETc`.
    # Sans ce retrait, l'estimation annonçait « demain » le matin même où l'arrosage partait.

    def test_pure_reserve_franchira_le_seuil_aujourdhui_est_imminent(self) -> None:
        # réserve 7,2 / MAD 6 / ETc 3,2 : la journée consomme 3,2 → on finit à 4,0, sous le
        # seuil 6. La projection d'aube franchit donc le seuil DÈS CE MATIN → 0 (imminent).
        self.assertEqual(water.estimate_days_until_watering(7.2, 6.0, 3.2), 0)

    def test_pure_full_reserve(self) -> None:
        # réserve pleine 12 / MAD 6 / ETc 3,2 → ceil((6 − 3,2) / 3,2) = 1
        self.assertEqual(water.estimate_days_until_watering(12.0, 6.0, 3.2), 1)

    def test_pure_exact_day_boundary(self) -> None:
        # 9,2 − 6 − 3,2 = 0 pile → la projection franchit le seuil ce matin → 0.
        self.assertEqual(water.estimate_days_until_watering(9.2, 6.0, 3.2), 0)
        # Juste au-dessus (9,3) : il reste une marge → 1 jour.
        self.assertEqual(water.estimate_days_until_watering(9.3, 6.0, 3.2), 1)

    def test_pure_at_or_below_mad_is_imminent(self) -> None:
        self.assertEqual(water.estimate_days_until_watering(6.0, 6.0, 3.2), 0)
        self.assertEqual(water.estimate_days_until_watering(5.0, 6.0, 3.2), 0)

    def test_pure_no_drying_returns_none(self) -> None:
        self.assertIsNone(water.estimate_days_until_watering(10.0, 6.0, 0.0))
        self.assertIsNone(water.estimate_days_until_watering(10.0, 6.0, 0.05))

    def test_pure_missing_data_returns_none(self) -> None:
        self.assertIsNone(water.estimate_days_until_watering(None, 6.0, 3.2))
        self.assertIsNone(water.estimate_days_until_watering(10.0, None, 3.2))
        self.assertIsNone(water.estimate_days_until_watering(10.0, 6.0, None))

    def test_snapshot_expose_survie_canicule_active(self) -> None:
        # PROPAGATION BOUT-EN-BOUT. `water_bundle` recopie les clés du profil UNE PAR UNE (pas de
        # `**watering_profile`) : une clé ajoutée dans `_profile_for_normal` sans être listée dans
        # `decision_watering` n'atteint JAMAIS les capteurs, sans la moindre erreur. C'est arrivé
        # à cet attribut au premier essai — vérifié seulement parce qu'il manquait en live.
        snapshot = make_snapshot(temperature=20, etp_capteur=1.0)
        self.assertIn("survie_canicule_active", snapshot)
        self.assertIsNotNone(snapshot["survie_canicule_active"])

    def test_snapshot_exposes_estimate_and_consistent_date(self) -> None:
        today = date(2026, 6, 15)
        snapshot = make_snapshot(
            today=today,
            hour_of_day=8,
            temperature=20,
            etp_capteur=1.0,
        )
        jours = snapshot.get("jours_avant_arrosage_estime")
        self.assertIsInstance(jours, int)
        self.assertGreaterEqual(jours, 0)
        # date exposée = aujourd'hui + jours estimés (cohérence bout-en-bout)
        self.assertEqual(
            snapshot.get("date_prochain_arrosage_estime"),
            (today + timedelta(days=jours)).isoformat(),
        )


class TestGuardrailDemandBased(unittest.TestCase):
    """Plafond hebdo piloté par la DEMANDE ETc en continu (fin des paliers « canicule »)."""

    def _cap(self, et0):
        _, maximum, reason = guidance_module._dynamic_weekly_guardrail(
            today=date(2026, 7, 15), phase_dominante="Normal", et0_mm=et0, soil_profile="limoneux",
        )
        return maximum, reason

    def test_cap_suit_et0_en_continu(self):
        # ET0 faible → plancher saisonnier ; ET0 moyen → au-dessus ; ET0 fort → borné au ceiling.
        max_low, _ = self._cap(2.0)
        max_mid, _ = self._cap(5.0)
        max_high, _ = self._cap(9.0)
        self.assertLess(max_low, max_mid)          # croît avec la demande
        self.assertLess(max_mid, max_high)
        # 7 × 5 × 0,8 × 1,15 = 32,2 (> base été 26)
        self.assertAlmostEqual(max_mid, 32.2, delta=0.2)
        # ET0 fort → demande ~58 → borné au plafond de sûreté.
        self.assertEqual(max_high, guidance_module._GUARDRAIL_CEILING_MM)

    def test_plancher_saisonnier_preserve(self):
        # ET0 faible : le plafond ne descend jamais SOUS la base saisonnière (juillet ≈ 26).
        max_low, reason = self._cap(1.0)
        self.assertGreaterEqual(max_low, 25.0)
        # La raison expose la demande, plus un palier thermique.
        self.assertIn("demande_etc=", reason)
        self.assertNotIn("phase=canicule", reason)


if __name__ == "__main__":
    unittest.main()

class TestNextWateringEstimateAfterTodaysWatering(unittest.TestCase):
    """Le jour d'un arrosage, l'estimation ne doit pas annoncer « aujourd'hui ».

    `estimate_days_until_watering` ne raisonne que sur la réserve : son `0` veut dire « la
    projection d'aube franchit le seuil ». Mais l'aube d'aujourd'hui est passée — le prochain
    déclenchement possible est celui de demain. Sans plancher, deux attributs publics se
    contredisaient (constaté le 29/07/2026) : `block_reason_label` annonçait « Cooldown 24 h »
    pendant que `date_prochain_arrosage_estime` affichait le jour même.
    """

    @staticmethod
    def _estimate(historique):
        snap = make_snapshot(
            history=historique,
            temperature=30.0,
            etp_capteur=7.0,
        )
        return (
            snap.get("jours_avant_arrosage_estime"),
            snap.get("date_prochain_arrosage_estime"),
        )

    def test_sans_arrosage_aujourdhui_l_estimation_reste_inchangee(self) -> None:
        jours, date_estimee = self._estimate([])
        self.assertIsNotNone(jours)
        # Non-régression : aucun plancher appliqué quand rien n'a été arrosé aujourd'hui.
        attendue = (FIXED_TODAY + timedelta(days=int(jours))).isoformat()
        self.assertEqual(date_estimee, attendue)

    def test_apres_un_arrosage_du_jour_l_estimation_repousse_a_demain(self) -> None:
        historique = [
            {
                "date": FIXED_TODAY.isoformat(),
                # Le type doit être en MINUSCULES : `_iter_recent_watering_items` filtre sur
                # `item.get("type") != "arrosage"`. Un « Arrosage » capitalisé est ignoré en
                # silence — piège rencontré en écrivant ce test.
                "type": "arrosage",
                "mm": 6.0,
                "source": "auto_irrigation",
            }
        ]
        jours, date_estimee = self._estimate(historique)

        self.assertIsNotNone(jours)
        self.assertGreaterEqual(int(jours), 1, "0 jour = « aujourd'hui », or l'aube est passée")
        self.assertNotEqual(
            date_estimee,
            FIXED_TODAY.isoformat(),
            "l'estimation ne peut pas désigner un jour déjà arrosé",
        )


class TestPauseReserveeAuxGrossesDoses(unittest.TestCase):
    """La pause de 25 min ne se justifie que sur une GROSSE dose (demande de Kévin, 29/07/2026).

    Elle existe pour laisser le premier passage s'infiltrer avant le second — un enjeu de
    ruissellement, qui ne se pose pas sur un petit volume. Or le fractionnement peut être imposé
    pour d'autres raisons (session maximale, budget hebdo saturé) : la pause s'appliquait alors à
    des doses modestes, rallongeant la séance pour rien et repoussant la fin hors du créneau frais.

    Base agronomique du seuil : le régime manuel éprouvé appliquait 8,8 à 10,0 mm en UN SEUL
    passage, 3×/semaine, gazon en pleine forme et sans ruissellement observé.
    """

    SCENARIOS = [
        dict(temperature=30, humidite=45, type_sol="argileux", etp_capteur=4.5),
        dict(temperature=28, humidite=50, type_sol="limoneux", etp_capteur=4.0),
        dict(temperature=22, humidite=60, type_sol="limoneux", etp_capteur=2.0),
        dict(temperature=18, humidite=70, type_sol="sableux", etp_capteur=1.5),
        dict(temperature=33, humidite=35, type_sol="sableux", etp_capteur=6.0),
        # DISCRIMINANT : produit 9,5 mm, soit entre l'ancien seuil (6) et le nouveau (10).
        # Sous l'ancienne règle cette dose était coupée en deux avec 25 min d'attente ;
        # c'est exactement le cas que Kévin arrosait en un seul passage depuis des années.
        dict(temperature=18, humidite=50, type_sol="sableux", etp_capteur=1.5),
    ]

    def test_une_pause_implique_toujours_une_grosse_dose(self) -> None:
        # INVARIANT, volontairement testé sur plusieurs profils plutôt que sur un cas choisi :
        # dès qu'une pause est posée, la dose doit atteindre le seuil qui la justifie.
        seuil = guidance_module.PAUSE_LONGUE_MIN_DOSE_MM
        vus_avec_pause = 0
        for params in self.SCENARIOS:
            snap = make_snapshot(**params)
            pause = snap.get("watering_pause_minutes") or 0
            dose = float(snap.get("mm_final") or 0.0)
            if pause > 0:
                vus_avec_pause += 1
                self.assertGreaterEqual(
                    dose, seuil,
                    f"pause de {pause} min sur une dose de {dose} mm ({params})",
                )
        self.assertGreater(vus_avec_pause, 0, "aucun scénario ne produit de pause : test creux")

    def test_une_petite_dose_ne_declenche_jamais_de_pause(self) -> None:
        for params in self.SCENARIOS:
            snap = make_snapshot(**params)
            dose = float(snap.get("mm_final") or 0.0)
            if 0 < dose < guidance_module.PAUSE_LONGUE_MIN_DOSE_MM:
                self.assertEqual(
                    snap.get("watering_pause_minutes") or 0, 0,
                    f"pause posée sur {dose} mm ({params})",
                )

    def test_le_seuil_de_fractionnement_suit_la_pratique_eprouvee(self) -> None:
        # Garde-fou explicite : ces valeurs sont agronomiques, pas techniques. Les changer
        # sans raison documentée doit faire échouer un test, pas passer inaperçu.
        self.assertEqual(guidance_module.FRACTIONNEMENT_NORMAL_SEUIL_MM, 10.0)
        self.assertEqual(guidance_module.PAUSE_LONGUE_MIN_DOSE_MM, 10.0)
        self.assertEqual(guidance_module.PAUSE_ENTRE_PASSAGES_MIN, 25)

    def test_une_dose_de_9_5_mm_part_en_un_seul_passage_sans_pause(self) -> None:
        # LE cas concret de la demande de Kévin, valeurs codées en dur exprès : sous l'ancienne
        # règle (seuil 6 mm, pause inconditionnelle), 9,5 mm était coupé en deux avec 25 minutes
        # d'attente — alors que c'est précisément la dose qu'il appliquait d'un trait depuis des
        # années sans ruissellement. Ce test échoue si quelqu'un rabaisse le seuil.
        snap = make_snapshot(temperature=18, humidite=50, type_sol="sableux", etp_capteur=1.5)

        self.assertAlmostEqual(float(snap["mm_final"]), 9.5, places=1)
        self.assertEqual(snap.get("watering_passages"), 1)
        self.assertEqual(snap.get("watering_pause_minutes") or 0, 0)


class TestProjectionTonteHeureMurale(unittest.TestCase):
    """La projection de tonte raisonne en heures de la vie courante, pas en UTC.

    « Pas de tonte après 18 h, report à 6 h le lendemain » : ces bornes étaient testées et écrites
    sur un instant UTC. En Europe/Paris l'été, le seuil se déclenchait donc à 20 h locales et le
    « 6 h » écrit valait 8 h locales — toute projection tombant entre 18 h et 20 h annonçait le
    mauvais jour sur la carte.
    """

    def test_un_instant_de_19h_locales_est_bien_vu_comme_le_soir(self) -> None:
        # 17:06 UTC = 19:06 à Paris en été. Sous l'ancien code, l'heure testée valait 17 → pas de
        # report ; en heure murale elle vaut 19 → report au lendemain matin.
        instant = datetime(2026, 7, 29, 17, 6, tzinfo=timezone.utc)

        mural = decision_mowing._as_wall_clock(instant)

        self.assertEqual(mural.hour, 19, "l'instant n'a pas été ramené à l'heure murale")
        self.assertGreaterEqual(mural.hour, 18, "le report du soir ne se déclencherait pas")
        self.assertLess(instant.hour, 18, "sans conversion, le seuil était manqué")

    def test_la_date_murale_peut_differer_de_la_date_utc(self) -> None:
        # 23:30 UTC le 29 = 01:30 le 30 à Paris. La date renvoyée est comparée à `context.today`,
        # qui est une date LOCALE : les deux doivent être dans le même référentiel.
        instant = datetime(2026, 7, 29, 23, 30, tzinfo=timezone.utc)

        mural = decision_mowing._as_wall_clock(instant)

        self.assertEqual(mural.date().isoformat(), "2026-07-30")
        self.assertEqual(instant.date().isoformat(), "2026-07-29")

    def test_un_instant_naif_est_laisse_tel_quel(self) -> None:
        # Repli : hors runtime Home Assistant (ou sur un instant sans fuseau), on ne convertit pas.
        naif = datetime(2026, 7, 29, 17, 6)
        self.assertIs(decision_mowing._as_wall_clock(naif), naif)


class TestArrosageSoirSecoursAtteignable(unittest.TestCase):
    """L'exception « déficit critique » du soir est VIVANTE — un audit l'avait crue morte.

    Sa condition se lit « le gazon n'a rien reçu de toute la semaine », pas « rien reçu
    aujourd'hui » : c'est un filet pour l'absence prolongée, l'arrosage coupé ou un blocage d'une
    semaine. Elle dort tant que l'arrosage fonctionne, ce qui est le fonctionnement attendu.
    """

    @staticmethod
    def _autorise(*, bilan=-5.0, recent=0.0, temp=26.0, hum=50.0):
        return guidance_module._evening_window_allowed(
            temperature=temp,
            humidite=hum,
            water_balance={"bilan_hydrique_mm": bilan, "arrosage_recent": recent},
            objectif_mm=6.0,
            heat_stress_level="vigilance",
            minutes_to_sunset=120.0,
        )

    def test_une_semaine_sans_eau_en_deficit_declenche_le_secours(self) -> None:
        self.assertTrue(self._autorise(recent=0.0))

    def test_un_arrosage_dans_la_semaine_referme_le_secours(self) -> None:
        self.assertFalse(self._autorise(recent=6.0))

    def test_le_seuil_tolere_une_trace_negligeable(self) -> None:
        # 0,2 mm sur sept jours = « rien », l'exception reste ouverte.
        self.assertTrue(self._autorise(recent=0.2))

    def test_un_bilan_sain_ne_declenche_pas_le_secours(self) -> None:
        self.assertFalse(self._autorise(bilan=-1.0))

    def test_il_faut_aussi_de_la_chaleur(self) -> None:
        self.assertFalse(self._autorise(temp=22.0))


class TestIncorporationCrediteLaReserve(unittest.TestCase):
    """L'arrosage d'incorporation post-produit crédite la réserve ; le rafraîchissement du soir non.

    Décision de Kévin (29/07/2026). L'incorporation a pour BUT de faire pénétrer le produit dans
    le sol : cette eau atteint la zone racinaire. Ne pas la compter sous-estimait la réserve de la
    dose d'incorporation et provoquait une recharge inutile le lendemain matin, en silence.
    Les 3 mm du rafraîchissement du soir, eux, s'évaporent pour refroidir le gazon — c'est leur
    fonction, et les compter ferait paraître le sol plus plein qu'il ne l'est.
    """

    JOUR = date(2026, 3, 17)
    HISTORIQUE = [
        {"type": "arrosage", "date": "2026-03-17", "mm": 6.0, "watering_cause": "hydrique",
         "source": "auto_irrigation"},
        {"type": "arrosage", "date": "2026-03-17", "mm": 8.0, "watering_cause": "post_application",
         "source": "auto_irrigation"},
        {"type": "arrosage", "date": "2026-03-17", "mm": 3.0,
         "watering_cause": "rafraichissement_soir", "source": "auto_irrigation"},
    ]

    def _total(self, **kw):
        return water.compute_recent_watering_mm(
            self.HISTORIQUE, today=self.JOUR, days=0, include_external=False, **kw
        )

    def test_le_credit_reserve_inclut_l_incorporation(self) -> None:
        self.assertEqual(self._total(include_incorporation=True), 14.0)  # 6 hydrique + 8 incorporation

    def test_le_credit_reserve_exclut_le_rafraichissement(self) -> None:
        # 3 mm de cooling absents des 14 : ils s'évaporent, ils ne rechargent pas.
        self.assertNotIn(3.0, {self._total(include_incorporation=True) - 6.0 - 8.0})
        self.assertEqual(self._total(include_incorporation=True), 14.0)

    def test_le_garde_fou_hebdo_ne_compte_que_la_recharge_deliberee(self) -> None:
        # Un produit ne doit pas grignoter le budget d'arrosage du gazon.
        self.assertEqual(self._total(), 6.0)

    def test_l_eau_reellement_recue_les_compte_tous(self) -> None:
        self.assertEqual(
            water.compute_recent_watering_mm(
                self.HISTORIQUE, today=self.JOUR, days=0, include_technical=True
            ),
            17.0,
        )


class BesoinMmTraverseLaChaineTests(unittest.TestCase):
    """`besoin_mm` doit survivre à TOUTE la chaîne, pas seulement être déclaré.

    Une première série de tests ne vérifiait que les DÉCLARATIONS (champ présent dans
    `DecisionResult`, clé listée par le capteur). Deux mutations coupant le câblage —
    `besoin_mm=None` dans le bundle d'arrosage, puis dans `decision.py` — passaient au vert.
    Ce test-ci part du point d'entrée réel, `build_decision_snapshot`.
    """

    def test_le_snapshot_porte_le_besoin(self) -> None:
        snapshot = make_snapshot(today=date(2026, 3, 17), hour_of_day=10,
                                 temperature=20, etp_capteur=3.0)
        self.assertIn("besoin_mm", snapshot, "la clé se perd avant le snapshot")
        self.assertIsNotNone(snapshot["besoin_mm"], "la clé arrive vide : câblage coupé")
        self.assertGreater(snapshot["besoin_mm"], 0.0)

    def test_le_besoin_survit_a_un_blocage(self) -> None:
        """Le cas de Kévin du 01/08/2026, reproduit de bout en bout.

        ⚠️ Ce test bloquait par le GARDE-FOU HEBDOMADAIRE jusqu'au 02/08/2026. Depuis, celui-ci
        se lève dès que le sol dépasse le seuil MAD (0.38.0) — c'est-à-dire exactement quand un
        besoin existe. Il ne peut donc plus servir à démontrer « blocage ⇒ dose nulle, besoin
        préservé ». On passe par l'humidité de l'air, qui bloque encore indépendamment du sol.

        ⚠️ Première version de ce test : elle bloquait par la PLUIE. Mauvaise fixture — une
        pluie annoncée ne fait pas que bloquer, elle SUPPRIME le besoin (déficit 1,1 mm).
        `besoin_mm` valait donc légitimement 0 et le test ne prouvait rien. La retenue
        hebdomadaire, elle, ne change rien à la soif du sol : c'est le seul cas où les deux
        valeurs doivent diverger.
        """
        historique = [
            {"type": "arrosage", "date": "2026-07-28", "total_mm": 12.0, "source": "auto_irrigation"},
            {"type": "arrosage", "date": "2026-07-29", "total_mm": 5.0, "source": "auto_irrigation"},
            {"type": "arrosage", "date": "2026-07-30", "total_mm": 8.1, "source": "auto_irrigation"},
        ]
        snapshot = make_snapshot(
            history=historique, today=date(2026, 8, 1), hour_of_day=12,
            temperature=26.1, etp_capteur=5.8, humidite=90.0,
            soil_balance={"reserve_mm": 4.2, "reserve_max_mm": 24.0},
        )
        self.assertTrue(snapshot["water_balance"]["reserve_from_soil_ledger"],
                        "la fixture ne passe pas par la branche déplétion")
        self.assertEqual(snapshot["block_reason"], "humidite_excessive")
        self.assertEqual(snapshot["objectif_mm"], 0.0, "la dose doit rester à zéro")
        self.assertAlmostEqual(snapshot["besoin_mm"], snapshot["depletion_mm"], places=1,
                               msg="le besoin a disparu avec le blocage")
        self.assertGreater(snapshot["besoin_mm"], 7.0)


class DeficitInconnuNeDeclenchePasLaRetenueTests(unittest.TestCase):
    """Un déficit INCONNU n'est pas un déficit nul.

    `compute_water_balance` faisait `etp or 0.0` : sans ET0, tous les déficits tombaient à 0.
    La retenue hebdomadaire exige `deficit_mm_ajuste < plancher` — condition automatiquement
    vraie sur du vide. Relevé sur l'installation le 01/08/2026, premier cycle d'un redémarrage :
    `bilan_hydrique_mm: 0`, `deficit_3j: 0`, `deficit_7j: 0`, motif `garde_fou_hebdomadaire`,
    alors que la déplétion du ledger valait 8,2 mm pour une réserve de 3,8 sur un seuil de 6,0.
    Sur une coupure plus longue du capteur, la même mécanique a supprimé l'objectif pendant
    20 minutes DANS la fenêtre d'arrosage (30/07, 08 h 13 → 08 h 33).
    """

    HIST = [
        {"type": "arrosage", "date": "2026-07-28", "total_mm": 12.0, "source": "auto_irrigation"},
        {"type": "arrosage", "date": "2026-07-29", "total_mm": 5.0, "source": "auto_irrigation"},
        {"type": "arrosage", "date": "2026-07-30", "total_mm": 8.1, "source": "auto_irrigation"},
    ]
    # ⚠️ Réserve 15,0 sur 24 → déplétion 0,375, SOUS le seuil MAD : la retenue hebdomadaire est
    # légitime et le reste. La fixture précédente (3,8 mm, ratio 0,68) encodait l'ancien
    # comportement — la retenue s'y appliquait sur un sol qui réclamait de l'eau, ce que la
    # 0.38.0 interdit. Elle est ensuite passée à 9,0 (« 0,25 sur une référence de 12 »), valeur
    # qui n'est PLUS confortable depuis que la déplétion se mesure depuis la capacité au champ
    # (9 sur 24 = 62 % épuisé). Le sol confortable, sur cette échelle, c'est 15 mm.
    SOL = {"reserve_mm": 15.0, "reserve_max_mm": 24.0}

    def _snap(self, **over):
        kw = dict(history=self.HIST, today=date(2026, 8, 1), hour_of_day=12,
                  temperature=26.1, etp_capteur=5.8, humidite=52.0, soil_balance=self.SOL)
        kw.update(over)
        return make_snapshot(**kw)

    def test_avec_et0_mesuree_la_retenue_fonctionne_toujours(self) -> None:
        """Garde-fou : le correctif ne doit pas désarmer la retenue légitime."""
        snap = self._snap()
        self.assertTrue(snap["water_balance"]["etp_connue"])
        self.assertEqual(snap["block_reason"], "garde_fou_hebdomadaire")

    def test_sans_et0_la_retenue_ne_se_declenche_plus(self) -> None:
        snap = self._snap(temperature=None, etp_capteur=None)
        self.assertFalse(snap["water_balance"]["etp_connue"],
                         "la fixture fournit encore une ET0")
        self.assertEqual(snap["deficit_3j"], 0.0, "prémisse : les déficits retombent à 0")
        # `to_snapshot` retire les clés nulles : l'absence de `block_reason` VAUT « aucun motif ».
        self.assertNotEqual(
            snap.get("block_reason"), "garde_fou_hebdomadaire",
            "la retenue se déclenche sur un déficit qui vaut 0 par défaut, pas par mesure",
        )
        # (Le besoin vaut 0 ici : la fixture décrit un sol CONFORTABLE, sous le seuil MAD.
        #  La préservation du besoin sous blocage est démontrée par `BesoinMmTraverseLaChaine`.)

    def test_le_commutateur_est_publie(self) -> None:
        """Sans lui, rien ne permet de savoir si les déficits sont mesurés ou nuls par défaut.

        ⚠️ Ce test ne regardait QUE le sous-dictionnaire `water_balance` et la déclaration dans
        `_objective_attrs_keys()`. Les deux étaient vraies — et les clés n'apparaissaient
        pourtant PAS sur l'entité, constaté sur l'installation le 02/08/2026 : les clés du bilan
        sont recopiées une par une au niveau RACINE du snapshot (`decision.py`), une cinquième
        liste blanche que personne ne vérifiait. On teste maintenant là où l'entité lit.
        """
        snap = self._snap()
        self.assertIn("etp_connue", snap["water_balance"])
        self.assertIn("reserve_from_soil_ledger", snap["water_balance"])
        self.assertIn("etp_connue", snap, "absente du niveau racine : l'entité ne la verra pas")
        self.assertIn("reserve_from_soil_ledger", snap,
                      "absente du niveau racine : l'entité ne la verra pas")

    def test_un_bilan_SANS_la_cle_garde_l_ancien_comportement(self) -> None:
        """Montée de version : un état persisté d'avant 0.36.0 n'a pas `etp_connue`.

        Le défaut par absence doit être VRAI — sinon la retenue hebdomadaire ne se
        déclencherait plus jamais sur ces états, ce qui serait un sur-arrosage silencieux,
        pire que le défaut corrigé.
        """
        profil = guidance_module.compute_watering_profile(
            phase_dominante="Normal", sous_phase="Normal",
            water_balance={
                "bilan_hydrique_mm": -1.0, "reserve_hydrique_sol_mm": 9.0,
                "reserve_actuelle_mm": 9.0, "reserve_minimale_mm": 6.0,
                "reserve_utile_mm": 12.0, "depletion_mm": 3.0, "depletion_ratio": 0.25,
                "mad_ratio": 0.5, "reserve_from_soil_ledger": True, "et0_mm": 5.8,
                "etc_mm": 4.6, "reserve_stock_mm": 9.0, "reserve_stock_max_mm": 24.0,
                "arrosage_recent_7j": 35.0,
                # PAS de clé `etp_connue` — c'est tout l'objet du test.
            },
            today=date(2026, 8, 1), pluie_24h=0.0, pluie_demain=0.0,
            humidite=52.0, temperature=26.1, etp=5.8, type_sol="limoneux",
            history=self.HIST,
        )
        self.assertEqual(profil["block_reason"], "garde_fou_hebdomadaire",
                         "un état sans la clé désarme la retenue")


class PluiePrevueNeBloquePasUnSolAssoiffeTests(unittest.TestCase):
    """Rejoue la nuit du 02/08/2026 — celle où le gazon a touché zéro.

    À 03 h 20, la prévision de pluie passe de 3,1 à 9,1 mm. `pluie_prevue_suffisante` se
    déclenche et l'objectif tombe de 8,6 à 0,0 mm ; il y reste jusqu'à 10 h 13, soit TOUTE la
    fenêtre d'arrosage (03:45–10:00). Au même instant l'intégration publiait
    `reserve_actuelle_mm: 1,2 sur 12`, `depletion_ratio: 0,90`, `hydric_state: critique`,
    `hydric_strategy: arroser rapidement en profondeur`, et 34,5 °C prévus pour la journée.
    Il est tombé 3,2 mm effectifs pour 4,8 consommés : la réserve a atteint 0,0 mm à 12 h 09.

    La pluie était le SEUL des cinq blocages sans échappatoire sur l'état du sol — et le seul
    fondé sur une prévision. Arbitrage de Kévin : « la pluie prévue n'est jamais sûre, je
    préfère arroser ».
    """

    @staticmethod
    def _profil(*, reserve_mm, pluie_demain, depletion_mm):
        wb = {
            "bilan_hydrique_mm": -0.4, "reserve_hydrique_sol_mm": reserve_mm,
            "reserve_actuelle_mm": reserve_mm, "reserve_minimale_mm": 6.0,
            "reserve_utile_mm": 12.0, "depletion_mm": depletion_mm,
            "depletion_ratio": round(depletion_mm / 12.0, 3), "mad_ratio": 0.5,
            "deficit_3j": 9.2, "deficit_7j": 3.7, "reserve_from_soil_ledger": True,
            "et0_mm": 5.4, "etc_mm": 4.3, "etp_connue": True,
            "reserve_stock_mm": reserve_mm, "reserve_stock_max_mm": 24.0,
            "et_elapsed_fraction": 0.0, "arrosage_recent_7j": 22.1,
        }
        return guidance_module.compute_watering_profile(
            phase_dominante="Normal", sous_phase="Normal", water_balance=wb,
            today=date(2026, 8, 2), pluie_24h=0.0, pluie_demain=pluie_demain,
            humidite=45.7, temperature=20.9, etp=5.4, type_sol="limoneux",
        )

    def test_la_nuit_du_02_08_le_sol_aurait_du_etre_arrose(self) -> None:
        p = self._profil(reserve_mm=1.2, pluie_demain=9.1, depletion_mm=10.8)
        self.assertNotEqual(
            p["block_reason"], "pluie_prevue_suffisante",
            "une prévision bloque encore un sol à 10 % de sa réserve",
        )
        self.assertGreater(p["mm_final_recommande"], 0.0, "aucune dose n'est prévue")

    def test_sur_un_sol_CONFORTABLE_la_pluie_bloque_toujours(self) -> None:
        """Garde-fou : le correctif ne doit pas supprimer l'économie d'un cycle inutile."""
        p = self._profil(reserve_mm=10.0, pluie_demain=9.1, depletion_mm=2.0)
        self.assertEqual(p["block_reason"], "pluie_prevue_suffisante")
        self.assertEqual(p["mm_final_recommande"], 0.0)

    def test_le_seuil_est_bien_le_MAD(self) -> None:
        """Juste sous le seuil : la pluie décide encore. Juste au-dessus : plus jamais."""
        sous = self._profil(reserve_mm=6.6, pluie_demain=9.1, depletion_mm=5.4)   # ratio 0,45
        au_dessus = self._profil(reserve_mm=5.4, pluie_demain=9.1, depletion_mm=6.6)  # 0,55
        self.assertEqual(sous["block_reason"], "pluie_prevue_suffisante")
        self.assertNotEqual(au_dessus["block_reason"], "pluie_prevue_suffisante")

    def test_le_garde_fonctionne_SANS_ledger(self) -> None:
        """Il ne peut que débloquer : le rendre dépendant du ledger le rendrait inerte.

        C'est exactement le défaut corrigé toute la semaine — un garde qui disparaît en
        silence quand sa source manque.
        """
        wb = {
            "bilan_hydrique_mm": -0.4, "reserve_hydrique_sol_mm": 1.2,
            "reserve_actuelle_mm": 1.2, "reserve_minimale_mm": 6.0,
            "reserve_utile_mm": 12.0, "depletion_mm": 10.8, "depletion_ratio": 0.9,
            "mad_ratio": 0.5, "deficit_3j": 9.2, "deficit_7j": 3.7,
            "reserve_from_soil_ledger": False,   # ← pas de ledger
            "et0_mm": 5.4, "etc_mm": 4.3, "etp_connue": True,
            "reserve_stock_mm": 1.2, "reserve_stock_max_mm": 24.0,
            "et_elapsed_fraction": 0.0, "arrosage_recent_7j": 22.1,
        }
        p = guidance_module.compute_watering_profile(
            phase_dominante="Normal", sous_phase="Normal", water_balance=wb,
            today=date(2026, 8, 2), pluie_24h=0.0, pluie_demain=9.1,
            humidite=45.7, temperature=20.9, etp=5.4, type_sol="limoneux",
        )
        self.assertNotEqual(p["block_reason"], "pluie_prevue_suffisante")

    def test_une_pluie_DEJA_TOMBEE_bloque_toujours(self) -> None:
        """On ne touche qu'à la PRÉVISION. La pluie réelle reste un fait, pas un pari."""
        wb = {
            "bilan_hydrique_mm": 8.0, "reserve_hydrique_sol_mm": 11.0,
            "reserve_actuelle_mm": 11.0, "reserve_minimale_mm": 6.0,
            "reserve_utile_mm": 12.0, "depletion_mm": 1.0, "depletion_ratio": 0.08,
            "mad_ratio": 0.5, "deficit_3j": 0.0, "deficit_7j": 0.0,
            "reserve_from_soil_ledger": True, "et0_mm": 5.4, "etc_mm": 4.3,
            "etp_connue": True, "reserve_stock_mm": 11.0, "reserve_stock_max_mm": 24.0,
            "et_elapsed_fraction": 0.0, "arrosage_recent_7j": 22.1,
        }
        p = guidance_module.compute_watering_profile(
            phase_dominante="Normal", sous_phase="Normal", water_balance=wb,
            today=date(2026, 8, 2), pluie_24h=18.0, pluie_demain=0.0,
            humidite=45.7, temperature=20.9, etp=5.4, type_sol="limoneux",
        )
        self.assertEqual(p["mm_final_recommande"], 0.0)


class GardeFouNeLaissePasLeSolPasserLeSeuilTests(unittest.TestCase):
    """Rejoue les matins du 31/07 et du 01/08/2026 — l'enchaînement qui a mené à zéro.

    La retenue hebdomadaire jugeait sur `deficit_mm_ajuste` (modèle LEGACY) alors que le
    déclenchement se fait sur la déplétion du LEDGER. Les deux divergent, et c'est la retenue
    qui gagnait :

      31/07 04:00 — réserve 8,6, ratio 0,28 sur 12 → `confort`   → blocage jugé LÉGITIME
      01/08 04:00 — réserve 5,4, ratio 0,55 sur 12 → `depletion` → blocage FAUTIF
                    déficit legacy 4,3 mm contre 6,6 mm de déplétion réelle : 2,3 mm d'écart.

    Sans eau le 01/08, le sol est arrivé au 02/08 à 1,2 mm, puis à ZÉRO à 12 h 09.

    ⚠️ RÉ-ANCRAGE. Depuis que la déplétion se mesure depuis la capacité au champ (stock max du
    ledger, 24 mm en limoneux) et non depuis la réserve d'ouverture de 12 mm, la réserve de
    8,6 mm du 31/07 n'est PLUS confortable : 15,4 mm de déplétion sur 24, soit 64 % — au-delà
    du seuil MAD. Le blocage du 31/07 n'était donc pas légitime non plus, et c'est cohérent avec
    la suite de l'histoire (zéro le 02/08). Le premier test garde son rôle — prouver que la
    retenue fonctionne encore sur un sol vraiment confortable — avec une réserve qui l'est
    vraiment sur la bonne échelle (15,0 sur 24 = 37 % de déplétion).
    """

    HIST = [
        {"type": "arrosage", "date": "2026-07-26", "total_mm": 12.0, "source": "auto_irrigation"},
        {"type": "arrosage", "date": "2026-07-28", "total_mm": 12.0, "source": "auto_irrigation"},
        {"type": "arrosage", "date": "2026-07-30", "total_mm": 8.1, "source": "auto_irrigation"},
    ]

    def _snap(self, reserve_mm):
        return make_snapshot(
            history=self.HIST, today=date(2026, 8, 1), hour_of_day=4,
            temperature=19.5, etp_capteur=5.5, humidite=62.5,
            soil_balance={"reserve_mm": reserve_mm, "reserve_max_mm": 24.0},
        )

    def test_le_31_07_la_retenue_reste_legitime(self) -> None:
        """Sol à 37 % de déplétion : confortable. Le garde-fou doit encore plafonner."""
        snap = self._snap(15.0)
        self.assertLess(snap["water_balance"]["depletion_ratio"],
                        snap["water_balance"]["mad_ratio"], "prémisse : sol sous le seuil")
        self.assertEqual(snap.get("block_reason"), "garde_fou_hebdomadaire")

    def test_le_01_08_le_sol_aurait_du_etre_arrose(self) -> None:
        """Sol à 55 % : au-delà du seuil. La retenue ne peut plus le laisser descendre."""
        snap = self._snap(5.4)
        self.assertGreaterEqual(snap["water_balance"]["depletion_ratio"],
                                snap["water_balance"]["mad_ratio"], "prémisse : sol au-delà")
        self.assertNotEqual(
            snap.get("block_reason"), "garde_fou_hebdomadaire",
            "la retenue bloque encore un sol qui a franchi son seuil de déclenchement",
        )
        self.assertGreater(snap["objectif_mm"], 0.0, "aucune dose n'est prévue")

    def test_la_retenue_n_est_PAS_videe_de_son_sens(self) -> None:
        """Le point délicat du correctif — vérifié à l'aube, pas en fin de journée.

        Le déclenchement se fait sur la déplétion PROJETÉE (réelle + ETc restante), la retenue
        sur la déplétion RÉELLE. Un sol encore confortable à l'aube mais qui aura soif ce soir
        déclenche donc — et reste retenable. Si les deux grandeurs coïncidaient, le garde-fou
        ne bloquerait plus jamais rien et le correctif reviendrait à le supprimer.

        ⚠️ Passe par le profil et non par `make_snapshot` : sans contexte solaire, ce dernier
        fixe `et_elapsed_fraction` à 1,0 (journée entièrement écoulée), la projection retombe
        alors sur la déplétion réelle et le test ne démontre plus rien.
        """
        wb = {
            "bilan_hydrique_mm": -1.0, "reserve_hydrique_sol_mm": 8.4,
            "reserve_actuelle_mm": 8.4, "reserve_minimale_mm": 6.0,
            "reserve_utile_mm": 12.0, "depletion_mm": 3.6, "depletion_ratio": 0.30,
            "mad_ratio": 0.5, "deficit_3j": 5.8, "deficit_7j": 15.0,
            "reserve_from_soil_ledger": True, "et0_mm": 5.5, "etc_mm": 4.4,
            "etp_connue": True, "reserve_stock_mm": 8.4, "reserve_stock_max_mm": 24.0,
            "et_elapsed_fraction": 0.0,          # ← à l'aube : toute l'ETc reste à venir
            "arrosage_recent_7j": 32.1,
        }
        projete = (wb["depletion_mm"] + wb["etc_mm"]) / wb["reserve_utile_mm"]
        self.assertLess(wb["depletion_ratio"], wb["mad_ratio"], "prémisse : sol confortable")
        self.assertGreaterEqual(projete, wb["mad_ratio"], "prémisse : il aura soif ce soir")

        profil = guidance_module.compute_watering_profile(
            phase_dominante="Normal", sous_phase="Normal", water_balance=wb,
            today=date(2026, 8, 1), pluie_24h=0.0, pluie_demain=0.0,
            humidite=62.5, temperature=19.5, etp=5.5, type_sol="limoneux",
            history=self.HIST,
        )
        self.assertEqual(
            profil["block_reason"], "garde_fou_hebdomadaire",
            "la retenue ne bloque plus rien : le correctif l'a vidée de son sens",
        )


class DeuxProprietesQueRienNeDoitCasserTests(unittest.TestCase):
    """Balayage systématique : les desserrages de la semaine ne font pas sur-arroser.

    Entre le 01/08 et le 04/08, TROIS verrous ont été desserrés — prévision de pluie (0.37.0),
    retenue hebdomadaire (0.38.0), réduction de dose par la pluie (0.39.0). Chacun a ses tests,
    aucun ne vérifiait la propriété qui compte vraiment : **on n'a pas ouvert la porte au
    sur-arrosage**. C'est le risque exact qu'on prend en retirant des blocages.

    Deux invariants, balayés sur 2 100 combinaisons (déplétion × cumul 7 j × pluie annoncée ×
    température/ET0) :

      P1  une dose n'est versée QUE si la déplétion projetée atteint le seuil MAD
      P2  la dose ne dépasse jamais la marge hebdomadaire — hors secours documentés
          (survie canicule ≥ 32 °C, ou réserve réellement vide ≥ 90 %)

    ⚠️ Un balayage qui ne trouve rien doit d'abord prouver qu'il sait trouver. Vérifié :
    neutraliser le seuil MAD lève 75 violations de P1, neutraliser le plafond hebdo en lève 560.
    """

    RATIOS = (0.0, 0.15, 0.30, 0.45, 0.49, 0.50, 0.55, 0.70, 0.85, 1.0)
    SEPT = (0.0, 10.0, 20.0, 25.0, 30.0, 40.0, 60.0)
    PLUIE = (0.0, 1.0, 2.5, 5.0, 9.0, 15.0)
    METEO = ((15.0, 2.5), (22.0, 4.0), (28.0, 5.5), (33.0, 7.5), (38.0, 9.0))
    UTILE = 12.0

    def _profil(self, ratio, sept, pluie, temp, et0):
        dep = round(self.UTILE * ratio, 2)
        wb = {
            "bilan_hydrique_mm": -dep, "reserve_hydrique_sol_mm": self.UTILE - dep,
            "reserve_actuelle_mm": self.UTILE - dep, "reserve_minimale_mm": 6.0,
            "reserve_utile_mm": self.UTILE, "depletion_mm": dep, "depletion_ratio": ratio,
            "mad_ratio": 0.5, "deficit_3j": dep, "deficit_7j": dep * 1.5,
            "reserve_from_soil_ledger": True, "et0_mm": et0, "etc_mm": et0 * 0.8,
            "etp_connue": True, "reserve_stock_mm": self.UTILE - dep,
            "reserve_stock_max_mm": 24.0, "et_elapsed_fraction": 0.0,
            "arrosage_recent_7j": sept,
        }
        return guidance_module.compute_watering_profile(
            phase_dominante="Normal", sous_phase="Normal", water_balance=wb,
            today=date(2026, 8, 4), pluie_24h=0.0, pluie_demain=pluie,
            humidite=55.0, temperature=temp, etp=et0, type_sol="limoneux",
        )

    def _balayage(self):
        import itertools
        for ratio, sept, pluie, (temp, et0) in itertools.product(
            self.RATIOS, self.SEPT, self.PLUIE, self.METEO
        ):
            p = self._profil(ratio, sept, pluie, temp, et0)
            if p["mm_final_recommande"] > 0:
                yield ratio, sept, pluie, temp, et0, p

    def test_P1_jamais_d_arrosage_sous_le_seuil(self) -> None:
        fautes = []
        for ratio, sept, pluie, temp, et0, p in self._balayage():
            projete = min(1.0, (self.UTILE * ratio + et0 * 0.8) / self.UTILE)
            if projete < 0.5:
                fautes.append(
                    f"ratio={ratio} 7j={sept} pluie={pluie} T={temp} ET0={et0} "
                    f"→ {p['mm_final_recommande']} mm pour une projection de {projete:.2f}"
                )
        self.assertEqual(fautes, [], f"{len(fautes)} arrosage(s) sous le seuil :\n" + "\n".join(fautes[:5]))

    def test_P2_jamais_au_dela_de_la_marge_hebdomadaire(self) -> None:
        fautes = []
        for ratio, sept, pluie, temp, et0, p in self._balayage():
            marge = max(0.0, p["weekly_guardrail_mm_max"] - sept)
            secours_autorise = ratio >= 0.9          # survie canicule OU réserve réellement vide
            if p["mm_final_recommande"] > marge + 0.05 and not secours_autorise:
                fautes.append(
                    f"ratio={ratio} 7j={sept} pluie={pluie} T={temp} ET0={et0} "
                    f"→ {p['mm_final_recommande']} mm pour une marge de {marge:.1f}"
                )
        self.assertEqual(fautes, [], f"{len(fautes)} dépassement(s) :\n" + "\n".join(fautes[:5]))

    def test_le_balayage_sait_trouver_quelque_chose(self) -> None:
        """Sans ceci, deux assertions vides passeraient pour une preuve.

        On vérifie que le balayage produit bien des cas d'arrosage à examiner : s'il n'en
        trouvait aucun, P1 et P2 seraient vraies par vacuité.
        """
        arrosages = sum(1 for _ in self._balayage())
        self.assertGreater(arrosages, 200, f"seulement {arrosages} cas d'arrosage balayés")


class AlerteNeSeTaitPasSousBlocageTests(unittest.TestCase):
    """Le diagnostic du gazon doit rester vrai quand un garde-fou retient l'eau.

    Défaut mesuré sur l'installation le 01/08/2026 : à 15:30:35, réserve 2,8 mm →
    `risque_gazon: eleve`, `niveau_action: critique`. Deux minutes plus tard, MÊME réserve,
    MÊME `hydric_state: critique`, mais `block_reason: garde_fou_hebdomadaire` → `faible` /
    `aucune_action`. Sur la fenêtre auditée, 19 h 34 sur 239 h d'`etat_hydrique: critique`
    coexistaient avec un risque annoncé faible. C'est ce qui a rendu invisibles les trois
    jours à 0 mm de réserve (31/07 → 02/08).
    """

    SOL_ASSOIFFE = {
        "bilan_hydrique_mm": -6.0,
        "deficit_3j": 9.0,
        "deficit_7j": 22.0,
        "reserve_actuelle_mm": 2.8,
        "reserve_utile_mm": 12.0,
        "reserve_minimale_mm": 6.0,
        "depletion_mm": 9.2,
        "depletion_ratio": 0.767,
        "mad_ratio": 0.5,
        "reserve_stock_mm": 2.8,
        "reserve_stock_max_mm": 24.0,
    }

    def _guidance(self, *, objectif_mm: float) -> dict:
        return decision.compute_action_guidance(
            phase_dominante="Normal",
            sous_phase="Normal",
            water_balance=dict(self.SOL_ASSOIFFE),
            advanced_context={"vent": 6.0, "rosee": 0.0, "hauteur_gazon": 6.0},
            pluie_24h=0.0,
            pluie_demain=0.0,
            humidite=45.0,
            temperature=30.0,
            etp=6.5,
            objectif_mm=objectif_mm,
            hour_of_day=15,
        )

    def test_le_risque_reste_vrai_quand_lobjectif_est_ramene_a_zero(self) -> None:
        """Même sol, seul l'objectif change : le diagnostic ne doit pas basculer."""
        libre = self._guidance(objectif_mm=9.2)
        bloque = self._guidance(objectif_mm=0.0)

        self.assertNotEqual(
            libre["risque_gazon"], "faible",
            "prémisse cassée : ce sol à 2,8 mm doit être diagnostiqué à risque",
        )
        self.assertEqual(
            bloque["risque_gazon"], libre["risque_gazon"],
            "le risque du gazon a changé alors que SEUL l'objectif a été ramené à 0 — "
            "l'alerte s'éteint parce que le blocage s'allume",
        )

    def test_le_niveau_daction_lui_retombe_bien_a_aucune_action(self) -> None:
        """Le diagnostic reste vrai, mais il n'y a effectivement rien à faire."""
        bloque = self._guidance(objectif_mm=0.0)
        self.assertEqual(bloque["niveau_action"], "aucune_action")

    def test_les_raisons_expliquent_le_niveau_quelles_accompagnent(self) -> None:
        """Interdit : « risque faible » justifié par « stress hydrique eleve »."""
        for objectif in (0.0, 9.2):
            with self.subTest(objectif_mm=objectif):
                g = self._guidance(objectif_mm=objectif)
                raisons = " ".join(g.get("risque_gazon_raisons") or [])
                if g["risque_gazon"] == "faible":
                    self.assertNotIn(
                        guidance_mod._LIBELLE_STRESS, raisons,
                        f"« faible » justifié par « {raisons} » — les deux sorties se "
                        "contredisent",
                    )

    def test_un_sol_confortable_nest_pas_alarme_comme_un_sol_sec(self) -> None:
        """Garde-fou inverse : on n'a pas simplement rendu tout le monde « eleve ».

        Note : à 30 °C ce sol confortable ressort « modere » et non « faible » — la chaleur
        pèse dans le diagnostic indépendamment de la réserve. Ce qui compte ici, c'est
        qu'il soit STRICTEMENT moins alarmant que le sol à 2,8 mm.
        """
        confort = dict(self.SOL_ASSOIFFE)
        confort.update(
            bilan_hydrique_mm=0.5, deficit_3j=0.0, deficit_7j=0.0,
            reserve_actuelle_mm=11.5, depletion_mm=0.5, depletion_ratio=0.042,
            reserve_stock_mm=11.5,
        )
        g = decision.compute_action_guidance(
            phase_dominante="Normal", sous_phase="Normal", water_balance=confort,
            advanced_context={"vent": 6.0, "rosee": 0.0, "hauteur_gazon": 6.0},
            pluie_24h=0.0, pluie_demain=0.0, humidite=45.0, temperature=30.0,
            etp=6.5, objectif_mm=0.0, hour_of_day=15,
        )
        GRAVITE = {"faible": 0, "modere": 1, "eleve": 2, "severe": 3}
        sec = self._guidance(objectif_mm=0.0)["risque_gazon"]
        self.assertLess(
            GRAVITE[g["risque_gazon"]], GRAVITE[sec],
            f"sol confortable ({g['risque_gazon']}) diagnostiqué aussi grave qu'un sol à "
            f"2,8 mm ({sec}) — le correctif a rendu le risque insensible à la réserve",
        )
        self.assertNotEqual(g["risque_gazon"], "eleve")


class RaisonsExpliquentLeNiveauTests(unittest.TestCase):
    """`_raisons_par_defaut` ne doit jamais justifier un niveau par son contraire.

    Relevé sur l'installation le 01/08/2026 à 15:32:44 et le 06/08 à 00:00:50 :
    `risque_gazon: "faible"` accompagné de `risque_gazon_raisons: ["stress hydrique eleve"]`.
    Deux sorties publiées côte à côte qui se contredisent — le lecteur doit choisir
    laquelle croire, et c'est exactement ce qui rend un diagnostic inutilisable.
    """

    def test_un_risque_faible_nest_jamais_justifie_par_un_stress_eleve(self) -> None:
        for niveau in ("eleve", "severe", "modere"):
            with self.subTest(heat_stress_level=niveau):
                raisons = guidance_mod._raisons_par_defaut(
                    risque_gazon="faible", heat_stress_level=niveau
                )
                self.assertNotIn(
                    guidance_mod._LIBELLE_STRESS, " ".join(raisons),
                    f"« faible » justifié par « {raisons} »",
                )
                self.assertTrue(raisons, "une raison vide est indistinguable d'un attribut absent")

    def test_le_stress_reste_publie_quand_il_explique_vraiment_le_niveau(self) -> None:
        """Garde-fou inverse : on n'a pas simplement supprimé le motif partout."""
        for risque in ("modere", "eleve", "severe"):
            with self.subTest(risque_gazon=risque):
                raisons = guidance_mod._raisons_par_defaut(
                    risque_gazon=risque, heat_stress_level="eleve"
                )
                self.assertIn(guidance_mod.libelle_stress("eleve"), " ".join(raisons))
                # Le libellé doit rester informatif : ni vide, ni réduit au seul niveau.
                self.assertIn("eleve", " ".join(raisons))
                self.assertGreater(len(guidance_mod._LIBELLE_STRESS), 3)

    def test_le_motif_de_blocage_prime_quand_il_est_fourni(self) -> None:
        raisons = guidance_mod._raisons_par_defaut(
            risque_gazon="faible", heat_stress_level="eleve",
            block_reason="garde_fou_hebdomadaire",
        )
        self.assertEqual(raisons, ["garde_fou_hebdomadaire"])


class LaMachineNEffacePasLeVerdictDuGazonTests(unittest.TestCase):
    """Une panne du robot ne doit pas transformer un « non » du gazon en « oui ».

    Mesuré sur l'installation le 06/08/2026, DOUZE MILLISECONDES d'écart :
        13:41:44.040  tondeuse vue      · mowing_spacing      · off · prochaine 08/08
        13:41:44.052  0 candidat        · machine_unavailable · ON  · prochaine 06/08
        13:41:54.177  tondeuse revue    · mowing_spacing      · off · prochaine 08/08
    Sur la fenêtre auditée, `tonte_autorisee` a été à `on` 49,77 h sur 241,28 h (20,6 %),
    en 82 épisodes dont 58 sous la minute, et 99 % de ce temps sous `machine_unavailable`.

    Deux mécanismes indépendants, tous deux corrigés ici :
      1. `reason_code` est remplacé par le motif MACHINE (voulu pour l'affichage), et le test
         d'autorisation lisait ce code déjà réécrit ;
      2. le verdict BLOQUANT de la fenêtre horaire était annulé par `and not mowing_blocked`,
         puis carrément écrasé par le motif machine juste avant d'être lu.
    """

    # Reproduit le cas du 06/08 13:41:44.052 : la tondeuse configurée n'est plus résolue,
    # donc la coordination n'est plus prête. C'est `tondeuse_prete` / `mower_coordination_ready`
    # que lit `_machine_unavailable_detail`, pas `mower_ready`.
    ROBOT_ABSENT = {
        "mower_resolution_state": "configured_missing",
        "mower_resolution_candidate_count": 0,
        "mower_presence_state": "inconnue",
        "mower_operation_state": "unknown",
        "mower_is_docked": False,
        "mower_is_outside": False,
        "mower_coordination_ready": False,
        "tondeuse_prete": False,
    }

    def _bundle(self, *, hour, mower_context=None, temperature=22.0, history=None):
        ctx = decision.DecisionContext.from_legacy_args(
            history=history if history is not None else [
                {"type": "tonte", "date": "2026-08-06"},
            ],
            today=date(2026, 8, 6),
            hour_of_day=hour,
            temperature=temperature,
            pluie_24h=0,
            pluie_demain=0,
            humidite=55,
            type_sol="limoneux",
            etp_capteur=4.0,
        )
        if mower_context is not None:
            ctx.mower_context = dict(mower_context)
        phase = decision.build_phase_bundle(ctx)
        water = decision.build_water_bundle(ctx, phase)
        risk = decision.build_risk_bundle(ctx, phase, water)
        return decision.build_mowing_bundle(ctx, phase, water, risk)

    def test_le_fixture_declenche_bien_machine_unavailable(self) -> None:
        """PRÉMISSE. Sans ça, tous les tests de cette classe seraient verts sans rien exercer."""
        absent = self._bundle(hour=13, mower_context=self.ROBOT_ABSENT)
        self.assertEqual(absent.get("mowing_block_reason_code"), "machine_unavailable")

    def test_un_espacement_de_tonte_survit_a_la_perte_de_vue_du_robot(self) -> None:
        """Tondu aujourd'hui : le gazon dit non. Perdre le robot ne doit rien y changer."""
        vu = self._bundle(hour=13)
        absent = self._bundle(hour=13, mower_context=self.ROBOT_ABSENT)

        self.assertFalse(vu["tonte_autorisee"], "prémisse : tondu aujourd'hui → non autorisé")
        self.assertFalse(
            absent["tonte_autorisee"],
            "le robot a disparu de la vue et le gazon s'est mis à dire oui — "
            f"motif publié : {absent.get('mowing_block_reason_code')}",
        )

    def test_la_nuit_bloque_meme_quand_le_robot_est_introuvable(self) -> None:
        """21:38, soleil couché, robot perdu : c'est la nuit qui doit l'emporter."""
        nuit = self._bundle(hour=23, mower_context=self.ROBOT_ABSENT, history=[])
        self.assertFalse(
            nuit["tonte_autorisee"],
            "tonte autorisée en pleine nuit parce que le robot était introuvable",
        )

    def test_le_motif_machine_reste_bien_celui_qui_est_AFFICHE(self) -> None:
        """On n'a pas inversé la priorité d'affichage : une panne prime sur un délai."""
        absent = self._bundle(hour=13, mower_context=self.ROBOT_ABSENT)
        self.assertTrue(absent.get("mowing_blocked"))
        self.assertIn("Robot", absent.get("mowing_block_reason_label") or "")

    def test_le_petit_matin_bloque_meme_sans_motif_agronomique(self) -> None:
        """Le cas que SEUL le garde de fenêtre peut attraper.

        À 8 h, le gazon n'a aucun motif de refus (pas de tonte récente, rien à redire) : le
        refus vient uniquement de la FENÊTRE (« Matin trop tôt »). Or ce verdict était annulé
        deux fois quand la machine tombait — `and not mowing_blocked` d'abord, puis
        l'écrasement de l'état de fenêtre par le motif machine. Sans robot visible, la tonte
        devenait donc autorisée à 8 h du matin sur un sol non ressuyé.
        """
        tot = self._bundle(hour=8, mower_context=self.ROBOT_ABSENT, history=[])
        self.assertEqual(
            tot.get("mowing_window_state"), "blocked",
            "prémisse : à 8 h la fenêtre doit être bloquée",
        )
        self.assertFalse(
            tot["tonte_autorisee"],
            "tonte autorisée à 8 h parce que le robot était introuvable — "
            "le verdict de la fenêtre a été perdu",
        )

    def test_le_gazon_dit_toujours_oui_pendant_que_la_machine_dit_non(self) -> None:
        """LE CONTRAT DES DEUX AXES, dans l'autre sens — on n'a pas tout bloqué.

        `tonte_autorisee` est le verdict du GAZON. En pleine journée, sur un gazon prêt, une
        panne du robot ne doit PAS le faire passer à non : c'est `machine_permet_tonte` qui
        porte l'état matériel, et `action_possible` qui combine les deux. Confondre les deux
        rendrait le capteur inutilisable dans l'autre sens.
        """
        absent = self._bundle(hour=11, temperature=20.0, mower_context=self.ROBOT_ABSENT,
                              history=[{"type": "tonte", "date": "2026-07-28"}])
        self.assertTrue(absent.get("mowing_blocked"), "prémisse : la machine bloque bien")
        self.assertTrue(
            absent["tonte_autorisee"],
            "le gazon s'est mis à dire non parce que le robot est en panne — "
            "les deux axes ont été confondus",
        )
        self.assertFalse(absent.get("action_possible"),
                         "action_possible doit rester faux : la machine ne suit pas")

    def test_un_gazon_qui_dit_oui_reste_autorise_quand_le_robot_va_bien(self) -> None:
        """Garde-fou inverse : on n'a pas simplement tout bloqué."""
        ok = self._bundle(hour=11, temperature=20.0, history=[
            {"type": "tonte", "date": "2026-07-28"},
        ])
        self.assertTrue(
            ok["tonte_autorisee"],
            f"gazon prêt et robot sain, pourtant refusé : {ok.get('raison_blocage_tonte')}",
        )


class LHeurePasseAvantLesVerdictsAEviterTests(unittest.TestCase):
    """`_resolve_mowing_window` : un « à éviter » ne doit pas couvrir un refus ferme.

    Les bornes horaires (avant 10 h, après 22 h) sont BLOQUANTES ; le vent soutenu et la
    chaleur ne font que déconseiller. Elles étaient testées APRÈS, donc par nuit d'été tiède
    la fenêtre publiait « Température élevée : à éviter » au lieu de « Nuit ».
    Relevé le 05/08/2026 à 21:38 et 21:40, soleil couché depuis 21:26.
    """

    def _fenetre(self, *, hour, temperature=None, vent=None):
        ctx = decision_mowing.DecisionContext(
            history=[], today=date(2026, 8, 6), hour_of_day=hour,
            temperature=temperature, vent=vent,
        )
        return decision_mowing._resolve_mowing_window(ctx, weather_profile={})

    def test_la_nuit_bloque_meme_par_temps_chaud(self) -> None:
        etat, motif = self._fenetre(hour=23, temperature=27.0)
        self.assertEqual(etat, "blocked")
        self.assertIn("Nuit", motif)

    def test_la_nuit_bloque_meme_par_vent_soutenu(self) -> None:
        etat, motif = self._fenetre(hour=23, vent=25.0)
        self.assertEqual(etat, "blocked")
        self.assertIn("Nuit", motif)

    def test_le_petit_matin_bloque_aussi_par_temps_chaud(self) -> None:
        """Le défaut ne touchait pas que la nuit : toute la plage 22 h → 10 h.

        ⚠️ Le LIBELLÉ attendu a changé le 01/09/2026. À 3 h du matin, ce test exigeait
        « Matin trop tôt : attendre le ressuyage » — un message de rosée en pleine nuit noire,
        qui contredisait le motif de blocage disant « Nuit » au même instant. L'INTENTION du
        test est conservée : l'heure passe toujours avant le verdict « à éviter » de la chaleur.
        """
        etat, motif = self._fenetre(hour=3, temperature=27.0)
        self.assertEqual(etat, "blocked")
        self.assertIn("Nuit", motif)
        self.assertNotIn("Température", motif, "la chaleur l'a emporté sur l'heure")

    def test_le_matin_trop_tot_garde_son_sens_apres_le_lever_du_soleil(self) -> None:
        """« Matin trop tôt » parle de ROSÉE, pas d'obscurité : il ne doit valoir qu'en clarté.

        Sans ce test, faire tomber toute la plage 00 h–10 h dans « Nuit » passerait inaperçu et
        le motif de ressuyage matinal disparaîtrait purement et simplement.
        """
        etat, motif = self._fenetre(hour=8, temperature=27.0)
        self.assertEqual(etat, "blocked")
        self.assertIn("Matin trop tôt", motif)

    def test_la_fenetre_ne_repete_pas_ce_que_le_motif_dit_deja(self) -> None:
        """Les faire concorder était le but ; les imprimer deux fois n'en faisait pas partie.

        Relevé le 01/09/2026 à 01:25, juste après avoir unifié les deux sources :
        « Nuit: attendre le lever du soleil. Fenêtre horaire: Nuit: attendre le lever du
          soleil. »
        """
        ctx = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 9, 1), hour_of_day=1,
            temperature=18.0, pluie_24h=0, pluie_demain=0, humidite=60,
            type_sol="limoneux", etp_capteur=3.0,
        )
        # `raison_blocage_tonte` est assemblée au niveau DÉCISION, pas dans le bundle tonte :
        # c'est la phrase publiée, celle que Kévin lit sur la carte.
        snapshot = decision.build_decision_result(ctx).to_snapshot()
        raison = snapshot.get("raison_blocage_tonte") or ""
        self.assertIn("Nuit", raison, "prémisse : on doit bien être bloqué pour la nuit")
        self.assertEqual(raison.count("attendre le lever du soleil"), 1,
                         f"le motif est répété : « {raison} »")

    def test_les_deux_sources_de_la_nuit_ne_se_contredisent_plus(self) -> None:
        """⚠️ RELEVÉ SUR L'INSTALLATION le 01/09/2026 à 00:48, dans une seule phrase publiée :

            « Nuit: attendre le lever du soleil. Fenêtre horaire: Matin trop tôt: attendre le
              ressuyage. »

        Le motif de blocage lisait le SOLEIL, la fenêtre lisait l'HEURE, et les deux étaient
        concaténés dans le message que lit l'utilisateur. Un fait, deux sources, deux réponses.
        Elles partagent désormais `_est_la_nuit`.
        """
        for heure in (0, 3, 6, 23):
            with self.subTest(heure=heure):
                ctx = decision.DecisionContext.from_legacy_args(
                    history=[], today=date(2026, 9, 1), hour_of_day=heure,
                    temperature=18.0, pluie_24h=0, pluie_demain=0, humidite=60,
                    type_sol="limoneux", etp_capteur=3.0,
                )
                _etat, motif_fenetre = decision_mowing._resolve_mowing_window(
                    ctx, weather_profile={}
                )
                self.assertIn("Nuit", motif_fenetre or "",
                              f"à {heure} h la fenêtre ne dit pas la nuit")

    def test_la_nuit_suit_le_soleil_avant_l_horloge(self) -> None:
        """Le soleil prime : une nuit d'été à 21 h 30 est une nuit, quoi qu'en dise l'horloge."""
        ctx = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 9, 1), hour_of_day=21,
            temperature=20.0, pluie_24h=0, pluie_demain=0, humidite=60,
            type_sol="limoneux", etp_capteur=3.0,
        )
        ctx.sun_context = {"sun_state": "below_horizon", "sun_below_horizon": True}
        _etat, motif = decision_mowing._resolve_mowing_window(ctx, weather_profile={})
        self.assertIn("Nuit", motif or "", "le soleil couché n'a pas primé sur l'horloge")

        # Et l'inverse : soleil levé à 6 h → ce n'est plus la nuit, c'est le petit matin.
        ctx.sun_context = {"sun_state": "above_horizon", "sun_above_horizon": True}
        _etat, motif = decision_mowing._resolve_mowing_window(ctx, weather_profile={})
        self.assertNotIn("Nuit", motif or "", "le soleil levé n'a pas primé sur l'horloge")

    def test_en_journee_la_chaleur_deconseille_toujours(self) -> None:
        """Garde-fou inverse : on n'a pas supprimé les verdicts « à éviter »."""
        etat, motif = self._fenetre(hour=13, temperature=27.0)
        self.assertEqual(etat, "discouraged")
        self.assertIn("Température élevée", motif)

    def test_une_fenetre_ideale_le_reste(self) -> None:
        etat, motif = self._fenetre(hour=11, temperature=20.0, vent=5.0)
        self.assertEqual(etat, "ideal")
        self.assertIn("idéale", motif)

    def test_un_blocage_dur_prime_toujours_sur_l_heure(self) -> None:
        """Ordre préservé : les refus fermes météo restent avant les bornes horaires."""
        etat, motif = self._fenetre(hour=23, temperature=35.0)
        self.assertEqual(etat, "blocked")
        self.assertIn("trop élevée", motif)


class AmortissementDuRisqueTests(unittest.TestCase):
    """⚠️ QUATORZE BASCULES `faible ↔ modere` le 31/08/2026, dont six entre 16 h et 18 h.

    `heat_stress_level` sort d'un score ENTIER où chaque facteur vaut +1 et où « vigilance »
    commence à 3 : n'importe quel facteur qui oscille fait basculer un RANG ENTIER. Vérifié ce
    jour-là, ce n'était ni le vent (6 à 8 km/h, seuil 15) ni l'humidité (62 à 71 %, seuil 40) —
    corriger un capteur n'aurait donc rien réglé, la fragilité est structurelle.

    Et ce n'est pas cosmétique : `risque_gazon` alimente `compute_next_reevaluation`.
    """

    def _suite(self, niveaux, memoire=None):
        """Rejoue une suite de niveaux BRUTS et rend la liste des niveaux PUBLIÉS."""
        publies = []
        for brut in niveaux:
            publie, memoire = guidance_mod.amortir_niveau_risque(brut, memoire)
            publies.append(publie)
        return publies, memoire

    def test_un_clignotement_ne_passe_pas(self) -> None:
        # La séquence réelle du 31/08 : modéré/faible en alternance rapide.
        publies, _ = self._suite(["faible", "modere", "faible", "modere", "faible"])
        self.assertEqual(publies, ["faible"] * 5,
                         "le clignotement traverse encore jusqu'à l'affichage")

    def test_un_changement_qui_TIENT_finit_par_passer(self) -> None:
        publies, _ = self._suite(["faible", "modere", "modere", "modere", "modere"])
        self.assertEqual(publies, ["faible", "faible", "faible", "modere", "modere"],
                         "un changement stable doit passer après trois cycles")

    def test_une_montee_vers_eleve_ne_se_retarde_JAMAIS(self) -> None:
        """⚠️ Le cœur du réglage : amortir n'est pas différer une alerte."""
        publies, _ = self._suite(["faible", "eleve"])
        self.assertEqual(publies[-1], "eleve", "une alerte a été retardée par l'amortissement")

    def test_la_descente_depuis_eleve_est_amortie(self) -> None:
        """Asymétrie assumée : on monte vite en alerte, on en redescend prudemment."""
        publies, _ = self._suite(["eleve", "faible", "faible"])
        self.assertEqual(publies, ["eleve", "eleve", "eleve"])
        publies2, _ = self._suite(["eleve", "faible", "faible", "faible"])
        self.assertEqual(publies2[-1], "faible", "la descente ne passe jamais")

    def test_le_premier_cycle_publie_ce_qu_il_voit(self) -> None:
        """Sans mémoire, on n'invente pas d'inertie — et une mémoire abîmée non plus."""
        for memoire in (None, {}, {"publie": "n_importe_quoi"}, "pas un dict"):
            with self.subTest(memoire=memoire):
                publie, _ = guidance_mod.amortir_niveau_risque("modere", memoire)
                self.assertEqual(publie, "modere")

    def test_l_amortissement_est_REELLEMENT_cable_et_persiste(self) -> None:
        """⚠️ UNE FONCTION CORRECTE MAIS NON BRANCHÉE N'EXISTE PAS.

        Le banc l'a montré une heure plus tôt sur le filtre des passes fantômes : tester le
        prédicat seul ne prouve rien. Ce test suit la mémoire du contexte jusqu'au bundle, et
        vérifie qu'elle est rangée ET relue dans le coordinateur.
        """
        source_risk = (PACKAGE_DIR / "decision_risk.py").read_text(encoding="utf-8")
        self.assertIn("amortir_niveau_risque(", source_risk,
                      "le bundle de risque n'appelle pas l'amortissement")
        # Amorti AVANT les deux consommateurs, sinon la décision travaille sur le brut.
        self.assertLess(source_risk.index("amortir_niveau_risque("),
                        source_risk.index("compute_next_reevaluation("),
                        "le risque est amorti APRÈS avoir servi à la cadence de réévaluation")

        source_coord = (PACKAGE_DIR / "coordinator.py").read_text(encoding="utf-8")
        sauvegarde = source_coord.split("def _serialized_runtime_state")[1].split("\n    def ")[0]
        restauration = source_coord.split("def _restore_runtime_state")[1].split("\n    def ")[0]
        self.assertIn("risque_amortissement", sauvegarde, "la mémoire n'est pas SAUVEGARDÉE")
        self.assertIn("risque_amortissement", restauration, "la mémoire n'est pas RESTAURÉE")

    def test_le_compteur_repart_si_le_candidat_change(self) -> None:
        """Deux candidats qui ALTERNENT ne doivent pas s'additionner pour franchir le seuil.

        Depuis `eleve`, les deux candidats possibles sont `modere` et `faible` : ni l'un ni
        l'autre n'est une alerte, donc aucun ne passe en force. S'ils alternent, aucun ne tient
        trois cycles — et le niveau publié ne doit pas bouger. Sans remise à zéro du compteur,
        leurs cycles s'additionneraient et un niveau qui n'a jamais tenu finirait par passer.
        """
        publies, _ = self._suite(["eleve", "modere", "faible", "modere", "faible", "modere"])
        self.assertEqual(publies, ["eleve"] * 6,
                         "des candidats alternés ont additionné leurs cycles")

    def test_le_niveau_amorti_est_REELLEMENT_reinjecte_dans_la_decision(self) -> None:
        """⚠️ CALCULER N'EST PAS APPLIQUER — le banc l'a trouvé, pas les tests.

        Supprimer la réinjection (`action_guidance["risque_gazon"] = _risque_amorti`) laissait
        l'amortissement se calculer dans le vide : la décision continuait sur le niveau brut, et
        aucun test ne bronchait. Ce test compare le niveau PUBLIÉ à ce que la mémoire impose.
        """
        def _bundle(memoire):
            ctx = decision.DecisionContext.from_legacy_args(
                history=[], today=date(2026, 7, 15), hour_of_day=14,
                # Conditions DOUCES à dessein : il faut un niveau brut qui ne soit pas
                # `eleve`, sinon l'alerte passe en force et le test ne mordrait plus.
                temperature=19.0, pluie_24h=4.0, pluie_demain=2.0, humidite=75,
                type_sol="limoneux", etp_capteur=1.5,
                risk_context={"amortissement": memoire},
            )
            phase = decision.build_phase_bundle(ctx)
            water = decision.build_water_bundle(ctx, phase)
            return decision.build_risk_bundle(ctx, phase, water)

        # Sans mémoire : le niveau publié EST le brut (premier cycle, aucune inertie inventée).
        libre = _bundle(None)
        self.assertEqual(libre["risque_gazon"], libre["risque_gazon_brut"])

        # Avec une mémoire qui tient un autre niveau : c'est ELLE qui doit primer.
        autre = "faible" if libre["risque_gazon_brut"] != "faible" else "modere"
        tenu = _bundle({"publie": autre, "candidat": None, "compte": 0})
        self.assertEqual(
            tenu["risque_gazon_brut"], libre["risque_gazon_brut"],
            "prémisse : le niveau brut doit être le même dans les deux cas",
        )
        self.assertNotEqual(libre["risque_gazon_brut"], "eleve",
                            "prémisse : le montage doit produire un niveau NON-alerte")
        self.assertEqual(
            tenu["risque_gazon"], autre,
            "le niveau amorti n'est pas réinjecté : la décision travaille sur le brut",
        )

    # ── BANDE MORTE SUR LES PALIERS D'ET0 ────────────────────────────────────────────────
    def test_la_bande_morte_retient_le_palier_a_la_DESCENTE(self) -> None:
        """⚠️ LE VRAI DÉFAUT DERRIÈRE LES QUATORZE BASCULES DU 31/08/2026.

        Les dix bascules `faible ↔ modere` relevées l'après-midi coïncident À LA SECONDE près
        avec une mise à jour d'ET0, et toujours dans le bon sens. L'ET0 a passé l'après-midi
        entre 3,6 et 4,4 mm en franchissant NEUF FOIS le palier 4,0 ; le reste du score valait
        exactement 2, donc ce pas faisait basculer le seuil « vigilance ».

        On monte au seuil nominal, on ne redescend qu'une bande (0,4 mm) plus bas.
        """
        g = guidance_mod
        # Montée : au seuil nominal, immédiatement — un assèchement réel n'attend pas.
        self.assertEqual(g.palier_et0_stress(4.0, 1), 2, "la montée au palier a été retardée")
        self.assertEqual(g.palier_et0_stress(3.9, 1), 1, "un palier a été gagné sous son seuil")

        # Descente : retenue tant qu'on n'est pas franchement sorti.
        for valeur in (3.9, 3.8, 3.7, 3.6):
            with self.subTest(et0=valeur):
                self.assertEqual(
                    g.palier_et0_stress(valeur, 2), 2,
                    f"ET0 {valeur} fait retomber le palier alors que la bande vaut 0,4",
                )
        self.assertEqual(g.palier_et0_stress(3.5, 2), 1,
                         "sorti de la bande, le palier doit enfin retomber")

    def test_la_bande_morte_ne_fige_pas_le_score_sans_mesure(self) -> None:
        """⚠️ Une absence de mesure n'est pas un zéro, et ne doit pas non plus RETENIR.

        Sans ce garde, une station muette figerait le score de stress sur sa dernière valeur
        connue indéfiniment — le défaut que ce projet documente sous « repli silencieux ».
        """
        self.assertEqual(guidance_mod.palier_et0_stress(None, 2), 0)
        self.assertEqual(guidance_mod.palier_et0_stress("4.2", 2), 0)
        self.assertEqual(guidance_mod.palier_et0_stress(True, 2), 0,
                         "un booléen est compté comme une mesure")

    def test_sans_memoire_la_bande_morte_ne_change_RIEN(self) -> None:
        """Premier cycle, ou mémoire abîmée : on prend ce qu'on voit, sans inventer d'inertie."""
        for valeur, attendu in ((5.4, 3), (4.1, 2), (3.2, 1), (2.4, 0)):
            with self.subTest(et0=valeur):
                self.assertEqual(guidance_mod.palier_et0_stress(valeur, None), attendu)
                self.assertEqual(guidance_mod.palier_et0_stress(valeur, "deux"), attendu)

    def test_la_serie_REELLE_du_31_08_cesse_de_clignoter(self) -> None:
        """Le banc part de la série mesurée sur l'installation, pas d'un cas inventé.

        103 relevés d'ET0 du 31/08/2026 00:00 au 01/09 02:24. Sans bande morte, le palier change
        17 fois ; c'est ce qui faisait clignoter `risque_gazon`. La bande de 0,4 mm est le GENOU
        de la courbe : elle en supprime 70 %, et l'élargir à 0,5 ou 0,6 n'en supprime pas un de
        plus — elle colle donc à l'amplitude du bruit sans retarder davantage un vrai virage.
        """
        serie = [
            3.2, 3.9, 4.0, 4.1, 4.0, 4.1, 3.9, 4.0, 3.9, 3.4, 3.3, 3.2, 3.7, 3.6, 3.7, 3.8,
            3.2, 3.3, 3.1, 3.2, 3.1, 3.4, 3.5, 3.6, 3.8, 3.9, 3.8, 3.9, 3.7, 3.8, 3.7, 3.8,
            3.7, 3.6, 3.8, 3.7, 3.8, 4.0, 4.2, 4.3, 3.8, 3.7, 3.6, 3.7, 3.8, 3.9, 4.1, 4.2,
            4.3, 4.2, 4.1, 4.4, 4.3, 4.2, 4.3, 4.1, 4.0, 4.1, 4.2, 4.3, 4.4, 4.3, 4.0, 3.9,
            4.0, 3.8, 3.6, 3.7, 3.8, 3.7, 4.1, 4.0, 3.9, 3.7, 4.0, 3.9, 3.8, 3.7, 3.5, 3.6,
            3.5, 3.6, 3.5, 3.4, 3.5, 3.4, 3.3, 3.2, 3.6, 3.8, 3.7, 3.9, 3.6, 3.5, 3.6, 3.1,
            2.9, 3.1, 2.9, 2.8, 2.3, 2.1, 2.0,
        ]

        def parcourir(avec_bande: bool) -> int:
            precedent, changements = None, 0
            for valeur in serie:
                palier = guidance_mod.palier_et0_stress(valeur, precedent if avec_bande else None)
                if precedent is not None and palier != precedent:
                    changements += 1
                precedent = palier
            return changements

        sans = parcourir(False)
        avec = parcourir(True)
        self.assertEqual(sans, 17, "prémisse : la série mesurée doit bien produire 17 changements")
        self.assertLessEqual(avec, 5, f"la bande morte ne calme plus la série réelle ({avec})")
        self.assertGreater(avec, 0, "la bande morte fige le palier : plus aucun virage n'est vu")

    def _bundles_stress(self, memoire, *, etp=2.7):
        """Contexte où le palier d'ET0 fait BASCULER le niveau de stress.

        24 °C, 65 % d'humidité, ET0 2,7 : sans mémoire le palier vaut 0 et le score reste
        « normal » ; avec un palier 1 retenu par la bande morte (2,7 ≥ 3,0 − 0,4) il passe à
        « vigilance ». C'est la forme exacte du cas réel — une journée douce où l'ET0 flotte
        juste sous un seuil.
        """
        ctx = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 8, 31), hour_of_day=15,
            pluie_24h=0.0, pluie_demain=0.0, type_sol="limoneux",
            temperature=24.0, humidite=65, etp_capteur=etp,
            risk_context={"amortissement": None, "palier_et0": memoire},
        )
        phase = decision.build_phase_bundle(ctx)
        water = decision.build_water_bundle(ctx, phase)
        risk = decision.build_risk_bundle(ctx, phase, water)
        return water, risk

    def test_le_palier_CHANGE_le_score_de_stress_et_ne_le_decore_pas(self) -> None:
        """⚠️ CALCULER N'EST PAS APPLIQUER — QUATRIÈME FOIS EN DEUX NUITS.

        Le banc de mutations l'a trouvé, pas mes tests : neutraliser la prise en compte de
        `points_etp` dans `_heat_stress_level` ne faisait tomber AUCUN test. Le palier était
        calculé, publié, persisté — et n'entrait dans aucun score. Mes tests d'alors
        vérifiaient la VALEUR de la clé, jamais son EFFET.
        """
        g = guidance_mod
        # Base à 2 points, choisie pour que le SEUL pas d'ET0 fasse franchir « vigilance » (3) :
        # air sec (35 % ≤ 40) +1, et aucune pluie ni probabilité de pluie +1.
        commun = dict(temperature=24.0, etp=2.7, humidite=35,
                      weather_profile={}, deficit_mm_brut=0.0)
        self.assertEqual(g._heat_stress_level(**commun, points_etp=0), "normal",
                         "prémisse : sans point d'ET0 le score doit rester sous vigilance")
        self.assertEqual(
            g._heat_stress_level(**commun, points_etp=1), "vigilance",
            "le palier fourni n'entre pas dans le score : la bande morte ne sert à rien",
        )

    def test_le_palier_atteint_la_chaine_du_RISQUE(self) -> None:
        libre = self._bundles_stress(None)[1]
        tenu = self._bundles_stress(1)[1]
        self.assertEqual(libre["heat_stress_level"], "normal", "prémisse")
        self.assertEqual(
            tenu["heat_stress_level"], "vigilance",
            "le palier n'atteint pas compute_action_guidance : le risque ignore la bande morte",
        )

    def test_le_palier_atteint_la_chaine_de_l_ARROSAGE(self) -> None:
        libre = self._bundles_stress(None)[0]
        tenu = self._bundles_stress(1)[0]
        self.assertEqual(libre["heat_stress_level"], "normal", "prémisse")
        self.assertEqual(
            tenu["heat_stress_level"], "vigilance",
            "le palier n'atteint pas compute_watering_profile : l'arrosage ignore la bande morte",
        )

    def test_LES_DEUX_CHAINES_disent_le_meme_stress(self) -> None:
        """⚠️ LA FAMILLE DE DÉFAUT N°1 DE CE PROJET : deux sorties pour un même fait.

        `_heat_stress_level` est calculé DEUX fois — pour le profil d'arrosage et pour le
        risque. N'amortir qu'un côté ferait diverger deux valeurs qui décrivent la même
        atmosphère, et rien ne l'aurait signalé.
        """
        for memoire in (None, 0, 1, 2, 3):
            with self.subTest(memoire=memoire):
                water, risk = self._bundles_stress(memoire)
                self.assertEqual(
                    water["heat_stress_level"], risk["heat_stress_level"],
                    f"les deux chaînes divergent avec la mémoire {memoire!r}",
                )

    def _bundle_avec_registre(self, ledger, *, reserve=6.0):
        """Contexte d'aube en phase Normal, avec un registre de sol fourni.

        ⚠️ La projection ne mord QUE si le pilotage par épuisement est actif : phase Normal ET
        réserve issue du registre. Sans registre, on retombe sur le modèle déficit et le test
        serait vert sans rien exercer.
        """
        ctx = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 9, 4), hour_of_day=6,
            temperature=24.0, pluie_24h=0.0, pluie_demain=0.0, humidite=60,
            type_sol="limoneux", etp_capteur=5.2,
            # ⚠️ SANS FRACTION ÉCOULÉE, LA PROJECTION NE S'APPLIQUE PAS : le repli vaut 1,0,
            # donc « rien à venir aujourd'hui » et le biais n'a aucune prise. Le banc l'a
            # montré — le premier jet de ce test était vert sans exercer une seule ligne.
            weather_profile={"et_elapsed_fraction": 0.05},
            soil_balance={
                "date": "2026-09-04",
                "reserve_mm": reserve,
                "previous_reserve_mm": reserve,
                "pluie_mm": 0.0,
                "arrosage_mm": 0.0,
                "etp_mm": 4.2,
                "type_sol": "limoneux",
                "reserve_min_mm": 0.0,
                "reserve_max_mm": 24.0,
                "ledger": ledger,
            },
        )
        phase = decision.build_phase_bundle(ctx)
        return decision.build_water_bundle(ctx, phase)

    def _registre(self, mesuree):
        return [
            {
                "date": f"2026-09-0{i + 1}",
                "etp_mm": 4.2,
                "etp_elapsed_mm": mesuree,
                "etp_last_ts": f"2026-09-0{i + 1}T23:59:30+02:00",
            }
            for i in range(3)
        ]

    def test_le_biais_mesure_atteint_REELLEMENT_le_bilan(self) -> None:
        """⚠️ « DÉCLARER N'EST PAS CÂBLER » — le banc a pris ce projet en défaut cinq fois.

        Le biais est calculé dans `soil_balance`, posé dans le bilan par `decision_watering`,
        et lu par la projection de `_profile_for_normal`. Ce test part du REGISTRE et va
        jusqu'au bilan publié.
        """
        bundle = self._bundle_avec_registre(self._registre(2.9))
        biais = bundle["water_balance"].get("etc_biais_mesure")
        self.assertIsNotNone(biais, "le biais n'atteint pas le bilan : la projection l'ignore")
        self.assertAlmostEqual(biais, 2.9 / 4.2, places=2)

    def test_sans_registre_exploitable_le_biais_reste_None(self) -> None:
        self.assertIsNone(self._bundle_avec_registre([])["water_balance"].get("etc_biais_mesure"))

    def test_le_biais_CHANGE_la_soif_projetee_et_ne_la_decore_pas(self) -> None:
        """⚠️ CALCULER N'EST PAS APPLIQUER — et le banc a pris ce projet en défaut six fois.

        Le point de bascule est mesuré : réserve 9,5 mm sur 12 utiles, soit 2,5 mm de déplétion,
        ET0 5,2 à l'aube. Le modèle seul projette 4,2 mm de soif à venir → ratio 0,56 au-dessus
        du seuil MAD de 0,50 → il déclenche 5 mm. Corrigé par la mesure (0,69), il projette
        2,9 mm → ratio 0,45 → il attend.

        C'est exactement la conséquence arbitrée le 04/09/2026 : l'arrosage part plus tard,
        parce que le sol perd moins d'eau que ce que le modèle journalier annonce.
        """
        juste = self._bundle_avec_registre(self._registre(4.2), reserve=9.5)
        sur_estime = self._bundle_avec_registre(self._registre(2.9), reserve=9.5)

        self.assertAlmostEqual(juste["water_balance"]["etc_biais_mesure"], 1.0, places=2,
                               msg="prémisse : le premier registre doit donner un biais neutre")
        self.assertLess(sur_estime["water_balance"]["etc_biais_mesure"], 0.75, "prémisse")

        self.assertGreater(
            juste["objectif_mm"], 0.0,
            "prémisse : sans correction, ce montage DOIT déclencher un arrosage",
        )
        self.assertEqual(
            sur_estime["objectif_mm"], 0.0,
            "le biais mesuré ne change pas la décision : il ne sert à rien",
        )

    def test_la_date_estimee_seche_au_rythme_MESURE(self) -> None:
        """⚠️ « DEMAIN » TROIS JOURS DE SUITE, sans qu'aucun arrosage ne parte.

        Relevé à 20:00 : 01/09 → 02/09 · 02/09 → 03/09 · 03/09 → 04/09, avec
        `arrosage_recent_7j = 0` sur toute la période. La formule séchait le sol à 4,1 mm/j
        (modèle ET0 × Kc) quand le registre en débitait réellement 2,9.

        ⚠️ Et c'est d'abord une question de COHÉRENCE : depuis la 0.71.0 la projection de
        déclenchement utilise le rythme mesuré. Laisser l'estimation sur le modèle, c'est
        publier deux réponses à la même question.
        """
        lent = self._bundle_avec_registre(self._registre(2.8), reserve=14.0)
        rapide = self._bundle_avec_registre(self._registre(4.2), reserve=14.0)

        self.assertLess(lent["water_balance"]["etc_biais_mesure"], 0.75, "prémisse")
        self.assertAlmostEqual(rapide["water_balance"]["etc_biais_mesure"], 1.0, places=2,
                               msg="prémisse : le second registre doit donner un biais neutre")

        jours_lent = lent["jours_avant_arrosage_estime"]
        jours_rapide = rapide["jours_avant_arrosage_estime"]
        self.assertIsNotNone(jours_lent, "l'estimation n'est plus calculée")
        self.assertGreater(
            jours_lent, jours_rapide,
            "un sol qui sèche plus lentement doit repousser la date, pas l'avancer",
        )

    def test_le_biais_n_est_PAS_applique_deux_fois(self) -> None:
        """⚠️ `guidance._profile_for_normal` multiplie DÉJÀ `etc_mm` par le biais. Le
        pré-multiplier dans le bilan l'appliquerait une seconde fois, et la soif projetée
        tomberait à ~0,46 de sa valeur au lieu de 0,68."""
        bundle = self._bundle_avec_registre(self._registre(2.8), reserve=14.0)
        wb = bundle["water_balance"]
        et0 = float(wb["et0_mm"])
        kc = float(wb["kc_gazon"])
        self.assertAlmostEqual(
            float(wb["etc_mm"]), round(et0 * kc, 1), places=1,
            msg="etc_mm publié est déjà corrigé : le biais sera appliqué deux fois",
        )

    def test_le_palier_amorti_atteint_REELLEMENT_le_snapshot(self) -> None:
        """⚠️ LE PIÈGE DU PROJET, POUR LA TROISIÈME FOIS SUR CETTE FAMILLE DE CLÉS.

        `risque_amortissement` (0.65.0) était produit, rangé, persisté — et n'atteignait
        jamais le snapshot faute d'être dans DEUX listes blanches. L'amortissement n'a rien
        fait pendant quinze minutes tout en ayant l'air branché.

        Ce test part de la sortie RÉELLE et la suit jusqu'au snapshot publié.
        """
        ctx = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 8, 31), hour_of_day=17,
            temperature=24.0, pluie_24h=0.0, pluie_demain=0.0, humidite=65,
            type_sol="limoneux", etp_capteur=4.2,
            risk_context={"amortissement": None, "palier_et0": None},
        )
        snapshot = decision.build_decision_result(ctx).to_snapshot()
        self.assertIn("stress_palier_et0", snapshot,
                      "la clé n'atteint pas le snapshot — recopie ou liste blanche ?")
        self.assertIsInstance(snapshot["stress_palier_et0"], int)

    def test_la_memoire_du_palier_est_REELLEMENT_relue(self) -> None:
        """⚠️ CALCULER N'EST PAS APPLIQUER. La mémoire doit changer la sortie, pas décorer.

        Le même ET0, avec et sans mémoire, doit donner deux paliers différents — sinon
        `risk_context["palier_et0"]` n'est pas lu et la bande morte ne sert à rien.
        """
        def _palier(memoire):
            ctx = decision.DecisionContext.from_legacy_args(
                history=[], today=date(2026, 8, 31), hour_of_day=17,
                temperature=24.0, pluie_24h=0.0, pluie_demain=0.0, humidite=65,
                type_sol="limoneux", etp_capteur=3.7,
                risk_context={"amortissement": None, "palier_et0": memoire},
            )
            phase = decision.build_phase_bundle(ctx)
            water = decision.build_water_bundle(ctx, phase)
            return decision.build_risk_bundle(ctx, phase, water)["stress_palier_et0"]

        libre = _palier(None)
        self.assertEqual(libre, 1, "prémisse : ET0 3,7 vaut un seul point sans mémoire")
        self.assertEqual(
            _palier(2), 2,
            "la mémoire du palier n'est pas relue : la bande morte ne fait rien",
        )

    def test_les_motifs_suivent_le_niveau_PUBLIE_et_non_le_brut(self) -> None:
        """⚠️ CONTRADICTION RECRÉÉE PAR L'AMORTISSEMENT — relevée par la revue de la PR #47.

        `amortir_niveau_risque` ne remplaçait que `risque_gazon`. Les motifs, eux, venaient
        d'être calculés pour le niveau BRUT : pendant les deux cycles de retenue le capteur
        publiait « risque faible » avec pour raison « conditions asséchantes vigilance ».

        C'est exactement l'invariant que `_raisons_par_defaut` protège depuis le 01/08/2026 —
        « une raison doit EXPLIQUER le niveau qu'elle accompagne ». L'amortissement l'a
        contourné par le côté, en changeant le niveau APRÈS coup.
        """
        def _bundle(memoire):
            ctx = decision.DecisionContext.from_legacy_args(
                history=[], today=date(2026, 7, 15), hour_of_day=14,
                temperature=19.0, pluie_24h=4.0, pluie_demain=2.0, humidite=75,
                type_sol="limoneux", etp_capteur=1.5,
                risk_context={"amortissement": memoire},
            )
            phase = decision.build_phase_bundle(ctx)
            water = decision.build_water_bundle(ctx, phase)
            return decision.build_risk_bundle(ctx, phase, water)

        libre = _bundle(None)
        brut = libre["risque_gazon_brut"]
        self.assertNotEqual(brut, "eleve", "prémisse : le montage doit produire un niveau NON-alerte")

        autre = "faible" if brut != "faible" else "modere"
        tenu = _bundle({"publie": autre, "candidat": brut, "compte": 1})
        self.assertEqual(tenu["risque_gazon"], autre, "prémisse : la retenue doit s'appliquer")

        raisons = " · ".join(tenu["risque_gazon_raisons"])
        self.assertIn(autre, raisons,
                      "les motifs n'expliquent pas le niveau PUBLIÉ : contradiction à l'écran")
        self.assertIn(brut, raisons,
                      "le niveau observé n'est pas dit : la retenue est muette")
        # ⚠️ Et les motifs du brut ne doivent pas SURVIVRE tels quels : c'est précisément eux
        # qui contredisaient le niveau publié. Ils restent lisibles via `risque_gazon_brut`.
        for motif in libre["risque_gazon_raisons"]:
            self.assertNotIn(
                motif, tenu["risque_gazon_raisons"],
                f"le motif du niveau brut « {motif} » est publié à côté du niveau {autre}",
            )

    def test_sans_retenue_les_motifs_ne_sont_PAS_touches(self) -> None:
        """L'autre sens : hors retenue, l'explication réelle du niveau doit rester intacte."""
        ctx = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 7, 15), hour_of_day=14,
            temperature=19.0, pluie_24h=4.0, pluie_demain=2.0, humidite=75,
            type_sol="limoneux", etp_capteur=1.5, risk_context={"amortissement": None},
        )
        phase = decision.build_phase_bundle(ctx)
        water = decision.build_water_bundle(ctx, phase)
        bundle = decision.build_risk_bundle(ctx, phase, water)
        self.assertEqual(bundle["risque_gazon"], bundle["risque_gazon_brut"], "prémisse")
        self.assertTrue(bundle["risque_gazon_raisons"], "les motifs réels ont disparu")
        self.assertNotIn(
            "maintenu", " ".join(bundle["risque_gazon_raisons"]),
            "un motif de retenue est publié alors que rien n'est retenu",
        )

    def test_la_memoire_atteint_REELLEMENT_le_snapshot_publie(self) -> None:
        """⚠️ LE DÉFAUT QUE CE TEST AURAIT ÉVITÉ, constaté en production le 01/09/2026.

        `risque_amortissement` était bien produit par le bundle et bien rangé par le
        coordinateur — mais il n'était NI recopié dans `decision.py` (recopie clé par clé) NI
        déclaré dans `_COORDINATOR_SNAPSHOT_KEYS`. Il n'atteignait donc jamais le snapshot :
        `snapshot.get(...)` rendait `None`, la mémoire restait vide, et **l'amortissement ne
        faisait plus rien** tout en ayant l'air parfaitement branché. Persisté sur le disque :
        `null`.

        Mes tests d'alors vérifiaient le TEXTE du code — l'appel présent, la persistance
        écrite. Ce test-ci part de la sortie réelle et la suit jusqu'au snapshot publié.
        """
        ctx = decision.DecisionContext.from_legacy_args(
            history=[], today=date(2026, 7, 15), hour_of_day=14,
            temperature=19.0, pluie_24h=4.0, pluie_demain=2.0, humidite=75,
            type_sol="limoneux", etp_capteur=1.5,
            risk_context={"amortissement": {"publie": "modere", "candidat": None, "compte": 0}},
        )
        snapshot = decision.build_decision_result(ctx).to_snapshot()
        for cle in ("risque_gazon_brut", "risque_amortissement"):
            with self.subTest(cle=cle):
                self.assertIn(cle, snapshot,
                              f"{cle} n'atteint pas le snapshot — recopie ou liste blanche ?")
        self.assertIsInstance(snapshot["risque_amortissement"], dict,
                              "la mémoire arrive vide : le coordinateur ne pourra rien ranger")
        self.assertEqual(snapshot["risque_amortissement"].get("publie"), "modere",
                         "la mémoire publiée ne reflète pas le niveau réellement tenu")

        # ⚠️ DEUX LISTES BLANCHES, PAS UNE. Le snapshot de décision ci-dessus est filtré une
        # SECONDE fois par le coordinateur. Le banc l'a montré : retirer la clé de cette
        # liste-là ne faisait tomber aucun test — « quatre listes blanches, pas deux ».
        coordinateur = importlib.import_module("custom_components.gazon_intelligent.coordinator")
        for cle in ("risque_gazon_brut", "risque_amortissement"):
            with self.subTest(liste="coordinator", cle=cle):
                self.assertIn(cle, coordinateur._COORDINATOR_SNAPSHOT_KEYS,
                              f"{cle} est filtrée par la liste blanche du coordinateur")

    def test_le_libelle_du_stress_ne_parle_plus_du_SOL(self) -> None:
        """⚠️ Le score mesure la demande de l'ATMOSPHÈRE, pas l'état du sol.

        Relevé le 01/09/2026 : « risque modéré — stress hydrique vigilance » affiché pendant
        que le bilan sol annonçait la réserve PLEINE (12/12) et la déplétion nulle. Deux
        affirmations inconciliables sur le même écran.

        Ce test ne fige pas une formulation — il interdit celle qui ment. Le mot « hydrique »
        renvoie à l'eau du sol ; le score, lui, additionne température, air sec, vent, absence
        de pluie et déficit.
        """
        libelle = guidance_mod._LIBELLE_STRESS.lower()
        self.assertNotIn("hydrique", libelle,
                         "le libellé parle encore de l'eau du SOL alors qu'il mesure l'air")
        self.assertGreater(len(libelle), 3, "un libellé vide n'explique rien")
        # Et il doit réellement atteindre les raisons publiées.
        raisons = " ".join(guidance_mod._raisons_par_defaut(
            risque_gazon="modere", heat_stress_level="vigilance"
        ))
        self.assertIn(libelle, raisons.lower())
        self.assertNotIn("hydrique", raisons.lower())
