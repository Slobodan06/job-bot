/**
 * Gmail status tracking. On mail.google.com (top frame only) this reads the
 * job emails visible in the member's own Gmail tab — inbox rows (sender,
 * subject, snippet) and opened messages (full text) — and hands them to the
 * background, which sends them to JobBot. The server classifies each one
 * (application received / assessment / interview / offer / rejection) and moves
 * the matching tracked application forward.
 *
 * Only emails that look job-related leave the browser, each is sent once, and
 * the member can switch this off in the extension popup.
 */
import { bg, type EmailSignal } from "../lib/messaging";

const SCAN_DEBOUNCE_MS = 2500;
const SCAN_INTERVAL_MS = 30_000;
const BATCH = 40;

// Keep in sync with looks_job_related() in backend/app/applications/email_tracking.py.
const ATS_SENDER_RE =
  /greenhouse|lever\.co|hire\.lever|workday|myworkday|ashbyhq|smartrecruiters|workable|icims|jobvite|bamboohr|breezy|recruitee|teamtailor|jazzhr|applytojob|successfactors|taleo|rippling|gem\.com|dover|wellfound|hackerrank|codility|codesignal|testgorilla|hirevue/i;
const JOB_TEXT_RE =
  /\b(?:appl(?:y|ied|ying|ication)s?|candidacy|candidate|interview\w*|assessment|coding (?:challenge|test|exercise)|take[- ]home|online test|offer|unfortunately|regret|moving forward|move forward|next steps?|recruit\w*|hiring|talent (?:acquisition|team)|position|opportunity|role)\b/i;

function looksJobRelated(e: EmailSignal): boolean {
  return ATS_SENDER_RE.test(e.from_email) || JOB_TEXT_RE.test(`${e.from_name} ${e.subject} ${e.snippet}`);
}

function clean(text: string | null | undefined, max: number): string {
  return (text || "").replace(/[​-‏  ]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
}

/** Gmail's hover titles look like "Sat, Oct 18, 2026, 10:42 AM". */
function parseGmailDate(title: string | null | undefined): string | null {
  const text = clean(title, 80);
  if (!text) return null;
  const t = Date.parse(text.replace(/,(\s*\d{1,2}:\d{2})/, "$1"));
  return Number.isNaN(t) ? null : new Date(t).toISOString();
}

function hash(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

/** Conversation list rows (Inbox, labels, search results). */
function readRows(): EmailSignal[] {
  const out: EmailSignal[] = [];
  document.querySelectorAll<HTMLTableRowElement>('div[role="main"] tr.zA').forEach((row) => {
    const sender = row.querySelector<HTMLElement>(".yW span[email], .yX span[email]");
    const subject = clean(row.querySelector(".bog")?.textContent, 500);
    const snippet = clean(row.querySelector(".y2")?.textContent, 1000).replace(/^[-–]\s*/, "");
    if (!sender || !subject) return;
    const dateTitle = row.querySelector(".xW span[title], td.xW [title]")?.getAttribute("title");
    const thread =
      row.querySelector("[data-legacy-thread-id]")?.getAttribute("data-legacy-thread-id") ||
      row.querySelector("[data-thread-id]")?.getAttribute("data-thread-id") ||
      "";
    out.push({
      key: `row:${thread}:${hash(`${subject}|${snippet}|${dateTitle || ""}`)}`,
      from_name: clean(sender.getAttribute("name") || sender.textContent, 200),
      from_email: clean(sender.getAttribute("email"), 200),
      subject,
      snippet,
      body: "",
      received_at: parseGmailDate(dateTitle),
    });
  });
  return out;
}

/** Expanded messages of the open conversation (full text). */
function readOpenMessages(): EmailSignal[] {
  const subject = clean(document.querySelector("h2.hP")?.textContent, 500);
  if (!subject) return [];
  const out: EmailSignal[] = [];
  document.querySelectorAll<HTMLElement>('div[role="main"] div.adn').forEach((msg) => {
    const body = msg.querySelector<HTMLElement>(".a3s");
    const sender = msg.querySelector<HTMLElement>(".gD[email]");
    if (!body || !sender) return;
    const text = clean(body.innerText, 8000);
    if (!text) return;
    const id = msg.getAttribute("data-legacy-message-id") || msg.getAttribute("data-message-id") || "";
    const dateTitle = msg.querySelector(".g3[title]")?.getAttribute("title");
    out.push({
      key: `msg:${id || hash(`${subject}|${sender.getAttribute("email")}|${dateTitle || ""}|${text.slice(0, 300)}`)}`,
      from_name: clean(sender.getAttribute("name") || sender.textContent, 200),
      from_email: clean(sender.getAttribute("email"), 200),
      subject,
      snippet: text.slice(0, 300),
      body: text,
      received_at: parseGmailDate(dateTitle),
    });
  });
  return out;
}

function showToast(lines: string[]): void {
  const box = document.createElement("div");
  box.style.cssText =
    "position:fixed;right:20px;bottom:20px;z-index:2147483647;max-width:340px;padding:10px 14px;" +
    "border-radius:10px;background:#1a1b1e;color:#e9ecef;font:13px/1.45 system-ui;" +
    "box-shadow:0 6px 24px rgba(0,0,0,.35);border-left:4px solid #20c997";
  const title = document.createElement("strong");
  title.textContent = "JobBot tracker updated";
  title.style.cssText = "display:block;color:#20c997;margin-bottom:2px";
  box.appendChild(title);
  for (const line of lines.slice(0, 4)) {
    const row = document.createElement("div");
    row.textContent = line;
    box.appendChild(row);
  }
  document.body.appendChild(box);
  window.setTimeout(() => box.remove(), 8000);
}

const STATUS_LABEL: Record<string, string> = {
  submitted: "Submitted",
  assessment: "Assessment",
  interviewing: "Interviewing",
  offer: "Offer",
  rejected: "Rejected",
};

export function initGmailTracking(): void {
  if (window.top !== window.self || location.hostname !== "mail.google.com") return;

  const sent = new Set<string>(); // this page load; the background remembers across loads
  let timer: number | undefined;
  let busy = false;

  const scan = async () => {
    if (busy) return;
    busy = true;
    try {
      const fresh = [...readRows(), ...readOpenMessages()].filter((e) => !sent.has(e.key) && looksJobRelated(e));
      for (let i = 0; i < fresh.length; i += BATCH) {
        const batch = fresh.slice(i, i + BATCH);
        const res = await bg.gmailSignals(batch);
        if (!res.ok) return; // signed out, switched off, or offline — try again next scan
        batch.forEach((e) => sent.add(e.key));
        if (res.data.updated.length) {
          showToast(
            res.data.updated.map(
              (u) =>
                `${u.job_title || "Application"}${u.company ? ` at ${u.company}` : ""} → ${STATUS_LABEL[u.status] || u.status}`,
            ),
          );
        }
      }
    } finally {
      busy = false;
    }
  };

  // Throttle, not debounce: Gmail mutates the page constantly, so a debounce could starve.
  const schedule = () => {
    if (timer !== undefined) return;
    timer = window.setTimeout(() => {
      timer = undefined;
      void scan();
    }, SCAN_DEBOUNCE_MS);
  };
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  window.setInterval(schedule, SCAN_INTERVAL_MS);
  schedule();
}
