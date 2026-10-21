import AppKit

/// First launch after the rename from Sttark Effort: carry everything over, then take the old app away.
/// Settings, the state and hook folder, and the log come across; hooks in Claude Code's settings and the
/// LaunchAgents are pointed at the new folder; the old app is quit and moved to the Trash.
/// The server for Claude app sessions is left alone, since restarting it would end every running session.
enum Migrate {
    static let flag = "migratedFromSttarkEffort"
    static let fm = FileManager.default
    static var home: URL { fm.homeDirectoryForCurrentUser }
    static var oldDir: URL { home.appendingPathComponent("Library/Application Support/SttarkEffort") }
    static var oldApp: URL { URL(fileURLWithPath: "/Applications/SttarkEffort.app") }

    /// Before anything reads settings or state.
    static func beforeStart() {
        let d = UserDefaults.standard
        guard !d.bool(forKey: flag) else { return }
        for (k, v) in d.persistentDomain(forName: "com.sttark.sttark-effort") ?? [:]
        where d.object(forKey: k) == nil && !["loginItemSet", "loginItemPath", "notifiedBuild"].contains(k) {
            d.set(v, forKey: k)
        }
        if fm.fileExists(atPath: oldDir.path) && !fm.fileExists(atPath: supportDir.appendingPathComponent("state.json").path) {
            for name in (try? fm.contentsOfDirectory(atPath: oldDir.path)) ?? [] {
                let to = supportDir.appendingPathComponent(name)
                if !fm.fileExists(atPath: to.path) { try? fm.copyItem(at: oldDir.appendingPathComponent(name), to: to) }
            }
        }
        let oldLog = home.appendingPathComponent("Library/Logs/claude-effort-hook.log")
        if fm.fileExists(atPath: oldLog.path) && !fm.fileExists(atPath: logURL.path) { try? fm.moveItem(at: oldLog, to: logURL) }
    }

    /// After the hooks were copied in: point everything that's on at the new folder, then retire the old app.
    static func afterStart() {
        let d = UserDefaults.standard
        guard !d.bool(forKey: flag) else { return }
        if Bypass.on { Bypass.set(true) }
        if Names.on { Names.set(true) }
        let test = ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] != nil   // dry runs leave real agents and apps alone
        if ProfileSync.on && !test { ProfileSync.start { _ in } }
        if FileManager.default.fileExists(atPath: ChromeApprover.plist.path) && !test { ChromeApprover.start() }
        if ChromeWindow.on { ChromeWindow.installTool() }
        if !test { for app in NSRunningApplication.runningApplications(withBundleIdentifier: "com.sttark.sttark-effort") { app.terminate() }
            if fm.fileExists(atPath: oldApp.path) { try? fm.trashItem(at: oldApp, resultingItemURL: nil) } }
        d.set(true, forKey: flag)
        note("moved over from Sttark Effort")
    }
}
