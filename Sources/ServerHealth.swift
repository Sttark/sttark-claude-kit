import Foundation

/// Checks that the server the Kit set up is really connected, and fixes what stops it, with no one pressing a button.
///
/// `claude rc` runs inside `screen`, so a question it asks waits there with no one to see it. In a folder Claude Code
/// hasn't been trusted in, it asks "Trust <folder>? [y/N]" before it connects; on a first run it can also ask
/// "Enable Remote Control? (y/n)"; in a git repo a Claude Code without --spawn asks which spawn mode to use. A
/// LaunchAgent that is installed is not a server that is connected. Every 30 seconds the Kit:
/// - ends copies of the server that earlier starts left running (a copy that waits on a question outlives its screen,
///   and one that runs keeps the folder, so the next server can't register it);
/// - reads the server's screen, and answers those three questions (yes, yes, same-dir: the person chose this folder,
///   or the Kit chose it for them);
/// - notes when it is connected (the screen shows "Connected" and the environment), and tells the person once;
/// - sees a known refusal (Remote Control off for the organization, signed out, a long-lived token), or a question
///   it can't answer, and says so in Settings and on the Events page;
/// - starts the server again when it hasn't connected after 3 minutes, with a back-off; and when launchd starts it
///   again and again because it stops soon after each start, unloads it, so it isn't started every 10 seconds, and
///   starts it later with the same back-off.
enum ServerHealth {
    enum Screen: Equatable {
        case connected(String)      // the folder's name, as the Claude app lists it under Remote Control
        case trustPrompt
        case enablePrompt
        case spawnPrompt            // which spawn mode: same-dir (1) or worktree (2)
        case question(String)       // a question the Kit doesn't know, as the screen shows it
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
        if last.hasPrefix("Choose [1/2]") && all.lowercased().contains("spawn mode") { return .spawnPrompt }
        if let r = refusal(all) { return .failed(r) }
        if isQuestion(last) { return .question(String(last.prefix(100))) }
        return .starting
    }

    /// A line that waits for an answer: it ends with "?", or offers a choice such as [y/N], (y/n) or [1/2].
    static func isQuestion(_ line: String) -> Bool {
        line.range(of: #"\?\s*$|\[[A-Za-z0-9]{1,3}(/[A-Za-z0-9]{1,3})+\]|\([A-Za-z0-9]{1,3}(/[A-Za-z0-9]{1,3})+\)"#,
                   options: .regularExpression) != nil
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
        if t.contains("already served by another claude code") {
            return "Another Claude Code on this Mac serves this folder. The Kit ends its own old copies; stop a server you started there yourself."
        }
        if let r = text.range(of: "Unknown argument:", options: .caseInsensitive) {
            return "This Claude Code doesn't know an option the Kit gives it (" + text[r.lowerBound...].prefix { $0 != "\n" } + ")."
        }
        if let r = text.range(of: "Remote Control cannot start (") {
            let rest = text[r.lowerBound...].prefix { $0 != "\n" }
            return String(rest)
        }
        return nil
    }

    /// Text from the screen or its log without the terminal's escape codes (colors, links).
    static func plain(_ s: String) -> String {
        s.replacingOccurrences(of: #"\x{1B}\][^\x{07}\x{1B}]*(\x{07}|\x{1B}\\)"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"\x{1B}\[[0-9;?]*[ -/]*[@-~]"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"\x{1B}[()][0-9A-B]"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: "\r", with: "\n")
    }

    /// The last line with text in it.
    static func lastLine(_ s: String) -> String? {
        plain(s).split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.last { !$0.isEmpty }.map { String($0.prefix(100)) }
    }

    // MARK: the live check

    /// The state for Settings and the menu. Set on the main thread.
    enum State: Equatable { case unknown, connected(String), connecting, failing(String) }
    static var state: State = .unknown
    /// Checked and not connected (starting, at a question, or failing), read on the main thread (Server.keepChats).
    static var down: Bool {
        switch state { case .unknown, .connected: return false; default: return true }
    }

    /// Not connected this long, it starts again.
    static var stuckAfter: TimeInterval = 180
    /// The wait before the first start again, which doubles with each one up to `backoffMax`.
    static var backoffBase: TimeInterval = 60
    static var backoffMax: TimeInterval = 3600
    /// A copy younger than this may be one launchd just started, so it is never taken for one left over.
    static var staleAge = 30
    /// launchd started it `loopRuns` times in `loopWindow` seconds without a connection: it stops soon after each
    /// start, and launchd would start it every 10 seconds without end.
    static var loopRuns = 3
    static var loopWindow: TimeInterval = 180

    private static var lastLogged = ""
    private static var notConnectedSince: Date?
    private static var deadChecks = 0
    private static var restarts = 0
    private static var backoffUntil = Date.distantPast
    private static var runsSeen: [(at: Date, runs: Int)] = []
    private static var stoppedAgain = false   // unloaded because it stopped again and again: it starts later
    private static var refreshed = false
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

    /// One check, done before it returns (tools/server-health-test.swift).
    static func checkNow() {
        busy.sync { run() }
    }

    private static func set(_ s: State) {
        DispatchQueue.main.async {
            guard state != s else { return }
            state = s
            writeHealth()
        }
    }

    /// health.json in the Kit's folder: the server's state in one line, for a report that collects each Mac's Kit
    /// health. Nothing sends it yet.
    static func writeHealth() {
        let text = settingsText?.0 ?? ""
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? ""
        let j: [String: Any] = ["version": v, "server": text, "at": ISO8601DateFormatter().string(from: Date())]
        if let d = try? JSONSerialization.data(withJSONObject: j, options: [.sortedKeys]) {
            try? d.write(to: supportDir.appendingPathComponent("health.json"), options: .atomic)
        }
    }

    /// One line in the log for each change, under "server".
    private static func log(_ s: String) {
        guard s != lastLogged else { return }
        lastLogged = s
        logLine("server", s)
    }

    private static func run() {
        guard Server.installed, ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] == nil else {
            set(.unknown); notConnectedSince = nil; deadChecks = 0; runsSeen = []; return
        }
        let folder = Server.folder ?? ""
        let home = FileManager.default.homeDirectoryForCurrentUser
        let shown = folder.replacingOccurrences(of: home.path, with: "~")
        // Once a launch: a LaunchAgent an older Kit wrote starts the server without --spawn. The new one takes effect at
        // the server's next start; a server that waits on the spawn question meanwhile gets its answer below.
        if !refreshed {
            refreshed = true
            if Server.refresh() { log("start command updated: it gives --spawn same-dir when Claude Code has it, from the next start") }
        }
        // The processes first, then launchd's job: a copy launchd starts in between is not in the list, so it is never
        // taken for one left over. Each copy an earlier start left keeps the folder ("already served by another Claude
        // Code on this device"), so the server can't connect, and they pile up: end them.
        let procs = Server.processes()
        let job = Server.job()
        let left = Server.endCopies(keeping: job.pid, olderThan: staleAge, procs: procs)
        if left > 0 { logLine("server", "ended \(left) old \(left == 1 ? "copy" : "copies") of the server that earlier starts left running") }
        // The screen of the server launchd runs now, by its full id: `screen -S claude-rc` acts on none when two have the name.
        // launchd's process is the screen itself (zsh runs it with exec), the id to use when `screen -ls` misses it.
        let mine = Set(job.pid.map { Server.tree($0, procs) } ?? [])
        let screen = mine.isEmpty ? nil : Server.screens().first { mine.contains($0.pid) }?.id ?? job.pid.map { "\($0).\(Server.screenName)" }
        let text = screen.flatMap { screenText($0) }
        // Once: a server in another folder that isn't connected moves to ~/src (servers set up before the Kit used
        // ~/src everywhere often waited on a question there). A connected server, or a folder picked in Settings, stays.
        let d = UserDefaults.standard
        if !d.bool(forKey: movedKey) && !Server.test {
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
        // launchd starts the server again 10 seconds after it stops. One that stops soon after each start would be
        // started every 10 seconds without end: unload it, and start it again later, waiting longer each time.
        if let runs = job.runs {
            if let f = runsSeen.first, runs < f.runs { runsSeen = [] }   // loaded again since
            let before = runsSeen.last?.runs
            runsSeen.append((Date(), runs))
            runsSeen.removeAll { Date().timeIntervalSince($0.at) > loopWindow }
            if let f = runsSeen.first, runs - f.runs >= loopRuns, !isConnected(text) {
                let tail = self.tail(Server.logFile)
                let why = refusal(plain(tail)) ?? lastLine(tail).map { "it showed: " + $0 } ?? ""
                runsSeen = []
                Server.unload()
                backoffUntil = Date().addingTimeInterval(delay())   // the start again counts the step up
                stoppedAgain = true
                fail("it stopped \(runs - f.runs) times soon after it started" + (why.isEmpty ? "" : "; " + why)
                     + ". The Kit starts it again in \(wait(until: backoffUntil)).")
                return
            }
            if let before, runs > before, !isConnected(text) { log("stopped, and macOS started it again") }
        } else { runsSeen = [] }
        guard let text else {
            // No screen: the server isn't running right now (it stopped, or launchd is starting it again).
            deadChecks += 1
            let why = refusal(plain(tail(Server.logFile))) ?? "it stops soon after it starts"
            if deadChecks >= 3 { if !stoppedAgain { fail(why) } } else if !stoppedAgain { set(.connecting) }
            if (deadChecks >= 3 || stoppedAgain) && Date() > backoffUntil && !job.loaded {
                restart(stoppedAgain ? "it had stopped again and again soon after it started" : "it was not running")
            }
            return
        }
        deadChecks = 0
        stoppedAgain = false
        switch read(text) {
        case .connected(let found):
            let name = found.isEmpty ? (folder as NSString).lastPathComponent : found
            notConnectedSince = nil; restarts = 0; backoffUntil = .distantPast
            if state != .connected(name) {
                log("connected: in the Claude app, Remote Control > \(name), sessions start in \(shown)")
                tellOnce(folder: folder, name: name, shown: shown)
            }
            set(.connected(name))
        case .trustPrompt:
            answer(screen!, "y", "answered yes: trust \(shown) for sessions from the Claude app")
        case .enablePrompt:
            answer(screen!, "y", "answered yes: enable Remote Control")
        case .spawnPrompt:
            // 1 is same-dir, the mode the Kit gives with --spawn; Claude Code saves it for the folder and doesn't ask again
            answer(screen!, "1", "answered same-dir: the spawn mode, so every session starts in \(shown)")
        case .question(let q):
            notYet(text, failing: "it waits on a question the Kit can't answer: \(q)")
        case .failed(let why):
            notYet(text, failing: why)
        case .starting:
            notYet(text, failing: nil)
        }
    }

    private static func isConnected(_ text: String?) -> Bool {
        if let text, case .connected = read(text) { return true }
        return false
    }

    /// Not connected yet: at a question it can't answer, with a reason it gave, or with nothing to act on. After
    /// `stuckAfter`, it starts again (a newer Claude Code, a setting fixed meanwhile or a sign-in may let it connect).
    private static func notYet(_ text: String, failing why: String?) {
        let since = notConnectedSince ?? Date()
        notConnectedSince = since
        if let why { fail(why) } else { set(.connecting) }
        guard Date().timeIntervalSince(since) > stuckAfter && Date() > backoffUntil else { return }
        let last = text.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.last { !$0.isEmpty } ?? ""
        let after = stuckAfter >= 120 ? "\(Int(stuckAfter / 60)) minutes" : "\(Int(stuckAfter)) seconds"
        restart("not connected after \(after)" + (last.isEmpty ? "" : "; it showed: " + last.prefix(80)))
    }

    private static func fail(_ why: String) {
        set(.failing(why))
        log("not connected: \(why)")
        // Signed out: start the sign-in so the person only finishes it in the browser.
        if why.hasPrefix("Claude Code is signed out") { Server.Fix.signIn() }
    }

    static func answer(_ screen: String, _ key: String, _ what: String) {
        set(.connecting)
        Updater.run("/usr/bin/screen", ["-S", screen, "-p", "0", "-X", "stuff", key + "\r"])
        log(what)
        notConnectedSince = Date()
    }

    /// The wait before the next start again, longer each time: 1, 2, 4 … up to 60 minutes, so a server that can't
    /// connect isn't started over and over.
    private static func delay() -> TimeInterval { min(backoffMax, backoffBase * pow(2, Double(restarts))) }

    /// Starts it again, after the back-off. Server.start ends every copy the Kit started before the new one starts,
    /// and a newer Kit's way of starting it comes with it.
    private static func restart(_ why: String) {
        backoffUntil = Date().addingTimeInterval(delay())
        restarts += 1
        notConnectedSince = nil; stoppedAgain = false; runsSeen = []
        log("started again: \(why)")
        guard let f = Server.folder else { return }
        _ = Server.start(folder: f, quiet: true)
    }

    /// "4 min", "1 hr" or "30 s": how long until `date`.
    private static func wait(until date: Date) -> String {
        let s = Int(date.timeIntervalSinceNow.rounded())
        return s >= 3600 ? "\(s / 3600) hr" : s >= 60 ? "\(s / 60) min" : "\(max(s, 0)) s"
    }

    /// The first time the server connects in a folder: one notice that says where to find it.
    private static func tellOnce(folder: String, name: String, shown: String) {
        let d = UserDefaults.standard
        guard d.string(forKey: "serverToldFolder") != folder, !Server.test else { return }
        d.set(folder, forKey: "serverToldFolder")
        let moved = d.string(forKey: "serverMovedFrom").map { " The server moved there from \($0), where it could not connect." } ?? ""
        d.removeObject(forKey: "serverMovedFrom")
        Updater.post("server-on", "Sessions from the Claude app now run on this Mac",
                     "New Code sessions in the Claude app start on Remote Control > \(name), in \(shown).\(moved) They show on your phone and in the Kit.")
    }

    /// The text of the screen with this id (12345.claude-rc), or nil when it doesn't run.
    static func screenText(_ id: String) -> String? {
        let fm = FileManager.default
        let f = supportDir.appendingPathComponent(".server-screen.txt")
        try? fm.removeItem(at: f)
        let r = Updater.run("/usr/bin/screen", ["-S", id, "-p", "0", "-X", "hardcopy", f.path])
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
            return ("Connected: Remote Control > \(name). New sessions in the Claude app start here, in \(f).", false)
        case .connecting: return ("Connecting. The Kit answers the server's questions and starts it again if needed.", false)
        case .failing(let why): return ("Not connected: " + why, true)
        }
    }
}
