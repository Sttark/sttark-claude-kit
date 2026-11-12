// Tests the app's side of each session's usage setting (Sources/Limit.swift) on a temporary folder: a stand-in
// state file and usage file, never the real ones. Reading and writing limit_modes as the hooks do, the log lines,
// the holding sessions the menu lists, and when the menu says the limit is reached.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/limit-menu-test tools/limit-menu-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/limit-menu-test
import Foundation

@main struct LimitMenuTest {
    static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-modetest-\(getpid())")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        var fails = 0
        func check(_ name: String, _ ok: Bool) { print((ok ? "ok   " : "FAIL ") + name); if !ok { fails += 1 } }
        let now = Date().timeIntervalSince1970
        // the hook set it by session id (a typed phrase), an older menu entry by cse
        let state: [String: Any] = ["limit_modes": [
            "11111111-aaaa": ["mode": "hold", "at": 70, "sid": "11111111-aaaa", "by": "typed", "set_at": now - 10],
            "cse_X": ["mode": "credits", "cse": "cse_X", "by": "menu", "set_at": now - 100],
            "22222222-bbbb": ["mode": "hold", "at": 90, "sid": "22222222-bbbb", "set_at": now],
        ], "limit_pauses": [
            "11111111-aaaa": ["sid": "11111111-aaaa", "cse": "cse_X", "title": "One", "pid": Int(getpid()), "mode": "hold", "at": 70,
                              "percent": 72, "since": now - 60, "until": now + 600, "limit": "5-hour"],
            "11111111-aaaa/ag1": ["sid": "11111111-aaaa", "agent": "ag1", "cse": "cse_X", "title": "One", "pid": Int(getpid()),
                                  "mode": "hold", "at": 70, "since": now - 30, "until": now + 900, "limit": "5-hour"],
            "33333333-dead": ["sid": "33333333-dead", "title": "Gone", "pid": 999999, "since": now, "until": now + 60],
            "44444444-old": ["title": "Old row", "pid": Int(getpid()), "since": now - 5, "until": now + 60, "limit": "weekly"],
        ]]
        try! JSONSerialization.data(withJSONObject: state).write(to: dir.appendingPathComponent("state.json"))
        let t = Limit.Target(sid: "11111111-aaaa", cse: "cse_X", title: "One")
        check("newest of two entries wins (hold 70 over credits)", Limit.mode(t) == .hold(70))
        check("found by cse alone", Limit.mode(Limit.Target(sid: "", cse: "cse_X", title: "")) == .credits)
        check("other session untouched", Limit.mode(Limit.Target(sid: "22222222-bbbb", cse: "", title: "")) == .hold(90))
        check("unknown session follows the menu", Limit.mode(Limit.Target(sid: "nope", cse: "cse_nope", title: "")) == .follow)
        Limit.setMode(.hold(50), for: t)
        var m = State.read()["limit_modes"] as! [String: [String: Any]]
        check("set from the menu: one entry, under the cse", m.keys.sorted() == ["22222222-bbbb", "cse_X"] && m["cse_X"]?["at"] as? Int == 50
              && m["cse_X"]?["by"] as? String == "menu" && m["cse_X"]?["sid"] as? String == "11111111-aaaa")
        Limit.setMode(.hold(50), for: t)   // no change: no log line
        Limit.setMode(.follow, for: t)
        m = State.read()["limit_modes"] as! [String: [String: Any]]
        check("follow removes it", m.keys.sorted() == ["22222222-bbbb"])
        Limit.setMode(.credits, for: Limit.Target(sid: "55555555-term", cse: "", title: "Terminal"))
        m = State.read()["limit_modes"] as! [String: [String: Any]]
        check("no cse: keyed by session id", m["55555555-term"]?["mode"] as? String == "credits")
        let log = (try? String(contentsOf: dir.appendingPathComponent("log"), encoding: .utf8)) ?? ""
        print(log, terminator: "")
        let lines = log.split(separator: "\n")
        check("three limit lines, hook format", lines.count == 3 && lines.allSatisfy { $0.dropFirst(20).hasPrefix("limit  mode   ") }
              && lines[0].hasSuffix("limit  mode   11111111 never use credits; hold at 50% (menu)")
              && lines[1].hasSuffix("mode   11111111 follow the menu (menu)") && lines[2].hasSuffix("mode   55555555 always use credits (menu)"))
        let w = Limit.waiting
        check("one row per session, dead row dropped", w.count == 2 && w.map(\.sid).contains("11111111-aaaa") && w.map(\.sid).contains("44444444-old"))
        let one = w.first { $0.sid == "11111111-aaaa" }!
        check("main row with its agent counted", one.agents == 1 && one.hold && one.at == 70 && one.percent == 72 && one.until.timeIntervalSince1970 == now + 900)
        let old = w.first { $0.sid == "44444444-old" }!
        check("an old row without mode is a wait at 100%", !old.hold && old.at == 100)
        check("dead row removed from the file", (State.read()["limit_pauses"] as! [String: Any])["33333333-dead"] == nil)

        // the stand-in usage file: the menu says "Usage limit reached" only at 100% with credits on the account
        func usage(_ percent: Int, credits: Bool = true, scoped: Bool = false, resetsIn: Double = 3600) {
            let f = ISO8601DateFormatter()
            f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            var l: [String: Any] = ["kind": "session", "percent": percent, "resets_at": f.string(from: Date().addingTimeInterval(resetsIn))]
            if scoped { l["kind"] = "weekly_scoped"; l["scope"] = ["model": ["display_name": "Sample"]] }
            let u: [String: Any] = ["at": Date().timeIntervalSince1970, "usage": ["extra_usage": ["is_enabled": credits], "limits": [l]]]
            try! JSONSerialization.data(withJSONObject: u).write(to: dir.appendingPathComponent("usage.json"))
        }
        usage(100)
        check("reached at 100% with credits", Limit.reached?.name == "5-hour")
        usage(84)
        check("not reached at 84% (a hold below the limit is a row, not this)", Limit.reached == nil)
        usage(100, credits: false)
        check("not reached without credits on the account", Limit.reached == nil)
        usage(100, scoped: true)
        check("a model's own limit is not shown as reached", Limit.reached == nil)
        usage(100, resetsIn: -60)
        check("a reset time that has passed is not reached", Limit.reached == nil)
        try? FileManager.default.removeItem(at: dir)
        print(fails == 0 ? "all passed" : "\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
