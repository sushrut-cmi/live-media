from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List
import re
from typing import Tuple
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from ingest_manager import ingest_manager

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VIDEOS_DIR = DATA_DIR / "videos_mp4"
CSV_FILE = DATA_DIR / "segment_metadata.csv"
LATEST_JSON = DATA_DIR / "latest_metadata.json"
CURRENT_INGEST_FILE = DATA_DIR / "current_ingest.json"

@asynccontextmanager
async def lifespan(app: FastAPI):
    ingest_manager.start_metadata_worker()
    try:
        yield
    finally:
        ingest_manager.stop_segmenter()
        ingest_manager.stop_metadata_worker()

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/video", StaticFiles(directory=str(VIDEOS_DIR)), name="video")

clients: set[WebSocket] = set()


DEFAULT_HIGHLIGHT_KEYWORDS = {
    "goal",
    "goals",
    "penalty",
    "penalties",
    "yellow card",
    "red card",
    "free kick",
    "corner",
    "save",
    "saved",
    "own goal",
    "hat-trick",
    "assist",
    "goal line",
    "counter attack",
}
STATE: Dict[str, Any] = {
    "live": False,
    "protocol": "srt",
    "sport_type": "football",
    "source_url": "",
    "title": "Control Room",
    "subtitle": "Broadcast Control Room",
    "clock": "67:31",
    "agents": 47,
    "highlights": 143,
    "live_url": "",
    "localized_url": "",
}

def _people_to_text(value) -> str:
    if not isinstance(value, list):
        return ""
    out = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            out.append(item.get("name", "") or item.get("label", "") or item.get("title", ""))
    return " ".join(x for x in out if x)


def _segment_blob(segment: Dict[str, Any]) -> str:
    md = segment.get("metadata") or {}
    parts = [
        segment.get("segment_name", ""),
        md.get("Headline", "") or md.get("headline", ""),
        md.get("description", "") or md.get("Description", ""),
        md.get("transcription", "") or md.get("Transcription", ""),
        " ".join(md.get("tags", []) or []),
        _people_to_text(md.get("people_recognition", [])),
    ]
    return " ".join(parts).lower()


def _matched_keywords(segment: Dict[str, Any]) -> list[str]:
    blob = _segment_blob(segment)
    return [kw for kw in DEFAULT_HIGHLIGHT_KEYWORDS if kw in blob]


def _build_persona_prompt(user_prompt: str, persona: str) -> str:
    persona = (persona or "editor").strip().lower()
    user_prompt = (user_prompt or "").strip()

    if persona == "editor":
        return user_prompt

    return (
        f"Create highlights for persona '{persona}'. "
        f"Use the user's request as the task brief: {user_prompt}"
    )
def reset_ingest_artifacts():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    for mp4_file in VIDEOS_DIR.glob("*.mp4"):
        try:
            mp4_file.unlink()
        except Exception:
            pass

    for path in [CSV_FILE, LATEST_JSON, CURRENT_INGEST_FILE]:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["index", "segment_name", "metadata"])


async def broadcast(message: Dict[str, Any]) -> None:
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def load_segments() -> List[Dict[str, Any]]:
    if not CSV_FILE.exists():
        return []

    rows: List[Dict[str, Any]] = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = row.get("metadata", "")
            metadata = {}
            if raw:
                try:
                    metadata = json.loads(raw)
                except Exception:
                    metadata = {}

            rows.append(
                {
                    "index": int(row.get("index") or len(rows)),
                    "segment_name": row.get("segment_name") or "",
                    "sport_type": metadata.get("sport_type", "football"),
                    "metadata": metadata,
                    "video_url": f"/video/{row.get('segment_name')}" if row.get("segment_name") else "",
                }
            )

    rows.reverse()
    return rows


def load_latest_metadata():
    if not LATEST_JSON.exists():
        return None

    try:
        with open(LATEST_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


async def run_highlights_orchestrator(prompt: str) -> Dict[str, Any]:
    import asyncio

    from strands_app.orchestrator import run_orchestrator

    # The Strands orchestrator is synchronous (and opens MCP sessions), so run
    # it in a worker thread to avoid blocking the FastAPI event loop.
    raw_text = await asyncio.to_thread(run_orchestrator, prompt)

    return {
        "raw_text": raw_text,
        "event_count": 1,
    }


@app.get("/api/control-state")
def control_state():
    return {**STATE, "workers": ingest_manager.status()}


@app.get("/api/live")
def live():
    return {
        "live": STATE["live"],
        "protocol": STATE["protocol"],
        "sport_type": STATE["sport_type"],
        "hls_url": STATE["live_url"],
        "playback_url": STATE["live_url"],
        "clock": STATE["clock"],
    }


@app.get("/api/localized")
def localized():
    return {
        "language": "en",
        "hls_url": STATE["localized_url"],
        "playback_url": STATE["localized_url"],
        "clock": STATE["clock"],
    }
@app.get("/api/highlights/default-clips")
def default_clips():
    segments = load_segments()
    clips = []

    for seg in segments:
        hits = _matched_keywords(seg)
        if not hits:
            continue

        md = seg.get("metadata") or {}
        clips.append(
            {
                "index": seg.get("index"),
                "segment_name": seg.get("segment_name"),
                "video_url": seg.get("video_url"),
                "sport_type": seg.get("sport_type") or md.get("sport_type") or "football",
                "headline": md.get("Headline") or md.get("headline") or seg.get("segment_name"),
                "priority": md.get("Priority") or md.get("priority"),
                "matched_keywords": hits,
                "reason": f"Matched: {', '.join(hits[:3])}",
                "metadata": md,
            }
        )

    return {
        "status": "success",
        "count": len(clips),
        "clips": clips,
    }
@app.post("/api/highlights/creative")
async def creative_highlights(payload: dict):
    user_prompt = (payload.get("prompt") or "").strip()
    persona = (payload.get("persona") or "editor").strip().lower()

    if not user_prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    final_prompt = _build_persona_prompt(user_prompt, persona)

   
    result = await run_highlights_orchestrator(final_prompt)

    return {
        "status": "success",
        "persona": persona,
        "prompt": final_prompt,
        "result": result,
    }
@app.get("/api/segments")
def segments():
    return {"segments": load_segments()}

@app.get("/api/metadata/latest")
def latest_metadata():
    latest = load_latest_metadata()
    if latest:
        return latest

    segments = load_segments()
    if segments:
        return {"latest": segments[0]}

    return {"latest": None}


@app.get("/api/usecases/metadata")
def usecase_metadata():
    return {
        "latest": load_latest_metadata(),
        "segments": load_segments(),
        "state": STATE,
        "workers": ingest_manager.status(),
    }


@app.post("/api/ingest/start")
async def ingest_start(payload: dict):
    reset_ingest_artifacts()

    source_url = (
        payload.get("url")
        or payload.get("source_url")
        or payload.get("hls_url")
        or ""
    ).strip()

    if not source_url:
        raise HTTPException(status_code=400, detail="url is required")

    protocol = str(payload.get("protocol", "srt")).lower()
    sport_type = str(payload.get("sport_type", "football")).lower()

    result = ingest_manager.start_segmenter(
        source_url=source_url,
        protocol=protocol,
        sport_type=sport_type,
        extra=payload,
    )

    STATE.update(
        {
            "live": True,
            "protocol": protocol,
            "sport_type": sport_type,
            "source_url": source_url,
            "title": payload.get("title") or STATE["title"],
            "live_url": payload.get("playback_url") or payload.get("hls_url") or source_url,
            "localized_url": payload.get("localized_url") or payload.get("playback_url") or source_url,
        }
    )

    await broadcast({"type": "ingest_started", "state": STATE})
    return {"ok": True, "state": STATE, "workers": ingest_manager.status(), "segmenter": result}


@app.post("/api/ingest/stop")
async def ingest_stop():
    ingest_manager.stop_segmenter()
    ingest_manager.stop_metadata_worker()
    STATE["live"] = False
    await broadcast({"type": "ingest_stopped", "state": STATE})
    return {"ok": True, "state": STATE, "workers": ingest_manager.status()}


@app.websocket("/ws/control")
async def ws_control(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        await ws.send_json({"type": "state", "state": STATE})
        while True:
            try:
                _ = await ws.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                await ws.send_json({"type": "state", "state": STATE})
    finally:
        clients.discard(ws)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("new_backend:app", host="0.0.0.0", port=8000, reload=True)
