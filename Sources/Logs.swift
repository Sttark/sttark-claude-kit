import Foundation

/// The Kit's logs, trimmed so they never grow without end. The window never shows them: its Events page tells what
/// the Kit did in plain words. Many processes write to them at once (every hook opens the file for each line;
/// launchd holds the profile sync's and the server's open), so a trim rewrites in place and keeps what came in.
enum KitLogs {
    struct Log: Identifiable, Hashable {
        let id: String      // a short name for the picker
        let url: URL
        let what: String    // one line for the page
    }

    static let keepDays = 30
    static let keepBytes = 10_000_000

    /// Every log the Kit writes. The Kit's own log comes first; it follows STTARK_KIT_LOG like the rest of the app.
    static var all: [Log] {
        let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs")
        if let dir = ProcessInfo.processInfo.environment["STTARK_KIT_LOGS_DIR"], !dir.isEmpty {
            return files(logURL, URL(fileURLWithPath: dir))
        }
        return files(logURL, logs)
    }

    private static func files(_ kit: URL, _ d: URL) -> [Log] {
        [Log(id: "Kit", url: kit, what: "Every decision the Kit makes"),
         Log(id: "Bypass", url: d.appendingPathComponent("claude-bypass-hook.log"), what: "Each session switched to Bypass permissions"),
         Log(id: "Chrome approver", url: d.appendingPathComponent("claude-chrome-approver.log"), what: "Each Claude in Chrome approval"),
         Log(id: "Profile sync", url: d.appendingPathComponent("claude-profile-sync.log"), what: "Each sync of your Claude profile instructions"),
         Log(id: "Server", url: d.appendingPathComponent("claude-rc.log"), what: "What the Remote Control server prints")]
    }

    // MARK: trimming

    /// Trims every log now, then every 6 hours.
    static func start() {
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 60) { trimAll() }
        Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { _ in DispatchQueue.global(qos: .utility).async { trimAll() } }
    }

    static func trimAll(now: Date = Date()) {
        for l in all {
            if let (before, after) = trim(l.url, now: now) {
                note("log    trimmed \(l.url.lastPathComponent): \(before / 1000) KB to \(after / 1000) KB (keeps \(keepDays) days, at most \(keepBytes / 1_000_000) MB)")
            }
        }
    }

    /// Keeps the lines of the last `days` days, and at most `bytes` of them (the newest). Lines start with their
    /// date (2026-11-13 11:35:39, or 2026-11-13T15:44:30Z); a line with no date goes with the dated line before it.
    /// Rewritten in place (truncate, then write), so a writer that holds the file open in append mode, as launchd
    /// does, goes on writing at its new end; lines added while it reads are kept. Returns the sizes before and after,
    /// or nil when there was nothing to cut.
    @discardableResult
    static func trim(_ url: URL, days: Int = keepDays, bytes: Int = keepBytes, now: Date = Date()) -> (Int, Int)? {
        guard let data = try? Data(contentsOf: url), !data.isEmpty else { return nil }
        let nl = UInt8(ascii: "\n")
        var start = 0
        if data.count > bytes {
            start = data.count - bytes
            if let i = data[start...].firstIndex(of: nl) { start = i + 1 } else { start = data.count }
        }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        let cutoff = Array(f.string(from: now.addingTimeInterval(-Double(days) * 86400)).utf8)
        // Lines are in time order: cut up to the first dated line that is on or after the cutoff day.
        var i = start
        while i < data.count {
            let end = data[i...].firstIndex(of: nl) ?? data.count
            if let day = dayPrefix(data, i, end) {
                if !day.lexicographicallyPrecedes(cutoff) { break }
                start = end + 1
            }
            i = end + 1
        }
        start = min(start, data.count)
        guard start > 0 else { return nil }
        guard let h = try? FileHandle(forUpdating: url) else { return nil }
        defer { try? h.close() }
        // What was written since the read goes along.
        let size = (try? h.seekToEnd()) ?? UInt64(data.count)
        var keep = Data(data[start...])
        if size > UInt64(data.count) {
            try? h.seek(toOffset: UInt64(data.count))
            keep.append(h.readDataToEndOfFile())
        }
        do {
            try h.truncate(atOffset: 0)
            try h.seek(toOffset: 0)
            try h.write(contentsOf: keep)
        } catch { return nil }
        return (Int(size), keep.count)
    }

    /// The "yyyy-MM-dd" at the start of a line, as bytes, or nil when the line doesn't start with a date.
    private static func dayPrefix(_ d: Data, _ i: Int, _ end: Int) -> [UInt8]? {
        guard end - i >= 10 else { return nil }
        let b = Array(d[i..<(i + 10)])
        let digits = [0, 1, 2, 3, 5, 6, 8, 9].allSatisfy { b[$0] >= 48 && b[$0] <= 57 }
        return digits && b[4] == 45 && b[7] == 45 ? b : nil
    }
}

