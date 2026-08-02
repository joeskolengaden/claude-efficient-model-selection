#!/usr/bin/env python3
"""
Extracts delegation data (tier, tokens, duration, task) directly from Claude Code session
transcripts and appends it to ~/.claude/tools/model-selection-log.jsonl — zero AI/credit cost,
since this reads files already on disk instead of Claude making an extra tool call after every
delegation. Meant to run on a schedule (see the accompanying launchd plist), not interactively.

Scope: only foreground Agent-tool delegations (run_in_background: false) that explicitly set a
model tier — that's every delegation the efficient-model-selection skill actually governs.
Background Agent calls and Workflow agent() calls aren't covered yet (their completion data lives
in a different transcript shape); a delegation made that way won't appear until this is extended.

Like limit-notifier, a brand-new transcript is NOT backfilled on first sight — only content
appended after this script first sees a given file gets scanned. This avoids silently vacuuming in
every historical delegation from unrelated past work the first time it runs.

State file (~/.claude/tools/model-selection-log-extract-state.json) tracks:
  - per-transcript byte offset, so repeat runs only scan new content
  - last_run: ISO timestamp of the last successful run, for missed-day detection
"""
import getpass
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
LOG_PATH = HOME / ".claude" / "tools" / "model-selection-log.jsonl"
STATE_PATH = HOME / ".claude" / "tools" / "model-selection-log-extract-state.json"

USAGE_RE = re.compile(
    r"<usage>\s*subagent_tokens:\s*(\d+)\s*"
    r"tool_uses:\s*(\d+)\s*"
    r"duration_ms:\s*(\d+)\s*</usage>"
)


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"file_offsets": {}, "last_run": None}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def all_transcript_files():
    if not PROJECTS_DIR.is_dir():
        return []
    return [p for p in PROJECTS_DIR.glob("*/*.jsonl")]


def utc_offset_str():
    offset = time.strftime("%z")  # e.g. "+0530"
    if not offset:
        return None
    sign, hh, mm = offset[0], offset[1:3], offset[3:5]
    return f"{sign}{hh}:{mm}"


def extract_from_file(path, start_offset):
    """Yield (new_end_offset, [entries]) for content appended since start_offset."""
    size = path.stat().st_size
    if size <= start_offset:
        return size, []

    with open(path, "r", errors="replace") as f:
        f.seek(start_offset)
        chunk = f.read()
    new_offset = start_offset + len(chunk.encode("utf-8", errors="replace"))

    # Build a tool_use_id -> tool_result text map from this chunk, plus the tool_use records
    tool_uses = []  # (id, model, description, timestamp, cwd)
    results = {}  # id -> combined text of all text blocks in that tool_result

    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Agent":
                inp = block.get("input", {})
                if inp.get("model") and inp.get("run_in_background") is False:
                    tool_uses.append({
                        "id": block.get("id"),
                        "model": inp["model"],
                        "task": inp.get("description", ""),
                        "timestamp": d.get("timestamp"),
                        "cwd": d.get("cwd"),
                    })
            elif block.get("type") == "tool_result":
                tid = block.get("tool_use_id")
                inner = block.get("content")
                text_parts = []
                if isinstance(inner, list):
                    for c in inner:
                        if isinstance(c, dict) and c.get("type") == "text":
                            text_parts.append(c.get("text", ""))
                elif isinstance(inner, str):
                    text_parts.append(inner)
                if tid:
                    results[tid] = results.get(tid, "") + "\n".join(text_parts)

    entries = []
    for tu in tool_uses:
        result_text = results.get(tu["id"])
        if not result_text:
            continue  # tool_result not in this chunk (e.g. split across scan boundary) — picked up next run
        m = USAGE_RE.search(result_text)
        if not m:
            continue
        tokens, tool_uses_count, duration_ms = (int(x) for x in m.groups())
        project = Path(tu["cwd"]).name if tu.get("cwd") else "(unknown)"
        entries.append({
            "timestamp": tu["timestamp"],
            "tier": tu["model"],
            "tokens": tokens,
            "duration_ms": duration_ms,
            "tool_uses": tool_uses_count,
            "task": tu["task"][:200],
            "escalated_from": None,  # not derivable from the transcript alone
            "project": project,
        })

    return new_offset, entries


def main():
    state = load_state()
    offsets = state.setdefault("file_offsets", {})
    machine_fields = {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "username": getpass.getuser(),
        "utc_offset": utc_offset_str(),
    }

    all_new_entries = []
    for path in all_transcript_files():
        key = str(path)
        if key not in offsets:
            # first time seeing this transcript: don't backfill its whole history, start from here
            offsets[key] = path.stat().st_size
            continue
        new_offset, entries = extract_from_file(path, offsets[key])
        offsets[key] = new_offset
        all_new_entries.extend(entries)

    if all_new_entries:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            for e in all_new_entries:
                e.update(machine_fields)
                f.write(json.dumps(e) + "\n")
        print(f"logged {len(all_new_entries)} new delegation(s)")
    else:
        print("no new delegations found")

    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(state)


if __name__ == "__main__":
    main()
