"""Test the usage read back-off on copies: a local stand-in server answers 429 with Retry-After: 300.
Many hook calls must make one request, keep the last good read, and log once."""
import http.server, importlib.util, json, os, tempfile, threading, time

hits = []


class S(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(time.time())
        self.send_response(429)
        self.send_header('Retry-After', '300')
        self.end_headers()

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(('127.0.0.1', 0), S)
threading.Thread(target=srv.serve_forever, daemon=True).start()
d = tempfile.mkdtemp()
os.environ.update(STTARK_KIT_DIR=d, STTARK_KIT_LOG=d + '/log', STTARK_LIMIT_URL=f'http://127.0.0.1:{srv.server_port}/')
spec = importlib.util.spec_from_file_location(
    'lh', os.path.join(os.path.dirname(os.path.abspath(__file__)), '../Resources/hooks/limit-hook.py'))
lh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lh)
good = {'extra_usage': {'is_enabled': True}, 'limits': [{'kind': 'session', 'is_active': True, 'percent': 100,
                                                         'resets_at': '2099-01-01T00:00:00+00:00'}]}
json.dump({'at': time.time() - 3600, 'usage': good}, open(lh.USAGE, 'w'))   # an old good read
got = [lh.usage() for _ in range(50)]
c = json.load(open(lh.USAGE))
print('requests:', len(hits))
print('every call kept the last good read:', all(g == good for g in got))
print('next read in s:', round(c['retry_at'] - time.time()))
print('still at the limit (no guess):', lh.wall(got[-1]) is not None)
print(open(d + '/log').read().strip())
