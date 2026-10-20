"""Whether the optional voice module is on for this home."""

from __future__ import annotations

from typing import Any


def voice_module_enabled(settings: dict[str, Any] | None) -> bool:
    """True when announcements and the kids' briefing should run."""
    return bool((settings or {}).get("voice_enabled"))


def migrate_voice_settings(stored: dict[str, Any] | None) -> dict[str, bool]:
    """Keep the module on for a home that already speaks announcements.

    ``voice_enabled`` is absent on installs saved before the module existed.
    Those homes stay on only when announcements were already turned on.
    A saved ``voice_enabled`` is left alone, including an explicit off.
    New installs never call this with ``announce_enabled`` set, so they stay off.
    """
    saved = stored or {}
    if "voice_enabled" in saved:
        return {}
    if saved.get("announce_enabled"):
        return {"voice_enabled": True}
    return {}
