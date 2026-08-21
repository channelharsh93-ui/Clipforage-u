import { useState } from "react";
import { forgotPassword, getOAuthUrl, login, register, requestMagicLink, resetPassword, verifyEmail, consumeMagicLink } from "./authApi";
import type { AuthState } from "./authApi";

export function AuthScreen({ onAuthenticated, onBack }: { onAuthenticated: (state: AuthState) => void; onBack: () => void }) {
  const [mode, setMode] = useState<"login" | "register" | "forgot" | "magic">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ type: "error" | "info"; text: string } | null>(null);
  const [devLink, setDevLink] = useState("");

  const submit = async () => {
    setBusy(true); setNotice(null); setDevLink("");
    try {
      if (mode === "login") onAuthenticated(await login(email, password, remember));
      else if (mode === "register") {
        const result = await register(email, password, name, remember);
        if (result.verification_link) setDevLink(result.verification_link);
        setNotice({ type: "info", text: "Account created. Check your email to verify the address before publishing." });
        onAuthenticated(result);
      } else if (mode === "forgot") {
        const result = await forgotPassword(email);
        if (result.reset_link) setDevLink(result.reset_link);
        setNotice({ type: "info", text: result.message });
      } else {
        const result = await requestMagicLink(email);
        if (result.magic_link) setDevLink(result.magic_link);
        setNotice({ type: "info", text: result.message });
      }
    } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Authentication request failed." }); }
    finally { setBusy(false); }
  };

  const oauth = async (provider: "google" | "github") => {
    try { const result = await getOAuthUrl(provider); window.location.href = result.url; }
    catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : `${provider} Sign-In is not configured.` }); }
  };

  const heading = mode === "register" ? "Create your ClipForge account" : mode === "forgot" ? "Reset your password" : mode === "magic" ? "Get a magic sign-in link" : "Welcome back to ClipForge";
  return <div className="auth-shell"><div className="auth-card"><button className="auth-back" onClick={onBack}>← Back to ClipForge</button><div className="auth-brand"><span>✦</span><div><strong>ClipForge</strong><small>LOCAL-FIRST CONTENT STUDIO</small></div></div><span className="eyebrow">SECURE ACCOUNT ACCESS</span><h1>{heading}</h1><p className="auth-lede">Your workspace, projects, and billing history stay tied to your account.</p>{mode === "login" || mode === "register" ? <div className="oauth-buttons"><button onClick={() => void oauth("google")}><b>G</b> Continue with Google</button><button onClick={() => void oauth("github")}><b>⌘</b> Continue with GitHub</button></div> : null}{mode === "login" || mode === "register" ? <div className="auth-divider"><span>or use email</span></div> : null}<div className="auth-form">{mode === "register" && <label><span>Name</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Your name" autoComplete="name" /></label>}<label><span>Email</span><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" autoComplete="email" /></label>{(mode === "login" || mode === "register") && <label><span>Password</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters with a number" autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>}{(mode === "login" || mode === "register") && <label className="auth-check"><input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} /><span>Remember this device</span></label>}<button className="primary-button auth-submit" onClick={() => void submit()} disabled={busy}>{busy ? "Please wait…" : mode === "register" ? "Create account" : mode === "forgot" ? "Send reset link" : mode === "magic" ? "Send sign-in link" : "Log in"}</button></div>{notice && <div className={`auth-notice ${notice.type}`}>{notice.text}</div>}{devLink && <div className="auth-dev-link"><strong>Local development link</strong><a href={devLink}>{devLink}</a></div>}<div className="auth-links">{mode === "login" && <><button onClick={() => setMode("register")}>Create an account</button><button onClick={() => setMode("forgot")}>Forgot password?</button><button onClick={() => setMode("magic")}>Use a magic link</button></>}{mode !== "login" && <button onClick={() => setMode("login")}>Back to login</button>}</div><p className="auth-legal">By continuing, you confirm you will only upload and publish content you own or are authorized to use.</p></div></div>;
}
