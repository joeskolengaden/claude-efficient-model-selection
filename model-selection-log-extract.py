#!/usr/bin/env python3
"""
Extracts delegation data (tier, tokens, duration, task) directly from Claude Code session
transcripts and appends it to ~/.claude/tools/model-selection-log.jsonl — zero AI/credit cost,
since this reads files already on disk instead of Claude making an extra tool call after every
delegation. Meant to run on a schedule (see the accompanying launchd plist), not interactively.

Scope: Agent-tool delegations that explicitly set a model tier — both foreground
(run_in_background: false) and background (the tool's own default) — plus Workflow agent() calls.

Workflow coverage works differently from the other two, because the data lives differently: a
Workflow run's tool_result in the main transcript is just a "launched in background" pointer (like
the Agent tool's background case), but unlike Agent, its completion is NOT signalled by a
<task-notification> in the main transcript at all (confirmed empirically — a real Workflow run's
task ID never appeared in a queued_command attachment, even long after the run had finished). So
instead of watching for a completion signal, each run's own directory is polled directly:
~/.claude/projects/<project>/<session-id>/subagents/workflows/<run-id>/journal.jsonl records one
"started"/"result" pair per agent() call in the script, and — the part that makes this possible at
all — a sibling agent-<agentId>.jsonl next to it is a REAL sub-transcript for that one call, with
genuine assistant `message.model` and `message.usage` per turn (confirmed against a live file
before writing this, not assumed). That's actually more granular than what's available for the
Agent tool (a single combined subagent_tokens figure): here tokens are summed directly from each
turn's usage block, and the model is the one that actually ran, not just the one requested.

Two honest limitations, called out rather than glossed over: (1) duration_ms is approximated as
last-turn-timestamp minus first-turn-timestamp within that sub-transcript, since no single duration
field exists there — close but not identical to the wall-clock duration_ms reported elsewhere.
(2) the tokens figure is a raw sum of input+output+cache_creation+cache_read across that call's
turns, which is a different basis than the Agent tool's subagent_tokens field — comparable in
magnitude, not guaranteed identical in formula. Both are noted here so nobody mistakes this for a
higher-precision number than it is.

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
  - workflow_journal_offsets: per-journal.jsonl byte offset, so repeat runs only scan new "result"
    lines (mirrors file_offsets but kept separate since these live under a different glob)
  - last_run: ISO timestamp of the last successful run, for missed-day detection
"""
import getpass
import json
import platform
import re
import time
from datetime import datetime
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
            state.setdefault("workflow_journal_offsets", {})
            return state
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "file_offsets": {},
        "pending_background": {},
        "workflow_journal_offsets": {},
        "last_run": None,
    }


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2))


def all_transcript_files():
    if not PROJECTS_DIR.is_dir():
        return []
    return [p for p in PROJECTS_DIR.glob("*/*.jsonl")]


def all_workflow_journal_files():
    if not PROJECTS_DIR.is_dir():
        return []
    return [p for p in PROJECTS_DIR.glob("*/*/subagents/workflows/*/journal.jsonl")]


def normalize_tier(model_id):
    """Raw model IDs (e.g. "claude-opus-4-8", "claude-haiku-4-5-20251001") down to the same
    tier names ("opus", "haiku", ...) used everywhere else in the log, so Workflow-sourced
    entries aggregate correctly alongside Agent-tool ones. Falls back to the raw ID, unchanged,
    for anything that doesn't match a known tier — better than guessing wrong."""
    lowered = (model_id or "").lower()
    for tier in ("opus", "sonnet", "haiku", "fable"):
        if tier in lowered:
            return tier
    return model_id


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


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _read_agent_subtranscript(agent_path):
    """Returns (model, task, cwd, timestamp, tokens, tool_uses_count, duration_ms) for one
    Workflow agent() call's sub-transcript, or None if the file is missing/unreadable/empty —
    e.g. a "result" journal line written just before its sibling file was flushed to disk."""
    if not agent_path.exists():
        return None
    model = None
    task = None
    cwd = None
    first_ts = None
    last_ts = None
    tokens = 0
    tool_uses_count = 0
    try:
        with open(agent_path, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(d.get("timestamp"))
                if ts:
                    first_ts = ts if first_ts is None else min(first_ts, ts)
                    last_ts = ts if last_ts is None else max(last_ts, ts)
                if cwd is None and d.get("cwd"):
                    cwd = d.get("cwd")
                msg = d.get("message")
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if d.get("type") == "user" and task is None:
                    if isinstance(content, str):
                        task = content
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                task = block.get("text", "")
                                break
                elif d.get("type") == "assistant":
                    if model is None and msg.get("model"):
                        model = msg["model"]
                    usage = msg.get("usage")
                    if isinstance(usage, dict):
                        tokens += sum(
                            usage.get(k, 0) or 0
                            for k in (
                                "input_tokens",
                                "output_tokens",
                                "cache_creation_input_tokens",
                                "cache_read_input_tokens",
                            )
                        )
                    if isinstance(content, list):
                        tool_uses_count += sum(
                            1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
                        )
    except OSError:
        return None
    if model is None:
        return None
    duration_ms = int((last_ts - first_ts).total_seconds() * 1000) if first_ts and last_ts else 0
    timestamp = first_ts.isoformat() if first_ts else None
    return normalize_tier(model), task, cwd, timestamp, tokens, tool_uses_count, duration_ms


def extract_from_workflow_journal(journal_path, start_offset):
    """Returns (new_end_offset, [entries]) for "result" lines appended to a Workflow run's
    journal.jsonl since start_offset. Each result names an agentId; the actual model/usage data
    is read from that agent's own sibling sub-transcript file, not the journal line itself."""
    size = journal_path.stat().st_size
    if size <= start_offset:
        return size, []

    with open(journal_path, "r", errors="replace") as f:
        f.seek(start_offset)
        chunk = f.read()
    new_offset = start_offset + len(chunk.encode("utf-8", errors="replace"))

    entries = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") != "result":
            continue
        agent_id = d.get("agentId")
        if not agent_id:
            continue
        agent_path = journal_path.parent / f"agent-{agent_id}.jsonl"
        parsed = _read_agent_subtranscript(agent_path)
        if parsed is None:
            continue
        model, task, cwd, timestamp, tokens, tool_uses_count, duration_ms = parsed
        entries.append(make_entry(model, task, cwd, timestamp, tokens, tool_uses_count, duration_ms))

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

    workflow_offsets = state["workflow_journal_offsets"]
    for path in all_workflow_journal_files():
        key = str(path)
        if key not in workflow_offsets:
            # same no-backfill policy as main transcripts: only watch from here forward
            workflow_offsets[key] = path.stat().st_size
            continue
        new_offset, entries = extract_from_workflow_journal(path, workflow_offsets[key])
        workflow_offsets[key] = new_offset
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
