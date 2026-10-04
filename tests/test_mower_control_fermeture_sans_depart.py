"""Le volet se ferme quand le pilote n'a plus de départ à envoyer, pas seulement quand le gazon interdit la tonte.

Avant : tondeuse rentrée, travail terminé, tonte encore autorisée par le gazon → le volet restait ouvert
jusqu'à la nuit, même quand le quota du jour était atteint, le créneau non autorisé ou la batterie à
recharger. Maintenant il se ferme (après son délai) tant que le pilote ne repart pas, et se rouvre tout seul
avant le prochain départ.
"""

from __future__ import annotations

import importlib
import itertools
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

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
REGLAGES = {"tondeuse_garage_delai_fermeture": 1.0, "tondeuse_garage_fermer_apres_retour": True,
            "tondeuse_garage_avance_ouverture": 0.25, "tondeuse_creneaux_depart": "ideal_seulement"}


def _il_y_a(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def _rentree(**maj):
    """Rentrée, travail TERMINÉ, tonte autorisée par le gazon, un seul passage fait sur deux."""
    base = {
        "tondeuse_source_entity": "lawn_mower.x", "tondeuse_connectee": True, "tondeuse_prete": True,
        "mower_is_docked": True, "mower_is_outside": False, "mower_is_mowing": False, "mower_is_returning": False,
        "mower_operation_state": "docked", "mower_dock_signal_fort": True, "mower_battery": 100,
        "gazon_permet_tonte": True, "action_possible": True, "mowing_window_state": "ideal",
        "mower_job_completion_state": "termine", "mower_pass_count_today": 1, "mowing_daily_session_limit": 2,
    }
    base.update(maj)
    return base


def _decider(snapshot, *, runtime=None, mode="actif", cover="open", reglages=None, irrigation=False):
    return mc.evaluate_mower_control(
        snapshot, now=NOW, mode=mode, settings={**REGLAGES, **(reglages or {})},
        runtime={"docked_since": _il_y_a(30), "garage_opened_at": _il_y_a(30), **(runtime or {})},
        irrigation_active=irrigation, cover_entity="cover.garage", cover_state=cover, cover_position=100,
        bootstrap_complete=True,
    )


class FermeQuandLePiloteNeRepartPasTests(unittest.TestCase):
    def test_quota_du_jour_atteint_le_volet_se_ferme(self) -> None:
        r = _decider(_rentree(mower_pass_count_today=2))
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_quota_inconnu_le_volet_se_ferme_comme_le_depart_est_refuse(self) -> None:
        r = _decider(_rentree(mower_pass_count_today=None))
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_creneau_non_autorise_le_volet_se_ferme_selon_le_choix_de_creneaux(self) -> None:
        for politique, fenetre, ferme in (
            ("ideal_seulement", "acceptable", True), ("ideal_seulement", "discouraged", True), ("ideal_seulement", "ideal", False),
            ("ideal_acceptable", "acceptable", False), ("ideal_acceptable", "discouraged", True),
            ("tout_non_bloque", "discouraged", False), ("tout_non_bloque", "blocked", True), ("tout_non_bloque", "", True),
        ):
            with self.subTest(politique=politique, fenetre=fenetre):
                r = _decider(_rentree(mowing_window_state=fenetre), reglages={"tondeuse_creneaux_depart": politique})
                self.assertEqual(r["mower_control_pending_action"] == "close_cover", ferme)

    def test_batterie_a_recharger_le_volet_se_ferme(self) -> None:
        """Seuil de départ à 50 % : sous le seuil (ou inconnue) le pilote ne repart pas → fermeture ; au-dessus il repart."""
        for batterie, attendu in ((30, "close_cover"), (49, "close_cover"), (50, "start_mowing"), (80, "start_mowing"), (None, "close_cover")):
            with self.subTest(batterie=batterie):
                r = _decider(_rentree(mower_battery=batterie), reglages={"tondeuse_pilotage_batterie_min": 50})
                self.assertEqual(r["mower_control_pending_action"], attendu)

    def test_sans_seuil_regle_le_seuil_par_defaut_s_applique(self) -> None:
        constantes = importlib.import_module("custom_components.gazon_intelligent.mower_control_constants")
        seuil = constantes.DEFAULT_MOWER_CONTROL_MIN_BATTERY
        self.assertGreater(seuil, 0)
        sous = _decider(_rentree(mower_battery=seuil - 1))
        au_dessus = _decider(_rentree(mower_battery=seuil))
        self.assertEqual(sous["mower_control_pending_action"], "close_cover")
        self.assertEqual(au_dessus["mower_control_pending_action"], "start_mowing")

    def test_retour_manuel_recent_le_volet_se_ferme_meme_tonte_autorisee(self) -> None:
        r = _decider(_rentree(mower_manual_suspension_active=True))
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_le_pilote_repart_le_volet_reste_ouvert_et_le_depart_est_envoye(self) -> None:
        r = _decider(_rentree())
        self.assertEqual(r["mower_control_pending_action"], "start_mowing")

    def test_le_delai_de_fermeture_est_respecte(self) -> None:
        r = _decider(_rentree(mower_pass_count_today=2), runtime={"docked_since": _il_y_a(0.2)})
        self.assertIsNone(r["mower_control_pending_action"])
        self.assertEqual(r["mower_control_state"], "attente_fermeture_garage")

    def test_le_volet_deja_ferme_rien_a_faire_puis_le_pilote_l_ouvre_avant_le_depart(self) -> None:
        ferme = _decider(_rentree(mower_pass_count_today=2), cover="closed")
        self.assertNotEqual(ferme["mower_control_pending_action"], "close_cover")
        # Les conditions reviennent (nouveau créneau, quota du lendemain) : ouverture, puis départ.
        depart = _decider(_rentree(), cover="closed", runtime={"garage_opened_at": None})
        self.assertEqual(depart["mower_control_pending_action"], "open_cover")

    def test_un_travail_inacheve_garde_la_priorite_le_volet_reste_ouvert(self) -> None:
        r = _decider(_rentree(mower_pass_count_today=2, mower_job_completion_state="en_pause", mower_job_progress_pct=55))
        self.assertEqual(r["mower_control_state"], "travail_inacheve")

    def test_une_reprise_due_n_est_pas_un_depart_perdu_le_volet_ne_se_ferme_pas(self) -> None:
        r = _decider(_rentree(mower_pass_count_today=2), runtime={"resume_required": True})
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")

    def test_un_arrosage_en_cours_n_est_pas_un_depart_abandonne_le_volet_ne_se_ferme_pas(self) -> None:
        r = _decider(_rentree(), irrigation=True)
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")
        self.assertEqual(r["mower_control_state"], "bloque")

    def test_tondeuse_pas_prete_le_volet_ne_se_ferme_pas_pour_autant(self) -> None:
        r = _decider(_rentree(tondeuse_prete=False))
        self.assertNotEqual(r["mower_control_pending_action"], "close_cover")

    def test_tonte_interdite_la_fermeture_d_avant_est_inchangee(self) -> None:
        r = _decider(_rentree(action_possible=False))
        self.assertEqual(r["mower_control_pending_action"], "close_cover")

    def test_option_de_fermeture_automatique_desactivee_le_volet_reste_ouvert(self) -> None:
        r = _decider(_rentree(mower_pass_count_today=2), reglages={"tondeuse_garage_fermer_apres_retour": False})
        self.assertEqual(r["mower_control_state"], "rangee")

    def test_en_observation_la_decision_est_affichee_sans_envoi(self) -> None:
        r = _decider(_rentree(mower_pass_count_today=2), mode="observation")
        self.assertEqual(r["mower_control_pending_action"], "close_cover")


class CoherenceAvecLesGardesDeDepartTests(unittest.TestCase):
    """⚠️ `_departure_held` imite les gardes de départ : tant qu'il est vrai le pilote ne part jamais, tant qu'il est
    faux (et le reste passe) il part — jamais de fermeture dans ce cas."""

    def test_sur_toute_la_grille_la_fermeture_et_le_depart_s_excluent(self) -> None:
        vues = 0
        for (politique, fenetre, passes, batterie, suspension) in itertools.product(
            ("ideal_seulement", "ideal_acceptable", "tout_non_bloque"),
            ("ideal", "acceptable", "discouraged", "blocked", ""),
            (0, 1, 2, None),
            (100, 30, None),
            (False, True),
        ):
            snapshot = _rentree(mowing_window_state=fenetre, mower_pass_count_today=passes, mower_battery=batterie,
                                mower_manual_suspension_active=suspension)
            reglages = {"tondeuse_creneaux_depart": politique, "tondeuse_pilotage_batterie_min": 50}
            retenu = mc._departure_held(snapshot, {**REGLAGES, **reglages})
            action = _decider(snapshot, reglages=reglages)["mower_control_pending_action"]
            if retenu:
                self.assertEqual(action, "close_cover", f"{politique} {fenetre} {passes} {batterie} {suspension}")
            else:
                self.assertEqual(action, "start_mowing", f"{politique} {fenetre} {passes} {batterie} {suspension}")
            vues += 1
        self.assertEqual(vues, 3 * 5 * 4 * 3 * 2)


class FermetureEtReouvertureDansLeCoordinateurTests(unittest.TestCase):
    """Par le vrai cycle : fermeture une fois le quota atteint, puis ouverture avant le départ suivant."""

    def test_quota_atteint_le_volet_se_ferme_puis_se_rouvre_avant_le_depart_du_lendemain(self) -> None:
        from tests.test_garage_coordinateur import VoletDansLeCoordinateurTests, _pret
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord("actif")
        coord._reglages_instance = lambda: {"tondeuse_garage_delai_fermeture": 1.0, "tondeuse_garage_avance_ouverture": 0.25}
        # Soir : deuxième passage fait, quota atteint, mais le gazon autorise encore la tonte.
        soir = dict(action_possible=True, mower_pass_count_today=2, mower_job_completion_state="termine")
        base._cycle(coord, _pret(**soir), etat="open", position=100)
        instantane = base._cycle(coord, _pret(**soir), apres=0.5)
        self.assertEqual(instantane["mower_control_state"], "attente_fermeture_garage")
        base._cycle(coord, _pret(**soir), apres=0.7)
        self.assertEqual(base._ordres(appel), ["close_cover"], "fermé après le délai, alors que la tonte est encore possible")
        # Le lendemain : nouveau quota, créneau idéal, batterie pleine → ouverture, délai de sécurité, départ.
        matin = dict(action_possible=True, mower_pass_count_today=0, mower_job_completion_state="repos")
        base._cycle(coord, _pret(**matin), apres=600.0, etat="closed", position=0)
        self.assertEqual(base._ordres(appel)[-1], "open_cover")
        base._cycle(coord, _pret(**matin), apres=0.1, etat="open", position=100)
        base._cycle(coord, _pret(**matin), apres=0.4)
        self.assertEqual(base._ordres(appel)[-2:], ["open_cover", "start_mowing"])


if __name__ == "__main__":
    unittest.main()
