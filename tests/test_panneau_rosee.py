"""La page « Herbe mouillée » suit le verdict du moteur, y compris la rosée maintenue (hystérésis)."""

from __future__ import annotations

import json
from pathlib import Path
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
  const p = Object.create(ctx.Classe.prototype);
  p._donnees = { meteo: "weather.maison" };
  p._hass = { states: { "weather.maison": { state: c.meteo || "cloudy", attributes: c.pointDeRosee === undefined ? {} : { dew_point: c.pointDeRosee } } } };
  p._sourceMeteo = (cle) => (cle === "capteur_rosee" && c.capteurRosee !== undefined ? { entity_id: "sensor.rosee", nom: "Rosée" } : null);
  p._lectureSource = () => (c.capteurRosee !== undefined
    ? { statut: "ok", nombre: c.capteurRosee, etat: { state: String(c.capteurRosee), attributes: {} } }
    : { statut: "absent", nombre: null });
  p._mesureMeteo = (cle) => {
    if (cle === "capteur_temperature" && c.temperature !== undefined) return { valeur: c.temperature, unite: "°C", jardin: true };
    if (cle === "capteur_humidite" && c.humidite !== undefined) return { valeur: c.humidite, unite: "%", jardin: true };
    return null;
  };
  p._sante = () => (c.sante === undefined ? {} : c.sante);
  return p._herbeMouillee();
});
process.stdout.write(JSON.stringify(sorties));
"""


def _jouer(cas: list[dict]) -> list[dict | None]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class HerbeMouilleeSuitLeMoteurTests(unittest.TestCase):
    # Écart 2,2 °C et humidité 87 % : la règle d'entrée ne voit plus de rosée.
    BANDE = {"temperature": 16.2, "pointDeRosee": 14.0, "humidite": 87}

    def test_une_rosee_maintenue_par_le_moteur_est_affichee_mouillee(self) -> None:
        """Relevé de contre-lecture : le moteur gardait l'herbe mouillée, la page disait « sèche »."""
        (sortie,) = _jouer([{**self.BANDE, "sante": {"rosee_maintenue": True}}])
        self.assertTrue(sortie["mouillee"])
        self.assertIn("rosée maintenue", sortie["raison"])
        self.assertIn("air à 2,2", sortie["raison"])  # l'écart lu, avec l'espace insécable de la page

    def test_sans_rosee_maintenue_la_meme_bande_reste_seche(self) -> None:
        """La page n'invente pas de mémoire : elle lit celle du moteur."""
        for sante in ({}, {"rosee_maintenue": False}, {"rosee_maintenue": None}, {"rosee_maintenue": "oui"}):
            with self.subTest(sante=sante):
                (sortie,) = _jouer([{**self.BANDE, "sante": sante}])
                self.assertFalse(sortie["mouillee"])

    def test_la_raison_reste_lisible_sans_point_de_rosee(self) -> None:
        (sortie,) = _jouer([{"humidite": 87, "sante": {"rosee_maintenue": True}}])
        self.assertTrue(sortie["mouillee"])
        self.assertNotIn("—", sortie["raison"])

    def test_un_capteur_de_rosee_branche_garde_la_priorite(self) -> None:
        """Le moteur ne maintient que la rosée ESTIMÉE : une mesure directe se lit telle quelle."""
        sec, mouille = _jouer([
            {**self.BANDE, "capteurRosee": 0, "sante": {"rosee_maintenue": True}},
            {**self.BANDE, "capteurRosee": 1, "sante": {}},
        ])
        self.assertFalse(sec["mouillee"])
        self.assertTrue(mouille["mouillee"])

    def test_les_regles_d_entree_sont_inchangees(self) -> None:
        ecart, humidite, brouillard, rien, sec = _jouer([
            {"temperature": 16.0, "pointDeRosee": 14.0},
            {"humidite": 88},
            {"meteo": "fog"},
            {},
            {"temperature": 20.0, "pointDeRosee": 10.0, "humidite": 50},
        ])
        self.assertTrue(ecart["mouillee"])
        self.assertTrue(humidite["mouillee"])
        self.assertTrue(brouillard["mouillee"])
        self.assertIsNone(rien)
        self.assertFalse(sec["mouillee"])


if __name__ == "__main__":
    unittest.main()
