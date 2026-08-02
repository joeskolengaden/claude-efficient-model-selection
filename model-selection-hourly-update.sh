#!/usr/bin/env bash
# Runs the delegation-log extractor, then syncs the result to the private GitHub backup repo, in
# that order — combined into one job so extraction always completes before sync reads the file,
# rather than two independently-scheduled jobs that could race or drift apart over time.
#
# Triggered hourly, plus once immediately on login/restart (RunAtLoad in the plist) so a period
# the machine was asleep or off gets caught up right away instead of silently skipped — both
# steps are already incremental/idempotent (the extractor only reads new transcript content since
# its last run; the sync script only commits+pushes when the file actually changed), so running
# this after an arbitrarily long gap just processes everything that piled up in one pass.
set -euo pipefail

TOOLS_DIR="$HOME/.claude/tools"
LOG="$TOOLS_DIR/model-selection-hourly-update.log"

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
