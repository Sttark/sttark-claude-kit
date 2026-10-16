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
            guard let w = s.waitingSince, -w.timeIntervalSinceNow >= after, -w.timeIntervalSinceNow < 86400 else { return false }
            return told[s.id] != w.timeIntervalSince1970
        }
        guard let first = due.first else { return }
        for s in due { told[s.id] = s.waitingSince!.timeIntervalSince1970 }
        d.set(told, forKey: "waitingTold")
        let c = UNUserNotificationCenter.current()
        c.requestAuthorization(options: [.alert, .sound]) { ok, _ in
            guard ok else { return }
            let n = UNMutableNotificationContent()
            n.title = due.count == 1 ? (first.needsYou ? "Claude needs you: \(first.title)" : "Claude finished: \(first.title)")
                : "\(due.count) sessions are waiting on you"
            n.body = all.prefix(4).map { "\($0.title), \(ago($0.waitingSince!))" }.joined(separator: "\n")
                + "\nClick to open \(first.title)."
            n.sound = .default
            n.userInfo = ["url": first.url]
            c.add(UNNotificationRequest(identifier: "waiting-\(first.id)", content: n, trigger: nil))
        }
        note("waiting notice: \(due.map(\.title).joined(separator: ", "))")
    }

    static func open(_ url: String) {
        guard let u = URL(string: url), !url.isEmpty else { return }
        NSWorkspace.shared.open(u)
    }
}
