// The phone panel: bridge address, token, the folder for new sessions, the
// swipe direction, whether Kit reaches the Mac, and, while the glasses
// listen, a box to type the words instead (the simulator has no glasses mic).
import type { Controller, Snapshot } from './controller';
import type { SpeakerState } from './speaker';
import { saveSettings, settings } from './settings';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export function startPanel(app: Controller): void {
  themeSwitch();
  menu();

  const url = $<HTMLInputElement>('bridge-url');
  const token = $<HTMLInputElement>('bridge-token');
  const folder = $<HTMLSelectElement>('new-folder');
  const swap = $<HTMLInputElement>('swap-swipe');
  const form = $<HTMLFormElement>('settings');
  const err = $<HTMLParagraphElement>('form-error');
  const show = $<HTMLButtonElement>('token-show');

  const s = settings();
  url.value = s.bridgeUrl;
  token.value = s.token;
  swap.checked = s.swapSwipe;
  $('readonly-chip').hidden = !s.readonly;
  $('only-chip').hidden = !s.only;
  $('only-words').textContent = `Test mode: only sessions whose name starts with ${s.only}`;
  $('mute-chip').hidden = !s.mute;

  // Read to me. The button is a tap on the page, so the phone lets the page
  // play sound from then on: Turn on sound plays a short tone, Stop reading stops.
  $('sound-button').addEventListener('click', () => {
    const sp = app.speaker;
    if (sp.state().reading) sp.stop();
    else sp.unlock(true);
  });
  app.speaker.onChange(sound);
  sound(app.speaker.state());

  show.addEventListener('click', () => {
    const on = token.type === 'password';
    token.type = on ? 'text' : 'password';
    show.textContent = on ? 'Hide' : 'Show';
    show.setAttribute('aria-pressed', String(on));
  });

  // Folder and swipe direction take effect at once; the address and token
  // on Save, since a half-typed address should not start a connection.
  folder.addEventListener('change', () => void saveSettings({ folder: folder.value }));
  swap.addEventListener('change', () => void saveSettings({ swapSwipe: swap.checked }));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = url.value.trim().replace(/\/+$/, '');
    if (!/^https?:\/\/[^\s/]+(:\d+)?$/.test(u)) {
      err.textContent = 'Enter the address as http:// then the Mac\'s address and port, for example http://192.168.1.20:8740.';
      err.hidden = false;
      url.focus();
      return;
    }
    if (!token.value.trim()) {
      err.textContent = 'Enter the token from your Mac.';
      err.hidden = false;
      token.focus();
      return;
    }
    err.hidden = true;
    url.value = u;
    await saveSettings({ bridgeUrl: u, token: token.value.trim(), folder: folder.value, swapSwipe: swap.checked });
    app.reconnect();
  });

  const typed = $<HTMLTextAreaElement>('typed-text');
  $('typed-use').addEventListener('click', () => {
    const words = typed.value.trim();
    if (!words) {
      typed.focus();
      return;
    }
    if (app.useTyped(words)) typed.value = '';
  });

  let lastFolders = '';
  app.onChange((snap) => {
    summary(snap);
    $('typed').hidden = !snap.listening;
    const key = JSON.stringify(snap.folders);
    if (key !== lastFolders) {
      lastFolders = key;
      fillFolders(folder, snap);
    }
  });
  // The age line counts up on its own.
  setInterval(() => summary(app.snapshot()), 5000);
}

function sound(s: SpeakerState): void {
  const chip = $('sound-chip');
  const words = $('sound-words');
  const button = $<HTMLButtonElement>('sound-button');
  chip.hidden = true;
  if (s.reading) {
    chip.hidden = false;
    chip.className = 'chip';
    words.textContent = `${s.reading.loading ? 'Getting the sound for' : 'Reading'}: ${s.reading.title}`;
    button.textContent = 'Stop reading';
    return;
  }
  if (s.blocked) {
    chip.hidden = false;
    chip.className = 'chip warn';
    words.textContent = 'The phone did not let Kit play the sound. Tap Turn on sound.';
  }
  button.textContent = s.on ? 'Test sound' : 'Turn on sound';
}

function summary(s: Snapshot): void {
  const chip = $('state-chip');
  const words = $('state-words');
  const line = $('state-line');
  const age = $('state-age');
  const set = (kind: 'good' | 'warn' | 'bad' | 'info', text: string) => {
    chip.className = `chip ${kind === 'info' ? '' : kind}`.trim();
    words.textContent = text;
  };
  switch (s.conn) {
    case 'ok': {
      set('good', 'Connected to your Mac');
      const need = s.needYou === 0 ? 'Nothing needs you' : `${s.needYou} need${s.needYou === 1 ? 's' : ''} you`;
      line.textContent = `${need} · ${s.sessions} session${s.sessions === 1 ? '' : 's'}${s.version ? ` · bridge ${s.version}` : ''}${s.live ? '' : ' · updates every 5 s'}`;
      break;
    }
    case 'connecting':
      set('info', 'Connecting to your Mac');
      line.textContent = settings().bridgeUrl;
      break;
    case 'unset':
      set('warn', 'Not set up');
      line.textContent = 'Enter the bridge address and token from your Mac, then Save and connect.';
      break;
    case 'auth':
      set('bad', 'Token not accepted');
      line.textContent = 'The bridge did not accept this token. Check it on your Mac.';
      break;
    case 'down':
      set('bad', "Can't reach your Mac");
      line.textContent = `${s.error}. Kit tries again every 10 s.`;
      break;
  }
  const parts: string[] = [];
  if (s.conn !== 'unset' && s.checkedAt) parts.push(`Checked ${ago(s.checkedAt)}`);
  if (s.conn !== 'unset' && s.downSince) parts.push(`no contact for ${ago(s.downSince, true)}`);
  age.textContent = parts.join(', ');
}

function ago(t: number, bare = false): string {
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  const words = sec < 5 ? (bare ? 'a moment' : 'just now') : sec < 60 ? `${sec} s` : `${Math.floor(sec / 60)} min`;
  return bare || sec < 5 ? words : `${words} ago`;
}

function fillFolders(sel: HTMLSelectElement, s: Snapshot): void {
  const want = settings().folder;
  sel.textContent = '';
  if (!s.folders.length) {
    const o = document.createElement('option');
    o.value = want;
    o.textContent = want ? want : 'The bridge picks the folder';
    sel.append(o);
    sel.disabled = !want;
    $('folder-help').textContent = 'The folders come from your Mac once Kit connects.';
    return;
  }
  sel.disabled = false;
  for (const f of s.folders) {
    const o = document.createElement('option');
    o.value = f.path;
    o.textContent = f.label;
    sel.append(o);
  }
  sel.value = s.folders.some((f) => f.path === want) ? want : s.folders[0].path;
  $('folder-help').textContent = 'A session you start from the glasses works in this folder.';
}

// ---------- the light, auto and dark switch ----------

const THEME_KEY = 'kit-glasses-theme';

function themeSwitch(): void {
  const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-theme-choice]'));
  const media = matchMedia('(prefers-color-scheme: dark)');
  const apply = () => {
    const t = localStorage.getItem(THEME_KEY) || 'auto';
    const dark = t === 'dark' || (t === 'auto' && media.matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.themeChoice === t)));
  };
  buttons.forEach((b) =>
    b.addEventListener('click', () => {
      localStorage.setItem(THEME_KEY, b.dataset.themeChoice!);
      apply();
    }),
  );
  media.addEventListener('change', apply);
  apply();
}

function menu(): void {
  const bar = document.querySelector<HTMLElement>('.topbar')!;
  const btn = bar.querySelector<HTMLButtonElement>('.menu-btn')!;
  btn.addEventListener('click', () => {
    const open = bar.dataset.menu !== 'open';
    bar.dataset.menu = open ? 'open' : 'closed';
    btn.setAttribute('aria-expanded', String(open));
  });
}
