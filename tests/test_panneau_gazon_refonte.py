"""L'onglet Gazon (refonte 1.0) : le mode en tête, l'escalier des étapes du semis, la composition.

Figé ici : l'escalier n'existe qu'en Semis et Sursemis, ses étapes reprennent exactement les bornes de
`etapesGraines`, la bande rayée de l'attente de la tondeuse suit le réglage du mode (Sursemis :
levée + 1 ; Semis : `semis_reprise_tonte_jours`), le repère « Jour N » est posé au milieu de la journée,
et la phase n'est répétée que si elle diffère du mode. Le vrai JS est exécuté dans Node.
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
const REGLAGES = {
  graines_duree: 28, graines_fin_germination: 7, graines_fin_enracinement: 14, graines_fin_reprise: 21,
  sursemis_levee: 10, semis_reprise_tonte_jours: 21,
};
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  const etats = { phase: c.phase === undefined ? "Normal" : c.phase, risque: "low", etat_hydrique: "" };
  p._s = (cle) => etats[cle];
  p._a = () => undefined;
  p._toutesLesValeurs = () => { if (c.erreurReglages) throw new Error("x"); return { ...REGLAGES, ...(c.reglages || {}) }; };
  p._valeurEntiteReelle = () => undefined;
  p._estAdmin = () => true;
  p._mosaique = (items) => items.map((i) => i[0]).join("\n<!--sep-->\n");
  for (const m of ["_reservoirHtml", "_conseilsHtml", "_tuileRisque", "_tuileReserve"]) p[m] = () => `<i>${m}</i>`;
  if (c.quoi === "escalier") return p._etapesModeHtml(c.contexte);
  return p._ongletGazonHtml(c.contexte);
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


def _escalier(mode: str | None, age: int, **extra: object) -> dict:
    contexte = {"semis": {"mode": mode, "age": age, "coupes": 0}} if mode else {"semis": None}
    return {"quoi": "escalier", "contexte": contexte, **extra}


def _pourcents(html: str, classe: str, propriete: str) -> list[float]:
    return [float(x) for x in re.findall(rf'class="{classe}"[^>]*style="[^"]*{propriete}:([\d.]+)%', html)]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class EscalierDuModeTests(unittest.TestCase):
    def test_pas_d_escalier_hors_semis_et_sursemis(self) -> None:
        sans, normal = _rendre([_escalier(None, 0), _escalier("Normal", 3)])
        self.assertEqual(sans, "")
        self.assertEqual(normal, "")

    def test_les_quatre_etapes_reprennent_les_bornes_des_reglages(self) -> None:
        (html,) = _rendre([_escalier("Semis", 3)])
        self.assertEqual(
            re.findall(r'<li class="[^"]*" style="flex:(\d+)"[^>]*>\s*<b>([^<]+)</b><span>jours (\d+) à (\d+)</span>', html),
            [("8", "Germination", "0", "7"), ("7", "Enracinement", "8", "14"), ("7", "Reprise", "15", "21"), ("6", "Stabilisation", "22", "27")],
        )

    def test_seule_l_etape_du_jour_est_marquee(self) -> None:
        for age, attendue in ((0, "Germination"), (7, "Germination"), (8, "Enracinement"), (21, "Reprise"), (27, "Stabilisation")):
            with self.subTest(age=age):
                (html,) = _rendre([_escalier("Semis", age)])
                marquees = re.findall(r'<li class="ici"[^>]*>\s*<b>([^<]+)</b>', html)
                self.assertEqual(marquees, [attendue])
                self.assertEqual(html.count('aria-current="step"'), 1)

    def test_le_repere_du_jour_est_au_milieu_de_la_journee(self) -> None:
        (html,) = _rendre([_escalier("Semis", 7)])
        (gauche,) = re.findall(r'class="ici-marque" style="left:([\d.]+)%">Jour 7<', html)
        self.assertAlmostEqual(float(gauche), 7.5 / 28 * 100, places=1)

    def test_apres_la_duree_du_suivi_il_n_y_a_plus_de_repere_ni_d_etape_marquee(self) -> None:
        (html,) = _rendre([_escalier("Semis", 40)])
        self.assertNotIn("ici-marque", html)
        self.assertNotIn('aria-current="step"', html)

    def test_le_dernier_jour_du_suivi_a_son_repere_et_le_jour_suivant_n_en_a_plus(self) -> None:
        dernier, suivant = _rendre([_escalier("Semis", 27), _escalier("Semis", 28)])
        self.assertIn("Jour 27", dernier)
        self.assertNotIn("ici-marque", suivant)
        self.assertNotIn('aria-current="step"', suivant)

    def test_l_attente_de_la_tondeuse_suit_le_reglage_du_mode(self) -> None:
        semis, sursemis = _rendre([_escalier("Semis", 3), _escalier("Sursemis", 3)])
        (largeur_semis,) = re.findall(r'class="suspendu" style="width:([\d.]+)%"', semis)
        (largeur_sursemis,) = re.findall(r'class="suspendu" style="width:([\d.]+)%"', sursemis)
        self.assertAlmostEqual(float(largeur_semis), 21 / 28 * 100, places=1)
        self.assertAlmostEqual(float(largeur_sursemis), 11 / 28 * 100, places=1)
        self.assertIn("peut repartir au jour 21", semis)
        self.assertIn("peut repartir au jour 11", sursemis)

    def test_un_reglage_deplace_l_escalier(self) -> None:
        (html,) = _rendre([_escalier("Semis", 3, reglages={"semis_reprise_tonte_jours": 14, "graines_fin_germination": 5})])
        self.assertIn("peut repartir au jour 14", html)
        self.assertIn("jours 0 à 5", html)
        self.assertIn("jours 6 à 14", html)

    def test_reglages_illisibles_ou_duree_nulle_ne_dessinent_rien_et_ne_plantent_pas(self) -> None:
        illisibles, nulle = _rendre([_escalier("Semis", 3, erreurReglages=True), _escalier("Semis", 3, reglages={"graines_duree": 0})])
        self.assertEqual(illisibles, "")
        self.assertEqual(nulle, "")


@unittest.skipUnless(NODE, "Node n'est pas installé")
class OngletGazonTests(unittest.TestCase):
    def _onglet(self, mode: str, phase: str, semis: dict | None) -> str:
        (html,) = _rendre([{"quoi": "onglet", "phase": phase, "contexte": {"mode": mode, "semis": semis, "hauteurConseillee": 4.5, "motif": "Saison"}}])
        return html

    def test_la_phase_n_est_ecrite_que_si_elle_differe_du_mode(self) -> None:
        identique = self._onglet("Normal", "Normal", None)
        differente = self._onglet("Normal", "Hivernage", None)
        self.assertNotIn("Phase :", identique)
        self.assertIn("Phase : Hivernage", differente)

    def test_le_mode_est_en_tete_puis_le_reservoir_puis_les_outils_en_dernier(self) -> None:
        html = self._onglet("Semis", "Semis", {"mode": "Semis", "age": 3, "coupes": 0})
        morceaux = html.split("<!--sep-->")
        self.assertIn("Le mode du gazon", morceaux[0])
        self.assertIn("Semis · jour 3", morceaux[0])
        self.assertIn('class="escalier-mode"', morceaux[0])
        self.assertIn("_reservoirHtml", morceaux[1])
        self.assertIn("Hauteur conseillée", morceaux[2])
        self.assertIn("_tuileRisque", morceaux[2])
        self.assertNotIn("_tuileReserve", html)

    def test_les_boutons_de_mode_restent_dans_la_carte_du_mode(self) -> None:
        html = self._onglet("Semis", "Semis", {"mode": "Semis", "age": 3, "coupes": 0})
        carte = html.split("<!--sep-->")[0]
        self.assertIn('data-dialogue="mode"', carte)
        self.assertIn('data-dialogue="normal"', carte)


if __name__ == "__main__":
    unittest.main()
