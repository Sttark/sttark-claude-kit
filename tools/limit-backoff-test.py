"""Test the usage read back-off on copies when the server allows a read only now and then: a good read between two
429s keeps the count of failed reads, so the reads back off (2, 4, 8 min) instead of failing every 2 minutes, and a
read is good for a minute, not 15 seconds, near a limit after a failure."""
import http.server, importlib.util, json, os, tempfile, threading, time

d = tempfile.mkdtemp()
usage = d + '/usage-test.json'
json.dump({'extra_usage': {'is_enabled': True}, 'limits': [
    {'kind': 'weekly_all', 'percent': 93, 'resets_at': '2099-01-01T00:00:00+00:00'}]}, open(usage, 'w'))
os.environ.update(STTARK_KIT_DIR=d, STTARK_KIT_LOG=d + '/log')
here = os.path.dirname(os.path.abspath(__file__))
fails = 0


def load():
    spec = importlib.util.spec_from_file_location('lh', os.path.join(here, '../Resources/hooks/limit-hook.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    fails += not ok


# a server that allows a read only now and then: good, 429, good, 429...
hits = []


class S(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(time.time())
        if len(hits) % 2:
            self.send_response(429)
            self.end_headers()
            return
        b = open(usage, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


srv = http.server.HTTPServer(('127.0.0.1', 0), S)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ['STTARK_LIMIT_URL'] = f'http://127.0.0.1:{srv.server_port}/'
lh = load()
waits = []
for _ in range(3):
    lh.usage()   # 429
    k = json.load(open(lh.USAGE))
    waits.append(round(k['retry_at'] - time.time()))
    k['retry_at'] = 0                          # skip the wait
    k['at'] = 0
    json.dump(k, open(lh.USAGE, 'w'))
    lh.usage()   # good read
    k = json.load(open(lh.USAGE))
    check('a good read keeps the failed count', k.get('fails', 0) >= 1)
    check('near the limit after a failure, a read is good for FRESH_SLOW, not 15 s',
          lh.good_for(k, k['usage'], None) == lh.FRESH_SLOW)
    k['at'] = 0
    json.dump(k, open(lh.USAGE, 'w'))
print('back-off after each 429 (s):', waits)
check('the back-off doubles across good reads', waits[0] < waits[1] < waits[2])
k['failed_at'] = time.time() - lh.CALM - 1
check('the count ends CALM after the last failure', lh.calm(k) == {})
print('FAILED' if fails else 'all passed')
raise SystemExit(1 if fails else 0)
