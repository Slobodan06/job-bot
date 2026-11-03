import { useCallback, useEffect, useRef, useState } from "react";

import { AUTOFILL_ENABLED, WEB_ORIGIN } from "../lib/env";
import type { BgToFrame } from "../lib/frames";
import { bg, ONSITE_BLOCKED } from "../lib/messaging";
import type { ApplicationQuestion, DetectedJob } from "../lib/types";

type Phase = "idle" | "working" | "done" | "error";
type Props = { job: DetectedJob };

const HUMANIZER_URL = "https://cleverhumanizer.ai/";
// After clicking Next, a step that loads in place (no new page) is filled from here;
// a step on a new page is picked up by that page's overlay (see takeContinuation).
const SAME_PAGE_STEP_WAIT_MS = 2500;
// A new step can take a moment to render its form.
const FORM_WAIT_TRIES = 6;
const FORM_WAIT_MS = 1000;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Pages can block the clipboard API (an iframe policy, say).
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

const btn: React.CSSProperties = {
  border: "none",
  borderRadius: 8,
  padding: "8px 12px",
  font: "600 12px/1 system-ui, sans-serif",
  cursor: "pointer",
};

const emptyTotals = () => ({
  filled: 0,
  skipped: 0,
  resume: false,
  keptResume: false,
  frames: 0,
  expected: 0,
  error: "",
  notes: "",
  questions: 0,
  nextLabel: "",
  continuing: false,
});

export function Overlay({ job }: Props) {
  // Collapsed to a round button in the corner until the member opens it.
  const [open, setOpen] = useState(false);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [msg, setMsg] = useState("");
  const [questions, setQuestions] = useState<ApplicationQuestion[]>([]);
  const [copiedKey, setCopiedKey] = useState("");
  const [nextLabel, setNextLabel] = useState("");
  const totals = useRef(emptyTotals());
  const settleTimer = useRef<number | undefined>(undefined);
  const variantRef = useRef<string | undefined>(undefined);
  const checkedContinuation = useRef(false);

  useEffect(() => {
    bg.authGet().then((r) => setAuthed(r.ok && !!r.data.token));
  }, []);

  // Applications are recorded only once the site confirms the submission (see
  // content/submission.ts + background/index.ts), never just for
  // detecting or viewing a posting — the tracker would otherwise fill up with
  // every job you glance at.

  const settle = useCallback(() => {
    window.clearTimeout(settleTimer.current);
    const t = totals.current;
    setNextLabel(t.nextLabel);
    if (t.filled === 0 && !t.resume && t.questions === 0) {
      if (t.nextLabel && !t.error) {
        setPhase("done");
        setMsg("Nothing left to fill on this step.");
        return;
      }
      setPhase("error");
      setMsg(t.error || "No fillable fields found yet — open the application form, then try again.");
      return;
    }
    setPhase("done");
    setMsg(
      `Filled ${t.filled} field${t.filled === 1 ? "" : "s"}${t.resume ? " and attached your tailored resume" : ""}.` +
        (t.keptResume && !t.resume ? " A resume was already uploaded, so JobBot left it as it is." : "") +
        (t.skipped ? ` ${t.skipped} need a manual check.` : "") +
        (t.questions ? ` Copy the ${t.questions === 1 ? "answer" : "answers"} below into the written question${t.questions === 1 ? "" : "s"}.` : "") +
        // A later step rarely has its own upload: only mention a missing resume on the first.
        (t.resume || t.keptResume || t.continuing ? "" : ` Resume not attached: ${t.notes || "no resume upload field found"} — add it by hand.`) +
        " Review everything before moving on. JobBot never submits for you.",
    );
  }, []);

  // A frame that dies mid-fill never reports back: give up after a quiet spell.
  const settleAfterQuiet = useCallback(() => {
    window.clearTimeout(settleTimer.current);
    settleTimer.current = window.setTimeout(settle, 20000);
  }, [settle]);

  // Fill results stream in from whichever frame(s) actually contain the
  // application form (see fill-runner.ts + background frame relay).
  useEffect(() => {
    const listener = (raw: BgToFrame) => {
      if (raw.type === "job:fill-progress") {
        setMsg(`Filling ${raw.index} of ${raw.total} — ${raw.label}…`);
        settleAfterQuiet();
        return;
      }
      if (raw.type !== "job:fill-status") return;
      const t = totals.current;
      t.filled += raw.filled;
      t.skipped += raw.skipped;
      t.resume = t.resume || raw.attachedResume;
      t.keptResume = t.keptResume || !!raw.keptResume;
      t.error = t.error || raw.error || "";
      t.nextLabel = t.nextLabel || raw.nextLabel || "";
      t.questions += raw.questions.length;
      if (raw.questions.length) setQuestions((prev) => [...prev, ...raw.questions]);
      t.frames += 1;
      if (t.frames >= t.expected) settle();
      else settleAfterQuiet();
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, [settle, settleAfterQuiet]);

  /** Fill this step. `continuing`: a later step after Next — keep the resume, fill only blanks. */
  const fill = useCallback(
    async (continuing: boolean) => {
      setOpen(true);
      setPhase("working");
      setNextLabel("");
      setMsg(continuing ? "Waiting for the next step to load…" : "Looking for the application form…");
      totals.current = { ...emptyTotals(), continuing };
      if (!continuing) setQuestions([]);

      // Check before tailoring: on a posting page with no form yet, spend nothing.
      let targets = 0;
      for (let attempt = 0; attempt < (continuing ? FORM_WAIT_TRIES : 1); attempt += 1) {
        if (attempt) await sleep(FORM_WAIT_MS);
        const probe = await bg.probeForm();
        if (!probe.ok) {
          setPhase("error");
          setMsg(probe.error);
          return;
        }
        targets = probe.data.targets;
        if (targets) break;
      }
      if (!targets) {
        setPhase(continuing ? "done" : "error");
        setMsg(
          continuing
            ? "No form on this step. Check the page and continue yourself."
            : "No application form on this page yet — open it, then click Auto-fill.",
        );
        return;
      }

      if (!continuing) {
        const profile = await bg.profile();
        if (profile.ok && !profile.data.has_base_resume) {
          setPhase("error");
          setMsg("Save a base resume on your JobBot Profile page first.");
          return;
        }
        setMsg("Tailoring your resume for this job — this can take a minute…");
        const t = await bg.tailor(job, job.job_title);
        // Hybrid / on-site: stop here, nothing is filled or uploaded.
        if (!t.ok && t.code === ONSITE_BLOCKED) {
          setPhase("error");
          setMsg(t.error);
          return;
        }
        variantRef.current = t.ok ? t.data.resume.variant_id : undefined;
        // Tailoring failing shouldn't lose the rest of the form: fill it and say so.
        if (!t.ok) totals.current.notes = t.error;
      }

      setMsg("Filling the form…");
      const r = await bg.requestFill(job, "tailored", variantRef.current, continuing);
      if (!r.ok || !r.data.targets) {
        setPhase("error");
        setMsg(r.ok ? "The application form is gone — reopen it, then click Auto-fill." : r.error);
        return;
      }
      totals.current.expected = r.data.targets;
      settleAfterQuiet();
    },
    [job, settleAfterQuiet],
  );

  // A Next clicked on the previous page leads here: carry on filling this step.
  useEffect(() => {
    if (checkedContinuation.current || !authed) return;
    checkedContinuation.current = true;
    void bg.takeContinuation().then((r) => {
      if (!r.ok || !r.data) return;
      variantRef.current = r.data.resume_variant_id;
      void fill(true);
    });
  }, [authed, fill]);

  const proceed = useCallback(async () => {
    setNextLabel("");
    setPhase("working");
    setMsg("Going to the next step…");
    // A slow page load must leave the continuation for the new page, not fill this one.
    let leaving = false;
    window.addEventListener("beforeunload", () => (leaving = true), { once: true });
    const r = await bg.continueToNext(job, variantRef.current);
    if (!r.ok || !r.data.clicked) {
      setPhase("error");
      setMsg(
        !r.ok
          ? r.error
          : r.data.reason === "disabled"
            ? "The Next button is still disabled — a required field is probably empty. Fill it, then try again."
            : "Couldn't find the Next button any more. Click it yourself.",
      );
      return;
    }
    // Same-page steps: still here after the wait, so fill this step ourselves.
    window.setTimeout(() => {
      if (leaving) return;
      void bg.takeContinuation().then((c) => {
        if (c.ok && c.data) void fill(true);
      });
    }, SAME_PAGE_STEP_WAIT_MS);
  }, [job, fill]);

  if (!open) {
    return (
      <button
        title="JobBot Copilot"
        onClick={() => setOpen(true)}
        style={{
          position: "fixed",
          right: 16,
          bottom: 16,
          width: 52,
          height: 52,
          borderRadius: "50%",
          border: "none",
          background: "#20c997",
          color: "#04211a",
          font: "800 15px/1 system-ui, sans-serif",
          boxShadow: "0 6px 20px rgba(0,0,0,.35)",
          cursor: "pointer",
          zIndex: 2147483647,
        }}
      >
        JB
      </button>
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        width: questions.length ? 400 : 320,
        maxHeight: "85vh",
        overflowY: "auto",
        background: "#1a1b1e",
        color: "#e9ecef",
        borderRadius: 12,
        boxShadow: "0 12px 40px rgba(0,0,0,.45)",
        padding: 14,
        zIndex: 2147483647,
        font: "13px/1.5 system-ui, sans-serif",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <strong style={{ color: "#20c997" }}>JobBot Copilot</strong>
        <button
          title="Minimize"
          onClick={() => setOpen(false)}
          style={{ ...btn, background: "transparent", color: "#868e96", padding: 4 }}
        >
          ✕
        </button>
      </div>
      <div style={{ margin: "6px 0 10px", color: "#adb5bd" }}>
        {job.job_title || "Job application"} {job.company ? `· ${job.company}` : ""}
      </div>

      {authed === false && (
        <div>
          <p style={{ margin: "0 0 8px" }}>Sign in to JobBot to autofill and track this application.</p>
          <a
            href={`${WEB_ORIGIN}/auth`}
            target="_blank"
            rel="noreferrer"
            style={{ ...btn, background: "#20c997", color: "#04211a", textDecoration: "none", display: "inline-block" }}
          >
            Open JobBot
          </a>
        </div>
      )}

      {authed && (
        <>
          {!AUTOFILL_ENABLED && (
            <p style={{ margin: "0 0 8px", color: "#adb5bd" }}>
              Apply as usual — when the site confirms your application, JobBot records it in your tracker with the
              resume you sent.
            </p>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {AUTOFILL_ENABLED && (
              <button
                style={{ ...btn, background: "#20c997", color: "#04211a" }}
                disabled={phase === "working"}
                onClick={() => void fill(false)}
              >
                {phase === "working" ? "Working…" : "Auto-fill"}
              </button>
            )}
            <a
              href={`${WEB_ORIGIN}/applications`}
              target="_blank"
              rel="noreferrer"
              style={{ ...btn, background: "#2c2e33", color: "#e9ecef", textDecoration: "none" }}
            >
              Tracker
            </a>
          </div>
          {msg && (
            <p
              style={{
                margin: "10px 0 0",
                color: phase === "error" ? "#ff8787" : "#adb5bd",
              }}
            >
              {msg}
            </p>
          )}
          {nextLabel && phase === "done" && (
            <div style={{ marginTop: 10, padding: 10, background: "#25262b", borderRadius: 8 }}>
              <div style={{ marginBottom: 8 }}>
                Go to the next step? JobBot will click “{nextLabel}” and fill the blank fields on the next page.
                Check this page first.
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button style={{ ...btn, background: "#20c997", color: "#04211a" }} onClick={() => void proceed()}>
                  Proceed
                </button>
                <button
                  style={{ ...btn, background: "#2c2e33", color: "#e9ecef" }}
                  onClick={() => setNextLabel("")}
                >
                  Not now
                </button>
              </div>
            </div>
          )}
          {questions.length > 0 && (
            <div style={{ marginTop: 12, borderTop: "1px solid #2c2e33", paddingTop: 10 }}>
              <strong style={{ color: "#e9ecef" }}>Application questions</strong>
              {questions.map((q) => (
                <div key={q.key} style={{ marginTop: 10 }}>
                  <div style={{ fontWeight: 600, color: "#ced4da" }}>{q.label}</div>
                  {q.answer ? (
                    <>
                      <div style={{ margin: "4px 0 6px", whiteSpace: "pre-wrap", color: "#adb5bd" }}>{q.answer}</div>
                      <button
                        style={{ ...btn, background: "#2c2e33", color: "#e9ecef", padding: "6px 10px" }}
                        onClick={() => {
                          void copyText(q.answer).then(() => setCopiedKey(q.key));
                        }}
                      >
                        {copiedKey === q.key ? "Copied" : "Copy"}
                      </button>
                    </>
                  ) : (
                    <div style={{ marginTop: 4, color: "#868e96" }}>
                      JobBot can't answer this from your resume. Please answer it yourself.
                    </div>
                  )}
                </div>
              ))}
              {questions.some((q) => q.answer) && (
                <p style={{ margin: "12px 0 0", color: "#ffd43b" }}>
                  You need to humanize the text via this platform{" "}
                  <a href={HUMANIZER_URL} target="_blank" rel="noreferrer" style={{ color: "#ffd43b" }}>
                    {HUMANIZER_URL}
                  </a>{" "}
                  since this is AI generated text.
                </p>
              )}
            </div>
          )}
          {AUTOFILL_ENABLED && (
            <p style={{ margin: "8px 0 0", fontSize: 11, color: "#868e96" }}>
              JobBot never submits for you. Always review what it filled.
            </p>
          )}
        </>
      )}
    </div>
  );
}
