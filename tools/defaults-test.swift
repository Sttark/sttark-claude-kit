// Tests the Kit's defaults (Sources/Defaults.swift) and install-hooks.py --defaults on copies: a temp home folder and
// this test's own settings domain, never the real ones. Which switches come on, that one turned off by hand stays
// off, that turning it on again clears that, that the sync waits for the Claude app's sign-in, and that Claude Code's
// phone notice keys are set only when missing.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/defaults-test tools/defaults-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/defaults-test
import Foundation

@main struct DefaultsTest {
    static func main() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-defaultstest-\(getpid())")
        try? FileManager.default.createDirectory(at: dir.appendingPathComponent(".claude"), withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_DESKTOP_CONFIG", dir.appendingPathComponent("desktop.json").path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)
        var fails = 0
        func check(_ name: String, _ ok: Bool) { print((ok ? "ok   " : "FAIL ") + name); if !ok { fails += 1 } }
        let allOff = ["names": false, "profile": false, "fileLinks": false, "bypass": false, "chrome": false]
        check("new Mac: every switch comes on", KitDefaults.due(on: allOff, claudeAppSignedIn: true) == ["names", "profile", "fileLinks", "bypass", "chrome"])
        check("no Claude app sign-in: the sync waits", KitDefaults.due(on: allOff, claudeAppSignedIn: false) == ["names", "fileLinks", "bypass", "chrome"])
        check("already on: nothing to do", KitDefaults.due(on: ["names": true, "profile": true, "fileLinks": true, "bypass": true, "chrome": true], claudeAppSignedIn: true).isEmpty)
        KitDefaults.chose("names", on: false)
        check("turned off by hand: stays off", !KitDefaults.due(on: allOff, claudeAppSignedIn: true).contains("names"))
        KitDefaults.chose("names", on: true)
        check("turned on again: the record is gone", !KitDefaults.turnedOff("names"))
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)
        // Progress check-ins: on unless turned off by hand; checkin.py reads the switch in the state file
        check("check-ins: on with no record", Checkins.on)
        Checkins.tellHooks()
        check("check-ins: the state file says on", State.read()["checkins"] as? Bool == true)
        Checkins.set(false)
        check("check-ins off by hand: the record and the state file say so",
              !Checkins.on && KitDefaults.turnedOff("checkins") && State.read()["checkins"] as? Bool == false)
        Checkins.set(true)
        check("check-ins on again: the record is gone", Checkins.on && State.read()["checkins"] as? Bool == true)
        // Check-ins in the session: on unless turned off by hand, beside the check-ins' own switch in the state file
        check("check-ins in the session: on with no record, and the state file says so",
              Checkins.chatOn && State.read()["checkins_chat"] as? Bool == true)
        Checkins.setChat(false)
        check("check-ins in the session off by hand: the record and the state file say so, and the check-ins stay on",
              !Checkins.chatOn && KitDefaults.turnedOff("checkinsChat") && State.read()["checkins_chat"] as? Bool == false
              && Checkins.on && State.read()["checkins"] as? Bool == true)
        Checkins.set(false)
        check("check-ins off: each switch keeps its own record",
              State.read()["checkins"] as? Bool == false && State.read()["checkins_chat"] as? Bool == false)
        Checkins.set(true)
        Checkins.setChat(true)
        check("check-ins in the session on again: the record is gone",
              Checkins.chatOn && !KitDefaults.turnedOff("checkinsChat") && State.read()["checkins_chat"] as? Bool == true)
        // the notes the Kit app shows: only the latest of a run that goes on; none while the switch is off
        let t = Date().timeIntervalSince1970
        let runs: [String: Any] = ["sessions": [
            "cse_now": ["start": t - 1800, "note_at": t - 720, "note": " It finished the page. Next it checks the links. "],
            "cse_old": ["start": t - 300, "note_at": t - 2000, "note": "A note of a run that ended."],
            "cse_ended": ["sent": t - 600],
            "cse_empty": ["start": t - 1800, "note_at": t - 60, "note": ""],
        ]]
        try? JSONSerialization.data(withJSONObject: runs).write(to: Checkins.file)
        let notes = Checkins.latest(["checkins": true])
        check("check-ins: the latest note of the run that goes on, and its age",
              notes.keys.sorted() == ["cse_now"] && notes["cse_now"]?.text == "It finished the page. Next it checks the links."
              && notes["cse_now"]?.age == "Check-in 12 min ago" && Checkins.latest([:]).count == 1)
        check("check-ins: none while the switch is off", Checkins.latest(["checkins": false]).isEmpty)
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)

        let settings = dir.appendingPathComponent(".claude/settings.json")
        try! #"{"agentPushNotifEnabled": false}"#.write(to: settings, atomically: true, encoding: .utf8)
        func defaults() -> String {
            let p = Process(); let out = Pipe()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = ["Resources/hooks/install-hooks.py", "--defaults"]
            var env = ProcessInfo.processInfo.environment; env["HOME"] = dir.path; p.environment = env
            p.standardOutput = out; try! p.run(); p.waitUntilExit()
            return String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)!.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        check("missing phone notice key is set", defaults() == "set inputNeededNotifEnabled")
        let d = try! JSONSerialization.jsonObject(with: Data(contentsOf: settings)) as! [String: Any]
        check("a false the person set stays false", d["agentPushNotifEnabled"] as? Bool == false && d["inputNeededNotifEnabled"] as? Bool == true)
        check("second run: unchanged", defaults() == "unchanged")
        // the bypass keys: set only when missing, taken out only when the Kit set them
        func run(_ args: [String]) -> String {
            let p = Process(); let out = Pipe()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3"); p.arguments = args
            var env = ProcessInfo.processInfo.environment
            env["HOME"] = dir.path; env["STTARK_DESKTOP_CONFIG"] = dir.appendingPathComponent("desktop.json").path
            p.environment = env; p.standardOutput = out; try! p.run(); p.waitUntilExit()
            return String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)!.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        try! #"{"permissions": {"defaultMode": "acceptEdits"}}"#.write(to: settings, atomically: true, encoding: .utf8)
        check("bypass keys: a mode the person set stays", run(["Resources/hooks/install-hooks.py", "--bypass-defaults", "on"]) == "set skipDangerousModePermissionPrompt")
        check("bypass off: only what the Kit set goes", run(["Resources/hooks/install-hooks.py", "--bypass-defaults", "off"]) == "removed skipDangerousModePermissionPrompt")
        try! #"{"oauthAccount": {"accountUuid": "acct-1"}}"#.write(to: dir.appendingPathComponent(".claude.json"), atomically: true, encoding: .utf8)
        let desk = dir.appendingPathComponent("desktop.json")
        try! #"{"preferences": {"other": 1}}"#.write(to: desk, atomically: true, encoding: .utf8)
        check("Claude app: both set when missing", run(["Resources/hooks/desktop-prefs.py", "apply", "--bypass"]) == "set ccAutoArchiveOnPrClose, bypassPermissionsGateByAccount")
        try! #"{"preferences": {"other": 1, "ccAutoArchiveOnPrClose": true}}"#.write(to: desk, atomically: true, encoding: .utf8)
        check("Claude app: the app dropped the gate, it comes back; a changed value stays", run(["Resources/hooks/desktop-prefs.py", "apply", "--bypass"]) == "set bypassPermissionsGateByAccount")
        check("Claude app: bypass off takes the gate out", run(["Resources/hooks/desktop-prefs.py", "bypass-off"]) == "removed bypassPermissionsGateByAccount")
        let p = (try! JSONSerialization.jsonObject(with: Data(contentsOf: desk)) as! [String: Any])["preferences"] as! [String: Any]
        check("Claude app: other settings kept", p["other"] as? Int == 1 && p["ccAutoArchiveOnPrClose"] as? Bool == true)
        try? FileManager.default.removeItem(at: dir)
        print(fails == 0 ? "all passed" : "\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
