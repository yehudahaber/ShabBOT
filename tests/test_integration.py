"""End-to-end behaviour inside Home Assistant: executor, protection, overrides."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.shabbot.const import DOMAIN
from custom_components.shabbot.manager import ShabbotManager

TZ = ZoneInfo("America/New_York")
# Friday 2026-10-09, Shabbat Bereshit. Sunset ≈ 18:24, candle lighting 18:06, havdalah Sat ≈ 19:14.
FRIDAY_AFTERNOON = datetime(2026, 10, 9, 16, 0, tzinfo=TZ)

DEVICES = ["chandelier", "bedroom", "hotplate"]


def _action(aid: str, entity: str, start: str, end: str, state: str = "on") -> dict:
    return {"id": aid, "entity_id": entity, "state": state, "start": start, "end": end}


@pytest.fixture
async def manager(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> ShabbotManager:
    freezer.move_to(FRIDAY_AFTERNOON)
    await hass.config.async_set_time_zone("America/New_York")
    hass.config.latitude, hass.config.longitude, hass.config.elevation = 40.6501, -73.94958, 18
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {d: {} for d in DEVICES}})
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"candle_lighting_min": 18})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    m: ShabbotManager = entry.runtime_data
    m.config["routines"]["fri_standard"]["actions"] = [
        _action("a1", "input_boolean.chandelier", "sunset+18m", "11:45pm"),
        _action("a2", "input_boolean.hotplate", "sunset", "sunset+2h"),
    ]
    m.config["routines"]["baseline"]["actions"] = [
        _action("b1", "input_boolean.bedroom", "block_start", "block_end", state="off"),
        _action("b2", "input_boolean.chandelier", "block_start", "block_end", state="off"),
    ]
    m.settings.update(dry_run=False, grace_seconds=4)
    m.config_changed(reconcile=False)
    await hass.async_block_till_done()
    return m


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, to: datetime | timedelta) -> None:
    if isinstance(to, timedelta):
        freezer.tick(to)
    else:
        freezer.move_to(to)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _user_toggle(hass: HomeAssistant, entity: str, on: bool) -> None:
    """Simulate someone flipping a switch (a context ShabBOT didn't create)."""
    await hass.services.async_call("input_boolean", "turn_on" if on else "turn_off",
                                   {"entity_id": f"input_boolean.{entity}"}, blocking=True, context=Context())
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity: str) -> str:
    return hass.states.get(f"input_boolean.{entity}").state


def _block_times(m: ShabbotManager):
    (block,) = m.upcoming_blocks(3)
    night = block.slots[0]
    return block, night.anchors["sunset"]


async def test_entities_created(hass: HomeAssistant, manager: ShabbotManager) -> None:
    assert hass.states.get("binary_sensor.shabbot_issur_melacha").state == "off"
    candle = hass.states.get("sensor.shabbot_next_candle_lighting").state
    assert candle.startswith("2026-10-09T22:06")  # 18:06 EDT in UTC
    assert hass.states.get("select.shabbot_mode").state == "Normal"
    assert hass.states.get("switch.shabbot_dry_run").state == "off"
    assert hass.states.get("calendar.shabbot_shabbat_yom_tov").attributes["message"] == "Shabbat"


async def test_executor_follows_schedule(hass: HomeAssistant, manager: ShabbotManager,
                                         freezer: FrozenDateTimeFactory) -> None:
    block, sunset = _block_times(manager)
    await _user_toggle(hass, "bedroom", True)
    await _user_toggle(hass, "chandelier", True)
    await _advance(hass, freezer, block.start + timedelta(seconds=1))
    assert hass.states.get("binary_sensor.shabbot_issur_melacha").state == "on"
    assert _state(hass, "bedroom") == "off"  # baseline
    assert _state(hass, "chandelier") == "off"
    await _advance(hass, freezer, sunset + timedelta(seconds=1))
    assert _state(hass, "hotplate") == "on"
    await _advance(hass, freezer, sunset + timedelta(minutes=18, seconds=1))
    assert _state(hass, "chandelier") == "on"
    await _advance(hass, freezer, sunset + timedelta(hours=2, seconds=1))
    assert _state(hass, "hotplate") == "off"  # one-shot end state
    await _advance(hass, freezer, datetime(2026, 10, 9, 23, 45, 1, tzinfo=TZ))
    assert _state(hass, "chandelier") == "off"  # baseline takes over again


async def test_announcement_dry_run_logs_at_the_lead_adjusted_time(
        hass: HomeAssistant, manager: ShabbotManager, freezer: FrozenDateTimeFactory) -> None:
    block, _sunset = _block_times(manager)
    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.google_en_com",
        "announce_lead_seconds": 20,
        "dry_run": True,
    })
    manager.config_changed(reconcile=False)
    await hass.async_block_till_done()
    nominal = block.start - timedelta(minutes=60)
    fire = nominal - timedelta(seconds=20)
    await _advance(hass, freezer, fire - timedelta(seconds=5))
    assert not any(e["kind"] == "announce" for e in manager.store.activity)
    await _advance(hass, freezer, fire + timedelta(seconds=1))
    logged = [e for e in manager.store.activity if e["kind"] == "announce"]
    from custom_components.shabbot.voice.wording import natural_time
    assert logged and logged[-1]["message"] == (
        f"Dry run: About an hour until candle lighting, {natural_time(block.start)}."
    )
    assert logged[-1]["entity_id"] == "media_player.kitchen"


async def test_dry_run_changes_nothing(hass: HomeAssistant, manager: ShabbotManager,
                                       freezer: FrozenDateTimeFactory) -> None:
    manager.settings["dry_run"] = True
    _, sunset = _block_times(manager)
    await _advance(hass, freezer, sunset + timedelta(minutes=18, seconds=1))
    assert _state(hass, "chandelier") == "off"
    assert any(e["kind"] == "dry_run" and e["entity_id"] == "input_boolean.chandelier"
               for e in manager.store.activity)


async def test_protection_reverts_after_grace(hass: HomeAssistant, manager: ShabbotManager,
                                              freezer: FrozenDateTimeFactory) -> None:
    block, _ = _block_times(manager)
    await _advance(hass, freezer, block.start + timedelta(minutes=5))
    await _user_toggle(hass, "bedroom", True)
    await _advance(hass, freezer, timedelta(seconds=2))
    assert _state(hass, "bedroom") == "on"  # still within grace window
    await _advance(hass, freezer, timedelta(seconds=3))
    assert _state(hass, "bedroom") == "off"
    assert manager.store.activity[-1]["kind"] == "revert"


async def test_protection_poll_catches_missed_events(hass: HomeAssistant, manager: ShabbotManager,
                                                     freezer: FrozenDateTimeFactory) -> None:
    block, _ = _block_times(manager)
    await _advance(hass, freezer, block.start + timedelta(minutes=5))
    # Write state directly (no state_changed listener path through a service) and drop pending reverts.
    hass.states.async_set("input_boolean.bedroom", "on", context=Context())
    await hass.async_block_till_done()
    manager._cancel_revert("input_boolean.bedroom")
    await _advance(hass, freezer, timedelta(seconds=61))
    assert hass.states.get("input_boolean.bedroom").state == "off"


async def test_no_protection_outside_issur(hass: HomeAssistant, manager: ShabbotManager,
                                           freezer: FrozenDateTimeFactory) -> None:
    await _user_toggle(hass, "bedroom", True)
    await _advance(hass, freezer, timedelta(seconds=10))
    assert _state(hass, "bedroom") == "on"


async def test_flip_pattern_override(hass: HomeAssistant, manager: ShabbotManager,
                                     freezer: FrozenDateTimeFactory) -> None:
    manager.config["devices"]["input_boolean.bedroom"] = {
        "override": {"detector": "flip_pattern", "count": 3, "window_s": 6}, "override_minutes": 20}
    manager.config_changed(reconcile=False)
    block, _ = _block_times(manager)
    await _advance(hass, freezer, block.start + timedelta(seconds=1))
    await _advance(hass, freezer, timedelta(minutes=5))
    for on in (True, False, True):
        await _user_toggle(hass, "bedroom", on)
        await _advance(hass, freezer, timedelta(seconds=1))
    assert "input_boolean.bedroom" in manager.overrides
    await _advance(hass, freezer, timedelta(minutes=10))
    assert _state(hass, "bedroom") == "on"  # housekeeper is cleaning
    await _advance(hass, freezer, timedelta(minutes=11))
    assert "input_boolean.bedroom" not in manager.overrides
    assert _state(hass, "bedroom") == "off"  # re-asserted when the override expired


async def test_persistence_override(hass: HomeAssistant, manager: ShabbotManager,
                                    freezer: FrozenDateTimeFactory) -> None:
    manager.config["devices"]["input_boolean.bedroom"] = {
        "override": {"detector": "persistence", "count": 3, "window_s": 120}}
    manager.config_changed(reconcile=False)
    block, _ = _block_times(manager)
    await _advance(hass, freezer, block.start + timedelta(minutes=5))
    for _ in range(2):
        await _user_toggle(hass, "bedroom", True)
        await _advance(hass, freezer, timedelta(seconds=5))
        assert _state(hass, "bedroom") == "off"
    await _user_toggle(hass, "bedroom", True)  # third time: intentional
    await _advance(hass, freezer, timedelta(seconds=5))
    assert _state(hass, "bedroom") == "on"
    assert "input_boolean.bedroom" in manager.overrides


async def test_zwave_triple_tap_override(hass: HomeAssistant, manager: ShabbotManager,
                                         freezer: FrozenDateTimeFactory) -> None:
    base = {"device_id": "dev1", "command_class": 91, "value": "KeyPressed3x"}
    manager.config["devices"]["input_boolean.bedroom"] = {"override": {
        "detector": "event",
        "start": {"event_type": "zwave_js_value_notification", "data": {**base, "property_key": "001"}},
        "end": {"event_type": "zwave_js_value_notification", "data": {**base, "property_key": "002"}},
    }, "override_group": ["input_boolean.chandelier"]}
    manager.config_changed(reconcile=False)
    block, _ = _block_times(manager)
    await _advance(hass, freezer, block.start + timedelta(minutes=5))
    # Triple-tap up: the switch's local control turns the load on, and the scene event arrives.
    await _user_toggle(hass, "bedroom", True)
    hass.bus.async_fire("zwave_js_value_notification", {**base, "property_key": "001", "node_id": 7})
    await _advance(hass, freezer, timedelta(seconds=10))
    assert _state(hass, "bedroom") == "on"
    assert set(manager.overrides) == {"input_boolean.bedroom", "input_boolean.chandelier"}
    # A different paddle/press count is ignored.
    hass.bus.async_fire("zwave_js_value_notification", {**base, "property_key": "002", "value": "KeyPressed"})
    await hass.async_block_till_done()
    assert "input_boolean.bedroom" in manager.overrides
    # Triple-tap down ends it early and re-asserts.
    hass.bus.async_fire("zwave_js_value_notification", {**base, "property_key": "002"})
    await _advance(hass, freezer, timedelta(seconds=1))
    assert manager.overrides == {}
    assert _state(hass, "bedroom") == "off"


async def test_storm_guard(hass: HomeAssistant, manager: ShabbotManager, freezer: FrozenDateTimeFactory) -> None:
    manager.settings.update(storm_max_reverts=3, storm_window_min=10)
    block, _ = _block_times(manager)
    await _advance(hass, freezer, block.start + timedelta(minutes=5))
    for _ in range(4):
        await _user_toggle(hass, "bedroom", True)
        await _advance(hass, freezer, timedelta(seconds=5))
    assert manager.paused.get("input_boolean.bedroom") == "storm"
    assert _state(hass, "bedroom") == "on"
    assert any(e["kind"] == "storm" for e in manager.store.activity)


async def test_restart_mid_shabbat_reconciles(hass: HomeAssistant, manager: ShabbotManager,
                                              freezer: FrozenDateTimeFactory) -> None:
    _, sunset = _block_times(manager)
    freezer.move_to(sunset + timedelta(minutes=30))
    await manager.async_reconcile("test restart")
    await hass.async_block_till_done()
    assert _state(hass, "chandelier") == "on"
    assert _state(hass, "hotplate") == "on"
    assert _state(hass, "bedroom") == "off"


async def test_skip_meal_only_once(hass: HomeAssistant, manager: ShabbotManager,
                                   freezer: FrozenDateTimeFactory) -> None:
    await hass.services.async_call(DOMAIN, "skip_slot", {"slot": "2026-10-10/night"}, blocking=True)
    await hass.async_block_till_done()
    _, sunset = _block_times(manager)
    await _advance(hass, freezer, sunset + timedelta(minutes=20))
    assert _state(hass, "chandelier") == "off"
    _, instances = manager.plan(datetime(2026, 10, 17).date(), datetime(2026, 10, 17).date())
    nxt = next(i for i in instances if i.target.key == "2026-10-17/night")
    assert nxt.routine and nxt.routine["id"] == "fri_standard"


async def test_websocket_plan_and_routine_save(hass: HomeAssistant, manager: ShabbotManager, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "shabbot/plan", "start": "2026-10-01", "end": "2026-10-31"})
    res = await client.receive_json()
    assert res["success"]
    keys = {i["key"] for i in res["result"]["instances"]}
    assert "2026-10-10/night" in keys
    await client.send_json_auto_id({"type": "shabbot/routine/save", "routine": {
        "name": "Bad", "part": "night", "actions": [{"entity_id": "light.x", "state": "on",
                                                      "start": "sunsett", "end": "midnight"}]}})
    res = await client.receive_json()
    assert not res["success"] and "Unknown time" in res["error"]["message"]
    await client.send_json_auto_id({"type": "shabbot/preview", "expr": "sunset+18m", "part": "night"})
    res = await client.receive_json()
    assert res["result"]["time"].startswith("2026-10-09T18:4")


async def test_websocket_rejects_backwards_routine(hass: HomeAssistant, manager: ShabbotManager, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    routine = {"name": "Backwards", "part": "night", "actions": [
        {"entity_id": "light.x", "state": "on", "start": "slot_end", "end": "slot_start"}]}
    await client.send_json_auto_id({"type": "shabbot/routine/save", "routine": routine})
    res = await client.receive_json()
    assert not res["success"] and "never after the start time" in res["error"]["message"]
    await client.send_json_auto_id({"type": "shabbot/routine/check", "part": "night",
                                    "actions": [{"start": "sunset", "end": "sunrise"}]})
    res = await client.receive_json()
    (check,) = res["result"]
    assert check["first"]["start"].startswith("2026-10-09T18:2")
    assert check["first"]["end"].startswith("2026-10-10T07:0") and check["first"]["next_day"]
    assert check["next_day"] == check["total"] and not check["always_invalid"]


async def test_early_shabbat_setting_moves_candle_lighting(hass: HomeAssistant, manager: ShabbotManager,
                                                           hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "shabbot/settings/save", "settings": {
        "early_shabbat": True, "early_shabbat_time": "19:00", "early_shabbat_after": "19:15"}})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "shabbot/plan", "start": "2027-06-25", "end": "2027-06-26"})
    (block,) = (await client.receive_json())["result"]["blocks"]
    assert block["start"].startswith("2027-06-25T19:00") and block["normal_start"].startswith("2027-06-25T20:1")
    await client.send_json_auto_id({"type": "shabbot/settings/save", "settings": {"early_shabbat_time": "7pm"}})
    assert not (await client.receive_json())["success"]


async def test_every_day_baseline_row_runs_each_morning(hass: HomeAssistant, manager: ShabbotManager,
                                                        freezer: FrozenDateTimeFactory, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    baseline = {**manager.config["routines"]["baseline"], "actions": [
        {"entity_id": "input_boolean.hotplate", "state": "on", "start": "7:00am", "end": "10:00am", "repeat": "day"}]}
    await client.send_json_auto_id({"type": "shabbot/routine/save", "routine": baseline})
    res = await client.receive_json()
    assert res["success"] and res["result"]["actions"][0]["repeat"] == "day"
    # Meal routines don't repeat: the field is dropped on save.
    meal = {**manager.config["routines"]["fri_standard"], "actions": [
        {"entity_id": "input_boolean.hotplate", "state": "on", "start": "sunset", "end": "midnight", "repeat": "day"}]}
    await client.send_json_auto_id({"type": "shabbot/routine/save", "routine": meal})
    assert "repeat" not in (await client.receive_json())["result"]["actions"][0]

    # Pesach 2027 + Shabbat: Thu, Fri, Sat. The device comes on each morning at 7.
    freezer.move_to(datetime(2027, 4, 21, 12, 0, tzinfo=TZ))
    manager.config["routines"]["fri_standard"]["actions"] = []
    manager.rebuild()
    for day in (22, 23, 24):
        await _advance(hass, freezer, datetime(2027, 4, day, 7, 0, 1, tzinfo=TZ))
        assert _state(hass, "hotplate") == "on", day
        await _advance(hass, freezer, datetime(2027, 4, day, 10, 0, 1, tzinfo=TZ))
        assert _state(hass, "hotplate") == "off", day


async def test_routine_rows_store_device_lists(hass: HomeAssistant, manager: ShabbotManager, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    routine = {**manager.config["routines"]["fri_standard"], "actions": [
        {"entity_id": "input_boolean.chandelier", "state": "on", "start": "sunset", "end": "11pm"},
        {"entity_ids": ["input_boolean.hotplate", "input_boolean.bedroom"], "state": "on",
         "start": "sunset", "end": "sunset+2h"}]}
    await client.send_json_auto_id({"type": "shabbot/routine/save", "routine": routine})
    res = await client.receive_json()
    assert [a["entity_ids"] for a in res["result"]["actions"]] == [
        ["input_boolean.chandelier"], ["input_boolean.hotplate", "input_boolean.bedroom"]]
    assert all("entity_id" not in a for a in res["result"]["actions"])
    await client.send_json_auto_id({"type": "shabbot/routine/save", "routine": {
        **routine, "actions": [{"entity_ids": [], "state": "on", "start": "sunset", "end": "11pm"}]}})
    res = await client.receive_json()
    assert not res["success"] and "at least one device" in res["error"]["message"]


async def test_routines_reorder(hass: HomeAssistant, manager: ShabbotManager, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    ids = list(manager.config["routines"])
    wanted = [ids[1], ids[0], "missing"]
    await client.send_json_auto_id({"type": "shabbot/routines/reorder", "routine_ids": wanted})
    res = await client.receive_json()
    assert res["success"]
    assert res["result"] == list(manager.config["routines"]) == [ids[1], ids[0], *ids[2:]]
    await client.send_json_auto_id({"type": "shabbot/config"})
    assert (await client.receive_json())["result"]["config"]["routine_order"] == res["result"]


async def test_prerendered_clip_plays_and_a_missing_clip_uses_live_tts(
        hass: HomeAssistant, manager: ShabbotManager) -> None:
    """Saved volume still applies. Sonos gets the file; live TTS is only the fallback."""
    import io
    import wave

    from custom_components.shabbot.voice.prerender import ClipLibrary, media_directory

    played: list[dict] = []
    spoken: list[dict] = []
    volumes: list[float] = []

    async def _play(call) -> None:
        played.append(dict(call.data))

    async def _speak(call) -> None:
        spoken.append(dict(call.data))

    async def _volume(call) -> None:
        volumes.append(call.data["volume_level"])

    hass.services.async_register("media_player", "play_media", _play)
    hass.services.async_register("tts", "speak", _speak)
    hass.services.async_register("media_player", "volume_set", _volume)

    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.piper",
        "announce_voice": "en_US-lessac-high",
        "announce_volume": 65,
        "dry_run": True,
    })
    heard = await manager.announcer.async_speak_test("Shkia")
    assert heard == "shkee-ah"
    assert manager.store.activity[-1]["message"] == "Dry run: Shkia"
    assert not played

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    ClipLibrary(media_directory(hass)).store(
        "tts.piper", "en_US-lessac-high", "", "shkee-ah", buffer.getvalue(),
    )
    manager.settings["dry_run"] = False
    await manager.announcer.async_speak_test("shkia")
    await hass.async_block_till_done()
    assert volumes == [0.65]
    assert played and played[0]["media_content_id"].startswith("media-source://media_source/local/shabbot/")
    assert played[0]["announce"] is True
    assert played[0]["entity_id"] == ["media_player.kitchen"]
    assert not spoken

    await manager.announcer.async_speak_test("a line with no recording")
    await hass.async_block_till_done()
    assert spoken and spoken[-1]["message"] == "a line with no recording"
    assert spoken[-1]["options"] == {"voice": "en_US-lessac-high"}


async def test_prerender_file_io_stays_off_the_event_loop(
        hass: HomeAssistant, manager: ShabbotManager, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Reading, writing, and deleting clips must not run on the loop.

    Home Assistant 2026.10 warns when ``index.json`` is read from ``reschedule``.
    pytest skips those file checks, so this turns the production detector back on
    and also fails if a media-folder call still runs on the loop thread.
    """
    from functools import partial
    import io
    import logging
    from pathlib import Path
    import threading
    import wave

    import homeassistant.block_async_io as block_async_io
    from homeassistant.util.loop import _PREVIOUSLY_REPORTED

    from custom_components.shabbot.const import PLAN_HORIZON_DAYS
    from custom_components.shabbot.core import jcal
    from custom_components.shabbot.voice import announcements, announcer as announcer_mod
    from custom_components.shabbot.voice.prerender import ClipLibrary, media_directory
    from custom_components.shabbot.voice.pronounce import apply_pronunciation

    def _wav(seconds: float) -> bytes:
        rate = 16000
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(b"\x00\x00" * int(seconds * rate))
        return buffer.getvalue()

    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.piper",
        "announce_voice": "en_US-lessac-high",
        "announce_lead_seconds": 8,
        "announce_volume": 65,
        "dry_run": False,
    })
    now = manager.now()
    options = announcements.options_from_settings(manager.settings)
    blocks = jcal.blocks_between(
        now.date() - timedelta(days=3), now.date() + timedelta(days=PLAN_HORIZON_DAYS),
        manager.location, manager.minhag,
    )
    events = announcements.plan_announcements(blocks, manager.minhag, options)
    final = next(event for event in events if event.kind == "shkia_final")
    spoken_final = apply_pronunciation(final.message, options.pronunciations)
    library = ClipLibrary(media_directory(hass))
    library.store("tts.piper", "en_US-lessac-high", "", spoken_final, _wav(3.5))
    library.store("tts.piper", "en_US-lessac-high", "", "shkee-ah", _wav(1.0))
    orphan = library.directory / "orphan.wav"
    orphan.write_bytes(b"RIFF")

    played: list[dict] = []

    async def _play(call) -> None:
        played.append(dict(call.data))

    hass.services.async_register("media_player", "play_media", _play)
    hass.services.async_register("media_player", "volume_set", lambda call: None)

    async def _synth(_hass, _engine, _language, _voice, _text) -> bytes:
        return _wav(3.5)

    monkeypatch.setattr(announcer_mod, "tts_ready", lambda _hass: True)
    monkeypatch.setattr(announcer_mod, "synthesize", _synth)

    media = library.directory
    loop_id = threading.get_ident()
    offenders: list[str] = []
    for name in (
        "open", "read_text", "read_bytes", "write_text", "write_bytes",
        "is_file", "is_dir", "iterdir", "mkdir", "unlink",
    ):
        real = getattr(Path, name)

        def _wrap(self, *args, __real=real, __name=name, **kwargs):
            if threading.get_ident() == loop_id and (self == media or media in self.parents):
                offenders.append(f"{__name} {self}")
            return __real(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, _wrap)

    tracked: list = []
    real_track = announcer_mod.async_track_point_in_time

    def _track(hass, action, point):
        tracked.append(action)
        return real_track(hass, action, point)

    monkeypatch.setattr(announcer_mod, "async_track_point_in_time", _track)

    previous_in_tests = block_async_io._IN_TESTS
    block_async_io._IN_TESTS = False
    _PREVIOUSLY_REPORTED.clear()
    block_async_io.enable()
    before = manager.announcer._generation
    try:
        with caplog.at_level(logging.WARNING, logger="homeassistant.util.loop"):
            manager.announcer.reschedule()
            await hass.async_block_till_done()
            manager.announcer._clips = {}
            await manager.announcer.async_speak_test("shkia")
            await hass.async_block_till_done()
    finally:
        block_async_io._IN_TESTS = previous_in_tests
        calls = block_async_io._BLOCKED_CALLS.calls
        for blocking_call in list(calls):
            setattr(blocking_call.object, blocking_call.function, blocking_call.original_func)
        calls.clear()
        _PREVIOUSLY_REPORTED.clear()

    assert offenders == []
    assert manager.announcer._generation - before <= 3
    assert not orphan.exists()
    assert "shkee-ah" in manager.announcer._clips
    finals = [
        action.args[0] for action in tracked
        if isinstance(action, partial) and action.args and getattr(action.args[0], "announcement", None)
        and action.args[0].announcement.kind == "shkia_final"
    ]
    assert finals
    assert (finals[-1].announcement.nominal_at - finals[-1].fire_at).total_seconds() == pytest.approx(11.5)
    assert played and played[0]["media_content_id"].startswith("media-source://media_source/local/shabbot/")
    assert played[0]["announce"] is True
    blocking = [
        record.getMessage() for record in caplog.records
        if "Detected blocking call" in record.getMessage() and str(media) in record.getMessage()
    ]
    assert blocking == []


async def test_announce_style_repeat_cue_and_single_run(
        hass: HomeAssistant, manager: ShabbotManager, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cue, then the line N times; a mark already playing is not started again."""
    import io
    import wave

    from custom_components.shabbot.voice import announcer as announcer_module
    from custom_components.shabbot.voice.prerender import ClipLibrary, media_directory

    sleeps: list[float] = []

    async def _no_wait(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(announcer_module.asyncio, "sleep", _no_wait)
    played: list[dict] = []

    async def _play(call) -> None:
        played.append(dict(call.data))

    hass.services.async_register("media_player", "play_media", _play)
    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.piper",
        "announce_repeat": "twice",
        "announce_cue": True,
        "announce_gap_ms": 500,
        "dry_run": False,
    })
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    ClipLibrary(media_directory(hass)).store("tts.piper", "", "", "shkee-ah", buffer.getvalue())

    await manager.announcer.async_speak_test("shkia")
    ids = [item["media_content_id"] for item in played]
    assert len(ids) == 3
    assert ids[0].endswith("/soft_cue.wav")
    assert ids[1] == ids[2] and not ids[1].endswith("/soft_cue.wav")
    assert (media_directory(hass) / "soft_cue.wav").is_file()
    assert sleeps == [0.5 + 0.5, 1.0 + 0.5]

    # Same key while a run is in flight: ignored, never a third play.
    manager.announcer._active.add(("test",))
    played.clear()
    await manager.announcer.async_speak_test("shkia")
    assert not played

    manager.announcer._active.clear()
    manager.settings.update({"announce_repeat": "once", "announce_cue": False})
    await manager.announcer.async_speak_test("shkia")
    assert len(played) == 1


def _register_recorder(hass: HomeAssistant, *services: tuple[str, str]) -> list[tuple[str, str, dict]]:
    calls: list[tuple[str, str, dict]] = []

    async def _record(call) -> None:
        calls.append((call.domain, call.service, dict(call.data)))

    for domain, service in services:
        hass.services.async_register(domain, service, _record)
    return calls


def _store_test_clip(hass: HomeAssistant) -> None:
    import io
    import wave

    from custom_components.shabbot.voice.prerender import ClipLibrary, media_directory

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)
    ClipLibrary(media_directory(hass)).store("tts.piper", "", "", "shkee-ah", buffer.getvalue())


async def test_announce_unmutes_even_without_volume_and_sonos_restore_keeps_mute(
        hass: HomeAssistant, manager: ShabbotManager, freezer: FrozenDateTimeFactory,
) -> None:
    """A muted speaker must still speak. Sonos restore, not a second mute call, puts mute back."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player", "sonos", "kitchen-sonos", suggested_object_id="kitchen",
    )
    hass.states.async_set(
        "media_player.kitchen", "idle", {"volume_level": 0.2, "is_volume_muted": True},
    )
    calls = _register_recorder(
        hass,
        ("sonos", "snapshot"),
        ("sonos", "restore"),
        ("media_player", "volume_set"),
        ("media_player", "volume_mute"),
        ("media_player", "play_media"),
    )
    _store_test_clip(hass)

    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.piper",
        "announce_volume": None,
        "announce_repeat": "once",
        "announce_cue": False,
        "dry_run": False,
    })
    await manager.announcer.async_speak_test("shkia")
    await hass.async_block_till_done()
    assert ("media_player", "volume_set") not in [(d, s) for d, s, _ in calls]
    mute = [data for domain, service, data in calls if domain == "media_player" and service == "volume_mute"]
    assert mute == [{"entity_id": ["media_player.kitchen"], "is_volume_muted": False}]
    prepare = [(domain, service) for domain, service, _ in calls]
    assert prepare.index(("sonos", "snapshot")) < prepare.index(("media_player", "volume_mute"))
    assert prepare.index(("media_player", "volume_mute")) < prepare.index(("media_player", "play_media"))

    await _advance(hass, freezer, timedelta(seconds=4))
    assert [service for _domain, service, _data in calls].count("volume_mute") == 1
    assert ("sonos", "restore") in [(domain, service) for domain, service, _data in calls]
    restore = next(data for domain, service, data in calls if domain == "sonos" and service == "restore")
    assert restore["entity_id"] == ["media_player.kitchen"]
    assert "is_volume_muted" not in restore

    calls.clear()
    manager.settings["announce_volume"] = 40
    await manager.announcer.async_speak_test("shkia")
    await hass.async_block_till_done()
    ordered = [(domain, service, data) for domain, service, data in calls]
    assert ("media_player", "volume_set", {"entity_id": ["media_player.kitchen"], "volume_level": 0.4}) in ordered
    assert ("media_player", "volume_mute", {"entity_id": ["media_player.kitchen"], "is_volume_muted": False}) in ordered
    services = [(domain, service) for domain, service, _data in ordered]
    assert services.index(("media_player", "volume_set")) < services.index(("media_player", "volume_mute"))
    assert services.index(("media_player", "volume_mute")) < services.index(("media_player", "play_media"))


async def test_non_sonos_mute_is_cleared_for_speech_and_restored_only_if_it_was_muted(
        hass: HomeAssistant, manager: ShabbotManager, freezer: FrozenDateTimeFactory,
) -> None:
    """No snapshot service: remember mute per player, unmute for speech, re-mute only the muted one."""
    hass.states.async_set("media_player.den", "idle", {"volume_level": 0.3, "is_volume_muted": True})
    hass.states.async_set("media_player.porch", "idle", {"volume_level": 0.5, "is_volume_muted": False})
    calls = _register_recorder(
        hass,
        ("media_player", "volume_set"),
        ("media_player", "volume_mute"),
        ("media_player", "play_media"),
    )
    _store_test_clip(hass)
    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.den", "media_player.porch"],
        "announce_tts_entity": "tts.piper",
        "announce_volume": None,
        "announce_repeat": "once",
        "announce_cue": False,
        "dry_run": False,
    })
    await manager.announcer.async_speak_test("shkia")
    await hass.async_block_till_done()
    names = [(domain, service) for domain, service, _data in calls]
    assert ("media_player", "volume_set") not in names  # mute restore does not need a volume
    assert names.count(("media_player", "volume_mute")) == 1
    first_mute = next(data for _d, service, data in calls if service == "volume_mute")
    assert first_mute == {
        "entity_id": ["media_player.den", "media_player.porch"], "is_volume_muted": False,
    }
    assert names.index(("media_player", "volume_mute")) < names.index(("media_player", "play_media"))

    await _advance(hass, freezer, timedelta(seconds=4))
    mutes = [data for _d, service, data in calls if service == "volume_mute"]
    assert mutes[1:] == [{"entity_id": "media_player.den", "is_volume_muted": True}]
    assert ("media_player", "volume_set") not in [(d, s) for d, s, _ in calls]

    # Nobody muted beforehand: nothing to put back.
    calls.clear()
    hass.states.async_set("media_player.den", "idle", {"volume_level": 0.3, "is_volume_muted": False})
    await manager.announcer.async_speak_test("shkia")
    await hass.async_block_till_done()
    await _advance(hass, freezer, timedelta(seconds=4))
    mutes = [data for _d, service, data in calls if service == "volume_mute"]
    assert mutes == [{"entity_id": ["media_player.den", "media_player.porch"], "is_volume_muted": False}]


async def test_test_mode_due_mark_does_not_touch_mute(
        hass: HomeAssistant, manager: ShabbotManager, freezer: FrozenDateTimeFactory,
) -> None:
    """A real mark skipped during Test mode must not unmute (or play) anything."""
    block, _sunset = _block_times(manager)
    hass.states.async_set("media_player.kitchen", "idle", {"volume_level": 0.2, "is_volume_muted": True})
    calls = _register_recorder(
        hass,
        ("media_player", "volume_set"),
        ("media_player", "volume_mute"),
        ("media_player", "play_media"),
    )
    _store_test_clip(hass)
    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.piper",
        "announce_repeat": "once",
        "announce_cue": False,
        "dry_run": False,
    })
    manager.config_changed(reconcile=False)
    await hass.async_block_till_done()
    await _advance(hass, freezer, block.start - timedelta(minutes=61))
    manager.start_simulation()
    await _advance(hass, freezer, block.start - timedelta(minutes=59))
    assert any(e["kind"] == "simulation" and "skipped announcement" in e["message"] for e in manager.store.activity)
    assert not [c for c in calls if c[1] in ("volume_mute", "volume_set", "play_media")]


async def test_simulation_api_switches_devices_even_in_dry_run(hass: HomeAssistant, manager: ShabbotManager,
                                                               hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    manager.settings["dry_run"] = True  # the test still moves real devices
    await client.send_json_auto_id({"type": "shabbot/simulate/steps", "start": "2026-10-09T17:00",
                                    "end": "2026-10-10T21:00"})
    steps = (await client.receive_json())["result"]
    chandelier_on = next(s for s in steps for c in s["commands"]
                         if c["entity_id"] == "input_boolean.chandelier" and c["state"] == "on")
    assert chandelier_on["commands"][0]["expr"] == "sunset+18m"

    await client.send_json_auto_id({"type": "shabbot/simulate/apply", "commands": chandelier_on["commands"]})
    assert not (await client.receive_json())["success"]  # only while test mode runs
    await client.send_json_auto_id({"type": "shabbot/simulate/start"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "shabbot/simulate/apply", "commands": chandelier_on["commands"]})
    assert (await client.receive_json())["success"]
    assert _state(hass, "chandelier") == "on"
    assert manager.status()["simulation"]

    await client.send_json_auto_id({"type": "shabbot/simulate/stop"})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert _state(hass, "chandelier") == "off"  # back to how it was before the test
    assert not manager.status()["simulation"]


async def test_simulation_pauses_schedule_and_protection(hass: HomeAssistant, manager: ShabbotManager,
                                                         freezer: FrozenDateTimeFactory) -> None:
    block, _ = _block_times(manager)
    await _advance(hass, freezer, block.start - timedelta(minutes=5))
    manager.start_simulation()
    await manager.async_simulate_apply([{"entity_id": "input_boolean.bedroom", "state": "on"}])
    # Shabbat starts mid-test: the baseline "off" isn't sent and nothing is reverted.
    await _advance(hass, freezer, block.start + timedelta(seconds=1))
    await _advance(hass, freezer, timedelta(minutes=2))
    assert _state(hass, "bedroom") == "on"
    manager.stop_simulation()
    await hass.async_block_till_done()
    assert _state(hass, "bedroom") == "off"  # the schedule now wants it off
    with pytest.raises(ValueError, match="can't run during"):
        manager.start_simulation()


async def test_simulation_restores_and_expires(hass: HomeAssistant, manager: ShabbotManager,
                                               freezer: FrozenDateTimeFactory) -> None:
    manager.start_simulation()
    await manager.async_simulate_apply([{"entity_id": "input_boolean.hotplate", "state": "on"}])
    assert _state(hass, "hotplate") == "on"
    await _advance(hass, freezer, timedelta(minutes=31))
    assert not manager.simulating
    assert _state(hass, "hotplate") == "off"  # no schedule before Shabbat: back to how it was


async def test_announcement_is_skipped_while_test_mode_runs(
        hass: HomeAssistant, manager: ShabbotManager, freezer: FrozenDateTimeFactory) -> None:
    block, _sunset = _block_times(manager)
    manager.settings.update({
        "voice_enabled": True,
        "announce_enabled": True,
        "announce_players": ["media_player.kitchen"],
        "announce_tts_entity": "tts.google_en_com",
        "dry_run": True,
    })
    manager.config_changed(reconcile=False)
    await hass.async_block_till_done()
    await _advance(hass, freezer, block.start - timedelta(minutes=61))
    manager.start_simulation()
    await _advance(hass, freezer, block.start - timedelta(minutes=59))
    assert not any(e["kind"] == "announce" for e in manager.store.activity)
    assert any(e["kind"] == "simulation" and "skipped announcement" in e["message"] for e in manager.store.activity)
