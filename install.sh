#!/bin/zsh
# Builds Sttark Claude Kit from this folder, puts it in /Applications and opens it.
# Most people don't need this: download the app from the Releases page instead, and it updates itself.
set -e
cd "$(dirname "$0")"
./build.sh
pkill -x SttarkClaudeKit 2>/dev/null || true
rm -rf /Applications/SttarkClaudeKit.app ~/Applications/SttarkClaudeKit.app
cp -R build/SttarkClaudeKit.app /Applications/
open /Applications/SttarkClaudeKit.app
echo "Installed. Look for the gauge in the menu bar."
