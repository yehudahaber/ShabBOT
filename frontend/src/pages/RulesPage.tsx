import { useMemo, useState } from "react";
import { useDraft } from "../useDraft";
import { DragHandle, tempId, useReorder } from "../components/reorder";
import { callWS } from "../hass";
import { errorMessage, invalidateAll, useConfig, usePlan } from "../api";
import { Icon, Loading, SaveBar } from "../components/ui";
import { RoutineSelect } from "../components/inputs";
import { addDays, DAY_TYPE_LABEL, dateShort, HOLIDAY_LABEL, isoDate, PART_LABEL, WEEKDAYS } from "../format";
import { routineList, type Part, type Rule } from "../types";

const PARTS: Part[] = ["night", "day", "block"];

export function RulesPage() {
  const { data } = useConfig();
  const [rules, setRules, dirty, reset] = useDraft<Rule[]>(data?.config.rules);
  const reorder = useReorder(rules ?? [], setRules);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const today = new Date();
  const preview = usePlan(isoDate(today), isoDate(addDays(today, 45)));

  const routines = useMemo(() => (data ? routineList(data.config) : []), [data]);
  if (!data || !rules) return <Loading />;

  const set = (i: number, patch: Partial<Rule>) => setRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const setMatch = (i: number, key: keyof Rule["match"], value: string) =>
    set(i, { match: { ...rules[i].match, [key]: value === "" ? null : key === "day_in_block" || key === "weekday" ? Number(value) : value } });
  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const saved = await callWS<Rule[]>({ type: "shabbot/rules/save", rules });
      setRules(saved);
      invalidateAll();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const upcoming = (preview.data?.instances ?? []).filter((i) => i.part !== "block").slice(0, 12);

  return (
    <div className="sb-stack">
      <div className="sb-card sb-card-pad sb-stack sb-editor">
        <div>
          <h3 className="sb-section-title">Default rules</h3>
          <p className="sb-hint">
            For each meal, ShabBOT uses the most specific matching rule (the one with the most conditions). Ties go to the
            rule higher in the list; drag the ⋮⋮ handle to reorder. A one-time choice on the calendar, or an active Summer/Vacation mode, takes priority over these.
          </p>
        </div>
        <div className="sb-scroll-x">
          <div className="sb-rule sb-action-head">
            <span /><span>Name</span><span>Meal</span><span>Kind of day</span><span>Holiday</span><span>Day #</span><span>Weekday</span><span>Use routine</span><span />
          </div>
          {rules.map((r, i) => (
            <div key={r.id || i} className="sb-rule" {...reorder.row(i)} style={{ opacity: r.enabled ? 1 : 0.5 }}>
              <div className="sb-row" style={{ gap: 4, flexWrap: "nowrap" }}>
                <DragHandle {...reorder.handle(i)} />
                <input type="checkbox" checked={r.enabled} title="Enabled" onChange={(e) => set(i, { enabled: e.target.checked })} />
              </div>
              <div><span className="sb-cell-label">Name</span><input className="sb-input" value={r.name} onChange={(e) => set(i, { name: e.target.value })} /></div>
              <div><span className="sb-cell-label">Meal</span><select className="sb-select" value={r.part} onChange={(e) => set(i, { part: e.target.value as Part, routine_id: null })}>
                {PARTS.map((p) => <option key={p} value={p}>{PART_LABEL[p]}</option>)}
              </select></div>
              <div><span className="sb-cell-label">Kind of day</span><select className="sb-select" value={r.match.day_type ?? ""} onChange={(e) => setMatch(i, "day_type", e.target.value)}>
                <option value="">Any</option>
                {data.meta.day_types.map((d) => <option key={d} value={d}>{DAY_TYPE_LABEL[d] ?? d}</option>)}
              </select></div>
              <div><span className="sb-cell-label">Holiday</span><select className="sb-select" value={r.match.holiday_group ?? ""} onChange={(e) => setMatch(i, "holiday_group", e.target.value)}>
                <option value="">Any</option>
                {data.meta.holiday_groups.map((g) => <option key={g} value={g}>{HOLIDAY_LABEL[g] ?? g}</option>)}
              </select></div>
              <div><span className="sb-cell-label">Day #</span><select className="sb-select" value={r.match.day_in_block ?? ""} title="Which day of a 2- or 3-day Shabbat/Yom Tov"
                onChange={(e) => setMatch(i, "day_in_block", e.target.value)}>
                <option value="">Any</option><option value="1">1st</option><option value="2">2nd</option><option value="3">3rd</option>
              </select></div>
              <div><span className="sb-cell-label">Weekday</span><select className="sb-select" value={r.match.weekday ?? ""} onChange={(e) => setMatch(i, "weekday", e.target.value)}>
                <option value="">Any</option>
                {WEEKDAYS.map((w, n) => <option key={w} value={n}>{w}</option>)}
              </select></div>
              <div><span className="sb-cell-label">Use routine</span><RoutineSelect value={r.routine_id} onChange={(v) => set(i, { routine_id: v })} routines={routines} part={r.part}
                specials={[{ value: null, label: "Nothing" }]} /></div>
              <div className="sb-row" style={{ gap: 0, flexWrap: "nowrap" }}>
                <button className="sb-btn sb-btn-ghost sb-icon-btn sb-btn-danger" onClick={() => setRules(rules.filter((_, j) => j !== i))} aria-label="Delete"><Icon name="trash" size={16} /></button>
              </div>
            </div>
          ))}
        </div>
        <div className="sb-row">
          <button className="sb-btn" onClick={() => setRules([...rules, { id: tempId(), name: "New rule", part: "night", enabled: true, match: {}, routine_id: null }])}>
            <Icon name="plus" size={16} /> Add rule
          </button>
        </div>
        <SaveBar dirty={dirty} saving={saving} error={error} onSave={save} onReset={reset} />
      </div>

      <div className="sb-card sb-card-pad sb-stack">
        <div>
          <h3 className="sb-section-title">Coming up</h3>
          <p className="sb-hint">What the saved rules choose for the next few weeks. Change a single date from the Calendar tab.</p>
        </div>
        <div className="sb-scroll-x">
          <table className="sb-table">
            <thead><tr><th>Date</th><th>Meal</th><th>Routine</th><th>Why</th></tr></thead>
            <tbody>
              {upcoming.map((i) => (
                <tr key={i.key}>
                  <td className="sb-tnum">{dateShort(i.start)}</td>
                  <td>{i.target_title}</td>
                  <td>{i.routine_name ?? <span className="sb-hint">{i.source === "skipped" ? "Skipped" : "Nothing"}</span>}</td>
                  <td className="sb-hint">{i.source === "rule" ? `Rule: ${i.source_name}` : i.source === "mode" ? `Mode: ${i.source_name}` : i.source === "assignment" ? "Chosen for this date" : i.source === "skipped" ? "Skipped this time" : "No rule"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
