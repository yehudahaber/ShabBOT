<p align="center"><img src="assets/banner.svg" alt="ShabBOT: Shabbat &amp; Yom Tov automation for Home Assistant" width="640"></p>

<p align="center">
  <a href="https://github.com/aniceberg/ShabBOT/releases/latest"><img src="https://img.shields.io/github/v/release/aniceberg/ShabBOT?label=release" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/Home%20Assistant-2026.9%2B-41BDF5" alt="Home Assistant 2026.9 or newer">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/aniceberg/ShabBOT" alt="License: GPL-3.0"></a>
</p>

# ShabBOT for Home Assistant

Set your home's Shabbat and Yom Tov schedule once, and ShabBOT runs it. It works out the times, turns your devices on and off, and puts back anything that changes by accident. Your devices stay in Home Assistant, whether they're Lutron, SmartThings, Z-Wave, Kasa or anything else.

- **Calendar:** see every Shabbat and Yom Tov by year, month, week or day, with the routine planned for each meal.
- **Routines:** build plans like "Standard Friday night" or "Lunch hosting guests" from rows such as *chandelier on from `sunset+18m` until `11:45pm`*.
- **Default rules:** choose a routine for each meal once, then change or skip any single meal from the calendar.
- **Summer and vacation modes:** switch plans for a date range, or until you end the mode.
- **Device protection:** if a device changes unexpectedly during Shabbat or Yom Tov, ShabBOT puts it back.
- **Intentional overrides:** a triple-tap or a learned button press pauses protection on a device for a set time.
- **Test mode:** rehearse the schedule on your real devices before you rely on it.
- **Built-in zmanim:** ShabBOT calculates its own times and doesn't need Home Assistant's Jewish Calendar integration.

## What you need

### Install the announcements pre-release

Announcements, the kids' daily briefing, and the Jewish-calendar sensors are a pre-release on the fork [yehudahaber/ShabBOT](https://github.com/yehudahaber/ShabBOT), tag `v0.2.7-announce.8`. They are not an upstream release.

1. HACS → ⋮ → **Custom repositories** → `https://github.com/yehudahaber/ShabBOT`, category **Integration**. If ShabBOT from another repository is already installed, remove that copy first — both write `custom_components/shabbot`.
2. Open the repository in HACS and turn on **Show beta** (pre-releases are hidden until then). Download **v0.2.7-announce.8**. HACS fetches `shabbot.zip` from that release.
3. Restart Home Assistant. **Settings → Devices & services → Add integration → ShabBOT**, then open **ShabBOT** in the sidebar → **Settings → Voice**. The Hebrew date, parasha, Daf Yomi, and zmanim show up as sensors without any extra setup. The voice module stays off on a new install. A home that already had announcements turned on keeps it on.

Requires Home Assistant 2026.9.0 or newer, the same as upstream ShabBOT. Pre-rendered clips are written to Home Assistant's local media folder (`config/media` on Container and Core, `/media` on Home Assistant OS) so Sonos can fetch them.

ShabBOT starts in **dry run**: it logs what it would do without touching any device. Turn it off ("Go live") after a Shabbat of watching the Activity tab.
- Home Assistant 2026.9 or newer, on any install type (OS, Supervised, Container or Core)
- Your home's location and time zone set correctly in Home Assistant, because all zmanim are calculated from them
- Devices already in Home Assistant: lights, switches, input booleans, fans, climate, covers, media players or water heaters
- An administrator login to make changes (other users can open the panel)

## Set it up

### 1. Install

Open **Settings → Marketplace**, search for **ShabBOT** and choose **Install**. Restart Home Assistant if it asks you to.

If the search finds nothing yet, add `aniceberg/ShabBOT` by link in the Marketplace, which needs a GitHub connection.

The Marketplace needs Home Assistant 2026.11 or newer. On older versions, use HACS: search for **ShabBOT**, or add this repository under ⋮ → **Custom repositories** with the category **Integration**.

### 2. Add the integration

[![Add ShabBOT to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=shabbot)

Or go to **Settings → Devices & services → Add integration → ShabBOT**. Then set your minhagim:

| Setting | Starts at | Notes |
| --- | --- | --- |
| Candle lighting | 18 minutes before sunset | Use your community's time |
| Havdalah | Sun 8.5° below the horizon | Or choose a fixed number of minutes after sunset |
| Israel | Off | Turn on for one-day Yom Tov |

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
You can change these later on ShabBOT's **Settings** tab. **ShabBOT** now appears in the sidebar.

ShabBOT starts in **dry run**: it logs what it would do without touching any device. It stays that way until you choose to go live in step 6.

### 3. Fill in your routines

Open the **Routines** tab. ShabBOT starts you off with routines such as "Standard Friday night", "Standard lunch" and "Yom Kippur", but they're empty until you add devices.

Choose a routine, then choose **Add device** for each row:

- **Devices:** one or more devices that share this schedule.
- **State:** on or off.
- **From** and **Until:** a zman with an offset, like `sunset+18m`, or a clock time, like `11:45pm`.
- **Afterwards:** what to do when the row ends.

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

## Test mode
Use the **Baseline** routine for anything that applies to every Shabbat and Yom Tov. Meal routines take priority over it while they run. See the [time formats and routine details](docs/reference.md#concepts).

### 4. Check your default rules

The **Default rules** tab chooses a routine for each meal. The starter rules already cover Shabbat night, Yom Tov night, lunch, the baseline and Yom Kippur, so you may only need to add rules for special cases.

**Coming up** on that tab shows what the rules pick for the next few weeks, and the **Calendar** tab shows the full year.

### 5. Rehearse it

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
Use the **Test** tab to step through the schedule on your real devices. Pick a time range, then choose **Begin test** for each event and mark it **Pass** or **Fail**.

The test really does change your devices, even in dry run. When it ends, they go back to what the schedule wants now, or else to how they were. You can't start a test during Shabbat or Yom Tov. See the [test mode details](docs/reference.md#test-mode).

### 6. Watch one Shabbat, then go live

1. Leave dry run on for one Shabbat. If other automations still run your home, compare what they do with what the **Activity** tab says ShabBOT would have done.
2. Turn off your old Shabbat automations, so they don't compete with ShabBOT. These might be SmartThings routines, Lutron schedules, Node-RED flows, or Home Assistant automations that use `issur_melacha_in_effect`.
3. Choose **Go live** in the banner at the top of the panel.

## Using it

### Change one meal

On the **Calendar** tab, select a meal, then choose a different routine or **Skip this meal**. Your default rules stay as they are.

### Summer and vacation

On the **Summer & vacation** tab, add a mode with its dates and its routines, or tick **No end date**. An active mode takes priority over your default rules, but not over a choice for a single date on the calendar.

For early Shabbat in the summer, go to the **Settings** tab and turn on **Start Shabbat early in the summer**. Write routine rows with `candle_lighting` rather than `sunset` if they should move with it.

### Let someone override a device

Protection puts a device back when someone changes it, so give people a way to change it on purpose. On the **Devices** tab, choose **Configure** next to a device and pick a gesture:

| Gesture | Works with |
| --- | --- |
| **Button event** | Zooz and other Z-Wave scene switches, Lutron Pico and RA3 keypads, ZHA and Hue remotes |
| **Flip the switch quickly** | On/off devices such as Caséta, Kasa and Wemo |
| **Keep turning it back** | On/off switches: if someone keeps undoing ShabBOT's correction, their change sticks |

Zooz switches send these events only when scene control is enabled in the device's parameters. See the [override details](docs/reference.md#overrides).

### If ShabBOT stops correcting a device

If a device keeps changing back, ShabBOT eventually stops correcting it, by default after 5 corrections in 10 minutes. The **Devices** tab shows it as **Paused**. Open the device and choose **Resume protection**.

To be told when this happens, choose a notification service on the **Settings** tab.

### More than one home

Install ShabBOT separately in each home. To copy your setup, use **Copy between homes** on the **Settings** tab: **Export…** in one home and **Import…** in the other.

## Learn more

- [Reference](docs/reference.md): time formats, how a routine is chosen, overrides, test mode, entities and actions
- [Contributing](CONTRIBUTING.md): development setup, brand images and releases

## Getting help

Open a [GitHub issue](https://github.com/aniceberg/ShabBOT/issues). Tell us your Home Assistant version, your ShabBOT version and what the **Activity** tab shows. If a test failed, **Copy results** on the **Test** tab gives you a summary to paste in.

## License

ShabBOT is licensed under the [GNU General Public License v3.0](LICENSE). The wordmark is drawn from Fredoka (SIL Open Font License).
