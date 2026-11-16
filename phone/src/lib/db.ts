// The one module that opens the database. SQLite in WAL mode, as Building:
// readers never block the writer. Holds the sign-ins, the roster, the Macs
// and what each last sent, push subscriptions and the change records.
//
// Schema changes are a new statement here that is safe to run on every
// start: CREATE ... IF NOT EXISTS, or a column in ADDED_COLUMNS (an ALTER
// guarded by PRAGMA table_info). Times are Unix seconds.
import Database from 'better-sqlite3';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const SCHEMA = `
-- Sign-ins on phones and browsers (lib/session.ts): a random id, the only
-- thing in the cookie. 30 days, rolled forward at most once a day while used.
CREATE TABLE IF NOT EXISTS web_sessions (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_web_sessions_email ON web_sessions (email);
-- A Google sign-in under way: its PKCE verifier, nonce and where to go
-- after. 10 minutes.
CREATE TABLE IF NOT EXISTS oauth_states (state TEXT PRIMARY KEY, data TEXT NOT NULL, expires_at INTEGER NOT NULL);
-- Everyone who has signed in, with the name Google gave.
CREATE TABLE IF NOT EXISTS people (email TEXT PRIMARY KEY, name TEXT NOT NULL, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL);
-- The last good roster from Workrouter (lib/roster.ts): everyone on the
-- active roster, replaced whole by each good sync.
CREATE TABLE IF NOT EXISTS roster (email TEXT PRIMARY KEY, name TEXT NOT NULL, synced_at INTEGER NOT NULL);
-- The roster sync's state: the feed's ETag, the last good read, the last
-- error.
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Linked Macs: each Mac's own public key, saved when its person links it.
-- Never deleted; a removed Mac keeps its row, with when, why and by whom.
CREATE TABLE IF NOT EXISTS macs (
  id TEXT PRIMARY KEY,         -- the random id the Kit made for this Mac
  email TEXT NOT NULL,         -- its person
  name TEXT NOT NULL,          -- the Mac's name, as the Kit last sent it
  public_key TEXT NOT NULL,    -- P-256, base64 SPKI
  key_kind TEXT NOT NULL,      -- secure-enclave or keychain
  kit_version TEXT,
  linked_at INTEGER NOT NULL,
  last_seen INTEGER,
  bye TEXT,                    -- the last bye: sleep, quit or update
  bye_at INTEGER,
  removed_at INTEGER,
  removed_why TEXT,            -- phone, mac, roster or quiet
  removed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_macs_email ON macs (email);
-- Link pages waiting for a sign-in: one per link request from a Kit. A
-- page works once, for 10 minutes; rows go after a day. Only hashes of the
-- page's and the poll's tokens are kept.
CREATE TABLE IF NOT EXISTS links (
  token_hash TEXT PRIMARY KEY,
  poll_hash TEXT NOT NULL UNIQUE,
  code TEXT NOT NULL,          -- the 4 letters the page and the Kit both show
  mac_id TEXT NOT NULL,
  mac_name TEXT NOT NULL,
  public_key TEXT NOT NULL,
  key_kind TEXT NOT NULL,
  kit_version TEXT,
  address TEXT,                -- the public address the Kit asked from
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  linked_at INTEGER,
  linked_by TEXT
);
-- The last snapshot each Mac sent: replaced each time, deleted when the
-- Mac is removed.
CREATE TABLE IF NOT EXISTS snapshots (mac_id TEXT PRIMARY KEY, at INTEGER NOT NULL, received_at INTEGER NOT NULL, data TEXT NOT NULL);
-- The last archived list each Mac sent: the same.
CREATE TABLE IF NOT EXISTS archived (mac_id TEXT PRIMARY KEY, hash TEXT NOT NULL, received_at INTEGER NOT NULL, data TEXT NOT NULL);
-- Web Push subscriptions, one per phone, with the sign-in it was made
-- under (Sign out on that phone ends it). Until sign-out, or until the push
-- service says it is gone.
CREATE TABLE IF NOT EXISTS push_subs (
  endpoint TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  web_session TEXT,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  notices INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_push_subs_email ON push_subs (email);
-- Needs you pushes sent, so a reconnect or a second Mac never sends one
-- twice. 2 days.
CREATE TABLE IF NOT EXISTS pushes_sent (
  email TEXT NOT NULL,
  cse TEXT NOT NULL,
  waiting_since INTEGER NOT NULL,
  sent_at INTEGER NOT NULL,
  PRIMARY KEY (email, cse, waiting_since)
);

-- Every change, with who made it (Sign-in and Access, Every change has a
-- name on it): when, who (a person's address, or the job that made it),
-- the Mac and session as they were named then, what was done, before and
-- after, how it ended and the words shown. Append only: the triggers below
-- refuse to change, replace or delete a row, except a delete of a row over
-- a year old, which the daily job makes (lib/expiry.ts).
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at INTEGER NOT NULL CHECK (at > 1000000000 AND at < 10000000000),
  who TEXT NOT NULL,
  who_name TEXT NOT NULL,
  mac_id TEXT,
  mac_name TEXT,
  session TEXT,
  session_name TEXT,
  action TEXT NOT NULL,
  before TEXT,
  after TEXT,
  result TEXT,
  words TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_at ON records (at);
CREATE INDEX IF NOT EXISTS idx_records_mac ON records (mac_id, at);
CREATE INDEX IF NOT EXISTS idx_records_session ON records (session, at);
CREATE TRIGGER IF NOT EXISTS records_no_update BEFORE UPDATE ON records
BEGIN
  SELECT RAISE(ABORT, 'records are append only: a record is never changed');
END;
CREATE TRIGGER IF NOT EXISTS records_no_delete BEFORE DELETE ON records
WHEN OLD.at > CAST(strftime('%s', 'now', '-1 year') AS INTEGER)
BEGIN
  SELECT RAISE(ABORT, 'records are append only: a record goes only when it is over a year old');
END;
-- INSERT OR REPLACE deletes the old row without the delete trigger (unless
-- recursive triggers are on), so an insert over an existing id is refused.
CREATE TRIGGER IF NOT EXISTS records_no_replace BEFORE INSERT ON records
WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM records WHERE id = NEW.id)
BEGIN
  SELECT RAISE(ABORT, 'records are append only: a record is never replaced');
END;
`;

/** Columns added after a table first shipped: guarded, safe on every start. */
const ADDED_COLUMNS: [table: string, column: string, decl: string][] = [
  // The Claude Code login the Kit sent as Google's account hint, if it is a
  // @sttark.com address (lib/link.ts).
  ['links', 'hint', 'TEXT'],
  // When this phone's notices were last turned on or off, and the kind of
  // device it is ("iPhone"), for Menu and the records (lib/push.ts).
  ['push_subs', 'changed_at', 'INTEGER'],
  ['push_subs', 'device', 'TEXT'],
  // The address the phone turned notices on at (siteName(): kit.sttark.com),
  // whose service worker gets them. None: before the server kept it, at the
  // Kit's first address (lib/push.ts, endOtherAddresses).
  ['push_subs', 'site', 'TEXT'],
];

let handle: Database.Database | undefined;

export function dbPath(): string {
  return process.env.KIT_DB || 'data/kit.db';
}

export function db(): Database.Database {
  if (handle) return handle;
  const path = dbPath();
  if (path !== ':memory:') mkdirSync(dirname(path), { recursive: true });
  const d = new Database(path);
  d.pragma('journal_mode = WAL');
  d.pragma('busy_timeout = 5000');
  d.exec(SCHEMA);
  for (const [t, c, decl] of ADDED_COLUMNS) {
    const cols = (d.prepare(`PRAGMA table_info(${t})`).all() as { name: string }[]).map((r) => r.name);
    if (!cols.includes(c)) d.exec(`ALTER TABLE ${t} ADD COLUMN ${c} ${decl}`);
  }
  handle = d;
  return d;
}

/** Tests only: drop the handle so the next db() opens KIT_DB afresh. */
export function resetDbForTests(): void {
  handle?.close();
  handle = undefined;
}
