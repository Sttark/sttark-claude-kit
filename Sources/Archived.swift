import Foundation

/// The window's Archived page: the person's archived sessions that this Mac can bring back, newest first.
/// effort-hook.py writes the list to archived.json: keep() from the session list it reads every 15 seconds while the
/// server runs, and `effort-hook.py --archived` on a Mac with no server (every 10 minutes, and when the page opens).
/// The phone reads the same file, so both show the same list. Bring it back is KitActions.unarchive.
enum Archived {
    struct Item: Identifiable {
        /// The session's Remote Control id (cse_…).
        let id: String
        let title: String
        let folder: String
        let transcript: String
        /// When it was last active: the server gives no archive time, and a session is archived after its last event.
        let at: Date
        let url: String
        /// What it was doing: the server's own summary of its last turn.
        let doing: String

        var folderShort: String { folder.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~") }
    }

    struct List {
        var items: [Item] = []
        /// When effort-hook.py last wrote it.
        var at: Date?
    }

    static var file: URL { supportDir.appendingPathComponent("archived.json") }

    /// The list as effort-hook.py last wrote it, less any session that has a Kit wait now (it shows under Waiting on
    /// someone else) or that the Claude app lists again (brought back): a session shows in one list only, at once.
    static func read(_ state: [String: Any] = State.read()) -> List {
        guard let d = try? Data(contentsOf: file),
              let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return List() }
        let waits = Set(Waits.list(state).map(\.cse))
        let open = Set(State.appList(state)?.items.keys.map { $0 } ?? [])
        let items: [Item] = (j["items"] as? [[String: Any]] ?? []).compactMap { x in
            guard let id = x["cse"] as? String, !waits.contains(id), !open.contains(id) else { return nil }
            return Item(id: id, title: (x["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "Session " + id.suffix(6),
                        folder: x["folder"] as? String ?? "", transcript: x["transcript"] as? String ?? "",
                        at: Date(timeIntervalSince1970: Limit.num(x["archived_at"]) ?? 0),
                        url: x["url"] as? String ?? "", doing: x["doing"] as? String ?? "")
        }
        return List(items: items, at: Limit.num(j["at"]).map { Date(timeIntervalSince1970: $0) })
    }

    private static var reading = false

    /// Reads the list from Claude again when archived.json is older than `olderThan` seconds. Where the server runs,
    /// keep() writes it at least once a minute, so this reads nothing more there.
    static func refresh(olderThan: TimeInterval) {
        guard !reading else { return }
        if let at = read([:]).at, -at.timeIntervalSinceNow < olderThan { return }
        reading = true
        DispatchQueue.global(qos: .utility).async {
            Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path, "--archived"])
            DispatchQueue.main.async { reading = false }
        }
    }
}
