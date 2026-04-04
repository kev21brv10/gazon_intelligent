from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .decision_models import DecisionResult
from .entity_ids import public_entity_id


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
                return value
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict) and key in extra and extra[key] is not None:
                return extra[key]

        attrs = getattr(self.coordinator, "data", None)
        if isinstance(attrs, dict):
            return attrs.get(key, default)
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
                    attrs[key] = value
            if attrs:
                return attrs
        return self._attrs_from_data(*keys)

    def _possible_values_attr(self, key: str) -> dict[str, object] | None:
        result = self.decision_result
        if result is None:
            return None
        possible_values = result.possible_values_for(key)
        if not possible_values:
            return None
        return {"possible_values": list(possible_values)}

    def _attrs_from_data(self, *keys: str) -> dict[str, object] | None:
        attrs = {key: self.coordinator.data.get(key) for key in keys}
        clean = {k: v for k, v in attrs.items() if v is not None}
        return clean or None

    def _attrs_from_result(self, *keys: str) -> dict[str, object] | None:
        return self._decision_attrs(*keys)
