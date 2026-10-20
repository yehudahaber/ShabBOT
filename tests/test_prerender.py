"""Clip length and the on-disk library Sonos plays from."""

import io
from pathlib import Path
import wave

from custom_components.shabbot.voice.prerender import ClipLibrary, _mp3_seconds, audio_seconds, sniff_extension


def _wav(seconds: float, rate: int = 16000) -> bytes:
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def _mpeg1_frame() -> bytes:
    """One MPEG-1 Layer III frame: 128 kbps, 44.1 kHz, 1152 samples."""
    return bytes.fromhex("fffb9000") + bytes(413)


def test_wav_and_mp3_durations() -> None:
    wav = _wav(1.5)
    assert sniff_extension(wav) == "wav"
    assert audio_seconds(wav, "wav") == 1.5

    frame = _mpeg1_frame()
    assert sniff_extension(frame) == "mp3"
    assert _mp3_seconds(frame) == 1152 / 44100
    assert audio_seconds(b"not audio", "mp3") is None
    assert audio_seconds(b"OggSxxxx", "ogg") is None


def test_library_round_trip_is_keyed_by_voice(tmp_path: Path) -> None:
    library = ClipLibrary(tmp_path)
    clip = library.store("tts.piper", "en_US-lessac-high", "", "shkee-ah", _wav(2))
    assert clip.seconds == 2
    assert clip.media_content_id == f"media-source://media_source/local/shabbot/{clip.filename}"
    assert (tmp_path / clip.filename).is_file()

    loaded = library.load("tts.piper", "en_US-lessac-high", "")
    assert loaded["shkee-ah"].seconds == 2
    assert library.load("tts.piper", "3", "") == {}

    orphan = tmp_path / "old.wav"
    orphan.write_bytes(b"RIFF")
    library.drop_unreferenced("tts.piper", "en_US-lessac-high", "")
    assert not orphan.exists()
    assert (tmp_path / clip.filename).is_file()
