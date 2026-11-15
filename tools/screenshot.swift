// Draws the README's pictures with the app's own code, from made-up sessions in a temporary folder. Nothing from
// this Mac's own state:
//   docs/menu.png             the menu: what needs you, one row for each other group, one group's submenu open
//   docs/window-sessions.png  the window's Sessions page, a session that waits on someone else selected
//   docs/window-archived.png  the window's Archived page, by day, the newest selected with Bring it back
//   docs/window-settings.png  the window's Settings page
//   docs/settings-phone.png   the Settings page's Phone box in each of its states (Kit on your phone)
//   docs/window-news.png      the window's What's new page
//   docs/window-events.png    the window's Events page, newest first, from sample log lines
//   docs/whats-new.png        the What's new sheet over the window, with this repo's notes
// and the pictures of a few What's new notes in whats-new/ (each crop is named where it is made below).
// Each is light. STTARK_SHOT_DARK=<folder> also draws the window and the sheet in dark mode into that folder.
// The window and the sheet are real windows, put off the screen and captured with screencapture, so they look as
// they do on this Mac; nothing shows on the screen and nothing comes to the front.
// The times are drawn in a time zone where it is late morning, so the sample times read the same on every run.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/shot tools/screenshot.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/shot
import AppKit
import SwiftUI

@main struct Shot {
    @MainActor static func main() {
        // A fixed late-morning clock: the sample times below are today, after it.
        let utcHour = Calendar(identifier: .gregorian).dateComponents(in: TimeZone(identifier: "UTC")!, from: Date()).hour!
        var offset = 11 - utcHour
        if offset < -11 { offset += 24 }
        if offset > 13 { offset -= 24 }
        setenv("TZ", offset == 0 ? "UTC" : "Etc/GMT\(offset > 0 ? "-" : "+")\(abs(offset))", 1)
        tzset()
        NSTimeZone.resetSystemTimeZone()
        NSTimeZone.default = TimeZone(secondsFromGMT: offset * 3600)!

        // A temporary folder the app's code reads instead of ~/Library/Application Support/SttarkClaudeKit.
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("kit-shot-\(getpid())")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", dir.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        setenv("STTARK_KIT_LOGS_DIR", dir.path, 1)   // the Log page's other logs: none, so nothing of this Mac's
        defer { try? FileManager.default.removeItem(at: dir) }

        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        app.finishLaunching()
        app.appearance = NSAppearance(named: .aqua)
        let dark = ProcessInfo.processInfo.environment["STTARK_SHOT_DARK"]

        // What's new: the notes in whats-new/, built as build.sh builds them into the app.
        let notes = dir.appendingPathComponent("whats-new")
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = ["tools/whats-new.py", "build", notes.path]
        p.standardOutput = FileHandle.nullDevice
        try! p.run()
        p.waitUntilExit()
        setenv("STTARK_WHATS_NEW_DIR", notes.path, 1)

        Sample.write(dir)
        let facts = Sample.facts
        let c = Controller()
        let menu = NSMenu()
        let snap = Inbox.snapshot()
        c.build(menu, facts, snap)
        // the menu with one group's submenu open, as it shows when you point at the group
        let heldRow = menu.items.firstIndex { $0.submenu != nil && $0.image?.accessibilityDescription == Inbox.Group.held.title }
        for look in [false, true] where !look || dark != nil {
            Draw.dark = look
            Draw.png(menu.items, hot: heldRow, menuBar: true, to: (look ? dark! : "docs") + "/menu.png")
        }
        // the What's new note's picture: the same menu with fewer sessions, so it fits the note's frame
        var small = snap
        let keep = Set(snap.rows(.needs).prefix(1).map(\.id))
        small.rows = snap.rows.filter { $0.group != .needs || keep.contains($0.id) }.filter { $0.group != .idle && $0.group != .local }
            .map { var r = $0; r.subWarn = false; return r }
        let noteMenu = NSMenu()
        var noteFacts = facts
        noteFacts.whatsNewUnseen = 1
        c.build(noteMenu, noteFacts, small)
        for look in [false, true] {
            Draw.dark = look
            Draw.png(noteMenu.items, hot: nil, menuBar: false, to: "whats-new/menu-groups" + (look ? "-dark" : "") + ".png")
        }
        Draw.dark = false

        let model = KitModel()
        model.fixedFacts = facts
        model.reload()
        model.reloadFacts()
        model.phone = Sample.phone[2].1   // Settings shows Kit on your phone linked
        for look in [false, true] where !look || dark != nil {
            Shot.phoneStates(dark: look, to: (look ? dark! : "docs") + "/settings-phone.png")
        }
        model.selected = model.snap.rows.first { $0.wait?.kind == "email-reply" }?.id
        let w = Shot.window(model)
        for look in [false, true] where !look || dark != nil {
            let folder = look ? dark! : "docs"
            w.appearance = NSAppearance(named: look ? .darkAqua : .aqua)
            model.page = .sessions
            Shot.capture(w, to: folder + "/window-sessions.png")
            model.page = .archived
            model.reload()
            model.archivedSelected = model.archived.items.first?.id
            let arch = "/tmp/kit-shot-\(getpid())-archived.png"
            Shot.capture(w, to: arch)
            try? FileManager.default.removeItem(atPath: folder + "/window-archived.png")
            try? FileManager.default.copyItem(atPath: arch, toPath: folder + "/window-archived.png")
            print("wrote \(folder)/window-archived.png")
            // the archived note's picture: the selected session with Open and Bring it back
            Shot.crop(arch, NSRect(x: 840, y: 56, width: 340, height: 256),
                      to: "whats-new/archived-sessions" + (look ? "-dark" : "") + ".png")
            ShotWindow.key = true   // Settings as the person sees it while using it: an on switch in its accent color
            model.page = .settings
            Shot.redraw(w)
            Shot.capture(w, to: folder + "/window-settings.png")
            ShotWindow.key = false
            model.page = .news
            Shot.redraw(w)
            Shot.capture(w, to: folder + "/window-news.png")
            model.page = .events
            model.readEvents()
            RunLoop.main.run(until: Date().addingTimeInterval(1))
            model.openEvent = model.events.first { $0.count > 1 }?.id
            RunLoop.main.run(until: Date().addingTimeInterval(0.3))
            Shot.capture(w, to: folder + "/window-events.png")
            model.openEvent = nil
            // the events note's picture: the newest rows alone, at the note's size
            let rows = NSWindow(contentRect: NSRect(x: -9000, y: 0, width: 440, height: 280), styleMask: [.borderless], backing: .buffered, defer: false)
            rows.appearance = w.appearance
            rows.isReleasedWhenClosed = false
            model.openEvent = model.events.first { $0.count > 1 }?.id
            rows.contentView = NSHostingView(rootView: VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(model.events.prefix(4))) { e in
                    EventRow(model: model, e: e, open: model.openEvent == e.id)
                    Hairline()
                }
                Spacer(minLength: 0)
            }.padding(12).frame(width: 440, height: 280).background(K.card).font(K.font(13)).foregroundColor(K.ink))
            rows.setFrameOrigin(NSPoint(x: -9000, y: 0))
            Shot.capture(rows, to: "whats-new/events-page" + (look ? "-dark" : "") + ".png")
            rows.close()
            model.openEvent = nil
            // the subagent-effort note's picture: the agent rows alone
            let agents = model.events.filter { $0.text.hasPrefix("Agent \u{201C}") || $0.text.contains(" so fork ") }
            let ar = NSWindow(contentRect: NSRect(x: -9000, y: 0, width: 440, height: 280), styleMask: [.borderless], backing: .buffered, defer: false)
            ar.appearance = w.appearance
            ar.isReleasedWhenClosed = false
            model.openEvent = agents.last?.id
            ar.contentView = NSHostingView(rootView: VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(agents.prefix(3))) { e in
                    EventRow(model: model, e: e, open: model.openEvent == e.id)
                    Hairline()
                }
                Spacer(minLength: 0)
            }.padding(12).frame(width: 440, height: 280, alignment: .top).background(K.card).font(K.font(13)).foregroundColor(K.ink))
            ar.setFrameOrigin(NSPoint(x: -9000, y: 0))
            Shot.capture(ar, to: "whats-new/subagent-effort" + (look ? "-dark" : "") + ".png")
            ar.close()
            model.openEvent = nil
            // the kit-window note's picture: the top of the session list, at the window's narrowest
            model.page = .sessions
            let f = w.frame
            w.setContentSize(NSSize(width: 960, height: 760))
            w.setFrameOrigin(NSPoint(x: -9000, y: 0))
            let full = "/tmp/kit-shot-\(getpid())-narrow.png"
            Shot.capture(w, to: full)
            Shot.crop(full, NSRect(x: 226, y: 60, width: 392, height: 252),
                      to: "whats-new/kit-window" + (look ? "-dark" : "") + ".png")
            // the sessions-at-once note's picture: the page's heading and its first groups
            Shot.crop(full, NSRect(x: 226, y: 0, width: 390, height: 280),
                      to: "whats-new/sessions-at-once" + (look ? "-dark" : "") + ".png")
            w.setFrame(f, display: true)
            // the What's new sheet, as the menu's What's new item opens it, over the window
            model.page = .sessions
            model.sheet = WhatsNew.all
            w.orderFrontRegardless()
            RunLoop.main.run(until: Date().addingTimeInterval(1.5))
            Shot.capture(w, to: folder + "/whats-new.png", wait: 0.2)
            model.sheet = []
            RunLoop.main.run(until: Date().addingTimeInterval(1))
            // the one-setting note's picture: a held session, pointed at its own setting
            let before = model.selected
            model.selected = model.snap.rows.first { $0.title == "Site map plan" }?.id
            let panel = "/tmp/kit-shot-\(getpid())-held.png"
            Shot.capture(w, to: panel)
            Shot.crop(panel, NSRect(x: 845, y: 255, width: 335, height: 250),
                      to: "whats-new/credits-one-setting" + (look ? "-dark" : "") + ".png")
            // the move note's picture: a session on this Mac only, with Move to Remote Control
            model.selected = model.snap.rows.first { $0.title == "Weekly plan" }?.id
            let local = "/tmp/kit-shot-\(getpid())-local.png"
            Shot.capture(w, to: local)
            Shot.crop(local, NSRect(x: 845, y: 74, width: 335, height: 280),
                      to: "whats-new/move-to-remote-control" + (look ? "-dark" : "") + ".png")
            model.selected = before
        }
        w.close()
    }

    /// The Phone box in Settings in each of its states, one under the other with a caption each, at the width of the
    /// Settings page's column: docs/settings-phone.png.
    static func phoneStates(dark: Bool, to path: String) {
        let view = VStack(alignment: .leading, spacing: 16) {
            ForEach(Sample.phone, id: \.0) { caption, s in
                VStack(alignment: .leading, spacing: 6) {
                    Text(caption).font(K.font(12, true)).foregroundColor(K.steel).padding(.leading, 2)
                    Box { PhoneRow(status: s, link: {}, toggle: {}) }
                }
            }
        }
        .padding(20).frame(width: 480).background(K.card).font(K.font(13)).foregroundColor(K.ink)
        let host = NSHostingView(rootView: view)
        let size = host.fittingSize
        let w = ShotWindow(contentRect: NSRect(x: -9000, y: 0, width: size.width, height: size.height), styleMask: [.borderless], backing: .buffered, defer: false)
        w.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        w.isReleasedWhenClosed = false
        w.contentView = host
        w.setFrameOrigin(NSPoint(x: -9000, y: 0))
        ShotWindow.key = true   // each switch on or off as it really is: on in its accent color, as in the key window
        redraw(w)
        capture(w, to: path)
        ShotWindow.key = false
        w.close()
    }

    /// Every view of the window draws again, so a change of ShotWindow.key shows in the next capture.
    static func redraw(_ w: NSWindow) {
        func all(_ v: NSView) { v.needsDisplay = true; v.subviews.forEach(all) }
        RunLoop.main.run(until: Date().addingTimeInterval(0.3))
        if let v = w.contentView { all(v) }
    }

    /// The window as the app makes it, off the screen.
    static func window(_ model: KitModel) -> NSWindow {
        let w = ShotWindow(contentRect: NSRect(x: -9000, y: 0, width: 1180, height: 760),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        w.titleVisibility = .hidden
        w.titlebarAppearsTransparent = true
        w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: KitRoot(model: model))
        w.setFrameOrigin(NSPoint(x: -9000, y: 0))
        return w
    }

    /// A part of a 2x capture, given in points from the top left.
    static func crop(_ path: String, _ r: NSRect, to out: String) {
        let img = NSImage(contentsOfFile: path)!
        var rect = NSRect(origin: .zero, size: img.size)
        let cg = img.cgImage(forProposedRect: &rect, context: nil, hints: nil)!
        let s: CGFloat = 2   // the captures are 2x
        let part = cg.cropping(to: CGRect(x: r.minX * s, y: r.minY * s, width: r.width * s, height: r.height * s))!
        let rep = NSBitmapImageRep(cgImage: part)
        try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
        print("wrote \(out)")
    }

    /// Shows the window off the screen, lets it draw, and captures it with its own pixels.
    static func capture(_ w: NSWindow, to path: String, wait: TimeInterval = 1.2) {
        if w.sheetParent == nil { w.orderFrontRegardless() }
        RunLoop.main.run(until: Date().addingTimeInterval(wait))
        let t = Process()
        t.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        t.arguments = ["-x", "-o", "-l\(w.windowNumber)", path]
        try! t.run()
        t.waitUntilExit()
        if !FileManager.default.fileExists(atPath: path) || t.terminationStatus != 0 { cache(w, to: path) }
        print("wrote \(path)")
    }

    /// When screencapture can't (the screen is locked): the window's views drawn into a 2x bitmap.
    static func cache(_ w: NSWindow, to path: String) {
        guard let v = w.contentView else { return }
        let size = v.bounds.size
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                                   bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                   bytesPerRow: 0, bitsPerPixel: 0)!
        rep.size = size
        v.cacheDisplay(in: v.bounds, to: rep)
        try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
    }
}

/// Made-up sessions, waits, holds and usage, written where the app's code reads them.
enum Sample {
    static func at(_ hour: Int, _ minute: Int, daysAhead: Int = 0) -> Date {
        var d = Calendar.current.date(bySettingHour: hour, minute: minute, second: 0, of: Date())!
        d = Calendar.current.date(byAdding: .day, value: daysAhead, to: d)!
        return d
    }

    static func iso(_ d: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: d)
    }

    /// Kit on your phone in each state Settings shows, with the words for the picture's captions.
    static var phone: [(String, PhoneLink.Status)] {
        [("Not linked", PhoneLink.Status(stage: .notLinked)),
         ("Linking: the link page is open in the browser", PhoneLink.Status(stage: .linking, code: "KXRT")),
         ("Linked", PhoneLink.Status(stage: .linked, email: "name@sttark.com", connected: true, lastSent: at(11, 30), phones: 1)),
         ("Linked, no phone gets notices yet", PhoneLink.Status(stage: .linked, email: "name@sttark.com", connected: true, lastSent: at(11, 30), phones: 0)),
         ("Linked, the network down", PhoneLink.Status(stage: .linked, email: "name@sttark.com", lastSent: at(11, 2), problem: "no network")),
         ("Removed on the phone", PhoneLink.Status(stage: .removed)),
         ("Not on the roster", PhoneLink.Status(stage: .refused, email: "name@sttark.com",
                                                problem: PhoneLink.notOnRoster)),
         ("Off", PhoneLink.Status(stage: .off))]
    }

    static var facts: MenuFacts {
        var f = MenuFacts(version: "1.140", serverInstalled: true,
                          serverFolder: FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("src").path,
                          bypass: true, chromeApprover: true, chromeWindow: true, fileLinks: true, names: true, profile: true,
                          profileLast: "10:45 AM, no change", workingRules: true)
        f.reach = Reach.Settings(ways: ["chat"], email: "name@sttark.com", phone: "", chat: "https://chat.googleapis.com/v1/spaces/sample")
        f.whatsNew = 3
        f.whatsNewUnseen = 3
        f.models = [("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-haiku-5-5", "Haiku 5.5")]
        f.model = "claude-sonnet-5-5"
        f.loginEnds = Date().addingTimeInterval(20 * 86400)
        f.lastCheck = Date().addingTimeInterval(-6 * 60)
        return f
    }

    static func write(_ dir: URL) {
        let now = Date().timeIntervalSince1970
        // The Log page's sample lines, oldest first as the hooks write them.
        let lf = DateFormatter(); lf.dateFormat = "yyyy-MM-dd HH:mm:ss"
        func logAt(_ m: Double) -> String { lf.string(from: Date().addingTimeInterval(-m * 60)) }
        var lines: [(Double, String)] = [
            (1500, "app    update: installed 1.160, restarting"),
            (1450, "wake   cse_01Sample7 \"Site map plan\" stopped, not archived; sent high to start it"),
            (300, "change cse_01Sample9 ->low (1.9s) low - A simple rename across a few files | Rename the report columns to match the new names"),
            (190, "name   sid-sample-9 -> \"Rename report columns\" (2.0s) | Rename the report columns to match the new names"),
            (62, "agent  cse_01Sample4 Explore ->low (1.9s) low - A short file search. | Find the Events page code"),
            (61, "agent  cse_01Sample4 general-purpose ->xhigh (2.2s) xhigh - A new page design with judgment calls. | Design the event rows"),
            (60, "agent  cse_01Sample4 fork low->high (2.0s) high - Code changes across a few files. | Build the filters"),
            (52, "change cse_01Sample3 medium->low (2.1s) low - Routine edit with a clear plan. | Fix the typo on the exterior lighting page"),
            (41, "wait   07f324 cse_01Sample5 \"HVAC updates\" set: a reply from the controls supplier, by Mon 9:00 AM | they answer overnight"),
            (33, "raise  cse_01Sample4 high->xhigh at 10 steps (1.8s) xhigh - Design question on a full app window. | Add an event viewer to the Kit"),
            (21, "limit  hold   sid-sample-6/a10a43cb at 80%: the 5-hour limit is at 80%, until 2:40 PM (Bash)"),
            (21, "limit  wait   sid-sample-6/a10a43cb at 80%: the 5-hour limit is at 80%, until 2:40 PM, with no model calls until it ends"),
            (12, "notify Sttark Claude Kit email ok: sent to you@example.com; it arrives in about a minute | HVAC updates: the supplier replied"),
            (9, "error  cse_01Sample8 judge failed: TimeoutExpired"),
            (6, "change cse_01Sample4 xhigh->high (2.4s) high - The layout is set; now the checks. | Make the rows plain words"),
        ]
        for m in stride(from: 240.0, through: 3, by: -3) { lines.append((m, "limit  usage read failed: HTTP Error 429: Too Many Requests; next read in 2 min, using the last read")) }
        let text = lines.sorted { $0.0 > $1.0 }.map { logAt($0.0) + " " + $0.1 }.joined(separator: "\n") + "\n"
        try? text.write(to: dir.appendingPathComponent("log"), atomically: true, encoding: .utf8)
        func session(_ n: Int, _ title: String, _ level: String, ago: Double, reason: String = "", manual: Bool = false,
                     app: [String: Any] = [:], turn: Double? = nil) -> (String, [String: Any]) {
            var a: [String: Any] = ["url": "https://claude.ai/code/session_sample\(n)", "working": false, "archived": false]
            a.merge(app) { $1 }
            var x: [String: Any] = ["title": title, "level": level, "reason": reason, "manual": manual, "at": now - ago * 60,
                                    "transcript": "/sample/sid-sample-\(n).jsonl", "app": a]
            if let turn { x["turn_at"] = now - turn * 60 }
            return ("cse_01Sample\(n)", x)
        }
        func ago(_ m: Double) -> String { iso(Date().addingTimeInterval(-m * 60)) }
        let list: [(String, [String: Any])] = [
            session(1, "Order page login", "high", ago: 22, app: ["needs": true, "why": "a plan waits for your go-ahead", "last_event_at": ago(22)]),
            session(2, "Label press manual", "medium", ago: 41, app: ["unseen": true, "last_event_at": ago(41)]),
            session(3, "Exterior lighting", "low", ago: 8, app: ["unseen": true, "last_event_at": ago(8)]),
            session(4, "Sttark Claude Kit", "xhigh", ago: 0, reason: "Design question on a full app window", app: ["working": true], turn: 6),
            session(5, "HVAC updates", "medium", ago: 1, reason: "Summarizes the agents' photos",
                    app: ["checked": now, "background": ["agents": 2, "bash": 0, "what": "Photos of the B unit heads", "since": now - 9 * 60]]),
            session(6, "Press color", "high", ago: 0, manual: true, app: ["working": true], turn: 14),
            session(7, "Site map plan", "high", ago: 30, reason: "Design work across several apps"),
            session(8, "Inventory photo cleanup", "medium", ago: 50),
            session(9, "Rename report columns", "low", ago: 190, reason: "A simple rename across a few files"),
            session(10, "Laminator quote", "low", ago: 300, reason: "A simple check of the time and the mail", app: ["archived": true]),
        ]
        var sessions: [String: Any] = [:]
        for (k, v) in list { sessions[k] = v }
        let modes: [String: Any] = [
            "cse_01Sample7": ["mode": "hold", "at": 80, "sid": "sid-sample-7", "cse": "cse_01Sample7", "title": "Site map plan", "by": "typed", "set_at": now - 3600],
            "cse_01Sample8": ["mode": "hold", "at": 60, "sid": "sid-sample-8", "cse": "cse_01Sample8", "title": "Inventory photo cleanup", "by": "menu", "set_at": now - 7200],
        ]
        let fiveHour = at(16, 40)
        var daysToSat = (7 - Calendar.current.component(.weekday, from: Date())) % 7   // Saturday is 7
        if daysToSat == 0 { daysToSat = 7 }
        let weekly = at(2, 0, daysAhead: daysToSat)
        let pid = Int(getpid())   // the app drops a row whose process is gone
        let pauses: [String: Any] = [
            "sid-sample-7": ["sid": "sid-sample-7", "cse": "cse_01Sample7", "title": "Site map plan", "limit": "5-hour", "since": now - 3000,
                             "until": fiveHour.timeIntervalSince1970, "pid": pid, "what": "hold", "mode": "hold", "at": 80, "percent": 81],
            "sid-sample-7/toolu_1": ["sid": "sid-sample-7", "agent": "a1b2c3", "cse": "cse_01Sample7", "title": "Site map plan", "limit": "5-hour",
                                     "since": now - 2990, "until": fiveHour.timeIntervalSince1970, "pid": pid, "what": "hold", "mode": "hold",
                                     "at": 80, "percent": 81],
            "sid-sample-8": ["sid": "sid-sample-8", "cse": "cse_01Sample8", "title": "Inventory photo cleanup", "limit": "weekly", "since": now - 5400,
                             "until": weekly.timeIntervalSince1970, "pid": pid, "what": "hold", "mode": "hold", "at": 60, "percent": 61],
        ]
        var daysToMon = (9 - Calendar.current.component(.weekday, from: Date())) % 7   // Monday is 2
        if daysToMon == 0 { daysToMon = 7 }
        let waits: [String: Any] = [
            "a1b2c3": ["id": "a1b2c3", "kind": "email-reply", "target": "18c0sample", "from": "supplier.example",
                       "what": "Supplier's reply to the deposit email", "why": "They said 2 workdays; later misses this week's slot",
                       "by": at(9, 0, daysAhead: daysToMon).timeIntervalSince1970, "set_at": now - 5 * 3600, "cse": "cse_01Sample10",
                       "title": "Laminator quote", "session_url": "https://claude.ai/code/session_sample10"],
            "j1k2l3": ["id": "j1k2l3", "kind": "email-reply", "target": "18c1sample", "what": "Supplier's reply on the web path drawing",
                       "why": "Same supplier, the older thread", "by": at(9, 0, daysAhead: daysToMon).timeIntervalSince1970 + 3600,
                       "set_at": now - 5 * 3600, "cse": "cse_01Sample10", "title": "Laminator quote",
                       "session_url": "https://claude.ai/code/session_sample10",
                       "failing": "the Workrouter connector did not load in the check (failed): a Claude outage or its sign-in",
                       "failing_since": now - 2 * 3600, "failures": 4],
            "d4e5f6": ["id": "d4e5f6", "kind": "pr", "target": "Sttark/example#12", "want": "merged", "what": "Merge of the retry fix PR",
                       "why": "Reviews land within a day; Friday is short", "by": at(17, 0, daysAhead: 2).timeIntervalSince1970,
                       "set_at": now - 3600, "cse": "cse_01Sample11", "title": "Usage report retry",
                       "url": "https://github.com/Sttark/example/pull/12", "session_url": "https://claude.ai/code/session_sample11"],
            "g7h8i9": ["id": "g7h8i9", "kind": "check-script", "what": "12 in of new snow at the resort", "every": 7200,
                       "why": "The season's first big storm", "by": now + 40 * 86400, "set_at": now - 86400,
                       "cse": "cse_01Sample12", "title": "Powder watch", "session_url": "https://claude.ai/code/session_sample12"],
        ]
        let state: [String: Any] = [
            "paused": false, "limit_credits_all": false, "limit_modes": modes, "limit_pauses": pauses, "sessions": sessions,
            "waits": waits, "reach": ["ways": ["chat"], "email": "name@sttark.com", "chat": "https://chat.googleapis.com/v1/spaces/sample"],
            "whats_new_seen": [String](),
            "models": [["id": "claude-sonnet-5-5", "label": "Sonnet 5.5"], ["id": "claude-haiku-5-5", "label": "Haiku 5.5"]],
        ]
        let usage: [String: Any] = ["at": now - 60, "usage": [
            "extra_usage": ["is_enabled": true],
            "limits": [["kind": "session", "percent": 100, "resets_at": iso(fiveHour), "is_active": true],
                       ["kind": "weekly_all", "percent": 64, "resets_at": iso(weekly), "is_active": false]]]]
        try! JSONSerialization.data(withJSONObject: state).write(to: dir.appendingPathComponent("state.json"))
        try! JSONSerialization.data(withJSONObject: usage).write(to: dir.appendingPathComponent("usage.json"))
        // sessions that run only on this Mac, as migrate.py --scan lists them
        let local: [String: Any] = ["at": now, "sessions": [
            ["id": "5f1c2e7a-sample-local-1", "title": "Bin label sizes", "cwd": NSHomeDirectory() + "/src/labels", "where": "terminal",
             "last": now - 35 * 60, "transcript": "/sample/5f1c2e7a.jsonl", "model": "claude-opus-5-5", "pending": false],
            ["id": "9a3d4b8c-sample-local-2", "title": "Weekly plan", "cwd": NSHomeDirectory() + "/Documents/plans", "where": "desktop",
             "last": now - 3 * 3600, "transcript": "/sample/9a3d4b8c.jsonl", "model": "claude-opus-5-5", "pid": pid, "busy": false, "pending": false],
        ]]
        try! JSONSerialization.data(withJSONObject: local).write(to: dir.appendingPathComponent("local-sessions.json"))
        // archived sessions this Mac can bring back, as effort-hook.py archived() writes them; the Laminator quote
        // has a Kit wait, so the page leaves it out (it shows under Waiting on someone else)
        func archived(_ n: Int, _ title: String, _ folder: String, _ when: Date, _ doing: String) -> [String: Any] {
            ["cse": "cse_01Sample\(n)", "title": title, "folder": NSHomeDirectory() + folder, "transcript": "/sample/arch-\(n).jsonl",
             "archived_at": when.timeIntervalSince1970, "url": "https://claude.ai/code/session_01Sample\(n)", "doing": doing]
        }
        let arch: [String: Any] = ["at": now - 40, "rev": "sample", "items": [
            archived(20, "Bin label printer", "/src/labels", at(10, 5), "Sent the new label size to the printer; the test print fits the bin."),
            archived(10, "Laminator quote", "/src/purchasing", at(9, 50), "Waits for the supplier's reply."),
            archived(21, "Supplier deposit", "/src/purchasing", at(9, 20), "Drafted the reply with the new ship date; it waits in Gmail."),
            archived(22, "Door relay fix", "/src/building", at(16, 40, daysAhead: -1), "Merged the relay timing fix; the door unlocks in 2 seconds."),
            archived(23, "Press color notes", "/src/docs", at(14, 10, daysAhead: -1), "Added the new profile names to the color chapter."),
            archived(24, "Fan blade test", "/src/tile-fan", at(15, 30, daysAhead: -3), "Printed the test blade; the cap fits the motor."),
            archived(25, "Weekly plan", "/Documents/plans", at(8, 45, daysAhead: -3), ""),
        ]]
        try! JSONSerialization.data(withJSONObject: arch).write(to: dir.appendingPathComponent("archived.json"))
    }
}

/// Draws menu items the way macOS shows them: a check column, the item's own title with its fonts, colors and tab,
/// indentation, separators, a submenu arrow, and the highlighted row with its submenu open beside it.
enum Draw {
    static let rowH: CGFloat = 24, sepH: CGFloat = 11, inset: CGFloat = 5, checkW: CGFloat = 22, indentW: CGFloat = 14
    /// Draw in dark mode: the menu's own dark look, on the brand's dark paper.
    static var dark = false
    static var panelFill: NSColor { dark ? NSColor(white: 0.17, alpha: 1) : NSColor(white: 0.975, alpha: 1) }
    static var beige: NSColor { dark ? Tokens.hex(0x121417) : NSColor(red: 0.973, green: 0.961, blue: 0.949, alpha: 1) }   // brand Beige-Light, or the dark paper
    static var edge: NSColor { dark ? NSColor.white.withAlphaComponent(0.14) : NSColor.black.withAlphaComponent(0.12) }
    static var hair: NSColor { dark ? NSColor.white.withAlphaComponent(0.12) : NSColor.black.withAlphaComponent(0.1) }
    static let imageW: CGFloat = 22

    static func height(_ i: NSMenuItem) -> CGFloat {
        if i.isSeparatorItem { return sepH }
        let h = (i.attributedTitle ?? NSAttributedString(string: i.title)).size().height
        return max(h > 18 ? rowH : 20, ceil(h) + 6)
    }

    static func textWidth(_ i: NSMenuItem) -> CGFloat {
        guard let t = i.attributedTitle else { return 0 }
        let tabbed = t.string.contains("\t")
        return (tabbed ? Controller.tab : ceil(t.size().width)) + CGFloat(i.indentationLevel) * indentW + (i.image != nil ? imageW : 0)
    }

    static func panelSize(_ items: [NSMenuItem]) -> NSSize {
        let w = inset * 2 + 6 + checkW + (items.map(textWidth).max() ?? 200)
            + (items.contains { $0.badge != nil } ? 70 : items.contains { $0.submenu != nil || !$0.keyEquivalent.isEmpty } ? 30 : 14)
        return NSSize(width: max(w, 200), height: items.map(height).reduce(10, +))
    }

    /// The panel at `origin` (top left); returns each item's row rectangle.
    @discardableResult
    static func panel(_ items: [NSMenuItem], _ origin: NSPoint, hot: Int?) -> [NSRect] {
        let size = panelSize(items)
        let r = NSRect(origin: origin, size: size)
        NSGraphicsContext.saveGraphicsState()
        let sh = NSShadow()
        sh.shadowColor = NSColor.black.withAlphaComponent(0.18)
        sh.shadowBlurRadius = 14
        sh.shadowOffset = NSSize(width: 0, height: -6)
        sh.set()
        panelFill.setFill()
        NSBezierPath(roundedRect: r, xRadius: 10, yRadius: 10).fill()
        NSGraphicsContext.restoreGraphicsState()
        edge.setStroke()
        NSBezierPath(roundedRect: r.insetBy(dx: 0.5, dy: 0.5), xRadius: 10, yRadius: 10).stroke()

        var y = origin.y + 5
        var rects: [NSRect] = []
        for (n, i) in items.enumerated() {
            let h = height(i)
            let row = NSRect(x: r.minX + inset, y: y, width: r.width - 2 * inset, height: h)
            rects.append(row)
            if i.isSeparatorItem {
                hair.setFill()
                NSRect(x: r.minX + 14, y: y + 5, width: r.width - 28, height: 1).fill()
            } else {
                let isHot = n == hot
                if isHot {
                    NSColor.controlAccentColor.setFill()
                    NSBezierPath(roundedRect: row, xRadius: 5, yRadius: 5).fill()
                }
                let ink: NSColor = isHot ? .white : .labelColor
                if i.state == .on {
                    let check = NSAttributedString(string: "✓", attributes: [.font: NSFont.systemFont(ofSize: 13, weight: .semibold),
                                                                             .foregroundColor: ink])
                    check.draw(at: NSPoint(x: row.minX + 6 + (checkW - check.size().width) / 2, y: y + (h - check.size().height) / 2))
                }
                let t = NSMutableAttributedString(attributedString: i.attributedTitle ?? NSAttributedString(string: i.title))
                if isHot {
                    t.enumerateAttribute(.foregroundColor, in: NSRange(location: 0, length: t.length)) { v, range, _ in
                        let secondary = (v as? NSColor) == NSColor.secondaryLabelColor
                        t.addAttribute(.foregroundColor, value: NSColor.white.withAlphaComponent(secondary ? 0.85 : 1), range: range)
                    }
                }
                let th = t.size().height
                var x = row.minX + 6 + checkW + CGFloat(i.indentationLevel) * indentW
                if let img = i.image {   // the item's image, before its title, as macOS draws it: a template one in the text's color
                    let drawn = img.isTemplate ? NSImage(size: img.size, flipped: false) { rect in
                        img.draw(in: rect)
                        ink.set()
                        rect.fill(using: .sourceAtop)
                        return true
                    } : img
                    drawn.draw(in: NSRect(x: x, y: y + (h - img.size.height) / 2, width: img.size.width, height: img.size.height),
                               from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
                    x += imageW
                }
                t.draw(with: NSRect(x: x, y: y + (h - th) / 2, width: textWidth(i) + 4, height: th + 2),
                       options: [.usesLineFragmentOrigin])
                if i.submenu != nil {
                    let arrow = NSAttributedString(string: "›", attributes: [.font: NSFont.systemFont(ofSize: 17, weight: .medium),
                        .foregroundColor: isHot ? NSColor.white : NSColor.secondaryLabelColor])
                    arrow.draw(at: NSPoint(x: row.maxX - 8 - arrow.size().width, y: y + (h - arrow.size().height) / 2 - 1))
                }
                if let b = i.badge {   // the menu item's badge ("3 new"), drawn the way macOS draws it
                    let bt = NSAttributedString(string: b.stringValue ?? "", attributes: [.font: NSFont.systemFont(ofSize: 12, weight: .semibold),
                        .foregroundColor: NSColor.secondaryLabelColor])
                    let bw = bt.size().width + 16, bh: CGFloat = 19
                    let br = NSRect(x: row.maxX - 8 - bw, y: y + (h - bh) / 2, width: bw, height: bh)
                    hair.setFill()
                    NSBezierPath(roundedRect: br, xRadius: bh / 2, yRadius: bh / 2).fill()
                    bt.draw(at: NSPoint(x: br.minX + 8, y: br.minY + (bh - bt.size().height) / 2))
                }
                if !i.keyEquivalent.isEmpty {
                    let k = NSAttributedString(string: "⌘" + i.keyEquivalent.uppercased(), attributes: [.font: NSFont.systemFont(ofSize: 14),
                        .foregroundColor: NSColor.secondaryLabelColor])
                    k.draw(at: NSPoint(x: row.maxX - 8 - k.size().width, y: y + (h - k.size().height) / 2))
                }
            }
            y += h
        }
        return rects
    }

    static func png(_ items: [NSMenuItem], hot: Int?, menuBar: Bool, to path: String) {
        let main = panelSize(items)
        let top: CGFloat = menuBar ? 34 : 16
        let sub = hot.flatMap { items[$0].submenu?.items } ?? []
        let subSize = sub.isEmpty ? NSSize.zero : panelSize(sub)
        // the submenu's first row lines up with the highlighted row, as macOS places it
        var hotY: CGFloat = top + 5
        if let hot { hotY += items.prefix(hot).map(height).reduce(0, +) }
        let subOrigin = NSPoint(x: 16 + main.width - 4, y: hotY - 5)
        let w = sub.isEmpty ? 16 + main.width + 16 : subOrigin.x + subSize.width + 24
        let h = max(top + main.height, subOrigin.y + subSize.height) + 28

        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(w * 2), pixelsHigh: Int(h * 2), bitsPerSample: 8,
                                   samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                   bytesPerRow: 0, bitsPerPixel: 0)!
        rep.size = NSSize(width: w, height: h)
        let base = NSGraphicsContext(bitmapImageRep: rep)!
        base.cgContext.translateBy(x: 0, y: h)
        base.cgContext.scaleBy(x: 1, y: -1)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: base.cgContext, flipped: true)
        NSAppearance(named: dark ? .darkAqua : .aqua)!.performAsCurrentDrawingAppearance {
            beige.setFill()
            NSRect(x: 0, y: 0, width: w, height: h).fill()
            if menuBar {   // the menu bar, with the gauge as the app draws it
                NSColor(white: dark ? 0.12 : 0.93, alpha: 1).setFill()
                NSRect(x: 0, y: 0, width: w, height: 30).fill()
                hair.setFill()
                NSBezierPath(roundedRect: NSRect(x: 24, y: 4, width: 34, height: 22), xRadius: 5, yRadius: 5).fill()
                let g = GaugeIcon.image("xhigh")
                let tinted = NSImage(size: g.size, flipped: false) { rect in
                    g.draw(in: rect)
                    (dark ? NSColor.white : NSColor.black).set()
                    rect.fill(using: .sourceAtop)
                    return true
                }
                tinted.draw(in: NSRect(x: 30, y: 7.5, width: g.size.width, height: g.size.height), from: .zero, operation: .sourceOver,
                            fraction: 1, respectFlipped: true, hints: nil)
            }
            panel(items, NSPoint(x: 16, y: top), hot: hot)
            if !sub.isEmpty { panel(sub, subOrigin, hot: nil) }
        }
        NSGraphicsContext.restoreGraphicsState()
        try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: path))
        print("wrote \(path) (\(Int(w))×\(Int(h)) pt)")
    }
}

/// The tool's windows. AppKit draws a control in its accent color (an on switch, a checked box) only in the key window
/// of the active app, and gray in any other window, where an on switch reads as off. The tool never activates the app,
/// since nothing may come to the front, so while `key` is set its window says it has the key window's look (AppKit's own
/// `hasKeyAppearance`, which the controls ask when they draw) and they draw as the person sees them in use.
final class ShotWindow: NSWindow {
    static var key = false
    @objc(hasKeyAppearance) func keyLook() -> Bool { ShotWindow.key }
}
