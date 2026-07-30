from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _ensure_homeassistant_dt_module() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
    homeassistant = sys.modules.get("homeassistant")
    if homeassistant is None:
        homeassistant = types.ModuleType("homeassistant")
        homeassistant.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant"] = homeassistant
    util = sys.modules.get("homeassistant.util")
    if util is None:
        util = types.ModuleType("homeassistant.util")
        util.__path__ = []  # type: ignore[attr-defined]
        sys.modules["homeassistant.util"] = util
    dt_module = types.ModuleType("homeassistant.util.dt")
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=timezone.utc)  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_ensure_homeassistant_dt_module()

water = importlib.import_module("custom_components.gazon_intelligent.water")
mowing = importlib.import_module("custom_components.gazon_intelligent.decision_mowing")
decision = importlib.import_module("custom_components.gazon_intelligent.decision")
guidance = importlib.import_module("custom_components.gazon_intelligent.guidance")




TODAY = date(2026, 7, 29)


def _both(item: dict[str, object]) -> tuple[datetime, datetime | None]:
    """Date la MÊME entrée des deux côtés : tonte, puis arrosage."""
    return (
        mowing._parse_history_timestamp(dict(item), TODAY),
        guidance._latest_watering_datetime([dict(item)]),
    )


class HorodatageHistoriquePartageTests(unittest.TestCase):
    """Contrat inter-sous-systèmes : arrosage et tonte datent un événement IDENTIQUEMENT.

    Avant le 29/07/2026 ils divergeaient : la tonte retombait sur 06:00 et lisait `declared_at`,
    l'arrosage retombait sur 00:00 et l'ignorait. Un arrosage déclaré à la main se retrouvait à
    6 h d'écart — et jusqu'à plusieurs JOURS sur une déclaration rétroactive, que la tonte datait
    du moment de la saisie. Les deux passent désormais par `water.resolve_history_moment`.
    """

    def test_les_deux_sous_systemes_ne_divergent_jamais(self) -> None:
        cas = (
            ("arrosage auto", {"type": "arrosage", "recorded_at": "2026-07-28T05:12:00+00:00", "date": "2026-07-28"}),
            ("manuel date seule", {"type": "arrosage", "date": "2026-07-28"}),
            ("manuel jour même", {"type": "arrosage", "date": "2026-07-28", "declared_at": "2026-07-28T07:40:00+00:00"}),
            ("manuel rétroactif", {"type": "arrosage", "date": "2026-07-26", "declared_at": "2026-07-29T21:15:00+00:00"}),
        )
        for libelle, item in cas:
            with self.subTest(cas=libelle):
                cote_tonte, cote_arrosage = _both(item)
                self.assertIsNotNone(cote_arrosage)
                self.assertEqual(cote_tonte, cote_arrosage, f"divergence réapparue sur : {libelle}")

    def test_un_horodatage_machine_est_pris_tel_quel(self) -> None:
        # Cas ultra-majoritaire : les arrosages lancés par l'intégration. Rien ne doit bouger.
        item = {"type": "arrosage", "recorded_at": "2026-07-28T05:12:00+00:00", "date": "2026-07-28"}
        self.assertEqual(
            water.resolve_history_moment(item),
            datetime(2026, 7, 28, 5, 12, tzinfo=timezone.utc),
        )

    def test_une_declaration_du_jour_meme_garde_son_heure(self) -> None:
        # Arbitrage de Kévin : « le déclarer à l'heure où l'arrosage a été déclaré ».
        item = {"type": "arrosage", "date": "2026-07-28", "declared_at": "2026-07-28T07:40:00+00:00"}
        self.assertEqual(
            water.resolve_history_moment(item),
            datetime(2026, 7, 28, 7, 40, tzinfo=timezone.utc),
        )

    def test_une_declaration_retroactive_garde_la_date_declaree(self) -> None:
        # Régression : `declared_at` primait sur la date côté tonte → un arrosage du 26 était
        # daté du 29 à 21:15, soit 3 jours d'erreur sur le ressuyage du gazon.
        item = {"type": "arrosage", "date": "2026-07-26", "declared_at": "2026-07-29T21:15:00+00:00"}
        resolu = water.resolve_history_moment(item)
        assert resolu is not None
        self.assertEqual(resolu.date(), date(2026, 7, 26), "l'instant de saisie a repris le dessus")
        self.assertEqual(resolu.hour, water.HISTORY_DATE_ONLY_FALLBACK_HOUR)

    def test_une_date_seule_retombe_a_l_aube_pas_a_minuit(self) -> None:
        # 06:00 et non 00:00 : la règle de Kévin est d'arroser à l'aube. Repli plus proche du
        # réel, et plus prudent — le cooldown 24 h dure 6 h de plus au lieu de 6 h de moins.
        resolu = water.resolve_history_moment({"type": "arrosage", "date": "2026-07-28"})
        self.assertEqual(resolu, datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc))

    def test_une_entree_non_datable_reste_non_datable(self) -> None:
        self.assertIsNone(water.resolve_history_moment({"type": "arrosage"}))
        self.assertIsNone(water.resolve_history_moment({"date": "pas-une-date"}))
        self.assertIsNone(water.resolve_history_moment("pas un dict"))

    def test_la_tonte_retombe_sur_aujourd_hui_si_rien_n_est_datable(self) -> None:
        # Comportement historique de la tonte conservé : elle ne renvoie jamais None.
        self.assertEqual(
            mowing._parse_history_timestamp({"type": "arrosage"}, TODAY),
            datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc),
        )


class BornesDeHauteurSuiventLaConfigTests(unittest.TestCase):
    """Les bornes publiées sont celles de la CONFIG — la machine fait loi.

    Historique de cette zone, en trois temps :
    - avant 0.25.0 : un plancher fixe de 4,0 cm et un plafond de 6,5 cm rognaient la config
      EN SILENCE (un réglage 3,0-6,0 devenait 4,0-6,0), et l'attribut publiait quand même la
      config — il mentait donc deux fois ;
    - 0.25.0 : les bornes publiées deviennent celles appliquées, le rognage devient visible ;
    - 0.27.0 : les planchers fixes sont RETIRÉS (arbitrage de Kévin, « pour la tondeuse il
      devrait se fier au min max »). Ce qui protège du scalp est la RÈGLE DU TIERS, dynamique,
      qui suit la hauteur réelle du gazon au lieu d'un seuil figé.

    NE PAS réintroduire de plancher fixe : la config décrit la machine de l'utilisateur.
    """

    def _snapshot(self, mini: float, maxi: float, hauteur_gazon: float = 12.0) -> dict[str, object]:
        return decision.build_decision_snapshot(
            history=[],
            today=date(2026, 6, 15),
            hour_of_day=8,
            temperature=25,
            pluie_24h=0,
            pluie_demain=0,
            humidite=50,
            type_sol="limoneux",
            etp_capteur=4.0,
            hauteur_gazon=hauteur_gazon,
            hauteur_min_tondeuse_cm=mini,
            hauteur_max_tondeuse_cm=maxi,
        )

    def test_la_config_n_est_plus_rognee(self) -> None:
        # Une config 3,0-8,0 était ramenée à 4,0-6,5 par les anciens planchers fixes.
        snap = self._snapshot(3.0, 8.0)
        self.assertEqual(snap["hauteur_tonte_min_cm"], 3.0, "un plancher fixe a été réintroduit")
        self.assertEqual(snap["hauteur_tonte_max_cm"], 8.0, "un plafond fixe a été réintroduit")

    def test_la_config_de_kevin_est_respectee_telle_quelle(self) -> None:
        snap = self._snapshot(3.0, 6.0)
        self.assertEqual(snap["hauteur_tonte_min_cm"], 3.0)
        self.assertEqual(snap["hauteur_tonte_max_cm"], 6.0)

    def test_la_regle_du_tiers_tient_toujours_le_plancher(self) -> None:
        # Vraie protection anti-scalp : on n'ôte pas plus d'un tiers du limbe. Avec un gazon à
        # 12 cm, la consigne ne peut pas descendre sous 8 cm, quelle que soit la config.
        snap = self._snapshot(3.0, 20.0, hauteur_gazon=12.0)
        self.assertGreaterEqual(
            float(snap["hauteur_tonte_recommandee_cm"]), 8.0,
            "la règle du tiers ne protège plus du scalp",
        )

    def test_la_regle_du_tiers_suit_la_hauteur_du_gazon(self) -> None:
        # Elle DESCEND quand l'herbe est courte — c'est ce qu'un plancher fixe ne savait pas faire.
        haut = float(self._snapshot(3.0, 20.0, hauteur_gazon=15.0)["hauteur_tonte_recommandee_cm"])
        bas = float(self._snapshot(3.0, 20.0, hauteur_gazon=6.0)["hauteur_tonte_recommandee_cm"])
        self.assertGreater(haut, bas, "le plancher ne suit pas la hauteur réelle")

    def test_le_libelle_explique_la_regle_du_tiers_quand_elle_pilote(self) -> None:
        label = str(self._snapshot(3.0, 20.0, hauteur_gazon=15.0).get("hauteur_tonte_garde_fou_label") or "")
        self.assertIn("tiers", label.lower(), "la contrainte qui pilote n'est pas expliquée")

    def test_pas_de_libelle_quand_c_est_la_saison_qui_pilote(self) -> None:
        # Gazon court : la règle du tiers ne contraint rien, donc rien à expliquer.
        snap = self._snapshot(3.0, 6.0, hauteur_gazon=4.0)
        self.assertIsNone(snap.get("hauteur_tonte_garde_fou_label"))


class PalierDeHauteurTests(unittest.TestCase):
    """Exigence de Kévin (30/07/2026) : toutes les hauteurs sont des paliers de 0,5 cm.

    Vaut pour la consigne, les bornes publiées, et la descente progressive d'une tonte à
    l'autre. Le pas est unique et fixe (`_MOWER_STEP_CM`) : il ne dépend PAS de la tondeuse
    configurée, sans quoi une machine à pas fin ferait dériver la consigne hors grille.
    """

    def _snapshot(self, **kw: object) -> dict[str, object]:
        base = dict(
            history=[], today=date(2026, 7, 15), hour_of_day=8, temperature=25,
            pluie_24h=0, pluie_demain=0, humidite=55, type_sol="limoneux",
            etp_capteur=3.0, hauteur_gazon=9.0,
            hauteur_min_tondeuse_cm=2.5, hauteur_max_tondeuse_cm=8.0,
        )
        base.update(kw)
        return decision.build_decision_snapshot(**base)  # type: ignore[arg-type]

    def _est_un_palier(self, valeur: object) -> bool:
        return abs(float(valeur) * 2 - round(float(valeur) * 2)) < 1e-9

    def test_le_pas_du_moteur_vaut_bien_un_demi_centimetre(self) -> None:
        self.assertEqual(mowing._MOWER_STEP_CM, 0.5)

    def test_consigne_et_bornes_tombent_sur_la_grille(self) -> None:
        for gazon in (3.0, 4.5, 5.9, 7.2, 9.0, 12.0, 15.0):
            snap = self._snapshot(hauteur_gazon=gazon)
            for cle in ("hauteur_tonte_recommandee_cm", "hauteur_tonte_min_cm", "hauteur_tonte_max_cm"):
                with self.subTest(gazon=gazon, cle=cle):
                    self.assertTrue(self._est_un_palier(snap[cle]), f"{cle} = {snap[cle]} hors grille")

    def test_une_config_hors_grille_est_ramenee_sur_la_grille(self) -> None:
        # Une tondeuse déclarée 2,3-7,8 cm ne doit pas produire de bornes hors palier.
        snap = self._snapshot(hauteur_min_tondeuse_cm=2.3, hauteur_max_tondeuse_cm=7.8)
        self.assertTrue(self._est_un_palier(snap["hauteur_tonte_min_cm"]))
        self.assertTrue(self._est_un_palier(snap["hauteur_tonte_max_cm"]))

    def test_la_descente_progresse_par_paliers_de_0_5(self) -> None:
        # Régression : la descente d'une tonte à l'autre ne saute jamais plus d'un palier.
        gazon, memoire, precedent = 12.0, None, None
        for _ in range(8):
            reco = float(self._snapshot(hauteur_gazon=gazon, memory=memoire)["hauteur_tonte_recommandee_cm"])
            self.assertTrue(self._est_un_palier(reco), f"consigne hors grille : {reco}")
            if precedent is not None:
                self.assertLessEqual(
                    abs(reco - precedent), 0.5 + 1e-9,
                    f"saut de {abs(reco - precedent):.2f} cm entre deux tontes — plus d'un palier",
                )
            precedent = reco
            memoire = {"hauteur_tonte_recommandee_cm": reco}
            gazon = reco + 1.2


class UnArrosageParJourTests(unittest.TestCase):
    """Le garde d'arrosage est « une fois par jour », pas « 24 h glissantes ».

    Mesuré sur l'install le 30/07/2026 : le compte à rebours partait de la FIN du cycle, si
    bien que l'heure autorisée reculait de la durée du cycle (~1 h) CHAQUE JOUR — fin à 06:36
    le 28, 07:36 le 29, 08:40 le 30, projection 10:44 le 1er août, soit hors de la fenêtre du
    matin qui ferme à 10:00. L'arrosage se serait bloqué un jour entier en pleine chaleur.

    NE PAS revenir à un delta en heures : c'est précisément ce qui créait la dérive.
    """

    def _guidance_ctx(self, dernier_arrosage_iso: str, maintenant: datetime):
        """Rejoue le calcul du garde tel qu'il est dans `compute_action_guidance`."""
        dernier = guidance._parse_history_datetime(dernier_arrosage_iso)
        assert dernier is not None
        local = dernier.astimezone(maintenant.tzinfo)
        return local.date() == maintenant.date()

    def test_arrose_ce_matin_bloque_le_reste_de_la_journee(self) -> None:
        matin = "2026-07-30T06:40:00+02:00"
        for heure in (9, 12, 18, 23):
            with self.subTest(heure=heure):
                maintenant = datetime(2026, 7, 30, heure, 0, tzinfo=timezone(timedelta(hours=2)))
                self.assertTrue(self._guidance_ctx(matin, maintenant), "le garde devrait être armé")

    def test_le_lendemain_a_l_aube_le_garde_est_leve(self) -> None:
        # LE point du correctif : à 04:00 le lendemain, seulement 21 h 20 se sont écoulées.
        # L'ancien garde « < 24 h » aurait encore bloqué ; le nouveau laisse passer.
        maintenant = datetime(2026, 7, 31, 4, 0, tzinfo=timezone(timedelta(hours=2)))
        self.assertFalse(
            self._guidance_ctx("2026-07-30T06:40:00+02:00", maintenant),
            "le garde bloque encore à l'aube — la dérive est revenue",
        )

    def test_la_derive_ne_se_reproduit_pas_sur_une_semaine(self) -> None:
        # On rejoue sept jours : chaque arrosage part à 04:00 et dure 1 h. Avec l'ancien garde,
        # l'heure de départ reculait d'une heure par jour. Ici elle doit rester à 04:00.
        tz = timezone(timedelta(hours=2))
        fin_precedente = "2026-07-30T05:00:00+02:00"
        for jour in range(31, 38):
            mois, num = (7, jour) if jour <= 31 else (8, jour - 31)
            aube = datetime(2026, mois, num, 4, 0, tzinfo=tz)
            with self.subTest(jour=f"{num:02d}/{mois:02d}"):
                self.assertFalse(
                    self._guidance_ctx(fin_precedente, aube),
                    f"le {num:02d}/{mois:02d} l'arrosage de 04:00 est bloqué — dérive réapparue",
                )
            fin_precedente = aube.replace(hour=5).isoformat()

    def test_la_comparaison_se_fait_en_heure_LOCALE(self) -> None:
        # Piège de la falaise de minuit : un arrosage local le 30 à 01:00 vaut le 29 en UTC.
        # Comparé en UTC, le garde ne s'armerait pas et un second arrosage partirait le jour même.
        tz = timezone(timedelta(hours=2))
        self.assertTrue(
            self._guidance_ctx("2026-07-30T01:00:00+02:00", datetime(2026, 7, 30, 6, 0, tzinfo=tz)),
            "la comparaison est faite en UTC — un second arrosage peut passer",
        )


if __name__ == "__main__":
    unittest.main()
