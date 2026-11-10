"""La frise des 24 heures du bandeau « En ce moment » dit la vérité sur la journée.

Elle ne recalcule rien : les fenêtres viennent des mêmes fonctions que les dessins de Réglages
(`classeMatin`, `classeGraines`, `classeTonte`). Ce qu'elle ajoute, et que ces tests figent :
la tonte est hachurée quand le gazon ou la machine la retiennent, pleine sinon ; la séance
d'arrosage en cours s'allume ; le curseur « maintenant » est à la bonne place ; le motif d'un
blocage ne s'injecte jamais en HTML brut. Le vrai JS est exécuté dans Node, comme les autres tests.
"""

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
const REGLAGES = {
  tonte_fenetre_ideale_debut: 600, tonte_fenetre_ideale_fin: 840,
  tonte_soir_avant_coucher: 300, tonte_soir_apres_coucher: 30,
  arrosage_ouverture: 225, arrosage_fin_optimale: 480, arrosage_fin_acceptable: 600,
  graines_fenetre_debut: 510, graines_fenetre_fin: 960,
};
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  p._toutesLesValeurs = () => (c.sansReglages ? {} : REGLAGES);
  p._a = (cle, nom) => (c.attrs?.[cle] || {})[nom];
  p._arrosageEnCours = () => Boolean(c.enCours);
  p._fuseau = () => "Europe/Paris";
  const contexte = {
    maintenant: c.sansHeure ? {} : { minute: c.minute ?? 12 * 60 },
    soleil: { lever: 450, coucher: 1200 },
    semis: c.mode ? { mode: c.mode, age: 3, coupes: 0 } : null,
  };
  return p._rubanJourHtml(contexte);
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre(cas: list[dict]) -> list[str]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    # Les heures françaises utilisent des espaces insécables : on compare avec des espaces simples.
    return [html.replace(" ", " ") for html in json.loads(sortie.stdout)]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class RubanJourTests(unittest.TestCase):
    def test_sans_heure_ou_sans_reglages_la_frise_ne_s_affiche_pas(self) -> None:
        sans_heure, sans_reglages = _rendre([{"sansHeure": True}, {"sansReglages": True}])
        self.assertEqual(sans_heure, "")
        self.assertEqual(sans_reglages, "")

    def test_la_fenetre_du_matin_suit_les_reglages(self) -> None:
        (html,) = _rendre([{}])
        self.assertIn("fenêtre du matin, de 3 h 45 à 10 h 00", html)
        self.assertNotIn("fenêtre des graines", html)

    def test_pendant_un_semis_c_est_la_fenetre_des_graines(self) -> None:
        sursemis, semis = _rendre([{"mode": "Sursemis"}, {"mode": "Semis"}])
        for html in (sursemis, semis):
            self.assertIn("fenêtre des graines, de 8 h 30 à 16 h 00", html)
            self.assertNotIn("fenêtre du matin", html)

    def test_la_tonte_est_pleine_quand_elle_est_libre_et_hachuree_quand_elle_est_retenue(self) -> None:
        libre, precaution, inconnue, retenue = _rendre([
            {"attrs": {"tonte_autorisee": {"tonte_statut": "autorisee"}}},
            {"attrs": {"tonte_autorisee": {"tonte_statut": "autorisee_avec_precaution"}}},
            {},
            {"attrs": {"tonte_autorisee": {
                "tonte_statut": "deconseillee", "mowing_block_reason_label": "Sursemis : tonte suspendue jusqu'à J+7.",
            }}},
        ])
        for html in (libre, precaution, inconnue):
            self.assertIn("b-ouvert", html)
            self.assertNotIn("b-ferme", html)
            self.assertIn("fenêtres ouvertes", html)
        self.assertIn("b-ferme", retenue)
        self.assertNotIn("b-ouvert", retenue)
        # Le texte du motif est échappé (l'apostrophe devient &#39;) : jamais de HTML brut venu d'une entité.
        self.assertIn("fermée : sursemis : tonte suspendue jusqu&#39;à J+7", retenue)

    def test_le_motif_d_un_blocage_n_entre_jamais_en_html_brut(self) -> None:
        (html,) = _rendre([{"attrs": {"tonte_autorisee": {
            "tonte_statut": "interdite", "mowing_block_reason_label": '<img src=x onerror="alert(1)">',
        }}}])
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)

    def test_l_arrosage_en_cours_s_allume(self) -> None:
        calme, vivant = _rendre([{}, {"enCours": True}])
        self.assertNotIn("b-live", calme)
        self.assertIn("b-live", vivant)
        self.assertIn("en cours", vivant)

    def test_le_curseur_est_a_la_bonne_heure(self) -> None:
        (html,) = _rendre([{"minute": 17 * 60 + 55}])
        self.assertIn('class="maintenant" style="left:74.65%"', html)
        self.assertIn("17 h 55", html)

    def test_la_frise_est_lisible_sans_la_voir(self) -> None:
        (html,) = _rendre([{}])
        self.assertIn('role="img"', html)
        self.assertIn("aria-label=\"Journée de 0 h à 24 h. Arrosage : fenêtre du matin", html)


if __name__ == "__main__":
    unittest.main()
