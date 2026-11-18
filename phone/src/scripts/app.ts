// The phone pages in the browser. The server drew the page from the last
// snapshots and put what it drew from in #kit-state; this opens /live
// (phone/asyncapi.yaml), keeps that data up to date, and draws the page
// again in place with the same code (view/render.ts). A tap on a control
// sends one action; its button says "Sending..." until the server answers,
// and the page shows only the answer the server sent: never a success the
// Mac did not confirm. Also: the ⓘ notes, search, Remove's confirm, the
// light / auto / dark choice, and forms that ask first. And Web Push: every
// page registers the service worker (public/sw.js) and puts the Needs you
// count on the app icon's badge; Menu turns this phone's notices on and off.
//
// It knows nothing of how the socket is served: only the messages.
import { draw, drawList, type View } from '../view/render.ts';
import {
  NO_SERVER_WORDS, emptyUi, findArchived, findRow, needsCount, noticesOf, periodOf, usageQuery,
  type Kit, type MacInfo, type Notices, type Reason, type Result, type Ui, type UsagePick, type UsageView,
} from '../view/model.ts';
import { dayKey } from '../view/time.ts';

// ---------- light / auto / dark, on every page ----------

const THEME_KEY = 'sttark-theme';
const systemDark = matchMedia('(prefers-color-scheme: dark)');
const themeMode = () => {
  let m: string | null = null;
  try {
    m = localStorage.getItem(THEME_KEY);
  } catch {}
  return m === 'light' || m === 'dark' ? m : 'system';
};
function applyTheme() {
  const m = themeMode();
  document.documentElement.dataset.theme = m === 'dark' || (m === 'system' && systemDark.matches) ? 'dark' : 'light';
  for (const b of document.querySelectorAll<HTMLButtonElement>('#theme-toggle button')) b.setAttribute('aria-pressed', String(b.dataset.mode === m));
}
systemDark.addEventListener('change', () => themeMode() === 'system' && applyTheme());
applyTheme();

// A form with data-confirm asks first; the question says what happens.
document.addEventListener('submit', (ev) => {
  const form = ev.target as HTMLFormElement;
  const q = (ev as SubmitEvent).submitter?.getAttribute('data-confirm') ?? form.getAttribute('data-confirm');
  if (q && !confirm(q)) ev.preventDefault();
});

// ---------- the page's data ----------

const stateEl = document.getElementById('kit-state');
const viewEl = document.getElementById('view');
const started = stateEl && viewEl ? (JSON.parse(stateEl.textContent || '{}') as { kit: Kit; view: View; ui?: Partial<Ui> }) : null;

if (started && viewEl) run(started.kit, started.view, { ...emptyUi(), ...started.ui }, viewEl);
else {
  // Pages without the Kit's data (sign-in, errors): only the theme above.
  document.addEventListener('click', (ev) => {
    const b = (ev.target as Element).closest<HTMLButtonElement>('#theme-toggle button');
    if (!b) return;
    try {
      localStorage.setItem(THEME_KEY, b.dataset.mode!);
    } catch {}
    applyTheme();
  });
}

function run(kit: Kit, view: View, ui: Ui, root: HTMLElement) {
  const base = kit.base;
  const now = () => Math.floor(Date.now() / 1000);
  kit.now = now();

  // ---------- drawing ----------

  let queued = false;
  let held = false;
  /** The Needs you count on the app icon (a Home Screen app, once notices
   *  are allowed; a browser tab ignores it). */
  let badgeWas = -1;
  function appBadge(n: number) {
    if (n === badgeWas || !('setAppBadge' in navigator)) return;
    badgeWas = n;
    (n > 0 ? navigator.setAppBadge(n) : navigator.clearAppBadge()).catch(() => {});
  }
  /** Draw again on the next frame. While someone is in a field or a
   *  dropdown, only the list under a search field is drawn, so nothing
   *  moves under their hand; the rest waits until they leave it. */
  function redraw() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const a = document.activeElement;
      if (a && root.contains(a) && (a.tagName === 'SELECT' || a.tagName === 'INPUT')) {
        if (a.tagName === 'INPUT') drawListOnly();
        held = true;
        return;
      }
      held = false;
      drawAll();
    });
  }
  function drawAll() {
    kit.now = now();
    const focusKey = (document.activeElement as HTMLElement | null)?.closest<HTMLElement>('[data-k]')?.dataset.k;
    const d = draw(view, kit, ui);
    root.innerHTML = d.html;
    document.title = `${d.title} · Claude Kit · Sttark`;
    for (const t of document.querySelectorAll<HTMLAnchorElement>('.tabbar a[data-tab]')) {
      if (t.dataset.tab === d.tab) t.setAttribute('aria-current', 'page');
      else t.removeAttribute('aria-current');
    }
    const n = needsCount(kit);
    const badge = document.querySelector<HTMLElement>('[data-badge]');
    if (badge) {
      badge.textContent = String(n);
      badge.hidden = !n;
      badge.setAttribute('aria-label', `${n} need you`);
    }
    appBadge(n);
    applyTheme();
    if (focusKey) root.querySelector<HTMLElement>(`[data-k="${CSS.escape(focusKey)}"]`)?.focus({ preventScroll: true });
  }
  function drawListOnly() {
    kit.now = now();
    const list = root.querySelector('#list');
    const html = drawList(view, kit, ui);
    if (list && html !== null) list.innerHTML = html;
  }
  root.addEventListener('focusout', () => setTimeout(() => held && redraw(), 0));
  // Times in words ("22 min") move on by themselves.
  setInterval(redraw, 30_000);

  // ---------- /live ----------

  let ws: WebSocket | null = null;
  let open = false;
  let tries = 0;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let lostAt: number | null = null;
  const conn = document.getElementById('conn');
  const visible = () => document.visibilityState === 'visible';
  const sendMsg = (event: string, payload: unknown) => ws?.send(JSON.stringify({ event, success: true, payload }));

  // After 4 seconds without the server, the page says so: a short drop
  // while it connects again says nothing.
  setInterval(() => {
    if (conn) conn.hidden = open || lostAt === null || Date.now() - lostAt < 4000;
  }, 1000);

  function connect() {
    clearTimeout(retry);
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const url = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${base}/live`;
    lostAt ??= Date.now();
    try {
      ws = new WebSocket(url);
    } catch {
      return later();
    }
    ws.addEventListener('open', () => {
      open = true;
      tries = 0;
      lostAt = null;
      if (conn) conn.hidden = true;
      sendMsg('hello', { visible: visible() });
      if (view.page === 'archived' || view.page === 'archived-item') sendMsg('open_archived', {});
      askUsage();
    });
    ws.addEventListener('message', (ev) => {
      let m: { event?: string; success?: boolean; payload?: any };
      try {
        m = JSON.parse(String(ev.data));
      } catch {
        return;
      }
      onMessage(m.event ?? '', m.payload ?? {});
    });
    ws.addEventListener('close', () => {
      if (open) lostAt = Date.now();
      open = false;
      ws = null;
      later();
    });
  }
  function later() {
    if (!visible()) return; // connects again when the page shows
    const wait = Math.min(30, 2 ** tries++) * 1000;
    retry = setTimeout(connect, wait);
  }
  document.addEventListener('visibilitychange', () => {
    if (open) sendMsg('visible', { visible: visible() });
    else if (visible()) {
      tries = 0;
      connect();
    }
    if (visible()) {
      askUsage();
      redraw();
    }
  });

  // ---------- Usage by session ----------

  const usageNow = (): UsageView => (view.page === 'usage' && view.usage ? view.usage : { pick: '7d', from: null, to: null, all: false });
  /** The Usage tab asks each Mac for its list for the period it shows: when
   *  it opens or shows again, when the period changes, and every minute. A
   *  Mac that does not answer in 15 seconds is said so. */
  function askUsage() {
    if (view.page !== 'usage' || !open) return;
    const period = periodOf(usageNow());
    if (!period) return;
    sendMsg('open_usage', { period });
    ui.usageAsked ??= now();
    setTimeout(redraw, 15_500);
  }
  setInterval(() => {
    if (visible()) askUsage();
  }, 60_000);
  function setUsage(u: UsageView) {
    if (view.page !== 'usage') return;
    const changed = periodOf(u) !== periodOf(usageNow());
    view = { page: 'usage', usage: u };
    history.replaceState(history.state, '', `${base}/usage${usageQuery(u)}`);
    if (changed) {
      ui.usageAsked = null;
      askUsage();
    }
    drawAll();
  }

  function onMessage(event: string, p: any) {
    switch (event) {
      case 'macs': {
        const macs = (p.macs ?? []) as MacInfo[];
        const ids = new Set(macs.map((m) => m.id));
        for (const id of Object.keys(kit.snaps)) if (!ids.has(id)) delete kit.snaps[id];
        for (const id of Object.keys(kit.archived)) if (!ids.has(id)) delete kit.archived[id];
        for (const id of Object.keys(kit.usage ?? {})) if (!ids.has(id)) delete kit.usage![id];
        kit.macs = macs.map((m) => ({ ...m, name: kit.snaps[m.id]?.mac.name ?? m.name }));
        break;
      }
      case 'snapshot':
        if (!p.mac || !p.snapshot) return;
        kit.snaps[p.mac] = p.snapshot;
        for (const m of kit.macs) if (m.id === p.mac) Object.assign(m, { name: p.snapshot.mac.name, kit: p.snapshot.mac.kit });
        break;
      case 'archived':
        if (!p.mac) return;
        kit.archived[p.mac] = p.items ?? [];
        break;
      case 'usage':
        if (!p.mac || !p.list) return;
        kit.usage = { ...kit.usage, [p.mac]: p.list };
        break;
      case 'action_result':
        answer(p.id, p.reason as Reason, p.words ?? '');
        return;
      case 'record': {
        const cse = view.page === 'session' || view.page === 'archived-item' ? view.cse : null;
        if (!cse || p.cse !== cse) return;
        kit.records.unshift({ at: p.at, mac: p.mac, cse: p.cse, act: p.act, reason: p.reason, words: p.words });
        break;
      }
      case 'error':
        // The server refused what this page sent: the action that waits
        // for an answer did nothing.
        if (pending) answer(pending.id, 'bad', p.words ?? '');
        return;
      default:
        return;
    }
    redraw();
  }

  // ---------- actions ----------

  type Pending = { id: string; key: string; scope: string; sec: Result['sec']; timer: ReturnType<typeof setTimeout> };
  let pending: Pending | null = null;

  function answer(id: string, reason: Reason, words: string) {
    if (!pending || pending.id !== id) return;
    clearTimeout(pending.timer);
    ui.sending = null;
    ui.result = { scope: pending.scope, sec: pending.sec, reason, words };
    pending = null;
    drawAll();
  }

  /** Sends one action for the session (or archived session) on this page. */
  function act(key: string, sec: Result['sec'], name: string, args: Record<string, unknown>) {
    if (ui.sending) return;
    const cse = view.page === 'session' || view.page === 'archived-item' ? view.cse : '';
    const mac = findRow(kit, cse)?.mac.id ?? findArchived(kit, cse)?.mac.id;
    if (!mac) return;
    ui.result = null;
    if (!open || !ws) {
      ui.result = { scope: cse, sec, reason: 'offline', words: NO_SERVER_WORDS };
      drawAll();
      return;
    }
    const id = `act-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    // The server answers in 20 seconds at most (timeout); this is only
    // for a server that never answers at all.
    const timer = setTimeout(() => answer(id, 'timeout', ''), 25_000);
    pending = { id, key, scope: cse, sec, timer };
    ui.sending = key;
    sendMsg('action', { id, mac, act: name, args, basis: kit.snaps[mac]?.at ?? now() });
    drawAll();
  }

  const rowHere = () => (view.page === 'session' ? findRow(kit, view.cse)?.row : undefined);

  // Custom's Show: the days picked, in the address, and their list.
  root.addEventListener('submit', (ev) => {
    const form = ev.target as HTMLFormElement;
    if (form.id !== 'bys-range') return;
    ev.preventDefault();
    let from = (form.elements.namedItem('from') as HTMLInputElement | null)?.value ?? '';
    let to = (form.elements.namedItem('to') as HTMLInputElement | null)?.value ?? '';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) return;
    if (from > to) [from, to] = [to, from];
    (document.activeElement as HTMLElement | null)?.blur();
    setUsage({ pick: 'custom', from, to, all: false });
  });

  root.addEventListener('change', (ev) => {
    const sel = ev.target as HTMLSelectElement;
    if (sel.id !== 'limit-sel') return;
    const row = rowHere();
    if (!row) return;
    const [mode, at] = sel.value.split(':');
    act('limit', 'limit', 'set_limit', { cse: row.cse, sid: row.sid, mode, at: mode === 'hold' ? Number(at) : null });
  });

  root.addEventListener('input', (ev) => {
    const input = ev.target as HTMLInputElement;
    if (input.id !== 'sq' && input.id !== 'aq') return;
    ui.q = input.value;
    drawListOnly();
    const url = new URL(location.href);
    if (ui.q) url.searchParams.set('q', ui.q);
    else url.searchParams.delete('q');
    history.replaceState(history.state, '', url);
  });

  const setQuery = (q: string, find: boolean) => {
    ui.q = q;
    ui.find = find;
    const url = new URL(location.href);
    url.searchParams.delete('q');
    url.searchParams.delete('find');
    if (find) url.searchParams.set('find', '1');
    history.replaceState(history.state, '', url);
  };

  document.addEventListener('click', (ev) => {
    const target = ev.target as Element;
    // A tap on the tab you are on goes back to the top of its list.
    const tab = target.closest<HTMLAnchorElement>('.tabbar a[data-tab]');
    if (tab && tab.getAttribute('aria-current') === 'page' && (view.page === 'sessions' || view.page === 'archived' || view.page === 'usage')) {
      ev.preventDefault();
      scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    const theme = target.closest<HTMLButtonElement>('#theme-toggle button');
    if (theme) {
      try {
        localStorage.setItem(THEME_KEY, theme.dataset.mode!);
      } catch {}
      applyTheme();
      return;
    }
    const el = target.closest<HTMLElement>('[data-act]');
    if (!el || el.tagName === 'SELECT') return;
    if (el.getAttribute('aria-disabled') === 'true') {
      ev.preventDefault();
      return;
    }
    const row = rowHere();
    switch (el.dataset.act) {
      case 'noop':
        ev.preventDefault();
        return;
      case 'info': {
        const k = el.dataset.key!;
        ui.notes = ui.notes.includes(k) ? ui.notes.filter((x) => x !== k) : [...ui.notes, k];
        drawAll();
        return;
      }
      case 'clear-result':
        ui.result = null;
        drawAll();
        return;
      case 'stop':
        if (row) act(`stop:${el.dataset.wait}`, 'waits', 'stop_waits', { waits: [el.dataset.wait] });
        return;
      case 'stopall':
        if (row) act('stopall', 'waits', 'stop_waits', { waits: row.waits.map((w) => w.id) });
        return;
      case 'bring':
        if (row?.waits[0]) act('bring', 'waits', 'bring_back', { wait: row.waits[0].id });
        return;
      case 'level':
        if (row) act(`lvl:${el.dataset.level}`, 'effort', 'set_level', { cse: row.cse, level: el.dataset.level });
        return;
      case 'auto':
        if (row?.session) act('auto', 'effort', 'set_auto', { cse: row.cse, on: row.session.manual });
        return;
      case 'alerts':
        if (row) act('alerts', 'alerts', 'set_alerts', { cse: row.cse, alerts: row.alerts === false });
        return;
      case 'unarchive':
        if (view.page === 'archived-item') act('unarchive', 'top', 'unarchive', { cse: view.cse });
        return;
      case 'period': {
        // Custom starts at the days the list shows now (else the 7 days to
        // today), and asks for them at once; Show asks for other days.
        const pick = el.dataset.pick as UsagePick;
        const u = usageNow();
        if (pick === u.pick) return;
        if (pick !== 'custom') return setUsage({ pick, from: null, to: null, all: false });
        const shown = Object.values(kit.usage ?? {}).find((l) => l.period === periodOf(u));
        const first = kit.macs.find((m) => kit.snaps[m.id]);
        const tz = first ? kit.snaps[first.id].mac.tz : 'America/New_York';
        return setUsage({ pick, from: shown?.from ?? dayKey(now() - 6 * 86400, tz), to: shown?.to ?? dayKey(now(), tz), all: false });
      }
      case 'usage-all':
        setUsage({ ...usageNow(), all: !usageNow().all });
        return;
      case 'search':
        if (view.page !== 'sessions') return; // the link opens Sessions with search
        ev.preventDefault();
        setQuery(ui.find ? '' : ui.q, !ui.find);
        drawAll();
        if (ui.find) root.querySelector<HTMLInputElement>('#sq')?.focus();
        return;
      case 'close-search':
        setQuery('', false);
        drawAll();
        return;
      case 'remove':
        ui.confirm = el.dataset.mac ?? null;
        drawAll();
        root.querySelector<HTMLElement>(`#rm-${CSS.escape(ui.confirm ?? '')} .btn.ghost`)?.focus();
        return;
      case 'remove-no':
        ui.confirm = null;
        drawAll();
        return;
      case 'back':
      case 'menu-close': {
        // Back to the page before at the same scroll place, when it is the
        // one this link goes to (or, for Close, any page of this app).
        const href = (el as HTMLAnchorElement).href;
        const ref = document.referrer;
        const same = ref && new URL(ref).origin === location.origin && new URL(ref).pathname.startsWith(base + '/');
        if (same && (el.dataset.act === 'menu-close' || ref.split('#')[0] === href)) {
          ev.preventDefault();
          history.back();
        }
        return;
      }
    }
  });

  // ---------- Web Push: the service worker, the badge, Menu > Notices ----------

  const canPush = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  let worker: Promise<ServiceWorkerRegistration> | null = null;
  if ('serviceWorker' in navigator) {
    worker = navigator.serviceWorker.register(`${base}/sw.js`, { scope: `${base}/` }).then(() => navigator.serviceWorker.ready);
    worker.catch(() => {});
    // A tap on a notice while this page is open: the service worker asks
    // this page to open the session's page when it cannot itself.
    navigator.serviceWorker.addEventListener('message', (ev) => {
      const d = ev.data as { kit?: string; url?: string } | null;
      if (d?.kit !== 'open' || typeof d.url !== 'string') return;
      const u = new URL(d.url, location.href);
      if (u.origin === location.origin && u.pathname.startsWith(`${base}/`)) location.assign(u.href);
    });
  }

  const ua = navigator.userAgent;
  const ipad = /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const ios = ipad || /iPhone|iPod/.test(ua);
  const device: Notices['device'] = ipad ? 'iPad' : ios ? 'iPhone' : 'phone';
  const installed = matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true;

  function setNotices(n: Partial<Notices>) {
    ui.notices = { ...noticesOf(kit, ui), device, ...n };
    drawAll();
  }

  async function post(path: string, body: unknown): Promise<{ ok: boolean; status: number; body: any }> {
    try {
      const r = await fetch(base + path, { method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
      let b: any = null;
      try {
        b = await r.json();
      } catch {}
      return { ok: r.ok, status: r.status, body: b };
    } catch {
      return { ok: false, status: 0, body: null };
    }
  }
  const failed = (r: { status: number; body: any }) =>
    r.status === 0 ? 'Your phone is not connected to the server. Try again when it is back.' : String(r.body?.words || 'The server did not take it. Try again.');

  /** Does this subscription use the server's key? A new key on the server
   *  needs a new subscription. */
  function sameKey(sub: PushSubscription, key: string): boolean {
    const have = sub.options?.applicationServerKey;
    if (!have) return true;
    const a = new Uint8Array(have);
    const b = Uint8Array.from(atob(key.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (key.length % 4)) % 4)), (c) => c.charCodeAt(0));
    return a.length === b.length && a.every((x, i) => x === b[i]);
  }

  /** What this phone can do, and what the server knows of the subscription
   *  its browser holds. Opening Menu changes nothing. */
  async function checkNotices() {
    const key = kit.notices?.key;
    if (!key) return setNotices({ state: 'not_set_up', since: null });
    if (!canPush || !worker) return setNotices({ state: ios && !installed ? 'install' : 'unsupported', since: null });
    if (Notification.permission === 'denied') return setNotices({ state: 'blocked', since: null });
    let sub: PushSubscription | null = null;
    try {
      sub = await (await worker).pushManager.getSubscription();
    } catch {
      return;
    }
    if (!sub) return setNotices({ state: 'off', since: null });
    const r = await post('/api/push/state', { endpoint: sub.endpoint });
    if (!r.ok) return; // the server's own view stays
    setNotices({ state: r.body.known && r.body.on ? 'on' : 'off', since: r.body.known ? r.body.since : null });
  }

  /** On: the phone's permission (asked straight from the tap, as an iPhone
   *  needs), a subscription with the server's key, and the server keeps it. */
  async function turnOn(asked: Promise<NotificationPermission>) {
    const key = kit.notices?.key;
    if (!key || !worker) return;
    setNotices({ state: 'turning_on', problem: null });
    const permission = await asked.catch(() => Notification.permission);
    if (permission !== 'granted') return setNotices(permission === 'denied' ? { state: 'blocked', since: null } : { state: 'off', problem: 'The phone did not allow notices. Tap the switch again and choose Allow.' });
    try {
      const reg = await worker;
      let sub = await reg.pushManager.getSubscription();
      if (sub && !sameKey(sub, key)) {
        await sub.unsubscribe().catch(() => false);
        sub = null;
      }
      sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      const r = await post('/api/push/subscribe', sub.toJSON());
      if (!r.ok) return setNotices({ state: 'off', problem: failed(r) });
      setNotices({ state: r.body.on ? 'on' : 'off', since: r.body.since, problem: null });
    } catch {
      if (Notification.permission === 'denied') return setNotices({ state: 'blocked', since: null });
      setNotices({ state: 'off', problem: "The phone's push service did not answer. Try again." });
    }
  }

  async function turnOff() {
    setNotices({ state: 'turning_off', problem: null });
    let sub: PushSubscription | null = null;
    try {
      if (worker) sub = await (await worker).pushManager.getSubscription();
    } catch {}
    if (!sub) return setNotices({ state: 'off', since: null });
    const r = await post('/api/push/notices', { endpoint: sub.endpoint, on: false });
    if (r.ok) return setNotices({ state: r.body.on ? 'on' : 'off', since: r.body.since });
    if (r.status === 404) return setNotices({ state: 'off', since: null });
    setNotices({ state: 'on', problem: failed(r) });
  }

  document.addEventListener('click', (ev) => {
    const el = (ev.target as Element).closest<HTMLElement>('[data-act="notices"], [data-act="notices-clear"]');
    if (!el || view.page !== 'menu') return;
    if (el.dataset.act === 'notices-clear') {
      setNotices({ problem: null });
      return;
    }
    const n = noticesOf(kit, ui);
    if (n.state === 'off') {
      // The permission question comes straight from the tap: an iPhone asks
      // only then.
      const asked = canPush && Notification.permission === 'default' ? Notification.requestPermission() : Promise.resolve(canPush ? Notification.permission : 'denied');
      void turnOn(asked);
    } else if (n.state === 'on') void turnOff();
  });

  if (view.page === 'menu') void checkNotices();

  connect();
}
