import AppKit
import SwiftUI

/// What the Kit did, in plain words, for the window's Events page. Read from the Kit's log and the bypass log, and
/// never shown as raw lines: each line becomes one sentence about one session, under the session's name.
struct KitEvent: Identifiable, Equatable {
    enum Kind: String, CaseIterable {
        case effort, limit, restart, name, same, wait, phone, update, check, app, problem
        var title: String {
            switch self {
            case .effort: return "Effort and permissions"
            case .limit: return "Usage limit"
            case .restart: return "Sessions started again"
            case .name: return "Session names"
            case .same: return "Same work"
            case .wait: return "Waits and messages"
            case .phone: return "Kit on your phone"
            case .update: return "Updates"
            case .check: return "Reply checks"
            case .app: return "The Kit"
            case .problem: return "Problems"
            }
        }
        var icon: String {
            switch self {
            case .effort: return "gauge.with.dots.needle.50percent"
            case .limit: return "pause.circle"
            case .restart: return "arrow.clockwise.circle"
            case .name: return "tag"
            case .same: return "arrow.triangle.merge"
            case .wait: return "hourglass"
            case .phone: return "iphone"
            case .update: return "arrow.down.circle"
            case .check: return "checkmark.seal"
            case .app: return "menubar.rectangle"
            case .problem: return "exclamationmark.triangle"
            }
        }
    }
    enum Level: Int { case info, warn, error }

    var kind: Kind
    var level: Level = .info
    /// A check that runs all the time and changes nothing: hidden unless "Routine checks" is on.
    var routine = false
    var session: String?      // the Remote Control id (cse_…), when known
    var name: String?         // the session's name
    var text: String
    var detail: [String] = []
    var first: Date
    var last: Date
    var count = 1
    var id: String { "\(kind.rawValue)|\(session ?? name ?? "")|\(text)|\(first.timeIntervalSince1970)" }
    /// Events with the same key are the same thing happening again.
    var key: String { "\(kind.rawValue)|\(session ?? name ?? "")|\(text)" }
}

enum Events {
    /// Session names from the Kit's state: by Remote Control id, by Claude Code id, and ids by name.
    struct Names {
        var byCse: [String: String] = [:]
        var bySid: [String: String] = [:]
        var cseByName: [String: String] = [:]
        var cseBySid: [String: String] = [:]

        static func current() -> Names {
            var n = Names()
            let all = State.read()["sessions"] as? [String: [String: Any]] ?? [:]
            for (cse, x) in all {
                let t = (x["title"] as? String ?? "").trimmingCharacters(in: .whitespaces)
                guard !t.isEmpty else { continue }
                n.byCse[cse] = t
                n.cseByName[t] = cse
                if let tp = x["transcript"] as? String, tp.hasSuffix(".jsonl") {
                    let sid = String((tp as NSString).lastPathComponent.dropLast(6))
                    n.bySid[sid] = t
                    n.cseBySid[sid] = cse
                }
            }
            return n
        }

        /// The session an id in a log line names: a full cse_ id, a Claude Code id or its first 8 characters
        /// ("f46255ef", "f46255ef/a10a43cb"), or the first characters of a cse_ id when only one session has them.
        func resolve(_ raw: String) -> (cse: String?, name: String?) {
            var id = raw
            if let slash = id.firstIndex(of: "/") { id = String(id[..<slash]) }
            id = id.trimmingCharacters(in: CharacterSet(charactersIn: "…:,"))
            guard id.count >= 6 else { return (nil, nil) }
            if id.hasPrefix("session_") { id = "cse_" + id.dropFirst(8) }
            if let t = byCse[id] { return (id, t) }
            if let t = bySid[id] { return (cseBySid[id], t) }
            if id.hasPrefix("cse_") { return (id, nil) }
            let sids = bySid.keys.filter { $0.hasPrefix(id) }
            if sids.count == 1 { return (cseBySid[sids[0]], bySid[sids[0]]) }
            let cses = byCse.keys.filter { $0.dropFirst(4).hasPrefix(id) }
            if cses.count == 1 { return (cses[0], byCse[cses[0]]) }
            return (nil, nil)
        }
    }

    static let stamp: DateFormatter = {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd HH:mm:ss"; return f
    }()

    static let levelWords = ["low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra", "max": "Max"]
    static func level<S: StringProtocol>(_ s: S) -> String { levelWords[String(s)] ?? String(s) }

    /// Every event in the Kit's log and the bypass log, newest first, with repeats folded together.
    static func read(kitLog: URL = logURL, bypassLog: URL? = nil, names: Names = .current()) -> [KitEvent] {
        var raw: [KitEvent] = []
        for (url, parse) in [(kitLog, kitLine), (bypassLog ?? KitLogs.all[1].url, bypassLine)] as [(URL, (String, Names) -> KitEvent?)] {
            guard let data = try? Data(contentsOf: url),
                  let text = String(data: data, encoding: .utf8) ?? String(data: data, encoding: .isoLatin1) else { continue }
            text.enumerateLines { line, _ in if let e = parse(line, names) { raw.append(e) } }
        }
        raw.sort { $0.first < $1.first }
        return fold(raw)
    }

    /// Problems that happen again in a day fold into one row for that day wherever they fall (with how many times that
    /// day, since when, and the last time), so the count under Today is today's; anything else folds with the same
    /// event just before it, or within a minute.
    static func fold(_ events: [KitEvent]) -> [KitEvent] {
        var out: [KitEvent] = []
        var at: [String: Int] = [:]
        let day = DateFormatter(); day.dateFormat = "yyyy-MM-dd"
        for e in events {
            let k = e.level != .info ? e.key + "|" + day.string(from: e.first) : e.key
            if let i = at[k], e.level != .info || e.first.timeIntervalSince(out[i].last) < 60 || i == out.count - 1 {
                out[i].count += 1; out[i].last = e.last; continue
            }
            out.append(e)
            at[k] = out.count - 1
        }
        return out.sorted { $0.last > $1.last }
    }

    /// An HTTP error in plain words: "<HTTPError 503: 'Service Unavailable'>" → "Claude was not available".
    static func http(_ s: String) -> String? {
        guard let r = s.range(of: #"(HTTP ?Error|HTTPError) ?(\d{3})"#, options: .regularExpression) else { return nil }
        let code = String(s[r].suffix(3))
        switch code {
        case "429": return "too many requests"
        case "500", "502", "503", "529": return "Claude was not available"
        case "504": return "Claude did not answer in time"
        case "401", "403": return "the Claude Code login was refused"
        default: return "error \(code)"
        }
    }

    /// "A 12 in storm" → "a 12 in storm", but "Cherry's date" and "PR #3" stay as they are.
    static func lower<S: StringProtocol>(_ s: S) -> String {
        let x = String(s)
        guard let f = x.first, f.isUppercase, x.count > 1 else { return x }
        let second = x[x.index(after: x.startIndex)]
        return second == " " || second.isLowercase && ["A ", "The ", "New ", "An "].contains(where: { x.hasPrefix($0) }) ? f.lowercased() + x.dropFirst() : x
    }

    // MARK: one line of the bypass log

    /// "2026-11-13 11:30:38 session=e676ee87-… mode=default tool=Bash"
    static func bypassLine(_ line: String, _ names: Names) -> KitEvent? {
        guard line.count > 20, let t = stamp.date(from: String(line.prefix(19))) else { return nil }
        var fields: [String: String] = [:]
        for part in line.dropFirst(20).split(separator: " ") {
            let kv = part.split(separator: "=", maxSplits: 1)
            if kv.count == 2 { fields[String(kv[0])] = String(kv[1]) }
        }
        guard let sid = fields["session"] else { return nil }
        let (cse, name) = names.resolve(sid)
        var tool = fields["tool"] ?? "a tool"
        if tool.hasPrefix("mcp__") { tool = (tool.components(separatedBy: "__").last ?? tool).replacingOccurrences(of: "_", with: " ") }
        let mode = fields["mode"] ?? ""
        if mode == "bypassPermissions" {
            return KitEvent(kind: .effort, routine: true, session: cse, name: name, text: "Approved a command that Bypass permissions still asks about",
                            detail: ["The command used \(tool)."], first: t, last: t)
        }
        let was = ["default": "asking before commands", "acceptEdits": "Accept edits", "auto": "Auto", "plan": "Plan"][mode] ?? mode
        return KitEvent(kind: .effort, session: cse, name: name, text: "Switched to Bypass permissions",
                        detail: ["It was in \(was) mode and asked to use \(tool)."], first: t, last: t)
    }

    // MARK: one line of the Kit's log

    /// No raw ids in what a person reads: a session id becomes the session's name, an email thread id goes.
    static func scrub(_ s: String, _ names: Names) -> String {
        guard s.contains("cse_") || s.contains("session_") || s.contains("claude://") || s.contains("thread ") else { return s }
        var out = s
        out = out.replacingOccurrences(of: #"claude://code/"#, with: "", options: .regularExpression)
        while let r = out.range(of: #"(cse|session)_[A-Za-z0-9]{6,}"#, options: .regularExpression) {
            let n = names.resolve(String(out[r])).name
            out.replaceSubrange(r, with: n.map { "\u{201C}\($0)\u{201D}" } ?? "a session")
        }
        out = out.replacingOccurrences(of: #"email thread [0-9a-f]{10,}"#, with: "an email thread", options: .regularExpression)
        out = out.replacingOccurrences(of: #"thread [0-9a-f]{10,}"#, with: "a thread", options: .regularExpression)
        return out
    }

    /// Where the person replied, as the reply watch logs it (`in the email thread "Lunch"`, `in the thread of its Chat
    /// post`, `in a Chat space it posted in`, `on its Asana task 1220…`), in words with no id: `in the email thread
    /// “Lunch”`, `on its Asana task`.
    static func placeWords(_ place: String) -> String {
        var p = place.trimmingCharacters(in: .whitespaces)
        p = p.replacingOccurrences(of: #" \d{6,}$"#, with: "", options: .regularExpression)   // an Asana task's id: in the detail as a link
        if let a = p.firstIndex(of: "\""), let b = p[p.index(after: a)...].firstIndex(of: "\"") {
            p = String(p[..<a]) + "\u{201C}" + p[p.index(after: a)..<b] + "\u{201D}" + p[p.index(after: b)...]
        }
        return p
    }

    /// The reply watch saw the person's own reply where a session watches or waits (watch.py):
    /// `replied <cse> "<title>" <where>, <time>: <their first words> | <what the Kit did>; <what the Kit did>`.
    /// One row: what they replied and where, then each thing the Kit did, as a sentence. A bring-back with a note is a
    /// row of Sessions started again; the rest are Waits and messages. Nothing about it alerts anyone.
    static func ownReply(_ rest: String, _ e: inout KitEvent) {
        e.kind = .wait
        // what the Kit did: after the " | " that starts one of its phrases (the person's words may hold a " | " too)
        let starts = ["its message in the Kit", "its wait ", "noted for", "brought back", "would come back", "not told", "comes back"]
        var main = rest, did = ""
        var from = rest.startIndex
        while let r = rest.range(of: " | ", range: from..<rest.endIndex) {
            if starts.contains(where: { rest[r.upperBound...].hasPrefix($0) }) {
                main = String(rest[..<r.lowerBound]); did = String(rest[r.upperBound...]); break
            }
            from = r.upperBound
        }
        // after the session's name in quotes: where, then the time of the reply, then the person's first words
        var tail = main
        if let a = main.firstIndex(of: "\""), let b = main[main.index(after: a)...].firstIndex(of: "\"") {
            tail = String(main[main.index(after: b)...]).trimmingCharacters(in: .whitespaces)
        }
        var place = tail, at = "", words = ""
        if let t = tail.range(of: #", ((?:[A-Z][a-z]{2} (?:\d{1,2} )?)?\d{1,2}:\d\d [AP]M): "#, options: .regularExpression) {
            place = String(tail[..<t.lowerBound])
            at = String(tail[t]).trimmingCharacters(in: CharacterSet(charactersIn: ", :"))
            words = String(tail[t.upperBound...]).trimmingCharacters(in: .whitespaces)
        }
        let task = place.range(of: #"\d{6,}$"#, options: .regularExpression).map { String(place[$0]) }
        let whereWords = placeWords(place)
        let brought = did.contains("brought back with a note")
        e.kind = brought ? .restart : .wait
        e.text = (brought ? "Brought back with a note: you replied " : "You replied ") + whereWords
        if !words.isEmpty {
            e.detail.append((at.isEmpty ? "You wrote: " : "At \(at) you wrote: ") + "\u{201C}" + words.prefix(160) + "\u{201D}")
        } else if !at.isEmpty {
            e.detail.append("You replied at \(at).")
        }
        if let g = task { e.detail.append("Asana task: https://app.asana.com/0/0/\(g)") }
        var told = false
        for raw in did.components(separatedBy: "; ") {
            let x = raw.trimmingCharacters(in: .whitespaces)
            let shows = x.range(of: "You replied ").map { String(x[$0.upperBound...]).replacingOccurrences(of: #" and still waits.*$"#, with: "", options: .regularExpression) } ?? ""
            if x.hasPrefix("its message in the Kit") {
                let subject = x.firstIndex(of: "\"").flatMap { a in x[x.index(after: a)...].firstIndex(of: "\"").map { String(x[x.index(after: a)..<$0]) } } ?? ""
                e.detail.append("Its message in the Kit" + (subject.isEmpty ? "" : ", \u{201C}\(subject)\u{201D},")
                                + " now shows \u{201C}You replied \(shows)\u{201D}: it is handled.")
            } else if x.hasPrefix("its wait ") {
                e.detail.append("Its email reply wait shows \u{201C}You replied \(shows)\u{201D} and still waits for the other person: your own reply does not end it.")
            } else if x.hasPrefix("noted for") {
                told = true
                e.detail.append("The session gets a note about it with its next prompt.")
            } else if x.hasPrefix("brought back with a note") {
                told = true
                let why = x.range(of: ": ").map { String(x[$0.upperBound...]) } ?? ""
                e.detail.append("The Kit brought it back with a note" + (why.isEmpty ? "." : ", since \(why)."))
            } else if x.hasPrefix("would come back") {
                told = true
                e.detail.append("Test run: it would come back with a note.")
            } else if x.hasPrefix("not told") {
                // why, as the log says it: it read the reply at a time, or it sent the mail itself
                let why = x.range(of: ": ").map { String(x[$0.upperBound...]) } ?? ""
                e.detail.append(why.isEmpty ? "Not told." : "Not told: \(why).")
            } else if !x.isEmpty {
                e.detail.append(x.prefix(1).uppercased() + x.dropFirst() + (x.hasSuffix(".") ? "" : "."))
            }
        }
        if told { e.detail.append("No alert, and no message to anyone.") }
        // the Kit only noted that it saw it: nothing changed for the session
        if did.trimmingCharacters(in: .whitespaces).hasPrefix("not told") && !did.contains(";") { e.routine = true }
    }

    static func kitLine(_ line: String, _ names: Names) -> KitEvent? {
        guard line.count > 20, let t = stamp.date(from: String(line.prefix(19))) else { return nil }
        let body = line.dropFirst(20)
        guard let sp = body.firstIndex(of: " ") else { return nil }
        let tag = String(body[..<sp])
        let rest = String(body[sp...].drop { $0 == " " })
        var e = KitEvent(kind: .app, text: "", first: t, last: t)

        // The part after " | " is the start of the person's prompt; the part after " - " is the reason.
        func split(_ s: String) -> (main: String, reason: String, prompt: String) {
            var main = s, prompt = ""
            if let r = main.range(of: " | ") { prompt = String(main[r.upperBound...]); main = String(main[..<r.lowerBound]) }
            var reason = ""
            if let r = main.range(of: " - ") { reason = String(main[r.upperBound...]); main = String(main[..<r.lowerBound]) }
            return (main, reason, prompt)
        }
        func who(_ id: Substring) { let r = names.resolve(String(id)); e.session = r.cse; e.name = r.name }
        func quoted(_ s: String) -> String? {
            guard let a = s.firstIndex(of: "\""), let b = s[s.index(after: a)...].firstIndex(of: "\"") else { return nil }
            return String(s[s.index(after: a)..<b])
        }
        func named(_ s: String) {
            if let q = quoted(s) { e.name = e.name ?? q; e.session = e.session ?? names.cseByName[q] }
        }
        func sentence(_ s: Substring) -> String {   // a reason from the log as a sentence of its own
            let t = s.trimmingCharacters(in: .whitespaces)
            return t.prefix(1).uppercased() + t.dropFirst() + (t.hasSuffix(".") ? "" : ".")
        }
        func promptDetail(_ p: String) {
            let clean = p.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
            guard !clean.isEmpty, !clean.hasPrefix("<") else { return }
            e.detail.append("Prompt: “" + clean.prefix(160) + (clean.count > 160 ? "…”" : "”"))
        }
        let words = rest.split(separator: " ", omittingEmptySubsequences: true)
        let first = words.first ?? ""

        switch tag {
        case "change", "keep", "raise", "lower", "steady":
            e.kind = .effort
            let (main, reason, prompt) = split(rest)
            let w = main.split(separator: " ")
            guard let id = w.first, id.hasPrefix("cse_") else {
                if rest.hasPrefix("can't list chats") {
                    e.kind = .problem; e.level = .warn
                    e.text = "Could not read the session list from Claude" + (http(rest).map { ": " + $0 } ?? "")
                    e.detail = ["The Kit tries again in a minute."]
                } else if rest.hasPrefix("the server is not connected") {
                    e.kind = .restart; e.level = .warn
                    e.text = "Sessions on the server wait until it connects"
                    e.detail = ["A session can't start on a server that is not connected. The Kit starts them again when it connects."]
                } else { e.text = rest.prefix(1).uppercased() + rest.dropFirst() }
                return e
            }
            who(id)
            named(main)
            // A keep line from the check that keeps sessions running has the name in quotes before the level.
            var lv = w.count > 1 ? w[1] : ""
            if let q = main.range(of: "\"", options: .backwards) { lv = main[q.upperBound...].split(separator: " ").first ?? "" }
            let steps = main.range(of: #"at (\d+) steps"#, options: .regularExpression).map { " after " + main[$0].dropFirst(3) } ?? ""
            if lv.contains("->") {
                let parts = lv.split(separator: "-", omittingEmptySubsequences: false)
                let from = parts.first.map { level($0) } ?? "", to = level(parts.last?.dropFirst() ?? "")
                if from.isEmpty { e.text = "Effort set to \(to)" + steps }
                else {
                    let up = (K.levels.firstIndex(of: String(parts.first!)) ?? 0) < (K.levels.firstIndex(of: String(parts.last!.dropFirst())) ?? 0)
                    e.text = "Effort \(up ? "raised" : "lowered") from \(from) to \(to)" + steps
                }
            } else {
                e.text = "Effort stays at \(level(lv))" + steps
                e.routine = tag != "keep" || !main.contains("\"")
            }
            if tag == "keep", main.contains("\"") {
                e.kind = .restart; e.routine = false
                if levelWords[String(lv)] != nil { e.text = "Started again at \(level(lv)) effort" }
                else if main.contains("archived or deleted") {
                    e.text = main.contains("while it was stopped") ? "Archived in the Claude app while it was stopped, so the Kit left it archived"
                        : "Archived in the Claude app, so the Kit stopped it"
                }
                else if let q = main.range(of: "\"", options: .backwards) {
                    let x = main[q.upperBound...].trimmingCharacters(in: .whitespaces)
                    e.text = x.prefix(1).uppercased() + x.dropFirst()
                }
            }
            if let r = reason.range(of: "not set now: ") {   // effort-hook.py typed_waits(): no change goes out now
                e.detail.append("It needs \(level(w.last ?? "")), but the Kit did not set it now. " + sentence(reason[r.upperBound...]))
            } else if let r = reason.range(of: "not checked now: ") {
                e.detail.append("Not checked now. " + sentence(reason[r.upperBound...]))
            } else if !reason.isEmpty { e.detail.append("Why: " + reason) }
            promptDetail(prompt)
        case "manual":
            e.kind = .effort
            let (main, _, prompt) = split(rest)
            who(first)
            e.text = main.contains("left at") ? "Effort is on Manual, left at " + level(main.split(separator: " ").last ?? "") : "Effort set by hand"
            e.routine = true
            promptDetail(prompt)
        case "agent":   // a subagent's effort, picked when it starts (effort-hook.py on_agent)
            e.kind = .effort
            let (main, reason, desc) = split(rest)
            let w = main.split(separator: " ")
            if let id = w.first, id.hasPrefix("cse_") { who(id) }
            let typ = w.count > 1 ? String(w[1]) : "agent"
            let what = desc.isEmpty ? (typ == "fork" ? "A fork" : "An agent") : (typ == "fork" ? "Fork" : "Agent") + " \u{201C}\(desc)\u{201D}"
            let tail = w.count > 2 ? String(w[2]) : ""
            // where a level that the Kit replaced or left came from
            let byCall = main.contains("(set in the call)"), byDefinition = main.contains("(set by its definition)")
            func own(_ s: Substring) -> String {   // a level of the call's own: a level, or one step from the session's
                s == "higher" ? "one step over the session's level" : s == "lower" ? "one step under the session's level" : level(s)
            }
            if tail == "kept" {   // older lines: the Kit kept a level that the call or the definition set
                e.text = "\(what) keeps \(level(w.count > 3 ? w[3] : "")) effort"; e.routine = true
                if !reason.isEmpty { e.detail.append(reason.prefix(1).uppercased() + reason.dropFirst() + ".") }
            } else if tail == "replaced" {   // "… Explore replaced xhigh (set in the call) with low (1.9s) low - why | desc"
                let old = w.count > 3 ? w[3] : ""
                let new = w.firstIndex(of: "with").flatMap { $0 + 1 < w.count ? w[$0 + 1] : nil } ?? ""
                let source = byDefinition ? "its definition" : "the call"
                e.text = "\(what) set to \(level(new)) effort"
                if !reason.isEmpty { e.detail.append("Why: " + reason) }
                e.detail.append(old == new ? "The level of \(source) was \(level(old)) too." : "It replaces \(own(old)), the level of \(source).")
                e.detail.append("Agent type: \(typ). It keeps this level until it finishes.")
            } else if tail == "left" {   // "… Explore left at high (set in the call) - the session is on Manual | desc"
                let lv = w.count > 4 ? w[4] : ""
                e.text = levelWords[String(lv)] != nil ? "\(what) left at \(level(lv)) effort" : "\(what) left at the session's level"
                e.routine = true
                if !reason.isEmpty { e.detail.append("The Kit did not set it: " + reason + ".") }
                e.detail.append(byCall ? "The call sets this level." : byDefinition ? "Its definition sets this level."
                    : typ == "fork" ? "A fork runs at the session's level, also when that level changes."
                    : "It runs at the session's level, also when that level changes.")
            } else if typ == "fork", tail.contains("->") {
                let p = tail.split(separator: "-", omittingEmptySubsequences: false)
                let to = level(p.last?.dropFirst() ?? "")
                e.text = "Effort raised from \(level(p.first ?? "")) to \(to) so \(what.prefix(1).lowercased() + what.dropFirst()) starts at \(to)"
                e.detail.append("A fork runs at the session's level, also when that level changes. So the Kit does not set the session back.")
                if !reason.isEmpty { e.detail.append("Why: " + reason) }
            } else if typ == "fork" {
                e.text = "\(what) starts at \(level(w.count > 3 ? w[3] : "")) effort, the session's level"; e.routine = true
                let needs = level(w.count > 5 ? w[5] : "")
                if let r = reason.range(of: "not raised now: ") {
                    e.detail.append("It needs \(needs), but the Kit did not raise the level now. " + sentence(reason[r.upperBound...]))
                } else if !reason.isEmpty { e.detail.append("It needs \(needs): " + reason) }
                e.detail.append("A fork runs at the session's level, also when that level changes.")
            } else {
                e.text = "\(what) set to \(level(tail.replacingOccurrences(of: "->", with: ""))) effort"
                if !reason.isEmpty { e.detail.append("Why: " + reason) }
                e.detail.append("Agent type: \(typ). It keeps this level until it finishes.")
            }
        case "reopen":
            e.kind = .effort
            who(first)
            e.text = "Came back in a new process at \(level(words.count > 2 ? words[2].trimmingCharacters(in: CharacterSet(charactersIn: ";")) : "")) effort"
        case "skip":
            e.kind = .effort; e.routine = true
            if first.hasPrefix("cse_") { who(first) }
            e.text = rest.contains("usage limit") ? "Effort not checked: at the usage limit" : "Effort not set: not a Remote Control session"
        case "paused":
            e.kind = .effort; e.text = "Auto effort is off"; e.routine = true
        case "halt":   // effort-hook.py halt_copies(): the Mac shuts down
            e.kind = .restart; e.routine = true
            e.text = "The Mac shuts down, so the Kit stopped its sessions without archiving them"
        case "wake", "start", "reattach", "move", "handover", "standdown":
            e.kind = .restart
            who(first); named(rest)
            switch tag {
            case "wake": e.text = "Stopped while not archived, so the Kit started it again"
            case "start": e.text = "Had stopped, so the Kit started it again"
            case "reattach":
                if rest.contains("wakes did not start it") {
                    e.text = "The server did not start it, so the Kit started it on the same link"
                    e.detail = ["The Kit asked the server to start it, and the server did not. The Kit runs it on its own, and it answers the messages sent while it was stopped."]
                } else {
                    e.text = "Unarchived, so the Kit started it on the same link"
                    e.detail = ["The server does not start a session that was archived. The Kit runs it on its own, and it answers the messages sent after it was unarchived."]
                }
            case "move": e.text = "Moved to a new link; the old entry stays in your list"; e.level = .warn
                e.detail = ["Claude Code could not keep its old link. Its Routines moved with it. The old entry has \"(old link)\" after its name; archive it in the Claude app when you want."]
            case "handover", "standdown":
                let other = tag == "handover" ? "The server runs it again" : "Taken over in another place"
                if rest.contains("\" waits: ") {
                    // "handover cse_… "Name" waits: the server runs it now, but the Kit's copy still works (<what>); the Kit waits …"
                    e.text = "\(other), but the Kit's copy still works, so the Kit waits to close it"
                    if let a = rest.range(of: "still works ("), let b = rest.range(of: "); the Kit waits", range: a.upperBound..<rest.endIndex) {
                        let what = rest[a.upperBound..<b.lowerBound]
                            .replacingOccurrences(of: #"\b[A-Za-z0-9]{8,} (?=")"#, with: "", options: .regularExpression)
                            .replacingOccurrences(of: #""([^"]*)""#, with: "\u{201C}$1\u{201D}", options: .regularExpression)
                        e.detail.append("Still at work: \(what).")
                    }
                    e.detail.append("The server's copy can fail as it starts, so the Kit waits 30 seconds at most. Then it closes its own copy, and a prompt from the Kit that has no answer goes again.")
                } else {
                    e.text = "\(other), so the Kit closed its own copy"
                    if tag == "standdown" { e.level = .warn }
                    if let r = rest.range(of: #"after it waited (\d+) seconds"#, options: .regularExpression) {
                        let n = rest[r].filter(\.isNumber)
                        e.detail.append("It waited \(n) seconds first, as the server's copy can fail as it starts.")
                    }
                }
            default: e.text = "Taken over in another place, so the Kit closed its own copy"; e.level = .warn
            }
        case "prompt":   // a prompt the Kit typed into its own copy of a session, until the session answers it
            // (effort-hook.py confirm_typed(), lose_typed(); wait.py redeliver(), tell_typed()):
            // "prompt lost   cse_… "Name" the copy that received the prompt the Kit typed in at 1:16 PM (same work) ended …"
            if words.count > 1 { who(words[1]) }
            named(rest)
            let (main, prompt) = rest.range(of: " | ").map { (String(rest[..<$0.lowerBound]), String(rest[$0.upperBound...])) } ?? (rest, "")
            let source = main.range(of: #"\((same work|a wait|new messages|the Kit)\)"#, options: .regularExpression)
                .map { String(main[$0].dropFirst().dropLast()) } ?? "the Kit"
            e.kind = source == "same work" ? .same : source == "the Kit" ? .restart : .wait
            let from = ["same work": "a prompt you sent here from another session (Send to)", "a wait": "a wait that ended",
                        "new messages": "new messages that came in"][source] ?? "the Kit's own message"
            let at = main.range(of: #"\d{1,2}:\d\d [AP]M"#, options: .regularExpression).map { String(main[$0]) }
            let tries = main.range(of: #"try \d of \d"#, options: .regularExpression).map { String(main[$0]) }
            func after(_ mark: String) -> String? { main.range(of: mark).map { String(main[$0.upperBound...]) } }
            switch String(first) {
            case "in":
                e.text = tries == nil ? "Answered the prompt the Kit typed in" : "Answered the prompt the Kit typed in again"
                e.routine = tries == nil
                e.detail.append("The Kit typed it in" + (at.map { " at \($0)" } ?? "") + ", for \(from).")
            case "lost":
                e.level = .warn
                e.text = "The copy that received a prompt ended before it answered"
                if let why = after("ended before it answered: ")?.components(separatedBy: "; ").first {
                    e.detail.append("Why: " + why + ".")
                }
                e.detail.append("The Kit typed it in" + (at.map { " at \($0)" } ?? "") + ", for \(from).")
                e.detail.append(main.contains("the Kit tells you") ? "It does not go again: the Kit tells you, with its text."
                                : "The Kit types it in again in the copy that runs the session next.")
            case "again":
                e.text = "Typed a prompt in again"
                e.detail.append("It first went in" + (at.map { " at \($0)" } ?? "") + ", for \(from), and had no answer." + (tries.map { " This was \($0)." } ?? ""))
            case "waits":
                e.text = "A prompt waits to go in again"
                if let why = after("could not start it to type a prompt in again: ") {
                    e.level = .warn
                    e.detail.append("The Kit could not start the session: " + (why.components(separatedBy: "; ").first ?? why) + ". It tries again each minute.")
                } else {
                    e.detail.append(main.contains("agents") ? "It goes when the session's agents and background commands end."
                                    : "It goes when the session's turn ends.")
                }
            case "failed":
                e.kind = .problem; e.level = .error
                e.text = "A prompt did not go in"
                if let why = after("did not go in: ")?.components(separatedBy: "; ").first { e.detail.append("Why: " + why + ".") }
                e.detail.append("The Kit typed it in" + (at.map { " at \($0)" } ?? "") + ", for \(from).")
                e.detail.append(main.contains("kept a message") ? "The Kit kept a message with its text on the session, in the Kit app."
                                : "The Kit sent you a message with its text. Send it again in the session if you still need it.")
            default:
                e.text = "Prompt: " + rest.prefix(160)
            }
            promptDetail(prompt)
        case "work":   // what runs in a session's copy when the Kit would end it (effort-hook.py running_work()): a
            // bring-back that waits for it (defer, done), work the Kit ended (kill) and the session told (told).
            // "work   kill cse_… "Name" handover: 1 agent (a1b2… "Build the page"); the session is told at its next prompt"
            e.kind = .restart
            if words.count > 1 { who(words[1]) }
            named(rest)
            var after = rest
            if let q = quoted(rest), let r = rest.range(of: "\"\(q)\" ") { after = String(rest[r.upperBound...]) }
            let action = String(after.prefix { $0 != " " && $0 != ":" })
            var list = after.range(of: ": ").map { String(after[$0.upperBound...]) } ?? ""
            list = list.components(separatedBy: "; ").first ?? list
            // the agents' and commands' own ids mean nothing to a person: their descriptions stay
            let plain = list.replacingOccurrences(of: #"\b[A-Za-z0-9]{8,} (?=")"#, with: "", options: .regularExpression)
                .replacingOccurrences(of: #""([^"]*)""#, with: "\u{201C}$1\u{201D}", options: .regularExpression)
            switch String(first) {
            case "defer":
                e.text = "Comes back when its work ends"
                e.detail = ["Still at work: \(plain).",
                            "Bringing it back would end them, so the Kit tries again each minute. It brings it back when they end, at most 2 hours later."]
            case "kill":
                e.level = .warn
                switch action {
                case "handover": e.text = "Work stopped: the server took it over"
                    e.detail = ["The server started its own copy of the session, so the Kit ended the copy it ran, and the work in it."]
                case "standdown": e.text = "Work stopped: taken over in another place"
                    e.detail = ["The Kit's copy stood down, so the Kit ended it, and the work in it."]
                case "archived": e.text = "Work stopped: archived"
                    e.detail = ["The Kit ended its copy, and the work in it."]
                case "halt": e.text = "Work stopped: the Mac shut down"
                    e.detail = ["The Kit ended its copy before the Mac shut down, so the session was not archived."]
                default: e.text = "Work stopped: brought back after 2 hours"
                    e.detail = ["The Kit waited 2 hours for the work to end, then brought the session back for what it waited on."]
                }
                e.detail.insert("Stopped: \(plain).", at: 0)
                e.detail.append(rest.contains("told in the Kit's message") ? "The Kit's message tells the session what stopped, with each one's id, so it can go on."
                                : "The session gets a list of what stopped, with each one's id, at its next prompt, so it can go on.")
            case "told":
                e.text = "Told the session what work stopped"
                e.detail = [after.contains("in the Kit's message") ? "In the message the Kit brought it back with." : "With its next prompt."]
            case "done":
                e.routine = true
                e.text = "Its agents and background commands ended, so the Kit brings it back"
            default:
                e.text = "Work: " + rest.prefix(160)
            }
        case "trust":   // effort-hook.py trust_folder(): a session's folder trusted in Claude Code before the Kit starts it there
            e.kind = .restart
            if let r = rest.range(of: " could not be marked trusted") {
                e.text = "Could not trust a session's folder in Claude Code"; e.level = .warn
                e.detail = ["Folder: " + rest[..<r.lowerBound],
                            "Claude Code can ask whether to trust it, and in the Kit's screen nobody can answer, so the session does not start."]
            } else {
                e.text = "Trusted a session's folder in Claude Code"; e.routine = true
                e.detail = ["Folder: " + (rest.range(of: " trusted in Claude Code").map { rest[..<$0.lowerBound] } ?? Substring(rest)),
                            "The session ran there before. Now it starts there without Claude Code's trust question."]
            }
        case "migrate":   // Move a session to Remote Control (migrate.py)
            e.kind = .restart
            if let r = rest.range(of: #"as (cse_\w+)"#, options: .regularExpression) { who(rest[r].dropFirst(3)) }
            named(rest)
            if rest.contains("moved to Remote Control") {
                e.text = "Moved to Remote Control from this Mac only"
                e.detail = ["It keeps its whole conversation and shows on your phone and in the Claude app."]
                if rest.contains("closed it in Terminal") { e.detail.append("It was open in Terminal, so the Kit closed it there first.") }
                if rest.contains("closed it in the desktop app") { e.detail.append("It was open in the desktop app, so the Kit closed it there first. Archive its old entry under This computer.") }
            } else if rest.contains("moves when its reply ends") {
                e.text = "Moves to Remote Control when its reply ends"
            } else if rest.contains("did not get a Remote Control link") {
                e.kind = .problem; e.level = .warn
                e.text = "Did not move to Remote Control: no link came in 90 seconds"
                e.detail = ["It stays on this Mac only. Move it again from the Sessions page."]
            } else if rest.contains("could not be closed") {
                e.kind = .problem; e.level = .warn
                e.text = "Did not move to Remote Control: it did not close where it runs"
                e.detail = ["Quit it there, then move it again."]
            } else if rest.contains("could not set") {
                e.kind = .problem; e.level = .warn
                e.text = "Moved, but its name did not reach the Claude app"
            } else { e.text = rest.prefix(1).uppercased() + rest.dropFirst() }
        case "name":
            e.kind = .name
            let (main, _, prompt) = split(rest)
            if main.contains(" set \"") && main.hasSuffix("in the Claude app") { return nil }   // the same name, sent to the app
            who(first)
            if words.count > 1 && words[1] == "wait" { return nil }   // naming waits for a longer prompt
            if main.contains(" keeps \"") || main.contains(" has \"") { named(main); e.text = "Name kept"; e.routine = true }
            else if main.contains("-> \""), let q = quoted(main) {
                e.text = "Named “\(q)”"; e.name = e.name ?? q; e.session = e.session ?? names.cseByName[q]
                promptDetail(prompt)
            } else { e.text = "Name: " + main }
        case "limit":
            e.kind = .limit
            let sub = String(first)
            let after = rest.dropFirst(sub.count).drop { $0 == " " }
            let aw = after.split(separator: " ")
            func sentence(_ s: Substring) -> String {
                var x = String(s)
                if let r = x.range(of: #" \((Bash|menu|typed|command|[A-Za-z]+)\)$"#, options: .regularExpression) {
                    let src = x[r].dropFirst(2).dropLast()
                    x = String(x[..<r.lowerBound])
                    e.detail.append(["menu": "From the menu or the window.", "window": "From the Kit window.", "phone": "From the phone.",
                                     "typed": "Typed in the session.", "command": "From the claude-limit-mode command."][String(src)]
                                    ?? "At its next step (\(src)).")
                }
                return x
            }
            switch sub {
            case "usage":
                e.kind = .problem; e.level = .warn
                e.text = rest.contains("429") ? "Usage read failed: too many requests" : "Usage read failed"
                e.detail = ["The Kit uses its last good read until the next one works."]
            case "hold":
                if let id = aw.first { who(id) }
                let why = sentence(after.drop { $0 != ":" }.dropFirst().drop { $0 == " " })
                if let r = why.range(of: ", until ") {
                    e.text = "Held: " + why[..<r.lowerBound] + ". Goes on " + why[r.upperBound...]
                } else { e.text = "Held: " + why }
            case "wait":
                return nil   // the hold's own wait, logged in the same second
            case "reload":
                if let id = aw.first { who(id) }
                e.text = "The hold went on in the updated Kit"
                e.routine = true
            case "resume":
                if let id = aw.first { who(id) }
                let why = after.drop { $0 != " " }.drop { $0 == " " }
                e.text = "Went on: " + (why.split(separator: ",").first.map(String.init) ?? String(why))
                if let r = why.range(of: #"after (\d+) min"#, options: .regularExpression),
                   let m = Int(why[r].split(separator: " ")[1]) {
                    e.detail.append("It held for " + (m >= 60 ? "\(m / 60) h \(m % 60) min" : "\(m) min") + ".")
                }
            case "credits":
                if aw.first == "every" {
                    let x = sentence(after.dropFirst(6))
                    e.text = x.hasPrefix("session uses") ? "Every session now uses credits at the limit" : "Every session now holds at the limit"
                } else {
                    if let id = aw.first { who(id) }
                    e.text = "Set to use credits " + sentence(after.drop { $0 != " " }.drop { $0 == " " }).replacingOccurrences(of: "uses credits ", with: "")
                }
            case "mode":
                if let id = aw.first { who(id) }
                let x = sentence(after.drop { $0 != " " }.drop { $0 == " " })
                e.text = "Usage setting changed: " + x
            default:
                e.text = rest.prefix(1).uppercased() + rest.dropFirst()
            }
        case "ste":
            e.kind = .check
            who(first)
            let x = words.dropFirst().joined(separator: " ")
            if x.hasPrefix("ok") { e.text = "Reply checked: OK"; e.routine = true }
            else if x.hasPrefix("noted") || x.hasPrefix("sent back") {
                e.text = "Reply check found words to fix"; e.routine = true
                if let c = x.firstIndex(of: ":") { e.detail.append(String(x[x.index(after: c)...]).trimmingCharacters(in: .whitespaces)) }
                e.detail.append("The session gets a note with its next prompt.")
            } else if x.contains("error") || x.contains("failed") { e.kind = .problem; e.level = .warn; e.text = "Reply check could not run" }
            else { e.text = "Reply check: " + x }
        case "agents":
            e.kind = .check; who(first)
            e.text = "Many tool calls in the chat with no agent"
            e.detail = ["The session gets a note with its next prompt to hand such work to an agent."]
        case "icons":
            e.kind = .check; who(first); e.text = "A status cell had more than one icon"
        case "rules":
            e.kind = .check; e.routine = true
            who(first)
            e.text = rest.contains("pointer") ? "Sttark app rules: pointer added" : "Sttark app rules refreshed"
        case "wait":
            e.kind = .wait
            let (main, _, _) = split(rest)
            named(main)
            if let c = main.range(of: " set: ") {
                let what = main[c.upperBound...]
                if let by = what.range(of: ", by ", options: .backwards) {
                    e.text = "Waits for " + lower(what[..<by.lowerBound]); e.detail.append("Deadline: " + what[by.upperBound...] + ".")
                } else { e.text = "Waits for " + lower(what) }
            } else if main.contains(" from the archive") {   // claude-wait --unarchive: the window's Archived page, or the phone
                e.kind = .restart
                let from = main.contains("(phone)") ? "the phone" : "the Kit window"
                if main.contains(" brought back from the archive") && !main.contains("not brought back") {
                    e.text = "Unarchived, on the same link"
                    e.detail = ["Asked from \(from). It came back with its whole conversation, and nothing was sent to it."]
                } else {
                    e.kind = .problem; e.level = .warn
                    e.text = main.contains("not archived now") ? "Not unarchived: it is not archived now"
                        : main.contains("not on this Mac") ? "Not unarchived: its conversation is not on this Mac"
                        : main.contains("was not back after") ? "Started from the archive, but the Claude app did not show it back"
                        : "Not unarchived: it did not come back"
                    e.detail = ["Asked from \(from)."]
                    if main.contains("not archived now") { e.level = .info; e.kind = .restart }
                }
            } else if main.contains("the Kit kept one in the Kit app") || main.contains(" kept the message from the Kit") {
                e.text = main.contains("did not come back") ? "It could not come back; the Kit kept its message here"
                                                            : "It sent no message after coming back; the Kit kept one here"
                e.detail = ["Alerts are off, so nothing was sent. The message is on the session's panel on the Sessions page."]
            } else if main.contains(" brought ") { e.text = "Brought back: the wait ended" }
            else if main.contains(" cancelled") { e.text = "Wait cancelled" }
            else if main.contains("checked:") {
                e.routine = !main.contains("YES")
                e.text = main.contains("YES") ? "Wait check: it happened" : "Wait check: not yet"
            } else if main.contains("fail") { e.kind = .problem; e.level = .warn; e.text = "A wait check failed" }
            else {
                var x = String(main.split(separator: " ").dropFirst().joined(separator: " "))
                if x.hasPrefix("cse_") { x = String(x.drop { $0 != " " }.dropFirst()) }
                if let q = quoted(x) { x = x.replacingOccurrences(of: "\"\(q)\" ", with: "") }
                e.text = x.prefix(1).uppercased() + x.dropFirst()
            }
        case "watch":   // the reply watch (watch.py), and the working rules' reply wait check
            e.kind = .wait
            named(rest)   // the session's name in quotes; its id in the line is cut short, as in a wait line
            let after = rest.firstIndex(of: ":").map { String(rest[rest.index(after: $0)...]).trimmingCharacters(in: .whitespaces) } ?? ""
            // The check of a broad match (a new message on a channel that carries other work too):
            // "skip|checked <cse> "<name>" <from>: [not] about this session's work: <first words> | <why>"
            func checkDetail(_ marker: String) {
                let (main, _, why) = split(rest)
                guard let r = main.range(of: marker) else { return }
                let head = main[..<r.lowerBound]
                if let q = quoted(String(head)), let end = head.range(of: "\"\(q)\"") {
                    let from = head[end.upperBound...].trimmingCharacters(in: .whitespaces)
                    if !from.isEmpty { e.detail.append("From: " + from + ".") }
                }
                let words = main[r.upperBound...].trimmingCharacters(in: .whitespaces)
                if !words.isEmpty { e.detail.append("Message: \u{201C}" + words.prefix(160) + "\u{201D}") }
                if !why.isEmpty { e.detail.append("Why: " + why.prefix(200)) }
            }
            if rest.hasPrefix("replied ") {   // the person's own reply where the session watches or waits
                ownReply(rest, &e)
            } else if rest.hasPrefix("told ") && rest.contains(" of your reply ") {
                e.routine = true
                let inMessage = rest.hasSuffix(", in the Kit's message")
                e.text = inMessage ? "Told of your reply, in the Kit's message" : "Told of your reply, with its next prompt"
                if let r = rest.range(of: " of your reply ") {
                    var place = String(rest[r.upperBound...])
                    if let c = place.range(of: ", ", options: .backwards) { place = String(place[..<c.lowerBound]) }
                    let words = Events.placeWords(place)
                    if !words.isEmpty { e.detail.append("Where: " + words + ".") }
                }
                e.detail.append("No alert, and no message to anyone.")
            } else if rest.contains(" not watched: archived with no wait") {
                // an archived session with no open wait: the watch reads nothing for it (watch.py not_watched())
                e.routine = true
                e.text = "Not watched: it is archived and waits on no one"
                e.detail.append("Answers to it do not bring it back. A session that waits on someone else is watched.")
            } else if rest.contains(" not told of ") && rest.contains(": archived with no wait") {
                e.text = "Not brought back: it is archived and waits on no one"
                if let r = rest.range(of: ": archived with no wait: ") {
                    e.detail.append("Messages: " + rest[r.upperBound...].prefix(300))
                }
                e.detail.append("Answers to it do not bring it back. A session that waits on someone else is watched.")
            } else if rest.hasPrefix("skip ") && rest.contains(" you in Chat: not about this session's work: ") {
                e.text = "Your Chat post was about other work, so the session was not told"
                let (main, _, why) = split(rest)
                if let r = main.range(of: ": not about this session's work: ") {
                    let words = main[r.upperBound...].trimmingCharacters(in: .whitespaces)
                    if !words.isEmpty { e.detail.append("You wrote: \u{201C}" + words.prefix(160) + "\u{201D}") }
                }
                if !why.isEmpty { e.detail.append("Why: " + why.prefix(200)) }
                e.detail.append("The reply watch asked Haiku, because your post was in a Chat space the session posted in, not in the thread of its post.")
            } else if rest.hasPrefix("checked ") && rest.contains(" you in Chat: about this session's work: ") {
                e.kind = .check; e.routine = true
                e.text = "Your Chat post is about its work"
                checkDetail(": about this session's work: ")
            } else if rest.hasPrefix("skip ") && rest.contains(": not about this session's work: ") {
                e.text = "Not brought back: a new message was about other work"
                checkDetail(": not about this session's work: ")
                e.detail.append("The reply watch asked Haiku, because mail from this sender or a post in this Chat space can be about other work.")
            } else if rest.hasPrefix("checked ") && rest.contains(": about this session's work: ") {
                e.kind = .check; e.routine = true
                e.text = "A new message is about its work"
                checkDetail(": about this session's work: ")
            } else if rest.contains(" could not check a message (") {
                e.kind = .problem; e.level = .warn
                e.text = "The reply watch could not check a message, so it brought the session back"
                e.detail.append(String(rest.prefix(300)))
            } else if rest.contains(" waits for the usage hold to end before the check") {
                e.routine = true; e.text = "New messages wait for the usage hold to end before their check"
            } else if rest.contains(" brought back for ") {
                e.kind = .restart
                e.text = "Brought back: new messages came in from someone it contacted"
                if !after.isEmpty { e.detail.append("Messages: " + after.prefix(300)) }
            } else if rest.contains(" would come back (dry)") {
                e.routine = true; e.text = "Would bring it back for new messages (test run)"
            } else if rest.contains(" is in a turn;") {
                e.routine = true; e.text = "New messages came in; it comes back when its turn ends"
            } else if rest.contains("the Kit kept the message in the Kit app") {
                e.text = "New messages came in, but it could not come back; the Kit kept a message on the session"
            } else if rest.contains("the Kit sent you the message") {
                e.level = .warn; e.text = "New messages came in, but it could not come back; the Kit sent you a message"
            } else if rest.contains(" could not come back") || rest.contains(" message failed") || rest.hasPrefix("could not read a step") {
                e.kind = .problem; e.level = .warn; e.text = "The reply watch could not bring it back"
                e.detail.append(String(rest.prefix(300)))
            } else if rest.contains(" with no reply wait") {
                e.kind = .check; who(first)
                e.text = "Contacted someone and set no wait for the answer"
                e.detail = [String(rest.dropFirst(first.count + 1).prefix(200)), "The session gets a note with its next prompt."]
            } else if rest.contains(" read failed: ") {
                e.kind = .problem; e.level = .warn
                e.text = "The reply watch could not read " + String(first).trimmingCharacters(in: CharacterSet(charactersIn: ":"))
                e.detail.append(after.isEmpty ? String(rest.prefix(300)) : String(rest[rest.range(of: " read failed: ")!.upperBound...].prefix(300)))
            } else if rest.contains(" read (") {
                e.kind = .check
                e.routine = !rest.contains(" for a session") || rest.contains(", 0 for a session")
                e.text = "Reply watch read " + String(first) + ": " + after
            } else if rest.contains("cannot read this mailbox") {
                e.kind = .check; e.level = .warn
                e.text = "The reply watch cannot read " + String(first).trimmingCharacters(in: CharacterSet(charactersIn: ":"))
                e.detail.append(String(rest.prefix(300)))
            } else {
                e.text = "Reply watch: " + rest.prefix(160)
            }
        case "same":   // One session for the same work (same-work.py): a new session's first prompt, the question, the answer
            e.kind = .same
            var body = rest
            if first.hasPrefix("cse_") || first.hasPrefix("session_") { who(first); body = String(rest.dropFirst(first.count + 1)) }
            // a line about the open session the prompt goes to: "<cse> "<name>" got the first prompt of <cse>…"
            if body.hasPrefix("\""), let q = quoted(body) {
                e.name = e.name ?? q; e.session = e.session ?? names.cseByName[q]
                body = String(body.dropFirst(q.count + 2)).trimmingCharacters(in: .whitespaces)
            }
            let fromName: String? = body.range(of: #" of (cse|session)_[A-Za-z0-9]+"#, options: .regularExpression)
                .flatMap { names.resolve(String(body[$0].dropFirst(4))).name }
            let from = fromName.map { "From the new session \u{201C}\($0)\u{201D}." }
            let dry = body.hasSuffix(" (dry: nothing sent)")
            var main = body, prompt = ""
            if let r = body.range(of: " | ") { main = String(body[..<r.lowerBound]); prompt = String(body[r.upperBound...]) }
            func after(_ mark: String) -> String? { main.range(of: mark).map { String(main[$0.upperBound...]) } }
            if main.hasPrefix("asks: ") {
                let t = quoted(main) ?? "another session"
                e.text = "Same work as \u{201C}\(t)\u{201D}: Claude asks where the prompt goes"
                if let s = main.range(of: "\", started "), let end = main.range(of: " (", range: s.upperBound..<main.endIndex) {
                    e.detail.append("\u{201C}\(t)\u{201D} started " + main[s.upperBound..<end.lowerBound] + ". The question offers Send to and Keep here.")
                }
                if let r = main.range(of: "s) - ") { e.detail.append("Why: " + main[r.upperBound...] + ".") }
            } else if main.hasPrefix("no match among ") {
                e.routine = true; e.text = "Same work check: no open session does this work"
                if let n = main.split(separator: " ").dropFirst(3).first { e.detail.append("Compared with \(n) open session\(n == "1" ? "" : "s").") }
                if let r = main.range(of: "s) - ") { e.detail.append("Why: " + main[r.upperBound...] + ".") }
            } else if let why = after("no match: ") {
                e.routine = true; e.text = "Same work check: no other open session to compare"
                e.detail.append(why.prefix(1).uppercased() + why.dropFirst() + ".")
            } else if let why = after("not checked: ") {
                e.routine = true; e.text = "Same work check skipped"
                e.detail.append(why.prefix(1).uppercased() + why.dropFirst() + ".")
            } else if let why = after("check failed: ") {
                e.kind = .problem; e.level = .warn; e.text = "The same work check could not run"
                e.detail.append(String(why.prefix(300)))
            } else if main.hasPrefix("keeps its first prompt here") {
                e.text = "The prompt stays here: Keep here" + (quoted(main).map { ", not \u{201C}\($0)\u{201D}" } ?? "")
            } else if main.hasPrefix("answered the same work question") {
                e.text = "The same work question got another answer; nothing was sent"
                if let a = after("sends nothing: ") { e.detail.append("Answer: \u{201C}" + a + "\u{201D}") }
            } else if main.hasPrefix("got the first prompt of ") {
                e.routine = dry
                e.text = (main.contains(", which waited ") ? "Got a new session's first prompt after its turn ended"
                          : "Got a new session's first prompt (Send to)") + (dry ? " (test run)" : "")
                if let w = after(", which waited ") { e.detail.append("It waited " + w.replacingOccurrences(of: " (dry: nothing sent)", with: "") + ".") }
                e.detail.append("It runs here as the person's own message.")
            } else if main.hasPrefix("gets the first prompt of ") {
                if let why = after("it could not start now: ") {
                    e.level = .warn; e.text = "A new session's first prompt waits: this session could not start"
                    e.detail.append(why.prefix(1).uppercased() + why.dropFirst() + ". The Kit tries again each minute.")
                } else {
                    e.text = "A new session's first prompt waits for the turn to end"
                }
            } else if main.hasPrefix("could not start for the first prompt of ") {
                e.level = .warn; e.text = "A new session's first prompt waits: this session could not start"
                if let r = main.range(of: #"_[A-Za-z0-9]+: "#, options: .regularExpression) { e.detail.append(String(main[r.upperBound...])) }
            } else if main.hasPrefix("could not get the first prompt of ") || main.hasPrefix("never got the first prompt of ") {
                e.kind = .problem; e.level = .warn
                e.text = main.hasPrefix("never") ? "A new session's first prompt never went" : "A new session's first prompt could not go"
                if let r = main.range(of: #"_[A-Za-z0-9]+: "#, options: .regularExpression) { e.detail.append(String(main[r.upperBound...])) }
            } else {
                e.kind = .problem; e.level = .warn; e.text = "The same work check failed"
                e.detail.append(String(rest.prefix(300)))
            }
            if let from, e.text.contains("new session") { e.detail.append(from) }
            promptDetail(prompt)
        case "checkin":   // the progress check-ins (checkin.py): a note on a session's long work, shown in the Kit app;
                          // and the check-in timer in the session (checkin-timer.py), named by its cse or conversation id
            e.kind = .wait
            if first.hasPrefix("cse_") || first.count == 36 { who(first) }
            named(rest)
            var after = rest
            if let q = quoted(rest), let r = rest.range(of: "\"\(q)\" ") { after = String(rest[r.upperBound...]) }
            // "<status> | <subject> | <note>"; the status is "shown in the Kit", then "; no summary (…)" when it applies,
            // or "written (dry)". Lines from before the check-in timer can add "; in the chat", "; would go in the chat"
            // (dry) or "; not in the chat: <why>". Lines from before check-ins stayed in the Kit app say "sent by …",
            // "would send (dry)" or "not sent (…)", with "; not by …"
            let fields = after.components(separatedBy: " | ")
            let items = fields[0].components(separatedBy: "; ")
            let subject = fields.count > 1 ? fields[1] : ""
            let note = fields.count > 2 ? fields[2...].joined(separator: " | ") : ""
            if items[0].hasPrefix("timer ") {
                // the check-in timer in the session (checkin-timer.py): "timer <what> [<job>] | <detail>"
                let w = items[0].dropFirst(6).split(separator: " ", maxSplits: 1).map(String.init)
                let what = w.first ?? "", job = w.count > 1 ? w[1] : ""
                let detail = fields.count > 1 ? fields[1...].joined(separator: " | ") : ""
                e.routine = true
                switch what {
                case "asked":
                    e.text = "Check-in timer asked for"
                    e.detail = ["Work runs in the background (\(detail)), so the Kit asked the session to set its check-in timer."]
                case "set":
                    e.text = "Check-in timer set"
                    e.detail = ["The session set its check-in timer, job \(job): \(detail)."]
                case "check-in":
                    e.routine = false
                    e.text = "Check-in in the session's chat"
                    if detail.hasPrefix("no work runs") {
                        e.detail = ["The Kit saw no agent or background command at work, so it told the session to delete the timer."]
                    } else if detail.hasPrefix("check-ins in the session are off") {
                        e.detail = ["Check-ins in the session are off, so the Kit told the session to delete the timer."]
                    } else if detail.hasPrefix("could not read its work") {
                        e.level = .warn
                        e.detail = ["The Kit " + detail + ". The session answers from what it knows."]
                    } else {
                        e.detail = ["What runs: \(detail). The Kit gave the session this list for its answer of one or two lines."]
                    }
                case "reminder":
                    e.text = "Check-in timer: the Kit told the session to delete it"
                    e.detail = [detail.hasPrefix("check-ins in the session are off")
                                ? "Check-ins in the session are off." : "The timer was still set, and no agent or background command was at work."]
                case "ended":
                    e.text = "Check-in timer deleted"
                    e.detail = ["The session deleted its check-in timer, job \(job)."]
                case "second":
                    e.text = "A second check-in timer: the Kit told the session to delete it"
                    e.detail = [detail.prefix(1).uppercased() + detail.dropFirst() + "."]
                case "error:":
                    e.kind = .problem; e.level = .warn; e.routine = false
                    e.text = "The check-in timer hook failed"
                    e.detail = [String(items[0].dropFirst(13).prefix(300))]
                default:
                    e.text = "Check-in timer: " + what
                }
                break
            }
            if !note.isEmpty { e.detail.append("\u{201C}" + note + "\u{201D}") }
            var inChat = false
            for x in items.dropFirst() {
                if x.hasPrefix("not by ") { e.level = .warn; e.detail.append("Not sent by " + x.dropFirst(7) + ".") }
                else if x.hasPrefix("no summary") { e.detail.append("Haiku gave no summary" + x.dropFirst(10) + ", so the note gives the count of steps.") }
                else if x == "in the chat" {
                    inChat = true
                    e.detail.append("The Kit typed it into the session as a prompt, and the session answers it in its chat.")
                } else if x == "would go in the chat" {
                    e.detail.append("Test run: it would go in the session's chat, and nothing was typed.")
                } else if x.hasPrefix("not in the chat: ") {
                    let why = String(x.dropFirst(17))
                    e.detail.append("Not in the chat: " + why + (why.hasSuffix(".") ? "" : "."))
                    if why.hasPrefix("the Kit could not type") { e.level = .warn }
                }
            }
            if items[0].hasPrefix("shown") {
                e.text = (inChat ? "Progress check-in, also in the chat" : "Progress check-in") + (subject.isEmpty ? "" : ": " + subject)
            } else if items[0].hasPrefix("written (dry)") {
                e.routine = true; e.text = "Progress check-in written, not kept (test run)" + (subject.isEmpty ? "" : ": " + subject)
            } else if items[0].hasPrefix("sent by ") {
                e.text = "Progress check-in sent by " + items[0].dropFirst(8) + (subject.isEmpty ? "" : ": " + subject)
            } else if items[0].hasPrefix("would send") {
                e.routine = true; e.text = "Progress check-in written, not sent (test run)" + (subject.isEmpty ? "" : ": " + subject)
            } else if items[0].hasPrefix("not sent") {
                e.level = .warn
                e.text = "Progress check-in not sent" + (subject.isEmpty ? "" : ": " + subject)
                if let r = items[0].range(of: "not sent (") { e.detail.insert(String(items[0][r.upperBound...].dropLast()), at: 0) }
                else if let r = items[0].range(of: "not sent: ") { e.text = "Progress check-in not sent: " + items[0][r.upperBound...] }
            } else if items[0].hasPrefix("skipped: ") {
                e.routine = true; e.text = "Progress check-in skipped: " + items[0].dropFirst(9)
            } else if items[0].hasPrefix("work ended") {
                e.routine = true
                e.text = "Long work ended" + items[0].dropFirst(10) + (items.count > 1 ? "; " + items[1] : "")
            } else {
                e.kind = .problem; e.level = .warn
                e.text = "A progress check-in failed"
                e.detail.append(String(after.prefix(300)))
            }
        case "notify" where rest.hasPrefix("alerts on for ") || rest.hasPrefix("alerts off for "):
            // "alerts off for cse_… "Order page" (window)": the person turned a session's alerts off or on (Alerts.set)
            let on = rest.hasPrefix("alerts on")
            if let id = words.dropFirst(3).first { who(id) }
            named(rest)
            e.kind = .wait
            e.text = on ? "Alerts turned on" : "Alerts turned off"
            e.detail.append((rest.hasSuffix("(phone)") ? "From your phone. " : "From the Kit window. ")
                            + (on ? "It reaches you the ways set in Reach me by." : "Nothing about it goes out; its messages are kept on the session."))
        case "notify" where rest.hasPrefix("alerts of each session are off unless turned on"):
            // once, after the update (Alerts.migrate): "… unless turned on: kept 1 turned off and 1 turned on by hand"
            e.kind = .wait
            e.routine = true
            e.text = "Alerts of each session are off until you turn them on"
            if let r = rest.range(of: ": kept ") {
                e.detail = ["Your choices stay: kept " + rest[r.upperBound...] + ". Every other session's alerts are off."]
            }
        case "notify":
            e.kind = .wait
            // kept in the Kit app (notify.py keep_in_kit()): "<name> kept <id>: <why> | <subject>"
            if let k = rest.range(of: #" kept [0-9a-f]{12}: "#, options: .regularExpression) {
                let title = String(rest[..<k.lowerBound]), id = String(rest[k].dropFirst(6).prefix(12))
                let tail = rest[k.upperBound...]
                let why = tail.range(of: " | ").map { String(tail[..<$0.lowerBound]) } ?? String(tail)
                let subject = tail.range(of: " | ").map { String(tail[$0.upperBound...]) } ?? ""
                if title != "-" { e.name = title; e.session = names.cseByName[title] }
                let m = Kept.find(id)
                if let m, !m.cse.isEmpty { e.session = m.cse }
                e.text = "Message kept in the Kit, not sent" + (subject.isEmpty ? "" : ": " + (m?.subject ?? subject))
                e.detail = ["Not sent: \(why). It is on the session's panel on the Sessions page."]
                if let m, !m.body.isEmpty { e.detail.append("\u{201C}" + m.body.replacingOccurrences(of: "\n\n", with: " ") + "\u{201D}") }
                if why.contains("no way") { e.level = .warn }
                break
            }
            let (main, _, subject) = split(rest)
            let ok = main.contains(" ok")
            let way = ["email", "chat", "text", "push", "app", "notice"].first { main.lowercased().contains(" \($0) ") } ?? ""
            e.text = (ok ? "Message sent" : "Message not sent") + (way.isEmpty ? "" : " by " + way) + (subject.isEmpty ? "" : ": " + subject)
            if !ok { e.kind = .problem; e.level = .warn }
        case "stable":
            e.kind = .update
            if rest.hasPrefix("copy is now") { e.text = "Claude Code updated to " + (words.last ?? "") }
            else if rest.hasPrefix("update waiting:") {
                e.text = "Claude Code update waits for a session to finish"; e.routine = true
                if let n = rest.range(of: ": ").map({ rest[$0.upperBound...] }), let s = n.range(of: " still working") {
                    let q = String(n[..<s.lowerBound]); e.name = q; e.session = names.cseByName[q]
                }
            } else { e.text = "Claude Code: " + rest }
        case "app", "window":
            e.kind = .app
            if rest.hasPrefix("started ") { e.text = "The Kit started (version \(words.last ?? ""))"; e.routine = true }
            else if rest.hasPrefix("update: downloading") || rest.hasPrefix("update: check") { e.kind = .update; e.routine = true; e.text = "Downloading the Kit update" + (words.count > 2 ? " " + words[2] : "") }
            else if rest.hasPrefix("update: installed") { e.kind = .update; e.text = "The Kit updated to \(words.count > 2 ? words[2].trimmingCharacters(in: CharacterSet(charactersIn: ",")) : "")" }
            else if rest.hasPrefix("menu"), let r = rest.range(of: "claude://code/") {
                who(Substring(rest[r.upperBound...].split(separator: " ").first ?? ""))
                e.text = "Opened in the Claude app"; e.detail.append("From the menu bar menu.")
            } else if rest.hasPrefix("waiting notice: ") {
                let q = String(rest.dropFirst(16)); e.name = q; e.session = names.cseByName[q]
                e.kind = .wait; e.text = "Notice: it has waited on you for 10 minutes"
            } else if rest.hasPrefix("waiting notice skipped: "), rest.hasSuffix(": alerts are off") {
                // "waiting notice skipped: Order page login: alerts are off"
                let q = String(rest.dropFirst(24).dropLast(16))
                e.name = q; e.session = names.cseByName[q]
                e.kind = .wait; e.text = "No reminder: alerts are off"
                e.detail = ["It has waited on you for 10 minutes. It shows under Needs you on the Sessions page."]
            } else if rest.hasPrefix("notice not shown, alerts are off: ") {
                // "notice not shown, alerts are off: <title> | <body>": the Kit's own notice (Updater.post)
                let x = rest.dropFirst(34)
                let r = x.range(of: " | ")
                e.text = "Notice not shown, alerts are off: " + (r.map { String(x[..<$0.lowerBound]) } ?? String(x))
                if let r { e.detail = [String(x[r.upperBound...])] }
            } else if rest.hasPrefix("waiting notice skipped: ") {
                // "waiting notice skipped: Order page login: it sent a Reach me by message in the last 30 min", or
                // "…: its alerts are off"
                let body = rest.dropFirst(24)
                let off = body.hasSuffix(": its alerts are off")
                let q = (body.range(of: ": it sent") ?? body.range(of: ": its alerts are off")).map { String(body[..<$0.lowerBound]) } ?? String(body)
                e.name = q; e.session = names.cseByName[q]
                e.kind = .wait
                e.text = off ? "No reminder: its alerts are off" : "No reminder: it sent you a Reach me by message in the last 30 minutes"
                if off { e.detail = ["It has waited on you for 10 minutes. It shows under Needs you on the Sessions page."] }
            } else if rest.hasPrefix("window:") || tag == "window" || rest.hasPrefix("what's new") {
                e.routine = true
                e.text = tag == "window" ? rest.replacingOccurrences(of: "Claude window: ", with: "Claude window in Chrome ") : rest.prefix(1).uppercased() + rest.dropFirst()
                if rest.hasPrefix("window: opened at") { e.text = "Kit window opened" }
            } else if rest.contains("fail") || rest.contains("error") || rest.contains("can't") {
                e.kind = .problem; e.level = .warn; e.text = rest.prefix(1).uppercased() + rest.dropFirst()
            } else { e.text = rest.prefix(1).uppercased() + rest.dropFirst() }
        case "server":   // the Remote Control server: ServerHealth and Server.autoStart
            e.kind = .app
            let r = rest.prefix(1).uppercased() + rest.dropFirst()
            if rest.hasPrefix("not connected: ") || rest.hasPrefix("not started: ") {
                e.kind = .problem; e.level = .warn
                e.text = "Remote Control server " + rest
            } else if rest.hasPrefix("connected: ") {
                e.text = "Remote Control server connected"
                e.detail.append(r.replacingOccurrences(of: "Connected: in", with: "In") + ".")
            } else if rest.hasPrefix("answered yes: ") {
                e.text = "The server asked a question, so the Kit answered yes"
                e.detail.append("It asked to " + rest.dropFirst(14) + ".")
            } else if rest.hasPrefix("answered same-dir: ") {
                e.text = "The server asked which spawn mode to use, so the Kit chose same-dir"
                e.detail.append("Every session starts in the server's folder. Claude Code keeps this answer for the folder.")
            } else if rest.hasPrefix("ended ") {
                e.kind = .problem; e.level = .warn
                let n = words.count > 1 ? String(words[1]) : ""
                e.text = "Ended \(n) old \(n == "1" ? "copy" : "copies") of the Remote Control server"
                e.detail.append("Earlier starts left them running. They kept the folder, so the server could not connect. The Kit ends only its own copies, never a server you started yourself.")
            } else if rest.hasPrefix("stopped, ") {
                e.kind = .restart; e.level = .warn
                e.text = "Remote Control server stopped, and macOS started it again"
            } else if rest.hasPrefix("start command updated") {
                e.text = "Remote Control server: start command updated"; e.routine = true
                e.detail.append("It gives --spawn same-dir when Claude Code has that option. It takes effect when the server starts next.")
            } else if rest.hasPrefix("started again: ") {
                e.kind = .restart; e.level = .warn
                e.text = "Remote Control server started again"
                e.detail.append("Why: " + rest.dropFirst(15) + ".")
            } else { e.text = "Remote Control server: " + rest }
        case "phone":   // Kit on your phone (PhoneLink.swift): the link, the socket, and each action from the phone
            e.kind = .phone
            let host = PhoneLink.shown
            if rest.hasPrefix("action "), let by = rest.range(of: " by ") {
                // "action set_level cse_01Abc by name@sttark.com: ok: Effort is High now. Auto is off for this session."
                let head = rest[rest.index(rest.startIndex, offsetBy: 7)..<by.lowerBound].split(separator: " ")
                let tail = rest[by.upperBound...]
                let parts = tail.components(separatedBy: ": ")
                let asker = parts.first ?? "", reason = parts.count > 1 ? parts[1] : "", said = parts.count > 2 ? parts[2...].joined(separator: ": ") : ""
                if head.count > 1, head[1] != "-" { who(head[1]) }
                e.text = "From the phone: " + (said.isEmpty ? "the Kit did not run it" : said)
                let asked = ["bring_back": "Bring it back now", "stop_waits": "Stop watching", "set_level": "an effort level",
                             "set_auto": "Auto effort", "set_limit": "At the usage limit", "set_alerts": "Alerts",
                             "unarchive": "Unarchive"][String(head.first ?? "")]
                e.detail = ["Asked by \(asker)" + (asked.map { ", with \($0)" } ?? "") + "."]
                if reason == "bad" { e.level = .warn }
            } else if rest.hasPrefix("linked to ") {
                e.text = "This Mac is linked to your phone"
                e.detail = ["Signed in as \(rest.dropFirst(10)). Its sessions show at \(host)."]
            } else if rest.hasPrefix("link page opened") {
                e.text = "Link page opened in your browser"
                let parts = rest.components(separatedBy: ", ")
                e.detail = parts.dropFirst().map { p in p.hasPrefix("code ") ? "This Mac's code: \(p.dropFirst(5))." : p.hasPrefix("until ") ? "It works until \(p.dropFirst(6))." : p }
            } else if rest.hasPrefix("link page ended") {
                e.text = "The link page ended before this Mac was linked"
                e.detail = ["Click Link this Mac… in Settings to try again."]
            } else if rest.hasPrefix("link: ") {
                e.kind = .problem; e.level = .warn
                e.text = rest.hasPrefix("link: no key") ? "This Mac could not make its key for Kit on your phone" : "Could not get a link page from \(host)"
                if let c = rest.range(of: ": ", options: .backwards) { e.detail = ["Why: " + rest[c.upperBound...] + "."] }
            } else if rest.hasPrefix("connected") {
                e.text = "Connected to \(host)"; e.routine = true
                if let a = rest.range(of: " after ") { e.detail = ["It connected " + rest[a.lowerBound...].dropFirst() + "."] }
            } else if rest.hasPrefix("not connected: ") {
                let why = rest.dropFirst(15).components(separatedBy: "; ").first ?? ""
                e.text = "Not connected to \(host): \(why)"
                e.detail = [rest.contains("in a minute") ? "The Kit tries again in a minute."
                            : "The Kit tries again by itself: at once when the Mac wakes or the network changes, else after 1, 2, 4 … 60 seconds."]
            } else if rest.hasPrefix("removed from your phone") {
                e.level = .warn
                e.text = "Removed from your phone"
                e.detail = ["The Kit dropped this Mac's key and does not link it again by itself. To link it again, click Link this Mac… in Settings."]
            } else if rest.hasPrefix("refused (4403)") {
                e.level = .warn
                e.text = "Not on the Sttark roster, so \(host) does not take this Mac"
                e.detail = ["The Kit tries again each hour."]
            } else if rest.hasPrefix("this Mac's key is gone") {
                e.level = .warn
                e.text = "This Mac's key for Kit on your phone is gone, so it is not linked now"
                e.detail = ["To link it again, click Link this Mac… in Settings."]
            } else if rest.hasPrefix("turned off") {
                e.text = "Kit on your phone turned off"
                if let c = rest.range(of: ": ") { e.detail = [rest[c.upperBound...].prefix(1).uppercased() + rest[c.upperBound...].dropFirst() + "."] }
            } else if rest.hasPrefix("bye: ") {
                e.routine = true
                let why = rest.dropFirst(5)
                e.text = why == "sleep" ? "Told \(host) that this Mac sleeps" : why == "update" ? "Told \(host) that the Kit updates" : "Told \(host) that the Kit quits"
            } else if rest.hasPrefix("notice: ") {
                e.text = "Notice: use the Kit on your phone"
            } else if rest.hasPrefix("reminder to your phone: ") {
                let q = String(rest.dropFirst(24)); e.name = q; e.session = names.cseByName[q]
                e.text = "Reminder to your phone: it has waited on you for 10 minutes"
                e.detail = ["You were away from this Mac, so the reminder went to your phone, not to this Mac."]
            } else if rest.hasPrefix("reminder did not go to your phone") {
                e.level = .warn
                if let c = rest.range(of: "instead: ") { let q = String(rest[c.upperBound...]); e.name = q; e.session = names.cseByName[q] }
                e.text = "The reminder did not reach \(host), so this Mac showed it"
            } else if rest.hasPrefix("phones that get notices: ") {
                e.routine = true
                let n = Int(rest.dropFirst(25)) ?? 0
                e.text = n == 0 ? "No phone gets Needs you notices now" : n == 1 ? "1 phone gets Needs you notices" : "\(n) phones get Needs you notices"
            } else if rest.hasPrefix("dry: ") {
                e.routine = true
                e.text = "Dry run: " + rest.dropFirst(5)
            } else if rest.contains("refused") || rest.contains("cannot") || rest.contains("no id") {
                e.level = .warn
                e.text = rest.prefix(1).uppercased() + rest.dropFirst()
            } else {
                e.text = rest.prefix(1).uppercased() + rest.dropFirst()
            }
        case "log":
            e.kind = .app; e.routine = true; e.text = "Old log lines removed"
        case "usage":   // Usage by session (usage-scan.py): the first read of the records, a model with no price, a failed read
            e.kind = .app
            if rest.hasPrefix("first scan: ") {
                e.text = "Read the sessions' records for the Usage page: " + rest.dropFirst(12)
            } else if rest.hasPrefix("no price for ") {
                e.level = .warn
                let model = rest.dropFirst(13).split(separator: " ").first.map(String.init) ?? "a model"
                e.text = "No price for \(model) in the Kit: on the Usage page its use counts at the price of its family"
            } else if rest.hasPrefix("scan failed") {
                e.level = .warn
                e.text = "Could not read the sessions' records for the Usage page"
                e.detail.append(String(rest.prefix(300)))
            } else {
                e.text = "Usage page: " + rest.prefix(160)
            }
        case "error":
            e.kind = .problem; e.level = .error
            if first.hasPrefix("cse_") { who(first) }
            let x = e.session != nil ? String(rest.dropFirst(first.count + 1)) : rest
            if x.hasPrefix("judge failed: TimeoutExpired") { e.text = "Effort check timed out; the level stayed as it was" }
            else if x.hasPrefix("judge failed") { e.text = "Effort check failed; the level stayed as it was" }
            else if x.hasPrefix("unreadable answer") {
                e.text = "Effort check got an answer it could not use; the level stayed as it was"
                if x.contains("safeguards") { e.detail.append("Claude's safety check stopped the effort check for this prompt. The session itself was not stopped.") }
            }
            else if let w = http(x) { e.text = (x.hasPrefix("app list") ? "Could not read the session list from the Claude app: " : "A request to Claude failed: ") + w }
            else { e.text = "Error: " + x.prefix(120) }
        default:
            e.text = tag.prefix(1).uppercased() + tag.dropFirst() + ": " + rest.prefix(160)
        }
        if e.text.isEmpty { return nil }
        e.text = scrub(e.text, names)
        e.detail = e.detail.map { scrub($0, names) }
        if e.level == .info && (rest.contains(" failed") || rest.hasPrefix("can't")) && e.kind != .effort { e.level = .warn }
        return e
    }
}

// MARK: the page

struct EventsPage: View {
    @ObservedObject var model: KitModel
    var body: some View {
        let shown = model.shownEvents
        VStack(alignment: .leading, spacing: 0) {
            EventFilters(model: model)
            Rectangle().fill(K.hair).frame(height: 1)
            if shown.isEmpty {
                Text(model.events.isEmpty ? "Nothing yet. The Kit adds an event here each time it does something." : "No event matches these filters.")
                    .font(K.font(13)).foregroundColor(K.steel).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(Events.days(shown), id: \.day) { d in
                            HStack(spacing: 6) {
                                Text(d.title).font(K.font(12, true))
                                Text("\(d.events.count)").font(K.font(12))
                                Spacer()
                            }
                            .foregroundColor(K.steel)
                            .padding(.horizontal, 8).padding(.top, 14).padding(.bottom, 4)
                            // The day's events, indented one step behind a thin line, as the guide groups a long list.
                            VStack(alignment: .leading, spacing: 0) {
                                ForEach(d.events) { e in
                                    EventRow(model: model, e: e, open: model.openEvent == e.id)
                                    Hairline().padding(.leading, K.z(8))
                                }
                            }
                            .padding(.leading, K.z(12))
                            .overlay(alignment: .leading) { Rectangle().fill(K.hair).frame(width: 1).padding(.leading, K.z(8)) }
                        }
                        if model.shownEventsCut { Text("Showing the newest 1500. Search or filter to find older events.").font(K.font(12)).foregroundColor(K.steel).padding(12) }
                    }
                    .padding(.horizontal, 16).padding(.bottom, 16)
                }
            }
        }
        .onAppear { model.readEvents() }
    }
}

/// The Events page's filters: Kind, Session, Problems only, Routine checks and its own filter of words, which looks in
/// the events (the top bar's search finds sessions). One row when the page is wide enough, else two.
struct EventFilters: View {
    @ObservedObject var model: KitModel
    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) { kind; session; checks; words; Spacer(minLength: 0); clear }
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) { kind; session; Spacer(minLength: 0); clear }
                HStack(spacing: 10) { checks; words; Spacer(minLength: 0) }
            }
        }
        .font(K.font(13))
        .controlSize(K.control)
        .padding(.horizontal, K.z(20))
        .padding(.vertical, K.z(10))
    }

    var kind: some View {
        Picker("Kind", selection: $model.eventKind) {
            Text("All kinds").tag(KitEvent.Kind?.none)
            ForEach(KitEvent.Kind.allCases, id: \.self) { k in Label(k.title, systemImage: k.icon).tag(KitEvent.Kind?.some(k)) }
        }
        .fixedSize()
    }

    var session: some View {
        Picker("Session", selection: $model.eventSession) {
            Text("All sessions").tag(String?.none)
            ForEach(model.eventSessionNames, id: \.self) { Text($0).tag(String?.some($0)) }
        }
        .frame(minWidth: K.z(140), idealWidth: K.z(180), maxWidth: K.z(260), alignment: .leading)
    }

    @ViewBuilder var checks: some View {
        Toggle("Problems only", isOn: $model.eventProblems).toggleStyle(.checkbox).fixedSize()
        Toggle("Routine checks", isOn: $model.eventRoutine).toggleStyle(.checkbox).fixedSize()
            .help("Checks that run all the time and change nothing, such as a reply check that passed")
    }

    /// Words in the events: a filter of this list, not the top bar's search, which finds sessions.
    var words: some View {
        HStack(spacing: 5) {
            Image(systemName: "line.3.horizontal.decrease").foregroundColor(K.steel)
            TextField("Filter events", text: $model.eventSearch).textFieldStyle(.plain).font(K.font(13))
                .accessibilityLabel("Filter events by words")
            if !model.eventSearch.isEmpty {
                Button { model.eventSearch = "" } label: { Image(systemName: "xmark.circle.fill").foregroundColor(K.steel) }
                    .buttonStyle(.plain).accessibilityLabel("Clear the filter")
            }
        }
        .padding(.horizontal, 8)
        .frame(width: K.z(170), height: K.z(26))
        .background(K.card, in: RoundedRectangle(cornerRadius: 6))
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(K.gray))
        .help("Shows only the events with these words. The search at the top finds sessions.")
    }

    @ViewBuilder var clear: some View {
        if model.eventFiltered {
            Button("Clear filters") { model.clearEventFilters() }.buttonStyle(.link).fixedSize()
        }
    }
}

struct EventRow: View {
    @ObservedObject var model: KitModel
    let e: KitEvent
    let open: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(Events.time(e.last)).font(K.font(12)).foregroundColor(K.steel).frame(width: K.z(64), alignment: .leading)
                Image(systemName: e.level == .info ? e.kind.icon : "exclamationmark.triangle.fill")
                    .font(.system(size: 13 * K.zoom))
                    .foregroundColor(e.level == .error ? EventColors.badMark : e.level == .warn ? K.warnMark : K.steel)
                    .frame(width: K.z(18))
                    .accessibilityLabel(e.level == .info ? e.kind.title : e.level == .error ? "Error" : "Warning")
                if let n = e.name {
                    Button { model.goToSession(e) } label: { Text(n).font(K.font(13, true)).foregroundColor(K.ink).fixedSize(horizontal: false, vertical: true) }
                        .buttonStyle(.plain)
                        .layoutPriority(1)
                        .help(e.session != nil && model.snapHas(e.session!) ? "Open this session on the Sessions page" : "Show only this session's events")
                }
                Text(e.text).font(K.font(13)).foregroundColor(e.level == .error ? EventColors.badText : e.level == .warn ? K.warnText : K.ink)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 8)
                if e.count > 1 {
                    Text("\(e.count) times").font(K.font(12, true)).foregroundColor(K.steel)
                        .padding(.horizontal, 7).padding(.vertical, 1)
                        .overlay(Capsule().strokeBorder(K.gray))
                }
                if !e.detail.isEmpty || e.count > 1 {
                    Image(systemName: open ? "chevron.up" : "chevron.down").font(.system(size: 11 * K.zoom)).foregroundColor(K.steel)
                }
            }
            if open {
                VStack(alignment: .leading, spacing: 3) {
                    if e.count > 1 {
                        Text("\(e.count) times, from \(Events.when(e.first)) to \(Events.when(e.last)).")
                    }
                    ForEach(e.detail, id: \.self) { Text($0).fixedSize(horizontal: false, vertical: true) }
                }
                .font(K.font(12.5)).foregroundColor(K.steel)
                .textSelection(.enabled)
                .padding(.leading, K.z(102)).padding(.bottom, 4)
            }
        }
        .padding(.horizontal, 8).padding(.vertical, K.z(7))
        .background(e.level == .error ? EventColors.badSoft : e.level == .warn ? EventColors.warnSoft : (open ? K.wash : .clear),
                    in: RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .onTapGesture { if !e.detail.isEmpty || e.count > 1 { model.openEvent = open ? nil : e.id } }
    }
}

enum EventColors {
    static let badText = Color(nsColor: Tokens.token(0xb42318, 0xf97066))
    static let badMark = Color(nsColor: Tokens.token(0xdf3d33, 0xf97066))
    static let badSoft = Color(nsColor: Tokens.token(0xfdecea, 0x3a1d1a))
    static let warnSoft = Color(nsColor: Tokens.token(0xfdf6d8, 0x2b2512))
}

extension Events {
    struct Day { let day: String; let title: String; let events: [KitEvent] }

    /// Events grouped by the day of their last time: Today, Yesterday, then "Wed, Nov 11".
    static func days(_ events: [KitEvent]) -> [Day] {
        let cal = Calendar.current
        let key = DateFormatter(); key.dateFormat = "yyyy-MM-dd"
        let title = DateFormatter(); title.dateFormat = "EEE, MMM d"
        var order: [String] = [], groups: [String: [KitEvent]] = [:], titles: [String: String] = [:]
        for e in events {
            let k = key.string(from: e.last)
            if groups[k] == nil {
                order.append(k)
                titles[k] = cal.isDateInToday(e.last) ? "Today" : cal.isDateInYesterday(e.last) ? "Yesterday" : title.string(from: e.last)
            }
            groups[k, default: []].append(e)
        }
        return order.map { Day(day: $0, title: titles[$0]!, events: groups[$0]!) }
    }

    static func time(_ d: Date) -> String { let t = DateFormatter(); t.dateFormat = "h:mm a"; return t.string(from: d) }

    /// "11:34 AM" today, "Nov 6, 5:17 PM" another day.
    static func when(_ d: Date) -> String {
        let t = DateFormatter(); t.dateFormat = "h:mm a"
        if Calendar.current.isDateInToday(d) { return t.string(from: d) }
        let f = DateFormatter(); f.dateFormat = "MMM d"
        return f.string(from: d) + ", " + t.string(from: d)
    }
}
