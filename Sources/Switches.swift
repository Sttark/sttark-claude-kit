import AppKit

/// "Bypass permissions for server sessions": the bypass hook in Claude Code's settings.
enum Bypass {
    static var installer: String { hooksDir.appendingPathComponent("install-hooks.py").path }

    static var on: Bool {
        let out = Updater.run("/usr/bin/python3", [installer, "--status"]).1
        let d = (try? JSONSerialization.jsonObject(with: Data(out.utf8))) as? [String: Bool]
        return d?["bypass"] ?? false
    }

    static func set(_ on: Bool) {
        let r = Updater.run("/usr/bin/python3", [installer, "--bypass", on ? "on" : "off"]).1
        note("bypass hook: \(r.trimmingCharacters(in: .whitespacesAndNewlines))")
    }
}

/// "Approve Claude in Chrome": the helper inside the app, run at login by a LaunchAgent.
/// It needs the Accessibility permission to press the button, which macOS ties to the helper itself.
enum ChromeApprover {
    static let label = "com.sttark.chrome-approver"
    static var plist: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }
    static var log: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/claude-chrome-approver.log")
    }
    /// A copy outside the app, replaced only when it changes, so an app update that doesn't touch it
    /// doesn't make macOS ask for Accessibility again.
    static var helper: URL { supportDir.appendingPathComponent("SttarkChromeApprover") }
    static var domain: String { "gui/\(getuid())" }

    static var on: Bool { FileManager.default.fileExists(atPath: plist.path) }

    /// The helper's own last word on Accessibility, from its log.
    static var needsAccessibility: Bool {
        guard on, let text = try? String(contentsOf: log, encoding: .utf8) else { return false }
        let last = text.split(separator: "\n").last(where: { $0.contains("accessibility access") }) ?? ""
        return last.contains(": no") || last.contains(": removed")
    }

    static func copyHelper() {
        guard let src = Bundle.main.url(forAuxiliaryExecutable: "SttarkChromeApprover") else { return }
        let fm = FileManager.default
        if fm.contentsEqual(atPath: src.path, andPath: helper.path) { return }
        try? fm.removeItem(at: helper)
        try? fm.copyItem(at: src, to: helper)
        if on {   // a new helper: restart it so the new code runs
            Updater.run("/bin/launchctl", ["kickstart", "-k", "\(domain)/\(label)"])
        }
    }

    static func start() {
        copyHelper()
        let d: [String: Any] = [
            "Label": label, "ProgramArguments": [helper.path],
            "RunAtLoad": true, "KeepAlive": true, "ProcessType": "Interactive",
            "StandardOutPath": log.path, "StandardErrorPath": log.path,
        ]
        try? FileManager.default.createDirectory(at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
        (d as NSDictionary).write(to: plist, atomically: true)
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        Updater.run("/bin/launchctl", ["bootstrap", domain, plist.path])
        note("Chrome approver on")
    }

    static func stop() {
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        try? FileManager.default.removeItem(at: plist)
        note("Chrome approver off")
    }

    static func openAccessibility() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
    }
}
