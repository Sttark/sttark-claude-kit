import Foundation

/// "Use credits at the usage limit" and the sessions waiting for a reset, shared with limit-hook.py through
/// the state file (limit_credits_all, limit_credits, limit_pauses) and its usage cache (usage.json).
enum Limit {
    struct Waiting {
        let id: String
        let title: String
        let limit: String
        let since: Date
        let until: Date
    }

    /// Off by default: at the limit, sessions wait for the reset. On: they go on with usage credits.
    static var creditsAll: Bool { State.read()["limit_credits_all"] as? Bool ?? false }

    static func setCreditsAll(_ on: Bool) {
        State.change { $0["limit_credits_all"] = on }
        note(on ? "usage limit: every session uses credits at the limit" : "usage limit: sessions wait for the reset")
    }

    /// One session goes on with usage credits until its limit resets.
    static func useCredits(_ w: Waiting) {
        State.change { s in
            var c = s["limit_credits"] as? [String: Double] ?? [:]
            c[w.id] = w.until.timeIntervalSince1970
            s["limit_credits"] = c.filter { $0.value > Date().timeIntervalSince1970 }
        }
        note("usage limit: \(w.title) uses credits until \(clock(w.until)), from the menu")
    }

    /// Sessions waiting now, longest first. A row whose hook process is gone (the session closed) is dropped.
    static var waiting: [Waiting] {
        let all = State.read()["limit_pauses"] as? [String: [String: Any]] ?? [:]
        var gone: [String] = []
        let list: [Waiting] = all.compactMap { id, x in
            let pid = (x["pid"] as? NSNumber)?.int32Value ?? 0
            guard pid > 0, kill(pid, 0) == 0 else { gone.append(id); return nil }
            return Waiting(id: id, title: x["title"] as? String ?? "Session", limit: x["limit"] as? String ?? "usage",
                           since: Date(timeIntervalSince1970: x["since"] as? Double ?? 0),
                           until: Date(timeIntervalSince1970: x["until"] as? Double ?? 0))
        }.sorted { $0.since < $1.since }
        if !gone.isEmpty {
            State.change { s in
                var p = s["limit_pauses"] as? [String: Any] ?? [:]
                for id in gone { p.removeValue(forKey: id) }
                s["limit_pauses"] = p
            }
        }
        return list
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
