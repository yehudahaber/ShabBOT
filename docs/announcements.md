# Announcements, briefing, and Jewish calendar (fork)

These features are in the [yehudahaber/ShabBOT](https://github.com/yehudahaber/ShabBOT) pre-release only. Everything else works as in [upstream ShabBOT](https://github.com/aniceberg/ShabBOT); see the [README](../README.md) and the [reference](reference.md).

## Voice module

Announcements and the kids' daily briefing live in `custom_components/shabbot/voice/`. That package is optional. Core ShabBOT (`core/`) is the calendar and the device rules: Hebrew date, zmanim, parasha, Daf Yomi, issur melacha, and the schedules that use them. `shabbot.get_day_info` stays on the core and returns structured facts. HACS allows one integration per repository, so the voice module stays inside ShabBOT rather than becoming a second integration.

**Settings → Voice** turns the module on. It is off on a new install. A home that already had **Speak announcements** on keeps the module on after updating. With the module off, nothing is scheduled to speak and `shabbot.get_daily_briefing` refuses. The sensors, `get_day_info`, and device protection keep working.

Settings → Voice speaks a short sentence on the media players you pick, using a TTS engine and an optional voice. Speaking itself also has a switch, so the module can be on for the kids' briefing without the countdowns. Each announcement (candle countdown, at candle lighting, shkia countdown, the final warning, motzei Shabbat, and next-meal preparation) has its own switch, its minute marks, and its wording, with **Reset wording** to put the default sentence back. **Dry run** logs the sentence on the Activity tab instead of speaking. `shabbot.announce` (or **Speak a test** in the panel) says one sentence immediately. **Speak this** under Pronunciation says one word or line with the current respelling. The panel lists the next few times so you can check the schedule before it runs.

**Voice.** The engine and an optional voice are on the announcements card. Leave the voice blank for the engine default. Piper Lessac high is `en_US-lessac-high`. Kokoro af_heart on the sherpa/Wyoming engine (`tts.sherpa_onnx_offline_tts`) is voice `3`. The list also offers whatever voices that engine reports.

**Pronunciation.** Before any announcement or briefing is sent to TTS, Hebrew and Yiddish words are respelled as whole words, ignoring case, so Piper and Kokoro say “shkee-ah” for shkia instead of spelling the letters. A built-in list covers zmanim, Hebrew months, parasha names, masechtot, and holidays. Rows in Settings → Voice override one word at a time and do not erase that list. An optional YAML file (Settings → Voice → Pronunciation file, for example `/config/tts_lexicon.yaml`) is applied last, so it extends or overrides both. A missing or invalid file is ignored. Set a word to itself in the file to have it spoken as written. Removing a row falls back to the built-in spelling. Sensors and the `text` field stay as written; `spoken` is the respelling.

**Pre-rendered audio.** The wording is deterministic for a date and a time window: there is no random phrasing, and clock times round the same way every time (to the nearest minute; “about twenty minutes” rounds to five). A morning and an afternoon before shkia share one briefing. At shkia the Hebrew date rolls and the evening wording takes over until midnight. ShabBOT fires `shabbot_day_rollover` at civil midnight and at shkia, with `reason` (`midnight` or `shkia`), `text` / `spoken`, `briefing_text` / `briefing_spoken` (the calendar script, without live weather or notes), and `day` (the day-info snapshot for that window). An automation can render the audio once on that event and reuse it until the next one. Nothing is fired when Home Assistant starts.

Once the day’s times are known — at startup, at the daily zmanim refresh (00:05), and again six hours before candle lighting — ShabBOT also renders each upcoming announcement and stores it in `config/media/shabbot/`. At the mark it plays that file (`media-source://media_source/local/shabbot/…`) so Sonos is not waiting on synthesis. Changing the sentence, the voice, the language, or the pronunciation map renders again. If a file is missing, it speaks live. The stop-melacha clip is started early by its own length, plus the lead, so the sentence finishes one minute before shkia. Other countdowns still start on their mark. Sonos snapshot/restore and the announcement volume are unchanged.

| When | Default |
|---|---|
| Before candle lighting | 60, 30, 15 and 5 minutes: "About an hour until candle lighting, at 6:08." The minutes round the way a person would say them ("about twenty minutes", "about half an hour"). The clock is "at 6:08", "at six", or "a little after six". |
| At candle lighting | once, at the candle-lighting moment itself (on erev Shabbat and erev Yom Tov, and the Friday night of a Yom Tov that runs into Shabbat): "It's candle lighting time." On by default; it has its own switch and wording. |
| After candle lighting, before shkia | the same marks, but only the ones that fall after candles are lit: "About fifteen minutes until shkia." Then a final warning 1 minute before shkia: "Shkia is in about a minute. Time to stop all melacha." |
| Havdalah | "It's motzei Shabbat. Havdalah is about an hour after shkia, and melacha is permitted." On a Yom Tov that is not Shabbat, the name is that Yom Tov ("It's motzei Pesach I."). The length is the Shabbat havdalah setting (or the real sun-angle gap) on Shabbat, and the Yom Tov end setting otherwise. |

**Yom Tov sequences.** "Muttar" is said only when issur melacha actually ends (the end of the whole Shabbat/Yom Tov block), never on a night that is still inside it.

- **First night** of Shabbat or Yom Tov, including an early Shabbat: countdown to candle lighting, then countdown to shkia. Early Shabbat moves the candle countdown to the early time; the shkia warning stays on the real sunset.
- **Yom Tov into Shabbat** (for example Friday night of a Yom Tov that continues into Shabbat): candles are lit before shkia, so the ordinary candle and shkia warnings run. There is no "muttar" that afternoon.
- **Second Yom Tov night that is not Shabbat**: the previous day has ended, so you may start getting the next meal ready. There is no shkia countdown and no "stop all melacha". Its own minute marks (60, 30, 15 and 5 by default) count down to that time ("About half an hour until you can start getting the next meal ready.") and one sentence fires when preparation may begin ("You can start getting the next meal ready now."). Turning off the candle-lighting countdown does not turn this off. After a Shabbat, the time is Shabbat havdalah. After a Yom Tov day, it is the Yom Tov end setting (default 42 minutes after shkia; 42, 50, 60, 72, or a custom value). That setting is global: device schedules use the same end.
- **Shabbat into Yom Tov** (for example Rosh Hashana starting on Shabbat): Saturday night is next-meal preparation at Shabbat havdalah, not a second candle lighting. The block then ends on Yom Tov, so motzaei uses the Yom Tov end offset.

**Lead.** A global offset in seconds, with an optional per-player override, fires the trigger that early so speaker buffering (Sonos is often several seconds) lands on the nominal time. The stop-melacha warning adds the pre-rendered clip length on top of that lead, so the sentence ends on the mark. `0` means the other announcements start exactly on time. A moment that was missed while Home Assistant was down is not spoken late.

**Volume.** An optional percentage is applied before the sentence and put back after it. Sonos players use snapshot/restore, so the previous playback returns as well. Other players only get their previous volume restored.

Each wording is a template. Placeholders: `{minutes}`, `{time}` ("at 6:08" or "a little after six"), `{about}` ("about twenty minutes"), `{parasha}`, `{hebrew_date}`, `{daf}`, `{zman_name}`, plus `{unit}`, `{minutes_words}`, `{occasion}`, and `{title}`. `{About}` is the same phrase with a capital letter. Leave a wording blank to skip that sentence. **Reset wording** puts the default back. A saved copy of an older default sentence is upgraded; a sentence you rewrote is kept.

### Kids' daily briefing

`shabbot.get_daily_briefing` returns one spoken script. It needs the voice module on. The default is warm and short: Hebrew date, the parasha (or the holiday reading, and a holiday coming up this week), Daf Yomi, shkia, candle lighting or havdalah when that evening has them, and how soon Shabbat or Yom Tov starts. With no date, the calendar part is the morning window (08:00 local) until shkia, then the shkia window. `script` and `text` are the words as written. `spoken` is the same sentence after the pronunciation lexicon. Weather and notes are still read live, so they are left out of the rollover event’s cached briefing.

Weather is optional. Pick one `weather.*` entity. ShabBOT reads its condition and the numeric high, low, and precipitation chance. It does not read a written forecast, and it does not go to the web. Notes are optional too: one `todo.*` list (items drop off after their due date; completed items are skipped) or one `input_text.*` helper with an optional "hide after" date. If weather or notes are not set, that part of the sentence is left out and the rest still makes sense. The wording is editable, with the same reset. Placeholders: `{hebrew_date}`, `{reading}`, `{parasha}`, `{daf}`, `{zmanim}`, `{countdown}`, `{weather}`, `{notes}`.

Players, the TTS engine, the voice, per-player leads, and the pronunciation-file path are not included in Export / Import (they belong to one home). The minute marks, templates, pronunciation rows, and lead are.

**Which routine runs** (most specific first):
1. A choice made for that date on the calendar (a different routine, or *Skip this meal*).
2. An active Summer/Vacation mode.
3. The default rule with the most matching conditions (kind of day, holiday, day number, weekday); ties go to the rule higher in the list.

## Jewish calendar

ShabBOT can answer "what day is it?" for a dashboard, a voice assistant, or a phone briefing. The facts come from [hdate](https://github.com/py-libhdate/py-libhdate) 1.2.1, the same library Home Assistant's Jewish Calendar uses. Candle lighting and havdalah still use ShabBOT's own sunset and the settings below, so they match the rest of the integration.

**Hebrew date.** The state is an English transliteration such as `9 Cheshvan 5787`. The Hebrew (for example `ט' מרחשוון ה' תשפ"ז`) is an attribute. The Hebrew day begins at shkia: before sunset the date is the civil day's, and at sunset it moves ahead. Attributes `civil_english` / `civil_hebrew` always keep the civil day, and `halachic_english` / `halachic_hebrew` follow shkia. hdate's "Marcheshvan" is shown as Cheshvan.

**Zmanim** for the civil date (they do not jump at shkia, so havdalah is still there after sunset):

| Name | How it is calculated |
|---|---|
| Alot HaShachar (עלות השחר) | 16.1° below the horizon |
| Misheyakir (משיכיר) | 11° below the horizon |
| Netz (הנץ החמה) | sunrise |
| Sof zman Shema, MGA and GRA | 3 seasonal hours from alot (MGA) or from sunrise (GRA) |
| Sof zman tefilla, MGA and GRA | 4 seasonal hours, the same two opinions |
| Chatzot (חצות) | midpoint of sunrise and sunset |
| Mincha gedola / ketana (מנחה גדולה / קטנה) | 6.5 and 9.5 seasonal hours after sunrise |
| Plag haMincha (פלג המנחה) | 1.25 seasonal hours before sunset |
| Shkia (שקיעה) | sunset |
| Tzeit (צאת הכוכבים) | 8.5° below the horizon |
| Candle lighting (הדלקת נרות) | the candle-lighting offset before ShabBOT's sunset, on an evening candles are lit, including early Shabbat. Empty otherwise |
| Havdalah (הבדלה) | when melacha actually becomes permitted that night. Shabbat uses the Shabbat havdalah setting (60 minutes after shkia in this house, or a sun angle). A Yom Tov that is not Shabbat uses the Yom Tov end setting (42 minutes by default). Empty on an ordinary day, and empty on a night that is still inside a multi-day Yom Tov |

**Parasha.** The weekly reading for the Shabbat of the Hebrew day in effect, in English and Hebrew. The Israel checkbox chooses the Israel or Chutz La'aretz list, including the weeks they differ (in 5787, from Shavuot II through Chukat-Balak). On a Shabbat that has a holiday reading instead, the state is that reading (Chol HaMoed Pesach, Shavuot II, Shmini Atzeret, …). After Shabbat's shkia the sensor moves to next week's parasha.

**Israel checkbox.** This is the same box as always (one-day Yom Tov, and now the Torah reading too). When you first add ShabBOT it starts checked if Home Assistant's country is IL or the map pin is inside Israel (a box from Eilat to Metula, the coast through the Golan), and unchecked otherwise. After setup, the box is the setting: check it for Israel, uncheck it for Chutz La'aretz, even if that disagrees with the map. It does not keep following the map on its own.

**Daf Yomi** is the Bavli daf for that Hebrew day: masechet and daf, in English (`Bechoros 32`) and Hebrew.

`shabbot.get_day_info` returns the same facts as JSON, plus `summary`, a short factual sentence. `text` is that same sentence. `spoken` is it after the pronunciation lexicon, which is what to send to TTS. The sensors stay on the display spelling. Leave `date` empty for right now. Pass a civil `date` (`2026-10-20`) for that day's daytime, with no shkia rollover. The kids' script is a separate action, `shabbot.get_daily_briefing`, and only when the voice module is on.

## Entities & actions

| Entity | |
|---|---|
| `binary_sensor.shabbot_issur_melacha` | on from candle lighting to havdalah |
| `calendar.shabbot_shabbat_yom_tov`, `calendar.shabbot_routines` | also visible in HA's Calendar |
| `sensor.shabbot_next_candle_lighting`, `sensor.shabbot_next_havdalah` | timestamps |
| `sensor.shabbot_active_overrides` | count, with details in attributes |
| `sensor.shabbot_hebrew_date` | `9 Cheshvan 5787`, with Hebrew and the civil/halachic pair in attributes |
| `sensor.shabbot_parasha` | this Shabbat's reading (parasha, or the holiday reading) |
| `sensor.shabbot_daf_yomi` | `Bechoros 32`, with masechet, daf, and Hebrew |
| `sensor.shabbot_zmanim` | the next zman still ahead; every time is an attribute |
| `sensor.shabbot_alot_hashachar`, `sensor.shabbot_misheyakir`, `sensor.shabbot_netz`, `sensor.shabbot_sof_zman_shema_mga`, `sensor.shabbot_sof_zman_shema_gra`, `sensor.shabbot_sof_zman_tefilla_mga`, `sensor.shabbot_sof_zman_tefilla_gra`, `sensor.shabbot_chatzot`, `sensor.shabbot_mincha_gedola`, `sensor.shabbot_mincha_ketana`, `sensor.shabbot_plag_hamincha`, `sensor.shabbot_shkia`, `sensor.shabbot_tzeit` | today's time for that zman |
| `select.shabbot_mode` | Normal / your modes (selecting one starts it today, open-ended) |
| `switch.shabbot_device_protection`, `switch.shabbot_dry_run` | |

Actions: `shabbot.start_override`, `shabbot.end_override`, `shabbot.set_slot_routine`, `shabbot.skip_slot`, `shabbot.reconcile`, `shabbot.announce`, `shabbot.get_day_info`, `shabbot.get_daily_briefing`.

`get_day_info` takes an optional `date` and returns:

| Field | |
|---|---|
| `hebrew_date`, `civil_hebrew_date`, `halachic_hebrew_date` | `english`, `hebrew`, `day`, `month`, `month_hebrew`, `year` |
| `parasha` | `english`, `hebrew`, `kind` (`parasha` or `holiday`), `shabbat`, plus the holiday name when there is one |
| `daf_yomi` | `english`, `hebrew`, `masechet`, `masechet_hebrew`, `daf` |
| `zmanim` | ISO timestamps for each zman; `candle_lighting` and `havdalah` are null when they don't apply. `havdalah_kind` is `shabbat` or `yom_tov` |
| `summary`, `text` | one factual sentence, as written: Hebrew date, parasha, Daf Yomi, and the next key times (sunrise, sof zman Shema, candle lighting, shkia, havdalah) |
| `spoken` | `text` after the pronunciation lexicon |
| `israel` | whether the Israel checkbox is on |
| `rollover` | `shkia` for "right now", `daytime` when a date was passed |

`get_daily_briefing` takes an optional `date` and returns:

| Field | |
|---|---|
| `script`, `text` | the one sentence, as written |
| `spoken` | `text` after the pronunciation lexicon |
| `window` | `morning` (08:00 until shkia), `shkia` (from sunset), or `daytime` (a date was passed) |
| `hebrew_date`, `parasha`, `daf` | the same facts, as short text |
| `countdown` | for example `Shabbat is in three days.` |
| `zmanim_sentence` | shkia, and candle lighting or havdalah when they apply |
| `weather` | the weather sentence, or null when no weather entity is set |
| `notes` | the parental lines that are still current, or an empty list |

A Tuesday morning in Brooklyn, with no weather and no note, sounds like: "Good morning. Today is 9 Cheshvan 5787. This week's parasha is Lech-Lecha. Daf Yomi is Bechoros, daf 32. Shkia is at 6:08. Shabbat is in three days."

