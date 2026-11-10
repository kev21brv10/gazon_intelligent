"""Garde-fous du volet de garage : série d'ordres, plafond, reprise, alerte, ouverture à la main.

Un volet qui accepte un ordre sans bouger était relancé toutes les 10 minutes, sans plafond et sans
alerte ; un volet ouvert à la main, tondeuse à quai, était refermé après le délai de rentrée. Les
fonctions pures sont testées ici ; leur branchement dans le pilote et le coordinateur plus bas.
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
gg = importlib.import_module("custom_components.gazon_intelligent.garage_guard")

NOW = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)


def _il_y_a(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def _serie(action="open_cover", *, depuis=1.0, tentatives=1, debut=None, **extra):
    """Un registre avec une série en cours : dernier ordre il y a `depuis` minutes."""
    return {
        gg.KEY_COMMAND: action,
        gg.KEY_COMMAND_AT: _il_y_a(depuis),
        gg.KEY_ATTEMPTS: tentatives,
        gg.KEY_SERIES_START: _il_y_a(debut if debut is not None else depuis),
        **extra,
    }


class PorteDesOrdresTests(unittest.TestCase):
    def test_sans_serie_l_ordre_part(self) -> None:
        self.assertIsNone(gg.command_gate("open_cover", {}, {}, NOW))

    def test_un_ordre_qui_n_est_pas_un_ordre_de_volet_n_est_jamais_retenu(self) -> None:
        for action in ("start_mowing", "dock", None):
            with self.subTest(action=action):
                self.assertIsNone(gg.command_gate(action, _serie(tentatives=9), {}, NOW))

    def test_dans_le_delai_de_reprise_l_ordre_est_retenu_avec_le_temps_restant(self) -> None:
        retenu = gg.command_gate("open_cover", _serie(depuis=0.5), {}, NOW)
        self.assertEqual(retenu["state"], "temporisation")
        self.assertIn("nouvelle tentative dans 2 min", retenu["reason"])

    def test_apres_le_delai_de_reprise_l_ordre_est_renvoye(self) -> None:
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=2.0), {}, NOW))
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=2.5, tentatives=2), {}, NOW))

    def test_le_delai_de_reprise_est_celui_du_volet_pas_les_10_minutes_communes(self) -> None:
        """⚠️ Avant : un ordre raté retardait le départ de 10 min. Ici 2 min par défaut."""
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=3.0), {"tondeuse_pilotage_delai_commandes": 10}, NOW))

    def test_le_delai_de_reprise_est_reglable(self) -> None:
        reglages = {"tondeuse_garage_delai_reprise": 5}
        self.assertEqual(gg.command_gate("open_cover", _serie(depuis=4.0), reglages, NOW)["state"], "temporisation")
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=5.0), reglages, NOW))

    def test_au_plafond_de_tentatives_le_volet_est_bloque_meme_apres_le_delai(self) -> None:
        bloque = gg.command_gate("open_cover", _serie(depuis=10.0, tentatives=3), {}, NOW)
        self.assertEqual(bloque["state"], "volet_bloque")
        self.assertIn("après 3 tentatives", bloque["reason"])
        self.assertIn("intervention manuelle", bloque["reason"])

    def test_le_plafond_est_reglable(self) -> None:
        reglages = {"tondeuse_garage_tentatives_max": 5}
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=10.0, tentatives=3), reglages, NOW))
        self.assertEqual(gg.command_gate("open_cover", _serie(depuis=10.0, tentatives=5), reglages, NOW)["state"], "volet_bloque")

    def test_un_plafond_nul_ou_negatif_laisse_au_moins_une_tentative(self) -> None:
        reglages = {"tondeuse_garage_tentatives_max": 0}
        self.assertEqual(gg.command_gate("open_cover", _serie(depuis=10.0, tentatives=1), reglages, NOW)["state"], "volet_bloque")

    def test_l_autre_sens_commence_une_nouvelle_serie(self) -> None:
        self.assertIsNone(gg.command_gate("close_cover", _serie("open_cover", depuis=0.1, tentatives=3), {}, NOW))

    def test_une_serie_non_epuisee_de_plus_d_une_heure_est_oubliee(self) -> None:
        """Deux pannes différentes, pas une suite d'échecs : on repart de zéro."""
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=61.0, tentatives=2), {}, NOW))

    def test_une_serie_epuisee_tient_bien_au_dela_d_une_heure(self) -> None:
        """⚠️ DÉCISION DU PROPRIÉTAIRE (« s'arrêter jusqu'à réparation ») : volet bloqué, le pilote ne
        renvoie rien tant que le volet n'a pas atteint sa position. L'oubli au bout d'une heure
        relançait trois ordres, effaçait l'alerte puis la renvoyait à chaque série — contre-exemple
        relevé en revue de l'étape 2."""
        for minutes in (61.0, 120.0, 600.0, 1439.0):
            with self.subTest(minutes=minutes):
                bloque = gg.command_gate("open_cover", _serie(depuis=minutes, tentatives=3), {}, NOW)
                self.assertEqual(bloque["state"], "volet_bloque")

    def test_une_serie_epuisee_est_oubliee_apres_24_heures(self) -> None:
        """Un volet réparé sans que personne ne l'ait manœuvré ne reste pas bloqué indéfiniment."""
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=25 * 60.0, tentatives=3), {}, NOW))

    def test_le_plafond_reglable_decide_de_l_epuisement(self) -> None:
        reglages = {"tondeuse_garage_tentatives_max": 5}
        self.assertIsNone(gg.command_gate("open_cover", _serie(depuis=90.0, tentatives=3), reglages, NOW))
        self.assertEqual(gg.command_gate("open_cover", _serie(depuis=90.0, tentatives=5), reglages, NOW)["state"], "volet_bloque")

    def test_un_instant_abime_ne_bloque_jamais_le_volet_pour_toujours(self) -> None:
        for valeur in ("pas une date", "", None, 12):
            with self.subTest(valeur=valeur):
                registre = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: valeur, gg.KEY_ATTEMPTS: 9}
                self.assertIsNone(gg.command_gate("open_cover", registre, {}, NOW))


class RegistreApresUnOrdreTests(unittest.TestCase):
    def test_le_premier_ordre_ouvre_la_serie(self) -> None:
        maj = gg.after_command({}, "open_cover", NOW.isoformat(), NOW)
        self.assertEqual(maj[gg.KEY_COMMAND], "open_cover")
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 1)
        self.assertEqual(maj[gg.KEY_SERIES_START], NOW.isoformat())
        self.assertIs(maj[gg.KEY_OPENED_BY_PILOT], True)

    def test_un_ordre_de_plus_dans_la_serie_compte_et_garde_le_debut(self) -> None:
        registre = _serie(depuis=2.5, tentatives=1, debut=2.5)
        maj = gg.after_command(registre, "open_cover", NOW.isoformat(), NOW)
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 2)
        self.assertEqual(maj[gg.KEY_SERIES_START], registre[gg.KEY_SERIES_START])

    def test_l_autre_sens_recommence_a_un(self) -> None:
        maj = gg.after_command(_serie("open_cover", tentatives=3), "close_cover", NOW.isoformat(), NOW)
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 1)
        self.assertEqual(maj[gg.KEY_SERIES_START], NOW.isoformat())
        self.assertNotIn(gg.KEY_OPENED_BY_PILOT, maj, "une fermeture n'efface pas à elle seule le fait d'avoir ouvert")

    def test_une_serie_non_epuisee_oubliee_recommence_a_un(self) -> None:
        maj = gg.after_command(_serie(depuis=90.0, tentatives=2), "open_cover", NOW.isoformat(), NOW)
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 1)

    def test_une_serie_epuisee_oubliee_apres_24_heures_recommence_a_un(self) -> None:
        maj = gg.after_command(_serie(depuis=25 * 60.0, tentatives=3), "open_cover", NOW.isoformat(), NOW)
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 1)

    def test_un_ordre_qui_n_est_pas_un_ordre_de_volet_ne_change_rien(self) -> None:
        self.assertEqual(gg.after_command({}, "start_mowing", NOW.isoformat(), NOW), {})


class RemiseAZeroTests(unittest.TestCase):
    def test_l_ouverture_atteinte_ferme_la_serie(self) -> None:
        maj = gg.reset_updates(_serie("open_cover"), "open", 100, NOW)
        self.assertIsNone(maj[gg.KEY_COMMAND])
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 0)

    def test_un_volet_ouvert_a_moitie_n_a_pas_atteint_la_cible(self) -> None:
        self.assertNotIn(gg.KEY_COMMAND, gg.reset_updates(_serie("open_cover"), "open", 50, NOW))

    def test_l_ouverture_sans_position_publiee_se_juge_sur_l_etat(self) -> None:
        self.assertIsNone(gg.reset_updates(_serie("open_cover"), "open", None, NOW)[gg.KEY_COMMAND])

    def test_la_fermeture_atteinte_ferme_la_serie(self) -> None:
        self.assertIsNone(gg.reset_updates(_serie("close_cover"), "closed", 0, NOW)[gg.KEY_COMMAND])

    def test_une_serie_non_epuisee_oubliee_est_effacee_meme_sans_cible_atteinte(self) -> None:
        maj = gg.reset_updates(_serie("open_cover", depuis=75.0, tentatives=2), "closed", 0, NOW)
        self.assertIsNone(maj[gg.KEY_COMMAND])
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 0)

    def test_une_serie_epuisee_n_est_pas_effacee_apres_une_heure(self) -> None:
        """⚠️ Le contre-exemple de la revue : après 61 min, trois tentatives restaient mémorisées ET
        étaient remises à zéro. Désormais la série tient (le pilote reste arrêté, l'alerte reste)."""
        registre = _serie("open_cover", depuis=61.0, tentatives=3)
        self.assertNotIn(gg.KEY_COMMAND, gg.reset_updates(registre, "closed", 0, NOW))
        self.assertNotIn(gg.KEY_ATTEMPTS, gg.reset_updates(registre, "closed", 0, NOW))

    def test_une_serie_epuisee_est_effacee_des_que_le_volet_atteint_sa_cible(self) -> None:
        """La réparation : le volet s'ouvre (même à la main) → le pilote repart normalement."""
        registre = _serie("open_cover", depuis=300.0, tentatives=3)
        maj = gg.reset_updates(registre, "open", 100, NOW)
        self.assertIsNone(maj[gg.KEY_COMMAND])
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 0)

    def test_une_serie_epuisee_est_effacee_apres_24_heures(self) -> None:
        maj = gg.reset_updates(_serie("open_cover", depuis=25 * 60.0, tentatives=3), "closed", 0, NOW)
        self.assertIsNone(maj[gg.KEY_COMMAND])

    def test_volet_ferme_efface_le_fait_de_l_avoir_ouvert(self) -> None:
        maj = gg.reset_updates({gg.KEY_OPENED_BY_PILOT: True}, "closed", 0, NOW)
        self.assertIs(maj[gg.KEY_OPENED_BY_PILOT], False)

    def test_un_volet_vu_ferme_sans_trace_est_marque_non_ouvert_par_le_pilote(self) -> None:
        """C'est ce « faux » explicite qui désigne ensuite une ouverture à la main."""
        self.assertIs(gg.reset_updates({}, "closed", 0, NOW)[gg.KEY_OPENED_BY_PILOT], False)

    def test_un_volet_deja_marque_non_ouvert_n_est_pas_remarque(self) -> None:
        self.assertNotIn(gg.KEY_OPENED_BY_PILOT, gg.reset_updates({gg.KEY_OPENED_BY_PILOT: False}, "closed", 0, NOW))

    def test_le_volet_vu_ouvert_note_depuis_quand(self) -> None:
        for etat in ("open", "opening"):
            with self.subTest(etat=etat):
                self.assertEqual(gg.reset_updates({}, etat, 100, NOW)[gg.KEY_OPEN_SINCE], NOW.isoformat())

    def test_le_depuis_quand_n_est_pas_reecrit_a_chaque_cycle(self) -> None:
        registre = {gg.KEY_OPEN_SINCE: _il_y_a(45)}
        self.assertNotIn(gg.KEY_OPEN_SINCE, gg.reset_updates(registre, "open", 100, NOW))

    def test_le_volet_ferme_efface_le_depuis_quand(self) -> None:
        self.assertIsNone(gg.reset_updates({gg.KEY_OPEN_SINCE: _il_y_a(45)}, "closed", 0, NOW)[gg.KEY_OPEN_SINCE])

    def test_l_ordre_d_ouverture_vient_de_partir_le_volet_n_a_pas_bouge_on_garde_le_fait(self) -> None:
        """⚠️ Sinon l'ouverture que NOUS venons de demander serait prise pour une ouverture à la main."""
        registre = _serie("open_cover", depuis=0.2, **{gg.KEY_OPENED_BY_PILOT: True})
        self.assertNotIn(gg.KEY_OPENED_BY_PILOT, gg.reset_updates(registre, "closed", 0, NOW))

    def test_un_volet_ouvert_garde_le_fait_de_l_avoir_ouvert(self) -> None:
        maj = gg.reset_updates({gg.KEY_OPENED_BY_PILOT: True, gg.KEY_OPEN_SINCE: _il_y_a(3)}, "open", 100, NOW)
        self.assertEqual(maj, {})

    def test_un_volet_indisponible_est_note_depuis_quand_puis_efface_au_retour(self) -> None:
        for etat in ("unavailable", "unknown", ""):
            with self.subTest(etat=etat):
                self.assertEqual(gg.reset_updates({}, etat, None, NOW)[gg.KEY_UNAVAILABLE_SINCE], NOW.isoformat())
        deja = {gg.KEY_UNAVAILABLE_SINCE: _il_y_a(3)}
        self.assertNotIn(gg.KEY_UNAVAILABLE_SINCE, gg.reset_updates(deja, "unavailable", None, NOW))
        self.assertIsNone(gg.reset_updates(deja, "closed", 0, NOW)[gg.KEY_UNAVAILABLE_SINCE])

    def test_rien_a_effacer(self) -> None:
        registre = {gg.KEY_OPENED_BY_PILOT: False}
        self.assertEqual(gg.reset_updates(registre, "closed", 0, NOW), {})

    def test_la_position_minimale_d_ouverture_est_celle_du_reglage(self) -> None:
        self.assertNotIn(gg.KEY_COMMAND, gg.reset_updates(_serie("open_cover"), "open", 80, NOW))
        self.assertIsNone(gg.reset_updates(_serie("open_cover"), "open", 80, NOW, min_open_position=75)[gg.KEY_COMMAND])


class DelaiDeFermetureTests(unittest.TestCase):
    def test_ouvert_par_le_pilote_le_delai_est_celui_de_la_rentree(self) -> None:
        self.assertEqual(gg.close_delay({"tondeuse_garage_delai_fermeture": 1}, {gg.KEY_OPENED_BY_PILOT: True}), (1.0, False))

    def test_ouvert_a_la_main_le_delai_est_plus_long(self) -> None:
        self.assertEqual(gg.close_delay({"tondeuse_garage_delai_fermeture": 1}, {gg.KEY_OPENED_BY_PILOT: False}), (30.0, True))

    def test_origine_inconnue_le_delai_reste_celui_de_la_rentree(self) -> None:
        """Jamais vu fermé (état d'avant cette version) : comportement inchangé, pas de changement en silence."""
        self.assertEqual(gg.close_delay({"tondeuse_garage_delai_fermeture": 1}, {}), (1.0, False))

    def test_le_delai_manuel_est_reglable(self) -> None:
        reglages = {"tondeuse_garage_delai_fermeture": 1, "tondeuse_garage_delai_fermeture_manuel": 90}
        self.assertEqual(gg.close_delay(reglages, {gg.KEY_OPENED_BY_PILOT: False}), (90.0, True))

    def test_le_delai_manuel_n_est_jamais_plus_court_que_le_delai_normal(self) -> None:
        reglages = {"tondeuse_garage_delai_fermeture": 15, "tondeuse_garage_delai_fermeture_manuel": 5}
        self.assertEqual(gg.close_delay(reglages, {gg.KEY_OPENED_BY_PILOT: False}), (15.0, True))

    def test_valeurs_absentes_ou_illisibles_defauts(self) -> None:
        self.assertEqual(gg.close_delay({}, {gg.KEY_OPENED_BY_PILOT: True}), (2.0, False))
        self.assertEqual(gg.close_delay({"tondeuse_garage_delai_fermeture": "x", "tondeuse_garage_delai_fermeture_manuel": None}, {gg.KEY_OPENED_BY_PILOT: False})[0], 30.0)


class EtatNotifiableTests(unittest.TestCase):
    """Seul ce que le PILOTE a ordonné, il y a peu, est annoncé au téléphone."""

    def test_l_ouverture_ordonnee_par_le_pilote_est_annoncee(self) -> None:
        self.assertEqual(gg.notifiable_state("open", "open_cover", _il_y_a(1), NOW), "open")
        self.assertEqual(gg.notifiable_state("opening", "open_cover", _il_y_a(0.1), NOW), "opening")

    def test_la_fermeture_ordonnee_par_le_pilote_est_annoncee(self) -> None:
        self.assertEqual(gg.notifiable_state("closed", "close_cover", _il_y_a(2), NOW), "closed")

    def test_un_changement_a_la_main_n_est_pas_annonce(self) -> None:
        """Le pilote a ouvert il y a 20 min ; vous fermez à la main : état « fermé » sans ordre de fermeture."""
        self.assertIsNone(gg.notifiable_state("closed", "open_cover", _il_y_a(2), NOW))
        self.assertIsNone(gg.notifiable_state("open", "close_cover", _il_y_a(2), NOW))

    def test_un_ordre_ancien_n_est_plus_annonce(self) -> None:
        self.assertIsNone(gg.notifiable_state("open", "open_cover", _il_y_a(16), NOW))
        self.assertEqual(gg.notifiable_state("open", "open_cover", _il_y_a(14.5), NOW), "open")

    def test_un_ordre_qui_n_est_pas_un_ordre_de_volet_ou_un_instant_illisible(self) -> None:
        for action in ("start_mowing", "dock", None):
            self.assertIsNone(gg.notifiable_state("open", action, _il_y_a(1), NOW))
        for instant in ("pas une date", "", None):
            self.assertIsNone(gg.notifiable_state("open", "open_cover", instant, NOW))

    def test_un_instant_dans_le_futur_n_est_pas_annonce(self) -> None:
        self.assertIsNone(gg.notifiable_state("open", "open_cover", _il_y_a(-5), NOW))


class PolitiqueDeBlocageAnnonceeTests(unittest.TestCase):
    """La limite de 24 h du blocage est DITE à l'utilisateur, jamais présentée comme sans limite."""

    def test_l_aide_du_plafond_dit_la_limite_de_24_heures(self) -> None:
        reglages = importlib.import_module("custom_components.gazon_intelligent.reglages")
        aide = reglages.reglage("tondeuse_garage_tentatives_max").aide
        self.assertIn("24 h au plus", aide)
        self.assertEqual(gg.GARAGE_BLOCK_WINDOW_MINUTES, 24 * 60)

    def test_au_dela_de_24_heures_une_nouvelle_serie_est_autorisee_et_l_alerte_s_efface(self) -> None:
        """Choix explicite du propriétaire (« garder 24 h ») : documenté par un test, pas une surprise."""
        registre = _serie("open_cover", depuis=24 * 60.0 + 1, tentatives=3, debut=24 * 60.0 + 6)
        self.assertIsNone(gg.command_gate("open_cover", registre, {}, NOW))
        self.assertIsNone(
            gg.alert(cover_entity="cover.garage", cover_state="closed", position=0, mower_away=False,
                     runtime=registre, settings={}, now=NOW)
        )
        self.assertIsNone(gg.reset_updates(registre, "closed", 0, NOW)[gg.KEY_COMMAND])

    def test_juste_avant_24_heures_le_blocage_tient_encore(self) -> None:
        registre = _serie("open_cover", depuis=24 * 60.0 - 1, tentatives=3, debut=24 * 60.0 + 4)
        self.assertEqual(gg.command_gate("open_cover", registre, {}, NOW)["state"], "volet_bloque")


class ReferenceDeFermetureTests(unittest.TestCase):
    """Depuis quand compte-t-on le délai avant fermeture ?"""

    def test_apres_une_rentree_normale_c_est_la_rentree(self) -> None:
        rentree = _il_y_a(5)
        self.assertEqual(gg.close_reference({gg.KEY_OPEN_SINCE: _il_y_a(1)}, rentree, False), rentree)

    def test_volet_ouvert_a_la_main_apres_la_rentree_c_est_l_ouverture(self) -> None:
        """⚠️ Le cas du 03/10 : tondeuse à quai depuis des heures, volet ouvert à la main il y a
        1 minute. Compter depuis la rentrée le refermerait d'emblée."""
        ouverture = _il_y_a(1)
        self.assertEqual(gg.close_reference({gg.KEY_OPEN_SINCE: ouverture}, _il_y_a(300), True), ouverture)

    def test_volet_ouvert_a_la_main_avant_la_rentree_c_est_la_rentree(self) -> None:
        rentree = _il_y_a(2)
        self.assertEqual(gg.close_reference({gg.KEY_OPEN_SINCE: _il_y_a(60)}, rentree, True), rentree)

    def test_sans_ouverture_notee_on_retombe_sur_la_rentree(self) -> None:
        rentree = _il_y_a(10)
        self.assertEqual(gg.close_reference({}, rentree, True), rentree)

    def test_sans_rentree_notee_on_prend_l_ouverture(self) -> None:
        ouverture = _il_y_a(3)
        self.assertEqual(gg.close_reference({gg.KEY_OPEN_SINCE: ouverture}, None, True), ouverture)


class AlerteTests(unittest.TestCase):
    def _alerte(self, *, etat="open", position=100, dehors=False, registre=None, reglages=None, volet="cover.garage"):
        return gg.alert(
            cover_entity=volet, cover_state=etat, position=position, mower_away=dehors,
            runtime=registre or {}, settings=reglages or {}, now=NOW,
        )

    def test_sans_volet_configure_aucune_alerte(self) -> None:
        self.assertIsNone(self._alerte(etat="unavailable", dehors=True, volet=None))

    def test_volet_indisponible_tondeuse_dehors_alerte_apres_le_delai_de_grace(self) -> None:
        registre = {gg.KEY_UNAVAILABLE_SINCE: _il_y_a(6)}
        for etat in ("unavailable", "unknown", "", None):
            with self.subTest(etat=etat):
                alerte = self._alerte(etat=etat, dehors=True, registre=registre)
                self.assertEqual(alerte["code"], gg.ALERT_UNAVAILABLE)
                self.assertIn("la tondeuse est dehors", alerte["motif"])

    def test_juste_apres_un_redemarrage_de_home_assistant_pas_de_fausse_alerte(self) -> None:
        """⚠️ Le volet est « indisponible » une à deux minutes après chaque redémarrage."""
        for registre in ({}, {gg.KEY_UNAVAILABLE_SINCE: _il_y_a(1)}, {gg.KEY_UNAVAILABLE_SINCE: _il_y_a(4.9)}):
            with self.subTest(registre=registre):
                self.assertIsNone(self._alerte(etat="unavailable", dehors=True, registre=registre))

    def test_le_delai_de_grace_est_exactement_cinq_minutes(self) -> None:
        self.assertIsNotNone(self._alerte(etat="unavailable", dehors=True, registre={gg.KEY_UNAVAILABLE_SINCE: _il_y_a(5)}))

    def test_volet_indisponible_tondeuse_rentree_pas_d_alerte(self) -> None:
        """Rien à protéger : la tondeuse est à quai. Le volet reste « indisponible » dans l'état publié."""
        self.assertIsNone(self._alerte(etat="unavailable", dehors=False, registre={gg.KEY_UNAVAILABLE_SINCE: _il_y_a(60)}))

    def test_volet_normal_tondeuse_dehors_pas_d_alerte(self) -> None:
        for etat in ("open", "opening", "closed", "closing"):
            with self.subTest(etat=etat):
                self.assertIsNone(self._alerte(etat=etat, dehors=True))

    def test_ordre_sans_effet_au_dela_de_la_marge_le_volet_est_bloque(self) -> None:
        registre = _serie("open_cover", depuis=0.5, tentatives=2, debut=4.0)
        alerte = self._alerte(etat="closed", position=0, registre=registre)
        self.assertEqual(alerte["code"], gg.ALERT_STUCK)
        self.assertIn("l'ordre d'ouverture", alerte["motif"])
        self.assertIn("2 tentatives", alerte["motif"])

    def test_la_marge_se_mesure_depuis_le_premier_ordre_de_la_serie(self) -> None:
        """Le délai de reprise (2 min) est plus court que la marge (3 min) : mesurer depuis le
        DERNIER ordre ne la laisserait jamais s'écouler."""
        registre = _serie("close_cover", depuis=0.5, tentatives=2, debut=3.5)
        self.assertEqual(self._alerte(etat="open", registre=registre)["code"], gg.ALERT_STUCK)

    def test_dans_la_marge_pas_d_alerte(self) -> None:
        registre = _serie("open_cover", depuis=1.0, tentatives=1, debut=1.0)
        self.assertIsNone(self._alerte(etat="closed", position=0, registre=registre))

    def test_la_marge_est_reglable(self) -> None:
        registre = _serie("open_cover", depuis=1.0, tentatives=1, debut=4.0)
        self.assertIsNone(self._alerte(etat="closed", registre=registre, reglages={"tondeuse_garage_delai_max_mouvement": 5}))
        self.assertIsNotNone(self._alerte(etat="closed", registre=registre, reglages={"tondeuse_garage_delai_max_mouvement": 4}))

    def test_au_plafond_de_tentatives_l_alerte_part_sans_attendre_la_marge(self) -> None:
        registre = _serie("open_cover", depuis=0.2, tentatives=3, debut=1.0)
        self.assertEqual(self._alerte(etat="closed", registre=registre)["code"], gg.ALERT_STUCK)

    def test_un_volet_qui_a_atteint_sa_cible_n_est_pas_bloque(self) -> None:
        registre = _serie("open_cover", depuis=0.5, tentatives=3, debut=10.0)
        self.assertIsNone(self._alerte(etat="open", position=100, registre=registre))

    def test_un_volet_ouvert_a_moitie_apres_la_marge_est_bloque(self) -> None:
        registre = _serie("open_cover", depuis=0.5, tentatives=1, debut=5.0)
        self.assertEqual(self._alerte(etat="open", position=40, registre=registre)["code"], gg.ALERT_STUCK)

    def test_une_serie_non_epuisee_oubliee_ne_donne_pas_d_alerte(self) -> None:
        registre = _serie("open_cover", depuis=90.0, tentatives=2, debut=95.0)
        self.assertIsNone(self._alerte(etat="closed", registre=registre))

    def test_un_volet_bloque_reste_signale_bien_au_dela_d_une_heure(self) -> None:
        """⚠️ L'alerte ne s'efface plus au bout de 61 minutes : le volet est toujours bloqué."""
        for minutes in (61.0, 180.0, 1000.0):
            with self.subTest(minutes=minutes):
                registre = _serie("open_cover", depuis=minutes, tentatives=3, debut=minutes + 5)
                self.assertEqual(self._alerte(etat="closed", registre=registre)["code"], gg.ALERT_STUCK)

    def test_un_volet_bloque_n_est_plus_signale_apres_24_heures(self) -> None:
        registre = _serie("open_cover", depuis=25 * 60.0, tentatives=3, debut=25 * 60.0 + 5)
        self.assertIsNone(self._alerte(etat="closed", registre=registre))

    def test_un_volet_indisponible_prime_sur_un_volet_bloque(self) -> None:
        registre = _serie("open_cover", depuis=0.5, tentatives=3, debut=10.0)
        registre = {**registre, gg.KEY_UNAVAILABLE_SINCE: _il_y_a(10)}
        self.assertEqual(self._alerte(etat="unavailable", dehors=True, registre=registre)["code"], gg.ALERT_UNAVAILABLE)

    def test_le_motif_dit_un_seul_ordre_au_singulier(self) -> None:
        registre = _serie("open_cover", depuis=0.5, tentatives=1, debut=5.0)
        self.assertIn("(1 tentative)", self._alerte(etat="closed", registre=registre)["motif"])


# ── Le pilote complet : la porte des ordres et le délai d'un volet ouvert à la main ─────────────

mc = importlib.import_module("custom_components.gazon_intelligent.mower_control")


def _pret(**maj):
    """Une tondeuse prête à partir, à quai, gazon autorisé (comme `tests/test_mower_control.py`)."""
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


def _piloter(instantane, *, volet="closed", position=0, registre=None, reglages=None):
    return mc.evaluate_mower_control(
        instantane, now=NOW, mode="actif", bootstrap_complete=True, settings=reglages or {},
        runtime=registre or {}, cover_entity="cover.garage", cover_state=volet, cover_position=position,
    )


class PorteDesOrdresDansLePiloteTests(unittest.TestCase):
    def test_un_ordre_d_ouverture_tout_juste_envoye_n_est_pas_renvoye(self) -> None:
        decision = _piloter(_pret(), registre=_serie("open_cover", depuis=0.5))
        self.assertIsNone(decision["mower_control_pending_action"])
        self.assertEqual(decision["mower_control_state"], "temporisation")
        self.assertIn("nouvelle tentative dans", decision["mower_control_reason"])

    def test_apres_le_delai_du_volet_l_ordre_est_renvoye_sans_attendre_les_10_minutes_communes(self) -> None:
        """⚠️ Avant : même sens renvoyé après le délai COMMUN (10 min). Un ordre raté retardait le départ."""
        decision = _piloter(
            _pret(), registre={**_serie("open_cover", depuis=3.0), "last_action": "open_cover", "last_action_at": _il_y_a(3.0)},
        )
        self.assertEqual(decision["mower_control_pending_action"], "open_cover")

    def test_au_plafond_le_pilote_n_envoie_plus_et_dit_que_le_volet_est_bloque(self) -> None:
        decision = _piloter(_pret(), registre=_serie("open_cover", depuis=10.0, tentatives=3))
        self.assertIsNone(decision["mower_control_pending_action"])
        self.assertEqual(decision["mower_control_state"], "volet_bloque")
        self.assertIn("intervention manuelle", decision["mower_control_reason"])

    def test_le_plafond_et_le_delai_viennent_des_reglages(self) -> None:
        reglages = {"tondeuse_garage_tentatives_max": 6, "tondeuse_garage_delai_reprise": 8}
        registre = _serie("open_cover", depuis=5.0, tentatives=3)
        self.assertEqual(_piloter(_pret(), registre=registre, reglages=reglages)["mower_control_state"], "temporisation")
        registre = _serie("open_cover", depuis=9.0, tentatives=3)
        self.assertEqual(_piloter(_pret(), registre=registre, reglages=reglages)["mower_control_pending_action"], "open_cover")

    def test_un_ordre_de_fermeture_n_est_pas_retenu_par_une_serie_d_ouverture(self) -> None:
        """Sens opposé : nouvelle série. Tondeuse rentrée, volet ouvert par le pilote, délai écoulé."""
        registre = {**_serie("open_cover", depuis=0.5, tentatives=3), gg.KEY_OPENED_BY_PILOT: True, "docked_since": _il_y_a(10)}
        decision = _piloter(_pret(action_possible=False), volet="open", position=100, registre=registre)
        self.assertEqual(decision["mower_control_pending_action"], "close_cover")

    def test_les_ordres_qui_ne_sont_pas_des_ordres_de_volet_gardent_le_delai_commun(self) -> None:
        """Le départ reste protégé par le délai habituel de toutes les commandes (10 min)."""
        registre = {"last_action": "start_mowing", "last_action_at": _il_y_a(3.0)}
        decision = _piloter(_pret(), volet="open", position=100, registre={**registre, "garage_ouvert_depuis": _il_y_a(5), gg.KEY_OPENED_BY_PILOT: True,
                                                                          "garage_opened_at": _il_y_a(5)})
        self.assertEqual(decision["mower_control_state"], "temporisation")
        self.assertIn("déjà envoyée récemment", decision["mower_control_reason"])


class VoletOuvertALaMainDansLePiloteTests(unittest.TestCase):
    """Tondeuse à quai depuis des heures, volet ouvert à la main : on ne le referme pas d'emblée."""

    REGLAGES = {"tondeuse_garage_delai_fermeture": 1, "tondeuse_garage_delai_fermeture_manuel": 30}

    def _quai(self, **registre):
        return _piloter(
            _pret(action_possible=False), volet="open", position=100, reglages=self.REGLAGES,
            registre={"docked_since": _il_y_a(300), **registre},
        )

    def test_ouvert_a_la_main_il_y_a_1_minute_on_attend(self) -> None:
        decision = self._quai(**{gg.KEY_OPENED_BY_PILOT: False, gg.KEY_OPEN_SINCE: _il_y_a(1)})
        self.assertIsNone(decision["mower_control_pending_action"])
        self.assertEqual(decision["mower_control_state"], "attente_fermeture_garage")
        self.assertIn("Garage ouvert à la main", decision["mower_control_reason"])
        self.assertIn("30 min", decision["mower_control_reason"])
        self.assertNotIn("Rentrée confirmée", decision["mower_control_reason"])

    def test_ouvert_a_la_main_depuis_plus_que_le_delai_manuel_on_ferme(self) -> None:
        decision = self._quai(**{gg.KEY_OPENED_BY_PILOT: False, gg.KEY_OPEN_SINCE: _il_y_a(31)})
        self.assertEqual(decision["mower_control_pending_action"], "close_cover")
        self.assertIn("Garage ouvert à la main", decision["mower_control_reason"])
        self.assertNotIn("Rentrée confirmée", decision["mower_control_reason"])

    def test_ouvert_par_le_pilote_le_delai_est_celui_de_la_rentree(self) -> None:
        decision = self._quai(**{gg.KEY_OPENED_BY_PILOT: True, gg.KEY_OPEN_SINCE: _il_y_a(1)})
        self.assertEqual(decision["mower_control_pending_action"], "close_cover")
        self.assertIn("Rentrée confirmée", decision["mower_control_reason"])

    def test_ouvert_a_la_main_avant_la_rentree_c_est_la_rentree_qui_compte(self) -> None:
        """Volet ouvert à la main il y a 3 h, tondeuse rentrée il y a 1 min : délai manuel depuis la rentrée."""
        decision = _piloter(
            _pret(action_possible=False), volet="open", position=100, reglages=self.REGLAGES,
            registre={gg.KEY_OPENED_BY_PILOT: False, gg.KEY_OPEN_SINCE: _il_y_a(180), "docked_since": _il_y_a(1)},
        )
        self.assertIsNone(decision["mower_control_pending_action"])
        self.assertEqual(decision["mower_control_state"], "attente_fermeture_garage")

    def test_origine_inconnue_le_comportement_d_avant_est_conserve(self) -> None:
        decision = self._quai(**{gg.KEY_OPEN_SINCE: _il_y_a(1)})
        self.assertEqual(decision["mower_control_pending_action"], "close_cover")


class RegistreLieAUnVoletTests(unittest.TestCase):
    """Changer de volet ne transmet pas au nouveau le blocage de l'ancien."""

    BLOQUE = {
        gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(10), gg.KEY_SERIES_START: _il_y_a(15),
        gg.KEY_ATTEMPTS: 3, gg.KEY_OPENED_BY_PILOT: True, gg.KEY_OPEN_SINCE: _il_y_a(30),
        gg.KEY_UNAVAILABLE_SINCE: _il_y_a(5),
    }

    def test_sans_volet_configure_rien_n_est_lie(self) -> None:
        self.assertEqual(gg.entity_updates({}, None), {})
        self.assertEqual(gg.entity_updates(self.BLOQUE, ""), {})

    def test_le_premier_volet_est_adopte_sans_rien_effacer(self) -> None:
        self.assertEqual(gg.entity_updates({}, "cover.garage"), {gg.KEY_ENTITY: "cover.garage"})
        # Un registre d'avant cette liaison (aucune entité mémorisée) est adopté tel quel.
        self.assertEqual(gg.entity_updates(dict(self.BLOQUE), "cover.garage"), {gg.KEY_ENTITY: "cover.garage"})

    def test_le_meme_volet_ne_change_rien(self) -> None:
        self.assertEqual(gg.entity_updates({**self.BLOQUE, gg.KEY_ENTITY: "cover.garage"}, "cover.garage"), {})

    def test_un_autre_volet_repart_d_un_registre_vierge(self) -> None:
        runtime = {**self.BLOQUE, gg.KEY_ENTITY: "cover.ancien"}
        maj = gg.entity_updates(runtime, "cover.nouveau")
        self.assertEqual(maj[gg.KEY_ENTITY], "cover.nouveau")
        for cle in (gg.KEY_COMMAND, gg.KEY_COMMAND_AT, gg.KEY_SERIES_START, gg.KEY_OPENED_BY_PILOT,
                    gg.KEY_OPEN_SINCE, gg.KEY_UNAVAILABLE_SINCE):
            self.assertIsNone(maj[cle], cle)
        self.assertEqual(maj[gg.KEY_ATTEMPTS], 0)
        # Appliqué : plus aucune série, le nouveau volet n'est pas tenu pour bloqué.
        appliquee = {**runtime, **maj}
        self.assertIsNone(gg.command_gate("open_cover", appliquee, {}, NOW))
        self.assertFalse(gg.exhausted(appliquee))

    def test_un_volet_retire_puis_un_autre_configure_est_aussi_reinitialise(self) -> None:
        """Volet décoché (aucune entité) puis un AUTRE choisi : la mémoire de l'ancien ne survit pas."""
        runtime = {**self.BLOQUE, gg.KEY_ENTITY: "cover.ancien"}
        self.assertEqual(gg.entity_updates(runtime, None), {})
        self.assertIn(gg.KEY_COMMAND, gg.entity_updates(runtime, "cover.nouveau"))


class VoletFermeDevantUneTondeuseDehorsTests(unittest.TestCase):
    """⚠️ Une tondeuse dehors devant un volet fermé : le plus grave, et le moins visible hors mode actif."""

    def _alerte(self, *, etat="closed", position=0, dehors=True, depuis=10.0, runtime=None, entite="cover.garage"):
        rt = {gg.KEY_CLOSED_OUTSIDE_SINCE: _il_y_a(depuis) if depuis is not None else None, **(runtime or {})}
        return gg.alert(cover_entity=entite, cover_state=etat, position=position, mower_away=dehors,
                        runtime=rt, settings=None, now=NOW)

    def test_volet_ferme_devant_une_tondeuse_dehors_l_alerte_part_apres_la_marge(self) -> None:
        self.assertIsNone(self._alerte(depuis=2.9))
        alerte = self._alerte(depuis=3.0)
        self.assertEqual(alerte["code"], gg.ALERT_CLOSED_OUTSIDE)
        self.assertIn("la tondeuse est dehors", alerte["motif"])

    def test_la_marge_est_celle_du_module(self) -> None:
        self.assertEqual(gg.GARAGE_CLOSED_OUTSIDE_GRACE_MINUTES, 3.0)

    def test_volet_en_fermeture_ou_ouverture_incomplete_compte_comme_non_ouvert(self) -> None:
        for etat, position in (("closing", 40), ("opening", 30), ("open", 60), ("closed", None)):
            with self.subTest(etat=etat):
                self.assertEqual(self._alerte(etat=etat, position=position)["code"], gg.ALERT_CLOSED_OUTSIDE)

    def test_volet_ouvert_assez_aucune_alerte(self) -> None:
        for etat, position in (("open", 100), ("open", 95), ("open", None)):
            with self.subTest(position=position):
                self.assertIsNone(self._alerte(etat=etat, position=position))

    def test_tondeuse_rentree_ou_sans_volet_configure_aucune_alerte(self) -> None:
        self.assertIsNone(self._alerte(dehors=False))
        self.assertIsNone(self._alerte(entite=None))
        self.assertIsNone(self._alerte(entite=""))

    def test_sans_trace_de_depuis_quand_pas_d_alerte(self) -> None:
        self.assertIsNone(self._alerte(depuis=None))

    def test_volet_injoignable_reste_l_alerte_injoignable_pas_celle_ci(self) -> None:
        for etat in ("unavailable", "unknown"):
            alerte = self._alerte(etat=etat, position=None, runtime={gg.KEY_UNAVAILABLE_SINCE: _il_y_a(10)})
            self.assertEqual(alerte["code"], gg.ALERT_UNAVAILABLE)

    def test_un_volet_bloque_prime_sur_le_volet_ferme(self) -> None:
        bloque = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(4), gg.KEY_ATTEMPTS: 3,
                  gg.KEY_SERIES_START: _il_y_a(10)}
        self.assertEqual(self._alerte(runtime=bloque)["code"], gg.ALERT_STUCK)

    def test_depuis_quand_est_note_puis_efface_par_le_registre(self) -> None:
        maj = gg.reset_updates({}, "closed", 0, NOW, mower_away=True)
        self.assertEqual(maj[gg.KEY_CLOSED_OUTSIDE_SINCE], NOW.isoformat())
        # Déjà noté : l'instant d'origine n'est pas réécrit.
        self.assertNotIn(gg.KEY_CLOSED_OUTSIDE_SINCE, gg.reset_updates({gg.KEY_CLOSED_OUTSIDE_SINCE: _il_y_a(5)}, "closed", 0, NOW, mower_away=True))
        for etat, position in (("open", 100), ("open", None)):
            maj = gg.reset_updates({gg.KEY_CLOSED_OUTSIDE_SINCE: _il_y_a(5)}, etat, position, NOW, mower_away=True)
            self.assertIsNone(maj[gg.KEY_CLOSED_OUTSIDE_SINCE], "volet rouvert : on efface")
        maj = gg.reset_updates({gg.KEY_CLOSED_OUTSIDE_SINCE: _il_y_a(5)}, "closed", 0, NOW, mower_away=False)
        self.assertIsNone(maj[gg.KEY_CLOSED_OUTSIDE_SINCE], "tondeuse rentrée : on efface")

    def test_pas_de_depuis_quand_pour_un_volet_muet_ou_sans_tondeuse_dehors(self) -> None:
        self.assertNotIn(gg.KEY_CLOSED_OUTSIDE_SINCE, gg.reset_updates({}, "unavailable", None, NOW, mower_away=True))
        self.assertNotIn(gg.KEY_CLOSED_OUTSIDE_SINCE, gg.reset_updates({}, "closed", 0, NOW, mower_away=False))
        self.assertNotIn(gg.KEY_CLOSED_OUTSIDE_SINCE, gg.reset_updates({}, "closed", 0, NOW), "défaut : tondeuse non dehors")

    def test_un_autre_volet_efface_aussi_le_depuis_quand(self) -> None:
        runtime = {gg.KEY_ENTITY: "cover.ancien", gg.KEY_CLOSED_OUTSIDE_SINCE: _il_y_a(30)}
        self.assertIsNone(gg.entity_updates(runtime, "cover.nouveau")[gg.KEY_CLOSED_OUTSIDE_SINCE])


if __name__ == "__main__":
    unittest.main()
