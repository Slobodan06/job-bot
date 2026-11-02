import { useCallback, useEffect, useRef, useState } from "react";

import { AUTOFILL_ENABLED, WEB_ORIGIN } from "../lib/env";
import type { BgToFrame } from "../lib/frames";
import { bg } from "../lib/messaging";
import type { DetectedJob } from "../lib/types";

type Phase = "idle" | "working" | "done" | "error";
type Props = { job: DetectedJob; onDismiss: () => void };

const btn: React.CSSProperties = {
  border: "none",
  borderRadius: 8,
  padding: "8px 12px",
  font: "600 12px/1 system-ui, sans-serif",
  cursor: "pointer",
};

export function Overlay({ job, onDismiss }: Props) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [msg, setMsg] = useState("");
  const totals = useRef({ filled: 0, skipped: 0, resume: false, frames: 0, expected: 0, error: "", notes: "" });
  const settleTimer = useRef<number | undefined>(undefined);

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
    if (t.filled === 0 && !t.resume) {
      setPhase("error");
      setMsg(t.error || "No fillable fields found yet — open the application form, then try again.");
      return;
    }
    setPhase("done");
    setMsg(
      `Filled ${t.filled} field${t.filled === 1 ? "" : "s"}${t.resume ? " and attached your tailored resume" : ""}.` +
        (t.skipped ? ` ${t.skipped} need a manual check.` : "") +
        (t.resume ? "" : ` Resume not attached: ${t.notes || "no resume upload field found"} — add it by hand.`) +
        " Review everything, then submit it yourself. JobBot tracks it once the site confirms.",
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
      t.error = t.error || raw.error || "";
      t.frames += 1;
      if (t.frames >= t.expected) settle();
      else settleAfterQuiet();
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, [settle, settleAfterQuiet]);

  const run = useCallback(async () => {
    setPhase("working");
    setMsg("Looking for the application form…");
    totals.current = { filled: 0, skipped: 0, resume: false, frames: 0, expected: 0, error: "", notes: "" };

    // Check before tailoring: on a posting page with no form yet, spend nothing.
    const probe = await bg.probeForm();
    if (!probe.ok || !probe.data.targets) {
      setPhase("error");
      setMsg(probe.ok ? "No application form on this page yet — open it, then click Auto-fill." : probe.error);
      return;
    }
    const profile = await bg.profile();
    if (profile.ok && !profile.data.has_base_resume) {
      setPhase("error");
      setMsg("Save a base resume on your JobBot Profile page first.");
      return;
    }

    setMsg("Tailoring your resume for this job — this can take a minute…");
    let resumeVariantId: string | undefined;
    const t = await bg.tailor(job, job.job_title);
    if (t.ok) resumeVariantId = t.data.resume.variant_id;
    // Tailoring failing shouldn't lose the rest of the form: fill it and say so.
    else totals.current.notes = t.error;

    setMsg("Filling the form…");
    const r = await bg.requestFill(job, "tailored", resumeVariantId);
    if (!r.ok || !r.data.targets) {
      setPhase("error");
      setMsg(r.ok ? "The application form is gone — reopen it, then click Auto-fill." : r.error);
      return;
    }
    totals.current.expected = r.data.targets;
    settleAfterQuiet();
  }, [job, settleAfterQuiet]);

  return (
    <div
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        width: 320,
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
          onClick={onDismiss}
          style={{ ...btn, background: "transparent", color: "#868e96", padding: 4 }}
        >
          ✕
        </button>
      </div>
      <div style={{ margin: "6px 0 10px", color: "#adb5bd" }}>
        {job.job_title || "Job"} {job.company ? `· ${job.company}` : ""}
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
                onClick={run}
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
          {AUTOFILL_ENABLED && (
            <p style={{ margin: "8px 0 0", fontSize: 11, color: "#868e96" }}>
              JobBot never submits for you. Always review AI-drafted answers.
            </p>
          )}
        </>
      )}
    </div>
  );
}
