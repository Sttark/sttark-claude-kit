// Plays the What's new pictures in the app's own views, off the screen, to see that each GIF moves as it should:
// the What's new page and each note's bigger picture, light and dark, with the model read again every 3 seconds as
// the window does. Every 0.25 seconds it captures each picture and finds the GIF frame it shows, and prints the
// frames it saw and each jump back before the loop's end (a GIF that starts again too early). It writes a sheet of
// the captures for each note, look and view into <folder>. `switch` plays the page only, and changes the look to
// dark at one third of the time and back to light at two thirds: the picture must go on from the same frame.
// Nothing shows on the screen and nothing comes to the front. Uses made-up state in a temporary folder.
// Run from the repo root, with <seconds> longer than the longest GIF's loop:
//   swiftc -parse-as-library -o /tmp/motion tools/whats-new-motion.swift $(ls Sources/*.swift | grep -v main.swift)
//   /tmp/motion . /tmp/motion-out 20 [switch]
import AppKit
import SwiftUI
import ImageIO

struct Gif { let frames: [CGImage]; let delays: [Double]
    var total: Double { delays.reduce(0, +) }
    static func load(_ url: URL) -> Gif {
        let s = CGImageSourceCreateWithURL(url as CFURL, nil)!
        var f: [CGImage] = [], d: [Double] = []
        for i in 0..<CGImageSourceGetCount(s) {
            f.append(CGImageSourceCreateImageAtIndex(s, i, nil)!)
            let p = CGImageSourceCopyPropertiesAtIndex(s, i, nil) as? [String: Any] ?? [:]
            let g = p[kCGImagePropertyGIFDictionary as String] as? [String: Any] ?? [:]
            d.append((g[kCGImagePropertyGIFUnclampedDelayTime as String] as? Double) ?? (g[kCGImagePropertyGIFDelayTime as String] as? Double) ?? 0.1)
        }
        return Gif(frames: f, delays: d)
    }
}

/// A small gray thumbnail for comparing pictures.
func thumb(_ img: CGImage, inset: CGFloat = 0.03) -> [UInt8] {
    let w = 110, h = 60
    let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w, space: CGColorSpaceCreateDeviceGray(),
                        bitmapInfo: CGImageAlphaInfo.none.rawValue)!
    ctx.interpolationQuality = .medium
    let iw = CGFloat(img.width), ih = CGFloat(img.height)
    let crop = img.cropping(to: CGRect(x: iw * inset, y: ih * inset, width: iw * (1 - 2 * inset), height: ih * (1 - 2 * inset)))!
    ctx.draw(crop, in: CGRect(x: 0, y: 0, width: w, height: h))
    let p = ctx.data!.assumingMemoryBound(to: UInt8.self)
    return Array(UnsafeBufferPointer(start: p, count: w * h))
}
func diff(_ a: [UInt8], _ b: [UInt8]) -> Double {
    var s = 0; for i in 0..<a.count { s += abs(Int(a[i]) - Int(b[i])) }; return Double(s) / Double(a.count)
}

func views(_ v: NSView, label: String) -> [NSView] {
    var out: [NSView] = []
    if (v.accessibilityLabel() ?? "") == label { out.append(v) }
    for s in v.subviews { out += views(s, label: label) }
    return out
}

/// The window's own drawing of a rect (window points, from the bottom left), at 2x.
func grab(_ w: NSWindow, _ r: NSRect) -> CGImage {
    let v = w.contentView!
    let rr = v.convert(r, from: nil)
    let rep = v.bitmapImageRepForCachingDisplay(in: rr)!
    v.cacheDisplay(in: rr, to: rep)
    return rep.cgImage!
}

func savePNG(_ img: CGImage, _ path: String) {
    let rep = NSBitmapImageRep(cgImage: img)
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
}

struct Shot { let t: Double; let img: CGImage; let frame: Int; let d: Double; let dark: Bool }

/// A grid of captures with their times and frame numbers.
func sheet(_ shots: [Shot], title: String, cols: Int, cell: CGFloat, to path: String) {
    guard let first = shots.first else { return }
    let ratio = CGFloat(first.img.height) / CGFloat(first.img.width)
    let ch = cell * ratio, lab: CGFloat = 22, pad: CGFloat = 10, head: CGFloat = 40
    let rows = (shots.count + cols - 1) / cols
    let W = pad + CGFloat(cols) * (cell + pad), H = head + CGFloat(rows) * (ch + lab + pad) + pad
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(W * 2), pixelsHigh: Int(H * 2), bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: W, height: H)
    NSGraphicsContext.saveGraphicsState()
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    ctx.cgContext.translateBy(x: 0, y: H); ctx.cgContext.scaleBy(x: 1, y: -1)
    NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx.cgContext, flipped: true)
    NSColor(white: 0.5, alpha: 1).setFill(); NSRect(x: 0, y: 0, width: W, height: H).fill()
    let a: [NSAttributedString.Key: Any] = [.font: NSFont.boldSystemFont(ofSize: 16), .foregroundColor: NSColor.white]
    NSAttributedString(string: title, attributes: a).draw(at: NSPoint(x: pad, y: 10))
    for (i, s) in shots.enumerated() {
        let x = pad + CGFloat(i % cols) * (cell + pad), y = head + CGFloat(i / cols) * (ch + lab + pad)
        let la: [NSAttributedString.Key: Any] = [.font: NSFont.monospacedSystemFont(ofSize: 12, weight: .medium), .foregroundColor: NSColor.white]
        NSAttributedString(string: String(format: "%.2fs  frame %d", s.t, s.frame), attributes: la).draw(at: NSPoint(x: x, y: y + 2))
        NSImage(cgImage: s.img, size: .zero).draw(in: NSRect(x: x, y: y + lab, width: cell, height: ch), from: .zero, operation: .sourceOver,
                                                  fraction: 1, respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
    }
    NSGraphicsContext.restoreGraphicsState()
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
    print("wrote \(path)")
}

@main struct Motion {
    @MainActor static func main() {
        let args = CommandLine.arguments
        let repo = args[1], out = args[2], seconds = Double(args[3])!
        let switchLook = args.count > 4 && args[4] == "switch"
        FileManager.default.changeCurrentDirectoryPath(repo)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-motion-\(getpid())")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        defer { try? FileManager.default.removeItem(at: dir) }
        let notesDir = dir.appendingPathComponent("whats-new")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = ["tools/whats-new.py", "build", notesDir.path]
        p.standardOutput = FileHandle.nullDevice
        try! p.run(); p.waitUntilExit()
        setenv("STTARK_WHATS_NEW_DIR", notesDir.path, 1)
        try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)

        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        app.finishLaunching()

        let notes = WhatsNew.all.filter { $0.picture.hasSuffix(".gif") }
        var gifs: [String: Gif] = [:]
        for n in notes {
            gifs[n.picture] = Gif.load(notesDir.appendingPathComponent(n.picture))
            if let d = n.picture_dark { gifs[d] = Gif.load(notesDir.appendingPathComponent(d)) }
        }
        var thumbs: [String: [[UInt8]]] = [:]
        for (k, g) in gifs { thumbs[k] = g.frames.map { thumb($0) } }

        let model = KitModel()
        model.reload()
        model.page = .news
        let w = NSWindow(contentRect: NSRect(x: -9000, y: 0, width: 1180, height: 1500),
                         styleMask: [.titled, .closable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        w.titleVisibility = .hidden; w.titlebarAppearsTransparent = true; w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: KitRoot(model: model))
        w.setFrame(NSRect(x: -9000, y: 0, width: 1180, height: 1500), display: true)
        // the window's own refresh: every 3 seconds
        let tick = Timer(timeInterval: 3, repeats: true) { _ in MainActor.assumeIsolated { model.reload() } }
        if ProcessInfo.processInfo.environment["NO_TICK"] == nil { RunLoop.main.add(tick, forMode: .common) }

        let looks: [Bool] = switchLook ? [false] : ProcessInfo.processInfo.environment["LIGHT_ONLY"] != nil ? [false] : [false, true]
        for dark in looks {
            w.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            let runs: [(Bool, [WhatsNew.Note])] = [(false, notes)] + (switchLook ? [] : notes.map { (true, [$0]) })
            for (big, targets) in runs {
                model.big = nil
                RunLoop.main.run(until: Date().addingTimeInterval(0.3))
                if big { model.big = targets[0] }
                w.orderFrontRegardless()
                RunLoop.main.run(until: Date().addingTimeInterval(0.25))
                let start = Date()
                var shots: [String: [Shot]] = [:]
                var k = 0
                var switched = false
                while true {
                    let due = start.addingTimeInterval(Double(k) * 0.25)
                    if due.timeIntervalSinceNow > 0 { RunLoop.main.run(until: due) }
                    let t = Date().timeIntervalSince(start)
                    if t > seconds { break }
                    if switchLook && t >= Double(switched ? 2 : 1) * seconds / 3 - 0.01 && !(switched && w.appearance?.name == .aqua) {
                        w.appearance = NSAppearance(named: switched ? .aqua : .darkAqua); switched = true
                        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
                    }
                    let isDark = w.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                    for n in targets {
                        let vs = views(w.contentView!, label: n.alt)
                        guard let v = big ? vs.max(by: { $0.bounds.width < $1.bounds.width }) : vs.min(by: { $0.bounds.width < $1.bounds.width }) else { continue }
                        let r = v.convert(v.bounds, to: nil)
                        let img = grab(w, r.insetBy(dx: -6, dy: -6))
                        let inner = grab(w, r)
                        let key = isDark ? (n.picture_dark ?? n.picture) : n.picture
                        let th = thumb(inner)
                        var best = -1, bd = 1e9
                        for (i, f) in thumbs[key]!.enumerated() { let d = diff(th, f); if d < bd { bd = d; best = i } }
                        shots[n.id, default: []].append(Shot(t: t, img: img, frame: best, d: bd, dark: isDark))
                    }
                    k += 1
                }
                let look = switchLook ? "switch" : dark ? "dark" : "light"
                for n in targets {
                    let s = shots[n.id] ?? []
                    let where_ = big ? "enlarged" : "page"
                    let g = gifs[n.picture]!
                    print("\(n.id) \(look) \(where_): loop \(String(format: "%.2f", g.total)) s, \(g.frames.count) frames; seen:",
                          s.map { "\(String(format: "%.2f", $0.t)):\($0.frame)\($0.d > 6 ? "?" : "")" }.joined(separator: " "))
                    // the frame each capture should show, if playback runs without a restart from the first capture on
                    var starts: [Double] = [0]; for d in g.delays { starts.append(starts.last! + d) }
                    var restarts = 0
                    for i in 1..<max(1, s.count) where s[i].frame < s[i - 1].frame && s[i - 1].frame < g.frames.count - 3 { restarts += 1 }
                    print("   frames seen: \(Set(s.map(\.frame)).count) distinct; jumps back before the loop end: \(restarts); max diff \(String(format: "%.1f", s.map(\.d).max() ?? 0))")
                    let base = "\(out)/\(n.id)-\(look)-\(where_)"
                    sheet(s, title: "\(n.id) · \(look) · \(where_) · a capture every 0.25 s", cols: big ? 4 : 6, cell: big ? 360 : 260, to: base + ".png")
                }
            }
        }
        tick.invalidate()
        w.close()
    }
}
