"""
Strands port of localization_agent.py (ADK `LocalizationAgent`).

ADK original:
    root_agent = Agent(
        name="LocalizationAgent",
        model="gemini-2.5-flash",
        instruction=...,
        tools=[McpToolset(SseConnectionParams(url="http://localhost:8000/sse"))],
    )

The localization FastMCP server must be running as an SSE server first:
    python localization_mcp_server.py
"""

from __future__ import annotations

from strands import Agent

# Works both as a package import and when run directly from inside strands_app/.
try:
    from .config import build_model, make_localization_mcp_client
except ImportError:
    from config import build_model, make_localization_mcp_client

# ============================================================================
# AGENT PROMPT  (verbatim from the ADK agent)
# ============================================================================
PROMPT = """
You MUST follow steps in order:

1. transcribe_video
2. translate_text
3. generate_tts
4. merge_audio_video

Rules:
- Use tool outputs correctly
- Do NOT skip steps
- Temp audio path is auto handled

Return:
{
  "output_video_path": "...",
  "status": "success"
}
"""

AGENT_NAME = "LocalizationAgent"


def run_localization(query: str) -> str:
    """Run the localization agent for a single query and return its final text."""
    mcp_client = make_localization_mcp_client()
    with mcp_client:
        tools = mcp_client.list_tools_sync()
        agent = Agent(
            name=AGENT_NAME,
            model=build_model(),
            system_prompt=PROMPT,
            tools=tools,
        )
        result = agent(query)
        return str(result)


if __name__ == "__main__":
    query = """
    video_path: /home/tummala_venkata/ai_for_live/backend/data/videos/segment_003.mp4
    source_language: English
    target_language: Spanish
    voice: Sushrut
    output_video_path: /home/tummala_venkata/ai_for_live/backend/data/videos/segment_003_spanish.mp4
    """
    print(f"--- Processing Query: {query} ---\n")
    print(run_localization(query))
