// What one part of the server tells the others, without importing them: a
// Mac linked or removed, a roster sync done, a reminder from a Mac, a change
// in a person's phones that get notices. The sockets (lib/hub.ts) and the
// Web Push sender (lib/push.ts) listen; the database code only says what
// happened.
// One emitter per process, kept on globalThis so a dev reload that runs a
// module again still reaches the same listeners.
import { EventEmitter } from 'node:events';

export type KitEvents = {
  /** A Mac was linked to this person. */
  'mac-linked': [{ macId: string; email: string }];
  /** A Mac was removed: its socket must close. */
  'mac-removed': [{ macId: string; email: string; why: RemovedWhy }];
  /** A good roster was stored: whoever is off it loses their sockets. */
  'roster-synced': [];
  /** A session needed its person for 10 minutes while they were away from
   *  the Mac (mac_to_server.remind). The Web Push sender listens
   *  (lib/push.ts); `visible` says one of the person's pages shows now. */
  remind: [{ macId: string; email: string; cse: string; waitingSince: number; title: string; why: string | null; visible: boolean }];
  /** How many of this person's phones can get a push may have changed (a
   *  phone turned notices on or off, signed out, or is gone): the sockets
   *  tell the person's Macs (server_to_mac.phones). */
  'push-subs-changed': [{ email: string }];
};

/** Why a Mac was removed (macs.removed_why). */
export type RemovedWhy = 'phone' | 'mac' | 'roster' | 'quiet';

const KEY = Symbol.for('sttark.kit.events');
const g = globalThis as Record<symbol, unknown>;
export const events: EventEmitter<KitEvents> = (g[KEY] ??= new EventEmitter<KitEvents>()) as EventEmitter<KitEvents>;
events.setMaxListeners(50);
