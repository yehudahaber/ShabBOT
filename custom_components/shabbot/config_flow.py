"""Config flow: one ShabBOT per Home Assistant, location taken from HA."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import DEFAULT_SETTINGS, DOMAIN, NAME
from .core.dayinfo import location_is_israel

MINHAG_KEYS = (
    "candle_lighting_min", "havdalah_mode", "havdalah_degrees", "havdalah_minutes",
    "yom_tov_end_minutes", "israel",
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("candle_lighting_min", default=defaults["candle_lighting_min"]): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=60, step=1, unit_of_measurement="min",
                                          mode=selector.NumberSelectorMode.BOX)),
        vol.Required("havdalah_mode", default=defaults["havdalah_mode"]): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["degrees", "minutes"], translation_key="havdalah_mode")),
        vol.Required("havdalah_degrees", default=defaults["havdalah_degrees"]): selector.NumberSelector(
            selector.NumberSelectorConfig(min=5, max=20, step=0.01, unit_of_measurement="°",
                                          mode=selector.NumberSelectorMode.BOX)),
        vol.Required("havdalah_minutes", default=defaults["havdalah_minutes"]): selector.NumberSelector(
            selector.NumberSelectorConfig(min=20, max=90, step=1, unit_of_measurement="min",
                                          mode=selector.NumberSelectorMode.BOX)),
        vol.Required("yom_tov_end_minutes", default=defaults.get("yom_tov_end_minutes", 42)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=20, max=90, step=1, unit_of_measurement="min",
                                          mode=selector.NumberSelectorMode.BOX)),
        vol.Required("israel", default=defaults["israel"]): selector.BooleanSelector(),
    })


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(user_input)
    for key in ("candle_lighting_min", "havdalah_minutes", "yom_tov_end_minutes"):
        out[key] = int(out[key])
    out["havdalah_degrees"] = float(out["havdalah_degrees"])
    return out


class ShabbotConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=NAME, data=_clean(user_input))
        # The checkbox starts from Home Assistant's location. Saving the form stores
        # that choice, and the Settings page can change it later. The stored box is
        # what the parasha and Yom Tov schedule use.
        defaults = {**DEFAULT_SETTINGS, "israel": location_is_israel(
            self.hass.config.latitude, self.hass.config.longitude, self.hass.config.country)}
        if defaults["israel"]:
            defaults["candle_lighting_min"] = 40 if "jerusalem" in (self.hass.config.location_name or "").lower() else 20
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(defaults),
            description_placeholders={
                "latitude": f"{self.hass.config.latitude:.4f}",
                "longitude": f"{self.hass.config.longitude:.4f}",
                "time_zone": self.hass.config.time_zone,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ShabbotOptionsFlow()


class ShabbotOptionsFlow(OptionsFlow):
    """Edits the same minhag settings the panel's Settings page edits (stored in ShabBOT's store)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        manager = getattr(self.config_entry, "runtime_data", None)
        if user_input is not None:
            if manager is not None:
                manager.settings.update(_clean(user_input))
                manager.config_changed()
            return self.async_create_entry(data={})
        current = manager.settings if manager is not None else {**DEFAULT_SETTINGS, **self.config_entry.data}
        return self.async_show_form(step_id="init", data_schema=_schema({k: current[k] for k in MINHAG_KEYS}))
