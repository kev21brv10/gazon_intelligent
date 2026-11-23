"""Volet « porte » : la fermeture pendant la tonte ne passe jamais devant le rappel de sécurité.

Signalé en revue de la PR #85. Avec `tondeuse_garage_ferme_pendant_tonte`, la branche « fermer le volet
derrière la tondeuse qui tond » retournait AVANT le contrôle « le gazon n'autorise plus la tonte » :
- pendant le délai de fermeture, le rappel (`dock`) attendait d'abord ces quelques secondes ;
- un volet qui ne se ferme pas (trois ordres sans effet, « volet bloqué ») supprimait le rappel pour de
  bon : la tondeuse continuait de tondre malgré l'interdiction, tant que le volet ne se fermait pas.

La fermeture « pour les chats » est facultative ; le rappel est une règle de sécurité. Les cas ci-dessous
passent par le VRAI chemin d'application (`_async_apply_mower_control`), et par la décision pure pour les
variantes.
"""

from __future__ import annotations

import types
import unittest

from tests.test_manual_coordinateur import _Base, _dehors, _quai
from tests.test_mower_control_volet_porte import (
    PORTE,
    SANS_PORTE,
    _decider,
    _il_y_a,
    _rentre,
    _tond,
)

REGLAGES = {"tondeuse_garage_ferme_pendant_tonte": True}
INTERDIT = {"gazon_permet_tonte": False}


class DecisionPureTests(unittest.TestCase):
    def test_tonte_interdite_le_rappel_passe_avant_le_delai_de_fermeture(self) -> None:
        r = _decider(_tond(**INTERDIT), runtime={"mowing_since": _il_y_a(5)})
        self.assertEqual(r["mower_control_pending_action"], "dock")
        self.assertEqual(r["mower_control_state"], "retour_demande")

    def test_tonte_interdite_le_rappel_passe_avant_la_fermeture_du_volet(self) -> None:
        r = _decider(_tond(**INTERDIT), runtime={"mowing_since": _il_y_a(60)})
        self.assertEqual(r["mower_control_pending_action"], "dock")

    def test_tonte_interdite_volet_en_cours_d_ouverture_ou_ouvert_le_rappel_part(self) -> None:
        for cover, position in (("open", 100), ("open", 40), ("opening", 50)):
            with self.subTest(cover=cover, position=position):
                r = _decider(_tond(**INTERDIT), runtime={"mowing_since": _il_y_a(60)}, cover=cover, position=position)
                self.assertEqual(r["mower_control_pending_action"], "dock")

    def test_volet_bloque_apres_trois_fermetures_le_rappel_part_quand_meme(self) -> None:
        """Le scénario signalé : tondeuse en tonte, tonte interdite, volet ouvert, trois fermetures sans effet."""
        serie = {
            "mowing_since": _il_y_a(600), "garage_commande": "close_cover", "garage_tentatives": 3,
            "garage_commande_a": _il_y_a(30), "garage_serie_debut": _il_y_a(400),
        }
        # Témoin : tonte permise, le volet bloqué reste signalé et rien ne part (comportement d'avant).
        permise = _decider(_tond(), runtime=serie)
        self.assertEqual(permise["mower_control_state"], "volet_bloque")
        self.assertIsNone(permise["mower_control_pending_action"])
        interdite = _decider(_tond(**INTERDIT), runtime=serie)
        self.assertEqual(interdite["mower_control_pending_action"], "dock")
        self.assertEqual(interdite["mower_control_state"], "retour_demande")

    def test_volet_en_temporisation_le_rappel_part_quand_meme(self) -> None:
        serie = {"mowing_since": _il_y_a(600), "garage_commande": "close_cover", "garage_tentatives": 1,
                 "garage_commande_a": _il_y_a(20), "garage_serie_debut": _il_y_a(20)}
        self.assertEqual(_decider(_tond(), runtime=serie)["mower_control_state"], "temporisation")
        self.assertEqual(_decider(_tond(**INTERDIT), runtime=serie)["mower_control_pending_action"], "dock")

    def test_tonte_permise_rien_ne_change(self) -> None:
        for runtime, attendu_etat, attendu_action in (
            ({"mowing_since": _il_y_a(5)}, "attente_fermeture_tonte", None),
            ({"mowing_since": _il_y_a(60)}, "fermeture_pendant_tonte", "close_cover"),
        ):
            with self.subTest(etat=attendu_etat):
                r = _decider(_tond(), runtime=runtime)
                self.assertEqual(r["mower_control_state"], attendu_etat)
                self.assertEqual(r["mower_control_pending_action"], attendu_action)

    def test_tonte_interdite_plus_de_fermeture_apres_l_envoi_du_rappel(self) -> None:
        """Rappel déjà envoyé (temporisation de la commande) : on n'enchaîne pas une fermeture devant la tondeuse qui rentre."""
        runtime = {"mowing_since": _il_y_a(60), "last_action": "dock", "last_action_at": _il_y_a(30)}
        r = _decider(_tond(**INTERDIT), runtime=runtime, reglages={**PORTE, "tondeuse_pilotage_delai_commandes": 10})
        self.assertEqual(r["mower_control_state"], "temporisation")
        self.assertIsNone(r["mower_control_pending_action"])

    def test_la_tondeuse_qui_rentre_n_est_pas_rappelee_et_son_volet_s_ouvre(self) -> None:
        r = _decider(_rentre(**INTERDIT), cover="closed", position=0)
        self.assertEqual(r["mower_control_pending_action"], "open_cover")
        # Volet déjà ouvert : elle rentre, un second rappel n'aurait aucun sens.
        ouvert = _decider(_rentre(**INTERDIT), runtime={"mowing_since": _il_y_a(60)})
        self.assertIsNone(ouvert["mower_control_pending_action"])

    def test_le_rappel_part_aussi_quand_elle_tond_sans_etre_signalee_dehors(self) -> None:
        """Même jugement que l'envoi du rappel : « dehors » OU « en tonte » suffit."""
        r = _decider(_tond(mower_is_outside=False, **INTERDIT), runtime={"mowing_since": _il_y_a(5)})
        self.assertEqual(r["mower_control_pending_action"], "dock")

    def test_sans_le_reglage_le_rappel_part_comme_avant(self) -> None:
        r = _decider(_tond(**INTERDIT), runtime={"mowing_since": _il_y_a(60)}, reglages=SANS_PORTE)
        self.assertEqual(r["mower_control_pending_action"], "dock")

    def test_commande_manuelle_en_cours_le_pilote_ne_rappelle_toujours_pas(self) -> None:
        """Le mode manuel garde la priorité : ni rappel, et la fermeture derrière la tondeuse reste ce qu'elle était."""
        manuel = _tond(mower_manual_active=True, mower_manual_step="dehors", **INTERDIT)
        apres_delai = _decider(manuel, runtime={"mowing_since": _il_y_a(60)})
        self.assertEqual(apres_delai["mower_control_pending_action"], "close_cover")
        avant_delai = _decider(manuel, runtime={"mowing_since": _il_y_a(5)})
        self.assertEqual(avant_delai["mower_control_state"], "attente_fermeture_tonte")
        self.assertIsNone(avant_delai["mower_control_pending_action"])

    def test_en_observation_le_rappel_est_affiche(self) -> None:
        r = _decider(_tond(**INTERDIT), runtime={"mowing_since": _il_y_a(5)}, mode="observation")
        self.assertEqual(r["mower_control_pending_action"], "dock")


class CheminReelTests(_Base):
    """Volet « porte » + pilote actif, par le coordinateur : ce que Home Assistant recevrait."""

    def _tondeuse_qui_tond(self, coord, *, interdit: bool, apres: float = 0.0, etat=None, position=None):
        # ⚠️ `_dehors()` part d'un gazon qui N'autorise PAS la tonte : la permission est donc posée à chaque fois.
        instantane = _dehors(gazon_permet_tonte=not interdit)
        return self._cycle(coord, instantane, apres=apres, etat=etat, position=position)

    def _volet_ouvert(self) -> None:
        self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})

    def test_trois_fermetures_sans_effet_puis_interdiction_le_rappel_part(self) -> None:
        coord = self._coord("actif", reglages=REGLAGES)
        self._volet_ouvert()
        self._tondeuse_qui_tond(coord, interdit=False)                       # note l'instant de tonte
        for _ in range(3):                                                    # le volet ne bouge jamais
            self._tondeuse_qui_tond(coord, interdit=False, apres=2.5)
        self.assertEqual(self._ordres(), ["cover.close_cover"] * 3)
        bloque = self._tondeuse_qui_tond(coord, interdit=False, apres=2.5)
        self.assertEqual(bloque["mower_control_state"], "volet_bloque")
        self.assertEqual(self._ordres(), ["cover.close_cover"] * 3, "tonte permise : aucun ordre de plus")
        interdite = self._tondeuse_qui_tond(coord, interdit=True, apres=0.5)
        self.assertEqual(self._ordres()[-1], "lawn_mower.dock", "le rappel n'est pas masqué par le volet bloqué")
        self.assertEqual(interdite["mower_control_state"], "retour_demande")
        self.assertEqual(self._donnees_de_l_appel(), {"entity_id": "lawn_mower.esperance_jr"})

    def test_interdiction_pendant_le_delai_de_fermeture_le_rappel_part_aussitot(self) -> None:
        coord = self._coord("actif", reglages=REGLAGES)
        self._volet_ouvert()
        self._tondeuse_qui_tond(coord, interdit=False)
        etat = self._tondeuse_qui_tond(coord, interdit=True, apres=0.1)      # 6 s : le délai (15 s) court encore
        self.assertEqual(self._ordres(), ["lawn_mower.dock"])
        self.assertEqual(etat["mower_control_state"], "retour_demande")

    def test_apres_le_rappel_aucune_fermeture_ne_part_devant_la_tondeuse_qui_rentre(self) -> None:
        coord = self._coord("actif", reglages=REGLAGES)
        self._volet_ouvert()
        self._tondeuse_qui_tond(coord, interdit=False)
        self._tondeuse_qui_tond(coord, interdit=True, apres=0.1)
        self.assertEqual(self._ordres(), ["lawn_mower.dock"])
        # Elle n'a pas encore changé d'état : ni second rappel (temporisation), ni fermeture.
        self._tondeuse_qui_tond(coord, interdit=True, apres=1.0)
        self._tondeuse_qui_tond(coord, interdit=True, apres=1.0)
        self.assertEqual(self._ordres(), ["lawn_mower.dock"])
        # Elle rentre : le volet est déjà ouvert, rien à commander.
        en_retour = _dehors(mower_is_mowing=False, mower_is_returning=True, mower_operation_state="transit", **INTERDIT)
        self._cycle(coord, en_retour, apres=1.0)
        self.assertEqual(self._ordres(), ["lawn_mower.dock"])

    def test_tonte_permise_le_volet_se_ferme_comme_avant(self) -> None:
        coord = self._coord("actif", reglages=REGLAGES)
        self._volet_ouvert()
        self._tondeuse_qui_tond(coord, interdit=False)
        self._tondeuse_qui_tond(coord, interdit=False, apres=0.1)
        self.assertEqual(self._ordres(), [], "délai de fermeture non échu")
        self._tondeuse_qui_tond(coord, interdit=False, apres=0.5)
        self.assertEqual(self._ordres(), ["cover.close_cover"])

    def test_sortie_manuelle_le_pilote_ne_rappelle_pas_et_ferme_toujours_derriere(self) -> None:
        coord = self._coord("actif", reglages=REGLAGES)
        self._volet_ouvert()
        coord._latest_full_snapshot = _quai()
        self.assertTrue(self._demander(coord, "demarrer")["ok"])
        self._cycle(coord, _quai(), apres=0.5)
        self._cycle(coord, _quai(), apres=2.5)
        self._cycle(coord, _dehors(gazon_permet_tonte=True), apres=1.0)       # elle sort : mode manuel « dehors »
        avant = list(self._ordres())
        self._cycle(coord, _dehors(**INTERDIT), apres=1.0)
        self._cycle(coord, _dehors(**INTERDIT), apres=1.0)
        nouveaux = self._ordres()[len(avant):]
        self.assertNotIn("lawn_mower.dock", nouveaux, "mode manuel : le pilote ne rappelle pas")
        self.assertIn("cover.close_cover", nouveaux, "mode manuel : la fermeture derrière la tondeuse est inchangée")

    def test_volet_non_porte_le_rappel_part_comme_avant(self) -> None:
        coord = self._coord("actif", reglages={})
        self._volet_ouvert()
        self._tondeuse_qui_tond(coord, interdit=True)
        self.assertEqual(self._ordres(), ["lawn_mower.dock"])

