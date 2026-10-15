#!/bin/zsh
# Takes the effort hook out of Claude Code's settings and removes the app. Leaves the log.
H="$HOME/Library/Application Support/SttarkEffort/hooks/install-hooks.py"
[[ -f $H ]] && /usr/bin/python3 "$H" --remove
pkill -x SttarkEffort 2>/dev/null || true
rm -rf ~/Applications/SttarkEffort.app /Applications/SttarkEffort.app "$HOME/Library/Application Support/SttarkEffort"
echo "Removed. Sessions keep whatever effort they have now."
