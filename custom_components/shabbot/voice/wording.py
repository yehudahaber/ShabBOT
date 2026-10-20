"""Spoken phrasing for announcements and the kids' briefing.

Times come out as a person would say them ("at 6:08", "a little after six").
Minute counts round to a nearby comfortable number ("about twenty minutes").
"""

from __future__ import annotations

from datetime import datetime, timedelta

_HOURS = (
    "twelve", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten", "eleven",
)

_SMALL = {
    5: "five", 10: "ten", 15: "fifteen", 20: "twenty", 25: "twenty-five",
    30: "thirty", 35: "thirty-five", 40: "forty", 45: "forty-five",
    50: "fifty", 55: "fifty-five",
}

_DAY_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}


def about_minutes(minutes: int) -> str:
    """A rounded length: 'about twenty minutes', 'about an hour', 'about a minute'."""
    n = abs(int(minutes))
    if n <= 0:
        return "less than a minute"
    if n == 1:
        return "about a minute"
    if n == 2:
        return "about a couple of minutes"
    if n <= 4:
        return "about a few minutes"
    rounded = max(5, int(round(n / 5.0) * 5))
    if rounded == 30:
        return "about half an hour"
    if rounded < 60:
        return f"about {_SMALL.get(rounded, str(rounded))} minutes"
    hours, rem = divmod(rounded, 60)
    hour = "an hour" if hours == 1 else f"{hours} hours"
    if rem == 0:
        return f"about {hour}"
    if rem == 30:
        return f"about {hour} and a half"
    return f"about {hour} and {_SMALL.get(rem, str(rem))} minutes"


def capitalize_phrase(phrase: str) -> str:
    """Uppercase the first letter, leaving the rest of the phrase as written."""
    if not phrase:
        return phrase
    return phrase[0].upper() + phrase[1:]


def natural_time(moment: datetime) -> str:
    """'at 6:08', 'at six', 'a little after six', or 'just before seven'.

    Exact minutes stay numeric. The top of the hour, and a couple of minutes
    either side, use the hour's name.
    """
    rounded = (moment + timedelta(seconds=30)).replace(second=0, microsecond=0)
    minute = rounded.minute
    hour12 = rounded.hour % 12
    name = _HOURS[hour12]
    if minute == 0:
        return f"at {name}"
    if minute <= 3:
        return f"a little after {name}"
    if minute >= 57:
        return f"just before {_HOURS[(hour12 + 1) % 12]}"
    shown = hour12 or 12
    return f"at {shown}:{minute:02d}"


def day_count(days: int) -> str:
    """'three days', 'one day'."""
    n = abs(int(days))
    word = _DAY_WORDS.get(n, str(n))
    unit = "day" if n == 1 else "days"
    return f"{word} {unit}"
