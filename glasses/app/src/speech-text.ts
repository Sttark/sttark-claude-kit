// Read to me: the words for a session. The bridge makes the same words into
// sound on the Mac (glasses/bridge/speech.py); this copy is for the phone's
// own voice, when the Mac cannot make the sound. The two keep the same rules
// and the same test cases (speech-text.test.ts, test_bridge.py Speech).
//
// In order: the session's name; its glance (a short summary) when it has
// one, else its status line and the first two sentences of its last reply;
// then the question it asks now, with the answers.
import type { Pending, SessionRow, Status } from './api';

export const MAX_CHARS = 900;

const STATUS_WORDS: Record<Status, string> = {
  needs_you: 'Needs you',
  working: 'Working',
  waiting: 'Waiting',
  idle: 'Idle',
};

/** Text as a voice should read it: no links, no Markdown or table marks, no emoji. */
export function speakable(s: string | null | undefined): string {
  let t = String(s ?? '');
  t = t.replace(/!?\[([^\]]+)\]\([^)]*\)/g, '$1');
  t = t.replace(/https?:\/\/\S+/g, 'a link');
  t = t.replace(/`+/g, '');
  t = t.replace(/(\*\*|__)(.+?)\1/g, '$2');
  t = t.replace(/^\s*(#{1,6}|>|[-*+]|\d+[.)])\s+/gm, '');
  t = t.replace(/\|/g, ', ').replace(/->|→|=>/g, ' to ');
  t = t.replace(/[\p{So}\p{Cs}\p{Co}\u{FE0F}\u{200D}]/gu, '');
  t = t.replace(/…/g, '...').replace(/—/g, ', ').replace(/–/g, '-');
  return t;
}

function sentence(s: string): string {
  let t = s.replace(/\s+/g, ' ').trim().replace(/^[ ,;:]+|[ ,;:]+$/g, '');
  if (t && !/[.!?]$/.test(t)) t += '.';
  return t;
}

/** The first `n` sentences. A line that ends without a stop (a heading, a
 *  list item, a table card's line) is a sentence of its own. */
export function firstSentences(text: string, n = 2): string[] {
  const flat = speakable(text)
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => /\w/.test(l))
    .map(sentence)
    .join(' ');
  const out: string[] = [];
  for (let p of flat.split(/(?<=[.!?])\s+(?=["'([]?[A-Z0-9])/)) {
    p = p.trim();
    if (!p) continue;
    if (p.length > 300) p = p.slice(0, 300).replace(/\s+\S*$/, '').replace(/[ ,;:]+$/, '') + '.';
    out.push(p);
    if (out.length === n) break;
  }
  return out;
}

const clean = (s: string | null | undefined) => speakable(s).replace(/\s+/g, ' ').trim();

/** The words to read for a session: a list row or the detail. */
export function spokenText(d: Partial<SessionRow> & { last_reply?: string | null; pending?: Pending | null }): string {
  const parts = [sentence(clean(d.title) || 'This session')];
  const pending = d.pending ?? null;
  const glance = clean(d.glance);
  if (glance) {
    parts.push(sentence(glance));
  } else {
    const words = STATUS_WORDS[d.status as Status] ?? 'Idle';
    // The status line's words. While a question waits, they repeat the question, which comes last.
    const why = pending ? '' : clean(d.why || d.status_line);
    parts.push(sentence(why ? `${words}: ${why}` : words));
    parts.push(...firstSentences(d.last_reply || ''));
  }
  if (pending) {
    const text = clean(pending.text);
    if (pending.kind === 'plan') {
      parts.push('It has a plan for you to approve.');
    } else if (pending.kind === 'permission') {
      parts.push(sentence(text ? `It asks for your OK: ${text}` : 'It asks for your OK.'));
    } else {
      parts.push(sentence(text ? `It asks: ${text}` : 'It asks you a question.'));
      const labels = (pending.options || []).map((o) => clean(o.label)).filter(Boolean);
      if (labels.length) parts.push('The answers: ' + labels.slice(0, 6).map((l, i) => sentence(`${i + 1}, ${l}`)).join(' '));
    }
  }
  let text = parts.filter(Boolean).join(' ');
  if (text.length > MAX_CHARS) text = text.slice(0, MAX_CHARS).replace(/\s+\S*$/, '').replace(/[ ,;:]+$/, '') + '.';
  return text;
}
