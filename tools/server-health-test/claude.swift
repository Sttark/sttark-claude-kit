// A stand-in for Claude Code's `claude rc`, for tools/server-health-test.swift. A real program, so `ps` shows
// "<path>/claude rc ..." as it shows the real one. It never connects to anything.
//
// The words in the file <its path>.mode set what it does:
//   (none)    a Claude Code with --spawn: without it, asks the spawn mode question as Claude Code 2.1.325 does in a
//             git repo, and waits; with it, or once answered (saved in <its path>.saved), shows a connected server
//   old       a Claude Code from before --spawn: its help doesn't name it, the option is an error, and it never asks
//   other     asks a question the Kit doesn't know, and waits
//   exit      stops at once with an error
//   stubborn  ignores SIGHUP and SIGTERM, and goes on waiting when its terminal closes: a `claude rc` at a question
//             outlives its screen this way, which is how copies piled up
// Each run adds its arguments to <its path>.calls. Built with -D NEWER, it says it is a newer version.
import Foundation

let me = CommandLine.arguments[0]
let args = Array(CommandLine.arguments.dropFirst())
let mode = (try? String(contentsOfFile: me + ".mode", encoding: .utf8)) ?? ""
func has(_ w: String) -> Bool { mode.split(whereSeparator: { $0 == " " || $0 == "\n" }).contains(Substring(w)) }
#if NEWER
let version = "2.1.1000 (Claude Code)"
#else
let version = "2.1.999 (Claude Code)"
#endif

if let h = FileHandle(forWritingAtPath: me + ".calls") ?? { FileManager.default.createFile(atPath: me + ".calls", contents: nil); return FileHandle(forWritingAtPath: me + ".calls") }() {
    h.seekToEndOfFile(); h.write((args.joined(separator: " ") + "\n").data(using: .utf8)!); try? h.close()
}
setvbuf(stdout, nil, _IONBF, 0)
if args.contains("--version") { print(version); exit(0) }
if args.contains("--help") || args.contains("-h") {
    print("Remote Control - Control local sessions from claude.ai/code or the Claude mobile app\n\nOPTIONS\n  --name <name>                    Name for the session\n  --permission-mode <mode>         Permission mode for spawned sessions")
    if !has("old") { print("  --spawn <mode>                   Spawn mode: same-dir, worktree, session\n                                   (default: same-dir)\n  --capacity <N>                   Max concurrent sessions in worktree or\n                                   same-dir mode (default: 32)") }
    exit(0)
}
guard args.first == "rc" || args.first == "remote-control" else { print(version); exit(0) }
if has("stubborn") { signal(SIGHUP, SIG_IGN); signal(SIGTERM, SIG_IGN) }
let spawn = args.contains("--spawn") || args.contains { $0.hasPrefix("--spawn=") }
if spawn && has("old") {
    FileHandle.standardError.write("Error: Unknown argument: --spawn\nRun 'claude remote-control --help' for usage.\n".data(using: .utf8)!)
    exit(1)
}
if has("exit") { print("Error: Remote Control could not start (a test)"); exit(1) }

func forever() -> Never { while true { sleep(3600) } }
func connected() -> Never {
    let name = (FileManager.default.currentDirectoryPath as NSString).lastPathComponent
    print("\n\u{00B7} \u{2714} Connected \u{00B7} \(name)\n    Capacity: 0/32 \u{00B7} New sessions will be created in the current directory\n\nContinue coding in the Claude mobile app or https://claude.ai/code?environment=env_test\nspace to show QR code")
    forever()
}
/// The answer typed on its terminal; nil when the terminal closed (a stubborn copy then waits on).
func answer() -> String? {
    guard let a = readLine() else { if has("stubborn") { forever() }; return nil }
    return a.trimmingCharacters(in: .whitespaces)
}

if has("other") {
    print("\nPick a region for this server:\n  [1] here\n  [2] there")
    print("Region [1/2]: ", terminator: "")
    _ = answer()
    forever()
}
let saved = me + ".saved"
if spawn || has("old") || FileManager.default.fileExists(atPath: saved) { connected() }
print("\nRemote Control is launching in spawn mode, which lets you start new sessions in this project from claude.ai/code or the Claude mobile app. Learn more: https://code.claude.com/docs/en/remote-control\nSpawn mode for this project:\n  [1] same-dir \u{2014} sessions share the current directory (default)\n  [2] worktree \u{2014} each session gets an isolated git worktree\nThis can be changed later or explicitly set with --spawn=same-dir or --spawn=worktree.\n")
print("Choose [1/2] (default: 1): ", terminator: "")
guard let a = answer() else {
    print("\nRemote Control did not start: \"Choose [1/2] (default: 1):\" got no answer. You can run `claude remote-control` and choose, or pass --spawn=same-dir or --spawn=worktree.")
    exit(1)
}
try? (a == "2" ? "worktree" : "same-dir").write(toFile: saved, atomically: true, encoding: .utf8)
connected()
