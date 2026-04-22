"""Python tools exposed to writeup_agent."""

from __future__ import annotations

from typing import Any, Dict, List

from google.adk.tools.tool_context import ToolContext

from opensage.toolbox.sandbox_requirements import requires_sandbox

from .store import (
    WRITEUP_ROOT,
    WriteupStoreError,
    ensure_store,
    format_unit,
    list_unit_slugs,
    parse_unit_frontmatter,
    read_index,
    read_unit,
    rebuild_index,
    write_unit,
)


@requires_sandbox("main")
async def list_writeups(*, tool_context: ToolContext) -> Dict[str, Any]:
    """List all stored writeups.

    Returns the full WRITEUP.md index text plus a parsed list of
    {slug, keywords, hook} entries derived from each unit file's frontmatter.
    Use this first in `consult` mode to decide which writeups to read.
    """
    await ensure_store(tool_context)
    sandbox_slugs = await list_unit_slugs(tool_context)
    entries: List[Dict[str, Any]] = []
    # Pull frontmatter straight from unit files (authoritative) rather than
    # parsing the index — it cannot drift.
    from opensage.memory.file_based.short_term.sandbox_io import _get_main_sandbox

    sandbox = _get_main_sandbox(tool_context)
    for slug in sorted(sandbox_slugs):
        try:
            body = await sandbox.aextract_file_from_container(
                f"{WRITEUP_ROOT}/{slug}.md"
            )
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        meta = parse_unit_frontmatter(body)
        if meta is not None:
            entries.append(meta)
    index_text = await read_index(tool_context)
    return {"success": True, "index": index_text, "entries": entries}


@requires_sandbox("main")
async def read_writeup(slug: str, *, tool_context: ToolContext) -> Dict[str, Any]:
    """Return the full markdown body of /mem/shared/writeups/<slug>.md.

    Use after `list_writeups` identifies a relevant slug.
    """
    await ensure_store(tool_context)
    try:
        content = await read_unit(tool_context, slug)
    except WriteupStoreError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "slug": slug, "content": content}


@requires_sandbox("main")
async def upsert_writeup(
    slug: str,
    writeup: str,
    failure_root_cause: str,
    keywords: List[str],
    hook: str,
    *,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Create or overwrite a writeup unit and refresh WRITEUP.md.

    Args:
        slug: Stable identifier (lowercase, digits, '-', '_', '.'). Same slug
            on a later call overwrites the unit — use this to evolve writeups.
        writeup: Distilled solution narrative (the "how it was solved" part).
        failure_root_cause: What went wrong or cost time; what would have
            shortcut the solve. One paragraph.
        keywords: 3-7 tags a future `consult` query can grep for
            (e.g., ["pwn", "ret2libc", "canary-bypass"]).
        hook: Single-line, <=120 char summary used in the index line.

    Idempotent: writing the same slug replaces the unit and updates its line
    in WRITEUP.md.
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
    content = format_unit(slug, writeup, failure_root_cause, keywords, hook)
    try:
        await write_unit(tool_context, slug, content)
        new_index = await rebuild_index(tool_context)
    except WriteupStoreError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "slug": slug,
        "path": f"{WRITEUP_ROOT}/{slug}.md",
        "index": new_index,
    }
