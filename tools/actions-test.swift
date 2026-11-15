// Tests KitActions (Sources/Actions.swift), the one place for every action the window and the phone run, on copies:
// a temporary Kit folder with its own copy of the hooks, a temporary log, a temporary ~/.claude and a stand-in for
// Claude's list of sessions. STTARK_WAIT_DRY, STTARK_EFFORT_DRY and STTARK_NOTIFY_DRY: nothing is brought back,
// started, sent to a session or sent to a person. Each action from the window and from the phone, with its result,
// before and after, and log line; a wait that already ended, a wait not named that stays, an effort change while the
// session waits, a session in no group, a bad level, an archived session whose conversation is not on this Mac, and
// one that is not archived any more. Each answer comes on the main thread, after the call returned.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/actions-test tools/actions-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/actions-test
import Foundation

@main struct ActionsTest {
    static var fails = 0
    static func check(_ name: String, _ ok: Bool) { print((ok ? "ok    " : "FAIL  ") + name); if !ok { fails += 1 } }

    static func main() {
        let fm = FileManager.default
        let tmp = fm.temporaryDirectory.appendingPathComponent("kit-actions-\(getpid())")
        let kit = tmp.appendingPathComponent("kit"), claude = tmp.appendingPathComponent("claude")
        let proj = claude.appendingPathComponent("projects/-Users-test-src")
        try! fm.createDirectory(at: kit.appendingPathComponent("hooks"), withIntermediateDirectories: true)
        try! fm.createDirectory(at: proj, withIntermediateDirectories: true)
        let list = tmp.appendingPathComponent("sessions.json"), logFile = tmp.appendingPathComponent("kit.log")
        for (k, v) in ["STTARK_KIT_DIR": kit.path, "STTARK_KIT_LOG": logFile.path, "STTARK_CLAUDE_DIR": claude.path,
                       "STTARK_ARCHIVED_TEST": list.path, "STTARK_WAIT_DRY": "1", "STTARK_EFFORT_DRY": "1",
                       "STTARK_NOTIFY_DRY": "1", "STTARK_CLAUDE_KIT_TEST": "1"] { setenv(k, v, 1) }
        check("the app's folder is the test copy", supportDir.path == kit.path && hooksDir.path.hasPrefix(tmp.path))
        // this repo's hooks, copied, as the app copies them out of itself
        let src = URL(fileURLWithPath: fm.currentDirectoryPath).appendingPathComponent("Resources/hooks")
        for f in try! fm.contentsOfDirectory(atPath: src.path) where f.hasSuffix(".py") {
            try! fm.copyItem(at: src.appendingPathComponent(f), to: hooksDir.appendingPathComponent(f))
        }

        let now = Date().timeIntervalSince1970
        let convA = proj.appendingPathComponent("aaaa1111.jsonl")
        try! (#"{"type": "user", "cwd": "/Users/test/src/order-page", "message": {"content": "hello"}}"# + "\n").write(to: convA, atomically: true, encoding: .utf8)
        func wait(_ id: String, _ cse: String, _ title: String, kind: String = "at", extra: [String: Any] = [:]) -> [String: Any] {
            ["id": id, "cse": cse, "title": title, "kind": kind, "target": "t-\(id)", "at": now + 3600, "by": now + 3600,
             "why": "a reason", "set_at": now - 60].merging(extra) { $1 }
        }
        let state: [String: Any] = [
            "sessions": [
                "cse_IDLE": ["title": "Order page", "level": "medium", "manual": false, "at": now - 600,
                             "transcript": "/Users/test/.claude/projects/x/sid-idle-1.jsonl"],
                "cse_WAIT": ["title": "Supplier reply", "level": "high", "manual": false, "at": now - 300],
            ],
            "waits": [
                "w1": wait("w1", "cse_WAIT", "Supplier reply"),
                "w2": wait("w2", "cse_TWO", "Two waits", kind: "email-reply"),
                "w3": wait("w3", "cse_TWO", "Two waits"),
                "wb": wait("wb", "cse_BACK", "Came back", extra: ["stage": "back", "back_at": now]),
            ],
        ]
        try! JSONSerialization.data(withJSONObject: state).write(to: State.file)
        let item = { (cse: String, transcript: String) -> [String: Any] in
            ["cse": cse, "title": "Archived " + cse, "folder": "/Users/test/src/order-page", "transcript": transcript,
             "archived_at": now - 7200, "url": "https://claude.ai/code/session_" + cse.dropFirst(4), "doing": ""]
        }
        try! JSONSerialization.data(withJSONObject: ["at": now, "rev": "0123456789abcdef", "items": [
            item("cse_A", convA.path), item("cse_B", proj.appendingPathComponent("nothere.jsonl").path)]])
            .write(to: kit.appendingPathComponent("archived.json"))
        try! JSONSerialization.data(withJSONObject: ["sessions": [
            ["id": "cse_A", "status": "archived", "title": "Archived cse_A"],
            ["id": "cse_B", "status": "archived", "title": "Archived cse_B"],
            ["id": "cse_O", "status": "active", "title": "Open one"]]]).write(to: list)

        /// Runs one action as the window and the phone do: it returns at once, and its answer comes on the main thread.
        func act(_ name: String, _ f: (@escaping (KitActions.Result) -> Void) -> Void) -> KitActions.Result {
            var r: KitActions.Result?
            var onMain = false
            f { onMain = Thread.isMainThread; r = $0 }
            let atOnce = r == nil
            let end = Date().addingTimeInterval(30)
            while r == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.02)) }
            guard let r else { check(name + ": answered", false); return KitActions.Result(reason: .bad, words: "no answer") }
            if !(atOnce && onMain) { check(name + ": ran off the main thread and answered on it", false) }
            let j = r.json
            if !(Set(j.keys) == ["reason", "words", "before", "after"] && (j["words"] as? String ?? "").count <= 160 && !r.words.isEmpty) {
                check(name + ": the phone's result shape", false)
            }
            print("      \(name): \(r.reason.rawValue) \"\(r.words)\"")
            return r
        }
        func log() -> String { (try? String(contentsOf: logFile, encoding: .utf8)) ?? "" }
        func session(_ cse: String) -> [String: Any] { (State.read()["sessions"] as? [String: Any])?[cse] as? [String: Any] ?? [:] }
        func openWaits() -> [String] { Waits.list().map(\.id).sorted() }
        let W = KitActions.Words.self

        // bring_back
        var r = act("bring_back w1 (phone)") { KitActions.bringBack(wait: "w1", origin: .phone, done: $0) }
        check("bring_back: ok, wait.py --now ran (dry)", r.reason == .ok && r.words.contains("would bring back w1") && r.before?.waits == ["w1"])
        check("bring_back: the log says the phone asked", log().contains("w1 cse_WAIT \"Supplier reply\" The person asked to bring it back now (phone)"))
        r = act("bring_back of no such wait") { KitActions.bringBack(wait: "gone1", origin: .window, done: $0) }
        check("a wait that is not there: gone, with the design's words, logged", r.reason == .gone && r.words == W.waitGone
              && r.before == nil && log().contains("bring back wait gone1 (window): gone, nothing changed"))
        r = act("bring_back of a wait that already brought its session back") { KitActions.bringBack(wait: "wb", origin: .phone, done: $0) }
        check("a wait that already ended: gone, and it is left as it was", r.reason == .gone && r.words == W.waitGone
              && (State.read()["waits"] as? [String: Any])?["wb"] != nil)

        // stop_waits
        r = act("stop_waits [w2] (phone)") { KitActions.stopWaits(["w2"], origin: .phone, done: $0) }
        check("Stop (one wait): ok, the session's other wait stays", r.reason == .ok && r.before?.waits?.sorted() == ["w2", "w3"]
              && r.after?.waits == ["w3"] && openWaits() == ["w1", "w3"] && log().contains("wait   w2 cancelled (phone)"))
        r = act("stop_waits [w2] again") { KitActions.stopWaits(["w2"], origin: .window, done: $0) }
        check("a wait stopped since: gone, nothing changed", r.reason == .gone && r.words == W.waitGone && openWaits() == ["w1", "w3"])
        r = act("stop_waits [w3, w9] (window)") { KitActions.stopWaits(["w3", "w9"], origin: .window, done: $0) }
        check("Stop waiting: only the ids named; w1, not named, stays", r.reason == .ok && r.after?.waits == []
              && r.words.contains("1 wait already ended") && openWaits() == ["w1"] && log().contains("wait   w3 cancelled (window)"))
        r = act("stop_waits []") { KitActions.stopWaits([], origin: .phone, done: $0) }
        check("no ids: bad", r.reason == .bad)

        // set_level
        r = act("set_level cse_IDLE high (phone)") { KitActions.setLevel(cse: "cse_IDLE", level: "high", origin: .phone, done: $0) }
        check("set_level: ok, Manual at High, before and after", r.reason == .ok
              && r.before == KitActions.Values(level: "medium", manual: false) && r.after == KitActions.Values(level: "high", manual: true)
              && r.words == "Effort is High now. Auto is off for this session.")
        check("set_level: effort-hook.py --set logs the phone, and sent nothing (dry)",
              log().contains("manual cse_IDLE set to high (phone) (dry: nothing sent); leaving this session alone"))
        r = act("set_level while it waits") { KitActions.setLevel(cse: "cse_WAIT", level: "low", origin: .phone, done: $0) }
        check("an effort change while the session waits: not_now, nothing changed", r.reason == .notNow && r.words == W.waiting
              && session("cse_WAIT")["level"] as? String == "high" && session("cse_WAIT")["manual"] as? Bool == false
              && log().contains("set effort low for cse_WAIT (phone): not_now, nothing changed"))
        r = act("set_level for a session in no group") { KitActions.setLevel(cse: "cse_NONE", level: "low", origin: .phone, done: $0) }
        check("a session in no group: gone, with the design's words", r.reason == .gone && r.words == W.sessionGone && session("cse_NONE").isEmpty)
        r = act("set_level huge") { KitActions.setLevel(cse: "cse_IDLE", level: "huge", origin: .phone, done: $0) }
        check("not a level: bad, nothing changed", r.reason == .bad && session("cse_IDLE")["level"] as? String == "high")

        // set_auto
        r = act("set_auto cse_IDLE on (window)") { KitActions.setAuto(cse: "cse_IDLE", on: true, origin: .window, done: $0) }
        check("set_auto on: ok, Manual off", r.reason == .ok && r.before?.manual == true && r.after?.manual == false
              && session("cse_IDLE")["manual"] as? Bool == false && log().contains("app    cse_IDLE set to Auto (window)"))
        r = act("set_auto cse_IDLE off (phone)") { KitActions.setAuto(cse: "cse_IDLE", on: false, origin: .phone, done: $0) }
        check("set_auto off: ok, Manual at its level", r.reason == .ok && r.after == KitActions.Values(level: "high", manual: true)
              && r.words == "Auto is off. The effort stays at High." && log().contains("cse_IDLE set to Manual (phone)"))
        let lines = log().components(separatedBy: "\n").count
        r = act("set_auto off again") { KitActions.setAuto(cse: "cse_IDLE", on: false, origin: .phone, done: $0) }
        check("set_auto to what it is now: ok, no write and no log line", r.reason == .ok && r.before == r.after
              && log().components(separatedBy: "\n").count == lines)
        r = act("set_auto while it waits") { KitActions.setAuto(cse: "cse_WAIT", on: false, origin: .phone, done: $0) }
        check("Auto while the session waits: not_now", r.reason == .notNow && r.words == W.waiting && session("cse_WAIT")["manual"] as? Bool == false)
        r = act("set_auto for a session in no group") { KitActions.setAuto(cse: "cse_NONE", on: true, origin: .window, done: $0) }
        check("Auto for a session in no group: gone", r.reason == .gone && r.words == W.sessionGone)

        // set_limit
        func modes() -> [String: [String: Any]] { Limit.dicts(State.read()["limit_modes"]) }
        r = act("set_limit cse_IDLE hold 70 (phone)") { KitActions.setLimit(cse: "cse_IDLE", sid: nil, mode: .hold(70), origin: .phone, done: $0) }
        check("set_limit: ok, before and after, stored by the phone", r.reason == .ok && r.before?.limitMode == .follow && r.after?.limitMode == .hold(70)
              && modes()["cse_IDLE"]?["by"] as? String == "phone" && modes()["cse_IDLE"]?["sid"] as? String == "sid-idle-1")
        check("set_limit: the limit line says the phone", log().contains("limit  mode   sid-idle never use credits; hold at 70% (phone)"))
        r = act("set_limit by its session id only (window)") { KitActions.setLimit(cse: "", sid: "sid-idle-1", mode: .credits, origin: .window, done: $0) }
        check("found by Claude Code's id: ok, one entry", r.reason == .ok && r.after?.limitMode == .credits && modes().count == 1
              && log().contains("mode   sid-idle always use credits (window)"))
        r = act("set_limit while it waits") { KitActions.setLimit(cse: "cse_WAIT", sid: nil, mode: .credits, origin: .window, done: $0) }
        check("the usage setting while the session waits: ok, as the window shows it", r.reason == .ok && r.after?.limitMode == .credits)
        r = act("set_limit for a session in no group") { KitActions.setLimit(cse: "cse_NONE", sid: nil, mode: .credits, origin: .phone, done: $0) }
        check("the usage setting for a session in no group: gone, nothing stored", r.reason == .gone && r.words == W.sessionGone && modes()["cse_NONE"] == nil)
        r = act("set_limit hold 0") { KitActions.setLimit(cse: "cse_IDLE", sid: nil, mode: .hold(0), origin: .phone, done: $0) }
        check("hold at 0%: bad, nothing changed", r.reason == .bad && Limit.mode(Limit.Target(sid: "sid-idle-1", cse: "cse_IDLE", title: "")) == .credits)

        // unarchive
        r = act("unarchive cse_A (phone)") { KitActions.unarchive(cse: "cse_A", origin: .phone, done: $0) }
        check("unarchive: ok, wait.py --unarchive ran (dry)", r.reason == .ok && r.words.contains("would bring cse_A back")
              && r.before == KitActions.Values(archived: true) && r.after == KitActions.Values(archived: false))
        r = act("unarchive cse_B (window)") { KitActions.unarchive(cse: "cse_B", origin: .window, done: $0) }
        check("an archived session with no conversation here: not_here, with the design's words", r.reason == .notHere && r.words == W.notHere
              && log().contains("cse_B \"Archived cse_B\" not brought back from the archive (window): its conversation is not on this Mac"))
        r = act("unarchive cse_O (phone)") { KitActions.unarchive(cse: "cse_O", origin: .phone, done: $0) }
        check("a session that is not archived any more: gone, with the design's words", r.reason == .gone && r.words == W.notArchived
              && log().contains("cse_O \"Open one\" not brought back from the archive (phone): it is not archived now"))
        r = act("unarchive a bad id") { KitActions.unarchive(cse: "nonsense", origin: .phone, done: $0) }
        check("a bad id: bad", r.reason == .bad)

        check("the phone's payload: reason and words, before and after null when nothing changed",
              (KitActions.Result(reason: .gone, words: W.waitGone).json["before"] is NSNull)
              && (KitActions.Values(limitMode: .hold(70)).json["limit_mode"] as? [String: Any])?["at"] as? Int == 70)
        print(log().components(separatedBy: "\n").filter { !$0.isEmpty }.map { "      log: " + $0.dropFirst(20) }.joined(separator: "\n"))
        try? fm.removeItem(at: tmp)
        print(fails == 0 ? "ok" : "\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
