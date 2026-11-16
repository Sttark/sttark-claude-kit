// Tests how the Kit starts the Remote Control server, checks its health and ends the copies that earlier starts left
// (Sources/Server.swift, Sources/ServerHealth.swift and Resources/hooks/stable-claude.sh), on a copy: a LaunchAgent of
// its own (a test label, loaded from a file in a temporary folder), its own screen name, log and Kit folder
// (STTARK_SERVER_LABEL, STTARK_SERVER_PLIST, STTARK_SERVER_SCREEN, STTARK_SERVER_LOG, STTARK_KIT_DIR, STTARK_KIT_LOG),
// and a stand-in `claude` built from tools/server-health-test/claude.swift (STTARK_SERVER_CLAUDE). The real server
// (com.sttark.claude-rc), its screen and its sessions are never touched, and nothing comes to the front.
// About 2 minutes. Run from the repo root:
//   swiftc -parse-as-library -o /tmp/server-health-test tools/server-health-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/server-health-test
import Foundation

@main struct ServerHealthTest {
    static func main() {
        let fm = FileManager.default
        let n = getpid()
        let dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("kit-healthtest-\(n)")
        let bin = dir.appendingPathComponent("bin"), claude = bin.appendingPathComponent("claude")
        let newer = dir.appendingPathComponent("newer-claude"), folder = dir.appendingPathComponent("folder")
        let kitLog = dir.appendingPathComponent("kit.log")
        try? fm.createDirectory(at: bin, withIntermediateDirectories: true)
        try? fm.createDirectory(at: folder, withIntermediateDirectories: true)
        let label = "com.sttark.kit-test-rc-\(n)", screenName = "kit-test-rc-\(n)"
        for (k, v) in ["STTARK_KIT_DIR": dir.appendingPathComponent("kit").path, "STTARK_KIT_LOG": kitLog.path,
                       "STTARK_SERVER_LABEL": label, "STTARK_SERVER_PLIST": dir.appendingPathComponent("\(label).plist").path,
                       "STTARK_SERVER_SCREEN": screenName, "STTARK_SERVER_CLAUDE": claude.path,
                       "STTARK_SERVER_LOG": dir.appendingPathComponent("rc.log").path] { setenv(k, v, 1) }
        var fails = 0
        func check(_ name: String, _ ok: Bool, _ detail: @autoclosure () -> String = "") {
            print((ok ? "ok   " : "FAIL ") + name + (ok ? "" : "  [\(detail())]")); if !ok { fails += 1 }
        }
        func spin(_ s: Double) { RunLoop.main.run(until: Date().addingTimeInterval(s)) }
        @discardableResult func until(_ timeout: Double, _ cond: () -> Bool) -> Bool {
            let end = Date().addingTimeInterval(timeout)
            while Date() < end { if cond() { return true }; spin(0.25) }
            return cond()
        }
        let src = "tools/server-health-test/claude.swift"
        guard Updater.run("/usr/bin/swiftc", ["-O", "-o", claude.path, src]).0 == 0,
              Updater.run("/usr/bin/swiftc", ["-O", "-D", "NEWER", "-o", newer.path, src]).0 == 0 else {
            print("FAIL could not build \(src): run this from the repo root"); exit(1)
        }
        func mode(_ m: String) { try? m.write(toFile: claude.path + ".mode", atomically: true, encoding: .utf8) }
        func calls() -> [String] { ((try? String(contentsOfFile: claude.path + ".calls", encoding: .utf8)) ?? "").split(separator: "\n").map(String.init) }
        func clearCalls() { try? fm.removeItem(atPath: claude.path + ".calls") }
        func forget() { try? fm.removeItem(atPath: claude.path + ".saved") }   // the spawn mode answer Claude Code keeps
        /// The test's copies of `claude rc` with the Kit's mark, as Server.copies finds them.
        func copies() -> [Server.Proc] { Server.copies(Server.processes()).filter { $0.command.hasPrefix(claude.path + " ") } }
        func lines(_ prefix: String) -> [String] {
            ((try? String(contentsOf: kitLog, encoding: .utf8)) ?? "").split(separator: "\n").map(String.init)
                .filter { $0.dropFirst(20).hasPrefix("server " + prefix) }
        }
        func health() -> ServerHealth.State { spin(0.2); return ServerHealth.state }
        func connect(_ timeout: Double = 8) -> Bool {
            until(timeout) { ServerHealth.checkNow(); return health() == .connected("folder") }
        }
        func cleanUp() {
            Updater.run("/bin/launchctl", ["bootout", "\(Server.domain)/\(label)"])
            for p in Server.processes() where p.command.hasPrefix(claude.path) || p.command.contains(screenName) { kill(p.pid, SIGKILL) }
            for s in Server.screens() { Updater.run("/usr/bin/screen", ["-S", s.id, "-X", "quit"]) }
        }
        ServerHealth.staleAge = 2
        Server.endWait = 2
        Server.checksAfterStart = []
        let home = fm.homeDirectoryForCurrentUser.path

        // 1. What an older Kit did. Its LaunchAgent starts `claude rc` without --spawn, so a newer Claude Code asks the
        // spawn mode question in a git repo, and no one answers. Each start again (launchctl bootout, screen -S <name>
        // -X quit, bootstrap) ended the screen but left its `claude rc` waiting at the question.
        mode("stubborn"); forget()
        let rc = Server.writeScreenrc().path
        let old: [String: Any] = [
            "Label": label,
            "ProgramArguments": ["/bin/zsh", "-lc", "exec /usr/bin/screen -c '\(rc)' -DmS \(screenName) /bin/zsh -c \"cd '\(folder.path)' && exec '\(claude.path)' rc --permission-mode bypassPermissions\""],
            "EnvironmentVariables": ["PATH": "\(home)/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"],
            "RunAtLoad": true, "KeepAlive": true, "ThrottleInterval": 10,
            "StandardOutPath": Server.logFile.path, "StandardErrorPath": Server.logFile.path,
        ]
        (old as NSDictionary).write(to: Server.plist, atomically: true)
        for i in 0..<4 {
            if i > 0 {
                Updater.run("/bin/launchctl", ["bootout", "\(Server.domain)/\(label)"])
                Updater.run("/usr/bin/screen", ["-S", screenName, "-X", "quit"])
            }
            Updater.run("/bin/launchctl", ["bootstrap", Server.domain, Server.plist.path])
            until(5) { copies().count == i + 1 }
        }
        check("an older Kit's starts left a copy of claude rc at the question each time: 4 run", copies().count == 4, "\(copies().count)")
        // a person's own `claude rc` in a terminal: the same program, without the Kit's mark. Nothing may end it.
        let own = Process()
        own.executableURL = claude
        own.arguments = ["rc", "--permission-mode", "bypassPermissions"]
        own.environment = ["HOME": home, "PATH": "/usr/bin:/bin", "TERM": "xterm-256color"]
        own.currentDirectoryURL = folder
        own.standardInput = Pipe(); own.standardOutput = FileHandle.nullDevice
        try? own.run()
        spin(2.5)   // every copy is older than ServerHealth.staleAge now

        // The new Kit's first check
        let job = Server.job().pid
        ServerHealth.checkNow()
        check("the first check ends the 3 copies that earlier starts left, and keeps the one launchd runs",
              copies().count == 1 && Server.job().pid == job, "\(copies().count) copies")
        check("it logs how many it ended", lines("ended 3 old copies of the server that earlier starts left running").count == 1)
        check("a person's own claude rc is never ended", own.isRunning)
        check("it answers the spawn mode question with same-dir", lines("answered same-dir: the spawn mode").count == 1
              && fm.fileExists(atPath: claude.path + ".saved"))
        let args = (NSDictionary(contentsOf: Server.plist)?["ProgramArguments"] as? [String])?.last ?? ""
        let envs = NSDictionary(contentsOf: Server.plist)?["EnvironmentVariables"] as? [String: String] ?? [:]
        check("it writes the older Kit's LaunchAgent again, with --spawn same-dir and the Kit's marker",
              args.contains("--spawn same-dir") && envs[Server.marker] == label && lines("start command updated").count == 1)
        check("then the server connects, with no start again", connect() && Server.job().pid == job, "\(ServerHealth.state)")

        // 2. The new LaunchAgent gives --spawn same-dir when Claude Code's help names it: no question at all
        mode(""); forget(); clearCalls()
        let answered = lines("answered same-dir").count
        check("Server.start", Server.start(folder: folder.path, quiet: true) == nil)
        check("a Claude Code with --spawn connects with no question", connect() && lines("answered same-dir").count == answered, "\(ServerHealth.state)")
        check("the help is read first, then claude rc gets --spawn same-dir",
              calls() == ["remote-control --help", "rc --permission-mode bypassPermissions --spawn same-dir"], "\(calls())")
        let server = copies().first
        check("the copy that waited at the question is gone, and one server runs", copies().count == 1, "\(copies().count)")
        check("the server carries the Kit's marker", server.map { Updater.run("/bin/ps", ["-wwE", "-o", "command=", "-p", String($0.pid)]).1
            .contains(" \(Server.marker)=\(label)") } == true)

        // 3. An older Claude Code: its help doesn't name --spawn, which would stop it, so it gets none
        mode("old"); clearCalls()
        Server.start(folder: folder.path, quiet: true)
        check("an older Claude Code gets no --spawn, and connects", connect() && calls() == ["remote-control --help", "rc --permission-mode bypassPermissions"], "\(calls())")

        // 4. A question the Kit can't answer: a problem in Settings and on the Events page, and a start again each time
        // the server isn't connected after stuckAfter, each one later than the last (the back-off doubles)
        mode("other stubborn")
        ServerHealth.stuckAfter = 2; ServerHealth.backoffBase = 4
        let first = lines("started again: ").count
        Server.start(folder: folder.path, quiet: true)
        var at: [Date] = [], most = 0, problem = false
        let t0 = Date()
        while lines("started again: ").count - first < 4 && Date().timeIntervalSince(t0) < 70 {
            let before = lines("started again: ").count
            ServerHealth.checkNow()
            if lines("started again: ").count > before { at.append(Date()) }
            if case .failing(let why) = health(), why == "it waits on a question the Kit can't answer: Region [1/2]:" { problem = true }
            most = max(most, copies().count)
            spin(0.5)
        }
        check("Settings shows the question as a problem", problem)
        check("the Events page gets it as a problem", Events.read(kitLog: kitLog, bypassLog: dir.appendingPathComponent("none.log"), names: .init())
            .contains { $0.kind == .problem && $0.text == "Remote Control server not connected: it waits on a question the Kit can't answer: Region [1/2]:" })
        check("a server stuck at the question starts again: 4 times", at.count == 4,
              "\(at.count): " + lines("started again: ").suffix(4).joined(separator: " / "))
        let gaps = zip(at.dropFirst(), at).map { $0.timeIntervalSince($1) }
        check("each start again waits longer: at least 4, 8 and 16 seconds", gaps.count == 3 && gaps[0] >= 3.6 && gaps[1] >= 7.6 && gaps[2] >= 15.6,
              gaps.map { String(format: "%.1f", $0) }.joined(separator: ", "))
        check("each one ended the copy before it (it ignored SIGTERM): never more than one at a time", most == 1, "\(most)")
        check("the log says what it showed", lines("started again: not connected after 2 seconds; it showed: Region [1/2]:").count >= 4)

        // connected again, which ends the back-off
        mode(""); Server.start(folder: folder.path, quiet: true)
        check("connected again", connect())

        // 5. A server that stops soon after each start: launchd would start it every few seconds without end. The Kit
        // unloads it, says why, and starts it again later, waiting longer each time.
        mode("exit"); Server.throttle = 2; ServerHealth.backoffBase = 3
        Server.start(folder: folder.path, quiet: true)
        until(40) { ServerHealth.checkNow(); return !lines("not connected: it stopped ").isEmpty }
        let loop = lines("not connected: it stopped ").first ?? ""
        check("launchd started it again and again: the Kit unloads it and says why",
              !Server.job().loaded && loop.contains("it stopped 3 times soon after it started; it showed: Error: Remote Control could not start (a test). The Kit starts it again in 3 s."), loop)
        spin(2)
        check("nothing starts it until the back-off ends", !Server.job().loaded && copies().isEmpty)
        until(20) { ServerHealth.checkNow(); return !lines("started again: it had stopped again and again soon after it started").isEmpty }
        check("after the back-off, the Kit starts it again", lines("started again: it had stopped again and again soon after it started").count == 1)
        until(40) { ServerHealth.checkNow(); return lines("not connected: it stopped ").count >= 2 }
        check("it stops again: the next back-off is longer", lines("not connected: it stopped ").last?.hasSuffix("The Kit starts it again in 6 s.") == true,
              lines("not connected: it stopped ").last ?? "")
        Server.throttle = 10

        // 6. The night job (stable-claude.sh) swaps in a newer Claude Code and restarts the server: it ends every copy
        // the Kit started and waits until they are gone, so the new server can register the folder
        mode("stubborn")
        Server.start(folder: folder.path, quiet: true)
        check("a server that ignores SIGTERM connects", connect())
        let was = copies().map(\.pid)
        let state = dir.appendingPathComponent("state.json")
        try? "{}".write(to: state, atomically: true, encoding: .utf8)
        let night = Process()
        night.executableURL = URL(fileURLWithPath: "/bin/zsh")
        night.arguments = ["Resources/hooks/stable-claude.sh", "--now"]
        night.environment = ProcessInfo.processInfo.environment.merging(
            ["STABLE": claude.path, "NEWEST": newer.path, "LABEL": label, "PLIST": Server.plist.path, "STATE": state.path,
             "LOG": kitLog.path, "SCREEN_NAME": screenName]) { $1 }
        try? night.run(); night.waitUntilExit()
        let stable = ((try? String(contentsOf: kitLog, encoding: .utf8)) ?? "").split(separator: "\n").filter { $0.contains(" stable ") }
        check("the night job swaps in the newer Claude Code and restarts the server",
              stable.contains { $0.hasSuffix("copy is now newer-claude") } && stable.contains { $0.hasSuffix("server restarted on newer-claude") },
              stable.joined(separator: " / "))
        check("the new server runs the newer Claude Code", Updater.run(claude.path, ["--version"]).1.hasPrefix("2.1.1000"))
        check("its restart ended the old copy (it ignored SIGTERM) and started one new server",
              until(10) { copies().count == 1 && !was.contains(copies()[0].pid) }, "\(copies().map(\.pid)) was \(was)")
        check("and it connects", connect())
        check("a person's own claude rc is never ended", own.isRunning)

        // 7. Turning the switch off ends every copy and removes the LaunchAgent, and nothing else
        Server.stop()
        check("turned off: no copy runs, launchd has no job, and its file is gone",
              copies().isEmpty && !Server.job().loaded && !fm.fileExists(atPath: Server.plist.path))
        check("a person's own claude rc is never ended", own.isRunning)

        kill(own.processIdentifier, SIGKILL)
        cleanUp()
        try? fm.removeItem(at: dir)
        print(fails == 0 ? "\nall passed" : "\n\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
