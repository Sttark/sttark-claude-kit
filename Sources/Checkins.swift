import Foundation

/// Progress check-ins (Resources/hooks/checkin.py, run by wait.py --check each minute): while a session or its agents
/// work 15 minutes or more, a short note every 15 minutes, kept in checkins.json and shown in the Kit app: on the
/// session's row in Claude working (the window's Sessions page and Kit on your phone) and in its side panel. A
/// check-in is never an alert: no Reach me by way, no Mac notice. On unless the person turns it off in Settings
/// ("checkins" in KitDefaults' turned-off record). The hook reads "checkins" in the state file, which the app writes
/// at launch and at each change.
///
/// Check-ins in the session: a note Haiku wrote also goes into the session's own chat, as a prompt the session answers
/// in a line or two, while its turn is idle and its agents work in the background; only into a session that runs in
/// the Kit's own copy, the one kind the Kit can type into. On unless turned off ("checkinsChat" in the turned-off
/// record, "checkins_chat" in the state file); it needs the check-ins above.
enum Checkins {
    static let id = "checkins"
    static let chatId = "checkinsChat"
    static var on: Bool { !KitDefaults.turnedOff(id) }
    static var chatOn: Bool { !KitDefaults.turnedOff(chatId) }
    static let file = supportDir.appendingPathComponent("checkins.json")

    static func tellHooks() {
        let v = on, chat = chatOn
        let s = State.read()
        if s["checkins"] as? Bool != v || s["checkins_chat"] as? Bool != chat {
            State.change { $0["checkins"] = v; $0["checkins_chat"] = chat }
        }
    }

    static func set(_ on: Bool) {
        KitDefaults.chose(id, on: on)
        tellHooks()
    }

    static func setChat(_ on: Bool) {
        KitDefaults.chose(chatId, on: on)
        tellHooks()
    }

    /// The latest check-in of a session's work that runs now.
    struct Note: Equatable {
        /// 2 or 3 short sentences: what got done, what it does next, what stops it.
        let text: String
        let at: Date

        /// "Check-in 12 min ago", "Check-in just now".
        var age: String {
            let a = Waiting.ago(at)
            return a == "just now" ? "Check-in just now" : "Check-in \(a) ago"
        }
    }

    /// Each session's latest check-in of the run of work that goes on now, by its Remote Control id. A run that ended
    /// has none (checkin.py drops its note), so the line goes away when the work ends. None while the switch is off
    /// (`state`'s "checkins"), since the notes then stop.
    static func latest(_ state: [String: Any]) -> [String: Note] {
        guard state["checkins"] as? Bool != false,
              let d = try? Data(contentsOf: file),
              let all = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any],
              let runs = all["sessions"] as? [String: [String: Any]] else { return [:] }
        var out: [String: Note] = [:]
        for (cse, c) in runs {
            guard let text = (c["note"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty,
                  let at = Limit.num(c["note_at"]), let start = Limit.num(c["start"]), at >= start else { continue }
            out[cse] = Note(text: text, at: Date(timeIntervalSince1970: at))
        }
        return out
    }
}
