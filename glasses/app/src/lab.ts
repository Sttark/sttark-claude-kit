// Dev server only (lab.html; a build has none of it): a glance card drawn
// as a picture, a big bold title and 24 px lines, beside the same card in
// the lens's own text, to compare them on the lens. Swipe for the next
// card. Made-up plant work only. scripts/pictures.mjs takes their pictures.
import { waitForEvenAppBridge } from '@evenrealities/even_hub_sdk';
import { toInput } from './events';
import { Glasses, type PageSpec } from './glasses';
import { hash, pictureBoxes } from './picture';
import { fit, width } from './text';

interface Card {
  title: string;
  chip: string;
  lines: string[];
  you: string;
}

const CARDS: Card[] = [
  { title: 'Press 3 nozzle report', chip: 'NEEDS YOU', lines: ['Heads 2 and 4: nozzles out', 'Job 4471 is next on Press 3'], you: 'You: pick the fix' },
  { title: 'Laminate quote', chip: 'WORKING', lines: ['✓ Two prices are in', '▷ Waits on Midway Bearing'], you: 'You: nothing now' },
];

const FAMILY = 'system-ui, -apple-system, "Helvetica Neue", Roboto, Arial, sans-serif';
const W = 560;
const H = 176;

function drawCard(c: Card): HTMLCanvasElement {
  const cv = document.createElement('canvas');
  cv.width = W;
  cv.height = H;
  const g = cv.getContext('2d')!;
  g.fillStyle = '#000';
  g.fillRect(0, 0, W, H);
  g.textBaseline = 'alphabetic';
  // The status, in a box at the right.
  g.font = `bold 20px ${FAMILY}`;
  const cw = Math.ceil(g.measureText(c.chip).width) + 20;
  g.strokeStyle = '#ffffff';
  g.lineWidth = 2;
  g.beginPath();
  g.roundRect(W - cw - 1, 5, cw, 32, 6);
  g.stroke();
  g.fillStyle = '#ffffff';
  g.fillText(c.chip, W - cw + 9, 28);
  // The title, big and bold, cut to the room left of the box.
  g.font = `bold 34px ${FAMILY}`;
  let t = c.title;
  while (t.length > 3 && g.measureText(t).width > W - cw - 16) t = t.slice(0, -2).trimEnd() + '…';
  g.fillText(t, 0, 34);
  g.font = `24px ${FAMILY}`;
  c.lines.forEach((l, i) => g.fillText(l, 0, 84 + i * 36));
  g.fillStyle = '#9a9a9a';
  g.fillText(c.you, 0, 84 + c.lines.length * 36);
  return cv;
}

function picturePage(c: Card): PageSpec {
  return {
    texts: [{ name: 'capture', x: 0, y: 0, w: 576, h: 288, content: ' ', capture: true }],
    images: pictureBoxes(hash(JSON.stringify(c)), W, H, 8, 8, () => drawCard(c)),
  };
}

/** The same card in the lens's own font: one size, brightness for the "You" line, a border for the status. */
function textPage(c: Card): PageSpec {
  const chipW = width(c.chip) + 24;
  return {
    texts: [
      { name: 'title', x: 8, y: 4, w: 560 - chipW - 8, h: 32, content: fit(c.title, 560 - chipW - 16) },
      { name: 'chip', x: 568 - chipW, y: 0, w: chipW, h: 40, content: c.chip, border: 2, borderColor: 15, radius: 6, pad: 4 },
      { name: 'body', x: 8, y: 52, w: 560, h: 2 * 27 + 4, content: c.lines.join('\n'), capture: true },
      { name: 'you', x: 8, y: 52 + 2 * 27 + 4, w: 560, h: 30, content: c.you, color: 2 },
    ],
  };
}

/** Gray steps, to read how the lens shows each gray: the top box has all 16
 *  (0, 17, ... 255), the lower one only 0 to 119, to see whether the
 *  brightest gray in a picture is stretched to full. */
function swatches(top: number): () => HTMLCanvasElement {
  return () => {
    const cv = document.createElement('canvas');
    cv.width = 288;
    cv.height = 60;
    const g = cv.getContext('2d')!;
    for (let k = 0; k < 16; k++) {
      const v = Math.round((k * top) / 15);
      g.fillStyle = `rgb(${v},${v},${v})`;
      g.fillRect(k * 18, 0, 18, 60);
    }
    return cv;
  };
}

const grays: PageSpec = {
  texts: [{ name: 'capture', x: 0, y: 0, w: 576, h: 288, content: ' ', capture: true }],
  images: [
    ...pictureBoxes('gray255', 288, 60, 8, 20, swatches(255)),
    ...pictureBoxes('gray119', 288, 60, 8, 120, swatches(119)).map((b) => ({ ...b, name: 'pic9' })),
  ],
};

const screens: { name: string; page: () => PageSpec }[] = [
  ...CARDS.flatMap((c, i) => [
    { name: `lab:glance${i + 1}-picture`, page: () => picturePage(c) },
    { name: `lab:glance${i + 1}-text`, page: () => textPage(c) },
  ]),
  { name: 'lab:grays', page: () => grays },
];

async function boot(): Promise<void> {
  const even = await waitForEvenAppBridge();
  const lens = new Glasses(even);
  let at = Math.max(0, Math.min(screens.length - 1, Number(new URLSearchParams(location.search).get('at')) || 0));
  const show = () => {
    console.log(`[kit] screen ${screens[at].name}`);
    lens.show(screens[at].page());
  };
  even.onEvenHubEvent((ev) => {
    const input = toInput(ev);
    if (input?.kind !== 'down' && input?.kind !== 'up') return;
    const next = Math.max(0, Math.min(screens.length - 1, at + (input.kind === 'down' ? 1 : -1)));
    if (next === at) return;
    at = next;
    show();
  });
  show();
  document.body.textContent = 'Glance lab: swipe on the lens for the next card.';
}

void boot();
