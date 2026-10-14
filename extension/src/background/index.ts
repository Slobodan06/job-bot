/**
 * Service worker: the only place that holds the auth token and talks to the
 * API. Content scripts and popup message it via `sendToBackground`. It also
 * relays job-detection and fill-trigger messages between the frames of a tab
 * (see ../lib/frames.ts) — a job posting or its application form frequently
 * lives in an iframe, so no single frame can be assumed to own everything.
 */
import { API_ORIGIN, TOKEN_KEY, WEB_ORIGIN } from "../lib/env";
import type { BgRequest, BgResponse } from "../lib/messaging";
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

class HttpError extends Error {
  constructor(public status: number, message: string) {
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
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") detail = j.detail;
    } catch {
      /* ignore */
    }
    throw new HttpError(res.status, detail);
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
const lastPushedSignature = new Map<number, string>();

function bestJobForTab(tabId: number): DetectedJob | null {
  const frames = framesByTab.get(tabId);
  if (!frames) return null;
  let best: DetectedJob | null = null;
  for (const [frameId, job] of frames) {
    if (!job) continue;
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
}

// A new top-level document means every previously reported frame is gone.
chrome.webNavigation.onCommitted.addListener(({ tabId, frameId }) => {
  if (frameId !== 0) return;
  framesByTab.delete(tabId);
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
// A remembered job only stands in for the current page if it's this fresh and
// from the same site — otherwise it's probably a different job seen earlier.
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

function sameSite(a: string, b: string): boolean {
  try {
    return new URL(a).hostname === new URL(b).hostname;
  } catch {
    return false;
  }
}

async function armTracking(
  tabId: number,
  pageUrl: string,
  pageTitle: string,
  clickedFrameJob: DetectedJob | null,
): Promise<void> {
  await pruneDeadFrames(tabId);
  const current = bestJobForTab(tabId);
  const st = await updateTracking(tabId, (cur) => {
    const recentLast =
      cur.lastJob && cur.lastJobAt && Date.now() - cur.lastJobAt < LAST_JOB_TTL_MS && sameSite(cur.lastJob.url, pageUrl)
        ? cur.lastJob
        : null;
    return {
      armedAt: Date.now(),
      // Most trustworthy first: what the live frames of this page show, then what the
      // frame holding the Submit button sees itself, then a recent same-site memory.
      armedJob: current || clickedFrameJob || recentLast || fallbackJob(pageUrl, pageTitle),
    };
  });
  // No frameId → every frame of the tab starts watching for the confirmation.
  chrome.tabs
    .sendMessage(tabId, { type: "track:armed", until: (st.armedAt ?? 0) + ARM_TTL_MS } satisfies BgToFrame)
    .catch(() => {});
}

async function recordConfirmedApplication(tabId: number, pageUrl: string): Promise<void> {
  if (recordingTabs.has(tabId)) return; // several frames can confirm at once
  recordingTabs.add(tabId);
  try {
    const st = await getTracking(tabId);
    if (!st.armedAt || Date.now() - st.armedAt > ARM_TTL_MS) return;
    // Disarm first so a failure can't loop; the user can still add it by hand.
    await updateTracking(tabId, () => ({ armedAt: null, armedJob: null }));

    if (!(await getToken())) {
      notifyTopFrame(tabId, false, "JobBot: sign in on the JobBot website in this browser to track your applications.");
      return;
    }
    const job = st.armedJob || st.lastJob || fallbackJob(pageUrl, "");
    const form = new FormData();
    form.append(
      "payload",
      JSON.stringify({
        job_url: postingUrl(job.url),
        ats: job.ats,
        company: job.company,
        job_title: job.job_title,
        location: job.location,
        jd_text: job.text,
      }),
    );
    const resume = st.resume && Date.now() - st.resume.at < RESUME_TTL_MS ? st.resume : null;
    if (resume?.variantId) {
      form.append("resume_variant_id", resume.variantId);
    } else if (resume?.dataUrl) {
      const blob = await (await fetch(resume.dataUrl)).blob();
      form.append("resume", blob, resume.filename);
      form.append("resume_source", "selected_on_page");
    }
    const app = await api<Application>("/api/applications/submitted", { method: "POST", body: form });
    await updateTracking(tabId, () => ({ resume: null }));

    const what = [app.job_title, app.company].filter(Boolean).join(" at ") || "Application";
    notifyTopFrame(
      tabId,
      true,
      `✓ Tracked: ${what}${app.applied_resume ? ` — resume "${app.applied_resume.filename}" saved` : ""}`,
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
    void pruneDeadFrames(tabId).then(() => {
      const best = bestJobForTab(tabId);
      // Remembered past navigation: the confirmation page rarely looks like a job.
      if (best) void updateTracking(tabId, () => ({ lastJob: best, lastJobAt: Date.now() }));
      const sig = best ? `${best.url}|${best.job_title}|${best.text.length}` : "";
      if (sig !== lastPushedSignature.get(tabId)) {
        lastPushedSignature.set(tabId, sig);
        pushToTopFrame(tabId, { type: "job:update", job: best });
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

function broadcastFill(
  tabId: number,
  job: DetectedJob,
  variant: "quick" | "tailored",
  resumeVariantId: string | undefined,
): number {
  const frames = framesByTab.get(tabId);
  const frameIds = frames && frames.size ? Array.from(frames.keys()) : [0];
  for (const frameId of frameIds) {
    chrome.tabs
      .sendMessage(tabId, { type: "do-fill", job, variant, resumeVariantId }, { frameId })
      .catch(() => {
        /* a frame that never loaded the content script (e.g. about:blank) — ignore */
      });
  }
  return frameIds.length;
}

chrome.tabs.onRemoved.addListener((tabId) => {
  framesByTab.delete(tabId);
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
        const s = await chrome.storage.local.get([TOKEN_KEY, "jobbot_email"]);
        return { ok: true, data: { token: s[TOKEN_KEY] || null, email: s.jobbot_email || null } };
      }
      case "auth:sync": {
        // One browser per account: the extension never signs in on its own — it uses
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
        if (req.token === current) return { ok: true, data: null };
        const me = await fetch(`${API_ORIGIN}/api/auth/me`, { headers: { Authorization: `Bearer ${req.token}` } });
        if (!me.ok) return { ok: false, error: "Website session isn't valid." };
        const user = (await me.json()) as { email?: string };
        await setToken(req.token, user.email || null);
        return { ok: true, data: { email: user.email || null } };
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
              job: req.job,
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
            body: JSON.stringify({ job: req.job, target_job_role: req.target_job_role || "" }),
          }),
        };
      case "job:fill-request": {
        const tabId = sender.tab?.id;
        if (tabId == null) return { ok: false, error: "No active tab." };
        const targets = broadcastFill(tabId, req.job, req.variant, req.resume_variant_id);
        return { ok: true, data: { targets } };
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
      default:
        return { ok: false, error: "Unknown request." };
    }
  } catch (e) {
    const err = e as HttpError;
    return { ok: false, error: err.message || "Request failed", status: err.status };
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
