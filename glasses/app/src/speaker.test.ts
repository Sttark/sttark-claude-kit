import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Speaker, type AudioLike, type SpeakerEnv } from './speaker';

// The speaker with a stand-in <audio> element and phone voice: what plays,
// what the lens hears back when the phone refuses, and the fallbacks.

class FakeAudio implements AudioLike {
  src = '';
  muted = false;
  played: string[] = [];
  refuse: string | null = null; // the error name play() rejects with
  private on: Record<string, ((e: Event) => void)[]> = {};
  async play() {
    if (this.refuse) {
      const e = new Error('refused');
      e.name = this.refuse;
      throw e;
    }
    this.played.push(this.src);
    this.fire('playing');
  }
  pause() {
    this.fire('pause');
  }
  addEventListener(t: string, f: (e: Event) => void) {
    (this.on[t] ||= []).push(f);
  }
  fire(t: string) {
    (this.on[t] || []).forEach((f) => f(new Event(t)));
  }
}

class FakeUtterance {
  volume = 1;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  constructor(public text: string) {}
}

function setup(o: { refuse?: string; voice?: 'speaks' | 'not-allowed' | 'silent' | 'none' } = {}) {
  const el = new FakeAudio();
  el.refuse = o.refuse ?? null;
  const spoken: string[] = [];
  const synth =
    o.voice === 'none'
      ? null
      : ({
          speak: (u: FakeUtterance) => {
            if (!u.text.trim()) return; // the unlock
            spoken.push(u.text);
            if (o.voice === 'speaks') setTimeout(() => u.onstart?.(), 10);
            if (o.voice === 'not-allowed') setTimeout(() => u.onerror?.({ error: 'not-allowed' }), 10);
          },
          cancel: () => {},
        } as unknown as SpeechSynthesis);
  const env: SpeakerEnv = { audio: () => el, synth: () => synth, objectUrl: () => 'blob:sound', revoke: () => {} };
  const sp = new Speaker(false, env);
  const src = (audio: () => Promise<{ audio: Blob; text: string }>) => ({
    id: 'cse_b',
    title: 'Press job 4471',
    audio,
    words: () => 'Press job 4471. Needs you.',
  });
  const fromMac = async () => ({ audio: new Blob(['x']), text: 'Press job 4471. Needs you. It asks: Which press?' });
  return { sp, el, spoken, src, fromMac };
}

describe('Read to me on the phone', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance);
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("plays the Mac's sound on the one element, and is done when it ends", async () => {
    const { sp, el, src, fromMac } = setup();
    const r = await sp.read(src(fromMac));
    expect(r.result).toBe('playing');
    expect(el.played).toEqual(['blob:sound']);
    expect(sp.state().reading).toMatchObject({ id: 'cse_b', loading: false });
    expect(sp.state().on).toBe(true);
    el.fire('ended');
    expect(sp.state().reading).toBeNull();
  });

  it('says the words with the phone voice when the phone refuses the sound, and asks for a tap when that fails too', async () => {
    const a = setup({ refuse: 'NotAllowedError', voice: 'speaks' });
    const p = a.sp.read(a.src(a.fromMac));
    await vi.advanceTimersByTimeAsync(50);
    expect((await p).result).toBe('spoken');
    expect(a.spoken).toEqual(['Press job 4471. Needs you. It asks: Which press?']); // the Mac's words

    const b = setup({ refuse: 'NotAllowedError', voice: 'not-allowed' });
    const q = b.sp.read(b.src(b.fromMac));
    await vi.advanceTimersByTimeAsync(50);
    expect((await q).result).toBe('blocked');
    expect(b.sp.state().blocked).toBe(true);
    expect(b.sp.state().reading).toBeNull();
  });

  it('a tap on the page turns the sound on, and the next read plays', async () => {
    const { sp, el, src, fromMac } = setup({ refuse: 'NotAllowedError', voice: 'none' });
    expect((await sp.read(src(fromMac))).result).toBe('blocked');
    el.refuse = null; // the phone allows it after the tap
    sp.unlock();
    await vi.advanceTimersByTimeAsync(0);
    expect(sp.state()).toMatchObject({ on: true, blocked: false });
    expect((await sp.read(src(fromMac))).result).toBe('playing');
  });

  it("uses the phone's words when the Mac cannot make the sound", async () => {
    const { sp, spoken, src } = setup({ voice: 'speaks' });
    const p = sp.read(
      src(async () => {
        throw new Error('This bridge has no Read to me yet');
      }),
    );
    await vi.advanceTimersByTimeAsync(50);
    expect((await p).result).toBe('spoken');
    expect(spoken).toEqual(['Press job 4471. Needs you.']);
  });

  it('says why when there is no way to make sound', async () => {
    const { sp, src } = setup({ voice: 'silent' });
    const p = sp.read(
      src(async () => {
        throw new Error('This bridge has no Read to me yet');
      }),
    );
    await vi.advanceTimersByTimeAsync(3500);
    expect(await p).toEqual({ result: 'failed', why: 'This bridge has no Read to me yet' });
  });

  it('stop ends a read that is still on its way', async () => {
    const { sp, el, src } = setup();
    let give: (v: { audio: Blob; text: string }) => void = () => {};
    const p = sp.read(src(() => new Promise((r) => (give = r))));
    expect(sp.state().reading?.loading).toBe(true);
    sp.stop();
    give({ audio: new Blob(['x']), text: 'late' });
    expect((await p).result).toBe('stopped');
    expect(el.played).toEqual([]);
    expect(sp.state().reading).toBeNull();
  });
});
