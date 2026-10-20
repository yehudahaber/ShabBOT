"""Optional voice module: announcements and the kids' daily briefing.

Core ShabBOT (``core/``) is the calendar and the device rules: Hebrew date,
zmanim, parasha, Daf Yomi, issur melacha, and the schedules that use them.
``shabbot.get_day_info`` stays on that core and returns structured facts.

This package rides on those facts. It speaks the countdown announcements and
builds ``shabbot.get_daily_briefing``. HACS allows one integration per
repository, so the module stays inside ShabBOT rather than becoming a second
integration. New installs leave ``voice_enabled`` off. A home that already
had announcements turned on keeps the module on (see ``migrate_voice_settings``).
"""

from .gate import migrate_voice_settings, voice_module_enabled

__all__ = ["migrate_voice_settings", "voice_module_enabled"]
