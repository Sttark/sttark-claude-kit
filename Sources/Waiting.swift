import AppKit
import UserNotifications

/// "Waiting on you": sessions where Claude finished a reply you haven't read, on any device. Checked every
/// minute; a notice comes once per reply after it has waited 10 minutes.
enum Waiting {
    static let after: TimeInterval = 10 * 60

    static var sessions: [Session] {
        // the ones that need you first, then the ones you haven't opened; oldest first in each
        State.sessions(hours: 24).filter { $0.waitingSince != nil }
            .sorted { ($0.needsYou ? 0 : 1, $0.waitingSince!) < ($1.needsYou ? 0 : 1, $1.waitingSince!) }
    }

    static func ago(_ d: Date) -> String {
        let m = Int(-d.timeIntervalSinceNow / 60)
        if m < 1 { return "just now" }
        if m < 60 { return "\(m) min" }
        if m < 1440 { return "\(m / 60) hr" }
        return "\(m / 1440) d"
    }

    /// Runs the hook's check off the main thread, then sends any notice that's due.
    static func refresh(done: @escaping () -> Void = {}) {
        DispatchQueue.global().async {
            Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path, "--track"])
            DispatchQueue.main.async { notifyDue(); done() }
        }
    }

    static func notifyDue() {
        let d = UserDefaults.standard
        var told = d.dictionary(forKey: "waitingTold") as? [String: Double] ?? [:]
        let all = sessions
        let due = all.filter { s in
            guard s.needsYou, let w = s.waitingSince, -w.timeIntervalSinceNow >= after, -w.timeIntervalSinceNow < 86400 else { return false }
            return told[s.id] != w.timeIntervalSince1970
        }
        guard let first = due.first else { return }
        for s in due { told[s.id] = s.waitingSince!.timeIntervalSince1970 }
        d.set(told, forKey: "waitingTold")
        let c = UNUserNotificationCenter.current()
        c.requestAuthorization(options: [.alert, .sound]) { ok, _ in
            guard ok else { return }
            let n = UNMutableNotificationContent()
            n.title = due.count == 1 ? "Claude needs you: \(first.title)" : "\(due.count) sessions need you"
            n.body = all.filter(\.needsYou).prefix(4).map { "\($0.title), \(ago($0.waitingSince!))" }.joined(separator: "\n")
                + "\nClick to open \(first.title)."
            n.sound = .default
            n.userInfo = ["url": first.url, "id": first.id]
            c.add(UNNotificationRequest(identifier: "waiting-\(first.id)", content: n, trigger: nil))
        }
        note("waiting notice: \(due.map(\.title).joined(separator: ", "))")
    }

    /// When the Claude app was the app in front with the screen on, so the check can tell a reply you saw from
    /// one that landed while you were in another app or away. Kept for a day as [[start, end], ...] in
    /// claude-front.json; while it's in front the last one ends at 0.
    static let frontFile = supportDir.appendingPathComponent("claude-front.json")
    static let claudeApp = "com.anthropic.claudefordesktop"

    static func watchFront() {
        record(false, closeAt: nil)   // a span left open by the last run: when it ended is unknown, so it counts for nothing
        let claudeInFront = { NSWorkspace.shared.frontmostApplication?.bundleIdentifier == claudeApp }
        record(claudeInFront())
        let ws = NSWorkspace.shared.notificationCenter
        ws.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { n in
            record((n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication)?.bundleIdentifier == claudeApp)
        }
        ws.addObserver(forName: NSWorkspace.screensDidSleepNotification, object: nil, queue: .main) { _ in record(false) }
        ws.addObserver(forName: NSWorkspace.screensDidWakeNotification, object: nil, queue: .main) { _ in record(claudeInFront()) }
        let dn = DistributedNotificationCenter.default()
        dn.addObserver(forName: .init("com.apple.screenIsLocked"), object: nil, queue: .main) { _ in record(false) }
        dn.addObserver(forName: .init("com.apple.screenIsUnlocked"), object: nil, queue: .main) { _ in record(claudeInFront()) }
    }

    /// Opens a span when Claude comes to the front, closes it (at `closeAt`, now by default; nil: at its start) when it leaves.
    static func record(_ front: Bool, closeAt: Double? = Date().timeIntervalSince1970) {
        let now = Date().timeIntervalSince1970
        var spans = ((try? JSONSerialization.jsonObject(with: Data(contentsOf: frontFile))) as? [[Double]] ?? [])
            .filter { $0.count == 2 && ($0[1] == 0 || $0[1] > now - 86400) }
        let open = spans.last?[1] == 0
        if front && !open { spans.append([now, 0]) }
        else if !front && open { spans[spans.count - 1][1] = closeAt ?? spans[spans.count - 1][0] }
        else { return }
        if let d = try? JSONSerialization.data(withJSONObject: spans) { try? d.write(to: frontFile, options: .atomic) }
    }

    /// Opens a session in the Claude desktop app when it is installed, else in the browser. The app's own link for a
    /// Claude Code session is claude://code/<cse_… or session_… id> (its open-url handler). `id` is the session's
    /// Remote Control id; without it the id is read from the link when the link has one.
    static func open(_ url: String, id: String = "") {
        if let app = appLink(id: id, url: url) { NSWorkspace.shared.open(app); return }
        guard let u = URL(string: url), !url.isEmpty else { return }
        NSWorkspace.shared.open(u)
    }

    static func appLink(id: String, url: String) -> URL? {
        var sid = id
        if !(sid.hasPrefix("cse_") || sid.hasPrefix("session_")), let u = URL(string: url), u.host == "claude.ai" {
            let parts = u.path.split(separator: "/")
            if parts.count == 2, parts[0] == "code", parts[1].hasPrefix("session_") || parts[1].hasPrefix("cse_") { sid = String(parts[1]) }
        }
        guard sid.hasPrefix("cse_") || sid.hasPrefix("session_"), let app = URL(string: "claude://code/\(sid)"),
              NSWorkspace.shared.urlForApplication(toOpen: app) != nil else { return nil }
        return app
    }
}
