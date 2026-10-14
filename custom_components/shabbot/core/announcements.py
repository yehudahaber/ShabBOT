"""Spoken announcements for erev Shabbat, erev Yom Tov, shkia, and motzaei.

Times come from the blocks the calendar already built, so candle lighting,
early Shabbat, and havdalah stay consistent with the device schedules.

Which evenings speak
--------------------
Each night slot is one of two kinds. The split is the one ``jcal.build_block``
already uses (a night that continues into Shabbat starts at candle lighting;
a later Yom Tov night starts at the previous day's havdalah, after tzeit):

* **Before shkia** — the slot starts at or before that evening's sunset. This
  is the first night of a block (erev Shabbat or erev Yom Tov, including an
  early Shabbat) and any later night that enters Shabbat, such as Yom Tov
  flowing into Shabbat. Candles are lit before sunset. Speak the
  candle-lighting countdown, then the shkia countdown for marks that fall
  *after* candle lighting, then the final "stop all melacha" warning
  (default: one minute before shkia). A shkia mark that would land before
  candles are lit is skipped: that stretch is the candle countdown's job.

* **Next-meal preparation** — the slot starts after sunset. This is a second
  (or later) Yom Tov night that is not Shabbat. The previous day has ended, so
  melacha needed for the next meal may begin. There is no shkia countdown and
  no "stop all melacha". Its own minute marks count down to that moment, and
  one announcement fires when preparation may begin. The moment is the previous
  day's end: Shabbat havdalah if that day was Shabbat, otherwise the Yom Tov
  end offset.

Each group (candle countdown, shkia countdown, the final warning, motzaei,
and next-meal preparation) can be switched off on its own. A missing group
flag stays on, so settings saved before the switches existed keep speaking.

Motzaei
-------
"Muttar" is spoken once, at ``block.end``. It is not spoken on an evening that
is still inside the block, so a Yom Tov that runs into Shabbat, or a two-day
Yom Tov, never says melacha is permitted while it is still forbidden. The
number in the sentence is the offset that day actually used. Shabbat uses the
Shabbat havdalah setting (the configured minutes, or the rounded sun-angle
gap). A block that ends on a Yom Tov which is not Shabbat uses the Yom Tov
end setting.

Latency
-------
``nominal_at`` is when the words should be heard. ``schedule_announcements``
fires that many real seconds earlier (one global lead, with an optional
per-player override) so TTS generation and speaker buffering can finish first.
The lead is subtracted in UTC, so a daylight-saving gap cannot shorten it.
A call whose fire time is already past is dropped: a late "60 minutes until…"
is worse than silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import jcal

CANDLE = "candle"
SHKIA = "shkia"
SHKIA_FINAL = "shkia_final"
MOTZEI = "motzei"
YT_CANDLE = "yt_candle"
YT_CANDLE_NOW = "yt_candle_now"

TEMPLATE_KINDS = (CANDLE, SHKIA, SHKIA_FINAL, MOTZEI, YT_CANDLE, YT_CANDLE_NOW)
MARK_MAX = 12 * 60
LEAD_MAX = 300

DEFAULT_TEMPLATES: dict[str, str] = {
    "candle": "{minutes} {unit} until candle lighting",
    "shkia": "{minutes} {unit} until shkia",
    "shkia_final": "Shkia in {minutes_words}. Stop all melacha.",
    "motzei": "It's now {minutes} {unit} after shkia and it's muttar to do melacha.",
    "yt_candle": "{minutes} {unit} until you can start preparing for the next meal",
    "yt_candle_now": "You can now start preparing for the next meal.",
}
# Sentences from the first draft of this branch. Treated as unset so the preparation wording takes over.
_RETIRED_TEMPLATES = {
    "yt_candle": "{minutes} {unit} until candle lighting. Light from an existing flame.",
    "yt_candle_now": "Light candles now from an existing flame.",
}
DEFAULT_CANDLE_MARKS = (60, 30, 15, 5)
DEFAULT_SHKIA_MARKS = (60, 30, 15, 5)
DEFAULT_YT_MARKS = (60, 30, 15, 5)

# Panel switches. yt_candle also covers the sentence spoken when preparation may begin.
GROUP_KEYS = (CANDLE, SHKIA, SHKIA_FINAL, MOTZEI, YT_CANDLE)

# Merged into the integration settings. Nested values are replaced wholesale on save.
ANNOUNCE_DEFAULTS: dict[str, Any] = {
    "announce_enabled": False,
    "announce_players": [],
    "announce_tts_entity": "",
    "announce_voice": "",
    "announce_language": "",
    "announce_lead_seconds": 0,
    "announce_player_leads": {},
    "announce_volume": None,
    "announce_candle_marks": list(DEFAULT_CANDLE_MARKS),
    "announce_shkia_marks": list(DEFAULT_SHKIA_MARKS),
    "announce_yt_marks": list(DEFAULT_YT_MARKS),
    "announce_shkia_final_min": 1,
    "announce_groups": {key: True for key in GROUP_KEYS},
    "announce_templates": dict(DEFAULT_TEMPLATES),
}

def shift(moment: datetime, seconds: float) -> datetime:
    """Move an instant by real seconds.

    Subtracting a timedelta from a ``zoneinfo`` datetime follows the wall clock,
    so a gap or a repeated hour (US DST) would make "60 minutes before" the wrong
    length. Going through the UTC timestamp keeps the offset exact.
    """
    # UTC has a fixed offset, so the timedelta is a real elapsed time and microseconds survive.
    return (moment.astimezone(UTC) + timedelta(seconds=seconds)).astimezone(moment.tzinfo)


_NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}


class _FormatMap(dict):
    """Unknown placeholders stay visible in the spoken sentence."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def minutes_words(minutes: int) -> str:
    """'one minute', 'five minutes', '42 minutes'. Zero is not a countdown mark."""
    n = abs(int(minutes))
    unit = "minute" if n == 1 else "minutes"
    if n == 0:
        return "less than a minute"
    word = _NUMBER_WORDS.get(n)
    return f"{word} {unit}" if word else f"{n} {unit}"


def render_template(template: str, fields: dict[str, Any]) -> str | None:
    """Fill a template. None means the template is broken (unbalanced braces)."""
    try:
        return template.format_map(_FormatMap(fields))
    except ValueError:
        return None


def _whole(value: Any, what: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a whole number")
    try:
        number = int(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{what} must be a whole number") from err
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{what} must be a whole number")
    return number


def coerce_marks(value: Any) -> tuple[int, ...]:
    """Unique minute marks, longest first. An empty list means no marks."""
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raise ValueError("Minute marks must be a list of minutes")
    marks: list[int] = []
    for item in raw:
        number = _whole(item, "Minute marks")
        if not 1 <= number <= MARK_MAX:
            raise ValueError(f"Minute marks must be between 1 and {MARK_MAX}")
        marks.append(number)
    return tuple(sorted(set(marks), reverse=True))


def coerce_lead(value: Any) -> int:
    number = _whole(value, "Lead")
    if not 0 <= number <= LEAD_MAX:
        raise ValueError(f"Lead must be between 0 and {LEAD_MAX} seconds")
    return number


def coerce_volume(value: Any) -> int | None:
    if value in (None, ""):
        return None
    number = _whole(value, "Volume")
    if not 0 <= number <= 100:
        raise ValueError("Volume must be between 0 and 100")
    return number


def coerce_players(value: Any) -> tuple[str, ...]:
    if value in (None, "", []):
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError("Media players must be a list of entity ids")
    players = [str(item).strip() for item in value if str(item).strip()]
    return tuple(dict.fromkeys(players))


def coerce_player_leads(value: Any) -> dict[str, int]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("Per-player leads must be a mapping of entity ids to seconds")
    leads: dict[str, int] = {}
    for entity_id, seconds in value.items():
        if seconds in (None, ""):
            continue
        leads[str(entity_id)] = coerce_lead(seconds)
    return leads


def coerce_groups(value: Any, *, strict: bool = False) -> dict[str, bool]:
    """On/off for each announcement group. Missing keys stay on."""
    merged = {key: True for key in GROUP_KEYS}
    if value in (None, {}):
        return merged
    if not isinstance(value, dict):
        raise ValueError("Announcement groups must be a mapping")
    for key, flag in value.items():
        if key not in merged:
            if strict:
                raise ValueError(f"Unknown announcement group {key}")
            continue
        if isinstance(flag, bool):
            merged[key] = flag
        elif strict:
            raise ValueError(f"Announcement group {key} must be on or off")
    return merged


def coerce_templates(value: Any, *, strict: bool = False) -> dict[str, str]:
    """Merge over the defaults. A blank template disables that announcement."""
    merged = dict(DEFAULT_TEMPLATES)
    if value in (None, {}):
        return merged
    if not isinstance(value, dict):
        raise ValueError("Templates must be a mapping")
    for key, text in value.items():
        if key not in DEFAULT_TEMPLATES:
            if strict:
                raise ValueError(f"Unknown announcement template {key}")
            continue
        if not isinstance(text, str):
            raise ValueError(f"Template {key} must be text")
        if len(text) > 400:
            raise ValueError(f"Template {key} is too long")
        merged[key] = DEFAULT_TEMPLATES[key] if text == _RETIRED_TEMPLATES.get(key) else text
    return merged


def _marks_or_default(value: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    if value is None:
        return default
    try:
        return coerce_marks(value)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class AnnounceOptions:
    """Announcement settings, already coerced."""

    enabled: bool
    players: tuple[str, ...]
    tts_entity: str
    voice: str
    language: str
    lead_seconds: int
    player_leads: dict[str, int]
    volume: int | None
    candle_marks: tuple[int, ...]
    shkia_marks: tuple[int, ...]
    yt_marks: tuple[int, ...]
    shkia_final_min: int
    groups: dict[str, bool]
    templates: dict[str, str]


def options_from_settings(settings: dict[str, Any] | None) -> AnnounceOptions:
    """Lenient read of stored settings. Broken hand-edited values fall back to defaults."""
    s = settings or {}
    try:
        lead = coerce_lead(s.get("announce_lead_seconds", 0))
    except ValueError:
        lead = 0
    try:
        leads = coerce_player_leads(s.get("announce_player_leads"))
    except ValueError:
        leads = {}
    try:
        volume = coerce_volume(s.get("announce_volume"))
    except ValueError:
        volume = None
    try:
        players = coerce_players(s.get("announce_players"))
    except ValueError:
        players = ()
    try:
        final_min = _whole(s.get("announce_shkia_final_min", 1), "Final shkia offset")
        if not 0 <= final_min <= 180:
            final_min = 1
    except ValueError:
        final_min = 1
    try:
        templates = coerce_templates(s.get("announce_templates"))
    except ValueError:
        templates = dict(DEFAULT_TEMPLATES)
    try:
        groups = coerce_groups(s.get("announce_groups"))
    except ValueError:
        groups = {key: True for key in GROUP_KEYS}
    return AnnounceOptions(
        enabled=bool(s.get("announce_enabled")),
        players=players,
        tts_entity=str(s.get("announce_tts_entity") or "").strip(),
        voice=str(s.get("announce_voice") or "").strip(),
        language=str(s.get("announce_language") or "").strip(),
        lead_seconds=lead,
        player_leads=leads,
        volume=volume,
        candle_marks=_marks_or_default(s.get("announce_candle_marks"), DEFAULT_CANDLE_MARKS),
        shkia_marks=_marks_or_default(s.get("announce_shkia_marks"), DEFAULT_SHKIA_MARKS),
        yt_marks=_marks_or_default(s.get("announce_yt_marks"), DEFAULT_YT_MARKS),
        shkia_final_min=final_min,
        groups=groups,
        templates=templates,
    )


@dataclass(frozen=True, slots=True)
class Announcement:
    """One sentence, at the moment it should be heard (before any lead)."""

    id: str
    kind: str
    block_id: str
    day: date
    nominal_at: datetime
    minutes: int
    message: str


@dataclass(frozen=True, slots=True)
class ScheduledCall:
    """One TTS call: a group of players that share a lead, fired early."""

    announcement: Announcement
    fire_at: datetime
    players: tuple[str, ...]
    lead_seconds: int


def _occasion(is_shabbat: bool, holiday: jcal.Holiday | None) -> str:
    if holiday and is_shabbat:
        return f"{holiday.name} on Shabbat"
    if holiday:
        return holiday.name
    return "Shabbat"


def _message(kind: str, templates: dict[str, str], fields: dict[str, Any]) -> str | None:
    chosen = templates.get(kind, DEFAULT_TEMPLATES[kind])
    if not chosen.strip():
        return None  # blank template: this announcement is turned off
    rendered = render_template(chosen, fields)
    if rendered is not None:
        return rendered
    if chosen != DEFAULT_TEMPLATES[kind]:
        return render_template(DEFAULT_TEMPLATES[kind], fields)
    return None


def havdalah_minutes_spoken(block: jcal.Block, minhag: jcal.Minhag) -> int:
    """The number of minutes the motzaei sentence should say for this block's end."""
    last = block.days[-1]
    if last.weekday() != 5:
        return int(minhag.yom_tov_end_minutes)
    if minhag.havdalah_mode == "minutes":
        return int(minhag.havdalah_minutes)
    shkia = block.slots[-1].anchors["sunset"]
    return int(round((block.end - shkia).total_seconds() / 60))


def plan_announcements(
    blocks: list[jcal.Block], minhag: jcal.Minhag, options: AnnounceOptions,
) -> list[Announcement]:
    """Every announcement for these blocks, in speaking order."""
    events: list[Announcement] = []

    def add(kind: str, when: datetime, minutes: int, slot: jcal.Slot | None, block: jcal.Block,
            occasion: str) -> None:
        fields = {
            "minutes": minutes,
            "unit": "minute" if minutes == 1 else "minutes",
            "minutes_words": minutes_words(minutes),
            "occasion": occasion,
            "title": block.title,
        }
        message = _message(kind, options.templates, fields)
        if message is None:
            return
        day = slot.day if slot else block.days[-1]
        events.append(Announcement(
            id=f"{block.id}:{kind}:{when.isoformat()}",
            kind=kind,
            block_id=block.id,
            day=day,
            nominal_at=when,
            minutes=minutes,
            message=message,
        ))

    for block in blocks:
        for slot in block.slots:
            if slot.part is not jcal.Part.NIGHT:
                continue
            sunset = slot.anchors.get("sunset")
            if sunset is None:
                continue
            candle = slot.start
            occasion = _occasion(slot.is_shabbat, slot.holiday)
            groups = options.groups
            # After sunset: the previous day has ended, so preparation for the next meal may begin.
            if candle > sunset:
                if groups.get(YT_CANDLE, True):
                    for minutes in options.yt_marks:
                        add(YT_CANDLE, shift(candle, -minutes * 60), minutes, slot, block, occasion)
                    add(YT_CANDLE_NOW, candle, 0, slot, block, occasion)
                continue
            if groups.get(CANDLE, True):
                for minutes in options.candle_marks:
                    add(CANDLE, shift(candle, -minutes * 60), minutes, slot, block, occasion)
            final_on = groups.get(SHKIA_FINAL, True)
            final_at = shift(sunset, -options.shkia_final_min * 60)
            if groups.get(SHKIA, True):
                for minutes in options.shkia_marks:
                    at = shift(sunset, -minutes * 60)
                    # Only after candles are lit, and don't speak over the final warning.
                    if at <= candle or (final_on and at == final_at):
                        continue
                    add(SHKIA, at, minutes, slot, block, occasion)
            if final_on and final_at > candle:
                add(SHKIA_FINAL, final_at, options.shkia_final_min, slot, block, occasion)
        if (
            options.groups.get(MOTZEI, True)
            and block.slots
            and block.slots[-1].anchors.get("sunset") is not None
        ):
            minutes = havdalah_minutes_spoken(block, minhag)
            add(MOTZEI, block.end, minutes, None, block, block.title)

    events.sort(key=lambda event: (event.nominal_at, event.kind, event.id))
    return events


def schedule_announcements(
    events: list[Announcement],
    *,
    players: list[str] | tuple[str, ...],
    lead_seconds: int,
    player_leads: dict[str, int],
    not_before: datetime,
) -> list[ScheduledCall]:
    """Group players that share a lead and drop calls that should already have fired."""
    if not players:
        return []
    groups: dict[int, list[str]] = {}
    for player in players:
        lead = int(player_leads.get(player, lead_seconds))
        groups.setdefault(lead, []).append(player)
    calls: list[ScheduledCall] = []
    for event in events:
        for lead, group in groups.items():
            fire_at = shift(event.nominal_at, -lead)
            if fire_at <= not_before:
                continue
            calls.append(ScheduledCall(
                announcement=event, fire_at=fire_at, players=tuple(group), lead_seconds=lead,
            ))
    calls.sort(key=lambda call: (call.fire_at, call.announcement.id, call.lead_seconds))
    return calls
