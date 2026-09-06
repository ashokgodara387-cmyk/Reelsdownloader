# Status Downloader – yt-dlp Backend

FastAPI backend powered by **yt-dlp** for downloading public media from Instagram, Facebook, YouTube, Twitter/X, and many other sites.

## Quick Start

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Backend will be available at: http://127.0.0.1:8000

## API Endpoints

| Method | Endpoint          | Description                                      |
|--------|-------------------|--------------------------------------------------|
| GET    | `/`               | Service info                                     |
| GET    | `/health`         | Health check + yt-dlp version                    |
| POST   | `/api/info`       | Extract metadata + available formats             |
| POST   | `/api/download`   | Get best download URL + metadata (recommended)   |
| GET    | `/api/stream`     | Stream the media file through the backend        |

### Example – Get download link

```bash
curl -X POST http://127.0.0.1:8000/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

### Example – Stream file

```
http://127.0.0.1:8000/api/stream?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

## Frontend

Open `../status-downloader.html` in a browser.  
It automatically talks to `http://127.0.0.1:8000`.

## Notes

- Only **public** content works reliably without cookies.
- Instagram / Facebook may require session cookies for some content (Stories, private posts, age-restricted).
- Keep yt-dlp updated: `pip install -U yt-dlp`
- For production, add rate limiting, authentication, and proxies.
