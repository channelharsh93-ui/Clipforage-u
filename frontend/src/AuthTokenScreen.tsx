import { useEffect, useState } from "react";
import { consumeMagicLink, resetPassword, verifyEmail } from "./authApi";
import type { AuthState } from "./authApi";

export function AuthTokenScreen({ kind, token, onAuthenticated, onBack }: { kind: "verify" | "magic" | "reset"; token: string; onAuthenticated: (state: AuthState) => void; onBack: () => void }) {
  const [message, setMessage] = useState("Working securely…");
  const [busy, setBusy] = useState(kind !== "reset");
  const [password, setPassword] = useState("");
  useEffect(() => {
    if (kind === "reset") return;
    (async () => {
      try {
        if (kind === "verify") { const result = await verifyEmail(token); setMessage(result.message); }
        else { const result = await consumeMagicLink(token); setMessage("Signed in successfully."); onAuthenticated(result); }
      } catch (error) { setMessage(error instanceof Error ? error.message : "This link is invalid or expired."); }
      finally { setBusy(false); }
    })();
  }, [kind, token, onAuthenticated]);
  const submitReset = async () => { setBusy(true); try { const result = await resetPassword(token, password); setMessage(result.message); } catch (error) { setMessage(error instanceof Error ? error.message : "Could not reset the password."); } finally { setBusy(false); } };
  return <div className="auth-shell"><div className="auth-card auth-token-card"><div className="auth-brand"><span>✦</span><div><strong>ClipForge</strong><small>SECURE ACCOUNT ACCESS</small></div></div><span className="eyebrow">{kind === "verify" ? "EMAIL VERIFICATION" : kind === "magic" ? "MAGIC SIGN-IN" : "PASSWORD RESET"}</span><h1>{kind === "verify" ? "Verify your email" : kind === "magic" ? "Signing you in" : "Choose a new password"}</h1>{kind === "reset" && <div className="auth-form"><label><span>New password</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters with a number" /></label><button className="primary-button auth-submit" disabled={busy} onClick={() => void submitReset()}>{busy ? "Saving…" : "Reset password"}</button></div>}<div className="auth-notice info">{message}</div>{!busy && <button className="secondary-button auth-submit" onClick={onBack}>Continue to login</button>}</div></div>;
}
