// What the phone panel sets: where the bridge is, its token, the folder new
// sessions start in, and the swipe direction. Kept in two places: the Even
// app's own storage (the one that survives on the phone) and the WebView's
// localStorage (the one the simulator keeps). Reads take whichever has it.
import type { EvenAppBridge } from '@evenrealities/even_hub_sdk';

declare const __DEFAULT_BRIDGE__: string;

export interface Settings {
  bridgeUrl: string;
  token: string;
  folder: string;
  swapSwipe: boolean;
  /** Draw a reply's tables as pictures with real columns (picture.ts), and
   *  the glance card with a big bold title (cardpicture.ts); off: lens text
   *  only (each table row as a text card). */
  pictures: boolean;
  /** Test mode only, from the address: refuse every change. Never stored. */
  readonly: boolean;
  /** Test mode only, from the address: show only the sessions whose title
   *  starts with these words, and the ones started from these glasses, so a
   *  real Mac's other sessions never show. Never stored. */
  only: string;
}

const KEY = 'kit-glasses-settings';

export const DEFAULTS: Settings = {
  bridgeUrl: import.meta.env.VITE_BRIDGE_URL || __DEFAULT_BRIDGE__,
  token: import.meta.env.VITE_BRIDGE_TOKEN || '',
  folder: '',
  swapSwipe: false,
  pictures: true,
  readonly: false,
  only: '',
};

let current: Settings = { ...DEFAULTS };
let host: EvenAppBridge | null = null;
const listeners = new Set<(s: Settings) => void>();

/** Values from the address (?bridge=&token=&readonly=1&only=G2&pictures=0) win for this
 *  run only, so a test can point the simulator at the mock without saving. */
function fromAddress(): Partial<Settings> {
  const q = new URLSearchParams(location.search);
  const o: Partial<Settings> = {};
  if (q.get('bridge')) o.bridgeUrl = q.get('bridge')!;
  if (q.get('token')) o.token = q.get('token')!;
  if (q.get('readonly') === '1') o.readonly = true;
  if (q.get('only')?.trim()) o.only = q.get('only')!.trim();
  if (q.get('pictures') === '0' || q.get('pictures') === '1') o.pictures = q.get('pictures') === '1';
  return o;
}

function parse(raw: string | null | undefined): Partial<Settings> {
  if (!raw) return {};
  try {
    const o = JSON.parse(raw);
    return typeof o === 'object' && o ? o : {};
  } catch {
    return {};
  }
}

export async function loadSettings(bridge: EvenAppBridge | null): Promise<Settings> {
  host = bridge;
  let stored: Partial<Settings> = parse(localStorage.getItem(KEY));
  if (host) {
    try {
      const fromHost = parse(await withTimeout(host.getLocalStorage(KEY), 2000));
      if (Object.keys(fromHost).length) stored = fromHost;
    } catch {}
  }
  delete stored.readonly;
  delete stored.only;
  current = { ...DEFAULTS, ...stored, ...fromAddress() };
  return current;
}

export function settings(): Settings {
  return current;
}

export async function saveSettings(next: Partial<Settings>): Promise<void> {
  const addr = fromAddress();
  current = { ...current, ...next };
  const { readonly: _ro, only: _only, ...keep } = current;
  const raw = JSON.stringify(keep);
  localStorage.setItem(KEY, raw);
  if (host) {
    try {
      await withTimeout(host.setLocalStorage(KEY, raw), 2000);
    } catch {}
  }
  // A value given in the address still wins for this run.
  current = { ...current, ...addr };
  listeners.forEach((f) => f(current));
}

/** Change settings for this run only, never stored (a dev-server test hook). */
export function setForRun(next: Partial<Settings>): void {
  current = { ...current, ...next };
  listeners.forEach((f) => f(current));
}

export function onSettings(f: (s: Settings) => void): () => void {
  listeners.add(f);
  return () => listeners.delete(f);
}

export function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`timed out after ${ms} ms`)), ms);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e) => {
        clearTimeout(t);
        reject(e);
      },
    );
  });
}
