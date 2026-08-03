#!/usr/bin/env python3
"""
Extracts delegation data (tier, tokens, duration, task) directly from Claude Code session
transcripts and appends it to ~/.claude/tools/model-selection-log.jsonl — zero AI/credit cost,
since this reads files already on disk instead of Claude making an extra tool call after every
delegation. Meant to run on a schedule (see the accompanying launchd plist), not interactively.

Scope: Agent-tool delegations that explicitly set a model tier — both foreground
(run_in_background: false) and background (the tool's own default). Workflow agent() calls aren't
covered yet (a different transcript shape again); a delegation made that way won't appear until
this is extended further.

Foreground calls resolve within one scan: the tool_use and its tool_result both land in the
transcript back-to-back. Background calls don't — the launch and the completion notification can
be arbitrarily far apart, often past a scan-file's incremental read boundary, so a launched-but-
not-yet-completed background call is remembered in the state file's "pending_background" map
(tool_use_id -> launch details) and resolved whenever its completion notification is later seen,
even if that's a different run entirely. A launch that never completes just stays pending
indefinitely — harmless at this scale, but would need pruning if this map ever grew large.

Background completions arrive as a `type: "attachment"` entry (attachment.type ==
"queued_command") containing a <task-notification> block with a DIFFERENT usage-block format than
foreground tool_results (XML tags, not colon-separated) — confirmed against a real transcript
entry before writing the regex, not assumed from the foreground shape. The same task can notify
more than once (per Claude Code's own note text in that block, if the agent is resumed) — since a
pending entry is removed from state on first successful match, a repeat notification for the same
tool_use_id simply finds nothing pending and is safely skipped, not double-logged.

Like limit-notifier, a brand-new transcript is NOT backfilled on first sight — only content
appended after this script first sees a given file gets scanned. This avoids silently vacuuming in
every historical delegation from unrelated past work the first time it runs.

State file (~/.claude/tools/model-selection-log-extract-state.json) tracks:
  - per-transcript byte offset, so repeat runs only scan new content
  - pending_background: tool_use_id -> launch details, for background calls awaiting completion
  - last_run: ISO timestamp of the last successful run, for missed-day detection
"""
import getpass
import json
import platform
import re
import time
from pathlib import Path

HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
LOG_PATH = HOME / ".claude" / "tools" / "model-selection-log.jsonl"
STATE_PATH = HOME / ".claude" / "tools" / "model-selection-log-extract-state.json"

# Foreground: "<usage>subagent_tokens: 28678\ntool_uses: 1\nduration_ms: 8659</usage>"
FOREGROUND_USAGE_RE = re.compile(
    r"<usage>\s*subagent_tokens:\s*(\d+)\s*"
    r"tool_uses:\s*(\d+)\s*"
    r"duration_ms:\s*(\d+)\s*</usage>"
)
# Background: "<usage><subagent_tokens>44440</subagent_tokens><tool_uses>15</tool_uses><duration_ms>51888</duration_ms></usage>"
BACKGROUND_USAGE_RE = re.compile(
    r"<usage><subagent_tokens>(\d+)</subagent_tokens>"
    r"<tool_uses>(\d+)</tool_uses>"
    r"<duration_ms>(\d+)</duration_ms></usage>"
)
TASK_NOTIFICATION_RE = re.compile(
    r"<task-notification>.*?<tool-use-id>(.*?)</tool-use-id>.*?<status>(.*?)</status>.*?</task-notification>",
    re.DOTALL,
)


def load_state():
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
            state.setdefault("pending_background", {})
            return state
        except (json.JSONDecodeError, OSError):
            pass
    return {"file_offsets": {}, "pending_background": {}, "last_run": None}


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


def make_entry(model, task, cwd, timestamp, tokens, tool_uses_count, duration_ms):
    project = Path(cwd).name if cwd else "(unknown)"
    return {
        "timestamp": timestamp,
        "tier": model,
        "tokens": tokens,
        "duration_ms": duration_ms,
        "tool_uses": tool_uses_count,
        "task": (task or "")[:200],
        "escalated_from": None,  # not derivable from the transcript alone
        "project": project,
    }


def extract_from_file(path, start_offset, pending_background):
    """Returns (new_end_offset, [entries]) for content appended since start_offset. Mutates
    pending_background in place: adds newly-launched background calls, removes ones resolved
    by a completion notification found in this chunk."""
    size = path.stat().st_size
    if size <= start_offset:
        return size, []

    with open(path, "r", errors="replace") as f:
        f.seek(start_offset)
        chunk = f.read()
    new_offset = start_offset + len(chunk.encode("utf-8", errors="replace"))

    entries = []
    fg_tool_uses = []  # foreground launches awaiting their tool_result, same-chunk only
    fg_results = {}  # tool_use_id -> combined text of that tool_result's text blocks

    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Background completion notifications are a top-level "attachment" event, not nested
        # under message.content like tool_use/tool_result are.
        if d.get("type") == "attachment":
            attachment = d.get("attachment")
            if isinstance(attachment, dict) and attachment.get("type") == "queued_command":
                notif_text = attachment.get("prompt", "")
                nm = TASK_NOTIFICATION_RE.search(notif_text)
                if nm:
                    tool_use_id, status = nm.group(1).strip(), nm.group(2).strip()
                    if status == "completed" and tool_use_id in pending_background:
                        usage_m = BACKGROUND_USAGE_RE.search(notif_text)
                        if usage_m:
                            launch = pending_background.pop(tool_use_id)
                            tokens, tool_uses_count, duration_ms = (int(x) for x in usage_m.groups())
                            entries.append(make_entry(
                                launch["model"], launch["task"], launch["cwd"],
                                launch["timestamp"], tokens, tool_uses_count, duration_ms,
                            ))
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
                if not inp.get("model"):
                    continue
                launch = {
                    "model": inp["model"],
                    "task": inp.get("description", ""),
                    "timestamp": d.get("timestamp"),
                    "cwd": d.get("cwd"),
                }
                if inp.get("run_in_background") is False:
                    fg_tool_uses.append({"id": block.get("id"), **launch})
                else:
                    pending_background[block.get("id")] = launch
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
                    fg_results[tid] = fg_results.get(tid, "") + "\n".join(text_parts)

    for tu in fg_tool_uses:
        result_text = fg_results.get(tu["id"])
        if not result_text:
            continue  # tool_result not in this chunk (e.g. split across scan boundary) — picked up next run
        m = FOREGROUND_USAGE_RE.search(result_text)
        if not m:
            continue
        tokens, tool_uses_count, duration_ms = (int(x) for x in m.groups())
        entries.append(make_entry(
            tu["model"], tu["task"], tu["cwd"], tu["timestamp"],
            tokens, tool_uses_count, duration_ms,
        ))

    return new_offset, entries


def main():
    state = load_state()
    offsets = state.setdefault("file_offsets", {})
    pending_background = state["pending_background"]
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
        new_offset, entries = extract_from_file(path, offsets[key], pending_background)
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

    if pending_background:
        print(f"{len(pending_background)} background delegation(s) still awaiting completion")

    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(state)


if __name__ == "__main__":
    main()
