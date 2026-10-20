"""Respelling lexicon applied before any announcement or briefing reaches TTS.

Display text, sensors, and the ``text`` fields stay as written. ``spoken`` is
the same sentence after this map. Matching is whole-word and case-insensitive;
longer phrases are applied first (see ``apply_pronunciation``).

Merge order, later wins:

1. The built-in list (zmanim, Hebrew months, parasha names, masechtot, holidays).
2. The pronunciation rows saved in settings. They override individual words.
   They do not erase the built-in list.
3. An optional YAML file (``tts_lexicon_path``, for example ``/config/tts_lexicon.yaml``).

A blank path reads nothing. A missing or invalid file is logged and ignored.
To say a built-in word as it is spelled, set that word to itself in the file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
import yaml

from .pronounce import DEFAULT_PRONUNCIATIONS, apply_pronunciation, coerce_pronunciations

_LOGGER = logging.getLogger(__name__)

LEXICON_DEFAULTS: dict[str, Any] = {
    "tts_lexicon_path": "",
}

_FILE_MAX = 400

# Months, including hdate's "Marcheshvan" and the Cheshvan form shown in the UI.
_MONTHS: dict[str, str] = {
    "tishrei": "tish-ray",
    "marcheshvan": "mar-khesh-vahn",
    "cheshvan": "khesh-vahn",
    "kislev": "kis-lev",
    "tevet": "tay-vet",
    "sh'vat": "shvaht",
    "adar ii": "ah-dahr the second",
    "adar i": "ah-dahr the first",
    "adar": "ah-dahr",
    "nisan": "nee-sahn",
    "iyyar": "ee-yahr",
    "sivan": "see-vahn",
    "tammuz": "tah-mooz",
    "av": "ahv",
    "elul": "eh-lool",
}

# Weekly readings, including the combined diaspora sedrot. Hyphenated names are
# one token: the hyphen is not a word boundary.
_PARASHA: dict[str, str] = {
    "vayakhel-pekudei": "vah-yahk-hayl peh-koo-day",
    "tazria-metzora": "tahz-ree-ah meh-tzoh-rah",
    "achrei mot-kedoshim": "ahkh-ray moht keh-doh-sheem",
    "behar-bechukotai": "beh-hahr beh-khoo-koh-tai",
    "chukat-balak": "khoo-kaht bah-lahk",
    "matot-masei": "mah-toht mah-say",
    "nitzavim-vayeilech": "nee-tzah-veem vah-yay-lekh",
    "bereshit": "beh-ray-sheet",
    "noach": "noh-akh",
    "lech-lecha": "lekh lee-khah",
    "vayera": "vah-yay-rah",
    "chayei sara": "khah-yay sah-rah",
    "toldot": "tohl-doht",
    "vayetzei": "vah-yay-tzay",
    "vayishlach": "vah-yish-lakh",
    "vayeshev": "vah-yay-shev",
    "miketz": "mee-kaytz",
    "vayigash": "vah-yee-gahsh",
    "vayechi": "vah-yee-khee",
    "shemot": "shmoht",
    "vaera": "vah-ay-rah",
    "bo": "boh",
    "beshalach": "beh-shah-lakh",
    "yitro": "yis-roh",
    "mishpatim": "mish-pah-teem",
    "terumah": "teh-roo-mah",
    "tetzaveh": "teh-tzah-veh",
    "ki tisa": "kee tee-sah",
    "vayakhel": "vah-yahk-hayl",
    "pekudei": "peh-koo-day",
    "vayikra": "vah-yik-rah",
    "tzav": "tzahv",
    "shmini": "shmee-nee",
    "tazria": "tahz-ree-ah",
    "metzora": "meh-tzoh-rah",
    "achrei mot": "ahkh-ray moht",
    "kedoshim": "keh-doh-sheem",
    "emor": "eh-mor",
    "behar": "beh-hahr",
    "bechukotai": "beh-khoo-koh-tai",
    "bamidbar": "bah-mid-bahr",
    "nasso": "nah-soh",
    "beha'alotcha": "beh-hah-ah-loh-skhah",
    "sh'lach": "shlahkh",
    "korach": "koh-rahkh",
    "chukat": "khoo-kaht",
    "balak": "bah-lahk",
    "pinchas": "peen-khahs",
    "matot": "mah-toht",
    "masei": "mah-say",
    "devarim": "deh-vah-reem",
    "vaetchanan": "vah-es-khah-nahn",
    "eikev": "ay-kev",
    "re'eh": "reh-eh",
    "shoftim": "shohf-teem",
    "ki teitzei": "kee tay-tzay",
    "ki tavo": "kee tah-voh",
    "nitzavim": "nee-tzah-veem",
    "vayeilech": "vah-yay-lekh",
    "ha'azinu": "hah-ah-zee-noo",
    "vezot habracha": "veh-zoht hah-brah-khah",
}

_MASECHTOT: dict[str, str] = {
    "rosh hashanah": "rohsh hah-shah-nah",
    "avodah zarah": "ah-voh-dah zah-rah",
    "bava kamma": "bah-vah kah-mah",
    "bava metzia": "bah-vah meh-tzee-ah",
    "bava basra": "bah-vah bahs-rah",
    "moed katan": "moh-ed kah-tahn",
    "berachos": "beh-rah-khohs",
    "eruvin": "eh-roo-vin",
    "pesachim": "peh-sah-kheem",
    "shekalim": "sheh-kah-leem",
    "yoma": "yoh-mah",
    "succah": "soo-kah",
    "beitzah": "bay-tzah",
    "taanis": "tah-ah-nis",
    "megillah": "meh-gee-lah",
    "chagigah": "khah-gee-gah",
    "yevamos": "yeh-vah-moht",
    "kesubos": "keh-soo-bohs",
    "nedarim": "neh-dah-reem",
    "nazir": "nah-zeer",
    "sotah": "soh-tah",
    "gittin": "gee-tin",
    "kiddushin": "kee-doo-shin",
    "sanhedrin": "sahn-hed-rin",
    "makkos": "mah-koht",
    "shevuos": "sheh-voo-oht",
    "horayos": "hoh-rah-yoht",
    "zevachim": "zeh-vah-kheem",
    "menachos": "meh-nah-khoht",
    "chullin": "khoo-lin",
    "bechoros": "beh-khoh-rohs",
    "arachin": "ah-rah-khin",
    "temurah": "teh-moo-rah",
    "kereisos": "keh-ray-soht",
    "meilah": "meh-ee-lah",
    "niddah": "nih-dah",
}

_ZMANIM: dict[str, str] = {
    "sof zman shema mga": "sohf zmahn shmah em-gee-ah",
    "sof zman shema gra": "sohf zmahn shmah grah",
    "sof zman shema": "sohf zmahn shmah",
    "sof zman tefilla mga": "sohf zmahn teh-fee-lah em-gee-ah",
    "sof zman tefilla gra": "sohf zmahn teh-fee-lah grah",
    "sof zman tefilla": "sohf zmahn teh-fee-lah",
    "alot hashachar": "ah-loat hah-shah-khahr",
    "misheyakir": "mee-sheh-yah-keer",
    "mincha gedola": "min-khah geh-doh-lah",
    "mincha ketana": "min-khah keh-tah-nah",
    "plag hamincha": "plahg hah-min-khah",
    "chatzot": "khah-tzoht",
    "netz": "naytz",
    "mincha": "min-khah",
    "shema": "shmah",
    "tefilla": "teh-fee-lah",
    "zman": "zmahn",
}

# Holiday names that are not already in the small announcement map.
_HOLIDAYS: dict[str, str] = {
    "chol hamoed sukkot": "khol hah-moh-ed soo-koht",
    "hol hamoed sukkot": "khol hah-moh-ed soo-koht",
    "chol hamoed pesach": "khol hah-moh-ed peh-sahkh",
    "hol hamoed pesach": "khol hah-moh-ed peh-sahkh",
    "chol hamoed": "khol hah-moh-ed",
    "hol hamoed": "khol hah-moh-ed",
    "shushan purim": "shoo-shahn poo-rim",
    "tzom gedaliah": "tzohm geh-dahl-yah",
    "asara b'tevet": "ah-sah-rah beh-tay-vet",
    "ta'anit esther": "tah-ah-nit es-ter",
    "hoshana raba": "hoh-shah-nah rah-bah",
    "rosh chodesh": "rohsh khoh-desh",
    "yom haatzma'ut": "yohm hah-ahtz-mah-oot",
    "yom hazikaron": "yohm hah-zee-kah-rohn",
    "yom yerushalayim": "yohm yeh-roo-shah-lah-yim",
    "yom hashoah": "yohm hah-shoh-ah",
    "tish'a b'av": "tee-shah beh-ahv",
    "lag b'omer": "lahg boh-mer",
    "tu b'shvat": "too bish-vaht",
    "tu b'av": "too beh-ahv",
    "tzom tammuz": "tzohm tah-mooz",
    "chanukah": "khah-noo-kah",
    "purim": "poo-rim",
    "tzom": "tzohm",
}

_WORDS: dict[str, str] = {
    "daf yomi": "dahf yoh-mee",
    "masechet": "mah-seh-khet",
    "masechta": "mah-seh-khah",
    "parasha": "pah-rah-shah",
    "parashat": "pah-rah-shaht",
    "daf": "dahf",
}

BUILTIN_LEXICON: dict[str, str] = {
    **_MONTHS,
    **_PARASHA,
    **_MASECHTOT,
    **_ZMANIM,
    **_HOLIDAYS,
    **_WORDS,
    **{key.casefold(): value for key, value in DEFAULT_PRONUNCIATIONS.items()},
}


def effective_lexicon(
    settings: dict[str, Any] | None = None,
    file_map: dict[str, str] | None = None,
    *,
    allow_read: bool = True,
) -> dict[str, str]:
    """Built-in list, then saved rows, then the YAML file.

    ``allow_read`` must be false on the event loop. Pass a map loaded earlier,
    or an empty map when there is no file. An empty path never touches the disk.
    """
    merged = dict(BUILTIN_LEXICON)
    stored = (settings or {}).get("announce_pronunciations")
    if isinstance(stored, dict):
        try:
            merged.update(coerce_pronunciations(stored))
        except ValueError:
            _LOGGER.debug("Ignoring an invalid pronunciation list")
    path = str((settings or {}).get("tts_lexicon_path") or "").strip()
    extra = file_map
    if extra is None and path and allow_read:
        extra = load_lexicon_file(path)
    if extra:
        merged.update(extra)
    return merged


def speak(
    text: str,
    settings: dict[str, Any] | None = None,
    file_map: dict[str, str] | None = None,
) -> str:
    """Respell ``text``. Reads the YAML file when a path is set and no map was passed."""
    return apply_pronunciation(
        text,
        effective_lexicon(settings, file_map=file_map, allow_read=file_map is None),
    )


async def async_spoken(hass: HomeAssistant, text: str, settings: dict[str, Any] | None) -> str:
    """Respell ``text``, reading a configured YAML file off the event loop."""
    if not text:
        return text
    path = str((settings or {}).get("tts_lexicon_path") or "").strip()
    if not path:
        return apply_pronunciation(text, effective_lexicon(settings, file_map={}, allow_read=False))
    file_map = await hass.async_add_executor_job(load_lexicon_file, path)
    return apply_pronunciation(text, effective_lexicon(settings, file_map=file_map, allow_read=False))


def load_lexicon_file(path: str) -> dict[str, str]:
    """Read a YAML word map. Failure returns an empty map so speech still works."""
    file = Path(path)
    try:
        raw = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        _LOGGER.warning("TTS lexicon file not found: %s", path)
        return {}
    except OSError as err:
        _LOGGER.warning("Could not read TTS lexicon %s: %s", path, err)
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as err:
        _LOGGER.warning("TTS lexicon %s is not valid YAML: %s", path, err)
        return {}
    return _clean_file_map(data, path)


def _as_mapping(data: Any) -> dict[Any, Any] | None:
    if data is None:
        return {}
    if isinstance(data, dict):
        for key in ("words", "lexicon", "pronunciations"):
            inner = data.get(key)
            if isinstance(inner, dict):
                return inner
        return data
    if isinstance(data, list):
        merged: dict[Any, Any] = {}
        for item in data:
            if isinstance(item, dict):
                merged.update(item)
        return merged
    return None


def _clean_file_map(data: Any, path: str) -> dict[str, str]:
    mapping = _as_mapping(data)
    if mapping is None:
        _LOGGER.warning("TTS lexicon %s must be a map of words to respellings", path)
        return {}
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        if len(cleaned) >= _FILE_MAX:
            _LOGGER.warning("TTS lexicon %s stopped at %s entries", path, _FILE_MAX)
            break
        try:
            one = coerce_pronunciations({raw_key: raw_value}, max_entries=1)
        except ValueError as err:
            _LOGGER.warning("Skipping TTS lexicon entry %r in %s: %s", raw_key, path, err)
            continue
        cleaned.update(one)
    return cleaned
