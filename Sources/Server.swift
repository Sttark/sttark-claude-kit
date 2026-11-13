import AppKit

/// "Start sessions from the Claude app": a `claude rc` (Remote Control) server that macOS keeps running.
/// Sessions started in the Claude app (phone, desktop or claude.ai, under Code) run on this Mac, in the
/// chosen folder. The server lives in a LaunchAgent, so it starts at every login and restarts if it stops.
enum Server {
    static let label = "com.sttark.claude-rc"
    static var plist: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }
    static var domain: String { "gui/\(getuid())" }
    /// The name of the screen the server runs in; the Kit reads it to see what the server shows.
    static let screenName = ProcessInfo.processInfo.environment["STTARK_SERVER_SCREEN"] ?? "claude-rc"
    /// Where the server's screen goes, so a reason it stops can be read later.
    static var logFile: URL { FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/claude-rc.log") }

    /// Ours: the LaunchAgent this app wrote.
    static var installed: Bool { FileManager.default.fileExists(atPath: plist.path) }

    /// The folder our server starts sessions in.
    static var folder: String? {
        guard let d = NSDictionary(contentsOf: plist), let args = d["ProgramArguments"] as? [String],
              let cmd = args.last, let r = cmd.range(of: "cd '", options: .backwards), let end = cmd[r.upperBound...].firstIndex(of: "'") else { return nil }
        return String(cmd[r.upperBound..<end])
    }

    /// A Remote Control server this app didn't set up (started by hand or by another LaunchAgent).
    /// Counts a server macOS is set to start even while it's crashing and has no process at that moment:
    /// any enabled LaunchAgent, other than ours, that runs `claude rc` or `claude remote-control`.
    static var otherRunning: Bool {
        guard !installed, ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] == nil else { return false }
        if Updater.run("/usr/bin/pgrep", ["-f", "claude (rc|remote-control)( |$)"]).0 == 0 { return true }
        let disabled = Updater.run("/bin/launchctl", ["print-disabled", domain]).1
        let fm = FileManager.default
        for dir in [fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents"), URL(fileURLWithPath: "/Library/LaunchAgents")] {
            for name in (try? fm.contentsOfDirectory(atPath: dir.path)) ?? [] where name.hasSuffix(".plist") {
                guard let d = NSDictionary(contentsOf: dir.appendingPathComponent(name)),
                      let l = d["Label"] as? String, l != label else { continue }
                let args = (d["ProgramArguments"] as? [String] ?? []).joined(separator: " ")
                guard args.range(of: #"claude['"]? (rc|remote-control)( |'|"|$)"#, options: .regularExpression) != nil else { continue }
                if disabled.contains("\"\(l)\" => disabled") || disabled.contains("\"\(l)\" => true") { continue }
                return true
            }
        }
        return false
    }

    /// Loaded in launchd (it may be between restarts).
    static var loaded: Bool { Updater.run("/bin/launchctl", ["print", "\(domain)/\(label)"]).0 == 0 }

    /// Always started in bypass. On its own that changes nothing: the Claude app switches every session it
    /// starts on a server back to asking. "Bypass permissions for server sessions" is what actually turns it on.
    /// The screen's output goes to ~/Library/Logs/claude-rc.log, so a reason it stops can be read; ServerHealth
    /// reads the live screen and answers its questions.
    @discardableResult
    static func start(folder: String, quiet: Bool = false) -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        // the fixed copy, when there is one: macOS keeps Accessibility for a program that stays in one place
        let stable = home + "/.local/share/claude/stable/claude"
        let claude = FileManager.default.isExecutableFile(atPath: stable) ? stable : home + "/.local/bin/claude"
        let mode = " --permission-mode bypassPermissions"
        // screen saves what the server shows to the log (screen 4.0 on macOS takes the log file from a screenrc)
        let rc = supportDir.appendingPathComponent("server.screenrc")
        try? FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
        try? "logfile \(logFile.path)\nlogfile flush 5\ndeflog on\n".write(to: rc, atomically: true, encoding: .utf8)
        // screen gives the server a terminal of its own, so it runs with no Terminal window open
        let cmd = "exec /usr/bin/screen -c '\(rc.path)' -DmS \(screenName) /bin/zsh -c \"cd '\(folder)' && exec '\(claude)' rc\(mode)\""
        let d: [String: Any] = [
            "Label": label,
            "ProgramArguments": ["/bin/zsh", "-lc", cmd],
            "EnvironmentVariables": ["PATH": "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"],
            "RunAtLoad": true, "KeepAlive": true, "ThrottleInterval": 10,
            "StandardOutPath": logFile.path, "StandardErrorPath": logFile.path,
        ]
        try? FileManager.default.createDirectory(at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard (d as NSDictionary).write(to: plist, atomically: true) else { return "Couldn't save \(plist.path)." }
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        // bootout leaves the screen running; end an old one so the new one has the name to itself
        Updater.run("/usr/bin/screen", ["-S", screenName, "-X", "quit"])
        let r = Updater.run("/bin/launchctl", ["bootstrap", domain, plist.path])
        guard r.0 == 0 else { return "macOS didn't start it: \(r.1.trimmingCharacters(in: .whitespacesAndNewlines))" }
        Stable.keep(true)
        if !quiet { note("server sessions on: claude rc in \(folder)") }
        // `claude rc` asks "Trust <folder>? [y/N]" in a folder it hasn't seen (its own trust store; a key in
        // ~/.claude.json doesn't stop it), so look at its screen a few times while it starts and answer it
        for t in [4.0, 8, 15, 30] { DispatchQueue.main.asyncAfter(deadline: .now() + t) { ServerHealth.check() } }
        return nil
    }

    static func stop() {
        Stable.keep(false)
        // The server runs inside screen; unloading the LaunchAgent alone leaves it running, so end
        // the whole tree under the agent's process first.
        let out = Updater.run("/bin/launchctl", ["print", "\(domain)/\(label)"]).1
        if let line = out.split(separator: "\n").first(where: { $0.trimmingCharacters(in: .whitespaces).hasPrefix("pid = ") }),
           let pid = Int32(line.split(separator: "=").last?.trimmingCharacters(in: .whitespaces) ?? "") {
            killTree(pid)
        }
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        try? FileManager.default.removeItem(at: plist)
        note("server sessions off")
    }

    /// Every minute: start again any chat on this Mac's server that stopped (a restart, or unarchiving it) but
    /// isn't archived. The hook does the work and does nothing when no server runs; see keep() in effort-hook.py.
    static func keepChats() {
        DispatchQueue.global().async {
            Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path, "--keep"])
        }
    }

    static func killTree(_ pid: Int32) {
        let kids = Updater.run("/usr/bin/pgrep", ["-P", String(pid)]).1.split(separator: "\n").compactMap { Int32($0) }
        kids.forEach(killTree)
        kill(pid, SIGTERM)
    }

    // MARK: On by itself

    /// A person who turned the switch off (KitDefaults' "turnedOff" record, id "server"): the Kit never starts the
    /// server by itself again. A Mac with the switch off and no record counts as never chosen, so it gets it once.
    static var turnedOff: Bool { KitDefaults.turnedOff("server") }

    enum AutoStep: Equatable { case skip(String), start(String), ask }

    /// What autoStart() does, from plain facts, so tools/server-auto-test.swift can test it with made-up ones.
    /// `folder` runs only when everything else allows a start.
    static func decide(installed: Bool, elsewhere: Bool, turnedOff: Bool, claudeFound: Bool, signedIn: Bool,
                       folder: () -> String?) -> AutoStep {
        if installed { return .skip("already on") }
        if elsewhere { return .skip("a server set up another way runs") }
        if turnedOff { return .skip("turned off in Settings") }
        if !claudeFound { return .skip("Claude Code isn't installed") }
        // Remote Control needs the normal sign-in; it refuses a long-lived token from `claude setup-token`
        if !signedIn { return .skip("Claude Code isn't signed in") }
        guard let f = folder() else { return .ask }
        return .start(f)
    }

    /// The folder sessions start in when the Kit sets the server up: ~/src on every Mac, made when it is missing
    /// (an empty folder is fine). A folder the person picks in Settings stays.
    static func srcFolder(home: URL) -> String {
        let src = home.appendingPathComponent("src")
        try? FileManager.default.createDirectory(at: src, withIntermediateDirectories: true)
        return src.path
    }

    /// Why the last check didn't start it, for Settings.
    static var lastSkip = ""

    /// At launch and every hour: sets the server up for a person who never turned it off, so sessions they start from
    /// the Claude app run on this Mac without finding the switch. Tells them once, with a notice.
    static func autoStart() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let step = decide(installed: installed, elsewhere: otherRunning, turnedOff: turnedOff, claudeFound: Setup.claudeFound,
                          signedIn: Login.read()?.signedIn == true, folder: { srcFolder(home: home) })
        switch step {
        case .skip(let why):
            if why != lastSkip && why != "already on" { logLine("server", "not started: \(why)") }
            lastSkip = why
            if why == "Claude Code isn't signed in" { Fix.signIn() }
        case .ask:
            break   // the folder is always ~/src, so there is always one
        case .start(let folder):
            if ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] != nil { logLine("server", "would start in \(folder)"); return }
            if let err = start(folder: folder, quiet: true) { logLine("server", "not started: couldn't start: \(err)"); return }
            let shown = folder.replacingOccurrences(of: home.path, with: "~")
            // the notice comes when it connects (ServerHealth), not now: started is not connected
            logLine("server", "started in \(shown)")
        }
    }

    /// Turning it on: pick the folder, start.
    static func setUp() {
        NSApp.activate(ignoringOtherApps: true)
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.canCreateDirectories = true
        p.prompt = "Use this folder"
        p.message = "Sessions you start from the Claude app, on your phone or any computer, will start in this folder. A folder that holds all your projects works well."
        let src = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("src")
        p.directoryURL = FileManager.default.fileExists(atPath: src.path) ? src : FileManager.default.homeDirectoryForCurrentUser
        guard p.runModal() == .OK, let folder = p.url?.path else { return }
        UserDefaults.standard.set(true, forKey: ServerHealth.movedKey)   // the person's own pick: never moved to ~/src

        let a = NSAlert()
        a.messageText = "Start sessions from the Claude app"
        let shown = folder.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~")
        a.informativeText = "Sessions will run on this Mac, in \(shown). The Mac has to be on and awake for them to run.\n\nIn the Claude app, open Code, pick this Mac, and type."
        a.addButton(withTitle: "Start")
        a.addButton(withTitle: "Cancel")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        if let err = start(folder: folder) {
            let e = NSAlert()
            e.messageText = "Couldn't start it"
            e.informativeText = err
            e.runModal()
        }
    }

    /// Fixes the Kit makes by itself, so no one has to press a button.
    enum Fix {
        /// Signed out: starts Claude Code's own sign-in, which opens the sign-in page in the browser by itself. The
        /// person only approves it there. At most once every 6 hours. When the login appears, the server starts
        /// (or starts again) at once.
        static func signIn() {
            guard Thread.isMainThread else { DispatchQueue.main.async { signIn() }; return }
            guard ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] == nil else { return }
            let d = UserDefaults.standard
            let last = d.double(forKey: "serverSignInAt")
            guard Date().timeIntervalSince1970 - last > 6 * 3600, Setup.claudeFound else { return }
            d.set(Date().timeIntervalSince1970, forKey: "serverSignInAt")
            let claude = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/claude").path
            // a screen gives the sign-in the terminal it needs; it opens the browser itself and ends when done
            Updater.run("/usr/bin/screen", ["-dmS", "kit-sign-in", claude, "auth", "login"])
            logLine("server", "sign-in started: the Claude sign-in page opens in the browser")
            Updater.post("server-signin", "Approve the Claude sign-in in your browser",
                         "Claude Code is signed out, so sessions from the Claude app can't run. The Kit opened the sign-in page. The server starts when you approve it.")
            var n = 0
            Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { t in
                n += 1
                if Login.read()?.signedIn == true {
                    t.invalidate()
                    logLine("server", "signed in: starting the server")
                    if installed, let f = folder { start(folder: f, quiet: true) } else { autoStart() }
                } else if n > 180 { t.invalidate() }   // 15 minutes
            }
        }
    }
}
