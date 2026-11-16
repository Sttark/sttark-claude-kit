import Foundation

/// Usage by session: each session's share of the person's Claude Code use on this Mac in a period, and the part its
/// agents did, for the window's Usage page and the phone's Usage tab. usage-scan.py reads the sessions' records on this
/// Mac (only what was added since its last read) and writes usage/by-session.json in the Kit's folder: for each
/// session, day and model, the use in dollars at API prices and the tokens. This reads that file and adds up any
/// period. Each token counts at its model's API price, because the usage limit also counts a larger model as more
/// use; a share is of the person's use, never a percent of the limit, which Anthropic gives only as a total.
enum SessionUsage {
    struct Model { let id: String; let name: String; let priced: Bool }

    struct Session {
        /// "cse:<id>", "sid:<id>", "runs:<folder name>", "kit" or "temp", as the scan groups records.
        let key: String
        /// session (it has a Remote Control link), local (only on this Mac), runs, kit or temp.
        let kind: String
        let cse: String?
        let title: String
        let last: Date?
    }

    /// One session's use on one day with one model.
    struct Cell { let s: Int; let d: Int; let m: Int; let own: Double; let agents: Double; let ownTokens: Double; let agentTokens: Double }

    /// A kind of work and its factor: the hours of a person's work that one hour of Claude at work equals. The scan
    /// sets them (usage-scan.py's WORK; the method is docs/human-work.md).
    struct Kind { let id: String; let name: String; let x: Double }

    /// How long Claude was at work for one session on one day, in one kind of work (waits left out).
    struct Work { let s: Int; let d: Int; let k: Int; let seconds: Double }

    struct Data {
        /// When the scan finished.
        var at: Date?
        /// "2026-11-16", the oldest kept first, through the day of the scan.
        var days: [String] = []
        var models: [Model] = []
        var sessions: [Session] = []
        var cells: [Cell] = []
        /// Agents each session started on each day.
        var agents: [(s: Int, d: Int, n: Int)] = []
        /// Models with no price in usage-scan.py, and their tokens.
        var unpriced: [String: Double] = [:]
        var kinds: [Kind] = []
        var work: [Work] = []
        var empty: Bool { at == nil }
    }

    static var dir: URL { supportDir.appendingPathComponent("usage") }
    static var file: URL { dir.appendingPathComponent("by-session.json") }
    static var script: URL { hooksDir.appendingPathComponent("usage-scan.py") }

    /// The scan's last result; empty before the first scan.
    static func read() -> Data {
        guard let d = try? Foundation.Data(contentsOf: file),
              let j = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] else { return Data() }
        var out = Data(at: Limit.num(j["at"]).map { Date(timeIntervalSince1970: $0) })
        out.days = j["days"] as? [String] ?? []
        out.models = (j["models"] as? [[String: Any]] ?? []).map {
            Model(id: $0["id"] as? String ?? "", name: $0["name"] as? String ?? "", priced: $0["priced"] as? Bool ?? true)
        }
        out.sessions = (j["sessions"] as? [[String: Any]] ?? []).map {
            Session(key: $0["key"] as? String ?? "", kind: $0["kind"] as? String ?? "local",
                    cse: ($0["cse"] as? String).flatMap { $0.isEmpty ? nil : $0 }, title: $0["title"] as? String ?? "",
                    last: Limit.num($0["last"]).flatMap { $0 > 0 ? Date(timeIntervalSince1970: $0) : nil })
        }
        let n = out.sessions.count, days = out.days.count, models = out.models.count
        for r in j["rows"] as? [[Any]] ?? [] where r.count == 7 {
            let v = r.map { Limit.num($0) ?? -1 }
            guard v[0] >= 0, Int(v[0]) < n, v[1] >= 0, Int(v[1]) < days, v[2] >= 0, Int(v[2]) < models else { continue }
            out.cells.append(Cell(s: Int(v[0]), d: Int(v[1]), m: Int(v[2]), own: max(0, v[3]), agents: max(0, v[4]),
                                  ownTokens: max(0, v[5]), agentTokens: max(0, v[6])))
        }
        for r in j["agents"] as? [[Any]] ?? [] where r.count == 3 {
            let v = r.map { Int(Limit.num($0) ?? -1) }
            if v[0] >= 0, v[0] < n, v[1] >= 0, v[1] < days, v[2] > 0 { out.agents.append((v[0], v[1], v[2])) }
        }
        for (k, v) in j["unpriced"] as? [String: Any] ?? [:] { out.unpriced[k] = Limit.num(v) ?? 0 }
        out.kinds = (j["kinds"] as? [[String: Any]] ?? []).compactMap {
            guard let id = $0["id"] as? String, let x = Limit.num($0["x"]), x >= 0 else { return nil }
            return Kind(id: id, name: $0["name"] as? String ?? id, x: x)
        }
        for r in j["work"] as? [[Any]] ?? [] where r.count == 4 {
            let v = r.map { Limit.num($0) ?? -1 }
            guard v[0] >= 0, Int(v[0]) < n, v[1] >= 0, Int(v[1]) < days, v[2] >= 0, Int(v[2]) < out.kinds.count, v[3] > 0 else { continue }
            out.work.append(Work(s: Int(v[0]), d: Int(v[1]), k: Int(v[2]), seconds: v[3]))
        }
        return out
    }

    // MARK: periods

    /// Today, the last 7 days, the last 30 days (today among them), or a range of days. The key is the phone
    /// contract's period (phone/schema/usage.v1.json): today, 7d, 30d or first..last.
    enum Period: Hashable {
        case today, week, month
        case custom(String, String)

        var key: String {
            switch self {
            case .today: return "today"
            case .week: return "7d"
            case .month: return "30d"
            case .custom(let a, let b): return a + ".." + b
            }
        }

        init?(key: String) {
            switch key {
            case "today": self = .today
            case "7d": self = .week
            case "30d": self = .month
            default:
                let parts = key.components(separatedBy: "..")
                guard parts.count == 2, let a = SessionUsage.date(parts[0]), let b = SessionUsage.date(parts[1]) else { return nil }
                self = a <= b ? .custom(parts[0], parts[1]) : .custom(parts[1], parts[0])
            }
        }

        var isCustom: Bool { if case .custom = self { return true } else { return false } }
    }

    /// The first and last day of a period, "2026-11-10" and "2026-11-16", in this Mac's time zone.
    static func span(_ p: Period, now: Date = Date()) -> (from: String, to: String) {
        let today = day(now)
        switch p {
        case .today: return (today, today)
        case .week: return (day(now, plus: -6), today)
        case .month: return (day(now, plus: -29), today)
        case .custom(let a, let b): return (a, b)
        }
    }

    static func dayFormatter() -> DateFormatter {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd"
        return f
    }

    /// "2026-11-16" for a date, `plus` days on.
    static func day(_ d: Date, plus: Int = 0) -> String {
        let c = Calendar.current
        return dayFormatter().string(from: c.date(byAdding: .day, value: plus, to: c.startOfDay(for: d)) ?? d)
    }

    /// The start of a day "2026-11-16", or nil when it is not one.
    static func date(_ day: String) -> Date? {
        guard day.count == 10, let d = dayFormatter().date(from: day) else { return nil }
        return Calendar.current.startOfDay(for: d)
    }

    /// Every day from `from` to `to`.
    static func days(from: String, to: String) -> [String] {
        guard let a = date(from), let b = date(to), a <= b else { return [] }
        var out: [String] = [], d = a
        while d <= b, out.count < 400 {
            out.append(day(d))
            d = Calendar.current.date(byAdding: .day, value: 1, to: d) ?? b.addingTimeInterval(1)
        }
        return out
    }

    // MARK: adding up a period

    /// One session's use in a period.
    struct Line: Identifiable {
        let s: Int
        let session: Session
        var id: String { session.key }
        var own = 0.0, agents = 0.0, tokens = 0.0
        var started = 0
        var byDay: [String: (own: Double, agents: Double)] = [:]
        var byModel: [Int: (usd: Double, tokens: Double)] = [:]
        /// Hours Claude was at work, and the human hours they equal, in all and by kind of work.
        var active = 0.0, human = 0.0
        var humanByKind: [Int: Double] = [:]
        var usd: Double { own + agents }
    }

    struct Report {
        var from = "", to = ""
        /// The biggest first.
        var lines: [Line] = []
        var usd = 0.0, agents = 0.0, tokens = 0.0
        /// Hours Claude was at work in the period, and the human hours they equal.
        var active = 0.0, human = 0.0
        /// All use each day, for a day's part of the whole.
        var byDay: [String: Double] = [:]
        var dayList: [String] { SessionUsage.days(from: from, to: to) }
        func share(_ x: Double) -> Double { usd > 0 ? x / usd : 0 }
    }

    static func report(_ d: Data, from: String, to: String) -> Report {
        var r = Report(from: from, to: to)
        let inside = Set(d.days.indices.filter { d.days[$0] >= from && d.days[$0] <= to })
        var lines: [Int: Line] = [:]
        for c in d.cells where inside.contains(c.d) {
            var l = lines[c.s] ?? Line(s: c.s, session: d.sessions[c.s])
            l.own += c.own
            l.agents += c.agents
            l.tokens += c.ownTokens + c.agentTokens
            let day = d.days[c.d]
            let x = l.byDay[day] ?? (0, 0)
            l.byDay[day] = (x.own + c.own, x.agents + c.agents)
            let m = l.byModel[c.m] ?? (0, 0)
            l.byModel[c.m] = (m.usd + c.own + c.agents, m.tokens + c.ownTokens + c.agentTokens)
            lines[c.s] = l
            r.byDay[day, default: 0] += c.own + c.agents
        }
        for a in d.agents where inside.contains(a.d) { lines[a.s]?.started += a.n }
        for w in d.work where inside.contains(w.d) {
            let h = w.seconds / 3600 * d.kinds[w.k].x
            r.active += w.seconds / 3600
            r.human += h
            lines[w.s]?.active += w.seconds / 3600
            lines[w.s]?.human += h
            lines[w.s]?.humanByKind[w.k, default: 0] += h
        }
        r.lines = lines.values.filter { $0.usd > 0 }.sorted { ($0.usd, $1.session.title) > ($1.usd, $0.session.title) }
        r.usd = r.lines.reduce(0) { $0 + $1.usd }
        r.agents = r.lines.reduce(0) { $0 + $1.agents }
        r.tokens = r.lines.reduce(0) { $0 + $1.tokens }
        return r
    }

    // MARK: reading the records again

    private static var running = false
    private static var waiting: [() -> Void] = []

    /// Runs usage-scan.py when its result is more than `olderThan` seconds old, off the main thread and one at a time,
    /// then calls `done` on the main thread (also when nothing was due). The scan reads only what the records gained.
    static func refresh(olderThan: TimeInterval, done: (() -> Void)? = nil) {
        if let done { waiting.append(done) }
        guard !running else { return }
        running = true
        DispatchQueue.global(qos: .utility).async {
            let (code, said) = Updater.run("/usr/bin/python3", [script.path, "--if-older", String(Int(olderThan))])
            if code != 0 { logLine("usage", "scan failed: " + said.split(separator: "\n").suffix(2).joined(separator: " ").prefix(300)) }
            DispatchQueue.main.async {
                running = false
                let calls = waiting
                waiting = []
                calls.forEach { $0() }
            }
        }
    }

    // MARK: words

    /// "8.1 billion", "173 million", "12 thousand", "640".
    static func tokens(_ n: Double) -> String {
        if n >= 1e9 { return String(format: "%.1f billion", n / 1e9) }
        if n >= 1e8 { return String(format: "%.0f million", n / 1e6) }
        if n >= 1e6 { return String(format: "%.1f million", n / 1e6) }
        if n >= 1e3 { return String(format: "%.0f thousand", n / 1e3) }
        return String(format: "%.0f", n)
    }

    /// "$3,106" from $100, else "$8.79".
    static func dollars(_ x: Double) -> String {
        if x >= 100 {
            let f = NumberFormatter()
            f.numberStyle = .decimal
            f.maximumFractionDigits = 0
            return "$" + (f.string(from: NSNumber(value: x.rounded())) ?? String(Int(x.rounded())))
        }
        return String(format: "$%.2f", x)
    }

    /// A share as the list shows it: "28.3%", "<0.1%".
    static func percent1(_ x: Double) -> String { x > 0 && x < 0.001 ? "<0.1%" : String(format: "%.1f%%", x * 100) }

    /// A share in words: "18%", "4.5%", "<0.1%".
    static func percent(_ x: Double) -> String {
        x >= 0.0995 ? String(format: "%.0f%%", x * 100) : x >= 0.000995 ? String(format: "%.1f%%", x * 100) : x > 0 ? "<0.1%" : "0%"
    }

    // MARK: human work in words (phone/src/view/human.ts says the same; the examples are in tools/usage-words-test.swift)

    /// "3", "2.5" under 10 (round half up, no ".0"); "20", "1,240" from 10.
    static func num(_ n: Double) -> String {
        if n < 10 {
            let r = (n * 10).rounded() / 10
            return r == r.rounded() ? String(Int(r)) : String(format: "%.1f", r)
        }
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.maximumFractionDigits = 0
        f.locale = Locale(identifier: "en_US")
        return f.string(from: NSNumber(value: n.rounded())) ?? String(Int(n.rounded()))
    }

    /// What one person would take for `h` hours of work, at 8 hours a day, 40 a week, 4.33 weeks a month:
    /// "1 person for 15 minutes", "1 person for 2.5 days", "1 person for 4.7 months".
    static func personWords(_ h: Double) -> String {
        let (n, unit): (Double, String)
        if (h * 60).rounded() < 60 { n = max(1, (h * 60).rounded()); unit = "minute" }
        else if h < 8 { n = h; unit = "hour" }
        else if h < 80 { n = h / 8; unit = "day" }
        else if h < 520 { n = h / 40; unit = "week" }
        else if h < 4160 { n = h / 173.2; unit = "month" }
        else { n = h / 2080; unit = "year" }
        let shown = num(n)
        return "1 person for \(shown) \(unit)\(shown == "1" ? "" : "s")"
    }

    /// Mondays to Fridays from `from` to `to`, both in, at least 1.
    static func weekdays(from: String, to: String) -> Int {
        let c = Calendar(identifier: .gregorian)
        return max(1, days(from: from, to: to).filter { d in date(d).map { ![1, 7].contains(c.component(.weekday, from: $0)) } ?? false }.count)
    }

    /// The period as the picker names it, after a number of people: "today", "over these 7 days", "from Nov 2 to
    /// Nov 9", "on Wed, Nov 4".
    static func periodWords(_ p: Period, from: String, to: String) -> String {
        switch p {
        case .today: return "today"
        case .week: return "over these 7 days"
        case .month: return "over these 30 days"
        case .custom: return from == to ? "on " + dayWords(from, weekday: true) : "from " + dayWords(from) + " to " + dayWords(to)
        }
    }

    /// How many people full time, 8 hours each weekday, the work of `h` hours equals in a period: "≈ 20 people full
    /// time over these 7 days", "less than 1 person full time today".
    static func peopleWords(_ h: Double, _ p: Period, from: String, to: String) -> String {
        let n = h / (8 * Double(weekdays(from: from, to: to)))
        let when = periodWords(p, from: from, to: to)
        if n < 1 { return "less than 1 person full time " + when }
        let shown = num(n)
        return "≈ \(shown) \(shown == "1" ? "person" : "people") full time " + when
    }

    /// "182 h", "2.5 h", "< 0.1 h".
    static func hoursWords(_ h: Double) -> String { h < 0.1 ? "< 0.1 h" : num(h) + " h" }

    /// The ⓘ note: how the estimate is made, with the factors the scan sent.
    static func humanNote(_ kinds: [Kind]) -> String {
        let f = kinds.map { $0.name.lowercased() + " " + num($0.x) }.joined(separator: ", ")
        return "An estimate. The Kit counts the hours Claude was at work, its agents too: the model writing and the tools "
            + "it ran. Waits do not count: for you, at the usage limit, for checks and timers. Each hour counts as the hours "
            + "a person needs for that kind of work" + (f.isEmpty ? "" : ": " + f) + ". Full time is 8 hours a day, 5 days a week."
    }

    /// "Nov 16", "Mon, Nov 16".
    static func dayWords(_ day: String, weekday: Bool = false) -> String {
        guard let d = date(day) else { return day }
        let f = DateFormatter()
        f.dateFormat = weekday ? "EEE, MMM d" : "MMM d"
        return f.string(from: d)
    }

    /// "Nov 10 to Nov 16", or "Mon, Nov 16" for one day.
    static func spanWords(from: String, to: String) -> String {
        from == to ? dayWords(from, weekday: true) : dayWords(from) + " to " + dayWords(to)
    }

    /// When a session was last active: "9:43 AM" today, else "Nov 15".
    static func lastWords(_ d: Date?) -> String {
        guard let d else { return "" }
        let f = DateFormatter()
        f.dateFormat = Calendar.current.isDateInToday(d) ? "h:mm a" : "MMM d"
        return f.string(from: d)
    }
}
