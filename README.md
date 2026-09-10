# TRIM. — a self-hosted video trimmer

Upload a video, drag the in/out handles on the filmstrip, hit trim, download the
clip. React (no build step — loaded straight from CDN via Babel) on the front,
FastAPI + ffmpeg on the back. One process serves both, so there's exactly one
thing to deploy.

```
video-trimmer/
├── backend/
│   ├── main.py            FastAPI app: upload / probe / trim / download
│   └── requirements.txt
├── frontend/
│   └── index.html         React app (CDN React + Babel, no npm/webpack needed)
├── storage/                per-upload working files (gitignored)
├── capcut-mcp/             MCP server for editing CapCut desktop draft projects
├── Dockerfile
└── render.yaml             one-click Render.com deploy config
```

## capcut-mcp

[`capcut-mcp/`](capcut-mcp/README.md) is a separate MCP server (Node.js,
stdio transport) that lets Claude read and edit **CapCut desktop draft
projects** directly — add/move/trim/split clips, text, audio, images; set
transforms; validate; save. It's pulled in from
[JmsLdrn/capcut-mcp](https://github.com/JmsLdrn/capcut-mcp) and is
independent of the trimmer app above (different runtime, different job —
CapCut project files rather than raw video files). See
[`capcut-mcp/README.md`](capcut-mcp/README.md) for setup, tools, and its
companion `capcut-reels` skill.

## Run it locally

You need Python 3.10+ and **ffmpeg** installed and on your PATH.

```bash
# 1. install ffmpeg (skip if you already have it)
#    macOS:   brew install ffmpeg
#    Ubuntu:  sudo apt install ffmpeg
#    Windows: choco install ffmpeg   (or download from ffmpeg.org)

# 2. install backend deps
cd video-trimmer
pip install -r backend/requirements.txt

# 3. run it — this also serves the frontend at the same address
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000** — that's the whole app, frontend and API
together.

## Run it with Docker (recommended — bundles ffmpeg for you)

```bash
cd video-trimmer
docker build -t trim-app .
docker run -p 8000:8000 trim-app
```

Open **http://localhost:8000**.

## Put it online for anyone in the world to use

Because the Dockerfile bundles ffmpeg and serves frontend + backend from one
process, any container host works. Three easy, free-tier-friendly options:

### Option A — Render.com (easiest)
1. Push this folder to a GitHub repo.
2. On Render: **New → Blueprint**, point it at the repo — it reads
   `render.yaml` automatically and deploys.
3. You get a public `https://your-app.onrender.com` URL. Free tier sleeps
   after inactivity and spins back up on the next request (~30s cold start).

### Option B — Railway.app
1. Push to GitHub, then on Railway: **New Project → Deploy from GitHub repo**.
2. Railway detects the `Dockerfile` automatically. No extra config needed.
3. Generate a public domain from the service's **Settings → Networking** tab.

### Option C — Fly.io (best latency worldwide — edge regions)
```bash
fly launch    # detects the Dockerfile, asks a few questions
fly deploy
```
Fly lets you add extra `fly regions add <region>` so the app runs close to
users on multiple continents.

Any of these give you a real `https://…` URL reachable from anywhere — no
port forwarding or home server needed.

## Notes on running this for real traffic

- **Storage cleanup**: uploaded/trimmed files sit in `storage/<video_id>/`
  and are never auto-deleted right now. For a public deployment, add a
  cron job (or a scheduled task on Render/Railway) that deletes folders
  older than a few hours, or call `DELETE /api/video/{video_id}` from the
  frontend once a download finishes.
- **Upload size cap**: currently 500MB per file (`MAX_UPLOAD_BYTES` in
  `backend/main.py`) — raise or lower it to match your host's plan.
- **Concurrent trims**: ffmpeg runs are offloaded to a thread pool so the
  server stays responsive, but heavy concurrent traffic on a free-tier
  host will queue up. Scale the host's CPU/RAM if that becomes an issue.
- **HTTPS**: Render, Railway, and Fly all provide free HTTPS on their
  generated domains automatically.
