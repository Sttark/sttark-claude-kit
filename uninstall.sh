#!/bin/zsh
# Removes Sttark Effort and everything it set up: the hooks in Claude Code's settings, the Chrome
# approver, and the server for Claude app sessions if it was turned on from the app. Leaves the logs.
H="$HOME/Library/Application Support/SttarkEffort/hooks/install-hooks.py"
[[ -f $H ]] && /usr/bin/python3 "$H" --remove
for label in com.sttark.chrome-approver com.sttark.claude-rc; do
  launchctl bootout gui/$(id -u)/$label 2>/dev/null
  rm -f ~/Library/LaunchAgents/$label.plist
done
pkill -x SttarkEffort 2>/dev/null || true
rm -rf ~/Applications/SttarkEffort.app /Applications/SttarkEffort.app "$HOME/Library/Application Support/SttarkEffort"
echo "Removed. Sessions keep whatever effort they have now."
