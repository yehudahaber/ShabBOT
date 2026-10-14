"""ShabBOT runtime: planning, the executor, device protection and overrides."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import date, datetime, time, timedelta
from functools import partial
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .announcer import Announcer
from .const import PLAN_HORIZON_DAYS, POLL_SECONDS, SIGNAL_ACTIVITY, SIGNAL_UPDATE
from .core import astro, gestures, jcal, planner
from .store import ShabbotStore, device_config

_LOGGER = logging.getLogger(__name__)

OFF_STATES = {"off", "closed", "standby", "idle", "paused"}
ECHO_SECONDS = 20  # a state matching our last command within this window is our own echo
SERVICE_TIMEOUT = 30


def _hhmm(value: str | None) -> time | None:
    """Parse "HH:MM" from settings."""
    if not value:
        return None
    hour, minute = value.split(":")[:2]
    return time(int(hour), int(minute))


def is_on(state: State) -> bool:
    return state.state not in OFF_STATES


def matches(state: State, desired: str) -> bool:
    return is_on(state) == (desired == "on")


def service_calls(entity_id: str, state: str, attrs: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Map a desired on/off (+ attributes) to Home Assistant service calls."""
    domain = entity_id.split(".", 1)[0]
    target = {"entity_id": entity_id}
    if domain == "light":
        if state == "on":
            data = {**target}
            if attrs.get("brightness") is not None:
                data["brightness_pct"] = int(attrs["brightness"])
            return [("light", "turn_on", data)]
        return [("light", "turn_off", target)]
    if domain == "climate":
        if state == "off":
            return [("climate", "turn_off", target)]
        calls = [("climate", "turn_on", target)]
        if attrs.get("temperature") is not None:
            calls.append(("climate", "set_temperature", {**target, "temperature": float(attrs["temperature"])}))
        return calls
    if domain == "cover":
        return [("cover", "open_cover" if state == "on" else "close_cover", target)]
    return [("homeassistant", "turn_on" if state == "on" else "turn_off", target)]


class ShabbotManager:
    """One instance per config entry (ShabBOT is single-instance)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: ShabbotStore) -> None:
        self.hass = hass
        self.entry = entry
        self.store = store
        self.timeline = planner.Timeline([])
        self.instances: list[planner.Instance] = []
        self.overrides: dict[str, dict[str, Any]] = {}
        self.paused: dict[str, str] = {}  # entity -> reason; cleared at the entity's next boundary
        self._own_contexts: dict[str, datetime] = {}
        self._expected: dict[str, tuple[str, datetime]] = {}
        self._pending_revert: dict[str, CALLBACK_TYPE] = {}
        self._override_timers: dict[str, CALLBACK_TYPE] = {}
        self._reverts: dict[str, deque[datetime]] = {}
        self._trackers: dict[str, gestures.GestureTracker] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._state_unsub: CALLBACK_TYPE | None = None
        self._event_unsubs: list[CALLBACK_TYPE] = []
        self._boundary_unsub: CALLBACK_TYPE | None = None
        self._block_unsub: CALLBACK_TYPE | None = None
        self._next_boundary: datetime | None = None
        self.announcer = Announcer(self)

    # ------------------------------------------------------------ config accessors

    @property
    def config(self) -> dict[str, Any]:
        return self.store.config

    @property
    def settings(self) -> dict[str, Any]:
        return self.store.config["settings"]

    @property
    def location(self) -> astro.Location:
        s, c = self.settings, self.hass.config
        return astro.Location(
            latitude=s["latitude"] if s.get("latitude") is not None else c.latitude,
            longitude=s["longitude"] if s.get("longitude") is not None else c.longitude,
            time_zone=c.time_zone,
            elevation_m=float(c.elevation or 0),
        )

    @property
    def minhag(self) -> jcal.Minhag:
        s = self.settings
        return jcal.Minhag(
            candle_lighting_min=int(s["candle_lighting_min"]),
            havdalah_mode=s["havdalah_mode"],
            havdalah_degrees=float(s["havdalah_degrees"]),
            havdalah_minutes=int(s["havdalah_minutes"]),
            israel=bool(s["israel"]),
            use_elevation=bool(s["use_elevation"]),
            early_shabbat_time=_hhmm(s.get("early_shabbat_time")) if s.get("early_shabbat") else None,
            early_shabbat_after=_hhmm(s.get("early_shabbat_after")) if s.get("early_shabbat") else None,
        )

    def now(self) -> datetime:
        return dt_util.now().astimezone(self.location.tzinfo)

    # ------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        self.rebuild()
        self._unsubs.append(async_track_time_interval(self.hass, self._poll, timedelta(seconds=POLL_SECONDS)))
        self._unsubs.append(async_track_time_change(self.hass, self._daily, hour=0, minute=5, second=0))
        await self.async_reconcile("Home Assistant started")

    async def async_stop(self) -> None:
        for unsub in [*self._unsubs, *self._event_unsubs, *self._pending_revert.values(),
                      *self._override_timers.values()]:
            unsub()
        for unsub in (self._state_unsub, self._boundary_unsub, self._block_unsub):
            if unsub:
                unsub()
        self._unsubs.clear()
        await self.announcer.async_stop()
        await self.store.async_flush()

    @callback
    def _daily(self, _now: datetime) -> None:
        self.store.prune_assignments(self.now() - timedelta(days=365))
        self.rebuild()

    # ------------------------------------------------------------ planning

    def plan(self, start: date, end: date) -> tuple[list[jcal.Block], list[planner.Instance]]:
        return planner.plan_range(start, end, self.location, self.minhag, self.config)

    def config_changed(self, reconcile: bool = True) -> None:
        self.store.save_config()
        self.rebuild()
        if reconcile:
            self.hass.async_create_task(self.async_reconcile("Configuration changed"))

    @callback
    def rebuild(self) -> None:
        today = self.now().date()
        _, self.instances = self.plan(today - timedelta(days=2), today + timedelta(days=PLAN_HORIZON_DAYS))
        self.timeline = planner.Timeline(self.instances)
        self._trackers = {}
        self._subscribe_states()
        self._subscribe_events()
        self._schedule_next_boundary()
        self._schedule_block_change()
        self.announcer.reschedule()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    def managed_entities(self) -> list[str]:
        return sorted(set(self.timeline.entities) | set(self.config["devices"]))

    @callback
    def _subscribe_states(self) -> None:
        if self._state_unsub:
            self._state_unsub()
            self._state_unsub = None
        entities = self.managed_entities()
        if entities:
            self._state_unsub = async_track_state_change_event(self.hass, entities, self._on_state_change)

    @callback
    def _subscribe_events(self) -> None:
        for unsub in self._event_unsubs:
            unsub()
        self._event_unsubs = []
        event_types: set[str] = set()
        for cfg in self.config["devices"].values():
            ov = (cfg or {}).get("override") or {}
            if ov.get("detector") == "event":
                event_types |= {m["event_type"] for m in (ov.get("start"), ov.get("end")) if m}
        for event_type in event_types:
            self._event_unsubs.append(self.hass.bus.async_listen(event_type, self._on_bus_event))

    @callback
    def _schedule_next_boundary(self) -> None:
        if self._boundary_unsub:
            self._boundary_unsub()
            self._boundary_unsub = None
        self._next_boundary = self.timeline.next_boundary(self.now())
        if self._next_boundary:
            self._boundary_unsub = async_track_point_in_time(self.hass, self._on_boundary, self._next_boundary)

    @callback
    def _schedule_block_change(self) -> None:
        """Wake entities (Issur Melacha sensor etc.) at the next block start/end."""
        if self._block_unsub:
            self._block_unsub()
            self._block_unsub = None
        nxt = self.next_block_change()
        if nxt:
            self._block_unsub = async_track_point_in_time(self.hass, self._on_block_change, nxt)

    @callback
    def _on_block_change(self, _now: datetime) -> None:
        self._schedule_block_change()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    def current_block(self) -> jcal.Block | None:
        return jcal.block_at(self.now(), self.location, self.minhag)

    def upcoming_blocks(self, days: int = 30) -> list[jcal.Block]:
        today = self.now().date()
        return [b for b in jcal.blocks_between(today, today + timedelta(days=days), self.location, self.minhag)
                if b.end > self.now()]

    def next_block_change(self) -> datetime | None:
        now = self.now()
        times = [t for b in self.upcoming_blocks(10) for t in (b.start, b.end) if t > now]
        return min(times) if times else None

    # ------------------------------------------------------------ executor

    @callback
    def _on_boundary(self, _fired: datetime) -> None:
        t = self._next_boundary
        self._boundary_unsub = None
        if t is None:
            return
        for entity_id in self.timeline.entities_with_boundary(t):
            self.paused.pop(entity_id, None)
            self._reverts.pop(entity_id, None)
            if entity_id in self._trackers:
                self._trackers[entity_id].reset()
            if entity_id in self.overrides:
                continue  # the override's own timer re-asserts when it ends
            desired = self.timeline.desired_at(entity_id, t)
            if desired is not None:
                reason = f"{desired.routine_name}"
                self.hass.async_create_task(self._apply(entity_id, desired.state, desired.attrs, reason))
            else:
                ending = self.timeline.ending_at(entity_id, t)
                if ending and ending.end_state in ("on", "off"):
                    reason = f"End of {ending.routine_name}"
                    self.hass.async_create_task(self._apply(entity_id, ending.end_state, {}, reason))
        self._schedule_next_boundary()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def async_reconcile(self, reason: str) -> None:
        """Assert the desired state of every managed entity right now (idempotent)."""
        now = self.now()
        for entity_id in self.timeline.entities:
            if entity_id in self.overrides:
                continue
            desired = self.timeline.desired_at(entity_id, now)
            state = self.hass.states.get(entity_id)
            if desired is None or state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            if not matches(state, desired.state):
                await self._apply(entity_id, desired.state, desired.attrs, f"{desired.routine_name} ({reason})")

    def _remember(self, ctx: Context, entity_id: str, state: str) -> None:
        now = dt_util.utcnow()
        self._own_contexts = {k: v for k, v in self._own_contexts.items() if v > now}
        self._own_contexts[ctx.id] = now + timedelta(minutes=5)
        self._expected[entity_id] = (state, now + timedelta(seconds=ECHO_SECONDS))

    def _is_ours(self, entity_id: str, state: State) -> bool:
        ctx = state.context
        if ctx.id in self._own_contexts or (ctx.parent_id and ctx.parent_id in self._own_contexts):
            return True
        expected = self._expected.get(entity_id)
        return bool(expected and expected[1] > dt_util.utcnow() and matches(state, expected[0]))

    async def _apply(self, entity_id: str, state: str, attrs: dict[str, Any], reason: str,
                     kind: str = "command") -> None:
        current = self.hass.states.get(entity_id)
        name = current.name if current else entity_id
        if current is None:
            self.log("error", f"{entity_id} not found in Home Assistant", entity_id)
            return
        if self.settings.get("dry_run"):
            self.log("dry_run", f"Would turn {state} {name} — {reason}", entity_id, state=state, would=kind)
            return
        ctx = Context()
        self._remember(ctx, entity_id, state)
        try:
            async with asyncio.timeout(SERVICE_TIMEOUT):
                for domain, service, data in service_calls(entity_id, state, attrs):
                    own_domain = entity_id.split(".", 1)[0]
                    if domain == "homeassistant" and self.hass.services.has_service(own_domain, service):
                        domain = own_domain
                    await self.hass.services.async_call(domain, service, data, blocking=True, context=ctx)
        except Exception as err:  # noqa: BLE001 - any device failure must not stop the engine
            self.log("error", f"Failed to turn {state} {name}: {err}", entity_id)
            return
        verb = "Reverted" if kind == "revert" else "Turned"
        self.log(kind, f"{verb} {name} {state} — {reason}", entity_id, state=state)

    # ------------------------------------------------------------ protection

    def _mode_allows_protection(self) -> bool:
        mode = planner.active_mode(self.config["modes"], self.now().date())
        return mode is None or mode.get("protection", True)

    def protected_desired(self, entity_id: str, now: datetime) -> planner.Interval | None:
        if not self.settings.get("protection") or entity_id in self.paused:
            return None
        if not device_config(self.config, entity_id)["protect"] or not self._mode_allows_protection():
            return None
        return self.timeline.desired_at(entity_id, now)

    def _tracker(self, entity_id: str) -> gestures.GestureTracker:
        if entity_id not in self._trackers:
            self._trackers[entity_id] = gestures.GestureTracker.from_config(
                device_config(self.config, entity_id)["override"])
        return self._trackers[entity_id]

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new, old = event.data["new_state"], event.data["old_state"]
        if new is None or old is None or new.state == old.state:
            return
        if new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or old.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if self._is_ours(entity_id, new):
            return
        now = self.now()
        desired = self.protected_desired(entity_id, now)
        if desired is None:
            return
        deviates = not matches(new, desired.state)
        tracker = self._tracker(entity_id)
        if entity_id in self.overrides:
            if tracker.detector == "flip_pattern" and tracker.manual_change(now, deviates):
                self.end_override([entity_id], "flip gesture")
            return
        if tracker.manual_change(now, deviates):
            self._cancel_revert(entity_id)
            self.start_override(self._with_group(entity_id), reason=f"{tracker.detector.replace('_', ' ')} gesture")
            return
        if not deviates:
            self._cancel_revert(entity_id)
            return
        if entity_id not in self._pending_revert:
            grace = float(self.settings.get("grace_seconds", 4))
            if tracker.needs_extended_grace:
                grace = max(grace, tracker.window.total_seconds())
            self._pending_revert[entity_id] = async_track_point_in_time(
                self.hass, partial(self._revert_due, entity_id), dt_util.utcnow() + timedelta(seconds=grace))

    @callback
    def _revert_due(self, entity_id: str, _now: datetime) -> None:
        self._pending_revert.pop(entity_id, None)
        self.hass.async_create_task(self._revert(entity_id))

    def _cancel_revert(self, entity_id: str) -> None:
        unsub = self._pending_revert.pop(entity_id, None)
        if unsub:
            unsub()

    async def _revert(self, entity_id: str) -> None:
        self._cancel_revert(entity_id)
        if entity_id in self.overrides:
            return
        now = self.now()
        desired = self.protected_desired(entity_id, now)
        state = self.hass.states.get(entity_id)
        if desired is None or state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if matches(state, desired.state):
            return
        window = timedelta(minutes=float(self.settings.get("storm_window_min", 10)))
        q = self._reverts.setdefault(entity_id, deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= int(self.settings.get("storm_max_reverts", 5)):
            self.paused[entity_id] = "storm"
            msg = f"Stopped protecting {state.name}: reverted {len(q)} times in {window.seconds // 60} min"
            self.log("storm", msg, entity_id)
            self.notify(msg)
            async_dispatcher_send(self.hass, SIGNAL_UPDATE)
            return
        q.append(now)
        await self._apply(entity_id, desired.state, desired.attrs, "protection: undid an unexpected change", "revert")

    @callback
    def _poll(self, _now: datetime) -> None:
        now = self.now()
        grace = timedelta(seconds=float(self.settings.get("grace_seconds", 4)))
        for entity_id in self.timeline.entities:
            if entity_id in self.overrides or entity_id in self._pending_revert:
                continue
            desired = self.protected_desired(entity_id, now)
            state = self.hass.states.get(entity_id)
            if desired is None or state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            if not matches(state, desired.state) and now - state.last_changed > grace:
                self.hass.async_create_task(self._revert(entity_id))

    # ------------------------------------------------------------ overrides

    def _with_group(self, entity_id: str) -> list[str]:
        group = device_config(self.config, entity_id).get("override_group") or []
        return [entity_id, *[e for e in group if e != entity_id]]

    @callback
    def _on_bus_event(self, event: Event) -> None:
        data = dict(event.data)
        for entity_id, cfg in self.config["devices"].items():
            ov = (cfg or {}).get("override") or {}
            if ov.get("detector") != "event":
                continue
            is_start = gestures.event_matches(ov.get("start"), event.event_type, data)
            is_end = gestures.event_matches(ov.get("end"), event.event_type, data)
            if is_start and is_end:  # single-button remotes toggle
                is_start = entity_id not in self.overrides
                is_end = not is_start
            if is_start:
                self.start_override(self._with_group(entity_id), reason="override gesture")
            elif is_end and entity_id in self.overrides:
                self.end_override(self._with_group(entity_id), "end gesture")

    @callback
    def start_override(self, entity_ids: list[str], minutes: float | None = None, reason: str = "manual") -> None:
        now = self.now()
        names = []
        first_mins = 0.0
        for entity_id in entity_ids:
            cfg = device_config(self.config, entity_id)
            mins = float(minutes if minutes is not None else cfg["override_minutes"])
            first_mins = first_mins or mins
            until = now + timedelta(minutes=mins)
            self._cancel_revert(entity_id)
            if timer := self._override_timers.pop(entity_id, None):
                timer()
            self.overrides[entity_id] = {"until": until.isoformat(), "started": now.isoformat(), "reason": reason}
            self._override_timers[entity_id] = async_track_point_in_time(
                self.hass, partial(self._override_expired, entity_id), until)
            state = self.hass.states.get(entity_id)
            names.append(state.name if state else entity_id)
            self.log("override_start", f"Protection paused for {mins:g} min ({reason})", entity_id,
                     until=until.isoformat())
        if names and self.settings.get("notify_overrides"):
            self.notify(f"Override: {', '.join(names)} unprotected for {first_mins:g} min ({reason})")
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    @callback
    def _override_expired(self, entity_id: str, _now: datetime) -> None:
        self._override_timers.pop(entity_id, None)
        self.end_override([entity_id], "timer ended")

    @callback
    def end_override(self, entity_ids: list[str], reason: str = "manual") -> None:
        for entity_id in entity_ids:
            if self.overrides.pop(entity_id, None) is None:
                continue
            if timer := self._override_timers.pop(entity_id, None):
                timer()
            self._tracker(entity_id).reset()
            self._reverts.pop(entity_id, None)
            self.log("override_end", f"Protection resumed ({reason})", entity_id)
            after = device_config(self.config, entity_id)["after_override"]
            if after == "reassert":
                self.hass.async_create_task(self._reassert(entity_id))
            elif after == "next_transition":
                self.paused[entity_id] = "waiting for next scheduled change"
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    async def _reassert(self, entity_id: str) -> None:
        desired = self.protected_desired(entity_id, self.now())
        state = self.hass.states.get(entity_id)
        if desired and state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) and not matches(
                state, desired.state):
            await self._apply(entity_id, desired.state, desired.attrs, "override ended")

    # ------------------------------------------------------------ activity / notify / status

    @callback
    def log(self, kind: str, message: str, entity_id: str | None = None, **extra: Any) -> None:
        entry = self.store.add_activity(kind, message, entity_id, **extra)
        level = logging.WARNING if kind in ("error", "storm") else logging.INFO
        _LOGGER.log(level, "%s %s", entity_id or "", message)
        async_dispatcher_send(self.hass, SIGNAL_ACTIVITY, entry)

    @callback
    def notify(self, message: str) -> None:
        target = (self.settings.get("notify_service") or "").strip()
        if not target or "." not in target:
            return
        domain, service = target.split(".", 1)
        self.hass.async_create_task(self.hass.services.async_call(
            domain, service, {"title": "ShabBOT", "message": message}, blocking=False))

    def status(self) -> dict[str, Any]:
        now = self.now()
        block = self.current_block()
        rows = []
        for entity_id in self.managed_entities():
            state = self.hass.states.get(entity_id)
            desired = self.timeline.desired_at(entity_id, now)
            protected = self.protected_desired(entity_id, now) is not None
            rows.append({
                "entity_id": entity_id,
                "name": state.name if state else entity_id,
                "state": state.state if state else None,
                "desired": desired.to_dict() if desired else None,
                "in_sync": bool(desired is None or (state and matches(state, desired.state))),
                "protected": protected,
                "override": self.overrides.get(entity_id),
                "paused": self.paused.get(entity_id),
                "pending_revert": entity_id in self._pending_revert,
            })
        return {
            "now": now.isoformat(),
            "issur_melacha": block is not None,
            "block": {"id": block.id, "title": block.title, "start": block.start.isoformat(),
                      "end": block.end.isoformat()} if block else None,
            "dry_run": bool(self.settings.get("dry_run")),
            "protection": bool(self.settings.get("protection")),
            "next_boundary": self._next_boundary.isoformat() if self._next_boundary else None,
            "location": {"latitude": self.location.latitude, "longitude": self.location.longitude,
                         "time_zone": self.location.time_zone, "elevation": self.location.elevation_m},
            "entities": rows,
        }
