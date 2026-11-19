// What each screen puts on the lens. Pure functions: state in, page out.
// The lens is 576 x 288, one fixed font, 27 px a line, no colors, only five
// brightness steps. A header line sits on every screen, so a notice can
// show there on any screen without taking the input.
import type { Pending, SessionDetail, SessionRow, Status } from './api';
import type { PageSpec, TextBox } from './glasses';
import { type TableData, type TablePage, tableBoxes, tablePages } from './picture';
import { LINE_H, fit, padTo, paginate, plainReply, spread, width, wrapLines } from './text';

export const W = 576;
export const H = 288;
const X = 8;
const TW = W - 2 * X; // text box width
const TPX = TW - 4; // what a line may fill, with a little room for rounding

export const BODY_ROWS = 7;

/** One mark per status, so the eye finds what needs it. Glyphs the font has. */
export const MARK: Record<Status, string> = {
  needs_you: '!',
  working: '▷',
  waiting: '○',
  idle: '-',
};

export function statusWords(s: SessionRow): string {
  switch (s.status) {
    case 'needs_you':
      return s.has_pending ? 'needs answer' : 'needs you';
    case 'working':
      return 'working';
    case 'waiting':
      return 'waiting';
    default:
      return 'idle';
  }
}

const RANK: Record<Status, number> = { needs_you: 0, working: 1, waiting: 2, idle: 3 };

/** Needs you first, then working, waiting, idle; by title inside a group,
 *  so rows do not jump about when only times change. */
export function sortRows(rows: SessionRow[]): SessionRow[] {
  return [...rows].sort((a, b) => RANK[a.status] - RANK[b.status] || (a.title || '').localeCompare(b.title || '') || a.id.localeCompare(b.id));
}

// ---------- shared boxes ----------

function head(content: string, color = 4): TextBox {
  return { name: 'head', x: X, y: 0, w: TW, h: 30, content, color };
}

function foot(content: string): TextBox {
  return { name: 'foot', x: X, y: 258, w: TW, h: 30, content: fit(content, TPX), color: 2 };
}

/** A header line, or the notice in its place while one shows. */
function headLine(text: string, right: string, notice: string | null): string {
  return notice ? fit(`! ${notice}`, TPX) : spread(text, right, TPX);
}

// ---------- lists ----------
// The lens's own list widget draws every row but the highlighted one dim,
// which is hard to read on the move. So a list here is one text box: every
// row at full brightness, the chosen row marked with ">" in a column of its
// own. A swipe moves the mark with an in-place text update (no flicker, no
// redraw of the page), the rows scroll when there are more than the box
// shows, and a tap acts on the marked row. The box always holds its lines
// exactly, so every swipe on it comes to the app.

const PICK_COL = 20; // ">" and two spaces, or four spaces: the same width
const ROW_PX = TPX - PICK_COL; // what a row's words may fill

/** The first row to show, so the marked row is in view with a row of the
 *  list above and below it when there is one. Moves as little as it can. */
export function scrollTo(first: number, sel: number, count: number, rows: number): number {
  if (count <= rows) return 0;
  const lo = Math.max(0, sel - 1);
  const hi = Math.min(count - 1, sel + 1);
  let f = first;
  if (lo < f) f = lo;
  if (hi > f + rows - 1) f = hi - rows + 1;
  return Math.max(0, Math.min(f, count - rows));
}

/** The lines a list shows: `rows` rows from `first`, the marked row with ">". */
export function listLines(labels: string[], sel: number, first: number, rows: number): string {
  const out: string[] = [];
  for (let i = first; i < Math.min(labels.length, first + rows); i++) {
    out.push(padTo(i === sel ? '>' : '', PICK_COL) + fit(labels[i], ROW_PX));
  }
  return out.join('\n');
}

/** Where the marked row is, for the header, when the list is longer than its box. */
function position(sel: number, count: number, rows: number): string {
  return count > rows ? `${sel + 1}/${count}` : '';
}

// ---------- home ----------

export const NEW_ROW = '+ New session';
const MAX_SESSION_ROWS = 40;
const MARK_COL = 22;
/** Rows Home shows at once, under the header line. */
export const HOME_ROWS = 9;
const HOME_Y = 34;

export interface HomeRow {
  label: string;
  id: string | null; // null: the New session row
}

export function homeRows(sessions: SessionRow[]): HomeRow[] {
  const rows: HomeRow[] = [{ label: NEW_ROW, id: null }];
  for (const s of sortRows(sessions).slice(0, MAX_SESSION_ROWS)) {
    const mark = padTo(MARK[s.status], MARK_COL);
    const words = ` · ${statusWords(s)}`;
    // The status words follow the title, so a short title is not followed
    // by a run of spaces; a long title is cut to make room for them.
    const title = fit(clean(s.title) || 'Untitled session', ROW_PX - width(mark) - width(words));
    rows.push({ label: `${mark}${title}${words}`, id: s.id });
  }
  return rows;
}

export function homePage(o: { rows: HomeRow[]; sel: number; first: number; needCount: number; offline: string | null; notice: string | null }): PageSpec {
  const count = o.needCount === 0 ? 'Nothing needs you' : `${o.needCount} need${o.needCount === 1 ? 's' : ''} you`;
  const right = [o.offline ?? '', position(o.sel, o.rows.length, HOME_ROWS)].filter(Boolean).join('   ');
  return {
    texts: [
      head(headLine(`Kit   ${count}`, right, o.notice)),
      {
        name: 'sessions',
        x: X,
        y: HOME_Y,
        w: TW,
        h: HOME_ROWS * LINE_H + 2,
        content: listLines(
          o.rows.map((r) => r.label),
          o.sel,
          o.first,
          HOME_ROWS,
        ),
        capture: true,
      },
    ],
  };
}

// ---------- one session ----------

/** A page of a reply: lines of text, or a table drawn as a picture under a
 *  caption line (the reply's short line just before the table, if any). */
export type ReplyPage = string | { table: TableData; caption: string; page: TablePage };

const BODY_Y = 62;
const BODY_H = BODY_ROWS * LINE_H + 2;

export function sessionPages(d: SessionDetail | null, offline = false, pictures = true): ReplyPage[] {
  if (!d) return [offline ? 'Your Mac is offline. This reply shows when Kit reaches the Mac again.' : 'Loading...'];
  let text = plainReply(d.last_reply || '');
  // A plan waiting for approval is what to read: show the plan itself.
  if (d.pending?.kind === 'plan' && d.pending.text) text = plainReply(d.pending.text);
  else if (pictures && d.reply_parts?.some((p) => 'table' in p)) return pictureReply(d.reply_parts);
  if (!text) text = d.status === 'working' ? 'Claude is working. No reply yet.' : 'No reply yet.';
  return paginate(text, TPX, BODY_ROWS);
}

/** The reply's text in pages as always, and each table as picture pages. */
function pictureReply(parts: NonNullable<SessionDetail['reply_parts']>): ReplyPage[] {
  const pages: ReplyPage[] = [];
  let caption = '';
  parts.forEach((p, i) => {
    if ('table' in p) {
      const tps = tablePages(p.table, TW, BODY_H - (caption ? LINE_H + 2 : 0));
      for (const page of tps) pages.push({ table: p.table, caption, page });
      caption = '';
      return;
    }
    let text = plainReply(p.text);
    const next = parts[i + 1];
    if (next && 'table' in next) {
      // The table's lead-in ("Where the press jobs stand:") goes over its picture.
      const cut = text.lastIndexOf('\n\n');
      const last = text.slice(cut + 1).trim();
      if (last && !last.includes('\n') && width(last) <= TPX) {
        caption = last;
        text = cut < 0 ? '' : text.slice(0, cut).trim();
      }
    }
    if (text) pages.push(...paginate(text, TPX, BODY_ROWS));
  });
  return pages.length ? pages : ['No reply yet.'];
}

export function statusLine(row: SessionRow | null, d: SessionDetail | null, flash: string | null): string {
  if (flash) return fit(flash, TPX);
  const s = d ?? row;
  if (!s) return '';
  const p = d?.pending;
  if (p) {
    const lead = p.kind === 'permission' ? 'Needs your OK' : p.kind === 'plan' ? 'Plan to approve' : 'Question';
    const text = p.kind === 'plan' ? 'tap to answer' : clean(p.text || '') || 'tap to answer';
    return fit(`!  ${lead}: ${text}`, TPX);
  }
  const why = clean(s.why || s.status_line || '');
  const words = statusWords(s);
  const first = `${MARK[s.status]}  ${words[0].toUpperCase()}${words.slice(1)}`;
  return fit(why ? `${first} · ${why}` : first, TPX);
}

export function sessionPage(o: {
  title: string;
  pages: ReplyPage[];
  page: number;
  status: string;
  pending: Pending | null;
  notice: string | null;
}): PageSpec {
  const n = o.pages.length;
  const pageMark = n > 1 ? `${o.page + 1}/${n}` : '';
  const tapWord = o.pending ? 'answer' : 'reply';
  const hint = n > 1 ? `Swipe: page   Tap: ${tapWord}   Double tap: back` : `Tap: ${tapWord}   Double tap: back`;
  const page = o.pages[o.page] ?? '';
  const texts: TextBox[] = [
    head(headLine(clean(o.title), pageMark, o.notice)),
    { name: 'status', x: X, y: 28, w: TW, h: 30, content: o.status, color: 3 },
    { name: 'body', x: X, y: BODY_Y, w: TW, h: BODY_H, content: typeof page === 'string' ? page : fit(page.caption, TPX), capture: true },
    foot(hint),
  ];
  if (typeof page === 'string') return { texts };
  // The picture lies over the body box, under its caption; the body box,
  // behind it, still takes the swipes and taps (Even Hub: image-first pages).
  return { texts, images: tableBoxes(page.page, X, BODY_Y + (page.caption ? LINE_H + 2 : 0)) };
}

// ---------- actions ----------

export type ActionItem =
  | { kind: 'option'; id: string; label: string }
  | { kind: 'voice'; label: string }
  | { kind: 'continue'; label: string }
  | { kind: 'back'; label: string };

export function actionItems(pending: Pending | null): ActionItem[] {
  const items: ActionItem[] = [];
  (pending?.options ?? []).slice(0, 12).forEach((o, i) => {
    items.push({ kind: 'option', id: o.id, label: `${i + 1}  ${clean(o.label)}` });
  });
  items.push({ kind: 'voice', label: '●  Reply by voice' });
  items.push({ kind: 'continue', label: '▶  Continue' });
  items.push({ kind: 'back', label: '←  Back' });
  return items;
}

export function askText(pending: Pending | null): string[] {
  if (!pending) return [];
  const lead = pending.kind === 'permission' ? 'Claude asks: OK to go on?' : pending.kind === 'plan' ? 'Approve this plan?' : '';
  const text = plainReply(pending.kind === 'plan' ? '' : pending.text || '');
  const lines = wrapLines([lead, text].filter(Boolean).join('\n'), TPX);
  if (lines.length > 3) {
    const cut = lines.slice(0, 3);
    cut[2] = fit(`${cut[2]} ...`, TPX);
    return cut;
  }
  return lines;
}

/** Where the actions start and how many show at once, under `askLines` lines. */
function actionsBox(askLines: number): { y: number; rows: number } {
  const y = askLines ? 30 + askLines * LINE_H + 6 : 34;
  return { y, rows: Math.floor((H - y - 2) / LINE_H) };
}

export function actionRows(askLines: number): number {
  return actionsBox(askLines).rows;
}

export function actionsPage(o: { title: string; ask: string[]; items: ActionItem[]; sel: number; first: number; notice: string | null }): PageSpec {
  const box = actionsBox(o.ask.length);
  const texts: TextBox[] = [head(headLine(clean(o.title), position(o.sel, o.items.length, box.rows), o.notice), 3)];
  if (o.ask.length) {
    texts.push({ name: 'ask', x: X, y: 30, w: TW, h: o.ask.length * LINE_H + 2, content: o.ask.map((l) => fit(l, TPX)).join('\n'), color: 4 });
  }
  texts.push({
    name: 'actions',
    x: X,
    y: box.y,
    w: TW,
    h: box.rows * LINE_H + 2,
    content: listLines(
      o.items.map((i) => i.label),
      o.sel,
      o.first,
      box.rows,
    ),
    capture: true,
  });
  return { texts };
}

// ---------- voice, confirm, messages: one shape ----------

export function textPage(o: { title: string; body: string; hint: string; notice: string | null; bodyColor?: number }): PageSpec {
  const lines = wrapLines(o.body, TPX).slice(0, BODY_ROWS);
  return {
    texts: [
      head(headLine(o.title, '', o.notice)),
      { name: 'body', x: X, y: 34, w: TW, h: BODY_ROWS * LINE_H + 2, content: lines.join('\n'), capture: true, color: o.bodyColor ?? 4 },
      foot(o.hint),
    ],
  };
}

/** The last lines of a text that grows (live dictation): the newest words stay in view. */
export function tail(text: string, rows: number): string {
  const lines = wrapLines(text, TPX);
  return lines.slice(-rows).join('\n');
}

export function clean(s: string): string {
  return plainReply(s).replace(/\s+/g, ' ').trim();
}
