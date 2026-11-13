import AppKit
import SwiftUI

/// What's new: a short note for each change people notice, one per person, after the update that brings it.
/// The notes are whats-new/*.md in the repo; build.sh turns them into whats-new/index.json in the app, newest
/// first, with their pictures (tools/whats-new.py). The notes a person has seen are `whats_new_seen` in the
/// shared state file.
///
/// Nothing opens by itself. While a note is unseen, the menu bar icon has a dot and the menu's What's new item a
/// "3 new" badge. Clicking it opens the window with a short sheet: each new note's icon, title and one line, with
/// Continue and All changes. Opening the sheet marks them seen. All changes is the window's What's new page:
/// every note, newest first, with its picture.
enum WhatsNew {
    struct Note: Decodable {
        let id: String
        let build: Int
        let title: String
        /// New or Better.
        let kind: String
        /// One sentence: what changes for the person. The sheet shows it too.
        let lead: String
        /// Two or three short points; one says how to start.
        let points: [String]
        let picture: String
        let alt: String
        /// The picture for dark mode, when the note has one (<slug>-dark.gif beside it).
        var picture_dark: String? = nil
        var icon: String? = nil
        /// The day the build that first shipped it was made, yyyy-mm-dd.
        var date: String? = nil

        var version: String { "1.\(build)" }
        /// "Nov 12"
        var day: String {
            let i = DateFormatter(); i.dateFormat = "yyyy-MM-dd"; i.locale = Locale(identifier: "en_US_POSIX")
            guard let date, let d = i.date(from: date) else { return "" }
            let o = DateFormatter(); o.dateFormat = "MMM d"
            return o.string(from: d)
        }
    }

    /// The notes in groups, one per build, newest first.
    static func releases(_ notes: [Note]) -> [(build: Int, notes: [Note])] {
        var out: [(build: Int, notes: [Note])] = []
        for n in notes {
            if out.last?.build == n.build { out[out.count - 1].notes.append(n) } else { out.append((n.build, [n])) }
        }
        return out
    }

    /// STTARK_WHATS_NEW_DIR points the code at test notes; the drawing tool (tools/screenshot.swift) uses it.
    static var dir: URL {
        let env = ProcessInfo.processInfo.environment["STTARK_WHATS_NEW_DIR"] ?? ""
        return !env.isEmpty ? URL(fileURLWithPath: env)
            : (Bundle.main.resourceURL ?? URL(fileURLWithPath: "/")).appendingPathComponent("whats-new")
    }

    /// Every note, newest first.
    static var all: [Note] {
        (try? JSONDecoder().decode([Note].self, from: Data(contentsOf: dir.appendingPathComponent("index.json")))) ?? []
    }

    static var seen: Set<String> { Set(State.read()["whats_new_seen"] as? [String] ?? []) }
    static var unseen: [Note] { let s = seen; return all.filter { !s.contains($0.id) } }
    static var hasUnseen: Bool { !unseen.isEmpty }

    /// What the sheet shows: the notes not seen yet, or, when all are seen, the newest update's notes (at most 4).
    static var forSheet: [Note] {
        let u = unseen
        if !u.isEmpty { return u }
        let notes = all
        guard let newest = notes.first?.build else { return [] }
        return Array(notes.filter { $0.build == newest }.prefix(4))
    }

    /// Set in main.swift: no state file before this launch means a new install, which hasn't missed anything.
    static var newInstall = false

    private static var changed: () -> Void = {}

    static func start(changed: @escaping () -> Void) {
        self.changed = changed
        let notes = all
        if State.read()["whats_new_seen"] == nil {
            // A new install starts with every note seen: they tell what changed, and nothing changed for them.
            let ids = newInstall ? notes.map(\.id) : []
            State.change { $0["whats_new_seen"] = ids }
            if newInstall && !ids.isEmpty { note("what's new: new install, \(ids.count) notes marked seen") }
        }
        let u = unseen
        if !u.isEmpty {
            note("what's new: \(u.count) not seen yet (\(u.map(\.id).joined(separator: ", "))); a dot on the icon and a badge in the menu")
        }
    }

    /// Marks the notes seen, and returns the ones that were new: the dot and the badge go away.
    @discardableResult
    static func markSeen(_ notes: [Note], _ how: String) -> [String] {
        let ids = notes.map(\.id)
        let had = seen
        let new = ids.filter { !had.contains($0) }
        guard !new.isEmpty else { return [] }
        State.change { s in
            let old = s["whats_new_seen"] as? [String] ?? []
            s["whats_new_seen"] = old + ids.filter { !old.contains($0) }
        }
        note("what's new: seen (\(how)): " + new.joined(separator: ", "))
        changed()
        return new
    }
}

// MARK: the window

/// Brand tokens from the guide's Look chapter, light and dark.
enum Tokens {
    static func hex(_ v: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat(v >> 16 & 255) / 255, green: CGFloat(v >> 8 & 255) / 255, blue: CGFloat(v & 255) / 255, alpha: 1)
    }
    static func token(_ light: UInt32, _ dark: UInt32) -> NSColor {
        NSColor(name: nil) { a in a.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? hex(dark) : hex(light) }
    }
    static let paper = token(0xf8f5f2, 0x121417)
    static let card = token(0xffffff, 0x1a1d21)
    static let highlight = token(0xf0e1cc, 0x2a2620)
    static let ink = token(0x000000, 0xe6e8ea)
    static let steel = token(0x5b6570, 0x9aa3ad)
    static let line = token(0xe6e1da, 0x2b2f34)
    static let green = token(0x00892f, 0x00892f)
    static let greenHover = token(0x007a2a, 0x00a82d)
    static let infoMark = token(0x0473b1, 0x5aa9e0)
    static let infoText = token(0x035f93, 0x5aa9e0)
    static let infoSoft = token(0xe8f1f8, 0x16222d)
    static let infoBorder = token(0xb6d3e8, 0x24435c)
    static let gray = token(0xa3abb2, 0x5b6570)
    static let warnText = token(0x7a5c00, 0xe8c547)
    static let warnMark = token(0xe5b200, 0xe5b200)
    static let greenText = token(0x007a2a, 0x00a82d)
    /// The window's own grounds: the sidebar, the side panel, and hairlines between parts.
    static let side = token(0xebe8e4, 0x17191c)
    static let panel = token(0xfbfaf9, 0x15181b)
    static let hair = tokenA(0x000000, 0.10, 0xffffff, 0.10)
    /// The "you are here" wash: the current page and the selected session.
    static let wash = tokenA(0x00892f, 0.13, 0x00a82d, 0.20)
    static let track = tokenA(0x000000, 0.10, 0xffffff, 0.14)

    static func tokenA(_ light: UInt32, _ la: CGFloat, _ dark: UInt32, _ da: CGFloat) -> NSColor {
        NSColor(name: nil) { a in a.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? hex(dark).withAlphaComponent(da) : hex(light).withAlphaComponent(la) }
    }

    /// Helvetica Neue, the guide's fallback for Founders Grotesk, as the menu uses it.
    static func font(_ size: CGFloat, _ semibold: Bool = false) -> NSFont {
        let f = NSFont(name: "Helvetica Neue", size: size) ?? .systemFont(ofSize: size)
        return semibold ? NSFontManager.shared.convert(f, toHaveTrait: .boldFontMask).withSize(size) : f
    }
}

/// The sheet's notes, and the button that closes it.
struct NewsSheet: View {
    let notes: [WhatsNew.Note]
    let onContinue: () -> Void
    let onAll: () -> Void
    var body: some View {
        VStack(spacing: 0) {
            Text("What's new in Sttark Claude Kit").font(K.font(19, true)).padding(.top, 28).padding(.bottom, 20)
            VStack(alignment: .leading, spacing: 18) {
                ForEach(notes, id: \.id) { n in
                    HStack(alignment: .top, spacing: 14) {
                        Image(systemName: n.icon ?? "sparkles")
                            .font(.system(size: 22 * K.zoom, weight: .regular))
                            .foregroundColor(K.greenText)
                            .frame(width: 30, alignment: .center)
                            .padding(.top, 1)
                            .accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(n.title).font(K.font(14, true)).fixedSize(horizontal: false, vertical: true)
                            Text(NoteText.md(n.lead)).font(K.font(13)).foregroundColor(K.steel)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.horizontal, 32)
            Rectangle().fill(K.hair).frame(height: 1).padding(.top, 24)
            HStack {
                Button("All changes", action: onAll).controlSize(K.control)
                    .help("Every note, newest first, with its picture.")
                Spacer()
                Button("Continue", action: onContinue).buttonStyle(GreenButtonStyle()).keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 20)
            .frame(height: 60)
        }
        .textSelection(.enabled)
        .frame(width: K.z(460))
        .controlSize(K.control)
        .foregroundColor(K.ink)
        .background(K.card)
    }
}

/// A note's words: the tag and title, the one sentence, and the points.
struct NoteText: View {
    let note: WhatsNew.Note
    var titleSize: CGFloat = 17
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(note.title).font(K.font(titleSize, true)).fixedSize(horizontal: false, vertical: true)
                KindTag(kind: note.kind)
            }
            Text(Self.md(note.lead)).font(K.font(14)).lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true).padding(.top, 6)
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(note.points.enumerated()), id: \.offset) { _, t in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Circle().fill(K.steel).frame(width: 4, height: 4).alignmentGuide(.firstTextBaseline) { $0[.bottom] + 4 }
                        Text(Self.md(t)).font(K.font(13)).foregroundColor(K.ink.opacity(0.86)).lineSpacing(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .padding(.top, 12)
        }
    }

    /// The note's **bold** and `code`; what a person types shows in bold, in the same font as the words.
    static func md(_ s: String) -> AttributedString {
        guard var a = try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))
        else { return AttributedString(s) }
        for r in a.runs where r.inlinePresentationIntent?.contains(.code) == true {
            a[r.range].inlinePresentationIntent = .stronglyEmphasized
        }
        return a
    }
}

/// New: information blue; Better: a quiet outline.
struct KindTag: View {
    let kind: String
    var body: some View {
        let new = kind != "Better"
        Text(kind).font(K.font(11, true)).tracking(0.3)
            .foregroundColor(new ? K.infoText : K.steel)
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(new ? K.infoSoft : .clear, in: Capsule())
            .overlay(Capsule().strokeBorder(new ? K.infoBorder : K.hair))
            .fixedSize()
    }
}

/// A note's picture at its own size, never smaller; a click shows it bigger.
struct NoteImage: View {
    let note: WhatsNew.Note
    let open: (WhatsNew.Note) -> Void
    var body: some View {
        if let p = NotePicture.size(note) {
            NotePicture(note: note)
                .frame(width: K.z(p.width), height: K.z(p.width / p.ratio))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(K.hair))
                .contentShape(Rectangle())
                .onTapGesture { open(note) }
                .help("Click to see it bigger")
                .accessibilityAddTraits(.isButton)
        }
    }
}

/// The picture bigger, over the page; a click or Escape closes it.
struct BigPicture: View {
    let note: WhatsNew.Note
    let close: () -> Void
    var body: some View {
        ZStack {
            Color.black.opacity(0.55).ignoresSafeArea().onTapGesture(perform: close)
            if let p = NotePicture.size(note) {
                GeometryReader { g in
                    let w = min(p.width * 1.6, g.size.width - 64, (g.size.height - 96) * p.ratio)
                    VStack(spacing: 10) {
                        NotePicture(note: note)
                            .frame(width: w, height: w / p.ratio)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            .shadow(color: .black.opacity(0.3), radius: 24, y: 8)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .onTapGesture(perform: close)
            }
        }
        .onExitCommand(perform: close)
    }
}

/// A note's picture, which moves when it is a GIF, and changes with the system's light or dark look.
///
/// The view plays the GIF itself, from one clock: each frame shows for its own time, and the light and the dark
/// picture share the clock, so a change of look goes on at the same point. An image view that animates does not do
/// this: it starts again at the first frame each time it gets its image, and the window reads its model again every
/// 3 seconds, which set the image again and kept the picture on its first frame. This view reads its files once.
struct NotePicture: NSViewRepresentable {
    let note: WhatsNew.Note

    /// The light picture and the dark one, when the note has one.
    var files: [URL] {
        [note.picture].map { WhatsNew.dir.appendingPathComponent($0) }
            + (note.picture_dark.map { [WhatsNew.dir.appendingPathComponent($0)] } ?? [])
    }

    private static var sizes: [String: (ratio: CGFloat, width: CGFloat)] = [:]

    /// `width`: the picture's own width in points, the most it is drawn at, so its words stay the size they were drawn.
    /// Read once for each file, not at each update of the page.
    static func size(_ n: WhatsNew.Note) -> (ratio: CGFloat, width: CGFloat)? {
        let path = WhatsNew.dir.appendingPathComponent(n.picture).path
        if let s = sizes[path] { return s }
        guard let img = NSImage(contentsOfFile: path) else { return nil }
        let px = img.representations.first.map { NSSize(width: $0.pixelsWide, height: $0.pixelsHigh) } ?? img.size
        let s = (ratio: px.height > 0 ? px.width / px.height : 2, width: px.width / 2)
        sizes[path] = s
        return s
    }

    /// A picture's frames and the time each one ends, from the start of the loop. A still picture is one frame.
    struct Movie {
        var frames: [CGImage] = []
        var ends: [Double] = []
        var total: Double { ends.last ?? 0 }

        init?(_ url: URL) {
            if let src = CGImageSourceCreateWithURL(url as CFURL, nil), CGImageSourceGetCount(src) > 0 {
                var t = 0.0
                for i in 0..<CGImageSourceGetCount(src) {
                    guard let f = CGImageSourceCreateImageAtIndex(src, i, nil) else { continue }
                    let p = CGImageSourceCopyPropertiesAtIndex(src, i, nil) as? [CFString: Any]
                    let g = p?[kCGImagePropertyGIFDictionary] as? [CFString: Any]
                    let d = (g?[kCGImagePropertyGIFUnclampedDelayTime] as? Double) ?? (g?[kCGImagePropertyGIFDelayTime] as? Double) ?? 0.1
                    t += d < 0.02 ? 0.1 : d   // as browsers do, a frame with no time shows for 0.1 s
                    frames.append(f)
                    ends.append(t)
                }
            } else if let img = NSImage(contentsOf: url) {   // an SVG
                var r = NSRect(origin: .zero, size: NSSize(width: img.size.width * 2, height: img.size.height * 2))
                if let f = img.cgImage(forProposedRect: &r, context: nil, hints: nil) { frames = [f]; ends = [1] }
            }
            if frames.isEmpty { return nil }
        }

        /// The frame at a time on the clock, and the time it ends.
        func frame(at t: Double) -> (index: Int, ends: Double) {
            guard frames.count > 1, total > 0 else { return (0, .infinity) }
            let loop = (t / total).rounded(.down) * total
            let i = ends.firstIndex { loop + $0 > t } ?? frames.count - 1
            return (i, loop + ends[i])
        }
    }

    final class View: NSView {
        private var files: [URL] = []
        private var light: Movie?, dark: Movie?
        /// The clock's zero: when the picture first showed.
        private var start = CACurrentMediaTime()
        private var timer: Timer?
        private(set) var shown = 0

        /// Reads the files only when they are not the ones it shows already: an update of the page keeps it playing.
        func show(_ files: [URL]) {
            guard files != self.files else { return }
            self.files = files
            light = Movie(files[0])
            dark = files.count > 1 ? Movie(files[1]) : nil
            start = CACurrentMediaTime()
            tick()
        }

        /// Gone from the page: no more timer.
        func stop() { timer?.invalidate(); timer = nil }

        var movie: Movie? {
            effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? (dark ?? light) : light
        }

        /// Shows the frame for the clock now, and sets a timer for the next one. While the window is not on the
        /// screen, it only checks again now and then.
        private func tick() {
            timer?.invalidate()
            timer = nil
            guard let m = movie, window != nil else { return }
            let now = CACurrentMediaTime()
            let f = m.frame(at: now - start)
            if f.index != shown { shown = f.index; needsDisplay = true }
            guard m.frames.count > 1 else { return }
            let visible = window?.isVisible == true
            let wait = visible ? max(0.01, f.ends - (now - start)) : 0.5
            let t = Timer(timeInterval: wait, repeats: false) { [weak self] _ in self?.tick() }
            RunLoop.main.add(t, forMode: .common)   // it plays on while the page scrolls
            timer = t
        }

        override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); tick() }

        override func viewDidChangeEffectiveAppearance() {
            super.viewDidChangeEffectiveAppearance()
            needsDisplay = true
            tick()
        }

        override func draw(_ dirtyRect: NSRect) {
            guard let m = movie, let ctx = NSGraphicsContext.current?.cgContext else { return }
            let f = m.frames[min(shown, m.frames.count - 1)]
            let w = CGFloat(f.width), h = CGFloat(f.height)
            let s = min(bounds.width / w, bounds.height / h)
            let r = CGRect(x: bounds.midX - w * s / 2, y: bounds.midY - h * s / 2, width: w * s, height: h * s)
            ctx.interpolationQuality = .high
            ctx.draw(f, in: r)
        }

        /// A click goes to the SwiftUI view around it, which opens the picture bigger.
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override var intrinsicContentSize: NSSize { NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric) }
    }

    func makeNSView(context: Context) -> View {
        let v = View()
        v.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        v.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        v.setAccessibilityElement(true)
        v.setAccessibilityRole(.image)
        return v
    }

    func updateNSView(_ v: View, context: Context) {
        v.setAccessibilityLabel(note.alt)
        v.show(files)
    }

    static func dismantleNSView(_ v: View, coordinator: ()) { v.stop() }
}

extension NSColor {
    /// A token's light or dark value, for drawing outside a view.
    func resolved(_ dark: Bool) -> NSColor {
        var out = self
        NSAppearance(named: dark ? .darkAqua : .aqua)!.performAsCurrentDrawingAppearance { out = self.usingColorSpace(.sRGB) ?? self }
        return out
    }
}
