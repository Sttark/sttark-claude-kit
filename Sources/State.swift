import Foundation
import ServiceManagement

/// The app's folder in Application Support. STTARK_KIT_DIR and STTARK_KIT_LOG point the code at a test folder and
/// log, as they do for the hooks; the drawing tool (tools/screenshot.swift) uses them. The app itself never sets them.
let supportDir: URL = {
    let env = ProcessInfo.processInfo.environment["STTARK_KIT_DIR"] ?? ""
    let u = !env.isEmpty ? URL(fileURLWithPath: env)
        : FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("SttarkClaudeKit")
    try? FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
    return u
}()
let hooksDir = supportDir.appendingPathComponent("hooks")
let logURL: URL = {
    let env = ProcessInfo.processInfo.environment["STTARK_KIT_LOG"] ?? ""
    return !env.isEmpty ? URL(fileURLWithPath: env)
        : FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/sttark-claude-kit.log")
}()

/// One line in the same log the hook writes, so everything is in one place.
func note(_ s: String) { logLine("app", s) }

/// A log line under its first word, padded as the hooks pad theirs ("app    ", "limit  ").
func logLine(_ tag: String, _ s: String) {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    let line = f.string(from: Date()) + " " + tag.padding(toLength: max(6, tag.count), withPad: " ", startingAt: 0) + " " + s + "\n"
    if let h = try? FileHandle(forWritingTo: logURL) {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close()
    } else {
        try? line.write(to: logURL, atomically: true, encoding: .utf8)
    }
}

struct Session {
    /// The key in state.sessions: the Remote Control id (cse_…).
    let id: String
    /// Claude Code's own id for the session: its transcript's file name. Empty when not known.
    var sid: String = ""
    let title: String
    let level: String
    let reason: String
    let manual: Bool
    let at: Date
    /// From the Claude app, checked every minute: the link, and when Claude finished a reply you haven't read yet.
    var url: String = ""
    var waitingSince: Date? = nil
    var why: String = ""
    /// Claude needs you (blocked, or the reply asks you); otherwise just not opened yet.
    var needsYou = false
}

/// The state file the hook and the app share: {"paused": bool, "sessions": {id: {...}}}.
/// Both sides take the same lock before writing.
enum State {
    static let file = supportDir.appendingPathComponent("state.json")

    static func read() -> [String: Any] {
        (try? JSONSerialization.jsonObject(with: Data(contentsOf: file))) as? [String: Any] ?? [:]
    }

    static func change(_ edit: (inout [String: Any]) -> Void) {
        let fd = open(file.path + ".lock", O_CREAT | O_RDWR, 0o644)
        guard fd >= 0 else { return }
        flock(fd, LOCK_EX)
        defer { flock(fd, LOCK_UN); close(fd) }
        var s = read()
        edit(&s)
        if let d = try? JSONSerialization.data(withJSONObject: s, options: [.prettyPrinted]) {
            try? d.write(to: file, options: .atomic)
        }
    }

    static var paused: Bool { read()["paused"] as? Bool ?? false }

    static func setPaused(_ on: Bool) {
        change { $0["paused"] = on }
        note(on ? "auto effort turned off for every session" : "auto effort turned on")
    }

    static func setManual(_ id: String, _ on: Bool) {
        change { s in
            var all = s["sessions"] as? [String: Any] ?? [:]
            var x = all[id] as? [String: Any] ?? [:]
            x["manual"] = on
            if !on {   // the current level, and the server's latest change, become the starting point again
                x.removeValue(forKey: "sent")
                x.removeValue(forKey: "seen_id")
            }
            all[id] = x
            s["sessions"] = all
        }
        note("\(id) set to \(on ? "Manual" : "Auto") from the menu")
    }

    /// The models the hook can use: the two newest Haiku and two newest Sonnet, as the hook last listed them.
    static var models: [(id: String, label: String)] {
        (read()["models"] as? [[String: String]] ?? []).compactMap { m in
            guard let id = m["id"], let label = m["label"] else { return nil }
            return (id, label)
        }
    }

    /// The model picked in the menu; nil means the newest Sonnet.
    static var model: String? { read()["model"] as? String }

    static func setModel(_ id: String) {
        change { $0["model"] = id }
        note("model set to \(id)")
    }

    /// Asks the hook for the current list of models. Runs off the main thread; it calls the API.
    static func refreshModels(done: @escaping () -> Void = {}) {
        DispatchQueue.global().async {
            Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path, "--models"])
            DispatchQueue.main.async(execute: done)
        }
    }

    /// Sessions seen in the last `hours`, newest first. Archived ones are left out.
    static func sessions(hours: Double = 12) -> [Session] {
        let all = read()["sessions"] as? [String: [String: Any]] ?? [:]
        let cutoff = Date().addingTimeInterval(-hours * 3600)
        return all.compactMap { id, x in
            let at = Date(timeIntervalSince1970: x["at"] as? Double ?? 0)
            guard at > cutoff, !((x["app"] as? [String: Any])?["archived"] as? Bool ?? false) else { return nil }
            let t = (x["title"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            var s = Session(id: id, title: t.isEmpty ? "Session " + id.suffix(6) : t,
                            level: x["level"] as? String ?? "?", reason: x["reason"] as? String ?? "",
                            manual: x["manual"] as? Bool ?? false, at: at)
            if let tp = x["transcript"] as? String, tp.hasSuffix(".jsonl") {
                s.sid = String((tp as NSString).lastPathComponent.dropLast(6))
            }
            if let a = x["app"] as? [String: Any] {
                s.url = a["url"] as? String ?? ""
                let iso = ISO8601DateFormatter()
                iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                s.why = a["why"] as? String ?? ""
                s.needsYou = a["needs"] as? Bool ?? false
                if (s.needsYou || (a["unseen"] as? Bool ?? false)), !(a["working"] as? Bool ?? true),
                   let d = iso.date(from: a["last_event_at"] as? String ?? "") {
                    s.waitingSince = d
                }
            }
            return s
        }.sorted { $0.at > $1.at }
    }
}

/// Copies the hook scripts out of the app and adds them to Claude Code's settings.
/// Runs on every launch, so an update brings new scripts and a removed hook comes back.
enum Setup {
    static var claudeFound: Bool {
        FileManager.default.isExecutableFile(atPath: FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".local/bin/claude").path)
    }

    @discardableResult
    static func install() -> String {
        let fm = FileManager.default
        guard let src = Bundle.main.resourceURL?.appendingPathComponent("hooks") else { return "no hooks in the app" }
        try? fm.createDirectory(at: hooksDir, withIntermediateDirectories: true)
        for name in (try? fm.contentsOfDirectory(atPath: src.path)) ?? [] where name.hasSuffix(".py") || name.hasSuffix(".sh") || name.hasSuffix(".js") || name.hasSuffix(".pem") {
            let to = hooksDir.appendingPathComponent(name)
            if fm.contentsEqual(atPath: src.appendingPathComponent(name).path, andPath: to.path) { continue }
            try? fm.removeItem(at: to)
            try? fm.copyItem(at: src.appendingPathComponent(name), to: to)
            try? fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: to.path)
        }
        let out = Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("install-hooks.py").path])
        let r = out.1.trimmingCharacters(in: .whitespacesAndNewlines)
        if r != "unchanged" { note("hooks: \(r)") }
        return r
    }

    static func remove() {
        let r = Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("install-hooks.py").path, "--remove"])
        note("hooks: \(r.1.trimmingCharacters(in: .whitespacesAndNewlines))")
    }

    /// Start at login, from the copy in an Applications folder. A copy run from anywhere else (a test build)
    /// never takes it over, and the Applications copy takes it back. Set once per copy, so turning it off in
    /// System Settings > General > Login Items sticks.
    static func loginItem() {
        let d = UserDefaults.standard
        let here = Bundle.main.bundlePath
        guard here.hasSuffix(".app"), here.contains("/Applications/"), d.string(forKey: "loginItemPath") != here else { return }
        try? SMAppService.mainApp.unregister()   // drops one another copy registered
        try? SMAppService.mainApp.register()
        d.set(here, forKey: "loginItemPath")
        note("starts at login from \(here)")
    }
}
