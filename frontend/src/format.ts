// Date/time formatting in Home Assistant's time zone (the house's, not the browser's).

let tz: string | undefined;
export const setTimeZone = (zone: string) => {
  tz = zone;
};

const fmt = (opts: Intl.DateTimeFormatOptions) => (iso: string | Date | null | undefined) =>
  iso ? new Intl.DateTimeFormat(undefined, { timeZone: tz, ...opts }).format(new Date(iso)) : "—";

export const time = fmt({ hour: "numeric", minute: "2-digit" });
export const dayTime = fmt({ weekday: "short", hour: "numeric", minute: "2-digit" });
export const dateLong = fmt({ weekday: "long", month: "long", day: "numeric", year: "numeric" });
export const dateShort = fmt({ weekday: "short", month: "short", day: "numeric" });
export const dateTime = fmt({ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export const isoDate = (d: Date) => {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

export const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

export const PART_LABEL: Record<string, string> = { night: "Night meal", day: "Day meal", block: "Baseline" };
export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const HOLIDAY_LABEL: Record<string, string> = {
  rosh_hashana: "Rosh Hashana",
  yom_kippur: "Yom Kippur",
  sukkot: "Sukkot",
  shmini_atzeret: "Shmini Atzeret",
  simchat_torah: "Simchat Torah",
  pesach: "Pesach",
  shavuot: "Shavuot",
};
export const DAY_TYPE_LABEL: Record<string, string> = {
  shabbat: "Shabbat (incl. Yom Tov on Shabbat)",
  yomtov: "Yom Tov (incl. on Shabbat)",
  shabbat_only: "Plain Shabbat",
  yomtov_only: "Yom Tov on a weekday",
};
export const ANCHOR_LABEL: Record<string, string> = {
  alot: "Dawn (alot)",
  sunrise: "Sunrise",
  chatzot: "Midday (chatzot)",
  mincha_gedola: "Mincha gedola",
  plag: "Plag hamincha",
  candle_lighting: "Candle lighting",
  sunset: "Sunset",
  tzeit: "Nightfall (tzeit)",
  havdalah: "Havdalah (end of Shabbat/Yom Tov)",
  midnight: "Midnight",
  slot_start: "Start of this meal period",
  slot_end: "End of this meal period",
  block_start: "Candle lighting (start of Shabbat/Yom Tov)",
  block_end: "Havdalah (end of Shabbat/Yom Tov)",
};

/** Short names for the "Insert time" chips. */
export const ANCHOR_CHIP: Record<string, string> = {
  sunset: "Sunset",
  candle_lighting: "Candle lighting",
  tzeit: "Nightfall",
  havdalah: "Havdalah",
  midnight: "Midnight",
  sunrise: "Sunrise",
  chatzot: "Midday",
};

const EXPR_ALIASES: Record<string, string> = {
  candles: "candle_lighting", candlelighting: "candle_lighting", nightfall: "tzeit",
  start: "slot_start", end: "slot_end", "12am": "midnight",
};

/** "+1h30m-5min" → "+ 1 h 30 min − 5 min". */
const describeOffset = (offset: string) =>
  offset.replace(/\s+/g, "")
    .replace(/(\d+)(h(?:rs?|ours?)?|m(?:ins?|inutes?)?)/g, (_, n: string, u: string) => `${n} ${u.startsWith("h") ? "h" : "min"}`)
    .replace(/([+-])/g, (sign) => ` ${sign === "-" ? "−" : "+"} `)
    .trim();

/** Plain-language reading of a time expression, e.g. "sunset+18m" → "Sunset + 18 min". Null for clock times etc. */
export function describeExpr(expr: string): string | null {
  const text = expr.trim().toLowerCase();
  const fn = text.match(/^(min|max)\s*\((.*)\)$/);
  if (fn) {
    const args = splitArgs(fn[2]).map((a) => describeExpr(a) ?? a.trim());
    return `${fn[1] === "max" ? "Later" : "Earlier"} of ${args.join(" and ")}`;
  }
  const m = text.match(/^([a-z_]+)\s*(.*)$/);
  if (!m) return null;
  const label = ANCHOR_LABEL[EXPR_ALIASES[m[1]] ?? m[1]];
  if (!label) return null;
  return m[2].trim() ? `${label} ${describeOffset(m[2])}` : label;
}

/** Split min()/max() arguments on top-level commas. */
function splitArgs(text: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of text) {
    if (ch === "," && depth === 0) {
      out.push(cur);
      cur = "";
      continue;
    }
    if (ch === "(") depth++;
    if (ch === ")") depth--;
    cur += ch;
  }
  return [...out, cur];
}

/** "10/23/26 @ 5:44 PM" in the house's time zone. */
export const atTime = (iso: string) =>
  `${fmt({ month: "numeric", day: "numeric", year: "2-digit" })(iso)} @ ${time(iso)}`;

/** An ISO time as a `datetime-local` input value ("2026-10-23T17:00") in the house's time zone. */
export function localInput(iso: string | Date): string {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}
