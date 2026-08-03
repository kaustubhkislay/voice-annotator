#!/bin/sh
# Pull the voice-annotator companion window to the current workspace without
# switching to it. Used by the window-manager hotkey binding (see README).
wid=$(aerospace list-windows --all 2>/dev/null | awk -F'|' '/voice annotator/{gsub(/ /,"",$1); print $1; exit}')
ws=$(aerospace list-workspaces --focused 2>/dev/null)
if [ -n "$wid" ] && [ -n "$ws" ]; then
    aerospace move-node-to-workspace --window-id "$wid" "$ws" 2>/dev/null
fi
curl -s -m 2 -X POST http://localhost:8765/summon >/dev/null
