#!/usr/bin/env python3
"""
Reads ~/.claude/tools/model-selection-log.jsonl and reports delegation savings.

Estimate, not exact billing: each logged entry carries one blended token count
(subagent_tokens from the Agent/Workflow call's own <usage> block), with no
input/output split — so cost uses each tier's average of its input and output
price, not precise per-token rates. Opus is the counterfactual baseline: it's
the documented no-skill default for delegated work, not the most expensive
tier (Fable), so it's the honest comparison rather than the most flattering one.

Usage:
    python3 model-selection-report.py             # full summary
    python3 model-selection-report.py --audit      # flag suspected mis-tiers (see below)
    python3 model-selection-report.py --by-month   # also break down by month
    python3 model-selection-report.py --by-day     # also break down by day
    python3 model-selection-report.py --by-host    # also break down by hostname
    python3 model-selection-report.py --by-user    # also break down by username
    python3 model-selection-report.py --by-project # also break down by project

Entries logged before a given field was added won't have it — they're grouped under "(unknown)"
in the relevant --by-* output rather than dropped. Escalation count and average duration are
shown per group whenever at least one entry in that group carries the relevant field.

Why --audit exists: savings is a ONE-SIDED metric. It rises whenever work moves to a cheaper
tier, whether or not the result held up — a log that ran everything on haiku would report ~80%
"savings" while producing garbage, and nothing else here would catch it. The honest counterweight
is the escalation rate (how often a cheap tier had to be retried higher), which is reported
alongside savings, including — especially — when it is zero. Since the zero-cost extractor cannot
see escalations at all (see SKILL.md, "Track delegations"), --audit adds the other available
signal: effort actually expended, which IS recorded per delegation as tool_uses and duration_ms.
A cheap tier that burned many tool calls over a long run is a candidate for having been
under-tiered; an expensive tier that finished trivially is a candidate for overspend. These are
flags for review, never verdicts — the log records what a delegation cost, never whether its
output was any good.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "tools" / "model-selection-log.jsonl"

# $ per million tokens, blended = average of (input + output) price. Update these if pricing
# changes — see the efficient-model-selection skill's "The four tiers" section for the source.
BLENDED_RATE_PER_MTOK = {
    "haiku": 3.0,
    "sonnet": 9.0,
    "opus": 15.0,
    "fable": 30.0,
}
BASELINE_TIER = "opus"


def load_entries():
    if not LOG_PATH.exists():
        print(f"No log yet at {LOG_PATH} — nothing delegated has been recorded.")
        sys.exit(0)
    entries = []
    with open(LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"warning: skipping malformed log line: {line[:80]}", file=sys.stderr)
    return entries


def cost(tokens, tier):
    rate = BLENDED_RATE_PER_MTOK.get(tier)
    if rate is None:
        print(f"warning: unknown tier '{tier}', skipping its cost calculation", file=sys.stderr)
        return 0.0
    return tokens / 1_000_000 * rate


def summarize(entries, label="Overall"):
    by_tier = defaultdict(lambda: {"count": 0, "tokens": 0})
    actual_total = 0.0
    counterfactual_total = 0.0
    durations = []
    escalations = 0
    escalation_trackable = 0

    for e in entries:
        tier = e.get("tier", "unknown")
        tokens = e.get("tokens", 0)
        by_tier[tier]["count"] += 1
        by_tier[tier]["tokens"] += tokens
        actual_total += cost(tokens, tier)
        counterfactual_total += cost(tokens, BASELINE_TIER)
        if e.get("duration_ms") is not None:
            durations.append(e["duration_ms"])
        # Distinguish "field absent" (logged before the field existed) from "present and null"
        # (a real delegation that was not an escalation) — only the latter is a tracked zero.
        if "escalated_from" in e:
            escalation_trackable += 1
        if e.get("escalated_from"):
            escalations += 1

    print(f"\n=== {label} ({len(entries)} delegations) ===")
    for tier in sorted(by_tier):
        d = by_tier[tier]
        print(f"  {tier:8s} {d['count']:3d} calls, {d['tokens']:>9,} tokens")
    print(f"  Actual cost:            ${actual_total:.4f}")
    print(f"  Counterfactual ({BASELINE_TIER}):  ${counterfactual_total:.4f}")
    if counterfactual_total > 0:
        savings = counterfactual_total - actual_total
        pct = (1 - actual_total / counterfactual_total) * 100
        # Token-equivalent: what the money saved would have bought at the baseline tier's rate —
        # not a literal token-count difference, just the same dollar savings in a more intuitive unit.
        token_equiv = int(savings / (BLENDED_RATE_PER_MTOK[BASELINE_TIER] / 1_000_000))
        print(f"  Estimated savings:      ${savings:.4f}  ({pct:.1f}% reduction)")
        print(f"  Token-equivalent:       {token_equiv:,} {BASELINE_TIER} tokens "
              f"(what the savings would buy at {BASELINE_TIER}'s rate)")
    if durations:
        print(f"  Avg duration:           {sum(durations)/len(durations)/1000:.1f}s "
              f"(over {len(durations)} entries with duration recorded)")
    # Always print this, including when it is zero — a zero escalation rate is the single most
    # informative number here, and hiding it (as this line used to, behind `if escalations:`)
    # left savings looking like an unqualified win. It is not: savings only measures that work
    # moved to cheaper tiers, never that the results held up.
    if escalation_trackable:
        print(f"  Escalations:            {escalations} of {escalation_trackable} trackable "
              f"({'none recorded — see --audit' if not escalations else 'retries after a cheaper tier fell short'})")


# Effort thresholds for the heuristics below, set from the observed shape of a real log rather
# than picked out of the air: haiku delegations there clustered at 1-25 tool calls, while sonnet
# routinely ran 20-55. A haiku run at or above UNDER_TIER_TOOLS therefore sits squarely in the
# effort range of the tier above it. Re-derive these if the mix shifts; they are a starting point,
# not a constant of nature.
UNDER_TIER_TOOLS = 20
UNDER_TIER_SECONDS = 300
OVER_TIER_TOOLS = 2
OVER_TIER_SECONDS = 30
CHEAP_TIERS = ("haiku",)
EXPENSIVE_TIERS = ("opus", "fable")


def audit(entries):
    """Flag delegations whose effort looks mismatched to the tier that ran them.

    Deliberately not a verdict: the log records what a delegation cost and how hard it worked,
    never whether its output was any good. A flag here means "worth a look", nothing more.
    """
    under, over = [], []
    for e in entries:
        tier = e.get("tier")
        tools = e.get("tool_uses")
        dur_ms = e.get("duration_ms")
        if tools is None or dur_ms is None:
            continue  # logged before effort fields existed; nothing to judge
        seconds = dur_ms / 1000
        if tier in CHEAP_TIERS and (tools >= UNDER_TIER_TOOLS or seconds >= UNDER_TIER_SECONDS):
            under.append((e, tools, seconds))
        elif tier in EXPENSIVE_TIERS and tools <= OVER_TIER_TOOLS and seconds <= OVER_TIER_SECONDS:
            over.append((e, tools, seconds))

    print("\n=== Tier audit (heuristic — candidates for review, not verdicts) ===")

    def show(rows, heading, note):
        print(f"\n  {heading}")
        print(f"  {note}")
        if not rows:
            print("    (none)")
            return
        for e, tools, seconds in sorted(rows, key=lambda r: r[0].get("timestamp", "")):
            print(f"    {e.get('tier','?'):7s} {tools:3d} tools {seconds:6.0f}s  "
                  f"{e.get('task','')[:56]}")

    show(under, "Suspected under-tier (cheap tier, heavy effort):",
         "Long autonomous runs are where a higher tier tends to earn its cost. Check whether the\n"
         "  output actually held up — if it did, the cheap tier was the right call and this is noise.")
    show(over, "Suspected over-tier (expensive tier, trivial effort):",
         "Finished fast with almost no tool use — likely cheaper tier territory next time.")

    print("\n  Reminder: this looks only at effort, never at output quality. Nothing in the log\n"
          "  records whether a delegation produced a good answer, so a clean audit is not\n"
          "  evidence that every tier choice was correct.")


def main():
    entries = load_entries()
    if not entries:
        print("Log exists but is empty.")
        return

    summarize(entries, "Overall")

    if "--audit" in sys.argv:
        audit(entries)

    if "--by-month" in sys.argv:
        by_month = defaultdict(list)
        for e in entries:
            month = e.get("timestamp", "")[:7]  # YYYY-MM
            by_month[month].append(e)
        for month in sorted(by_month):
            summarize(by_month[month], month)

    if "--by-day" in sys.argv:
        by_day = defaultdict(list)
        for e in entries:
            day = e.get("timestamp", "")[:10]  # YYYY-MM-DD
            by_day[day].append(e)
        for day in sorted(by_day):
            summarize(by_day[day], day)

    if "--by-host" in sys.argv:
        by_host = defaultdict(list)
        for e in entries:
            by_host[e.get("hostname", "(unknown)")].append(e)
        for host in sorted(by_host):
            summarize(by_host[host], f"host: {host}")

    if "--by-user" in sys.argv:
        by_user = defaultdict(list)
        for e in entries:
            by_user[e.get("username", "(unknown)")].append(e)
        for user in sorted(by_user):
            summarize(by_user[user], f"user: {user}")

    if "--by-project" in sys.argv:
        by_project = defaultdict(list)
        for e in entries:
            by_project[e.get("project", "(unknown)")].append(e)
        for project in sorted(by_project):
            summarize(by_project[project], f"project: {project}")


if __name__ == "__main__":
    main()
