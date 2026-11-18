import Foundation

/// Kept in the Kit app: each message that did not go out, on its session (notify.py `held()` decides, `keep_in_kit()`
/// keeps). That is what a session sent with claude-notify, the Kit's own message after a wait, or a progress check-in,
/// while Reach me by's Alerts switch is off, or with no way checked; a session's own alerts switch keeps its messages
/// the same way. kept.json in the Kit's folder holds the last 7 days. The window shows them on their session (the
/// Sessions page's row and panel), the phone gets each shown session's last 24 hours (Phone.swift), and the Events
/// page has a row for each (the log's "notify <name> kept <id>: <why> | <subject>"). A message the person answered
/// themselves, in the thread, Chat space or Asana task it is about, has `replied` (the reply watch writes it): it is
/// handled, and the window and the phone say "You replied <time>" for it.
enum Kept {
    struct Message: Identifiable, Equatable {
        let id: String
        let at: Date
        /// The session's Remote Control id; empty when it came from outside a session.
        let cse: String
        let title: String
        let subject: String
        let body: String
        /// A link the message points to (a pull request); never the session's own.
        let link: String
        /// "session" (claude-notify), "kit" (the Kit's own message after a wait) or "checkin".
        let from: String
        /// Why it did not go out: "alerts are off", "no way is checked under Reach me by".
        let why: String
        /// When the person replied, themselves, where the message is about (the reply watch, watch.py): the message
        /// is handled, and the Kit says "You replied <time>" for it. Nil while it is open.
        var replied: Date? = nil
        /// Where they replied, in words: the email thread "Lunch".
        var repliedWhere = ""
    }

    static var file: URL { supportDir.appendingPathComponent("kept.json") }
    /// How long a message counts as new: the row shows it, and the phone gets it.
    static let recent: TimeInterval = 86400
    private static let lock = NSLock()
    private static var cache: (stamp: Date, items: [Message])?

    /// Every kept message of the last 7 days, newest first. The file is read again only when it changed.
    static func all() -> [Message] {
        let stamp = (try? file.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate ?? .distantPast
        lock.lock(); defer { lock.unlock() }
        if let c = cache, c.stamp == stamp { return c.items }
        let d = (try? JSONSerialization.jsonObject(with: Data(contentsOf: file))) as? [String: Any]
        let week = Date().addingTimeInterval(-7 * 86400)
        let items = (d?["items"] as? [[String: Any]] ?? []).compactMap { x -> Message? in
            guard let id = x["id"] as? String, let t = Limit.num(x["at"]) else { return nil }
            var m = Message(id: id, at: Date(timeIntervalSince1970: t), cse: x["cse"] as? String ?? "",
                            title: x["title"] as? String ?? "", subject: x["subject"] as? String ?? "",
                            body: x["body"] as? String ?? "", link: x["link"] as? String ?? "",
                            from: x["from"] as? String ?? "session", why: x["why"] as? String ?? "alerts are off")
            if let r = x["replied"] as? [String: Any], let at = Limit.num(r["at"]) {
                m.replied = Date(timeIntervalSince1970: at)
                m.repliedWhere = r["where"] as? String ?? ""
            }
            return m
        }.filter { $0.at > week }.sorted { $0.at > $1.at }
        cache = (stamp, items)
        return items
    }

    /// One session's kept messages, newest first; `within` seconds back (default: all 7 days).
    static func of(_ cse: String, within: TimeInterval? = nil) -> [Message] {
        guard !cse.isEmpty else { return [] }
        let since = within.map { Date().addingTimeInterval(-$0) } ?? .distantPast
        return all().filter { $0.cse == cse && $0.at > since }
    }

    static func find(_ id: String) -> Message? { all().first { $0.id == id } }

    /// "Not sent: alerts are off." for the window.
    static func notSent(_ why: String) -> String { "Not sent: \(why)." }

    /// "You replied 2:30 PM": the person replied themselves where a kept message or an email reply wait is about.
    static func youReplied(_ at: Date) -> String { "You replied " + Limit.clock(at) }

    /// The tip of "You replied": where, when the reply watch said (`the email thread "Lunch"`).
    static func repliedTip(_ place: String) -> String {
        let w = place.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "^in ", with: "", options: .regularExpression)
        return w.isEmpty ? "You replied to this yourself." : "You replied to this yourself, in \(w)."
    }
}
