import { useEffect, useId, useMemo, useState } from "react";
import { callWS, CONTROLLABLE, shallowEqual, useHassSelector } from "../hass";
import { ANCHOR_CHIP, ANCHOR_LABEL, dayTime, describeExpr } from "../format";
import type { Part } from "../types";

/** Controllable entities as {entity_id: friendly name}, re-rendering only when that list changes. */
function useEntityOptions(domains: string[]): { options: Record<string, string>; sorted: [string, string][] } {
  const options = useHassSelector(
    (h) =>
      Object.fromEntries(
        Object.values(h.states)
          .filter((s) => domains.includes(s.entity_id.split(".")[0]))
          .map((s) => [s.entity_id, (s.attributes.friendly_name as string) || s.entity_id]),
      ) as Record<string, string>,
    shallowEqual,
  );
  const sorted = useMemo(() => Object.entries(options).sort((a, b) => a[1].localeCompare(b[1])), [options]);
  return { options, sorted };
}

/** Entity picker over controllable entities, with friendly names. */
export function EntityPicker({ value, onChange, domains = CONTROLLABLE, placeholder = "Choose a device…" }: {
  value: string; onChange: (v: string) => void; domains?: string[]; placeholder?: string;
}) {
  const listId = useId();
  const { options, sorted } = useEntityOptions(domains);
  const known = value in options;
  return (
    <div className="sb-stack" style={{ gap: 2 }}>
      <input className={`sb-input ${value && !known ? "sb-invalid" : ""}`} list={listId} value={value}
        placeholder={placeholder} onChange={(e) => onChange(e.target.value.trim())} />
      <datalist id={listId}>
        {sorted.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </datalist>
      <small className="sb-preview">{known ? options[value] : value ? "Not found in Home Assistant" : ""}</small>
    </div>
  );
}

/** Several devices: removable chips, plus a box that adds a device as soon as a known one is chosen. */
export function EntityMultiPicker({ value, onChange, domains = CONTROLLABLE, exclude = [] }: {
  value: string[]; onChange: (v: string[]) => void; domains?: string[]; exclude?: string[];
}) {
  const listId = useId();
  const { options, sorted } = useEntityOptions(domains);
  const [typed, setTyped] = useState("");
  const add = (text: string) => {
    const id = text.trim();
    if (id in options && !value.includes(id) && !exclude.includes(id)) {
      onChange([...value, id]);
      setTyped("");
    } else {
      setTyped(text);
    }
  };
  const unknown = typed.trim() !== "" && !(typed.trim() in options);
  // Two entities with one name (e.g. a switch and its converted light) look identical; tell them apart.
  const shared = new Set<string>();
  const seen = new Set<string>();
  for (const name of Object.values(options)) {
    const key = name.toLowerCase();
    if (seen.has(key)) shared.add(key);
    seen.add(key);
  }
  const label = (id: string) => {
    const name = options[id];
    if (!name) return id;
    return shared.has(name.toLowerCase()) ? `${name} · ${id.split(".")[0]}` : name;
  };
  return (
    <div className="sb-stack" style={{ gap: 4 }}>
      {value.length > 0 && (
        <div className="sb-chips" style={{ marginTop: 0 }}>
          {value.map((id) => (
            <button key={id} type="button" className={`sb-chip sb-chip-device ${id in options ? "" : "sb-invalid"}`}
              title={`${id} (click to remove)`} onClick={() => onChange(value.filter((x) => x !== id))}>
              {label(id)} <span aria-hidden="true">×</span>
            </button>
          ))}
        </div>
      )}
      <input className={`sb-input ${unknown ? "sb-invalid" : ""}`} list={listId} value={typed}
        placeholder={value.length ? "Add another device…" : "Choose a device…"} onChange={(e) => add(e.target.value)} />
      <datalist id={listId}>
        {sorted.filter(([id]) => !value.includes(id) && !exclude.includes(id)).map(([id, name]) => (
          <option key={id} value={id}>{label(id) || name}</option>
        ))}
      </datalist>
      {unknown && <small className="sb-preview">Not found in Home Assistant</small>}
    </div>
  );
}

const QUICK = ["candle_lighting", "sunset", "tzeit", "midnight", "sunrise", "chatzot", "havdalah"];

/** Time expression input with live preview against the next matching Shabbat/Yom Tov. */
export function ExprInput({ value, onChange, part, slotKey, resolved }: {
  value: string; onChange: (v: string) => void; part: Part; slotKey?: string;
  /** Time the whole row resolves to (e.g. an end read as the next morning); overrides the single-field preview. */
  resolved?: string | null;
}) {
  const [preview, setPreview] = useState<{ time?: string; error?: string; title?: string }>({});
  useEffect(() => {
    if (!value.trim()) {
      setPreview({ error: "Required" });
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      callWS<{ time?: string; error?: string; title?: string }>({
        type: "shabbot/preview", expr: value, ...(slotKey ? { key: slotKey } : { part }),
      }).then((r) => !cancelled && setPreview(r), (e) => !cancelled && setPreview({ error: String(e?.message ?? e) }));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [value, part, slotKey]);
  const quick = QUICK;
  const shown = resolved ?? preview.time;
  return (
    <div>
      <input className={`sb-input sb-mono ${preview.error ? "sb-invalid" : ""}`} value={value}
        onChange={(e) => onChange(e.target.value)} placeholder="e.g. sunset+18m or 11:45pm" spellCheck={false} />
      <div className="sb-preview" title={preview.title}>
        {preview.error ? <span className="sb-error">{preview.error}</span>
          : shown ? `${describeExpr(value) ? `${describeExpr(value)} ` : ""}→ ${dayTime(shown)}` : ""}
      </div>
      <details>
        <summary className="sb-hint" style={{ cursor: "pointer", fontSize: 11 }}>Insert time</summary>
        <div className="sb-chips">
          {quick.map((q) => (
            <button key={q} type="button" className="sb-chip" title={`${ANCHOR_LABEL[q]} (${q})`} onClick={() => onChange(q)}>
              {ANCHOR_CHIP[q] ?? q}
            </button>
          ))}
        </div>
      </details>
    </div>
  );
}

/** Routine dropdown for one part; `specials` adds entries like "Use default rules" (null) or "Nothing" ("none"). */
export function RoutineSelect({ value, onChange, routines, part, specials }: {
  value: string | null;
  onChange: (v: string | null) => void;
  routines: { id: string; name: string; part: Part }[];
  part: Part;
  specials: { value: string | null; label: string }[];
}) {
  const enc = (v: string | null) => (v === null ? "__null__" : v);
  return (
    <select className="sb-select" value={enc(value)}
      onChange={(e) => onChange(e.target.value === "__null__" ? null : e.target.value)}>
      {specials.map((s) => <option key={enc(s.value)} value={enc(s.value)}>{s.label}</option>)}
      {routines.filter((r) => r.part === part).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
    </select>
  );
}
