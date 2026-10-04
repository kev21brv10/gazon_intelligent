"""Un travail inachevé garde le volet ouvert : la tondeuse rentrée se recharger repart seule.

Quand le travail n'a pas été lancé par ce pilote (appli du constructeur, programme horaire), rien ne dit
au pilote que la tondeuse va repartir : il la tenait pour « rentrée » et refermait le volet après son
délai, la tondeuse repartant ensuite vers une porte close. Le garde est borné : un vieux travail
abandonné ne bloque pas la fermeture pour toujours.
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
constantes = importlib.import_module("custom_components.gazon_intelligent.mower_control_constants")

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)


def _il_y_a(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def _recharge(**maj):
    """Rentrée se recharger au milieu d'un travail ; la décision de tonte n'autorise pas un départ."""
    base = {
        "tondeuse_source_entity": "lawn_mower.x", "tondeuse_connectee": True, "tondeuse_prete": True,
        "mower_is_docked": True, "mower_is_outside": False, "mower_is_mowing": False, "mower_is_returning": False,
        "mower_operation_state": "charging", "mower_dock_signal_fort": True, "mower_battery": 30,
        "gazon_permet_tonte": True, "action_possible": False, "mowing_window_state": "acceptable",
        "mower_job_completion_state": "en_pause", "mower_job_progress_pct": 55, "mower_job_resume_possible": False,
        "mower_pass_count_today": 1, "mowing_daily_session_limit": 2,
    }
    base.update(maj)
    return base


REGLAGES = {"tondeuse_garage_delai_fermeture": 1.0, "tondeuse_garage_fermer_apres_retour": True}


def _decider(snapshot, *, runtime=None, mode="actif", cover="open", reglages=None):
    runtime = {"docked_since": _il_y_a(10), **(runtime or {})}
    return mc.evaluate_mower_control(
        snapshot, now=NOW, mode=mode, settings={**REGLAGES, **(reglages or {})}, runtime=runtime,
        cover_entity="cover.garage", cover_state=cover, cover_position=100, bootstrap_complete=True,
    )


class TravailInacheveGardeLeVoletOuvertTests(unittest.TestCase):
    def test_travail_en_pause_a_quai_le_volet_reste_ouvert(self) -> None:
        r = _decider(_recharge(mower_job_completion_state="en_pause"))
        self.assertEqual(r["mower_control_state"], "travail_inacheve")
        self.assertIsNone(r["mower_control_pending_action"])
        self.assertIn("reste ouvert", r["mower_control_reason"])

    def test_travail_encore_en_cours_a_quai_le_volet_reste_ouvert(self) -> None:
        r = _decider(_recharge(mower_job_completion_state="en_cours"))
        self.assertEqual(r["mower_control_state"], "travail_inacheve")

    def test_vieux_travail_repris_possible_le_volet_reste_ouvert_dans_la_limite(self) -> None:
        r = _decider(_recharge(mower_job_completion_state="repos", mower_job_resume_possible=True),
                     runtime={"docked_since": _il_y_a(90)})
        self.assertEqual(r["mower_control_state"], "travail_inacheve")

    def test_aucun_travail_en_cours_le_volet_est_referme_comme_avant(self) -> None:
        for etat, extra in (
            ("termine", {}), ("repos", {"mower_job_resume_possible": False}), ("sans_mesure", {}), ("", {}),
        ):
            with self.subTest(etat=etat):
                r = _decider(_recharge(mower_job_completion_state=etat, **extra))
                self.assertEqual(r["mower_control_pending_action"], "close_cover")
                self.assertEqual(r["mower_control_state"], "fermeture_garage")

    def test_la_garde_est_bornee_un_travail_abandonne_ne_bloque_pas_la_fermeture_pour_toujours(self) -> None:
        limite = constantes.MOWER_JOB_HOLD_MAX_MINUTES
        for etat, extra in (("en_pause", {}), ("en_cours", {}), ("repos", {"mower_job_resume_possible": True})):
            with self.subTest(etat=etat):
                snap = _recharge(mower_job_completion_state=etat, **extra)
                avant = _decider(snap, runtime={"docked_since": _il_y_a(limite - 1)})
                apres = _decider(snap, runtime={"docked_since": _il_y_a(limite + 1)})
                self.assertEqual(avant["mower_control_state"], "travail_inacheve")
                self.assertEqual(apres["mower_control_pending_action"], "close_cover")

    def test_la_limite_est_de_trois_heures(self) -> None:
        self.assertEqual(constantes.MOWER_JOB_HOLD_MAX_MINUTES, 180)

    def test_le_travail_termine_le_volet_est_referme_tout_de_suite(self) -> None:
        """La rentrée date de plusieurs heures : le délai de sécurité est déjà écoulé."""
        r = _decider(_recharge(mower_job_completion_state="termine"), runtime={"docked_since": _il_y_a(100)})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_la_rentree_est_notee_pendant_la_garde(self) -> None:
        """`docked_since` est posé même quand le volet est gardé ouvert : la limite se compte depuis la rentrée."""
        r = mc.evaluate_mower_control(
            _recharge(), now=NOW, mode="actif", settings=REGLAGES, runtime={}, cover_entity="cover.garage",
            cover_state="open", cover_position=100, bootstrap_complete=True,
        )
        self.assertEqual(r["mower_control_state"], "travail_inacheve")
        self.assertEqual(r["mower_control_runtime_updates"]["docked_since"], NOW.isoformat())

    def test_meme_decision_en_observation_et_en_actif(self) -> None:
        for mode in ("observation", "actif"):
            with self.subTest(mode=mode):
                r = _decider(_recharge(), mode=mode)
                self.assertEqual(r["mower_control_state"], "travail_inacheve")
                self.assertIsNone(r["mower_control_pending_action"])

    def test_une_reprise_due_du_pilote_referme_comme_avant(self) -> None:
        """Si le pilote a lui-même interrompu le cycle (`resume_required`), il referme exprès."""
        r = _decider(_recharge(), runtime={"resume_required": True, "managed_cycle_active": False})
        self.assertNotEqual(r["mower_control_state"], "travail_inacheve")

    def test_fermeture_automatique_desactivee_le_message_d_origine_prime(self) -> None:
        r = _decider(_recharge(), reglages={"tondeuse_garage_fermer_apres_retour": False})
        self.assertEqual(r["mower_control_state"], "rangee")

    def test_cycle_lance_par_le_pilote_reste_autonome(self) -> None:
        r = _decider(_recharge(), runtime={"managed_cycle_active": True})
        self.assertEqual(r["mower_control_state"], "cycle_autonome")

    def test_volet_deja_ferme_rien_a_garder(self) -> None:
        r = _decider(_recharge(), cover="closed")
        self.assertNotEqual(r["mower_control_state"], "travail_inacheve")

    def test_tondeuse_dehors_la_regle_du_volet_ferme_reste_la_meme(self) -> None:
        dehors = _recharge(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True,
                           mower_operation_state="tonte", mower_dock_signal_fort=False, mower_job_completion_state="en_cours")
        r = _decider(dehors, cover="closed")
        self.assertEqual(r["mower_control_pending_action"], "open_cover")


class TravailInacheveDansLeCoordinateurTests(unittest.TestCase):
    """Par le vrai cycle : aucun ordre de fermeture tant que le travail n'est pas fini."""

    def test_aucun_close_cover_pendant_la_recharge_puis_fermeture_a_la_fin_du_travail(self) -> None:
        from tests.test_garage_coordinateur import VoletDansLeCoordinateurTests
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord("actif")
        for minutes in (0.0, 1.5, 3.0, 20.0, 40.0):
            base._cycle(coord, _recharge(), apres=minutes, etat="open", position=100)
        self.assertNotIn("close_cover", base._ordres(appel))
        instantane = base._cycle(coord, _recharge(mower_job_completion_state="termine"), apres=5.0)
        self.assertEqual(base._ordres(appel)[-1], "close_cover", f"fin du travail : fermeture ({instantane['mower_control_state']})")


if __name__ == "__main__":
    unittest.main()
