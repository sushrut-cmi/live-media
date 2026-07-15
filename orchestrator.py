import asyncio
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner

from google.adk.tools.agent_tool import AgentTool


from highlight_agent import root_agent as highlight_agent
from localization_agent import root_agent as localization_agent


tools = [
    AgentTool(agent=highlight_agent),
    AgentTool(agent=localization_agent),
]


orchestrator_prompt = """
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


orchestrator_agent = LlmAgent(
    name="OrchestratorAgent",
    model="gemini-2.5-flash",
    instruction=orchestrator_prompt,
    tools=tools
)


async def main():
    runner = InMemoryRunner(agent=orchestrator_agent)

    query = """
    creeate a highlight of Free kick awarded to Tottenham
    """

    events = await runner.run_debug(query)

    for e in events:
        if hasattr(e, "text") and e.text:
            print(e.text)


if __name__ == "__main__":
    asyncio.run(main())
