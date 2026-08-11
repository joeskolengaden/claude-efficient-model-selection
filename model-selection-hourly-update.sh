#!/usr/bin/env bash
# Runs the delegation-log extractor, then syncs the result to the private GitHub backup repo, in
# that order — combined into one job so extraction always completes before sync reads the file,
# rather than two independently-scheduled jobs that could race or drift apart over time.
#
# Triggered hourly (launchd), plus once immediately on login/restart (RunAtLoad in the plist), AND
# once after every single Agent/Workflow delegation (a PostToolUse hook — see
# model-selection-hook-install.py) so the GitHub log stays close to real-time instead of waiting
# up to an hour. That last trigger point is why the lock below exists: parallel delegations in one
# turn each fire their own PostToolUse event, which would otherwise mean several copies of this
# script racing on the same state file and log — one process's "new content since offset X" read
# could double-count another's, since the extractor's own offset bookkeeping isn't itself safe
# against concurrent writers. The lock makes concurrent triggers collapse into one effective run
# rather than corrupt anything: whichever process gets here first runs normally; any other
# already-in-flight process exits immediately, since the data it would have synced is already on
# disk in the transcript and will be picked up by the run that's currently in progress, or by the
# hourly job as a backstop either way — nothing is lost, just deferred a few seconds at most.
set -euo pipefail

TOOLS_DIR="$HOME/.claude/tools"
LOG="$TOOLS_DIR/model-selection-hourly-update.log"
LOCKDIR="$TOOLS_DIR/.model-selection-hourly-update.lock"

if ! mkdir "$LOCKDIR" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "$LOCKDIR"' EXIT

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

log "--- run start ---"

if [ -f "$TOOLS_DIR/model-selection-log-extract.py" ]; then
    if /usr/bin/python3 "$TOOLS_DIR/model-selection-log-extract.py" >> "$LOG" 2>&1; then
        log "extract: ok"
    else
        log "extract: FAILED (see above) — continuing to sync whatever's already logged"
    fi
else
    log "extract: skipped, script not found at $TOOLS_DIR/model-selection-log-extract.py"
fi

if [ -f "$TOOLS_DIR/model-selection-log-sync/sync.sh" ]; then
    if "$TOOLS_DIR/model-selection-log-sync/sync.sh"; then
        log "sync: ok"
    else
        log "sync: FAILED (see model-selection-log-sync/sync.log)"
    fi
else
    log "sync: skipped, not set up at $TOOLS_DIR/model-selection-log-sync/"
fi

log "--- run end ---"
