#!/bin/zsh
# claude-window: lets Claude use your signed-in Chrome without taking your screen.
#
# Works only in the Chrome window named "Claude" that Sttark Claude Kit opens ("Claude window in Chrome" in its
# menu). Each Claude Code session gets its own tab there, so sessions never move each other's pages. A session's
# tab becomes the window's front tab whenever the session uses it, so sites that only work in the front tab do.
# It never opens windows and never activates Chrome: a new window, or Chrome coming forward, takes the screen
# from whatever you're typing in. Opening, switching and closing tabs, and running JavaScript, don't.
#
#   claude-window go <url>      open a page in this session's tab, wait for it to load, print its title and URL
#   claude-window url           print the current title and URL
#   claude-window text [chars]  print the page's visible text (first 20000 characters unless given)
#   claude-window js '<code>'   run JavaScript in the page and print the result
#   claude-window done          close this session's tab (when you're finished with the browser)
#
# A tab nobody closed is closed for you once its session's process ends or it goes unused for 30 minutes
# (Sttark Claude Kit runs `claude-window cleanup` every 30 seconds).
#
# Needs Chrome's View > Developer > Allow JavaScript from Apple Events.
set -uo pipefail
cmd=${1:-}
[[ -n $cmd ]] || { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

# One file per session: "<tab id> <session process id>". The file's time is the tab's last use.
tabs="$HOME/Library/Application Support/SttarkClaudeKit/claude-window-tabs"
session=${CLAUDE_CODE_SESSION_ID:-${CLAUDE_PID:-terminal}}
mine="$tabs/$session"
unused_limit=1800  # seconds

if ! pgrep -xq "Google Chrome"; then
  [[ $cmd == cleanup ]] && { rm -rf "$tabs"; exit 0; }  # Chrome quit, so every tab is gone
  echo "Chrome isn't open. Sttark Claude Kit starts it and reopens the Claude window once no one has used the keyboard or mouse for a minute, or open Chrome and click Open Claude window in its menu." >&2; exit 1
fi

chrome() {  # chrome <op> [tab id] [javascript]: work on the Claude window; never activates Chrome
  osascript - "$@" <<'OSA'
on run argv
  set op to item 1 of argv
  tell application "Google Chrome"
    set ws to (every window whose given name is "Claude")
    if (count of ws) is 0 then error "NO_CLAUDE_WINDOW"
    set w to item 1 of ws
    set ids to id of every tab of w
    if op is "ids" then
      set AppleScript's text item delimiters to " "
      return ids as text
    end if
    if op is "new" then
      -- a plain new tab: giving it an address here (or setting a tab's URL) brings Chrome to the front
      set t to make new tab at end of tabs of w
      return id of t
    end if
    set n to 0
    repeat with i from 1 to count of ids
      if item i of ids is (item 2 of argv) then set n to i
    end repeat
    if op is "close" then
      if n is 0 then return ""
      -- the window's last tab stays, blank, so the window stays open
      if (count of ids) > 1 then
        close tab n of w
      else
        execute tab n of w javascript "location.href = 'about:blank'"
      end if
      return ""
    end if
    if n is 0 then error "NO_TAB"
    if active tab index of w is not n then set active tab index of w to n
    return execute (tab n of w) javascript (item 3 of argv)
  end tell
end run
OSA
}

explain() {  # turn a failure from chrome() into a plain message
  case $1 in
    *NO_CLAUDE_WINDOW*) echo "There's no Chrome window named Claude. Sttark Claude Kit reopens it once no one has used the keyboard or mouse for a minute, or click Open Claude window in its menu." >&2 ;;
    *"Apple Events"*|*"JavaScript"*) echo "Chrome blocks scripts: turn on View > Developer > Allow JavaScript from Apple Events." >&2 ;;
    *) echo "$1" >&2 ;;
  esac
}

new_tab() {  # give this session a tab; $1 is the closed tab it replaces, if any
  local id
  mkdir -p "$tabs" && : >> "$tabs/.lock"
  zmodload zsh/system
  zsystem flock -t 20 "$tabs/.lock" || return 1  # two steps of one session at once still get one tab
  if [[ ! -f $mine || $(cut -d' ' -f1 < "$mine") == ${1:-} ]]; then
    id=$(chrome new 2>&1) || { explain "$id"; return 1; }
    print -r -- "$id ${CLAUDE_PID:-}" > "$mine"
  fi
}

js() {  # run JavaScript in this session's tab, opening the tab first if the session has none
  local out rc tab
  [[ -f $mine ]] || ( new_tab ) || return 1
  tab=$(cut -d' ' -f1 < "$mine")
  out=$(chrome js "$tab" "$1" 2>&1); rc=$?
  if [[ $out == *NO_TAB* ]]; then
    echo "This session's tab had been closed, so it has a new, blank one." >&2
    ( new_tab "$tab" ) || return 1
    out=$(chrome js "$(cut -d' ' -f1 < "$mine")" "$1" 2>&1); rc=$?
  fi
  (( rc == 0 )) || { explain "$out"; return 1; }
  touch "$mine"
  print -r -- "$out"
}

wait_loaded() {
  for i in {1..60}; do
    [[ $(js 'document.readyState' 2>/dev/null) == complete ]] && return 0
    sleep 0.5
  done
}

cleanup() {  # close tabs whose session's process ended or that went unused too long; forget tabs closed by hand
  [[ -d $tabs ]] || return 0
  local open now f id pid
  open=" $(chrome ids 2>/dev/null) " || { rm -rf "$tabs"; return 0; }  # no Claude window: its tabs are gone
  now=$(date +%s)
  for f in "$tabs"/*(N); do
    read -r id pid < "$f"
    if [[ $open != *" $id "* ]]; then
      rm -f "$f"
    elif [[ -n $pid ]] && ! kill -0 "$pid" 2>/dev/null || (( now - $(stat -f %m "$f") > unused_limit )); then
      chrome close "$id" >/dev/null 2>&1
      rm -f "$f"
    fi
  done
}

case $cmd in
  go)
    [[ -n ${2:-} ]] || { echo "usage: claude-window go <url>" >&2; exit 2; }
    url=$(/usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$2")
    old=$(js 'location.href') || exit 1
    js "location.href = $url; 'ok'" >/dev/null || exit 1
    # wait for the new page to replace the old one, then for it to finish loading
    for i in {1..40}; do [[ $(js 'location.href' 2>/dev/null) != "$old" ]] && break; sleep 0.25; done
    wait_loaded
    js 'document.title + "\n" + location.href' ;;
  url)  js 'document.title + "\n" + location.href' ;;
  text) js "document.body ? document.body.innerText.slice(0, ${2:-20000}) : ''" ;;
  js)   [[ -n ${2:-} ]] || { echo "usage: claude-window js '<code>'" >&2; exit 2; }; js "$2" ;;
  done)
    if [[ -f $mine ]]; then
      chrome close "$(cut -d' ' -f1 < "$mine")" >/dev/null 2>&1
      rm -f "$mine"
    fi
    echo "Closed this session's tab." ;;
  cleanup) cleanup ;;
  *)    echo "unknown command: $cmd (use go, url, text, js or done)" >&2; exit 2 ;;
esac
