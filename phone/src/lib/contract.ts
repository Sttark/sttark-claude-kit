// The contract (schema/, asyncapi.yaml, phone/DESIGN.md) as the server
// checks it. Every message that comes in on /mac or /live, and the link
// request, is checked against its JSON Schema before anything reads it;
// each schema refuses fields it does not know. Every message the server
// sends is checked too, so the server never says what the contract does
// not allow. The schemas are bundled into the build: the deployed server
// has no schema/ folder.
import Ajv2020, { type ValidateFunction } from 'ajv/dist/2020.js';
import snapshotSchema from '../../schema/snapshot.v1.json';
import archivedSchema from '../../schema/archived.v1.json';
import usageSchema from '../../schema/usage.v1.json';
import messagesSchema from '../../schema/messages.v1.json';
import linkSchema from '../../schema/link.v1.json';

const MESSAGES = 'https://kit.sttark.com/schema/messages.v1.json';
const LINK = 'https://kit.sttark.com/schema/link.v1.json';

const ajv = new Ajv2020({ strict: false, allErrors: false });
for (const s of [snapshotSchema, archivedSchema, usageSchema, messagesSchema, linkSchema]) ajv.addSchema(s as object);

const compiled = new Map<string, ValidateFunction>();
function validator(ref: string): ValidateFunction {
  let v = compiled.get(ref);
  if (!v) {
    v = ajv.compile({ $ref: ref });
    compiled.set(ref, v);
  }
  return v;
}

export type Direction = 'server_to_mac' | 'mac_to_server' | 'phone_to_server' | 'server_to_phone';
export type Message = { event: string; success: boolean; payload: any };
export type Checked = { ok: true; message: Message } | { ok: false; why: string };

/** The events each direction may carry, from the schema's own defs. */
export const EVENTS: Record<Direction, Set<string>> = (() => {
  const out = {} as Record<Direction, Set<string>>;
  for (const d of ['server_to_mac', 'mac_to_server', 'phone_to_server', 'server_to_phone'] as Direction[]) {
    out[d] = new Set(Object.keys(messagesSchema.$defs).filter((k) => k.startsWith(`${d}.`)).map((k) => k.slice(d.length + 1)));
  }
  return out;
})();

/** Checks one message in one direction: its event, then the whole message
 *  against that event's schema. */
export function checkMessage(dir: Direction, value: unknown): Checked {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { ok: false, why: 'not an object' };
  const event = (value as { event?: unknown }).event;
  if (typeof event !== 'string' || !EVENTS[dir].has(event)) return { ok: false, why: `unknown event ${JSON.stringify(event)?.slice(0, 40)}` };
  const v = validator(`${MESSAGES}#/$defs/${dir}.${event}`);
  if (v(value)) return { ok: true, message: value as Message };
  return { ok: false, why: `${event}: ${ajv.errorsText(v.errors, { dataVar: 'message' })}`.slice(0, 300) };
}

/** Checks a value against a def of schema/link.v1.json (request, answer,
 *  poll, refusal). */
export function checkLink(def: 'request' | 'answer' | 'poll' | 'refusal', value: unknown): { ok: true } | { ok: false; why: string } {
  const v = validator(`${LINK}#/$defs/${def}`);
  if (v(value)) return { ok: true };
  return { ok: false, why: ajv.errorsText(v.errors, { dataVar: def }).slice(0, 300) };
}
