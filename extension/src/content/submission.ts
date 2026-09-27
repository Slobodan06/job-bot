/**
 * Application-submission tracking, run in every frame.
 *
 * A job is recorded only when BOTH happen, in order:
 *   1. the user clicks what looks like the form's final "Submit / Apply / Send"
 *      control (or a form submits) — this merely *arms* tracking for the tab;
 *   2. a confirmation then appears — "Thanks for applying", "Your application
 *      has been submitted", a /thank-you or /confirmation URL, ... — in any
 *      frame of the tab, either on the same page or after it navigates.
 * Step 1 alone never records anything (validation errors, multi-step wizards,
 * "Apply" buttons that merely open the form), so the tracker only ever holds
 * applications the site itself confirmed.
 *
 * The resume that went out is captured whenever the user picks/drops a file
 * into a resume-like upload field (or the extension attaches one), and the
 * background sends it along with the record.
 */
import type { BgToFrame, FrameToBg } from "../lib/frames";
import { sendToBackground } from "../lib/messaging";

const isTopFrame = window.top === window.self;
// Held in chrome.storage.session (10 MB quota) until the confirmation arrives.
const MAX_RESUME_BYTES = 5 * 1024 * 1024;
const RESUME_FILE_RE = /\.(pdf|docx?|rtf|odt|txt)$/i;

function report(msg: FrameToBg): void {
  chrome.runtime.sendMessage(msg).catch(() => {
    /* background may not be ready yet (extension just installed/reloaded) */
  });
}

// ---------------------------------------------------------------------------
// 1. Final-submit detection (arms tracking)
// ---------------------------------------------------------------------------

const CLICKABLE = 'button, input[type="submit"], input[type="button"], [role="button"], a';
// Words on a control that finishes an application...
const FINAL_RE = /\b(submit|send( my)? application|finish|complete( my)? application)\b/i;
// ..."Apply" only inside a form — on a posting page "Apply now" just opens it.
const APPLY_RE = /\bapply\b/i;
// ...unless it plainly only moves between wizard steps.
const STEP_RE = /\b(next|continue|back|previous|cancel|save (as )?draft|save for later)\b/i;

function controlText(el: Element): string {
  const input = el as HTMLInputElement;
  const text =
    (el as HTMLElement).innerText ||
    (el.tagName === "INPUT" ? input.value : "") ||
    el.getAttribute("aria-label") ||
    el.getAttribute("title") ||
    "";
  return text.replace(/\s+/g, " ").trim();
}

export function isFinalSubmitControl(el: Element): boolean {
  const isSubmitType = el.matches('button[type="submit"], input[type="submit"]');
  const text = controlText(el);
  // Long text means we hit a container, not a button label.
  if (!text || text.length > 60) return isSubmitType;
  if (STEP_RE.test(text)) return false;
  if (FINAL_RE.test(text)) return true;
  if (APPLY_RE.test(text)) return el.tagName !== "A" && !!el.closest("form");
  return isSubmitType;
}

function arm(): void {
  report({ type: "frame:submit-clicked", pageUrl: location.href, pageTitle: document.title });
}

// ---------------------------------------------------------------------------
// 2. Confirmation detection (records the application)
// ---------------------------------------------------------------------------

const CONFIRM_TEXT_RE = [
  /\bthanks?( you)?( so much| again)?,? for (applying|your application|submitting( your application)?)\b/gi,
  /\bapplication (has been|was) (successfully )?(submitted|received|sent|completed)\b/gi,
  /\bapplication (successfully )?(submitted|received|sent)\b/gi,
  /\bwe('ve| have)? (successfully )?received your application\b/gi,
  /\byou('ve| have) (successfully )?(applied|submitted your application)\b/gi,
  /\bsuccessfully (applied|submitted)\b/gi,
  /\byour application is (on its way|in)\b/gi,
];
// "Once your application has been submitted, you'll…" is an instruction, not a confirmation.
const CONDITIONAL_BEFORE_RE = /\b(once|after|when|until|before|if|unless)\b[^.!?\n]{0,30}$/i;
const CONFIRM_URL_RE = /[/_-](thank[s-]?(you)?|confirmation|application[-_]?(submitted|complete|received)|applied|success)([/_?#.-]|$)/i;

function pageText(): string {
  // innerText skips display:none content, so hidden success templates that
  // ship with the form don't count. Capped: confirmations are near the top.
  return `${document.title}\n${(document.body?.innerText || "").slice(0, 60000)}`;
}

export function findConfirmation(): string | null {
  const text = pageText();
  for (const re of CONFIRM_TEXT_RE) {
    for (const m of text.matchAll(re)) {
      const before = text.slice(Math.max(0, m.index - 40), m.index);
      if (!CONDITIONAL_BEFORE_RE.test(before)) return m[0];
    }
  }
  if (CONFIRM_URL_RE.test(location.pathname + location.search + location.hash)) {
    return `url:${location.pathname}`;
  }
  return null;
}

let watchUntil = 0;
let baseline: string | null = null;
let observer: MutationObserver | null = null;
let scanTimer: number | undefined;
let confirmed = false;

function stopWatching(): void {
  observer?.disconnect();
  observer = null;
  window.clearTimeout(scanTimer);
}

function scan(): void {
  if (confirmed) return;
  if (Date.now() > watchUntil) {
    stopWatching();
    return;
  }
  const hit = findConfirmation();
  // A phrase that was already on screen when the user clicked submit (e.g.
  // "once your application has been submitted…" in the instructions) is not
  // a confirmation.
  if (hit && hit !== baseline) {
    confirmed = true;
    stopWatching();
    report({ type: "frame:confirmation", pageUrl: location.href, evidence: hit.slice(0, 200) });
  }
}

function scheduleScan(): void {
  window.clearTimeout(scanTimer);
  scanTimer = window.setTimeout(scan, 500);
}

/** Watch this frame for a confirmation until `until` (epoch ms). */
function watchForConfirmation(until: number, freshPage: boolean): void {
  watchUntil = until;
  confirmed = false;
  baseline = freshPage ? null : findConfirmation();
  if (!observer) {
    // Confirmations usually replace the form in place (SPA) — watch the DOM.
    observer = new MutationObserver(scheduleScan);
    observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  }
  scheduleScan();
  // Re-check a few times for changes the observer can't see (e.g. inside a
  // shadow root).
  window.setTimeout(scan, 3000);
  window.setTimeout(scan, 8000);
}

// ---------------------------------------------------------------------------
// 3. Resume capture
// ---------------------------------------------------------------------------

const RESUME_WORD_RE = /\b(resume|cv|curriculum)\b|résumé/i;
const OTHER_UPLOAD_RE = /cover\s*letter|transcript|portfolio|writing sample|photo|avatar/i;

/** Text describing an upload control, from its own attributes outward `depth` ancestors. */
function contextText(el: Element, depth: number): string {
  const input = el as HTMLInputElement;
  const parts = [
    input.name,
    input.id,
    el.getAttribute("aria-label"),
    el.getAttribute("data-automation-id"),
    ...Array.from(input.labels || []).map((l) => l.textContent),
  ];
  let node: Element | null = el.parentElement;
  for (let d = 0; node && d < depth; d += 1, node = node.parentElement) {
    parts.push((node.textContent || "").slice(0, 300));
  }
  return parts.filter(Boolean).join(" ");
}

function isResumeUploadTarget(el: Element): boolean {
  // Nearest context first: wider ancestors often span the whole form, where
  // "Resume" and "Cover letter" both appear.
  for (const depth of [1, 2, 4]) {
    const ctx = contextText(el, depth);
    const resume = RESUME_WORD_RE.test(ctx);
    const other = OTHER_UPLOAD_RE.test(ctx);
    if (resume && !other) return true;
    if (other && !resume) return false;
  }
  // A form with a single upload field is, in practice, the resume field.
  return document.querySelectorAll('input[type="file"]').length === 1;
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

async function captureResume(file: File | undefined, target: Element): Promise<void> {
  if (!file || file.size === 0 || file.size > MAX_RESUME_BYTES) return;
  if (!RESUME_FILE_RE.test(file.name)) return;
  if (!isResumeUploadTarget(target)) return;
  try {
    const dataUrl = await readAsDataUrl(file);
    report({
      type: "frame:resume-selected",
      filename: file.name,
      contentType: file.type,
      dataUrl,
    });
  } catch {
    /* unreadable file — nothing to record */
  }
}

/** Called by the fill runner after it attached a JobBot-generated resume. */
export function reportAttachedResume(variantId: string, filename: string): void {
  report({ type: "frame:resume-selected", filename, variantId });
}

// ---------------------------------------------------------------------------
// 4. Feedback toast (top frame only)
// ---------------------------------------------------------------------------

function showToast(text: string, ok: boolean): void {
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;z-index:2147483647;right:16px;bottom:16px;";
  const shadow = host.attachShadow({ mode: "open" });
  const box = document.createElement("div");
  box.textContent = text;
  box.style.cssText = [
    "max-width:320px",
    "padding:12px 14px",
    "border-radius:10px",
    "font:500 13px/1.4 system-ui,sans-serif",
    "color:#fff",
    `background:${ok ? "#0ca678" : "#e03131"}`,
    "box-shadow:0 6px 24px rgba(0,0,0,.25)",
  ].join(";");
  shadow.appendChild(box);
  document.documentElement.appendChild(host);
  window.setTimeout(() => host.remove(), 6000);
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

export function initSubmissionTracking(): void {
  document.addEventListener(
    "click",
    (e) => {
      if (!e.isTrusted) return;
      const control = (e.target as Element | null)?.closest?.(CLICKABLE);
      if (control && isFinalSubmitControl(control)) arm();
    },
    true,
  );
  document.addEventListener(
    "submit",
    () => arm(),
    true,
  );

  // Only real user picks: the extension's own programmatic attach dispatches
  // untrusted events and reports itself via reportAttachedResume().
  document.addEventListener(
    "change",
    (e) => {
      const input = e.target as HTMLInputElement | null;
      if (!e.isTrusted || !input || input.type !== "file") return;
      void captureResume(input.files?.[0], input);
    },
    true,
  );
  document.addEventListener(
    "drop",
    (e) => {
      if (!e.isTrusted || !e.target) return;
      void captureResume(e.dataTransfer?.files?.[0], e.target as Element);
    },
    true,
  );

  chrome.runtime.onMessage.addListener((msg: BgToFrame) => {
    if (msg.type === "track:armed") watchForConfirmation(msg.until, false);
    if (msg.type === "track:recorded" && isTopFrame) showToast(msg.message, msg.ok);
  });

  // A confirmation often lives on the page the form navigates to — if this
  // tab was armed before this document loaded, watch it from the start.
  void sendToBackground<{ armedUntil: number | null }>({ type: "tracking:state" }).then((r) => {
    if (r.ok && r.data.armedUntil && r.data.armedUntil > Date.now()) {
      watchForConfirmation(r.data.armedUntil, true);
    }
  });
}
