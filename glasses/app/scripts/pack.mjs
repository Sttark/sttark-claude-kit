#!/usr/bin/env node
// Packs the built app (dist/) into kit-glasses-<version>.ehpk for the Even app.
// The Even app only lets the app reach the addresses its app.json lists, so
// the packed copy lists this Mac's bridge: http://<LAN address>:8740, or
// KIT_BRIDGE_URL. KIT_BRIDGE_ORIGINS adds more (comma separated), and
// KIT_WHITELIST_ANY=1 adds "*" (the Even docs say wildcards are not
// supported; it packs, but it is not tried on glasses yet). No token is ever
// packed: the phone panel asks for it.
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(readFileSync(join(app, 'app.json'), 'utf8'));
const pkg = JSON.parse(readFileSync(join(app, 'package.json'), 'utf8'));
if (manifest.version !== pkg.version) {
  console.error(`pack: app.json version ${manifest.version} and package.json version ${pkg.version} differ. Make them the same.`);
  process.exit(1);
}

function lanIp() {
  for (const iface of ['en0', 'en1']) {
    try {
      const ip = execFileSync('ipconfig', ['getifaddr', iface]).toString().trim();
      if (ip) return ip;
    } catch {}
  }
  return null;
}

const origins = new Set();
const main = process.env.KIT_BRIDGE_URL || (lanIp() ? `http://${lanIp()}:8740` : null);
if (main) origins.add(new URL(main).origin);
for (const o of (process.env.KIT_BRIDGE_ORIGINS || '').split(',').map((s) => s.trim()).filter(Boolean)) origins.add(new URL(o).origin);
if (process.env.KIT_WHITELIST_ANY) origins.add('*');
if (!origins.size) {
  console.error('pack: no bridge address. Set KIT_BRIDGE_URL, for example http://192.168.1.20:8740.');
  process.exit(1);
}

const net = manifest.permissions.find((p) => p.name === 'network');
net.whitelist = [...origins];
mkdirSync(join(app, '.pack'), { recursive: true });
const packed = join(app, '.pack', 'app.json');
writeFileSync(packed, JSON.stringify(manifest, null, 2) + '\n');

const sdk = JSON.parse(readFileSync(join(app, 'node_modules', '@evenrealities', 'even_hub_sdk', 'package.json'), 'utf8')).version;
const out = join(app, `kit-glasses-${pkg.version}.ehpk`);
execFileSync('npx', ['evenhub', 'pack', packed, join(app, 'dist'), '-o', out, '--sdk-ver', sdk], { stdio: 'inherit', cwd: app });
console.log(`pack: ${out}\npack: the app may reach ${[...origins].join(', ')}`);
