/**
 * Choosing the right option for an answer, shared by every kind of picker: native
 * <select>, radio groups, Yes/No button groups, dropdowns and search-as-you-type lists.
 * Forms word the same answer many ways ("TX" / "Texas", "USA" / "United States",
 * "Alaskan Native" / "Alaska Native"), so options are scored, not compared verbatim.
 */

const US_STATES: Record<string, string> = {
  al: "alabama", ak: "alaska", az: "arizona", ar: "arkansas", ca: "california", co: "colorado",
  ct: "connecticut", de: "delaware", fl: "florida", ga: "georgia", hi: "hawaii", id: "idaho",
  il: "illinois", in: "indiana", ia: "iowa", ks: "kansas", ky: "kentucky", la: "louisiana",
  me: "maine", md: "maryland", ma: "massachusetts", mi: "michigan", mn: "minnesota",
  ms: "mississippi", mo: "missouri", mt: "montana", ne: "nebraska", nv: "nevada",
  nh: "new hampshire", nj: "new jersey", nm: "new mexico", ny: "new york", nc: "north carolina",
  nd: "north dakota", oh: "ohio", ok: "oklahoma", or: "oregon", pa: "pennsylvania",
  ri: "rhode island", sc: "south carolina", sd: "south dakota", tn: "tennessee", tx: "texas",
  ut: "utah", vt: "vermont", va: "virginia", wa: "washington", wv: "west virginia",
  wi: "wisconsin", wy: "wyoming", dc: "district of columbia",
};
const COUNTRY_ALIASES: Record<string, string> = {
  usa: "united states", us: "united states", "united states of america": "united states",
  uk: "united kingdom", "great britain": "united kingdom", uae: "united arab emirates",
};
const FILLER_WORDS = new Set(["or", "and", "other", "the", "a", "of"]);
export const DECLINE_RE = /decline|prefer not|(do not|don'?t) (wish|want)|choose not/i;

export const normalize = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

/** Normalized, with abbreviations spelled out, so "Austin, TX, USA" equals "Austin, Texas, United States". */
function canonical(s: string): string {
  const parts = s.split(",").map((p) => normalize(p)).filter(Boolean);
  return parts
    .map((p) => COUNTRY_ALIASES[p] ?? US_STATES[p] ?? p)
    .join(" ");
}

/** Whole-word containment, so "male" never matches the option "Female". */
export function hasWords(text: string, words: string): boolean {
  if (!words) return false;
  const escaped = words.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^\\p{L}\\p{N}])${escaped}($|[^\\p{L}\\p{N}])`, "u").test(text);
}

/**
 * How well an option's text answers `value`: 3 same answer, 2 one contains the other
 * as whole words, 1 every meaningful word of the answer starts a word of the option,
 * 0 no match. Options far longer than the answer are a wrapper around a whole list.
 */
export function optionScore(optionText: string, value: string): number {
  // Workday-style suffixes: "White (Not Hispanic or Latino) (United States of America)".
  const bare = optionText.replace(/\([^)]*\)/g, " ").trim();
  const full = textScore(optionText, value);
  return bare && bare !== optionText.trim() ? Math.max(full, textScore(bare, value)) : full;
}

function textScore(optionText: string, value: string): number {
  const want = canonical(value);
  const text = canonical(optionText);
  if (!want || !text) return 0;
  if (text.length > Math.max(want.length * 2, want.length + 40)) return 0;
  if (text === want) return 3;
  if (hasWords(text, want) || hasWords(want, text)) return 2;
  const wantWords = want.split(" ").filter((w) => !FILLER_WORDS.has(w));
  const words = text.split(" ");
  if (wantWords.length && wantWords.every((w) => words.some((t) => t.startsWith(w)))) return 1;
  return 0;
}

/** What to choose: the answer, other acceptable wordings of it, and whether it is a
 * yes/no-type survey answer ("I am not a protected veteran") that may be matched by meaning. */
export type Answer = { value: string; alternatives?: string[]; polar?: boolean };

const NEGATIVE_RE = /\b(no|not|non|none)\b|n't\b/i;
const PLACEHOLDER_RE = /^\s*(select|choose|--|please select)/i;
const MIXED_RE = /\bbut\b/i;

/** Index of the option for `answer`: by wording first (answer, then alternatives), then,
 * for yes/no-type survey answers, the option saying the same thing ("I am not a veteran"
 * for "I am not a protected veteran"), preferring the one sharing the most words. */
export function pickAnswer(texts: string[], answer: string | Answer): number {
  const a = typeof answer === "string" ? { value: answer } : answer;
  for (const value of [a.value, ...(a.alternatives || [])]) {
    // Loose word matches mislead on survey answers: "I am not a protected veteran"
    // shares every word with "I am a veteran but not a protected veteran".
    const i = pickOption(texts, value, !a.polar);
    if (i >= 0) return i;
  }
  if (!a.polar || DECLINE_RE.test(a.value)) return -1;
  const negative = NEGATIVE_RE.test(a.value);
  const wantWords = new Set(normalize(a.value).split(" "));
  let best = -1;
  let bestOverlap = -1;
  texts.forEach((t, i) => {
    if (!t.trim() || t.length > 160 || PLACEHOLDER_RE.test(t) || DECLINE_RE.test(t)) return;
    // "I am a veteran but not a protected veteran" says both things: never a match by meaning.
    if (MIXED_RE.test(t)) return;
    if (NEGATIVE_RE.test(t) !== negative) return;
    const overlap = normalize(t)
      .split(" ")
      .filter((w) => wantWords.has(w)).length;
    if (overlap > bestOverlap) {
      best = i;
      bestOverlap = overlap;
    }
  });
  return best;
}

/** Index of the best option for `value`, or -1. A score-1 (close) match counts only
 * when it is the only one; "decline" answers take whatever the form calls declining. */
export function pickOption(texts: string[], value: string, allowClose = true): number {
  let best = -1;
  let bestScore = 0;
  let closeCount = 0;
  texts.forEach((t, i) => {
    const score = optionScore(t, value);
    if (score === 1) closeCount += 1;
    // Ties go to the shorter option: "Austin, Texas" over "Austin, Texas Metro Area".
    if (score > bestScore || (score === bestScore && score > 0 && t.length < texts[best].length)) {
      best = i;
      bestScore = score;
    }
  });
  if (bestScore >= 2 || (allowClose && bestScore === 1 && closeCount === 1)) return best;
  if (DECLINE_RE.test(value)) {
    const decline = texts.findIndex((t) => t.length < 120 && DECLINE_RE.test(t));
    if (decline >= 0) return decline;
  }
  return -1;
}
