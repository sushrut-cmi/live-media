# Strands port of the live-media agentic flow

This folder is a 1:1 conversion of the Google ADK agents into the
[Strands Agents SDK](https://strandsagents.com). The FastMCP tool servers and
the FastAPI backend are **unchanged** — only the three ADK agents were ported.

## What maps to what

| Google ADK (original)                              | Strands (this folder)                           |
| -------------------------------------------------- | ----------------------------------------------- |
| `orchestrator.py` → `LlmAgent` + `AgentTool`       | `orchestrator.py` → `Agent` + `@tool` wrappers  |
| `highlight_agent.py` → `LlmAgent` + stdio McpToolset | `highlight_agent.py` → `Agent` + `MCPClient(stdio)` |
| `localization_agent.py` → `Agent` + SSE McpToolset | `localization_agent.py` → `Agent` + `MCPClient(sse)` |
| `model="gemini-2.5-flash"`                         | `config.build_model()` (Bedrock → Amazon Nova)  |
| `InMemoryRunner(agent).run_debug(query)`           | `agent(query)` (direct callable)                |
| `AgentTool(agent=sub_agent)`                        | agents-as-tools: `@tool` function per specialist |

**Files unchanged:** `highlights_mcp_server.py`, `localization_mcp_server.py`,
`new_backend.py`, `ingest_manager.py`, `mp4_segmenter1.py`, `metadata_mp4_1.py`.
Strands speaks MCP natively, so the FastMCP servers work as-is.

## Key behavioural difference vs ADK

In Strands, MCP tools are only valid **while the MCP session is open**. So each
agent builds and runs itself inside a `with mcp_client:` block (see
`run_highlights` / `run_localization`). ADK hid this lifecycle inside
`McpToolset`; Strands makes it explicit.

## Setup

```bash
pip install -r requirements.txt

# AWS Bedrock (Amazon Nova) — standard AWS credential chain:
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1                 # region where Nova is enabled
export BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0   # optional; this is the default
# (Windows PowerShell: $env:AWS_ACCESS_KEY_ID="..."  etc.)
```

**Prerequisites for Nova on Bedrock:**
1. In the AWS console → *Bedrock → Model access*, enable the Amazon Nova models
   in your region.
2. The IAM principal needs `bedrock:InvokeModel` and
   `bedrock:InvokeModelWithResponseStream` on the Nova model ARN.
3. Use the cross-region inference profile IDs (`us.` / `eu.` / `apac.` prefix)
   for on-demand throughput.

Model choices (set `BEDROCK_MODEL_ID`):
`us.amazon.nova-pro-v1:0` (default, most capable) ·
`us.amazon.nova-lite-v1:0` (cheaper, multimodal) ·
`us.amazon.nova-micro-v1:0` (text-only, cheapest).

To fall back to Gemini (LiteLLM or Vertex), see the commented options in
`config.py`.

## Run

```bash
# 1) Highlights agent needs its stdio MCP server on disk (auto-launched).
#    Just run it:
python highlight_agent.py

# 2) Localization agent talks to the SSE MCP server — start it first:
python ../localization_mcp_server.py        # serves http://localhost:8000/sse
python localization_agent.py                # in another terminal

# 3) Orchestrator (routes to the two specialists):
python orchestrator.py
```

> Note: the localization MCP server uses SSE on port 8000, which is also the
> default FastAPI port. Run one or the other, or set `LOCALIZATION_MCP_URL` and
> the server's port accordingly.

## Wiring into the FastAPI backend

`new_backend.py` currently calls the ADK orchestrator:

```python
async def run_highlights_orchestrator(prompt: str) -> Dict[str, Any]:
    from google.adk.runners import InMemoryRunner
    from orchestrator import orchestrator_agent
    runner = InMemoryRunner(agent=orchestrator_agent)
    events = await runner.run_debug(prompt)
    ...
```

Replace it with the Strands version (note it is synchronous, so offload it to a
thread to avoid blocking the event loop):

```python
async def run_highlights_orchestrator(prompt: str) -> Dict[str, Any]:
    import asyncio
    from strands_app.orchestrator import run_orchestrator
    raw_text = await asyncio.to_thread(run_orchestrator, prompt)
    return {"raw_text": raw_text, "event_count": 1}
```
