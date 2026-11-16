// Times as the pages say them, in the Mac's time zone: a clock time today,
// a weekday this week, a date further out; and spans of time in words.
// Times are Unix seconds (the contract's). Pure: the server and the browser
// draw the same words.

type Parts = { y: number; m: number; d: number; wd: string; mon: string; clock: string };

const fmts = new Map<string, Intl.DateTimeFormat>();
function fmt(tz: string): Intl.DateTimeFormat {
  let f = fmts.get(tz);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat('en-US', { timeZone: tz, year: 'numeric', month: 'numeric', day: 'numeric', weekday: 'short', hour: 'numeric', minute: '2-digit', hour12: true });
    } catch {
      f = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: 'numeric', day: 'numeric', weekday: 'short', hour: 'numeric', minute: '2-digit', hour12: true });
    }
    fmts.set(tz, f);
  }
  return f;
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function parts(t: number, tz: string): Parts {
  const p: Record<string, string> = {};
  for (const x of fmt(tz).formatToParts(new Date(t * 1000))) p[x.type] = x.value;
  const m = Number(p.month);
  return { y: Number(p.year), m, d: Number(p.day), wd: p.weekday, mon: MONTHS[m - 1], clock: `${p.hour}:${p.minute} ${p.dayPeriod}` };
}

/** Whole days from now's day to t's day, in tz (0 today, -1 yesterday). */
function dayDiff(t: number, now: number, tz: string): number {
  const a = parts(t, tz);
  const b = parts(now, tz);
  return Math.round((Date.UTC(a.y, a.m - 1, a.d) - Date.UTC(b.y, b.m - 1, b.d)) / 86400000);
}

/** 4:40 PM */
export function clock(t: number, tz: string): string {
  return parts(t, tz).clock;
}

/** 4:40 PM today, Sun 5:00 PM within 6 days, else Dec 23. */
export function when(t: number, now: number, tz: string): string {
  const p = parts(t, tz);
  const dd = dayDiff(t, now, tz);
  if (dd === 0) return p.clock;
  if (Math.abs(dd) <= 6) return `${p.wd} ${p.clock}`;
  return `${p.mon} ${p.d}`;
}

/** As when, but always with the clock time: Nov 2, 6:12 PM. */
export function whenFull(t: number, now: number, tz: string): string {
  const p = parts(t, tz);
  const dd = dayDiff(t, now, tz);
  if (dd === 0) return p.clock;
  if (Math.abs(dd) <= 6) return `${p.wd} ${p.clock}`;
  return `${p.mon} ${p.d}, ${p.clock}`;
}

/** Today, Yesterday, else Wed Nov 11: the archived list's day headings. */
export function dayLabel(t: number, now: number, tz: string): string {
  const dd = dayDiff(t, now, tz);
  if (dd === 0) return 'Today';
  if (dd === -1) return 'Yesterday';
  const p = parts(t, tz);
  return `${p.wd} ${p.mon} ${p.d}`;
}

/** A day key for grouping: 2026-11-13. */
export function dayKey(t: number, tz: string): string {
  const p = parts(t, tz);
  return `${p.y}-${String(p.m).padStart(2, '0')}-${String(p.d).padStart(2, '0')}`;
}

/** A day of the contract (2026-11-10) in words: Nov 10. */
export function dayWords(day: string): string {
  const [, m, d] = day.split('-').map(Number);
  return m >= 1 && m <= 12 && d ? `${MONTHS[m - 1]} ${d}` : day;
}

/** A span: 22 min, 1 hr 5 min, 14 hr, 3 days. At least 1 min. */
export function span(sec: number): string {
  const min = Math.max(1, Math.floor(sec / 60));
  if (min < 60) return `${min} min`;
  const hr = Math.floor(min / 60);
  const m = min % 60;
  if (hr < 10) return m ? `${hr} hr ${m} min` : `${hr} hr`;
  if (hr < 48) return `${hr} hr`;
  const days = Math.floor(hr / 24);
  return `${days} days`;
}

/** How long until t: in 5 hr 10 min, in 2 days; now when it is past. */
export function until(t: number, now: number): string {
  if (t - now < 60) return 'now';
  return `in ${span(t - now)}`;
}
