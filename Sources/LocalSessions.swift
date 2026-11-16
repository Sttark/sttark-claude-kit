import Foundation

/// Sessions that run only on this Mac: started in Terminal, or under "This computer" in the Claude desktop app,
/// without Remote Control, so the phone, the Claude app's list and the Kit's other groups can't reach them.
/// migrate.py lists them every minute (local-sessions.json) and moves one to Remote Control on request.
enum LocalSessions {
    struct Item {
        let id: String
        let title: String
        let cwd: String
        /// "terminal" or "desktop".
        let whereFrom: String
        let last: Date
        /// Open now: its Claude Code process.
        let pid: Int?
        /// Open and Claude is in a reply.
        let busy: Bool
        /// Waits to move when its reply ends.
        let pending: Bool

        var inDesktop: Bool { whereFrom == "desktop" }
        var whereWords: String { inDesktop ? "the Claude desktop app" : "Terminal" }
        var folder: String { cwd.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~") }
    }

    static var file: URL { supportDir.appendingPathComponent("local-sessions.json") }
    static var script: URL { hooksDir.appendingPathComponent("migrate.py") }

    /// The list migrate.py last wrote; empty when it is more than 10 minutes old.
    static var items: [Item] {
        guard let d = try? Data(contentsOf: file),
              let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let at = Limit.num(j["at"]), Date().timeIntervalSince1970 - at < 600 else { return [] }
        return (j["sessions"] as? [[String: Any]] ?? []).compactMap { x in
            guard let id = x["id"] as? String else { return nil }
            return Item(id: id, title: (x["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "Session " + id.prefix(6),
                        cwd: x["cwd"] as? String ?? "", whereFrom: x["where"] as? String ?? "terminal",
                        last: Date(timeIntervalSince1970: Limit.num(x["last"]) ?? 0),
                        pid: (Limit.num(x["pid"])).map { Int($0) }, busy: x["busy"] as? Bool ?? false,
                        pending: x["pending"] as? Bool ?? false)
        }
    }

    /// Every minute, from the app: the list again, and the moves that waited for a reply to end.
    static func scan(done: (() -> Void)? = nil) {
        DispatchQueue.global().async {
            Updater.run("/usr/bin/python3", [script.path, "--scan"])
            if let done { DispatchQueue.main.async(execute: done) }
        }
    }

    /// Moves one now (closing it where it is open), or when its reply ends. Calls back with what happened.
    static func move(_ item: Item, done: @escaping (Bool, String) -> Void) {
        DispatchQueue.global().async {
            let (code, out) = Updater.run("/usr/bin/python3", [script.path, item.id, "--yes", "--window"])
            Updater.run("/usr/bin/python3", [script.path, "--scan"])
            let words = out.trimmingCharacters(in: .whitespacesAndNewlines)
            DispatchQueue.main.async { done(code == 0, words.isEmpty ? (code == 0 ? "Moved." : "It did not move.") : words) }
        }
    }
}
