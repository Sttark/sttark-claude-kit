import { describe, expect, it } from 'vitest';
import { measureTextWrap } from '@evenrealities/pretext';
import { TEXT_BYTES, byteLength, clampBytes, glyphSafe, paginate, plainReply, spread, width } from './text';
import { HOME_ROWS, actionItems, homePage, homeRows, listLines, scrollTo, sessionPages, statusLine } from './screens';
import type { SessionDetail, SessionRow } from './api';

const LONG =
  'I read the Press 3 nozzle check from this morning. Heads 2 and 4 still show missing nozzles after one purge. ' +
  'The pattern on head 4 looks like dried ink at the plate, not a failed nozzle. '.repeat(12);

describe('paginate', () => {
  it('never puts more lines on a page than the lens shows', () => {
    const pages = paginate(LONG, 552, 7);
    expect(pages.length).toBeGreaterThan(1);
    for (const p of pages) {
      expect(measureTextWrap(p, 552).lineCount).toBeLessThanOrEqual(7);
      expect(byteLength(p)).toBeLessThanOrEqual(TEXT_BYTES);
    }
  });

  it('keeps every word, in order', () => {
    const pages = paginate(LONG, 552, 7);
    expect(pages.join(' ').replace(/\s+/g, ' ').trim()).toBe(LONG.replace(/\s+/g, ' ').trim());
  });

  it('cuts a word wider than a line', () => {
    const pages = paginate('x'.repeat(300), 552, 7);
    for (const line of pages.join('\n').split('\n')) expect(width(line)).toBeLessThanOrEqual(552);
  });

  it('starts no page with a blank line', () => {
    const text = Array.from({ length: 30 }, (_, i) => `Line ${i}\n`).join('\n');
    for (const p of paginate(text, 552, 7)) expect(p.startsWith('\n')).toBe(false);
  });
});

// What the bridge sends for a Markdown table: one card per row, the row's
// name, then "  Header: cell" lines (made-up press jobs and supplier quotes).
const CARDS =
  'Where the press jobs and quotes stand:\n\n' +
  'Job 4471 gloss wine labels, 12,000 pieces on Press 3\n' +
  '  Needs you: Pick the head 2 fix (a second purge, a hand wipe of the plate or a new head), and I start it before the 2:00 PM run.\n\n' +
  'Job 4480 coffee bags\n  In progress\n\n' +
  'Laminate quote from New Star Labels\n  Price: $0.12 per m for 5,000 m of 330 mm matte\n  Lead time: 3 weeks to the Engineering Office\n\n' +
  'Laminate quote from Harbor Film Co.\n  Price: $0.10 per m\n  Lead time: 6 weeks\n  Notes: Matte only, no gloss\n\n' +
  'Rewinder 2 belts\n  Done\n\n' +
  'Job 4462 sample run\n  Dropped';

describe('cards', () => {
  const PX = 552;
  const pages = paginate(CARDS, PX, 7);
  const lines = pages.join('\n').split('\n');

  it('fits every page and keeps every word', () => {
    expect(pages.length).toBeGreaterThan(1);
    for (const p of pages) {
      expect(measureTextWrap(p, PX).lineCount).toBeLessThanOrEqual(7);
      expect(p.split('\n').length).toBeLessThanOrEqual(7);
      expect(byteLength(p)).toBeLessThanOrEqual(TEXT_BYTES);
    }
    for (const l of lines) expect(width(l)).toBeLessThanOrEqual(PX);
    expect(pages.join(' ').replace(/\s+/g, ' ').trim()).toBe(CARDS.replace(/\s+/g, ' ').trim());
  });

  it('keeps a detail line and its wrapped lines indented under the title', () => {
    const at = lines.findIndex((l) => l.startsWith('  Needs you: Pick the head 2 fix'));
    expect(at).toBeGreaterThan(0);
    expect(lines[at - 1]).toBe('Job 4471 gloss wine labels, 12,000 pieces on Press 3');
    expect(lines[at + 1].startsWith('  ') && !lines[at + 1].startsWith('   ')).toBe(true);
  });

  it('never ends a page with a title whose first detail is on the next page', () => {
    for (const p of pages) {
      const last = p.split('\n').slice(-1)[0];
      const card = CARDS.split('\n').indexOf(last);
      if (card >= 0) expect(CARDS.split('\n')[card + 1]?.startsWith('  ')).not.toBe(true);
    }
  });

  it('moves a title to the next page instead of leaving it alone', () => {
    const text = 'One\ntwo\nthree\nfour\nfive\nsix\n\nPress 3 heads\n  Needs you: Pick a fix';
    expect(paginate(text, PX, 7)).toEqual(['One\ntwo\nthree\nfour\nfive\nsix', 'Press 3 heads\n  Needs you: Pick a fix']);
  });

  it('drops the blank line between cards only when that keeps a card whole', () => {
    const a = 'Rewinder 2 belts\n  Price: $38 each\n  Lead time: 2 days';
    const b = 'Job 4480 coffee bags\n  Status: In progress\n  Press: 5\n  Due: Friday';
    expect(paginate(`${a}\n\n${b}`, PX, 7)).toEqual([`${a}\n${b}`]);
    expect(paginate(`${a}\n\n${b}`, PX, 8)).toEqual([`${a}\n\n${b}`]);
  });
});

describe('lens text', () => {
  it('swaps what the font cannot draw', () => {
    expect(glyphSafe('Done… “ok” — ✓ 🚀')).toBe('Done... "ok"  -  yes ');
  });
  it('drops an emoji with the space after it, so no line starts with a space', () => {
    expect(glyphSafe('✅ Belts came in')).toBe('Belts came in');
    expect(glyphSafe('Press 3 🚀 runs')).toBe('Press 3 runs');
  });
  it('keeps nested list items in, and the blank line before a list', () => {
    expect(plainReply('Heads:\n\n- Head 2\n  - 6 nozzles out')).toBe('Heads:\n\n- Head 2\n  - 6 nozzles out');
  });
  it('turns Markdown into plain words', () => {
    expect(plainReply('## Plan\n**Heads 2** and `4`: see [the log](https://x.example).')).toBe('Plan\nHeads 2 and 4: see the log.');
  });
  it('cuts to a byte budget at a whole character', () => {
    const s = clampBytes('▶'.repeat(40), 63);
    expect(byteLength(s)).toBeLessThanOrEqual(63);
    expect(s.endsWith('...')).toBe(true);
  });
  it('spreads a title and a page mark across one line', () => {
    const line = spread('Press 3 nozzle report', '2/4', 552);
    expect(width(line)).toBeLessThanOrEqual(552);
    expect(line.endsWith('2/4')).toBe(true);
  });
});

const row = (o: Partial<SessionRow>): SessionRow => ({ id: o.title || 'x', title: 'x', status: 'idle', ...o });

describe('home rows', () => {
  it('puts New session first, then needs you, working, waiting, idle', () => {
    const rows = homeRows([
      row({ title: 'Label die template', status: 'idle' }),
      row({ title: 'Atlas web tension check', status: 'working' }),
      row({ title: 'Press 3 nozzle report', status: 'needs_you', has_pending: true }),
      row({ title: 'Rewinder 2 belt order', status: 'waiting' }),
    ]);
    expect(rows.map((r) => r.id)).toEqual([null, 'Press 3 nozzle report', 'Atlas web tension check', 'Rewinder 2 belt order', 'Label die template']);
    expect(rows[1].label).toContain('needs answer');
  });
  it('fits every row on one lens line, status words kept', () => {
    const rows = homeRows([row({ title: 'A very long session title that goes on and on about the Press 3 nozzle report', status: 'needs_you' })]);
    const lines = listLines(rows.map((r) => r.label), 1, 0, HOME_ROWS).split('\n');
    for (const l of lines) expect(width(l)).toBeLessThanOrEqual(556);
    expect(lines[1]).toMatch(/· needs you$/);
  });
});

describe('lists', () => {
  const labels = Array.from({ length: 14 }, (_, i) => `Row ${i + 1}`);
  it('marks the chosen row and lines every row up in one column', () => {
    const lines = listLines(labels, 2, 0, 9).split('\n');
    expect(lines).toHaveLength(9);
    expect(lines[2].startsWith('>')).toBe(true);
    expect(lines.filter((l) => l.startsWith('>'))).toHaveLength(1);
    const at = (l: string) => width(l.slice(0, l.indexOf('Row')));
    for (const l of lines) expect(at(l)).toBe(at(lines[2]));
  });
  it('scrolls only as far as it must, with a row of the list past the mark', () => {
    expect(scrollTo(0, 7, 14, 9)).toBe(0);
    expect(scrollTo(0, 8, 14, 9)).toBe(1);
    expect(scrollTo(5, 13, 14, 9)).toBe(5);
    expect(scrollTo(5, 5, 14, 9)).toBe(4);
    expect(scrollTo(5, 0, 14, 9)).toBe(0);
    expect(scrollTo(3, 4, 5, 9)).toBe(0);
  });
  it('draws Home as text at full brightness, with no list widget', () => {
    const rows = homeRows(Array.from({ length: 12 }, (_, i) => row({ id: `s${i}`, title: `Session ${i}` })));
    const page = homePage({ rows, sel: 10, first: 4, needCount: 0, offline: null, notice: null });
    const list = page.texts.find((t) => t.name === 'sessions')!;
    expect(list.capture).toBe(true);
    expect(list.color ?? 4).toBe(4);
    expect(list.content.split('\n')).toHaveLength(HOME_ROWS);
    expect(byteLength(list.content)).toBeLessThanOrEqual(TEXT_BYTES);
    expect(page.texts[0].content.endsWith('11/13')).toBe(true);
  });
});

describe('one session', () => {
  const d: SessionDetail = {
    id: 'a',
    title: 'Press 3 nozzle report',
    status: 'needs_you',
    has_pending: true,
    last_reply: LONG,
    pending: { kind: 'question', text: 'What next?', options: [{ id: 'p', label: 'Run a second purge' }] },
  };
  it('shows the question on the status line', () => {
    expect(statusLine(null, d, null)).toContain('Question: What next?');
  });
  it('lists the answers first, then reply, continue and back', () => {
    expect(actionItems(d.pending).map((i) => i.kind)).toEqual(['option', 'voice', 'continue', 'back']);
  });
  it('shows a plan waiting for approval as the reply', () => {
    const plan: SessionDetail = { ...d, pending: { kind: 'plan', text: '1. Move the racks.', options: [] } };
    expect(sessionPages(plan)[0]).toBe('1. Move the racks.');
  });
});
