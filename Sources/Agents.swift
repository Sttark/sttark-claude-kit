import Foundation

/// The agents a session started, as the effort hook records them in the state file: `sessions[<cse>].agents`, a list of
/// {tool_use_id, agent_id, type ("fork" for a fork), desc, level (a LEVELS key), set_by ("kit" or "session"), reason,
/// started_at, done_at (null while it runs)}. The Sessions page shows them under their session, and the session's panel
/// shows each one's level with its reason.
enum Agents {
    struct Item: Identifiable, Equatable {
        /// The Agent call's tool_use_id, else the agent's own id: one key for each agent.
        let id: String
        /// The agent's type as Claude Code names it (Explore, general-purpose, …); "fork" for a fork.
        let type: String
        let desc: String
        /// The level it runs at: a key of `levelNames` ("low" … "max"), or "" when the Kit has none. A fork has no level
        /// of its own: while it runs, this is its session's level now.
        let level: String
        /// "kit": the Kit picked the level. "session": the Kit picked none (Auto effort off, Manual, no check). A fork has
        /// an entry only when the Kit let it run (Auto effort off, Manual): the Kit stops every other fork. Entries from
        /// before that can still show a fork with "kit" (the Kit raised the session for it) for up to 7 days.
        let setBy: String
        let reason: String
        let started: Date
        /// When it finished; nil while it runs.
        let done: Date?
        /// The level it started at, as the hook recorded it; for a fork that runs, it can differ from `level`.
        var startLevel = ""
        /// The Kit saw no end of it, and the session stopped its work more than 30 min ago: it shows as finished, with
        /// no time, since the Kit does not know when it ended.
        var lost = false

        var running: Bool { done == nil && !lost }
        var isFork: Bool { type.lowercased() == "fork" }
        /// The type as the window shows it: "Fork" for a fork, else Claude Code's own name for it.
        var typeName: String { isFork ? "Fork" : type.isEmpty ? "Agent" : type }
        var levelName: String? { levelNames[level] }

        /// The time column of its row: "running 6 min", "done 12 min ago", or "ended" when the Kit saw no end.
        var timeWords: String {
            if lost { return "ended" }
            guard let d = done else {
                let a = Waiting.ago(started)
                return a == "just now" ? "started just now" : "running " + a
            }
            let a = Waiting.ago(d)
            return a == "just now" ? "done just now" : "done \(a) ago"
        }

        /// The same in a narrow list: "31 min", "32 min ago", "ended".
        var shortTime: String {
            if lost { return "ended" }
            let a = Waiting.ago(done ?? started)
            return done == nil || a == "just now" ? a : a + " ago"
        }

        /// Why it runs at its level, in plain words, for the session's panel.
        var why: String {
            let r = reason.trimmingCharacters(in: .whitespacesAndNewlines)
            let said = r.isEmpty ? "" : (r.prefix(1).uppercased() + r.dropFirst()) + (r.hasSuffix(".") ? "" : ".")
            if isFork {
                // the fork took the session's level as it was (Auto effort off, Manual); older entries: the Kit picked the
                // session's level for it (and raised the session to it when it was lower), with the Kit's note on why
                let at = levelName.map { "the session's level, \($0)" } ?? "the session's level"
                let start = levelNames[startLevel]
                let moved = start != nil && startLevel != level
                let head = moved ? "Runs at \(at). It started at \(start!)" + (setBy == "kit" ? ", the level the Kit picked for it." : ".")
                    : setBy == "kit" && levelName != nil ? "Runs at \(at), the level the Kit picked for it." : "Runs at \(at)."
                var note = said
                for same in ["A fork runs at the session's level.", "A fork runs at the session level."] where note.hasPrefix(same) {
                    note = String(note.dropFirst(same.count)).trimmingCharacters(in: .whitespaces)
                }
                for (k, name) in levelNames {   // the hook's "It needs high: …" names the level as the window does
                    note = note.replacingOccurrences(of: "needs \(k)", with: "needs \(name)")
                }
                return [head, note].filter { !$0.isEmpty }.joined(separator: " ")
            }
            if setBy == "session" {
                switch r.lowercased() {
                case "set in the call": return "The session set this level in its call."
                case "set by its definition": return "The agent's own definition sets this level."
                default: return r.isEmpty ? "The Kit did not pick this level." : "The Kit did not pick this level. " + said
                }
            }
            guard let l = levelName else { return said }
            return r.isEmpty ? "The Kit picked \(l) when it started." : "Why \(l): " + said
        }

        /// Its tip on the Sessions page.
        var tip: String {
            let state = lost ? "The Kit did not see it end. The session stopped its work more than 30 min ago."
                : running ? "It runs now." : "It finished."
            let level = isFork ? "A fork runs at the session's level, also when the session's level changes."
                : levelName.map { "It keeps \($0) until it ends." } ?? ""
            return [desc.isEmpty ? typeName : desc, state, level].filter { !$0.isEmpty }.joined(separator: " ")
        }
    }

    /// After this long with no work in its session, an agent the Kit saw no end of shows as finished (a lost
    /// SubagentStop).
    static let lostAfter: TimeInterval = 30 * 60
    /// A session's finished agents that show on the list as rows of their own; more than this show as one row,
    /// "8 finished", that opens them.
    static let inline = 2

    /// The agents in one session's state, running first (the oldest first), then finished (the newest first). None when
    /// the state has no `agents` list. `busy`: the session works now (a turn, agents or background commands, or it holds
    /// at the usage limit), so an agent with no end still runs. `lastActive`: when the session last worked. A fork that
    /// runs shows the session's level now (`x["level"]`), since a fork runs at it.
    static func read(_ x: [String: Any]?, busy: Bool, lastActive: Date, now: Date = Date()) -> [Item] {
        guard let list = x?["agents"] as? [[String: Any]] else { return [] }
        let stopped = !busy && now.timeIntervalSince(lastActive) > lostAfter
        let sessionLevel = key(x?["level"] as? String ?? "")
        var out: [Item] = []
        for (i, a) in list.enumerated() {
            let id = (a["tool_use_id"] as? String).flatMap(\.nilIfEmpty) ?? (a["agent_id"] as? String).flatMap(\.nilIfEmpty) ?? "agent-\(i)"
            let started = Limit.num(a["started_at"]).map { Date(timeIntervalSince1970: $0) } ?? lastActive
            let done = Limit.num(a["done_at"]).map { Date(timeIntervalSince1970: $0) }
            let type = a["type"] as? String ?? "", recorded = key(a["level"] as? String ?? "")
            let runs = done == nil && !stopped
            var item = Item(id: id, type: type, desc: (a["desc"] as? String ?? "").trimmingCharacters(in: .whitespaces),
                            level: runs && type.lowercased() == "fork" && !sessionLevel.isEmpty ? sessionLevel : recorded,
                            setBy: a["set_by"] as? String ?? "", reason: a["reason"] as? String ?? "", started: started, done: done)
            item.startLevel = recorded
            item.lost = done == nil && stopped
            out.append(item)
        }
        return sorted(out)
    }

    /// Running first, the oldest first; then finished, the newest first (an agent with no end time last).
    static func sorted(_ items: [Item]) -> [Item] {
        let run = items.filter(\.running).sorted { ($0.started, $0.id) < ($1.started, $1.id) }
        let fin = items.filter { !$0.running }.sorted {
            let a = $0.done ?? .distantPast, b = $1.done ?? .distantPast
            return a != b ? a > b : ($0.started, $0.id) > ($1.started, $1.id)
        }
        return run + fin
    }

    /// A level as the window keys it: "Max" or "MAX" is "max", "Extra" is "xhigh". "" when it is not a level.
    static func key(_ s: String) -> String {
        let k = s.lowercased().trimmingCharacters(in: .whitespaces)
        if k == "extra" { return "xhigh" }
        return levelNames[k] != nil ? k : ""
    }

    /// What the Sessions page lists under a session: every running agent, then the finished ones while there are at most
    /// `inline` of them or the person opened them. `finished`: the count for the "N finished" row, nil when there is
    /// no such row (it shows whenever more than `inline` finished).
    static func listed(_ items: [Item], open: Bool) -> (rows: [Item], finished: Int?) {
        let run = items.filter(\.running), fin = items.filter { !$0.running }
        if fin.count <= inline { return (run + fin, nil) }
        return (open ? run + fin : run, fin.count)
    }

    /// "2 running · 8 finished", "3 running", "1 finished".
    static func counts(_ items: [Item]) -> String {
        let r = items.filter(\.running).count, f = items.count - r
        return [r > 0 ? "\(r) running" : "", f > 0 ? "\(f) finished" : ""].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}
