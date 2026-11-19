import { describe, expect, it } from 'vitest';
import type { Glance, Pending, SessionDetail } from './api';
import { MAX_BUTTONS, buttonBoxes, cardButtons, cardOf, cardPage, cardRows, homeRows, tagText, youLine } from './screens';
import { TEXT_BYTES, byteLength, width } from './text';

// The glance card with made-up press jobs and supplier quotes.

const quote: Glance = {
  status_word: 'NEEDS YOU',
  lines: ['Harbor Film: $4,820 for 50,000', 'Lead: 2 wk after proof OK', 'Rush: +15%'],
  you: 'approve the proof',
  options: [],
  phrase: 'approve the proof',
};
const asks: Glance = {
  status_word: 'NEEDS YOU',
  lines: ['! Job 4490 proof: pick a day + time', '! Head 2 order: pick 1 or 2 heads', 'Laminate: wait New Star, Mon 11/30', 'Ink order: wait Harbor, Tue', 'Belts: wait supplier', 'Die quote: wait Harbor Dies', 'Rewinder 2 belts: done'],
  states: ['needs', 'needs', 'working', 'working', 'working', 'working', 'done'],
  you: null,
  options: [],
};
const question: Pending = {
  kind: 'question',
  text: 'Which press runs job 4471?',
  options: [
    { id: 'q0.o0', label: 'Press 3 (gloss line)' },
    { id: 'q0.o1', label: 'Press 5 (matte line)' },
  ],
};

describe('the glance card', () => {
  it('puts a blank line between short lines, and You under them', () => {
    expect(cardRows(quote, 6)).toEqual(['Harbor Film: $4,820 for 50,000', '', 'Lead: 2 wk after proof OK', '', 'Rush: +15%']);
    expect(youLine(quote, null)).toEqual({ text: 'You: approve the proof', bright: true });
    expect(youLine({ ...quote, you: 'nothing now' }, null)).toEqual({ text: 'You: nothing now', bright: false });
    expect(youLine(asks, null)).toBeNull(); // the ! lines say it
  });

  it('packs the lines when the blanks do not fit, and counts the rest', () => {
    expect(cardRows({ ...asks, lines: asks.lines.slice(0, 4) }, 5)).toHaveLength(4);
    const rows = cardRows(asks, 5);
    expect(rows).toEqual(['! Job 4490 proof: pick a day + time', '! Head 2 order: pick 1 or 2 heads', 'Laminate: wait New Star, Mon 11/30', 'Ink order: wait Harbor, Tue', '+3 more']);
    const working = { ...asks, states: asks.states!.map((s, i) => (i < 2 ? s : 'working')) };
    const last = cardRows(working, 5);
    expect(last[last.length - 1]).toBe('+3 waiting');
  });

  it('wraps a long line under itself, never cuts its words', () => {
    const rows = cardRows({ ...quote, lines: ['Error: job 4471 is locked by another user on the Press 3 PC since 6:40 AM today'] }, 6);
    expect(rows.length).toBe(2);
    expect(rows.join(' ')).toContain('since 6:40 AM today');
  });

  it('shows the answers as buttons, short words when they are for this question, then Say it', () => {
    const g = { ...quote, options: [{ id: 'q0.o0', label: 'Press 3' }, { id: 'q0.o1', label: 'Press 5' }] };
    expect(cardButtons(g, question).map((b) => b.label)).toEqual(['Press 3', 'Press 5', 'Say it']);
    // Short words from another question: the question's own.
    const other = { ...quote, options: [{ id: 'q1.o0', label: 'Day' }, { id: 'q1.o1', label: 'Night' }] };
    expect(cardButtons(other, question).map((b) => b.label)).toEqual(['Press 3 (gloss line)', 'Press 5 (matte line)', 'Say it']);
    expect(cardButtons(g, null)).toEqual([]);
  });

  it('keeps the buttons on the lens, the chosen one marked, and scrolls more than fit in place', () => {
    const many: Pending = { ...question, options: ['Press 1', 'Press 2', 'Press 3', 'Press 5', 'Press 6'].map((l, i) => ({ id: `q0.o${i}`, label: l })) };
    const buttons = cardButtons(quote, many);
    const a = buttonBoxes(buttons, 0, 0);
    const b = buttonBoxes(buttons, 4, 2);
    expect(a).toHaveLength(MAX_BUTTONS);
    expect(a.map((x) => [x.x, x.w])).toEqual(b.map((x) => [x.x, x.w])); // a swipe changes only the words
    expect(a[0].content).toBe('▶ Press 1');
    expect(b[2].content).toBe('▶ Press 6');
    for (const x of [...a, ...b]) expect(x.x + x.w).toBeLessThanOrEqual(576);
  });

  it('centers the status word in its box', () => {
    expect(tagText('DONE').trim()).toBe('DONE');
    expect(tagText('DONE').startsWith(' ')).toBe(true);
    expect(width(tagText('NEEDS YOU'))).toBeLessThan(140);
  });

  it('fits the page: every box inside the lens, its words within the byte cap', () => {
    const page = cardPage({ title: 'Label quote, Harbor Film', glance: asks, buttons: cardButtons(quote, question), sel: 0, first: 0, message: null, head: null, replyPages: 3 });
    expect(page.texts.length).toBeLessThanOrEqual(8);
    expect(page.texts.filter((t) => t.capture)).toHaveLength(1);
    for (const t of page.texts) {
      expect(t.y + t.h).toBeLessThanOrEqual(288);
      expect(byteLength(t.content)).toBeLessThanOrEqual(TEXT_BYTES);
    }
    const lines = page.texts.find((t) => t.name === 'lines')!;
    const btn = page.texts.find((t) => t.name === 'btn0')!;
    expect(lines.y + lines.h).toBeLessThanOrEqual(btn.y);
  });

  it('makes a card from the reply when the bridge sent none', () => {
    const d: SessionDetail = { id: 'cse_a', title: 'Job 4471', status: 'needs_you', has_pending: true, last_reply: 'Job 4471 is ready. It runs on Press 3.', pending: question };
    const g = cardOf(d, null);
    expect(g.status_word).toBe('NEEDS YOU');
    expect(g.lines).toEqual(['Which press runs job 4471?']);
    expect(g.you).toBe('pick below');
    expect(cardOf({ ...d, status: 'idle', pending: null }, null)).toMatchObject({ status_word: 'DONE', lines: ['Job 4471 is ready.'], you: 'nothing now' });
  });

  it("puts the card's few words on the Home row", () => {
    const rows = homeRows([
      { id: 'a', title: 'Label quote, Harbor Film', status: 'needs_you', glance: quote },
      { id: 'b', title: 'Rewinder 2 belt order', status: 'waiting' },
    ]);
    expect(rows[1].label).toMatch(/Label quote.* · approve the proof$/);
    expect(rows[2].label).toMatch(/Rewinder 2 belt order · waiting$/);
  });
});
