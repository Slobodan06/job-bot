import { applyValues, attachResume } from "../autofill/apply";
import { discoverFields } from "../autofill/fields";
import { bg } from "../lib/messaging";
import type { DetectedJob } from "../lib/types";

/** Discover + fill whatever form fields exist in THIS frame's document, if any. */
export async function runFillInThisFrame(
  job: DetectedJob,
  variant: "quick" | "tailored",
  resumeVariantId: string | undefined,
): Promise<{ filled: number; skipped: number; attachedResume: boolean }> {
  const live = discoverFields();
  if (!live.length) {
    return { filled: 0, skipped: 0, attachedResume: false };
  }
  const r = await bg.autofill(
    job,
    live.map((f) => f.descriptor),
    variant,
    resumeVariantId,
  );
  if (!r.ok) {
    return { filled: 0, skipped: live.length, attachedResume: false };
  }
  const { filled, skipped } = await applyValues(live, r.data.values, r.data.answers, (p) => {
    chrome.runtime
      .sendMessage({ type: "frame:fill-progress", label: p.label, index: p.index, total: p.total })
      .catch(() => {});
  });
  let attached = false;
  if (r.data.resume) {
    const file = await bg.fetchResume(r.data.resume.download_path);
    if (file.ok) attached = await attachResume(live, file.data.dataUrl, file.data.filename);
  }
  return { filled, skipped: skipped.length, attachedResume: attached };
}
