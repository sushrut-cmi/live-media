"""
Strands port of orchestrator.py (ADK `OrchestratorAgent`).

ADK original:
    tools = [AgentTool(agent=highlight_agent), AgentTool(agent=localization_agent)]
    orchestrator_agent = LlmAgent(
        name="OrchestratorAgent",
        model="gemini-2.5-flash",
        instruction=orchestrator_prompt,
        tools=tools,
    )

Strands has no direct `AgentTool` primitive, so we use the idiomatic
"agents-as-tools" pattern: each specialist agent is wrapped in a `@tool`
function that the orchestrator can call. This is functionally identical to
ADK's AgentTool — the orchestrator LLM decides which specialist to invoke and
passes it a natural-language request.
"""

from __future__ import annotations

from strands import Agent, tool

# Works both as a package import (`from strands_app.orchestrator import ...`)
# and when run directly from inside strands_app/ (`python orchestrator.py`).
try:
    from .config import build_model
    from .highlight_agent import run_highlights
    from .localization_agent import run_localization
except ImportError:
    from config import build_model
    from highlight_agent import run_highlights
    from localization_agent import run_localization


# --------------------------------------------------------------------------- #
# Specialist agents exposed as tools (== ADK AgentTool)
# --------------------------------------------------------------------------- #
@tool
def highlights_agent(request: str) -> str:
    """Select the best video segment(s) for a persona/intent and compose a
    highlight/summary clip.

    Use for requests about: highlights, summaries, "best parts", short videos,
    "what happened in the last N minutes", persona-based highlights.

    Args:
        request: A natural-language description of the highlight to create,
            e.g. "create a highlight of the free kick awarded to Tottenham".

    Returns:
        JSON string with the selected indices and the composed playlist path.
    """
    return run_highlights(request)


@tool
def localization_agent(request: str) -> str:
    """Localize a video: transcribe, translate, generate TTS, and merge the new
    audio back onto the video.

    Use for requests about: localize, translate video, dub, voice-over.

    Args:
        request: A natural-language request that includes video_path,
            source_language, target_language, voice, and output_video_path.

    Returns:
        JSON string with the output video path.
    """
    return run_localization(request)


# --------------------------------------------------------------------------- #
# Orchestrator prompt  (verbatim from the ADK agent)
# --------------------------------------------------------------------------- #
ORCHESTRATOR_PROMPT = """
You are a video processing orchestrator agent.

You manage two specialist agents:

1. HighlightsAgent
- selects best video segments based on persona/intent
- outputs: selected highlight video path

2. LocalizationAgent
- transcribes, translates, generates TTS, merges video
- outputs localized video

-------------------------
ROUTING RULES:

If user request contains:
- "highlight", "summary", "best parts", "short video"
→ use HighlightsAgent

If user request contains:
- "localize", "translate video", "dub", "voice over"
→ use LocalizationAgent

If request contains BOTH:
→ FIRST call HighlightsComposerAgent
→ THEN pass result to LocalizationAgent


-------------------------
FINAL OUTPUT FORMAT:
Return only JSON:

{
  "task_flow": ["highlights", "localization"],
  "final_output_path": "...",
  "status": "success"
}
"""


def build_orchestrator() -> Agent:
    """Build the orchestrator agent with the two specialists as tools."""
    return Agent(
        name="OrchestratorAgent",
        model=build_model(),
        system_prompt=ORCHESTRATOR_PROMPT,
        tools=[highlights_agent, localization_agent],
    )


def run_orchestrator(query: str) -> str:
    """Run the orchestrator for a single query and return its final text.

    This is the Strands replacement for `run_highlights_orchestrator` in
    new_backend.py. To wire it into the FastAPI backend:

        from strands_app.orchestrator import run_orchestrator
        raw_text = run_orchestrator(prompt)     # note: synchronous
    """
    agent = build_orchestrator()
    result = agent(query)
    return str(result)


if __name__ == "__main__":
    query = "create a highlight of Free kick awarded to Tottenham"
    print(run_orchestrator(query))
