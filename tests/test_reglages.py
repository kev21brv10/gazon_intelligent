"""Le registre de la page « Réglages du gazon » dit la vérité sur le moteur.

Chaque valeur par défaut est comparée à la constante (ou au comportement) qu'elle représente :
une page qui annoncerait « 10:00 » pendant que le moteur tond dès 9 h serait pire que pas de page.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


def _install_homeassistant_dt_stub() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
    homeassistant_module = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    util_module = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
    homeassistant_module.util = util_module  # type: ignore[attr-defined]
    dt_module = types.ModuleType("homeassistant.util.dt")
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=ZoneInfo("Europe/Paris"))  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module
    util_module.dt = dt_module  # type: ignore[attr-defined]


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_dt_stub()


def _module(nom: str):
    return __import__(f"custom_components.gazon_intelligent.{nom}", fromlist=["_"])


reglages = _module("reglages")


class LeRegistreEstCoherentTests(unittest.TestCase):
    def test_cles_uniques_groupes_et_genres_connus(self) -> None:
        cles = [r.cle for r in reglages.REGLAGES]
        self.assertEqual(len(cles), len(set(cles)))
        groupes = {g.cle for g in reglages.GROUPES}
        for r in reglages.REGLAGES:
            with self.subTest(cle=r.cle):
                self.assertIn(r.groupe, groupes)
                self.assertIn(r.genre, reglages.GENRES)
                self.assertTrue(r.titre.endswith("?"), "le titre est une question simple")
                self.assertTrue(r.aide)
                self.assertLess(r.minimum, r.maximum)
                self.assertGreater(r.pas, 0)
                if r.avertissement:
                    self.assertTrue(r.avertissement.startswith("Réglage sensible :"))

    def test_les_valeurs_par_defaut_sont_valides(self) -> None:
        self.assertEqual(reglages.valider({}), {})
        self.assertEqual(reglages.valider(reglages.valeurs_par_defaut()), {})
        pluie = reglages.reglage("arrosage_sensibilite_pluie")
        self.assertEqual((pluie.defaut, pluie.minimum, pluie.maximum, pluie.pas), (1.0, 0.75, 1.25, 0.25))

    def test_les_contraintes_portent_sur_des_reglages_existants(self) -> None:
        cles = {r.cle for r in reglages.REGLAGES}
        for c in reglages.CONTRAINTES:
            with self.subTest(contrainte=c.message):
                self.assertIn(c.gauche, cles)
                self.assertIn(c.droite, cles)

    def test_une_valeur_hors_bornes_est_refusee_en_clair(self) -> None:
        erreurs = reglages.valider({"tonte_vent_bloque": 200})
        self.assertEqual(erreurs, {"tonte_vent_bloque": "Sélectionner une valeur entre 20 et 60."})
        self.assertEqual(
            reglages.valider({"sursemis_pousse_plantules": 2}),
            {"sursemis_pousse_plantules": "Sélectionner une valeur entre 0,1 et 1."},
        )

    def test_une_contrainte_violee_est_refusee_en_clair(self) -> None:
        erreurs = reglages.valider({"tonte_fenetre_ideale_debut": 14 * 60})
        self.assertIn("avant sa fin", erreurs["tonte_fenetre_ideale_debut"])
        # Égalité permise quand la contrainte n'est pas stricte, refusée sinon.
        self.assertEqual(reglages.valider({"sursemis_lame_finale": 4.0}), {})
        self.assertIn("sursemis_lame", reglages.valider({"sursemis_lame_finale": 3.5}))
        self.assertIn("tonte_vent_a_eviter", reglages.valider({"tonte_vent_a_eviter": 30, "tonte_vent_bloque": 30}))

    def test_chaque_contrainte_refuse_vraiment_quelque_chose(self) -> None:
        """Une contrainte que les bornes empêchent de violer ne protège rien : elle ment."""
        for c in reglages.CONTRAINTES:
            with self.subTest(gauche=c.gauche, droite=c.droite):
                gauche, droite = reglages.reglage(c.gauche), reglages.reglage(c.droite)
                erreurs = reglages.valider({c.gauche: gauche.maximum, c.droite: droite.minimum})
                self.assertEqual(erreurs.get(c.gauche), c.message)

    def test_l_attente_de_la_tondeuse_finit_toujours_avant_le_suivi(self) -> None:
        self.assertLess(reglages.reglage("sursemis_levee").maximum, reglages.reglage("graines_duree").minimum)

    def test_la_table_des_mois_a_douze_valeurs_dans_les_bornes(self) -> None:
        self.assertEqual(
            reglages.valider({"tonte_hauteur_par_mois": [4.0] * 11}),
            {"tonte_hauteur_par_mois": "Il faut un nombre pour chaque mois."},
        )
        self.assertEqual(
            reglages.valider({"tonte_hauteur_par_mois": [4.0] * 11 + [9.0]}),
            {"tonte_hauteur_par_mois": "Sélectionner une valeur entre 3 et 8."},
        )
        self.assertEqual(reglages.valider({"tonte_hauteur_par_mois": [5.0] * 12}), {})

    def test_une_valeur_hors_du_pas_est_refusee(self) -> None:
        self.assertEqual(
            reglages.valider({"semis_hauteur_germination": 7.3}),
            {"semis_hauteur_germination": "La valeur avance de 0,5 en 0,5."},
        )
        self.assertEqual(reglages.valider({"sursemis_pousse_plantules": 0.35}), {})
        self.assertEqual(reglages.valider({"tonte_fenetre_ideale_debut": 9 * 60 + 45}), {})
        self.assertIn("tonte_fenetre_ideale_debut", reglages.valider({"tonte_fenetre_ideale_debut": 9 * 60 + 50}))

    def test_ce_qui_n_est_pas_un_nombre_est_refuse(self) -> None:
        for valeur in ("40", True, None, float("nan"), [40]):
            with self.subTest(valeur=valeur):
                self.assertEqual(reglages.valider({"tonte_vent_bloque": valeur}), {"tonte_vent_bloque": "Il faut un nombre."})

    def test_un_reglage_inconnu_est_refuse(self) -> None:
        self.assertEqual(reglages.valider({"inconnu": 1}), {"inconnu": "Réglage inconnu."})

    def test_l_export_est_du_json(self) -> None:
        export = reglages.exporter()
        json.dumps(export)
        self.assertEqual(len(export["reglages"]), len(reglages.REGLAGES))
        self.assertEqual(export["reglages"][0]["cle"], "tonte_fenetre_ideale_debut")

    def test_les_reglages_sensibles_sont_exportes_avec_leur_avertissement(self) -> None:
        exportes = {r["cle"]: r for r in reglages.exporter()["reglages"]}
        sensibles = {cle for cle, r in exportes.items() if r["avertissement"]}
        self.assertEqual(
            sensibles,
            {
                "tonte_vent_bloque",
                "tonte_temperature_bloquee",
                "tonte_humidite_bloquee",
                "tonte_max_par_jour",
                "arrosage_delai_relance",
                "arrosage_decoupage_seuil",
                "arrosage_pause_duree",
                "arrosage_sensibilite_pluie",
                "arrosage_reduction_ombre_zone_1",
                "arrosage_reduction_ombre_zone_2",
                "arrosage_reduction_ombre_zone_3",
                "arrosage_reduction_ombre_zone_4",
                "arrosage_reduction_ombre_zone_5",
                "rafraichissement_temperature",
                "rafraichissement_dose",
                "graines_germination_dose",
                "graines_germination_cycles",
                "graines_fenetre_fin",
                "semis_reprise_tonte_jours",
                "mode_scarification_temperature_min",
                "tondeuse_pilotage_batterie_min",
                "tondeuse_pilotage_delai_commandes",
                "tondeuse_garage_ouvrir_avant_depart",
                "tondeuse_garage_ouvrir_pour_retour",
                "tondeuse_garage_fermer_apres_retour",
                "tondeuse_garage_avance_ouverture",
                "tondeuse_garage_ouverture_min",
                "tondeuse_garage_delai_fermeture",
            },
        )


class LesValeursParDefautSontCellesDuMoteurTests(unittest.TestCase):
    """Une ligne par réglage : la valeur montrée est celle que le moteur utilise."""

    def setUp(self) -> None:
        self.defauts = reglages.valeurs_par_defaut()

    def test_tonte(self) -> None:
        dm = _module("decision_mowing")
        normal = {"phase_dominante": "Normal", "sous_phase": "Normal"}
        attendu = {
            "tonte_fenetre_ideale_debut": dm._MOWING_WINDOW_IDEAL_START * 60,
            "tonte_fenetre_ideale_fin": dm._MOWING_WINDOW_IDEAL_END * 60,
            "tonte_soir_avant_coucher": dm._MOWING_EVENING_START_BEFORE_SUNSET_MIN,
            "tonte_soir_apres_coucher": dm._MOWING_EVENING_END_AFTER_SUNSET_MIN,
            "tonte_vent_a_eviter": dm._MOWING_WINDOW_DISCOURAGED_WIND,
            "tonte_vent_bloque": dm._MOWING_WINDOW_BLOCK_WIND,
            "tonte_temperature_a_eviter": dm._MOWING_WINDOW_DISCOURAGED_TEMP_MIN,
            "tonte_temperature_bloquee": dm._MOWING_WINDOW_BLOCK_TEMP_MIN,
            "tonte_humidite_bloquee": dm._MOWING_WINDOW_BLOCK_HUMIDITY,
            "tonte_ecart_min_jours": dm._mowing_spacing_min_days(normal),
            "tonte_max_par_jour": dm._mowing_daily_session_policy(normal)[0],
            "tonte_hauteur_par_mois": [dm._HAUTEUR_BASE_PAR_MOIS[m] for m in range(1, 13)],
            "tonte_frequence_par_mois": [dm._MOWING_FREQUENCY_BY_MONTH[m][0] for m in range(1, 13)],
        }
        for cle, valeur in attendu.items():
            with self.subTest(cle=cle):
                self.assertEqual(self.defauts[cle], valeur)
        self.assertEqual(
            reglages.valider({"tondeuse_garage_ouvrir_avant_depart": "oui"}),
            {"tondeuse_garage_ouvrir_avant_depart": "Sélectionner activé ou désactivé."},
        )

    def test_le_rythme_du_mois_est_celui_qui_juge_le_retard(self) -> None:
        # `_mowing_overdue_state` lit la fréquence par ce chemin, hors semis et sursemis.
        # ⚠️ Le libellé (« 2 à 3 / semaine ») est un texte À PART : au branchement, il devra
        # suivre la valeur réglée, sinon la page et l'intégration se contrediront.
        dm = _module("decision_mowing")
        for phase in ("Normal", "Traitement", "Fertilisation"):
            for mois in range(1, 13):
                with self.subTest(phase=phase, mois=mois):
                    self.assertEqual(
                        dm._phase_adjusted_mowing_frequency({"phase_dominante": phase, "sous_phase": phase}, mois)[0],
                        self.defauts["tonte_frequence_par_mois"][mois - 1],
                    )

    def test_arrosage(self) -> None:
        gu = _module("guidance")
        cc = _module("coordinator_constants")
        attendu = {
            "arrosage_ouverture": int(gu.OPTIMAL_MORNING_START_HOUR * 60),
            "arrosage_fin_optimale": gu.OPTIMAL_MORNING_END_HOUR * 60,
            "arrosage_fin_acceptable": gu.ACCEPTABLE_MORNING_END_HOUR * 60,
            "arrosage_marge_avant_lever": cc.WATERING_SUNRISE_MARGIN_MINUTES,
            "arrosage_delai_relance": cc.AUTO_IRRIGATION_RELAUNCH_COOLDOWN.total_seconds() / 3600,
            "arrosage_decoupage_seuil": gu.FRACTIONNEMENT_NORMAL_SEUIL_MM,
            "arrosage_pause_dose_min": gu.PAUSE_LONGUE_MIN_DOSE_MM,
            "arrosage_pause_duree": gu.PAUSE_ENTRE_PASSAGES_MIN,
            "rafraichissement_temperature": gu.EVENING_COOLING_MIN_TEMP,
            "rafraichissement_dose": gu.EVENING_COOLING_MM,
        }
        for cle, valeur in attendu.items():
            with self.subTest(cle=cle):
                self.assertEqual(self.defauts[cle], valeur)

    def test_le_seuil_de_decoupage_reste_dans_ce_que_le_mode_normal_arrose(self) -> None:
        """Hors de ces bornes, le réglage ne changerait rien : le moteur ne verrait jamais la dose."""
        wp = _module("watering_policy")
        execution = wp.WATERING_POLICIES[wp.MODE_NORMAL].execution
        seuil = reglages.reglage("arrosage_decoupage_seuil")
        self.assertEqual(seuil.minimum, execution.min_session_mm)
        # Au-delà de la plus grosse séance, le moteur coupe déjà en passages de 15 mm au plus.
        self.assertEqual(seuil.maximum, execution.max_session_mm)

    def test_graines(self) -> None:
        ph = _module("phases")
        gu = _module("guidance")
        wp = _module("watering_policy")
        bornes = dict((libelle, borne) for borne, libelle in ph.SUBPHASE_RULES["Sursemis"])
        programmes = wp.SEMIS_STAGE_PROGRAMS
        attendu = {
            "graines_duree": ph.PHASE_DURATIONS_DAYS["Sursemis"],
            "graines_fin_germination": bornes["Germination"],
            "graines_fin_enracinement": bornes["Enracinement"],
            "graines_fin_reprise": bornes["Reprise"],
            "graines_germination_dose": programmes["germination"].surface_cycle_mm_optimal,
            "graines_germination_cycles": programmes["germination"].daily_cycles_optimal,
            "graines_enracinement_dose": programmes["enracinement"].surface_cycle_mm_optimal,
            "graines_enracinement_cycles": programmes["enracinement"].daily_cycles_optimal,
            "graines_reprise_dose": programmes["levee"].surface_cycle_mm_optimal,
            "graines_reprise_cycles": programmes["levee"].daily_cycles_optimal,
            "graines_fenetre_debut": gu.SEMIS_WINDOW_START_HOUR * 60,
            "graines_fenetre_fin": gu.SEMIS_WINDOW_END_HOUR * 60,
            # Une alerte, pas une décision : le délai du module qui la lance.
            "graines_alerte_retard": _module("notifications").DELAI_RETARD_GRAINES.total_seconds() / 60,
        }
        for cle, valeur in attendu.items():
            with self.subTest(cle=cle):
                self.assertEqual(self.defauts[cle], valeur)
        # Semis et Sursemis partagent la même durée et les mêmes étapes. La tonte en gardait une
        # TROISIÈME copie (`decision_mowing._SEMIS_DUREE_JOURS`) : retirée au branchement (0.92.0),
        # elle lit désormais `phases.phase_duration_days`, réglage compris.
        self.assertEqual(ph.PHASE_DURATIONS_DAYS["Semis"], self.defauts["graines_duree"])
        self.assertFalse(hasattr(_module("decision_mowing"), "_SEMIS_DUREE_JOURS"))
        self.assertEqual(ph.SUBPHASE_RULES["Semis"], ph.SUBPHASE_RULES["Sursemis"])
        # Même température minimale pour toutes les politiques de semis.
        for politique in gu.SURSEMIS_POLICY_CONFIGS.values():
            self.assertEqual(politique["temperature_min"], self.defauts["graines_temperature_min"])

    def test_le_vent_maximal_des_graines_est_celui_du_moteur(self) -> None:
        """Pas de constante : le seuil est écrit dans la branche semis. On le mesure."""
        gu = _module("guidance")
        seuil = self.defauts["graines_vent_max"]

        def fenetre(vent: float) -> str:
            return gu.compute_action_guidance(
                phase_dominante="Sursemis", sous_phase="Germination",
                water_balance={"bilan_hydrique_mm": -1.0, "deficit_3j": 1.0, "deficit_7j": 1.0},
                advanced_context={"vent": vent, "rosee": 0.0, "hauteur_gazon": None},
                pluie_24h=0.0, pluie_demain=0.0, humidite=60.0, temperature=18.0, etp=2.0,
                objectif_mm=1.5, hour_of_day=11, history=[{"type": "Sursemis", "date": "2026-04-01"}],
                sous_phase_age_days=3, sous_phase_progression=30.0,
            )["fenetre_optimale"]

        self.assertEqual(fenetre(seuil - 0.1), "maintenant")
        self.assertNotEqual(fenetre(seuil), "maintenant")

    def test_sursemis_et_semis(self) -> None:
        ph = _module("phases")
        dm = _module("decision_mowing")
        attendu = {
            "sursemis_levee": ph.SURSEMIS_LEVEE_JOURS,
            "sursemis_pousse_plantules": ph.PLANTULES_POUSSE_CM_JOUR,
            "sursemis_lame": ph.SURSEMIS_HAUTEUR_COUPE_CM,
            "sursemis_lame_finale": dm.SURSEMIS_HAUTEUR_FINALE_CM,
            "sursemis_coupes_avant_remontee": dm.SURSEMIS_COUPES_AVANT_REMONTEE,
            "sursemis_ecart_tontes": dm.SURSEMIS_ESPACEMENT_TONTE_JOURS,
            "sursemis_premiere_coupe": ph.PLANTULES_RATIO_PREMIERE_COUPE,
            "semis_reprise_tonte_jours": dm.SEMIS_REPRISE_TONTE_JOUR,
            "semis_hauteur_germination": dm._SEMIS_PLANCHERS_CM["Germination"],
            "semis_hauteur_enracinement": dm._SEMIS_PLANCHERS_CM["Enracinement"],
            "semis_hauteur_reprise": dm._SEMIS_PLANCHERS_CM["Reprise"],
            "semis_hauteur_stabilisation": dm._SEMIS_PLANCHERS_CM["Stabilisation"],
        }
        for cle, valeur in attendu.items():
            with self.subTest(cle=cle):
                self.assertEqual(self.defauts[cle], valeur)

    def test_modes(self) -> None:
        ph = _module("phases")
        wp = _module("watering_policy")
        modes = {
            "mode_traitement_duree": "Traitement",
            "mode_fertilisation_duree": "Fertilisation",
            "mode_biostimulant_duree": "Biostimulant",
            "mode_agent_mouillant_duree": "Agent Mouillant",
            "mode_scarification_duree": "Scarification",
        }
        for cle, mode in modes.items():
            with self.subTest(cle=cle):
                self.assertEqual(self.defauts[cle], ph.PHASE_DURATIONS_DAYS[mode])
        # Tous les modes à durée finie ont leur réglage : Semis et Sursemis passent par
        # `graines_duree`, Normal n'a pas de durée, Hivernage n'en a pas de fin.
        couverts = set(modes.values()) | {"Semis", "Sursemis"}
        self.assertEqual(set(ph.PHASE_DURATIONS_DAYS) - {"Normal", "Hivernage"}, couverts)
        self.assertEqual(
            self.defauts["mode_scarification_temperature_min"],
            wp.WATERING_POLICIES[wp.MODE_SCARIFICATION].conditions["temperature_min_c"],
        )

    def test_pilotage_tondeuse(self) -> None:
        mc = _module("mower_control_constants")
        attendu = {
            "tondeuse_pilotage_batterie_min": mc.DEFAULT_MOWER_CONTROL_MIN_BATTERY,
            "tondeuse_pilotage_delai_commandes": mc.DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES,
            "tondeuse_garage_avance_ouverture": mc.DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES,
            "tondeuse_garage_ouverture_min": mc.DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION,
            "tondeuse_garage_delai_fermeture": mc.DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES,
            "tondeuse_garage_ouvrir_avant_depart": mc.DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START,
            "tondeuse_garage_ouvrir_pour_retour": mc.DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN,
            "tondeuse_garage_fermer_apres_retour": mc.DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK,
        }
        for cle, valeur in attendu.items():
            with self.subTest(cle=cle):
                self.assertEqual(self.defauts[cle], valeur)
        (choix,) = [c for c in reglages.CHOIX if c.cle == "pilotage_tondeuse"]
        self.assertEqual(choix.defaut, mc.DEFAULT_MOWER_CONTROL_MODE)
        self.assertEqual(tuple(o.valeur for o in choix.options), mc.MOWER_CONTROL_MODES)
        (creneaux,) = [c for c in reglages.CHOIX if c.cle == "tondeuse_creneaux_depart"]
        self.assertEqual(creneaux.defaut, mc.DEFAULT_MOWER_START_WINDOW_POLICY)
        self.assertEqual(tuple(o.valeur for o in creneaux.options), mc.MOWER_START_WINDOW_POLICIES)

    def test_surface_totale_du_gazon(self) -> None:
        (surface,) = [r for r in reglages.REGLAGES if r.cle == "surface_gazon_m2"]
        self.assertEqual(surface.defaut, 0.0)
        self.assertEqual(surface.minimum, 0.0)
        self.assertEqual(surface.maximum, 100000.0)
        self.assertEqual(surface.pas, 1.0)
        self.assertEqual(surface.unite, "m²")

    def test_le_jour_de_la_declaration_compte_dans_la_duree(self) -> None:
        """« 2 jours » = le jour déclaré et le lendemain : c'est ce que la page écrit."""
        from datetime import date, timedelta

        ph = _module("phases")
        debut = date(2026, 9, 16)
        for cle, mode in (("mode_traitement_duree", "Traitement"), ("mode_scarification_duree", "Scarification")):
            duree = self.defauts[cle]
            historique = [{"type": mode, "date": debut.isoformat()}]
            with self.subTest(mode=mode):
                dernier = debut + timedelta(days=duree - 1)
                self.assertEqual(ph.compute_dominant_phase(historique, today=dernier)["phase_dominante"], mode)
                self.assertEqual(ph.compute_dominant_phase(historique, today=dernier + timedelta(days=1))["phase_dominante"], "Normal")

    def test_le_type_de_sol_dit_les_chiffres_du_moteur(self) -> None:
        const = _module("const")
        sol = _module("soil_balance")
        water = _module("water")
        (choix,) = [c for c in reglages.CHOIX if c.cle == "type_sol"]
        self.assertEqual(choix.cle, const.CONF_TYPE_SOL)
        self.assertEqual(choix.defaut, const.DEFAULT_TYPE_SOL)
        self.assertEqual(tuple(o.valeur for o in choix.options), const.TYPES_SOL)
        for option in choix.options:
            with self.subTest(sol=option.valeur):
                self.assertEqual(option.reserve_mm, sol.SOIL_RESERVE_BASE_MM[option.valeur])
                self.assertEqual(option.reserve_mm, water._SOIL_RESERVE_UTILE_MM[option.valeur])
                self.assertEqual(option.reserve_max_mm, sol.SOIL_RESERVE_MAX_MM[option.valeur])

    def test_un_choix_hors_liste_est_refuse_en_clair(self) -> None:
        self.assertEqual(reglages.valider_choix({"type_sol": "argileux"}), {})
        self.assertEqual(
            reglages.valider_choix({"type_sol": "tourbe"}),
            {"type_sol": "Sélectionner parmi : sableuse, limoneuse, argileuse."},
        )
        self.assertEqual(reglages.valider_choix({"inconnu": "x"}), {"inconnu": "Choix inconnu."})
        sol = next(c for c in reglages.exporter()["choix"] if c["cle"] == "type_sol")
        self.assertEqual(sol["options"][1]["valeur"], "limoneux")

    def test_chaque_reglage_est_verifie_ici(self) -> None:
        """Un réglage ajouté au registre sans sa ligne de vérification ferait échouer ce test."""
        source = Path(__file__).read_text(encoding="utf-8")
        for r in reglages.REGLAGES:
            with self.subTest(cle=r.cle):
                self.assertIn(f'"{r.cle}"', source)
