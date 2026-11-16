// Shared by the tests: made-up people, a roster feed as Workrouter sends it,
// and cookies like Astro's.
import { storeRoster, type RosterPerson } from '../src/lib/roster.ts';

/** Twelve made-up people on the roster (a good roster has at least 10). */
export const ROSTER: RosterPerson[] = [
  'ada.anvil', 'avery.stone', 'bix.dowel', 'cal.easel', 'dot.gasket', 'eve.inkwell',
  'faro.tap', 'gus.nozzle', 'hal.oarlock', 'ivy.rivet', 'kip.valve', 'lux.yoke',
].map((u) => ({ email: `${u}@sttark.com`, name: u.split('.').map((w) => w[0].toUpperCase() + w.slice(1)).join(' ') }));

export const storeSampleRoster = (people = ROSTER, now?: number) => storeRoster(people, now);

/** The org-sync feed's shape: {success, data: {circles, roles, employees}}. */
export function feed(people = ROSTER, extra: { email: string; name: string; active: boolean }[] = []) {
  return {
    success: true,
    data: {
      circles: { name: 'Company', slug: 'company', members: [], children: [] },
      roles: [],
      employees: [...people.map((p) => ({ ...p, active: true })), ...extra],
    },
  };
}

/** Cookies as Astro hands them to a route: get, set and delete. */
export function fakeCookies(initial: Record<string, string> = {}) {
  const jar = new Map(Object.entries(initial));
  const sets: { name: string; value: string; options: Record<string, unknown> }[] = [];
  return {
    jar,
    sets,
    get: (name: string) => (jar.has(name) ? { value: jar.get(name)! } : undefined),
    set: (name: string, value: string, options: Record<string, unknown> = {}) => {
      jar.set(name, value);
      sets.push({ name, value, options });
    },
    delete: (name: string) => {
      jar.delete(name);
    },
  } as any;
}
