// Web Push for Needs you (phone/DESIGN.md section 5): the server's key pair,
// each phone's subscription with its own on and off, and the sender.
//
// A Mac sends `remind` when a session has needed its person for 10 minutes
// and they are away from that Mac; the Mac decides, so a reminder is a Mac
// notice or a push, never both. The server then sends one push to each of
// the person's phones with notices on, and skips it when:
//   - no key pair is set (VAULT_VAPID_PUBLIC_KEY, VAULT_VAPID_PRIVATE_KEY);
//   - no phone of theirs has notices on;
//   - it sent this one already: pushes_sent keeps the person, the session
//     and its waiting time for 2 days (lib/expiry.ts), so a reconnect or a
//     second Mac never sends it twice;
//   - one of their pages is visible: the page shows the session already
//     (the hub says so with the reminder).
// A subscription the push service says is gone (404, 410) is dropped, with a
// record. Each payload is encrypted for its phone (web-push, RFC 8291) and
// signed with the key pair (VAPID, RFC 8292), so the push service sees only
// the endpoint. Each push has the tag needs-<cse>, so a newer one replaces
// the old one on the phone.
//
// Turning notices on or off, on one phone, is a change with a record. Menu
// says when it was last done. Sign out ends the phone's subscription
// (lib/session.ts). A subscription belongs to the address it was made at
// (its service worker's): at start, one made at another address ends, with
// a record (endOtherAddresses).
import { createHash } from 'node:crypto';
import { generateRequestDetails, generateVAPIDKeys, type RequestDetails } from 'web-push';
import { db } from './db.ts';
import { addRecord } from './records.ts';
import { events } from './events.ts';
import { appOrigin, appUrl, siteName } from './paths.ts';
import { lastSnapshot, macsOf } from './macs.ts';
import { span } from '../view/time.ts';

/** Here so the tests can change them. */
export const settings = {
  /** A push the phone has not taken in this long is dropped by its push
   *  service: a reminder an hour old says little. */
  ttlS: 60 * 60,
  /** A push service that does not answer in this long: that push failed. */
  timeoutMs: 10_000,
};

const nowS = () => Math.floor(Date.now() / 1000);
const B64URL = /^[A-Za-z0-9_-]+={0,2}$/;
const bytes = (s: string) => (B64URL.test(s) ? Buffer.from(s.replace(/=+$/, ''), 'base64url') : Buffer.alloc(0));

// ---------- the key pair ----------

export type Vapid = { publicKey: string; privateKey: string; subject: string };

/** A P-256 public key (65 bytes, uncompressed) and private key (32 bytes),
 *  base64url, as web-push makes them. */
export function validPair(publicKey: string, privateKey: string): boolean {
  const pub = bytes(publicKey);
  return pub.length === 65 && pub[0] === 4 && bytes(privateKey).length === 32;
}

let warned = '';

/** The key pair the pushes are signed with: from the environment. A local
 *  run (not production) without one makes its own and keeps it in the
 *  database, so a phone page tried locally stays subscribed across restarts.
 *  Null when production has none, or a bad one: notices are not set up. */
export function vapid(env: Record<string, string | undefined> = process.env): Vapid | null {
  const subject = appOrigin().startsWith('https://') ? appOrigin() : 'https://kit.sttark.com';
  const pub = (env.VAULT_VAPID_PUBLIC_KEY ?? '').trim();
  const priv = (env.VAULT_VAPID_PRIVATE_KEY ?? '').trim();
  if (pub || priv) {
    if (validPair(pub, priv)) return { publicKey: pub.replace(/=+$/, ''), privateKey: priv.replace(/=+$/, ''), subject };
    if (warned !== pub) console.error('[push] ALERT: VAULT_VAPID_PUBLIC_KEY or VAULT_VAPID_PRIVATE_KEY is not a P-256 key in base64url: no notices go out');
    warned = pub;
    return null;
  }
  if (env.NODE_ENV === 'production') return null;
  const row = db().prepare("SELECT value FROM meta WHERE key = 'dev_vapid'").get() as { value: string } | undefined;
  if (row) {
    const k = JSON.parse(row.value) as { publicKey: string; privateKey: string };
    if (validPair(k.publicKey, k.privateKey)) return { ...k, subject };
  }
  const k = generateVAPIDKeys();
  db().prepare("INSERT OR REPLACE INTO meta (key, value) VALUES ('dev_vapid', ?)").run(JSON.stringify(k));
  return { publicKey: k.publicKey, privateKey: k.privateKey, subject };
}

/** The public key a page subscribes with, or null when notices are not set
 *  up on this server. */
export function pushKey(): string | null {
  return vapid()?.publicKey ?? null;
}

// ---------- subscriptions ----------

/** The push services of the browsers people use: Chrome and Android (and
 *  Samsung Internet), Safari and iPhone, Firefox, Edge. A subscription for
 *  any other host is refused, so nobody can make the server post to an
 *  address of their choosing. */
const PUSH_HOSTS = ['fcm.googleapis.com', 'push.apple.com', 'push.services.mozilla.com', 'notify.windows.com'];
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

/** Is this an endpoint the server sends to? A local run also takes a
 *  stand-in push service on this computer (tools/push-sink.mjs). */
export function allowedEndpoint(raw: unknown, env: Record<string, string | undefined> = process.env): raw is string {
  if (typeof raw !== 'string' || raw.length > 1024) return false;
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    return false;
  }
  if (u.username || u.password) return false;
  const host = u.hostname.toLowerCase();
  if (u.protocol === 'https:' && PUSH_HOSTS.some((h) => host === h || host.endsWith(`.${h}`))) return true;
  return env.NODE_ENV !== 'production' && (u.protocol === 'http:' || u.protocol === 'https:') && LOCAL_HOSTS.has(host);
}

/** The kind of device, from its browser, for the records: iPhone, Android
 *  phone, Mac. An iPad with a desktop browser says Mac. */
export function deviceOf(ua: string | null | undefined): string {
  const a = ua ?? '';
  if (/iPad/.test(a)) return 'iPad';
  if (/iPhone|iPod/.test(a)) return 'iPhone';
  if (/Android/.test(a)) return /Mobile/.test(a) ? 'Android phone' : 'Android tablet';
  if (/CrOS/.test(a)) return 'Chromebook';
  if (/Macintosh|Mac OS X/.test(a)) return 'Mac';
  if (/Windows/.test(a)) return 'Windows computer';
  if (/Linux/.test(a)) return 'Linux computer';
  return 'browser';
}

type SubRow = { endpoint: string; email: string; web_session: string | null; p256dh: string; auth: string; notices: number; created_at: number; changed_at: number | null; device: string | null; site: string | null };
const subRow = (endpoint: string) => db().prepare('SELECT * FROM push_subs WHERE endpoint = ?').get(endpoint) as SubRow | undefined;

/** How many of this person's phones can get a push now (welcome, phones). */
export function phonesFor(email: string): number {
  const n = (db().prepare('SELECT count(*) AS n FROM push_subs WHERE email = ? AND notices = 1').get(email) as { n: number }).n;
  return Math.min(50, n);
}

/** This phone as the page asks about it: does the server know its
 *  subscription, is it on, and since when. */
export type PhoneNotices = { known: boolean; on: boolean; since: number | null };

export function noticesOf(email: string, endpoint: string): PhoneNotices {
  const r = subRow(endpoint);
  if (!r || r.email !== email) return { known: false, on: false, since: null };
  return { known: true, on: r.notices === 1, since: r.changed_at ?? r.created_at };
}

/** The newest subscription made under this sign-in, for Menu's first
 *  drawing; the page then asks about the subscription its browser holds. */
export function noticesOfSignIn(webSession: string | null): { on: boolean; since: number } | null {
  if (!webSession) return null;
  const r = db().prepare('SELECT notices, created_at, changed_at FROM push_subs WHERE web_session = ? ORDER BY COALESCE(changed_at, created_at) DESC LIMIT 1').get(webSession) as
    | { notices: number; created_at: number; changed_at: number | null }
    | undefined;
  return r ? { on: r.notices === 1, since: r.changed_at ?? r.created_at } : null;
}

export type Refused = { ok: false; status: number; words: string };
export type Done = { ok: true; on: boolean; since: number };

const NOT_SET_UP = 'Notices are not set up on this server yet.';
const UNKNOWN = 'This phone is not set up for notices now. Turn them on again.';

/** A subscription from a phone (PushSubscription.toJSON(), and `old` when
 *  the browser replaced one). A new one turns notices on: only a tap on the
 *  switch makes one. One that replaces an old one keeps its on or off. An
 *  endpoint is one browser on one phone: the person who subscribes it last
 *  gets its notices. */
export function subscribe(user: { email: string; name: string }, webSession: string | null, body: unknown, ua?: string | null, now = nowS()): Done | Refused {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, status: 400, words: 'Send the subscription as JSON.' };
  const { endpoint, keys, old, expirationTime, ...extra } = body as Record<string, unknown>;
  void expirationTime;
  const k = (keys ?? {}) as Record<string, unknown>;
  const keyNames = keys && typeof keys === 'object' && !Array.isArray(keys) ? Object.keys(k).sort().join(',') : '';
  if (Object.keys(extra).length || keyNames !== 'auth,p256dh' || typeof k.p256dh !== 'string' || typeof k.auth !== 'string' || (old != null && typeof old !== 'string')) {
    return { ok: false, status: 400, words: 'That is not a subscription from a browser.' };
  }
  const p256dh = bytes(k.p256dh);
  if (p256dh.length !== 65 || p256dh[0] !== 4 || bytes(k.auth).length !== 16) return { ok: false, status: 400, words: 'That is not a subscription from a browser.' };
  if (!vapid()) return { ok: false, status: 503, words: NOT_SET_UP };
  if (!allowedEndpoint(endpoint)) return { ok: false, status: 400, words: 'This browser uses a push service the Kit does not send to.' };
  const device = deviceOf(ua);
  const d = db();
  const out = d.transaction((): { on: boolean; since: number; before: SubRow | undefined; renewed: SubRow | undefined } => {
    const before = subRow(endpoint);
    const replaced = old && old !== endpoint ? subRow(old) : undefined;
    const renewed = replaced && replaced.email === user.email ? replaced : undefined;
    const notices = renewed ? renewed.notices : 1;
    const since = renewed ? (renewed.changed_at ?? renewed.created_at) : now;
    d.prepare(
      `INSERT INTO push_subs (endpoint, email, web_session, p256dh, auth, notices, created_at, changed_at, device, site) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(endpoint) DO UPDATE SET email = excluded.email, web_session = excluded.web_session, p256dh = excluded.p256dh, auth = excluded.auth,
         notices = excluded.notices, changed_at = excluded.changed_at, device = excluded.device, site = excluded.site`,
    ).run(endpoint, user.email, webSession, k.p256dh, k.auth, notices, now, since, device, siteName());
    if (renewed) d.prepare('DELETE FROM push_subs WHERE endpoint = ?').run(renewed.endpoint);
    const was = before && before.email === user.email ? before.notices === 1 : renewed ? renewed.notices === 1 : false;
    addRecord({
      at: now, who: user.email, whoName: user.name, action: 'notices',
      before: { notices: was, ...(before && before.email !== user.email ? { other_person: true } : {}) },
      after: { notices: notices === 1, device },
      result: 'ok',
      words: renewed ? `The browser on ${device} renewed its Needs you notices.` : `Turned Needs you notices on for ${device}.`,
    });
    return { on: notices === 1, since, before, renewed };
  })();
  console.log(`[push] ${user.email}: notices ${out.renewed ? 'renewed' : 'on'} for ${device}`);
  events.emit('push-subs-changed', { email: user.email });
  if (out.before && out.before.email !== user.email) events.emit('push-subs-changed', { email: out.before.email });
  return { ok: true, on: out.on, since: out.since };
}

/** Menu > Notices on this phone: on or off. The person's own subscription
 *  only. */
export function setNotices(user: { email: string; name: string }, endpoint: unknown, on: unknown, now = nowS()): Done | Refused {
  if (typeof endpoint !== 'string' || typeof on !== 'boolean') return { ok: false, status: 400, words: 'Send the endpoint and on, true or false.' };
  const r = subRow(endpoint);
  if (!r || r.email !== user.email) return { ok: false, status: 404, words: UNKNOWN };
  if (on && !vapid()) return { ok: false, status: 503, words: NOT_SET_UP };
  const device = r.device ?? 'this phone';
  if ((r.notices === 1) !== on) {
    const d = db();
    d.transaction(() => {
      d.prepare('UPDATE push_subs SET notices = ?, changed_at = ? WHERE endpoint = ?').run(on ? 1 : 0, now, endpoint);
      addRecord({
        at: now, who: user.email, whoName: user.name, action: 'notices', before: { notices: !on }, after: { notices: on, device }, result: 'ok',
        words: on ? `Turned Needs you notices on for ${device}.` : `Turned Needs you notices off for ${device}.`,
      });
    })();
    console.log(`[push] ${user.email}: notices ${on ? 'on' : 'off'} for ${device}`);
    events.emit('push-subs-changed', { email: user.email });
    return { ok: true, on, since: now };
  }
  return { ok: true, on, since: r.changed_at ?? r.created_at };
}

/** Subscriptions made at another address than this server's now: the Kit
 *  moved (building.sttark.com/kit to kit.sttark.com). Each belongs to the
 *  service worker of the address it was made at, which no page here can
 *  reach to turn it off, and that phone would get each notice twice once
 *  notices are on at this address too. So each ends, with a record, and its
 *  person's Macs hear the new count; the person turns notices on again here.
 *  A subscription with no address was made before the server kept one, at
 *  the Kit's first address. Runs at start; returns how many ended. */
export function endOtherAddresses(now = nowS()): number {
  const here = siteName();
  const d = db();
  const ended = d.transaction(() => {
    const rows = d.prepare('SELECT * FROM push_subs WHERE site IS NULL OR site != ?').all(here) as SubRow[];
    for (const s of rows) {
      d.prepare('DELETE FROM push_subs WHERE endpoint = ?').run(s.endpoint);
      const was = s.site ?? 'the Kit\'s first address';
      addRecord({
        at: now, who: 'server start', whoName: 'Server start', action: 'notices',
        before: { notices: s.notices === 1, device: s.device, site: s.site }, after: { notices: false, why: 'moved', site: here }, result: 'ok',
        words: `Stopped Needs you notices for ${s.device ?? 'a phone'}: they were turned on at ${was}, and the Kit is at ${here} now. Turn them on again there.`,
      });
    }
    return rows;
  })();
  for (const email of new Set(ended.map((s) => s.email))) {
    console.log(`[push] ${email}: notices made at another address than ${here} ended`);
    events.emit('push-subs-changed', { email });
  }
  return ended.length;
}

/** A subscription the push service says is gone: it can never get a push
 *  again, so it goes, with a record. */
function dropGone(s: SubRow, status: number): void {
  const d = db();
  const gone = d.transaction(() => {
    if (d.prepare('DELETE FROM push_subs WHERE endpoint = ?').run(s.endpoint).changes !== 1) return false;
    addRecord({
      who: 'push sender', whoName: 'Push sender', action: 'notices', before: { notices: s.notices === 1, device: s.device }, after: { notices: false, why: 'gone' }, result: 'ok',
      words: `Stopped Needs you notices for ${s.device ?? 'a phone'}: its push service says the subscription is gone (${status}).`,
    });
    return true;
  })();
  if (gone) {
    console.log(`[push] ${s.email}: ${s.device ?? 'a phone'} is gone (${status}): its subscription is dropped`);
    events.emit('push-subs-changed', { email: s.email });
  }
}

// ---------- sending ----------

export type Remind = { macId: string; email: string; cse: string; waitingSince: number; title: string; why: string | null; visible: boolean };
export type Skip = 'not_set_up' | 'no_phone' | 'sent' | 'visible';
export type RemindResult = { skipped: Skip | null; sent: number; gone: number; failed: number };

/** "A plan waits" as part of a sentence: "a plan waits". A name such as PR stays. */
const lowerFirst = (t: string) => (/^(?:[A-Z][a-z]|A\s)/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);

/** The Needs you count the app icon's badge shows: the needs-you rows of the
 *  person's live Macs, as the Sessions tab counts them. */
export function needsCount(email: string): number {
  let n = 0;
  for (const m of macsOf(email)) {
    if (m.state !== 'live') continue;
    n += ((lastSnapshot(m.id)?.rows ?? []) as { group?: string }[]).filter((r) => r.group === 'needs_you').length;
  }
  return Math.min(n, 99);
}

/** What one push says: a title and one line, its tag, the One session page
 *  a tap opens, and the badge. */
export function payloadOf(r: Remind, now = nowS()): { title: string; body: string; tag: string; url: string; badge: number } {
  const waited = span(Math.max(60, now - r.waitingSince));
  const why = (r.why ?? '').trim().replace(/[.\s]+$/, '');
  return {
    title: `Claude needs you: ${r.title}`,
    body: why ? `Waiting ${waited}: ${lowerFirst(why)}.` : `Waiting ${waited} for you.`,
    tag: `needs-${r.cse}`,
    url: appUrl(`/s/${encodeURIComponent(r.cse)}`),
    badge: needsCount(r.email),
  };
}

/** A push service keeps one waiting push per topic: an older one for the
 *  same session that the phone has not taken yet is replaced. */
const topicOf = (cse: string) => createHash('sha256').update(cse).digest('base64url').slice(0, 24);

async function deliver(s: SubRow, body: string, keys: Vapid, topic: string): Promise<'sent' | 'gone' | 'failed'> {
  let req: RequestDetails;
  try {
    req = generateRequestDetails({ endpoint: s.endpoint, keys: { p256dh: s.p256dh, auth: s.auth } }, body, {
      vapidDetails: keys, TTL: settings.ttlS, urgency: 'high', topic,
    });
  } catch (e) {
    console.error(`[push] ${s.email}: could not make the push for ${s.device ?? 'a phone'}: ${(e as Error).message}`);
    return 'failed';
  }
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(req.headers)) if (k.toLowerCase() !== 'content-length') headers[k] = String(v);
  try {
    const res = await fetch(req.endpoint, {
      method: 'POST', headers, body: req.body ? new Uint8Array(req.body) : undefined, redirect: 'error', signal: AbortSignal.timeout(settings.timeoutMs),
    });
    await res.arrayBuffer().catch(() => undefined);
    if (res.status === 404 || res.status === 410) {
      dropGone(s, res.status);
      return 'gone';
    }
    if (res.ok) return 'sent';
    console.warn(`[push] ${s.email}: the push service of ${s.device ?? 'a phone'} answered ${res.status}`);
    return 'failed';
  } catch (e) {
    console.warn(`[push] ${s.email}: the push service of ${s.device ?? 'a phone'} did not take the push: ${(e as Error).message}`);
    return 'failed';
  }
}

/** One reminder from a Mac: a push to each of the person's phones with
 *  notices on, unless a skip rule above says no. */
export async function remind(r: Remind, now = nowS()): Promise<RemindResult> {
  const out: RemindResult = { skipped: null, sent: 0, gone: 0, failed: 0 };
  const skip = (why: Skip) => {
    console.log(`[push] ${r.email}: no push for ${r.cse}: ${{ not_set_up: 'notices are not set up', no_phone: 'no phone has notices on', sent: 'it went already', visible: 'a page of theirs shows' }[why]}`);
    return { ...out, skipped: why };
  };
  const keys = vapid();
  if (!keys) return skip('not_set_up');
  const subs = db().prepare('SELECT * FROM push_subs WHERE email = ? AND notices = 1 ORDER BY created_at').all(r.email) as SubRow[];
  if (!subs.length) return skip('no_phone');
  // Claimed first, in one statement: two Macs that send the same reminder
  // at once make one push.
  const claimed = db().prepare('INSERT OR IGNORE INTO pushes_sent (email, cse, waiting_since, sent_at) VALUES (?, ?, ?, ?)').run(r.email, r.cse, Math.floor(r.waitingSince), now).changes === 1;
  if (!claimed) return skip('sent');
  // Claimed too: the page showed it, so this reply has had its reminder.
  if (r.visible) return skip('visible');
  const body = JSON.stringify(payloadOf(r, now));
  const topic = topicOf(r.cse);
  for (const result of await Promise.all(subs.map((s) => deliver(s, body, keys, topic)))) out[result] += 1;
  console.log(`[push] ${r.email}: Needs you for ${r.cse} to ${out.sent} of ${subs.length} phone${subs.length === 1 ? '' : 's'}${out.gone ? `, ${out.gone} gone` : ''}${out.failed ? `, ${out.failed} failed` : ''}`);
  return out;
}

/** With the server: each reminder a Mac sends goes out (once per process). */
export function startPush(): void {
  const g = globalThis as { __kitPushListening?: boolean };
  if (g.__kitPushListening) return;
  g.__kitPushListening = true;
  try {
    endOtherAddresses();
  } catch (e) {
    console.error(`[push] ALERT: could not end the notices made at another address: ${(e as Error).message}`);
  }
  events.on('remind', (r) => {
    remind(r).catch((e) => console.error(`[push] ALERT: a reminder failed: ${(e as Error).message}`));
  });
}
