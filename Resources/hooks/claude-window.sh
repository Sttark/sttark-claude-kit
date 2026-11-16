#!/bin/zsh
# claude-window: lets Claude use your signed-in Chrome without taking your screen.
#
# Each Claude Code session gets a Chrome window of its own, named "Claude", in your own profile, and each agent
# that the session starts (a subagent or a fork) gets a tab of its own in that window. So sessions never take each
# other's front tab, and sessions and agents that work at the same time never move, read or close each other's
# pages. Opening, switching and closing tabs, and running JavaScript, leave Chrome behind whatever you're typing
# in; giving a tab its address by script brings Chrome forward, so this never does. The one step that brings
# Chrome forward is making a window: once for a session, at its first use of the browser (and again only if that
# window is gone). It starts Chrome hidden first if it isn't running, puts the app you were in back in front at
# once (Chrome is in front for less than half a second; the log says how long), or, when you were in Chrome, the
# Chrome window you were in, then goes on.
#
#   claude-window go <url>      open a page in this session's tab, wait for it to load, print its title and URL
#   claude-window url           print the current title and URL
#   claude-window text [chars]  print the page's visible text (first 20000 characters unless given)
#   claude-window js '<code>'   run JavaScript in the page and print the result
#   claude-window done          close this session's tab (when you're finished with the browser)
#
# Run by an agent, each command works in the agent's own tab, with nothing to set, and done closes only that tab.
# The session and its agents share their window's front tab. What nobody closed is closed for you: an agent's tab
# when the agent stops, and any tab, then the window, once its session's process ends or it goes unused for 30
# minutes (Sttark Claude Kit runs `claude-window cleanup` every 30 seconds).
#
# Needs Chrome's View > Developer > Allow JavaScript from Apple Events.
#
# It talks to your own Chrome by its process id, so a Chrome that a test tool runs at the same time (Playwright,
# Puppeteer: started with --headless, --remote-debugging-…, --enable-automation or --user-data-dir) never gets
# the commands. Scripts that name "Google Chrome" go to whichever copy macOS picks, often the test one.
#
# For tests: STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log, and STTARK_WINDOW_DRY=1 keeps it
# from making the Claude window or starting Chrome (a command that needs the window then fails).
set -uo pipefail
cmd=${1:-}
[[ -n $cmd ]] || { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

# One file per tab: "<tab id> <session process id> <window id>". The file's time is the tab's last use. A
# session's tab is named for the session; an agent's tab is "<session>.<agent>".
kit="${STTARK_KIT_DIR:-$HOME/Library/Application Support/SttarkClaudeKit}"
tabs="$kit/claude-window-tabs"
session=${CLAUDE_CODE_SESSION_ID:-${CLAUDE_PID:-terminal}}
# Which agent runs this command. An agent's commands run in the session's own process, with the session's
# environment, so nothing there tells one agent from the next. The Kit's browser guard (browser-guard.py, a
# PreToolUse hook) knows the agent of each command, and puts "export CLAUDE_WINDOW_AGENT=<agent id>; " in front
# of every command an agent runs. So a script that the agent runs works in the agent's tab too.
agent_ok='^[A-Za-z0-9_-]{1,64}$'
agent=${CLAUDE_WINDOW_AGENT:-}
[[ $agent =~ $agent_ok ]] || agent=""
mine="$tabs/$session${agent:+.$agent}"
owner=session; [[ -n $agent ]] && owner=agent
unused_limit=1800  # seconds
chrome_id=com.google.Chrome
logfile="${STTARK_KIT_LOG:-$HOME/Library/Logs/sttark-claude-kit.log}"

log() { print -r -- "$(date '+%F %T') window $*" >> "$logfile" 2>/dev/null }

# The person's own Chrome: the main Google Chrome process that no test tool started. Several can run at once;
# "tell application" picks one of them, so every call here goes to this one by its process id.
# skipped lists the main Chrome processes passed over as a test tool's, with the flag that ruled each out, so the
# log can say why a second copy of Chrome was started.
cpid="" skipped=""
find_chrome() {
  local p args f flag
  cpid="" skipped=""
  ps -axww -o pid=,args= | while read -r p args; do
    [[ $args == */Google\ Chrome.app/Contents/MacOS/Google\ Chrome || $args == */Google\ Chrome.app/Contents/MacOS/Google\ Chrome\ * ]] || continue
    f=""
    for flag in --headless --remote-debugging- --enable-automation --user-data-dir --test-type; do
      [[ $args == *$flag* ]] && { f=$flag; break }
    done
    if [[ -n $f ]]; then
      skipped+="${skipped:+, }$p ($f)"
      continue
    fi
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

# Each session has a Chrome window of its own, named Claude, so no other session takes its front tab. The window's
# record is "<window id> <session process id> [<id of its first tab, until a tab record takes it>]" in
# claude-window-wins/<session>; the file's time is the window's last use. The session's agents get their tabs in it.
wins="$kit/claude-window-wins"
mywin="$wins/$session"

open_window() {  # make this session's window, then put back what was in front at once
  local before after out back started="" t0 t1 secs wid
  [[ -z ${STTARK_WINDOW_DRY:-} ]] || return 1  # a test never makes a window: that brings Chrome forward
  zmodload zsh/system zsh/datetime
  mkdir -p "$tabs" "$wins" && : >> "$tabs/.window-lock"
  zsystem flock -t 60 "$tabs/.window-lock" || return 1  # two steps of one session at once still get one window
  if [[ -f $mywin && ${1:-} != again ]]; then return 0; fi
  before=$(front_app)
  if ! chrome_running; then
    # a Chrome passed over here is not the person's (a test tool's flag); starting another copy can show it
    [[ -n $skipped ]] && log "Claude window: Chrome $skipped skipped as not the person's; starting another copy"
    rm -f "$tabs"/*(N) "$wins"/*(N)  # Chrome quit, so every tab and window is gone
    # -n: a test tool's Chrome may be running, and without -n macOS would only hand the request to that one
    open -n -g -j -b "$chrome_id" || { log "Claude window: couldn't start Chrome"; return 1; }  # in the background, hidden
    for i in {1..60}; do
      chrome_running && jxa <<<'function run(a) { PID = Number(a[0]); return count("cwin") }' >/dev/null 2>&1 && break
      sleep 0.5
    done
    log "Chrome wasn't running; started it hidden"
    started=1
  fi
  # Making a window brings Chrome forward (tested: a plain window, a minimized one and Chrome's --new-window all
  # do), so what was in front goes back right after. Only this step does it: once for a session, at its first use
  # of the browser, and again only if its window is gone. When the person was in Chrome itself, the window they
  # were in goes back in front of the new one (by its id, in the same Apple event script), so their typing goes on
  # there. The log says how long Chrome was in front.
  chrome_running || { log "Claude window: Chrome didn't start"; return 1; }
  t0=$EPOCHREALTIME
  out=$(jxa "$([[ $before == "$chrome_id" && -z $started ]] && echo back)" <<'JXA' 2>&1
function run(argv) {
  PID = Number(argv[0])
  var front = null
  if (argv[1] === 'back' && count('cwin') > 0) front = get(prop('ID  ', nth('cwin', null, 1)))
  var w = make('cwin')
  set(prop('GNam', w), str('Claude'))
  var ids = get(prop('ID  ', w)) + ' ' + String((get(prop('ID  ', every('CrTb', w))) || [''])[0])
  if (front === null) return 'opened ' + ids
  try {
    set(prop('pidx', obj('cwin', null, 'ID  ', D.descriptorWithInt32(front))), D.descriptorWithInt32(1))
    return 'opened-back ' + ids
  } catch (e) { return 'opened-unback ' + ids + ' ' + e.message }
}
JXA
  )
  after=$(front_app) back=""
  if [[ -n $before && $before != "$chrome_id" && $after == "$chrome_id" ]]; then
    osascript -e "tell application id \"$before\" to activate" >/dev/null 2>&1
    back="; put $before back in front"
  fi
  t1=$EPOCHREALTIME
  secs=$(printf '%.1f' $(( t1 - t0 )))
  case $out in
    opened\ *|opened-back\ *|opened-unback\ *) ;;
    *) log "Claude window: couldn't open: $out"; return 1 ;;
  esac
  wid=${${=out}[2]}
  print -r -- "$wid ${CLAUDE_PID:-} ${${=out}[3]}" > "$mywin"
  case $out in
    opened\ *)        if [[ -n $back ]]; then log "Claude window: opened for a session; Chrome was in front for at most $secs s$back"
                      else log "Claude window: opened for a session; Chrome did not stay in front"; fi ;;
    opened-back\ *)   log "Claude window: opened for a session; put the person's own Chrome window back in front after at most $secs s" ;;
    opened-unback\ *) log "Claude window: opened for a session; couldn't put the person's own Chrome window back in front: ${${=out}[4,-1]}" ;;
  esac
}

if ! chrome_running; then
  [[ $cmd == cleanup ]] && { rm -rf "$tabs" "$wins"; exit 0; }  # Chrome quit, so every tab and window is gone
  [[ $cmd == done ]] && { rm -f "$mine"; echo "Closed this $owner's tab."; exit 0; }
  [[ $cmd == agent-done && ${2:-} =~ $agent_ok ]] && { rm -f "$tabs"/*."$2"(N); exit 0; }
  [[ $cmd == exists ]] && { echo false; exit 0; }
  [[ $cmd == close-window ]] && { rm -rf "$wins"; exit 0; }
fi

chrome() {  # chrome <op> [window id] [tab id] [javascript]; never activates Chrome
  [[ -n $cpid ]] || chrome_running || { echo "NO_CHROME" >&2; return 1; }
  jxa "$@" <<'JXA'
function run(argv) {
  PID = Number(argv[0])
  var op = argv[1]
  if (op === 'exists') return claudeWindows().length > 0
  if (op === 'wins') return claudeWindows().join(' ')
  if (op === 'close-window') { claudeWindows().forEach(closeWin); return '' }
  if (op === 'close-win') { if (alive(argv[2])) closeWin(argv[2]); return '' }
  if (op === 'close-unowned') {  // argv[2]: the window ids in records; argv[3]: the tab ids in records
    var owned = (argv[2] || '').split(' '), kept = (argv[3] || '').split(' '), n = 0
    claudeWindows().forEach(function (i) {
      if (owned.indexOf(i) >= 0) return
      var t = []; try { t = tabIds(win(i)) } catch (e) { return }
      if (t.some(function (x) { return kept.indexOf(x) >= 0 })) return
      closeWin(i); n++
    })
    return String(n)
  }
  if (op === 'ids') return claudeWindows().map(function (i) { try { return tabIds(win(i)).join(' ') } catch (e) { return '' } }).join(' ')
  var wid = argv[2]
  if (op === 'new') {
    if (!alive(wid)) throw new Error('NO_CLAUDE_WINDOW')
    // a plain new tab: giving it an address here (or setting a tab's URL) brings Chrome to the front
    return String(get(prop('ID  ', make('CrTb', win(wid)))))
  }
  // The tab by its id, never by its place in the window: agents open and close tabs at the same moment, so the
  // place a tab had in one Apple event can be another tab's place in the next. A record from before each
  // session had its own window has no window id: then the tab is looked for in every Claude window, and it stays
  // there with its page until its owner closes it.
  var id = argv[3], w = null, ids = []
  var where = wid ? (alive(wid) ? [wid] : []) : claudeWindows()
  if (/^[0-9]+$/.test(id)) where.forEach(function (i) {
    if (w) return
    var t = []; try { t = tabIds(win(i)) } catch (e) {}
    if (t.indexOf(id) >= 0) { w = win(i); ids = t }
  })
  var tab = w ? obj('CrTb', w, 'ID  ', D.descriptorWithInt32(Number(id))) : null
  if (op === 'close') {
    if (!w) return ''
    quiet(tab)
    // the window's last tab stays, blank, so the window stays open until the session ends
    if (ids.length > 1) send('core', 'clos', {'----': tab})
    else send('CrSu', 'ExJa', {'----': tab, JvSc: str("location.href = 'about:blank'")})
    return ''
  }
  if (!w) throw new Error(wid && !where.length ? 'NO_CLAUDE_WINDOW' : 'NO_TAB')
  try {
    if (op === 'quiet') { quiet(tab); return '' }
    front(w, id)
    return show(val(send('CrSu', 'ExJa', {'----': tab, JvSc: str(argv[4])})))
  } catch (e) {
    var gone = false  // -1728: no such object. The tab was closed after the list was read.
    if (/\(-1728\)/.test(e.message)) try { gone = tabIds(w).indexOf(id) < 0 } catch (x) { gone = true }
    throw gone ? new Error('NO_TAB') : e
  }
}
function win(i) { return obj('cwin', null, 'ID  ', D.descriptorWithInt32(Number(i))) }
function alive(i) { try { return /^[0-9]+$/.test(String(i)) && get(prop('GNam', win(i))) === 'Claude' } catch (e) { return false } }
function claudeWindows() {  // the ids of the windows named Claude
  var ids = (get(prop('ID  ', every('cwin'))) || []).map(String)
  return ids.filter(alive)
}
// A page can ask "Leave site? Changes you made may not be saved" when its tab closes or goes to another address
// (a beforeunload handler). That dialog shows on the person's screen and waits for them. So before each close and
// each address change, the page's handlers are made harmless: the property is cleared, and a beforeunload event
// can no longer be answered (its preventDefault and returnValue do nothing), whoever listens for it.
var QUIET = "(function(){try{window.onbeforeunload=null;if(document.body)document.body.onbeforeunload=null;" +
  "if(!window.__kitQuiet){window.__kitQuiet=1;var p=Event.prototype.preventDefault;" +
  "Event.prototype.preventDefault=function(){if(this.type!=='beforeunload')return p.apply(this,arguments)};" +
  "[window.BeforeUnloadEvent&&BeforeUnloadEvent.prototype,Event.prototype].forEach(function(o){if(o)try{" +
  "var d=Object.getOwnPropertyDescriptor(o,'returnValue');if(d&&d.set)Object.defineProperty(o,'returnValue',{configurable:true," +
  "get:d.get,set:function(v){if(this.type!=='beforeunload')d.set.call(this,v)}})}catch(e){}})}}catch(e){}return 'quiet'})()"
function quiet(tab) { try { send('CrSu', 'ExJa', {'----': tab, JvSc: str(QUIET)}) } catch (e) {} }
function quietAll(i) { try { tabIds(win(i)).forEach(function (t) { quiet(obj('CrTb', win(i), 'ID  ', D.descriptorWithInt32(Number(t)))) }) } catch (e) {} }
function closeWin(i) { quietAll(i); try { send('core', 'clos', {'----': win(i)}) } catch (e) {} }
function tabIds(w) { return (get(prop('ID  ', every('CrTb', w))) || []).map(String) }
// Make the tab the window's front tab. Chrome takes only the tab's place in the window for this, and the place
// can change between two events (the place can even be past the last tab by then, which is an error), so this
// checks which tab is in front and tries again. The page's script then runs in the tab by its id either way.
function front(w, id) {
  for (var k = 0; k < 4; k++) {
    if (String(get(prop('ID  ', prop('acTa', w)))) === id) return
    var n = tabIds(w).indexOf(id) + 1
    if (n === 0) throw new Error('NO_TAB')
    try { set(prop('acTI', w), D.descriptorWithInt32(n)) } catch (e) {}
  }
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
    *NO_CLAUDE_WINDOW*|*NO_CHROME*) echo "This session has no Chrome window named Claude and making one failed; the Sttark Claude Kit log says why." >&2 ;;
    *"(-600)"*|*"(-609)"*) echo "Chrome quit or restarted while the command ran; run it again." >&2 ;;
    *"Executing JavaScript through AppleScript is turned off"*|*"Allow JavaScript from Apple Events"*) echo "Chrome blocks scripts: turn on View > Developer > Allow JavaScript from Apple Events." >&2 ;;
    *) echo "$1" >&2 ;;
  esac
}

tab_lock() {  # one at a time for steps that open or close a tab; held until the (sub)shell that took it ends
  mkdir -p "$tabs" "$wins" && : >> "$tabs/.lock"
  zmodload zsh/system
  zsystem flock -t 20 "$tabs/.lock"
}

new_tab() {  # give this session or agent a tab in the session's window; $1 is the closed tab it replaces, if any
  local id wid first try
  tab_lock || return 1  # two steps of one session at once still get one tab
  [[ ! -f $mine || $(cut -d' ' -f1 < "$mine") == ${1:-} ]] || return 0
  for try in 1 2; do
    [[ -f $mywin ]] || ( open_window ) || { explain NO_CLAUDE_WINDOW; return 1; }
    read -r wid _ first < "$mywin"
    if [[ -n $first ]]; then   # the tab the new window came with
      id=$first
      print -r -- "$wid ${CLAUDE_PID:-}" > "$mywin"
    elif ! id=$(chrome new "$wid" 2>&1); then
      [[ $id == *NO_CLAUDE_WINDOW* && $try == 1 ]] && { rm -f "$mywin"; continue; }   # its window was closed: make it again
      explain "$id"; return 1
    fi
    print -r -- "$id ${CLAUDE_PID:-} $wid" > "$mine"
    touch "$mywin"
    return 0
  done
}

close_tab() {  # close_tab <tab id> [window id]; two closes at once still leave the window its last tab
  tab_lock || return 1
  chrome close "${2:-}" "$1" >/dev/null 2>&1
}

js() {  # run JavaScript in this session's or agent's tab, opening the tab first if it has none
  local out rc tab wid
  if [[ ! -f $mine ]]; then
    ( new_tab ) || return 1
    # A page it had before is gone with the old tab (done, the agent stopped earlier, or 30 minutes unused).
    [[ $cmd == go ]] || echo "This $owner had no tab, so it has a new, blank one. Open a page with: claude-window go <url>" >&2
  fi
  read -r tab _ wid < "$mine"
  out=$(chrome js "${wid:-}" "$tab" "$1" 2>&1); rc=$?
  if [[ $out == *NO_TAB* || $out == *NO_CLAUDE_WINDOW* ]]; then
    echo "This $owner's tab had been closed, so it has a new, blank one." >&2
    ( new_tab "$tab" ) || return 1
    read -r tab _ wid < "$mine"
    out=$(chrome js "${wid:-}" "$tab" "$1" 2>&1); rc=$?
  fi
  (( rc == 0 )) || { explain "$out"; return 1; }
  touch "$mine"; [[ -f $mywin ]] && touch "$mywin"
  print -r -- "$out"
}

wait_loaded() {
  for i in {1..60}; do
    [[ $(js 'document.readyState' 2>/dev/null) == complete ]] && return 0
    sleep 0.5
  done
}

cleanup() {  # close tabs and windows whose session's process ended or that went unused too long; forget those closed by hand
  [[ -d $tabs || -d $wins ]] || return 0
  local open live now f id pid wid used
  open=" $(chrome ids 2>/dev/null) " || return 0
  live=" $(chrome wins 2>/dev/null) "
  now=$(date +%s)
  used=" "
  for f in "$tabs"/*(N); do
    read -r id pid wid < "$f"
    if [[ $open != *" $id "* ]]; then
      rm -f "$f"
    elif [[ -n $pid ]] && ! kill -0 "$pid" 2>/dev/null || (( now - $(stat -f %m "$f") > unused_limit )); then
      ( close_tab "$id" "$wid" )
      rm -f "$f"
    else
      used+="$wid "
    fi
  done
  for f in "$wins"/*(N); do   # a session's window: closed when its process ended, or with no tab in use for 30 minutes
    read -r wid pid _ < "$f"
    if [[ $live != *" $wid "* ]]; then
      rm -f "$f"
    elif [[ -n $pid ]] && ! kill -0 "$pid" 2>/dev/null || { [[ $used != *" $wid "* ]] && (( now - $(stat -f %m "$f") > unused_limit )); }; then
      chrome close-win "$wid" >/dev/null 2>&1
      rm -f "$f"
    fi
  done
  # A Claude window that no session owns and that holds no tab of a session (the one window all sessions shared
  # before, once its sessions moved out): closed. Under the window lock, so a window just made is not taken for one.
  (
    zmodload zsh/system
    mkdir -p "$tabs" && : >> "$tabs/.window-lock"
    [[ -z ${STTARK_WINDOW_DRY:-} ]] || exit 0  # a test knows only its own records: every other window is a live session's
    zsystem flock -t 2 "$tabs/.window-lock" || exit 0
    local owned="" kept=""
    for f in "$wins"/*(N); do read -r wid _ < "$f"; owned+="$wid "; done
    for f in "$tabs"/*(N); do read -r id _ < "$f"; kept+="$id "; done
    n=$(chrome close-unowned "${owned% }" "${kept% }" 2>/dev/null)
    [[ ${n:-0} == 0 ]] || log "Claude window: closed $n with no session"
  )
}

agent_done() {  # an agent stopped: close its tab (every tab with its id, whatever key its session has)
  local f id wid
  for f in "$tabs"/*."$1"(N); do
    read -r id _ wid < "$f"
    ( close_tab "$id" "$wid" )
    rm -f "$f"
  done
}

case $cmd in
  go)
    [[ -n ${2:-} ]] || { echo "usage: claude-window go <url>" >&2; exit 2; }
    url=$(/usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$2")
    old=$(js 'location.href') || exit 1
    read -r tab _ wid < "$mine"; chrome quiet "${wid:-}" "$tab" >/dev/null 2>&1   # no "Leave site?" dialog for the page it leaves
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
      read -r tab _ wid < "$mine"
      ( close_tab "$tab" "$wid" )
      rm -f "$mine"
    fi
    echo "Closed this $owner's tab." ;;
  cleanup) cleanup ;;
  agent-done)                           # for the browser guard hook: the agent with this id stopped
    [[ ${2:-} =~ $agent_ok ]] || { echo "usage: claude-window agent-done <agent id>" >&2; exit 2; }
    agent_done "$2" ;;
  open) ;;                              # for the app's Open Claude window: each session makes its window when it needs it
  exists) chrome exists ;;              # for the app: is a Claude window open?
  close-window) chrome close-window; rm -rf "$wins" ;;  # for the app: the switch was turned off
  quiet) read -r tab _ wid < "$mine" && chrome quiet "${wid:-}" "$tab" ;;  # for tests: the step before a close
  ids) chrome ids ;;                    # for tests: the ids of the tabs in the Claude windows
  wins) chrome wins ;;                  # for tests: the ids of the Claude windows
  *)    echo "unknown command: $cmd (use go, url, text, js or done)" >&2; exit 2 ;;
esac
