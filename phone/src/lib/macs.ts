// A person's linked Macs (macs, lib/db.ts): the ones not removed.
import { db } from './db.ts';
import { addRecord } from './records.ts';

export type Mac = { id: string; name: string; linkedAt: number; lastSeen: number | null };

export function macsOf(email: string): Mac[] {
  return db()
    .prepare('SELECT id, name, linked_at AS linkedAt, last_seen AS lastSeen FROM macs WHERE email = ? AND removed_at IS NULL ORDER BY name')
    .all(email) as Mac[];
}

/** Remove from the phone (Menu > Macs > Remove): the person's own Mac is
 *  marked removed (its row stays, with when, why and by whom), what it last
 *  sent is deleted, and the change is recorded. The socket server closes
 *  its socket through the hook at sttark.kit.macRemoved, when one is set.
 *  False when it is not this person's linked Mac. */
export function removeMac(user: { email: string; name: string }, macId: string, now = Math.floor(Date.now() / 1000)): boolean {
  const d = db();
  const mac = d.prepare('SELECT id, name FROM macs WHERE id = ? AND email = ? AND removed_at IS NULL').get(macId, user.email) as { id: string; name: string } | undefined;
  if (!mac) return false;
  d.transaction(() => {
    d.prepare("UPDATE macs SET removed_at = ?, removed_why = 'phone', removed_by = ? WHERE id = ?").run(now, user.email, mac.id);
    d.prepare('DELETE FROM snapshots WHERE mac_id = ?').run(mac.id);
    d.prepare('DELETE FROM archived WHERE mac_id = ?').run(mac.id);
    addRecord({ at: now, who: user.email, whoName: user.name, macId: mac.id, macName: mac.name, action: 'remove_mac', before: { linked: true }, after: { linked: false }, result: 'ok', words: `Removed ${mac.name} from the phone.` });
  })();
  const hook = (globalThis as Record<symbol, unknown>)[Symbol.for('sttark.kit.macRemoved')];
  if (typeof hook === 'function') hook(mac.id);
  return true;
}
