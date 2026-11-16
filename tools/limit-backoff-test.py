"""Test the usage read back-off on copies when the server allows a read only now and then: a good read between two
429s keeps the count of failed reads, so the reads back off (2, 4, 8 min) instead of failing every 2 minutes, and a
read is good for 5 minutes for 30 minutes after a failure, and near a limit for 2 minutes, not 15 seconds, for
6 hours after it."""
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
    waits.append(round(k['next_read'] - time.time()))
    k['next_read'] = 0                          # skip the wait
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
check('after CALM, near a limit, a read is good for FRESH, not 15 s, while a read failed in the last NEAR_CALM',
      lh.good_for(k, k['usage'], None) == lh.FRESH)
check('a good read after CALM keeps the last failure for NEAR_CALM', 'last_failed_at' in lh.kept(k) and 'fails' not in lh.kept(k))
k['last_failed_at'] = time.time() - lh.NEAR_CALM - 1
check('NEAR_CALM after the last failure, near a limit, a read is good for 15 s again',
      lh.good_for(k, k['usage'], None) == lh.FRESH_NEAR and lh.kept({**k, 'failed_at': k['last_failed_at']}) == {})
old = {'usage': k['usage'], 'at': time.time(), 'fails': 1, 'failed_at': time.time() - lh.CALM - 1}
check('a cache from the last Kit (failed_at, no last_failed_at) counts the same', lh.good_for({**old, **lh.kept(old)}, old['usage'], None) == lh.FRESH)
print('FAILED' if fails else 'all passed')
raise SystemExit(1 if fails else 0)
