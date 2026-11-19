import { defineConfig, type Plugin, type ViteDevServer } from 'vite';
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

// Dev server only, from this Mac only: hooks a test uses to drive the app
// in the simulator, whose phone page has no other way in without keys.
//   POST /__kit/typed     the body's words go in the app as if typed in the
//                         phone's box while the glasses listen (scripts/e2e.mjs)
//   POST /__kit/pictures  body "1" or "0": tables and glance cards as pictures,
//                         or lens text (scripts/pictures.mjs, glance-pictures.mjs)
//   POST /__kit/lab       the page goes to the glance lab, lab.html (src/lab.ts)
function kitDev(): Plugin {
  const hook = (server: ViteDevServer, path: string, event: string, data: (body: string) => object) =>
    server.middlewares.use(path, (req, res) => {
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
        server.ws.send({ type: 'custom', event, data: data(body) });
        res.end('sent\n');
      });
    });
  return {
    name: 'kit-dev',
    apply: 'serve',
    configureServer(server) {
      hook(server, '/__kit/typed', 'kit:typed', (b) => ({ text: b.trim().slice(0, 2000) }));
      hook(server, '/__kit/pictures', 'kit:pictures', (b) => ({ on: b.trim() !== '0' }));
      hook(server, '/__kit/lab', 'kit:lab', () => ({}));
    },
  };
}

export default defineConfig(({ command }) => ({
  // Relative asset paths: the .ehpk serves index.html from its own folder.
  base: './',
  plugins: [kitDev()],
  server: { host: true, port: 5181, strictPort: true },
  // VITE_* values (a dev bridge address and token) reach `npm run dev` only.
  // A build reads none of them, so no token can end up in an .ehpk.
  envPrefix: command === 'build' ? 'KIT_BUILD_NEVER_' : 'VITE_',
  define: {
    __DEFAULT_BRIDGE__: JSON.stringify(process.env.KIT_BRIDGE_URL || `http://${lanIp()}:8740`),
  },
  build: { target: 'es2020', outDir: 'dist', emptyOutDir: true },
}));
