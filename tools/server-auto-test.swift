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
        
        // srcFolder(): ~/src on every Mac, made when missing
        let h1 = dir.appendingPathComponent("h1")
        try? fm.createDirectory(at: h1, withIntermediateDirectories: true)
        check("~/src is made when it is missing", Server.srcFolder(home: h1) == h1.appendingPathComponent("src").path
              && fm.fileExists(atPath: h1.appendingPathComponent("src").path))
        check("an existing ~/src is used as it is", Server.srcFolder(home: h1) == h1.appendingPathComponent("src").path)

        // the record of a person turning it off (KitDefaults, in this test program's own defaults, never the app's)
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)
        check("not turned off at first", !Server.turnedOff)
        KitDefaults.chose("server", on: false)
        check("turned off by hand counts", Server.turnedOff)
        KitDefaults.chose("server", on: true)
        check("turned on again clears it", !Server.turnedOff)
        UserDefaults.standard.removeObject(forKey: KitDefaults.offKey)

        // ServerHealth.read(): what the server's screen says, from real screens (hardcopy of `claude rc` in screen)
        let trust = """
        Remote Control starts Claude Code sessions in this folder, driven from your othe
        r devices:
          /Users/x/Daily Plan
        Quick safety check: is this a project you created or one you trust? Sessions sta
        rted here can read, edit, and execute files, and this folder's project settings
        (hooks, MCP servers, permission rules, helper commands) apply to them.
        Security guide: https://code.claude.com/docs/en/security
        Trust /Users/x/Daily Plan? [y/N]

        """
        check("a folder not trusted yet: the trust question", ServerHealth.read(trust) == .trustPrompt)
        let connected = trust.replacingOccurrences(of: "[y/N]\n", with: "[y/N] y\n") + """
        \u{FFFD} \u{FFFD} Connected \u{FFFD} Daily Plan
            Capacity: 0/32 \u{FFFD} New sessions will be created in the current directory
        Continue coding in the Claude mobile app or https://claude.ai/code?environment=e
        nv_01ABC
        Or ask Claude to work in this folder from your projects on claude.ai
        space to show QR code
        """
        check("answered and connected, with the folder's name", ServerHealth.read(connected) == .connected("Daily Plan"))
        let busy = """
        [12:39:29] Session failed: Process exited with error cse_01QRd8t9GwjN5qXeDNYs1rv
        · ✔ Connected · src
            Capacity: 10/32 · New sessions will be created in the current directory
            Logbook web app
        Continue coding in the Claude mobile app or https://claude.ai/code?environment=e
        nv_014g7
        space to show QR code
        """
        check("a busy server is connected", ServerHealth.read(busy) == .connected("src"))
        let enable = """
        Take this session with you and pick up right where you left off on any device.
        The session keeps running on this machine. Use your other devices as a remote
        control. Press Ctrl+C to stop.

        Enable Remote Control? (y/n)
        """
        check("a full list that hides the status line still counts", ServerHealth.read("    one\n    two\nContinue coding in the Claude mobile app or https://claude.ai/code?environment=e\nnv_1\nspace to show QR code\n") == .connected(""))
        check("the first-run question", ServerHealth.read(enable) == .enablePrompt)
        check("still starting: nothing to do", ServerHealth.read("Remote Control is launching in spawn mode\n") == .starting)
        check("turned off for the organization", ServerHealth.read("Remote Control is disabled by your organization's policy. Contact your organization admin for access.\n")
              == .failed("Remote Control is turned off for your organization. An admin of your Claude organization must turn it on."))
        check("signed out", ServerHealth.refusal("Not logged in · Please run /login") == "Claude Code is signed out.")
        check("a long-lived token", ServerHealth.refusal("Remote Control requires a full-scope login token. Long-lived tokens (from setup-token) ...")?
              .contains("long-lived token") == true)
        check("an API key", ServerHealth.refusal("Remote Control is only available with claude.ai subscriptions. Run /login")?.contains("API key") == true)
        check("a trust question already answered is not a question", ServerHealth.read(trust.replacingOccurrences(of: "[y/N]\n", with: "[y/N] y\n")) != .trustPrompt)

        try? fm.removeItem(at: dir)
        print(fails == 0 ? "\nall passed" : "\n\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
