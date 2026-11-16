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
        // the spawn mode question, as Claude Code 2.1.325 asks it in a git repo when it has no --spawn
        let spawn = """

        Remote Control is launching in spawn mode, which lets you start new sessions in this project from claude.ai/
        code or the Claude mobile app. Learn more: https://code.claude.com/docs/en/remote-control
        Spawn mode for this project:
          [1] same-dir \u{2014} sessions share the current directory (default)
          [2] worktree \u{2014} each session gets an isolated git worktree
        This can be changed later or explicitly set with --spawn=same-dir or --spawn=worktree.

        Choose [1/2] (default: 1):

        """
        check("the spawn mode question", ServerHealth.read(spawn) == .spawnPrompt)
        check("the spawn mode question, answered, is not a question", ServerHealth.read(spawn.replacingOccurrences(of: "(default: 1):", with: "(default: 1): 1\nSpawn mode: same-dir")) == .starting)
        check("a question the Kit does not know", ServerHealth.read("Pick a region for this server:\n  [1] here\n  [2] there\nRegion [1/2]:\n") == .question("Region [1/2]:"))
        check("a line that ends with a question mark", ServerHealth.read("Keep the old sessions?\n") == .question("Keep the old sessions?"))
        check("a link in brackets is not a question", ServerHealth.read("Learn more (https://code.claude.com/docs/en/remote-control)\n") == .starting)
        check("a copy that still runs keeps the folder", ServerHealth.read("Error: This folder is already served by another Claude Code on this device. Stop it first.\n")
              == .failed(ServerHealth.refusal("already served by another Claude Code")!))
        check("an option this Claude Code does not know", ServerHealth.refusal("Error: Unknown argument: --spawn\nRun 'claude remote-control --help' for usage.")
              == "This Claude Code doesn't know an option the Kit gives it (Unknown argument: --spawn).")
        check("the log's escape codes go", ServerHealth.lastLine("\u{1B}[2mChoose [1/2]\u{1B}[22m\r\n\u{1B}]8;;https://x\u{07}a link\u{1B}]8;;\u{07}\r\n") == "a link")

        // command(): --spawn same-dir only when this Claude Code's help names it, checked when it starts
        let cmd = Server.command(folder: "/Users/x/src", claude: "/Users/x/.local/share/claude/stable/claude", screenrc: "/k/server.screenrc", screen: "claude-rc")
        check("the command starts claude rc in its screen, in the folder, in bypass", cmd.hasPrefix("exec /usr/bin/screen -c '/k/server.screenrc' -DmS claude-rc /bin/zsh -c \"cd '/Users/x/src' && exec '/Users/x/.local/share/claude/stable/claude' rc --permission-mode bypassPermissions "))
        check("the command gives --spawn same-dir when the help names it", cmd.contains("\\$('/Users/x/.local/share/claude/stable/claude' remote-control --help 2>/dev/null | /usr/bin/grep -q -- --spawn && echo --spawn same-dir)\""))
        check("the command's screen still reads as a server", Server.isServer("/usr/bin/screen -c /k/server.screenrc -DmS claude-rc /bin/zsh -c cd '/Users/x/src' && exec '/Users/x/.local/share/claude/stable/claude' rc --permission-mode bypassPermissions $('/Users/x/.local/share/claude/stable/claude' remote-control --help 2>/dev/null | /usr/bin/grep -q -- --spawn && echo --spawn same-dir)"))
        check("a server with --spawn is a server", Server.isServer("/Users/x/.local/share/claude/stable/claude rc --permission-mode bypassPermissions --spawn same-dir"))
        check("its help is not a server", !Server.isServer("/Users/x/.local/share/claude/stable/claude remote-control --help"))
        // the zsh that runs in the screen, with the help of a Claude Code that has --spawn and one that hasn't
        for (help, want) in [("  --spawn <mode>   Spawn mode: same-dir, worktree, session", "rc --permission-mode bypassPermissions --spawn same-dir"),
                             ("  --name <name>    Name for the session", "rc --permission-mode bypassPermissions")] {
            let fake = dir.appendingPathComponent("claude")
            try? "#!/bin/sh\n[ \"$2\" = --help ] && { echo '\(help)'; exit 0; }\necho \"$@\"\n".write(to: fake, atomically: true, encoding: .utf8)
            chmod(fake.path, 0o755)
            let inner = Server.command(folder: dir.path, claude: fake.path, screenrc: "", screen: "")
                .components(separatedBy: "/bin/zsh -c \"").last!.dropLast().replacingOccurrences(of: "\\$", with: "$")
            let out = Updater.run("/bin/zsh", ["-c", inner]).1.trimmingCharacters(in: .whitespacesAndNewlines)
            check("zsh runs: \(want)", out == want)
        }

        // launchctl print, read: the job's own lines only
        let printed = "gui/501/com.sttark.claude-rc = {\n\tactive count = 1\n\tpath = /Users/x/Library/LaunchAgents/com.sttark.claude-rc.plist\n\ttype = LaunchAgent\n\tstate = running\n\n\tprogram = /bin/zsh\n\truns = 221\n\tpid = 6008\n\tlast exit code = 0\n\n\tresource coalition = {\n\t\tid = 1234\n\t\tstate = active\n\t}\n}\n"
        check("launchd's job: its process and how many times it started", Server.job(printed) == Server.Job(loaded: true, pid: 6008, runs: 221))
        check("launchd's job between two starts", Server.job("\tstate = waiting\n\truns = 3\n\tlast exit code = 1\n") == Server.Job(loaded: true, pid: nil, runs: 3))
        // which copies of `claude rc` are the Kit's: its marker or the server screen's STY in the environment
        check("a copy with the Kit's marker", Server.isCopy(environment: "123 /x/claude rc --permission-mode bypassPermissions PATH=/bin STTARK_KIT_SERVER=com.sttark.claude-rc TERM=screen"))
        check("a copy an older Kit started, in the server's screen", Server.isCopy(environment: "123 /x/claude rc --permission-mode bypassPermissions STY=6008.claude-rc TERM=screen WINDOW=0"))
        check("a person's own claude rc in a terminal is not", !Server.isCopy(environment: "123 /x/claude rc TERM=xterm-256color HOME=/Users/x"))
        check("one in another screen is not", !Server.isCopy(environment: "123 /x/claude rc STY=777.kit-0e1262ba TERM=screen"))
        check("a test copy's marker is not the Kit's", !Server.isCopy(environment: "123 /x/claude rc STTARK_KIT_SERVER=com.sttark.claude-rc-test STY=1.claude-rc-test"))
        check("ps's elapsed time in seconds", Server.seconds("05:03") == 303 && Server.seconds("02:03:04") == 7384 && Server.seconds("1-02:03:04") == 93784)

        // isServer(): only a process that runs a server, not a line that mentions one
        check("claude rc", Server.isServer("/Users/x/.local/share/claude/stable/claude rc --permission-mode bypassPermissions"))
        check("claude remote-control", Server.isServer("claude remote-control --name Build"))
        check("through node", Server.isServer("node /opt/homebrew/bin/claude rc"))
        check("a screen running one", Server.isServer("/usr/bin/screen -DmS claude-rc /bin/zsh -c cd '/Users/x/src' && exec '/Users/x/.local/bin/claude' rc"))
        check("not a grep", !Server.isServer("grep claude rc"))
        check("not a shell command that mentions it", !Server.isServer("/bin/zsh -c pgrep -f 'claude rc'"))
        check("not a session with --remote-control", !Server.isServer("/Users/x/.local/bin/claude --resume abc --remote-control"))
        check("not an editor", !Server.isServer("vim notes about claude rc"))

        try? fm.removeItem(at: dir)
        print(fails == 0 ? "\nall passed" : "\n\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }
}
