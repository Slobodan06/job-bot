/**
 * Service worker: the only place that holds the auth token and talks to the
 * API. Content scripts and popup message it via `sendToBackground`. It also
 * relays job-detection and fill-trigger messages between the frames of a tab
 * (see ../lib/frames.ts) — a job posting or its application form frequently
 * lives in an iframe, so no single frame can be assumed to own everything.
 */
import { API_ORIGIN, TOKEN_KEY } from "../lib/env";
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
    throw new HttpError(401, "Your session expired — sign in again from the popup.");
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
  resume: CapturedResume | null;
  armedAt: number | null;
  armedJob: DetectedJob | null;
};
const EMPTY_TRACKING: TabTracking = { lastJob: null, resume: null, armedAt: null, armedJob: null };

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

async function armTracking(tabId: number, pageUrl: string, pageTitle: string): Promise<void> {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const st = await updateTracking(tabId, (cur) => ({
    armedAt: Date.now(),
    armedJob:
      bestJobForTab(tabId) || cur.lastJob || fallbackJob(tab?.url || pageUrl, tab?.title || pageTitle),
  }));
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
      notifyTopFrame(tabId, false, "JobBot: sign in from the extension popup to track your applications.");
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
    const best = bestJobForTab(tabId);
    // Remembered past navigation: the confirmation page rarely looks like a job.
    if (best) void updateTracking(tabId, () => ({ lastJob: best }));
    const sig = best ? `${best.url}|${best.job_title}|${best.text.length}` : "";
    if (sig !== lastPushedSignature.get(tabId)) {
      lastPushedSignature.set(tabId, sig);
      pushToTopFrame(tabId, { type: "job:update", job: best });
    }
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
    void armTracking(tabId, req.pageUrl, req.pageTitle);
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
      case "auth:login": {
        const r = await api<{ status: string; access_token?: string; email: string; message: string }>(
          "/api/auth/login",
          { method: "POST", body: JSON.stringify({ email: req.email, password: req.password }) },
          false,
        );
        if (!r.access_token) return { ok: false, error: r.message || "Login incomplete." };
        await setToken(r.access_token, r.email);
        return { ok: true, data: { email: r.email } };
      }
      case "auth:logout":
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
