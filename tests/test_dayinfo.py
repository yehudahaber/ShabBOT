"""Hebrew date, parasha, Daf Yomi, and zmanim for the New York area."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shabbot.const import DOMAIN
from custom_components.shabbot.core import astro, jcal
from custom_components.shabbot.core.dayinfo import build_day_info, location_is_israel

BROOKLYN = astro.Location(40.6501, -73.94958, "America/New_York", 18)
JERUSALEM = astro.Location(31.7683, 35.2137, "Asia/Jerusalem", 754)
NY = ZoneInfo("America/New_York")

# hebcal.com zmanim for Brooklyn, elevation 0, 2026-10-20.
HEBCAL = {
    "alot_hashachar": "2026-10-20T05:51:10-04:00",
    "misheyakir": "2026-10-20T06:15:27-04:00",
    "netz": "2026-10-20T07:12:25-04:00",
    "sof_zman_shema_mga": "2026-10-20T09:15:40-04:00",
    "sof_zman_shema_gra": "2026-10-20T09:56:19-04:00",
    "sof_zman_tefilla_mga": "2026-10-20T10:23:50-04:00",
    "sof_zman_tefilla_gra": "2026-10-20T10:50:57-04:00",
    "chatzot": "2026-10-20T12:40:13-04:00",
    "mincha_gedola": "2026-10-20T13:07:32-04:00",
    "mincha_ketana": "2026-10-20T15:51:26-04:00",
    "plag_hamincha": "2026-10-20T16:59:44-04:00",
    "shkia": "2026-10-20T18:08:02-04:00",
    "tzeit": "2026-10-20T18:49:03-04:00",
}
# Pinned to hdate 1.2.1 at the same coordinates. Direct sun times stay within a
# couple of minutes of hebcal; proportional hours can drift a little more.
# hdate 1.2.1 with astral 2.2, the astral release Home Assistant 2026.9 ships.
HDATE = {
    "alot_hashachar": "2026-10-20T05:51:00-04:00",
    "misheyakir": "2026-10-20T06:18:00-04:00",
    "netz": "2026-10-20T07:13:00-04:00",
    "sof_zman_shema_mga": "2026-10-20T09:15:30-04:00",
    "sof_zman_shema_gra": "2026-10-20T09:55:00-04:00",
    "sof_zman_tefilla_mga": "2026-10-20T10:23:40-04:00",
    "sof_zman_tefilla_gra": "2026-10-20T10:49:00-04:00",
    "chatzot": "2026-10-20T12:40:00-04:00",
    "mincha_gedola": "2026-10-20T13:04:00-04:00",
    "mincha_ketana": "2026-10-20T15:46:00-04:00",
    "plag_hamincha": "2026-10-20T17:00:30-04:00",
    "shkia": "2026-10-20T18:08:00-04:00",
    "tzeit": "2026-10-20T18:49:00-04:00",
}
SOLAR = {"alot_hashachar", "netz", "chatzot", "shkia", "tzeit"}


def _schema_default(schema, name: str):
    for key in schema.schema:
        if key == name:
            return key.default()
    raise KeyError(name)


def test_location_is_israel_from_country_or_coordinates() -> None:
    """The setup default: country IL, or a map pin inside Israel."""
    assert location_is_israel(31.7683, 35.2137, None)  # Jerusalem
    assert location_is_israel(32.0853, 34.7818, "US")  # Tel Aviv, even if the country is wrong
    assert location_is_israel(29.5577, 34.9519, None)  # Eilat
    assert location_is_israel(40.6501, -73.94958, "US") is False  # Brooklyn
    assert location_is_israel(40.6501, -73.94958, "IL")  # country wins
    assert location_is_israel(40.6501, -73.94958, "il")
    assert location_is_israel(33.8938, 35.5018, None) is False  # Beirut
    assert location_is_israel(31.9539, 35.9106, "JO") is False  # Amman
    assert location_is_israel(30.0444, 31.2357, "EG") is False  # Cairo
    assert location_is_israel(None, None, None) is False
    assert location_is_israel(None, None, "IL")


async def test_config_flow_defaults_to_diaspora_outside_israel(hass: HomeAssistant) -> None:
    hass.config.latitude, hass.config.longitude = 40.6501, -73.94958
    hass.config.country = "US"
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["type"] == "form"
    assert _schema_default(flow["data_schema"], "israel") is False


async def test_config_flow_defaults_to_israel_and_stores_an_override(hass: HomeAssistant) -> None:
    hass.config.latitude, hass.config.longitude = 31.7683, 35.2137
    hass.config.country = None
    hass.config.location_name = "Jerusalem"
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert _schema_default(flow["data_schema"], "israel") is True
    assert _schema_default(flow["data_schema"], "candle_lighting_min") == 40

    # The checkbox overrides the map: Jerusalem's pin, diaspora saved on purpose.
    created = await hass.config_entries.flow.async_configure(flow["flow_id"], {
        "candle_lighting_min": 18,
        "havdalah_mode": "degrees",
        "havdalah_degrees": 8.5,
        "havdalah_minutes": 50,
        "yom_tov_end_minutes": 42,
        "israel": False,
    })
    assert created["type"] == "create_entry"
    assert created["data"]["israel"] is False


def test_parasha_diverges_between_israel_and_the_diaspora() -> None:
    """5787: Shavuot II falls on Shabbat, so the schedules stay apart until Balak."""
    shavuot = date(2027, 6, 12)
    diaspora = build_day_info(shavuot, BROOKLYN, jcal.Minhag(israel=False))
    israel = build_day_info(shavuot, BROOKLYN, jcal.Minhag(israel=True))
    assert diaspora.reading_kind == "holiday"
    assert diaspora.reading_english == "Shavuot II"
    assert diaspora.reading_hebrew == "שני של שבועות"
    assert israel.reading_kind == "parasha"
    assert israel.reading_english == "Nasso"
    assert israel.reading_hebrew == "נשא"

    balak = date(2027, 7, 17)
    diaspora = build_day_info(balak, BROOKLYN, jcal.Minhag(israel=False))
    israel = build_day_info(balak, BROOKLYN, jcal.Minhag(israel=True))
    assert diaspora.reading_english == "Chukat-Balak"
    assert israel.reading_english == "Balak"
    assert diaspora.reading_hebrew != israel.reading_hebrew


def test_yom_tov_week_uses_the_holiday_reading() -> None:
    pesach = build_day_info(date(2027, 4, 24), BROOKLYN, jcal.Minhag())
    assert pesach.reading_kind == "holiday"
    assert pesach.reading_english == "Chol HaMoed Pesach"
    assert pesach.reading_hebrew == "חול המועד פסח"
    assert pesach.parasha_english is None

    # Diaspora reads Shmini Atzeret; Israel reads Vezot Habracha on Simchat Torah.
    diaspora = build_day_info(date(2026, 10, 3), BROOKLYN, jcal.Minhag(israel=False))
    israel = build_day_info(date(2026, 10, 3), JERUSALEM, jcal.Minhag(israel=True))
    assert diaspora.reading_english == "Shmini Atzeret"
    assert diaspora.reading_kind == "holiday"
    assert israel.reading_english == "Vezot Habracha"
    assert israel.holiday_english is not None and "Simchat Torah" in israel.holiday_english


def test_israel_checkbox_overrides_the_location() -> None:
    """Brooklyn with the box checked follows Israel. Jerusalem unchecked stays diaspora."""
    shavuot = date(2027, 6, 12)
    assert build_day_info(shavuot, BROOKLYN, jcal.Minhag(israel=True)).reading_english == "Nasso"
    assert build_day_info(shavuot, JERUSALEM, jcal.Minhag(israel=False)).reading_english == "Shavuot II"


def test_daf_yomi_on_known_dates() -> None:
    # The 14th cycle opened on 5 January 2020 with Berachos 2. The day before is Niddah 73.
    eve = build_day_info(date(2020, 1, 4), BROOKLYN, jcal.Minhag())
    assert eve.masechet == "Niddah" and eve.daf == 73
    opening = build_day_info(date(2020, 1, 5), BROOKLYN, jcal.Minhag())
    assert opening.daf_english == "Berachos 2"
    assert opening.masechet == "Berachos" and opening.daf == 2
    assert opening.daf_hebrew == "ברכות ב"

    cheshvan = build_day_info(date(2026, 10, 20), BROOKLYN, jcal.Minhag())
    assert cheshvan.daf_english == "Bechoros 32"
    assert cheshvan.masechet == "Bechoros" and cheshvan.daf == 32
    assert cheshvan.masechet_hebrew == "בכורות"
    assert cheshvan.daf_hebrew == "בכורות לב"


def test_hebrew_date_rolls_at_shkia_and_keeps_the_civil_day() -> None:
    daytime = build_day_info(date(2026, 10, 20), BROOKLYN, jcal.Minhag())
    assert daytime.rollover == "daytime"
    assert daytime.hebrew_date.english == "9 Cheshvan 5787"
    assert daytime.hebrew_date.hebrew == 'ט\' מרחשוון ה\' תשפ"ז'
    assert daytime.civil_hebrew_date.english == daytime.halachic_hebrew_date.english

    shkia = daytime.zmanim["shkia"]
    before = build_day_info(shkia - timedelta(seconds=1), BROOKLYN, jcal.Minhag())
    after = build_day_info(shkia, BROOKLYN, jcal.Minhag())
    assert before.rollover == "shkia"
    assert before.hebrew_date.english == "9 Cheshvan 5787"
    assert before.daf == 32
    assert before.civil_hebrew_date.english == before.halachic_hebrew_date.english
    assert after.hebrew_date.english == "10 Cheshvan 5787"
    assert after.civil_hebrew_date.english == "9 Cheshvan 5787"
    assert after.halachic_hebrew_date.english == "10 Cheshvan 5787"
    assert after.daf == 33
    # Zmanim stay on the civil evening, so shkia itself does not jump to tomorrow.
    assert after.zmanim["shkia"] == shkia
    assert "Tomorrow's sunrise" in after.summary()


def test_parasha_advances_after_shabbat_shkia() -> None:
    shabbat = build_day_info(date(2026, 10, 24), BROOKLYN, jcal.Minhag())
    assert shabbat.reading_english == "Lech-Lecha"
    after = build_day_info(shabbat.zmanim["shkia"], BROOKLYN, jcal.Minhag())
    assert after.reading_english == "Vayera"


def test_zmanim_for_brooklyn_match_hdate_and_hebcal() -> None:
    info = build_day_info(date(2026, 10, 20), BROOKLYN, jcal.Minhag())
    for key, expected in HDATE.items():
        assert info.zmanim[key].isoformat() == expected, key
    for key, expected in HEBCAL.items():
        limit = 120 if key in SOLAR else 8 * 60
        gap = abs((info.zmanim[key] - datetime.fromisoformat(expected)).total_seconds())
        assert gap <= limit, (key, gap)
    # An ordinary Tuesday has neither candle lighting nor havdalah.
    assert info.candle_lighting is None and info.havdalah is None


def test_candle_lighting_and_havdalah_follow_the_configured_offsets() -> None:
    friday = build_day_info(date(2026, 10, 23), BROOKLYN, jcal.Minhag())
    friday_zman = jcal.Zmanim(date(2026, 10, 23), BROOKLYN, jcal.Minhag())
    assert friday.candle_lighting == friday_zman.candle_lighting
    assert friday.havdalah is None

    minhag = jcal.Minhag(havdalah_mode="minutes", havdalah_minutes=60, yom_tov_end_minutes=42)
    shabbat = build_day_info(date(2026, 10, 24), BROOKLYN, minhag)
    shabbat_zman = jcal.Zmanim(date(2026, 10, 24), BROOKLYN, minhag)
    assert shabbat.havdalah == shabbat_zman.havdalah
    assert shabbat.havdalah_kind == "shabbat"
    assert shabbat.candle_lighting is None
    gap = (shabbat.havdalah - shabbat_zman.sunset).total_seconds()
    assert 60 * 60 <= gap < 61 * 60

    # Rosh Hashana II, 13 Sep 2026, is a Sunday. It ends at the Yom Tov offset, not 60 minutes.
    yom_tov = build_day_info(date(2026, 9, 13), BROOKLYN, minhag)
    yom_tov_zman = jcal.Zmanim(date(2026, 9, 13), BROOKLYN, minhag)
    assert yom_tov.havdalah == yom_tov_zman.yom_tov_end
    assert yom_tov.havdalah_kind == "yom_tov"
    gap = (yom_tov.havdalah - yom_tov_zman.sunset).total_seconds()
    assert 42 * 60 <= gap < 43 * 60


def test_early_shabbat_moves_candle_lighting() -> None:
    early = jcal.Minhag(early_shabbat_time=time(19, 0), early_shabbat_after=time(19, 15))
    info = build_day_info(date(2027, 6, 25), BROOKLYN, early)
    assert info.candle_lighting == datetime(2027, 6, 25, 19, 0, tzinfo=NY)


def test_spoken_summary_for_a_morning_in_brooklyn() -> None:
    morning = datetime(2026, 10, 20, 8, 0, tzinfo=NY)
    info = build_day_info(morning, BROOKLYN, jcal.Minhag())
    assert info.summary() == (
        "Today is 9 Cheshvan 5787. This week's parasha is Lech-Lecha. "
        "Daf Yomi is Bechoros, daf 32. Sof zman Shema is at 9:55 AM, and shkia is at 6:08 PM."
    )
    daytime = build_day_info(date(2026, 10, 20), BROOKLYN, jcal.Minhag())
    assert daytime.summary().startswith("9 Cheshvan 5787.")
    assert "Sunrise is at 7:13 AM" in daytime.summary()


async def test_sensors_and_get_day_info_service(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(datetime(2026, 10, 20, 12, 0, tzinfo=NY))
    await hass.config.async_set_time_zone("America/New_York")
    hass.config.latitude, hass.config.longitude, hass.config.elevation = 40.6501, -73.94958, 18
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"candle_lighting_min": 18, "israel": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    keys = [
        "hebrew_date", "parasha", "daf_yomi", "zmanim", "alot_hashachar", "misheyakir", "netz",
        "sof_zman_shema_mga", "sof_zman_shema_gra", "sof_zman_tefilla_mga", "sof_zman_tefilla_gra",
        "chatzot", "mincha_gedola", "mincha_ketana", "plag_hamincha", "shkia", "tzeit",
    ]
    for key in keys:
        assert hass.states.get(f"sensor.shabbot_{key}") is not None, key

    hebrew = hass.states.get("sensor.shabbot_hebrew_date")
    assert hebrew.state == "9 Cheshvan 5787"
    assert "מרחשוון" in hebrew.attributes["hebrew"]
    assert hebrew.attributes["civil_english"] == "9 Cheshvan 5787"
    assert hass.states.get("sensor.shabbot_parasha").state == "Lech-Lecha"
    assert hass.states.get("sensor.shabbot_daf_yomi").state == "Bechoros 32"
    assert hass.states.get("sensor.shabbot_daf_yomi").attributes["daf"] == 32
    assert hass.states.get("sensor.shabbot_zmanim").state == "Chatzot"
    assert hass.states.get("sensor.shabbot_shkia").state.startswith("2026-10-20T22:08")

    response = await hass.services.async_call(DOMAIN, "get_day_info", {}, blocking=True, return_response=True)
    assert response["hebrew_date"]["english"] == "9 Cheshvan 5787"
    assert response["daf_yomi"]["masechet"] == "Bechoros"
    assert response["summary"].startswith("Today is 9 Cheshvan 5787.")
    assert response["zmanim"]["candle_lighting"] is None
    assert response["israel"] is False

    dated = await hass.services.async_call(
        DOMAIN, "get_day_info", {"date": "2027-06-12"}, blocking=True, return_response=True)
    assert dated["parasha"]["english"] == "Shavuot II"
    assert dated["rollover"] == "daytime"

    entry.runtime_data.settings["israel"] = True
    overridden = await hass.services.async_call(
        DOMAIN, "get_day_info", {"date": "2027-06-12"}, blocking=True, return_response=True)
    assert overridden["israel"] is True
    assert overridden["parasha"]["english"] == "Nasso"
