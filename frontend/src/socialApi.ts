import type { CostStatus, Plan, PrivacyStatus, PublishItem, SocialConnection, SocialProvider, SocialVideo, Subscription, Usage, UserSettings } from "./types";
import { apiUrl } from "./runtime";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const csrf = sessionStorage.getItem("clipforge_csrf");
  if (csrf && (options.method || "GET").toUpperCase() !== "GET") headers.set("X-CSRF-Token", csrf);
  const response = await fetch(apiUrl(path), { ...options, headers, credentials: "include" });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "string" ? payload : payload?.detail || "Request failed";
    throw new Error(message);
  }
  return payload as T;
}

export async function getSocialProviders(): Promise<{ free_mode: boolean; providers: SocialProvider[] }> {
  return request("/api/social/providers");
}

export async function getSocialConnections(): Promise<{ connections: SocialConnection[] }> {
  return request("/api/social/connections");
}

export async function connectSocial(platform: string, purpose: "import" | "publish" = "import", redirectUri?: string): Promise<{ ok: boolean; configured: boolean; authorization_url?: string; message?: string }> {
  const redirect = redirectUri ? `&redirect_uri=${encodeURIComponent(redirectUri)}` : "";
  return request(`/api/social/${platform}/connect?purpose=${purpose}${redirect}`, { method: "GET" });
}

export async function disconnectSocial(id: string): Promise<void> {
  await request(`/api/social/connections/${id}`, { method: "DELETE" });
}

export async function getSocialVideos(platform: string, connectionId: string): Promise<{ platform: string; videos: SocialVideo[] }> {
  return request(`/api/social/${platform}/videos?connection_id=${encodeURIComponent(connectionId)}`);
}

export async function importSocialVideo(platform: string, payload: { connection_id: string; video_id: string; project_name: string; rights_acknowledged: boolean }): Promise<{ project: import("./types").Project }> {
  return request(`/api/social/${platform}/import`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function getCostStatus(): Promise<CostStatus> {
  return request("/api/cost-status");
}

export async function getFreeMode(): Promise<{ free_mode: boolean }> {
  return request("/api/settings");
}

export async function setFreeMode(free_mode: boolean): Promise<{ free_mode: boolean }> {
  return request("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ free_mode }) });
}

export async function getPlans(): Promise<{ plans: Plan[]; billing_configured: boolean; note: string }> {
  return request("/api/plans");
}

export async function getSubscription(): Promise<Subscription> {
  return request("/api/subscription");
}

export async function getUsage(): Promise<Usage> {
  return request("/api/usage");
}

export async function requestPlanInterest(plan_id: string, contact = "", note = ""): Promise<{ id: string; status: string; message: string }> {
  return request("/api/subscription/interest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan_id, contact, note }) });
}

export async function getBillingStatus(): Promise<{ configured: boolean; provider: string; message: string }> {
  return request("/api/billing/status");
}

export async function createCheckout(plan_id: string): Promise<{ configured: boolean; provider?: string; checkout_type?: string; key_id?: string; message: string; order?: Record<string, unknown>; provider_payload?: Record<string, unknown>; short_url?: string; subscription_id?: string }> {
  return request("/api/billing/checkout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan_id }) });
}

export async function verifyCheckout(payload: Record<string, string>): Promise<{ verified: boolean; status: string; message: string }> {
  return request("/api/billing/verify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function getBillingDashboard(): Promise<{ subscription: Record<string, unknown> | null; payments: Record<string, unknown>[]; invoices: Record<string, unknown>[]; provider: { configured: boolean; provider: string } }> {
  return request("/api/billing/dashboard");
}

export async function cancelBillingSubscription(cancel_at_cycle_end = true): Promise<{ message: string }> {
  return request("/api/billing/subscription/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cancel_at_cycle_end }) });
}

export async function getPrivacy(): Promise<PrivacyStatus> {
  return request("/api/privacy");
}

export async function setPrivacy(enabled: boolean): Promise<{ enabled: boolean; status: PrivacyStatus }> {
  return request("/api/privacy", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
}

export async function getUserSettings(): Promise<{ settings: UserSettings }> {
  return request("/api/user-settings");
}

export async function setUserSettings(settings: UserSettings): Promise<{ settings: UserSettings }> {
  return request("/api/user-settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) });
}

export async function queuePublish(payload: { clip_id: string; platform: string; account_id?: string | null; caption: string; title: string; hashtags: string[]; visibility: string; scheduled_at?: string | null; rights_acknowledged: boolean }): Promise<{ item: PublishItem; message: string }> {
  return request("/api/publishing/queue", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

export async function publishQueued(id: string): Promise<{ item: PublishItem }> {
  return request(`/api/publishing/queue/${id}/publish`, { method: "POST" });
}

export async function getPublishQueue(): Promise<{ items: PublishItem[] }> {
  return request("/api/publishing/queue");
}

export async function uploadLibraryAsset(kind: "music" | "sfx", file: File, license: string, artist: string): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(apiUrl(`/api/library/${kind}/upload?license=${encodeURIComponent(license)}&artist=${encodeURIComponent(artist)}`), { method: "POST", body: form, credentials: "include", headers: { "X-CSRF-Token": sessionStorage.getItem("clipforge_csrf") || "" } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Could not upload library asset.");
  }
}

export async function deleteLibraryAsset(kind: "music" | "sfx", id: string): Promise<void> {
  await request(`/api/library/${kind}/${encodeURIComponent(id)}`, { method: "DELETE" });
}
