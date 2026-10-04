"""Volet « porte » : fermé pendant la tonte, ouvert seulement pour laisser passer la tondeuse.

Réglage facultatif (éteint par défaut) demandé pour que les chats ne puissent pas entrer dans le cabanon
pendant la tonte : le volet s'ouvre pour laisser SORTIR la tondeuse, se referme dès qu'elle tond, se rouvre
quand elle REVIENT, et se referme derrière elle une fois à quai — y compris pour une recharge à mi-travail.
Réglages : "tondeuse_garage_ferme_pendant_tonte" et "tondeuse_garage_delai_fermeture_tonte".
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
PORTE = {"tondeuse_garage_ferme_pendant_tonte": True, "tondeuse_garage_delai_fermeture_tonte": 0.25,
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
        r = _decider(_tond(), reglages={**PORTE, "tondeuse_garage_delai_fermeture_tonte": 0})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_le_delai_regle_est_celui_applique(self) -> None:
        for delai, ecoule, attendu in ((0.5, 20, None), (0.5, 31, "close_cover"), (0.25, 14, None), (0.25, 16, "close_cover")):
            with self.subTest(delai=delai, ecoule=ecoule):
                r = _decider(_tond(), runtime={"mowing_since": _il_y_a(ecoule)},
                             reglages={**PORTE, "tondeuse_garage_delai_fermeture_tonte": delai})
                self.assertEqual(r["mower_control_pending_action"], attendu)

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
        reglages = {k: v for k, v in PORTE.items() if k != "tondeuse_garage_delai_fermeture_tonte"}
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
        self.assertEqual(constantes.DEFAULT_MOWER_GARAGE_CLOSE_WHILE_MOWING_DELAY_MINUTES, 0.25)
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


class JourneeCompleteDansLeCoordinateurTests(unittest.TestCase):
    """Par le vrai cycle (pilote actif) : sortie, tonte, retour, rentrée."""

    def test_le_volet_est_une_porte_sortie_fermeture_retour_ouverture_rentree_fermeture(self) -> None:
        from tests.test_garage_coordinateur import VoletDansLeCoordinateurTests, _pret
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord("actif")
        coord._reglages_instance = lambda: {
            "tondeuse_garage_ferme_pendant_tonte": True, "tondeuse_garage_delai_fermeture_tonte": 0.25,
            "tondeuse_garage_delai_fermeture": 1.0, "tondeuse_garage_avance_ouverture": 0.25,
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
        self.assertIn('"tondeuse_garage_delai_fermeture_tonte"', garage)


if __name__ == "__main__":
    unittest.main()
