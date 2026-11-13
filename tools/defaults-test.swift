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
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)
        var fails = 0
        func check(_ name: String, _ ok: Bool) { print((ok ? "ok   " : "FAIL ") + name); if !ok { fails += 1 } }
        let allOff = ["names": false, "profile": false, "fileLinks": false]
        check("new Mac: all three come on", KitDefaults.due(on: allOff, claudeAppSignedIn: true) == ["names", "profile", "fileLinks"])
        check("no Claude app sign-in: the sync waits", KitDefaults.due(on: allOff, claudeAppSignedIn: false) == ["names", "fileLinks"])
        check("already on: nothing to do", KitDefaults.due(on: ["names": true, "profile": true, "fileLinks": true], claudeAppSignedIn: true).isEmpty)
        KitDefaults.chose("names", on: false)
        check("turned off by hand: stays off", !KitDefaults.due(on: allOff, claudeAppSignedIn: true).contains("names"))
        KitDefaults.chose("names", on: true)
        check("turned on again: the record is gone", !KitDefaults.turnedOff("names"))
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
        try? FileManager.default.removeItem(at: dir)
        print(fails == 0 ? "all passed" : "\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
