// The public address a request came from, and whether two requests came
// from the same network: the link page shows its code check when the
// browser is not where the Mac that asked to link is.
//
// Behind nginx every request arrives from 127.0.0.1, so the address is the
// one nginx passes: X-Real-IP, else the last X-Forwarded-For entry (the one
// nginx adds; earlier entries are whatever the client sent). In production a
// loopback address means nginx passed none, so it counts as unknown, and an
// unknown address always shows the code.

type Headers = { get(name: string): string | null };

const LOOPBACK = /^(127\.|::1$|::ffff:127\.)/;

function clean(a: string | null | undefined): string | null {
  const s = (a ?? '').trim().replace(/^\[|\]$/g, '');
  if (!s || s.length > 64) return null;
  return s.startsWith('::ffff:') && s.includes('.') ? s.slice(7) : s;
}

/** The client's address, or null when it cannot be known. `socket` is the
 *  connection's own address (Astro's clientAddress, req.socket.remoteAddress). */
export function clientAddress(headers: Headers, socket: string | null | undefined, env: Record<string, string | undefined> = process.env): string | null {
  const forwarded = headers.get('x-forwarded-for')?.split(',').map((s) => s.trim()).filter(Boolean);
  const a = clean(headers.get('x-real-ip')) ?? clean(forwarded?.at(-1)) ?? clean(socket);
  if (!a) return null;
  if (env.NODE_ENV === 'production' && LOOPBACK.test(a)) return null;
  return a;
}

/** One network: the same IPv4 address (one NAT), or the same IPv6 /64 (a
 *  Mac and its browser can use different temporary addresses in one /64). */
export function sameNetwork(a: string | null, b: string | null): boolean {
  if (!a || !b) return false;
  if (a.includes(':') !== b.includes(':')) return false;
  if (!a.includes(':')) return a === b;
  return prefix64(a) === prefix64(b);
}

function prefix64(v6: string): string | null {
  const [head, tail] = v6.toLowerCase().split('::');
  const h = head ? head.split(':') : [];
  const t = tail !== undefined ? (tail ? tail.split(':') : []) : null;
  const groups = t === null ? h : [...h, ...Array(Math.max(0, 8 - h.length - t.length)).fill('0'), ...t];
  if (groups.length !== 8) return null;
  return groups.slice(0, 4).map((g) => g.replace(/^0+(?=.)/, '')).join(':');
}
