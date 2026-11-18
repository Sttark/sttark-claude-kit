// Tests the window's one search (Sources/Search.swift, KitModel in Sources/Window.swift) on a temporary STTARK_KIT_DIR
// and log, never the real ones: made-up sessions in every group of the Sessions page (their saved conversations in the
// test folder, each with the folder it ran in and a prompt with a marker), waits, a progress check-in, messages kept
// in the Kit, sessions on this Mac only and archived sessions. It checks each field the search finds a session by,
// that a prompt is never searched, that every word must match with case and accents ignored, the groups in the Sessions
// page's order with Archived last and one place for each session, the model (a search typed on another page, the
// session picked, the ×, Escape and the sidebar, which bring the page back), the folder's own name on the phone, and
// the time a key takes with thousands of archived sessions. No window is shown, and no key goes to any app: Escape is
// an event made here and handed to the window's own check. Run from the repo root:
//   swiftc -parse-as-library -o /tmp/search-test tools/search-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/search-test
import AppKit
import Foundation

@main struct SearchTest {
    static var failed = 0
    static func check(_ ok: Bool, _ what: String) { print((ok ? "ok    " : "FAIL  ") + what); if !ok { failed += 1 } }

    static func json(_ v: Any, _ name: String) {
        try! JSONSerialization.data(withJSONObject: v).write(to: supportDir.appendingPathComponent(name))
    }

    /// A saved conversation in the test folder: a prompt with a marker, then lines that ran in `cwd`.
    static func conversation(_ dir: URL, _ name: String, cwd: String) -> String {
        let p = dir.appendingPathComponent("projects/\(name).jsonl")
        try? FileManager.default.createDirectory(at: p.deletingLastPathComponent(), withIntermediateDirectories: true)
        let lines = [
            #"{"type":"user","message":{"role":"user","content":"PROMPTMARK fix the hopper sensor"},"cwd":"/tmp/elsewhere"}"#,
            #"{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"REPLYMARK done"}]},"cwd":"\#(cwd)"}"#,
        ]
        try! (lines.joined(separator: "\n") + "\n").write(to: p, atomically: true, encoding: .utf8)
        return p.path
    }

    @MainActor static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-searchtest-\(getpid())")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        defer { try? FileManager.default.removeItem(at: dir) }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let now = Date().timeIntervalSince1970
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        // made-up sessions: one that needs you, one at work with a check-in, two idle (one with a message kept in the
        // Kit), one that waits (archived, with two waits), and their saved conversations with the folder each ran in
        func session(_ title: String, ago: Double, cwd: String, app: [String: Any] = [:], turn: Double? = nil) -> [String: Any] {
            var a: [String: Any] = ["url": "https://claude.ai/code/session_x", "working": false, "archived": false]
            a.merge(app) { $1 }
            var x: [String: Any] = ["title": title, "level": "medium", "reason": "Routine edit with a clear plan", "manual": false,
                                    "at": now - ago * 60, "app": a,
                                    "transcript": conversation(dir, title.replacingOccurrences(of: " ", with: "-"), cwd: cwd)]
            if let turn { x["turn_at"] = now - turn * 60 }
            return x
        }
        let sessions: [String: Any] = [
            "cse_01Needs": session("Order page login", ago: 20, cwd: home + "/src/order-site",
                                   app: ["needs": true, "why": "a plan for the checkout waits for your go-ahead",
                                         "last_event_at": iso.string(from: Date(timeIntervalSince1970: now - 1200))]),
            "cse_01Work": session("Slitter blade change", ago: 1, cwd: home + "/src/maintenance", app: ["working": true], turn: 31),
            "cse_01Idle": session("Rename report columns", ago: 90, cwd: home + "/src/reports"),
            "cse_01Kept": session("Dock door repair", ago: 40, cwd: home + "/src/building"),
            "cse_01Home": session("Home notes", ago: 30, cwd: home),
        ]
        let waits: [String: Any] = [
            "w1": ["id": "w1", "kind": "email-reply", "what": "Supplier's reply to the deposit email", "why": "They said 2 workdays",
                   "from": "dana@corrugator.example", "by": now + 86400, "set_at": now - 3600, "cse": "cse_01Wait",
                   "title": "Core supplier quote", "cwd": home + "/src/purchasing", "session_url": "https://claude.ai/code/session_w"],
            "w2": ["id": "w2", "kind": "pr", "target": "Sttark/example#7", "want": "merged", "what": "Merge of the glue fix",
                   "why": "Friday is short", "by": now + 2 * 86400, "set_at": now - 3600, "cse": "cse_01Wait",
                   "title": "Core supplier quote", "session_url": "https://claude.ai/code/session_w"],
        ]
        json(["sessions": sessions, "waits": waits, "paused": false], "state.json")
        json(["sessions": ["cse_01Work": ["start": now - 31 * 60, "note_at": now - 60, "note": "It read the photos and marked three blades for the regrind shop."]]], "checkins.json")
        json(["items": [["id": "m1", "at": now - 600, "cse": "cse_01Kept", "title": "Dock door repair", "subject": "Door company asks for a visit",
                         "body": "They want to measure dock door 3 with a laser on Thursday.", "from": "session", "why": "alerts are off"]]], "kept.json")
        json(["at": now, "sessions": [["id": "local-1", "title": "Box label sizes", "cwd": home + "/src/shipping", "where": "terminal",
                                       "last": now - 1800]]], "local-sessions.json")
        func item(_ n: Int, _ title: String, _ folder: String, ago: Double, _ doing: String, cse: String? = nil) -> [String: Any] {
            ["cse": cse ?? "cse_01Arch\(n)", "title": title, "folder": folder, "transcript": "/sample/arch-\(n).jsonl",
             "archived_at": now - ago * 3600, "url": "https://claude.ai/code/session_01Arch\(n)", "doing": doing]
        }
        json(["at": now, "rev": "test", "items": [
            item(1, "Waste report totals", home + "/src/reports", ago: 30, "Fixed the totals row of the weekly report."),
            item(2, "Café menu labels", home + "/src/labels", ago: 50, "Printed the test labels on the Epson."),
            item(3, "Core supplier quote", home + "/src/purchasing", ago: 5, "It has a wait, so it is under Waiting on someone else.", cse: "cse_01Wait"),
            item(4, "Dryer belt change", home + "/src/maintenance", ago: 70, ""),
        ]], "archived.json")

        let model = KitModel()
        model.reload()
        func find(_ q: String) -> Search.Found { model.search = q; return model.found }
        func names(_ f: Search.Found) -> [String] { f.rows.map(\.title) + f.archived.map { "archived " + $0.title } }

        // the words
        check(Search.words("  Café   REPORT ") == ["cafe", "report"], "words: folded, case and accents ignored, extra spaces dropped")
        check(Search.words("   ").isEmpty && Search.words("").isEmpty, "words: none for spaces only")
        model.search = "   "
        check(!model.searching, "only spaces is no search")

        // each field a session is found by
        check(names(find("login")) == ["Order page login"], "the name")
        check(names(find("checkout")) == ["Order page login"], "the words on its row: why it needs you")
        check(names(find("order-site")) == ["Order page login"], "its folder, from its saved conversation")
        check(names(find("regrind")) == ["Slitter blade change"], "its last check-in")
        check(names(find("laser")) == ["Dock door repair"], "a message kept in the Kit: its words")
        check(names(find("door company")) == ["Dock door repair"], "a message kept in the Kit: its subject")
        check(names(find("deposit")) == ["Core supplier quote"], "what a wait is for")
        check(names(find("glue")) == ["Core supplier quote"], "what its second wait is for")
        check(names(find("workdays")) == ["Core supplier quote"], "why the wait's deadline")
        check(names(find("corrugator")) == ["Core supplier quote"], "who the wait is from")
        check(names(find("shipping")) == ["Box label sizes"], "the folder of a session on this Mac only")
        check(names(find("routine edit")).contains("Rename report columns"), "the effort's reason")
        check(names(find("totals")) == ["archived Waste report totals"], "an archived session: what it was doing")
        check(names(find("dryer")) == ["archived Dryer belt change"], "an archived session: its name")
        check(names(find("src/labels")) == ["archived Café menu labels"], "an archived session: its folder")
        check(names(find("cafe")) == ["archived Café menu labels"] && names(find("CAFÉ")) == ["archived Café menu labels"],
              "accents and case ignored")

        // what is never searched
        check(find("promptmark").isEmpty && find("replymark").isEmpty && find("hopper").isEmpty, "never a prompt or a reply")
        check(find("elsewhere").isEmpty, "an older folder of a conversation: only the last one counts")
        let index = Search.Index(model.snap, model.archived.items)
        check(!(index.rows.map(\.text) + index.archived.map(\.text)).contains { $0.contains(Search.fold(home)) },
              "the home folder's path is never searched: folders show from ~")
        check(Folders.of(transcript: (sessions["cse_01Home"] as! [String: Any])["transcript"] as! String) == home
              && model.snap.rows.first { $0.title == "Home notes" }?.folderShort == "~", "a session's folder can be home itself: ~")

        // every word must match, in any order
        check(names(find("report weekly")) == ["archived Waste report totals"], "every word must match")
        check(names(find("weekly report")) == ["archived Waste report totals"], "in any order")
        check(find("report zzz").isEmpty, "one word that matches nothing: no session")

        // the groups: the Sessions page's order, Archived last, each session once
        let all = find("src")
        check(all.groups.map(\.group) == [.needs, .working, .waits, .local, .idle], "the groups in the Sessions page's order")
        check(all.groups.first { $0.group == .waits }?.rows.count == 1, "a session with two waits is one row")
        check(!all.archived.contains { $0.title == "Core supplier quote" }, "a session that waits is under Waiting on someone else, not under Archived")
        check(all.archived.map(\.title) == ["Waste report totals", "Café menu labels", "Dryer belt change"], "Archived last, newest first")
        check(all.count == 9, "the count: every row and every archived session (\(all.count))")

        // the model: a search typed on another page, and how the page comes back
        model.search = ""
        model.go(.settings)
        model.search = "report"
        check(model.searching && model.page == .settings, "typed on Settings: the search shows over the page, which stays")
        check(model.picked?.key == "cse_01Idle", "the first session found is picked")
        model.searchPick = "archived:cse_01Arch1"
        check(model.picked?.key == "archived:cse_01Arch1", "an archived session can be picked, for its own panel")
        model.search = "report totals"
        check(model.picked?.key == "archived:cse_01Arch1", "the pick stays while the search still finds it")
        model.search = "rename"
        check(model.picked?.key == "cse_01Idle", "else the first session found")
        model.clearSearch()
        check(!model.searching && model.search.isEmpty && model.page == .settings, "the × clears it, and Settings shows again")
        let esc = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil,
                                   characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}", isARepeat: false, keyCode: 53)!
        let cmdEsc = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.command], timestamp: 0, windowNumber: 0, context: nil,
                                      characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}", isARepeat: false, keyCode: 53)!
        check(!KitNSWindow.clearsSearch(esc, model), "Escape with no search: the window's own Escape")
        model.go(.usage)
        model.search = "dryer"
        check(!KitNSWindow.clearsSearch(cmdEsc, model) && model.searching, "Command-Escape is not Escape")
        check(KitNSWindow.clearsSearch(esc, model) && !model.searching && model.page == .usage, "Escape clears it, and Usage shows again")
        model.search = "dryer"
        model.go(.events)
        check(!model.searching && model.page == .events, "a page picked in the sidebar clears the search")
        model.go(.archived)
        model.search = "dryer"
        model.clearSearch()
        check(model.archivedSelected == "cse_01Arch4", "back on Archived, the archived session picked in the search is selected")
        model.go(.sessions)
        model.search = "deposit"
        model.clearSearch()
        check(model.selected == "cse_01Wait", "back on Sessions, the session picked in the search is selected")
        model.search = "dryer"
        model.showOnSessions("cse_01Needs")
        check(!model.searching && model.page == .sessions && model.selected == "cse_01Needs", "Show it, after Bring it back: the Sessions page, with the search cleared")

        // the phone gets a session's folder as its own name only, and none for the home folder
        let snap = Inbox.snapshot()
        func phoneRow(_ title: String) -> [String: Any]? {
            snap.rows.first { $0.title == title }.flatMap { Phone.row($0, group: "x", state: State.read()) }
        }
        check(phoneRow("Order page login")?["folder"] as? String == "order-site", "phone: the folder's own name")
        check(phoneRow("Home notes").map { $0["folder"] == nil } == true, "phone: no folder for the home folder")
        check(phoneRow("Core supplier quote")?["folder"] as? String == "purchasing", "phone: a wait's folder")
        let payload = String(decoding: try! JSONSerialization.data(withJSONObject: snap.rows.compactMap { Phone.row($0, group: "x", state: State.read()) }), as: UTF8.self)
        check(!payload.contains(home) && !payload.contains("/src/"), "phone: never a path")

        // a key typed, with thousands of archived sessions: the texts are made once for each read of the state
        var many: [[String: Any]] = []
        for i in 0..<3000 {
            many.append(item(1000 + i, "Archived job \(i) for press \(i % 9)", home + "/src/job-\(i % 40)", ago: Double(i),
                             "It set up the plates for press \(i % 9), ran the proof and filed the notes for order \(i)."))
        }
        json(["at": now, "rev": "many", "items": many], "archived.json")
        model.reload()
        model.search = ""
        var t = Date()
        model.search = "p"
        _ = model.found
        let first = -t.timeIntervalSinceNow
        t = Date()
        var keys = 0
        for q in ["pr", "pre", "pres", "press", "press 7", "press 7 job", "press 7 job 2", "press 7 job 21", "press 7 job 219", "press 7 job 2194"] {
            model.search = q
            _ = model.found
            _ = model.picked
            keys += 1
        }
        let each = -t.timeIntervalSinceNow / Double(keys)
        check(model.found.archived.map(\.title) == ["Archived job 2194 for press 7"], "3000 archived sessions: the one typed is found")
        check(first < 0.5, String(format: "3000 archived sessions: the first key, with the texts made, %.0f ms", first * 1000))
        check(each < 0.02, String(format: "3000 archived sessions: each key after it %.1f ms", each * 1000))

        print(failed == 0 ? "all passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
