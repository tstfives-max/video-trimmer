"""
TRIM. — a minimal, self-hosted video trimmer.
FastAPI backend: upload -> probe -> trim (ffmpeg) -> download.
Serves the React (CDN/Babel, no build step) frontend from /frontend as static files.
"""

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
FRONTEND_DIR = BASE_DIR / "frontend"
STORAGE_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB safety cap
ALLOWED_CONTENT_PREFIXES = ("video/",)

# Optional WeChat notification on trim completion, sent via the notifier
# service in bot/ (see bot/notifier.js). Leave unset to disable.
NOTIFIER_URL = os.environ.get("NOTIFIER_URL")


async def notify_trim_complete(video_id: str) -> None:
    if not NOTIFIER_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{NOTIFIER_URL}/notify",
                json={"message": f"Your video ({video_id}) has finished trimming and is ready to download."},
            )
    except Exception:
        pass  # notification is best-effort and must never fail the trim request

app = FastAPI(title="TRIM. video trimmer")

# Same-origin by default (frontend is served by this app), but allow all
# origins too in case someone hosts the frontend separately.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def run_ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def run_ffmpeg_trim(src: Path, dst: Path, start: float, end: float) -> None:
    duration = max(0.05, end - start)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-4000:])


def job_dir(video_id: str) -> Path:
    d = STORAGE_DIR / video_id
    if not d.exists():
        raise HTTPException(status_code=404, detail="Unknown video_id.")
    return d


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith(ALLOWED_CONTENT_PREFIXES):
        raise HTTPException(status_code=400, detail="Please upload a video file.")

    video_id = uuid.uuid4().hex
    vdir = STORAGE_DIR / video_id
    vdir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "upload.mp4").suffix or ".mp4"
    src_path = vdir / f"original{suffix}"

    size = 0
    with src_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                shutil.rmtree(vdir, ignore_errors=True)
                raise HTTPException(status_code=413, detail="File is too large (500MB limit).")
            out.write(chunk)

    try:
        duration = await asyncio.get_event_loop().run_in_executor(None, run_ffprobe_duration, src_path)
    except Exception:
        shutil.rmtree(vdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Could not read this file as a video.")

    return {
        "video_id": video_id,
        "filename": file.filename,
        "duration": duration,
    }


class TrimRequest(BaseModel):
    video_id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)


@app.post("/api/trim")
async def trim(req: TrimRequest):
    vdir = job_dir(req.video_id)
    srcs = list(vdir.glob("original.*"))
    if not srcs:
        raise HTTPException(status_code=404, detail="Original upload not found.")
    src = srcs[0]

    duration = await asyncio.get_event_loop().run_in_executor(None, run_ffprobe_duration, src)
    start = max(0.0, req.start)
    end = min(duration, req.end)
    if end - start < 0.1:
        raise HTTPException(status_code=400, detail="Trim range is too short.")

    dst = vdir / "trimmed.mp4"
    try:
        await asyncio.get_event_loop().run_in_executor(None, run_ffmpeg_trim, src, dst, start, end)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {e}")

    await notify_trim_complete(req.video_id)
    return {"video_id": req.video_id, "download_url": f"/api/download/{req.video_id}"}


@app.get("/api/download/{video_id}")
async def download(video_id: str):
    vdir = job_dir(video_id)
    dst = vdir / "trimmed.mp4"
    if not dst.exists():
        raise HTTPException(status_code=404, detail="No trimmed file yet — trim it first.")
    return FileResponse(dst, media_type="video/mp4", filename="trimmed.mp4")


@app.delete("/api/video/{video_id}")
async def delete_video(video_id: str):
    vdir = STORAGE_DIR / video_id
    shutil.rmtree(vdir, ignore_errors=True)
    return {"deleted": True}


# Serve the no-build React frontend at "/"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
