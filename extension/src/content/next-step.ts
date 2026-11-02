/**
 * Multi-step application forms: find the control that moves to the next step,
 * and click it only after the member confirms in the overlay. The final
 * Submit is never clicked: the member always sends the application themselves.
 */
import { deepQueryAll } from "../detectors/dom";
import { isFinalSubmitControl } from "./submission";

const CLICKABLE = 'button, input[type="submit"], input[type="button"], [role="button"], a';
const NEXT_RE = /^(next( step| page)?|continue|save (and|&) continue|save (and|&) next|proceed)\b/i;

function labelOf(el: Element): string {
  const text =
    (el as HTMLElement).innerText ||
    (el instanceof HTMLInputElement ? el.value : "") ||
    el.getAttribute("aria-label") ||
    "";
  return text.replace(/\s+/g, " ").trim();
}

function isShown(el: Element): boolean {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
}

function isDisabled(el: Element): boolean {
  return (el as HTMLButtonElement).disabled || el.getAttribute("aria-disabled") === "true";
}

/** This frame's "Next" / "Continue" control, if it has one. */
export function findNextControl(): HTMLElement | null {
  for (const el of deepQueryAll<HTMLElement>(CLICKABLE)) {
    const label = labelOf(el);
    if (label.length > 40 || !NEXT_RE.test(label)) continue;
    if (!isShown(el) || isFinalSubmitControl(el)) continue;
    return el;
  }
  return null;
}

export type NextClick = "clicked" | "disabled" | "none";

/** Click this frame's Next control. Called only after the member pressed Proceed. */
export function clickNextInThisFrame(): NextClick {
  const el = findNextControl();
  if (!el) return "none";
  // A required field still empty often keeps Next disabled.
  if (isDisabled(el)) return "disabled";
  el.scrollIntoView({ block: "center" });
  el.click();
  return "clicked";
}
