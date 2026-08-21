const configuredApi = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

if (import.meta.env.PROD && !configuredApi) {
  // On Vercel the frontend is static-only; the FastAPI backend must run elsewhere.
  // Without VITE_API_BASE_URL, every /api/* fetch hits the Vercel domain itself,
  // gets caught by the SPA rewrite in vercel.json, and silently returns index.html
  // instead of JSON — which looks like "everything is broken" with no clear error.
  // eslint-disable-next-line no-console
  console.error(
    "[ClipForge] VITE_API_BASE_URL is not set. API requests will be sent to this " +
      "same domain and rewritten to index.html by vercel.json, causing JSON parse " +
      "errors on every request. Set VITE_API_BASE_URL to your deployed backend URL " +
      "(e.g. https://api.yourdomain.com) in Vercel → Project → Settings → Environment Variables, " +
      "then redeploy.",
  );
}

export function apiUrl(path: string): string {
  if (!configuredApi || /^https?:\/\//i.test(path)) return path;
  return `${configuredApi}${path}`;
}

export const API_BASE_URL = configuredApi;
