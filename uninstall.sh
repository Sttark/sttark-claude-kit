#!/bin/zsh
# Removes Sttark Claude Kit and everything it set up: the hooks in Claude Code's settings, the Chrome
# approver, and the server for Claude app sessions if it was turned on from the app. Leaves the logs.
H="$HOME/Library/Application Support/SttarkClaudeKit/hooks/install-hooks.py"
[[ -f $H ]] && /usr/bin/python3 "$H" --remove
for label in com.sttark.chrome-approver com.sttark.claude-rc com.sttark.claude-profile-sync com.sttark.claude-stable; do
  launchctl bootout gui/$(id -u)/$label 2>/dev/null
  rm -f ~/Library/LaunchAgents/$label.plist
done
pkill -x SttarkClaudeKit 2>/dev/null || true
rm -rf ~/.local/share/claude/stable ~/.local/bin/claude-window
rm -rf ~/Applications/SttarkClaudeKit.app /Applications/SttarkClaudeKit.app "$HOME/Library/Application Support/SttarkClaudeKit"
echo "Removed. Sessions keep whatever effort they have now."
