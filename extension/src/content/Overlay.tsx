import { useCallback, useEffect, useRef, useState } from "react";

import { WEB_ORIGIN } from "../lib/env";
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
  const totals = useRef({ filled: 0, skipped: 0, resume: false, frames: 0 });
  const settleTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    bg.authGet().then((r) => setAuthed(r.ok && !!r.data.token));
  }, []);

  // Applications are recorded only on a confirmed submit (see
  // background/index.ts's "frame:submitted" handling), never just for
  // detecting or viewing a posting — the tracker would otherwise fill up with
  // every job you glance at.

  // Fill results stream in from whichever frame(s) actually contain the
  // application form (see fill-runner.ts + background frame relay).
  useEffect(() => {
    const listener = (raw: BgToFrame) => {
      if (raw.type === "job:fill-progress") {
        setMsg(`Filling ${raw.index} of ${raw.total} — ${raw.label}…`);
        return;
      }
      if (raw.type !== "job:fill-status") return;
      const t = totals.current;
      t.filled += raw.filled;
      t.skipped += raw.skipped;
      t.resume = t.resume || raw.attachedResume;
      t.frames += 1;
      window.clearTimeout(settleTimer.current);
      settleTimer.current = window.setTimeout(() => {
        setPhase(t.filled + t.skipped === 0 ? "error" : "done");
        setMsg(
          t.filled === 0
            ? "No fillable fields found yet — open the application form, then try again."
            : `Filled ${t.filled} field${t.filled === 1 ? "" : "s"}${t.resume ? " + attached resume" : ""}.` +
                (t.skipped ? ` ${t.skipped} need a manual check.` : "") +
                " Review everything, then submit the form yourself.",
        );
      }, 900);
    };
    chrome.runtime.onMessage.addListener(listener);
    return () => chrome.runtime.onMessage.removeListener(listener);
  }, []);

  const run = useCallback(
    async (variant: "quick" | "tailored") => {
      setPhase("working");
      setMsg(variant === "tailored" ? "Tailoring your resume for this job…" : "Filling the form…");
      totals.current = { filled: 0, skipped: 0, resume: false, frames: 0 };

      let resumeVariantId: string | undefined;
      if (variant === "tailored") {
        const t = await bg.tailor(job, job.job_title);
        if (!t.ok) {
          setPhase("error");
          setMsg(t.error);
          return;
        }
        resumeVariantId = t.data.resume.variant_id;
      }
      const r = await bg.requestFill(job, variant, resumeVariantId);
      if (!r.ok || !r.data.targets) {
        setPhase("error");
        setMsg(r.ok ? "No application form found on this page yet." : r.error);
        return;
      }
      // Fields are typed one at a time (so the fill is visible) — a form with
      // many fields can take a while. Results arrive asynchronously via the
      // job:fill-status listener above; only flag "nothing happened" once a
      // generous window has passed with no report at all.
      window.setTimeout(() => {
        if (totals.current.frames === 0) {
          setPhase("error");
          setMsg("No application form found on this page yet — open the apply form first.");
        }
      }, 20000);
    },
    [job],
  );

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
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              style={{ ...btn, background: "#20c997", color: "#04211a" }}
              disabled={phase === "working"}
              onClick={() => run("quick")}
            >
              Quick fill
            </button>
            <button
              style={{ ...btn, background: "#4c6ef5", color: "#fff" }}
              disabled={phase === "working"}
              onClick={() => run("tailored")}
            >
              Tailor &amp; fill
            </button>
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
          <p style={{ margin: "8px 0 0", fontSize: 11, color: "#868e96" }}>
            JobBot never submits for you. Always review AI-drafted answers.
          </p>
        </>
      )}
    </div>
  );
}
