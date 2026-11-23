// Tests the agents under their sessions (Sources/Agents.swift): how the state's `agents` list of a session is read
// (running first, the oldest first, then finished, the newest first), the levels, a fork's words, an agent whose end
// was lost (no SubagentStop) once its session stopped work for 30 min, which agents the Sessions page lists under a
// row ("8 finished agents"), and that Inbox.snapshot puts each session's agents on its row. Runs on a temporary
// folder with made-up sessions, never the real state. Run from the repo root:
//   swiftc -parse-as-library -o /tmp/agents-test tools/agents-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/agents-test
import Foundation

@main struct AgentsTest {
    static var failed = 0
    static func check(_ ok: Bool, _ what: String) { print((ok ? "ok    " : "FAIL  ") + what); if !ok { failed += 1 } }

    static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-agentstest-\(getpid())")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        defer { try? FileManager.default.removeItem(at: dir) }

        let now = Date().timeIntervalSince1970
        func agent(_ id: String, _ type: String, _ desc: String, _ level: String, by: String = "kit", _ reason: String = "",
                   started: Double, done: Double? = nil) -> [String: Any] {
            ["tool_use_id": "toolu_" + id, "agent_id": NSNull(), "type": type, "desc": desc, "level": level, "set_by": by,
             "reason": reason, "started_at": now - started * 60, "done_at": done.map { now - $0 * 60 } as Any? ?? NSNull()]
        }

        // reading one session's list
        check(Agents.read([:], busy: true, lastActive: Date()).isEmpty, "no agents key: no agents")
        check(Agents.read(nil, busy: true, lastActive: Date()).isEmpty, "no session: no agents")
        let mixed: [String: Any] = ["agents": [
            agent("a", "Explore", "Find the die files", "low", "A short file search.", started: 40, done: 38),
            agent("b", "general-purpose", "Order the plates", "High", "Several steps with care.", started: 20),
            agent("c", "general-purpose", "Count the cores", "medium", started: 30, done: 10),
            agent("d", "fork", "Build the die list", "Extra", started: 25),
            agent("e", "Plan", "Plan the move", "warp", started: 5),
        ]]
        let a = Agents.read(mixed, busy: true, lastActive: Date())
        check(a.map(\.id) == ["toolu_d", "toolu_b", "toolu_e", "toolu_c", "toolu_a"],
              "running first, the oldest first; then finished, the newest first: \(a.map(\.id))")
        check(a.map(\.level) == ["xhigh", "high", "", "medium", "low"], "levels read as the window keys them, an unknown one as none: \(a.map(\.level))")
        check(a[0].isFork && a[0].typeName == "Fork" && a[1].typeName == "general-purpose", "a fork shows as Fork, any other agent by its type")
        check(a[1].running && !a[3].running && a[3].timeWords == "done 10 min ago" && a[1].timeWords == "running 20 min",
              "running and finished, with how long: \(a[1].timeWords), \(a[3].timeWords)")
        check(a[1].shortTime == "20 min" && a[3].shortTime == "10 min ago", "short times for a narrow list: \(a[1].shortTime), \(a[3].shortTime)")
        check(Agents.counts(a) == "3 running · 2 finished", "the counts: \(Agents.counts(a))")

        // the words for each level: the Kit's reason, the session's own, and a fork's
        check(a[1].why == "Why High: Several steps with care.", "the Kit's reason: \(a[1].why)")
        check(a[0].why == "Runs at the session's level, Extra, the level the Kit picked for it.", "a fork at the level the Kit picked: \(a[0].why)")
        let fork = Agents.read(["agents": [agent("f", "fork", "Build the job card", "max", by: "session",
                                                 "A fork runs at the session's level. It needs high: code across a few files", started: 4),
                                           agent("f2", "fork", "Build the label list", "high", by: "session", started: 3)]],
                               busy: true, lastActive: Date())
        check(fork[0].why == "Runs at the session's level, Max. It needs High: code across a few files.",
              "a fork at the session's level as it was, with the Kit's note, said once: \(fork[0].why)")
        check(fork[1].why == "Runs at the session's level, High.", "a fork with no note: \(fork[1].why)")
        // a fork has no level of its own: while it runs, it shows the session's level now
        let moved = Agents.read(["level": "max", "agents": [agent("m", "fork", "Build the plate list", "high", "Code across a few files.", started: 9),
                                                            agent("m2", "fork", "Build the core list", "high", started: 30, done: 20)]],
                                busy: true, lastActive: Date())
        check(moved[0].level == "max" && moved[0].why == "Runs at the session's level, Max. It started at High, the level the Kit picked for it. Code across a few files.",
              "a running fork after the session went up: the session's level now, and where it started: \(moved[0].why)")
        check(moved[1].level == "high", "a finished fork keeps the level it started at")
        check(fork[0].tip.contains("A fork runs at the session's level"), "a fork's tip says it runs at the session's level")
        let own = Agents.read(["agents": [agent("g", "Explore", "Find the files", "low", by: "session", "set in the call", started: 4),
                                          agent("g2", "Explore", "Find the notes", "medium", by: "session", "The session is on Manual.", started: 3)]],
                              busy: true, lastActive: Date())
        check(own[0].why == "The session set this level in its call.", "a level the session set in its call: \(own[0].why)")
        check(own[1].why == "The Kit did not pick this level. The session is on Manual.", "a level the Kit did not pick, with why: \(own[1].why)")

        // an agent whose end the Kit never saw: it runs while the session works, and shows as ended 30 min after its work stopped
        let open: [String: Any] = ["agents": [agent("h", "Explore", "Find the press notes", "low", started: 120)]]
        check(Agents.read(open, busy: true, lastActive: Date(timeIntervalSince1970: now - 7200))[0].running,
              "no end, its session works: it runs")
        check(Agents.read(open, busy: false, lastActive: Date(timeIntervalSince1970: now - 29 * 60))[0].running,
              "no end, its session stopped 29 min ago: it still runs")
        let lost = Agents.read(open, busy: false, lastActive: Date(timeIntervalSince1970: now - 31 * 60))[0]
        check(!lost.running && lost.lost && lost.timeWords == "ended", "no end, its session stopped 31 min ago: it ended, with no time")

        // what the Sessions page lists under a row
        func finished(_ n: Int) -> [Agents.Item] {
            Agents.read(["agents": (0..<n).map { agent("x\($0)", "Explore", "Part \($0)", "low", started: 60, done: Double(50 - $0)) }
                         + [agent("run", "general-purpose", "Write the list", "high", started: 3)]], busy: true, lastActive: Date())
        }
        let two = Agents.listed(finished(2), open: false)
        check(two.rows.count == 3 && two.finished == nil, "1 running and 2 finished: all three rows, no finished row")
        let eight = Agents.listed(finished(8), open: false)
        check(eight.rows.map(\.id) == ["toolu_run"] && eight.finished == 8, "1 running and 8 finished: the running one, and one row for 8 finished")
        let opened = Agents.listed(finished(8), open: true)
        check(opened.rows.count == 9 && opened.finished == 8 && opened.rows.first?.id == "toolu_run", "opened: every agent, running first, and the row to close them")

        // Inbox.snapshot puts each session's agents on its row
        let state: [String: Any] = ["sessions": [
            "cse_W1": ["title": "Die list", "level": "max", "at": now - 60, "turn_at": now - 300,
                       "app": ["working": true, "checked": now, "archived": false],
                       "agents": [agent("w1", "fork", "Build A", "max", started: 4), agent("w2", "fork", "Build B", "max", started: 3),
                                  agent("w3", "fork", "Build C", "max", started: 2)]],
            "cse_B2": ["title": "Plate order", "level": "medium", "at": now - 7200,
                       "app": ["working": false, "checked": now, "archived": false,
                               "background": ["agents": 1, "bash": 0, "what": "Order the plates", "since": now - 7200]],
                       "agents": [agent("b1", "general-purpose", "Order the plates", "high", started: 120)]],
            "cse_I3": ["title": "Core count", "level": "low", "at": now - 7200, "app": ["working": false, "checked": now, "archived": false],
                       "agents": [agent("i1", "Explore", "Find the counts", "low", started: 125)]],
            "cse_N4": ["title": "Ink check", "level": "low", "at": now - 600, "app": ["working": false, "checked": now, "archived": false]],
        ]]
        try! JSONSerialization.data(withJSONObject: state).write(to: State.file)
        let snap = Inbox.snapshot()
        func row(_ id: String) -> Inbox.Row? { snap.rows.first { $0.id == id } }
        check(row("cse_W1")?.group == .working && row("cse_W1")?.agents.filter(\.running).count == 3, "a working session: its 3 forks run")
        check(row("cse_B2")?.group == .working && row("cse_B2")?.agents.first?.running == true,
              "an agent that runs after the turn, 2 hours on: it runs")
        check(row("cse_I3")?.group == .idle && row("cse_I3")?.agents.first?.lost == true, "an idle session 2 hours on: its agent with no end ended")
        check(row("cse_N4")?.agents.isEmpty == true, "a session with no agents key: no agent rows")

        print(failed == 0 ? "all passed" : "\(failed) failed")
        exit(failed == 0 ? 0 : 1)
    }
}
