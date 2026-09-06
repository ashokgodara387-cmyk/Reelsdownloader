"""
Status Downloader Backend
Powered by yt-dlp
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
import yt_dlp
import io
import re
import tempfile
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI(
    title="Status Downloader API",
    description="yt-dlp powered media downloader for Instagram, Facebook, YouTube, Twitter/X, etc.",
    version="1.0.0"
)

# Allow frontend (file:// or localhost) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)


class DownloadRequest(BaseModel):
    url: str
    format: Optional[str] = "best"   # best, mp4, mp3, audio
    quality: Optional[str] = None    # 720, 1080, etc.


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name[:120].strip() or "media"


def extract_info(url: str, extract_flat: bool = False) -> dict:
    """Extract metadata without downloading the full file."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": extract_flat,
        "noplaylist": True,
        # Helpful for Instagram / Facebook public content
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info


def get_best_formats(info: dict) -> List[dict]:
    """Return a simplified list of available formats (skip storyboards & images)."""
    formats = []
    seen = set()

    for f in info.get("formats", []):
        fmt_id = f.get("format_id") or ""
        ext = (f.get("ext") or "").lower()
        height = f.get("height")
        vcodec = f.get("vcodec") or "none"
        acodec = f.get("acodec") or "none"
        protocol = f.get("protocol") or ""
        filesize = f.get("filesize") or f.get("filesize_approx")

        # Skip storyboards, images, and pure metadata
        if ext in ("mhtml", "jpg", "png", "webp", "json") or "storyboard" in fmt_id.lower():
            continue
        if vcodec == "none" and acodec == "none":
            continue

        if vcodec == "none" and acodec != "none":
            kind = "audio"
            label = f"Audio ({ext})"
        elif acodec == "none" and vcodec != "none":
            kind = "video-only"
            label = f"{height}p video-only ({ext})" if height else f"Video-only ({ext})"
        else:
            kind = "video"
            label = f"{height}p ({ext})" if height else f"Video ({ext})"

        key = (kind, height, ext)
        if key in seen:
            continue
        seen.add(key)

        formats.append({
            "format_id": fmt_id,
            "label": label,
            "ext": ext,
            "height": height,
            "filesize": filesize,
            "kind": kind,
            "url": f.get("url"),
            "protocol": protocol,
        })

    # Prefer progressive (video+audio) → highest video → audio
    formats.sort(key=lambda x: (
        0 if x["kind"] == "video" else 1 if x["kind"] == "video-only" else 2,
        -(x["height"] or 0)
    ))
    return formats[:15]


@app.get("/")
async def root():
    return {
        "service": "Status Downloader API",
        "powered_by": "yt-dlp",
        "endpoints": {
            "POST /api/info": "Get metadata + available formats",
            "POST /api/download": "Get best download URL + metadata",
            "GET  /api/stream": "Stream the media file directly",
            "GET  /health": "Health check"
        }
    }


@app.get("/health")
async def health():
    try:
        version = yt_dlp.version.__version__
        return {"status": "ok", "yt_dlp": version}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/api/info")
async def media_info(req: DownloadRequest):
    """
    Extract metadata and available formats without downloading the full file.
    """
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, extract_info, url)

        if not info:
            raise HTTPException(status_code=404, detail="Could not extract media info")

        # Handle playlists / multi-entry (take first)
        if "entries" in info and info["entries"]:
            info = info["entries"][0]

        title = info.get("title") or info.get("fulltitle") or "Untitled"
        uploader = info.get("uploader") or info.get("channel") or info.get("creator") or ""
        thumbnail = info.get("thumbnail")
        duration = info.get("duration")
        description = (info.get("description") or "")[:300]
        webpage_url = info.get("webpage_url") or url
        extractor = info.get("extractor_key") or info.get("extractor") or "unknown"

        formats = get_best_formats(info)

        # Best overall video URL
        # 1) Prefer progressive (has both video + audio)
        # 2) Then highest quality video-only
        # 3) Then any available
        best_url = None
        best_ext = "mp4"
        best_format_id = None

        for f in formats:
            if f["kind"] == "video" and f.get("url"):
                best_url = f["url"]
                best_ext = f["ext"] or "mp4"
                best_format_id = f["format_id"]
                break

        if not best_url:
            for f in formats:
                if f["kind"] == "video-only" and f.get("url"):
                    best_url = f["url"]
                    best_ext = f["ext"] or "mp4"
                    best_format_id = f["format_id"]
                    break

        if not best_url:
            for f in formats:
                if f.get("url"):
                    best_url = f["url"]
                    best_ext = f["ext"] or "mp4"
                    best_format_id = f["format_id"]
                    break

        # Fallback: let yt-dlp pick the "best" format URL if available
        if not best_url and info.get("url"):
            best_url = info["url"]
            best_ext = info.get("ext") or "mp4"

        return {
            "success": True,
            "platform": extractor.lower(),
            "title": title,
            "uploader": uploader,
            "thumbnail": thumbnail,
            "duration": duration,
            "description": description,
            "webpage_url": webpage_url,
            "best_url": best_url,
            "best_ext": best_ext,
            "best_format_id": best_format_id,
            "formats": formats,
        }

    except yt_dlp.utils.DownloadError as e:
        msg = str(e).split("\n")[-1][:200]
        raise HTTPException(status_code=400, detail=f"Extraction failed: {msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)[:200]}")


@app.post("/api/download")
async def get_download(req: DownloadRequest):
    """
    Convenience endpoint – returns the best direct media URL + metadata.
    Frontend can use the returned URL to trigger a download.
    """
    # Re-use the info logic
    info_resp = await media_info(req)

    if not info_resp.get("best_url"):
        raise HTTPException(status_code=404, detail="No downloadable media found")

    return {
        "success": True,
        "title": info_resp["title"],
        "uploader": info_resp["uploader"],
        "thumbnail": info_resp["thumbnail"],
        "duration": info_resp["duration"],
        "platform": info_resp["platform"],
        "download_url": info_resp["best_url"],
        "ext": info_resp["best_ext"],
        "filename": sanitize_filename(info_resp["title"]) + "." + info_resp["best_ext"],
        "formats": info_resp["formats"],
    }


@app.get("/api/stream")
async def stream_media(
    url: str = Query(..., description="Original media page URL"),
    format_id: Optional[str] = Query(None, description="Specific format_id from /api/info")
):
    """
    Stream the media file through the backend.
    Useful when the CDN blocks direct browser downloads (CORS / hotlink protection).
    """
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")

    def download_to_bytes():
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": format_id or "best[ext=mp4]/best",
            "outtmpl": "-",          # stdout
            "noplaylist": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        }
        buffer = io.BytesIO()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # We download into a temp file then read, because stdout streaming
            # with yt-dlp can be unreliable for some extractors.
            with tempfile.TemporaryDirectory() as tmp:
                ydl_opts["outtmpl"] = os.path.join(tmp, "%(id)s.%(ext)s")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                    info = ydl2.extract_info(url, download=True)
                    filename = ydl2.prepare_filename(info)
                    if not os.path.exists(filename):
                        # try with different extension
                        for f in os.listdir(tmp):
                            filename = os.path.join(tmp, f)
                            break
                    with open(filename, "rb") as fh:
                        buffer.write(fh.read())
        buffer.seek(0)
        return buffer, info

    try:
        loop = asyncio.get_event_loop()
        buffer, info = await loop.run_in_executor(executor, download_to_bytes)

        title = sanitize_filename(info.get("title") or "media")
        ext = info.get("ext") or "mp4"
        media_type = "audio/mpeg" if ext in ("mp3", "m4a", "opus") else f"video/{ext}"

        headers = {
            "Content-Disposition": f'attachment; filename="{title}.{ext}"',
            "Content-Length": str(buffer.getbuffer().nbytes),
        }

        return StreamingResponse(
            buffer,
            media_type=media_type,
            headers=headers
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)[:200]}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
