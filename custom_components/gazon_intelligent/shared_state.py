from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

try:
    from homeassistant.helpers.storage import Store
except Exception:  # pragma: no cover - fallback for unit tests / stripped envs
    class Store:  # type: ignore[too-many-ancestors]
        def __init__(self, hass, version: int, key: str) -> None:
            self.hass = hass
            self.version = version
            self.key = key

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

from .const import DOMAIN, SHARED_WEATHER_CONFIG_KEYS

_SHARED_STATE_KEY = f"{DOMAIN}_shared_state"
_STORE_VERSION = 1


def _normalize_shared_value(value: Any) -> Any:
    if value in (None, "", [], {}):
        return None
    return value


def _defined_config_value(value: Any) -> bool:
    return _normalize_shared_value(value) is not None


def resolve_effective_config(
    entry: Any,
    key: str,
    *,
    shared_state: Any = None,
    default: Any = None,
) -> dict[str, Any]:
    """Résout une option selon la priorité locale > partagée > data > défaut."""
    options = getattr(entry, "options", {})
    if not isinstance(options, Mapping):
        options = {}
    data = getattr(entry, "data", {})
    if not isinstance(data, Mapping):
        data = {}

    local_raw = options.get(key) if key in options else None
    local_value = _normalize_shared_value(local_raw)
    shared_value = None
    if key in SHARED_WEATHER_CONFIG_KEYS and shared_state is not None:
        get_conf = getattr(shared_state, "get_conf", None)
        if callable(get_conf):
            shared_value = _normalize_shared_value(get_conf(key))
        else:
            shared_config = getattr(shared_state, "shared_config", None)
            if isinstance(shared_config, dict):
                shared_value = _normalize_shared_value(shared_config.get(key))
    entry_data_value = _normalize_shared_value(data.get(key)) if key in data else None

    if local_value is not None:
        return {
            "local_value": copy.deepcopy(local_value),
            "shared_value": copy.deepcopy(shared_value),
            "entry_data_value": copy.deepcopy(entry_data_value),
            "default_value": copy.deepcopy(default),
            "effective_value": copy.deepcopy(local_value),
            "source": "options",
        }

    if shared_value is not None:
        return {
            "local_value": None,
            "shared_value": copy.deepcopy(shared_value),
            "entry_data_value": copy.deepcopy(entry_data_value),
            "default_value": copy.deepcopy(default),
            "effective_value": copy.deepcopy(shared_value),
            "source": "shared_state",
        }

    if entry_data_value is not None:
        return {
            "local_value": None,
            "shared_value": None,
            "entry_data_value": copy.deepcopy(entry_data_value),
            "default_value": copy.deepcopy(default),
            "effective_value": copy.deepcopy(entry_data_value),
            "source": "entry_data",
        }

    return {
        "local_value": None,
        "shared_value": None,
        "entry_data_value": None,
        "default_value": copy.deepcopy(default),
        "effective_value": copy.deepcopy(default),
        "source": "default",
    }


def _extract_shared_config(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    shared: dict[str, Any] = {}
    for key in SHARED_WEATHER_CONFIG_KEYS:
        value = _normalize_shared_value(data.get(key))
        if value is not None:
            shared[key] = copy.deepcopy(value)
    return shared


class GazonIntelligentSharedState:
    """Stocke les réglages maison partagés entre plusieurs pelouses."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self._store = Store(hass, _STORE_VERSION, f"{DOMAIN}_shared.json")
        self._loaded = False
        self.shared_config: dict[str, Any] = {}
        self.products: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        if self._loaded:
            return
        data = await self._store.async_load() or {}
        if isinstance(data, dict):
            shared_config = data.get("shared_config")
            if isinstance(shared_config, dict):
                self.shared_config = _extract_shared_config(shared_config)
            products = data.get("products")
            if isinstance(products, dict):
                normalized_products: dict[str, dict[str, Any]] = {}
                for product_id, product in products.items():
                    if isinstance(product_id, str) and isinstance(product, dict):
                        normalized_products[product_id] = copy.deepcopy(product)
                self.products = normalized_products
        self._loaded = True

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "shared_config": copy.deepcopy(self.shared_config),
                "products": copy.deepcopy(self.products),
            }
        )

    def get_conf(self, key: str) -> Any:
        if key not in SHARED_WEATHER_CONFIG_KEYS:
            return None
        return self.shared_config.get(key)

    async def async_bootstrap_from_entry(self, entry) -> None:
        """Initialise les réglages partagés à partir d'une entrée existante."""
        if not self.shared_config:
            shared_config = _extract_shared_config({**entry.data, **entry.options})
            if shared_config:
                self.shared_config.update(shared_config)
        if not self.products:
            products = getattr(entry, "products", None)
            if isinstance(products, dict) and products:
                normalized_products: dict[str, dict[str, Any]] = {}
                for product_id, product in products.items():
                    if isinstance(product_id, str) and isinstance(product, dict):
                        normalized_products[product_id] = copy.deepcopy(product)
                self.products.update(normalized_products)
        await self.async_save()

    async def async_update_shared_config(self, updates: dict[str, Any]) -> None:
        changed = False
        for key in SHARED_WEATHER_CONFIG_KEYS:
            if key not in updates:
                continue
            value = _normalize_shared_value(updates.get(key))
            if value is None:
                if key in self.shared_config:
                    self.shared_config.pop(key, None)
                    changed = True
                continue
            if self.shared_config.get(key) != value:
                self.shared_config[key] = copy.deepcopy(value)
                changed = True
        if changed:
            await self.async_save()

    async def async_sync_products(self, products: dict[str, dict[str, Any]]) -> None:
        self.products.clear()
        for product_id, product in products.items():
            if isinstance(product_id, str) and isinstance(product, dict):
                self.products[product_id] = copy.deepcopy(product)
        await self.async_save()


def get_shared_state(hass, *, create: bool = True) -> GazonIntelligentSharedState | None:
    state = hass.data.get(_SHARED_STATE_KEY)
    if state is None and create:
        state = GazonIntelligentSharedState(hass)
        hass.data[_SHARED_STATE_KEY] = state
    if isinstance(state, GazonIntelligentSharedState):
        return state
    return None
