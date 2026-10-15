#!/bin/zsh
# Builds Sttark Effort from this folder, puts it in /Applications and opens it.
# Most people don't need this: download the app from the Releases page instead, and it updates itself.
set -e
cd "$(dirname "$0")"
./build.sh
pkill -x SttarkEffort 2>/dev/null || true
rm -rf /Applications/SttarkEffort.app ~/Applications/SttarkEffort.app
cp -R build/SttarkEffort.app /Applications/
open /Applications/SttarkEffort.app
echo "Installed. Look for the gauge in the menu bar."
