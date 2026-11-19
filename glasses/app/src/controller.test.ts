import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Bridge, Pending, SessionDetail, SessionRow, Turn } from './api';
import { Controller } from './controller';
import type { Glasses, PageSpec } from './glasses';

// The swipe direction from the phone panel, set by a test.
const swap = vi.hoisted(() => ({ on: false }));
vi.mock('./settings', async (orig) => {
  const real = await orig<typeof import('./settings')>();
  return { ...real, settings: () => ({ ...real.DEFAULTS, swapSwipe: swap.on }) };
});

// The controller with a stand-in bridge and lens: what a swipe and a tap do
// on the text lists, and a prompt with two questions (the bridge answers
// `done: false` with the next one).

const first: Pending = {
  kind: 'question',
  text: '(1/2) Which press?',
  options: [
    { id: 'q0.o0', label: 'Press 3' },
    { id: 'q0.o1', label: 'Press 5' },
  ],
};
const second: Pending = {
  kind: 'question',
  text: '(2/2) Which shift?',
  options: [
    { id: 'q1.o0', label: 'Day' },
    { id: 'q1.o1', label: 'Night' },
  ],
};
const rows: SessionRow[] = [
  { id: 'cse_a', title: 'Rewinder 2 belt order', status: 'waiting' },
  { id: 'cse_b', title: 'Press job 4471', status: 'needs_you', has_pending: true },
];
const detail: SessionDetail = { ...rows[1], last_reply: 'Job 4471 is next.', pending: first };

function setup(start: SessionDetail = detail) {
  const shown: PageSpec[] = [];
  const lens = { show: (p: PageSpec) => shown.push(p), invalidate() {}, mic: async () => true, exit: async () => {}, present: true };
  // Like the bridge: the detail shows the question that waits now.
  let now: SessionDetail = start;
  const answer = vi.fn(async (_id: string, option: string) => {
    if (option.startsWith('q0.')) {
      now = { ...detail, pending: second };
      return { ok: true, done: false, pending: second };
    }
    now = { ...detail, status: 'working', has_pending: false, pending: null };
    return { ok: true, done: true };
  });
  const bridge = {
    health: async () => ({ ok: true, version: 'test' }),
    sessions: async () => rows,
    session: async () => now,
    folders: async () => [],
    live: () => null,
    answer,
    message: vi.fn(async () => ({ ok: true })),
  };
  const app = new Controller(bridge as unknown as Bridge, lens as unknown as Glasses);
  const text = (name: string) => shown[shown.length - 1]?.texts.find((t) => t.name === name)?.content ?? '';
  return { app, answer, text, last: () => shown[shown.length - 1] };
}

describe('the controller', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(console, 'log').mockImplementation(() => {}); // the "[kit] screen" lines
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function settle(ms = 1000) {
    await vi.advanceTimersByTimeAsync(ms);
  }

  it('moves the > with a swipe and opens the marked row with a tap', async () => {
    const { app, text } = setup();
    app.start();
    await settle();
    expect(text('sessions').split('\n')[0].startsWith('>')).toBe(true); // + New session
    app.handle({ kind: 'down' });
    await settle();
    const lines = text('sessions').split('\n');
    expect(lines[1].startsWith('>')).toBe(true);
    expect(lines[1]).toContain('Press job 4471'); // needs you sorts first
    app.handle({ kind: 'tap', from: 'text' });
    await settle();
    expect(app.snapshot().screen).toBe('session');
  });

  /** Home, down to the session that asks, tap: its card. Then past the tap guard. */
  async function openAsking(app: Controller) {
    app.start();
    await settle();
    app.handle({ kind: 'down' });
    await settle();
    app.handle({ kind: 'tap', from: 'text' });
    await settle();
  }
  const buttons = (shown: () => PageSpec | undefined) =>
    (shown()?.texts ?? []).filter((t) => t.name.startsWith('btn')).map((t) => t.content.trim());

  it('opens a session on its card: the answers as buttons, a swipe picks, a tap sends', async () => {
    const { app, answer, text, last } = setup();
    await openAsking(app);
    expect(app.snapshot().screen).toBe('session');
    expect(text('lines')).toContain('Which press?');
    expect(text('tag').trim()).toBe('NEEDS YOU');
    expect(buttons(last)).toEqual(['▶ Press 3', 'Press 5', 'Say it']);
    app.handle({ kind: 'down' });
    await settle();
    expect(buttons(last)).toEqual(['Press 3', '▶ Press 5', 'Say it']);
    app.handle({ kind: 'tap', from: 'text' });
    await settle();
    expect(answer).toHaveBeenLastCalledWith('cse_b', 'q0.o1');
    // The bridge keeps it (done: false): the next question takes the buttons, the first one chosen.
    expect(text('lines')).toContain('Which shift?');
    expect(buttons(last)).toEqual(['▶ Day', 'Night', 'Say it']);
    app.handle({ kind: 'down' });
    await settle();
    app.handle({ kind: 'tap', from: 'text' }); // Night
    await settle();
    expect(answer).toHaveBeenLastCalledWith('cse_b', 'q1.o1');
    expect(app.snapshot().screen).toBe('session');
    expect(text('head')).toBe('Sent: Night');
  });

  it('takes no tap in the first 0.7 s after the card with answers opens', async () => {
    const { app, answer } = setup();
    app.start();
    await settle();
    app.handle({ kind: 'down' });
    await settle();
    app.handle({ kind: 'tap', from: 'text' }); // the card opens
    await vi.advanceTimersByTimeAsync(400);
    app.handle({ kind: 'tap', from: 'text' }); // too soon: the same finger
    await settle();
    expect(answer).not.toHaveBeenCalled();
  });

  it('shows the full reply one swipe past the last button, and comes back to it', async () => {
    const { app, text, last } = setup();
    await openAsking(app);
    app.handle({ kind: 'down' });
    await settle();
    app.handle({ kind: 'down' }); // Say it
    await settle();
    expect(buttons(last)).toEqual(['Press 3', 'Press 5', '▶ Say it']);
    app.handle({ kind: 'down' }); // the full reply
    await settle();
    expect(text('body')).toContain('Job 4471 is next.');
    app.handle({ kind: 'up' }); // back on the card, on Say it
    await settle();
    expect(buttons(last)).toEqual(['Press 3', 'Press 5', '▶ Say it']);
    app.handle({ kind: 'tap', from: 'text' });
    await settle();
    expect(app.snapshot().screen).toBe('voice');
    app.handle({ kind: 'double' }); // cancel: back on the card
    await settle();
    expect(app.snapshot().screen).toBe('session');
    expect(text('lines')).toContain('Which press?');
  });

  it('still answers from the actions, opened with a tap on the full reply', async () => {
    const { app, answer, text } = setup();
    await openAsking(app);
    for (let i = 0; i < 3; i++) {
      app.handle({ kind: 'down' }); // Press 5, Say it, the full reply
      await settle();
    }
    app.handle({ kind: 'tap', from: 'text' }); // the actions
    await settle();
    expect(text('ask')).toContain('Which press?');
    app.handle({ kind: 'tap', from: 'text' }); // Press 3
    await settle();
    expect(answer).toHaveBeenLastCalledWith('cse_b', 'q0.o0');
    expect(app.snapshot().screen).toBe('actions');
    expect(text('ask')).toContain('Which shift?');
  });

  it('a card with no question: its lines, You, and a tap opens the actions', async () => {
    const { app, text } = setup({
      ...rows[1],
      has_pending: false,
      status: 'idle',
      last_reply: 'Long reply.',
      pending: null,
      glance: { status_word: 'DONE', lines: ['Quote: $4,820 for 50,000 labels', 'Lead: 2 wk after proof OK'], you: 'nothing now', options: [] },
    });
    await openAsking(app);
    expect(text('lines')).toBe('Quote: $4,820 for 50,000 labels\n\nLead: 2 wk after proof OK');
    expect(text('you')).toBe('You: nothing now');
    expect(text('tag').trim()).toBe('DONE');
    app.handle({ kind: 'tap', from: 'text' });
    await settle();
    expect(app.snapshot().screen).toBe('actions');
  });
});

// Scrolling back to earlier turns: made-up press and supplier work.
const job = 'Press job 4471';
const turnsOf: Turn[] = [
  { index: 0, at: '2026-11-05T13:05:00Z', from: 'you', user_text: 'Pull the start-up checks for all presses', reply_text: 'Presses 1, 2 and 5 passed. Press 3 failed the nozzle check.' },
  { index: 1, at: '2026-11-18T13:30:00Z', from: 'kit', user_text: 'A wait you handed to the Kit has ended.', reply_text: 'New Star Labels quotes $0.12 per m for 5,000 m.' },
  {
    index: 2,
    at: '2026-11-19T14:10:00Z',
    from: 'you',
    user_text: 'Is the head 2 problem new?',
    reply_text: Array.from({ length: 14 }, (_, i) => `Line ${i + 1} of the head 2 history.`).join('\n'),
  },
  { index: 3, at: '2026-11-19T14:40:00Z', from: 'you', user_text: 'What next for job 4471?', reply_text: 'Job 4471 is next.' },
];

function setupHistory(pending: Pending | null = null) {
  const shown: PageSpec[] = [];
  const lens = { show: (p: PageSpec) => shown.push(p), invalidate() {}, mic: async () => true, exit: vi.fn(async () => {}), present: true };
  const one: SessionDetail = { id: 'cse_b', title: job, status: pending ? 'needs_you' : 'idle', has_pending: !!pending, last_reply: 'Job 4471 is next.', pending };
  const turns = vi.fn(async (_id: string, before?: number, limit = 5) => {
    const end = before ?? turnsOf.length;
    return { turns: turnsOf.slice(Math.max(0, end - limit), end), total: turnsOf.length, latest: 3 };
  });
  const bridge = {
    health: async () => ({ ok: true, version: 'test' }),
    sessions: async () => [{ id: 'cse_b', title: job, status: 'idle' }],
    session: async () => one,
    folders: async () => [],
    live: () => null,
    turns,
  };
  const app = new Controller(bridge as unknown as Bridge, lens as unknown as Glasses);
  const text = (name: string) => shown[shown.length - 1]?.texts.find((t) => t.name === name)?.content ?? '';
  /** The latest turn, at its top: the glance card. */
  const onCard = () => app.snapshot().screen === 'session' && text('lines').includes('Job 4471 is next.');
  return { app, text, turns, lens, onCard };
}

describe('earlier turns', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-19T16:00:00Z'));
    vi.spyOn(console, 'log').mockImplementation(() => {});
    swap.on = false;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function open(pending: Pending | null = null) {
    const h = setupHistory(pending);
    h.app.start();
    await vi.advanceTimersByTimeAsync(500);
    h.app.handle({ kind: 'down' }); // from + New session to the session
    await vi.advanceTimersByTimeAsync(400);
    h.app.handle({ kind: 'tap', from: 'text' });
    await vi.advanceTimersByTimeAsync(500);
    return h;
  }
  async function swipe(app: Controller, kind: 'up' | 'down', n = 1) {
    for (let i = 0; i < n; i++) {
      app.handle({ kind });
      await vi.advanceTimersByTimeAsync(300);
    }
  }

  it('opens on the latest turn, its card, with "▲ earlier" in its hint', async () => {
    const { text, onCard } = await open();
    expect(onCard()).toBe(true);
    expect(text('foot')).toContain('▲ earlier');
  });

  it('with answer buttons: up moves to the first answer, then to the turn before; the top line says "▲ earlier"', async () => {
    const { app, text } = await open(first);
    // With a question, the card shows the question.
    const onCard = () => app.snapshot().screen === 'session' && text('lines').includes('Which press?');
    expect(onCard()).toBe(true);
    expect(text('head')).toContain('▲ earlier');
    await swipe(app, 'down'); // the second answer
    expect(text('btn1')).toMatch(/^▶/);
    await swipe(app, 'up'); // the first answer again
    expect(text('btn0')).toMatch(/^▶/);
    expect(onCard()).toBe(true);
    await swipe(app, 'up');
    expect(text('head')).toMatch(/^Earlier 1 of 3/);
  });

  it('goes up one turn at a time, from each turn\'s top, and down again to the latest', async () => {
    const { app, text, onCard } = await open();
    await swipe(app, 'up');
    expect(text('head')).toMatch(/^Earlier 1 of 3 · /);
    expect(text('status')).toBe('You: Is the head 2 problem new?');
    expect(text('body').split('\n')[0]).toBe('Line 1 of the head 2 history.');
    expect(text('foot')).toContain('▲ earlier');
    await swipe(app, 'up');
    expect(text('head')).toMatch(/^Earlier 2 of 3 · Wed /);
    expect(text('status')).toBe('Kit: A wait you handed to the Kit has ended.');
    await swipe(app, 'up');
    expect(text('head')).toMatch(/^Earlier 3 of 3 · Nov 5$/);
    expect(text('foot')).toContain('First turn');
    await swipe(app, 'up'); // the first turn: nothing above
    expect(text('head')).toMatch(/^Earlier 3 of 3/);
    await swipe(app, 'down', 2); // its one page, then the Kit's turn
    expect(text('head')).toMatch(/^Earlier 1 of 3/);
    await swipe(app, 'down'); // head 2 history, page 2
    expect(text('body')).toContain('Line 14');
    expect(text('foot')).toContain('▼ latest');
    await swipe(app, 'down');
    expect(onCard()).toBe(true);
  });

  it('tap or double tap on an earlier turn shows the latest; double tap there goes Home', async () => {
    const { app, text, onCard } = await open();
    await swipe(app, 'up', 2);
    expect(text('head')).toMatch(/^Earlier 2 of 3/);
    app.handle({ kind: 'tap', from: 'text' });
    await vi.advanceTimersByTimeAsync(400);
    expect(onCard()).toBe(true);
    await swipe(app, 'up');
    app.handle({ kind: 'double' });
    await vi.advanceTimersByTimeAsync(500);
    expect(onCard()).toBe(true);
    app.handle({ kind: 'double' });
    await vi.advanceTimersByTimeAsync(500);
    expect(app.snapshot().screen).toBe('home');
  });

  it('follows the swipe direction setting', async () => {
    const { app, text, onCard } = await open();
    swap.on = true;
    await swipe(app, 'down'); // swapped: this is "up"
    expect(text('head')).toMatch(/^Earlier 1 of 3/);
    await swipe(app, 'up', 2);
    expect(onCard()).toBe(true);
  });

  it('loads older turns a few at a time, before the person gets to them', async () => {
    const { app, turns } = await open();
    expect(turns).toHaveBeenCalledTimes(1);
    expect(turns).toHaveBeenLastCalledWith('cse_b', undefined, 5);
    await swipe(app, 'up');
    expect(turns).toHaveBeenCalledTimes(1); // all four came in the first five
  });
});
