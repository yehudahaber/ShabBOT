"""Pre-rendered announcement audio in Home Assistant's local media folder.

Files live in ``<media>/shabbot/`` and are played as
``media-source://media_source/local/shabbot/<file>``, which Sonos can fetch
through Home Assistant. The index records the clip length so the final
"stop all melacha" warning can be scheduled to finish on its mark.

A missing file, or a TTS engine that is not ready, is not an error here.
The announcer falls back to live ``tts.speak``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import logging
from pathlib import Path
import wave

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

INDEX_NAME = "index.json"
CUE_NAME = "soft_cue.wav"
BUNDLED_CUE_SECONDS = 0.5
BUNDLED_CUE = Path(__file__).parent / "assets" / CUE_NAME
MEDIA_SOURCE_PREFIX = "media-source://media_source/local/shabbot"

# MPEG-1 / MPEG-2 Layer III bitrates, index 0 and 15 unused.
_MP3_BITRATES = {
    3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    0: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
}
_MP3_RATES = {
    3: (44100, 48000, 32000),
    2: (22050, 24000, 16000),
    0: (11025, 12000, 8000),
}


@dataclass(frozen=True, slots=True)
class Clip:
    """One rendered sentence on disk."""

    text: str
    filename: str
    seconds: float | None

    @property
    def media_content_id(self) -> str:
        return f"{MEDIA_SOURCE_PREFIX}/{self.filename}"


def media_directory(hass: HomeAssistant) -> Path:
    """The shabbot folder inside HA's local media directory."""
    dirs = getattr(hass.config, "media_dirs", None) or {}
    base = dirs.get("local") or hass.config.path("media")
    return Path(base) / "shabbot"


def install_cue(directory: Path) -> Clip | None:
    """Copy the packaged soft cue into the media folder so players can fetch it.

    Blocking file I/O: run on the executor. Returns None if the copy fails.
    """
    try:
        data = BUNDLED_CUE.read_bytes()
        target = directory / CUE_NAME
        if not target.is_file() or target.stat().st_size != len(data):
            directory.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except OSError as err:
        _LOGGER.warning("Could not install the bundled announcement cue: %s", err)
        return None
    return Clip(text="", filename=CUE_NAME, seconds=audio_seconds(data, "wav"))


def sniff_extension(data: bytes) -> str:
    """File extension from the audio header. Unknown bytes are stored as mp3."""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return "mp3"


def audio_seconds(data: bytes, extension: str) -> float | None:
    """Clip length in seconds, when the format is one we can read without ffmpeg."""
    if extension == "wav":
        return _wav_seconds(data)
    if extension == "mp3":
        return _mp3_seconds(data)
    return None


def _wav_seconds(data: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(data)) as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
    except (wave.Error, EOFError):
        return None
    if rate <= 0 or frames < 0:
        return None
    return frames / float(rate)


def _mp3_seconds(data: bytes) -> float | None:
    """Sum MPEG frame durations. ID3v2 at the front is skipped."""
    offset = _id3_size(data)
    total = 0.0
    frames = 0
    limit = min(len(data), offset + 8_000_000)
    while offset + 4 <= limit and frames < 20_000:
        header = int.from_bytes(data[offset:offset + 4], "big")
        parsed = _mp3_frame(header)
        if parsed is None:
            offset += 1
            continue
        frame_len, frame_seconds = parsed
        if frame_len < 4 or offset + frame_len > len(data):
            break
        total += frame_seconds
        frames += 1
        offset += frame_len
    if frames == 0:
        return None
    return total


def _id3_size(data: bytes) -> int:
    if len(data) < 10 or data[:3] != b"ID3":
        return 0
    size = 0
    for byte in data[6:10]:
        size = (size << 7) | (byte & 0x7F)
    return 10 + size


def _mp3_frame(header: int) -> tuple[int, float] | None:
    if header & 0xFFE00000 != 0xFFE00000:
        return None
    version_id = (header >> 19) & 0b11
    layer = (header >> 17) & 0b11
    bitrate_idx = (header >> 12) & 0b1111
    rate_idx = (header >> 10) & 0b11
    padding = (header >> 9) & 0b1
    if version_id == 1 or layer == 0 or bitrate_idx in (0, 15) or rate_idx == 3:
        return None
    version = {3: 3, 2: 2, 0: 0}[version_id]
    bitrates = _MP3_BITRATES.get(version)
    rates = _MP3_RATES.get(version)
    if not bitrates or not rates:
        return None
    bitrate = bitrates[bitrate_idx] * 1000
    sample_rate = rates[rate_idx]
    if bitrate <= 0 or sample_rate <= 0:
        return None
    # layer bits 01 = III, 10 = II, 11 = I.
    if layer == 0b11:
        samples = 384
        frame_len = ((12 * bitrate // sample_rate) + padding) * 4
    elif version == 3 or layer != 0b01:
        samples = 1152
        frame_len = 144 * bitrate // sample_rate + padding
    else:
        samples = 576
        frame_len = 72 * bitrate // sample_rate + padding
    if frame_len < 4:
        return None
    return frame_len, samples / float(sample_rate)


def _signature(engine: str, voice: str, language: str) -> dict[str, str]:
    return {"engine": engine, "voice": voice, "language": language}


def _file_name(engine: str, voice: str, language: str, text: str, extension: str) -> str:
    raw = json.dumps([engine, voice, language, text], separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"{digest}.{extension}"


class ClipLibrary:
    """Persistent clips for one engine, voice, and language.

    Every method reads or writes the media folder. From the event loop, run
    them with ``hass.async_add_executor_job`` so Home Assistant does not report
    a blocking call.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(self, engine: str, voice: str, language: str) -> dict[str, Clip]:
        """Clips already rendered for this voice. A different voice returns nothing."""
        payload = self._read_index()
        if payload.get("signature") != _signature(engine, voice, language):
            return {}
        clips: dict[str, Clip] = {}
        for text, row in (payload.get("clips") or {}).items():
            if not isinstance(row, dict):
                continue
            filename = str(row.get("file") or "")
            if not filename or "/" in filename or "\\" in filename:
                continue
            path = self.directory / filename
            if not path.is_file():
                continue
            seconds = row.get("seconds")
            clips[str(text)] = Clip(
                text=str(text),
                filename=filename,
                seconds=float(seconds) if isinstance(seconds, (int, float)) and seconds > 0 else None,
            )
        return clips

    def store(self, engine: str, voice: str, language: str, text: str, audio: bytes) -> Clip:
        """Write one clip and update the index. Replaces the index if the voice changed."""
        self.directory.mkdir(parents=True, exist_ok=True)
        extension = sniff_extension(audio)
        filename = _file_name(engine, voice, language, text, extension)
        (self.directory / filename).write_bytes(audio)
        seconds = audio_seconds(audio, extension)
        payload = self._read_index()
        signature = _signature(engine, voice, language)
        if payload.get("signature") != signature:
            payload = {"signature": signature, "clips": {}}
        payload.setdefault("clips", {})[text] = {
            "file": filename,
            "seconds": seconds,
        }
        self._write_index(payload)
        return Clip(text=text, filename=filename, seconds=seconds)

    def drop_unreferenced(self, engine: str, voice: str, language: str) -> None:
        """Delete audio that this voice's index no longer names. No-op if the index is for another voice."""
        payload = self._read_index()
        if payload.get("signature") != _signature(engine, voice, language):
            return
        keep = {INDEX_NAME, CUE_NAME}
        for row in (payload.get("clips") or {}).values():
            if isinstance(row, dict) and row.get("file"):
                keep.add(str(row["file"]))
        if not self.directory.is_dir():
            return
        for path in self.directory.iterdir():
            if path.is_file() and path.name not in keep:
                path.unlink()

    def _read_index(self) -> dict:
        path = self.directory / INDEX_NAME
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_index(self, payload: dict) -> None:
        path = self.directory / INDEX_NAME
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def tts_ready(hass: HomeAssistant) -> bool:
    """True when the TTS integration has started and can render audio.

    Checked by key so importing the TTS package (and its optional deps) is
    not required just to decide that live speech is the fallback.
    """
    return "tts_manager" in hass.data


async def synthesize(hass: HomeAssistant, engine: str, language: str, voice: str, text: str) -> bytes:
    """Render one sentence to audio bytes. Raises if the engine cannot."""
    from homeassistant.components.tts import async_create_stream

    options = {"voice": voice} if voice else None
    stream = async_create_stream(hass, engine, language or None, options)
    stream.async_set_message(text)
    return b"".join([chunk async for chunk in stream.async_stream_result()])
