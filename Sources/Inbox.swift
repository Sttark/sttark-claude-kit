import Foundation

/// The session inbox: every recent session in one group, from the shared state the hooks and the app write.
/// The window's Sessions page and the menu's glance both read it, so they always agree.
///
/// Each session shows once, in the first group that fits: held at the usage limit, needs you, Claude working,
/// waiting on someone else (a wait handed to the Kit), then idle. The sessions that run only on this Mac (Terminal,
/// or "This computer" in the desktop app, with no Remote Control) show before idle, since each one can move to
/// Remote Control.
enum Inbox {
    enum Group: String, CaseIterable {
        case needs, working, waits, held, local, idle

        var title: String {
            switch self {
            case .needs: return "Needs you"
            case .working: return "Claude working"
            case .waits: return "Waiting on someone else"
            case .held: return "Held at usage limit"
            case .idle: return "Idle"
            case .local: return "On this Mac only"
            }
        }

        /// The SF Symbol the window and the menu show for the group.
        var symbol: String {
            switch self {
            case .needs: return "bell"
            case .working: return "waveform.path.ecg"
            case .waits: return "hourglass"
            case .held: return "pause.circle"
            case .idle: return "moon.zzz"
            case .local: return "desktopcomputer"
            }
        }

        /// The time column's heading.
        var column: String {
            switch self {
            case .needs: return "Waiting for"
            case .working: return "Working for"
            case .waits: return "Deadline"
            case .held: return "Goes on"
            case .idle, .local: return "Last active"
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
        /// The first wait (by deadline) and every wait of the session: a session that waits on several things is one row.
        var wait: Waits.Wait? = nil
        var waits: [Waits.Wait] = []
        /// `subStrong` is a warning (a check that fails).
        var subWarn = false
        var hold: Limit.Waiting? = nil
        /// A session that runs only on this Mac (On this Mac only).
        var local: LocalSessions.Item? = nil
        /// What a session runs in the background after its turn ended (Claude working, with no turn).
        var background: Background? = nil
        /// The time with what it is, for the menu: "waiting 15 min", "continues Sat 2:00 AM", "deadline Mon 9:00 AM".
        var timeLabel: String {
            guard !time.isEmpty else { return "" }
            let now = time == "just now"
            switch group {
            case .needs: return now ? "waiting just now" : "waiting \(time)"
            case .working: return now ? "started just now" : "working \(time)"
            case .waits: return "deadline \(time)"
            case .held: return "continues \(time)"
            case .idle, .local: return now ? "active just now" : "active \(time) ago"
            }
        }
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

        // The sessions the Claude app lists (not archived, not runs of a scheduled task), read every 10 seconds while
        // the window or the menu is open and every minute otherwise (Sync.swift). Only those show as needs you, working or idle; without a fresh list, the Kit's own sessions do.
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let list = state["app_list"] as? [String: Any]
        let fresh = Limit.num(list?["at"]).map { Date().timeIntervalSince1970 - $0 < 15 * 60 } ?? false
        let listed = fresh ? (list?["sessions"] as? [[String: Any]] ?? []) : []
        let listedIds: Set<String>? = fresh ? Set(listed.compactMap { $0["id"] as? String }) : nil
        func inApp(_ id: String) -> Bool { listedIds?.contains(id) ?? true }
        // sessions the app lists that the Kit has no record of yet (older ones, or ones its hooks never ran in)
        var extra: [Session] = []
        var bucket: [String: String] = [:]
        for x in listed {
            guard let id = x["id"] as? String else { continue }
            bucket[id] = x["bucket"] as? String ?? ""
            guard !sessions.contains(where: { $0.id == id }) else { continue }
            let last = (x["last"] as? String).flatMap { iso.date(from: $0) ?? ISO8601DateFormatter().date(from: $0) } ?? .distantPast
            var e = Session(id: id, title: (x["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "Session " + id.suffix(6),
                            level: x["level"] as? String ?? "", reason: "", manual: false, at: last)
            e.url = "https://claude.ai/code/session_" + id.dropFirst(4)
            if bucket[id] == "blocked" { e.needsYou = true; e.why = "waiting on your answer or permission"; e.waitingSince = last }
            extra.append(e)
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

        // needs you, oldest first: only where the person must act (a question, a decision, a permission). A
        // finished reply that needs nothing, read or not, is idle; it shows "Finished; reply not opened" there.
        var unread: [String: Date] = [:]
        for s in Waiting.sessions + extra.filter(\.needsYou) where !used.contains(s.id) && inApp(s.id) {
            guard s.needsYou else { unread[s.id] = s.waitingSince; continue }
            used.insert(s.id)
            let w = s.waitingSince!
            var r = Row(id: s.id, group: .needs, title: s.title, sub: "Needs you" + (s.why.isEmpty ? "" : ": " + s.why),
                        time: Waiting.ago(w))
            r.late = -w.timeIntervalSinceNow >= Waiting.after
            r.session = s
            snap.rows.append(r)
        }

        // Claude working, the longest first: in a turn, or with agents or background commands still running after it
        // in a turn: the app's list when it is newer than the minute's check of the session, else that check
        let listAt = Limit.num(list?["at"]) ?? 0
        func inTurn(_ s: Session) -> Bool {
            let app = raw[s.id]?["app"] as? [String: Any]
            if let b = bucket[s.id], listAt > Limit.num(app?["checked"]) ?? 0 { return b == "working" }
            return app?["working"] as? Bool == true || bucket[s.id] == "working"
        }
        let working = (sessions + extra).filter { !used.contains($0.id) && inApp($0.id) && (inTurn($0) || background(raw[$0.id]) != nil) }
        func turnAt(_ s: Session) -> Date? { Limit.num(raw[s.id]?["turn_at"]).map { Date(timeIntervalSince1970: $0) } }
        func since(_ s: Session) -> Date? { inTurn(s) ? turnAt(s) : background(raw[s.id])?.since }
        for s in working.sorted(by: { (since($0) ?? $0.at) < (since($1) ?? $1.at) }) {
            used.insert(s.id)
            let bg = inTurn(s) ? nil : background(raw[s.id])
            var r = Row(id: s.id, group: .working, title: s.title, sub: bg.map(\.words) ?? effortWords(s),
                        time: since(s).map(Waiting.ago) ?? "")
            r.session = s
            r.background = bg
            snap.rows.append(r)
        }

        // waits handed to the Kit, one row per session, by its first deadline
        var bySession: [String: [Waits.Wait]] = [:], order: [String] = []
        for w in Waits.list(state) {
            let key = w.cse.isEmpty ? "wait:" + w.id : w.cse
            if bySession[key] == nil { order.append(key) }
            bySession[key, default: []].append(w)
        }
        for key in order {
            let ws = bySession[key]!, w = ws[0]
            let s = session(cse: w.cse, sid: "")
            if let s { used.insert(s.id) }
            var r = Row(id: s?.id ?? (w.cse.isEmpty ? "wait:" + w.id : w.cse), group: .waits, title: w.title,
                        sub: ws.count == 1 ? w.what : waitsWords(ws), time: w.by.map(day) ?? "")
            if ws.count == 1, !w.from.isEmpty { r.subStrong = "from " + w.from }
            let failing = ws.filter { !$0.failing.isEmpty }.count
            if failing > 0 { r.subStrong = ws.count == 1 || failing == ws.count ? "check failing" : "\(failing) check\(failing == 1 ? "" : "s") failing"; r.subWarn = true }
            r.late = w.by.map { $0 < Date() } ?? false
            r.session = s
            r.wait = w
            r.waits = ws
            snap.rows.append(r)
        }

        // the rest: every other session the app lists (or, without the list, the last `hours`), newest first
        let cutoff = Date().addingTimeInterval(-hours * 3600)
        let rest = (sessions + extra).filter { !used.contains($0.id) && inApp($0.id)
            && (listedIds != nil || $0.at > cutoff || unread[$0.id] != nil) }
        for s in rest.sorted(by: { (unread[$0.id] ?? $0.at) > (unread[$1.id] ?? $1.at) }) {
            let sub = unread[s.id] != nil ? "Finished; reply not opened" : effortWords(s)
            var r = Row(id: s.id, group: .idle, title: s.title, sub: sub, time: Waiting.ago(unread[s.id] ?? s.at))
            r.session = s
            snap.rows.append(r)
        }

        // on this Mac only: started in Terminal or the desktop app without Remote Control; they can move to it
        for x in LocalSessions.items {
            let now = x.pending ? "Moves to Remote Control when its reply ends"
                : x.busy ? "Open in \(x.whereWords), Claude working" : x.pid != nil ? "Open in \(x.whereWords)" : "In \(x.whereWords)"
            var r = Row(id: "local:" + x.id, group: .local, title: x.title, sub: now, time: Waiting.ago(x.last))
            r.local = x
            snap.rows.append(r)
        }
        return snap
    }

    /// Agents (any kind) and background commands a session still runs after its turn, as the hook's minute check
    /// last found them (effort-hook.py background()). Dropped when that check is more than 3 minutes old.
    struct Background {
        let agents: Int
        let bash: Int
        /// The newest one's description.
        let what: String
        /// When the oldest one started.
        let since: Date

        /// "2 agents working · Fix the map", "1 background command · Watch CI".
        var words: String {
            let a = agents == 1 ? "1 agent" : "\(agents) agents", b = bash == 1 ? "1 background command" : "\(bash) background commands"
            let head = agents > 0 && bash > 0 ? "\(a) and \(b) working" : agents > 0 ? "\(a) working" : b
            return head + (what.isEmpty ? "" : " · " + what)
        }
    }

    static func background(_ x: [String: Any]?) -> Background? {
        guard let app = x?["app"] as? [String: Any], let b = app["background"] as? [String: Any],
              let checked = Limit.num(app["checked"]), Date().timeIntervalSince1970 - checked < 180 else { return nil }
        let agents = Int(Limit.num(b["agents"]) ?? 0), bash = Int(Limit.num(b["bash"]) ?? 0)
        guard agents + bash > 0 else { return nil }
        return Background(agents: agents, bash: bash, what: b["what"] as? String ?? "",
                          since: Date(timeIntervalSince1970: Limit.num(b["since"]) ?? checked))
    }

    /// "2 email replies", "2 pull requests", or "3 waits" when they are of more than one kind.
    static func waitsWords(_ ws: [Waits.Wait]) -> String {
        let n = ws.count
        let kinds = Set(ws.map(\.kind))
        guard kinds.count == 1 else { return "\(n) waits" }
        switch ws[0].kind {
        case "email-reply": return "\(n) email replies"
        case "pr": return "\(n) pull requests"
        case "at": return "\(n) set times"
        default: return "\(n) checks"
        }
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
