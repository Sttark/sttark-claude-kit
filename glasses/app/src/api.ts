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
  /** A short summary of the session, when the bridge has one: what Read to me says first. */
  glance?: string | null;
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
const START_TIMEOUT_MS = 120000;
// The Mac makes the sound with macOS say: a few seconds for a long summary.
const SPEECH_TIMEOUT_MS = 30000;

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
  /** Read to me: the session's summary as sound made on the Mac (audio/mp4), and its words.
   *  A bridge without Read to me answers 404 "No such endpoint": kind 'http', status 404. */
  async speech(id: string): Promise<{ audio: Blob; text: string }> {
    const base = this.base();
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), SPEECH_TIMEOUT_MS);
    try {
      let res: Response;
      try {
        res = await fetch(`${base}/api/sessions/${encodeURIComponent(id)}/speech`, {
          signal: ctl.signal,
          headers: { Authorization: `Bearer ${this.cfg().token}` },
        });
      } catch {
        throw new BridgeError(`Can't reach ${base} (${ctl.signal.aborted ? 'no sound in 30 s' : 'no connection'})`, 'down');
      }
      if (res.status === 401 || res.status === 403) throw new BridgeError('The bridge did not accept the token', 'auth', res.status);
      if (!res.ok) {
        let msg = `${res.status}`;
        try {
          const j = await res.json();
          msg = j.error || msg;
        } catch {}
        if (res.status === 404 && /session/i.test(msg)) throw new BridgeError('This session is gone from your Mac', 'gone', 404);
        throw new BridgeError(res.status === 404 ? 'This bridge has no Read to me yet' : `The bridge said: ${msg}`, 'http', res.status);
      }
      let text = '';
      try {
        text = decodeURIComponent(res.headers.get('X-Speech-Text') || '');
      } catch {}
      return { audio: await res.blob(), text };
    } finally {
      clearTimeout(timer);
    }
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
