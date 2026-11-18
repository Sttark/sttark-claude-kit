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

        // Only the person archives: the Kit's own lines say it stopped sessions without archiving them, and why it ran one on its own
        let noArchive = [
            at(5) + " halt   the Mac shuts down: ended 3 Claude Code process(es) of 3 chat(s) the Kit runs, so none is archived",
            at(4) + " reattach cse_01AAAtest2 \"Bird deterrent\" the server won't start it (2 wakes did not start it), so it runs on its own on the same link, from 113",
            at(3) + " reattach cse_01AAAtest3 \"Facility map\" the server won't start it (it was archived, then unarchived), so it runs on its own on the same link, from 9",
            at(2) + " keep   cse_01AAAtest4 \"Rivian claims\" archived or deleted in the Claude app while it was stopped; left it so",
            at(1) + " move   cse_01AAAtest5 \"JetFly\" the server won't start it (2 wakes did not start it), so it runs on its own as cse_01AAAtest6; 0 Routine(s) moved, old entry renamed \"(old link)\" and left in the list",
        ]
        let klog = dir.appendingPathComponent("kept.log")
        try! (noArchive.joined(separator: "\n") + "\n").write(to: klog, atomically: true, encoding: .utf8)
        let kev = Events.read(kitLog: klog, bypassLog: dir.appendingPathComponent("none.log"), names: names)
        check(kev.contains { $0.routine && $0.text == "The Mac shuts down, so the Kit stopped its sessions without archiving them" },
              "the halt before a shutdown is a routine row that says nothing was archived")
        check(kev.first { $0.name == "Bird deterrent" }?.text == "The server did not start it, so the Kit started it on the same link",
              "a session the server did not start after wakes is not called unarchived")
        check(kev.first { $0.name == "Facility map" }?.text == "Unarchived, so the Kit started it on the same link",
              "an unarchived session still reads as unarchived")
        check(kev.first { $0.name == "Rivian claims" }?.text == "Archived in the Claude app while it was stopped, so the Kit left it archived",
              "a session archived while stopped is left archived")
        check(kev.first { $0.name == "JetFly" }?.text == "Moved to a new link; the old entry stays in your list",
              "a move leaves the old entry in the list")

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
        // The reply watch (watch.py): a session brought back for new messages, a read, a failed read, and the working
        // rules' reply wait check.
        let wb = Events.kitLine(f.string(from: Date()) + " watch  cse_01AAAtes \"Press color\" brought back for 1 new message: Sam <help@utility.example> \"[Ticket 1] Contact Us\"", names)
        check(wb?.name == "Press color" && wb?.session == "cse_01AAAtest1" && wb?.kind == .restart && wb?.text == "Brought back: new messages came in from someone it contacted"
              && wb?.detail.first?.contains("help@utility.example") == true, "a session the reply watch brought back, with what came")
        let wr = Events.kitLine(f.string(from: Date()) + " watch  person@sample.example read (Haiku through Workrouter): 4 new messages, 0 for a session", names)
        check(wr?.kind == .check && wr?.routine == true && wr?.text == "Reply watch read person@sample.example: 4 new messages, 0 for a session",
              "a read of the reply watch is a routine check")
        let wf = Events.kitLine(f.string(from: Date()) + " watch  person@sample.example read failed: Haiku did not call gmail_search", names)
        check(wf?.kind == .problem && wf?.text == "The reply watch could not read person@sample.example"
              && wf?.detail.first == "Haiku did not call gmail_search", "a failed read is a problem, with why")
        let wn = Events.kitLine(f.string(from: Date()) + " watch  f46255ef contacted utility.example (a web form) with no reply wait: noted for the next prompt", names)
        check(wn?.name == "Press color" && wn?.kind == .check && wn?.text == "Contacted someone and set no wait for the answer",
              "the reply wait check names the session")
        // The progress check-ins (checkin.py): one row a check-in under its session, with the note in the detail; a
        // summary that failed, a test run, a hold and the end of the work.
        let ck = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit | Build the color page, working 45 min | It finished the page and opened pull request 12. Next it checks the links.", names)
        check(ck?.name == "Press color" && ck?.session == "cse_01AAAtest1" && ck?.kind == .wait && ck?.level == .info && ck?.routine == false
              && ck?.text == "Progress check-in: Build the color page, working 45 min"
              && ck?.detail == ["\u{201C}It finished the page and opened pull request 12. Next it checks the links.\u{201D}"],
              "a check-in kept in the Kit: its subject, the note in the detail")
        let cks = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" shown in the Kit; no summary (exit 1: overloaded) | Working 20 min | It made 12 steps since the last note.", names)
        check(cks?.level == .info && cks?.text == "Progress check-in: Working 20 min"
              && cks?.detail.contains { $0.hasPrefix("Haiku gave no summary (exit 1: overloaded)") } == true, "a summary that failed shows in the row")
        let ckd = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" written (dry) | Working 20 min | It made 3 steps.", names)
        let cke = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" work ended after 1 hr 31 min; 6 check-ins", names)
        check(ckd?.routine == true && ckd?.text == "Progress check-in written, not kept (test run): Working 20 min"
              && cke?.routine == true && cke?.text == "Long work ended after 1 hr 31 min; 6 check-ins", "a test run and the end of the work are routine rows")
        // lines from before check-ins stayed in the Kit app (they went the Reach me by ways) still read
        let cs = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" sent by Email, Google Chat | Build the color page, working 45 min | It finished the page and opened pull request 12. Next it checks the links.", names)
        check(cs?.name == "Press color" && cs?.session == "cse_01AAAtest1" && cs?.kind == .wait && cs?.level == .info && cs?.routine == false
              && cs?.text == "Progress check-in sent by Email, Google Chat: Build the color page, working 45 min"
              && cs?.detail == ["\u{201C}It finished the page and opened pull request 12. Next it checks the links.\u{201D}"],
              "a check-in that went: its ways and subject, the note in the detail")
        let cw = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" sent by Email; not by Google Chat (the webhook did not take it: HTTP Error 404); no summary (exit 1: overloaded) | Working 20 min | It made 12 steps in the last 15 min.", names)
        check(cw?.level == .warn && cw?.text == "Progress check-in sent by Email: Working 20 min"
              && cw?.detail.contains("Not sent by Google Chat (the webhook did not take it: HTTP Error 404).") == true
              && cw?.detail.contains { $0.hasPrefix("Haiku gave no summary (exit 1: overloaded)") } == true,
              "a way that failed and a summary that failed show in the row")
        let cn = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" not sent: no way is checked under Reach me by", names)
        check(cn?.level == .warn && cn?.text == "Progress check-in not sent: no way is checked under Reach me by", "no way to send is a warning, with why")
        let cf = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" not sent (Email: gh could not start the mail: HTTP 401) | Working 20 min | It made 3 steps.", names)
        check(cf?.level == .warn && cf?.text == "Progress check-in not sent: Working 20 min"
              && cf?.detail.first == "Email: gh could not start the mail: HTTP 401", "a check-in that went no way says why first")
        let ch = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" skipped: it holds at the usage limit", names)
        let cd = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" would send (dry) | Working 20 min | It made 3 steps.", names)
        let ce = Events.kitLine(f.string(from: Date()) + " checkin cse_01AAAtest1 \"Press color\" work ended after 1 hr 31 min; 6 check-ins sent", names)
        check(ch?.routine == true && ch?.text == "Progress check-in skipped: it holds at the usage limit"
              && cd?.routine == true && cd?.text == "Progress check-in written, not sent (test run): Working 20 min"
              && ce?.routine == true && ce?.text == "Long work ended after 1 hr 31 min; 6 check-ins sent",
              "a hold, a test run and the end of the work are routine rows")
        let cx = Events.kitLine(f.string(from: Date()) + " checkin error: KeyError: 'sessions'", names)
        check(cx?.kind == .problem && cx?.text == "A progress check-in failed", "an error is a problem")

        // Reach me by's alerts off: what was kept in the Kit, the reminder and the Kit's own notice that did not show.
        // Each is a plain row, not a warning: alerts off is a choice. With alerts on and no way checked, a warning.
        let nk = Events.kitLine(f.string(from: Date()) + " notify Press color kept a1b2c3d4e5f6: alerts are off | PR #12 merged", names)
        check(nk?.name == "Press color" && nk?.session == "cse_01AAAtest1" && nk?.kind == .wait && nk?.level == .info
              && nk?.text == "Message kept in the Kit, not sent: PR #12 merged"
              && nk?.detail.first == "Not sent: alerts are off. It is on the session's panel on the Sessions page.",
              "a message kept in the Kit: its session, its subject, and why it was not sent")
        let nw = Events.kitLine(f.string(from: Date()) + " notify Press color kept a1b2c3d4e5f7: no way is checked under Reach me by | PR #12 merged", names)
        check(nw?.level == .warn && nw?.text == "Message kept in the Kit, not sent: PR #12 merged", "kept with no way checked is a warning")
        let rk = Events.kitLine(f.string(from: Date()) + " app    waiting notice skipped: Press color: alerts are off", names)
        check(rk?.name == "Press color" && rk?.session == "cse_01AAAtest1" && rk?.text == "No reminder: alerts are off" && rk?.level == .info,
              "a Needs you reminder that alerts off kept back")
        let ak = Events.kitLine(f.string(from: Date()) + " app    notice not shown, alerts are off: Sttark Claude Kit 1.300 didn't install | Click to try again.", names)
        check(ak?.kind == .app && ak?.level == .info && ak?.text == "Notice not shown, alerts are off: Sttark Claude Kit 1.300 didn't install"
              && ak?.detail == ["Click to try again."], "the Kit's own notice that alerts off kept back")
        let wk = Events.kitLine(f.string(from: Date()) + " wait   07f324 cse_01AAAtes \"Press color\" sent no message after coming back; the Kit kept one in the Kit app (alerts are off)", names)
        check(wk?.text == "It sent no message after coming back; the Kit kept one here", "the Kit's own message after a wait, kept")

        print(failed == 0 ? "all passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
