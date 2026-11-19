// What each screen puts on the lens. Pure functions: state in, page out.
// The lens is 576 x 288, one fixed font, 27 px a line, no colors, only five
// brightness steps. A header line sits on every screen, so a notice can
// show there on any screen without taking the input.
import type { Glance, Pending, SessionDetail, SessionRow, Status, Turn } from './api';
import type { PageSpec, TextBox } from './glasses';
import { LINE_H, SPACE_W, fit, padTo, paginate, plainReply, spread, width, wrapLines } from './text';

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
    // The card's few words ("sign + pay 50%"), else the status in words.
    const phrase = clean(s.glance?.phrase || '');
    const words = ` · ${phrase ? fit(phrase, Math.round(ROW_PX * 0.55)) : statusWords(s)}`;
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

// ---------- earlier turns ----------
// Above the latest turn, one turn at a time, the newest first: a swipe up
// at the top of a turn shows the turn before it, from its top, so its prompt
// is the first thing to read; a swipe down at the end of a turn shows the
// next one, and after the newest earlier turn, the latest turn again. The
// layout is the session screen's (head, one line, the reply's pages, hint),
// so moving between them is an in-place update.

export const EARLIER = '▲ earlier';

/** The pages of an earlier turn's reply; one page that says so while it loads. */
export function turnPages(t: Turn | null): string[] {
  if (!t) return ['Loading earlier turns...'];
  const text = plainReply(t.reply_text || '');
  return paginate(text || 'No reply text in this turn. Claude only used tools.', TPX, BODY_ROWS);
}

/** Who started the turn and what they said, in one line: "You: ...". */
export function promptLine(t: Turn | null): string {
  if (!t) return '';
  const words = clean(t.user_text || '');
  if (t.from === 'claude' || (!words && t.from !== 'you')) return 'Claude went on, with no new prompt';
  const who = t.from === 'kit' ? 'Kit' : t.from === 'task' ? 'Task' : 'You';
  return fit(`${who}: ${words || '(no words)'}`, TPX);
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** When a turn started, as the person reads it: 9:12 AM today, Tue 9:12 AM
 *  this week, Nov 3 before that. */
export function when(at: string | number | null | undefined, now = new Date()): string {
  if (at === null || at === undefined || at === '') return '';
  const d = new Date(typeof at === 'number' ? at * 1000 : at);
  if (Number.isNaN(d.getTime())) return '';
  const h = d.getHours() % 12 || 12;
  const time = `${h}:${String(d.getMinutes()).padStart(2, '0')} ${d.getHours() < 12 ? 'AM' : 'PM'}`;
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(now) - day(d)) / 86400000);
  if (days === 0) return time;
  if (days > 0 && days < 7) return `${DAYS[d.getDay()]} ${time}`;
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

export function turnPage(o: {
  /** 1 for the turn just before the latest, `count` for the first turn. */
  k: number;
  count: number;
  turn: Turn | null;
  pages: string[];
  page: number;
  /** What a swipe down at the end of this turn shows: the latest turn, or a later earlier one. */
  next: 'latest' | 'later';
  notice: string | null;
}): PageSpec {
  const n = o.pages.length;
  const at = when(o.turn?.at);
  const title = `Earlier ${o.k} of ${o.count}${at ? ` · ${at}` : ''}`;
  const up = o.page > 0 ? '▲ page' : o.k < o.count ? EARLIER : 'First turn';
  const down = o.page < n - 1 ? '▼ page' : o.next === 'latest' ? '▼ latest' : '▼ later';
  return {
    texts: [
      head(headLine(title, n > 1 ? `${o.page + 1}/${n}` : '', o.notice)),
      { name: 'status', x: X, y: 28, w: TW, h: 30, content: o.turn ? promptLine(o.turn) : '', color: 3 },
      { name: 'body', x: X, y: 62, w: TW, h: BODY_ROWS * LINE_H + 2, content: o.pages[o.page] ?? '', capture: true },
      foot(`${up}   ${down}   Tap: latest`),
    ],
  };
}

// ---------- the glance card ----------
// The first thing on the session screen: the title, one status word in a
// box, then a few short lines with the key fact first, and what you must do.
// The lens has one font size and no bold, so the card reads by its spacing:
// a blank line between lines when they fit, and few words on each.

export const CARD_Y = 48;
const YOU_GAP = 14; // between the lines and You
const YOU_EDGE = 6; // the You box's border and padding
const TAG_PAD = 4;
const TAG_BORDER = 2;
const TAG_W = width('NEEDS YOU') + 2 * (TAG_PAD + TAG_BORDER) + 16;
const BTN_Y = 244;
const BTN_H = 40;
const BTN_GAP = 8;
const BTN_PAD = 4;
/** Buttons on the card at once; more scroll in place. */
export const MAX_BUTTONS = 4;
export const SAY_IT = 'Say it';

export type CardButton = { kind: 'option'; id: string; label: string } | { kind: 'say'; label: string };

const WORD: Record<Status, string> = { needs_you: 'NEEDS YOU', working: 'WORKING', waiting: 'WAITING', idle: 'DONE' };

function firstSentence(text: string): string {
  const t = clean(text);
  const m = t.match(/^(.+?[.!?])(\s|$)/);
  return m ? m[1] : t;
}

/** The card the bridge wrote, or one made here from what is known (an
 *  older bridge, or one that has not written it yet). */
export function cardOf(d: SessionDetail | null, row: SessionRow | null): Glance {
  const g = d?.glance ?? row?.glance;
  if (g && g.lines?.length) return g;
  const s = d ?? row;
  const status: Status = s?.status ?? 'idle';
  const p = d?.pending ?? null;
  const text = p && p.kind !== 'plan' && p.text ? p.text : d?.last_reply || s?.why || s?.status_line || '';
  const line = fit(firstSentence(text), 2 * TPX);
  const you = p ? (p.options.length ? 'pick below' : 'answer below') : status === 'needs_you' ? 'read the reply' : 'nothing now';
  return { status_word: WORD[status], lines: line ? [line] : [], you, options: [] };
}

/** The buttons: the answers of the question that waits, then Say it. None
 *  when nothing waits. Short labels from the card when they are for this
 *  same question. */
export function cardButtons(g: Glance, pending: Pending | null): CardButton[] {
  const opts = pending?.options ?? [];
  if (!opts.length) return [];
  const short = g.options ?? [];
  const same = short.length === opts.length && short.every((o, i) => o.id === opts[i].id && o.label);
  return [...opts.map((o, i) => ({ kind: 'option' as const, id: o.id, label: clean(same ? short[i].label : o.label) })), { kind: 'say', label: SAY_IT }];
}

/** The word in the status box, centered with spaces (the font has no alignment). */
export function tagText(word: string): string {
  const inner = TAG_W - 2 * (TAG_PAD + TAG_BORDER) - 4;
  const w = fit(word, inner);
  const pad = Math.max(0, Math.floor((inner - width(w)) / 2 / SPACE_W));
  return ' '.repeat(pad) + w;
}

/** The card's lines as lens rows: each line wrapped (its words never cut),
 *  a blank row between lines when all fit that way, and, when even tight
 *  they do not fit, the first lines (needs-you asks come first) and "+3
 *  waiting" for the rest. */
export function cardRows(g: Glance, maxRows: number): string[] {
  const lines = (g.lines ?? []).map((l) => clean(l)).filter(Boolean);
  const wrapped = lines.map((l) => wrapLines(l, TPX));
  const total = (n: number, gap: number) => wrapped.slice(0, n).reduce((a, w) => a + w.length, 0) + gap * Math.max(0, n - 1);
  if (total(wrapped.length, 1) <= maxRows) return wrapped.flatMap((w, i) => (i ? ['', ...w] : w));
  if (total(wrapped.length, 0) <= maxRows) return wrapped.flat();
  let n = wrapped.length - 1;
  while (n > 0 && total(n, 0) + 1 > maxRows) n--;
  const rest = (g.states ?? []).slice(n);
  const kind = rest.length && rest.every((s) => s === 'working') ? 'waiting' : rest.length && rest.every((s) => s === 'done') ? 'done' : 'more';
  return [...wrapped.slice(0, n).flat(), `+${wrapped.length - n} ${kind}`];
}

/** The "You:" line: what you must do, or the message of an answer on its way. */
export function youLine(g: Glance, message: string | null): { text: string; bright: boolean } | null {
  if (message) return { text: fit(message, TPX - 2 * YOU_EDGE - 8), bright: true };
  if (!g.you) return null;
  const you = clean(g.you);
  const nothing = /^nothing( now)?\.?$/i.test(you);
  return { text: fit(`You: ${you}`, TPX - 2 * YOU_EDGE - 8), bright: !nothing };
}

/** The "You:" line's box: a border around what you must do (the one
 *  emphasis the lens has), none for "You: nothing now" and when the
 *  answers are buttons under it. */
function youBox(you: { text: string; bright: boolean }, y: number, boxed: boolean): TextBox {
  if (!boxed) return { name: 'you', x: X, y: y + YOU_GAP, w: TW, h: LINE_H + 2, content: you.text, color: you.bright ? 4 : 2 };
  return {
    name: 'you',
    x: X,
    y: y + YOU_GAP - YOU_EDGE + 4,
    w: Math.min(TW, width(you.text) + 2 * YOU_EDGE + 14),
    h: LINE_H + 2 * YOU_EDGE + 1,
    content: you.text,
    border: 2,
    borderColor: 15,
    radius: 6,
    pad: YOU_EDGE - 2,
  };
}

/** The buttons in view: up to MAX_BUTTONS from `first`, each as wide as its
 *  words (all the same width when they scroll, so a swipe never changes the
 *  layout). The chosen one has "▶ " in front. */
export function buttonBoxes(buttons: CardButton[], sel: number, first: number): TextBox[] {
  const shown = buttons.slice(first, first + MAX_BUTTONS);
  const room = TW - BTN_GAP * (shown.length - 1);
  const mark = width('▶ ');
  const inner = (l: string) => mark + width(l) + 2 * (BTN_PAD + 2) + 4;
  let widths = shown.map((b) => inner(b.label));
  if (buttons.length > MAX_BUTTONS) {
    // They scroll: equal widths, so a swipe changes only the words.
    widths = shown.map(() => Math.floor(room / shown.length));
  } else if (widths.reduce((a, b) => a + b, 0) > room) {
    // Too wide: the widest give way first, down to one cap; their words are cut.
    let cap = Math.max(...widths);
    while (cap > 40 && widths.reduce((a, w) => a + Math.min(w, cap), 0) > room) cap--;
    widths = widths.map((w) => Math.min(w, cap));
  }
  let x = X;
  return shown.map((b, i) => {
    const w = widths[i];
    const on = first + i === sel;
    const text = fit(b.label, w - 2 * (BTN_PAD + 2) - mark - 4);
    const box: TextBox = {
      name: `btn${i}`,
      x,
      y: BTN_Y,
      w,
      h: BTN_H,
      content: on ? `▶ ${text}` : `${' '.repeat(Math.round(mark / SPACE_W))}${text}`,
      color: on ? 4 : 3,
      border: 2,
      borderColor: 12,
      radius: 6,
      pad: BTN_PAD,
    };
    x += w + BTN_GAP;
    return box;
  });
}

export function cardPage(o: {
  title: string;
  glance: Glance;
  buttons: CardButton[];
  sel: number;
  first: number;
  message: string | null;
  head: string | null;
  replyPages: number;
  /** Earlier turns are above the card: its hint line starts with "▲ earlier"
   *  (with answer buttons, which take the hint's place, the top line ends with it). */
  earlier?: boolean;
}): PageSpec {
  const hasButtons = o.buttons.length > 0;
  const you = youLine(o.glance, o.message);
  const boxed = !!you && you.bright && !hasButtons;
  const bottom = hasButtons ? BTN_Y - 4 : 254;
  const youH = you ? YOU_GAP + (boxed ? LINE_H + 2 * YOU_EDGE + 1 - YOU_EDGE + 4 : LINE_H + 2) : 0;
  const maxRows = Math.max(1, Math.floor((bottom - CARD_Y - youH) / LINE_H));
  const rows = cardRows(o.glance, maxRows);
  const texts: TextBox[] = [
    head(o.head ? fit(o.head, TW - TAG_W - 12) : o.earlier && hasButtons ? spread(clean(o.title), EARLIER, TW - TAG_W - 24) : fit(clean(o.title), TW - TAG_W - 12)),
    { name: 'tag', x: W - X - TAG_W, y: 2, w: TAG_W, h: LINE_H + 2 * (TAG_PAD + TAG_BORDER) + 1, content: tagText(o.glance.status_word || ''), border: TAG_BORDER, borderColor: 15, radius: 6, pad: TAG_PAD },
    { name: 'lines', x: X, y: CARD_Y, w: TW, h: Math.max(1, rows.length) * LINE_H + 2, content: rows.join('\n'), capture: true },
  ];
  if (you) texts.push(youBox(you, CARD_Y + rows.length * LINE_H, boxed));
  if (hasButtons) texts.push(...buttonBoxes(o.buttons, o.sel, o.first));
  else if (o.replyPages > 0) texts.push(foot(`${o.earlier ? `${EARLIER}   ▼ full reply` : 'Swipe: full reply'}   Tap: reply   Double tap: back`));
  else texts.push(foot(`${o.earlier ? `${EARLIER}   ` : ''}Tap: reply   Double tap: back`));
  // The title sits level with the word in the box, and stops before the box.
  texts[0] = { ...texts[0], y: 8, w: TW - TAG_W - 8 };
  return { texts };
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
