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

    /// Ours: the LaunchAgent this app wrote.
    static var installed: Bool { FileManager.default.fileExists(atPath: plist.path) }

    /// The folder our server starts sessions in.
    static var folder: String? {
        guard let d = NSDictionary(contentsOf: plist), let args = d["ProgramArguments"] as? [String],
              let cmd = args.last, let r = cmd.range(of: "cd '"), let end = cmd[r.upperBound...].firstIndex(of: "'") else { return nil }
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

    /// Always started in bypass. On its own that changes nothing: the Claude app switches every session it
    /// starts on a server back to asking. "Bypass permissions for server sessions" is what actually turns it on.
    static func start(folder: String) -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        // the fixed copy, when there is one: macOS keeps Accessibility for a program that stays in one place
        let stable = home + "/.local/share/claude/stable/claude"
        let claude = FileManager.default.isExecutableFile(atPath: stable) ? stable : home + "/.local/bin/claude"
        let mode = " --permission-mode bypassPermissions"
        // screen gives the server a terminal of its own, so it runs with no Terminal window open
        let cmd = "exec /usr/bin/screen -DmS claude-rc /bin/zsh -c \"cd '\(folder)' && exec '\(claude)' rc\(mode)\""
        let d: [String: Any] = [
            "Label": label,
            "ProgramArguments": ["/bin/zsh", "-lc", cmd],
            "EnvironmentVariables": ["PATH": "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"],
            "RunAtLoad": true, "KeepAlive": true, "ThrottleInterval": 10,
            "StandardOutPath": "\(home)/Library/Logs/claude-rc.log", "StandardErrorPath": "\(home)/Library/Logs/claude-rc.log",
        ]
        try? FileManager.default.createDirectory(at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard (d as NSDictionary).write(to: plist, atomically: true) else { return "Couldn't save \(plist.path)." }
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        let r = Updater.run("/bin/launchctl", ["bootstrap", domain, plist.path])
        guard r.0 == 0 else { return "macOS didn't start it: \(r.1.trimmingCharacters(in: .whitespacesAndNewlines))" }
        Stable.keep(true)
        note("server sessions on: claude rc in \(folder)")
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

    /// The folder sessions start in when the Kit sets the server up by itself: ~/src when there is one, else the
    /// folder that holds the most git repos, one or two levels under the home folder. Never the home folder, a hidden
    /// folder or ~/Library; and not Desktop, Documents or Downloads, which macOS asks permission to read.
    static func defaultFolder(home: URL) -> String? {
        let fm = FileManager.default
        func isDir(_ u: URL) -> Bool { var d: ObjCBool = false; return fm.fileExists(atPath: u.path, isDirectory: &d) && d.boolValue }
        func isRepo(_ u: URL) -> Bool { fm.fileExists(atPath: u.appendingPathComponent(".git").path) }
        func folders(_ u: URL) -> [URL] {
            ((try? fm.contentsOfDirectory(atPath: u.path)) ?? []).filter { !$0.hasPrefix(".") && $0 != "node_modules" }
                .map { u.appendingPathComponent($0) }.filter(isDir)
        }
        let src = home.appendingPathComponent("src")
        if isDir(src) { return src.path }
        let skip: Set<String> = ["Library", "Applications", "Desktop", "Documents", "Downloads", "Movies", "Music", "Pictures", "Public"]
        let top = folders(home).filter { !skip.contains($0.lastPathComponent) && !isRepo($0) }
        let candidates = top + top.flatMap { folders($0).filter { !isRepo($0) } }
        var best: (url: URL, repos: Int)? = nil
        for c in candidates {
            let n = folders(c).filter(isRepo).count
            // more repos wins; on a tie, the folder nearer the home folder
            if n > 0, best == nil || n > best!.repos || (n == best!.repos && c.pathComponents.count < best!.url.pathComponents.count) {
                best = (c, n)
            }
        }
        return best?.url.path
    }

    private static var lastSkip = ""

    /// At launch and every hour: sets the server up for a person who never turned it off, so sessions they start from
    /// the Claude app run on this Mac without finding the switch. Tells them once, with a notice.
    static func autoStart() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let step = decide(installed: installed, elsewhere: otherRunning, turnedOff: turnedOff, claudeFound: Setup.claudeFound,
                          signedIn: Login.read()?.signedIn == true, folder: { defaultFolder(home: home) })
        switch step {
        case .skip(let why):
            if why != lastSkip && why != "already on" { note("server auto: not started, \(why)") }
            lastSkip = why
        case .ask:
            let d = UserDefaults.standard
            guard !d.bool(forKey: "serverAskSent") else { return }
            d.set(true, forKey: "serverAskSent")
            note("server auto: no project folder found, asked with a notice")
            Updater.post("server-ask", "Start sessions from the Claude app",
                         "Click to pick the folder that holds your projects. Then sessions you start in the Claude app run on this Mac.")
        case .start(let folder):
            if ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] != nil { note("server auto: would start in \(folder)"); return }
            if let err = start(folder: folder) { note("server auto: couldn't start: \(err)"); return }
            let shown = folder.replacingOccurrences(of: home.path, with: "~")
            let name = (folder as NSString).lastPathComponent
            note("server auto: started in \(shown)")
            Updater.post("server-on", "Sessions from the Claude app now run on this Mac",
                         "In the Claude app, open Code and pick Remote Control > \(name). Sessions start in \(shown). Click to open Settings.")
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
}
