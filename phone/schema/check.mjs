#!/usr/bin/env node
// Checks the phone contract (phone/DESIGN.md), with no dependencies:
//   1. The schemas follow the contract's rules: every object schema refuses fields it does not know
//      (additionalProperties: false) and every free string has a length cap.
//   2. Every fixture in phone/fixtures matches its schema.
//   3. A field planted in any object of any fixture makes it fail, so no part of a message is open.
//   4. Every case in phone/fixtures/invalid fails, for its own reason.
//   5. Each message the schema defines has at least one fixture, and asyncapi.yaml names the same messages.
// It knows the small part of JSON Schema 2020-12 that these schemas use, and stops on any other keyword.
// Run: node phone/schema/check.mjs
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const schemaDir = dirname(fileURLToPath(import.meta.url));
const phoneDir = dirname(schemaDir);
const fixtureDir = join(phoneDir, 'fixtures');
const docs = {};
const load = (name) => (docs[name] ??= JSON.parse(readFileSync(join(schemaDir, name), 'utf8')));
const SCHEMAS = ['snapshot.v1.json', 'archived.v1.json', 'messages.v1.json'];
const DIRECTIONS = ['server_to_mac', 'mac_to_server', 'phone_to_server', 'server_to_phone'];

const KNOWN = new Set(['$schema', '$id', '$defs', '$ref', 'title', 'description', 'type', 'const', 'enum',
  'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength',
  'pattern', 'minimum', 'maximum', 'oneOf', 'allOf', 'if', 'then', 'else']);

function resolve(ref, base) {
  const [file, frag = ''] = ref.split('#');
  const name = file || base;
  let node = load(name);
  for (const part of frag.split('/').filter(Boolean)) node = node?.[part.replace(/~1/g, '/').replace(/~0/g, '~')];
  if (node === undefined) throw new Error(`$ref ${ref} in ${base} points at nothing`);
  return [node, name];
}

const typeOf = (v) => (v === null ? 'null' : Array.isArray(v) ? 'array' : Number.isInteger(v) ? 'integer' : typeof v);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function validate(v, s, base, path, errs) {
  for (const k of Object.keys(s)) if (!KNOWN.has(k)) throw new Error(`${base}: keyword ${k} is not known to this check`);
  if (s.$ref) { const [t, b] = resolve(s.$ref, base); validate(v, t, b, path, errs); }
  const t = typeOf(v);
  if (s.type) {
    const types = [].concat(s.type);
    if (!types.includes(t) && !(t === 'integer' && types.includes('number'))) {
      errs.push(`${path}: is ${t}, must be ${types.join(' or ')}`);
      return;
    }
  }
  if ('const' in s && !same(v, s.const)) errs.push(`${path}: must be ${JSON.stringify(s.const)}`);
  if (s.enum && !s.enum.some((e) => same(e, v))) errs.push(`${path}: ${JSON.stringify(v)} is not one of ${s.enum.map(String).join(', ')}`);
  if (t === 'string') {
    const n = [...v].length;
    if (s.maxLength !== undefined && n > s.maxLength) errs.push(`${path}: ${n} characters, at most ${s.maxLength}`);
    if (s.minLength !== undefined && n < s.minLength) errs.push(`${path}: ${n} characters, at least ${s.minLength}`);
    if (s.pattern && !new RegExp(s.pattern, 'u').test(v)) errs.push(`${path}: ${JSON.stringify(v)} does not match ${s.pattern}`);
  }
  if (t === 'integer' || t === 'number') {
    if (s.minimum !== undefined && v < s.minimum) errs.push(`${path}: ${v} is under ${s.minimum}`);
    if (s.maximum !== undefined && v > s.maximum) errs.push(`${path}: ${v} is over ${s.maximum}`);
  }
  if (t === 'array') {
    if (s.maxItems !== undefined && v.length > s.maxItems) errs.push(`${path}: ${v.length} items, at most ${s.maxItems}`);
    if (s.minItems !== undefined && v.length < s.minItems) errs.push(`${path}: ${v.length} items, at least ${s.minItems}`);
    if (s.items) v.forEach((x, i) => validate(x, s.items, base, `${path}[${i}]`, errs));
  }
  if (t === 'object') {
    for (const r of s.required ?? []) if (!(r in v)) errs.push(`${path}: ${r} is missing`);
    for (const [k, x] of Object.entries(v)) {
      if (s.properties && k in s.properties) validate(x, s.properties[k], base, `${path}.${k}`, errs);
      else if (s.additionalProperties === false) errs.push(`${path}: ${k} is not a known field`);
    }
  }
  if (s.allOf) s.allOf.forEach((x) => validate(v, x, base, path, errs));
  if (s.oneOf) {
    const fits = s.oneOf.map((x) => { const e = []; validate(v, x, base, path, e); return e; });
    const good = fits.filter((e) => !e.length).length;
    if (good !== 1) {
      const best = fits.reduce((a, b) => (b.length < a.length ? b : a));
      errs.push(good ? `${path}: fits ${good} choices, must fit one` : `${path}: fits no choice (nearest: ${best.slice(0, 3).join('; ')})`);
    }
  }
  if (s.if) {
    const e = [];
    validate(v, s.if, base, path, e);
    if (!e.length && s.then) validate(v, s.then, base, path, errs);
    if (e.length && s.else) validate(v, s.else, base, path, errs);
  }
}

const check = (value, ref) => { const [s, b] = resolve(ref, 'messages.v1.json'); const errs = []; validate(value, s, b, '$', errs); return errs; };

let failures = 0;
const fail = (msg) => { failures++; console.log(`FAIL ${msg}`); };

// 1. The schemas' own rules.
function rules(node, file, path) {
  if (Array.isArray(node)) return node.forEach((x, i) => rules(x, file, `${path}/${i}`));
  if (!node || typeof node !== 'object') return;
  const types = [].concat(node.type ?? []);
  if (types.includes('object') && node.additionalProperties !== false) fail(`${file}${path}: an object schema must have "additionalProperties": false`);
  if (types.includes('string') && node.maxLength === undefined && !node.enum && !('const' in node)) fail(`${file}${path}: a string must have maxLength`);
  for (const [k, x] of Object.entries(node)) if (k !== 'enum' && k !== 'const') rules(x, file, `${path}/${k}`);
}
for (const f of SCHEMAS) rules(load(f), f, '#');

// 2 and 3. Fixtures match; a planted field fails.
function objects(v, path = '$', out = []) {
  if (Array.isArray(v)) v.forEach((x, i) => objects(x, `${path}[${i}]`, out));
  else if (v && typeof v === 'object') { out.push(path); for (const [k, x] of Object.entries(v)) objects(x, `${path}.${k}`, out); }
  return out;
}
function plantAt(v, path) {
  const copy = structuredClone(v);
  let node = copy;
  for (const m of path.slice(1).matchAll(/\.([^.[\]]+)|\[(\d+)\]/g)) node = node[m[1] ?? Number(m[2])];
  node.planted_extra = 'x';
  return copy;
}
const seen = new Set();
let valid = 0, planted = 0;
function expectValid(value, ref, label) {
  const errs = check(value, ref);
  if (errs.length) return fail(`${label}: ${errs.slice(0, 5).join('; ')}`);
  valid++;
  for (const p of objects(value)) {
    planted++;
    if (!check(plantAt(value, p), ref).length) fail(`${label}: a field planted at ${p} passed`);
  }
}
const read = (...p) => JSON.parse(readFileSync(join(fixtureDir, ...p), 'utf8'));
const files = (dir) => readdirSync(join(fixtureDir, dir)).filter((f) => f.endsWith('.json')).sort();

for (const f of files('.')) {
  if (f.startsWith('snapshot')) expectValid(read(f), 'snapshot.v1.json', f);
  else if (f.startsWith('archived-delta')) expectValid(read(f), 'archived.v1.json#/$defs/delta', f);
  else if (f.startsWith('archived')) expectValid(read(f), 'archived.v1.json#/$defs/list', f);
  else fail(`${f}: no schema for this name (snapshot*, archived*, archived-delta*)`);
}
for (const d of DIRECTIONS) {
  const list = read('messages', `${d}.json`);
  list.forEach((m, i) => {
    seen.add(`${d}.${m.event}`);
    expectValid(m, `messages.v1.json#/$defs/${d}`, `messages/${d}.json[${i}] ${m.event}`);
  });
}

// 4. Every invalid case fails.
let refused = 0;
for (const f of files('invalid')) {
  const target = f.replace(/\.json$/, '');
  const ref = target === 'snapshot' ? 'snapshot.v1.json' : target === 'archived' ? 'archived.v1.json' : `messages.v1.json#/$defs/${target}`;
  for (const c of read('invalid', f)) {
    const errs = check(c.value, ref);
    if (!errs.length) fail(`invalid/${f} "${c.why}": passed, must fail`);
    else refused++;
  }
}

// 5. Every message has a fixture, and asyncapi.yaml names the same messages.
const defs = Object.keys(load('messages.v1.json').$defs).filter((k) => DIRECTIONS.some((d) => k.startsWith(`${d}.`)));
for (const k of defs) {
  const ev = load('messages.v1.json').$defs[k].properties.event.const;
  if (`${k.split('.')[0]}.${ev}` !== k) fail(`messages.v1.json ${k}: its event is ${ev}`);
  if (!seen.has(k)) fail(`${k}: no fixture in phone/fixtures/messages`);
}
const api = readFileSync(join(phoneDir, 'asyncapi.yaml'), 'utf8');
const named = new Set([...api.matchAll(/messages\.v1\.json#\/\$defs\/([a-z_]+\.[a-z_]+)/g)].map((m) => m[1]));
for (const k of defs) if (!named.has(k)) fail(`asyncapi.yaml does not name ${k}`);
for (const k of named) if (!defs.includes(k)) fail(`asyncapi.yaml names ${k}, which messages.v1.json does not define`);

console.log(`${valid} fixtures match, ${planted} planted fields fail, ${refused} invalid cases fail, ${defs.length} messages in asyncapi.yaml`);
if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
console.log('Contract OK');
