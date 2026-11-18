import Foundation

/// The window's one search, in its top bar on every page: every session the Sessions page lists, in its groups, and the
/// archived sessions this Mac can bring back, as the last group. Each word typed must be in what the Kit knows of a
/// session, with case and accents ignored: its name, the words on its row, its folder, what each of its waits is for,
/// why then and from whom, its latest progress check-in and the messages kept in the Kit for it; for an archived session,
/// its name, its folder and what it was doing. The Kit keeps no prompt of a session for this, so prompts are not
/// searched. Kit on your phone searches the same way over what the phone gets (phone/src/view/model.ts, searchText).
enum Search {
    /// The words typed, folded; each one must match. None when only spaces are typed.
    static func words(_ q: String) -> [String] {
        fold(q).split(whereSeparator: { $0.isWhitespace }).map(String.init)
    }

    /// Case, accents and width ignored: "Café" and "cafe" are the same word.
    static func fold(_ s: String) -> String {
        s.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive], locale: nil)
    }

    /// A folder with the home folder as "~", so a search for a word of the home folder's path finds nothing.
    static func home(_ path: String) -> String {
        let h = FileManager.default.homeDirectoryForCurrentUser.path
        if path == h { return "~" }
        return path.hasPrefix(h + "/") ? "~" + path.dropFirst(h.count) : path
    }

    /// What a session on the Sessions page is found by, folded.
    static func text(_ r: Inbox.Row) -> String {
        var parts = [r.title, r.sub, r.subStrong, r.folderShort]
        if let s = r.session { parts += [s.reason, s.why] }
        for w in r.waits { parts += [w.what, w.why, w.from, home(w.folder)] }
        if let n = r.checkin { parts.append(n.text) }
        for m in r.kept { parts += [m.subject, m.body] }
        return fold(parts.filter { !$0.isEmpty }.joined(separator: "\n"))
    }

    /// What an archived session is found by, folded.
    static func text(_ x: Archived.Item) -> String {
        fold([x.title, home(x.folder), x.doing].filter { !$0.isEmpty }.joined(separator: "\n"))
    }

    /// Every word is in the text.
    static func matches(_ text: String, _ words: [String]) -> Bool { words.allSatisfy { text.contains($0) } }

    /// What a search found: the sessions in the Sessions page's groups, in its order, then the archived ones, newest
    /// first.
    struct Found {
        var groups: [(group: Inbox.Group, rows: [Inbox.Row])] = []
        var archived: [Archived.Item] = []
        var count: Int { groups.reduce(0) { $0 + $1.rows.count } + archived.count }
        var isEmpty: Bool { count == 0 }
        var rows: [Inbox.Row] { groups.flatMap(\.rows) }
    }

    /// The text of every session, made once for each read of the state (KitModel keeps it until the next one), so a
    /// key typed only compares words: thousands of archived sessions take a few milliseconds.
    struct Index {
        var rows: [(row: Inbox.Row, text: String)] = []
        var archived: [(item: Archived.Item, text: String)] = []

        init() {}
        init(_ snap: Inbox.Snapshot, _ archived: [Archived.Item]) {
            rows = snap.rows.map { ($0, Search.text($0)) }
            self.archived = archived.map { ($0, Search.text($0)) }
        }

        func find(_ words: [String]) -> Found {
            var f = Found()
            guard !words.isEmpty else { return f }
            let hit = rows.filter { matches($0.text, words) }.map(\.row)
            for g in Inbox.Group.allCases {
                let r = hit.filter { $0.group == g }
                if !r.isEmpty { f.groups.append((g, r)) }
            }
            f.archived = archived.filter { matches($0.text, words) }.map(\.item)
            return f
        }
    }
}
