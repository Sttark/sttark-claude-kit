#!/usr/bin/env python3
"""claude-link: turns a file on this Mac into a link that opens in the browser.

Claude Code sessions save pictures, pages and PDFs on the Mac, but the person reads the reply in the Claude app,
often on their phone, where a file path opens nothing. With "Links to files" on in Sttark Claude Kit:

    claude-link <file or folder> ...    print a link for each, like http://Your-Mac.local:8732/k3J.../chart.svg

Each link gets its own unguessable folder in Application Support (links/<token>/<name>, a link to the real
file), so the server shows only what a session chose to share, and the link shows the file as it is now.
Links older than 30 days are removed.

    file-links.py --serve               the server itself, run at login by the LaunchAgent com.sttark.claude-file-links
"""
import http.server
import os
import secrets
import shutil
import socketserver
import subprocess
import sys
import time
import urllib.parse

PORT = 8732
ROOT = os.path.expanduser('~/Library/Application Support/SttarkClaudeKit/links')
KEEP_DAYS = 30


def host():
    """The Mac's Bonjour name, which phones and computers on the same network can reach and which doesn't change."""
    name = subprocess.run(['scutil', '--get', 'LocalHostName'], capture_output=True, text=True).stdout.strip()
    return f'{name}.local' if name else 'localhost'


def link(path):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        print(f'claude-link: no such file: {path}', file=sys.stderr)
        return False
    token = secrets.token_urlsafe(12)
    name = os.path.basename(path.rstrip('/')) or 'file'
    os.makedirs(os.path.join(ROOT, token))
    os.symlink(path, os.path.join(ROOT, token, name))
    tail = urllib.parse.quote(name) + ('/' if os.path.isdir(path) else '')
    print(f'http://{host()}:{PORT}/{token}/{tail}')
    return True


def prune():
    cutoff = time.time() - KEEP_DAYS * 86400
    for t in os.listdir(ROOT):
        p = os.path.join(ROOT, t)
        if os.path.isdir(p) and not os.path.islink(p) and os.lstat(p).st_mtime < cutoff:
            shutil.rmtree(p, ignore_errors=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def send_head(self):
        # No list of links at the top or at a token: only someone given a link can open it
        parts = [p for p in urllib.parse.urlsplit(self.path).path.split('/') if p]
        if len(parts) < 2 or '..' in parts:
            self.send_error(404)
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')  # the link shows the file as it is now
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve():
    os.makedirs(ROOT, exist_ok=True)
    prune()
    Server(('', PORT), Handler).serve_forever()


def main():
    args = sys.argv[1:]
    if args == ['--serve']:
        serve()
        return
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.split('\n\n')[1] if not args else __doc__)
        sys.exit(2)
    os.makedirs(ROOT, exist_ok=True)
    ok = all([link(a) for a in args])
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
