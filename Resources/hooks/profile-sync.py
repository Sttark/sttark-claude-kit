#!/usr/bin/env python3
"""Copy the instructions from the Claude app's Profile settings into ~/.claude/CLAUDE.md.

Turned on with "Sync Claude profile instructions" in the Sttark Effort menu, which runs this every 15 minutes
(and profile-hook.sh runs it in the background when a prompt arrives and the last run is over a minute old).

Claude Code reads CLAUDE.md files; it doesn't read the "Instructions for Claude" box in the Claude app's
Profile settings. Those live on Anthropic's servers, so this asks for them with the Claude desktop app's own
sign-in cookie. Plain script requests get Cloudflare's bot check, so the request goes through curl_cffi, which
connects the way Chrome does. If that fails and a claude.ai tab is already open in Google Chrome, it reads
through that tab; it never opens one.

Before writing, it checks that the account answering is the one the Claude app is signed in to. It reads only
that account and writes one block in one file. The cookie stays in memory: never logged, never saved.
"""
import hashlib, json, sqlite3, subprocess, sys, tempfile, time
from pathlib import Path

TARGET = Path.home() / ".claude/CLAUDE.md"
APP_DIR = Path.home() / "Library/Application Support/Claude"
APP_CONFIG = APP_DIR / "config.json"
TRIED = Path.home() / "Library/Application Support/SttarkEffort/profile-sync.tried"  # every run; the prompt hook spaces runs by it
PROFILE_URL = "https://claude.ai/api/account_profile"
MARK_BEGIN = "<!-- profile-sync:begin -->"
MARK_END = "<!-- profile-sync:end -->"


def app_session_key() -> str:
    """The Claude app's sessionKey cookie, decrypted with its keychain password."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    pw = subprocess.run(["security", "find-generic-password", "-w", "-s", "Claude Safe Storage"],
                        capture_output=True, text=True, check=True).stdout.strip()
    key = hashlib.pbkdf2_hmac("sha1", pw.encode(), b"saltysalt", 1003, 16)
    # Copy first: the app holds the db open and SQLite will refuse a shared lock.
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Cookies"
        copy.write_bytes((APP_DIR / "Cookies").read_bytes())
        row = sqlite3.connect(copy).execute(
            "SELECT encrypted_value FROM cookies "
            "WHERE host_key='.claude.ai' AND name='sessionKey'").fetchone()
    if not row:
        raise RuntimeError("no sessionKey cookie in the Claude app")
    blob = row[0]
    if not blob.startswith(b"v10"):
        raise RuntimeError(f"unexpected cookie encryption version {blob[:3]!r}")
    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plain = dec.update(blob[3:]) + dec.finalize()
    plain = plain[: -plain[-1]]                       # strip PKCS7 padding
    # Chromium >= 130 prefixes the plaintext with a 32-byte domain hash.
    if len(plain) > 32 and not plain[:32].decode("utf8", "ignore").isprintable():
        plain = plain[32:]
    return plain.decode("utf8", "ignore").lstrip("\x00")


def read_direct(want: str) -> str:
    from curl_cffi import requests
    jar = {"sessionKey": app_session_key()}

    def get(path):
        r = requests.get("https://claude.ai" + path, cookies=jar, impersonate="chrome", timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"{path} gave HTTP {r.status_code}")
        return r.json()

    acct = get("/api/account")
    if acct.get("uuid") != want:
        raise RuntimeError("the app's cookie answers for another account")
    text = (get("/api/account_profile").get("conversation_preferences") or "").strip()
    if not text:
        raise RuntimeError("the profile has no instructions")
    return text


def osa(script: str, *args: str) -> str:
    r = subprocess.run(["osascript", "-e", script, *args],
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or f"osascript exit {r.returncode}")
    return r.stdout.rstrip("\n")


def in_tab(verb: str, wid: str, tid: str, *rest: str) -> str:
    """Run `verb` against one tab, e.g. 'return loading of' or 'close'."""
    tail = " javascript (item 3 of argv)" if rest else ""
    return osa("on run argv\n"
               f'tell application "Google Chrome" to {verb} tab id (item 2 of argv as integer) '
               f"of window id (item 1 of argv as integer){tail}\n"
               "end run", wid, tid, *rest)


def get_json(wid: str, tid: str, path: str):
    """Same-origin GET from inside the tab, so it carries Chrome's cookies and clearance."""
    code = ("(()=>{const x=new XMLHttpRequest();x.open('GET',%s,false);x.send();"
            "return x.status+'\\n'+x.responseText})()" % json.dumps(path))
    for attempt in range(3):
        status, _, body = in_tab("return execute", wid, tid, code).partition("\n")
        if status == "200":
            return json.loads(body)
        time.sleep(2)  # a Cloudflare check may still be finishing in the tab
    raise RuntimeError(f"{path} gave HTTP {status} in Chrome")


def read_through(wid: str, tid: str, want: str) -> str:
    acct = get_json(wid, tid, "/api/account")
    if acct.get("uuid") != want:
        raise RuntimeError(f"Chrome is signed in to {acct.get('email_address')}, "
                           "not the Claude app's account")
    text = (get_json(wid, tid, "/api/account_profile").get("conversation_preferences") or "").strip()
    if not text:
        raise RuntimeError("the profile has no instructions")
    return text


def claude_tabs() -> list:
    out = osa('tell application "Google Chrome"\n'
              'set out to ""\n'
              'repeat with w in windows\n'
              'repeat with t in tabs of w\n'
              'if (URL of t starts with "https://claude.ai/") and not (loading of t) then '
              'set out to out & (id of w) & " " & (id of t) & linefeed\n'
              'end repeat\n'
              'end repeat\n'
              'return out\n'
              'end tell')
    return [line.split() for line in out.splitlines() if line.strip()]


def read_profile() -> str:
    want = json.loads(APP_CONFIG.read_text()).get("lastKnownAccountUuid")
    if not want:
        raise RuntimeError(f"no lastKnownAccountUuid in {APP_CONFIG}")
    errors = []
    try:
        return read_direct(want)
    except Exception as e:
        errors.append(f"direct: {e}")
    # Fallback: a claude.ai tab that is already open. Never open one.
    # Checking this way never launches Chrome; `tell application` would.
    if osa('return application "Google Chrome" is running') == "true":
        for wid, tid in claude_tabs():
            try:
                return read_through(wid, tid, want)
            except Exception as e:
                errors.append(f"claude.ai tab: {e}")
    raise RuntimeError("; ".join(errors))


def write(text: str) -> str:
    block = (f"{MARK_BEGIN}\n"
             f"<!-- Synced from the Claude app Profile settings ({PROFILE_URL}).\n"
             f"     Edit them there, not here: this block is overwritten. -->\n\n"
             f"{text}\n{MARK_END}")
    existing = TARGET.read_text() if TARGET.exists() else ""
    if MARK_BEGIN in existing and MARK_END in existing:
        head, rest = existing.split(MARK_BEGIN, 1)
        tail = rest.split(MARK_END, 1)[1]
        new = head + block + tail
    else:
        new = (existing.rstrip() + "\n\n" if existing.strip() else "") + block + "\n"
    if new == existing:
        return "up to date"
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(new)
    return f"updated {TARGET} ({len(text)} chars)"


def main():
    TRIED.touch()
    try:
        result = write(read_profile())
    except Exception as e:
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "failed:", e, flush=True)
        sys.exit(1)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), result, flush=True)


if __name__ == "__main__":
    main()
