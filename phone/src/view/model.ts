// What the phone pages draw from: the person's Macs, each Mac's last
// snapshot and archived list (schema/snapshot.v1.json, archived.v1.json),
// its Usage by session list for the period the Usage tab shows
// (usage.v1.json), and the change records of the session that is open. The server fills it
// from the database (lib/state.ts) and draws the page; the browser keeps it
// up to date from /live (scripts/app.ts) and draws again with the same
// code. Pure: no database, no DOM.

export type Level = 'low' | 'medium' | 'high' | 'xhigh' | 'max';
/** The four groups, and idle: a session that needs nothing now but has a
 *  message kept in the Kit in the last 24 hours (only those go up). */
export type Group = 'needs_you' | 'working' | 'waiting' | 'held' | 'idle';
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
  /** On an email reply: when the person replied in its thread themselves.
   *  The wait goes on: it still waits for the other person. A Kit from
   *  before it sends none. */
  replied?: number;
};

/** A message the session or the Kit would have sent to the person (email,
 *  Chat, a text, a notice), kept in the Kit instead: Alerts are off in Reach
 *  me by on the Mac, or for this session. why is the Mac's words for that.
 *  replied: when the person answered it themselves, where it is about (the
 *  same email thread, Chat space or Asana task); it is handled then. No link
 *  and no address ever comes up. */
export type KeptMessage = { at: number; subject: string; text: string; why: string; replied?: number };

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
  /** The latest progress check-in of the work that runs now (Claude working
   *  only): the Kit's short note and when it wrote it. A Kit from before it
   *  sends none. */
  checkin?: { note: string; at: number } | null;
  waits: Wait[];
  hold: { hold: boolean; at: number | null; percent: number | null; limit: string; since: number | null; until: number | null; agents: number } | null;
  limit_mode: { mode: 'follow' | 'credits' | 'hold'; at: number | null };
  /** At most 3, newest first; only when there is one. */
  messages?: KeptMessage[];
  /** The session's alerts: true only when the person turned them on for it;
   *  every session starts off. A Kit from before the switch sends none: on,
   *  since it had no switch. */
  alerts?: boolean;
  /** The folder it works in, its own name only (src), when the Mac knows
   *  it. A Kit from before it sends none. */
  folder?: string;
};

/** A session's alerts, as its Mac says them (on for a Kit that sends none). */
export const alertsOn = (row: Row) => row.alerts !== false;

/** The Reach me by ways, as the Kit's Settings name them. */
export const REACH_WAYS = { email: 'Email', push: 'Claude app', chat: 'Google Chat', text: 'Text message', mac: 'Mac notice' } as const;

export type Bar = { kind: string; name: string; percent: number; resets: number | null };
export type Usage = { at: number | null; bars: Bar[]; reached: { name: string; until: number | null } | null };

export type Snapshot = {
  v: 1;
  at: number;
  mac: { name: string; kit: string; tz: string; account: string };
  /** alerts_off: true only while Alerts are off in Reach me by on that Mac
   *  (absent from a Kit before it, and while they are on). */
  flags: { paused: boolean; credits_all: boolean; alerts_off?: boolean };
  reach: string[];
  usage: Usage;
  rows: Row[];
  archived_rev: string | null;
  archived_count: number;
};

export type MacInfo = { id: string; name: string; state: MacState; last_seen: number | null; kit: string };
export type ArchivedItem = { cse: string; title: string; folder: string; archived_at: number | null; url: string };
export type ChangeRecord = { at: number; mac: string; cse: string; act: string; reason: string; words: string };

/** Usage by session (schema/usage.v1.json): each session's share of the
 *  person's use on one Mac in one period, in percent, and the part its
 *  agents did. A share is never a percent of the usage limit. human_hours,
 *  the human work estimate, comes only from a Kit that knows it. */
export type UsageRow = { title: string; cse: string | null; share: number; agent_share: number; last_active: number | null; agents: number; human_hours?: number };
/** A kind of work and its factor: the hours a person needs for each hour
 *  Claude was at work on it. */
export type WorkFactor = { name: string; x: number };
export type UsageList = {
  v: 1;
  /** today, 7d, 30d, or a range of days: 2026-11-01..2026-11-10. */
  period: string;
  from: string;
  to: string;
  /** When the Mac made it. */
  at: number;
  total: { sessions: number; tokens: number; agent_share: number; usd: number; human_hours?: number };
  /** The biggest share first; at most 100. */
  rows: UsageRow[];
  /** The sessions after the first 100, together. */
  more: { sessions: number; share: number; human_hours?: number };
  /** The factors human_hours uses, for the note. */
  factors?: WorkFactor[];
};

/** What the Usage tab's By session list shows: the period picked (Custom
 *  with its first and last day), and whether every row shows. It lives in
 *  the address: ?p=today|7d|30d|custom&from=&to=&all=1. */
export type UsagePick = 'today' | '7d' | '30d' | 'custom';
export type UsageView = { pick: UsagePick; from: string | null; to: string | null; all: boolean };

const DAY = /^\d{4}-\d{2}-\d{2}$/;
/** The Usage tab's choice from its address; 7 days when there is none. */
export function usageView(q: URLSearchParams): UsageView {
  const p = q.get('p');
  const pick: UsagePick = p === 'today' || p === '30d' || p === 'custom' ? p : '7d';
  let from = DAY.test(q.get('from') ?? '') ? q.get('from') : null;
  let to = DAY.test(q.get('to') ?? '') ? q.get('to') : null;
  if (from && to && from > to) [from, to] = [to, from];
  return { pick, from, to, all: q.get('all') === '1' };
}
/** The contract's period for a choice; null for Custom without both days. */
export function periodOf(u: UsageView | undefined): string | null {
  const v = u ?? { pick: '7d', from: null, to: null, all: false };
  if (v.pick !== 'custom') return v.pick;
  return v.from && v.to ? `${v.from}..${v.to}` : null;
}
/** The address of a choice. */
export function usageQuery(u: UsageView): string {
  const q = new URLSearchParams();
  if (u.pick !== '7d') q.set('p', u.pick);
  if (u.pick === 'custom') {
    if (u.from) q.set('from', u.from);
    if (u.to) q.set('to', u.to);
  }
  if (u.all) q.set('all', '1');
  const s = q.toString();
  return s ? `?${s}` : '';
}
/** The claude.ai link that Open in Claude uses, from a Remote Control id, as
 *  the Mac makes it (Phone.link in the Kit). */
export function sessionLink(cse: string): string {
  if (cse.startsWith('cse_')) return `https://claude.ai/code/session_${cse.slice(4)}`;
  if (cse.startsWith('session_')) return `https://claude.ai/code/${cse}`;
  return 'https://claude.ai/code';
}

/** Needs you notices on this phone, as Menu draws them (lib/push.ts, and the
 *  page's own check of its browser in scripts/app.ts):
 *    off, on            this phone gets no notices, or gets them;
 *    turning_on, turning_off   a tap's change is under way;
 *    install            an iPhone or iPad in the browser: notices need Claude
 *                       Kit on the Home Screen;
 *    unsupported        this browser has no Web Push;
 *    blocked            the phone's settings block Claude Kit's notices;
 *    not_set_up         the server has no Web Push keys. */
export type NoticeState = 'off' | 'on' | 'turning_on' | 'turning_off' | 'install' | 'unsupported' | 'blocked' | 'not_set_up';
export type Notices = {
  state: NoticeState;
  /** When they were last turned on or off on this phone. */
  since: number | null;
  /** Why the last tap did not work, in words. */
  problem: string | null;
  /** iPhone, iPad, or any other phone. */
  device: 'iPhone' | 'iPad' | 'phone';
};

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
  /** Usage: each Mac's Usage by session list, for the period the tab shows
   *  (a list for another period is not drawn). */
  usage?: Record<string, UsageList>;
  /** The open session's changes from the phone, newest first. */
  records: ChangeRecord[];
  /** Menu only: the key a phone subscribes to notices with (null: notices
   *  are not set up on this server), and this sign-in's notices. */
  notices?: { key: string | null; mine: { on: boolean; since: number } | null };
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
  /** The search's words, on Sessions: every session, archived ones too. */
  q: string;
  /** Sessions: the search field shows (the top bar's Search). */
  find: boolean;
  /** Menu: Needs you notices on this phone, once the page checked its
   *  browser; until then Menu draws what the server knows (Kit.notices). */
  notices: Notices | null;
  /** Usage: when the page asked the Macs for their list (Unix seconds); a
   *  live Mac that has not answered in 15 seconds is said so. */
  usageAsked?: number | null;
};

export type Reason = 'ok' | 'gone' | 'not_now' | 'not_here' | 'bad' | 'offline' | 'timeout' | 'denied';
export type Result = { scope: string; sec: 'top' | 'waits' | 'effort' | 'limit' | 'alerts'; reason: Reason; words: string };

export const emptyUi = (): Ui => ({ notes: [], sending: null, result: null, confirm: null, q: '', find: false, notices: null });

/** Menu's notices before the page checked its browser: what the server knows
 *  of this sign-in. */
export function noticesOf(k: Kit, ui: Ui): Notices {
  if (ui.notices) return ui.notices;
  const n = k.notices;
  if (n && !n.key) return { state: 'not_set_up', since: null, problem: null, device: 'phone' };
  return { state: n?.mine?.on ? 'on' : 'off', since: n?.mine?.since ?? null, problem: null, device: 'phone' };
}

export const GROUPS: { key: Group; label: string; icon: 'bell' | 'activity' | 'hourglass' | 'circle-pause' | 'mail'; col: string }[] = [
  { key: 'needs_you', label: 'Needs you', icon: 'bell', col: 'Waiting for' },
  { key: 'working', label: 'Claude working', icon: 'activity', col: 'Working for' },
  { key: 'waiting', label: 'Waiting on someone else', icon: 'hourglass', col: 'Deadline' },
  { key: 'held', label: 'Held at usage limit', icon: 'circle-pause', col: 'Goes on' },
  { key: 'idle', label: 'Idle with a message', icon: 'mail', col: 'Message' },
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
/** Macs that are not live: their sessions leave the groups. */
export const awayMacs = (k: Kit) => k.macs.filter((m) => !isLive(m));

/** The rows of these Macs, each group in time order: the longest waiting
 *  or working first, the nearest deadline or end of hold first, the newest
 *  kept message first. */
export function rowsOf(k: Kit, macs: MacInfo[]): Placed[] {
  const out: Placed[] = [];
  for (const mac of macs) {
    const snap = k.snaps[mac.id];
    if (!snap) continue;
    for (const row of snap.rows) out.push({ row, mac, snap });
  }
  const order = (p: Placed) => (p.row.group === 'idle' ? -(p.row.time_at ?? 0) : (p.row.time_at ?? Number.MAX_SAFE_INTEGER));
  return out.sort((a, b) => order(a) - order(b));
}
export const liveRows = (k: Kit) => rowsOf(k, liveMacs(k));
export const needsCount = (k: Kit) => liveRows(k).filter((p) => p.row.group === 'needs_you').length;

/** A session by its Remote Control id: a live Mac's first, then an away
 *  Mac's last list. */
export function findRow(k: Kit, cse: string): Placed | null {
  return rowsOf(k, liveMacs(k)).find((p) => p.row.cse === cse) ?? rowsOf(k, awayMacs(k)).find((p) => p.row.cse === cse) ?? null;
}

// ---------- the search ----------
// One search, from the top bar on every page, over every session the phone
// has: the rows of the live Macs and every Mac's archived sessions. Each word
// must be in what the phone knows of a session, with case and accents
// ignored: its name, the words on its row, its folder, its Mac's name, what
// each wait is for, why then and from whom, its last check-in and its kept
// messages; for an archived session, its name, its folder and its Mac's name.
// The window's search does the same over what the Mac has (Sources/Search.swift).

/** Case and accents ignored: "Café" and "cafe" are the same word. */
export const fold = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();
/** The words typed, folded; none for spaces only. */
export const searchWords = (q: string) => fold(q).split(/\s+/).filter(Boolean);
/** What a session row is found by, folded. */
export function searchText(p: Placed): string {
  const { row, mac } = p;
  const parts = [row.title, row.sub, row.sub_strong, row.sub_warn, row.folder, mac.name, row.session?.reason, row.session?.why, row.background?.what, row.checkin?.note];
  for (const w of row.waits) parts.push(w.what, w.why, w.from);
  for (const m of row.messages ?? []) parts.push(m.subject, m.text);
  return fold(parts.filter(Boolean).join('\n'));
}
/** What an archived session is found by, folded. */
export const archivedText = (a: PlacedArchived) => fold([a.item.title, a.item.folder, a.mac.name].filter(Boolean).join('\n'));
const matches = (text: string, words: string[]) => words.every((w) => text.includes(w));

/** What a search found: the rows that match, the live Macs' first, then
 *  those of the Macs that are away (their last list), and the archived
 *  sessions that match, newest first. */
export function searchAll(k: Kit, q: string): { rows: Placed[]; archived: PlacedArchived[] } {
  const words = searchWords(q);
  if (!words.length) return { rows: [], archived: [] };
  const rows = [...liveRows(k), ...rowsOf(k, awayMacs(k))].filter((p) => matches(searchText(p), words));
  return { rows, archived: archivedOf(k).filter((a) => matches(archivedText(a), words)) };
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
