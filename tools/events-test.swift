// Tests the Events page's reading of the log and the trim of the logs, on a temporary folder, never the real logs.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/events-test tools/events-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/events-test
import Foundation

@main struct EventsTest {
    static var failed = 0
    static func check(_ ok: Bool, _ what: String) { print((ok ? "ok    " : "FAIL  ") + what); if !ok { failed += 1 } }

    static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("events-test-\(getpid())")
        try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        func at(_ m: Double) -> String { f.string(from: Date().addingTimeInterval(-m * 60)) }

        // Names come from the Kit's state file.
        var names = Events.Names()
        names.byCse["cse_01AAAtest1"] = "Press color"; names.cseByName["Press color"] = "cse_01AAAtest1"
        names.bySid["f46255ef-0000"] = "Press color"; names.cseBySid["f46255ef-0000"] = "cse_01AAAtest1"

        var lines = [
            at(30) + " change cse_01AAAtest1 low->high (2.0s) high - Needs judgment. | Fix the color page",
            at(20) + " limit  hold   f46255ef/a10a43cb at 90%: the weekly limit is at 93%, until Sat 2:00 AM (Bash)",
            at(20) + " limit  wait   f46255ef/a10a43cb at 90%: the weekly limit is at 93%, until Sat 2:00 AM, with no model calls until it ends",
            at(10) + " ste    f46255ef ok (3.1s)",
            at(5) + " migrate 3796db69 \"Bin label sizes\" moved to Remote Control as cse_01BBBtest2; closed it in Terminal (window)",
        ]
        for m in stride(from: 50.0, through: 1, by: -7) { lines.append(at(m) + " limit  usage read failed: HTTP Error 429: Too Many Requests; next read in 2 min, using the last read") }
        lines.sort()
        let log = dir.appendingPathComponent("kit.log")
        try! (lines.joined(separator: "\n") + "\n").write(to: log, atomically: true, encoding: .utf8)
        let ev = Events.read(kitLog: log, bypassLog: dir.appendingPathComponent("none.log"), names: names)

        let change = ev.first { $0.kind == .effort }
        check(change?.name == "Press color" && change?.text == "Effort raised from Low to High", "an effort change reads in plain words under the session's name")
        check(change?.detail.contains("Why: Needs judgment.") == true, "the reason is in the row's detail")
        let holds = ev.filter { $0.kind == .limit }
        check(holds.count == 1 && holds[0].text == "Held: the weekly limit is at 93%. Goes on Sat 2:00 AM", "a hold and its wait are one row")
        let usage = ev.filter { $0.kind == .problem }
        check(usage.count == 1 && usage[0].count == 8 && usage[0].level == .warn, "a problem that occurs again is one row with its count")
        check(ev.first { $0.kind == .check }?.routine == true, "a reply check that passed is routine")
        check(ev.first?.last ?? .distantPast >= ev.last?.last ?? .distantFuture, "newest first")
        check(!ev.contains { $0.text.contains("cse_") || $0.text.contains("f46255ef") }, "no ids in the sentences")
        let moved = ev.first { $0.text == "Moved to Remote Control from this Mac only" }
        check(moved?.name == "Bin label sizes" && moved?.detail.contains { $0.contains("open in Terminal") } == true,
              "a move to Remote Control reads in plain words under the session's name")

        // Trim: 30 days, lines with no date go with the dated line before them, a writer that holds the file open
        // in append mode (as launchd does) goes on at the new end, and a second trim finds nothing to cut.
        var s = ""
        for day in stride(from: 40, through: 0, by: -1) {
            for i in 0..<3 { s += f.string(from: Date().addingTimeInterval(-Double(day) * 86400 + Double(i))) + " app    day \(day) #\(i)\n" + (i == 1 ? "  no date\n" : "") }
        }
        let t = dir.appendingPathComponent("t.log")
        try! s.write(to: t, atomically: true, encoding: .utf8)
        let fd = open(t.path, O_WRONLY | O_APPEND)
        let r = KitLogs.trim(t)
        _ = "late line\n".withCString { write(fd, $0, strlen($0)) }
        close(fd)
        let out = try! String(contentsOf: t, encoding: .utf8).split(separator: "\n")
        check(r != nil && out.first?.contains("day 30 #0") == true, "lines older than 30 days are cut")
        check(out.last == "late line", "a line written after the trim lands at the end")
        check(KitLogs.trim(t) == nil, "a second trim cuts nothing")
        let big = String(repeating: f.string(from: Date()) + " app    " + String(repeating: "x", count: 90) + "\n", count: 2000)
        try! big.write(to: t, atomically: true, encoding: .utf8)
        _ = KitLogs.trim(t, bytes: 50_000)
        let kept = try! Data(contentsOf: t)
        check(kept.count <= 50_000 && kept.first == UInt8(ascii: "2"), "the size cap keeps whole lines, the newest")

        // A menu click on a session shows as that session opened in the Claude app, with no raw link or id.
        let m = Events.kitLine(f.string(from: Date()) + " app    menu   open claude://code/cse_01AAAtest1", names)
        check(m?.name == "Press color" && m?.text == "Opened in the Claude app", "a menu open names the session, no link")
        let w = Events.kitLine(f.string(from: Date()) + " wait   7f15a1 cse_01AAAtest1 \"Press color\" set: a reply on email thread 1a1d6158534acc04, by Wed 5:00 PM", names)
        check(w.map { !$0.text.contains("1a1d6158") && !$0.text.contains("cse_") } == true, "no email thread id in a wait row")

        print(failed == 0 ? "all passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
