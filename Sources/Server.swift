import AppKit

/// "Start sessions from your phone": a `claude rc` (Remote Control) server that macOS keeps running.
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
    static var otherRunning: Bool {
        guard !installed, ProcessInfo.processInfo.environment["STTARK_EFFORT_TEST"] == nil else { return false }
        return Updater.run("/usr/bin/pgrep", ["-f", "claude (rc|remote-control)( |$)"]).0 == 0
    }

    static func start(folder: String, skipApprovals: Bool) -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let claude = home + "/.local/bin/claude"
        let mode = skipApprovals ? " --permission-mode bypassPermissions" : ""
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
        note("phone sessions on: claude rc in \(folder)\(skipApprovals ? ", without approvals" : "")")
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
        note("phone sessions off")
    }

    static func killTree(_ pid: Int32) {
        let kids = Updater.run("/usr/bin/pgrep", ["-P", String(pid)]).1.split(separator: "\n").compactMap { Int32($0) }
        kids.forEach(killTree)
        kill(pid, SIGTERM)
    }

    /// Turning it on: pick the folder, choose whether sessions may run commands without asking, start.
    static func setUp() {
        NSApp.activate(ignoringOtherApps: true)
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.canCreateDirectories = true
        p.prompt = "Use this folder"
        p.message = "Sessions you start from your phone or the Claude app will start in this folder. A folder that holds all your projects works well."
        let src = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("src")
        p.directoryURL = FileManager.default.fileExists(atPath: src.path) ? src : FileManager.default.homeDirectoryForCurrentUser
        guard p.runModal() == .OK, let folder = p.url?.path else { return }

        let a = NSAlert()
        a.messageText = "Start sessions from your phone"
        let shown = folder.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~")
        a.informativeText = "Sessions will run on this Mac, in \(shown). The Mac has to be on and awake for them to run.\n\nIn the Claude app, open Code, pick this Mac, and type."
        let skip = NSButton(checkboxWithTitle: "Let sessions run commands without asking first", target: nil, action: nil)
        skip.state = .off
        skip.toolTip = "Nobody is at the Mac to approve each command. Off: you approve from your phone."
        a.accessoryView = skip
        a.addButton(withTitle: "Start")
        a.addButton(withTitle: "Cancel")
        guard a.runModal() == .alertFirstButtonReturn else { return }
        if let err = start(folder: folder, skipApprovals: skip.state == .on) {
            let e = NSAlert()
            e.messageText = "Couldn't start it"
            e.informativeText = err
            e.runModal()
        }
    }
}
