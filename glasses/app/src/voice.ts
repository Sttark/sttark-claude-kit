// Dictation: the glasses mic sends 16 kHz mono 16-bit PCM in 100 ms frames
// (3200 bytes). We keep the frames, and every few seconds send all of them
// to the bridge for words to show while the person speaks. When they finish,
// one last pass gives the words that are sent.
import type { Bridge } from './api';

const BYTES_PER_SECOND = 32000;
const MAX_SECONDS = 90;
const LIVE_EVERY_MS = 2500;

export class Dictation {
  private frames: Uint8Array[] = [];
  private bytes = 0;
  private sentBytes = 0;
  private busy = false;
  private timer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;
  live = '';
  lastFrameAt = 0;
  readonly startedAt = Date.now();

  constructor(
    private bridge: Bridge,
    private onLive: (text: string) => void,
    private onFull: () => void,
  ) {
    this.timer = setInterval(() => void this.tick(), LIVE_EVERY_MS);
  }

  get seconds(): number {
    return this.bytes / BYTES_PER_SECOND;
  }

  add(pcm: Uint8Array): void {
    if (this.stopped) return;
    this.frames.push(pcm.slice());
    this.bytes += pcm.length;
    this.lastFrameAt = Date.now();
    if (this.seconds >= MAX_SECONDS) this.onFull();
  }

  private all(): Uint8Array {
    const out = new Uint8Array(this.bytes);
    let at = 0;
    for (const f of this.frames) {
      out.set(f, at);
      at += f.length;
    }
    return out;
  }

  private async tick(): Promise<void> {
    if (this.busy || this.stopped || this.bytes - this.sentBytes < BYTES_PER_SECOND / 2) return;
    this.busy = true;
    this.sentBytes = this.bytes;
    try {
      const text = await this.bridge.transcribe(this.all());
      if (!this.stopped && text) {
        this.live = text;
        this.onLive(text);
      }
    } catch (e) {
      console.warn('[voice] live words failed:', (e as Error).message);
    } finally {
      this.busy = false;
    }
  }

  /** Stop listening and get the final words ('' when nothing was heard). */
  async finish(): Promise<string> {
    this.stop();
    if (this.bytes < BYTES_PER_SECOND / 4) return this.live;
    return await this.bridge.transcribe(this.all());
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
