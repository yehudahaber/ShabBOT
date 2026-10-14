"""Time expressions, rule resolution and the desired-state timeline."""

from datetime import date, datetime, timedelta

import pytest

from custom_components.shabbot.core import astro, jcal, planner, timeexpr

BROOKLYN = astro.Location(40.6501, -73.94958, "America/New_York", 18)
TZ = BROOKLYN.tzinfo
MINHAG = jcal.Minhag()


def _slot(day: date, part: str) -> jcal.Slot:
    (block,) = jcal.blocks_between(day, day, BROOKLYN, MINHAG)
    return next(s for s in block.slots if s.key == f"{day.isoformat()}/{part}")


def _eval(expr: str, slot: jcal.Slot) -> datetime:
    return timeexpr.evaluate(expr, slot.anchors, slot.base_date, slot.part is jcal.Part.NIGHT, TZ)


# ---------------------------------------------------------------- time expressions

FRI_NIGHT = date(2026, 10, 10)  # Shabbat Bereshit


def test_offsets_and_clock_times() -> None:
    slot = _slot(FRI_NIGHT, "night")
    sunset = slot.anchors["sunset"]
    assert sunset.date() == date(2026, 10, 9)
    assert _eval("sunset+18m", slot) == sunset + timedelta(minutes=18)
    assert _eval("sunset + 2h", slot) == sunset + timedelta(hours=2)
    assert _eval("Sunset+1h30m-5min", slot) == sunset + timedelta(minutes=85)
    assert _eval("11:45pm", slot) == datetime(2026, 10, 9, 23, 45, tzinfo=TZ)
    assert _eval("23:45", slot) == datetime(2026, 10, 9, 23, 45, tzinfo=TZ)
    # Night slots: morning clock times roll to the next day.
    assert _eval("1:30am", slot) == datetime(2026, 10, 10, 1, 30, tzinfo=TZ)
    assert _eval("midnight", slot) == datetime(2026, 10, 10, 0, 0, tzinfo=TZ)
    assert _eval("candles", slot) == slot.anchors["candle_lighting"]
    assert _eval("max(sunset+18m, 7pm)", slot) == datetime(2026, 10, 9, 19, 0, tzinfo=TZ)
    assert _eval("min(sunset+18m, 7pm)", slot) == sunset + timedelta(minutes=18)


def test_day_slot_clock_times() -> None:
    slot = _slot(FRI_NIGHT, "day")
    assert _eval("11:30am", slot) == datetime(2026, 10, 10, 11, 30, tzinfo=TZ)
    assert _eval("havdalah", slot) == slot.anchors["havdalah"]


@pytest.mark.parametrize("bad", ["sunrize", "sunset+", "sunset 18m", "25:00", "max(sunset", "sunset+18x", ""])
def test_invalid_expressions(bad: str) -> None:
    with pytest.raises(timeexpr.ExprError):
        timeexpr.validate(bad)


# ---------------------------------------------------------------- resolution


def _action(aid: str, entity: str, start: str, end: str, state: str = "on") -> dict:
    return {"id": aid, "entity_id": entity, "state": state, "start": start, "end": end}


CONFIG = {
    "routines": {
        "std_night": {"id": "std_night", "name": "Standard Friday night", "part": "night", "actions": [
            _action("a1", "light.chandelier", "sunset+18m", "11:45pm"),
            _action("a2", "switch.hotplate", "sunset", "sunset+2h"),
            _action("a3", "light.living_room", "sunset", "midnight"),
        ]},
        "hosting": {"id": "hosting", "name": "Friday night hosting", "part": "night", "actions": [
            _action("h1", "light.chandelier", "sunset+18m", "1:00am"),
        ]},
        "away": {"id": "away", "name": "Away", "part": "night", "actions": []},
        "yt_night": {"id": "yt_night", "name": "Yom Tov home", "part": "night", "actions": []},
        "lunch": {"id": "lunch", "name": "Lunch", "part": "day", "actions": [
            _action("l1", "switch.hotplate", "7am", "2pm"),
        ]},
        "baseline": {"id": "baseline", "name": "Baseline", "part": "block", "actions": [
            _action("b1", "light.bedroom", "block_start", "block_end", state="off"),
            _action("b2", "light.chandelier", "block_start", "block_end", state="off"),
        ]},
    },
    "rules": [
        {"id": "r1", "name": "Shabbat night", "part": "night", "match": {"day_type": "shabbat"}, "routine_id": "std_night"},
        {"id": "r2", "name": "YT night", "part": "night", "match": {"day_type": "yomtov"}, "routine_id": "yt_night"},
        {"id": "r3", "name": "Pesach 2nd night", "part": "night",
         "match": {"holiday_group": "pesach", "day_in_block": 2}, "routine_id": "hosting"},
        {"id": "r4", "name": "Lunch", "part": "day", "match": {}, "routine_id": "lunch"},
        {"id": "r5", "name": "Baseline", "part": "block", "match": {}, "routine_id": "baseline"},
    ],
    "modes": [],
    "assignments": {},
}


def _target(key: str) -> planner.Target:
    day = date.fromisoformat(key.split("/")[0])
    (block,) = jcal.blocks_between(day, day, BROOKLYN, MINHAG)
    return next(t for t in planner.targets_for_block(block) if t.key == key)


def test_rule_specificity() -> None:
    # Pesach 2027: Thu (YT1), Fri (YT2), Sat (Shabbat). Night 2 has the specific Pesach rule.
    assert planner.resolve(_target("2027-04-22/night"), CONFIG).routine_id == "yt_night"
    assert planner.resolve(_target("2027-04-23/night"), CONFIG).routine_id == "hosting"
    assert planner.resolve(_target("2027-04-24/night"), CONFIG).routine_id == "std_night"  # first matching rule wins ties
    assert planner.resolve(_target("2027-04-22/block"), CONFIG).routine_id == "baseline"


def test_assignment_overrides_and_skip() -> None:
    cfg = {**CONFIG, "assignments": {
        "2026-10-10/night": {"routine_id": "hosting"},
        "2026-10-10/day": {"skip": True},
    }}
    res = planner.resolve(_target("2026-10-10/night"), cfg)
    assert (res.routine_id, res.source, res.default_routine_id) == ("hosting", "assignment", "std_night")
    res = planner.resolve(_target("2026-10-10/day"), cfg)
    assert (res.routine_id, res.source, res.default_routine_id) == (None, "skipped", "lunch")
    # The general rule still applies the following week.
    assert planner.resolve(_target("2026-10-17/day"), cfg).routine_id == "lunch"


def test_modes_open_ended_and_bounded() -> None:
    cfg = {**CONFIG, "modes": [
        {"id": "m1", "name": "Summer", "enabled": True, "start": "2026-10-15", "end": None,
         "night": "away", "day": "none", "block": None},
    ]}
    assert planner.resolve(_target("2026-10-10/night"), cfg).routine_id == "std_night"
    res = planner.resolve(_target("2026-10-17/night"), cfg)
    assert (res.routine_id, res.source, res.source_name) == ("away", "mode", "Summer")
    assert planner.resolve(_target("2026-10-17/day"), cfg).routine_id is None
    assert planner.resolve(_target("2026-10-17/block"), cfg).routine_id == "baseline"  # None falls through
    cfg["modes"][0]["end"] = "2026-10-20"
    assert planner.resolve(_target("2026-10-24/night"), cfg).routine_id == "std_night"


# ---------------------------------------------------------------- timeline


def test_timeline_layers_meal_over_baseline() -> None:
    _, instances = planner.plan_range(date(2026, 10, 10), date(2026, 10, 10), BROOKLYN, MINHAG, CONFIG)
    tl = planner.Timeline(instances)
    night = _slot(FRI_NIGHT, "night")
    sunset = night.anchors["sunset"]
    # Before sunset+18m the baseline keeps the chandelier off; then the meal routine turns it on.
    assert tl.desired_at("light.chandelier", sunset + timedelta(minutes=5)).state == "off"
    assert tl.desired_at("light.chandelier", sunset + timedelta(minutes=30)).state == "on"
    assert tl.desired_at("light.chandelier", datetime(2026, 10, 9, 23, 50, tzinfo=TZ)).state == "off"
    # Hotplate: on for 2h, then unmanaged with a one-shot "off".
    assert tl.desired_at("switch.hotplate", sunset + timedelta(hours=1)).state == "on"
    assert tl.desired_at("switch.hotplate", sunset + timedelta(hours=3)) is None
    ending = tl.ending_at("switch.hotplate", sunset + timedelta(hours=2))
    assert ending is not None and ending.end_state == "off"
    nb = tl.next_boundary(sunset)
    assert nb == sunset + timedelta(minutes=18)
    assert "light.chandelier" in tl.entities_with_boundary(nb)


def test_instance_span_and_errors() -> None:
    cfg = {**CONFIG, "routines": {**CONFIG["routines"], "bad": {"id": "bad", "name": "Bad", "part": "night",
           "actions": [_action("x", "light.x", "slot_end", "slot_start"), _action("y", "light.y", "nope", "sunset"),
                       _action("z", "light.z", "sunset", "sunset-1h")]}},
           "assignments": {"2026-10-10/night": {"routine_id": "bad"}}}
    _, instances = planner.plan_range(date(2026, 10, 10), date(2026, 10, 10), BROOKLYN, MINHAG, cfg)
    inst = next(i for i in instances if i.target.key == "2026-10-10/night")
    assert inst.actions[0].error == "End is not after start"
    assert "Unknown time" in inst.actions[1].error
    assert inst.actions[2].error is None and inst.actions[2].next_day  # read as the next evening (23 h)
    std = next(i for i in instances if i.target.key == "2026-10-10/day")
    assert std.start == datetime(2026, 10, 10, 7, 0, tzinfo=TZ)
    assert std.end == datetime(2026, 10, 10, 14, 0, tzinfo=TZ)


def test_check_actions_reports_overnight_and_invalid_rows() -> None:
    blocks = jcal.blocks_between(date(2026, 10, 5), date(2027, 10, 4), BROOKLYN, MINHAG)
    checks = planner.check_actions("night", [
        _action("ok", "light.a", "sunset+18m", "11:45pm"),
        _action("overnight", "light.b", "6:15pm", "5:00pm"),  # read as 5:00 PM the next day
        _action("morning", "light.c", "11pm", "1:00am"),  # morning clock times already mean the next morning
        _action("seasonal", "light.d", "sunset", "7pm"),  # evening in winter, crosses midnight in summer
        _action("never", "light.e", "slot_end", "slot_start"),  # fixed times that can't fit
        _action("bad", "light.f", "sunsett", "midnight"),
    ], blocks, TZ)
    ok, overnight, morning, seasonal, never, bad = checks
    assert ok.total > 50 and ok.next_day == 0 and ok.invalid == 0
    assert overnight.next_day == overnight.total and overnight.invalid == 0
    assert morning.next_day == 0
    assert 0 < seasonal.next_day < seasonal.total
    assert seasonal.next_day_example and seasonal.next_day_example["key"] >= "2027-03"
    assert never.always_invalid
    assert bad.error and "Unknown time" in bad.error and bad.total == 0


def test_sunset_to_sunrise_crosses_midnight() -> None:
    cfg = {**CONFIG, "routines": {**CONFIG["routines"], "dark": {"id": "dark", "name": "Dark", "part": "night",
           "actions": [_action("bd", "light.bedroom", "sunset", "sunrise", state="off")]}},
           "assignments": {"2026-10-10/night": {"routine_id": "dark"}}}
    _, instances = planner.plan_range(date(2026, 10, 10), date(2026, 10, 10), BROOKLYN, MINHAG, cfg)
    (a,) = next(i for i in instances if i.target.key == "2026-10-10/night").actions
    assert a.error is None and a.next_day
    assert a.start.date() == date(2026, 10, 9) and a.start.hour == 18
    assert a.end.date() == date(2026, 10, 10) and a.end.hour == 7  # Saturday's sunrise, not Friday's


def test_havdalah_and_candle_lighting_in_meal_routines() -> None:
    # Pesach 2027: Thu (YT1), Fri (YT2), Sat (Shabbat).
    (block,) = jcal.blocks_between(date(2027, 4, 22), date(2027, 4, 22), BROOKLYN, MINHAG)
    night1, day1, night2 = block.slots[0], block.slots[1], block.slots[2]
    for slot in (night1, day1, night2):
        assert slot.anchors["havdalah"] == block.end  # always the real end of this Yom Tov/Shabbat
    assert night1.anchors["candle_lighting"] == block.start
    assert night2.anchors["candle_lighting"] == night2.start  # 2nd night: after the previous day's Yom Tov end
    assert night2.anchors["candle_lighting"] > night2.anchors["sunset"]


def test_instance_span_ignores_backwards_rows() -> None:
    cfg = {**CONFIG, "routines": {**CONFIG["routines"], "mixed": {"id": "mixed", "name": "Mixed", "part": "night",
           "actions": [_action("bw", "light.x", "slot_end", "slot_start")]}},
           "assignments": {"2026-10-10/night": {"routine_id": "mixed"}}}
    _, instances = planner.plan_range(date(2026, 10, 10), date(2026, 10, 10), BROOKLYN, MINHAG, cfg)
    inst = next(i for i in instances if i.target.key == "2026-10-10/night")
    assert inst.actions[0].error == "End is not after start"
    assert inst.end >= inst.start  # calendar events must never run backwards


def _baseline_cfg(*actions: dict) -> dict:
    return {**CONFIG, "routines": {**CONFIG["routines"], "baseline": {
        "id": "baseline", "name": "Baseline", "part": "block", "actions": list(actions)}}}


def _baseline_actions(day: date, cfg: dict) -> list[planner.PlannedAction]:
    _, instances = planner.plan_range(day, day, BROOKLYN, MINHAG, cfg)
    return next(i for i in instances if i.target.part == "block").actions


CLOSET_DAILY = {**_action("cl", "light.closet", "7:00am", "10:00am"), "repeat": "day"}


def test_every_day_row_runs_each_morning_of_two_day_yom_tov() -> None:
    # Pesach 2028 starts Monday night (Apr 10): Tuesday and Wednesday are Yom Tov.
    actions = _baseline_actions(date(2028, 4, 11), _baseline_cfg(CLOSET_DAILY))
    assert [(a.start, a.end) for a in actions] == [
        (datetime(2028, 4, 11, 7, 0, tzinfo=TZ), datetime(2028, 4, 11, 10, 0, tzinfo=TZ)),
        (datetime(2028, 4, 12, 7, 0, tzinfo=TZ), datetime(2028, 4, 12, 10, 0, tzinfo=TZ)),
    ]
    assert [a.occurrence_title for a in actions] == ["Pesach I — Day", "Pesach II — Day"]
    # The same row set to "once" only runs the first morning.
    once = _baseline_actions(date(2028, 4, 11), _baseline_cfg({**CLOSET_DAILY, "repeat": "once"}))
    assert [(a.start.date(), a.occurrence_key) for a in once] == [(date(2028, 4, 11), None)]


def test_every_day_row_runs_three_mornings_of_three_day_block() -> None:
    actions = _baseline_actions(date(2027, 4, 22), _baseline_cfg(CLOSET_DAILY))
    assert [a.start.date().isoformat() for a in actions] == ["2027-04-22", "2027-04-23", "2027-04-24"]
    tl = planner.Timeline(planner.plan_range(date(2027, 4, 22), date(2027, 4, 22), BROOKLYN, MINHAG,
                                             _baseline_cfg(CLOSET_DAILY))[1])
    assert tl.desired_at("light.closet", datetime(2027, 4, 23, 8, 0, tzinfo=TZ)).state == "on"
    assert tl.desired_at("light.closet", datetime(2027, 4, 23, 11, 0, tzinfo=TZ)) is None


def test_every_night_row_runs_each_night() -> None:
    night_off = {**_action("bd", "light.bedroom", "sunset", "sunrise", state="off"), "repeat": "night"}
    actions = _baseline_actions(date(2027, 4, 22), _baseline_cfg(night_off))
    assert len(actions) == 3 and all(a.next_day and a.error is None for a in actions)
    assert [a.end.date().isoformat() for a in actions] == ["2027-04-22", "2027-04-23", "2027-04-24"]


def test_check_actions_respects_repeat_and_flags_outside_block() -> None:
    blocks = jcal.blocks_between(date(2026, 10, 5), date(2027, 10, 4), BROOKLYN, MINHAG)
    daily, nightly_wrong, early = planner.check_actions("block", [
        CLOSET_DAILY,
        {**_action("x", "light.x", "sunset", "sunrise"), "repeat": "day"},  # last day runs past havdalah
        _action("y", "light.y", "3:00pm", "havdalah"),  # "once": Friday 3 PM is before Shabbat
    ], blocks, TZ)
    assert daily.total > len(blocks) and daily.before_start == 0 and daily.after_end == 0
    assert nightly_wrong.after_end > 0
    assert early.before_start == early.total


def test_one_row_can_control_several_devices() -> None:
    row = {"id": "multi", "entity_ids": ["light.chandelier", "light.living_room", "light.chandelier"],
           "state": "on", "start": "sunset", "end": "11pm"}
    cfg = {**CONFIG, "routines": {**CONFIG["routines"], "std_night": {**CONFIG["routines"]["std_night"],
                                                                         "actions": [row]}}}
    _, instances = planner.plan_range(date(2026, 10, 10), date(2026, 10, 10), BROOKLYN, MINHAG, cfg)
    actions = next(i for i in instances if i.target.key == "2026-10-10/night").actions
    assert [a.entity_id for a in actions] == ["light.chandelier", "light.living_room"]  # de-duplicated
    assert len({(a.start, a.end) for a in actions}) == 1
    # Rows saved before multi-device support still work.
    assert planner.action_entities({"entity_id": "light.x"}) == ["light.x"]
