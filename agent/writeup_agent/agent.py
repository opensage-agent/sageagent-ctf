import os
import logging

from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

from opensage.agents.opensage_agent import OpenSageAgent
from opensage.toolbox.general.bash_tools_interface import run_terminal_command
from opensage.toolbox.general.history_management import (
    get_all_events_for_summarization,
    get_all_invocations_for_agent,
)

from .prompt import WRITEUP_AGENT_INSTRUCTION
from .tools import list_writeups, read_writeup, upsert_writeup

logger = logging.getLogger(__name__)


def create_writeup_agent(opensage_session_id: str) -> OpenSageAgent:
    """Create the writeup_agent.

    Two modes (selected via the caller's message, not a function arg):
    - recap: distill a writeup + failure root cause into persistent memory.
    - consult: retrieve relevant prior writeups given current trajectory.
    """
    logger.info("Creating Writeup Agent within session %s", opensage_session_id)

    model = LiteLlm(
        model="claude-opus-4-6",
        api_key=os.getenv("LITELLM_API_KEY"),
        base_url=os.getenv("LITELLM_BASE_URL") or "http://localhost:8082",
        cache_control_injection_points=[
            {"location": "message", "role": "system"},  # Cache all system messages
            {"location": "message", "index": -2},  # Cache second-to-last message
            {"location": "message", "index": -1},  # Cache last message
        ],
    )

    tools = [
        list_writeups,
        read_writeup,
        upsert_writeup,
        get_all_invocations_for_agent,
        get_all_events_for_summarization,
        run_terminal_command,
    ]

    return OpenSageAgent(
        name=f"writeup_agent",
        model=model,
        description=(
            "Writeup agent: (recap) distills a writeup + failure root cause "
            "into long-term memory; (consult) retrieves relevant prior "
            "writeups given the current trajectory. Operates on "
            "/mem/shared/writeups/ with a WRITEUP.md index."
        ),
        instruction=WRITEUP_AGENT_INSTRUCTION,
        tools=tools,
    )


def create_writeup_agent_tool(opensage_session_id: str) -> AgentTool:
    """Wrap the writeup_agent as an AgentTool for callers like ctf_agent."""
    return AgentTool(agent=create_writeup_agent(opensage_session_id))
