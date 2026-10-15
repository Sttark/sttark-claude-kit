#!/bin/bash
# Claude Code PermissionRequest hook, turned on with "Bypass permissions for
# server sessions" in the Sttark Effort menu.
#
# The Claude app, on desktop or phone, switches each session it starts on a
# Remote Control server to Manual or auto, and never offers Bypass permissions
# for those sessions, even when the server was started with
# --permission-mode bypassPermissions. Without this hook there's no way to run
# them in bypass. At a session's first approval prompt, this
# approves it and switches the session to bypass, so no more prompts follow.
# Plan mode, plan approvals and questions to the person are left alone, and so
# is any session whose server wasn't started in bypass. Every switch is logged.
set -uo pipefail
LOG="$HOME/Library/Logs/claude-bypass-hook.log"

input=$(cat)
mode=$(/usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("permission_mode") or "")' <<<"$input")
tool=$(/usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_name") or "")' <<<"$input")

case "$mode" in default|auto|acceptEdits) ;; *) exit 0 ;; esac
case "$tool" in AskUserQuestion|ExitPlanMode) exit 0 ;; esac

# Only when the session's parent chain includes a Remote Control server started in bypass.
pid=$PPID
while [ "${pid:-1}" -gt 1 ]; do
  if ps -ww -o args= -p "$pid" | grep -qE 'claude (rc|remote-control)( .*)? --permission-mode[= ]bypassPermissions'; then
    sid=$(/usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id") or "")' <<<"$input")
    printf '%s session=%s mode=%s tool=%s\n' "$(date '+%F %T')" "$sid" "$mode" "$tool" >>"$LOG"
    echo '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow","updatedPermissions":[{"type":"setMode","mode":"bypassPermissions","destination":"session"}]}}}'
    exit 0
  fi
  pid=$(ps -o ppid= -p "$pid" | tr -d ' ')
done
exit 0
