#!/usr/bin/env bash
# Installs the combined hourly extract+sync job for THIS macOS account. Safe under any account —
# launchd plists need literal paths (no $HOME expansion), so this generates one scoped to whoever
# runs it. Replaces the separate model-selection-log-extract / model-selection-log-sync jobs from
# earlier versions of this setup — unload those first if you have them installed:
#   launchctl unload ~/Library/LaunchAgents/com.$(whoami).model-selection-log-extract.plist
#   launchctl unload ~/Library/LaunchAgents/com.$(whoami).model-selection-log-sync.plist
set -euo pipefail

TOOLS_DIR="$HOME/.claude/tools"
PLIST_LABEL="com.$(whoami).model-selection-hourly-update"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ ! -f "$TOOLS_DIR/model-selection-hourly-update.sh" ]; then
    echo "error: $TOOLS_DIR/model-selection-hourly-update.sh not found — install that first." >&2
    exit 1
fi
chmod +x "$TOOLS_DIR/model-selection-hourly-update.sh"

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
        <string>${TOOLS_DIR}/model-selection-hourly-update.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${TOOLS_DIR}/model-selection-hourly-update.out.log</string>
    <key>StandardErrorPath</key>
    <string>${TOOLS_DIR}/model-selection-hourly-update.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH"

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "Installed ${PLIST_LABEL}, scoped to $HOME"
echo "Runs every 3600s (hourly), plus once immediately (RunAtLoad) on every login/restart of the"
echo "app that hosts this LaunchAgent, or of the Mac itself — that immediate run is what catches"
echo "up any previous data that piled up while the machine was asleep, off, or the job wasn't"
echo "loaded, since both steps (extract, sync) are incremental and safe to run after any gap."
