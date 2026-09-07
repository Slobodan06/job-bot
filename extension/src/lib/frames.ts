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
  // The user clicked what looks like the site's own submit control in this
  // frame. No job payload needed — the background already knows the best
  // detected job for this tab (or this specific frame, if it has its own).
  | { type: "frame:submitted" };

/** Pushed by the background into a specific frame via chrome.tabs.sendMessage. */
export type BgToFrame =
  | { type: "job:update"; job: DetectedJob | null }
  | { type: "job:fill-progress"; label: string; index: number; total: number }
  | { type: "job:fill-status"; filled: number; skipped: number; attachedResume: boolean }
  | {
      type: "do-fill";
      job: DetectedJob;
      variant: "quick" | "tailored";
      resumeVariantId?: string;
    };
