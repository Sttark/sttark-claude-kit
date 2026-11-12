import AppKit
import SwiftUI

/// What's new: a short note for each change people notice, shown once per person, after the update that brings it.
/// The notes are whats-new/*.md in the repo; build.sh turns them into whats-new/index.json in the app, newest
/// first, with their pictures (tools/whats-new.py). The notes a person has seen are `whats_new_seen` in the
/// shared state file.
///
/// It never takes the screen. The window is a panel that doesn't make the app active and never takes the keyboard,
/// so typing goes on where it was. While a note is unseen, the menu bar icon has a dot, and the window waits for
/// the person to come back to the Mac: the screen unlocks or wakes, or input starts again after 5 minutes idle.
/// Opening the menu shows it too, when the menu closes. "What's new" in the menu shows every note.
enum WhatsNew {
    struct Note: Decodable {
        let id: String
        let build: Int
        let title: String
        let text: [String]
        let action: String
        let picture: String
        let alt: String
        /// The picture for dark mode, when the note has one (<slug>-dark.gif beside it).
        var picture_dark: String? = nil
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

    /// Set in main.swift: no state file before this launch means a new install, which hasn't missed anything.
    static var newInstall = false
    /// Minutes of no input that count as being away.
    static let away: TimeInterval = 5 * 60

    private static var changed: () -> Void = {}
    private static var anchor: () -> NSStatusItem? = { nil }
    private static var panel: NotesPanel?
    private static var lastIdle: TimeInterval = 0
    private static var menuWasOpened = false

    static func start(anchor: @escaping () -> NSStatusItem?, changed: @escaping () -> Void) {
        self.anchor = anchor
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
            note("what's new: \(u.count) not seen yet (\(u.map(\.id).joined(separator: ", "))); a dot on the icon until you come back to the Mac")
        }
        let ws = NSWorkspace.shared.notificationCenter
        ws.addObserver(forName: NSWorkspace.screensDidWakeNotification, object: nil, queue: .main) { _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { if !screenLocked { cameBack("the screen woke") } }
        }
        DistributedNotificationCenter.default().addObserver(forName: .init("com.apple.screenIsUnlocked"), object: nil, queue: .main) { _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { cameBack("the screen unlocked") }
        }
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in watchIdle() }
    }

    /// Input after `away` with none: the person is back.
    static func watchIdle() {
        let idle = CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: CGEventType(rawValue: ~0)!)
        defer { lastIdle = idle }
        guard lastIdle >= away, idle < lastIdle, idle < 10 else { return }
        cameBack("back after \(Int(lastIdle / 60)) min away")
    }

    static var screenLocked: Bool {
        (CGSessionCopyCurrentDictionary() as? [String: Any])?["CGSSessionScreenIsLocked"] as? Bool ?? false
    }

    static func cameBack(_ why: String) {
        guard panel == nil, !screenLocked else { return }
        let u = unseen
        guard !u.isEmpty else { return }
        show(u, why: why)
    }

    /// Marks the notes seen, and returns the ones that were new. The window's What's new page does this too.
    @discardableResult
    static func markSeen(_ notes: [Note]) -> [String] {
        let ids = notes.map(\.id)
        let had = seen
        let new = ids.filter { !had.contains($0) }
        guard !new.isEmpty else { return [] }
        State.change { s in
            let old = s["whats_new_seen"] as? [String] ?? []
            s["whats_new_seen"] = old + ids.filter { !old.contains($0) }
        }
        if panel == nil { note("what's new: seen in the window: " + new.joined(separator: ", ")) }
        changed()
        return new
    }

    static func menuOpened() { menuWasOpened = hasUnseen }

    /// After the menu closes, so the window never covers the menu.
    static func menuClosed() {
        guard menuWasOpened else { return }
        menuWasOpened = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { cameBack("the menu was opened") }
    }

    /// "What's new" in the menu: every note, newest first.
    static func showAll() {
        let notes = all
        guard !notes.isEmpty else { return }
        show(notes, why: "What's new in the menu")
    }

    static func show(_ notes: [Note], why: String) {
        panel?.close()
        let p = NotesPanel(notes, unseen: notes.contains { !seen.contains($0.id) }) { done(notes) }
        p.place(near: anchor(), notes: notes)
        p.orderFrontRegardless()   // in front, without making the app active or taking the keyboard
        panel = p
        note("what's new: shown (\(why)): \(notes.map(\.id).joined(separator: ", "))")
    }

    /// Got it: every note in the window is seen.
    static func done(_ notes: [Note]) {
        let new = markSeen(notes)
        note("what's new: Got it" + (new.isEmpty ? "" : ", seen: " + new.joined(separator: ", ")))
        panel?.close()
        panel = nil
        changed()
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

/// A panel that never makes the app active and never takes the keyboard: typing elsewhere goes on as it was.
/// Its button still takes a click. It draws the same note cards as the window's What's new page.
final class NotesPanel: NSPanel {
    static let width: CGFloat = 460

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    init(_ notes: [WhatsNew.Note], unseen: Bool, onDone: @escaping () -> Void) {
        super.init(contentRect: NSRect(x: 0, y: 0, width: Self.width, height: 400),
                   styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel], backing: .buffered, defer: false)
        title = "What's new"
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        for b in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] { standardWindowButton(b)?.isHidden = true }
        isFloatingPanel = true
        level = .floating
        hidesOnDeactivate = false
        becomesKeyOnlyIfNeeded = true
        isMovableByWindowBackground = true
        isReleasedWhenClosed = false
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        contentView = FirstClickHost(rootView: NotesPopup(notes: notes, button: unseen ? "Got it" : "Close", onDone: onDone))
    }

    /// The height the notes need at the panel's width, without scrolling.
    static func fitHeight(_ notes: [WhatsNew.Note]) -> CGFloat {
        let probe = NSHostingView(rootView: NotesStack(notes: notes).frame(width: width))
        return NotesPopup.head + ceil(probe.fittingSize.height) + NotesPopup.foot
    }

    /// Under the menu bar icon, right edges lined up, as tall as the notes need and at most most of the screen.
    func place(near item: NSStatusItem?, notes: [WhatsNew.Note]) {
        let iconFrame = item?.button?.window?.frame
        let screen = item?.button?.window?.screen ?? NSScreen.main ?? NSScreen.screens.first
        let vis = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 875)
        let h = min(Self.fitHeight(notes), (vis.height * 0.85).rounded())
        let right = min(iconFrame.map { $0.maxX + 8 } ?? vis.maxX - 8, vis.maxX - 8)
        setFrame(NSRect(x: max(vis.minX + 8, right - Self.width), y: vis.maxY - 8 - h, width: Self.width, height: h), display: true)
    }
}

/// Takes the first click, since the panel is never the key window.
final class FirstClickHost<V: View>: NSHostingView<V> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

/// The popup: a heading, the notes (scrolling when they don't fit), and one green button.
struct NotesPopup: View {
    static let head: CGFloat = 52, foot: CGFloat = 57
    let notes: [WhatsNew.Note]
    let button: String
    let onDone: () -> Void
    var body: some View {
        VStack(spacing: 0) {
            Text("What's new in Sttark Claude Kit").font(K.font(15, true))
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16).frame(height: Self.head)
            ScrollView { NotesStack(notes: notes) }
            Rectangle().fill(K.hair).frame(height: 1)
            HStack {
                Spacer()
                Button(button, action: onDone).buttonStyle(GreenButtonStyle())
            }
            .padding(.horizontal, 16)
            .frame(height: Self.foot - 1)
        }
        .foregroundColor(K.ink)
        .background(K.paper)
        .ignoresSafeArea()
    }
}

struct NotesStack: View {
    let notes: [WhatsNew.Note]
    var body: some View {
        VStack(spacing: 12) { ForEach(notes, id: \.id) { NoteCardView(note: $0) } }
            .padding(.horizontal, 16)
            .padding(.bottom, 16)
    }
}

/// One note: its title, its picture (the dark one in dark mode), its words, and what you do differently.
struct NoteCardView: View {
    let note: WhatsNew.Note
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(note.title).font(K.font(15, true)).fixedSize(horizontal: false, vertical: true)
            if let p = NotePicture.load(note) {
                NotePicture(light: p.light, dark: p.dark, alt: note.alt)
                    .aspectRatio(p.ratio, contentMode: .fit)
                    .frame(maxWidth: p.width)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(K.hair))
            }
            ForEach(Array(note.text.enumerated()), id: \.offset) { _, t in
                Text(Self.md(t)).font(K.font(13)).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
            }
            (Text("What you do: ").font(K.font(13, true)) + Text(Self.md(note.action)).font(K.font(13)))
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(K.highlight, in: RoundedRectangle(cornerRadius: 6))
        }
        .padding(14)
        .background(K.card, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(K.hair))
    }

    /// The note's **bold** and `code`.
    static func md(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
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
        return (img, dark, px.height > 0 ? px.width / px.height : 2, max(200, px.width / 2))
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
