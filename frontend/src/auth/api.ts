export type User = {
  id: string;
  email: string;
  name: string;
  avatar_url: string;
  headline: string;
  target_role: string;
  location: string;
  bio: string;
  role: "owner" | "member";
  email_verified: boolean;
  has_access: boolean;
  cv_template_key: string;
  cv_template_label: string;
  created_at: string | null;
  updated_at: string | null;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

export type AuthResult = {
  status: "pending_verification" | "pending_access" | "authenticated";
  message: string;
  email: string;
  access_token?: string | null;
  user?: User | null;
};

export type ProfileUpdatePayload = {
  name?: string;
  headline?: string;
  target_role?: string;
  location?: string;
  bio?: string;
};

const TOKEN_KEY = "jobbot_access_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail)) {
      return data.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(", ") || res.statusText;
    }
  } catch {
    /* ignore */
  }
  return res.statusText || `Request failed (${res.status})`;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const authToken = token ?? getStoredToken();
  if (authToken) headers.set("Authorization", `Bearer ${authToken}`);

  const res = await fetch(path, { ...options, headers });
  if (!res.ok) throw new Error(await parseError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function userHasTemplate(user: User | null): boolean {
  return Boolean(user?.cv_template_key);
}

export function userCanBuild(user: User | null): boolean {
  if (!user) return false;
  if (user.role === "owner") return true;
  return user.email_verified && user.has_access;
}

export function userIsOwner(user: User | null): boolean {
  return user?.role === "owner";
}

export const authApi = {
  register(email: string, password: string, name: string) {
    return apiFetch<AuthResult>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name }),
    });
  },
  login(email: string, password: string) {
    return apiFetch<AuthResult>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  },
  verifyEmail(token: string) {
    return apiFetch<AuthResult>(`/api/auth/verify-email?token=${encodeURIComponent(token)}`);
  },
  resendVerification(email: string) {
    return apiFetch<{ message: string }>("/api/auth/resend-verification", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },
  me(token?: string) {
    return apiFetch<User>("/api/auth/me", {}, token);
  },
  updateProfile(payload: ProfileUpdatePayload) {
    return apiFetch<User>("/api/auth/profile", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  changePassword(currentPassword: string, newPassword: string) {
    return apiFetch<{ message: string }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  },
};

export type AppliedResume = {
  file_id: string;
  filename: string;
  content_type: string;
  size: number;
  source: "attached_by_extension" | "selected_on_page" | "uploaded_manually";
  stored_at: string | null;
};

export type JobApplication = {
  id: string;
  job_url: string;
  ats: string;
  company: string;
  job_title: string;
  location: string;
  status: string;
  resume_variant_id: string | null;
  notes: string;
  scores: Record<string, number>;
  applied_resume: AppliedResume | null;
  created_at: string | null;
  updated_at: string | null;
  submitted_at: string | null;
};

export const APPLICATION_STATUSES = [
  "detected",
  "drafting",
  "ready",
  "submitted",
  "interviewing",
  "offer",
  "rejected",
  "withdrawn",
] as const;

export const applicationsApi = {
  list(params: { status?: string; q?: string; cursor?: string; limit?: number } = {}) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v != null && v !== "" && qs.set(k, String(v)));
    return apiFetch<{ items: JobApplication[]; next_cursor: string | null }>(
      `/api/applications${qs.toString() ? `?${qs}` : ""}`,
    );
  },
  stats() {
    return apiFetch<{ total: number; by_status: Record<string, number> }>("/api/applications/stats");
  },
  get(id: string) {
    return apiFetch<JobApplication>(`/api/applications/${id}`);
  },
  /** Manual insert from the dashboard; fails (409) if the job URL is already tracked. */
  create(body: ApplicationInput) {
    return apiFetch<JobApplication>("/api/applications?strict=true", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  update(id: string, patch: Partial<ApplicationInput>) {
    return apiFetch<JobApplication>(`/api/applications/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  },
  remove(id: string) {
    return apiFetch<void>(`/api/applications/${id}`, { method: "DELETE" });
  },
  uploadResume(id: string, file: File) {
    const body = new FormData();
    body.append("resume", file);
    return apiFetch<JobApplication>(`/api/applications/${id}/resume`, { method: "PUT", body });
  },
  removeResume(id: string) {
    return apiFetch<JobApplication>(`/api/applications/${id}/resume`, { method: "DELETE" });
  },
  /** The resume download needs the bearer token, so fetch it and hand the browser a blob. */
  async downloadResume(app: JobApplication) {
    const token = getStoredToken();
    const res = await fetch(`/api/applications/${app.id}/resume`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!res.ok) throw new Error(await parseError(res));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = app.applied_resume?.filename || "resume";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },
};

export type ApplicationInput = {
  job_url: string;
  company?: string;
  job_title?: string;
  location?: string;
  status?: string;
  notes?: string;
  submitted_at?: string | null;
};

export type ExtensionProfile = {
  name: string;
  email: string;
  has_base_resume: boolean;
  autofill_profile: Record<string, unknown>;
};

export const extensionApi = {
  getProfile() {
    return apiFetch<ExtensionProfile>("/api/extension/profile");
  },
  saveProfile(profile: Record<string, unknown>) {
    return apiFetch<ExtensionProfile>("/api/extension/profile", {
      method: "PUT",
      body: JSON.stringify(profile),
    });
  },
};

export type JobListing = {
  title: string;
  company: string;
  location: string;
  url: string;
  source: string;
  remote: boolean;
  employment_type: string;
  posted_at: string | null;
  description_snippet: string;
};

export const jobSearchApi = {
  search(params: {
    keyword: string;
    country?: string;
    remote?: boolean;
    posted_within_days?: number;
    page?: number;
  }) {
    const qs = new URLSearchParams();
    qs.set("keyword", params.keyword);
    qs.set("country", params.country || "us");
    qs.set("remote", String(params.remote ?? true));
    qs.set("posted_within_days", String(params.posted_within_days ?? 1));
    qs.set("page", String(params.page ?? 1));
    return apiFetch<{ items: JobListing[]; count: number }>(`/api/jobs/search?${qs.toString()}`);
  },
};

export type JobBoard = {
  id: string;
  platform: string;
  company: string;
  board_url: string;
  added_at: string | null;
  last_synced_at: string | null;
  job_count: number;
};

export type PlatformCredential = {
  platform: string;
  label: string;
  has_key: boolean;
  updated_at: string | null;
  signup_url: string;
  signup_note: string;
};

export class ApiKeyRequiredError extends Error {
  platform: string;
  label: string;
  signupUrl: string;
  signupNote: string;
  constructor(platform: string, label: string, message: string, signupUrl: string, signupNote: string) {
    super(message);
    this.name = "ApiKeyRequiredError";
    this.platform = platform;
    this.label = label;
    this.signupUrl = signupUrl;
    this.signupNote = signupNote;
  }
}

type AddJobBoardResult = {
  board: JobBoard;
  added_count: number;
  skipped_duplicate_count: number;
  filtered_out_count: number;
};

export const jobBoardsApi = {
  // Admin-only on the backend (get_owner_user) — a non-owner call fails with 403.
  async add(url: string): Promise<AddJobBoardResult> {
    const authToken = getStoredToken();
    const headers = new Headers({ "Content-Type": "application/json" });
    if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
    const res = await fetch("/api/job-boards", {
      method: "POST",
      headers,
      body: JSON.stringify({ url }),
    });
    if (res.status === 428) {
      const data = await res.json().catch(() => ({}));
      const d = (data?.detail ?? {}) as {
        platform?: string;
        label?: string;
        message?: string;
        signup_url?: string;
        signup_note?: string;
      };
      throw new ApiKeyRequiredError(
        d.platform || "",
        d.label || "This platform",
        d.message || "This platform requires an API key.",
        d.signup_url || "",
        d.signup_note || "",
      );
    }
    if (!res.ok) throw new Error(await parseError(res));
    return (await res.json()) as AddJobBoardResult;
  },
  list() {
    return apiFetch<{ items: JobBoard[] }>("/api/job-boards");
  },
  remove(id: string) {
    return apiFetch<void>(`/api/job-boards/${id}`, { method: "DELETE" });
  },
  listJobs(platform?: string) {
    const qs = platform ? `?platform=${encodeURIComponent(platform)}` : "";
    return apiFetch<{ items: JobListing[]; count: number }>(`/api/job-boards/jobs${qs}`);
  },
  // Admin-only: manage per-platform API keys for sources that need them (e.g. ZipRecruiter).
  listPlatformCredentials() {
    return apiFetch<{ items: PlatformCredential[] }>("/api/job-boards/platform-credentials");
  },
  setPlatformCredential(platform: string, apiKey: string) {
    return apiFetch<PlatformCredential>(
      `/api/job-boards/platform-credentials/${encodeURIComponent(platform)}`,
      { method: "PUT", body: JSON.stringify({ api_key: apiKey }) },
    );
  },
  removePlatformCredential(platform: string) {
    return apiFetch<void>(`/api/job-boards/platform-credentials/${encodeURIComponent(platform)}`, {
      method: "DELETE",
    });
  },
};

export const resumeApi = {
  get() {
    return apiFetch<Record<string, unknown>>("/api/resume");
  },
  saveFromFile(file: File) {
    const body = new FormData();
    body.append("resume", file);
    return apiFetch<Record<string, unknown>>("/api/resume", { method: "POST", body });
  },
  remove() {
    return apiFetch<void>("/api/resume", { method: "DELETE" });
  },
};

export const adminApi = {
  listMembers() {
    return apiFetch<User[]>("/api/admin/members");
  },
  listTemplates() {
    return apiFetch<Array<{ key: string; label: string; description: string; accent_color: string; layout_family: string }>>(
      "/api/admin/templates",
    );
  },
  setMemberAccess(memberId: string, hasAccess: boolean) {
    return apiFetch<User>(`/api/admin/members/${memberId}/access`, {
      method: "PATCH",
      body: JSON.stringify({ has_access: hasAccess }),
    });
  },
  setMemberTemplate(memberId: string, templateKey: string | null) {
    return apiFetch<User>(`/api/admin/members/${memberId}/template`, {
      method: "PATCH",
      body: JSON.stringify({ template_key: templateKey }),
    });
  },
};

export type TailorResponse = {
  tailored_resume: string;
  tailored_contact: string;
  tailored_summary: string;
  tailored_experience: string;
  tailored_skills: string;
  tailored_education: string;
  tailored_other: string;
  docx_base64: string;
  download_filename: string;
  pdf_base64: string;
  pdf_download_filename: string;
  keywords_highlighted: string[];
  experience_keywords_highlighted: string[];
  skills_keywords_highlighted: string[];
  ats_tips: string[];
  used_llm: boolean;
  openai_configured?: boolean;
  llm_error?: string;
  enable_bold_applied: boolean;
  export_mode?: string;
  template_key?: string;
  template_label?: string;
  match_scores?: Record<string, number>;
  gap_report?: string[];
  clarifying_questions?: string[];
  integration_report?: string[];
  audit_report?: {
    validation?: { status?: string; issues?: Array<{ severity?: string; claim?: string; reason?: string }> };
    scoring?: Record<string, unknown>;
    bullet_audit?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
};

export type QualificationQuestion = {
  id: string;
  category: string;
  title: string;
  prompt: string;
  why_it_matters: string;
  detail_prompt: string;
  suggested_details: string[];
  missing_requirements: string[];
  confirmation_claim: string;
  example_answer: string;
  example_skills: string;
  skills_prompt: string;
  details_required_when_yes: boolean;
};

export type QualificationAnalysisResponse = {
  target_role: string;
  intro: string;
  questions: QualificationQuestion[];
  already_supported: string[];
  question_count: number;
};

export type CandidateQualificationAnswer = {
  question_id?: string;
  category?: string;
  question: string;
  answer: string;
};

export const tailorApi = {
  tailor(
    resume: File,
    jobDescription: string,
    enableBold = true,
    candidateAnswers: CandidateQualificationAnswer[] = [],
    confirmedSkills = "",
    confirmedExperience = "",
  ) {
    const body = new FormData();
    body.append("resume", resume);
    body.append("job_description", jobDescription);
    const verifiedAnswers = ([
      ...candidateAnswers,
      confirmedSkills.trim()
        ? { question: "Which missing skills can you personally confirm?", answer: confirmedSkills.trim() }
        : null,
      confirmedExperience.trim()
        ? { question: "What omitted experience can you personally confirm?", answer: confirmedExperience.trim() }
        : null,
    ] as Array<CandidateQualificationAnswer | null>).filter(
      (item): item is CandidateQualificationAnswer => Boolean(item),
    );
    if (verifiedAnswers.length) body.append("candidate_answers", JSON.stringify(verifiedAnswers));
    body.append("sample_mode", "true");
    body.append("enable_bold", enableBold ? "true" : "false");
    return apiFetch<TailorResponse>("/api/tailor", { method: "POST", body });
  },
  analyzeQualifications(resume: File, jobDescription: string) {
    const body = new FormData();
    body.append("resume", resume);
    body.append("job_description", jobDescription);
    return apiFetch<QualificationAnalysisResponse>("/api/qualification-analysis", {
      method: "POST",
      body,
    });
  },
};

export type CoverLetterResponse = {
  cover_letter: string;
  pdf_base64: string;
  pdf_download_filename: string;
  candidate_name: string;
  target_job_role: string;
  company_name: string;
  used_llm: boolean;
};

export const coverLetterApi = {
  generate(
    resume: File,
    jobDescription: string,
    companyName = "",
    targetJobRole = "",
  ) {
    const body = new FormData();
    body.append("resume", resume);
    body.append("job_description", jobDescription);
    if (targetJobRole.trim()) {
      body.append("target_job_role", targetJobRole.trim());
    }
    if (companyName.trim()) body.append("company_name", companyName.trim());
    return apiFetch<CoverLetterResponse>("/api/cover-letter", { method: "POST", body });
  },
};

export type CvTemplate = {
  key: string;
  label: string;
  description: string;
  status: "available" | "yours" | "taken";
  accent_color: string;
  layout_family: string;
};

export const cvTemplateApi = {
  list() {
    return apiFetch<CvTemplate[]>("/api/cv-templates");
  },
  mine() {
    return apiFetch<CvTemplate | null>("/api/cv-templates/mine");
  },
  select(templateKey: string) {
    return apiFetch<{ message: string; template_key: string; template_label: string }>(
      "/api/cv-templates/select",
      {
        method: "POST",
        body: JSON.stringify({ template_key: templateKey }),
      },
    );
  },
  previewPdfUrl(templateKey: string) {
    return `/api/cv-templates/${encodeURIComponent(templateKey)}/preview.pdf`;
  },
};

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type AnswerLength = "concise" | "standard" | "detailed";

export const applicationAnswerApi = {
  /**
   * Stream a resume-grounded answer to an application question. `onText` receives the
   * full answer so far after every chunk; resolves with the final text.
   */
  async stream(
    params: {
      question: string;
      resume: File | null;
      jobDescription: string;
      companyName: string;
      length: AnswerLength;
      history: ChatTurn[];
    },
    onText: (textSoFar: string) => void,
    signal?: AbortSignal,
  ): Promise<string> {
    const body = new FormData();
    body.append("question", params.question);
    body.append("job_description", params.jobDescription);
    body.append("company_name", params.companyName);
    body.append("length", params.length);
    body.append("history", JSON.stringify(params.history));
    if (params.resume) body.append("resume", params.resume);

    const token = getStoredToken();
    const res = await fetch("/api/application-answer", {
      method: "POST",
      body,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      signal,
    });
    if (!res.ok) throw new Error(await parseError(res));
    if (!res.body) throw new Error("Streaming is not supported by this browser.");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let text = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      text += decoder.decode(value, { stream: true });
      onText(text);
    }
    text += decoder.decode();
    return text;
  },
};
