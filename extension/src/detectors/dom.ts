/**
 * Shadow-DOM-piercing DOM queries.
 *
 * Modern ATS UIs (Workday's candidate apply flow especially, and increasingly
 * others) render their form fields and job content inside open shadow roots
 * via web components. Plain `document.querySelectorAll` never sees into those
 * — these helpers walk every open shadow root so detection and autofill work
 * the same way regardless of how the page is built.
 */

const MAX_DEPTH = 8;

function walkRoots(root: ParentNode, depth: number, visit: (root: ParentNode) => void): void {
  visit(root);
  if (depth >= MAX_DEPTH) return;
  const all = root.querySelectorAll("*");
  for (const el of Array.from(all)) {
    const sr = (el as HTMLElement).shadowRoot;
    if (sr) walkRoots(sr, depth + 1, visit);
  }
}

export function deepQueryAll<T extends Element = HTMLElement>(
  selector: string,
  root: ParentNode = document,
): T[] {
  const out: T[] = [];
  walkRoots(root, 0, (r) => out.push(...Array.from(r.querySelectorAll<T>(selector))));
  return out;
}

export function deepQuery<T extends Element = HTMLElement>(
  selector: string,
  root: ParentNode = document,
): T | null {
  let found: T | null = null;
  walkRoots(root, 0, (r) => {
    if (!found) found = r.querySelector<T>(selector);
  });
  return found;
}

export function deepText(selector: string, root: ParentNode = document): string {
  const el = deepQuery<HTMLElement>(selector, root);
  return (el?.innerText || el?.textContent || "").trim();
}

/** The Document or ShadowRoot an element actually lives in (for local label/name lookups). */
export function rootOf(el: Element): ParentNode {
  const root = el.getRootNode();
  return root instanceof ShadowRoot || root instanceof Document ? root : document;
}
