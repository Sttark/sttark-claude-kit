// The lens driver. Screens describe a page (text boxes; a list is a text box
// too, see screens.ts); this draws it with as little as possible: a
// whole-page rebuild only when the layout changes, otherwise an in-place
// text update, which does not flicker.
//
// Every SDK call goes through one queue, one at a time, each with a time
// limit (a Bluetooth call that never answers must not freeze the lens). A
// call that fails makes the next draw a full rebuild.
//
// A page can also hold pictures (picture.ts): image boxes of at most 288 x
// 144, 4 to a page. A new page shows them empty; then each picture goes,
// one at a time, at least 100 ms apart (the SDK holds a send that comes
// sooner until the next one), and only when it differs from what shows.
import {
  AudioInputSource,
  CreateStartUpPageContainer,
  ImageContainerProperty,
  ImageRawDataUpdate,
  ImageRawDataUpdateResult,
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

export interface ImageBox {
  name: string; // at most 16 characters, unique on the page
  x: number;
  y: number;
  w: number; // 20 to 288
  h: number; // 20 to 144
  /** What the picture shows: a picture is sent again only when this changes.
   *  '' is an empty (black) picture, which a new page already shows. */
  key: string;
  /** The picture as PNG bytes, exactly w x h. */
  data?: () => Promise<Uint8Array>;
  /** What the picture is part of ("card"), for onPictures. */
  group?: string;
}

/** How a page's pictures went: all sent (`ok`), and how long the page took
 *  to show, from the start of its draw to the last picture. */
export interface PictureResult {
  group: string;
  ok: boolean;
  ms: number;
  sent: number;
}

export interface PageSpec {
  texts: TextBox[];
  images?: ImageBox[];
}

const CALL_MS = 6000;
/** The least time between two picture sends (SDK 0.0.14+ holds a sooner one). */
const IMAGE_GAP_MS = 110;

export class Glasses {
  private queue: Promise<unknown> = Promise.resolve();
  private created = false;
  /** What is on the lens now, as last drawn without an error. */
  private shown: PageSpec | null = null;
  private wanted: PageSpec | null = null;
  private drawing = false;
  private lastImageAt = 0;
  /** When the page now on the lens started to draw, while its pictures are
   *  still on the way: a newer draw of the same page, which takes over
   *  their sending, counts its time from there. */
  private drawnAt: number | null = null;
  /** Told when a page's pictures are all sent, or one fails. */
  onPictures: ((r: PictureResult) => void) | null = null;
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
      return this.sendImages(spec, this.drawnAt ?? performance.now());
    }

    const page = toContainers(spec);
    const t0 = performance.now();
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
      this.drawnAt = spec.images?.length ? t0 : null;
      // A new page shows its image boxes empty.
      for (const im of this.shown.images ?? []) im.key = '';
    } catch {
      this.shown = null;
      return;
    }
    if (!spec.images?.length) console.log(`[glasses] page rebuilt in ${Math.round(performance.now() - t0)} ms`);
    return this.sendImages(spec, t0);
  }

  /** Send the pictures that differ from what shows, one at a time. Stops
   *  when a newer page waits: its draw sends what is still out of date. */
  private async sendImages(spec: PageSpec, t0: number): Promise<void> {
    const b = this.bridge;
    const images = spec.images ?? [];
    if (!b || !images.length) return;
    const took: number[] = [];
    const group = images.find((im) => im.group)?.group ?? '';
    let failed = false;
    const tell = (ok: boolean) => this.onPictures?.({ group, ok, ms: Math.round(performance.now() - t0), sent: took.length });
    for (const [i, im] of images.entries()) {
      const old = this.shown?.images?.find((o) => o.name === im.name);
      if (!old || old.key === im.key || !im.data) continue;
      if (this.wanted) {
        if (took.length) console.log(`[glasses] pictures ${took.length} sent (${took.join(', ')} ms each), then a newer page`);
        return;
      }
      let bytes: Uint8Array;
      try {
        bytes = await im.data();
      } catch (e) {
        console.warn(`[glasses] picture ${im.name} not drawn: ${(e as Error)?.message || e}`);
        failed = true;
        continue;
      }
      const wait = this.lastImageAt + IMAGE_GAP_MS - performance.now();
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      const t1 = (this.lastImageAt = performance.now());
      try {
        const r = await this.call('updateImageRawData', () =>
          b.updateImageRawData(new ImageRawDataUpdate({ containerID: spec.texts.length + i + 1, containerName: im.name, imageData: bytes })),
        );
        if (!ImageRawDataUpdateResult.isSuccess(ImageRawDataUpdateResult.normalize(r))) throw new Error(String(r));
        old.key = im.key;
        took.push(Math.round(performance.now() - t1));
      } catch (e) {
        console.warn(`[glasses] picture ${im.name} not shown: ${(e as Error)?.message || e}`);
        this.shown = null;
        tell(false);
        return;
      }
    }
    this.drawnAt = null;
    if (took.length) console.log(`[glasses] pictures ${took.length} sent (${took.join(', ')} ms each), page shown in ${Math.round(performance.now() - t0)} ms${group ? ` (${group})` : ''}`);
    if (took.length || failed) tell(!failed);
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
  const imageObject = (spec.images ?? []).map(
    (im, i) =>
      new ImageContainerProperty({
        xPosition: im.x,
        yPosition: im.y,
        width: im.w,
        height: im.h,
        containerID: textObject.length + i + 1,
        containerName: im.name,
      }),
  );
  return { containerTotalNum: textObject.length + imageObject.length, textObject, ...(imageObject.length ? { imageObject } : {}) };
}

/** Everything about a page except the words in its text boxes and what its pictures show. */
function layoutKey(spec: PageSpec): string {
  return JSON.stringify([
    spec.texts.map(({ content: _c, color: _k, ...rest }) => rest),
    (spec.images ?? []).map(({ key: _k, data: _d, ...rest }) => rest),
  ]);
}

function clone(spec: PageSpec): PageSpec {
  return JSON.parse(JSON.stringify(spec));
}
