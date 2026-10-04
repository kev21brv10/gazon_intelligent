"""Le volet de garage dans le vrai coordinateur : registre des ordres, alerte publiée, mode du pilote.

Tout passe par `_async_apply_mower_control` : ni registre ni alerte injectés à la main. Le coordinateur
réel demande l'appareillage de simulation de Home Assistant, déjà installé par
`test_watering_session_monitoring` : on réutilise son module plutôt que de le recopier.
"""

from __future__ import annotations

import asyncio
import importlib
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from tests.test_watering_session_monitoring import coordinator_mod

gg = importlib.import_module("custom_components.gazon_intelligent.garage_guard")

NOW = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)


def _pret(**maj):
    """Une tondeuse prête à partir, à quai, gazon autorisé."""
    instantane = {
        "tondeuse_source_entity": "lawn_mower.esperance_jr",
        "tondeuse_connectee": True, "tondeuse_prete": True,
        "mower_is_docked": True, "mower_is_outside": False, "mower_is_mowing": False,
        "mower_is_returning": False, "mower_operation_state": "docked", "mower_dock_signal_fort": True,
        "mower_battery": 100, "mower_pass_count_today": 0, "mowing_daily_session_limit": 2,
        "mowing_window_state": "ideal", "gazon_permet_tonte": True, "action_possible": True,
    }
    instantane.update(maj)
    return instantane


class _Horloge:
    def __init__(self) -> None:
        self.maintenant = NOW

    def avancer(self, minutes: float) -> None:
        self.maintenant = self.maintenant + timedelta(minutes=minutes)


class VoletDansLeCoordinateurTests(unittest.TestCase):
    """Tout passe par `_async_apply_mower_control` : ni registre ni alerte injectés à la main."""

    def _coord(self, mode: str = "actif"):
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        self.horloge = _Horloge()
        self.volet = types.SimpleNamespace(state="closed", attributes={"current_position": 0})
        appel = AsyncMock()
        coord.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda entity_id: self.volet if entity_id == "cover.garage" else None),
            services=types.SimpleNamespace(async_call=appel),
        )
        coord._runtime_state = {}
        coord._mower_control_bootstrap_complete = True
        coord._get_conf = lambda cle: (
            mode if cle == "pilotage_tondeuse" else "cover.garage" if cle == "entite_volet_garage_tondeuse" else None
        )
        coord._reglages_instance = lambda: {}
        coord.arrosage_en_cours = lambda: False
        coord._current_datetime = lambda: self.horloge.maintenant
        return coord, appel

    def _cycle(self, coord, instantane, *, etat=None, position=None, apres=0.0):
        if apres:
            self.horloge.avancer(apres)
        if etat is not None:
            self.volet = types.SimpleNamespace(state=etat, attributes={"current_position": position})
        asyncio.run(coord._async_apply_mower_control(instantane))
        return instantane

    @staticmethod
    def _ordres(appel) -> list[str]:
        return [c.args[1] for c in appel.await_args_list]

    def test_un_ordre_envoye_ouvre_une_serie_au_registre_et_le_pilote_ne_renvoie_pas_aussitot(self) -> None:
        coord, appel = self._coord()
        instantane = self._cycle(coord, _pret())
        self.assertEqual(self._ordres(appel), ["open_cover"])
        registre = coord._runtime_state["mower_control"]
        self.assertEqual(registre[gg.KEY_COMMAND], "open_cover")
        self.assertEqual(registre[gg.KEY_ATTEMPTS], 1)
        self.assertIs(registre[gg.KEY_OPENED_BY_PILOT], True)
        self.assertIsNone(instantane["mower_garage_alert"])
        self._cycle(coord, _pret(), apres=0.5)
        self.assertEqual(self._ordres(appel), ["open_cover"], "pas de second ordre avant le délai de reprise")

    def test_un_volet_qui_ne_bouge_pas_est_relance_deux_fois_puis_bloque_avec_alerte(self) -> None:
        coord, appel = self._coord()
        self._cycle(coord, _pret())
        self._cycle(coord, _pret(), apres=2.5)
        instantane = self._cycle(coord, _pret(), apres=2.5)
        self.assertEqual(self._ordres(appel), ["open_cover"] * 3)
        self.assertEqual(coord._runtime_state["mower_control"][gg.KEY_ATTEMPTS], 3)
        self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_STUCK)
        self.assertIn("à vérifier sur place", instantane["mower_garage_alert_reason"])
        # Plafond atteint : plus aucun ordre, même bien après le délai de reprise.
        instantane = self._cycle(coord, _pret(), apres=5.0)
        self.assertEqual(self._ordres(appel), ["open_cover"] * 3)
        self.assertEqual(instantane["mower_control_state"], "volet_bloque")
        self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_STUCK)

    def test_un_volet_bloque_reste_arrete_et_signale_jusqu_a_reparation(self) -> None:
        """⚠️ Décision du propriétaire : après le plafond, le pilote s'arrête ET l'alerte reste affichée
        tant que le volet n'a pas atteint sa position — pas d'oubli au bout d'une heure."""
        coord, appel = self._coord()
        self._cycle(coord, _pret())
        self._cycle(coord, _pret(), apres=2.5)
        self._cycle(coord, _pret(), apres=2.5)
        self.assertEqual(self._ordres(appel), ["open_cover"] * 3)
        for minutes in (61.0, 120.0, 300.0):
            instantane = self._cycle(coord, _pret(), apres=minutes)
            self.assertEqual(self._ordres(appel), ["open_cover"] * 3, "aucun ordre de plus")
            self.assertEqual(instantane["mower_control_state"], "volet_bloque")
            self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_STUCK, "l'alerte reste")
        self.assertEqual(coord._runtime_state["mower_control"][gg.KEY_ATTEMPTS], 3, "les tentatives ne sont pas remises à zéro")

    def test_le_plafond_regle_par_l_utilisateur_gouverne_aussi_la_duree_du_blocage(self) -> None:
        """Plafond réglé à 2 : après 2 ordres le volet est bloqué ET le reste bien au-delà d'une heure
        (le registre juge l'épuisement avec le RÉGLAGE, pas avec la valeur par défaut)."""
        coord, appel = self._coord()
        coord._reglages_instance = lambda: {"tondeuse_garage_tentatives_max": 2}
        self._cycle(coord, _pret())
        self._cycle(coord, _pret(), apres=2.5)
        instantane = self._cycle(coord, _pret(), apres=2.5)
        self.assertEqual(self._ordres(appel), ["open_cover"] * 2)
        self.assertEqual(instantane["mower_control_state"], "volet_bloque")
        instantane = self._cycle(coord, _pret(), apres=120.0)
        self.assertEqual(self._ordres(appel), ["open_cover"] * 2, "toujours aucun ordre à +2 h")
        self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_STUCK)

    def test_le_volet_repare_a_la_main_le_pilote_repart_et_l_alerte_s_efface(self) -> None:
        coord, appel = self._coord()
        for minutes in (0.0, 2.5, 2.5):
            self._cycle(coord, _pret(), apres=minutes)
        instantane = self._cycle(coord, _pret(), apres=200.0, etat="open", position=100)
        self.assertIsNone(instantane["mower_garage_alert"])
        self.assertIsNone(coord._runtime_state["mower_control"][gg.KEY_COMMAND])
        # Plus tard le volet est refermé par quelqu'un ; un nouveau besoin d'ouverture envoie un ordre.
        self._cycle(coord, _pret(), apres=30.0, etat="closed", position=0)
        self.assertEqual(self._ordres(appel)[-1], "open_cover")
        self.assertEqual(len(self._ordres(appel)), 4, "une nouvelle série, pas la suite de l'ancienne")

    def test_apres_24_heures_un_volet_bloque_est_retente(self) -> None:
        coord, appel = self._coord()
        for minutes in (0.0, 2.5, 2.5):
            self._cycle(coord, _pret(), apres=minutes)
        self._cycle(coord, _pret(), apres=25 * 60.0)
        self.assertEqual(len(self._ordres(appel)), 4)

    def test_un_volet_qui_atteint_sa_cible_ferme_la_serie_et_l_alerte(self) -> None:
        coord, appel = self._coord()
        self._cycle(coord, _pret())
        self._cycle(coord, _pret(), apres=2.5)
        instantane = self._cycle(coord, _pret(), apres=0.5, etat="open", position=100)
        registre = coord._runtime_state["mower_control"]
        self.assertIsNone(registre[gg.KEY_COMMAND])
        self.assertEqual(registre[gg.KEY_ATTEMPTS], 0)
        self.assertIsNone(instantane["mower_garage_alert"])
        self.assertIs(registre[gg.KEY_OPENED_BY_PILOT], True, "c'est nous qui l'avons ouvert")

    def test_en_observation_rien_n_est_envoye_ni_compte(self) -> None:
        coord, appel = self._coord("observation")
        for minutes in (0.0, 3.0, 3.0, 3.0):
            self._cycle(coord, _pret(), apres=minutes)
        appel.assert_not_awaited()
        self.assertIsNone(coord._runtime_state["mower_control"].get(gg.KEY_COMMAND))

    def test_volet_indisponible_tondeuse_dehors_alerte_apres_le_delai_de_grace_quel_que_soit_le_mode(self) -> None:
        dehors = dict(mower_is_docked=False, mower_is_outside=True, mower_operation_state="tonte")
        for mode in ("desactive", "observation", "actif"):
            with self.subTest(mode=mode):
                coord, appel = self._coord(mode)
                instantane = self._cycle(coord, _pret(**dehors), etat="unavailable", position=None)
                self.assertIsNone(instantane["mower_garage_alert"], "pas d'alerte au premier cycle (redémarrage)")
                instantane = self._cycle(coord, _pret(**dehors), apres=6.0)
                self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_UNAVAILABLE)
                self.assertIn("la tondeuse est dehors", instantane["mower_garage_alert_reason"])

    def test_le_volet_revient_avant_la_fin_du_delai_de_grace_aucune_alerte(self) -> None:
        coord, _ = self._coord("observation")
        dehors = dict(mower_is_docked=False, mower_is_outside=True, mower_operation_state="tonte")
        self._cycle(coord, _pret(**dehors), etat="unavailable", position=None)
        self._cycle(coord, _pret(**dehors), apres=3.0, etat="open", position=100)
        instantane = self._cycle(coord, _pret(**dehors), apres=4.0, etat="unavailable", position=None)
        self.assertIsNone(instantane["mower_garage_alert"], "le compte repart de zéro à chaque indisponibilité")

    def test_volet_indisponible_tondeuse_rentree_pas_d_alerte(self) -> None:
        coord, _ = self._coord("observation")
        instantane = self._cycle(coord, _pret(), etat="unavailable", position=None)
        self.assertIsNone(instantane["mower_garage_alert"])

    def test_sans_volet_configure_aucune_alerte_publiee(self) -> None:
        coord, _ = self._coord("observation")
        coord._get_conf = lambda cle: "observation" if cle == "pilotage_tondeuse" else None
        instantane = self._cycle(coord, _pret())
        self.assertIsNone(instantane["mower_garage_alert"])

    # ── un volet ouvert à la main ──
    def test_un_volet_vu_ferme_puis_ouvert_a_la_main_n_est_pas_referme_d_emblee(self) -> None:
        coord, appel = self._coord()
        quai = dict(action_possible=False)
        self._cycle(coord, _pret(**quai), etat="closed", position=0)              # vu fermé
        self._cycle(coord, _pret(**quai), apres=240.0, etat="closed", position=0)  # rentrée ancienne
        self.assertIs(coord._runtime_state["mower_control"][gg.KEY_OPENED_BY_PILOT], False)
        instantane = self._cycle(coord, _pret(**quai), apres=1.0, etat="open", position=100)  # ouvert à la main
        self.assertEqual(self._ordres(appel), [], "aucun ordre de fermeture")
        self.assertEqual(instantane["mower_control_state"], "attente_fermeture_garage")
        self.assertIn("Garage ouvert à la main", instantane["mower_control_reason"])
        instantane = self._cycle(coord, _pret(**quai), apres=29.0, etat="open", position=100)
        self.assertEqual(self._ordres(appel), [])
        instantane = self._cycle(coord, _pret(**quai), apres=2.0, etat="open", position=100)  # 32 min après l'ouverture
        self.assertEqual(self._ordres(appel), ["close_cover"])

    def test_un_volet_ouvert_par_le_pilote_est_referme_apres_le_delai_de_la_rentree(self) -> None:
        coord, appel = self._coord()
        self._cycle(coord, _pret())                                                  # le pilote ouvre
        self._cycle(coord, _pret(), apres=0.5, etat="open", position=100)            # ouvert
        # La tondeuse est sortie puis rentrée ; la tonte n'est plus possible.
        quai = dict(action_possible=False)
        self._cycle(coord, _pret(**quai), apres=60.0, etat="open", position=100)    # rentrée vue
        self._cycle(coord, _pret(**quai), apres=3.0, etat="open", position=100)     # délai écoulé
        self.assertEqual(self._ordres(appel), ["open_cover", "close_cover"])


class VoletFermeDevantUneTondeuseDehorsCoordinateurTests(unittest.TestCase):
    """L'alerte part dans les TROIS modes du pilote, par le vrai cycle, jusqu'à l'instantané publié."""

    DEHORS = dict(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True, mower_operation_state="tonte",
                  mower_dock_signal_fort=False, action_possible=False)

    def _coord(self, mode):
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord(mode)
        self.base = base
        return coord, appel

    def test_dans_chaque_mode_l_alerte_part_apres_la_marge(self) -> None:
        for mode in ("desactive", "observation", "actif"):
            with self.subTest(mode=mode):
                coord, appel = self._coord(mode)
                instantane = self.base._cycle(coord, _pret(**self.DEHORS), etat="closed", position=0)
                self.assertIsNone(instantane["mower_garage_alert"], "pas d'alerte au premier constat")
                instantane = self.base._cycle(coord, _pret(**self.DEHORS), apres=2.0)
                if mode != "actif":
                    self.assertIsNone(instantane["mower_garage_alert"], "dans la marge")
                instantane = self.base._cycle(coord, _pret(**self.DEHORS), apres=1.5)
                self.assertIn(
                    instantane["mower_garage_alert"], (gg.ALERT_CLOSED_OUTSIDE, gg.ALERT_STUCK),
                    f"{mode} : une alerte doit être publiée",
                )
                if mode != "actif":
                    self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_CLOSED_OUTSIDE)
                    self.assertIn("la tondeuse est dehors", instantane["mower_garage_alert_reason"])
                    self.assertEqual(self.base._ordres(appel), [], "observation / désactivé : rien n'est commandé")

    def test_le_volet_rouvert_dans_la_marge_aucune_alerte_et_la_trace_est_effacee(self) -> None:
        coord, _ = self._coord("observation")
        self.base._cycle(coord, _pret(**self.DEHORS), etat="closed", position=0)
        self.base._cycle(coord, _pret(**self.DEHORS), apres=2.0, etat="open", position=100)
        instantane = self.base._cycle(coord, _pret(**self.DEHORS), apres=3.0)
        self.assertIsNone(instantane["mower_garage_alert"])
        self.assertIsNone(coord._runtime_state["mower_control"].get(gg.KEY_CLOSED_OUTSIDE_SINCE))

    def test_le_volet_rouvert_apres_l_alerte_elle_s_efface(self) -> None:
        coord, _ = self._coord("desactive")
        self.base._cycle(coord, _pret(**self.DEHORS), etat="closed", position=0)
        instantane = self.base._cycle(coord, _pret(**self.DEHORS), apres=4.0)
        self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_CLOSED_OUTSIDE)
        instantane = self.base._cycle(coord, _pret(**self.DEHORS), apres=1.0, etat="open", position=100)
        self.assertIsNone(instantane["mower_garage_alert"])

    def test_tondeuse_rentree_volet_ferme_aucune_alerte_dans_aucun_mode(self) -> None:
        for mode in ("desactive", "observation", "actif"):
            with self.subTest(mode=mode):
                coord, _ = self._coord(mode)
                self.base._cycle(coord, _pret(action_possible=False), etat="closed", position=0)
                instantane = self.base._cycle(coord, _pret(action_possible=False), apres=10.0)
                self.assertIsNone(instantane["mower_garage_alert"])

    def test_la_cle_de_depuis_quand_est_persistee_avec_le_registre(self) -> None:
        coord, _ = self._coord("observation")
        self.base._cycle(coord, _pret(**self.DEHORS), etat="closed", position=0)
        self.assertTrue(coord._runtime_state["mower_control"].get(gg.KEY_CLOSED_OUTSIDE_SINCE))


class PiloteRejugeVitePendantLesAttentesDuVoletTests(unittest.TestCase):
    """⚠️ Le départ doit suivre l'ouverture du volet de quelques secondes, pas de plusieurs minutes.

    Sans minuteur court, le pilote ne se rejugeait qu'à l'intervalle normal (2 min) ou à un événement
    d'une entité suivie : la tondeuse partait bien après le délai de sécurité (36 s mesurés pour un délai
    de 15 s). Ici le vrai cycle demande lui-même un nouveau passage tant qu'il attend le volet.
    """

    def _coord(self, mode="actif", reglages=None):
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord(mode)
        coord._reglages_instance = lambda: dict(reglages or {})
        self.demandes = []
        coord._schedule_quick_refresh = lambda *a, **k: self.demandes.append(base.horloge.maintenant)
        self.base = base
        return coord, appel

    def _cycle(self, coord, snapshot, apres=0.0, **kw):
        return self.base._cycle(coord, snapshot, apres=apres, **kw)

    def test_le_depart_suit_l_ouverture_du_volet_de_quelques_secondes(self) -> None:
        coord, appel = self._coord(reglages={"tondeuse_garage_avance_ouverture": 0.25})   # 15 s
        secondes = 0
        # t = 0 : l'ordre d'ouverture part.
        self._cycle(coord, _pret(), etat="closed", position=0)
        self.assertEqual(self.base._ordres(appel), ["open_cover"])
        # Le volet s'ouvre : 6 s plus tard il est confirmé ouvert.
        self._cycle(coord, _pret(), apres=6 / 60, etat="open", position=100)
        secondes = 6
        depart_a = None
        while secondes < 120 and depart_a is None:
            # Un nouveau passage est demandé À CHAQUE ATTENTE : le minuteur réel (5 s) tourne.
            self.assertTrue(self.demandes, "aucun passage rapide demandé pendant l'attente du volet")
            self.demandes.clear()
            self._cycle(coord, _pret(), apres=5 / 60)
            secondes += 5
            if "start_mowing" in self.base._ordres(appel):
                depart_a = secondes
        self.assertIsNotNone(depart_a, "la tondeuse n'est jamais partie")
        self.assertLessEqual(depart_a - 6, 15 + 5, "départ au plus tard un pas de minuteur après le délai de sécurité")
        self.assertGreaterEqual(depart_a - 6, 15, "jamais avant le délai de sécurité")
        self.assertEqual(self.base._ordres(appel), ["open_cover", "start_mowing"])

    def test_l_ouverture_en_cours_et_le_delai_demandent_un_passage_rapide(self) -> None:
        for etat, position, attendu in (("closed", 0, "ouverture_garage"), ("opening", 40, "attente_garage"), ("open", 100, "attente_garage")):
            with self.subTest(etat=etat):
                coord, _ = self._coord(reglages={"tondeuse_garage_avance_ouverture": 2.0})
                instantane = self._cycle(coord, _pret(), etat=etat, position=position)
                self.assertEqual(instantane["mower_control_state"], attendu)
                self.assertTrue(self.demandes)

    def test_le_delai_avant_fermeture_demande_aussi_un_passage_rapide_et_la_fermeture_suit_le_delai(self) -> None:
        coord, appel = self._coord(reglages={"tondeuse_garage_delai_fermeture": 1.0})
        quai = dict(action_possible=False)
        self._cycle(coord, _pret(**quai), etat="open", position=100)            # rentrée vue (t = 0)
        ferme_a = None
        for pas in range(1, 30):
            self.demandes.clear()
            instantane = self._cycle(coord, _pret(**quai), apres=5 / 60)
            if "close_cover" in self.base._ordres(appel):
                ferme_a = pas * 5
                break
            self.assertEqual(instantane["mower_control_state"], "attente_fermeture_garage")
            self.assertTrue(self.demandes, "pas de passage rapide pendant le délai de fermeture")
        self.assertIsNotNone(ferme_a)
        self.assertGreaterEqual(ferme_a, 60)
        self.assertLessEqual(ferme_a, 65, "fermeture au plus un pas de minuteur après le délai")

    def test_pas_de_passage_rapide_en_observation_ni_desactive(self) -> None:
        for mode in ("observation", "desactive"):
            with self.subTest(mode=mode):
                coord, _ = self._coord(mode, reglages={"tondeuse_garage_avance_ouverture": 2.0})
                self._cycle(coord, _pret(), etat="open", position=100)
                self._cycle(coord, _pret(), apres=0.1)
                self.assertEqual(self.demandes, [])

    def test_pas_de_passage_rapide_quand_rien_n_attend_le_volet(self) -> None:
        coord, _ = self._coord()
        instantane = self._cycle(coord, _pret(action_possible=False, mower_pass_count_today=2), etat="closed", position=0)
        self.assertNotIn(instantane["mower_control_state"], coordinator_mod._PILOT_FAST_WAIT_STATES)
        self.assertEqual(self.demandes, [])

    def test_les_etats_d_attente_sont_ceux_du_pilote(self) -> None:
        self.assertEqual(
            coordinator_mod._PILOT_FAST_WAIT_STATES,
            frozenset({"ouverture_garage", "ouverture_garage_reprise", "attente_garage", "attente_fermeture_garage"}),
        )


class ChangementDeVoletTests(unittest.TestCase):
    """Un volet remplacé repart d'un registre vierge : il n'hérite pas du blocage de l'ancien."""

    def _coord(self):
        base = VoletDansLeCoordinateurTests()
        coord, appel = base._coord()
        self.base = base
        self.cover_conf = {"valeur": "cover.garage"}
        coord._get_conf = lambda cle: (
            "actif" if cle == "pilotage_tondeuse"
            else self.cover_conf["valeur"] if cle == "entite_volet_garage_tondeuse" else None
        )
        self.nouveau = types.SimpleNamespace(state="closed", attributes={"current_position": 0})
        coord.hass.states.get = lambda entity_id: (
            self.base.volet if entity_id == "cover.garage" else self.nouveau if entity_id == "cover.neuf" else None
        )
        return coord, appel

    def test_le_blocage_de_l_ancien_volet_ne_s_applique_pas_au_nouveau(self) -> None:
        coord, appel = self._coord()
        for minutes in (0.0, 2.5, 2.5):
            self.base._cycle(coord, _pret(), apres=minutes)
        self.assertEqual(self.base._ordres(appel), ["open_cover"] * 3)
        instantane = self.base._cycle(coord, _pret(), apres=2.5)
        self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_STUCK, "l'ancien volet est bien bloqué")
        # Le volet est remplacé par un autre, fermé : le pilote doit pouvoir l'ouvrir.
        self.cover_conf["valeur"] = "cover.neuf"
        instantane = self.base._cycle(coord, _pret(), apres=1.0)
        self.assertEqual(self.base._ordres(appel)[-1], "open_cover")
        self.assertEqual(len(self.base._ordres(appel)), 4, "un ordre de plus, pour le NOUVEAU volet")
        self.assertEqual(appel.await_args_list[-1].args[2], {"entity_id": "cover.neuf"})
        self.assertIsNone(instantane["mower_garage_alert"])
        self.assertEqual(coord._runtime_state["mower_control"][gg.KEY_ENTITY], "cover.neuf")

    def test_le_meme_volet_reste_bloque(self) -> None:
        coord, appel = self._coord()
        for minutes in (0.0, 2.5, 2.5, 2.5):
            self.base._cycle(coord, _pret(), apres=minutes)
        self.base._cycle(coord, _pret(), apres=10.0)
        self.assertEqual(self.base._ordres(appel), ["open_cover"] * 3, "aucun ordre de plus pour le même volet")
        self.assertEqual(coord._runtime_state["mower_control"][gg.KEY_ENTITY], "cover.garage")


class AnomalieDuVoletArriveJusqu_AuCapteurTests(unittest.TestCase):
    """⚠️ Déclarer n'est pas câbler : l'alerte doit suivre sa VALEUR jusqu'à l'entité publiée.

    Trois maillons, tous nécessaires : la liste blanche du coordinateur (sans elle la clé vaut
    toujours `None`), l'instantané décidé par le pilote, puis les attributs du capteur de tonte.
    """

    CLES = ("mower_garage_alert", "mower_garage_alert_reason")

    def test_les_deux_cles_sont_dans_la_liste_blanche_du_coordinateur(self) -> None:
        for cle in self.CLES:
            with self.subTest(cle=cle):
                self.assertIn(cle, coordinator_mod._COORDINATOR_SNAPSHOT_KEYS)

    def test_le_pilote_decide_puis_l_instantane_porte_l_alerte(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        horloge = _Horloge()
        volet = types.SimpleNamespace(state="unavailable", attributes={})
        coord.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(get=lambda e: volet if e == "cover.garage" else None),
            services=types.SimpleNamespace(async_call=AsyncMock()),
        )
        coord._runtime_state = {}
        coord._mower_control_bootstrap_complete = True
        coord._get_conf = lambda cle: (
            "observation" if cle == "pilotage_tondeuse" else "cover.garage" if cle == "entite_volet_garage_tondeuse" else None
        )
        coord._reglages_instance = lambda: {}
        coord.arrosage_en_cours = lambda: False
        coord._current_datetime = lambda: horloge.maintenant
        dehors = _pret(mower_is_docked=False, mower_is_outside=True, mower_operation_state="tonte")
        asyncio.run(coord._async_apply_mower_control(dehors))
        horloge.avancer(6.0)
        instantane = dict(dehors)
        asyncio.run(coord._async_apply_mower_control(instantane))
        for cle in self.CLES:
            self.assertTrue(instantane[cle], f"{cle} n'est pas dans l'instantané décidé")
        # Et la liste blanche la recopie dans les données publiées.
        publie = {cle: instantane.get(cle) for cle in coordinator_mod._COORDINATOR_SNAPSHOT_KEYS if cle in self.CLES}
        self.assertEqual(publie["mower_garage_alert"], gg.ALERT_UNAVAILABLE)

    def test_le_capteur_de_tonte_publie_l_alerte_en_attribut(self) -> None:
        from tests.test_entity_result_chain import _FakeCoordinator, _FakeEntry, sensor

        coordinateur = _FakeCoordinator(
            entry=_FakeEntry(),
            data={
                "mower_garage_alert": gg.ALERT_STUCK,
                "mower_garage_alert_reason": "Le volet n'a pas atteint sa position.",
                "mower_control_mode": "actif",
            },
            result=None, history=[], memory={},
        )
        attributs = sensor.GazonTonteEtatSensor(coordinateur).extra_state_attributes
        self.assertEqual(attributs["mower_garage_alert"], gg.ALERT_STUCK)
        self.assertEqual(attributs["mower_garage_alert_reason"], "Le volet n'a pas atteint sa position.")

    def test_sans_anomalie_les_attributs_sont_absents_ou_vides(self) -> None:
        from tests.test_entity_result_chain import _FakeCoordinator, _FakeEntry, sensor

        coordinateur = _FakeCoordinator(
            entry=_FakeEntry(), data={"mower_garage_alert": None, "mower_control_mode": "actif"},
            result=None, history=[], memory={},
        )
        attributs = sensor.GazonTonteEtatSensor(coordinateur).extra_state_attributes
        self.assertFalse(attributs.get("mower_garage_alert"))


if __name__ == "__main__":
    unittest.main()
