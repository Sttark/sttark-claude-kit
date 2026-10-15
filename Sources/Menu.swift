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
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        updater.changed = { [weak self] in self?.refreshIcon() }
        updater.start()
        refreshIcon()
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refreshIcon() }
    }

    /// A gauge showing the level of the session used last; a pause sign when auto effort is off.
    func refreshIcon() {
        guard let b = item.button else { return }
        let last = State.sessions(hours: 1).first
        let name: String
        if State.paused {
            name = "pause.circle"
        } else {
            let pct = ["low": "0", "medium": "33", "high": "50", "xhigh": "67", "max": "100"][last?.level ?? ""] ?? "50"
            name = "gauge.with.dots.needle.\(pct)percent"
        }
        let img = NSImage(systemSymbolName: name, accessibilityDescription: "Sttark Effort")
        img?.isTemplate = true
        b.image = img
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

        if let r = updater.available {
            menu.addItem(action(updater.installing ? "Updating…" : "Update to \(r.version)", #selector(update), enabled: !updater.installing))
            menu.addItem(.separator())
        }

        let auto = action("Auto effort", #selector(togglePaused))
        auto.state = paused ? .off : .on
        menu.addItem(auto)
        menu.addItem(caption(paused ? "Off: every session keeps the level it has."
                                    : "Claude picks each session's effort per task."))
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
        menu.addItem(action("Open log", #selector(openLog)))
        menu.addItem(action("Check for updates", #selector(checkUpdates)))
        let about = caption("Sttark Effort \(Updater.version)")
        menu.addItem(about)
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
            a.messageText = "Sttark Effort"
            a.informativeText = msg
            NSApp.activate(ignoringOtherApps: true)
            a.runModal()
        }
    }

    @objc func quit() { NSApp.terminate(nil) }
}
