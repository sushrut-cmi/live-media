"""
Strands port of highlight_agent.py (ADK `HighlightsComposerAgent`).

ADK original:
    root_agent = LlmAgent(
        name="HighlightsComposerAgent",
        model="gemini-2.5-flash",
        instruction=prompt,
        tools=[McpToolset(StdioConnectionParams(...))],
    )

Strands: an Agent whose tools come from the highlights FastMCP server over
stdio. Because Strands requires MCP tools to be used while the MCP session is
open, the agent is built and run *inside* the client's `with` block.
"""

from __future__ import annotations

from strands import Agent

# Works both as a package import (`from strands_app.highlight_agent import ...`)
# and when run directly from inside strands_app/ (`python highlight_agent.py`).
try:
    from .config import build_model, make_highlights_mcp_client
except ImportError:
    from config import build_model, make_highlights_mcp_client

# ============================================================================
# AGENT PROMPT  (verbatim from the ADK agent)
# ============================================================================
PROMPT = """
You are an intelligent sports/video highlights/summmary editor.

Your task:
- Understand user intent
- Analyze segment metadata semantically
- Select best highlight segments
- Generate final highlight playlist
Workflow for summary creation
1.Understand the intent
Examples:
"What happend in last 5min?"
"Whnat happend between 0-5min"
2.Get required metadata using tools based on tools
-get_recent_segments
-get_segments_by_time_range
3.summarize what is happend in the time period
4.If intent also has to create video for summary the use compose_video tool by giving indices needed to added in video and generate the sumamry clip
Final Output format:
{
  "intent": "...",
  "summary": "...",
  "video_path": "...",//if asked
  "status": "success"
}

WORKFLOW for highlight creation:

1. Understand the intent

Examples:
- "columbia scoring goal"
- "best emotional moments"
- "engineer view"
- "defensive mistakes"
- "funny reactions"
2. If intent needs persona load persona
Examples:
- "create highlight based on persona"
- "Highlights based on my person"

3. Call load_metadata

4. Analyze ALL segments carefully

Each segment contains:
- transcript
- semantic description
- tags
- timestamp
- OCR
- commentary

5. Select MOST relevant segment and its index

Rules:
- Choose only one segment which is most relevant
- Select one clip which has most reevance and most priority score
- Avoid too many clips
- Quality > quantity
- Think semantically
- Understand sports events naturally

6. Call compose_highlight_playlist with selected index(for 1 intent 1 call)

IMPORTANT:
- Pass ONLY 1 selected_index which is relavent
- Composer automatically adds ±2 context
- Donot add your own final path just the path given by compose tool
Final Output Format:

{
  "intent": "...",
  "selected_index": [...],
  "playlist_path": "...",
  "status": "success"
}
"""

AGENT_NAME = "HighlightsComposerAgent"


def run_highlights(query: str) -> str:
    """Run the highlights agent for a single query and return its final text.

    MCP tools are only valid while the MCP session is open, so we open the
    client, build the Agent with the discovered tools, and run it — all inside
    the `with` block.
    """
    mcp_client = make_highlights_mcp_client()
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
    query = "create a highlight of Free kick awarded to Tottenham"
    print(run_highlights(query))
