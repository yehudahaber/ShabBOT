"""Speak planned announcements on media players, or log them in dry run.

Sonos players are snapshotted before speech and restored afterwards, so a
previous queue and volume come back. Other players only have their volume put
back, and only when an announcement volume is set — there is no standard
snapshot service for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import partial
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import PLAN_HORIZON_DAYS
from .core import announcements, jcal

if TYPE_CHECKING:
    from .manager import ShabbotManager

_LOGGER = logging.getLogger(__name__)

TEST_MESSAGE = "This is a ShabBOT announcement test."


@dataclass(slots=True)
class _Hold:
    """How to put one player back after the sentence."""

    entity_id: str
    sonos: bool
    previous_volume: float | None


def _speech_seconds(message: str) -> float:
    """How long to wait before restoring playback. TTS returns when audio starts, not when it ends."""
    words = max(1, len(message.split()))
    return max(8.0, words * 0.45 + 4.0)


def _is_sonos(hass: HomeAssistant, entity_id: str) -> bool:
    entry = er.async_get(hass).async_get(entity_id)
    return bool(entry and entry.platform == "sonos")


class Announcer:
    """Schedules announcement timers and performs the TTS calls."""

    def __init__(self, manager: ShabbotManager) -> None:
        self._m = manager
        self._unsubs: list[CALLBACK_TYPE] = []
        self._holds: list[tuple[CALLBACK_TYPE, list[_Hold]]] = []

    def reschedule(self) -> None:
        """Rebuild timers from the current settings and calendar. Safe to call often."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        options = announcements.options_from_settings(self._m.settings)
        if not options.enabled:
            return
        if not options.players:
            _LOGGER.info("Announcements are enabled but no media player is selected")
            return
        now = self._m.now()
        blocks = jcal.blocks_between(
            now.date() - timedelta(days=3),
            now.date() + timedelta(days=PLAN_HORIZON_DAYS),
            self._m.location,
            self._m.minhag,
        )
        events = announcements.plan_announcements(blocks, self._m.minhag, options)
        calls = announcements.schedule_announcements(
            events,
            players=options.players,
            lead_seconds=options.lead_seconds,
            player_leads=options.player_leads,
            not_before=now,
        )
        for call in calls:
            self._unsubs.append(async_track_point_in_time(
                self._m.hass, partial(self._on_due, call), call.fire_at,
            ))
        _LOGGER.debug("Scheduled %s announcement triggers", len(calls))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        pending = self._holds
        self._holds = []
        for unsub, holds in pending:
            unsub()
            await self._restore(holds)

    @callback
    def _on_due(self, call: announcements.ScheduledCall, _now: Any) -> None:
        self._m.hass.async_create_task(self._speak(
            call.announcement.message, list(call.players),
        ))

    async def async_speak_test(self, message: str | None = None) -> None:
        """Speak (or, in dry run, log) one sentence now. Does not require the schedule to be enabled."""
        options = announcements.options_from_settings(self._m.settings)
        if not options.players:
            raise ServiceValidationError("Choose at least one media player")
        if not self._m.settings.get("dry_run") and not options.tts_entity:
            raise ServiceValidationError("Choose a TTS engine")
        await self._speak(message.strip() if message and message.strip() else TEST_MESSAGE, list(options.players))

    async def _speak(self, message: str, players: list[str]) -> None:
        if not players:
            return
        if self._m.settings.get("dry_run"):
            self._m.log("announce", f"Dry run: {message}", players[0] if len(players) == 1 else None, players=players)
            return
        options = announcements.options_from_settings(self._m.settings)
        hass = self._m.hass
        if not options.tts_entity:
            self._m.log("error", f"Announcement not spoken (choose a TTS engine): {message}")
            return
        if not hass.services.has_service("tts", "speak"):
            self._m.log("error", f"Announcement not spoken (tts.speak is unavailable): {message}")
            return
        holds = await self._prepare(players, options.volume)
        data: dict[str, Any] = {
            "media_player_entity_id": players,
            "message": message,
            "cache": True,
        }
        if options.language:
            data["language"] = options.language
        if options.voice:
            data["options"] = {"voice": options.voice}
        try:
            await hass.services.async_call(
                "tts", "speak", data, target={"entity_id": options.tts_entity}, blocking=True,
            )
        except Exception as err:
            self._m.log("error", f"Announcement failed: {err}")
            _LOGGER.warning("Announcement failed: %s", err)
            await self._restore(holds)
            return
        self._m.log("announce", message, players[0] if len(players) == 1 else None, players=players)
        self._schedule_restore(holds, _speech_seconds(message))

    async def _prepare(self, players: list[str], volume: int | None) -> list[_Hold]:
        hass = self._m.hass
        sonos = [entity_id for entity_id in players if _is_sonos(hass, entity_id)]
        snapshotted: set[str] = set()
        if sonos and hass.services.has_service("sonos", "snapshot"):
            try:
                await hass.services.async_call(
                    "sonos", "snapshot", {"entity_id": sonos, "with_group": True}, blocking=True,
                )
                snapshotted.update(sonos)
            except Exception as err:
                _LOGGER.warning("Sonos snapshot failed, continuing without it: %s", err)
        holds: list[_Hold] = []
        for entity_id in players:
            previous: float | None = None
            if volume is not None and entity_id not in snapshotted:
                state = hass.states.get(entity_id)
                raw = state.attributes.get("volume_level") if state else None
                if isinstance(raw, (int, float)):
                    previous = float(raw)
            holds.append(_Hold(entity_id, entity_id in snapshotted, previous))
        if volume is not None:
            try:
                await hass.services.async_call(
                    "media_player", "volume_set",
                    {"entity_id": players, "volume_level": max(0.0, min(1.0, volume / 100))},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning("Could not set announcement volume: %s", err)
        return holds

    def _schedule_restore(self, holds: list[_Hold], delay: float) -> None:
        if not any(hold.sonos or hold.previous_volume is not None for hold in holds):
            return
        when = dt_util.utcnow() + timedelta(seconds=delay)

        @callback
        def _fire(_now: Any) -> None:
            self._holds = [item for item in self._holds if item[0] is not unsub]
            self._m.hass.async_create_task(self._restore(holds))

        unsub = async_track_point_in_time(self._m.hass, _fire, when)
        self._holds.append((unsub, holds))

    async def _restore(self, holds: list[_Hold]) -> None:
        hass = self._m.hass
        sonos = [hold.entity_id for hold in holds if hold.sonos]
        if sonos and hass.services.has_service("sonos", "restore"):
            try:
                await hass.services.async_call(
                    "sonos", "restore", {"entity_id": sonos, "with_group": True}, blocking=True,
                )
            except Exception as err:
                _LOGGER.warning("Sonos restore failed: %s", err)
        for hold in holds:
            if hold.sonos or hold.previous_volume is None:
                continue
            try:
                await hass.services.async_call(
                    "media_player", "volume_set",
                    {"entity_id": hold.entity_id, "volume_level": hold.previous_volume},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning("Could not restore volume on %s: %s", hold.entity_id, err)
