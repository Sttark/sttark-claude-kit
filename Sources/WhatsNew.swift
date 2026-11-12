import AppKit

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
        p.place(near: anchor())
        p.orderFrontRegardless()   // in front, without making the app active or taking the keyboard
        panel = p
        note("what's new: shown (\(why)): \(notes.map(\.id).joined(separator: ", "))")
    }

    /// Got it: every note in the window is seen.
    static func done(_ notes: [Note]) {
        let ids = notes.map(\.id)
        let had = seen
        State.change { s in
            let old = s["whats_new_seen"] as? [String] ?? []
            s["whats_new_seen"] = old + ids.filter { !old.contains($0) }
        }
        let new = ids.filter { !had.contains($0) }
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

    /// Helvetica Neue, the guide's fallback for Founders Grotesk, as the menu uses it.
    static func font(_ size: CGFloat, _ semibold: Bool = false) -> NSFont {
        let f = NSFont(name: "Helvetica Neue", size: size) ?? .systemFont(ofSize: size)
        return semibold ? NSFontManager.shared.convert(f, toHaveTrait: .boldFontMask).withSize(size) : f
    }
}

/// A panel that never makes the app active and never takes the keyboard: typing elsewhere goes on as it was.
/// Its button still takes a click.
final class NotesPanel: NSPanel {
    static let width: CGFloat = 520
    static let pad: CGFloat = 24
    private let onDone: () -> Void

    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    init(_ notes: [WhatsNew.Note], unseen: Bool, onDone: @escaping () -> Void) {
        self.onDone = onDone
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
        contentView = NotesView(notes, button: unseen ? "Got it" : "Close") { [weak self] in self?.onDone() }
    }

    /// Under the menu bar icon, right edges lined up, as tall as the notes need and the screen allows.
    func place(near item: NSStatusItem?) {
        let iconFrame = item?.button?.window?.frame
        let screen = item?.button?.window?.screen ?? NSScreen.main ?? NSScreen.screens.first
        let vis = screen?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 875)
        let view = contentView as! NotesView
        let h = min(view.fitHeight, vis.height - 16)
        let right = min(iconFrame.map { $0.maxX + 8 } ?? vis.maxX - 8, vis.maxX - 8)
        setFrame(NSRect(x: max(vis.minX + 8, right - Self.width), y: vis.maxY - 8 - h, width: Self.width, height: h), display: true)
    }
}

/// The window's content: the heading, each note on a card (title, picture, words, what you do), and one button.
final class NotesView: NSView {
    let scroll = NSScrollView()
    let stack = NSStackView()
    let heading: NSTextField
    let button: GreenButton
    let headH: CGFloat = 64, footH: CGFloat = 72

    init(_ notes: [WhatsNew.Note], button title: String, onDone: @escaping () -> Void) {
        heading = NotesView.label("What's new in Sttark Claude Kit", size: 19, semibold: true)
        button = GreenButton(title, onDone)
        super.init(frame: NSRect(x: 0, y: 0, width: NotesPanel.width, height: 400))
        let inner = NotesPanel.width - 2 * NotesPanel.pad
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 16
        stack.edgeInsets = NSEdgeInsets(top: 0, left: NotesPanel.pad, bottom: 8, right: NotesPanel.pad)
        for n in notes { stack.addArrangedSubview(NoteCard(n, width: inner)) }
        let doc = FlippedView()
        doc.addSubview(stack)
        stack.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: doc.topAnchor), stack.leadingAnchor.constraint(equalTo: doc.leadingAnchor),
            stack.widthAnchor.constraint(equalToConstant: NotesPanel.width),
        ])
        stack.layoutSubtreeIfNeeded()
        doc.frame = NSRect(x: 0, y: 0, width: NotesPanel.width, height: stack.fittingSize.height)
        scroll.documentView = doc
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.scrollerStyle = .overlay
        addSubview(heading)
        addSubview(scroll)
        addSubview(button)
    }

    required init?(coder: NSCoder) { fatalError() }

    var fitHeight: CGFloat { headH + (scroll.documentView?.frame.height ?? 0) + footH }

    override var isFlipped: Bool { true }

    override func layout() {
        super.layout()
        let w = bounds.width, pad = NotesPanel.pad
        heading.frame = NSRect(x: pad, y: 28, width: w - 2 * pad, height: heading.fittingSize.height)
        scroll.frame = NSRect(x: 0, y: headH, width: w, height: bounds.height - headH - footH)
        let b = button.fittingSize
        button.frame = NSRect(x: w - pad - b.width, y: bounds.height - 16 - b.height - 8, width: b.width, height: b.height)
    }

    override func draw(_ dirtyRect: NSRect) {
        Tokens.paper.setFill()
        bounds.fill()
        Tokens.line.setFill()   // a hairline over the button when the notes scroll under it
        if fitHeight > bounds.height + 1 { NSRect(x: 0, y: bounds.height - footH, width: bounds.width, height: 1).fill() }
    }

    static func label(_ s: String, size: CGFloat = 16, semibold: Bool = false, color: NSColor = Tokens.ink) -> NSTextField {
        let t = NSTextField(labelWithString: s)
        t.font = Tokens.font(size, semibold)
        t.textColor = color
        return t
    }
}

final class FlippedView: NSView { override var isFlipped: Bool { true } }

/// One note on a card: its title, its picture, its words, and what you do differently on a highlight.
final class NoteCard: NSView {
    init(_ n: WhatsNew.Note, width: CGFloat) {
        super.init(frame: .zero)
        let pad: CGFloat = 16, inner = width - 2 * pad
        let col = NSStackView()
        col.orientation = .vertical
        col.alignment = .leading
        col.spacing = 12
        col.edgeInsets = NSEdgeInsets(top: pad, left: pad, bottom: pad, right: pad)
        col.addArrangedSubview(Self.paragraph(n.title, inner, size: 17, semibold: true))
        if let img = NSImage(contentsOf: WhatsNew.dir.appendingPathComponent(n.picture)) {
            let px = img.representations.first.map { NSSize(width: $0.pixelsWide, height: $0.pixelsHigh) } ?? img.size
            let h = px.width > 0 ? (inner * px.height / px.width).rounded() : 200
            let v = NSImageView()
            v.image = img
            v.animates = true
            v.imageScaling = .scaleProportionallyUpOrDown
            v.setAccessibilityLabel(n.alt)
            v.toolTip = n.alt
            v.wantsLayer = true
            v.layer?.cornerRadius = 6
            v.layer?.masksToBounds = true
            v.translatesAutoresizingMaskIntoConstraints = false
            v.widthAnchor.constraint(equalToConstant: inner).isActive = true
            v.heightAnchor.constraint(equalToConstant: h).isActive = true
            col.addArrangedSubview(v)
        }
        for p in n.text { col.addArrangedSubview(Self.paragraph(p, inner)) }
        col.addArrangedSubview(Highlight(Self.paragraph("**What you do:** " + n.action, inner - 24), width: inner))
        addSubview(col)
        col.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            col.topAnchor.constraint(equalTo: topAnchor), col.bottomAnchor.constraint(equalTo: bottomAnchor),
            col.leadingAnchor.constraint(equalTo: leadingAnchor), col.trailingAnchor.constraint(equalTo: trailingAnchor),
            widthAnchor.constraint(equalToConstant: width),
        ])
    }

    required init?(coder: NSCoder) { fatalError() }

    override func draw(_ dirtyRect: NSRect) {
        let r = bounds.insetBy(dx: 0.5, dy: 0.5)
        Tokens.card.setFill()
        NSBezierPath(roundedRect: r, xRadius: 6, yRadius: 6).fill()
        Tokens.line.setStroke()
        NSBezierPath(roundedRect: r, xRadius: 6, yRadius: 6).stroke()
    }

    /// Body text, 16 pt, with the note's **bold** and `code` kept.
    static func paragraph(_ s: String, _ width: CGFloat, size: CGFloat = 16, semibold: Bool = false) -> TextBlock {
        let para = NSMutableParagraphStyle()
        para.lineHeightMultiple = 1.15
        let out = NSMutableAttributedString()
        let base: [NSAttributedString.Key: Any] = [.font: Tokens.font(size, semibold), .foregroundColor: Tokens.ink, .paragraphStyle: para]
        var rest = Substring(s)
        let rx = try! NSRegularExpression(pattern: "\\*\\*(.+?)\\*\\*|`([^`]+)`")
        while let m = rx.firstMatch(in: String(rest), range: NSRange(location: 0, length: (String(rest) as NSString).length)) {
            let str = String(rest) as NSString
            out.append(NSAttributedString(string: str.substring(to: m.range.location), attributes: base))
            var a = base
            if m.range(at: 1).location != NSNotFound {
                a[.font] = Tokens.font(16, true)
                out.append(NSAttributedString(string: str.substring(with: m.range(at: 1)), attributes: a))
            } else {
                a[.font] = NSFont.monospacedSystemFont(ofSize: 14, weight: .regular)
                out.append(NSAttributedString(string: str.substring(with: m.range(at: 2)), attributes: a))
            }
            rest = Substring(str.substring(from: m.range.location + m.range.length))
        }
        out.append(NSAttributedString(string: String(rest), attributes: base))
        return TextBlock(out, width: width)
    }
}

/// Wrapped text that measures itself at its width and draws itself, so no line is ever cut off.
final class TextBlock: NSView {
    let text: NSAttributedString

    init(_ text: NSAttributedString, width: CGFloat) {
        self.text = text
        let h = ceil(text.boundingRect(with: NSSize(width: width, height: 10000), options: [.usesLineFragmentOrigin, .usesFontLeading]).height)
        super.init(frame: NSRect(x: 0, y: 0, width: width, height: h))
        translatesAutoresizingMaskIntoConstraints = false
        widthAnchor.constraint(equalToConstant: width).isActive = true
        heightAnchor.constraint(equalToConstant: h).isActive = true
        setAccessibilityElement(true)
        setAccessibilityRole(.staticText)
        setAccessibilityValue(text.string)
    }

    required init?(coder: NSCoder) { fatalError() }

    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        text.draw(with: bounds, options: [.usesLineFragmentOrigin, .usesFontLeading])
    }
}

/// The brand's highlight ground, for the one thing to remember.
final class Highlight: NSView {
    init(_ content: NSView, width: CGFloat) {
        super.init(frame: .zero)
        addSubview(content)
        content.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            content.topAnchor.constraint(equalTo: topAnchor, constant: 12), content.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -12),
            content.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            widthAnchor.constraint(equalToConstant: width),
        ])
    }

    required init?(coder: NSCoder) { fatalError() }

    override func draw(_ dirtyRect: NSRect) {
        Tokens.highlight.setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 6, yRadius: 6).fill()
    }
}

/// The one main action: green fill, white 15 pt semibold, 40 pt tall, 6 pt corners. It takes the first click,
/// since its window is never the key window.
final class GreenButton: NSButton {
    private let onClick: () -> Void
    private var hover = false

    init(_ title: String, _ onClick: @escaping () -> Void) {
        self.onClick = onClick
        super.init(frame: .zero)
        self.title = title
        isBordered = false
        attributedTitle = NSAttributedString(string: title, attributes: [.font: Tokens.font(15, true), .foregroundColor: NSColor.white])
        target = self
        action = #selector(clicked)
        setAccessibilityLabel(title)
    }

    required init?(coder: NSCoder) { fatalError() }

    @objc private func clicked() { onClick() }

    override var fittingSize: NSSize { NSSize(width: ceil(attributedTitle.size().width) + 40, height: 40) }
    override var intrinsicContentSize: NSSize { fittingSize }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways], owner: self))
    }
    override func mouseEntered(with event: NSEvent) { hover = true; needsDisplay = true }
    override func mouseExited(with event: NSEvent) { hover = false; needsDisplay = true }

    override func draw(_ dirtyRect: NSRect) {
        (hover || isHighlighted ? Tokens.greenHover : Tokens.green).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 6, yRadius: 6).fill()
        let t = attributedTitle, s = t.size()
        t.draw(at: NSPoint(x: (bounds.width - s.width) / 2, y: (bounds.height - s.height) / 2 + (isFlipped ? 0 : 1)))
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
