from __future__ import annotations

"""Migration et nettoyage des entrées de configuration."""

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .entity_migration import CURRENT_CONFIG_ENTRY_VERSION, async_cleanup_obsolete_entities


async def async_migrate_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Migre les anciennes versions et nettoie les entités obsolètes."""
    if entry.version > CURRENT_CONFIG_ENTRY_VERSION:
        return False

    await async_cleanup_obsolete_entities(hass, entry.entry_id)

    if entry.version < CURRENT_CONFIG_ENTRY_VERSION:
        hass.config_entries.async_update_entry(entry, version=CURRENT_CONFIG_ENTRY_VERSION)

    return True
