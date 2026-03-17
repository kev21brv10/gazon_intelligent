# Gazon Intelligent

Intégration Home Assistant pour gérer les modes gazon :

- Normal
- Sursemis
- Traitement
- Fertilisation
- Biostimulant
- Agent Mouillant
- Scarification
- Hivernage

## Fonctionnalités

- Configuration UI
- Sélection des entités
- Calcul automatique de l'objectif d'arrosage
- Autorisation tonte / arrosage automatique
- Gestion des phases gazon

## Entités créées

- Mode gazon
- Objectif d'arrosage
- Jours restants de la phase
- Tonte autorisée
- Arrosage automatique autorisé
- Bouton retour au mode normal

## Installation simple

1. Copier `custom_components/gazon_intelligent` dans le dossier `custom_components` de Home Assistant (ou installer via HACS si tu publies le repo).
2. Redémarrer Home Assistant.
3. Dans *Paramètres → Appareils et services → Ajouter une intégration*, choisir **Gazon Intelligent**.

## Configuration (ce qui est demandé)

- Zone 1 (obligatoire) + Zones 2 à 5 (optionnelles) : ce sont tes `switch` d’électrovannes.
- Tondeuse (optionnel, domaine `lawn_mower`).
- Capteur pluie 24h (obligatoire), pluie demain J+1 (prévision, pas la pluie du jour) / température / ETP / humidité extérieure (optionnels).
- Débit par zone (mm/h) : combien de millimètres d’eau la zone apporte en 1 heure. Si tu ne sais pas, laisse 60 mm/h (≈ 1 mm/min) et ajuste après mesure.

## Entités créées

- Sélecteur de mode gazon (Normal, Sursemis, Traitement, Fertilisation, Biostimulant, Agent Mouillant, Scarification, Hivernage).
- Capteur `Objectif d'arrosage` (mm).
- Capteur `Jours restants de la phase`.
- Capteur `ETP estimée` (mm/j) : prend la valeur du capteur ETP si fourni, sinon calcule une estimation simple à partir de la température et de la pluie récente.
- Capteur `Humidité extérieure` (%) : reflète le capteur fourni s'il existe.
- Capteur `Arrosage conseillé` : auto / personnalise / interdit selon le mode.
- Binaire `Tonte autorisée`.
- Binaire `Arrosage automatique autorisé` (reste à gérer par tes automations externes).
- Bouton `Repasser en mode normal`.
- Bouton `Date action = aujourd'hui` : fixe la date d'action à aujourd'hui (utile pour Sursemis ou autres phases si tu ajustes en retard).

Reconfigurer plus tard
- Tu peux modifier à tout moment les entités (zones, capteurs, débits) via le menu Options de l'intégration dans Home Assistant. Les nouvelles valeurs sont prises en compte sans devoir tout recréer.

Toutes les entités sont rattachées à un appareil « Gazon Intelligent » pour permettre le renommage persistant.

## Versions / Releases
- Voir `CHANGELOG.md` pour le détail des versions (dernière : 0.3.0).
- La version du manifeste est alignée ; pousser main met à jour la release HACS.

## Services

- `gazon_intelligent.set_mode` (`mode` parmi la liste ci-dessus).
- `gazon_intelligent.set_date_action` (`date_action` au format `AAAA-MM-JJ`).
- `gazon_intelligent.reset_mode` (revient en Normal).
- `gazon_intelligent.start_manual_irrigation` (`objectif_mm` float, 0‑30).
- `gazon_intelligent.start_auto_irrigation` (objectif optionnel, utilise l'objectif calculé si omis). Lance chaque zone en séquence en convertissant l'objectif mm en durée selon le débit renseigné (mm/h).
- `gazon_intelligent.set_date_action` (`date_action` au format `AAAA-MM-JJ`) pour fixer une date spécifique différente d'aujourd'hui.

Objectif en mode Normal
- Pensé pour 3 arrosages par semaine : 8.3 mm par passage (~25 mm/sem).
- Si tu arroses 2×/sem : passe `objectif_mm: 12.5` dans ton automation `start_auto_irrigation`.

## Événement

`gazon_intelligent_manual_irrigation_requested` émis lors de `start_manual_irrigation` avec `objectif_mm`, `mode`, `date_action`.

### Exemple d'automatisation pour déclencher une scène d'arrosage

```yaml
alias: Arrosage manuel gazon
mode: single
trigger:
  - platform: event
    event_type: gazon_intelligent_manual_irrigation_requested
action:
  - service: gazon_intelligent.start_auto_irrigation
    data: {}

# Variante : imposer 2 mm d'eau
#  - service: gazon_intelligent.start_auto_irrigation
#    data:
#      objectif_mm: 2
```

### Exemple : créer un cumul pluie 24h simple

Si tu n'as qu'un capteur de pluie horaire ou instantanée (ex. `sensor.pluie_horaire`), crée un cumul 24h glissant avec `statistics` :

```yaml
template:
  - sensor:
      - name: "Pluie 24h"
        unit_of_measurement: "mm"
        state: "{{ states('sensor.pluie_24h_stats') }}"
        availability: "{{ states('sensor.pluie_24h_stats') not in ['unknown','unavailable','none'] }}"

sensor:
  - platform: statistics
    name: "Pluie 24h stats"
    entity_id: sensor.pluie_horaire
    sampling_size: 200
    max_age:
      hours: 24
    state_characteristic: sum
```

Puis utilise `sensor.pluie_24h` comme `capteur_pluie_24h` dans l'intégration.
