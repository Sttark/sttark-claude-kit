#!/usr/bin/env node
// Puts lens pictures side by side, each with a caption under it, in one PNG
// (docs/lens-screens.png, docs/end-to-end.png). Draws an SVG and turns it
// into a PNG with rsvg-convert (brew install librsvg).
//
//   import { sheet } from './sheet.mjs';
//   sheet([{ file: 'shots/01-home.png', title: 'Home.', text: 'Needs you first.' }], 'docs/x.png');
//
//   node scripts/sheet.mjs <frames.json> <out.png> [columns]
//     frames.json: [{"file": "...", "title": "...", "text": "..."}, ...]
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const FW = 576; // the lens
const FH = 288;
const GAP = 24;
const LINE = 20; // caption line height
const CHARS = 74; // caption characters a line, at 15 px Helvetica in 576 px

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Words in lines of at most CHARS characters; the first line starts after the bold title. */
function wrap(title, text) {
  const words = `${title} ${text}`.trim().split(/\s+/);
  const lines = [];
  let line = '';
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (next.length > CHARS && line) {
      lines.push(line);
      line = w;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

export function sheet(frames, out, columns = 2) {
  const cols = Math.min(columns, frames.length);
  const rows = Math.ceil(frames.length / cols);
  const captions = frames.map((f) => wrap(f.title || '', f.text || ''));
  const capLines = Math.max(...captions.map((c) => c.length));
  const cellH = FH + 2 + 10 + capLines * LINE + GAP;
  const W = GAP + cols * (FW + 2 + GAP);
  const H = GAP + rows * cellH;
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`,
    `<rect width="${W}" height="${H}" fill="#161618"/>`,
  ];
  frames.forEach((f, i) => {
    const x = GAP + (i % cols) * (FW + 2 + GAP);
    const y = GAP + Math.floor(i / cols) * cellH;
    const png = readFileSync(resolve(f.file)).toString('base64');
    parts.push(`<rect x="${x}" y="${y}" width="${FW + 2}" height="${FH + 2}" fill="#000" stroke="#3a3a3e" stroke-width="1"/>`);
    parts.push(`<image x="${x + 1}" y="${y + 1}" width="${FW}" height="${FH}" xlink:href="data:image/png;base64,${png}"/>`);
    const title = (f.title || '').trim();
    captions[i].forEach((line, j) => {
      const ty = y + FH + 2 + 10 + (j + 1) * LINE - 5;
      let body = esc(line);
      if (j === 0 && title && line.startsWith(title)) {
        body = `<tspan font-weight="bold">${esc(title)}</tspan>${esc(line.slice(title.length))}`;
      }
      parts.push(`<text x="${x}" y="${ty}" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="15" fill="#f2f2f2" xml:space="preserve">${body}</text>`);
    });
  });
  parts.push('</svg>');
  const svg = out.replace(/\.png$/, '.svg');
  writeFileSync(svg, parts.join('\n'));
  try {
    execFileSync('rsvg-convert', ['-o', out, svg]);
  } finally {
    execFileSync('rm', ['-f', svg]);
  }
  return out;
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const [spec, out, cols] = process.argv.slice(2);
  if (!spec || !out) {
    console.error('usage: node scripts/sheet.mjs <frames.json> <out.png> [columns]');
    process.exit(1);
  }
  console.log(sheet(JSON.parse(readFileSync(spec, 'utf8')), out, Number(cols) || 2));
}
