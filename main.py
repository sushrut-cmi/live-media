from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VIDEO_DIR = DATA_DIR / "videos_mp4"
CSV_FILE = DATA_DIR / "segment_metadata.csv"

DEFAULT_HLS_URL = "https://d1zg15j6dk79m2.cloudfront.net/live/stream1_1.m3u8"

STATE: Dict[str, Any] = {
    "live": False,
    "protocol": "srt",
    "clock": "67:31",
    "title": "Liverpool vs Arsenal",
    "subtitle": "Broadcast Control Room",
    "agents": 47,
    "highlights": 143,
    "language": "en",
    "live_url": DEFAULT_HLS_URL,
    "localized_url": DEFAULT_HLS_URL,
    "source": {},
}

CLIENTS: set[WebSocket] = set()


def _segment_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("metadata")
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            pass

    return {
        "Headline": row.get("Headline") or row.get("headline") or row.get("segment_name") or "",
        "description": row.get("description") or "",
        "tags": row.get("tags") or [],
        "people_recognition": row.get("people_recognition") or [],
        "transcription": row.get("transcription") or "",
        "Priority": row.get("Priority") or row.get("priority") or "",
    }


def load_segments() -> List[Dict[str, Any]]:
    if not CSV_FILE.exists():
        return []

    try:
        df = pd.read_csv(CSV_FILE)
    except Exception:
        return []

    items: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        meta = _segment_metadata(row_dict)

        items.append(
            {
                "id": int(row_dict.get("index", len(items))),
                "segment_name": row_dict.get("segment_name") or row_dict.get("segment") or "",
                "metadata": meta,
                "video_url": f"/video/{row_dict.get('segment_name')}" if row_dict.get("segment_name") else "",
            }
        )

    return items


async def broadcast(event: Dict[str, Any]) -> None:
    stale = []
    payload = {"state": STATE, **event}

    for client in list(CLIENTS):
        try:
            await client.send_json(payload)
        except Exception:
            stale.append(client)

    for client in stale:
        CLIENTS.discard(client)


@app.get("/")
def root():
    return {"status": "ok", "service": "ai-for-live-control-room"}


@app.get("/api/control-state")
def control_state():
    return STATE


@app.get("/api/live")
def live():
    return {
        "hls_url": STATE["live_url"],
        "playback_url": STATE["live_url"],
        "live": STATE["live"],
        "protocol": STATE["protocol"],
        "clock": STATE["clock"],
    }


@app.get("/api/localized")
def localized():
    return {
        "hls_url": STATE["localized_url"],
        "playback_url": STATE["localized_url"],
        "language": STATE["language"],
        "clock": STATE["clock"],
    }


@app.get("/api/segments")
def segments():
    return load_segments()


@app.get("/api/search")
def search(query: str = ""):
    data = load_segments()
    query = query.strip().lower()
    results = []

    for item in data:
        meta = item.get("metadata", {})
        score = 0

        headline = str(meta.get("Headline") or "").lower()
        description = str(meta.get("description") or "").lower()
        transcription = str(meta.get("transcription") or "").lower()
        tags = [str(t).lower() for t in meta.get("tags", [])]
        people = [str(p).lower() for p in meta.get("people_recognition", [])]

        if not query:
            score = 1
        else:
            if query in headline:
                score += 5
            if query in description:
                score += 3
            if query in transcription:
                score += 4
            score += sum(5 for tag in tags if query in tag)
            score += sum(2 for person in people if query in person)

        if score > 0:
            results.append(
                {
                    "score": score,
                    "id": item["id"],
                    "segment_name": item["segment_name"],
                    "headline": meta.get("Headline") or "",
                    "description": meta.get("description") or "",
                    "priority": meta.get("Priority") or "",
                    "metadata": meta,
                    "video_url": item["video_url"],
                }
            )

    results.sort(key=lambda row: row["score"], reverse=True)
    return {"results": results[:30]}


@app.post("/api/ingest/start")
async def ingest_start(payload: dict):
    protocol = str(payload.get("protocol", "srt")).lower()
    source_url = str(payload.get("url") or payload.get("source_url") or "").strip()
    playback_url = source_url if protocol in {"hls", "file"} and source_url else DEFAULT_HLS_URL

    if protocol == "file":
        playback_url = payload.get("file_url") or playback_url

    STATE.update(
        {
            "live": True,
            "protocol": protocol,
            "live_url": playback_url,
            "localized_url": playback_url,
            "source": payload,
        }
    )

    await broadcast({"type": "ingest_started", "message": f"Ingest started with {protocol.upper()}"})

    return {
        "ok": True,
        "state": STATE,
        "playback_url": playback_url,
        "localized_url": STATE["localized_url"],
    }


@app.post("/api/ingest/stop")
async def ingest_stop():
    STATE["live"] = False
    await broadcast({"type": "ingest_stopped", "message": "Ingest stopped"})
    return {"ok": True, "state": STATE}


@app.post("/api/streams/{stream_id}/language")
async def set_language(stream_id: str, payload: dict):
    language = str(payload.get("language", "en")).strip().lower()
    STATE["language"] = language
    await broadcast({"type": "language_changed", "message": f"Language set to {language.upper()}"})
    return {
        "ok": True,
        "stream_id": stream_id,
        "language": language,
        "localized_url": STATE["localized_url"],
        "state": STATE,
    }


@app.post("/api/highlights")
async def highlights(payload: dict):
    await broadcast({"type": "highlights", "message": "Highlights requested"})
    return {
        "ok": True,
        "requested": payload,
        "clips": load_segments()[:5],
    }


@app.post("/api/localize")
async def localize(payload: dict):
    language = str(payload.get("target_language", STATE["language"])).strip().lower()
    STATE["language"] = language
    await broadcast({"type": "localize", "message": f"Localization requested for {language.upper()}"})
    return {
        "ok": True,
        "language": language,
        "localized_url": STATE["localized_url"],
        "state": STATE,
    }


@app.post("/api/chat")
async def chat(payload: dict):
    message = str(payload.get("message", "")).strip()
    await broadcast({"type": "chat", "message": f"Chat received: {message[:80]}"})
    return {
        "ok": True,
        "steps": [
            {"agent": "Orchestrator", "message": "Processing request"},
            {"agent": "Highlights", "message": "Ready"},
            {"agent": "Localization", "message": "Ready"},
        ],
    }


@app.websocket("/ws/control")
async def ws_control(socket: WebSocket):
    await socket.accept()
    CLIENTS.add(socket)

    try:
        await socket.send_json({"type": "state", "state": STATE})

        while True:
            try:
                message = await socket.receive_text()
                if message:
                    await socket.send_json({"type": "echo", "message": message})
            except WebSocketDisconnect:
                break
            except Exception:
                await socket.send_json({"type": "state", "state": STATE})
    finally:
        CLIENTS.discard(socket)


@app.get("/video/{filename}")
def video(filename: str, request: Request):
    path = (VIDEO_DIR / filename).resolve()
    if not str(path).startswith(str(VIDEO_DIR.resolve())) or not path.exists():
        return JSONResponse({"error": "Video not found"}, status_code=404)

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        start, end = range_header.replace("bytes=", "").split("-")
        start = int(start or 0)
        end = int(end) if end else file_size - 1

        with open(path, "rb") as handle:
            handle.seek(start)
            chunk = handle.read(end - start + 1)

        return StreamingResponse(
            iter([chunk]),
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Type": "video/mp4",
            },
        )

    return FileResponse(path)


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)