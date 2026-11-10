# ShabBOT reference

The details behind the [setup guide](../README.md): how routines and times work, override gestures, test mode, and every entity and action.

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

## Test mode

The **Test** tab rehearses the schedule on your real devices. Pick a range (it defaults to the next Shabbat/Yom Tov, an hour either side) and ShabBOT steps through every scheduled change in it, grouped by time:

1. It lists what's about to change, e.g. `Simulating 10/23/26 @ 5:44 PM (Candle lighting − 20 min) events: Master Bedroom: OFF`. Times that come from zmanim show where they came from. You can first flip those devices to the opposite state, so you can see the change happen.
2. **Begin test** sends the changes (even in dry run). Then mark the event **Pass** or **Fail**; on Fail, mark each device.
3. **Skip** moves on without testing (its devices are marked skipped). **Back** returns to an earlier event: its results are kept unless you press **Re-test**.
4. At the end, or if you **Cancel test** midway, a summary lists every event done so far with each device's Pass/Fail/Skipped; **Copy results** copies it as text.

While a test runs, protection and the real schedule are paused. When it ends (or after 30 idle minutes), every device it touched goes back to what the schedule wants now, or else to how it was before. Tests can't start during Shabbat/Yom Tov.

## Entities & actions

| Entity | |
|---|---|
| `binary_sensor.shabbot_issur_melacha` | on from candle lighting to havdalah |
| `calendar.shabbot_shabbat_yom_tov`, `calendar.shabbot_routines` | also visible in HA's Calendar |
| `sensor.shabbot_next_candle_lighting`, `sensor.shabbot_next_havdalah` | timestamps |
| `sensor.shabbot_active_overrides` | count, with details in attributes |
| `select.shabbot_mode` | Normal / your modes (selecting one starts it today, open-ended) |
| `switch.shabbot_device_protection`, `switch.shabbot_dry_run` | |

Actions: `shabbot.start_override`, `shabbot.end_override`, `shabbot.set_slot_routine`, `shabbot.skip_slot`, `shabbot.reconcile`.
