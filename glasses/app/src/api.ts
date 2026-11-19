// The Kit glasses bridge on the Mac: its JSON API and live socket.
// Contract: glasses/app/README.md, "The bridge API".

export type Status = 'needs_you' | 'working' | 'waiting' | 'idle';

export interface SessionRow {
  id: string;
  title: string;
  folder?: string;
  status: Status;
  why?: string | null;
  status_line?: string | null;
  updated_at?: string | number | null;
  has_pending?: boolean;
  /** The glance card the bridge wrote for the newest reply; null until it is made. */
  glance?: Glance | null;
}

/** What the session screen shows first: the reply in a few short lines (bridge, glance.py). */
export interface Glance {
  /** NEEDS YOU, WORKING, WAITING or DONE. */
  status_word: string;
  /** At most 3 short lines, the key fact first; from a status table, one line per ask, "! " for asks that need you. */
  lines: string[];
  /** From a status table: each line's state (needs, working, other, done, dropped). */
  states?: string[];
  /** What the person must do, "nothing now", or null when the "! " lines say it. */
  you: string | null;
  /** The answers of the question that waits, in short words. */
  options: PendingOption[];
  /** A few words for the Home row. */
  phrase?: string;
  from?: 'table' | 'summary';
  source?: string;
}

export interface PendingOption {
  id: string;
  label: string;
}

export interface Pending {
  kind: 'question' | 'permission' | 'plan';
  text: string;
  options: PendingOption[];
}

export interface SessionDetail extends SessionRow {
  last_reply: string;
  pending: Pending | null;
}

/** One turn of a session: a prompt and all of Claude's text after it. */
export interface Turn {
  /** From 0, the session's first turn. */
  index: number;
  /** When the prompt came: ISO 8601, or Unix seconds. */
  at: string | number | null;
  /** you: the person's prompt; kit: a message the Kit typed; task: a background task's notice; claude: none. */
  from?: 'you' | 'kit' | 'task' | 'claude';
  /** The prompt as plain text (a short label for the Kit's and a task's). */
  user_text: string;
  reply_text: string;
}

export interface TurnPage {
  /** Oldest first, newest last. */
  turns: Turn[];
  total: number;
  /** The turn the session screen shows now (its reply is last_reply); -1 for none. */
  latest: number;
}

export interface Folder {
  path: string;
  label: string;
}

export class BridgeError extends Error {
  constructor(
    message: string,
    readonly kind: 'unset' | 'down' | 'auth' | 'gone' | 'http' | 'readonly',
    readonly status = 0,
  ) {
    super(message);
  }
}

export interface BridgeConfig {
  url: string;
  token: string;
  /** Test mode: refuse every request that would change a session. */
  readonly?: boolean;
}

const TIMEOUT_MS = 8000;
const TRANSCRIBE_TIMEOUT_MS = 30000;
// A message goes from the Mac through a claude.ai page in Chrome, which can
// take a while when Chrome has to open the page first. A new session can
// wait up to 90 s for its Claude Code to connect (bridge README).
const SEND_TIMEOUT_MS = 60000;
// The first look at a long session's history reads all its events on the Mac.
const TURNS_TIMEOUT_MS = 30000;
const START_TIMEOUT_MS = 120000;

export class Bridge {
  constructor(private cfg: () => BridgeConfig) {}

  private base(): string {
    const { url, token } = this.cfg();
    if (!url || !token) throw new BridgeError('No bridge address or token yet', 'unset');
    return url.replace(/\/+$/, '');
  }

  private async req<T>(method: string, path: string, body?: BodyInit, type?: string, timeout = TIMEOUT_MS): Promise<T> {
    const base = this.base();
    if (method !== 'GET' && path !== '/api/transcribe' && this.cfg().readonly) {
      throw new BridgeError('Read-only test mode: nothing was sent', 'readonly');
    }
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeout);
    let res: Response;
    try {
      res = await fetch(base + path, {
        method,
        body,
        signal: ctl.signal,
        headers: {
          Authorization: `Bearer ${this.cfg().token}`,
          ...(type ? { 'Content-Type': type } : {}),
        },
      });
    } catch (e) {
      const why = ctl.signal.aborted ? `no answer in ${Math.round(timeout / 1000)} s` : 'no connection';
      throw new BridgeError(`Can't reach ${base} (${why})`, 'down');
    } finally {
      clearTimeout(timer);
    }
    if (res.status === 401 || res.status === 403) throw new BridgeError('The bridge did not accept the token', 'auth', res.status);
    if (res.status === 404 && path.startsWith('/api/sessions/')) throw new BridgeError('This session is gone from your Mac', 'gone', 404);
    if (!res.ok) {
      let msg = `${res.status}`;
      try {
        const j = await res.json();
        msg = j.error || j.message || msg;
      } catch {}
      throw new BridgeError(`The bridge said: ${msg}`, 'http', res.status);
    }
    return (await res.json()) as T;
  }

  health() {
    return this.req<{ ok: boolean; version?: string }>('GET', '/api/health');
  }
  async sessions(): Promise<SessionRow[]> {
    return (await this.req<{ sessions: SessionRow[] }>('GET', '/api/sessions')).sessions || [];
  }
  session(id: string) {
    return this.req<SessionDetail>('GET', `/api/sessions/${encodeURIComponent(id)}`);
  }
  /** The `limit` turns before turn `before` (the newest ones without it). */
  async turns(id: string, before?: number, limit = 5): Promise<TurnPage> {
    const q = `limit=${limit}${before === undefined ? '' : `&before=${before}`}`;
    const r = await this.req<Partial<TurnPage>>('GET', `/api/sessions/${encodeURIComponent(id)}/turns?${q}`, undefined, undefined, TURNS_TIMEOUT_MS);
    const turns = r.turns || [];
    const total = r.total ?? turns.length;
    // An older bridge without `latest`: the newest turn with reply text.
    const latest = r.latest ?? [...turns].reverse().find((t) => t.reply_text)?.index ?? -1;
    return { turns, total, latest };
  }
  message(id: string, text: string) {
    return this.req<{ ok: boolean }>('POST', `/api/sessions/${encodeURIComponent(id)}/message`, JSON.stringify({ text }), 'application/json', SEND_TIMEOUT_MS);
  }
  /** `done: false` with `pending`: the prompt has more questions; this answer is kept and `pending` is the next one. */
  answer(id: string, optionId: string) {
    return this.req<{ ok: boolean; done?: boolean; pending?: Pending | null }>(
      'POST',
      `/api/sessions/${encodeURIComponent(id)}/answer`,
      JSON.stringify({ option_id: optionId }),
      'application/json',
      SEND_TIMEOUT_MS,
    );
  }
  start(prompt: string, folder?: string) {
    return this.req<{ id: string }>('POST', '/api/sessions', JSON.stringify(folder ? { prompt, folder } : { prompt }), 'application/json', START_TIMEOUT_MS);
  }
  async folders(): Promise<Folder[]> {
    return (await this.req<{ folders: Folder[] }>('GET', '/api/folders')).folders || [];
  }
  async transcribe(pcm: Uint8Array): Promise<string> {
    // Copy into a plain ArrayBuffer: fetch takes it as raw bytes.
    const body = pcm.slice().buffer as ArrayBuffer;
    const r = await this.req<{ text: string }>('POST', '/api/transcribe', body, 'application/octet-stream', TRANSCRIBE_TIMEOUT_MS);
    return (r.text || '').trim();
  }

  /** The live socket. Calls back with every message; reconnects is the caller's job. */
  live(onMessage: (m: LiveMessage) => void, onClose: (why: string) => void): LiveSocket | null {
    let base: string;
    try {
      base = this.base();
    } catch {
      return null;
    }
    const url = base.replace(/^http/, 'ws') + `/api/live?token=${encodeURIComponent(this.cfg().token)}`;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      onClose('socket refused');
      return null;
    }
    let closed = false;
    ws.onmessage = (e) => {
      try {
        onMessage(JSON.parse(String(e.data)));
      } catch {}
    };
    ws.onclose = (e) => {
      if (closed) return;
      closed = true;
      onClose(e.reason || `closed (${e.code})`);
    };
    ws.onerror = () => {};
    return {
      subscribe(id: string | null) {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'subscribe', id }));
        else ws.addEventListener('open', () => ws.send(JSON.stringify({ type: 'subscribe', id })), { once: true });
      },
      close() {
        closed = true;
        try {
          ws.close();
        } catch {}
      },
      get open() {
        return ws.readyState === WebSocket.OPEN;
      },
    };
  }
}

export type LiveMessage =
  | { type: 'sessions'; sessions: SessionRow[] }
  | { type: 'session'; session: SessionDetail };

export interface LiveSocket {
  subscribe(id: string | null): void;
  close(): void;
  readonly open: boolean;
}
