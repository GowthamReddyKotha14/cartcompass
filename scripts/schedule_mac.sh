#!/bin/sh
# Schedule `cartcompass track` once a day on macOS (launchd).
# If the Mac is asleep at that time, launchd runs it when the Mac wakes.
#   sh scripts/schedule_mac.sh            install (daily at 08:17)
#   sh scripts/schedule_mac.sh remove     uninstall
#   DRY_RUN=1 sh scripts/schedule_mac.sh  print the job without installing
set -e
LABEL=com.cartcompass.track
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$REPO/.venv/bin/python}"
HOUR="${HOUR:-8}"
MINUTE="${MINUTE:-17}"

if [ "$1" = "remove" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed daily tracking"
  exit 0
fi

JOB="<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$PY</string><string>-m</string><string>cartcompass</string><string>track</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$REPO/data/track.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/track.log</string>
</dict>
</plist>"

if [ -n "$DRY_RUN" ]; then
  echo "$JOB"
  exit 0
fi

[ -x "$PY" ] || { echo "No Python at $PY. Create the venv first: python3 -m venv .venv && .venv/bin/pip install -e ."; exit 1; }
mkdir -p "$REPO/data" "$(dirname "$PLIST")"
echo "$JOB" > "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "scheduled: cartcompass track daily at $HOUR:$(printf %02d "$MINUTE"), log in data/track.log"
