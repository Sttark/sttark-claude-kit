import Foundation

/// Checks that the server the Kit set up is really connected, and fixes what stops it, with no one pressing a button.
///
/// `claude rc` runs inside `screen`, so a question it asks waits there with no one to see it. In a folder Claude Code
/// hasn't been trusted in, it asks "Trust <folder>? [y/N]" before it connects; on a first run it can also ask
/// "Enable Remote Control? (y/n)". A LaunchAgent that is installed is not a server that is connected. Every 30 seconds
/// the Kit reads the server's screen and:
/// - answers those two questions with y (the person chose this folder, or the Kit chose it for them);
/// - notes when it is connected (the screen shows "Connected" and the environment), and tells the person once;
/// - sees a known refusal (Remote Control off for the organization, signed out, a long-lived token) and says so;
/// - starts the server again when it hasn't connected after 3 minutes, or when it keeps stopping, with a back-off.
enum ServerHealth {
    enum Screen: Equatable {
        case connected(String)      // the folder's name, as the Claude app lists it under Remote Control
        case trustPrompt
        case enablePrompt
        case failed(String)         // a reason in plain words
        case starting               // nothing to act on yet
    }

    /// What the server's screen says. Pure, so tools/server-auto-test.swift tests it with real screens.
    static func read(_ text: String) -> Screen {
        let lines = text.replacingOccurrences(of: "\r", with: "").split(separator: "\n", omittingEmptySubsequences: true)
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let all = lines.joined(separator: "\n")
        // Connected: the status line, or the lines a connected server keeps at the bottom of its screen. With many
        // sessions listed, the status line can scroll off the top, so any of them counts.
        if all.contains("Capacity:") || all.contains("environment=") || all.contains("space to show QR code") {
            // "· Connected · src": the name after the last dot
            let name = lines.last(where: { $0.contains("Connected") })?.components(separatedBy: "Connected").last?
                .trimmingCharacters(in: CharacterSet(charactersIn: " ·\u{00B7}\u{FFFD}")) ?? ""
            return .connected(name)
        }
        let last = lines.last ?? ""
        if last.hasPrefix("Enable Remote Control?") || last.hasSuffix("(y/n)") && all.contains("Enable Remote Control?") { return .enablePrompt }
        if last.hasSuffix("[y/N]") && all.contains("Trust ") { return .trustPrompt }
        if let r = refusal(all) { return .failed(r) }
        return .starting
    }

    /// Known reasons `claude rc` gives for not starting, in words for the person. Read from the screen or the log.
    static func refusal(_ text: String) -> String? {
        let t = text.lowercased()
        if t.contains("disabled by your organization") || t.contains("turned off for your organization") || t.contains("remote control is turned off by the") {
            return "Remote Control is turned off for your organization. An admin of your Claude organization must turn it on."
        }
        if t.contains("not available for your account") || t.contains("not enabled for your account") {
            return "Remote Control is not available for this Claude account."
        }
        if t.contains("requires a full-scope login token") || t.contains("long-lived tokens") {
            return "Claude Code uses a long-lived token. Remote Control needs the normal sign-in."
        }
        if t.contains("requires a claude.ai subscription") || t.contains("only available with claude.ai subscriptions") || t.contains("requires claude.ai subscription auth") {
            return "Claude Code uses an API key. Remote Control needs the sign-in with your Claude account."
        }
        if t.contains("requires feature-flag evaluation") {
            return "A setting in the environment stops Remote Control from starting (for example CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC)."
        }
        if t.contains("not logged in") || t.contains("please run /login") || t.contains("run claude auth login") {
            return "Claude Code is signed out."
        }
        if let r = text.range(of: "Remote Control cannot start (") {
            let rest = text[r.lowerBound...].prefix { $0 != "\n" }
            return String(rest)
        }
        return nil
    }

    // MARK: the live check

    /// The state for Settings and the menu. Set on the main thread.
    enum State: Equatable { case unknown, connected(String), connecting, failing(String) }
    static var state: State = .unknown
    private static var lastLogged = ""
    private static var notConnectedSince: Date?
    private static var deadChecks = 0
    private static var restarts = 0
    private static var backoffUntil = Date.distantPast
    private static let busy = DispatchQueue(label: "kit.server-health")
    /// Set once the Kit has moved a server that never connected to ~/src, or the person picked a folder.
    static let movedKey = "serverMovedToSrc"

    static func start() {
        Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { _ in check() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) { check() }
    }

    static func check() {
        busy.async { run() }
    }

    private static func set(_ s: State) { DispatchQueue.main.async { state = s } }

    /// One line in the log for each change, under "server".
    private static func log(_ s: String) {
        guard s != lastLogged else { return }
        lastLogged = s
        logLine("server", s)
    }

    private static func run() {
        guard Server.installed, ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] == nil else {
            set(.unknown); notConnectedSince = nil; deadChecks = 0; return
        }
        let folder = Server.folder ?? ""
        let home = FileManager.default.homeDirectoryForCurrentUser
        let shown = folder.replacingOccurrences(of: home.path, with: "~")
        let text = screenText()
        // Once: a server in another folder that isn't connected moves to ~/src (servers set up before the Kit used
        // ~/src everywhere often waited on a question there). A connected server, or a folder picked in Settings, stays.
        let d = UserDefaults.standard
        if !d.bool(forKey: movedKey) {
            let src = home.appendingPathComponent("src").path
            let connected: Bool = { if let t = text, case .connected = read(t) { return true }; return false }()
            if folder != src && !connected {
                d.set(true, forKey: movedKey)
                d.set(shown, forKey: "serverMovedFrom")
                log("moved to ~/src from \(shown)")
                Server.start(folder: Server.srcFolder(home: home), quiet: true)
                return
            }
            if connected || folder == src { d.set(true, forKey: movedKey) }
        }
        guard let text else {
            // No screen: the server isn't running right now (it stopped, or launchd is starting it again).
            deadChecks += 1
            let why = refusal(tail(Server.logFile)) ?? "it stops soon after it starts"
            if deadChecks >= 3 { fail(why) } else { set(.connecting) }
            if deadChecks >= 3 && Date() > backoffUntil && !Server.loaded { restart("it was not running") }
            return
        }
        deadChecks = 0
        switch read(text) {
        case .connected(let found):
            let name = found.isEmpty ? (folder as NSString).lastPathComponent : found
            notConnectedSince = nil; restarts = 0
            if state != .connected(name) {
                log("connected: in the Claude app, Remote Control > \(name), sessions start in \(shown)")
                tellOnce(folder: folder, name: name, shown: shown)
            }
            set(.connected(name))
        case .trustPrompt:
            answer("y", "answered yes: trust \(shown) for sessions from the Claude app")
        case .enablePrompt:
            answer("y", "answered yes: enable Remote Control")
        case .failed(let why):
            fail(why)
        case .starting:
            let since = notConnectedSince ?? Date()
            notConnectedSince = since
            set(.connecting)
            if Date().timeIntervalSince(since) > 180 && Date() > backoffUntil {
                let shownLast = text.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.last { !$0.isEmpty } ?? ""
                restart("not connected after 3 minutes" + (shownLast.isEmpty ? "" : "; it showed: " + shownLast.prefix(80)))
            }
        }
    }

    private static func fail(_ why: String) {
        set(.failing(why))
        log("not connected: \(why)")
        // Signed out: start the sign-in so the person only finishes it in the browser.
        if why.hasPrefix("Claude Code is signed out") { Server.Fix.signIn() }
    }

    static func answer(_ key: String, _ what: String) {
        set(.connecting)
        Updater.run("/usr/bin/screen", ["-S", Server.screenName, "-p", "0", "-X", "stuff", key + "\r"])
        log(what)
        notConnectedSince = Date()
    }

    /// Starts it again, waiting longer each time (1, 2, 4 … up to 60 minutes) so a server that can't connect isn't
    /// started over and over. A newer Kit's way of starting it (with its screen saved to the log) comes with it.
    private static func restart(_ why: String) {
        restarts += 1
        backoffUntil = Date().addingTimeInterval(min(3600, 60 * pow(2, Double(restarts - 1))))
        notConnectedSince = nil
        log("started again: \(why)")
        guard let f = Server.folder else { return }
        _ = Server.start(folder: f, quiet: true)
    }

    /// The first time the server connects in a folder: one notice that says where to find it.
    private static func tellOnce(folder: String, name: String, shown: String) {
        let d = UserDefaults.standard
        guard d.string(forKey: "serverToldFolder") != folder else { return }
        d.set(folder, forKey: "serverToldFolder")
        let moved = d.string(forKey: "serverMovedFrom").map { " The server moved there from \($0), where it could not connect." } ?? ""
        d.removeObject(forKey: "serverMovedFrom")
        Updater.post("server-on", "Sessions from the Claude app now run on this Mac",
                     "In the Claude app, open Code and pick Remote Control > \(name). Sessions start in \(shown).\(moved) To change the folder, open Settings.")
    }

    /// The server's screen as text, or nil when no server screen runs.
    static func screenText() -> String? {
        let fm = FileManager.default
        let f = supportDir.appendingPathComponent(".server-screen.txt")
        try? fm.removeItem(at: f)
        let r = Updater.run("/usr/bin/screen", ["-S", Server.screenName, "-p", "0", "-X", "hardcopy", f.path])
        guard r.0 == 0 else { return nil }
        for _ in 0..<15 {
            if let d = try? Data(contentsOf: f), !d.isEmpty {
                try? fm.removeItem(at: f)
                return String(decoding: d, as: UTF8.self)
            }
            usleep(200_000)
        }
        return nil
    }

    /// The end of a log, for the reason a server stopped.
    static func tail(_ url: URL, bytes: Int = 8000) -> String {
        guard let h = try? FileHandle(forReadingFrom: url) else { return "" }
        defer { try? h.close() }
        let end = (try? h.seekToEnd()) ?? 0
        try? h.seek(toOffset: end > UInt64(bytes) ? end - UInt64(bytes) : 0)
        return String(decoding: h.readDataToEndOfFile(), as: UTF8.self)
    }

    /// Plain words for Settings.
    static var settingsText: (String, Bool)? {
        switch state {
        case .unknown: return nil
        case .connected(let name):
            let f = (Server.folder ?? "").replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~")
            return ("Connected. In the Claude app, pick Remote Control > \(name). Sessions start in \(f).", false)
        case .connecting: return ("Connecting. The Kit answers the server's questions and starts it again if needed.", false)
        case .failing(let why): return ("Not connected: " + why, true)
        }
    }
}
