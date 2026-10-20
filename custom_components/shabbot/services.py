"""ShabBOT services (usable from dashboards, scripts and Node-RED)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN
from .manager import ShabbotManager
from .voice.briefing import async_daily_briefing


def _mgr(hass: HomeAssistant) -> ShabbotManager:
    if DOMAIN not in hass.data:
        raise ServiceValidationError("ShabBOT is not set up")
    return hass.data[DOMAIN]


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def start_override(call: ServiceCall) -> None:
        _mgr(hass).start_override(call.data["entity_id"], call.data.get("minutes"), reason="service call")

    async def end_override(call: ServiceCall) -> None:
        _mgr(hass).end_override(call.data["entity_id"], "service call")

    async def set_slot_routine(call: ServiceCall) -> None:
        m = _mgr(hass)
        key, rid = call.data["slot"], call.data.get("routine_id")
        if rid and rid not in m.config["routines"]:
            matches = [r["id"] for r in m.config["routines"].values() if r["name"] == rid]
            if not matches:
                raise ServiceValidationError(f"Unknown routine {rid!r}")
            rid = matches[0]
        assignment = {k: v for k, v in m.config["assignments"].get(key, {}).items() if k != "skip"}
        if rid:
            assignment["routine_id"] = rid
        else:
            assignment.pop("routine_id", None)
        if assignment:
            m.config["assignments"][key] = assignment
        else:
            m.config["assignments"].pop(key, None)
        m.config_changed()

    async def skip_slot(call: ServiceCall) -> None:
        m = _mgr(hass)
        key = call.data["slot"]
        assignment = dict(m.config["assignments"].get(key, {}))
        if call.data.get("skip", True):
            assignment["skip"] = True
        else:
            assignment.pop("skip", None)
        if assignment:
            m.config["assignments"][key] = assignment
        else:
            m.config["assignments"].pop(key, None)
        m.config_changed()

    async def reconcile(call: ServiceCall) -> None:
        await _mgr(hass).async_reconcile("service call")

    async def announce(call: ServiceCall) -> None:
        try:
            await _mgr(hass).announcer.async_speak_test(call.data.get("message"))
        except ServiceValidationError as err:
            raise HomeAssistantError(str(err)) from err

    slot = vol.Match(r"^\d{4}-\d{2}-\d{2}/(night|day|block)$")
    hass.services.async_register(DOMAIN, "start_override", start_override, vol.Schema({
        vol.Required("entity_id"): cv.entity_ids,
        vol.Optional("minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=1440)),
    }))
    hass.services.async_register(DOMAIN, "end_override", end_override,
                                 vol.Schema({vol.Required("entity_id"): cv.entity_ids}))
    hass.services.async_register(DOMAIN, "set_slot_routine", set_slot_routine, vol.Schema({
        vol.Required("slot"): slot, vol.Optional("routine_id"): vol.Any(None, cv.string)}))
    hass.services.async_register(DOMAIN, "skip_slot", skip_slot, vol.Schema({
        vol.Required("slot"): slot, vol.Optional("skip", default=True): cv.boolean}))
    hass.services.async_register(DOMAIN, "reconcile", reconcile, vol.Schema({}))
    hass.services.async_register(DOMAIN, "announce", announce, vol.Schema({
        vol.Optional("message"): cv.string,
    }))

    async def get_day_info(call: ServiceCall) -> ServiceResponse:
        try:
            info = _mgr(hass).day_info(call.data.get("date"))
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(str(err)) from err
        return info.as_dict()

    hass.services.async_register(
        DOMAIN, "get_day_info", get_day_info,
        vol.Schema({vol.Optional("date"): cv.date}),
        supports_response=SupportsResponse.ONLY,
    )

    async def get_daily_briefing(call: ServiceCall) -> ServiceResponse:
        try:
            return await async_daily_briefing(_mgr(hass).hass, _mgr(hass), call.data.get("date"))
        except ServiceValidationError:
            raise
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(
        DOMAIN, "get_daily_briefing", get_daily_briefing,
        vol.Schema({vol.Optional("date"): cv.date}),
        supports_response=SupportsResponse.ONLY,
    )
