/**
 * Presentational parsing only — improves layout/copy UX from plain API strings.
 */

function norm(s: string): string {
  return s.replace(/\u00A0/g, " ").replace(/[\u2010-\u2015]/g, "-").trim();
}

function isBulletLine(line: string): boolean {
  const s = norm(line);
  if (!s) return false;
  return (
    /^[•\-\*●▪▫‣⁃○◦‧]/.test(s) ||
    /^\[[ xX]\]\s/.test(s) ||
    (/^[-–—]\s+\S/.test(s) && !/^\d{1,2}\/\d{4}/.test(s))
  );
}

function isDateLine(line: string): boolean {
  const s = norm(line);
  return /^\d{1,2}\/\d{4}\s*[-–—]\s*(?:\d{1,2}\/\d{4}|Present|Current)$/i.test(s);
}

/** Single-line geography — keep strict so multi-word job titles are never mistaken for locations. */
function isLikelyLocationOnly(line: string): boolean {
  const s = norm(line).toLowerCase();
  if (!s || s.length > 48) return false;
  const oneLiners = new Set([
    "united states",
    "usa",
    "uk",
    "u.k.",
    "u.s.",
    "canada",
    "india",
    "remote",
    "hybrid",
    "serbia",
    "germany",
    "france",
    "australia",
    "netherlands",
    "singapore",
    "spain",
    "italy",
    "poland",
    "brazil",
    "mexico",
    "japan",
    "china",
  ]);
  if (oneLiners.has(s)) return true;
  /* "City, ST" / "City, Country" short geography lines */
  if (/^[a-z][a-z\s\-]{1,28},\s*[a-z]{2,}(\s+[a-z]+)?$/i.test(s) && s.length <= 36) return true;
  return false;
}

function looksLikeJobTitleLine(line: string): boolean {
  const s = norm(line);
  if (!s || s.length < 8) return false;
  if (isBulletLine(line) || isDateLine(line)) return false;
  if (isLikelyLocationOnly(line)) return false;
  /* All-caps section headers */
  if (/^[A-Z0-9 &/]{8,}$/.test(s) && !/[a-z]/.test(s) && !/\//.test(s)) return false;

  const roleHints =
    /\b(engineer|engineering|developer|scientist|architect|designer|analyst|consultant|specialist|manager|director|lead|head|principal|staff|associate|intern|programmer|devops|program|officer|coordinator|executive|vp|cto|cio|full[-\s]?stack|front[-\s]?end|back[-\s]?end|software|platform|data|product|ux|ui|machine learning|ml|ai)\b/i;
  if (roleHints.test(s)) return true;
  if (s.length >= 14 && (/[/]|(\s\/\s)|\s&\s|,\s*[A-Za-z]/.test(s) || /\b(and|\/)\b/i.test(s))) return true;
  return s.length >= 28;
}

function looksLikeCompanyLine(line: string): boolean {
  const s = norm(line);
  if (!s || isBulletLine(line) || isDateLine(line)) return false;
  if (s.length > 96) return false;
  return true;
}

/**
 * Detect "Job title / Company / (bullet | date)" — common when PDF extraction removes blank lines between roles.
 */
function isJobHeaderTriple(lines: string[], titleIdx: number): boolean {
  if (!looksLikeJobTitleLine(lines[titleIdx] ?? "")) return false;

  let j = titleIdx + 1;
  while (j < lines.length && !norm(lines[j] ?? "")) j += 1;
  if (j >= lines.length || !looksLikeCompanyLine(lines[j] ?? "")) return false;

  let k = j + 1;
  while (k < lines.length && !norm(lines[k] ?? "")) k += 1;
  if (k >= lines.length) return false;

  const third = lines[k] ?? "";
  if (isBulletLine(third) || isDateLine(third)) return true;
  if (isLikelyLocationOnly(third)) {
    let m = k + 1;
    while (m < lines.length && !norm(lines[m] ?? "")) m += 1;
    const fourth = lines[m] ?? "";
    return isBulletLine(fourth) || isDateLine(fourth);
  }
  return false;
}

function splitExperienceByJobHeaders(lines: string[]): string[] {
  const starts: number[] = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (!norm(lines[i] ?? "")) continue;
    if (!isJobHeaderTriple(lines, i)) continue;
    starts.push(i);
  }
  if (starts.length <= 1) return [];

  const blocks: string[] = [];
  for (let b = 0; b < starts.length; b += 1) {
    const from = starts[b]!;
    const to = b + 1 < starts.length ? starts[b + 1]! : lines.length;
    let slice = lines.slice(from, to);
    if (b === 0 && from > 0) slice = [...lines.slice(0, from), ...slice];
    blocks.push(slice.join("\n").trim());
  }
  return blocks.filter(Boolean);
}

/** Presentational metadata for one experience block (plain text from PDF). */
export type ExperienceCardMeta = {
  titleLine: string;
  companyLine?: string;
  periodLine?: string;
  locationLine?: string;
  /** Body text for the scroll area (without repeating title/company when shown above). */
  detailBody: string;
};

/** Pull title / company / date / location out so each role is easy to scan and copy. */
export function parseExperienceCardMeta(block: string): ExperienceCardMeta {
  const raw = block.split(/\r?\n/);
  const n = raw.map((l) => norm(l));
  let i = 0;
  while (i < n.length && !n[i]) i += 1;
  const titleLine = n[i] ?? "";
  i += 1;
  while (i < n.length && !n[i]) i += 1;

  let companyLine: string | undefined;
  if (
    i < n.length &&
    n[i] &&
    !isBulletLine(raw[i]!) &&
    !isDateLine(raw[i]!) &&
    !isLikelyLocationOnly(raw[i]!) &&
    looksLikeCompanyLine(raw[i]!)
  ) {
    companyLine = n[i];
    i += 1;
  }

  let periodLine: string | undefined;
  let locationLine: string | undefined;
  for (let k = i; k < n.length; k += 1) {
    if (!n[k]) continue;
    if (isDateLine(raw[k]!)) {
      periodLine = n[k];
      const nextLn = raw[k + 1];
      if (nextLn !== undefined && n[k + 1] && isLikelyLocationOnly(nextLn)) {
        locationLine = n[k + 1];
      }
      break;
    }
  }

  let detailLines = raw.slice(i);
  const drop = new Set<string>();
  if (periodLine) drop.add(periodLine);
  if (locationLine) drop.add(locationLine);
  if (drop.size > 0) {
    detailLines = detailLines.filter((l) => {
      const t = norm(l);
      if (!t) return true;
      return !drop.has(t);
    });
  }
  const detailBody = detailLines.join("\n").trim();

  return {
    titleLine,
    companyLine,
    periodLine,
    locationLine,
    detailBody,
  };
}

/** Split experience into separate roles when blank lines, date leads, or title/company/bullet patterns separate entries. */
export function splitExperienceBlocks(raw: string): string[] {
  const t = raw.trim();
  if (!t) return [];

  const blocks = t
    .split(/\n\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean);

  if (blocks.length > 1) return blocks;

  const blob = blocks[0] ?? t;
  const lines = blob.split(/\r?\n/);

  const byHeaders = splitExperienceByJobHeaders(lines);
  if (byHeaders.length > 1) return byHeaders;

  const dateLead =
    /\n(?=\s*\d{1,2}\/\d{4}\s*[\u2013\u2014\-]\s*(?:\d{1,2}\/\d{4}|Present|Current))/gi;
  const splitDate = blob.split(dateLead).map((s) => s.trim()).filter(Boolean);
  if (splitDate.length > 1) return splitDate;

  return [blob];
}

/** Separate offline "Posting-aligned terms..." suffix from main skills prose. */
export function splitSkillsParts(raw: string): { body: string; postingHint?: string } {
  const t = raw.trim();
  if (!t) return { body: "" };

  const idx = t.search(/\bPosting-aligned terms\b/i);
  if (idx === -1) return { body: t };
  if (idx === 0) return { body: "", postingHint: t };

  let body = t.slice(0, idx).trim();
  body = body.replace(/\.\s*$/, "").trim();
  const postingHint = t.slice(idx).trim();
  return { body, postingHint };
}

/**
 * Split "Frontend: React… Backend: Node…" style prose into labeled segments.
 * Returns [] when there are no `Label:` patterns (caller shows plain paragraph).
 */
export function segmentLabeledSkills(body: string): Array<{ label: string; text: string }> {
  const t = body.trim();
  if (!t) return [];

  /* Category labels usually start with a capital (Frontend:, AI & Data:). */
  const re = /\b([A-Z][A-Za-z0-9 &/+.\-\(\)]{1,52}):\s+/g;
  const matches = [...t.matchAll(re)];
  if (matches.length === 0) return [];

  const out: Array<{ label: string; text: string }> = [];
  const firstIdx = matches[0]!.index!;
  if (firstIdx > 0) {
    const preamble = t.slice(0, firstIdx).trim();
    if (preamble) out.push({ label: "Overview", text: preamble.replace(/\s+/g, " ") });
  }
  for (let i = 0; i < matches.length; i += 1) {
    const m = matches[i]!;
    const label = m[1]!.trim();
    if (label.length < 2) continue;
    const start = m.index! + m[0].length;
    const end = i + 1 < matches.length ? matches[i + 1]!.index! : t.length;
    const text = t.slice(start, end).trim().replace(/\s+/g, " ");
    out.push({ label, text });
  }
  return out;
}
