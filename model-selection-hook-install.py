#!/usr/bin/env python3
"""
Installs the efficient-model-selection enforcement hooks into ~/.claude/settings.json.

Why this exists: the skill's guidance is advisory by default — Claude Code shows every session a
one-line description of the skill and leaves it to the model to notice a delegation is coming and
choose to go read the full rubric. Measured against 51 real sessions on the machine this was built
on, that happened twice (4%). These hooks make the enforceable parts of the skill actually
enforced, deterministically, instead of depending on the model remembering:

  - PreToolUse on Agent/Workflow: blocks a delegation that has no model tier set at all, and the
    block's own reason text carries the full Haiku/Sonnet/Opus/Fable rubric — so the guidance
    reaches context by being forced into the block, not by hoping the model goes and reads the
    skill first.
  - PostToolUse on Agent/Workflow: after a delegation completes, injects a reminder to report the
    tier and reason back to the user visibly (colored badge via a widget tool if available, else a
    blockquote callout).
  - UserPromptSubmit: on a substantial or multi-part incoming prompt (word count >= 40, or 2+
    newlines, or a numbered list — checked against real captured prompts before shipping, not
    guessed), injects a reminder to consider delegating any independent/routine piece of it, while
    explicitly telling Claude NOT to delegate tightly-coupled, sequential, or stateful work. Stays
    silent on short or single-step prompts — checked against real recent messages from other
    sessions ("is the local host still running?", "do the recomendations") to confirm it doesn't
    fire on exactly the kind of terse, sequential-debugging turns that shouldn't be nudged.

Honest limit, unchanged by this script: a hook can force a *block* deterministically, but it cannot
force the *shape* of Claude's final reply, nor force an actual delegation decision — all three
reminders are strong nudges, not guarantees. See the skill's SKILL.md, "Report the choice" section.

Safe to re-run: each hook entry is matched by its (event, matcher) pair — UserPromptSubmit has no
matcher (no tool to match against), so it's keyed on event alone. If an identical entry is already
installed, it's left alone. If a *different* hook is already installed on the same (event,
matcher) — something else you added yourself — this script does NOT overwrite it; it reports the
conflict and leaves your settings file untouched for that entry, so you can merge it by hand.
"""
import json
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

AGENT_PRE_REASON = (
    "No model tier set. Pick one now: HAIKU = routine/mechanical/checkable, little judgment "
    "(listing, grepping, fetch+summarize, mechanical edits). SONNET = multi-step work needing "
    "synthesis/judgment across a few things, or default when unsure. OPUS = real ambiguity, "
    "conflicting inputs, costly if wrong. FABLE = reserve for the deepest reasoning or a "
    "documented cheaper-tier failure only. Set model to haiku/sonnet/opus/fable (or explicitly to "
    "the current model only if deliberately inheriting it, never as a default) and retry. When "
    "this delegation completes, report the tier and a short reason to the user in a visually "
    "distinct way (a colored badge via a widget tool if available, else a blockquote callout) - "
    "every time, not only if asked."
)
WORKFLOW_PRE_REASON = (
    "This Workflow script calls agent() but sets opts.model nowhere. Rubric: HAIKU = "
    "routine/mechanical/checkable. SONNET = multi-step synthesis, default when unsure. OPUS = "
    "real ambiguity, costly if wrong. FABLE = reserve only. Set opts.model on each agent() call "
    "using this rubric and retry. (Best-effort check: total omission only, not per-call "
    "coverage.) Report the tier and a short reason for each delegation to the user in a visually "
    "distinct way when this completes - every time, not only if asked."
)
AGENT_POST_CONTEXT = (
    "Reminder (efficient-model-selection): report the tier used for this delegation and a short "
    "reason to the user in a visually distinct way - a colored badge via a widget tool if "
    "available, else a blockquote callout - as part of your reply. Do this every time, not only "
    "if asked."
)
WORKFLOW_POST_CONTEXT = (
    "Reminder (efficient-model-selection): report the tier used for each delegation and a short "
    "reason to the user in a visually distinct way - a colored badge via a widget tool if "
    "available, else a blockquote callout - as part of your reply. Do this every time, not only "
    "if asked."
)
PROMPT_SUBMIT_CONTEXT = (
    "efficient-model-selection: this looks like a substantial or multi-part request. Before "
    "diving in, briefly consider whether any independent, routine, or mechanical piece of it "
    "could be delegated to a subagent via Agent (with an explicit model tier per the rubric). Do "
    "not delegate tightly-coupled, stateful, or interactive work - live debugging, edit-test-"
    "restart loops, or anything where each step depends on the last result stays in the main loop."
)


def jq_pre_command(if_clause, reason):
    # if_clause is the exact text between "if " and " then" — callers supply their own parens,
    # since Agent's and Workflow's conditions need different wrapping and a generic wrapper here
    # previously produced a functionally-equivalent but not byte-identical string, which broke the
    # dedup check below against an already-installed hook.
    return (
        "jq 'if " + if_clause + " then "
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", '
        'permissionDecisionReason: "' + reason.replace('"', '\\"') + '"}} '
        'else {hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "allow"}} end\''
    )


def jq_post_command(context):
    return (
        "jq '{hookSpecificOutput: {hookEventName: \"PostToolUse\", additionalContext: "
        '"' + context.replace('"', '\\"') + '"}}\''
    )


def jq_prompt_submit_command(context):
    # Fires only on a substantial/multi-part prompt: word count >= 40, or 2+ newlines, or a
    # numbered list. Stays silent (bare {}) otherwise — validated against real captured prompts
    # from other sessions before shipping, not just synthetic cases.
    return (
        'jq \'if (((.prompt // "") | split(" ") | length) >= 40) or '
        '(((.prompt // "") | [scan("\\n")] | length) >= 2) or '
        '((.prompt // "") | test("(^|\\n)\\\\s*[0-9]+[.)]")) then '
        '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: '
        '"' + context.replace('"', '\\"') + '"}} else {} end\''
    )


DESIRED = {
    ("PreToolUse", "Agent"): jq_pre_command('((.tool_input.model // "") == "")', AGENT_PRE_REASON),
    ("PreToolUse", "Workflow"): jq_pre_command(
        '((.tool_input.script // "") | test("agent\\\\(")) and '
        '((.tool_input.script // "") | test("model\\\\s*:") | not)',
        WORKFLOW_PRE_REASON,
    ),
    ("PostToolUse", "Agent"): jq_post_command(AGENT_POST_CONTEXT),
    ("PostToolUse", "Workflow"): jq_post_command(WORKFLOW_POST_CONTEXT),
    ("UserPromptSubmit", None): jq_prompt_submit_command(PROMPT_SUBMIT_CONTEXT),
}


def load_settings():
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text())
    return {}


def main():
    settings = load_settings()
    hooks = settings.setdefault("hooks", {})

    installed, skipped_identical, conflicts = [], [], []

    for (event, matcher), command in DESIRED.items():
        label = event if matcher is None else f"{event}/{matcher}"
        entries = hooks.setdefault(event, [])
        existing = next((e for e in entries if e.get("matcher") == matcher), None)

        if existing is None:
            new_entry = {"hooks": [{"type": "command", "command": command}]}
            if matcher is not None:
                new_entry = {"matcher": matcher, **new_entry}
            entries.append(new_entry)
            installed.append(label)
            continue

        existing_commands = [h.get("command") for h in existing.get("hooks", []) if h.get("type") == "command"]
        if existing_commands == [command]:
            skipped_identical.append(label)
        else:
            conflicts.append(label)

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))

    # Round-trip validation — fail loudly rather than leave a broken settings.json in place.
    json.loads(SETTINGS_PATH.read_text())

    if installed:
        print(f"Installed: {', '.join(installed)}")
    if skipped_identical:
        print(f"Already installed, unchanged: {', '.join(skipped_identical)}")
    if conflicts:
        print(
            f"Conflict, left untouched: {', '.join(conflicts)} — a different hook is already "
            f"registered on that event/matcher. Merge it by hand in {SETTINGS_PATH}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"efficient-model-selection enforcement hooks are active in {SETTINGS_PATH}")


if __name__ == "__main__":
    main()
