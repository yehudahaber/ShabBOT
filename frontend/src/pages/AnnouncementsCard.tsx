import { useEffect, useId, useState, type ReactNode } from "react";
import { callWS, friendlyName, useHassSelector } from "../hass";
import { errorMessage } from "../api";
import { dayTime } from "../format";
import { Check, Field } from "../components/ui";
import type { AnnounceGroups, AnnounceTemplates, AnnounceUpcoming, Settings } from "../types";

const MARK_MAX = 720;
const WORDS: Record<number, string> = {
  1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
  6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
};

const TEMPLATES: { key: keyof AnnounceTemplates; label: string }[] = [
  { key: "candle", label: "Candle lighting" },
  { key: "shkia", label: "Shkia countdown" },
  { key: "shkia_final", label: "Final warning" },
  { key: "motzei", label: "Motzaei" },
  { key: "yt_candle", label: "Next-meal preparation, countdown" },
  { key: "yt_candle_now", label: "Next-meal preparation, when it begins" },
];

const DEFAULT_GROUPS: AnnounceGroups = {
  candle: true, shkia: true, shkia_final: true, motzei: true, yt_candle: true,
};

function minutesWords(minutes: number): string {
  const n = Math.abs(minutes);
  if (n === 0) return "less than a minute";
  const unit = n === 1 ? "minute" : "minutes";
  return WORDS[n] ? `${WORDS[n]} ${unit}` : `${n} ${unit}`;
}

function fill(template: string, minutes: number): string {
  const fields: Record<string, string> = {
    minutes: String(minutes),
    unit: minutes === 1 ? "minute" : "minutes",
    minutes_words: minutesWords(minutes),
    occasion: "Shabbat",
    title: "Shabbat",
  };
  return template.replace(/\{(\w+)\}/g, (_, key: string) => fields[key] ?? `{${key}}`);
}

function marksPhrase(marks: number[], before: string): string {
  const sorted = [...marks].sort((a, b) => b - a);
  if (sorted.length === 0) return `Add a minute mark to announce before ${before}.`;
  return `Will announce at ${sorted.join(", ")} min before ${before}.`;
}

function shkiaPhrase(marks: number[]): string {
  const base = marksPhrase(marks, "shkia");
  return marks.length ? `${base} Marks before candle lighting are skipped.` : base;
}

function preparePhrase(marks: number[]): string {
  const sorted = [...marks].sort((a, b) => b - a);
  if (sorted.length === 0) return "Add a minute mark to announce before you can start preparing.";
  return `Will announce at ${sorted.join(", ")} min before you can start preparing. Then once when preparation may begin.`;
}

function samePlayers(a: [string, string][], b: [string, string][]): boolean {
  return a.length === b.length && a.every((row, i) => row[0] === b[i][0] && row[1] === b[i][1]);
}

export function AnnouncementsCard({ draft, set, dirty, dryRun, onNotice, startAdvanced = false }: {
  draft: Settings;
  set: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  dirty: boolean;
  dryRun: boolean;
  onNotice: (message: string) => void;
  /** Preview harness: open the Advanced section. */
  startAdvanced?: boolean;
}) {
  const groups = draft.announce_groups ?? DEFAULT_GROUPS;
  const templates = draft.announce_templates;
  const setGroup = (key: keyof AnnounceGroups, on: boolean) => set("announce_groups", { ...groups, [key]: on });
  const setTemplate = (key: keyof AnnounceTemplates, value: string) =>
    set("announce_templates", { ...templates, [key]: value });
  const [testing, setTesting] = useState(false);
  const [upcoming, setUpcoming] = useState<AnnounceUpcoming | null>(null);
  const [upcomingError, setUpcomingError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      callWS<AnnounceUpcoming>({ type: "shabbot/announce/upcoming", settings: draft }).then(
        (result) => {
          if (!cancelled) {
            setUpcoming(result);
            setUpcomingError("");
          }
        },
        (err) => {
          if (!cancelled) setUpcomingError(errorMessage(err));
        },
      );
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [draft]);

  const testSpeak = async () => {
    setTesting(true);
    try {
      const result = await callWS<{ dry_run: boolean }>({ type: "shabbot/announce/test" });
      onNotice(result.dry_run
        ? "Dry run: the test was logged on the Activity tab, not spoken."
        : "Test announcement sent.");
    } catch (e) {
      onNotice(errorMessage(e));
    } finally {
      setTesting(false);
    }
  };

  const shabbatEnd = draft.havdalah_mode === "minutes" ? `${draft.havdalah_minutes} min after shkia` : "the sun-angle havdalah";
  const yomTovEnd = draft.yom_tov_end_minutes ?? 42;

  return (
    <div className="sb-card sb-card-pad sb-stack">
      <div>
        <h3 className="sb-section-title">Announcements</h3>
        <p className="sb-hint">
          A short sentence on the speakers you pick: before candle lighting, before shkia, and at havdalah when melacha is permitted.
        </p>
      </div>
      <Check checked={draft.announce_enabled} onChange={(v) => set("announce_enabled", v)}>
        Speak announcements
      </Check>
      {dryRun && (
        <p className="sb-hint">Dry run is on, so sentences are logged on Activity instead of spoken.</p>
      )}

      <SpeakerPicker value={draft.announce_players} onChange={(v) => set("announce_players", v)} />

      <div className="sb-grid-2">
        <TtsField value={draft.announce_tts_entity} onChange={(v) => set("announce_tts_entity", v)} />
        <Field label="Lead (seconds)" hint="Start this early so the words land on time. Sonos often needs 5–10.">
          <input className="sb-input" type="number" min={0} max={300} value={draft.announce_lead_seconds}
            onChange={(e) => set("announce_lead_seconds", clampInt(e.target.value, 0, 300))} />
        </Field>
      </div>

      <VolumeField value={draft.announce_volume} onChange={(v) => set("announce_volume", v)} />

      <div className="sb-announce-groups">
        <Group title="Candle lighting countdown" on={groups.candle} onToggle={(v) => setGroup("candle", v)}>
          <MinuteChips value={draft.announce_candle_marks} onChange={(v) => set("announce_candle_marks", v)}
            phrase={marksPhrase(draft.announce_candle_marks, "candle lighting")} />
        </Group>
        <Group title="Shkia countdown" on={groups.shkia} onToggle={(v) => setGroup("shkia", v)}>
          <MinuteChips value={draft.announce_shkia_marks} onChange={(v) => set("announce_shkia_marks", v)}
            phrase={shkiaPhrase(draft.announce_shkia_marks)} />
        </Group>
        <Group title="Final “stop melacha” warning" on={groups.shkia_final} onToggle={(v) => setGroup("shkia_final", v)}>
          <Field label="Minutes before shkia">
            <input className="sb-input sb-mark-add" type="number" min={0} max={180} value={draft.announce_shkia_final_min}
              onChange={(e) => set("announce_shkia_final_min", clampInt(e.target.value, 0, 180))} />
          </Field>
          <p className="sb-hint">{sentencePreview(templates.shkia_final, draft.announce_shkia_final_min)}</p>
        </Group>
        <Group title="Motzaei “muttar”" on={groups.motzei} onToggle={(v) => setGroup("motzei", v)}>
          <p className="sb-hint">
            Spoken when the block ends. Shabbat uses {shabbatEnd}. A Yom Tov that is not Shabbat uses Yom Tov end ({yomTovEnd} min). {sentencePreview(templates.motzei, draft.havdalah_mode === "minutes" ? draft.havdalah_minutes : yomTovEnd)}
          </p>
        </Group>
        <Group title="Next-meal preparation" on={groups.yt_candle} onToggle={(v) => setGroup("yt_candle", v)}>
          <MinuteChips value={draft.announce_yt_marks ?? [60, 30, 15, 5]} onChange={(v) => set("announce_yt_marks", v)}
            phrase={preparePhrase(draft.announce_yt_marks ?? [60, 30, 15, 5])} />
          <p className="sb-hint">A later Yom Tov night. After Shabbat this is Shabbat havdalah; after a Yom Tov day it is Yom Tov end.</p>
        </Group>
      </div>

      <details className="sb-advanced" {...(startAdvanced ? { open: true } : {})}>
        <summary>Advanced</summary>
        <div className="sb-stack">
          <p className="sb-hint">A different lead for one speaker, the voice, and the exact sentences.</p>
          {draft.announce_players.length > 0 ? (
            <div className="sb-grid-2">
              {draft.announce_players.map((id) => (
                <Field key={id} label={`${friendlyName(id)} lead (seconds)`} hint="Blank uses the lead above.">
                  <input className="sb-input" type="number" min={0} max={300} value={draft.announce_player_leads[id] ?? ""}
                    onChange={(e) => {
                      const next = { ...draft.announce_player_leads };
                      if (e.target.value === "") delete next[id];
                      else next[id] = clampInt(e.target.value, 0, 300);
                      set("announce_player_leads", next);
                    }} />
                </Field>
              ))}
            </div>
          ) : (
            <p className="sb-hint">Choose speakers to give one of them its own lead.</p>
          )}
          <div className="sb-grid-2">
            <Field label="Voice" hint="Blank uses the engine’s default.">
              <input className="sb-input" value={draft.announce_voice} onChange={(e) => set("announce_voice", e.target.value)} />
            </Field>
            <Field label="Language" hint="Blank uses the engine’s default. Example: en">
              <input className="sb-input" value={draft.announce_language} onChange={(e) => set("announce_language", e.target.value)} />
            </Field>
          </div>
          <p className="sb-hint">
            Placeholders: {"{minutes}"}, {"{unit}"}, {"{minutes_words}"}, {"{occasion}"}, {"{title}"}. A blank template skips that sentence.
          </p>
          {TEMPLATES.map((row) => (
            <Field key={row.key} label={row.label}>
              <textarea className="sb-input" value={templates[row.key]} onChange={(e) => setTemplate(row.key, e.target.value)} />
            </Field>
          ))}
        </div>
      </details>

      <div className="sb-row">
        <button className="sb-btn" type="button" disabled={testing || dirty} onClick={testSpeak}>
          {testing ? "Speaking…" : "Speak a test"}
        </button>
        <span className="sb-hint">
          {dirty
            ? "Save first. The test uses the saved speakers and engine."
            : dryRun
              ? "Dry run is on, so the test is logged rather than spoken."
              : "Uses the saved speakers, engine, and volume."}
        </span>
      </div>

      <div className="sb-stack" style={{ gap: 6 }}>
        <h4 className="sb-subtitle">Next announcements</h4>
        {upcoming && !upcoming.enabled && (
          <p className="sb-hint">Announcements are off. These are the times that would be spoken.</p>
        )}
        {upcomingError ? (
          <p className="sb-error">{upcomingError}</p>
        ) : upcoming == null ? (
          <p className="sb-hint">Checking the calendar…</p>
        ) : upcoming.items.length === 0 ? (
          <p className="sb-hint">Nothing coming up in the next two months.</p>
        ) : (
          <ul className="sb-upcoming">
            {(upcoming?.items ?? []).map((item) => (
              <li key={`${item.at}:${item.kind}:${item.minutes}`}>
                <time dateTime={item.at}>{dayTime(item.at)}</time>
                <span>{item.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function clampInt(raw: string, min: number, max: number): number {
  if (raw === "") return min;
  const n = Math.trunc(Number(raw));
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

function sentencePreview(template: string, minutes: number): string {
  if (!template.trim()) return "This sentence is blank, so it stays quiet.";
  return `“${fill(template, minutes)}”`;
}

function Group({ title, on, onToggle, children }: {
  title: string; on: boolean; onToggle: (v: boolean) => void; children: ReactNode;
}) {
  return (
    <div className="sb-announce-group">
      <Check checked={on} onChange={onToggle}>{title}</Check>
      {on && <div className="sb-announce-body">{children}</div>}
    </div>
  );
}

function MinuteChips({ value, onChange, phrase }: {
  value: number[]; onChange: (v: number[]) => void; phrase: string;
}) {
  const [raw, setRaw] = useState("");
  const [error, setError] = useState("");
  const sorted = [...value].sort((a, b) => b - a);
  const add = () => {
    const text = raw.trim();
    if (!/^\d+$/.test(text)) {
      setError(`Enter a whole number from 1 to ${MARK_MAX}.`);
      return;
    }
    const n = Number(text);
    if (n < 1 || n > MARK_MAX) {
      setError(`Enter a whole number from 1 to ${MARK_MAX}.`);
      return;
    }
    if (sorted.includes(n)) {
      setError(`${n} is already in the list.`);
      return;
    }
    onChange([...sorted, n].sort((a, b) => b - a));
    setRaw("");
    setError("");
  };
  return (
    <div className="sb-stack" style={{ gap: 6 }}>
      <div className="sb-chips" aria-label="Minute marks">
        {sorted.map((minutes) => (
          <button key={minutes} type="button" className="sb-chip sb-chip-mark"
            aria-label={`Remove ${minutes} minutes`} onClick={() => onChange(sorted.filter((m) => m !== minutes))}>
            {minutes} <span aria-hidden="true">×</span>
          </button>
        ))}
      </div>
      <div className="sb-mark-row">
        <input className={`sb-input sb-mark-add ${error ? "sb-invalid" : ""}`} type="number" inputMode="numeric"
          min={1} max={MARK_MAX} value={raw} aria-label="Minutes to add" placeholder="Minutes"
          onChange={(e) => {
            setRaw(e.target.value);
            setError("");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }} />
        <button className="sb-btn sb-btn-sm" type="button" onClick={add}>Add</button>
      </div>
      {error && <p className="sb-error" role="alert">{error}</p>}
      <p className="sb-hint">{phrase}</p>
    </div>
  );
}

function SpeakerPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const labelId = useId();
  const players = useHassSelector((h) => {
    const rows = Object.values(h.states)
      .filter((s) => s.entity_id.startsWith("media_player."))
      .map((s) => [s.entity_id, (s.attributes.friendly_name as string) || s.entity_id] as [string, string]);
    rows.sort((a, b) => a[1].localeCompare(b[1]));
    return rows;
  }, samePlayers);
  const known = new Set(players.map(([id]) => id));
  const missing = value.filter((id) => !known.has(id));
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const shown = players.filter(([id, name]) => !needle || name.toLowerCase().includes(needle) || id.includes(needle));
  const toggle = (id: string, on: boolean) => {
    onChange(on ? [...value, id] : value.filter((x) => x !== id));
  };
  return (
    <div className="sb-field">
      <span id={labelId}>Speakers</span>
      {players.length > 6 && (
        <input className="sb-input" value={filter} placeholder="Filter speakers…" aria-label="Filter speakers"
          onChange={(e) => setFilter(e.target.value)} />
      )}
      <div className="sb-pick-list" role="group" aria-labelledby={labelId}>
        {shown.length === 0 && missing.length === 0 && (
          <p className="sb-hint">No media players in Home Assistant yet.</p>
        )}
        {shown.map(([id, name]) => (
          <label key={id} className="sb-check">
            <input type="checkbox" checked={value.includes(id)} onChange={(e) => toggle(id, e.target.checked)} />
            {name}
          </label>
        ))}
        {missing.map((id) => (
          <label key={id} className="sb-check">
            <input type="checkbox" checked onChange={() => toggle(id, false)} />
            {id}
          </label>
        ))}
      </div>
    </div>
  );
}

function TtsField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const engines = useHassSelector((h) => Object.keys(h.states).filter((id) => id.startsWith("tts.")).sort(), (a, b) =>
    a.length === b.length && a.every((id, i) => id === b[i]));
  return (
    <Field label="TTS engine" hint="The voice that speaks. Choose one before a live test.">
      <select className="sb-select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose an engine…</option>
        {value && !engines.includes(value) && <option value={value}>{value}</option>}
        {engines.map((id) => <option key={id} value={id}>{friendlyName(id)}</option>)}
      </select>
    </Field>
  );
}

function VolumeField({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  const volumeId = useId();
  const [remembered, setRemembered] = useState(value ?? 40);
  const alone = value == null;
  const shown = alone ? remembered : value;
  return (
    <div className="sb-field">
      <span id={volumeId}>Volume</span>
      <div className="sb-volume">
        <input type="range" min={0} max={100} step={1} disabled={alone} value={shown}
          aria-labelledby={volumeId} aria-valuemin={0} aria-valuemax={100} aria-valuenow={shown}
          aria-valuetext={alone ? "Leave volume alone" : `${shown} percent`}
          onChange={(e) => {
            const n = Number(e.target.value);
            setRemembered(n);
            onChange(n);
          }} />
        <span className="sb-volume-readout">{alone ? "—" : `${shown}%`}</span>
      </div>
      <Check checked={alone} onChange={(on) => onChange(on ? null : remembered)}>
        Leave each speaker’s volume alone
      </Check>
      <small className="sb-hint">Applied for the sentence, then put back. Sonos restores the previous playback too.</small>
    </div>
  );
}
