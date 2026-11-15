#!/usr/bin/env node
// A stand-in push service for local runs and tests, never a real one: it
// makes subscriptions of its own as a browser would (a P-256 key pair and an
// auth secret per phone), takes the server's Web Push requests at their
// endpoints, checks each VAPID signature (RFC 8292), decrypts each payload
// (RFC 8291, aes128gcm) and keeps what it got. The server sends to it only on
// a local run: in production it refuses an endpoint on this computer
// (lib/push.ts, allowedEndpoint).
//
//   node tools/push-sink.mjs [--port 0] [--subscription <file>] [--out <file>]
//
// --subscription writes one phone's subscription, as PushSubscription.toJSON()
// gives it, for a test to post to /api/push/subscribe; --out gets one JSON
// line per push it takes. The server's tests use startSink().
import { createServer } from 'node:http';
import { createDecipheriv, createECDH, createPublicKey, hkdfSync, randomBytes, verify } from 'node:crypto';
import { appendFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const b64u = (b) => Buffer.from(b).toString('base64url');

/** An aes128gcm Web Push body, decrypted with the phone's keys. */
export function decrypt(body, phone) {
  const salt = body.subarray(0, 16);
  const idlen = body[20];
  const sender = body.subarray(21, 21 + idlen);
  const data = body.subarray(21 + idlen);
  const shared = phone.ecdh.computeSecret(sender);
  const info = Buffer.concat([Buffer.from('WebPush: info\0'), phone.ecdh.getPublicKey(), sender]);
  const ikm = Buffer.from(hkdfSync('sha256', shared, phone.auth, info, 32));
  const cek = Buffer.from(hkdfSync('sha256', ikm, salt, Buffer.from('Content-Encoding: aes128gcm\0'), 16));
  const nonce = Buffer.from(hkdfSync('sha256', ikm, salt, Buffer.from('Content-Encoding: nonce\0'), 12));
  const d = createDecipheriv('aes-128-gcm', cek, nonce);
  d.setAuthTag(data.subarray(data.length - 16));
  const plain = Buffer.concat([d.update(data.subarray(0, data.length - 16)), d.final()]);
  let end = plain.length - 1;
  while (end >= 0 && plain[end] === 0) end--;
  if (plain[end] !== 2) throw new Error('the last record does not end with its delimiter');
  return plain.subarray(0, end).toString('utf8');
}

/** The VAPID header: its claims, when the signature is good with its key. */
export function vapidOf(header) {
  const m = /^vapid t=([^,\s]+),\s*k=([A-Za-z0-9_-]+)$/.exec(header ?? '');
  if (!m) throw new Error('no vapid Authorization header');
  const [head, claims, sig] = m[1].split('.');
  const raw = Buffer.from(m[2], 'base64url');
  const key = createPublicKey({ key: { kty: 'EC', crv: 'P-256', x: b64u(raw.subarray(1, 33)), y: b64u(raw.subarray(33, 65)) }, format: 'jwk' });
  const good = verify('sha256', Buffer.from(`${head}.${claims}`), { key, dsaEncoding: 'ieee-p1363' }, Buffer.from(sig, 'base64url'));
  if (!good) throw new Error('the VAPID signature is wrong');
  return { ...JSON.parse(Buffer.from(claims, 'base64url').toString('utf8')), key: m[2] };
}

/** Starts the stand-in on 127.0.0.1. */
export async function startSink({ port = 0, onPush } = {}) {
  const phones = new Map();
  const answers = new Map();
  const received = [];
  const server = createServer(async (req, res) => {
    const parts = [];
    for await (const p of req) parts.push(p);
    const body = Buffer.concat(parts);
    const name = decodeURIComponent((req.url ?? '').replace(/^\/push\//, ''));
    const phone = phones.get(name);
    if (req.method !== 'POST' || !phone) {
      res.writeHead(404).end();
      return;
    }
    const got = { at: Date.now(), phone: name, ttl: req.headers.ttl, urgency: req.headers.urgency, topic: req.headers.topic, encoding: req.headers['content-encoding'], vapid: null, payload: null, problem: null };
    try {
      got.vapid = vapidOf(req.headers.authorization);
      const text = decrypt(body, phone);
      try {
        got.payload = JSON.parse(text);
      } catch {
        got.payload = text;
      }
    } catch (e) {
      got.problem = e.message;
    }
    received.push(got);
    onPush?.(got);
    const status = answers.get(name) ?? 201;
    res.writeHead(status).end();
  });
  await new Promise((done) => server.listen(port, '127.0.0.1', done));
  const url = `http://127.0.0.1:${server.address().port}`;
  return {
    url,
    received,
    /** A new phone's subscription, as PushSubscription.toJSON() gives it. */
    subscription(name = `phone-${phones.size + 1}`) {
      const ecdh = createECDH('prime256v1');
      ecdh.generateKeys();
      const auth = randomBytes(16);
      phones.set(name, { ecdh, auth });
      return { endpoint: `${url}/push/${encodeURIComponent(name)}`, expirationTime: null, keys: { p256dh: b64u(ecdh.getPublicKey()), auth: b64u(auth) } };
    },
    /** How it answers that phone's pushes from now: 201, or 410 for a phone
     *  whose subscription is gone. */
    answer(name, status) {
      answers.set(name, status);
    },
    close: () => new Promise((done) => { server.closeAllConnections?.(); server.close(() => done()); }),
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const arg = (k, d) => {
    const i = process.argv.indexOf(k);
    return i >= 0 ? process.argv[i + 1] : d;
  };
  const out = arg('--out');
  const sink = await startSink({
    port: Number(arg('--port', 0)),
    onPush: (got) => {
      const line = JSON.stringify(got);
      console.log(`push: ${line}`);
      if (out) appendFileSync(out, line + '\n');
    },
  });
  const sub = sink.subscription('phone-1');
  if (arg('--subscription')) writeFileSync(arg('--subscription'), JSON.stringify(sub) + '\n');
  console.log(`push sink: ${sink.url} (subscription ${sub.endpoint})`);
}
