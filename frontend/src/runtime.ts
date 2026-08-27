const configuredApi = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export function apiUrl(path: string): string {
  if (!configuredApi || /^https?:\/\//i.test(path)) return path;
  return `${configuredApi}${path}`;
}

export const API_BASE_URL = configuredApi;
