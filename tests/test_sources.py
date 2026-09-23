"""Les entrées météo et jardin (0.94.0) : une seule liste, fidèle à la configuration.

L'onglet Météo de la page et l'alerte « des mesures manquent » lisent `sources.SOURCES`. Une entrée
oubliée ici serait invisible sur la page et jamais surveillée ; une clé mal écrite montrerait une
entrée « non branchée » alors qu'elle l'est.
"""

from __future__ import annotations

import importlib
import unittest

from tests.test_watering_session_monitoring import coordinator_mod  # noqa: F401 - installe les stubs HA

const = importlib.import_module("custom_components.gazon_intelligent.const")
sources = importlib.import_module("custom_components.gazon_intelligent.sources")


class LaListeDesEntreesTests(unittest.TestCase):
    def test_des_cles_uniques_et_des_groupes_connus(self) -> None:
        cles = [s.cle for s in sources.SOURCES]
        self.assertEqual(len(cles), len(set(cles)))
        groupes = {cle for cle, _ in sources.GROUPES_SOURCES}
        for s in sources.SOURCES:
            with self.subTest(cle=s.cle):
                self.assertIn(s.groupe, groupes)
                self.assertTrue(s.titre and s.dans_une_phrase and s.apporte and s.sans_elle)
                self.assertEqual(s.dans_une_phrase, s.dans_une_phrase.lower()[:1] + s.dans_une_phrase[1:])

    def test_toutes_les_entrees_meteo_et_jardin_y_sont(self) -> None:
        attendues = set(const.SHARED_WEATHER_CONFIG_KEYS) | {
            const.CONF_CAPTEUR_HUMIDITE_SOL,
            const.CONF_CAPTEUR_HAUTEUR_GAZON,
            const.CONF_CAPTEUR_RETOUR_ARROSAGE,
        }
        self.assertEqual({s.cle for s in sources.SOURCES}, attendues)

    def test_chaque_entree_existe_dans_le_formulaire_des_options(self) -> None:
        """La page renvoie aux options pour brancher une entrée : chacune doit y être proposée."""
        from pathlib import Path

        formulaire = (Path(const.__file__).parent / "config_flow.py").read_text(encoding="utf-8")
        schema = formulaire.split("def build_advanced_schema", 1)[1].split("\nclass ", 1)[0]
        noms = [nom for nom in dir(const) if nom.startswith("CONF_")]
        for s in sources.SOURCES:
            with self.subTest(cle=s.cle):
                (constante,) = [nom for nom in noms if getattr(const, nom) == s.cle]
                self.assertRegex(schema, rf"vol\.(Required|Optional)\(\s*{constante}\b")

    def test_ce_qui_est_surveille(self) -> None:
        pas_des_mesures = {s.cle for s in sources.SOURCES if not s.mesure}
        self.assertEqual(pas_des_mesures, {
            const.CONF_CAPTEUR_PLUIE_DEMAIN, const.CONF_CAPTEUR_HAUTEUR_GAZON, const.CONF_CAPTEUR_RETOUR_ARROSAGE,
        })
        self.assertEqual({s.cle for s in sources.SOURCES if not s.numerique}, {const.CONF_ENTITE_METEO})

    def test_une_valeur_utilisable(self) -> None:
        for etat, numerique, attendu in (
            ("17.5", True, True), ("0", True, True), ("-3", True, True),
            ("unavailable", True, False), ("unknown", False, False), ("", False, False), (None, True, False),
            ("nan", True, False), ("abc", True, False), ("cloudy", False, True), ("Unavailable", False, False),
        ):
            with self.subTest(etat=etat, numerique=numerique):
                self.assertIs(sources.valeur_utilisable(etat, numerique=numerique), attendu)

    def test_l_export_est_du_json(self) -> None:
        import json

        export = sources.exporter()
        json.dumps(export)
        self.assertEqual([e["cle"] for e in export], [s.cle for s in sources.SOURCES])
        self.assertEqual(export[6]["indices"], ["rosee", "dew"])
        self.assertEqual(export[7]["indices"], ["foliaire", "feuillage", "leaf_wetness", "leaf_moisture"])
        self.assertEqual(export[1]["noms_refuses"][:2], ["rosee", "dew"])

    def test_un_point_de_rosee_n_est_pas_propose_pour_la_rosee(self) -> None:
        # 0.94.1 : le moteur lit « Rosée sur l'herbe » comme « au-dessus de 0 = mouillée ». Un point
        # de rosée (une température, 11 °C) y ferait croire l'herbe toujours mouillée.
        rosee = sources.PAR_CLE["capteur_rosee"]
        self.assertNotIn("point de rosée", rosee.titre.lower())
        self.assertIn("Ce n'est pas le point de rosée", rosee.apporte)
        for nom in ("sensor.station_point_de_rosee", "sensor.dew_point", "sensor.jardin_dewpoint", "sensor.rosee"):
            with self.subTest(nom=nom):
                self.assertFalse(any(indice in nom for indice in rosee.indices))
        self.assertTrue(any(indice in "sensor.jardin_humidite_foliaire" for indice in rosee.indices))

    def test_le_point_de_rosee_air_est_distinct_de_la_rosee_sur_l_herbe(self) -> None:
        # 0.97.24 : les deux rôles sont volontairement voisins dans le fichier (une température
        # pour l'un, une humidité du feuillage pour l'autre) — jamais interchangeables.
        point_de_rosee = sources.PAR_CLE["capteur_point_de_rosee"]
        rosee = sources.PAR_CLE["capteur_rosee"]
        self.assertIn("(air)", point_de_rosee.titre)
        self.assertNotIn("herbe", point_de_rosee.titre.lower())
        # °C uniquement (0.97.25, relecture automatique) : la valeur n'est jamais convertie avant
        # comparaison, comme la température de l'air — un °F ou K serait lu comme des °C.
        self.assertEqual(point_de_rosee.unites, ("°C",))
        self.assertEqual(point_de_rosee.classes, ("temperature",))
        self.assertNotEqual(point_de_rosee.indices, rosee.indices)



class CeQueLaPageAccepteTests(unittest.TestCase):
    """0.95.0 : une entrée changée sur la page doit être lue par le moteur SANS contresens."""

    water = importlib.import_module("custom_components.gazon_intelligent.water")

    def _refus(self, cle: str, entity_id: str, unite=None, classe=None, **autres):
        return sources.refus(sources.PAR_CLE[cle], entity_id=entity_id, unite=unite, classe=classe, **autres)

    def test_le_domaine(self) -> None:
        self.assertIsNone(self._refus("entite_meteo", "weather.maison"))
        self.assertEqual(self._refus("entite_meteo", "sensor.meteo"), "« Entité météo » attend une entité météo (weather).")
        self.assertEqual(self._refus("capteur_vent", "number.vent", "km/h"), "« Vent » attend un capteur (sensor).")
        self.assertTrue(sources.PAR_CLE["entite_meteo"].obligatoire)
        self.assertEqual([s.cle for s in sources.SOURCES if s.obligatoire], ["entite_meteo"])

    def test_les_unites(self) -> None:
        acceptees = {
            "capteur_temperature": ["°C", "°c"],
            "capteur_humidite": ["%"],
            "capteur_vent": ["km/h", "m/s", "mph", "kn", "kt", "KM/H"],
            "capteur_rayonnement": ["W/m²", "W/m2"],
            "capteur_pression": ["hPa", "mbar", "kPa", "Pa", "bar", "inHg", "mmHg", "HPA"],
            "capteur_pluie_cumul": ["mm"],
            "capteur_pluie_24h": ["mm"],
            "capteur_pluie_actuelle": ["mm", "mm/h"],
            "capteur_pluie_demain": ["mm"],
            "capteur_etp": ["mm", "mm/d", "mm/j"],
            "capteur_humidite_sol": ["%"],
            "capteur_hauteur_gazon": ["cm"],
            "capteur_retour_arrosage": ["mm"],
            "capteur_rosee": ["%", None, "mm"],
        }
        refusees = {
            "capteur_temperature": ["°F", "K", None],
            "capteur_humidite": ["g/m³", None],
            "capteur_vent": ["ft/s", "Beaufort", None],
            "capteur_rayonnement": ["kW/m²", "lx", "BTU/(h⋅ft²)", None],
            "capteur_pression": ["psi", "cbar", None],
            "capteur_pluie_cumul": ["in", "cm", None],
            # Sans unité : l'indice UV de la station (2 en plein jour) dirait « il pleut ».
            "capteur_pluie_actuelle": ["in/h", None],
            "capteur_hauteur_gazon": ["mm", "in", None],
            "capteur_rosee": ["°C", "°F", "K"],
        }
        # Sans classe déclarée, certains rôles exigent un nom qui les annonce : il l'annonce ici.
        noms = {
            "capteur_rosee": "sensor.feuilles_foliaire",
            "capteur_humidite": "sensor.air_humidite",
            "capteur_humidite_sol": "sensor.jardin_humidite_sol",
            "capteur_pluie_demain": "sensor.pluie_demain",
            "capteur_etp": "sensor.etp_du_jour",
            "capteur_hauteur_gazon": "sensor.hauteur_herbe",
            "capteur_retour_arrosage": "sensor.eau_arrosage",
        }
        for cle, unites in acceptees.items():
            for unite in unites:
                with self.subTest(cle=cle, unite=unite, attendu="acceptée"):
                    self.assertIsNone(self._refus(cle, noms.get(cle, "sensor.mesure"), unite))
        for cle, unites in refusees.items():
            for unite in unites:
                with self.subTest(cle=cle, unite=unite, attendu="refusée"):
                    self.assertIsNotNone(self._refus(cle, noms.get(cle, "sensor.mesure"), unite))
        self.assertEqual(
            self._refus("capteur_pression", "sensor.x", "psi"),
            "« Pression » attend une mesure en hPa, mbar, kPa, Pa, bar, inHg ou mmHg, et ce capteur est en psi.",
        )
        self.assertEqual(
            self._refus("capteur_temperature", "sensor.x"),
            "« Température » attend une mesure en °C, et ce capteur n'a pas d'unité.",
        )
        self.assertEqual(
            self._refus("capteur_rayonnement", "sensor.x", "kW/m²"),
            "« Rayonnement solaire » attend une mesure en W/m², et ce capteur est en kW/m².",
        )

    def test_un_point_de_rosee_est_refuse_meme_sans_unite(self) -> None:
        rosee = sources.PAR_CLE["capteur_rosee"]
        self.assertIn("point de rosée", rosee.refus_explique)
        self.assertIn("la tonte ne partirait plus", rosee.refus_explique)
        self.assertEqual(self._refus("capteur_rosee", "sensor.feuillage", None, "temperature"), rosee.refus_explique)
        self.assertEqual(self._refus("capteur_rosee", "sensor.feuillage", "°C", None), rosee.refus_explique)
        self.assertIsNone(self._refus("capteur_rosee", "sensor.feuillage", "%", "moisture"))

    def test_ce_que_le_moteur_ignore_quoi_qu_il_arrive(self) -> None:
        rosee = sources.PAR_CLE["capteur_rosee"]
        for unite, classe in (("°C", None), ("°f", None), ("K", None), (None, "temperature"), ("%", "TEMPERATURE")):
            with self.subTest(unite=unite, classe=classe):
                self.assertTrue(sources.interdit(rosee, unite=unite, classe=classe))
        for unite, classe in (("%", "moisture"), (None, None), ("", "humidity")):
            with self.subTest(unite=unite, classe=classe):
                self.assertFalse(sources.interdit(rosee, unite=unite, classe=classe))
        # Seule la rosée a des lectures interdites : les autres rôles passent par `refus`.
        self.assertEqual([s.cle for s in sources.SOURCES if s.unites_refusees or s.classes_refusees], ["capteur_rosee"])
        self.assertFalse(sources.interdit(sources.PAR_CLE["capteur_temperature"], unite="°C", classe="temperature"))

    def test_la_rosee_exige_un_nom_qui_dit_le_role(self) -> None:
        """Toute mesure au-dessus de 0 y dit « mouillée » : une humidité de l'air (63 %), une
        batterie ou une pression bloqueraient la tonte pour toujours."""
        rosee = sources.PAR_CLE["capteur_rosee"]
        for entity_id, nom in (
            ("sensor.station_humidite", "Station Humidité"),
            ("sensor.station_pression", None),
            ("sensor.sonde", "Sonde du jardin"),
        ):
            with self.subTest(entity_id=entity_id):
                self.assertEqual(self._refus("capteur_rosee", entity_id, "%", None, nom=nom), rosee.refus_indice)
        for entity_id, nom in (
            ("sensor.jardin_humidite_foliaire", None),
            ("sensor.capteur_7", "Humidité foliaire"),
            ("sensor.capteur_8", "Humidité du Feuillage"),
            ("sensor.ecowitt_leaf_wetness_ch1", None),
            ("sensor.capteur_9", "Leaf-Wetness CH2"),
        ):
            with self.subTest(entity_id=entity_id):
                self.assertIsNone(self._refus("capteur_rosee", entity_id, "%", None, nom=nom))

    def test_le_point_de_rosee_exige_un_nom_qui_dit_le_role(self) -> None:
        """Sans indice dans le nom, une température de l'air ordinaire (même classe, même unité)
        serait prise pour le point de rosée — exactement le piège que `capteur_rosee` évite déjà
        dans l'autre sens."""
        point_de_rosee = sources.PAR_CLE["capteur_point_de_rosee"]
        for entity_id, nom in (
            ("sensor.station_meteo_jardin_temperature", None),
            ("sensor.exterieur", "Température extérieure"),
        ):
            with self.subTest(entity_id=entity_id):
                self.assertEqual(
                    self._refus("capteur_point_de_rosee", entity_id, "°C", "temperature", nom=nom),
                    point_de_rosee.refus_indice,
                )
        for entity_id, nom in (
            ("sensor.station_meteo_jardin_point_de_rosee", None),
            ("sensor.dew_point", None),
            ("sensor.capteur_10", "Point de rosée"),
        ):
            with self.subTest(entity_id=entity_id):
                self.assertIsNone(self._refus("capteur_point_de_rosee", entity_id, "°C", "temperature", nom=nom))

    def test_le_point_de_rosee_refuse_le_fahrenheit_et_le_kelvin(self) -> None:
        """Corrigé en relecture automatique de la PR #52 (21/09/2026) : la valeur n'est jamais
        convertie avant d'être comparée à une température en °C dans `estimate_rosee` — un
        capteur en °F ou K lu tel quel ferait croire l'herbe mouillée en permanence (ou jamais)."""
        for unite in ("°F", "K"):
            with self.subTest(unite=unite):
                self.assertIsNotNone(
                    self._refus(
                        "capteur_point_de_rosee",
                        "sensor.station_meteo_jardin_point_de_rosee",
                        unite,
                        "temperature",
                    )
                )
        self.assertIsNone(
            self._refus(
                "capteur_point_de_rosee", "sensor.station_meteo_jardin_point_de_rosee", "°C", "temperature"
            )
        )

    def test_le_point_de_rosee_et_la_rosee_sur_l_herbe_ne_se_substituent_jamais(self) -> None:
        # Le même capteur réel de station (un point de rosée en °C) est accepté pour l'un,
        # refusé pour l'autre ; une humidité foliaire (%) fait l'inverse.
        self.assertIsNone(
            self._refus("capteur_point_de_rosee", "sensor.station_meteo_jardin_point_de_rosee", "°C", "temperature")
        )
        self.assertIsNotNone(
            self._refus("capteur_rosee", "sensor.station_meteo_jardin_point_de_rosee", "°C", "temperature")
        )
        self.assertIsNotNone(
            self._refus("capteur_point_de_rosee", "sensor.feuillage_humidite_foliaire", "%", "humidity")
        )
        self.assertIsNone(
            self._refus("capteur_rosee", "sensor.feuillage_humidite_foliaire", "%", "humidity")
        )

    def test_la_classe_de_l_appareil_doit_dire_la_meme_chose(self) -> None:
        self.assertEqual(
            self._refus("capteur_humidite", "sensor.bat", "%", "battery"),
            "« Humidité de l'air » attend l'humidité de l'air, et ce capteur mesure autre chose (battery).",
        )
        self.assertIsNotNone(self._refus("capteur_humidite_sol", "sensor.bat", "%", "battery"))
        self.assertIsNotNone(self._refus("capteur_pression", "sensor.x", "kPa", "precipitation"))
        # Sans classe déclarée, l'unité suffit (le rayonnement d'Open-Meteo n'en a pas).
        self.assertIsNone(self._refus("capteur_rayonnement", "sensor.open_meteo", "W/m²", None))
        self.assertIsNone(self._refus("capteur_humidite", "sensor.x", "%", "HUMIDITY"))

    def test_sans_classe_le_nom_doit_annoncer_le_role(self) -> None:
        """Relevé sur la station météo le 17/09 : « Stress thermique » est en %, sans classe."""
        self.assertEqual(
            self._refus("capteur_humidite", "sensor.station_meteo_jardin_stress_thermique", "%", nom="Stress thermique"),
            "« Humidité de l'air » attend l'humidité de l'air, et ce capteur ne dit pas ce qu'il mesure : "
            "ni classe d'appareil, ni nom qui l'annonce.",
        )
        self.assertIsNone(self._refus("capteur_humidite", "sensor.x", "%", nom="Hygrométrie de la serre"))
        self.assertIsNone(self._refus("capteur_humidite", "sensor.x", "%", "humidity"))
        # L'humidité du sol : la classe « moisture », ou un nom qui le dit — jamais l'humidité de l'air,
        # qui dépasse souvent les 70 % où la tonte attend.
        self.assertEqual(
            self._refus("capteur_humidite_sol", "sensor.meteo_netatmo_humidite", "%", "humidity"),
            "« Humidité du sol » attend l'humidité du sol, et ce capteur mesure autre chose (humidity).",
        )
        self.assertIsNotNone(self._refus("capteur_humidite_sol", "sensor.station_humidite", "%"))
        self.assertIsNone(self._refus("capteur_humidite_sol", "sensor.sonde", "%", "moisture"))
        self.assertIsNone(self._refus("capteur_humidite_sol", "sensor.sonde", "%", nom="Humidité du sol"))
        self.assertIsNone(self._refus("capteur_humidite_sol", "sensor.soil_sensor_3", "%"))

    def test_un_nom_qui_annonce_autre_chose_est_refuse(self) -> None:
        """Tous en °C, classe « temperature » : ce ne sont pas la température de l'air."""
        for entity_id, nom in (
            ("sensor.station_meteo_jardin_point_de_rosee", None),
            ("sensor.station_meteo_jardin_humidex", None),
            ("sensor.station_meteo_jardin_temperature_ressentie", None),
            ("sensor.station_meteo_jardin_refroidissement_eolien", None),
            ("sensor.capteur_4", "Temperature du sol"),
            ("sensor.dew_point", None),
            ("sensor.heat_index", None),
        ):
            with self.subTest(entity_id=entity_id):
                self.assertEqual(
                    self._refus("capteur_temperature", entity_id, "°C", "temperature", nom=nom),
                    f"« Température » attend la température, et « {nom or entity_id} » mesure autre chose.",
                )
        for entity_id in ("sensor.station_meteo_jardin_temperature", "sensor.panneau_solaire_temperature", "sensor.console_temp"):
            with self.subTest(entity_id=entity_id):
                self.assertIsNone(self._refus("capteur_temperature", entity_id, "°C", "temperature"))
        self.assertIsNotNone(self._refus("capteur_humidite", "sensor.humidite_du_sol", "%"))
        for entity_id in ("sensor.station_meteo_jardin_rafales", "sensor.meteo_netatmo_force_des_rafales", "sensor.wind_gust"):
            with self.subTest(entity_id=entity_id):
                self.assertIsNotNone(self._refus("capteur_vent", entity_id, "km/h", "wind_speed"))
        self.assertIsNone(self._refus("capteur_vent", "sensor.station_meteo_jardin_vent", "km/h", "wind_speed"))
        self.assertIsNone(self._refus("capteur_vent", "sensor.meteo_netatmo_vitesse_du_vent", "km/h", "wind_speed"))
        self.assertIsNotNone(self._refus("capteur_humidite", "sensor.x", "%", "humidity", nom="Humidité foliaire"))

    def test_un_pluviometre_ne_tient_pas_les_roles_qui_lui_ressemblent(self) -> None:
        """Tous en mm, classe « precipitation » : seul le nom distingue la pluie du reste."""
        pluviometre = {"unite": "mm", "classe": "precipitation", "classe_etat": "total_increasing", "etat": "2.4"}
        for cle in ("capteur_pluie_demain", "capteur_etp", "capteur_retour_arrosage"):
            with self.subTest(cle=cle):
                self.assertEqual(
                    self._refus(cle, "sensor.meteo_netatmo_precipitation_aujourd_hui", **pluviometre),
                    sources.PAR_CLE[cle].refus_indice,
                )
        for cle, entity_id in (
            ("capteur_pluie_demain", "sensor.pluie_prevue_demain"),
            ("capteur_etp", "sensor.smart_irrigation_evapotranspiration"),
            ("capteur_retour_arrosage", "sensor.eau_d_arrosage_du_jour"),
        ):
            with self.subTest(cle=cle, entity_id=entity_id):
                self.assertIsNone(self._refus(cle, entity_id, "mm", "precipitation"))
        self.assertEqual(
            self._refus("capteur_hauteur_gazon", "sensor.niveau_cuve", "cm", "distance"),
            sources.PAR_CLE["capteur_hauteur_gazon"].refus_indice,
        )
        self.assertIsNone(self._refus("capteur_hauteur_gazon", "sensor.robot_hauteur_herbe", "cm", "distance"))

    def test_la_pluie_du_jour_est_un_cumul_du_jour(self) -> None:
        for cle in ("capteur_pluie_24h", "capteur_pluie_cumul"):
            with self.subTest(cle=cle, cas="mesure de l'instant"):
                self.assertEqual(
                    self._refus(cle, "sensor.meteo_netatmo_precipitation", "mm", "precipitation", classe_etat="measurement"),
                    sources.PAR_CLE[cle].refus_classe_etat,
                )
            for entity_id in (
                "sensor.meteo_netatmo_precipitations_dans_l_heure_precedente",
                "sensor.pluie_demain",
                "sensor.pluie_intensite",
            ):
                with self.subTest(cle=cle, entity_id=entity_id):
                    self.assertIsNotNone(self._refus(cle, entity_id, "mm", "precipitation", classe_etat="total"))
            with self.subTest(cle=cle, cas="cumul"):
                self.assertIsNone(
                    self._refus(cle, "sensor.pluie_du_jour_ws90", "mm", "precipitation", classe_etat="total_increasing")
                )

    def test_pluie_en_ce_moment_refuse_un_cumul(self) -> None:
        refus_classe_etat = sources.PAR_CLE["capteur_pluie_actuelle"].refus_classe_etat
        for classe_etat in ("total_increasing", "total", "TOTAL"):
            with self.subTest(classe_etat=classe_etat):
                self.assertEqual(
                    self._refus("capteur_pluie_actuelle", "sensor.p", "mm", "precipitation", classe_etat=classe_etat),
                    refus_classe_etat,
                )
        self.assertIsNone(self._refus("capteur_pluie_actuelle", "sensor.p", "mm", "precipitation", classe_etat="measurement"))
        # Pour la pluie du jour, un cumul est justement ce qu'il faut.
        self.assertIsNone(self._refus("capteur_pluie_24h", "sensor.p", "mm", "precipitation", classe_etat="total_increasing"))

    def test_une_mesure_donne_un_nombre(self) -> None:
        for etat in ("Pas de pluie", "3 mm", "nan", "3abc"):
            with self.subTest(etat=etat):
                self.assertEqual(
                    self._refus("capteur_pluie_actuelle", "sensor.p", "mm", etat=etat),
                    f"« Pluie en ce moment » attend un nombre, et ce capteur donne « {etat} ».",
                )
        # Indisponible au moment du choix : rien à juger, la valeur reviendra.
        for etat in ("0", "12.5", "-3", "unavailable", "unknown", "", None):
            with self.subTest(etat=etat):
                self.assertIsNone(self._refus("capteur_pluie_actuelle", "sensor.p", "mm", etat=etat))
        # L'entité météo donne un texte : c'est normal.
        self.assertIsNone(self._refus("entite_meteo", "weather.maison", etat="sunny"))

    def test_chaque_unite_acceptee_est_convertie_par_le_moteur(self) -> None:
        """La liste de la page et la conversion du moteur ne doivent pas diverger : une unité
        acceptée sans conversion serait lue comme des hPa ou des km/h, sans un mot."""
        pression_type = {"hPa": 1013.0, "mbar": 1013.0, "kPa": 101.3, "Pa": 101300.0, "bar": 1.013,
                         "inHg": 29.9139, "mmHg": 759.8}
        for unite in sources.UNITES_PRESSION:
            with self.subTest(unite=unite):
                self.assertAlmostEqual(self.water.pression_vers_hpa(pression_type[unite], unite), 1013.0, delta=0.5)
        vent_type = {"km/h": 36.0, "m/s": 10.0, "mph": 22.3694, "kn": 19.4384, "kt": 19.4384}
        for unite in sources.UNITES_VENT:
            with self.subTest(unite=unite):
                self.assertAlmostEqual(self.water.wind_speed_to_kmh(vent_type[unite], unite), 36.0, delta=0.05)
        self.assertEqual(sources.PAR_CLE["capteur_pression"].unites, sources.UNITES_PRESSION)
        self.assertEqual(sources.PAR_CLE["capteur_vent"].unites, sources.UNITES_VENT)

    def test_une_unite_refusee_n_est_jamais_acceptee(self) -> None:
        for s in sources.SOURCES:
            with self.subTest(cle=s.cle):
                self.assertFalse({u.casefold() for u in s.unites} & {u.casefold() for u in s.unites_refusees})
                if s.classes_refusees or s.unites_refusees:
                    self.assertTrue(s.refus_explique)


if __name__ == "__main__":
    unittest.main()
