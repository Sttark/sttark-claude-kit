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

function setup() {
  const shown: PageSpec[] = [];
  const lens = { show: (p: PageSpec) => shown.push(p), invalidate() {}, mic: async () => true, exit: async () => {}, present: true };
  // Like the bridge: the detail shows the question that waits now.
  let now: SessionDetail = detail;
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
  return { app, answer, text };
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

  it('shows the next question when the bridge keeps an answer (done: false), then sends', async () => {
    const { app, answer, text } = setup();
    app.start();
    await settle();
    app.handle({ kind: 'down' });
    await settle();
    app.handle({ kind: 'tap', from: 'text' }); // open the session
    await settle();
    app.handle({ kind: 'tap', from: 'text' }); // its actions
    await settle();
    expect(text('ask')).toContain('Which press?');
    app.handle({ kind: 'tap', from: 'text' }); // Press 3
    await settle();
    expect(answer).toHaveBeenLastCalledWith('cse_b', 'q0.o0');
    expect(app.snapshot().screen).toBe('actions');
    expect(text('ask')).toContain('Which shift?');
    app.handle({ kind: 'down' });
    await settle();
    app.handle({ kind: 'tap', from: 'text' }); // Night
    await settle();
    expect(answer).toHaveBeenLastCalledWith('cse_b', 'q1.o1');
    expect(app.snapshot().screen).toBe('session');
  });

  it('takes no tap in the first 0.7 s after the answers open', async () => {
    const { app, answer } = setup();
    app.start();
    await settle();
    app.handle({ kind: 'down' });
    await settle();
    app.handle({ kind: 'tap', from: 'text' });
    await settle();
    app.handle({ kind: 'tap', from: 'text' }); // the actions open
    await vi.advanceTimersByTimeAsync(400);
    app.handle({ kind: 'tap', from: 'text' }); // too soon: the same finger
    await settle();
    expect(answer).not.toHaveBeenCalled();
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

function setupHistory() {
  const shown: PageSpec[] = [];
  const lens = { show: (p: PageSpec) => shown.push(p), invalidate() {}, mic: async () => true, exit: vi.fn(async () => {}), present: true };
  const one: SessionDetail = { id: 'cse_b', title: job, status: 'idle', last_reply: 'Job 4471 is next.', pending: null };
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
  return { app, text, turns, lens };
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

  async function open() {
    const h = setupHistory();
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

  it('opens on the latest turn, with "▲ earlier" in its hint', async () => {
    const { app, text } = await open();
    expect(app.snapshot().screen).toBe('session');
    expect(text('body')).toBe('Job 4471 is next.');
    expect(text('foot')).toContain('▲ earlier');
  });

  it('goes up one turn at a time, from each turn\'s top, and down again to the latest', async () => {
    const { app, text } = await open();
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
    expect(app.snapshot().screen).toBe('session');
    expect(text('body')).toBe('Job 4471 is next.');
  });

  it('tap or double tap on an earlier turn shows the latest; double tap there goes Home', async () => {
    const { app, text } = await open();
    await swipe(app, 'up', 2);
    app.handle({ kind: 'tap', from: 'text' });
    await vi.advanceTimersByTimeAsync(400);
    expect(text('body')).toBe('Job 4471 is next.');
    await swipe(app, 'up');
    app.handle({ kind: 'double' });
    await vi.advanceTimersByTimeAsync(500);
    expect(text('body')).toBe('Job 4471 is next.');
    expect(app.snapshot().screen).toBe('session');
    app.handle({ kind: 'double' });
    await vi.advanceTimersByTimeAsync(500);
    expect(app.snapshot().screen).toBe('home');
  });

  it('follows the swipe direction setting', async () => {
    const { app, text } = await open();
    swap.on = true;
    await swipe(app, 'down'); // swapped: this is "up"
    expect(text('head')).toMatch(/^Earlier 1 of 3/);
    await swipe(app, 'up', 2);
    expect(text('body')).toBe('Job 4471 is next.');
  });

  it('loads older turns a few at a time, before the person gets to them', async () => {
    const { app, turns } = await open();
    expect(turns).toHaveBeenCalledTimes(1);
    expect(turns).toHaveBeenLastCalledWith('cse_b', undefined, 5);
    await swipe(app, 'up');
    expect(turns).toHaveBeenCalledTimes(1); // all four came in the first five
  });
});
