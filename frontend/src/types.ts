export type ProjectStatus =
  | "created"
  | "uploaded"
  | "preparing"
  | "transcribing"
  | "detecting_scenes"
  | "detecting_highlights"
  | "scoring_moments"
  | "creating_clips"
  | "adding_captions"
  | "generating_content"
  | "seo_analysis"
  | "finished"
  | "failed";

export interface Clip {
  id: string;
  project_id: string;
  rank: number;
  category: string;
  score: number;
  reason: string;
  start_sec: number;
  end_sec: number;
  duration: number;
  transcript: { start: number; end: number; text: string; words?: unknown[] }[];
  hook: string;
  title: string;
  title_suggestions: string[];
  description: string;
  hashtags: string[];
  captions_enabled: boolean;
  caption_style: string;
  caption_font_size: number;
  caption_position: string;
  hook_enabled: boolean;
  hook_position: string;
  hook_duration: number;
  format: string;
  logo_path?: string | null;
  logo_position: string;
  logo_opacity: number;
  intro_text: string;
  outro_text: string;
  intro_duration: number;
  outro_duration: number;
  music_path?: string | null;
  music_volume: number;
  sfx_path?: string | null;
  sfx_volume: number;
  speed: number;
  effects: Record<string, unknown>;
  status: "queued" | "rendering" | "ready" | "failed";
  error?: string | null;
  video_url?: string | null;
  thumbnail_url?: string | null;
  content_pack?: ContentPack | null;
  content_pack_locked?: boolean;
}

export interface Project {
  id: string;
  name: string;
  status: ProjectStatus;
  progress: number;
  current_stage: string;
  original_path?: string | null;
  original_url?: string | null;
  original_filename?: string | null;
  source_type: string;
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  audio_channels?: number | null;
  rights_acknowledged: boolean;
  error?: string | null;
  created_at: string;
  updated_at: string;
  clip_count?: number;
  ready_count?: number;
  clips?: Clip[];
  content_packs?: { id: string; clip_id: string; language: string; tone: string; data: ContentPack; updated_at: string }[];
  summary?: { duration?: number | null; highlights_found: number; top_clips_generated: number; average_score: number; content_packs_generated: number; seo_packages_generated: number };
}

export interface ProjectStatusResponse {
  id: string;
  status: ProjectStatus;
  progress: number;
  current_stage: string;
  error?: string | null;
  clip_count: number;
}

export interface ProcessingQueue {
  projects: { id: string; name: string; status: string; progress: number; current_stage: string; created_at: string }[];
  render_jobs: { id: string; project_id: string; clip_id: string; status: string; progress: number; message?: string | null; updated_at: string }[];
}

export interface ClipTemplate {
  id: string;
  name: string;
  description: string;
  premium: boolean;
  settings: Record<string, unknown>;
}

export interface SystemStatus {
  running_locally: boolean;
  privacy_mode: boolean;
  ai_provider: string;
  local_model: string;
  cloud_ai_allowed: boolean;
  cpu_percent?: number | null;
  memory_percent?: number | null;
  gpu: { available: boolean; name?: string | null; memory_used_mb?: number | null; memory_total_mb?: number | null };
  message: string;
}

export interface LibraryAsset {
  id: string;
  name: string;
  artist?: string;
  license: string;
  url: string;
  path: string;
}

export interface SocialConnection {
  id: string;
  provider_id: string;
  account_id: string;
  account_name: string;
  expires_at?: string | null;
  scopes: string[];
  metadata: Record<string, unknown>;
  status: string;
  error?: string | null;
}

export interface SocialProvider {
  id: string;
  name: string;
  short_name: string;
  color: string;
  configured_env: string[];
  configured: boolean;
  connected: boolean;
  connection_count: number;
  capabilities: { import_metadata: boolean; import_media: boolean; publish: boolean; schedule: boolean; thumbnail?: boolean };
  note: string;
  connections: SocialConnection[];
}

export interface SocialVideo {
  id: string;
  title: string;
  thumbnail_url?: string | null;
  duration?: number | null;
  created_at?: string | null;
  platform: string;
  views?: number | null;
  media_import_available?: boolean;
  permalink?: string | null;
}

export interface ContentPack {
  provider: string;
  notice: string;
  language: string;
  tone: string;
  hook: string;
  hooks: string[];
  title: string;
  titles: string[];
  description: { short: string; medium: string; long: string };
  hashtags: { broad: string[]; niche: string[]; topic: string[]; all: string[] };
  keywords: { primary: string; secondary: string[]; long_tail: string[]; related: string[] };
  seo: { score: number; title: number; description: number; keywords: number; hashtags: number; clarity: number; click_potential: number; suggestions: string[] };
  platforms: Record<string, Record<string, string | string[]>>;
}

export interface Plan {
  id: string;
  name: string;
  price_inr_monthly: number;
  badge: string;
  description: string;
  limits: { projects: number; monthly_source_minutes: number; daily_clips?: number; clips_per_project: number; storage_gb: number };
  features: string[];
  entitlements?: Record<string, boolean>;
  ads?: boolean;
  cloud_processing?: boolean;
  billing_required: boolean;
}

export interface Subscription {
  plan: Plan;
  plan_id: string;
  billing_configured: boolean;
  billing_status: string;
  source: string;
  message: string;
  subscription?: Record<string, unknown> | null;
}

export interface Usage {
  period: string;
  plan_id: string;
  source_minutes: number;
  projects: number;
  clips: number;
  daily_clips: number;
  daily_processing_jobs?: number;
  limits: { projects: number; monthly_source_minutes: number; daily_processing_jobs?: number; daily_clips: number; clips_per_project: number; storage_gb: number };
  remaining: { source_minutes: number; projects: number; daily_clips: number; daily_processing_jobs?: number };
  note: string;
}

export interface PrivacyStatus {
  enabled: boolean;
  cloud_ai: boolean;
  external_analytics: boolean;
  official_social_apis: boolean | string;
  message: string;
}

export interface UserSettings {
  language: "en" | "hi";
  default_clip_length: 15 | 30 | 45 | 60;
  default_aspect: "9:16" | "1:1" | "16:9";
  caption_style: string;
  caption_position: string;
  hook_style: string;
  hashtag_count: 5 | 10 | 20;
  default_platform: string;
  tone: string;
  brand_name: string;
  brand_description: string;
}

export interface CostStatus {
  free_mode: boolean;
  ai_processing: { status: string; detail: string };
  video_processing: { status: string; detail: string };
  storage: { status: string; detail: string };
  social_apis: { status: string; detail: string };
  paid_services: { status: string; detail: string };
  disabled_paid_features: string[];
}

export interface PublishItem {
  id: string;
  clip_id: string;
  platform: string;
  account_id?: string | null;
  caption: string;
  title: string;
  hashtags: string[];
  visibility: string;
  scheduled_at?: string | null;
  status: "Draft" | "Ready" | "Publishing" | "Published" | "Failed" | string;
  remote_id?: string | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}
