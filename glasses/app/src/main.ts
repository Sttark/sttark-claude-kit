import './styles/sttark-shared.css';
import './styles/panel.css';
import { waitForEvenAppBridge, type EvenAppBridge } from '@evenrealities/even_hub_sdk';
import { Bridge } from './api';
import { Controller } from './controller';
import { toInput } from './events';
import { Glasses } from './glasses';
import { startPanel } from './panel';
import { loadSettings, settings, withTimeout } from './settings';

/** The Even app and the simulator put a Flutter handler in the page; a plain
 *  browser has none, and then only the panel works. */
async function host(): Promise<EvenAppBridge | null> {
  const w = window as unknown as { flutter_inappwebview?: unknown };
  for (let i = 0; i < 10 && !w.flutter_inappwebview; i++) await new Promise((r) => setTimeout(r, 100));
  if (!w.flutter_inappwebview) return null;
  try {
    return await withTimeout(waitForEvenAppBridge(), 5000);
  } catch {
    return null;
  }
}

async function boot(): Promise<void> {
  const even = await host();
  await loadSettings(even);
  const bridge = new Bridge(() => {
    const s = settings();
    return { url: s.bridgeUrl, token: s.token, readonly: s.readonly };
  });
  const lens = new Glasses(even);
  const app = new Controller(bridge, lens);
  if (even) {
    even.onEvenHubEvent((ev) => {
      const input = toInput(ev);
      if (input) app.handle(input);
    });
  }
  startPanel(app);
  // Read to me: many phones let a page play sound only after a tap on the
  // page itself. The first tap anywhere on the phone page turns sound on
  // (silently); a glasses gesture never counts as such a tap.
  const soundOn = () => {
    if (!app.speaker.state().on) app.speaker.unlock();
  };
  document.addEventListener('touchend', soundOn, { capture: true });
  document.addEventListener('click', soundOn, { capture: true });
  // Dev server only: words a script types in the phone's box, so a test can
  // reply without keys (scripts/e2e.mjs; vite.config.ts, kitTyped).
  if (import.meta.hot) {
    import.meta.hot.on('kit:typed', (d: { text?: string }) => {
      const used = app.useTyped(String(d?.text || ''));
      console.log(`[kit] typed words ${used ? 'used' : 'not used: the glasses are not listening'}`);
    });
  }
  app.start();
  console.log(`[kit] ready (${even ? 'glasses' : 'panel only'})`);
}

void boot();
