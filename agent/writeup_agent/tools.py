"""Python tools exposed to writeup_agent."""

from __future__ import annotations

from typing import Any, Dict, List

from google.adk.tools.tool_context import ToolContext

from opensage.toolbox.sandbox_requirements import requires_sandbox

from .store import (
    INSIGHT_PATH,
    WRITEUP_ROOT,
    WriteupStoreError,
    ensure_store,
    format_writeup,
    list_unit_names,
    parse_unit_frontmatter,
    read_index,
    read_insight_file,
    read_unit,
    rebuild_index,
    upsert_insight_entry,
    write_unit,
)


def _format_event_to_text(event) -> str:
    compaction = getattr(getattr(event, "actions", None), "compaction", None)
    if compaction:
        compacted_content = getattr(compaction, "compacted_content", None)
        if compacted_content and getattr(compacted_content, "parts", None):
            summary_parts = [
                part.text
                for part in compacted_content.parts
                if getattr(part, "text", None)
            ]
            if summary_parts:
                author = getattr(event, "author", "model")
                return f"[{author}][Summary]: {' | '.join(summary_parts)}"

    parts_text = []
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) if content else None
    for part in parts or []:
        text = getattr(part, "text", None)
        function_call = getattr(part, "function_call", None)
        function_response = getattr(part, "function_response", None)
        if text:
            parts_text.append(text)
        elif function_call:
            parts_text.append(f"[TOOL_CALL] {function_call.name}({function_call.args})")
        elif function_response:
            parts_text.append(
                f"[TOOL_RESULT] {function_response.name}: {function_response.response}"
            )

    if parts_text:
        return f"[{getattr(event, 'author', 'unknown')}]: {' | '.join(parts_text)}"
    return ""


async def summarize_current_trajectory(
    max_events: int = 80,
    max_chars: int = 20000,
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Return formatted events from this session.

    For writeup_agent, this includes the caller trajectory only when the main
    agent invoked call_subagent(..., use_parent_history=True).
    """
    invocation_context = tool_context._invocation_context
    current_branch = getattr(invocation_context, "branch", None)
    events = invocation_context.session.events or []

    def _is_branch_match(event) -> bool:
        if not current_branch:
            return True
        event_branch = getattr(event, "branch", None)
        return event_branch is None or event_branch == current_branch

    branch_events = [event for event in events if _is_branch_match(event)]
    processed_events = branch_events
    if branch_events:
        try:
            from google.adk.flows.llm_flows import contents as adk_contents

            processed = adk_contents._process_compaction_events(branch_events)
            if processed:
                processed_events = processed
        except Exception:
            processed_events = branch_events

    selected_events = processed_events[-max_events:]
    lines = []
    for event in selected_events:
        formatted = _format_event_to_text(event)
        if formatted:
            lines.append(formatted)

    text = "\n".join(lines)
    truncated = len(text) > max_chars
    if truncated:
        text = text[-max_chars:]

    return {
        "success": True,
        "event_count": len(events),
        "processed_event_count": len(processed_events),
        "returned_event_count": len(selected_events),
        "truncated": truncated,
        "trajectory": text or "No trajectory events available.",
    }


@requires_sandbox("main")
async def list_writeups(*, tool_context: ToolContext) -> Dict[str, Any]:
    """List stored challenge writeups and return INDEX.md plus parsed metadata."""
    await ensure_store(tool_context)
    challenge_names = await list_unit_names(tool_context)
    entries: List[Dict[str, Any]] = []

    from opensage.memory.file_based.short_term.sandbox_io import _get_main_sandbox

    sandbox = _get_main_sandbox(tool_context)
    for challenge_name in sorted(challenge_names):
        try:
            body = await sandbox.aextract_file_from_container(
                f"{WRITEUP_ROOT}/{challenge_name}.md"
            )
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        meta = parse_unit_frontmatter(body)
        if meta is not None:
            entries.append(meta)
    index_text = await read_index(tool_context)
    return {"success": True, "index": index_text, "entries": entries}


@requires_sandbox("main")
async def read_writeup(
    challenge_name: str, *, tool_context: ToolContext
) -> Dict[str, Any]:
    """Return /mem/shared/writeup/<challenge_name>.md."""
    await ensure_store(tool_context)
    try:
        content = await read_unit(tool_context, challenge_name)
    except WriteupStoreError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "challenge_name": challenge_name, "content": content}


@requires_sandbox("main")
async def read_insights(*, tool_context: ToolContext) -> Dict[str, Any]:
    """Return the fixed /mem/shared/writeup/INSIGHT.md file."""
    await ensure_store(tool_context)
    content = await read_insight_file(tool_context)
    return {"success": True, "path": INSIGHT_PATH, "content": content}


@requires_sandbox("main")
async def upsert_challenge_writeup(
    challenge_name: str,
    writeup: str,
    keywords: List[str],
    hook: str,
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Create or overwrite one challenge writeup and refresh INDEX.md.

    Args:
        challenge_name: Stable lowercase identifier used as the filename.
        writeup: Distilled challenge solution or improved user-provided writeup.
        keywords: 3-7 retrieval tags such as ["pwn", "ret2libc"].
        hook: Single-line, <=120 char index summary.
    """
    await ensure_store(tool_context)
    if not keywords:
        return {
            "success": False,
            "error": "keywords must be non-empty (3-7 tags recommended)",
        }
    if len(hook) > 120:
        return {
            "success": False,
            "error": f"hook is {len(hook)} chars; keep it <=120",
        }
    content = format_writeup(challenge_name, writeup, keywords, hook)
    try:
        await write_unit(tool_context, challenge_name, content)
        new_index = await rebuild_index(tool_context)
    except WriteupStoreError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "challenge_name": challenge_name,
        "path": f"{WRITEUP_ROOT}/{challenge_name}.md",
        "index": new_index,
    }


@requires_sandbox("main")
async def upsert_stuck_insight(
    challenge_name: str,
    stuck_point: str,
    trajectory_gap: str,
    writeup_correction: str,
    keywords: List[str],
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Create or replace one challenge insight section in INSIGHT.md.

    Use this only when comparing a stuck trajectory against a user-provided
    writeup. The fixed INSIGHT.md file is the retrieval target for future stuck
    runs.
    """
    await ensure_store(tool_context)
    if not keywords:
        return {
            "success": False,
            "error": "keywords must be non-empty (3-7 tags recommended)",
        }
    try:
        content = await upsert_insight_entry(
            tool_context,
            challenge_name,
            stuck_point,
            trajectory_gap,
            writeup_correction,
            keywords,
        )
    except WriteupStoreError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "challenge_name": challenge_name,
        "path": INSIGHT_PATH,
        "content": content,
    }
