import type { Clip, ClipTemplate, CostStatus, LibraryAsset, ProcessingQueue, Project, ProjectStatusResponse, PublishItem, SocialConnection, SocialProvider, SocialVideo, SystemStatus } from "./types";
import { apiUrl } from "./runtime";

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
  return payload as T;
}

export async function getProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export async function getStats(): Promise<{ projects: number; clips: number; ready_clips: number; videos_processed: number; avg_processing_seconds: number | null }> {
  return request("/api/stats");
}

export async function getProcessingQueue(): Promise<ProcessingQueue> {
  return request("/api/queue");
}

export async function getSystemStatus(): Promise<SystemStatus> {
  return request("/api/system/status");
}

export async function getTemplates(): Promise<{ templates: ClipTemplate[] }> {
  return request("/api/templates");
}

export async function applyTemplate(clipId: string, templateId: string): Promise<{ clip: Clip; template: ClipTemplate }> {
  return request(`/api/clips/${clipId}/template`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template_id: templateId }) });
}

export async function getProject(id: string): Promise<Project> {
  return request<Project>(`/api/projects/${id}`);
}

export async function deleteProject(id: string): Promise<void> {
  await request(`/api/projects/${id}`, { method: "DELETE" });
}

export async function createProject(name: string, rights_acknowledged: boolean): Promise<Project> {
  return request<Project>("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, rights_acknowledged }),
  });
}

export async function uploadVideo(projectId: string, file: File): Promise<{ project: Project; size_bytes: number }> {
  const form = new FormData();
  form.append("file", file);
  return request(`/api/projects/${projectId}/upload`, { method: "POST", body: form });
}

export async function importVideoUrl(projectId: string, url: string): Promise<{ project: Project; size_bytes: number }> {
  return request(`/api/projects/${projectId}/import-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
}

export async function analyzeProject(id: string): Promise<{ project: Project; message: string }> {
  return request(`/api/projects/${id}/analyze`, { method: "POST" });
}

export async function getProjectStatus(id: string): Promise<ProjectStatusResponse> {
  return request(`/api/projects/${id}/status`);
}

export async function retryProject(id: string): Promise<{ project: Project; message: string }> {
  return request(`/api/projects/${id}/retry`, { method: "POST" });
}

export async function getContentPack(id: string): Promise<{ content_pack: import("./types").ContentPack | null; premium_required?: boolean; message?: string; updated_at?: string | null }> {
  return request(`/api/clips/${id}/content-pack`);
}

export async function regenerateContentPack(id: string, language = "en", tone = "casual", variant = 0): Promise<{ content_pack: import("./types").ContentPack; updated_at: string }> {
  return request(`/api/clips/${id}/content-pack/regenerate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language, tone, variant }) });
}

export async function generateThumbnail(id: string, time_offset: number, text: string, position: string): Promise<{ clip: Clip; message: string }> {
  return request(`/api/clips/${id}/thumbnail`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ time_offset, text, position }) });
}

export async function updateClip(id: string, patch: Partial<Clip>): Promise<Clip> {
  return request(`/api/clips/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function renderClip(id: string): Promise<{ job: { id: string }; clip: Clip }> {
  return request(`/api/clips/${id}/render`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
}

export async function getRenderJob(id: string): Promise<{ id: string; status: string; progress: number; message?: string }> {
  return request(`/api/render-jobs/${id}`);
}

export async function deleteClip(id: string): Promise<void> {
  await request(`/api/clips/${id}`, { method: "DELETE" });
}

export async function uploadLogo(projectId: string, file: File): Promise<{ logo_url: string }> {
  const form = new FormData();
  form.append("file", file);
  return request(`/api/projects/${projectId}/logo`, { method: "POST", body: form });
}

export async function getLibrary(): Promise<{ music: LibraryAsset[]; sfx: LibraryAsset[] }> {
  return request("/api/library");
}
