import AppKit

/// New Code sessions in the Claude desktop app start on this Mac's server (Remote Control > its folder), with nothing
/// for the person to choose. The app starts a new session where the last one was started, and keeps that in its
/// Local Storage; desktop-default.py puts the server first there (see that file). The app locks its Local Storage
/// while it runs, so this acts when the Claude app quits (it also restarts for each of its updates), on launch and
/// every 10 minutes, and does nothing while the app is open. On by default; the Settings switch turns it off
/// ("desktopDefault" in KitDefaults' turned-off record).
enum DesktopDefault {
    static let id = "desktopDefault"
    static var script: String { hooksDir.appendingPathComponent("desktop-default.py").path }
    static var tool: String { Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/kit-ldb").path }
    static var on: Bool { !KitDefaults.turnedOff(id) }
    private static var last = ""
    private static let queue = DispatchQueue(label: "desktop-default")

    static func start() {
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didTerminateApplicationNotification,
                                                          object: nil, queue: .main) { n in
            guard (n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication)?.bundleIdentifier
                    == Waiting.claudeApp else { return }
            queue.asyncAfter(deadline: .now() + 3) { apply() }   // the app lets go of its Local Storage as it exits
        }
        queue.asyncAfter(deadline: .now() + 60) { apply() }      // after the server has had time to connect
        Timer.scheduledTimer(withTimeInterval: 600, repeats: true) { _ in queue.async { apply() } }
    }

    /// The person turned the switch on in Settings.
    static func now() { queue.async { apply() } }

    private static func apply() {
        guard on, !KitDefaults.test, Server.installed, let folder = Server.folder,
              FileManager.default.isExecutableFile(atPath: tool) else { return }
        let out = Updater.run("/usr/bin/python3", [script, "apply", "--folder", folder, "--ldb", tool]).1
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard out != last else { return }
        last = out
        note("desktop default: \(out)")
        guard out.hasPrefix("set:") else { return }
        let d = UserDefaults.standard
        guard !d.bool(forKey: "desktopDefaultTold") else { return }
        d.set(true, forKey: "desktopDefaultTold")
        let name = (folder as NSString).lastPathComponent
        Updater.post("desktop-default", "New sessions start on this Mac's server",
                     "New Code sessions in the Claude app now start on Remote Control > \(name), so they show on your phone and in the Kit.")
    }
}
