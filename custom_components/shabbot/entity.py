"""Base entity for ShabBOT."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME, SIGNAL_UPDATE, VERSION
from .manager import ShabbotManager


class ShabbotEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: ShabbotManager, key: str) -> None:
        self.manager = manager
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_translation_key = key
        self._attr_suggested_object_id = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, DOMAIN)},
            name=NAME,
            manufacturer=NAME,
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
