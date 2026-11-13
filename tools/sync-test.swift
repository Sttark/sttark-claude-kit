// Tests Sync: a hook's write to the state reaches the app quickly, many writes make one reload, and the Claude
// app's list from the state file wins over an older minute's check. Runs on a temporary folder, never the real state.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/sync-test tools/sync-test.swift $(ls Sources/*.swift | grep -v main.swift) \
//     && STTARK_KIT_DIR=$(mktemp -d) /tmp/sync-test
import Foundation

@main struct SyncTest {
    static var failed = 0
    static func check(_ ok: Bool, _ what: String) { print((ok ? "ok    " : "FAIL  ") + what); if !ok { failed += 1 } }

    /// A write the way the hooks write: a new file, then a rename over state.json.
    static func hookWrite(_ obj: [String: Any]) {
        let tmp = supportDir.appendingPathComponent("state.json.tmp")
        try! JSONSerialization.data(withJSONObject: obj).write(to: tmp)
        _ = rename(tmp.path, State.file.path)
    }

    static func main() {
        guard ProcessInfo.processInfo.environment["STTARK_KIT_DIR"] != nil else {
            print("Set STTARK_KIT_DIR to a temporary folder."); exit(2)
        }
        hookWrite(["sessions": [:]])
        var times: [Date] = []
        NotificationCenter.default.addObserver(forName: .kitStateChanged, object: nil, queue: .main) { _ in times.append(Date()) }
        Sync.start()
        func spin(_ s: Double) { RunLoop.main.run(until: Date().addingTimeInterval(s)) }
        spin(0.3)

        // one write: the app hears it in well under a second
        var lat: [Double] = []
        for i in 0..<5 {
            times = []
            let t0 = Date()
            hookWrite(["sessions": [:], "n": i])
            spin(1.0)
            if let t = times.first { lat.append(t.timeIntervalSince(t0)) }
        }
        check(lat.count == 5, "each of 5 writes was heard (\(lat.count))")
        let worst = lat.max() ?? 99
        check(worst < 1.0, String(format: "a write shows in under 1 second (worst %.0f ms, mean %.0f ms)",
                                  worst * 1000, lat.reduce(0, +) / Double(max(lat.count, 1)) * 1000))

        // ten writes in a row: one reload
        times = []
        for i in 0..<10 { hookWrite(["sessions": [:], "burst": i]); spin(0.02) }
        spin(0.6)
        check(times.count == 1, "10 writes in a row make 1 reload (\(times.count))")

        // a hold file in holds/ is heard too
        times = []
        try? "{}".write(to: supportDir.appendingPathComponent("holds/test.json"), atomically: true, encoding: .utf8)
        spin(0.6)
        check(times.count == 1, "a change in holds/ is heard")

        // the app's list, newer than the session's minute check, wins: its name, working again, or asking you
        let now = Date().timeIntervalSince1970
        let iso = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-120))
        hookWrite([
            "sessions": [
                "cse_A": ["at": now, "title": "Old name",
                          "app": ["needs": true, "why": "a question", "working": false, "unseen": true,
                                  "last_event_at": iso, "checked": now - 30]],
                "cse_B": ["at": now, "title": "B", "app": ["needs": false, "working": false, "checked": now - 30]],
                "cse_C": ["at": now, "title": "C", "app": ["needs": true, "why": "x", "working": false,
                                                         "last_event_at": iso, "checked": now + 5]],
            ],
            "app_list": ["at": now, "sessions": [
                ["id": "cse_A", "title": "New name", "bucket": "working", "last": iso, "unread": false],
                ["id": "cse_B", "title": "B", "bucket": "blocked", "last": iso, "unread": true],
                ["id": "cse_C", "title": "C", "bucket": "working", "last": iso, "unread": false],
            ]],
        ])
        let ss = Dictionary(uniqueKeysWithValues: State.sessions(hours: 24).map { ($0.id, $0) })
        check(ss["cse_A"]?.title == "New name", "a new name in the Claude app shows")
        check(ss["cse_A"]?.needsYou == false, "a session that works again no longer needs you")
        check(ss["cse_B"]?.needsYou == true, "a session that asks you (blocked, unread) needs you")
        check(ss["cse_C"]?.needsYou == true, "an older list does not change a newer check")
        let snap = Inbox.snapshot(hours: 24)
        check(snap.rows.first { $0.id == "cse_A" }?.group == .working, "the list's working shows as Claude working")

        print(failed == 0 ? "all passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
