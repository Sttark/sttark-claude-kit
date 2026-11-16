// The phone pages as drawn from the Kit's data (view/render.ts), the same
// code on the server and in the browser: the four groups, a Mac that is
// away, several Macs, every action's answer, BASE_PATH in every link, and
// the data from the database (lib/state.ts), with Remove for a Mac.
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { draw, resultHtml, type View } from '../src/view/render.ts';
import { emptyUi, periodOf, usageQuery, usageView, type Kit, type MacInfo, type Snapshot, type UsageView } from '../src/view/model.ts';
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
  it('groups archived sessions by day, newest first, with no folder in the rows', () => {
    const h = html({ page: 'archived' }, one());
    expect(h.indexOf('Weekly plan')).toBeLessThan(h.indexOf('South E building model'));
    expect(h).not.toContain('class="folder"');
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

describe('Usage by session', () => {
  const lists = () => ({ [PRO]: fixture('usage.macbook-pro.json'), [MINI]: fixture('usage.mac-mini-away.json') });
  const u = (over: Partial<UsageView> = {}): View => ({ page: 'usage', usage: { pick: '7d', from: null, to: null, all: false, ...over } });
  /** The By session section only. */
  const bys = (h: string) => h.slice(h.indexOf('<section class="bys'));
  const rows = (h: string) => (bys(h).match(/<li><div class="bys-main">/g) ?? []).length;

  it('lists the sessions under the limits, biggest share first, with the note, the totals and the legend', () => {
    const h = html(u(), kit({ usage: lists() }, one().macs));
    expect(h.indexOf('By session')).toBeGreaterThan(h.indexOf('Change it in Settings on your Mac.'));
    const b = bys(h);
    expect(b).toContain('It is not a percent of your limit: Anthropic gives only the total percent.');
    expect(b).toContain('18 sessions · 8.1 billion tokens · agents did <b>77%</b> · worth $3,106 at API prices');
    expect(b).toContain('<i class="own"></i>The session</span><span><i class="ag"></i>Its agents');
    expect(b).toContain('Claude Code on this Mac · Nov 7 to Nov 13');
    expect(b.indexOf('Site map plan')).toBeLessThan(b.indexOf('Sttark Claude Kit<'));
    expect(b).toMatch(/Site map plan<\/span><b class="bys-pct">28\.3%<\/b>/);
    expect(b).toContain('75 agents');
    // The biggest share is the whole width; a bar is the session's part, then its agents'.
    expect(b).toContain('style="width:100.0%" role="img" aria-label="28.3% of your use: the session 5.1%, its agents 23.2%"');
    expect(b).toContain('<i class="own" style="flex:5.10"></i><i class="ag" style="flex:23.20"></i>');
  });
  it('has no folder or path, and no green', () => {
    const b = bys(html(u({ all: true }), kit({ usage: lists() })));
    expect(b).not.toMatch(/~\/|\/Users\/|\/src\b|class="folder"/);
    expect(b).not.toMatch(/green/);
  });
  it('shows the top 15, then how many more and their share, with Show all; all of them with ?all=1', () => {
    const k = kit({ usage: lists() }, one().macs);
    const h = html(u(), k);
    expect(rows(h)).toBe(15);
    expect(bys(h)).toContain('3 more sessions · 3.5% of your use');
    expect(bys(h)).toContain('data-act="usage-all"');
    const all = html(u({ all: true }), k);
    expect(rows(all)).toBe(18);
    expect(bys(all)).toContain('Show the top 15');
  });
  it('gives a row with a session link its ↗ Open in Claude, and keeps the bars on one scale without one', () => {
    const b = bys(html(u({ all: true }), kit({ usage: lists() }, one().macs)));
    expect(b).toContain('href="https://claude.ai/code/session_01SampleSiteMap" target="_blank" rel="noopener" aria-label="Open in Claude"');
    expect(b).toMatch(/Bin label sizes<\/span>.*?<span class="open-none" aria-hidden="true"><\/span>/s);
    // a row opens nothing in the app
    expect(b).not.toContain('href="/s/');
  });
  it('lists each Mac under its name; an away Mac’s list is as of its time, in gray', () => {
    const b = bys(html(u(), kit({ usage: lists() })));
    expect(b).toContain('Claude Code on your Macs');
    expect(b).toContain('<h3 class="bys-mac">MacBook Pro</h3>');
    expect(b).toContain('<h3 class="bys-mac">Mac mini</h3>');
    expect(b).toMatch(/As of Thu 6:12 PM\. Mac mini is away\.<\/p>.*<div class="stale"><ul class="bys-rows">.*Nozzle check page/s);
  });
  it('waits for a live Mac’s list, and says after 15 seconds that it did not come', () => {
    const k = kit({ usage: {} }, one().macs);
    expect(bys(html(u(), k))).toContain('Getting the list from MacBook Pro...');
    const late = bys(draw(u(), k, { ...emptyUi(), usageAsked: AT - 20 }).html);
    expect(late).toContain('MacBook Pro did not send the list. A Kit from before this list does not send it; the Kit updates by itself within an hour.');
    // An away Mac with no list says when it comes.
    expect(bys(html(u(), kit({ usage: {} })))).toContain('No list from Mac mini for this period. It comes when this Mac is back.');
  });
  it('draws only the lists of the period it shows, and says when there is no use', () => {
    const k = kit({ usage: lists() }, one().macs);
    expect(bys(html(u({ pick: '30d' }), k))).toContain('Getting the list from MacBook Pro...');
    const empty = { ...fixture('usage.macbook-pro.json'), rows: [], total: { sessions: 0, tokens: 0, agent_share: 0, usd: 0 } };
    expect(bys(html(u(), kit({ usage: { [PRO]: empty } }, one().macs)))).toContain('No use in this period.');
  });
  it('the period buttons, and Custom with its two days and Show', () => {
    const k = kit({ usage: lists() }, one().macs);
    const h = bys(html(u(), k));
    expect(h).toMatch(/data-pick="today"[^>]*aria-pressed="false">Today<.*data-pick="7d"[^>]*aria-pressed="true">7 days<.*>30 days<.*>Custom</s);
    const c = bys(html(u({ pick: 'custom', from: '2026-11-02', to: '2026-11-09' }), k));
    expect(c).toContain('name="from" value="2026-11-02"');
    expect(c).toContain('name="to" value="2026-11-09" max="2026-11-13"');
    expect(c).toContain('>Show</button>');
    expect(bys(html(u({ pick: 'custom' }), k))).toContain('name="from" value="2026-11-07"');
  });
  it('says the human work under the totals, with an ⓘ whose note opens in place', () => {
    const k = kit({ usage: lists() }, one().macs);
    const b = bys(html(u(), k));
    const line = '<p><span>Human work ≈ <b>1 person for 4.7 months</b> ·</span> <span>≈ 20 people full time over these 7 days</span></p>';
    expect(b).toContain(line);
    expect(b.indexOf('class="bys-tot"')).toBeLessThan(b.indexOf(line));
    expect(b.indexOf(line)).toBeLessThan(b.indexOf('<ul class="bys-rows">'));
    expect(b).toContain(`data-act="info" data-key="human-${PRO}" data-k="info:human-${PRO}" aria-expanded="false" aria-controls="note-human-${PRO}" aria-label="About human work"`);
    expect(b).toContain(`<div class="note" id="note-human-${PRO}" hidden>An estimate. The Kit counts the hours Claude was at work, its agents too:`);
    expect(b).toContain('that kind of work: software 12, design 5, browser and admin 2.5, small or mixed 2. Full time is 8 hours a day, 5 days a week.');
    const open = bys(draw(u(), k, { ...emptyUi(), notes: [`human-${PRO}`] }).html);
    expect(open).toContain(`aria-expanded="true" aria-controls="note-human-${PRO}"`);
    expect(open).toContain(`<div class="note" id="note-human-${PRO}">An estimate`);
  });
  it('ends each row’s line with its human work, when it has some', () => {
    const b = bys(html(u({ all: true }), kit({ usage: lists() }, one().macs)));
    const text = (h: string) => h.replace(/<[^>]+>/g, '');
    const meta = [...b.matchAll(/<div class="sub bys-meta">(.*?)<\/div>/g)].map((m) => text(m[1]));
    expect(meta[0]).toMatch(/^last active \d+:\d\d [AP]M · 75 agents · ≈ 1 person for 5\.9 weeks$/);
    expect(meta[1]).toMatch(/ · 51 agents · ≈ 1 person for 7\.4 weeks$/);
    expect(meta).toContainEqual(expect.stringMatching(/ · ≈ 1 person for 6 hours$/));
    expect(meta).toContainEqual(expect.stringMatching(/ · ≈ 1 person for 18 minutes$/));
    // A row with no human work (the Kit's own checks) ends as before.
    expect(b).toMatch(/Sttark Claude Kit checks<\/span>.*?<div class="sub bys-meta"><span>last active [^<]*<\/span><\/div>/s);
  });
  it('gives each Mac its own human work line', () => {
    const b = bys(html(u(), kit({ usage: lists() })));
    expect(b).toContain('Human work ≈ <b>1 person for 4.7 months</b>');
    expect(b).toContain('<div class="bys-human stale"><p><span>Human work ≈ <b>1 person for 5.8 days</b> ·</span> <span>≈ 1.2 people full time over these 7 days</span>');
    expect(b).toContain(`aria-controls="note-human-${PRO}"`);
    expect(b).toContain(`aria-controls="note-human-${MINI}"`);
    expect(b).toContain('≈ 1 person for 30 minutes');
  });
  it('shows a list from a Kit before the estimate as before: no human work line, no ≈ on the rows', () => {
    const old = (f: string) => {
      const l = fixture(f);
      delete l.total.human_hours;
      delete l.more.human_hours;
      delete l.factors;
      for (const r of l.rows) delete r.human_hours;
      return l;
    };
    const b = bys(html(u({ all: true }), kit({ usage: { [PRO]: old('usage.macbook-pro.json'), [MINI]: old('usage.mac-mini-away.json') } })));
    expect(b).not.toContain('Human work');
    expect(b).not.toContain('≈');
    expect(b).not.toContain('note-human');
    expect(b).toContain('18 sessions · 8.1 billion tokens · agents did <b>77%</b> · worth $3,106 at API prices</p><div><ul class="bys-rows">');
    expect(b).toMatch(/<div class="sub bys-meta"><span>last active \d+:\d\d [AP]M ·<\/span> <span>75 agents<\/span><\/div>/);
    // A list whose work comes to 0 hours says nothing either.
    const none = fixture('usage.macbook-pro.json');
    none.total.human_hours = 0;
    expect(bys(html(u(), kit({ usage: { [PRO]: none } }, one().macs)))).not.toContain('Human work');
  });
  it('reads its choice from the address, and writes it back', () => {
    const v = usageView(new URLSearchParams('p=custom&from=2026-11-09&to=2026-11-02&all=1'));
    expect(v).toEqual({ pick: 'custom', from: '2026-11-02', to: '2026-11-09', all: true });
    expect(periodOf(v)).toBe('2026-11-02..2026-11-09');
    expect(usageQuery(v)).toBe('?p=custom&from=2026-11-02&to=2026-11-09&all=1');
    expect(usageView(new URLSearchParams('p=nope'))).toEqual({ pick: '7d', from: null, to: null, all: false });
    expect(periodOf(usageView(new URLSearchParams('p=custom&from=2026-11-02')))).toBeNull();
    expect(usageQuery(usageView(new URLSearchParams('')))).toBe('');
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
    const k = loadKit({ email: 'avery.stone@sttark.com' }, { session: 'session_01SampleHvacUpdates', now, usage: '7d' });
    expect(k.macs.map((m) => [m.name, m.state])).toEqual([
      ['MacBook Pro', 'live'],
      ['Mac mini', 'asleep'],
    ]);
    expect(k.snaps[PRO].rows.length).toBe(sample(now).snaps[PRO].rows.length);
    expect(k.archived[PRO].length).toBe(7);
    expect(k.records[0].words).toBe('Turned Auto on from the phone.');
    expect(k.usage![PRO].rows.length).toBe(18);
    expect(k.usage![MINI].rows[0].title).toBe('Nozzle check page');
    expect(loadKit({ email: 'avery.stone@sttark.com' }, { usage: '30d' }).usage).toEqual({});
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
    expect(db().prepare('SELECT COUNT(*) AS n FROM usage_lists WHERE mac_id = ?').get(MINI)).toEqual({ n: 0 });
  });
});
