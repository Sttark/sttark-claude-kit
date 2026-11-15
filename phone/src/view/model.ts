// What the phone pages draw from: the person's Macs, each Mac's last
// snapshot and archived list (schema/snapshot.v1.json, archived.v1.json),
// and the change records of the session that is open. The server fills it
// from the database (lib/state.ts) and draws the page; the browser keeps it
// up to date from /live (scripts/app.ts) and draws again with the same
// code. Pure: no database, no DOM.

export type Level = 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export type Group = 'needs_you' | 'working' | 'waiting' | 'held';
export type MacState = 'live' | 'updating' | 'asleep' | 'quit' | 'not_heard';

export type Wait = {
  id: string;
  kind: 'pr' | 'email-reply' | 'at' | 'check-script' | 'check-prompt';
  what: string;
  from: string | null;
  why: string | null;
  by: number | null;
  checks: string | null;
  failing: boolean;
  failing_since: number | null;
};

export type Row = {
  id: string;
  cse: string;
  sid: string | null;
  group: Group;
  title: string;
  sub: string;
  sub_strong: string | null;
  sub_warn: string | null;
  late: boolean;
  time_at: number | null;
  url: string;
  session: {
    level: Level | null;
    manual: boolean;
    reason: string | null;
    needs_you: boolean;
    why: string | null;
    waiting_since: number | null;
    turn_at: number | null;
  } | null;
  background: { agents: number; bash: number; what: string; since: number | null } | null;
  waits: Wait[];
  hold: { hold: boolean; at: number | null; percent: number | null; limit: string; since: number | null; until: number | null; agents: number } | null;
  limit_mode: { mode: 'follow' | 'credits' | 'hold'; at: number | null };
};

export type Bar = { kind: string; name: string; percent: number; resets: number | null };
export type Usage = { at: number | null; bars: Bar[]; reached: { name: string; until: number | null } | null };

export type Snapshot = {
  v: 1;
  at: number;
  mac: { name: string; kit: string; tz: string; account: string };
  flags: { paused: boolean; credits_all: boolean };
  reach: string[];
  usage: Usage;
  rows: Row[];
  archived_rev: string | null;
  archived_count: number;
};

export type MacInfo = { id: string; name: string; state: MacState; last_seen: number | null; kit: string };
export type ArchivedItem = { cse: string; title: string; folder: string; archived_at: number | null; url: string };
export type ChangeRecord = { at: number; mac: string; cse: string; act: string; reason: string; words: string };

/** Everything a page is drawn from. */
export type Kit = {
  /** "" or "/kit" (lib/paths.ts). */
  base: string;
  /** Unix seconds. */
  now: number;
  email: string;
  macs: MacInfo[];
  snaps: Record<string, Snapshot>;
  archived: Record<string, ArchivedItem[]>;
  /** The open session's changes from the phone, newest first. */
  records: ChangeRecord[];
};

/** What the person did on this page that the data does not hold. */
export type Ui = {
  /** The ⓘ notes that are open, by key. */
  notes: string[];
  /** The control that sent an action and waits for its answer. */
  sending: string | null;
  /** The answer to the last action, shown where it was asked. */
  result: Result | null;
  /** The Mac whose Remove asks to confirm. */
  confirm: string | null;
  /** Search words (Sessions, Archived). */
  q: string;
  /** Sessions: the search field shows. */
  find: boolean;
};

export type Reason = 'ok' | 'gone' | 'not_now' | 'not_here' | 'bad' | 'offline' | 'timeout' | 'denied';
export type Result = { scope: string; sec: 'top' | 'waits' | 'effort' | 'limit'; reason: Reason; words: string };

export const emptyUi = (): Ui => ({ notes: [], sending: null, result: null, confirm: null, q: '', find: false });

export const GROUPS: { key: Group; label: string; icon: 'bell' | 'activity' | 'hourglass' | 'circle-pause'; col: string }[] = [
  { key: 'needs_you', label: 'Needs you', icon: 'bell', col: 'Waiting for' },
  { key: 'working', label: 'Claude working', icon: 'activity', col: 'Working for' },
  { key: 'waiting', label: 'Waiting on someone else', icon: 'hourglass', col: 'Deadline' },
  { key: 'held', label: 'Held at usage limit', icon: 'circle-pause', col: 'Goes on' },
];

export const LEVELS: { key: Level; label: string }[] = [
  { key: 'low', label: 'Low' },
  { key: 'medium', label: 'Medium' },
  { key: 'high', label: 'High' },
  { key: 'xhigh', label: 'Extra' },
  { key: 'max', label: 'Max' },
];
export const levelLabel = (l: Level | null | undefined) => LEVELS.find((x) => x.key === l)?.label ?? '';

/** A row with the Mac it came from. */
export type Placed = { row: Row; mac: MacInfo; snap: Snapshot };

export const isLive = (m: MacInfo) => m.state === 'live';
export const multi = (k: Kit) => k.macs.length > 1;
export const macById = (k: Kit, id: string) => k.macs.find((m) => m.id === id);
export const liveMacs = (k: Kit) => k.macs.filter(isLive);
/** Macs that are not live: their sessions leave the four groups. */
export const awayMacs = (k: Kit) => k.macs.filter((m) => !isLive(m));

/** The rows of these Macs, each group in time order: the longest waiting
 *  or working first, the nearest deadline or end of hold first. */
export function rowsOf(k: Kit, macs: MacInfo[]): Placed[] {
  const out: Placed[] = [];
  for (const mac of macs) {
    const snap = k.snaps[mac.id];
    if (!snap) continue;
    for (const row of snap.rows) out.push({ row, mac, snap });
  }
  const order = (p: Placed) => p.row.time_at ?? Number.MAX_SAFE_INTEGER;
  return out.sort((a, b) => order(a) - order(b));
}
export const liveRows = (k: Kit) => rowsOf(k, liveMacs(k));
export const needsCount = (k: Kit) => liveRows(k).filter((p) => p.row.group === 'needs_you').length;

/** A session by its Remote Control id: a live Mac's first, then an away
 *  Mac's last list. */
export function findRow(k: Kit, cse: string): Placed | null {
  return rowsOf(k, liveMacs(k)).find((p) => p.row.cse === cse) ?? rowsOf(k, awayMacs(k)).find((p) => p.row.cse === cse) ?? null;
}

export type PlacedArchived = { item: ArchivedItem; mac: MacInfo; tz: string };
/** Every Mac's archived sessions, newest first. */
export function archivedOf(k: Kit): PlacedArchived[] {
  const out: PlacedArchived[] = [];
  for (const mac of k.macs) {
    const items = k.archived[mac.id];
    if (!items) continue;
    const tz = k.snaps[mac.id]?.mac.tz ?? 'America/New_York';
    for (const item of items) out.push({ item, mac, tz });
  }
  return out.sort((a, b) => (b.item.archived_at ?? 0) - (a.item.archived_at ?? 0));
}
export const findArchived = (k: Kit, cse: string) => archivedOf(k).find((a) => a.item.cse === cse) ?? null;

/** The time zone the page says times in: the first Mac's with a snapshot. */
export function tzOf(k: Kit, macId?: string): string {
  if (macId && k.snaps[macId]) return k.snaps[macId].mac.tz;
  const first = k.macs.find((m) => k.snaps[m.id]);
  return first ? k.snaps[first.id].mac.tz : 'America/New_York';
}

/** Usage, one block per Claude account (the account hash), from the newest
 *  read of the Macs on it. */
export type UsageBlock = { account: string; usage: Usage; snap: Snapshot; mac: MacInfo; macs: MacInfo[] };
export function usageBlocks(k: Kit): UsageBlock[] {
  const by = new Map<string, UsageBlock>();
  for (const mac of k.macs) {
    const snap = k.snaps[mac.id];
    if (!snap) continue;
    const acc = snap.mac.account;
    const have = by.get(acc);
    if (!have) by.set(acc, { account: acc, usage: snap.usage, snap, mac, macs: [mac] });
    else {
      have.macs.push(mac);
      if ((snap.usage.at ?? 0) > (have.usage.at ?? 0)) Object.assign(have, { usage: snap.usage, snap, mac });
    }
  }
  return [...by.values()];
}

/** The words for a Mac's state, as a chip and in a sentence. */
export const STATE_WORD: Record<MacState, string> = { live: 'Live', updating: 'Updating', asleep: 'Asleep', quit: 'Kit quit', not_heard: 'Not heard from' };

/** A wait's kind in words, one and many. */
export const KIND: Record<Wait['kind'], [string, string]> = {
  pr: ['pull request', 'pull requests'],
  'email-reply': ['email reply', 'email replies'],
  at: ['timed check', 'timed checks'],
  'check-script': ['check', 'checks'],
  'check-prompt': ['check', 'checks'],
};
/** "2 email replies", "1 pull request", "3 things". */
export function waitsInWords(waits: Wait[]): string {
  const n = waits.length;
  const kinds = [...new Set(waits.map((w) => KIND[w.kind][n === 1 ? 0 : 1]))];
  return `${n} ${kinds.length === 1 ? kinds[0] : 'things'}`;
}

/** At the usage limit choices. */
export const HOLD_AT = [50, 60, 70, 80, 90, 100];
export function limitChoices(row: Row, creditsAll: boolean): { value: string; label: string }[] {
  const ats = [...HOLD_AT];
  if (row.limit_mode.mode === 'hold' && row.limit_mode.at && !ats.includes(row.limit_mode.at)) ats.push(row.limit_mode.at), ats.sort((a, b) => a - b);
  return [
    { value: 'follow', label: `Same as Settings (${creditsAll ? 'use credits' : 'hold at the limit'})` },
    { value: 'credits', label: 'Always use credits' },
    ...ats.map((n) => ({ value: `hold:${n}`, label: `Never use credits; hold at ${n}%` })),
  ];
}
export const limitValue = (row: Row) => (row.limit_mode.mode === 'hold' ? `hold:${row.limit_mode.at ?? 100}` : row.limit_mode.mode);

/** The words of an action's answer when the server sent none. */
export const FALLBACK_WORDS: Record<Reason, string> = {
  ok: 'Done.',
  gone: 'This session is no longer on your Mac. Nothing was changed.',
  not_now: 'Your Mac cannot do this now. Nothing was changed.',
  not_here: 'Its conversation is not on this Mac, so this Mac cannot bring it back.',
  bad: 'Your Mac did not take that action. Nothing was changed.',
  offline: 'Your Mac is not connected, so nothing was sent. Try again when it is back.',
  timeout: 'Your Mac did not answer in time. Check the session before you try again.',
  denied: 'That Mac is not linked to your account. Nothing was sent.',
};
/** The phone itself has no connection to the server. */
export const NO_SERVER_WORDS = 'Your phone is not connected to the server, so nothing was sent. Try again when it is back.';
