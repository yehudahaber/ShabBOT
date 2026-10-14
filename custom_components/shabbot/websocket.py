"""Websocket API used by the ShabBOT panel. Reads are open to users; writes need admin."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.const import MATCH_ALL
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import voluptuous as vol

from .const import (
    DEFAULT_DEVICE,
    DEFAULT_SETTINGS,
    DOMAIN,
    EXPORT_SKIP_SETTINGS,
    PLAN_HORIZON_DAYS,
    SIGNAL_ACTIVITY,
    SIGNAL_UPDATE,
    VERSION,
)
from .core import gestures, jcal, planner, timeexpr
from .core.announcements import (
    coerce_groups,
    coerce_lead,
    coerce_marks,
    coerce_player_leads,
    coerce_players,
    coerce_templates,
    coerce_volume,
    options_from_settings,
    plan_announcements,
)
from .manager import ShabbotManager
from .store import new_id

PARTS = ["night", "day", "block"]
STATES = ["on", "off"]
END_STATES = ["on", "off", "leave"]
DAY_TYPES = ["shabbat", "yomtov", "shabbat_only", "yomtov_only"]
DETECTORS = ["none", "event", "flip_pattern", "persistence"]

# Events never offered by Learn.
LEARN_IGNORE = {
    "state_changed", "state_reported", "call_service", "service_registered", "service_removed",
    "component_loaded", "core_config_updated", "logbook_entry", "entity_registry_updated",
    "device_registry_updated", "area_registry_updated", "automation_triggered", "script_started",
    "recorder_5min_statistics_generated", "recorder_hourly_statistics_generated", "panels_updated",
    "themes_updated", "lovelace_updated", "user_added", "user_removed", "user_updated", "timer_out_of_sync",
    "homeassistant_start", "homeassistant_started", "homeassistant_stop", "homeassistant_final_write",
    "data_entry_flow_progressed", "config_entry_discovered", "repairs_issue_registry_updated",
}
LEARN_ID_KEYS = ("device_id", "serial", "unique_id", "device_ieee", "node_id")


def _expr(value: Any) -> str:
    value = str(value).strip()
    try:
        timeexpr.validate(value)
    except timeexpr.ExprError as err:
        raise vol.Invalid(str(err)) from err
    return value


def _entities(action: dict) -> dict:
    """Store a row's devices as a de-duplicated `entity_ids` list (accepts the older single `entity_id`)."""
    entities = planner.action_entities(action)
    if not entities:
        raise vol.Invalid("Choose at least one device for each row")
    action = {k: v for k, v in action.items() if k != "entity_id"}
    action["entity_ids"] = entities
    return action


ACTION_SCHEMA = vol.All(vol.Schema({
    vol.Optional("id"): str,
    vol.Optional("entity_id"): str,
    vol.Optional("entity_ids"): [str],
    vol.Required("state"): vol.In(STATES),
    vol.Optional("brightness"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=100))),
    vol.Optional("temperature"): vol.Any(None, vol.Coerce(float)),
    vol.Required("start"): _expr,
    vol.Required("end"): _expr,
    vol.Optional("end_state"): vol.Any(None, vol.In(END_STATES)),
    vol.Optional("label"): vol.Any(None, str),
    vol.Optional("repeat"): vol.Any(None, vol.In(planner.REPEATS)),  # baseline rows only
}), _entities)
ROUTINE_SCHEMA = vol.Schema({
    vol.Optional("id"): vol.Any(None, str),
    vol.Required("name"): vol.All(str, vol.Length(min=1)),
    vol.Required("part"): vol.In(PARTS),
    vol.Optional("color"): vol.Any(None, str),
    vol.Optional("description"): vol.Any(None, str),
    vol.Required("actions"): [ACTION_SCHEMA],
})
RULE_SCHEMA = vol.Schema({
    vol.Optional("id"): vol.Any(None, str),
    vol.Required("name"): str,
    vol.Required("part"): vol.In(PARTS),
    vol.Optional("enabled", default=True): bool,
    vol.Required("match"): {
        vol.Optional("day_type"): vol.Any(None, vol.In(DAY_TYPES)),
        vol.Optional("holiday_group"): vol.Any(None, vol.In(jcal.HOLIDAY_GROUPS)),
        vol.Optional("holiday"): vol.Any(None, str),
        vol.Optional("day_in_block"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=3))),
        vol.Optional("weekday"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=6))),
    },
    vol.Optional("routine_id"): vol.Any(None, str),
})
MODE_SCHEMA = vol.Schema({
    vol.Optional("id"): vol.Any(None, str),
    vol.Required("name"): vol.All(str, vol.Length(min=1)),
    vol.Optional("enabled", default=True): bool,
    vol.Required("start"): vol.All(str, vol.Date()),
    vol.Optional("end"): vol.Any(None, vol.All(str, vol.Date())),
    vol.Optional("night"): vol.Any(None, str),
    vol.Optional("day"): vol.Any(None, str),
    vol.Optional("block"): vol.Any(None, str),
    vol.Optional("protection", default=True): bool,
})
MATCHER_SCHEMA = vol.Any(None, vol.Schema({vol.Required("event_type"): str, vol.Optional("data"): dict}))
DEVICE_SCHEMA = vol.Schema({
    vol.Optional("protect"): bool,
    vol.Optional("override"): {
        vol.Required("detector"): vol.In(DETECTORS),
        vol.Optional("start"): MATCHER_SCHEMA,
        vol.Optional("end"): MATCHER_SCHEMA,
        vol.Optional("count"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=2, max=10))),
        vol.Optional("window_s"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=1, max=600))),
        vol.Optional("preset"): vol.Any(None, str),
    },
    vol.Optional("override_minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=24 * 60)),
    vol.Optional("after_override"): vol.In(["reassert", "next_transition"]),
    vol.Optional("override_group"): [str],
})


def _as_vol(fn):
    """Turn a ValueError from the announcement coercers into a config-flow error."""

    def _run(value):
        try:
            return fn(value)
        except ValueError as err:
            raise vol.Invalid(str(err)) from err

    return _run


SETTINGS_SCHEMA = vol.Schema({
    vol.Optional("candle_lighting_min"): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
    vol.Optional("havdalah_mode"): vol.In(["degrees", "minutes"]),
    vol.Optional("havdalah_degrees"): vol.All(vol.Coerce(float), vol.Range(min=5, max=20)),
    vol.Optional("havdalah_minutes"): vol.All(vol.Coerce(int), vol.Range(min=20, max=90)),
    vol.Optional("israel"): bool,
    vol.Optional("use_elevation"): bool,
    vol.Optional("early_shabbat"): bool,
    vol.Optional("early_shabbat_time"): vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$"),
    vol.Optional("early_shabbat_after"): vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$"),
    vol.Optional("latitude"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=-90, max=90))),
    vol.Optional("longitude"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=-180, max=180))),
    vol.Optional("dry_run"): bool,
    vol.Optional("protection"): bool,
    vol.Optional("grace_seconds"): vol.All(vol.Coerce(float), vol.Range(min=0, max=60)),
    vol.Optional("storm_max_reverts"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    vol.Optional("storm_window_min"): vol.All(vol.Coerce(float), vol.Range(min=1, max=120)),
    vol.Optional("notify_service"): vol.Any(None, str),
    vol.Optional("notify_overrides"): bool,
    vol.Optional("announce_enabled"): bool,
    vol.Optional("announce_players"): _as_vol(lambda v: list(coerce_players(v))),
    vol.Optional("announce_tts_entity"): vol.Any(None, str),
    vol.Optional("announce_voice"): vol.Any(None, str),
    vol.Optional("announce_language"): vol.Any(None, str),
    vol.Optional("announce_lead_seconds"): _as_vol(coerce_lead),
    vol.Optional("announce_player_leads"): _as_vol(coerce_player_leads),
    vol.Optional("announce_volume"): _as_vol(coerce_volume),
    vol.Optional("announce_candle_marks"): _as_vol(lambda v: list(coerce_marks(v))),
    vol.Optional("announce_shkia_marks"): _as_vol(lambda v: list(coerce_marks(v))),
    vol.Optional("announce_yt_marks"): _as_vol(lambda v: list(coerce_marks(v))),
    vol.Optional("announce_shkia_final_min"): vol.All(vol.Coerce(int), vol.Range(min=0, max=180)),
    vol.Optional("announce_groups"): _as_vol(lambda v: coerce_groups(v, strict=True)),
    vol.Optional("announce_templates"): _as_vol(lambda v: coerce_templates(v, strict=True)),
})


def _mgr(hass: HomeAssistant) -> ShabbotManager:
    return hass.data[DOMAIN]


def _ready(func):
    """Reject commands while ShabBOT isn't set up."""

    async def wrapper(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
        if DOMAIN not in hass.data:
            connection.send_error(msg["id"], "not_ready", "ShabBOT is not set up")
            return
        try:
            await func(hass, connection, msg)
        except vol.Invalid as err:
            connection.send_error(msg["id"], "invalid_format", str(err))

    return wrapper


def _range(msg: dict) -> tuple[date, date]:
    start, end = date.fromisoformat(msg["start"][:10]), date.fromisoformat(msg["end"][:10])
    if (end - start).days > 400:
        raise vol.Invalid("Range too long (max 400 days)")
    return start, end


# ---------------------------------------------------------------- reads


@websocket_api.websocket_command({vol.Required("type"): "shabbot/config"})
@websocket_api.async_response
@_ready
async def ws_config(hass, connection, msg) -> None:
    m = _mgr(hass)
    connection.send_result(msg["id"], {
        # routine_order: the panel's cache can't see a change in key order alone, so send the order as a list.
        "config": {**m.config, "routine_order": list(m.config["routines"])},
        "meta": {
            "version": VERSION,
            "anchors": list(timeexpr.ANCHORS),
            "holiday_groups": jcal.HOLIDAY_GROUPS,
            "day_types": DAY_TYPES,
            "detectors": DETECTORS,
            "default_device": DEFAULT_DEVICE,
            "default_settings": DEFAULT_SETTINGS,
            "location": m.status()["location"],
            "is_admin": connection.user.is_admin,
        },
    })


@websocket_api.websocket_command({vol.Required("type"): "shabbot/plan", vol.Required("start"): str,
                                  vol.Required("end"): str})
@websocket_api.async_response
@_ready
async def ws_plan(hass, connection, msg) -> None:
    start, end = _range(msg)
    blocks, instances = _mgr(hass).plan(start, end)
    connection.send_result(msg["id"], {"blocks": [b.to_dict() for b in blocks],
                                       "instances": [i.to_dict() for i in instances]})


@websocket_api.websocket_command({vol.Required("type"): "shabbot/timeline", vol.Required("start"): str,
                                  vol.Required("end"): str})
@websocket_api.async_response
@_ready
async def ws_timeline(hass, connection, msg) -> None:
    start, end = _range(msg)
    _, instances = _mgr(hass).plan(start, end)
    tl = planner.Timeline(instances)
    connection.send_result(msg["id"], {e: [iv.to_dict() for iv in ivs] for e, ivs in tl.intervals.items()})


@websocket_api.websocket_command({vol.Required("type"): "shabbot/preview", vol.Required("expr"): str,
                                  vol.Optional("key"): str, vol.Optional("part"): vol.In(PARTS)})
@websocket_api.async_response
@_ready
async def ws_preview(hass, connection, msg) -> None:
    """Evaluate an expression for a slot (default: the next slot of that part)."""
    m = _mgr(hass)
    today = m.now().date()
    now = m.now()
    blocks = jcal.blocks_between(today, today + timedelta(days=60), m.location, m.minhag)
    targets = [t for b in blocks if b.end > now for t in planner.targets_for_block(b)
               if t.slot is None or t.slot.end > now]
    if msg.get("key"):
        day = date.fromisoformat(msg["key"][:10])
        targets = [t for b in jcal.blocks_between(day, day, m.location, m.minhag)
                   for t in planner.targets_for_block(b)]
        targets = [t for t in targets if t.key == msg["key"]]
    elif msg.get("part"):
        targets = [t for t in targets if t.part == msg["part"]]
    if not targets:
        connection.send_result(msg["id"], {"error": "No matching Shabbat/Yom Tov found"})
        return
    t = targets[0]
    try:
        when = timeexpr.evaluate(msg["expr"], t.anchors, t.base_date, t.night, m.location.tzinfo)
        connection.send_result(msg["id"], {"time": when.isoformat(), "key": t.key, "title": t.title})
    except timeexpr.ExprError as err:
        connection.send_result(msg["id"], {"error": str(err), "key": t.key, "title": t.title})


@websocket_api.websocket_command({vol.Required("type"): "shabbot/status"})
@websocket_api.async_response
@_ready
async def ws_status(hass, connection, msg) -> None:
    connection.send_result(msg["id"], _mgr(hass).status())


@websocket_api.websocket_command({vol.Required("type"): "shabbot/activity", vol.Optional("limit", default=200): int})
@websocket_api.async_response
@_ready
async def ws_activity(hass, connection, msg) -> None:
    connection.send_result(msg["id"], list(reversed(_mgr(hass).store.activity[-msg["limit"]:])))


@websocket_api.websocket_command({vol.Required("type"): "shabbot/subscribe"})
@websocket_api.async_response
@_ready
async def ws_subscribe(hass, connection, msg) -> None:
    @callback
    def on_update() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"type": "update"}))

    @callback
    def on_activity(entry: dict) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"type": "activity", "entry": entry}))

    unsubs = [async_dispatcher_connect(hass, SIGNAL_UPDATE, on_update),
              async_dispatcher_connect(hass, SIGNAL_ACTIVITY, on_activity)]

    @callback
    def unsub_all() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = unsub_all
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/export"})
@websocket_api.async_response
@_ready
async def ws_export(hass, connection, msg) -> None:
    c = _mgr(hass).config
    settings = {k: v for k, v in c["settings"].items() if k not in EXPORT_SKIP_SETTINGS}
    connection.send_result(msg["id"], {"shabbot_export": 1, "version": VERSION, "settings": settings,
                                       "routines": c["routines"], "rules": c["rules"], "modes": c["modes"],
                                       "devices": c["devices"]})


def _check_routine(m: ShabbotManager, part: str, actions: list[dict]) -> list[planner.ActionCheck]:
    """Check each row against every occurrence of `part` in the next year."""
    today, now = m.now().date(), m.now()
    blocks = [b for b in jcal.blocks_between(today, today + timedelta(days=365), m.location, m.minhag) if b.end > now]
    return planner.check_actions(part, actions, blocks, m.location.tzinfo)


@websocket_api.websocket_command({
    vol.Required("type"): "shabbot/routine/check",
    vol.Required("part"): vol.In(PARTS),
    vol.Required("actions"): [{vol.Required("start"): str, vol.Required("end"): str,
                               vol.Optional("repeat"): vol.Any(None, vol.In(planner.REPEATS))}],
})
@websocket_api.async_response
@_ready
async def ws_routine_check(hass, connection, msg) -> None:
    actions = [{"start": a["start"], "end": a["end"], "repeat": a.get("repeat")} for a in msg["actions"]]
    connection.send_result(msg["id"], [c.to_dict() for c in _check_routine(_mgr(hass), msg["part"], actions)])


# ---------------------------------------------------------------- writes


@websocket_api.websocket_command({vol.Required("type"): "shabbot/routine/save", vol.Required("routine"): dict})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_routine_save(hass, connection, msg) -> None:
    m = _mgr(hass)
    routine = ROUTINE_SCHEMA(msg["routine"])
    for action in routine["actions"]:
        if routine["part"] != "block" or action.get("repeat") in (None, planner.ONCE):
            action.pop("repeat", None)  # only baseline rows repeat; "once" is the default
    for check in _check_routine(m, routine["part"], routine["actions"]):
        if check.always_invalid:
            entity = ", ".join(routine["actions"][check.index]["entity_ids"])
            raise vol.Invalid(f"Row {check.index + 1} ({entity}): the end time is never after the start time")
    routine["id"] = routine.get("id") or new_id()
    for action in routine["actions"]:
        action["id"] = action.get("id") or new_id()
    m.config["routines"][routine["id"]] = routine
    m.config_changed()
    connection.send_result(msg["id"], routine)


@websocket_api.websocket_command({vol.Required("type"): "shabbot/routine/delete", vol.Required("routine_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_routine_delete(hass, connection, msg) -> None:
    m, rid = _mgr(hass), msg["routine_id"]
    m.config["routines"].pop(rid, None)
    for rule in m.config["rules"]:
        if rule.get("routine_id") == rid:
            rule["routine_id"] = None
    for mode in m.config["modes"]:
        for part in PARTS:
            if mode.get(part) == rid:
                mode[part] = None
    for key, a in list(m.config["assignments"].items()):
        if a.get("routine_id") == rid:
            del m.config["assignments"][key]
    m.config_changed()
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/routines/reorder", vol.Required("routine_ids"): [str]})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_routines_reorder(hass, connection, msg) -> None:
    """Set the order routines are listed in; ids not given keep their place at the end."""
    m = _mgr(hass)
    routines = m.config["routines"]
    order = list(dict.fromkeys(rid for rid in msg["routine_ids"] if rid in routines))
    order += [rid for rid in routines if rid not in order]
    reordered = {rid: routines[rid] for rid in order}
    routines.clear()
    routines.update(reordered)
    m.config_changed(reconcile=False)  # order is only for display
    connection.send_result(msg["id"], order)


@websocket_api.websocket_command({vol.Required("type"): "shabbot/rules/save", vol.Required("rules"): list})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_rules_save(hass, connection, msg) -> None:
    m = _mgr(hass)
    rules = [RULE_SCHEMA(r) for r in msg["rules"]]
    for rule in rules:
        rule["id"] = rule.get("id") or new_id()
        rule["match"] = {k: v for k, v in rule["match"].items() if v not in (None, "")}
    m.config["rules"] = rules
    m.config_changed()
    connection.send_result(msg["id"], rules)


@websocket_api.websocket_command({vol.Required("type"): "shabbot/modes/save", vol.Required("modes"): list})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_modes_save(hass, connection, msg) -> None:
    m = _mgr(hass)
    modes = [MODE_SCHEMA(x) for x in msg["modes"]]
    for mode in modes:
        mode["id"] = mode.get("id") or new_id()
        if mode.get("end") and mode["end"] < mode["start"]:
            raise vol.Invalid(f"{mode['name']}: end date is before start date")
    m.config["modes"] = modes
    m.config_changed()
    connection.send_result(msg["id"], modes)


@websocket_api.websocket_command({vol.Required("type"): "shabbot/device/save", vol.Required("entity_id"): str,
                                  vol.Required("device"): dict})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_device_save(hass, connection, msg) -> None:
    m = _mgr(hass)
    device = DEVICE_SCHEMA(msg["device"])
    m.config["devices"][msg["entity_id"]] = {**m.config["devices"].get(msg["entity_id"], {}), **device}
    m.config_changed(reconcile=False)
    connection.send_result(msg["id"], m.config["devices"][msg["entity_id"]])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/device/delete", vol.Required("entity_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_device_delete(hass, connection, msg) -> None:
    m = _mgr(hass)
    m.config["devices"].pop(msg["entity_id"], None)
    m.config_changed(reconcile=False)
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/device/zwave_preset", vol.Required("entity_id"): str,
                                  vol.Optional("taps", default=3): vol.All(int, vol.Range(min=1, max=5)),
                                  vol.Optional("up_scene", default="001"): str,
                                  vol.Optional("down_scene", default="002"): str})
@websocket_api.async_response
@_ready
async def ws_zwave_preset(hass, connection, msg) -> None:
    entry = er.async_get(hass).async_get(msg["entity_id"])
    if entry is None or entry.device_id is None:
        connection.send_error(msg["id"], "not_found", "Entity has no device in the registry")
        return
    matchers = gestures.zwave_multitap_matchers(entry.device_id, msg["taps"], msg["up_scene"], msg["down_scene"])
    connection.send_result(msg["id"], {"detector": "event", "preset": f"zwave_{msg['taps']}x", **matchers})


@websocket_api.websocket_command({vol.Required("type"): "shabbot/settings/save", vol.Required("settings"): dict})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_settings_save(hass, connection, msg) -> None:
    m = _mgr(hass)
    m.settings.update(SETTINGS_SCHEMA(msg["settings"]))
    m.config_changed()
    connection.send_result(msg["id"], m.settings)


@websocket_api.websocket_command({
    vol.Required("type"): "shabbot/announce/test",
    vol.Optional("message"): vol.Any(None, str),
})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_announce_test(hass, connection, msg) -> None:
    """Speak one sentence now, so the chosen players and TTS engine can be checked."""
    m = _mgr(hass)
    try:
        await m.announcer.async_speak_test(msg.get("message"))
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"dry_run": bool(m.settings.get("dry_run"))})


@websocket_api.websocket_command({
    vol.Required("type"): "shabbot/announce/upcoming",
    vol.Optional("settings"): dict,
})
@websocket_api.async_response
@_ready
async def ws_announce_upcoming(hass, connection, msg) -> None:
    """The next sentences, at the time they should be heard.

    ``settings`` is an unsaved draft from the panel. Zmanim still come from the
    saved minhag; only announcement options are overlaid.
    """
    m = _mgr(hass)
    settings = dict(m.settings)
    if msg.get("settings"):
        settings.update(SETTINGS_SCHEMA(msg["settings"]))
    options = options_from_settings(settings)
    now = m.now()
    blocks = jcal.blocks_between(
        now.date() - timedelta(days=3),
        now.date() + timedelta(days=PLAN_HORIZON_DAYS),
        m.location,
        m.minhag,
    )
    events = plan_announcements(blocks, m.minhag, options)
    items = [
        {"at": event.nominal_at.isoformat(), "kind": event.kind, "message": event.message, "minutes": event.minutes}
        for event in events
        if event.nominal_at > now
    ][:8]
    connection.send_result(msg["id"], {"enabled": options.enabled, "items": items})


@websocket_api.websocket_command({
    vol.Required("type"): "shabbot/assignment/set",
    vol.Required("key"): str,
    vol.Optional("routine_id"): vol.Any(None, str),
    vol.Optional("skip"): bool,
    vol.Optional("disabled_actions"): [str],
})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_assignment_set(hass, connection, msg) -> None:
    m = _mgr(hass)
    current = dict(m.config["assignments"].get(msg["key"], {}))
    for field in ("routine_id", "skip", "disabled_actions"):
        if field in msg:
            current[field] = msg[field]
    current = {k: v for k, v in current.items() if v not in (None, False, [])}
    if current:
        m.config["assignments"][msg["key"]] = current
    else:
        m.config["assignments"].pop(msg["key"], None)
    m.config_changed()
    connection.send_result(msg["id"], current)


@websocket_api.websocket_command({vol.Required("type"): "shabbot/override/start", vol.Required("entity_ids"): [str],
                                  vol.Optional("minutes"): vol.Any(None, vol.Coerce(float))})
@websocket_api.async_response
@_ready
async def ws_override_start(hass, connection, msg) -> None:
    _mgr(hass).start_override(msg["entity_ids"], msg.get("minutes"), reason=f"panel ({connection.user.name})")
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/override/end", vol.Required("entity_ids"): [str]})
@websocket_api.async_response
@_ready
async def ws_override_end(hass, connection, msg) -> None:
    _mgr(hass).end_override(msg["entity_ids"], f"panel ({connection.user.name})")
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/resume", vol.Required("entity_id"): str})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_resume(hass, connection, msg) -> None:
    """Clear a storm/after-override pause for an entity."""
    m = _mgr(hass)
    m.paused.pop(msg["entity_id"], None)
    m.log("settings", "Protection resumed from the panel", msg["entity_id"])
    m.rebuild()
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/import", vol.Required("data"): dict,
                                  vol.Optional("replace", default=False): bool})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_import(hass, connection, msg) -> None:
    m, data = _mgr(hass), msg["data"]
    if data.get("shabbot_export") != 1:
        raise vol.Invalid("Not a ShabBOT export file")
    routines = {rid: ROUTINE_SCHEMA(r) for rid, r in (data.get("routines") or {}).items()}
    rules = [RULE_SCHEMA(r) for r in data.get("rules") or []]
    modes = [MODE_SCHEMA(x) for x in data.get("modes") or []]
    devices = {e: DEVICE_SCHEMA(d) for e, d in (data.get("devices") or {}).items()}
    settings = SETTINGS_SCHEMA({k: v for k, v in (data.get("settings") or {}).items() if k in SETTINGS_SCHEMA.schema})
    c = m.config
    if msg["replace"]:
        c["routines"], c["rules"], c["modes"], c["devices"] = routines, rules, modes, devices
    else:
        c["routines"].update(routines)
        known = {r["id"] for r in c["rules"]}
        c["rules"] += [r for r in rules if r.get("id") not in known]
        known = {x["id"] for x in c["modes"]}
        c["modes"] += [x for x in modes if x.get("id") not in known]
        c["devices"].update(devices)
    c["settings"].update({k: v for k, v in settings.items() if k not in ("dry_run",)})
    m.log("settings", f"Imported {len(routines)} routines, {len(rules)} rules, {len(modes)} modes")
    m.config_changed()
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): "shabbot/learn"})
@websocket_api.require_admin
@websocket_api.async_response
@_ready
async def ws_learn(hass, connection, msg) -> None:
    """Stream bus events (e.g. button presses) so the user can pick one as an override gesture."""

    @callback
    def on_event(event: Event) -> None:
        if event.event_type in LEARN_IGNORE or event.event_type.startswith(DOMAIN):
            return
        data = dict(event.data)
        if not any(k in data for k in LEARN_ID_KEYS):
            return
        safe = {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool)) or v is None}
        connection.send_message(websocket_api.event_message(msg["id"], {
            "event_type": event.event_type,
            "data": safe,
            "time": event.time_fired.isoformat(),
            "matcher": gestures.suggest_matcher(event.event_type, safe),
        }))

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(MATCH_ALL, on_event)
    connection.send_result(msg["id"])


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    for handler in (
        ws_config, ws_plan, ws_timeline, ws_preview, ws_status, ws_activity, ws_subscribe, ws_export, ws_routine_check,
        ws_routine_save, ws_routine_delete, ws_routines_reorder, ws_rules_save, ws_modes_save, ws_device_save,
        ws_device_delete, ws_zwave_preset, ws_settings_save, ws_announce_test, ws_announce_upcoming,
        ws_assignment_set, ws_override_start, ws_override_end, ws_resume, ws_import, ws_learn,
    ):
        websocket_api.async_register_command(hass, handler)
