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
    python3 model-selection-report.py            # full summary
    python3 model-selection-report.py --by-month  # also break down by month
    python3 model-selection-report.py --by-day    # also break down by day
    python3 model-selection-report.py --by-host   # also break down by hostname
    python3 model-selection-report.py --by-user   # also break down by username

Entries logged before hostname/os/username were added won't have those fields — they're grouped
under "(unknown)" in --by-host / --by-user output rather than dropped.
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

    for e in entries:
        tier = e.get("tier", "unknown")
        tokens = e.get("tokens", 0)
        by_tier[tier]["count"] += 1
        by_tier[tier]["tokens"] += tokens
        actual_total += cost(tokens, tier)
        counterfactual_total += cost(tokens, BASELINE_TIER)

    print(f"\n=== {label} ({len(entries)} delegations) ===")
    for tier in sorted(by_tier):
        d = by_tier[tier]
        print(f"  {tier:8s} {d['count']:3d} calls, {d['tokens']:>9,} tokens")
    print(f"  Actual cost:            ${actual_total:.4f}")
    print(f"  Counterfactual ({BASELINE_TIER}):  ${counterfactual_total:.4f}")
    if counterfactual_total > 0:
        savings = counterfactual_total - actual_total
        pct = (1 - actual_total / counterfactual_total) * 100
        print(f"  Estimated savings:      ${savings:.4f}  ({pct:.1f}% reduction)")


def main():
    entries = load_entries()
    if not entries:
        print("Log exists but is empty.")
        return

    summarize(entries, "Overall")

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


if __name__ == "__main__":
    main()
