import type {
  Application,
  ApplicationStats,
  AutofillResponse,
  DetectedJob,
  ExtensionProfile,
  FormField,
  TailorForJobResponse,
} from "./types";

export type BgRequest =
  | { type: "auth:get" }
  | { type: "auth:login"; email: string; password: string }
  | { type: "auth:logout" }
  | { type: "profile:get" }
  | { type: "job:track"; job: DetectedJob; status?: string }
  | { type: "job:analyze"; job: DetectedJob }
  | { type: "job:autofill"; job: DetectedJob; fields: FormField[]; variant: "quick" | "tailored"; resume_variant_id?: string }
  | { type: "job:tailor"; job: DetectedJob; target_job_role?: string }
  | {
      type: "job:fill-request";
      job: DetectedJob;
      variant: "quick" | "tailored";
      resume_variant_id?: string;
    }
  | { type: "resume:fetch"; download_path: string }
  | { type: "applications:list"; limit?: number }
  | { type: "applications:stats" }
  | { type: "applications:update"; id: string; status: string };

export type BgResponse<T = unknown> = { ok: true; data: T } | { ok: false; error: string; status?: number };

export function sendToBackground<T = unknown>(req: BgRequest): Promise<BgResponse<T>> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(req, (res: BgResponse<T>) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message || "Extension error" });
        return;
      }
      resolve(res ?? { ok: false, error: "No response from background." });
    });
  });
}

// Convenience typed wrappers
export const bg = {
  authGet: () => sendToBackground<{ token: string | null; email: string | null }>({ type: "auth:get" }),
  login: (email: string, password: string) =>
    sendToBackground<{ email: string }>({ type: "auth:login", email, password }),
  logout: () => sendToBackground({ type: "auth:logout" }),
  profile: () => sendToBackground<ExtensionProfile>({ type: "profile:get" }),
  track: (job: DetectedJob, status?: string) =>
    sendToBackground<Application>({ type: "job:track", job, status }),
  analyze: (job: DetectedJob) => sendToBackground<Record<string, unknown>>({ type: "job:analyze", job }),
  autofill: (
    job: DetectedJob,
    fields: FormField[],
    variant: "quick" | "tailored",
    resume_variant_id?: string,
  ) => sendToBackground<AutofillResponse>({ type: "job:autofill", job, fields, variant, resume_variant_id }),
  tailor: (job: DetectedJob, target_job_role?: string) =>
    sendToBackground<TailorForJobResponse>({ type: "job:tailor", job, target_job_role }),
  requestFill: (job: DetectedJob, variant: "quick" | "tailored", resume_variant_id?: string) =>
    sendToBackground<{ targets: number }>({
      type: "job:fill-request",
      job,
      variant,
      resume_variant_id,
    }),
  fetchResume: (download_path: string) =>
    sendToBackground<{ dataUrl: string; filename: string }>({ type: "resume:fetch", download_path }),
  applications: (limit = 20) =>
    sendToBackground<{ items: Application[] }>({ type: "applications:list", limit }),
  stats: () => sendToBackground<ApplicationStats>({ type: "applications:stats" }),
  updateApplication: (id: string, status: string) =>
    sendToBackground<Application>({ type: "applications:update", id, status }),
};
