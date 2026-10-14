"""Constants for ShabBOT."""

from __future__ import annotations

from typing import Final

from .core.announcements import ANNOUNCE_DEFAULTS

DOMAIN: Final = "shabbot"
NAME: Final = "ShabBOT"
VERSION: Final = "0.2.2"

STORAGE_VERSION: Final = 1
STORAGE_KEY_CONFIG: Final = f"{DOMAIN}.config"
STORAGE_KEY_ACTIVITY: Final = f"{DOMAIN}.activity"

PANEL_URL: Final = "shabbot"
PANEL_STATIC_URL: Final = "/shabbot_static"
PANEL_COMPONENT: Final = "shabbot-panel"
PANEL_ICON: Final = "shabbot:logo"

SIGNAL_UPDATE: Final = f"{DOMAIN}_update"  # plan/status changed
SIGNAL_ACTIVITY: Final = f"{DOMAIN}_activity"  # one activity entry

ACTIVITY_MAX: Final = 2000
PLAN_HORIZON_DAYS: Final = 60
POLL_SECONDS: Final = 60

DEFAULT_SETTINGS: Final = {
    "candle_lighting_min": 18,
    "havdalah_mode": "degrees",
    "havdalah_degrees": 8.5,
    "havdalah_minutes": 50,
    "israel": False,
    "use_elevation": False,
    "early_shabbat": False,  # summer: accept Shabbat at a fixed time when candle lighting is late
    "early_shabbat_time": "19:00",
    "early_shabbat_after": "19:15",
    "latitude": None,  # None = use Home Assistant's location
    "longitude": None,
    "dry_run": True,  # start safe: log only until the user turns it off
    "protection": True,
    "grace_seconds": 4,
    "storm_max_reverts": 5,
    "storm_window_min": 10,
    "notify_service": "",
    "notify_overrides": True,
    **ANNOUNCE_DEFAULTS,
}

# Home-specific values. Export/import copies minhag and templates, not another house's devices.
EXPORT_SKIP_SETTINGS: Final = (
    "latitude",
    "longitude",
    "notify_service",
    "announce_players",
    "announce_tts_entity",
    "announce_player_leads",
)

DEFAULT_DEVICE: Final = {
    "protect": True,
    "override": {"detector": "none"},
    "override_minutes": 20,
    "after_override": "reassert",  # reassert | next_transition
    "override_group": [],
}

# Starter routines/rules created on first setup, so the panel isn't empty.
STARTER_ROUTINES: Final = [
    ("baseline", "Baseline (whole Shabbat/Yom Tov)", "block", "#64748b"),
    ("fri_standard", "Standard Friday night", "night", "#2563eb"),
    ("fri_hosting", "Friday night hosting guests", "night", "#7c3aed"),
    ("fri_away", "Friday night away", "night", "#94a3b8"),
    ("day_standard", "Standard lunch", "day", "#16a34a"),
    ("day_hosting", "Lunch hosting guests", "day", "#0d9488"),
    ("day_away", "Lunch away", "day", "#94a3b8"),
    ("yt_night", "Yom Tov night at home", "night", "#ea580c"),
    ("yk_baseline", "Yom Kippur", "block", "#475569"),
]
STARTER_RULES: Final = [
    # Ties on specificity go to the earlier rule, so the Yom Kippur rules come first.
    ("Yom Kippur", "block", {"holiday_group": "yom_kippur"}, "yk_baseline"),
    ("No meals on Yom Kippur (night)", "night", {"holiday_group": "yom_kippur"}, None),
    ("No meals on Yom Kippur (day)", "day", {"holiday_group": "yom_kippur"}, None),
    ("Every Shabbat/Yom Tov baseline", "block", {}, "baseline"),
    ("Shabbat night", "night", {"day_type": "shabbat"}, "fri_standard"),
    ("Yom Tov night", "night", {"day_type": "yomtov_only"}, "yt_night"),
    ("Lunch", "day", {}, "day_standard"),
]
