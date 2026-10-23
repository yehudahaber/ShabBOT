"""Persistence for ShabBOT: config (routines, rules, modes, ...) and the activity log."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVITY_MAX,
    DEFAULT_DEVICE,
    DEFAULT_SETTINGS,
    STARTER_ROUTINES,
    STARTER_RULES,
    STORAGE_KEY_ACTIVITY,
    STORAGE_KEY_CONFIG,
    STORAGE_VERSION,
)
from .voice.announcements import coerce_templates
from .voice.briefing import coerce_briefing_template
from .voice.gate import migrate_voice_settings


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def starter_config(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    routines = {
        rid: {"id": rid, "name": name, "part": part, "color": color, "description": "", "actions": []}
        for rid, name, part, color in STARTER_ROUTINES
    }
    rules = [
        {"id": new_id(), "name": name, "part": part, "match": match, "routine_id": rid, "enabled": True}
        for name, part, match, rid in STARTER_RULES
    ]
    return {
        "settings": {**DEFAULT_SETTINGS, **(settings or {})},
        "routines": routines,
        "rules": rules,
        "modes": [],
        "assignments": {},
        "devices": {},
    }


def device_config(config: dict[str, Any], entity_id: str) -> dict[str, Any]:
    return {**copy.deepcopy(DEFAULT_DEVICE), **(config.get("devices", {}).get(entity_id) or {})}


class ShabbotStore:
    """Wraps two HA Stores: the config document and the activity ring buffer."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._config_store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY_CONFIG)
        self._activity_store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY_ACTIVITY)
        self.config: dict[str, Any] = {}
        self.activity: list[dict[str, Any]] = []

    async def async_load(self, initial_settings: dict[str, Any]) -> None:
        data = await self._config_store.async_load()
        if data is None:
            self.config = starter_config(initial_settings)
            await self._config_store.async_save(self.config)
        else:
            self.config = data
            self.config.setdefault("settings", {})
            raw_settings = dict(self.config["settings"])
            self.config["settings"] = {**DEFAULT_SETTINGS, **raw_settings}
            self.config["settings"].update(migrate_voice_settings(raw_settings))
            stored_templates = self.config["settings"].get("announce_templates")
            if isinstance(stored_templates, dict):
                self.config["settings"]["announce_templates"] = coerce_templates(stored_templates)
            try:
                self.config["settings"]["briefing_template"] = coerce_briefing_template(
                    self.config["settings"].get("briefing_template"),
                )
            except ValueError:
                self.config["settings"]["briefing_template"] = DEFAULT_SETTINGS["briefing_template"]
            for key, empty in (("routines", {}), ("rules", []), ("modes", []), ("assignments", {}), ("devices", {})):
                self.config.setdefault(key, empty)
        activity = await self._activity_store.async_load()
        self.activity = (activity or {}).get("entries", [])

    def save_config(self) -> None:
        self._config_store.async_delay_save(lambda: self.config, 1.0)

    async def async_flush(self) -> None:
        await self._config_store.async_save(self.config)
        await self._activity_store.async_save({"entries": self.activity})

    def add_activity(self, kind: str, message: str, entity_id: str | None = None, **extra: Any) -> dict[str, Any]:
        entry = {"ts": dt_util.utcnow().isoformat(), "kind": kind, "entity_id": entity_id, "message": message, **extra}
        self.activity.append(entry)
        if len(self.activity) > ACTIVITY_MAX:
            del self.activity[: len(self.activity) - ACTIVITY_MAX]
        self._activity_store.async_delay_save(lambda: {"entries": self.activity}, 10.0)
        return entry

    def prune_assignments(self, before: datetime) -> None:
        """Drop per-occurrence choices for dates long past (keeps storage small)."""
        cutoff = before.date().isoformat()
        stale = [k for k in self.config["assignments"] if k.split("/")[0] < cutoff]
        for key in stale:
            del self.config["assignments"][key]
        if stale:
            self.save_config()
