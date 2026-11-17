import AppKit

/// "Start sessions from the Claude app": a `claude rc` (Remote Control) server that macOS keeps running.
/// Sessions started in the Claude app (phone, desktop or claude.ai, under Code) run on this Mac, in the
/// chosen folder. The server lives in a LaunchAgent, so it starts at every login and restarts if it stops.
enum Server {
    private static let env = ProcessInfo.processInfo.environment
    /// The LaunchAgent's label. A test copy of the server (tools/server-health-test.swift) sets STTARK_SERVER_LABEL,
    /// STTARK_SERVER_PLIST, STTARK_SERVER_SCREEN, STTARK_SERVER_CLAUDE and STTARK_SERVER_LOG, so it never touches the
    /// real server, its file or its log. The app itself never sets them.
    static let label = env["STTARK_SERVER_LABEL"] ?? "com.sttark.claude-rc"
    /// A test copy: no notices, no night job, no sign-in and no move to ~/src.
    static var test: Bool { label != "com.sttark.claude-rc" }
    static var plist: URL {
        if let p = env["STTARK_SERVER_PLIST"] { return URL(fileURLWithPath: p) }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }
    static var domain: String { "gui/\(getuid())" }
    /// The name of the screen the server runs in; the Kit reads it to see what the server shows.
    static let screenName = env["STTARK_SERVER_SCREEN"] ?? "claude-rc"
    /// Where the server's screen goes, so a reason it stops can be read later.
    static var logFile: URL {
        env["STTARK_SERVER_LOG"].map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/claude-rc.log")
    }
    /// The Claude Code the server runs: the fixed copy when there is one, since macOS keeps Accessibility for a program
    /// that stays in one place (Stable), else ~/.local/bin/claude.
    static var claude: String {
        if let c = env["STTARK_SERVER_CLAUDE"] { return c }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let stable = home + "/.local/share/claude/stable/claude"
        return FileManager.default.isExecutableFile(atPath: stable) ? stable : home + "/.local/bin/claude"
    }
    /// In the server's environment, so the Kit knows its own copies of `claude rc` from a person's own (copies()).
    static let marker = "STTARK_KIT_SERVER"
    /// The Kit waits this many seconds for a copy it ends to stop, then kills it.
    static var endWait: Double = 5
    /// When the Kit looks at the server's screen after it starts it.
    static var checksAfterStart: [Double] = [4, 8, 15, 30]
    /// launchd starts the server again this many seconds after it stops.
    static var throttle = 10

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
        // a running server: only a process that IS `claude rc` (or a screen running one), not any command line that
        // mentions it (a grep, a shell, an editor)
        let ps = Updater.run("/bin/ps", ["-axww", "-o", "args="]).1
        if ps.split(separator: "\n").contains(where: { isServer(String($0)) }) { return true }
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

    /// What launchd says about the server's LaunchAgent: whether it is loaded (it may be between restarts), its
    /// process (the screen), and how many times launchd has started it since it was loaded.
    struct Job: Equatable { var loaded = false; var pid: Int32?; var runs: Int? }

    static func job() -> Job {
        let r = Updater.run("/bin/launchctl", ["print", "\(domain)/\(label)"])
        guard r.0 == 0 else { return Job() }
        return job(r.1)
    }

    /// `launchctl print`, read. Only the job's own lines, which have one tab in front; deeper ones belong to its parts.
    /// Pure, so tools/server-auto-test.swift tests it.
    static func job(_ text: String) -> Job {
        var j = Job(loaded: true)
        for line in text.split(separator: "\n") where line.hasPrefix("\t") && !line.hasPrefix("\t\t") {
            let kv = line.trimmingCharacters(in: .whitespaces).components(separatedBy: " = ")
            guard kv.count == 2 else { continue }
            if kv[0] == "pid" { j.pid = Int32(kv[1]) }
            if kv[0] == "runs" { j.runs = Int(kv[1]) }
        }
        return j
    }

    static var loaded: Bool { job().loaded }

    /// True for a process that runs a Remote Control server: `claude rc`, `claude remote-control`, the same through
    /// node or bun, or a screen that runs one. Not its help. Pure, so tools/server-auto-test.swift tests it.
    static func isServer(_ line: String) -> Bool {
        let t = line.trimmingCharacters(in: .whitespaces).split(separator: " ", omittingEmptySubsequences: true).map(String.init)
        guard let exe = t.first else { return false }
        let base = (exe as NSString).lastPathComponent
        func rc(_ i: Int) -> Bool { i < t.count && (t[i] == "rc" || t[i] == "remote-control") && !t[(i + 1)...].contains { $0 == "--help" || $0 == "-h" } }
        if base == "claude" { return rc(1) }
        if base == "node" || base == "bun", t.count > 2,
           (t[1] as NSString).lastPathComponent == "claude" || t[1].hasSuffix("/cli.js") { return rc(2) }
        if base == "screen" { return line.range(of: #"claude['"]? (rc|remote-control)( |'|"|$)"#, options: .regularExpression) != nil }
        return false
    }

    /// The LaunchAgent's command: `claude rc` in a screen (a terminal of its own, so no Terminal window is open), in
    /// the folder, always in bypass. On its own bypass changes nothing: the Claude app switches every session it starts
    /// on a server back to asking. "Bypass permissions for server sessions" is what actually turns it on.
    /// `claude rc` asks which spawn mode to use when it starts in a git repo (or with a WorktreeCreate hook), and with
    /// no one to answer it waits there and never connects. So it gets `--spawn same-dir`: every session shares the
    /// server's folder, as the Kit needs (sessions start in it, and keep() keeps up to 30 running of the 32 a server
    /// takes in this mode). An older Claude Code has no `--spawn` and stops at an option it doesn't know, so the flag
    /// goes in only when `claude remote-control --help` names it, checked at each start with the copy that runs.
    /// Pure, so tools/server-auto-test.swift tests it.
    static func command(folder: String, claude: String, screenrc: String, screen: String) -> String {
        let spawn = "\\$('\(claude)' remote-control --help 2>/dev/null | /usr/bin/grep -q -- --spawn && echo --spawn same-dir)"
        return "exec /usr/bin/screen -c '\(screenrc)' -DmS \(screen) /bin/zsh -c \"cd '\(folder)' && exec '\(claude)' rc --permission-mode bypassPermissions \(spawn)\""
    }

    /// The LaunchAgent the Kit writes for a server in `folder`. The marker in its environment reaches `claude rc`.
    static func definition(folder: String, screenrc: String) -> [String: Any] {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return [
            "Label": label,
            "ProgramArguments": ["/bin/zsh", "-lc", command(folder: folder, claude: claude, screenrc: screenrc, screen: screenName)],
            "EnvironmentVariables": ["PATH": "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                                     marker: label],
            "RunAtLoad": true, "KeepAlive": true, "ThrottleInterval": throttle,
            "StandardOutPath": logFile.path, "StandardErrorPath": logFile.path,
        ]
    }

    /// The screenrc the server's screen starts with: screen saves what the server shows to the log (screen 4.0 on
    /// macOS takes the log file from a screenrc), so a reason it stops can be read; ServerHealth reads the live screen.
    static func writeScreenrc() -> URL {
        let rc = supportDir.appendingPathComponent("server.screenrc")
        try? FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
        try? "logfile \(logFile.path)\nlogfile flush 5\ndeflog on\n".write(to: rc, atomically: true, encoding: .utf8)
        return rc
    }

    @discardableResult
    static func start(folder: String, quiet: Bool = false) -> String? {
        let d = definition(folder: folder, screenrc: writeScreenrc().path)
        try? FileManager.default.createDirectory(at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard (d as NSDictionary).write(to: plist, atomically: true) else { return "Couldn't save \(plist.path)." }
        // launchd ends the screen when it unloads the LaunchAgent, but a `claude rc` that waits on a question outlives
        // its screen: each start left one more copy running, and a copy that runs keeps the folder, so the next one
        // can't register it. First copies an earlier start left, then the one that ran until now, before the new one.
        let left = endCopies(keeping: job().pid)
        if left > 0 { logLine("server", "ended \(left) old \(left == 1 ? "copy" : "copies") of the server that earlier starts left running") }
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        endCopies()
        let r = Updater.run("/bin/launchctl", ["bootstrap", domain, plist.path])
        guard r.0 == 0 else { return "macOS didn't start it: \(r.1.trimmingCharacters(in: .whitespacesAndNewlines))" }
        if !test { Stable.keep(true) }
        if !quiet { note("server sessions on: claude rc in \(folder)") }
        // `claude rc` asks "Trust <folder>? [y/N]" in a folder it hasn't seen (its own trust store; a key in
        // ~/.claude.json doesn't stop it), so look at its screen a few times while it starts and answer it
        for t in checksAfterStart { DispatchQueue.main.asyncAfter(deadline: .now() + t) { ServerHealth.check() } }
        return nil
    }

    /// The LaunchAgent's file is not what this Kit writes (an older Kit wrote it, without --spawn or the marker, or the
    /// fixed copy came since): write it again for the same folder. launchd keeps the job it loaded, so a server that
    /// runs goes on as it is and starts with the new file the next time (a restart, the night job, the next login).
    @discardableResult
    static func refresh() -> Bool {
        guard let folder, let had = NSDictionary(contentsOf: plist) else { return false }
        let d = definition(folder: folder, screenrc: writeScreenrc().path)
        guard !had.isEqual(to: d) else { return false }
        return (d as NSDictionary).write(to: plist, atomically: true)
    }

    /// Unloads the LaunchAgent but keeps its file, and ends the server: launchd starts nothing until the Kit loads it.
    static func unload() {
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        endCopies()
    }

    static func stop() {
        if !test { Stable.keep(false) }
        // The server runs inside screen, and can outlive it; unloading the LaunchAgent alone leaves it running.
        unload()
        try? FileManager.default.removeItem(at: plist)
        note("server sessions off")
    }

    /// Every 15 seconds: start again any chat on this Mac's server that stopped (a restart, or unarchiving it) but
    /// isn't archived. The hook does the work and does nothing when no server runs; see keep() in effort-hook.py.
    /// While the Kit's own server isn't connected (it starts, waits on a question, or fails), its chats wait for it:
    /// a wake can't reach it, and starting each of them on its own made a second copy of each once it came back.
    static func keepChats() {
        let down = installed && ServerHealth.down
        DispatchQueue.global().async {
            Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path, "--keep"] + (down ? ["--server-down"] : []))
        }
    }

    /// Before the Mac shuts down, restarts or logs out: end each chat the Kit runs on its own (screens kit-*) the
    /// way that never archives it. The system ends what is left with SIGTERM, and Claude Code archives a Remote
    /// Control chat when it ends that way; only the person archives a session. keep() starts them again after the
    /// restart, on the same link. See halt_copies() in effort-hook.py.
    static func haltChatsAtPowerOff() {
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.willPowerOffNotification, object: nil,
                                                          queue: .main) { _ in
            Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path, "--halt-copies"])
        }
    }

    // MARK: the Kit's own copies of the server

    struct Proc: Equatable { let pid: Int32; let ppid: Int32; let uid: UInt32; let age: Int; let command: String }

    /// Every process, from one `ps`: each with its parent, its owner, its age in seconds and its command line. All of
    /// them, not only this user's: screen starts what runs in it through `login`, which runs as root, so the way from
    /// the server's screen down to its `claude rc` goes through a process of root's.
    static func processes() -> [Proc] {
        Updater.run("/bin/ps", ["-axww", "-o", "pid=,ppid=,uid=,etime=,command="]).1.split(separator: "\n").compactMap { line in
            let f = line.split(separator: " ", maxSplits: 4, omittingEmptySubsequences: true)
            guard f.count == 5, let pid = Int32(f[0]), let ppid = Int32(f[1]), let uid = UInt32(f[2]) else { return nil }
            return Proc(pid: pid, ppid: ppid, uid: uid, age: seconds(String(f[3])), command: String(f[4]))
        }
    }

    /// ps's elapsed time, [[dd-]hh:]mm:ss, in seconds.
    static func seconds(_ etime: String) -> Int {
        var days = 0, rest = Substring(etime)
        if let dash = rest.firstIndex(of: "-") { days = Int(rest[..<dash]) ?? 0; rest = rest[rest.index(after: dash)...] }
        return days * 86400 + rest.split(separator: ":").reduce(0) { $0 * 60 + (Int($1) ?? 0) }
    }

    /// A process and everything under it.
    static func tree(_ pid: Int32, _ procs: [Proc]) -> [Int32] {
        var out = [pid], i = 0
        while i < out.count { let p = out[i]; out += procs.filter { $0.ppid == p && !out.contains($0.pid) }.map(\.pid); i += 1 }
        return out
    }

    /// Whether a process's environment, as `ps -E` prints it after its command line, marks it as the Kit's server: the
    /// marker the LaunchAgent sets, or the STY that screen gives what runs in the server's screen (<pid>.claude-rc),
    /// which copies an older Kit started carry. A `claude rc` a person starts in a terminal has neither.
    /// Pure, so tools/server-auto-test.swift tests it.
    static func isCopy(environment line: String) -> Bool {
        let name = NSRegularExpression.escapedPattern(for: screenName), tag = NSRegularExpression.escapedPattern(for: label)
        return line.range(of: " (\(marker)=\(tag)|STY=[0-9]+\\.\(name))( |$)", options: .regularExpression) != nil
    }

    /// The Kit's own copies of the server among `procs`: `claude rc` processes with the Kit's mark (isCopy). The
    /// screens are screens(); a person's own `claude rc` is never one of them.
    static func copies(_ procs: [Proc]) -> [Proc] {
        let me = getuid()
        let servers = procs.filter { $0.uid == me && isServer($0.command)
            && ($0.command.split(separator: " ").first.map { (String($0) as NSString).lastPathComponent.lowercased() } ?? "") != "screen" }
        guard !servers.isEmpty else { return [] }
        let out = Updater.run("/bin/ps", ["-wwE", "-o", "pid=,command=", "-p", servers.map { String($0.pid) }.joined(separator: ",")]).1
        let marked = Set(out.split(separator: "\n").compactMap { line -> Int32? in
            isCopy(environment: String(line)) ? Int32(line.split(separator: " ").first ?? "") : nil
        })
        return servers.filter { marked.contains($0.pid) }
    }

    /// The screens named for the server, as `screen -ls` lists them ("12345.claude-rc"), with their process.
    static func screens() -> [(id: String, pid: Int32)] {
        Updater.run("/usr/bin/screen", ["-ls"]).1.split(separator: "\n").compactMap { line in
            guard let id = line.split(whereSeparator: { $0 == " " || $0 == "\t" }).first, let dot = id.firstIndex(of: "."),
                  id[id.index(after: dot)...] == screenName, let pid = Int32(id[..<dot]) else { return nil }
            return (String(id), pid)
        }
    }

    /// Ends the Kit's own copies of the server and the screens named for it, except `keeping` and everything under it
    /// (the copy launchd runs now), and only ones at least `olderThan` seconds old, so a copy launchd started a moment
    /// ago is never taken for one left over. A screen is quit by its full id: `screen -S claude-rc` acts on none when
    /// two have the name. Each copy, and everything under it (its sessions), gets SIGTERM, then SIGKILL when it still
    /// runs after `endWait` seconds: a `claude rc` that waits on a question ignores the hang-up its screen sends as it
    /// closes. Pass `procs` read before launchd's job, so a copy launchd starts in between is not in it.
    /// Returns how many copies it ended.
    @discardableResult
    static func endCopies(keeping: Int32? = nil, olderThan: Int = 0, procs given: [Proc]? = nil) -> Int {
        let procs = given ?? processes()
        let keep = Set(keeping.map { tree($0, procs) } ?? [])
        let age = Dictionary(procs.map { ($0.pid, $0.age) }, uniquingKeysWith: { a, _ in a })
        for s in screens() where !keep.contains(s.pid) && (age[s.pid] ?? 0) >= olderThan {
            Updater.run("/usr/bin/screen", ["-S", s.id, "-X", "quit"])
        }
        let stale = copies(procs).filter { !keep.contains($0.pid) && $0.age >= olderThan }
        guard !stale.isEmpty else { return 0 }
        let me = getuid()
        let all = Set(stale.flatMap { tree($0.pid, procs) }).filter { pid in procs.first { $0.pid == pid }?.uid == me }
        all.forEach { kill($0, SIGTERM) }
        let end = Date().addingTimeInterval(endWait)
        while Date() < end && !living(all).isEmpty { usleep(250_000) }
        living(all).forEach { kill($0, SIGKILL) }
        return stale.count
    }

    /// Those of `pids` that still run: not gone, and not a zombie that waits for its parent to read how it ended.
    static func living(_ pids: Set<Int32>) -> Set<Int32> {
        guard !pids.isEmpty else { return [] }
        let out = Updater.run("/bin/ps", ["-o", "pid=,stat=", "-p", pids.map(String.init).joined(separator: ",")]).1
        return Set(out.split(separator: "\n").compactMap { line -> Int32? in
            let f = line.split(separator: " ", omittingEmptySubsequences: true)
            return f.count == 2 && !f[1].hasPrefix("Z") ? Int32(f[0]) : nil
        })
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
            if why == "Claude Code isn't installed" { Fix.installClaude() }
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
        /// No Claude Code at ~/.local/bin/claude: links a copy installed another way (Homebrew, npm), else runs the
        /// official installer (`curl -fsSL https://claude.ai/install.sh | bash`, which installs to ~/.local/bin and
        /// needs no password). At most once every 6 hours; the server starts when it is there.
        static func installClaude() {
            guard ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] == nil, !Setup.claudeFound else { return }
            let fm = FileManager.default
            let home = fm.homeDirectoryForCurrentUser
            let bin = home.appendingPathComponent(".local/bin")
            let other = ["/opt/homebrew/bin/claude", "/usr/local/bin/claude", home.appendingPathComponent(".npm-global/bin/claude").path,
                         home.appendingPathComponent(".claude/local/claude").path].first { fm.isExecutableFile(atPath: $0) }
            if let other {
                try? fm.createDirectory(at: bin, withIntermediateDirectories: true)
                try? fm.createSymbolicLink(atPath: bin.appendingPathComponent("claude").path, withDestinationPath: other)
                logLine("server", "found Claude Code at \(other), linked it to ~/.local/bin/claude")
                DispatchQueue.main.async { autoStart() }
                return
            }
            let d = UserDefaults.standard
            guard Date().timeIntervalSince1970 - d.double(forKey: "claudeInstallAt") > 6 * 3600 else { return }
            d.set(Date().timeIntervalSince1970, forKey: "claudeInstallAt")
            logLine("server", "installing Claude Code (the official installer)")
            DispatchQueue.global().async {
                let r = Updater.run("/bin/bash", ["-c", "curl -fsSL https://claude.ai/install.sh | bash"])
                let last = r.1.split(separator: "\n").last.map(String.init) ?? ""
                if Setup.claudeFound {
                    logLine("server", "installed Claude Code")
                    DispatchQueue.main.async { autoStart() }
                } else {
                    logLine("server", "not started: Claude Code didn't install (\(last.prefix(120))); the Kit tries again in 6 hours")
                }
            }
        }

        /// Signed out: starts Claude Code's own sign-in, which opens the sign-in page in the browser by itself. The
        /// person only approves it there. At most once every 6 hours. When the login appears, the server starts
        /// (or starts again) at once.
        static func signIn(endsSoon: Bool = false) {
            guard Thread.isMainThread else { DispatchQueue.main.async { signIn(endsSoon: endsSoon) }; return }
            guard ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] == nil, !test else { return }
            let d = UserDefaults.standard
            let last = d.double(forKey: "serverSignInAt")
            guard Date().timeIntervalSince1970 - last > 6 * 3600, Setup.claudeFound else { return }
            d.set(Date().timeIntervalSince1970, forKey: "serverSignInAt")
            let claude = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/claude").path
            // a screen gives the sign-in the terminal it needs; it opens the browser itself and ends when done
            Updater.run("/usr/bin/screen", ["-dmS", "kit-sign-in", claude, "auth", "login"])
            logLine("server", "sign-in started: the Claude sign-in page opens in the browser")
            Updater.post("server-signin", "Approve the Claude sign-in in your browser",
                         endsSoon ? "The Claude Code login ends soon. The Kit opened the sign-in page, so sessions and the server keep running after that."
                         : "Claude Code is signed out, so sessions from the Claude app can't run. The Kit opened the sign-in page. The server starts when you approve it.")
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
