"""Conseil par l'IA (0.93.0) : ce qui est envoyé, et ce qui revient.

L'IA ne commande rien et ne doit rien inventer : la consigne le dit, et c'est vérifié ici. Un appel
coûte : aucun ne part sans qu'on le demande, et une panne se lit en clair.
"""

from __future__ import annotations

import asyncio
import importlib
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tests.test_watering_session_monitoring import _FakeEntry  # noqa: F401 - installe les stubs HA

ia = importlib.import_module("custom_components.gazon_intelligent.ia")

MAINTENANT = datetime(2026, 9, 17, 11, 5, tzinfo=ZoneInfo("Europe/Paris"))


class ConsigneTests(unittest.TestCase):
    def test_contenu(self) -> None:
        texte = ia.consigne("Faut-il arroser ?", ["Phase : Sursemis.", "Réserve du sol : 12 mm."], maintenant=MAINTENANT)
        self.assertIn("Réponds en français", texte)
        self.assertIn("Tu ne commandes rien", texte)
        self.assertIn("S'il manque une information, dis-le", texte)
        self.assertIn("État du gazon le 17/09/2026 à 11:05 :\n- Phase : Sursemis.\n- Réserve du sol : 12 mm.", texte)
        self.assertTrue(texte.endswith("Question : Faut-il arroser ?"))

    def test_question_vide(self) -> None:
        for question in (None, "", "   "):
            with self.subTest(question=question):
                texte = ia.consigne(question, [], maintenant=MAINTENANT)
                self.assertTrue(texte.endswith(f"Question : {ia.QUESTION_PAR_DEFAUT}"))
                self.assertIn("- (aucune donnée disponible)", texte)

    def test_question_trop_longue_coupee(self) -> None:
        texte = ia.consigne("a" * 5000, [], maintenant=MAINTENANT)
        self.assertTrue(texte.endswith("Question : " + "a" * ia.QUESTION_MAX_CARACTERES))

    def test_notification_garde_les_faits_et_interdit_les_commandes(self) -> None:
        texte = ia.consigne_notification(
            "Vanne bloquée",
            "La vanne Zone 1 ne s'est pas fermée à 13:20.",
            "critique",
            ["Phase : Sursemis.", "Vent : 12 km/h."],
            maintenant=MAINTENANT,
        )
        self.assertIn("Vanne bloquée", texte)
        self.assertIn("La vanne Zone 1 ne s'est pas fermée à 13:20.", texte)
        self.assertIn("N'invente rien", texte)
        self.assertIn("ne prétends commander aucun appareil", texte)
        self.assertIn("même écrit en lettres", texte)
        self.assertIn("même au conditionnel", texte)


class ReponseTests(unittest.TestCase):
    def test_conseil_notification_suspect_retombe_sur_les_faits(self) -> None:
        faits = "La vanne Zone 1 ne s'est pas fermée à 13:20."
        contexte = ["Arrosage automatique : coupé."]
        for conseil in (
            "Bonjour Camille, la vanne demande une vérification.",
            "Camille, la vanne demande une vérification.",
            "La vanne demande une vérification pour Camille.",
            "La vanne Zone 2 demande une vérification.",
            "Fermez la vanne.",
            "La vanne doit être ouverte.",
            "La vanne demande une vérification.\nArrosez maintenant.",
        ):
            with self.subTest(conseil=conseil):
                self.assertFalse(ia.conseil_notification_utilisable(
                    conseil, faits=faits, contexte=contexte,
                ))
        self.assertTrue(ia.conseil_notification_utilisable(
            "La vanne demande une vérification.", faits=faits, contexte=contexte,
        ))

    def test_conseil_notification_refuse_ordre_conditionnel_ou_infinitif(self) -> None:
        """Un ordre déguisé (conditionnel, infinitif, impératif en -ez, périphrase de conseil)
        n'est pas moins un ordre que « il faut » : le garde-fou ne doit pas s'y laisser prendre."""
        faits = "La vanne Zone 1 ne s'est pas fermée à 13:20."
        contexte = ["Arrosage automatique : coupé."]
        for conseil in (
            "Il faudrait arroser la zone.",
            "Il faudra fermer la vanne.",
            "Il ne faudrait pas relancer l'arrosage.",
            "Il conviendrait de fermer la vanne.",
            "Il convient de vérifier la vanne.",
            "Il serait préférable de fermer la vanne.",
            "Il est conseillé de couper l'arrivée d'eau.",
            "Il est vraiment préférable d'attendre.",
            "Il pourrait être utile de relancer le cycle.",
            "Il vaut mieux couper l'eau.",
            "Mieux vaut fermer la vanne.",
            "Pensez à fermer la vanne.",
            "Assurez-vous de couper l'eau.",
            "Veillez à vérifier la vanne.",
            "Faites attention à la vanne.",
            "Vous pouvez relancer le cycle.",
            "Je recommande de fermer la vanne.",
            "On devrait vérifier la vanne.",
            "La vanne demande une vérification. Arroser dès maintenant.",
            "arroser dès maintenant.",
            # Mêmes formes noyées dans une phrase d'allure neutre : la majuscule initiale d'un
            # ordre est déjà refusée plus haut, ce sont ces formes-là que seuls les motifs d'ordre
            # arrêtent.
            "La vanne reste ouverte, pensez à la fermer.",
            "La vanne reste ouverte, assurez-vous de couper l'eau.",
            "La vanne reste ouverte, veillez à la vérifier.",
            "La vanne reste ouverte, faites attention.",
            "La vanne reste ouverte, vous pouvez relancer le cycle.",
            "La vanne reste ouverte, mieux vaut couper l'eau.",
            "La vanne reste ouverte, je recommande de la fermer.",
            "La vanne reste ouverte, nous conseillons de couper l'eau.",
            "La vanne reste ouverte : fermer la vanne.",
        ):
            with self.subTest(conseil=conseil):
                self.assertFalse(ia.conseil_notification_utilisable(
                    conseil, faits=faits, contexte=contexte,
                ))

    def test_conseil_notification_refuse_quantite_ecrite_en_lettres(self) -> None:
        """« deux heures » vaut « 2 heures » : une durée, un volume ou un horaire écrit en toutes
        lettres, absent des faits, est aussi inventé qu'un chiffre."""
        faits = "La vanne Zone 1 ne s'est pas fermée à 13:20."
        contexte = ["Arrosage automatique : coupé."]
        for conseil in (
            "Il faudrait arroser pendant deux heures.",
            "La vanne est restée ouverte pendant trois heures.",
            "Le cycle reprendra dans un quart d'heure.",
            "Le cycle reprendra dans une demi-heure.",
            "Le cycle reprendra dans une heure.",
            "La vanne a débité quinze minutes de trop.",
            "La vanne a laissé passer cent litres.",
            "Le cycle reprendra à midi.",
            "Le cycle reprendra à minuit.",
        ):
            with self.subTest(conseil=conseil):
                self.assertFalse(ia.conseil_notification_utilisable(
                    conseil, faits=faits, contexte=contexte,
                ))

    def test_conseil_notification_accepte_les_observations_legitimes(self) -> None:
        """Garde-fou inverse : durcir ne doit pas rejeter une simple observation, sinon le
        complément de l'IA disparaît pour rien (mots proches d'un ordre ou d'un nombre, mais
        qui n'en sont pas : « assez », « rendez-vous », « une vérification », « conseillée »)."""
        faits = "La vanne Zone 1 ne s'est pas fermée à 13:20."
        contexte = ["Arrosage automatique : coupé."]
        for conseil in (
            "La vanne demande une vérification.",
            "Une vérification de la vanne est conseillée.",
            "Le sol est assez humide pour que l'arrosage puisse attendre.",
            "Un rendez-vous de maintenance reste possible.",
            "Il est probable que la vanne soit restée ouverte.",
            "Il n'est pas nécessaire d'intervenir pour le moment.",
            "La vanne de la Zone 1 reste à surveiller.",
            "Le cycle reprendra après la fermeture de la vanne.",
            "La tondeuse reste à la station.",
        ):
            with self.subTest(conseil=conseil):
                self.assertTrue(ia.conseil_notification_utilisable(
                    conseil, faits=faits, contexte=contexte,
                ))

    def test_conseil_notification_quantite_ecrite_deja_dans_les_faits_est_permise(self) -> None:
        """Comme pour les chiffres, une quantité en lettres PRÉSENTE dans les faits ou le contexte
        n'est pas une invention ; une autre l'est."""
        faits = "Les deux zones sont à l'arrêt depuis une heure."
        contexte = ["Arrosage automatique : coupé."]
        self.assertTrue(ia.conseil_notification_utilisable(
            "Les deux zones restent surveillées.", faits=faits, contexte=contexte,
        ))
        self.assertTrue(ia.conseil_notification_utilisable(
            "L'arrêt dure depuis une heure.", faits=faits, contexte=contexte,
        ))
        # La casse ne compte pas : « Une heure » en tête de phrase = « une heure » des faits.
        self.assertTrue(ia.conseil_notification_utilisable(
            "Une heure s'est écoulée depuis l'arrêt.", faits=faits, contexte=contexte,
        ))
        self.assertFalse(ia.conseil_notification_utilisable(
            "Les trois zones restent surveillées.", faits=faits, contexte=contexte,
        ))
        self.assertFalse(ia.conseil_notification_utilisable(
            "L'arrêt dure depuis trois heures.", faits=faits, contexte=contexte,
        ))

    def test_formes_de_reponse(self) -> None:
        self.assertEqual(ia.texte_de_la_reponse({"data": "  Bonjour \n"}), "Bonjour")
        self.assertEqual(ia.texte_de_la_reponse({"data": {"text": "Oui"}}), "Oui")
        self.assertEqual(ia.texte_de_la_reponse({"data": {"autre": 1}}), "")
        self.assertEqual(ia.texte_de_la_reponse(None), "")
        self.assertEqual(ia.texte_de_la_reponse("Direct"), "Direct")

    def test_une_cle_vide_ne_masque_pas_une_cle_suivante_remplie(self) -> None:
        # `text` avant `reponse` avant `answer` : une clé présente mais vide ne doit pas être
        # prise pour LA réponse (elle serait rendue comme une IA "qui a répondu sans texte").
        self.assertEqual(ia.texte_de_la_reponse({"data": {"text": "   ", "reponse": "Oui"}}), "Oui")
        self.assertEqual(ia.texte_de_la_reponse({"data": {"text": "", "answer": "Oui"}}), "Oui")
        self.assertEqual(ia.texte_de_la_reponse({"data": {"text": "  ", "reponse": "", "answer": ""}}), "")


class EntiteTests(unittest.TestCase):
    def test_choix(self) -> None:
        self.assertEqual(ia.entite_configuree(_FakeEntry(options={"entite_ia": "ai_task.openai"})), "ai_task.openai")
        self.assertIsNone(ia.entite_configuree(_FakeEntry()))
        self.assertIsNone(ia.entite_configuree(_FakeEntry(options={"entite_ia": "conversation.gpt"})))
        # Champ vidé dans les options : pas de retour à la valeur de création.
        self.assertIsNone(ia.entite_configuree(
            _FakeEntry(data={"entite_ia": "ai_task.ancien"}, options={"entite_ia": None})
        ))
        self.assertEqual(ia.entite_configuree(_FakeEntry(data={"entite_ia": "ai_task.creation"})), "ai_task.creation")


class EntiteUniqueTests(unittest.TestCase):
    class _Etats:
        def __init__(self, ids):
            self._ids = ids

        def async_entity_ids(self, domaine):
            assert domaine == "ai_task"
            return list(self._ids)

    def _hass(self, ids):
        return types.SimpleNamespace(states=self._Etats(ids))

    def test_une_seule_ia_est_prise_d_office(self) -> None:
        self.assertEqual(ia.entite_unique(self._hass(["ai_task.openai"])), "ai_task.openai")
        self.assertIsNone(ia.entite_unique(self._hass([])))
        self.assertIsNone(ia.entite_unique(self._hass(["ai_task.a", "ai_task.b"])), "deux IA : Home Assistant choisit")
        self.assertIsNone(ia.entite_unique(types.SimpleNamespace(states=object())))

    def test_le_choix_des_options_passe_devant(self) -> None:
        hass = self._hass(["ai_task.openai"])
        self.assertEqual(ia.entite_effective(hass, _FakeEntry(options={"entite_ia": "ai_task.ollama"})), "ai_task.ollama")
        self.assertEqual(ia.entite_effective(hass, _FakeEntry()), "ai_task.openai")


class _Hass:
    def __init__(self, reponse=None, *, present: bool = True, attente: float = 0.0) -> None:
        self.appels: list[tuple[str, str, dict]] = []
        self._reponse = reponse
        self._present = present
        self._attente = attente
        self.services = self

    def has_service(self, domaine: str, service: str) -> bool:
        return self._present and (domaine, service) == ("ai_task", "generate_data")

    async def async_call(self, domaine, service, donnees, blocking=False, return_response=False):
        self.appels.append((domaine, service, dict(donnees)))
        if self._attente:
            await asyncio.sleep(self._attente)
        if isinstance(self._reponse, Exception):
            raise self._reponse
        return self._reponse


class DemanderTests(unittest.TestCase):
    def test_reponse(self) -> None:
        hass = _Hass({"data": "Tout va bien."})
        texte = asyncio.run(ia.async_demander(hass, "consigne", entite="ai_task.openai"))
        self.assertEqual(texte, "Tout va bien.")
        self.assertEqual(
            hass.appels,
            [("ai_task", "generate_data", {
                "task_name": ia.NOM_DE_LA_TACHE, "instructions": "consigne", "entity_id": "ai_task.openai",
            })],
        )

    def test_sans_entite_pas_de_champ(self) -> None:
        hass = _Hass({"data": "Oui"})
        asyncio.run(ia.async_demander(hass, "consigne", entite=None))
        self.assertNotIn("entity_id", hass.appels[0][2])

    def test_pannes_lisibles(self) -> None:
        cas = {
            "absente": (_Hass(present=False), "n'est pas disponible"),
            "refus": (_Hass(RuntimeError("clé invalide")), "L'IA a refusé la demande : clé invalide"),
            "vide": (_Hass({"data": ""}), "sans texte"),
        }
        for nom, (hass, attendu) in cas.items():
            with self.subTest(cas=nom):
                with self.assertRaises(ia.IaIndisponible) as erreur:
                    asyncio.run(ia.async_demander(hass, "consigne", entite=None))
                self.assertIn(attendu, str(erreur.exception))

    def test_delai_depasse(self) -> None:
        hass = _Hass({"data": "trop tard"}, attente=0.5)
        ancien = ia.DELAI_REPONSE_S
        ia.DELAI_REPONSE_S = 0.05
        try:
            with self.assertRaises(ia.IaIndisponible) as erreur:
                asyncio.run(ia.async_demander(hass, "consigne", entite=None))
        finally:
            ia.DELAI_REPONSE_S = ancien
        self.assertIn("n'a pas répondu", str(erreur.exception))

    def test_le_delai_personnalise_des_notifications_est_reellement_applique(self) -> None:
        # `notifications.py` passe `delai_s=ia.DELAI_NOTIFICATION_S` (15 s) pour ne jamais retenir
        # une alerte le temps du délai par défaut (90 s). Sans le paramètre honoré, une réponse
        # plus lente que 15 s mais plus rapide que 90 s passerait à tort pour un succès.
        hass = _Hass({"data": "réponse lente"}, attente=0.2)
        with self.assertRaises(ia.IaIndisponible) as erreur:
            asyncio.run(ia.async_demander(hass, "consigne", entite=None, delai_s=0.05))
        self.assertIn("n'a pas répondu en 0.05", str(erreur.exception))
        # La même réponse, avec un délai personnalisé assez large, aboutit normalement.
        hass = _Hass({"data": "réponse lente"}, attente=0.05)
        texte = asyncio.run(ia.async_demander(hass, "consigne", entite=None, delai_s=1))
        self.assertEqual(texte, "réponse lente")


if __name__ == "__main__":
    unittest.main()
