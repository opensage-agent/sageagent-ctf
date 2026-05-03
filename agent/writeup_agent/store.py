"""File-based writeup store backed by /mem/shared/writeup in the main sandbox.

Layout on disk, inside the long-term memory mount:

    /mem/shared/writeup/
        INDEX.md                # index of per-challenge writeups
        INSIGHT.md              # fixed stuck-point insight file
        <challenge_name>.md     # one summarized writeup per challenge
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

WRITEUP_ROOT = "/mem/shared/writeup"
WRITEUP_INDEX_PATH = f"{WRITEUP_ROOT}/INDEX.md"
INSIGHT_PATH = f"{WRITEUP_ROOT}/INSIGHT.md"

INDEX_HEADER = (
    "# INDEX.md\n\n"
    "Index of CTF writeups. Each line: "
    "`- [challenge](challenge.md) - keywords: k1, k2 - hook`.\n\n"
)
INSIGHT_HEADER = (
    "# INSIGHT.md\n\n"
    "Persistent stuck-point insights extracted by comparing failed trajectories "
    "with known-good writeups.\n\n"
)

CHALLENGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
RESERVED_NAMES = {"index", "insight"}


class WriteupStoreError(Exception):
    pass


def _validate_challenge_name(challenge_name: str) -> None:
    if challenge_name in RESERVED_NAMES or not CHALLENGE_NAME_RE.match(challenge_name):
        raise WriteupStoreError(
            f"Invalid challenge_name '{challenge_name}': use lowercase letters, "
            "digits, '-', '_', or '.', and avoid INDEX/INSIGHT"
        )


def _unit_path(challenge_name: str) -> str:
    return f"{WRITEUP_ROOT}/{challenge_name}.md"


async def ensure_store(invocation_context) -> None:
    """Create writeup root, INDEX.md, and INSIGHT.md if missing."""
    sandbox = _get_main_sandbox(invocation_context)
    await sandbox.arun_command_in_container(f"mkdir -p {shlex.quote(WRITEUP_ROOT)}")
    for path, header in (
        (WRITEUP_INDEX_PATH, INDEX_HEADER),
        (INSIGHT_PATH, INSIGHT_HEADER),
    ):
        _, exit_code = await sandbox.arun_command_in_container(
            f"test -f {shlex.quote(path)}"
        )
        if exit_code != 0:
            await _write_text_to_main_sandbox(invocation_context, path, header)


async def read_index(invocation_context) -> str:
    sandbox = _get_main_sandbox(invocation_context)
    return await sandbox.aextract_file_from_container(WRITEUP_INDEX_PATH)


async def read_insight_file(invocation_context) -> str:
    sandbox = _get_main_sandbox(invocation_context)
    return await sandbox.aextract_file_from_container(INSIGHT_PATH)


async def read_unit(invocation_context, challenge_name: str) -> str:
    _validate_challenge_name(challenge_name)
    sandbox = _get_main_sandbox(invocation_context)
    _, exit_code = await sandbox.arun_command_in_container(
        f"test -f {shlex.quote(_unit_path(challenge_name))}"
    )
    if exit_code != 0:
        raise WriteupStoreError(f"Writeup '{challenge_name}' not found")
    return await sandbox.aextract_file_from_container(_unit_path(challenge_name))


async def list_unit_names(invocation_context) -> List[str]:
    sandbox = _get_main_sandbox(invocation_context)
    out, exit_code = await sandbox.arun_command_in_container(
        f"ls -1 {shlex.quote(WRITEUP_ROOT)}"
    )
    if exit_code != 0:
        return []
    names = []
    for line in out.splitlines():
        if not line.endswith(".md") or line in {"INDEX.md", "INSIGHT.md"}:
            continue
        name = line[:-3]
        try:
            _validate_challenge_name(name)
        except WriteupStoreError:
            logger.warning("Skipping invalid writeup filename %s", line)
            continue
        names.append(name)
    return names


def format_writeup(
    challenge_name: str,
    writeup: str,
    keywords: List[str],
    hook: str,
) -> str:
    keywords_yaml = "[" + ", ".join(keywords) + "]"
    return (
        "---\n"
        f"name: {challenge_name}\n"
        f"keywords: {keywords_yaml}\n"
        f"hook: {hook}\n"
        "---\n"
        "## Writeup\n"
        f"{writeup.strip()}\n"
    )


def parse_unit_frontmatter(content: str) -> Optional[dict]:
    """Extract index metadata from a writeup file's frontmatter."""
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
    return {"name": name, "keywords": keywords, "hook": hook}


def format_index_line(challenge_name: str, keywords: List[str], hook: str) -> str:
    kw = ", ".join(keywords) if keywords else ""
    return f"- [{challenge_name}]({challenge_name}.md) - keywords: {kw} - {hook}"


async def write_unit(invocation_context, challenge_name: str, content: str) -> None:
    """Atomic write: write to <challenge_name>.md.tmp, then mv into place."""
    _validate_challenge_name(challenge_name)
    sandbox = _get_main_sandbox(invocation_context)
    tmp_path = f"{_unit_path(challenge_name)}.tmp"
    await _write_text_to_main_sandbox(invocation_context, tmp_path, content)
    _, exit_code = await sandbox.arun_command_in_container(
        f"mv {shlex.quote(tmp_path)} {shlex.quote(_unit_path(challenge_name))}"
    )
    if exit_code != 0:
        raise WriteupStoreError(f"Failed to finalize writeup '{challenge_name}'")


async def rebuild_index(invocation_context) -> str:
    """Regenerate INDEX.md from writeup frontmatter. Returns the new index text."""
    sandbox = _get_main_sandbox(invocation_context)
    names = await list_unit_names(invocation_context)
    entries: List[str] = []
    for name in sorted(names):
        try:
            body = await sandbox.aextract_file_from_container(_unit_path(name))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("Skipping writeup %s: %s", name, exc)
            continue
        meta = parse_unit_frontmatter(body)
        if meta is None:
            logger.warning("Skipping writeup %s: malformed frontmatter", name)
            continue
        entries.append(format_index_line(meta["name"], meta["keywords"], meta["hook"]))
    new_index = INDEX_HEADER + "\n".join(entries) + ("\n" if entries else "")
    await _write_text_to_main_sandbox(invocation_context, WRITEUP_INDEX_PATH, new_index)
    return new_index


def format_insight_entry(
    challenge_name: str,
    stuck_point: str,
    trajectory_gap: str,
    writeup_correction: str,
    keywords: List[str],
) -> str:
    keywords_text = ", ".join(keywords)
    return (
        f"<!-- insight:{challenge_name} -->\n"
        f"## {challenge_name}\n\n"
        f"- keywords: {keywords_text}\n"
        f"- stuck point: {stuck_point.strip()}\n"
        f"- trajectory gap: {trajectory_gap.strip()}\n"
        f"- writeup correction: {writeup_correction.strip()}\n"
        f"<!-- /insight:{challenge_name} -->\n"
    )


async def upsert_insight_entry(
    invocation_context,
    challenge_name: str,
    stuck_point: str,
    trajectory_gap: str,
    writeup_correction: str,
    keywords: List[str],
) -> str:
    """Create or replace one challenge section inside INSIGHT.md."""
    _validate_challenge_name(challenge_name)
    current = await read_insight_file(invocation_context)
    entry = format_insight_entry(
        challenge_name, stuck_point, trajectory_gap, writeup_correction, keywords
    )
    start_marker = f"<!-- insight:{challenge_name} -->"
    end_marker = f"<!-- /insight:{challenge_name} -->"
    start = current.find(start_marker)
    if start != -1:
        end = current.find(end_marker, start)
        if end == -1:
            raise WriteupStoreError(
                f"Malformed INSIGHT.md section for '{challenge_name}'"
            )
        end += len(end_marker)
        new_content = current[:start] + entry.rstrip() + current[end:]
    else:
        new_content = current.rstrip() + "\n\n" + entry
    await _write_text_to_main_sandbox(invocation_context, INSIGHT_PATH, new_content)
    return new_content
