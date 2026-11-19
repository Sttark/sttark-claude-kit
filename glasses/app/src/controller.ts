// The app: what screen shows, what each gesture does there, and how it keeps
// in step with the bridge. Gestures: swipe moves, tap opens or acts, double
// tap goes back (on the first screen, the system asks to close the app).
import { Bridge, BridgeError, type Folder, type LiveSocket, type Pending, type SessionDetail, type SessionRow, type Turn } from './api';
import type { Input } from './events';
import type { Glasses } from './glasses';
import * as S from './screens';
import { settings } from './settings';
import { Dictation } from './voice';

type Screen =
  | { kind: 'home' }
  // page 0 is the glance card, 1 and on the reply's pages; sel is the card's
  // chosen button, first the first button in view. turn: null for the latest
  // turn; else the earlier turn shown (its index), and page is a page of
  // that turn's reply.
  | { kind: 'session'; id: string; page: number; flash: string | null; replyKey: string; sel: number; first: number; btnKey: string; message: string | null; busy: boolean; turn: number | null }
  | { kind: 'actions'; id: string; items: S.ActionItem[]; sel: number; first: number; pending: Pending | null; ask: string[]; message: string | null; busy: boolean }
  | { kind: 'voice'; purpose: 'reply' | 'new'; id: string | null; phase: 'listening' | 'finishing' | 'sending' | 'empty' | 'error'; text: string; note: string | null; back: 'session' | 'actions' }
  | { kind: 'confirm'; prompt: string; busy: boolean; error: string | null };

export type ConnState = 'unset' | 'connecting' | 'ok' | 'down' | 'auth';

export interface Snapshot {
  conn: ConnState;
  error: string;
  version: string | null;
  checkedAt: number | null;
  downSince: number | null;
  live: boolean;
  sessions: number;
  needYou: number;
  listening: boolean;
  folders: Folder[];
  screen: Screen['kind'];
}

const POLL_MS = 5000;
const RETRY_MS = 10000;
const NOTICE_MS = 6000;
const FLASH_MS = 8000;
/** Earlier turns come from the bridge a few at a time. */
const TURN_BATCH = 5;

/** A session's earlier turns, as far back as the person has scrolled. */
interface History {
  total: number;
  /** The turn the session screen shows (its reply is last_reply); the earlier ones are below it. */
  latest: number;
  turns: Map<number, Turn>;
  loaded: boolean;
  /** Requests on the way: "new" for the newest turns, else the `before` index. */
  pending: Set<string>;
  error: string | null;
}

export class Controller {
  private screen: Screen = { kind: 'home' };
  private rows: SessionRow[] = [];
  private loaded = false;
  private details = new Map<string, SessionDetail>();
  private histories = new Map<string, History>();
  private homeRows: S.HomeRow[] = [];
  /** The marked row on Home: a session id, or null for + New session. It
   *  follows its session when the rows move; homeAt is the fallback when
   *  the session leaves the list. */
  private homeSel: string | null = null;
  private homeAt = 0;
  private homeFirst = 0;
  private conn: ConnState = 'connecting';
  private error = '';
  private version: string | null = null;
  private checkedAt: number | null = null;
  private downSince: number | null = null;
  private socket: LiveSocket | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private notice: { text: string; until: number } | null = null;
  private noticeTimer: ReturnType<typeof setTimeout> | null = null;
  private flashTimer: ReturnType<typeof setTimeout> | null = null;
  private dictation: Dictation | null = null;
  private folders: Folder[] = [];
  private lastSwipe = 0;
  private lastDouble = 0;
  private lastTap = 0;
  /** When the current screen opened: a tap too soon after is the same finger. */
  private openedAt = 0;
  private listeners = new Set<(s: Snapshot) => void>();
  private generation = 0;
  /** The screen last drawn, as one word, for the log (scripts/e2e.mjs waits on it). */
  private shownKey = '';
  /** Sessions started from these glasses in this run: test mode (only=) keeps
   *  them when the Kit renames them after their first prompt. */
  private startedHere = new Set<string>();

  constructor(
    private bridge: Bridge,
    private lens: Glasses,
  ) {}

  // ---------- panel side ----------

  onChange(f: (s: Snapshot) => void): () => void {
    this.listeners.add(f);
    f(this.snapshot());
    return () => this.listeners.delete(f);
  }

  snapshot(): Snapshot {
    return {
      conn: this.conn,
      error: this.error,
      version: this.version,
      checkedAt: this.checkedAt,
      downSince: this.downSince,
      live: !!this.socket?.open,
      sessions: this.rows.length,
      needYou: this.rows.filter((r) => r.status === 'needs_you').length,
      listening: this.screen.kind === 'voice' && (this.screen.phase === 'listening' || this.screen.phase === 'empty'),
      folders: this.folders,
      screen: this.screen.kind,
    };
  }

  private changed(): void {
    const s = this.snapshot();
    this.listeners.forEach((f) => f(s));
  }

  /** Words typed on the phone instead of spoken (the simulator has no mic). */
  useTyped(text: string): boolean {
    const sc = this.screen;
    if (sc.kind !== 'voice' || (sc.phase !== 'listening' && sc.phase !== 'empty')) return false;
    this.stopMic();
    void this.gotWords(text.trim());
    return true;
  }

  // ---------- connection ----------

  start(): void {
    this.render();
    void this.connect();
  }

  /** Start again from scratch: after the panel saves new settings, or a tap on "try now". */
  reconnect(): void {
    this.generation++;
    this.socket?.close();
    this.socket = null;
    this.rows = [];
    this.loaded = false;
    this.details.clear();
    this.histories.clear();
    if (this.screen.kind !== 'home') this.stopMic();
    this.screen = { kind: 'home' };
    this.conn = 'connecting';
    this.render();
    void this.connect();
  }

  private async connect(): Promise<void> {
    const gen = this.generation;
    if (this.pollTimer) clearTimeout(this.pollTimer);
    try {
      const h = await this.bridge.health();
      if (gen !== this.generation) return;
      this.version = h.version ?? null;
      await this.refresh();
      if (gen !== this.generation) return;
      void this.loadFolders();
      this.openLive();
    } catch (e) {
      if (gen !== this.generation) return;
      this.fail(e);
    }
    this.schedulePoll();
  }

  private schedulePoll(): void {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    const gen = this.generation;
    const wait = this.conn === 'ok' ? POLL_MS : RETRY_MS;
    this.pollTimer = setTimeout(async () => {
      if (gen !== this.generation) return;
      if (this.conn !== 'ok' && this.conn !== 'connecting') {
        await this.connect();
        return;
      }
      // While the live socket is open it brings every change; the poll is
      // the fallback and the health check.
      if (!this.socket?.open) {
        try {
          await this.refresh();
          if (!this.socket) this.openLive();
        } catch (e) {
          this.fail(e);
        }
      } else {
        this.checkedAt = Date.now();
        this.changed();
      }
      this.schedulePoll();
    }, wait);
  }

  private async refresh(): Promise<void> {
    const rows = await this.bridge.sessions();
    this.ok();
    this.applyRows(rows);
    const sc = this.screen;
    if (sc.kind === 'session' || sc.kind === 'actions') {
      try {
        this.applyDetail(await this.bridge.session(sc.id));
      } catch (e) {
        if (e instanceof BridgeError && e.kind === 'gone') this.gone();
        else throw e;
      }
    }
  }

  private async loadFolders(): Promise<void> {
    try {
      this.folders = await this.bridge.folders();
      this.changed();
    } catch {}
  }

  private openLive(): void {
    if (this.socket) return;
    const gen = this.generation;
    this.socket = this.bridge.live(
      (m) => {
        if (gen !== this.generation) return;
        if (m.type === 'sessions') {
          this.ok();
          this.applyRows(m.sessions || []);
        } else if (m.type === 'session' && m.session) {
          this.applyDetail(m.session);
        }
      },
      (why) => {
        if (gen !== this.generation) return;
        console.warn('[live] closed:', why);
        this.socket = null;
        this.changed();
      },
    );
    const sc = this.screen;
    if (sc.kind === 'session' || sc.kind === 'actions') this.socket?.subscribe(sc.id);
  }

  private ok(): void {
    const wasDown = this.conn !== 'ok';
    this.conn = 'ok';
    this.error = '';
    this.downSince = null;
    this.checkedAt = Date.now();
    if (wasDown) this.render();
    this.changed();
  }

  private fail(e: unknown): void {
    const err = e instanceof BridgeError ? e : new BridgeError(String((e as Error)?.message || e), 'down');
    this.conn = err.kind === 'unset' ? 'unset' : err.kind === 'auth' ? 'auth' : 'down';
    this.error = err.message;
    this.downSince ??= Date.now();
    this.checkedAt = Date.now();
    this.socket?.close();
    this.socket = null;
    this.render();
    this.changed();
  }

  // ---------- data in ----------

  private applyRows(all: SessionRow[]): void {
    const only = settings().only.toLowerCase();
    const rows = only ? all.filter((r) => this.startedHere.has(r.id) || (r.title || '').trim().toLowerCase().startsWith(only)) : all;
    if (this.loaded) {
      const before = new Map(this.rows.map((r) => [r.id, r.status]));
      // Not the session on the screen now: its own status line says so.
      const open = this.openId();
      const fresh = rows.filter((r) => r.status === 'needs_you' && before.get(r.id) !== 'needs_you' && r.id !== open);
      if (fresh.length === 1) this.showNotice(`${S.clean(fresh[0].title)} needs you`);
      else if (fresh.length > 1) this.showNotice(`${fresh.length} sessions need you`);
    }
    this.rows = rows;
    this.loaded = true;
    this.render();
    this.changed();
  }

  private applyDetail(d: SessionDetail): void {
    const prev = this.details.get(d.id);
    this.details.set(d.id, d);
    // Keep the list row in step with what the detail says.
    const i = this.rows.findIndex((r) => r.id === d.id);
    if (i >= 0) {
      const { last_reply: _l, pending: _p, ...row } = d;
      this.rows[i] = { ...this.rows[i], ...row };
    }
    const sc = this.screen;
    if (sc.kind === 'session' && sc.id === d.id) {
      const key = replyKey(d);
      if (key !== sc.replyKey) {
        if (sc.turn !== null) {
          // Reading an earlier turn: stay there, and say a new reply came.
          if (prev && sc.replyKey) this.showNotice('New reply. Tap for the latest.');
        } else {
          if (prev && sc.replyKey) this.flash(sc, 'New reply');
          sc.page = 0;
        }
        sc.replyKey = key;
        // The reply before this one is an earlier turn now.
        if (prev) void this.loadTurns(d.id);
      }
    }
    if (sc.kind === 'actions' && sc.id === d.id && sc.pending && !sameQuestion(sc.pending, d.pending)) {
      // Answered somewhere else. The rows stay put, so the > stays on the
      // row under the person's finger; only the words change.
      sc.message = 'This was answered on another screen.';
    }
    this.render();
  }

  // ---------- notices ----------

  private showNotice(text: string): void {
    this.notice = { text, until: Date.now() + NOTICE_MS };
    if (this.noticeTimer) clearTimeout(this.noticeTimer);
    this.noticeTimer = setTimeout(() => {
      this.notice = null;
      this.render();
    }, NOTICE_MS);
  }

  private flash(sc: Extract<Screen, { kind: 'session' }>, text: string): void {
    sc.flash = text;
    if (this.flashTimer) clearTimeout(this.flashTimer);
    this.flashTimer = setTimeout(() => {
      if (this.screen === sc) {
        sc.flash = null;
        this.render();
      }
    }, FLASH_MS);
  }

  // ---------- drawing ----------

  private render(): void {
    const key = this.screenKey();
    if (key !== this.shownKey) {
      this.shownKey = key;
      console.log(`[kit] screen ${key}`);
    }
    this.lens.show(this.page());
  }

  private screenKey(): string {
    const sc = this.screen;
    switch (sc.kind) {
      case 'home':
        return this.loaded ? 'home' : `connect:${this.conn}`;
      case 'voice':
        return `voice:${sc.phase}`;
      case 'confirm':
        return sc.busy ? 'confirm:starting' : sc.error ? 'confirm:error' : 'confirm';
      case 'actions':
        return sc.busy ? 'actions:sending' : 'actions';
      case 'session': {
        if (sc.turn !== null) {
          const h = this.histories.get(sc.id);
          return `earlier:${(h?.latest ?? 0) - sc.turn}${h?.turns.has(sc.turn) ? '' : ':loading'}`;
        }
        // The glance card is page 0; the reply's pages follow.
        return sc.page === 0 ? (sc.busy ? 'card:sending' : 'card') : 'session';
      }
    }
  }

  private offlineWords(): string | null {
    if (this.conn === 'ok' || !this.downSince) return null;
    const min = Math.floor((Date.now() - this.downSince) / 60000);
    return min < 1 ? 'offline' : `offline ${min} min`;
  }

  private page() {
    const notice = this.notice && this.notice.until > Date.now() ? this.notice.text : null;
    const sc = this.screen;
    switch (sc.kind) {
      case 'home': {
        if (!this.loaded) return this.connectionPage(notice);
        this.homeRows = S.homeRows(this.rows);
        const sel = this.homeIndex();
        return S.homePage({
          rows: this.homeRows,
          sel,
          first: this.homeFirst,
          needCount: this.rows.filter((r) => r.status === 'needs_you').length,
          offline: this.offlineWords(),
          notice,
        });
      }
      case 'session': {
        if (sc.turn !== null) return this.earlierPage(sc, notice);
        const d = this.details.get(sc.id) ?? null;
        const row = this.rows.find((r) => r.id === sc.id) ?? null;
        const off = this.offlineWords();
        const pages = S.sessionPages(d, !!off);
        sc.page = Math.min(sc.page, pages.length);
        const title = d?.title || row?.title || 'Session';
        if (sc.page === 0) {
          const glance = S.cardOf(d, row);
          const buttons = this.cardButtons(sc);
          const head = notice ? `! ${notice}` : sc.flash ? sc.flash : off ? `! ${off[0].toUpperCase()}${off.slice(1)}: may be old` : null;
          const earlier = (this.histories.get(sc.id)?.latest ?? 0) > 0;
          return S.cardPage({ title, glance, buttons, sel: sc.sel, first: sc.first, message: sc.message, head, replyPages: pages.length, earlier });
        }
        const status = off && !sc.flash ? `! ${off[0].toUpperCase()}${off.slice(1)}: this may be old` : S.statusLine(row, d, sc.flash);
        return S.sessionPage({ title, pages, page: sc.page - 1, status, pending: d?.pending ?? null, notice });
      }
      case 'actions': {
        const d = this.details.get(sc.id) ?? null;
        const row = this.rows.find((r) => r.id === sc.id) ?? null;
        let ask = sc.ask;
        if (sc.message) ask = [sc.message, ...sc.ask.slice(1).map(() => '')];
        return S.actionsPage({ title: d?.title || row?.title || 'Session', ask, items: sc.items, sel: sc.sel, first: sc.first, notice });
      }
      case 'voice': {
        const title = sc.purpose === 'new' ? 'New session' : `Reply to ${S.clean(this.titleOf(sc.id))}`;
        const done = sc.purpose === 'new' ? 'done' : 'send';
        let body = '';
        let hint = `Tap: ${done}   Double tap: cancel`;
        if (sc.phase === 'listening') {
          const words = sc.text ? `\n${S.tail(sc.text, 5)}` : sc.note ? `\n${sc.note}` : '\nSpeak now.';
          body = `●  Listening...${words}`;
        } else if (sc.phase === 'finishing') {
          body = 'Getting your words...';
          hint = 'Double tap: cancel';
        } else if (sc.phase === 'sending') {
          body = `Sending...\n${S.tail(sc.text, 5)}`;
          hint = '';
        } else if (sc.phase === 'empty') {
          body = 'No words heard.\nTap to speak again, or type on your phone.';
          hint = 'Tap: speak again   Double tap: cancel';
        } else {
          body = `! Not sent: ${sc.note}\n${S.tail(sc.text, 4)}`;
          hint = 'Tap: try again   Double tap: cancel';
        }
        return S.textPage({ title, body, hint, notice });
      }
      case 'confirm': {
        const folder = this.newFolder();
        const where = folder ? `\nFolder: ${folder.label}` : '';
        const body = sc.busy ? `Starting...\n${sc.prompt}` : sc.error ? `! Not started: ${sc.error}\n${sc.prompt}` : `${sc.prompt}${where}`;
        const hint = sc.busy ? '' : sc.error ? 'Tap: try again   Double tap: cancel' : 'Tap: start   Double tap: cancel';
        return S.textPage({ title: 'Start this new session?', body, hint, notice });
      }
    }
  }

  private earlierPage(sc: Extract<Screen, { kind: 'session' }>, notice: string | null) {
    const h = this.histories.get(sc.id);
    const i = sc.turn ?? 0;
    const latest = h?.latest ?? 0;
    const turn = h?.turns.get(i) ?? null;
    const pages = !turn && h?.error ? [`! Earlier turns did not load: ${h.error}.\nSwipe to try again.`] : S.turnPages(turn);
    sc.page = Math.min(sc.page, pages.length - 1);
    return S.turnPage({ k: latest - i, count: latest, turn, pages, page: sc.page, next: i + 1 >= latest ? 'latest' : 'later', notice });
  }

  private connectionPage(notice: string | null) {
    if (this.conn === 'unset') {
      return S.textPage({
        title: 'Set up Kit',
        body: 'Open Kit on your phone, in the Even app.\nEnter the bridge address and token from your Mac.',
        hint: 'Double tap: close',
        notice,
      });
    }
    if (this.conn === 'auth') {
      return S.textPage({
        title: 'Token not accepted',
        body: 'Your Mac did not accept the token.\nCheck the token on your phone, in the Kit page of the Even app.',
        hint: 'Tap: try again   Double tap: close',
        notice,
      });
    }
    if (this.conn === 'down') {
      return S.textPage({
        title: "Can't reach your Mac",
        body: `${this.error}.\nKit tries again every 10 s. Is the Mac awake, and on the same network as your phone?`,
        hint: 'Tap: try now   Double tap: close',
        notice,
      });
    }
    return S.textPage({ title: 'Kit', body: 'Connecting to your Mac...', hint: '', notice });
  }

  /** The session the screen is about, if any. */
  private openId(): string | null {
    const sc = this.screen;
    if (sc.kind === 'session' || sc.kind === 'actions') return sc.id;
    if (sc.kind === 'voice') return sc.id;
    return null;
  }

  private titleOf(id: string | null): string {
    if (!id) return 'Session';
    return this.details.get(id)?.title || this.rows.find((r) => r.id === id)?.title || 'Session';
  }

  /** The marked Home row's index now: its session's row, wherever it moved;
   *  the same place when that session left the list. Keeps the rows in view. */
  private homeIndex(): number {
    const rows = this.homeRows;
    let i = rows.findIndex((r) => r.id === this.homeSel);
    if (i < 0) i = Math.max(0, Math.min(this.homeAt, rows.length - 1));
    this.homeSel = rows[i]?.id ?? null;
    this.homeAt = i;
    this.homeFirst = S.scrollTo(this.homeFirst, i, rows.length, S.HOME_ROWS);
    return i;
  }

  /** The card's buttons now. A new question puts the choice back on its first answer. */
  private cardButtons(sc: Extract<Screen, { kind: 'session' }>): S.CardButton[] {
    const d = this.details.get(sc.id) ?? null;
    const row = this.rows.find((r) => r.id === sc.id) ?? null;
    const buttons = S.cardButtons(S.cardOf(d, row), d?.pending ?? null);
    const key = buttons.map((b) => (b.kind === 'option' ? b.id : b.kind)).join(',');
    if (key !== sc.btnKey) {
      sc.btnKey = key;
      sc.sel = 0;
      sc.first = 0;
    }
    sc.sel = Math.max(0, Math.min(sc.sel, buttons.length - 1));
    sc.first = S.scrollTo(sc.first, sc.sel, buttons.length, S.MAX_BUTTONS);
    return buttons;
  }

  private newFolder(): Folder | null {
    const want = settings().folder;
    return this.folders.find((f) => f.path === want) ?? this.folders[0] ?? null;
  }

  // ---------- input ----------

  handle(input: Input): void {
    const now = Date.now();
    switch (input.kind) {
      case 'audio':
        this.dictation?.add(input.pcm);
        return;
      case 'foreground':
        this.lens.invalidate();
        this.render();
        if (this.conn === 'ok') void this.refresh().catch((e) => this.fail(e));
        return;
      case 'background':
        return;
      case 'exit':
        this.stopMic();
        this.socket?.close();
        return;
      case 'double':
        if (now - this.lastDouble < 400) return; // one gesture can arrive twice
        this.lastDouble = now;
        this.back();
        return;
      case 'up':
      case 'down': {
        if (now - this.lastSwipe < 250) return;
        this.lastSwipe = now;
        const forward = (input.kind === 'down') !== settings().swapSwipe;
        this.swipe(forward);
        return;
      }
      case 'tap': {
        // One tap can come as a text event and a system event: the same gesture.
        if (now - this.lastTap < 300) return;
        // On the answer list and on a card with answers the marked one can be
        // an answer: a tap that comes right after the tap that opened it is
        // not a choice.
        const sc = this.screen;
        const answers = sc.kind === 'actions' || (sc.kind === 'session' && sc.page === 0 && !!this.details.get(sc.id)?.pending?.options.length);
        if (answers && now - this.openedAt < 700) return;
        this.lastTap = now;
        this.tap();
        return;
      }
    }
  }

  private swipe(forward: boolean): void {
    const sc = this.screen;
    const step = forward ? 1 : -1;
    if (sc.kind === 'home') {
      if (!this.loaded || !this.homeRows.length) return;
      const i = Math.max(0, Math.min(this.homeRows.length - 1, this.homeIndex() + step));
      this.homeSel = this.homeRows[i].id;
      this.homeAt = i;
      this.render();
      return;
    }
    if (sc.kind === 'actions') {
      const i = Math.max(0, Math.min(sc.items.length - 1, sc.sel + step));
      if (i === sc.sel) return;
      sc.sel = i;
      sc.first = S.scrollTo(sc.first, i, sc.items.length, S.actionRows(sc.ask.length));
      this.render();
      return;
    }
    if (sc.kind !== 'session') return;
    if (sc.turn !== null) {
      this.swipeEarlier(sc, forward);
      return;
    }
    const n = S.sessionPages(this.details.get(sc.id) ?? null).length;
    if (sc.page === 0) {
      // The card: a swipe picks the next answer; past the last one, the full reply.
      const buttons = this.cardButtons(sc);
      const i = sc.sel + step;
      if (buttons.length && i >= 0 && i < buttons.length) {
        sc.sel = i;
        sc.first = S.scrollTo(sc.first, i, buttons.length, S.MAX_BUTTONS);
        if (!sc.busy) sc.message = null;
        this.render();
        return;
      }
      // Up at the top of the card (its first answer): the turn before.
      if (!forward) {
        this.toEarlier(sc);
        return;
      }
    }
    const next = Math.max(0, Math.min(n, sc.page + step));
    if (next === sc.page) return;
    sc.page = next;
    if (next === 0) {
      // Back on the card from the reply: the last button, where the swipe left it.
      const buttons = this.cardButtons(sc);
      sc.sel = Math.max(0, buttons.length - 1);
      sc.first = S.scrollTo(sc.first, sc.sel, buttons.length, S.MAX_BUTTONS);
    }
    this.render();
  }

  private tap(): void {
    const sc = this.screen;
    switch (sc.kind) {
      case 'home': {
        if (!this.loaded) {
          if (this.conn === 'down' || this.conn === 'auth') this.reconnect();
          return;
        }
        const row = this.homeRows[this.homeIndex()];
        if (!row) return;
        if (row.id === null) this.startVoice('new', null);
        else this.openSession(row.id);
        return;
      }
      case 'session': {
        if (sc.turn !== null) {
          this.toLatest(sc);
          return;
        }
        if (sc.page === 0) {
          const buttons = this.cardButtons(sc);
          const b = buttons[sc.sel];
          if (b?.kind === 'say') {
            this.startVoice('reply', sc.id, 'session');
            return;
          }
          if (b?.kind === 'option') {
            if (!sc.busy) void this.answerFromCard(sc, b.id, b.label);
            return;
          }
        }
        this.openActions(sc.id);
        return;
      }
      case 'actions': {
        if (sc.busy) return;
        const item = sc.items[sc.sel];
        if (!item) return;
        if (item.kind === 'back') this.openSession(sc.id, false);
        else if (item.kind === 'voice') this.startVoice('reply', sc.id, 'actions');
        else if (item.kind === 'continue') void this.sendFromActions(sc, 'Continue');
        else void this.answer(sc, item.id, item.label);
        return;
      }
      case 'voice':
        if (sc.phase === 'listening') void this.finishVoice();
        else if (sc.phase === 'empty') this.startVoice(sc.purpose, sc.id, sc.back);
        else if (sc.phase === 'error') void this.gotWords(sc.text);
        return;
      case 'confirm':
        if (!sc.busy) void this.startSession(sc);
        return;
    }
  }

  private back(): void {
    const sc = this.screen;
    switch (sc.kind) {
      case 'home':
        void this.lens.exit();
        return;
      case 'session':
        if (sc.turn !== null) this.toLatest(sc);
        else this.goHome();
        return;
      case 'actions':
        this.openSession(sc.id, false);
        return;
      case 'voice':
        this.stopMic();
        if (sc.purpose === 'reply' && sc.id) {
          if (sc.back === 'session') this.openSession(sc.id, false);
          else this.openActions(sc.id);
        } else this.goHome();
        return;
      case 'confirm':
        this.goHome();
        return;
    }
  }

  // ---------- moves ----------

  private goHome(): void {
    this.screen = { kind: 'home' };
    this.socket?.subscribe(null);
    this.render();
    this.changed();
  }

  private openSession(id: string, fresh = true): void {
    // Back on Home, the mark is on this session.
    this.homeSel = id;
    const d = this.details.get(id);
    this.screen = { kind: 'session', id, page: 0, flash: null, replyKey: d ? replyKey(d) : '', sel: 0, first: 0, btnKey: '', message: null, busy: false, turn: null };
    this.openedAt = Date.now();
    this.socket?.subscribe(id);
    this.render();
    this.changed();
    if (fresh || !d) void this.loadDetail(id);
    // The newest turns now, so the first swipe up shows one at once.
    if (fresh || !this.histories.get(id)?.loaded) void this.loadTurns(id);
  }

  // ---------- earlier turns ----------

  /** A swipe up at the top of the latest turn: the turn before it, from its top. */
  private toEarlier(sc: Extract<Screen, { kind: 'session' }>): void {
    const h = this.histories.get(sc.id);
    if (!h?.loaded) {
      this.flash(sc, 'Getting the earlier turns...');
      this.render();
      void this.loadTurns(sc.id);
      return;
    }
    if (h.latest <= 0) {
      this.flash(sc, 'No earlier turns in this session');
      this.render();
      return;
    }
    sc.turn = h.latest - 1;
    sc.page = 0;
    this.ensureTurns(sc);
    this.render();
  }

  /** In an earlier turn: its pages, then the turn before (up) or after (down);
   *  down at the end of the newest earlier turn is the latest turn again. */
  private swipeEarlier(sc: Extract<Screen, { kind: 'session' }>, forward: boolean): void {
    const h = this.histories.get(sc.id);
    const i = sc.turn ?? 0;
    if (!h) return this.toLatest(sc);
    const pages = S.turnPages(h.turns.get(i) ?? null).length;
    if (forward) {
      if (h.turns.has(i) && sc.page < pages - 1) sc.page++;
      else if (i + 1 >= h.latest) return this.toLatest(sc);
      else {
        sc.turn = i + 1;
        sc.page = 0;
      }
    } else if (sc.page > 0) {
      sc.page--;
    } else if (i > 0) {
      sc.turn = i - 1;
      sc.page = 0;
    } else {
      return; // the first turn: nothing above
    }
    this.ensureTurns(sc);
    this.render();
  }

  /** The latest turn again, at its top: the card, its first answer marked. A
   *  tap right after is the same finger, not an answer (see handle). */
  private toLatest(sc: Extract<Screen, { kind: 'session' }>): void {
    sc.turn = null;
    sc.page = 0;
    sc.sel = 0;
    sc.first = 0;
    this.openedAt = Date.now();
    this.render();
  }

  /** Load the turn on the screen and the next ones up, before the person gets there. */
  private ensureTurns(sc: Extract<Screen, { kind: 'session' }>): void {
    const h = this.histories.get(sc.id);
    if (!h || sc.turn === null) return;
    // The oldest turn held without a gap below the latest one.
    let low = h.latest;
    while (low > 0 && h.turns.has(low - 1)) low--;
    if (low > 0 && sc.turn - 2 < low) void this.loadTurns(sc.id, low);
  }

  /** The newest turns (no `before`), or the ones before turn `before`. */
  private async loadTurns(id: string, before?: number): Promise<void> {
    let h = this.histories.get(id);
    if (!h) {
      h = { total: 0, latest: -1, turns: new Map(), loaded: false, pending: new Set(), error: null };
      this.histories.set(id, h);
    }
    const key = before === undefined ? 'new' : String(before);
    if (h.pending.has(key)) return;
    h.pending.add(key);
    const gen = this.generation;
    try {
      const r = await this.bridge.turns(id, before, TURN_BATCH);
      if (gen !== this.generation) return;
      for (const t of r.turns) h.turns.set(t.index, t);
      if (before === undefined || !h.loaded) {
        h.total = r.total;
        h.latest = r.latest;
      }
      h.loaded = true;
      h.error = null;
    } catch (e) {
      if (gen !== this.generation) return;
      h.error = (e as Error).message;
    } finally {
      h.pending.delete(key);
    }
    const sc = this.screen;
    if (sc.kind === 'session' && sc.id === id) {
      if (sc.turn !== null && sc.turn >= h.latest) sc.turn = null; // the history moved under it
      if (sc.flash === 'Getting the earlier turns...' && h.loaded) sc.flash = null;
      this.ensureTurns(sc);
      this.render();
    }
  }

  private async loadDetail(id: string): Promise<void> {
    try {
      this.applyDetail(await this.bridge.session(id));
    } catch (e) {
      if (e instanceof BridgeError && e.kind === 'gone') this.gone();
      else if (e instanceof BridgeError && (e.kind === 'down' || e.kind === 'auth')) this.fail(e);
    }
  }

  private gone(): void {
    this.showNotice('That session is gone from your Mac');
    this.goHome();
  }

  private openActions(id: string): void {
    const d = this.details.get(id);
    const pending = d?.pending ?? null;
    let ask = S.askText(pending);
    // Always one line above the rows, so a message there never changes the
    // layout (a rebuild redraws the whole page, which flickers).
    if (!ask.length) ask = [d?.status === 'working' ? 'Claude is working. A reply adds to the work.' : 'Reply, or tell Claude to continue.'];
    this.screen = { kind: 'actions', id, items: S.actionItems(pending), sel: 0, first: 0, pending, ask, message: null, busy: false };
    this.openedAt = Date.now();
    this.render();
    this.changed();
  }

  private async answer(sc: Extract<Screen, { kind: 'actions' }>, optionId: string, label: string): Promise<void> {
    const latest = this.details.get(sc.id)?.pending;
    if (!latest || !latest.options.some((o) => o.id === optionId)) {
      sc.message = 'Already answered. Nothing was sent.';
      this.render();
      return;
    }
    sc.busy = true;
    sc.message = `Sending: ${label.replace(/^\d+\s+/, '')}...`;
    this.render();
    try {
      const r = await this.bridge.answer(sc.id, optionId);
      if (r.done === false && r.pending) {
        // A prompt with more questions: the bridge keeps this answer and
        // shows the next question; all go to the session after the last.
        if (this.screen !== sc) return;
        const d = this.details.get(sc.id);
        if (d) this.details.set(sc.id, { ...d, pending: r.pending, has_pending: true });
        this.openActions(sc.id);
        return;
      }
      this.afterSend(sc.id, `Sent: ${label.replace(/^\d+\s+/, '')}`);
    } catch (e) {
      if (this.screen !== sc) return;
      sc.busy = false;
      sc.message = `! Not sent: ${(e as Error).message}`;
      this.render();
    }
  }

  /** An answer from the card's buttons: it goes at once, as from the answer list. */
  private async answerFromCard(sc: Extract<Screen, { kind: 'session' }>, optionId: string, label: string): Promise<void> {
    const latest = this.details.get(sc.id)?.pending;
    if (!latest || !latest.options.some((o) => o.id === optionId)) {
      sc.message = 'Already answered. Nothing was sent.';
      this.render();
      return;
    }
    sc.busy = true;
    sc.message = `Sending: ${label}...`;
    this.render();
    try {
      const r = await this.bridge.answer(sc.id, optionId);
      if (this.screen !== sc) return;
      if (r.done === false && r.pending) {
        // The next question of the same prompt: its answers take the buttons.
        const d = this.details.get(sc.id);
        if (d) this.details.set(sc.id, { ...d, pending: r.pending, has_pending: true });
        sc.busy = false;
        sc.message = null;
        this.openedAt = Date.now();
        this.render();
        return;
      }
      this.afterSend(sc.id, `Sent: ${label}`);
    } catch (e) {
      if (this.screen !== sc) return;
      sc.busy = false;
      sc.message = `! Not sent: ${(e as Error).message}`;
      this.render();
    }
  }

  private async sendFromActions(sc: Extract<Screen, { kind: 'actions' }>, text: string): Promise<void> {
    sc.busy = true;
    sc.message = `Sending: ${text}...`;
    this.render();
    try {
      await this.bridge.message(sc.id, text);
      this.afterSend(sc.id, `Sent: ${text}`);
    } catch (e) {
      if (this.screen !== sc) return;
      sc.busy = false;
      sc.message = `! Not sent: ${(e as Error).message}`;
      this.render();
    }
  }

  private afterSend(id: string, flash: string): void {
    // Until the bridge says otherwise, Claude is now working on it. The
    // card it wrote was for the question: the bridge sends a new one.
    const i = this.rows.findIndex((r) => r.id === id);
    if (i >= 0) this.rows[i] = { ...this.rows[i], status: 'working', has_pending: false, glance: null };
    const d = this.details.get(id);
    if (d) this.details.set(id, { ...d, status: 'working', pending: null, has_pending: false, glance: null });
    this.openSession(id, true);
    const sc = this.screen;
    if (sc.kind === 'session') this.flash(sc, flash);
    this.render();
  }

  // ---------- voice ----------

  private startVoice(purpose: 'reply' | 'new', id: string | null, back: 'session' | 'actions' = 'actions'): void {
    this.stopMic();
    const sc: Screen = { kind: 'voice', purpose, id, phase: 'listening', text: '', note: null, back };
    this.screen = sc;
    const dict = new Dictation(
      this.bridge,
      (text) => {
        if (this.screen === sc && sc.phase === 'listening') {
          sc.text = text;
          this.render();
        }
      },
      () => {
        if (this.screen === sc && sc.phase === 'listening') void this.finishVoice();
      },
    );
    this.dictation = dict;
    this.render();
    this.changed();
    void this.lens.mic(true).then((on) => {
      if (this.screen !== sc) return;
      if (!on && this.lens.present) {
        sc.note = 'The glasses mic did not start. Type on your phone instead.';
        this.render();
      }
    });
    // No sound after a few seconds: say so, and name the other way in.
    setTimeout(() => {
      if (this.screen === sc && sc.phase === 'listening' && !dict.lastFrameAt && !sc.note) {
        sc.note = 'No sound from the mic yet. Speak, or type on your phone.';
        this.render();
      }
    }, 4000);
  }

  private stopMic(): void {
    if (this.dictation) {
      this.dictation.stop();
      this.dictation = null;
      void this.lens.mic(false);
    }
  }

  private async finishVoice(): Promise<void> {
    const sc = this.screen;
    if (sc.kind !== 'voice' || !this.dictation) return;
    const dict = this.dictation;
    this.dictation = null;
    sc.phase = 'finishing';
    this.render();
    this.changed();
    void this.lens.mic(false);
    let words = '';
    try {
      words = await dict.finish();
    } catch (e) {
      if (this.screen !== sc) return;
      words = dict.live;
      if (!words) {
        sc.phase = 'empty';
        this.render();
        this.changed();
        return;
      }
    }
    if (this.screen !== sc) return;
    await this.gotWords(words);
  }

  private async gotWords(words: string): Promise<void> {
    const sc = this.screen;
    if (sc.kind !== 'voice') return;
    if (!words) {
      sc.phase = 'empty';
      this.render();
      this.changed();
      return;
    }
    sc.text = words;
    if (sc.purpose === 'new') {
      this.screen = { kind: 'confirm', prompt: words, busy: false, error: null };
      this.render();
      this.changed();
      return;
    }
    sc.phase = 'sending';
    this.render();
    this.changed();
    try {
      await this.bridge.message(sc.id!, words);
      if (this.screen !== sc) return;
      this.afterSend(sc.id!, `Sent: ${words}`);
    } catch (e) {
      if (this.screen !== sc) return;
      sc.phase = 'error';
      sc.note = (e as Error).message;
      this.render();
    }
  }

  private async startSession(sc: Extract<Screen, { kind: 'confirm' }>): Promise<void> {
    sc.busy = true;
    sc.error = null;
    this.render();
    try {
      const folder = this.newFolder();
      const { id } = await this.bridge.start(sc.prompt, folder?.path);
      this.startedHere.add(id);
      if (this.screen !== sc) return;
      const title = S.clean(sc.prompt).split(' ').slice(0, 6).join(' ');
      const row: SessionRow = { id, title, status: 'working', has_pending: false };
      if (!this.rows.some((r) => r.id === id)) this.rows = [...this.rows, row];
      this.details.set(id, { ...row, last_reply: '', pending: null });
      this.openSession(id, true);
      const s2 = this.screen as Screen;
      if (s2.kind === 'session') this.flash(s2, 'Started. Claude is working.');
      this.render();
    } catch (e) {
      if (this.screen !== sc) return;
      sc.busy = false;
      sc.error = (e as Error).message;
      this.render();
    }
  }
}

function replyKey(d: SessionDetail): string {
  return `${d.last_reply?.length ?? 0}:${(d.last_reply || '').slice(0, 80)}:${d.pending?.kind ?? ''}:${(d.pending?.text || '').slice(0, 40)}`;
}

function sameQuestion(a: Pending | null, b: Pending | null): boolean {
  if (!a || !b) return a === b;
  return a.kind === b.kind && a.text === b.text && a.options.map((o) => o.id).join() === b.options.map((o) => o.id).join();
}
