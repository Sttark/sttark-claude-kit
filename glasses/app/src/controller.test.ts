import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Bridge, Pending, SessionDetail, SessionRow } from './api';
import { Controller } from './controller';
import type { Glasses, PageSpec } from './glasses';

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
