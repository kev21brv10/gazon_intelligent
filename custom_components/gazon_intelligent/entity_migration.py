from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TYPE_CHECKING

from .entity_ids import ACTIVE_ENTITY_SUFFIXES

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.core import HomeAssistant

CURRENT_CONFIG_ENTRY_VERSION = 2


def _unique_id_suffix(unique_id: Any, entry_id: str) -> str | None:
    if not isinstance(unique_id, str):
        return None
    prefix = f"{entry_id}_"
    if not unique_id.startswith(prefix):
        return None
    suffix = unique_id[len(prefix) :].strip()
    return suffix or None


def is_obsolete_entity_unique_id(unique_id: Any, entry_id: str) -> bool:
    suffix = _unique_id_suffix(unique_id, entry_id)
    if suffix is None:
        return False
    return suffix not in ACTIVE_ENTITY_SUFFIXES


def iter_obsolete_entity_ids(
    entities: Iterable[Any],
    entry_id: str,
) -> list[str]:
    obsolete_entity_ids: list[str] = []
    for entity in entities:
        config_entry_id = getattr(entity, "config_entry_id", None)
        if config_entry_id != entry_id:
            continue
        if not is_obsolete_entity_unique_id(getattr(entity, "unique_id", None), entry_id):
            continue
        entity_id = getattr(entity, "entity_id", None)
        if isinstance(entity_id, str) and entity_id:
            obsolete_entity_ids.append(entity_id)
    return obsolete_entity_ids


async def async_cleanup_obsolete_entities(
    hass: "HomeAssistant | None",
    entry_id: str,
    entity_registry: Any | None = None,
) -> list[str]:
    if entity_registry is None:
        from homeassistant.helpers import entity_registry as er  # local import for HA runtime

        registry = er.async_get(hass)
    else:
        registry = entity_registry
    obsolete_entity_ids = iter_obsolete_entity_ids(registry.entities.values(), entry_id)
    for entity_id in obsolete_entity_ids:
        registry.async_remove(entity_id)
    return obsolete_entity_ids
