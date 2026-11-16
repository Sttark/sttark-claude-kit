#!/bin/zsh
# Tests claude-window's tabs, on a copy: a temp folder holds a copy of Resources/hooks/claude-window.sh and
# chrome-ae.js, its own tabs folder and log (STTARK_KIT_DIR, STTARK_KIT_LOG) and a small web server on 127.0.0.1
# for the pages. Only a real Chrome can show that tabs do not mix, so the tabs it opens are in your Chrome's
# Claude window, beside the tabs of your sessions, which it never reads or closes; it closes its own at the end.
# It never makes a window, starts Chrome, brings an app to the front or sends a key (STTARK_WINDOW_DRY=1). With
# no Chrome window named Claude, it skips.
#
# It checks: a session and each of its agents get a tab of their own; three of them that work at the same time
# each read back only their own page, also while tabs before theirs in the window close and another agent opens
# and closes a tab; done closes only the caller's tab; agent-done (the browser guard's step when an agent stops)
# closes that agent's tabs only; a tab closed under its owner is replaced, with a note; cleanup closes the tab of
# a session that ended.
# Prints each case; exits 1 if any fails.  Run: zsh tools/claude-window-test.sh
set -u
HERE=${0:A:h}
T=$(mktemp -d -t claude-window-test)
mkdir -p "$T/hooks" "$T/kit" "$T/www" "$T/out"
cp "$HERE/../Resources/hooks/claude-window.sh" "$HERE/../Resources/hooks/chrome-ae.js" "$T/hooks/"
TABS="$T/kit/claude-window-tabs"
WINS="$T/kit/claude-window-wins"
WIN=""
SID="cw-test-$$"
failed=0
made=()   # every tab id the test had a record for

# cw <agent or -> <command...>: the copy, as the test session (agent "-") or as one of its agents.
# KEY=<key> before it stands in for another session; ENDED=1 for a session whose process ended.
cw() {
  local agent=$1 pid=$$; shift
  [[ $agent == - ]] && agent=""
  [[ -n ${ENDED:-} ]] && pid=99999999   # no process has this id
  # Each session has its own window, but a test never makes one: every test session gets a record that names
  # the Claude window that is open already, so their tabs go there.
  [[ -z ${WIN:-} || -e $WINS/${KEY:-$SID} ]] || { mkdir -p "$WINS"; print -r -- "$WIN $$" > "$WINS/${KEY:-$SID}"; }
  env CLAUDE_CODE_SESSION_ID="${KEY:-$SID}" CLAUDE_PID="$pid" CLAUDE_WINDOW_AGENT="$agent" \
      STTARK_KIT_DIR="$T/kit" STTARK_KIT_LOG="$T/log" STTARK_WINDOW_DRY=1 /bin/zsh "$T/hooks/claude-window.sh" "$@"
}
check() {  # check <name> <ok or anything else> [detail]
  if [[ $2 == ok ]]; then print -r -- "ok    $1"; else print -r -- "FAIL  $1  -- ${3:-}"; failed=$((failed + 1)); fi
}
is() { [[ $1 == "$2" ]] && print ok || print no }
record() {  # the tab id in a record
  local id; id=$(cut -d' ' -f1 < "$TABS/$1" 2>/dev/null)
  print -r -- "$id"
}
note() { local f; for f in "$TABS"/*(N); do made+=("$(cut -d' ' -f1 < "$f")"); done }
close_mine() { local f; for f in "$TABS"/*(N); do KEY=${f:t} cw - done >/dev/null 2>&1; done }
finish() {
  close_mine
  [[ -n ${server:-} ]] && kill $server 2>/dev/null
  rm -rf "$T"
}
trap finish EXIT
trap 'exit 1' INT TERM

if [[ $(cw - exists 2>/dev/null) != true ]]; then
  print "skipped: no Chrome window named Claude is open (the test never makes one)"
  exit 0
fi
WIN=${$(cw - wins)[(w)1]}
front_before=$(lsappinfo info -only bundleid "$(lsappinfo front)" 2>/dev/null)

port=$(/usr/bin/python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
for p in S A B C H; do print -r -- "<title>page-$p</title><h1>$p</h1>" > "$T/www/$p.html"; done
/usr/bin/python3 -m http.server "$port" --bind 127.0.0.1 --directory "$T/www" >/dev/null 2>&1 &
server=$!
base="http://127.0.0.1:$port"
for i in {1..40}; do curl -s -o /dev/null "$base/S.html" && break; sleep 0.1; done
before=" $(cw - ids) "

# Tabs of other sessions that are in the window first, so they are before the test's tabs in the window. Each one
# that closes later moves every tab after it one place: the case of an agent that stops while others work.
FILLERS=8
for i in {1..$FILLERS}; do KEY=filler$i cw - url >/dev/null 2>&1; done
note

# --- a tab each ---
out=$(cw - go "$base/S.html" 2>&1);       check "session: go prints its page" $(is "$out" "page-S"$'\n'"$base/S.html") "$out"
out=$(cw agentA go "$base/A.html" 2>&1);  check "agent A: go prints its page" $(is "$out" "page-A"$'\n'"$base/A.html") "$out"
out=$(cw agentB go "$base/B.html" 2>&1);  check "agent B: go prints its page" $(is "$out" "page-B"$'\n'"$base/B.html") "$out"
s=$(record "$SID"); a=$(record "$SID.agentA"); b=$(record "$SID.agentB"); note
check "three records, three tabs" $([[ -n $s && -n $a && -n $b && $s != $a && $s != $b && $a != $b ]] && print ok || print no) "session $s, A $a, B $b"
check "session still on its page" $(is "$(cw - url 2>&1)" "page-S"$'\n'"$base/S.html")
check "agent A still on its page" $(is "$(cw agentA url 2>&1)" "page-A"$'\n'"$base/A.html")
check "a bad agent id counts as no agent" $(is "$(cw '../x' url 2>&1)" "page-S"$'\n'"$base/S.html")

# --- at the same time: each goes to its own pages and reads back only its own ---
worker() {  # worker <agent or -> <page letter> <rounds>
  local who=$1 p=$2 n=$3 i got
  for i in {1..$n}; do
    got=$(cw "$who" go "$base/$p.html?round=$i" 2>&1)
    [[ $got == "page-$p"$'\n'"$base/$p.html?round=$i" ]] || print -r -- "go $i: $got" >> "$T/out/$p.bad"
    got=$(cw "$who" url 2>&1)
    [[ $got == "page-$p"$'\n'"$base/$p.html?round=$i" ]] || print -r -- "url $i: $got" >> "$T/out/$p.bad"
    got=$(cw "$who" js 'document.title + " " + location.search' 2>&1)
    [[ $got == "page-$p ?round=$i" ]] || print -r -- "js $i: $got" >> "$T/out/$p.bad"
  done
}
churn() {  # meanwhile the earlier tabs close one by one, and another agent opens a tab and closes it, again and again
  local i
  for i in {1..$FILLERS}; do
    KEY=filler$i cw - done >/dev/null 2>&1
    cw agentC go "$base/C.html?churn=$i" >/dev/null 2>&1
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
done
check "same tabs as before the rounds" $([[ $(record "$SID") == $s && $(record "$SID.agentA") == $a && $(record "$SID.agentB") == $b ]] && print ok || print no)

# --- a page that asks "Leave site?" (beforeunload, set both ways): go and done turn its handlers off first ---
setb='(()=>{window.__asked=0;window.onbeforeunload=function(e){window.__asked++;e.preventDefault();return "x"};window.addEventListener("beforeunload",function(e){window.__asked++;e.preventDefault();e.returnValue="x"});return "set"})()'
fire='(()=>{var e=document.createEvent("BeforeUnloadEvent");e.initEvent("beforeunload",false,true);window.dispatchEvent(e);return "asked "+window.__asked+", stays "+(e.defaultPrevented||e.returnValue!=="")+", property "+(window.onbeforeunload?"set":"off")})()'
cw agentA js "$setb" >/dev/null
check "a page's own beforeunload handlers run when nothing stops them" $(is "$(cw agentA js "$fire")" "asked 2, stays true, property set")
cw agentA js 'window.__asked=0' >/dev/null
out=$(cw agentA go "$base/A.html?left=1" 2>&1)
check "go leaves a page that asks to stay, with no wait" $(is "$out" "page-A"$'\n'"$base/A.html?left=1") "$out"
cw agentA js "$setb" >/dev/null
cw agentA quiet >/dev/null 2>&1
out=$(cw agentA js "$fire" 2>&1); check "after the quiet step, no handler can ask to stay" $(is "$out" "asked 1, stays false, property off") "$out"
cw agentA go "$base/A.html?round=5" >/dev/null 2>&1

# --- done closes only the caller's tab ---
out=$(cw agentA done 2>&1)
check "agent A: done says so" $(is "$out" "Closed this agent's tab.") "$out"
now=" $(cw - ids) "
check "agent A: its tab is closed, its record gone" $([[ $now != *" $a "* && ! -e $TABS/$SID.agentA ]] && print ok || print no) "$now"
check "session and agent B: tabs still open" $([[ $now == *" $s "* && $now == *" $b "* ]] && print ok || print no) "$now"
check "agent B still on its page" $(is "$(cw agentB url 2>&1)" "page-B"$'\n'"$base/B.html?round=5")
check "session still on its page" $(is "$(cw - url 2>&1)" "page-S"$'\n'"$base/S.html?round=5")
out=$(cw agentA url 2>&1)
check "agent A after done: a new blank tab, with a note" $([[ $out == *"This agent had no tab"* && $out != *"$base"* ]] && print ok || print no) "$out"

# --- the agent stopped: agent-done closes that agent's tabs, whatever key its session has ---
KEY=hand-key cw agentB go "$base/H.html" >/dev/null 2>&1
h=$(record "hand-key.agentB"); a2=$(record "$SID.agentA"); note
cw - agent-done agentB
now=" $(cw - ids) "
check "agent-done: both tabs of agent B closed, records gone" $([[ -n $h && $now != *" $b "* && $now != *" $h "* && -z "$(print -l "$TABS"/*.agentB(N))" ]] && print ok || print no) "$now"
check "agent-done: the session's tab and agent A's stay" $([[ $now == *" $s "* && $now == *" $a2 "* ]] && print ok || print no) "$now"
cw - agent-done 'no/such' 2>/dev/null; check "agent-done: a bad id is refused" $(is $? 2)
cw - agent-done nobody; check "agent-done: an agent with no tab is fine" $(is $? 0)

# --- a tab closed under its owner is replaced, with a note ---
cp "$TABS/$SID" "$TABS/other"   # another key that points at the session's tab
KEY=other cw - done >/dev/null 2>&1
out=$(cw - url 2>&1)
check "tab closed under the session: a new blank tab, with a note" $([[ $out == *"This session's tab had been closed"* && $out != *"$base"* ]] && print ok || print no) "$out"
check "the session's new tab is another tab" $([[ -n $(record "$SID") && $(record "$SID") != $s ]] && print ok || print no)

# --- cleanup closes the tab of a session whose process ended, and leaves the others ---
ENDED=1 KEY=ended cw - go "$base/C.html" >/dev/null 2>&1
e=$(record ended); s2=$(record "$SID"); note
cw - cleanup
now=" $(cw - ids) "
check "cleanup: the ended session's tab is closed" $([[ -n $e && $now != *" $e "* && ! -e $TABS/ended ]] && print ok || print no) "$now"
check "cleanup: the running session's tab stays" $([[ $now == *" $s2 "* && -e $TABS/$SID ]] && print ok || print no) "$now"

# --- the end: every test tab closed, nothing came to the front, no window made ---
note; close_mine
after=" $(cw - ids) "
left=""; for id in ${(u)made}; do [[ $after == *" $id "* ]] && left+=" $id"; done
check "no test tab is left" $([[ -z $left ]] && print ok || print no) "still open:$left"
lost=""; for id in ${=before}; do [[ $after == *" $id "* ]] || lost+=" $id"; done
[[ -z $lost ]] || print -r -- "note  closed since the start, and not by this test:$lost (a session of yours closed its tab)"
front_after=$(lsappinfo info -only bundleid "$(lsappinfo front)" 2>/dev/null)
check "Chrome did not come to the front" $([[ $front_after != *com.google.Chrome* || $front_before == *com.google.Chrome* ]] && print ok || print no) "$front_before -> $front_after"
check "no window was made" $([[ ! -s $T/log ]] && print ok || print no) "$(cat "$T/log" 2>/dev/null)"

print
if (( failed )); then print "FAILED: $failed"; exit 1; fi
print "all passed"
