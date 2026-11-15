// The daily job: what is kept only for a while goes when its time is up
// (README, Storage). It runs at start and then every 24 hours. Records go
// after a year, the only way a record ever goes; the database refuses any
// other delete (lib/db.ts). The cut-off for records is worked out by SQLite
// in the same statement the trigger checks, so the two always agree.
import { db } from './db.ts';

const DAY_S = 24 * 60 * 60;
const nowS = () => Math.floor(Date.now() / 1000);

export type Expired = { webSessions: number; oauthStates: number; links: number; pushesSent: number; records: number };

export function expireOld(now = nowS()): Expired {
  const d = db();
  return d.transaction(() => ({
    webSessions: d.prepare('DELETE FROM web_sessions WHERE expires_at <= ?').run(now).changes,
    oauthStates: d.prepare('DELETE FROM oauth_states WHERE expires_at < ?').run(now).changes,
    links: d.prepare('DELETE FROM links WHERE created_at < ?').run(now - DAY_S).changes,
    pushesSent: d.prepare('DELETE FROM pushes_sent WHERE sent_at < ?').run(now - 2 * DAY_S).changes,
    records: d.prepare("DELETE FROM records WHERE at <= CAST(strftime('%s', 'now', '-1 year') AS INTEGER)").run().changes,
  }))();
}

function runOnce(): void {
  try {
    const n = expireOld();
    const said = Object.entries(n).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k}`);
    if (said.length) console.log(`[expiry] removed ${said.join(', ')}`);
  } catch (e) {
    console.error(`[expiry] ALERT: the daily job failed: ${(e as Error).message}`);
  }
}

/** Now and every 24 hours, with the server (once per process). */
export function startExpiry(): void {
  const g = globalThis as { __kitExpiryTimer?: ReturnType<typeof setInterval> };
  if (g.__kitExpiryTimer) return;
  runOnce();
  g.__kitExpiryTimer = setInterval(runOnce, DAY_S * 1000);
  g.__kitExpiryTimer.unref?.();
}
