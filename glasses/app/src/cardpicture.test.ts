import { describe, expect, it } from 'vitest';
import type { Glance } from './api';
import { BOLD_FONT, type CardEl, type CardInput, LINE_FONT, TITLE_FONT, cardBoxes, cardPicture, tileKeys, wrap } from './cardpicture';
import { cardPage } from './screens';

// The glance card as a picture, with made-up press jobs and supplier quotes.
// Widths from a stand-in measure: px size x 0.5 a letter (bold x 0.55).
const m = (s: string, font: string) => Math.ceil(s.length * Number(font.match(/(\d+)px/)?.[1] || 20) * (font.startsWith('bold') ? 0.55 : 0.5));

const base: CardInput = {
  title: 'Harbor Film quote',
  notice: false,
  word: 'NEEDS YOU',
  earlier: false,
  lines: ['Harbor Film: $4,820 for 10', 'Lead: 3 wk after deposit', 'Up 18% vs 2023 price'],
  you: { text: 'You: sign + pay $2,410', bright: true, boxed: true },
  w: 560,
  bottom: 254,
};
const texts = (els: CardEl[]) => els.filter((e): e is Extract<CardEl, { t: 'text' }> => e.t === 'text');

describe('the glance card as a picture', () => {
  it('has a big bold title, the status word in a box at the right, the lines, and You in a box', () => {
    const p = cardPicture(base, m);
    const t = texts(p.els);
    expect(t[0]).toMatchObject({ s: 'NEEDS YOU' });
    expect(t[1]).toMatchObject({ s: 'Harbor Film quote', font: TITLE_FONT });
    expect(t.slice(2, 5).map((e) => [e.s, e.font])).toEqual(base.lines.map((l) => [l, LINE_FONT]));
    expect(t[5]).toMatchObject({ s: 'You: sign + pay $2,410', font: BOLD_FONT });
    const boxes = p.els.filter((e) => e.t === 'box');
    expect(boxes).toHaveLength(2); // the status word and You
    expect(boxes[0].x + boxes[0].w).toBe(560);
    // A gap between the lines, and only as tall as what it shows.
    expect(t[3].y - t[2].y).toBeGreaterThan(30);
    expect(p.h).toBeLessThan(254);
    expect(p.shown).toBe(3);
  });

  it('steps a long title down in size before it cuts it, and makes room for "▲ earlier"', () => {
    const p = cardPicture({ ...base, title: 'Press 3 nozzle report', earlier: true }, m);
    const t = texts(p.els);
    expect(t.find((e) => e.s === '▲ earlier')).toBeTruthy();
    const title = t.find((e) => e.y === 35)!;
    expect(title.s).toBe('Press 3 nozzle report');
    expect(title.font).not.toBe(TITLE_FONT);
    const cut = texts(cardPicture({ ...base, title: 'The Press 3 nozzle report for both night shifts', earlier: true }, m).els).find((e) => e.y === 35)!;
    expect(cut.s.endsWith('…')).toBe(true);
  });

  it('a notice takes the title\'s place, smaller', () => {
    const t = texts(cardPicture({ ...base, title: '! Laminate quote needs you', notice: true }, m).els);
    expect(t.find((e) => e.s === '! Laminate quote needs you')?.font).toBe(BOLD_FONT);
  });

  it('a status table: asks that need you bold, done ones dim, and the rest counted when they do not fit', () => {
    const asks: CardInput = {
      ...base,
      title: "Today's open asks",
      lines: ['! Job 4490 proof: pick a day + time', '! Head 2 order: pick 1 or 2 heads', 'Laminate: wait New Star, Mon 11/30', 'Ink order: wait Harbor, Tue', 'Belts: wait supplier', 'Die quote: wait Harbor Dies', 'Rewinder 2 belts: done'],
      states: ['needs', 'needs', 'working', 'working', 'working', 'working', 'done'],
      you: null,
    };
    const p = cardPicture(asks, m);
    const t = texts(p.els);
    expect(t.find((e) => e.s.startsWith('! Job 4490'))?.font).toBe(BOLD_FONT);
    expect(t.find((e) => e.s.startsWith('Laminate'))?.font).toBe(LINE_FONT);
    expect(p.shown).toBeLessThan(7);
    expect(t[t.length - 1].s).toBe(`+${7 - p.shown} more`);
    expect(p.h).toBeLessThanOrEqual(254);
    // All of them working: "+N waiting".
    const working = cardPicture({ ...asks, states: asks.states!.map((s, i) => (i < 2 ? s : 'working')) }, m);
    expect(texts(working.els).pop()?.s).toMatch(/^\+\d waiting$/);
  });

  it('wraps a long line at its words, never in a word', () => {
    expect(wrap('Send the fit check to the shift lead after step 2 is done', 200, LINE_FONT, m)).toEqual(['Send the fit', 'check to the', 'shift lead after', 'step 2 is done']);
  });

  it('sends only the tiles that change: a notice changes the top ones; an empty tile is never sent', () => {
    const a = tileKeys(cardPicture(base, m));
    const b = tileKeys(cardPicture({ ...base, title: '! Rewinder 2 needs you', notice: true }, m));
    expect(a).toHaveLength(4);
    expect(b[0]).not.toBe(a[0]);
    expect(b[2]).toBe(a[2]); // the lower left: lines and You
    // Short lines: nothing reaches the lower right tile.
    const short = tileKeys(cardPicture({ ...base, lines: ['Die: 3 x 2 in', 'Corners: 0.125 in', 'Saved: shared drive'], you: null }, m));
    expect(short).toHaveLength(4);
    expect(short[3]).toBe('');
  });

  it('the page: an empty text box under the picture takes the input; buttons and the hint stay lens text', () => {
    const glance: Glance = { status_word: 'NEEDS YOU', lines: ['Heads 2, 4: nozzles still out'], you: 'pick next step', options: [] };
    const page = cardPage({
      title: 'Press 3 nozzle report',
      glance,
      buttons: [
        { kind: 'option', id: 'purge', label: 'Second purge' },
        { kind: 'say', label: 'Say it' },
      ],
      sel: 0,
      first: 0,
      message: null,
      head: null,
      replyPages: 2,
      earlier: true,
      picture: true,
    });
    expect(page.texts.map((t) => t.name)).toEqual(['card', 'btn0', 'btn1']);
    expect(page.texts[0]).toMatchObject({ capture: true, content: ' ' });
    expect(page.images!.length).toBeGreaterThan(0);
    expect(page.images!.length).toBeLessThanOrEqual(4);
    expect(page.images!.every((im) => im.group === 'card' && im.w <= 288 && im.h <= 144)).toBe(true);
    const noButtons = cardPage({ title: 'Harbor Film quote', glance, buttons: [], sel: 0, first: 0, message: null, head: null, replyPages: 2, earlier: true, picture: true });
    expect(noButtons.texts.map((t) => t.name)).toEqual(['card', 'foot']);
    expect(noButtons.texts[1].content).toContain('▲ earlier');
    expect(cardBoxes(cardPicture(base, m), 8, 0).every((b) => b.x >= 8)).toBe(true);
  });
});
