/// <reference types="vite/client" />
import { QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import "../src/styles.css";
import { queryClient } from "../src/api";
import { setHass } from "../src/hass";
import { setTimeZone } from "../src/format";
import { SettingsPage } from "../src/pages/SettingsPage";
import type { AnnounceGroups, AnnounceUpcoming, Hass, HassEntity, Settings } from "../src/types";

const params = new URLSearchParams(location.search);
const dark = params.get("theme") === "dark";
const narrow = params.has("narrow");

const TEMPLATES = {
  candle: "{minutes} {unit} until candle lighting",
  shkia: "{minutes} {unit} until shkia",
  shkia_final: "Shkia in {minutes_words}. Stop all melacha.",
  motzei: "It's now {minutes} {unit} after shkia and it's muttar to do melacha.",
  yt_candle: "{minutes} {unit} until you can start preparing for the next meal",
  yt_candle_now: "You can now start preparing for the next meal.",
};

const GROUPS: AnnounceGroups = {
  candle: true, shkia: true, shkia_final: true, motzei: true, yt_candle: true,
};

const saved: Settings = {
  candle_lighting_min: 18,
  havdalah_mode: "minutes",
  havdalah_degrees: 8.5,
  havdalah_minutes: 60,
  yom_tov_end_minutes: 42,
  israel: false,
  use_elevation: true,
  early_shabbat: false,
  early_shabbat_time: "19:00",
  early_shabbat_after: "19:15",
  latitude: null,
  longitude: null,
  dry_run: false,
  protection: true,
  grace_seconds: 2,
  storm_max_reverts: 3,
  storm_window_min: 2,
  notify_service: "",
  notify_overrides: false,
  announce_enabled: true,
  announce_players: ["media_player.kitchen", "media_player.living_room"],
  announce_tts_entity: "tts.google_translate_en_com",
  announce_voice: "",
  announce_language: "",
  announce_lead_seconds: 8,
  announce_player_leads: {},
  announce_volume: null,
  announce_candle_marks: [60, 30, 15, 5],
  announce_shkia_marks: [60, 30, 15, 5],
  announce_yt_marks: [60, 30, 15, 5],
  announce_shkia_final_min: 1,
  announce_groups: GROUPS,
  announce_templates: TEMPLATES,
};

const UPCOMING: AnnounceUpcoming["items"] = [
  { at: "2026-10-09T17:06:00-04:00", kind: "candle", minutes: 60, message: "60 minutes until candle lighting" },
  { at: "2026-10-09T17:36:00-04:00", kind: "candle", minutes: 30, message: "30 minutes until candle lighting" },
  { at: "2026-10-09T17:51:00-04:00", kind: "candle", minutes: 15, message: "15 minutes until candle lighting" },
  { at: "2026-10-09T18:01:00-04:00", kind: "candle", minutes: 5, message: "5 minutes until candle lighting" },
  { at: "2026-10-09T18:09:00-04:00", kind: "shkia", minutes: 15, message: "15 minutes until shkia" },
  { at: "2026-10-09T18:19:00-04:00", kind: "shkia", minutes: 5, message: "5 minutes until shkia" },
  { at: "2026-10-09T18:23:00-04:00", kind: "shkia_final", minutes: 1, message: "Shkia in one minute. Stop all melacha." },
  { at: "2026-10-10T19:24:00-04:00", kind: "motzei", minutes: 60, message: "It's now 60 minutes after shkia and it's muttar to do melacha." },
];

function entity(id: string, name: string): HassEntity {
  return { entity_id: id, state: "idle", attributes: { friendly_name: name }, last_changed: "2026-10-09T16:00:00-04:00" };
}

function previewUpcoming(settings: Settings): AnnounceUpcoming {
  const groups = settings.announce_groups;
  const items = UPCOMING.filter((item) => {
    if (item.kind === "candle") return groups.candle && settings.announce_candle_marks.includes(item.minutes);
    if (item.kind === "shkia") return groups.shkia && settings.announce_shkia_marks.includes(item.minutes);
    if (item.kind === "shkia_final") return groups.shkia_final;
    if (item.kind === "motzei") return groups.motzei;
    return groups.yt_candle;
  });
  return { enabled: settings.announce_enabled, items: items.slice(0, 8) };
}

const hass: Hass = {
  states: {
    "media_player.kitchen": entity("media_player.kitchen", "Kitchen"),
    "media_player.living_room": entity("media_player.living_room", "Living room"),
    "media_player.dining_room": entity("media_player.dining_room", "Dining room"),
    "tts.google_translate_en_com": entity("tts.google_translate_en_com", "Google Translate en com"),
  },
  services: {},
  user: { name: "Yehuda", is_admin: true },
  themes: { darkMode: dark },
  config: { time_zone: "America/New_York" },
  language: "en",
  callWS: (async (msg) => {
    if (msg.type === "shabbot/config") {
      return {
        config: { settings: saved, routines: {}, rules: [], modes: [], assignments: {}, devices: {} },
        meta: {
          version: "0.2.2",
          anchors: [],
          holiday_groups: [],
          day_types: [],
          detectors: [],
          default_device: {
            protect: true,
            override: { detector: "none" },
            override_minutes: 20,
            after_override: "reassert",
            override_group: [],
          },
          location: { latitude: 40.6501, longitude: -73.94958, time_zone: "America/New_York", elevation: 18 },
          is_admin: true,
        },
      };
    }
    if (msg.type === "shabbot/announce/upcoming") return previewUpcoming(msg.settings as Settings);
    if (msg.type === "shabbot/announce/test") return { dry_run: false };
    return {};
  }) as Hass["callWS"],
  connection: {
    subscribeMessage: async () => async () => undefined,
  },
};

setHass(hass);
setTimeZone("America/New_York");

function Preview() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className={narrow ? "sb-narrow" : undefined}>
        <main className="sb-main" style={{ maxWidth: narrow ? 390 : 760 }}>
          <SettingsPage />
        </main>
      </div>
    </QueryClientProvider>
  );
}

const host = document.createElement("shabbot-panel");
host.dataset.colorScheme = dark ? "dark" : "light";
host.style.display = "block";
host.style.minHeight = "100vh";
document.body.appendChild(host);
createRoot(host).render(<Preview />);
