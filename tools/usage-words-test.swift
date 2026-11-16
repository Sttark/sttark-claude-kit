// Tests the Usage page's human work estimate in words (Sources/SessionUsage.swift): one person's time, people full
// time in a period, the hours, and the ⓘ note made from the scan's factors; and that a period adds up the human hours
// of each kind of work from a made-up usage/by-session.json in a temporary folder, never the real one. The phone says
// the same words (phone/src/view/human.ts), with the same examples.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/usage-words-test tools/usage-words-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/usage-words-test
import Foundation

@main struct UsageWordsTest {
    static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-wordstest-\(getpid())")
        try? FileManager.default.createDirectory(at: dir.appendingPathComponent("usage"), withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        var fails = 0
        func check(_ name: String, _ ok: Bool) { print((ok ? "ok   " : "FAIL ") + name); if !ok { fails += 1 } }
        func same(_ got: String, _ want: String) { check("\(want)" + (got == want ? "" : " (got: \(got))"), got == want) }

        // one person
        same(SessionUsage.personWords(0.25), "1 person for 15 minutes")
        same(SessionUsage.personWords(0.004), "1 person for 1 minute")
        same(SessionUsage.personWords(0.995), "1 person for 1 hour")
        same(SessionUsage.personWords(6), "1 person for 6 hours")
        same(SessionUsage.personWords(7.5), "1 person for 7.5 hours")
        same(SessionUsage.personWords(8), "1 person for 1 day")
        same(SessionUsage.personWords(20), "1 person for 2.5 days")
        same(SessionUsage.personWords(79), "1 person for 9.9 days")
        same(SessionUsage.personWords(80), "1 person for 2 weeks")
        same(SessionUsage.personWords(519), "1 person for 13 weeks")
        same(SessionUsage.personWords(520), "1 person for 3 months")
        same(SessionUsage.personWords(809.4), "1 person for 4.7 months")
        same(SessionUsage.personWords(4160), "1 person for 2 years")
        same(SessionUsage.personWords(10000), "1 person for 4.8 years")
        // people full time in a period: 8 hours each weekday, at least one day
        same(SessionUsage.peopleWords(809.4, .week, from: "2026-11-10", to: "2026-11-16"), "≈ 20 people full time over these 7 days")
        same(SessionUsage.peopleWords(3, .today, from: "2026-11-15", to: "2026-11-15"), "less than 1 person full time today")
        same(SessionUsage.peopleWords(12, .today, from: "2026-11-16", to: "2026-11-16"), "≈ 1.5 people full time today")
        same(SessionUsage.peopleWords(8, .today, from: "2026-11-16", to: "2026-11-16"), "≈ 1 person full time today")
        same(SessionUsage.peopleWords(100, .custom("2026-11-02", "2026-11-09"), from: "2026-11-02", to: "2026-11-09"),
             "≈ 2.1 people full time from Nov 2 to Nov 9")
        same(SessionUsage.peopleWords(9, .custom("2026-11-04", "2026-11-04"), from: "2026-11-04", to: "2026-11-04"),
             "≈ 1.1 people full time on Wed, Nov 4")
        same(SessionUsage.peopleWords(3000, .month, from: "2026-10-18", to: "2026-11-16"), "≈ 18 people full time over these 30 days")
        check("weekdays: Tue to Mon is 5, a Saturday alone counts as 1",
              SessionUsage.weekdays(from: "2026-11-10", to: "2026-11-16") == 5 && SessionUsage.weekdays(from: "2026-11-14", to: "2026-11-14") == 1)
        same(SessionUsage.hoursWords(182.4), "182\u{00A0}h")
        same(SessionUsage.hoursWords(2.46), "2.5\u{00A0}h")
        same(SessionUsage.hoursWords(0.04), "<\u{00A0}0.1\u{00A0}h")
        same(SessionUsage.num(1240.2), "1,240")
        let kinds = [SessionUsage.Kind(id: "software", name: "Software", x: 12), SessionUsage.Kind(id: "design", name: "Design", x: 5),
                     SessionUsage.Kind(id: "admin", name: "Browser and admin", x: 2.5), SessionUsage.Kind(id: "small", name: "Small or mixed", x: 2)]
        let note = SessionUsage.humanNote(kinds)
        same(note, "An estimate. The Kit counts the hours Claude was at work, its agents too: the model writing and the tools it ran. "
             + "Waits do not count: for you, at the usage limit, for checks and timers. Each hour counts as the hours a person needs "
             + "for that kind of work: software 12, design 5, browser and admin 2.5, small or mixed 2. Full time is 8 hours a day, 5 days a week.")

        // a period adds up human hours by kind: a made-up by-session.json as usage-scan.py writes it
        let list: [String: Any] = [
            "v": 1, "at": Date().timeIntervalSince1970, "keep_days": 45, "days": ["2026-11-14", "2026-11-15", "2026-11-16"],
            "models": [["id": "claude-opus-5-5", "name": "Opus 5.5", "priced": true]],
            "sessions": [["key": "cse:cse_A", "kind": "session", "cse": "cse_A", "title": "A", "last": 1794800000],
                         ["key": "cse:cse_B", "kind": "session", "cse": "cse_B", "title": "B", "last": 1794800000]],
            "rows": [[0, 2, 0, 10.0, 30.0, 1000, 3000], [1, 2, 0, 1.0, 0.0, 100, 0], [0, 0, 0, 5.0, 5.0, 10, 10]],
            "agents": [], "unpriced": [:],
            "kinds": [["id": "software", "name": "Software", "x": 12], ["id": "design", "name": "Design", "x": 5],
                      ["id": "admin", "name": "Browser and admin", "x": 2.5], ["id": "small", "name": "Small or mixed", "x": 2]],
            // [session, day, kind, seconds]: A has 2 h of software and 1 h of admin on the 16th, 1 h of design on the 14th;
            // B has 30 min of small work
            "work": [[0, 2, 0, 7200], [0, 2, 2, 3600], [0, 0, 1, 3600], [1, 2, 3, 1800], [0, 2, 9, 3600]],
        ]
        try! JSONSerialization.data(withJSONObject: list).write(to: dir.appendingPathComponent("usage/by-session.json"))
        let data = SessionUsage.read()
        check("the kinds and their factors are read, and a row with no such kind is left out", data.kinds.count == 4 && data.work.count == 4)
        let today = SessionUsage.report(data, from: "2026-11-16", to: "2026-11-16")
        let a = today.lines.first { $0.session.title == "A" }, b = today.lines.first { $0.session.title == "B" }
        check("a session's human hours: each kind at its factor (2 h x 12 + 1 h x 2.5)", abs((a?.human ?? 0) - 26.5) < 1e-9
              && abs((a?.active ?? 0) - 3) < 1e-9 && abs((a?.humanByKind[0] ?? 0) - 24) < 1e-9 && abs((a?.humanByKind[2] ?? 0) - 2.5) < 1e-9)
        check("a small session at its factor (30 min x 2)", abs((b?.human ?? 0) - 1) < 1e-9)
        check("the period's total: only its days", abs(today.human - 27.5) < 1e-9 && abs(today.active - 3.5) < 1e-9)
        let three = SessionUsage.report(data, from: "2026-11-14", to: "2026-11-16")
        check("a longer period adds the day before (1 h of design x 5)", abs(three.human - 32.5) < 1e-9)

        // the phone's list carries the numbers and the factors, rounded to 0.1 h
        let phone = Phone.usage(period: "today", data: data, now: SessionUsage.date("2026-11-16")!.addingTimeInterval(12 * 3600)) ?? [:]
        let total = phone["total"] as? [String: Any] ?? [:], rows = phone["rows"] as? [[String: Any]] ?? []
        check("the phone's list: the total's and each row's human hours", (total["human_hours"] as? Double) == 27.5
              && rows.compactMap { $0["human_hours"] as? Double }.sorted() == [1.0, 26.5])
        check("the phone's list: the factors, by name", ((phone["factors"] as? [[String: Any]]) ?? []).map { "\($0["name"] ?? "")=\($0["x"] ?? "")" }
              == ["Software=12.0", "Design=5.0", "Browser and admin=2.5", "Small or mixed=2.0"])

        try? FileManager.default.removeItem(at: dir)
        print(fails == 0 ? "\nall passed" : "\n\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
