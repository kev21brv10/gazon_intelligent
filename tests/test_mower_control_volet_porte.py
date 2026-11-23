"""Volet « porte » : fermé pendant la tonte, ouvert seulement pour laisser passer la tondeuse.

Réglage facultatif (éteint par défaut) demandé pour que les chats ne puissent pas entrer dans le cabanon
pendant la tonte : le volet s'ouvre pour laisser SORTIR la tondeuse, se referme dès qu'elle tond, se rouvre
quand elle REVIENT, et se referme derrière elle une fois à quai — y compris pour une recharge à mi-travail.
Réglages : "tondeuse_garage_ferme_pendant_tonte" et "tondeuse_garage_delai_fermeture_tonte_secondes".
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
mc = importlib.import_module("custom_components.gazon_intelligent.mower_control")
gg = importlib.import_module("custom_components.gazon_intelligent.garage_guard")
man = importlib.import_module("custom_components.gazon_intelligent.manual_command")
constantes = importlib.import_module("custom_components.gazon_intelligent.mower_control_constants")

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
PORTE = {"tondeuse_garage_ferme_pendant_tonte": True, "tondeuse_garage_delai_fermeture_tonte_secondes": 15,
         "tondeuse_garage_delai_fermeture": 1.0, "tondeuse_garage_fermer_apres_retour": True,
         "tondeuse_garage_avance_ouverture": 0.25}
SANS_PORTE = {**PORTE, "tondeuse_garage_ferme_pendant_tonte": False}


def _il_y_a(secondes: float) -> str:
    return (NOW - timedelta(seconds=secondes)).isoformat()


def _quai(**maj):
    base = {
        "tondeuse_source_entity": "lawn_mower.x", "tondeuse_connectee": True, "tondeuse_prete": True,
        "mower_is_docked": True, "mower_is_outside": False, "mower_is_mowing": False, "mower_is_returning": False,
        "mower_operation_state": "docked", "mower_dock_signal_fort": True, "mower_battery": 100,
        "gazon_permet_tonte": True, "action_possible": False, "mowing_window_state": "ideal",
        "mower_job_completion_state": "termine", "mower_pass_count_today": 1, "mowing_daily_session_limit": 2,
    }
    base.update(maj)
    return base


def _tond(**maj):
    base = dict(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True, mower_operation_state="tonte",
                mower_dock_signal_fort=False, mower_job_completion_state="en_cours")
    base.update(maj)
    return _quai(**base)


def _demarre(**maj):
    return _tond(mower_is_mowing=False, mower_operation_state="starting", **maj)


def _rentre(**maj):
    return _tond(mower_is_mowing=False, mower_is_returning=True, mower_operation_state="transit", **maj)


def _decider(snapshot, *, runtime=None, mode="actif", cover="open", position=100, reglages=PORTE):
    return mc.evaluate_mower_control(
        snapshot, now=NOW, mode=mode, settings=reglages, runtime=runtime or {},
        cover_entity="cover.garage", cover_state=cover, cover_position=position, bootstrap_complete=True,
    )


class LeVoletSeFermePendantLaTonteTests(unittest.TestCase):
    def test_apres_le_delai_de_tonte_le_volet_se_ferme_derriere_la_tondeuse(self) -> None:
        r = _decider(_tond(), runtime={"mowing_since": _il_y_a(20)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        self.assertEqual(r["mower_control_state"], "fermeture_pendant_tonte")

    def test_avant_le_delai_il_attend(self) -> None:
        r = _decider(_tond(), runtime={"mowing_since": _il_y_a(5)})
        self.assertIsNone(r["mower_control_pending_action"])
        self.assertEqual(r["mower_control_state"], "attente_fermeture_tonte")
        self.assertIn("après 15 s", r["mower_control_reason"])

    def test_la_premiere_fois_qu_elle_tond_l_instant_est_note(self) -> None:
        r = _decider(_tond())
        self.assertEqual(r["mower_control_runtime_updates"]["mowing_since"], NOW.isoformat())
        self.assertIsNone(r["mower_control_pending_action"])

    def test_delai_zero_le_volet_se_ferme_aussitot(self) -> None:
        r = _decider(_tond(), reglages={**PORTE, "tondeuse_garage_delai_fermeture_tonte_secondes": 0})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_le_delai_regle_est_celui_applique(self) -> None:
        for delai, ecoule, attendu in (
            (30, 20, None), (30, 31, "close_cover"), (15, 14, None), (15, 16, "close_cover"),
            # À la seconde : de 1 à 4 s, la valeur réglée est bien celle qui s'applique.
            (1, 0.5, None), (1, 1.2, "close_cover"), (2, 1.5, None), (2, 2.2, "close_cover"),
            (3, 2.5, None), (3, 3.2, "close_cover"), (4, 3.5, None), (4, 4.2, "close_cover"),
        ):
            with self.subTest(delai=delai, ecoule=ecoule):
                r = _decider(_tond(), runtime={"mowing_since": _il_y_a(ecoule)},
                             reglages={**PORTE, "tondeuse_garage_delai_fermeture_tonte_secondes": delai})
                self.assertEqual(r["mower_control_pending_action"], attendu)

    def test_l_attente_publie_le_temps_restant_a_la_seconde_pres(self) -> None:
        """Le coordinateur cadence son prochain passage dessus : à 1 s près, pas au pas de 5 s."""
        for ecoule, reste in ((0, 15.0), (4, 11.0), (12.5, 2.5), (14, 1.0)):
            with self.subTest(ecoule=ecoule):
                r = _decider(_tond(), runtime={"mowing_since": _il_y_a(ecoule)})
                self.assertEqual(r["mower_control_state"], "attente_fermeture_tonte")
                self.assertAlmostEqual(r["mower_control_wait_seconds"], reste, places=3)
        # Première fois vue en tonte (rien noté) : tout le délai reste à attendre.
        premiere = _decider(_tond())
        self.assertEqual(premiere["mower_control_state"], "attente_fermeture_tonte")
        self.assertAlmostEqual(premiere["mower_control_wait_seconds"], 15.0, places=3)

    def test_le_temps_restant_n_est_publie_que_pendant_l_attente_de_fermeture(self) -> None:
        for libelle, r in (
            ("délai échu", _decider(_tond(), runtime={"mowing_since": _il_y_a(20)})),
            ("démarrage", _decider(_demarre())),
            ("retour", _decider(_rentre())),
            ("réglage éteint", _decider(_tond(), reglages=SANS_PORTE)),
        ):
            with self.subTest(cas=libelle):
                self.assertNotIn("mower_control_wait_seconds", r)

    def test_un_horodatage_de_tonte_abime_repart_de_maintenant_et_n_empeche_pas_la_fermeture(self) -> None:
        """Un « depuis quand » illisible ne devait jamais être « écoulé » : le volet ne se serait jamais fermé."""
        for abime in ("n'importe quoi", "2026-13-45T99:00:00", "12"):
            with self.subTest(abime=abime):
                r = _decider(_tond(), runtime={"mowing_since": abime})
                self.assertEqual(r["mower_control_runtime_updates"]["mowing_since"], NOW.isoformat())
                self.assertEqual(r["mower_control_state"], "attente_fermeture_tonte")
                self.assertAlmostEqual(r["mower_control_wait_seconds"], 15.0, places=3)
                # Une fois réécrit, le délai court normalement et le volet se ferme.
                suite = _decider(_tond(), runtime={"mowing_since": _il_y_a(16)})
                self.assertEqual(suite["mower_control_pending_action"], "close_cover")

    def test_pendant_son_demarrage_le_volet_reste_ouvert(self) -> None:
        r = _decider(_demarre(), runtime={"mowing_since": _il_y_a(60)})
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")

    def test_au_demarrage_un_volet_ferme_est_ouvert_pour_la_laisser_sortir(self) -> None:
        r = _decider(_demarre(), cover="closed", position=0)
        self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_en_tonte_un_volet_ferme_reste_ferme(self) -> None:
        r = _decider(_tond(), cover="closed", position=0)
        self.assertIsNone(r["mower_control_pending_action"])
        sans = _decider(_tond(), cover="closed", position=0, reglages=SANS_PORTE)
        self.assertEqual(sans["mower_control_pending_action"], "open_cover", "témoin : sans le réglage, il s'ouvre")

    def test_au_retour_le_volet_est_ouvert_pour_la_laisser_rentrer(self) -> None:
        r = _decider(_rentre(), cover="closed", position=0)
        self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_au_retour_volet_ouvert_aucun_ordre_et_jamais_de_fermeture(self) -> None:
        r = _decider(_rentre(), runtime={"mowing_since": _il_y_a(60)})
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")

    def test_l_option_ouvrir_pour_le_retour_desactivee_garde_son_effet(self) -> None:
        r = _decider(_rentre(), cover="closed", position=0, reglages={**PORTE, "tondeuse_garage_ouvrir_pour_retour": False})
        self.assertEqual(r["mower_control_state"], "bloque_garage")

    def test_une_tondeuse_en_pause_dehors_ne_provoque_ni_ouverture_ni_fermeture(self) -> None:
        pause = _tond(mower_is_mowing=False, mower_operation_state="paused")
        for cover, position in (("open", 100), ("closed", 0)):
            with self.subTest(cover=cover):
                r = _decider(pause, cover=cover, position=position)
                self.assertIsNone(r["mower_control_pending_action"])

    def test_l_instant_de_tonte_est_efface_des_qu_elle_ne_tond_plus(self) -> None:
        r = _decider(_rentre(), runtime={"mowing_since": _il_y_a(300)})
        self.assertIsNone(r["mower_control_runtime_updates"]["mowing_since"])

    def test_sans_le_reglage_rien_n_est_note_ni_ferme(self) -> None:
        r = _decider(_tond(), reglages=SANS_PORTE)
        self.assertNotIn("mowing_since", r["mower_control_runtime_updates"])
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")
        # Un reste d'une période où le réglage était allumé est effacé.
        r = _decider(_tond(), reglages=SANS_PORTE, runtime={"mowing_since": _il_y_a(300)})
        self.assertIsNone(r["mower_control_runtime_updates"]["mowing_since"])

    def test_sans_delai_regle_le_delai_par_defaut_de_15_secondes_s_applique(self) -> None:
        reglages = {k: v for k, v in PORTE.items() if k != "tondeuse_garage_delai_fermeture_tonte_secondes"}
        avant = _decider(_tond(), runtime={"mowing_since": _il_y_a(10)}, reglages=reglages)
        apres = _decider(_tond(), runtime={"mowing_since": _il_y_a(20)}, reglages=reglages)
        self.assertIsNone(avant["mower_control_pending_action"])
        self.assertEqual(apres["mower_control_pending_action"], "close_cover")

    def test_un_instantane_incoherent_retour_et_tonte_a_la_fois_ne_ferme_pas_le_volet(self) -> None:
        """Retour signalé alors que l'état dit encore « tonte » : le volet doit rester ouvert pour elle."""
        r = _decider(_tond(mower_is_returning=True), runtime={"mowing_since": _il_y_a(60)})
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")

    def test_le_reglage_est_eteint_par_defaut(self) -> None:
        self.assertIs(constantes.DEFAULT_MOWER_GARAGE_CLOSE_WHILE_MOWING, False)
        self.assertEqual(constantes.DEFAULT_MOWER_GARAGE_CLOSE_WHILE_MOWING_DELAY_SECONDS, 15)
        r = mc.evaluate_mower_control(_tond(), now=NOW, mode="actif", settings={}, runtime={}, cover_entity="cover.garage",
                                      cover_state="closed", cover_position=0, bootstrap_complete=True)
        self.assertEqual(r["mower_control_pending_action"], "open_cover", "sans réglage : comportement d'avant")

    def test_en_observation_la_decision_est_affichee_sans_envoi(self) -> None:
        r = _decider(_tond(), runtime={"mowing_since": _il_y_a(20)}, mode="observation")
        self.assertEqual(r["mower_control_pending_action"], "close_cover")


class ApresLaRentreeTests(unittest.TestCase):
    def test_a_quai_le_volet_se_ferme_derriere_apres_le_delai(self) -> None:
        r = _decider(_quai(), runtime={"docked_since": _il_y_a(120)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_l_attente_apres_la_rentree_publie_le_temps_restant_a_la_seconde_pres(self) -> None:
        reglages = {**PORTE, "tondeuse_garage_delai_fermeture": 1.0}                    # 60 s
        for ecoule, reste in ((0, 60.0), (10, 50.0), (47.5, 12.5), (59, 1.0)):
            with self.subTest(ecoule=ecoule):
                r = _decider(_quai(), runtime={"docked_since": _il_y_a(ecoule)}, reglages=reglages)
                self.assertEqual(r["mower_control_state"], "attente_fermeture_garage")
                self.assertAlmostEqual(r["mower_control_wait_seconds"], reste, places=3)
        # Première fois vue à quai (rien noté) : tout le délai reste à attendre.
        premiere = _decider(_quai(), runtime={}, reglages=reglages)
        self.assertAlmostEqual(premiere["mower_control_wait_seconds"], 60.0, places=3)
        # Délai échu : plus d'attente, donc plus de temps restant publié.
        echu = _decider(_quai(), runtime={"docked_since": _il_y_a(61)}, reglages=reglages)
        self.assertEqual(echu["mower_control_pending_action"], "close_cover")
        self.assertNotIn("mower_control_wait_seconds", echu)

    def test_a_quai_il_attend_son_delai_de_fermeture(self) -> None:
        r = _decider(_quai(), runtime={"docked_since": _il_y_a(10)})
        self.assertEqual(r["mower_control_state"], "attente_fermeture_garage")

    def test_recharge_a_mi_travail_le_volet_se_ferme_aussi_derriere_elle(self) -> None:
        recharge = _quai(mower_job_completion_state="en_pause", mower_job_progress_pct=55, mower_operation_state="charging")
        r = _decider(recharge, runtime={"docked_since": _il_y_a(120)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        garde = _decider(recharge, runtime={"docked_since": _il_y_a(120)}, reglages=SANS_PORTE)
        self.assertEqual(garde["mower_control_state"], "travail_inacheve", "témoin : sans le réglage il reste ouvert")

    def test_cycle_lance_par_le_pilote_recharge_le_volet_se_ferme_sans_jamais_relancer(self) -> None:
        recharge = _quai(action_possible=True, mower_job_completion_state="en_pause", mower_job_progress_pct=55,
                         mower_operation_state="charging")
        r = _decider(recharge, runtime={"managed_cycle_active": True, "docked_since": _il_y_a(120)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        ferme = _decider(recharge, runtime={"managed_cycle_active": True, "docked_since": _il_y_a(120)}, cover="closed", position=0)
        self.assertEqual(ferme["mower_control_state"], "cycle_autonome")
        self.assertIsNone(ferme["mower_control_pending_action"], "le pilote ne relance pas un cycle autonome")

    def test_cycle_lance_par_le_pilote_et_tondeuse_dehors_reste_autonome(self) -> None:
        r = _decider(_tond(), runtime={"managed_cycle_active": True, "mowing_since": _il_y_a(1)})
        self.assertEqual(r["mower_control_state"], "attente_fermeture_tonte")

    def test_le_pilote_va_repartir_le_volet_reste_ouvert(self) -> None:
        r = _decider(_quai(action_possible=True), runtime={"docked_since": _il_y_a(120), "garage_opened_at": _il_y_a(120)})
        self.assertEqual(r["mower_control_pending_action"], "start_mowing")

    def test_depart_envoye_et_tondeuse_encore_a_quai_le_volet_n_est_pas_ferme(self) -> None:
        r = _decider(_quai(action_possible=True), runtime={"managed_start_pending": True, "docked_since": _il_y_a(120),
                                                          "managed_start_requested_at": _il_y_a(5)})
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")
        self.assertEqual(r["mower_control_state"], "depart_envoye")

    def test_reprise_due_du_pilote_le_volet_n_est_pas_ferme(self) -> None:
        r = _decider(_quai(action_possible=True), runtime={"resume_required": True, "docked_since": _il_y_a(120)})
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")


class AlerteVoletFermeTests(unittest.TestCase):
    def _alerte(self, *, etat, depuis=600, porte=True, away=True, door=None):
        return gg.alert(cover_entity="cover.garage", cover_state=etat, position=0, mower_away=away,
                        runtime={gg.KEY_CLOSED_OUTSIDE_SINCE: _il_y_a(depuis)}, settings=None, now=NOW, door_needed=door)

    def test_volet_ferme_pendant_la_tonte_n_est_pas_une_anomalie_avec_le_volet_porte(self) -> None:
        self.assertIsNone(self._alerte(etat="closed", door=False))

    def test_volet_ferme_au_retour_ou_au_demarrage_est_une_anomalie(self) -> None:
        self.assertEqual(self._alerte(etat="closed", door=True)["code"], gg.ALERT_CLOSED_OUTSIDE)

    def test_sans_porte_le_comportement_d_avant_est_conserve(self) -> None:
        self.assertEqual(self._alerte(etat="closed")["code"], gg.ALERT_CLOSED_OUTSIDE)

    def test_le_depuis_quand_suit_le_besoin_de_la_porte(self) -> None:
        self.assertNotIn(gg.KEY_CLOSED_OUTSIDE_SINCE, gg.reset_updates({}, "closed", 0, NOW, mower_away=False))
        self.assertIn(gg.KEY_CLOSED_OUTSIDE_SINCE, gg.reset_updates({}, "closed", 0, NOW, mower_away=True))


class CommandeManuelleEtVoletPorteTests(unittest.TestCase):
    def _suite(self, etat, snapshot, *, volet="closed", position=0, reglages=PORTE):
        return man.evaluate(
            snapshot, now=NOW, state=etat, cover_entity="cover.garage", cover_state=volet, cover_position=position,
            settings=reglages, garage_runtime={}, irrigation_active=False, edgecut_available=True,
        )

    def _etat(self, commande, etape, **maj):
        base = man.new_state(commande, NOW - timedelta(seconds=60))
        base.update(etape=etape, **maj)
        return base

    def test_pendant_une_sortie_manuelle_le_volet_ferme_n_est_pas_rouvert_en_tonte(self) -> None:
        etat = self._etat("demarrer", "dehors", envoye_a=_il_y_a(60), vu_dehors=True)
        self.assertIsNone(self._suite(etat, _tond())["action"])
        sans = self._suite(etat, _tond(), reglages=SANS_PORTE)
        self.assertEqual(sans["action"]["service"], "cover.open_cover", "témoin : sans le réglage, il est rouvert")

    def test_pendant_une_sortie_manuelle_le_volet_est_rouvert_au_retour_et_au_demarrage(self) -> None:
        etat = self._etat("demarrer", "dehors", envoye_a=_il_y_a(60), vu_dehors=True)
        for snapshot in (_rentre(), _demarre()):
            with self.subTest(etat=snapshot["mower_operation_state"]):
                r = self._suite(etat, snapshot)
                self.assertEqual(r["action"]["service"], "cover.open_cover")

    def test_reprise_apres_pause_le_volet_ferme_n_est_pas_ouvert_pour_rien(self) -> None:
        en_pause = _tond(mower_operation_state="paused", mower_is_mowing=False)
        etat = self._etat("reprendre", "reprise_envoyee")
        r = self._suite(etat, en_pause)
        self.assertEqual(r["action"]["service"], "lawn_mower.start_mowing")
        sans = self._suite(etat, en_pause, reglages=SANS_PORTE)
        self.assertEqual(sans["action"]["service"], "cover.open_cover", "témoin : sans le réglage, le volet d'abord")

    def test_le_retour_ouvre_toujours_le_volet_avant_l_ordre(self) -> None:
        etat = self._etat("retour", "ouverture_garage")
        r = self._suite(etat, _tond())
        self.assertEqual(r["action"]["service"], "cover.open_cover")


class RedemarrageAutonomeApresRechargeTests(unittest.TestCase):
    """⚠️ Relevé réel du 04/10/2026 (22 h 11 → 22 h 12 min 47) : la tondeuse repart SEULE après sa recharge, l'état brut
    passe à `starting` mais le capteur « en charge » reste à True. Avec le vrai adaptateur de coordination (et non un
    instantané écrit à la main), le volet fermé doit s'ouvrir tout de suite pour la laisser sortir."""

    def _instantane(self, **brut):
        from custom_components.gazon_intelligent.mower_coordination import build_mower_coordination_context
        contexte = {"tondeuse_source_entity": "lawn_mower.x", "tondeuse_connectee": True, **brut}
        sortie = build_mower_coordination_context(contexte, enabled=True)
        cles = ("mower_operation_state", "mower_is_docked", "mower_is_outside", "mower_is_mowing",
                "mower_is_returning", "mower_dock_signal_fort")
        return _quai(**{k: sortie[k] for k in cles}, mower_job_completion_state="en_pause", mower_job_progress_pct=59,
                     mower_manual_active=True, mower_manual_step="dehors")

    def test_starting_avec_le_capteur_de_charge_encore_vrai_ouvre_le_volet_ferme(self) -> None:
        snapshot = self._instantane(tondeuse_etat_brut="starting", tondeuse_en_charge=True, tondeuse_statut="en_charge")
        self.assertEqual(snapshot["mower_operation_state"], "starting")
        for volet, position in (("closed", 0), ("closing", 20)):
            with self.subTest(volet=volet):
                r = _decider(snapshot, cover=volet, position=position)
                self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_la_meme_chose_hors_sortie_manuelle(self) -> None:
        snapshot = {**self._instantane(tondeuse_etat_brut="starting", tondeuse_en_charge=True),
                    "mower_manual_active": False, "mower_manual_step": None}
        r = _decider(snapshot, cover="closed", position=0)
        self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_un_retour_avec_le_capteur_de_charge_perime_ouvre_le_volet_ferme(self) -> None:
        """Constat A-014 : `returning` + « en charge » encore vrai (demi-tour juste après la sortie) — le volet doit s'ouvrir."""
        for reglages in (PORTE, SANS_PORTE):
            for volet, position in (("closed", 0), ("closing", 20)):
                with self.subTest(porte=reglages is PORTE, volet=volet):
                    snapshot = self._instantane(tondeuse_etat_brut="returning", tondeuse_en_charge=True,
                                                tondeuse_statut="retour_station")
                    self.assertEqual(snapshot["mower_operation_state"], "transit")
                    r = _decider(snapshot, cover=volet, position=position, reglages=reglages)
                    self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_a_quai_en_charge_le_volet_n_est_pas_rouvert(self) -> None:
        snapshot = self._instantane(tondeuse_etat_brut="charging", tondeuse_en_charge=True)
        r = _decider(snapshot, cover="closed", position=0)
        self.assertNotEqual(r["mower_control_pending_action"], "open_cover")


class RechargeEnSortieManuelleTests(unittest.TestCase):
    """⚠️ Relevé réel du 04/10/2026 (21 h 04) : sortie lancée depuis la page, tondeuse rentrée se recharger à 59 %,
    le pilote restait « manuel » et le volet restait OUVERT pendant toute la recharge (chats). En volet « porte »,
    il doit se refermer derrière elle ; il se rouvre à son redémarrage."""

    RECHARGE = dict(mower_job_completion_state="en_pause", mower_job_progress_pct=59, mower_operation_state="charging",
                    mower_manual_active=True, mower_manual_step="dehors")

    def _recharge(self, **maj):
        return _quai(**{**self.RECHARGE, **maj})

    def test_a_quai_en_recharge_pendant_une_sortie_manuelle_le_volet_se_ferme_apres_le_delai(self) -> None:
        r = _decider(self._recharge(), runtime={"docked_since": _il_y_a(130)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        self.assertEqual(r["mower_control_state"], "fermeture_garage")

    def test_meme_quand_le_gazon_autorise_encore_la_tonte_le_volet_se_ferme_derriere_elle(self) -> None:
        """Le cas réel n'est pas forcément « tonte interdite » : conditions bonnes, quota non atteint, batterie haute."""
        recharge = self._recharge(action_possible=True, mower_pass_count_today=0, mower_battery=100)
        r = _decider(recharge, runtime={"docked_since": _il_y_a(130)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        self.assertEqual(r["mower_control_state"], "fermeture_garage")

    def test_une_etape_dehors_perimee_sans_commande_manuelle_active_ne_ferme_rien_de_plus(self) -> None:
        """L'étape publiée ne suffit pas : c'est la commande ACTIVE qui efface le pilote ; sinon règles normales (le pilote peut repartir)."""
        perimee = self._recharge(mower_manual_active=False, action_possible=True, mower_pass_count_today=0,
                                 mower_job_completion_state="repos")
        r = _decider(perimee, runtime={"docked_since": _il_y_a(600)})
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")

    def test_invariant_seule_la_fermeture_passe_pendant_la_recharge_d_une_sortie_manuelle(self) -> None:
        """⚠️ Constat A-011 (relecture croisée) : si un cycle du pilote reste « actif » pendant la commande manuelle,
        la recharge avec gazon interdit déclenchait `interruption_recharge` → `dock`. Par construction, le chemin manuel
        ne passe plus que par la fermeture : on énumère toutes les combinaisons d'états du pilote."""
        import itertools
        n = 0
        for cycle, reprise, depart_en_cours, gazon, possible, cover, depuis in itertools.product(
            (False, True), (False, True), (False, True), (True, False), (True, False),
            (("open", 100), ("opening", 60)), (10, 130),
        ):
            runtime = {"docked_since": _il_y_a(depuis), "managed_cycle_active": cycle, "resume_required": reprise,
                       "managed_start_pending": depart_en_cours}
            snapshot = self._recharge(gazon_permet_tonte=gazon, action_possible=possible)
            with self.subTest(cycle=cycle, reprise=reprise, depart=depart_en_cours, gazon=gazon, possible=possible,
                              cover=cover[0], depuis=depuis):
                r = _decider(snapshot, runtime=runtime, cover=cover[0], position=cover[1])
                self.assertIn(r["mower_control_pending_action"], (None, "close_cover"),
                              f"état {r['mower_control_state']} : ordre {r['mower_control_pending_action']}")
                if depuis == 130:
                    self.assertEqual(r["mower_control_pending_action"], "close_cover")
                n += 1
        self.assertEqual(n, 2 ** 5 * 2 * 2)

    def test_l_option_fermer_apres_la_rentree_desactivee_est_respectee_aussi_en_sortie_manuelle(self) -> None:
        r = _decider(self._recharge(), runtime={"docked_since": _il_y_a(600)},
                     reglages={**PORTE, "tondeuse_garage_fermer_apres_retour": False})
        self.assertEqual(r["mower_control_state"], "rangee")
        self.assertIsNone(r["mower_control_pending_action"])

    def test_cycle_actif_gazon_interdit_ferme_au_lieu_de_rappeler(self) -> None:
        r = _decider(self._recharge(gazon_permet_tonte=False), runtime={
            "managed_cycle_active": True, "docked_since": _il_y_a(130)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        self.assertNotEqual(r["mower_control_state"], "interruption_recharge")

    def test_le_volet_en_cours_d_ouverture_est_aussi_referme_derriere_elle(self) -> None:
        r = _decider(self._recharge(), runtime={"docked_since": _il_y_a(130)}, cover="opening", position=40)
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_une_tondeuse_en_pause_dehors_pendant_la_sortie_manuelle_n_est_ni_rappelee_ni_touchee(self) -> None:
        """Seule une tondeuse À QUAI déclenche la fermeture : dehors (pause), le pilote reste en retrait, même gazon interdit."""
        pause = _tond(mower_operation_state="paused", mower_is_mowing=False, mower_manual_active=True, mower_manual_step="dehors")
        for maj in ({}, dict(gazon_permet_tonte=False)):
            with self.subTest(maj=maj):
                r = _decider({**pause, **maj}, runtime={"docked_since": _il_y_a(600)})
                self.assertEqual(r["mower_control_state"], "manuel")
                self.assertIsNone(r["mower_control_pending_action"])

    def test_il_attend_d_abord_son_delai_de_fermeture_apres_la_rentree(self) -> None:
        r = _decider(self._recharge(), runtime={"docked_since": _il_y_a(10)})
        self.assertEqual(r["mower_control_state"], "attente_fermeture_garage")
        self.assertIsNone(r["mower_control_pending_action"])
        premiere = _decider(self._recharge(), runtime={})
        self.assertEqual(premiere["mower_control_state"], "attente_fermeture_garage")
        self.assertEqual(premiere["mower_control_runtime_updates"]["docked_since"], NOW.isoformat())

    def test_le_delai_regle_apres_la_rentree_est_celui_applique(self) -> None:
        for delai_min, ecoule, attendu in ((1.0, 50, None), (1.0, 65, "close_cover"), (3.0, 150, None), (3.0, 185, "close_cover")):
            with self.subTest(delai=delai_min, ecoule=ecoule):
                r = _decider(self._recharge(), runtime={"docked_since": _il_y_a(ecoule)},
                             reglages={**PORTE, "tondeuse_garage_delai_fermeture": delai_min})
                self.assertEqual(r["mower_control_pending_action"], attendu)

    def test_sans_le_volet_porte_le_pilote_reste_en_retrait_comme_avant(self) -> None:
        r = _decider(self._recharge(), runtime={"docked_since": _il_y_a(300)}, reglages=SANS_PORTE)
        self.assertEqual(r["mower_control_state"], "manuel")
        self.assertIsNone(r["mower_control_pending_action"])

    def test_avant_la_sortie_le_volet_n_est_jamais_ferme(self) -> None:
        """Ouverture, délai de sécurité, départ envoyé : le volet est ouvert POUR elle, à quai ; la séquence manuelle le gère."""
        for etape in ("ouverture_garage", "attente_garage", "depart_envoye", "retour_envoye", "pause_envoyee", "reprise_envoyee", None, ""):
            with self.subTest(etape=etape):
                r = _decider(self._recharge(mower_manual_step=etape, mower_job_completion_state="repos"),
                             runtime={"docked_since": _il_y_a(600)})
                self.assertEqual(r["mower_control_state"], "manuel")
                self.assertIsNone(r["mower_control_pending_action"])

    def test_la_commande_manuelle_terminee_ou_absente_ne_change_rien_a_la_fermeture_normale(self) -> None:
        r = _decider(self._recharge(mower_manual_active=False), runtime={"docked_since": _il_y_a(130)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_volet_deja_ferme_rien_a_faire_et_le_pilote_reste_en_retrait(self) -> None:
        for cover, position in (("closed", 0), ("closing", 20)):
            with self.subTest(cover=cover):
                r = _decider(self._recharge(), runtime={"docked_since": _il_y_a(600)}, cover=cover, position=position)
                self.assertEqual(r["mower_control_state"], "manuel")
                self.assertIsNone(r["mower_control_pending_action"])

    def test_jamais_de_depart_ni_de_rappel_pendant_la_sortie_manuelle(self) -> None:
        """Seule la fermeture passe : même gazon autorisant la tonte, aucun `start_mowing` ni `dock`."""
        for maj in (dict(action_possible=True, mower_pass_count_today=0), dict(gazon_permet_tonte=False)):
            with self.subTest(maj=maj):
                for cover, position in (("open", 100), ("closed", 0)):
                    r = _decider(self._recharge(**maj), runtime={"docked_since": _il_y_a(600)}, cover=cover, position=position)
                    self.assertNotIn(r["mower_control_pending_action"], ("start_mowing", "dock"))

    def test_au_redemarrage_apres_la_recharge_le_volet_ferme_est_rouvert(self) -> None:
        """La suite de l'histoire : elle repart seule ; le volet fermé derrière elle se rouvre à `starting`."""
        redemarre = _demarre(mower_manual_active=True, mower_manual_step="dehors", mower_job_completion_state="en_cours")
        r = _decider(redemarre, cover="closed", position=0)
        self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_sans_entite_de_volet_aucun_ordre_de_fermeture(self) -> None:
        r = mc.evaluate_mower_control(
            self._recharge(), now=NOW, mode="actif", settings=PORTE, runtime={"docked_since": _il_y_a(600)},
            cover_entity=None, cover_state=None, cover_position=None, bootstrap_complete=True,
        )
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")


class JourneeCompleteDansLeCoordinateurTests(unittest.TestCase):
    """Par le vrai cycle (pilote actif) : sortie, tonte, retour, rentrée."""

    def test_le_volet_est_une_porte_sortie_fermeture_retour_ouverture_rentree_fermeture(self) -> None:
        from tests.test_garage_coordinateur import VoletDansLeCoordinateurTests, _pret
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord("actif")
        coord._reglages_instance = lambda: {
            "tondeuse_garage_ferme_pendant_tonte": True, "tondeuse_garage_delai_fermeture_tonte_secondes": 15,
            "tondeuse_garage_delai_fermeture_secondes": 60, "tondeuse_garage_avance_ouverture_secondes": 15,
        }
        depart = dict(action_possible=True, mower_job_completion_state="repos", mower_pass_count_today=0)
        # 1. Elle va sortir : ouverture, délai de sécurité, départ.
        base._cycle(coord, _pret(**depart), etat="closed", position=0)
        base._cycle(coord, _pret(**depart), apres=0.1, etat="open", position=100)
        base._cycle(coord, _pret(**depart), apres=0.3)
        self.assertEqual(base._ordres(appel), ["open_cover", "start_mowing"])
        # 2. Elle démarre, volet ouvert : rien. Puis elle tond : après 15 s le volet se referme derrière elle.
        sortie = dict(mower_is_docked=False, mower_is_outside=True, mower_dock_signal_fort=False, action_possible=True,
                      mower_job_completion_state="en_cours")
        base._cycle(coord, _pret(**sortie, mower_is_mowing=False, mower_operation_state="starting"), apres=0.1)
        self.assertEqual(base._ordres(appel), ["open_cover", "start_mowing"])
        tonte = _pret(**sortie, mower_is_mowing=True, mower_operation_state="tonte")
        base._cycle(coord, tonte, apres=0.2)
        self.assertEqual(base._ordres(appel)[-1], "start_mowing", "pas encore : 15 s à attendre")
        base._cycle(coord, tonte, apres=0.3)
        self.assertEqual(base._ordres(appel)[-1], "close_cover", "fermé derrière elle une fois en tonte")
        base._cycle(coord, tonte, apres=0.1, etat="closed", position=0)
        self.assertEqual(base._ordres(appel).count("open_cover"), 1, "le volet fermé n'est pas rouvert pendant la tonte")
        # 3. Elle rentre : le volet s'ouvre pour la laisser passer.
        retour = _pret(**sortie, mower_is_mowing=False, mower_is_returning=True, mower_operation_state="transit")
        base._cycle(coord, retour, apres=0.1)
        self.assertEqual(base._ordres(appel)[-1], "open_cover")
        base._cycle(coord, retour, apres=0.1, etat="open", position=100)
        # 4. Elle est à quai : le volet se referme derrière elle après son délai.
        fin = dict(action_possible=False, mower_job_completion_state="termine", mower_pass_count_today=2)
        base._cycle(coord, _pret(**fin), apres=0.3)
        base._cycle(coord, _pret(**fin), apres=0.5)
        base._cycle(coord, _pret(**fin), apres=0.7)
        self.assertEqual(base._ordres(appel)[-1], "close_cover")
        self.assertEqual(base._ordres(appel), ["open_cover", "start_mowing", "close_cover", "open_cover", "close_cover"])

    def test_pas_d_alerte_pendant_la_tonte_volet_ferme_mais_alerte_si_elle_rentre_devant_un_volet_ferme(self) -> None:
        from tests.test_garage_coordinateur import VoletDansLeCoordinateurTests, _pret
        for porte, attendu in ((True, None), (False, gg.ALERT_CLOSED_OUTSIDE)):
            with self.subTest(porte=porte):
                base = VoletDansLeCoordinateurTests()
                coord, appel = base._coord("observation")
                coord._reglages_instance = lambda porte=porte: {"tondeuse_garage_ferme_pendant_tonte": porte}
                tonte = _pret(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True, mower_operation_state="tonte",
                              mower_dock_signal_fort=False, action_possible=True, mower_job_completion_state="en_cours")
                base._cycle(coord, tonte, etat="closed", position=0)
                instantane = base._cycle(coord, tonte, apres=10.0)
                self.assertEqual(instantane["mower_garage_alert"], attendu, f"porte={porte}")
                since = coord._runtime_state["mower_control"].get(gg.KEY_CLOSED_OUTSIDE_SINCE)
                self.assertEqual(bool(since), not porte, "avec le volet porte, « fermé devant la tondeuse » n'est pas compté en tonte")
        # Elle rentre et trouve le volet fermé : alerte dans les deux cas, après la marge.
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord("observation")
        coord._reglages_instance = lambda: {"tondeuse_garage_ferme_pendant_tonte": True}
        retour = _pret(mower_is_docked=False, mower_is_outside=True, mower_is_returning=True, mower_operation_state="transit",
                       mower_dock_signal_fort=False, action_possible=True, mower_job_completion_state="en_cours")
        base._cycle(coord, retour, etat="closed", position=0)
        instantane = base._cycle(coord, retour, apres=10.0)
        self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_CLOSED_OUTSIDE)

    def test_une_sortie_manuelle_suit_aussi_le_volet_porte_par_le_vrai_cycle(self) -> None:
        """Commande manuelle en cours, tondeuse en tonte, volet fermé : l'orchestrateur manuel ne le rouvre pas
        avec le réglage, le rouvre sans (la règle « jamais de volet fermé devant une tondeuse dehors »)."""
        from tests.test_manual_coordinateur import RetourPauseReprendreTests, _quai as quai_manuel
        for porte, ouvre in ((True, False), (False, True)):
            with self.subTest(porte=porte):
                base = RetourPauseReprendreTests()
                coord = base._coord("actif")
                coord._reglages_instance = lambda porte=porte: {"tondeuse_garage_ferme_pendant_tonte": porte}
                coord._latest_full_snapshot = quai_manuel()
                self.assertTrue(base._demander(coord, "demarrer")["ok"])
                tonte = _tond(tondeuse_source_entity="lawn_mower.esperance_jr", mower_job_completion_state="en_cours")
                # État de la commande : déjà partie, tondeuse en tonte, volet fermé entre-temps.
                coord._runtime_state["mower_manual"].update(etape="dehors", envoye_a=NOW.isoformat(), vu_dehors=True)
                base._cycle(coord, tonte, etat="closed", position=0, apres=1.0)
                self.assertEqual("cover.open_cover" in base._ordres(), ouvre)

    def test_sortie_manuelle_recharge_a_mi_travail_le_volet_se_ferme_puis_se_rouvre_au_redemarrage(self) -> None:
        """⚠️ Relevé réel du 04/10/2026 par le VRAI cycle : `mower_manual_step` doit atteindre le pilote (déclarer n'est pas câbler)."""
        from tests.test_manual_coordinateur import RetourPauseReprendreTests, _quai as quai_manuel
        base = RetourPauseReprendreTests()
        coord = base._coord("actif", reglages={
            "tondeuse_garage_ferme_pendant_tonte": True, "tondeuse_garage_delai_fermeture_secondes": 60,
        })
        coord._latest_full_snapshot = quai_manuel()
        self.assertTrue(base._demander(coord, "demarrer")["ok"])
        coord._runtime_state["mower_manual"].update(etape="dehors", envoye_a=NOW.isoformat(), vu_dehors=True)
        recharge = quai_manuel(mower_job_completion_state="en_pause", mower_job_progress_pct=59,
                               mower_operation_state="charging", action_possible=False)
        # Rentrée se recharger, volet resté ouvert : le pilote reste en retrait (manuel) mais ferme derrière elle.
        premier = base._cycle(coord, recharge, etat="open", position=100, apres=1.0)
        self.assertEqual(premier["mower_manual_step"], "dehors")
        self.assertEqual(premier["mower_control_state"], "attente_fermeture_garage")
        self.assertNotIn("cover.close_cover", base._ordres())
        base._cycle(coord, recharge, apres=1.2)
        self.assertEqual(base._ordres().count("cover.close_cover"), 1, "refermé une fois le délai écoulé")
        # Le volet est fermé ; elle repart seule après la charge : le volet se rouvre à `starting`.
        base._cycle(coord, recharge, etat="closed", position=0, apres=0.2)
        redemarre = _demarre(tondeuse_source_entity="lawn_mower.esperance_jr", mower_job_completion_state="en_cours")
        base._cycle(coord, redemarre, apres=0.2)
        self.assertEqual(base._ordres().count("cover.open_cover"), 1, "rouvert pour la laisser sortir")
        self.assertNotIn("lawn_mower.start_mowing", base._ordres(), "jamais un départ envoyé par le pilote")
        self.assertNotIn("lawn_mower.dock", base._ordres())

    def test_le_reglage_eteint_le_volet_reste_ouvert_pendant_la_tonte(self) -> None:
        from tests.test_garage_coordinateur import VoletDansLeCoordinateurTests, _pret
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord("actif")
        coord._reglages_instance = lambda: {}
        tonte = _pret(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True, mower_operation_state="tonte",
                      mower_dock_signal_fort=False, action_possible=True, mower_job_completion_state="en_cours")
        for minutes in (0.0, 0.3, 1.0, 5.0):
            base._cycle(coord, tonte, apres=minutes, etat="open", position=100)
        self.assertNotIn("close_cover", base._ordres(appel))


class PageTests(unittest.TestCase):
    def test_les_deux_reglages_sont_proposes_dans_la_carte_du_garage(self) -> None:
        source = (PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js").read_text(encoding="utf-8")
        garage = source.split("_garageTondeuseHtml(choixSeulement = false) {")[1].split("\n  }\n")[0]
        self.assertIn('scenario("Pendant la tonte"', garage)
        self.assertIn('"tondeuse_garage_ferme_pendant_tonte"', garage)
        self.assertIn('"tondeuse_garage_delai_fermeture_tonte_secondes"', garage)


if __name__ == "__main__":
    unittest.main()
