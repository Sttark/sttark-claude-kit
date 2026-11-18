// The phone pages as HTML: Sessions, One session, Archived and an archived
// session, Usage, a Mac's page and Menu. The server draws a page with
// these from the last snapshots, and the browser draws it again with the
// same functions when /live sends something new, so the two never differ.
// Every word from a Mac goes through esc(). Layout, words and behavior
// follow the clickable prototype the owner approved (see phone/README.md).
import { ic, type IconName } from '../lib/icons.ts';
import {
  FALLBACK_WORDS,
  GROUPS,
  LEVELS,
  REACH_WAYS,
  STATE_WORD,
  alertsOn,
  archivedOf,
  awayMacs,
  findArchived,
  findRow,
  isLive,
  levelLabel,
  limitChoices,
  limitValue,
  liveMacs,
  liveRows,
  macById,
  multi,
  noticesOf,
  periodOf,
  rowsOf,
  searchAll,
  sessionLink,
  tzOf,
  usageBlocks,
  waitsInWords,
  type Kit,
  type MacInfo,
  type Notices,
  type Placed,
  type PlacedArchived,
  type Result,
  type Row,
  type Ui,
  type UsageList,
  type UsagePick,
  type UsageRow,
  type UsageView,
  type Wait,
} from './model.ts';
import { clock, dayKey, dayLabel, dayWords, span, until, when, whenFull } from './time.ts';
import { humanNote, peopleWords, personWords } from './human.ts';

export type View =
  | { page: 'sessions' }
  | { page: 'session'; cse: string; from: string }
  | { page: 'archived' }
  | { page: 'archived-item'; cse: string; from?: string }
  | { page: 'usage'; usage?: UsageView }
  | { page: 'mac'; id: string }
  | { page: 'menu' };

export type Drawn = {
  /** The page's name in the tab title ("Page · Claude Kit · Sttark"). */
  title: string;
  html: string;
  /** Which of the three tabs is current. */
  tab: 'sessions' | 'archived' | 'usage' | null;
  /** 404 when the thing the address names is not there. */
  status: number;
};

export const esc = (s: unknown) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const enc = encodeURIComponent;
const lowerFirst = (t: string) => (/^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);
const noStop = (t: string) => t.replace(/[.\s]+$/, '');
const L = (k: Kit, path: string) => k.base + path;
/** A limit's name in a sentence: "5-hour limit", "weekly limit". */
const limitName = (name: string) => {
  const n = lowerFirst(name.trim());
  return /limit$/i.test(n) ? n : `${n} limit`;
};

// ---------- links ----------

/** A session's own page; from says where its way back goes. */
export const sessionHref = (k: Kit, cse: string, from = 'sessions') => L(k, `/s/${enc(cse)}${from && from !== 'sessions' ? `?from=${enc(from)}` : ''}`);
const backOf = (k: Kit, from: string): { href: string; label: string; tab: Drawn['tab'] } => {
  if (from.startsWith('mac:')) {
    const id = from.slice(4);
    return { href: L(k, `/mac/${enc(id)}`), label: macById(k, id)?.name ?? 'Mac', tab: 'sessions' };
  }
  if (from === 'usage') return { href: L(k, '/usage'), label: 'Usage', tab: 'usage' };
  if (from === 'archived') return { href: L(k, '/archived'), label: 'Archived', tab: 'archived' };
  // what a search found, on Sessions: back goes to it (the page's script goes back in the history, to the words typed)
  if (from === 'search') return { href: L(k, '/?find=1'), label: 'Search', tab: 'sessions' };
  return { href: L(k, '/'), label: 'Sessions', tab: 'sessions' };
};
const crumbs = (href: string, label: string) => `<nav class="crumbs" aria-label="Back"><a href="${esc(href)}" data-act="back">${ic('chevron-left')}${esc(label)}</a></nav>`;
const openLink = (url: string, cls: string, words: boolean) =>
  words
    ? `<a class="${cls}" href="${esc(url)}" target="_blank" rel="noopener" data-k="open">${ic('arrow-up-right')}Open in Claude</a>`
    : `<a class="open-btn" href="${esc(url)}" target="_blank" rel="noopener" aria-label="Open in Claude">${ic('arrow-up-right')}</a>`;

// ---------- small parts ----------

/** An ⓘ and its note, which opens in place under what it explains. */
const infoBtn = (ui: Ui, key: string, label: string) =>
  `<button type="button" class="info-btn" data-act="info" data-key="${esc(key)}" data-k="info:${esc(key)}" aria-expanded="${ui.notes.includes(key)}" aria-controls="note-${esc(key)}" aria-label="${esc(label)}">${ic('info')}</button>`;
const noteHtml = (ui: Ui, key: string, text: string) =>
  `<div class="note" id="note-${esc(key)}"${ui.notes.includes(key) ? '' : ' hidden'}>${esc(text)}<button type="button" class="x" data-act="info" data-key="${esc(key)}" aria-label="Close">${ic('x')}</button></div>`;

/** The answer to an action: its first sentence bold, the rest after it.
 *  Only the words the server sent (the Mac's, or the server's for offline,
 *  timeout and denied), so the page never claims what the Mac did not. */
export function resultHtml(r: Result): string {
  const kind = r.reason === 'ok' ? 'ok' : r.reason === 'gone' || r.reason === 'not_now' || r.reason === 'not_here' ? 'nochange' : 'fail';
  const icon: IconName = kind === 'ok' ? 'check' : kind === 'nochange' ? 'info' : 'circle-alert';
  const words = (r.words || FALLBACK_WORDS[r.reason]).trim();
  const m = words.match(/^(.+?[.!?])(\s+[\s\S]*)?$/);
  const head = m ? m[1] : words;
  const rest = m?.[2] ?? '';
  return `<div class="note result ${kind}" role="status">${ic(icon)}<div><b>${esc(head)}</b>${esc(rest)}</div><button type="button" class="x" data-act="clear-result" aria-label="Close">${ic('x')}</button></div>`;
}
const resultAt = (ui: Ui, scope: string, sec: Result['sec']) => (ui.result && ui.result.scope === scope && ui.result.sec === sec ? resultHtml(ui.result) : '');

/** An action button: "Sending..." while its answer is out. */
function actBtn(ui: Ui, key: string, label: string, attrs: string, cls = 'btn ghost'): string {
  const sending = ui.sending === key;
  const busy = !!ui.sending;
  return `<button type="button" class="${cls}${sending ? ' sending' : ''}" data-k="${esc(key)}" ${attrs}${busy ? ' aria-disabled="true"' : ''}>${sending ? 'Sending...' : esc(label)}</button>`;
}

const chip = (cls: string, words: string) => `<span class="chip${cls ? ' ' + cls : ''}">${esc(words)}</span>`;

// ---------- rows and groups ----------

function rowTime(row: Row, now: number, tz: string): string {
  if (row.time_at == null) return '';
  if (row.group === 'needs_you' || row.group === 'working') return span(now - row.time_at);
  return when(row.time_at, now, tz);
}

/** When the person replied themselves where a row's item is about, or
 *  null: an idle row's newest kept message (it is handled), or the newest
 *  reply in a wait's thread (the wait still waits for the other person). */
export function repliedOf(row: Row): number | null {
  if (row.group === 'idle') return row.messages?.[0]?.replied ?? null;
  if (row.group === 'waiting') {
    const at = row.waits.reduce((a, w) => Math.max(a, w.replied ?? 0), 0);
    return at || null;
  }
  return null;
}

function rowSub(k: Kit, p: Placed, now: number): string {
  const { row, mac, snap } = p;
  let out = '';
  if (row.sub_warn) out += `<span class="warn">${esc(row.sub_warn)}</span> · `;
  if (multi(k)) out += `<span class="mac">${esc(mac.name)}</span> · `;
  // first, so the line's end never cuts it: the person answered it, so it no longer reads as open
  const rep = repliedOf(row);
  if (rep) out += `<span class="rep">You replied ${esc(whenFull(rep, now, snap.mac.tz))}</span> · `;
  return out + esc(row.sub);
}

/** The latest progress check-in of a working row, or null: the Kit writes
 *  one every 15 minutes while the work runs, and drops it when the work ends. */
const checkinOf = (row: Row) => (row.group === 'working' && row.checkin?.note ? row.checkin : null);
/** "Check-in 12 min ago", "Check-in just now". */
const checkinAge = (at: number, now: number) => (now - at < 60 ? 'Check-in just now' : `Check-in ${span(now - at)} ago`);
/** After the name of a session whose alerts are off: a bell with a line
 *  through it, with its words for screen readers. */
const ALERTS_OFF = `<span class="alerts-off">${ic('bell-off')}<span class="vh">Alerts off</span></span>`;

function sessionRow(k: Kit, p: Placed, from: string, stale: boolean): string {
  const { row, snap } = p;
  const now = stale ? snap.at : k.now;
  const lvl = row.group === 'working' && row.session?.level ? `<span class="lvl${row.session.manual ? ' manual' : ''}">${esc(levelLabel(row.session.level))}</span>` : '';
  const off = alertsOn(row) ? '' : ALERTS_OFF;
  const ck = checkinOf(row);
  return (
    // a Mac's last list, in gray (among what a search found, the row alone)
    `<li${stale ? ' class="stale"' : ''}><a class="row" href="${esc(sessionHref(k, row.cse, from))}"><div class="row-main"><div class="name-line"><span class="name">${esc(row.title)}</span>${lvl}${off}</div>` +
    `<div class="sub">${rowSub(k, p, now)}</div>` +
    `</div><span class="time${row.late && !stale ? ' late' : ''}">${esc(rowTime(row, now, snap.mac.tz))}</span>` +
    // under the name and the time, the row's whole width, so more of the note shows
    (ck ? `<div class="ck">${ic('message-square-text')}<span class="ck-text"><span class="ck-age">${esc(checkinAge(ck.at, now))}:</span> ${esc(ck.note)}</span></div>` : '') +
    `</a>` +
    `${openLink(row.url, '', false)}</li>`
  );
}

/** The groups, each with its count. `stale`: every row is a Mac's last list
 *  (an away Mac's page); `mixed`: the search, where only an away Mac's rows
 *  are, each in gray as of its Mac's last list. */
function groupsHtml(k: Kit, list: Placed[], from: string, stale: boolean | 'mixed' = false): string {
  const old = (p: Placed) => (stale === 'mixed' ? !isLive(p.mac) : stale);
  return GROUPS.map((g) => {
    const rows = list.filter((p) => p.row.group === g.key);
    if (!rows.length) return '';
    return (
      `<section class="grp" aria-label="${esc(g.label)}"><h2 class="grp-h ${g.key}">${ic(g.icon)}${esc(g.label)} <span class="n">${rows.length}</span><span class="col">${stale === true ? '' : esc(g.col)}</span></h2>` +
      `<ul class="rows">${rows.map((p) => sessionRow(k, p, from, old(p))).join('')}</ul></section>`
    );
  }).join('');
}

const emptyHtml = (icon: IconName, head: string, words: string) => `<div class="empty-list">${ic(icon)}<h2>${esc(head)}</h2><p>${esc(words)}</p></div>`;

/** Until a Mac is linked: how to link one, in the Kit's own words. */
export function noMacHtml(lead: string): string {
  return (
    `<section class="empty" aria-labelledby="no-mac"><h2 id="no-mac">${ic('laptop')}No Mac linked yet</h2><p class="lede">${esc(lead)}</p>` +
    `<p class="steps-h">To link your Mac:</p><ol class="steps">` +
    `<li>On your Mac, click the Kit's gauge in the menu bar, then <b>Open Sttark Claude Kit</b>.</li>` +
    `<li>Click <b>Settings</b>, then <b>Link this Mac</b> in the <b>Phone</b> box.</li>` +
    `<li>Sign in with your Sttark Google account, then click <b>Link</b>.</li></ol></section>`
  );
}

/** How a Mac that is not live is now: "Asleep since Thu 6:12 PM." */
function awaySince(k: Kit, m: MacInfo): string {
  const t = m.last_seen;
  const at = t ? whenFull(t, k.now, tzOf(k, m.id)) : null;
  switch (m.state) {
    case 'updating':
      return 'Updating the Kit. It is back in a moment.';
    case 'asleep':
      return at ? `Asleep since ${at}.` : 'Asleep.';
    case 'quit':
      return at ? `The Kit quit at ${at}.` : 'The Kit quit.';
    default:
      return at ? `Not heard from since ${at}.` : 'Not heard from yet.';
  }
}
/** The head of an away Mac's pages: "Mac mini is asleep." */
function awayHead(m: MacInfo): string {
  switch (m.state) {
    case 'updating':
      return `${m.name} is updating the Kit.`;
    case 'asleep':
      return `${m.name} is asleep.`;
    case 'quit':
      return `The Kit on ${m.name} quit.`;
    default:
      return `${m.name} does not answer.`;
  }
}

// ---------- Sessions ----------

/** An archived session's row: a tap opens its page, with Bring it back. On
 *  the Archived tab the day is the heading over it, so the row says the
 *  time; among what a search found, the day too. */
function archivedRow(k: Kit, a: PlacedArchived, search: boolean): string {
  const t = a.item.archived_at;
  return (
    `<li><a class="row" href="${esc(L(k, `/archived/${enc(a.item.cse)}${search ? '?from=search' : ''}`))}"><div class="row-main"><div class="name-line"><span class="name">${esc(a.item.title)}</span></div>` +
    (multi(k) ? `<div class="sub"><span class="mac">${esc(a.mac.name)}</span></div>` : '') +
    `</div><span class="time">${t ? esc(search ? when(t, k.now, a.tz) : clock(t, a.tz)) : ''}</span></a>${openLink(a.item.url, '', false)}</li>`
  );
}

/** What the search found: the sessions in their groups (a Mac that is away:
 *  its last list, in gray), then Archived, every Mac's archived sessions,
 *  newest first; each group with its count. A row opens the session's page,
 *  whose way back is the search. */
function searchList(k: Kit, ui: Ui): string {
  const f = searchAll(k, ui.q);
  const q = ui.q.trim();
  // a live Mac with archived sessions whose list the server has not sent yet: the page asked for it
  const waiting = k.macs.filter((m) => isLive(m) && !k.archived[m.id] && (k.snaps[m.id]?.archived_count ?? 0) > 0);
  const note = waiting.length ? `<p class="quiet">Getting the archived sessions from ${esc(waiting.map((m) => m.name).join(' and '))}...</p>` : '';
  if (!f.rows.length && !f.archived.length) {
    return note + emptyHtml('search', `No session matches “${q}”`, 'Search looks at each session’s name, folder, waits, last check-in and messages, archived sessions too.');
  }
  let html = note + groupsHtml(k, f.rows, 'search', 'mixed');
  if (f.archived.length) {
    html +=
      `<section class="grp" aria-label="Archived"><h2 class="grp-h">${ic('archive')}Archived <span class="n">${f.archived.length}</span><span class="col">Archived</span></h2>` +
      `<ul class="rows">${f.archived.map((a) => archivedRow(k, a, true)).join('')}</ul></section>`;
  }
  return html;
}

function sessionsList(k: Kit, ui: Ui): string {
  if (!k.macs.length) return noMacHtml('Your Claude sessions show here: the ones that need you, the ones Claude works on, and the ones that wait.');
  if (ui.q.trim()) return searchList(k, ui);
  const shown = liveRows(k);
  let html = '';
  if (!shown.length && !k.macs.some(isLive)) html += emptyHtml('moon', 'No Mac is live now', 'The last list of each Mac is under Macs away. Actions work when a Mac is back.');
  else if (!shown.length) html += emptyHtml('inbox', 'Nothing needs you', 'No session works, waits or holds now.');
  html += groupsHtml(k, shown, 'sessions');
  const away = awayMacs(k);
  if (away.length) {
    html +=
      `<section class="grp" aria-label="Macs away"><h2 class="grp-h">${ic('moon')}Macs away <span class="n">${away.length}</span></h2><ul class="rows">` +
      away
        .map((m) => {
          const n = k.snaps[m.id]?.rows.length ?? 0;
          const then = k.snaps[m.id] ? ` ${n} ${n === 1 ? 'session' : 'sessions'} then.` : '';
          return (
            `<li><a class="row nav" href="${esc(L(k, `/mac/${enc(m.id)}`))}"><div class="row-main"><div class="name-line"><span class="name">${esc(m.name)}</span></div>` +
            `<div class="sub">${esc(awaySince(k, m) + then)}</div></div><span class="chev">${ic('chevron-right')}</span></a></li>`
          );
        })
        .join('') +
      `</ul></section>`;
  }
  return html;
}

/** The 5-hour and weekly strip above the tab bar; a tap opens Usage. */
function stripHtml(k: Kit): string {
  const b = usageBlocks(k)[0];
  if (!b || !b.usage.bars.length) return '';
  const tz = b.snap.mac.tz;
  return (
    `<div class="strip" id="strip"><a href="${esc(L(k, '/usage'))}" aria-label="Usage: open the Usage tab">` +
    b.usage.bars
      .slice(0, 2)
      .map((bar) => {
        const full = bar.percent >= 100;
        return (
          `<div><div class="u-top"><span>${esc(bar.name)}</span><b${full ? ' class="warn"' : ''}>${bar.percent}%</b></div>` +
          `<div class="u-bar${full ? ' full' : ''}"><i style="width:${Math.min(100, bar.percent)}%"></i></div>` +
          `<div class="u-reset">${bar.resets ? `Resets ${esc(when(bar.resets, k.now, tz))}` : '&nbsp;'}</div></div>`
        );
      })
      .join('') +
    `</a></div>`
  );
}

function pageSessions(k: Kit, ui: Ui): Drawn {
  const find = ui.find || !!ui.q;
  // the top bar's Search: one search over every session, archived ones too
  const field = find
    ? `<div class="search-row" role="search"><div class="search-field">${ic('search')}<input id="sq" type="search" name="q" placeholder="Search sessions" aria-label="Search sessions" value="${esc(ui.q)}" autocomplete="off" data-form-type="other" data-1p-ignore data-lpignore="true"></div>` +
      `<button type="button" class="close-search" data-act="close-search" aria-label="Close search">${ic('x')}</button></div>`
    : '';
  return { title: 'Sessions', tab: 'sessions', status: 200, html: `<h1 class="vh">Sessions</h1>${field}<div id="list">${sessionsList(k, ui)}</div>${k.macs.length ? stripHtml(k) : ''}` };
}

// ---------- One session ----------

function gone(k: Kit, from: string, ui: Ui, scope: string): Drawn {
  const back = backOf(k, from);
  return {
    title: 'Not in your list',
    tab: back.tab,
    status: 404,
    html:
      crumbs(back.href, back.label) +
      (ui.result && ui.result.scope === scope ? resultHtml(ui.result) : '') +
      `<h1 class="vh">Not in your list</h1>` +
      emptyHtml('inbox', 'This session is not in your list now', 'It may be archived, or its Mac may be away.'),
  };
}

function waitCard(k: Kit, w: Wait, ro: boolean, ui: Ui, tz: string, now: number): string {
  const by = w.by ? `Deadline ${when(w.by, now, tz)} · ${until(w.by, now)}` : 'No deadline';
  return (
    `<div class="card wait"><div><div class="w-what">${esc(w.what)}</div><div class="w-by">${esc(by)}</div>` +
    // the person replied in its thread themselves: the wait goes on, for the other person's reply
    (w.replied ? `<div class="w-rep">${esc(`You replied ${whenFull(w.replied, now, tz)}. It still waits for their reply.`)}</div>` : '') +
    (w.checks ? `<div class="w-how">${esc(w.checks)}</div>` : '') +
    (w.failing ? `<div class="w-fail">Check failing${w.failing_since ? ` since ${esc(whenFull(w.failing_since, k.now, tz))}` : ''}</div>` : '') +
    `</div>` +
    (ro ? '' : actBtn(ui, `stop:${w.id}`, 'Stop', `data-act="stop" data-wait="${esc(w.id)}"`)) +
    `</div>`
  );
}

function stillRuns(b: NonNullable<Row['background']>): string {
  const parts: string[] = [];
  if (b.agents) parts.push(`${b.agents} ${b.agents === 1 ? 'agent' : 'agents'}`);
  if (b.bash) parts.push(`${b.bash} ${b.bash === 1 ? 'command' : 'commands'}`);
  return parts.length ? `${parts.join(' and ')}: ${lowerFirst(b.what)}` : b.what;
}

function changesHtml(k: Kit, cse: string): string {
  const recs = k.records.filter((r) => r.cse === cse && r.reason === 'ok');
  if (!recs.length) return '';
  return (
    `<section class="sec" aria-labelledby="changes-h"><h2 class="sub-h" id="changes-h">Changes from the phone</h2><ul class="log card">` +
    recs.map((r) => `<li>${esc(noStop(r.words))}, ${esc(whenFull(r.at, k.now, tzOf(k, r.mac)))}</li>`).join('') +
    `</ul></section>`
  );
}

/** The messages the Kit kept for this session instead of sending them,
 *  newest first, each with its subject, time and words (their line breaks
 *  kept), then one line on why: the newest one's reason, in the Mac's
 *  words. Alerts off is the person's choice, so the line is steel, never a
 *  warning. */
function messagesHtml(k: Kit, row: Row, tz: string): string {
  const list = row.messages ?? [];
  if (!list.length) return '';
  const why = lowerFirst(noStop(list[0].why.trim()));
  return (
    `<section class="sec msgs" aria-labelledby="msgs-h"><h2 class="sub-h" id="msgs-h">Messages</h2>` +
    list
      .map((m) => {
        const text = m.text.replace(/^\n+|\s+$/g, '');
        return (
          `<article class="card msg"><div class="msg-subj">${esc(m.subject)}</div><div class="msg-at">${esc(whenFull(m.at, k.now, tz))}</div>` +
          (text ? `<p class="msg-text">${esc(text)}</p>` : '') +
          // the person answered it themselves, where it is about: it is handled (a status, with its words)
          (m.replied ? `<div class="msg-rep">${chip('good', `You replied ${whenFull(m.replied, k.now, tz)}`)}</div>` : '') +
          `</article>`
        );
      })
      .join('') +
    `<p class="why">${esc(`${why ? `Not sent: ${why} on your Mac.` : 'Not sent.'} Messages stay here and in the Kit on your Mac.`)}</p></section>`
  );
}

function pageSession(k: Kit, cse: string, from: string, ui: Ui): Drawn {
  const p = findRow(k, cse);
  if (!p) {
    if (findArchived(k, cse)) return pageArchivedItem(k, cse, ui, from);
    return gone(k, from, ui, cse);
  }
  const { row, mac, snap } = p;
  const ro = !isLive(mac);
  const tz = snap.mac.tz;
  const now = ro ? snap.at : k.now;
  const back = backOf(k, from);
  const failing = row.waits.some((w) => w.failing);
  const head = ro
    ? chip('', `As of ${whenFull(snap.at, k.now, tz)}`)
    : row.group === 'needs_you'
      ? chip('warn', 'Needs you')
      : row.group === 'working'
        ? chip('info', 'Claude working')
        : row.group === 'held'
          ? chip('', 'Held')
          : row.group === 'idle'
            ? chip('', 'Idle')
            : failing
              ? chip('warn', 'Check failing')
              : chip('', 'Waiting');
  let html = crumbs(back.href, back.label) + `<div class="title-row"><h1 class="page-title">${esc(row.title)}</h1>${head}</div>`;
  // its Mac (with several), and the folder it works in, which the search finds it by
  const where = [multi(k) ? `On ${esc(mac.name)}` : '', row.folder ? `Folder <span class="folder">${esc(row.folder)}</span>` : ''].filter(Boolean);
  if (where.length) html += `<p class="page-sub">${where.join(' · ')}</p>`;
  if (ro) html += `<div class="card away-head">${ic('moon')}<span><b>${esc(awayHead(mac))}</b> Actions work when this Mac is back.</span></div>`;
  const effortHere = !ro && !!row.session;
  const waitsHere = row.group === 'waiting' && row.waits.length > 0;
  const r = ui.result && ui.result.scope === cse ? ui.result : null;
  // An answer shows where it was asked, or at the top when that part is gone.
  if (r && (r.sec === 'top' || (r.sec === 'waits' && !waitsHere) || (r.sec === 'effort' && !effortHere) || ((r.sec === 'limit' || r.sec === 'alerts') && ro))) html += resultHtml(r);
  html += openLink(row.url, 'btn full', true);
  // Reading the message is why the person opened the page: right under Open in Claude.
  html += messagesHtml(k, row, tz);

  if (row.group === 'needs_you') {
    html +=
      `<section class="sec" aria-labelledby="needs-h"><h2 class="sub-h" id="needs-h">Needs you</h2><div class="card facts">` +
      `<div class="f"><span>Waiting for</span><span>${esc(row.session?.waiting_since ? span(now - row.session.waiting_since) : row.time_at ? span(now - row.time_at) : '')}</span></div>` +
      (row.session?.why ? `<div class="f"><span>Why</span><span>${esc(row.session.why)}</span></div>` : '') +
      `</div><p class="why">Answer it in Claude. Opening it there clears it from Needs you.</p></section>`;
  } else if (row.group === 'working') {
    const since = row.session?.turn_at ?? row.time_at;
    const ck = checkinOf(row);
    html +=
      `<div class="sec"><div class="card facts"><div class="f"><span>Working for</span><span>${esc(since ? span(now - since) : '')}</span></div>` +
      (row.background ? `<div class="f"><span>Still runs</span><span>${esc(stillRuns(row.background))}</span></div>` : '') +
      `</div></div>`;
    if (ck) {
      html +=
        `<section class="sec" aria-labelledby="ck-h"><h2 class="sub-h" id="ck-h">Last check-in</h2>` +
        `<div class="card ck-card"><p>${esc(ck.note)}</p><p class="ck-when">${esc(`${now - ck.at < 60 ? 'Just now' : `${span(now - ck.at)} ago`}, at ${clock(ck.at, tz)}`)}</p></div>` +
        `<p class="why">A new one every 15 min while the work runs.</p></section>`;
    }
  } else if (waitsHere) {
    const many = row.waits.length > 1;
    html +=
      `<section class="sec" aria-labelledby="waits-h"><div class="sub-h"><h2 class="l" id="waits-h">Waits on ${esc(waitsInWords(row.waits))}</h2>${infoBtn(ui, 'waits', 'About these waits')}</div>` +
      noteHtml(
        ui,
        'waits',
        `It comes back when any one wait ends: when the thing occurs, or at its deadline. ${
          snap.flags.alerts_off
            ? 'Then its message stays in the Kit on this session, since alerts are off in Reach me by on your Mac.'
            : !alertsOn(row)
              ? 'Then its message stays in the Kit on this session, since its alerts are off.'
              : 'Then it tells you the way you set in Reach me by on your Mac.'
        }${many ? ' Its other waits stay open.' : ''}`,
      ) +
      resultAt(ui, cse, 'waits') +
      row.waits.map((w) => waitCard(k, w, ro, ui, tz, now)).join('');
    if (!ro) {
      html +=
        `<div class="btn-row">${actBtn(ui, 'bring', 'Bring it back now', 'data-act="bring"')}` +
        `${actBtn(ui, 'stopall', 'Stop waiting', 'data-act="stopall"')}</div>`;
    }
    html += `</section>`;
  } else if (row.group === 'held' && row.hold) {
    const h = row.hold;
    html +=
      `<div class="sec"><div class="card facts">` +
      `<div class="f"><span>Holds at</span><span>${esc(h.at ? `${h.at}% of the ${limitName(h.limit)}` : `The ${limitName(h.limit)}`)}</span></div>` +
      (h.until ? `<div class="f"><span>Goes on</span><span>${esc(`${when(h.until, now, tz)} · ${until(h.until, now)}`)}</span></div>` : '') +
      (h.agents ? `<div class="f"><span>Agents</span><span>${h.agents} ${h.agents === 1 ? 'agent holds' : 'agents hold'} too</span></div>` : '') +
      `</div><p class="why">It uses no credits while it holds. To let it go on now, set At the usage limit to Always use credits.</p></div>`;
  }

  // Effort.
  if (row.session) {
    const s = row.session;
    if (ro) {
      html += `<section class="sec" aria-labelledby="eff-h"><h2 class="sub-h" id="eff-h">Effort</h2><div class="card readout"><span>${esc(levelLabel(s.level) || 'Not set')}</span><span class="time">${s.manual ? 'Manual' : 'Auto'}</span></div></section>`;
    } else {
      const waiting = row.group === 'waiting';
      const busy = !!ui.sending;
      const off = waiting ? ' aria-disabled="true"' : busy ? ' aria-disabled="true"' : '';
      html +=
        `<section class="sec" aria-labelledby="eff-h"><div class="eff-h"><h2 class="sub-h" id="eff-h">Effort</h2>` +
        `<button type="button" class="switch${waiting ? ' off' : ''}" role="switch" aria-checked="${!s.manual}" data-act="${waiting ? 'noop' : 'auto'}" data-k="auto"${off}>${ui.sending === 'auto' ? 'Sending...' : 'Auto'} <span class="track"></span></button></div>` +
        `<div class="segments${waiting ? ' off' : ''}" role="group" aria-label="Effort level">` +
        LEVELS.map((l) => {
          const key = `lvl:${l.key}`;
          const sending = ui.sending === key;
          return `<button type="button" aria-pressed="${s.level === l.key}" data-act="${waiting ? 'noop' : 'level'}" data-level="${l.key}" data-k="${key}"${off}${sending ? ' class="sending"' : ''}>${sending ? 'Sending...' : l.label}</button>`;
        }).join('') +
        `</div>` +
        resultAt(ui, cse, 'effort') +
        `<p class="why">${esc(
          waiting
            ? 'It does not run while it waits. Set the effort when it comes back.'
            : s.manual
              ? 'Manual: you set the effort. Turn Auto on to give it back to Claude.'
              : `Auto: Claude sets the effort.${s.reason ? ` Latest reason: ${noStop(lowerFirst(s.reason))}.` : ''}`,
        )}</p></section>`;
    }
  }

  // At the usage limit.
  const choices = limitChoices(row, snap.flags.credits_all);
  const value = limitValue(row);
  const settings = snap.flags.credits_all ? 'Settings on your Mac: use credits at the limit.' : 'Settings on your Mac: hold at the limit, and go on by itself when it resets.';
  if (ro) {
    html += `<section class="sec" aria-labelledby="lim-h"><h2 class="sub-h" id="lim-h">At the usage limit</h2><div class="card readout"><span>${esc(choices.find((c) => c.value === value)?.label ?? '')}</span></div></section>`;
  } else {
    const sending = ui.sending === 'limit';
    html +=
      `<section class="sec"><label class="sub-h" for="limit-sel">At the usage limit</label><div class="select-wrap${sending ? ' sending' : ''}">` +
      `<select id="limit-sel" data-act="limit" data-k="limit"${sending || ui.sending ? ' disabled' : ''}>` +
      (sending ? `<option>Sending...</option>` : choices.map((c) => `<option value="${c.value}"${c.value === value ? ' selected' : ''}>${esc(c.label)}</option>`).join('')) +
      `</select>${ic('chevron-down')}</div>` +
      resultAt(ui, cse, 'limit') +
      `<p class="why">${esc(settings)}</p></section>`;
  }

  // Alerts: whether this session may reach the person the Reach me by ways.
  const on = alertsOn(row);
  if (ro) {
    html += `<section class="sec" aria-labelledby="al-h"><h2 class="sub-h" id="al-h">Alerts</h2><div class="card readout"><span>${on ? 'On' : 'Off'}</span></div></section>`;
  } else {
    const ways = snap.reach.map((w) => REACH_WAYS[w as keyof typeof REACH_WAYS] ?? w);
    const list = ways.length > 1 ? `${ways.slice(0, -1).join(', ')} and ${ways[ways.length - 1]}` : ways[0];
    html +=
      `<section class="sec" aria-labelledby="al-h"><div class="eff-h"><h2 class="sub-h" id="al-h">Alerts</h2>` +
      `<button type="button" class="switch" role="switch" aria-checked="${on}" aria-labelledby="al-h" data-act="alerts" data-k="alerts"${ui.sending ? ' aria-disabled="true"' : ''}>` +
      `${ui.sending === 'alerts' ? 'Sending...' : on ? 'On' : 'Off'} <span class="track"></span></button></div>` +
      resultAt(ui, cse, 'alerts') +
      `<p class="why">${esc(
        !on
          ? 'Off, as each session starts: nothing about it goes out, not even a Needs you notice. Its messages stay here and in the Kit on your Mac.'
          : snap.flags.alerts_off
            ? 'On, but alerts are off for every session in Reach me by on your Mac, so its messages stay in the Kit.'
            : list
              ? `On: it reaches you by ${list}, as set in Reach me by on your Mac.`
              : 'On, but no way is checked in Reach me by on your Mac.',
      )}</p></section>`;
  }
  html += changesHtml(k, cse);
  return { title: row.title, tab: back.tab, status: 200, html };
}

// ---------- Archived ----------

function archivedList(k: Kit): string {
  if (!k.macs.length) return noMacHtml('Your archived sessions show here, so you can find an old session and bring it back.');
  const list = archivedOf(k);
  // A live Mac that has archived sessions but whose list the server does
  // not have yet: the server asks it when this tab opens.
  const waiting = k.macs.filter((m) => isLive(m) && !k.archived[m.id] && (k.snaps[m.id]?.archived_count ?? 0) > 0);
  const note = waiting.length ? `<p class="quiet">Getting the list from ${esc(waiting.map((m) => m.name).join(' and '))}...</p>` : '';
  // A session that waits on someone else is under Sessions, archived or not,
  // so it is never in this list; the top bar's Search finds both.
  if (!list.length) return note + (waiting.length ? '' : emptyHtml('archive', 'No archived sessions', 'Sessions you archive in the Claude app show here.'));
  const days: { key: string; label: string; rows: typeof list }[] = [];
  for (const a of list) {
    const t = a.item.archived_at;
    const key = t ? dayKey(t, a.tz) : 'none';
    let d = days.find((x) => x.key === key);
    if (!d) days.push((d = { key, label: t ? dayLabel(t, k.now, a.tz) : 'Earlier', rows: [] }));
    d.rows.push(a);
  }
  return (
    note +
    days
      .map(
        (d) =>
          `<section class="grp" aria-label="${esc(d.label)}"><h2 class="grp-h">${esc(d.label)} <span class="n">${d.rows.length}</span><span class="col">Archived</span></h2><ul class="rows">` +
          d.rows.map((a) => archivedRow(k, a, false)).join('') +
          `</ul></section>`,
      )
      .join('')
  );
}

/** Archived: the list, by day. The top bar's Search finds archived sessions
 *  with every other session, so this tab has no search of its own. */
function pageArchived(k: Kit): Drawn {
  return { title: 'Archived', tab: 'archived', status: 200, html: `<h1 class="vh">Archived</h1><div id="list">${archivedList(k)}</div>` };
}

function pageArchivedItem(k: Kit, cse: string, ui: Ui, from = 'archived'): Drawn {
  const a = findArchived(k, cse);
  // the way back: the Archived tab, or where the page was opened from (what the search found, Usage, a Mac)
  const way = from === 'sessions' ? 'archived' : from;
  if (!a) {
    // Brought back: it is in the list again, on its own page.
    if (findRow(k, cse)) return pageSession(k, cse, way, ui);
    return gone(k, way, ui, cse);
  }
  const back = backOf(k, way);
  const { item, mac, tz } = a;
  const live = isLive(mac);
  let html =
    crumbs(back.href, back.label) +
    `<div class="title-row"><h1 class="page-title">${esc(item.title)}</h1>${chip('', 'Archived')}</div>` +
    // Any answer for it: also Stop waiting's, after which it shows here.
    (ui.result && ui.result.scope === cse ? resultHtml(ui.result) : '') +
    `<div class="card facts">` +
    (item.archived_at ? `<div class="f"><span>Archived</span><span>${esc(`${dayLabel(item.archived_at, k.now, tz)}, ${clock(item.archived_at, tz)}`)}</span></div>` : '') +
    `<div class="f"><span>Folder</span><span class="folder">${esc(item.folder)}</span></div>` +
    (multi(k) ? `<div class="f"><span>Mac</span><span>${esc(mac.name)}</span></div>` : '') +
    `</div>`;
  // The Mac said its conversation is not there: Bring it back cannot work.
  const cannot = ui.result?.scope === cse && ui.result.reason === 'not_here';
  if (live && !cannot) {
    const sending = ui.sending === 'unarchive';
    html +=
      `<div class="sec">${
        sending
          ? `<button type="button" class="btn full sending" aria-disabled="true" data-k="unarchive">Sending...</button>`
          : `<button type="button" class="btn full" data-act="unarchive" data-k="unarchive"${ui.sending ? ' aria-disabled="true"' : ''}>${ic('rotate-ccw')}Bring it back</button>`
      }` +
      `<p class="why">It goes back to your list on the same link, and Claude goes on with it.</p>` +
      `${openLink(item.url, 'btn ghost full open-second', true)}</div>`;
  } else if (cannot) {
    html += `<div class="sec">${openLink(item.url, 'btn full', true)}</div>`;
  } else {
    html +=
      `<div class="sec"><div class="card away-head">${ic('moon')}<span><b>${esc(awayHead(mac))}</b> Bring it back works when this Mac is back.</span></div>` +
      `${openLink(item.url, 'btn full', true)}</div>`;
  }
  html += changesHtml(k, cse);
  return { title: item.title, tab: back.tab, status: 200, html };
}

// ---------- Usage ----------

function meters(k: Kit, b: ReturnType<typeof usageBlocks>[number]): string {
  const tz = b.snap.mac.tz;
  const u = b.usage;
  if (!u.bars.length) return `<div class="card meters"><div class="m-foot"><span>No usage read yet.</span></div></div>`;
  return (
    `<div class="card meters">` +
    u.bars
      .map((bar) => {
        const full = bar.percent >= 100;
        return (
          `<div class="meter"><div class="m-top"><span class="m-label">${esc(bar.name)}</span><span class="m-pct${full ? ' warn' : ''}">${bar.percent}%</span></div>` +
          `<div class="m-bar${full ? ' full' : ''}" role="img" aria-label="${esc(`${bar.name}: ${bar.percent}%`)}"><i style="width:${Math.min(100, bar.percent)}%"></i><s style="left:60%"></s><s style="left:80%"></s></div>` +
          `<div class="m-ticks" aria-hidden="true"><span style="left:60%">60%</span><span style="left:80%">80%</span></div>` +
          `<div class="m-reset">${bar.resets ? esc(`Resets ${when(bar.resets, k.now, tz)} · ${until(bar.resets, k.now)}`) : ''}</div></div>`
        );
      })
      .join('') +
    `<div class="m-foot"><span class="key"><s></s>Where a session holds</span><span>${u.at ? esc(`Read ${whenFull(u.at, k.now, tz)}`) : 'Not read yet'}</span></div></div>`
  );
}

// ---------- Usage: By session ----------
// Each session's share of the person's use on each Mac in a period, and the
// part its agents did (schema/usage.v1.json), under the limits. A share is
// never a percent of the limit, and the note says so. The session's part is
// the info blue and its agents' a lighter tint of it (never green, which
// means "do this" and "you are here"). No folder or path anywhere. A Kit
// that sends it adds the human work estimate (view/human.ts): a line under
// the totals with its ⓘ, and the end of each row's line.

const PICKS: [UsagePick, string][] = [
  ['today', 'Today'],
  ['7d', '7 days'],
  ['30d', '30 days'],
  ['custom', 'Custom'],
];
/** Rows shown before Show all. */
export const USAGE_SHOWN = 15;
/** A live Mac that has not sent its list this long after the page asked is
 *  said so. */
export const USAGE_WAIT_S = 15;
const DEFAULT_USAGE: UsageView = { pick: '7d', from: null, to: null, all: false };

/** 28.3%; under 0.05, <0.1%. */
const pct1 = (p: number) => (p > 0 && p < 0.05 ? '<0.1%' : `${p.toFixed(1)}%`);
/** 77%; under 0.5, <1%. */
const pct0 = (p: number) => (p > 0 && p < 0.5 ? '<1%' : `${Math.round(p)}%`);
/** 8.1 billion, 412 million, 15 thousand. */
function tokensWords(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} billion`;
  if (n >= 1e6) return `${n >= 1e8 ? Math.round(n / 1e6) : (n / 1e6).toFixed(1)} million`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} thousand`;
  return String(Math.round(n));
}
/** $3,106; under $100, $12.40. */
const usd = (x: number) => `$${x >= 100 ? Math.round(x).toLocaleString('en-US') : x.toFixed(2)}`;

/** The first and last day of Custom before the person picks: the 7 days to
 *  today, in the first Mac's time zone. */
function rangeDefault(k: Kit): { from: string; to: string } {
  const tz = tzOf(k);
  return { from: dayKey(k.now - 6 * 86400, tz), to: dayKey(k.now, tz) };
}

function rangeForm(k: Kit, u: UsageView): string {
  const d = rangeDefault(k);
  const field = (name: 'from' | 'to', label: string, value: string) =>
    `<label class="bys-field"><span>${label}</span><input type="date" name="${name}" value="${esc(value)}" max="${esc(d.to)}" required autocomplete="off" data-form-type="other" data-1p-ignore data-lpignore="true" data-k="${name}"></label>`;
  return (
    `<form class="bys-range" id="bys-range" method="get" action="${esc(L(k, '/usage'))}"><input type="hidden" name="p" value="custom">` +
    field('from', 'From', u.from ?? d.from) +
    field('to', 'To', u.to ?? d.to) +
    `<button type="submit" class="btn ghost" data-k="range-show">Show</button></form>`
  );
}

/** Words joined with " · ", each part kept whole when the line wraps. */
const parts = (words: string[]) => words.map((w, i) => `<span>${esc(w)}${i < words.length - 1 ? ' ·' : ''}</span>`).join(' ');

function usageRow(k: Kit, r: UsageRow, top: number, tz: string): string {
  const meta = [
    r.last_active ? `last active ${when(r.last_active, k.now, tz)}` : '',
    r.agents ? `${r.agents} ${r.agents === 1 ? 'agent' : 'agents'}` : '',
    r.human_hours && r.human_hours > 0 ? `≈ ${personWords(r.human_hours)}` : '',
  ].filter(Boolean);
  const own = Math.max(0, r.share - r.agent_share);
  const ag = Math.min(r.share, r.agent_share);
  const width = Math.max(1, Math.min(100, (r.share / top) * 100));
  const label = `${pct1(r.share)} of your use: the session ${pct1(own)}, its agents ${pct1(ag)}`;
  const bar =
    `<div class="bys-bar" style="width:${width.toFixed(1)}%" role="img" aria-label="${esc(label)}">` +
    (own > 0 ? `<i class="own" style="flex:${own.toFixed(2)}"></i>` : '') +
    (ag > 0 ? `<i class="ag" style="flex:${ag.toFixed(2)}"></i>` : '') +
    `</div>`;
  return (
    `<li><div class="bys-main"><div class="bys-top"><span class="name">${esc(r.title)}</span><b class="bys-pct">${pct1(r.share)}</b></div>` +
    (meta.length ? `<div class="sub bys-meta">${parts(meta)}</div>` : '') +
    `${bar}</div>${r.cse ? openLink(sessionLink(r.cse), '', false) : '<span class="open-none" aria-hidden="true"></span>'}</li>`
  );
}

/** The human work estimate under the totals, with its ⓘ: only from a Kit
 *  that sends it, and only when there was work. Each Mac has its own. */
function humanLine(ui: Ui, mac: MacInfo, list: UsageList, live: boolean): string {
  const h = list.total.human_hours ?? 0;
  if (!(h > 0)) return '';
  const key = `human-${mac.id}`;
  return (
    `<div class="bys-human${live ? '' : ' stale'}"><p><span>Human work ≈ <b>${esc(personWords(h))}</b> ·</span> <span>${esc(peopleWords(h, list.from, list.to, list.period))}</span></p>` +
    `${infoBtn(ui, key, 'About human work')}</div>` +
    noteHtml(ui, key, humanNote(list.factors))
  );
}

/** One Mac's list: its totals, then its sessions, biggest share first. */
function macUsage(k: Kit, ui: Ui, u: UsageView, mac: MacInfo, list: UsageList | undefined, many: boolean): string {
  const head = many ? `<h3 class="bys-mac">${esc(mac.name)}</h3>` : '';
  const live = isLive(mac);
  if (!list) {
    if (!live) return `${head}<p class="quiet">No list from ${esc(mac.name)} for this period. It comes when this Mac is back.</p>`;
    const waited = ui.usageAsked ? k.now - ui.usageAsked >= USAGE_WAIT_S : false;
    return (
      head +
      `<p class="quiet">${
        waited
          ? `${esc(mac.name)} did not send the list. A Kit from before this list does not send it; the Kit updates by itself within an hour.`
          : `Getting the list from ${esc(mac.name)}...`
      }</p>`
    );
  }
  const tz = tzOf(k, mac.id);
  let html = head;
  if (!live) html += `<p class="quiet">As of ${esc(whenFull(list.at, k.now, tz))}. ${esc(mac.name)} is away.</p>`;
  if (!list.rows.length) return `${html}<p class="quiet">No use in this period.</p>`;
  const t = list.total;
  html += `<p class="bys-tot">${t.sessions} ${t.sessions === 1 ? 'session' : 'sessions'} · ${tokensWords(t.tokens)} tokens · agents did <b>${pct0(t.agent_share)}</b> · worth ${usd(t.usd)} at API prices</p>`;
  html += humanLine(ui, mac, list, live);
  const top = list.rows[0].share || 1;
  const shown = u.all ? list.rows : list.rows.slice(0, USAGE_SHOWN);
  html += `<div${live ? '' : ' class="stale"'}><ul class="bys-rows">${shown.map((r) => usageRow(k, r, top, tz)).join('')}</ul></div>`;
  const rest = list.rows.slice(shown.length);
  const restN = rest.length + list.more.sessions;
  const restShare = rest.reduce((a, r) => a + r.share, 0) + list.more.share;
  if (restN > 0) {
    html +=
      `<div class="bys-more"><span>${restN} more ${restN === 1 ? 'session' : 'sessions'} · ${pct1(restShare)} of your use</span>` +
      (rest.length ? `<button type="button" class="btn ghost" data-act="usage-all" data-k="usage-all">Show all</button>` : '') +
      `</div>`;
  } else if (u.all && list.rows.length > USAGE_SHOWN) {
    html += `<div class="bys-more"><span>All ${list.rows.length} sessions</span><button type="button" class="btn ghost" data-act="usage-all" data-k="usage-all">Show the top ${USAGE_SHOWN}</button></div>`;
  }
  return html;
}

/** The By session section of Usage: the period, the note, the legend, and
 *  each Mac's list. */
export function bySession(k: Kit, ui: Ui, u: UsageView = DEFAULT_USAGE): string {
  const period = periodOf(u);
  const lists: Record<string, UsageList> = {};
  for (const [id, l] of Object.entries(k.usage ?? {})) if (l.period === period) lists[id] = l;
  let html =
    `<section class="bys sec" aria-labelledby="bys-h"><h2 class="sub-h" id="bys-h">By session</h2>` +
    `<div class="segments periods" role="group" aria-label="Period">` +
    PICKS.map(([key, label]) => `<button type="button" data-act="period" data-pick="${key}" data-k="period:${key}" aria-pressed="${u.pick === key}">${label}</button>`).join('') +
    `</div>`;
  if (u.pick === 'custom') html += rangeForm(k, u);
  const first = Object.values(lists)[0];
  if (first) html += `<p class="bys-days">Claude Code on ${k.macs.length > 1 ? 'your Macs' : 'this Mac'} · ${esc(first.from === first.to ? dayWords(first.from) : `${dayWords(first.from)} to ${dayWords(first.to)}`)}</p>`;
  html +=
    `<p class="bys-note">${ic('info')}<span>Each bar is the session’s share of <b>your use</b> in this period. ` +
    `It is not a percent of your limit: Anthropic gives only the total percent.</span></p>`;
  if (!period) return `${html}<p class="quiet">Pick the first and last day, then Show.</p></section>`;
  html += `<p class="bys-key"><span><i class="own"></i>The session</span><span><i class="ag"></i>Its agents</span></p>`;
  const many = k.macs.length > 1;
  for (const mac of k.macs) html += macUsage(k, ui, u, mac, lists[mac.id], many);
  return `${html}</section>`;
}

function pageUsage(k: Kit, ui: Ui, u?: UsageView): Drawn {
  if (!k.macs.length) return { title: 'Usage', tab: 'usage', status: 200, html: `<h1 class="vh">Usage</h1>${noMacHtml('Your 5-hour and weekly usage shows here, with the sessions that hold at the limit.')}` };
  const blocks = usageBlocks(k);
  const held = liveRows(k).filter((p) => p.row.group === 'held');
  let html = `<h1 class="vh">Usage</h1>`;
  if (!blocks.length) html += emptyHtml('gauge', 'No usage yet', 'Your Mac sends its usage when it connects.');
  blocks.forEach((b, i) => {
    const tz = b.snap.mac.tz;
    const reached = b.usage.reached;
    const mine = held.filter((p) => p.snap.mac.account === b.account);
    const first = mine.map((p) => p.row.hold?.until ?? p.row.time_at).filter((t): t is number => !!t).sort((x, y) => x - y)[0];
    const firstAt = first ? when(first, k.now, tz) : '';
    if (blocks.length > 1) html += `<h2 class="sub-h${i ? ' block-h' : ''}">${esc(b.macs.map((m) => m.name).join(' and '))}</h2>`;
    html +=
      `<div class="lead">${reached ? chip('warn', `At the ${limitName(reached.name)}`) : chip('', 'Under the limits')}` +
      `<p>${esc(mine.length ? (mine.length === 1 ? `1 session holds.${firstAt ? ` It goes on at ${firstAt}.` : ''}` : `${mine.length} sessions hold.${firstAt ? ` The first goes on at ${firstAt}.` : ''}`) : 'No session holds now.')}</p></div>` +
      meters(k, b);
  });
  if (held.length) {
    html +=
      `<section class="grp sec" aria-label="Held at usage limit"><h2 class="grp-h has-info">${ic('circle-pause')}Held at usage limit <span class="n">${held.length}</span>${infoBtn(ui, 'holds', 'About holds')}<span class="col">Goes on</span></h2>` +
      noteHtml(ui, 'holds', 'Held sessions use no credits. Each one goes on by itself when its limit resets. To let one go on now, open it and set At the usage limit to Always use credits.') +
      `<ul class="rows">${held.map((p) => sessionRow(k, p, 'usage', false)).join('')}</ul></section>`;
  }
  const credits = [...new Set(blocks.map((b) => b.snap.flags.credits_all))];
  if (credits.length === 1) {
    html += `<div class="card fact"><div class="f-top"><span>Use credits at the usage limit</span><b>${credits[0] ? 'On' : 'Off'}</b></div><p>Change it in Settings on your Mac.</p></div>`;
  } else if (credits.length > 1) {
    html +=
      `<div class="card fact"><div class="f-top"><span>Use credits at the usage limit</span></div>` +
      blocks.map((b) => `<div class="f-top f-mac"><span>${esc(b.mac.name)}</span><b>${b.snap.flags.credits_all ? 'On' : 'Off'}</b></div>`).join('') +
      `<p>Change it in Settings on your Mac.</p></div>`;
  }
  html += bySession(k, ui, u);
  return { title: 'Usage', tab: 'usage', status: 200, html };
}

// ---------- A Mac ----------

function pageMac(k: Kit, id: string, ui: Ui): Drawn {
  const m = macById(k, id);
  if (!m) {
    return {
      title: 'Not linked',
      tab: 'sessions',
      status: 404,
      html: crumbs(L(k, '/'), 'Sessions') + `<h1 class="vh">Not linked</h1>` + emptyHtml('laptop', 'This Mac is not linked to your account', 'It may have been removed. Menu lists your Macs.'),
    };
  }
  const snap = k.snaps[m.id];
  const from = `mac:${m.id}`;
  let html = crumbs(L(k, '/'), 'Sessions') + `<div class="title-row"><h1 class="page-title">${esc(m.name)}</h1>${isLive(m) ? chip('good', 'Live') : chip('', STATE_WORD[m.state])}</div>`;
  const list = rowsOf(k, [m]);
  if (isLive(m)) {
    html += list.length ? groupsHtml(k, list, from) : emptyHtml('inbox', 'Nothing on this Mac now', 'No session works, waits or holds on it.');
  } else {
    html += `<div class="card away-head">${ic('moon')}<span><b>${snap ? esc(`As of ${whenFull(snap.at, k.now, snap.mac.tz)}.`) : esc(awayHead(m))}</b> Actions work when this Mac is back. Open in Claude works now.</span></div>`;
    html += list.length ? `<div class="stale">${groupsHtml(k, list, from, true)}</div>` : emptyHtml('inbox', 'No sessions then', 'Its last list had no session that worked, waited or held.');
  }
  void ui;
  return { title: m.name, tab: 'sessions', status: 200, html };
}

// ---------- Menu ----------

const WHEN_AWAY = 'one notice when a session waits 10 min for you and you are away from your Mac';

/** "MacBook Pro", "MacBook Pro and Mac mini", "A, B and C". */
const andList = (names: string[]) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);

/** Under Needs you notices, when every live Mac has Alerts off in Reach me
 *  by: those Macs send no notice (their messages stay in the Kit). Quiet
 *  words, no warning: alerts off is the person's choice. */
function alertsOffLine(k: Kit): string {
  const live = liveMacs(k);
  if (!live.length || !live.every((m) => k.snaps[m.id]?.flags.alerts_off === true)) return '';
  const one = live.length === 1;
  const who = `${andList(live.map((m) => m.name))} ${one ? 'sends' : 'send'}`;
  return `<p class="why" id="notices-alerts">${esc(`${who} no notices while ${one ? 'its' : 'their'} alerts are off in Reach me by on the Mac.`)}</p>`;
}

/** The line under Needs you notices: what this phone gets now, or what keeps
 *  it from getting them and what to do. */
function noticesLine(k: Kit, n: Notices): string {
  switch (n.state) {
    case 'on':
      return esc(`On for this phone${n.since ? ` since ${whenFull(n.since, k.now, tzOf(k))}` : ''}: ${WHEN_AWAY}.`);
    case 'turning_on':
      return 'Turning on...';
    case 'turning_off':
      return 'Turning off...';
    case 'install':
      return (
        `To get notices on this ${esc(n.device === 'phone' ? 'iPhone' : n.device)}, add Claude Kit to your Home Screen: in Safari, tap Share ` +
        `<span class="inline-i" role="img" aria-label="(the Share button)">${ic('share')}</span>, then Add to Home Screen. Open Claude Kit from your Home Screen and turn on notices here.`
      );
    case 'unsupported':
      return 'This browser cannot get notices. On an iPhone, open Claude Kit from your Home Screen (iOS 16.4 or later). On Android, use Chrome.';
    case 'blocked':
      return "Notices for Claude Kit are blocked on this phone. Allow them in the phone's settings, then turn them on here.";
    case 'not_set_up':
      return 'Notices are not set up on this server yet.';
    default:
      return esc(`Off for this phone. Turn on to get ${WHEN_AWAY}.`);
  }
}

/** Menu > Notices: one switch for this phone. It turns on only from a tap
 *  (the phone asks for permission then), and only where the phone can get
 *  notices: on an iPhone, Claude Kit on the Home Screen. */
function noticesHtml(k: Kit, ui: Ui): string {
  const n = noticesOf(k, ui);
  const on = n.state === 'on' || n.state === 'turning_off';
  const can = n.state === 'on' || n.state === 'off';
  const busy = n.state === 'turning_on' || n.state === 'turning_off';
  const problem = n.problem
    ? `<div class="note result fail" role="status">${ic('circle-alert')}<div><b>Notices did not change.</b> ${esc(n.problem)}</div>` +
      `<button type="button" class="x" data-act="notices-clear" aria-label="Close">${ic('x')}</button></div>`
    : '';
  const alerts = alertsOffLine(k);
  return (
    `<section class="m-sec" aria-labelledby="notices-h"><h2 class="sec" id="notices-h">Notices</h2>` +
    `<div class="card set-row" id="notices" data-state="${esc(n.state)}"><span class="s-l">Needs you notices<small id="notices-line">${noticesLine(k, n)}</small></span>` +
    `<button type="button" class="switch" role="switch" aria-checked="${on}" aria-label="Needs you notices" aria-describedby="notices-line${alerts ? ' notices-alerts' : ''}" data-act="notices" data-k="notices"` +
    `${can ? '' : ' aria-disabled="true"'}${busy ? ' aria-busy="true"' : ''}><span class="track"></span></button></div>${alerts}${problem}</section>`
  );
}

function pageMenu(k: Kit, ui: Ui): Drawn {
  const macRows = k.macs.length
    ? k.macs
        .map((m) => {
          const live = isLive(m);
          const seen = live ? 'now' : m.last_seen ? whenFull(m.last_seen, k.now, tzOf(k, m.id)) : 'never';
          const open = ui.confirm === m.id;
          return (
            `<div class="mac-row"><div class="mac-top"><span class="mac-name">${ic('laptop')}${esc(m.name)}</span>${live ? chip('good', 'Live') : chip('', STATE_WORD[m.state])}</div>` +
            `<div class="mac-seen">${esc(`Last seen ${seen} · Kit ${m.kit}`)}</div>` +
            `<div class="mac-acts"${open ? ' hidden' : ''}><button type="button" class="btn danger-line" data-act="remove" data-mac="${esc(m.id)}" data-k="remove:${esc(m.id)}" aria-expanded="${open}" aria-controls="rm-${esc(m.id)}">Remove</button></div>` +
            `<div class="confirm" id="rm-${esc(m.id)}"${open ? '' : ' hidden'}>Remove ${esc(m.name)}? Its sessions stop showing on your phone. To link it again, use the Kit on that Mac.` +
            `<div class="btn-row"><form method="post" action="${esc(L(k, `/macs/${enc(m.id)}/remove`))}"><button type="submit" class="btn danger">Remove</button></form>` +
            `<button type="button" class="btn ghost" data-act="remove-no">Cancel</button></div></div></div>`
          );
        })
        .join('')
    : `<div class="mac-row"><div class="mac-seen">No Mac is linked. On your Mac, open the Kit's Settings and click Link this Mac.</div></div>`;
  const html =
    `<h1 class="page-title">Menu</h1>` +
    `<section class="m-sec" aria-labelledby="macs-h"><h2 class="sec" id="macs-h">Macs</h2><div class="card">${macRows}</div>` +
    `<form method="post" action="${esc(L(k, '/auth/logout-everywhere'))}" data-confirm="Sign out on every phone and browser? Your Macs stay linked." class="btn-row"><button type="submit" class="btn ghost">Sign out everywhere</button></form>` +
    `<p class="why">Sign out everywhere ends each sign-in and notice of yours. Your Macs stay linked.</p></section>` +
    noticesHtml(k, ui) +
    `<section class="m-sec" aria-labelledby="look-h"><h2 class="sec" id="look-h">Look</h2><div class="segments theme-choice" id="theme-toggle" role="group" aria-label="Look">` +
    `<button type="button" data-mode="light" aria-pressed="false">Light</button><button type="button" data-mode="system" aria-pressed="false">Auto</button><button type="button" data-mode="dark" aria-pressed="false">Dark</button></div></section>` +
    `<section class="m-sec" aria-labelledby="phone-h"><h2 class="sec" id="phone-h">This phone</h2><p class="why first">Signed in as ${esc(k.email)}.</p>` +
    `<form method="post" action="${esc(L(k, '/auth/logout'))}"><button type="submit" class="btn ghost full">Sign out</button></form></section>`;
  return { title: 'Menu', tab: null, status: 200, html };
}

// ---------- one entry ----------

export function draw(view: View, k: Kit, ui: Ui): Drawn {
  switch (view.page) {
    case 'sessions':
      return pageSessions(k, ui);
    case 'session':
      return pageSession(k, view.cse, view.from, ui);
    case 'archived':
      return pageArchived(k);
    case 'archived-item':
      return pageArchivedItem(k, view.cse, ui, view.from);
    case 'usage':
      return pageUsage(k, ui, view.usage);
    case 'mac':
      return pageMac(k, view.id, ui);
    case 'menu':
      return pageMenu(k, ui);
  }
}

/** Only the list part of a page with search (Sessions), drawn again as
 *  people type. */
export function drawList(view: View, k: Kit, ui: Ui): string | null {
  if (view.page === 'sessions') return sessionsList(k, ui);
  return null;
}
