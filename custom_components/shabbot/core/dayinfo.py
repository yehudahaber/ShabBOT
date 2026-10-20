"""Hebrew date, parasha, Daf Yomi, and the day's zmanim.

Calendar facts come from ``hdate`` (the library Home Assistant's Jewish Calendar
uses). Candle lighting and havdalah do not: they use ShabBOT's own sunset and the
candle-lighting, Shabbat havdalah, and Yom Tov end settings, so they match the
rest of the integration, including early Shabbat.

Hebrew day boundary
-------------------
A clock time uses shkia (sunset). Before shkia, the Hebrew date, the weekly
parasha, and Daf Yomi are the civil date's. At shkia they advance to the next
civil date. Both values are always returned (``civil_hebrew_date`` and
``halachic_hebrew_date``). ``hebrew_date`` is the one in effect.

A bare date, with no time, is the daytime of that civil day: no shkia rollover.
The zmanim are always the civil date's, including havdalah later that evening,
so a motzei Shabbat question still sees havdalah after the Hebrew date has moved on.

Israel and the diaspora
-----------------------
The parasha and the Yom Tov schedule follow ``Minhag.israel``, which is the
existing Israel checkbox. On first setup that box is filled in from Home
Assistant (country IL, or the map pin inside Israel). After that the box wins,
even if the map says something else.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any

from hdate import HDateInfo, HebrewDate, HolidayTypes, Location, Zmanim
from hdate.daf_yomi import DafYomiDatabase
from hdate.translator import context_language

from . import astro, jcal

# Inclusive box around the State of Israel: Eilat through Metula, the coast
# through the Golan. Beirut, Damascus, Amman, and Cairo fall outside. A bit of
# the southern Arava can fall inside. This only seeds the Israel checkbox.
ISRAEL_LATITUDE = (29.45, 33.40)
ISRAEL_LONGITUDE = (34.22, 35.88)

# hdate calls Cheshvan "Marcheshvan". The spoken form used here is Cheshvan.
_MONTH_EN = {"Marcheshvan": "Cheshvan"}

# Public key -> hdate Zmanim attribute. Tzeit is 8.5° (three medium stars).
# Misheyakir is hdate's talit-and-tefillin time, 11° below the horizon.
_HDATE_KEYS = (
    ("alot_hashachar", "alot_hashachar"),
    ("misheyakir", "talit_and_tefillin"),
    ("netz", "netz_hachama"),
    ("sof_zman_shema_mga", "sof_zman_shema_mga"),
    ("sof_zman_shema_gra", "sof_zman_shema_gra"),
    ("sof_zman_tefilla_mga", "sof_zman_tfilla_mga"),
    ("sof_zman_tefilla_gra", "sof_zman_tfilla_gra"),
    ("chatzot", "chatzot_hayom"),
    ("mincha_gedola", "mincha_gedola"),
    ("mincha_ketana", "mincha_ketana"),
    ("plag_hamincha", "plag_hamincha"),
    ("shkia", "shkia"),
    ("tzeit", "tset_hakohavim_shabbat"),
)

ZMAN_LABELS: dict[str, tuple[str, str]] = {
    "alot_hashachar": ("Alot HaShachar", "עלות השחר"),
    "misheyakir": ("Misheyakir", "משיכיר"),
    "netz": ("Netz", "הנץ החמה"),
    "sof_zman_shema_mga": ("Sof zman Shema MGA", "סוף זמן קריאת שמע מג״א"),
    "sof_zman_shema_gra": ("Sof zman Shema GRA", "סוף זמן קריאת שמע גר״א"),
    "sof_zman_tefilla_mga": ("Sof zman tefilla MGA", "סוף זמן תפילה מג״א"),
    "sof_zman_tefilla_gra": ("Sof zman tefilla GRA", "סוף זמן תפילה גר״א"),
    "chatzot": ("Chatzot", "חצות"),
    "mincha_gedola": ("Mincha gedola", "מנחה גדולה"),
    "mincha_ketana": ("Mincha ketana", "מנחה קטנה"),
    "plag_hamincha": ("Plag haMincha", "פלג המנחה"),
    "shkia": ("Shkia", "שקיעה"),
    "tzeit": ("Tzeit", "צאת הכוכבים"),
    "candle_lighting": ("Candle lighting", "הדלקת נרות"),
    "havdalah": ("Havdalah", "הבדלה"),
}

# What the phone briefing says, in the order we prefer when we have to shorten.
_SPOKEN = (
    ("candle_lighting", "Candle lighting"),
    ("havdalah", "Havdalah"),
    ("shkia", "shkia"),
    ("netz", "Sunrise"),
    ("sof_zman_shema_gra", "Sof zman Shema"),
)
_SPOKEN_LABEL = dict(_SPOKEN)
_READING_TYPES = (HolidayTypes.YOM_TOV, HolidayTypes.HOL_HAMOED)

HEBREW_DATE_NOTE = (
    "The Hebrew day begins at shkia. hebrew_date, the parasha, and Daf Yomi follow it "
    "when this is the current time; civil_hebrew_date stays on the civil day. "
    "A date with no time is that civil day's daytime Hebrew date. "
    "Zmanim stay on the civil date, so havdalah is still listed after shkia."
)
ZMANIM_NOTE = (
    "Alot HaShachar through tzeit are calculated by hdate, the same library as "
    "Home Assistant's Jewish Calendar. Misheyakir is 11° below the horizon. "
    "Tzeit is 8.5° below the horizon. Candle lighting and havdalah use ShabBOT's "
    "sunset and the configured candle-lighting, Shabbat havdalah, and Yom Tov end "
    "settings, and are null when they do not apply that evening."
)
ISRAEL_NOTE = (
    "The Israel checkbox chooses the Israel or Chutz La'aretz schedule for the "
    "parasha and for Yom Tov. On setup the box starts checked when Home Assistant's "
    "country is IL or its location is inside Israel. After that, the box is the setting."
)


def location_is_israel(latitude: float | None, longitude: float | None, country: str | None) -> bool:
    """Whether Home Assistant's location should start the Israel checkbox checked.

    True when the country is IL, or when latitude/longitude fall in Israel.
    This does not change a checkbox the user has already saved.
    """
    if (country or "").strip().upper() == "IL":
        return True
    if latitude is None or longitude is None:
        return False
    lat_min, lat_max = ISRAEL_LATITUDE
    lon_min, lon_max = ISRAEL_LONGITUDE
    return lat_min <= float(latitude) <= lat_max and lon_min <= float(longitude) <= lon_max


@contextmanager
def _language(lang: str):
    """hdate translates through a context-local language. Always put it back."""
    token = context_language.set(lang)  # type: ignore[arg-type]
    try:
        yield
    finally:
        context_language.reset(token)


def _friendly_holiday(name: str) -> str:
    if name.startswith("Hol hamoed"):
        return "Chol HaMoed" + name[len("Hol hamoed"):]
    return name


def _is_blank_parasha(name: str) -> bool:
    return name.casefold() in {"none", ""}


def _shabbat_on_or_after(day: date) -> date:
    return day + timedelta(days=(5 - day.weekday()) % 7)


def _speak_clock(moment: datetime) -> str:
    """12-hour clock, rounded to the nearest minute: '7:12 AM'."""
    rounded = (moment + timedelta(seconds=30)).replace(second=0, microsecond=0)
    hour = rounded.hour % 12 or 12
    suffix = "AM" if rounded.hour < 12 else "PM"
    return f"{hour}:{rounded.minute:02d} {suffix}"


def _and_join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


@lru_cache(maxsize=32)
def _hdate_times(
    day: date, latitude: float, longitude: float, time_zone: str, altitude: float,
) -> tuple[tuple[str, datetime], ...]:
    location = Location("shabbot", latitude, longitude, time_zone, altitude, diaspora=True)
    zmanim = Zmanim(date=day, location=location)
    return tuple((key, getattr(zmanim, attr).local) for key, attr in _HDATE_KEYS)


def _times(day: date, loc: astro.Location, minhag: jcal.Minhag) -> dict[str, datetime]:
    altitude = float(loc.elevation_m) if minhag.use_elevation else 0.0
    pairs = _hdate_times(day, round(loc.latitude, 6), round(loc.longitude, 6), loc.time_zone, round(altitude, 1))
    return dict(pairs)


def next_rollover(moment: datetime, loc: astro.Location, minhag: jcal.Minhag) -> datetime:
    """The next shkia at which the Hebrew date advances. Strictly after ``moment``."""
    local = moment.astimezone(loc.tzinfo)
    shkia = _times(local.date(), loc, minhag)["shkia"]
    if local < shkia:
        return shkia
    return _times(local.date() + timedelta(days=1), loc, minhag)["shkia"]


def _hebrew_text(day: date) -> HebrewDateText:
    hebrew_date = HebrewDate.from_gdate(day)
    with _language("en"):
        month_en = _MONTH_EN.get(str(hebrew_date.month), str(hebrew_date.month))
    with _language("he"):
        hebrew = str(hebrew_date)
        month_he = str(hebrew_date.month)
    return HebrewDateText(
        english=f"{hebrew_date.day} {month_en} {hebrew_date.year}",
        hebrew=hebrew,
        day=hebrew_date.day,
        month=month_en,
        month_hebrew=month_he,
        year=hebrew_date.year,
    )


def _reading(day: date, israel: bool) -> tuple[str | None, str | None, str | None, str | None]:
    """Parasha and Yom Tov/Chol HaMoed names in English and Hebrew.

    hdate reports ``none`` when a holiday reading replaces the weekly parasha.
    """
    diaspora = not israel
    with _language("en"):
        info = HDateInfo(day, diaspora=diaspora)
        parasha = None if _is_blank_parasha(info.parasha) else info.parasha
        holiday = " / ".join(
            _friendly_holiday(str(item)) for item in info.holidays if item.type in _READING_TYPES
        ) or None
    with _language("he"):
        info = HDateInfo(day, diaspora=diaspora)
        parasha_he = None if _is_blank_parasha(info.parasha) else info.parasha
        holiday_he = " / ".join(str(item) for item in info.holidays if item.type in _READING_TYPES) or None
    return parasha, parasha_he, holiday, holiday_he


def _daf(day: date) -> tuple[str, str, str, str, int]:
    masechta = DafYomiDatabase().lookup(day)
    with _language("en"):
        english = str(masechta)
        name = masechta.get_translation(masechta.name)
    with _language("he"):
        hebrew = str(masechta)
        name_he = masechta.get_translation(masechta.name)
    return english, hebrew, name, name_he, masechta.pages


def _boundaries(
    day: date, loc: astro.Location, minhag: jcal.Minhag,
) -> tuple[datetime | None, datetime | None, str | None]:
    """Candle lighting and havdalah for one civil evening, or None when not relevant.

    Candles are lit before shkia on the first night of Shabbat or Yom Tov, and on
    any evening that leads into Shabbat. Early Shabbat, when it applies, moves
    that Friday time. Havdalah is only when issur melacha ends that evening:
    the Shabbat setting on Shabbat, otherwise the Yom Tov end offset.
    """
    tomorrow = day + timedelta(days=1)
    today_issur = jcal.is_issur_day(day, minhag.israel)
    tomorrow_issur = jcal.is_issur_day(tomorrow, minhag.israel)
    zman = jcal.Zmanim(day, loc, minhag)

    candle: datetime | None = None
    if tomorrow_issur and (tomorrow.weekday() == 5 or not today_issur):
        early = jcal._early_shabbat_start(tomorrow, zman, minhag) if tomorrow.weekday() == 5 else None
        candle = early or zman.candle_lighting

    if today_issur and not tomorrow_issur:
        kind = "shabbat" if day.weekday() == 5 else "yom_tov"
        return candle, zman.issur_end, kind
    return candle, None, None


class HebrewDateText:
    """One Hebrew date in English transliteration and in Hebrew."""

    def __init__(self, english: str, hebrew: str, day: int, month: str, month_hebrew: str, year: int) -> None:
        self.english = english
        self.hebrew = hebrew
        self.day = day
        self.month = month
        self.month_hebrew = month_hebrew
        self.year = year

    def as_dict(self) -> dict[str, Any]:
        return {
            "english": self.english,
            "hebrew": self.hebrew,
            "day": self.day,
            "month": self.month,
            "month_hebrew": self.month_hebrew,
            "year": self.year,
        }


class DayInfo:
    """Everything a dashboard, a voice assistant, or the morning phone call needs."""

    def __init__(
        self,
        *,
        civil_date: date,
        hebrew_day: date,
        rollover: str,
        moment: datetime | None,
        israel: bool,
        hebrew_date: HebrewDateText,
        civil_hebrew_date: HebrewDateText,
        halachic_hebrew_date: HebrewDateText,
        parasha_english: str | None,
        parasha_hebrew: str | None,
        holiday_english: str | None,
        holiday_hebrew: str | None,
        shabbat: date,
        daf_english: str,
        daf_hebrew: str,
        masechet: str,
        masechet_hebrew: str,
        daf: int,
        zmanim: dict[str, datetime],
        candle_lighting: datetime | None,
        havdalah: datetime | None,
        havdalah_kind: str | None,
        loc: astro.Location,
        minhag: jcal.Minhag,
    ) -> None:
        self.civil_date = civil_date
        self.hebrew_day = hebrew_day
        self.rollover = rollover
        self.moment = moment
        self.israel = israel
        self.hebrew_date = hebrew_date
        self.civil_hebrew_date = civil_hebrew_date
        self.halachic_hebrew_date = halachic_hebrew_date
        self.parasha_english = parasha_english
        self.parasha_hebrew = parasha_hebrew
        self.holiday_english = holiday_english
        self.holiday_hebrew = holiday_hebrew
        self.shabbat = shabbat
        self.daf_english = daf_english
        self.daf_hebrew = daf_hebrew
        self.masechet = masechet
        self.masechet_hebrew = masechet_hebrew
        self.daf = daf
        self.zmanim = zmanim
        self.candle_lighting = candle_lighting
        self.havdalah = havdalah
        self.havdalah_kind = havdalah_kind
        self._loc = loc
        self._minhag = minhag

    @property
    def reading_kind(self) -> str:
        return "holiday" if self.parasha_english is None else "parasha"

    @property
    def reading_english(self) -> str:
        if self.parasha_english:
            return self.parasha_english
        return self.holiday_english or "No weekly reading"

    @property
    def reading_hebrew(self) -> str:
        if self.parasha_hebrew:
            return self.parasha_hebrew
        return self.holiday_hebrew or self.reading_english

    def time(self, key: str) -> datetime | None:
        if key == "candle_lighting":
            return self.candle_lighting
        if key == "havdalah":
            return self.havdalah
        return self.zmanim.get(key)

    def next_zman(self) -> tuple[str, datetime] | None:
        """The next named zman still ahead of ``moment``, including candles and havdalah."""
        if self.moment is None:
            return None
        ahead = [(key, when) for key in (*self.zmanim, "candle_lighting", "havdalah")
                 if (when := self.time(key)) is not None and when > self.moment]
        if not ahead:
            return None
        return min(ahead, key=lambda item: item[1])

    def summary(self) -> str:
        """A short sentence for TTS: Hebrew date, parasha, daf, and a few zmanim."""
        opener = f"{self.hebrew_date.english}." if self.moment is None else f"Today is {self.hebrew_date.english}."
        if self.reading_kind == "holiday":
            reading = f"This Shabbat the reading is {self.reading_english}."
        elif self.holiday_english:
            reading = f"This week's parasha is {self.parasha_english}. It is also {self.holiday_english}."
        else:
            reading = f"This week's parasha is {self.parasha_english}."
        daf = f"Daf Yomi is {self.masechet}, daf {self.daf}."
        zmanim = self._zman_sentence()
        return " ".join(part for part in (opener, reading, daf, zmanim) if part)

    def _zman_sentence(self) -> str:
        if self.moment is None:
            phrases = []
            for key in ("netz", "candle_lighting", "shkia", "havdalah"):
                moment = self.time(key)
                if moment is not None:
                    phrases.append(f"{_SPOKEN_LABEL[key]} is at {_speak_clock(moment)}")
            return f"{_and_join(phrases)}." if phrases else ""

        upcoming: list[tuple[datetime, str]] = []
        for key, label in _SPOKEN:
            moment = self.time(key)
            if moment is not None and self.moment is not None and moment > self.moment:
                upcoming.append((moment, label))
        if self.hebrew_day > self.civil_date and len(upcoming) < 2:
            sunrise = _times(self.civil_date + timedelta(days=1), self._loc, self._minhag)["netz"]
            upcoming.append((sunrise, "Tomorrow's sunrise"))
        upcoming.sort(key=lambda item: item[0])
        phrases = [f"{label} is at {_speak_clock(when)}" for when, label in upcoming[:3]]
        if not phrases:
            shkia = self.time("shkia")
            return f"Shkia was at {_speak_clock(shkia)}." if shkia else ""
        return f"{_and_join(phrases)}."

    def as_dict(self) -> dict[str, Any]:
        times: dict[str, str | None] = {key: value.isoformat() for key, value in self.zmanim.items()}
        times["candle_lighting"] = self.candle_lighting.isoformat() if self.candle_lighting else None
        times["havdalah"] = self.havdalah.isoformat() if self.havdalah else None
        nxt = self.next_zman()
        return {
            "date": self.civil_date.isoformat(),
            "hebrew_day": self.hebrew_day.isoformat(),
            "rollover": self.rollover,
            "israel": self.israel,
            "hebrew_date": self.hebrew_date.as_dict(),
            "civil_hebrew_date": self.civil_hebrew_date.as_dict(),
            "halachic_hebrew_date": self.halachic_hebrew_date.as_dict(),
            "parasha": {
                "english": self.reading_english,
                "hebrew": self.reading_hebrew,
                "kind": self.reading_kind,
                "parasha_english": self.parasha_english,
                "parasha_hebrew": self.parasha_hebrew,
                "holiday_english": self.holiday_english,
                "holiday_hebrew": self.holiday_hebrew,
                "shabbat": self.shabbat.isoformat(),
            },
            "daf_yomi": {
                "english": self.daf_english,
                "hebrew": self.daf_hebrew,
                "masechet": self.masechet,
                "masechet_hebrew": self.masechet_hebrew,
                "daf": self.daf,
            },
            "zmanim": times,
            "zmanim_names": {
                key: {"english": english, "hebrew": hebrew} for key, (english, hebrew) in ZMAN_LABELS.items()
            },
            "havdalah_kind": self.havdalah_kind,
            "next_zman": nxt[0] if nxt else None,
            "summary": self.summary(),
            "notes": {
                "hebrew_date": HEBREW_DATE_NOTE,
                "zmanim": ZMANIM_NOTE,
                "israel": ISRAEL_NOTE,
            },
        }


def build_day_info(when: date | datetime, loc: astro.Location, minhag: jcal.Minhag) -> DayInfo:
    """Day info for a civil date, or for a timezone-aware moment (shkia rollover)."""
    if isinstance(when, datetime):
        if when.tzinfo is None:
            raise ValueError("datetime must be timezone-aware")
        moment = when.astimezone(loc.tzinfo)
        civil = moment.date()
        shkia = _times(civil, loc, minhag)["shkia"]
        hebrew_day = civil + timedelta(days=1) if moment >= shkia else civil
        rollover = "shkia"
    elif isinstance(when, date):
        moment = None
        civil = when
        hebrew_day = when
        rollover = "daytime"
    else:
        raise TypeError("when must be a date or a timezone-aware datetime")

    parasha_en, parasha_he, holiday_en, holiday_he = _reading(hebrew_day, minhag.israel)
    daf_en, daf_he, masechet, masechet_he, daf_num = _daf(hebrew_day)
    candle, havdalah, havdalah_kind = _boundaries(civil, loc, minhag)
    return DayInfo(
        civil_date=civil,
        hebrew_day=hebrew_day,
        rollover=rollover,
        moment=moment,
        israel=minhag.israel,
        hebrew_date=_hebrew_text(hebrew_day),
        civil_hebrew_date=_hebrew_text(civil),
        halachic_hebrew_date=_hebrew_text(hebrew_day),
        parasha_english=parasha_en,
        parasha_hebrew=parasha_he,
        holiday_english=holiday_en,
        holiday_hebrew=holiday_he,
        shabbat=_shabbat_on_or_after(hebrew_day),
        daf_english=daf_en,
        daf_hebrew=daf_he,
        masechet=masechet,
        masechet_hebrew=masechet_he,
        daf=daf_num,
        zmanim=_times(civil, loc, minhag),
        candle_lighting=candle,
        havdalah=havdalah,
        havdalah_kind=havdalah_kind,
        loc=loc,
        minhag=minhag,
    )
