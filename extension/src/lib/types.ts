export type DetectedJob = {
  url: string;
  text: string;
  page_title: string;
  company: string;
  job_title: string;
  location: string;
  ats: string;
};

export type FormField = {
  key: string;
  label: string;
  name: string;
  id: string;
  type: string;
  placeholder: string;
  autocomplete: string;
  aria_label: string;
  required: boolean;
  options: string[];
  // Set when the field lives inside a numbered repeated block ("Work
  // Experience 2", "Education 1", ...) so it can be mapped to that specific
  // resume entry instead of a single flat "current employer" answer.
  group_kind: "experience" | "education" | "";
  group_index: number | null;
};

export type AutofillValue = {
  value: string;
  source: string;
  confidence: number;
  canonical: string;
};

export type ResumeAttachment = {
  variant_id: string;
  filename: string;
  download_path: string;
  kind?: string;
};

export type AutofillResponse = {
  values: Record<string, AutofillValue>;
  answers: Record<string, string>;
  resume: ResumeAttachment | null;
  application_id: string | null;
  unfilled: string[];
};

export type TailorForJobResponse = {
  resume: ResumeAttachment;
  docx_variant_id: string;
  match_scores: Record<string, number>;
  application_id: string | null;
};

export type ExtensionProfile = {
  name: string;
  email: string;
  has_base_resume: boolean;
  autofill_profile: Record<string, unknown>;
};

export type Application = {
  id: string;
  job_url: string;
  ats: string;
  company: string;
  job_title: string;
  location: string;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  submitted_at: string | null;
};

export type ApplicationStats = { total: number; by_status: Record<string, number> };

export type AuthState = { token: string | null; email: string | null };
