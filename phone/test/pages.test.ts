// The phone pages as drawn from the Kit's data (view/render.ts), the same
// code on the server and in the browser: the four groups, a Mac that is
// away, several Macs, every action's answer, BASE_PATH in every link, and
// the data from the database (lib/state.ts), with Remove for a Mac.
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { draw, resultHtml, type View } from '../src/view/render.ts';
import { emptyUi, type Kit, type MacInfo, type Snapshot } from '../src/view/model.ts';
import { span, until, when } from '../src/view/time.ts';
import { db, resetDbForTests } from '../src/lib/db.ts';
import { loadKit, kitJson } from '../src/lib/state.ts';
import { macState, removeOwnMac } from '../src/lib/macs.ts';
import { seed, sample } from './sample.mjs';

const fixture = (f: string) => JSON.parse(readFileSync(new URL(`../fixtures/${f}`, import.meta.url), 'utf8'));
const PRO = 'mac_7Hq2Lx9Kp4';
const MINI = 'mac_2Vd8Rt5Wn1';
const AT = 1794587400;

function kit(over: Partial<Kit> = {}, macs?: MacInfo[]): Kit {
  const pro: Snapshot = fixture('snapshot.macbook-pro.json');
  const mini: Snapshot = fixture('snapshot.mac-mini-away.json');
  return {
    base: '',
    now: AT,
    email: 'avery.stone@sttark.com',
    macs: macs ?? [
      { id: PRO, name: 'MacBook Pro', state: 'live', last_seen: AT, kit: '1.140' },
      { id: MINI, name: 'Mac mini', state: 'asleep', last_seen: mini.at, kit: '1.139' },
    ],
    snaps: { [PRO]: pro, [MINI]: mini },
    archived: { [PRO]: fixture('archived.json').items },
    records: [],
    ...over,
  };
}
const one = () => kit({}, [{ id: PRO, name: 'MacBook Pro', state: 'live', last_seen: AT, kit: '1.140' }]);
const html = (v: View, k = kit(), ui = emptyUi()) => draw(v, k, ui).html;

describe('Sessions', () => {
  it('draws the four groups, Needs you first, then the Macs away', () => {
    const h = html({ page: 'sessions' });
    const order = ['Needs you', 'Claude working', 'Waiting on someone else', 'Held at usage limit', 'Macs away'].map((w) => h.indexOf(`>${w} <`));
    expect(order.every((i) => i > 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });
  it('leaves the sessions of a Mac that is away out of the groups, and stands one row for it', () => {
    const h = html({ page: 'sessions' });
    expect(h).not.toContain('Nozzle check page');
    expect(h).toContain('Mac mini');
    expect(h).toMatch(/Asleep since [^<]+\. 2 sessions then\./);
  });
  it('gives each row its page and a ↗ named Open in Claude', () => {
    const h = html({ page: 'sessions' });
    expect(h).toContain('href="/s/session_01SampleOrderLogin"');
    expect(h).toContain('href="https://claude.ai/code/session_01SampleOrderLogin" target="_blank" rel="noopener" aria-label="Open in Claude"');
  });
  it('names the Mac on a row only with more than one Mac', () => {
    expect(html({ page: 'sessions' })).toContain('<span class="mac">MacBook Pro</span>');
    expect(html({ page: 'sessions' }, one())).not.toContain('<span class="mac">');
  });
  it('searches the names', () => {
    const h = html({ page: 'sessions' }, kit(), { ...emptyUi(), q: 'lam' });
    expect(h).toContain('Laminator quote');
    expect(h).not.toContain('Press color');
    expect(html({ page: 'sessions' }, kit(), { ...emptyUi(), q: 'zzz' })).toContain('No session matches “zzz”');
  });
  it('says how to link a Mac when none is linked', () => {
    expect(html({ page: 'sessions' }, kit({ snaps: {}, archived: {} }, []))).toContain('No Mac linked yet');
  });
  it('says no Mac is live when every Mac is away', () => {
    const k = kit({}, [
      { id: PRO, name: 'MacBook Pro', state: 'quit', last_seen: AT, kit: '1.140' },
      { id: MINI, name: 'Mac mini', state: 'asleep', last_seen: AT, kit: '1.139' },
    ]);
    const h = html({ page: 'sessions' }, k);
    expect(h).toContain('No Mac is live now');
    expect(h).toContain('The Kit quit at');
  });
  it('escapes every word from a Mac', () => {
    const k = one();
    k.snaps[PRO].rows[0].title = '<img src=x onerror=alert(1)>';
    const h = html({ page: 'sessions' }, k);
    expect(h).not.toContain('<img src=x');
    expect(h).toContain('&lt;img src=x onerror=alert(1)&gt;');
  });
});

describe('One session', () => {
  it('has Open in Claude as its one green button, and Stop, Bring it back now and Stop waiting for a wait', () => {
    const h = html({ page: 'session', cse: 'session_01SampleLaminator', from: 'sessions' });
    expect(h.match(/class="btn full"/g)?.length).toBe(1);
    expect(h).toContain('Waits on 2 email replies');
    expect(h.match(/data-act="stop"/g)?.length).toBe(2);
    expect(h).toContain('Bring it back now');
    expect(h).toContain('Stop waiting');
    expect(h).toContain('It does not run while it waits.');
    expect(h).toContain('Check failing since');
  });
  it('shows "Sending..." on the button that sent, and holds the others', () => {
    const h = html({ page: 'session', cse: 'session_01SampleHvacUpdates', from: 'sessions' }, kit(), { ...emptyUi(), sending: 'lvl:high' });
    expect(h).toMatch(/data-level="high"[^>]*>Sending\.\.\.</);
    expect(h).toMatch(/data-level="low"[^>]*aria-disabled="true"/);
  });
  it('shows a session of a Mac that is away as of its time, with no buttons', () => {
    const h = html({ page: 'session', cse: 'session_01SampleNozzleCheck', from: `mac:${MINI}` });
    expect(h).toContain('As of ');
    expect(h).toContain('Mac mini is asleep.');
    expect(h).toContain('Actions work when this Mac is back.');
    expect(h).not.toContain('data-act="level"');
    expect(h).not.toContain('<select');
    expect(h).toContain('Open in Claude');
    expect(h).toContain(`href="/mac/${MINI}"`);
  });
  it('says so when the session is no longer in the list', () => {
    const d = draw({ page: 'session', cse: 'session_gone', from: 'usage' }, kit(), emptyUi());
    expect(d.status).toBe(404);
    expect(d.html).toContain('This session is not in your list now');
    expect(d.html).toContain('href="/usage"');
  });
  it('lists its changes from the phone, with the time', () => {
    const k = kit({ records: [{ at: AT, mac: PRO, cse: 'session_01SampleLaminator', act: 'set_level', reason: 'ok', words: 'Set effort to High from the phone.' }] });
    expect(html({ page: 'session', cse: 'session_01SampleLaminator', from: 'sessions' }, k)).toMatch(/Set effort to High from the phone, \d+:\d\d [AP]M/);
  });
});

describe('answers', () => {
  it('shows only the words the server sent, the first sentence bold', () => {
    const h = resultHtml({ scope: 'x', sec: 'top', reason: 'ok', words: 'Effort is High now. Auto is off for this session.' });
    expect(h).toContain('result ok');
    expect(h).toContain('<b>Effort is High now.</b> Auto is off for this session.');
  });
  it('draws every reason: done, nothing changed, and not sent', () => {
    const kind = (reason: any) => resultHtml({ scope: 'x', sec: 'top', reason, words: '' }).match(/result (\w+)/)![1];
    expect(['gone', 'not_now', 'not_here'].map(kind)).toEqual(['nochange', 'nochange', 'nochange']);
    expect(['offline', 'timeout', 'denied', 'bad'].map(kind)).toEqual(['fail', 'fail', 'fail', 'fail']);
    expect(resultHtml({ scope: 'x', sec: 'top', reason: 'timeout', words: '' })).toContain('Your Mac did not answer in time.');
  });
  it('shows an answer where it was asked, and at the top once that part is gone', () => {
    const r = { scope: 'session_01SampleHvacUpdates', sec: 'effort' as const, reason: 'ok' as const, words: 'Effort is High now.' };
    const h = html({ page: 'session', cse: 'session_01SampleHvacUpdates', from: 'sessions' }, kit(), { ...emptyUi(), result: r });
    expect(h.indexOf('result ok')).toBeGreaterThan(h.indexOf('Effort level'));
  });
  it('hides Bring it back once the Mac says the conversation is not on it', () => {
    const ui = { ...emptyUi(), result: { scope: 'session_01SampleDoorPi', sec: 'top' as const, reason: 'not_here' as const, words: 'Its conversation is not on this Mac, so this Mac cannot bring it back.' } };
    const h = html({ page: 'archived-item', cse: 'session_01SampleDoorPi' }, kit(), ui);
    expect(h).not.toContain('data-act="unarchive"');
    expect(h).toContain('cannot bring it back');
  });
});

describe('Archived, Usage, a Mac, Menu', () => {
  it('groups archived sessions by day, newest first, with the folder', () => {
    const h = html({ page: 'archived' }, one());
    expect(h.indexOf('Weekly plan')).toBeLessThan(h.indexOf('South E building model'));
    expect(h).toContain('<span class="folder">building</span>');
    expect(html({ page: 'archived' }, one(), { ...emptyUi(), q: 'quotes' })).toContain('Laminator RFQ');
  });
  it('offers Bring it back for an archived session', () => {
    const h = html({ page: 'archived-item', cse: 'session_01SampleDoorPi' });
    expect(h).toContain('Bring it back');
    expect(h).toContain('It goes back to your list on the same link');
  });
  it('shows the limits, the marks, the held sessions and the read time', () => {
    const h = html({ page: 'usage' });
    expect(h).toContain('At the 5-hour limit');
    expect(h).toContain('2 sessions hold.');
    expect(h).toContain('left:60%');
    expect(h).toMatch(/Read \d+:\d\d [AP]M/);
    expect(h).toContain('Change it in Settings on your Mac.');
  });
  it('shows an away Mac’s last list in gray, as of its time', () => {
    const h = html({ page: 'mac', id: MINI });
    expect(h).toContain('class="stale"');
    expect(h).toContain('As of ');
    expect(h).toContain('Open in Claude works now.');
  });
  it('lists the Macs with Remove and its confirm, and the light, auto and dark choice', () => {
    const h = html({ page: 'menu' });
    expect(h).toContain('aria-controls="rm-mac_2Vd8Rt5Wn1"');
    expect(h).toContain('action="/macs/mac_2Vd8Rt5Wn1/remove"');
    expect(h).toMatch(/>Light<.*>Auto<.*>Dark</s);
    expect(h).toContain('action="/auth/logout"');
  });
});

describe('Menu > Notices', () => {
  const menu = (k: Kit, notices: Partial<NonNullable<ReturnType<typeof emptyUi>['notices']>> | null = null) =>
    html({ page: 'menu' }, k, { ...emptyUi(), notices: notices ? { state: 'off', since: null, problem: null, device: 'phone', ...notices } : null });
  const sw = (h: string) => h.match(/<button type="button" class="switch"[^>]*data-act="notices"[^>]*>/)?.[0] ?? '';
  it('draws what the server knows first: this sign-in\'s notices, on since a time, or off', () => {
    const on = menu(kit({ notices: { key: 'k', mine: { on: true, since: AT - 3600 } } }));
    expect(on).toMatch(/On for this phone since \d+:\d\d [AP]M: one notice when a session waits 10 min for you and you are away from your Mac\./);
    expect(sw(on)).toContain('aria-checked="true"');
    expect(sw(on)).not.toContain('aria-disabled');
    const off = menu(kit({ notices: { key: 'k', mine: null } }));
    expect(off).toContain('Off for this phone. Turn on to get one notice when a session waits 10 min');
    expect(sw(off)).toContain('aria-checked="false"');
  });
  it('says when the server has no keys, and the switch waits', () => {
    const h = menu(kit({ notices: { key: null, mine: null } }));
    expect(h).toContain('Notices are not set up on this server yet.');
    expect(sw(h)).toContain('aria-disabled="true"');
  });
  it('on an iPhone in the browser: how to add it to the Home Screen, with the Share icon', () => {
    const h = menu(kit({ notices: { key: 'k', mine: null } }), { state: 'install', device: 'iPhone' });
    expect(h).toContain('To get notices on this iPhone, add Claude Kit to your Home Screen: in Safari, tap Share');
    expect(h).toContain('aria-label="(the Share button)"');
    expect(h).toContain('then Add to Home Screen. Open Claude Kit from your Home Screen and turn on notices here.');
    expect(sw(h)).toContain('aria-disabled="true"');
    expect(menu(kit({ notices: { key: 'k', mine: null } }), { state: 'install', device: 'iPad' })).toContain('on this iPad');
  });
  it('blocked, no Web Push, a change under way, and a tap that did not work', () => {
    const k = kit({ notices: { key: 'k', mine: null } });
    expect(menu(k, { state: 'blocked' })).toContain("Allow them in the phone's settings, then turn them on here.");
    expect(menu(k, { state: 'unsupported' })).toContain('This browser cannot get notices.');
    const busy = menu(k, { state: 'turning_on' });
    expect(busy).toContain('Turning on...');
    expect(sw(busy)).toContain('aria-busy="true"');
    const failed = menu(k, { state: 'off', problem: "The phone's push service did not answer. Try again." });
    expect(failed).toContain('<div class="note result fail" role="status">');
    expect(failed).toContain("<b>Notices did not change.</b> The phone&#39;s push service did not answer. Try again.");
  });
});

describe('BASE_PATH', () => {
  it('puts every link and form under the base', () => {
    const k = kit({ base: '/kit' });
    for (const v of [{ page: 'sessions' }, { page: 'archived' }, { page: 'menu' }, { page: 'usage' }, { page: 'mac', id: MINI }, { page: 'session', cse: 'session_01SampleLaminator', from: 'usage' }] as View[]) {
      const h = html(v, k);
      const own = [...h.matchAll(/(?:href|action)="([^"]+)"/g)].map((m) => m[1]).filter((u) => !u.startsWith('https://claude.ai/'));
      expect(own.length).toBeGreaterThan(0);
      for (const u of own) expect(u.startsWith('/kit/')).toBe(true);
    }
  });
});

describe('times', () => {
  it('says spans and deadlines in words', () => {
    expect(span(22 * 60)).toBe('22 min');
    expect(span(5 * 3600 + 10 * 60)).toBe('5 hr 10 min');
    expect(span(14 * 3600)).toBe('14 hr');
    expect(until(AT + 2 * 86400 + 60, AT)).toBe('in 2 days');
    expect(when(AT, AT, 'America/New_York')).toMatch(/^\d+:\d\d [AP]M$/);
    expect(when(AT + 3 * 86400, AT, 'America/New_York')).toMatch(/^[A-Z][a-z]{2} \d+:\d\d [AP]M$/);
    expect(when(AT + 40 * 86400, AT, 'America/New_York')).toMatch(/^[A-Z][a-z]{2} \d+$/);
  });
});

describe('the data from the database', () => {
  beforeEach(() => resetDbForTests());

  it('says a Mac’s state as the socket server does', () => {
    const now = 2_000_000_000;
    expect(macState({ lastSeen: now - 10, bye: null, byeAt: null }, now)).toBe('live');
    expect(macState({ lastSeen: now - 61, bye: null, byeAt: null }, now)).toBe('not_heard');
    expect(macState({ lastSeen: now - 100, bye: 'sleep', byeAt: now - 100 }, now)).toBe('asleep');
    expect(macState({ lastSeen: now - 100, bye: 'quit', byeAt: now - 100 }, now)).toBe('quit');
    expect(macState({ lastSeen: now - 30, bye: 'update', byeAt: now - 30 }, now)).toBe('updating');
    expect(macState({ lastSeen: now - 300, bye: 'update', byeAt: now - 300 }, now)).toBe('not_heard');
  });

  it('reads the person’s Macs, snapshots, archived list and the session’s changes', async () => {
    const now = Math.floor(Date.now() / 1000);
    await seed(':memory:', 'avery.stone@sttark.com', now);
    const k = loadKit({ email: 'avery.stone@sttark.com' }, { session: 'session_01SampleHvacUpdates', now });
    expect(k.macs.map((m) => [m.name, m.state])).toEqual([
      ['MacBook Pro', 'live'],
      ['Mac mini', 'asleep'],
    ]);
    expect(k.snaps[PRO].rows.length).toBe(sample(now).snaps[PRO].rows.length);
    expect(k.archived[PRO].length).toBe(7);
    expect(k.records[0].words).toBe('Turned Auto on from the phone.');
    expect(loadKit({ email: 'ada.anvil@sttark.com' }).macs).toEqual([]);
    expect(kitJson({ t: '</script>' })).not.toContain('</script>');
  });

  it('removes only the person’s own Mac, and records it', async () => {
    await seed(':memory:', 'avery.stone@sttark.com');
    expect(removeOwnMac({ email: 'ada.anvil@sttark.com', name: 'Ada Anvil' }, MINI)).toBe(false);
    expect(removeOwnMac({ email: 'avery.stone@sttark.com', name: 'Avery Stone' }, MINI)).toBe(true);
    expect(loadKit({ email: 'avery.stone@sttark.com' }).macs.map((m) => m.id)).toEqual([PRO]);
    expect(db().prepare("SELECT who, action, mac_name FROM records WHERE action = 'remove_mac'").get()).toEqual({ who: 'avery.stone@sttark.com', action: 'remove_mac', mac_name: 'Mac mini' });
    expect(db().prepare('SELECT COUNT(*) AS n FROM snapshots WHERE mac_id = ?').get(MINI)).toEqual({ n: 0 });
  });
});
