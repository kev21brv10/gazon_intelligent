"""Chaque réglage de la page « Gazon » change la DÉCISION, pas seulement ce que la page affiche.

Le registre (`test_reglages.py`) prouve que les valeurs conseillées sont celles du moteur. Ce
fichier-ci prouve le branchement : pour chaque réglage, un scénario où la valeur réglée change ce
que l'intégration décide et publie. Tout passe par le chemin de production —
`DecisionContext.reglages` puis `decision.build_decision_result` — et jamais par la fonction qui
lit la valeur : un appelant qui oublierait de la transmettre ferait échouer ces tests.

Les trois réglages lus par le coordinateur (marge avant le lever, délai de relance, créneaux des
graines) sont vérifiés dans `test_watering_session_monitoring.py`, avec ses faux coordinateurs.
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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
    """Le MÊME stub que `test_watering_session_monitoring.py` (heure réelle, en UTC).

    Ce stub sert aussi aux modules de test lancés après celui-ci : une horloge figée y faisait
    tourner à vide les attentes du veilleur de vanne (4 min 30 au lieu d'une seconde), et une
    heure locale y déplaçait « hier 23:30 UTC » à aujourd'hui. Les scénarios d'ici fixent
    l'heure qu'ils lisent avec `_horloge` et par le contexte ; ils ne dépendent pas de celle-ci.
    """
    homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    if not hasattr(homeassistant, "__path__"):
        homeassistant.__path__ = []  # type: ignore[attr-defined]
    util = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
    if not hasattr(util, "__path__"):
        util.__path__ = []  # type: ignore[attr-defined]
    dt_module = sys.modules.setdefault("homeassistant.util.dt", types.ModuleType("homeassistant.util.dt"))
    if not hasattr(dt_module, "now"):
        dt_module.now = lambda: datetime.now(timezone.utc)  # type: ignore[attr-defined]
    if not hasattr(dt_module, "utcnow"):
        dt_module.utcnow = lambda: datetime.now(timezone.utc)  # type: ignore[attr-defined]
    if not hasattr(util, "dt"):
        util.dt = dt_module  # type: ignore[attr-defined]


PARIS = ZoneInfo("Europe/Paris")
_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_dt_stub()


def _module(nom: str):
    return importlib.import_module(f"custom_components.gazon_intelligent.{nom}")


decision = _module("decision")
decision_models = _module("decision_models")
decision_watering = _module("decision_watering")
reglages = _module("reglages")
watering_policy = _module("watering_policy")
guidance = _module("guidance")
GazonBrain = _module("gazon_brain").GazonBrain

JOUR = date(2026, 4, 4)
SEMIS = date(2026, 4, 1)
# Mois d'avril changé : fréquence 2,5 → 1 par semaine, hauteur 4,0 → 6,0 cm.
FREQUENCES_AVRIL_1 = [0.0, 0.0, 2.5, 1.0, 5.0, 5.0, 3.0, 3.0, 5.0, 5.0, 1.5, 0.0]
HAUTEURS_AVRIL_6 = [4.0, 4.0, 4.5, 6.0, 4.0, 4.5, 5.0, 5.0, 4.0, 4.0, 4.0, 4.0]


class _DtFige:
    """`dt_util` dont seul `now()` est fixé ; le reste vient du stub installé."""

    def __init__(self, reel, moment: datetime) -> None:
        self._reel = reel
        self._moment = moment

    def now(self, *_args, **_kwargs) -> datetime:
        return self._moment

    def __getattr__(self, nom: str):
        return getattr(self._reel, nom)


@contextmanager
def _horloge(moment: datetime):
    """Fixe l'heure que lisent `guidance` et `decision_phase` (progression d'une étape).

    Piège du réimport : on patche les globales des modules que la décision appelle VRAIMENT,
    pas un module importé à côté. Sans la seconde, le stub d'un autre fichier de test (figé au
    04/04) donnait 0 % de progression à un semis daté de mai, et la transition ne partait pas.
    """
    guidance_globales = decision_watering.compute_watering_profile.__globals__
    phase_globales = decision._build_runtime_bundles.__globals__["build_phase_bundle"].__globals__
    with patch.dict(guidance_globales, {"_current_datetime": lambda: moment}), patch.dict(
        phase_globales, {"dt_util": _DtFige(phase_globales["dt_util"], moment)}
    ):
        yield


def _snapshot(reglages_instance: dict | None = None, *, maintenant: datetime | None = None, **params) -> dict:
    base = dict(
        history=[], today=JOUR, hour_of_day=11.0, temperature=18.0, pluie_24h=0.0, pluie_demain=0.0,
        humidite=60.0, type_sol="limoneux", etp_capteur=2.0, vent=5.0,
        sun_context={"sun_state": "above_horizon"}, weather_profile={"sunset_minute": 20 * 60 + 30},
        hauteur_min_tondeuse_cm=3.0, hauteur_max_tondeuse_cm=8.0,
    )
    base.update(params)
    if maintenant is None:
        heure = float(base["hour_of_day"])
        maintenant = datetime.combine(base["today"], datetime.min.time(), tzinfo=PARIS) + timedelta(hours=heure)
    contexte = decision_models.DecisionContext.from_legacy_args(reglages=reglages_instance, **base)
    with _horloge(maintenant):
        return decision.build_decision_result(contexte).to_snapshot()


class _Comparaison(unittest.TestCase):
    """Un réglage, deux décisions : le conseil, puis la valeur réglée."""

    def compare(self, reglage: dict, cles: tuple[str, ...], attendu_defaut: dict, attendu_regle: dict, **params):
        defaut = _snapshot(None, **params)
        regle = _snapshot(reglage, **params)
        self.assertEqual({k: defaut.get(k) for k in attendu_defaut}, attendu_defaut, "sans réglage")
        self.assertEqual({k: regle.get(k) for k in attendu_regle}, attendu_regle, f"avec {reglage}")
        return defaut, regle


class LaTonteSuitSesReglagesTests(_Comparaison):
    def test_debut_de_la_fenetre_ideale(self) -> None:
        self.compare({"tonte_fenetre_ideale_debut": 9 * 60}, (),
                     {"mowing_window_state": "blocked"}, {"mowing_window_state": "ideal"}, hour_of_day=9.5)

    def test_fin_de_la_fenetre_ideale(self) -> None:
        self.compare({"tonte_fenetre_ideale_fin": 15 * 60}, (),
                     {"mowing_window_state": "discouraged"}, {"mowing_window_state": "ideal"}, hour_of_day=14.5)

    def test_le_soir_commence_plus_tot_avant_le_coucher(self) -> None:
        self.compare({"tonte_soir_avant_coucher": 360}, (),
                     {"mowing_window_state": "discouraged"}, {"mowing_window_state": "acceptable"}, hour_of_day=15.0)

    def test_le_soir_finit_plus_tard_apres_le_coucher(self) -> None:
        # Soleil couché depuis 45 min : la nuit tombe au bout du délai réglé, pas avant.
        self.compare({"tonte_soir_apres_coucher": 60}, (),
                     {"mowing_window_state": "blocked", "raison_blocage_code": "mowing_night"},
                     {"mowing_window_state": "acceptable"},
                     hour_of_day=21.25, sun_context={"sun_state": "below_horizon"})

    def test_vent_a_eviter(self) -> None:
        self.compare({"tonte_vent_a_eviter": 12}, (),
                     {"mowing_window_state": "ideal"}, {"mowing_window_state": "discouraged"}, vent=15.0)

    def test_vent_interdit(self) -> None:
        self.compare({"tonte_vent_bloque": 30}, (),
                     {"mowing_window_state": "discouraged", "raison_blocage_code": None},
                     {"mowing_window_state": "blocked", "raison_blocage_code": "vent_fort", "tonte_autorisee": False},
                     vent=35.0)

    def test_chaleur_a_eviter(self) -> None:
        self.compare({"tonte_temperature_a_eviter": 22}, (),
                     {"mowing_window_state": "ideal"}, {"mowing_window_state": "discouraged"}, temperature=23.0)

    def test_la_fenetre_suit_aussi_la_chaleur_interdite(self) -> None:
        # 31 °C : interdit au-delà de 30, seulement « à éviter » jusqu'à 32 réglés. La FENÊTRE
        # aussi le dit, pas seulement le blocage (qui, lui, écraserait l'état de la fenêtre).
        self.compare({"tonte_temperature_bloquee": 32}, (),
                     {"mowing_window_state": "blocked", "raison_blocage_code": "temp_extreme"},
                     {"mowing_window_state": "discouraged", "raison_blocage_code": None},
                     temperature=31.0)

    def test_chaleur_interdite_et_son_seuil_dans_le_motif(self) -> None:
        _, regle = self.compare({"tonte_temperature_bloquee": 28}, (),
                                {"raison_blocage_code": None},
                                {"raison_blocage_code": "temp_extreme", "tonte_autorisee": False},
                                temperature=28.5)
        self.assertIn("seuil 28 °C", regle["mowing_block_reason_label"])

    def test_humidite_qui_interdit(self) -> None:
        hier = [{"type": "arrosage", "date": (JOUR - timedelta(days=1)).isoformat(), "mm": 5.0, "source": "auto_irrigation"}]
        self.compare({"tonte_humidite_bloquee": 84}, (),
                     {"mowing_block_reason_code": None}, {"mowing_block_reason_code": "soil_wet"},
                     humidite=85.0, history=hier)

    def test_ecart_entre_deux_tontes(self) -> None:
        avant_hier = [{"type": "tonte", "date": (JOUR - timedelta(days=2)).isoformat()}]
        self.compare({"tonte_ecart_min_jours": 3}, (),
                     {"raison_blocage_code": None, "tonte_autorisee": True},
                     {"raison_blocage_code": "mowing_spacing", "tonte_autorisee": False},
                     history=avant_hier)

    def test_tontes_par_jour(self) -> None:
        self.compare({"tonte_max_par_jour": 3}, (),
                     {"mowing_daily_session_limit": 2}, {"mowing_daily_session_limit": 3})

    def test_hauteur_du_mois_et_son_motif(self) -> None:
        defaut, regle = self.compare({"tonte_hauteur_par_mois": HAUTEURS_AVRIL_6}, (), {}, {})
        self.assertEqual(float(regle["hauteur_tonte_recommandee_cm"]) - float(defaut["hauteur_tonte_recommandee_cm"]), 2.0)
        self.assertIn("base 6,0 cm", regle["hauteur_tonte_motif"])

    def test_rythme_du_mois_son_libelle_et_le_retard(self) -> None:
        il_y_a_5_jours = [{"type": "tonte", "date": (JOUR - timedelta(days=5)).isoformat()}]
        self.compare({"tonte_frequence_par_mois": FREQUENCES_AVRIL_1}, (),
                     {"mowing_frequency_target_per_week": 2.5, "mowing_frequency_label": "2 à 3 / semaine",
                      "mowing_is_overdue": True},
                     {"mowing_frequency_target_per_week": 1.0, "mowing_frequency_label": "1 / semaine",
                      "mowing_is_overdue": False},
                     history=il_y_a_5_jours)

    def test_un_mois_non_touche_garde_son_libelle(self) -> None:
        # Le réglage change avril seulement : en mai, le moteur garde « 4 à 6 / semaine ».
        snapshot = _snapshot({"tonte_frequence_par_mois": FREQUENCES_AVRIL_1}, today=date(2026, 5, 4))
        self.assertEqual(snapshot["mowing_frequency_label"], "4 à 6 / semaine")

    def test_libelle_d_une_demi_valeur(self) -> None:
        frequences = list(FREQUENCES_AVRIL_1)
        frequences[3] = 3.5
        self.assertEqual(_snapshot({"tonte_frequence_par_mois": frequences})["mowing_frequency_label"], "3 à 4 / semaine")


class LArrosageSuitSesReglagesTests(_Comparaison):
    def test_fenetre_du_matin(self) -> None:
        self.compare({"arrosage_ouverture": 240, "arrosage_fin_optimale": 450, "arrosage_fin_acceptable": 570}, (),
                     {"watering_window_start_minute": 225, "watering_window_optimal_end_minute": 480,
                      "watering_window_acceptable_end_minute": 600},
                     {"watering_window_start_minute": 240, "watering_window_optimal_end_minute": 450,
                      "watering_window_acceptable_end_minute": 570})

    def test_le_profil_d_arrosage_suit_aussi_l_ouverture(self) -> None:
        # 03:50 : dans la fenêtre à 03:45, pas encore à 04:00. Le PROFIL (qui pèse sur « soir »
        # et sur la fenêtre retenue) calcule sa propre fenêtre : il doit lire le même réglage.
        self.compare({"arrosage_ouverture": 240}, (),
                     {"fenetre_optimale_profil": "maintenant", "fenetre_optimale": "maintenant"},
                     {"fenetre_optimale_profil": "ce_matin", "fenetre_optimale": "ce_matin"},
                     hour_of_day=3 + 50 / 60)

    def test_chaque_borne_du_matin_seule(self) -> None:
        for cle, sortie, valeur in (
            ("arrosage_ouverture", "watering_window_start_minute", 300),
            ("arrosage_fin_optimale", "watering_window_optimal_end_minute", 420),
            ("arrosage_fin_acceptable", "watering_window_acceptable_end_minute", 660),
        ):
            with self.subTest(cle=cle):
                self.assertEqual(_snapshot({cle: valeur})[sortie], valeur)

    def test_seuil_de_decoupage(self) -> None:
        # 14 mm conseillés : deux passages au-delà de 10 mm, un seul si le seuil passe à 14,5.
        self.compare({"arrosage_decoupage_seuil": 14.5}, (),
                     {"mm_final": 14.0, "watering_passages": 2, "watering_pause_minutes": 25},
                     {"mm_final": 14.0, "watering_passages": 1, "watering_pause_minutes": 0})

    def test_dose_qui_declenche_la_pause(self) -> None:
        self.compare({"arrosage_pause_dose_min": 15.0}, (),
                     {"watering_passages": 2, "watering_pause_minutes": 25},
                     {"watering_passages": 2, "watering_pause_minutes": 0})

    def test_duree_de_la_pause(self) -> None:
        self.compare({"arrosage_pause_duree": 40}, (),
                     {"watering_pause_minutes": 25}, {"watering_pause_minutes": 40})

    def test_sensibilite_pluie_econome_reporte_plus_tot(self) -> None:
        # 5 mm annoncés demain valent 3,5 mm après la confiance J+1 : sous le seuil conseillé
        # (4 mm), le moteur réduit seulement la dose. Économe (×0,75) abaisse le seuil à 3 mm :
        # la même prévision suffit alors à reporter. La pluie déjà mesurée ne dépend d'aucun profil.
        self.compare({"arrosage_sensibilite_pluie": 0.75}, (),
                     {"block_reason": None, "arrosage_recommande": True, "mm_final": 11.4},
                     {"block_reason": "pluie_prevue_suffisante", "arrosage_recommande": False, "mm_final": 0.0},
                     pluie_demain=5.0, etp_capteur=5.0)

    def test_sensibilite_pluie_prudente_exige_plus_de_pluie(self) -> None:
        # 6 mm annoncés demain suffisent au profil Équilibré. Prudente (×1,25) relève le seuil :
        # cette prévision ne bloque plus et le moteur garde un apport réduit pour protéger le gazon.
        equilibree = _snapshot({}, pluie_demain=6.0, etp_capteur=5.0)
        self.assertEqual(equilibree.get("block_reason"), "pluie_prevue_suffisante")
        snapshot = _snapshot({"arrosage_sensibilite_pluie": 1.25}, pluie_demain=6.0, etp_capteur=5.0)
        self.assertIsNone(snapshot.get("block_reason"))
        self.assertTrue(snapshot["arrosage_recommande"])
        self.assertEqual(snapshot["mm_final"], 11.0)

    def _soir_de_canicule(self) -> dict:
        return dict(
            today=date(2026, 7, 10), hour_of_day=21.25, temperature=31.0, humidite=35.0, etp_capteur=6.5,
            weather_profile={"sunset_minute": 21 * 60 + 40},
            maintenant=datetime(2026, 7, 10, 21, 15, tzinfo=PARIS),
        )

    def test_temperature_du_rafraichissement(self) -> None:
        # 31 °C réels, dans la fenêtre du soir : sous le seuil de 32 °C, pas de rafraîchissement.
        self.compare({"rafraichissement_temperature": 30}, (),
                     {"watering_cause": "hydrique"},
                     {"watering_cause": "rafraichissement_soir", "fenetre_optimale": "soir", "mm_final": 3.0},
                     **self._soir_de_canicule())

    def test_dose_du_rafraichissement(self) -> None:
        snapshot = _snapshot({"rafraichissement_temperature": 30, "rafraichissement_dose": 4.5}, **self._soir_de_canicule())
        self.assertEqual(snapshot["watering_cause"], "rafraichissement_soir")
        self.assertEqual(snapshot["mm_final"], 4.5)
        # Une dose de rafraîchissement ne se découpe jamais, et n'attend pas.
        self.assertEqual((snapshot["watering_passages"], snapshot["watering_pause_minutes"]), (1, 0))


class LesPhasesSuiventLeursDureesTests(_Comparaison):
    def test_duree_de_chaque_mode(self) -> None:
        for mode, cle, duree in (
            ("Traitement", "mode_traitement_duree", 2),
            ("Fertilisation", "mode_fertilisation_duree", 2),
            ("Biostimulant", "mode_biostimulant_duree", 1),
            ("Agent Mouillant", "mode_agent_mouillant_duree", 1),
            ("Scarification", "mode_scarification_duree", 7),
        ):
            with self.subTest(mode=mode):
                # Le lendemain du dernier jour : fini sans réglage, encore là avec deux jours de plus.
                self.compare({cle: duree + 2}, (),
                             {"phase_dominante": "Normal"},
                             {"phase_dominante": mode, "jours_restants": 1},
                             history=[{"type": mode, "date": SEMIS.isoformat()}],
                             today=SEMIS + timedelta(days=duree))

    def test_une_duree_allongee_rend_la_sous_phase_suivante_atteignable(self) -> None:
        _, regle = self.compare({"mode_traitement_duree": 3}, (), {"phase_dominante": "Normal"},
                                {"phase_dominante": "Traitement", "sous_phase": "Rémanence"},
                                history=[{"type": "Traitement", "date": SEMIS.isoformat()}],
                                today=SEMIS + timedelta(days=2))

    def test_temperature_minimale_apres_scarification(self) -> None:
        self.compare(
            {"mode_scarification_temperature_min": 15.0},
            (),
            {"block_reason": None},
            {"block_reason": "temperature_trop_basse"},
            history=[{"type": "Scarification", "date": JOUR.isoformat()}],
            temperature=13.0,
            humidite=50.0,
            etp_capteur=8.0,
        )

    def test_duree_du_suivi_des_graines(self) -> None:
        self.compare({"graines_duree": 50}, (),
                     {"phase_dominante": "Normal"}, {"phase_dominante": "Sursemis", "sous_phase": "Stabilisation"},
                     history=[{"type": "Sursemis", "date": SEMIS.isoformat()}], today=SEMIS + timedelta(days=45))

    def test_fin_de_chaque_etape_des_graines(self) -> None:
        for cle, age, avant, apres in (
            ("graines_fin_germination", 11, "Enracinement", "Germination"),
            ("graines_fin_enracinement", 25, "Reprise", "Enracinement"),
            ("graines_fin_reprise", 35, "Stabilisation", "Reprise"),
        ):
            with self.subTest(cle=cle):
                self.compare({cle: age}, (), {"sous_phase": avant}, {"sous_phase": apres},
                             history=[{"type": "Sursemis", "date": SEMIS.isoformat()}],
                             today=SEMIS + timedelta(days=age))

    def test_la_projection_du_semis_suit_la_fin_de_l_enracinement(self) -> None:
        # Semis sur sol nu, tonte interdite jusqu'à la reprise : le lendemain de la fin réglée.
        self.compare({"graines_fin_enracinement": 28}, (),
                     {"next_mowing_date": (SEMIS + timedelta(days=25)).isoformat()},
                     {"next_mowing_date": (SEMIS + timedelta(days=29)).isoformat()},
                     history=[{"type": "Semis", "date": SEMIS.isoformat()}], today=SEMIS + timedelta(days=5))


class LesGrainesSuiventLeursReglagesTests(_Comparaison):
    def _sursemis(self, age: int, **params) -> dict:
        base = dict(history=[{"type": "Sursemis", "date": SEMIS.isoformat()}], today=SEMIS + timedelta(days=age))
        base.update(params)
        return base

    def test_dose_et_nombre_d_arrosages_de_chaque_etape(self) -> None:
        for age, cle_dose, dose, cle_cycles, cycles, defauts in (
            (3, "graines_germination_dose", 2.5, "graines_germination_cycles", 1, (1.5, 3)),
            (15, "graines_enracinement_dose", 4.0, "graines_enracinement_cycles", 2, (3.0, 1)),
            (30, "graines_reprise_dose", 3.5, "graines_reprise_cycles", 2, (2.5, 1)),
        ):
            with self.subTest(age=age):
                self.compare({cle_dose: dose}, (),
                             {"surface_cycle_mm": defauts[0], "daily_cycles_target": defauts[1]},
                             {"surface_cycle_mm": dose, "daily_cycles_target": defauts[1]}, **self._sursemis(age))
                self.compare({cle_cycles: cycles}, (),
                             {"daily_cycles_target": defauts[1]},
                             {"surface_cycle_mm": defauts[0], "daily_cycles_target": cycles}, **self._sursemis(age))

    def test_vent_maximal(self) -> None:
        self.compare({"graines_vent_max": 12}, (),
                     {"fenetre_optimale": "maintenant"}, {"fenetre_optimale": "demain_matin"},
                     **self._sursemis(3, vent=13.0))

    def test_temperature_minimale(self) -> None:
        # 7 °C en germination : bloqué sous 8 °C, arrosé au-dessus de 6 °C réglés.
        self.compare({"graines_temperature_min": 6}, (),
                     {"seeding_block_reason": "temperature_trop_basse_germination", "mm_final": 0.0},
                     {"seeding_block_reason": None, "mm_final": 1.2},
                     **self._sursemis(3, temperature=7.0))

    def test_horaire_des_graines(self) -> None:
        self.compare({"graines_fenetre_debut": 8 * 60, "graines_fenetre_fin": 18 * 60}, (),
                     {"fenetre_optimale": "ce_matin", "watering_window_start_minute": 600,
                      "watering_window_acceptable_end_minute": 1020},
                     {"fenetre_optimale": "maintenant", "watering_window_start_minute": 480,
                      "watering_window_acceptable_end_minute": 1080},
                     **self._sursemis(3, hour_of_day=9.0))

    def test_l_horaire_publie_quand_rien_n_est_a_arroser(self) -> None:
        # 7 °C : pas d'arrosage (objectif nul), sortie anticipée — la fenêtre publiée suit quand même.
        self.compare({"graines_fenetre_debut": 8 * 60}, (),
                     {"objectif_mm": 0.0, "watering_window_start_minute": 600},
                     {"objectif_mm": 0.0, "watering_window_start_minute": 480},
                     **self._sursemis(3, temperature=7.0))

    def test_la_transition_des_graines_suit_la_premiere_coupe_reglee(self) -> None:
        # Tontes à J+20 et J+26 ; la transition exige deux coupes APRÈS la première coupe des
        # plantules (J+22 par défaut, J+20 avec une levée de 5 jours) : seule la levée réglée
        # compte les deux, et le programme passe à celui de l'enracinement.
        historique = [{"type": "Sursemis", "date": SEMIS.isoformat()}] + [
            {"type": "tonte", "date": (SEMIS + timedelta(days=j)).isoformat()} for j in (20, 26)
        ]
        self.compare({"sursemis_levee": 5}, (),
                     {"seeding_transition_ready": False, "watering_stage": "levee", "surface_cycle_mm": 2.5},
                     {"seeding_transition_ready": True, "watering_stage": "enracinement", "surface_cycle_mm": 3.0},
                     history=historique, today=SEMIS + timedelta(days=33))

    def test_la_transition_vue_par_le_risque(self) -> None:
        # Même scénario, côté `compute_action_guidance` (niveau d'action et fenêtre du risque).
        historique = [{"type": "Sursemis", "date": SEMIS.isoformat()}] + [
            {"type": "tonte", "date": (SEMIS + timedelta(days=j)).isoformat()} for j in (20, 26)
        ]

        def guider(reglages_instance):
            return decision.compute_action_guidance(
                phase_dominante="Sursemis", sous_phase="Reprise",
                water_balance={"bilan_hydrique_mm": 0.5, "deficit_3j": 0.0, "deficit_7j": 0.0},
                advanced_context={"vent": 5.0, "rosee": 0.0, "hauteur_gazon": 6.5},
                pluie_24h=0.0, pluie_demain=0.0, humidite=60.0, temperature=18.0, etp=2.0,
                objectif_mm=2.5, hour_of_day=11, history=historique,
                sous_phase_age_days=33, sous_phase_progression=80.0, reglages=reglages_instance,
            )

        self.assertEqual(guider(None)["niveau_action"], "a_faire")
        self.assertEqual(guider({"sursemis_levee": 5})["niveau_action"], "surveiller")

    def test_le_profil_des_graines_lit_le_vent_et_l_horaire(self) -> None:
        # Le profil ne décide la fenêtre publiée que le soir, jamais pour des graines : on le lit
        # directement, pour que les deux calculs de la fenêtre des graines disent la même chose.
        def profil(reglages_instance):
            with _horloge(datetime(2026, 4, 4, 11, 0, tzinfo=PARIS)):
                return guidance.compute_watering_profile(
                    phase_dominante="Sursemis", sous_phase="Germination",
                    water_balance={"bilan_hydrique_mm": -1.0, "deficit_3j": 1.0, "deficit_7j": 1.0},
                    today=JOUR, temperature=18.0, humidite=60.0, etp=2.0,
                    weather_profile={"weather_wind_speed": 13.0},
                    history=[{"type": "Sursemis", "date": SEMIS.isoformat()}],
                    sous_phase_age_days=3, sous_phase_progression=30.0, reglages=reglages_instance,
                )["fenetre_optimale"]

        self.assertEqual(profil(None), "maintenant")
        self.assertEqual(profil({"graines_vent_max": 12}), "demain_matin")
        self.assertEqual(profil({"graines_fenetre_debut": 12 * 60}), "ce_matin")

    def test_une_fin_plus_tardive_n_invente_pas_de_plafond_a_17_h(self) -> None:
        # 27 °C et fin réglée à 18 h : l'ancien `min(…, 17 h)` serait devenu un vrai plafond.
        snapshot = _snapshot({"graines_fenetre_fin": 18 * 60}, **self._sursemis(3, temperature=27.0))
        self.assertEqual(snapshot["watering_window_acceptable_end_minute"], 18 * 60)
        # Le plafond de 16 h des jours de pluie, lui, reste en place.
        pluie = _snapshot({"graines_fenetre_fin": 18 * 60}, **self._sursemis(3, pluie_24h=1.0))
        self.assertEqual(pluie["watering_window_acceptable_end_minute"], 16 * 60)

    def test_levee_du_sursemis(self) -> None:
        _, regle = self.compare({"sursemis_levee": 10}, (),
                                {"raison_blocage_code": None, "plantules_levee_date": "2026-04-08"},
                                {"raison_blocage_code": "phase_sursemis", "plantules_levee_date": "2026-04-11",
                                 # La tonte reprend le lendemain de la levée réglée.
                                 "next_mowing_date": (SEMIS + timedelta(days=11)).isoformat()},
                                **self._sursemis(8))
        self.assertIn("jusqu'à J+10", regle["tonte_reason"])

    def test_le_suivi_des_plantules_dure_autant_que_les_graines(self) -> None:
        # J+46 : plus de suivi après 45 jours, encore suivi avec 50 jours réglés.
        self.compare({"graines_duree": 50}, (),
                     {"plantules_hauteur_estimee_cm": None},
                     {"plantules_hauteur_estimee_cm": round((46 - 7) * 0.4, 1)},
                     **self._sursemis(46))

    def test_pousse_des_plantules_et_premiere_coupe(self) -> None:
        self.compare({"sursemis_pousse_plantules": 0.5}, (),
                     {"plantules_hauteur_estimee_cm": 1.2, "plantules_premiere_coupe_date": "2026-04-23"},
                     {"plantules_hauteur_estimee_cm": 1.5, "plantules_premiere_coupe_date": "2026-04-20"},
                     **self._sursemis(10))
        self.compare({"sursemis_premiere_coupe": 2.0}, (),
                     {"plantules_premiere_coupe_date": "2026-04-23"},
                     {"plantules_premiere_coupe_date": "2026-04-28"}, **self._sursemis(10))

    def test_lame_du_sursemis(self) -> None:
        self.compare({"sursemis_lame": 5.0, "sursemis_lame_finale": 5.0}, (),
                     {"hauteur_tonte_recommandee_cm": 4.0}, {"hauteur_tonte_recommandee_cm": 5.0},
                     **self._sursemis(10))

    def _deux_coupes(self) -> dict:
        historique = [{"type": "Sursemis", "date": SEMIS.isoformat()}] + [
            {"type": "tonte", "date": (SEMIS + timedelta(days=j)).isoformat()} for j in (23, 29)
        ]
        return dict(history=historique, today=SEMIS + timedelta(days=31))

    def test_lame_remontee(self) -> None:
        self.compare({"sursemis_lame_finale": 5.5}, (),
                     {"hauteur_tonte_recommandee_cm": 4.5}, {"hauteur_tonte_recommandee_cm": 5.5},
                     **self._deux_coupes())

    def test_coupes_avant_de_remonter(self) -> None:
        _, regle = self.compare({"sursemis_coupes_avant_remontee": 3}, (),
                                {"hauteur_tonte_recommandee_cm": 4.5}, {"hauteur_tonte_recommandee_cm": 4.0},
                                **self._deux_coupes())
        self.assertIn("3ᵉ coupe", regle["hauteur_tonte_motif"])

    def test_ecart_entre_tontes_du_sursemis(self) -> None:
        historique = [{"type": "Sursemis", "date": SEMIS.isoformat()},
                      {"type": "tonte", "date": (SEMIS + timedelta(days=24)).isoformat()}]
        self.compare({"sursemis_ecart_tontes": 7}, (),
                     {"raison_blocage_code": None, "tonte_autorisee": True},
                     {"raison_blocage_code": "mowing_spacing", "tonte_autorisee": False},
                     history=historique, today=SEMIS + timedelta(days=30))

    def test_hauteurs_du_semis(self) -> None:
        for cle, age, defaut, valeur in (
            ("semis_hauteur_germination", 5, 7.5, 8.0),
            ("semis_hauteur_enracinement", 15, 7.0, 8.0),
            ("semis_hauteur_reprise", 30, 6.5, 8.0),
            ("semis_hauteur_stabilisation", 40, 5.5, 6.0),
        ):
            with self.subTest(cle=cle):
                # Stabilisation : 5,0 conseillé, mais la hauteur du mois (5,5 en avril, bonus de phase
                # compris) passe au-dessus ; 6,0 réglés repassent devant.
                self.compare({cle: valeur}, (),
                             {"hauteur_tonte_recommandee_cm": defaut}, {"hauteur_tonte_recommandee_cm": valeur},
                             history=[{"type": "Semis", "date": SEMIS.isoformat()}], today=SEMIS + timedelta(days=age))

    def test_le_plancher_du_semis_suit_les_etapes_reglees(self) -> None:
        # J+26 : reprise par défaut (6,5 cm), encore l'enracinement (7,0 cm) si elle finit à J+28.
        self.compare({"graines_fin_enracinement": 28}, (),
                     {"hauteur_tonte_recommandee_cm": 6.5}, {"hauteur_tonte_recommandee_cm": 7.0},
                     history=[{"type": "Semis", "date": SEMIS.isoformat()}], today=SEMIS + timedelta(days=26))


class LeCerveauTransmetLesReglagesTests(unittest.TestCase):
    """`GazonBrain.reglages` → `DecisionContext.reglages` : le chemin que suit le coordinateur."""

    def _snapshot(self, brain) -> dict:
        with _horloge(datetime(2026, 4, 4, 11, 0, tzinfo=PARIS)):
            return brain.compute_snapshot(
                today=JOUR, hour_of_day=11.0, temperature=18.0, pluie_24h=0.0, pluie_demain=0.0,
                humidite=60.0, type_sol="limoneux", etp_capteur=2.0, humidite_sol=None, vent=5.0,
                rosee=None, hauteur_gazon=None, retour_arrosage=None, pluie_source="capteur_pluie_24h",
                pluie_demain_source="meteo_forecast", weather_profile={"sunset_minute": 20 * 60 + 30},
                sun_context={"sun_state": "above_horizon"},
            )

    def test_les_reglages_du_cerveau_arrivent_a_la_decision(self) -> None:
        brain = GazonBrain()
        self.assertEqual(self._snapshot(brain)["mowing_daily_session_limit"], 2)
        brain.reglages = {"tonte_max_par_jour": 3, "arrosage_ouverture": 300}
        snapshot = self._snapshot(brain)
        self.assertEqual(snapshot["mowing_daily_session_limit"], 3)
        self.assertEqual(snapshot["watering_window_start_minute"], 300)

    def test_l_expiration_de_l_historique_suit_la_duree_reglee(self) -> None:
        brain = GazonBrain()
        entree = {"type": "Scarification", "date": SEMIS.isoformat()}
        huit_jours_apres = SEMIS + timedelta(days=8)
        self.assertTrue(brain._is_history_item_expired(entree, huit_jours_apres))
        brain.reglages = {"mode_scarification_duree": 10}
        self.assertFalse(brain._is_history_item_expired(entree, huit_jours_apres))

    def test_les_reglages_ne_sont_pas_persistes_avec_l_etat(self) -> None:
        # Leur seule source est l'entrée : une copie dans le stockage finirait par diverger.
        brain = GazonBrain()
        brain.reglages = {"tonte_max_par_jour": 3}
        self.assertNotIn("reglages", brain.dump_state())


class LeNettoyageDesReglagesTests(unittest.TestCase):
    def test_seules_les_valeurs_valides_et_differentes_du_conseil_restent(self) -> None:
        propres = reglages.nettoyer({
            "tonte_vent_bloque": 45,          # gardée
            "tonte_vent_a_eviter": 20,        # égale au conseil : retirée
            "inconnu": 3,                     # inconnue : retirée
            "graines_vent_max": 200,          # hors bornes : retirée
            "sursemis_lame": "4",             # pas un nombre : retirée
            "arrosage_pause_duree": 27,       # hors du pas de 5 : retirée
        })
        self.assertEqual(propres, {"tonte_vent_bloque": 45})

    def test_une_contrainte_violee_ecarte_ses_deux_cotes(self) -> None:
        # Début 13:00 après une fin à 12:30, chacun valide seul ET compatible avec le conseil de
        # l'autre côté : retirer un seul des deux suffirait à lever la contradiction. Les deux partent.
        propres = reglages.nettoyer({"tonte_fenetre_ideale_debut": 780, "tonte_fenetre_ideale_fin": 750, "tonte_max_par_jour": 3})
        self.assertEqual(propres, {"tonte_max_par_jour": 3})
        # Une valeur hors bornes, elle, part seule : l'autre côté reste s'il tient face au conseil.
        self.assertEqual(
            reglages.nettoyer({"tonte_fenetre_ideale_debut": 900, "tonte_fenetre_ideale_fin": 870}),
            {"tonte_fenetre_ideale_fin": 870},
        )

    def test_une_contrainte_jugee_contre_le_conseil(self) -> None:
        # Seul le début est réglé, après la fin CONSEILLÉE (14:00) : écarté.
        self.assertEqual(reglages.nettoyer({"tonte_fenetre_ideale_debut": 14 * 60}), {})

    def test_forme_des_valeurs(self) -> None:
        propres = reglages.nettoyer({"tonte_hauteur_par_mois": HAUTEURS_AVRIL_6, "tonte_vent_bloque": 45.0, "graines_germination_dose": 2.0})
        self.assertEqual(propres["tonte_hauteur_par_mois"], [float(v) for v in HAUTEURS_AVRIL_6])
        self.assertIsInstance(propres["tonte_vent_bloque"], int)
        self.assertIsInstance(propres["graines_germination_dose"], float)

    def test_rien_ou_n_importe_quoi(self) -> None:
        for brut in (None, [], "reglages", 3):
            with self.subTest(brut=brut):
                self.assertEqual(reglages.nettoyer(brut), {})

    def test_lire_refuse_une_cle_inconnue(self) -> None:
        with self.assertRaises(KeyError):
            reglages.lire({}, "faute_de_frappe", 1)
        self.assertEqual(reglages.lire(None, "tonte_vent_bloque", 40), 40)
        self.assertEqual(reglages.lire({"tonte_vent_bloque": 45}, "tonte_vent_bloque", 40), 45)

    def test_valeurs_effectives(self) -> None:
        effectives = reglages.valeurs_effectives({"tonte_vent_bloque": 45})
        self.assertEqual(effectives["tonte_vent_bloque"], 45)
        self.assertEqual(effectives["tonte_vent_a_eviter"], 20)
        self.assertEqual(set(effectives), {r.cle for r in reglages.REGLAGES})


class LesCreneauxDesGrainesTests(unittest.TestCase):
    def test_les_defauts_de_la_fenetre_sont_ceux_de_guidance(self) -> None:
        self.assertEqual(watering_policy._OUVERTURE_GRAINES_MIN, guidance.SEMIS_WINDOW_START_HOUR * 60)
        self.assertEqual(watering_policy._FERMETURE_GRAINES_MIN, guidance.SEMIS_WINDOW_END_HOUR * 60)

    def test_sans_reglage_le_programme_est_la_constante(self) -> None:
        for etape in ("germination", "levee", "enracinement"):
            with self.subTest(etape=etape):
                _, programme = watering_policy.resolve_semis_stage_program(etape, reglages={"tonte_max_par_jour": 3})
                self.assertEqual(programme, watering_policy.SEMIS_STAGE_PROGRAMS[etape])

    def test_les_creneaux_suivent_l_ouverture(self) -> None:
        _, programme = watering_policy.resolve_semis_stage_program("germination", reglages={"graines_fenetre_debut": 8 * 60})
        self.assertEqual(programme.cycle_slots_minutes, (480, 600, 720, 840))

    def test_un_creneau_apres_la_fermeture_est_retire_et_borne_les_arrosages(self) -> None:
        # Ouverture à 12:00 : le 4ᵉ créneau tomberait à 18:00, après la fermeture de 17:00.
        _, programme = watering_policy.resolve_semis_stage_program(
            "germination", reglages={"graines_fenetre_debut": 12 * 60, "graines_germination_cycles": 4}
        )
        self.assertEqual(programme.cycle_slots_minutes, (720, 840, 960))
        self.assertEqual(
            (programme.daily_cycles_min, programme.daily_cycles_optimal, programme.daily_cycles_max),
            (2, 3, 3),
        )

    def test_le_nombre_regle_est_nominal_et_la_meteo_garde_une_marge(self) -> None:
        _, programme = watering_policy.resolve_semis_stage_program(
            "germination", reglages={"graines_germination_cycles": 4}
        )
        self.assertEqual(
            (programme.daily_cycles_min, programme.daily_cycles_optimal, programme.daily_cycles_max),
            (3, 4, 4),
        )

    def test_la_marge_de_dose_suit_la_dose_reglee(self) -> None:
        _, programme = watering_policy.resolve_semis_stage_program("germination", reglages={"graines_germination_dose": 2.5})
        self.assertEqual(
            (programme.surface_cycle_mm_min, programme.surface_cycle_mm_optimal, programme.surface_cycle_mm_max),
            (2.2, 2.5, 2.8),
        )
        _, petite = watering_policy.resolve_semis_stage_program("germination", reglages={"graines_germination_dose": 0.5})
        self.assertEqual(petite.surface_cycle_mm_min, 0.2)

    def test_deux_arrosages_au_plus_quand_il_n_y_a_que_deux_creneaux(self) -> None:
        for etape, cle in (("levee", "graines_reprise_cycles"), ("enracinement", "graines_enracinement_cycles")):
            with self.subTest(etape=etape):
                self.assertEqual(reglages.reglage(cle).maximum, len(watering_policy.SEMIS_STAGE_PROGRAMS[etape].cycle_slots_minutes))


class ChaqueReglageEstBrancheTests(unittest.TestCase):
    AILLEURS = {
        # Lus par le coordinateur, avec ses faux coordinateurs.
        "arrosage_marge_avant_lever": "test_watering_session_monitoring.py",
        "arrosage_delai_relance": "test_watering_session_monitoring.py",
        # Le délai de l'alerte des graines : une alerte, pas une décision (0.94.0).
        "graines_alerte_retard": "test_notifications.py",
        # Le pilote pur vérifie chaque garde matérielle sans appeler Home Assistant.
        "tondeuse_pilotage_batterie_min": "test_mower_control.py",
        "tondeuse_pilotage_delai_commandes": "test_mower_control.py",
        "tondeuse_garage_ouvrir_avant_depart": "test_mower_control.py",
        "tondeuse_garage_ouvrir_pour_retour": "test_mower_control.py",
        "tondeuse_garage_fermer_apres_retour": "test_mower_control.py",
        "tondeuse_garage_avance_ouverture": "test_mower_control.py",
        "tondeuse_garage_delai_fermeture": "test_mower_control.py",
    }

    def test_chaque_reglage_a_son_scenario(self) -> None:
        dossier = Path(__file__).parent
        for r in reglages.REGLAGES:
            with self.subTest(cle=r.cle):
                nom = self.AILLEURS.get(r.cle, Path(__file__).name)
                source = (dossier / nom).read_text(encoding="utf-8")
                self.assertTrue(f'"{r.cle}"' in source, f"{r.cle} n'a pas de scénario dans {nom}")


if __name__ == "__main__":
    unittest.main()
