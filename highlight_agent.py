import asyncio
from dotenv import load_dotenv

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams
)

from mcp import StdioServerParameters

from google.adk.runners import InMemoryRunner

load_dotenv()



tools = [
    McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python3",
                args=[
                    "/home/tummala_venkata/ai_for_live/new_backend/highlights_mcp_server.py"
                ],
            )
        )
    )
]

# =========================================================
# AGENT PROMPT
# =========================================================

prompt = """
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

# =========================================================
# AGENT
# =========================================================

root_agent = LlmAgent(
    name="HighlightsComposerAgent",
    model="gemini-2.5-flash",
    instruction=prompt,
    tools=tools,
)


async def main():

    runner = InMemoryRunner(agent=root_agent)

    # query = """
    # Create highlights for my persona
    # """
    query = """
    create a highlight of Free kick awarded to Tottenham
    """

    events = await runner.run_debug(query)

    for e in events:
        if hasattr(e, "text") and e.text:
            print(e.text)



if __name__ == "__main__":
    asyncio.run(main())