#!/usr/bin/env python3
"""
Regenerates the README's dashboard section from model-selection-log.jsonl. Run by the
update-dashboard GitHub Action on every push that changes the log; safe to run locally too.

Everything between the DASHBOARD:START / DASHBOARD:END markers in README.md is replaced on each
run — content outside those markers (the repo description, field docs) is left untouched.
"""
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG_PATH = Path("model-selection-log.jsonl")
README_PATH = Path("README.md")

START_MARKER = "<!-- DASHBOARD:START -->"
END_MARKER = "<!-- DASHBOARD:END -->"

BLENDED_RATE_PER_MTOK = {"haiku": 3.0, "sonnet": 9.0, "opus": 15.0, "fable": 30.0}
BASELINE_TIER = "opus"

# (label, timedelta or None for all-time), in display order.
WINDOWS = [
    ("Last 1 hour", timedelta(hours=1)),
    ("Last 24 hours", timedelta(hours=24)),
    ("Last 7 days", timedelta(days=7)),
    ("Last 30 days", timedelta(days=30)),
    ("Last 1 year", timedelta(days=365)),
    ("All time", None),
]


def cost(tokens, tier):
    return tokens / 1_000_000 * BLENDED_RATE_PER_MTOK.get(tier, BLENDED_RATE_PER_MTOK[BASELINE_TIER])


def parse_ts(ts):
    if not isinstance(ts, str) or not ts:
        return None
    try:
        # Handles both with and without milliseconds, and a trailing "Z".
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def window_table(entries, now):
    lines = [
        "### Rolling-window stats", "",
        "| Window | Delegations | Actual Cost | Counterfactual | Savings | Savings % |",
        "|---|---|---|---|---|---|",
    ]
    for label, delta in WINDOWS:
        cutoff = now - delta if delta is not None else None
        windowed = []
        for e in entries:
            ts = parse_ts(e.get("timestamp"))
            if ts is None:
                continue  # entries with no parseable timestamp can't be placed in a rolling window
            if cutoff is not None and ts < cutoff:
                continue
            windowed.append(e)

        actual = sum(cost(e.get("tokens", 0), e.get("tier", "unknown")) for e in windowed)
        counterfactual = sum(cost(e.get("tokens", 0), BASELINE_TIER) for e in windowed)
        if counterfactual > 0:
            savings = counterfactual - actual
            pct = (1 - actual / counterfactual) * 100
            savings_str, pct_str = f"${savings:.4f}", f"{pct:.1f}%"
        else:
            savings_str = pct_str = "—"
        lines.append(
            f"| {label} | {len(windowed)} | ${actual:.4f} | ${counterfactual:.4f} "
            f"| {savings_str} | {pct_str} |"
        )
    lines.append("")
    lines.append(
        "_Windows are rolling from the moment this dashboard was last generated, not calendar-"
        "aligned (e.g. \"last 24 hours\" is a trailing 24h span, not \"today\"). Entries with no "
        "parseable timestamp are excluded from every window but still counted in Overall below._"
    )
    lines.append("")
    return "\n".join(lines)


def tier_comparison_table(entries):
    actual = sum(cost(e.get("tokens", 0), e.get("tier", "unknown")) for e in entries)

    lines = [
        "### Actual spend vs. an all-one-tier baseline", "",
        "| If everything ran on... | That baseline's cost | Actual cost | Difference | Difference % |",
        "|---|---|---|---|---|",
    ]
    for tier in ("haiku", "sonnet", "opus", "fable"):
        baseline = sum(cost(e.get("tokens", 0), tier) for e in entries)
        if baseline > 0:
            diff = baseline - actual
            pct = diff / baseline * 100
            diff_str = f"+${diff:.4f}" if diff >= 0 else f"-${abs(diff):.4f}"
            pct_str = f"{pct:+.1f}%"
        else:
            diff_str = pct_str = "—"
        label = f"{tier} (documented no-skill default)" if tier == BASELINE_TIER else tier
        lines.append(f"| {label} | ${baseline:.4f} | ${actual:.4f} | {diff_str} | {pct_str} |")
    lines.append("")
    lines.append(
        "_Difference = that tier's baseline cost minus actual cost. Positive means actual spend "
        "came in under that baseline (real savings); negative means actual spend exceeded it — "
        "expected for the haiku row, since some delegations genuinely needed more than haiku "
        "provides. All-time totals, not windowed. Opus is used as the headline savings figure "
        "elsewhere on this page because it's the documented no-skill default for delegated work, "
        "not because it's the most expensive tier (fable is)._"
    )
    lines.append("")
    return "\n".join(lines)


def load_entries():
    if not LOG_PATH.exists():
        return []
    entries = []
    for line in LOG_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def summary_block(entries, title):
    by_tier = defaultdict(lambda: {"count": 0, "tokens": 0})
    actual = counterfactual = 0.0
    for e in entries:
        tier = e.get("tier", "unknown")
        tokens = e.get("tokens", 0)
        by_tier[tier]["count"] += 1
        by_tier[tier]["tokens"] += tokens
        actual += cost(tokens, tier)
        counterfactual += cost(tokens, BASELINE_TIER)

    lines = [f"### {title} ({len(entries)} delegations)", "", "| Tier | Calls | Tokens |", "|---|---|---|"]
    for tier in sorted(by_tier):
        d = by_tier[tier]
        lines.append(f"| {tier} | {d['count']} | {d['tokens']:,} |")
    lines.append("")
    lines.append(f"Actual: **${actual:.4f}** · Counterfactual (all {BASELINE_TIER}): ${counterfactual:.4f}")
    if counterfactual > 0:
        savings = counterfactual - actual
        pct = (1 - actual / counterfactual) * 100
        # Token-equivalent savings: what the money saved would have bought at the baseline
        # tier's rate — not a literal token-count difference (different tiers don't necessarily
        # use the same number of tokens for the same task), but a way to express the same dollar
        # savings in a more intuitive unit.
        token_equiv = int(savings / (BLENDED_RATE_PER_MTOK[BASELINE_TIER] / 1_000_000))
        lines.append(f" · Savings: **${savings:.4f} ({pct:.1f}%)** — "
                      f"equivalent to **{token_equiv:,} {BASELINE_TIER} tokens** "
                      f"(what the savings would buy at {BASELINE_TIER}'s rate)")
    lines.append("")
    return "\n".join(lines)


def build_dashboard(entries):
    if not entries:
        return "_No delegations logged yet._\n"

    now = datetime.now(timezone.utc)
    parts = [window_table(entries, now), summary_block(entries, "Overall"), tier_comparison_table(entries)]

    by_user = defaultdict(list)
    for e in entries:
        by_user[e.get("username", "(unknown)")].append(e)
    # Always show the per-contributor breakdown, even with only one contributor — the dashboard
    # should reflect however many people are actually in the data, not hide the individual view
    # until a second contributor shows up.
    parts.append("## By contributor\n")
    for user in sorted(by_user):
        parts.append(summary_block(by_user[user], f"@{user}"))

    parts.append(f"_Last generated from {len(entries)} entries. Regenerated automatically on every "
                  f"push to `model-selection-log.jsonl` — do not edit this section by hand, edits "
                  f"will be overwritten on the next push._")
    return "\n".join(parts)


def main():
    entries = load_entries()
    dashboard = build_dashboard(entries)

    if README_PATH.exists():
        readme = README_PATH.read_text()
    else:
        readme = f"# claude-model-selection-log\n\n{START_MARKER}\n{END_MARKER}\n"

    if START_MARKER not in readme or END_MARKER not in readme:
        print("error: README.md is missing DASHBOARD:START/END markers", file=sys.stderr)
        sys.exit(1)

    new_readme = re.sub(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER),
        f"{START_MARKER}\n\n{dashboard}\n\n{END_MARKER}",
        readme,
        flags=re.DOTALL,
    )
    README_PATH.write_text(new_readme)
    print("dashboard regenerated")


if __name__ == "__main__":
    main()
