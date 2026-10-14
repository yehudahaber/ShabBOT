"""Announcement times: candle lighting, shkia, havdalah, Yom Tov chains, DST."""

from datetime import date, datetime, time, timedelta

import pytest

from custom_components.shabbot.core import announcements, astro, jcal

BROOKLYN = astro.Location(40.6501, -73.94958, "America/New_York", 18)
TZ = BROOKLYN.tzinfo


def _plan(day: date, minhag: jcal.Minhag | None = None, **settings):
    minhag = minhag or jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=60)
    blocks = [b for b in jcal.blocks_between(day, day, BROOKLYN, minhag) if day in b.days]
    assert len(blocks) == 1, blocks
    events = announcements.plan_announcements(
        blocks, minhag, announcements.options_from_settings(settings),
    )
    return blocks[0], events


def _by(events, kind: str, day: date | None = None, minutes: int | None = None):
    found = [
        e for e in events
        if e.kind == kind and (day is None or e.day == day) and (minutes is None or e.minutes == minutes)
    ]
    assert len(found) == 1, [(e.kind, e.day, e.minutes, e.nominal_at) for e in events if e.kind == kind]
    return found[0]


# ---------------------------------------------------------------- plain Shabbat


def test_plain_shabbat_countdown_and_motzei_text() -> None:
    block, events = _plan(date(2026, 10, 10))
    sunset = block.slots[0].anchors["sunset"]
    candle60 = _by(events, "candle", block.days[0], 60)
    assert candle60.nominal_at == block.start - timedelta(minutes=60)
    assert candle60.message == "60 minutes until candle lighting"
    assert _by(events, "candle", block.days[0], 5).message == "5 minutes until candle lighting"

    final = _by(events, "shkia_final", block.days[0])
    assert final.nominal_at == sunset - timedelta(minutes=1)
    assert final.message == "Shkia in one minute. Stop all melacha."
    # 18 minutes before sunset: a 60- or 30-minute shkia warning is still before candles.
    shkia_marks = [e.minutes for e in events if e.kind == "shkia" and e.day == block.days[0]]
    assert shkia_marks == [15, 5]
    assert all(e.nominal_at > block.start for e in events if e.kind in ("shkia", "shkia_final"))

    motzei = _by(events, "motzei")
    assert motzei.nominal_at == block.end
    assert motzei.minutes == 60
    assert motzei.message == "It's now 60 minutes after shkia and it's muttar to do melacha."
    assert not any(e.kind.startswith("yt_") for e in events)


@pytest.mark.parametrize("minutes", [42, 72])
def test_motzei_uses_configured_havdalah_minutes(minutes: int) -> None:
    minhag = jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=minutes)
    block, events = _plan(date(2026, 10, 10), minhag)
    motzei = _by(events, "motzei")
    assert motzei.nominal_at == block.end
    assert motzei.message == f"It's now {minutes} minutes after shkia and it's muttar to do melacha."


def test_degrees_mode_motzei_uses_the_actual_gap() -> None:
    minhag = jcal.Minhag()  # 8.5°; havdalah_minutes is not the clock
    block, events = _plan(date(2026, 10, 10), minhag)
    shkia = block.slots[-1].anchors["sunset"]
    spoken = round((block.end - shkia).total_seconds() / 60)
    motzei = _by(events, "motzei")
    assert motzei.nominal_at == block.end
    assert motzei.minutes == spoken
    assert str(spoken) in motzei.message
    assert spoken != minhag.havdalah_minutes


def test_shkia_mark_that_matches_the_final_warning_is_not_repeated() -> None:
    block, events = _plan(
        date(2026, 10, 10),
        announce_shkia_marks=[15, 5, 1],
        announce_shkia_final_min=1,
    )
    sunset = block.slots[0].anchors["sunset"]
    at_final = [e for e in events if e.day == block.days[0] and e.nominal_at == sunset - timedelta(minutes=1)]
    assert [e.kind for e in at_final] == ["shkia_final"]


def test_blank_template_skips_and_broken_template_falls_back() -> None:
    _, skipped = _plan(date(2026, 10, 10), announce_templates={"shkia_final": "  "})
    assert not any(e.kind == "shkia_final" for e in skipped)
    assert any(e.kind == "candle" for e in skipped)

    _, fallback = _plan(date(2026, 10, 10), announce_templates={"candle": "{minutes"})
    assert _by(fallback, "candle", minutes=60).message == "60 minutes until candle lighting"


def test_early_shabbat_countdown_follows_the_early_time_and_shkia_does_not() -> None:
    minhag = jcal.Minhag(
        havdalah_mode="minutes", havdalah_minutes=60,
        early_shabbat_time=time(19, 0), early_shabbat_after=time(19, 15),
    )
    block, events = _plan(date(2027, 6, 26), minhag)
    assert block.start == datetime(2027, 6, 25, 19, 0, tzinfo=TZ)
    assert _by(events, "candle", minutes=60).nominal_at == block.start - timedelta(minutes=60)
    sunset = block.slots[0].anchors["sunset"]
    assert sunset.hour >= 20  # June in Brooklyn; the early time is well before shkia
    final = _by(events, "shkia_final")
    assert final.nominal_at == sunset - timedelta(minutes=1)
    # 60 minutes before a late sunset is still after 7:00pm, so the shkia mark is spoken.
    assert _by(events, "shkia", minutes=60).nominal_at == sunset - timedelta(minutes=60)
    assert _by(events, "motzei").nominal_at == block.end


# ---------------------------------------------------------------- Yom Tov chains


def test_pesach_chain_keeps_issur_until_the_real_end() -> None:
    """Pesach 2027 in the diaspora: Thu YT, Fri YT, Sat Shabbat. One block."""
    block, events = _plan(date(2027, 4, 22))
    assert [d.isoformat() for d in block.days] == ["2027-04-22", "2027-04-23", "2027-04-24"]
    nights = [s for s in block.slots if s.part is jcal.Part.NIGHT]

    first = {e.kind for e in events if e.day == date(2027, 4, 22)}
    assert {"candle", "shkia", "shkia_final"} <= first
    assert not any(k.startswith("yt_") for k in first)

    # Friday night of Pesach II: after tzeit, existing flame. No shkia warning, no muttar.
    assert nights[1].start > nights[1].anchors["sunset"]
    second = [e for e in events if e.day == date(2027, 4, 23)]
    assert {e.kind for e in second} == {"yt_candle", "yt_candle_now"}
    now = _by(events, "yt_candle_now", date(2027, 4, 23))
    assert now.nominal_at == nights[1].start
    assert now.message == "Light candles now from an existing flame."
    assert _by(events, "yt_candle", date(2027, 4, 23), 30).message == (
        "30 minutes until candle lighting. Light from an existing flame."
    )

    # Into Shabbat: candles before shkia again, including the stop-melacha warning.
    assert nights[2].start < nights[2].anchors["sunset"]
    third = {e.kind for e in events if e.day == date(2027, 4, 24) and e.kind != "motzei"}
    assert {"candle", "shkia_final"} <= third
    assert not any(k.startswith("yt_") for k in third)

    motzei = [e for e in events if e.kind == "motzei"]
    assert len(motzei) == 1 and motzei[0].nominal_at == block.end
    assert motzei[0].message == "It's now 60 minutes after shkia and it's muttar to do melacha."


def test_shabbat_into_rosh_hashana_has_no_muttar_on_saturday_night() -> None:
    # Rosh Hashana 5787 begins on Shabbat 2026-09-12 and continues Sunday.
    block, events = _plan(date(2026, 9, 12), jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=72))
    assert block.days == [date(2026, 9, 12), date(2026, 9, 13)]
    nights = [s for s in block.slots if s.part is jcal.Part.NIGHT]
    assert nights[1].start > nights[1].anchors["sunset"]
    assert any(e.kind == "yt_candle" and e.day == date(2026, 9, 13) for e in events)
    # Nothing about lighting-before-shkia or stopping melacha after Saturday's sunset.
    assert not any(
        e.kind in ("candle", "shkia", "shkia_final") and e.nominal_at > nights[1].anchors["sunset"]
        for e in events
    )
    motzei = [e for e in events if e.kind == "motzei"]
    assert len(motzei) == 1
    assert motzei[0].nominal_at == block.end
    assert motzei[0].message == "It's now 72 minutes after shkia and it's muttar to do melacha."


def test_two_day_yom_tov_away_from_shabbat() -> None:
    minhag = jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=50)
    blocks = jcal.blocks_between(date(2026, 1, 1), date(2027, 6, 1), BROOKLYN, minhag)
    block = next(
        b for b in blocks
        if len(b.days) == 2 and all(d.weekday() != 5 for d in b.days)
    )
    events = announcements.plan_announcements([block], minhag, announcements.options_from_settings({}))
    assert any(e.kind == "candle" and e.day == block.days[0] for e in events)
    assert any(e.kind == "yt_candle" and e.day == block.days[1] for e in events)
    assert not any(e.kind in ("candle", "shkia", "shkia_final") and e.day == block.days[1] for e in events)
    assert _by(events, "motzei").nominal_at == block.end
    assert "50 minutes" in _by(events, "motzei").message


def test_israel_one_day_pesach_has_no_second_night() -> None:
    minhag = jcal.Minhag(israel=True, havdalah_mode="minutes", havdalah_minutes=42)
    block, events = _plan(date(2027, 4, 22), minhag)
    assert block.days == [date(2027, 4, 22)]
    assert not any(e.kind.startswith("yt_") for e in events)
    assert _by(events, "motzei").message == "It's now 42 minutes after shkia and it's muttar to do melacha."


# ---------------------------------------------------------------- lead and DST


def test_lead_groups_players_and_skips_the_past() -> None:
    _, events = _plan(date(2026, 10, 10))
    event = _by(events, "candle", minutes=60)
    calls = announcements.schedule_announcements(
        [event],
        players=["media_player.kitchen", "media_player.den", "media_player.loft"],
        lead_seconds=8,
        player_leads={"media_player.den": 15, "media_player.loft": 8},
        not_before=event.nominal_at - timedelta(hours=3),
    )
    by_lead = {call.lead_seconds: call for call in calls}
    assert set(by_lead) == {8, 15}
    assert by_lead[8].players == ("media_player.kitchen", "media_player.loft")
    assert by_lead[15].players == ("media_player.den",)
    assert (event.nominal_at - by_lead[8].fire_at).total_seconds() == 8
    assert (event.nominal_at - by_lead[15].fire_at).total_seconds() == 15
    assert announcements.schedule_announcements(
        [event], players=["media_player.kitchen"], lead_seconds=8, player_leads={},
        not_before=event.nominal_at,
    ) == []


@pytest.mark.parametrize("day", [date(2026, 3, 7), date(2026, 3, 14), date(2026, 10, 31), date(2026, 11, 7)])
def test_offsets_stay_absolute_across_us_dst(day: date) -> None:
    """The Friday before and after the 2026 spring-forward and fall-back."""
    minhag = jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=72)
    block, events = _plan(day, minhag)
    candle = _by(events, "candle", block.days[0], 60)
    assert (block.start - candle.nominal_at).total_seconds() == 3600
    sunset = block.slots[0].anchors["sunset"]
    final = _by(events, "shkia_final", block.days[0])
    assert (sunset - final.nominal_at).total_seconds() == pytest.approx(60)
    motzei = _by(events, "motzei")
    assert motzei.nominal_at == block.end
    # Havdalah is rounded up to the next minute, so it is the configured offset, not a wall-clock guess.
    assert 72 * 60 <= (block.end - block.slots[-1].anchors["sunset"]).total_seconds() < 72 * 60 + 60


def test_lead_crosses_the_spring_forward_gap() -> None:
    """3:30am EDT minus 2 hours is 12:30am, not 1:30am: the 2 o'clock hour does not exist."""
    nominal = datetime(2026, 3, 8, 3, 30, tzinfo=TZ)
    event = announcements.Announcement(
        id="dst", kind="candle", block_id="x", day=date(2026, 3, 8),
        nominal_at=nominal, minutes=0, message="hello",
    )
    (call,) = announcements.schedule_announcements(
        [event], players=["media_player.kitchen"], lead_seconds=120 * 60, player_leads={},
        not_before=nominal - timedelta(hours=5),
    )
    fire = call.fire_at.astimezone(TZ)
    assert (fire.hour, fire.minute) == (0, 30)
    assert (nominal.timestamp() - fire.timestamp()) == 120 * 60


def test_lead_crosses_the_fall_back_fold() -> None:
    """2:30am after the clocks repeat is 90 minutes after 1:00am EST, not the earlier 1:00am EDT."""
    nominal = datetime(2026, 11, 1, 2, 30, tzinfo=TZ)
    event = announcements.Announcement(
        id="dst", kind="motzei", block_id="x", day=date(2026, 11, 1),
        nominal_at=nominal, minutes=0, message="hello",
    )
    (call,) = announcements.schedule_announcements(
        [event], players=["media_player.kitchen"], lead_seconds=90 * 60, player_leads={},
        not_before=nominal - timedelta(hours=5),
    )
    fire = call.fire_at.astimezone(TZ)
    assert (fire.hour, fire.minute) == (1, 0)
    assert fire.utcoffset() == timedelta(hours=-5)
    assert (nominal.timestamp() - fire.timestamp()) == 90 * 60
