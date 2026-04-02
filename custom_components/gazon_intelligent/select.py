from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import DEFAULT_MODE, DOMAIN, MODES_GAZON
from .entity_base import GazonEntityBase
from .memory import format_application_months_label


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonModeSelect(coordinator),
            GazonInterventionProductSelect(coordinator),
        ]
    )


def _catalogue_name_key(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _catalogue_product_label(product: dict[str, Any], duplicate_name_counts: dict[str, int]) -> str:
    product_id = str(product.get("id") or "").strip()
    product_name = str(product.get("nom") or product_id or "").strip()
    months_label = str(product.get("application_months_label") or "").strip()
    if not product_name:
        base_label = product_id or "Produit"
    elif duplicate_name_counts.get(_catalogue_name_key(product_name), 0) > 1 and product_id:
        base_label = f"{product_name} — {product_id}"
    else:
        base_label = product_name
    if months_label:
        return f"{base_label} · {months_label}"
    return base_label


class GazonModeSelect(GazonEntityBase, SelectEntity):
    _attr_name = "Mode du gazon"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:grass"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_mode"

    @property
    def options(self):
        return MODES_GAZON

    @property
    def current_option(self):
        return self.coordinator.data.get("mode", DEFAULT_MODE)

    async def async_select_option(self, option: str):
        await self.coordinator.async_set_mode(option)


class GazonInterventionProductSelect(GazonEntityBase, SelectEntity):
    _attr_name = "Produit d'intervention"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_produit_intervention"

    def _catalogue(self) -> list[tuple[str, dict[str, Any], str]]:
        products = getattr(self.coordinator, "products", None)
        if not isinstance(products, dict) or not products:
            return []
        ordered_products: list[dict[str, Any]] = []
        for product_id in sorted(products.keys()):
            product = products.get(product_id)
            if isinstance(product, dict):
                ordered_products.append(product)
        if not ordered_products:
            return []
        name_counts: dict[str, int] = {}
        for product in ordered_products:
            product_name = str(product.get("nom") or product.get("id") or "").strip()
            if not product_name:
                continue
            key = _catalogue_name_key(product_name)
            name_counts[key] = name_counts.get(key, 0) + 1
        catalogue: list[tuple[str, dict[str, Any], str]] = []
        for product in ordered_products:
            product_id = str(product.get("id") or "").strip()
            if not product_id:
                continue
            label = _catalogue_product_label(product, name_counts)
            catalogue.append((product_id, product, label))
        return catalogue

    def _label_by_product_id(self) -> dict[str, str]:
        return {product_id: label for product_id, _product, label in self._catalogue()}

    def _product_id_by_label(self) -> dict[str, str]:
        return {label: product_id for product_id, _product, label in self._catalogue()}

    def _resolved_selected_product_id(self) -> str | None:
        catalogue = self._catalogue()
        if not catalogue:
            return None
        selected_product_id = getattr(self.coordinator, "selected_product_id", None)
        if selected_product_id:
            normalized_selected_product_id = str(selected_product_id).strip()
            if normalized_selected_product_id in self._label_by_product_id():
                return normalized_selected_product_id
        if len(catalogue) == 1:
            return catalogue[0][0]
        return None

    def _product_name_by_id(self) -> dict[str, str]:
        return {
            product_id: str(product.get("nom") or product.get("id") or "").strip()
            for product_id, product, _label in self._catalogue()
        }

    @property
    def options(self):
        return [label for _product_id, _product, label in self._catalogue()]

    @property
    def current_option(self):
        selected_product_id = self._resolved_selected_product_id()
        if not selected_product_id:
            return None
        return self._label_by_product_id().get(selected_product_id)

    @property
    def extra_state_attributes(self):
        catalogue = self._catalogue()
        selected_product_id = self._resolved_selected_product_id()
        label_by_product_id = self._label_by_product_id()
        product_name_by_id = self._product_name_by_id()
        product_by_id = {product_id: product for product_id, product, _label in catalogue}
        selected_product_label = label_by_product_id.get(selected_product_id) if selected_product_id else None
        selected_product_name = product_name_by_id.get(selected_product_id) if selected_product_id else None
        selected_product_months = None
        selected_product_months_label = None
        if selected_product_id:
            selected_product = product_by_id.get(selected_product_id)
            if isinstance(selected_product, dict):
                selected_product_months = selected_product.get("application_months")
                selected_product_months_label = selected_product.get("application_months_label") or format_application_months_label(selected_product_months)
        if catalogue:
            if selected_product_id and selected_product_label:
                summary = f"Produit sélectionné : {selected_product_label}"
            elif getattr(self.coordinator, "selected_product_id", None):
                summary = "Produit sélectionné introuvable"
            else:
                summary = "Aucun produit sélectionné"
        else:
            summary = "Aucun produit enregistré"
        return {
            "selected_product_id": str(selected_product_id).strip() if selected_product_id else None,
            "selected_product_name": selected_product_name,
            "selected_product_months": selected_product_months,
            "selected_product_months_label": selected_product_months_label,
            "summary": summary,
            "products_count": len(catalogue),
        }

    async def async_select_option(self, option: str):
        option = str(option).strip()
        product_id = self._product_id_by_label().get(option)
        if not product_id:
            raise HomeAssistantError(f"Produit d'intervention introuvable dans le catalogue: {option}")
        await self.coordinator.async_set_selected_product(product_id)
