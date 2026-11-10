"""Bandeau « En ce moment » quand les données ne sont pas là : titre honnête, capteurs muets listés.

Figé ici : une entité d'assistant indisponible n'écrit plus « Unavailable » en gros titre (« On attend
les données »), une décision connue (attribut `action`) l'emporte sur cet état, et la liste des
capteurs ne s'affiche que si un capteur BRANCHÉ ne répond pas : une entrée non branchée (facultative)
n'est jamais comptée. Le vrai JS est exécuté dans Node.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, cas } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console, structuredClone,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const sorties = cas.map((c) => {
  if (c.condition !== undefined) return JSON.stringify(ctx.conditionActuelle(c.condition));
  const p = Object.create(ctx.Classe.prototype);
  const etats = { ...(c.etats || {}) };
  if (c.assistant) etats["sensor.assistant"] = c.assistant;
  p._hass = { config: { time_zone: "Europe/Paris" }, states: etats };
  p._donnees = { entites: c.assistant ? { assistant: "sensor.assistant" } : {}, sources: c.sources || [] };
  p._arrosageEnCours = () => false;
  p._commandesEnCours = new Set();
  p._blocageMeriteAlerte = () => false;
  p._texteSession = () => "";
  p._sessionActive = () => false;
  if (c.miniMeteo) {
    p._donnees.meteo = "weather.maison";
    p._texteHeure = () => "13 h 33";
    p._prevision = null;
    return p._meteoHtml();
  }
  if (c.meteoMaintenant) {
    p._donnees.meteo = "weather.maison";
    p._previsions = null;
    return p._meteoMaintenantHtml({});
  }
  return p._maintenantHtml({ maintenant: { annee: 2026, mois: 9, jour: 22 } });
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre(cas: list[dict]) -> list[str]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return [texte.replace(" ", " ") for texte in json.loads(sortie.stdout)]


def _source(cle: str, entite: str | None, titre: str = "") -> dict:
    ligne: dict = {"cle": cle, "titre": titre or cle, "numerique": True}
    if entite:
        ligne["entity_id"] = entite
    return ligne


@unittest.skipUnless(NODE, "Node n'est pas installé")
class TitreSansDonneeTests(unittest.TestCase):
    def test_une_entite_indisponible_n_ecrit_plus_unavailable(self) -> None:
        indisponible, inconnue = _rendre([
            {"assistant": {"state": "unavailable", "attributes": {}}},
            {"assistant": {"state": "unknown", "attributes": {}}},
        ])
        for html in (indisponible, inconnue):
            self.assertIn("<h2>On attend les données</h2>", html)
            self.assertNotIn("Unavailable", html)
            self.assertNotIn("Unknown", html)
            self.assertIn("reprennent dès que les données sont revenues", html)

    def test_une_decision_connue_l_emporte_sur_un_etat_indisponible(self) -> None:
        (html,) = _rendre([{"assistant": {"state": "unavailable", "attributes": {"action": "arrosage", "status": "action_required"}}}])
        self.assertNotIn("On attend les données", html)
        self.assertIn("Il faut arroser", html)

    def test_un_etat_normal_ne_change_pas(self) -> None:
        (html,) = _rendre([{"assistant": {"state": "aucune_action", "attributes": {"action": "aucune_action", "status": "no_need"}}}])
        self.assertIn("<h2>Tout va bien</h2>", html)
        self.assertNotIn("On attend les données", html)

    def test_une_entite_absente_de_home_assistant_n_annonce_pas_l_attente(self) -> None:
        (html,) = _rendre([{"assistant": None}])
        self.assertNotIn("On attend les données", html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class CapteursEnAttenteTests(unittest.TestCase):
    ETATS = {
        "sensor.a": {"state": "12.5", "attributes": {}},
        "sensor.b": {"state": "unavailable", "attributes": {}},
        "sensor.c": {"state": "unknown", "attributes": {}},
        "sensor.d": {"state": "texte", "attributes": {}},
    }

    def _rendu(self, sources: list[dict], etats: dict | None = None) -> str:
        (html,) = _rendre([{"assistant": {"state": "aucune_action", "attributes": {"action": "aucune_action"}}, "etats": etats or self.ETATS, "sources": sources}])
        return html

    def test_le_nombre_de_capteurs_qui_repondent_est_donne_sur_ceux_qui_sont_branches(self) -> None:
        html = self._rendu([_source("t", "sensor.a", "Température"), _source("v", "sensor.b", "Vent"), _source("p", "sensor.c", "Pluie")])
        self.assertIn("Capteurs : 1 sur 3 répondent.", html)
        self.assertEqual(re.findall(r'<li class="(att)?"><ha-icon icon="([^"]+)"></ha-icon>([^<]+)</li>', html),
                         [("", "mdi:check", "Température"), ("att", "mdi:pause-circle-outline", "Vent"), ("att", "mdi:pause-circle-outline", "Pluie")])

    def test_une_entree_non_branchee_n_est_jamais_comptee(self) -> None:
        html = self._rendu([_source("t", "sensor.a", "Température"), _source("v", "sensor.b", "Vent"), _source("r", None, "Rosée")])
        self.assertIn("Capteurs : 1 sur 2 répondent.", html)
        self.assertNotIn("Rosée", html)

    def test_rien_n_est_affiche_quand_tous_les_capteurs_repondent(self) -> None:
        html = self._rendu([_source("t", "sensor.a", "Température")])
        self.assertNotIn("capteurs-attente", html)
        self.assertNotIn("Capteurs :", html)

    def test_rien_n_est_affiche_sans_aucun_capteur_branche(self) -> None:
        self.assertNotIn("capteurs-attente", self._rendu([_source("r", None)]))
        self.assertNotIn("capteurs-attente", self._rendu([]))

    def test_une_entite_introuvable_ou_illisible_ne_compte_pas_comme_repondant(self) -> None:
        html = self._rendu([_source("t", "sensor.a", "Température"), _source("x", "sensor.disparu", "Disparu"), _source("d", "sensor.d", "Texte")])
        self.assertIn("Capteurs : 1 sur 3 répondent.", html)
        self.assertEqual(html.count('<li class="att">'), 2)

    def test_le_texte_ne_pretend_pas_savoir_pourquoi_ils_se_taisent(self) -> None:
        html = self._rendu([_source("v", "sensor.b", "Vent")])
        self.assertNotIn("redémarr", html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class ConditionMeteoTests(unittest.TestCase):
    def _condition(self, etat: object) -> list[str]:
        (texte,) = _rendre([{"condition": etat}])
        return json.loads(texte)

    def test_une_condition_connue_garde_son_icone_et_son_libelle(self) -> None:
        self.assertEqual(self._condition("sunny")[0], "mdi:weather-sunny")

    def test_une_entite_meteo_muette_est_en_attente_et_jamais_unavailable(self) -> None:
        for etat in ("unavailable", "unknown", "Unavailable", "", None):
            with self.subTest(etat=etat):
                self.assertEqual(self._condition(etat), ["mdi:weather-cloudy-clock", "Météo en attente"])

    def test_une_condition_inconnue_reste_lisible(self) -> None:
        self.assertEqual(self._condition("light-rain"), ["mdi:weather-cloudy-alert", "Light rain"])

    def test_le_bloc_meteo_du_bandeau_n_ecrit_pas_unavailable(self) -> None:
        muet, connu = _rendre([
            {"etats": {"weather.maison": {"state": "unavailable", "attributes": {}}}, "miniMeteo": True},
            {"etats": {"weather.maison": {"state": "sunny", "attributes": {"temperature": 21.5}}}, "miniMeteo": True},
        ])
        self.assertIn("Météo en attente", muet)
        self.assertNotIn("Unavailable", muet)
        self.assertIn("Ensoleillé", connu)
        self.assertNotIn("Météo en attente", connu)

    def test_la_page_meteo_n_ecrit_pas_unavailable(self) -> None:
        (html,) = _rendre([{"etats": {"weather.maison": {"state": "unavailable", "attributes": {}}}, "meteoMaintenant": True}])
        self.assertIn("Météo en attente", html)
        self.assertNotIn("Unavailable", html)


if __name__ == "__main__":
    unittest.main()
