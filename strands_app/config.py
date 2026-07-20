"""
Shared configuration for the Strands version of the live-media agentic flow.

This is the Strands equivalent of the model + toolset wiring that was
previously done inline inside each Google ADK agent file.

Model provider
--------------
The original ADK agents used `model="gemini-2.5-flash"`. In Strands we build an
explicit model object. This project now targets **AWS Bedrock Amazon Nova**,
which is Strands' native/default provider.

1. BedrockModel  -> Amazon Nova (default). Uses the standard AWS credential
   chain (env vars, shared profile, or an IAM role). Nova supports tool use and
   streaming, both required by these agents.

2. LiteLLMModel  -> Gemini Developer API (needs GEMINI_API_KEY). Kept as a
   commented fallback.
3. GeminiModel   -> native google-genai / Vertex AI. Kept as a commented
   fallback.

MCP servers
-----------
The FastMCP servers (highlights_mcp_server.py, localization_mcp_server.py) are
UNCHANGED. Strands consumes them exactly like ADK's McpToolset did, just through
the strands.tools.mcp.MCPClient wrapper.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from mcp import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from strands.tools.mcp import MCPClient

load_dotenv()

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# strands_app/ lives next to the original scripts, so the repo root is parent.
REPO_ROOT = Path(__file__).resolve().parent.parent

# highlights_mcp_server.py sits at the repo root in this project.
HIGHLIGHTS_MCP_SERVER = REPO_ROOT / "highlights_mcp_server.py"

# The localization MCP server runs as an SSE server (FastMCP `transport="sse"`).
# Start it separately:  python localization_mcp_server.py
LOCALIZATION_MCP_URL = os.getenv("LOCALIZATION_MCP_URL", "http://localhost:8000/sse")

# AWS Bedrock Amazon Nova.
#   Nova Pro   -> us.amazon.nova-pro-v1:0    (most capable, best for orchestration)
#   Nova Lite  -> us.amazon.nova-lite-v1:0   (cheaper/faster, multimodal)
#   Nova Micro -> us.amazon.nova-micro-v1:0  (text-only, cheapest)
# The "us." prefix is the cross-region inference profile required for on-demand
# throughput in US regions (use "eu." / "apac." in those regions).
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
def build_model():
    """Build the shared model used by every agent.

    Default: AWS Bedrock Amazon Nova (Strands' native provider).
    Credentials come from the standard AWS chain: AWS_ACCESS_KEY_ID /
    AWS_SECRET_ACCESS_KEY (+ AWS_SESSION_TOKEN), an AWS_PROFILE, or an attached
    IAM role. Ensure the account has bedrock:InvokeModel[WithResponseStream]
    access to the Nova model in AWS_REGION.
    """
    # ---- Option 1: AWS Bedrock -> Amazon Nova (default) -------------------- #
    from strands.models import BedrockModel

    return BedrockModel(
        model_id=BEDROCK_MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.2,
        # streaming=True by default; Nova supports it. Set streaming=False only
        # if your account/region requires the non-streaming Converse API.
    )

    # ---- Option 2: LiteLLM -> Gemini Developer API ------------------------- #
    # from strands.models.litellm import LiteLLMModel
    # return LiteLLMModel(
    #     model_id="gemini/gemini-2.5-flash",   # reads GEMINI_API_KEY from env
    #     params={"temperature": 0.2},
    # )

    # ---- Option 3: native Gemini / Vertex AI ------------------------------- #
    # from strands.models.gemini import GeminiModel
    # return GeminiModel(
    #     client_args={"api_key": os.getenv("GEMINI_API_KEY")},
    #     model_id="gemini-2.5-flash",
    #     params={"temperature": 0.2},
    # )


# --------------------------------------------------------------------------- #
# MCP clients
# --------------------------------------------------------------------------- #
def make_highlights_mcp_client() -> MCPClient:
    """Strands equivalent of the ADK stdio McpToolset for highlights.

    ADK:
        McpToolset(connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(command="python3", args=[...])))
    """
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command=sys.executable,  # more portable than hardcoded "python3"
                args=[str(HIGHLIGHTS_MCP_SERVER)],
            )
        )
    )


def make_localization_mcp_client() -> MCPClient:
    """Strands equivalent of the ADK SSE McpToolset for localization.

    ADK:
        McpToolset(connection_params=SseConnectionParams(
            url="http://localhost:8000/sse"))
    """
    return MCPClient(lambda: sse_client(LOCALIZATION_MCP_URL))
