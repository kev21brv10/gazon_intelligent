"""La carte « Commander la tondeuse » : départ, bordure, retour, pause, reprise — et le mode manuel.

La page n'orchestre RIEN : elle envoie une demande (`gazon_intelligent/tondeuse/commande`) et le
serveur joue la séquence (volet, délai de sécurité, départ). Ici : ce que la carte montre, ce qu'elle
grise, les confirmations, et ce qu'elle envoie.
"""

from __future__ import annotations

import html as html_module
import json
import shutil
import subprocess
import unittest
from pathlib import Path

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
  console, structuredClone, setTimeout: () => 0,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

function fabriquer(c) {
  const p = Object.create(ctx.Classe.prototype);
  const volet = c.volet === undefined ? "closed" : c.volet;
  p._hass = {
    config: { time_zone: "Europe/Paris" },
    user: { is_admin: c.admin !== false },
    states: {
      "sensor.etat": { state: "a_surveiller", attributes: c.attributs || {} },
      ...(volet === null ? {} : { "cover.garage": { state: volet, attributes: c.volet_attributs || { friendly_name: "Garage tondeuse" } } }),
    },
    callService: async (domaine, service, donnees) => {
      if (c.echec_service) throw new Error(c.echec_service);
      p.services.push([domaine, service, donnees]);
    },
    callWS: async (message) => {
      p.messages.push(message);
      if (c.echec) throw new Error(c.echec);
      return c.reponse || { ok: true, message: "Commande manuelle prise en compte." };
    },
  };
  p._donnees = {
    entry_id: "entree-1", entites: { tonte_etat: "sensor.etat", tonte_autorisee: "sensor.etat", assistant: "sensor.etat" },
    garage_tondeuse: { choisie: c.sans_volet ? "" : "cover.garage", volets: [] },
  };
  p._commandesEnCours = new Set();
  p._tondeuseConfirmation = c.confirmation;
  p._garageConfirmation = c.confirmation_volet;
  p.services = [];
  p._fenetre = { contains: () => false };
  p._dialogue = null;
  p.messages = [];
  p.toasts = [];
  p._afficherToast = (texte, erreur) => p.toasts.push([texte, Boolean(erreur)]);
  p._signalerEchec = async (e) => p.toasts.push([`échec : ${e.message}`, true]);
  p._rendre = () => {};
  p._rendreQuandLibre = () => {};
  return p;
}

function clic(p, selecteurs) {
  p._surClicAccueil({ target: { closest: (sel) => selecteurs[sel] || null } });
}

const sorties = cas.map(() => null);
(async () => {
  for (let i = 0; i < cas.length; i++) {
    const c = cas[i];
    const p = fabriquer(c);
    if (c.type === "carte") {
      sorties[i] = { html: p._commandesTondeuseHtml() };
    } else if (c.type === "onglet") {
      // L'onglet Tonte COMPLET, pas la carte seule : la carte doit y être posée.
      p._mosaique = (items) => items.map((item) => item[0]).join("");
      p._coordinationHtml = () => "";
      p._pilotageTondeuseEtatHtml = () => "";
      p._arrosageEnCours = () => false;
      p._travailHtml = () => "";
      p._hauteursHtml = () => "";
      p._pousseHtml = () => "";
      p._motifsBlocageTonteHtml = () => "";
      p._tonduAujourdhui = () => true;
      sorties[i] = { html: p._ongletTonteHtml({}) };
    } else if (c.type === "refus") {
      sorties[i] = { refus: p._refusTondeuse(c.commande) };
    } else if (c.type === "commande") {
      await p._commande(c.nom, { dataset: c.dataset || {} });
      sorties[i] = { messages: p.messages, toasts: p.toasts, services: p.services, confirmation: p._tondeuseConfirmation === undefined ? "aucune" : p._tondeuseConfirmation, confirmationVolet: p._garageConfirmation === undefined ? "aucune" : p._garageConfirmation };
    } else if (c.type === "course") {
      // La confirmation est ouverte, puis l'état de Home Assistant change avant le second clic.
      Object.assign(p._hass.states["sensor.etat"].attributes, c.changement || {});
      await p._commande(c.nom, { dataset: {} });
      sorties[i] = { messages: p.messages, toasts: p.toasts };
    } else if (c.type === "navigation") {
      p._page = { scrollTo: () => {} };
      p._ongletAccueil = "tonte";
      const vue = (() => `${p._garageConfirmation === undefined ? "-" : p._garageConfirmation}/${p._tondeuseConfirmation === undefined ? "-" : p._tondeuseConfirmation}`);
      const trace = { avant: vue() };
      if (c.geste === "onglet") {
        clic(p, { "[data-onglet-accueil]": { dataset: { ongletAccueil: "apercu" } } });
        trace.onglet = p._ongletAccueil;
      } else if (c.geste === "vue") {
        p._choisirVue("reglages");
        trace.vue = p._vue;
      } else if (c.geste === "route") {
        p._vue = "accueil";
        p.route = { path: "/reglages" };
        trace.vue = p._vue;
      } else if (c.geste === "meme_vue") {
        p._vue = "accueil";
        p._choisirVue("accueil");
      }
      trace.apres = vue();
      sorties[i] = trace;
    } else if (c.type === "clics_volet") {
      const trace = [];
      clic(p, { "[data-garage-demander]": { dataset: { garageDemander: "fermer" }, disabled: false } });
      trace.push(p._garageConfirmation);
      clic(p, { "[data-garage-annuler]": {} });
      trace.push(p._garageConfirmation === undefined ? "aucune" : p._garageConfirmation);
      clic(p, { "[data-garage-demander]": { dataset: { garageDemander: "ouvrir" }, disabled: true } });
      trace.push(p._garageConfirmation === undefined ? "aucune" : p._garageConfirmation);
      sorties[i] = { trace, services: p.services };
    } else if (c.type === "clics") {
      const trace = [];
      clic(p, { "[data-tondeuse-demander]": { dataset: { tondeuseDemander: "demarrer" }, disabled: false } });
      trace.push(p._tondeuseConfirmation);
      clic(p, { "[data-tondeuse-annuler]": {} });
      trace.push(p._tondeuseConfirmation === undefined ? "aucune" : p._tondeuseConfirmation);
      clic(p, { "[data-tondeuse-demander]": { dataset: { tondeuseDemander: "bordure" }, disabled: false } });
      trace.push(p._tondeuseConfirmation);
      sorties[i] = { trace, messages: p.messages };
    }
  }
  process.stdout.write(JSON.stringify(sorties));
  process.exit(0);
})();
"""


def _rendre(cas: list[dict]) -> list[dict]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


A_QUAI = {
    "tondeuse_source_entity": "lawn_mower.esperance_jr", "tondeuse_connectee": True, "tondeuse_prete": True,
    "tondeuse_batterie": 100, "mower_is_docked": True, "mower_is_outside": False,
    "mower_edgecut_available": True, "mower_job_completion_state": "repos", "mower_manual_active": False,
}
DEHORS = {**A_QUAI, "mower_is_docked": False, "mower_is_outside": True, "mower_job_completion_state": "en_cours"}


def _carte(attributs: dict, **extra) -> str:
    """Le HTML de la carte, apostrophes et guillemets déséchappés : on lit ce que verra l'utilisateur."""
    (sortie,) = _rendre([{"type": "carte", "attributs": attributs, **extra}])
    return html_module.unescape(sortie["html"])


def _refus(commande: str, attributs: dict, **extra) -> str:
    (sortie,) = _rendre([{"type": "refus", "commande": commande, "attributs": attributs, **extra}])
    return sortie["refus"]


def _bouton(html: str, repere: str) -> str:
    debut = html.index(repere)
    debut = html.rfind("<button", 0, debut)
    return html[debut:html.index("</button>", debut)]


def _actif(html: str, repere: str) -> bool:
    return " disabled" not in _bouton(html, repere).split(">", 1)[0]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class AffichageTests(unittest.TestCase):
    def test_sans_tondeuse_la_carte_n_existe_pas(self) -> None:
        self.assertEqual(_carte({}).strip(), "")
        self.assertEqual(_carte({"tondeuse_source_entity": None}).strip(), "")

    def test_a_quai_on_peut_partir_pas_rentrer_ni_mettre_en_pause(self) -> None:
        html = _carte(A_QUAI)
        self.assertTrue(_actif(html, 'data-tondeuse-demander="demarrer"'))
        self.assertTrue(_actif(html, 'data-tondeuse-demander="bordure"'))
        self.assertFalse(_actif(html, 'data-commande="tondeuse-retour"'))
        self.assertFalse(_actif(html, 'data-commande="tondeuse-pause"'))
        self.assertIn("déjà à sa base", _bouton(html, 'data-commande="tondeuse-retour"'))

    def test_dehors_on_peut_rentrer_ou_mettre_en_pause_pas_partir(self) -> None:
        html = _carte(DEHORS)
        self.assertTrue(_actif(html, 'data-commande="tondeuse-retour"'))
        self.assertTrue(_actif(html, 'data-commande="tondeuse-pause"'))
        self.assertFalse(_actif(html, 'data-tondeuse-demander="demarrer"'))
        self.assertIn("à sa base", _bouton(html, 'data-tondeuse-demander="demarrer"'))

    def test_une_tondeuse_en_pause_propose_de_reprendre_a_la_place_de_pause(self) -> None:
        html = _carte({**DEHORS, "mower_job_completion_state": "en_pause"})
        self.assertIn('data-commande="tondeuse-reprendre"', html)
        self.assertNotIn('data-commande="tondeuse-pause"', html)
        self.assertTrue(_actif(html, 'data-commande="tondeuse-reprendre"'))
        self.assertNotIn('tondeuse-reprendre"', _carte(DEHORS))

    def test_une_tondeuse_mise_en_pause_ailleurs_propose_de_reprendre(self) -> None:
        """⚠️ Dehors, l'état de travail reste `en_cours` même en pause : seul l'état de la machine le dit."""
        for nom, maj in (
            ("état machine", {"mower_operation_state": "paused"}),
            ("état machine (variante)", {"mower_operation_state": "pause"}),
            ("statut normalisé", {"tondeuse_statut": "pause"}),
        ):
            with self.subTest(source=nom):
                html = _carte({**DEHORS, "mower_job_completion_state": "en_cours", **maj})
                self.assertIn('data-commande="tondeuse-reprendre"', html)
                self.assertNotIn('data-commande="tondeuse-pause"', html)
                self.assertTrue(_actif(html, 'data-commande="tondeuse-reprendre"'))
                self.assertEqual(_refus("reprendre", {**DEHORS, "mower_job_completion_state": "en_cours", **maj}), "")

    def test_une_tondeuse_qui_tond_ne_propose_pas_de_reprendre(self) -> None:
        html = _carte({**DEHORS, "mower_operation_state": "tonte", "tondeuse_statut": "tonte_en_cours"})
        self.assertNotIn('tondeuse-reprendre"', html)
        self.assertIn("pas en pause", _refus("reprendre", {**DEHORS, "mower_operation_state": "tonte"}))

    def test_pas_de_bouton_bordure_sans_le_bouton_de_la_tondeuse(self) -> None:
        html = _carte({**A_QUAI, "mower_edgecut_available": False})
        self.assertNotIn('data-tondeuse-demander="bordure"', html)

    def test_un_lecteur_non_administrateur_ne_peut_rien_commander(self) -> None:
        html = _carte(A_QUAI, admin=False)
        for repere in ('data-tondeuse-demander="demarrer"', 'data-tondeuse-demander="bordure"'):
            self.assertFalse(_actif(html, repere))
        self.assertIn("administrateur", html)

    def test_la_note_dit_si_le_volet_est_gere(self) -> None:
        self.assertIn("Le volet s'ouvre tout seul", _carte(A_QUAI))
        self.assertNotIn("Le volet s'ouvre tout seul", _carte(A_QUAI, sans_volet=True))

    def test_la_coupe_de_bordure_n_a_aucune_duree_a_regler(self) -> None:
        """La bordure est automatique : ni curseur, ni durée affichée, que le bouton soit proposé ou non."""
        for attributs in (A_QUAI, {**A_QUAI, "mower_edgecut_available": True}, {**A_QUAI, "mower_edgecut_available": False}):
            with self.subTest(attributs=attributs.get("mower_edgecut_available")):
                html = _carte(attributs)
                self.assertNotIn("data-bordure-duree", html)
                self.assertNotIn("bordure-duree", html)
                self.assertNotIn('type="range"', html)
                self.assertNotIn("Durée de la coupe", html)
        self.assertIn('data-tondeuse-demander="bordure"', _carte(A_QUAI), "le bouton lui-même reste proposé")


@unittest.skipUnless(NODE, "Node n'est pas installé")
class DansLOngletTonteTests(unittest.TestCase):
    def test_la_carte_est_posee_dans_l_onglet_tonte(self) -> None:
        (sortie,) = _rendre([{"type": "onglet", "attributs": {**A_QUAI, "tonte_statut": "autorisee", "gazon_permet_tonte": True,
                                                            "machine_permet_tonte": True}}])
        self.assertIn("Commander la tondeuse", sortie["html"])
        self.assertIn('data-tondeuse-demander="demarrer"', sortie["html"])

    def test_sans_tondeuse_l_onglet_n_a_pas_la_carte(self) -> None:
        (sortie,) = _rendre([{"type": "onglet", "attributs": {"tonte_statut": "autorisee", "gazon_permet_tonte": True,
                                                            "machine_permet_tonte": False}}])
        self.assertNotIn("Commander la tondeuse", sortie["html"])


@unittest.skipUnless(NODE, "Node n'est pas installé")
class ModeManuelTests(unittest.TestCase):
    def _actif(self, **maj) -> dict:
        return {**DEHORS, "mower_manual_active": True, "mower_manual_command": "demarrer",
                "mower_manual_step": "dehors", "mower_manual_reason": "La tondeuse travaille.",
                "mower_manual_until": "2026-10-04T18:00:00+00:00", "mower_control_mode": "actif", **maj}

    def test_le_bandeau_dit_le_mode_manuel_et_propose_d_annuler(self) -> None:
        html = _carte(self._actif())
        self.assertIn("Mode manuel : un départ", html)
        self.assertIn("La tondeuse travaille (au plus tard", html)
        self.assertIn("Le pilote automatique attend la fin de cette commande.", html)
        self.assertIn("Annuler rend la main au pilote sans arrêter la tondeuse.", html)
        self.assertNotRegex(html, r"\.\s*\(au plus tard", "pas de point avant la parenthèse de l'échéance")
        self.assertIn("Annuler la commande", html)
        self.assertTrue(_actif(html, 'data-commande="tondeuse-annuler"'))

    def test_pilote_desactive_le_bandeau_ne_parle_pas_du_pilote(self) -> None:
        self.assertNotIn("pilote automatique attend", _carte(self._actif(mower_control_mode="desactive")))

    def test_pendant_une_sortie_manuelle_pause_et_retour_restent_possibles(self) -> None:
        html = _carte(self._actif())
        self.assertTrue(_actif(html, 'data-commande="tondeuse-retour"'))
        self.assertTrue(_actif(html, 'data-commande="tondeuse-pause"'))

    def test_pendant_une_commande_un_second_depart_est_grise(self) -> None:
        html = _carte(self._actif(mower_is_docked=True, mower_is_outside=False, mower_manual_step="attente_garage"))
        self.assertFalse(_actif(html, 'data-tondeuse-demander="demarrer"'))
        self.assertIn("déjà en cours", _bouton(html, 'data-tondeuse-demander="demarrer"'))

    def test_pendant_un_retour_le_bouton_retour_est_grise(self) -> None:
        html = _carte(self._actif(mower_manual_command="retour", mower_manual_step="retour_envoye"))
        self.assertFalse(_actif(html, 'data-commande="tondeuse-retour"'))
        self.assertTrue(_actif(html, 'data-commande="tondeuse-pause"'))

    def test_une_commande_abandonnee_recente_est_signalee(self) -> None:
        recent = "2099-01-01T00:00:00+00:00"
        html = _carte({**A_QUAI, "mower_manual_step": "erreur", "mower_manual_command": "demarrer",
                       "mower_manual_reason": "Le volet ne répond pas : départ abandonné.",
                       "mower_manual_ended_at": recent})
        self.assertIn("Commande abandonnée", html)
        self.assertIn("Le volet ne répond pas", html)

    def test_une_ancienne_erreur_n_est_plus_affichee(self) -> None:
        html = _carte({**A_QUAI, "mower_manual_step": "erreur", "mower_manual_reason": "Ancienne.",
                       "mower_manual_ended_at": "2026-01-01T00:00:00+00:00"})
        self.assertNotIn("Commande abandonnée", html)

    def test_la_suspension_apres_un_retour_est_expliquee(self) -> None:
        html = _carte({**A_QUAI, "mower_manual_suspension_active": True,
                       "mower_manual_suspension_until": "2026-10-04T18:00:00+00:00"})
        self.assertIn("le pilote ne relance pas la tondeuse", html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class ConfirmationTests(unittest.TestCase):
    def test_un_depart_demande_une_confirmation_qui_parle_du_volet(self) -> None:
        html = _carte(A_QUAI, confirmation="demarrer")
        self.assertIn("Le volet va d'abord s'ouvrir", html)
        self.assertIn("passage est dégagé", html)
        self.assertIn('data-commande="tondeuse-demarrer"', html)
        self.assertIn("data-tondeuse-annuler", html)

    def test_sans_volet_la_confirmation_ne_parle_pas_de_volet(self) -> None:
        html = _carte(A_QUAI, confirmation="demarrer", sans_volet=True)
        self.assertNotIn("volet", html.lower().split("passage")[0].replace("le volet s'ouvre tout seul", ""))

    def test_la_confirmation_de_la_bordure_dit_qu_elle_est_automatique_sans_duree(self) -> None:
        html = _carte(A_QUAI, confirmation="bordure")
        self.assertIn("coupe de bordure automatique", html)
        self.assertIn("rentre seule", html)
        self.assertNotIn("pendant", html)
        self.assertNotRegex(html, r"\d+\s*min")
        self.assertIn('data-commande="tondeuse-bordure"', html)

    def test_demander_puis_annuler_n_envoie_rien(self) -> None:
        (sortie,) = _rendre([{"type": "clics", "attributs": A_QUAI}])
        self.assertEqual(sortie["trace"], ["demarrer", "aucune", "bordure"])
        self.assertEqual(sortie["messages"], [])

    def test_la_tondeuse_sort_entre_la_demande_et_la_confirmation_la_page_le_dit(self) -> None:
        html = _carte(DEHORS, confirmation="demarrer")
        self.assertIn("La demande est annulée", html)
        self.assertNotIn('data-commande="tondeuse-demarrer"', html)

    def test_pause_et_retour_n_ont_pas_de_confirmation(self) -> None:
        html = _carte(DEHORS)
        self.assertIn('data-commande="tondeuse-retour"', html)
        self.assertIn('data-commande="tondeuse-pause"', html)
        self.assertNotIn('data-tondeuse-demander="retour"', html)
        self.assertNotIn('data-tondeuse-demander="pause"', html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class VoletDuGarageDansLaCarteTests(unittest.TestCase):
    """Demande du 04/10/2026 : « les actions du garage (volet) ne sont pas dans Accueil → Tonte, ce serait bien de les avoir là aussi ».
    Mêmes boutons, mêmes confirmations et mêmes refus que dans Installation → Tondeuse → Garage."""

    def test_le_volet_enregistre_est_commandable_depuis_la_carte(self) -> None:
        html = _carte(A_QUAI, volet="open")
        self.assertIn('class="volet-tonte"', html)
        self.assertIn("Garage tondeuse", html)
        self.assertIn("ouvert", html)
        self.assertIn('data-garage-demander="ouvrir"', html)
        self.assertIn('data-garage-demander="fermer"', html)

    def test_les_boutons_suivent_l_etat_du_volet_et_de_la_tondeuse(self) -> None:
        # (état du volet, tondeuse, bouton, actif ?, mot attendu dans l'info-bulle quand grisé)
        for volet, attributs, verbe, actif, mot in (
            ("closed", A_QUAI, "ouvrir", True, ""),
            ("closed", A_QUAI, "fermer", False, "déjà fermé"),
            ("open", A_QUAI, "fermer", True, ""),
            ("open", A_QUAI, "ouvrir", False, "déjà ouvert"),
            ("open", DEHORS, "fermer", False, "dehors"),
            ("opening", A_QUAI, "ouvrir", False, ""),
            ("closing", A_QUAI, "fermer", False, ""),
            ("unavailable", A_QUAI, "ouvrir", False, "ne répond pas"),
            ("unknown", A_QUAI, "fermer", False, "ne répond pas"),
        ):
            with self.subTest(volet=volet, verbe=verbe, dehors=attributs is DEHORS):
                html = _carte(attributs, volet=volet)
                repere = f'data-garage-demander="{verbe}"'
                self.assertIn(repere, html)
                self.assertEqual(_actif(html, repere), actif)
                if mot:
                    self.assertIn(mot, _bouton(html, repere))

    def test_la_fermeture_exige_la_tondeuse_confirmee_a_sa_base(self) -> None:
        """Position inconnue : on ne ferme pas à l'aveugle (même règle qu'Installation)."""
        html = _carte({**A_QUAI, "mower_is_docked": False, "mower_is_outside": False}, volet="open")
        self.assertFalse(_actif(html, 'data-garage-demander="fermer"'))
        self.assertIn("pas confirmée", _bouton(html, 'data-garage-demander="fermer"'))

    def test_sans_volet_enregistre_ou_sans_etat_aucune_ligne_de_volet(self) -> None:
        self.assertNotIn("volet-tonte", _carte(A_QUAI, sans_volet=True))
        self.assertNotIn("data-garage-demander", _carte(A_QUAI, sans_volet=True))
        self.assertNotIn("volet-tonte", _carte(A_QUAI, volet=None))

    def test_un_lecteur_non_administrateur_ne_commande_pas_le_volet(self) -> None:
        html = _carte(A_QUAI, volet="open", admin=False)
        for verbe in ("ouvrir", "fermer"):
            self.assertFalse(_actif(html, f'data-garage-demander="{verbe}"'))

    def test_la_confirmation_dit_ce_qui_va_se_passer_et_cible_le_volet_enregistre(self) -> None:
        ouvrir = _carte(A_QUAI, volet="closed", confirmation_volet="ouvrir")
        self.assertIn("Ouvrir le volet ?", ouvrir)
        self.assertIn('data-commande="garage-ouvrir"', ouvrir)
        self.assertIn('data-volet="cover.garage"', ouvrir)
        self.assertIn("data-garage-annuler", ouvrir)
        fermer = _carte(A_QUAI, volet="open", confirmation_volet="fermer")
        self.assertIn("Fermer le volet ?", fermer)
        self.assertIn('data-commande="garage-fermer"', fermer)
        self.assertIn("la tondeuse n'est pas dehors", fermer)

    def test_une_confirmation_devenue_impossible_est_annulee_en_clair(self) -> None:
        html = _carte(DEHORS, volet="open", confirmation_volet="fermer")
        self.assertIn("La confirmation est annulée", html)
        self.assertNotIn('data-commande="garage-fermer"', html)

    def test_une_confirmation_ne_survit_pas_a_un_changement_d_onglet_ni_de_vue(self) -> None:
        """Relecture croisée (A-017) : une confirmation commencée dans Tonte réapparaissait dans Installation sans nouveau premier clic."""
        for geste in ("onglet", "vue", "route"):
            with self.subTest(geste=geste):
                (sortie,) = _rendre([{"type": "navigation", "geste": geste, "attributs": A_QUAI, "volet": "open",
                                      "confirmation_volet": "fermer", "confirmation": "demarrer"}])
                self.assertEqual(sortie["avant"], "fermer/demarrer")
                self.assertEqual(sortie["apres"], "-/-", "les deux confirmations d'ordres physiques sont oubliées")

    def test_rester_sur_la_meme_vue_ne_perd_pas_la_confirmation(self) -> None:
        (sortie,) = _rendre([{"type": "navigation", "geste": "meme_vue", "attributs": A_QUAI, "volet": "open",
                              "confirmation_volet": "fermer"}])
        self.assertEqual(sortie["apres"], sortie["avant"])

    def test_demander_puis_annuler_n_envoie_rien(self) -> None:
        (sortie,) = _rendre([{"type": "clics_volet", "attributs": A_QUAI, "volet": "open"}])
        self.assertEqual(sortie["trace"], ["fermer", "aucune", "aucune"], "un bouton grisé n'ouvre pas de confirmation")
        self.assertEqual(sortie["services"], [])

    def test_l_ordre_confirme_part_vers_le_volet_enregistre(self) -> None:
        for nom, volet, service in (("garage-ouvrir", "closed", "open_cover"), ("garage-fermer", "open", "close_cover")):
            with self.subTest(nom=nom):
                (sortie,) = _rendre([{"type": "commande", "nom": nom, "attributs": A_QUAI, "volet": volet,
                                      "dataset": {"volet": "cover.garage"}}])
                self.assertEqual(sortie["services"], [["cover", service, {"entity_id": "cover.garage"}]])
                self.assertEqual(sortie["confirmationVolet"], "aucune")

    def test_un_ordre_rejuge_au_moment_de_l_envoi_n_est_pas_envoye_si_l_etat_a_change(self) -> None:
        """La tondeuse est sortie entre la confirmation et le second clic : le volet n'est PAS fermé devant elle."""
        (sortie,) = _rendre([{"type": "commande", "nom": "garage-fermer", "attributs": DEHORS, "volet": "open",
                              "dataset": {"volet": "cover.garage"}}])
        self.assertEqual(sortie["services"], [])
        self.assertIn("Commande annulée", sortie["toasts"][0][0])
        self.assertIn("dehors", sortie["toasts"][0][0])

    def test_un_bouton_qui_montrait_un_autre_volet_n_envoie_rien(self) -> None:
        (sortie,) = _rendre([{"type": "commande", "nom": "garage-ouvrir", "attributs": A_QUAI, "volet": "closed",
                              "dataset": {"volet": "cover.ancien"}}])
        self.assertEqual(sortie["services"], [])
        self.assertIn("n'est plus celui qui est enregistré", sortie["toasts"][0][0])

    def test_un_volet_sans_la_fonction_n_est_pas_commande(self) -> None:
        """Capacités du volet (OPEN = 1, CLOSE = 2) : sans fermeture, le bouton Fermer est grisé."""
        html = _carte(A_QUAI, volet="open", volet_attributs={"friendly_name": "Garage", "supported_features": 1})
        self.assertFalse(_actif(html, 'data-garage-demander="fermer"'))
        self.assertIn("ne sait pas se fermer", _bouton(html, 'data-garage-demander="fermer"'))
        self.assertFalse(_actif(_carte(A_QUAI, volet="closed", volet_attributs={"friendly_name": "G", "supported_features": 2}),
                                'data-garage-demander="ouvrir"'))


@unittest.skipUnless(NODE, "Node n'est pas installé")
class EnvoiTests(unittest.TestCase):
    def _envoyer(self, nom: str, attributs: dict, **extra) -> dict:
        (sortie,) = _rendre([{"type": "commande", "nom": nom, "attributs": attributs, **extra}])
        return sortie

    def test_chaque_commande_envoie_la_demande_au_serveur_avec_l_instance(self) -> None:
        for commande, attributs in (("demarrer", A_QUAI), ("retour", DEHORS), ("pause", DEHORS)):
            with self.subTest(commande=commande):
                sortie = self._envoyer(f"tondeuse-{commande}", attributs, confirmation=commande)
                self.assertEqual(sortie["messages"], [{
                    "type": "gazon_intelligent/tondeuse/commande", "entry_id": "entree-1", "commande": commande,
                }])
                self.assertEqual(sortie["confirmation"], "aucune", "la confirmation retombe après l'envoi")

    def test_la_bordure_n_envoie_aucune_duree(self) -> None:
        sortie = self._envoyer("tondeuse-bordure", A_QUAI, confirmation="bordure")
        self.assertEqual(sortie["messages"], [{
            "type": "gazon_intelligent/tondeuse/commande", "entry_id": "entree-1", "commande": "bordure",
        }])

    def test_aucune_commande_n_envoie_de_duree(self) -> None:
        for commande, attributs in (("demarrer", A_QUAI), ("bordure", A_QUAI), ("retour", DEHORS), ("pause", DEHORS)):
            with self.subTest(commande=commande):
                message = self._envoyer(f"tondeuse-{commande}", attributs, confirmation=commande)["messages"][0]
                self.assertNotIn("duree_min", message)

    def test_annuler_la_commande_en_cours_part_sans_jugement_de_position(self) -> None:
        sortie = self._envoyer("tondeuse-annuler", {**DEHORS, "mower_manual_active": True, "mower_manual_command": "demarrer"})
        self.assertEqual(sortie["messages"][0]["commande"], "annuler")

    def test_annuler_sans_commande_en_cours_n_envoie_rien(self) -> None:
        sortie = self._envoyer("tondeuse-annuler", A_QUAI)
        self.assertEqual(sortie["messages"], [])
        self.assertIn("Aucune commande manuelle", sortie["toasts"][0][0])

    def test_un_lecteur_non_administrateur_n_envoie_rien(self) -> None:
        sortie = self._envoyer("tondeuse-demarrer", A_QUAI, admin=False)
        self.assertEqual(sortie["messages"], [])
        self.assertTrue(sortie["toasts"][0][1])

    def test_le_refus_du_serveur_est_montre_en_clair_comme_une_erreur(self) -> None:
        sortie = self._envoyer("tondeuse-demarrer", A_QUAI,
                               reponse={"ok": False, "message": "Un arrosage est en cours : la tondeuse ne part pas pendant l'eau."})
        texte, erreur = sortie["toasts"][0]
        self.assertTrue(erreur)
        self.assertIn("Un arrosage est en cours", texte)

    def test_l_acceptation_est_montree_sans_erreur(self) -> None:
        texte, erreur = self._envoyer("tondeuse-demarrer", A_QUAI)["toasts"][0]
        self.assertFalse(erreur)
        self.assertIn("prise en compte", texte)

    def test_une_erreur_de_connexion_est_signalee_sans_planter(self) -> None:
        sortie = self._envoyer("tondeuse-demarrer", A_QUAI, echec="connexion perdue")
        self.assertTrue(sortie["toasts"][0][1])
        self.assertIn("connexion perdue", sortie["toasts"][0][0])

    def test_la_tondeuse_sort_entre_les_deux_clics_l_ordre_n_est_jamais_envoye(self) -> None:
        (sortie,) = _rendre([{"type": "course", "nom": "tondeuse-demarrer", "attributs": A_QUAI,
                              "changement": {"mower_is_docked": False, "mower_is_outside": True}}])
        self.assertEqual(sortie["messages"], [])
        self.assertIn("Commande annulée", sortie["toasts"][0][0])

    def test_le_volet_devenu_muet_entre_les_deux_clics_bloque_le_depart(self) -> None:
        (sortie,) = _rendre([{"type": "commande", "nom": "tondeuse-demarrer", "attributs": A_QUAI, "volet": "unavailable"}])
        self.assertEqual(sortie["messages"], [])
        self.assertIn("volet ne répond pas", sortie["toasts"][0][0])

    def test_une_batterie_basse_bloque_le_depart_cote_page_aussi(self) -> None:
        sortie = self._envoyer("tondeuse-demarrer", {**A_QUAI, "tondeuse_batterie": 12})
        self.assertEqual(sortie["messages"], [])
        self.assertIn("batterie est trop basse", sortie["toasts"][0][0])


@unittest.skipUnless(NODE, "Node n'est pas installé")
class RefusTests(unittest.TestCase):
    def test_les_gardes_miroir_du_serveur(self) -> None:
        cas = [
            ("demarrer", {**A_QUAI, "tondeuse_connectee": False}, "pas connectée"),
            ("demarrer", {**A_QUAI, "tondeuse_prete": False}, "pas prête"),
            ("demarrer", DEHORS, "à sa base"),
            ("bordure", {**A_QUAI, "mower_edgecut_available": False}, "pas disponible"),
            ("retour", A_QUAI, "déjà à sa base"),
            ("pause", A_QUAI, "pas dehors"),
            ("reprendre", A_QUAI, "pas dehors"),
            ("reprendre", DEHORS, "pas en pause"),
        ]
        for commande, attributs, attendu in cas:
            with self.subTest(commande=commande, attendu=attendu):
                self.assertIn(attendu, _refus(commande, attributs))

    def test_commandes_possibles(self) -> None:
        for commande, attributs in (
            ("demarrer", A_QUAI), ("bordure", A_QUAI), ("retour", DEHORS), ("pause", DEHORS),
            ("reprendre", {**DEHORS, "mower_job_completion_state": "en_pause"}),
        ):
            with self.subTest(commande=commande):
                self.assertEqual(_refus(commande, attributs), "")

    def test_une_batterie_inconnue_ne_bloque_pas(self) -> None:
        self.assertEqual(_refus("demarrer", {**A_QUAI, "tondeuse_batterie": None}), "")

    def test_un_etat_de_volet_absent_est_traite_comme_muet(self) -> None:
        self.assertIn("volet ne répond pas", _refus("demarrer", A_QUAI, volet=None))
        self.assertIn("volet ne répond pas", _refus("retour", DEHORS, volet=None))
        self.assertEqual(_refus("pause", DEHORS, volet=None), "", "la pause ne touche pas au volet")
        en_pause = {**DEHORS, "mower_operation_state": "paused"}
        self.assertIn("volet ne répond pas", _refus("reprendre", en_pause, volet=None), "la reprise attend le volet")
        self.assertEqual(_refus("reprendre", en_pause), "", "volet fermé mais joignable : la reprise l'ouvrira")

    def test_sans_volet_enregistre_son_etat_ne_compte_pas(self) -> None:
        self.assertEqual(_refus("demarrer", A_QUAI, volet=None, sans_volet=True), "")


if __name__ == "__main__":
    unittest.main()
