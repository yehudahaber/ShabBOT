"""Solar event calculations (NOAA algorithm), dependency-free.

Implements the NOAA solar calculator equations, the same approach used by
KosherJava's NOAACalculator and hebcal's @hebcal/noaa. All functions are pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo as TzInfo
import math

# Zenith angles, in degrees from vertical.
GEOMETRIC_ZENITH = 90.0
# Official sunrise/sunset: 34' refraction + 16' solar radius.
SUNRISE_ZENITH = 90.0 + 50.0 / 60.0
EARTH_RADIUS_KM = 6356.9


@dataclass(frozen=True, slots=True)
class Location:
    """A point on Earth plus its time zone."""

    latitude: float
    longitude: float
    tzinfo: TzInfo
    elevation_m: float = 0.0


def _julian_day(d: date) -> float:
    year, month, day = d.year, d.month, d.day
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def _sun_params(julian_century: float) -> tuple[float, float]:
    """Return (equation of time in minutes, declination in degrees)."""
    jc = julian_century
    mean_long = (280.46646 + jc * (36000.76983 + 0.0003032 * jc)) % 360.0
    mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    m = math.radians(mean_anom)
    center = (
        math.sin(m) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + math.sin(2 * m) * (0.019993 - 0.000101 * jc)
        + math.sin(3 * m) * 0.000289
    )
    true_long = mean_long + center
    omega = math.radians(125.04 - 1934.136 * jc)
    app_long = true_long - 0.00569 - 0.00478 * math.sin(omega)
    seconds = 21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))
    mean_obliq = 23.0 + (26.0 + seconds / 60.0) / 60.0
    obliq = mean_obliq + 0.00256 * math.cos(omega)
    decl = math.degrees(math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long))))

    y = math.tan(math.radians(obliq) / 2.0) ** 2
    l0 = math.radians(mean_long)
    eq_time = 4.0 * math.degrees(
        y * math.sin(2 * l0)
        - 2 * ecc * math.sin(m)
        + 4 * ecc * y * math.sin(m) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0)
        - 1.25 * ecc * ecc * math.sin(2 * m)
    )
    return eq_time, decl


def _century(jd: float, utc_minutes: float) -> float:
    return (jd + utc_minutes / 1440.0 - 2451545.0) / 36525.0


def _elevation_adjustment(elevation_m: float) -> float:
    """Extra degrees of depression visible from an elevated observer."""
    if elevation_m <= 0:
        return 0.0
    return math.degrees(math.acos(EARTH_RADIUS_KM / (EARTH_RADIUS_KM + elevation_m / 1000.0)))


def _utc_event_minutes(d: date, loc: Location, zenith: float, rising: bool) -> float | None:
    """Minutes after 00:00 UTC on date d of the event, or None if it doesn't occur."""
    jd = _julian_day(d)
    # Start from local solar noon, then refine twice at the estimated event time.
    estimate = 720.0 - 4.0 * loc.longitude
    for _ in range(3):
        eq_time, decl = _sun_params(_century(jd, estimate))
        lat = math.radians(loc.latitude)
        dec = math.radians(decl)
        cos_ha = math.cos(math.radians(zenith)) / (math.cos(lat) * math.cos(dec)) - math.tan(lat) * math.tan(dec)
        if cos_ha < -1.0 or cos_ha > 1.0:
            return None
        ha = math.degrees(math.acos(cos_ha))
        noon = 720.0 - 4.0 * loc.longitude - eq_time
        estimate = noon - 4.0 * ha if rising else noon + 4.0 * ha
    return estimate


def solar_event(d: date, loc: Location, zenith: float, rising: bool, use_elevation: bool = False) -> datetime | None:
    """Local datetime of the sun crossing `zenith` on local date d."""
    z = zenith
    if use_elevation:
        z += _elevation_adjustment(loc.elevation_m)
    minutes = _utc_event_minutes(d, loc, z, rising)
    if minutes is None:
        return None
    base = datetime(d.year, d.month, d.day, tzinfo=UTC)
    result = (base + timedelta(minutes=minutes)).astimezone(loc.tzinfo)
    # Guard against date slip at extreme longitudes: re-anchor onto the local date.
    if result.date() != d:
        shift = 1 if result.date() < d else -1
        minutes = _utc_event_minutes(d + timedelta(days=shift), loc, z, rising)
        if minutes is None:
            return None
        base = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=shift)
        result = (base + timedelta(minutes=minutes)).astimezone(loc.tzinfo)
    return result


def sunrise(d: date, loc: Location, use_elevation: bool = False) -> datetime | None:
    return solar_event(d, loc, SUNRISE_ZENITH, rising=True, use_elevation=use_elevation)


def sunset(d: date, loc: Location, use_elevation: bool = False) -> datetime | None:
    return solar_event(d, loc, SUNRISE_ZENITH, rising=False, use_elevation=use_elevation)


def sun_below_horizon(d: date, loc: Location, degrees: float, evening: bool = True) -> datetime | None:
    """When the sun is `degrees` below the geometric horizon (e.g. tzeit 8.5°, alot 16.1°)."""
    return solar_event(d, loc, GEOMETRIC_ZENITH + degrees, rising=not evening)


def solar_noon(d: date, loc: Location) -> datetime:
    jd = _julian_day(d)
    noon = 720.0 - 4.0 * loc.longitude
    for _ in range(2):
        eq_time, _decl = _sun_params(_century(jd, noon))
        noon = 720.0 - 4.0 * loc.longitude - eq_time
    base = datetime(d.year, d.month, d.day, tzinfo=UTC)
    return (base + timedelta(minutes=noon)).astimezone(loc.tzinfo)
