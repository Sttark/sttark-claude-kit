import Foundation

/// The session inbox: every recent session in one group, from the shared state the hooks and the app write.
/// The window's Sessions page and the menu's glance both read it, so they always agree.
///
/// Each session shows once, in the first group that fits: held at the usage limit, needs you, Claude working,
/// waiting on someone else (a wait handed to the Kit), then idle.
enum Inbox {
    enum Group: String, CaseIterable {
        case needs, working, waits, held, idle

        var title: String {
            switch self {
            case .needs: return "Needs you"
            case .working: return "Claude working"
            case .waits: return "Waiting on someone else"
            case .held: return "Held at usage limit"
            case .idle: return "Idle"
            }
        }

        /// The time column's heading.
        var column: String {
            switch self {
            case .needs: return "Waiting for"
            case .working: return "Working for"
            case .waits: return "Deadline"
            case .held: return "Goes on"
            case .idle: return "Last active"
            }
        }
    }

    struct Row: Identifiable {
        /// The session's Remote Control id when it has one, so a row keeps its place when it moves to another group.
        let id: String
        let group: Group
        let title: String
        let sub: String
        /// A part of `sub` drawn in ink (who or what it waits on).
        var subStrong = ""
        let time: String
        /// The time is late: waited past the notice, or past a deadline.
        var late = false
        var session: Session? = nil
        var wait: Waits.Wait? = nil
        var hold: Limit.Waiting? = nil
        /// The link that opens the session in the Claude app.
        var url: String { session?.url.nilIfEmpty ?? wait?.sessionURL.nilIfEmpty ?? "" }
        var target: Limit.Target? {
            if let s = session { return Limit.Target(sid: s.sid, cse: s.id, title: s.title) }
            if let h = hold { return h.target }
            if let w = wait, !w.cse.isEmpty { return Limit.Target(sid: "", cse: w.cse, title: w.title) }
            return nil
        }
    }

    struct Snapshot {
        var rows: [Row] = []
        var reach = Reach.Settings(ways: [], email: "", phone: "", chat: "")
        var creditsAll = false
        var paused = false
        func rows(_ g: Group) -> [Row] { rows.filter { $0.group == g } }
        func count(_ g: Group) -> Int { rows.lazy.filter { $0.group == g }.count }

        /// The page's status line: "3 need you · 2 hold until 4:40 PM".
        var summary: String {
            var parts: [String] = []
            let n = count(.needs), w = count(.working), o = count(.waits), h = rows(.held)
            if n > 0 { parts.append("\(n) need\(n == 1 ? "s" : "") you") }
            if w > 0 { parts.append("\(w) working") }
            if o > 0 { parts.append("\(o) wait\(o == 1 ? "s" : "") on someone else") }
            if !h.isEmpty {
                let next = h.compactMap { $0.hold?.until }.min()
                parts.append("\(h.count) held" + (next.map { ", the first goes on at \(Limit.clock($0))" } ?? ""))
            }
            return parts.isEmpty ? "Nothing needs you" : parts.joined(separator: " · ")
        }
    }

    /// Reads the state once. `hours`: how far back an idle session still shows.
    static func snapshot(hours: Double = 12) -> Snapshot {
        let state = State.read()
        var snap = Snapshot()
        snap.reach = Reach.settings(state)
        snap.creditsAll = state["limit_credits_all"] as? Bool ?? false
        snap.paused = state["paused"] as? Bool ?? false
        let raw = state["sessions"] as? [String: [String: Any]] ?? [:]
        let sessions = State.sessions(hours: 24)
        var used = Set<String>()
        func session(cse: String, sid: String) -> Session? {
            sessions.first { (!cse.isEmpty && $0.id == cse) || (!sid.isEmpty && $0.sid == sid) }
        }

        // held at the usage limit
        for h in Limit.waiting {
            let s = session(cse: h.cse, sid: h.sid)
            if let s { used.insert(s.id) }
            let agents = h.agents == 0 ? "" : h.agents == 1 ? " · 1 of its agents holds too" : " · \(h.agents) of its agents hold too"
            let sub = h.hold ? "Hold \(h.at)%" + agents
                : (snap.creditsAll ? "Goes on with usage credits" : "Waits at the \(h.limit) limit") + agents
            var r = Row(id: s?.id ?? "hold:" + h.sid, group: .held, title: s?.title ?? h.title, sub: sub, time: Limit.clock(h.until))
            r.session = s
            r.hold = h
            snap.rows.append(r)
        }

        // needs you, oldest first
        for s in Waiting.sessions where !used.contains(s.id) {
            used.insert(s.id)
            let w = s.waitingSince!
            var r = Row(id: s.id, group: .needs, title: s.title,
                        sub: s.needsYou ? "Needs you" + (s.why.isEmpty ? "" : ": " + s.why) : "Finished; reply not opened",
                        time: Waiting.ago(w))
            r.late = s.needsYou && -w.timeIntervalSinceNow >= Waiting.after
            r.session = s
            snap.rows.append(r)
        }

        // Claude working, the longest first
        let working = sessions.filter { !used.contains($0.id) && (raw[$0.id]?["app"] as? [String: Any])?["working"] as? Bool == true }
        func turnAt(_ s: Session) -> Date? { Limit.num(raw[s.id]?["turn_at"]).map { Date(timeIntervalSince1970: $0) } }
        for s in working.sorted(by: { (turnAt($0) ?? $0.at) < (turnAt($1) ?? $1.at) }) {
            used.insert(s.id)
            var r = Row(id: s.id, group: .working, title: s.title, sub: effortWords(s), time: turnAt(s).map(Waiting.ago) ?? "")
            r.session = s
            snap.rows.append(r)
        }

        // waits handed to the Kit, by deadline
        for w in Waits.list(state) {
            let s = session(cse: w.cse, sid: "")
            if let s { used.insert(s.id) }
            var r = Row(id: s?.id ?? "wait:" + w.id, group: .waits, title: w.title, sub: w.what, time: w.by.map(day) ?? "")
            if !w.from.isEmpty { r.subStrong = "from " + w.from }
            r.late = w.by.map { $0 < Date() } ?? false
            r.session = s
            r.wait = w
            snap.rows.append(r)
        }

        // the rest of the last `hours`, newest first
        let cutoff = Date().addingTimeInterval(-hours * 3600)
        for s in sessions where !used.contains(s.id) && s.at > cutoff {
            var r = Row(id: s.id, group: .idle, title: s.title, sub: effortWords(s), time: Waiting.ago(s.at))
            r.session = s
            snap.rows.append(r)
        }
        return snap
    }

    /// "Auto · design question on a full app window", or "Manual: you set the effort".
    static func effortWords(_ s: Session) -> String {
        s.manual ? "Manual: you set the effort" : "Auto" + (s.reason.isEmpty ? "" : " · " + s.reason)
    }

    /// "4:40 PM" today, "Mon 9:00 AM" within a week, else "Apr 20".
    static func day(_ d: Date) -> String {
        let f = DateFormatter()
        let days = d.timeIntervalSinceNow / 86400
        f.dateFormat = Calendar.current.isDateInToday(d) ? "h:mm a" : (days > -1 && days < 6) ? "EEE h:mm a" : "MMM d"
        return f.string(from: d)
    }

    /// "Mon Nov 16, 9:00 AM · in 3 days".
    static func longDay(_ d: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "EEE MMM d, h:mm a"
        return f.string(from: d) + " · " + relative(d)
    }

    /// "in 3 days", "in 2 hr", "in 12 min", "5 min ago".
    static func relative(_ d: Date) -> String {
        let s = d.timeIntervalSinceNow
        let a = abs(s)
        let t = a < 3600 ? "\(max(1, Int(a / 60))) min" : a < 86400 ? "\(Int(a / 3600)) hr" : "\(Int((a / 86400).rounded())) day\(Int((a / 86400).rounded()) == 1 ? "" : "s")"
        return s >= 0 ? "in " + t : t + " ago"
    }

    /// "10 min", "2 hr".
    static func every(_ secs: Double) -> String {
        secs >= 3600 ? "\(Int(secs / 3600)) hr" : "\(Int(max(1, secs / 60))) min"
    }

    /// How the Kit checks a wait, as wait.py does it.
    static func checks(_ w: Waits.Wait) -> String {
        let age = -(w.setAt ?? Date()).timeIntervalSinceNow
        let modelGap = max(w.every > 0 ? w.every : 600, age < 3 * 3600 ? 0 : age < 86400 ? 1800 : 3600)
        switch w.kind {
        case "pr": return "The pull request on GitHub, every 5 min"
        case "at": return "The clock"
        case "email-reply": return "Your email" + (w.from.isEmpty ? "" : ", for mail from \(w.from)") + ", every \(every(modelGap)), 7 AM to 9 PM"
        case "check-prompt": return "A short Haiku check, every \(every(modelGap)), 7 AM to 9 PM"
        case "check-script": return "The session's own check script, every \(every(w.every > 0 ? w.every : 600))"
        default: return "Every minute"
        }
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
