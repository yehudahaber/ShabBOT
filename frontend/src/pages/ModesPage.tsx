import { useMemo, useState } from "react";
import { useDraft } from "../useDraft";
import { callWS } from "../hass";
import { errorMessage, invalidateAll, useConfig } from "../api";
import { Check, Field, Icon, Loading, SaveBar } from "../components/ui";
import { RoutineSelect } from "../components/inputs";
import { isoDate, PART_LABEL } from "../format";
import { routineList, type Mode, type Part } from "../types";

const PARTS: Part[] = ["night", "day", "block"];

export function ModesPage() {
  const { data } = useConfig();
  const [modes, setModes, dirty, reset] = useDraft<Mode[]>(data?.config.modes);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const routines = useMemo(() => (data ? routineList(data.config) : []), [data]);
  if (!data || !modes) return <Loading />;

  const today = isoDate(new Date());
  const set = (i: number, patch: Partial<Mode>) => setModes(modes.map((m, j) => (j === i ? { ...m, ...patch } : m)));
  const add = (name: string) =>
    setModes([...modes, { id: "", name, enabled: true, start: today, end: null, night: "none", day: "none", block: null, protection: true }]);
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      setModes(await callWS<Mode[]>({ type: "shabbot/modes/save", modes }));
      invalidateAll();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };
  const isActive = (m: Mode) => m.enabled && m.start <= today && (!m.end || today <= m.end);

  return (
    <div className="sb-stack">
      <div className="sb-card sb-card-pad">
        <h3 className="sb-section-title">Summer & vacation modes</h3>
        <p className="sb-hint">
          While a mode is active, it replaces the default rules for the meals you set here. Choose “Use default rules”
          to leave that meal alone. A one-time choice on the calendar still wins over a mode.
        </p>
      </div>
      {modes.map((m, i) => (
        <div key={m.id || i} className="sb-card sb-card-pad sb-stack">
          <div className="sb-row">
            <input className="sb-input" style={{ maxWidth: 280, fontWeight: 600 }} value={m.name} onChange={(e) => set(i, { name: e.target.value })} />
            {isActive(m) && <span className="sb-badge sb-badge-candle">Active now</span>}
            <span className="sb-spacer" />
            <Check checked={m.enabled} onChange={(v) => set(i, { enabled: v })}>Enabled</Check>
            <button className="sb-btn sb-btn-ghost sb-icon-btn sb-btn-danger" aria-label="Delete mode"
              onClick={() => setModes(modes.filter((_, j) => j !== i))}><Icon name="trash" size={16} /></button>
          </div>
          <div className="sb-grid-2">
            <Field label="From"><input className="sb-input" type="date" value={m.start} onChange={(e) => set(i, { start: e.target.value })} /></Field>
            <Field label="Until">
              <div className="sb-row" style={{ flexWrap: "nowrap" }}>
                <input className="sb-input" type="date" value={m.end ?? ""} disabled={m.end === null}
                  onChange={(e) => set(i, { end: e.target.value || null })} />
                <Check checked={m.end === null} onChange={(v) => set(i, { end: v ? null : m.start })}>No end date</Check>
              </div>
            </Field>
          </div>
          <div className="sb-grid-2">
            {PARTS.map((p) => (
              <Field key={p} label={PART_LABEL[p]}>
                <RoutineSelect value={m[p]} onChange={(v) => set(i, { [p]: v } as Partial<Mode>)} routines={routines} part={p}
                  specials={[{ value: null, label: "Use default rules" }, { value: "none", label: "Nothing" }]} />
              </Field>
            ))}
          </div>
          <Check checked={m.protection} onChange={(v) => set(i, { protection: v })}>Device protection while this mode is active</Check>
        </div>
      ))}
      <div className="sb-row">
        <button className="sb-btn" onClick={() => add("Summer")}><Icon name="plus" size={16} /> Summer mode</button>
        <button className="sb-btn" onClick={() => add("Vacation")}><Icon name="plus" size={16} /> Vacation mode</button>
      </div>
      <SaveBar dirty={dirty} saving={saving} error={error} onSave={save} onReset={reset} />
    </div>
  );
}
