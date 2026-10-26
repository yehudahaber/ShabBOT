import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { callWS, friendlyName, shallowEqual, useHassSelector } from "../hass";
import { errorMessage, invalidateAll, usePlan, useStatus } from "../api";
import { Field, Icon } from "../components/ui";
import { addDays, atTime, describeExpr, isoDate, localInput } from "../format";
import type { SimCommand, SimStep } from "../types";

type Verdict = "pass" | "fail" | "skipped";
interface StepResult {
  verdict: Verdict;
  devices: Record<number, Verdict>; // per command
}
type Phase = "setup" | "review" | "before" | "after" | "detail" | "results";

const VERDICT_LABEL: Record<Verdict, string> = { pass: "Passed", fail: "Failed", skipped: "Skipped" };
const VERDICT_BADGE: Record<Verdict, string> = { pass: "sb-badge-ok", fail: "sb-badge-danger", skipped: "sb-badge-muted" };
const allDevices = (step: SimStep, v: Verdict): StepResult =>
  ({ verdict: v, devices: Object.fromEntries(step.commands.map((_, i) => [i, v])) });
const VerdictBadge = ({ v }: { v?: Verdict }) =>
  v ? <span className={`sb-badge ${VERDICT_BADGE[v]}`}>{VERDICT_LABEL[v]}</span> : null;

const opposite = (state: "on" | "off") => (state === "on" ? "off" : "on");
const stateText = (c: Pick<SimCommand, "state" | "attrs">) =>
  [c.state.toUpperCase(), c.attrs.brightness != null && `${c.attrs.brightness}%`, c.attrs.temperature != null && `${c.attrs.temperature}°`]
    .filter(Boolean).join(" ");
/** Where a time came from, e.g. "Candle lighting − 20 min"; null for plain clock times. */
const origin = (c: SimCommand) => {
  const what = describeExpr(c.expr);
  return what;
};
/** The origin shared by every change in a step, if there is one. */
const sharedOrigin = (step: SimStep) => {
  const labels = new Set(step.commands.map(origin));
  return labels.size === 1 ? [...labels][0] : null;
};
const stepTitle = (step: SimStep) => {
  const o = sharedOrigin(step);
  return `${atTime(step.at)}${o ? ` (${o})` : ""}`;
};

/** Test mode: step through every scheduled device change in a time range on the real devices. */
export function SimulatePage() {
  const status = useStatus();
  const today = new Date();
  const plan = usePlan(isoDate(today), isoDate(addDays(today, 30)));
  const nextBlock = plan.data?.blocks.find((b) => new Date(b.end) > today);

  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [steps, setSteps] = useState<SimStep[] | null>(null);
  const [phase, setPhase] = useState<Phase>("setup");
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState<StepResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = phase !== "setup" && phase !== "results";
  const runningRef = useRef(false);
  runningRef.current = running;

  // Default range: the next Shabbat/Yom Tov, an hour either side.
  useEffect(() => {
    if (start || !nextBlock) return;
    setStart(localInput(new Date(+new Date(nextBlock.start) - 3600_000)));
    setEnd(localInput(new Date(+new Date(nextBlock.end) + 3600_000)));
  }, [nextBlock, start]);

  // Preview the steps whenever the range changes.
  useEffect(() => {
    if (phase !== "setup" || !start || !end) return;
    let cancelled = false;
    setError("");
    callWS<SimStep[]>({ type: "shabbot/simulate/steps", start, end })
      .then((s) => !cancelled && setSteps(s), (e) => !cancelled && (setSteps(null), setError(errorMessage(e))));
    return () => {
      cancelled = true;
    };
  }, [start, end, phase]);

  // Leaving the tab ends test mode (the server also ends it after 30 idle minutes).
  useEffect(() => () => {
    if (runningRef.current) callWS({ type: "shabbot/simulate/stop" }).finally(invalidateAll);
  }, []);

  const act = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const apply = (commands: { entity_id: string; state: string; attrs?: object; reason?: string }[]) =>
    callWS<void>({ type: "shabbot/simulate/apply", commands });

  const begin = () => act(async () => {
    await callWS({ type: "shabbot/simulate/start" });
    invalidateAll();
    setResults([]);
    setIndex(0);
    setPhase("before");
  });
  const finish = () => act(async () => {
    await callWS({ type: "shabbot/simulate/stop" });
    invalidateAll();
    setPhase("results");
  });
  /** Open event i: review it if it already has a result, otherwise get ready to test it. */
  const goTo = (i: number, rs = results) => {
    if (!steps || i >= steps.length) return finish();
    setIndex(i);
    setPhase(rs[i] ? "review" : "before");
  };
  const record = (r: StepResult) => {
    const next = [...results];
    next[index] = r;
    setResults(next);
    goTo(index + 1, next);
  };
  const retest = () => {
    const next = [...results];
    delete next[index];
    setResults(next);
    setPhase("before");
  };

  const step = steps?.[index];
  const earlier = results[index];

  if (phase === "results" && steps) {
    return <Results steps={steps} results={results} onAgain={() => setPhase("setup")} />;
  }

  if (running && step && steps) {
    return (
      <div className="sb-stack sb-sim">
        <div className="sb-row">
          <button className="sb-btn sb-btn-sm" disabled={busy || index === 0} onClick={() => goTo(index - 1)}
            title="Go back to the previous event (its results are kept unless you re-test it)">
            <Icon name="left" size={16} /> Back
          </button>
          <span className="sb-hint">Event {index + 1} of {steps.length}</span>
          <span className="sb-spacer" />
          <button className="sb-btn sb-btn-danger" disabled={busy} onClick={finish}>Cancel test</button>
        </div>
        <div className="sb-sim-progress"><i style={{ width: `${(results.filter(Boolean).length / steps.length) * 100}%` }} /></div>

        {phase === "review" && earlier && (
          <div className="sb-card sb-card-pad sb-stack">
            <h3 className="sb-section-title" style={{ margin: 0 }}>{stepTitle(step)}: tested earlier — {VERDICT_LABEL[earlier.verdict]}</h3>
            <CommandList step={step} render={(_, i) => <VerdictBadge v={earlier.devices[i]} />} />
            <p className="sb-hint">Skip keeps these results. Re-test clears them and runs this event again.</p>
            <div className="sb-row sb-wrap">
              <span className="sb-spacer" />
              <button className="sb-btn" disabled={busy} onClick={() => goTo(index + 1)}>Skip</button>
              <button className="sb-btn sb-btn-primary" disabled={busy} onClick={retest}>Re-test</button>
            </div>
          </div>
        )}

        {phase === "before" && (
          <div className="sb-card sb-card-pad sb-stack">
            <h3 className="sb-section-title" style={{ margin: 0 }}>Simulating {stepTitle(step)} events:</h3>
            <CommandList step={step} render={(c) => (
              <button className="sb-btn sb-btn-sm" disabled={busy}
                onClick={() => act(() => apply([{ entity_id: c.entity_id, state: opposite(c.state), reason: "set up before test" }]))}
                title="Put this device in the opposite state first, so you can see the test change it">
                Set to {opposite(c.state).toUpperCase()}
              </button>
            )} />
            <p className="sb-hint">Optionally set the devices to the opposite state first, then press Begin test to send these changes.</p>
            <div className="sb-row sb-wrap">
              <button className="sb-btn" disabled={busy} onClick={() => act(() => apply(
                step.commands.map((c) => ({ entity_id: c.entity_id, state: opposite(c.state), reason: "set up before test" }))))}>
                Set all to opposite
              </button>
              <span className="sb-spacer" />
              <button className="sb-btn" disabled={busy} onClick={() => record(allDevices(step, "skipped"))}>Skip</button>
              <button className="sb-btn sb-btn-primary" disabled={busy} onClick={() => act(async () => {
                await apply(step.commands.map((c) => ({
                  entity_id: c.entity_id, state: c.state, attrs: c.attrs, reason: `${c.routine_name} (test of ${atTime(step.at)})`,
                })));
                setPhase("after");
              })}>Begin test</button>
            </div>
          </div>
        )}

        {phase === "after" && (
          <div className="sb-card sb-card-pad sb-stack">
            <h3 className="sb-section-title" style={{ margin: 0 }}>{stepTitle(step)}: did all of these happen correctly?</h3>
            <CommandList step={step} />
            <div className="sb-row sb-wrap">
              <span className="sb-spacer" />
              <button className="sb-btn sb-btn-fail" onClick={() => setPhase("detail")}>Fail</button>
              <button className="sb-btn sb-btn-pass" onClick={() => record(allDevices(step, "pass"))}>Pass</button>
            </div>
          </div>
        )}

        {phase === "detail" && (
          <DeviceVerdicts step={step} onDone={(devices) => record({
            verdict: Object.values(devices).includes("fail") ? "fail" : "pass", devices,
          })} />
        )}
        {error && <div className="sb-error">{error}</div>}
      </div>
    );
  }

  const changes = steps?.reduce((n, s) => n + s.commands.length, 0) ?? 0;
  const blocked = status.data?.issur_melacha ? `Test mode can't run during ${status.data.block?.title ?? "Shabbat/Yom Tov"}.` : "";
  return (
    <div className="sb-stack sb-sim">
      <div className="sb-card sb-card-pad sb-stack">
        <div>
          <h3 className="sb-section-title" style={{ margin: 0 }}>Test the schedule on your devices</h3>
          <p className="sb-hint">Pick a time range. ShabBOT walks through every scheduled change in it, one moment at a time: it shows what's about to change, sends it when you press Begin test, and asks whether it worked. While the test runs, protection and the real schedule are paused; when it ends, devices go back to what the schedule wants (or how they were).</p>
        </div>
        <div className="sb-grid-2">
          <Field label="From"><input className="sb-input" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Until"><input className="sb-input" type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        </div>
        {nextBlock && <p className="sb-hint">Next: {nextBlock.title}, {atTime(nextBlock.start)} → {atTime(nextBlock.end)}.</p>}
        {steps && (
          <p className="sb-hint">{steps.length} {steps.length === 1 ? "moment" : "moments"} with {changes} device {changes === 1 ? "change" : "changes"}.</p>
        )}
        {error && <div className="sb-error">{error}</div>}
        {blocked && <div className="sb-banner">{blocked}</div>}
        {status.data?.simulation && (
          <div className="sb-banner">
            A test from earlier is still running, so protection is paused (it ends by itself after 30 idle minutes).
            <span className="sb-spacer" />
            <button className="sb-btn sb-btn-sm" disabled={busy} onClick={() => act(async () => {
              await callWS({ type: "shabbot/simulate/stop" });
              invalidateAll();
            })}>End it now</button>
          </div>
        )}
        <div className="sb-row">
          <span className="sb-spacer" />
          <button className="sb-btn sb-btn-primary" disabled={busy || !!blocked || !steps?.length} onClick={begin}>
            <Icon name="right" size={16} /> Start test
          </button>
        </div>
      </div>
      {steps && steps.length > 0 && (
        <div className="sb-card sb-card-pad sb-stack">
          <h3 className="sb-section-title" style={{ margin: 0 }}>What will be tested</h3>
          {steps.map((s) => (
            <div key={s.at} className="sb-sim-preview">
              <strong>{stepTitle(s)}</strong>
              <span className="sb-hint">
                {s.commands.map((c) => `${friendlyName(c.entity_id)}: ${stateText(c)}`).join(" · ")}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** The devices in a step with their target and live state; `render` adds a control per row. */
function CommandList({ step, render }: { step: SimStep; render?: (c: SimCommand, i: number) => ReactNode }) {
  const ids = step.commands.map((c) => c.entity_id);
  const live = useHassSelector((h) => Object.fromEntries(ids.map((e) => [e, h.states[e]?.state ?? "missing"])), shallowEqual);
  const shared = sharedOrigin(step);
  return (
    <div className="sb-list">
      {step.commands.map((c, i) => (
        <div key={`${c.entity_id}-${i}`} className="sb-list-item sb-sim-row">
          <div className="sb-grow">
            <div><strong>{friendlyName(c.entity_id)}</strong>: {stateText(c)}</div>
            <div className="sb-hint">
              {c.routine_name}{!shared && origin(c) ? ` · ${origin(c)}` : ""}
            </div>
          </div>
          <span className={`sb-badge ${live[c.entity_id] === c.state ? "sb-badge-ok" : ""}`} title="Current state">
            now {live[c.entity_id]}
          </span>
          {render?.(c, i)}
        </div>
      ))}
    </div>
  );
}

function DeviceVerdicts({ step, onDone }: { step: SimStep; onDone: (d: Record<number, Verdict>) => void }) {
  const [devices, setDevices] = useState<Record<number, Verdict>>({});
  const done = step.commands.every((_, i) => devices[i]);
  return (
    <div className="sb-card sb-card-pad sb-stack">
      <h3 className="sb-section-title" style={{ margin: 0 }}>{stepTitle(step)} events:</h3>
      <div className="sb-list">
        {step.commands.map((c, i) => (
          <div key={`${c.entity_id}-${i}`} className="sb-list-item sb-sim-row">
            <span className="sb-grow">{friendlyName(c.entity_id)} turn {stateText(c)}?</span>
            {(["pass", "fail"] as const).map((v) => (
              <button key={v} className={`sb-btn sb-btn-sm sb-btn-${v}`} aria-pressed={devices[i] === v}
                onClick={() => setDevices((d) => ({ ...d, [i]: v }))}>{v === "pass" ? "Pass" : "Fail"}</button>
            ))}
          </div>
        ))}
      </div>
      <div className="sb-row">
        <span className="sb-spacer" />
        <button className="sb-btn sb-btn-primary" disabled={!done} onClick={() => onDone(devices)}>Next event</button>
      </div>
    </div>
  );
}

function Results({ steps, results, onAgain }: { steps: SimStep[]; results: StepResult[]; onAgain: () => void }) {
  const counts = { pass: 0, fail: 0, skipped: 0 };
  results.forEach((r) => r && counts[r.verdict]++);
  const done = steps.map((s, i) => ({ s, r: results[i] })).filter(({ r }) => r);
  const untested = steps.length - done.length;
  const text = useMemo(() => [
    `ShabBOT test: ${counts.pass} passed, ${counts.fail} failed, ${counts.skipped} skipped${untested ? `, ${untested} not tested` : ""}`,
    ...done.flatMap(({ s, r }) => [
      "",
      `${stepTitle(s)}: ${r.verdict.toUpperCase()}`,
      ...s.commands.map((c, i) => `  ${friendlyName(c.entity_id)} turn ${stateText(c)}: ${(r.devices[i] ?? r.verdict).toUpperCase()}`
        + ` (${c.routine_name}${origin(c) ? `, ${origin(c)}` : ""})`),
    ]),
  ].join("\n"), [done, counts.pass, counts.fail, counts.skipped, untested]);

  return (
    <div className="sb-stack sb-sim">
      <div className="sb-card sb-card-pad sb-stack">
        <h3 className="sb-section-title" style={{ margin: 0 }}>
          Test summary{untested > 0 ? ` — ended early, ${done.length} of ${steps.length} events done` : ""}
        </h3>
        <div className="sb-row sb-wrap">
          <span className="sb-badge sb-badge-ok">{counts.pass} passed</span>
          <span className={`sb-badge ${counts.fail ? "sb-badge-danger" : ""}`}>{counts.fail} failed</span>
          <span className="sb-badge">{counts.skipped} skipped</span>
          {untested > 0 && <span className="sb-badge sb-badge-warn">{untested} not tested</span>}
        </div>
        {done.length === 0 && <p className="sb-hint">No events were tested.</p>}
        {done.map(({ s, r }) => (
          <div key={s.at} className="sb-sim-summary">
            <div className="sb-row">
              <strong className="sb-grow">{stepTitle(s)}</strong>
              <VerdictBadge v={r.verdict} />
            </div>
            {s.commands.map((c, i) => (
              <div key={i} className={`sb-row ${r.devices[i] === "fail" ? "sb-sim-fail" : "sb-sim-device"}`}>
                <span className="sb-grow">
                  {friendlyName(c.entity_id)} turn {stateText(c)} <span className="sb-hint">· {c.routine_name}
                    {origin(c) ? ` · ${origin(c)}` : ""}</span>
                </span>
                <VerdictBadge v={r.devices[i] ?? r.verdict} />
              </div>
            ))}
          </div>
        ))}
        {untested > 0 && done.length > 0 && (
          <p className="sb-hint">{untested} more {untested === 1 ? "event" : "events"} not tested.</p>
        )}
        <div className="sb-row">
          <button className="sb-btn" onClick={() => navigator.clipboard?.writeText(text)}>Copy results</button>
          <span className="sb-spacer" />
          <button className="sb-btn sb-btn-primary" onClick={onAgain}>New test</button>
        </div>
      </div>
    </div>
  );
}
