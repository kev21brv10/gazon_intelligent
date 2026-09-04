from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
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


class SoilBalanceHourlyAccumulationTests(unittest.TestCase):
    """Débit du ledger par intégration du taux HORAIRE mesuré (au lieu du prorata estimé).

    L'ET0 journalière est extrapolée d'un instantané et fait du yo-yo (28/07/2026 : 9 mm/j
    annoncés à 15 h, 6,9 à 17 h, ~6 mesurés). Le taux horaire mesuré est intégré au fil du
    temps : le sol sèche au rythme réel. Ces tests verrouillent l'accumulation ET ses
    garde-fous (amorçage, coupure, horloge non monotone, plafond, repli).
    """

    TODAY = date(2026, 7, 28)
    TZ = timezone(timedelta(hours=2))

    def _state_at(self, *, previous_state, hour, minute=0, rate, etp=8.0, fraction=0.5, **kwargs):
        return soil_balance.update_soil_balance(
            previous_state=previous_state,
            today=self.TODAY,
            pluie_mm=kwargs.pop("pluie_mm", 0.0),
            arrosage_mm=kwargs.pop("arrosage_mm", 0.0),
            etp_mm=etp,
            type_sol="limoneux",
            et_elapsed_fraction=fraction,
            etc_hourly_mm_h=rate,
            now=datetime(2026, 7, 28, hour, minute, tzinfo=self.TZ),
            **kwargs,
        )

    def test_le_taux_horaire_est_integre_dans_le_temps(self) -> None:
        # Amorçage à 12 h : prorata 8 × 0.5 = 4 mm déjà écoulés.
        first = self._state_at(previous_state=None, hour=12, rate=0.5)
        self.assertAlmostEqual(first["ledger"][-1]["etp_elapsed_mm"], 4.0, places=3)

        # +2 h à 0.5 mm/h → +1 mm débité (4 → 5), sans dépendre de l'estimation journalière.
        second = self._state_at(previous_state=first, hour=14, rate=0.5)
        self.assertAlmostEqual(second["ledger"][-1]["etp_elapsed_mm"], 5.0, places=3)

        # La réserve suit : elle a bien perdu 1 mm de plus entre les deux passages.
        self.assertAlmostEqual(
            first["ledger"][-1]["reserve_mm"] - second["ledger"][-1]["reserve_mm"], 1.0, places=1
        )

    def test_sans_taux_horaire_on_retombe_sur_le_prorata(self) -> None:
        # Repli intégral sur le modèle historique : aucune régression si le capteur manque.
        state = soil_balance.update_soil_balance(
            previous_state=None,
            today=self.TODAY,
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=8.0,
            type_sol="limoneux",
            et_elapsed_fraction=0.25,
        )
        # 12 − 8 × 0,25 = 10 : prorata inchangé.
        self.assertAlmostEqual(state["ledger"][-1]["reserve_mm"], 10.0, places=1)
        # Et l'entrée ne porte PAS de cumul horaire : c'est CE qui fait retomber la clôture de la
        # veille sur l'ET0 pleine journée (filet anti-sous-débit, cf.
        # SoilBalanceTests::test_cloture_de_la_veille_debite_l_et0_entiere).
        self.assertNotIn("etp_elapsed_mm", state["ledger"][-1])

    def test_le_debit_ne_recule_jamais_en_cours_de_journee(self) -> None:
        # L'estimation journalière peut RETOMBER (9 → 6,9 constaté le 28/07/2026). L'eau déjà
        # évaporée ne revient pas : la réserve ne doit pas REMONTER sans pluie ni arrosage.
        first = soil_balance.update_soil_balance(
            previous_state=None, today=self.TODAY, pluie_mm=0.0, arrosage_mm=0.0,
            etp_mm=9.0, type_sol="limoneux", et_elapsed_fraction=0.6,
        )
        second = soil_balance.update_soil_balance(
            previous_state=first, today=self.TODAY, pluie_mm=0.0, arrosage_mm=0.0,
            etp_mm=4.0, type_sol="limoneux", et_elapsed_fraction=0.6,
        )
        self.assertLessEqual(
            second["ledger"][-1]["reserve_mm"], first["ledger"][-1]["reserve_mm"]
        )

    def test_une_coupure_longue_ne_sur_debite_ni_ne_sous_debite(self) -> None:
        # Home Assistant arrêté 10 h puis relancé. Appliquer le taux courant sur tout le trou
        # viderait la réserve d'un coup (sur-débit) ; mais se contenter de borner le pas PERD
        # définitivement les heures manquées — l'erreur se fige dans la réserve d'ouverture du
        # lendemain (mesuré : ~2,6 mm d'eau fantôme pour 8 h d'arrêt). On borne donc le pas ET
        # on se resynchronise sur le prorata, seule estimation qui connaisse la fraction de
        # journée écoulée pendant l'absence.
        first = self._state_at(previous_state=None, hour=8, rate=1.0, etp=8.0, fraction=0.1)
        self.assertAlmostEqual(first["ledger"][-1]["etp_elapsed_mm"], 0.8, places=3)  # amorçage

        after_gap = self._state_at(previous_state=first, hour=18, rate=1.0, etp=8.0, fraction=0.8)
        elapsed = after_gap["ledger"][-1]["etp_elapsed_mm"]
        # Pas de sur-débit : bien moins que 10 h × 1 mm/h.
        self.assertLess(elapsed, 0.8 + 10.0)
        # Pas de sous-débit non plus : au moins le prorata de la journée écoulée (8 × 0,8 = 6,4),
        # au lieu des 2,8 mm qu'aurait donnés le simple bornage du pas.
        self.assertAlmostEqual(elapsed, 6.4, places=3)

    def test_un_blip_de_capteur_ne_detruit_pas_l_accumulation(self) -> None:
        # DÉFAUT CORRIGÉ : un seul cycle sans taux horaire (capteur `unavailable` — le Netatmo
        # décroche à CHAQUE redémarrage de Home Assistant) réécrivait l'entrée sans les clés
        # d'accumulation, qui étaient alors purgées : le cumul repartait du prorata au cycle
        # suivant. Mesuré : +22 % de sur-débit quand un capteur clignote, l'intégration horaire
        # étant en pratique remplacée par le prorata — en silence.
        state = self._state_at(previous_state=None, hour=8, rate=0.5, etp=8.0, fraction=0.2)
        for _hour in (10, 12, 14):
            state = self._state_at(previous_state=state, hour=_hour, rate=0.5, etp=8.0, fraction=0.2)
        avant = state["ledger"][-1]["etp_elapsed_mm"]

        # Cycle en repli : taux indisponible.
        blip = soil_balance.update_soil_balance(
            previous_state=state, today=self.TODAY, pluie_mm=0.0, arrosage_mm=0.0,
            etp_mm=8.0, type_sol="limoneux", et_elapsed_fraction=0.2,
            etc_hourly_mm_h=None, now=datetime(2026, 7, 28, 14, 2, tzinfo=self.TZ),
        )
        entry = blip["ledger"][-1]
        self.assertIn("etp_elapsed_mm", entry)  # le cumul SURVIT au blip
        self.assertGreaterEqual(entry["etp_elapsed_mm"], avant)  # et ne recule pas
        self.assertTrue(entry.get("etp_hourly"))  # le mode horaire reste celui de la journée

        # Reprise : on repart du cumul conservé, pas du prorata.
        reprise = self._state_at(previous_state=blip, hour=16, rate=0.5, etp=8.0, fraction=0.2)
        self.assertAlmostEqual(reprise["ledger"][-1]["etp_elapsed_mm"], avant + 1.0, places=2)

    def test_journee_tronquee_se_cloture_sur_l_estimation(self) -> None:
        # DÉFAUT CORRIGÉ : si le seul cycle de la journée tombe AVANT l'aube, `et_elapsed_fraction`
        # vaut 0 → cumul 0,0 mm, qui n'est pas None et était donc préféré à l'estimation à la
        # clôture. Une journée entière d'ETc n'était jamais débitée (~5 mm d'eau fantôme), et le
        # sol paraissait plein au réveil — précisément quand la décision d'arroser se prend.
        avant_aube = self._state_at(previous_state=None, hour=0, minute=2, rate=0.0, etp=6.0, fraction=0.0)
        self.assertAlmostEqual(avant_aube["ledger"][-1]["etp_elapsed_mm"], 0.0, places=3)
        ouverture_veille = avant_aube["ledger"][-1]["previous_reserve_mm"]

        lendemain = soil_balance.update_soil_balance(
            previous_state=avant_aube, today=date(2026, 7, 29), pluie_mm=0.0, arrosage_mm=0.0,
            etp_mm=6.0, type_sol="limoneux", et_elapsed_fraction=0.0,
            etc_hourly_mm_h=0.0, now=datetime(2026, 7, 29, 1, 0, tzinfo=self.TZ),
        )
        # La veille est clôturée sur l'estimation pleine journée (6 mm), pas sur le cumul nul.
        self.assertAlmostEqual(
            lendemain["ledger"][-1]["previous_reserve_mm"], max(0.0, ouverture_veille - 6.0), places=1
        )

    def test_taux_non_fini_ne_gele_pas_le_debit(self) -> None:
        # DÉFAUT CORRIGÉ : `max(0.0, nan)` renvoie 0.0 → le mode horaire restait actif avec un
        # taux nul, la réserve cessait de descendre et la journée se clôturait sur cette valeur
        # figée. Un NaN doit être traité comme ABSENT (repli prorata), jamais comme zéro.
        state = self._state_at(previous_state=None, hour=10, rate=0.5, etp=8.0, fraction=0.3)
        avant = state["ledger"][-1]["etp_elapsed_mm"]
        nan_state = self._state_at(previous_state=state, hour=12, rate=float("nan"), etp=8.0, fraction=0.5)
        apres = nan_state["ledger"][-1]["etp_elapsed_mm"]
        # Le débit continue (repli prorata = 8 × 0,5 = 4,0) au lieu de rester figé.
        self.assertGreater(apres, avant)
        self.assertAlmostEqual(apres, 4.0, places=3)

    def test_un_redemarrage_ne_fait_pas_chuter_la_reserve(self) -> None:
        """Signalé par Kévin le 30/07/2026 : « à chaque fois que je redémarre la réserve descend ».

        Le capteur d'ET horaire décroche systématiquement au redémarrage de Home Assistant. Le
        repli faisait alors `max(prorata, cumul)` : la mesure fine était remplacée par
        l'estimation, plus grossière et systématiquement plus haute. Mesuré sur l'install :
        jusqu'à **−1,4 mm en un pas**, là où la dérive normale vaut 0,1 mm.

        NE PAS resynchroniser sur le prorata pour une absence de quelques minutes.
        """
        # 10:00 — cumul mesuré normal, bien EN DESSOUS de ce que le prorata estimerait.
        state = self._state_at(previous_state=None, hour=10, rate=0.2, etp=12.0, fraction=0.4)
        avant = state["ledger"][-1]["etp_elapsed_mm"]
        # 10:05 — redémarrage : le capteur est absent (rate=None), 5 minutes se sont écoulées.
        apres_state = self._state_at(
            previous_state=state, hour=10, minute=5, rate=None, etp=12.0, fraction=0.42
        )
        apres = apres_state["ledger"][-1]["etp_elapsed_mm"]
        self.assertAlmostEqual(
            apres, avant, places=3,
            msg=f"le redémarrage a débité {apres - avant:.2f} mm de plus — le prorata a repris la main",
        )

    def test_une_vraie_coupure_se_resynchronise_toujours(self) -> None:
        # Garde-fou inverse : au-delà de la fenêtre de fraîcheur, le prorata doit reprendre la
        # main, sans quoi une coupure sous-débiterait définitivement (eau fantôme au lendemain).
        state = self._state_at(previous_state=None, hour=8, rate=0.2, etp=12.0, fraction=0.2)
        avant = state["ledger"][-1]["etp_elapsed_mm"]
        apres = self._state_at(
            previous_state=state, hour=14, rate=None, etp=12.0, fraction=0.7
        )["ledger"][-1]["etp_elapsed_mm"]
        self.assertGreater(apres, avant, "une coupure de 6 h n'a pas été rattrapée")

    def test_horloge_non_monotone_ne_debite_rien(self) -> None:
        # Changement d'heure / resynchro NTP : pas de pas négatif, pas de débit inventé.
        first = self._state_at(previous_state=None, hour=14, rate=0.5)
        backwards = self._state_at(previous_state=first, hour=13, rate=0.5)
        self.assertAlmostEqual(
            backwards["ledger"][-1]["etp_elapsed_mm"],
            first["ledger"][-1]["etp_elapsed_mm"],
            places=3,
        )

    def test_accumulation_plafonnee(self) -> None:
        # Un taux aberrant ne peut pas drainer la réserve au-delà du plafond physique journalier.
        state = self._state_at(previous_state=None, hour=6, rate=99.0, etp=8.0, fraction=0.1)
        for hour in (8, 10, 12, 14, 16, 18):
            state = self._state_at(previous_state=state, hour=hour, rate=99.0, etp=8.0, fraction=0.1)
        self.assertLessEqual(state["ledger"][-1]["etp_elapsed_mm"], soil_balance.ETP_DAILY_CAP_MM)

    def test_cloture_de_la_veille_utilise_l_et_accumulee(self) -> None:
        # La veille se clôture sur l'ET RÉELLEMENT accumulée (mesurée), pas sur l'estimation
        # journalière — c'est tout l'intérêt de la bascule.
        # Taux abaissé à 0,3 mm/h : la journée va maintenant jusqu'à 23:58, et l'intégration
        # doit rester SOUS l'estimation journalière pour que l'assertion ci-dessous morde.
        veille = self._state_at(previous_state=None, hour=12, rate=0.3, etp=9.0, fraction=0.4)
        # Pas de 2 h (borne d'intégration) : au-delà, un « trou » déclencherait la
        # resynchronisation sur le prorata, ce que couvre test_une_coupure_longue_*.
        # ⚠️ On va jusqu'à 23:58 : depuis le 01/09/2026, le filet de clôture juge la COUVERTURE
        # de la veille (`etp_last_ts`) et non l'ampleur de l'ET. Une journée qui s'arrête à 20 h
        # est réellement tronquée — c'est le cas couvert par le test suivant.
        for _hour in (14, 16, 18, 20, 22):
            veille = self._state_at(previous_state=veille, hour=_hour, rate=0.3, etp=9.0, fraction=1.0)
        veille = self._state_at(previous_state=veille, hour=23, minute=58, rate=0.3, etp=9.0, fraction=1.0)
        entry_veille = veille["ledger"][-1]
        ouverture = entry_veille["previous_reserve_mm"]
        accumulee = entry_veille["etp_elapsed_mm"]
        self.assertLess(accumulee, 9.0)  # l'accumulation mesurée reste sous l'estimation

        lendemain = soil_balance.update_soil_balance(
            previous_state=veille,
            today=date(2026, 7, 29),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=9.0,
            type_sol="limoneux",
            et_elapsed_fraction=0.0,
            etc_hourly_mm_h=0.0,
            now=datetime(2026, 7, 29, 1, 0, tzinfo=self.TZ),
        )
        attendu = max(0.0, ouverture - accumulee)
        self.assertAlmostEqual(lendemain["ledger"][-1]["previous_reserve_mm"], attendu, places=1)


    def test_une_journee_pluvieuse_mais_complete_garde_sa_mesure(self) -> None:
        """⚠️ DÉFAUT MESURÉ SUR LE REGISTRE RÉEL, corrigé le 01/09/2026.

        Le filet de clôture jugeait sur l'AMPLEUR : « une journée couverte accumule au moins la
        moitié de l'estimation ». Faux les jours de pluie, où la mesure vaut légitimement 38 à
        47 % de la prévision. Relevé sur l'installation :

            28/08  mesurée 2,388  estimée 5,1  → jetée
            29/08  mesurée 1,085  estimée 3,4  → jetée
            30/08  mesurée 1,339  estimée 2,9  → jetée

        …alors que les trois journées avaient tourné jusqu'à 23:58, 23:59 et 23:59. Six
        millimètres débités en trop en trois jours, et jamais dans l'autre sens.
        """
        # Journée pluvieuse : taux horaire faible, estimation journalière haute.
        veille = self._state_at(previous_state=None, hour=6, rate=0.05, etp=9.0, fraction=0.0)
        for _hour in (8, 10, 12, 14, 16, 18, 20, 22):
            veille = self._state_at(previous_state=veille, hour=_hour, rate=0.05, etp=9.0, fraction=0.0)
        veille = self._state_at(previous_state=veille, hour=23, minute=58, rate=0.05, etp=9.0, fraction=0.0)
        entree = veille["ledger"][-1]
        accumulee = entree["etp_elapsed_mm"]
        ouverture = entree["previous_reserve_mm"]
        self.assertLess(accumulee, 9.0 * 0.5,
                        "le montage doit produire une mesure SOUS l'ancien seuil, sinon il ne mord pas")

        lendemain = soil_balance.update_soil_balance(
            previous_state=veille, today=date(2026, 7, 29),
            pluie_mm=0.0, arrosage_mm=0.0, etp_mm=9.0, type_sol="limoneux",
            et_elapsed_fraction=0.0, etc_hourly_mm_h=0.0,
            now=datetime(2026, 7, 29, 1, 0, tzinfo=self.TZ),
        )
        self.assertAlmostEqual(lendemain["ledger"][-1]["previous_reserve_mm"],
                               max(0.0, ouverture - accumulee), places=1,
                               msg="la mesure d'une journée COMPLÈTE a été remplacée par l'estimation")

    def test_une_journee_tronquee_retombe_sur_l_estimation(self) -> None:
        """Le filet garde sa raison d'être : Home Assistant arrêté avant minuit.

        Sans lui, le cumul amputé laisserait de l'eau FANTÔME dans la réserve d'ouverture,
        définitivement. C'est la COUVERTURE qui le dit désormais, pas l'ampleur de l'ET.
        """
        veille = self._state_at(previous_state=None, hour=6, rate=0.05, etp=9.0, fraction=0.0)
        for _hour in (8, 10, 12):
            veille = self._state_at(previous_state=veille, hour=_hour, rate=0.05, etp=9.0, fraction=0.0)
        entree = veille["ledger"][-1]          # dernier cumul à 12 h : 12 h manquantes
        ouverture = entree["previous_reserve_mm"]

        lendemain = soil_balance.update_soil_balance(
            previous_state=veille, today=date(2026, 7, 29),
            pluie_mm=0.0, arrosage_mm=0.0, etp_mm=9.0, type_sol="limoneux",
            et_elapsed_fraction=0.0, etc_hourly_mm_h=0.0,
            now=datetime(2026, 7, 29, 1, 0, tzinfo=self.TZ),
        )
        self.assertAlmostEqual(lendemain["ledger"][-1]["previous_reserve_mm"],
                               max(0.0, ouverture - 9.0), places=1,
                               msg="une journée arrêtée à midi a été clôturée sur sa mesure amputée")


    def test_un_horodatage_illisible_ne_desarme_pas_le_filet(self) -> None:
        """⚠️ Une absence n'est pas une preuve de couverture.

        Sans horodatage exploitable, on ne SAIT pas jusqu'où la veille a tourné : on retient
        l'estimation pleine journée, comportement prudent d'avant le correctif. Le trou avait
        été trouvé par le banc de mutations, pas par les tests.
        """
        for horodatage in (None, "", "pas-une-date", 12345):
            with self.subTest(horodatage=horodatage):
                veille = self._state_at(previous_state=None, hour=23, minute=58,
                                        rate=0.05, etp=9.0, fraction=0.0)
                entree = veille["ledger"][-1]
                ouverture = entree["previous_reserve_mm"]
                entree["etp_last_ts"] = horodatage      # horodatage perdu / corrompu

                lendemain = soil_balance.update_soil_balance(
                    previous_state=veille, today=date(2026, 7, 29),
                    pluie_mm=0.0, arrosage_mm=0.0, etp_mm=9.0, type_sol="limoneux",
                    et_elapsed_fraction=0.0, etc_hourly_mm_h=0.0,
                    now=datetime(2026, 7, 29, 1, 0, tzinfo=self.TZ),
                )
                self.assertAlmostEqual(
                    lendemain["ledger"][-1]["previous_reserve_mm"],
                    max(0.0, ouverture - 9.0), places=1,
                    msg="sans horodatage, la journée a été réputée couverte",
                )


class RaccordDuRegistreTests(unittest.TestCase):
    """⚠️ QUATRE RUPTURES SILENCIEUSES PENDANT UNE SEMAINE — trouvées à la main le 04/09/2026.

    Contrôle des 119 raccords du registre : les 22→23, 28→29, 29→30 et 30→31/08 étaient rompus,
    chacun d'exactement `etp_elapsed_mm − etp_mm` — la signature de l'ancien garde de clôture
    qui remplaçait la mesure par l'estimation. **5,9 mm** encore effectifs, et un arrosage
    déclenché sur cette erreur de comptabilité. Rien ne l'avait signalé.

    La cause est corrigée depuis la 0.63.0. Ce garde-ci ne la corrige pas : il détecte la
    SUIVANTE, quelle qu'elle soit.
    """

    def _veille(self, *, ouverture, pluie, etc_estimee, etc_mesuree, cloture, couverte=True):
        """Journée d'hier, telle qu'elle est stockée au registre."""
        entree = {
            "date": "2026-08-30",
            "previous_reserve_mm": ouverture,
            "pluie_mm": pluie,
            "arrosage_mm": 0.0,
            "etp_mm": etc_estimee,
            "etp_elapsed_mm": etc_mesuree,
            "etp_hourly": True,
            "reserve_mm": cloture,
            "type_sol": "limoneux",
        }
        entree["etp_last_ts"] = (
            "2026-08-30T23:59:49+02:00" if couverte else "2026-08-30T12:00:00+02:00"
        )
        return entree

    def _basculer(self, veille):
        """Passe au lendemain — c'est la bascule de date qui recalcule la clôture."""
        etat = {
            "date": "2026-08-30",
            "reserve_mm": veille["reserve_mm"],
            "previous_reserve_mm": veille["previous_reserve_mm"],
            "type_sol": "limoneux",
            "reserve_min_mm": 0.0,
            "reserve_max_mm": 24.0,
            "ledger": [veille],
        }
        return soil_balance.update_soil_balance(
            etat, today=date(2026, 8, 31), pluie_mm=0.0, arrosage_mm=0.0, etp_mm=3.5,
            type_sol="limoneux", et_elapsed_fraction=0.0,
        )

    def test_un_raccord_ROMPU_est_signale(self) -> None:
        """La rupture RÉELLE du 30→31/08, rejouée telle quelle.

        Ouverture 19,8 · pluie 3,6 · ETc mesurée 1,339 → clôture 22,1 (ce qui est stocké).
        L'ancien garde clôturait sur l'estimation 2,9 → réouverture à 20,5. Écart −1,6 mm.
        """
        rompu = self._veille(ouverture=19.8, pluie=3.6, etc_estimee=2.9,
                             etc_mesuree=1.339, cloture=22.1)
        # On force la clôture recalculée à diverger, comme le faisait l'ancien garde.
        rompu["etp_elapsed_mm"] = 2.9
        etat = self._basculer(rompu)
        ecart = etat.get("ecart_raccord_mm")
        self.assertIsNotNone(ecart, "un raccord rompu n'est pas signalé : le défaut reste muet")
        self.assertAlmostEqual(ecart, -1.6, places=1)

    def test_un_raccord_SAIN_ne_signale_rien(self) -> None:
        """L'autre sens, et il compte : une alerte qui crie tous les jours ne sert à rien.

        C'est le cas des quatre raccords du 31/08 au 04/09, tous propres depuis la 0.63.0.
        """
        sain = self._veille(ouverture=19.8, pluie=3.6, etc_estimee=2.9,
                            etc_mesuree=1.339, cloture=22.1)
        self.assertIsNone(self._basculer(sain).get("ecart_raccord_mm"))

    def test_une_journee_TRONQUEE_n_est_pas_une_rupture(self) -> None:
        """⚠️ Sur une journée arrêtée avant minuit, la clôture retombe VOLONTAIREMENT sur
        l'estimation : l'écart est délibéré, pas un défaut. Crier là-dessus rendrait l'alerte
        inutilisable — c'est exactement le piège dans lequel l'ancien garde était tombé, en
        jugeant l'ampleur au lieu de la couverture."""
        tronquee = self._veille(ouverture=19.8, pluie=3.6, etc_estimee=2.9,
                                etc_mesuree=1.339, cloture=22.1, couverte=False)
        self.assertIsNone(self._basculer(tronquee).get("ecart_raccord_mm"),
                          "une journée tronquée est signalée comme une rupture")

    def test_un_ecart_SOUS_la_tolerance_ne_crie_pas(self) -> None:
        """Les deux valeurs sont arrondies au dixième : un double arrondi peut produire 0,1."""
        limite = self._veille(ouverture=19.8, pluie=3.6, etc_estimee=2.9,
                              etc_mesuree=1.339, cloture=22.2)
        self.assertIsNone(self._basculer(limite).get("ecart_raccord_mm"))

    def test_l_ecart_SURVIT_aux_cycles_de_la_journee(self) -> None:
        """⚠️ Sans report, l'alerte disparaîtrait deux minutes après avoir été détectée — aussi
        silencieuse que le défaut qu'elle surveille. Le coordinateur tourne toutes les 2 min."""
        rompu = self._veille(ouverture=19.8, pluie=3.6, etc_estimee=2.9,
                             etc_mesuree=1.339, cloture=22.1)
        rompu["etp_elapsed_mm"] = 2.9
        etat = self._basculer(rompu)
        self.assertIsNotNone(etat.get("ecart_raccord_mm"), "prémisse")
        # Second cycle du MÊME jour : rien ne bascule, mais l'écart doit tenir.
        encore = soil_balance.update_soil_balance(
            etat, today=date(2026, 8, 31), pluie_mm=0.0, arrosage_mm=0.0, etp_mm=3.5,
            type_sol="limoneux", et_elapsed_fraction=0.2,
        )
        self.assertAlmostEqual(encore.get("ecart_raccord_mm"), -1.6, places=1,
                               msg="l'alerte s'efface au cycle suivant")


class BiaisEtcMesureTests(unittest.TestCase):
    """⚠️ DEUX ETc DU MÊME JOUR, 31 à 35 % D'ÉCART — mesuré sur l'installation.

    Le ledger débite l'intégrale du taux HORAIRE mesuré ; la projection d'aube qui décide du
    déclenchement utilisait le modèle journalier ET0 × Kc. Relevé à 23:59, journées complètes :

        02/09   mesurée 2,991 mm   estimée 4,6 mm   → 0,65
        03/09   mesurée 2,886 mm   estimée 4,2 mm   → 0,69

    Arbitré par Kévin le 04/09/2026 : aligner la projection sur la mesure.
    """

    def _jour(self, date_str, estimee, mesuree, *, derniere_heure="23:59:30"):
        return {
            "date": date_str,
            "etp_mm": estimee,
            "etp_elapsed_mm": mesuree,
            "etp_last_ts": f"{date_str}T{derniere_heure}+02:00",
        }

    def test_le_biais_reprend_les_deux_journees_reelles(self) -> None:
        ledger = [
            self._jour("2026-09-01", 3.8, 2.766),
            self._jour("2026-09-02", 4.6, 2.991),
            self._jour("2026-09-03", 4.2, 2.886),
        ]
        biais = soil_balance.biais_etc_mesure(ledger)
        self.assertIsNotNone(biais)
        # médiane de 0,728 · 0,650 · 0,687
        self.assertAlmostEqual(biais, 0.687, places=2)

    def test_une_journee_TRONQUEE_ne_compte_pas(self) -> None:
        """⚠️ Une journée arrêtée à midi a une mesure amputée : son rapport serait
        artificiellement bas et tirerait la correction vers le sens dangereux. On réutilise le
        prédicat de clôture, pas une seconde définition de « journée complète »."""
        complets = [
            self._jour("2026-09-01", 4.0, 2.8),
            self._jour("2026-09-02", 4.0, 2.8),
            self._jour("2026-09-03", 4.0, 2.8),
        ]
        self.assertAlmostEqual(soil_balance.biais_etc_mesure(complets), 0.7, places=2)

        # ⚠️ TROIS journées tronquées, et les plus RÉCENTES : une seule ne déplacerait pas la
        # médiane, et le test serait vert sans rien exercer — le banc l'a montré.
        # Sans le filtre, la médiane de [0,1 · 0,1 · 0,1 · 0,7 · 0,7 · 0,7] tombe à 0,4, puis
        # au plancher de 0,5. Avec le filtre, elle reste à 0,7.
        avec_tronquees = complets + [
            self._jour(f"2026-09-0{4 + i}", 4.0, 0.4, derniere_heure="12:00:00")
            for i in range(3)
        ]
        self.assertAlmostEqual(
            soil_balance.biais_etc_mesure(avec_tronquees), 0.7, places=2,
            msg="des journées tronquées sont entrées dans la correction",
        )

    def test_moins_de_trois_journees_rend_None(self) -> None:
        """Une correction apprise sur deux points est une opinion. Le modèle seul reprend
        la main — le comportement d'avant, sans surprise."""
        for n in (0, 1, 2):
            with self.subTest(jours=n):
                ledger = [self._jour(f"2026-09-0{i + 1}", 4.0, 2.8) for i in range(n)]
                self.assertIsNone(soil_balance.biais_etc_mesure(ledger))

    def test_les_bornes_protegent_du_sens_DANGEREUX(self) -> None:
        """⚠️ Bornes asymétriques, et c'est le cœur du garde-fou.

        Plafond 1,0 : le biais ne peut que RÉDUIRE la projection, jamais la gonfler — le modèle
        seul reste la borne prudente. Plancher 0,5 : un rapport aberrant ne peut pas effondrer
        la soif projetée et retarder un arrosage nécessaire.
        """
        effondre = [self._jour(f"2026-09-0{i + 1}", 4.0, 0.2) for i in range(3)]
        self.assertAlmostEqual(soil_balance.biais_etc_mesure(effondre), 0.5, places=3,
                               msg="un rapport aberrant peut retarder un arrosage nécessaire")
        gonfle = [self._jour(f"2026-09-0{i + 1}", 2.0, 6.0) for i in range(3)]
        self.assertAlmostEqual(soil_balance.biais_etc_mesure(gonfle), 1.0, places=3,
                               msg="le biais gonfle la projection au-dessus du modèle")

    def test_la_mediane_resiste_a_une_journee_aberrante(self) -> None:
        ledger = [
            self._jour("2026-09-01", 4.0, 2.8),
            self._jour("2026-09-02", 4.0, 0.1),   # journée de pluie, mesure très basse
            self._jour("2026-09-03", 4.0, 2.8),
        ]
        self.assertAlmostEqual(soil_balance.biais_etc_mesure(ledger), 0.7, places=2,
                               msg="une seule journée aberrante déplace la correction")

    def test_une_estimation_absente_ou_nulle_est_ignoree(self) -> None:
        ledger = [
            self._jour("2026-08-30", None, 2.8),
            self._jour("2026-08-31", 0.0, 2.8),
            self._jour("2026-09-01", 4.0, 2.8),
            self._jour("2026-09-02", 4.0, 2.8),
            self._jour("2026-09-03", 4.0, None),
        ]
        self.assertIsNone(soil_balance.biais_etc_mesure(ledger),
                          "des entrées inexploitables ont été comptées comme des journées")

    def test_un_registre_absent_ou_abime_ne_casse_rien(self) -> None:
        for ledger in (None, [], "pas une liste", [None, 3, "x"]):
            with self.subTest(ledger=type(ledger).__name__):
                self.assertIsNone(soil_balance.biais_etc_mesure(ledger))


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

    def test_et0_debitee_au_prorata_de_la_journee(self) -> None:
        # Anti « falaise de minuit » ET anti sur-arrosage : l'ET0 du jour est débitée AU PRORATA de
        # la journée écoulée, pas en totalité dès 00h01. Sinon la réserve tombe à 0 au petit matin
        # (et se fait écraser au plancher, information perdue) : le pilotage commande alors une
        # recharge pleine sur un sol encore rempli — constaté en réel 07/2026, ~59 mm appliqués sur
        # 7 jours pour un besoin ETc de ~33 mm.
        commun = dict(
            previous_state=None,
            today=date(2026, 7, 24),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=8.0,
            type_sol="limoneux",
        )

        minuit = soil_balance.update_soil_balance(**commun, et_elapsed_fraction=0.0)
        midi = soil_balance.update_soil_balance(**commun, et_elapsed_fraction=0.5)
        soir = soil_balance.update_soil_balance(**commun, et_elapsed_fraction=1.0)

        # Réserve d'ouverture limoneux = 12 mm. À minuit rien n'est encore évaporé.
        self.assertEqual(minuit["reserve_mm"], 12.0)
        self.assertEqual(midi["reserve_mm"], 8.0)  # 12 − 8 × 0,5
        self.assertEqual(soir["reserve_mm"], 4.0)  # 12 − 8 × 1,0 : total du jour inchangé
        # `etp_mm` reste l'ET0 PLEINE JOURNÉE (pic du jour + clôture de la veille en dépendent).
        self.assertEqual(minuit["etp_mm"], 8.0)
        self.assertEqual(soir["etp_mm"], 8.0)

    def test_cloture_de_la_veille_debite_l_et0_entiere(self) -> None:
        # Si Home Assistant s'arrête avant le coucher du soleil, la dernière écriture de la veille
        # ne contient qu'une FRACTION de son ET0. Au changement de jour on doit rouvrir sur le
        # solde de clôture réel (ET0 pleine journée), sinon l'erreur se propage de jour en jour.
        veille = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 7, 24),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=8.0,
            type_sol="limoneux",
            et_elapsed_fraction=0.25,  # HA coupé en début de journée
        )
        self.assertEqual(veille["reserve_mm"], 10.0)  # 12 − 8 × 0,25 : valeur partielle

        lendemain = soil_balance.update_soil_balance(
            previous_state=veille,
            today=date(2026, 7, 25),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=6.0,
            type_sol="limoneux",
            et_elapsed_fraction=0.0,
        )

        # La veille est clôturée à 12 − 8 = 4 mm (ET0 ENTIÈRE), et non aux 10 mm partiels.
        self.assertEqual(lendemain["previous_reserve_mm"], 4.0)
        self.assertEqual(lendemain["reserve_mm"], 4.0)  # rien d'évaporé encore le lendemain

    def test_entree_du_jour_sans_reserve_douverture_ne_casse_pas_le_bilan(self) -> None:
        # Une entrée du jour peut arriver sans `previous_reserve_mm` : ledger hérité d'une version
        # antérieure à cette clé, ou `.storage` retouché. Le calcul levait alors un TypeError
        # (None + float) et le bilan sol s'arrêtait à chaque cycle sans rien dire.
        state = {
            "ledger": [
                {"date": "2026-07-28", "reserve_mm": 9.0, "previous_reserve_mm": 12.0, "etp_mm": 3.0},
                {"date": "2026-07-29", "reserve_mm": 6.0, "etp_mm": 3.0},  # ouverture manquante
            ]
        }

        result = soil_balance.update_soil_balance(
            previous_state=state,
            today=date(2026, 7, 29),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=4.0,
            type_sol="limoneux",
        )

        # Repli sur la CLÔTURE DE LA VEILLE (9 mm), pas sur la réserve de fin de journée du jour
        # même (6 mm) qui aurait fait perdre l'ET0 déjà débitée.
        self.assertEqual(result["previous_reserve_mm"], 9.0)
        self.assertEqual(result["reserve_mm"], 5.0)  # 9 − 4

    def test_entree_du_jour_orpheline_repli_sur_la_reserve_de_base(self) -> None:
        # Même cas, mais sans veille exploitable : on doit retomber sur la réserve de base du sol
        # plutôt que de planter.
        state = {"ledger": [{"date": "2026-07-29", "reserve_mm": 6.0, "etp_mm": 3.0}]}

        result = soil_balance.update_soil_balance(
            previous_state=state,
            today=date(2026, 7, 29),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=2.0,
            type_sol="limoneux",
        )

        self.assertEqual(result["previous_reserve_mm"], soil_balance.base_reserve_mm("limoneux"))

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


class RecalageSansGelDeLaJourneeTests(unittest.TestCase):
    """`freeze_day=False` corrige la réserve SANS figer la journée.

    L'ancre historique (`freeze_day=True`) arrête tout le calcul du jour : ni ET débitée, ni
    pluie ou arrosage crédités, jauge immobile. C'est voulu pour « j'ai sondé mon sol ce soir ».
    Pour corriger une comptabilité faussée en cours de journée, il faut l'inverse.
    """

    def test_le_gel_reste_le_defaut(self) -> None:
        # Non-régression : l'usage historique ne change pas.
        state = soil_balance.set_reserve_mm(None, 8.0, today=date(2026, 7, 29), type_sol="limoneux")
        self.assertTrue(state["ledger"][-1].get("manual_anchor"))

    def test_sans_gel_aucune_ancre_posee(self) -> None:
        state = soil_balance.set_reserve_mm(
            None, 7.5, today=date(2026, 7, 29), type_sol="limoneux", freeze_day=False
        )
        self.assertNotIn("manual_anchor", state["ledger"][-1])

    def test_sans_gel_la_journee_continue_de_se_calculer(self) -> None:
        # LE point : après un recalage sans gel, l'ET du jour doit de nouveau être débitée.
        recale = soil_balance.set_reserve_mm(
            None, 7.5, today=date(2026, 7, 29), type_sol="limoneux", freeze_day=False
        )

        suite = soil_balance.update_soil_balance(
            previous_state=recale,
            today=date(2026, 7, 29),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=6.0,
            type_sol="limoneux",
            et_elapsed_fraction=0.5,  # mi-journée
        )

        self.assertEqual(suite["previous_reserve_mm"], 7.5)
        self.assertEqual(suite["reserve_mm"], 4.5)  # 7,5 − 6 × 0,5

    def test_avec_gel_la_journee_reste_immobile(self) -> None:
        # Le miroir : avec l'ancre, la même ET ne bouge rien.
        ancre = soil_balance.set_reserve_mm(
            None, 7.5, today=date(2026, 7, 29), type_sol="limoneux", freeze_day=True
        )

        suite = soil_balance.update_soil_balance(
            previous_state=ancre,
            today=date(2026, 7, 29),
            pluie_mm=0.0,
            arrosage_mm=0.0,
            etp_mm=6.0,
            type_sol="limoneux",
            et_elapsed_fraction=0.5,
        )

        self.assertEqual(suite["reserve_mm"], 7.5)

    def test_sans_gel_en_cours_de_journee_preserve_ce_qui_a_deja_coule(self) -> None:
        # Si 3 mm ont déjà été débités et qu'on demande 7,5, la réserve COURANTE doit valoir 7,5
        # — donc l'ouverture doit remonter à 10,5, sinon la correction serait mangée aussitôt.
        state = {
            "ledger": [
                {
                    "date": "2026-07-29",
                    "previous_reserve_mm": 12.0,
                    "pluie_mm": 0.0,
                    "arrosage_mm": 0.0,
                    "etp_mm": 6.0,
                    "etp_elapsed_mm": 3.0,
                    "etp_hourly": True,
                    "reserve_mm": 9.0,
                }
            ]
        }

        recale = soil_balance.set_reserve_mm(
            state, 7.5, today=date(2026, 7, 29), type_sol="limoneux", freeze_day=False
        )

        self.assertEqual(recale["reserve_mm"], 7.5)
        self.assertEqual(recale["previous_reserve_mm"], 10.5)  # 7,5 + 3 déjà évaporés


class MarqueursSuspectsSurvivantsTests(unittest.TestCase):
    """Les drapeaux de relevé aberrant doivent SURVIVRE à la normalisation.

    `normalize_soil_balance_state` tourne au début de CHAQUE `update_soil_balance`, pas seulement
    au rechargement : une clé absente de la liste blanche disparaît donc au cycle suivant, soit
    ~2 minutes plus tard. Le test historique ne vérifiait que l'état frais et ne pouvait pas le voir.
    """

    def test_pluie_suspecte_survit_au_cycle_suivant(self) -> None:
        veille = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 7, 20),
            pluie_mm=250.0,  # aberrant → écrêté et marqué
            arrosage_mm=0.0,
            etp_mm=4.0,
            type_sol="limoneux",
        )
        self.assertTrue(veille["ledger"][-1].get("pluie_suspect"))

        # Un simple passage de normalisation (ce que fait tout cycle suivant) doit le conserver.
        renormalise = soil_balance.normalize_soil_balance_state(veille)
        self.assertTrue(
            renormalise["ledger"][-1].get("pluie_suspect"),
            "le marqueur disparaissait au cycle suivant",
        )

    def test_arrosage_suspect_survit_au_cycle_suivant(self) -> None:
        etat = soil_balance.update_soil_balance(
            previous_state=None,
            today=date(2026, 7, 20),
            pluie_mm=0.0,
            arrosage_mm=120.0,  # aberrant
            etp_mm=4.0,
            type_sol="limoneux",
        )
        self.assertTrue(etat["ledger"][-1].get("arrosage_suspect"))
        self.assertTrue(soil_balance.normalize_soil_balance_state(etat)["ledger"][-1].get("arrosage_suspect"))


class LeCliquetIntraJourneeDuPluviometreTests(unittest.TestCase):
    """Le pluviomètre journalier BAISSE en cours de journée, et la réserve le suivait.

    Mesuré le 04/08/2026 sur `sensor.meteo_netatmo_precipitation_aujourd_hui` — dix baisses :

        00:48 1,0 → 03:11 2,6 → 04:08 2,5 → 04:20 3,5 → 04:44 2,7 → 17:17 4,2
              → 19:08 3,4 → 20:11 4,0 → 21:50 2,9 → 23:52 3,1

    La réserve suivait pas pour pas : 21:33→21:50, réserve 9,8 → 8,9 pour un pluviomètre
    3,8 → 2,9, pendant que l'ET0 horaire valait 0,04 mm/h — 90 fois moins. Le ledger retenait
    la DERNIÈRE lecture (3,1) quand le maximum du jour valait 4,2 : **1,1 mm réellement tombé
    n'entrait jamais au bilan**, un jour de rattrapage.
    """

    TZ = timezone.utc
    JOUR = date(2026, 8, 4)

    def _cycle(self, etat, pluie, heure, minute=0):
        return soil_balance.update_soil_balance(
            previous_state=etat,
            today=self.JOUR,
            pluie_mm=pluie,
            arrosage_mm=0.0,
            etp_mm=4.0,
            type_sol="limoneux",
            now=datetime(2026, 8, 4, heure, minute, tzinfo=self.TZ),
        )

    # Séquence réelle du 04/08/2026.
    RELEVES = [
        (0, 48, 1.0), (3, 11, 2.6), (4, 8, 2.5), (4, 20, 3.5), (4, 44, 2.7),
        (17, 17, 4.2), (19, 8, 3.4), (20, 11, 4.0), (21, 50, 2.9), (23, 52, 3.1),
    ]

    def test_le_maximum_du_jour_est_retenu_et_non_la_derniere_lecture(self) -> None:
        etat = None
        for h, m, pluie in self.RELEVES:
            etat = self._cycle(etat, pluie, h, m)
        self.assertAlmostEqual(
            etat["pluie_mm"], 4.2, places=1,
            msg="le bilan retient encore la dernière lecture — 1,1 mm perdus",
        )

    def test_sans_cliquet_le_bilan_perdrait_bien_ces_millimetres(self) -> None:
        """PRÉMISSE : la dernière lecture vaut réellement moins que le maximum."""
        self.assertLess(self.RELEVES[-1][2], max(p for _, _, p in self.RELEVES))
        self.assertAlmostEqual(max(p for _, _, p in self.RELEVES) - self.RELEVES[-1][2], 1.1, places=1)

    def test_une_remise_a_zero_relache_le_cliquet(self) -> None:
        """Le capteur reboucle plusieurs dizaines de minutes après minuit local.

        C'est l'objection qui avait fait refuser un `max()` nu : sans relâchement, le cumul de
        la veille resterait figé toute la journée. On détecte donc la CHUTE VERS ZÉRO, pas
        l'heure.
        """
        etat = self._cycle(None, 4.2, 0, 2)      # entrée créée avec le cumul de la veille
        etat = self._cycle(etat, 0.0, 0, 42)     # le Netatmo reboucle
        self.assertAlmostEqual(etat["pluie_mm"], 0.0, places=1,
                               msg="le cumul de la veille est resté figé")
        etat = self._cycle(etat, 1.4, 9, 0)      # la vraie pluie du jour
        self.assertAlmostEqual(etat["pluie_mm"], 1.4, places=1)

    def test_un_decrochage_vers_une_valeur_non_nulle_est_ignore(self) -> None:
        etat = self._cycle(None, 3.8, 21, 33)
        etat = self._cycle(etat, 2.9, 21, 50)    # le décrochage mesuré à 21:50
        self.assertAlmostEqual(etat["pluie_mm"], 3.8, places=1)

    def test_une_journee_qui_monte_normalement_n_est_pas_affectee(self) -> None:
        """Garde-fou inverse : le cliquet ne doit rien changer au cas nominal."""
        etat = None
        for h, pluie in ((6, 0.0), (9, 1.2), (14, 3.0), (20, 5.5)):
            etat = self._cycle(etat, pluie, h)
        self.assertAlmostEqual(etat["pluie_mm"], 5.5, places=1)

    def test_le_pic_survit_a_la_normalisation_du_state(self) -> None:
        """LISTE BLANCHE : une clé absente est perdue à chaque cycle et au rechargement."""
        etat = self._cycle(None, 4.2, 17, 17)
        recharge = soil_balance.normalize_soil_balance_state(etat)
        self.assertIn("pluie_pic_mm", recharge["ledger"][-1],
                      "le pic est perdu au rechargement : le cliquet n'a plus de mémoire")
        # …et il tient encore après le rechargement.
        apres = self._cycle(recharge, 2.9, 21, 50)
        self.assertAlmostEqual(apres["pluie_mm"], 4.2, places=1)


class RemiseAZeroDuPluviometreTests(unittest.TestCase):
    """Une remise à zéro est une chute VERS ZÉRO — pas simplement « sous 0,5 mm ».

    ⚠️ DÉFAUT MESURÉ LE 29/08/2026, introduit par le cliquet lui-même (0.54.2). Journée de
    bruine, cumul du jour à 0,4 mm :

        09:00  0,3    10:17  0,4 (pic)    11:23  0,2 ↓    12:23  0,4 ↑

    L'ancien test — `lecture ≤ max(0,5 ; pic/2)` ET `lecture ≤ 0,5` — était vrai pour
    0,2 avec un pic à 0,4. Le cliquet croyait le compteur rebouclé, se recalait sur 0,2, et
    la remontée à 0,4 devenait une NOUVELLE averse : `pluie_mesuree_active` s'est allumé sur
    une pluie qui n'a jamais eu lieu. Le commentaire disait « chute vers ~0 » ; le code
    disait « sous 0,5 » — ce n'est pas la même chose quand la journée entière vaut 0,4.
    """

    def _cliquet(self, lecture, pic):
        return soil_balance.appliquer_cliquet_pluie(lecture, pic)

    def test_la_bruine_du_29_aout_n_invente_plus_de_pluie(self) -> None:
        retenue, pic, remise = self._cliquet(0.2, 0.4)
        self.assertFalse(remise, "0,2 sous un pic de 0,4 n'est pas une remise à zéro")
        self.assertEqual(pic, 0.4, "le pic du jour doit tenir")
        self.assertEqual(retenue, 0.4, "la valeur retenue reste le maximum")
        # Et la remontée qui suit ne doit pas franchir le pic, donc ne rien signaler.
        _retenue2, pic2, remise2 = self._cliquet(0.4, pic)
        self.assertFalse(remise2)
        self.assertEqual(pic2, 0.4, "retour au pic : aucune hausse nouvelle")

    def test_une_chute_vers_zero_reste_une_remise_a_zero(self) -> None:
        """La forme observée à chaque minuit : 0.0 le 17/08 à 01:39, le 25/08 à 00:04."""
        for pic in (0.4, 3.6, 29.1):
            with self.subTest(pic=pic):
                retenue, nouveau, remise = self._cliquet(0.0, pic)
                self.assertTrue(remise, f"chute 0,0 depuis {pic} : le compteur a rebouclé")
                self.assertEqual((retenue, nouveau), (0.0, 0.0))

    def test_un_redemarrage_sous_la_pluie_reste_detecte(self) -> None:
        """⚠️ Après une grosse journée, un compteur qui repart à 0,3 a bien rebouclé.

        Sans ce bras, un `max()` figerait le cumul de la VEILLE toute la journée — le défaut
        que le commentaire d'origine mettait en garde de réintroduire.
        """
        _retenue, pic, remise = self._cliquet(0.3, 29.1)
        self.assertTrue(remise)
        self.assertEqual(pic, 0.3)

    def test_le_bruit_d_orage_n_est_pas_une_remise_a_zero(self) -> None:
        """Journée du 24/08 : pic 29,1 puis douze oscillations, aucune n'est un reset."""
        for lecture in (25.9, 25.2, 27.0, 26.2, 24.0, 25.0):
            with self.subTest(lecture=lecture):
                retenue, pic, remise = self._cliquet(lecture, 29.1)
                self.assertFalse(remise)
                self.assertEqual((retenue, pic), (29.1, 29.1))

    def test_une_hausse_reste_une_hausse(self) -> None:
        retenue, pic, remise = self._cliquet(4.2, 3.6)
        self.assertFalse(remise)
        self.assertEqual((retenue, pic), (4.2, 4.2))
