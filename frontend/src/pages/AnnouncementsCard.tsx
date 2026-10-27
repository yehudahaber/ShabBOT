import { useEffect, useId, useState, type ReactNode } from "react";
import { callWS, friendlyName, useHassSelector } from "../hass";
import { errorMessage } from "../api";
import { dayTime } from "../format";
import { Check, Field } from "../components/ui";
import { applyPronunciation } from "../pronunciations";
import type { AnnounceGroups, AnnounceTemplates, AnnounceUpcoming, Settings } from "../types";

const MARK_MAX = 720;
const WORDS: Record<number, string> = {
  1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
  6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
};

const DEFAULT_GROUPS: AnnounceGroups = {
  candle: true, candle_now: true, shkia: true, shkia_final: true, motzei: true, yt_candle: true,
};

const ABOUT: Record<number, string> = {
  5: "five", 10: "ten", 15: "fifteen", 20: "twenty", 25: "twenty-five",
  30: "thirty", 35: "thirty-five", 40: "forty", 45: "forty-five",
  50: "fifty", 55: "fifty-five",
};

function minutesWords(minutes: number): string {
  const n = Math.abs(minutes);
  if (n === 0) return "less than a minute";
  const unit = n === 1 ? "minute" : "minutes";
  return WORDS[n] ? `${WORDS[n]} ${unit}` : `${n} ${unit}`;
}

function aboutMinutes(minutes: number): string {
  const n = Math.abs(minutes);
  if (n <= 0) return "less than a minute";
  if (n === 1) return "about a minute";
  if (n === 2) return "about a couple of minutes";
  if (n <= 4) return "about a few minutes";
  const rounded = Math.max(5, Math.round(n / 5) * 5);
  if (rounded === 30) return "about half an hour";
  if (rounded < 60) return `about ${ABOUT[rounded] ?? rounded} minutes`;
  const hours = Math.floor(rounded / 60);
  const rem = rounded % 60;
  const hour = hours === 1 ? "an hour" : `${hours} hours`;
  if (rem === 0) return `about ${hour}`;
  if (rem === 30) return `about ${hour} and a half`;
  return `about ${hour} and ${ABOUT[rem] ?? rem} minutes`;
}

function fill(template: string, minutes: number): string {
  const about = aboutMinutes(minutes);
  const fields: Record<string, string> = {
    minutes: String(minutes),
    unit: minutes === 1 ? "minute" : "minutes",
    minutes_words: minutesWords(minutes),
    about,
    About: about.charAt(0).toUpperCase() + about.slice(1),
    time: "at 6:08",
    parasha: "Lech-Lecha",
    hebrew_date: "9 Cheshvan 5787",
    daf: "Bechoros 32",
    zman_name: "candle lighting",
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

export function AnnouncementsCard({ draft, set, dirty, dryRun, onNotice, startAdvanced = false, defaults }: {
  draft: Settings;
  set: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  dirty: boolean;
  dryRun: boolean;
  onNotice: (message: string) => void;
  /** Preview harness: open the Advanced section. */
  startAdvanced?: boolean;
  defaults?: Settings;
}) {
  const groups = draft.announce_groups ?? DEFAULT_GROUPS;
  const templates = draft.announce_templates;
  const defaultTemplates = defaults?.announce_templates ?? templates;
  const defaultPronunciations = defaults?.announce_pronunciations;
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

  const testSpeak = async (message?: string) => {
    setTesting(true);
    try {
      const result = await callWS<{ dry_run: boolean; spoken: string }>({
        type: "shabbot/announce/test",
        ...(message ? { message } : {}),
      });
      const heard = result.spoken && result.spoken !== (message || "") ? ` Heard as “${result.spoken}”.` : "";
      onNotice(result.dry_run
        ? `Dry run: the test was logged on the Activity tab, not spoken.${heard}`
        : `Test announcement sent.${heard}`);
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
        <h3 className="sb-section-title">Voice</h3>
        <p className="sb-hint">
          Optional. Announcements and a kids' daily briefing, using the calendar ShabBOT already knows. Off on a new install. A home that already speaks keeps it on.
        </p>
      </div>
      <Check checked={draft.voice_enabled} onChange={(v) => set("voice_enabled", v)}>
        Voice module
      </Check>
      {draft.voice_enabled && (
      <Check checked={draft.announce_enabled} onChange={(v) => set("announce_enabled", v)}>
        Speak announcements
      </Check>
      )}
      {draft.voice_enabled && dryRun && (
        <p className="sb-hint">Dry run is on, so sentences are logged on Activity instead of spoken.</p>
      )}

      {draft.voice_enabled && <>
      <SpeakerPicker value={draft.announce_players} onChange={(v) => set("announce_players", v)} />

      <div className="sb-grid-2">
        <TtsField value={draft.announce_tts_entity} onChange={(v) => set("announce_tts_entity", v)} />
        <VoiceField engine={draft.announce_tts_entity} language={draft.announce_language}
          value={draft.announce_voice} onChange={(v) => set("announce_voice", v)} />
      </div>
      <Field label="Lead (seconds)" hint="Start this early so the words land on time. The stop-melacha clip also starts early by its own length, so it finishes on the mark. Sonos often needs 5–10.">
        <input className="sb-input" type="number" min={0} max={300} value={draft.announce_lead_seconds}
          onChange={(e) => set("announce_lead_seconds", clampInt(e.target.value, 0, 300))} />
      </Field>

      <VolumeField value={draft.announce_volume} onChange={(v) => set("announce_volume", v)} />

      <div className="sb-grid-2">
        <Field label="Repeat" hint="Total plays of each sentence, with a short gap between them. The final warning starts early enough to finish on its mark.">
          <select className="sb-input" value={draft.announce_repeat ?? "once"}
            onChange={(e) => set("announce_repeat", e.target.value === "twice" ? "twice" : "once")}>
            <option value="once">Repeat once</option>
            <option value="twice">Repeat twice</option>
          </select>
        </Field>
        <Field label="Gap (ms)" hint="Silence between the cue and the sentence, and between repeats.">
          <input className="sb-input" type="number" min={0} max={5000} step={50} value={draft.announce_gap_ms ?? 400}
            onChange={(e) => set("announce_gap_ms", clampInt(e.target.value, 0, 5000))} />
        </Field>
      </div>
      <Check checked={draft.announce_cue ?? false} onChange={(v) => set("announce_cue", v)}>
        Soft cue beep before each announcement
      </Check>
      {draft.announce_cue && (
        <Field label="Custom cue (optional)" hint="A media-source or URL id to play instead of the bundled soft tone.">
          <input className="sb-input" value={draft.announce_cue_media_id ?? ""} spellCheck={false}
            placeholder="media-source://media_source/local/…"
            onChange={(e) => set("announce_cue_media_id", e.target.value)} />
        </Field>
      )}

      <p className="sb-hint">
        Each announcement is a switch, the minute marks, and the wording. Placeholders: {"{minutes}"}, {"{time}"}, {"{about}"}, {"{parasha}"}, {"{hebrew_date}"}, {"{daf}"}, {"{zman_name}"}. Leave the wording blank to skip that sentence.
      </p>
      <div className="sb-announce-groups">
        <Group title="Candle lighting countdown" on={groups.candle} onToggle={(v) => setGroup("candle", v)}>
          <MinuteChips value={draft.announce_candle_marks} onChange={(v) => set("announce_candle_marks", v)}
            phrase={marksPhrase(draft.announce_candle_marks, "candle lighting")} />
          <Wording value={templates.candle} fallback={defaultTemplates.candle} minutes={draft.announce_candle_marks[0] ?? 20}
            onChange={(v) => setTemplate("candle", v)} />
        </Group>
        <Group title="At candle lighting" on={groups.candle_now} onToggle={(v) => setGroup("candle_now", v)}>
          <p className="sb-hint">Spoken once at candle lighting itself, on erev Shabbat and erev Yom Tov.</p>
          <Wording value={templates.candle_now} fallback={defaultTemplates.candle_now} minutes={0}
            onChange={(v) => setTemplate("candle_now", v)} />
        </Group>
        <Group title="Shkia countdown" on={groups.shkia} onToggle={(v) => setGroup("shkia", v)}>
          <MinuteChips value={draft.announce_shkia_marks} onChange={(v) => set("announce_shkia_marks", v)}
            phrase={shkiaPhrase(draft.announce_shkia_marks)} />
          <Wording value={templates.shkia} fallback={defaultTemplates.shkia} minutes={draft.announce_shkia_marks[0] ?? 20}
            onChange={(v) => setTemplate("shkia", v)} />
        </Group>
        <Group title="Final “stop melacha” warning" on={groups.shkia_final} onToggle={(v) => setGroup("shkia_final", v)}>
          <Field label="Minutes before shkia">
            <input className="sb-input sb-mark-add" type="number" min={0} max={180} value={draft.announce_shkia_final_min}
              onChange={(e) => set("announce_shkia_final_min", clampInt(e.target.value, 0, 180))} />
          </Field>
          <Wording value={templates.shkia_final} fallback={defaultTemplates.shkia_final} minutes={draft.announce_shkia_final_min}
            onChange={(v) => setTemplate("shkia_final", v)} />
        </Group>
        <Group title="Motzei Shabbat" on={groups.motzei} onToggle={(v) => setGroup("motzei", v)}>
          <p className="sb-hint">
            Spoken when the block ends. Shabbat uses {shabbatEnd}. A Yom Tov that is not Shabbat uses Yom Tov end ({yomTovEnd} min).
          </p>
          <Wording value={templates.motzei} fallback={defaultTemplates.motzei}
            minutes={draft.havdalah_mode === "minutes" ? draft.havdalah_minutes : yomTovEnd}
            onChange={(v) => setTemplate("motzei", v)} />
        </Group>
        <Group title="Next-meal preparation" on={groups.yt_candle} onToggle={(v) => setGroup("yt_candle", v)}>
          <MinuteChips value={draft.announce_yt_marks ?? [60, 30, 15, 5]} onChange={(v) => set("announce_yt_marks", v)}
            phrase={preparePhrase(draft.announce_yt_marks ?? [60, 30, 15, 5])} />
          <p className="sb-hint">A later Yom Tov night. After Shabbat this is Shabbat havdalah; after a Yom Tov day it is Yom Tov end.</p>
          <Wording label="Countdown" value={templates.yt_candle} fallback={defaultTemplates.yt_candle}
            minutes={(draft.announce_yt_marks ?? [30])[0] ?? 30} onChange={(v) => setTemplate("yt_candle", v)} />
          <Wording label="When it begins" value={templates.yt_candle_now} fallback={defaultTemplates.yt_candle_now}
            minutes={0} onChange={(v) => setTemplate("yt_candle_now", v)} />
        </Group>
      </div>

      <PronunciationEditor
        value={draft.announce_pronunciations ?? {}}
        defaults={defaultPronunciations ?? {}}
        onChange={(v) => set("announce_pronunciations", v)}
        lexiconPath={draft.tts_lexicon_path ?? ""}
        onLexiconPath={(v) => set("tts_lexicon_path", v)}
        testing={testing}
        dirty={dirty}
        onSpeak={(line) => void testSpeak(line)}
      />

      <details className="sb-advanced" {...(startAdvanced ? { open: true } : {})}>
        <summary>Advanced</summary>
        <div className="sb-stack">
          <p className="sb-hint">A different lead for one speaker, and the language.</p>
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
          <Field label="Language" hint="Blank uses the engine’s default. Example: en_US">
            <input className="sb-input" value={draft.announce_language} onChange={(e) => set("announce_language", e.target.value)} />
          </Field>
        </div>
      </details>

      <BriefingFields draft={draft} set={set} fallback={defaults?.briefing_template ?? draft.briefing_template} />

      <div className="sb-row">
        <button className="sb-btn" type="button" disabled={testing || dirty} onClick={() => void testSpeak()}>
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
      </>}
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

function Wording({ label = "Wording", value, fallback, minutes, onChange }: {
  label?: string;
  value: string;
  fallback: string;
  minutes: number;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label} hint={sentencePreview(value, minutes)}>
      <textarea className="sb-input" rows={2} value={value} onChange={(e) => onChange(e.target.value)} />
      {value !== fallback && (
        <button className="sb-btn sb-btn-sm" type="button" onClick={() => onChange(fallback)}>
          Reset wording
        </button>
      )}
    </Field>
  );
}

function BriefingFields({ draft, set, fallback }: {
  draft: Settings;
  set: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  fallback: string;
}) {
  const notes = draft.briefing_notes_entity ?? "";
  return (
    <div className="sb-stack">
      <div>
        <h4 className="sb-subtitle">Kids' daily briefing</h4>
        <p className="sb-hint">
          One spoken script: the Hebrew date, the parasha or the holiday, the daf, shkia, and candle lighting or havdalah when they apply, plus how soon Shabbat or Yom Tov starts. Weather comes only from the weather entity you pick. A note comes only from a todo list or a text helper, and can expire. Nothing is read from the web.
        </p>
      </div>
      <EntitySelect
        label="Weather"
        hint="Leave blank to skip the weather. ShabBOT uses the condition, the high, the low, and the chance of rain. It does not read a written forecast."
        prefixes={["weather."]}
        value={draft.briefing_weather_entity ?? ""}
        onChange={(v) => set("briefing_weather_entity", v)}
      />
      <EntitySelect
        label="Note from home"
        hint="A todo list, or one text helper. Leave blank to skip. A todo item drops off after its due date."
        prefixes={["todo.", "input_text."]}
        value={notes}
        onChange={(v) => set("briefing_notes_entity", v)}
      />
      {notes.startsWith("input_text.") && (
        <Field label="Hide this note after" hint="Blank keeps it.">
          <input className="sb-input" type="date" value={draft.briefing_notes_until ?? ""}
            onChange={(e) => set("briefing_notes_until", e.target.value)} />
        </Field>
      )}
      <Field label="Briefing wording" hint="Placeholders: {hebrew_date}, {reading}, {parasha}, {daf}, {zmanim}, {countdown}, {weather}, {notes}. A missing piece is left out.">
        <textarea className="sb-input" rows={4} value={draft.briefing_template ?? ""}
          onChange={(e) => set("briefing_template", e.target.value)} />
      </Field>
      {(draft.briefing_template ?? "") !== fallback && (
        <button className="sb-btn sb-btn-sm" type="button" onClick={() => set("briefing_template", fallback)}>
          Reset wording
        </button>
      )}
    </div>
  );
}

function EntitySelect({ label, hint, prefixes, value, onChange }: {
  label: string;
  hint: string;
  prefixes: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  const entities = useHassSelector((h) => {
    const rows = Object.values(h.states)
      .filter((s) => prefixes.some((prefix) => s.entity_id.startsWith(prefix)))
      .map((s) => [s.entity_id, (s.attributes.friendly_name as string) || s.entity_id] as [string, string]);
    rows.sort((a, b) => a[1].localeCompare(b[1]));
    return rows;
  }, (a, b) => a.length === b.length && a.every((row, i) => row[0] === b[i][0] && row[1] === b[i][1]));
  return (
    <Field label={label} hint={hint}>
      <select className="sb-select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">None</option>
        {value && !entities.some(([id]) => id === value) && <option value={value}>{value}</option>}
        {entities.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
    </Field>
  );
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

function VoiceField({ engine, language, value, onChange }: {
  engine: string; language: string; value: string; onChange: (v: string) => void;
}) {
  const [voices, setVoices] = useState<{ voice_id: string; name?: string }[]>([]);
  useEffect(() => {
    if (!engine) {
      setVoices([]);
      return;
    }
    let cancelled = false;
    callWS<{ voices: { voice_id: string; name?: string }[] | null }>({
      type: "tts/engine/voices",
      engine_id: engine,
      language: language.trim() || "en_US",
    }).then(
      (result) => { if (!cancelled) setVoices(result.voices ?? []); },
      () => { if (!cancelled) setVoices([]); },
    );
    return () => { cancelled = true; };
  }, [engine, language]);
  const presets = [
    { voice_id: "en_US-lessac-high", name: "Piper Lessac high" },
    { voice_id: "3", name: "Kokoro af_heart" },
  ];
  const seen = new Set<string>();
  const options = [...presets, ...voices].filter((voice) => {
    if (!voice.voice_id || seen.has(voice.voice_id)) return false;
    seen.add(voice.voice_id);
    return true;
  });
  return (
    <Field label="Voice" hint="Blank uses the engine’s default. Piper Lessac is en_US-lessac-high. Kokoro af_heart on sherpa is 3.">
      <input className="sb-input" list="sb-announce-voices" value={value} placeholder="Engine default"
        onChange={(e) => onChange(e.target.value)} />
      <datalist id="sb-announce-voices">
        {options.map((voice) => <option key={voice.voice_id} value={voice.voice_id}>{voice.name ?? voice.voice_id}</option>)}
      </datalist>
    </Field>
  );
}

function PronunciationEditor({ value, defaults, onChange, lexiconPath, onLexiconPath, testing, dirty, onSpeak }: {
  value: Record<string, string>;
  defaults: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
  lexiconPath: string;
  onLexiconPath: (v: string) => void;
  testing: boolean;
  dirty: boolean;
  onSpeak: (line: string) => void;
}) {
  const rows = Object.entries(value);
  const [addWord, setAddWord] = useState("");
  const [addSays, setAddSays] = useState("");
  const [sample, setSample] = useState("shkia");
  const commit = (next: [string, string][]) => {
    const map: Record<string, string> = {};
    for (const [word, says] of next) {
      if (word.trim()) map[word] = says;
    }
    onChange(map);
  };
  const spoken = applyPronunciation(sample, value);
  return (
    <details className="sb-advanced">
      <summary>Pronunciation</summary>
      <div className="sb-stack">
        <p className="sb-hint">
          Whole words, before the voice speaks. shkia is one word, “shkee-ah”, not “S-H KIA”. Piper and Kokoro both read these spellings. Months, parasha names, the daf, zmanim, and holidays are already in the built-in list. A row here overrides one of those words. Removing a row falls back to the built-in spelling. The preview below uses these rows; speaking also applies the built-in list and the file.
        </p>
        {rows.map(([word, says], index) => (
          <div className="sb-pron-row" key={index}>
            <input className="sb-input" aria-label={`Word ${index + 1}`} value={word}
              onChange={(e) => commit(rows.map((row, i) => i === index ? [e.target.value, says] : row))} />
            <span className="sb-pron-says">says</span>
            <input className="sb-input" aria-label={`Sounds like ${word || index + 1}`} value={says}
              onChange={(e) => commit(rows.map((row, i) => i === index ? [word, e.target.value] : row))} />
            <button className="sb-btn sb-btn-sm" type="button" aria-label={`Remove ${word || "row"}`}
              onClick={() => commit(rows.filter((_, i) => i !== index))}>×</button>
          </div>
        ))}
        <div className="sb-pron-row">
          <input className="sb-input" aria-label="New word" placeholder="Word" value={addWord}
            onChange={(e) => setAddWord(e.target.value)} />
          <span className="sb-pron-says">says</span>
          <input className="sb-input" aria-label="New respelling" placeholder="shkee-ah" value={addSays}
            onChange={(e) => setAddSays(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (!addWord.trim() || !addSays.trim()) return;
                commit([...rows, [addWord.trim(), addSays.trim()]]);
                setAddWord("");
                setAddSays("");
              }
            }} />
          <button className="sb-btn sb-btn-sm" type="button" onClick={() => {
            if (!addWord.trim() || !addSays.trim()) return;
            commit([...rows, [addWord.trim(), addSays.trim()]]);
            setAddWord("");
            setAddSays("");
          }}>Add</button>
        </div>
        {Object.keys(defaults).length > 0 && (
          <button className="sb-btn sb-btn-sm" type="button" onClick={() => onChange({ ...defaults })}>
            Reset to defaults
          </button>
        )}
        <Field label="Pronunciation file" hint="Optional YAML of extra words. Example: /config/tts_lexicon.yaml. Entries in the file override this list and the built-in words. Leave blank to skip the file. Set a word to itself to say it as written.">
          <input className="sb-input" value={lexiconPath} placeholder="/config/tts_lexicon.yaml"
            onChange={(e) => onLexiconPath(e.target.value)} />
        </Field>
        <Field label="Try a word or line" hint={sample.trim() ? `Will say “${spoken}”.` : "Type a word from the list, or a whole sentence."}>
          <div className="sb-row">
            <input className="sb-input" value={sample} aria-label="Line to preview"
              onChange={(e) => setSample(e.target.value)} />
            <button className="sb-btn" type="button" disabled={testing || dirty || !sample.trim()}
              onClick={() => onSpeak(sample.trim())}>
              {testing ? "Speaking…" : "Speak this"}
            </button>
          </div>
        </Field>
        {dirty && <p className="sb-hint">Save first. Speak this uses the saved map, speakers, and voice.</p>}
      </div>
    </details>
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
