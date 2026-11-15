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
  STATE_WORD,
  archivedOf,
  awayMacs,
  findArchived,
  findRow,
  isLive,
  levelLabel,
  limitChoices,
  limitValue,
  liveRows,
  macById,
  multi,
  noticesOf,
  rowsOf,
  tzOf,
  usageBlocks,
  waitsInWords,
  type Kit,
  type MacInfo,
  type Notices,
  type Placed,
  type Result,
  type Row,
  type Ui,
  type Wait,
} from './model.ts';
import { clock, dayKey, dayLabel, span, until, when, whenFull } from './time.ts';

export type View =
  | { page: 'sessions' }
  | { page: 'session'; cse: string; from: string }
  | { page: 'archived' }
  | { page: 'archived-item'; cse: string }
  | { page: 'usage' }
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

function rowSub(k: Kit, p: Placed): string {
  const { row, mac } = p;
  let out = '';
  if (row.sub_warn) out += `<span class="warn">${esc(row.sub_warn)}</span> · `;
  if (multi(k)) out += `<span class="mac">${esc(mac.name)}</span> · `;
  return out + esc(row.sub);
}

function sessionRow(k: Kit, p: Placed, from: string, stale: boolean): string {
  const { row, snap } = p;
  const now = stale ? snap.at : k.now;
  const lvl = row.group === 'working' && row.session?.level ? `<span class="lvl${row.session.manual ? ' manual' : ''}">${esc(levelLabel(row.session.level))}</span>` : '';
  return (
    `<li><a class="row" href="${esc(sessionHref(k, row.cse, from))}"><div class="row-main"><div class="name-line"><span class="name">${esc(row.title)}</span>${lvl}</div>` +
    `<div class="sub">${rowSub(k, p)}</div></div><span class="time${row.late && !stale ? ' late' : ''}">${esc(rowTime(row, now, snap.mac.tz))}</span></a>` +
    `${openLink(row.url, '', false)}</li>`
  );
}

function groupsHtml(k: Kit, list: Placed[], from: string, stale = false): string {
  return GROUPS.map((g) => {
    const rows = list.filter((p) => p.row.group === g.key);
    if (!rows.length) return '';
    return (
      `<section class="grp" aria-label="${esc(g.label)}"><h2 class="grp-h ${g.key}">${ic(g.icon)}${esc(g.label)} <span class="n">${rows.length}</span><span class="col">${stale ? '' : esc(g.col)}</span></h2>` +
      `<ul class="rows">${rows.map((p) => sessionRow(k, p, from, stale)).join('')}</ul></section>`
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

function sessionsList(k: Kit, ui: Ui): string {
  if (!k.macs.length) return noMacHtml('Your Claude sessions show here: the ones that need you, the ones Claude works on, and the ones that wait.');
  const all = liveRows(k);
  const q = ui.q.trim().toLowerCase();
  const shown = q ? all.filter((p) => p.row.title.toLowerCase().includes(q) || p.mac.name.toLowerCase().includes(q)) : all;
  let html = '';
  if (q && !shown.length) html += emptyHtml('search', `No session matches “${ui.q.trim()}”`, 'Search looks at session names.');
  else if (!shown.length && !k.macs.some(isLive)) html += emptyHtml('moon', 'No Mac is live now', 'The last list of each Mac is under Macs away. Actions work when a Mac is back.');
  else if (!shown.length) html += emptyHtml('inbox', 'Nothing needs you', 'No session works, waits or holds now.');
  html += groupsHtml(k, shown, 'sessions');
  const away = q ? [] : awayMacs(k);
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
          : failing
            ? chip('warn', 'Check failing')
            : chip('', 'Waiting');
  let html = crumbs(back.href, back.label) + `<div class="title-row"><h1 class="page-title">${esc(row.title)}</h1>${head}</div>`;
  if (multi(k)) html += `<p class="page-sub">On ${esc(mac.name)}</p>`;
  if (ro) html += `<div class="card away-head">${ic('moon')}<span><b>${esc(awayHead(mac))}</b> Actions work when this Mac is back.</span></div>`;
  const effortHere = !ro && !!row.session;
  const waitsHere = row.group === 'waiting' && row.waits.length > 0;
  const r = ui.result && ui.result.scope === cse ? ui.result : null;
  // An answer shows where it was asked, or at the top when that part is gone.
  if (r && (r.sec === 'top' || (r.sec === 'waits' && !waitsHere) || (r.sec === 'effort' && !effortHere) || (r.sec === 'limit' && ro))) html += resultHtml(r);
  html += openLink(row.url, 'btn full', true);

  if (row.group === 'needs_you') {
    html +=
      `<section class="sec" aria-labelledby="needs-h"><h2 class="sub-h" id="needs-h">Needs you</h2><div class="card facts">` +
      `<div class="f"><span>Waiting for</span><span>${esc(row.session?.waiting_since ? span(now - row.session.waiting_since) : row.time_at ? span(now - row.time_at) : '')}</span></div>` +
      (row.session?.why ? `<div class="f"><span>Why</span><span>${esc(row.session.why)}</span></div>` : '') +
      `</div><p class="why">Answer it in Claude. Opening it there clears it from Needs you.</p></section>`;
  } else if (row.group === 'working') {
    const since = row.session?.turn_at ?? row.time_at;
    html +=
      `<div class="sec"><div class="card facts"><div class="f"><span>Working for</span><span>${esc(since ? span(now - since) : '')}</span></div>` +
      (row.background ? `<div class="f"><span>Still runs</span><span>${esc(stillRuns(row.background))}</span></div>` : '') +
      `</div></div>`;
  } else if (waitsHere) {
    const many = row.waits.length > 1;
    html +=
      `<section class="sec" aria-labelledby="waits-h"><div class="sub-h"><h2 class="l" id="waits-h">Waits on ${esc(waitsInWords(row.waits))}</h2>${infoBtn(ui, 'waits', 'About these waits')}</div>` +
      noteHtml(ui, 'waits', `It comes back when any one wait ends: when the thing occurs, or at its deadline. Then it tells you the way you set in Reach me by on your Mac.${many ? ' Its other waits stay open.' : ''}`) +
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
  html += changesHtml(k, cse);
  return { title: row.title, tab: back.tab, status: 200, html };
}

// ---------- Archived ----------

function archivedList(k: Kit, ui: Ui): string {
  if (!k.macs.length) return noMacHtml('Your archived sessions show here, so you can find an old session and bring it back.');
  const all = archivedOf(k);
  // A live Mac that has archived sessions but whose list the server does
  // not have yet: the server asks it when this tab opens.
  const waiting = k.macs.filter((m) => isLive(m) && !k.archived[m.id] && (k.snaps[m.id]?.archived_count ?? 0) > 0);
  const note = waiting.length ? `<p class="quiet">Getting the list from ${esc(waiting.map((m) => m.name).join(' and '))}...</p>` : '';
  if (!all.length) return note + (waiting.length ? '' : emptyHtml('archive', 'No archived sessions', 'Sessions you archive in the Claude app show here.'));
  const q = ui.q.trim().toLowerCase();
  const list = q ? all.filter((a) => a.item.title.toLowerCase().includes(q) || a.item.folder.toLowerCase().includes(q)) : all;
  if (!list.length) return note + emptyHtml('search', `No archived session matches “${ui.q.trim()}”`, 'Search looks at names and folders.');
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
          d.rows
            .map(
              (a) =>
                `<li><a class="row" href="${esc(L(k, `/archived/${enc(a.item.cse)}`))}"><div class="row-main"><div class="name-line"><span class="name">${esc(a.item.title)}</span></div>` +
                `<div class="sub">${multi(k) ? `<span class="mac">${esc(a.mac.name)}</span> · ` : ''}<span class="folder">${esc(a.item.folder)}</span></div></div>` +
                `<span class="time">${a.item.archived_at ? esc(clock(a.item.archived_at, a.tz)) : ''}</span></a>${openLink(a.item.url, '', false)}</li>`,
            )
            .join('') +
          `</ul></section>`,
      )
      .join('')
  );
}

function pageArchived(k: Kit, ui: Ui): Drawn {
  const field =
    // The field's own clear button (type=search) empties it.
    `<div class="search-row" role="search"><div class="search-field">${ic('search')}<input id="aq" type="search" name="q" placeholder="Search archived sessions" aria-label="Search archived sessions" value="${esc(ui.q)}" autocomplete="off" data-form-type="other" data-1p-ignore data-lpignore="true"></div></div>`;
  return { title: 'Archived', tab: 'archived', status: 200, html: `<h1 class="vh">Archived</h1>${k.macs.length ? field : ''}<div id="list">${archivedList(k, ui)}</div>` };
}

function pageArchivedItem(k: Kit, cse: string, ui: Ui, from = 'archived'): Drawn {
  const a = findArchived(k, cse);
  if (!a) {
    // Brought back: it is in the list again, on its own page.
    if (findRow(k, cse)) return pageSession(k, cse, 'archived', ui);
    return gone(k, 'archived', ui, cse);
  }
  const back = backOf(k, from === 'sessions' ? 'archived' : from);
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
  return { title: item.title, tab: 'archived', status: 200, html };
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

function pageUsage(k: Kit, ui: Ui): Drawn {
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
  return (
    `<section class="m-sec" aria-labelledby="notices-h"><h2 class="sec" id="notices-h">Notices</h2>` +
    `<div class="card set-row" id="notices" data-state="${esc(n.state)}"><span class="s-l">Needs you notices<small id="notices-line">${noticesLine(k, n)}</small></span>` +
    `<button type="button" class="switch" role="switch" aria-checked="${on}" aria-label="Needs you notices" aria-describedby="notices-line" data-act="notices" data-k="notices"` +
    `${can ? '' : ' aria-disabled="true"'}${busy ? ' aria-busy="true"' : ''}><span class="track"></span></button></div>${problem}</section>`
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
      return pageArchived(k, ui);
    case 'archived-item':
      return pageArchivedItem(k, view.cse, ui);
    case 'usage':
      return pageUsage(k, ui);
    case 'mac':
      return pageMac(k, view.id, ui);
    case 'menu':
      return pageMenu(k, ui);
  }
}

/** Only the list part of a page with search, drawn again as people type. */
export function drawList(view: View, k: Kit, ui: Ui): string | null {
  if (view.page === 'sessions') return sessionsList(k, ui);
  if (view.page === 'archived') return archivedList(k, ui);
  return null;
}
