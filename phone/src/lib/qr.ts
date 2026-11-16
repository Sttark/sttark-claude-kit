// A QR code as an SVG drawn in currentColor (the link page's "On your
// phone, open ..."). One path of squares on a quiet zone of four modules,
// which the style puts on a light ground in both themes, since a phone's
// camera reads dark on light best.
import { encode } from 'uqr';

export function qrSvg(text: string, label: string): string {
  const { data, size } = encode(text, { ecc: 'M', border: 0 });
  const quiet = 4;
  const n = size + quiet * 2;
  let d = '';
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) if (data[y][x]) d += `M${x + quiet} ${y + quiet}h1v1h-1z`;
  }
  const esc = label.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" role="img" aria-label="${esc}"><path fill="currentColor" d="${d}"/></svg>`;
}
