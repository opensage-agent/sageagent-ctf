import os
import logging

from google.adk.models.base_llm import BaseLlm
from opensage.agents.opensage_agent import OpenSageAgent
from opensage.toolbox.general.bash_tools_interface import run_terminal_command

from .prompt import WRITEUP_AGENT_INSTRUCTION
from .tools import (
    list_writeups,
    read_insights,
    read_writeup,
    summarize_current_trajectory,
    upsert_challenge_writeup,
    upsert_stuck_insight,
)

logger = logging.getLogger(__name__)


def create_writeup_agent(opensage_session_id: str, model: BaseLlm) -> OpenSageAgent:
    """Create the writeup_agent.

    Modes are selected via the caller's message:
    - cap, solved: extract a writeup from a successful trajectory.
    - cap, stuck with user writeup: extract an insight and improve the writeup.
    - consult: retrieve relevant writeups and insights.
    """
    logger.info("Creating Writeup Agent within session %s", opensage_session_id)

    tools = [
        list_writeups,
        read_writeup,
        read_insights,
        upsert_challenge_writeup,
        upsert_stuck_insight,
        summarize_current_trajectory,
        run_terminal_command,
    ]

    return OpenSageAgent(
        name=f"writeup_agent",
        model=model,
        description=(
            "Writeup agent: cap mode stores solved writeups or stuck-point "
            "insights; consult mode retrieves prior writeups and insights. "
            "Operates on /mem/shared/writeup/ with INDEX.md and INSIGHT.md."
        ),
        instruction=WRITEUP_AGENT_INSTRUCTION,
        tools=tools,
    )
