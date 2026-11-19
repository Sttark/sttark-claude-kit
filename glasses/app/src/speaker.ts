// Read to me: sound on the phone. The glasses have no speaker and the Even
// Hub SDK has no sound output, but the app is a web page in the phone's Even
// app, so a web page's own sound plays on the phone: its speaker, or the
// earbuds connected to it.
//
// The first way is one <audio> element that plays the sound the Mac makes
// (GET /api/sessions/:id/speech). The second is the phone's own voice
// (speechSynthesis), when the Mac cannot make the sound or the element cannot
// play it. Many phone web views let a page play sound only after a tap on the
// page itself, and a gesture on the glasses is not a tap on the page. So the
// app keeps ONE element, and the first tap on the phone page plays it once
// (unlock); after that the same element plays when a glasses gesture asks.
export interface ReadSource {
  id: string;
  title: string;
  /** The sound from the Mac, and its words. */
  audio: () => Promise<{ audio: Blob; text: string }>;
  /** The words, made on the phone: when the Mac gives no words. */
  words: () => string;
}

export type ReadResult =
  | { result: 'playing' | 'spoken' | 'stopped' }
  | { result: 'blocked' }
  | { result: 'failed'; why: string };

export interface SpeakerState {
  /** The session being read now, and whether its sound is still on its way. */
  reading: { id: string; title: string; loading: boolean } | null;
  /** The phone let the page play sound (after a tap on the page, or a play that worked). */
  on: boolean;
  /** The last read was refused by the phone: a tap on the page is needed. */
  blocked: boolean;
  /** Test mode (?mute=1): the sound plays with no volume, so tests make no noise. */
  muted: boolean;
}

/** The parts of an <audio> element this uses, so a test can give its own. */
export interface AudioLike {
  src: string;
  muted: boolean;
  play(): Promise<void>;
  pause(): void;
  addEventListener(type: string, f: (e: Event) => void): void;
}

export interface SpeakerEnv {
  audio: () => AudioLike;
  synth: () => SpeechSynthesis | null;
  objectUrl: (b: Blob) => string;
  revoke: (u: string) => void;
}

const browserEnv: SpeakerEnv = {
  audio: () => {
    const el = new Audio();
    el.preload = 'auto';
    return el;
  },
  synth: () => (typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null),
  objectUrl: (b) => URL.createObjectURL(b),
  revoke: (u) => URL.revokeObjectURL(u),
};

/** How long the phone's voice may take to start before it counts as not working. */
const VOICE_START_MS = 3000;

export class Speaker {
  private el: AudioLike | null = null;
  private url: string | null = null;
  private seq = 0;
  private st: SpeakerState;
  private listeners = new Set<(s: SpeakerState) => void>();

  constructor(
    muted = false,
    private env: SpeakerEnv = browserEnv,
  ) {
    this.st = { reading: null, on: false, blocked: false, muted };
  }

  state(): SpeakerState {
    return this.st;
  }

  onChange(f: (s: SpeakerState) => void): () => void {
    this.listeners.add(f);
    return () => this.listeners.delete(f);
  }

  private set(p: Partial<SpeakerState>): void {
    this.st = { ...this.st, ...p };
    this.listeners.forEach((f) => f(this.st));
  }

  /** The one element. Its events go to the console as "[kit] speech <event>",
   *  so a test can see the sound play without listening to it. */
  private element(): AudioLike {
    if (this.el) return this.el;
    const el = this.env.audio();
    for (const t of ['playing', 'ended', 'pause', 'error']) {
      el.addEventListener(t, () => {
        if (el.src.startsWith('data:')) return; // the unlock and the test tone
        console.log(`[kit] speech ${t}`);
        if ((t === 'ended' || t === 'error') && this.st.reading && !this.st.reading.loading) this.finish();
      });
    }
    this.el = el;
    return el;
  }

  /** Call from a tap on the phone page: the phone then lets the page play
   *  sound. With `tone`, a short tone says that the sound works, and where
   *  it comes out. */
  unlock(tone = false): void {
    const el = this.element();
    if (this.st.reading && !this.st.reading.loading) return; // it plays now: leave it
    el.src = tone ? TONE : SILENCE;
    el.muted = this.st.muted;
    el.play().then(
      () => this.set({ on: true, blocked: false }),
      () => {},
    );
    // The phone's voice has the same rule on some phones: an empty utterance in the tap.
    const synth = this.env.synth();
    if (synth && !this.st.on) {
      try {
        const u = new SpeechSynthesisUtterance(' ');
        u.volume = 0;
        synth.speak(u);
      } catch {}
    }
  }

  /** Read a session aloud. Anything read before stops first. */
  async read(src: ReadSource): Promise<ReadResult> {
    this.stop();
    const my = ++this.seq;
    this.set({ reading: { id: src.id, title: src.title, loading: true } });
    let text = '';
    let why = '';
    try {
      const r = await src.audio();
      if (my !== this.seq) return { result: 'stopped' };
      text = r.text;
      const el = this.element();
      this.url = this.env.objectUrl(r.audio);
      el.src = this.url;
      el.muted = this.st.muted;
      try {
        await el.play();
        if (my !== this.seq) return { result: 'stopped' };
        this.set({ reading: { id: src.id, title: src.title, loading: false }, on: true, blocked: false });
        return { result: 'playing' };
      } catch (e) {
        if (my !== this.seq) return { result: 'stopped' };
        if ((e as Error)?.name === 'NotAllowedError') this.set({ blocked: true, on: false });
        else why = 'the phone cannot play the sound';
        console.warn(`[kit] speech play refused: ${(e as Error)?.name || e}`);
      }
    } catch (e) {
      if (my !== this.seq) return { result: 'stopped' };
      why = (e as Error)?.message || String(e);
      console.warn(`[kit] speech from the Mac failed: ${why}`);
    }
    // The phone's own voice.
    const spoken = await this.voice(text || src.words(), my);
    if (spoken === 'stopped') return { result: 'stopped' };
    if (spoken === 'spoken') {
      this.set({ blocked: false });
      return { result: 'spoken' };
    }
    this.finish();
    if (this.st.blocked || spoken === 'blocked') {
      this.set({ blocked: true, on: false });
      return { result: 'blocked' };
    }
    return { result: 'failed', why: why || 'no sound on this phone' };
  }

  private voice(text: string, my: number): Promise<'spoken' | 'blocked' | 'none' | 'stopped'> {
    const synth = this.env.synth();
    if (!synth || !text) return Promise.resolve('none');
    return new Promise((resolve) => {
      let started = false;
      const u = new SpeechSynthesisUtterance(text);
      u.volume = this.st.muted ? 0 : 1;
      const timer = setTimeout(() => {
        if (started) return;
        synth.cancel();
        resolve(my === this.seq ? 'none' : 'stopped');
      }, VOICE_START_MS);
      u.onstart = () => {
        started = true;
        clearTimeout(timer);
        console.log('[kit] speech voice playing');
        if (my !== this.seq) return resolve('stopped');
        const r = this.st.reading;
        if (r) this.set({ reading: { ...r, loading: false } });
        resolve('spoken');
      };
      u.onend = () => {
        console.log('[kit] speech voice ended');
        if (my === this.seq) this.finish();
      };
      u.onerror = (e) => {
        clearTimeout(timer);
        if (started) {
          if (my === this.seq) this.finish();
          return;
        }
        resolve(my !== this.seq ? 'stopped' : e.error === 'not-allowed' ? 'blocked' : 'none');
      };
      synth.cancel();
      synth.speak(u);
    });
  }

  /** Stop reading. */
  stop(): void {
    this.seq++;
    if (this.el && !this.el.src.startsWith('data:')) {
      try {
        this.el.pause();
      } catch {}
    }
    try {
      if (this.st.reading) this.env.synth()?.cancel();
    } catch {}
    this.finish();
  }

  private finish(): void {
    if (this.url) {
      this.env.revoke(this.url);
      this.url = null;
    }
    if (this.st.reading) this.set({ reading: null });
  }
}

// ---------- the two short sounds ----------

/** A WAV file of `ms` milliseconds, 8 kHz mono 16-bit: silence, or a soft tone. */
function wav(ms: number, hz: number, gain: number): string {
  const rate = 8000;
  const n = Math.round((rate * ms) / 1000);
  const b = new Uint8Array(44 + n * 2);
  const v = new DataView(b.buffer);
  const str = (o: number, s: string) => [...s].forEach((c, i) => (b[o + i] = c.charCodeAt(0)));
  str(0, 'RIFF');
  v.setUint32(4, 36 + n * 2, true);
  str(8, 'WAVE');
  str(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, 'data');
  v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const fade = Math.min(1, i / 200, (n - i) / 200); // no click at either end
    v.setInt16(44 + i * 2, Math.round(Math.sin((2 * Math.PI * hz * i) / rate) * gain * fade * 32767), true);
  }
  let bin = '';
  b.forEach((x) => (bin += String.fromCharCode(x)));
  return `data:audio/wav;base64,${btoa(bin)}`;
}

const SILENCE = wav(100, 0, 0);
const TONE = wav(250, 880, 0.3);
