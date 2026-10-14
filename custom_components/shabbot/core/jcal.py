"""Issur Melacha calendar: Yom Tov table, blocks and meal slots.

A *block* is a maximal run of consecutive days on which melacha is forbidden
(Shabbat and/or Yom Tov), running from candle lighting on the eve of the first
day until havdalah after the last day. Each day in a block yields two *slots*:
the night meal (evening before) and the day meal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from pyluach.dates import GregorianDate

from . import astro

NISSAN, SIVAN, TISHREI = 1, 3, 7


class Part(StrEnum):
    NIGHT = "night"
    DAY = "day"


@dataclass(frozen=True, slots=True)
class Holiday:
    name: str
    group: str


# (Hebrew month, day) -> holiday. Diaspora-only days are in _DIASPORA_ONLY.
_YOM_TOV: dict[tuple[int, int], Holiday] = {
    (TISHREI, 1): Holiday("Rosh Hashana I", "rosh_hashana"),
    (TISHREI, 2): Holiday("Rosh Hashana II", "rosh_hashana"),
    (TISHREI, 10): Holiday("Yom Kippur", "yom_kippur"),
    (TISHREI, 15): Holiday("Sukkot I", "sukkot"),
    (TISHREI, 16): Holiday("Sukkot II", "sukkot"),
    (TISHREI, 22): Holiday("Shmini Atzeret", "shmini_atzeret"),
    (TISHREI, 23): Holiday("Simchat Torah", "simchat_torah"),
    (NISSAN, 15): Holiday("Pesach I", "pesach"),
    (NISSAN, 16): Holiday("Pesach II", "pesach"),
    (NISSAN, 21): Holiday("Pesach VII", "pesach"),
    (NISSAN, 22): Holiday("Pesach VIII", "pesach"),
    (SIVAN, 6): Holiday("Shavuot I", "shavuot"),
    (SIVAN, 7): Holiday("Shavuot II", "shavuot"),
}
_DIASPORA_ONLY = {(TISHREI, 16), (TISHREI, 23), (NISSAN, 16), (NISSAN, 22), (SIVAN, 7)}
_ISRAEL_NAMES = {
    (TISHREI, 22): Holiday("Shmini Atzeret / Simchat Torah", "shmini_atzeret"),
    (SIVAN, 6): Holiday("Shavuot", "shavuot"),
}

HOLIDAY_GROUPS = ["rosh_hashana", "yom_kippur", "sukkot", "shmini_atzeret", "simchat_torah", "pesach", "shavuot"]


@dataclass(frozen=True, slots=True)
class Minhag:
    """User-configurable calculation customs."""

    candle_lighting_min: int = 18
    havdalah_mode: str = "degrees"  # "degrees" | "minutes"
    havdalah_degrees: float = 8.5
    havdalah_minutes: int = 50
    # End of a Yom Tov day that is not Shabbat, in minutes after shkia. Shabbat keeps havdalah_*.
    yom_tov_end_minutes: int = 42
    israel: bool = False
    use_elevation: bool = False
    # Early Shabbat (summer): light at this clock time when the normal candle lighting is later than
    # `early_shabbat_after`. Never before plag hamincha. Plain Shabbat only (not when it is also Yom Tov).
    early_shabbat_time: time | None = None
    early_shabbat_after: time | None = None


def yom_tov(d: date, israel: bool) -> Holiday | None:
    h = GregorianDate(d.year, d.month, d.day).to_heb()
    key = (h.month, h.day)
    if israel and key in _DIASPORA_ONLY:
        return None
    if israel and key in _ISRAEL_NAMES:
        return _ISRAEL_NAMES[key]
    return _YOM_TOV.get(key)


def hebrew_date_str(d: date) -> str:
    h = GregorianDate(d.year, d.month, d.day).to_heb()
    return f"{h.day} {h.month_name()} {h.year}"


def is_issur_day(d: date, israel: bool) -> bool:
    return d.weekday() == 5 or yom_tov(d, israel) is not None


def _floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def _ceil_minute(dt: datetime) -> datetime:
    if dt.second or dt.microsecond:
        return dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return dt


class Zmanim:
    """Zmanim for one civil date at one location."""

    def __init__(self, d: date, loc: astro.Location, minhag: Minhag) -> None:
        self.date = d
        self.loc = loc
        self.minhag = minhag
        ue = minhag.use_elevation
        self.sunrise = astro.sunrise(d, loc, ue)
        self.sunset = astro.sunset(d, loc, ue)
        self.alot = astro.sun_below_horizon(d, loc, 16.1, evening=False)
        self.tzeit = astro.sun_below_horizon(d, loc, 8.5, evening=True)
        # Halachic chatzot: midpoint of sunrise and sunset.
        self.chatzot = self.sunrise + (self.sunset - self.sunrise) / 2

    @property
    def candle_lighting(self) -> datetime:
        return _floor_minute(self.sunset - timedelta(minutes=self.minhag.candle_lighting_min))

    @property
    def havdalah(self) -> datetime:
        """End of Shabbat: the Shabbat havdalah setting. Not used for a weekday Yom Tov."""
        if self.minhag.havdalah_mode == "minutes":
            return _ceil_minute(self.sunset + timedelta(minutes=self.minhag.havdalah_minutes))
        t = astro.sun_below_horizon(self.date, self.loc, self.minhag.havdalah_degrees, evening=True)
        return _ceil_minute(t if t else self.sunset + timedelta(minutes=50))

    @property
    def yom_tov_end(self) -> datetime:
        """End of a Yom Tov day that is not Shabbat, a fixed number of minutes after shkia."""
        return _ceil_minute(self.sunset + timedelta(minutes=self.minhag.yom_tov_end_minutes))

    @property
    def issur_end(self) -> datetime:
        """When this day ends, if the next day does not begin at candle lighting.

        Shabbat, including Yom Tov on Shabbat, uses the Shabbat havdalah setting.
        Any other Yom Tov day uses ``yom_tov_end``.
        """
        return self.havdalah if self.date.weekday() == 5 else self.yom_tov_end

    @property
    def shaah_zmanit(self) -> timedelta:
        return (self.sunset - self.sunrise) / 12

    @property
    def mincha_gedola(self) -> datetime:
        return self.chatzot + self.shaah_zmanit / 2

    @property
    def plag(self) -> datetime:
        return self.sunset - self.shaah_zmanit * 1.25

    def anchors(self) -> dict[str, datetime]:
        return {
            "alot": self.alot,
            "sunrise": self.sunrise,
            "chatzot": self.chatzot,
            "mincha_gedola": self.mincha_gedola,
            "plag": self.plag,
            "candle_lighting": self.candle_lighting,
            "sunset": self.sunset,
            "tzeit": self.tzeit,
            "havdalah": self.havdalah,
        }


@dataclass(slots=True)
class Slot:
    """One meal period: the night or the day of an Issur Melacha day."""

    key: str  # "{issur day ISO}/{part}"
    day: date  # the Issur Melacha (civil) day this slot belongs to
    part: Part
    base_date: date  # civil date whose zmanim the slot's anchors use
    start: datetime
    end: datetime
    is_shabbat: bool
    holiday: Holiday | None
    day_in_block: int
    block_id: str
    anchors: dict[str, datetime] = field(default_factory=dict)
    # Anchors for "the next day", used when an end time falls before its start (e.g. sunset → sunrise).
    next_anchors: dict[str, datetime] = field(default_factory=dict)

    @property
    def title(self) -> str:
        names = []
        if self.holiday:
            names.append(self.holiday.name)
        if self.is_shabbat:
            names.insert(0, "Shabbat")
        label = " / ".join(names)
        return f"{label} — {'Night' if self.part is Part.NIGHT else 'Day'}"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "day": self.day.isoformat(),
            "part": self.part.value,
            "base_date": self.base_date.isoformat(),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "is_shabbat": self.is_shabbat,
            "is_yomtov": self.holiday is not None,
            "holiday": self.holiday.name if self.holiday else None,
            "holiday_group": self.holiday.group if self.holiday else None,
            "day_in_block": self.day_in_block,
            "block_id": self.block_id,
            "title": self.title,
            "anchors": {k: v.isoformat() for k, v in self.anchors.items() if v},
        }


@dataclass(slots=True)
class Block:
    id: str  # ISO date of the first Issur day
    days: list[date]
    start: datetime  # candle lighting on erev
    end: datetime  # havdalah after the last day
    slots: list[Slot]
    normal_start: datetime | None = None  # set when Shabbat starts early: the normal candle-lighting time

    @property
    def title(self) -> str:
        names: list[str] = []
        for s in self.slots:
            if s.holiday and s.holiday.name not in names:
                names.append(s.holiday.name)
        if any(s.is_shabbat for s in self.slots):
            names.insert(0, "Shabbat")
        return " + ".join(names)

    def anchors(self) -> dict[str, datetime]:
        return {"block_start": self.start, "block_end": self.end}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "days": [d.isoformat() for d in self.days],
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "normal_start": self.normal_start.isoformat() if self.normal_start else None,
            "slots": [s.to_dict() for s in self.slots],
        }


def _next_midnight(d: date, loc: astro.Location) -> datetime:
    n = d + timedelta(days=1)
    return datetime(n.year, n.month, n.day, tzinfo=loc.tzinfo)


def build_block(days: list[date], loc: astro.Location, minhag: Minhag) -> Block:
    block_id = days[0].isoformat()
    zm: dict[date, Zmanim] = {}

    def z(d: date) -> Zmanim:
        if d not in zm:
            zm[d] = Zmanim(d, loc, minhag)
        return zm[d]

    erev = days[0] - timedelta(days=1)
    normal_start = z(erev).candle_lighting
    block_start = _early_shabbat_start(days[0], z(erev), minhag) or normal_start
    block_end = z(days[-1]).issur_end

    slots: list[Slot] = []
    for i, d in enumerate(days):
        prev = d - timedelta(days=1)
        is_shabbat = d.weekday() == 5
        holiday = yom_tov(d, minhag.israel)
        # Night begins at candle lighting. A later night that is not Shabbat begins when the
        # previous day ends: Shabbat havdalah if that day was Shabbat, otherwise the Yom Tov
        # end offset. Into Shabbat, candles are always before sunset.
        if i == 0:  # noqa: SIM108 - nested ternary reads worse
            night_start = block_start
        else:
            night_start = z(prev).candle_lighting if is_shabbat else z(prev).issur_end
        day_start = z(d).sunrise
        day_end = block_end if i == len(days) - 1 else (
            z(d).candle_lighting if days[i + 1].weekday() == 5 else z(d).issur_end
        )
        common = dict(day=d, is_shabbat=is_shabbat, holiday=holiday, day_in_block=i + 1, block_id=block_id)
        # "havdalah" always means the real end of this Shabbat/Yom Tov. A night's "candle_lighting"
        # is when that night begins (after the previous day's end on a later Yom Tov night).
        fixed = {"block_start": block_start, "block_end": block_end, "havdalah": block_end}
        night_fixed = {**fixed, "slot_start": night_start, "slot_end": day_start}
        day_fixed = {**fixed, "slot_start": day_start, "slot_end": day_end}
        night_anchors = {**z(prev).anchors(), "midnight": _next_midnight(prev, loc), **night_fixed,
                         "candle_lighting": night_start}
        day_anchors = {**z(d).anchors(), "midnight": _next_midnight(d, loc), **day_fixed}
        nxt = d + timedelta(days=1)
        slots.append(Slot(key=f"{d.isoformat()}/night", part=Part.NIGHT, base_date=prev,
                          start=night_start, end=day_start, anchors=night_anchors,
                          next_anchors={**z(d).anchors(), "midnight": _next_midnight(d, loc), **night_fixed},
                          **common))
        slots.append(Slot(key=f"{d.isoformat()}/day", part=Part.DAY, base_date=d,
                          start=day_start, end=day_end, anchors=day_anchors,
                          next_anchors={**z(nxt).anchors(), "midnight": _next_midnight(nxt, loc), **day_fixed},
                          **common))
    return Block(id=block_id, days=days, start=block_start, end=block_end, slots=slots,
                 normal_start=normal_start if block_start != normal_start else None)


def _early_shabbat_start(first_day: date, erev: Zmanim, minhag: Minhag) -> datetime | None:
    """Early candle lighting for a plain Shabbat, or None to use the normal time."""
    if minhag.early_shabbat_time is None or first_day.weekday() != 5 or yom_tov(first_day, minhag.israel):
        return None
    normal = erev.candle_lighting
    after = minhag.early_shabbat_after or minhag.early_shabbat_time
    if normal.timetz().replace(tzinfo=None) <= after:
        return None
    early = datetime.combine(erev.date, minhag.early_shabbat_time, tzinfo=normal.tzinfo)
    early = max(early, _ceil_minute(erev.plag))  # Shabbat can't be accepted before plag hamincha
    return early if early < normal else None


def blocks_between(start: date, end: date, loc: astro.Location, minhag: Minhag) -> list[Block]:
    """All blocks with at least one Issur day in [start, end] (inclusive).

    Blocks that straddle the range edges are returned whole.
    """
    # Widen so a straddling block is complete (max block length is 3 days).
    d = start - timedelta(days=3)
    last = end + timedelta(days=3)
    runs: list[list[date]] = []
    current: list[date] = []
    while d <= last:
        if is_issur_day(d, minhag.israel):
            current.append(d)
        elif current:
            runs.append(current)
            current = []
        d += timedelta(days=1)
    if current:
        runs.append(current)
    return [build_block(run, loc, minhag) for run in runs if run[-1] >= start and run[0] <= end]


def block_at(moment: datetime, loc: astro.Location, minhag: Minhag) -> Block | None:
    """The block in effect at `moment`, if Issur Melacha is in effect."""
    local = moment.astimezone(loc.tzinfo).date()
    for b in blocks_between(local - timedelta(days=1), local + timedelta(days=1), loc, minhag):
        if b.start <= moment < b.end:
            return b
    return None


def round_half_minute(dt: datetime) -> datetime:
    """Round to the nearest minute (used only for display/comparison)."""
    return (dt + timedelta(seconds=30)).replace(second=0, microsecond=0)


__all__ = [
    "Block", "Holiday", "HOLIDAY_GROUPS", "Minhag", "Part", "Slot", "Zmanim",
    "block_at", "blocks_between", "build_block", "hebrew_date_str", "is_issur_day", "yom_tov",
]
