import AppKit

let levels = ["low", "medium", "high", "xhigh", "max"]
let levelNames = ["low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra", "max": "Max"]

/// What the menu shows besides the sessions and the usage limit, read once each time it opens. The drawing tool
/// (tools/screenshot.swift) passes made-up facts instead, so it draws the menu with this same code and runs nothing.
struct MenuFacts {
    var version = Updater.version
    var installing = false
    /// The version of an update that waits to install.
    var available: String? = nil
    var loginWarning: String? = nil
    var loginTip = ""
    var claudeFound = true
    var serverElsewhere = false
    var serverInstalled = false
    var serverFolder: String? = nil
    var bypass = false
    var chromeApprover = false
    var needsAccessibility = false
    var chromeWindow = false
    var chromeWindowClosed = false
    var fileLinks = false
    var names = false
    var profile = false
    var profileSettingUp = false
    var profileLast: String? = nil
    var workingRules = false
    var reach = Reach.Settings(ways: ["email"], email: "name@sttark.com", phone: "", chat: "")
    /// What's new: how many notes there are, and how many this person hasn't seen.
    var whatsNew = 0
    var whatsNewUnseen = 0
    /// For the window's Settings page.
    var paused = false
    var creditsAll = false
    var models: [(id: String, label: String)] = []
    var model = ""
    var loginEnds: Date? = nil
    var signedIn = true
    var lastCheck: Date? = nil

    /// The real facts. Some of them run commands, which lets the update check's answer land part way through, so
    /// the update state is read first.
    static func current(_ u: Updater) -> MenuFacts {
        var f = MenuFacts()
        f.installing = u.installing
        f.available = u.available?.version
        f.loginWarning = Login.urgent
        f.loginTip = Login.tip
        f.claudeFound = Setup.claudeFound
        f.serverElsewhere = Server.otherRunning
        f.serverInstalled = Server.installed
        f.serverFolder = Server.folder
        f.bypass = Bypass.on
        f.chromeApprover = ChromeApprover.on
        f.needsAccessibility = ChromeApprover.needsAccessibility
        f.chromeWindow = ChromeWindow.on
        f.chromeWindowClosed = f.chromeWindow && ChromeWindow.chromeRunning && !ChromeWindow.exists
        f.fileLinks = FileLinks.on
        f.names = Names.on
        f.profile = ProfileSync.on
        f.profileSettingUp = ProfileSync.settingUp
        f.profileLast = ProfileSync.lastResult
        f.workingRules = WorkingRules.on
        f.reach = Reach.settings()
        f.whatsNew = WhatsNew.all.count
        f.whatsNewUnseen = WhatsNew.unseen.count
        f.paused = State.paused
        f.creditsAll = Limit.creditsAll
        f.models = State.models
        f.model = State.model ?? f.models.first(where: { $0.id.contains("sonnet") })?.id ?? f.models.first?.id ?? ""
        if let i = Login.read() { f.loginEnds = i.ends; f.signedIn = i.signedIn }
        f.lastCheck = u.lastCheck == .distantPast ? nil : u.lastCheck
        return f
    }
}

/// The menu bar icon and its menu: the on/off switch for every session, each recent session with its level and
/// its own usage setting, and the sessions holding at the usage limit.
final class Controller: NSObject, NSMenuDelegate {
    /// Made in start(), so the drawing tool can use the menu code without putting an icon in the menu bar.
    lazy var item: NSStatusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let updater = Updater()
    var setupResult = ""
    var menuOpen = false
    /// Where the tags on the right of the rows line up.
    static let tab: CGFloat = 380

    func start() {
        setupResult = Setup.install()
        if ChromeApprover.on { ChromeApprover.copyHelper() }
        if ChromeWindow.on { ChromeWindow.installTool() }
        ChromeWindow.tellHooks()
        FileLinks.refresh()
        KitDefaults.apply()
        NotificationCenter.default.addObserver(forName: .init("kitOpenSettings"), object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }
            KitWindow.shared.show(.settings, controller: self)
        }
        Stable.keep(Server.installed)
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        updater.changed = { [weak self] in self?.refreshIcon() }
        updater.busy = { [weak self] in self?.menuOpen == true || NSApp.modalWindow != nil || KitWindow.shared.inUse }
        updater.start()
        State.refreshModels()
        Timer.scheduledTimer(withTimeInterval: 24 * 3600, repeats: true) { _ in State.refreshModels() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { Login.check() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 40) { Server.autoStart() }
        Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { _ in Server.autoStart() }
        Waiting.watchFront()
        Waiting.refresh()
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in Waiting.refresh() }
        Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { _ in Server.keepChats() }
        Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { _ in ChromeWindow.cleanTabs() }
        Timer.scheduledTimer(withTimeInterval: 600, repeats: true) { _ in KitDefaults.applyBypassSettings() }
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in Reach.poll() }
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in Waits.check() }
        LocalSessions.scan()
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in LocalSessions.scan() }
        Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { _ in Login.check() }
        KitLogs.start()
        WhatsNew.start(changed: { [weak self] in self?.refreshIcon(); KitWindow.shared.model.unseen = WhatsNew.unseen.count })
        refreshIcon()
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refreshIcon() }
    }

    /// A gauge showing the level of the session used last; a pause sign when auto effort is off. A dot while a
    /// What's new note is unseen.
    func refreshIcon() {
        guard let b = item.button else { return }
        let last = State.sessions(hours: 1).first
        let new = WhatsNew.unseen
        if State.paused && new.isEmpty {
            let img = NSImage(systemSymbolName: "pause.circle", accessibilityDescription: "Sttark Claude Kit: off")
            img?.isTemplate = true
            b.image = img
        } else {
            b.image = GaugeIcon.image(State.paused ? nil : last?.level, dot: !new.isEmpty)
        }
        b.toolTip = (State.paused ? "Sttark Claude Kit: off for every session"
            : last.map { "Sttark Claude Kit: \($0.title) at \(levelNames[$0.level] ?? $0.level)\($0.manual ? " (Manual)" : "")" }
            ?? "Sttark Claude Kit")
            + (new.isEmpty ? "" : "\n\nWhat's new: " + new.map(\.title).joined(separator: "; ") + ". Click What's new in the menu.")
        b.appearsDisabled = State.paused && new.isEmpty
    }

    func menuWillOpen(_ menu: NSMenu) {
        menuOpen = true
        updater.check()
        build(menu)
    }

    func menuDidClose(_ menu: NSMenu) {
        menuOpen = false
    }

    func build(_ menu: NSMenu) { build(menu, MenuFacts.current(updater)) }

    func build(_ menu: NSMenu, _ f: MenuFacts) { build(menu, f, Inbox.snapshot()) }

    /// A short glance: what needs the person, the count in each group, and the way into the window, where every
    /// session and every setting is.
    func build(_ menu: NSMenu, _ f: MenuFacts, _ snap: Inbox.Snapshot) {
        menu.removeAllItems()
        menu.addItem(caption("Sttark Claude Kit \(f.version)"))
        if f.installing {
            menu.addItem(caption("Updating…"))
        } else if let v = f.available {
            let u = action("Update to \(v)", #selector(update))
            u.attributedTitle = NSAttributedString(string: "Update to \(v)", attributes: [.font: font(14, true)])
            menu.addItem(u)
        }
        if !f.claudeFound {
            let t = "Claude Code isn't installed: Install…"
            let i = action(t, #selector(installClaudeCode))
            i.attributedTitle = NSAttributedString(string: t, attributes: [.font: font(14, true)])
            i.toolTip = Login.missingTip
            menu.addItem(i)
        }
        if let warn = f.loginWarning {
            let l = action(warn, #selector(signIn))
            l.attributedTitle = NSAttributedString(string: warn, attributes: [.font: font(14, true)])
            l.toolTip = f.loginTip
            menu.addItem(l)
        }
        if f.needsAccessibility {
            menu.addItem(action("Needs Accessibility permission…", #selector(openAccessibility)))
        }

        menu.addItem(.separator())
        if snap.rows.isEmpty {
            menu.addItem(caption("No sessions in the last 12 hours"))
        }
        // the most urgent first: what needs you, then what holds at the limit, each row opens the window at it
        for g in [Inbox.Group.needs, .held, .working, .waits] {
            let rows = snap.rows(g)
            guard !rows.isEmpty else { continue }
            let head = action("", #selector(openGroup(_:)))
            head.attributedTitle = row(g.title, "\(rows.count)", bold: true, tagBold: true)
            head.representedObject = rows.first?.id
            head.toolTip = "Opens Sttark Claude Kit at \(g.title.lowercased())."
            menu.addItem(head)
            if g == .waits {  // a wait whose check fails shows, so it never fails silently
                for r in rows where r.subWarn {
                    let i = action("", #selector(openRow(_:)))
                    i.attributedTitle = row(r.title, "check failing", tagBold: true)
                    i.representedObject = r.id
                    i.toolTip = (r.waits.first { !$0.failing.isEmpty }?.failing ?? "") + ". Click to see it in Sttark Claude Kit."
                    menu.addItem(i)
                }
            }
            guard g == .needs || g == .held else { continue }
            for r in rows.prefix(g == .needs ? 5 : 3) {
                let i = action("", #selector(openRow(_:)))
                i.attributedTitle = row(r.title, r.time, tagBold: r.late)
                i.representedObject = r.id
                i.toolTip = r.sub + ". Click to see it in Sttark Claude Kit."
                menu.addItem(i)
            }
            if rows.count > (g == .needs ? 5 : 3) { menu.addItem(caption("and \(rows.count - (g == .needs ? 5 : 3)) more")) }
        }

        menu.addItem(.separator())
        let open = action("Open Sttark Claude Kit", #selector(openWindow))
        open.toolTip = "Every session, with its settings, and every setting of the Kit."
        menu.addItem(open)
        let unseen = f.whatsNewUnseen
        let news = action("What's new", #selector(showWhatsNew))
        if unseen > 0 { news.badge = NSMenuItemBadge.newItems(count: unseen) }
        news.toolTip = unseen > 0 ? "What changed in the Kit since you last looked." : "Short notes on the changes you notice, newest first."
        news.isEnabled = f.whatsNew > 0
        menu.addItem(news)
        menu.addItem(.separator())
        menu.addItem(action("Quit", #selector(quit), key: "q"))
    }

    // MARK: the window

    @objc func openWindow() { KitWindow.shared.show(.sessions, controller: self) }
    @objc func openRow(_ sender: NSMenuItem) { KitWindow.shared.show(.sessions, select: sender.representedObject as? String, controller: self) }
    @objc func openGroup(_ sender: NSMenuItem) { openRow(sender) }

    // MARK: rows

    /// Brand type: Helvetica Neue (the guide's fallback for Founders Grotesk), 400 and 600 only.
    func font(_ size: CGFloat, _ semibold: Bool = false) -> NSFont {
        let f = NSFont(name: "Helvetica Neue", size: size) ?? .systemFont(ofSize: size)
        return semibold ? NSFontManager.shared.convert(f, toHaveTrait: .boldFontMask).withSize(size) : f
    }

    /// A row: the name in ink on the left, a short tag in steel on the right. The name is cut to fit, so every tag
    /// lines up in one column. No color for levels or holds: the guide keeps an app's own meaning colors few and
    /// never green for data, and the words already say it.
    func row(_ title: String, _ tag: String, dim: Bool = false, bold: Bool = false, tagBold: Bool = true) -> NSAttributedString {
        let right = NSAttributedString(string: tag, attributes: [.font: font(14, tagBold), .foregroundColor: NSColor.secondaryLabelColor])
        let t = NSMutableAttributedString(string: fit(title, font(14, bold), Controller.tab - right.size().width - 20),
                                          attributes: [.font: font(14, bold),
                                                       .foregroundColor: dim ? NSColor.secondaryLabelColor : NSColor.labelColor])
        t.append(NSAttributedString(string: "\t"))
        t.append(right)
        let para = NSMutableParagraphStyle()
        para.tabStops = [NSTextTab(textAlignment: .right, location: Controller.tab)]
        t.addAttribute(.paragraphStyle, value: para, range: NSRange(location: 0, length: t.length))
        return t
    }

    /// The text, cut with "…" to fit the width.
    func fit(_ s: String, _ f: NSFont, _ width: CGFloat) -> String {
        func w(_ x: String) -> CGFloat { NSAttributedString(string: x, attributes: [.font: f]).size().width }
        guard w(s) > width else { return s }
        var t = s
        while !t.isEmpty && w(t.trimmingCharacters(in: .whitespaces) + "…") > width { t.removeLast() }
        return t.trimmingCharacters(in: .whitespaces) + "…"
    }

    /// Lines of at most `width` characters, broken between words.
    func wrap(_ s: String, _ width: Int) -> [String] {
        var lines: [String] = [], line = ""
        for word in s.split(separator: " ") {
            if !line.isEmpty && line.count + 1 + word.count > width { lines.append(line); line = "" }
            line += (line.isEmpty ? "" : " ") + word
        }
        if !line.isEmpty { lines.append(line) }
        return lines
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

    @objc func toggleBypass() {
        let on = !Bypass.on
        KitDefaults.chose("bypass", on: on)
        Bypass.set(on)
        if on { KitDefaults.applyBypassSettings() } else { KitDefaults.bypassOff() }
    }
    @objc func toggleCredits() { Limit.setCreditsAll(!Limit.creditsAll) }

    @objc func toggleChrome() {
        if ChromeApprover.on { ChromeApprover.stop(); KitDefaults.chose("chrome", on: false) } else { ChromeApprover.start(); KitDefaults.chose("chrome", on: true) }
    }

    @objc func signIn() { Login.signIn() }
    @objc func installClaudeCode() { Login.installClaudeCode() }
    @objc func toggleChromeWindow() { ChromeWindow.set(!ChromeWindow.on) }
    @objc func openChromeWindow() { ChromeWindow.open() }

    @objc func toggleFileLinks() { let on = !FileLinks.on; FileLinks.set(on); KitDefaults.chose("fileLinks", on: on) }
    @objc func toggleNames() { let on = !Names.on; Names.set(on); KitDefaults.chose("names", on: on) }
    @objc func toggleWorkingRules() { WorkingRules.set(!WorkingRules.on) }

    @objc func toggleProfile() {
        if ProfileSync.on { ProfileSync.stop(); KitDefaults.chose("profile", on: false); return }
        guard ProfileSync.claudeAppSignedIn else {
            let a = NSAlert()
            a.messageText = "Needs the Claude app"
            a.informativeText = "The sync reads your profile with the Claude desktop app's sign-in. Install the Claude app, sign in, then turn this on."
            NSApp.activate(ignoringOtherApps: true)
            a.runModal()
            return
        }
        ProfileSync.start { err in
            guard let err else { KitDefaults.chose("profile", on: true); return }
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
        if Server.installed { Server.stop(); KitDefaults.chose("server", on: false) }
        else { Server.setUp(); if Server.installed { KitDefaults.chose("server", on: true) } }
    }

    @objc func togglePaused() { State.setPaused(!State.paused); refreshIcon() }

    /// The window's Events page: what the Kit did, in plain words, newest first.
    @objc func openLog() { KitWindow.shared.show(.events, controller: self) }

    @objc func update() { updater.install() }
    @objc func showWhatsNew() { KitWindow.shared.show(KitWindow.shared.window?.isVisible == true ? KitWindow.shared.model.page : .sessions, sheet: true, controller: self) }

    /// A new version installs right away; otherwise a dialog says why not.
    @objc func checkUpdates() {
        updater.check(force: true) { msg in
            if self.updater.available != nil { self.updater.install(); return }
            let a = NSAlert()
            a.messageText = "No update"
            a.informativeText = msg
            NSApp.activate(ignoringOtherApps: true)
            a.runModal()
        }
    }

    @objc func quit() { NSApp.terminate(nil) }
}

/// The menu bar gauge: the app icon's gauge (tools/make-icon.py) drawn small, with the needle on the dot
/// for the level. No level (no session lately) draws no needle, so it can't be mistaken for one.
enum GaugeIcon {
    static let angles: [String: CGFloat] = ["low": 170, "medium": 130, "high": 90, "xhigh": 50, "max": 10]

    /// `dot`: a What's new note is unseen. The dot is the brand's information blue, so the image can't be a
    /// template one; it draws the gauge in the menu bar's own ink for its light or dark look instead.
    static func image(_ level: String?, dot: Bool = false) -> NSImage {
        let gw: CGFloat = 22, w: CGFloat = dot ? 27 : 22, h: CGFloat = 15
        let img = NSImage(size: NSSize(width: w, height: h), flipped: false) { _ in
            let dark = NSAppearance.currentDrawing().bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            let ink: NSColor = dot ? (dark ? .white : .black) : .black
            let s: CGFloat = 19 / 556          // the icon's 1024 grid, fitted to the menu bar
            let c = NSPoint(x: gw / 2, y: 2.6)
            let r = 250 * s
            func at(_ deg: CGFloat, _ len: CGFloat) -> NSPoint {
                NSPoint(x: c.x + len * cos(deg * .pi / 180), y: c.y + len * sin(deg * .pi / 180))
            }
            ink.set()
            let arc = NSBezierPath()
            arc.appendArc(withCenter: c, radius: r, startAngle: 0, endAngle: 180)
            arc.lineWidth = 56 * s
            arc.lineCapStyle = .round
            arc.stroke()
            ink.withAlphaComponent(0.45).set()
            for d in angles.values {
                let p = at(d, r - 80 * s), dr = 18 * s
                NSBezierPath(ovalIn: NSRect(x: p.x - dr, y: p.y - dr, width: 2 * dr, height: 2 * dr)).fill()
            }
            ink.set()
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
            if dot {
                Tokens.infoMark.resolved(dark).setFill()
                NSBezierPath(ovalIn: NSRect(x: w - 7.5, y: h - 8, width: 7, height: 7)).fill()
            }
            return true
        }
        img.isTemplate = !dot
        img.accessibilityDescription = "Sttark Claude Kit" + (level.map { ": \($0)" } ?? "") + (dot ? ", What's new" : "")
        return img
    }
}
