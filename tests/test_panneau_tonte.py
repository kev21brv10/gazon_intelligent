"""La page Tonte garde un seul badge pour le gazon, distinct de la machine."""

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
  p._hass = {
    config: { time_zone: "Europe/Paris" },
    states: {
      "binary_sensor.tonte": {
        state: c.gazon ? "on" : "off",
        attributes: {
          tonte_statut: c.statut,
          gazon_permet_tonte: c.gazon,
          machine_permet_tonte: c.machine,
          tondeuse_nom: "Landroid",
          tondeuse_statut_libelle: c.machine ? "A la station" : "Indisponible",
          tondeuse_batterie: 80,
          ...(c.attrs || {}),
        },
      },
    },
  };
  p._donnees = { entites: { tonte_autorisee: "binary_sensor.tonte", tonte_etat: "binary_sensor.tonte" } };
  p._mosaique = (items) => items.map((item) => item[0]).join("");
  p._coordinationHtml = () => "";
  if (!c.travail) p._travailHtml = () => "";
  p._hauteursHtml = () => "";
  p._pousseHtml = () => "";
  p._tonduAujourdhui = () => true;
  return c.travail ? p._travailHtml() : p._ongletTonteHtml(c.contexte || {});
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre() -> list[str]:
    assert NODE
    cas = [
        {"statut": "autorisee", "gazon": True, "machine": False},
        {"statut": "deconseillee", "gazon": True, "machine": True},
        {"statut": "interdite", "gazon": False, "machine": True},
    ]
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(sortie.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class PastilleTonteTests(unittest.TestCase):
    def test_un_seul_badge_decrit_le_gazon_sans_le_confondre_avec_la_machine(self) -> None:
        autorisee, deconseillee, interdite = _rendre()
        self.assertIn("Gazon : prêt", autorisee)
        self.assertIn("Pas disponible", autorisee)
        self.assertIn("Gazon : tonte à éviter", deconseillee)
        self.assertIn("Gazon : pas prêt", interdite)
        for html in (autorisee, deconseillee, interdite):
            self.assertEqual(html.count("Gazon :"), 1)
            self.assertNotIn("Tonte :", html)

    def test_un_travail_inacheve_a_quai_est_affiche_en_pause(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn('travail_en_pause: "Travail en pause à la base"', source)
        self.assertIn('etat === "en_pause" ? "en pause à la base"', source)

    def test_un_ancien_travail_est_separe_de_l_activite_actuelle(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn('a("mower_job_resume_possible") === true', source)
        self.assertIn("<b>Travail précédent :</b>", source)
        self.assertIn("reprise possible", source)
        self.assertIn("progres !== null && !reprisePossible", source)

        sortie = subprocess.run(
            [NODE, "-e", SCRIPT],
            input=json.dumps(
                {
                    "chemin": str(PANNEAU),
                    "cas": [
                        {
                            "statut": "autorisee",
                            "gazon": True,
                            "machine": True,
                            "travail": True,
                            "attrs": {
                                "mower_job_progress_pct": 18,
                                "mower_job_completion_state": "repos",
                                "mower_job_resume_possible": True,
                                "mower_job_paused_since": "2026-09-19T14:00:00+02:00",
                                "mower_auto_declaration_state": "travail_au_repos",
                            },
                        }
                    ],
                }
            ),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        html = json.loads(sortie.stdout)[0]
        self.assertIn("Travail précédent :</b> 18 %", html)
        self.assertIn("reprise possible", html)
        self.assertNotIn('role="progressbar"', html)

    def test_le_cycle_autonome_et_la_reprise_sont_expliques(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn("la tondeuse gère seule ses retours batterie et ses redéparts", source)
        self.assertIn("il envoie une seule reprise", source)
        self.assertIn("Cycle autonome : recharges gérées par la tondeuse", source)
        self.assertIn("Reprise attendue après un rappel de l'intégration", source)

    def test_le_rythme_de_tonte_dit_quand_semis_ou_sursemis_l_ajuste(self) -> None:
        cas = [
            {"statut": "interdite", "gazon": False, "machine": True, "attrs": {"mowing_frequency_label": "0 / semaine"}},
            {"statut": "interdite", "gazon": False, "machine": True, "attrs": {"mowing_frequency_label": "0 / semaine"}, "contexte": {"semis": {"mode": "Semis"}}},
            {"statut": "interdite", "gazon": False, "machine": True, "attrs": {"mowing_frequency_label": "0 / semaine"}, "contexte": {"semis": {"mode": "Sursemis"}}},
        ]
        sortie = subprocess.run(
            [NODE, "-e", SCRIPT],
            input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        normal, semis, sursemis = json.loads(sortie.stdout)
        self.assertIn("Ce mois-ci : 0 / semaine", normal)
        self.assertIn("Rythme actuel : 0 / semaine (Semis)", semis)
        self.assertIn("Rythme actuel : 0 / semaine (Sursemis)", sursemis)
        self.assertNotIn("Ce mois-ci", semis)
        self.assertNotIn("Ce mois-ci", sursemis)


if __name__ == "__main__":
    unittest.main()
