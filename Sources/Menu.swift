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
        return f
    }
}

/// A usage setting picked in a session's submenu.
final class UsagePick: NSObject {
    let target: Limit.Target
    let mode: Limit.Mode
    init(_ t: Limit.Target, _ m: Limit.Mode) { target = t; mode = m }
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
        Stable.keep(Server.installed)
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        item.menu = menu
        updater.changed = { [weak self] in self?.refreshIcon() }
        updater.busy = { [weak self] in self?.menuOpen == true || NSApp.modalWindow != nil }
        updater.start()
        State.refreshModels()
        Timer.scheduledTimer(withTimeInterval: 24 * 3600, repeats: true) { _ in State.refreshModels() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { Login.check() }
        Waiting.watchFront()
        Waiting.refresh()
        Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in Waiting.refresh() }
        Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { _ in Server.keepChats() }
        Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { _ in ChromeWindow.cleanTabs() }
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
        menuOpen = true
        updater.check()
        build(menu)
    }

    func menuDidClose(_ menu: NSMenu) { menuOpen = false }

    func build(_ menu: NSMenu) { build(menu, MenuFacts.current(updater)) }

    func build(_ menu: NSMenu, _ f: MenuFacts) {
        menu.removeAllItems()
        let paused = State.paused

        menu.addItem(caption("Sttark Claude Kit \(f.version)"))
        if f.installing {
            menu.addItem(caption("Updating…"))
        } else if let v = f.available {
            let u = action("Update to \(v)", #selector(update))
            u.attributedTitle = NSAttributedString(string: "Update to \(v)", attributes: [.font: font(14, true)])
            menu.addItem(u)
        }
        if let warn = f.loginWarning {
            let l = action(warn, #selector(signIn))
            l.attributedTitle = NSAttributedString(string: warn, attributes: [.font: font(14, true)])
            l.toolTip = f.loginTip
            menu.addItem(l)
        }
        let waiting = Waiting.sessions
        if !waiting.isEmpty {
            menu.addItem(.separator())
            for s in waiting {
                let i = action("", #selector(openWaiting(_:)))
                i.attributedTitle = row(s.title, (s.needsYou ? "needs you · " : "not opened · ") + Waiting.ago(s.waitingSince!),
                                        bold: s.needsYou, tagBold: false)
                i.representedObject = s.url
                i.toolTip = (s.needsYou ? (s.why.isEmpty ? "Claude needs you here." : "Claude needs you: \(s.why).")
                             : "Claude finished and you haven't opened the reply yet.") + " Click to open the session."
                menu.addItem(i)
            }
        }
        addLimit(menu)
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
        if !f.claudeFound { menu.addItem(caption("Claude Code isn't installed at ~/.local/bin/claude.")) }

        menu.addItem(.separator())
        addSessions(menu, paused: paused)

        menu.addItem(.separator())
        let credits = action("Use credits at the usage limit", #selector(toggleCredits))
        credits.state = Limit.creditsAll ? .on : .off
        credits.toolTip = (Limit.creditsAll
            ? "On: when your 5-hour or weekly limit is reached, sessions go on with usage credits."
            : "Off: when your 5-hour or weekly limit is reached, sessions wait and go on by themselves when it resets, so no usage credits are spent. To use credits for one session, click it under Usage limit reached, or send \"use credits\" in it.")
            + " A session set to Always use credits or Never use credits on its own row keeps that setting."
        menu.addItem(credits)
        let phone = action("Start sessions from the Claude app", #selector(togglePhone))
        if f.serverElsewhere {
            phone.state = .on
            phone.toolTip = "A Remote Control server set up outside Sttark Claude Kit already runs on this Mac."
        } else {
            phone.state = f.serverInstalled ? .on : .off
            phone.toolTip = f.serverFolder.map { "Sessions start in " + $0.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~") }
                ?? "Start Claude Code sessions on this Mac from the Claude app on your phone or any computer."
        }
        menu.addItem(phone)
        let skip = action("Bypass permissions for server sessions", #selector(toggleBypass))
        skip.state = f.bypass ? .on : .off
        skip.toolTip = "The Claude app, on desktop or phone, doesn't offer Bypass permissions for sessions on a Remote Control server. This turns it on for them."
        menu.addItem(skip)
        let chrome = action("Approve Claude in Chrome", #selector(toggleChrome))
        chrome.state = f.chromeApprover ? .on : .off
        chrome.toolTip = "Clicks Allow when Claude for Chrome asks to use a site."
        menu.addItem(chrome)
        let cw = action("Claude window in Chrome", #selector(toggleChromeWindow))
        cw.state = f.chromeWindow ? .on : .off
        cw.toolTip = "Claude uses one Chrome window named Claude, with your logins, each session in its own tab, and works there in the background, so Chrome stops jumping in front of what you're typing in. If the window closes, Claude makes a new one the next time it needs it; Chrome comes forward for a moment then, and the app you were in goes back in front."
        menu.addItem(cw)
        if f.chromeWindowClosed {
            let o = action("Open Claude window", #selector(openChromeWindow))
            o.toolTip = "The Claude window in Chrome was closed. Opens it now. Claude also opens it the next time it needs it."
            menu.addItem(o)
        }
        let links = action("Links to files", #selector(toggleFileLinks))
        links.state = f.fileLinks ? .on : .off
        links.toolTip = "When Claude gives you a file it made on this Mac, you get a link that opens it in your browser, on this Mac or your phone on the same network, instead of a file path that opens nothing."
        menu.addItem(links)
        let names = action("Name sessions automatically", #selector(toggleNames))
        names.state = f.names ? .on : .off
        names.toolTip = "Gives each Claude Code session a short handle for its project or area, in the style of your own names. When the work moves to another topic, it renames a session it named. It never changes a name you set."
        menu.addItem(names)
        let sync = action(f.profileSettingUp ? "Sync Claude profile instructions: setting up…" : "Sync Claude profile instructions",
                          #selector(toggleProfile), enabled: !f.profileSettingUp)
        sync.state = f.profile ? .on : .off
        sync.toolTip = "Copies the instructions from your Claude profile into Claude Code and puts them in front of every prompt, so running sessions see edits too."
            + (f.profile ? (f.profileLast.map { "\n\nLast sync: " + $0 } ?? "") : "")
        menu.addItem(sync)
        let rules = action("Sttark working rules", #selector(toggleWorkingRules))
        rules.state = f.workingRules ? .on : .off
        rules.toolTip = "Puts Sttark's working rules in front of every prompt: answer first, a plan with a step count, work handed to agents, a status table for a prompt with several asks, Simplified Technical English, and more. When a reply isn't in Simplified Technical English, the words to fix go in front of the session's next prompt. On unless you turn it off."
        menu.addItem(rules)
        if f.needsAccessibility {
            menu.addItem(action("Needs Accessibility permission…", #selector(openAccessibility)))
        }
        menu.addItem(.separator())
        let sign = action("Sign in to Claude Code…", #selector(signIn))
        sign.toolTip = f.loginTip
        menu.addItem(sign)
        menu.addItem(action("Open log", #selector(openLog)))
        if f.available == nil && !f.installing { menu.addItem(action("Check for updates", #selector(checkUpdates))) }
        menu.addItem(.separator())
        menu.addItem(action("Quit", #selector(quit), key: "q"))
    }

    // MARK: sessions

    /// Each recent session: its name, its level and its own usage setting, with a submenu to change either.
    func addSessions(_ menu: NSMenu, paused: Bool) {
        let sessions = State.sessions()
        if sessions.isEmpty { menu.addItem(caption("No sessions in the last 12 hours")); return }
        let state = State.read()
        for s in sessions.prefix(12) {
            let t = Limit.Target(sid: s.sid, cse: s.id, title: s.title)
            let mode = Limit.mode(t, in: state)
            let level = levelNames[s.level] ?? s.level
            let tag = ([level] + (s.manual ? ["Manual"] : []) + [mode.tag].compactMap { $0 }).joined(separator: " · ")
            let i = NSMenuItem(title: "", action: nil, keyEquivalent: "")
            i.attributedTitle = row(s.title, tag, dim: paused)
            i.state = s.manual ? .off : .on
            i.submenu = sessionMenu(s, t, mode)
            let why = s.reason.isEmpty || s.manual ? "" : "Why \(level): \(s.reason)\n\n"
            i.toolTip = why + (s.manual ? "Manual: you set the effort." : "Auto: Claude picks the effort.") + " " + usageWords(mode)
                + " Open it to change either."
            menu.addItem(i)
        }
    }

    /// A session's submenu: why its level, Auto effort, and what it does at the usage limit.
    func sessionMenu(_ s: Session, _ t: Limit.Target, _ mode: Limit.Mode) -> NSMenu {
        let sub = NSMenu()
        sub.autoenablesItems = false
        if !s.reason.isEmpty && !s.manual {
            for line in wrap("Why \(levelNames[s.level] ?? s.level): \(s.reason)", 52).prefix(3) { sub.addItem(caption(line)) }
        }
        let auto = action("Auto effort", #selector(toggleManual(_:)))
        auto.state = s.manual ? .off : .on
        auto.representedObject = s.id
        auto.toolTip = s.manual ? "Manual: you set this session's effort. Click to let Claude pick it again."
                                : "On: Claude picks this session's effort for each task. Click to set it yourself."
        sub.addItem(auto)
        sub.addItem(.separator())
        addUsage(sub, t, mode)
        return sub
    }

    /// The three settings for what one session does at the usage limit, the current one checked.
    func addUsage(_ menu: NSMenu, _ t: Limit.Target, _ mode: Limit.Mode) {
        menu.addItem(caption("At the usage limit"))
        usageItem(menu, "Follow the menu", .follow, t, mode).toolTip =
            "Does what Use credits at the usage limit says: waits for the reset when it's off, goes on with usage credits when it's on."
        usageItem(menu, "Always use credits", .credits, t, mode).toolTip =
            "Goes on with usage credits at the limit, even when Use credits at the usage limit is off."
        menu.addItem(caption("Never use credits; hold at:"))
        var choices = Limit.holdChoices
        if case .hold(let n) = mode, !choices.contains(n) { choices = (choices + [n]).sorted() }
        for n in choices {
            let i = usageItem(menu, "\(n)%", .hold(n), t, mode)
            i.indentationLevel = 1
            i.toolTip = n >= 100
                ? "Never uses usage credits: at the 5-hour or weekly limit it stops before its next step and waits, with no model calls, even when Use credits at the usage limit is on. It goes on by itself when the limit resets."
                : "Never uses usage credits. When the 5-hour or weekly limit reaches \(n)%, it stops before its next step and waits, with no model calls. It goes on by itself when the limit resets under \(n)%."
        }
    }

    @discardableResult
    func usageItem(_ menu: NSMenu, _ title: String, _ m: Limit.Mode, _ t: Limit.Target, _ current: Limit.Mode) -> NSMenuItem {
        let i = action(title, #selector(pickUsage(_:)))
        i.state = m == current ? .on : .off
        i.representedObject = UsagePick(t, m)
        menu.addItem(i)
        return i
    }

    func usageWords(_ m: Limit.Mode) -> String {
        switch m {
        case .follow: return "At the usage limit it follows the menu."
        case .credits: return "At the usage limit it goes on with usage credits."
        case .hold(let n): return "It never uses usage credits, and holds when a limit reaches \(n)%."
        }
    }

    // MARK: usage limit

    /// While a limit is reached or a session holds: the status first, then each holding session with its
    /// percentage and reset time. Nothing shows otherwise.
    func addLimit(_ menu: NSMenu) {
        let all = Limit.waiting
        let reached = Limit.reached
        let creditsAll = Limit.creditsAll
        let holds = all.filter(\.hold)
        let waits = creditsAll ? [] : all.filter { !$0.hold }   // with credits for every session, a wait ends at once
        guard reached != nil || !holds.isEmpty || !waits.isEmpty else { return }
        menu.addItem(.separator())
        let head = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        let atLimit = reached != nil || !waits.isEmpty
        let until = reached?.until ?? waits.map(\.until).max()
        head.attributedTitle = NSAttributedString(
            string: atLimit && until != nil ? "Usage limit reached · resets \(Limit.clock(until!))"
                : holds.count == 1 ? "1 session on hold" : "\(holds.count) sessions on hold",
            attributes: [.font: font(14, true)])
        head.isEnabled = false
        menu.addItem(head)
        let note: String
        if atLimit && creditsAll {
            note = holds.isEmpty ? "Sessions go on with usage credits" : "These hold and go on by themselves. Other sessions use credits."
        } else if !waits.isEmpty {
            note = holds.isEmpty ? "These wait and go on by themselves. Click one to use credits now." : "These wait and go on by themselves."
        } else if !holds.isEmpty {
            note = "These wait with no model calls and go on by themselves."
        } else {
            note = "A session that reaches it waits here for the reset"
        }
        menu.addItem(caption(note))
        for w in waits {
            let i = action("", #selector(useCredits(_:)))
            i.attributedTitle = row(w.title, "Use credits")
            i.representedObject = w.sid
            i.toolTip = "Waiting since \(Limit.clock(w.since)) for the \(w.limit) limit. It goes on by itself at \(Limit.clock(w.until)). "
                + agentsWords(w) + "Click to let this session go on now with usage credits."
            menu.addItem(i)
        }
        for w in holds {
            let i = NSMenuItem(title: "", action: nil, keyEquivalent: "")
            i.attributedTitle = row(w.title, "Hold \(w.at)% · until \(Limit.clock(w.until))")
            i.submenu = holdMenu(w)
            let level = w.percent.map { "the \(w.limit) limit was at \($0)% at \(Limit.clock(w.since))" }
                ?? "the \(w.limit) limit reached it at \(Limit.clock(w.since))"
            i.toolTip = "Holds at \(w.at)%: \(level). It waits with no model calls and goes on by itself at \(Limit.clock(w.until)), when the limit resets. "
                + agentsWords(w) + "Open it to change its setting, or to use credits now."
            menu.addItem(i)
        }
    }

    /// A holding session's submenu: go on now with credits, or change its setting.
    func holdMenu(_ w: Limit.Waiting) -> NSMenu {
        let sub = NSMenu()
        sub.autoenablesItems = false
        let use = action("Use credits until \(Limit.clock(w.until))", #selector(useCredits(_:)))
        use.representedObject = w.sid
        use.toolTip = "Goes on now, and may use usage credits until the limit resets at \(Limit.clock(w.until)). After that, its setting applies again."
        sub.addItem(use)
        sub.addItem(.separator())
        addUsage(sub, w.target, Limit.mode(w.target))
        return sub
    }

    func agentsWords(_ w: Limit.Waiting) -> String {
        w.agents == 0 ? "" : w.agents == 1 ? "1 of its agents waits too. " : "\(w.agents) of its agents wait too. "
    }

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

    @objc func pickModel(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        State.setModel(id)
    }

    @objc func toggleBypass() { Bypass.set(!Bypass.on) }
    @objc func toggleCredits() { Limit.setCreditsAll(!Limit.creditsAll) }

    @objc func useCredits(_ sender: NSMenuItem) {
        guard let sid = sender.representedObject as? String, let w = Limit.waiting.first(where: { $0.sid == sid }) else { return }
        Limit.useCredits(w)
    }

    @objc func pickUsage(_ sender: NSMenuItem) {
        guard let p = sender.representedObject as? UsagePick else { return }
        Limit.setMode(p.mode, for: p.target)
    }

    @objc func toggleChrome() {
        if ChromeApprover.on { ChromeApprover.stop() } else { ChromeApprover.start() }
    }

    @objc func signIn() { Login.signIn() }
    @objc func openWaiting(_ sender: NSMenuItem) { Waiting.open(sender.representedObject as? String ?? "") }
    @objc func toggleChromeWindow() { ChromeWindow.set(!ChromeWindow.on) }
    @objc func openChromeWindow() { ChromeWindow.open() }

    @objc func toggleFileLinks() { FileLinks.set(!FileLinks.on) }
    @objc func toggleNames() { Names.set(!Names.on) }
    @objc func toggleWorkingRules() { WorkingRules.set(!WorkingRules.on) }

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
