import Foundation
import ServiceManagement

let supportDir: URL = {
    let u = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("SttarkClaudeKit")
    try? FileManager.default.createDirectory(at: u, withIntermediateDirectories: true)
    return u
}()
let hooksDir = supportDir.appendingPathComponent("hooks")
let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/sttark-claude-kit.log")

/// One line in the same log the hook writes, so everything is in one place.
func note(_ s: String) {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm:ss"
    let line = f.string(from: Date()) + " app    " + s + "\n"
    if let h = try? FileHandle(forWritingTo: logURL) {
        h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close()
    } else {
        try? line.write(to: logURL, atomically: true, encoding: .utf8)
    }
}

struct Session {
    let id: String
    let title: String
    let level: String
    let reason: String
    let manual: Bool
    let at: Date
    /// From the Claude app, checked every minute: the link, and when Claude finished a reply you haven't read yet.
    var url: String = ""
    var waitingSince: Date? = nil
    var why: String = ""
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
            if !on { x.removeValue(forKey: "sent") }   // the current level becomes the starting point again
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

    /// Sessions seen in the last `hours`, newest first.
    static func sessions(hours: Double = 12) -> [Session] {
        let all = read()["sessions"] as? [String: [String: Any]] ?? [:]
        let cutoff = Date().addingTimeInterval(-hours * 3600)
        return all.compactMap { id, x in
            let at = Date(timeIntervalSince1970: x["at"] as? Double ?? 0)
            guard at > cutoff else { return nil }
            let t = (x["title"] as? String ?? "").trimmingCharacters(in: .whitespaces)
            var s = Session(id: id, title: t.isEmpty ? "Session " + id.suffix(6) : t,
                            level: x["level"] as? String ?? "?", reason: x["reason"] as? String ?? "",
                            manual: x["manual"] as? Bool ?? false, at: at)
            if let a = x["app"] as? [String: Any] {
                s.url = a["url"] as? String ?? ""
                let iso = ISO8601DateFormatter()
                iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                s.why = a["why"] as? String ?? ""
                if (a["needs"] as? Bool ?? false), !(a["archived"] as? Bool ?? false), !(a["working"] as? Bool ?? true),
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
        for name in (try? fm.contentsOfDirectory(atPath: src.path)) ?? [] where name.hasSuffix(".py") || name.hasSuffix(".sh") {
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

    /// Start at login. Set once, so turning it off in System Settings > General > Login Items sticks.
    static func loginItem() {
        let d = UserDefaults.standard
        guard !d.bool(forKey: "loginItemSet"), Bundle.main.bundlePath.hasSuffix(".app") else { return }
        try? SMAppService.mainApp.register()
        d.set(true, forKey: "loginItemSet")
    }
}
