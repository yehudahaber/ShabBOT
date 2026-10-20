"""TTS lexicon, stable briefing windows, and the day-rollover event."""

from datetime import date, datetime, timedelta
from pathlib import Path
import threading

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.shabbot.const import DOMAIN, EVENT_DAY_ROLLOVER
from custom_components.shabbot.core.dayinfo import ZMAN_LABELS
from custom_components.shabbot.voice.lexicon import load_lexicon_file, speak
from custom_components.shabbot.voice.wording import natural_time


def test_lexicon_is_whole_word_and_case_insensitive() -> None:
    assert speak("shkia") == "shkee-ah"
    assert speak("SHKIA") == "shkee-ah"
    assert speak("Cheshvan") == "khesh-vahn"
    assert speak("CHESHVAN") == "khesh-vahn"
    assert speak("lech-lecha") == "lekh lee-khah"
    assert speak("LECH-LECHA") == "lekh lee-khah"
    assert speak("until shkia.") == "until shkee-ah."
    for untouched in ("change", "shkiah", "preshkia", "notcheshvan", "the Shabbaton"):
        assert speak(untouched) == untouched


def test_longer_calendar_phrase_wins() -> None:
    assert speak("Sof zman Shema MGA") == "sohf zmahn shmah em-gee-ah"
    assert speak("Sof zman Shema") == "sohf zmahn shmah"
    assert speak("Adar I") == "ah-dahr the first"
    assert speak("Adar") == "ah-dahr"
    assert speak("Achrei Mot-Kedoshim") == "ahkh-ray moht keh-doh-sheem"
    assert speak("Chol HaMoed Pesach") == "khol hah-moh-ed peh-sahkh"
    assert speak("Hol hamoed Sukkot") == "khol hah-moh-ed soo-koht"
    assert speak("Rosh Hashanah") == "rohsh hah-shah-nah"


def test_builtin_covers_months_parashot_masechtot_zmanim_and_holidays() -> None:
    from hdate.daf_yomi import DafYomiDatabase
    from hdate.parasha import Months, Parasha
    from hdate.translator import context_language

    token = context_language.set("en")
    try:
        for month in Months:
            name = str(month)
            assert speak(name) != name, name
        for parasha in Parasha:
            name = str(parasha)
            if name.casefold() == "none":
                continue
            assert speak(name) != name, name
        names: set[str] = set()
        db = DafYomiDatabase()
        start = date(2020, 1, 2)
        for offset in range(2711):
            masechta = db.lookup(start + timedelta(days=offset))
            names.add(masechta.get_translation(masechta.name))
        assert len(names) >= 30
        for name in names:
            assert speak(name) != name, name
    finally:
        context_language.reset(token)

    for english, _hebrew in ZMAN_LABELS.values():
        if english == "Candle lighting":
            assert speak(english) == english
        else:
            assert speak(english) != english, english

    for holiday in (
        "Chanukah", "Purim", "Shushan Purim", "Rosh Chodesh", "Tish'a B'Av",
        "Tu B'Shvat", "Lag B'Omer", "Hoshana Raba", "Yom HaAtzma'ut", "Daf Yomi",
    ):
        assert speak(holiday) != holiday, holiday


def test_yaml_extends_and_overrides_and_a_bad_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "tts_lexicon.yaml"
    path.write_text("shkia: SHEE-kee-ah\nmyword: my-word\n", encoding="utf-8")
    settings = {
        "tts_lexicon_path": str(path),
        "announce_pronunciations": {"melacha": "MEL-ah-khah", "shkia": "shkee-ah"},
    }
    assert speak("Shkia and melacha and Cheshvan myword", settings) == (
        "SHEE-kee-ah and MEL-ah-khah and khesh-vahn my-word"
    )

    nested = tmp_path / "nested.yaml"
    nested.write_text("words:\n  shkia: from-file\n", encoding="utf-8")
    assert speak("shkia", {"tts_lexicon_path": str(nested)}) == "from-file"

    wide = tmp_path / "wide.yaml"
    wide.write_text("".join(f"word{i}: say-{i}\n" for i in range(90)), encoding="utf-8")
    loaded = load_lexicon_file(str(wide))
    assert len(loaded) == 90
    assert speak("word89", {"tts_lexicon_path": str(wide)}) == "say-89"

    missing = {"tts_lexicon_path": str(tmp_path / "no-such-tts_lexicon.yaml")}
    assert speak("shkia", missing) == "shkee-ah"
    broken = tmp_path / "broken.yaml"
    broken.write_text(":\n  - [\n", encoding="utf-8")
    assert speak("shkia", {"tts_lexicon_path": str(broken)}) == "shkee-ah"
    assert speak("shkia", {"announce_pronunciations": {}}) == "shkee-ah"


def test_briefing_and_announcements_are_stable_inside_a_window() -> None:
    from custom_components.shabbot.core import astro, jcal
    from custom_components.shabbot.core.dayinfo import build_day_info
    from custom_components.shabbot.voice import announcements
    from custom_components.shabbot.voice.briefing import render_briefing, stable_briefing_moment

    root = Path(__file__).resolve().parents[1] / "custom_components" / "shabbot" / "voice"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "random." not in text
        assert "Random(" not in text

    brooklyn = astro.Location(40.6501, -73.94958, "America/New_York", 18)
    morning = datetime(2026, 10, 20, 8, 0, tzinfo=brooklyn.tzinfo)
    afternoon = datetime(2026, 10, 20, 15, 0, tzinfo=brooklyn.tzinfo)
    info = build_day_info(morning, brooklyn, jcal.Minhag())
    shkia = info.time("shkia")
    assert shkia is not None
    anchor, window = stable_briefing_moment(afternoon, shkia)
    assert window == "morning"
    assert anchor == afternoon.replace(hour=8, minute=0, second=0, microsecond=0)
    assert render_briefing(build_day_info(anchor, brooklyn, jcal.Minhag()), template="") == render_briefing(
        info, template="",
    )
    evening_anchor, evening_window = stable_briefing_moment(shkia, shkia)
    assert evening_window == "shkia"
    assert render_briefing(build_day_info(evening_anchor, brooklyn, jcal.Minhag()), template="") != (
        render_briefing(info, template="")
    )

    rounded = datetime(2026, 10, 20, 18, 7, 40, tzinfo=brooklyn.tzinfo)
    assert natural_time(rounded) == natural_time(rounded.replace(minute=8, second=20)) == "at 6:08"

    minhag = jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=60)
    blocks = [block for block in jcal.blocks_between(date(2026, 10, 10), date(2026, 10, 10), brooklyn, minhag)]
    options = announcements.options_from_settings({})
    first = [event.message for event in announcements.plan_announcements(blocks, minhag, options)]
    second = [event.message for event in announcements.plan_announcements(blocks, minhag, options)]
    assert first == second
    assert first


async def _brooklyn(hass: HomeAssistant, freezer) -> None:
    from zoneinfo import ZoneInfo

    freezer.move_to(datetime(2026, 10, 20, 8, 0, tzinfo=ZoneInfo("America/New_York")))
    await hass.config.async_set_time_zone("America/New_York")
    hass.config.latitude, hass.config.longitude, hass.config.elevation = 40.6501, -73.94958, 18


async def test_services_keep_display_text_and_add_spoken(
        hass: HomeAssistant, freezer, tmp_path: Path,
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    await _brooklyn(hass, freezer)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"candle_lighting_min": 18, "israel": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = hass.data[DOMAIN]
    manager.settings["voice_enabled"] = True

    info = await hass.services.async_call(DOMAIN, "get_day_info", {}, blocking=True, return_response=True)
    assert info["text"] == info["summary"]
    assert "Cheshvan" in info["text"]
    assert "Lech-Lecha" in info["text"]
    assert "khesh-vahn" in info["spoken"]
    assert "lekh lee-khah" in info["spoken"]
    assert "Cheshvan" not in info["spoken"]
    assert hass.states.get("sensor.shabbot_hebrew_date").state == "9 Cheshvan 5787"
    assert hass.states.get("sensor.shabbot_parasha").state == "Lech-Lecha"
    assert hass.states.get("sensor.shabbot_daf_yomi").state == "Bechoros 32"

    morning = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert morning["text"] == morning["script"]
    assert morning["window"] == "morning"
    assert "T08:00" in morning["anchor"]
    assert "Cheshvan" in morning["text"]
    assert "khesh-vahn" in morning["spoken"]
    assert "beh-khoh-rohs" in morning["spoken"]
    assert "shkee-ah" in morning["spoken"]

    freezer.move_to(datetime(2026, 10, 20, 15, 0, tzinfo=manager.location.tzinfo))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    afternoon = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert afternoon["script"] == morning["script"]
    assert afternoon["spoken"] == morning["spoken"]
    assert afternoon["window"] == "morning"

    shkia = manager.day_info().time("shkia")
    freezer.move_to(shkia)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    evening = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert evening["window"] == "shkia"
    assert evening["script"] != morning["script"]
    assert "10 Cheshvan" in evening["text"]
    assert "khesh-vahn" in evening["spoken"]

    dated = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {"date": "2026-10-20"}, blocking=True, return_response=True,
    )
    assert dated["window"] == "daytime"
    assert "9 Cheshvan" in dated["text"]

    path = tmp_path / "tts_lexicon.yaml"
    path.write_text("shkia: SHEE-kee-ah\n", encoding="utf-8")
    manager.settings["tts_lexicon_path"] = str(path)
    overridden = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert "SHEE-kee-ah" in overridden["spoken"]
    assert "shkee-ah" not in overridden["spoken"]
    assert "Cheshvan" in overridden["text"]
    assert "khesh-vahn" in overridden["spoken"]
    assert hass.states.get("sensor.shabbot_hebrew_date").state == "10 Cheshvan 5787"

    manager.settings["tts_lexicon_path"] = str(tmp_path / "missing.yaml")
    fallback = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert "shkee-ah" in fallback["spoken"]
    assert "SHEE-kee-ah" not in fallback["spoken"]


async def test_day_rollover_fires_at_midnight_and_shkia_and_not_at_startup(
        hass: HomeAssistant, freezer,
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    heard: list[dict] = []

    def _capture(event) -> None:
        heard.append(dict(event.data))

    hass.bus.async_listen(EVENT_DAY_ROLLOVER, _capture)
    await _brooklyn(hass, freezer)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"candle_lighting_min": 18, "israel": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert heard == []

    manager = hass.data[DOMAIN]
    manager.settings["voice_enabled"] = True
    shkia = manager.day_info().time("shkia")
    freezer.move_to(shkia)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [item["reason"] for item in heard] == ["shkia"]
    rolled = heard[0]
    assert rolled["window"] == "shkia"
    assert rolled["day"]["date"] == "2026-10-20"
    assert rolled["day"]["hebrew_date"]["english"].startswith("10 Cheshvan")
    assert rolled["text"] == rolled["day"]["summary"]
    assert "Cheshvan" in rolled["text"]
    assert "khesh-vahn" in rolled["spoken"]
    assert "Cheshvan" not in rolled["spoken"]
    assert "Good morning" in rolled["briefing_text"]
    assert "khesh-vahn" in rolled["briefing_spoken"]
    assert rolled["voice_enabled"] is True
    live = await hass.services.async_call(
        DOMAIN, "get_daily_briefing", {}, blocking=True, return_response=True,
    )
    assert live["script"] == rolled["briefing_text"]
    assert live["spoken"] == rolled["briefing_spoken"]

    freezer.move_to(datetime(2026, 10, 21, 0, 0, tzinfo=manager.location.tzinfo))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert [item["reason"] for item in heard] == ["shkia", "midnight"]
    assert heard[1]["day"]["date"] == "2026-10-21"
    assert heard[1]["window"] == "morning"
    assert heard[1]["text"].startswith("Today is")
    assert "khesh-vahn" in heard[1]["spoken"]
    assert heard[1]["briefing_text"] != rolled["briefing_text"]


async def test_lexicon_file_is_not_read_on_the_event_loop(
        hass: HomeAssistant, freezer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.shabbot.voice import announcer as announcer_mod

    await _brooklyn(hass, freezer)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"candle_lighting_min": 18, "israel": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    path = tmp_path / "tts_lexicon.yaml"
    path.write_text("cheshvan: KHESh-vahn\n", encoding="utf-8")
    manager = hass.data[DOMAIN]
    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "dry_run": True,
        "tts_lexicon_path": str(path),
    })
    loop_id = threading.get_ident()
    on_loop: list[bool] = []
    real = announcer_mod.load_lexicon_file

    def _spy(file_path: str) -> dict[str, str]:
        on_loop.append(threading.get_ident() == loop_id)
        return real(file_path)

    monkeypatch.setattr(announcer_mod, "load_lexicon_file", _spy)
    manager.announcer.reschedule()
    await hass.async_block_till_done()
    assert on_loop == []
    spoken = await manager.announcer.async_speak_test("Cheshvan shkia")
    await hass.async_block_till_done()
    assert on_loop == [False]
    assert spoken == "KHESh-vahn shkee-ah"
