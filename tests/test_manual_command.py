"""Commandes manuelles de la tondeuse : départ, bordure, retour, pause — volet compris.

Un départ est une SÉQUENCE (ouvrir le volet, attendre sa confirmation, puis partir) rejugée à chaque
cycle avec l'état réel. Tant qu'une commande est en cours, le pilote automatique s'efface : c'est le
« mode manuel ». Ici : la machine à états pure ; son branchement dans le pilote et le coordinateur
plus bas.
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
mc = importlib.import_module("custom_components.gazon_intelligent.manual_command")
gg = importlib.import_module("custom_components.gazon_intelligent.garage_guard")

NOW = datetime(2026, 10, 4, 14, 0, tzinfo=timezone.utc)


def _il_y_a(minutes: float) -> str:
    return (NOW - timedelta(minutes=minutes)).isoformat()


def _dans(minutes: float) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat()


def _quai(**maj):
    """Une tondeuse prête, à quai, batterie pleine."""
    instantane = {
        "tondeuse_connectee": True, "tondeuse_prete": True,
        "mower_is_docked": True, "mower_is_outside": False, "mower_is_mowing": False,
        "mower_is_returning": False, "mower_operation_state": "docked", "mower_dock_signal_fort": True,
        "mower_battery": 100, "mower_job_completion_state": "repos",
    }
    instantane.update(maj)
    return instantane


def _dehors(**maj):
    base = dict(mower_is_docked=False, mower_is_outside=True, mower_is_mowing=True,
                mower_operation_state="tonte", mower_dock_signal_fort=False)
    base.update(maj)
    return _quai(**base)


def _valider(commande, snapshot=None, **kw):
    return mc.validate_request(
        commande, snapshot if snapshot is not None else _quai(), state=kw.pop("state", None), now=NOW,
        irrigation_active=kw.pop("irrigation_active", False), edgecut_available=kw.pop("edgecut_available", True),
    )


def _etat(commande="demarrer", *, etape=None, **maj):
    base = mc.new_state(commande, NOW - timedelta(minutes=1), duree_min=maj.pop("duree_min", None))
    if etape:
        base["etape"] = etape
    base.update(maj)
    return base


def _suite(etat, snapshot=None, *, volet="closed", position=0, reglages=None, garage=None, arrosage=False, bordure=True, maintenant=NOW):
    """Un volet est configuré (`cover.garage`) ; `volet` en est l'état lu (None = lecture absente)."""
    return mc.evaluate(
        snapshot if snapshot is not None else _quai(), now=maintenant, state=etat,
        cover_entity="cover.garage", cover_state=volet, cover_position=position,
        settings=reglages or {}, garage_runtime=garage or {}, irrigation_active=arrosage, edgecut_available=bordure,
    )


def _sans_volet(etat, snapshot=None, **kw):
    return mc.evaluate(
        snapshot if snapshot is not None else _quai(), now=kw.pop("maintenant", NOW), state=etat,
        cover_entity=None, cover_state=None, cover_position=None, settings={}, garage_runtime={},
        irrigation_active=kw.pop("arrosage", False), edgecut_available=kw.pop("bordure", True),
    )


class ValidationDeLaDemandeTests(unittest.TestCase):
    def test_une_commande_inconnue_est_refusee(self) -> None:
        self.assertEqual(_valider("tondre_la_haie"), "Commande inconnue.")
        self.assertEqual(_valider(None), "Commande inconnue.")

    def test_une_tondeuse_pas_connectee_ne_recoit_rien(self) -> None:
        for commande in mc.COMMANDES:
            with self.subTest(commande=commande):
                self.assertIn("pas connectée", _valider(commande, _quai(tondeuse_connectee=False)))

    def test_un_depart_a_quai_est_accepte(self) -> None:
        self.assertIsNone(_valider("demarrer"))
        self.assertIsNone(_valider("bordure"))

    def test_un_depart_exige_une_tondeuse_prete(self) -> None:
        for commande in mc.DEPARTS:
            self.assertIn("pas prête", _valider(commande, _quai(tondeuse_prete=False)))

    def test_un_depart_exige_la_tondeuse_a_sa_base(self) -> None:
        dehors = _dehors()
        for commande in mc.DEPARTS:
            with self.subTest(commande=commande):
                self.assertIn("à sa base", _valider(commande, dehors))

    def test_un_depart_est_refuse_batterie_trop_basse(self) -> None:
        self.assertIn("batterie est trop basse", _valider("demarrer", _quai(mower_battery=19)))
        self.assertIsNone(_valider("demarrer", _quai(mower_battery=20)))

    def test_une_batterie_inconnue_ne_bloque_pas_le_depart(self) -> None:
        self.assertIsNone(_valider("demarrer", _quai(mower_battery=None)))

    def test_un_depart_est_refuse_pendant_un_arrosage(self) -> None:
        self.assertIn("arrosage", _valider("demarrer", irrigation_active=True))

    def test_la_bordure_est_refusee_sans_le_service_de_la_tondeuse(self) -> None:
        self.assertIn("bordure n'est pas disponible", _valider("bordure", edgecut_available=False))
        self.assertIsNone(_valider("demarrer", edgecut_available=False))

    def test_un_depart_en_cours_empeche_un_autre_depart(self) -> None:
        en_cours = _etat("demarrer", etape="attente_garage")
        for commande in sorted(mc.DEPARTS):
            self.assertIn("déjà en cours", _valider(commande, state=en_cours))

    def test_retour_et_pause_passent_devant_une_sortie_en_cours(self) -> None:
        """⚠️ Au milieu d'une sortie manuelle, « rentre » et « pause » doivent rester possibles :
        sinon l'utilisateur ne peut plus arrêter ce qu'il a lancé pendant des heures."""
        sortie = _etat("demarrer", etape="dehors", vu_dehors=True)
        self.assertIsNone(_valider("retour", _dehors(), state=sortie))
        self.assertIsNone(_valider("pause", _dehors(), state=sortie))

    def test_une_commande_prioritaire_ne_se_repete_pas(self) -> None:
        for commande in ("retour", "pause"):
            en_cours = _etat(commande, etape="retour_envoye" if commande == "retour" else "pause_envoyee")
            self.assertIn("déjà en cours", _valider(commande, _dehors(), state=en_cours))

    def test_reprendre_exige_une_tondeuse_dehors_et_en_pause(self) -> None:
        self.assertIn("pas dehors", _valider("reprendre"))
        self.assertIn("pas en pause", _valider("reprendre", _dehors()))
        self.assertIsNone(_valider("reprendre", _dehors(mower_job_completion_state="en_pause")))
        pause = _etat("pause", etape="pause_envoyee", envoye_a=_il_y_a(1))
        self.assertIsNone(_valider("reprendre", _dehors(), state=pause))

    def test_demarrer_reste_refuse_pendant_une_pause_manuelle(self) -> None:
        pause = _etat("pause", etape="pause_envoyee", envoye_a=_il_y_a(1))
        self.assertIn("déjà en cours", _valider("demarrer", state=pause))
        self.assertIn("déjà en cours", _valider("bordure", state=pause))

    def test_un_volet_muet_refuse_departs_et_retour_mais_pas_la_pause(self) -> None:
        for commande, snap in (("demarrer", _quai()), ("bordure", _quai()), ("retour", _dehors())):
            with self.subTest(commande=commande):
                self.assertIn("volet ne répond pas", mc.validate_request(
                    commande, snap, state=None, now=NOW, irrigation_active=False, edgecut_available=True, cover_known=False))
        self.assertIsNone(mc.validate_request(
            "pause", _dehors(), state=None, now=NOW, irrigation_active=False, edgecut_available=True, cover_known=False))

    def test_une_commande_terminee_ou_expiree_n_empeche_rien(self) -> None:
        for etape in ("termine", "annule", "erreur", "expire"):
            self.assertIsNone(_valider("demarrer", state=_etat("demarrer", etape=etape)))
        vieille = _etat("demarrer", etape="dehors", jusqu_a=_il_y_a(1))
        self.assertIsNone(_valider("demarrer", state=vieille))

    def test_le_retour_est_refuse_si_la_tondeuse_est_deja_rangee(self) -> None:
        self.assertIn("déjà à sa base", _valider("retour"))
        self.assertIsNone(_valider("retour", _dehors()))

    def test_la_pause_exige_une_tondeuse_dehors(self) -> None:
        self.assertIn("pas dehors", _valider("pause"))
        self.assertIsNone(_valider("pause", _dehors()))

    def test_un_depart_n_exige_pas_de_pilote_actif(self) -> None:
        """La commande est une action explicite : aucune dépendance au mode du pilote."""
        self.assertIsNone(_valider("demarrer"))


class NouvelEtatTests(unittest.TestCase):
    def test_un_depart_commence_par_le_volet(self) -> None:
        for commande in ("demarrer", "bordure", "retour"):
            self.assertEqual(mc.new_state(commande, NOW)["etape"], "ouverture_garage")

    def test_la_pause_commence_directement(self) -> None:
        self.assertEqual(mc.new_state("pause", NOW)["etape"], "pause_envoyee")

    def test_les_durees_du_mode_manuel(self) -> None:
        def _fin(commande, **kw):
            return datetime.fromisoformat(mc.new_state(commande, NOW, **kw)["jusqu_a"]) - NOW
        self.assertEqual(_fin("demarrer"), timedelta(minutes=240))
        self.assertEqual(_fin("retour"), timedelta(minutes=240))
        self.assertEqual(_fin("pause"), timedelta(minutes=60))
        self.assertEqual(_fin("bordure", duree_min=45), timedelta(minutes=45 + 20))

    def test_la_duree_de_bordure_est_bornee_et_a_un_defaut(self) -> None:
        for demande, attendu in ((None, 30), ("x", 30), (5, 10), (10, 10), (45.4, 45), (120, 120), (500, 120), (True, 30)):
            with self.subTest(demande=demande):
                self.assertEqual(mc.edge_duration(demande), attendu)
        self.assertEqual(mc.new_state("bordure", NOW, duree_min=500)["duree_min"], 120)
        self.assertIsNone(mc.new_state("demarrer", NOW)["duree_min"])


class ModeManuelEtSuspensionTests(unittest.TestCase):
    def test_une_commande_en_cours_active_le_mode_manuel(self) -> None:
        for etape in sorted(mc.ACTIVE_STEPS):
            with self.subTest(etape=etape):
                self.assertTrue(mc.is_active(_etat(etape=etape), NOW))

    def test_une_commande_terminee_n_active_pas_le_mode_manuel(self) -> None:
        for etape in sorted(mc.TERMINAL_STEPS):
            self.assertFalse(mc.is_active(_etat(etape=etape), NOW))

    def test_le_mode_manuel_s_arrete_a_l_echeance(self) -> None:
        self.assertTrue(mc.is_active(_etat(etape="dehors", jusqu_a=_dans(1)), NOW))
        self.assertFalse(mc.is_active(_etat(etape="dehors", jusqu_a=_il_y_a(0.1)), NOW))
        self.assertFalse(mc.is_active(_etat(etape="dehors", jusqu_a="pas une date"), NOW))

    def test_sans_etat_pas_de_mode_manuel(self) -> None:
        for etat in (None, {}, "x"):
            self.assertFalse(mc.is_active(etat, NOW))

    def test_la_suspension_des_departs_se_lit_dans_le_registre(self) -> None:
        self.assertTrue(mc.suspension_active({"suspension_jusqu_a": _dans(30)}, NOW))
        self.assertFalse(mc.suspension_active({"suspension_jusqu_a": _il_y_a(1)}, NOW))
        self.assertFalse(mc.suspension_active({"suspension_jusqu_a": None}, NOW))
        self.assertFalse(mc.suspension_active({}, NOW))
        self.assertFalse(mc.suspension_active(None, NOW))


class DepartSansVoletTests(unittest.TestCase):
    def test_le_depart_part_tout_de_suite(self) -> None:
        r = _sans_volet(_etat("demarrer"))
        self.assertEqual(r["action"], {"service": "lawn_mower.start_mowing", "data": {}})
        self.assertEqual(r["etape"], "depart_envoye")
        self.assertEqual(r["updates"]["envoye_a"], NOW.isoformat())

    def test_la_bordure_part_avec_sa_duree(self) -> None:
        r = _sans_volet(_etat("bordure", duree_min=45))
        self.assertEqual(r["action"], {"service": "landroid_cloud.ots", "data": {"boundary": True, "runtime": 45}})

    def test_la_bordure_par_defaut_dure_30_minutes(self) -> None:
        self.assertEqual(_sans_volet(_etat("bordure"))["action"]["data"]["runtime"], 30)

    def test_les_gardes_sont_rejugees_au_moment_d_envoyer(self) -> None:
        cas = {
            "tondeuse indisponible": (_quai(tondeuse_connectee=False), {}),
            "tondeuse pas prête": (_quai(tondeuse_prete=False), {}),
            "sortie de la base": (_dehors(), {}),
            "batterie": (_quai(mower_battery=10), {}),
            "arrosage": (_quai(), {"arrosage": True}),
            "bordure indisponible": (_quai(), {"bordure": False}),
        }
        for nom, (instantane, extra) in cas.items():
            with self.subTest(garde=nom):
                commande = "bordure" if nom == "bordure indisponible" else "demarrer"
                r = _sans_volet(_etat(commande), instantane, **extra)
                self.assertIsNone(r["action"], "aucun ordre ne part quand une garde tombe")
                self.assertEqual(r["etape"], "erreur")
                self.assertTrue(r["finished"])

    def test_un_depart_deja_envoye_n_est_pas_renvoye(self) -> None:
        r = _sans_volet(_etat("demarrer", etape="depart_envoye", envoye_a=_il_y_a(0.5)))
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "depart_envoye")


class DepartAvecVoletTests(unittest.TestCase):
    def test_volet_ferme_on_ouvre_d_abord_et_rien_ne_part(self) -> None:
        r = _suite(_etat("demarrer"), volet="closed", position=0)
        self.assertEqual(r["action"], {"service": "cover.open_cover", "data": {}})
        self.assertEqual(r["etape"], "ouverture_garage")
        self.assertNotIn("envoye_a", r["updates"])

    def test_volet_en_ouverture_on_attend(self) -> None:
        r = _suite(_etat("demarrer", etape="ouverture_garage"), volet="opening", position=40)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "attente_garage")

    def test_volet_ouvert_on_attend_le_delai_de_securite(self) -> None:
        r = _suite(_etat("demarrer", etape="attente_garage"), volet="open", position=100)
        self.assertIsNone(r["action"])
        self.assertEqual(r["updates"]["garage_confirme_a"], NOW.isoformat())
        self.assertIn("délai de sécurité", r["reason"])

    def test_le_depart_part_une_fois_le_delai_ecoule(self) -> None:
        etat = _etat("demarrer", etape="attente_garage", garage_confirme_a=_il_y_a(2.5))
        r = _suite(etat, volet="open", position=100)
        self.assertEqual(r["action"]["service"], "lawn_mower.start_mowing")

    def test_le_delai_n_est_pas_encore_ecoule(self) -> None:
        etat = _etat("demarrer", etape="attente_garage", garage_confirme_a=_il_y_a(1.0))
        r = _suite(etat, volet="open", position=100)
        self.assertIsNone(r["action"])

    def test_le_delai_de_securite_est_celui_du_reglage_du_volet(self) -> None:
        etat = _etat("demarrer", etape="attente_garage", garage_confirme_a=_il_y_a(0.6))
        self.assertIsNone(_suite(etat, volet="open", position=100)["action"])  # défaut : 2 min
        self.assertIsNotNone(_suite(etat, volet="open", position=100, reglages={"tondeuse_garage_avance_ouverture": 0.5})["action"])

    def test_un_volet_ouvert_a_moitie_n_est_pas_confirme(self) -> None:
        r = _suite(_etat("demarrer"), volet="open", position=60)
        self.assertEqual(r["action"], {"service": "cover.open_cover", "data": {}})

    def test_la_position_minimale_est_celle_du_reglage(self) -> None:
        etat = _etat("demarrer", etape="attente_garage", garage_confirme_a=_il_y_a(5))
        r = _suite(etat, volet="open", position=60, reglages={"tondeuse_garage_ouverture_min": 50})
        self.assertEqual(r["action"]["service"], "lawn_mower.start_mowing")

    def test_la_bordure_attend_aussi_le_volet(self) -> None:
        r = _suite(_etat("bordure", duree_min=40), volet="closed", position=0)
        self.assertEqual(r["action"], {"service": "cover.open_cover", "data": {}})
        etat = _etat("bordure", duree_min=40, etape="attente_garage", garage_confirme_a=_il_y_a(3))
        self.assertEqual(
            _suite(etat, volet="open", position=100)["action"],
            {"service": "landroid_cloud.ots", "data": {"boundary": True, "runtime": 40}},
        )

    def test_un_volet_qui_ne_repond_pas_abandonne_le_depart(self) -> None:
        for etat_volet in ("unavailable", "unknown", None):
            with self.subTest(volet=etat_volet):
                r = _suite(_etat("demarrer"), volet=etat_volet)
                self.assertIsNone(r["action"])
                self.assertEqual(r["etape"], "erreur")
                self.assertIn("volet ne répond pas", r["reason"])

    def test_un_volet_pas_ouvert_apres_8_minutes_abandonne_le_depart(self) -> None:
        vieux = mc.new_state("demarrer", NOW - timedelta(minutes=9))
        r = _suite(vieux, volet="closed", position=0)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "erreur")
        self.assertEqual(r["updates"]["erreur"], "volet_non_ouvert")

    def test_l_ordre_d_ouverture_est_retenu_dans_le_delai_de_reprise_du_volet(self) -> None:
        garage = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(0.5), gg.KEY_ATTEMPTS: 1,
                  gg.KEY_SERIES_START: _il_y_a(0.5)}
        r = _suite(_etat("demarrer"), volet="closed", position=0, garage=garage)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "attente_garage")
        self.assertIn("nouvelle tentative", r["reason"])

    def test_un_volet_bloque_apres_le_plafond_abandonne_le_depart(self) -> None:
        garage = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(4), gg.KEY_ATTEMPTS: 3,
                  gg.KEY_SERIES_START: _il_y_a(10)}
        r = _suite(_etat("demarrer"), volet="closed", position=0, garage=garage)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "erreur")
        self.assertEqual(r["updates"]["erreur"], "volet_bloque")

    def test_le_depart_n_est_jamais_envoye_volet_non_confirme(self) -> None:
        """⚠️ L'invariant : aucun `start_mowing` / `ots` tant que le volet n'est pas confirmé ouvert."""
        for volet, position in (("closed", 0), ("closing", 20), ("opening", 50), ("open", 60), ("unavailable", None)):
            for commande in ("demarrer", "bordure"):
                with self.subTest(volet=volet, commande=commande):
                    etat = _etat(commande, etape="attente_garage", garage_confirme_a=_il_y_a(10))
                    r = _suite(etat, volet=volet, position=position)
                    service = (r["action"] or {}).get("service", "")
                    self.assertNotIn(service, ("lawn_mower.start_mowing", "landroid_cloud.ots"))

    def test_apres_l_envoi_on_attend_la_sortie_sans_renvoyer(self) -> None:
        etat = _etat("demarrer", etape="depart_envoye", envoye_a=_il_y_a(1))
        r = _suite(etat, volet="open", position=100)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "depart_envoye")


class SortieEtFinDeLaCommandeTests(unittest.TestCase):
    def test_la_tondeuse_qui_sort_passe_en_dehors(self) -> None:
        etat = _etat("demarrer", etape="depart_envoye", envoye_a=_il_y_a(1))
        r = _suite(etat, _dehors(), volet="open", position=100)
        self.assertEqual(r["etape"], "dehors")
        self.assertIs(r["updates"]["vu_dehors"], True)

    def test_un_depart_sans_sortie_apres_5_minutes_est_signale(self) -> None:
        etat = _etat("demarrer", etape="depart_envoye", envoye_a=_il_y_a(6))
        r = _suite(etat, _quai(), volet="open", position=100)
        self.assertEqual(r["etape"], "erreur")
        self.assertEqual(r["updates"]["erreur"], "depart_non_confirme")
        self.assertTrue(r["finished"])

    def test_pendant_le_travail_le_mode_manuel_tient(self) -> None:
        etat = _etat("demarrer", etape="dehors", vu_dehors=True)
        r = _suite(etat, _dehors(mower_job_completion_state="en_cours"), volet="open", position=100)
        self.assertEqual(r["etape"], "dehors")
        self.assertFalse(r["finished"])

    def test_une_recharge_au_milieu_du_travail_ne_termine_rien(self) -> None:
        """⚠️ La tondeuse rentre se charger 70 min puis repart seule : le pilote ne doit pas reprendre
        la main (il fermerait le volet ou la rappellerait)."""
        etat = _etat("demarrer", etape="dehors", vu_dehors=True)
        for completion in ("en_cours", "en_pause", "sans_mesure"):
            with self.subTest(completion=completion):
                r = _suite(etat, _quai(mower_job_completion_state=completion), volet="open", position=100)
                self.assertEqual(r["etape"], "dehors")
                self.assertFalse(r["finished"])

    def test_le_rebond_de_demarrage_ne_termine_rien(self) -> None:
        """⚠️ `starting` → `docked` quelques secondes → `starting` (mesuré) : l'état de travail est encore
        « repos ». Terminer ici rendrait la tondeuse au pilote, qui la rappellerait."""
        etat = _etat("demarrer", etape="dehors", vu_dehors=True)
        r = _suite(etat, _quai(mower_job_completion_state="repos"), volet="open", position=100)
        self.assertEqual(r["etape"], "dehors")
        self.assertFalse(r["finished"])

    def test_le_travail_termine_et_la_tondeuse_rentree_finissent_la_commande(self) -> None:
        etat = _etat("demarrer", etape="dehors", vu_dehors=True)
        r = _suite(etat, _quai(mower_job_completion_state="termine"), volet="open", position=100)
        self.assertEqual(r["etape"], "termine")
        self.assertTrue(r["finished"])

    def test_le_travail_termine_mais_la_tondeuse_encore_dehors_ne_finit_pas(self) -> None:
        etat = _etat("demarrer", etape="dehors", vu_dehors=True)
        r = _suite(etat, _dehors(mower_job_completion_state="termine"), volet="open", position=100)
        self.assertEqual(r["etape"], "dehors")

    def test_une_commande_jamais_vue_dehors_ne_se_termine_pas_sur_un_travail_termine_ancien(self) -> None:
        etat = _etat("demarrer", etape="dehors", vu_dehors=False)
        r = _suite(etat, _quai(mower_job_completion_state="termine"), volet="open", position=100)
        self.assertEqual(r["etape"], "dehors")

    def test_la_commande_expire_au_bout_de_son_delai(self) -> None:
        vieille = _etat("demarrer", etape="dehors", vu_dehors=True, jusqu_a=_il_y_a(1))
        r = _suite(vieille, _dehors(), volet="open", position=100)
        self.assertEqual(r["etape"], "expire")
        self.assertTrue(r["finished"])
        self.assertIsNone(r["action"])

    def test_un_etat_termine_ne_commande_plus_rien(self) -> None:
        for etape in sorted(mc.TERMINAL_STEPS):
            r = _suite(_etat("demarrer", etape=etape), volet="closed")
            self.assertIsNone(r["action"])
            self.assertTrue(r["finished"])


class RetourTests(unittest.TestCase):
    def test_sans_volet_le_retour_part_et_suspend_les_departs_automatiques(self) -> None:
        r = _sans_volet(_etat("retour"), _dehors())
        self.assertEqual(r["action"], {"service": "lawn_mower.dock", "data": {}})
        self.assertEqual(r["suspension_minutes"], mc.MANUAL_HOLD_AFTER_RETURN_MINUTES)

    def test_volet_ferme_on_l_ouvre_avant_le_retour(self) -> None:
        r = _suite(_etat("retour"), _dehors(), volet="closed", position=0)
        self.assertEqual(r["action"], {"service": "cover.open_cover", "data": {}})
        self.assertIsNone(r["suspension_minutes"])

    def test_le_retour_ne_part_pas_tant_que_le_volet_n_est_pas_confirme_ouvert(self) -> None:
        for volet, position in (("closed", 0), ("closing", 10), ("opening", 50), ("open", 60)):
            with self.subTest(volet=volet):
                r = _suite(_etat("retour", etape="attente_garage"), _dehors(), volet=volet, position=position)
                self.assertNotEqual((r["action"] or {}).get("service"), "lawn_mower.dock")

    def test_volet_ouvert_le_retour_part_sans_delai_supplementaire(self) -> None:
        r = _suite(_etat("retour", etape="attente_garage"), _dehors(), volet="open", position=100)
        self.assertEqual(r["action"]["service"], "lawn_mower.dock")

    def test_un_volet_qui_ne_repond_pas_empeche_le_retour(self) -> None:
        r = _suite(_etat("retour"), _dehors(), volet="unavailable")
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "erreur")

    def test_l_ordre_de_volet_retenu_ne_fait_pas_echouer_le_retour(self) -> None:
        """⚠️ Un ordre d'ouverture parti il y a 30 s : le retour ATTEND (pas d'erreur, pas de second ordre)."""
        garage = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(0.5), gg.KEY_ATTEMPTS: 1,
                  gg.KEY_SERIES_START: _il_y_a(0.5)}
        r = _suite(_etat("retour"), _dehors(), volet="closed", position=0, garage=garage)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "attente_garage")
        self.assertFalse(r["finished"])

    def test_un_volet_qui_n_ouvre_jamais_fait_abandonner_le_retour_apres_8_minutes(self) -> None:
        vieux = mc.new_state("retour", NOW - timedelta(minutes=9))
        garage = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(1), gg.KEY_ATTEMPTS: 1,
                  gg.KEY_SERIES_START: _il_y_a(1)}
        r = _suite(vieux, _dehors(), volet="closed", position=0, garage=garage)
        self.assertEqual(r["etape"], "erreur")
        self.assertEqual(r["updates"]["erreur"], "volet_non_ouvert")

    def test_un_volet_bloque_empeche_le_retour(self) -> None:
        garage = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(4), gg.KEY_ATTEMPTS: 3,
                  gg.KEY_SERIES_START: _il_y_a(10)}
        r = _suite(_etat("retour"), _dehors(), volet="closed", garage=garage)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "erreur")

    def test_apres_l_envoi_la_tondeuse_rentre_puis_la_commande_se_termine(self) -> None:
        envoye = _etat("retour", etape="retour_envoye", envoye_a=_il_y_a(2))
        encore_dehors = _suite(envoye, _dehors(), volet="open", position=100)
        self.assertEqual(encore_dehors["etape"], "retour_envoye")
        self.assertIsNone(encore_dehors["action"])
        rentree = _suite(envoye, _quai(), volet="open", position=100)
        self.assertEqual(rentree["etape"], "termine")
        self.assertEqual(rentree["suspension_minutes"], mc.MANUAL_HOLD_AFTER_RETURN_MINUTES)

    def test_le_retour_n_est_pas_renvoye(self) -> None:
        envoye = _etat("retour", etape="retour_envoye", envoye_a=_il_y_a(2))
        self.assertIsNone(_suite(envoye, _dehors(), volet="open", position=100)["action"])


class PauseTests(unittest.TestCase):
    def test_la_pause_part_une_fois(self) -> None:
        r = _sans_volet(_etat("pause", etape="pause_envoyee"), _dehors())
        self.assertEqual(r["action"], {"service": "lawn_mower.pause", "data": {}})
        envoyee = _etat("pause", etape="pause_envoyee", envoye_a=_il_y_a(1))
        self.assertIsNone(_sans_volet(envoyee, _dehors())["action"])

    def test_la_pause_ne_touche_pas_au_volet(self) -> None:
        r = _suite(_etat("pause", etape="pause_envoyee"), _dehors(), volet="closed", position=0)
        self.assertEqual(r["action"]["service"], "lawn_mower.pause")

    def test_la_pause_garde_le_mode_manuel_puis_expire(self) -> None:
        envoyee = _etat("pause", etape="pause_envoyee", envoye_a=_il_y_a(1))
        self.assertEqual(_sans_volet(envoyee, _dehors())["etape"], "pause_envoyee")
        expiree = _etat("pause", etape="pause_envoyee", envoye_a=_il_y_a(61), jusqu_a=_il_y_a(1))
        self.assertEqual(_sans_volet(expiree, _dehors())["etape"], "expire")


class ReprisePourSortieTests(unittest.TestCase):
    def test_la_reprise_envoie_un_seul_depart_sans_toucher_au_volet(self) -> None:
        r = _suite(_etat("reprendre"), _dehors(mower_job_completion_state="en_pause"), volet="closed", position=0)
        self.assertEqual(r["action"], {"service": "lawn_mower.start_mowing", "data": {}})
        self.assertEqual(r["etape"], "dehors")
        self.assertIs(r["updates"]["vu_dehors"], True)
        envoyee = _etat("reprendre", etape="dehors", envoye_a=_il_y_a(1), vu_dehors=True)
        self.assertIsNone(_suite(envoyee, _dehors(), volet="open", position=100)["action"])

    def test_une_tondeuse_rentree_entre_temps_abandonne_la_reprise(self) -> None:
        r = _suite(_etat("reprendre"), _quai(), volet="open", position=100)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "erreur")

    def test_apres_la_reprise_le_travail_termine_finit_la_commande(self) -> None:
        envoyee = _etat("reprendre", etape="dehors", envoye_a=_il_y_a(5), vu_dehors=True)
        r = _suite(envoyee, _quai(mower_job_completion_state="termine"), volet="open", position=100)
        self.assertEqual(r["etape"], "termine")
        self.assertTrue(r["finished"])


class SortieSupplanteeTests(unittest.TestCase):
    def test_un_retour_pendant_une_sortie_part_meme_avec_un_etat_d_ordre_actif(self) -> None:
        sortie = _etat("demarrer", etape="dehors", vu_dehors=True)
        self.assertIsNone(_valider("retour", _dehors(), state=sortie))
        nouveau = mc.new_state("retour", NOW)
        r = _suite(nouveau, _dehors(), volet="open", position=100)
        self.assertEqual(r["action"]["service"], "lawn_mower.dock")

    def test_un_nouvel_etat_remet_a_zero_la_date_de_fin(self) -> None:
        self.assertIsNone(mc.new_state("demarrer", NOW)["fini_a"])


class VoletRouvertDevantUneTondeuseDehorsTests(unittest.TestCase):
    """⚠️ Une tondeuse dehors ne trouve jamais son volet fermé : tant qu'une commande manuelle dure,
    c'est elle qui le rouvre — le pilote ne le fait qu'en mode actif, et la commande marche dans les trois."""

    ETATS = {
        "pause": lambda: _etat("pause", etape="pause_envoyee", envoye_a=_il_y_a(1)),
        "retour": lambda: _etat("retour", etape="retour_envoye", envoye_a=_il_y_a(1)),
        "sortie": lambda: _etat("demarrer", etape="dehors", envoye_a=_il_y_a(5), vu_dehors=True),
        "départ_envoyé": lambda: _etat("demarrer", etape="depart_envoye", envoye_a=_il_y_a(1)),
        "reprise": lambda: _etat("reprendre", etape="dehors", envoye_a=_il_y_a(1), vu_dehors=True),
    }

    def test_volet_ferme_devant_une_tondeuse_dehors_il_est_rouvert_dans_chaque_etat(self) -> None:
        for nom, fabrique in self.ETATS.items():
            with self.subTest(etat=nom):
                etat = fabrique()
                r = _suite(etat, _dehors(), volet="closed", position=0)
                self.assertEqual(r["action"], {"service": "cover.open_cover", "data": {}})
                self.assertEqual(r["etape"], etat["etape"] if nom != "départ_envoyé" else "dehors",
                                 "la commande continue, son étape ne change pas")
                self.assertFalse(r["finished"])

    def test_volet_qui_se_ferme_en_route_est_aussi_rouvert(self) -> None:
        for volet, position in (("closing", 40), ("closed", 0)):
            with self.subTest(volet=volet):
                r = _suite(self.ETATS["sortie"](), _dehors(), volet=volet, position=position)
                self.assertEqual((r["action"] or {}).get("service"), "cover.open_cover")

    def test_ouverture_incomplete_est_completee(self) -> None:
        r = _suite(self.ETATS["sortie"](), _dehors(), volet="open", position=60)
        self.assertEqual((r["action"] or {}).get("service"), "cover.open_cover")

    def test_volet_ouvert_ou_en_ouverture_aucun_ordre(self) -> None:
        for volet, position in (("open", 100), ("opening", 30)):
            with self.subTest(volet=volet):
                for nom, fabrique in self.ETATS.items():
                    self.assertIsNone(_suite(fabrique(), _dehors(), volet=volet, position=position)["action"], nom)

    def test_volet_muet_aucun_ordre_l_alerte_s_en_charge(self) -> None:
        for volet in ("unavailable", "unknown", None):
            with self.subTest(volet=volet):
                r = _suite(self.ETATS["sortie"](), _dehors(), volet=volet)
                self.assertIsNone(r["action"])
                self.assertFalse(r["finished"], "la commande n'est pas abandonnée : la tondeuse est dehors")

    def test_sans_volet_configure_aucun_ordre(self) -> None:
        self.assertIsNone(_sans_volet(self.ETATS["sortie"](), _dehors())["action"])

    def test_tondeuse_rentree_aucun_ordre_de_volet(self) -> None:
        """À quai, volet fermé : rien à rouvrir (ni pour une sortie finie, ni pour un retour terminé)."""
        r = _suite(self.ETATS["sortie"](), _quai(mower_job_completion_state="en_cours"), volet="closed", position=0)
        self.assertIsNone(r["action"])

    def test_ordre_deja_envoye_retenu_aucun_doublon(self) -> None:
        garage = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(0.5), gg.KEY_ATTEMPTS: 1,
                  gg.KEY_SERIES_START: _il_y_a(0.5)}
        r = _suite(self.ETATS["sortie"](), _dehors(), volet="closed", position=0, garage=garage)
        self.assertIsNone(r["action"])
        self.assertEqual(r["etape"], "dehors")
        self.assertIn("nouvelle tentative", r["reason"])

    def test_volet_bloque_la_commande_continue_sans_ordre(self) -> None:
        garage = {gg.KEY_COMMAND: "open_cover", gg.KEY_COMMAND_AT: _il_y_a(4), gg.KEY_ATTEMPTS: 3,
                  gg.KEY_SERIES_START: _il_y_a(10)}
        r = _suite(self.ETATS["sortie"](), _dehors(), volet="closed", position=0, garage=garage)
        self.assertIsNone(r["action"])
        self.assertFalse(r["finished"])
        self.assertEqual(r["etape"], "dehors")


class PauseFaiteAilleursTests(unittest.TestCase):
    """⚠️ Dehors, l'état de travail est `en_cours` même en pause : seul l'état de la machine dit « pause »."""

    def test_pause_depuis_l_appli_du_constructeur_la_reprise_est_possible(self) -> None:
        for nom, maj in (
            ("état machine", {"mower_operation_state": "paused"}),
            ("statut normalisé", {"tondeuse_statut": "pause"}),
            ("travail en pause à quai", {"mower_job_completion_state": "en_pause"}),
        ):
            with self.subTest(source=nom):
                self.assertIsNone(_valider("reprendre", _dehors(**{"mower_job_completion_state": "en_cours", **maj})))

    def test_une_tondeuse_qui_tond_n_est_pas_en_pause(self) -> None:
        self.assertIn("pas en pause", _valider("reprendre", _dehors(mower_job_completion_state="en_cours")))
        self.assertIn("pas en pause", _valider("reprendre", _dehors(mower_job_completion_state="sans_mesure")))

    def test_la_pause_manuelle_expiree_n_empeche_pas_de_reprendre_une_machine_restee_en_pause(self) -> None:
        expiree = _etat("pause", etape="pause_envoyee", envoye_a=_il_y_a(70), jusqu_a=_il_y_a(10))
        self.assertIsNone(_valider("reprendre", _dehors(mower_operation_state="paused"), state=expiree))


class AnnulationTests(unittest.TestCase):
    def test_annuler_arrete_le_mode_manuel(self) -> None:
        etat = cancel_etat = mc.cancel(_etat("demarrer", etape="attente_garage"), NOW)
        self.assertEqual(etat["etape"], "annule")
        self.assertFalse(mc.is_active(cancel_etat, NOW))

    def test_annuler_date_la_fin(self) -> None:
        self.assertEqual(mc.cancel(_etat("demarrer", etape="dehors"), NOW)["fini_a"], NOW.isoformat())

    def test_annuler_sans_etat_ne_plante_pas(self) -> None:
        self.assertEqual(mc.cancel(None, NOW)["etape"], "annule")


if __name__ == "__main__":
    unittest.main()
