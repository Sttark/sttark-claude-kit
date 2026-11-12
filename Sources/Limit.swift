import Foundation

/// "Use credits at the usage limit", each session's own setting for it, and the sessions holding now, shared with
/// limit-hook.py through the state file (limit_credits_all, limit_credits, limit_modes, limit_pauses) and its usage
/// cache (usage.json).
enum Limit {
    /// A session's own setting (limit_modes). Follow the menu is stored as no entry.
    enum Mode: Equatable {
        case follow, credits, hold(Int)

        /// As the log and the hook write it.
        var words: String {
            switch self {
            case .follow: return "follow the menu"
            case .credits: return "always use credits"
            case .hold(let n): return "never use credits; hold at \(n)%"
            }
        }

        /// On the session's row, after its level. Nil for Follow the menu.
        var tag: String? {
            switch self {
            case .follow: return nil
            case .credits: return "Credits"
            case .hold(let n): return "Hold \(n)%"
            }
        }
    }

    /// The hold percentages the menu offers; the hook and claude-limit-mode take any from 1 to 100.
    static let holdChoices = [50, 60, 70, 80, 90, 100]
    static let defaultHold = 80

    /// A session as the hooks know it: Claude Code's session id (its transcript's name) and its Remote Control id.
    struct Target {
        let sid: String
        let cse: String
        let title: String
        /// The id the log shows, as the hook writes it.
        var short: String { Limit.short(sid: sid, cse: cse) }
    }

    /// The id the log shows for a session, the hook's rule: the first 8 characters of its session id, or, for a
    /// session known only by its Remote Control id, the 8 characters after "cse_".
    static func short(sid: String, cse: String) -> String {
        if !sid.isEmpty { return String(sid.prefix(8)) }
        return String((cse.hasPrefix("cse_") ? cse.dropFirst(4) : Substring(cse)).prefix(8))
    }

    struct Waiting {
        /// The session's id. limit_pauses keys a held call "<session id>/<tool call id>" (with `agent` set for an
        /// agent's call), and the wait command's own loop "<session id>" or "<session id>/<agent id>".
        let sid: String
        let cse: String
        let title: String
        let limit: String
        let since: Date
        let until: Date
        /// "hold" for a session set to Never use credits; otherwise a wait at the usage limit.
        let mode: String
        /// The percentage it holds at (100 for a wait at the limit), and the limit's percent when it began.
        let at: Int
        let percent: Int?
        /// How many of its subagents and background agents hold too (distinct agent ids).
        let agents: Int
        var hold: Bool { mode == "hold" }
        var target: Target { Target(sid: sid, cse: cse, title: title) }
    }

    /// Off by default: at the limit, sessions wait for the reset. On: they go on with usage credits.
    static var creditsAll: Bool { State.read()["limit_credits_all"] as? Bool ?? false }

    static func setCreditsAll(_ on: Bool) {
        State.change { $0["limit_credits_all"] = on }
        logLine("limit", on ? "credits every session uses credits at the limit, except one set to hold (menu)"
                            : "credits every session waits at the limit, except one set to use credits (menu)")
    }

    /// One session goes on with usage credits until its limit resets.
    static func useCredits(_ w: Waiting) {
        State.change { s in
            // keep every other session's entry as the hooks wrote it (a number), drop the ones that have passed
            var c: [String: Any] = [:]
            for (k, v) in s["limit_credits"] as? [String: Any] ?? [:] {
                if let t = (v as? NSNumber)?.doubleValue, t > Date().timeIntervalSince1970 { c[k] = t }
            }
            c[w.sid] = w.until.timeIntervalSince1970
            s["limit_credits"] = c
        }
        logLine("limit", "credits \(w.target.short) uses credits until \(clock(w.until)) (menu)")
    }

    // MARK: each session's own setting

    /// True when a limit_modes entry belongs to the session: by its key, its session id or its Remote Control id.
    static func matches(_ key: String, _ v: [String: Any], _ t: Target) -> Bool {
        if (!t.sid.isEmpty && (key == t.sid || v["sid"] as? String == t.sid))
            || (!t.cse.isEmpty && (key == t.cse || v["cse"] as? String == t.cse)) { return true }
        return false
    }

    /// The session's setting. With several entries for it (set under different ids), the newest wins.
    static func mode(_ t: Target, in s: [String: Any]? = nil) -> Mode {
        let all = dicts((s ?? State.read())["limit_modes"])
        let mine = all.filter { matches($0.key, $0.value, t) }.map(\.value)
        guard let v = mine.max(by: { num($0["set_at"]) ?? 0 < num($1["set_at"]) ?? 0 }) else { return .follow }
        switch v["mode"] as? String {
        case "credits": return .credits
        case "hold":
            let n = num(v["at"]).map { Int($0) } ?? Int((v["at"] as? String ?? "").trimmingCharacters(in: .whitespaces)) ?? defaultHold
            return .hold(min(100, max(1, n)))
        default: return .follow
        }
    }

    /// The dictionaries in a state value, by key. Anything else is left out, so one bad entry hides nothing else.
    static func dicts(_ v: Any?) -> [String: [String: Any]] {
        var out: [String: [String: Any]] = [:]
        for (k, x) in v as? [String: Any] ?? [:] { if let d = x as? [String: Any] { out[k] = d } }
        return out
    }

    /// A number as JSON gives it (Python writes ints and floats); nil for anything else.
    static func num(_ v: Any?) -> Double? {
        guard let n = v as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
        return n.doubleValue
    }

    /// Sets the session's setting from the menu, under its Remote Control id when it has one, and logs the change.
    static func setMode(_ m: Mode, for t: Target) {
        var changed = false
        State.change { s in
            guard mode(t, in: s) != m else { return }
            changed = true
            var all = s["limit_modes"] as? [String: Any] ?? [:]
            for (k, v) in all where matches(k, v as? [String: Any] ?? [:], t) { all.removeValue(forKey: k) }
            var e: [String: Any] = ["by": "menu", "set_at": Date().timeIntervalSince1970, "title": t.title]
            if !t.sid.isEmpty { e["sid"] = t.sid }
            if !t.cse.isEmpty { e["cse"] = t.cse }
            switch m {
            case .follow: break
            case .credits: e["mode"] = "credits"; all[t.cse.isEmpty ? t.sid : t.cse] = e
            case .hold(let n): e["mode"] = "hold"; e["at"] = n; all[t.cse.isEmpty ? t.sid : t.cse] = e
            }
            s["limit_modes"] = all
        }
        if changed { logLine("limit", "mode   \(t.short) \(m.words) (menu)") }
    }

    // MARK: sessions holding now

    /// Sessions holding now, one row per session, longest first. A row whose process is gone (the session closed,
    /// or its turn was stopped) is dropped.
    static var waiting: [Waiting] {
        let all = dicts(State.read()["limit_pauses"])
        var gone: [String: Int32] = [:]   // key: the dead process it named
        var rows: [(key: String, agent: String, w: Waiting)] = []
        for (key, x) in all {
            let pid = num(x["pid"]).map { Int32(clamping: Int($0)) } ?? 0
            guard pid > 0, kill(pid, 0) == 0 else { gone[key] = pid; continue }
            let named = (x["sid"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            let sid = named.isEmpty ? String(key.split(separator: "/").first ?? "") : named
            guard !sid.isEmpty else { continue }
            let agent = x["agent"] as? String ?? ""   // null or missing: the session's own call
            let mode = x["mode"] as? String ?? "follow"
            let w = Waiting(sid: sid, cse: x["cse"] as? String ?? "", title: x["title"] as? String ?? "Session",
                            limit: x["limit"] as? String ?? "usage",
                            since: Date(timeIntervalSince1970: num(x["since"]) ?? 0),
                            until: Date(timeIntervalSince1970: num(x["until"]) ?? 0),
                            mode: mode, at: num(x["at"]).map { Int($0) } ?? (mode == "hold" ? defaultHold : 100),
                            percent: num(x["percent"]).map { Int($0) }, agents: 0)
            rows.append((key, agent, w))
        }
        if !gone.isEmpty {
            State.change { s in
                var p = s["limit_pauses"] as? [String: Any] ?? [:]
                for (key, pid) in gone {   // only the dead row itself: a hook may have put a new one there since
                    let now = num((p[key] as? [String: Any])?["pid"]).map { Int32(clamping: Int($0)) } ?? 0
                    if now == pid { p.removeValue(forKey: key) }
                }
                s["limit_pauses"] = p
            }
        }
        // one row per session: the session's own hold when it has one, else its first agent's
        let bySession = Dictionary(grouping: rows, by: { $0.w.sid })
        return bySession.values.compactMap { group -> Waiting? in
            let sorted = group.sorted { ($0.agent.isEmpty ? 0 : 1, $0.w.since) < ($1.agent.isEmpty ? 0 : 1, $1.w.since) }
            guard let first = sorted.first?.w else { return nil }
            let agents = Set(group.map(\.agent).filter { !$0.isEmpty }).count
            return Waiting(sid: first.sid, cse: first.cse, title: first.title, limit: first.limit, since: first.since,
                           until: group.map(\.w.until).max() ?? first.until, mode: first.mode, at: first.at,
                           percent: first.percent, agents: agents)
        }.sorted { $0.since < $1.since }
    }

    /// The limit reached now, from the hook's last usage read: its name and reset time. Nil under the limit,
    /// with no usage credits on the account (Claude Code stops by itself then), or with no recent read.
    static var reached: (name: String, until: Date)? {
        let f = supportDir.appendingPathComponent("usage.json")
        guard let c = (try? JSONSerialization.jsonObject(with: Data(contentsOf: f))) as? [String: Any],
              let at = c["at"] as? Double, Date().timeIntervalSince1970 - at < 15 * 60,
              let u = c["usage"] as? [String: Any] else { return nil }
        let x = u["extra_usage"] as? [String: Any] ?? [:]
        guard x["is_enabled"] as? Bool ?? false, !(x["spend_limit_reached"] as? Bool ?? false) else { return nil }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let names = ["session": "5-hour", "weekly_all": "weekly"]
        var best: (String, Date)? = nil
        for l in u["limits"] as? [[String: Any]] ?? [] {
            guard ((l["percent"] as? Double) ?? 0) >= 100,
                  (l["scope"] as? [String: Any]) == nil,   // a model's own limit only holds sessions on that model
                  let r = l["resets_at"] as? String,
                  let d = iso.date(from: r) ?? ISO8601DateFormatter().date(from: r), d > Date() else { continue }
            let name = names[l["kind"] as? String ?? ""] ?? "usage"
            if best == nil || d > best!.1 { best = (name, d) }
        }
        return best
    }

    /// "6:00 PM", or "Sat 2:00 AM" when it isn't today. Rounded to the minute, as the hook does.
    static func clock(_ d: Date) -> String {
        let t = Date(timeIntervalSince1970: (d.timeIntervalSince1970 / 60).rounded() * 60)
        let f = DateFormatter()
        f.dateFormat = Calendar.current.isDateInToday(t) ? "h:mm a" : "EEE h:mm a"
        return f.string(from: t)
    }
}
