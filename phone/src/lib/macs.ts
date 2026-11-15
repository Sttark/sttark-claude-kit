// A person's linked Macs (macs, lib/db.ts): the ones not removed.
import { db } from './db.ts';

export type Mac = { id: string; name: string; linkedAt: number; lastSeen: number | null };

export function macsOf(email: string): Mac[] {
  return db()
    .prepare('SELECT id, name, linked_at AS linkedAt, last_seen AS lastSeen FROM macs WHERE email = ? AND removed_at IS NULL ORDER BY name')
    .all(email) as Mac[];
}
