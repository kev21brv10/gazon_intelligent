"""Mode « volet seul » : le volet suit l'état de la tondeuse, l'intégration ne la commande JAMAIS.

Le mode actif commande aussi la tondeuse (départ, retour, reprise). Ici la tondeuse reste gérée par son
appli et ses horaires : seul le volet est ouvert devant elle quand elle sort ou rentre, et refermé après
sa rentrée, avec toutes les sécurités de fermeture et d'alerte.
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
constantes = importlib.import_module("custom_components.gazon_intelligent.mower_control_constants")

NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)
REGLAGES = {"tondeuse_garage_delai_fermeture": 1.0, "tondeuse_garage_fermer_apres_retour": True}
ORDRES_DE_TONDEUSE = {"start_mowing", "dock"}


def _il_y_a(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def _quai(**maj):
    base = {
        "tondeuse_source_entity": "lawn_mower.x", "tondeuse_connectee": True, "tondeuse_prete": True,
        "mower_is_docked": True, "mower_is_outside": False, "mower_is_mowing": False, "mower_is_returning": False,
        "mower_operation_state": "docked", "mower_dock_signal_fort": True, "mower_battery": 100,
        "gazon_permet_tonte": True, "action_possible": False, "mowing_window_state": "ideal",
        "mower_job_completion_state": "repos", "mower_pass_count_today": 0, "mowing_daily_session_limit": 2,
    }
    base.update(maj)
    return base


def _dehors(**maj):
    base = dict(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True, mower_operation_state="tonte",
                mower_dock_signal_fort=False, mower_job_completion_state="en_cours")
    base.update(maj)
    return _quai(**base)


def _decider(snapshot, *, runtime=None, mode="volet_seul", cover="open", position=100, entite="cover.garage"):
    return mc.evaluate_mower_control(
        snapshot, now=NOW, mode=mode, settings=REGLAGES, runtime={"docked_since": _il_y_a(10), **(runtime or {})},
        cover_entity=entite, cover_state=cover, cover_position=position, bootstrap_complete=True,
    )


class ModeDeclareTests(unittest.TestCase):
    def test_le_mode_existe_et_se_place_entre_observation_et_actif(self) -> None:
        self.assertEqual(constantes.MOWER_CONTROL_MODES, ("desactive", "observation", "volet_seul", "actif"))
        self.assertEqual(constantes.MOWER_CONTROL_COVER_ONLY, "volet_seul")

    def test_un_mode_inconnu_retombe_sur_le_defaut_desactive(self) -> None:
        r = _decider(_quai(), mode="n_importe_quoi")
        self.assertEqual(r["mower_control_mode"], constantes.DEFAULT_MOWER_CONTROL_MODE)


class LeVoletSuitLaTondeuseTests(unittest.TestCase):
    def test_tondeuse_dehors_volet_ferme_il_s_ouvre(self) -> None:
        r = _decider(_dehors(), cover="closed", position=0)
        self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_tondeuse_qui_demarre_ou_revient_le_volet_s_ouvre(self) -> None:
        for nom, maj in (("démarrage", {"mower_operation_state": "starting"}),
                         ("retour", {"mower_is_returning": True, "mower_is_mowing": False, "mower_operation_state": "transit"})):
            with self.subTest(cas=nom):
                r = _decider(_dehors(**maj), cover="closed", position=0)
                self.assertEqual(r["mower_control_pending_action"], "open_cover")

    def test_tondeuse_rentree_depart_non_autorise_le_volet_est_referme_apres_le_delai(self) -> None:
        r = _decider(_quai(action_possible=False))
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        self.assertEqual(r["mower_control_state"], "fermeture_garage")

    def test_le_delai_de_fermeture_est_respecte(self) -> None:
        r = _decider(_quai(), runtime={"docked_since": _il_y_a(0.2)})
        self.assertIsNone(r["mower_control_pending_action"])
        self.assertEqual(r["mower_control_state"], "attente_fermeture_garage")

    def test_un_travail_inacheve_garde_le_volet_ouvert(self) -> None:
        r = _decider(_quai(mower_job_completion_state="en_pause", mower_job_progress_pct=55))
        self.assertEqual(r["mower_control_state"], "travail_inacheve")
        self.assertIsNone(r["mower_control_pending_action"])

    def test_departs_possibles_le_volet_reste_ouvert_et_la_tondeuse_n_est_pas_lancee(self) -> None:
        """Conditions où le mode actif ouvrirait puis LANCERAIT la tondeuse : ici, rien."""
        r = _decider(_quai(action_possible=True))
        self.assertEqual(r["mower_control_state"], "volet_seul")
        self.assertIsNone(r["mower_control_pending_action"])

    def test_departs_possibles_volet_ferme_aucune_ouverture_pour_un_depart_que_l_on_n_enverra_pas(self) -> None:
        """⚠️ Le mode actif ouvre « avant le départ » parce qu'il va partir ; ici le départ n'est pas le nôtre."""
        r = _decider(_quai(action_possible=True), cover="closed", position=0)
        self.assertIsNone(r["mower_control_pending_action"])
        self.assertEqual(r["mower_control_state"], "volet_seul")

    def test_sans_volet_configure_rien_a_gerer(self) -> None:
        r = _decider(_quai(), entite=None, cover=None, position=None)
        self.assertEqual(r["mower_control_state"], "volet_seul")
        self.assertIsNone(r["mower_control_pending_action"])
        self.assertIn("Aucun volet", r["mower_control_reason"])

    def test_commande_manuelle_en_cours_le_pilote_s_efface_comme_avant(self) -> None:
        r = _decider(_quai(mower_manual_active=True, action_possible=False))
        self.assertEqual(r["mower_control_state"], "manuel")

    def test_retour_manuel_le_volet_est_referme_comme_avant(self) -> None:
        r = _decider(_quai(mower_job_completion_state="en_pause", mower_manual_suspension_active=True))
        self.assertEqual(r["mower_control_pending_action"], "close_cover")


class LaTondeuseNEstJamaisCommandeeTests(unittest.TestCase):
    def test_aucune_combinaison_ne_produit_un_ordre_de_tondeuse(self) -> None:
        """⚠️ L'invariant du mode : sur toutes les situations utiles, jamais `start_mowing` ni `dock`."""
        positions = {
            "à quai": _quai, "dehors": _dehors,
            "en retour": lambda **m: _dehors(mower_is_returning=True, mower_is_mowing=False, mower_operation_state="transit", **m),
            "démarrage": lambda **m: _dehors(mower_operation_state="starting", **m),
        }
        vues = 0
        for (nom, fabrique), action_possible, permet, completion, volet, runtime in itertools.product(
            positions.items(), (True, False), (True, False), ("repos", "termine", "en_pause", "en_cours", "sans_mesure"),
            (("open", 100), ("closed", 0), ("opening", 40), ("unavailable", None)),
            ({}, {"managed_cycle_active": True}, {"managed_start_pending": True}, {"resume_required": True},
             {"managed_cycle_active": True, "resume_required": True}),
        ):
            snapshot = fabrique(action_possible=action_possible, gazon_permet_tonte=permet, mower_job_completion_state=completion)
            r = _decider(snapshot, runtime=runtime, cover=volet[0], position=volet[1])
            action = r["mower_control_pending_action"]
            self.assertNotIn(action, ORDRES_DE_TONDEUSE, f"{nom} {action_possible} {permet} {completion} {volet} {runtime}")
            self.assertIn(action, (None, "open_cover", "close_cover"))
            vues += 1
        self.assertGreater(vues, 1000)

    def test_la_tondeuse_n_est_pas_rappelee_quand_le_gazon_interdit_la_tonte(self) -> None:
        """Le mode actif rappelle une tondeuse dehors quand le gazon l'interdit (pluie…) ; ici non."""
        r = _decider(_dehors(gazon_permet_tonte=False), cover="open")
        self.assertIsNone(r["mower_control_pending_action"])
        actif = _decider(_dehors(gazon_permet_tonte=False), mode="actif", cover="open")
        self.assertEqual(actif["mower_control_pending_action"], "dock", "témoin : le mode actif, lui, la rappelle")

    def test_le_mode_actif_lance_la_tondeuse_dans_la_meme_situation(self) -> None:
        """Témoin : mêmes conditions de départ ; actif envoie le départ, volet seul non."""
        snapshot = _quai(action_possible=True)
        actif = _decider(snapshot, mode="actif", runtime={"garage_opened_at": _il_y_a(10)})
        self.assertEqual(actif["mower_control_pending_action"], "start_mowing")
        self.assertIsNone(_decider(snapshot, runtime={"garage_opened_at": _il_y_a(10)})["mower_control_pending_action"])

    def test_un_reste_de_cycle_du_mode_actif_ne_bloque_pas_la_fermeture_et_est_efface(self) -> None:
        r = _decider(_quai(), runtime={"managed_cycle_active": True, "resume_required": True, "managed_start_pending": True})
        self.assertEqual(r["mower_control_pending_action"], "close_cover")
        maj = r["mower_control_runtime_updates"]
        for cle in ("managed_cycle_active", "resume_required", "managed_start_pending"):
            self.assertIs(maj[cle], False, cle)

    def test_une_reprise_due_d_un_ancien_mode_actif_n_exempte_pas_de_la_garde_du_travail_inacheve(self) -> None:
        """Le pilote ne reprend plus rien : une `resume_required` périmée ne doit pas faire refermer le volet
        devant une tondeuse en recharge à mi-travail."""
        snapshot = _quai(mower_job_completion_state="en_pause", mower_job_progress_pct=55)
        r = _decider(snapshot, runtime={"resume_required": True})
        self.assertEqual(r["mower_control_state"], "travail_inacheve")
        self.assertIsNone(r["mower_control_pending_action"])
        self.assertIs(r["mower_control_runtime_updates"]["resume_required"], False)

    def test_sans_reste_de_cycle_rien_n_est_ecrit(self) -> None:
        r = _decider(_quai())
        self.assertNotIn("managed_cycle_active", r["mower_control_runtime_updates"])

    def test_les_autres_modes_sont_inchanges(self) -> None:
        self.assertEqual(_decider(_quai(), mode="desactive")["mower_control_state"], "desactive")
        # Observation : même décision que le volet seul pour la fermeture, sans rien envoyer (le coordinateur filtre).
        self.assertEqual(_decider(_quai(), mode="observation")["mower_control_pending_action"], "close_cover")
        # Actif avec un cycle géré : toujours « cycle autonome ».
        r = _decider(_quai(), mode="actif", runtime={"managed_cycle_active": True})
        self.assertEqual(r["mower_control_state"], "cycle_autonome")


class VoletSeulDansLeCoordinateurTests(unittest.TestCase):
    """Par le vrai cycle : seuls des ordres de VOLET partent, et ils partent vraiment."""

    def _base(self):
        from tests.test_garage_coordinateur import VoletDansLeCoordinateurTests
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord("volet_seul")
        return base, coord, appel

    def test_tondeuse_dehors_volet_ferme_l_ordre_d_ouverture_part_sur_le_volet(self) -> None:
        from tests.test_garage_coordinateur import _pret
        base, coord, appel = self._base()
        dehors = dict(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True, mower_operation_state="tonte",
                      mower_dock_signal_fort=False, action_possible=False)
        instantane = base._cycle(coord, _pret(**dehors), etat="closed", position=0)
        self.assertEqual(base._ordres(appel), ["open_cover"])
        self.assertEqual(appel.await_args_list[-1].args[:2], ("cover", "open_cover"))
        self.assertEqual(appel.await_args_list[-1].args[2], {"entity_id": "cover.garage"})
        self.assertEqual(instantane["mower_control_last_action"], "open_cover")

    def test_tondeuse_rentree_le_volet_est_referme_et_la_tondeuse_n_est_jamais_commandee(self) -> None:
        from tests.test_garage_coordinateur import _pret
        base, coord, appel = self._base()
        base._cycle(coord, _pret(action_possible=False), etat="open", position=100)
        base._cycle(coord, _pret(action_possible=False), apres=1.0)
        base._cycle(coord, _pret(action_possible=False), apres=2.0)
        self.assertEqual(base._ordres(appel), ["close_cover"])
        for appel_service in appel.await_args_list:
            self.assertEqual(appel_service.args[0], "cover", "aucun service de tondeuse")

    def test_conditions_de_depart_reunies_la_tondeuse_n_est_pas_lancee_et_le_volet_pas_ouvert(self) -> None:
        from tests.test_garage_coordinateur import _pret
        base, coord, appel = self._base()
        for minutes in (0.0, 1.0, 3.0, 5.0):
            instantane = base._cycle(coord, _pret(action_possible=True), apres=minutes)
        self.assertEqual(base._ordres(appel), [], "ni départ, ni ouverture « avant le départ »")
        self.assertEqual(instantane["mower_control_state"], "volet_seul")

    def test_garde_fou_un_ordre_de_tondeuse_demande_par_une_regle_est_ignore(self) -> None:
        from unittest.mock import patch
        from tests.test_garage_coordinateur import _pret, coordinator_mod
        base, coord, appel = self._base()
        faux = {"mower_control_mode": "volet_seul", "mower_control_state": "volet_seul", "mower_control_reason": "x",
                "mower_control_pending_action": "start_mowing", "mower_control_runtime_updates": {}}
        with patch.object(coordinator_mod, "evaluate_mower_control", return_value=faux):
            instantane = base._cycle(coord, _pret())
        appel.assert_not_awaited()
        self.assertIsNone(instantane["mower_control_pending_action"])

    def test_la_decision_est_publiee_comme_pour_les_autres_modes(self) -> None:
        from tests.test_garage_coordinateur import _pret
        base, coord, _ = self._base()
        instantane = base._cycle(coord, _pret(action_possible=False), etat="closed", position=0)
        self.assertEqual(instantane["mower_control_mode"], "volet_seul")


class RegistreEtPageTests(unittest.TestCase):
    def test_le_choix_du_registre_propose_le_mode_avec_son_explication(self) -> None:
        reglages = importlib.import_module("custom_components.gazon_intelligent.reglages")
        (choix,) = [c for c in reglages.CHOIX if c.cle == "pilotage_tondeuse"]
        options = {o.valeur: o for o in choix.options}
        self.assertIn("volet_seul", options)
        self.assertEqual(options["volet_seul"].titre, "Volet seul")
        self.assertIn("sans jamais commander la tondeuse", options["volet_seul"].aide)
        self.assertEqual(tuple(options), constantes.MOWER_CONTROL_MODES)


if __name__ == "__main__":
    unittest.main()
