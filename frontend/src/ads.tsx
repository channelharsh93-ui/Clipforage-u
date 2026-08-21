import { useEffect, useState } from "react";
import { apiUrl } from "./runtime";

interface AdPayload {
  id: string;
  label: string;
  title: string;
  body: string;
  accent: string;
  click_url?: string | null;
  page: string;
  device: string;
}

function sessionId() {
  const key = "clipforge-ad-session";
  const existing = window.sessionStorage.getItem(key);
  if (existing) return existing;
  const next = `s_${crypto.randomUUID?.() || Math.random().toString(36).slice(2)}`;
  window.sessionStorage.setItem(key, next);
  return next;
}

export function AdSlot({ page, compact = false }: { page: "dashboard" | "sidebar" | "results" | "content-packs"; compact?: boolean }) {
  const [ad, setAd] = useState<AdPayload | null>(null);
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const device = window.innerWidth <= 700 ? "mobile" : "desktop";
        const response = await fetch(apiUrl(`/api/ads/next?session_id=${encodeURIComponent(sessionId())}&page=${page}&device=${device}`), { credentials: "include" });
        const result = await response.json();
        if (!cancelled && result.show && result.ad) {
          setAd(result.ad);
          void fetch(apiUrl("/api/ads/impression"), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": sessionStorage.getItem("clipforge_csrf") || "" }, body: JSON.stringify({ ad_id: result.ad.id, page, device }) });
        }
      } catch {
        // Ads are optional. Collapse the placement if the provider is unavailable.
      }
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [page]);
  if (!ad) return null;
  const click = () => { if (!ad.click_url) return; void fetch(apiUrl("/api/ads/click"), { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", "X-CSRF-Token": sessionStorage.getItem("clipforge_csrf") || "" }, body: JSON.stringify({ ad_id: ad.id, page, device: window.innerWidth <= 700 ? "mobile" : "desktop" }) }); window.open(ad.click_url, "_blank", "noopener,noreferrer"); };
  return <section className={`ad-slot ${compact ? "compact" : ""} accent-${ad.accent}`} aria-label="Advertisement"><div className="ad-slot-label"><span>Sponsored</span><small>Advertisement</small></div><div className="ad-slot-content"><div className="ad-spark">✦</div><div><strong>{ad.title}</strong><p>{ad.body}</p></div>{ad.click_url && <button className="ad-action" onClick={click}>Learn more</button>}</div></section>;
}
