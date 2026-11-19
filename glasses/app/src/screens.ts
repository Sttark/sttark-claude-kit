// What each screen puts on the lens. Pure functions: state in, page out.
// The lens is 576 x 288, one fixed font, 27 px a line, no colors, only five
// brightness steps. A header line sits on every screen, so a notice can
// show there on any screen without taking the input.
import type { Pending, SessionDetail, SessionRow, Status } from './api';
import type { ListBox, PageSpec, TextBox } from './glasses';
import { ITEM_BYTES, LINE_H, byteLength, clampBytes, fit, padTo, paginate, plainReply, spread, width, wrapLines } from './text';

export const W = 576;
export const H = 288;
const X = 8;
const TW = W - 2 * X; // text box width
const TPX = TW - 4; // what a line may fill, with a little room for rounding
const ROW_PX = W - 2 * 12 - 16; // a list row's words (12 px padding each side, the highlight border)

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

/** A list as tall as its rows (40 px each): the lens centers rows in a
 *  taller list, which leaves a gap under the words above it. */
function listHeight(rows: number, most: number): number {
  return Math.min(rows, most) * 40 + 4;
}

// ---------- home ----------

export const NEW_ROW = '+ New session';
const MAX_SESSION_ROWS = 19; // a list holds 20 rows
const MARK_COL = 22;

export interface HomeRow {
  label: string;
  id: string | null; // null: the New session row
}

export function homeRows(sessions: SessionRow[]): HomeRow[] {
  const rows: HomeRow[] = [{ label: NEW_ROW, id: null }];
  for (const s of sortRows(sessions).slice(0, MAX_SESSION_ROWS)) {
    const mark = padTo(MARK[s.status], MARK_COL);
    const words = ` · ${statusWords(s)}`;
    // A row holds 63 bytes, so the status words follow the title (lining
    // them up in a column would take more spaces than a row holds).
    let title = fit(clean(s.title) || 'Untitled session', ROW_PX - width(mark) - width(words));
    title = clampBytes(title, ITEM_BYTES - byteLength(mark) - byteLength(words));
    rows.push({ label: `${mark}${title}${words}`, id: s.id });
  }
  return rows;
}

export function homePage(o: { rows: HomeRow[]; needCount: number; offline: string | null; notice: string | null }): PageSpec {
  const count = o.needCount === 0 ? 'Nothing needs you' : `${o.needCount} need${o.needCount === 1 ? 's' : ''} you`;
  // At most six whole rows of 40 px; the list scrolls for more.
  const list: ListBox = {
    name: 'sessions',
    x: 0,
    y: 36,
    w: W,
    h: listHeight(o.rows.length, 6),
    items: o.rows.map((r) => r.label),
    capture: true,
  };
  return { texts: [head(headLine(`Kit   ${count}`, o.offline ?? '', o.notice))], list };
}

// ---------- one session ----------

export function sessionPages(d: SessionDetail | null, offline = false): string[] {
  if (!d) return [offline ? 'Your Mac is offline. This reply shows when Kit reaches the Mac again.' : 'Loading...'];
  let text = plainReply(d.last_reply || '');
  // A plan waiting for approval is what to read: show the plan itself.
  if (d.pending?.kind === 'plan' && d.pending.text) text = plainReply(d.pending.text);
  if (!text) text = d.status === 'working' ? 'Claude is working. No reply yet.' : 'No reply yet.';
  return paginate(text, TPX, BODY_ROWS);
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
  pages: string[];
  page: number;
  status: string;
  pending: Pending | null;
  notice: string | null;
}): PageSpec {
  const n = o.pages.length;
  const pageMark = n > 1 ? `${o.page + 1}/${n}` : '';
  const tapWord = o.pending ? 'answer' : 'reply';
  const hint = n > 1 ? `Swipe: page   Tap: ${tapWord}   Double tap: back` : `Tap: ${tapWord}   Double tap: back`;
  return {
    texts: [
      head(headLine(clean(o.title), pageMark, o.notice)),
      { name: 'status', x: X, y: 28, w: TW, h: 30, content: o.status, color: 3 },
      { name: 'body', x: X, y: 62, w: TW, h: BODY_ROWS * LINE_H + 2, content: o.pages[o.page] ?? '', capture: true },
      foot(hint),
    ],
  };
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

export function actionsPage(o: { title: string; ask: string[]; items: ActionItem[]; message: string | null; notice: string | null }): PageSpec {
  const askLines = o.message ? [fit(o.message, TPX)] : o.ask;
  const texts: TextBox[] = [head(headLine(clean(o.title), '', o.notice), 3)];
  let y = 32;
  if (askLines.length) {
    texts.push({ name: 'ask', x: X, y: 30, w: TW, h: askLines.length * LINE_H + 2, content: askLines.join('\n'), color: 4 });
    y = 30 + askLines.length * LINE_H + 6;
  }
  return {
    texts,
    list: { name: 'actions', x: 0, y, w: W, h: Math.min(H - y, listHeight(o.items.length, 6)), items: o.items.map((i) => i.label), capture: true },
  };
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
