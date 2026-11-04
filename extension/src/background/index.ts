/**
 * Service worker: the only place that holds the auth token and talks to the
 * API. Content scripts and popup message it via `sendToBackground`. It also
 * relays job-detection and fill-trigger messages between the frames of a tab
 * (see ../lib/frames.ts) — a job posting or its application form frequently
 * lives in an iframe, so no single frame can be assumed to own everything.
 */
import { API_ORIGIN, TOKEN_KEY, WEB_ORIGIN, WEB_TOKEN_KEY } from "../lib/env";
import type { BgRequest, BgResponse, EmailSignal, EmailStatusUpdate } from "../lib/messaging";
import type { BgToFrame, FrameToBg } from "../lib/frames";
import type { Application, DetectedJob } from "../lib/types";

async function getToken(): Promise<string | null> {
  const s = await chrome.storage.local.get(TOKEN_KEY);
  return (s[TOKEN_KEY] as string) || null;
}
async function setToken(token: string | null, email: string | null): Promise<void> {
  if (token) await chrome.storage.local.set({ [TOKEN_KEY]: token, jobbot_email: email });
  else await chrome.storage.local.remove([TOKEN_KEY, "jobbot_email"]);
}

/** Take the website's token if the server still accepts it. */
async function adoptToken(token: string): Promise<boolean> {
  const me = await fetch(`${API_ORIGIN}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } }).catch(
    () => null,
  );
  if (!me?.ok) return false;
  const user = (await me.json()) as { email?: string };
  await setToken(token, user.email || null);
  void flushPendingApplications();
  return true;
}

/**
 * The extension's copy of the sign-in is lost on reinstall and on a 401, and the
 * website's content script only re-shares it once a JobBot page loads. Read it from
 * any JobBot tab already open instead, so a signed-in member is never told to sign in.
 */
async function recoverSession(): Promise<string | null> {
  const tabs = await chrome.tabs.query({ url: `${WEB_ORIGIN}/*` }).catch(() => [] as chrome.tabs.Tab[]);
  for (const tab of tabs) {
    if (tab.id == null) continue;
    try {
      const [res] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (key: string) => localStorage.getItem(key),
        args: [WEB_TOKEN_KEY],
      });
      const token = res?.result;
      if (typeof token === "string" && token && (await adoptToken(token))) return token;
    } catch {
      /* tab still loading, or a page we may not script */
    }
  }
  return null;
}

async function tokenOrRecover(): Promise<string | null> {
  return (await getToken()) || (await recoverSession());
}

chrome.runtime.onInstalled.addListener(() => void tokenOrRecover());
chrome.runtime.onStartup.addListener(() => void tokenOrRecover().then(() => flushPendingApplications()));

class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = await getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${API_ORIGIN}${path}`, { ...init, headers });
  if (res.status === 401) {
    await setToken(null, null);
    let detail = "Your JobBot session ended — sign in on the JobBot website in this browser.";
    if (res.headers.get("X-Session-Ended")) {
      try {
        const j = await res.json();
        if (typeof j?.detail === "string") detail = j.detail;
      } catch {
        /* keep default */
      }
    }
    throw new HttpError(401, detail);
  }
  if (!res.ok) {
    let detail = res.statusText;
    let code: string | undefined;
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") detail = j.detail;
      // Structured refusals ({code, message}), e.g. a hybrid / on-site job.
      else if (typeof j?.detail?.message === "string") {
        detail = j.detail.message;
        code = typeof j.detail.code === "string" ? j.detail.code : undefined;
      }
    } catch {
      /* ignore */
    }
    throw new HttpError(res.status, detail, code);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function trackJob(job: DetectedJob, status?: string) {
  return api("/api/applications", {
    method: "POST",
    body: JSON.stringify({
      job_url: job.url,
      ats: job.ats,
      company: job.company,
      job_title: job.job_title,
      location: job.location,
      jd_text: job.text,
      status: status || "detected",
    }),
  });
}

// ---------------------------------------------------------------------------
// Gmail status tracking (see ../content/gmail.ts): forward job emails once each.
// ---------------------------------------------------------------------------
const GMAIL_ENABLED_KEY = "jobbot_gmail_tracking";
const GMAIL_SEEN_KEY = "jobbot_gmail_seen";
const GMAIL_SEEN_MAX = 5000;

async function gmailTrackingEnabled(): Promise<boolean> {
  const s = await chrome.storage.local.get(GMAIL_ENABLED_KEY);
  return s[GMAIL_ENABLED_KEY] !== false; // on unless switched off in the popup
}

async function sendGmailSignals(emails: EmailSignal[]): Promise<{ updated: EmailStatusUpdate[] }> {
  if (!(await gmailTrackingEnabled())) throw new HttpError(403, "Gmail tracking is switched off.");
  if (!(await getToken())) throw new HttpError(401, "Not signed in to JobBot.");
  const s = await chrome.storage.local.get(GMAIL_SEEN_KEY);
  const seen: string[] = Array.isArray(s[GMAIL_SEEN_KEY]) ? s[GMAIL_SEEN_KEY] : [];
  const seenSet = new Set(seen);
  const fresh = emails.filter((e) => !seenSet.has(e.key));
  if (!fresh.length) return { updated: [] };
  const res = await api<{ processed_keys: string[]; updated: EmailStatusUpdate[] }>("/api/applications/email-signals", {
    method: "POST",
    body: JSON.stringify({ emails: fresh }),
  });
  // Only what the server handled; anything it deferred is sent again on a later Gmail visit.
  const next = [...seen, ...res.processed_keys.filter((k) => !seenSet.has(k))].slice(-GMAIL_SEEN_MAX);
  await chrome.storage.local.set({ [GMAIL_SEEN_KEY]: next });
  return { updated: res.updated };
}

async function blobToDataUrl(blob: Blob): Promise<string> {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 1) bin += String.fromCharCode(buf[i]);
  return `data:${blob.type || "application/pdf"};base64,${btoa(bin)}`;
}

// ---------------------------------------------------------------------------
// Cross-frame relay: which frames of a tab have reported a job, and the best
// one to show/act on (longest description text wins; frame 0 breaks ties).
// ---------------------------------------------------------------------------
const framesByTab = new Map<number, Map<number, DetectedJob | null>>();
// Frames showing an application form but no posting (sign-in, consent, later steps).
const formFramesByTab = new Map<number, Map<number, { url: string; title: string }>>();
const lastPushedSignature = new Map<number, string>();

// Apply-flow URLs (Workday's /apply/..., Lever's /apply, Ashby's /application, iCIMS
// mode=apply, Taleo jobapply.ftl, sign-in/registration steps): the page is the form,
// and any "description" read off it is the form's own text, not the posting.
const APPLY_URL_RE =
  /\/(apply|application|applymanually|autofillwithresume|usemylastapplication|oneclick-ui|jobapply(?:\.ftl)?|login|signin|sign-in|register|createaccount)(?=[/?#.]|$)|[?&](mode=apply|career_ns=job_application)/i;
// A form page with less text than this has no posting worth tailoring against.
const MIN_POSTING_ON_FORM_CHARS = 600;

/** The job is really an application form, not a posting to tailor against. */
function isFormPageJob(job: DetectedJob, hasForm: boolean): boolean {
  return APPLY_URL_RE.test(job.url) || (hasForm && job.text.length < MIN_POSTING_ON_FORM_CHARS);
}

function bestJobForTab(tabId: number, postingsOnly = false): DetectedJob | null {
  const frames = framesByTab.get(tabId);
  if (!frames) return null;
  const forms = formFramesByTab.get(tabId);
  let best: DetectedJob | null = null;
  for (const [frameId, job] of frames) {
    if (!job) continue;
    if (postingsOnly && isFormPageJob(job, !!forms?.has(frameId))) continue;
    if (!best || job.text.length > best.text.length || (frameId === 0 && job.text.length === best.text.length)) {
      best = job;
    }
  }
  return best;
}

/**
 * Forget frames that no longer exist. Without this, an iframe from a job viewed
 * earlier in the same tab (e.g. a previous Greenhouse embed) kept "winning"
 * bestJobForTab, so every later submission was recorded as that first job.
 */
async function pruneDeadFrames(tabId: number): Promise<void> {
  const frames = framesByTab.get(tabId);
  if (!frames?.size) return;
  const live = await chrome.webNavigation.getAllFrames({ tabId }).catch(() => null);
  if (!live) return;
  const alive = new Set(live.map((f) => f.frameId));
  for (const frameId of Array.from(frames.keys())) {
    if (!alive.has(frameId)) frames.delete(frameId);
  }
  const forms = formFramesByTab.get(tabId);
  for (const frameId of Array.from(forms?.keys() ?? [])) {
    if (!alive.has(frameId)) forms?.delete(frameId);
  }
}

/**
 * The job this tab is about. A posting on the page wins. On an application form with
 * no posting of its own (the description on a careers site, the form on the ATS; or
 * Workday's /apply steps) it is the posting this tab, or the tab that opened it, was
 * just on, so the resume is tailored to the real description, never the form's text.
 */
async function jobForTab(tabId: number): Promise<DetectedJob | null> {
  const posting = bestJobForTab(tabId, true);
  if (posting) return posting;
  const formJob = bestJobForTab(tabId);
  const forms = formFramesByTab.get(tabId);
  if (!formJob && !forms?.size) return null;
  const st = await getTracking(tabId);
  if (st.lastJob && st.lastJobAt && Date.now() - st.lastJobAt < LAST_JOB_TTL_MS) return st.lastJob;
  // No posting seen: keep the title, drop the form text, and key it by the posting URL
  // so a resume already tailored on the posting (seen earlier) is still found.
  if (formJob) return { ...formJob, url: postingUrl(formJob.url), text: "" };
  const page = forms!.get(0) ?? forms!.values().next().value!;
  return fallbackJob(page.url, page.title);
}

// The application form often opens in a new tab: it inherits the posting.
chrome.webNavigation.onCreatedNavigationTarget.addListener(({ sourceTabId, tabId }) => {
  void getTracking(sourceTabId).then((src) => {
    if (src.lastJob && src.lastJobAt && Date.now() - src.lastJobAt < LAST_JOB_TTL_MS) {
      void updateTracking(tabId, () => ({ lastJob: src.lastJob, lastJobAt: src.lastJobAt }));
    }
  });
});

// A new top-level document means every previously reported frame is gone.
chrome.webNavigation.onCommitted.addListener(({ tabId, frameId }) => {
  if (frameId !== 0) return;
  framesByTab.delete(tabId);
  formFramesByTab.delete(tabId);
  lastPushedSignature.delete(tabId);
});
// SPA navigation keeps the document but may swap the job's iframe.
chrome.webNavigation.onHistoryStateUpdated.addListener(({ tabId, frameId }) => {
  if (frameId === 0) void pruneDeadFrames(tabId);
});

function pushToTopFrame(tabId: number, message: BgToFrame): void {
  chrome.tabs.sendMessage(tabId, message, { frameId: 0 }).catch(() => {
    /* top frame may not have a listener yet (early navigation) — ignore */
  });
}

// ---------------------------------------------------------------------------
// Submission tracking. Per-tab state lives in chrome.storage.session (not just
// memory) because it must outlive both the page — the confirmation is often a
// new page load — and this service worker, which Chrome stops when idle.
// Flow: resume-selected (any time) → submit-clicked (arms) → confirmation
// (records, with the resume) — see ../content/submission.ts.
// ---------------------------------------------------------------------------
const ARM_TTL_MS = 15 * 60 * 1000;
const RESUME_TTL_MS = 3 * 60 * 60 * 1000;

type CapturedResume = {
  filename: string;
  contentType?: string;
  dataUrl?: string;
  variantId?: string;
  at: number;
};
type TabTracking = {
  lastJob: DetectedJob | null;
  lastJobAt: number | null;
  resume: CapturedResume | null;
  armedAt: number | null;
  armedJob: DetectedJob | null;
};
const EMPTY_TRACKING: TabTracking = {
  lastJob: null,
  lastJobAt: null,
  resume: null,
  armedAt: null,
  armedJob: null,
};
// A remembered posting only stands in for a form page if it's this fresh —
// otherwise it's probably a different job seen earlier.
const LAST_JOB_TTL_MS = 30 * 60 * 1000;

const trackingKey = (tabId: number) => `track:${tabId}`;
const trackingQueues = new Map<number, Promise<unknown>>();
const recordingTabs = new Set<number>();

async function getTracking(tabId: number): Promise<TabTracking> {
  const s = await chrome.storage.session.get(trackingKey(tabId));
  return { ...EMPTY_TRACKING, ...(s[trackingKey(tabId)] as Partial<TabTracking> | undefined) };
}

/** Serialized read-modify-write of a tab's tracking state (frames message concurrently). */
function updateTracking(tabId: number, fn: (st: TabTracking) => Partial<TabTracking>): Promise<TabTracking> {
  const prev = trackingQueues.get(tabId) ?? Promise.resolve();
  const next = prev.then(async () => {
    const cur = await getTracking(tabId);
    const st = { ...cur, ...fn(cur) };
    try {
      await chrome.storage.session.set({ [trackingKey(tabId)]: st });
    } catch {
      // Over quota (very large resume) — keep going without the file bytes.
      st.resume = st.resume?.dataUrl ? null : st.resume;
      await chrome.storage.session.set({ [trackingKey(tabId)]: st }).catch(() => {});
    }
    return st;
  });
  trackingQueues.set(tabId, next.catch(() => {}));
  return next;
}

/** Lever/Ashby/Workday put the form under …/apply or …/application — record the posting itself. */
function postingUrl(raw: string): string {
  try {
    const u = new URL(raw);
    const stripped = u.pathname.replace(/\/(apply|application)(\/.*)?$/i, "");
    if (stripped && stripped !== "/") u.pathname = stripped;
    u.hash = "";
    return u.toString();
  } catch {
    return raw;
  }
}

function fallbackJob(url: string, title: string): DetectedJob {
  return { url, text: "", page_title: title, company: "", job_title: title, location: "", ats: "" };
}

function notifyTopFrame(tabId: number, ok: boolean, message: string): void {
  pushToTopFrame(tabId, { type: "track:recorded", ok, message });
}

async function armTracking(
  tabId: number,
  pageUrl: string,
  pageTitle: string,
  clickedFrameJob: DetectedJob | null,
): Promise<void> {
  await pruneDeadFrames(tabId);
  // The same job the overlay shows: the posting, even when the form is elsewhere.
  const current = await jobForTab(tabId);
  const st = await updateTracking(tabId, () => ({
    armedAt: Date.now(),
    armedJob: current || clickedFrameJob || fallbackJob(pageUrl, pageTitle),
  }));
  // No frameId → every frame of the tab starts watching for the confirmation.
  chrome.tabs
    .sendMessage(tabId, { type: "track:armed", until: (st.armedAt ?? 0) + ARM_TTL_MS } satisfies BgToFrame)
    .catch(() => {});
}

// Confirmed applications that couldn't be saved yet (signed out, offline). Kept until
// the extension has a sign-in again, so no confirmed application is ever lost.
const PENDING_KEY = "pending_applications";
const MAX_PENDING = 20;
const PENDING_TTL_MS = 14 * 24 * 60 * 60 * 1000;
// chrome.storage.local holds ~10 MB: keep a picked-on-page resume only if it's small.
const MAX_PENDING_RESUME_CHARS = 3 * 1024 * 1024;

type Submission = {
  payload: string;
  resumeVariantId?: string;
  resumeDataUrl?: string;
  resumeFilename?: string;
  at: number;
};

async function postSubmission(sub: Submission): Promise<Application> {
  const form = new FormData();
  form.append("payload", sub.payload);
  if (sub.resumeVariantId) {
    form.append("resume_variant_id", sub.resumeVariantId);
  } else if (sub.resumeDataUrl) {
    const blob = await (await fetch(sub.resumeDataUrl)).blob();
    form.append("resume", blob, sub.resumeFilename || "resume");
    form.append("resume_source", "selected_on_page");
  }
  return api<Application>("/api/applications/submitted", { method: "POST", body: form });
}

async function queueSubmission(sub: Submission): Promise<void> {
  const s = await chrome.storage.local.get(PENDING_KEY);
  const pending = ((s[PENDING_KEY] as Submission[]) || []).filter((p) => Date.now() - p.at < PENDING_TTL_MS);
  const kept = sub.resumeDataUrl && sub.resumeDataUrl.length > MAX_PENDING_RESUME_CHARS
    ? { ...sub, resumeDataUrl: undefined }
    : sub;
  await chrome.storage.local.set({ [PENDING_KEY]: [...pending, kept].slice(-MAX_PENDING) });
}

let flushing: Promise<void> | null = null;

/** Save queued applications now that there's a sign-in. */
function flushPendingApplications(): Promise<void> {
  flushing ??= (async () => {
    try {
      if (!(await getToken())) return;
      const s = await chrome.storage.local.get(PENDING_KEY);
      const pending = (s[PENDING_KEY] as Submission[]) || [];
      const left: Submission[] = [];
      for (const [i, sub] of pending.entries()) {
        if (Date.now() - sub.at >= PENDING_TTL_MS) continue;
        try {
          await postSubmission(sub);
        } catch (e) {
          const status = (e as HttpError).status;
          // Signed out again or offline: keep the rest for next time. A refused one is dropped.
          if (status === 401 || status === undefined || status >= 500) {
            left.push(sub, ...pending.slice(i + 1));
            break;
          }
        }
      }
      await chrome.storage.local.set({ [PENDING_KEY]: left });
    } finally {
      flushing = null;
    }
  })();
  return flushing;
}

async function recordConfirmedApplication(tabId: number, pageUrl: string): Promise<void> {
  if (recordingTabs.has(tabId)) return; // several frames can confirm at once
  recordingTabs.add(tabId);
  try {
    const st = await getTracking(tabId);
    if (!st.armedAt || Date.now() - st.armedAt > ARM_TTL_MS) return;
    // Disarm first so a failure can't loop; the user can still add it by hand.
    await updateTracking(tabId, () => ({ armedAt: null, armedJob: null }));

    const job = st.armedJob || st.lastJob || fallbackJob(pageUrl, "");
    const resume = st.resume && Date.now() - st.resume.at < RESUME_TTL_MS ? st.resume : null;
    const sub: Submission = {
      payload: JSON.stringify({
        job_url: postingUrl(job.url),
        ats: job.ats,
        company: job.company,
        job_title: job.job_title,
        location: job.location,
        jd_text: job.text,
      }),
      resumeVariantId: resume?.variantId,
      resumeDataUrl: resume?.variantId ? undefined : resume?.dataUrl,
      resumeFilename: resume?.filename,
      at: Date.now(),
    };
    await updateTracking(tabId, () => ({ resume: null }));
    const what = [job.job_title, job.company].filter(Boolean).join(" at ") || "This application";
    const later = `JobBot kept ${what} and will add it to your tracker as soon as you open the JobBot website signed in.`;

    if (!(await tokenOrRecover())) {
      await queueSubmission(sub);
      notifyTopFrame(tabId, false, later);
      return;
    }
    let app: Application;
    try {
      app = await postSubmission(sub);
    } catch (e) {
      const status = (e as HttpError).status;
      // Signed out meanwhile, offline or a server hiccup: keep it, don't lose it.
      if (status === 401 || status === undefined || status >= 500) {
        await queueSubmission(sub);
        notifyTopFrame(tabId, false, later);
        return;
      }
      throw e;
    }
    void flushPendingApplications();

    const saved = [app.job_title, app.company].filter(Boolean).join(" at ") || "Application";
    notifyTopFrame(
      tabId,
      true,
      `✓ Tracked: ${saved}${app.applied_resume ? ` — resume "${app.applied_resume.filename}" saved` : ""}`,
    );
  } catch (e) {
    notifyTopFrame(tabId, false, `JobBot couldn't record this application: ${(e as Error).message}`);
  } finally {
    recordingTabs.delete(tabId);
  }
}

function handleFrameMessage(req: FrameToBg, sender: chrome.runtime.MessageSender): void {
  const tabId = sender.tab?.id;
  if (tabId == null) return;
  const frameId = sender.frameId ?? 0;

  if (req.type === "frame:report-job") {
    let frames = framesByTab.get(tabId);
    if (!frames) {
      frames = new Map();
      framesByTab.set(tabId, frames);
    }
    frames.set(frameId, req.job);
    let forms = formFramesByTab.get(tabId);
    if (!forms) {
      forms = new Map();
      formFramesByTab.set(tabId, forms);
    }
    if (req.hasForm) forms.set(frameId, req.page);
    else forms.delete(frameId);
    void pruneDeadFrames(tabId).then(async () => {
      const posting = bestJobForTab(tabId, true);
      // Remembered past navigation: the form and the confirmation rarely carry the posting.
      if (posting) await updateTracking(tabId, () => ({ lastJob: posting, lastJobAt: Date.now() }));
      const shown = await jobForTab(tabId);
      const sig = shown ? `${shown.url}|${shown.job_title}|${shown.text.length}` : "";
      if (sig !== lastPushedSignature.get(tabId)) {
        lastPushedSignature.set(tabId, sig);
        pushToTopFrame(tabId, { type: "job:update", job: shown });
      }
    });
    return;
  }
  if (req.type === "frame:fill-progress") {
    pushToTopFrame(tabId, {
      type: "job:fill-progress",
      label: req.label,
      index: req.index,
      total: req.total,
    });
    return;
  }
  if (req.type === "frame:fill-result") {
    pushToTopFrame(tabId, {
      type: "job:fill-status",
      filled: req.filled,
      skipped: req.skipped,
      attachedResume: req.attachedResume,
      keptResume: req.keptResume,
      questions: req.questions,
      nextLabel: req.nextLabel,
      error: req.error,
    });
    return;
  }
  if (req.type === "frame:resume-selected") {
    void updateTracking(tabId, () => ({
      resume: {
        filename: req.filename,
        contentType: req.contentType,
        dataUrl: req.dataUrl,
        variantId: req.variantId,
        at: Date.now(),
      },
    }));
    return;
  }
  if (req.type === "frame:submit-clicked") {
    void armTracking(tabId, req.pageUrl, req.pageTitle, req.job);
    return;
  }
  if (req.type === "frame:confirmation") {
    void recordConfirmedApplication(tabId, req.pageUrl);
  }
}

/** Frames of the tab holding an application form. Asks every live frame, not only
 * those that detected a job: a form iframe often has no job signal of its own. */
async function formFrames(tabId: number): Promise<number[]> {
  const frames = (await chrome.webNavigation.getAllFrames({ tabId })) ?? [];
  const checks = await Promise.all(
    frames.map(async ({ frameId }) => {
      try {
        const hasForm = await chrome.tabs.sendMessage(tabId, { type: "do-probe" }, { frameId });
        return hasForm === true ? frameId : null;
      } catch {
        return null; // a frame that never loaded the content script (e.g. about:blank)
      }
    }),
  );
  return checks.filter((id): id is number => id !== null);
}

async function broadcastFill(
  tabId: number,
  job: DetectedJob,
  variant: "quick" | "tailored",
  resumeVariantId: string | undefined,
  onlyBlank: boolean,
): Promise<number> {
  const frameIds = await formFrames(tabId);
  for (const frameId of frameIds) {
    chrome.tabs
      .sendMessage(tabId, { type: "do-fill", job, variant, resumeVariantId, onlyBlank }, { frameId })
      .catch(() => {
        /* the frame navigated away since the probe — ignore */
      });
  }
  return frameIds.length;
}

// Proceed was pressed: the next step (same page or a new one) carries on filling.
const CONTINUATION_TTL_MS = 2 * 60 * 1000;
const continuationKey = (tabId: number) => `continue:${tabId}`;
type Continuation = { job: DetectedJob; resume_variant_id?: string; at: number };

async function clickNext(tabId: number): Promise<{ clicked: boolean; reason?: "disabled" | "none" }> {
  const frames = (await chrome.webNavigation.getAllFrames({ tabId })) ?? [];
  const results = await Promise.all(
    frames.map(({ frameId }) =>
      chrome.tabs.sendMessage(tabId, { type: "do-next" }, { frameId }).catch(() => "none"),
    ),
  );
  if (results.includes("clicked")) return { clicked: true };
  return { clicked: false, reason: results.includes("disabled") ? "disabled" : "none" };
}

chrome.tabs.onRemoved.addListener((tabId) => {
  framesByTab.delete(tabId);
  formFramesByTab.delete(tabId);
  void chrome.storage.session.remove(continuationKey(tabId));
  lastPushedSignature.delete(tabId);
  trackingQueues.delete(tabId);
  void chrome.storage.session.remove(trackingKey(tabId));
});

// ---------------------------------------------------------------------------
// Request/response API (popup + top-frame overlay -> background)
// ---------------------------------------------------------------------------

async function handle(req: BgRequest, sender: chrome.runtime.MessageSender): Promise<BgResponse> {
  try {
    switch (req.type) {
      case "auth:get": {
        await tokenOrRecover();
        const s = await chrome.storage.local.get([TOKEN_KEY, "jobbot_email"]);
        return { ok: true, data: { token: s[TOKEN_KEY] || null, email: s.jobbot_email || null } };
      }
      case "auth:sync": {
        // The extension never signs in on its own — it uses
        // the JobBot website's session in this same browser. Only that site may set it.
        let origin = "";
        try {
          origin = new URL(sender.url || "").origin;
        } catch {
          /* no url */
        }
        if (origin !== WEB_ORIGIN || sender.frameId !== 0) return { ok: false, error: "Not allowed." };
        const current = await getToken();
        if (!req.token) {
          if (current) await setToken(null, null);
          return { ok: true, data: null };
        }
        if (req.token === current) {
          void flushPendingApplications();
          return { ok: true, data: null };
        }
        if (!(await adoptToken(req.token))) return { ok: false, error: "Website session isn't valid." };
        const s = await chrome.storage.local.get("jobbot_email");
        return { ok: true, data: { email: (s.jobbot_email as string) || null } };
      }
      case "auth:logout":
        // Signing out ends the account's session everywhere (website included).
        await api("/api/auth/logout", { method: "POST" }).catch(() => {});
        await setToken(null, null);
        return { ok: true, data: null };
      case "profile:get":
        return { ok: true, data: await api("/api/extension/profile") };
      case "job:track":
        return { ok: true, data: await trackJob(req.job, req.status) };
      case "job:analyze":
        return {
          ok: true,
          data: await api("/api/extension/analyze-job", {
            method: "POST",
            body: JSON.stringify(req.job),
          }),
        };
      case "job:autofill":
        return {
          ok: true,
          data: await api("/api/extension/autofill", {
            method: "POST",
            body: JSON.stringify({
              // Same key as the tracker: an /apply page belongs to its posting.
              job: { ...req.job, url: postingUrl(req.job.url) },
              fields: req.fields,
              variant: req.variant,
              resume_variant_id: req.resume_variant_id,
            }),
          }),
        };
      case "job:tailor":
        return {
          ok: true,
          data: await api("/api/extension/tailor", {
            method: "POST",
            body: JSON.stringify({
              job: { ...req.job, url: postingUrl(req.job.url) },
              target_job_role: req.target_job_role || "",
            }),
          }),
        };
      case "job:probe-form": {
        const tabId = sender.tab?.id;
        if (tabId == null) return { ok: false, error: "No active tab." };
        return { ok: true, data: { targets: (await formFrames(tabId)).length } };
      }
      case "job:fill-request": {
        const tabId = sender.tab?.id;
        if (tabId == null) return { ok: false, error: "No active tab." };
        const targets = await broadcastFill(tabId, req.job, req.variant, req.resume_variant_id, !!req.only_blank);
        return { ok: true, data: { targets } };
      }
      case "job:continue": {
        const tabId = sender.tab?.id;
        if (tabId == null) return { ok: false, error: "No active tab." };
        // Saved first: clicking Next may unload the page that asked.
        const pending: Continuation = { job: req.job, resume_variant_id: req.resume_variant_id, at: Date.now() };
        await chrome.storage.session.set({ [continuationKey(tabId)]: pending });
        const result = await clickNext(tabId);
        if (!result.clicked) await chrome.storage.session.remove(continuationKey(tabId));
        return { ok: true, data: result };
      }
      case "job:take-continuation": {
        const tabId = sender.tab?.id;
        if (tabId == null) return { ok: true, data: null };
        const key = continuationKey(tabId);
        const s = await chrome.storage.session.get(key);
        await chrome.storage.session.remove(key);
        const pending = s[key] as Continuation | undefined;
        const fresh = pending && Date.now() - pending.at < CONTINUATION_TTL_MS;
        return { ok: true, data: fresh ? { job: pending.job, resume_variant_id: pending.resume_variant_id } : null };
      }
      case "resume:fetch": {
        const token = await getToken();
        const res = await fetch(`${API_ORIGIN}${req.download_path}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (!res.ok) return { ok: false, error: `Resume download failed (${res.status})` };
        const disposition = res.headers.get("Content-Disposition") || "";
        const filename = /filename="?([^"]+)"?/.exec(disposition)?.[1] || "resume.pdf";
        return { ok: true, data: { dataUrl: await blobToDataUrl(await res.blob()), filename } };
      }
      case "tracking:state": {
        const tabId = sender.tab?.id;
        if (tabId == null) return { ok: true, data: { armedUntil: null } };
        const st = await getTracking(tabId);
        const armedUntil = st.armedAt ? st.armedAt + ARM_TTL_MS : null;
        return { ok: true, data: { armedUntil: armedUntil && armedUntil > Date.now() ? armedUntil : null } };
      }
      case "applications:list":
        return { ok: true, data: await api(`/api/applications?limit=${req.limit ?? 20}`) };
      case "applications:stats":
        return { ok: true, data: await api("/api/applications/stats") };
      case "applications:update":
        return {
          ok: true,
          data: await api(`/api/applications/${req.id}`, {
            method: "PATCH",
            body: JSON.stringify({ status: req.status }),
          }),
        };
      case "gmail:signals":
        return { ok: true, data: await sendGmailSignals(req.emails) };
      case "gmail:get-enabled":
        return { ok: true, data: await gmailTrackingEnabled() };
      case "gmail:set-enabled":
        await chrome.storage.local.set({ [GMAIL_ENABLED_KEY]: req.enabled });
        return { ok: true, data: req.enabled };
      default:
        return { ok: false, error: "Unknown request." };
    }
  } catch (e) {
    const err = e as HttpError;
    return { ok: false, error: err.message || "Request failed", status: err.status, code: err.code };
  }
}

chrome.runtime.onMessage.addListener((req: BgRequest | FrameToBg, sender, sendResponse) => {
  if (
    req.type === "frame:report-job" ||
    req.type === "frame:fill-progress" ||
    req.type === "frame:fill-result" ||
    req.type === "frame:resume-selected" ||
    req.type === "frame:submit-clicked" ||
    req.type === "frame:confirmation"
  ) {
    handleFrameMessage(req, sender);
    return false; // fire-and-forget, no reply expected
  }
  handle(req as BgRequest, sender).then(sendResponse);
  return true; // async reply
});
