<p align="center"><img src="assets/banner.svg" alt="ShabBOT — Shabbat &amp; Yom Tov automation for Home Assistant" width="640"></p>

# ShabBOT

Shabbat & Yom Tov automation for Home Assistant. Home Assistant stays the hub for every device (Lutron, SmartThings, Z-Wave, Kasa, …); ShabBOT decides what those devices do during Shabbat and Yom Tov, and keeps them that way.

- **Calendar** (Year / Month / Week / Day) of every Shabbat and Yom Tov with the routines scheduled in it. Click an entry to drill into the routine, then into each device's on/off windows.
- **Routines** like "Standard Friday night", "Friday night hosting guests", "Friday night away", built from device windows such as *chandelier on from `sunset+18m` until `11:45pm`*.
- **Default rules** pick a routine for each meal (Shabbat night, Yom Tov day 1 lunch, 2nd night of Pesach, …). Change or skip any single meal from the calendar without touching the rule.
- **Summer / Vacation modes** for a date range or open-ended.
- **Device protection**: during Shabbat/Yom Tov, a device that changes unexpectedly is put back (on every state change, plus a check every minute).
- **Intentional overrides**: a Zooz triple-tap (or a learned button press, or a quick flip pattern on Caséta/Kasa/Wemo) pauses protection for that device for N minutes; the opposite gesture ends it early.
- Zmanim are calculated by ShabBOT itself (NOAA solar algorithm, checked against hebcal.com), so it doesn't depend on Home Assistant's Jewish Calendar integration.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repository's URL, category **Integration**.
2. Install **ShabBOT**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → ShabBOT.** Set candle-lighting minutes, havdalah rule, and Israel/Diaspora. Location and time zone come from Home Assistant.
4. Open **ShabBOT** in the sidebar.

### Install the announcements pre-release

Announcements are a pre-release on the fork [yehudahaber/ShabBOT](https://github.com/yehudahaber/ShabBOT), tag `v0.2.5-announce.2`. They are not an upstream release.

1. HACS → ⋮ → **Custom repositories** → `https://github.com/yehudahaber/ShabBOT`, category **Integration**. If ShabBOT from another repository is already installed, remove that copy first — both write `custom_components/shabbot`.
2. Open the repository in HACS and turn on **Show beta** (pre-releases are hidden until then). Download **v0.2.5-announce.2**. HACS fetches `shabbot.zip` from that release.
3. Restart Home Assistant. **Settings → Devices & services → Add integration → ShabBOT**, then open **ShabBOT** in the sidebar → **Settings → Announcements**.

Requires Home Assistant 2026.9.0 or newer, the same as upstream ShabBOT. Pre-rendered clips are written to Home Assistant's local media folder (`config/media` on Container and Core, `/media` on Home Assistant OS) so Sonos can fetch them.

ShabBOT starts in **dry run**: it logs what it would do without touching any device. Turn it off ("Go live") after a Shabbat of watching the Activity tab.

Works on every Home Assistant install type (OS, Supervised, Container, Core). Install it separately in each home; use **Settings → Export / Import** to copy routines between homes.

## Concepts

**Block**: one continuous Shabbat/Yom Tov, from candle lighting to havdalah (1–3 days).
**Slot**: each day in a block has a *night* meal (the evening before) and a *day* meal. Slot keys look like `2026-10-10/night`.

**Routine**: runs for a night, a day, or the whole block ("baseline"). Each row keeps one or more devices on (or off) between two times (add several devices to a row to give them the same schedule). Drag the ⋮⋮ handle to reorder rows, routines within each list, or default rules (where order breaks ties). **Duplicate routine** makes an editable copy (e.g. start "Lunch hosting guests" from "Standard lunch"), and **Copy rows from…** adds another routine's rows to the one you're editing. When meal routines and the baseline overlap, the meal wins.

**Baseline rows** apply to every Shabbat/Yom Tov whatever the meal plans, and each can **repeat**:
- *Once* (default): times count from the first evening, so `7:00am` means the next morning and `3:00pm` means that Friday afternoon.
- *Every night*: read in each evening's frame (evening → next morning), e.g. bedroom lights off `sunset` → `sunrise` every night of a 2- or 3-day Yom Tov.
- *Every day*: read on each day itself, e.g. closet lights on `7:00am` → `10:00am` every morning of a 2- or 3-day Yom Tov.

**Time expressions**

| Example | Meaning |
|---|---|
| `sunset+18m`, `candle_lighting-30m`, `tzeit+1h30m` | zman with an offset |
| `11:45pm`, `23:45`, `1:00am` | clock time (on a night slot, morning times mean the next morning) |
| `midnight` | 12:00 AM after the evening |
| `max(sunset+18m, 7pm)` | later of the two |
| `10pm` → `6am`, `sunset` → `sunrise` | an end before the start is read as the next day ("crosses midnight") |
| `slot_start`, `slot_end` | start/end of this meal period |

Available zmanim: `alot`, `sunrise`, `chatzot`, `mincha_gedola`, `plag`, `candle_lighting` (when candles are lit that night), `sunset`, `tzeit` (8.5°), `havdalah` (the end of this Shabbat/Yom Tov, as configured).

**Early Shabbat (summer)**: Settings → Early Shabbat lights candles at a fixed time (e.g. 7:00 PM) on Fridays when the normal time would be later than a cutoff (e.g. 7:15 PM), never before plag hamincha, and only on a plain Shabbat (not when it is also Yom Tov). Device protection starts at the early time, and routine rows written with `candle_lighting` move with it; rows written with `sunset` don't, so prefer `candle_lighting` for anything tied to the start of Shabbat.

## Announcements

Settings → Announcements speaks a short sentence on the media players you pick, using a TTS engine and an optional voice. It starts off. Each announcement (candle countdown, shkia countdown, the final warning, motzaei, and next-meal preparation) has its own switch. **Dry run** logs the sentence on the Activity tab instead of speaking. `shabbot.announce` (or **Speak a test** in the panel) says one sentence immediately. **Speak this** under Pronunciation says one word or line with the current respelling. The panel lists the next few times so you can check the schedule before it runs.

**Voice.** The engine and an optional voice are on the announcements card. Leave the voice blank for the engine default. Piper Lessac high is `en_US-lessac-high`. Kokoro af_heart on the sherpa/Wyoming engine (`tts.sherpa_onnx_offline_tts`) is voice `3`. The list also offers whatever voices that engine reports.

**Pronunciation.** Hebrew and Yiddish words are respelled before TTS, as whole words, so Piper and Kokoro say “shkee-ah” for shkia instead of spelling the letters. The list is editable. Reset puts the defaults back. Removing a row leaves that word as written.

**Pre-rendered audio.** Once the day’s times are known — at startup, at the daily zmanim refresh (00:05), and again six hours before candle lighting — ShabBOT renders each upcoming sentence and stores it in `config/media/shabbot/`. At the mark it plays that file (`media-source://media_source/local/shabbot/…`) so Sonos is not waiting on synthesis. Changing the sentence, the voice, the language, or the pronunciation map renders again. If a file is missing, it speaks live. The stop-melacha clip is started early by its own length, plus the lead, so the sentence finishes one minute before shkia. Other countdowns still start on their mark. Sonos snapshot/restore and the announcement volume are unchanged.

| When | Default |
|---|---|
| Before candle lighting | 60, 30, 15 and 5 minutes: "60 minutes until candle lighting" |
| After candle lighting, before shkia | the same marks, but only the ones that fall after candles are lit, then a final warning 1 minute before shkia: "Shkia in one minute. Stop all melacha." |
| Havdalah | "It's now 60 minutes after shkia and it's muttar to do melacha." On Shabbat the number is the Shabbat havdalah setting (or the real sun-angle gap). On a Yom Tov that is not Shabbat it is the Yom Tov end setting. |

**Yom Tov sequences.** "Muttar" is said only when issur melacha actually ends (the end of the whole Shabbat/Yom Tov block), never on a night that is still inside it.

- **First night** of Shabbat or Yom Tov, including an early Shabbat: countdown to candle lighting, then countdown to shkia. Early Shabbat moves the candle countdown to the early time; the shkia warning stays on the real sunset.
- **Yom Tov into Shabbat** (for example Friday night of a Yom Tov that continues into Shabbat): candles are lit before shkia, so the ordinary candle and shkia warnings run. There is no "muttar" that afternoon.
- **Second Yom Tov night that is not Shabbat**: the previous day has ended, so you may start preparing for the next meal. There is no shkia countdown and no "stop all melacha". Its own minute marks (60, 30, 15 and 5 by default) count down to that time ("30 minutes until you can start preparing for the next meal") and one sentence fires when preparation may begin. Turning off the candle-lighting countdown does not turn this off. After a Shabbat, the time is Shabbat havdalah. After a Yom Tov day, it is the Yom Tov end setting (default 42 minutes after shkia; 42, 50, 60, 72, or a custom value). That setting is global: device schedules use the same end.
- **Shabbat into Yom Tov** (for example Rosh Hashana starting on Shabbat): Saturday night is next-meal preparation at Shabbat havdalah, not a second candle lighting. The block then ends on Yom Tov, so motzaei uses the Yom Tov end offset.

**Lead.** A global offset in seconds, with an optional per-player override, fires the trigger that early so speaker buffering (Sonos is often several seconds) lands on the nominal time. The stop-melacha warning adds the pre-rendered clip length on top of that lead, so the sentence ends on the mark. `0` means the other announcements start exactly on time. A moment that was missed while Home Assistant was down is not spoken late.

**Volume.** An optional percentage is applied before the sentence and put back after it. Sonos players use snapshot/restore, so the previous playback returns as well. Other players only get their previous volume restored.

Templates accept `{minutes}`, `{unit}` (minute/minutes), `{minutes_words}` ("one minute"), `{occasion}`, and `{title}`. Leave a template blank to skip that sentence.

Players, the TTS engine, the voice, and per-player leads are not included in Export / Import (they belong to one home). The minute marks, templates, pronunciation map, and lead are.

**Which routine runs** (most specific first):
1. A choice made for that date on the calendar (a different routine, or *Skip this meal*).
2. An active Summer/Vacation mode.
3. The default rule with the most matching conditions (kind of day, holiday, day number, weekday); ties go to the rule higher in the list.

## Overrides

Configure each device on the **Devices** tab.

| Gesture | Use for | How |
|---|---|---|
| **Button event** | Zooz / Z-Wave scene switches, Lutron Pico & RA3 keypads, ZHA/Hue remotes | "Use Z-Wave triple-tap" fills in Central Scene 3× (scene 001 = up paddle starts, 002 = down paddle ends). Or press **Learn** and do the gesture. |
| **Flip the switch quickly** | Caséta, Kasa, Wemo (on/off only) | e.g. 3 flips within 6 seconds starts (and ends) an override |
| **Keep turning it back** | on/off-only switches | if someone undoes ShabBOT's correction 3 times in 2 minutes, the last one sticks |
| **Override now** | anyone | panel button, or `shabbot.start_override` from a dashboard |

Z-Wave note: Zooz switches send scene events only when *scene control* is enabled in the device parameters.

"Also override these devices" lets a single switch's gesture release a whole room.

## Entities & actions

| Entity | |
|---|---|
| `binary_sensor.shabbot_issur_melacha` | on from candle lighting to havdalah |
| `calendar.shabbot_shabbat_yom_tov`, `calendar.shabbot_routines` | also visible in HA's Calendar |
| `sensor.shabbot_next_candle_lighting`, `sensor.shabbot_next_havdalah` | timestamps |
| `sensor.shabbot_active_overrides` | count, with details in attributes |
| `select.shabbot_mode` | Normal / your modes (selecting one starts it today, open-ended) |
| `switch.shabbot_device_protection`, `switch.shabbot_dry_run` | |

Actions: `shabbot.start_override`, `shabbot.end_override`, `shabbot.set_slot_routine`, `shabbot.skip_slot`, `shabbot.reconcile`, `shabbot.announce`.

## Moving over from SmartThings / Lutron / Node-RED

1. Build routines and default rules in ShabBOT; leave dry run on.
2. Watch one Shabbat: compare ShabBOT's Activity tab with what the old automations did.
3. Turn off the old Shabbat automations (SmartThings routines, Lutron schedules, Node-RED flows, HA automations that use `issur_melacha_in_effect`).
4. Turn dry run off.

## Development

```bash
uv sync                      # Python 3.14, pinned Home Assistant test harness
uv run pytest -q             # zmanim vs hebcal.com, planner, executor/protection/override flows
cd frontend && npm ci && npm run build   # builds custom_components/shabbot/frontend/shabbot-panel.js
```

Run a throwaway Home Assistant against the working tree:

```bash
uv run hass -c .devha        # .devha/custom_components/shabbot → ../../custom_components/shabbot
```

Brand assets (integration icon/logo, sidebar icon, panel header icon, this README's banner) are generated from vector shapes:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/usr/local/lib uvx --with cairosvg --with fonttools python assets/build_brand.py
```

Release: publish a GitHub release tagged `vX.Y.Z`; the workflow builds the panel and attaches `shabbot.zip` for HACS.

## License

ShabBOT is licensed under the [GNU General Public License v3.0](LICENSE). The wordmark is drawn from Fredoka (SIL Open Font License).
