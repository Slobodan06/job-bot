import { deepQueryAll, rootOf } from "../detectors/dom";
import { fieldGroup } from "./groups";
import type { FormField } from "../lib/types";

export type LiveField = { el: HTMLElement; descriptor: FormField };

const isVisible = (el: HTMLElement) => {
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
};

function labelFor(el: HTMLElement): string {
  // Labels almost always live in the same Document/ShadowRoot as their input —
  // search there first (correct for web-component forms), then fall back to a
  // full shadow-piercing sweep for label[for] wired across a boundary.
  const local = rootOf(el);
  const id = el.getAttribute("id");
  if (id) {
    const lbl =
      local.querySelector(`label[for="${CSS.escape(id)}"]`) ||
      deepQueryAll(`label[for="${CSS.escape(id)}"]`)[0];
    if (lbl) return (lbl as HTMLElement).innerText.trim();
  }
  const wrap = el.closest("label");
  if (wrap) return (wrap as HTMLElement).innerText.trim();
  const aria = el.getAttribute("aria-labelledby");
  if (aria) {
    const parts = aria
      .split(/\s+/)
      .map((x) => (local as Document | ShadowRoot).getElementById?.(x)?.innerText || "")
      .filter(Boolean);
    if (parts.length) return parts.join(" ").trim();
  }
  return nearbyLabel(el);
}

const LABELISH = "legend, label, [class*='label' i], [class*='question' i]";

/** The closest label-ish text before the field. Its own wrapper often holds only the
 * input (Lever's .application-field) with the label a level up, so look outward. */
function nearbyLabel(el: HTMLElement): string {
  for (let node = el.parentElement, depth = 0; node && depth < 4; node = node.parentElement, depth += 1) {
    const before = Array.from(node.querySelectorAll<HTMLElement>(LABELISH)).filter(
      (c) =>
        !c.contains(el) &&
        !c.querySelector("input, select, textarea") &&
        (c.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0 &&
        (c.innerText || "").trim(),
    );
    if (before.length) return before[before.length - 1].innerText.trim();
  }
  return "";
}

/** An option's own name: the first line of its label, without the explanation under it
 * ("Hispanic or Latino" + "A person of Cuban, Mexican, ... origin"). */
const firstLine = (text: string) =>
  text
    .split("\n")
    .map((t) => t.trim())
    .find(Boolean) || "";

/** Radios (and same-name checkboxes) are labelled by their answers; the question is
 * the text above the whole set ("Race", "Are you legally authorized to work...?"). */
function groupQuestion(el: HTMLInputElement): string {
  const name = el.getAttribute("name");
  const set = name
    ? Array.from(rootOf(el).querySelectorAll<HTMLInputElement>(`input[name="${CSS.escape(name)}"]`))
    : [el];
  if (set.length < 2 && el.type !== "radio") return "";
  let container = el.parentElement;
  while (container && !set.every((input) => container!.contains(input))) container = container.parentElement;
  // Step out of the answer's own <label> so the answers aren't read as the question.
  while (container && container.closest("label")) container = container.closest("label")!.parentElement;
  return container ? questionFor(container) : "";
}

function optionsFor(el: HTMLElement): string[] {
  if (el instanceof HTMLSelectElement) {
    return Array.from(el.options)
      .map((o) => o.text.trim())
      .filter((t) => t && !/^select|^--|^choose/i.test(t));
  }
  const name = el.getAttribute("name");
  if (name && (el as HTMLInputElement).type === "radio") {
    const root = rootOf(el);
    return Array.from(root.querySelectorAll(`input[type="radio"][name="${CSS.escape(name)}"]`))
      .map((r) => firstLine(labelFor(r as HTMLElement)))
      .filter(Boolean);
  }
  return [];
}

// Custom dropdown widgets (React-Select, MUI Select, Radix, Headless UI, ...)
// are frequently a <div>/<button> with no underlying native <select>/<input>
// at all — only an ARIA role gives them away.
const CUSTOM_DROPDOWN_SELECTOR = '[role="combobox"], [aria-haspopup="listbox"]';

// Choice widgets with no native inputs: Yes/No button pairs ("Are you legally
// authorized to work...? [Yes] [No]") and role="radiogroup" sets of role="radio" items.
const CHOICE_ATTR = "data-jobbot-choice";
const BUTTONISH = 'button:not([type="submit"]), [role="button"]';
const YES_RE = /^yes$/i;
const NO_RE = /^no$/i;

const textOf = (el: HTMLElement) => (el.innerText || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();

export const isChoiceGroup = (el: HTMLElement) => el.hasAttribute(CHOICE_ATTR);

export function choiceItems(group: HTMLElement): HTMLElement[] {
  const selector = group.getAttribute("role") === "radiogroup" ? '[role="radio"]' : BUTTONISH;
  return Array.from(group.querySelectorAll<HTMLElement>(selector)).filter(isVisible);
}

const SELECTED_CLASS_RE = /(^|[\s_-])(active|selected|checked)([\s_-]|$)/i;

export function isChoiceSelected(item: HTMLElement): boolean {
  return (
    ["aria-checked", "aria-pressed", "aria-selected"].some((a) => item.getAttribute(a) === "true") ||
    /^(checked|on|active)$/i.test(item.getAttribute("data-state") || "") ||
    SELECTED_CLASS_RE.test(typeof item.className === "string" ? item.className : "")
  );
}

function findChoiceGroups(root: ParentNode): HTMLElement[] {
  const out = new Set<HTMLElement>();
  for (const g of deepQueryAll<HTMLElement>('[role="radiogroup"]', root)) {
    const nativeRadios = Array.from(g.querySelectorAll<HTMLElement>('input[type="radio"]')).filter(isVisible);
    if (!nativeRadios.length && g.querySelector('[role="radio"]')) out.add(g);
  }
  for (const b of deepQueryAll<HTMLElement>(BUTTONISH, root)) {
    if (!YES_RE.test(textOf(b)) || !isVisible(b)) continue;
    // The smallest ancestor holding both answers: the Yes/No pair, nothing more.
    let node = b.parentElement;
    for (let depth = 0; depth < 3 && node; depth += 1, node = node.parentElement) {
      const items = Array.from(node.querySelectorAll<HTMLElement>(BUTTONISH)).filter(isVisible);
      if (items.length > 4) break;
      if (items.some((i) => NO_RE.test(textOf(i)))) {
        out.add(node);
        break;
      }
    }
  }
  return Array.from(out);
}

/** The question a set of answers belongs to: its ARIA label, else the text just above it. */
function questionFor(group: HTMLElement): string {
  const own = group.hasAttribute("aria-labelledby") ? labelFor(group) : group.getAttribute("aria-label") || "";
  if (own && !/^(yes|no)\b/i.test(own)) return own;
  for (let node: HTMLElement | null = group, depth = 0; node && depth < 4; node = node.parentElement, depth += 1) {
    for (let sib = node.previousElementSibling as HTMLElement | null; sib; sib = sib.previousElementSibling as HTMLElement | null) {
      const text = (sib.innerText || "").trim();
      if (text) return text.length <= 400 ? text : "";
    }
  }
  return nearbyLabel(group);
}

/** Styled radios and checkboxes hide the real input and show only its label. */
function hasVisibleLabel(el: HTMLElement, type: string): boolean {
  if (type !== "radio" && type !== "checkbox") return false;
  const id = el.getAttribute("id");
  const label =
    (id ? rootOf(el).querySelector<HTMLElement>(`label[for="${CSS.escape(id)}"]`) : null) ||
    el.closest<HTMLElement>("label");
  return !!label && isVisible(label);
}

let counter = 0;

function keyFor(el: HTMLElement): string {
  let key = el.dataset.jobbotKey;
  if (!key) {
    key = `jb${counter++}`;
    el.dataset.jobbotKey = key;
  }
  return key;
}

export function discoverFields(root: ParentNode = document): LiveField[] {
  const out: LiveField[] = [];
  const seen = new Set<HTMLElement>();
  const seenRadioNames = new Set<string>();
  // deepQueryAll pierces open shadow roots — required for Workday and other
  // web-component-based application forms where plain querySelectorAll finds
  // nothing at all.
  const els = deepQueryAll<HTMLElement>(
    `input, textarea, select, ${CUSTOM_DROPDOWN_SELECTOR}`,
    root,
  );
  for (const el of els) {
    if (seen.has(el)) continue;
    seen.add(el);
    const isFormEl = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement;
    const type = isFormEl ? (el.getAttribute("type") || el.tagName).toLowerCase() : "combobox";
    // File inputs aren't text to fill: the resume goes in via attachResume.
    if (["hidden", "submit", "button", "reset", "image", "search", "file"].includes(type)) continue;
    if (el instanceof HTMLInputElement && el.disabled) continue;
    if (!isFormEl && el.getAttribute("aria-disabled") === "true") continue;
    if (!isVisible(el) && !hasVisibleLabel(el, type)) continue;
    if (type === "radio") {
      const name = el.getAttribute("name") || "";
      if (seenRadioNames.has(name)) continue;
      seenRadioNames.add(name);
    }
    const group = fieldGroup(el);
    out.push({
      el,
      descriptor: {
        key: keyFor(el),
        label: (
          (type === "radio" || type === "checkbox" ? groupQuestion(el as HTMLInputElement) : "") || labelFor(el)
        ).slice(0, 500),
        name: el.getAttribute("name") || "",
        id: el.getAttribute("id") || "",
        type: el instanceof HTMLTextAreaElement ? "textarea" : type,
        placeholder: el.getAttribute("placeholder") || "",
        autocomplete: el.getAttribute("autocomplete") || "",
        aria_label: el.getAttribute("aria-label") || "",
        required:
          el.hasAttribute("required") || el.getAttribute("aria-required") === "true",
        options: optionsFor(el),
        group_kind: group.kind,
        group_index: group.index,
      },
    });
  }
  for (const el of findChoiceGroups(root)) {
    if (!isVisible(el)) continue;
    el.setAttribute(CHOICE_ATTR, "1");
    const group = fieldGroup(el);
    const question = questionFor(el);
    out.push({
      el,
      descriptor: {
        key: keyFor(el),
        label: question.slice(0, 500),
        name: "",
        id: el.getAttribute("id") || "",
        type: "radio",
        placeholder: "",
        autocomplete: "",
        aria_label: el.getAttribute("aria-label") || "",
        required: el.getAttribute("aria-required") === "true" || /\*\s*$/.test(question),
        options: choiceItems(el).map(textOf).filter(Boolean),
        group_kind: group.kind,
        group_index: group.index,
      },
    });
  }
  return out;
}
