"""One spoken daily briefing for kids, built only from ShabBOT and Home Assistant.

The script uses the core day info (Hebrew date, parasha or holiday, Daf Yomi,
shkia, candle lighting or havdalah, and a countdown to Shabbat or Yom Tov).
Weather, when configured, is summarized from a single ``weather.*`` entity's
condition and numeric high, low, and precipitation chance. Parental notes come
from one ``todo.*`` list or ``input_text.*`` entity. Nothing is fetched from
the web, and forecast narrative text is ignored.

Missing weather or notes are left out. The sentence still makes sense.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ..core import dayinfo, jcal
from .announcements import render_template
from .gate import voice_module_enabled
from .wording import day_count, natural_time

DEFAULT_BRIEFING_TEMPLATE = (
    "Good morning. Today is {hebrew_date}. {reading} "
    "Daf Yomi is {daf}. {zmanim}{countdown}{weather}{notes}"
)

BRIEFING_DEFAULTS: dict[str, Any] = {
    "briefing_template": DEFAULT_BRIEFING_TEMPLATE,
    "briefing_weather_entity": "",
    "briefing_notes_entity": "",
    "briefing_notes_until": "",
}

_TEMPLATE_MAX = 1200
_NARRATIVE_KEYS = frozenset({
    "detailed_description", "description", "narrative", "text", "comment", "forecast_text",
})


def coerce_briefing_template(value: Any, *, strict: bool = False) -> str:
    """A blank template means the warm default. Broken types raise."""
    if value in (None, ""):
        return DEFAULT_BRIEFING_TEMPLATE
    if not isinstance(value, str):
        raise ValueError("Briefing template must be text")
    text = value.strip()
    if not text:
        return DEFAULT_BRIEFING_TEMPLATE
    if len(text) > _TEMPLATE_MAX:
        raise ValueError("Briefing template is too long")
    return text


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _finish(text: str) -> str:
    """A section, or empty. Non-empty sections end with a period and a space."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned + " "


def reading_sentence(info: dayinfo.DayInfo) -> str:
    """The parasha, or the holiday reading when that replaces it."""
    if info.reading_kind == "holiday":
        return f"This Shabbat the reading is {info.reading_english}."
    if info.holiday_english:
        return (
            f"This week's parasha is {info.parasha_english}. "
            f"It is also {info.holiday_english}."
        )
    upcoming = _upcoming_holiday(info.civil_date, info.israel, info.reading_english)
    if upcoming:
        return f"This week's parasha is {info.parasha_english}. Coming up is {upcoming}."
    return f"This week's parasha is {info.parasha_english}."


def _upcoming_holiday(day: date, israel: bool, already: str) -> str | None:
    """The next Yom Tov name in the coming week, when it is not already named."""
    for offset in range(0, 8):
        holiday = jcal.yom_tov(day + timedelta(days=offset), israel)
        if holiday and holiday.name.casefold() not in already.casefold():
            return holiday.name
    return None


def countdown_sentence(day: date, israel: bool) -> str:
    """How soon Shabbat or Yom Tov starts, said from the civil morning."""
    for offset in range(0, 21):
        candidate = day + timedelta(days=offset)
        previous = candidate - timedelta(days=1)
        if not (jcal.is_issur_day(candidate, israel) and not jcal.is_issur_day(previous, israel)):
            continue
        holiday = jcal.yom_tov(candidate, israel)
        name = "Shabbat" if holiday is None else holiday.name
        if offset == 0:
            return "It's Shabbat." if holiday is None else f"It's {name}."
        if offset == 1:
            return f"{name} starts tonight."
        return f"{name} is in {day_count(offset - 1)}."
    return ""


def zmanim_sentence(info: dayinfo.DayInfo) -> str:
    """Shkia, plus candle lighting or havdalah when that evening has one."""
    parts: list[str] = []
    shkia = info.time("shkia")
    if shkia is not None:
        parts.append(f"Shkia is {natural_time(shkia)}")
    if info.candle_lighting is not None:
        parts.append(f"candle lighting is {natural_time(info.candle_lighting)}")
    if info.havdalah is not None:
        parts.append(f"havdalah is {natural_time(info.havdalah)}")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0] + "."
    return ", ".join(parts[:-1]) + ", and " + parts[-1] + "."


def weather_sentence(state: Any) -> str:
    """Condition, high, low, and precipitation chance. Narrative forecast text is ignored."""
    if state is None:
        return ""
    raw = getattr(state, "state", None)
    if raw in (None, "", "unavailable", "unknown", "none"):
        return ""
    condition = str(raw).replace("_", " ").replace("-", " ").strip()
    if len(condition.split()) > 3:
        condition = ""
    attrs = dict(getattr(state, "attributes", None) or {})
    high = _number(attrs.get("temperature"))
    low = _number(attrs.get("templow"))
    if low is None:
        low = _number(attrs.get("temperature_low"))
    precip = _number(attrs.get("precipitation_probability"))
    forecast = attrs.get("forecast")
    if isinstance(forecast, list) and forecast and isinstance(forecast[0], dict):
        item = {key: value for key, value in forecast[0].items() if key not in _NARRATIVE_KEYS}
        if _number(item.get("temperature")) is not None:
            high = _number(item.get("temperature"))
        if _number(item.get("templow")) is not None:
            low = _number(item.get("templow"))
        if _number(item.get("precipitation_probability")) is not None:
            precip = _number(item.get("precipitation_probability"))
        item_condition = item.get("condition")
        if isinstance(item_condition, str) and item_condition.strip() and len(item_condition.split()) <= 3:
            condition = item_condition.replace("_", " ").replace("-", " ").strip()
    pieces: list[str] = []
    if condition:
        pieces.append(f"It's {condition}")
    if high is not None and low is not None:
        pieces.append(f"with a high around {round(high)} and a low around {round(low)}")
    elif high is not None:
        pieces.append(f"around {round(high)} degrees")
    if precip is not None and precip >= 1:
        chance = f"about a {round(precip)} percent chance of rain"
        pieces.append(f"and {chance}" if pieces else chance)
    if not pieces:
        return ""
    if len(pieces) == 1:
        return pieces[0] + "."
    return pieces[0] + ", " + ", ".join(pieces[1:]) + "."


def notes_sentence(lines: list[str]) -> str:
    cleaned = [" ".join(line.split()).rstrip(".") for line in lines if line and line.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"A note from home: {cleaned[0]}."
    return "Notes from home: " + "; ".join(cleaned) + "."


def _todo_items(result: Any, entity_id: str) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    bucket = result.get(entity_id)
    if isinstance(bucket, dict):
        items = bucket.get("items", [])
    elif isinstance(bucket, list):
        items = bucket
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


async def collect_notes(
    hass: HomeAssistant, entity_id: str, until: str, today: date,
) -> list[str]:
    """Parental lines from one todo list or input_text. Expired lines are dropped."""
    entity_id = (entity_id or "").strip()
    if "." not in entity_id:
        return []
    domain = entity_id.split(".", 1)[0]
    if domain == "input_text":
        state = hass.states.get(entity_id)
        if state is None or state.state in ("", "unknown", "unavailable"):
            return []
        expiry = _parse_date(until) or _parse_date((state.attributes or {}).get("expiry"))
        if expiry is not None and today > expiry:
            return []
        return [state.state.strip()]
    if domain != "todo" or not hass.services.has_service("todo", "get_items"):
        return []
    try:
        result = await hass.services.async_call(
            "todo", "get_items", {"entity_id": entity_id}, blocking=True, return_response=True,
        )
    except Exception:  # noqa: BLE001 — a missing list should not break the morning
        return []
    lines: list[str] = []
    for item in _todo_items(result, entity_id):
        if str(item.get("status") or "").lower() == "completed":
            continue
        due = _parse_date(item.get("due"))
        if due is not None and today > due:
            continue
        summary = str(item.get("summary") or "").strip()
        if summary:
            lines.append(summary)
    return lines


def render_briefing(
    info: dayinfo.DayInfo,
    *,
    template: str,
    weather: str = "",
    notes: list[str] | None = None,
) -> str:
    """Fill the template. Empty weather and notes disappear."""
    fields = {
        "hebrew_date": info.hebrew_date.english,
        "reading": _finish(reading_sentence(info)),
        "parasha": info.reading_english,
        "daf": f"{info.masechet}, daf {info.daf}",
        "zmanim": _finish(zmanim_sentence(info)),
        "countdown": _finish(countdown_sentence(info.civil_date, info.israel)),
        "weather": _finish(weather),
        "notes": _finish(notes_sentence(notes or [])),
    }
    chosen = template.strip() or DEFAULT_BRIEFING_TEMPLATE
    rendered = render_template(chosen, fields)
    if rendered is None:
        rendered = render_template(DEFAULT_BRIEFING_TEMPLATE, fields) or ""
    return " ".join(rendered.split())


async def async_daily_briefing(
    hass: HomeAssistant,
    manager: Any,
    when: date | datetime | None = None,
) -> dict[str, Any]:
    """The kids' briefing for right now, or for a civil date. Requires the voice module."""
    if not voice_module_enabled(manager.settings):
        raise ServiceValidationError(
            "The voice module is turned off. Turn it on in ShabBOT settings to get the daily briefing.",
        )
    info = manager.day_info(when)
    settings = manager.settings
    try:
        template = coerce_briefing_template(settings.get("briefing_template"))
    except ValueError:
        template = DEFAULT_BRIEFING_TEMPLATE
    weather_entity = str(settings.get("briefing_weather_entity") or "").strip()
    weather = ""
    if weather_entity.startswith("weather."):
        weather = weather_sentence(hass.states.get(weather_entity))
    today = info.civil_date
    note_lines = await collect_notes(
        hass,
        str(settings.get("briefing_notes_entity") or ""),
        str(settings.get("briefing_notes_until") or ""),
        today,
    )
    script = render_briefing(info, template=template, weather=weather, notes=note_lines)
    return {
        "script": script,
        "hebrew_date": info.hebrew_date.english,
        "parasha": info.reading_english,
        "daf": f"{info.masechet}, daf {info.daf}",
        "countdown": countdown_sentence(info.civil_date, info.israel),
        "zmanim_sentence": zmanim_sentence(info),
        "weather": weather or None,
        "notes": note_lines,
        "voice_enabled": True,
    }
