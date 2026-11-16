// The human work estimate in words: what the same work takes people. The
// Mac computes the hours (Resources/hooks/usage-scan.py) and sends them with
// its factors (schema/usage.v1.json); the Mac window says them with the same
// words, so both follow one rule, with the same examples in their tests.
// A person full time works 8 hours a day, 40 hours a week, 4.33 weeks a
// month, 52 weeks a year. Pure: the server and the browser draw the same
// words.
import type { WorkFactor } from './model.ts';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** One number: under 10, one decimal unless it is whole ("3", "2.5");
 *  from 10, a whole number with a thousands comma ("20", "1,240"). */
export function num(n: number): string {
  if (n < 10) {
    const r = Math.round(n * 10) / 10;
    return Number.isInteger(r) ? String(r) : r.toFixed(1);
  }
  return Math.round(n).toLocaleString('en-US');
}

/** Each unit after minutes: under this many hours, the hours in one, and
 *  its name. */
const UNITS: [under: number, hours: number, one: string, many: string][] = [
  [8, 1, 'hour', 'hours'],
  [80, 8, 'day', 'days'],
  [520, 40, 'week', 'weeks'],
  [4160, 173.2, 'month', 'months'],
  [Infinity, 2080, 'year', 'years'],
];

/** One person: "1 person for 15 minutes", "1 person for 4.7 months". For
 *  more than 0 hours. */
export function personWords(h: number): string {
  const minutes = Math.round(h * 60);
  if (minutes < 60) {
    const n = Math.max(1, minutes);
    return `1 person for ${n} ${n === 1 ? 'minute' : 'minutes'}`;
  }
  const [, hours, one, many] = UNITS.find(([under]) => h < under)!;
  const n = num(h / hours);
  return `1 person for ${n} ${n === '1' ? one : many}`;
}

const dayMs = (day: string) => Date.parse(`${day}T00:00:00Z`);
const dayOf = (day: string) => new Date(dayMs(day));

/** Mondays to Fridays from the first day to the last, both in; at least 1. */
export function weekdays(from: string, to: string): number {
  let n = 0;
  for (let t = dayMs(from); t <= dayMs(to); t += 86400000) {
    const wd = new Date(t).getUTCDay();
    if (wd !== 0 && wd !== 6) n++;
  }
  return Math.max(1, n);
}

/** today, over these 7 days, over these 30 days, from Nov 2 to Nov 9, or on
 *  Mon, Nov 2. */
export function periodWords(period: string, from: string, to: string): string {
  if (period === 'today') return 'today';
  if (period === '7d') return 'over these 7 days';
  if (period === '30d') return 'over these 30 days';
  const md = (day: string) => `${MONTHS[dayOf(day).getUTCMonth()]} ${dayOf(day).getUTCDate()}`;
  return from === to ? `on ${WEEKDAYS[dayOf(from).getUTCDay()]}, ${md(from)}` : `from ${md(from)} to ${md(to)}`;
}

/** People together: "≈ 20 people full time over these 7 days", or "less
 *  than 1 person full time today". */
export function peopleWords(h: number, from: string, to: string, period: string): string {
  const n = h / (8 * weekdays(from, to));
  const when = periodWords(period, from, to);
  if (n < 1) return `less than 1 person full time ${when}`;
  const s = num(n);
  return `≈ ${s} ${s === '1' ? 'person' : 'people'} full time ${when}`;
}

/** The ⓘ note: how the estimate is made, with the factors the Mac sent. */
export function humanNote(factors: WorkFactor[] | undefined): string {
  const list = (factors ?? []).map((f) => `${f.name.toLowerCase()} ${num(f.x)}`).join(', ');
  return (
    'An estimate. The Kit counts the hours Claude was at work, its agents too: the model writing and the tools it ran. ' +
    'Waits do not count: for you, at the usage limit, for checks and timers. ' +
    `Each hour counts as the hours a person needs for that kind of work${list ? `: ${list}` : ''}. ` +
    'Full time is 8 hours a day, 5 days a week.'
  );
}
