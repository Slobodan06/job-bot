/**
 * Detects which numbered repeated block ("Work Experience 1", "Work
 * Experience 2", "Education 1", ...) a field lives in. Workday and several
 * other ATS's ask Company/Job Title/Location/From/To/Description once PER
 * EMPLOYER rather than a single "current employer" question — each
 * occurrence has to map to a different entry in the resume, in order.
 */

const HEADING_SELECTOR = 'h1,h2,h3,h4,h5,legend,[class*="heading" i],[data-automation-id*="panelHeader" i]';
const EXPERIENCE_RE = /\b(?:work\s*experience|employment(?:\s*history)?|position)\D{0,15}(\d+)\b/i;
const EDUCATION_RE = /\beducation\D{0,15}(\d+)\b/i;

export type FieldGroup = { kind: "experience" | "education" | ""; index: number | null };

function headingNumber(container: HTMLElement, pattern: RegExp): number | null {
  for (const h of Array.from(container.querySelectorAll<HTMLElement>(HEADING_SELECTOR))) {
    const text = h.innerText || h.textContent || "";
    const m = pattern.exec(text);
    if (m) return parseInt(m[1], 10);
  }
  return null;
}

/** Walk outward from `el` until an ancestor's subtree contains a matching
 * numbered heading — the smallest such ancestor is that entry's own panel. */
export function fieldGroup(el: HTMLElement): FieldGroup {
  let node: HTMLElement | null = el;
  for (let depth = 0; depth < 12 && node; depth += 1, node = node.parentElement) {
    const expNum = headingNumber(node, EXPERIENCE_RE);
    if (expNum != null) return { kind: "experience", index: Math.max(0, expNum - 1) };
    const eduNum = headingNumber(node, EDUCATION_RE);
    if (eduNum != null) return { kind: "education", index: Math.max(0, eduNum - 1) };
  }
  return { kind: "", index: null };
}
