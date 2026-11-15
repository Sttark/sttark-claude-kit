// Linking a Mac, once (phone/DESIGN.md section 2, schema/link.v1.json).
//
//  1. The Kit sends POST /api/mac/link: its public key, its name, the Kit
//     version and a random Mac id. The server keeps a link row (links) and
//     answers with the link page's address, a poll token and a 4-letter
//     code. Only hashes of the two tokens are kept. The page works once,
//     for 10 minutes; rows go after a day (lib/expiry.ts).
//  2. A person opens the page, signs in, and clicks Link. That saves the
//     Mac's key to them (macs), with a record.
//  3. The Kit, polling every 2 seconds, sees linked and opens /mac.
//
// A Mac id is linked at most once: an id the server knows (linked or
// removed) is refused, so linking can never put a new key on a Mac
// someone already has.
import { db } from './db.ts';
import { addRecord } from './records.ts';
import { events } from './events.ts';
import { checkLink } from './contract.ts';
import { newCode, newToken, parseMacKey, tokenHash } from './keys.ts';
import { appUrl } from './paths.ts';
import { sameNetwork } from './net.ts';
import { MAX_MACS, personName } from './macs.ts';

export const LINK_TTL_S = 10 * 60;
const nowS = () => Math.floor(Date.now() / 1000);

export type LinkRequest = { v: 1; mac: string; name: string; kit: string; key: string; kind: 'secure-enclave' | 'keychain'; hint: string | null };
export type LinkAnswer = { link: string; poll: string; code: string; expires_at: number };
export type Refusal = { error: 'bad_request' | 'mac_taken' | 'too_many' | 'too_large'; words: string };

type LinkRow = {
  token_hash: string; code: string; mac_id: string; mac_name: string; public_key: string; key_kind: string;
  kit_version: string | null; address: string | null; created_at: number; expires_at: number;
  linked_at: number | null; linked_by: string | null; hint: string | null;
};

// Link requests per address, in memory: at most 20 in 10 minutes.
const RATE = { max: 20, windowS: 600 };
const asked = new Map<string, number[]>();
function tooMany(address: string | null, now: number): boolean {
  const key = address ?? 'unknown';
  const recent = (asked.get(key) ?? []).filter((t) => t > now - RATE.windowS);
  recent.push(now);
  asked.set(key, recent);
  if (asked.size > 5000) for (const [k, v] of asked) if (!v.some((t) => t > now - RATE.windowS)) asked.delete(k);
  return recent.length > RATE.max;
}

/** Tests only. */
export function resetLinkRateForTests(): void {
  asked.clear();
}

/** Step 1. `body` is the parsed JSON; `address` is where it came from. */
export function createLink(body: unknown, address: string | null, now = nowS()): { status: 201; answer: LinkAnswer } | { status: 400 | 409 | 429; refusal: Refusal } {
  const checked = checkLink('request', body);
  if (!checked.ok) return { status: 400, refusal: { error: 'bad_request', words: `The link request does not match the contract: ${checked.why}`.slice(0, 160) } };
  const r = body as LinkRequest;
  const key = parseMacKey(r.key);
  if (!key) return { status: 400, refusal: { error: 'bad_request', words: 'The key is not a P-256 public key (SPKI, DER, base64).' } };
  if (tooMany(address, now)) return { status: 429, refusal: { error: 'too_many', words: 'Too many link requests from this address. Try again in 10 minutes.' } };
  const d = db();
  if (d.prepare('SELECT 1 FROM macs WHERE id = ?').get(r.mac)) {
    return { status: 409, refusal: { error: 'mac_taken', words: 'This Mac id is known already. Make a new Mac id and ask again.' } };
  }
  const token = newToken();
  const poll = newToken();
  const code = newCode();
  const expiresAt = now + LINK_TTL_S;
  d.prepare(
    `INSERT INTO links (token_hash, poll_hash, code, mac_id, mac_name, public_key, key_kind, kit_version, address, created_at, expires_at, hint)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(tokenHash(token), tokenHash(poll), code, r.mac, r.name, key, r.kind, r.kit, address, now, expiresAt, r.hint);
  return { status: 201, answer: { link: appUrl(`/link/${token}`), poll, code, expires_at: expiresAt } };
}

export type PollAnswer = { status: 'waiting' | 'linked' | 'expired'; email: string | null; name: string | null };

/** Step 3: what the Kit's poll gets. Null for a poll the server does not
 *  know (answered 404, status expired). */
export function pollLink(poll: string, now = nowS()): PollAnswer | null {
  if (!/^[A-Za-z0-9_-]{43}$/.test(poll)) return null;
  const row = db().prepare('SELECT linked_at, linked_by, expires_at FROM links WHERE poll_hash = ?').get(tokenHash(poll)) as Pick<LinkRow, 'linked_at' | 'linked_by' | 'expires_at'> | undefined;
  if (!row) return null;
  if (row.linked_at !== null && row.linked_by) return { status: 'linked', email: row.linked_by, name: personName(row.linked_by) };
  return { status: row.expires_at <= now ? 'expired' : 'waiting', email: null, name: null };
}

export type LinkPage =
  | { kind: 'unknown' }
  | { kind: 'expired'; macName: string }
  | { kind: 'linked'; macName: string; mine: boolean }
  | { kind: 'taken'; macName: string }
  | { kind: 'full'; macName: string }
  | { kind: 'ask'; macName: string; kit: string | null; code: string; showCode: boolean; expiresAt: number; askedAt: number; keyKind: string };

function rowOf(token: string): LinkRow | undefined {
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) return undefined;
  return db().prepare('SELECT * FROM links WHERE token_hash = ?').get(tokenHash(token)) as LinkRow | undefined;
}

/** The Google account hint the Kit sent with this link, if any. */
export function linkHint(token: string): string | null {
  return rowOf(token)?.hint ?? null;
}

/** What the link page shows this person. `address` is the browser's. */
export function linkPage(token: string, email: string, address: string | null, now = nowS()): LinkPage {
  const row = rowOf(token);
  if (!row) return { kind: 'unknown' };
  const macName = row.mac_name;
  if (row.linked_at !== null) return { kind: 'linked', macName, mine: row.linked_by === email };
  if (row.expires_at <= now) return { kind: 'expired', macName };
  if (db().prepare('SELECT 1 FROM macs WHERE id = ?').get(row.mac_id)) return { kind: 'taken', macName };
  const count = (db().prepare('SELECT count(*) AS n FROM macs WHERE email = ? AND removed_at IS NULL').get(email) as { n: number }).n;
  if (count >= MAX_MACS) return { kind: 'full', macName };
  return {
    kind: 'ask', macName, kit: row.kit_version, code: row.code, keyKind: row.key_kind,
    showCode: !sameNetwork(row.address, address), expiresAt: row.expires_at, askedAt: row.created_at,
  };
}

/** Step 2: the person clicked Link. Saves the Mac's key to them, once, with
 *  a record. Answers what the page shows next. */
export function approveLink(token: string, person: { email: string; name: string }, now = nowS()): LinkPage {
  const d = db();
  let linked: string | null = null;
  const result = d.transaction((): LinkPage => {
    const page = linkPage(token, person.email, null, now);
    if (page.kind !== 'ask') return page;
    const row = rowOf(token)!;
    linked = row.mac_id;
    d.prepare(
      `INSERT INTO macs (id, email, name, public_key, key_kind, kit_version, linked_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    ).run(row.mac_id, person.email, row.mac_name, row.public_key, row.key_kind, row.kit_version, now);
    d.prepare('UPDATE links SET linked_at = ?, linked_by = ? WHERE token_hash = ?').run(now, person.email, row.token_hash);
    addRecord({
      at: now, who: person.email, whoName: person.name, macId: row.mac_id, macName: row.mac_name, action: 'link_mac',
      before: { linked: false }, after: { linked: true, key: row.key_kind }, result: 'ok', words: `Linked ${row.mac_name}.`,
    });
    return { kind: 'linked', macName: row.mac_name, mine: true };
  })();
  if (linked) events.emit('mac-linked', { macId: linked, email: person.email });
  return result;
}
