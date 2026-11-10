"""L'onglet Tonte (refonte 1.0) : trois portes, une frise des fenêtres, une règle de hauteur, une lame.

Figé ici : la tondeuse « sort quand les trois sont au vert » (gazon, créneau, machine), la règle qui dit
si la lame est au cran conseillé, plus basse ou plus haute, la fenêtre « Lame » (bornes = celles de la
machine ET de l'entité, mm ramenés en cm et inversement) et la frise qui ne montre que la tonte et le
soleil. Le vrai JS est exécuté dans Node, comme les autres tests du panneau.
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
  tonte_fenetre_ideale_debut: 600, tonte_fenetre_ideale_fin: 840,
  tonte_soir_avant_coucher: 300, tonte_soir_apres_coucher: 30,
  arrosage_ouverture: 225, arrosage_fin_optimale: 480, arrosage_fin_acceptable: 600,
  graines_fenetre_debut: 510, graines_fenetre_fin: 960,
};
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  const attrs = c.attrs || {};
  const etats = { hauteur_coupe_tondeuse: c.lameMm === undefined ? "30" : c.lameMm, hauteur_tonte: c.conseil === undefined ? "4" : c.conseil };
  p._a = (cle, nom) => (attrs[cle] || {})[nom];
  p._s = (cle) => (etats[cle] === null ? undefined : etats[cle]);
  p._estAdmin = () => c.admin !== false;
  p._donnees = { entites: c.sansEntite ? {} : { hauteur_coupe_tondeuse: "number.lame" } };
  p._entite = (cle) => (cle === "hauteur_coupe_tondeuse" ? { attributes: c.entite || { unit_of_measurement: "mm", min: 10, max: 120, step: 5 } } : undefined);
  p._valeurEntite = (cle) => (cle === "hauteur_min_tondeuse_cm" ? (c.machine || [3, 6])[0] : cle === "hauteur_max_tondeuse_cm" ? (c.machine || [3, 6])[1] : undefined);
  p._toutesLesValeurs = () => REGLAGES;
  p._arrosageEnCours = () => false;
  p._fuseau = () => "Europe/Paris";
  const d = { nom: "lame", valeur: c.valeur };
  if (c.quoi === "regle") return p._hauteursHtml({ maintenant: { minute: 720 } });
  if (c.quoi === "infos") return JSON.stringify(p._lameInfos());
  if (c.quoi === "effet") return p._lameEffetHtml(d);
  if (c.quoi === "bouton") return JSON.stringify(p._lameBouton(d));
  if (c.quoi === "frise") return p._fenetresTonteHtml({ maintenant: c.sansHeure ? {} : { minute: 720 }, soleil: { lever: 450, coucher: 1200 }, semis: null });
  // l'onglet entier, sans ses voisins
  p._tonduAujourdhui = () => false;
  p._mosaique = (items) => items.map((i) => i[0]).join("");
  for (const m of ["_fenetresTonteHtml", "_hauteursHtml", "_travailHtml", "_pousseHtml", "_coordinationHtml", "_pilotageTondeuseEtatHtml", "_motifsBlocageTonteHtml"]) p[m] = () => "";
  return p._ongletTonteHtml({ maintenant: { annee: 2026, mois: 9, jour: 22, minute: 720 }, semis: null });
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre(cas: list[dict]) -> list[str]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return [texte.replace(" ", " ") for texte in json.loads(sortie.stdout)]


def _tonte(statut: str, gazon: bool, machine: bool, **extra: str) -> dict:
    return {"attrs": {"tonte_autorisee": {
        "tonte_statut": statut, "gazon_permet_tonte": gazon, "machine_permet_tonte": machine,
        "tondeuse_nom": "Landroid", "tondeuse_statut_libelle": "À la base", "tondeuse_batterie": 80, **extra,
    }}}


def _portes(html: str) -> dict[str, tuple[str, str]]:
    trouvees = re.findall(r'data-axe="(\w+)" data-etat="(\w+)">\s*<h4>[^<]*</h4><div class="etat">([^<]*)</div>', html)
    return {axe: (etat, texte) for axe, etat, texte in trouvees}


def _regle(lame_mm: str | None, conseil: str | None, **extra: object) -> dict:
    return {
        "quoi": "regle", "lameMm": lame_mm, "conseil": conseil,
        "attrs": {"tonte_etat": {"tondeuse_hauteur_coupe_mm": float(lame_mm) if lame_mm else None},
                  "hauteur_tonte": {"hauteur_tonte_min_cm": 3, "hauteur_tonte_max_cm": 6, **extra}},
    }


@unittest.skipUnless(NODE, "Node n'est pas installé")
class PortesTonteTests(unittest.TestCase):
    def test_trois_portes_quand_le_creneau_est_connu(self) -> None:
        (html,) = _rendre([_tonte("autorisee", True, True, mowing_window_label="Idéal", mowing_window_state="ideal")])
        self.assertIn("La tondeuse sort quand les trois sont au vert", html)
        self.assertEqual(_portes(html), {"gazon": ("oui", "Prêt"), "creneau": ("oui", "Idéal"), "machine": ("oui", "Disponible")})

    def test_le_creneau_a_eviter_est_orange_et_le_creneau_bloque_est_rouge(self) -> None:
        eviter, bloque = _rendre([
            _tonte("autorisee", True, True, mowing_window_label="À éviter", mowing_window_state="discouraged", mowing_window_reason="Température élevée : à éviter."),
            _tonte("autorisee", True, True, mowing_window_label="Bloqué", mowing_window_state="blocked"),
        ])
        self.assertEqual(_portes(eviter)["creneau"], ("attention", "À éviter"))
        self.assertIn("Température élevée : à éviter.", eviter)
        self.assertEqual(_portes(bloque)["creneau"], ("non", "Bloqué"))

    def test_sans_creneau_le_titre_ne_promet_pas_trois_portes(self) -> None:
        (html,) = _rendre([_tonte("autorisee", True, True)])
        self.assertNotIn("les trois sont au vert", html)
        self.assertIn("Ce qui décide de la tonte", html)
        self.assertNotIn('data-axe="creneau"', html)

    def test_le_motif_du_blocage_est_le_detail_de_la_porte_du_gazon(self) -> None:
        (html,) = _rendre([_tonte("interdite", False, True, mowing_block_reason_label="Sursemis : tonte suspendue jusqu'à J+7.")])
        self.assertEqual(_portes(html)["gazon"], ("non", "Pas prêt"))
        self.assertIn("Sursemis : tonte suspendue jusqu&#39;à J+7.", html)

    def test_la_prochaine_tonte_et_la_batterie_sont_dans_l_en_tete(self) -> None:
        (html,) = _rendre([{**_tonte("autorisee", True, True), "attrs": {
            **_tonte("autorisee", True, True)["attrs"], "prochaine_tonte": {"target_date": "2026-10-05"}}}])
        self.assertIn("Prochaine tonte", html)
        self.assertIn("Lundi 5 octobre", html)
        self.assertIn('class="batterie"', html)
        self.assertIn("width:80%", html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class RegleHauteurTests(unittest.TestCase):
    def test_une_lame_plus_basse_que_le_conseil_le_dit_et_garde_deux_reperes(self) -> None:
        (html,) = _rendre([_regle("30", "4")])
        self.assertIn("La lame est plus basse que le conseil (4 cm)", html)
        self.assertIn("regle-repere lame bas", html)
        self.assertIn("regle-repere conseil", html)
        self.assertIn("Lame 3 cm", html)
        self.assertIn("Conseillé 4 cm", html)

    def test_une_lame_au_cran_conseille_fusionne_les_reperes(self) -> None:
        (html,) = _rendre([_regle("40", "4")])
        self.assertIn("La lame est au cran conseillé, 4 cm", html)
        self.assertIn("Lame et conseil 4 cm", html)
        self.assertNotIn("regle-repere conseil", html)

    def test_une_lame_plus_haute_que_le_conseil_est_orange(self) -> None:
        (html,) = _rendre([_regle("50", "4")])
        self.assertIn("La lame est plus haute que le conseil (4 cm)", html)
        self.assertIn("regle-repere lame haut", html)

    def test_les_bornes_de_la_tondeuse_et_le_motif_sont_dits(self) -> None:
        (html,) = _rendre([_regle("30", "4", hauteur_tonte_motif="Sursemis : lame courte.")])
        self.assertIn("La tondeuse va de 3 cm à 6 cm.", html)
        self.assertIn("Sursemis : lame courte.", html)

    def test_sans_lame_ni_conseil_rien_ne_s_affiche(self) -> None:
        (html,) = _rendre([_regle(None, None)])
        self.assertEqual(html, "")

    def test_le_bouton_n_existe_que_pour_un_administrateur_avec_l_entite(self) -> None:
        admin, lecteur, sans_entite = _rendre([_regle("30", "4"), {**_regle("30", "4"), "admin": False}, {**_regle("30", "4"), "sansEntite": True}])
        self.assertIn('data-dialogue="lame"', admin)
        self.assertNotIn('data-dialogue="lame"', lecteur)
        self.assertNotIn('data-dialogue="lame"', sans_entite)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class FenetreLameTests(unittest.TestCase):
    def test_les_bornes_sont_l_intersection_de_la_machine_et_de_l_entite(self) -> None:
        defaut, serre, large = _rendre([
            {"quoi": "infos"},
            {"quoi": "infos", "machine": [3, 6], "entite": {"unit_of_measurement": "mm", "min": 40, "max": 55, "step": 5}},
            {"quoi": "infos", "machine": [1, 15], "entite": {"unit_of_measurement": "mm", "min": 10, "max": 120, "step": 5}},
        ])
        for sortie, attendu in ((defaut, (3, 6, 0.5)), (serre, (4, 5.5, 0.5)), (large, (1, 12, 0.5))):
            i = json.loads(sortie)
            self.assertEqual((i["min"], i["max"], i["pas"]), attendu)
        self.assertEqual(json.loads(defaut)["actuelle"], 3)
        self.assertAlmostEqual(json.loads(defaut)["facteur"], 0.1)

    def test_une_entite_en_cm_n_est_pas_divisee(self) -> None:
        (sortie,) = _rendre([{"quoi": "infos", "lameMm": "3.5", "entite": {"unit_of_measurement": "cm", "min": 1, "max": 12, "step": 0.5}}])
        i = json.loads(sortie)
        self.assertEqual((i["facteur"], i["actuelle"], i["pas"]), (1, 3.5, 0.5))

    def test_l_effet_compare_au_conseil_et_refuse_hors_des_crans(self) -> None:
        conseil, bas, haut, trop_haut, texte = _rendre([
            {"quoi": "effet", "valeur": "4"}, {"quoi": "effet", "valeur": "3.5"}, {"quoi": "effet", "valeur": "5"},
            {"quoi": "effet", "valeur": "7"}, {"quoi": "effet", "valeur": "abc"},
        ])
        self.assertIn("C'est le cran conseillé, 4 cm", conseil)
        self.assertIn("Plus bas que le conseil (4 cm)", bas)
        self.assertIn("note alerte", bas)
        self.assertIn("Plus haut que le conseil (4 cm)", haut)
        self.assertNotIn("note alerte", haut)
        for hors in (trop_haut, texte):
            self.assertIn("Saisir une hauteur entre 3 cm et 6 cm", hors)
            self.assertNotIn("se calcule depuis cette lame", hors)

    def test_le_bouton_ne_part_pas_sans_changement_ni_hors_des_crans(self) -> None:
        inchange, change, hors, invalide = _rendre([
            {"quoi": "bouton", "valeur": "3"}, {"quoi": "bouton", "valeur": "3.5"},
            {"quoi": "bouton", "valeur": "9"}, {"quoi": "bouton", "valeur": ""},
        ])
        self.assertTrue(json.loads(inchange)["off"])
        self.assertEqual(json.loads(change), {"texte": "Enregistrer 3,5 cm", "off": False})
        self.assertTrue(json.loads(hors)["off"])
        self.assertTrue(json.loads(invalide)["off"])

    def test_la_fenetre_est_branchee_et_ecrit_en_millimetres(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn('if (this._dialogue?.nom === "lame" && this._fenetre.contains(cible))', source)
        self.assertIn('appel = ["number", "set_value", { entity_id: entityId, value: Math.round((v / i.facteur) * 100) / 100 }];', source)
        self.assertIn("if (!this._donnees?.entites?.hauteur_coupe_tondeuse) return;", source)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class FriseFenetresTests(unittest.TestCase):
    def test_la_frise_ne_montre_que_la_tonte_et_le_soleil(self) -> None:
        (html,) = _rendre([{"quoi": "frise"}])
        self.assertIn("Les fenêtres de la journée", html)
        self.assertIn('<span class="rang-nom">Tonte</span>', html)
        self.assertIn('<span class="rang-nom">Soleil</span>', html)
        self.assertNotIn('<span class="rang-nom">Arrosage</span>', html)

    def test_sans_heure_la_section_ne_s_affiche_pas(self) -> None:
        (html,) = _rendre([{"quoi": "frise", "sansHeure": True}])
        self.assertEqual(html, "")


if __name__ == "__main__":
    unittest.main()
