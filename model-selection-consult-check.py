#!/usr/bin/env python3
"""
PreToolUse gate for Agent/Workflow delegations, enforcing BOTH halves of
efficient-model-selection:

  1. A model tier is explicitly set on the call, and
  2. the skill has actually been consulted (Skill tool invoked) in this session
     before any task is assigned to a model.

The earlier hook only enforced (1) — a tier set from memory, without the skill ever being read,
passed silently. This closes that: the first delegation in a session is blocked until the skill
has genuinely been loaded, after which subsequent delegations pass (consultation is per-session,
not per-delegation — re-reading the full rubric before every single call would be pure waste).

Why this can't be a jq one-liner like the other hooks: answering "was the skill consulted?" means
reading the session transcript, which arrives as `transcript_path` in the hook's own stdin
(confirmed empirically from a real PreToolUse payload, not assumed).

Detection is deliberately strict — proper JSON parsing of tool_use blocks, never a substring
grep. The transcript legitimately contains the string "efficient-model-selection" in several
places that are NOT a consultation: the SessionStart hook's injected rubric, this hook's own
denial text, and any unrelated call that merely mentions it (a real skill-creator invocation in
one transcript embedded the whole policy in its arguments). A grep would count all of those as
proof of consultation and quietly disable this gate.

Namespacing: a plugin-installed skill can surface as "<plugin>:efficient-model-selection" rather
than the bare name, so the match is on the trailing segment.

Failure policy: fail OPEN, loudly. If the transcript is unreadable or the payload has an
unexpected shape, the consultation half is skipped (the tier check still applies) and a
systemMessage surfaces why. A bug here would otherwise block every delegation in every project —
for a gate this broad, a visible non-enforcement beats an invisible deadlock.
"""
import json
import sys

SKILL_NAME = "efficient-model-selection"

TIER_MISSING_REASON = (
    "No model tier set. Call the Skill tool now with skill: efficient-model-selection to load "
    "the full tier rubric, then retry this call with an explicit model (haiku/sonnet/opus/fable, "
    "or the current model only if deliberately inheriting it, never as a default). When this "
    "delegation completes, report the tier and a short reason to the user in a visually distinct "
    "way (a colored badge via a widget tool if available, else a blockquote callout) - every "
    "time, not only if asked."
)
NOT_CONSULTED_REASON = (
    "A model tier is set, but the efficient-model-selection skill has not been consulted in this "
    "session, and it must be before any task is assigned to a model. Call the Skill tool now with "
    "skill: efficient-model-selection, then retry this call. This is required once per session, "
    "not before every delegation - later delegations in this session will pass straight through. "
    "Report the tier and a short reason to the user in a visually distinct way when this "
    "completes."
)
WORKFLOW_TIER_MISSING_REASON = (
    "This Workflow script calls agent() but sets opts.model nowhere. Call the Skill tool now "
    "with skill: efficient-model-selection to load the full tier rubric, then set opts.model on "
    "each agent() call and retry. (Best-effort check: total omission only, not per-call "
    "coverage.) Report the tier and a short reason for each delegation to the user in a visually "
    "distinct way when this completes - every time, not only if asked."
)


def emit(decision, reason=None, system_message=None):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision}}
    if reason:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    if system_message:
        out["systemMessage"] = system_message
    print(json.dumps(out))
    sys.exit(0)


def tier_is_set(tool_name, tool_input):
    if tool_name == "Workflow":
        script = tool_input.get("script")
        if not isinstance(script, str):
            return True  # nothing to inspect; don't invent a violation
        if "agent(" not in script:
            return True  # no delegation in this script at all
        return "model:" in script
    model = tool_input.get("model")
    return isinstance(model, str) and model.strip() != ""


def skill_was_consulted(transcript_path):
    """True if a Skill tool_use for this skill appears anywhere in the session transcript.

    Raises on unreadable transcript so the caller can fail open with a visible message.
    """
    with open(transcript_path, errors="replace") as f:
        for line in f:
            # Cheap prefilter first — these transcripts run to tens of megabytes, and this hook
            # sits in front of every delegation, so a full json.loads per line is not affordable.
            if SKILL_NAME not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use" or block.get("name") != "Skill":
                    continue
                skill = (block.get("input") or {}).get("skill")
                if not isinstance(skill, str):
                    continue
                # Accept a plugin-namespaced form ("<plugin>:efficient-model-selection") too.
                if skill == SKILL_NAME or skill.endswith(":" + SKILL_NAME):
                    return True
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        emit("allow", system_message=f"efficient-model-selection gate skipped: unreadable hook input ({exc})")

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}

    if not tier_is_set(tool_name, tool_input):
        emit("deny", WORKFLOW_TIER_MISSING_REASON if tool_name == "Workflow" else TIER_MISSING_REASON)

    transcript_path = payload.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        emit("allow", system_message="efficient-model-selection: tier OK; consultation unverifiable (no transcript_path in hook input)")

    try:
        consulted = skill_was_consulted(transcript_path)
    except Exception as exc:
        emit("allow", system_message=f"efficient-model-selection: tier OK; consultation unverifiable ({exc})")

    if not consulted:
        emit("deny", NOT_CONSULTED_REASON)

    emit("allow")


if __name__ == "__main__":
    main()
