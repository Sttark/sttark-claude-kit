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
        if ChromeWindow.on { ChromeWindow.installTool() }
        ChromeWindow.tellHooks()
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        updater.changed = { [weak self] in self?.refreshIcon() }
        updater.start()
        State.refreshModels()
        Timer.scheduledTimer(withTimeInterval: 24 * 3600, repeats: true) { _ in State.refreshModels() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { Login.check() }
        Waiting.refresh()
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in Waiting.refresh() }
        Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { _ in Login.check() }
        refreshIcon()
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refreshIcon() }
    }

    /// A gauge showing the level of the session used last; a pause sign when auto effort is off.
    func refreshIcon() {
        guard let b = item.button else { return }
        let last = State.sessions(hours: 1).first
        if State.paused {
            let img = NSImage(systemSymbolName: "pause.circle", accessibilityDescription: "Sttark Claude Kit: off")
            img?.isTemplate = true
            b.image = img
        } else {
            b.image = GaugeIcon.image(last?.level)
        }
        b.toolTip = State.paused ? "Sttark Claude Kit: off for every session"
            : last.map { "Sttark Claude Kit: \($0.title) at \(levelNames[$0.level] ?? $0.level)\($0.manual ? " (Manual)" : "")" }
            ?? "Sttark Claude Kit"
        b.appearsDisabled = State.paused
    }

    func menuWillOpen(_ menu: NSMenu) {
        updater.check()
        build(menu)
    }

    func build(_ menu: NSMenu) {
        menu.removeAllItems()
        let paused = State.paused

        menu.addItem(caption("Sttark Claude Kit \(Updater.version)"))
        if updater.installing {
            menu.addItem(caption("Updating…"))
        } else if let r = updater.available {
            let u = action("Update to \(r.version)", #selector(update))
            u.attributedTitle = NSAttributedString(string: "Update to \(r.version)", attributes: [.font: font(14, true)])
            menu.addItem(u)
        }
        if let warn = Login.urgent {
            let l = action(warn, #selector(signIn))
            l.attributedTitle = NSAttributedString(string: warn, attributes: [.font: font(14, true)])
            l.toolTip = Login.tip
            menu.addItem(l)
        }
        let waiting = Waiting.sessions
        if !waiting.isEmpty {
            menu.addItem(.separator())
            for s in waiting {
                let i = action("", #selector(openWaiting(_:)))
                let t = NSMutableAttributedString(string: s.title.count > 40 ? String(s.title.prefix(39)) + "…" : s.title,
                                                  attributes: [.font: font(14, true)])
                let para = NSMutableParagraphStyle()
                para.tabStops = [NSTextTab(textAlignment: .right, location: 380)]
                t.append(NSAttributedString(string: "\twaiting " + Waiting.ago(s.waitingSince!),
                                            attributes: [.font: font(14), .foregroundColor: NSColor.secondaryLabelColor]))
                t.addAttribute(.paragraphStyle, value: para, range: NSRange(location: 0, length: t.length))
                i.attributedTitle = t
                i.representedObject = s.url
                i.toolTip = (s.why.isEmpty ? "Claude needs you here." : "Claude needs you: \(s.why).") + " Click to open the session."
                menu.addItem(i)
            }
        }
        menu.addItem(.separator())

        let auto = action("Auto effort", #selector(togglePaused))
        auto.state = paused ? .off : .on
        auto.toolTip = paused ? "Off: every session keeps the level it has." : "On: Claude picks each session's effort for each task."
        menu.addItem(auto)
        let models = State.models
        if !models.isEmpty {
            let current = State.model ?? models.first(where: { $0.id.contains("sonnet") })?.id ?? models[0].id
            let name = models.first(where: { $0.id == current })?.label ?? current
            let pick = NSMenuItem(title: "", action: nil, keyEquivalent: "")
            pick.attributedTitle = NSAttributedString(string: "Model: \(name)", attributes: [.font: font(14)])
            let sub = NSMenu()
            sub.autoenablesItems = false
            for m in models {
                let i = action(m.label + (m.id.contains("haiku") ? "  (faster, cheaper)" : "  (slower, smarter)"), #selector(pickModel(_:)))
                i.representedObject = m.id
                i.state = m.id == current ? .on : .off
                sub.addItem(i)
            }
            pick.submenu = sub
            pick.toolTip = "The model that picks the effort level. The newest Haiku and Sonnet models."
            menu.addItem(pick)
        }
        if !Setup.claudeFound { menu.addItem(caption("Claude Code isn't installed at ~/.local/bin/claude.")) }

        menu.addItem(.separator())
        let sessions = State.sessions()
        if sessions.isEmpty { menu.addItem(caption("No sessions in the last 12 hours")) }
        for s in sessions.prefix(12) {
            let i = action("", #selector(toggleManual(_:)))
            i.attributedTitle = row(s, dim: paused)
            i.representedObject = s.id
            i.state = s.manual ? .off : .on
            let why = s.reason.isEmpty || s.manual ? "" : "Why \(levelNames[s.level] ?? s.level): \(s.reason)\n\n"
            i.toolTip = why + (s.manual ? "Manual: you set the effort. Click to let Claude pick it again."
                                        : "Auto: Claude picks the effort. Click to set it yourself.")
            menu.addItem(i)
        }

        menu.addItem(.separator())
        let phone = action("Start sessions from the Claude app", #selector(togglePhone))
        if Server.otherRunning {
            phone.state = .on
            phone.toolTip = "A Remote Control server set up outside Sttark Claude Kit already runs on this Mac."
        } else {
            phone.state = Server.installed ? .on : .off
            phone.toolTip = Server.folder.map { "Sessions start in " + $0.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~") }
                ?? "Start Claude Code sessions on this Mac from the Claude app on your phone or any computer."
        }
        menu.addItem(phone)
        let skip = action("Bypass permissions for server sessions", #selector(toggleBypass))
        skip.state = Bypass.on ? .on : .off
        skip.toolTip = "The Claude app, on desktop or phone, doesn't offer Bypass permissions for sessions on a Remote Control server. This turns it on for them."
        menu.addItem(skip)
        let chrome = action("Approve Claude in Chrome", #selector(toggleChrome))
        chrome.state = ChromeApprover.on ? .on : .off
        chrome.toolTip = "Clicks Allow when Claude for Chrome asks to use a site."
        menu.addItem(chrome)
        let cw = action("Claude window in Chrome", #selector(toggleChromeWindow))
        cw.state = ChromeWindow.on ? .on : .off
        cw.toolTip = "Claude uses one Chrome window named Claude, with your logins, and moves it between pages instead of opening tabs or windows, so Chrome stops jumping in front of what you're typing in."
        menu.addItem(cw)
        if ChromeWindow.on && ChromeWindow.chromeRunning && !ChromeWindow.exists {
            let o = action("Open Claude window", #selector(openChromeWindow))
            o.toolTip = "The Claude window in Chrome was closed. Opens it again; Chrome comes forward this once."
            menu.addItem(o)
        }
        let names = action("Name sessions automatically", #selector(toggleNames))
        names.state = Names.on ? .on : .off
        names.toolTip = "Gives each Claude Code session a short handle for its project or area, in the style of your own names. Never changes a name once set."
        menu.addItem(names)
        let sync = action(ProfileSync.settingUp ? "Sync Claude profile instructions: setting up…" : "Sync Claude profile instructions",
                          #selector(toggleProfile), enabled: !ProfileSync.settingUp)
        sync.state = ProfileSync.on ? .on : .off
        sync.toolTip = "Copies the instructions from your Claude profile into Claude Code and puts them in front of every prompt, so running sessions see edits too."
            + (ProfileSync.on ? (ProfileSync.lastResult.map { "\n\nLast sync: " + $0 } ?? "") : "")
        menu.addItem(sync)
        if ChromeApprover.needsAccessibility {
            menu.addItem(action("Needs Accessibility permission…", #selector(openAccessibility)))
        }
        menu.addItem(.separator())
        let sign = action("Sign in to Claude Code…", #selector(signIn))
        sign.toolTip = Login.tip
        menu.addItem(sign)
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

    @objc func signIn() { Login.signIn() }
    @objc func openWaiting(_ sender: NSMenuItem) { Waiting.open(sender.representedObject as? String ?? "") }
    @objc func toggleChromeWindow() { ChromeWindow.set(!ChromeWindow.on) }
    @objc func openChromeWindow() { ChromeWindow.open() }

    @objc func toggleNames() { Names.set(!Names.on) }

    @objc func toggleProfile() {
        if ProfileSync.on { ProfileSync.stop(); return }
        guard ProfileSync.claudeAppSignedIn else {
            let a = NSAlert()
            a.messageText = "Needs the Claude app"
            a.informativeText = "The sync reads your profile with the Claude desktop app's sign-in. Install the Claude app, sign in, then turn this on."
            NSApp.activate(ignoringOtherApps: true)
            a.runModal()
            return
        }
        ProfileSync.start { err in
            guard let err else { return }
            let a = NSAlert()
            a.messageText = "Couldn't turn on the sync"
            a.informativeText = err
            NSApp.activate(ignoringOtherApps: true)
            a.runModal()
        }
    }

    @objc func openAccessibility() { ChromeApprover.openAccessibility() }

    @objc func togglePhone() {
        if Server.otherRunning {
            let a = NSAlert()
            a.messageText = "Already set up"
            a.informativeText = "A Remote Control server set up outside Sttark Claude Kit already runs on this Mac, so it's left as it is."
            NSApp.activate(ignoringOtherApps: true)
            a.runModal()
            return
        }
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
        img.accessibilityDescription = "Sttark Claude Kit" + (level.map { ": \($0)" } ?? "")
        return img
    }
}
