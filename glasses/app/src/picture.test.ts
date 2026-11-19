import { describe, expect, it } from 'vitest';
import type { SessionDetail } from './api';
import { HEAD_H, LINE2, ROW_H, TILE_H, TILE_W, fitWidths, lensGray, shorten, splitRows, tablePages, tiles, twoLines } from './picture';
import { sessionPage, sessionPages } from './screens';

// 10 px a letter: easy to reason about.
const m = (s: string) => s.length * 10;

describe('table pictures', () => {
  it('cuts a long cell at a clause, then at a word', () => {
    const s = 'Pick 5,000 m or 8,000 m, and I make the order draft.';
    expect(shorten(s, 600, '', m)).toBe(s);
    expect(shorten(s, 250, '', m)).toBe('Pick 5,000 m or 8,000 m…');
    expect(shorten(s, 120, '', m)).toBe('Pick 5,000…');
    expect(shorten('Laminate', 50, '', m)).toBe('Lami…');
  });

  it('takes a second line before it cuts', () => {
    expect(twoLines('Same belt as on the machine', 300, '', m)).toEqual(['Same belt as on the machine']);
    expect(twoLines('Same belt as on the machine', 150, '', m)).toEqual(['Same belt as on', 'the machine']);
    expect(twoLines('Made to order, minimum of 4 belts, so the order is $124.80', 150, '', m)).toEqual(['Made to order,', 'minimum of 4…']);
  });

  it('splits rows evenly by height', () => {
    expect(splitRows([31, 31, 31, 31, 31, 31, 31], 160)).toEqual([[0, 1, 2, 3], [4, 5, 6]]);
    expect(splitRows([54, 54, 31], 120)).toEqual([[0, 1], [2]]);
  });

  it('keeps a supplier quote whole: 2 lines a cell, then column groups', () => {
    const q = {
      heads: ['Supplier', 'Belt', 'Price', 'Ships', 'Notes'],
      rows: [
        ['Belt Supply Co.', 'HTD 8M-1200-30', '$38.50 each', '2 days', 'Same belt as the one on the machine, from stock'],
        ['Harbor Power Transmission', 'HTD 8M-1200-30', '$31.20 each', '3 weeks', 'Made to order, minimum of 4 belts'],
      ],
    };
    const pages = tablePages(q, 560, 194, m);
    const shown = pages.flatMap((p) => p.cells.flat(2)).join(' ');
    expect(pages.every((p) => p.cols[0] === 0 && p.w <= 560)).toBe(true);
    for (const c of ['Belt Supply Co.', '$38.50 each', '3 weeks', 'HTD 8M-1200-30']) expect(shown).toContain(c);
    expect(pages[0].rowH.every((h) => h === ROW_H || h === ROW_H + LINE2)).toBe(true);
  });

  it('keeps a status table in one group, its long column cut after 2 lines', () => {
    const asks = {
      heads: ['Ask', 'Status', 'Need from you'],
      rows: [
        ['Laminate quote from New Star Labels', 'Needs you', 'Pick 5,000 m or 8,000 m, and I make the order draft.'],
        ['Job 4490 proof for the customer', 'Needs you', 'Tell me a day and time for the press check, and I make a reply draft.'],
      ],
    };
    const pages = tablePages(asks, 560, 164, m);
    expect(pages.every((p) => p.cols.length === 3)).toBe(true);
    expect(pages.flatMap((p) => p.cells).every((row) => row.every((lines) => lines.length <= 2))).toBe(true);
  });

  it('turns brightness into the gray the lens shows that way', () => {
    expect(lensGray(0)).toBe(0);
    expect(lensGray(255)).toBe(255);
    expect(lensGray(197) >> 4).toBe(5); // as dim as the lens's text brightness 2
    expect(lensGray(128) >> 4).toBe(2); // a soft edge stays soft
  });

  it('gives narrow columns their width and shares the rest', () => {
    expect(fitWidths([100, 50], 400)).toEqual([100, 50]);
    expect(fitWidths([60, 400, 300], 400)).toEqual([60, 170, 170]);
  });

  it('splits rows evenly over pages, the header on each', () => {
    const rows = [...Array(7).keys()].map((i) => [`D-10${i}`, `${i} x 2 in`]);
    const pages = tablePages({ heads: ['Die', 'Size'], rows }, 560, 194, m);
    expect(pages.map((p) => p.rows.length)).toEqual([4, 3]);
    expect(pages[1].heads).toEqual(['Die', 'Size']);
    expect(pages.map((p) => p.h)).toEqual([HEAD_H + 4 * ROW_H + 1, HEAD_H + 4 * ROW_H + 1]);
    expect(pages[1].rowH).toEqual([ROW_H, ROW_H, ROW_H]);
    expect(pages.every((p) => p.w <= 560)).toBe(true);
  });

  it('shows too many columns in groups, the first column in each', () => {
    const heads = [...Array(10).keys()].map((i) => `C${i}`);
    const pages = tablePages({ heads, rows: [heads.map((h) => `${h} cell`)] }, 560, 194, m);
    expect(pages.length).toBe(2);
    expect(pages.every((p) => p.cols[0] === 0)).toBe(true);
    expect(new Set(pages.flatMap((p) => p.cols)).size).toBe(10);
  });

  it('tiles a picture in boxes the glasses take', () => {
    for (const [w, h] of [[560, 183], [280, 140], [576, 288], [300, 60]]) {
      const t = tiles(w, h);
      expect(t.every((b) => b.w <= TILE_W && b.h <= TILE_H && b.w >= 20 && b.h >= 20)).toBe(true);
      expect(t.reduce((a, b) => a + b.w * b.h, 0)).toBe(w * h);
      expect(t.length).toBeLessThanOrEqual(4);
    }
    expect(tiles(280, 140).length).toBe(1);
  });

  it('puts a table on picture pages, its lead-in line over it', () => {
    const d: SessionDetail = {
      id: 's',
      title: 'Open asks',
      status: 'needs_you',
      last_reply: 'cards',
      pending: null,
      reply_parts: [
        { text: 'Where the open asks stand:' },
        { table: { heads: ['Ask', 'Status'], rows: [['Laminate quote', 'Needs you']] } },
        { text: 'One needs you.' },
      ],
    };
    const pages = sessionPages(d);
    expect(pages.length).toBe(2);
    expect(typeof pages[0]).toBe('object');
    expect(pages[1]).toBe('One needs you.');
    const spec = sessionPage({ title: 'Open asks', pages, page: 0, status: '', pending: null, notice: null });
    expect(spec.texts.find((t) => t.name === 'body')?.content).toBe('Where the open asks stand:');
    expect(spec.texts.find((t) => t.name === 'body')?.capture).toBe(true);
    expect(spec.images?.length).toBeGreaterThan(0);
    expect(spec.images!.every((i) => i.y >= 62 + 27)).toBe(true);
    // Pictures off: the cards, as before.
    expect(sessionPages(d, false, false)).toEqual(['cards']);
  });
});
