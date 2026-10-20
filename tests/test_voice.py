"""The optional voice module: wording, the kids' briefing, and core with the module off."""

from datetime import datetime
from pathlib import Path

from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shabbot.const import DOMAIN
from custom_components.shabbot.voice.briefing import (
    notes_sentence,
    render_briefing,
    weather_sentence,
)
from custom_components.shabbot.voice.gate import migrate_voice_settings
from custom_components.shabbot.voice.wording import about_minutes, natural_time


def test_core_package_does_not_import_the_voice_module() -> None:
    root = Path(__file__).resolve().parents[1] / "custom_components" / "shabbot" / "core"
    for path in root.glob("*.py"):
        text = path.read_text()
        assert "shabbot.voice" not in text
        assert "from ..voice" not in text
        assert "from .voice" not in text


def test_existing_announce_setup_keeps_the_module_on() -> None:
    assert migrate_voice_settings({"announce_enabled": True}) == {"voice_enabled": True}
    assert migrate_voice_settings({}) == {}
    assert migrate_voice_settings({"announce_enabled": False}) == {}
    assert migrate_voice_settings({"announce_enabled": True, "voice_enabled": False}) == {}


def test_weather_uses_structured_fields_and_ignores_forecast_prose() -> None:
    class _State:
        state = "partly_cloudy"
        attributes = {
            "temperature": 60,
            "templow": 40,
            "precipitation_probability": 5,
            "forecast": [{
                "temperature": 68,
                "templow": 52,
                "precipitation_probability": 20,
                "detailed_description": "A written forecast that must never be spoken aloud to the kids.",
            }],
        }

    sentence = weather_sentence(_State())
    assert sentence == (
        "It's partly cloudy, with a high around 68 and a low around 52, "
        "and about a 20 percent chance of rain."
    )
    assert "written forecast" not in sentence
    assert weather_sentence(None) == ""

    class _Empty:
        state = "unavailable"
        attributes = {}

    assert weather_sentence(_Empty()) == ""


def test_notes_sentence_and_a_briefing_without_weather_or_notes() -> None:
    from custom_components.shabbot.core import astro, jcal
    from custom_components.shabbot.core.dayinfo import build_day_info

    assert notes_sentence([]) == ""
    assert notes_sentence(["Pack the lunch bag"]) == "A note from home: Pack the lunch bag."
    brooklyn = astro.Location(40.6501, -73.94958, "America/New_York", 18)
    morning = datetime(2026, 10, 20, 8, 0, tzinfo=brooklyn.tzinfo)
    info = build_day_info(morning, brooklyn, jcal.Minhag())
    script = render_briefing(info, template="")
    assert script == (
        "Good morning. Today is 9 Cheshvan 5787. This week's parasha is Lech-Lecha. "
        "Daf Yomi is Bechoros, daf 32. Shkia is at 6:08. Shabbat is in three days."
    )
    assert "rain" not in script
    assert "note from home" not in script
    assert about_minutes(18) == "about twenty minutes"
    assert natural_time(info.time("shkia")) == "at 6:08"

    with_both = render_briefing(
        info,
        template="",
        weather="It's sunny, with a high around 68 and a low around 52.",
        notes=["Pack the lunch bag"],
    )
    assert "It's sunny, with a high around 68 and a low around 52." in with_both
    assert "A note from home: Pack the lunch bag." in with_both
    assert with_both.startswith("Good morning. Today is 9 Cheshvan 5787.")


async def _setup(hass: HomeAssistant, freezer) -> None:
    from zoneinfo import ZoneInfo

    freezer.move_to(datetime(2026, 10, 20, 8, 0, tzinfo=ZoneInfo("America/New_York")))
    await hass.config.async_set_time_zone("America/New_York")
    hass.config.latitude, hass.config.longitude, hass.config.elevation = 40.6501, -73.94958, 18
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"candle_lighting_min": 18, "israel": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_core_still_answers_when_the_voice_module_is_off(
        hass: HomeAssistant, freezer) -> None:
    await _setup(hass, freezer)
    manager = hass.data[DOMAIN]
    assert manager.settings["voice_enabled"] is False
    manager.settings.update({
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.piper",
    })
    manager.announcer.reschedule()
    assert manager.announcer._unsubs == []

    info = await hass.services.async_call(DOMAIN, "get_day_info", {}, blocking=True, return_response=True)
    assert info["hebrew_date"]["english"] == "9 Cheshvan 5787"
    assert info["parasha"]["english"] == "Lech-Lecha"
    assert "script" not in info
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True)


async def test_daily_briefing_with_and_without_weather_and_notes(
        hass: HomeAssistant, freezer) -> None:
    await _setup(hass, freezer)
    manager = hass.data[DOMAIN]
    manager.settings["voice_enabled"] = True

    plain = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert plain["script"] == (
        "Good morning. Today is 9 Cheshvan 5787. This week's parasha is Lech-Lecha. "
        "Daf Yomi is Bechoros, daf 32. Shkia is at 6:08. Shabbat is in three days."
    )
    assert plain["weather"] is None
    assert plain["notes"] == []
    assert plain["voice_enabled"] is True

    hass.states.async_set("weather.home", "sunny", {
        "temperature": 70,
        "temperature_unit": "°F",
        "forecast": [{
            "temperature": 71,
            "templow": 55,
            "precipitation_probability": 10,
            "detailed_description": "Storm narrative from a forecast blob.",
        }],
    })
    hass.states.async_set("input_text.kids", "Violin at four", {"expiry": "2026-10-19"})
    manager.settings.update({
        "briefing_weather_entity": "weather.home",
        "briefing_notes_entity": "input_text.kids",
        "briefing_notes_until": "2026-10-19",
    })
    expired = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert "sunny" in expired["script"]
    assert "high around 71" in expired["script"]
    assert "Storm narrative" not in expired["script"]
    assert "Violin" not in expired["script"]

    async def _items(_call):
        return {"todo.family": {"items": [
            {"summary": "Pack the lunch bag", "status": "needs_action"},
            {"summary": "Old chore", "status": "needs_action", "due": "2020-01-01"},
            {"summary": "Already done", "status": "completed"},
        ]}}

    hass.services.async_register(
        "todo", "get_items", _items, supports_response=SupportsResponse.ONLY,
    )
    manager.settings.update({
        "briefing_notes_entity": "todo.family",
        "briefing_notes_until": "",
    })
    full = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert full["notes"] == ["Pack the lunch bag"]
    assert "A note from home: Pack the lunch bag." in full["script"]
    assert "Old chore" not in full["script"]
    assert "Already done" not in full["script"]
    assert "Storm narrative" not in full["script"]
    assert full["hebrew_date"] == "9 Cheshvan 5787"
    assert full["parasha"] == "Lech-Lecha"
    assert full["daf"] == "Bechoros, daf 32"
    assert full["countdown"] == "Shabbat is in three days."
