#!/usr/bin/env python3
"""
Installs the efficient-model-selection enforcement hooks into ~/.claude/settings.json.

Why this exists: the skill's guidance is advisory by default — Claude Code shows every session a
one-line description of the skill and leaves it to the model to notice a delegation is coming and
choose to go read the full rubric. Measured against 51 real sessions on the machine this was built
on, that happened twice (4%). These hooks make the enforceable parts of the skill actually
enforced, deterministically, instead of depending on the model remembering:

  - PreToolUse on Agent/Workflow: a two-part gate, run by model-selection-consult-check.py rather
    than an inline jq filter, because the second half needs to read the session transcript.
    (1) The call must set a model tier at all, and (2) the skill must actually have been consulted
    — a real Skill tool_use for it somewhere earlier in this session — before any task is assigned
    to a model. Part (2) is the addition: every earlier version enforced only (1), so a tier set
    from memory, with the skill never once opened, sailed through silently. Consultation is
    required once per session, not before every delegation; later calls in the same session pass
    straight through, since re-reading the whole rubric per delegation would be pure waste.
    Detection parses tool_use blocks properly and never greps: the transcript legitimately
    contains this skill's name in the SessionStart injected rubric, in this hook's own denial
    text, and in unrelated calls that merely mention it, and a substring match would count all of
    those as proof of consultation — silently disabling the gate it implements.
    Two earlier generations of this hook are recognized for silent in-place upgrade: v1 embedded
    the rubric directly in the denial text (cheap, but meant the skill was almost never actually
    invoked), v2 replaced that with a call-Skill-first instruction (traded one extra tool call for
    real trigger visibility).
  - PostToolUse on Agent/Workflow: after a delegation completes, (1) injects a reminder to report
    the tier and reason back to the user visibly (colored badge via a widget tool if available,
    else a blockquote callout), and (2) triggers model-selection-hourly-update.sh in the
    background (async, non-blocking) so the private GitHub log stays close to real-time instead of
    waiting up to an hour for the scheduled job. That script now holds a simple mkdir-based lock
    (flock isn't available on macOS by default) so a burst of parallel delegations — which this
    skill's own rubric explicitly encourages splitting work into — collapses into one effective
    sync instead of several processes racing on the same state file: whichever fires first runs
    normally, any other already-in-flight trigger exits immediately, and the hourly job remains as
    a backstop either way, so nothing is ever lost, only deferred by a few seconds at most.
  - UserPromptSubmit: on a substantial or multi-part incoming prompt (word count >= 40, or 2+
    newlines, or a numbered list — checked against real captured prompts before shipping, not
    guessed), injects a reminder to consider delegating any independent/routine piece of it, while
    explicitly telling Claude NOT to delegate tightly-coupled, sequential, or stateful work. Stays
    silent on short or single-step prompts — checked against real recent messages from other
    sessions ("is the local host still running?", "do the recomendations") to confirm it doesn't
    fire on exactly the kind of terse, sequential-debugging turns that shouldn't be nudged.
  - SubagentStop: also triggers the same async sync as PostToolUse/Agent, added because
    PostToolUse alone leaves a real gap. `run_in_background: true` (the Agent tool's default) means
    the tool_result that fires PostToolUse arrives at LAUNCH time ("started in background"), not
    real completion — the actual result shows up later via a task-notification, which is not a
    tool_result and never fires PostToolUse at all. Confirmed empirically with a temporary inert
    diagnostic hook (not guessed): SubagentStop fires at real completion, its
    last_assistant_message matching the eventual task-notification result exactly. It may also
    fire redundantly alongside PostToolUse for foreground delegations — harmless, the shared
    script's lock collapses redundant triggers into one effective run.
  - SessionStart: every hook above only has anything to act on once a delegation is already being
    attempted or a substantial prompt comes in — a session that never reaches either point never
    sees the rubric at all. This one closes that: it fires once, at the very start of every
    session, and injects the condensed core rubric (tiers, splitting mixed-difficulty work,
    escalation, reporting, override) directly into context — not a pointer to go call Skill, the
    actual guidance, so it's genuinely present from turn one regardless of whether a delegation
    ever happens. Unlike the old embedded-rubric PreToolUse design (rejected for paying that cost
    on every delegation), this pays it exactly once per session, which is a materially different
    tradeoff — and in practice it should make the PreToolUse retry-via-Skill path fire less often
    too, since a session primed with the rubric from the start is more likely to set a valid tier
    on its first attempt. This hook doesn't read any field from SessionStart's own input — it
    injects fixed content unconditionally — so unlike UserPromptSubmit and SubagentStop, there was
    no schema to verify empirically before building it; the risk that motivated verifying those
    (misreading an unfamiliar field) doesn't apply here.

Honest limit, unchanged by this script: a hook can force a *block* deterministically, but it cannot
force which specific action Claude takes next — the retry instruction can't literally compel a
Skill call any more than the removed embedded rubric could compel the reporting reminder to be
followed. Claude could still set a tier from memory instead of calling Skill. What the block *can*
do deterministically is refuse a tier-less call outright, every time. See the skill's SKILL.md,
"Report the choice" section, and "Make it deterministic" for the full picture.

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

# The PreToolUse gate is a script, not a jq filter — it has to read the session transcript to
# answer "was the skill actually consulted?", which jq alone can't do from the hook payload.
# Invoked via an explicit python3 so it does not depend on the file's exec bit or on PATH.
CONSULT_CHECK_COMMAND = 'python3 "$HOME/.claude/tools/model-selection-consult-check.py"'
CONSULT_CHECK_PATH = Path.home() / ".claude" / "tools" / "model-selection-consult-check.py"

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
SYNC_TRIGGER_COMMAND = '"$HOME/.claude/tools/model-selection-hourly-update.sh"'
SESSION_START_CONTEXT = (
    "efficient-model-selection is active this session. Before any delegation - an Agent call, a "
    "Workflow agent() call, or splitting a multi-step task into pieces - pick the cheapest tier "
    "that genuinely fits: HAIKU for routine/mechanical/checkable work (listing, grepping, "
    "fetch+summarize, mechanical edits). SONNET for multi-step work needing synthesis/judgment "
    "across a few things, or the default when unsure. OPUS for real ambiguity, conflicting "
    "inputs, or costly-if-wrong decisions. FABLE reserved for the deepest reasoning or a "
    "documented cheaper-tier failure only - a task mattering a lot is not by itself a reason for "
    "it. Split mixed-difficulty work across tiers rather than running it all on one. Default down "
    "when unsure; if the result from a chosen tier is inadequate, escalate exactly one tier up "
    "and say why. Report the tier and a short reason back to the user in a visually distinct way (a "
    "colored badge via a widget tool if available, else a blockquote callout) every time a "
    "delegation happens, not only if asked. A direct user instruction naming a model or tier "
    "always wins immediately, no pushback. Call the Skill tool with skill: "
    "efficient-model-selection for the complete rubric, including exact per-tier criteria, "
    "generation-pinning, and savings tracking."
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


def jq_session_start_command(context):
    return (
        "jq '{hookSpecificOutput: {hookEventName: \"SessionStart\", additionalContext: "
        '"' + context.replace('"', '\\"') + '"}}\''
    )


def cmd_hook(command, async_=False):
    h = {"type": "command", "command": command}
    if async_:
        h["async"] = True
    return h


AGENT_PRE_IF_CLAUSE = '((.tool_input.model // "") == "")'
WORKFLOW_PRE_IF_CLAUSE = (
    '((.tool_input.script // "") | test("agent\\\\(")) and '
    '((.tool_input.script // "") | test("model\\\\s*:") | not)'
)

# Each entry is the *list* of hook dicts that should run, in order, for that (event, matcher).
# PostToolUse/Agent and PostToolUse/Workflow each carry two: the reporting reminder (unchanged
# since it first shipped) plus the new real-time sync trigger, run async so it never adds latency
# to the delegation itself.
DESIRED = {
    ("PreToolUse", "Agent"): [cmd_hook(CONSULT_CHECK_COMMAND)],
    ("PreToolUse", "Workflow"): [cmd_hook(CONSULT_CHECK_COMMAND)],
    ("PostToolUse", "Agent"): [
        cmd_hook(jq_post_command(AGENT_POST_CONTEXT)),
        cmd_hook(SYNC_TRIGGER_COMMAND, async_=True),
    ],
    ("PostToolUse", "Workflow"): [
        cmd_hook(jq_post_command(WORKFLOW_POST_CONTEXT)),
        cmd_hook(SYNC_TRIGGER_COMMAND, async_=True),
    ],
    ("UserPromptSubmit", None): [cmd_hook(jq_prompt_submit_command(PROMPT_SUBMIT_CONTEXT))],
    ("SubagentStop", None): [cmd_hook(SYNC_TRIGGER_COMMAND, async_=True)],
    ("SessionStart", None): [cmd_hook(jq_session_start_command(SESSION_START_CONTEXT))],
}

# Prior reason texts this script has shipped for the two PreToolUse hooks, kept only so an
# in-place upgrade can tell "an older version of MY OWN hook" apart from a genuinely foreign hook
# someone else added on the same event/matcher — the former is safe to silently replace, the
# latter must never be silently overwritten. v1 embedded the rubric directly in the block text
# (cheaper per-delegation, but meant Skill was almost never actually invoked); v2 (current)
# instructs Claude to call Skill first instead, trading a small per-delegation cost for actual
# trigger visibility.
_AGENT_PRE_REASON_V1 = (
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
_WORKFLOW_PRE_REASON_V1 = (
    "This Workflow script calls agent() but sets opts.model nowhere. Rubric: HAIKU = "
    "routine/mechanical/checkable. SONNET = multi-step synthesis, default when unsure. OPUS = "
    "real ambiguity, costly if wrong. FABLE = reserve only. Set opts.model on each agent() call "
    "using this rubric and retry. (Best-effort check: total omission only, not per-call "
    "coverage.) Report the tier and a short reason for each delegation to the user in a visually "
    "distinct way when this completes - every time, not only if asked."
)
# v2 shipped after v1: the rubric came out of the denial text, replaced by an instruction to call
# the Skill tool before retrying. Registered here because v2 is what is currently deployed on
# existing installs — without it, the upgrade to the script-based gate reports a false conflict
# instead of replacing cleanly.
_AGENT_PRE_REASON_V2 = (
    "No model tier set. Call the Skill tool now with skill: efficient-model-selection to load "
    "the full tier rubric, then retry this call with an explicit model (haiku/sonnet/opus/fable, "
    "or the current model only if deliberately inheriting it, never as a default). When this "
    "delegation completes, report the tier and a short reason to the user in a visually distinct "
    "way (a colored badge via a widget tool if available, else a blockquote callout) - every "
    "time, not only if asked."
)
_WORKFLOW_PRE_REASON_V2 = (
    "This Workflow script calls agent() but sets opts.model nowhere. Call the Skill tool now "
    "with skill: efficient-model-selection to load the full tier rubric, then set opts.model on "
    "each agent() call and retry. (Best-effort check: total omission only, not per-call "
    "coverage.) Report the tier and a short reason for each delegation to the user in a visually "
    "distinct way when this completes - every time, not only if asked."
)
KNOWN_PRIOR_HOOK_LISTS = {
    ("PreToolUse", "Agent"): [
        [cmd_hook(jq_pre_command(AGENT_PRE_IF_CLAUSE, _AGENT_PRE_REASON_V1))],
        [cmd_hook(jq_pre_command(AGENT_PRE_IF_CLAUSE, _AGENT_PRE_REASON_V2))],
    ],
    ("PreToolUse", "Workflow"): [
        [cmd_hook(jq_pre_command(WORKFLOW_PRE_IF_CLAUSE, _WORKFLOW_PRE_REASON_V1))],
        [cmd_hook(jq_pre_command(WORKFLOW_PRE_IF_CLAUSE, _WORKFLOW_PRE_REASON_V2))],
    ],
    # v1 of the PostToolUse hooks shipped with only the reporting reminder, before the real-time
    # sync trigger was added — recognized here so that upgrade is also silent and automatic.
    ("PostToolUse", "Agent"): [
        [cmd_hook(jq_post_command(AGENT_POST_CONTEXT))],
    ],
    ("PostToolUse", "Workflow"): [
        [cmd_hook(jq_post_command(WORKFLOW_POST_CONTEXT))],
    ],
}


def load_settings():
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text())
    return {}


def main():
    # The PreToolUse gate is the one hook that lives in a separate file; warn loudly rather than
    # silently installing a hook command that points at nothing.
    if not CONSULT_CHECK_PATH.exists():
        print(
            f"warning: {CONSULT_CHECK_PATH} not found — the PreToolUse gate will allow everything "
            f"until that script is in place. Copy it from the skill repo alongside this one.",
            file=sys.stderr,
        )

    settings = load_settings()
    hooks = settings.setdefault("hooks", {})

    installed, skipped_identical, upgraded, conflicts = [], [], [], []

    for (event, matcher), desired_hooks in DESIRED.items():
        label = event if matcher is None else f"{event}/{matcher}"
        entries = hooks.setdefault(event, [])
        existing = next((e for e in entries if e.get("matcher") == matcher), None)

        if existing is None:
            new_entry = {"hooks": desired_hooks}
            if matcher is not None:
                new_entry = {"matcher": matcher, **new_entry}
            entries.append(new_entry)
            installed.append(label)
            continue

        existing_hooks = existing.get("hooks", [])
        prior_versions = KNOWN_PRIOR_HOOK_LISTS.get((event, matcher), [])
        if existing_hooks == desired_hooks:
            skipped_identical.append(label)
        elif existing_hooks in prior_versions:
            existing["hooks"] = desired_hooks
            upgraded.append(label)
        else:
            conflicts.append(label)

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))

    # Round-trip validation — fail loudly rather than leave a broken settings.json in place.
    json.loads(SETTINGS_PATH.read_text())

    if installed:
        print(f"Installed: {', '.join(installed)}")
    if upgraded:
        print(f"Upgraded from a prior version of this hook: {', '.join(upgraded)}")
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
