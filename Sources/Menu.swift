import AppKit

let levels = ["low", "medium", "high", "xhigh", "max"]
let levelNames = ["low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra", "max": "Max"]

/// The menu bar icon and its menu: the on/off switch for every session, each recent
/// session with its level and the latest reason, and Auto or Manual per session.
final class Controller: NSObject, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let updater = Updater()
    var setupResult = ""

    func start() {
        setupResult = Setup.install()
        if ChromeApprover.on { ChromeApprover.copyHelper() }
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        updater.changed = { [weak self] in self?.refreshIcon() }
        updater.start()
        State.refreshModels()
        Timer.scheduledTimer(withTimeInterval: 24 * 3600, repeats: true) { _ in State.refreshModels() }
        refreshIcon()
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refreshIcon() }
    }

    /// A gauge showing the level of the session used last; a pause sign when auto effort is off.
    func refreshIcon() {
        guard let b = item.button else { return }
        let last = State.sessions(hours: 1).first
        if State.paused {
            let img = NSImage(systemSymbolName: "pause.circle", accessibilityDescription: "Sttark Effort: off")
            img?.isTemplate = true
            b.image = img
        } else {
            b.image = GaugeIcon.image(last?.level)
        }
        b.toolTip = State.paused ? "Sttark Effort: off for every session"
            : last.map { "Sttark Effort: \($0.title) at \(levelNames[$0.level] ?? $0.level)\($0.manual ? " (Manual)" : "")" }
            ?? "Sttark Effort"
        b.appearsDisabled = State.paused
    }

    func menuWillOpen(_ menu: NSMenu) {
        updater.check()
        build(menu)
    }

    func build(_ menu: NSMenu) {
        menu.removeAllItems()
        let paused = State.paused

        menu.addItem(caption("Sttark Effort \(Updater.version)"))
        if updater.installing {
            menu.addItem(caption("Updating…"))
        } else if let r = updater.available {
            let u = action("Update to \(r.version)", #selector(update))
            u.attributedTitle = NSAttributedString(string: "Update to \(r.version)", attributes: [.font: font(14, true)])
            menu.addItem(u)
        }
        menu.addItem(.separator())

        let auto = action("Auto effort", #selector(togglePaused))
        auto.state = paused ? .off : .on
        menu.addItem(auto)
        menu.addItem(caption(paused ? "Off: every session keeps the level it has."
                                    : "Claude picks each session's effort per task."))
        let models = State.models
        if !models.isEmpty {
            let current = State.model ?? models.first(where: { $0.id.contains("haiku") })?.id ?? models[0].id
            let name = models.first(where: { $0.id == current })?.label ?? current
            let pick = NSMenuItem(title: "", action: nil, keyEquivalent: "")
            pick.attributedTitle = NSAttributedString(string: "Model: \(name)", attributes: [.font: font(14)])
            let sub = NSMenu()
            sub.autoenablesItems = false
            sub.addItem(caption("Picks the effort level. Newest Haiku and Sonnet models."))
            for m in models {
                let i = action(m.label + (m.id.contains("haiku") ? "  (faster, cheaper)" : "  (slower, smarter)"), #selector(pickModel(_:)))
                i.representedObject = m.id
                i.state = m.id == current ? .on : .off
                sub.addItem(i)
            }
            pick.submenu = sub
            menu.addItem(pick)
        }
        if !Setup.claudeFound { menu.addItem(caption("Claude Code isn't installed at ~/.local/bin/claude.")) }

        menu.addItem(.separator())
        let sessions = State.sessions()
        menu.addItem(header(sessions.isEmpty ? "No sessions in the last 12 hours" : "Sessions (click for Auto or Manual)"))
        for s in sessions.prefix(12) {
            let i = action("", #selector(toggleManual(_:)))
            i.attributedTitle = row(s, dim: paused)
            i.representedObject = s.id
            i.state = s.manual ? .off : .on
            i.toolTip = s.manual ? "Manual: you set the effort. Click to let Claude pick it again."
                                 : "Auto: Claude picks the effort. Click to set it yourself."
            menu.addItem(i)
            if !s.reason.isEmpty && !s.manual { menu.addItem(caption(s.reason, indent: 1)) }
        }

        menu.addItem(.separator())
        if Server.otherRunning {
            menu.addItem(caption("Phone sessions: a Remote Control server already runs on this Mac."))
        } else {
            let phone = action("Start sessions from your phone", #selector(togglePhone))
            phone.state = Server.installed ? .on : .off
            menu.addItem(phone)
            if Server.installed, let f = Server.folder {
                menu.addItem(caption("Sessions start in " + f.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~")))
            }
        }
        let skip = action("Skip approvals in phone sessions", #selector(toggleBypass))
        skip.state = Bypass.on ? .on : .off
        menu.addItem(skip)
        menu.addItem(caption("Sessions from a server started without approvals stay that way."))
        let chrome = action("Approve Claude in Chrome", #selector(toggleChrome))
        chrome.state = ChromeApprover.on ? .on : .off
        menu.addItem(chrome)
        menu.addItem(caption("Clicks Allow when Claude for Chrome asks to use a site."))
        if ChromeApprover.needsAccessibility {
            menu.addItem(action("Needs Accessibility permission…", #selector(openAccessibility)))
        }
        menu.addItem(.separator())
        menu.addItem(action("Open log", #selector(openLog)))
        if updater.available == nil && !updater.installing { menu.addItem(action("Check for updates", #selector(checkUpdates))) }
        menu.addItem(.separator())
        menu.addItem(action("Quit", #selector(quit), key: "q"))
    }

    // MARK: rows

    /// Brand type: Helvetica Neue (the guide's fallback for Founders Grotesk), 400 and 600 only.
    func font(_ size: CGFloat, _ semibold: Bool = false) -> NSFont {
        let f = NSFont(name: "Helvetica Neue", size: size) ?? .systemFont(ofSize: size)
        return semibold ? NSFontManager.shared.convert(f, toHaveTrait: .boldFontMask).withSize(size) : f
    }

    /// Session name in ink, level as a word in steel. No color for levels: the guide keeps an app's own
    /// meaning colors few and never green for data, and the word already says the level.
    func row(_ s: Session, dim: Bool) -> NSAttributedString {
        let t = NSMutableAttributedString()
        let title = s.title.count > 42 ? String(s.title.prefix(41)) + "…" : s.title
        t.append(NSAttributedString(string: title, attributes: [.font: font(14),
            .foregroundColor: dim ? NSColor.secondaryLabelColor : NSColor.labelColor]))
        let tag = (levelNames[s.level] ?? s.level) + (s.manual ? " · Manual" : "")
        let para = NSMutableParagraphStyle()
        para.tabStops = [NSTextTab(textAlignment: .right, location: 380)]
        t.append(NSAttributedString(string: "\t" + tag, attributes: [.font: font(14, true),
            .foregroundColor: NSColor.secondaryLabelColor]))
        t.addAttribute(.paragraphStyle, value: para, range: NSRange(location: 0, length: t.length))
        return t
    }

    func action(_ title: String, _ sel: Selector, key: String = "", enabled: Bool = true) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        i.attributedTitle = NSAttributedString(string: title, attributes: [.font: font(14)])
        i.target = self
        i.isEnabled = enabled
        return i
    }

    func header(_ text: String) -> NSMenuItem {
        if #available(macOS 14.0, *) { return NSMenuItem.sectionHeader(title: text) }
        return caption(text)
    }

    func caption(_ text: String, indent: Int = 0) -> NSMenuItem {
        let i = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        i.attributedTitle = NSAttributedString(string: text.count > 70 ? String(text.prefix(69)) + "…" : text, attributes: [
            .font: font(12), .foregroundColor: NSColor.secondaryLabelColor])
        i.indentationLevel = indent
        i.isEnabled = false
        return i
    }

    // MARK: actions

    @objc func pickModel(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        State.setModel(id)
    }

    @objc func toggleBypass() { Bypass.set(!Bypass.on) }

    @objc func toggleChrome() {
        if ChromeApprover.on { ChromeApprover.stop() } else { ChromeApprover.start() }
    }

    @objc func openAccessibility() { ChromeApprover.openAccessibility() }

    @objc func togglePhone() {
        if Server.installed { Server.stop() } else { Server.setUp() }
    }

    @objc func togglePaused() { State.setPaused(!State.paused); refreshIcon() }

    @objc func toggleManual(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        State.setManual(id, sender.state == .on)
        refreshIcon()
    }

    @objc func openLog() {
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        NSWorkspace.shared.open([logURL], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Console.app"),
                                configuration: NSWorkspace.OpenConfiguration())
    }

    @objc func update() { updater.install() }

    @objc func checkUpdates() {
        updater.check(force: true) { msg in
            let a = NSAlert()
            a.messageText = self.updater.available == nil ? "No update" : "Update ready"
            a.informativeText = msg
            if self.updater.available != nil { a.addButton(withTitle: "Update now"); a.addButton(withTitle: "Later") }
            NSApp.activate(ignoringOtherApps: true)
            if a.runModal() == .alertFirstButtonReturn && self.updater.available != nil { self.updater.install() }
        }
    }

    @objc func quit() { NSApp.terminate(nil) }
}

/// The menu bar gauge: the app icon's gauge (tools/make-icon.py) drawn small, with the needle on the dot
/// for the level. No level (no session lately) draws no needle, so it can't be mistaken for one.
enum GaugeIcon {
    static let angles: [String: CGFloat] = ["low": 170, "medium": 130, "high": 90, "xhigh": 50, "max": 10]

    static func image(_ level: String?) -> NSImage {
        let w: CGFloat = 22, h: CGFloat = 15
        let img = NSImage(size: NSSize(width: w, height: h), flipped: false) { _ in
            let s: CGFloat = 19 / 556          // the icon's 1024 grid, fitted to the menu bar
            let c = NSPoint(x: w / 2, y: 2.6)
            let r = 250 * s
            func at(_ deg: CGFloat, _ len: CGFloat) -> NSPoint {
                NSPoint(x: c.x + len * cos(deg * .pi / 180), y: c.y + len * sin(deg * .pi / 180))
            }
            NSColor.black.set()
            let arc = NSBezierPath()
            arc.appendArc(withCenter: c, radius: r, startAngle: 0, endAngle: 180)
            arc.lineWidth = 56 * s
            arc.lineCapStyle = .round
            arc.stroke()
            NSColor.black.withAlphaComponent(0.45).set()
            for d in angles.values {
                let p = at(d, r - 80 * s), dr = 18 * s
                NSBezierPath(ovalIn: NSRect(x: p.x - dr, y: p.y - dr, width: 2 * dr, height: 2 * dr)).fill()
            }
            NSColor.black.set()
            if let level, let d = angles[level] {
                let n = NSBezierPath()
                n.move(to: c)
                n.line(to: at(d, r - 70 * s))
                n.lineWidth = 52 * s
                n.lineCapStyle = .round
                n.stroke()
            }
            let hr = 58 * s
            NSBezierPath(ovalIn: NSRect(x: c.x - hr, y: c.y - hr, width: 2 * hr, height: 2 * hr)).fill()
            return true
        }
        img.isTemplate = true
        img.accessibilityDescription = "Sttark Effort" + (level.map { ": \($0)" } ?? "")
        return img
    }
}
