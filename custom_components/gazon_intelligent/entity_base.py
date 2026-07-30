from __future__ import annotations

from datetime import date, datetime
from typing import Any

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
from .entity_ids import public_entity_id, resolve_entry_instance_slug

_MISSING = object()

_LEGACY_POSSIBLE_VALUES_BY_KEY: dict[str, tuple[str, ...]] = {
    "phase_dominante": POSSIBLE_PHASE_DOMINANTE_VALUES,
    "sous_phase": POSSIBLE_SOUS_PHASE_VALUES,
    "niveau_action": POSSIBLE_NIVEAU_ACTION_VALUES,
    "tonte_statut": POSSIBLE_TONTE_STATUT_VALUES,
    "fenetre_optimale": POSSIBLE_FENETRE_OPTIMALE_VALUES,
    "type_arrosage": POSSIBLE_TYPE_ARROSAGE_VALUES,
}


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


def _coordinator_snapshot(coordinator) -> dict[str, Any]:
    attrs = getattr(coordinator, "data", None)
    return attrs if isinstance(attrs, dict) else {}


def _result_extra(result: DecisionResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    extra = getattr(result, "extra", None)
    return extra if isinstance(extra, dict) else {}


def _result_value(result: DecisionResult | None, key: str):
    if result is None:
        return _MISSING
    value = getattr(result, key, _MISSING)
    if value not in (_MISSING, None):
        return value
    extra = _result_extra(result)
    if key in extra and extra[key] is not None:
        return extra[key]
    return _MISSING


def _snapshot_value(snapshot: dict[str, Any], key: str, default=_MISSING):
    if key in snapshot:
        return snapshot[key]
    return default


def _normalized_public_value(value, key: str | None = None, default=None):
    if value is _MISSING:
        return default
    return _normalize_exposed_value(value, key)


def _legacy_possible_values_for(key: str) -> tuple[str, ...] | None:
    return _LEGACY_POSSIBLE_VALUES_BY_KEY.get(key)


class GazonEntityBase(CoordinatorEntity):
    """Base commune pour les entités de Gazon Intelligent."""

    _device_model = "Gestion gazon"

    @property
    def instance_slug(self) -> str | None:
        entry = getattr(self.coordinator, "entry", None)
        if entry is None:
            return None
        return resolve_entry_instance_slug(entry)

    def _set_entity_identity(self, platform: str, suffix: str) -> None:
        entry_id = self.coordinator.entry.entry_id
        resolved_entity_id = public_entity_id(platform, suffix, instance_slug=self.instance_slug)
        _domain, object_id = resolved_entity_id.split(".", 1)
        self._attr_unique_id = f"{entry_id}_{suffix}"
        self._attr_suggested_object_id = object_id
        self.entity_id = resolved_entity_id

    @property
    def device_info(self) -> DeviceInfo:
        entry_id = self.coordinator.entry.entry_id
        entry_title = getattr(self.coordinator.entry, "title", None)
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=entry_title or "Gazon Intelligent",
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

    def _snapshot_data(self) -> dict[str, Any]:
        return _coordinator_snapshot(self.coordinator)

    def _public_mowing_facade(self) -> dict[str, Any]:
        snapshot = self._snapshot_data()
        facade = snapshot.get("_public_mowing_facade")
        if isinstance(facade, dict) and facade:
            return facade
        return {}

    def _public_mowing_value(self, key: str, default=None):
        facade = self._public_mowing_facade()
        if key in facade and facade.get(key) is not None:
            return _normalized_public_value(facade.get(key), key, default)
        return default

    def _decision_value(self, key: str, default=None):
        result = self.decision_result
        value = _result_value(result, key)
        if value is not _MISSING:
            return _normalized_public_value(value, key)

        snapshot = self._snapshot_data()
        value = _snapshot_value(snapshot, key, default)
        if value is _MISSING:
            return default
        return _normalized_public_value(value, key)

    def _decision_attrs(self, *keys: str) -> dict[str, Any] | None:
        result = self.decision_result
        if result is not None:
            attrs: dict[str, Any] = {}
            for key in keys:
                value = _result_value(result, key)
                if value is _MISSING:
                    continue
                attrs[key] = _normalized_public_value(value, key)
            if attrs:
                return attrs
        return self._attrs_from_data(*keys)

    def _possible_values_attr(self, key: str) -> dict[str, Any] | None:
        result = self.decision_result
        possible_values = result.possible_values_for(key) if result is not None else _legacy_possible_values_for(key)
        if not possible_values:
            return None
        return {"possible_values": list(possible_values)}

    def _attrs_from_data(self, *keys: str) -> dict[str, Any] | None:
        snapshot = self._snapshot_data()
        attrs = {
            key: _normalized_public_value(_snapshot_value(snapshot, key), key)
            for key in keys
        }
        clean = {k: v for k, v in attrs.items() if v is not None}
        return clean or None

    def _attrs_from_result(self, *keys: str) -> dict[str, Any] | None:
        return self._decision_attrs(*keys)
