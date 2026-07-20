# AI for Live — Media Control Room

An agentic pipeline for **live sports video**: it ingests a stream, splits it
into short clips, auto-tags each clip with AI-generated metadata, and exposes
two specialist agents that can **create highlight reels** and **localize
(dub) videos** into other languages.

The agents are built with the **[Strands Agents SDK](https://strandsagents.com)**
and run on **AWS Bedrock — Amazon Nova**. Tools are provided over **MCP** (Model
Context Protocol). A FastAPI backend drives the whole thing.

> This project was migrated from Google ADK + Gemini to Strands + Bedrock Nova.
> See [`strands_app/README.md`](strands_app/README.md) for the ADK→Strands
> mapping details.

---

## Architecture

```
                        ┌─────────────────────────────────────────────┐
   live stream / URL    │                new_backend.py                │
   ───────────────────► │              FastAPI control plane           │
                        │           (:8000, /api/ingest/start)         │
                        └───────────────┬───────────────┬─────────────-┘
                                        │ starts        │ starts
                                        ▼               ▼
                        ┌───────────────────┐   ┌────────────────────────┐
                        │ mp4_segmenter1.py │   │   metadata_mp4_1.py     │
                        │  ffmpeg splits    │   │  watches videos_mp4/,   │
                        │  stream into      │   │  Nova analyzes each     │
                        │  ~30s .mp4 clips  │   │  clip → CSV metadata    │
                        └─────────┬─────────┘   └───────────┬────────────┘
                                  │ writes                  │ writes
                                  ▼                         ▼
                        data/videos_mp4/*.mp4      data/segment_metadata.csv
                                  │                         │
                                  └──────────┬──────────────┘
                                             ▼
                        ┌────────────────────────────────────────────┐
                        │        strands_app/  (Bedrock Nova)         │
                        │                                             │
                        │   OrchestratorAgent  ── routes to ──┐       │
                        │        │                            │       │
                        │        ▼                            ▼       │
                        │  HighlightsAgent            LocalizationAgent│
                        │        │ MCP (stdio)            │ MCP (SSE)  │
                        │        ▼                        ▼            │
                        │  highlights_mcp_server   localization_mcp_server
                        └────────────────────────────────────────────┘
                                  │                         │
                                  ▼                         ▼
                        data/highlights_mp4/       localized .mp4 output
```

---

## Components

| File | Role |
|---|---|
| **`strands_app/orchestrator.py`** | Top-level agent. Routes a request to the highlights or localization specialist (agents-as-tools). |
| **`strands_app/highlight_agent.py`** | Selects the best clip(s) for an intent/persona and composes a highlight reel. |
| **`strands_app/localization_agent.py`** | Transcribe → translate → TTS → merge, to dub a video into another language. |
| **`strands_app/config.py`** | Shared model builder (Bedrock Nova) + MCP client wiring. **Configure models here.** |
| `highlights_mcp_server.py` | MCP tools: load metadata/personas, query by time, compose highlight MP4 (ffmpeg). |
| `localization_mcp_server.py` | MCP tools: transcribe, translate, TTS, merge (calls camb.ai + ffmpeg). SSE server. |
| `new_backend.py` | **Main** FastAPI backend: ingest control, segments/metadata APIs, WebSocket. |
| `ingest_manager.py` | Supervises the segmenter + metadata worker subprocesses. |
| `mp4_segmenter1.py` | ffmpeg: splits a live stream into short MP4 clips. |
| `metadata_mp4_1.py` | Watches new clips, analyzes each with Nova, writes metadata CSV. |
| `main.py` | Older/alternate FastAPI backend (no agents). Superseded by `new_backend.py`. |
| `persona.json` | Example persona used by highlight selection. |

---

## Prerequisites

1. **Python 3.10+**
2. **ffmpeg** on your `PATH` — required by the segmenter, highlights compose, and
   localization merge.
   - Windows: `winget install Gyan.FFmpeg` (then reopen the terminal)
   - macOS: `brew install ffmpeg`
   - Linux: `apt install ffmpeg`
3. **AWS account with Bedrock access:**
   - In the AWS console → *Bedrock → Model access*, enable the **Amazon Nova**
     models in your region.
   - IAM permissions: `bedrock:InvokeModel` and
     `bedrock:InvokeModelWithResponseStream` on the Nova model ARNs.
4. **(Localization only)** a [camb.ai](https://camb.ai) API key — currently set
   inside `localization_mcp_server.py`.

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
#    then edit .env — set AWS credentials, region, and model IDs
```

---

## Configuration

Everything is driven by environment variables (see [`.env.example`](.env.example)).

| Variable | Default | What it controls |
|---|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | AWS credentials (or use a profile / IAM role) |
| `AWS_REGION` | `us-east-1` | Region for all Bedrock calls |
| `BEDROCK_MODEL_ID` | `us.amazon.nova-pro-v1:0` | Model for the **agents** ([config.py](strands_app/config.py)) |
| `BEDROCK_METADATA_MODEL_ID` | `us.amazon.nova-lite-v1:0` | Model for the **metadata worker** ([metadata_mp4_1.py](metadata_mp4_1.py)) — must be Lite/Pro |
| `MAX_INLINE_VIDEO_MB` | `24` | Max clip size sent inline to Bedrock |
| `SOURCE_URL` | — | Live stream URL (for standalone segmenter runs) |
| `SEGMENT_TIME` | `30` | Clip length in seconds |
| `LOCALIZATION_MCP_URL` | `http://localhost:8000/sse` | Where the localization agent finds its MCP server |

**Valid Nova model IDs:** `us.amazon.nova-micro-v1:0` (text-only),
`us.amazon.nova-lite-v1:0`, `us.amazon.nova-pro-v1:0`,
`us.amazon.nova-premier-v1:0`. Use the `us.` / `eu.` / `apac.` inference-profile
prefix matching your region.

---

## How to run

### Step 1 — Start the backend (ingest + metadata worker)

```bash
python new_backend.py          # serves http://localhost:8000
```

This starts the FastAPI control plane and the metadata worker automatically.

### Step 2 — Ingest video

**Option A — live stream (automatic segmentation):**

```bash
curl -X POST http://localhost:8000/api/ingest/start \
  -H "Content-Type: application/json" \
  -d '{"url":"https://.../stream.m3u8","protocol":"hls","sport_type":"football"}'
```

Clips land in `data/videos_mp4/` and metadata rows appear in
`data/segment_metadata.csv` within seconds. Stop with
`POST /api/ingest/stop`.

**Option B — upload your own MP4s:**

1. Copy `.mp4` files into `data/videos_mp4/`.
   - Keep clips **~10s each** (the time-range tools assume 6 clips/minute).
   - Name them so alphabetical = chronological (`segment_001.mp4`, `002`, …).
   - ⚠️ Do **not** call `/api/ingest/start` — it wipes `data/videos_mp4/` first.
2. Make sure the metadata worker is running (it is, if the backend is up), or
   run it standalone: `python metadata_mp4_1.py`.

### Step 3 — Run the agents

**Highlights** (auto-launches its stdio MCP server):
```bash
cd strands_app
python highlight_agent.py
# or the orchestrator, which routes automatically:
python orchestrator.py
```

**Localization** (needs its SSE MCP server running first):
```bash
python localization_mcp_server.py          # terminal 1 (SSE on :8000)
cd strands_app && python localization_agent.py   # terminal 2
```

**From the backend** — the orchestrator is also wired into the API:
```bash
curl -X POST http://localhost:8000/api/highlights/creative \
  -H "Content-Type: application/json" \
  -d '{"prompt":"create a highlight of the free kick for Tottenham","persona":"editor"}'
```

---

## Backend API (`new_backend.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/control-state` | Current state + worker status |
| GET | `/api/live` | Live stream info |
| GET | `/api/localized` | Localized stream info |
| GET | `/api/segments` | All ingested segments + metadata |
| GET | `/api/metadata/latest` | Most recent segment |
| GET | `/api/highlights/default-clips` | Keyword-matched highlight candidates |
| POST | `/api/highlights/creative` | Run the orchestrator agent (`{prompt, persona}`) |
| POST | `/api/ingest/start` | Start ingest (`{url, protocol, sport_type}`) |
| POST | `/api/ingest/stop` | Stop ingest |
| WS | `/ws/control` | Live state updates |
| GET | `/video/{filename}` | Stream a clip (static mount) |

---

## Data & directory layout

```
live-media/
├── strands_app/            # the agents (Strands + Bedrock Nova)
├── data/
│   ├── videos_mp4/         # ← ingested/uploaded clips go HERE
│   ├── highlights_mp4/     # composed highlight output
│   ├── segment_metadata.csv    # auto-generated per-clip metadata
│   ├── latest_metadata.json    # latest snapshot
│   └── current_ingest.json     # active ingest config
├── logs/                   # segmenter / metadata worker logs
├── .env                    # your config (copy of .env.example)
└── requirements.txt
```

---

## Troubleshooting

- **⚠️ Port 8000 conflict:** both `new_backend.py` and the localization MCP
  server (`localization_mcp_server.py`) default to port 8000. Run them on
  different ports, e.g. change the backend's uvicorn port or the FastMCP port,
  and update `LOCALIZATION_MCP_URL` accordingly.
- **`AccessDeniedException` / model not found:** enable the Nova model in
  *Bedrock → Model access* and confirm your region + IAM permissions.
- **`ffmpeg: command not found`:** install ffmpeg and reopen the terminal.
- **Highlights agent finds no segments:** the metadata worker must be running so
  `segment_metadata.csv` gets populated — uploading videos alone isn't enough.
- **Nova returns non-JSON:** the metadata worker's `extract_json` handles stray
  prose, but if you see markdown fences, reinforce "Output ONLY valid JSON" in
  the `SPORT_PROMPTS` in `metadata_mp4_1.py`.
- **MCP tool errors in Strands:** MCP tools are only valid inside the client's
  `with` block — the agents already handle this; keep that pattern if you edit
  them.
