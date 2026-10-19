import { useEffect, useMemo, useRef, useState } from "react";
import { callWS } from "../hass";
import { errorMessage, invalidateAll, queryClient, useConfig } from "../api";
import { Field, Icon, Loading, SaveBar } from "../components/ui";
import { EntityMultiPicker, ExprInput } from "../components/inputs";
import { DragHandle, tempId, useReorder } from "../components/reorder";
import { dateShort, PART_LABEL, time } from "../format";
import { entitiesOf, type Action, type Config, type Meta, type Part, routineList, type Routine, type RowCheck } from "../types";

const PARTS: Part[] = ["night", "day", "block"];
const PART_HELP: Record<Part, string> = {
  night: "Runs on the evening of a Shabbat/Yom Tov day (e.g. Friday night dinner). Times like sunset refer to that evening.",
  day: "Runs on the day itself (e.g. Shabbat lunch).",
  block: "Applies to every Shabbat/Yom Tov, whatever the meal plans; meal routines override it while they run. Each row runs once (times count from the first evening, so 7:00am means the next morning and 3:00pm means that Friday afternoon), every night (each evening → next morning), or every day (times on each day, so 7:00am–10:00am runs every morning of a 2- or 3-day Yom Tov).",
};
const COLORS = ["#2563eb", "#7c3aed", "#16a34a", "#0d9488", "#ea580c", "#db2777", "#64748b", "#94a3b8"];

const blankAction = (part: Part): Action => ({
  id: tempId(),
  entity_ids: [],
  state: part === "block" ? "off" : "on",
  start: part === "block" ? "candle_lighting" : part === "night" ? "sunset" : "11:30am",
  end: part === "block" ? "havdalah" : part === "night" ? "midnight" : "3pm",
  end_state: null,
});

/** Rows copied from another routine: fresh ids, and only baseline rows keep their repeat. */
const copyRows = (actions: Action[], part: Part): Action[] =>
  actions.map(({ repeat, ...a }) => ({ ...structuredClone(a), id: tempId(), ...(part === "block" && repeat ? { repeat } : {}) }));

/** Editor copy of a routine: every row lists its devices in `entity_ids`. */
const normalize = (r: Routine): Routine => ({
  ...structuredClone(r),
  actions: r.actions.map(({ entity_id: _legacy, ...a }) => ({ ...structuredClone(a), entity_ids: entitiesOf({ ...a, entity_id: _legacy }) })),
});

export function RoutinesPage() {
  const { data } = useConfig();
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<Routine | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const routines = useMemo(() => (data ? routineList(data.config) : []), [data]);
  const checks = useRowChecks(draft);
  const reorder = useReorder(draft?.actions ?? [], (actions) => setDraft((d) => d && { ...d, actions }));
  // Open the first routine on load only; later a null selection means a new, unsaved routine.
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || !routines.length) return;
    opened.current = true;
    if (selected === null) setSelected(routines[0].id);
  }, [routines, selected]);
  // Load the draft only when the selection changes, so background refreshes never wipe unsaved edits.
  useEffect(() => {
    const routine = selected ? data?.config.routines[selected] : undefined;
    if (routine) setDraft(normalize(routine));
    setError("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, !!data]);

  if (!data) return <Loading />;
  const original = selected ? data.config.routines[selected] : undefined;
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(original && normalize(original));
  const missingDevice = !!draft && draft.actions.some((a) => entitiesOf(a).length === 0);
  const usage = (id: string) => {
    const rules = data.config.rules.filter((r) => r.routine_id === id).map((r) => r.name);
    const modes = data.config.modes.filter((m) => [m.night, m.day, m.block].includes(id)).map((m) => m.name);
    return [...rules.map((n) => `rule “${n}”`), ...modes.map((n) => `mode “${n}”`)];
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setError("");
    try {
      const saved = await callWS<Routine>({
        type: "shabbot/routine/save",
        routine: { ...draft, id: draft.id || undefined, actions: draft.actions.map((a) => ({ ...a, id: a.id || undefined })) },
      });
      invalidateAll();
      setDraft(normalize(saved));
      setSelected(saved.id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const create = (part: Part) => {
    setSelected(null);
    setDraft({ id: "", name: "New routine", part, color: COLORS[routines.length % COLORS.length], description: "", actions: [] });
  };

  const duplicate = () => {
    if (!draft) return;
    setSelected(null);
    setDraft({ ...structuredClone(draft), id: "", name: `${draft.name} (copy)`, actions: copyRows(draft.actions, draft.part) });
  };

  const copyFrom = (id: string) => {
    const source = data.config.routines[id];
    if (!draft || !source) return;
    setDraft({ ...draft, actions: [...draft.actions, ...copyRows(normalize(source).actions, draft.part)] });
  };

  const remove = async () => {
    if (!draft?.id) return;
    const used = usage(draft.id);
    if (!confirm(`Delete “${draft.name}”?${used.length ? `\n\nIt is used by ${used.join(", ")}; those will fall back to nothing.` : ""}`)) return;
    await callWS({ type: "shabbot/routine/delete", routine_id: draft.id });
    invalidateAll();
    setSelected(null);
    setDraft(null);
  };

  const setAction = (i: number, patch: Partial<Action>) =>
    setDraft((d) => d && { ...d, actions: d.actions.map((a, j) => (j === i ? { ...a, ...patch } : a)) });

  return (
    <div className="sb-split">
      <div className="sb-stack">
        {PARTS.map((part) => (
          <div key={part} className="sb-stack" style={{ gap: 6 }}>
            <div className="sb-row">
              <h3 className="sb-section-title" style={{ margin: 0 }}>{PART_LABEL[part]} routines</h3>
              <span className="sb-spacer" />
              <button className="sb-btn sb-btn-sm sb-btn-ghost" onClick={() => create(part)}><Icon name="plus" size={14} /> New</button>
            </div>
            <RoutineList items={routines.filter((r) => r.part === part)} selected={selected} onSelect={setSelected}
              onReorder={(ids) => reorderRoutines(routines.map((r) => r.id), ids)} />
          </div>
        ))}
      </div>

      {draft ? (
        <div className="sb-card sb-card-pad sb-stack sb-editor">
          <div className="sb-grid-2">
            <Field label="Name"><input className="sb-input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
            <Field label="Runs for">
              <select className="sb-select" value={draft.part} disabled={!!draft.id}
                onChange={(e) => setDraft({ ...draft, part: e.target.value as Part })}>
                {PARTS.map((p) => <option key={p} value={p}>{PART_LABEL[p]}</option>)}
              </select>
            </Field>
          </div>
          <p className="sb-hint">{PART_HELP[draft.part]}</p>
          <div className="sb-row">
            <span className="sb-hint">Color</span>
            {COLORS.map((c) => (
              <button key={c} aria-label={c} className="sb-dot"
                style={{ background: c, width: 22, height: 22, border: draft.color === c ? "2px solid var(--text)" : "2px solid transparent", cursor: "pointer" }}
                onClick={() => setDraft({ ...draft, color: c })} />
            ))}
          </div>
          {draft.id && usage(draft.id).length > 0 && <p className="sb-hint">Used by {usage(draft.id).join(", ")}.</p>}

          <div>
            <h3 className="sb-section-title">Devices</h3>
            <p className="sb-hint">Each row keeps one or more devices on (or off) between two times; drag the ⋮⋮ handle to reorder rows. Times can be zmanim with offsets (sunset+18m), clock times (11:45pm), or min()/max() of both.</p>
          </div>
          <div className="sb-scroll-x">
            <div className="sb-action sb-action-head">
              <span /><span>Devices</span><span>State</span><span>From</span><span>Until</span><span>Afterwards</span><span />
            </div>
            {draft.actions.map((a, i) => (
              <div key={a.id || i} className="sb-action" {...reorder.row(i)}>
                <DragHandle {...reorder.handle(i)} />
                <div><span className="sb-cell-label">Devices</span>
                  <EntityMultiPicker value={entitiesOf(a)} onChange={(v) => setAction(i, { entity_ids: v })} /></div>
                <div className="sb-stack" style={{ gap: 4 }}>
                  <span className="sb-cell-label">State</span>
                  <select className="sb-select" value={a.state} onChange={(e) => setAction(i, { state: e.target.value as "on" | "off" })}>
                    <option value="on">On</option><option value="off">Off</option>
                  </select>
                  {a.state === "on" && entitiesOf(a).some((e) => e.startsWith("light.")) && (
                    <input className="sb-input" type="number" min={1} max={100} placeholder="Bright %"
                      value={a.brightness ?? ""} onChange={(e) => setAction(i, { brightness: e.target.value ? Number(e.target.value) : null })} />
                  )}
                  {a.state === "on" && entitiesOf(a).some((e) => e.startsWith("climate.")) && (
                    <input className="sb-input" type="number" step={0.5} placeholder="Temp"
                      value={a.temperature ?? ""} onChange={(e) => setAction(i, { temperature: e.target.value ? Number(e.target.value) : null })} />
                  )}
                </div>
                <div><span className="sb-cell-label">From</span><ExprInput value={a.start} onChange={(v) => setAction(i, { start: v })} part={contextPart(draft.part, a)} resolved={checks[i]?.first?.start} /></div>
                <div><span className="sb-cell-label">Until</span><ExprInput value={a.end} onChange={(v) => setAction(i, { end: v })} part={contextPart(draft.part, a)} resolved={checks[i]?.first?.end} /></div>
                <div><span className="sb-cell-label">Afterwards</span><select className="sb-select" value={a.end_state ?? ""} title="What to do when the window ends (if no other routine covers it)"
                  onChange={(e) => setAction(i, { end_state: (e.target.value || null) as Action["end_state"] })}>
                  <option value="">{a.state === "on" ? "Turn off" : "Leave as is"}</option>
                  <option value="off">Turn off</option>
                  <option value="on">Turn on</option>
                  <option value="leave">Leave as is</option>
                </select></div>
                <button className="sb-btn sb-btn-ghost sb-icon-btn sb-btn-danger" aria-label="Remove device"
                  onClick={() => setDraft({ ...draft, actions: draft.actions.filter((_, j) => j !== i) })}>
                  <Icon name="trash" size={16} />
                </button>
                {draft.part === "block" && (
                  <label className="sb-row-msg sb-row" style={{ gap: 8 }}>
                    <span className="sb-hint">Repeat</span>
                    <select className="sb-select" style={{ width: "auto", minWidth: 260 }} value={a.repeat ?? "once"}
                      onChange={(e) => setAction(i, { repeat: e.target.value as Action["repeat"] })}>
                      <option value="once">Once for the whole Shabbat/Yom Tov</option>
                      <option value="night">Every night (evening → next morning)</option>
                      <option value="day">Every day (that day's morning → evening)</option>
                    </select>
                  </label>
                )}
                <RowMessage check={checks[i]} part={draft.part} />
              </div>
            ))}
          </div>
          <div className="sb-row">
            <button className="sb-btn" onClick={() => setDraft({ ...draft, actions: [...draft.actions, blankAction(draft.part)] })}>
              <Icon name="plus" size={16} /> Add device
            </button>
            <select className="sb-select" style={{ width: "auto" }} value="" aria-label="Copy rows from another routine"
              title="Add a copy of another routine's rows to this one" onChange={(e) => copyFrom(e.target.value)}>
              <option value="">Copy rows from…</option>
              {PARTS.map((part) => {
                const sources = routines.filter((r) => r.part === part && r.id !== draft.id && r.actions.length);
                return sources.length > 0 && (
                  <optgroup key={part} label={`${PART_LABEL[part]} routines`}>
                    {sources.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.actions.length})</option>)}
                  </optgroup>
                );
              })}
            </select>
            <span className="sb-spacer" />
            {draft.id && <button className="sb-btn" onClick={duplicate}><Icon name="copy" size={16} /> Duplicate routine</button>}
            {draft.id && <button className="sb-btn sb-btn-danger" onClick={remove}>Delete routine</button>}
          </div>
          <SaveBar dirty={dirty || !draft.id} blocked={checks.some((c) => c?.always_invalid) || missingDevice} saving={saving}
            error={error || (missingDevice ? "Choose at least one device for each row."
              : checks.some((c) => c?.always_invalid) ? "Fix the rows whose times can't work." : "")} onSave={save}
            onReset={original ? () => setDraft(normalize(original)) : undefined} />
        </div>
      ) : (
        <div className="sb-card sb-empty">Choose a routine, or create one.</div>
      )}
    </div>
  );
}

/** Puts one part's routines in a new order (keeping the slots the other parts use) and saves it. */
function reorderRoutines(all: string[], partIds: string[]) {
  const moved = new Set(partIds);
  const queue = [...partIds];
  const order = all.map((id) => (moved.has(id) ? queue.shift()! : id));
  // Show the new order right away; the save confirms it.
  queryClient.setQueryData<{ config: Config; meta: Meta }>(["config"], (old) => old && {
    ...old,
    config: { ...old.config, routine_order: order },
  });
  callWS({ type: "shabbot/routines/reorder", routine_ids: order }).finally(invalidateAll);
}

/** One part's routines, reorderable with the ⋮⋮ handle; the new order is saved when the drag ends. */
function RoutineList({ items, selected, onSelect, onReorder }: {
  items: Routine[]; selected: string | null; onSelect: (id: string) => void; onReorder: (ids: string[]) => void;
}) {
  const [moving, setMoving] = useState<Routine[] | null>(null);
  const shown = moving ?? items;
  const reorder = useReorder(shown, setMoving);
  useEffect(() => {
    if (!moving || reorder.dragging) return;
    const ids = moving.map((r) => r.id);
    if (ids.join() !== items.map((r) => r.id).join()) onReorder(ids);
    setMoving(null);
  }, [moving, reorder.dragging]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="sb-list">
      {shown.map((r, i) => (
        <div key={r.id} className="sb-list-item sb-list-item-grip" {...reorder.row(i)}
          style={selected === r.id ? { background: "var(--accent-soft)" } : undefined}>
          {shown.length > 1 && <DragHandle {...reorder.handle(i)} />}
          <button className="sb-list-select" onClick={() => onSelect(r.id)}>
            <i className="sb-dot" style={{ background: r.color ?? "var(--border)" }} />
            <span className="sb-grow sb-ellipsis">{r.name}</span>
            <span className="sb-hint">{r.actions.length}</span>
          </button>
        </div>
      ))}
      {shown.length === 0 && <div className="sb-list-item sb-hint">None yet</div>}
    </div>
  );
}

/** Checks each row's start/end against every matching meal in the next year (zmanim move with the seasons). */
function useRowChecks(draft: Routine | null): (RowCheck | undefined)[] {
  const [checks, setChecks] = useState<RowCheck[]>([]);
  useEffect(() => setChecks([]), [draft?.id]); // don't show another routine's results
  const key = draft ? JSON.stringify([draft.part, draft.actions.map((a) => [a.start, a.end, a.repeat])]) : "";
  useEffect(() => {
    if (!draft) return;
    const actions = draft.actions.map((a) => ({ start: a.start, end: a.end, repeat: a.repeat ?? null }));
    if (actions.some((a) => !a.start.trim() || !a.end.trim())) return;
    let cancelled = false;
    const t = setTimeout(() => {
      callWS<RowCheck[]>({ type: "shabbot/routine/check", part: draft.part, actions })
        .then((r) => !cancelled && setChecks(r), () => !cancelled && setChecks([]));
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return draft ? draft.actions.map((_, i) => checks[i]) : [];
}

const duration = (start: string, end: string) => {
  const mins = Math.round((+new Date(end) - +new Date(start)) / 60000);
  return `${Math.floor(mins / 60)} h${mins % 60 ? ` ${mins % 60} m` : ""}`;
};

/** The context a row's times are read in: a repeated baseline row previews like a night or day meal. */
const contextPart = (part: Part, a: Action): Part =>
  part === "block" && (a.repeat === "night" || a.repeat === "day") ? a.repeat : part;

function RowMessage({ check, part }: { check?: RowCheck; part: Part }) {
  if (!check || check.error || check.total === 0) return null;
  if (check.always_invalid) {
    return (
      <div className="sb-row-msg sb-error">
        These times can't work: the end is never after the start, even counting it as the next day.
      </div>
    );
  }
  const parts: string[] = [];
  const ex = check.next_day_example;
  if (ex) {
    const when = `${dateShort(ex.start)} ${time(ex.start)} → ${dateShort(ex.end)} ${time(ex.end)}, ${duration(ex.start, ex.end)}`;
    parts.push(check.next_day === check.total
      ? `Crosses midnight: ends the next day (${when}).`
      : `On ${check.next_day} of ${check.total} dates this crosses midnight and ends the next day, because the zmanim shift with the seasons (first: ${when}).`);
  }
  const span = (e: { start: string; end: string }) => `${dateShort(e.start)} ${time(e.start)} → ${dateShort(e.end)} ${time(e.end)}`;
  if (part === "block" && check.before_start_example) {
    parts.push(`Starts before Shabbat/Yom Tov begins (${span(check.before_start_example)}).`);
  }
  if (part === "block" && check.after_end_example) {
    parts.push(`Runs past the end of Shabbat/Yom Tov (${span(check.after_end_example)})${
      check.after_end < check.total ? ` on ${check.after_end} of ${check.total} dates` : ""}.`);
  }
  if (check.invalid > 0) {
    parts.push(`Skipped on ${check.invalid} of ${check.total} dates where the times can't work${check.invalid_example ? ` (first: ${check.invalid_example.title})` : ""}.`);
  }
  if (parts.length === 0) return null;
  return <div className="sb-row-msg sb-warn-text">{parts.join(" ")}</div>;
}
