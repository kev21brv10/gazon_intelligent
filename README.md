# Gazon Intelligent 🌱

Intégration Home Assistant pour piloter l'entretien du gazon avec un moteur de décision basé sur:
- la météo,
- le type de sol,
- l'historique réel des actions,
- des scores internes (hydrique, stress, tonte).

Objectif: configurer une fois, déclarer les actions terrain, laisser le système décider.

## Version actuelle 🏷️

- Version `manifest`: `0.3.9`
- Compatibilité HACS indiquée: Home Assistant `2026.3.2`

## Installation 🚀

### 1) Via HACS (recommandé) 🧩

1. Ajouter ce dépôt comme dépôt personnalisé HACS (catégorie `Integration`).
2. Installer **Gazon Intelligent**.
3. Redémarrer Home Assistant.
4. Aller dans `Paramètres > Appareils et services > Ajouter une intégration` puis choisir **Gazon Intelligent**.

### 2) Installation manuelle 🛠️

1. Copier `custom_components/gazon_intelligent` dans votre dossier `config/custom_components`.
2. Redémarrer Home Assistant.
3. Ajouter l'intégration depuis `Paramètres > Appareils et services`.

## Configuration initiale (UI) ⚙️

L'intégration se configure entièrement via formulaire:

- Zones d'arrosage `switch` 💧:
  - `zone_1` obligatoire
  - `zone_2` à `zone_5` optionnelles
- Débit par zone (mm/h):
  - `debit_zone_1` obligatoire (défaut conseillé: `60`)
  - autres débits optionnels
- Capteurs météo 🌦️:
  - `capteur_pluie_24h` obligatoire
  - `capteur_pluie_demain` optionnel
  - `capteur_temperature`, `capteur_etp`, `capteur_humidite` optionnels
- `entite_meteo` (`weather`) optionnelle:
  - utilisée pour récupérer automatiquement la pluie J+1 via `weather.get_forecasts` si `capteur_pluie_demain` n'est pas défini
- `type_sol`:
  - `sableux`, `limoneux`, `argileux`
- `tondeuse` (`lawn_mower`) optionnelle:
  - aujourd'hui stockée dans la config (préparation des évolutions), sans pilotage direct automatique dans cette version

Vous pouvez modifier cette configuration plus tard via les **Options** de l'intégration, sans suppression/recréation.

## Moteur de décision 🧠

Le moteur décide à chaque rafraîchissement (toutes les 5 minutes) avec:

- phase active dominante issue de l'historique (`Sursemis`, `Traitement`, `Fertilisation`, `Biostimulant`, `Agent Mouillant`, `Scarification`, `Hivernage`, sinon `Normal`),
- bilan hydrique basé sur `ETP`, pluie 24h, pluie J+1 et arrosages récents,
- scores internes 📊:
  - `score_hydrique` (besoin en eau),
  - `score_stress` (stress global gazon),
  - `score_tonte` (risque tonte),
- décisions finales ✅:
  - `tonte_autorisee`,
  - `arrosage_auto_autorise`,
  - `arrosage_recommande`,
  - objectif d'arrosage en mm,
  - conseil principal + action recommandée + action à éviter + urgence.

Les phases restent des contraintes métier, mais la décision s'appuie désormais sur les scores.

## Entités créées 📡

### Select

- `Mode gazon`

### Sensors

- `Phase active`
- `Objectif d'arrosage` (mm)
- `Bilan hydrique (déficit)` (mm)
- `Score hydrique`
- `Score stress gazon`
- `Score tonte`
- `Jours restants de la phase` (j)
- `ETP estimée` (mm/j)
- `Humidité extérieure` (%)
- `Date de l'action`
- `Date de fin de phase`
- `Pluie 24h` (mm)
- `Pluie prévue demain` (mm)
- `Température extérieure` (°C)
- `Arrosage (auto/personnalisé)`
- `Type d'arrosage`
- `Raison décision`
- `Conseil principal`
- `Action recommandée`
- `Action à éviter`
- `Urgence`

### Binary sensors

- `Tonte autorisée`
- `Arrosage auto autorisé`
- `Arrosage recommandé`

### Buttons

- `Repasser en mode normal`
- `Date action = aujourd'hui`

## Attributs utiles exposés 📝

Les entités de l'intégration exposent des attributs communs:

- `entites_utilisees`:
  - zones configurées,
  - capteurs météo utilisés,
  - entité météo utilisée
- `configuration`:
  - `type_sol`
- `pluie_demain_source`:
  - `capteur`, `meteo_forecast`, ou `indisponible`
- `historique_resume`:
  - total d'actions mémorisées,
  - dernière intervention

## Services disponibles 🧰

- `gazon_intelligent.set_mode`
- `gazon_intelligent.set_date_action`
- `gazon_intelligent.reset_mode`
- `gazon_intelligent.start_manual_irrigation`
- `gazon_intelligent.start_auto_irrigation`
- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.declare_mowing`
- `gazon_intelligent.declare_watering`

Détails des champs: voir `custom_components/gazon_intelligent/services.yaml`.

## Événement Home Assistant 🔔

- `gazon_intelligent_manual_irrigation_requested`

Émis à l'appel de `start_manual_irrigation` avec:
- `objectif_mm`
- `mode`
- `date_action`

## Blueprint d'arrosage (modes spéciaux hors Normal) 📘

- Fichier:
  - `blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml`
- Nom:
  - `Gazon Intelligent - Arrosage intelligent (modes spéciaux hors Normal)`
- Import direct:

[![Importer ce blueprint dans Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/kev21brv10/gazon_intelligent/blob/main/blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml)

Ce blueprint utilise les entités créées par l'intégration pour automatiser l'arrosage hors mode `Normal`.

## Exemple d'automatisation (événement -> arrosage auto) 🤖

```yaml
alias: Gazon - Arrosage manuel relayé en auto
mode: single
trigger:
  - platform: event
    event_type: gazon_intelligent_manual_irrigation_requested
action:
  - service: gazon_intelligent.start_auto_irrigation
    data: {}
```

## Structure du dépôt 📁

- `custom_components/gazon_intelligent/`:
  - code de l'intégration
- `blueprints/automation/gazon_intelligent/`:
  - blueprint prêt à importer
- `logo.png`, `icon.png`:
  - branding HACS
- `CHANGELOG.md`:
  - historique des versions

## Notes ℹ️

- Les données de mode, date d'action et historique sont persistées.
- L'historique est limité aux 300 derniers enregistrements.
- En cas de capteur absent/inconnu, le moteur applique des valeurs de repli pour rester opérationnel.
