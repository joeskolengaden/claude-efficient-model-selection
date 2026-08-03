#!/usr/bin/env bash
# Merges this account's local delegation log into the shared private repo and pushes.
#
# Multi-contributor safe: does NOT just copy-and-overwrite (that would let one contributor's
# push silently clobber another's, or non-fast-forward-fail once more than one person is
# pushing). Instead: pull the latest remote state, take the deduplicated union of
# (remote entries) + (this account's local entries), write that back, and push — retrying the
# pull/merge/push cycle if someone else pushed in between. Set union is a safe merge for
# append-only JSONL data: order doesn't matter, and an exact-duplicate line (same contributor's
# entry already present remotely) collapses to one copy rather than being counted twice.
#
# Deliberately does NOT pull the merged team-wide result back into this account's own personal
# log at ~/.claude/tools/model-selection-log.jsonl — that file stays this account's own
# delegations only. The merged, team-wide view lives in the shared repo (and its dashboard),
# not mixed into anyone's personal local file.
set -euo pipefail
cd "$(dirname "$0")"

SRC="$HOME/.claude/tools/model-selection-log.jsonl"
LOG="$HOME/.claude/tools/model-selection-log-sync/sync.log"
MAX_RETRIES=5

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

if [ ! -f "$SRC" ]; then
    log "no source log at $SRC yet, nothing to sync"
    exit 0
fi

attempt=0
while [ "$attempt" -lt "$MAX_RETRIES" ]; do
    attempt=$((attempt + 1))

    git fetch -q origin main
    git reset -q --hard origin/main

    python3 - "$SRC" <<'PYEOF'
import sys
from pathlib import Path

src_path = Path(sys.argv[1])
remote_path = Path("model-selection-log.jsonl")

remote_lines = remote_path.read_text().splitlines() if remote_path.exists() else []
local_lines = src_path.read_text().splitlines() if src_path.exists() else []

# Deduplicated union, preserving remote's existing order and appending genuinely new lines.
seen = set(l.strip() for l in remote_lines if l.strip())
merged = [l for l in remote_lines if l.strip()]
for line in local_lines:
    line = line.strip()
    if line and line not in seen:
        merged.append(line)
        seen.add(line)

remote_path.write_text("\n".join(merged) + ("\n" if merged else ""))
PYEOF

    if [ -z "$(git status --porcelain model-selection-log.jsonl)" ]; then
        log "no new entries to contribute (attempt $attempt)"
        exit 0
    fi

    git add model-selection-log.jsonl
    git commit -q -m "merge from $(whoami)@$(hostname -s 2>/dev/null || hostname) $(date '+%Y-%m-%d %H:%M:%S')"

    if git push -q origin main 2>>"$LOG"; then
        log "pushed successfully (attempt $attempt)"
        exit 0
    fi

    log "push rejected (attempt $attempt of $MAX_RETRIES) — likely a concurrent push from another contributor, retrying"
    sleep $((RANDOM % 5 + 1))
done

log "gave up after $MAX_RETRIES attempts — push kept losing the race against concurrent contributors"
exit 1
