// The glance card as a picture. The lens font has one size and no bold, so a
// card in lens text reads by its spacing only. A picture can have a big bold
// title (34 px), large lines (24 px) and bold for what needs you. The side by
// side test (docs/pictures-vs-text.png, last row) read far better this way.
//
// The picture holds the title (or a notice in its place), the status word in
// a box, the card's lines and the "You:" line. The answer buttons and the
// hint line stay lens text under it (screens.ts, cardPage), so a swipe
// changes only their words, with no picture sent again.
//
// Pure layout here (text widths from `measure`, so the tests can run without
// a canvas); drawing happens only when a tile is sent (glasses.ts).
import type { ImageBox } from './glasses';
import { FAMILY, type Measure, hash, measure, pictureBoxes, shorten, tiles } from './picture';

export const TITLE_FONT = `bold 34px ${FAMILY}`;
/** A title too long for 34 px steps down to these before it is cut. */
const TITLE_SIZES = [34, 32, 30, 28];
export const NOTICE_FONT = `bold 24px ${FAMILY}`;
export const WORD_FONT = `bold 20px ${FAMILY}`;
export const LINE_FONT = `24px ${FAMILY}`;
export const BOLD_FONT = `bold 24px ${FAMILY}`;
const SMALL_FONT = `20px ${FAMILY}`;

/** Colors as they should look on the lens (picture.ts, lensGray, turns them
 *  into the gray the lens shows at that brightness). */
const WHITE = '#ffffff';
const SOFT = '#c5c5c5'; // "▲ earlier", "+2 waiting": a step under full
const DIM = '#9d9d9d'; // "You: nothing now", asks that are done

/** The first row's top, under the title. */
export const TOP = 50;
/** A row of 24 px text. */
export const ROW = 30;
/** Between two lines of the card, when all fit with it. */
const GAP = 12;
/** Between two lines when they do not all fit with GAP. */
const TIGHT = 4;
const YOU_GAP = 12;
const YOU_PAD = 8;
const YOU_H = 38; // the You box: a 24 px line, its padding and border
const WORD_PAD = 10;
const WORD_H = 32;

export type CardEl =
  | { t: 'text'; s: string; font: string; color: string; x: number; y: number; w: number; size: number }
  | { t: 'box'; x: number; y: number; w: number; h: number; color: string };

export interface CardPicture {
  w: number;
  h: number;
  els: CardEl[];
  /** How many of the card's lines show (the rest are counted, "+2 waiting"). */
  shown: number;
}

export interface CardInput {
  /** The title, or a notice in its place (`notice` true): smaller, so more of it fits. */
  title: string;
  notice: boolean;
  word: string;
  /** "▲ earlier" beside the status word (a card with buttons, which take the hint line's place). */
  earlier: boolean;
  lines: string[];
  /** Each line's state from a status table: needs (bold), done or dropped (dim). */
  states?: string[];
  you: { text: string; bright: boolean; boxed: boolean } | null;
  /** The picture's width, and the lowest it may reach (the buttons or the hint line are under it). */
  w: number;
  bottom: number;
}

/** `s` in lines of at most `px`, broken at spaces; a word longer than a line is cut. */
export function wrap(s: string, px: number, font: string, m: Measure = measure): string[] {
  const words = s.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean);
  const out: string[] = [];
  let cur = '';
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (m(next, font) <= px) {
      cur = next;
      continue;
    }
    if (cur) out.push(cur);
    cur = m(w, font) <= px ? w : shorten(w, px, font, m);
  }
  if (cur) out.push(cur);
  return out;
}

/** What the asks that do not fit are: all waiting, all done, else more. */
export function restWord(states: string[]): string {
  if (states.length && states.every((s) => s === 'working')) return 'waiting';
  if (states.length && states.every((s) => s === 'done')) return 'done';
  return 'more';
}

function lineStyle(state: string | undefined): { font: string; color: string } {
  if (state === 'needs') return { font: BOLD_FONT, color: WHITE };
  if (state === 'done' || state === 'dropped') return { font: LINE_FONT, color: DIM };
  return { font: LINE_FONT, color: WHITE };
}

const sizeOf = (font: string) => Number(font.match(/(\d+)px/)?.[1] || 24);

/** Where everything on the card goes. */
export function cardPicture(o: CardInput, m: Measure = measure): CardPicture {
  const els: CardEl[] = [];
  const text = (s: string, font: string, color: string, x: number, y: number) =>
    els.push({ t: 'text', s, font, color, x, y, w: m(s, font), size: sizeOf(font) });

  // The status word in a box, at the right; the title to its left.
  const word = o.word.trim();
  let left = o.w;
  if (word) {
    const ww = m(word, WORD_FONT) + 2 * WORD_PAD;
    els.push({ t: 'box', x: o.w - ww, y: 4, w: ww, h: WORD_H, color: WHITE });
    text(word, WORD_FONT, WHITE, o.w - ww + WORD_PAD, 27);
    left = o.w - ww - 12;
  }
  if (o.earlier) {
    const e = '▲ earlier';
    const ew = m(e, SMALL_FONT);
    text(e, SMALL_FONT, SOFT, left - ew, 27);
    left -= ew + 14;
  }
  if (o.notice) text(shorten(o.title, left, NOTICE_FONT, m), NOTICE_FONT, WHITE, 0, 30);
  else {
    const title = o.title || 'Session';
    const font = TITLE_SIZES.map((px) => `bold ${px}px ${FAMILY}`).find((f) => m(title, f) <= left) ?? `bold ${TITLE_SIZES[TITLE_SIZES.length - 1]}px ${FAMILY}`;
    text(shorten(title, left, font, m), font, WHITE, 0, 35);
  }

  // The lines: a gap between them when all fit that way, else tight, else
  // the first ones and a count of the rest ("+2 waiting").
  const youH = o.you ? YOU_GAP + (o.you.boxed ? YOU_H : ROW) : 0;
  const room = o.bottom - TOP - youH;
  const lines = o.lines.map((l) => l.trim()).filter(Boolean);
  const wrapped = lines.map((l, i) => wrap(l, o.w, lineStyle(o.states?.[i]).font, m));
  const total = (n: number, gap: number) => wrapped.slice(0, n).reduce((a, w) => a + w.length * ROW, 0) + gap * Math.max(0, n - 1);
  let gap = GAP;
  let n = wrapped.length;
  let rest = '';
  if (total(n, GAP) > room) gap = TIGHT;
  if (total(n, TIGHT) > room) {
    if (n > 1) {
      n--;
      while (n > 1 && total(n, TIGHT) + TIGHT + ROW > room) n--;
      rest = `+${wrapped.length - n} ${restWord((o.states ?? []).slice(n))}`;
    }
    // A first line too long by itself: as many of its rows as fit.
    const rows = Math.max(1, Math.floor((room - (rest ? TIGHT + ROW : 0)) / ROW));
    if (n === 1 && wrapped[0].length > rows) {
      wrapped[0] = wrapped[0].slice(0, rows);
      wrapped[0][rows - 1] = shorten(`${wrapped[0][rows - 1]} …`, o.w, lineStyle(o.states?.[0]).font, m);
    }
  }
  let y = TOP;
  wrapped.slice(0, n).forEach((rows, i) => {
    const st = lineStyle(o.states?.[i]);
    for (const r of rows) {
      text(r, st.font, st.color, 0, y + 23);
      y += ROW;
    }
    y += gap;
  });
  if (rest) {
    text(rest, LINE_FONT, SOFT, 0, y + 23);
    y += ROW + gap;
  }
  y -= gap;

  // What you must do: bold, in a box; "You: nothing now" dim, with none.
  if (o.you) {
    y += YOU_GAP;
    const font = o.you.bright ? BOLD_FONT : LINE_FONT;
    if (o.you.boxed) {
      const s = shorten(o.you.text, o.w - 2 * YOU_PAD - 4, font, m);
      els.push({ t: 'box', x: 0, y, w: Math.min(o.w, m(s, font) + 2 * YOU_PAD + 4), h: YOU_H, color: WHITE });
      text(s, font, WHITE, YOU_PAD + 2, y + 27);
      y += YOU_H;
    } else {
      text(shorten(o.you.text, o.w, font, m), font, o.you.bright ? WHITE : DIM, 0, y + 23);
      y += ROW;
    }
  }
  // Only as tall as what it shows: fewer pixels go to the glasses.
  const h = Math.max(WORD_H + 8, Math.min(o.bottom, y + 6));
  return { w: o.w, h, els, shown: n };
}

/** Draw the card, white on black. */
export function drawCard(p: CardPicture): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = p.w;
  c.height = p.h;
  const g = c.getContext('2d')!;
  g.fillStyle = '#000';
  g.fillRect(0, 0, p.w, p.h);
  g.textBaseline = 'alphabetic';
  for (const e of p.els) {
    if (e.t === 'box') {
      g.strokeStyle = e.color;
      g.lineWidth = 2;
      g.beginPath();
      g.roundRect(e.x + 1, e.y + 1, e.w - 2, e.h - 2, 6);
      g.stroke();
    } else {
      g.font = e.font;
      g.fillStyle = e.color;
      g.fillText(e.s, e.x, e.y);
    }
  }
  return c;
}

/** What a tile shows: the parts of the card that reach into it. A tile is
 *  sent again only when this changes, so a notice in the title's place
 *  sends only the top tiles. An empty tile is '' (glasses.ts: a new page
 *  shows its image boxes empty, so it is not sent). */
export function tileKeys(p: CardPicture): string[] {
  return tiles(p.w, p.h).map((t) => {
    const inside = p.els.filter((e) => {
      const [x0, x1, y0, y1] = e.t === 'box' ? [e.x - 2, e.x + e.w + 2, e.y - 2, e.y + e.h + 2] : [e.x - 2, e.x + e.w + 4, e.y - e.size, e.y + e.size * 0.35];
      return x1 > t.x && x0 < t.x + t.w && y1 > t.y && y0 < t.y + t.h;
    });
    return inside.length ? hash(JSON.stringify([t, inside])) : '';
  });
}

/** Image boxes for the card at (x, y), marked as the card's, so the app
 *  can tell when card pictures fail or come slowly (controller.ts). */
export function cardBoxes(p: CardPicture, x: number, y: number): ImageBox[] {
  const keys = tileKeys(p);
  return pictureBoxes(`card${hash(JSON.stringify(p.els))}`, p.w, p.h, x, y, () => drawCard(p)).map((b, i) => ({
    ...b,
    key: keys[i] && `card.${i}.${keys[i]}`,
    group: 'card',
  }));
}
