import importlib
import logging
import os
from typing import Optional

import google.adk as adk
from dotenv import load_dotenv
from google.adk.agents.llm_agent import ToolUnion
from google.adk.models.lite_llm import LiteLlm

from opensage.agents.opensage_agent import OpenSageAgent
from opensage.session import get_opensage_session
from opensage.toolbox.benchmark_specific.cybergym.cybergym import (
    critique,
    generate_poc_and_submit,
    run_poc_from_script,
)
from opensage.toolbox.binary.ghidra_mcp.get_toolset import (
    get_toolset as get_ghidra_toolset,
)
from opensage.toolbox.binary.ida_pro_mcp.get_toolset import (
    get_toolset as get_ida_pro_toolset,
)
from opensage.toolbox.binary.pyghidra_mcp.get_toolset import (
    get_toolset as get_pyghidra_toolset,
)
from opensage.toolbox.debugger.gdb_mcp.get_toolset import get_toolset as get_gdb_toolset
from opensage.toolbox.finish_task.finish_task import finish_task
from opensage.toolbox.general.agent_tools import (
    complain,
    note_suspicious_things,
    think,
)
from opensage.toolbox.general.bash_tool import bash_tool_main
from opensage.toolbox.general.bash_tools_interface import (
    get_background_task_output,
    list_background_tasks,
    run_terminal_command,
)
from opensage.toolbox.general.orchestration_tools import (
    call_subagent,
    create_subagent,
    get_available_models,
    list_subagents,
)
from opensage.toolbox.general.view_image import view_image

from .writeup_agent import create_writeup_agent


def create_main_model(opensage_session_id: str) -> LiteLlm:
    """Create the model declared by [llm.model_configs.main] in config.toml."""
    opensage_session = get_opensage_session(opensage_session_id)
    model_config = opensage_session.config.llm.get_model_config("main")
    model_name = (
        model_config.model_name
        if model_config is not None
        else "anthropic/claude-opus-4-6"  # default model if not specified in config.toml
    )
    return LiteLlm(
        model=model_name,
        api_key=os.getenv("LITELLM_API_KEY"),
        base_url=os.getenv("LITELLM_BASE_URL"),
        cache_control_injection_points=[
            {"location": "message", "role": "system"},
            {"location": "message", "index": -2},
            {"location": "message", "index": -1},
        ],
    )


def mk_agent(opensage_session_id: str):
    model = create_main_model(opensage_session_id)
    gdb_toolset = get_gdb_toolset(opensage_session_id)
    ida_pro_toolset = get_ida_pro_toolset(opensage_session_id)
    pyghidra_toolset = get_pyghidra_toolset(opensage_session_id)
    ghidra_toolset = get_ghidra_toolset(opensage_session_id)

    root_agent = OpenSageAgent(
        name="ctf_agent",
        model=model,
        description="CTF agent",
        instruction=f"""
        You are a CTF agent that solves CTF challenges.
        For reverse engineering workflows, use `create_subagent` and inject the
        MCP toolsets you need by name from this agent's available Python toolsets
        (for example `ida_pro_mcp`, `pyghidra_mcp`, `ghidra_mcp`, `gdb_mcp`).
        Perform MCP actions inside those subagents rather than directly from the
        root agent.

        Writeup memory: you have a `writeup_agent` subagent backed by a
        cross-session store at /mem/shared/writeup/ (indexed by INDEX.md, with
        stuck lessons in INSIGHT.md). Use `call_subagent` with
        agent_name="writeup_agent"; set use_parent_history=True whenever the
        writeup_agent needs your trajectory.
        - When you start a new challenge, call it in `consult, challenge start`
          mode with the challenge description and observed files/protections.
        - When you get stuck, call it in `consult, stuck` mode with your current
          blocker and trajectory summary.
        - After solving a challenge, call it in `cap, solved` mode with the
          challenge name and a pointer to your trajectory so it can extract
          /mem/shared/writeup/<challenge_name>.md and update INDEX.md.
        - If you were stuck and the user gives a writeup, call it in
          `cap, stuck with user writeup` mode with your trajectory plus the
          user writeup. It will update the challenge writeup and the fixed
          INSIGHT.md stuck-point file.
        """,
        tools=[
            get_available_models,
            create_subagent,
            view_image,
            list_subagents,
            call_subagent,
            critique,
            # think,
            complain,
            # Super Terminal Tools
            list_background_tasks,
            get_background_task_output,
            run_terminal_command,
            # Debugger Tools
            gdb_toolset,
            # Binary Analysis Tools
            ida_pro_toolset,
            pyghidra_toolset,
            ghidra_toolset,
        ],
        subagents=[
            create_writeup_agent(opensage_session_id, model=model),
        ],
        enabled_skills=[],
    )

    return root_agent
