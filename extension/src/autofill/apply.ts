import { deepQueryAll, rootOf } from "../detectors/dom";
import type { LiveField } from "./fields";
import { markField } from "./highlight";

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
): Promise<void> {
  el.focus();
  setNativeValueRaw(el, "");
  for (const ch of value) {
    setNativeValueRaw(el, el.value + ch);
    el.dispatchEvent(new InputEvent("input", { bubbles: true, data: ch, inputType: "insertText" }));
    if (perCharDelayMs) await sleep(perCharDelayMs);
  }
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new Event("blur", { bubbles: true }));
}

/** Match a radio group, or a multi-checkbox group sharing a `name`, by label text. */
function fillGroupByLabel(el: HTMLInputElement, value: string): boolean {
  const name = el.getAttribute("name");
  const root = rootOf(el);
  const group = name
    ? Array.from(root.querySelectorAll<HTMLInputElement>(`input[name="${CSS.escape(name)}"]`))
    : [el];
  const want = value.trim().toLowerCase();
  for (const radio of group) {
    const lbl = (
      root.querySelector(`label[for="${CSS.escape(radio.id)}"]`)?.textContent ||
      radio.closest("label")?.textContent ||
      radio.value ||
      ""
    )
      .trim()
      .toLowerCase();
    if (lbl === want || (want && (lbl.includes(want) || want.includes(lbl)))) {
      radio.checked = true;
      radio.dispatchEvent(new Event("input", { bubbles: true }));
      radio.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
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
  const shouldCheck = AFFIRMATIVE_RE.test(v);
  if (el.checked !== shouldCheck) {
    el.checked = shouldCheck;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  return true;
}

function fillSelect(el: HTMLSelectElement, value: string): boolean {
  const want = value.trim().toLowerCase();
  for (const opt of Array.from(el.options)) {
    if (opt.text.trim().toLowerCase() === want || opt.value.trim().toLowerCase() === want) {
      el.value = opt.value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  for (const opt of Array.from(el.options)) {
    const t = opt.text.trim().toLowerCase();
    if (want && (t.includes(want) || want.includes(t))) {
      el.value = opt.value;
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
  }
  return false;
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
    !!el.closest('[role="combobox"]')
  );
}

function dispatchClick(el: HTMLElement): void {
  for (const type of ["pointerdown", "mousedown", "mouseup", "click"]) {
    el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
  }
}

function findOption(value: string): HTMLElement | null {
  const want = value.trim().toLowerCase();
  if (!want) return null;
  const candidates = deepQueryAll<HTMLElement>(
    '[role="option"], li[role="option"], [role="listbox"] li, [class*="option" i]',
  );
  let exact: HTMLElement | null = null;
  let partial: HTMLElement | null = null;
  for (const opt of candidates) {
    const text = (opt.innerText || opt.textContent || "").trim().toLowerCase();
    if (!text) continue;
    if (text === want) {
      exact = opt;
      break;
    }
    if (!partial && (text.includes(want) || want.includes(text))) partial = opt;
  }
  return exact || partial;
}

/** Open a custom combobox/listbox widget and click the option matching `value`. */
async function fillCombobox(el: HTMLElement, value: string): Promise<boolean> {
  dispatchClick(el);
  await sleep(220);
  let option = findOption(value);
  if (!option && (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) {
    // Searchable/filterable combobox: type the value to filter the option list.
    await typeIntoInput(el, value, 15);
    await sleep(280);
    option = findOption(value);
  }
  if (option) {
    dispatchClick(option);
    await sleep(60);
    return true;
  }
  document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  return false;
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
    onProgress?.({ label: lf.descriptor.label || lf.descriptor.name || "field", index: i, total: entries.length });
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    await sleep(120);

    let ok = false;
    if (el instanceof HTMLSelectElement) {
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
      if (looksMasked(lf.descriptor.label, value)) {
        await typeIntoInput(el, value);
      } else {
        setNativeValueRaw(el, value);
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
      }
      ok = true;
    }
    if (ok) {
      filled += 1;
      markField(lf.el, values[key]?.source || "ai");
    } else {
      skipped.push(lf.descriptor.label || lf.descriptor.name || key);
    }
    await sleep(90);
  }
  return { filled, skipped };
}

/** Attach a resume file (as data URL) to the first file input that wants a resume/CV. */
export async function attachResume(
  fields: LiveField[],
  dataUrl: string,
  filename: string,
): Promise<boolean> {
  const target = fields.find(
    (f) =>
      f.el instanceof HTMLInputElement &&
      f.el.type === "file" &&
      /resume|cv|attach|upload/i.test(
        `${f.descriptor.label} ${f.descriptor.name} ${f.descriptor.id}`,
      ),
  );
  const input = (target?.el as HTMLInputElement) ??
    (document.querySelector('input[type="file"]') as HTMLInputElement | null);
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
  if (target) markField(target.el, "resume");
  return true;
}
