"""Pronunciation map: whole words, case-insensitive, and it must not eat neighboring words."""

import pytest
import voluptuous as vol

from custom_components.shabbot.core.announcements import DEFAULT_TEMPLATES, options_from_settings
from custom_components.shabbot.core.jcal import _ISRAEL_NAMES, _YOM_TOV
from custom_components.shabbot.core.pronounce import DEFAULT_PRONUNCIATIONS, apply_pronunciation, coerce_pronunciations
from custom_components.shabbot.websocket import SETTINGS_SCHEMA


def _say(text: str, mapping: dict[str, str] | None = None) -> str:
    return apply_pronunciation(text, DEFAULT_PRONUNCIATIONS if mapping is None else mapping)


def test_shkia_is_one_word_and_case_insensitive() -> None:
    assert _say("shkia") == "shkee-ah"
    assert _say("Shkia") == "shkee-ah"
    assert _say("SHKIA") == "shkee-ah"
    assert _say("Shkia in one minute. Stop all melacha.") == (
        "shkee-ah in one minute. Stop all meh-lah-khah."
    )


def test_substitution_does_not_mangle_other_words() -> None:
    untouched = [
        "change",
        "changed",
        "shkiah",
        "preshkia",
        "melachas",
        "It's now 60 minutes until candle lighting",
        "the Shabbaton",
    ]
    for text in untouched:
        assert _say(text) == text
    # The word itself, with punctuation, still changes. The neighbors do not.
    assert _say("until shkia.") == "until shkee-ah."
    assert _say("shkia and shkia") == "shkee-ah and shkee-ah"


def test_longer_phrase_wins_over_the_words_inside_it() -> None:
    assert _say("motzaei Shabbat") == "moht-zay shah-baht"
    assert _say("Yom Tov") == "yohm tohv"
    assert _say("Pesach I on Shabbat") == "peh-sahkh the first on shah-baht"
    assert _say("Shmini Atzeret / Simchat Torah") == "shmee-nee aht-zeh-ret sim-khaht toh-rah"
    assert "pesach" not in _say("Pesach VIII").lower()
    assert "eighth" in _say("Pesach VIII")


def test_defaults_cover_template_words_and_every_holiday_name() -> None:
    sentence = DEFAULT_TEMPLATES["motzei"].format(minutes=42, unit="minutes")
    spoken = _say(sentence)
    assert "shkee-ah" in spoken
    assert "moo-tahr" in spoken
    assert "meh-lah-khah" in spoken
    assert "It's now 42 minutes" in spoken

    names = {holiday.name for holiday in _YOM_TOV.values()}
    names |= {holiday.name for holiday in _ISRAEL_NAMES.values()}
    names.add("Shabbat")
    for name in names:
        assert _say(name) != name, name


def test_user_map_replaces_defaults_instead_of_merging() -> None:
    options = options_from_settings({"announce_pronunciations": {"Shkia": "SHEE-kee-ah"}})
    assert options.pronunciations == {"shkia": "SHEE-kee-ah"}
    assert apply_pronunciation("shkia and melacha", options.pronunciations) == "SHEE-kee-ah and melacha"

    missing = options_from_settings({})
    assert missing.pronunciations["shkia"] == "shkee-ah"
    assert "melacha" in missing.pronunciations


def test_blank_respelling_drops_the_word_and_bad_keys_are_rejected() -> None:
    assert coerce_pronunciations({"chag": "  ", "erev": "eh-rev"}) == {"erev": "eh-rev"}
    with pytest.raises(ValueError):
        coerce_pronunciations({"shkia*": "nope"})
    with pytest.raises(vol.Invalid):
        SETTINGS_SCHEMA({"announce_pronunciations": ["shkia"]})
