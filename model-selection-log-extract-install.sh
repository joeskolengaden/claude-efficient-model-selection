#!/usr/bin/env bash
# Installs the daily extraction job for THIS macOS account. Safe to run under any user account —
# launchd plists need literal paths (no $HOME expansion), so this generates one scoped to
# whoever runs it, rather than shipping a plist hardcoded to one person's home directory.
set -euo pipefail

TOOLS_DIR="$HOME/.claude/tools"
PLIST_LABEL="com.$(whoami).model-selection-log-extract"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ ! -f "$TOOLS_DIR/model-selection-log-extract.py" ]; then
    echo "error: $TOOLS_DIR/model-selection-log-extract.py not found — install that first." >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>${TOOLS_DIR}/model-selection-log-extract.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>20</integer>
        <key>Minute</key>
        <integer>45</integer>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${TOOLS_DIR}/model-selection-log-extract.out.log</string>
    <key>StandardErrorPath</key>
    <string>${TOOLS_DIR}/model-selection-log-extract.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH"

# Unload first in case this is a reinstall/update
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed ${PLIST_LABEL}, scoped to $HOME"
echo "Runs daily at 20:45, and once immediately (RunAtLoad) — this covers a missed day: if the"
echo "Mac was asleep/off at 20:45, the next login or restart triggers an immediate catch-up run,"
echo "and the extractor's own incremental scan picks up everything since its last successful run"
echo "regardless of how long the gap was."
