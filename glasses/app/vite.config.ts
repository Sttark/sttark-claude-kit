import { defineConfig, type Plugin } from 'vite';
import { execFileSync } from 'node:child_process';

// The Mac's address on the plant network, so the phone's first guess at the
// bridge is this Mac. Not a secret; the token is never built in.
function lanIp(): string {
  for (const iface of ['en0', 'en1']) {
    try {
      const ip = execFileSync('ipconfig', ['getifaddr', iface]).toString().trim();
      if (ip) return ip;
    } catch {}
  }
  return '127.0.0.1';
}

// Dev server only: POST /__kit/typed with words in the body puts them in the
// app as if typed in the phone's box while the glasses listen. From this Mac
// only. A test drives the simulator with it (scripts/e2e.mjs): the
// simulator's phone page has no other way in without keys.
function kitTyped(): Plugin {
  return {
    name: 'kit-typed',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/__kit/typed', (req, res) => {
        const from = req.socket.remoteAddress || '';
        if (req.method !== 'POST' || !/^(127\.|::1$|::ffff:127\.)/.test(from)) {
          res.statusCode = 403;
          res.end('POST from this Mac only\n');
          return;
        }
        let body = '';
        req.setEncoding('utf8');
        req.on('data', (c: string) => (body += c));
        req.on('end', () => {
          server.ws.send({ type: 'custom', event: 'kit:typed', data: { text: body.trim().slice(0, 2000) } });
          res.end('sent\n');
        });
      });
    },
  };
}

export default defineConfig(({ command }) => ({
  // Relative asset paths: the .ehpk serves index.html from its own folder.
  base: './',
  plugins: [kitTyped()],
  server: { host: true, port: 5181, strictPort: true },
  // VITE_* values (a dev bridge address and token) reach `npm run dev` only.
  // A build reads none of them, so no token can end up in an .ehpk.
  envPrefix: command === 'build' ? 'KIT_BUILD_NEVER_' : 'VITE_',
  define: {
    __DEFAULT_BRIDGE__: JSON.stringify(process.env.KIT_BRIDGE_URL || `http://${lanIp()}:8740`),
  },
  build: { target: 'es2020', outDir: 'dist', emptyOutDir: true },
}));
