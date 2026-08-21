import { useEffect, useMemo, useRef, useState } from "react";
import { getAuth, logout } from "./authApi";
import type { AuthState } from "./authApi";
import { AuthScreen } from "./AuthScreen";
import { AuthTokenScreen } from "./AuthTokenScreen";
import { BillingView } from "./BillingView";
import { AdminView } from "./AdminView";
import { AccountView } from "./AccountView";
import {
  analyzeProject,
  applyTemplate,
  createProject,
  deleteClip,
  deleteProject,
  generateThumbnail,
  getContentPack,
  getLibrary,
  getProcessingQueue,
  getProject,
  getProjects,
  getRenderJob,
  getStats,
  getSystemStatus,
  getTemplates,
  importVideoUrl,
  renderClip,
  regenerateContentPack,
  retryProject,
  updateClip,
  uploadLogo,
  uploadVideo,
} from "./api";
import { connectSocial, deleteLibraryAsset, disconnectSocial, getCostStatus, getFreeMode, getPublishQueue, getSocialConnections, getSocialProviders, getSocialVideos, importSocialVideo, publishQueued, queuePublish, setFreeMode, uploadLibraryAsset } from "./socialApi";
import type { Clip, ClipTemplate, ContentPack, LibraryAsset, ProcessingQueue, Project, SocialConnection, SocialProvider, SystemStatus } from "./types";
import { CostSettings, PlansView, PlatformsView, PublishingView } from "./socialViews";
import { AdSlot } from "./ads";
import LandingPage from "./LandingPage";

const pipeline = [
  ["uploaded", "Upload", "File is safely stored locally"],
  ["transcribing", "Transcribe", "Local Whisper word timestamps"],
  ["detecting_scenes", "Understand", "Scene and audio signals"],
  ["detecting_highlights", "Find highlights", "Context-aware candidates"],
  ["scoring_moments", "Rank moments", "Multi-signal scoring"],
  ["creating_clips", "Create clips", "Context windows and exports"],
  ["adding_captions", "Captions", "Synchronized mobile captions"],
  ["generating_content", "Content pack", "Hooks, titles, descriptions"],
  ["seo_analysis", "SEO", "Keywords and platform metadata"],
  ["finished", "Ready", "Preview, edit and download"],
] as const;

const categoryColors: Record<string, string> = {
  FUNNY: "orange",
  COMEDY: "orange",
  DRAMATIC: "rose",
  ACTION: "cyan",
  EMOTIONAL: "pink",
  SHOCKING: "red",
  MOTIVATIONAL: "green",
  EDUCATIONAL: "blue",
  STORY: "violet",
  REACTION: "yellow",
  SUSPENSE: "purple",
  DEBATE: "indigo",
  INTERESTING: "slate",
  OTHER: "slate",
};

function formatTime(value = 0) {
  const seconds = Math.max(0, Math.floor(value));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function isProcessing(status?: string) {
  return ["preparing", "transcribing", "detecting_scenes", "detecting_highlights", "scoring_moments", "creating_clips", "adding_captions", "generating_content", "seo_analysis"].includes(status || "");
}

function Icon({ name }: { name: "spark" | "play" | "upload" | "plus" | "arrow" | "edit" | "download" | "trash" | "refresh" | "folder" | "grid" | "settings" | "clock" | "check" | "close" | "link" }) {
  const paths: Record<string, string> = {
    spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Zm7 10 .9 2.1L22 16l-2.1.9L19 19l-.9-2.1L16 16l2.1-.9L19 13ZM5 16l.7 1.8L7.5 18l-1.8.7L5 20.5l-.7-1.8L2.5 18l1.8-.7L5 16Z",
    play: "M8 5v14l11-7L8 5Z",
    upload: "M12 16V4m0 0 4 4m-4-4L8 8M5 14v4h14v-4",
    plus: "M12 5v14m-7-7h14",
    arrow: "M5 12h14m-6-6 6 6-6 6",
    edit: "m4 20 4.2-1 9.9-9.9a2.1 2.1 0 0 0-3-3L5.2 16 4 20Zm9.8-12.8 3 3",
    download: "M12 4v11m0 0 4-4m-4 4-4-4M5 20h14",
    trash: "M5 7h14m-9 4v5m4-5v5M9 7V4h6v3m-8 0 1 13h8l1-13",
    refresh: "M20 11a8 8 0 0 0-14.9-3M5 4v4h4m-5 5a8 8 0 0 0 14.9 3M19 20v-4h-4",
    folder: "M3 7.5h6l2 2H21v8.7a1.8 1.8 0 0 1-1.8 1.8H4.8A1.8 1.8 0 0 1 3 18.2V7.5Zm0 0V5.8A1.8 1.8 0 0 1 4.8 4h3.7l2 2H19a2 2 0 0 1 2 2v1.5",
    grid: "M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z",
    settings: "M12 8.5A3.5 3.5 0 1 0 12 15.5 3.5 3.5 0 0 0 12 8.5Zm0-5v2m0 13v2m9-8h-2M5 12H3m15.4-6.4-1.4 1.4M7 17l-1.4 1.4m12.8 0L17 17M7 7 5.6 5.6",
    clock: "M12 7v5l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
    check: "m5 12 4 4L19 6",
    close: "m6 6 12 12M18 6 6 18",
    link: "M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1m-1 8.9a5 5 0 0 1-7.1-.1 5 5 0 0 1 0-7.1l2-2A5 5 0 0 1 12 5.8",
  };
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]} /></svg>;
}

function WorkspaceApp({ auth, onLogout }: { auth: AuthState; onLogout: () => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [stats, setStats] = useState({ projects: 0, clips: 0, ready_clips: 0, videos_processed: 0, avg_processing_seconds: null as number | null });
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null);
  const [page, setPage] = useState<"projects" | "content-packs" | "templates" | "platforms" | "publishing" | "plans" | "billing" | "admin" | "account" | "assets" | "settings">("projects");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ type: "error" | "success" | "info"; text: string } | null>(null);

  const refresh = async () => {
    try {
      const [nextProjects, nextStats] = await Promise.all([getProjects(), getStats()]);
      setProjects(nextProjects);
      setStats(nextStats);
      if (activeProject) {
        const next = await getProject(activeProject.id);
        setActiveProject(next);
        if (selectedClip) setSelectedClip(next.clips?.find((clip) => clip.id === selectedClip.id) || null);
      }
    } catch (error) {
      setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not load projects." });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, []);

  useEffect(() => {
    if (!activeProject || !isProcessing(activeProject.status)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getProject(activeProject.id);
        if (!cancelled) setActiveProject(next);
      } catch (error) {
        if (!cancelled) setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not read processing status." });
      }
    };
    const timer = window.setInterval(poll, 1600);
    void poll();
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [activeProject?.id, activeProject?.status]);

  const openProject = async (id: string) => {
    try {
      setLoading(true);
      const project = await getProject(id);
      setActiveProject(project);
      setPage("projects");
    } catch (error) {
      setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not open project." });
    } finally { setLoading(false); }
  };

  const closeProject = () => { setSelectedClip(null); setActiveProject(null); void refresh(); };

  return (
    <div className="app-shell">
      <Sidebar page={page} setPage={(next) => { setPage(next); setActiveProject(null); setSelectedClip(null); }} showAd={!activeProject && page === "projects"} onNew={() => { setPage("projects"); setActiveProject(null); }} auth={auth} />
      <main className="main-shell">
        <Topbar activeProject={activeProject} onBack={closeProject} onRefresh={refresh} auth={auth} onLogout={onLogout} />
        {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}
        {page === "projects" && !activeProject && <Dashboard projects={projects} stats={stats} loading={loading} onOpen={openProject} onPlatforms={() => setPage("platforms")} onCreated={async (project) => { setActiveProject(project); await refresh(); }} setNotice={setNotice} />}
        {page === "projects" && activeProject && <Workspace project={activeProject} showAds={!selectedClip} onBack={closeProject} onRefresh={refresh} onRetry={async () => { try { const result = await retryProject(activeProject.id); setActiveProject(result.project); setNotice({ type: "success", text: "Project retry started." }); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not retry project." }); } }} onDelete={async () => { if (!window.confirm(`Delete project \"${activeProject.name}\" and all generated clips?`)) return; try { await deleteProject(activeProject.id); setSelectedClip(null); setActiveProject(null); await refresh(); setNotice({ type: "success", text: "Project deleted." }); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not delete project." }); } }} onSelectClip={setSelectedClip} onDeleteClip={async (id) => { await deleteClip(id); const next = await getProject(activeProject.id); setActiveProject(next); setNotice({ type: "success", text: "Clip deleted." }); }} />}
        {page === "content-packs" && <ContentPacksView />}
        {page === "templates" && <TemplatesView setNotice={setNotice} />}
        {page === "platforms" && <PlatformsView onImported={async (project) => { await analyzeProject(project.id); setActiveProject(await getProject(project.id)); setPage("projects"); await refresh(); }} setNotice={setNotice} />}
        {page === "publishing" && <PublishingView setNotice={setNotice} />}
        {page === "plans" && <PlansView setNotice={setNotice} />}
        {page === "billing" && <BillingView setNotice={setNotice} />}
        {page === "admin" && <AdminView setNotice={setNotice} />}
        {page === "account" && <AccountView setNotice={setNotice} />}
        {page === "assets" && <AssetsView />}
        {page === "settings" && <CostSettings setNotice={setNotice} />}
      </main>
      {selectedClip && activeProject && <EditorPanel project={activeProject} clip={selectedClip} onClose={() => setSelectedClip(null)} onSaved={async () => { const next = await getProject(activeProject.id); setActiveProject(next); setSelectedClip(next.clips?.find((clip) => clip.id === selectedClip.id) || null); await refresh(); }} setNotice={setNotice} />}
    </div>
  );
}

function Sidebar({ page, setPage, showAd, onNew, auth }: { page: string; setPage: (page: "projects" | "content-packs" | "templates" | "platforms" | "publishing" | "plans" | "billing" | "admin" | "account" | "assets" | "settings") => void; showAd: boolean; onNew: () => void; auth: AuthState }) {
  return <aside className="sidebar">
    <div className="brand" onClick={onNew}><div className="brand-mark"><Icon name="spark" /></div><div><strong>ClipForge</strong><span>local AI studio</span></div></div>
    <button className="new-project-button" onClick={onNew}><Icon name="plus" /> New project</button>
    <nav className="side-nav">
      <button className={page === "projects" ? "active" : ""} onClick={() => setPage("projects")}><Icon name="grid" /><span>Projects</span><span className="nav-count">⌘ 1</span></button>
      <button className={page === "content-packs" ? "active" : ""} onClick={() => setPage("content-packs")}><Icon name="spark" /><span>Content packs</span></button>
      <button className={page === "templates" ? "active" : ""} onClick={() => setPage("templates")}><Icon name="spark" /><span>Templates</span></button>
      <button className={page === "platforms" ? "active" : ""} onClick={() => setPage("platforms")}><Icon name="link" /><span>Platforms</span></button>
      <button className={page === "publishing" ? "active" : ""} onClick={() => setPage("publishing")}><Icon name="arrow" /><span>Publishing</span></button>
      <button className={page === "plans" ? "active" : ""} onClick={() => setPage("plans")}><Icon name="spark" /><span>Plans</span></button>
      <button className={page === "billing" ? "active" : ""} onClick={() => setPage("billing")}><Icon name="spark" /><span>Billing</span></button>
      {auth.user?.is_admin && <button className={page === "admin" ? "active" : ""} onClick={() => setPage("admin")}><Icon name="settings" /><span>Admin</span></button>}
      <button className={page === "account" ? "active" : ""} onClick={() => setPage("account")}><Icon name="settings" /><span>Account</span></button>
      <button className={page === "assets" ? "active" : ""} onClick={() => setPage("assets")}><Icon name="folder" /><span>Assets</span></button>
      <button className={page === "settings" ? "active" : ""} onClick={() => setPage("settings")}><Icon name="settings" /><span>Settings</span></button>
    </nav>
    <div className="sidebar-bottom">
      <div className="free-card"><span className="tiny-label">FREE MODE</span><strong>Local-first processing</strong><p>No paid APIs or cloud GPU required.</p><div className="progress-track"><span style={{ width: "100%" }} /></div></div>
      {showAd && <AdSlot page="sidebar" compact />}
      <div className="user-row"><div className="avatar">{(auth.user?.name || auth.user?.email || "CF").slice(0, 2).toUpperCase()}</div><div><strong>{auth.user?.name || "Creator workspace"}</strong><span>{auth.user?.plan_id === "pro" ? "Pro plan" : auth.user?.email || "Free plan"}</span></div><span className="status-dot" /></div>
    </div>
  </aside>;
}

function Topbar({ activeProject, onBack, onRefresh, auth, onLogout }: { activeProject: Project | null; onBack: () => void; onRefresh: () => void; auth: AuthState; onLogout: () => void }) {
  return <header className="topbar">
    <div className="breadcrumbs"><span className="eyebrow">WORKSPACE</span>{activeProject ? <><span className="crumb-slash">/</span><button className="crumb-link" onClick={onBack}>Projects</button><span className="crumb-slash">/</span><strong>{activeProject.name}</strong></> : <strong>Projects</strong>}</div>
    <div className="topbar-actions"><span className="local-pill"><span className="status-dot" /> Local mode</span><button className="icon-button" title="Refresh" onClick={onRefresh}><Icon name="refresh" /></button><div className="account-chip"><div className="top-avatar">{(auth.user?.name || auth.user?.email || "A").slice(0, 1).toUpperCase()}</div><span>{auth.user?.name || auth.user?.email}</span><button onClick={onLogout}>Log out</button></div></div>
  </header>;
}

function Notice({ notice, onClose }: { notice: { type: string; text: string }; onClose: () => void }) {
  return <div className={`notice ${notice.type}`}><span>{notice.type === "error" ? "!" : notice.type === "success" ? "✓" : "i"}</span><p>{notice.text}</p><button onClick={onClose}><Icon name="close" /></button></div>;
}

function Dashboard({ projects, stats, loading, onOpen, onPlatforms, onCreated, setNotice }: { projects: Project[]; stats: { projects: number; clips: number; ready_clips: number; videos_processed: number; avg_processing_seconds: number | null }; loading: boolean; onOpen: (id: string) => void; onPlatforms: () => void; onCreated: (project: Project) => Promise<void>; setNotice: (notice: { type: "error" | "success" | "info"; text: string }) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rights, setRights] = useState(false);
  const [busy, setBusy] = useState(false);
  const [queue, setQueue] = useState<ProcessingQueue>({ projects: [], render_jobs: [] });
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const loadQueue = async () => { try { const next = await getProcessingQueue(); if (!cancelled) setQueue(next); } catch { /* dashboard can still work without queue telemetry */ } };
    void loadQueue();
    const timer = window.setInterval(loadQueue, 1800);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const start = async () => {
    if (!file && !url.trim()) { setNotice({ type: "error", text: "Choose a video file or provide a direct video URL." }); return; }
    if (!rights) { setNotice({ type: "error", text: "Please confirm that you own or have permission to use this video." }); return; }
    setBusy(true);
    try {
      const project = await createProject(name.trim() || file?.name?.replace(/\.[^/.]+$/, "") || "Imported video", rights);
      const uploaded = file ? await uploadVideo(project.id, file) : await importVideoUrl(project.id, url.trim());
      const readyProject = uploaded.project;
      await analyzeProject(readyProject.id);
      const processingProject = await getProject(readyProject.id);
      await onCreated(processingProject);
      setName(""); setUrl(""); setFile(null); setRights(false);
      setNotice({ type: "success", text: "Project created. Local analysis has started." });
    } catch (error) {
      setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not create the project." });
    } finally { setBusy(false); }
  };

  const onDrop = (event: React.DragEvent<HTMLDivElement>) => { event.preventDefault(); const dropped = event.dataTransfer.files?.[0]; if (dropped) setFile(dropped); };

  return <div className="page-content dashboard-page">
    <section className="hero-block"><div className="hero-kicker"><span className="pulse-dot" /> LOCAL-FIRST AI CLIP STUDIO</div><h1>Turn long videos into<br /><span>your best short clips.</span></h1><p>ClipForge finds the moments worth watching and turns them into ready-to-edit short videos — locally, transparently, and without paid APIs.</p></section>
    <section className="create-card panel-glow">
      <div className="section-heading"><div><span className="step-number">01</span><div><h2>Start a new project</h2><p>Upload a source you have the right to edit and publish.</p></div></div><span className="free-badge">FREE MODE</span></div>
      <div className="source-grid">
        <div className={`dropzone ${file ? "has-file" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={onDrop} onClick={() => inputRef.current?.click()}>
          <input ref={inputRef} type="file" hidden accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-msvideo,.mkv,.avi" onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <div className="drop-icon"><Icon name="upload" /></div><div><strong>{file ? file.name : "Drop your video here"}</strong><p>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · ready to upload` : "or click to browse from your computer"}</p></div>{file && <button className="clear-file" onClick={(event) => { event.stopPropagation(); setFile(null); }}><Icon name="close" /></button>}
          <div className="format-row"><span>MP4</span><span>MOV</span><span>MKV</span><span>WebM</span><span>Up to 30 min</span></div>
        </div>
        <div className="or-divider"><span>OR</span></div>
        <div className="url-source"><div className="input-label"><Icon name="link" /> Direct video URL</div><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/video.mp4" /><p className="input-hint">Only direct video files from sources that permit downloading. Platform pages are intentionally not imported.</p></div>
      </div>
      <div className="create-footer"><div className="project-name-field"><label>Project name <span>optional</span></label><input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Podcast Episode #12" /></div><label className="rights-check"><input type="checkbox" checked={rights} onChange={(event) => setRights(event.target.checked)} /><span className="fake-check"><Icon name="check" /></span><span>I own this video or have permission to edit and publish it.</span></label><button className="secondary-button platform-source-button" onClick={onPlatforms}><Icon name="link" /> Import from platform</button><button className="primary-button" onClick={start} disabled={busy}>{busy ? <><span className="spinner" /> Preparing…</> : <>Analyze video <Icon name="arrow" /></>}</button></div>
      <div className="rights-note"><span>ⓘ</span><p>Adding captions, music, effects, logos, cropping, or hooks does <strong>not</strong> remove copyright restrictions. You are responsible for your content rights.</p></div>
    </section>
    <div className="stats-row"><Stat label="Projects" value={stats.projects} icon="folder" /><Stat label="Clips created" value={stats.ready_clips} icon="play" /><Stat label="Videos processed" value={stats.videos_processed} icon="check" /><Stat label="Avg processing" value={stats.avg_processing_seconds ? `${stats.avg_processing_seconds}s` : "–"} icon="clock" /></div>
    <section className="queue-section"><div className="section-heading simple"><div><h2>Processing queue</h2><p>Live local jobs from the worker.</p></div><span className="queue-live"><span className="status-dot" /> {queue.projects.length + queue.render_jobs.length} active</span></div>{queue.projects.length || queue.render_jobs.length ? <div className="queue-dashboard-list">{queue.projects.map((item) => <button className="queue-dashboard-row" key={item.id} onClick={() => onOpen(item.id)}><div className="queue-row-icon"><Icon name="spark" /></div><div><strong>{item.name}</strong><span>{item.current_stage}</span></div><div className="queue-progress"><span>{item.progress}%</span><div className="progress-track"><span style={{ width: `${item.progress}%` }} /></div></div><Icon name="arrow" /></button>)}{queue.render_jobs.map((item) => <div className="queue-dashboard-row" key={item.id}><div className="queue-row-icon render"><Icon name="play" /></div><div><strong>Clip render</strong><span>{item.message || item.status}</span></div><div className="queue-progress"><span>{item.progress}%</span><div className="progress-track"><span style={{ width: `${item.progress}%` }} /></div></div><span className="queue-render-id">{item.id.slice(0, 6)}</span></div>)}</div> : <div className="queue-empty"><span className="status-dot" /><span>No active jobs. New analysis and renders will appear here.</span></div>}</section>
    <AdSlot page="dashboard" />
    <section className="recent-section"><div className="section-heading simple"><div><h2>Recent projects</h2><p>Your local video workspace.</p></div><span className="muted-count">{projects.length} total</span></div>{loading && !projects.length ? <div className="empty-panel"><span className="spinner dark" /> Loading projects…</div> : projects.length ? <div className="project-table"><div className="table-header"><span>PROJECT</span><span>STATUS</span><span>CLIPS</span><span>CREATED</span><span /></div>{projects.map((project) => <button className="project-row" key={project.id} onClick={() => onOpen(project.id)}><div className="project-cell"><div className="project-thumb"><Icon name={project.status === "finished" ? "play" : "clock"} /></div><div><strong>{project.name}</strong><span>{project.original_filename || "No video yet"}{project.duration ? ` · ${formatTime(project.duration)}` : ""}</span></div></div><div><StatusBadge status={project.status} /></div><div className="table-number">{project.ready_count || 0} <span>ready</span></div><div className="table-date">{formatDate(project.created_at)}</div><Icon name="arrow" /></button>)}</div> : <div className="empty-panel"><div className="empty-icon"><Icon name="spark" /></div><h3>Your best moments will live here.</h3><p>Upload a video above to create your first project.</p></div>}</section>
  </div>;
}

function Stat({ label, value, icon }: { label: string; value: number | string; icon: "folder" | "play" | "check" | "clock" }) { return <div className="stat-card"><div className="stat-icon"><Icon name={icon} /></div><div><span>{label}</span><strong>{value}</strong></div></div>; }

function StatusBadge({ status }: { status: string }) { const labels: Record<string, string> = { finished: "Ready", failed: "Failed", uploaded: "Ready to analyze", created: "Waiting", preparing: "Preparing", transcribing: "Transcribing", detecting_scenes: "Finding scenes", detecting_highlights: "Finding moments", scoring_moments: "Ranking", creating_clips: "Rendering", adding_captions: "Captions" }; return <span className={`status-badge ${isProcessing(status) ? "processing" : status === "finished" ? "ready" : status === "failed" ? "failed" : ""}`}><span />{labels[status] || status}</span>; }

function Workspace({ project, showAds, onBack, onRefresh, onRetry, onDelete, onSelectClip, onDeleteClip }: { project: Project; showAds: boolean; onBack: () => void; onRefresh: () => void; onRetry: () => Promise<void>; onDelete: () => Promise<void>; onSelectClip: (clip: Clip) => void; onDeleteClip: (id: string) => Promise<void> }) {
  const clips = project.clips || [];
  const [sort, setSort] = useState<"score" | "newest">("score");
  const sorted = useMemo(() => [...clips].sort((a, b) => sort === "score" ? b.score - a.score : b.rank - a.rank), [clips, sort]);
  const processing = isProcessing(project.status);
  return <div className="page-content workspace-page">
    <div className="workspace-head"><div><div className="eyebrow">PROJECT / {project.id.slice(0, 8).toUpperCase()}</div><h1>{project.name}</h1><p>{project.original_filename || "Source video"} {project.duration ? `· ${formatTime(project.duration)}` : ""} {project.width ? `· ${project.width}×${project.height}` : ""}</p></div><div className="workspace-actions"><a className="secondary-button" href={`/api/projects/${project.id}/download-all`}><Icon name="download" /> Download all</a><button className="danger-button" onClick={() => void onDelete()}><Icon name="trash" /> Delete</button><button className="icon-button bordered" onClick={onRefresh}><Icon name="refresh" /></button></div></div>
    {project.error && <div className="error-banner"><strong>Processing stopped</strong><span>{project.error}</span><button className="small-button" onClick={() => void onRetry()}><Icon name="refresh" /> Retry project</button></div>}
    {processing && <ProcessingPanel project={project} />}
    {project.status === "uploaded" && <div className="waiting-panel"><div className="empty-icon"><Icon name="spark" /></div><h3>Ready to find your best moments.</h3><p>Return to Projects and start analysis for this source video.</p><button onClick={onBack} className="secondary-button">Back to project list</button></div>}
    {project.status === "finished" && <><div className="result-summary"><div><span className="eyebrow">ANALYSIS COMPLETE</span><h2>Your best moments <span>{clips.length}</span></h2><p>Ranked using speech, audio intensity, scene changes, context, and pacing. Review before publishing.</p></div><div className="result-metrics"><div><strong>{clips.length}</strong><span>clips selected</span></div><div><strong>{clips[0]?.score || 0}</strong><span>top score</span></div><div><strong>9:16</strong><span>ready format</span></div></div></div><div className="results-toolbar"><div className="toolbar-title"><span>TOP MOMENTS</span><i>·</i><strong>{clips.length} candidates</strong></div><div className="sort-buttons"><span>Sort by</span><button className={sort === "score" ? "selected" : ""} onClick={() => setSort("score")}>Viral score</button><button className={sort === "newest" ? "selected" : ""} onClick={() => setSort("newest")}>Original order</button></div></div>{clips.length ? <div className="clip-grid">{sorted.map((clip) => <ClipCard key={clip.id} clip={clip} onEdit={() => onSelectClip(clip)} onDelete={() => void onDeleteClip(clip.id)} />)}</div> : <div className="empty-panel"><h3>No highlights were selected.</h3><p>There may not be enough speech or visual information to confidently rank moments.</p></div>}{showAds && <AdSlot page="results" />}</>}
  </div>;
}

function ProcessingPanel({ project }: { project: Project }) { const statusIndex = pipeline.findIndex((step) => step[0] === project.status); return <div className="processing-panel panel-glow"><div className="processing-top"><div><span className="eyebrow">LIVE LOCAL PIPELINE</span><h2>{project.current_stage || "Processing your video"}</h2><p>ClipForge is doing genuine work on your file. You can keep this tab open.</p></div><div className="big-progress"><strong>{project.progress}%</strong><div className="progress-track"><span style={{ width: `${project.progress}%` }} /></div></div></div><div className="pipeline-steps">{pipeline.map((step, index) => { const done = project.status === "finished" || index < statusIndex; const current = index === statusIndex; return <div className={`pipeline-step ${done ? "done" : ""} ${current ? "current" : ""}`} key={step[0]}><div className="pipeline-node">{done ? <Icon name="check" /> : current ? <span className="spinner" /> : <span>{String(index + 1).padStart(2, "0")}</span>}</div><div><strong>{step[1]}</strong><span>{step[2]}</span></div></div>; })}</div><div className="processing-foot"><span className="spinner dark" /> {project.current_stage || "Working"}<span className="processing-note">No paid API required</span><SystemMonitor /></div></div>; }

function SystemMonitor() { const [system, setSystem] = useState<SystemStatus | null>(null); useEffect(() => { let cancelled = false; const load = async () => { try { const next = await getSystemStatus(); if (!cancelled) setSystem(next); } catch { /* monitor is optional */ } }; void load(); const timer = window.setInterval(load, 1600); return () => { cancelled = true; window.clearInterval(timer); }; }, []); return <div className="system-monitor"><span className="system-local"><i /> {system?.running_locally ? "Running locally" : "Local status"}</span><span>CPU {system?.cpu_percent == null ? "–" : `${Math.round(system.cpu_percent)}%`}</span><span>RAM {system?.memory_percent == null ? "–" : `${Math.round(system.memory_percent)}%`}</span><span>GPU {system?.gpu?.available ? "available" : "not detected"}</span></div>; }

function ClipCard({ clip, onEdit, onDelete }: { clip: Clip; onEdit: () => void; onDelete: () => void }) { const color = categoryColors[clip.category] || "slate"; return <article className="clip-card"><div className="clip-preview">{clip.video_url ? <video src={clip.video_url} poster={clip.thumbnail_url || undefined} controls preload="metadata" /> : <div className="render-placeholder"><span className="spinner" /><small>{clip.status === "failed" ? "Render failed" : "Rendering"}</small></div>}<div className="rank-pill">#{String(clip.rank).padStart(2, "0")}</div><div className="score-pill"><Icon name="spark" /> {Math.round(clip.score)}</div></div><div className="clip-card-body"><div className="clip-meta"><span className={`category-chip ${color}`}>{clip.category}</span><span className="duration-chip"><Icon name="clock" /> {formatTime(clip.duration)}</span></div><h3>{clip.title}</h3><p className="clip-reason">{clip.reason}</p><div className="clip-footer"><span className="timestamp"><span>{formatTime(clip.start_sec)}</span> → <span>{formatTime(clip.end_sec)}</span></span><div className="clip-card-actions"><button onClick={onDelete} title="Delete"><Icon name="trash" /></button><button className="edit-button" onClick={onEdit}><Icon name="edit" /> Edit</button></div></div></div></article>; }

function EditorPanel({ project, clip, onClose, onSaved, setNotice }: { project: Project; clip: Clip; onClose: () => void; onSaved: () => Promise<void>; setNotice: (notice: { type: "error" | "success" | "info"; text: string }) => void }) {
  const [draft, setDraft] = useState<Clip>(clip);
  const [library, setLibrary] = useState<{ music: LibraryAsset[]; sfx: LibraryAsset[] }>({ music: [], sfx: [] });
  const [templates, setTemplates] = useState<ClipTemplate[]>([]);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [renderMessage, setRenderMessage] = useState("");
  const [showPublish, setShowPublish] = useState(false);
  const [contentPack, setContentPack] = useState<ContentPack | null>(clip.content_pack || null);
  const [packBusy, setPackBusy] = useState(false);
  const [packVariant, setPackVariant] = useState(0);
  const [thumbnailBusy, setThumbnailBusy] = useState(false);
  const [thumbnailText, setThumbnailText] = useState("");
  const [thumbnailTime, setThumbnailTime] = useState(0.5);
  const [thumbnailPosition, setThumbnailPosition] = useState("bottom");
  const logoRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setDraft(clip); setContentPack(clip.content_pack || null); void getLibrary().then(setLibrary).catch(() => undefined); void getTemplates().then((result) => setTemplates(result.templates)).catch(() => undefined); void getContentPack(clip.id).then((result) => setContentPack(result.content_pack)).catch(() => undefined); }, [clip.id]);
  const patch = (values: Partial<Clip>) => setDraft((current) => ({ ...current, ...values }));
  const save = async () => { setSaving(true); try { await updateClip(draft.id, { start_sec: draft.start_sec, end_sec: draft.end_sec, captions_enabled: draft.captions_enabled, caption_style: draft.caption_style, caption_font_size: draft.caption_font_size, caption_position: draft.caption_position, hook_enabled: draft.hook_enabled, hook: draft.hook, hook_position: draft.hook_position, format: draft.format, logo_position: draft.logo_position, logo_opacity: draft.logo_opacity, intro_text: draft.intro_text, outro_text: draft.outro_text, intro_duration: draft.intro_duration, outro_duration: draft.outro_duration, music_path: draft.music_path, music_volume: draft.music_volume, sfx_path: draft.sfx_path, sfx_volume: draft.sfx_volume, speed: draft.speed, effects: draft.effects } as Partial<Clip>); setNotice({ type: "success", text: "Clip settings saved." }); await onSaved(); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not save clip." }); } finally { setSaving(false); } };
  const render = async () => { setRendering(true); setRenderMessage("Starting FFmpeg render…"); try { await save(); const result = await renderClip(draft.id); let finished = false; while (!finished) { await new Promise((resolve) => window.setTimeout(resolve, 900)); const job = await getRenderJob(result.job.id); setRenderMessage(`${job.message || "Rendering"} · ${job.progress}%`); finished = job.status === "finished" || job.status === "failed"; if (job.status === "failed") throw new Error(job.message || "Render failed"); } setNotice({ type: "success", text: "Your edited clip is ready to preview." }); await onSaved(); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not render clip." }); } finally { setRendering(false); setRenderMessage(""); } };
  const addLogo = async (file?: File) => { if (!file) return; try { await uploadLogo(project.id, file); patch({ logo_path: "uploaded" }); setNotice({ type: "success", text: "Logo uploaded for this project." }); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not upload logo." }); } };
  const regeneratePack = async () => { setPackBusy(true); try { const result = await regenerateContentPack(draft.id, "en", "casual", packVariant + 1); setPackVariant((value) => value + 1); setContentPack(result.content_pack); setNotice({ type: "success", text: "Local content pack regenerated." }); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not regenerate content pack." }); } finally { setPackBusy(false); } };
  const generateThumb = async () => { setThumbnailBusy(true); try { const result = await generateThumbnail(draft.id, thumbnailTime, thumbnailText, thumbnailPosition); setDraft(result.clip); setNotice({ type: "success", text: "Thumbnail generated from the real video frame." }); await onSaved(); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not generate thumbnail." }); } finally { setThumbnailBusy(false); } };
  const applyClipTemplate = async (templateId: string) => { try { const result = await applyTemplate(draft.id, templateId); setDraft(result.clip); setNotice({ type: "success", text: `${result.template.name} applied.` }); await onSaved(); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not apply template." }); } };
  return <div className="editor-overlay"><div className="editor-panel"><div className="editor-header"><div><span className="eyebrow">CLIP EDITOR / #{String(clip.rank).padStart(2, "0")}</span><h2>{draft.title}</h2></div><button className="icon-button" onClick={onClose}><Icon name="close" /></button></div><div className="editor-body"><div className="editor-preview-column"><div className="editor-video"><div className="vertical-guide" />{draft.video_url ? <video src={draft.video_url} controls autoPlay muted loop /> : <div className="render-placeholder"><Icon name="play" /><span>Render this clip to preview</span></div>}<div className="editor-score"><Icon name="spark" /> {Math.round(draft.score)} / 100</div></div><div className="editor-caption"><span className={`category-chip ${categoryColors[draft.category] || "slate"}`}>{draft.category}</span><p>{draft.reason}</p></div><div className="rights-note compact"><span>ⓘ</span><p>Exporting edits does not grant rights to the source content.</p></div></div><div className="editor-controls"><ContentPackPanel pack={contentPack} locked={draft.content_pack_locked} busy={packBusy} onRegenerate={() => void regeneratePack()} /><TemplatePanel templates={templates} onApply={(id) => void applyClipTemplate(id)} /><ThumbnailPanel thumbnailUrl={draft.thumbnail_url} text={thumbnailText} setText={setThumbnailText} time={thumbnailTime} setTime={setThumbnailTime} position={thumbnailPosition} setPosition={setThumbnailPosition} busy={thumbnailBusy} onGenerate={() => void generateThumb()} /><ControlGroup title="Clip" icon="clock"><div className="two-fields"><Field label="Start"><input type="number" step="0.1" value={draft.start_sec} onChange={(event) => patch({ start_sec: Number(event.target.value) })} /></Field><Field label="End"><input type="number" step="0.1" value={draft.end_sec} onChange={(event) => patch({ end_sec: Number(event.target.value) })} /></Field></div><div className="range-line"><span>{formatTime(draft.start_sec)}</span><div className="range-track"><i style={{ left: `${Math.min(96, (draft.start_sec / Math.max(project.duration || 1, 1)) * 100)}%`, width: `${Math.max(4, ((draft.end_sec - draft.start_sec) / Math.max(project.duration || 1, 1)) * 100)}%` }} /></div><span>{formatTime(draft.end_sec)}</span></div></ControlGroup><ControlGroup title="Format" icon="grid"><div className="segmented">{["9:16", "1:1", "16:9", "4:5"].map((format) => <button key={format} className={draft.format === format ? "selected" : ""} onClick={() => patch({ format })}>{format}</button>)}</div></ControlGroup><ControlGroup title="Captions" icon="spark"><div className="toggle-row"><div><strong>Auto captions</strong><span>Local Whisper transcript</span></div><Toggle value={draft.captions_enabled} onChange={(value) => patch({ captions_enabled: value })} /></div><div className="control-grid"><Field label="Style"><select value={draft.caption_style} onChange={(event) => patch({ caption_style: event.target.value })}>{["clean", "bold", "creator", "podcast", "minimal", "high-energy"].map((value) => { const premiumStyle = ["creator", "podcast", "minimal", "high-energy"].includes(value); return <option key={value} disabled={Boolean(draft.content_pack_locked && premiumStyle)}>{premiumStyle ? `${value} · Pro` : value}</option>; })}</select></Field><Field label="Position"><select value={draft.caption_position} onChange={(event) => patch({ caption_position: event.target.value })}><option value="bottom">Bottom</option><option value="middle">Middle</option><option value="top">Top</option></select></Field></div></ControlGroup><ControlGroup title="Hook" icon="arrow"><div className="toggle-row"><div><strong>Content-based hook</strong><span>Generated from the actual moment</span></div><Toggle value={draft.hook_enabled} onChange={(value) => patch({ hook_enabled: value })} /></div><textarea value={draft.hook} onChange={(event) => patch({ hook: event.target.value })} placeholder="Write a truthful hook…" rows={2} /></ControlGroup><ControlGroup title="Copy ideas" icon="spark"><Field label="Local title suggestions"><select value={draft.title} onChange={(event) => patch({ title: event.target.value })}>{(draft.title_suggestions?.length ? draft.title_suggestions : [draft.title]).map((suggestion) => <option value={suggestion} key={suggestion}>{suggestion}</option>)}</select></Field><p className="micro-note">Generated from the clip's actual transcript or visual selection. Suggestions do not guarantee engagement.</p><div className="suggested-tags">{(draft.hashtags || []).map((tag) => <span key={tag}>{tag}</span>)}</div></ControlGroup><ControlGroup title="Branding" icon="spark"><div className="upload-line"><div><strong>{draft.logo_path ? "Logo attached" : "Add your logo"}</strong><span>PNG, JPG, WebP · project setting</span></div><input ref={logoRef} type="file" hidden accept="image/png,image/jpeg,image/webp" onChange={(event) => void addLogo(event.target.files?.[0])} /><button className="small-button" onClick={() => logoRef.current?.click()}>{draft.logo_path ? "Replace" : "Upload"}</button></div><div className="control-grid"><Field label="Position"><select value={draft.logo_position} onChange={(event) => patch({ logo_position: event.target.value })}><option>top-left</option><option>top-right</option><option>bottom-left</option><option>bottom-right</option></select></Field><Field label="Opacity"><input type="number" min="0.05" max="1" step="0.05" value={draft.logo_opacity} onChange={(event) => patch({ logo_opacity: Number(event.target.value) })} /></Field></div><div className="control-grid"><Field label="Intro card text"><input value={draft.intro_text} onChange={(event) => patch({ intro_text: event.target.value })} placeholder="Optional intro" /></Field><Field label="Outro card text"><input value={draft.outro_text} onChange={(event) => patch({ outro_text: event.target.value })} placeholder="Optional outro" /></Field></div></ControlGroup><ControlGroup title="Audio" icon="play"><Field label="Licensed music / local asset"><select value={draft.music_path || ""} onChange={(event) => patch({ music_path: event.target.value || null })}><option value="">Original audio only</option>{library.music.map((asset) => <option value={asset.path} key={asset.id}>{asset.name} · {asset.license}</option>)}</select></Field><div className="volume-row"><span>Music volume</span><input type="range" min="0" max="1" step="0.01" value={draft.music_volume} onChange={(event) => patch({ music_volume: Number(event.target.value) })} /><strong>{Math.round(draft.music_volume * 100)}%</strong></div><Field label="User-provided sound effect"><select value={draft.sfx_path || ""} onChange={(event) => patch({ sfx_path: event.target.value || null })}><option value="">No sound effect</option>{library.sfx.map((asset) => <option value={asset.path} key={asset.id}>{asset.name} · {asset.license}</option>)}</select></Field><div className="volume-row"><span>Effect volume</span><input type="range" min="0" max="1" step="0.01" value={draft.sfx_volume} onChange={(event) => patch({ sfx_volume: Number(event.target.value) })} /><strong>{Math.round(draft.sfx_volume * 100)}%</strong></div><p className="micro-note">Only use music or effects you own, uploaded yourself, or have properly licensed.</p></ControlGroup><ControlGroup title="Effects" icon="spark"><div className="toggle-row"><div><strong>Conservative punch</strong><span>Keep the default professional</span></div><Toggle value={Boolean(draft.effects?.shake)} onChange={(value) => patch({ effects: { ...draft.effects, shake: value } })} /></div><div className="toggle-row"><div><strong>Punch zoom</strong><span>Subtle 6% emphasis crop</span></div><Toggle value={Boolean(draft.effects?.punch_zoom)} onChange={(value) => patch({ effects: { ...draft.effects, punch_zoom: value } })} /></div><div className="toggle-row"><div><strong>Fade in / out</strong><span>Short, conservative transitions</span></div><Toggle value={Boolean(draft.effects?.fade)} onChange={(value) => patch({ effects: { ...draft.effects, fade: value } })} /></div><Field label="Playback speed"><select value={draft.speed} onChange={(event) => patch({ speed: Number(event.target.value) })}><option value="1">1× Normal</option><option value="1.1">1.1× Faster</option><option value="1.25">1.25× Faster</option><option value="0.9">0.9× Slower</option></select></Field></ControlGroup></div></div><div className="editor-footer"><span>{rendering ? <><span className="spinner dark" /> {renderMessage}</> : "Changes are local until you render."}</span><div><button className="secondary-button" onClick={save} disabled={saving || rendering}>{saving ? "Saving…" : "Save settings"}</button><button className="primary-button" onClick={render} disabled={rendering}>{rendering ? <><span className="spinner" /> Rendering…</> : <><Icon name="play" /> Generate clip</>}</button>{draft.video_url && <><button className="publish-button" onClick={() => setShowPublish(true)}><Icon name="arrow" /> Publish</button><a className="download-button" href={`/api/clips/${draft.id}/download`}><Icon name="download" /></a></>}</div></div></div>{showPublish && <PublishDialog clip={draft} onClose={() => setShowPublish(false)} setNotice={setNotice} />}</div>;
}

function TemplatePanel({ templates, onApply }: { templates: ClipTemplate[]; onApply: (id: string) => void }) { const [selected, setSelected] = useState(templates[0]?.id || ""); return <section className="template-panel"><div><span className="eyebrow">TEMPLATES</span><h3>Start with a proven local preset</h3><p>Templates change real editor settings; no remote service is required.</p></div><div className="template-row"><select value={selected} onChange={(event) => setSelected(event.target.value)}>{templates.map((template) => <option value={template.id} key={template.id}>{template.name}{template.premium ? " · Pro" : ""}</option>)}</select><button className="small-button" disabled={!selected} onClick={() => onApply(selected)}>Apply</button></div>{templates.find((template) => template.id === selected) && <span className="template-description">{templates.find((template) => template.id === selected)?.description}</span>}</section> }

function ThumbnailPanel({ thumbnailUrl, text, setText, time, setTime, position, setPosition, busy, onGenerate }: { thumbnailUrl?: string | null; text: string; setText: (value: string) => void; time: number; setTime: (value: number) => void; position: string; setPosition: (value: string) => void; busy: boolean; onGenerate: () => void }) { return <section className="thumbnail-panel"><div className="thumbnail-panel-head"><div><span className="eyebrow">THUMBNAIL</span><h3>Frame from the actual video</h3><p>No synthetic image — optional text overlay only.</p></div>{thumbnailUrl && <img src={thumbnailUrl} alt="Generated thumbnail" />}</div><div className="thumbnail-panel-controls"><Field label="Frame offset (seconds)"><input type="number" min="0" max="60" step="0.1" value={time} onChange={(event) => setTime(Number(event.target.value))} /></Field><Field label="Text overlay"><input value={text} onChange={(event) => setText(event.target.value)} maxLength={120} placeholder="Optional, truthful text" /></Field><Field label="Text position"><select value={position} onChange={(event) => setPosition(event.target.value)}><option value="top">Top</option><option value="middle">Middle</option><option value="bottom">Bottom</option></select></Field><button className="small-button" disabled={busy} onClick={onGenerate}>{busy ? "Generating…" : "Generate thumbnail"}</button></div></section>}

function ContentPackPanel({ pack, locked, busy, onRegenerate }: { pack: ContentPack | null; locked?: boolean; busy: boolean; onRegenerate: () => void }) {
  const [platform, setPlatform] = useState("youtube_shorts");
  const copy = (value: string) => { void navigator.clipboard?.writeText(value); };
  if (locked) return <section className="content-pack-panel empty locked-pack"><div><span className="control-icon"><Icon name="spark" /></span><div><strong>Pro content pack</strong><span>Full descriptions, hashtags, keywords, SEO, and platform versions unlock with Pro at ₹99/month.</span></div></div><span className="premium-lock">PREMIUM</span></section>;
  if (!pack) return <section className="content-pack-panel empty"><div><span className="control-icon"><Icon name="spark" /></span><div><strong>Content pack</strong><span>Local hooks, titles, descriptions, keywords, and SEO.</span></div></div><button className="small-button" onClick={onRegenerate} disabled={busy}>{busy ? "Generating…" : "Generate pack"}</button></section>;
  const platformData = pack.platforms?.[platform] || {};
  return <section className="content-pack-panel"><div className="content-pack-head"><div><span className="eyebrow">LOCAL CONTENT PACK</span><h3>Ready to publish</h3><p>{pack.notice}</p></div><button className="small-button" onClick={onRegenerate} disabled={busy}>{busy ? "Regenerating…" : "Regenerate"}</button></div><PackField label="Hook" value={pack.hook} onCopy={copy} /><PackField label="Title" value={pack.title} onCopy={copy} /><PackField label="Description" value={pack.description.medium} onCopy={copy} /><div className="pack-row"><div><span className="pack-label">Hashtags</span><div className="suggested-tags">{pack.hashtags.all.map((tag) => <span key={tag}>{tag}</span>)}</div></div><button className="copy-button" onClick={() => copy(pack.hashtags.all.join(" "))}>Copy</button></div><div className="pack-keywords"><span className="pack-label">Primary keyword</span><strong>{pack.keywords.primary}</strong><span className="pack-label">Related</span><span>{pack.keywords.secondary.join(" · ")}</span></div><div className="pack-seo"><div><span>SEO SCORE</span><strong>{pack.seo.score}/100</strong></div><div><span>Title</span><b>{pack.seo.title}</b></div><div><span>Description</span><b>{pack.seo.description}</b></div><div><span>Keywords</span><b>{pack.seo.keywords}</b></div><div><span>Hashtags</span><b>{pack.seo.hashtags}</b></div></div><div className="pack-platform"><div className="pack-platform-head"><span className="pack-label">Platform version</span><select value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="youtube_shorts">YouTube Shorts</option><option value="instagram_reels">Instagram Reels</option><option value="tiktok">TikTok</option><option value="facebook">Facebook</option></select></div><div className="platform-copy-box">{Object.entries(platformData).map(([key, value]) => <div key={key}><span>{key.split("_").join(" ")}</span><p>{Array.isArray(value) ? value.join(" ") : value}</p><button className="copy-button" onClick={() => copy(Array.isArray(value) ? value.join(" ") : value)}>Copy</button></div>)}</div></div></section>;
}

function PackField({ label, value, onCopy }: { label: string; value: string; onCopy: (value: string) => void }) { return <div className="pack-row"><div><span className="pack-label">{label}</span><p>{value}</p></div><button className="copy-button" onClick={() => onCopy(value)}>Copy</button></div>; }

function PublishDialog({ clip, onClose, setNotice }: { clip: Clip; onClose: () => void; setNotice: (notice: { type: "error" | "success" | "info"; text: string }) => void }) {
  const [providers, setProviders] = useState<SocialProvider[]>([]);
  const [connections, setConnections] = useState<SocialConnection[]>([]);
  const [platform, setPlatform] = useState("");
  const [accountId, setAccountId] = useState("");
  const [caption, setCaption] = useState(clip.description || "");
  const [title, setTitle] = useState(clip.title || "ClipForge clip");
  const [hashtags, setHashtags] = useState((clip.hashtags || []).join(" "));
  const [visibility, setVisibility] = useState("private");
  const [rights, setRights] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { void Promise.all([getSocialProviders(), getSocialConnections()]).then(([providerData, connectionData]) => { const available = providerData.providers.filter((item) => item.connected && item.capabilities.publish); setProviders(available); setConnections(connectionData.connections); if (available[0]) { setPlatform(available[0].id); const account = connectionData.connections.find((item) => item.provider_id === available[0].id && item.status === "connected"); if (account) setAccountId(account.account_id); } }).catch((error) => setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not load publishing capabilities." })); }, []);
  const accounts = connections.filter((item) => item.provider_id === platform && item.status === "connected");
  const submit = async () => { if (!rights) { setNotice({ type: "error", text: "Confirm that you own or have authorization to publish this content." }); return; } if (!platform || !accountId) { setNotice({ type: "error", text: "Choose an officially connected platform account." }); return; } setBusy(true); try { const queued = await queuePublish({ clip_id: clip.id, platform, account_id: accountId, caption, title, hashtags: hashtags.split(/[ ,]+/).map((tag) => tag.replace(/^#/, "")).filter(Boolean), visibility, rights_acknowledged: rights }); const result = await publishQueued(queued.item.id); if (result.item.status === "Failed") setNotice({ type: "error", text: result.item.error || "The platform rejected the publish request." }); else setNotice({ type: "success", text: "The clip was sent through the official publishing API." }); onClose(); } catch (error) { setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not publish the clip." }); } finally { setBusy(false); } };
  return <div className="publish-dialog-backdrop"><div className="publish-dialog"><div className="publish-dialog-head"><div><span className="eyebrow">EXPLICIT USER ACTION</span><h2>Publish this clip</h2><p>Nothing will be posted until you press Publish now.</p></div><button className="icon-button" onClick={onClose}><Icon name="close" /></button></div>{providers.length ? <><div className="publish-flow"><span className="flow-node done">✓</span><span>Generated clip</span><i>→</i><span className="flow-node active">2</span><span>Platform</span><i>→</i><span className="flow-node">3</span><span>Publish</span></div><div className="publish-fields"><Field label="Platform"><select value={platform} onChange={(event) => { setPlatform(event.target.value); const account = connections.find((item) => item.provider_id === event.target.value && item.status === "connected"); setAccountId(account?.account_id || ""); }}>{providers.map((item) => <option value={item.id} key={item.id}>{item.name} · official publish available</option>)}</select></Field><Field label="Account"><select value={accountId} onChange={(event) => setAccountId(event.target.value)}>{accounts.map((account) => <option value={account.account_id} key={account.id}>{account.account_name}</option>)}</select></Field><Field label="Title"><input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={150} /></Field><Field label="Visibility"><select value={visibility} onChange={(event) => setVisibility(event.target.value)}><option value="private">Private / review</option><option value="unlisted">Unlisted</option><option value="public">Public</option></select></Field><div className="thumbnail-setting"><span>Thumbnail</span><div>{clip.thumbnail_url && <img src={clip.thumbnail_url} alt="" />}<small>{providers.find((item) => item.id === platform)?.capabilities.thumbnail ? "Generated thumbnail will be sent where supported" : "Platform default thumbnail"}</small></div></div><label className="field full-field"><span>Caption</span><textarea value={caption} onChange={(event) => setCaption(event.target.value)} rows={4} maxLength={2200} /></label><label className="field full-field"><span>Hashtags</span><input value={hashtags} onChange={(event) => setHashtags(event.target.value)} placeholder="#podcast #shorts #clip" /></label></div><label className="rights-check publish-rights"><input type="checkbox" checked={rights} onChange={(event) => setRights(event.target.checked)} /><span className="fake-check"><Icon name="check" /></span><span>I confirm I have the necessary rights or authorization to publish this clip.</span></label><div className="publish-dialog-foot"><span className="micro-note">Thumbnails and scheduling are only available when the connected platform provider reports support.</span><button className="primary-button" onClick={() => void submit()} disabled={busy}>{busy ? <><span className="spinner" /> Publishing…</> : <><Icon name="arrow" /> Publish now</>}</button></div></> : <div className="publish-unavailable"><div className="empty-icon"><Icon name="link" /></div><h3>No official publishing account is connected.</h3><p>Connect a platform from the Platforms screen first. Instagram, YouTube, TikTok, and Facebook may expose different publishing permissions.</p><button className="secondary-button" onClick={onClose}>Close and connect platform</button></div>}</div></div>;
}

function ControlGroup({ title, icon, children }: { title: string; icon: "clock" | "grid" | "spark" | "arrow" | "play"; children: React.ReactNode }) { return <section className="control-group"><div className="control-heading"><span className="control-icon"><Icon name={icon} /></span><strong>{title}</strong></div>{children}</section>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="field"><span>{label}</span>{children}</label>; }
function Toggle({ value, onChange }: { value: boolean; onChange: (value: boolean) => void }) { return <button className={`toggle ${value ? "on" : ""}`} onClick={() => onChange(!value)} aria-label="Toggle"><span /></button>; }

function TemplatesView({ setNotice }: { setNotice: (notice: { type: "error" | "success" | "info"; text: string }) => void }) { const [templates, setTemplates] = useState<ClipTemplate[]>([]); useEffect(() => { void getTemplates().then((result) => setTemplates(result.templates)).catch((error) => setNotice({ type: "error", text: error instanceof Error ? error.message : "Could not load templates." })); }, []); return <div className="page-content generic-page"><div className="generic-head"><div><span className="eyebrow">LOCAL PRESETS</span><h1>Templates for your format</h1><p>Apply real caption, crop, speed, fade, and emphasis settings from the clip editor.</p></div><span className="free-badge">OPEN-SOURCE / FREE</span></div><div className="template-library-grid">{templates.map((template) => <article className={`template-library-card ${template.premium ? "pro-template" : ""}`} key={template.id}><div className="template-library-art"><span>{template.premium ? "PRO" : "CF"}</span><i>✦</i></div><div className="template-library-body"><div><span className="template-library-label">{template.premium ? "PRO TEMPLATE" : "FREE TEMPLATE"}</span><h3>{template.name}</h3></div><p>{template.description}</p><button className="secondary-button" onClick={() => setNotice({ type: "info", text: "Open a clip and apply this template from the editor." })}>Use in editor <Icon name="arrow" /></button></div></article>)}</div><div className="rights-note"><span>ⓘ</span><p>Templates are local settings presets. They do not add commercial music or make copyrighted source content legal to reuse.</p></div></div>; }

function ContentPacksView() {
  const [items, setItems] = useState<{ project: Project; clip: Clip }[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { let cancelled = false; const load = async () => { try { const projects = await getProjects(); const details = await Promise.all(projects.map((project) => getProject(project.id))); if (!cancelled) setItems(details.flatMap((project) => (project.clips || []).filter((clip) => clip.content_pack).map((clip) => ({ project, clip })))); } finally { if (!cancelled) setLoading(false); } }; void load(); return () => { cancelled = true; }; }, []);
  return <div className="page-content generic-page"><div className="generic-head"><div><span className="eyebrow">CONTENT PACKS</span><h1>Ready-to-publish metadata</h1><p>Hooks, titles, descriptions, hashtags, keywords, SEO, and platform versions generated locally.</p></div><span className="free-badge">LOCAL / FREE</span></div>{loading ? <div className="empty-panel"><span className="spinner dark" /> Loading content packs…</div> : items.length ? <div className="pack-library-grid">{items.map(({ project, clip }) => { const pack = clip.content_pack!; return <article className="pack-library-card" key={clip.id}><div className="pack-library-top"><span className={`category-chip ${categoryColors[clip.category] || "slate"}`}>{clip.category}</span><span>SEO {pack.seo.score}/100</span></div><h3>{pack.title}</h3><p>{pack.description.short}</p><div className="suggested-tags">{pack.hashtags.all.slice(0, 5).map((tag) => <span key={tag}>{tag}</span>)}</div><div className="pack-library-footer"><span>{project.name}</span><span>Score {Math.round(clip.score)}</span></div></article>; })}</div> : <div className="empty-panel"><div className="empty-icon"><Icon name="spark" /></div><h3>No content packs yet.</h3><p>Analyze a video to generate platform-ready metadata for its clips.</p></div>}{<AdSlot page="content-packs" />}<div className="rights-note"><span>ⓘ</span><p>Local content suggestions are based on available source context. Review every title, description, hashtag, and platform version before publishing.</p></div></div>;
}

function AssetsView() {
  const [library, setLibrary] = useState<{ music: LibraryAsset[]; sfx: LibraryAsset[] }>({ music: [], sfx: [] });
  const [license, setLicense] = useState("User-provided or properly licensed");
  const [busy, setBusy] = useState(false);
  const load = async () => { try { setLibrary(await getLibrary()); } catch { /* dashboard remains usable if library is empty */ } };
  useEffect(() => { void load(); }, []);
  const upload = async (kind: "music" | "sfx", file?: File) => { if (!file) return; setBusy(true); try { await uploadLibraryAsset(kind, file, license, ""); await load(); } catch (error) { window.alert(error instanceof Error ? error.message : "Could not upload asset."); } finally { setBusy(false); } };
  const remove = async (kind: "music" | "sfx", id: string) => { if (!window.confirm("Remove this local asset?")) return; try { await deleteLibraryAsset(kind, id); await load(); } catch (error) { window.alert(error instanceof Error ? error.message : "Could not remove asset."); } };
  return <div className="page-content generic-page"><div className="generic-head"><div><span className="eyebrow">ASSET LIBRARY</span><h1>Your local assets</h1><p>Upload user-provided or properly licensed music and sound effects for the clip editor.</p></div><span className="free-badge">NO CLOUD STORAGE</span></div><div className="asset-upload-settings"><label className="field"><span>License / source note</span><input value={license} onChange={(event) => setLicense(event.target.value)} placeholder="e.g. CC0 · source URL · my own recording" /></label><p>ClipForge stores this note beside the file. It does not verify licenses for you.</p></div><div className="asset-info-grid"><AssetLibraryCard kind="music" title="Music" symbol="♪" assets={library.music} busy={busy} onUpload={upload} onDelete={remove} /><AssetLibraryCard kind="sfx" title="Sound effects" symbol="✦" assets={library.sfx} busy={busy} onUpload={upload} onDelete={remove} /><div className="asset-info-card"><span className="asset-symbol">◈</span><h3>Logos</h3><p>Upload logos per project from the clip editor. Nothing is published automatically.</p><span className="asset-path">Project editor · PNG / JPG / WebP</span></div></div><div className="rights-note"><span>ⓘ</span><p>Adding music, sound effects, captions, logos, or other edits does not remove copyright restrictions. Use only content you have permission to use.</p></div></div>;
}

function AssetLibraryCard({ kind, title, symbol, assets, busy, onUpload, onDelete }: { kind: "music" | "sfx"; title: string; symbol: string; assets: LibraryAsset[]; busy: boolean; onUpload: (kind: "music" | "sfx", file?: File) => Promise<void>; onDelete: (kind: "music" | "sfx", id: string) => Promise<void> }) { const inputRef = useRef<HTMLInputElement>(null); return <div className="asset-info-card asset-library-card"><div className="asset-card-title"><span className="asset-symbol">{symbol}</span><button className="small-button" disabled={busy} onClick={() => inputRef.current?.click()}><Icon name="upload" /> Upload</button><input ref={inputRef} hidden type="file" accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/ogg,.mp3,.wav,.m4a,.ogg" onChange={(event) => void onUpload(kind, event.target.files?.[0])} /></div><h3>{title}</h3><p>Only use assets you own or have properly licensed.</p>{assets.length ? <div className="asset-file-list">{assets.map((asset) => <div className="asset-file-row" key={asset.id}><div><strong>{asset.name}</strong><span>{asset.license}</span></div><button onClick={() => void onDelete(kind, asset.id)}><Icon name="trash" /></button></div>)}</div> : <span className="asset-path">No local assets yet</span>}</div> }

function SettingsView() { return <div className="page-content generic-page"><div className="generic-head"><div><span className="eyebrow">SETTINGS</span><h1>Local processing controls</h1><p>Free-mode limits are designed to be adjustable through environment variables.</p></div></div><div className="settings-list"><div><strong>Maximum video duration</strong><span>1800 seconds · change with MAX_VIDEO_DURATION</span></div><div><strong>Maximum file size</strong><span>1000 MB · change with MAX_FILE_SIZE_MB</span></div><div><strong>Maximum clips</strong><span>10 per analysis · change with MAX_CLIPS</span></div><div><strong>Transcription</strong><span>faster-whisper tiny.en · local CPU mode</span></div><div><strong>Storage</strong><span>SQLite + backend/storage · no cloud database</span></div></div><div className="rights-note"><span>ⓘ</span><p>ClipForge never claims that an edit makes copyrighted content legal. You remain responsible for rights and publishing permissions.</p></div></div>; }

function App() {
  const path = window.location.pathname;
  const [showLanding, setShowLanding] = useState(() => path === "/" || path === "");
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [authLoading, setAuthLoading] = useState(!showLanding);
  const enterWorkspace = () => { window.history.pushState({}, "", "/app"); setShowLanding(false); setAuthLoading(true); void getAuth().then(setAuth).catch(() => setAuth({ authenticated: false, user: null })).finally(() => setAuthLoading(false)); window.scrollTo({ top: 0 }); };
  const goLanding = () => { window.history.pushState({}, "", "/"); setShowLanding(true); window.scrollTo({ top: 0 }); };
  useEffect(() => { if (!showLanding) void getAuth().then(setAuth).catch(() => setAuth({ authenticated: false, user: null })).finally(() => setAuthLoading(false)); }, [showLanding]);
  useEffect(() => { const onPop = () => { const nextLanding = window.location.pathname === "/" || window.location.pathname === ""; setShowLanding(nextLanding); if (!nextLanding) setAuthLoading(true); }; window.addEventListener("popstate", onPop); return () => window.removeEventListener("popstate", onPop); }, []);
  const onAuthenticated = (state: AuthState) => { setAuth(state); setShowLanding(false); if (window.location.pathname !== "/app") window.history.pushState({}, "", "/app"); };
  if (showLanding) return <LandingPage onEnter={enterWorkspace} />;
  const query = new URLSearchParams(window.location.search);
  if (path === "/verify-email" && query.get("token")) return <AuthTokenScreen kind="verify" token={query.get("token")!} onAuthenticated={onAuthenticated} onBack={() => { window.history.pushState({}, "", "/app"); setAuth({ authenticated: false, user: null }); }} />;
  if (path === "/magic-login" && query.get("token")) return <AuthTokenScreen kind="magic" token={query.get("token")!} onAuthenticated={onAuthenticated} onBack={goLanding} />;
  if (path === "/reset-password" && query.get("token")) return <AuthTokenScreen kind="reset" token={query.get("token")!} onAuthenticated={onAuthenticated} onBack={goLanding} />;
  if (authLoading || !auth) return <div className="auth-loading"><span className="spinner dark" /> Loading secure workspace…</div>;
  if (!auth.authenticated) return <AuthScreen onAuthenticated={onAuthenticated} onBack={goLanding} />;
  return <WorkspaceApp auth={auth} onLogout={() => { void logout().finally(() => { sessionStorage.removeItem("clipforge_csrf"); setAuth({ authenticated: false, user: null }); }); }} />;
}

export default App;
