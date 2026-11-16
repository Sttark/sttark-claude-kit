import CryptoKit
import Foundation
import SystemConfiguration

/// Kit on your phone, the Mac side (phone/DESIGN.md, sections 3, 13 and 14): what the Kit sends to the phone server (PhoneLink.address), and
/// when. Each payload is what phone/schema says, field for field: the snapshot holds the rows of the four groups the
/// phone shows (Needs you, Claude working, Waiting on someone else, Held at usage limit), the usage and the version of
/// the archived list; the archived list itself goes up only when the server asks for it, and so does the Usage by
/// session list of a period (names, ids and numbers only).
///
/// No payload holds a prompt, a reply, a transcript line, a file's contents, a path, a wait's target, a check script
/// or its output, a check-prompt's question or a Reach me by address. The rows come from `Inbox.snapshot()`, the
/// window's own rows, and every field is picked by name; tools/phone-test.swift plants each of those things in sample
/// state and fails if one shows. PhoneLink.swift links the Mac, keeps the socket and sends what this builds.
enum Phone {
    /// The groups the phone shows, in its order, with the schema's name for each. Idle and On this Mac only stay here.
    static let groups: [(Inbox.Group, String)] = [(.needs, "needs_you"), (.working, "working"), (.waits, "waiting"), (.held, "held")]
    static let levels: Set<String> = ["low", "medium", "high", "xhigh", "max"]
    static let waitKinds: Set<String> = ["pr", "email-reply", "at", "check-script", "check-prompt"]

    // MARK: this Mac

    /// This Mac as the snapshot names it.
    struct Mac {
        var name: String
        var kit: String
        var tz: String
        /// A short hash of the Claude Code login (`Phone.account`), never the address.
        var account: String

        private static var cache: (mac: Mac, at: Date)?

        /// Read once every 10 minutes: the Mac's name (System Settings > General > Sharing), the Kit version, the time
        /// zone and the login.
        static var current: Mac {
            if let c = cache, -c.at.timeIntervalSinceNow < 600 { return c.mac }
            let name = (SCDynamicStoreCopyComputerName(nil, nil) as String?) ?? Host.current().localizedName ?? "Mac"
            let m = Mac(name: name, kit: Updater.version, tz: TimeZone.current.identifier, account: Phone.account(Reach.loginEmail))
            cache = (m, Date())
            return m
        }
    }

    /// The same short hash of a Claude Code login on each of the person's Macs, so the phone can show one usage block
    /// per account. A Mac with no login gets the hash of an empty one.
    static func account(_ email: String) -> String {
        hash(Data(("kit-account-v1:" + email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()).utf8))
    }

    /// The first 16 hex digits of a SHA-256.
    static func hash(_ d: Data) -> String { SHA256.hash(data: d).prefix(8).map { String(format: "%02x", $0) }.joined() }

    // MARK: the snapshot

    /// The `snapshot` payload (phone/schema/snapshot.v1.json), from the Kit's state now. `now` is its `at`.
    static func snapshot(now: Date = Date(), mac: Mac = .current) -> [String: Any] {
        let state = State.read()
        let snap = Inbox.snapshot()
        var rows: [[String: Any]] = []
        for (g, name) in groups {
            for r in snap.rows(g) { if let x = row(r, group: name, state: state) { rows.append(x) } }
        }
        let usage = Usage.read()
        let list = archived(state)
        let kit = cut(mac.kit, 20), zone = cut(mac.tz, 64)
        return [
            "v": 1,
            "at": Int(now.timeIntervalSince1970.rounded()),
            "mac": [
                "name": cut(mac.name, 80).nilIfEmpty ?? "Mac",
                "kit": versionLike(kit) ? kit : "0",
                "tz": zoneLike(zone) ? zone : "UTC",
                "account": mac.account.count >= 16 && mac.account.count <= 32 && mac.account.allSatisfy(hexDigits.contains) ? mac.account : account(""),
            ] as [String: Any],
            "flags": ["paused": snap.paused, "credits_all": snap.creditsAll],
            "reach": Reach.ways.filter(snap.reach.ways.contains),
            "usage": [
                "at": time(usage.at),
                "bars": usage.bars.prefix(8).map { b -> [String: Any] in
                    ["kind": kindName(b.kind), "name": cut(b.name, 60), "percent": clamp(b.percent, 0, 1000), "resets": time(b.resets)]
                },
                "reached": Limit.reached.map { ["name": cut(limitName($0.name), 60), "until": time($0.until)] as [String: Any] } ?? NSNull(),
            ] as [String: Any],
            "rows": Array(rows.prefix(200)),
            "archived_rev": list?.rev ?? NSNull(),
            "archived_count": list?.items.count ?? 0,
        ]
    }

    /// One row of the window's Sessions page, as the phone gets it. Nil for a row with no Remote Control id (a held or
    /// waiting session that runs only in Terminal): the schema needs that id and its claude.ai link for every row.
    static func row(_ r: Inbox.Row, group: String, state: [String: Any]) -> [String: Any]? {
        guard let rid = id(r.id, max: 128), let cse = id(r.target?.cse) else { return nil }
        let raw = state["waits"] as? [String: [String: Any]] ?? [:]
        // a wait's row says what it waits for in safe words (the window's words can hold the question or the PR)
        let sub = r.group != .waits ? r.sub : r.waits.count > 1 ? Inbox.waitsWords(r.waits) : r.wait.map { what($0, raw[$0.id]) } ?? r.sub
        var strong = r.subStrong.trimmingCharacters(in: .whitespacesAndNewlines)
        if r.group == .waits, !r.subWarn, r.waits.count == 1, let w = r.wait, !w.from.isEmpty {   // the window's "from <sender>"
            strong = sender(w.from).isEmpty ? "" : "from " + sender(w.from)
        }
        var x: [String: Any] = [
            "id": rid, "cse": cse,
            "sid": id(r.target?.sid, max: 64, chars: sidChars).map { $0 as Any } ?? NSNull(),
            "group": group,
            "title": cut(r.title),
            "sub": cut(sub),
            "sub_strong": strong.isEmpty || r.subWarn ? NSNull() : cut(strong),
            "sub_warn": strong.isEmpty || !r.subWarn ? NSNull() : cut(strong),
            "late": r.late,
            "time_at": time(r.timeAt),
            "url": link(r.url, cse: cse),
            "session": NSNull(), "background": NSNull(), "hold": NSNull(),
            "waits": r.waits.compactMap { wait($0, raw[$0.id]) }.prefix(20).map { $0 },
        ]
        if let s = r.session {
            x["session"] = [
                "level": levels.contains(s.level) ? s.level : NSNull(),
                "manual": s.manual,
                "reason": label(s.reason),
                "needs_you": s.needsYou,
                "why": label(s.why),
                "waiting_since": time(s.waitingSince),
                "turn_at": r.group == .working && r.background == nil ? time(r.timeAt) : NSNull(),
            ] as [String: Any]
        }
        if let b = r.background {
            x["background"] = ["agents": clamp(b.agents, 0, 100), "bash": clamp(b.bash, 0, 100), "what": cut(b.what), "since": time(b.since)] as [String: Any]
        }
        if let h = r.hold {
            x["hold"] = ["hold": h.hold, "at": (1...100).contains(h.at) ? h.at : NSNull(),
                         "percent": h.percent.map { clamp($0, 0, 1000) as Any } ?? NSNull(), "limit": cut(limitName(h.limit), 60),
                         "since": time(h.since), "until": time(h.until), "agents": clamp(h.agents, 0, 100)] as [String: Any]
        }
        switch r.target.map({ Limit.mode($0, in: state) }) ?? .follow {
        case .follow: x["limit_mode"] = ["mode": "follow", "at": NSNull()]
        case .credits: x["limit_mode"] = ["mode": "credits", "at": NSNull()]
        case .hold(let n): x["limit_mode"] = ["mode": "hold", "at": clamp(n, 1, 100)] as [String: Any]
        }
        return x
    }

    /// One wait of a row. `raw` is its entry in the state file, for the words the session gave (--what, the PR's want).
    static func wait(_ w: Waits.Wait, _ raw: [String: Any]?) -> [String: Any]? {
        guard let wid = id(w.id), waitKinds.contains(w.kind) else { return nil }
        var safe = w
        safe.from = sender(w.from)   // also in how the Kit checks it: "Your email, for mail from supplier.com, …"
        let failing = !w.failing.isEmpty
        return ["id": wid, "kind": w.kind, "what": cut(what(w, raw)), "from": label(safe.from), "why": label(w.why),
                "by": time(w.by), "checks": label(Inbox.checks(safe)), "failing": failing,
                "failing_since": failing ? time(w.failingSince) : NSNull()]
    }

    /// Who an email reply is from, as the phone gets it: the domain of an address ("Dana <dana@supplier.com>" is
    /// supplier.com), else the name the session gave. A person's address stays on the Mac.
    static func sender(_ from: String) -> String {
        guard let at = from.lastIndex(of: "@") else { return from.trimmingCharacters(in: .whitespacesAndNewlines) }
        return String(from[from.index(after: at)...].prefix { $0.isLetter || $0.isNumber || $0 == "." || $0 == "-" })
    }

    /// What a wait waits for: the session's own --what, else words that name only its kind. Never its target (a
    /// thread id, a pull request), its script or a check-prompt's question.
    static func what(_ w: Waits.Wait, _ raw: [String: Any]?) -> String {
        let given = (raw?["what"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !given.isEmpty { return given }
        switch w.kind {
        case "pr": return raw?["want"] as? String == "closed" ? "Pull request closed" : "Pull request merged"
        case "email-reply": return "Email reply"
        case "check-prompt": return "A yes/no check"
        case "check-script": return "Its check script"
        case "at": return "A set time"
        default: return "A wait"
        }
    }

    /// A limit as the usage bars name it: the hook's "5-hour", "weekly" and "Opus weekly" are "5-hour limit", "Weekly"
    /// and "Weekly, Opus".
    static func limitName(_ hook: String) -> String {
        let n = hook.trimmingCharacters(in: .whitespacesAndNewlines)
        switch n.lowercased() {
        case "5-hour", "session", "5-hour limit": return "5-hour limit"
        case "weekly", "weekly_all": return "Weekly"
        case "", "usage": return "Usage limit"
        default: return n.lowercased().hasSuffix(" weekly") ? "Weekly, " + n.dropLast(7) : n
        }
    }

    // MARK: the archived list

    /// The archived sessions as the phone gets them (phone/DESIGN.md, section 13).
    struct ArchivedList: Equatable {
        struct Item: Equatable {
            let cse: String
            let title: String
            /// The working folder's own name, never its path.
            let folder: String
            let archivedAt: Int?
            let url: String

            var json: [String: Any] {
                ["cse": cse, "title": title, "folder": folder, "archived_at": archivedAt.map { $0 as Any } ?? NSNull(), "url": url]
            }
        }

        var items: [Item] = []

        /// A hash of the items as the phone sees them, so a snapshot's archived_rev names this exact list. Made here,
        /// from what goes up, so it always matches the list sent, whatever the file's own rev covers.
        var rev: String { Phone.hash(Phone.json(items.sorted { $0.cse < $1.cse }.map(\.json))) }
    }

    /// The list from archived.json (effort-hook.py writes it), less a session that has a Kit wait now (it shows under
    /// Waiting on someone else), that the Claude app lists again (it was brought back), or whose conversation is not on
    /// this Mac. Newest first, at most 200. Nil when there is no archived.json yet.
    static func archived(_ state: [String: Any]? = nil) -> ArchivedList? {
        guard let d = try? Data(contentsOf: supportDir.appendingPathComponent("archived.json")),
              let j = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any] else { return nil }
        let s = state ?? State.read()
        let waiting = Set(Waits.list(s).map(\.cse))
        let listed = Set(State.appList(s)?.items.keys.map { $0 } ?? [])
        var seen = Set<String>(), found: [(Int, ArchivedList.Item)] = []
        for (i, x) in (j["items"] as? [[String: Any]] ?? []).enumerated() {
            guard let cse = id(x["cse"] as? String), !waiting.contains(cse), !listed.contains(cse), !seen.contains(cse),
                  let tp = x["transcript"] as? String, !tp.isEmpty, FileManager.default.fileExists(atPath: tp) else { continue }
            seen.insert(cse)
            let title = cut(x["title"] as? String ?? "")
            let folder = cut(((x["folder"] as? String ?? "") as NSString).lastPathComponent.filter { !"/\\~".contains($0) }, 80)
            let at = Limit.num(x["archived_at"]).map { Int($0.rounded()) }.flatMap { (1_700_000_000...4_102_444_800).contains($0) ? $0 : nil }
            found.append((i, ArchivedList.Item(cse: cse, title: title.isEmpty ? "Session " + cse.suffix(6) : title, folder: folder,
                                               archivedAt: at, url: link(x["url"] as? String ?? "", cse: cse))))
        }
        found.sort { ($0.1.archivedAt ?? 0, -$0.0) > ($1.1.archivedAt ?? 0, -$1.0) }
        return ArchivedList(items: found.prefix(200).map(\.1))
    }

    /// The `archived` payload: the whole list, which the Kit sends only after the server's want_archived.
    static func archivedPayload(_ list: ArchivedList) -> [String: Any] {
        ["v": 1, "rev": list.rev, "items": list.items.map(\.json)]
    }

    /// The `archived_delta` payload from the list the server holds (`old`) to the list now. Nil when they are the same.
    static func archivedDelta(from old: ArchivedList, to new: ArchivedList) -> [String: Any]? {
        let base = old.rev, rev = new.rev
        guard base != rev else { return nil }
        let before = Dictionary(old.items.map { ($0.cse, $0) }, uniquingKeysWith: { a, _ in a })
        let after = Set(new.items.map(\.cse))
        return ["v": 1, "base": base, "rev": rev,
                "add": new.items.filter { before[$0.cse] != $0 }.map(\.json),
                "remove": old.items.map(\.cse).filter { !after.contains($0) }]
    }

    // MARK: usage by session

    /// The `usage` payload (phone/schema/usage.v1.json) for a period the server asked for: each session's share of the
    /// person's use on this Mac in it, the biggest first, at most 100, and the rest together, with the human work each
    /// equals and the factors of each kind of work. Names, Remote Control ids and numbers only: the scan's names never
    /// hold a path, a prompt or a reply. Nil for a period the contract does not have.
    static func usage(period key: String, data: SessionUsage.Data = SessionUsage.read(), now: Date = Date()) -> [String: Any]? {
        guard let p = SessionUsage.Period(key: key) else { return nil }
        let span = SessionUsage.span(p, now: now)
        let r = SessionUsage.report(data, from: span.from, to: span.to)
        func pct(_ x: Double) -> Double { min(100, max(0, (r.share(x) * 1000).rounded() / 10)) }
        func hours(_ h: Double) -> Double { min(1e7, max(0, (h * 10).rounded() / 10)) }
        let rows: [[String: Any]] = r.lines.prefix(100).map { l in
            let share = pct(l.usd)
            return ["title": cut(l.session.title).nilIfEmpty ?? "Unnamed session",
                    "cse": l.session.kind == "session" ? id(l.session.cse).map { $0 as Any } ?? NSNull() : NSNull(),
                    "share": share, "agent_share": min(share, pct(l.agents)),
                    "last_active": time(l.session.last), "agents": clamp(l.started, 0, 1_000_000),
                    "human_hours": hours(l.human)]
        }
        let rest = r.lines.dropFirst(100)
        return [
            "v": 1, "period": p.key, "from": span.from, "to": span.to, "at": Int(now.timeIntervalSince1970.rounded()),
            "total": ["sessions": clamp(r.lines.count, 0, 1_000_000), "tokens": min(1e15, r.tokens.rounded()),
                      "agent_share": pct(r.agents), "usd": min(1e9, (r.usd * 100).rounded() / 100),
                      "human_hours": hours(r.human)] as [String: Any],
            "rows": rows,
            "more": ["sessions": rest.count, "share": pct(rest.reduce(0) { $0 + $1.usd }),
                     "human_hours": hours(rest.reduce(0) { $0 + $1.human })] as [String: Any],
            "factors": data.kinds.prefix(8).map { ["name": String($0.name.prefix(40)), "x": min(100, max(0, $0.x))] as [String: Any] },
        ]
    }

    // MARK: when to send

    /// When a built snapshot goes up: only when it differs from the last one sent (its own build time aside), at most
    /// once every `gap` seconds, and a build `every` seconds after the last one catches words that change with age
    /// (how often a wait is checked) and a deadline that passed. Times go up as timestamps, so the clock alone never
    /// makes a send.
    struct Pacer {
        var gap: TimeInterval = 2
        var every: TimeInterval = 300
        private(set) var lastSent: Data?
        private(set) var sentAt: Date?
        private(set) var builtAt: Date?

        enum Step: Equatable {
            /// Send it now; it counts as sent.
            case send
            /// Nothing to send: the same as the last one sent.
            case same
            /// It changed, but the last send was under `gap` ago: build again after this many seconds.
            case wait(TimeInterval)
        }

        init(gap: TimeInterval = 2, every: TimeInterval = 300) {
            self.gap = gap
            self.every = every
        }

        /// A snapshot just built, on a change or by the timer.
        mutating func offer(_ payload: [String: Any], now: Date = Date()) -> Step {
            builtAt = now
            let key = Phone.comparable(payload)
            if key == lastSent { return .same }
            if let t = sentAt, now.timeIntervalSince(t) < gap { return .wait(gap - now.timeIntervalSince(t)) }
            lastSent = key
            sentAt = now
            return .send
        }

        /// A build is due with no change: `every` seconds after the last one.
        func buildDue(now: Date = Date()) -> Bool { builtAt.map { now.timeIntervalSince($0) >= every } ?? true }

        /// After a new connection: the next build goes up whatever it holds, since the server needs the whole snapshot.
        mutating func reset() {
            lastSent = nil
            sentAt = nil
        }

        /// After an action from the phone: the next build goes up even when it is the same as the last one sent, still
        /// at most once every `gap` seconds.
        mutating func forget() { lastSent = nil }
    }

    /// Builds the snapshot on each change of the Kit's state (Sync posts kitStateChanged 0.2 seconds after any write in
    /// the Kit's folder) and `every` seconds after the last build, and hands it to `send` when the pacer lets it go.
    /// PhoneLink sends it on the socket. Main thread only.
    final class Feed {
        private(set) var pacer: Pacer
        private let build: () -> [String: Any]
        private let send: ([String: Any]) -> Void
        private var held: DispatchWorkItem?
        private var timer: DispatchWorkItem?
        private var observer: NSObjectProtocol?

        init(pacer: Pacer = Pacer(), build: @escaping () -> [String: Any] = { Phone.snapshot() },
             send: @escaping ([String: Any]) -> Void) {
            self.pacer = pacer
            self.build = build
            self.send = send
        }

        /// Starts with the whole snapshot, as on a new connection.
        func start() {
            stop()
            observer = NotificationCenter.default.addObserver(forName: .kitStateChanged, object: nil, queue: .main) { [weak self] _ in
                self?.tick()
            }
            pacer.reset()
            tick()
        }

        func stop() {
            if let o = observer { NotificationCenter.default.removeObserver(o) }
            observer = nil
            held?.cancel()
            held = nil
            timer?.cancel()
            timer = nil
        }

        /// After an action from the phone: a snapshot goes up even when nothing changed, so the phone draws the truth.
        func sendNext() {
            pacer.forget()
            tick()
        }

        /// Builds now, unless a build already waits for the end of the gap: that one reads the state when it runs.
        func tick() {
            guard held == nil else { return }
            let p = build()
            switch pacer.offer(p) {
            case .send: send(p)
            case .same: break
            case .wait(let s): held = later(s) { [weak self] in self?.held = nil; self?.tick() }
            }
            timer?.cancel()
            timer = later(pacer.every) { [weak self] in self?.tick() }
        }

        private func later(_ secs: TimeInterval, _ f: @escaping () -> Void) -> DispatchWorkItem {
            let w = DispatchWorkItem(block: f)
            DispatchQueue.main.asyncAfter(deadline: .now() + secs, execute: w)
            return w
        }
    }

    // MARK: values as the schema takes them

    /// JSON with sorted keys, as it goes up.
    static func json(_ v: Any, pretty: Bool = false) -> Data {
        let o: JSONSerialization.WritingOptions = pretty ? [.sortedKeys, .withoutEscapingSlashes, .prettyPrinted] : [.sortedKeys, .withoutEscapingSlashes]
        return (try? JSONSerialization.data(withJSONObject: v, options: o)) ?? Data()
    }

    /// A snapshot without its build time, so two builds of the same state compare equal.
    static func comparable(_ payload: [String: Any]) -> Data {
        var p = payload
        p.removeValue(forKey: "at")
        return json(p)
    }

    /// A label as the schema takes it: each run of spaces and line breaks one space, cut to `cap` characters as JSON
    /// Schema counts them (Unicode scalars, so an emoji can count as two) at a whole character, with "…" when cut.
    static func cut(_ s: String, _ cap: Int = 160) -> String {
        let t = s.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        guard t.unicodeScalars.count > cap else { return t }
        var out = "", n = 0
        for ch in t {
            let k = ch.unicodeScalars.count
            if n + k > cap - 1 { break }
            out.append(ch)
            n += k
        }
        return out.trimmingCharacters(in: .whitespaces) + "…"
    }

    /// A label, or null when there is none.
    static func label(_ s: String?) -> Any {
        let t = cut(s ?? "")
        return t.isEmpty ? NSNull() : t
    }

    /// Unix seconds, or null for no time or one outside the schema's range.
    static func time(_ d: Date?) -> Any {
        guard let t = d?.timeIntervalSince1970.rounded(), t >= 1_700_000_000, t <= 4_102_444_800 else { return NSNull() }
        return Int(t)
    }

    static func clamp(_ n: Int, _ lo: Int, _ hi: Int) -> Int { min(hi, max(lo, n)) }

    static let idChars = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-")
    static let sidChars = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-")
    static let hexDigits = Set("0123456789abcdef")
    static let urlChars = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./?=&%-")

    /// An id as the schema takes it, or nil: an id can't be cut to fit.
    static func id(_ s: String?, max: Int = 80, chars: Set<Character> = idChars) -> String? {
        guard let s, !s.isEmpty, s.count <= max, s.allSatisfy(chars.contains) else { return nil }
        return s
    }

    /// The claude.ai link that Open in Claude uses: the session's own link, else one made from its Remote Control id.
    static func link(_ url: String, cse: String) -> String {
        let head = "https://claude.ai/"
        if url.hasPrefix(head), url.count <= 300, url.dropFirst(head.count).allSatisfy(urlChars.contains) { return url }
        if cse.hasPrefix("cse_") { return head + "code/session_" + cse.dropFirst(4) }
        if cse.hasPrefix("session_") { return head + "code/" + cse }
        return head + "code"
    }

    /// The usage API's kind, as the schema takes it (lowercase letters, digits and _).
    static func kindName(_ k: String) -> String {
        let s = String(k.lowercased().map { ("a"..."z").contains($0) || ("0"..."9").contains($0) ? $0 : "_" }.prefix(40))
        return s.isEmpty ? "usage" : s
    }

    /// "1.140".
    static func versionLike(_ v: String) -> Bool {
        let parts = v.split(separator: ".", omittingEmptySubsequences: false)
        return !parts.isEmpty && parts.allSatisfy { !$0.isEmpty && $0.allSatisfy { ("0"..."9").contains($0) } }
    }

    /// "America/New_York", "UTC".
    static func zoneLike(_ z: String) -> Bool {
        let parts = z.split(separator: "/", omittingEmptySubsequences: false)
        guard let first = parts.first, !first.isEmpty, first.allSatisfy({ $0.isASCII && ($0.isLetter || $0 == "_") }) else { return false }
        return parts.dropFirst().allSatisfy { !$0.isEmpty && $0.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || "_+-".contains($0)) } }
    }
}
