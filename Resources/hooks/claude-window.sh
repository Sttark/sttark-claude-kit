#!/bin/zsh
# claude-window: lets Claude use your signed-in Chrome without taking your screen.
#
# Each Claude Code session, and each agent that a session starts (a subagent or a fork), works in a Chrome window
# of its own, named "Claude", in your own profile. So sessions and agents that use the browser at the same time
# never take each other's front tab, and never move, read or close each other's pages. Opening, switching and
# closing tabs, and running JavaScript, leave Chrome behind whatever you're typing in; giving a tab its address by
# script brings Chrome forward, so this never does. The one step that brings a window forward is making one. So a
# window is made only when no spare one is there: a session or an agent that has finished gives its window back,
# blank, and the next one that needs a window takes it. A spare window that nobody takes for 30 minutes closes.
# When a window is made, the app you were in goes back in front at once, and your own Chrome window goes in front
# of the new one (the new window is in front for about a tenth of a second; the log says how long).
#
#   claude-window go <url>      open a page in this session's tab, wait for it to load, print its title and URL
#   claude-window url           print the current title and URL
#   claude-window text [chars]  print the page's visible text (first 20000 characters unless given)
#   claude-window js '<code>'   run JavaScript in the page and print the result
#   claude-window done          close this session's page (when you're finished with the browser)
#
# Run by an agent, each command works in the agent's own window, with nothing to set, and done gives back only that
# window. What nobody gave back is taken back for you: an agent's window when the agent stops, and any window once
# its session's process ends or it goes unused for 30 minutes (Sttark Claude Kit runs `claude-window cleanup` every
# 30 seconds).
#
# Needs Chrome's View > Developer > Allow JavaScript from Apple Events.
#
# It talks to your own Chrome by its process id, so a Chrome that a test tool runs at the same time (Playwright,
# Puppeteer: started with --headless, --remote-debugging-…, --enable-automation or --user-data-dir) never gets
# the commands. Scripts that name "Google Chrome" go to whichever copy macOS picks, often the test one.
#
# For tests: STTARK_KIT_DIR and STTARK_KIT_LOG point it at a test folder and log, STTARK_WINDOW_NAME gives its
# windows another name than Claude (so a test never touches a session's windows), and STTARK_WINDOW_DRY=1 keeps it
# from making a window or starting Chrome (a command that needs a new window then fails).
set -uo pipefail
cmd=${1:-}
[[ -n $cmd ]] || { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

# Who runs this command: a session, or one of its agents. An agent's commands run in the session's own process,
# with the session's environment, so nothing there tells one agent from the next. The Kit's browser guard
# (browser-guard.py, a PreToolUse hook) knows the agent of each command, and puts
# "export CLAUDE_WINDOW_AGENT=<agent id>; " in front of every command an agent runs. So a script that the agent
# runs works in the agent's window too. The key is the session, or "<session>.<agent>".
kit="${STTARK_KIT_DIR:-$HOME/Library/Application Support/SttarkClaudeKit}"
session=${CLAUDE_CODE_SESSION_ID:-${CLAUDE_PID:-terminal}}
agent_ok='^[A-Za-z0-9_-]{1,64}$'
agent=${CLAUDE_WINDOW_AGENT:-}
[[ $agent =~ $agent_ok ]] || agent=""
key="$session${agent:+.$agent}"
owner=session; [[ -n $agent ]] && owner=agent
# Three folders of small records, one file each:
#   claude-window-tabs/<key>         "<tab id> <session process id> <window id>": the tab a session or agent works
#                                    in. The file's time is the tab's last use.
#   claude-window-wins/<key>         "<window id> <session process id> [<id of its blank tab, until a tab record
#                                    takes it>]": the window that is its own.
#   claude-window-spare/<window id>  "<window id> <tab id> <the tab's address>": a window that was given back and
#                                    waits, blank, for the next session or agent. The file's time is since when.
tabs="$kit/claude-window-tabs"
wins="$kit/claude-window-wins"
spare="$kit/claude-window-spare"
mine="$tabs/$key"
mywin="$wins/$key"
unused_limit=1800  # seconds: a page nobody used for this long closes, and its window is given back
# The spare windows. A new window is the one step that puts Chrome in front of the person, so a window that was
# given back stays open for the next session or agent. How long, and how many: from 12 days of this Mac's session
# records (338 times a session or agent took a window; 315 ended with done). With no spare windows that is 28 new
# windows a day; a window for each session with its agents in it, as before, was 12 a day. Spares kept for 10
# minutes give 13 a day, for 30 minutes 8 a day, for 60 minutes 6 a day, with a quarter of one spare window open
# on average at 30 minutes. So: 30 minutes, the same time as for an unused page. More than 3 spares never saved a
# new window in those records (2 saved 3 fewer), so the fourth window given back closes at once.
spare_limit=1800   # seconds
spare_max=3
chrome_id=com.google.Chrome
wname=${STTARK_WINDOW_NAME:-Claude}
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
# What both scripts below use: the windows with the Kit's name, and where they are on the screen.
win_lib=$(cat <<'JXA'
var NAME = 'Claude', STEP = 22
function win(i) { return obj('cwin', null, 'ID  ', D.descriptorWithInt32(Number(i))) }
function alive(i) { try { return /^[0-9]+$/.test(String(i)) && get(prop('GNam', win(i))) === NAME } catch (e) { return false } }
// The ids of the windows with the Kit's name, front to back. Each window's name is read by the window's id, never
// from a second list beside the list of ids: a window that opens, closes or comes to the front between two lists
// puts them in different orders, and then a name stands beside another window's id. (That gave a spare window's
// place to another window once: its record was dropped and it was closed. It could as well have named one of the
// person's own windows.)
function named() { return (get(prop('ID  ', every('cwin'))) || []).map(String).filter(alive) }
// A window's frame as [left, top, right, bottom]. Chrome gives and takes it as a QuickDraw rectangle: top, left,
// bottom, right, each a 16-bit number.
var B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
function getRect(w) {
  try {
    var s = ObjC.unwrap(send('core', 'getd', {'----': prop('pbnd', w)}).data.base64EncodedStringWithOptions(0))
    var raw = [], buf = 0, bits = 0, a = []
    for (var i = 0; i < s.length; i++) { var c = B64.indexOf(s[i]); if (c < 0) continue; buf = (buf << 6) | c; bits += 6; if (bits >= 8) { bits -= 8; raw.push((buf >> bits) & 255) } }
    if (raw.length < 8) return null
    for (var j = 0; j < 4; j++) { var v = raw[2 * j] | (raw[2 * j + 1] << 8); a.push(v > 32767 ? v - 65536 : v) }
    return [a[1], a[0], a[3], a[2]]
  } catch (e) { return null }
}
function setRect(w, r) {
  var bs = [], s = ''
  ;[r[1], r[0], r[3], r[2]].forEach(function (v) { v = v < 0 ? v + 65536 : v; bs.push(v & 255, (v >> 8) & 255) })
  for (var i = 0; i < bs.length; i += 3) {
    var a = bs[i], b = bs[i + 1], c = bs[i + 2]
    s += B64[a >> 2] + B64[((a & 3) << 4) | ((b || 0) >> 4)] + (b === undefined ? '=' : B64[((b & 15) << 2) | ((c || 0) >> 6)]) + (c === undefined ? '=' : B64[c & 63])
  }
  set(prop('pbnd', w), D.descriptorWithDescriptorTypeData(fc('qdrt'), $.NSData.alloc.initWithBase64EncodedStringOptions(s, 0)))
}
// No two of the Kit's windows at one place. A window that other windows cover fully has a hidden page: its
// visibilityState is "hidden", its animation frames stop and its timers slow down, as in a tab that is not in
// front. Chrome gives each new window the frame of the last one used plus a step, so windows made one after the
// other for different sessions often get the same frame, and the newest one covers the rest (measured: of 4
// windows at one frame, 3 had a hidden page; in Chrome's own stack of 4, 1 or 2). So a window whose top right
// corner is less than a step from another's moves down and right, a step (22 points, as Chrome's own) at a time,
// until it is free. Then each window has a corner that no other of these windows covers, in whatever order they
// are (measured: 4 of 4 visible, in each order). The size stays, so the page sees no change. The person's own
// windows can still cover all of a window; nothing here can stop that.
function place(id, others) {
  var r = getRect(win(id))
  if (!r) return
  var rs = others.map(function (o) { return getRect(win(o)) }).filter(function (o) { return o }), moved = false
  for (var k = 0; k < 12; k++) {
    if (!rs.some(function (o) { return Math.abs(o[2] - r[2]) < STEP && Math.abs(o[1] - r[1]) < STEP })) break
    r = r.map(function (v) { return v + STEP })
    moved = true
  }
  if (moved) try { setRect(win(id), r) } catch (e) {}
}
JXA
)
jxa() { { print -r -- "$ae_lib"; print -r -- "$win_lib"; cat } | osascript -l JavaScript - "$cpid" "$wname" "$@" }  # script on stdin; run(argv) gets the pid and the windows' name first

front_app() {  # the bundle ID of the app in front
  lsappinfo info -only bundleid "$(lsappinfo front)" 2>/dev/null | sed -n 's/.*="\(.*\)"/\1/p'
}

lock() {  # one at a time for every step that gives, takes back, makes or closes a tab or a window; held until the (sub)shell that took it ends
  mkdir -p "$tabs" "$wins" "$spare" && : >> "$tabs/.lock"
  zmodload zsh/system
  zsystem flock -t ${1:-60} "$tabs/.lock"
}

open_window() {  # under the lock: make a window for this session or agent, then put back what was in front at once
  local asn before bpid mode after out started="" wid note p s i
  [[ -z ${STTARK_WINDOW_DRY:-} ]] || return 1  # a test that must not bring Chrome forward
  asn=$(lsappinfo front 2>/dev/null)
  before=$(lsappinfo info -only bundleid "$asn" 2>/dev/null | sed -n 's/.*="\(.*\)"/\1/p')
  bpid=$(lsappinfo info -only pid "$asn" 2>/dev/null | sed -n 's/.*=\([0-9][0-9]*\).*/\1/p')
  if ! chrome_running; then
    # a Chrome passed over here is not the person's (a test tool's flag); starting another copy can show it
    [[ -n $skipped ]] && log "Claude window: Chrome $skipped skipped as not the person's; starting another copy"
    rm -f "$tabs"/*(N) "$wins"/*(N) "$spare"/*(N)  # Chrome quit, so every tab and window is gone
    # -n: a test tool's Chrome may be running, and without -n macOS would only hand the request to that one
    open -n -g -j -b "$chrome_id" || { log "Claude window: couldn't start Chrome"; return 1; }  # in the background, hidden
    for i in {1..60}; do
      chrome_running && jxa <<<'function run(a) { PID = Number(a[0]); return count("cwin") }' >/dev/null 2>&1 && break
      sleep 0.5
    done
    log "Chrome wasn't running; started it hidden"
    started=1
  fi
  # Making a window brings it to the front (tested: a plain window, a minimized one and Chrome's --new-window all
  # do): in front of the person's own Chrome window always, and Chrome in front of the app they were in, at once
  # or a moment later. So, in the same Apple event script and right after the window is made, two things go back:
  # the app that was in front (when it was not this Chrome; a Chrome app window is another app), and the person's
  # own front Chrome window, in front of the new one. That window is the first in Chrome's order that shows and
  # does not have the Kit's name; putting it first also gives it the keyboard when Chrome is the app in front
  # (read through Accessibility in a test). One look is not enough, because Chrome can come forward after the
  # first look, so the script then looks every 50 ms until 1.5 s after the window was made, and puts back again
  # each time Chrome or the new window is in front. The log says until when one of them was in front, how often
  # each went back, and what each look saw. Making two windows in one go was measured too: each one more adds
  # about 0.1 s in front (71 ms for one, 169 for two, 326 for four), so one window is made at a time.
  chrome_running || { log "Claude window: Chrome didn't start"; return 1; }
  mode=other
  [[ -n $bpid && $bpid == "$cpid" && -z $started ]] && mode=chrome   # the person was in this Chrome itself
  [[ -n $bpid ]] || mode=none
  out=$(jxa "$mode" "${bpid:-0}" <<'JXA' 2>&1
function run(argv) {
  PID = Number(argv[0])
  NAME = argv[1]
  var mode = argv[2], bpid = Number(argv[3]) || 0
  function first() { set(prop('pidx', win(own)), D.descriptorWithInt32(1)) }
  function activate() {  // one "activate" event to the app that was in front. It does not wait for the answer: a Chrome app window took 0.5 s to give one
    try {
      var e = D.appleEventWithEventClassEventIDTargetDescriptorReturnIDTransactionID(fc('misc'), fc('actv'),
        D.descriptorWithProcessIdentifier(bpid), -1, 0)
      e.sendEventWithOptionsTimeoutError(0x1, 2, Ref())
    } catch (x) {}
  }
  var own = null, ours = []
  try {   // each window's name and "visible" by the window's id: see named()
    (get(prop('ID  ', every('cwin'))) || []).forEach(function (i) {
      var nm
      try { nm = get(prop('GNam', win(i))) } catch (e) { return }
      if (nm === NAME) ours.push(String(i))
      else if (own === null) try { if (get(prop('pvis', win(i))) === true) own = i } catch (e) {}
    })
  } catch (e) {}
  var t0 = Date.now(), napp = 0, nwin = 0, last = 0, seen = [], state = ''
  var w = make('cwin')
  if (mode === 'other') { activate(); napp++ }
  if (own !== null) try { first(); nwin++ } catch (e) {}
  last = Date.now() - t0
  var wid = get(prop('ID  ', w))
  set(prop('GNam', w), str(NAME))
  var tab = String((get(prop('ID  ', every('CrTb', w))) || [''])[0])
  place(wid, ours)
  while (Date.now() - t0 < 1500) {
    var active = false, front = null
    try { active = get(prop('pisf', null)) === true } catch (e) {}
    try { front = get(prop('ID  ', nth('cwin', null, 1))) } catch (e) {}
    var c = mode !== 'chrome' && active, n = own !== null && front === wid
    var s = (c ? 'C' : '-') + (n ? 'W' : '-')
    if (s !== state) { seen.push(((Date.now() - t0) / 1000).toFixed(2) + ':' + s); state = s }
    if (c && mode === 'other') { activate(); napp++ }
    if (n) try { first(); nwin++ } catch (e) {}
    if ((c && mode === 'other') || n) last = Date.now() - t0
    delay(0.05)
  }
  return ['opened', wid, tab, (last / 1000).toFixed(2), napp, nwin, seen.join(',')].join(' ')
}
JXA
  )
  case $out in
    opened\ *) ;;
    *) log "Claude window: couldn't open: $out"; return 1 ;;
  esac
  p=(${=out})
  wid=$p[2]
  print -r -- "$wid ${CLAUDE_PID:-} $p[3]" > "$mywin"
  after=$(front_app)
  note="Chrome or the new window was in front for at most $p[4] s"
  case $mode in
    other)  note+="; put $before back in front $p[5] time(s)" ;;
    chrome) note+="; the person was in Chrome" ;;
    none)   note+="; no app was in front before" ;;
  esac
  if (( p[6] )); then note+="; put the person's own Chrome window in front of the new one $p[6] time(s)"
  else note+="; the person had no Chrome window of their own"; fi
  note+="; looked until 1.5 s:"
  for s in ${(s:,:)p[7]}; do
    case ${s#*:} in
      CW) note+=" at ${s%%:*} s Chrome and the new window were in front," ;;
      C-) note+=" at ${s%%:*} s Chrome was in front," ;;
      -W) note+=" at ${s%%:*} s the new window was in front of the person's," ;;
      *)  note+=" at ${s%%:*} s neither was in front," ;;
    esac
  done
  note=${note%,}
  if [[ $mode == other && $after == "$chrome_id" && $before != "$chrome_id" ]]; then   # the events did not do it: the old way
    osascript -e "tell application id \"$before\" to activate" >/dev/null 2>&1
    note+="; Chrome was still in front after that, so $before was activated again"
  fi
  log "Claude window: opened for ${${owner/agent/an agent}/session/a session}; $note"
}

if ! chrome_running; then
  [[ $cmd == cleanup ]] && { rm -rf "$tabs" "$wins" "$spare"; exit 0; }  # Chrome quit, so every tab and window is gone
  [[ $cmd == done ]] && { rm -f "$mine" "$mywin"; echo "Closed this $owner's tab."; exit 0; }
  [[ $cmd == agent-done && ${2:-} =~ $agent_ok ]] && { rm -f "$tabs"/*."$2"(N) "$wins"/*."$2"(N); exit 0; }
  [[ $cmd == exists ]] && { echo false; exit 0; }
  [[ $cmd == close-window ]] && { rm -rf "$wins" "$spare"; exit 0; }
fi

chrome() {  # chrome <op> [window id] [tab id] [javascript]; never activates Chrome
  [[ -n $cpid ]] || chrome_running || { echo "NO_CHROME" >&2; return 1; }
  jxa "$@" <<'JXA'
function run(argv) {
  PID = Number(argv[0])
  NAME = argv.splice(1, 1)[0]
  var op = argv[1]
  if (op === 'exists') return named().length > 0
  if (op === 'wins') return named().join(' ')
  if (op === 'tidy') {  // the same list, after each window that is at another's place has moved away from it
    var all = named()
    all.forEach(function (i, k) { if (k) place(i, all.slice(0, k)) })
    return all.join(' ')
  }
  if (op === 'close-window') { named().forEach(closeWin); return '' }
  if (op === 'close-win') { if (alive(argv[2])) closeWin(argv[2]); return '' }
  if (op === 'front') return String(get(prop('ID  ', nth('cwin', null, 1))))   // Chrome's front window, whoever's it is
  if (op === 'rect') {  // a window's frame: left top right bottom; with four numbers more, the frame it gets first
    if (!alive(argv[2])) return ''
    if (argv.length > 6) setRect(win(argv[2]), argv.slice(3, 7).map(Number))
    return (getRect(win(argv[2])) || []).join(' ')
  }
  if (op === 'close-unowned') {  // argv[2]: the window ids in records; argv[3]: the tab ids in records
    var owned = (argv[2] || '').split(' '), kept = (argv[3] || '').split(' '), n = 0
    named().forEach(function (i) {
      if (owned.indexOf(i) >= 0) return
      var t = []; try { t = tabIds(win(i)) } catch (e) { return }
      if (t.some(function (x) { return kept.indexOf(x) >= 0 })) return
      closeWin(i); n++
    })
    return String(n)
  }
  // every tab id, or an error: cleanup forgets a record whose tab is not in this list, so a window that could not
  // be read must not look like a window with no tabs
  if (op === 'ids') return named().map(function (i) { return tabIds(win(i)).join(' ') }).join(' ')
  var wid = argv[2]
  if (op === 'new') {
    if (!alive(wid)) throw new Error('NO_CLAUDE_WINDOW')
    // a plain new tab: giving it an address here (or setting a tab's URL) brings Chrome to the front
    return String(get(prop('ID  ', make('CrTb', win(wid)))))
  }
  // A window that is given back: as new. One new tab, and every tab it had closes, so the next session or agent
  // gets no page, no history and no stored state of the last one. Prints "<tab id> <its address>"; nothing when
  // the window is gone.
  if (op === 'fresh') {
    if (!alive(wid)) return ''
    var fw = win(wid), old = tabIds(fw)
    quietAll(wid)
    var nt = String(get(prop('ID  ', make('CrTb', fw))))
    old.forEach(function (x) { try { send('core', 'clos', {'----': tabOf(fw, x)}) } catch (e) {} })
    return nt + ' ' + address(fw, nt)
  }
  // A spare window, before it is given out (take) or closed as unused (drop): argv[3] is its tab, argv[4] the
  // tab's address when it was given back. Still as it was left: "ok" (and for take it moves off another window's
  // place), or it closes and this prints "closed". With another tab, more tabs, or a page in it, somebody used it:
  // the person opened something there. Then it is theirs: its name is taken off, it stays open with its pages,
  // and this prints "used". "gone" when it was closed by hand.
  if (op === 'take' || op === 'drop') {
    if (!alive(wid)) return 'gone'
    var sw = win(wid), st = tabIds(sw), now = st.length === 1 ? address(sw, st[0]) : ''
    if (st.length !== 1 || st[0] !== argv[3] || !(now === argv[4] || blank(now))) {
      try { set(prop('GNam', sw), str('')) } catch (e) {}
      return 'used'
    }
    if (op === 'drop') { closeWin(wid); return 'closed' }
    place(wid, named().filter(function (i) { return i !== String(wid) }))
    return 'ok'
  }
  // The tab by its id, never by its place in the window: tabs open and close at the same moment, so the place a
  // tab had in one Apple event can be another tab's place in the next. A record from before each session had its
  // own window has no window id: then the tab is looked for in every window with the Kit's name, and it stays
  // there with its page until its owner closes it.
  var id = argv[3], w = null, ids = []
  var where = wid ? (alive(wid) ? [wid] : []) : named()
  if (/^[0-9]+$/.test(id)) where.forEach(function (i) {
    if (w) return
    var t = []; try { t = tabIds(win(i)) } catch (e) {}
    if (t.indexOf(id) >= 0) { w = win(i); ids = t }
  })
  var tab = w ? tabOf(w, id) : null
  if (op === 'close') {
    if (!w) return ''
    quiet(tab)
    // the window's last tab stays, blank, so the window stays open until its owner gives it back
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
function tabOf(w, id) { return obj('CrTb', w, 'ID  ', D.descriptorWithInt32(Number(id))) }
function address(w, id) { try { return String(get(prop('URL ', tabOf(w, id))) || '') } catch (e) { return '' } }
function blank(u) { return u === 'about:blank' || /^chrome:\/\/(newtab|new-tab-page)/.test(u) }
// A page can ask "Leave site? Changes you made may not be saved" when its tab closes or goes to another address
// (a beforeunload handler), once somebody really clicked or typed in it. That dialog shows on the person's screen
// and waits for them. A script from an Apple event runs in a world of its own: it shares the page's document, not
// the page's script objects, so it cannot clear the page's own handlers or change what they do (tested: a page's
// own handlers still ran, and still asked to stay, after such a script cleared onbeforeunload and replaced
// preventDefault). document.open() can: it takes every event listener and handler off the window and the
// document, of each world, and empties the document without leaving it, so no beforeunload runs for it; a frame
// in the page goes with the document. So a page that is closed is emptied this way first.
var QUIET = "try{document.open();document.close()}catch(e){}'quiet'"
function quiet(tab) { try { send('CrSu', 'ExJa', {'----': tab, JvSc: str(QUIET)}) } catch (e) {} }
function quietAll(i) { try { tabIds(win(i)).forEach(function (t) { quiet(tabOf(win(i), t)) }) } catch (e) {} }
function closeWin(i) { quietAll(i); try { send('core', 'clos', {'----': win(i)}) } catch (e) {} }
function tabIds(w) { return (get(prop('ID  ', every('CrTb', w))) || []).map(String) }
// Make the tab the window's front tab (a page can open more tabs in its window). Chrome takes only the tab's place
// in the window for this, and the place can change between two events (the place can even be past the last tab by
// then, which is an error), so this checks which tab is in front and tries again. The page's script then runs in
// the tab by its id either way.
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
    *NO_CLAUDE_WINDOW*|*NO_CHROME*) echo "This $owner has no Chrome window named $wname and making one failed; the Sttark Claude Kit log says why." >&2 ;;
    *"(-600)"*|*"(-609)"*) echo "Chrome quit or restarted while the command ran; run it again." >&2 ;;
    *"Executing JavaScript through AppleScript is turned off"*|*"Allow JavaScript from Apple Events"*) echo "Chrome blocks scripts: turn on View > Developer > Allow JavaScript from Apple Events." >&2 ;;
    *) echo "$1" >&2 ;;
  esac
}

take_spare() {  # under the lock: this session or agent gets a spare window, the one given back last, if one is there
  local f wid tab url
  for f in "$spare"/*(Nom); do
    read -r wid tab url < "$f"
    rm -f "$f"
    case $(chrome take "$wid" "$tab" "$url" 2>/dev/null) in
      ok) print -r -- "$wid ${CLAUDE_PID:-} $tab" > "$mywin"
          log "Claude window: taken by ${${owner/agent/an agent}/session/a session} from the spare ones; no new window"
          return 0 ;;
      used) log "Claude window: left to the person, a spare one with a page in it; its name is taken off" ;;
    esac
  done
  return 1
}

give_window() {  # under the lock: give_window <window id>. The window goes to the spare ones, blank; with $spare_max there already, it closes
  local wid=$1 out n
  n=("$spare"/*(N))
  if (( ${#n} >= spare_max )); then
    chrome close-win "$wid" >/dev/null 2>&1
    log "Claude window: closed when given back; $spare_max spare ones are there already"
    return 0
  fi
  out=$(chrome fresh "$wid" 2>/dev/null)
  [[ -n $out ]] || return 0   # closed by hand
  print -r -- "$wid $out" > "$spare/$wid"
  log "Claude window: given back; $(( ${#n} + 1 )) spare now"
}

get_tab() {  # give this session or agent a tab, in a window of its own; $1 is the closed tab it replaces, if any
  local id wid first try
  lock || return 1  # two steps of one session at once still get one tab, and a spare window goes to one of two that ask
  [[ ! -f $mine || $(cut -d' ' -f1 < "$mine") == ${1:-} ]] || return 0
  for try in 1 2 3; do
    [[ -f $mywin ]] || take_spare || open_window || { explain NO_CLAUDE_WINDOW; return 1; }
    read -r wid _ first < "$mywin"
    if [[ -n $first ]]; then   # the blank tab the window has
      id=$first
      print -r -- "$wid ${CLAUDE_PID:-}" > "$mywin"
    elif ! id=$(chrome new "$wid" 2>&1); then
      [[ $id == *NO_CLAUDE_WINDOW* && $try -lt 3 ]] && { rm -f "$mywin"; continue; }   # its window was closed: another one
      explain "$id"; return 1
    fi
    print -r -- "$id ${CLAUDE_PID:-} $wid" > "$mine"
    touch "$mywin"
    return 0
  done
}

give_back() {  # give_back <key>: that session or agent has finished with the browser, or stopped
  local f="$tabs/$1" w="$wins/$1" id="" wid="" own="" o other shared=""
  lock || return 1
  [[ -f $f ]] && read -r id _ wid < "$f"
  [[ -f $w ]] && read -r own _ < "$w"
  if [[ -n $own ]]; then
    # Its own window goes to the spare ones. But a tab of another one in it (an agent's tab from before each agent
    # had its own window) keeps the window: then only this tab closes.
    for o in "$tabs"/*(N); do
      [[ $o == $f ]] && continue
      read -r _ _ other < "$o"
      [[ $other == $own ]] && shared=1
    done
    if [[ -n $shared ]]; then
      [[ -n $id ]] && chrome close "$wid" "$id" >/dev/null 2>&1
    else
      [[ -n $id && -n $wid && $wid != $own ]] && chrome close "$wid" "$id" >/dev/null 2>&1
      give_window "$own"
      rm -f "$w"
    fi
  elif [[ -n $id ]]; then
    chrome close "$wid" "$id" >/dev/null 2>&1   # a tab in a window that is not its own (from before)
  fi
  rm -f "$f"
}

js() {  # run JavaScript in this session's or agent's tab, getting it a tab first if it has none
  local out rc tab wid
  if [[ ! -f $mine ]]; then
    ( get_tab ) || return 1
    # A page it had before is gone with the old tab (done, the agent stopped earlier, or 30 minutes unused).
    [[ $cmd == go ]] || echo "This $owner had no tab, so it has a new, blank one. Open a page with: claude-window go <url>" >&2
  fi
  read -r tab _ wid < "$mine"
  out=$(chrome js "${wid:-}" "$tab" "$1" 2>&1); rc=$?
  if [[ $out == *NO_TAB* || $out == *NO_CLAUDE_WINDOW* ]]; then
    echo "This $owner's tab had been closed, so it has a new, blank one." >&2
    ( get_tab "$tab" ) || return 1
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

cleanup() {  # take back what a session or agent that ended, or did not use it for too long, still has; close spare windows nobody took; forget what was closed by hand
  [[ -d $tabs || -d $wins || -d $spare ]] || return 0
  local open live now f id pid wid first tab url k used=" " stale=" " n=0 owned="" kept="" out
  # Under the lock from the first look at Chrome on, so a tab or window that a session gets while this runs is
  # never taken for one that is gone. With the lock busy for 5 seconds, the next run does it.
  lock 5 || return 0
  open=$(chrome ids 2>/dev/null) || return 0    # Chrome did not answer: nothing is forgotten or closed on a guess
  live=$(chrome tidy 2>/dev/null) || return 0
  open=" $open " live=" $live "
  now=$(date +%s)
  for f in "$tabs"/*(N); do   # tabs in use: their windows stay
    read -r id pid wid < "$f"
    if [[ $open != *" $id "* ]]; then
      rm -f "$f"
    elif [[ -n $pid ]] && ! kill -0 "$pid" 2>/dev/null || (( now - $(stat -f %m "$f") > unused_limit )); then
      stale+="${f:t} "
    else
      used+="$wid "
    fi
  done
  for k in ${=stale}; do      # tabs of a session that ended, or not used for 30 minutes
    f="$tabs/$k"
    read -r id pid wid < "$f"
    if [[ $used == *" $wid "* ]] || [[ ! -f $wins/$k ]] || [[ $(cut -d' ' -f1 < "$wins/$k") != "$wid" ]]; then
      chrome close "$wid" "$id" >/dev/null 2>&1   # in a window that another one still uses, or that is not its own
    fi
    rm -f "$f"
    [[ -f $wins/$k ]] && touch -t 200001010000 "$wins/$k"   # its own window goes back in the step below
  done
  for f in "$wins"/*(N); do   # windows: back to the spare ones when the session's process ended, or with no tab in use for 30 minutes
    read -r wid pid first < "$f"
    if [[ $live != *" $wid "* ]]; then
      rm -f "$f"
    elif [[ $used != *" $wid "* ]] && { [[ -n $pid ]] && ! kill -0 "$pid" 2>/dev/null || (( now - $(stat -f %m "$f") > unused_limit )); }; then
      give_window "$wid"
      rm -f "$f"
    fi
  done
  for f in "$spare"/*(Nom); do   # spare windows, the one given back last first: closed when nobody took one for 30 minutes
    read -r wid tab url < "$f"
    if [[ $live != *" $wid "* ]]; then
      rm -f "$f"
    elif (( ++n > spare_max || now - $(stat -f %m "$f") > spare_limit )); then
      out=$(chrome drop "$wid" "$tab" "$url" 2>/dev/null)
      rm -f "$f"
      case $out in
        closed) log "Claude window: closed, a spare one that nobody took for $(( spare_limit / 60 )) minutes" ;;
        used)   log "Claude window: left to the person, a spare one with a page in it; its name is taken off" ;;
      esac
    fi
  done
  # A window with the Kit's name that has no record and holds no tab of a record (the one window all sessions
  # shared before, once its sessions moved out; a window from before Chrome started again): closed.
  [[ -n ${STTARK_WINDOW_DRY:-} && $wname == Claude ]] && return 0  # a test with the sessions' own name knows only its own records
  for f in "$wins"/*(N) "$spare"/*(N); do read -r wid _ < "$f"; owned+="$wid "; done
  for f in "$tabs"/*(N); do read -r id _ < "$f"; kept+="$id "; done
  out=$(chrome close-unowned "${owned% }" "${kept% }" 2>/dev/null)
  [[ ${out:-0} == 0 ]] || log "Claude window: closed $out with no session"
}

agent_done() {  # an agent stopped: its window goes back (every key with its id, whatever key its session has)
  local f k seen=" "
  for f in "$tabs"/*."$1"(N) "$wins"/*."$1"(N); do
    k=${f:t}
    [[ $seen == *" $k "* ]] && continue
    seen+="$k "
    ( give_back "$k" )
  done
}

case $cmd in
  go)
    [[ -n ${2:-} ]] || { echo "usage: claude-window go <url>" >&2; exit 2; }
    url=$(/usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$2")
    old=$(js 'location.href') || exit 1
    # No "Leave site?" dialog for the page it leaves: a page in which somebody really clicked or typed (only such a
    # page can ask) is emptied first, as before a close. Not when only the part after # changes: that leaves no page.
    js "(function (u) { try { var t = new URL(u, location.href); if (navigator.userActivation && navigator.userActivation.hasBeenActive && !(t.hash && t.href.split('#')[0] === location.href.split('#')[0])) { document.open(); document.close() } } catch (e) {} location.href = u })($url); 'ok'" >/dev/null || exit 1
    # wait for the new page to replace the old one, then for it to finish loading
    for i in {1..40}; do [[ $(js 'location.href' 2>/dev/null) != "$old" ]] && break; sleep 0.25; done
    wait_loaded
    js 'document.title + "\n" + location.href' ;;
  url)  js 'document.title + "\n" + location.href' ;;
  text) js "document.body ? document.body.innerText.slice(0, ${2:-20000}) : ''" ;;
  js)   [[ -n ${2:-} ]] || { echo "usage: claude-window js '<code>'" >&2; exit 2; }; js "$2" ;;
  done)
    [[ -f $mine || -f $mywin ]] && ( give_back "$key" )
    echo "Closed this $owner's tab." ;;
  cleanup) ( cleanup ) ;;
  agent-done)                           # for the browser guard hook: the agent with this id stopped
    [[ ${2:-} =~ $agent_ok ]] || { echo "usage: claude-window agent-done <agent id>" >&2; exit 2; }
    agent_done "$2" ;;
  open) ;;                              # for the app's Open Claude window: each session makes its window when it needs it
  exists) chrome exists ;;              # for the app: is a Claude window open?
  close-window) chrome close-window; rm -rf "$wins" "$spare" ;;  # for the app: the switch was turned off
  quiet) read -r tab _ wid < "$mine" && chrome quiet "${wid:-}" "$tab" ;;  # for tests: the step before a close
  ids) chrome ids ;;                    # for tests: the ids of the tabs in the Kit's windows
  wins) chrome wins ;;                  # for tests: the ids of the Kit's windows, front to back
  spare) ( lock && give_window "${2:-}" ) ;;  # for tests: this window, which has no record, becomes a spare one
  raw) shift; chrome "$@" ;;            # for tests: one step of the Chrome script as it is (new, rect, front, close-win)
  *)    echo "unknown command: $cmd (use go, url, text, js or done)" >&2; exit 2 ;;
esac
