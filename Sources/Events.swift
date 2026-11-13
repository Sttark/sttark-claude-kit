import AppKit
import SwiftUI

/// What the Kit did, in plain words, for the window's Events page. Read from the Kit's log and the bypass log, and
/// never shown as raw lines: each line becomes one sentence about one session, under the session's name.
struct KitEvent: Identifiable, Equatable {
    enum Kind: String, CaseIterable {
        case effort, limit, restart, name, wait, update, check, app, problem
        var title: String {
            switch self {
            case .effort: return "Effort and permissions"
            case .limit: return "Usage limit"
            case .restart: return "Sessions started again"
            case .name: return "Session names"
            case .wait: return "Waits and messages"
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
            case .wait: return "hourglass"
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

    /// Problems that happen again fold into one row wherever they fall (with how many times, since when, and the
    /// last time); anything else folds with the same event just before it, or within a minute.
    static func fold(_ events: [KitEvent]) -> [KitEvent] {
        var out: [KitEvent] = []
        var at: [String: Int] = [:]
        for e in events {
            if let i = at[e.key], e.level != .info || e.first.timeIntervalSince(out[i].last) < 60 || i == out.count - 1 {
                out[i].count += 1; out[i].last = e.last; continue
            }
            out.append(e)
            at[e.key] = out.count - 1
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
                else if main.contains("archived or deleted") { e.text = "Archived in the Claude app, so the Kit stopped it" }
                else if let q = main.range(of: "\"", options: .backwards) {
                    let x = main[q.upperBound...].trimmingCharacters(in: .whitespaces)
                    e.text = x.prefix(1).uppercased() + x.dropFirst()
                }
            }
            if !reason.isEmpty { e.detail.append("Why: " + reason) }
            promptDetail(prompt)
        case "manual":
            e.kind = .effort
            let (main, _, prompt) = split(rest)
            who(first)
            e.text = main.contains("left at") ? "Effort is on Manual, left at " + level(main.split(separator: " ").last ?? "") : "Effort set by hand"
            e.routine = true
            promptDetail(prompt)
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
        case "wake", "start", "reattach", "move", "handover", "standdown":
            e.kind = .restart
            who(first); named(rest)
            switch tag {
            case "wake": e.text = "Stopped while not archived, so the Kit started it again"
            case "start": e.text = "Had stopped, so the Kit started it again"
            case "reattach": e.text = "Unarchived, so the Kit started it on the same link"
                e.detail = ["The server does not start a session that was archived. The Kit runs it on its own, and it answers the messages sent after it was unarchived."]
            case "move": e.text = "Moved to a new link, and the old entry archived"; e.level = .warn
                e.detail = ["Claude Code could not keep its old link. Its Routines moved with it."]
            case "handover": e.text = "The server runs it again, so the Kit closed its own copy"
            default: e.text = "Taken over in another place, so the Kit closed its own copy"; e.level = .warn
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
                    e.detail.append(["menu": "From the menu or the window.", "typed": "Typed in the session.", "command": "From the claude-limit-mode command."][String(src)]
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
        case "notify":
            e.kind = .wait
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
            } else if rest.hasPrefix("started again: ") {
                e.kind = .restart; e.level = .warn
                e.text = "Remote Control server started again"
                e.detail.append("Why: " + rest.dropFirst(15) + ".")
            } else { e.text = "Remote Control server: " + rest }
        case "log":
            e.kind = .app; e.routine = true; e.text = "Old log lines removed"
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

struct EventFilters: View {
    @ObservedObject var model: KitModel
    var body: some View {
        HStack(spacing: 10) {
            Picker("Kind", selection: $model.eventKind) {
                Text("All kinds").tag(KitEvent.Kind?.none)
                ForEach(KitEvent.Kind.allCases, id: \.self) { k in Label(k.title, systemImage: k.icon).tag(KitEvent.Kind?.some(k)) }
            }
            .fixedSize()
            Picker("Session", selection: $model.eventSession) {
                Text("All sessions").tag(String?.none)
                ForEach(model.eventSessionNames, id: \.self) { Text($0).tag(String?.some($0)) }
            }
            .frame(maxWidth: K.z(260))
            Toggle("Problems only", isOn: $model.eventProblems).toggleStyle(.checkbox)
            Toggle("Routine checks", isOn: $model.eventRoutine).toggleStyle(.checkbox)
                .help("Checks that run all the time and change nothing, such as a reply check that passed")
            Spacer()
            if model.eventFiltered {
                Button("Clear filters") { model.clearEventFilters() }.buttonStyle(.link)
            }
        }
        .font(K.font(13))
        .controlSize(K.control)
        .padding(.horizontal, K.z(20))
        .padding(.vertical, K.z(10))
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
