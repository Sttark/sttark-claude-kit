import Foundation

/// Keeps one copy of Claude Code that never moves (~/.local/share/claude/stable/claude) and runs the server from
/// it, so macOS keeps one Accessibility permission across Claude Code updates. The work is in stable-claude.sh,
/// run every 30 minutes by the LaunchAgent com.sttark.claude-stable; it restarts the server only between 2 and
/// 5 AM, when no session is working.
enum Stable {
    static let label = "com.sttark.claude-stable"
    static var plist: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }
    static var domain: String { "gui/\(getuid())" }

    /// On while this app's server is on.
    static func keep(_ on: Bool) {
        let fm = FileManager.default
        if on {
            let d: [String: Any] = ["Label": label, "ProgramArguments": ["/bin/zsh", hooksDir.appendingPathComponent("stable-claude.sh").path],
                                    "StartInterval": 1800, "RunAtLoad": true]
            let had = NSDictionary(contentsOf: plist) as? [String: Any]
            guard had == nil || !(had! as NSDictionary).isEqual(to: d) else { return }
            (d as NSDictionary).write(to: plist, atomically: true)
            Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
            Updater.run("/bin/launchctl", ["bootstrap", domain, plist.path])
            note("fixed Claude Code copy: night job on")
        } else if fm.fileExists(atPath: plist.path) {
            Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
            try? fm.removeItem(at: plist)
            note("fixed Claude Code copy: night job off")
        }
    }
}
