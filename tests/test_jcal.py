"""Check blocks, candle lighting and havdalah against hebcal.com reference data."""

from datetime import date, datetime, time, timedelta
import json
from pathlib import Path

import pytest

from custom_components.shabbot.core import astro, jcal

FIXTURES = Path(__file__).parent / "fixtures"
BROOKLYN = astro.Location(40.6501, -73.94958, "America/New_York", 18)
JERUSALEM = astro.Location(31.76904, 35.21633, "Asia/Jerusalem", 786)


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())["items"]


def _expected(items: list[dict]) -> tuple[list[datetime], list[datetime], set[date]]:
    candles = [datetime.fromisoformat(i["date"]) for i in items if i["category"] == "candles"]
    havdalah = [datetime.fromisoformat(i["date"]) for i in items if i["category"] == "havdalah"]
    yomtov = {date.fromisoformat(i["date"]) for i in items if i.get("yomtov")}
    return candles, havdalah, yomtov


CASES = [
    ("hebcal_brooklyn_2026.json", BROOKLYN, jcal.Minhag(), 2026),
    ("hebcal_brooklyn_2027.json", BROOKLYN, jcal.Minhag(), 2027),
    ("hebcal_jerusalem_2027.json", JERUSALEM, jcal.Minhag(candle_lighting_min=40, israel=True), 2027),
]


@pytest.mark.parametrize(("fixture", "loc", "minhag", "year"), CASES)
def test_yom_tov_days_match_hebcal(fixture, loc, minhag, year) -> None:
    _, _, expected = _expected(_load(fixture))
    d, ours = date(year, 1, 1), set()
    while d.year == year:
        if jcal.yom_tov(d, minhag.israel):
            ours.add(d)
        d += timedelta(days=1)
    assert ours == expected


@pytest.mark.parametrize(("fixture", "loc", "minhag", "year"), CASES)
def test_block_boundaries_match_hebcal(fixture, loc, minhag, year) -> None:
    candles, havdalah, _ = _expected(_load(fixture))
    blocks = jcal.blocks_between(date(year, 1, 2), date(year, 12, 29), loc, minhag)
    in_range = lambda t: date(year, 1, 2) <= t.date() <= date(year, 12, 28)  # noqa: E731
    # Erev candle lighting still matches hebcal. Shabbat havdalah does too.
    for block in blocks:
        if in_range(block.start):
            assert any(abs((block.start - c).total_seconds()) <= 60 for c in candles), block.start
        if in_range(block.end) and block.days[-1].weekday() == 5:
            assert any(abs((block.end - h).total_seconds()) <= 60 for h in havdalah), block.end
    # A weekday Yom Tov ends at the minute offset, not hebcal's sun-angle havdalah.
    nights = [s for b in blocks for s in b.slots if s.part is jcal.Part.NIGHT]
    for c in filter(in_range, candles):
        if any(abs((c - s.start).total_seconds()) <= 60 for s in nights):
            continue
        assert any(
            s.start > s.anchors["sunset"] and abs((s.start - c).total_seconds()) < 3 * 3600 for s in nights
        ), c


def test_pesach_2027_three_day_block() -> None:
    blocks = jcal.blocks_between(date(2027, 4, 22), date(2027, 4, 22), BROOKLYN, jcal.Minhag())
    assert len(blocks) == 1
    b = blocks[0]
    assert [d.isoformat() for d in b.days] == ["2027-04-22", "2027-04-23", "2027-04-24"]
    assert b.title == "Shabbat + Pesach I + Pesach II"
    nights = [s for s in b.slots if s.part is jcal.Part.NIGHT]
    # Night 2 (YT after YT) starts after tzeit; night 3 (into Shabbat) at candle lighting before sunset.
    assert nights[1].start > nights[1].anchors["sunset"]
    assert nights[2].start < nights[2].anchors["sunset"]
    assert [s.day_in_block for s in nights] == [1, 2, 3]


def test_block_at() -> None:
    fri_evening = datetime(2026, 10, 9, 20, 0, tzinfo=BROOKLYN.tzinfo)
    b = jcal.block_at(fri_evening, BROOKLYN, jcal.Minhag())
    assert b is not None and b.id == "2026-10-10"
    assert jcal.block_at(datetime(2026, 10, 7, 12, tzinfo=BROOKLYN.tzinfo), BROOKLYN, jcal.Minhag()) is None


def test_zmanim_against_hebcal() -> None:
    times = json.loads((FIXTURES / "zmanim_brooklyn_2026q4.json").read_text())["times"]
    for key, attr in [("sunrise", "sunrise"), ("sunset", "sunset"), ("tzeit85deg", "tzeit"),
                      ("chatzot", "chatzot"), ("alotHaShachar", "alot"), ("plagHaMincha", "plag")]:
        for ds, v in times[key].items():
            ours = getattr(jcal.Zmanim(date.fromisoformat(ds), BROOKLYN, jcal.Minhag()), attr)
            assert abs((ours - datetime.fromisoformat(v)).total_seconds()) <= 5, (key, ds)


EARLY = jcal.Minhag(early_shabbat_time=time(19, 0), early_shabbat_after=time(19, 15))


def _block(day: date, minhag: jcal.Minhag) -> jcal.Block:
    (block,) = jcal.blocks_between(day, day, BROOKLYN, minhag)
    return block


def test_early_shabbat_in_summer() -> None:
    normal = _block(date(2027, 6, 26), jcal.Minhag())
    early = _block(date(2027, 6, 26), EARLY)
    assert normal.start.time() > time(20, 0)
    assert early.start == datetime(2027, 6, 25, 19, 0, tzinfo=BROOKLYN.tzinfo)
    assert early.normal_start == normal.start
    night = early.slots[0]
    assert night.start == early.start and night.anchors["candle_lighting"] == early.start
    assert night.anchors["sunset"] == normal.slots[0].anchors["sunset"]  # zmanim themselves don't move
    assert jcal.block_at(datetime(2027, 6, 25, 19, 30, tzinfo=BROOKLYN.tzinfo), BROOKLYN, EARLY) is not None


def test_early_shabbat_not_in_winter_or_below_cutoff() -> None:
    assert _block(date(2026, 12, 12), EARLY).normal_start is None
    # Candle lighting 7:04 PM on Fri 2026-09-04 is before the 7:15 PM cutoff: normal time.
    sept = _block(date(2026, 9, 5), EARLY)
    assert sept.normal_start is None and sept.start == _block(date(2026, 9, 5), jcal.Minhag()).start


def test_early_shabbat_never_before_plag() -> None:
    six = jcal.Minhag(early_shabbat_time=time(18, 0), early_shabbat_after=time(18, 15))
    block = _block(date(2027, 6, 26), six)
    plag = jcal.Zmanim(date(2027, 6, 25), BROOKLYN, six).plag
    assert block.start > datetime(2027, 6, 25, 18, 0, tzinfo=BROOKLYN.tzinfo)
    assert block.start - plag < timedelta(minutes=1)


def _offset(end: datetime, sunset: datetime, minutes: int) -> None:
    gap = (end - sunset).total_seconds()
    assert minutes * 60 <= gap < minutes * 60 + 60, gap


def test_yom_tov_end_is_separate_from_shabbat_havdalah() -> None:
    """Weekday Yom Tov ends at yom_tov_end_minutes. Shabbat keeps its own setting."""
    minhag = jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=60, yom_tov_end_minutes=42)
    pesach = _block(date(2027, 4, 22), minhag)
    nights = [s for s in pesach.slots if s.part is jcal.Part.NIGHT]
    # Thu YT → Fri YT: Yom Tov end. Fri → Shabbat: candle lighting, before sunset.
    _offset(nights[1].start, nights[1].anchors["sunset"], 42)
    assert nights[2].start < nights[2].anchors["sunset"]
    _offset(pesach.end, pesach.slots[-1].anchors["sunset"], 60)
    # Day schedules stop at the same boundary the night starts on.
    assert pesach.slots[1].end == nights[1].start

    rh = _block(date(2026, 9, 12), minhag)
    rh_nights = [s for s in rh.slots if s.part is jcal.Part.NIGHT]
    _offset(rh_nights[1].start, rh_nights[1].anchors["sunset"], 60)
    _offset(rh.end, rh.slots[-1].anchors["sunset"], 42)
    assert rh.slots[1].end == rh_nights[1].start

    # Sun-angle Shabbat havdalah does not move the weekday Yom Tov end.
    degrees = jcal.Minhag(yom_tov_end_minutes=50)
    shavuot = _block(date(2026, 5, 22), degrees)  # Friday Shavuot runs into Shabbat; block ends Saturday
    assert shavuot.days[-1].weekday() == 5
    angle = jcal.Zmanim(shavuot.days[-1], BROOKLYN, degrees).havdalah
    assert shavuot.end == angle
    weekday = next(
        b for b in jcal.blocks_between(date(2026, 1, 1), date(2026, 12, 31), BROOKLYN, degrees)
        if b.days[-1].weekday() != 5
    )
    _offset(weekday.end, weekday.slots[-1].anchors["sunset"], 50)


def test_early_shabbat_skips_yom_tov_on_shabbat() -> None:
    # Rosh Hashana 5787 begins Shabbat 2026-09-12; early Shabbat is for plain Shabbatot only.
    early = jcal.Minhag(early_shabbat_time=time(18, 30), early_shabbat_after=time(18, 45))
    block = _block(date(2026, 9, 12), early)
    assert block.normal_start is None
    # Second night of Yom Tov still starts after tzeit.
    assert block.slots[2].start > block.slots[2].anchors["sunset"]
