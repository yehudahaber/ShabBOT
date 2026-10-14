import { useState } from "react";
import { useActivity } from "../api";
import { Loading, Segmented } from "../components/ui";
import { dateTime } from "../format";
import { friendlyName } from "../hass";

const KIND: Record<string, { label: string; cls: string }> = {
  command: { label: "Scheduled", cls: "sb-badge-accent" },
  revert: { label: "Reverted", cls: "sb-badge-warn" },
  dry_run: { label: "Dry run", cls: "" },
  override_start: { label: "Override", cls: "sb-badge-candle" },
  override_end: { label: "Resumed", cls: "sb-badge-ok" },
  storm: { label: "Gave up", cls: "sb-badge-danger" },
  error: { label: "Error", cls: "sb-badge-danger" },
  settings: { label: "Settings", cls: "" },
  announce: { label: "Spoken", cls: "sb-badge-candle" },
};

type Filter = "all" | "changes" | "overrides" | "problems";
const FILTERS: Record<Filter, (k: string) => boolean> = {
  all: () => true,
  changes: (k) => ["command", "revert", "dry_run"].includes(k),
  overrides: (k) => k.startsWith("override"),
  problems: (k) => ["error", "storm"].includes(k),
};

export function ActivityPage() {
  const { data } = useActivity();
  const [filter, setFilter] = useState<Filter>("all");
  if (!data) return <Loading />;
  const rows = data.filter((e) => FILTERS[filter](e.kind));
  return (
    <div className="sb-card sb-card-pad sb-stack">
      <div className="sb-row">
        <h3 className="sb-section-title" style={{ margin: 0 }}>Activity</h3>
        <span className="sb-spacer" />
        <Segmented value={filter} onChange={setFilter} options={[
          { value: "all", label: "All" }, { value: "changes", label: "Device changes" },
          { value: "overrides", label: "Overrides" }, { value: "problems", label: "Problems" },
        ]} />
      </div>
      <div className="sb-list">
        {rows.map((e, i) => {
          const k = KIND[e.kind] ?? { label: e.kind, cls: "" };
          return (
            <div key={`${e.ts}-${i}`} className="sb-list-item">
              <span className="sb-activity-kind"><span className={`sb-badge ${k.cls}`}>{k.label}</span></span>
              <div className="sb-grow">
                <div>{e.entity_id && <strong>{friendlyName(e.entity_id)} </strong>}{e.message}</div>
              </div>
              <span className="sb-hint sb-tnum" style={{ whiteSpace: "nowrap" }}>{dateTime(e.ts)}</span>
            </div>
          );
        })}
        {rows.length === 0 && <div className="sb-empty">Nothing here yet.</div>}
      </div>
    </div>
  );
}
