import { applyValues, attachResume, findResumeInput } from "../autofill/apply";
import { discoverFields } from "../autofill/fields";
import { bg } from "../lib/messaging";
import type { DetectedJob } from "../lib/types";
import { reportAttachedResume } from "./submission";

/** Enough to be an application form: a resume upload, or more than a lone newsletter/search box. */
export function hasApplicationForm(): boolean {
  return !!findResumeInput() || discoverFields().length >= 2;
}

/** Discover + fill whatever form fields exist in THIS frame's document, if any. */
export async function runFillInThisFrame(
  job: DetectedJob,
  variant: "quick" | "tailored",
  resumeVariantId: string | undefined,
): Promise<{ filled: number; skipped: number; attachedResume: boolean; error?: string }> {
  const live = discoverFields();
  if (!live.length && !findResumeInput()) {
    return { filled: 0, skipped: 0, attachedResume: false };
  }
  const r = await bg.autofill(
    job,
    live.map((f) => f.descriptor),
    variant,
    resumeVariantId,
  );
  if (!r.ok) {
    return { filled: 0, skipped: live.length, attachedResume: false, error: r.error };
  }
  const { filled, skipped } = await applyValues(live, r.data.values, r.data.answers, (p) => {
    chrome.runtime
      .sendMessage({ type: "frame:fill-progress", label: p.label, index: p.index, total: p.total })
      .catch(() => {});
  });
  let attached = false;
  if (r.data.resume) {
    const file = await bg.fetchResume(r.data.resume.download_path);
    if (file.ok) {
      attached = await attachResume(file.data.dataUrl, file.data.filename);
      if (attached) reportAttachedResume(r.data.resume.variant_id, file.data.filename);
    }
  }
  return { filled, skipped: skipped.length, attachedResume: attached };
}
