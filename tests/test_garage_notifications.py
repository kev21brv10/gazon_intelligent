"""Notifications du volet de garage : utiles seulement, et une anomalie part toujours.

Une ouverture ou une fermeture n'est annoncée au téléphone que si le PILOTE l'a ordonnée ; un volet
manœuvré à la main (page, appli, télécommande) ne dérange personne. Une anomalie — volet bloqué,
volet injoignable alors que la tondeuse est dehors — est, elle, une alerte persistante.
"""

from __future__ import annotations

import unittest
from datetime import timedelta

from tests.test_notifications import SNAPSHOT_VENT, _a, _coordinateur, _evaluer

SUJETS = {"garage_tondeuse"}


def _garage(**maj):
    return {"configured": True, "state": None, "error": None, "alert": None, "alert_reason": None, **maj}


class ManoeuvreAlaMainNeNotifiePasTests(unittest.TestCase):
    """Le contexte construit par le coordinateur : ce qui part aux téléphones."""

    def _etat(self, **snapshot) -> object:
        coord = _coordinateur()
        base = {**SNAPSHOT_VENT, "mower_garage_entity": "cover.garage"}
        contexte = coord._contexte_des_alertes({**base, **snapshot})
        self.maintenant = coord._current_datetime()
        return contexte["activite_garage"]["state"]

    def _il_y_a(self, minutes: float) -> str:
        return (_a("13:20") - timedelta(minutes=minutes)).isoformat()

    def test_le_pilote_ouvre_l_ouverture_est_annoncee(self) -> None:
        self.assertEqual(
            self._etat(mower_garage_state="open", mower_control_last_action="open_cover",
                       mower_control_last_action_at=self._il_y_a(2)),
            "open",
        )

    def test_le_pilote_ferme_la_fermeture_est_annoncee(self) -> None:
        self.assertEqual(
            self._etat(mower_garage_state="closed", mower_control_last_action="close_cover",
                       mower_control_last_action_at=self._il_y_a(1)),
            "closed",
        )

    def test_volet_ouvert_a_la_main_sans_ordre_du_pilote_rien_n_est_annonce(self) -> None:
        self.assertIsNone(self._etat(mower_garage_state="open"))
        self.assertIsNone(self._etat(mower_garage_state="open", mower_control_last_action="start_mowing",
                                     mower_control_last_action_at=self._il_y_a(1)))

    def test_volet_ferme_a_la_main_apres_une_ouverture_du_pilote_rien_n_est_annonce(self) -> None:
        self.assertIsNone(
            self._etat(mower_garage_state="closed", mower_control_last_action="open_cover",
                       mower_control_last_action_at=self._il_y_a(5))
        )

    def test_un_ordre_ancien_n_est_plus_annonce(self) -> None:
        self.assertIsNone(
            self._etat(mower_garage_state="open", mower_control_last_action="open_cover",
                       mower_control_last_action_at=self._il_y_a(40))
        )

    def test_l_anomalie_et_son_motif_suivent_jusqu_aux_notifications(self) -> None:
        coord = _coordinateur()
        contexte = coord._contexte_des_alertes({
            **SNAPSHOT_VENT, "mower_garage_entity": "cover.garage",
            "mower_garage_alert": "volet_bloque",
            "mower_garage_alert_reason": "Le volet n'a pas atteint sa position.",
        })
        self.assertEqual(contexte["activite_garage"]["alert"], "volet_bloque")
        self.assertEqual(contexte["activite_garage"]["alert_reason"], "Le volet n'a pas atteint sa position.")


class AlerteDuVoletTests(unittest.TestCase):
    def _suite(self, *etapes):
        """Rejoue des contrôles successifs ; rend les alertes de CHAQUE contrôle."""
        memoire = None
        resultats = []
        for garage in etapes:
            alertes, memoire = _evaluer(memoire, progression=None, sujets_actifs=SUJETS, activite_garage=garage)
            resultats.append(alertes)
        return resultats

    def test_un_volet_bloque_part_en_alerte_persistante_une_seule_fois(self) -> None:
        normal = _garage(state=None)
        bloque = _garage(alert="volet_bloque", alert_reason="Le volet n'a pas atteint sa position après 3 tentatives.")
        _, annonce, repetee = self._suite(normal, bloque, bloque)
        self.assertEqual([a.sujet for a in annonce], ["garage_tondeuse"])
        self.assertIn("volet bloqué", annonce[0].titre)
        self.assertIn("3 tentatives", annonce[0].message)
        self.assertEqual(annonce[0].niveau, "action")
        self.assertTrue(annonce[0].persistante)
        self.assertEqual(repetee, [], "la même anomalie ne repart pas à chaque contrôle")

    def test_un_volet_injoignable_tondeuse_dehors_est_critique(self) -> None:
        normal = _garage()
        injoignable = _garage(alert="volet_indisponible", alert_reason="Le volet ne répond pas alors que la tondeuse est dehors.")
        _, annonce = self._suite(normal, injoignable)
        self.assertEqual(annonce[0].niveau, "critique")
        self.assertIn("injoignable", annonce[0].titre)

    def test_l_anomalie_levee_retire_la_trace(self) -> None:
        bloque = _garage(alert="volet_bloque", alert_reason="Bloqué.")
        _, _, leve = self._suite(_garage(), bloque, _garage())
        self.assertEqual([(a.sujet, a.resolue) for a in leve], [("garage_tondeuse", True)])

    def test_une_anomalie_deja_la_au_premier_controle_part_au_suivant(self) -> None:
        """⚠️ Pas avalée comme un état de départ : un redémarrage de Home Assistant en pleine anomalie
        ne doit pas la faire oublier."""
        bloque = _garage(alert="volet_bloque", alert_reason="Bloqué.")
        premier, second, troisieme = self._suite(bloque, bloque, bloque)
        self.assertEqual(premier, [])
        self.assertEqual([a.sujet for a in second], ["garage_tondeuse"])
        self.assertEqual(troisieme, [])

    def test_un_volet_ferme_devant_une_tondeuse_dehors_est_critique(self) -> None:
        ferme = _garage(alert="volet_ferme_dehors", alert_reason="Le volet n'est pas ouvert alors que la tondeuse est dehors.")
        _, annonce = self._suite(_garage(), ferme)
        self.assertEqual(annonce[0].niveau, "critique")
        self.assertIn("volet fermé", annonce[0].titre)
        self.assertIn("tondeuse dehors", annonce[0].titre)
        self.assertTrue(annonce[0].persistante)

    def test_une_anomalie_sans_motif_a_un_message_par_defaut(self) -> None:
        _, annonce = self._suite(_garage(), _garage(alert="volet_bloque"))
        self.assertIn("anomalie", annonce[0].message.lower())

    def test_la_famille_garage_desactivee_aucune_alerte(self) -> None:
        memoire = None
        for garage in (_garage(), _garage(alert="volet_bloque", alert_reason="Bloqué.")):
            alertes, memoire = _evaluer(memoire, progression=None, sujets_actifs=set(), activite_garage=garage)
        self.assertEqual(alertes, [])

    def test_les_etats_confirmes_restent_annonces_comme_avant(self) -> None:
        _, ouvert = self._suite(_garage(state="closed"), _garage(state="open"))
        self.assertEqual([a.sujet for a in ouvert], ["garage_tondeuse"])
        self.assertIn("ouvert", ouvert[0].message.lower())

    def test_une_erreur_de_commande_prime_toujours_sur_une_anomalie(self) -> None:
        """Une seule trace par sujet : l'erreur de service (déjà connue) passe d'abord."""
        _, annonce = self._suite(
            _garage(),
            _garage(error="Service refusé", alert="volet_bloque", alert_reason="Bloqué."),
        )
        self.assertEqual(len(annonce), 1)
        self.assertIn("commande impossible", annonce[0].titre)


class AnomalieEtErreurSimultaneesTests(unittest.TestCase):
    """Une anomalie du volet ne se perd jamais parce qu'une erreur de commande passait avant elle."""

    BLOQUE = dict(alert="volet_bloque", alert_reason="Le volet n'a pas atteint sa position après 3 tentatives.")

    def _suite(self, *etapes):
        memoire = None
        resultats = []
        for garage in etapes:
            alertes, memoire = _evaluer(memoire, progression=None, sujets_actifs=SUJETS, activite_garage=garage)
            resultats.append(alertes)
        return resultats

    @staticmethod
    def _titres(alertes):
        return [("résolue" if a.resolue else a.titre) for a in alertes]

    def test_erreur_et_anomalie_au_meme_controle_l_anomalie_part_apres_la_levee_de_l_erreur(self) -> None:
        """⚠️ Reproduit en relecture : l'erreur gagnait la chaîne, la mémoire de l'anomalie avançait quand
        même, et l'alerte persistante du volet ne partait jamais."""
        normal = _garage()
        les_deux = _garage(error="Service refusé", **self.BLOQUE)
        anomalie = _garage(**self.BLOQUE)
        c1, c2, c3, c4, c5 = self._suite(normal, les_deux, anomalie, anomalie, anomalie)
        self.assertEqual(c1, [])
        self.assertEqual(self._titres(c2), ["⚠️ Garage de la tondeuse : commande impossible"])
        self.assertEqual(self._titres(c3), ["résolue"], "la levée de l'erreur passe d'abord")
        self.assertEqual(self._titres(c4), ["⚠️ Garage de la tondeuse : volet bloqué"], "puis l'anomalie, enfin annoncée")
        self.assertTrue(c4[0].persistante)
        self.assertEqual(c5, [], "et une seule fois")

    def test_erreur_levee_et_anomalie_nouvelle_au_meme_controle(self) -> None:
        c1, c2, c3, c4 = self._suite(_garage(), _garage(error="Service refusé"), _garage(**self.BLOQUE), _garage(**self.BLOQUE))
        self.assertEqual(self._titres(c2), ["⚠️ Garage de la tondeuse : commande impossible"])
        self.assertEqual(self._titres(c3), ["résolue"])
        self.assertEqual(self._titres(c4), ["⚠️ Garage de la tondeuse : volet bloqué"])

    def test_une_anomalie_deja_annoncee_n_est_pas_reannoncee_par_une_erreur_survenue_apres(self) -> None:
        bloque = _garage(**self.BLOQUE)
        c1, c2, c3, c4 = self._suite(_garage(), bloque, _garage(error="Service refusé", **self.BLOQUE), bloque)
        self.assertEqual(self._titres(c2), ["⚠️ Garage de la tondeuse : volet bloqué"])
        self.assertEqual(self._titres(c3), ["⚠️ Garage de la tondeuse : commande impossible"])
        self.assertEqual(self._titres(c4), ["résolue"], "l'erreur levée ; l'anomalie, déjà annoncée, ne repart pas")

    def test_anomalie_levee_pendant_une_erreur_ne_retire_pas_la_trace_de_l_erreur(self) -> None:
        """L'anomalie levée n'est pas différée : sa « résolution » retirerait, au contrôle suivant, la
        notification de l'erreur qui l'a remplacée alors que l'erreur dure encore."""
        erreur = _garage(error="Service refusé")
        c1, c2, c3, c4 = self._suite(_garage(), _garage(**self.BLOQUE), erreur, erreur)
        self.assertEqual(self._titres(c2), ["⚠️ Garage de la tondeuse : volet bloqué"])
        self.assertEqual(self._titres(c3), ["⚠️ Garage de la tondeuse : commande impossible"])
        self.assertEqual(c4, [], "aucune résolution tant que l'erreur est là")

    def test_une_anomalie_disparue_avant_d_etre_annoncee_ne_part_jamais(self) -> None:
        erreur = _garage(error="Service refusé")
        c1, c2, c3, c4, c5 = self._suite(_garage(), _garage(error="Service refusé", **self.BLOQUE), erreur, erreur, _garage())
        self.assertEqual(self._titres(c2), ["⚠️ Garage de la tondeuse : commande impossible"])
        self.assertEqual(c3, [])
        self.assertEqual(c4, [])
        self.assertEqual(self._titres(c5), ["résolue"], "seule l'erreur est levée : aucune anomalie n'a jamais été annoncée")

    def test_la_famille_garage_desactivee_n_accumule_aucune_anomalie_en_attente(self) -> None:
        """Famille décochée : rien ne part, et la mémoire suit l'état courant (rien à rattraper à la réactivation)."""
        memoire = None
        for garage in (_garage(), _garage(error="Service refusé", **self.BLOQUE), _garage(**self.BLOQUE)):
            alertes, memoire = _evaluer(memoire, progression=None, sujets_actifs=set(), activite_garage=garage)
            self.assertEqual(alertes, [])
        alertes, memoire = _evaluer(memoire, progression=None, sujets_actifs=SUJETS, activite_garage=_garage(**self.BLOQUE))
        self.assertEqual(alertes, [], "réactivée sur une anomalie déjà ancienne : pas d'alerte fantôme")


if __name__ == "__main__":
    unittest.main()
