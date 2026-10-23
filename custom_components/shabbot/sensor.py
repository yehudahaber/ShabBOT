"""Next candle lighting / havdalah, active overrides, and the Jewish day."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval

from . import ShabbotConfigEntry
from .core import jcal
from .core.dayinfo import ZMAN_LABELS, next_rollover
from .entity import ShabbotEntity

# Daily zmanim that always have a time. Candle lighting and havdalah are attributes
# on the zmanim sensor (they are null on an ordinary weekday).
_ZMAN_SENSORS: tuple[tuple[str, str], ...] = (
    ("alot_hashachar", "mdi:weather-sunset-up"),
    ("misheyakir", "mdi:glasses"),
    ("netz", "mdi:white-balance-sunny"),
    ("sof_zman_shema_mga", "mdi:book-open-variant"),
    ("sof_zman_shema_gra", "mdi:book-open-variant"),
    ("sof_zman_tefilla_mga", "mdi:hands-pray"),
    ("sof_zman_tefilla_gra", "mdi:hands-pray"),
    ("chatzot", "mdi:sun-clock"),
    ("mincha_gedola", "mdi:sun-clock"),
    ("mincha_ketana", "mdi:sun-clock"),
    ("plag_hamincha", "mdi:sun-clock"),
    ("shkia", "mdi:weather-sunset-down"),
    ("tzeit", "mdi:star-three-points"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ShabbotConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    manager = entry.runtime_data
    entities: list[ShabbotEntity] = [
        NextCandleLighting(manager),
        NextHavdalah(manager),
        ActiveOverrides(manager),
        HebrewDateSensor(manager),
        ParashaSensor(manager),
        DafYomiSensor(manager),
        ZmanimSensor(manager),
        *(_ZmanTimeSensor(manager, key, icon) for key, icon in _ZMAN_SENSORS),
    ]
    async_add_entities(entities)

    @callback
    def _refresh(_now: datetime | None = None) -> None:
        for entity in entities:
            if entity.hass is not None:
                entity.async_write_ha_state()
        _arm()

    holder: dict[str, Any] = {}

    @callback
    def _arm() -> None:
        when = next_rollover(manager.now(), manager.location, manager.minhag)
        if holder.get("when") == when:
            return
        previous = holder.get("unsub")
        if previous:
            previous()
        holder["when"] = when
        holder["unsub"] = async_track_point_in_time(hass, _refresh, when)

    def _cancel_rollover() -> None:
        unsub = holder.get("unsub")
        if unsub:
            unsub()

    entry.async_on_unload(async_track_time_interval(hass, _refresh, timedelta(seconds=30)))
    entry.async_on_unload(_cancel_rollover)
    _arm()


class NextCandleLighting(ShabbotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:candle"

    def __init__(self, manager) -> None:
        super().__init__(manager, "next_candle_lighting")

    def _next(self) -> jcal.Slot | None:
        now = self.manager.now()
        nights = [s for b in self.manager.upcoming_blocks() for s in b.slots
                  if s.part is jcal.Part.NIGHT and s.start > now]
        return min(nights, key=lambda s: s.start) if nights else None

    @property
    def native_value(self) -> datetime | None:
        slot = self._next()
        return slot.start if slot else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slot = self._next()
        return {"title": slot.title} if slot else {}


class NextHavdalah(ShabbotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:weather-night"

    def __init__(self, manager) -> None:
        super().__init__(manager, "next_havdalah")

    @property
    def native_value(self) -> datetime | None:
        now = self.manager.now()
        ends = [b.end for b in self.manager.upcoming_blocks() if b.end > now]
        return min(ends) if ends else None


class ActiveOverrides(ShabbotEntity, SensorEntity):
    _attr_icon = "mdi:hand-back-right"

    def __init__(self, manager) -> None:
        super().__init__(manager, "active_overrides")

    @property
    def native_value(self) -> int:
        return len(self.manager.overrides)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"overrides": self.manager.overrides, "paused": self.manager.paused}


class HebrewDateSensor(ShabbotEntity, SensorEntity):
    _attr_icon = "mdi:calendar-star"

    def __init__(self, manager) -> None:
        super().__init__(manager, "hebrew_date")

    @property
    def native_value(self) -> str:
        return self.manager.day_info().hebrew_date.english

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.manager.day_info()
        current = info.hebrew_date
        return {
            "hebrew": current.hebrew,
            "english": current.english,
            "day": current.day,
            "month": current.month,
            "month_hebrew": current.month_hebrew,
            "year": current.year,
            "civil_english": info.civil_hebrew_date.english,
            "civil_hebrew": info.civil_hebrew_date.hebrew,
            "halachic_english": info.halachic_hebrew_date.english,
            "halachic_hebrew": info.halachic_hebrew_date.hebrew,
            "rollover": "shkia",
            "civil_date": info.civil_date.isoformat(),
            "hebrew_day": info.hebrew_day.isoformat(),
        }


class ParashaSensor(ShabbotEntity, SensorEntity):
    _attr_icon = "mdi:book-open-page-variant"

    def __init__(self, manager) -> None:
        super().__init__(manager, "parasha")

    @property
    def native_value(self) -> str:
        return self.manager.day_info().reading_english

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.manager.day_info()
        return {
            "hebrew": info.reading_hebrew,
            "kind": info.reading_kind,
            "parasha": info.parasha_english,
            "parasha_hebrew": info.parasha_hebrew,
            "holiday": info.holiday_english,
            "holiday_hebrew": info.holiday_hebrew,
            "shabbat": info.shabbat.isoformat(),
            "israel": info.israel,
        }


class DafYomiSensor(ShabbotEntity, SensorEntity):
    _attr_icon = "mdi:book-open-variant"

    def __init__(self, manager) -> None:
        super().__init__(manager, "daf_yomi")

    @property
    def native_value(self) -> str:
        return self.manager.day_info().daf_english

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.manager.day_info()
        return {
            "hebrew": info.daf_hebrew,
            "masechet": info.masechet,
            "masechet_hebrew": info.masechet_hebrew,
            "daf": info.daf,
        }


class ZmanimSensor(ShabbotEntity, SensorEntity):
    """Today's zmanim. The state is the next one still ahead, in English."""

    _attr_icon = "mdi:sun-clock"

    def __init__(self, manager) -> None:
        super().__init__(manager, "zmanim")

    @property
    def native_value(self) -> str:
        info = self.manager.day_info()
        nxt = info.next_zman()
        if nxt is None:
            return "Tzeit"
        return ZMAN_LABELS[nxt[0]][0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.manager.day_info()
        nxt = info.next_zman()
        attrs: dict[str, Any] = {
            "date": info.civil_date.isoformat(),
            "next": nxt[0] if nxt else None,
            "next_at": nxt[1].isoformat() if nxt else None,
            "havdalah_kind": info.havdalah_kind,
            "names": {key: {"english": english, "hebrew": hebrew} for key, (english, hebrew) in ZMAN_LABELS.items()},
        }
        for key, moment in info.zmanim.items():
            attrs[key] = moment.isoformat()
        attrs["candle_lighting"] = info.candle_lighting.isoformat() if info.candle_lighting else None
        attrs["havdalah"] = info.havdalah.isoformat() if info.havdalah else None
        return attrs


class _ZmanTimeSensor(ShabbotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager, key: str, icon: str) -> None:
        super().__init__(manager, key)
        self._key = key
        self._attr_icon = icon

    @property
    def native_value(self) -> datetime | None:
        return self.manager.day_info().zmanim.get(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        english, hebrew = ZMAN_LABELS[self._key]
        return {"hebrew": hebrew, "english": english}
