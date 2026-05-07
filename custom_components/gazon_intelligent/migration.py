from __future__ import annotations

"""Migration et nettoyage des entrées de configuration."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .entity_ids import resolve_entry_instance_slug
from .entity_migration import CURRENT_CONFIG_ENTRY_VERSION, async_align_entity_ids, async_cleanup_obsolete_entities


async def async_migrate_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Migre les anciennes versions et nettoie les entités obsolètes."""
    if entry.version > CURRENT_CONFIG_ENTRY_VERSION:
        return False

    await async_cleanup_obsolete_entities(hass, entry.entry_id)
    await async_align_entity_ids(hass, entry.entry_id, instance_slug=resolve_entry_instance_slug(entry))

    if entry.version < CURRENT_CONFIG_ENTRY_VERSION:
        hass.config_entries.async_update_entry(entry, version=CURRENT_CONFIG_ENTRY_VERSION)

    return True
