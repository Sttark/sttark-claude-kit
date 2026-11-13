// Tests how the Kit sets up "Start sessions from the Claude app" by itself (Server.decide, Server.defaultFolder and
// the turned-off record in Sources/Server.swift), with made-up facts and a temporary home folder. Starts no server.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/server-auto-test tools/server-auto-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/server-auto-test
import Foundation

@main struct ServerAutoTest {
    static func main() {
        let fm = FileManager.default
        let dir = fm.temporaryDirectory.appendingPathComponent("kit-servertest-\(getpid())")
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.appendingPathComponent("kit").path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        var fails = 0
        func check(_ name: String, _ ok: Bool) { print((ok ? "ok   " : "FAIL ") + name); if !ok { fails += 1 } }

        // decide(): every reason not to start comes before the folder is looked for
        var looked = false
        func d(installed: Bool = false, elsewhere: Bool = false, off: Bool = false, claude: Bool = true, signedIn: Bool = true,
               folder: String? = "/Users/x/src") -> Server.AutoStep {
            looked = false
            return Server.decide(installed: installed, elsewhere: elsewhere, turnedOff: off, claudeFound: claude, signedIn: signedIn,
                                 folder: { looked = true; return folder })
        }
        check("a fresh Mac starts it in the folder found", d() == .start("/Users/x/src"))
        check("already on: nothing", d(installed: true) == .skip("already on") && !looked)
        check("a server set up another way: left alone", d(elsewhere: true) == .skip("a server set up another way runs") && !looked)
        check("turned off in Settings: never again", d(off: true) == .skip("turned off in Settings") && !looked)
        check("no Claude Code: waits", d(claude: false) == .skip("Claude Code isn't installed") && !looked)
        check("signed out, or only a setup-token: waits", d(signedIn: false) == .skip("Claude Code isn't signed in") && !looked)
        check("no project folder: asks", d(folder: nil) == .ask)

        // defaultFolder()
        func mk(_ p: String) { try? fm.createDirectory(at: dir.appendingPathComponent(p), withIntermediateDirectories: true) }
        func home(_ name: String, _ paths: [String]) -> URL {
            let h = dir.appendingPathComponent(name)
            mk(name)
            paths.forEach { mk(name + "/" + $0) }
            return h
        }
        let a = home("a", ["src", "code/one/.git", "code/two/.git"])
        check("~/src wins when there is one", Server.defaultFolder(home: a) == a.appendingPathComponent("src").path)
        let b = home("b", ["code/one/.git", "projects/one/.git", "projects/two/.git", "projects/three/.git"])
        check("else the folder with the most repos", Server.defaultFolder(home: b) == b.appendingPathComponent("projects").path)
        let c = home("c", ["Developer/GitHub/one/.git", "Developer/GitHub/two/.git", "work/one/.git"])
        check("two levels down counts too", Server.defaultFolder(home: c) == c.appendingPathComponent("Developer/GitHub").path)
        let e = home("e", ["Documents/GitHub/one/.git", "Documents/GitHub/two/.git", "Desktop/one/.git", ".hidden/one/.git",
                           "Library/one/.git", "solo/.git", "solo/inner/.git"])
        check("never Documents, Desktop, Library, a hidden folder or a repo itself", Server.defaultFolder(home: e) == nil)
        let f = home("f", ["empty", "notes/readme"])
        check("no repos at all: nothing", Server.defaultFolder(home: f) == nil)
        let g = home("g", ["one/x/.git", "two/y/.git"])
        check("a tie: the first one found, never the home folder", [g.appendingPathComponent("one").path, g.appendingPathComponent("two").path]
            .contains(Server.defaultFolder(home: g) ?? ""))

        // the record of a person turning it off (KitDefaults, in this test program's own defaults, never the app's)
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)
        check("not turned off at first", !Server.turnedOff)
        KitDefaults.chose("server", on: false)
        check("turned off by hand counts", Server.turnedOff)
        KitDefaults.chose("server", on: true)
        check("turned on again clears it", !Server.turnedOff)
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)

        try? fm.removeItem(at: dir)
        print(fails == 0 ? "\nall passed" : "\n\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
