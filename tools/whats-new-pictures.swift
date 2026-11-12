// Draws the pictures of the What's new notes as short GIFs, in the brand's colors and the app's type, from made-up
// sessions: each frame with AppKit, then ffmpeg (brew install ffmpeg) joins them. A new note with a picture that
// moves can add a function here the same way; a still picture can be any PNG or SVG.
//   whats-new/hold-before-limit.gif   a session set to hold stops at 80% and goes on when the limit resets
//   whats-new/session-inbox.gif       a session that waits is archived, then comes back with a message
// Each also as <slug>-dark.gif, in the dark tokens, which the app shows in dark mode.
// Run from the repo root:
//   swiftc -o /tmp/pictures tools/whats-new-pictures.swift && /tmp/pictures
import AppKit

let W: CGFloat = 440, scale: CGFloat = 2

/// The brand's tokens, light or dark: each picture is drawn twice, <slug>.gif and <slug>-dark.gif, and the app
/// shows the one for the system's look.
enum C {
    static func hex(_ v: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat(v >> 16 & 255) / 255, green: CGFloat(v >> 8 & 255) / 255, blue: CGFloat(v & 255) / 255, alpha: 1)
    }
    static var dark = false
    static func t(_ l: UInt32, _ d: UInt32) -> NSColor { hex(dark ? d : l) }
    static var paper: NSColor { t(0xf8f5f2, 0x121417) }
    static var card: NSColor { t(0xffffff, 0x1a1d21) }
    static var line: NSColor { t(0xe6e1da, 0x2b2f34) }
    static var ink: NSColor { t(0x000000, 0xe6e8ea) }
    static var steel: NSColor { t(0x5b6570, 0x9aa3ad) }
    static var gray: NSColor { t(0xa3abb2, 0x5b6570) }
    static var green: NSColor { t(0x00892f, 0x00892f) }
    static var goodText: NSColor { t(0x007a2a, 0x3cc46a) }
    static var goodSoft: NSColor { t(0xe6f4ea, 0x17271e) }
    static var goodBorder: NSColor { t(0xb9dec4, 0x2e4a3a) }
    static var infoText: NSColor { t(0x035f93, 0x5aa9e0) }
    static var infoSoft: NSColor { t(0xe8f1f8, 0x16222d) }
    static var infoBorder: NSColor { t(0xb6d3e8, 0x24435c) }
    static var infoMark: NSColor { t(0x0473b1, 0x5aa9e0) }
}

func font(_ size: CGFloat, _ semibold: Bool = false) -> NSFont {
    let f = NSFont(name: "Helvetica Neue", size: size) ?? .systemFont(ofSize: size)
    return semibold ? NSFontManager.shared.convert(f, toHaveTrait: .boldFontMask).withSize(size) : f
}

/// Text at a point (top left), or wrapped in a box.
@discardableResult
func text(_ s: String, _ x: CGFloat, _ y: CGFloat, size: CGFloat = 14, bold: Bool = false, color: NSColor? = nil,
          width: CGFloat? = nil, alpha: CGFloat = 1) -> CGFloat {
    let para = NSMutableParagraphStyle()
    para.lineSpacing = 2
    let a = NSAttributedString(string: s, attributes: [.font: font(size, bold), .foregroundColor: (color ?? C.ink).withAlphaComponent(alpha),
                                                        .paragraphStyle: para])
    let w = width ?? ceil(a.size().width) + 2
    let r = a.boundingRect(with: NSSize(width: w, height: 400), options: [.usesLineFragmentOrigin])
    a.draw(with: NSRect(x: x, y: y, width: w, height: ceil(r.height) + 2), options: [.usesLineFragmentOrigin])
    return ceil(r.height)
}

func width(_ s: String, size: CGFloat, bold: Bool = false) -> CGFloat {
    NSAttributedString(string: s, attributes: [.font: font(size, bold)]).size().width
}

func card(_ r: NSRect, fill: NSColor? = nil, border: NSColor? = nil, radius: CGFloat = 6, lineWidth: CGFloat = 1) {
    (fill ?? C.card).setFill()
    let p = NSBezierPath(roundedRect: r, xRadius: radius, yRadius: radius)
    p.fill()
    (border ?? C.line).setStroke()
    let b = NSBezierPath(roundedRect: r.insetBy(dx: lineWidth / 2, dy: lineWidth / 2), xRadius: radius, yRadius: radius)
    b.lineWidth = lineWidth
    b.stroke()
}

/// A status chip: soft wash, 1 px border, a dot and the word, right edge at `right`.
func chip(_ word: String, right: CGFloat, midY: CGFloat, good: Bool, alpha: CGFloat = 1) {
    let w = width(word, size: 13, bold: true) + 30, h: CGFloat = 24
    let r = NSRect(x: right - w, y: midY - h / 2, width: w, height: h)
    card(r, fill: (good ? C.goodSoft : C.infoSoft).withAlphaComponent(alpha),
         border: (good ? C.goodBorder : C.infoBorder).withAlphaComponent(alpha), radius: h / 2)
    (good ? C.goodText : C.infoMark).withAlphaComponent(alpha).setFill()
    NSBezierPath(ovalIn: NSRect(x: r.minX + 10, y: midY - 3.5, width: 7, height: 7)).fill()
    text(word, r.minX + 21, midY - 8.5, size: 13, bold: true, color: good ? C.goodText : C.infoText, alpha: alpha)
}

/// One frame: a flipped context at 2x, the paper ground, then `draw`.
func frame(_ h: CGFloat, _ draw: () -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(W * scale), pixelsHigh: Int(h * scale), bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: W, height: h)
    let base = NSGraphicsContext(bitmapImageRep: rep)!
    base.cgContext.translateBy(x: 0, y: h)   // the rep is already 2x: its size is in points
    base.cgContext.scaleBy(x: 1, y: -1)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(cgContext: base.cgContext, flipped: true)
    NSAppearance(named: .aqua)!.performAsCurrentDrawingAppearance {
        C.paper.setFill()
        NSRect(x: 0, y: 0, width: W, height: h).fill()
        draw()
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

/// Writes the frames (10 a second) and joins them into a looping GIF with ffmpeg.
func gif(_ frames: [NSBitmapImageRep], to path: String) {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("whats-new-frames-\(getpid())")
    try? FileManager.default.removeItem(at: dir)
    try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: dir) }
    for (i, f) in frames.enumerated() {
        try! f.representation(using: .png, properties: [:])!.write(to: dir.appendingPathComponent(String(format: "f%04d.png", i)))
    }
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    p.arguments = ["ffmpeg", "-v", "error", "-y", "-framerate", "10", "-i", dir.appendingPathComponent("f%04d.png").path,
                   "-vf", "split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];[b][p]paletteuse=dither=none",
                   "-loop", "0", path]
    try! p.run()
    p.waitUntilExit()
    guard p.terminationStatus == 0 else { fatalError("ffmpeg failed; is it installed? brew install ffmpeg") }
    let size = (try? FileManager.default.attributesOfItem(atPath: path)[.size] as? Int) ?? 0
    print("wrote \(path) (\(frames.count) frames, \(size / 1024) KB)")
}

func ease(_ t: CGFloat) -> CGFloat { t < 0.5 ? 2 * t * t : 1 - pow(-2 * t + 2, 2) / 2 }

// MARK: hold before the limit

func holdPicture() -> [NSBitmapImageRep] {
    let h: CGFloat = 232
    struct S { var usage: CGFloat; var held: Bool; var caption: String }
    func draw(_ s: S) -> NSBitmapImageRep {
        frame(h) {
            text("5-hour usage", 20, 16, size: 13, color: C.steel)
            let pct = "\(Int(s.usage.rounded()))%"
            text(pct, W - 20 - width(pct, size: 13, bold: true), 16, size: 13, bold: true)
            let bar = NSRect(x: 20, y: 38, width: W - 40, height: 14)
            card(bar, radius: 7)
            if s.usage > 0 {
                C.steel.setFill()
                NSBezierPath(roundedRect: NSRect(x: bar.minX, y: bar.minY, width: max(14, bar.width * s.usage / 100), height: bar.height),
                             xRadius: 7, yRadius: 7).fill()
            }
            let mx = bar.minX + bar.width * 0.8
            C.ink.setFill()
            NSRect(x: mx - 1, y: bar.minY - 5, width: 2, height: bar.height + 10).fill()
            text("Hold at 80%", mx - width("Hold at 80%", size: 12) / 2, 58, size: 12, color: C.ink)

            let rows: [(String, String?, Bool)] = [("Order page fix", nil, false), ("Site map plan", "Hold 80%", s.held)]
            for (i, r) in rows.enumerated() {
                let rr = NSRect(x: 20, y: 84 + CGFloat(i) * 56, width: W - 40, height: 46)
                card(rr)
                text(r.0, rr.minX + 14, rr.midY - 9, size: 15)
                if let tag = r.1 { text(tag, rr.minX + 22 + width(r.0, size: 15), rr.midY - 8, size: 13, color: C.steel) }
                chip(r.2 ? "On hold" : "Active", right: rr.maxX - 12, midY: rr.midY, good: !r.2)
            }
            text(s.caption, 20, 200, size: 15, bold: true, width: W - 40)
        }
    }
    var out: [NSBitmapImageRep] = []
    func hold(_ s: S, _ n: Int) { let f = draw(s); out += Array(repeating: f, count: n) }
    func move(_ from: CGFloat, _ to: CGFloat, held: Bool, _ caption: String, _ n: Int) {
        for i in 1...n { out.append(draw(S(usage: from + (to - from) * ease(CGFloat(i) / CGFloat(n)), held: held, caption: caption))) }
    }
    hold(S(usage: 81, held: true, caption: "The limit gets to 80%. This session stops and waits."), 28)
    hold(S(usage: 81, held: true, caption: "Your other sessions use what is left."), 24)
    move(81, 6, held: true, "The limit resets.", 8)
    hold(S(usage: 6, held: true, caption: "The limit resets."), 8)
    hold(S(usage: 6, held: false, caption: "The session starts again by itself."), 26)
    move(6, 81, held: false, "The limit gets near 80% again.", 14)
    return out
}

// MARK: the session list as an inbox

func inboxPicture() -> [NSBitmapImageRep] {
    let h: CGFloat = 252
    enum Right { case bubble, kit, reply, ask }
    struct S { var rows: [(String, CGFloat)]; var selected: String?; var back: Bool; var right: Right; var rightAlpha: CGFloat; var caption: String }
    let list = NSRect(x: 20, y: 16, width: 196, height: 176)
    let side = NSRect(x: 230, y: 16, width: W - 250, height: 176)
    func draw(_ s: S) -> NSBitmapImageRep {
        frame(h) {
            card(list)
            text("Sessions", list.minX + 14, list.minY + 12, size: 13, bold: true, color: C.steel)
            var y = list.minY + 38
            for (title, a) in s.rows {
                let r = NSRect(x: list.minX + 8, y: y, width: list.width - 16, height: 36 * a)
                if a > 0.05 {
                    if title == s.selected {
                        card(r, fill: C.card, border: C.ink.withAlphaComponent(a), radius: 6, lineWidth: 2)
                    }
                    text(title, r.minX + 8, r.minY + 9 * a, size: 14, alpha: a)
                    if title == "Supplier quote" && s.back { chip("Back", right: r.maxX - 6, midY: r.midY, good: false, alpha: a) }
                }
                y += 38 * a
            }
            let a = s.rightAlpha
            switch s.right {
            case .bubble:
                card(side, fill: C.card.withAlphaComponent(a), border: C.line.withAlphaComponent(a))
                text("Supplier quote", side.minX + 14, side.minY + 12, size: 13, bold: true, color: C.steel, alpha: a)
                text("I watch for the supplier's reply. If none comes in 2 days, I ask you what to do. You can archive this session.",
                     side.minX + 14, side.minY + 36, size: 14, width: side.width - 28, alpha: a)
            case .kit:
                card(side, fill: C.card.withAlphaComponent(a), border: C.line.withAlphaComponent(a))
                text("Sttark Claude Kit", side.minX + 14, side.minY + 12, size: 13, bold: true, color: C.steel, alpha: a)
                text("1 session waits on someone else", side.minX + 14, side.minY + 36, size: 14, width: side.width - 28, alpha: a)
                text("Supplier quote · Email reply", side.minX + 14, side.minY + 80, size: 13, color: C.steel, width: side.width - 28, alpha: a)
            case .reply, .ask:
                card(side, fill: C.card.withAlphaComponent(a), border: C.line.withAlphaComponent(a))
                text("Message · Reach me by", side.minX + 14, side.minY + 12, size: 13, bold: true, color: C.steel, alpha: a)
                text("Supplier quote", side.minX + 14, side.minY + 36, size: 14, bold: true, alpha: a)
                text(s.right == .reply ? "The supplier replied with the price. I update the order now. Nothing needed from you."
                                       : "The supplier did not reply. Should I send the follow-up now?",
                     side.minX + 14, side.minY + 58, size: 14, width: side.width - 28, alpha: a)
            }
            text(s.caption, 20, 208, size: 15, bold: true, width: W - 40)
        }
    }
    let all = ["Label press PR", "Supplier quote", "Site map plan"]
    func rows(_ a: CGFloat) -> [(String, CGFloat)] { all.map { ($0, $0 == "Supplier quote" ? a : 1) } }
    var out: [NSBitmapImageRep] = []
    func hold(_ s: S, _ n: Int) { let f = draw(s); out += Array(repeating: f, count: n) }
    let c1 = "The session waits on a reply. It tells you so in one line."
    let c2 = "You archive it. The Kit watches for the reply."
    let c3 = "The reply comes. The session comes back and sends you a message."
    let c4 = "No reply in time? The session asks you what to do."
    hold(S(rows: rows(1), selected: "Supplier quote", back: false, right: .bubble, rightAlpha: 1, caption: c1), 30)
    for i in 1...6 {   // archived: the row closes up, and the Kit takes the wait
        let t = ease(CGFloat(i) / 6)
        out.append(draw(S(rows: rows(1 - t), selected: "Supplier quote", back: false, right: .kit, rightAlpha: t, caption: c2)))
    }
    hold(S(rows: rows(0), selected: nil, back: false, right: .kit, rightAlpha: 1, caption: c2), 26)
    for i in 1...6 {
        let t = ease(CGFloat(i) / 6)
        out.append(draw(S(rows: rows(t), selected: nil, back: true, right: .reply, rightAlpha: t, caption: c3)))
    }
    hold(S(rows: rows(1), selected: nil, back: true, right: .reply, rightAlpha: 1, caption: c3), 30)
    hold(S(rows: rows(1), selected: nil, back: true, right: .ask, rightAlpha: 1, caption: c4), 30)
    return out
}

for dark in [false, true] {
    C.dark = dark
    let end = dark ? "-dark.gif" : ".gif"
    gif(holdPicture(), to: "whats-new/hold-before-limit" + end)
    gif(inboxPicture(), to: "whats-new/session-inbox" + end)
}
