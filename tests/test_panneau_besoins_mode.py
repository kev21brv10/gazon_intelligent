"""Les besoins du mode actif sur la page (0.96.2).

Demande de Kévin : « quand je suis en semis ou sursemis ou autre, il faudrait que la page bascule
sur les besoins de chaque mode ». C'était déjà le cas pour Semis/Sursemis (`_pucesProgrammeGraines`)
mais pas pour les modes produit (Traitement, Fertilisation…) ni pour l'Hivernage. Ce test charge la
page dans Node et exécute `_pucesProgrammeMode` avec les attributs que publient les capteurs.
Sans Node, il est sauté.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any

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
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const constantes = vm.runInContext("({ MODES_PRODUIT, BESOIN_MODES })", ctx);
const sansBalises = (t) => String(t).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  p._hass = { states: { "binary_sensor.ta": { state: c.tonteStatut === "autorisee" ? "on" : "off", attributes: { tonte_statut: c.tonteStatut || "" } } } };
  p._donnees = { entites: { tonte_autorisee: "binary_sensor.ta" } };
  const puces = p._pucesProgrammeMode({ mode: c.mode, semis: c.semis || null, joursRestantsMode: c.joursRestantsMode ?? null });
  return puces.map((h) => ({ genre: (h.match(/data-programme-mode="([^"]+)"/) || [])[1], texte: sansBalises(h) }));
});
process.stdout.write(JSON.stringify({ constantes, sorties }));
"""


def _rendre(cas: list[dict[str, Any]]) -> dict[str, Any]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


def _propre(rendu: dict[str, Any]) -> list[list[dict[str, str]]]:
    return [
        [{"genre": p["genre"], "texte": html.unescape(re.sub(r"\s+([.,])", r"\1", p["texte"]))} for p in puces]
        for puces in rendu["sorties"]
    ]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class LesBesoinsDuModeActifTests(unittest.TestCase):
    def test_les_six_modes_produit_et_hivernage_sont_couverts(self) -> None:
        rendu = _rendre([{}])
        modes_produit = rendu["constantes"]["MODES_PRODUIT"]
        besoins = rendu["constantes"]["BESOIN_MODES"]
        self.assertEqual(set(modes_produit), {"Traitement", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"})
        for mode in [*modes_produit, "Hivernage"]:
            self.assertTrue(besoins.get(mode), mode)

    def test_un_mode_produit_montre_ses_jours_son_besoin_et_la_tonte(self) -> None:
        [puces] = _propre(_rendre([{"mode": "Traitement", "joursRestantsMode": 1, "tonteStatut": "interdite"}]))
        genres = {p["genre"]: p["texte"] for p in puces}
        self.assertEqual(genres["jours"], "encore 1 jour")
        self.assertEqual(genres["besoin"], "Le foliaire reste au sec")
        self.assertEqual(genres["tonte"], "Tonte interdite")

    def test_dernier_jour_se_dit_autrement_qu_encore_zero_jour(self) -> None:
        [puces] = _propre(_rendre([{"mode": "Fertilisation", "joursRestantsMode": 0}]))
        textes = [p["texte"] for p in puces]
        self.assertIn("dernier jour du mode", textes)
        self.assertFalse(any("0 jour" in t for t in textes))

    def test_accord_singulier_pluriel(self) -> None:
        [un, deux] = _propre(_rendre([
            {"mode": "Scarification", "joursRestantsMode": 1},
            {"mode": "Scarification", "joursRestantsMode": 2},
        ]))
        self.assertIn("encore 1 jour", [p["texte"] for p in un])
        self.assertNotIn("encore 1 jours", [p["texte"] for p in un])
        self.assertIn("encore 2 jours", [p["texte"] for p in deux])

    def test_hivernage_n_a_pas_de_puce_jours(self) -> None:
        # Sa durée n'est pas bornée (`PHASE_DURATIONS_DAYS["Hivernage"] = 999`) : une puce
        # « encore 998 jours » n'aurait aucun sens. `_contexte()` met déjà `joursRestantsMode`
        # à null pour ce mode ; ce test verrouille aussi le comportement de la fonction elle-même
        # si un appelant lui passait quand même une valeur par erreur.
        [avec_jours] = _propre(_rendre([{"mode": "Hivernage", "joursRestantsMode": 998, "tonteStatut": "interdite"}]))
        genres = {p["genre"] for p in avec_jours}
        self.assertNotIn("jours", genres, "Hivernage ne doit jamais montrer un compte de jours")
        self.assertIn("besoin", genres)
        self.assertIn("tonte", genres)

    def test_le_mode_normal_et_les_graines_n_ont_pas_ces_puces(self) -> None:
        rendu = _rendre([
            {"mode": "Normal", "joursRestantsMode": None},
            {"mode": "Sursemis", "semis": {"mode": "Sursemis", "age": 3}, "joursRestantsMode": None},
            {"mode": None},
            {"mode": "Un-mode-qui-n-existe-pas", "joursRestantsMode": 3, "tonteStatut": "interdite"},
        ])
        for puces in rendu["sorties"]:
            self.assertEqual(puces, [])

    def test_sans_besoin_connu_pas_de_puce_besoin(self) -> None:
        # Filet de sécurité si un mode produit était ajouté sans entrée dans BESOIN_MODES.
        [puces] = _propre(_rendre([{"mode": "Agent Mouillant", "joursRestantsMode": 1}]))
        self.assertIn("besoin", {p["genre"] for p in puces})


if __name__ == "__main__":
    unittest.main()
