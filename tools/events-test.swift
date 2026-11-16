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
            at(8) + " agent  cse_01AAAtest1 Explore ->low (1.9s) low - Simple file search. | Find the color files",
            at(7) + " agent  cse_01AAAtest1 fork high->xhigh (2.2s) xhigh - Builds a feature end to end. | Build the page",
            at(6) + " agent  cse_01AAAtest1 general-purpose kept high - set in the call | Check the build",
            at(5) + " migrate 3796db69 \"Bin label sizes\" moved to Remote Control as cse_01BBBtest2; closed it in Terminal (window)",
        ]
        for m in stride(from: 50.0, through: 1, by: -7) { lines.append(at(m) + " limit  usage read failed: HTTP Error 429: Too Many Requests; next read in 2 min, using the last read") }
        for m in [2880.0, 2875, 2870] { lines.append(at(m) + " limit  usage read failed: HTTP Error 429: Too Many Requests; next read in 2 min, using the last read") }
        lines.sort()
        let log = dir.appendingPathComponent("kit.log")
        try! (lines.joined(separator: "\n") + "\n").write(to: log, atomically: true, encoding: .utf8)
        let ev = Events.read(kitLog: log, bypassLog: dir.appendingPathComponent("none.log"), names: names)

        let change = ev.first { $0.kind == .effort && $0.text.hasPrefix("Effort raised from Low") }
        check(change?.name == "Press color" && change?.text == "Effort raised from Low to High", "an effort change reads in plain words under the session's name")
        check(change?.detail.contains("Why: Needs judgment.") == true, "the reason is in the row's detail")
        let holds = ev.filter { $0.kind == .limit }
        check(holds.count == 1 && holds[0].text == "Held: the weekly limit is at 93%. Goes on Sat 2:00 AM", "a hold and its wait are one row")
        let usage = ev.filter { $0.kind == .problem }
        check(usage.count == 2 && usage[0].count == 8 && usage[0].level == .warn && usage[1].count == 3,
              "a problem that occurs again is one row a day, with that day's count")
        check(ev.first { $0.kind == .check }?.routine == true, "a reply check that passed is routine")
        check(ev.first?.last ?? .distantPast >= ev.last?.last ?? .distantFuture, "newest first")
        check(!ev.contains { $0.text.contains("cse_") || $0.text.contains("f46255ef") }, "no ids in the sentences")
        let agent = ev.first { $0.text == "Agent \u{201C}Find the color files\u{201D} set to Low effort" }
        check(agent?.name == "Press color" && agent?.detail.contains("Why: Simple file search.") == true,
              "a subagent's pick reads in plain words under its session's name")
        check(ev.contains { $0.text == "Effort raised from High to Extra so fork \u{201C}Build the page\u{201D} starts at Extra" },
              "a raise for a fork says why")
        check(ev.contains { $0.text == "Agent \u{201C}Check the build\u{201D} keeps High effort" && $0.routine }, "an effort set in the call is kept, as a routine row")
        let moved = ev.first { $0.text == "Moved to Remote Control from this Mac only" }
        check(moved?.name == "Bin label sizes" && moved?.detail.contains { $0.contains("open in Terminal") } == true,
              "a move to Remote Control reads in plain words under the session's name")

        // The Remote Control server: what its health check does, in plain words, with the problems as problems
        let server = [
            at(9) + " server ended 25 old copies of the server that earlier starts left running",
            at(8) + " server answered same-dir: the spawn mode, so every session starts in ~/src",
            at(7) + " server not connected: it waits on a question the Kit can't answer: Region [1/2]:",
            at(6) + " server stopped, and macOS started it again",
            at(5) + " server not connected: it stopped 3 times soon after it started; it showed: Error: x. The Kit starts it again in 1 min.",
            at(4) + " server start command updated: it gives --spawn same-dir when Claude Code has it, from the next start",
            at(3) + " keep   the server is not connected: 4 session(s) on it wait until it connects, and none starts on its own",
        ]
        let slog = dir.appendingPathComponent("server.log")
        try! (server.joined(separator: "\n") + "\n").write(to: slog, atomically: true, encoding: .utf8)
        let sev = Events.read(kitLog: slog, bypassLog: dir.appendingPathComponent("none.log"), names: names)
        check(sev.contains { $0.kind == .problem && $0.level == .warn && $0.text == "Ended 25 old copies of the Remote Control server" },
              "old copies of the server that were ended are a problem row, with how many")
        check(sev.contains { $0.text == "The server asked which spawn mode to use, so the Kit chose same-dir" && $0.level == .info },
              "the spawn mode answer reads in plain words")
        check(sev.filter { $0.kind == .problem && $0.text.hasPrefix("Remote Control server not connected: ") }.count == 2,
              "a question the Kit can't answer, and a server that stops again and again, are problem rows")
        check(sev.contains { $0.kind == .restart && $0.level == .warn && $0.text == "Remote Control server stopped, and macOS started it again" },
              "a server that stopped and came back is a warning")
        check(sev.contains { $0.routine && $0.text == "Remote Control server: start command updated" }, "the updated start command is a routine row")
        check(sev.contains { $0.kind == .restart && $0.level == .warn && $0.text == "Sessions on the server wait until it connects" },
              "sessions that wait for the server read in plain words")

        // A session started on its own: its folder trusted in Claude Code first, and a start that waits at the trust question
        let trust = [
            at(4) + " trust  /Users/x/src/airpark home trusted in Claude Code, so a chat that ran there starts without its safety question",
            at(3) + " trust  /Users/x/src/other could not be marked trusted in Claude Code: PermissionError(13, 'Permission denied')",
            at(2) + " keep   cse_01AAAtest1 \"Press color\" won't start, and starting it on a new link didn't work either - it waits in kit-6850f368 at Claude Code's question whether to trust /Users/x/src/airpark home",
        ]
        let tlog = dir.appendingPathComponent("trust.log")
        try! (trust.joined(separator: "\n") + "\n").write(to: tlog, atomically: true, encoding: .utf8)
        let tev = Events.read(kitLog: tlog, bypassLog: dir.appendingPathComponent("none.log"), names: names)
        check(tev.contains { $0.kind == .restart && $0.routine && $0.text == "Trusted a session's folder in Claude Code"
                             && $0.detail.first == "Folder: /Users/x/src/airpark home" }, "a folder trusted for a session is a routine row, with the folder")
        check(tev.contains { $0.level == .warn && $0.text == "Could not trust a session's folder in Claude Code"
                             && $0.detail.first == "Folder: /Users/x/src/other" }, "a folder that could not be trusted is a warning")
        let stuck = tev.first { $0.name == "Press color" }
        check(stuck?.text == "Won't start, and starting it on a new link didn't work either"
              && stuck?.detail.contains("Why: it waits in kit-6850f368 at Claude Code's question whether to trust /Users/x/src/airpark home") == true,
              "a start that waits at the trust question says why")

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
        // Bring it back on the Archived page (claude-wait --unarchive): the session, in plain words, and who asked
        let b = Events.kitLine(f.string(from: Date()) + " wait   cse_01AAAtest1 \"Press color\" brought back from the archive (window)", names)
        check(b?.name == "Press color" && b?.text == "Brought back from the archive, on the same link" && b?.kind == .restart
              && b?.detail.first?.contains("the Kit window") == true, "a session brought back from the archive")
        let n = Events.kitLine(f.string(from: Date()) + " wait   cse_01AAAtest1 \"Press color\" not brought back from the archive (phone): its conversation is not on this Mac", names)
        check(n?.text == "Not brought back: its conversation is not on this Mac" && n?.level == .warn
              && n?.detail.first?.contains("the phone") == true, "one that could not come back says why")

        print(failed == 0 ? "all passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
