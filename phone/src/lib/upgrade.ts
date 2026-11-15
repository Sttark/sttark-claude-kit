// The WebSocket hook. server.mjs passes every upgrade request on its port
// (the Kit on each Mac at /mac, the phone pages at /live) to the one
// handler set here, at a global the built server code and server.mjs both
// reach. None is set yet, so server.mjs refuses every upgrade; the module
// that serves the sockets calls onUpgrade() when it loads.
import type { IncomingMessage } from 'node:http';
import type { Duplex } from 'node:stream';

export const UPGRADE = Symbol.for('sttark.kit.upgrade');
export type UpgradeHandler = (req: IncomingMessage, socket: Duplex, head: Buffer) => void;

/** Sets the handler server.mjs passes every upgrade to. */
export function onUpgrade(handler: UpgradeHandler): void {
  (globalThis as Record<symbol, unknown>)[UPGRADE] = handler;
}
