import Foundation

extension Notification.Name {
    /// The Kit's shared state changed on disk: a hook, a command or the app itself wrote it.
    static let kitStateChanged = Notification.Name("kitStateChanged")
}

/// Keeps the window and the menu up to date with what the Claude app shows, with no wait for a timer.
///
/// - **On this Mac:** every hook and command writes the shared state with a new file (write, then rename), so a
///   watch on the Kit's folder sees each change. The window and the menu reload 0.2 seconds after the last change.
/// - **In the Claude app** (a new session, an archive, a new name, a session that starts or stops work): the Kit
///   reads the app's short session list (the sessions that are not archived) every 10 seconds while the window or
///   the menu is open, at once when the menu opens or the Kit itself changes a session, and every minute otherwise
///   (with the minute's check). One read runs at a time; after a failed read every reader waits, see
///   `app_list()` in effort-hook.py.
enum Sync {
    static let fastEvery: TimeInterval = 10
    private static var sources: [DispatchSourceFileSystemObject] = []
    private static var pending: DispatchWorkItem?
    private static var reading = false
    private static var lastRead = Date.distantPast
    /// Whether someone looks at the sessions now: the window shows, or the menu is open.
    static var watching: () -> Bool = { false }

    static func start() {
        watch(supportDir)
        let holds = supportDir.appendingPathComponent("holds")
        try? FileManager.default.createDirectory(at: holds, withIntermediateDirectories: true)
        watch(holds)
        Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in
            // every 8 to 10 seconds, so a change in the Claude app shows within about 10 seconds
            if watching(), -lastRead.timeIntervalSinceNow >= fastEvery - 2 { readList() }
        }
    }

    /// Watches one folder for files that are added, replaced or removed.
    private static func watch(_ dir: URL) {
        let fd = open(dir.path, O_EVTONLY)
        guard fd >= 0 else { return }
        let src = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: [.write, .rename, .delete, .extend],
                                                            queue: .main)
        src.setEventHandler { changed() }
        src.setCancelHandler { close(fd) }
        src.resume()
        sources.append(src)
    }

    /// Many writes in a row (a hook writes several times in one step) make one reload.
    static func changed() {
        pending?.cancel()
        let w = DispatchWorkItem { NotificationCenter.default.post(name: .kitStateChanged, object: nil) }
        pending = w
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: w)
    }

    /// Reads the Claude app's short session list now, unless a read already runs or one ended under
    /// `minGap` seconds ago. A change in the list writes the state, and the watch reloads the window and the menu.
    static func readList(minGap: TimeInterval = 0) {
        guard !reading, -lastRead.timeIntervalSinceNow >= minGap else { return }
        reading = true
        lastRead = Date()
        DispatchQueue.global(qos: .utility).async {
            Updater.run("/usr/bin/python3", [hooksDir.appendingPathComponent("effort-hook.py").path, "--list"])
            DispatchQueue.main.async { reading = false; lastRead = Date() }
        }
    }
}
