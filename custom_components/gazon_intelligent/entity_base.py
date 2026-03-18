from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class GazonEntityBase(CoordinatorEntity):
    """Base commune pour les entités de Gazon Intelligent."""

    _device_model = "Gestion gazon"

    @property
    def device_info(self) -> DeviceInfo:
        entry_id = self.coordinator.entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Gazon Intelligent",
            manufacturer="Custom",
            model=self._device_model,
        )

    def _attrs_from_data(self, *keys: str) -> dict[str, object] | None:
        attrs = {key: self.coordinator.data.get(key) for key in keys}
        clean = {k: v for k, v in attrs.items() if v is not None}
        return clean or None

