import { apiUrl } from "./runtime";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  profile_photo_url?: string | null;
  country: string;
  language: string;
  timezone: string;
  plan_id: string;
  email_verified: boolean;
  is_admin: boolean;
  notification_preferences: Record<string, boolean>;
  theme: string;
  created_at: string;
  last_login_at?: string | null;
}

export interface AuthState {
  authenticated: boolean;
  user: AuthUser | null;
  csrf_token?: string;
  session?: { id: string; expires_at: string };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const csrf = sessionStorage.getItem("clipforge_csrf");
  if (csrf && (options.method || "GET").toUpperCase() !== "GET") headers.set("X-CSRF-Token", csrf);
  const response = await fetch(apiUrl(path), { ...options, headers, credentials: "include" });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "string" ? payload : payload?.detail || payload?.message || "Request failed";
    throw new Error(message);
  }
  if (payload?.csrf_token) sessionStorage.setItem("clipforge_csrf", payload.csrf_token);
  return payload as T;
}

export function getAuth(): Promise<AuthState> {
  return request<AuthState>("/api/auth/me");
}

export function register(email: string, password: string, name: string, remember_me: boolean): Promise<AuthState & { verification_link?: string; email_verification_required?: boolean }> {
  return request("/api/auth/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password, name, remember_me }) });
}

export function login(email: string, password: string, remember_me: boolean): Promise<AuthState> {
  return request("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password, remember_me }) });
}

export function logout(): Promise<{ ok: boolean }> {
  return request("/api/auth/logout", { method: "POST" });
}

export function forgotPassword(email: string): Promise<{ ok: boolean; message: string; reset_link?: string }> {
  return request("/api/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
}

export function resetPassword(token: string, password: string): Promise<{ ok: boolean; message: string }> {
  return request("/api/auth/reset-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password }) });
}

export function verifyEmail(token: string): Promise<{ verified: boolean; message: string }> {
  return request("/api/auth/verify-email", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
}

export function consumeMagicLink(token: string): Promise<AuthState> {
  return request("/api/auth/magic-link/consume", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
}

export function requestMagicLink(email: string): Promise<{ ok: boolean; message: string; magic_link?: string }> {
  return request("/api/auth/magic-link", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
}

export function getOAuthUrl(provider: "google" | "github"): Promise<{ provider: string; url: string }> {
  return request(`/api/auth/oauth/${provider}/start`);
}

export function updateProfile(profile: Partial<AuthUser>): Promise<{ user: AuthUser }> {
  return request("/api/auth/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
}

export function uploadProfilePhoto(file: File): Promise<{ user: AuthUser }> {
  const form = new FormData(); form.append("file", file);
  return request("/api/auth/profile/photo", { method: "POST", body: form });
}

export function changePassword(current_password: string, new_password: string): Promise<{ ok: boolean; message: string }> {
  return request("/api/auth/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_password, new_password }) });
}

export function getSessions(): Promise<{ sessions: Array<Record<string, string | number>>; current_session_id?: string | null }> {
  return request("/api/auth/sessions");
}

export function revokeSession(id: string): Promise<{ ok: boolean }> {
  return request(`/api/auth/sessions/${id}`, { method: "DELETE" });
}
