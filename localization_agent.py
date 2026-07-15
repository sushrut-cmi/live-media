import asyncio
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams,SseConnectionParams
from mcp import StdioServerParameters
from google.adk.runners import InMemoryRunner
from dotenv import load_dotenv
load_dotenv()
# tools = McpToolset(
#     command=["python", "localization_mcp_server.py"],
# )
# tools=[
#         McpToolset(
#             connection_params=StdioConnectionParams(
#                 server_params = StdioServerParameters(
#                     command='python3', # Command to run your MCP server script
#                     args=["localization_mcp_server.py"], # Argument is the path to the script
#                     timeout=600
#                 )
#             )
#             # tool_filter=['load_web_page'] # Optional: ensure only specific tools are loaded
#         )
#     ]
tools = McpToolset(
    connection_params=SseConnectionParams(
        url="http://localhost:8000/sse"
    )
)
root_agent = Agent(
    name="LocalizationAgent",
    model="gemini-2.5-flash",
    instruction="""
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
""",
    tools=[tools],
)

async def main():
    runner = InMemoryRunner(agent=root_agent)

    query = """
    video_path: /home/tummala_venkata/ai_for_live/backend/data/videos/segment_003.mp4
    source_language: English
    target_language: Spanish
    voice: Sushrut
    output_video_path: /home/tummala_venkata/ai_for_live/backend/data/videos/segment_003_spanish.mp4
    """
    print(f"--- Processing Query: {query} ---\n")
    print("Running agent")
    try:
        # run_debug returns a list of events
        events = await runner.run_debug(query)
        
        for event in events:
            # Check if the event contains the final response text
            if hasattr(event, 'text') and event.text:
                print(f"Assistant: {event.text}")
            
            # Optional: Debug tool calls if the model supports it
            if hasattr(event, 'tool_calls') and event.tool_calls:
                print(f"[Tool Call]: {event.tool_calls}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
