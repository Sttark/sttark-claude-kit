// Claude Kit's service worker (phone/DESIGN.md section 5), scoped to the
// app's own path (BASE_PATH): every page registers it (src/scripts/app.ts).
// It only shows Needs you notices; it keeps no copy of any page and never
// answers a request, so the pages always come from the server.
//
//   push              one notice: the title and one line the server sent, with
//                     the tag needs-<session>, so a newer notice for the same
//                     session replaces the old one; and the app icon's badge
//                     with the Needs you count.
//   notificationclick the One session page, in the app's window when it is
//                     open, else in a new one.
//   pushsubscriptionchange
//                     the browser replaced the subscription: the new one goes
//                     to the server, which keeps this phone's on or off.
'use strict';

const SCOPE = new URL(self.registration.scope);
const BASE = SCOPE.pathname.replace(/\/$/, '');
const ICON = `${BASE}/icon-192.png?v=2`;
const BADGE = `${BASE}/notice-badge.png?v=2`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

/** Is this address a page of this app (under its scope)? On
 *  building.sttark.com/kit, Building's own pages share the origin and are not. */
function inScope(url) {
  try {
    const u = new URL(url, SCOPE);
    return u.origin === SCOPE.origin && (u.pathname + '/').startsWith(SCOPE.pathname);
  } catch {
    return false;
  }
}

/** A page of this app, or the app's home: never another site. */
function pageOf(url) {
  return url && inScope(url) ? new URL(url, SCOPE).href : SCOPE.href;
}

function setBadge(n) {
  const nav = self.navigator;
  if (!Number.isInteger(n) || !nav || !nav.setAppBadge) return Promise.resolve();
  return (n > 0 ? nav.setAppBadge(n) : nav.clearAppBadge()).catch(() => {});
}

self.addEventListener('push', (event) => {
  let d = {};
  try {
    d = event.data ? event.data.json() : {};
  } catch {
    d = {};
  }
  const title = typeof d.title === 'string' && d.title ? d.title : 'Claude needs you';
  const options = {
    body: typeof d.body === 'string' ? d.body : '',
    tag: typeof d.tag === 'string' && d.tag ? d.tag : 'needs',
    renotify: true,
    icon: ICON,
    badge: BADGE,
    data: { url: pageOf(d.url) },
  };
  // Every push shows a notice: a phone may stop sending pushes to a web app
  // that gets one and shows nothing.
  event.waitUntil(Promise.all([self.registration.showNotification(title, options), setBadge(d.badge)]));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = pageOf(event.notification.data && event.notification.data.url);
  event.waitUntil(
    (async () => {
      // Only this app's own window: a Building page on the same origin is
      // never focused or moved.
      const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const win = open.find((c) => inScope(c.url));
      if (!win) return self.clients.openWindow(url);
      // Focus while the tap still counts, then go to the session's page.
      await win.focus().catch(() => {});
      if (win.url === url) return;
      try {
        if (win.navigate) {
          await win.navigate(url);
          return;
        }
      } catch {}
      win.postMessage({ kit: 'open', url });
    })(),
  );
});

self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    (async () => {
      let sub = event.newSubscription;
      if (!sub) {
        let key = event.oldSubscription && event.oldSubscription.options && event.oldSubscription.options.applicationServerKey;
        if (!key) {
          const r = await fetch(`${BASE}/api/push/key`, { credentials: 'same-origin' });
          key = r.ok ? (await r.json()).key : null;
        }
        if (!key) return;
        sub = await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
      }
      await fetch(`${BASE}/api/push/subscribe`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ ...sub.toJSON(), old: event.oldSubscription ? event.oldSubscription.endpoint : null }),
      });
    })(),
  );
});
