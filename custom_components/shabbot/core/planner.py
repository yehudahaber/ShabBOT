"""Planner: blocks + routines + rules + modes + assignments -> desired device states.

Pure functions over plain dicts (the persisted config), so it is easy to test
and to call from the websocket API for arbitrary calendar ranges.

Config shapes (see store.py for defaults):

routine   {id, name, part: night|day|block, color, actions: [action]}
action    {id, entity_ids (or legacy entity_id), state: on|off, brightness?: 1-100, temperature?: float,
           start: expr, end: expr, end_state?: on|off|leave}
rule      {id, name, part, match: {day_type?, holiday_group?, holiday?, day_in_block?, weekday?}, routine_id|None}
mode      {id, name, enabled, start: date, end: date|None, night|day|block: routine_id|"none"|None, protection: bool}
assignment  assignments[slot_key | "{block_id}/block"] = {routine_id?, skip?, disabled_actions?: [action_id]}
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import product
from typing import Any

from . import astro, jcal, timeexpr

BLOCK_PART = "block"
NONE = "none"
PRIORITY = {BLOCK_PART: 0, "night": 1, "day": 1}


@dataclass(slots=True)
class Target:
    """A context a routine can be applied to: one slot, or a whole block (baseline)."""

    key: str
    part: str  # night | day | block
    block: jcal.Block
    slot: jcal.Slot | None

    @property
    def day(self) -> date:
        return self.slot.day if self.slot else self.block.days[0]

    @property
    def title(self) -> str:
        return self.slot.title if self.slot else f"{self.block.title} — Baseline"

    @property
    def anchors(self) -> dict[str, datetime]:
        if self.slot:
            return self.slot.anchors
        # Baseline: zmanim of the first evening; slot = the whole block.
        first = self.block.slots[0]
        return {**first.anchors, "slot_start": self.block.start, "slot_end": self.block.end}

    @property
    def next_anchors(self) -> dict[str, datetime]:
        if self.slot:
            return self.slot.next_anchors
        first = self.block.slots[0]
        return {**first.next_anchors, "slot_start": self.block.start, "slot_end": self.block.end}

    @property
    def base_date(self) -> date:
        return self.slot.base_date if self.slot else self.block.slots[0].base_date

    @property
    def night(self) -> bool:
        return self.slot is None or self.slot.part is jcal.Part.NIGHT


def evaluate_window(action: dict[str, Any], target: Target, tz) -> tuple[datetime, datetime, bool]:
    """Resolve an action's (start, end, crosses_midnight) for one target.

    If the end comes before the start (e.g. sunset → sunrise, or 10pm → 6am on a day meal), the end is
    read as the next day's time. Raises ExprError if it still doesn't fit within 24 hours after the start.
    """
    start = timeexpr.evaluate(action["start"], target.anchors, target.base_date, target.night, tz)
    end = timeexpr.evaluate(action["end"], target.anchors, target.base_date, target.night, tz)
    if end > start:
        return start, end, False
    end = timeexpr.evaluate(action["end"], target.next_anchors, target.base_date + timedelta(days=1), False, tz)
    if start < end <= start + timedelta(hours=24):
        return start, end, True
    raise timeexpr.ExprError("End is not after start")


def action_entities(action: dict[str, Any]) -> list[str]:
    """Devices a routine row controls; rows saved before multi-device support have a single entity_id."""
    entities = action.get("entity_ids") or ([action["entity_id"]] if action.get("entity_id") else [])
    return list(dict.fromkeys(entities))


ONCE, EVERY_NIGHT, EVERY_DAY = "once", "night", "day"
REPEATS = (ONCE, EVERY_NIGHT, EVERY_DAY)


def repeat_of(action: dict[str, Any], target: Target) -> str:
    """Baseline rows can repeat every night or every day of the block; meal-routine rows never repeat."""
    repeat = action.get("repeat") or ONCE
    return repeat if target.part == BLOCK_PART and repeat in REPEATS else ONCE


def occurrence_targets(action: dict[str, Any], target: Target) -> list[Target]:
    """The contexts an action is evaluated in: the target itself, or each night/day slot of its block."""
    repeat = repeat_of(action, target)
    if repeat == ONCE:
        return [target]
    return [t for t in targets_for_block(target.block) if t.part == repeat]


def targets_for_block(block: jcal.Block) -> list[Target]:
    targets = [Target(key=f"{block.id}/block", part=BLOCK_PART, block=block, slot=None)]
    targets += [Target(key=s.key, part=s.part.value, block=block, slot=s) for s in block.slots]
    return targets


# ---------------------------------------------------------------- resolution


def _rule_matches(match: dict[str, Any], target: Target) -> bool:
    slots = [target.slot] if target.slot else target.block.slots
    for field_name, want in match.items():
        if want in (None, ""):
            continue
        if field_name == "day_type":
            ok = {
                "shabbat": lambda: any(s.is_shabbat for s in slots),
                "yomtov": lambda: any(s.holiday for s in slots),
                "shabbat_only": lambda: all(s.is_shabbat and not s.holiday for s in slots),
                "yomtov_only": lambda: all(s.holiday and not s.is_shabbat for s in slots),
            }.get(want, lambda: False)()
        elif field_name == "holiday_group":
            ok = any(s.holiday and s.holiday.group == want for s in slots)
        elif field_name == "holiday":
            ok = any(s.holiday and s.holiday.name == want for s in slots)
        elif field_name == "day_in_block":
            ok = target.slot is not None and target.slot.day_in_block == int(want)
        elif field_name == "weekday":
            ok = target.slot is not None and target.slot.day.weekday() == int(want)
        else:
            ok = False
        if not ok:
            return False
    return True


def _specificity(rule: dict[str, Any]) -> int:
    return sum(1 for v in (rule.get("match") or {}).values() if v not in (None, ""))


def active_mode(modes: list[dict[str, Any]], day: date) -> dict[str, Any] | None:
    found = None
    for mode in modes:
        if not mode.get("enabled", True):
            continue
        start = date.fromisoformat(mode["start"])
        end = date.fromisoformat(mode["end"]) if mode.get("end") else None
        in_range = start <= day and (end is None or day <= end)
        if in_range and (found is None or start >= date.fromisoformat(found["start"])):
            found = mode
    return found


@dataclass(slots=True)
class Resolution:
    routine_id: str | None
    source: str  # assignment | mode | rule | skipped | none
    source_name: str = ""
    default_routine_id: str | None = None  # what would apply without the per-occurrence assignment


def resolve(target: Target, config: dict[str, Any]) -> Resolution:
    default = _resolve_default(target, config)
    assignment = (config.get("assignments") or {}).get(target.key) or {}
    if assignment.get("skip"):
        return Resolution(None, "skipped", "Skipped", default.routine_id)
    if assignment.get("routine_id") and assignment["routine_id"] in config.get("routines", {}):
        return Resolution(assignment["routine_id"], "assignment", "Chosen for this date", default.routine_id)
    default.default_routine_id = default.routine_id
    return default


def _resolve_default(target: Target, config: dict[str, Any]) -> Resolution:
    routines = config.get("routines", {})
    mode = active_mode(config.get("modes", []), target.day)
    if mode is not None and mode.get(target.part) is not None:
        rid = mode[target.part]
        if rid == NONE or rid not in routines:
            return Resolution(None, "mode", mode["name"])
        return Resolution(rid, "mode", mode["name"])
    candidates = [
        (i, r) for i, r in enumerate(config.get("rules", []))
        if r.get("part") == target.part and r.get("enabled", True) and _rule_matches(r.get("match") or {}, target)
    ]
    if candidates:
        _, rule = max(candidates, key=lambda ir: (_specificity(ir[1]), -ir[0]))
        rid = rule.get("routine_id")
        if rid and rid in routines:
            return Resolution(rid, "rule", rule.get("name", ""))
        return Resolution(None, "rule", rule.get("name", ""))
    return Resolution(None, "none")


# ---------------------------------------------------------------- planning


@dataclass(slots=True)
class PlannedAction:
    action_id: str
    entity_id: str
    state: str
    attrs: dict[str, Any]
    start: datetime | None
    end: datetime | None
    end_state: str
    disabled: bool = False
    error: str | None = None
    next_day: bool = False  # end was read as the next day's time (crosses midnight)
    occurrence_key: str | None = None  # for baseline rows repeated every night/day: which slot
    occurrence_title: str | None = None
    start_expr: str = ""  # the row's time expressions, e.g. "candle_lighting-20m"
    end_expr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_day": self.next_day, "start_expr": self.start_expr, "end_expr": self.end_expr,
            "occurrence_key": self.occurrence_key, "occurrence_title": self.occurrence_title,
            "action_id": self.action_id, "entity_id": self.entity_id, "state": self.state, "attrs": self.attrs,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "end_state": self.end_state, "disabled": self.disabled, "error": self.error,
        }


@dataclass(slots=True)
class Instance:
    """One routine applied to one target (slot or block)."""

    target: Target
    resolution: Resolution
    routine: dict[str, Any] | None
    actions: list[PlannedAction] = field(default_factory=list)

    def _valid_actions(self) -> list[PlannedAction]:
        return [a for a in self.actions if a.start and a.end and not a.disabled and not a.error]

    @property
    def start(self) -> datetime:
        times = [a.start for a in self._valid_actions() if a.start]
        return min(times) if times else (self.target.slot.start if self.target.slot else self.target.block.start)

    @property
    def end(self) -> datetime:
        """Latest valid end; never before `start` (rows that run backwards are ignored)."""
        times = [a.end for a in self._valid_actions() if a.end]
        end = max(times) if times else (self.target.slot.end if self.target.slot else self.target.block.end)
        return max(end, self.start)

    def to_dict(self) -> dict[str, Any]:
        r = self.resolution
        return {
            "key": self.target.key,
            "part": self.target.part,
            "block_id": self.target.block.id,
            "slot": self.target.slot.to_dict() if self.target.slot else None,
            "target_title": self.target.title,
            "routine_id": r.routine_id,
            "routine_name": self.routine["name"] if self.routine else None,
            "color": (self.routine or {}).get("color"),
            "source": r.source,
            "source_name": r.source_name,
            "default_routine_id": r.default_routine_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "actions": [a.to_dict() for a in self.actions],
        }


def default_end_state(state: str) -> str:
    return "off" if state == "on" else "leave"


def plan_instance(target: Target, config: dict[str, Any], tz) -> Instance:
    res = resolve(target, config)
    routine = config.get("routines", {}).get(res.routine_id) if res.routine_id else None
    inst = Instance(target=target, resolution=res, routine=routine)
    if not routine:
        return inst
    disabled = set(((config.get("assignments") or {}).get(target.key) or {}).get("disabled_actions") or [])
    for action in routine.get("actions", []):
        attrs = {k: action[k] for k in ("brightness", "temperature") if action.get(k) is not None}
        repeated = repeat_of(action, target) != ONCE
        for entity_id, occ in product(action_entities(action), occurrence_targets(action, target)):
            pa = PlannedAction(
                action_id=action["id"], entity_id=entity_id, state=action.get("state", "on"), attrs=attrs,
                start=None, end=None,
                end_state=action.get("end_state") or default_end_state(action.get("state", "on")),
                disabled=action["id"] in disabled,
                occurrence_key=occ.key if repeated else None,
                occurrence_title=occ.title if repeated else None,
                start_expr=action.get("start", ""), end_expr=action.get("end", ""),
            )
            try:
                pa.start, pa.end, pa.next_day = evaluate_window(action, occ, tz)
            except timeexpr.ExprError as err:
                pa.error = str(err)
            inst.actions.append(pa)
    return inst


def plan_range(start: date, end: date, loc: astro.Location, minhag: jcal.Minhag,
               config: dict[str, Any]) -> tuple[list[jcal.Block], list[Instance]]:
    blocks = jcal.blocks_between(start, end, loc, minhag)
    instances = [plan_instance(t, config, loc.tzinfo) for b in blocks for t in targets_for_block(b)]
    return blocks, instances


@dataclass(slots=True)
class ActionCheck:
    """How one routine row behaves across its upcoming occurrences."""

    index: int
    total: int = 0
    next_day: int = 0  # occurrences where the end was read as the next day (crosses midnight)
    invalid: int = 0  # occurrences where the window doesn't work even as next-day
    before_start: int = 0  # occurrences starting before the Shabbat/Yom Tov begins
    after_end: int = 0  # occurrences ending after it ends
    error: str | None = None  # expression error (same for every occurrence)
    next_day_example: dict[str, str] | None = None
    invalid_example: dict[str, str] | None = None
    before_start_example: dict[str, str] | None = None
    after_end_example: dict[str, str] | None = None
    first: dict[str, Any] | None = None  # next valid occurrence, for previews

    @property
    def always_invalid(self) -> bool:
        return self.total > 0 and self.invalid == self.total

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "total": self.total, "next_day": self.next_day, "invalid": self.invalid,
                "before_start": self.before_start, "after_end": self.after_end,
                "always_invalid": self.always_invalid, "error": self.error, "first": self.first,
                "next_day_example": self.next_day_example, "invalid_example": self.invalid_example,
                "before_start_example": self.before_start_example, "after_end_example": self.after_end_example}


def check_actions(part: str, actions: list[dict[str, Any]], blocks: list[jcal.Block], tz) -> list[ActionCheck]:
    """Evaluate each action's window on every occurrence of `part` in `blocks`.

    Zmanim move with the seasons, so a row like `sunset` → `7pm` is an evening window in winter but
    crosses midnight in summer; this reports both, plus windows that never fit and (for baselines)
    windows that start before or end after the Shabbat/Yom Tov.
    """
    targets = [t for b in blocks for t in targets_for_block(b) if t.part == part]
    results = []
    for i, action in enumerate(actions):
        res = ActionCheck(index=i)
        occurrences = [occ for t in targets for occ in occurrence_targets(action, t)]
        for t in occurrences:
            try:
                timeexpr.evaluate(action["start"], t.anchors, t.base_date, t.night, tz)
                timeexpr.evaluate(action["end"], t.anchors, t.base_date, t.night, tz)
            except timeexpr.ExprError as err:
                res.error = str(err)
                break
            res.total += 1
            try:
                start, end, next_day = evaluate_window(action, t, tz)
            except timeexpr.ExprError:
                res.invalid += 1
                res.invalid_example = res.invalid_example or {"key": t.key, "title": t.title}
                continue
            occurrence = {"key": t.key, "title": t.title, "start": start.isoformat(), "end": end.isoformat()}
            res.first = res.first or {**occurrence, "next_day": next_day}
            if next_day:
                res.next_day += 1
                res.next_day_example = res.next_day_example or occurrence
            if start < t.block.start:
                res.before_start += 1
                res.before_start_example = res.before_start_example or occurrence
            if end > t.block.end:
                res.after_end += 1
                res.after_end_example = res.after_end_example or occurrence
        results.append(res)
    return results


# ---------------------------------------------------------------- desired-state timeline


@dataclass(slots=True)
class Interval:
    entity_id: str
    start: datetime
    end: datetime
    state: str
    attrs: dict[str, Any]
    end_state: str
    priority: int
    instance_key: str
    routine_name: str
    action_id: str
    start_expr: str = ""
    end_expr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id, "start": self.start.isoformat(), "end": self.end.isoformat(),
            "start_expr": self.start_expr, "end_expr": self.end_expr,
            "state": self.state, "attrs": self.attrs, "end_state": self.end_state,
            "instance_key": self.instance_key, "routine_name": self.routine_name, "action_id": self.action_id,
        }


class Timeline:
    """Per-entity desired states over time; later/higher-priority layers win."""

    def __init__(self, instances: list[Instance]) -> None:
        self.intervals: dict[str, list[Interval]] = {}
        for inst in instances:
            if not inst.routine:
                continue
            for a in inst.actions:
                if a.disabled or a.error or not a.start or not a.end:
                    continue
                self.intervals.setdefault(a.entity_id, []).append(Interval(
                    entity_id=a.entity_id, start=a.start, end=a.end, state=a.state, attrs=a.attrs,
                    end_state=a.end_state, priority=PRIORITY[inst.target.part], instance_key=inst.target.key,
                    routine_name=inst.routine["name"], action_id=a.action_id,
                    start_expr=a.start_expr, end_expr=a.end_expr,
                ))
        self._bounds: dict[str, list[datetime]] = {}
        for entity_id, ivs in self.intervals.items():
            ivs.sort(key=lambda iv: (iv.start, iv.priority))
            self._bounds[entity_id] = sorted({t for iv in ivs for t in (iv.start, iv.end)})

    @property
    def entities(self) -> list[str]:
        return sorted(self.intervals)

    def desired_at(self, entity_id: str, t: datetime) -> Interval | None:
        best: Interval | None = None
        for iv in self.intervals.get(entity_id, ()):
            if iv.start > t:
                break
            if iv.start <= t < iv.end and (best is None or (iv.priority, iv.start) >= (best.priority, best.start)):
                best = iv
        return best

    def next_boundary(self, after: datetime) -> datetime | None:
        """Earliest boundary strictly after `after` across all entities."""
        best = None
        for bounds in self._bounds.values():
            i = bisect_right(bounds, after)
            if i < len(bounds) and (best is None or bounds[i] < best):
                best = bounds[i]
        return best

    def entities_with_boundary(self, t: datetime) -> list[str]:
        return [e for e, bounds in self._bounds.items() if t in bounds]

    def ending_at(self, entity_id: str, t: datetime) -> Interval | None:
        """The interval that was in effect just before t, if it ends exactly at t."""
        ending = [iv for iv in self.intervals.get(entity_id, ()) if iv.end == t]
        if not ending:
            return None
        return max(ending, key=lambda iv: (iv.priority, iv.start))


# ---------------------------------------------------------------- boundaries / test mode


@dataclass(slots=True)
class BoundaryCommand:
    """What the executor does to one device at one boundary, and which row's time caused it."""

    entity_id: str
    state: str
    attrs: dict[str, Any]
    routine_name: str
    instance_key: str
    action_id: str
    cause: str  # "start": a row begins at this time; "end": a row ends (its end_state, or what it uncovers)
    expr: str  # the expression that produced this time, e.g. "candle_lighting-20m"
    reason: str  # for the activity log

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id, "state": self.state, "attrs": self.attrs,
            "routine_name": self.routine_name, "instance_key": self.instance_key, "action_id": self.action_id,
            "cause": self.cause, "expr": self.expr,
        }


def boundary_command(timeline: Timeline, entity_id: str, t: datetime) -> BoundaryCommand | None:
    """The command for `entity_id` at boundary `t`: the state now in effect, or the end state of what just ended."""
    desired = timeline.desired_at(entity_id, t)
    ending = timeline.ending_at(entity_id, t)
    if desired is not None:
        if desired.start == t or ending is None:
            cause, src = "start", desired
        else:  # e.g. a meal row ends and the baseline row underneath takes over again
            cause, src = "end", ending
        return BoundaryCommand(
            entity_id=entity_id, state=desired.state, attrs=desired.attrs, routine_name=desired.routine_name,
            instance_key=src.instance_key, action_id=src.action_id, cause=cause,
            expr=src.start_expr if cause == "start" else src.end_expr, reason=desired.routine_name,
        )
    if ending and ending.end_state in ("on", "off"):
        return BoundaryCommand(
            entity_id=entity_id, state=ending.end_state, attrs={}, routine_name=ending.routine_name,
            instance_key=ending.instance_key, action_id=ending.action_id, cause="end", expr=ending.end_expr,
            reason=f"End of {ending.routine_name}",
        )
    return None


def simulation_steps(timeline: Timeline, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Every scheduled device change from `start` to `end` (inclusive), grouped by time, for test mode."""
    steps: list[dict[str, Any]] = []
    t = timeline.next_boundary(start - timedelta(microseconds=1))
    while t is not None and t <= end:
        commands = [c for e in sorted(timeline.entities_with_boundary(t))
                    if (c := boundary_command(timeline, e, t)) is not None]
        if commands:
            steps.append({"at": t.isoformat(), "commands": [c.to_dict() for c in commands]})
        t = timeline.next_boundary(t)
    return steps
