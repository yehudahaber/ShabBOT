import { useCallback, useMemo, useRef, useState } from "react";
import FullCalendar, { type CalendarRef, type EventInput } from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/react/daygrid";
import timeGridPlugin from "@fullcalendar/react/timegrid";
import multiMonthPlugin from "@fullcalendar/react/multimonth";
import interactionPlugin from "@fullcalendar/react/interaction";
import monarchTheme from "@fullcalendar/react/themes/monarch";
import { errorMessage, useConfig, usePlan, useSave, useTimeline } from "../api";
import { Drawer, Icon, Segmented } from "../components/ui";
import { DeviceTimeline } from "../components/DeviceTimeline";
import { RoutineSelect } from "../components/inputs";
import { friendlyName } from "../hass";
import { addDays, ANCHOR_LABEL, dateLong, dateShort, dayTime, isoDate, PART_LABEL, time } from "../format";
import { routineList, type Block, type Config, type Instance, type Interval } from "../types";

type ViewType = "multiMonthYear" | "dayGridMonth" | "timeGridWeek" | "timeGridDay";
const VIEWS: { value: ViewType; label: string }[] = [
  { value: "multiMonthYear", label: "Year" },
  { value: "dayGridMonth", label: "Month" },
  { value: "timeGridWeek", label: "Week" },
  { value: "timeGridDay", label: "Day" },
];
const CANDLE = "#d98a1f";
const VIEW_KEY = "shabbot.calendarView";

type Selection = { kind: "block"; id: string } | { kind: "instance"; key: string } | { kind: "device"; key: string; entity: string };

function savedView(): ViewType {
  try {
    const v = localStorage.getItem(VIEW_KEY) as ViewType | null;
    return v && VIEWS.some((x) => x.value === v) ? v : "dayGridMonth";
  } catch {
    return "dayGridMonth";
  }
}

export function CalendarPage() {
  const ref = useRef<CalendarRef>(null);
  const [view, setView] = useState<ViewType>(savedView);
  const [range, setRange] = useState<{ start: string; end: string; title: string } | null>(null);
  const [sel, setSel] = useState<Selection | null>(null);
  const config = useConfig();
  const plan = usePlan(range?.start ?? "", range?.end ?? "", !!range);

  const changeView = (v: ViewType) => {
    setView(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* per-viewer convenience only */
    }
    ref.current?.getApi().changeView(v);
  };

  const events = useMemo<EventInput[]>(() => {
    if (!plan.data) return [];
    const timeGrid = view.startsWith("timeGrid");
    const out: EventInput[] = [];
    if (view === "multiMonthYear") {
      // Year view cells are too small for event bars: shade the days instead (click a day for details).
      return plan.data.blocks.map((b) => ({
        id: `year-${b.id}`, start: b.days[0], end: isoDate(addDays(new Date(`${b.days[b.days.length - 1]}T00:00`), 1)),
        allDay: true, display: "background", color: CANDLE,
      }));
    }
    for (const b of plan.data.blocks) {
      if (timeGrid) {
        out.push({ id: `bg-${b.id}`, start: b.start, end: b.end, display: "background", color: CANDLE });
      }
      out.push({
        id: `block-${b.id}`,
        title: `${b.normal_start ? "Early " : ""}${b.title} · until ${time(b.end)}`,
        start: b.start,
        end: b.end,
        allDay: timeGrid,
        color: CANDLE,
        contrastColor: "#fff",
        className: "sb-ev sb-ev-block",
        extendedProps: { kind: "block", id: b.id },
      });
    }
    for (const i of plan.data.instances) {
      if (i.part === "block") continue;
      if (!i.routine_id && i.source !== "skipped") continue;
      const defaultName = i.default_routine_id ? config.data?.config.routines[i.default_routine_id]?.name : null;
      out.push({
        id: `inst-${i.key}`,
        title: i.source === "skipped" ? `Skipped: ${defaultName ?? PART_LABEL[i.part]}` : i.routine_name ?? "",
        start: i.start,
        end: i.end,
        color: i.color ?? "#2f5bd3",
        contrastColor: "#fff",
        className: `sb-ev ${i.source === "skipped" ? "sb-ev-skipped" : ""}`,
        extendedProps: { kind: "instance", key: i.key },
      });
    }
    return out;
  }, [plan.data, view, config.data]);

  const onDatesSet = useCallback((info: { start: Date; end: Date; view: { title: string } }) => {
    setRange({ start: isoDate(info.start), end: isoDate(addDays(info.end, -1)), title: info.view.title });
  }, []);

  const api = () => ref.current?.getApi();
  const blocks = plan.data?.blocks ?? [];
  const instances = plan.data?.instances ?? [];

  return (
    <div className="sb-stack">
      <div className="sb-cal-toolbar">
        <button className="sb-btn sb-icon-btn" aria-label="Previous" onClick={() => api()?.prev()}><Icon name="left" /></button>
        <button className="sb-btn sb-icon-btn" aria-label="Next" onClick={() => api()?.next()}><Icon name="right" /></button>
        <button className="sb-btn" onClick={() => api()?.today()}>Today</button>
        <h2 className="sb-cal-title">{range?.title}</h2>
        <span className="sb-spacer" />
        {plan.isFetching && <span className="sb-hint">Updating…</span>}
        <Segmented value={view} options={VIEWS} onChange={changeView} />
      </div>
      {plan.error && <div className="sb-banner">Couldn't load the schedule: {errorMessage(plan.error)}</div>}
      <div className="sb-card sb-cal">
        <FullCalendar
          ref={ref}
          plugins={[monarchTheme, dayGridPlugin, timeGridPlugin, multiMonthPlugin, interactionPlugin]}
          dateClick={(info) => {
            if (view !== "multiMonthYear") return;
            const block = blocks.find((b) => b.days.includes(isoDate(info.date)));
            if (block) setSel({ kind: "block", id: block.id });
          }}
          initialView={view}
          headerToolbar={false}
          height="auto"
          events={events}
          datesSet={onDatesSet}
          eventClick={(info) => {
            const p = info.event.extendedProps as { kind: string; id?: string; key?: string };
            if (p.kind === "block" && p.id) setSel({ kind: "block", id: p.id });
            if (p.kind === "instance" && p.key) setSel({ kind: "instance", key: p.key });
          }}
          dayCellClass={(d) => d.isPast && "sb-past"}
          dayLaneClass={(d) => d.isPast && "sb-past"}
          eventClass={(e) => e.isPast && "sb-ev-past"}
          backgroundEventClass={(e) => e.isPast && "sb-ev-past"}
          nowIndicator
          dayMaxEvents={4}
          scrollTime="16:00:00"
          firstDay={0}
        />
      </div>
      <div className="sb-legend">
        <span><i className="sb-dot" style={{ background: CANDLE }} /> Shabbat / Yom Tov (candle lighting → havdalah)</span>
        <span>{view === "multiMonthYear" ? "Click a shaded day to see that Shabbat/Yom Tov" : "Click an entry to see its routine and devices"}</span>
      </div>
      {config.data && (
        <SelectionDrawer sel={sel} setSel={setSel} blocks={blocks} instances={instances} config={config.data.config} />
      )}
    </div>
  );
}

function SelectionDrawer({ sel, setSel, blocks, instances, config }: {
  sel: Selection | null; setSel: (s: Selection | null) => void; blocks: Block[]; instances: Instance[]; config: Config;
}) {
  const close = () => setSel(null);
  if (!sel) return null;
  if (sel.kind === "block") {
    const block = blocks.find((b) => b.id === sel.id);
    if (!block) return null;
    return (
      <Drawer open onClose={close} title={block.title}
        subtitle={`${dateShort(block.start)} ${time(block.start)} → ${dateShort(block.end)} ${time(block.end)}`}>
        <BlockDetail block={block} instances={instances.filter((i) => i.block_id === block.id)} config={config}
          onOpen={(key) => setSel({ kind: "instance", key })} />
      </Drawer>
    );
  }
  const inst = instances.find((i) => i.key === sel.key);
  if (!inst) return null;
  const block = blocks.find((b) => b.id === inst.block_id);
  const crumbs = [
    { label: block?.title ?? "Shabbat", onClick: () => setSel({ kind: "block", id: inst.block_id }) },
    { label: inst.target_title, onClick: sel.kind === "device" ? () => setSel({ kind: "instance", key: inst.key }) : undefined },
  ];
  if (sel.kind === "device") {
    return (
      <Drawer open onClose={close} title={friendlyName(sel.entity)} subtitle={sel.entity}
        crumbs={[...crumbs, { label: friendlyName(sel.entity) }]}>
        {block && <DeviceDetail entity={sel.entity} block={block} />}
      </Drawer>
    );
  }
  return (
    <Drawer open onClose={close} crumbs={crumbs}
      title={inst.routine_name ?? (inst.source === "skipped" ? "Skipped" : "No routine")}
      subtitle={inst.slot ? `${inst.slot.title} · ${dateLong(inst.slot.day)}` : inst.target_title}>
      <InstanceDetail inst={inst} config={config} onDevice={(entity) => setSel({ kind: "device", key: inst.key, entity })} />
    </Drawer>
  );
}

function sourceBadge(inst: Instance) {
  switch (inst.source) {
    case "assignment": return <span className="sb-badge sb-badge-accent">Chosen for this date</span>;
    case "skipped": return <span className="sb-badge sb-badge-warn">Skipped this time</span>;
    case "mode": return <span className="sb-badge sb-badge-candle">Mode: {inst.source_name}</span>;
    case "rule": return <span className="sb-badge">Default rule: {inst.source_name}</span>;
    default: return <span className="sb-badge">No rule matches</span>;
  }
}

function BlockDetail({ block, instances, config, onOpen }: {
  block: Block; instances: Instance[]; config: Config; onOpen: (key: string) => void;
}) {
  const byKey = Object.fromEntries(instances.map((i) => [i.key, i]));
  const items = [`${block.id}/block`, ...block.slots.map((s) => s.key)];
  return (
    <>
      <dl className="sb-zmanim">
        <div><dt>Candle lighting</dt><dd>{dayTime(block.start)}</dd></div>
        {block.normal_start && <div><dt>Early Shabbat; normally</dt><dd>{time(block.normal_start)}</dd></div>}
        <div><dt>Havdalah</dt><dd>{dayTime(block.end)}</dd></div>
      </dl>
      <div className="sb-list">
        {items.map((key) => {
          const inst = byKey[key];
          if (!inst) return null;
          const defaultName = inst.default_routine_id ? config.routines[inst.default_routine_id]?.name : null;
          return (
            <button key={key} className="sb-list-item" onClick={() => onOpen(key)}>
              <i className="sb-dot" style={{ background: inst.color ?? "var(--border)" }} />
              <div className="sb-grow">
                <div className="sb-ellipsis">{inst.target_title}</div>
                <div className="sb-hint sb-ellipsis">
                  {inst.routine_name ?? (inst.source === "skipped" ? `Skipped (${defaultName ?? "—"})` : "Nothing scheduled")}
                  {inst.routine_id && ` · ${time(inst.start)}–${time(inst.end)}`}
                </div>
              </div>
              {inst.source === "assignment" && <span className="sb-badge sb-badge-accent">Changed</span>}
              {inst.source === "skipped" && <span className="sb-badge sb-badge-warn">Skipped</span>}
              <Icon name="right" size={16} />
            </button>
          );
        })}
      </div>
    </>
  );
}

function InstanceDetail({ inst, config, onDevice }: { inst: Instance; config: Config; onDevice: (e: string) => void }) {
  const save = useSave<{ key: string; routine_id?: string | null; skip?: boolean; disabled_actions?: string[] }>(
    "shabbot/assignment/set");
  const assignment = config.assignments[inst.key] ?? {};
  const disabled = new Set(assignment.disabled_actions ?? []);
  const defaultName = inst.default_routine_id ? config.routines[inst.default_routine_id]?.name : "nothing";
  const routines = routineList(config);
  const choice = assignment.skip ? "__skip__" : assignment.routine_id ?? null;

  const choose = (v: string | null) => {
    if (v === "__skip__") save.mutate({ key: inst.key, skip: true, routine_id: null });
    else save.mutate({ key: inst.key, skip: false, routine_id: v });
  };
  const toggleAction = (id: string, run: boolean) => {
    const next = new Set(disabled);
    if (run) next.delete(id);
    else next.add(id);
    save.mutate({ key: inst.key, disabled_actions: [...next] });
  };

  return (
    <>
      <div className="sb-row">{sourceBadge(inst)}</div>
      <div className="sb-card sb-card-pad sb-stack">
        <strong>For this {inst.part === "block" ? "Shabbat/Yom Tov" : PART_LABEL[inst.part].toLowerCase()} only</strong>
        <RoutineSelect value={choice} onChange={choose} routines={routines} part={inst.part}
          specials={[{ value: null, label: `Default (${defaultName ?? "nothing"})` },
            ...(inst.part === "block" ? [] : [{ value: "__skip__", label: "Skip this meal" }])]} />
        <p className="sb-hint">The general rule stays the same for every other week.</p>
        {save.error && <span className="sb-error">{errorMessage(save.error)}</span>}
      </div>
      {inst.slot && (
        <dl className="sb-zmanim">
          {(inst.part === "night" ? ["candle_lighting", "sunset", "tzeit"] : ["sunrise", "chatzot", "sunset", "slot_end"])
            .filter((k) => inst.slot!.anchors[k]).map((k) => (
            <div key={k}><dt>{k === "slot_end" ? "Day ends" : ANCHOR_LABEL[k]}</dt><dd>{time(inst.slot!.anchors[k])}</dd></div>
          ))}
        </dl>
      )}
      {inst.actions.length > 0 && (
        <>
          <div>
            <h3 className="sb-section-title">Device schedule</h3>
            <p className="sb-hint">Click a device to see its whole Shabbat/Yom Tov.</p>
          </div>
          <DeviceTimeline actions={inst.actions} color={inst.color ?? "#2f5bd3"} anchors={inst.slot?.anchors} onEntityClick={onDevice} />
          <div className="sb-list">
            {inst.actions.map((a) => (
              <div key={`${a.action_id}-${a.entity_id}-${a.occurrence_key ?? ""}`} className="sb-list-item">
                <input type="checkbox" checked={!a.disabled} title="Run this time"
                  onChange={(e) => toggleAction(a.action_id, e.target.checked)} />
                <div className="sb-grow">
                  <div className="sb-ellipsis">
                    {friendlyName(a.entity_id)}
                    {a.occurrence_title && <span className="sb-hint"> · {a.occurrence_title}</span>}
                  </div>
                  {a.error ? <div className="sb-error">{a.error}</div> : (
                    <div className="sb-hint sb-tnum">
                      {a.state === "on" ? "On" : "Off"} {a.occurrence_key ? dayTime(a.start) : time(a.start)} – {a.next_day ? dayTime(a.end) : time(a.end)}
                      {a.attrs.brightness ? ` · ${a.attrs.brightness}%` : ""}
                      {a.end_state !== "leave" ? ` · then ${a.end_state}` : ""}
                    </div>
                  )}
                </div>
                <button className="sb-btn sb-btn-sm" onClick={() => onDevice(a.entity_id)}>Details</button>
              </div>
            ))}
          </div>
        </>
      )}
      {inst.routine_id && inst.actions.length === 0 && (
        <p className="sb-hint">This routine has no devices yet. Add some on the Routines tab.</p>
      )}
    </>
  );
}

function DeviceDetail({ entity, block }: { entity: string; block: Block }) {
  const start = block.days[0];
  const end = block.days[block.days.length - 1];
  const tl = useTimeline(isoDate(addDays(new Date(`${start}T00:00`), -1)), end);
  const intervals: Interval[] = (tl.data?.[entity] ?? []).filter((iv) => iv.end > block.start && iv.start < block.end);
  if (tl.isLoading) return <p className="sb-hint">Loading…</p>;
  if (intervals.length === 0) return <p className="sb-hint">Not scheduled during this Shabbat/Yom Tov.</p>;
  const sorted = [...intervals].sort((a, b) => a.start.localeCompare(b.start));
  return (
    <>
      <p className="sb-hint">Every window for this device, from all routines. Meal routines take priority over the baseline where they overlap.</p>
      <DeviceTimeline
        actions={sorted.map((iv, i) => ({
          action_id: `${iv.action_id}-${i}`, entity_id: `${iv.routine_name}`, state: iv.state, attrs: iv.attrs,
          start: iv.start, end: iv.end, end_state: iv.end_state, disabled: false, error: null, next_day: false, occurrence_key: null, occurrence_title: null,
        }))}
        color="#2f5bd3"
        anchors={{ block_start: block.start, block_end: block.end }}
        range={[block.start, block.end]}
      />
      <div className="sb-list">
        {sorted.map((iv, i) => (
          <div key={i} className="sb-list-item">
            <span className={`sb-badge ${iv.state === "on" ? "sb-badge-ok" : ""}`}>{iv.state === "on" ? "On" : "Off"}</span>
            <div className="sb-grow">
              <div className="sb-tnum">{dayTime(iv.start)} – {dayTime(iv.end)}</div>
              <div className="sb-hint">{iv.routine_name}</div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
