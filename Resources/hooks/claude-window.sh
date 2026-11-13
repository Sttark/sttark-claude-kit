#!/bin/zsh
# claude-window: lets Claude use your signed-in Chrome without taking your screen.
#
# Works only in the Chrome window named "Claude" that Sttark Claude Kit opens ("Claude window in Chrome" in its
# menu). Each Claude Code session gets its own tab there, so sessions never move each other's pages. A session's
# tab becomes the window's front tab whenever the session uses it, so sites that only work in the front tab do.
# Opening, switching and closing tabs, and running JavaScript, leave Chrome behind whatever you're typing in;
# giving a tab its address by script brings Chrome forward, so this never does. The one step that brings Chrome
# forward is making a window: when the Claude window is gone (closed, Chrome quit, a restart), the next command
# makes it, starting Chrome hidden first if it isn't running, puts the app you were in back in front at once
# (Chrome is in front for less than half a second), then goes on.
#
#   claude-window go <url>      open a page in this session's tab, wait for it to load, print its title and URL
#   claude-window url           print the current title and URL
#   claude-window text [chars]  print the page's visible text (first 20000 characters unless given)
#   claude-window js '<code>'   run JavaScript in the page and print the result
#   claude-window done          close this session's tab (when you're finished with the browser)
#
# A tab nobody closed is closed for you once its session's process ends or it goes unused for 30 minutes
# (Sttark Claude Kit runs `claude-window cleanup` every 30 seconds; its Open Claude window runs `claude-window open`).
#
# Needs Chrome's View > Developer > Allow JavaScript from Apple Events.
#
# It talks to your own Chrome by its process id, so a Chrome that a test tool runs at the same time (Playwright,
# Puppeteer: started with --headless, --remote-debugging-…, --enable-automation or --user-data-dir) never gets
# the commands. Scripts that name "Google Chrome" go to whichever copy macOS picks, often the test one.
set -uo pipefail
cmd=${1:-}
[[ -n $cmd ]] || { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

# One file per session: "<tab id> <session process id>". The file's time is the tab's last use.
tabs="$HOME/Library/Application Support/SttarkClaudeKit/claude-window-tabs"
session=${CLAUDE_CODE_SESSION_ID:-${CLAUDE_PID:-terminal}}
mine="$tabs/$session"
unused_limit=1800  # seconds
chrome_id=com.google.Chrome
logfile="$HOME/Library/Logs/sttark-claude-kit.log"

log() { print -r -- "$(date '+%F %T') window $*" >> "$logfile" 2>/dev/null }

# The person's own Chrome: the main Google Chrome process that no test tool started. Several can run at once;
# "tell application" picks one of them, so every call here goes to this one by its process id.
cpid=""
find_chrome() {
  local p args
  cpid=""
  ps -axww -o pid=,args= | while read -r p args; do
    [[ $args == */Google\ Chrome.app/Contents/MacOS/Google\ Chrome || $args == */Google\ Chrome.app/Contents/MacOS/Google\ Chrome\ * ]] || continue
    [[ $args == *--headless* || $args == *--remote-debugging-* || $args == *--enable-automation* || $args == *--user-data-dir* || $args == *--test-type* ]] && continue
    cpid=$p
    break
  done
  [[ -n $cpid ]]
}

chrome_running() { find_chrome }

# Apple events to that one process, built by hand in JavaScript for Automation: AppleScript's "tell application"
# and JXA's Application() both choose a copy of Chrome by name, which can be a test tool's copy.
ae_lib=$(<"${0:A:h}/chrome-ae.js")  # the library, shared with profile-sync.py
jxa() { { print -r -- "$ae_lib"; cat } | osascript -l JavaScript - "$cpid" "$@" }  # script on stdin; run(argv) gets the pid first

front_app() {  # the bundle ID of the app in front
  lsappinfo info -only bundleid "$(lsappinfo front)" 2>/dev/null | sed -n 's/.*="\(.*\)"/\1/p'
}

open_window() {  # make the Claude window when it's gone, then put the app that was in front back at once
  local before after out back
  zmodload zsh/system
  mkdir -p "$tabs" && : >> "$tabs/.window-lock"
  zsystem flock -t 60 "$tabs/.window-lock" || return 1  # sessions asking at the same moment still get one window
  before=$(front_app)
  if ! chrome_running; then
    rm -f "$tabs"/*(N)  # Chrome quit, so every tab is gone
    # -n: a test tool's Chrome may be running, and without -n macOS would only hand the request to that one
    open -n -g -j -b "$chrome_id" || { log "Claude window: couldn't start Chrome"; return 1; }  # in the background, hidden
    for i in {1..60}; do
      chrome_running && jxa <<<'function run(a) { PID = Number(a[0]); return count("cwin") }' >/dev/null 2>&1 && break
      sleep 0.5
    done
    log "Chrome wasn't running; started it hidden"
  fi
  # Making a window brings Chrome forward (tested: a plain window, a minimized one and Chrome's --new-window all
  # do), so the app that was in front goes back right after. Only this step does it, and only when the window is gone.
  chrome_running || { log "Claude window: Chrome didn't start"; return 1; }
  out=$(jxa <<'JXA' 2>&1
function run(argv) {
  PID = Number(argv[0])
  if (claudeWindow()) return 'there'
  set(prop('GNam', make('cwin')), str('Claude'))
  return 'opened'
}
JXA
  )
  after=$(front_app) back=""
  if [[ -n $before && $before != "$chrome_id" && $after == "$chrome_id" ]]; then
    osascript -e "tell application id \"$before\" to activate" >/dev/null 2>&1
    back="; put $before back in front"
  fi
  case $out in
    there)  return 0 ;;
    opened) log "Claude window: opened$back" ;;
    *)      log "Claude window: couldn't open: $out"; return 1 ;;
  esac
}

if ! chrome_running; then
  [[ $cmd == cleanup ]] && { rm -rf "$tabs"; exit 0; }  # Chrome quit, so every tab is gone
  [[ $cmd == done ]] && { rm -f "$mine"; echo "Closed this session's tab."; exit 0; }
  [[ $cmd == exists ]] && { echo false; exit 0; }
  [[ $cmd == close-window ]] && exit 0
fi

chrome() {  # chrome <op> [tab id] [javascript]: work on the Claude window, making it first if it's gone
  local out rc
  [[ $1 == ids || $1 == close* || $1 == exists ]] || chrome_running || open_window
  out=$(chrome_raw "$@" 2>&1); rc=$?
  if [[ $out == *NO_CLAUDE_WINDOW* && $1 != ids && $1 != close* && $1 != exists ]] && open_window; then
    out=$(chrome_raw "$@" 2>&1); rc=$?
  fi
  if (( rc == 0 )); then print -r -- "$out"; else print -r -- "$out" >&2; fi
  return $rc
}

chrome_raw() {  # never activates Chrome
  [[ -n $cpid ]] || chrome_running || { echo "NO_CHROME"; return 1; }
  jxa "$@" <<'JXA'
function run(argv) {
  PID = Number(argv[0])
  var op = argv[1], w = claudeWindow()
  if (op === 'exists') return !!w
  if (op === 'close-window') { while (w) { send('core', 'clos', {'----': w}); w = claudeWindow() } return '' }
  if (!w) throw new Error('NO_CLAUDE_WINDOW')
  var ids = (get(prop('ID  ', every('CrTb', w))) || []).map(String)
  if (op === 'ids') return ids.join(' ')
  // a plain new tab: giving it an address here (or setting a tab's URL) brings Chrome to the front
  if (op === 'new') return String(get(prop('ID  ', make('CrTb', w))))
  var n = ids.indexOf(argv[2]) + 1, tab = nth('CrTb', w, n)
  if (op === 'close') {
    if (n === 0) return ''
    // the window's last tab stays, blank, so the window stays open
    if (ids.length > 1) send('core', 'clos', {'----': tab})
    else send('CrSu', 'ExJa', {'----': tab, JvSc: str("location.href = 'about:blank'")})
    return ''
  }
  if (n === 0) throw new Error('NO_TAB')
  if (get(prop('acTI', w)) !== n) set(prop('acTI', w), D.descriptorWithInt32(n))
  return show(val(send('CrSu', 'ExJa', {'----': tab, JvSc: str(argv[3])})))
}
// print a page's answer the way AppleScript did: lists joined with ", ", nothing as "missing value"
function show(v) {
  if (v === null || v === undefined) return 'missing value'
  if (Array.isArray(v)) return v.map(show).join(', ')
  if (typeof v === 'object') return Object.keys(v).map(function (k) { return k + ':' + show(v[k]) }).join(', ')
  return String(v)
}
JXA
}

explain() {  # turn a failure from chrome() into a plain message
  case $1 in
    *NO_CLAUDE_WINDOW*|*NO_CHROME*) echo "There's no Chrome window named Claude and making one failed; the Sttark Claude Kit log says why." >&2 ;;
    *"(-600)"*|*"(-609)"*) echo "Chrome quit or restarted while the command ran; run it again." >&2 ;;
    *"Executing JavaScript through AppleScript is turned off"*|*"Allow JavaScript from Apple Events"*) echo "Chrome blocks scripts: turn on View > Developer > Allow JavaScript from Apple Events." >&2 ;;
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
  open) open_window ;;
  exists) chrome exists ;;              # for the app: is the Claude window open?
  close-window) chrome close-window ;;  # for the app: the switch was turned off
  *)    echo "unknown command: $cmd (use go, url, text, js or done)" >&2; exit 2 ;;
esac
