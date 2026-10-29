"""Speak planned announcements on media players, or log them in dry run.

Audio is rendered ahead of time into the local media folder and played from
that file, so the speakers are not waiting on TTS at the mark. A missing file
falls back to live ``tts.speak``. The final stop-melacha warning is scheduled
from the known clip length so the sentence ends on its mark.

An optional soft cue plays first, then the line is spoken once or twice (the
``announce_repeat`` setting) with a short gap between plays. One run per mark:
a mark that is already playing is not started again, and runs never overlap.
While Test mode runs, real marks that come due are skipped (and logged), so a
rehearsal is never talked over.

Sonos players are snapshotted before speech and restored afterwards, so a
previous queue, volume, and mute come back. Mute is cleared on the announce
players before speech, including when no announcement volume is set, because
mute is independent of volume_level. Other players have no snapshot service:
they only get their volume put back (and only when an announcement volume is
set), and are re-muted if they were muted before.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from functools import partial
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from ..const import PLAN_HORIZON_DAYS
from ..core import jcal
from . import announcements
from .gate import voice_module_enabled
from .lexicon import effective_lexicon, load_lexicon_file
from .prerender import (
    BUNDLED_CUE_SECONDS,
    MEDIA_SOURCE_PREFIX,
    Clip,
    ClipLibrary,
    install_cue,
    media_directory,
    synthesize,
    tts_ready,
)
from .pronounce import apply_pronunciation

if TYPE_CHECKING:
    from ..manager import ShabbotManager

_LOGGER = logging.getLogger(__name__)

TEST_MESSAGE = "This is a ShabBOT announcement test."
# Render again this long before candle lighting, in case startup was too early
# or the engine was not ready yet. The daily rebuild also renders.
PRE_RENDER_HOURS = 6
_MESSAGE_MAX = 400


def _speech_seconds(message: str) -> float:
    """How long to wait before restoring playback when the clip length is unknown."""
    words = max(1, len(message.split()))
    return max(8.0, words * 0.45 + 4.0)


def _is_sonos(hass: HomeAssistant, entity_id: str) -> bool:
    entry = er.async_get(hass).async_get(entity_id)
    return bool(entry and entry.platform == "sonos")


class Announcer:
    """Schedules announcement timers and plays pre-rendered audio, or live TTS."""

    def __init__(self, manager: ShabbotManager) -> None:
        self._m = manager
        self._unsubs: list[CALLBACK_TYPE] = []
        self._holds: list[tuple[CALLBACK_TYPE, list[_Hold]]] = []
        self._generation = 0
        self._clips: dict[str, Clip] = {}
        self._clip_signature: tuple[str, str, str] | None = None
        self._lexicon_path = ""
        self._lexicon_file: dict[str, str] = {}
        self._cue: tuple[str, float | None] | None = None
        self._active: set[tuple] = set()
        self._play_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def reschedule(self) -> None:
        """Rebuild timers from the current settings and calendar. Safe to call often."""
        self._generation += 1
        generation = self._generation
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if not voice_module_enabled(self._m.settings):
            return
        options = announcements.options_from_settings(self._m.settings)
        if not options.enabled:
            return
        if not options.players:
            _LOGGER.info("Announcements are enabled but no media player is selected")
            return
        # Lengths already in memory apply on this pass. Reading the index is
        # file I/O, so it stays in ``_ensure_clips`` on the executor. A length
        # that shows up there schedules this again.
        signature = (options.tts_entity, options.voice, options.language)
        if signature != self._clip_signature:
            self._clips = {}
            self._clip_signature = signature
        now = self._m.now()
        blocks = jcal.blocks_between(
            now.date() - timedelta(days=3),
            now.date() + timedelta(days=PLAN_HORIZON_DAYS),
            self._m.location,
            self._m.minhag,
        )
        events = announcements.plan_announcements(
            blocks, self._m.minhag, options, location=self._m.location,
        )
        calls = announcements.schedule_announcements(
            events,
            players=options.players,
            lead_seconds=options.lead_seconds,
            player_leads=options.player_leads,
            not_before=now,
            clip_seconds=self._clip_seconds(events, options),
        )
        for call in calls:
            self._unsubs.append(async_track_point_in_time(
                self._m.hass, partial(self._on_due, call), call.fire_at,
            ))
        self._schedule_prerender_refresh(events, now, options)
        if options.tts_entity and not self._m.settings.get("dry_run"):
            self._m.hass.async_create_task(self._ensure_clips(generation, events, options))
        _LOGGER.debug("Scheduled %s announcement triggers", len(calls))

    async def async_stop(self) -> None:
        self._generation += 1
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        pending = self._holds
        self._holds = []
        for unsub, holds in pending:
            unsub()
            await self._restore(holds)

    @callback
    def _on_due(self, call: announcements.ScheduledCall, _now: Any) -> None:
        if self._m.simulating:
            # Test mode owns the speakers' neighbours; a late countdown is worse than silence, so skip it.
            self._m.log("simulation", f"Test mode: skipped announcement — {call.announcement.message}")
            return
        key = ("mark", call.announcement.id, call.players)
        if key in self._active:
            _LOGGER.debug("Announcement %s is already playing, not starting it again", call.announcement.id)
            return
        self._active.add(key)
        task = self._m.hass.async_create_task(self._speak(
            call.announcement.message, list(call.players), key=key, claimed=True,
        ))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def async_speak_test(self, message: str | None = None) -> str:
        """Speak (or, in dry run, log) one sentence now. Does not require the schedule to be enabled.

        Returns the text actually sent to TTS, after the pronunciation map.
        """
        if not voice_module_enabled(self._m.settings):
            raise ServiceValidationError(
                "The voice module is turned off. Turn it on in ShabBOT settings to speak.",
            )
        options = announcements.options_from_settings(self._m.settings)
        if not options.players:
            raise ServiceValidationError("Choose at least one media player")
        if not self._m.settings.get("dry_run") and not options.tts_entity:
            raise ServiceValidationError("Choose a TTS engine")
        text = message.strip() if message and message.strip() else TEST_MESSAGE
        if len(text) > _MESSAGE_MAX:
            raise ServiceValidationError("That line is too long")
        return await self._speak(text, list(options.players), render_first=True)

    async def _speak(
        self, message: str, players: list[str], *,
        render_first: bool = False, key: tuple = ("test",), claimed: bool = False,
    ) -> str:
        """One announcement run. A run for the same key, or any run in flight, is never doubled up."""
        if not claimed:
            if key in self._active:
                _LOGGER.debug("Announcement already playing, ignoring a second start")
                return apply_pronunciation(message, self._speech_map())
            self._active.add(key)
        try:
            async with self._play_lock:
                return await self._run(message, players, render_first=render_first)
        finally:
            self._active.discard(key)

    async def _run(self, message: str, players: list[str], *, render_first: bool) -> str:
        options = announcements.options_from_settings(self._m.settings)
        await self._refresh_lexicon_file()
        spoken = apply_pronunciation(message, self._speech_map())
        if not players:
            return spoken
        if self._m.settings.get("dry_run"):
            self._m.log("announce", f"Dry run: {message}", players[0] if len(players) == 1 else None, players=players)
            return spoken
        if not options.tts_entity:
            self._m.log("error", f"Announcement not spoken (choose a TTS engine): {message}")
            return spoken
        holds = await self._prepare(players, options.volume)
        try:
            return await self._play(message, spoken, players, options, holds, render_first=render_first)
        except asyncio.CancelledError:
            await self._restore(holds)
            raise

    async def _play(
        self, message: str, spoken: str, players: list[str], options: announcements.AnnounceOptions,
        holds: list[_Hold], *, render_first: bool,
    ) -> str:
        hass = self._m.hass
        gap = options.gap_ms / 1000
        if spoken not in self._clips and options.tts_entity:
            cached = await self._load_index(options)
            found = cached.get(spoken)
            if found is not None:
                self._clips[spoken] = found
        if render_first and spoken not in self._clips:
            await self._render_one(options, spoken)
        clip = self._clips.get(spoken)
        await self._play_cue(players, options)
        if clip is not None:
            seconds = clip.seconds or _speech_seconds(spoken)
            if await self._file_exists(clip.filename) and await self._play_clip(players, clip.media_content_id):
                for _ in range(options.repeat - 1):
                    await asyncio.sleep(seconds + gap)
                    if not await self._play_clip(players, clip.media_content_id):
                        break
                self._m.log("announce", message, players[0] if len(players) == 1 else None, players=players)
                self._schedule_restore(holds, seconds + 1.5)
                return spoken
            _LOGGER.info("Pre-rendered announcement missing or unplayable, using live TTS")
        if not hass.services.has_service("tts", "speak"):
            self._m.log("error", f"Announcement not spoken (tts.speak is unavailable): {message}")
            await self._restore(holds)
            return spoken
        data: dict[str, Any] = {
            "media_player_entity_id": players,
            "message": spoken,
            "cache": True,
        }
        if options.language:
            data["language"] = options.language
        if options.voice:
            data["options"] = {"voice": options.voice}
        try:
            for index in range(options.repeat):
                if index:
                    await asyncio.sleep(_speech_seconds(spoken) + gap)
                await hass.services.async_call(
                    "tts", "speak", data, target={"entity_id": options.tts_entity}, blocking=True,
                )
        except Exception as err:
            self._m.log("error", f"Announcement failed: {err}")
            _LOGGER.warning("Announcement failed: %s", err)
            await self._restore(holds)
            return spoken
        self._m.log("announce", message, players[0] if len(players) == 1 else None, players=players)
        self._schedule_restore(holds, _speech_seconds(spoken))
        return spoken

    async def _resolve_cue(self, options: announcements.AnnounceOptions) -> tuple[str, float | None] | None:
        """(media id, seconds) of the soft cue: the configured override, else the packaged WAV."""
        if options.cue_media_id:
            return options.cue_media_id, announcements.CUSTOM_CUE_SECONDS
        if self._cue is None:
            clip = await self._m.hass.async_add_executor_job(install_cue, media_directory(self._m.hass))
            if clip is None:
                return None
            self._cue = (f"{MEDIA_SOURCE_PREFIX}/{clip.filename}", clip.seconds or BUNDLED_CUE_SECONDS)
        return self._cue

    async def _play_cue(self, players: list[str], options: announcements.AnnounceOptions) -> None:
        if not options.cue:
            return
        cue = await self._resolve_cue(options)
        if cue is None or not await self._play_clip(players, cue[0]):
            return
        await asyncio.sleep((cue[1] or BUNDLED_CUE_SECONDS) + options.gap_ms / 1000)

    async def _play_clip(self, players: list[str], media_content_id: str) -> bool:
        hass = self._m.hass
        if not hass.services.has_service("media_player", "play_media"):
            return False
        try:
            await hass.services.async_call(
                "media_player", "play_media",
                {
                    "entity_id": players,
                    "media_content_id": media_content_id,
                    "media_content_type": "music",
                    "announce": True,
                },
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning("Playing pre-rendered announcement failed: %s", err)
            return False
        return True

    async def _ensure_clips(
        self, generation: int, events: list[announcements.Announcement], options: announcements.AnnounceOptions,
    ) -> None:
        """Load the index off the loop, render anything missing, and reschedule when a length is new."""
        if generation != self._generation:
            return
        before = self._speech_map()
        await self._refresh_lexicon_file()
        if generation != self._generation:
            return
        if self._speech_map() != before:
            self.reschedule()
            return
        try:
            loaded = await self._load_index(options)
        except OSError as err:
            _LOGGER.warning("Could not read pre-rendered announcements: %s", err)
            return
        if generation != self._generation:
            return
        scheduled = self._clip_seconds(events, options)
        self._clips = loaded
        if self._clip_seconds(events, options) != scheduled:
            self.reschedule()
            return
        if not tts_ready(self._m.hass):
            return
        speech = self._speech_map()
        texts = list(dict.fromkeys(apply_pronunciation(event.message, speech) for event in events))
        end_texts = {
            apply_pronunciation(event.message, speech)
            for event in events
            if event.kind in announcements.END_ON_TIME_KINDS
        }
        learned = False
        try:
            for text in texts:
                if generation != self._generation:
                    return
                if text in self._clips and await self._file_exists(self._clips[text].filename):
                    continue
                if not await self._render_one(options, text):
                    continue
                if text in end_texts and self._clips[text].seconds:
                    learned = True
            if all(text in self._clips for text in texts):
                await self._m.hass.async_add_executor_job(
                    self._library().drop_unreferenced, options.tts_entity, options.voice, options.language,
                )
        except Exception as err:
            _LOGGER.warning("Could not pre-render announcements: %s", err)
            return
        if learned and generation == self._generation:
            self.reschedule()

    async def _load_index(self, options: announcements.AnnounceOptions) -> dict[str, Clip]:
        """Read ``index.json`` and the clip files off the event loop."""
        library = self._library()
        return await self._m.hass.async_add_executor_job(
            library.load, options.tts_entity, options.voice, options.language,
        )

    async def _file_exists(self, filename: str) -> bool:
        path = self._library().directory / filename
        return await self._m.hass.async_add_executor_job(path.is_file)

    async def _render_one(self, options: announcements.AnnounceOptions, text: str) -> bool:
        if not options.tts_entity or not tts_ready(self._m.hass):
            return False
        try:
            audio = await synthesize(
                self._m.hass, options.tts_entity, options.language, options.voice, text,
            )
        except (HomeAssistantError, ServiceValidationError, OSError) as err:
            _LOGGER.warning("TTS pre-render failed: %s", err)
            return False
        if not audio:
            return False
        clip = await self._m.hass.async_add_executor_job(
            self._library().store, options.tts_entity, options.voice, options.language, text, audio,
        )
        self._clips[text] = clip
        return True

    def _speech_map(self) -> dict[str, str]:
        """Lexicon for a turn that is already on the event loop. Does not read the YAML file."""
        path = str(self._m.settings.get("tts_lexicon_path") or "").strip()
        file_map = self._lexicon_file if path and self._lexicon_path == path else {}
        return effective_lexicon(self._m.settings, file_map=file_map, allow_read=False)

    async def _refresh_lexicon_file(self) -> None:
        """Load ``tts_lexicon_path`` off the loop. An empty path does not touch the disk."""
        path = str(self._m.settings.get("tts_lexicon_path") or "").strip()
        if not path:
            self._lexicon_path = ""
            self._lexicon_file = {}
            return
        self._lexicon_file = await self._m.hass.async_add_executor_job(load_lexicon_file, path)
        self._lexicon_path = path

    def _library(self) -> ClipLibrary:
        return ClipLibrary(media_directory(self._m.hass))

    def _clip_seconds(
        self, events: list[announcements.Announcement], options: announcements.AnnounceOptions,
    ) -> dict[str, float]:
        lengths: dict[str, float] = {}
        for event in events:
            if event.kind not in announcements.END_ON_TIME_KINDS:
                continue
            spoken = apply_pronunciation(event.message, self._speech_map())
            clip = self._clips.get(spoken)
            if clip and clip.seconds:
                lengths[event.id] = announcements.playback_seconds(
                    clip.seconds,
                    repeat=options.repeat,
                    cue_seconds=self._cue_seconds(options),
                    gap_ms=options.gap_ms,
                )
        return lengths

    @staticmethod
    def _cue_seconds(options: announcements.AnnounceOptions) -> float | None:
        if not options.cue:
            return None
        return announcements.CUSTOM_CUE_SECONDS if options.cue_media_id else BUNDLED_CUE_SECONDS

    def _schedule_prerender_refresh(
        self, events: list[announcements.Announcement], now, options: announcements.AnnounceOptions,
    ) -> None:
        """One more render a few hours before candle lighting, on top of startup and the daily rebuild."""
        if not options.tts_entity or self._m.settings.get("dry_run"):
            return
        upcoming = []
        for event in events:
            if event.kind != announcements.CANDLE:
                continue
            at = announcements.shift(event.nominal_at, event.minutes * 60)
            if at > now:
                upcoming.append(at)
        if not upcoming:
            return
        refresh_at = announcements.shift(min(upcoming), -PRE_RENDER_HOURS * 3600)
        if refresh_at <= now:
            return
        self._unsubs.append(async_track_point_in_time(self._m.hass, lambda _now: self.reschedule(), refresh_at))

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
            muted = False
            if entity_id not in snapshotted:
                state = hass.states.get(entity_id)
                muted = bool(state and state.attributes.get("is_volume_muted") is True)
            holds.append(_Hold(entity_id, entity_id in snapshotted, previous, muted))
        if volume is not None:
            try:
                await hass.services.async_call(
                    "media_player", "volume_set",
                    {"entity_id": players, "volume_level": max(0.0, min(1.0, volume / 100))},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning("Could not set announcement volume: %s", err)
        # Sonos mute is not volume_level. Snapshot already saved it; restore puts
        # it back. Speech still has to be audible when volume is unset.
        await self._unmute(players)
        return holds

    async def _unmute(self, players: list[str]) -> None:
        """Clear mute on the announce players. No-op when the service is missing."""
        hass = self._m.hass
        if not players or not hass.services.has_service("media_player", "volume_mute"):
            return
        try:
            await hass.services.async_call(
                "media_player", "volume_mute",
                {"entity_id": players, "is_volume_muted": False},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning("Could not unmute announcement players: %s", err)

    def _schedule_restore(self, holds: list[_Hold], delay: float) -> None:
        if not any(hold.sonos or hold.previous_volume is not None or hold.previous_muted for hold in holds):
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
            if hold.sonos:
                continue
            if hold.previous_volume is not None:
                try:
                    await hass.services.async_call(
                        "media_player", "volume_set",
                        {"entity_id": hold.entity_id, "volume_level": hold.previous_volume},
                        blocking=True,
                    )
                except Exception as err:
                    _LOGGER.warning("Could not restore volume on %s: %s", hold.entity_id, err)
            if hold.previous_muted and hass.services.has_service("media_player", "volume_mute"):
                try:
                    await hass.services.async_call(
                        "media_player", "volume_mute",
                        {"entity_id": hold.entity_id, "is_volume_muted": True},
                        blocking=True,
                    )
                except Exception as err:
                    _LOGGER.warning("Could not restore mute on %s: %s", hold.entity_id, err)


class _Hold:
    """How to put one player back after the sentence."""

    def __init__(
        self, entity_id: str, sonos: bool, previous_volume: float | None, previous_muted: bool = False,
    ) -> None:
        self.entity_id = entity_id
        self.sonos = sonos
        self.previous_volume = previous_volume
        self.previous_muted = previous_muted
