import Foundation

/// Every action the window runs on a session, in one place, so the phone runs the same code (phone/DESIGN.md,
/// section 4, and the actions in phone/asyncapi.yaml): bring_back, stop_waits, set_level, set_auto, set_limit and
/// unarchive. Each one:
/// - reads the state again at the moment it runs, never the caller's copy, so a wait that ended or a session that left
///   since the caller looked is refused with nothing changed;
/// - runs off the main thread, and calls `done` on the main thread;
/// - logs with the word for where it came from, `window` or `phone` (the hooks get it as `--by`);
/// - answers with a Result: the reason (ok, gone, not_now, not_here, bad), one line for the person, and the values
///   it changed, before and after.
enum KitActions {
    /// Who asked: a button in the Kit window, or the phone.
    enum Origin: String { case window, phone }

    /// The phone's result names.
    enum Reason: String { case ok, gone, notNow = "not_now", notHere = "not_here", bad }

    /// The words for the person, from phone/DESIGN.md (sections 4 and 13) where it has them.
    enum Words {
        static let waitGone = "That wait already ended. Nothing was changed."
        static let sessionGone = "This session is no longer on your Mac. It may be archived. Nothing was changed."
        static let waiting = "It does not run while it waits. Set the effort when it comes back."
        static let notArchived = "It is not archived now. It is in your list."
        static let notHere = "Its conversation is not on this Mac, so this Mac cannot bring it back."
        static let bad = "This change is not possible for this session. Nothing was changed."
    }

    /// The part of a session an action changed, before or after it. Only the fields that apply are set.
    struct Values: Equatable {
        var level: String? = nil
        var manual: Bool? = nil
        var limitMode: Limit.Mode? = nil
        var waits: [String]? = nil
        var archived: Bool? = nil

        /// As the phone's result sends it (the schema's `state`).
        var json: [String: Any] {
            var j: [String: Any] = [:]
            if let level { j["level"] = level }
            if let manual { j["manual"] = manual }
            if let m = limitMode {
                switch m {
                case .follow: j["limit_mode"] = ["mode": "follow", "at": NSNull()]
                case .credits: j["limit_mode"] = ["mode": "credits", "at": NSNull()]
                case .hold(let n): j["limit_mode"] = ["mode": "hold", "at": n]
                }
            }
            if let waits { j["waits"] = waits }
            if let archived { j["archived"] = archived }
            return j
        }
    }

    struct Result {
        let reason: Reason
        let words: String
        var before: Values? = nil
        var after: Values? = nil
        var ok: Bool { reason == .ok }
        /// The phone's result payload, less its id.
        var json: [String: Any] {
            ["reason": reason.rawValue, "words": String(words.prefix(160)),
             "before": before.map { $0.json as Any } ?? NSNull(), "after": after.map { $0.json as Any } ?? NSNull()]
        }
    }

    // MARK: the actions

    /// Bring it back now: this wait ends now, and its session comes back to the person's list (wait.py --now).
    static func bringBack(wait id: String, origin: Origin, done: @escaping (Result) -> Void = { _ in }) {
        run(done) {
            let open = Waits.list()
            guard let w = open.first(where: { $0.id == id }) else {
                return refused("bring back wait \(id)", origin, Result(reason: .gone, words: Words.waitGone))
            }
            let key = session(w)
            let before = Values(waits: open.filter { session($0) == key }.map(\.id))
            let (code, out) = Updater.run("/usr/bin/python3", [Waits.script, "--now", id, "--by", origin.rawValue])
            let after = Values(waits: Waits.list().filter { session($0) == key }.map(\.id))
            switch code {
            case 0: return Result(reason: .ok, words: last(out) ?? "It is back in your list.", before: before, after: after)
            case 3: return Result(reason: .gone, words: Words.waitGone)
            case 1: return Result(reason: .notNow, words: last(out) ?? "The Kit cannot bring it back now. Try again in a minute.")
            default: return refused("bring back wait \(id)", origin, Result(reason: .bad, words: Words.bad))
            }
        }
    }

    /// Stop waiting (every wait of a session) or Stop (one wait): drops only the waits named, never one added since
    /// the caller looked (wait.py --cancel for each).
    static func stopWaits(_ ids: [String], origin: Origin, done: @escaping (Result) -> Void = { _ in }) {
        run(done) {
            guard !ids.isEmpty else { return refused("stop waits", origin, Result(reason: .bad, words: Words.bad)) }
            let open = Waits.list()
            let mine = open.filter { ids.contains($0.id) }
            guard !mine.isEmpty else {
                return refused("stop waits \(ids.joined(separator: ","))", origin, Result(reason: .gone, words: Words.waitGone))
            }
            let keys = Set(mine.map(session))
            let before = Values(waits: open.filter { keys.contains(session($0)) }.map(\.id))
            var stopped = 0
            for w in mine where Updater.run("/usr/bin/python3", [Waits.script, "--cancel", w.id, "--by", origin.rawValue]).0 == 0 {
                stopped += 1
            }
            let after = Values(waits: Waits.list().filter { keys.contains(session($0)) }.map(\.id))
            guard stopped > 0 else { return Result(reason: .gone, words: Words.waitGone) }
            let ended = ids.count - stopped
            let words = (stopped == 1 ? "Stopped waiting." : "Stopped \(stopped) waits.") + " The session stays where it is."
                + (ended == 0 ? "" : ended == 1 ? " 1 wait already ended." : " \(ended) waits already ended.")
            return Result(reason: .ok, words: words, before: before, after: after)
        }
    }

    /// An effort level picked by the person: the session goes to Manual at that level (effort-hook.py --set).
    static func setLevel(cse: String, level: String, origin: Origin, done: @escaping (Result) -> Void = { _ in }) {
        run(done) {
            guard levels.contains(level) else { return refused("set effort \(level) for \(cse)", origin, Result(reason: .bad, words: Words.bad)) }
            if let no = effortRefusal(cse) { return refused("set effort \(level) for \(cse)", origin, no) }
            let before = effort(cse)
            let (code, _) = Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path,
                                                            "--set", cse, level, "--by", origin.rawValue])
            let after = effort(cse)
            switch code {
            case 0: return Result(reason: .ok, words: "Effort is \(levelNames[level] ?? level) now. Auto is off for this session.",
                                  before: before, after: after)
            case 1: return Result(reason: .notNow, words: "Claude did not receive the change. Try again in a minute.",
                                  before: before, after: after)   // the session is on Manual now, at its old level
            default: return refused("set effort \(level) for \(cse)", origin, Result(reason: .bad, words: Words.bad))
            }
        }
    }

    /// Auto on: Claude picks the session's effort again. Off: the session goes to Manual at its level.
    static func setAuto(cse: String, on: Bool, origin: Origin, done: @escaping (Result) -> Void = { _ in }) {
        run(done) {
            if let no = effortRefusal(cse) { return refused("set Auto \(on ? "on" : "off") for \(cse)", origin, no) }
            let before = effort(cse)
            if before.manual != !on { State.setManual(cse, !on, by: origin) }
            let after = effort(cse)
            let name = after.level.flatMap { levelNames[$0] }
            return Result(reason: .ok, words: on ? "Auto is on. Claude sets the effort for each task."
                                                 : "Auto is off. " + (name.map { "The effort stays at \($0)." } ?? "You set the effort."),
                          before: before, after: after)
        }
    }

    /// The session's At the usage limit setting. `cse` or `sid` finds the session; a session that runs only on this
    /// Mac has no `cse`.
    static func setLimit(cse: String, sid: String?, mode: Limit.Mode, origin: Origin, done: @escaping (Result) -> Void = { _ in }) {
        run(done) {
            let what = "set the usage limit setting for \(cse.isEmpty ? sid ?? "" : cse)"
            if case .hold(let n) = mode, !(1...100).contains(n) { return refused(what, origin, Result(reason: .bad, words: Words.bad)) }
            guard let t = row(cse: cse, sid: sid ?? "")?.target else {
                return refused(what, origin, Result(reason: .gone, words: Words.sessionGone))
            }
            let before = Values(limitMode: Limit.mode(t))
            Limit.setMode(mode, for: t, by: origin)
            let after = Values(limitMode: Limit.mode(t))
            let words: String
            switch mode {
            case .follow: words = "It uses the usage limit setting in Settings now."
            case .credits: words = "It always uses usage credits at the limit now."
            case .hold(let n): words = "It never uses usage credits now. It holds at \(n)%."
            }
            return Result(reason: .ok, words: words, before: before, after: after)
        }
    }

    /// Bring it back, for an archived session: unarchived on the same link, with its whole conversation and nothing
    /// sent to it (wait.py --unarchive, which reads its status and archived.json when it runs).
    static func unarchive(cse: String, origin: Origin, done: @escaping (Result) -> Void = { _ in }) {
        run(done) {
            let (code, out) = Updater.run("/usr/bin/python3", [Waits.script, "--unarchive", cse, "--by", origin.rawValue])
            switch code {
            case 0: return Result(reason: .ok, words: last(out) ?? "It is back in your list.",
                                  before: Values(archived: true), after: Values(archived: false))
            case 3: return Result(reason: .gone, words: Words.notArchived)
            case 2: return Result(reason: .notHere, words: Words.notHere)
            case 1: return Result(reason: .notNow, words: last(out) ?? "It did not come back.")
            default: return refused("bring back \(cse) from the archive", origin, Result(reason: .bad, words: Words.bad))
            }
        }
    }

    // MARK: the live state

    /// The session's row in the inbox now, as the window and the phone show it: by its Remote Control id, else by
    /// Claude Code's id. Nil when it is in no group, idle included.
    static func row(cse: String, sid: String = "") -> Inbox.Row? {
        let rows = Inbox.snapshot(hours: 24).rows
        if !cse.isEmpty, let r = rows.first(where: { $0.id == cse }) { return r }
        return rows.first { r in
            guard let t = r.target else { return false }
            return (!cse.isEmpty && t.cse == cse) || (!sid.isEmpty && t.sid == sid)
        }
    }

    /// Why an effort change can't run now: the session is in no group, or it waits on someone else.
    private static func effortRefusal(_ cse: String) -> Result? {
        guard let r = row(cse: cse) else { return Result(reason: .gone, words: Words.sessionGone) }
        if r.wait != nil { return Result(reason: .notNow, words: Words.waiting) }
        return nil
    }

    /// The session's level and Manual, as the state file has them now.
    private static func effort(_ cse: String) -> Values {
        let x = (State.read()["sessions"] as? [String: Any])?[cse] as? [String: Any] ?? [:]
        return Values(level: (x["level"] as? String).flatMap { levels.contains($0) ? $0 : nil }, manual: x["manual"] as? Bool ?? false)
    }

    /// Which session a wait belongs to, as the inbox groups them: one row per session.
    private static func session(_ w: Waits.Wait) -> String { w.cse.isEmpty ? "wait:" + w.id : w.cse }

    /// The last line a command printed: its words for the person.
    private static func last(_ out: String) -> String? {
        out.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.last { !$0.isEmpty }
    }

    /// A refusal before anything ran: logged here, since no hook saw it.
    private static func refused(_ what: String, _ origin: Origin, _ r: Result) -> Result {
        note("\(what) (\(origin.rawValue)): \(r.reason.rawValue), nothing changed")
        return r
    }

    /// Runs the action off the main thread and answers on it.
    private static func run(_ done: @escaping (Result) -> Void, _ work: @escaping () -> Result) {
        DispatchQueue.global(qos: .userInitiated).async {
            let r = work()
            DispatchQueue.main.async { done(r) }
        }
    }
}
