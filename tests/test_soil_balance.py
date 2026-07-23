from __future__ import annotations

import unittest
from datetime import date
import importlib
from pathlib import Path
import sys
import types



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

soil_balance = importlib.import_module("custom_components.gazon_intelligent.soil_balance")


class SoilBalanceTests(unittest.TestCase):
    def test_update_soil_balance_initializes_from_soil_type(self) -> None:
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 3, 18),
            pluie_mm=1.2,
            arrosage_mm=3.6,
            etp_mm=2.0,
            type_sol="limoneux",
        )

        self.assertEqual(state["date"], "2026-03-18")
        self.assertEqual(state["previous_reserve_mm"], 12.0)
        self.assertEqual(state["reserve_mm"], 14.8)
        self.assertEqual(state["delta_mm"], 2.8)
        self.assertEqual(len(state["ledger"]), 1)
        self.assertEqual(state["ledger"][0]["reserve_mm"], 14.8)

    def test_update_soil_balance_replaces_same_day_entry(self) -> None:
        initial = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 3, 18),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=2.0,
            type_sol="limoneux",
        )
        updated = soil_balance.update_soil_balance(
            previous_state=initial,
            today=date(2026, 3, 18),
            pluie_mm=2.0,
            arrosage_mm=1.0,
            etp_mm=1.0,
            type_sol="limoneux",
        )

        self.assertEqual(len(updated["ledger"]), 1)
        # L'entrée du jour est bien REMPLACÉE (pluie / arrosage mis à jour)…
        self.assertEqual(updated["previous_reserve_mm"], 12.0)
        self.assertEqual(updated["ledger"][0]["pluie_mm"], 2.0)
        self.assertEqual(updated["ledger"][0]["arrosage_mm"], 1.0)
        # …mais l'ET0 retient le PIC du jour (lissage) : le 2e passage à 1.0 ne fait PAS redescendre
        # l'ET0 sous le 2.0 du 1er passage → réserve stable (12 + 2 + 1 − 2 = 13).
        self.assertEqual(updated["ledger"][0]["etp_mm"], 2.0)
        self.assertEqual(updated["reserve_mm"], 13.0)

    def test_etp_smoothing_keeps_daily_peak(self) -> None:
        # Lissage ET0 (anti-yoyo) : si l'estimation ET0 RECULE dans la journée (soir, ou soubresaut
        # météo type met.no soleil→pluie), le bilan retient le PIC du jour → la réserve ne remonte
        # pas. Reproduit le cas vécu 25/06 (ET0 9,5 à 17h puis 5,4 à 21h).
        common = dict(today=date(2026, 6, 25), pluie_mm=0.0, arrosage_mm=0.0, type_sol="limoneux")
        midi = soil_balance.update_soil_balance(
            previous_state={"reserve_mm": 12.0, "reserve_max_mm": 24.0, "type_sol": "limoneux"},
            etp_mm=9.5,
            **common,
        )
        soir = soil_balance.update_soil_balance(previous_state=midi, etp_mm=5.4, **common)
        self.assertEqual(soir["etp_mm"], 9.5)  # pic du jour retenu, PAS 5.4
        self.assertEqual(soir["reserve_mm"], midi["reserve_mm"])  # réserve stable (pas de remontée)

    def test_etp_smoothing_resets_each_day(self) -> None:
        # Le pic se réinitialise chaque jour : un nouveau jour repart de l'ET0 courante.
        j1 = soil_balance.update_soil_balance(
            previous_state={"reserve_mm": 12.0, "reserve_max_mm": 24.0, "type_sol": "limoneux"},
            today=date(2026, 6, 25), etp_mm=9.5, pluie_mm=0.0, arrosage_mm=0.0, type_sol="limoneux",
        )
        j2 = soil_balance.update_soil_balance(
            previous_state=j1, today=date(2026, 6, 26), etp_mm=4.0, pluie_mm=0.0, arrosage_mm=0.0, type_sol="limoneux",
        )
        self.assertEqual(j2["etp_mm"], 4.0)  # pas le pic d'hier (9.5)

    def test_etp_smoothing_capped(self) -> None:
        # Un faux pic météo absurde est plafonné (ETP_DAILY_CAP_MM) → ne casse pas le bilan.
        state = soil_balance.update_soil_balance(
            previous_state={"reserve_mm": 12.0, "reserve_max_mm": 24.0, "type_sol": "limoneux"},
            today=date(2026, 6, 25), etp_mm=30.0, pluie_mm=0.0, arrosage_mm=0.0, type_sol="limoneux",
        )
        self.assertEqual(state["etp_mm"], soil_balance.ETP_DAILY_CAP_MM)

    def test_normalize_soil_balance_state_keeps_legacy_ledger(self) -> None:
        state = soil_balance.normalize_soil_balance_state(
            {
                "date": "2026-03-18",
                "reserve_mm": "13.2",
                "ledger": [
                    {
                        "date": "2026-03-17",
                        "reserve_mm": "12.0",
                        "previous_reserve_mm": "11.0",
                        "pluie_mm": "1.0",
                        "arrosage_mm": "2.0",
                        "etp_mm": "1.5",
                        "delta_mm": "1.5",
                        "type_sol": "limoneux",
                    }
                ],
            }
        )

        self.assertEqual(state["reserve_mm"], 13.2)
        self.assertEqual(state["ledger"][0]["reserve_mm"], 12.0)
        self.assertEqual(state["ledger"][0]["delta_mm"], 1.5)

    def test_soil_balance_clamps_aberrant_rain(self) -> None:
        state = soil_balance.update_soil_balance(
            {},
            pluie_mm=120.0,
            arrosage_mm=0.0,
            etp_mm=2.0,
        )
        # La pluie aberrante (> 100mm) doit être clampée à 30mm
        self.assertTrue(state["ledger"][-1].get("pluie_suspect"))
        # La réserve doit être <= max raisonnable (pas de recharge à 120mm)
        self.assertLessEqual(state["reserve_mm"], state["reserve_max_mm"])
        # Vérifier que pluie utilisée est 30mm (clampée)
        self.assertEqual(state["ledger"][-1]["pluie_mm"], 30.0)

    def test_set_reserve_mm_anchors_and_survives_same_day_recompute(self) -> None:
        # Réserve « polluée » au départ.
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.2,
            type_sol="limoneux",
        )
        # Recalage manuel à 8 mm → ancre posée.
        state = soil_balance.set_reserve_mm(state, 8.0, today=date(2026, 6, 14))
        self.assertEqual(state["reserve_mm"], 8.0)
        self.assertTrue(state["ledger"][-1].get("manual_anchor"))

        # Cycle suivant le MÊME jour : l'ancre tient, pas de recalcul depuis l'historique.
        recomputed = soil_balance.update_soil_balance(
            state,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.5,
            type_sol="limoneux",
        )
        self.assertEqual(recomputed["reserve_mm"], 8.0)

    def test_manual_anchor_releases_next_day(self) -> None:
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.2,
            type_sol="limoneux",
        )
        state = soil_balance.set_reserve_mm(state, 8.0, today=date(2026, 6, 14))
        # Lendemain : l'évolution normale reprend depuis 8 mm (− ETc).
        nextday = soil_balance.update_soil_balance(
            state,
            today=date(2026, 6, 15),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=5.0,
            type_sol="limoneux",
        )
        self.assertEqual(nextday["previous_reserve_mm"], 8.0)
        self.assertEqual(nextday["reserve_mm"], 3.0)
        self.assertFalse(nextday["ledger"][-1].get("manual_anchor"))

    def test_set_reserve_mm_clamps_to_bounds(self) -> None:
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=0.0,
            type_sol="limoneux",
        )
        high = soil_balance.set_reserve_mm(state, 999.0, today=date(2026, 6, 14))
        self.assertLessEqual(high["reserve_mm"], high["reserve_max_mm"])
        low = soil_balance.set_reserve_mm(state, -5.0, today=date(2026, 6, 14))
        self.assertGreaterEqual(low["reserve_mm"], 0.0)

    def test_manual_anchor_survives_normalize_round_trip(self) -> None:
        # Simule une sauvegarde→restauration (passage par normalize) : l'ancre doit
        # survivre, sinon le recalage serait perdu au redémarrage de Home Assistant.
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=8.2,
            type_sol="limoneux",
        )
        state = soil_balance.set_reserve_mm(state, 8.0, today=date(2026, 6, 14))
        restored = soil_balance.normalize_soil_balance_state(state)
        self.assertTrue(restored["ledger"][-1].get("manual_anchor"))
        # Et l'ancre reste honorée après restauration (même jour).
        recomputed = soil_balance.update_soil_balance(
            restored,
            today=date(2026, 6, 14),
            pluie_mm=0.0,
            arrosage_mm=14.8,
            etp_mm=9.0,
            type_sol="limoneux",
        )
        self.assertEqual(recomputed["reserve_mm"], 8.0)


water = importlib.import_module("custom_components.gazon_intelligent.water")


class TestRoundHalfUpTwins(unittest.TestCase):
    """water._round_half_up_1 et soil_balance._round_half_up_1 sont deux copies du même
    helper. La correction de l'arrondi négatif n'avait été appliquée qu'à soil_balance, ce
    qui a laissé une erreur de 0,1 mm dans les bilans déficitaires de water.py. Ce test
    épingle les deux implémentations au même comportement pour empêcher une redivergence."""

    CASES = [-4.54, -2.38, -0.99, -0.95, -0.05, 0.0, 0.05, 0.95, 0.99, 2.38, 4.54, 12.25]

    def test_les_deux_jumeaux_donnent_le_meme_resultat(self) -> None:
        for value in self.CASES:
            with self.subTest(value=value):
                self.assertEqual(
                    water._round_half_up_1(value),
                    soil_balance._round_half_up_1(value),
                )

    def test_arrondi_negatif_sen_eloigne_de_zero(self) -> None:
        # Avant correction water.py tronquait : -0.99 → -0.9 (optimiste de 0,1 mm).
        for fn in (water._round_half_up_1, soil_balance._round_half_up_1):
            with self.subTest(fn=fn.__module__):
                self.assertEqual(fn(-0.99), -1.0)
                self.assertEqual(fn(-4.54), -4.5)
                self.assertEqual(fn(-2.38), -2.4)

    def test_symetrie_positif_negatif(self) -> None:
        for value in self.CASES:
            with self.subTest(value=value):
                self.assertEqual(
                    water._round_half_up_1(-value), -water._round_half_up_1(value)
                )


class TestSoilReserveTwins(unittest.TestCase):
    """water._SOIL_RESERVE_UTILE_MM et soil_balance.SOIL_RESERVE_BASE_MM sont deux copies de la
    même réserve utile du sol par type. Les modules sont volontairement découplés (pas d'import
    croisé) ; ce test épingle les deux tables à l'identique pour empêcher une divergence
    silencieuse (audit 0.16.x, finding [26])."""

    def test_les_deux_tables_reserve_sont_identiques(self) -> None:
        self.assertEqual(water._SOIL_RESERVE_UTILE_MM, soil_balance.SOIL_RESERVE_BASE_MM)


class TestReserveMaxFollowsSoilType(unittest.TestCase):
    """Le plafond de stock était figé à SOIL_RESERVE_DEFAULT_MAX_MM (24 mm) dès le premier
    appel — normalize_soil_balance_state le résolvait depuis l'état persisté (vide, donc
    type_sol None) et il n'était plus jamais recalculé. La table SOIL_RESERVE_MAX_MM était
    de ce fait inatteignable pour les sols sableux (16) et argileux (32)."""

    def _reserve_max_for(self, type_sol: str) -> float:
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 7, 15),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=1.0,
            type_sol=type_sol,
        )
        return state["reserve_max_mm"]

    def test_chaque_type_de_sol_a_son_plafond(self) -> None:
        for type_sol, attendu in soil_balance.SOIL_RESERVE_MAX_MM.items():
            with self.subTest(type_sol=type_sol):
                self.assertEqual(self._reserve_max_for(type_sol), attendu)

    def test_sol_inconnu_retombe_sur_le_defaut(self) -> None:
        self.assertEqual(
            self._reserve_max_for("inconnu"), soil_balance.SOIL_RESERVE_DEFAULT_MAX_MM
        )

    def test_changement_de_sol_reajuste_le_plafond(self) -> None:
        # Sol corrigé en configuration : le plafond doit suivre, pas rester sur l'ancien.
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 7, 15),
            pluie_mm=0.0, arrosage_mm=0.0, etp_mm=1.0,
            type_sol="sableux",
        )
        self.assertEqual(state["reserve_max_mm"], 16.0)
        state = soil_balance.update_soil_balance(
            previous_state=state,
            today=date(2026, 7, 16),
            pluie_mm=0.0, arrosage_mm=0.0, etp_mm=1.0,
            type_sol="argileux",
        )
        self.assertEqual(state["reserve_max_mm"], 32.0)

    def test_plafond_stable_si_le_sol_ne_change_pas(self) -> None:
        state = None
        for day in (15, 16, 17):
            state = soil_balance.update_soil_balance(
                previous_state=state,
                today=date(2026, 7, day),
                pluie_mm=0.0, arrosage_mm=0.0, etp_mm=1.0,
                type_sol="argileux",
            )
            self.assertEqual(state["reserve_max_mm"], 32.0)

    def test_un_sol_argileux_stocke_au_dela_de_24mm(self) -> None:
        # Conséquence concrète : avec l'ancien plafond figé, la réserve d'un sol argileux
        # saturait à 24 mm et l'eau au-delà était perdue pour le calcul.
        state = None
        for day in range(1, 12):
            state = soil_balance.update_soil_balance(
                previous_state=state,
                today=date(2026, 4, day),
                pluie_mm=8.0, arrosage_mm=0.0, etp_mm=1.0,
                type_sol="argileux",
            )
        self.assertGreater(state["reserve_mm"], 24.0)
        self.assertLessEqual(state["reserve_mm"], 32.0)


class RainDayEdgeProtectionTests(unittest.TestCase):
    """L'entrée du jour est REMPLACÉE à chaque refresh du coordinateur. Sans protection, un
    capteur pluie qui retombe à 0 en cours de journée (indisponible, glitch, redémarrage) effaçait
    la pluie déjà comptabilisée et faisait chuter la réserve rétroactivement — le même yoyo que
    celui déjà corrigé pour l'ET0."""

    def _jour(self, state, pluie):
        return soil_balance.update_soil_balance(
            previous_state=state,
            today=date(2026, 7, 22),
            pluie_mm=pluie,
            arrosage_mm=0.0,
            etp_mm=3.0,
            type_sol="limoneux",
        )

    def test_capteur_indisponible_ne_efface_pas_la_pluie_du_jour(self) -> None:
        # None = pas de mesure. La pluie déjà comptabilisée doit être conservée.
        etat = self._jour(None, 12.0)
        reserve_avec_pluie = etat["reserve_mm"]
        etat = self._jour(etat, None)
        self.assertEqual(etat["pluie_mm"], 12.0)
        self.assertEqual(etat["reserve_mm"], reserve_avec_pluie)

    def test_un_vrai_zero_est_respecte(self) -> None:
        # RÉGRESSION : un max(pluie, pic_du_jour) figeait le cumul de la VEILLE pour toute la
        # journée, car le capteur Netatmo se remet à zéro APRÈS minuit local — l'entrée du jour
        # naissait donc avec la valeur d'hier. Un 0.0 mesuré doit pouvoir corriger l'entrée.
        etat = self._jour(None, 12.0)         # cumul de la veille, lu juste après minuit
        etat = self._jour(etat, 0.0)          # le capteur bascule enfin sur le nouveau jour
        self.assertEqual(etat["pluie_mm"], 0.0)

    def test_le_cumul_qui_monte_est_bien_suivi(self) -> None:
        etat = self._jour(None, 4.0)
        etat = self._jour(etat, 9.0)
        self.assertEqual(etat["pluie_mm"], 9.0)

    def test_le_pic_se_reinitialise_le_lendemain(self) -> None:
        etat = self._jour(None, 12.0)
        demain = soil_balance.update_soil_balance(
            previous_state=etat,
            today=date(2026, 7, 23),
            pluie_mm=0.0, arrosage_mm=0.0, etp_mm=3.0, type_sol="limoneux",
        )
        self.assertEqual(demain["pluie_mm"], 0.0)

    def test_la_pluie_aberrante_reste_clampee(self) -> None:
        etat = self._jour(None, 250.0)
        self.assertEqual(etat["pluie_mm"], 30.0)
