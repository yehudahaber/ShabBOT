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

- Home Assistant 2026.9 or newer, on any install type (OS, Supervised, Container or Core)
- Your home's location and time zone set correctly in Home Assistant, because all zmanim are calculated from them
- Devices already in Home Assistant: lights, switches, input booleans, fans, climate, covers, media players or water heaters
- An administrator login to make changes (other users can open the panel)

## Announcements pre-release (this fork)

Announcements, the kids' daily briefing, and the Jewish-calendar sensors are a pre-release on the fork [yehudahaber/ShabBOT](https://github.com/yehudahaber/ShabBOT), tag `v0.2.10-announce.1`. They are not an upstream release.

1. HACS → ⋮ → **Custom repositories** → `https://github.com/yehudahaber/ShabBOT`, category **Integration**. If ShabBOT from another repository is already installed, remove that copy first — both write `custom_components/shabbot`.
2. Open the repository in HACS and turn on **Show beta** (pre-releases are hidden until then). Download **v0.2.10-announce.1**. HACS fetches `shabbot.zip` from that release.
3. Restart Home Assistant. **Settings → Devices & services → Add integration → ShabBOT**, then open **ShabBOT** in the sidebar → **Settings → Voice**. The Hebrew date, parasha, Daf Yomi, and zmanim show up as sensors without any extra setup. The voice module stays off on a new install. A home that already had announcements turned on keeps it on.

Requires Home Assistant 2026.9.0 or newer, the same as upstream ShabBOT. Pre-rendered clips are written to Home Assistant's local media folder (`config/media` on Container and Core, `/media` on Home Assistant OS) so Sonos can fetch them.

ShabBOT starts in **dry run**: it logs what it would do without touching any device. Turn it off ("Go live") after a Shabbat of watching the Activity tab.

What the voice module, the kids' briefing, and the calendar sensors do: [docs/announcements.md](docs/announcements.md).

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

You can change these later on ShabBOT's **Settings** tab. **ShabBOT** now appears in the sidebar.

ShabBOT starts in **dry run**: it logs what it would do without touching any device. It stays that way until you choose to go live in step 6.

### 3. Fill in your routines

Open the **Routines** tab. ShabBOT starts you off with routines such as "Standard Friday night", "Standard lunch" and "Yom Kippur", but they're empty until you add devices.

Choose a routine, then choose **Add device** for each row:

- **Devices:** one or more devices that share this schedule.
- **State:** on or off.
- **From** and **Until:** a zman with an offset, like `sunset+18m`, or a clock time, like `11:45pm`.
- **Afterwards:** what to do when the row ends.

Use the **Baseline** routine for anything that applies to every Shabbat and Yom Tov. Meal routines take priority over it while they run. See the [time formats and routine details](docs/reference.md#concepts).

### 4. Check your default rules

The **Default rules** tab chooses a routine for each meal. The starter rules already cover Shabbat night, Yom Tov night, lunch, the baseline and Yom Kippur, so you may only need to add rules for special cases.

**Coming up** on that tab shows what the rules pick for the next few weeks, and the **Calendar** tab shows the full year.

### 5. Rehearse it

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

- [Announcements, briefing, and Jewish calendar](docs/announcements.md): this fork's voice module and calendar sensors
- [Reference](docs/reference.md): time formats, how a routine is chosen, overrides, test mode, entities and actions
- [Contributing](CONTRIBUTING.md): development setup, brand images and releases

## Getting help

Open a [GitHub issue](https://github.com/aniceberg/ShabBOT/issues). Tell us your Home Assistant version, your ShabBOT version and what the **Activity** tab shows. If a test failed, **Copy results** on the **Test** tab gives you a summary to paste in.

## License

ShabBOT is licensed under the [GNU General Public License v3.0](LICENSE). The wordmark is drawn from Fredoka (SIL Open Font License).
