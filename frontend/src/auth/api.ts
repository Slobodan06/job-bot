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

async function parseError(res: Response): Promise<string> {
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
  ats_tips: string[];
  used_llm: boolean;
};

export const tailorApi = {
  tailor(resume: File, jobDescription: string) {
    const body = new FormData();
    body.append("resume", resume);
    body.append("job_description", jobDescription);
    return apiFetch<TailorResponse>("/api/tailor", { method: "POST", body });
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
