import { useState, useRef } from "react";
import { useDraft } from "../useDraft";
import { callWS, friendlyName, shallowEqual, useHassSelector } from "../hass";
import { errorMessage, invalidateAll, useConfig } from "../api";
import { EntityMultiPicker } from "../components/inputs";
import { Check, Field, Loading, SaveBar } from "../components/ui";
import type { AnnounceTemplates, Settings } from "../types";

export function SettingsPage() {
  const { data } = useConfig();
  const [draft, setDraft, dirty, reset] = useDraft<Settings>(data?.config.settings);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const notifiers = useHassSelector((h) => Object.keys(h.services.notify ?? {}).sort(), shallowEqual);

  if (!data || !draft) return <Loading />;
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setDraft({ ...draft, [k]: v });
  const num = (k: keyof Settings) => (e: React.ChangeEvent<HTMLInputElement>) => set(k, (e.target.value === "" ? null : Number(e.target.value)) as never);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      setDraft(await callWS<Settings>({ type: "shabbot/settings/save", settings: draft }));
      invalidateAll();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const exportConfig = async () => {
    const out = await callWS<unknown>({ type: "shabbot/export" });
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `shabbot-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const importConfig = async (file: File, replace: boolean) => {
    setNotice("");
    try {
      await callWS({ type: "shabbot/import", data: JSON.parse(await file.text()), replace });
      invalidateAll();
      setNotice("Imported. Check device names: entity ids from another home may differ.");
    } catch (e) {
      setNotice(`Import failed: ${errorMessage(e)}`);
    }
  };
  const loc = data.meta.location;

  return (
    <div className="sb-stack">
      <div className="sb-card sb-card-pad sb-stack">
        <h3 className="sb-section-title">Zmanim & minhagim</h3>
        <div className="sb-grid-2">
          <Field label="Candle lighting (minutes before sunset)">
            <input className="sb-input" type="number" min={0} max={60} value={draft.candle_lighting_min} onChange={num("candle_lighting_min")} />
          </Field>
          <Field label="Havdalah">
            <select className="sb-select" value={draft.havdalah_mode} onChange={(e) => set("havdalah_mode", e.target.value as Settings["havdalah_mode"])}>
              <option value="degrees">Sun angle below horizon</option>
              <option value="minutes">Fixed minutes after sunset</option>
            </select>
          </Field>
          {draft.havdalah_mode === "degrees" ? (
            <Field label="Degrees below horizon" hint="8.5° is the common default; 7.083° is earlier.">
              <input className="sb-input" type="number" step={0.001} value={draft.havdalah_degrees} onChange={num("havdalah_degrees")} />
            </Field>
          ) : (
            <Field label="Minutes after sunset" hint="e.g. 42, 50 or 72">
              <input className="sb-input" type="number" value={draft.havdalah_minutes} onChange={num("havdalah_minutes")} />
            </Field>
          )}
        </div>
        <div className="sb-row" style={{ gap: 20 }}>
          <Check checked={draft.israel} onChange={(v) => set("israel", v)}>Israel (one-day Yom Tov)</Check>
          <Check checked={draft.use_elevation} onChange={(v) => set("use_elevation", v)}>Use elevation for sunrise/sunset</Check>
        </div>
        <div className="sb-grid-2">
          <Field label="Latitude" hint={`Blank = Home Assistant's (${loc.latitude.toFixed(4)})`}>
            <input className="sb-input" type="number" step={0.0001} value={draft.latitude ?? ""} onChange={num("latitude")} />
          </Field>
          <Field label="Longitude" hint={`Blank = Home Assistant's (${loc.longitude.toFixed(4)}) · ${loc.time_zone}`}>
            <input className="sb-input" type="number" step={0.0001} value={draft.longitude ?? ""} onChange={num("longitude")} />
          </Field>
        </div>
      </div>

      <div className="sb-card sb-card-pad sb-stack">
        <div>
          <h3 className="sb-section-title">Early Shabbat (summer)</h3>
          <p className="sb-hint">
            Take Shabbat early at a fixed time on summer Fridays. Candle lighting, the start of device protection, and
            every routine time written as <code>candle_lighting</code> move with it. Applies to a plain Shabbat only (not
            when it is also Yom Tov), and never earlier than plag hamincha.
          </p>
        </div>
        <Check checked={draft.early_shabbat} onChange={(v) => set("early_shabbat", v)}>Start Shabbat early in the summer</Check>
        {draft.early_shabbat && (
          <div className="sb-grid-2">
            <Field label="Candle lighting at">
              <input className="sb-input" type="time" value={draft.early_shabbat_time}
                onChange={(e) => set("early_shabbat_time", e.target.value)} />
            </Field>
            <Field label="Only when the normal candle lighting is after" hint="So it switches on and off with the seasons.">
              <input className="sb-input" type="time" value={draft.early_shabbat_after}
                onChange={(e) => set("early_shabbat_after", e.target.value)} />
            </Field>
          </div>
        )}
      </div>

      <div className="sb-card sb-card-pad sb-stack">
        <h3 className="sb-section-title">Behavior</h3>
        <Check checked={draft.dry_run} onChange={(v) => set("dry_run", v)}>
          Dry run: log what ShabBOT would do, but don't touch any devices
        </Check>
        <Check checked={draft.protection} onChange={(v) => set("protection", v)}>Device protection</Check>
        <div className="sb-grid-2">
          <Field label="Wait before reverting (seconds)" hint="Gives override gestures time to register.">
            <input className="sb-input" type="number" min={0} max={60} value={draft.grace_seconds} onChange={num("grace_seconds")} />
          </Field>
          <Field label="Give up after this many reverts…">
            <input className="sb-input" type="number" min={1} value={draft.storm_max_reverts} onChange={num("storm_max_reverts")} />
          </Field>
          <Field label="…within (minutes)">
            <input className="sb-input" type="number" min={1} value={draft.storm_window_min} onChange={num("storm_window_min")} />
          </Field>
          <Field label="Notify" hint="Sends a notification on overrides and when ShabBOT gives up on a device.">
            <select className="sb-select" value={draft.notify_service} onChange={(e) => set("notify_service", e.target.value)}>
              <option value="">No notifications</option>
              {notifiers.map((n) => <option key={n} value={`notify.${n}`}>notify.{n}</option>)}
            </select>
          </Field>
        </div>
        {draft.notify_service && (
          <Check checked={draft.notify_overrides} onChange={(v) => set("notify_overrides", v)}>Also notify when an override starts</Check>
        )}
      </div>

      <AnnouncementsCard draft={draft} set={set} dirty={dirty} dryRun={draft.dry_run} onNotice={setNotice} />

      <SaveBar dirty={dirty} saving={saving} error={error} onSave={save} onReset={reset} />

      <div className="sb-card sb-card-pad sb-stack">
        <h3 className="sb-section-title">Copy between homes</h3>
        <p className="sb-hint">Export routines, rules, modes and device settings, then import them into ShabBOT in another home.</p>
        <div className="sb-row">
          <button className="sb-btn" onClick={exportConfig}>Export…</button>
          <input ref={fileRef} type="file" accept="application/json" hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importConfig(f, confirm("Replace everything here with the file?\n\nOK = replace, Cancel = merge"));
              e.target.value = "";
            }} />
          <button className="sb-btn" onClick={() => fileRef.current?.click()}>Import…</button>
          {notice && <span className="sb-hint">{notice}</span>}
        </div>
      </div>
      <p className="sb-hint">ShabBOT {data.meta.version}</p>
    </div>
  );
}

const TEMPLATES: { key: keyof AnnounceTemplates; label: string; hint: string }[] = [
  { key: "candle", label: "Before candle lighting", hint: "Erev Shabbat and erev Yom Tov, and a Yom Tov that runs into Shabbat. Blank skips it." },
  { key: "shkia", label: "Until shkia", hint: "Only marks that fall after candle lighting. Blank skips them." },
  { key: "shkia_final", label: "Final shkia warning", hint: "Default is one minute before shkia: “Shkia in one minute. Stop all melacha.”" },
  { key: "motzei", label: "Motzaei (melacha permitted)", hint: "Spoken at havdalah. {minutes} is your havdalah offset. Not spoken when issur melacha continues." },
  { key: "yt_candle", label: "Second-night Yom Tov countdown", hint: "Candles lit after tzeit from an existing flame. Same minute marks as candle lighting." },
  { key: "yt_candle_now", label: "Second-night Yom Tov, at lighting time", hint: "Spoken when it is time to light. Blank skips it." },
];

function MarksInput({ value, onChange }: { value: number[]; onChange: (v: number[]) => void }) {
  const [text, setText] = useState<string | null>(null);
  return (
    <input className="sb-input" value={text ?? value.join(", ")}
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
        if (parts.every((p) => /^\d+$/.test(p))) onChange(parts.map(Number));
      }}
      onBlur={() => setText(null)} />
  );
}

function AnnouncementsCard({ draft, set, dirty, dryRun, onNotice }: {
  draft: Settings;
  set: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  dirty: boolean;
  dryRun: boolean;
  onNotice: (message: string) => void;
}) {
  const ttsEngines = useHassSelector(
    (h) => Object.keys(h.states).filter((id) => id.startsWith("tts.")).sort(),
    shallowEqual,
  );
  const [testing, setTesting] = useState(false);
  const templates = draft.announce_templates;
  const setTemplate = (key: keyof AnnounceTemplates, value: string) =>
    set("announce_templates", { ...templates, [key]: value });
  const testSpeak = async () => {
    setTesting(true);
    try {
      const result = await callWS<{ dry_run: boolean }>({ type: "shabbot/announce/test" });
      onNotice(result.dry_run ? "Dry run: the test was logged on the Activity tab, not spoken." : "Test announcement sent.");
    } catch (e) {
      onNotice(errorMessage(e));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="sb-card sb-card-pad sb-stack">
      <div>
        <h3 className="sb-section-title">Announcements</h3>
        <p className="sb-hint">
          Spoken on the selected players: a countdown to candle lighting, a countdown to shkia after candles are lit,
          and one sentence at havdalah when melacha is actually permitted. A second Yom Tov night (candles from an
          existing flame, after tzeit) counts down to that lighting time instead, and does not say “muttar”.
          Dry run logs the sentence instead of speaking. Placeholders: {"{minutes}"}, {"{unit}"}, {"{minutes_words}"}, {"{occasion}"}, {"{title}"}.
        </p>
      </div>
      <Check checked={draft.announce_enabled} onChange={(v) => set("announce_enabled", v)}>
        Speak Shabbat and Yom Tov announcements
      </Check>
      <div className="sb-stack">
          <Field label="Players" hint="Every selected speaker says the same sentence. Remove a chip to drop it.">
            <EntityMultiPicker value={draft.announce_players} onChange={(v) => set("announce_players", v)} domains={["media_player"]} />
          </Field>
          <div className="sb-grid-2">
            <Field label="TTS engine" hint="A tts entity. The voice below is passed as that engine's voice option.">
              <select className="sb-select" value={draft.announce_tts_entity} onChange={(e) => set("announce_tts_entity", e.target.value)}>
                <option value="">Choose an engine…</option>
                {draft.announce_tts_entity && !ttsEngines.includes(draft.announce_tts_entity) && (
                  <option value={draft.announce_tts_entity}>{draft.announce_tts_entity}</option>
                )}
                {ttsEngines.map((id) => <option key={id} value={id}>{friendlyName(id)}</option>)}
              </select>
            </Field>
            <Field label="Voice" hint="Blank uses the engine's default.">
              <input className="sb-input" value={draft.announce_voice} onChange={(e) => set("announce_voice", e.target.value)} />
            </Field>
            <Field label="Language" hint="Blank uses the engine's default. Example: en">
              <input className="sb-input" value={draft.announce_language} onChange={(e) => set("announce_language", e.target.value)} />
            </Field>
            <Field label="Lead (seconds)" hint="Speak this early so TTS and speaker buffering land on time. Sonos is often 5–10. 0 is exact.">
              <input className="sb-input" type="number" min={0} max={300} value={draft.announce_lead_seconds}
                onChange={(e) => set("announce_lead_seconds", Number(e.target.value) || 0)} />
            </Field>
            <Field label="Announcement volume (%)" hint="Blank leaves each player's volume alone. Restored afterwards (Sonos snapshot/restore).">
              <input className="sb-input" type="number" min={0} max={100} value={draft.announce_volume ?? ""}
                onChange={(e) => set("announce_volume", e.target.value === "" ? null : Number(e.target.value))} />
            </Field>
            <Field label="Final shkia warning (minutes before sunset)" hint="Default 1. “Shkia in one minute. Stop all melacha.”">
              <input className="sb-input" type="number" min={0} max={180} value={draft.announce_shkia_final_min}
                onChange={(e) => set("announce_shkia_final_min", Number(e.target.value))} />
            </Field>
          </div>
          {draft.announce_players.length > 0 && (
            <div className="sb-grid-2">
              {draft.announce_players.map((id) => (
                <Field key={id} label={`${friendlyName(id)} lead (seconds)`} hint="Blank uses the global lead.">
                  <input className="sb-input" type="number" min={0} max={300} value={draft.announce_player_leads[id] ?? ""}
                    onChange={(e) => {
                      const next = { ...draft.announce_player_leads };
                      if (e.target.value === "") delete next[id];
                      else next[id] = Number(e.target.value);
                      set("announce_player_leads", next);
                    }} />
                </Field>
              ))}
            </div>
          )}
          <div className="sb-grid-2">
            <Field label="Candle-lighting reminders (minutes before)" hint="Default 60, 30, 15, 5.">
              <MarksInput value={draft.announce_candle_marks} onChange={(v) => set("announce_candle_marks", v)} />
            </Field>
            <Field label="Shkia reminders (minutes before sunset)" hint="Skipped when they would fall before candle lighting.">
              <MarksInput value={draft.announce_shkia_marks} onChange={(v) => set("announce_shkia_marks", v)} />
            </Field>
          </div>
          {TEMPLATES.map((row) => (
            <Field key={row.key} label={row.label} hint={row.hint}>
              <textarea className="sb-input" value={templates[row.key]} onChange={(e) => setTemplate(row.key, e.target.value)} />
            </Field>
          ))}
          <div className="sb-row">
            <button className="sb-btn" type="button" disabled={testing || dirty} onClick={testSpeak}>
              {testing ? "Speaking…" : "Speak a test"}
            </button>
            <span className="sb-hint">
              {dirty ? "Save first." : dryRun ? "Dry run is on, so the test is logged rather than spoken." : "Uses the saved players, engine, and volume. The test speaks even if the schedule is off."}
            </span>
          </div>
      </div>
    </div>
  );
}
