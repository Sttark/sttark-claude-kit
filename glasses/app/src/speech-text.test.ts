import { describe, expect, it } from 'vitest';
import { MAX_CHARS, spokenText } from './speech-text';

// The same cases as the bridge's own (glasses/bridge/test_bridge.py, Speech),
// so the phone's voice and the Mac's sound say the same words.

const REPLY =
  'Press 3 is clean now. The cyan head printed a full nozzle check.\n\nNext I will order two heads from the supplier. See https://example.com/quote for the price.';

describe('the words Read to me says', () => {
  it('says the glance when the session has one', () => {
    const d = { title: 'Press 3 heads', status: 'idle' as const, why: 'Done', glance: 'Heads cleaned; two on order', last_reply: REPLY };
    expect(spokenText(d)).toBe('Press 3 heads. Heads cleaned; two on order.');
  });

  it('else the status line and the first two sentences of the reply', () => {
    const d = { title: 'Press 3 heads', status: 'working' as const, status_line: 'Ordering heads', last_reply: REPLY };
    expect(spokenText(d)).toBe('Press 3 heads. Working: Ordering heads. Press 3 is clean now. The cyan head printed a full nozzle check.');
  });

  it('ends with the question and its answers, and does not say the question twice', () => {
    const d = {
      title: 'Press job 4471',
      status: 'needs_you' as const,
      why: 'Which press?',
      last_reply: 'Job 4471 is next.',
      pending: {
        kind: 'question' as const,
        text: 'Which press?',
        options: [
          { id: 'q0.o0', label: 'Press 3' },
          { id: 'q0.o1', label: 'Press 5' },
        ],
      },
    };
    expect(spokenText(d)).toBe('Press job 4471. Needs you. Job 4471 is next. It asks: Which press? The answers: 1, Press 3. 2, Press 5.');
  });

  it('names a plan and a permission', () => {
    const plan = { title: 'Label die', status: 'needs_you' as const, pending: { kind: 'plan' as const, text: '# Plan\nLong plan', options: [] } };
    expect(spokenText(plan).endsWith('It has a plan for you to approve.')).toBe(true);
    const perm = { title: 'Label die', status: 'needs_you' as const, pending: { kind: 'permission' as const, text: 'Run the die report', options: [] } };
    expect(spokenText(perm).endsWith('It asks for your OK: Run the die report.')).toBe(true);
  });

  it('reads no marks, links or emoji', () => {
    const d = { title: '✅ **Rewinder 2**', status: 'idle' as const, last_reply: '## Belts\n- Order [two belts](https://example.com/b) -> today\n| Belt | Qty |' };
    expect(spokenText(d)).toBe('Rewinder 2. Idle. Belts. Order two belts to today.');
  });

  it('cuts a long text at a word', () => {
    const t = spokenText({ title: 'Quote', status: 'idle', glance: 'word '.repeat(400) });
    expect(t.length).toBeLessThanOrEqual(MAX_CHARS + 1);
    expect(t.endsWith('word.')).toBe(true);
  });
});
