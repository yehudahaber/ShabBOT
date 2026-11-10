"""Find entities that drive the same physical device.

A schedule that turns one of them on while another keeps it off makes ShabBOT's protection
undo each change in turn, so the light flickers. Reads Home Assistant's in-memory registries only.
"""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .core.planner import Link

# Domains where two entities on one device usually mean one load shown twice (not two loads).
CONTROLLABLE = {"light", "switch", "fan", "cover", "climate", "media_player", "input_boolean"}


def _name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return state.name if state else entity_id


def linked_pairs(hass: HomeAssistant, entity_ids: Iterable[str]) -> list[Link]:
    """Pairs among `entity_ids` that control the same device.

    - wrapper: a "Change device type of a switch" (switch_as_x) entity and the switch it wraps
    - group: a light/switch group and one of its members
    - device: two controllable entities on the same device with the same name. A dual relay has two real
      loads with different names, so it isn't reported.
    """
    wanted = set(entity_ids)
    reg = er.async_get(hass)
    found: dict[frozenset[str], str] = {}

    def add(a: str | None, b: str | None, kind: str) -> None:
        if a and b and a != b and a in wanted and b in wanted:
            found.setdefault(frozenset((a, b)), kind)

    for entry in hass.config_entries.async_entries("switch_as_x"):
        source = entry.options.get(CONF_ENTITY_ID)
        source_id = er.async_resolve_entity_id(reg, source) if source else None
        for wrapper in er.async_entries_for_config_entry(reg, entry.entry_id):
            add(wrapper.entity_id, source_id, "wrapper")

    for entity_id in wanted:
        state = hass.states.get(entity_id)
        members = state.attributes.get("entity_id") if state else None
        if isinstance(members, (list, tuple)):
            for member in members:
                add(entity_id, member, "group")

    by_device: dict[str, list[str]] = {}
    for entity_id in wanted:
        entry = reg.async_get(entity_id)
        if entry and entry.device_id and entity_id.split(".", 1)[0] in CONTROLLABLE:
            by_device.setdefault(entry.device_id, []).append(entity_id)
    for members in by_device.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if _name(hass, a).casefold() == _name(hass, b).casefold():
                    add(a, b, "device")

    return [Link(*sorted(pair), kind) for pair, kind in found.items()]
