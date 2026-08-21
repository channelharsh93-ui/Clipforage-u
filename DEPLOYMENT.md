# ClipForge deployment guide

## Short answer: when to deploy

Deploy in three stages:

1. **Now — local single-user deployment.** The current build is ready for local use and private testing. Keep `USER_PLAN=free`, `PRIVACY_MODE=true`, and `ALLOW_OFFICIAL_APIS=false` while validating real podcast, interview, gaming, comedy, and action-heavy videos.
2. **After acceptance testing — private LAN deployment.** Share it only with trusted users on the same network or through a private VPN. Confirm uploads, transcription, rendering, downloads, storage cleanup, and rights acknowledgement first.
3. **Only after security work — public deployment.** Authentication, secure sessions, CSRF checks, and per-user project scope are now included, but public multi-user operation still needs production hardening, backups, rate limits, and a durable worker/database plan. Do not expose the development server directly to the public Internet.

The Pro plan is a catalog/entitlement architecture. Razorpay is now available as an optional provider, but it remains disabled with `PAYMENT_PROVIDER=none` until you deliberately configure server-only test/live keys and an HTTPS webhook. Do not set `USER_PLAN=pro` for customers; activate access only from verified billing state.

## Option A: local deployment on one computer

### 1. Install prerequisites

- Python 3.11 or newer
- Node.js 18 or newer
- FFmpeg on PATH (recommended; `imageio-ffmpeg` is also included as a local fallback)
- At least 4 GB RAM; more is recommended for local Whisper transcription

### 2. Unpack and configure

```bash
unzip ClipForge-AI-Full.zip
cd viral-clip-generator
cp backend/.env.example backend/.env
```

Edit `backend/.env` for the machine. Safe zero-cost defaults are:

```env
USER_PLAN=free
FREE_MODE=true
LOCAL_AI=true
ALLOW_CLOUD_AI=false
PRIVACY_MODE=true
ALLOW_OFFICIAL_APIS=false
MAX_CLIPS=10
MAX_VIDEO_DURATION=1800
MAX_FILE_SIZE_MB=1000
MAX_STORAGE_GB=20
```

`MAX_CLIPS` is the Free daily/project cap and is reflected by `GET /api/plans`. The default Free plan also allows 2 processing jobs per day (`FREE_PLAN_VIDEOS=2`). Lower these on a small computer. Keep `STORAGE_ROOT` and `DATABASE_PATH` on a persistent local disk if the project directory is not persistent.

### 3. Install and start the API

```bash
cd backend
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
# .venv\\Scripts\\Activate.ps1

pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

For a first smoke test without the optional Whisper dependency:

```bash
pip install -r requirements-minimal.txt
```

The minimal installation will honestly report that local transcription is unavailable; it does not invent captions. The full installation may download the configured open-source Whisper model the first time transcription runs.

Check the API:

```bash
curl http://127.0.0.1:8001/api/system/status
curl http://127.0.0.1:8001/api/usage
```

### 4. Start the frontend for local use

In another terminal:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`.

The Vite development server proxies `/api` and `/media` to the API. This is the simplest local deployment, but it is a development server and should not be exposed publicly.

The repository also includes:

```bash
./run-backend.sh
./run-frontend.sh
```

## Option B: private LAN deployment

Use this only for trusted devices on the same network.

Start the API on the host machine:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 1
```

Start Vite with its existing host-allow configuration:

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

Find the host's LAN address, for example `192.168.1.20`, and open:

```text
http://192.168.1.20:5173
```

Do not forward ports from the router. Keep Privacy Mode on and leave official social APIs disabled until their OAuth setup has been reviewed.

## Option C: Vercel frontend + separate FastAPI API

Vercel can host the Vite frontend, but it cannot run this long-running FFmpeg/SQLite/Whisper backend as a static frontend deployment. Deploy the backend separately on a persistent Python host or your own server.

### Vercel project settings

Use one deployment layout only:

- Import this repository and set Vercel **Root Directory** to `frontend`.
- Framework Preset: **Vite**
- Install Command: `npm install`
- Build Command: `npm run build`
- Output Directory: `dist`

The included `frontend/vercel.json` handles SPA routes. There is intentionally no root-level Vite entry point or root-level `vercel.json`; Vercel must build from `frontend`.

Set this Vercel environment variable to the public backend URL:

```env
VITE_API_BASE_URL=https://api.example.com
```

Set the backend environment variables to the Vercel origin:

```env
FRONTEND_ORIGIN=https://your-project.vercel.app
PUBLIC_API_URL=https://api.example.com
SESSION_COOKIE_SECURE=true
AUTH_REQUIRED=true
```

The Vercel rewrite fixes browser refreshes for `/app`, `/verify-email`, `/reset-password`, and `/magic-login`. It does **not** replace the FastAPI backend or proxy uploads by itself. `VITE_API_BASE_URL` makes authentication, upload, media, billing, and API requests reach the separate backend.

After deployment, verify:

```bash
curl https://api.example.com/api/health
curl https://your-project.vercel.app/
```

Configure the Razorpay webhook against the API host, not the Vercel static host:

```text
https://api.example.com/api/billing/webhook/razorpay
```

## Option D: private production-style deployment with Nginx

Use this after local testing when you want a stable private server. Build the frontend once and serve it from Nginx; keep FastAPI bound to localhost.

### Build the frontend

```bash
cd frontend
npm install
npm run build
```

The output is `frontend/dist/`. Do not use `npm run dev` for this deployment.

### Run the API

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1
```

### Example Nginx server block

Replace `/opt/clipforge` with the absolute project path:

```nginx
server {
    listen 80;
    server_name clipforge.local;

    root /opt/clipforge/frontend/dist;
    client_max_body_size 1000M;

    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900s;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 900s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

For public HTTPS, add a real TLS certificate and redirect HTTP to HTTPS. Do not expose port 8001 directly.

## Enable Razorpay safely

Keep billing disabled until the application is deployed behind HTTPS. For test mode, set only on the backend host:

```env
PAYMENT_PROVIDER=razorpay
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=<server-only>
RAZORPAY_WEBHOOK_SECRET=<server-only>
PRO_PRICE_MONTHLY=99
```

For recurring monthly billing, create the ₹99 monthly plan in the Razorpay Dashboard and set:

```env
RAZORPAY_PLAN_ID_PRO=plan_...
RAZORPAY_USE_SUBSCRIPTIONS=true
```

Configure the Razorpay webhook URL:

```text
https://your-domain.example/api/billing/webhook/razorpay
```

Use the webhook secret in `RAZORPAY_WEBHOOK_SECRET`. The backend validates the raw-body HMAC signature, uses `x-razorpay-event-id` for idempotency, checks captured payment state, and activates Pro only after verification. Never put `RAZORPAY_KEY_SECRET` or `RAZORPAY_WEBHOOK_SECRET` in frontend code or Git.

## Before public deployment

The application is local-first, and authentication is enabled by default. Before making it public, add:

- Production review of authentication/authorization on every project, clip, asset, billing-interest, social, and publishing route.
- Hardened per-user storage/database isolation and migration of legacy ownerless data; do not expose one user's local files to another user.
- HTTPS, secure cookies, CSRF protection where applicable, and a restricted CORS origin instead of `*`.
- Upload rate limits, request quotas, a reverse proxy, and monitoring.
- A durable job queue/worker model rather than relying only on the in-process executor.
- Backups and a tested restore plan for SQLite and `backend/storage`.
- Secure secret management for OAuth credentials and `TOKEN_ENCRYPTION_KEY`.
- Official OAuth redirect URLs for each enabled platform and only the scopes required for the selected action.
- A real billing provider abstraction with verified webhooks before activating paid Pro entitlements.
- A clear privacy policy and rights/authorization flow for uploaded and published media.

Do not claim that the current zero-cost build provides unlimited scale, public multi-tenancy, or live paid upgrades.

## Deployment acceptance checklist

Run this before each release:

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
python -m compileall -q app
cd ../frontend
npm run build
```

Then verify:

- `GET /api/system/status` reports local processing.
- `GET /api/privacy` reports Privacy Mode enabled.
- `GET /api/usage` shows the configured Free daily limit.
- `GET /api/billing/status` reports `configured: false` in the zero-cost MVP.
- Free content packs and Pro templates are visibly locked.
- Free upload, analysis, editing, rendering, and download work with a real test video.
- Publishing requires Pro, official API/OAuth, rights acknowledgement, and explicit confirmation.
- The storage cap and upload/duration limits reject oversized inputs cleanly.
- No payment, cloud AI call, platform scrape, or automatic publication occurs.
