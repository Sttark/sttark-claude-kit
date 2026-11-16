#!/bin/zsh
# Tests claude-window's windows, on a copy: a temp folder holds a copy of Resources/hooks/claude-window.sh and
# chrome-ae.js, its own records folder and log (STTARK_KIT_DIR, STTARK_KIT_LOG) and a small web server on 127.0.0.1
# for the pages. Only a real Chrome can show that windows and pages do not mix, so it works in your Chrome, but only
# in its own windows, named "Claude test" (STTARK_WINDOW_NAME): it never reads, moves or closes a window named
# Claude, which is a session's. It needs 4 such windows.
#
#   zsh tools/claude-window-test.sh            runs when 4 windows named "Claude test" are open; else it skips
#   zsh tools/claude-window-test.sh make       makes the windows that are missing first. Each one puts Chrome in
#                                              front for about a tenth of a second, and it waits for a pause in
#                                              your typing first. It closes its windows at the end.
#   zsh tools/claude-window-test.sh make keep  leaves its windows open, blank, for the next run, and skips the
#                                              checks that close a window
#
# After the start it never makes a window, brings an app to the front or sends a key (STTARK_WINDOW_DRY=1).
#
# It checks: a session and each of its agents get a window of their own, from the spare ones, with no new window;
# three of them that work at the same time each read back only their own page, their pages stay shown
# (visibilityState, animation frames) and they keep their windows, while a fourth takes a window and gives it back
# again and again; go and done turn off a page's "Leave site?" handlers; done gives back only the caller's window;
# the next one gets that window with a blank page; agent-done (the browser guard's step when an agent stops) gives
# back that agent's windows only; of several that ask at the same moment, each spare window goes to one, and no
# window that is in use is taken; an agent's tab in its session's window, from before each agent had its own, still
# works and closes alone; cleanup gives back the window of a session that ended, and moves a window that is at
# another's place; and, when it may close windows: the fourth spare window closes, a spare window closes after 30
# minutes, a window closed under its owner is replaced with a note, and a spare window that somebody used loses its
# name and stays open.
# Prints each case; exits 1 if any fails.
set -u
HERE=${0:A:h}
MAKE="" KEEP=""
for a in "$@"; do case $a in make) MAKE=1 ;; keep) KEEP=1 ;; *) print "usage: zsh tools/claude-window-test.sh [make] [keep]"; exit 2 ;; esac; done
T=$(mktemp -d -t claude-window-test)
mkdir -p "$T/hooks" "$T/kit" "$T/www" "$T/out"
cp "$HERE/../Resources/hooks/claude-window.sh" "$HERE/../Resources/hooks/chrome-ae.js" "$T/hooks/"
NAME="Claude test"
NEED=4
STEP=22
TABS="$T/kit/claude-window-tabs"
WINS="$T/kit/claude-window-wins"
SPARE="$T/kit/claude-window-spare"
SID="cw-test-$$"
failed=0

# cw <agent or -> <command...>: the copy, as the test session (agent "-") or as one of its agents.
# KEY=<key> before it stands in for another session; ENDED=1 for a session whose process ended; DRY= lets it make a window.
cw() {
  local agent=$1 pid=$$; shift
  [[ $agent == - ]] && agent=""
  [[ -n ${ENDED:-} ]] && pid=99999999   # no process has this id
  env CLAUDE_CODE_SESSION_ID="${KEY:-$SID}" CLAUDE_PID="$pid" CLAUDE_WINDOW_AGENT="$agent" STTARK_WINDOW_NAME="$NAME" \
      STTARK_KIT_DIR="$T/kit" STTARK_KIT_LOG="$T/log" STTARK_WINDOW_DRY="${DRY-1}" /bin/zsh "$T/hooks/claude-window.sh" "$@"
}
check() {  # check <name> <ok or anything else> [detail]
  if [[ $2 == ok ]]; then print -r -- "ok    $1"; else print -r -- "FAIL  $1  -- ${3:-}"; failed=$((failed + 1)); fi
}
is() { [[ $1 == "$2" ]] && print ok || print no }
yes() { if "$@"; then print ok; else print no; fi }
tabof() { cut -d' ' -f1 < "$TABS/$1" 2>/dev/null }      # the tab in a record
tabwin() { cut -d' ' -f3 < "$TABS/$1" 2>/dev/null }     # the window that tab is in
winof() { cut -d' ' -f1 < "$WINS/$1" 2>/dev/null }      # the window that is its own
spares() { print -r -- ${(o)$(print -l "$SPARE"/*(N:t))} }   # the spare windows' ids
nspare() { local n=("$SPARE"/*(N)); print ${#n} }
allwins() { cw - wins 2>/dev/null }
nwins() { local w=(${=$(allwins)}); print ${#w} }
sorted() { print -r -- ${(o)@} }
logged() { local n; n=$(grep -c -- "$1" "$T/log" 2>/dev/null); print ${n:-0} }   # how many log lines have this
opened() { logged "opened for" }                                                 # how many windows were made
front_now() { lsappinfo info -only bundleid "$(lsappinfo front)" 2>/dev/null }
finish() {
  [[ -n ${server:-} ]] && kill $server 2>/dev/null
  if [[ -z $KEEP ]]; then cw - close-window >/dev/null 2>&1; fi
  rm -rf "$T"
}
trap finish EXIT
trap 'exit 1' INT TERM

if ! pgrep -qf "Google Chrome.app/Contents/MacOS/Google Chrome"; then
  print "skipped: Chrome is not running (the test never starts it)"
  exit 0
fi
have=(${=$(allwins)})
if (( ${#have} < NEED )); then
  if [[ -z $MAKE ]]; then
    print "skipped: it needs $NEED Chrome windows named \"$NAME\" and ${#have} are open. Run it with \"make\" to let it make them:"
    print "each one puts Chrome in front for about a tenth of a second. With \"keep\" too, it leaves them open for the next run."
    exit 0
  fi
  # at a pause: no key or mouse use for 3 seconds (it goes on after a minute without one)
  for i in {1..120}; do
    (( $(ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {printf "%d", $NF/1000000000; exit}') >= 3 )) && break
    sleep 0.5
  done
  for i in {$(( ${#have} + 1 ))..$NEED}; do DRY= KEY=maker$i cw - url >/dev/null 2>&1; done
  have=(${=$(allwins)})
  check "made the missing windows" $(yes test ${#have} -ge $NEED) "${#have} of $NEED; $(tail -1 "$T/log" 2>/dev/null)"
  grep "opened for" "$T/log" | sed 's/^/      /'
  (( ${#have} >= NEED )) || exit 1
fi
made=$(opened)
rm -rf "$TABS" "$WINS" "$SPARE"   # the windows it found or made start with no record
for w in ${have[$(( NEED + 1 )),-1]}; do cw - raw close-win $w >/dev/null; done   # more than it needs, from an earlier run
have=(${have[1,$NEED]})
front_before=$(front_now)

port=$(/usr/bin/python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
for p in S A B C D H L U; do
  # Each page counts its animation frames and how often it was hidden (only a page that is shown runs frames), and
  # with "ask" in its address it asks to stay when it is left, both ways. A script from an Apple event does not see
  # a page's own variables, so the page writes what it counts on its document, and its handlers in window.name.
  print -r -- "<title>page-$p</title><h1>$p</h1><script>var d=document.documentElement.dataset,hid=document.visibilityState==='hidden'?1:0,frames=0,n=0;d.hid=hid;document.addEventListener('visibilitychange',function(){if(document.visibilityState==='hidden')d.hid=++hid});(function f(){d.frames=++frames;requestAnimationFrame(f)})();if(location.search.indexOf('ask')>=0){window.name='';window.onbeforeunload=function(e){window.name='asked '+(++n);e.preventDefault();return 'x'};window.addEventListener('beforeunload',function(e){window.name='asked '+(++n);e.preventDefault();e.returnValue='x'})}</script>" > "$T/www/$p.html"
done
/usr/bin/python3 -m http.server "$port" --bind 127.0.0.1 --directory "$T/www" >/dev/null 2>&1 &
server=$!
base="http://127.0.0.1:$port"
for i in {1..40}; do curl -s -o /dev/null "$base/S.html" && break; sleep 0.1; done

# --- a window each, from the spare ones ---
for w in ${have[1,3]}; do cw - spare $w; done
check "three windows with no record become spare" $(is "$(spares)" "$(sorted ${have[1,3]})") "$(spares)"
out=$(cw - go "$base/S.html" 2>&1);       check "session: go prints its page" $(is "$out" "page-S"$'\n'"$base/S.html") "$out"
out=$(cw agentA go "$base/A.html" 2>&1);  check "agent A: go prints its page" $(is "$out" "page-A"$'\n'"$base/A.html") "$out"
out=$(cw agentB go "$base/B.html" 2>&1);  check "agent B: go prints its page" $(is "$out" "page-B"$'\n'"$base/B.html") "$out"
ws=$(winof "$SID"); wa=$(winof "$SID.agentA"); wb=$(winof "$SID.agentB")
s=$(tabof "$SID"); a=$(tabof "$SID.agentA"); b=$(tabof "$SID.agentB")
check "three windows of their own" $([[ -n $ws && -n $wa && -n $wb && $ws != $wa && $ws != $wb && $wa != $wb ]] && print ok || print no) "session $ws, A $wa, B $wb"
check "each one's tab is in its own window" $([[ $(tabwin "$SID") == $ws && $(tabwin "$SID.agentA") == $wa && $(tabwin "$SID.agentB") == $wb && $s != $a && $s != $b && $a != $b ]] && print ok || print no)
check "they took the three spare windows: no new window" $([[ $(nspare) == 0 && $(opened) == $made && $(sorted $ws $wa $wb) == $(sorted ${have[1,3]}) ]] && print ok || print no) "$(nspare) spare, $(opened) made"
check "the log says so" $(is "$(logged 'from the spare ones; no new window')" 3)
check "session still on its page" $(is "$(cw - url 2>&1)" "page-S"$'\n'"$base/S.html")
check "agent A still on its page" $(is "$(cw agentA url 2>&1)" "page-A"$'\n'"$base/A.html")
check "a bad agent id counts as no agent" $(is "$(cw '../x' url 2>&1)" "page-S"$'\n'"$base/S.html")
cw - spare ${have[4]}   # the fourth window: for the one that comes and goes below

# --- at the same time: each goes to its own pages, reads back only its own, and its page stays shown ---
worker() {  # worker <agent or -> <page letter> <rounds>
  local who=$1 p=$2 n=$3 i got f1 f2
  for i in {1..$n}; do
    got=$(cw "$who" go "$base/$p.html?round=$i" 2>&1)
    [[ $got == "page-$p"$'\n'"$base/$p.html?round=$i" ]] || print -r -- "go $i: $got" >> "$T/out/$p.bad"
    got=$(cw "$who" url 2>&1)
    [[ $got == "page-$p"$'\n'"$base/$p.html?round=$i" ]] || print -r -- "url $i: $got" >> "$T/out/$p.bad"
    got=$(cw "$who" js 'document.title + " " + location.search + " " + document.visibilityState + " hidden " + document.documentElement.dataset.hid' 2>&1)
    [[ $got == "page-$p ?round=$i visible hidden 0" ]] || print -r -- "js $i: $got" >> "$T/out/$p.hid"
    f1=$(cw "$who" js 'document.documentElement.dataset.frames' 2>&1); f2=$(cw "$who" js 'document.documentElement.dataset.frames' 2>&1)
    [[ $f1 == <-> && $f2 == <-> ]] && (( f2 > f1 + 2 )) || print -r -- "frames $i: $f1 then $f2" >> "$T/out/$p.hid"
  done
}
churn() {  # meanwhile another agent takes the spare window, opens a page and gives the window back, again and again
  local i got
  for i in {1..8}; do
    got=$(cw agentC go "$base/C.html?churn=$i" 2>&1)
    [[ $got == "page-C"$'\n'"$base/C.html?churn=$i" ]] || print -r -- "go $i: $got" >> "$T/out/C.bad"
    print -r -- "$(winof "$SID.agentC")" >> "$T/out/C.wins"
    cw agentC done >/dev/null 2>&1
  done
}
worker - S 5 &
w1=$!
worker agentA A 5 &
w2=$!
worker agentB B 5 &
w3=$!
churn &
w4=$!
wait $w1 $w2 $w3 $w4
for p in S A B; do
  check "at the same time: $p read back only its own page, 5 rounds" $([[ ! -e $T/out/$p.bad ]] && print ok || print no) "$(head -3 "$T/out/$p.bad" 2>/dev/null | tr '\n' ' ')"
  check "at the same time: $p's page stayed shown and ran frames" $([[ ! -e $T/out/$p.hid ]] && print ok || print no) "$(head -3 "$T/out/$p.hid" 2>/dev/null | tr '\n' ' ') (a window that your own windows cover fully has a hidden page)"
done
check "same windows and tabs as before the rounds" $([[ $(winof "$SID") == $ws && $(winof "$SID.agentA") == $wa && $(winof "$SID.agentB") == $wb && $(tabof "$SID") == $s && $(tabof "$SID.agentA") == $a && $(tabof "$SID.agentB") == $b ]] && print ok || print no)
check "the one that came and went: its page each time, 8 times" $([[ ! -e $T/out/C.bad ]] && print ok || print no) "$(head -3 "$T/out/C.bad" 2>/dev/null | tr '\n' ' ')"
check "it got the one spare window each time, never another's" $(is "$(sort -u "$T/out/C.wins" | tr '\n' ' ')" "${have[4]} ") "$(sort -u "$T/out/C.wins" | tr '\n' ' ')"
check "that window is spare again, and no window was made" $([[ $(spares) == ${have[4]} && $(opened) == $made && $(nwins) == $NEED ]] && print ok || print no) "spare: $(spares); $(nwins) windows"

# --- a page that asks "Leave site?" (beforeunload, set both ways): go and done turn its handlers off first ---
fire='(()=>{var e=document.createEvent("BeforeUnloadEvent");e.initEvent("beforeunload",false,true);window.dispatchEvent(e);return window.name+", stays "+(e.defaultPrevented||e.returnValue!=="")})()'
cw agentA go "$base/A.html?ask=1" >/dev/null 2>&1
check "a page's own beforeunload handlers run when nothing stops them" $(is "$(cw agentA js "$fire" 2>&1)" "asked 2, stays true")
out=$(cw agentA go "$base/A.html?left=1" 2>&1)
check "go leaves a page that asks to stay, with no wait" $(is "$out" "page-A"$'\n'"$base/A.html?left=1") "$out"
cw agentA go "$base/A.html?ask=2" >/dev/null 2>&1
cw agentA quiet >/dev/null 2>&1
out=$(cw agentA js "$fire" 2>&1); check "after the step before a close, the page's own handlers are gone: nothing asks to stay" $(is "$out" ", stays false") "$out"
cw agentA go "$base/A.html?ask=3" >/dev/null 2>&1   # its window is given back next, with this page in it: no dialog may wait

# --- done gives back only the caller's window, and the next one gets it, blank ---
out=$(cw agentA done 2>&1)
check "agent A: done says so" $(is "$out" "Closed this agent's tab.") "$out"
now=" $(cw - ids) "
check "agent A: its page is closed, its records gone" $([[ $now != *" $a "* && ! -e $TABS/$SID.agentA && ! -e $WINS/$SID.agentA ]] && print ok || print no) "$now"
check "agent A: its window is spare now, not closed" $([[ " $(spares) " == *" $wa "* && $(nwins) == $NEED ]] && print ok || print no) "spare: $(spares)"
check "session and agent B: still on their pages, in their windows" $([[ $(cw - url 2>&1) == "page-S"$'\n'"$base/S.html?round=5" && $(cw agentB url 2>&1) == "page-B"$'\n'"$base/B.html?round=5" && $(winof "$SID") == $ws && $(winof "$SID.agentB") == $wb ]] && print ok || print no)
out=$(cw agentD url 2>&1)
check "the next agent: a blank tab, with a note" $([[ $out == *"This agent had no tab"* && $out != *"$base"* ]] && print ok || print no) "$out"
check "the next agent got the window given back last, and no window was made" $([[ $(winof "$SID.agentD") == $wa && $(opened) == $made ]] && print ok || print no) "$(winof "$SID.agentD") (A had $wa)"
check "nothing of the last page is in it: a new tab, no history" $([[ $(cw agentD js 'history.length + " " + location.href.indexOf("127.0.0.1")') == "1 -1" && $(tabof "$SID.agentD") != $a ]] && print ok || print no) "$(cw agentD js 'history.length + " " + location.href')"
cw agentD done >/dev/null 2>&1

# --- the agent stopped: agent-done gives back that agent's windows, whatever key its session has ---
KEY=hand-key cw agentB go "$base/H.html" >/dev/null 2>&1
wh=$(winof "hand-key.agentB")
cw - agent-done agentB
check "agent-done: both windows of agent B are spare, its records gone" $([[ -n $wh && $wh != $wb && " $(spares) " == *" $wb "* && " $(spares) " == *" $wh "* && -z "$(print -l "$TABS"/*.agentB(N) "$WINS"/*.agentB(N))" ]] && print ok || print no) "spare: $(spares); B had $wb and $wh"
check "agent-done: the session keeps its window and page" $([[ $(winof "$SID") == $ws && $(cw - url 2>&1) == "page-S"$'\n'"$base/S.html?round=5" ]] && print ok || print no)
cw - agent-done 'no/such' 2>/dev/null; check "agent-done: a bad id is refused" $(is $? 2)
cw - agent-done nobody; check "agent-done: an agent with no window is fine" $(is $? 0)

# --- several ask at the same moment: each spare window goes to one, and no window in use is taken ---
n0=$(nspare)   # 3: A's, B's and the hand key's
racers=()
for r in 1 2 3 4 5; do ( cw racer$r url > "$T/out/race$r" 2>&1; print $? > "$T/out/race$r.rc" ) & racers+=($!); done
wait $racers
got=(); lost=0
for r in 1 2 3 4 5; do
  if [[ $(<"$T/out/race$r.rc") == 0 ]]; then got+=($(winof "$SID.racer$r")); else lost=$((lost + 1)); fi
done
check "5 ask for $n0 spare windows: $n0 get one each, the others get none" $([[ ${#got} == $n0 && ${#${(u)got}} == $n0 && $lost == $((5 - n0)) ]] && print ok || print no) "got: $got; $lost got none"
check "the others are told why, and no window was made" $([[ $(cat "$T"/out/race<->(N) | grep -c "making one failed") == $((5 - n0)) && $(opened) == $made ]] && print ok || print no) "$(cat "$T"/out/race<->(N) | tr '\n' ' ')"
check "the session's window was not taken: it keeps its window and page" $([[ " $got " != *" $ws "* && $(winof "$SID") == $ws && $(cw - url 2>&1) == "page-S"$'\n'"$base/S.html?round=5" ]] && print ok || print no)
for r in 1 2 3 4 5; do cw racer$r done >/dev/null 2>&1; done
check "all given back: $n0 spare again" $(is "$(nspare)" "$n0")

# --- an agent's tab in its session's window, from before each agent had its own window ---
l=$(cw - raw new $ws)
print -r -- "$l $$ $ws" > "$TABS/$SID.agentL"
out=$(cw agentL go "$base/L.html" 2>&1); check "a tab from before: the agent still works in it" $([[ $out == "page-L"$'\n'"$base/L.html" && $(tabwin "$SID.agentL") == $ws && ! -e $WINS/$SID.agentL ]] && print ok || print no) "$out"
check "a tab from before: the session's page is not moved" $(is "$(cw - url 2>&1)" "page-S"$'\n'"$base/S.html?round=5")
cw agentL done >/dev/null 2>&1
now=" $(cw - ids) "
check "a tab from before: done closes that tab only; the window stays the session's" $([[ $now != *" $l "* && $now == *" $s "* && $(winof "$SID") == $ws && " $(spares) " != *" $ws "* ]] && print ok || print no) "$now"
l=$(cw - raw new $ws)
print -r -- "$l $$ $ws" > "$TABS/$SID.agentL"
cw - done >/dev/null 2>&1
now=" $(cw - ids) "
check "the session is done while that tab is open: only its own tab closes" $([[ $now != *" $s "* && $now == *" $l "* && " $(spares) " != *" $ws "* && $(winof "$SID") == $ws ]] && print ok || print no) "$now"
cw - agent-done agentL
out=$(cw - go "$base/S.html?again=1" 2>&1)
check "the session again: a tab in its own window" $([[ $out == "page-S"$'\n'"$base/S.html?again=1" && $(winof "$SID") == $ws && $(tabwin "$SID") == $ws ]] && print ok || print no) "$out"
s=$(tabof "$SID")

# --- cleanup: the window of a session whose process ended goes back; the running session keeps its own ---
ENDED=1 KEY=ended cw - go "$base/C.html" >/dev/null 2>&1
we=$(winof ended); e=$(tabof ended)
cw - cleanup
now=" $(cw - ids) "
check "cleanup: the ended session's page is closed, its records gone" $([[ -n $e && $now != *" $e "* && ! -e $TABS/ended && ! -e $WINS/ended ]] && print ok || print no) "$now"
check "cleanup: its window is spare, not closed" $([[ -n $we && " $(spares) " == *" $we "* && $(nwins) == $NEED ]] && print ok || print no) "spare: $(spares)"
check "cleanup: the running session keeps its window and page" $([[ $(winof "$SID") == $ws && $(cw - url 2>&1) == "page-S"$'\n'"$base/S.html?again=1" ]] && print ok || print no)

# --- no two windows at one place: a window that others cover fully has a hidden page ---
apart() {  # no two windows with their top right corners less than a step from each other
  local w r x y
  local -a rs
  local -aU one
  for w in ${=$(allwins)}; do r=(${=$(cw - raw rect $w)}); rs+=("$r[3] $r[2]"); done   # right, top
  for x in $rs; do for y in $rs; do
    [[ $x == $y ]] && continue
    (( ${x% *} - ${y% *} < STEP && ${y% *} - ${x% *} < STEP && ${x#* } - ${y#* } < STEP && ${y#* } - ${x#* } < STEP )) && return 1
  done; done
  one=($rs)
  (( ${#rs} == ${#one} ))   # and no two at exactly one place
}
all=(${=$(allwins)})
check "the windows are a step apart" $(yes apart) "$(for w in $all; do print -n "$(cw - raw rect $w) | "; done)"
r1=(${=$(cw - raw rect $all[1])}); r2=(${=$(cw - raw rect $all[2])})
cw - raw rect $all[2] $r1 >/dev/null
check "a window put at another's place" $(is "$(cw - raw rect $all[2])" "$r1")
cw - cleanup
r3=(${=$(cw - raw rect $all[2])})
check "cleanup moves it a step down and right, the same size" $([[ $(( r3[1] - r1[1] )) -ge $STEP && $(( r3[2] - r1[2] )) -ge $STEP && $(( r3[3] - r3[1] )) == $(( r1[3] - r1[1] )) && $(( r3[4] - r3[2] )) == $(( r1[4] - r1[2] )) ]] && print ok || print no) "$r1 -> $r3"
check "the windows are a step apart again" $(yes apart)
check "the session's page was not hidden by the moves" $(is "$(cw - js 'document.visibilityState + " " + document.documentElement.dataset.hid' 2>&1)" "visible 0")

if [[ -z $KEEP ]]; then
  # the person's own Chrome, as claude-window finds it: the main process that no test tool started
  cpid=$(ps -axww -o pid=,args= | awk '/Google Chrome.app\/Contents\/MacOS\/Google Chrome( |$)/ && !/--headless|--remote-debugging-|--enable-automation|--user-data-dir|--test-type/ {print $1; exit}')
  # --- the fourth spare window closes ---
  n=$(nwins)
  cw - done >/dev/null 2>&1
  check "a fourth window given back closes: 3 spare, one window fewer" $([[ $(nspare) == 3 && $(nwins) == $((n - 1)) && " $(allwins) " != *" $ws "* && $(logged 'spare ones are there already') == 1 ]] && print ok || print no) "$(nspare) spare, $(nwins) windows"
  # --- a window closed under its owner is replaced, with a note ---
  cw - go "$base/S.html" >/dev/null 2>&1
  ws=$(winof "$SID")
  cw - raw close-win $ws >/dev/null
  out=$(cw - url 2>&1)
  check "window closed under the session: a new blank tab, with a note" $([[ $out == *"This session's tab had been closed"* && $out != *"$base"* ]] && print ok || print no) "$out"
  check "it is in another window, a spare one: no window was made" $([[ -n $(winof "$SID") && $(winof "$SID") != $ws && $(opened) == $made ]] && print ok || print no) "$(winof "$SID")"
  # --- a spare window that nobody took for 30 minutes closes ---
  n=$(nwins); old=(${=$(spares)}); old=$old[1]
  touch -t 200001010000 "$SPARE/$old"
  cw - cleanup
  check "cleanup closes a spare window not taken for 30 minutes, and only that one" $([[ $(nwins) == $((n - 1)) && " $(allwins) " != *" $old "* && ! -e $SPARE/$old && $(logged 'nobody took for 30 minutes') == 1 ]] && print ok || print no) "$(nwins) windows of $n"
  check "cleanup: the session keeps its window" $([[ -n $(winof "$SID") && " $(allwins) " == *" $(winof "$SID") "* ]] && print ok || print no) "$(winof "$SID")"
  # --- a spare window that somebody used (a page in it): not taken, not closed; it loses the name ---
  for k in "$SPARE"/*(N:t); do cw - raw close-win $k >/dev/null; rm -f "$SPARE/$k"; done   # only the session's window is left
  cw agentU go "$base/U.html" >/dev/null 2>&1    # no spare: must fail
  check "no spare window and none may be made: the agent gets none" $(yes test ! -e "$WINS/$SID.agentU")
  cw - go "$base/U.html" >/dev/null 2>&1
  wu=$(winof "$SID")
  print -r -- "$wu $(tabof "$SID") chrome://newtab/" > "$SPARE/$wu"; rm -f "$TABS/$SID" "$WINS/$SID"   # as a spare window in which somebody opened a page
  out=$(cw agentU url 2>&1)
  check "a spare window with a page in it is not given out" $([[ ! -e $WINS/$SID.agentU && $out == *"making one failed"* && ! -e $SPARE/$wu ]] && print ok || print no) "$out"
  check "it is not closed, it loses the name, and the log says so" $([[ " $(allwins) " != *" $wu "* && $(logged 'with a page in it; its name is taken off') == 1 ]] && print ok || print no)
  still=$({ cat "$T/hooks/chrome-ae.js"; print -r -- 'function run(a) { PID = Number(a[0]); var w = obj("cwin", null, "ID  ", D.descriptorWithInt32(Number(a[1]))); var u = get(prop("URL ", prop("acTa", w))); send("core", "clos", {"----": w}); return u }' } | osascript -l JavaScript - "$cpid" "$wu" 2>&1)
  check "it was still open, with its page (the test closes it now)" $(is "$still" "$base/U.html") "$still"
fi

# --- the end: nothing came to the front, no window was made after the start ---
front_after=$(front_now)
# Chrome in front at the end can be the person's own doing; a test window as Chrome's front window can not
check "no test window came to the front" $([[ " $(allwins) " != *" $(cw - raw front) "* ]] && print ok || print no) "$front_before -> $front_after, Chrome's front window $(cw - raw front), test windows $(allwins)"
check "no window was made after the start" $(is "$(opened)" "$made") "$(grep 'opened for' "$T/log" 2>/dev/null | tail -2)"
if [[ -n $KEEP ]]; then
  for f in "$TABS"/*(N:t); do KEY=$f cw - js 'location.replace("about:blank")' >/dev/null 2>&1; done   # no test page stays open
  print "note  $(nwins) windows named \"$NAME\" stay open for the next run (keep)"
else
  cw - close-window >/dev/null 2>&1
  check "no test window is left" $(is "$(allwins)" "") "$(allwins)"
fi

print
if (( failed )); then print "FAILED: $failed"; exit 1; fi
print "all passed"
