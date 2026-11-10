"""Une sortie manuelle ne trouve jamais son volet fermé, quel que soit le mode du pilote.

Tout passe par le VRAI chemin d'application des ordres : `async_commande_tondeuse` (la demande de la
page) puis `_async_apply_mower_control` (le cycle). Les ordres sont lus sur le service Home Assistant
simulé, c'est-à-dire ce qui partirait vraiment vers le volet.

⚠️ POURQUOI TROIS MODES. La règle « une tondeuse dehors ne trouve pas son volet fermé » du pilote ne
s'exécute qu'en mode actif : désactivé, il s'arrête avant toute règle de volet ; en observation, il
calcule l'ordre mais n'envoie rien. Or une commande manuelle marche dans les trois modes. C'est donc
elle qui rouvre un volet refermé en route (à la main, par une automatisation…) — signalé en revue de
la PR #83. Les cas ci-dessous couvrent chaque commande, chaque mode et chaque état du volet.
"""

from __future__ import annotations

import types

from tests.test_manual_coordinateur import _Base, _dehors, _quai

MODES = ("desactive", "observation", "actif")

# état du volet refermé en route : (état Home Assistant, position, ordres d'ouverture attendus)
ETATS_DU_VOLET = {
    "fermé": ("closed", 0, 1),
    "à moitié ouvert": ("open", 40, 1),
    "en cours de fermeture": ("closing", 50, 1),
    "en cours d'ouverture": ("opening", 50, 0),    # déjà en route : on ne le contrarie pas
    "injoignable": ("unavailable", None, 0),       # aucun ordre possible : l'alerte du volet prend le relais
}


def _en_retour(**maj):
    return _dehors(mower_is_mowing=False, mower_is_returning=True, mower_operation_state="transit", **maj)


class _SortieManuelle(_Base):
    """Met la tondeuse en sortie manuelle, volet ouvert, puis rend la main au test."""

    def _ouvrir_le_volet(self) -> None:
        self.volet = types.SimpleNamespace(state="open", attributes={"current_position": 100})

    def _sortie(self, mode: str, commande: str, reglages=None):
        """Retourne (coord, instantané « en route » de la commande)."""
        coord = self._coord(mode, reglages=reglages)
        self._ouvrir_le_volet()
        if commande in ("demarrer", "bordure"):
            coord._latest_full_snapshot = _quai()
            self.assertTrue(self._demander(coord, commande)["ok"], commande)
            self._cycle(coord, _quai(), apres=0.5)       # volet ouvert : délai de sécurité
            self._cycle(coord, _quai(), apres=2.5)       # ordre de départ
            self._cycle(coord, _dehors(), apres=1.0)     # elle sort
            return coord, _dehors()
        if commande == "retour":
            coord._latest_full_snapshot = _dehors()
            self.assertTrue(self._demander(coord, "retour")["ok"])
            self._cycle(coord, _dehors(), apres=0.5)     # ordre de retour
            return coord, _en_retour()
        if commande == "pause":
            coord._latest_full_snapshot = _dehors()
            self.assertTrue(self._demander(coord, "pause")["ok"])
            self._cycle(coord, _dehors(mower_operation_state="paused"), apres=0.5)    # ordre de pause
            return coord, _dehors(mower_operation_state="paused")
        # reprise d'une tondeuse mise en pause ailleurs
        coord._latest_full_snapshot = _dehors(mower_operation_state="paused")
        self.assertTrue(self._demander(coord, "reprendre")["ok"])
        self._cycle(coord, _dehors(mower_operation_state="paused"), apres=0.5)       # ordre de reprise
        self._cycle(coord, _dehors(), apres=0.5)
        return coord, _dehors()

    def _ouvertures(self) -> int:
        return self._ordres().count("cover.open_cover")


class VoletRefermeEnRouteTests(_SortieManuelle):
    def test_chaque_commande_dans_chaque_mode_selon_l_etat_du_volet(self) -> None:
        for commande in ("demarrer", "bordure", "retour", "pause", "reprendre"):
            for mode in MODES:
                for libelle, (etat, position, attendu) in ETATS_DU_VOLET.items():
                    with self.subTest(commande=commande, mode=mode, volet=libelle):
                        coord, en_route = self._sortie(mode, commande)
                        avant = self._ouvertures()
                        self._cycle(coord, en_route, apres=2.0, etat=etat, position=position)
                        self.assertEqual(self._ouvertures() - avant, attendu, "ordres d'ouverture envoyés au volet")
                        # Cycle suivant, volet pas encore bougé : jamais deux fois le même ordre (le registre
                        # d'ordres du volet est commun à la commande manuelle et au pilote).
                        self._cycle(coord, en_route, apres=0.5)
                        self.assertEqual(self._ouvertures() - avant, attendu, "pas de doublon au cycle suivant")

    def test_volet_deja_ferme_au_premier_cycle_ou_elle_est_vue_dehors(self) -> None:
        """Le départ vient de partir (étape « départ envoyé ») : le tout premier cycle qui la voit dehors juge déjà le volet."""
        for mode in MODES:
            with self.subTest(mode=mode):
                coord = self._coord(mode)
                self._ouvrir_le_volet()
                self.assertTrue(self._demander(coord, "demarrer")["ok"])
                self._cycle(coord, _quai(), apres=0.5)
                self._cycle(coord, _quai(), apres=2.5)
                self.assertEqual(self._ordres(), ["lawn_mower.start_mowing"])
                self._cycle(coord, _dehors(), apres=1.0, etat="closed", position=0)
                self.assertEqual(self._ordres(), ["lawn_mower.start_mowing", "cover.open_cover"])

    def test_l_ordre_vise_le_volet_configure_dans_chaque_mode(self) -> None:
        for mode in MODES:
            with self.subTest(mode=mode):
                coord, en_route = self._sortie(mode, "demarrer")
                self._cycle(coord, en_route, apres=2.0, etat="closed", position=0)
                self.assertEqual(self._ordres()[-1], "cover.open_cover")
                self.assertEqual(self._donnees_de_l_appel(), {"entity_id": "cover.garage"})

    def test_le_volet_rouvert_aucun_autre_ordre_ne_part(self) -> None:
        for mode in MODES:
            with self.subTest(mode=mode):
                coord, en_route = self._sortie(mode, "demarrer")
                self._cycle(coord, en_route, apres=2.0, etat="closed", position=0)
                self._cycle(coord, en_route, apres=0.3, etat="open", position=100)
                self._cycle(coord, en_route, apres=5.0)
                self.assertEqual(self._ouvertures(), 1)


class VoletPorteTests(_SortieManuelle):
    """Volet « porte » (fermé pendant la tonte) : la règle ne rouvre PAS un volet fermé exprès derrière une
    tondeuse qui tond, mais le rouvre dès qu'elle revient — dans les trois modes."""

    REGLAGES = {"tondeuse_garage_ferme_pendant_tonte": True}

    def test_fermee_derriere_la_tondeuse_qui_tond_le_volet_n_est_pas_rouvert(self) -> None:
        for mode in MODES:
            with self.subTest(mode=mode):
                coord, en_route = self._sortie(mode, "demarrer", reglages=self.REGLAGES)
                avant = self._ouvertures()
                self._cycle(coord, en_route, apres=2.0, etat="closed", position=0)
                self._cycle(coord, en_route, apres=2.0)
                self._cycle(coord, en_route, apres=5.0)
                self.assertEqual(self._ouvertures() - avant, 0, "volet fermé exprès : rien à rouvrir pendant la tonte")

    def test_au_retour_le_volet_est_rouvert_une_seule_fois(self) -> None:
        for mode in MODES:
            with self.subTest(mode=mode):
                coord, en_route = self._sortie(mode, "demarrer", reglages=self.REGLAGES)
                self._cycle(coord, en_route, apres=2.0, etat="closed", position=0)
                avant = self._ouvertures()
                self._cycle(coord, _en_retour(), apres=1.0)
                self.assertEqual(self._ouvertures() - avant, 1)
                self._cycle(coord, _en_retour(), apres=0.5)
                self.assertEqual(self._ouvertures() - avant, 1, "pas de doublon")
