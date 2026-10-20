// Shapes returned by the shabbot/* websocket API (see custom_components/shabbot/websocket.py).

export type Part = "night" | "day" | "block";
export type OnOff = "on" | "off";

export interface Action {
  id: string;
  /** Devices this row controls. Rows saved before multi-device support have `entity_id` instead. */
  entity_ids?: string[];
  entity_id?: string;
  state: OnOff;
  brightness?: number | null;
  temperature?: number | null;
  start: string;
  end: string;
  end_state?: "on" | "off" | "leave" | null;
  label?: string | null;
  /** Baseline rows only: run once, every night, or every day of the Shabbat/Yom Tov. */
  repeat?: "once" | "night" | "day" | null;
}

/** All routines in the order the user arranged them on the Routines page. */
export const routineList = (config: Pick<Config, "routines" | "routine_order">): Routine[] => {
  const ids = [...new Set([...(config.routine_order ?? []), ...Object.keys(config.routines)])];
  return ids.map((id) => config.routines[id]).filter((r): r is Routine => !!r);
};

export const entitiesOf = (a: Pick<Action, "entity_ids" | "entity_id">): string[] =>
  a.entity_ids ?? (a.entity_id ? [a.entity_id] : []);

export interface Routine {
  id: string;
  name: string;
  part: Part;
  color?: string | null;
  description?: string | null;
  actions: Action[];
}

export interface RuleMatch {
  day_type?: string | null;
  holiday_group?: string | null;
  holiday?: string | null;
  day_in_block?: number | null;
  weekday?: number | null;
}

export interface Rule {
  id: string;
  name: string;
  part: Part;
  enabled: boolean;
  match: RuleMatch;
  routine_id: string | null;
}

export interface Mode {
  id: string;
  name: string;
  enabled: boolean;
  start: string;
  end: string | null;
  night: string | null;
  day: string | null;
  block: string | null;
  protection: boolean;
}

export interface Matcher {
  event_type: string;
  data?: Record<string, unknown>;
}

export interface DeviceConfig {
  protect?: boolean;
  override?: {
    detector: "none" | "event" | "flip_pattern" | "persistence";
    start?: Matcher | null;
    end?: Matcher | null;
    count?: number | null;
    window_s?: number | null;
    preset?: string | null;
  };
  override_minutes?: number;
  after_override?: "reassert" | "next_transition";
  override_group?: string[];
}

export interface Settings {
  candle_lighting_min: number;
  havdalah_mode: "degrees" | "minutes";
  havdalah_degrees: number;
  havdalah_minutes: number;
  yom_tov_end_minutes: number;
  israel: boolean;
  use_elevation: boolean;
  early_shabbat: boolean;
  early_shabbat_time: string;
  early_shabbat_after: string;
  latitude: number | null;
  longitude: number | null;
  dry_run: boolean;
  protection: boolean;
  grace_seconds: number;
  storm_max_reverts: number;
  storm_window_min: number;
  notify_service: string;
  notify_overrides: boolean;
  voice_enabled: boolean;
  announce_enabled: boolean;
  announce_players: string[];
  announce_tts_entity: string;
  announce_voice: string;
  announce_language: string;
  announce_lead_seconds: number;
  announce_player_leads: Record<string, number>;
  announce_volume: number | null;
  announce_candle_marks: number[];
  announce_shkia_marks: number[];
  announce_yt_marks: number[];
  announce_shkia_final_min: number;
  announce_groups: AnnounceGroups;
  announce_templates: AnnounceTemplates;
  announce_pronunciations: Record<string, string>;
  briefing_template: string;
  briefing_weather_entity: string;
  briefing_notes_entity: string;
  briefing_notes_until: string;
}

export interface AnnounceGroups {
  candle: boolean;
  shkia: boolean;
  shkia_final: boolean;
  motzei: boolean;
  yt_candle: boolean;
}

export interface AnnounceUpcoming {
  enabled: boolean;
  items: { at: string; kind: string; message: string; minutes: number }[];
}

export interface AnnounceTemplates {
  candle: string;
  shkia: string;
  shkia_final: string;
  motzei: string;
  yt_candle: string;
  yt_candle_now: string;
}

export interface Config {
  settings: Settings;
  routines: Record<string, Routine>;
  /** Routine ids in the user's order (see routineList). */
  routine_order?: string[];
  rules: Rule[];
  modes: Mode[];
  assignments: Record<string, { routine_id?: string; skip?: boolean; disabled_actions?: string[] }>;
  devices: Record<string, DeviceConfig>;
}

export interface Meta {
  version: string;
  anchors: string[];
  holiday_groups: string[];
  day_types: string[];
  detectors: string[];
  default_device: Required<DeviceConfig>;
  default_settings?: Settings;
  location: { latitude: number; longitude: number; time_zone: string; elevation: number };
  is_admin: boolean;
}

export interface Slot {
  key: string;
  day: string;
  part: "night" | "day";
  base_date: string;
  start: string;
  end: string;
  is_shabbat: boolean;
  is_yomtov: boolean;
  holiday: string | null;
  holiday_group: string | null;
  day_in_block: number;
  block_id: string;
  title: string;
  anchors: Record<string, string>;
}

export interface Block {
  id: string;
  title: string;
  days: string[];
  start: string;
  end: string;
  /** Set when Shabbat starts early: the normal candle-lighting time. */
  normal_start: string | null;
  slots: Slot[];
}

export interface PlannedAction {
  action_id: string;
  entity_id: string;
  state: OnOff;
  attrs: Record<string, number>;
  start: string | null;
  end: string | null;
  end_state: string;
  disabled: boolean;
  error: string | null;
  next_day: boolean;
  occurrence_key: string | null;
  occurrence_title: string | null;
}

export interface Instance {
  key: string;
  part: Part;
  block_id: string;
  slot: Slot | null;
  target_title: string;
  routine_id: string | null;
  routine_name: string | null;
  color: string | null;
  source: "assignment" | "mode" | "rule" | "skipped" | "none";
  source_name: string;
  default_routine_id: string | null;
  start: string;
  end: string;
  actions: PlannedAction[];
}

export interface Plan {
  blocks: Block[];
  instances: Instance[];
}

export interface Interval {
  entity_id: string;
  start: string;
  end: string;
  state: OnOff;
  attrs: Record<string, number>;
  end_state: string;
  instance_key: string;
  routine_name: string;
  action_id: string;
}

export interface EntityStatus {
  entity_id: string;
  name: string;
  state: string | null;
  desired: Interval | null;
  in_sync: boolean;
  protected: boolean;
  override: { until: string; started: string; reason: string } | null;
  paused: string | null;
  pending_revert: boolean;
}

export interface Status {
  now: string;
  issur_melacha: boolean;
  block: { id: string; title: string; start: string; end: string } | null;
  dry_run: boolean;
  protection: boolean;
  next_boundary: string | null;
  location: Meta["location"];
  entities: EntityStatus[];
}

export interface ActivityEntry {
  ts: string;
  kind: string;
  entity_id: string | null;
  message: string;
  [key: string]: unknown;
}

export interface LearnedEvent {
  event_type: string;
  data: Record<string, unknown>;
  time: string;
  matcher: Matcher;
}

// Minimal slice of Home Assistant's frontend `hass` object that the panel uses.
export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown> & { friendly_name?: string };
  last_changed: string;
}

export interface Hass {
  states: Record<string, HassEntity>;
  services: Record<string, Record<string, unknown>>;
  user: { name: string; is_admin: boolean };
  themes: { darkMode?: boolean };
  config: { time_zone: string };
  language: string;
  callWS<T>(msg: Record<string, unknown>): Promise<T>;
  connection: {
    subscribeMessage<T>(cb: (msg: T) => void, msg: Record<string, unknown>): Promise<() => Promise<void>>;
  };
}

/** Result of shabbot/routine/check for one routine row over the next year. */
export interface RowCheck {
  index: number;
  total: number;
  next_day: number;
  invalid: number;
  always_invalid: boolean;
  error: string | null;
  first: { key: string; title: string; start: string; end: string; next_day: boolean } | null;
  next_day_example: { key: string; title: string; start: string; end: string } | null;
  invalid_example: { key: string; title: string } | null;
  before_start: number;
  after_end: number;
  before_start_example: { key: string; title: string; start: string; end: string } | null;
  after_end_example: { key: string; title: string; start: string; end: string } | null;
}
