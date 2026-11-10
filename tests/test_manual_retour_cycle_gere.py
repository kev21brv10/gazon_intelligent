"""Un retour MANUEL réussi rend la tondeuse au constructeur : le cycle géré interrompu n'est plus suivi.

Signalé en revue de la PR #85. Un départ du pilote ouvre un cycle « géré » (`managed_cycle_active`) : la
tondeuse gère seule ses recharges et ses redéparts, et le pilote ne renvoie jamais `start_mowing`. Seule la
FIN du travail (état « terminé », ou progression à 100 % vue après un état inachevé) referme ce cycle. Or un
retour demandé à la main depuis la page interrompt volontairement le travail : il reste « en pause » sous
100 % et ne se termine jamais. L'indicateur restait donc posé :
- le pilote répondait `cycle_autonome` à chaque évaluation, avant la fermeture du volet (volet « classique »)
  et avant la suspension des départs ; le volet restait ouvert ;
- aucun départ automatique ne repartait, même après les quatre heures de suspension qui suivent un retour
  manuel, jusqu'à ce qu'un autre travail se termine.

Un retour du PILOTE (rappel de sécurité) garde son rôle : il crée la reprise due, le cycle reste géré. Une
recharge à mi-travail SANS intervention manuelle reste, elle aussi, un cycle autonome.

Tout passe par le VRAI chemin : `async_commande_tondeuse` (la demande de la page) puis
`_async_apply_mower_control` (le cycle), avec les ordres lus sur le service Home Assistant simulé.
"""

from __future__ import annotations

import types

from tests.test_manual_coordinateur import TONDEUSE, _Base, _dehors, _quai

CYCLE_GERE = (
    "managed_cycle_active", "managed_start_pending", "managed_job_seen_incomplete", "managed_job_id",
    "managed_start_baseline_captured", "managed_start_baseline_job_id", "managed_start_baseline_progress",
    "managed_start_baseline_completion_state", "managed_start_requested_at",
)
PORTE = {"tondeuse_garage_ferme_pendant_tonte": True}


def _pret(**maj):
    """À quai, le gazon et la machine autorisent un départ automatique."""
    base = dict(gazon_permet_tonte=True, action_possible=True, mower_job_completion_state="repos",
                mower_job_progress_pct=100, mower_job_id="travail-0")
    base.update(maj)
    return _quai(**base)


def _en_tonte(progression=30, **maj):
    base = dict(gazon_permet_tonte=True, action_possible=True, mower_job_completion_state="en_cours",
                mower_job_progress_pct=progression, mower_job_id="travail-1")
    base.update(maj)
    return _dehors(**base)


def _rentree_en_pause(progression=30, **maj):
    """Rentrée à quai au milieu du travail : « en pause » sous 100 %, comme après un retour demandé à la main."""
    base = dict(gazon_permet_tonte=True, action_possible=True, mower_job_completion_state="en_pause",
                mower_job_progress_pct=progression, mower_job_id="travail-1")
    base.update(maj)
    return _quai(**base)


class _CycleGere(_Base):
    def _runtime(self, coord) -> dict:
        return coord._runtime_state["mower_control"]

    def _suivre(self, coord, instantane, *, apres=0.0):
        """Un cycle ; le volet simulé obéit aux ordres envoyés (ouvert / fermé), comme le vrai."""
        avant = len(self.appel.await_args_list)
        resultat = self._cycle(coord, instantane, apres=apres)
        for appel in self.appel.await_args_list[avant:]:
            if (appel.args[0], appel.args[1]) == ("cover", "open_cover"):
                self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})
            elif (appel.args[0], appel.args[1]) == ("cover", "close_cover"):
                self.volet = types.SimpleNamespace(state="closed", attributes={"current_position": 0})
        return resultat

    def _cycle_lance_par_le_pilote(self, coord) -> None:
        """Le pilote ouvre le volet, envoie le départ, voit la tondeuse sortir : le cycle géré est ouvert."""
        self._suivre(coord, _pret())                        # ouvre le volet
        self._suivre(coord, _pret(), apres=0.5)             # volet ouvert : délai de sécurité
        self._suivre(coord, _pret(), apres=2.5)             # départ
        self.assertEqual(self._ordres(), ["cover.open_cover", "lawn_mower.start_mowing"])
        self._suivre(coord, _en_tonte(), apres=1.0)         # elle est sortie
        runtime = self._runtime(coord)
        self.assertIs(runtime["managed_cycle_active"], True, "le cycle est bien géré par le pilote")

    def _retour_manuel_reussi(self, coord) -> None:
        coord._latest_full_snapshot = _en_tonte()
        self.assertTrue(self._demander(coord, "retour")["ok"])
        avant = len(self._ordres())
        self._suivre(coord, _en_tonte(), apres=0.5)         # ordre de retour
        self.assertIn("lawn_mower.dock", self._ordres()[avant:])
        self._suivre(coord, _rentree_en_pause(), apres=1.0)  # elle est rentrée : la commande se termine
        self.assertEqual(coord._manual_state().get("etape"), "termine")


class RetourManuelPendantUnCycleGereTests(_CycleGere):
    def test_le_cycle_gere_est_rendu_au_constructeur_apres_un_retour_manuel_reussi(self) -> None:
        for libelle, reglages in (("volet classique", {}), ("volet porte", PORTE)):
            with self.subTest(volet=libelle):
                coord = self._coord("actif", reglages=reglages)
                self._cycle_lance_par_le_pilote(coord)
                self._retour_manuel_reussi(coord)
                runtime = self._runtime(coord)
                for cle in CYCLE_GERE:
                    self.assertFalse(runtime.get(cle), f"{cle} doit être purgé : {runtime.get(cle)!r}")
                self.assertIsNot(runtime.get("resume_required"), True, "un retour manuel ne crée pas de reprise due")

    def test_volet_classique_le_volet_se_ferme_apres_le_retour_manuel(self) -> None:
        coord = self._coord("actif")
        self._cycle_lance_par_le_pilote(coord)
        self._retour_manuel_reussi(coord)
        avant = self._ordres().count("cover.close_cover")
        etat = self._suivre(coord, _rentree_en_pause(), apres=1.0)
        self.assertEqual(etat["mower_control_state"], "attente_fermeture_garage")
        self._suivre(coord, _rentree_en_pause(), apres=3.0)
        self.assertEqual(self._ordres().count("cover.close_cover") - avant, 1, "le volet n'est plus tenu ouvert")

    def test_les_departs_automatiques_repartent_apres_la_suspension(self) -> None:
        for libelle, reglages in (("volet classique", {}), ("volet porte", PORTE)):
            with self.subTest(volet=libelle):
                coord = self._coord("actif", reglages=reglages)
                self._cycle_lance_par_le_pilote(coord)
                self._retour_manuel_reussi(coord)
                # Pendant la suspension (4 h) : le volet se referme, puis le pilote dit qu'aucun départ ne part.
                for apres in (1.0, 3.0, 10.0, 10.0):
                    suspendu = self._suivre(coord, _rentree_en_pause(), apres=apres)
                self.assertEqual(suspendu["mower_control_state"], "depart_suspendu")
                self.assertEqual(self.volet.state, "closed")
                departs_avant = self._ordres().count("lawn_mower.start_mowing")
                # Après les 4 h de suspension : le pilote n'est plus « en cycle autonome » ; un nouveau départ part.
                etats = []
                for _ in range(6):
                    etats.append(self._suivre(coord, _pret(), apres=250.0 if not etats else 2.5)["mower_control_state"])
                self.assertNotIn("cycle_autonome", etats, etats)
                self.assertEqual(self._ordres().count("lawn_mower.start_mowing") - departs_avant, 1, etats)

    def test_le_retour_manuel_est_purge_quel_que_soit_le_mode_du_pilote(self) -> None:
        """Les commandes manuelles marchent dans les trois modes : la purge ne dépend pas du mode."""
        for mode in ("desactive", "observation", "actif"):
            with self.subTest(mode=mode):
                coord = self._coord(mode)
                coord._runtime_state["mower_control"] = {"managed_cycle_active": True, "managed_job_seen_incomplete": True,
                                                         "managed_job_id": "travail-1"}
                self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})
                coord._latest_full_snapshot = _en_tonte()
                self.assertTrue(self._demander(coord, "retour")["ok"])
                self._suivre(coord, _en_tonte(), apres=0.5)
                self.assertIn("lawn_mower.dock", self._ordres())
                runtime = self._runtime(coord)
                for cle in CYCLE_GERE:
                    self.assertFalse(runtime.get(cle), f"{cle} : {runtime.get(cle)!r}")

    def test_un_depart_envoye_pas_encore_observe_n_est_pas_confirme_apres_le_retour(self) -> None:
        """La tondeuse vient de sortir : le retour manuel part AVANT que le pilote ait vu la sortie. Le cycle ne doit pas naître juste après."""
        coord = self._coord("actif")
        self._suivre(coord, _pret())
        self._suivre(coord, _pret(), apres=0.5)
        self._suivre(coord, _pret(), apres=2.5)
        self.assertEqual(self._ordres()[-1], "lawn_mower.start_mowing")
        self.assertIs(self._runtime(coord)["managed_start_pending"], True)
        coord._latest_full_snapshot = _en_tonte()
        self.assertTrue(self._demander(coord, "retour")["ok"])
        self._suivre(coord, _en_tonte(), apres=0.5)
        self.assertEqual(self._ordres()[-1], "lawn_mower.dock")
        self._suivre(coord, _en_tonte(), apres=0.5)          # le pilote la voit enfin dehors
        runtime = self._runtime(coord)
        for cle in CYCLE_GERE:
            self.assertFalse(runtime.get(cle), f"{cle} : le départ interrompu et sa référence sont rendus : {runtime.get(cle)!r}")
        self._suivre(coord, _rentree_en_pause(), apres=1.0)
        self.assertIsNot(self._runtime(coord).get("managed_cycle_active"), True)


class CasLegitimesQuiNeChangentPasTests(_CycleGere):
    def test_recharge_a_mi_travail_sans_intervention_reste_un_cycle_autonome(self) -> None:
        for libelle, reglages in (("volet classique", {}), ("volet porte", PORTE)):
            with self.subTest(volet=libelle):
                coord = self._coord("actif", reglages=reglages)
                self._cycle_lance_par_le_pilote(coord)
                recharge = _rentree_en_pause(55, mower_operation_state="charging")
                etats = [self._suivre(coord, recharge, apres=apres)["mower_control_state"] for apres in (1.0, 3.0, 3.0, 200.0)]
                # Volet « porte » : il se referme d'abord derrière elle ; ensuite, comme le volet classique, le pilote laisse faire.
                self.assertEqual(etats[-1], "cycle_autonome", etats)
                if not reglages:
                    self.assertEqual(set(etats), {"cycle_autonome"}, etats)
                runtime = self._runtime(coord)
                self.assertIs(runtime["managed_cycle_active"], True)
                self.assertIs(runtime["managed_job_seen_incomplete"], True)
                self.assertEqual(self._ordres().count("lawn_mower.start_mowing"), 1, "jamais de second départ pendant le cycle")
                self.assertNotIn("lawn_mower.dock", self._ordres())

    def test_le_retour_du_pilote_cree_toujours_la_reprise_due_et_garde_le_cycle(self) -> None:
        coord = self._coord("actif")
        self._cycle_lance_par_le_pilote(coord)
        self._suivre(coord, _en_tonte(gazon_permet_tonte=False, action_possible=False), apres=1.0)
        self.assertEqual(self._ordres()[-1], "lawn_mower.dock")
        runtime = self._runtime(coord)
        self.assertIs(runtime["resume_required"], True)
        self.assertIs(runtime["managed_cycle_active"], True)

    def test_un_retour_manuel_apres_un_rappel_du_pilote_laisse_la_reprise_due_telle_quelle(self) -> None:
        """La dette de reprise est celle d'un rappel DU PILOTE : le retour manuel qui suit n'y touche pas."""
        coord = self._coord("actif")
        self._cycle_lance_par_le_pilote(coord)
        self._suivre(coord, _en_tonte(gazon_permet_tonte=False, action_possible=False), apres=1.0)
        self.assertIs(self._runtime(coord)["resume_required"], True)
        en_retour = _en_tonte(mower_is_mowing=False, mower_is_returning=True, mower_operation_state="transit",
                              gazon_permet_tonte=False, action_possible=False)
        coord._latest_full_snapshot = en_retour
        self.assertTrue(self._demander(coord, "retour")["ok"])
        self._suivre(coord, en_retour, apres=0.5)
        self.assertEqual(self._ordres().count("lawn_mower.dock"), 2, "le pilote, puis la page")
        runtime = self._runtime(coord)
        self.assertIs(runtime["resume_required"], True, "la reprise due du pilote n'est pas effacée")
        self.assertIsNot(runtime["managed_cycle_active"], True)

    def test_un_retour_manuel_hors_cycle_du_pilote_ne_touche_a_aucun_etat(self) -> None:
        coord = self._coord("actif")
        self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})
        coord._latest_full_snapshot = _en_tonte()
        self.assertTrue(self._demander(coord, "retour")["ok"])
        self._suivre(coord, _en_tonte(), apres=0.5)
        self.assertEqual(self._ordres(), ["lawn_mower.dock"])
        runtime = self._runtime(coord)
        for cle in CYCLE_GERE:
            self.assertNotIn(cle, runtime, f"{cle} ne doit pas apparaître : aucun cycle géré à rendre")

    def test_un_retour_refuse_par_home_assistant_ne_purge_rien(self) -> None:
        coord = self._coord("actif")
        self._cycle_lance_par_le_pilote(coord)
        coord._latest_full_snapshot = _en_tonte()
        self.assertTrue(self._demander(coord, "retour")["ok"])

        async def refuse(domaine, service, donnees, blocking=False):
            if (domaine, service) == ("lawn_mower", "dock"):
                raise RuntimeError("service injoignable")

        self.appel.side_effect = refuse
        self._suivre(coord, _en_tonte(), apres=0.5)
        self.assertEqual(coord._manual_state().get("erreur"), "commande_refusee")
        self.assertIs(self._runtime(coord)["managed_cycle_active"], True, "l'ordre n'est pas parti : le cycle continue")

    def test_une_pause_ou_un_depart_manuel_ne_purgent_pas_le_cycle(self) -> None:
        coord = self._coord("actif")
        self._cycle_lance_par_le_pilote(coord)
        coord._latest_full_snapshot = _en_tonte()
        self.assertTrue(self._demander(coord, "pause")["ok"])
        self._suivre(coord, _en_tonte(mower_operation_state="paused"), apres=0.5)
        self.assertEqual(self._ordres()[-1], "lawn_mower.pause")
        self.assertIs(self._runtime(coord)["managed_cycle_active"], True)

    def test_l_entite_visee_par_le_retour_est_la_tondeuse_configuree(self) -> None:
        coord = self._coord("actif")
        self._cycle_lance_par_le_pilote(coord)
        self._retour_manuel_reussi(coord)
        envois = [a for a in self.appel.await_args_list if a.args[1] == "dock"]
        self.assertEqual(envois[-1].args[2], {"entity_id": TONDEUSE})
