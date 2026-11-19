// Text for the lens: what fits, what the firmware font can draw, and the
// byte limits of each container. Every width comes from @evenrealities/pretext,
// which measures with the glasses' own font tables, never from a guess.
import { getTextWidth, measureTextWrap, pxTruncate } from '@evenrealities/pretext';

/** One line of text on the lens, in pixels (fixed by the firmware). */
export const LINE_H = 27;
/** Width of one space in the firmware font, used to pad columns. */
export const SPACE_W = getTextWidth(' ') || 5;
/** The simulator refuses a text container over 999 bytes; the glasses take
 *  1000 on a rebuild. One cap for both keeps the two the same. */
export const TEXT_BYTES = 990;

const enc = new TextEncoder();
export const byteLength = (s: string) => enc.encode(s).length;

export const width = (s: string) => getTextWidth(s);

/** Cut to a pixel width, ending in "..." when cut. One line only. */
export function fit(s: string, px: number): string {
  if (px <= 0) return '';
  return getTextWidth(s) <= px ? s : pxTruncate(s, px);
}

/** Cut to a byte budget at a whole character, ending in "..." when cut. */
export function clampBytes(s: string, max: number): string {
  if (byteLength(s) <= max) return s;
  const chars = Array.from(s);
  let out = '';
  let used = 0;
  for (const c of chars) {
    const b = byteLength(c);
    if (used + b > max - 3) break;
    out += c;
    used += b;
  }
  return out.trimEnd() + '...';
}

// The firmware font has ASCII, Latin-1, arrows, box drawing, blocks and a
// few shapes; anything else is dropped without a trace (even-g2-notes,
// display.md). Swap the usual typography for what it can draw.
const SWAPS: Record<string, string> = {
  '…': '...', // ellipsis is not in the font
  '—': ' - ',
  '–': '-',
  '‘': "'",
  '’': "'",
  '“': '"',
  '”': '"',
  '•': '-', // bullet
  '‣': '-',
  '⁃': '-',
  '✓': 'yes',
  '✔': 'yes',
  '✗': 'no',
  '✘': 'no',
  ' ': ' ',
  '\t': '  ',
};

/** Make any text safe for the lens font. */
export function glyphSafe(s: string): string {
  let out = '';
  let dropSpace = false; // the space after an emoji that started a line or a word
  for (const c of s.replace(/\r/g, '')) {
    if (SWAPS[c] !== undefined) {
      out += SWAPS[c];
      dropSpace = false;
      continue;
    }
    // Emoji and pictographs: the font has none. "✅ Done" is "Done", not
    // " Done", which would read as an indented line.
    if (/\p{Extended_Pictographic}/u.test(c) && c.codePointAt(0)! > 0x2700) {
      dropSpace = out === '' || /\s$/.test(out);
      continue;
    }
    if (c === '️' || c === '‍') continue;
    if (dropSpace && c === ' ') {
      dropSpace = false;
      continue;
    }
    dropSpace = false;
    out += c;
  }
  return out;
}

/** A reply as plain words: no Markdown marks, links as their words. */
export function plainReply(md: string): string {
  let s = md.replace(/\r/g, '');
  s = s.replace(/^```.*$/gm, ''); // code fences
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1'); // images
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1'); // links
  s = s.replace(/^#{1,6}\s+/gm, ''); // headings
  s = s.replace(/(\*\*|__)(.+?)\1/g, '$2'); // bold
  s = s.replace(/(^|[\s(])[*_]([^*_\n]+)[*_](?=[\s).,;:!?]|$)/g, '$1$2'); // italic
  s = s.replace(/`([^`]+)`/g, '$1'); // inline code
  s = s.replace(/^([ \t]*)[-*+][ \t]+/gm, '$1- '); // bullets, nested ones kept in
  s = s.replace(/^[ \t]*>[ \t]?/gm, ''); // quotes
  s = s.replace(/^[ \t]*\|?[ \t]*:?-{3,}.*$/gm, ''); // table rules
  s = s.replace(/[ \t]+$/gm, '');
  s = s.replace(/\n{3,}/g, '\n\n');
  return glyphSafe(s.trim());
}

/** Break text into lens lines no wider than `px`, the way LVGL wraps:
 *  at spaces, and inside a word only when the word alone is too wide. */
export function wrapLines(text: string, px: number): string[] {
  return wrapParas(text, px).flat();
}

/** The lens lines of each line of `text`. A line keeps its indent, and its
 *  wrapped lines hang under its words: a card's "  Needs you: ..." stays
 *  in under its title, and a list item's words under the item's first word. */
function wrapParas(text: string, px: number): string[][] {
  return text.split('\n').map((para) => {
    if (para.trim() === '') return [''];
    let lead = para.match(/^ */)![0];
    const body = para.slice(lead.length);
    const mark = body.match(/^(- |\d{1,3}[.)] )/)?.[0] ?? '';
    let hang = lead + ' '.repeat(Math.round(width(mark) / SPACE_W));
    if (width(hang) > px / 3) hang = lead.length && width(lead) <= px / 3 ? lead : '';
    if (width(lead) > px / 3) lead = '';
    const lines: string[] = [];
    let pre = lead; // the indent of the line being built
    let cur = ''; // its words
    const push = () => {
      lines.push(pre + cur);
      pre = hang;
      cur = '';
    };
    for (const word of body.split(/ +/)) {
      if (!word) continue;
      const next = cur ? `${cur} ${word}` : word;
      if (width(pre + next) <= px) {
        cur = next;
        continue;
      }
      if (cur) push();
      // A word wider than the line: cut it into pieces that fit.
      let rest = word;
      while (width(pre + rest) > px && Array.from(rest).length > 1) {
        const chars = Array.from(rest);
        let cut = chars.length - 1;
        while (cut > 1 && width(pre + chars.slice(0, cut).join('')) > px) cut--;
        cur = chars.slice(0, cut).join('');
        push();
        rest = chars.slice(cut).join('');
      }
      cur = rest;
    }
    lines.push(pre + cur);
    return lines;
  });
}

/** Split text into pages of at most `rows` lens lines, each `px` wide.
 *  Each page carries its own line breaks, so the lens never wraps it again
 *  and a page never overflows (an overflowing page would scroll inside
 *  itself and swallow the swipe).
 *
 *  Cards (a line, then lines indented under it, as the bridge makes of a
 *  table row): a card's title never ends a page without its first indented
 *  line, and the blank line before a card goes when only it keeps the card
 *  off this page. */
export function paginate(text: string, px: number, rows: number): string[] {
  const paras = wrapParas(text, px).map((lines) => ({ lines, blank: lines[0] === '', indented: lines[0].startsWith(' ') }));
  const isTitle = (i: number) => !!paras[i] && !paras[i].blank && !paras[i].indented && !!paras[i + 1] && !paras[i + 1].blank && paras[i + 1].indented;
  const cardRows = (i: number) => {
    if (!isTitle(i)) return 0;
    let n = paras[i].lines.length;
    for (let j = i + 1; paras[j] && !paras[j].blank && paras[j].indented; j++) n += paras[j].lines.length;
    return n;
  };
  const pages: string[] = [];
  let page: string[] = [];
  const flush = () => {
    while (page.length && page[page.length - 1] === '') page.pop();
    if (page.length) pages.push(page.join('\n'));
    page = [];
  };
  const add = (line: string) => {
    if (page.length === 0 && line === '') return; // no blank first line
    page.push(line);
    if (page.length === rows) flush();
  };
  paras.forEach((p, i) => {
    if (p.blank) {
      const card = cardRows(i + 1);
      if (card && page.length && page.length + 1 + card > rows && page.length + card <= rows) return;
      add('');
      return;
    }
    if (isTitle(i)) {
      const need = p.lines.length + 1;
      if (page.length && page.length + need > rows && need <= rows) flush();
    }
    p.lines.forEach(add);
  });
  flush();
  // Guard against a measuring mismatch and the byte cap.
  return (pages.length ? pages : ['']).map((p) => {
    let out = p;
    while (out && (measureTextWrap(out, px).lineCount > rows || byteLength(out) > TEXT_BYTES)) {
      out = out.slice(0, out.lastIndexOf('\n') > 0 ? out.lastIndexOf('\n') : out.length - 10);
    }
    return out;
  });
}

/** `left` at the start of a line and `right` ending near `px`, padded with
 *  spaces (the font has no alignment). `left` is cut to make room. */
export function spread(left: string, right: string, px: number): string {
  if (!right) return fit(left, px);
  const rw = getTextWidth(right);
  const l = fit(left, px - rw - SPACE_W * 2);
  const gap = Math.max(2, Math.floor((px - getTextWidth(l) - rw) / SPACE_W));
  return l + ' '.repeat(gap) + right;
}

/** Pad `s` with spaces to at least `px` wide. */
export function padTo(s: string, px: number): string {
  const n = Math.max(1, Math.ceil((px - getTextWidth(s)) / SPACE_W));
  return s + ' '.repeat(n);
}

/** Lines of text that `s` takes at width `px`. */
export function lineCount(s: string, px: number): number {
  return measureTextWrap(s, px).lineCount;
}
