"""File-based writeup store backed by /mem/shared/writeups in the main sandbox.

Layout on disk (inside the main sandbox, host-mounted when
`sandbox.host_shared_mem_dir` is set — which it typically is, since that mount
is how /mem/shared is provisioned for every sandbox):

    /mem/shared/writeups/
        WRITEUP.md              # flat markdown index
        <slug>.md              # one file per writeup unit, YAML frontmatter + body
"""

from __future__ import annotations

import logging
import re
import shlex
from typing import List, Optional

from opensage.memory.file_based.short_term.sandbox_io import (
    _get_main_sandbox,
    _write_text_to_main_sandbox,
)

logger = logging.getLogger(__name__)

WRITEUP_ROOT = "/mem/shared/writeups"
WRITEUP_INDEX_PATH = f"{WRITEUP_ROOT}/WRITEUP.md"
INDEX_HEADER = "# WRITEUP.md\n\nIndex of CTF writeups. Each line: `- [slug](slug.md) — keywords: k1, k2 — hook`.\n\n"

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class WriteupStoreError(Exception):
    pass


def _validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise WriteupStoreError(
            f"Invalid slug '{slug}': use lowercase letters, digits, '-', '_', '.'"
        )


def _unit_path(slug: str) -> str:
    return f"{WRITEUP_ROOT}/{slug}.md"


async def ensure_store(invocation_context) -> None:
    """Create writeup root dir and an empty WRITEUP.md if missing."""
    sandbox = _get_main_sandbox(invocation_context)
    await sandbox.arun_command_in_container(f"mkdir -p {shlex.quote(WRITEUP_ROOT)}")
    _, exit_code = await sandbox.arun_command_in_container(
        f"test -f {shlex.quote(WRITEUP_INDEX_PATH)}"
    )
    if exit_code != 0:
        await _write_text_to_main_sandbox(
            invocation_context, WRITEUP_INDEX_PATH, INDEX_HEADER
        )


async def read_index(invocation_context) -> str:
    sandbox = _get_main_sandbox(invocation_context)
    return await sandbox.aextract_file_from_container(WRITEUP_INDEX_PATH)


async def read_unit(invocation_context, slug: str) -> str:
    _validate_slug(slug)
    sandbox = _get_main_sandbox(invocation_context)
    _, exit_code = await sandbox.arun_command_in_container(
        f"test -f {shlex.quote(_unit_path(slug))}"
    )
    if exit_code != 0:
        raise WriteupStoreError(f"Writeup '{slug}' not found")
    return await sandbox.aextract_file_from_container(_unit_path(slug))


async def list_unit_slugs(invocation_context) -> List[str]:
    sandbox = _get_main_sandbox(invocation_context)
    out, exit_code = await sandbox.arun_command_in_container(
        f"ls -1 {shlex.quote(WRITEUP_ROOT)}"
    )
    if exit_code != 0:
        return []
    return [
        line[:-3]
        for line in out.splitlines()
        if line.endswith(".md") and line != "WRITEUP.md"
    ]


def format_unit(
    slug: str,
    writeup: str,
    failure_root_cause: str,
    keywords: List[str],
    hook: str,
) -> str:
    keywords_yaml = "[" + ", ".join(keywords) + "]"
    return (
        "---\n"
        f"name: {slug}\n"
        f"keywords: {keywords_yaml}\n"
        f"hook: {hook}\n"
        "---\n"
        "## Writeup\n"
        f"{writeup.strip()}\n\n"
        "## Failure root cause\n"
        f"{failure_root_cause.strip()}\n"
    )


def parse_unit_frontmatter(content: str) -> Optional[dict]:
    """Extract {slug, keywords, hook} from a unit file's frontmatter. Returns None on malformed input."""
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---\n", 4)
    if end == -1:
        return None
    front = content[4:end]
    name = None
    keywords: List[str] = []
    hook = ""
    for line in front.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("keywords:"):
            raw = line.split(":", 1)[1].strip()
            if raw.startswith("[") and raw.endswith("]"):
                keywords = [k.strip() for k in raw[1:-1].split(",") if k.strip()]
        elif line.startswith("hook:"):
            hook = line.split(":", 1)[1].strip()
    if not name:
        return None
    return {"slug": name, "keywords": keywords, "hook": hook}


def format_index_line(slug: str, keywords: List[str], hook: str) -> str:
    kw = ", ".join(keywords) if keywords else ""
    return f"- [{slug}]({slug}.md) — keywords: {kw} — {hook}"


async def write_unit(invocation_context, slug: str, content: str) -> None:
    """Atomic write: write to <slug>.md.tmp, then mv into place."""
    _validate_slug(slug)
    sandbox = _get_main_sandbox(invocation_context)
    tmp_path = f"{_unit_path(slug)}.tmp"
    await _write_text_to_main_sandbox(invocation_context, tmp_path, content)
    _, exit_code = await sandbox.arun_command_in_container(
        f"mv {shlex.quote(tmp_path)} {shlex.quote(_unit_path(slug))}"
    )
    if exit_code != 0:
        raise WriteupStoreError(f"Failed to finalize writeup '{slug}'")


async def rebuild_index(invocation_context) -> str:
    """Regenerate WRITEUP.md from unit frontmatter. Returns the new index text."""
    sandbox = _get_main_sandbox(invocation_context)
    slugs = await list_unit_slugs(invocation_context)
    entries: List[str] = []
    for slug in sorted(slugs):
        try:
            body = await sandbox.aextract_file_from_container(_unit_path(slug))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Skipping writeup %s: %s", slug, exc)
            continue
        meta = parse_unit_frontmatter(body)
        if meta is None:
            logger.warning("Skipping writeup %s: malformed frontmatter", slug)
            continue
        entries.append(format_index_line(meta["slug"], meta["keywords"], meta["hook"]))
    new_index = INDEX_HEADER + "\n".join(entries) + ("\n" if entries else "")
    await _write_text_to_main_sandbox(invocation_context, WRITEUP_INDEX_PATH, new_index)
    return new_index
