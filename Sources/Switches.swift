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

/// "Name sessions automatically": the naming hook in Claude Code's settings.
enum Names {
    static var on: Bool {
        let out = Updater.run("/usr/bin/python3", [Bypass.installer, "--status"]).1
        let d = (try? JSONSerialization.jsonObject(with: Data(out.utf8))) as? [String: Bool]
        return d?["names"] ?? false
    }

    static func set(_ on: Bool) {
        let r = Updater.run("/usr/bin/python3", [Bypass.installer, "--names", on ? "on" : "off"]).1
        note("naming hook: \(r.trimmingCharacters(in: .whitespacesAndNewlines))")
    }
}

/// "Sync Claude profile instructions": copies the instructions from the Claude app's Profile settings into
/// ~/.claude/CLAUDE.md every 15 minutes, and puts them in front of every prompt with a hook.
/// The sync needs two Python add-ons (curl_cffi to get past Cloudflare, cryptography to read the Claude
/// app's sign-in), installed into a private folder the first time it's turned on.
enum ProfileSync {
    static let label = "com.sttark.claude-profile-sync"
    static var plist: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }
    static var log: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/claude-profile-sync.log")
    }
    static var venv: URL { supportDir.appendingPathComponent("venv") }
    static var python: String { venv.appendingPathComponent("bin/python").path }
    static var domain: String { "gui/\(getuid())" }
    static var claudeAppSignedIn: Bool {
        FileManager.default.fileExists(atPath: FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Claude/config.json").path)
    }
    private(set) static var settingUp = false

    static var on: Bool {
        let out = Updater.run("/usr/bin/python3", [Bypass.installer, "--status"]).1
        let d = (try? JSONSerialization.jsonObject(with: Data(out.utf8))) as? [String: Bool]
        return d?["profile"] ?? false
    }

    /// The last line the sync wrote: when it last ran and what happened.
    static var lastResult: String? {
        guard let text = try? String(contentsOf: log, encoding: .utf8) else { return nil }
        return text.split(separator: "\n").last.map(String.init)
    }

    static func start(done: @escaping (String?) -> Void) {
        settingUp = true
        DispatchQueue.global().async {
            var err: String?
            let fm = FileManager.default
            if !fm.isExecutableFile(atPath: python) {
                if Updater.run("/usr/bin/python3", ["-m", "venv", venv.path]).0 != 0 {
                    err = "Couldn't set up Python. Install Apple's command line tools: xcode-select --install"
                }
            }
            if err == nil {
                // python -m pip, not bin/pip: a copied folder's pip still points at its old place
                let r = Updater.run(python, ["-m", "pip", "install", "-q", "--disable-pip-version-check", "curl_cffi", "cryptography"])
                if r.0 != 0 { err = "Couldn't install the add-ons the sync needs: " + r.1.suffix(200) }
            }
            if err == nil {
                let home = fm.homeDirectoryForCurrentUser.path
                let d: [String: Any] = [
                    "Label": label,
                    "ProgramArguments": [python, hooksDir.appendingPathComponent("profile-sync.py").path],
                    "RunAtLoad": true, "StartInterval": 900,
                    "StandardOutPath": log.path, "StandardErrorPath": log.path,
                    "EnvironmentVariables": ["PATH": "\(home)/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"],
                ]
                try? fm.createDirectory(at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
                (d as NSDictionary).write(to: plist, atomically: true)
                Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
                Updater.run("/bin/launchctl", ["bootstrap", domain, plist.path])
                let r = Updater.run("/usr/bin/python3", [Bypass.installer, "--profile", "on"]).1
                note("profile sync on: \(r.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
            DispatchQueue.main.async { settingUp = false; done(err) }
        }
    }

    static func stop() {
        Updater.run("/bin/launchctl", ["bootout", "\(domain)/\(label)"])
        try? FileManager.default.removeItem(at: plist)
        let r = Updater.run("/usr/bin/python3", [Bypass.installer, "--profile", "off"]).1
        note("profile sync off: \(r.trimmingCharacters(in: .whitespacesAndNewlines))")
    }
}

/// "Claude window in Chrome": one Chrome window named "Claude", in the person's own signed-in profile, that
/// Claude moves between pages with the claude-window tool instead of opening tabs or windows (which bring Chrome
/// in front of whatever the person is typing in). Opening the window is the one moment Chrome comes forward, so
/// it only happens when the person clicks; the app puts the app they were using back in front right after.
enum ChromeWindow {
    static var on: Bool { UserDefaults.standard.bool(forKey: "claudeWindow") }
    static var tool: URL { FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/claude-window") }
    static var chromeRunning: Bool { !NSRunningApplication.runningApplications(withBundleIdentifier: "com.google.Chrome").isEmpty }

    /// Asking Chrome while it's closed would open it, so this only asks a running Chrome.
    static var exists: Bool {
        guard chromeRunning else { return false }
        let r = Updater.run("/usr/bin/osascript", ["-e", #"tell application "Google Chrome" to return (count of (every window whose given name is "Claude")) > 0"#])
        return r.1.trimmingCharacters(in: .whitespacesAndNewlines) == "true"
    }

    static func installTool() {
        let fm = FileManager.default
        try? fm.createDirectory(at: tool.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? fm.removeItem(at: tool)
        try? fm.createSymbolicLink(at: tool, withDestinationURL: hooksDir.appendingPathComponent("claude-window.sh"))
    }

    static func open() {
        let back = NSWorkspace.shared.frontmostApplication
        let r = Updater.run("/usr/bin/osascript", ["-e", """
            tell application "Google Chrome"
              set w to make new window
              set given name of w to "Claude"
              set URL of active tab of w to "about:blank"
              return id of w
            end tell
            """])
        note("Claude window: \(r.0 == 0 ? "opened" : "couldn't open: " + r.1.trimmingCharacters(in: .whitespacesAndNewlines))")
        back?.activate()
    }

    /// The hook reads this to add the browser rule to every prompt.
    static func tellHooks() { State.change { $0["claude_window"] = on } }

    static func set(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: "claudeWindow")
        tellHooks()
        if on {
            installTool()
            if !exists { open() }
        } else {
            try? FileManager.default.removeItem(at: tool)
            if chromeRunning {
                Updater.run("/usr/bin/osascript", ["-e", #"tell application "Google Chrome" to close (every window whose given name is "Claude")"#])
            }
        }
        note("Claude window in Chrome \(on ? "on" : "off")")
    }
}
