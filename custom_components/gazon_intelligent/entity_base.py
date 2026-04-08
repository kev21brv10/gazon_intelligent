from __future__ import annotations

from datetime import date, datetime

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .decision_models import (
    DecisionResult,
    POSSIBLE_FENETRE_OPTIMALE_VALUES,
    POSSIBLE_NIVEAU_ACTION_VALUES,
    POSSIBLE_PHASE_DOMINANTE_VALUES,
    POSSIBLE_SOUS_PHASE_VALUES,
    POSSIBLE_TONTE_STATUT_VALUES,
    POSSIBLE_TYPE_ARROSAGE_VALUES,
)
from .entity_ids import public_entity_id


_EXACT_VALUE_PRECISIONS: dict[str, int] = {
    "temperature": 1,
    "forecast_temperature_today": 1,
    "temperature_reference_hydrique": 1,
    "etp": 1,
    "et0_mm": 1,
    "etc_mm": 1,
    "kc_gazon": 2,
    "mad_ratio": 2,
    "depletion_ratio": 3,
    "depletion_ratio_raw": 3,
    "reserve_fill_ratio": 3,
    "reserve_available_ratio": 3,
    "sous_phase_progression": 1,
}

_SUFFIX_VALUE_PRECISIONS: tuple[tuple[str, int], ...] = (
    ("_mm", 1),
    ("_cm", 1),
    ("_temperature", 1),
    ("_ratio", 3),
)


def _round_precision_for_key(key: str | None) -> int | None:
    if not key:
        return None
    if key in _EXACT_VALUE_PRECISIONS:
        return _EXACT_VALUE_PRECISIONS[key]
    for suffix, precision in _SUFFIX_VALUE_PRECISIONS:
        if key.endswith(suffix):
            return precision
    return 3


def _normalize_exposed_value(value, key: str | None = None):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, dict):
        return {child_key: _normalize_exposed_value(child_value, child_key) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [_normalize_exposed_value(item, key) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_exposed_value(item, key) for item in value)
    if isinstance(value, (date, datetime, str)):
        return value
    if isinstance(value, int):
        precision = _round_precision_for_key(key)
        if precision is None:
            return value
        return round(float(value), precision)
    if isinstance(value, float):
        precision = _round_precision_for_key(key)
        if precision is None:
            return value
        return round(value, precision)
    return value


class GazonEntityBase(CoordinatorEntity):
    """Base commune pour les entités de Gazon Intelligent."""

    _device_model = "Gestion gazon"

    def _set_entity_identity(self, platform: str, suffix: str) -> None:
        entry_id = self.coordinator.entry.entry_id
        resolved_entity_id = public_entity_id(platform, suffix)
        _domain, object_id = resolved_entity_id.split(".", 1)
        self._attr_unique_id = f"{entry_id}_{suffix}"
        self._attr_entity_id = resolved_entity_id
        self._attr_suggested_object_id = object_id
        self.entity_id = resolved_entity_id

    @property
    def device_info(self) -> DeviceInfo:
        entry_id = self.coordinator.entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Gazon Intelligent",
            manufacturer="Custom",
            model=self._device_model,
        )

    @property
    def decision_result(self) -> DecisionResult | None:
        """Retourne le résultat métier courant si disponible."""
        result = getattr(self.coordinator, "result", None)
        if isinstance(result, DecisionResult):
            return result
        legacy_result = getattr(self.coordinator, "last_result", None)
        if isinstance(legacy_result, DecisionResult):
            return legacy_result
        return None

    def _decision_value(self, key: str, default=None):
        result = self.decision_result
        if result is not None:
            value = getattr(result, key, None)
            if value is not None:
                return _normalize_exposed_value(value, key)
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict) and key in extra and extra[key] is not None:
                return _normalize_exposed_value(extra[key], key)

        attrs = getattr(self.coordinator, "data", None)
        if isinstance(attrs, dict):
            return _normalize_exposed_value(attrs.get(key, default), key)
        return default

    def _decision_attrs(self, *keys: str) -> dict[str, object] | None:
        result = self.decision_result
        if result is not None:
            attrs: dict[str, object] = {}
            for key in keys:
                value = getattr(result, key, None)
                if value is None:
                    extra = getattr(result, "extra", None)
                    if isinstance(extra, dict):
                        value = extra.get(key)
                if value is not None:
                    attrs[key] = _normalize_exposed_value(value, key)
            if attrs:
                return attrs
        return self._attrs_from_data(*keys)

    def _possible_values_attr(self, key: str) -> dict[str, object] | None:
        result = self.decision_result
        possible_values = result.possible_values_for(key) if result is not None else {
            "phase_dominante": POSSIBLE_PHASE_DOMINANTE_VALUES,
            "sous_phase": POSSIBLE_SOUS_PHASE_VALUES,
            "niveau_action": POSSIBLE_NIVEAU_ACTION_VALUES,
            "tonte_statut": POSSIBLE_TONTE_STATUT_VALUES,
            "fenetre_optimale": POSSIBLE_FENETRE_OPTIMALE_VALUES,
            "type_arrosage": POSSIBLE_TYPE_ARROSAGE_VALUES,
        }.get(key)
        if not possible_values:
            return None
        return {"possible_values": list(possible_values)}

    def _attrs_from_data(self, *keys: str) -> dict[str, object] | None:
        attrs = {key: _normalize_exposed_value(self.coordinator.data.get(key), key) for key in keys}
        clean = {k: v for k, v in attrs.items() if v is not None}
        return clean or None

    def _attrs_from_result(self, *keys: str) -> dict[str, object] | None:
        return self._decision_attrs(*keys)
