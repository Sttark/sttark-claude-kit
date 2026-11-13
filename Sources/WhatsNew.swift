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
        if let p = NotePicture.load(note) {
            NotePicture(light: p.light, dark: p.dark, alt: note.alt)
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
            if let p = NotePicture.load(note) {
                GeometryReader { g in
                    let w = min(p.width * 1.6, g.size.width - 64, (g.size.height - 96) * p.ratio)
                    VStack(spacing: 10) {
                        NotePicture(light: p.light, dark: p.dark, alt: note.alt)
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
struct NotePicture: NSViewRepresentable {
    let light: NSImage
    let dark: NSImage?
    let alt: String

    /// `width`: the picture's own width in points, the most it is drawn at, so its words stay the size they were drawn.
    static func load(_ n: WhatsNew.Note) -> (light: NSImage, dark: NSImage?, ratio: CGFloat, width: CGFloat)? {
        guard let img = NSImage(contentsOf: WhatsNew.dir.appendingPathComponent(n.picture)) else { return nil }
        let dark = n.picture_dark.flatMap { NSImage(contentsOf: WhatsNew.dir.appendingPathComponent($0)) }
        let px = img.representations.first.map { NSSize(width: $0.pixelsWide, height: $0.pixelsHigh) } ?? img.size
        return (img, dark, px.height > 0 ? px.width / px.height : 2, px.width / 2)
    }

    final class View: NSImageView {
        var light: NSImage?, dark: NSImage?
        override func viewDidChangeEffectiveAppearance() { super.viewDidChangeEffectiveAppearance(); pick() }
        func pick() {
            let isDark = effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            let want = isDark ? (dark ?? light) : light
            if image !== want { image = want }
        }
        override var intrinsicContentSize: NSSize { NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric) }
    }

    func makeNSView(context: Context) -> View {
        let v = View()
        v.imageScaling = .scaleProportionallyUpOrDown
        v.animates = true
        v.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        v.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        v.setAccessibilityLabel(alt)
        v.toolTip = alt
        return v
    }

    func updateNSView(_ v: View, context: Context) {
        v.light = light
        v.dark = dark
        v.pick()
    }
}

extension NSColor {
    /// A token's light or dark value, for drawing outside a view.
    func resolved(_ dark: Bool) -> NSColor {
        var out = self
        NSAppearance(named: dark ? .darkAqua : .aqua)!.performAsCurrentDrawingAppearance { out = self.usingColorSpace(.sRGB) ?? self }
        return out
    }
}
