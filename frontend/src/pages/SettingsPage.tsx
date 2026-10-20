import { useState, useRef } from "react";
import { useDraft } from "../useDraft";
import { callWS, shallowEqual, useHassSelector } from "../hass";
import { errorMessage, invalidateAll, useConfig } from "../api";
import { Check, Field, Loading, SaveBar } from "../components/ui";
import { AnnouncementsCard } from "./AnnouncementsCard";
import type { Settings } from "../types";

const YOM_TOV_END_PRESETS = [42, 50, 60, 72];

function YomTovEndField({ value, onChange }: { value: number; onChange: (minutes: number) => void }) {
  const [custom, setCustom] = useState(!YOM_TOV_END_PRESETS.includes(value));
  const selected = custom || !YOM_TOV_END_PRESETS.includes(value) ? "custom" : String(value);
  return (
    <div className="sb-field">
      <span>Yom Tov end</span>
      <select className="sb-select" value={selected} aria-label="Yom Tov end"
        onChange={(e) => {
          if (e.target.value === "custom") setCustom(true);
          else {
            setCustom(false);
            onChange(Number(e.target.value));
          }
        }}>
        {YOM_TOV_END_PRESETS.map((n) => <option key={n} value={n}>{n} minutes</option>)}
        <option value="custom">Custom</option>
      </select>
      {selected === "custom" && (
        <input className="sb-input" type="number" min={20} max={90} value={value} aria-label="Custom Yom Tov end minutes"
          onChange={(e) => onChange(e.target.value === "" ? value : Math.min(90, Math.max(20, Math.trunc(Number(e.target.value)) || value)))} />
      )}
      <small className="sb-hint">Minutes after shkia when a Yom Tov day that is not Shabbat ends. 20–90.</small>
    </div>
  );
}

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
          <Field label="Shabbat havdalah">
            <select className="sb-select" value={draft.havdalah_mode} onChange={(e) => set("havdalah_mode", e.target.value as Settings["havdalah_mode"])}>
              <option value="degrees">Sun angle below horizon</option>
              <option value="minutes">Fixed minutes after sunset</option>
            </select>
          </Field>
          {draft.havdalah_mode === "degrees" ? (
            <Field label="Degrees below horizon" hint="8.5° is the common default; 7.083° is earlier. Shabbat only.">
              <input className="sb-input" type="number" step={0.001} value={draft.havdalah_degrees} onChange={num("havdalah_degrees")} />
            </Field>
          ) : (
            <Field label="Shabbat minutes after shkia" hint="Including Yom Tov that falls on Shabbat.">
              <input className="sb-input" type="number" min={20} max={90} value={draft.havdalah_minutes} onChange={num("havdalah_minutes")} />
            </Field>
          )}
          <YomTovEndField value={draft.yom_tov_end_minutes ?? 42} onChange={(v) => set("yom_tov_end_minutes", v)} />
        </div>
        <div className="sb-stack">
          <div className="sb-row" style={{ gap: 20 }}>
            <Check checked={draft.israel} onChange={(v) => set("israel", v)}>Israel (Eretz Yisrael)</Check>
            <Check checked={draft.use_elevation} onChange={(v) => set("use_elevation", v)}>Use elevation for sunrise/sunset</Check>
          </div>
          <p className="sb-hint">
            One-day Yom Tov and the Israel Torah reading (פרשת השבוע). Unchecked is Chutz La'aretz.
            On setup this starts from Home Assistant: checked if the country is Israel or the map pin is in Israel.
            After that, this box is what ShabBOT uses.
          </p>
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

      <AnnouncementsCard draft={draft} set={set} dirty={dirty} dryRun={draft.dry_run} onNotice={setNotice}
        defaults={data.meta.default_settings} />

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

