// Tests that the waits and the session rows keep one order. The state keeps waits, sessions and holds in dictionaries,
// which have no order of their own; with ties in the sort key (two waits with the same deadline, two sessions at the
// same second), rows changed places from one read to the next. This writes the same made-up state many times, each
// time with its keys in a new shuffled order, and checks that Waits.list, the Sessions page's groups, State.sessions
// and the holds at the usage limit come out the same each time, and in the expected order. Runs on a temporary
// folder, never the real state. Run from the repo root:
//   swiftc -parse-as-library -o /tmp/order-test tools/order-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/order-test
import Foundation

@main struct OrderTest {
    static var failed = 0
    static func check(_ ok: Bool, _ what: String) { print((ok ? "ok    " : "FAIL  ") + what); if !ok { failed += 1 } }

    /// JSON text with every object's keys in a random order, as a hook or the app could write them.
    static func shuffled(_ v: Any) -> String {
        if let d = v as? [String: Any] {
            return "{" + d.keys.shuffled().map { k in shuffled(k) + ":" + shuffled(d[k]!) }.joined(separator: ",") + "}"
        }
        if let a = v as? [Any] { return "[" + a.map(shuffled).joined(separator: ",") + "]" }
        return String(data: try! JSONSerialization.data(withJSONObject: v, options: [.fragmentsAllowed]), encoding: .utf8)!
    }

    static func write(_ state: [String: Any]) {
        let tmp = supportDir.appendingPathComponent("state.json.tmp")
        try! shuffled(state).data(using: .utf8)!.write(to: tmp)
        _ = rename(tmp.path, State.file.path)
    }

    static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-ordertest-\(getpid())")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        defer { try? FileManager.default.removeItem(at: dir) }

        let now = (Date().timeIntervalSince1970).rounded()
        let deadline = now + 3600, later = now + 86400
        let pid = Int(getpid())
        // made-up sessions: three at the same second, two of them with the same name
        var sessions: [String: Any] = [:]
        for (id, title) in [("cse_A1", "Press 4 job"), ("cse_B2", "Supplier quote"), ("cse_C3", "Press 4 job"),
                            ("cse_D4", "Chiller service"), ("cse_E5", "Label die order"), ("cse_F6", "Roll stock count"),
                            ("cse_G7", "Ink order"), ("cse_H8", "Press 4 job")] {
            sessions[id] = ["title": title, "at": now - 600, "level": "medium"]
        }
        // made-up waits: ties on the deadline, on when they were set, and on the session's name
        func wait(_ cse: String, _ title: String, by: Double?, setAt: Double?) -> [String: Any] {
            var w: [String: Any] = ["cse": cse, "title": title, "kind": "at", "what": "A reply", "why": "test", "stage": "wait"]
            if let by { w["by"] = by }
            if let setAt { w["set_at"] = setAt }
            return w
        }
        let waits: [String: Any] = [
            "w1": wait("cse_A1", "Press 4 job", by: deadline, setAt: now - 50),
            "w2": wait("cse_B2", "Supplier quote", by: deadline, setAt: now - 100),
            "w3": wait("cse_C3", "Press 4 job", by: deadline, setAt: now - 50),
            "w4": wait("cse_D4", "Chiller service", by: later, setAt: now - 10),
            "w5": wait("cse_E5", "Label die order", by: later, setAt: now - 10),
            "w6": wait("cse_F6", "Roll stock count", by: nil, setAt: nil),
            "w7": wait("cse_G7", "Ink order", by: nil, setAt: now - 5),
            "w8": wait("cse_A1", "Press 4 job", by: later, setAt: now - 5),   // a second wait of cse_A1
            "w9": ["cse": "cse_H8", "title": "Press 4 job", "kind": "at", "what": "A reply", "by": deadline, "stage": "back"],   // came back: not listed
        ]
        // made-up holds at the usage limit: two sessions that started holding at the same second
        let pauses: [String: Any] = [
            "sid-two": ["sid": "sid-two", "title": "Supplier quote", "pid": pid, "since": now - 30, "until": now + 600, "limit": "5-hour"],
            "sid-one": ["sid": "sid-one", "title": "Ink order", "pid": pid, "since": now - 30, "until": now + 600, "limit": "5-hour"],
            "sid-zero": ["sid": "sid-zero", "title": "Ink order", "pid": pid, "since": now - 30, "until": now + 600, "limit": "5-hour"],
        ]
        let state: [String: Any] = ["sessions": sessions, "waits": waits, "limit_pauses": pauses]

        let wantWaits = ["w2", "w1", "w3", "w4", "w5", "w8", "w7", "w6"]
        let wantRows = ["cse_B2", "cse_A1", "cse_C3", "cse_D4", "cse_E5", "cse_G7", "cse_F6"]
        let wantIdle = ["cse_H8"]
        let wantHolds = ["sid-one", "sid-zero", "sid-two"]
        var seenWaits = Set<[String]>(), seenRows = Set<[String]>(), seenIdle = Set<[String]>(),
            seenSessions = Set<[String]>(), seenHolds = Set<[String]>(), seenA1 = Set<[String]>()
        for _ in 0..<60 {
            write(state)
            let s = State.read()
            seenWaits.insert(Waits.list(s).map(\.id))
            let snap = Inbox.snapshot()
            seenRows.insert(snap.rows(.waits).map(\.id))
            seenA1.insert(snap.rows(.waits).first { $0.id == "cse_A1" }?.waits.map(\.id) ?? [])
            seenIdle.insert(snap.rows(.idle).map(\.id))
            seenSessions.insert(State.sessions(hours: 24).map(\.id))
            seenHolds.insert(Limit.waiting.map(\.sid))
        }
        check(seenWaits == [wantWaits], "Waits.list: one order in 60 shuffled reads, deadline, set, name, id: \(seenWaits.map { $0.joined(separator: " ") })")
        check(seenRows == [wantRows], "Waiting on someone else rows: one order by each session's first wait: \(seenRows.map { $0.joined(separator: " ") })")
        check(seenA1 == [["w1", "w8"]], "a session's own waits: one order, first deadline first")
        check(seenIdle == [wantIdle], "idle rows: one order")
        check(seenSessions.count == 1, "State.sessions: one order for sessions at the same second (\(seenSessions.count) seen)")
        check(seenSessions.first.map { Array($0.prefix(3)) } == ["cse_D4", "cse_G7", "cse_E5"],
              "State.sessions: same time, then name, then id: \(seenSessions.first ?? [])")
        check(seenHolds == [wantHolds], "Limit.waiting: one order for holds that started at the same second: \(seenHolds.map { $0.joined(separator: " ") })")

        // claude-wait --list, the same state: one order, the same as the window's
        let hook = URL(fileURLWithPath: "Resources/hooks/wait.py").path
        var seenList = Set<[String]>()
        for _ in 0..<20 {
            write(state)
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = [hook, "--list"]
            p.environment = ProcessInfo.processInfo.environment.merging(["STTARK_WAIT_DRY": "1"]) { $1 }
            let out = Pipe()
            p.standardOutput = out
            p.standardError = FileHandle.nullDevice
            try! p.run()
            p.waitUntilExit()
            let text = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            seenList.insert(text.split(separator: "\n").compactMap { $0.split(separator: " ").first.map(String.init) })
        }
        check(seenList == [wantWaits + ["w9"]], "claude-wait --list: one order, as the window's: \(seenList.map { $0.joined(separator: " ") })")

        print(failed == 0 ? "All passed." : "\(failed) failed.")
        exit(failed == 0 ? 0 : 1)
    }
}
