/**
 * Cross-frame protocol. A tab can be made of several frames (iframe-embedded
 * ATS widgets are common — Greenhouse/Workday/others are frequently embedded
 * on a company's own careers domain). Only the top frame renders the overlay;
 * every frame independently detects and can independently fill itself. The
 * background service worker is the relay between frames of the same tab.
 */
import type { DetectedJob } from "./types";

/** Sent by every frame's content script to the background, fire-and-forget. */
export type FrameToBg =
  | { type: "frame:report-job"; job: DetectedJob | null }
  | { type: "frame:fill-progress"; label: string; index: number; total: number }
  | { type: "frame:fill-result"; filled: number; skipped: number; attachedResume: boolean }
  // The user clicked what looks like the form's final submit control in this
  // frame. Only *arms* tracking — nothing is recorded until a confirmation
  // follows (see content/submission.ts).
  | { type: "frame:submit-clicked"; pageUrl: string; pageTitle: string }
  // A "thanks for applying"-style confirmation appeared in this frame while armed.
  | { type: "frame:confirmation"; pageUrl: string; evidence: string }
  // The resume that will go out with the application: a file the user picked
  // on the page (dataUrl) or a JobBot variant the extension attached (variantId).
  | {
      type: "frame:resume-selected";
      filename: string;
      contentType?: string;
      dataUrl?: string;
      variantId?: string;
    };

/** Pushed by the background into a specific frame via chrome.tabs.sendMessage. */
export type BgToFrame =
  | { type: "job:update"; job: DetectedJob | null }
  | { type: "job:fill-progress"; label: string; index: number; total: number }
  | { type: "job:fill-status"; filled: number; skipped: number; attachedResume: boolean }
  // Tracking armed for this tab: watch for a confirmation until `until` (epoch ms).
  | { type: "track:armed"; until: number }
  // Outcome of recording a confirmed application (top frame shows a toast).
  | { type: "track:recorded"; ok: boolean; message: string }
  | {
      type: "do-fill";
      job: DetectedJob;
      variant: "quick" | "tailored";
      resumeVariantId?: string;
    };
