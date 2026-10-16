#!/bin/zsh
# claude-window: lets Claude use your signed-in Chrome without taking your screen.
#
# Works only in the Chrome window named "Claude" that Sttark Effort opens ("Claude window in Chrome" in its
# menu). It moves that window between pages and reads or acts on them by running JavaScript inside the page,
# which doesn't bring Chrome forward. It never opens tabs or windows and never activates Chrome, because both
# make Chrome jump in front of whatever you're typing in.
#
#   claude-window go <url>      open a page in the Claude window, wait for it to load, print its title and URL
#   claude-window url           print the current title and URL
#   claude-window text [chars]  print the page's visible text (first 20000 characters unless given)
#   claude-window js '<code>'   run JavaScript in the page and print the result
#
# Needs Chrome's View > Developer > Allow JavaScript from Apple Events.
set -uo pipefail
cmd=${1:-}
[[ -n $cmd ]] || { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
if ! pgrep -xq "Google Chrome"; then
  echo "Chrome isn't open. Open Chrome, then click Open Claude window in the Sttark Effort menu." >&2; exit 1
fi

run_js() {  # run JavaScript in the Claude window's tab; never activates Chrome
  osascript - "$1" <<'OSA'
on run argv
  tell application "Google Chrome"
    set ws to (every window whose given name is "Claude")
    if (count of ws) is 0 then error "NO_CLAUDE_WINDOW"
    return execute (active tab of (item 1 of ws)) javascript (item 1 of argv)
  end tell
end run
OSA
}

js() {
  local out
  out=$(run_js "$1" 2>&1) || {
    case $out in
      *NO_CLAUDE_WINDOW*) echo "There's no Chrome window named Claude. Click Open Claude window in the Sttark Effort menu." >&2 ;;
      *"Apple Events"*|*"JavaScript"*) echo "Chrome blocks scripts: turn on View > Developer > Allow JavaScript from Apple Events." >&2 ;;
      *) echo "$out" >&2 ;;
    esac
    return 1
  }
  print -r -- "$out"
}

wait_loaded() {
  for i in {1..60}; do
    [[ $(js 'document.readyState' 2>/dev/null) == complete ]] && return 0
    sleep 0.5
  done
}

case $cmd in
  go)
    [[ -n ${2:-} ]] || { echo "usage: claude-window go <url>" >&2; exit 2; }
    url=$(/usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$2")
    js "location.href = $url; 'ok'" >/dev/null || exit 1
    sleep 1; wait_loaded
    js 'document.title + "\n" + location.href' ;;
  url)  js 'document.title + "\n" + location.href' ;;
  text) js "document.body ? document.body.innerText.slice(0, ${2:-20000}) : ''" ;;
  js)   [[ -n ${2:-} ]] || { echo "usage: claude-window js '<code>'" >&2; exit 2; }; js "$2" ;;
  *)    echo "unknown command: $cmd (use go, url, text or js)" >&2; exit 2 ;;
esac
