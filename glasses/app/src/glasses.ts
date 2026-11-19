// The lens driver. Screens describe a page (text boxes; a list is a text box
// too, see screens.ts); this draws it with as little as possible: a
// whole-page rebuild only when the layout changes, otherwise an in-place
// text update, which does not flicker.
//
// Every SDK call goes through one queue, one at a time, each with a time
// limit (a Bluetooth call that never answers must not freeze the lens). A
// call that fails makes the next draw a full rebuild.
import {
  AudioInputSource,
  CreateStartUpPageContainer,
  RebuildPageContainer,
  StartUpPageCreateResult,
  TextContainerProperty,
  TextContainerUpgrade,
  type EvenAppBridge,
} from '@evenrealities/even_hub_sdk';
import { TEXT_BYTES, clampBytes } from './text';
import { withTimeout } from './settings';

export interface TextBox {
  name: string; // at most 16 characters, unique on the page
  x: number;
  y: number;
  w: number;
  h: number;
  content: string;
  /** Brightness 0 (dim) to 4 (full). */
  color?: number;
  capture?: boolean;
  border?: number;
  borderColor?: number;
  radius?: number;
  pad?: number;
}

export interface PageSpec {
  texts: TextBox[];
}

const CALL_MS = 6000;

export class Glasses {
  private queue: Promise<unknown> = Promise.resolve();
  private created = false;
  /** What is on the lens now, as last drawn without an error. */
  private shown: PageSpec | null = null;
  private wanted: PageSpec | null = null;
  private drawing = false;
  constructor(private bridge: EvenAppBridge | null) {}

  get present(): boolean {
    return !!this.bridge;
  }

  /** Draw a page. Calls made while one draw runs collapse into the latest. */
  show(spec: PageSpec): void {
    this.wanted = spec;
    if (!this.drawing) void this.drain();
  }

  /** Forget what is on the lens, so the next draw rebuilds it whole. */
  invalidate(): void {
    this.shown = null;
  }

  private async drain(): Promise<void> {
    this.drawing = true;
    try {
      while (this.wanted) {
        const spec = this.wanted;
        this.wanted = null;
        await this.draw(spec);
      }
    } finally {
      this.drawing = false;
    }
  }

  private call<T>(what: string, f: () => Promise<T>): Promise<T> {
    const run = this.queue.then(() => withTimeout(f(), CALL_MS));
    this.queue = run.catch(() => {});
    return run.catch((e) => {
      console.warn(`[glasses] ${what} failed: ${e?.message || e}`);
      throw e;
    });
  }

  private async draw(spec: PageSpec): Promise<void> {
    if (!this.bridge) return;
    const b = this.bridge;
    const same = this.shown && layoutKey(this.shown) === layoutKey(spec);
    if (same) {
      for (const t of spec.texts) {
        const old = this.shown!.texts.find((o) => o.name === t.name)!;
        if (old.content === t.content && (old.color ?? 4) === (t.color ?? 4)) continue;
        const id = spec.texts.indexOf(t) + 1;
        try {
          const ok = await this.call('textContainerUpgrade', () =>
            b.textContainerUpgrade(
              new TextContainerUpgrade({
                containerID: id,
                containerName: t.name,
                contentOffset: 0,
                contentLength: 0,
                content: textContent(t.content),
                ...(t.color !== undefined ? { textColor: t.color } : {}),
              }),
            ),
          );
          if (!ok) throw new Error('returned false');
          old.content = t.content;
          old.color = t.color;
        } catch {
          this.shown = null;
          return this.draw(spec);
        }
      }
      return;
    }

    const page = toContainers(spec);
    try {
      if (!this.created) {
        const r = await this.call('createStartUpPageContainer', () => b.createStartUpPageContainer(new CreateStartUpPageContainer(page)));
        if (r === StartUpPageCreateResult.success) {
          this.created = true;
        } else {
          // A reload in the simulator finds the start page already made:
          // a rebuild takes it over.
          console.warn(`[glasses] start page result ${r}; trying a rebuild`);
          const ok = await this.call('rebuildPageContainer', () => b.rebuildPageContainer(new RebuildPageContainer(page)));
          if (!ok) throw new Error(`start page failed (${r})`);
          this.created = true;
        }
      } else {
        const ok = await this.call('rebuildPageContainer', () => b.rebuildPageContainer(new RebuildPageContainer(page)));
        // Some firmware answers false and still draws the page (cc-g2
        // known-limitations.md); keep going, but draw it whole next time.
        if (!ok) {
          console.warn('[glasses] rebuildPageContainer returned false');
          this.shown = null;
          return;
        }
      }
      this.shown = clone(spec);
    } catch {
      this.shown = null;
    }
  }

  /** Start or stop the glasses microphone. */
  async mic(on: boolean): Promise<boolean> {
    if (!this.bridge) return false;
    const b = this.bridge;
    try {
      return await this.call('audioControl', () => (on ? b.audioControl(true, AudioInputSource.Glasses) : b.audioControl(false)));
    } catch {
      return false;
    }
  }

  /** The system's own "close this app?" question (required on the root page). */
  async exit(): Promise<void> {
    if (!this.bridge) return;
    const b = this.bridge;
    try {
      await this.call('shutDownPageContainer', () => b.shutDownPageContainer(1));
    } catch {}
  }
}

function textContent(s: string): string {
  const c = clampBytes(s, TEXT_BYTES);
  return c.length ? c : ' ';
}

function toContainers(spec: PageSpec) {
  const textObject = spec.texts.map(
    (t, i) =>
      new TextContainerProperty({
        xPosition: t.x,
        yPosition: t.y,
        width: t.w,
        height: t.h,
        containerID: i + 1,
        containerName: t.name,
        content: textContent(t.content),
        isEventCapture: t.capture ? 1 : 0,
        borderWidth: t.border ?? 0,
        borderColor: t.borderColor ?? 0,
        borderRadius: t.radius ?? 0,
        paddingLength: t.pad ?? 0,
        ...(t.color !== undefined ? { textColor: t.color } : {}),
      }),
  );
  return { containerTotalNum: textObject.length, textObject };
}

/** Everything about a page except the words in its text boxes. */
function layoutKey(spec: PageSpec): string {
  return JSON.stringify(spec.texts.map(({ content: _c, color: _k, ...rest }) => rest));
}

function clone(spec: PageSpec): PageSpec {
  return JSON.parse(JSON.stringify(spec));
}
