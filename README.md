# Gazon Intelligent

<p align="center">
  <img src="https://raw.githubusercontent.com/kev21brv10/gazon_intelligent/main/logo.png" width="120" alt="Logo Gazon Intelligent">
</p>

<p align="center">
  <strong>Une intégration Home Assistant qui transforme tes capteurs et la météo en décisions claires pour ton gazon.</strong><br>
  Arrosage, tonte, phases, interventions produit, et coordination optionnelle avec un robot tondeuse.
</p>

<p align="center">
  <img src="https://img.shields.io/github/v/release/kev21brv10/gazon_intelligent?color=2f9e44" alt="Version">
  <img src="https://img.shields.io/badge/HACS-Custom-f57c00" alt="HACS">
  <img src="https://img.shields.io/badge/Home%20Assistant-2026.3.2+-1e88e5" alt="Home Assistant">
  <img src="https://img.shields.io/github/license/kev21brv10/gazon_intelligent" alt="License">
</p>

---

Gazon Intelligent ne se contente pas d'allumer des zones d'arrosage ou de remonter quelques capteurs. Il répond à **4 questions**, directement dans Home Assistant :

- **Quoi faire maintenant ?** — arroser, tondre, appliquer un produit, ou attendre
- **Pourquoi ?** — le motif est toujours lisible, jamais un blocage muet
- **Quand reconsidérer ?** — la prochaine fenêtre d'arrosage / de tonte
- **Dans quel contexte ?** — phase du gazon, réserve d'eau, météo, risque

## Sommaire

- [✨ Fonctionnalités](#-fonctionnalités)
- [🧠 Le principe](#-le-principe)
- [📦 Installation](#-installation)
- [⚙️ Configuration](#-configuration)
- [🚀 Prise en main](#-prise-en-main)
- [🔎 Comment ça décide](#-comment-ça-décide)
- [🎛️ Réglages et actions](#-réglages-et-actions)
- [🛠️ Services](#-services)
- [🧩 Carte Lovelace](#-carte-lovelace)
- [🚫 Ce qu'elle ne fait pas](#-ce-quelle-ne-fait-pas)
- [📝 Changelog](#-changelog)
- [🧪 Développement](#-développement)
- [📄 Licence](#-licence)

## ✨ Fonctionnalités

**💧 Arrosage intelligent (mode Normal)**
- Piloté par la **réserve d'eau du sol** : on laisse la réserve descendre jusqu'au **seuil d'épuisement (MAD 50 %)**, puis on **recharge en profondeur** jusqu'au plein. Résultat : des arrosages **plus espacés et plus profonds** → meilleur enracinement, au lieu de petits apports fréquents.
- Borné par un **garde-fou hebdomadaire** (jamais trop d'eau sur la semaine).
- **Calcul ET0 réaliste sans capteur dédié** (FAO-56), tenant compte de la pluie, du vent, de l'humidité et de la rosée.
- **Gestion canicule** : dose de **survie** le matin si la réserve est presque vide, et **rafraîchissement du soir** (petit arrosage de **3 mm, 30 min avant le coucher du soleil**) pour faire baisser la température du gazon même réserve pleine — sous garde-fous anti-maladies (air sec, pas de pluie).
- **Comptage fiable** de l'eau réellement appliquée (anti double-comptage des cycles fractionnés) et **suivi en temps réel** pendant un cycle.

**✂️ Tonte coordonnée**
- **Autorisation métier** selon la phase, le risque, la météo et l'heure (fenêtre **10 h–22 h**, nuit bloquée).
- **Fréquence cible** (~5/semaine) et **quota journalier** adaptés à la phase.
- **Coordination robot tondeuse** (optionnelle, par pelouse) : pas de tonte sous la pluie ni pendant l'arrosage, hauteur de coupe synchronisable, et séparation nette entre « gazon autorisé » et « machine disponible ».

**🌱 Phases du gazon**
- Suit la phase dominante (Normal, Sursemis, Traitement, Scarification, Hivernage…) et adapte l'arrosage **et** la tonte en conséquence.

**🧪 Interventions produit**
- Catalogue de produits (engrais, biostimulants, agent mouillant…), **scoring** selon phase / saison / météo, et recommandation de la prochaine application.

**🧩 Et aussi**
- **Multi-pelouse** : une instance par pelouse, proprement séparées.
- **Façade lisible** centrée sur `sensor.gazon_intelligent_assistant`.
- **Carte Lovelace dédiée** en complément.

> Contrat public détaillé des attributs exposés : [docs/public-attribute-contract.md](docs/public-attribute-contract.md).

## 🧠 Le principe

L'intégration sépare **trois niveaux**, pour éviter les faux signaux :

1. **Le gazon** — phase, sous-phase, risque, réserve hydrique
2. **La décision** — arroser / tondre ou non, prochaine fenêtre, blocage ou attente
3. **L'exécution** — machine disponible, coordination active, action réellement possible

Cette séparation évite les contradictions du type *« gazon autorisé mais machine indisponible »* ou *« arrosage bloqué sans explication »*.

## 📦 Installation

### Via HACS (recommandé)

1. **HACS → Intégrations → ⋮ → Dépôts personnalisés**
2. Ajoute `https://github.com/kev21brv10/gazon_intelligent`, catégorie **Intégration**
3. Installe **Gazon Intelligent**, puis **redémarre Home Assistant**
4. **Paramètres → Appareils et services → Ajouter une intégration** → `Gazon Intelligent`

### Manuelle

1. Copie [`custom_components/gazon_intelligent`](custom_components/gazon_intelligent) dans `config/custom_components`
2. Redémarre Home Assistant
3. Ajoute l'intégration depuis **Paramètres → Appareils et services**

> **Compatibilité** : Home Assistant `2026.3.2+`. Aucune configuration YAML n'est requise.

## ⚙️ Configuration

Tout se fait depuis l'interface (config flow), **par pelouse**.

**1. Pelouse** — `instance_slug` (pour séparer plusieurs gazons), zones `zone_1`…`zone_5` avec leurs débits `debit_zone_1`…`debit_zone_5`, et `type_sol`.

**2. Météo et capteurs** *(tous optionnels — l'intégration estime ce qui manque)* — `entite_meteo`, `capteur_pluie_24h`, `capteur_pluie_demain`, `capteur_temperature`, `capteur_etp`, `capteur_humidite`, `capteur_humidite_sol`, `capteur_vent`, `capteur_rosee`, `capteur_hauteur_gazon`, `capteur_retour_arrosage`.

**3. Robot tondeuse** *(optionnel, par pelouse)* — `entite_tondeuse`, `capteur_tondeuse_erreur`, `capteur_tondeuse_batterie`, `capteur_tondeuse_pluie`, `capteur_tondeuse_en_charge`, `capteur_tondeuse_prochain_depart`, `capteur_tondeuse_hauteur_coupe`, `hauteur_min_tondeuse_cm`, `hauteur_max_tondeuse_cm`.

> Coordination désactivée → l'intégration calcule toujours la logique gazon, mais ne considère plus la machine comme pilotable.

## 🚀 Prise en main

**Le point d'entrée** : `sensor.gazon_intelligent_assistant` — il résume l'action prioritaire (ou la raison d'attendre).

| Thème | Entités à lire en premier |
|---|---|
| **Arrosage** | `prochain_arrosage` · `fenetre_optimale` · `objectif_d_arrosage` · `plan_d_arrosage` · `binary_sensor…arrosage_recommande` · `…signal_irrigation` |
| **Tonte** | `binary_sensor…tonte_autorisee` · `etat_de_tonte` · `prochaine_tonte` · `hauteur_de_tonte_conseillee` · `hauteur_gazon_estimee` *(estimée sans capteur)* |
| **Phase & contexte** | `phase_dominante` · `sous_phase` · `risque_gazon` · `type_d_arrosage` |
| **Produits** | `prochaine_intervention` · `catalogue_produits` · `niveau_de_pertinence` · `binary_sensor…signal_intervention` · `select…produit_d_intervention` |

*(préfixe commun : `sensor.gazon_intelligent_…`)*

Côté tonte, les attributs `gazon_permet_tonte`, `machine_permet_tonte`, `action_possible`, `mowing_block_reason_code` / `…_label` et `mowing_watering_coordination` *(none / discourage / block)* détaillent la décision.

## 🔎 Comment ça décide

### Arrosage

`sensor.gazon_intelligent_prochain_arrosage` est la lecture la plus directe. Il affiche soit une **fenêtre utile avec objectif** (ex. *« demain matin, 8 mm »*), soit un **blocage avec son motif** (cooldown, pluie prévue, sol humide, garde-fou hebdo plafonné…), soit **« Non requis »** (réserve suffisante). Le motif n'est **jamais muet**.

### Tonte

`binary_sensor.gazon_intelligent_tonte_autorisee` exprime l'autorisation **métier** ; l'action finale dépend aussi de la **machine** (prête ou non) et de la **coordination**.

**Fenêtre horaire** (créneaux où une nouvelle tonte peut partir, si la météo le permet) :

- **idéale : 10 h – 12 h** · **acceptable : 17 h – 19 h**
- permise mais déconseillée : 12 h – 17 h et 19 h – 22 h
- **bloquée la nuit : 22 h → 10 h**

La météo bloque à **toute heure** : pluie en cours/imminente, rosée présente, température < 8 °C ou trop élevée, vent fort.

**Fréquence** : cible **4 à 6 tontes/semaine**, avec **2 tontes/jour** max en phase Normal (**1/jour** en phases sensibles). Une « tonte » = un **cycle complet** ; les retours en base pour recharge ne comptent pas. Avec coordination active, le robot est **rappelé** sous la pluie / pendant l'arrosage, puis **relancé** dès que les conditions repassent au vert.

### Phases sensibles

`Sursemis`, `Traitement`, `Hivernage`, `Scarification` dominent la lecture publique — ex. *« Phase Sursemis : tonte interdite pendant l'installation du gazon. »*

## 🎛️ Réglages et actions

- **Boutons** — `arroser_maintenant` · `date_action_today` · `retour_mode_normal`
- **Switches** — `arrosage_automatique_autorise` · `coordination_tondeuse`
- **Selects** — `mode_du_gazon` · `produit_d_intervention`
- **Numbers** —
  - `debit_zone_1` à `debit_zone_5`
  - `hauteur_min_tondeuse` / `hauteur_max_tondeuse` — plage de hauteur de **ta** tondeuse (en cm)
  - `hauteur_coupe_tondeuse` — hauteur de coupe cible (en mm) ; ses **bornes suivent automatiquement** la plage min/max ci-dessus (ex. 3–6 cm → curseur 30–60 mm), pour coller à n'importe quelle tondeuse
  - `delai_reprise_tonte_apres_arrosage`

## 🛠️ Services

| Domaine | Services *(préfixe `gazon_intelligent.`)* |
|---|---|
| **Métier** | `set_mode` · `reset_mode` · `set_date_action` |
| **Arrosage** | `start_manual_irrigation` · `start_auto_irrigation` · `start_application_irrigation` · `declare_watering` · `recalibrate_reserve` |
| **Tonte** | `declare_mowing` |
| **Produits** | `declare_intervention` · `remove_last_application` · `register_product` · `remove_product` |

`recalibrate_reserve` recale la réserve hydrique du sol à une valeur connue (calibration manuelle, persistante au redémarrage).

## 🧩 Carte Lovelace

Une carte dédiée — `lovelace-gazon-intelligent-card` — organise la façade publique en onglets : **synthèse · irrigation · tonte · gazon · produits · intervention · réglages**. Elle lit les entités publiques et les structure pour une lecture rapide ; elle ne remplace pas l'intégration.

## 🚫 Ce qu'elle ne fait pas

- Elle ne remplace **pas** ton matériel d'arrosage.
- Elle ne remplace **pas** les sécurités natives de ta tondeuse.
- Elle ne garantit pas **seule** un déclenchement automatique sans automatisations autour.

Son rôle : fournir une base métier **cohérente, lisible et exploitable**.

## 📝 Changelog

L'historique complet des versions est dans **[CHANGELOG.md](CHANGELOG.md)**.

## 🧪 Développement

Validation CI (GitHub Actions) à chaque push/PR : **Hassfest · Ruff · mypy · tests unitaires**. La logique métier vit surtout dans :

- [`coordinator.py`](custom_components/gazon_intelligent/coordinator.py) — orchestration & état
- [`decision_watering.py`](custom_components/gazon_intelligent/decision_watering.py) — décision d'arrosage
- [`decision_mowing.py`](custom_components/gazon_intelligent/decision_mowing.py) — décision de tonte
- [`guidance.py`](custom_components/gazon_intelligent/guidance.py) — profils d'arrosage (dose, fenêtres, canicule)
- [`assistant.py`](custom_components/gazon_intelligent/assistant.py) — façade « assistant »

## 📄 Licence

Projet publié sous licence **MIT** — voir [`LICENSE`](LICENSE).
