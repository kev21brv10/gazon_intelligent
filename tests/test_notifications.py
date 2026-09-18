"""Alertes et notifications (0.93.0) : ce qui part, quand, et ce que le message dit.

Une alerte fausse fait chercher au mauvais endroit ; une alerte muette laisse sécher des graines.
Chaque scénario ci-dessous vient d'une situation réelle ou d'un défaut connu du moteur :
    · 17/09/2026 : un vent au-dessus de la limite retient les cycles en silence, et « Bloqué »
      s'affiche AUSSI pendant l'attente normale entre deux cycles ;
    · un cycle dû après la fermeture de la fenêtre n'a jamais lieu ;
    · un redémarrage (fréquent ici) ne doit ni renvoyer une alerte, ni oublier un rattrapage.
"""

from __future__ import annotations

import asyncio
import copy
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from tests.test_watering_session_monitoring import (  # noqa: F401 - installe les stubs HA
    _FakeEntry,
    _FakeState,
    _FakeStates,
    _build_coordinator,
    coordinator_mod,
)

import importlib

notifications = importlib.import_module("custom_components.gazon_intelligent.notifications")
# ⚠️ La classe que le coordinateur LÈVE, lue dans ses globales : d'autres modules de test
# remplacent `homeassistant.exceptions.HomeAssistantError` en cours de suite (piège du réimport).
ErreurHA = coordinator_mod.HomeAssistantError

PARIS = ZoneInfo("Europe/Paris")
JOUR = datetime(2026, 9, 17, tzinfo=PARIS)


def _a(heure: str, jour: datetime = JOUR) -> datetime:
    h, m = (int(x) for x in heure.split(":"))
    return jour.replace(hour=h, minute=m)


def _progression(
    *,
    faits: int = 1,
    cible: int = 4,
    prevu: str = "12:58",
    etat: str = "ready",
    fin_dernier: str | None = "10:58",
) -> dict[str, object]:
    return {
        "state": etat,
        "next_due_at": _a(prevu) if faits < cible else None,
        "cycles_completed_today": faits,
        "cycles_remaining_today": max(0, cible - faits),
        "daily_cycles_target": cible,
        # Comme en production : `recorded_at` est en UTC.
        "last_cycle_at": _a(fin_dernier).astimezone(timezone.utc) if fin_dernier else None,
    }


def _evaluer(memoire=None, *, heure: str = "13:20", jour: datetime = JOUR, **changements):
    parametres: dict[str, object] = {
        "maintenant": _a(heure, jour),
        "progression": _progression(),
        "en_cours": False,
        "raison": "target_date_future",
        "fenetre": "demain_matin",
        "vent_kmh": 17.0,
        "vent_max_kmh": 15.0,
        "fin_fenetre_minute": 960,
        "motif_decision": None,
        "echec_lancement": None,
        "verrou": False,
    }
    parametres.update(changements)
    return notifications.evaluer_alertes(memoire, **parametres)


class CycleDeGrainesEnRetardTests(unittest.TestCase):
    def test_le_vent_au_dessus_de_la_limite_est_nomme(self) -> None:
        alertes, _ = _evaluer()
        self.assertEqual(len(alertes), 1)
        alerte = alertes[0]
        self.assertEqual(alerte.sujet, "graines")
        self.assertTrue(alerte.persistante)
        self.assertFalse(alerte.resolue)
        self.assertEqual(alerte.titre, "🌱 Graines : le cycle de 12:58 n'est pas parti")
        self.assertIn("17 km/h", alerte.message)
        self.assertIn("limite de 15 km/h", alerte.message)
        self.assertIn("jusqu'à 16:00", alerte.message)
        self.assertIn("Cycles faits aujourd'hui : 1 sur 4.", alerte.message)

    def test_rien_avant_vingt_minutes_de_retard(self) -> None:
        alertes, _ = _evaluer(maintenant=_a("12:58") + timedelta(minutes=19, seconds=59))
        self.assertEqual(alertes, [])
        alertes, _ = _evaluer(heure="13:18")
        self.assertEqual(len(alertes), 1, "à 20 minutes pile, le retard est avéré")

    def test_une_seule_alerte_par_cycle_meme_apres_redemarrage(self) -> None:
        _, memoire = _evaluer()
        # La mémoire traverse un aller-retour JSON, comme le fichier d'état.
        import json

        relue = json.loads(json.dumps(memoire))
        for heure in ("13:22", "13:40", "15:00"):
            with self.subTest(heure=heure):
                alertes, relue = _evaluer(relue, heure=heure)
                self.assertEqual(alertes, [])

    def test_le_rattrapage_est_annonce_une_fois(self) -> None:
        _, memoire = _evaluer()
        rattrape = _progression(faits=2, prevu="15:52", etat="waiting", fin_dernier="13:52")
        alertes, memoire = _evaluer(memoire, heure="13:53", progression=rattrape)
        self.assertEqual(len(alertes), 1)
        alerte = alertes[0]
        self.assertTrue(alerte.resolue, "la trace « pas parti » doit être retirée")
        self.assertFalse(alerte.persistante)
        self.assertEqual(alerte.titre, "🌱 Graines : cycle rattrapé")
        self.assertIn("prévu à 12:58", alerte.message)
        self.assertIn("terminé à 13:52", alerte.message, "l'heure de fin doit être lue à l'heure locale")
        self.assertIn("2 sur 4", alerte.message)
        alertes, _ = _evaluer(memoire, heure="14:10", progression=rattrape)
        self.assertEqual(alertes, [])

    def test_rien_pendant_un_arrosage(self) -> None:
        alertes, memoire = _evaluer(en_cours=True)
        self.assertEqual(alertes, [])
        self.assertEqual(memoire.get("graines"), {}, "un cycle en cours ne doit pas être noté en retard")

    def test_rien_quand_le_cycle_attend_son_heure(self) -> None:
        alertes, _ = _evaluer(heure="12:30", progression=_progression(etat="waiting"))
        self.assertEqual(alertes, [])

    def test_rien_quand_la_journee_est_faite(self) -> None:
        alertes, _ = _evaluer(heure="16:30", progression=_progression(faits=4, etat="complete"))
        self.assertEqual(alertes, [])

    def test_rien_sans_programme_de_graines(self) -> None:
        alertes, memoire = _evaluer(progression=None)
        self.assertEqual(alertes, [])
        self.assertEqual(memoire["jour"], "2026-09-17")

    def test_interrupteur_coupe(self) -> None:
        alertes, _ = _evaluer(raison="auto_irrigation_disabled", vent_kmh=3.0, fenetre="maintenant")
        self.assertIn("L'arrosage automatique est coupé.", alertes[0].message)
        self.assertIn("« Arrosage automatique autorisé »", alertes[0].message)

    def test_un_vent_faible_n_est_pas_accuse(self) -> None:
        alertes, _ = _evaluer(vent_kmh=8.0)
        message = alertes[0].message
        self.assertNotIn("au-dessus de la limite", message)
        self.assertIn("fenêtre « demain matin »", message)
        self.assertIn("Vent au jardin : 8 km/h.", message)

    def test_un_vent_egal_a_la_limite_est_nomme(self) -> None:
        # Le moteur n'arrose que sous la limite (`vent < vent_max`) : à la limite, il attend.
        alertes, _ = _evaluer(vent_kmh=15.0)
        self.assertIn("au-dessus de la limite de 15 km/h", alertes[0].message)

    def test_la_limite_de_vent_est_celle_qui_est_reglee(self) -> None:
        alertes, _ = _evaluer(vent_kmh=17.0, vent_max_kmh=20.0)
        self.assertNotIn("au-dessus de la limite", alertes[0].message)

    def test_fenetre_fermee_avant_le_depart(self) -> None:
        alertes, _ = _evaluer(heure="16:25", progression=_progression(prevu="15:12", faits=3), vent_kmh=3.0)
        message = alertes[0].message
        self.assertIn("La fenêtre des graines a fermé à 16:00 avant qu'il puisse partir.", message)
        self.assertIn("Il ne partira plus aujourd'hui", message)

    def test_cycle_prevu_apres_la_fermeture(self) -> None:
        # Défaut connu du moteur : à 1,8 mm, le 4ᵉ cycle tombe après la fin de la fenêtre.
        alertes, _ = _evaluer(heure="16:30", progression=_progression(prevu="16:04", faits=3), vent_kmh=3.0)
        self.assertIn("Il tombait après la fermeture de la fenêtre des graines (16:00).", alertes[0].message)

    def test_la_fenetre_fermee_prime_sur_le_vent(self) -> None:
        alertes, _ = _evaluer(heure="16:30", progression=_progression(prevu="15:12", faits=3), vent_kmh=25.0)
        self.assertIn("a fermé à 16:00", alertes[0].message)
        self.assertNotIn("vent", alertes[0].message.lower())

    def test_lancement_rate(self) -> None:
        alertes, _ = _evaluer(raison="ready", vent_kmh=2.0, echec_lancement="Vanne zone 1 indisponible")
        self.assertIn("ne s'est pas lancé : Vanne zone 1 indisponible", alertes[0].message)
        self.assertIn("Vérifie les vannes", alertes[0].message)

    def test_motif_inconnu_reste_lisible(self) -> None:
        alertes, _ = _evaluer(raison="code_futur", vent_kmh=2.0)
        self.assertIn("motif technique « code_futur »", alertes[0].message)

    def test_la_memoire_recue_n_est_pas_modifiee(self) -> None:
        _, memoire = _evaluer()
        copie = copy.deepcopy(memoire)
        _evaluer(memoire, heure="13:53", progression=_progression(faits=2, prevu="15:52", etat="waiting"))
        self.assertEqual(memoire, copie)


class LeDelaiEstReglableTests(unittest.TestCase):
    def test_un_delai_plus_long_attend_d_autant(self) -> None:
        trente = timedelta(minutes=30)
        self.assertEqual(_evaluer(heure="13:20", delai_graines=trente)[0], [])
        self.assertEqual(_evaluer(heure="13:27", delai_graines=trente)[0], [])
        self.assertEqual(len(_evaluer(heure="13:28", delai_graines=trente)[0]), 1)

    def test_un_delai_plus_court_previent_plus_tot(self) -> None:
        self.assertEqual(len(_evaluer(heure="13:08", delai_graines=timedelta(minutes=10))[0]), 1)


def _mesure(cle="capteur_temperature", phrase="la température", nom="Station Température", *, en_panne=True, depuis="12:00"):
    return notifications.Mesure(cle, phrase, nom, en_panne, _a(depuis) if depuis else None)


class MesuresManquantesTests(unittest.TestCase):
    def test_une_heure_sans_mesure_previent_une_fois(self) -> None:
        alertes, memoire = _evaluer(progression=None, heure="12:59", mesures=[_mesure()])
        self.assertEqual(alertes, [], "moins d'une heure : un redémarrage ou un hoquet")
        alertes, memoire = _evaluer(memoire, progression=None, heure="13:00", mesures=[_mesure()])
        self.assertEqual(len(alertes), 1)
        alerte = alertes[0]
        self.assertEqual((alerte.sujet, alerte.titre), ("mesures", "📡 Météo : des mesures manquent"))
        self.assertTrue(alerte.persistante and alerte.pousser and not alerte.resolue)
        self.assertEqual(
            alerte.message,
            "Gazon Intelligent ne reçoit plus : la température (Station Température, depuis 12:00). "
            "En attendant, l'intégration se sert des prévisions de l'entité météo, moins justes pour ton "
            "jardin. Vérifie ces appareils (piles, réseau).",
        )
        alertes, memoire = _evaluer(memoire, progression=None, heure="14:00", mesures=[_mesure()])
        self.assertEqual(alertes, [], "la même panne ne se répète pas")
        self.assertEqual(memoire["mesures"], {"signalee": True, "cles": ["capteur_temperature"]})

    def test_la_liste_qui_change_met_la_trace_a_jour_sans_resonner(self) -> None:
        _, memoire = _evaluer(progression=None, mesures=[_mesure()])
        vent = _mesure("capteur_vent", "le vent", "Station Vent", depuis="12:10")
        alertes, memoire = _evaluer(memoire, progression=None, heure="13:30", mesures=[_mesure(), vent])
        self.assertEqual(len(alertes), 1)
        self.assertFalse(alertes[0].pousser, "le téléphone a déjà été prévenu de cette panne")
        self.assertTrue(alertes[0].persistante)
        self.assertIn("la température (Station Température, depuis 12:00) ; le vent (Station Vent, depuis 12:10)", alertes[0].message)
        self.assertEqual(memoire["mesures"]["cles"], ["capteur_temperature", "capteur_vent"])

    def test_le_retour_se_dit_et_retire_la_trace(self) -> None:
        _, memoire = _evaluer(progression=None, mesures=[_mesure()])
        revenue = _mesure(en_panne=False, depuis=None)
        alertes, memoire = _evaluer(memoire, progression=None, heure="14:05", mesures=[revenue])
        self.assertEqual(len(alertes), 1)
        alerte = alertes[0]
        self.assertTrue(alerte.resolue and alerte.pousser and not alerte.persistante)
        self.assertEqual((alerte.titre, alerte.message), ("📡 Météo : mesures revenues", "Toutes les mesures sont revenues à 14:05."))
        self.assertNotIn("mesures", memoire)
        self.assertEqual(_evaluer(memoire, progression=None, heure="14:07", mesures=[revenue])[0], [])

    def test_une_panne_trop_courte_ne_compte_pas_dans_la_liste(self) -> None:
        recente = _mesure("capteur_vent", "le vent", "Station Vent", depuis="12:50")
        alertes, _ = _evaluer(progression=None, heure="13:20", mesures=[_mesure(), recente])
        self.assertNotIn("le vent", alertes[0].message)

    def test_l_entite_meteo_seule(self) -> None:
        meteo = _mesure("entite_meteo", "l'entité météo", "Prévisions")
        alertes, _ = _evaluer(progression=None, mesures=[meteo])
        self.assertTrue(alertes[0].message.endswith(
            "Sans elle, la pluie annoncée et la température du jour ne sont plus connues. Vérifie l'intégration météo."
        ))

    def test_l_entite_meteo_avec_d_autres(self) -> None:
        meteo = _mesure("entite_meteo", "l'entité météo", "Prévisions")
        alertes, _ = _evaluer(progression=None, mesures=[meteo, _mesure()])
        self.assertIn("n'ont même plus de prévision pour les remplacer", alertes[0].message)

    def test_les_graines_et_les_mesures_ensemble(self) -> None:
        alertes, _ = _evaluer(mesures=[_mesure()])
        self.assertEqual([a.sujet for a in alertes], ["mesures", "graines"])


class LectureDUneEntreeTests(unittest.TestCase):
    MAINTENANT = _a("13:00")

    def _lire(self, etat, *, numerique=True, appareil=None, changement="11:00"):
        return notifications.mesure_d_une_entite(
            cle="capteur_temperature", dans_une_phrase="la température", nom="Station",
            etat=etat, dernier_changement=_a(changement) if changement else None, numerique=numerique,
            derniere_nouvelle_appareil=appareil, maintenant=self.MAINTENANT,
        )

    def test_sans_valeur(self) -> None:
        for etat in ("unavailable", "unknown", "", None, "none", "abc"):
            with self.subTest(etat=etat):
                mesure = self._lire(etat)
                self.assertTrue(mesure.en_panne)
                self.assertEqual(mesure.depuis, _a("11:00"))

    def test_une_valeur_texte_suffit_quand_il_n_en_faut_pas_un_nombre(self) -> None:
        self.assertFalse(self._lire("cloudy", numerique=False).en_panne)
        self.assertTrue(self._lire("unavailable", numerique=False).en_panne)

    def test_l_appareil_muet(self) -> None:
        self.assertFalse(self._lire("17.5", appareil=_a("10:01")).en_panne, "moins de trois heures")
        muet = self._lire("17.5", appareil=_a("10:00"))
        self.assertTrue(muet.en_panne)
        self.assertEqual(muet.depuis, _a("10:00"), "la panne date de la dernière nouvelle de l'appareil")
        self.assertFalse(self._lire("17.5").en_panne, "sans appareil connu, seule la valeur compte")


class CoordinateurMesuresTests(unittest.TestCase):
    """Les entrées lues par le coordinateur : configuration, états, registre des appareils."""

    def _coordinateur(self, etats: dict[str, object], options: dict[str, object], registre=None):
        coord = _coordinateur(options=options)
        coord.hass.states = _FakeStates(etats)
        coord._derniere_nouvelle_de_l_appareil = lambda entity_id: registre.get(entity_id) if registre else None
        coord._get_conf = lambda cle: coord.entry.options.get(cle)
        return coord

    def test_les_entrees_qui_mesurent_seulement(self) -> None:
        maintenant = _a("13:00")
        etats = {
            "sensor.temperature": _FakeState("unavailable", _a("11:00"), {"friendly_name": "Station Température"}),
            "sensor.vent": _FakeState("3.2", _a("12:59"), {"friendly_name": "Station Vent"}),
        }
        coord = self._coordinateur(etats, {
            "capteur_temperature": "sensor.temperature",
            "capteur_vent": "sensor.vent",
            "capteur_pluie_demain": "sensor.pluie_demain",  # une prévision : pas surveillée
            "capteur_pression": "sensor.disparue",
        })
        mesures = coord._mesures_des_sources(maintenant)
        # Dans l'ordre du registre des entrées ; ni la prévision, ni ce qui n'est pas branché.
        self.assertEqual([m.cle for m in mesures], ["capteur_temperature", "capteur_vent", "capteur_pression"])
        par_cle = {m.cle: m for m in mesures}
        self.assertTrue(par_cle["capteur_temperature"].en_panne)
        self.assertEqual(par_cle["capteur_temperature"].depuis, _a("11:00"))
        self.assertEqual(par_cle["capteur_temperature"].nom, "Station Température")
        self.assertFalse(par_cle["capteur_vent"].en_panne)
        # Une entité introuvable est datée de la première fois qu'on la constate.
        self.assertTrue(par_cle["capteur_pression"].en_panne)
        self.assertEqual(par_cle["capteur_pression"].depuis, maintenant)
        plus_tard = coord._mesures_des_sources(_a("14:30"))
        self.assertEqual({m.cle: m for m in plus_tard}["capteur_pression"].depuis, maintenant)

    def test_le_delai_et_les_mesures_arrivent_a_l_alerte(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone"]}, services=services)
        coord._reglages_instance = lambda: {"graines_alerte_retard": 30}
        coord._semis_cycle_progress = lambda snapshot=None: _progression()
        # 13:20 : 22 min de retard, sous le délai réglé de 30 min → rien pour les graines.
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual(services.appels, [], "le réglage « graines_alerte_retard » est ignoré")
        coord._current_datetime = lambda: _a("13:30")
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual([s for _, s, _, _ in services.appels], ["create", "send_message"])

    def test_une_mesure_manquante_part_du_coordinateur(self) -> None:
        services = _Services()
        coord = _coordinateur(options={
            "notification_cibles": ["notify.iphone"], "capteur_temperature": "sensor.temperature",
        }, services=services)
        coord._semis_cycle_progress = lambda snapshot=None: None
        coord._get_conf = lambda cle: coord.entry.options.get(cle)
        coord.hass.states = _FakeStates({
            "sensor.temperature": _FakeState("unavailable", _a("12:00"), {"friendly_name": "Station Température"}),
        })
        coord._derniere_nouvelle_de_l_appareil = lambda entity_id: None
        asyncio.run(coord._async_verifier_alertes({}))
        self.assertEqual([s for _, s, _, _ in services.appels], ["create", "send_message"])
        _, _, trace, _ = services.appels[0]
        self.assertEqual(trace["notification_id"], "gazon_intelligent_entree1_mesures")
        self.assertIn("la température (Station Température, depuis 12:00)", services.appels[1][2]["message"])


class DerniereNouvelleDeLAppareilTests(unittest.TestCase):
    def _coordinateur(self, voisines, etats, *, device_id="station"):
        coord = _coordinateur()
        coord.hass.states = _FakeStates(etats)
        entree = types.SimpleNamespace(device_id=device_id)
        registre = types.SimpleNamespace(async_get=lambda entity_id: entree if entity_id == "sensor.temperature" else None)
        er = types.ModuleType("homeassistant.helpers.entity_registry")
        er.async_get = lambda hass: registre
        er.async_entries_for_device = lambda reg, dev: [types.SimpleNamespace(entity_id=v) for v in voisines]
        return coord, er

    def test_la_plus_recente_des_mesures_voisines(self) -> None:
        import sys
        from unittest.mock import patch

        etats = {
            "sensor.temperature": _FakeState("17", _a("10:00")),
            "sensor.vent": _FakeState("3", _a("12:40")),
            # Plus récents, mais sans valeur ou pas une mesure : ils ne comptent pas.
            "sensor.batterie": _FakeState("unavailable", _a("12:59")),
            "button.identifier": _FakeState("2026-09-17T10:58:00+00:00", _a("12:58")),
        }
        for entity_id, etat in etats.items():
            etat.last_updated = etat.last_changed
        coord, er = self._coordinateur(["sensor.temperature", "sensor.vent", "sensor.batterie", "button.identifier"], etats)
        helpers = types.ModuleType("homeassistant.helpers")
        helpers.entity_registry = er
        with patch.dict(sys.modules, {"homeassistant.helpers": helpers, "homeassistant.helpers.entity_registry": er}):
            self.assertEqual(coord._derniere_nouvelle_de_l_appareil("sensor.temperature"), _a("12:40"))
            # `last_reported` passe devant quand l'intégration relève sans changement.
            etats["sensor.temperature"].last_reported = _a("12:55")
            self.assertEqual(coord._derniere_nouvelle_de_l_appareil("sensor.temperature"), _a("12:55"))
            # Une seule mesure à comparer : rien à juger.
            self.assertIsNone(coord._derniere_nouvelle_de_l_appareil("sensor.inconnue"))
        coord2, er2 = self._coordinateur(["sensor.temperature"], etats)
        helpers.entity_registry = er2
        with patch.dict(sys.modules, {"homeassistant.helpers": helpers, "homeassistant.helpers.entity_registry": er2}):
            self.assertIsNone(coord2._derniere_nouvelle_de_l_appareil("sensor.temperature"))


class LeMoteurRenonceTests(unittest.TestCase):
    def test_une_information_par_jour_sans_trace(self) -> None:
        alertes, memoire = _evaluer(raison="no_objective", motif_decision="pluie_prevue_suffisante")
        self.assertEqual(len(alertes), 1)
        alerte = alertes[0]
        self.assertFalse(alerte.persistante, "ce n'est pas une panne : pas de trace dans Home Assistant")
        self.assertEqual(alerte.titre, "🌧️ Graines : cycles suspendus")
        self.assertIn("(pluie prévue suffisante)", alerte.message)
        self.assertIn("Rien à faire.", alerte.message)
        self.assertEqual(memoire["graines"], {}, "aucun retard ne doit être noté")
        # Même journée, cycle suivant : plus rien.
        alertes, _ = _evaluer(
            memoire, heure="15:40", raison="not_recommended",
            progression=_progression(faits=2, prevu="15:12"),
        )
        self.assertEqual(alertes, [])

    def test_le_lendemain_l_information_peut_revenir(self) -> None:
        _, memoire = _evaluer(raison="no_objective")
        lendemain = JOUR + timedelta(days=1)
        progression = _progression()
        progression["next_due_at"] = _a("12:58", lendemain)
        alertes, _ = _evaluer(memoire, jour=lendemain, raison="no_objective", progression=progression)
        self.assertEqual(len(alertes), 1)


class NouvelleJourneeTests(unittest.TestCase):
    def test_un_retard_d_hier_sans_rattrapage_voit_sa_trace_retiree(self) -> None:
        _, memoire = _evaluer()
        lendemain = JOUR + timedelta(days=1)
        alertes, memoire = _evaluer(
            memoire, jour=lendemain, heure="07:00",
            progression=_progression(faits=0, prevu="08:30", etat="waiting"),
        )
        self.assertEqual(len(alertes), 1)
        self.assertTrue(alertes[0].resolue)
        self.assertEqual(alertes[0].message, "", "un retrait de trace n'envoie rien aux téléphones")
        self.assertEqual(memoire["jour"], "2026-09-18")
        self.assertEqual(memoire["graines"], {})

    def test_une_journee_sans_retard_ne_retire_rien(self) -> None:
        _, memoire = _evaluer(heure="12:30", progression=_progression(etat="waiting"))
        lendemain = JOUR + timedelta(days=1)
        alertes, _ = _evaluer(
            memoire, jour=lendemain, heure="07:00",
            progression=_progression(faits=0, prevu="08:30", etat="waiting"),
        )
        self.assertEqual(alertes, [])


class VerrouDeSecuriteTests(unittest.TestCase):
    def test_une_alerte_a_la_pose_puis_retrait_a_la_levee(self) -> None:
        alertes, memoire = _evaluer(
            progression=None, verrou=True,
            erreur_verrou="la vanne n'a pas confirmé sa fermeture",
            zone_verrou="Zone 1 Arrosage",
        )
        self.assertEqual(len(alertes), 1)
        alerte = alertes[0]
        self.assertEqual(alerte.sujet, "verrou")
        self.assertEqual(alerte.titre, "⚠️ Arrosage automatique verrouillé")
        self.assertIn("(Zone 1 Arrosage)", alerte.message)
        self.assertIn("la vanne n'a pas confirmé sa fermeture", alerte.message)
        # Le seul déverrouillage efface le semis en cours : le message doit le dire.
        self.assertIn("« Retour au mode normal »", alerte.message)
        self.assertIn("efface aussi une phase Semis ou Sursemis", alerte.message)

        alertes, memoire = _evaluer(memoire, progression=None, verrou=True)
        self.assertEqual(alertes, [], "un verrou déjà signalé ne se répète pas")

        alertes, memoire = _evaluer(memoire, progression=None, verrou=False)
        self.assertEqual(len(alertes), 1)
        self.assertTrue(alertes[0].resolue)
        self.assertEqual(alertes[0].sujet, "verrou")
        self.assertEqual(alertes[0].message, "")
        self.assertFalse(memoire["verrou"])

    def test_le_verrou_n_empeche_pas_l_alerte_graines(self) -> None:
        alertes, _ = _evaluer(verrou=True, raison="safety_lock", vent_kmh=2.0)
        self.assertEqual([a.sujet for a in alertes], ["verrou", "graines"])
        self.assertIn("verrou de sécurité", alertes[1].message)


class ErreurTondeuseTests(unittest.TestCase):
    def test_une_nouvelle_erreur_est_signalee_une_seule_fois_puis_retiree(self) -> None:
        alertes, memoire = _evaluer(
            progression=None,
            erreur_tondeuse="blade_blocked",
            libelle_erreur_tondeuse="Lame bloquée",
        )
        self.assertEqual([a.sujet for a in alertes], ["tondeuse"])
        self.assertIn("Lame bloquée", alertes[0].message)
        self.assertEqual(memoire["tondeuse"], "blade_blocked")

        alertes, memoire = _evaluer(
            memoire,
            progression=None,
            erreur_tondeuse="blade_blocked",
            libelle_erreur_tondeuse="Lame bloquée",
        )
        self.assertEqual(alertes, [])

        alertes, memoire = _evaluer(memoire, progression=None, erreur_tondeuse=None)
        self.assertEqual(len(alertes), 1)
        self.assertTrue(alertes[0].resolue)
        self.assertNotIn("tondeuse", memoire)

    def test_une_pause_pluie_n_est_pas_une_panne(self) -> None:
        """La Landroid publie `rain_delay` sur son capteur d'ERREUR : chaque averse aurait
        envoyé « Tondeuse : erreur détectée »."""
        for code in ("rain_delay", "rain_delayed", "weather_delay", "Rain_Delay"):
            with self.subTest(code=code):
                alertes, memoire = _evaluer(progression=None, erreur_tondeuse=code)
                self.assertEqual(alertes, [])
                self.assertNotIn("tondeuse", memoire)
        # Une vraie panne suivie d'une pause pluie : la panne est tenue pour finie.
        _, memoire = _evaluer(progression=None, erreur_tondeuse="blade_blocked")
        alertes, memoire = _evaluer(memoire, progression=None, erreur_tondeuse="rain_delay")
        self.assertEqual([(a.sujet, a.resolue) for a in alertes], [("tondeuse", True)])
        self.assertNotIn("tondeuse", memoire)

    def test_une_categorie_decochee_n_est_pas_memorisee(self) -> None:
        alertes, memoire = _evaluer(
            progression=None,
            erreur_tondeuse="blade_blocked",
            sujets_actifs={"graines", "verrou", "mesures"},
        )
        self.assertEqual(alertes, [])
        self.assertNotIn("tondeuse", memoire)

    def test_la_securite_decochee_se_tait_et_retire_sa_trace(self) -> None:
        sans_securite = {"graines", "mesures", "tondeuse"}
        alertes, memoire = _evaluer(progression=None, verrou=True, sujets_actifs=sans_securite)
        self.assertEqual(alertes, [])
        self.assertNotIn("verrou", memoire)
        # Décochée pendant un verrou déjà signalé : la trace part, sans nouveau message.
        _, memoire = _evaluer(progression=None, verrou=True)
        alertes, memoire = _evaluer(memoire, progression=None, verrou=True, sujets_actifs=sans_securite)
        self.assertEqual([(a.sujet, a.resolue, a.message) for a in alertes], [("verrou", True, "")])
        self.assertNotIn("verrou", memoire)

    def test_les_capteurs_decoches_se_taisent_et_retirent_leur_trace(self) -> None:
        panne = notifications.Mesure("capteur_vent", "le vent", "Station Vent", True, JOUR - timedelta(hours=2))
        sans_capteurs = {"graines", "verrou", "tondeuse"}
        alertes, memoire = _evaluer(progression=None, mesures=[panne], sujets_actifs=sans_capteurs)
        self.assertEqual(alertes, [])
        self.assertNotIn("mesures", memoire)
        _, memoire = _evaluer(progression=None, mesures=[panne])
        self.assertIn("mesures", memoire, "prémisse : la panne a bien été signalée")
        alertes, memoire = _evaluer(memoire, progression=None, mesures=[panne], sujets_actifs=sans_capteurs)
        self.assertEqual([(a.sujet, a.resolue) for a in alertes], [("mesures", True)])
        self.assertNotIn("mesures", memoire)

    def test_graines_decochees_la_nouvelle_journee_ne_dit_rien(self) -> None:
        _, memoire = _evaluer()
        self.assertTrue(memoire["graines"], "prémisse : un retard est suivi")
        lendemain = JOUR + timedelta(days=1)
        alertes, memoire = _evaluer(
            memoire, jour=lendemain, progression=None, sujets_actifs={"verrou", "mesures", "tondeuse"},
        )
        self.assertEqual(alertes, [])
        self.assertEqual(memoire["graines"], {})

    def test_les_graines_peuvent_etre_decochees_sans_couper_la_securite(self) -> None:
        alertes, _ = _evaluer(
            verrou=True,
            sujets_actifs={"verrou", "mesures", "tondeuse"},
        )
        self.assertEqual([a.sujet for a in alertes], ["verrou"])


class ResumeDuGazonTests(unittest.TestCase):
    SNAPSHOT = {
        "phase_dominante": "Sursemis",
        "sous_phase": "Germination",
        "sous_phase_age_days": 1,
        "date_fin": "2026-10-30",
        "semis_daily_cycles_target": 4,
        "semis_cycles_completed_today": 2,
        "surface_cycle_mm": 1.2,
        "semis_followup_due_at": "2026-09-17T10:58:13+00:00",
        "fenetre_optimale": "attendre",
        "reserve_actuelle_mm": 12.0,
        "reserve_utile_mm": 12.0,
        "temperature": 14.6,
        "vent": 2.88,
        "pluie_demain": 0.9,
        "tonte_autorisee": False,
        "tonte_statut": "semis_en_cours",
        "derniere_tonte_date": "2026-09-15",
        "plantules_levee_date": "2026-09-23",
        "plantules_premiere_coupe_date": "2026-10-08",
        "derniere_application": {"libelle": "Floranid Twin Permanent", "date": "2026-09-16"},
        "risque_gazon": "modere",
        "conseil_principal": "Sursemis germination: prochain cycle déjà programmé, attends l'échéance.",
        # Rien de ceci ne doit sortir de la maison.
        "ha_latitude": 47.123456,
        "ha_longitude": -1.654321,
    }

    def test_les_lignes_attendues(self) -> None:
        lignes = notifications.resume_du_gazon(
            self.SNAPSHOT, maintenant=_a("11:00"), arrosage_auto=True,
        )
        self.assertEqual(
            lignes,
            [
                "Phase : Sursemis (Germination, jour 1), jusqu'au 30/10.",
                "Cycles de graines faits aujourd'hui : 2 sur 4 (1,2 mm chacun), prochain vers 12:58.",
                "Moment conseillé : attendre.",
                "Arrosage automatique : activé.",
                "Réserve du sol : 12 / 12 mm.",
                "Météo : 14,6 °C, vent 2,9 km/h, pluie prévue demain 0,9 mm.",
                "Tonte : non autorisée (semis en cours), dernière le 15/09.",
                "Semis : levée attendue le 23/09, première coupe le 08/10.",
                "Dernier produit : Floranid Twin Permanent le 16/09.",
                "Risque pour le gazon : modere.",
                "Conseil du moteur : Sursemis germination: prochain cycle déjà programmé, attends l'échéance.",
            ],
        )

    def test_aucune_coordonnee_ne_sort(self) -> None:
        texte = "\n".join(notifications.resume_du_gazon(self.SNAPSHOT, maintenant=_a("11:00")))
        for fragment in ("47.1", "47,1", "1.65", "1,65", "latitude", "longitude"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, texte)

    def test_phase_normale_et_verrou(self) -> None:
        lignes = notifications.resume_du_gazon(
            {"phase_dominante": "Normal", "date_fin": "2026-10-30", "objectif_mm": 0.0},
            maintenant=_a("11:00"), arrosage_auto=False, blocage="verrou de sécurité posé",
        )
        self.assertEqual(
            lignes,
            [
                "Phase : Normal.",
                "Arrosage du jour : aucun besoin.",
                "Arrosage automatique : coupé (verrou de sécurité posé).",
            ],
        )

    def test_rien_ne_casse_sur_un_etat_vide(self) -> None:
        self.assertEqual(notifications.resume_du_gazon({}, maintenant=_a("11:00")), [])


class OptionsTests(unittest.TestCase):
    def test_les_telephones_sont_nettoyes(self) -> None:
        entree = _FakeEntry(options={
            "notification_cibles": ["notify.iphone", "", "notify.iphone", "light.salon", "notify.ipad"],
        })
        self.assertEqual(notifications.cibles_configurees(entree), ["notify.iphone", "notify.ipad"])

    def test_un_champ_vide_dans_les_options_ne_retombe_pas_sur_la_creation(self) -> None:
        entree = _FakeEntry(
            data={"notification_cibles": ["notify.ancien"]},
            options={"notification_cibles": None},
        )
        self.assertEqual(notifications.cibles_configurees(entree), [])

    def test_valeur_de_creation_et_chaine_seule(self) -> None:
        self.assertEqual(
            notifications.cibles_configurees(_FakeEntry(data={"notification_cibles": "notify.iphone"})),
            ["notify.iphone"],
        )
        self.assertEqual(notifications.cibles_configurees(_FakeEntry()), [])

    def test_alertes_cochees_par_defaut(self) -> None:
        self.assertTrue(notifications.alertes_voulues(_FakeEntry()))
        self.assertFalse(notifications.alertes_voulues(_FakeEntry(options={"alertes_actives": False})))
        self.assertFalse(notifications.alertes_voulues(_FakeEntry(data={"alertes_actives": False})))
        self.assertTrue(notifications.alertes_voulues(
            _FakeEntry(data={"alertes_actives": False}, options={"alertes_actives": True})
        ))

    def test_toutes_les_categories_sont_cochees_par_defaut_et_se_reglent_separement(self) -> None:
        self.assertEqual(notifications.sujets_voulus(_FakeEntry()), {
            "graines", "verrou", "mesures", "tondeuse",
        })
        entree = _FakeEntry(options={
            "notifier_arrosage_graines": False,
            "notifier_capteurs_meteo": False,
        })
        self.assertEqual(notifications.sujets_voulus(entree), {"verrou", "tondeuse"})

    def test_la_veille_intelligente_surveille_toutes_les_categories(self) -> None:
        entree = _FakeEntry(options={
            "mode_notifications": "veille_intelligente",
            "notifier_arrosage_graines": False,
            "notifier_tondeuse": False,
        })
        self.assertEqual(notifications.mode_notifications(entree), "veille_intelligente")
        self.assertEqual(notifications.sujets_voulus(entree), {
            "graines", "verrou", "mesures", "tondeuse",
        })


class _Services:
    """`hass.services` qui note les appels ; `pannes` : les téléphones qui ne répondent pas."""

    def __init__(self, *, pannes: set[str] | None = None, ia: object = None, ia_absente: bool = False) -> None:
        self.appels: list[tuple[str, str, dict[str, object], dict[str, object]]] = []
        self.pannes = pannes or set()
        self.ia = ia
        self.ia_absente = ia_absente

    def has_service(self, domaine: str, service: str) -> bool:
        return not (self.ia_absente and domaine == "ai_task")

    async def async_call(self, domaine, service, donnees, blocking=False, return_response=False):
        self.appels.append((domaine, service, dict(donnees), {"blocking": blocking, "return_response": return_response}))
        if domaine == "notify" and donnees.get("entity_id") in self.pannes:
            raise RuntimeError("téléphone injoignable")
        if domaine == "ai_task":
            if isinstance(self.ia, Exception):
                raise self.ia
            return self.ia
        return None


def _coordinateur(*, options: dict[str, object] | None = None, services: _Services | None = None):
    coord = _build_coordinator()
    coord.entry = _FakeEntry(entry_id="entree1", options=dict(options or {}))
    coord.memory = {"auto_irrigation_enabled": True}
    coord.hass = types.SimpleNamespace(
        services=services or _Services(),
        states=_FakeStates({
            "switch.zone_1": _FakeState("off", datetime.now(timezone.utc), {"friendly_name": "Zone 1 Arrosage"}),
        }),
        config_entries=types.SimpleNamespace(async_get_entry=lambda entry_id: None),
    )
    coord._persist_runtime_state = AsyncMock()
    coord._reglages_instance = lambda: {}
    coord._current_datetime = lambda: _a("13:20")
    coord._watering_session_active = lambda: False
    coord._shared_valve_busy_elsewhere = lambda: False
    coord._semis_cycle_progress = lambda snapshot=None: _progression()
    coord._runtime_state["last_auto_irrigation_reason"] = {"reason": "target_date_future"}
    coord._auto_irrigation_scheduler_task = None
    return coord


SNAPSHOT_VENT = {
    "vent": 17.0,
    "fenetre_optimale": "demain_matin",
    "watering_window_end_minute": 960,
    "phase_dominante": "Sursemis",
    "sous_phase": "Germination",
}


class CoordinateurAlertesTests(unittest.TestCase):
    """Le branchement dans le coordinateur : la valeur suit jusqu'au téléphone et au disque."""

    def test_l_alerte_part_et_la_memoire_est_ecrite_une_fois(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone"]}, services=services)
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual(
            [(d, s) for d, s, _, _ in services.appels],
            [("persistent_notification", "create"), ("notify", "send_message")],
        )
        _, _, trace, _ = services.appels[0]
        self.assertEqual(trace["notification_id"], "gazon_intelligent_entree1_graines")
        _, _, envoi, options = services.appels[1]
        self.assertEqual(envoi["entity_id"], "notify.iphone")
        self.assertIn("17 km/h", envoi["message"])
        self.assertTrue(options["blocking"])
        self.assertIn("1", coord._runtime_state["alertes_gazon"]["graines"])
        coord._persist_runtime_state.assert_awaited_once()

        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual(len(services.appels), 2, "la même alerte est repartie")
        coord._persist_runtime_state.assert_awaited_once()

    def test_sans_telephone_la_trace_reste(self) -> None:
        services = _Services()
        coord = _coordinateur(services=services)
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual([(d, s) for d, s, _, _ in services.appels], [("persistent_notification", "create")])

    def test_alertes_decochees(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"alertes_actives": False, "notification_cibles": ["notify.iphone"]}, services=services)
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual(services.appels, [])
        coord._persist_runtime_state.assert_not_awaited()

    def test_le_reglage_de_vent_de_la_page_est_lu(self) -> None:
        services = _Services()
        coord = _coordinateur(services=services)
        coord._reglages_instance = lambda: {"graines_vent_max": 20}
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        message = services.appels[0][2]["message"]
        self.assertNotIn("au-dessus de la limite", message, "le réglage de vent de la page est ignoré")

    def test_un_arrosage_qui_se_lance_n_est_pas_en_retard(self) -> None:
        services = _Services()
        coord = _coordinateur(services=services)
        coord._auto_irrigation_scheduler_task = types.SimpleNamespace(done=lambda: False)
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual(services.appels, [])

    def test_le_verrou_nomme_la_vanne(self) -> None:
        services = _Services()
        coord = _coordinateur(services=services)
        coord._semis_cycle_progress = lambda snapshot=None: None
        coord._runtime_state["auto_irrigation_safety_lock"] = True
        coord._runtime_state["last_irrigation_execution"] = {
            "last_error": "fermeture non confirmée", "last_failed_zone": "switch.zone_1",
        }
        asyncio.run(coord._async_verifier_alertes({}))
        message = services.appels[0][2]["message"]
        self.assertIn("(Zone 1 Arrosage)", message)
        self.assertIn("fermeture non confirmée", message)

    def test_l_erreur_tondeuse_du_snapshot_arrive_au_telephone(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone"]}, services=services)
        coord._semis_cycle_progress = lambda snapshot=None: None
        asyncio.run(coord._async_verifier_alertes({
            "tondeuse_erreur": "blade_blocked",
            "tondeuse_erreur_libelle": "Lame bloquée",
        }))
        self.assertEqual(
            [(d, s) for d, s, _, _ in services.appels],
            [("persistent_notification", "create"), ("notify", "send_message")],
        )
        self.assertEqual(services.appels[0][2]["notification_id"], "gazon_intelligent_entree1_tondeuse")
        self.assertIn("Lame bloquée", services.appels[1][2]["message"])

    def test_une_categorie_decochee_n_empeche_pas_les_autres(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"notifier_arrosage_graines": False}, services=services)
        coord._runtime_state["auto_irrigation_safety_lock"] = True
        coord._semis_cycle_progress = lambda snapshot=None: _progression()
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual([appel[2]["notification_id"] for appel in services.appels], [
            "gazon_intelligent_entree1_verrou",
        ])

    def test_la_levee_du_verrou_retire_la_trace_sans_rien_envoyer(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone"]}, services=services)
        coord._semis_cycle_progress = lambda snapshot=None: None
        coord._runtime_state["alertes_gazon"] = {"jour": "2026-09-17", "graines": {}, "verrou": True}
        asyncio.run(coord._async_verifier_alertes({}))
        self.assertEqual(
            services.appels,
            [("persistent_notification", "dismiss", {"notification_id": "gazon_intelligent_entree1_verrou"},
              {"blocking": True, "return_response": False})],
        )

    def test_le_rattrapage_retire_la_trace_et_previent(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone"]}, services=services)
        coord._runtime_state["alertes_gazon"] = {
            "jour": "2026-09-17", "graines": {"1": {"prevu": "12:58", "rattrape": False}}, "verrou": False,
        }
        coord._current_datetime = lambda: _a("13:53")
        coord._semis_cycle_progress = lambda snapshot=None: _progression(
            faits=2, prevu="15:52", etat="waiting", fin_dernier="13:52",
        )
        asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))
        self.assertEqual(
            [(d, s) for d, s, _, _ in services.appels],
            [("persistent_notification", "dismiss"), ("notify", "send_message")],
        )
        self.assertEqual(services.appels[1][2]["title"], "🌱 Graines : cycle rattrapé")

    def test_une_trace_mise_a_jour_ne_part_pas_aux_telephones(self) -> None:
        services = _Services()
        hass = types.SimpleNamespace(services=services)
        entree = _FakeEntry(entry_id="e", options={"notification_cibles": ["notify.iphone"]})
        alerte = notifications.Alerte(sujet="mesures", titre="T", message="M", pousser=False)
        asyncio.run(notifications.async_publier(hass, entree, [alerte]))
        self.assertEqual([(d, s) for d, s, _, _ in services.appels], [("persistent_notification", "create")])

    def test_la_veille_intelligente_ne_pousse_pas_les_informations_calmes(self) -> None:
        services = _Services()
        hass = types.SimpleNamespace(services=services)
        entree = _FakeEntry(entry_id="e", options={
            "notification_cibles": ["notify.iphone"],
            "mode_notifications": "veille_intelligente",
        })
        asyncio.run(notifications.async_publier(hass, entree, [
            notifications.Alerte(
                sujet="graines", titre="Cycle rattrapé", message="Tout va bien.",
                persistante=False, niveau="information",
            ),
            notifications.Alerte(
                sujet="verrou", titre="Vanne bloquée", message="Vérifie la vanne.",
                persistante=False,
            ),
        ]))
        self.assertEqual([(d, s) for d, s, _, _ in services.appels], [("notify", "send_message")])
        self.assertEqual(services.appels[0][2]["title"], "Vanne bloquée")

    def test_le_mode_manuel_conserve_les_informations_choisies(self) -> None:
        services = _Services()
        hass = types.SimpleNamespace(services=services)
        entree = _FakeEntry(entry_id="e", options={"notification_cibles": ["notify.iphone"]})
        asyncio.run(notifications.async_publier(hass, entree, [
            notifications.Alerte(
                sujet="graines", titre="Cycle rattrapé", message="Tout va bien.",
                persistante=False, niveau="information",
            ),
        ]))
        self.assertEqual([(d, s) for d, s, _, _ in services.appels], [("notify", "send_message")])

    def test_une_panne_ne_remonte_jamais_dans_le_tick(self) -> None:
        coord = _coordinateur()

        def _casse(snapshot=None):
            raise RuntimeError("panne simulée")

        coord._semis_cycle_progress = _casse
        with self.assertLogs(coordinator_mod._LOGGER, level="ERROR"):
            asyncio.run(coord._async_verifier_alertes(dict(SNAPSHOT_VENT)))

    def test_le_tick_verifie_les_alertes_apres_le_lancement(self) -> None:
        coord = _coordinateur()
        ordre: list[str] = []

        async def _lancement(snapshot):
            ordre.append("lancement")

        async def _alertes(snapshot):
            ordre.append("alertes")

        coord._current_snapshot = lambda: dict(SNAPSHOT_VENT)
        coord._maybe_schedule_auto_irrigation = _lancement
        coord._async_verifier_alertes = _alertes
        asyncio.run(coord._async_auto_irrigation_monitor_tick())
        self.assertEqual(ordre, ["lancement", "alertes"])

    def test_un_refus_ancien_ne_sert_pas_d_explication(self) -> None:
        coord = _coordinateur()
        coord.memory["derniere_action_utilisateur"] = {
            "state": "refuse", "reason": "Vanne indisponible",
            "triggered_at": (_a("13:20") - timedelta(hours=5)).isoformat(),
        }
        self.assertIsNone(coord._refus_de_lancement_recent(_a("13:20")))
        coord.memory["derniere_action_utilisateur"]["triggered_at"] = (_a("13:20") - timedelta(minutes=10)).isoformat()
        self.assertEqual(coord._refus_de_lancement_recent(_a("13:20")), "Vanne indisponible")


class PersistanceTests(unittest.TestCase):
    """Les DEUX listes blanches : écrite sur le disque ET relue au démarrage."""

    def test_aller_retour(self) -> None:
        coord = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        memoire = {"jour": "2026-09-17", "graines": {"1": {"prevu": "12:58", "rattrape": False}}, "verrou": False}
        coord._runtime_state = {"alertes_gazon": memoire}
        coord._ensure_irrigation_runtime_bootstrap = lambda: None
        serialise = coord._serialized_runtime_state()
        self.assertEqual(serialise.get("alertes_gazon"), memoire, "la mémoire des alertes n'atteint pas le disque")
        relu = object.__new__(coordinator_mod.GazonIntelligentCoordinator)
        relu._restore_runtime_state(serialise)
        self.assertEqual(relu._runtime_state.get("alertes_gazon"), memoire, "écrite puis ignorée au démarrage")


class ActionNotificationTests(unittest.TestCase):
    def test_sans_telephone_une_erreur_claire(self) -> None:
        coord = _coordinateur()
        with self.assertRaises(ErreurHA) as erreur:
            asyncio.run(coord.async_envoyer_notification(message="bonjour"))
        self.assertIn("options de Gazon Intelligent", str(erreur.exception))

    def test_sans_message_l_etat_du_gazon(self) -> None:
        services = _Services()
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone", "notify.ipad"]}, services=services)
        coord._current_snapshot = lambda: {"phase_dominante": "Sursemis", "sous_phase": "Germination"}
        resultat = asyncio.run(coord.async_envoyer_notification())
        self.assertEqual(resultat["envoye_a"], ["notify.iphone", "notify.ipad"])
        self.assertEqual(resultat["titre"], "🌱 État du gazon")
        self.assertIn("Phase : Sursemis (Germination).", resultat["message"])
        self.assertIn("Arrosage automatique : activé.", resultat["message"])
        self.assertEqual(
            [(d, s, a["entity_id"]) for d, s, a, _ in services.appels],
            [("notify", "send_message", "notify.iphone"), ("notify", "send_message", "notify.ipad")],
        )

    def test_un_telephone_en_panne_n_arrete_pas_les_autres(self) -> None:
        services = _Services(pannes={"notify.iphone"})
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone", "notify.ipad"]}, services=services)
        resultat = asyncio.run(coord.async_envoyer_notification(titre="Test", message="Bonjour"))
        self.assertEqual(resultat, {"envoye_a": ["notify.ipad"], "titre": "Test", "message": "Bonjour"})

    def test_aucun_telephone_joint(self) -> None:
        services = _Services(pannes={"notify.iphone"})
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone"]}, services=services)
        with self.assertRaises(ErreurHA):
            asyncio.run(coord.async_envoyer_notification(message="Bonjour"))


class ActionIaTests(unittest.TestCase):
    def test_la_question_part_avec_l_etat_et_l_entite_choisie(self) -> None:
        services = _Services(ia={"conversation_id": "x", "data": "  Tout va bien.  "})
        coord = _coordinateur(
            options={"entite_ia": "ai_task.openai_ai_task", "notification_cibles": ["notify.iphone"]},
            services=services,
        )
        coord._current_snapshot = lambda: {"phase_dominante": "Sursemis", "sous_phase": "Germination"}
        resultat = asyncio.run(coord.async_demander_ia("Les graines vont bien ?"))
        self.assertEqual(
            resultat,
            {"question": "Les graines vont bien ?", "reponse": "Tout va bien.", "entite_ia": "ai_task.openai_ai_task"},
        )
        domaine, service, donnees, options = services.appels[0]
        self.assertEqual((domaine, service), ("ai_task", "generate_data"))
        self.assertEqual(donnees["entity_id"], "ai_task.openai_ai_task")
        self.assertIn("Phase : Sursemis (Germination).", donnees["instructions"])
        self.assertIn("Question : Les graines vont bien ?", donnees["instructions"])
        self.assertEqual(options, {"blocking": True, "return_response": True})
        self.assertEqual(len(services.appels), 1, "rien ne doit partir vers les téléphones sans `notifier`")

    def test_notifier_envoie_la_reponse(self) -> None:
        services = _Services(ia={"data": "Arrose ce soir."})
        coord = _coordinateur(options={"notification_cibles": ["notify.iphone"]}, services=services)
        coord._current_snapshot = lambda: {}
        resultat = asyncio.run(coord.async_demander_ia(None, notifier=True))
        self.assertEqual(resultat["envoye_a"], ["notify.iphone"])
        self.assertIsNone(resultat["entite_ia"])
        self.assertNotIn("entity_id", services.appels[0][2], "sans choix, l'IA par défaut de Home Assistant")
        self.assertEqual(services.appels[1][2]["title"], "🤖 Conseil pour le gazon")
        self.assertEqual(services.appels[1][2]["message"], "Arrose ce soir.")

    def test_sans_choix_la_seule_ia_de_la_maison(self) -> None:
        services = _Services(ia={"data": "Oui."})
        coord = _coordinateur(services=services)
        coord.hass.states.async_entity_ids = lambda domaine: ["ai_task.openai_ai_task"] if domaine == "ai_task" else []
        coord._current_snapshot = lambda: {}
        resultat = asyncio.run(coord.async_demander_ia("?"))
        self.assertEqual(resultat["entite_ia"], "ai_task.openai_ai_task")
        self.assertEqual(services.appels[0][2]["entity_id"], "ai_task.openai_ai_task")

    def test_ia_absente(self) -> None:
        coord = _coordinateur(services=_Services(ia_absente=True))
        coord._current_snapshot = lambda: {}
        with self.assertRaises(ErreurHA) as erreur:
            asyncio.run(coord.async_demander_ia("?"))
        self.assertIn("n'est pas disponible", str(erreur.exception))

    def test_erreur_du_fournisseur(self) -> None:
        coord = _coordinateur(services=_Services(ia=RuntimeError("quota dépassé")))
        coord._current_snapshot = lambda: {}
        with self.assertRaises(ErreurHA) as erreur:
            asyncio.run(coord.async_demander_ia("?"))
        self.assertIn("quota dépassé", str(erreur.exception))


if __name__ == "__main__":
    unittest.main()
