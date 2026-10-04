"""Commandes manuelles de la tondeuse dans le VRAI coordinateur et le VRAI pilote.

Tout passe par `async_commande_tondeuse` (la demande de la page) puis `_async_apply_mower_control`
(le cycle) : ni état manuel ni attribut injecté à la main. Les ordres sont lus sur le service Home
Assistant simulé — c'est ce qui part vers la machine et le volet.
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
mc = importlib.import_module("custom_components.gazon_intelligent.manual_command")
mower_control = importlib.import_module("custom_components.gazon_intelligent.mower_control")

NOW = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)
TONDEUSE = "lawn_mower.esperance_jr"


def _quai(**maj):
    """Une tondeuse prête à quai, batterie pleine ; le gazon n'autorise PAS de tonte automatique."""
    instantane = {
        "tondeuse_source_entity": TONDEUSE,
        "tondeuse_connectee": True, "tondeuse_prete": True,
        "mower_is_docked": True, "mower_is_outside": False, "mower_is_mowing": False,
        "mower_is_returning": False, "mower_operation_state": "docked", "mower_dock_signal_fort": True,
        "mower_battery": 100, "mower_pass_count_today": 0, "mowing_daily_session_limit": 2,
        "mowing_window_state": "ideal", "gazon_permet_tonte": False, "action_possible": False,
        "mower_job_completion_state": "repos",
    }
    instantane.update(maj)
    return instantane


def _dehors(**maj):
    base = dict(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True, mower_operation_state="tonte",
                mower_dock_signal_fort=False, mower_job_completion_state="en_cours")
    base.update(maj)
    return _quai(**base)


class _Horloge:
    def __init__(self) -> None:
        self.maintenant = NOW

    def avancer(self, minutes: float) -> None:
        self.maintenant = self.maintenant + timedelta(minutes=minutes)


class _Base(unittest.TestCase):
    avec_volet = True

    def _coord(self, mode: str = "actif", *, volet: bool | None = None, reglages=None):
        volet = self.avec_volet if volet is None else volet
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        self.horloge = _Horloge()
        self.volet = types.SimpleNamespace(state="closed", attributes={"current_position": 0})
        self.appel = AsyncMock()
        self.service_bordure = True
        coord.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(
                get=lambda entity_id: self.volet if entity_id == "cover.garage" else None
            ),
            services=types.SimpleNamespace(
                async_call=self.appel,
                has_service=lambda domaine, service: self.service_bordure
                and (domaine, service) == ("landroid_cloud", "ots"),
            ),
        )
        coord._runtime_state = {}
        coord._mower_control_bootstrap_complete = True
        coord._get_conf = lambda cle: (
            mode if cle == "pilotage_tondeuse"
            else "cover.garage" if cle == "entite_volet_garage_tondeuse" and volet
            else None
        )
        coord._reglages_instance = lambda: dict(reglages or {})
        coord.arrosage_en_cours = lambda: self.arrosage
        coord._current_datetime = lambda: self.horloge.maintenant
        coord._rafraichir_apres_action_utilisateur = AsyncMock()
        self.plateforme = "landroid_cloud"
        coord._mower_platform = lambda entity_id: self.plateforme
        self.rafraichissements = []
        coord._schedule_manual_refresh = lambda *a, **k: self.rafraichissements.append(1)
        self.arrosage = False
        coord._latest_full_snapshot = _quai()
        return coord

    def _cycle(self, coord, instantane, *, etat=None, position=None, apres=0.0):
        if apres:
            self.horloge.avancer(apres)
        if etat is not None:
            self.volet = types.SimpleNamespace(state=etat, attributes={"current_position": position})
        coord._latest_full_snapshot = instantane
        asyncio.run(coord._async_apply_mower_control(instantane))
        return instantane

    def _demander(self, coord, commande, **kw):
        return asyncio.run(coord.async_commande_tondeuse(commande, **kw))

    def _ordres(self) -> list[str]:
        return [f"{c.args[0]}.{c.args[1]}" for c in self.appel.await_args_list]

    def _donnees_de_l_appel(self, index: int = -1) -> dict:
        return self.appel.await_args_list[index].args[2]


class DepartSansVoletTests(_Base):
    avec_volet = False

    def test_la_demande_est_prise_puis_l_ordre_part_au_cycle(self) -> None:
        coord = self._coord("desactive")
        reponse = self._demander(coord, "demarrer")
        self.assertTrue(reponse["ok"], reponse)
        self.assertEqual(self._ordres(), [], "rien ne part avant le cycle : la séquence est jugée là")
        coord._rafraichir_apres_action_utilisateur.assert_awaited()
        instantane = self._cycle(coord, _quai())
        self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"])
        self.assertEqual(self._donnees_de_l_appel(), {"entity_id": TONDEUSE})
        self.assertIs(instantane["mower_manual_active"], True)
        self.assertEqual(instantane["mower_manual_command"], "demarrer")

    def test_le_depart_ne_depend_pas_du_mode_du_pilote(self) -> None:
        for mode in ("desactive", "observation", "actif"):
            with self.subTest(mode=mode):
                coord = self._coord(mode)
                self.assertTrue(self._demander(coord, "demarrer")["ok"])
                self._cycle(coord, _quai())
                self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"])

    def test_un_depart_n_est_pas_renvoye_au_cycle_suivant(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai())
        self._cycle(coord, _quai(), apres=0.5)
        self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"])

    def test_au_premier_cycle_apres_un_redemarrage_aucun_ordre_ne_part(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        coord._mower_control_bootstrap_complete = False
        self._cycle(coord, _quai())
        self.assertEqual(self._ordres(), [])
        self._cycle(coord, _quai(), apres=0.5)
        self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"], "au cycle suivant, la séquence reprend")

    def test_un_refus_est_rendu_a_la_page_en_clair_et_ne_cree_aucun_etat(self) -> None:
        coord = self._coord()
        coord._latest_full_snapshot = _dehors()
        reponse = self._demander(coord, "demarrer")
        self.assertFalse(reponse["ok"])
        self.assertIn("à sa base", reponse["message"])
        self.assertFalse(coord._manual_state().get("commande"))
        coord._rafraichir_apres_action_utilisateur.assert_not_awaited()

    def test_pas_de_donnees_pas_de_commande(self) -> None:
        coord = self._coord()
        coord._latest_full_snapshot = None
        reponse = self._demander(coord, "demarrer")
        self.assertFalse(reponse["ok"])
        self.assertIn("pas encore prêtes", reponse["message"])

    def test_un_arrosage_en_cours_refuse_le_depart(self) -> None:
        coord = self._coord()
        self.arrosage = True
        self.assertIn("arrosage", self._demander(coord, "demarrer")["message"])

    def test_un_arrosage_qui_demarre_pendant_la_sequence_l_abandonne(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        self.arrosage = True
        instantane = self._cycle(coord, _quai())
        self.assertEqual(self._ordres(), [])
        self.assertEqual(instantane["mower_manual_step"], "erreur")
        self.assertIs(instantane["mower_manual_active"], False)

    def test_la_bordure_envoie_le_service_de_la_tondeuse_avec_sa_duree(self) -> None:
        coord = self._coord()
        self.assertTrue(self._demander(coord, "bordure", duree_min=45)["ok"])
        self._cycle(coord, _quai())
        self.assertEqual(self._ordres(), ["landroid_cloud.ots"])
        self.assertEqual(self._donnees_de_l_appel(), {"entity_id": TONDEUSE, "boundary": True, "runtime": 45})

    def test_la_bordure_est_refusee_si_le_service_n_existe_pas(self) -> None:
        coord = self._coord()
        self.service_bordure = False
        reponse = self._demander(coord, "bordure")
        self.assertFalse(reponse["ok"])
        self.assertIn("bordure", reponse["message"])
        self.assertIs(self._cycle(coord, _quai())["mower_edgecut_available"], False)

    def test_un_ordre_refuse_par_home_assistant_arrete_la_sequence_sans_rien_marquer_comme_envoye(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        self.appel.side_effect = RuntimeError("tondeuse injoignable")
        instantane = self._cycle(coord, _quai())
        self.assertEqual(instantane["mower_manual_step"], "erreur")
        self.assertIn("refusée par Home Assistant", instantane["mower_manual_reason"])
        self.assertIn("tondeuse injoignable", instantane["mower_manual_reason"])
        self.assertIs(instantane["mower_manual_active"], False)
        self.assertFalse(coord._manual_state().get("envoye_a"))
        self.assertIsNotNone(instantane["mower_manual_ended_at"])

    def test_un_depart_sans_sortie_est_signale_apres_cinq_minutes(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai())
        instantane = self._cycle(coord, _quai(), apres=6.0)
        self.assertEqual(instantane["mower_manual_step"], "erreur")
        self.assertEqual(instantane["mower_manual_error"], "depart_non_confirme")


class DepartAvecVoletTests(_Base):
    def test_le_volet_s_ouvre_d_abord_et_le_depart_attend_la_confirmation_et_le_delai(self) -> None:
        coord = self._coord()
        self.assertTrue(self._demander(coord, "demarrer")["ok"])
        self._cycle(coord, _quai())
        self.assertEqual(self._ordres(), ["cover.open_cover"])
        self.assertEqual(self._donnees_de_l_appel(), {"entity_id": "cover.garage"})
        registre = coord._runtime_state["mower_control"]
        self.assertEqual(registre[gg.KEY_COMMAND], "open_cover")
        self.assertEqual(registre[gg.KEY_ATTEMPTS], 1)
        # Volet en route : toujours rien.
        self._cycle(coord, _quai(), apres=0.3, etat="opening", position=40)
        self.assertEqual(self._ordres(), ["cover.open_cover"])
        # Volet ouvert : on attend le délai de sécurité.
        instantane = self._cycle(coord, _quai(), apres=0.3, etat="open", position=100)
        self.assertEqual(self._ordres(), ["cover.open_cover"])
        self.assertEqual(instantane["mower_manual_step"], "attente_garage")
        self._cycle(coord, _quai(), apres=1.0)
        self.assertEqual(self._ordres(), ["cover.open_cover"], "1 min sur 2 : pas encore")
        self._cycle(coord, _quai(), apres=1.5)
        self.assertEqual(self._ordres(), ["cover.open_cover", "lawn_mower.start_mowing"])

    def test_le_pilote_n_ouvre_pas_le_volet_une_seconde_fois_pendant_le_depart_manuel(self) -> None:
        coord = self._coord("actif")
        self._demander(coord, "demarrer")
        # Conditions de départ AUTOMATIQUE réunies : le pilote voudrait lui aussi ouvrir.
        for minutes in (0.0, 0.5, 0.5):
            self._cycle(coord, _quai(gazon_permet_tonte=True, action_possible=True), apres=minutes)
        self.assertEqual(self._ordres().count("cover.open_cover"), 1)
        self.assertNotIn("lawn_mower.start_mowing", self._ordres())

    def test_un_volet_muet_abandonne_le_depart_sans_rien_envoyer(self) -> None:
        coord = self._coord()
        reponse = self._demander(coord, "demarrer")
        self.assertTrue(reponse["ok"])
        instantane = self._cycle(coord, _quai(), etat="unavailable", position=None)
        self.assertEqual(self._ordres(), [])
        self.assertEqual(instantane["mower_manual_step"], "erreur")

    def test_un_volet_muet_est_refuse_des_la_demande(self) -> None:
        coord = self._coord()
        self.volet = types.SimpleNamespace(state="unavailable", attributes={})
        reponse = self._demander(coord, "demarrer")
        self.assertFalse(reponse["ok"])
        self.assertIn("volet ne répond pas", reponse["message"])

    def test_un_volet_deja_ouvert_ne_recoit_aucun_ordre_mais_le_delai_court(self) -> None:
        coord = self._coord()
        self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai())
        self.assertEqual(self._ordres(), [])
        self._cycle(coord, _quai(), apres=2.5)
        self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"])

    def test_un_volet_bloque_apres_le_plafond_abandonne_le_depart(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        for minutes in (0.0, 2.5, 2.5):
            self._cycle(coord, _quai(), apres=minutes)
        self.assertEqual(self._ordres(), ["cover.open_cover"] * 3)
        instantane = self._cycle(coord, _quai(), apres=3.5)
        self.assertEqual(instantane["mower_manual_step"], "erreur")
        self.assertEqual(instantane["mower_manual_error"], "volet_bloque")
        self.assertNotIn("lawn_mower.start_mowing", self._ordres())
        self.assertEqual(self._ordres(), ["cover.open_cover"] * 3, "aucun quatrième ordre")

    def test_un_ordre_de_volet_manuel_ne_declenche_aucune_notification_du_pilote(self) -> None:
        """L'ouverture demandée depuis la page n'est pas une décision du pilote : elle n'est pas
        annoncée comme telle (`mower_control_last_action` reste celle du pilote)."""
        coord = self._coord()
        self._demander(coord, "demarrer")
        instantane = self._cycle(coord, _quai())
        self.assertIsNone(instantane["mower_control_last_action"])


class BordureLieeALaTondeuseChoisieTests(_Base):
    """Le service `landroid_cloud.ots` ne vaut que pour une tondeuse portée par cette intégration."""

    avec_volet = False

    def test_une_tondeuse_d_une_autre_marque_n_a_pas_de_bordure_meme_avec_une_landroid_installee(self) -> None:
        coord = self._coord()
        self.plateforme = "husqvarna_automower"   # le service existe (une Landroid est installée à côté)
        reponse = self._demander(coord, "bordure")
        self.assertFalse(reponse["ok"])
        self.assertIn("bordure", reponse["message"])
        self.assertIs(self._cycle(coord, _quai())["mower_edgecut_available"], False)
        self.assertTrue(self._demander(coord, "demarrer")["ok"], "le départ normal n'est pas touché")

    def test_une_plateforme_inconnue_vaut_indisponible(self) -> None:
        coord = self._coord()
        self.plateforme = None
        self.assertFalse(self._demander(coord, "bordure")["ok"])
        self.assertIs(self._cycle(coord, _quai())["mower_edgecut_available"], False)

    def test_sans_tondeuse_choisie_pas_de_bordure(self) -> None:
        coord = self._coord()
        self.assertIs(self._cycle(coord, _quai(tondeuse_source_entity=""))["mower_edgecut_available"], False)

    def test_la_landroid_choisie_avec_son_service_a_la_bordure(self) -> None:
        coord = self._coord()
        self.assertIs(self._cycle(coord, _quai())["mower_edgecut_available"], True)

    def test_la_plateforme_est_lue_pour_l_entite_choisie(self) -> None:
        coord = self._coord()
        vues = []
        coord._mower_platform = lambda entity_id: vues.append(entity_id) or "landroid_cloud"
        self._cycle(coord, _quai())
        self.assertIn(TONDEUSE, vues)

    def test_la_demande_juge_la_tondeuse_choisie_et_pas_une_autre(self) -> None:
        coord = self._coord()
        coord._mower_platform = lambda entity_id: "landroid_cloud" if entity_id == TONDEUSE else "autre_marque"
        self.assertTrue(self._demander(coord, "bordure")["ok"], "la tondeuse choisie est une Landroid")
        coord = self._coord()
        coord._mower_platform = lambda entity_id: "autre_marque" if entity_id == TONDEUSE else "landroid_cloud"
        reponse = self._demander(coord, "bordure")
        self.assertFalse(reponse["ok"], "la tondeuse choisie n'est PAS une Landroid, même si une autre l'est")
        self.assertIn("bordure", reponse["message"])

    def test_la_sequence_rejuge_la_tondeuse_choisie(self) -> None:
        """Acceptée, puis la plateforme n'est plus la bonne au cycle suivant : la bordure est abandonnée."""
        coord = self._coord()
        self.assertTrue(self._demander(coord, "bordure")["ok"])
        coord._mower_platform = lambda entity_id: "autre_marque" if entity_id == TONDEUSE else "landroid_cloud"
        instantane = self._cycle(coord, _quai())
        self.assertEqual(self._ordres(), [])
        self.assertEqual(instantane["mower_manual_step"], "erreur")

    def test_la_lecture_du_registre_est_protegee(self) -> None:
        """Vrai `_mower_platform` : le registre d'entités de Home Assistant, simulé ici."""
        import sys
        import types as _types
        from unittest.mock import patch
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.hass = object()
        er = _types.ModuleType("homeassistant.helpers.entity_registry")
        er.async_get = lambda hass: _types.SimpleNamespace(
            async_get=lambda eid: _types.SimpleNamespace(platform="landroid_cloud") if eid == TONDEUSE else None
        )
        helpers = _types.ModuleType("homeassistant.helpers")
        helpers.__path__ = []  # type: ignore[attr-defined]
        helpers.entity_registry = er  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"homeassistant.helpers": helpers, "homeassistant.helpers.entity_registry": er}):
            self.assertEqual(coord._mower_platform(TONDEUSE), "landroid_cloud")
            self.assertIsNone(coord._mower_platform("lawn_mower.inconnue"))
        er.async_get = lambda hass: (_ for _ in ()).throw(RuntimeError("registre indisponible"))
        with patch.dict(sys.modules, {"homeassistant.helpers": helpers, "homeassistant.helpers.entity_registry": er}):
            self.assertIsNone(coord._mower_platform(TONDEUSE))


class VoletRouvertPendantUneSortieManuelleTests(_Base):
    """⚠️ La règle « pas de volet fermé devant une tondeuse dehors » tient dans les TROIS modes du pilote."""

    def _sortie_en_cours(self, mode):
        coord = self._coord(mode)
        self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})
        self.assertTrue(self._demander(coord, "demarrer")["ok"])
        self._cycle(coord, _quai(), apres=0.5)          # volet ouvert : délai de sécurité
        self._cycle(coord, _quai(), apres=2.5)          # départ envoyé
        self._cycle(coord, _dehors(), apres=1.0)        # elle sort
        self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"])
        return coord

    def test_le_volet_refermé_en_route_est_rouvert_dans_chaque_mode(self) -> None:
        for mode in ("desactive", "observation", "actif"):
            with self.subTest(mode=mode):
                coord = self._sortie_en_cours(mode)
                instantane = self._cycle(coord, _dehors(), apres=2.0, etat="closed", position=0)
                self.assertEqual(self._ordres().count("cover.open_cover"), 1, f"{mode} : un seul ordre")
                self.assertEqual(self._ordres()[-1], "cover.open_cover")
                self.assertEqual(self._donnees_de_l_appel(), {"entity_id": "cover.garage"})
                self.assertIs(instantane["mower_manual_active"], True, "la commande continue")
                # Cycle suivant, volet pas encore bougé : l'ordre n'est pas doublé (registre partagé avec le pilote).
                self._cycle(coord, _dehors(), apres=0.5)
                self.assertEqual(self._ordres().count("cover.open_cover"), 1, f"{mode} : pas de doublon")

    def test_le_volet_rouvert_la_serie_se_ferme(self) -> None:
        coord = self._sortie_en_cours("observation")
        self._cycle(coord, _dehors(), apres=2.0, etat="closed", position=0)
        self._cycle(coord, _dehors(), apres=0.3, etat="open", position=100)
        self.assertIsNone(coord._runtime_state["mower_control"].get(gg.KEY_COMMAND))
        self._cycle(coord, _dehors(), apres=3.0)
        self.assertEqual(self._ordres().count("cover.open_cover"), 1)

    def test_un_volet_qui_refuse_de_s_ouvrir_declenche_l_alerte_quel_que_soit_le_mode(self) -> None:
        for mode in ("desactive", "observation"):
            with self.subTest(mode=mode):
                coord = self._sortie_en_cours(mode)
                self._cycle(coord, _dehors(), apres=2.0, etat="closed", position=0)
                self._cycle(coord, _dehors(), apres=2.5)
                self._cycle(coord, _dehors(), apres=2.5)
                instantane = self._cycle(coord, _dehors(), apres=3.5)
                self.assertEqual(self._ordres().count("cover.open_cover"), 3, "au plus trois tentatives")
                self.assertEqual(instantane["mower_garage_alert"], gg.ALERT_STUCK)
                self.assertIs(instantane["mower_manual_active"], True, "la tondeuse est dehors : on ne l'abandonne pas")


class PauseFaiteAilleursCoordinateurTests(_Base):
    avec_volet = False

    def test_la_reprise_est_acceptee_pour_une_machine_mise_en_pause_depuis_l_appli_du_constructeur(self) -> None:
        coord = self._coord()
        coord._latest_full_snapshot = _dehors(mower_operation_state="paused", mower_job_completion_state="en_cours")
        reponse = self._demander(coord, "reprendre")
        self.assertTrue(reponse["ok"], reponse)
        self._cycle(coord, coord._latest_full_snapshot)
        self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"])

    def test_une_tondeuse_qui_tond_n_a_rien_a_reprendre(self) -> None:
        coord = self._coord()
        coord._latest_full_snapshot = _dehors()
        self.assertFalse(self._demander(coord, "reprendre")["ok"])


class PiloteEffaceTests(_Base):
    def test_le_pilote_ne_rappelle_pas_une_tondeuse_en_sortie_manuelle(self) -> None:
        """Le gazon interdit la tonte → le pilote la rappellerait. Pas pendant une sortie manuelle."""
        coord = self._coord("actif")
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai(), etat="open", position=100)
        self._cycle(coord, _quai(), apres=2.5)
        self.assertIn("lawn_mower.start_mowing", self._ordres())
        instantane = self._cycle(coord, _dehors(), apres=0.5)
        self.assertNotIn("lawn_mower.dock", self._ordres())
        self.assertEqual(instantane["mower_control_state"], "manuel")
        self.assertIs(instantane["mower_manual_active"], True)

    def test_annuler_rend_la_main_au_pilote_qui_peut_alors_rappeler(self) -> None:
        coord = self._coord("actif")
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai(), etat="open", position=100)
        self._cycle(coord, _quai(), apres=2.5)
        self._cycle(coord, _dehors(), apres=0.5)
        reponse = self._demander(coord, "annuler")
        self.assertTrue(reponse["ok"])
        instantane = self._cycle(coord, _dehors(), apres=0.5)
        self.assertIs(instantane["mower_manual_active"], False)
        self.assertEqual(self._ordres()[-1], "lawn_mower.dock")

    def test_le_reglage_du_pilotage_n_est_jamais_modifie(self) -> None:
        coord = self._coord("actif")
        configuration = {"pilotage_tondeuse": "actif"}
        coord._get_conf = lambda cle: configuration.get(cle)
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai())
        self.assertEqual(configuration, {"pilotage_tondeuse": "actif"})

    def test_le_pilote_ne_ferme_pas_le_volet_pendant_l_attente_d_un_depart_manuel(self) -> None:
        coord = self._coord("actif")
        self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})
        self._cycle(coord, _quai(), apres=0.0)
        self._demander(coord, "demarrer")
        for minutes in (0.5, 0.5):
            self._cycle(coord, _quai(), apres=minutes)
        self.assertNotIn("cover.close_cover", self._ordres())

    def test_la_regle_volet_ferme_devant_une_tondeuse_dehors_reste_active(self) -> None:
        """La seule règle qui garde la priorité : une tondeuse dehors ne trouve pas son volet fermé."""
        coord = self._coord("actif")
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai(), etat="open", position=100)
        self._cycle(coord, _quai(), apres=2.5)
        # Le volet se referme tout seul alors que la tondeuse travaille.
        instantane = self._cycle(coord, _dehors(), apres=3.0, etat="closed", position=0)
        self.assertIn("cover.open_cover", self._ordres()[1:])
        self.assertEqual(instantane["mower_control_pending_action"], None)

    def test_une_tondeuse_partie_n_autorise_pas_une_fermeture_immediate_a_son_retour(self) -> None:
        """⚠️ Le vieux « rentrée depuis » d'avant le départ ne doit pas survivre : au retour, le délai
        de sécurité repart de la vraie rentrée."""
        coord = self._coord("actif")
        self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})
        self._cycle(coord, _quai())                                   # rentrée vue : docked_since posé
        self.assertIsNotNone(coord._runtime_state["mower_control"].get("docked_since"))
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai(), apres=0.5)                        # volet ouvert : délai de sécurité
        self._cycle(coord, _quai(), apres=2.5)                        # le délai passe : départ
        self.assertIn("lawn_mower.start_mowing", self._ordres())
        self._cycle(coord, _dehors(), apres=1.0)                      # elle sort
        self._cycle(coord, _dehors(), apres=60.0)                     # elle travaille depuis une heure
        self.assertIs(coord._runtime_state["mower_manual"]["etape"], "dehors")
        self.assertIsNone(coord._runtime_state["mower_control"].get("docked_since"))

    def test_la_commande_expiree_rend_la_main_au_pilote(self) -> None:
        coord = self._coord("actif")
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai(), etat="open", position=100)
        self._cycle(coord, _quai(), apres=2.5)
        self._cycle(coord, _dehors(), apres=0.5)
        instantane = self._cycle(coord, _dehors(), apres=mc.MANUAL_MAX_OUTING_MINUTES + 1)
        self.assertEqual(instantane["mower_manual_step"], "expire")
        self.assertIs(instantane["mower_manual_active"], False)

    def test_la_fin_du_travail_et_la_rentree_rendent_la_main_au_pilote(self) -> None:
        coord = self._coord("actif")
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai(), etat="open", position=100)
        self._cycle(coord, _quai(), apres=2.5)
        self._cycle(coord, _dehors(), apres=1.0)
        instantane = self._cycle(coord, _quai(mower_job_completion_state="termine"), apres=60.0)
        self.assertEqual(instantane["mower_manual_step"], "termine")
        self.assertIs(instantane["mower_manual_active"], False)


class RetourPauseReprendreTests(_Base):
    def test_retour_sans_volet_envoie_le_retour_et_suspend_les_departs(self) -> None:
        coord = self._coord("actif", volet=False)
        coord._latest_full_snapshot = _dehors()
        self.assertTrue(self._demander(coord, "retour")["ok"])
        instantane = self._cycle(coord, _dehors())
        self.assertEqual(self._ordres(), ["lawn_mower.dock"])
        self.assertIs(instantane["mower_manual_suspension_active"], True)
        self.assertIsNotNone(instantane["mower_manual_suspension_until"])

    def test_retour_avec_volet_ferme_ouvre_d_abord(self) -> None:
        coord = self._coord("actif")
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "retour")
        instantane = self._cycle(coord, _dehors())
        self.assertEqual(self._ordres(), ["cover.open_cover"])
        self.assertIs(instantane["mower_manual_suspension_active"], False, "pas de suspension avant l'ordre")
        self._cycle(coord, _dehors(), apres=0.3, etat="open", position=100)
        self.assertEqual(self._ordres(), ["cover.open_cover", "lawn_mower.dock"])

    def test_apres_un_retour_manuel_le_pilote_ne_renvoie_pas_la_tondeuse(self) -> None:
        """⚠️ La raison d'être de la suspension : tondeuse à quai, conditions idéales, pilote actif."""
        coord = self._coord("actif", volet=False)
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "retour")
        self._cycle(coord, _dehors())
        ideal = dict(gazon_permet_tonte=True, action_possible=True)
        instantane = self._cycle(coord, _quai(**ideal), apres=3.0)
        self.assertEqual(instantane["mower_manual_step"], "termine")
        instantane = self._cycle(coord, _quai(**ideal), apres=3.0)
        self.assertEqual(instantane["mower_control_state"], "depart_suspendu")
        self.assertNotIn("lawn_mower.start_mowing", self._ordres())

    def test_la_suspension_prend_fin_et_le_pilote_peut_repartir(self) -> None:
        coord = self._coord("actif", volet=False)
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "retour")
        self._cycle(coord, _dehors())
        ideal = dict(gazon_permet_tonte=True, action_possible=True)
        self._cycle(coord, _quai(**ideal), apres=3.0)
        self._cycle(coord, _quai(**ideal), apres=mc.MANUAL_HOLD_AFTER_RETURN_MINUTES + 5)
        self.assertEqual(self._ordres()[-1], "lawn_mower.start_mowing")

    def test_apres_un_retour_manuel_le_volet_est_quand_meme_referme(self) -> None:
        """La suspension ne vise que les DÉPARTS : la fermeture suit la rentrée comme d'habitude."""
        coord = self._coord("actif")
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "retour")
        self._cycle(coord, _dehors(), etat="open", position=100)
        self._cycle(coord, _quai(), apres=2.0)                       # rentrée : commande terminée
        self._cycle(coord, _quai(), apres=1.0)                       # signal de quai vu
        self._cycle(coord, _quai(), apres=3.0)                       # délai de sécurité écoulé
        self.assertEqual(self._ordres()[-1], "cover.close_cover")

    def test_un_depart_explicite_leve_la_suspension_d_un_retour(self) -> None:
        coord = self._coord("desactive", volet=False)
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "retour")
        self._cycle(coord, _dehors())
        self._cycle(coord, _quai(), apres=3.0)
        self.assertTrue(self._demander(coord, "demarrer")["ok"])
        self.assertIsNone(coord._manual_state()["suspension_jusqu_a"])

    def test_la_pause_envoie_un_seul_ordre_et_garde_le_mode_manuel(self) -> None:
        coord = self._coord("actif", volet=False)
        coord._latest_full_snapshot = _dehors()
        self.assertTrue(self._demander(coord, "pause")["ok"])
        self._cycle(coord, _dehors(gazon_permet_tonte=False))
        self._cycle(coord, _dehors(gazon_permet_tonte=False), apres=2.0)
        self.assertEqual(self._ordres(), ["lawn_mower.pause"])
        instantane = self._cycle(coord, _dehors(gazon_permet_tonte=False), apres=2.0)
        self.assertEqual(instantane["mower_control_state"], "manuel", "le pilote ne défait pas la pause")

    def test_reprendre_apres_une_pause_envoie_le_depart_sans_toucher_au_volet(self) -> None:
        coord = self._coord("actif")
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "pause")
        self._cycle(coord, _dehors(), etat="open", position=100)
        self.assertTrue(self._demander(coord, "reprendre")["ok"])
        self._cycle(coord, _dehors(), apres=1.0)
        self.assertEqual(self._ordres(), ["lawn_mower.pause", "lawn_mower.start_mowing"])

    def test_retour_en_pleine_sortie_manuelle_passe_devant_la_sortie(self) -> None:
        coord = self._coord("actif", volet=False)
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai())
        self._cycle(coord, _dehors(), apres=1.0)
        self.assertTrue(self._demander(coord, "retour")["ok"])
        self._cycle(coord, _dehors(), apres=0.5)
        self.assertEqual(self._ordres(), ["lawn_mower.start_mowing", "lawn_mower.dock"])

    def test_un_retour_refuse_par_home_assistant_ne_suspend_rien(self) -> None:
        coord = self._coord("actif", volet=False)
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "retour")
        self.appel.side_effect = RuntimeError("injoignable")
        instantane = self._cycle(coord, _dehors())
        self.assertEqual(instantane["mower_manual_step"], "erreur")
        self.assertIs(instantane["mower_manual_suspension_active"], False)

    def test_annuler_sans_commande_en_cours_le_dit(self) -> None:
        coord = self._coord()
        reponse = self._demander(coord, "annuler")
        self.assertFalse(reponse["ok"])
        self.assertIn("Aucune commande", reponse["message"])

    def test_annuler_leve_aussi_la_suspension(self) -> None:
        coord = self._coord("actif", volet=False)
        coord._latest_full_snapshot = _dehors()
        self._demander(coord, "retour")
        self._cycle(coord, _dehors())
        self.assertTrue(self._demander(coord, "annuler")["ok"])
        self.assertIsNone(coord._manual_state()["suspension_jusqu_a"])
        self.assertIs(self._cycle(coord, _dehors(), apres=0.5)["mower_manual_suspension_active"], False)


class RejugementPlanifieTests(_Base):
    """Une commande en cours est rejugée vite : l'intervalle normal (2 min) ferait traîner un départ."""

    def test_une_commande_en_cours_planifie_un_nouveau_cycle(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai())
        self.assertTrue(self.rafraichissements)

    def test_une_commande_terminee_ne_planifie_plus_rien(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        self.arrosage = True                       # la séquence est abandonnée à ce cycle
        self._cycle(coord, _quai())
        self.assertEqual(self.rafraichissements, [])

    def test_sans_commande_aucun_cycle_supplementaire(self) -> None:
        coord = self._coord()
        self._cycle(coord, _quai())
        self.assertEqual(self.rafraichissements, [])

    def test_la_planification_reelle_ne_se_double_pas_et_s_annule(self) -> None:
        from unittest.mock import MagicMock, patch
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        coord.hass = object()
        coord.async_request_refresh = AsyncMock()
        desabonnement = MagicMock()
        with patch.object(coordinator_mod, "async_call_later", return_value=desabonnement) as planifier:
            coord._schedule_manual_refresh()
            coord._schedule_manual_refresh()
            self.assertEqual(planifier.call_count, 1, "un seul minuteur à la fois")
            rappel = planifier.call_args.args[2]
            asyncio.run(rappel(None))
            coord.async_request_refresh.assert_awaited_once()
            self.assertIsNone(coord._unsub_manual_refresh, "le minuteur échu est oublié")
            coord._schedule_manual_refresh()
            self.assertEqual(planifier.call_count, 2, "un nouveau minuteur est possible après l'échéance")
            coord._cancel_manual_refresh()
            desabonnement.assert_called_once()
            self.assertIsNone(coord._unsub_manual_refresh)

    def test_l_arret_de_l_integration_annule_le_minuteur(self) -> None:
        import pathlib
        source = (pathlib.Path(coordinator_mod.__file__).parent / "coordinator.py").read_text(encoding="utf-8")
        arret = source.split("async def async_shutdown(self)")[1].split("\n    def ")[0]
        self.assertIn("self._cancel_manual_refresh()", arret)


class PublicationEtPersistanceTests(_Base):
    def test_les_attributs_atteignent_le_capteur_et_les_diagnostics(self) -> None:
        import pathlib
        racine = pathlib.Path(coordinator_mod.__file__).parent
        publies = [cle for cle in self._cycle(self._coord(), _quai()) if cle.startswith("mower_manual_")]
        publies.append("mower_edgecut_available")
        self.assertGreaterEqual(len(publies), 10)
        for fichier in ("sensor.py", "diagnostics.py"):
            source = (racine / fichier).read_text(encoding="utf-8")
            for cle in publies:
                self.assertIn(f'"{cle}"', source, f"{cle} n'est pas publié par {fichier}")
        source = (racine / "coordinator.py").read_text(encoding="utf-8")
        liste = source.split("_COORDINATOR_SNAPSHOT_KEYS: tuple[str, ...] = (")[1].split("\n)\n")[0]
        for cle in publies:
            self.assertIn(f'"{cle}"', liste, f"{cle} n'est pas dans la liste du coordinateur")

    def test_l_etat_manuel_survit_a_un_redemarrage(self) -> None:
        coord = self._coord()
        self._demander(coord, "demarrer")
        self._cycle(coord, _quai())
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        serialise = coord._serialized_runtime_state()
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(relu._runtime_state["mower_manual"], coord._runtime_state["mower_manual"])
        self.assertEqual(relu._runtime_state["mower_manual"]["commande"], "demarrer")

    def test_le_volet_est_suivi_pour_que_son_changement_declenche_un_cycle(self) -> None:
        coord = self._coord()
        coord._resolve_mower_selection = lambda: {}
        coord._get_conf = lambda cle: "cover.garage" if cle == "entite_volet_garage_tondeuse" else None
        self.assertIn("cover.garage", coord._source_entity_ids())

    def test_le_service_ws_est_reserve_aux_administrateurs(self) -> None:
        import pathlib
        source = (pathlib.Path(coordinator_mod.__file__).parent / "panneau.py").read_text(encoding="utf-8")
        enregistrement = source.split("commande_tondeuse = websocket_api.require_admin(")[1][:600]
        self.assertIn("WS_COMMANDE_TONDEUSE", enregistrement)


if __name__ == "__main__":
    unittest.main()
