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

        // the log's short id, the hooks' rule
        check("short id: first 8 of the session id", Limit.short(sid: "abcdef12-3456", cse: "cse_01Zzzzzzzz") == "abcdef12")
        check("short id: 8 after cse_ for a session known only by its cse", Limit.short(sid: "", cse: "cse_01AbCdEfGhIj") == "01AbCdEf")

        // A state file as the hooks write it (Python's json.dump: ints and floats, null, keys with "/"), with entries
        // that are not dictionaries next to good ones. A held call is keyed "<sid>/<tool call id>", with `agent` set
        // for an agent's call; the wait command's own loop "<sid>" or "<sid>/<agent>".
        let py = "abcdef12-3456-7890-abcd-ef1234567890"
        let pid = Int(getpid())
        let n0 = Int(now)
        let pyState = """
        {"limit_credits_all": false, "limit_credits": {"77777777-cccc": \(now + 1000), "passed": \(n0 - 10), "odd": "x"}, \
        "limit_modes": {"cse_01PyFixture0000000001": {"mode": "hold", "at": 75, "by": "typed", "set_at": \(now - 5), \
        "sid": "\(py)", "cse": "cse_01PyFixture0000000001", "title": "Py session"}, \
        "bad-entry": "not a dict", "also-bad": [1, 2], \
        "77777777-cccc": {"mode": "credits", "by": "command", "set_at": \(n0), "sid": "77777777-cccc"}}, \
        "limit_pauses": {\
        "\(py)/toolu_main1": {"since": \(now - 100.5), "until": \(now + 600.25), "limit": "5-hour", "cse": "cse_01PyFixture0000000001", \
        "title": "Py session", "pid": \(pid), "what": "hold", "sid": "\(py)", "agent": null, "mode": "hold", "at": 75, "percent": 77.0}, \
        "\(py)/toolu_ag1a": {"since": \(now - 90), "until": \(now + 700), "limit": "5-hour", "title": "Py session", "pid": \(pid), \
        "what": "hold", "sid": "\(py)", "agent": "agent-one", "mode": "hold", "at": 75, "percent": 77}, \
        "\(py)/toolu_ag1b": {"since": \(now - 80), "until": \(now + 700), "limit": "5-hour", "title": "Py session", "pid": \(pid), \
        "what": "hold", "sid": "\(py)", "agent": "agent-one", "mode": "hold", "at": 75, "percent": 77}, \
        "\(py)/toolu_ag2": {"since": \(now - 70), "until": \(now + 650), "limit": "5-hour", "title": "Py session", "pid": \(pid), \
        "what": "hold", "sid": "\(py)", "agent": "agent-two", "mode": "hold", "at": 75}, \
        "\(py)/toolu_dead": {"since": \(now - 60), "until": \(now + 9000), "limit": "5-hour", "title": "Py session", "pid": 999999, \
        "what": "hold", "sid": "\(py)", "agent": "agent-three", "mode": "hold", "at": 75}, \
        "99999999-dddd/agent-x": {"since": \(n0 - 50), "until": \(n0 + 60), "limit": "weekly", "title": "Agent only", "pid": \(pid), \
        "what": "wait", "sid": "99999999-dddd", "agent": "agent-x", "mode": "follow", "at": 100, "percent": 100}, \
        "88888888-eeee": {"since": \(n0 - 40), "until": \(n0 + 30), "title": "No sid field", "pid": \(pid)}, \
        "bad-row": "nope"}}
        """
        try! pyState.data(using: .utf8)!.write(to: dir.appendingPathComponent("state.json"))
        check("Python entry found by its sid field (keyed by cse)", Limit.mode(Limit.Target(sid: py, cse: "", title: "")) == .hold(75))
        check("Python entry found by cse", Limit.mode(Limit.Target(sid: "", cse: "cse_01PyFixture0000000001", title: "")) == .hold(75))
        check("bad entries hide nothing: an int set_at entry still reads", Limit.mode(Limit.Target(sid: "77777777-cccc", cse: "", title: "")) == .credits)
        let pw = Limit.waiting
        check("Python rows: one row per session, the bad row left out", pw.count == 3
              && Set(pw.map(\.sid)) == [py, "99999999-dddd", "88888888-eeee"])
        if let r = pw.first(where: { $0.sid == py }) {
            check("the session's own held call is its row (agent null)", r.hold && r.at == 75 && r.percent == 77 && r.since.timeIntervalSince1970 == now - 100.5)
            check("agents counted once each: two parallel calls of one agent, and a second agent", r.agents == 2)
            check("until is the latest of its live rows (not the dead one's)", r.until.timeIntervalSince1970 == now + 700)
        } else { check("Python session row present", false) }
        if let r = pw.first(where: { $0.sid == "99999999-dddd" }) {
            check("an agent's own wait, with no row of the session: shown, one agent", !r.hold && r.at == 100 && r.agents == 1 && r.title == "Agent only")
        } else { check("agent-only session row present", false) }
        if let r = pw.first(where: { $0.sid == "88888888-eeee" }) {
            check("a row with no sid field: the key names the session", r.agents == 0 && !r.hold)
        } else { check("row without sid present", false) }
        let left = State.read()["limit_pauses"] as? [String: Any] ?? [:]
        check("a dead call drops only its own row", left["\(py)/toolu_dead"] == nil && left["\(py)/toolu_main1"] != nil
              && left["\(py)/toolu_ag1a"] != nil && left["\(py)/toolu_ag1b"] != nil && left["\(py)/toolu_ag2"] != nil
              && left["99999999-dddd/agent-x"] != nil && left["bad-row"] != nil)

        // the switch and the click write `limit` lines, as the hooks do, not `app` lines
        let before = ((try? String(contentsOf: dir.appendingPathComponent("log"), encoding: .utf8)) ?? "").split(separator: "\n").count
        Limit.setCreditsAll(true)
        check("switch on", Limit.creditsAll)
        Limit.setCreditsAll(false)
        let row = Limit.waiting.first { $0.sid == py }!
        Limit.useCredits(row)
        let credits = State.read()["limit_credits"] as? [String: Any] ?? [:]
        check("Use credits: this session until its reset, other sessions kept, passed ones dropped",
              Limit.num(credits[py]) == row.until.timeIntervalSince1970 && Limit.num(credits["77777777-cccc"]) == now + 1000
              && credits["passed"] == nil)
        let newLines = ((try? String(contentsOf: dir.appendingPathComponent("log"), encoding: .utf8)) ?? "")
            .split(separator: "\n").dropFirst(before).map(String.init)
        newLines.forEach { print($0) }
        check("switch and click: three `limit` lines, no `app` line", newLines.count == 3 && newLines.allSatisfy { $0.dropFirst(20).hasPrefix("limit  credits ") })
        check("switch on line", newLines.first?.hasSuffix("limit  credits every session uses credits at the limit, except one set to hold (menu)") == true)
        check("switch off line", newLines.dropFirst().first?.hasSuffix("limit  credits every session waits at the limit, except one set to use credits (menu)") == true)
        check("click line, with the short id", newLines.last?.hasSuffix("limit  credits abcdef12 uses credits until \(Limit.clock(row.until)) (menu)") == true)

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
