#!/usr/bin/env bash
# Installs the efficient-model-selection enforcement hooks into ~/.claude/settings.json for THIS
# account. Thin wrapper around model-selection-hook-install.py, which does the actual read-merge-
# write (see that file's docstring for why these hooks exist and what they do). Safe to re-run —
# already-installed entries are left unchanged, and a conflicting hook you added yourself on the
# same event/matcher is reported, not overwritten.
set -euo pipefail

TOOLS_DIR="$HOME/.claude/tools"

if [ ! -f "$TOOLS_DIR/model-selection-hook-install.py" ]; then
    echo "error: $TOOLS_DIR/model-selection-hook-install.py not found — install that first." >&2
    exit 1
fi

python3 "$TOOLS_DIR/model-selection-hook-install.py"
