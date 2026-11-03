import { deepQueryAll, rootOf } from "../detectors/dom";
import { isResumeUploadTarget } from "../content/submission";
import { choiceItems, isChoiceGroup, isChoiceSelected, type LiveField } from "./fields";
import { markField } from "./highlight";
import { pickOption } from "./match";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Low-level: set .value via the native setter (bypasses React's shadowed
 * value property) and fire one input/change/blur — used for bulk (non-typed)
 * writes: textareas, and as the final commit after char-by-char typing. */
function setNativeValueRaw(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) {
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value");
  desc?.set?.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

/** Type into an <input> one character at a time. Real ATS forms frequently
 * use a masked/formatted or React-controlled input (dates, phone, zip) that
 * only reformats correctly in response to per-keystroke input events — a
 * single bulk `.value =` set (what a plain autofill does) leaves masked
 * fields showing garbage like "00/0000". This is also what makes the fill
 * visibly happen field by field instead of all at once. */
async function typeIntoInput(
  el: HTMLInputElement | HTMLTextAreaElement,
  value: string,
  perCharDelayMs = 18,
  commit = true,
): Promise<void> {
  el.focus();
  setNativeValueRaw(el, "");
  for (const ch of value) {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: ch, bubbles: true }));
    setNativeValueRaw(el, el.value + ch);
    el.dispatchEvent(new InputEvent("input", { bubbles: true, data: ch, inputType: "insertText" }));
    el.dispatchEvent(new KeyboardEvent("keyup", { key: ch, bubbles: true }));
    if (perCharDelayMs) await sleep(perCharDelayMs);
  }
  // A search box must keep focus while its suggestions load: blurring closes them.
  if (!commit) return;
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new Event("blur", { bubbles: true }));
}

/** An answer's own name: the first line of its label, without the explanation under it
 * ("Hispanic or Latino" + "A person of Cuban, Mexican, ... origin"). */
function labelTextOf(input: HTMLInputElement, root: ParentNode): string {
  const label =
    (input.id ? root.querySelector<HTMLElement>(`label[for="${CSS.escape(input.id)}"]`) : null) ||
    input.closest<HTMLElement>("label");
  const text = label ? label.innerText || label.textContent || "" : input.getAttribute("aria-label") || input.value || "";
  return (
    text
      .split("\n")
      .map((t) => t.trim())
      .find(Boolean) || ""
  );
}

function check(input: HTMLInputElement): void {
  if (input.checked) return;
  // A real click runs the site's own handlers (React/Vue listen for it, not for .checked).
  input.click();
  if (!input.checked) {
    input.checked = true;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

/** Match a radio group, or a multi-checkbox group sharing a `name`, by label text. */
function fillGroupByLabel(el: HTMLInputElement, value: string): boolean {
  const name = el.getAttribute("name");
  const root = rootOf(el);
  const group = name
    ? Array.from(root.querySelectorAll<HTMLInputElement>(`input[name="${CSS.escape(name)}"]`))
    : [el];
  const i = pickOption(group.map((input) => labelTextOf(input, root)), value);
  if (i < 0) return false;
  check(group[i]);
  return true;
}

const AFFIRMATIVE_RE = /^(yes|y|true|1|on|agree|confirm|accept)$/i;
const NEGATIVE_RE = /^(no|n|false|0|off|disagree|decline)$/i;

/** A standalone checkbox (not part of a multi-option group) is a boolean toggle. */
function fillCheckbox(el: HTMLInputElement, value: string): boolean {
  const name = el.getAttribute("name");
  const root = rootOf(el);
  const group = name
    ? Array.from(root.querySelectorAll<HTMLInputElement>(`input[type="checkbox"][name="${CSS.escape(name)}"]`))
    : [el];
  if (group.length > 1) return fillGroupByLabel(el, value);

  const v = value.trim();
  if (!AFFIRMATIVE_RE.test(v) && !NEGATIVE_RE.test(v)) return false; // not a clear yes/no — leave for manual review
  const want = AFFIRMATIVE_RE.test(v);
  if (el.checked !== want) el.click();
  if (el.checked !== want) {
    el.checked = want;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  return true;
}

function fillSelect(el: HTMLSelectElement, value: string): boolean {
  const options = Array.from(el.options);
  const exact = options.findIndex((o) => o.value.trim().toLowerCase() === value.trim().toLowerCase());
  const i = exact >= 0 ? exact : pickOption(options.map((o) => o.text), value);
  if (i < 0) return false;
  setNativeValueRaw(el, options[i].value);
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return true;
}

/** Yes/No buttons and custom radio groups (role="radio" items, no native inputs). */
function fillChoiceGroup(group: HTMLElement, value: string): boolean {
  const items = choiceItems(group);
  const i = pickOption(items.map((b) => b.innerText || b.getAttribute("aria-label") || ""), value);
  if (i < 0) return false;
  if (!isChoiceSelected(items[i])) dispatchClick(items[i]);
  return true;
}

// Most component-library dropdowns (React-Select, MUI Autocomplete, Radix,
// Headless UI, Workday's custom pickers, ...) are NOT a native <select> — they
// are a text input or button with role="combobox"/aria-haspopup="listbox"
// that opens a popup of role="option" elements (often rendered in a portal
// appended elsewhere in the document, not necessarily inside the trigger).
function isComboboxTrigger(el: HTMLElement): boolean {
  const role = (el.getAttribute("role") || "").toLowerCase();
  const haspopup = (el.getAttribute("aria-haspopup") || "").toLowerCase();
  return (
    role === "combobox" ||
    haspopup === "listbox" ||
    haspopup === "true" ||
    el.hasAttribute("aria-autocomplete") ||
    (el instanceof HTMLInputElement && !!el.list) ||
    !!el.closest('[role="combobox"]')
  );
}

// Text boxes that are search-as-you-type pickers without saying so (Google Places
// location boxes, school/employer lookups): suggestions appear under them as you type.
const LOOKUP_LABEL_RE = /\blocation\b|\bcity\b|\btown\b|where .*(live|based|located)|school|universit|college|employer/i;

function dispatchClick(el: HTMLElement): void {
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.startsWith("pointer") && typeof PointerEvent !== "undefined" ? PointerEvent : MouseEvent;
    el.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true, view: window }));
  }
}

function key(el: HTMLElement, k: string): void {
  for (const type of ["keydown", "keyup"]) {
    el.dispatchEvent(new KeyboardEvent(type, { key: k, code: k, bubbles: true, cancelable: true }));
  }
}

const OPTION_SELECTOR = [
  '[role="option"]',
  '[role="listbox"] li',
  '[role="menuitem"]',
  '[data-automation-id="promptOption"]',
  '[data-automation-id="menuItem"]',
  ".pac-item",
  '[class*="option" i]',
  '[class*="suggestion" i]',
  '[class*="autocomplete" i] li',
  '[class*="results" i] li',
  '[class*="dropdown" i] li',
].join(", ");

const isShown = (el: HTMLElement) => {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
};

/** The open option list's best match for `value`. Only visible options count: every
 * other dropdown on the page keeps its (hidden) list in the DOM too. */
function findOption(value: string, exclude?: HTMLElement): HTMLElement | null {
  const options = deepQueryAll<HTMLElement>(OPTION_SELECTOR).filter(
    (o) => isShown(o) && o !== exclude && !o.contains(exclude ?? null) && o.getAttribute("aria-disabled") !== "true",
  );
  const i = pickOption(options.map((o) => o.innerText || o.textContent || ""), value);
  return i >= 0 ? options[i] : null;
}

/** Suggestions load over the network: keep looking for a while. */
async function waitForOption(value: string, exclude: HTMLElement, ms: number): Promise<HTMLElement | null> {
  for (let waited = 0; waited <= ms; waited += 250) {
    const option = findOption(value, exclude);
    if (option) return option;
    await sleep(250);
  }
  return null;
}

/** What to type into a search box: the first part of an address ("Austin" for
 * "Austin, Texas, United States") finds the place; the full answer then picks it. */
function searchQueries(value: string): string[] {
  const first = value.split(",")[0].trim();
  return first && first !== value.trim() ? [first, value.trim()] : [value.trim()];
}

/** Open a custom dropdown or a search-as-you-type picker and click the option for `value`. */
async function fillCombobox(el: HTMLElement, value: string): Promise<boolean> {
  const typeable = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
  dispatchClick(el);
  el.focus();
  let option = await waitForOption(value, el, typeable ? 300 : 900);
  if (!option && typeable) {
    for (const query of searchQueries(value)) {
      await typeIntoInput(el, query, 25, false);
      option = await waitForOption(value, el, 2500);
      if (!option) {
        // Workday's pickers search on Enter rather than as you type.
        key(el, "Enter");
        option = await waitForOption(value, el, 2000);
      }
      if (option) break;
    }
  }
  if (option) {
    option.scrollIntoView({ block: "nearest" });
    dispatchClick(option);
    await sleep(150);
    return true;
  }
  key(el, "Escape");
  if (typeable) setNativeValueRaw(el, "");
  return false;
}

/** A plain text box that may still offer suggestions (Google Places): type the answer,
 * then pick a matching suggestion if one shows up. Typed text stands if none does. */
async function fillLookupInput(el: HTMLInputElement, value: string): Promise<void> {
  await typeIntoInput(el, searchQueries(value)[0], 25, false);
  const option = await waitForOption(value, el, 1500);
  if (option) {
    dispatchClick(option);
    await sleep(150);
    return;
  }
  await typeIntoInput(el, value, 10);
}

export type FillResult = { filled: number; skipped: string[] };
export type FillProgress = { label: string; index: number; total: number };

/** Fields typed char-by-char (short, often masked: dates, phone, zip, names).
 * Everything else (long free text) is set in bulk for speed. */
function looksMasked(descriptorLabel: string, value: string): boolean {
  return value.length <= 40 || /date|phone|zip|postal|code/i.test(descriptorLabel);
}

export async function applyValues(
  fields: LiveField[],
  values: Record<string, { value: string; source?: string }>,
  answers: Record<string, string>,
  onProgress?: (progress: FillProgress) => void,
): Promise<FillResult> {
  const byKey = new Map(fields.map((f) => [f.descriptor.key, f]));
  let filled = 0;
  const skipped: string[] = [];
  const all: Record<string, string> = {};
  for (const [k, v] of Object.entries(values)) all[k] = v.value;
  for (const [k, v] of Object.entries(answers)) all[k] = v;

  // Sort by the field's vertical position so the fill visibly proceeds down
  // the page in the order the user would tab through it, one field at a time.
  const entries = Object.entries(all).filter(([k, v]) => byKey.has(k) && v);
  entries.sort(([ka], [kb]) => {
    const ra = byKey.get(ka)!.el.getBoundingClientRect().top;
    const rb = byKey.get(kb)!.el.getBoundingClientRect().top;
    return ra - rb;
  });

  let i = 0;
  for (const [key, value] of entries) {
    i += 1;
    const lf = byKey.get(key)!;
    const el: HTMLElement = lf.el;
    const label = lf.descriptor.label || lf.descriptor.name || "field";
    onProgress?.({ label, index: i, total: entries.length });
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    await sleep(120);

    let ok = false;
    try {
      if (isChoiceGroup(el)) {
        ok = fillChoiceGroup(el, value);
      } else if (el instanceof HTMLSelectElement) {
        ok = fillSelect(el, value);
      } else if (el instanceof HTMLInputElement && el.type === "checkbox") {
        ok = fillCheckbox(el, value);
      } else if (el instanceof HTMLInputElement && el.type === "radio") {
        ok = fillGroupByLabel(el, value);
      } else if (isComboboxTrigger(el)) {
        ok = await fillCombobox(el, value);
      } else if (el instanceof HTMLTextAreaElement) {
        setNativeValueRaw(el, value);
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
        ok = true;
      } else if (el instanceof HTMLInputElement) {
        if (LOOKUP_LABEL_RE.test(`${lf.descriptor.label} ${lf.descriptor.name} ${lf.descriptor.id}`)) {
          await fillLookupInput(el, value);
        } else if (looksMasked(lf.descriptor.label, value)) {
          await typeIntoInput(el, value);
        } else {
          setNativeValueRaw(el, value);
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.dispatchEvent(new Event("blur", { bubbles: true }));
        }
        ok = true;
      }
    } catch {
      // One awkward widget must not abandon the rest of the form.
      ok = false;
    }
    if (ok) {
      filled += 1;
      markField(lf.el, values[key]?.source || "profile");
    } else {
      skipped.push(label);
    }
    await sleep(90);
  }
  return { filled, skipped };
}

/** Nothing in it yet. Custom dropdowns count as blank until JobBot has filled them,
 * since their selected value lives outside the element. */
export function isBlankField(el: HTMLElement): boolean {
  if (el.hasAttribute("data-jobbot-filled")) return false;
  if (isChoiceGroup(el)) return !choiceItems(el).some(isChoiceSelected);
  if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
    const name = el.name;
    const group = name
      ? Array.from(rootOf(el).querySelectorAll<HTMLInputElement>(`input[name="${CSS.escape(name)}"]`))
      : [el];
    return !group.some((input) => input.checked);
  }
  if (el instanceof HTMLSelectElement) return el.selectedIndex <= 0 || !el.value;
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return !el.value.trim();
  return true;
}

/** The upload field for the resume. Most ATS forms hide the real file input behind
 * a styled button, so hidden ones count. With several uploads and no clear resume
 * field, returns null: better no attachment than a resume in the cover-letter slot. */
export function findResumeInput(): HTMLInputElement | null {
  const inputs = deepQueryAll<HTMLInputElement>('input[type="file"]').filter((el) => !el.disabled);
  if (inputs.length === 1) return inputs[0];
  return inputs.find((el) => isResumeUploadTarget(el)) ?? null;
}

// A file already listed by the upload widget: Workday's uploaded-file row, or any
// widget showing the file's name ("cory-stagg.pdf"). "(.pdf, .docx)" hints don't count.
const UPLOADED_MARKERS =
  '[data-automation-id*="file-upload-item" i], [data-automation-id*="file-upload-success" i], ' +
  '[data-automation-id*="delete-file" i], [data-automation-id="fileName"]';
const UPLOADED_FILE_RE = /[\p{L}\p{N}](?:[\p{L}\p{N}_\-() ]*[\p{L}\p{N}_\-)])?\.(pdf|docx?|rtf|odt|txt|pages)\b/iu;

/** The resume slot already holds a file (uploaded by the member, or on an earlier step,
 * e.g. Workday's "Autofill with Resume"). Uploading again would add a second copy. */
export function resumeAlreadyUploaded(input: HTMLInputElement): boolean {
  if (input.files?.length) return true;
  // The upload's own section: the largest nearby ancestor holding no other upload.
  let section: HTMLElement | null = null;
  for (let node = input.parentElement, depth = 0; node && depth < 5; node = node.parentElement, depth += 1) {
    if (node.querySelectorAll('input[type="file"]').length > 1) break;
    section = node;
  }
  if (!section) return false;
  if (section.querySelector(UPLOADED_MARKERS)) return true;
  return UPLOADED_FILE_RE.test(section.innerText || "");
}

/** Attach a resume file (as data URL) to this frame's resume upload field. */
export async function attachResume(dataUrl: string, filename: string): Promise<boolean> {
  const input = findResumeInput();
  if (!input) return false;
  const res = await fetch(dataUrl);
  const blob = await res.blob();
  const file = new File([blob], filename, {
    type: "application/pdf",
  });
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  markField(input, "resume");
  return true;
}
