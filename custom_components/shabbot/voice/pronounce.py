"""Respell Hebrew and Yiddish words before they are sent to TTS.

The map is whole-word and case-insensitive. Longer phrases are applied first,
so "Rosh Hashana I" does not also get a second pass on "Rosh Hashana".
Replacements are plain English syllables, which Piper (en_US) and Kokoro both
read without engine-specific phonemes.

``apply_pronunciation`` only uses the map it is given. The map that actually
reaches TTS is built in ``lexicon.effective_lexicon``: the built-in list, then
the saved rows, then an optional YAML file.
"""

from __future__ import annotations

import re
from typing import Any

# Keys are matched case-insensitively. apply_pronunciation sorts by length.
DEFAULT_PRONUNCIATIONS: dict[str, str] = {
    "eruv tavshilin": "eh-roov tahv-shee-lin",
    "rosh hashana ii": "rohsh hah-shah-nah the second",
    "rosh hashana i": "rohsh hah-shah-nah the first",
    "rosh hashana": "rohsh hah-shah-nah",
    "yom kippur": "yohm kih-poor",
    "shmini atzeret / simchat torah": "shmee-nee aht-zeh-ret sim-khaht toh-rah",
    "shemini atzeret / simchat torah": "shmee-nee aht-zeh-ret sim-khaht toh-rah",
    "shmini atzeret": "shmee-nee aht-zeh-ret",
    "shemini atzeret": "shmee-nee aht-zeh-ret",
    "simchat torah": "sim-khaht toh-rah",
    "sukkot ii": "soo-koht the second",
    "sukkot i": "soo-koht the first",
    "sukkot": "soo-koht",
    "pesach viii": "peh-sahkh the eighth",
    "pesach vii": "peh-sahkh the seventh",
    "pesach ii": "peh-sahkh the second",
    "pesach i": "peh-sahkh the first",
    "pesach": "peh-sahkh",
    "shavuot ii": "shah-voo-oht the second",
    "shavuot i": "shah-voo-oht the first",
    "shavuot": "shah-voo-oht",
    "motzei shabbat": "moht-zay shah-baht",
    "motzaei shabbat": "moht-zay shah-baht",
    "yom tov": "yohm tohv",
    "motzei": "moht-zay",
    "motzaei": "moht-zay",
    "shabbat": "shah-baht",
    "shabbos": "shah-bus",
    "havdalah": "hahv-dah-lah",
    "melacha": "meh-lah-khah",
    "muttar": "moo-tahr",
    "shkia": "shkee-ah",
    "chag": "khahg",
    "erev": "eh-rev",
    "eruv": "eh-roov",
    "tavshilin": "tahv-shee-lin",
    "tzeit": "tzayt",
    "issur": "ee-soor",
    "yomtov": "yohm tohv",
}

_MAX_ENTRIES = 80
_MAX_KEY = 80
_MAX_VALUE = 160
_KEY_RE = re.compile(r"^[\w][\w\s'’./-]*$")


def apply_pronunciation(text: str, mapping: dict[str, str] | None) -> str:
    """Replace whole words and phrases. Unknown text is left as written."""
    if not text or not mapping:
        return text
    items = [(src.strip(), dst.strip()) for src, dst in mapping.items() if src.strip() and dst.strip()]
    items.sort(key=lambda item: len(item[0]), reverse=True)
    spoken = text
    for src, dst in items:
        parts = [re.escape(part) for part in src.split()]
        pattern = r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)"
        spoken = re.sub(pattern, lambda _match, dst=dst: dst, spoken, flags=re.IGNORECASE)
    return spoken


def coerce_pronunciations(value: Any, *, max_entries: int = _MAX_ENTRIES) -> dict[str, str]:
    """Validate a user map. This does not fill in defaults; the caller does that when the key is absent."""
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("Pronunciations must be a mapping of words to respellings")
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip().lower()
        if not key:
            continue
        if len(key) > _MAX_KEY or not _KEY_RE.match(key):
            raise ValueError(f"Pronunciation word {raw_key!r} is not a simple word or phrase")
        if not isinstance(raw_value, str):
            raise ValueError(f"Pronunciation for {key} must be text")
        says = raw_value.strip()
        if not says:
            continue
        if len(says) > _MAX_VALUE:
            raise ValueError(f"Pronunciation for {key} is too long")
        cleaned[key] = says
    if len(cleaned) > max_entries:
        raise ValueError(f"At most {max_entries} pronunciations")
    return cleaned
