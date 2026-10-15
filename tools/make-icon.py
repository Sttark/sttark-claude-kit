"""Makes Resources/AppIcon.icns: a white gauge with a green needle on the black rounded square the Sttark
brand guide uses for app icons. The menu bar draws the same gauge in code (Sources/Menu.swift, GaugeIcon),
with the needle at the current level. Run: python3 tools/make-icon.py   (needs Google Chrome to draw it)"""
import math, os, shutil, subprocess, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cx, cy, R = 512, 600, 250
arc = ' '.join('%.1f,%.1f' % (cx + R * math.cos(math.radians(a)), cy - R * math.sin(math.radians(a))) for a in range(0, 181, 3))
dots = ''.join('<circle cx="%.1f" cy="%.1f" r="18" fill="#5B6570"/>' % (cx + (R - 80) * math.cos(math.radians(a)), cy - (R - 80) * math.sin(math.radians(a))) for a in (170, 130, 90, 50, 10))
a, L = math.radians(50), R - 70
svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">'
       '<rect x="100" y="100" width="824" height="824" rx="185" fill="#000"/>'
       f'<polyline points="{arc}" fill="none" stroke="#fff" stroke-width="56" stroke-linecap="round"/>{dots}'
       f'<line x1="{cx}" y1="{cy}" x2="{cx + L * math.cos(a):.1f}" y2="{cy - L * math.sin(a):.1f}" stroke="#00A82D" stroke-width="52" stroke-linecap="round"/>'
       f'<circle cx="{cx}" cy="{cy}" r="58" fill="#fff"/></svg>')
tmp = tempfile.mkdtemp()
open(os.path.join(tmp, 'icon.html'), 'w').write('<html><body style="margin:0;background:transparent">' + svg + '</body></html>')
png = os.path.join(tmp, 'icon.png')
c = subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '--headless=new', '--user-data-dir=' + os.path.join(tmp, 'c'),
                      '--hide-scrollbars', '--window-size=1024,1024', '--default-background-color=00000000', '--screenshot=' + png,
                      'file://' + os.path.join(tmp, 'icon.html')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):  # headless Chrome can stay open after the shot, so wait for the file
    if os.path.exists(png) and os.path.getsize(png) > 0: time.sleep(1); break
    time.sleep(0.5)
c.kill()
iconset = os.path.join(tmp, 'AppIcon.iconset'); os.makedirs(iconset)
for size in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = size * scale
        subprocess.run(['sips', '-z', str(px), str(px), png, '--out', os.path.join(iconset, 'icon_%dx%d%s.png' % (size, size, '@2x' if scale == 2 else ''))], capture_output=True)
subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', os.path.join(ROOT, 'Resources', 'AppIcon.icns')], check=True)
shutil.rmtree(tmp)
print('wrote Resources/AppIcon.icns')
