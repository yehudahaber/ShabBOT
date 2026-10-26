import { useState } from "react";
import { invalidateAll, useStatus } from "./api";
import { callWS } from "./hass";
import { Icon } from "./components/ui";
import { ICON_SVG } from "./brand";
import { dayTime, time } from "./format";
import { CalendarPage } from "./pages/CalendarPage";
import { RoutinesPage } from "./pages/RoutinesPage";
import { RulesPage } from "./pages/RulesPage";
import { ModesPage } from "./pages/ModesPage";
import { DevicesPage } from "./pages/DevicesPage";
import { ActivityPage } from "./pages/ActivityPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SimulatePage } from "./pages/SimulatePage";

const TABS = [
  { id: "calendar", label: "Calendar", el: CalendarPage },
  { id: "routines", label: "Routines", el: RoutinesPage },
  { id: "rules", label: "Default rules", el: RulesPage },
  { id: "modes", label: "Summer & vacation", el: ModesPage },
  { id: "devices", label: "Devices", el: DevicesPage },
  { id: "activity", label: "Activity", el: ActivityPage },
  { id: "test", label: "Test", el: SimulatePage },
  { id: "settings", label: "Settings", el: SettingsPage },
] as const;
type TabId = (typeof TABS)[number]["id"];

function initialTab(): TabId {
  const h = window.location.hash.slice(1);
  return (TABS.find((t) => t.id === h)?.id ?? "calendar") as TabId;
}

export function App({ narrow }: { narrow: boolean }) {
  const [tab, setTab] = useState<TabId>(initialTab);
  const status = useStatus();
  const s = status.data;
  const Page = TABS.find((t) => t.id === tab)!.el;
  const go = (id: TabId) => {
    setTab(id);
    history.replaceState(null, "", `#${id}`);
  };
  const overrides = s?.entities.filter((e) => e.override).length ?? 0;
  const outOfSync = s?.entities.filter((e) => e.protected && !e.in_sync).length ?? 0;

  return (
    <div className={`sb-app ${narrow ? "sb-narrow" : ""}`}>
      <header className="sb-header">
        <div className="sb-header-row">
          {narrow && (
            <button className="sb-btn sb-btn-ghost sb-icon-btn" aria-label="Open Home Assistant menu"
              onClick={(e) => e.currentTarget.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }))}>
              <Icon name="menu" />
            </button>
          )}
          <div className="sb-title">
            <span className="sb-logo" aria-hidden="true" dangerouslySetInnerHTML={{ __html: ICON_SVG }} />
            <span>Shab<span className="sb-title-bot">BOT</span></span>
          </div>
          <div className="sb-status">
            {s?.issur_melacha && s.block ? (
              <span className="sb-badge sb-badge-candle">{s.block.title} until {time(s.block.end)}</span>
            ) : null}
            {s?.simulation && <span className="sb-badge sb-badge-warn">Test mode · protection paused</span>}
            {s && <span className={`sb-badge ${s.protection ? "sb-badge-ok" : ""}`}><Icon name="shield" size={12} /> Protection {s.protection ? "on" : "off"}</span>}
            {overrides > 0 && <span className="sb-badge sb-badge-warn">{overrides} overridden</span>}
            {outOfSync > 0 && <span className="sb-badge sb-badge-danger">{outOfSync} out of place</span>}
            {s?.next_boundary && <span className="sb-badge" title="Next scheduled device change">Next: {dayTime(s.next_boundary)}</span>}
          </div>
        </div>
        <nav className="sb-tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" className="sb-tab" aria-selected={tab === t.id} onClick={() => go(t.id)}>{t.label}</button>
          ))}
        </nav>
      </header>
      <main className="sb-main sb-stack">
        {s?.dry_run && (
          <div className="sb-banner">
            Dry run is on: ShabBOT logs what it would do but doesn't change any devices.
            <span className="sb-spacer" />
            <button className="sb-btn sb-btn-sm" onClick={async () => {
              if (!confirm("Turn off dry run? ShabBOT will start controlling devices on schedule.")) return;
              await callWS({ type: "shabbot/settings/save", settings: { dry_run: false } });
              invalidateAll();
            }}>Go live</button>
          </div>
        )}
        <Page />
      </main>
    </div>
  );
}
