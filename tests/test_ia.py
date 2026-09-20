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


class ReponseTests(unittest.TestCase):
    def test_formes_de_reponse(self) -> None:
        self.assertEqual(ia.texte_de_la_reponse({"data": "  Bonjour \n"}), "Bonjour")
        self.assertEqual(ia.texte_de_la_reponse({"data": {"text": "Oui"}}), "Oui")
        self.assertEqual(ia.texte_de_la_reponse({"data": {"autre": 1}}), "")
        self.assertEqual(ia.texte_de_la_reponse(None), "")
        self.assertEqual(ia.texte_de_la_reponse("Direct"), "Direct")


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


if __name__ == "__main__":
    unittest.main()
