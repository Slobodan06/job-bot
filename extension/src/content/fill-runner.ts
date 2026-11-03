import { applyValues, attachResume, findResumeInput, isBlankField, resumeAlreadyUploaded } from "../autofill/apply";
import { discoverFields } from "../autofill/fields";
import { markField } from "../autofill/highlight";
import { bg } from "../lib/messaging";
import type { ApplicationQuestion, DetectedJob } from "../lib/types";
import { findNextControl } from "./next-step";
import { reportAttachedResume } from "./submission";

// Answering one question can reveal another (Greenhouse shows the race question only
// after Hispanic/Latino is answered), so look again until nothing new appears.
const MAX_PASSES = 3;
const REVEAL_WAIT_MS = 500;

/** Enough to be an application form: a resume upload, or more than a lone newsletter/search box. */
export function hasApplicationForm(): boolean {
  return !!findResumeInput() || discoverFields().length >= 2;
}

/** Discover + fill whatever form fields exist in THIS frame's document, if any. */
export async function runFillInThisFrame(
  job: DetectedJob,
  variant: "quick" | "tailored",
  resumeVariantId: string | undefined,
  onlyBlank = false,
): Promise<{
  filled: number;
  skipped: number;
  attachedResume: boolean;
  keptResume: boolean;
  questions: ApplicationQuestion[];
  nextLabel?: string;
  error?: string;
}> {
  const seen = new Set<string>();
  const questions: ApplicationQuestion[] = [];
  let filled = 0;
  let skipped = 0;
  let attached = false;
  let kept = false;

  for (let pass = 0; pass < MAX_PASSES; pass += 1) {
    if (pass > 0) await new Promise((r) => setTimeout(r, REVEAL_WAIT_MS));
    const live = discoverFields().filter(
      (f) => !seen.has(f.descriptor.key) && (!onlyBlank || isBlankField(f.el)),
    );
    if (pass > 0 && !live.length) break;
    if (!live.length && !findResumeInput()) break;
    for (const field of live) seen.add(field.descriptor.key);

    const r = await bg.autofill(
      job,
      live.map((f) => f.descriptor),
      variant,
      resumeVariantId,
    );
    if (!r.ok) {
      return {
        filled,
        skipped: skipped + live.length,
        attachedResume: attached,
        keptResume: kept,
        questions,
        error: r.error,
      };
    }
    const result = await applyValues(live, r.data.values, r.data.answers, (p) => {
      chrome.runtime
        .sendMessage({ type: "frame:fill-progress", label: p.label, index: p.index, total: p.total })
        .catch(() => {});
    });
    filled += result.filled;
    skipped += result.skipped.length;

    for (const question of r.data.questions) {
      const field = live.find((f) => f.descriptor.key === question.key);
      if (field) markField(field.el, "question");
      questions.push(question);
    }

    if (r.data.resume && !attached && !kept) {
      // Workday keeps the resume from "Autofill with Resume"; members upload their own too.
      const input = findResumeInput();
      kept = !!input && resumeAlreadyUploaded(input);
    }
    if (r.data.resume && !attached && !kept) {
      const file = await bg.fetchResume(r.data.resume.download_path);
      if (file.ok) {
        attached = await attachResume(file.data.dataUrl, file.data.filename);
        if (attached) reportAttachedResume(r.data.resume.variant_id, file.data.filename);
      }
    }
  }
  const next = findNextControl();
  const nextLabel = next ? (next.innerText || (next as HTMLInputElement).value || "Next").trim() : undefined;
  return { filled, skipped, attachedResume: attached, keptResume: kept, questions, nextLabel };
}
