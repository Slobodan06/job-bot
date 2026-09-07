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
  // Nearest preceding heading/label-ish text within the field's group.
  const group = el.closest("fieldset, .field, [class*='field'], [class*='question'], div");
  const q = group?.querySelector("legend, label, [class*='label'], [class*='question']");
  if (q && !q.contains(el)) return (q as HTMLElement).innerText.trim();
  return "";
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
      .map((r) => labelFor(r as HTMLElement))
      .filter(Boolean);
  }
  return [];
}

// Custom dropdown widgets (React-Select, MUI Select, Radix, Headless UI, ...)
// are frequently a <div>/<button> with no underlying native <select>/<input>
// at all — only an ARIA role gives them away.
const CUSTOM_DROPDOWN_SELECTOR = '[role="combobox"], [aria-haspopup="listbox"]';

let counter = 0;

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
    if (["hidden", "submit", "button", "reset", "image", "search"].includes(type)) continue;
    if (el instanceof HTMLInputElement && el.disabled) continue;
    if (!isFormEl && el.getAttribute("aria-disabled") === "true") continue;
    if (!isVisible(el)) continue;
    if (type === "radio") {
      const name = el.getAttribute("name") || "";
      if (seenRadioNames.has(name)) continue;
      seenRadioNames.add(name);
    }
    let key = el.dataset.jobbotKey;
    if (!key) {
      key = `jb${counter++}`;
      el.dataset.jobbotKey = key;
    }
    const group = fieldGroup(el);
    out.push({
      el,
      descriptor: {
        key,
        label: labelFor(el).slice(0, 500),
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
  return out;
}
