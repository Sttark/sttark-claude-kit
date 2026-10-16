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
        let claude = home + "/.local/bin/claude"
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
        note("server sessions on: claude rc in \(folder)")
        return nil
    }

    static func stop() {
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

    static func killTree(_ pid: Int32) {
        let kids = Updater.run("/usr/bin/pgrep", ["-P", String(pid)]).1.split(separator: "\n").compactMap { Int32($0) }
        kids.forEach(killTree)
        kill(pid, SIGTERM)
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
