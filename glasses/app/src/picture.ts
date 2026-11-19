// A table as a picture. The lens font is proportional and has no sizes, so
// text columns never line up; a picture has real columns. The app draws the
// table on a canvas (white on black: the glasses show it as green, 16
// steps), cuts it into tiles of at most 288 x 144 (the largest image box the
// glasses take; a page may hold 4 of them), and sends each tile as PNG bytes.
//
// One table page: the header row (dim) and as many rows as fit; a long
// table goes on over more pages, the header on each. A cell takes a second
// line before anything is cut; only then is it cut short at a clause or a
// word, with "…". When the columns do not fit side by side even so, they go
// in groups, each with the first column, one group a page.
import type { ImageBox } from './glasses';

export interface TableData {
  heads: string[];
  rows: string[][];
}

export interface TablePage {
  /** The table's column indices on this page. */
  cols: number[];
  /** The table's row indices on this page. */
  rows: number[];
  widths: number[];
  heads: string[];
  /** Each row's cells, each cell its lines (1 or 2). */
  cells: string[][][];
  /** Each row's height. */
  rowH: number[];
  w: number;
  /** The picture's height: the same on every page of a column group, so a
   *  page turn sends new pictures into the same boxes, with no rebuild. */
  h: number;
}

/** The largest image box the glasses take (Even Hub display docs). */
export const TILE_W = 288;
export const TILE_H = 144;

export const FAMILY = 'system-ui, -apple-system, "Helvetica Neue", Roboto, Arial, sans-serif';
export const BODY_FONT = `21px ${FAMILY}`;
export const BOLD_FONT = `bold 21px ${FAMILY}`;
export const HEAD_FONT = `18px ${FAMILY}`;
const PAD_X = 8;
export const ROW_H = 31; // a row of one line
export const LINE2 = 23; // what a second line adds
export const HEAD_H = 27;
const MIN_COL = 76;
/** A long text column gets at least this; past 2 lines its cells are cut. */
const CUT_FLOOR = 150;
// Colors as they should look on the lens (the canvas is drawn in display
// brightness; lensGray turns it into the gray the lens shows that way):
// the header as dim as the lens's text brightness 2, the lines dimmer.
const TEXT = '#ffffff';
const HEAD = '#c5c5c5';
const LINE = '#9d9d9d';

/** How the lens shows each gray: a gray v shows as level v >> 4, and the
 *  simulator (0.9.5) lights levels 0 to 8 at these brightnesses, 9 to 15 all
 *  at full. Measured in the glance lab (lab.html, its gray screen). */
export const LEVEL_BRIGHTNESS = [0, 96, 131, 157, 179, 197, 214, 230, 244, 255];

/** The gray that shows at brightness `v` (0 to 255): full white stays 255;
 *  a soft text edge stays soft instead of lighting up. */
export function lensGray(v: number): number {
  let best = 0;
  LEVEL_BRIGHTNESS.forEach((b, l) => {
    if (Math.abs(b - v) < Math.abs(LEVEL_BRIGHTNESS[best] - v)) best = l;
  });
  return best === 0 ? 0 : best >= LEVEL_BRIGHTNESS.length - 1 ? 255 : best * 16 + 8;
}
const LENS_GRAY = Uint8Array.from({ length: 256 }, (_, v) => lensGray(v));

export type Measure = (s: string, font: string) => number;

/** True where a canvas can draw (the app's page; not the tests). */
export function canDraw(): boolean {
  return typeof document !== 'undefined' && typeof document.createElement === 'function';
}

let ctx: CanvasRenderingContext2D | null | undefined;
/** Text width on the canvas; outside a browser (the tests), a fair guess. */
export const measure: Measure = (s, font) => {
  if (ctx === undefined) ctx = typeof document !== 'undefined' ? document.createElement('canvas').getContext('2d') : null;
  if (!ctx) return Math.ceil(s.length * (parseInt(font.match(/(\d+)px/)?.[1] || '20', 10) * 0.52));
  ctx.font = font;
  return Math.ceil(ctx.measureText(s).width);
};

/** A status cell that asks for the person: drawn bold, so the eye finds it. */
const needsYou = (s: string) => /^needs you\b/i.test(s);
const fontOf = (s: string) => (needsYou(s) ? BOLD_FONT : BODY_FONT);

/** `s` cut short to fit `px`: at the last clause that fits ("Pick 5,000 m
 *  or 8,000 m…"), else at a word, else at a letter, with "…". */
export function shorten(s: string, px: number, font: string, m: Measure = measure): string {
  s = s.replace(/\s+/g, ' ').trim();
  if (m(s, font) <= px) return s;
  const fits = (t: string) => m(`${t}…`, font) <= px;
  let best = '';
  const clause = /[,;:(]\s|\s[-–—]\s/g;
  for (let k = clause.exec(s); k; k = clause.exec(s)) {
    const head = s.slice(0, k.index).trim();
    if (head.length >= 3 && fits(head)) best = head;
  }
  if (best) return `${best}…`;
  const words = s.split(' ');
  let out = '';
  for (const w of words) {
    const next = out ? `${out} ${w}` : w;
    if (!fits(next)) break;
    out = next;
  }
  if (out) return `${out.replace(/[,;:.]$/, '')}…`;
  let cut = s;
  while (cut.length > 1 && !fits(cut)) cut = cut.slice(0, -1);
  return `${cut}…`;
}

/** Column widths that fill at most `avail`: columns narrower than their
 *  share keep their width, the wide ones share the rest equally. */
export function fitWidths(natural: number[], avail: number): number[] {
  if (natural.reduce((a, b) => a + b, 0) <= avail) return [...natural];
  const out = [...natural];
  const order = natural.map((_, i) => i).sort((a, b) => natural[a] - natural[b]);
  let left = avail;
  let k = order.length;
  for (const i of order) {
    const share = Math.floor(left / k);
    out[i] = Math.min(natural[i], share);
    left -= out[i];
    k--;
  }
  return out;
}

/** `s` in at most 2 lines of `px`, broken at spaces; the second line cut
 *  short when the rest does not fit. */
export function twoLines(s: string, px: number, font: string, m: Measure = measure): string[] {
  s = s.replace(/\s+/g, ' ').trim();
  if (m(s, font) <= px) return [s];
  const words = s.split(' ');
  let first = '';
  let k = 0;
  while (k < words.length && m(first ? `${first} ${words[k]}` : words[k], font) <= px) first = first ? `${first} ${words[k++]}` : words[k++];
  if (!first) return [shorten(s, px, font, m)];
  return [first, shorten(words.slice(k).join(' '), px, font, m)];
}

/** The least width that holds `s` in 2 lines without a cut. */
function twoLineWidth(s: string, font: string, m: Measure): number {
  const words = s.replace(/\s+/g, ' ').trim().split(' ');
  let best = m(words.join(' '), font);
  for (let i = 1; i < words.length; i++) {
    best = Math.min(best, Math.max(m(words.slice(0, i).join(' '), font), m(words.slice(i).join(' '), font)));
  }
  return best;
}

/** Column widths that fill `avail`: each column at least `must` (2 lines),
 *  at most `natural` (1 line), the room shared out to the narrowest first. */
function spreadWidths(must: number[], natural: number[], avail: number): number[] {
  if (natural.reduce((a, b) => a + b, 0) <= avail) return [...natural];
  if (must.reduce((a, b) => a + b, 0) >= avail) return fitWidths(must, avail);
  let lo = 0;
  let hi = Math.max(...natural);
  const at = (cap: number) => must.map((w, j) => Math.max(w, Math.min(natural[j], cap)));
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (at(mid).reduce((a, b) => a + b, 0) <= avail) lo = mid;
    else hi = mid;
  }
  return at(lo);
}

/** Rows over pages of `room` px: as few pages as fit them, the rows spread
 *  evenly over those pages (7 rows at 5 a page go 4 and 3). */
export function splitRows(rowH: number[], room: number): number[][] {
  const greedy = (most: number) => {
    const pages: number[][] = [];
    let cur: number[] = [];
    let h = 0;
    rowH.forEach((rh, r) => {
      if (cur.length && (h + rh > room || cur.length >= most)) {
        pages.push(cur);
        cur = [];
        h = 0;
      }
      cur.push(r);
      h += rh;
    });
    if (cur.length) pages.push(cur);
    return pages;
  };
  const fewest = greedy(Infinity);
  for (let most = Math.ceil(rowH.length / fewest.length); most < rowH.length; most++) {
    const even = greedy(most);
    if (even.length === fewest.length) return even;
  }
  return fewest;
}

/** The table's pages for a picture at most `maxW` by `maxH`. */
export function tablePages(t: TableData, maxW: number, maxH: number, m: Measure = measure): TablePage[] {
  const n = Math.max(t.heads.length, ...t.rows.map((r) => r.length));
  if (!n || !t.rows.length) return [];
  const cell = (r: number, c: number) => (t.rows[r]?.[c] ?? '').replace(/\s+/g, ' ').trim();
  const head = (c: number) => (t.heads[c] ?? '').replace(/\s+/g, ' ').trim();
  const pad = 2 * PAD_X + 1;
  const natural = [...Array(n).keys()].map((c) => Math.max(m(head(c), HEAD_FONT), ...t.rows.map((_, r) => m(cell(r, c), fontOf(cell(r, c))))) + pad);
  // The least width for each column: its cells in 2 lines, with no cut; a
  // long text column, less, when the table is wide (its cells cut after 2 lines).
  const must = [...Array(n).keys()].map((c) =>
    Math.min(natural[c], Math.max(MIN_COL, Math.max(...t.rows.map((_, r) => twoLineWidth(cell(r, c), fontOf(cell(r, c)), m))) + pad)),
  );
  const wide = must.reduce((a, b) => a + b, 0) > maxW - 1;
  const least = wide ? must.map((w) => Math.min(w, CUT_FLOOR)) : must;

  // Column groups, only when even that does not fit: the first column,
  // then the others while they fit.
  const groups: number[][] = [];
  let group = [0];
  let used = least[0];
  for (let c = 1; c < n; c++) {
    if (group.length > 1 && used + least[c] > maxW - 1) {
      groups.push(group);
      group = [0];
      used = least[0];
    }
    group.push(c);
    used += least[c];
  }
  groups.push(group);

  const pages: TablePage[] = [];
  for (const cols of groups) {
    const widths = spreadWidths(cols.map((c) => least[c]), cols.map((c) => natural[c]), maxW - 1);
    const w = widths.reduce((a, b) => a + b, 0) + 1;
    const heads = cols.map((c, j) => shorten(head(c), widths[j] - pad, HEAD_FONT, m));
    const cells = t.rows.map((_, r) => cols.map((c, j) => twoLines(cell(r, c), widths[j] - pad, fontOf(cell(r, c)), m)));
    const rowH = cells.map((row) => ROW_H + (Math.max(...row.map((l) => l.length)) - 1) * LINE2);
    const chunks = splitRows(rowH, maxH - HEAD_H - 1);
    const tallest = Math.max(...chunks.map((ch) => HEAD_H + ch.reduce((a, i) => a + rowH[i], 0) + 1));
    for (const rows of chunks) {
      pages.push({ cols, rows, widths, heads, cells: rows.map((i) => cells[i]), rowH: rows.map((i) => rowH[i]), w, h: tallest });
    }
  }
  return pages;
}

/** Draw a table page, white on black. */
export function drawTable(p: TablePage): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = p.w;
  c.height = p.h;
  const g = c.getContext('2d')!;
  g.fillStyle = '#000';
  g.fillRect(0, 0, p.w, p.h);
  g.textBaseline = 'middle';
  const xs = [0];
  for (const w of p.widths) xs.push(xs[xs.length - 1] + w);

  g.font = HEAD_FONT;
  g.fillStyle = HEAD;
  p.heads.forEach((t, j) => g.fillText(t, xs[j] + PAD_X + 1, HEAD_H / 2 + 1));
  g.fillStyle = TEXT;
  const tops = [HEAD_H];
  for (const h of p.rowH) tops.push(tops[tops.length - 1] + h);
  p.cells.forEach((row, i) => {
    row.forEach((lines, j) => {
      g.font = fontOf(lines[0]);
      lines.forEach((t, k) => g.fillText(t, xs[j] + PAD_X + 1, tops[i] + ROW_H / 2 + 1 + k * LINE2));
    });
  });

  // The lines: a box, a rule under the header and between rows, and one
  // between columns. Whole pixels, so they stay sharp. A last page with
  // fewer rows ends its box under its last row.
  g.fillStyle = LINE;
  const right = p.w - 1;
  const bottom = tops[tops.length - 1];
  g.fillRect(0, 0, p.w, 1);
  for (const y of tops) g.fillRect(0, y, p.w, 1);
  for (const x of xs) g.fillRect(Math.min(x, right), 0, 1, bottom + 1);
  return c;
}

/** Tiles of at most 288 x 144 that cover a w x h picture, as even as can be. */
export function tiles(w: number, h: number): { x: number; y: number; w: number; h: number }[] {
  const nx = Math.ceil(w / TILE_W);
  const ny = Math.ceil(h / TILE_H);
  const out: { x: number; y: number; w: number; h: number }[] = [];
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const x0 = Math.round((i * w) / nx);
      const y0 = Math.round((j * h) / ny);
      out.push({ x: x0, y: y0, w: Math.round(((i + 1) * w) / nx) - x0, h: Math.round(((j + 1) * h) / ny) - y0 });
    }
  }
  return out;
}

/** A short, stable name for what a picture shows. */
export function hash(s: string): string {
  let a = 5381;
  let b = 52711;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    a = (a * 33) ^ c;
    b = (b * 31) ^ c;
  }
  return (a >>> 0).toString(36) + (b >>> 0).toString(36);
}

const cache = new Map<string, Promise<Uint8Array>>();

/** One tile of a canvas as PNG bytes; the last 40 are kept. */
function tilePng(key: string, draw: () => HTMLCanvasElement, t: { x: number; y: number; w: number; h: number }): Promise<Uint8Array> {
  let p = cache.get(key);
  if (!p) {
    p = new Promise<Uint8Array>((resolve, reject) => {
      const src = draw();
      const c = document.createElement('canvas');
      c.width = t.w;
      c.height = t.h;
      const g = c.getContext('2d')!;
      g.drawImage(src, -t.x, -t.y);
      const px = g.getImageData(0, 0, t.w, t.h);
      for (let i = 0; i < px.data.length; i += 4) {
        const v = LENS_GRAY[Math.round(0.299 * px.data[i] + 0.587 * px.data[i + 1] + 0.114 * px.data[i + 2])];
        px.data[i] = px.data[i + 1] = px.data[i + 2] = v;
        px.data[i + 3] = 255;
      }
      g.putImageData(px, 0, 0);
      c.toBlob((b) => (b ? b.arrayBuffer().then((a) => resolve(new Uint8Array(a)), reject) : reject(new Error('no PNG'))), 'image/png');
    });
    p.catch(() => cache.delete(key));
    cache.set(key, p);
    while (cache.size > 40) cache.delete(cache.keys().next().value!);
  }
  return p;
}

/** Image boxes for a picture at (x, y): one per tile, each drawn only when sent. */
export function pictureBoxes(id: string, w: number, h: number, x: number, y: number, draw: () => HTMLCanvasElement): ImageBox[] {
  let canvas: HTMLCanvasElement | null = null;
  const once = () => (canvas ??= draw());
  return tiles(w, h).map((t, i) => {
    const key = `${id}.${i}.${t.w}x${t.h}`;
    return { name: `pic${i}`, x: x + t.x, y: y + t.y, w: t.w, h: t.h, key, data: () => tilePng(key, once, t) };
  });
}

/** Image boxes for a table page at (x, y). */
export function tableBoxes(p: TablePage, x: number, y: number): ImageBox[] {
  return pictureBoxes(hash(JSON.stringify([p.heads, p.cells, p.widths])), p.w, p.h, x, y, () => drawTable(p));
}
