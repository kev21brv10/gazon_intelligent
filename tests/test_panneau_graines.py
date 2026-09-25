"""Le prochain arrosage des graines, dit par la page (0.96.1).

Le 17/09, en germination, la page annonçait « Prochain arrosage : dimanche 20 septembre » :
l'estimation du régime Normal, alors que les graines sont arrosées chaque jour. Ce test charge la
page dans Node, lui donne les attributs que publient les capteurs, et lit ce que disent la tuile,
le bulletin et l'onglet Arrosage. Sans Node, il est sauté.
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
  console, structuredClone,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const partiesLocales = vm.runInContext("partiesLocales", ctx);
const sansBalises = (t) => String(t).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  const entites = {
    prochain_arrosage: "sensor.pa", fenetre_optimale: "sensor.fo", objectif: "sensor.obj", reserve: "sensor.res",
    hauteur_tonte: "sensor.ht", tonte_autorisee: "binary_sensor.ta",
  };
  p._hass = {
    config: { time_zone: "Europe/Paris" },
    states: {
      "sensor.pa": { state: c.etat, attributes: c.prochain },
      "sensor.fo": { state: "attendre", attributes: c.fenetre },
      "sensor.obj": { state: "0", attributes: c.objectif || {} },
      "sensor.res": { state: "12", attributes: {} },
      "sensor.ht": { state: String(c.hauteur ?? 4), attributes: {} },
      "binary_sensor.ta": { state: c.tonte === "autorisee" ? "on" : "off", attributes: { tonte_statut: c.tonte || "" } },
    },
  };
  p._donnees = { entites };
  p._arrosageEnCours = () => false;
  const contexte = {
    maintenant: partiesLocales(new Date(c.maintenant), "Europe/Paris"),
    semis: c.semis || null,
    hauteurConseillee: c.hauteur ?? null,
  };
  const ea = p._etatArrosage(contexte);
  const tuile = p._tuileProchainArrosage(contexte);
  const bandeau = p._etatArrosageHtml(contexte);
  return {
    genre: ea.genre,
    tuile: sansBalises(tuile),
    bandeau: sansBalises(bandeau.split('<div class="rangee-boutons">')[0]),
    bulletin: sansBalises(p._bulletinHtml(contexte)),
    phrase: ea.genre === "graines" ? sansBalises(p._motsGraines(ea.graines).phrase) : null,
    programme: sansBalises(p._pucesProgrammeGraines(contexte).join(" ")),
    apercuReglages: sansBalises(p._carteEau("Germination", 1.2, 2, true, {
      graines_fenetre_debut: 8 * 60 + 30,
      graines_fenetre_fin: 16 * 60,
    }, 120)),
  };
});
process.stdout.write(JSON.stringify(sorties));
"""

MAINTENANT = "2026-09-17T15:40:00+00:00"  # 17 h 40 à Paris
GRAINES = {
    "watering_strategy": "semis_frequent", "surface_cycle_mm": 1.2, "daily_cycles_target": 3,
    "watering_window_start_minute": 510, "watering_window_display": "08:30–16:00",
}
DEMAIN = {"jours_avant_arrosage_estime": 1, "date_prochain_arrosage_estime": "2026-09-18",
          "watering_window_display": "08:30–16:00", "objective_mm": 0}


def _cas(etat: str = "Non requis", prochain: dict[str, Any] | None = None, fenetre: dict[str, Any] | None = None,
         maintenant: str = MAINTENANT) -> dict[str, Any]:
    return {"etat": etat, "prochain": {**DEMAIN, **(prochain or {})}, "fenetre": fenetre or {}, "maintenant": maintenant}


def _rendre(cas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return [{k: _propre(v) if k != "genre" else v for k, v in s.items()} for s in json.loads(sortie.stdout)]


def _propre(texte: str | None) -> str | None:
    return None if texte is None else re.sub(r"\s+([.,])", r"\1", html.unescape(texte))


@unittest.skipUnless(NODE, "Node n'est pas installé")
class LeProchainArrosageDesGrainesTests(unittest.TestCase):
    def test_la_page_de_reglages_affiche_les_depart_repartis(self) -> None:
        [rendu] = _rendre([_cas()])
        self.assertIn("Départs prévus : 8 h 30 · 15 h 00", rendu["apercuReglages"])
        self.assertIn("2 arrosages de 1,2 mm", rendu["apercuReglages"])

    def test_le_programme_reste_visible_pour_semis_et_sursemis(self) -> None:
        sursemis = {
            **_cas(fenetre={**GRAINES, "watering_stage": "germination"}),
            "semis": {"mode": "Sursemis", "age": 3, "coupes": 0},
            "objectif": {"sous_phase": "Germination"},
            "hauteur": 4,
            "tonte": "interdite",
        }
        semis = {
            **_cas(fenetre={
                **GRAINES,
                "watering_stage": "enracinement",
                "surface_cycle_mm": 3,
                "daily_cycles_target": 1,
                "semis_daily_cycles_target": 1,
            }),
            "semis": {"mode": "Semis", "age": 12, "coupes": 0},
            "objectif": {"sous_phase": "Enracinement"},
            "hauteur": 7,
            "tonte": "interdite",
        }
        rendu_sursemis, rendu_semis = _rendre([sursemis, semis])
        self.assertIn("Germination · J3", rendu_sursemis["programme"])
        self.assertIn("1,2 mm par cycle · objectif météo 3", rendu_sursemis["programme"])
        self.assertIn("8 h 30 → 16 h 00", rendu_sursemis["programme"])
        self.assertIn("Tonte interdite · 4 cm conseillés", rendu_sursemis["programme"])
        self.assertIn("Enracinement · J12", rendu_semis["programme"])
        self.assertIn("3 mm par cycle · objectif météo 1", rendu_semis["programme"])
        self.assertIn("Tonte interdite · 7 cm conseillés", rendu_semis["programme"])
        for rendu in (rendu_sursemis, rendu_semis):
            self.assertNotIn("aube", rendu["programme"])
            self.assertNotIn("semaine couverte", rendu["programme"].lower())

    def test_cycles_du_jour_faits(self) -> None:
        fini = {**GRAINES, "seeding_block_reason": "semis_cycle_daily_target_reached",
                "semis_followup_state": "complete", "semis_cycles_completed_today": 4}
        [s] = _rendre([_cas(fenetre=fini)])
        self.assertEqual(s["genre"], "graines")
        self.assertIn("Demain dès 8 h 30", s["tuile"])
        self.assertIn("4 cycles faits aujourd'hui", s["tuile"])
        self.assertIn("Graines : c'est fini pour aujourd'hui", s["bandeau"])
        self.assertIn("4 cycles faits aujourd'hui. Prochain cycle demain dès 8 h 30", s["bandeau"])
        self.assertEqual(s["phrase"], "Graines : 4 cycles faits aujourd'hui. Prochain cycle demain dès 8 h 30.")
        for texte in (s["tuile"], s["bandeau"]):
            self.assertNotIn("aube", texte)
            self.assertNotIn("sur 3", texte, "4 faits pour 3 prévus : pas de « 4 sur 3 »")

    def test_le_bulletin_parle_des_graines(self) -> None:
        fini = {**GRAINES, "semis_followup_state": "complete", "semis_cycles_completed_today": 4}
        [graines, normal] = _rendre([
            _cas(fenetre=fini),
            _cas(prochain={"jours_avant_arrosage_estime": 3, "date_prochain_arrosage_estime": "2026-09-20"}),
        ])
        self.assertIn("Graines : 4 cycles faits aujourd'hui. Prochain cycle demain dès 8 h 30.", graines["bulletin"])
        self.assertNotIn("aube", graines["bulletin"])
        self.assertIn("Prochain arrosage estimé : dimanche 20 septembre, à l'aube.", normal["bulletin"])

    def test_le_motif_seul_suffit(self) -> None:
        # Le cas réel du 17/09 à 17:31 : une intégration 0.96.0 publie le motif, pas le suivi.
        [fini, attente] = _rendre([
            _cas(fenetre={**GRAINES, "seeding_block_reason": "semis_cycle_daily_target_reached"}),
            _cas("Bloqué", {"block_reason_label": "Arrosage bloqué"},
                 {**GRAINES, "seeding_block_reason": "semis_cycle_pending"}, maintenant="2026-09-17T09:00:00+00:00"),
        ])
        self.assertIn("Graines : c'est fini pour aujourd'hui", fini["bandeau"])
        self.assertIn("Prochain cycle demain dès 8 h 30", fini["bandeau"])
        self.assertEqual(attente["genre"], "graines")
        self.assertIn("Prochain cycle de graines bientôt", attente["bandeau"])
        self.assertNotIn("bloqué", attente["bandeau"].lower())

    def test_pas_de_n_sur_m_quand_on_a_fait_plus_que_prevu(self) -> None:
        # La météo peut baisser le nombre prévu après coup : 4 faits, 3 prévus.
        plus = {**GRAINES, "semis_cycles_completed_today": 4}
        moins = {**GRAINES, "semis_cycles_completed_today": 2}
        [s_plus, s_moins] = _rendre([_cas(fenetre=plus), _cas(fenetre=moins)])
        self.assertIn("4 cycles faits aujourd'hui.", s_plus["bandeau"])
        self.assertNotIn("sur 3", s_plus["bandeau"])
        self.assertIn("2 cycles faits sur 3 aujourd'hui.", s_moins["bandeau"])

    def test_l_attente_entre_deux_cycles_n_est_pas_un_blocage(self) -> None:
        attente = {**GRAINES, "seeding_block_reason": "semis_cycle_pending", "semis_followup_state": "waiting",
                   "semis_cycles_completed_today": 2, "semis_followup_due_at": "2026-09-17T10:30:00+00:00"}
        [s] = _rendre([_cas("Bloqué", {"block_reason_label": "Arrosage bloqué", "block_reason": "semis_cycle_pending"},
                            attente, maintenant="2026-09-17T09:00:00+00:00")])
        self.assertEqual(s["genre"], "graines")
        self.assertIn("Vers 12 h 30", s["tuile"])
        self.assertIn("2 cycles faits sur 3", s["tuile"])
        self.assertIn("Prochain cycle de graines vers 12 h 30", s["bandeau"])
        self.assertIn("2 cycles faits sur 3 aujourd'hui. 1,2 mm par cycle.", s["bandeau"])
        self.assertNotIn("bloqué", s["bandeau"].lower())

    def test_ajustement_meteo_explique_pourquoi_la_cible_a_change(self) -> None:
        # Signalé le 25/09/2026 : « 3 sur 4 » sans explication ressemblait à un bug alors que la
        # météo du jour (chaud/sec) avait simplement ajouté un cycle au réglage de base.
        attente = {**GRAINES, "seeding_block_reason": "semis_cycle_pending", "semis_followup_state": "waiting",
                   "daily_cycles_target": 4, "semis_cycles_completed_today": 3,
                   "semis_followup_due_at": "2026-09-17T10:30:00+00:00", "semis_meteo_ajustement": "chaud_sec"}
        [s] = _rendre([_cas("Bloqué", {"block_reason_label": "Arrosage bloqué", "block_reason": "semis_cycle_pending"},
                            attente, maintenant="2026-09-17T09:00:00+00:00")])
        self.assertIn(
            "3 cycles faits sur 4 aujourd'hui (objectif adapté à une météo chaude ou desséchante)",
            s["bandeau"],
        )

    def test_humide_frais_ne_pretend_pas_mesurer_le_sol_ou_retirer_un_cycle(self) -> None:
        attente = {**GRAINES, "seeding_block_reason": "semis_cycle_pending", "semis_followup_state": "waiting",
                   "daily_cycles_target": 1, "semis_cycles_completed_today": 0,
                   "semis_followup_due_at": "2026-09-17T10:30:00+00:00", "semis_meteo_ajustement": "humide_frais"}
        [s] = _rendre([_cas("Bloqué", {"block_reason_label": "Arrosage bloqué", "block_reason": "semis_cycle_pending"},
                            attente, maintenant="2026-09-17T09:00:00+00:00")])
        self.assertIn("0 cycles faits sur 1 aujourd'hui (objectif adapté à une météo humide ou fraîche)", s["bandeau"])
        self.assertNotIn("sol reste humide", s["bandeau"])
        self.assertNotIn("un cycle de moins", s["bandeau"])

    def test_ajustement_neutre_ou_absent_ne_change_rien(self) -> None:
        sans_ajustement = {**GRAINES, "seeding_block_reason": "semis_cycle_pending", "semis_followup_state": "waiting",
                            "semis_cycles_completed_today": 2, "semis_followup_due_at": "2026-09-17T10:30:00+00:00"}
        neutre = {**sans_ajustement, "semis_meteo_ajustement": "neutre"}
        [s_sans, s_neutre] = _rendre([
            _cas("Bloqué", {"block_reason_label": "Arrosage bloqué"}, sans_ajustement, maintenant="2026-09-17T09:00:00+00:00"),
            _cas("Bloqué", {"block_reason_label": "Arrosage bloqué"}, neutre, maintenant="2026-09-17T09:00:00+00:00"),
        ])
        for s in (s_sans, s_neutre):
            self.assertIn("2 cycles faits sur 3 aujourd'hui.", s["bandeau"])
            self.assertNotIn("chaleur", s["bandeau"])
            self.assertNotIn("humide", s["bandeau"])

    def test_un_vrai_blocage_reste_un_blocage(self) -> None:
        vent = {**GRAINES, "seeding_block_reason": "vent_trop_fort"}
        [s] = _rendre([_cas("Bloqué", {"block_reason_label": "Vent trop fort pour les graines."}, vent)])
        self.assertEqual(s["genre"], "bloque")
        self.assertIn("Vent trop fort pour les graines", s["bandeau"])

    def test_un_cycle_du_reste_un_arrosage_prevu(self) -> None:
        [s] = _rendre([_cas("Programmé", {"objective_mm": 1.2}, GRAINES)])
        self.assertEqual(s["genre"], "prevu")
        self.assertIn("1,2 mm", s["bandeau"])

    def test_sans_suivi_publie_la_date_de_l_integration_suffit(self) -> None:
        # Une intégration plus ancienne ne publie pas `semis_*` ; la 0.96.1 annonce demain.
        [demain, aujourd_hui] = _rendre([
            _cas(fenetre=GRAINES),
            _cas(prochain={"jours_avant_arrosage_estime": 0, "date_prochain_arrosage_estime": "2026-09-17"},
                 fenetre=GRAINES, maintenant="2026-09-17T08:00:00+00:00"),
        ])
        self.assertEqual(demain["genre"], "graines")
        self.assertIn("Prochain cycle de graines : demain dès 8 h 30", demain["bandeau"])
        self.assertIn("Demain dès 8 h 30", demain["tuile"])
        self.assertIn("1,2 mm par cycle, selon la météo", demain["bandeau"])
        self.assertIn("Prochain cycle de graines : aujourd'hui", aujourd_hui["bandeau"])
        self.assertNotIn("dès", aujourd_hui["bandeau"], "à 10 h, « aujourd'hui dès 8 h 30 » ne veut rien dire")

    def test_le_regime_normal_garde_son_estimation(self) -> None:
        [s] = _rendre([_cas(prochain={"jours_avant_arrosage_estime": 3, "date_prochain_arrosage_estime": "2026-09-20",
                                      "watering_window_display": "03:45–10:00"},
                            fenetre={"watering_strategy": "deplete_to_mad"})])
        self.assertEqual(s["genre"], "estime")
        self.assertIn("Prochain arrosage : dimanche 20 septembre", s["bandeau"])
        self.assertIn("à l'aube", s["bandeau"])
        self.assertIsNone(s["phrase"])


if __name__ == "__main__":
    unittest.main()
