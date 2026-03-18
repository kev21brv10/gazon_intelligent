# Gazon Intelligent 🌱

Intégration Home Assistant pour aider à gérer le gazon simplement.
Elle analyse la météo, le sol et l'historique, puis propose quoi faire.

Objectif: installer, choisir les capteurs, noter ce qui a été fait si besoin, puis laisser le système décider.

## Installation

### Via HACS

1. Ajouter ce dépôt comme dépôt personnalisé HACS, catégorie `Integration`.
2. Installer **Gazon Intelligent**.
3. Redémarrer Home Assistant.
4. Ajouter l'intégration depuis `Paramètres > Appareils et services`.

### Manuelle

1. Copier `custom_components/gazon_intelligent` dans `config/custom_components`.
2. Redémarrer Home Assistant.
3. Ajouter l'intégration depuis `Paramètres > Appareils et services`.

## Configuration

L'intégration se configure via formulaire.

- Zones d'arrosage `switch`:
  - `zone_1` obligatoire
  - `zone_2` à `zone_5` optionnelles
- Débit par zone:
  - `debit_zone_1` obligatoire, défaut conseillé `60`
  - autres débits optionnels
- Capteurs météo:
  - `capteur_pluie_24h` obligatoire
  - `capteur_pluie_demain` optionnel
  - `capteur_temperature`, `capteur_etp`, `capteur_humidite` optionnels
- `entite_meteo` (`weather`) optionnelle:
  - utilisée pour récupérer la pluie J+1 automatiquement si `capteur_pluie_demain` est absent
- `type_sol`:
  - `sableux`, `limoneux`, `argileux`
- Capteurs avancés optionnels:
  - humidité du sol, vent, rosée, hauteur du gazon, retour réel d'arrosage, pluie plus fine
  - ils améliorent le moteur sans être obligatoires

## Usage réel

Le chemin normal est simple:

1. l'intégration calcule ce qu'il faut faire,
2. tu déclares les interventions avec les boutons,
3. le système ajuste ses conseils.

### Boutons

- `Déclarer un sursemis`
- `Déclarer une fertilisation`
- `Déclarer un traitement`
- `Déclarer une scarification`
- `Retour au mode normal`
- `Noter la date du jour` met à jour la dernière intervention active avec la date du jour

### Mode expert

- `Mode expert` reste disponible pour les cas spéciaux.
- Il n'est pas nécessaire à l'usage courant.

## Lecture rapide

Pour lire l'écran vite, regarde dans cet ordre:

- `Phase dominante`: ce qui pilote vraiment le gazon
- `État de tonte`: tonte autorisée ou non
- `Conseil principal`: ce qu'il faut faire maintenant
- `Action à éviter`: ce qu'il vaut mieux ne pas faire
- `Niveau d'action`: priorité de l'action
- `Fenêtre optimale`: meilleur moment pour agir

## Entités créées

### Select

- `Mode expert`

### Sensors

- `Phase dominante`
- `État de tonte`
- `Pourquoi ce choix`
- `Conseil principal`
- `Action recommandée`
- `Action à éviter`
- `Niveau d'action`
- `Fenêtre optimale`
- `Risque gazon`
- `Prochaine réévaluation`
- `Stade actuel`
- `Objectif d'arrosage`
- `Jours restants de la phase`
- `Date d'action`
- `Date de fin de phase`

### Diagnostics

- `Manque d'eau estimé`
- `Besoin en eau du jour (ETP)`
- `Niveau de manque d'eau`
- `Niveau de stress du gazon`
- `Risque de tonte`
- `Humidité extérieure`
- `Pluie 24h`
- `Pluie prévue demain`
- `Température extérieure`
- `Arrosage conseillé`
- `Mode d'arrosage`

### Binary sensors

- `Tonte autorisée`
- `Arrosage auto autorisé`
- `Arrosage recommandé`

## Attributs utiles

Les attributs sont ciblés selon l'entité.

- `Phase dominante`:
  - contexte de décision complet: entités utilisées, configuration, source de la pluie J+1, contexte avancé, état de la phase et état de tonte
- `Stade actuel`:
  - détail, âge et progression de la phase
- `État de tonte`:
  - statut lisible de la tonte: autorisée, à surveiller, déconseillée ou interdite
- `Pluie prévue demain`:
  - source de la valeur (`capteur`, `meteo_forecast`, `indisponible`)
- `Objectif d'arrosage` et `Manque d'eau estimé`:
  - métriques hydriques détaillées
- `Pourquoi ce choix`, `Conseil principal`, `Action recommandée`, `Risque gazon`:
  - contexte de décision et prochaine réévaluation
- `Mode expert`:
  - vue système rapide pour diagnostic et pilotage

## Services disponibles

- `gazon_intelligent.set_mode`
- `gazon_intelligent.set_date_action`
- `gazon_intelligent.reset_mode`
- `gazon_intelligent.start_manual_irrigation`
- `gazon_intelligent.start_auto_irrigation`
- `gazon_intelligent.declare_intervention`
- `gazon_intelligent.declare_mowing`
- `gazon_intelligent.declare_watering`

Les champs détaillés sont dans `custom_components/gazon_intelligent/services.yaml`.

## Événement Home Assistant

- `gazon_intelligent_manual_irrigation_requested`

Émis par `start_manual_irrigation` avec:
- `objectif_mm`
- `mode`
- `date_action`

## Blueprint

- Fichier:
  - `blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml`
- Nom:
  - `Gazon Intelligent - Arrosage intelligent (modes spéciaux hors Normal)`

[Importer le blueprint dans Home Assistant](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/kev21brv10/gazon_intelligent/blob/main/blueprints/automation/gazon_intelligent/arrosage_modes_speciaux_hors_normal.yaml)

## Glossaire rapide

- `ETP`: besoin en eau estimé pour la journée.
- `Phase dominante`: phase qui gouverne réellement le gazon.
- `Stade actuel`: étape fine à l'intérieur d'une phase dominante.
- `Manque d'eau estimé`: quantité d'eau manquante en mm.
- `deficit_jour`, `deficit_3j`, `deficit_7j`: bilan hydrique court et moyen terme.
- `pluie_efficace`: pluie réellement retenue par le calcul.
- `arrosage_recent`: arrosage cumulé récent pris en compte par le moteur.
- `Niveau d'action`: priorité du moteur, de `aucune_action` à `critique`.
- `Fenêtre optimale`: meilleur moment pour agir.
- `Si on attend`: risque synthétique si l'action est retardée.
- `Prochaine réévaluation`: quand relancer le calcul du moteur.
