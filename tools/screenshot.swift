// Draws the README's pictures with the app's own code, from made-up sessions in a temporary folder. Nothing from
// this Mac's own state:
//   docs/menu.png             the menu: what needs you, one row for each other group, one group's submenu open
//   docs/window-sessions.png  the window's Sessions page, a session that waits on someone else selected, each row with
//                             its alerts bell (two sessions have their alerts off)
//   docs/window-archived.png  the window's Archived page, by day, the newest selected with Bring it back
//   docs/window-archived-search.png  the Archived page's search, which finds an archived session that waits
//   docs/window-usage.png     the window's Usage page, 7 days, the biggest session selected with its days and models
//   docs/window-settings.png  the window's Settings page
//   docs/settings-phone.png   the Settings page's Phone box in each of its states (Kit on your phone)
//   docs/window-news.png      the window's What's new page
//   docs/window-events.png    the window's Events page, newest first, from sample log lines
//   docs/whats-new.png        the What's new sheet over the window, with this repo's newest notes (at most 4)
// and the pictures of a few What's new notes in whats-new/ (each crop is named where it is made below).
// Each is light. STTARK_SHOT_DARK=<folder> also draws the window and the sheet in dark mode into that folder.
// The window and the sheet are real windows, kept off every screen and drawn by their own views, so they look as
// they do on this Mac; nothing shows on the screen and nothing comes to the front (see ShotWindow).
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
        ShotWindow.watch()
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
        // the What's new note's picture: the Phone box at the new address with no phone that gets notices yet, as a
        // linked Mac shows it after the move until the person turns notices on again
        for look in [false, true] {
            Shot.phoneBox(Sample.phone[3].1, dark: look, to: "whats-new/kit-new-address" + (look ? "-dark" : "") + ".png")
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
            // a search for an archived session that waits: it is under Waiting on someone else, not in the list
            model.archivedSearch = "core"
            model.reload()
            Shot.capture(w, to: folder + "/window-archived-search.png")
            model.archivedSearch = ""
            model.page = .usage
            model.usageData = SessionUsage.read()
            model.setUsagePeriod(.week)
            model.usageSelected = model.usageReport.lines.first?.id
            let usage = "/tmp/kit-shot-\(getpid())-usage.png"
            Shot.capture(w, to: usage)
            try? FileManager.default.removeItem(atPath: folder + "/window-usage.png")
            try? FileManager.default.copyItem(atPath: usage, toPath: folder + "/window-usage.png")
            print("wrote \(folder)/window-usage.png")
            // the usage note's picture: the period, the legend and the biggest sessions, at the note's size
            let r = model.usageReport
            let uw = ShotWindow(contentRect: NSRect(x: ShotWindow.away, y: 0, width: 440, height: 280), styleMask: [.borderless], backing: .buffered, defer: false)
            uw.appearance = w.appearance
            uw.isReleasedWhenClosed = false
            uw.contentView = NSHostingView(rootView: VStack(alignment: .leading, spacing: 0) {
                Segments(options: [("today", "Today"), ("7d", "7 days"), ("30d", "30 days"), ("custom", "Custom")], value: "7d") { _ in }
                    .padding(.bottom, 12)
                UsageLegend().padding(.horizontal, 10).padding(.bottom, 4)
                ForEach(Array(r.lines.prefix(3).enumerated()), id: \.element.id) { i, l in
                    if i > 1 { Hairline().padding(.horizontal, 10) } else if i > 0 { Color.clear.frame(height: 1) }
                    UsageRow(line: l, share: r.share(l.usd), top: r.lines.first?.usd ?? 1, selected: i == 0, multiDay: true)
                }
                Spacer(minLength: 0)
            }.padding(14).frame(width: 440, height: 280).background(K.card).font(K.font(13)).foregroundColor(K.ink))
            uw.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
            Shot.capture(uw, to: "whats-new/usage-by-session" + (look ? "-dark" : "") + ".png")
            uw.close()
            // the human work note's picture: the totals with the human work line and its ⓘ note open, and the biggest rows
            model.openNotes = ["usage-human"]
            let hw = ShotWindow(contentRect: NSRect(x: ShotWindow.away, y: 0, width: 440, height: 280), styleMask: [.borderless], backing: .buffered, defer: false)
            hw.appearance = w.appearance
            hw.isReleasedWhenClosed = false
            hw.contentView = NSHostingView(rootView: VStack(alignment: .leading, spacing: 0) {
                UsagePage(model: model).human(r).padding(.horizontal, 10).padding(.bottom, 8)
                ForEach(Array(r.lines.prefix(2).enumerated()), id: \.element.id) { i, l in
                    if i > 0 { Hairline().padding(.horizontal, 10) }
                    UsageRow(line: l, share: r.share(l.usd), top: r.lines.first?.usd ?? 1, selected: false, multiDay: true)
                }
                Spacer(minLength: 0)
            }.padding(14).frame(width: 440, height: 280, alignment: .top).background(K.card).font(K.font(13)).foregroundColor(K.ink))
            hw.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
            Shot.capture(hw, to: "whats-new/human-work" + (look ? "-dark" : "") + ".png")
            hw.close()
            model.openNotes = []
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
            let rows = ShotWindow(contentRect: NSRect(x: ShotWindow.away, y: 0, width: 440, height: 280), styleMask: [.borderless], backing: .buffered, defer: false)
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
            rows.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
            Shot.capture(rows, to: "whats-new/events-page" + (look ? "-dark" : "") + ".png")
            rows.close()
            model.openEvent = nil
            // the subagent-effort note's picture: the agent rows alone
            let agents = model.events.filter { $0.text.hasPrefix("Agent \u{201C}") || $0.text.contains(" so fork ") }
            let ar = ShotWindow(contentRect: NSRect(x: ShotWindow.away, y: 0, width: 440, height: 280), styleMask: [.borderless], backing: .buffered, defer: false)
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
            ar.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
            Shot.capture(ar, to: "whats-new/subagent-effort" + (look ? "-dark" : "") + ".png")
            ar.close()
            model.openEvent = nil
            // the kit-window note's picture: the top of the session list, at the window's narrowest
            model.page = .sessions
            let f = w.frame
            w.setContentSize(NSSize(width: 960, height: 760))
            w.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
            let full = "/tmp/kit-shot-\(getpid())-narrow.png"
            Shot.capture(w, to: full)
            Shot.crop(full, NSRect(x: 226, y: 60, width: 392, height: 280),
                      to: "whats-new/kit-window" + (look ? "-dark" : "") + ".png")
            // the sessions-at-once note's picture: the page's heading and its first groups
            Shot.crop(full, NSRect(x: 226, y: 0, width: 390, height: 280),
                      to: "whats-new/sessions-at-once" + (look ? "-dark" : "") + ".png")
            w.setFrame(f, display: true)
            ShotWindow.check("the window's size again")
            // the What's new sheet, as the menu's What's new item opens it, over the window: the newest notes, at most 4
            // as WhatsNew.forSheet gives them, so the sheet fits the window with its title and buttons
            model.page = .sessions
            model.sheet = Array(WhatsNew.all.prefix(4))
            w.orderFrontRegardless()
            ShotWindow.check("the sheet")
            RunLoop.main.run(until: Date().addingTimeInterval(1.5))
            ShotWindow.check("the sheet")
            Shot.capture(w, to: folder + "/whats-new.png", wait: 0.2)
            model.sheet = []
            RunLoop.main.run(until: Date().addingTimeInterval(1))
            // the one-setting note's picture: a held session, pointed at its own setting
            let before = model.selected
            model.selected = model.snap.rows.first { $0.title == "Shift schedule" }?.id
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
            // the check-ins note's picture: the Claude working group at the window's narrowest, the blade change's row with its
            // latest check-in
            model.selected = model.snap.rows.first { $0.checkin != nil }?.id
            let wide = w.frame
            w.setContentSize(NSSize(width: 960, height: 760))
            w.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
            let ck = "/tmp/kit-shot-\(getpid())-checkin.png"
            Shot.capture(w, to: ck)
            if ProcessInfo.processInfo.environment["STTARK_SHOT_KEEP"] != nil {
                try? FileManager.default.removeItem(atPath: folder + "/window-checkin-full.png")
                try? FileManager.default.copyItem(atPath: ck, toPath: folder + "/window-checkin-full.png")
            }
            Shot.crop(ck, NSRect(x: 226, y: 146, width: 392, height: 176),
                      to: "whats-new/check-ins-in-the-kit" + (look ? "-dark" : "") + ".png")
            w.setFrame(wide, display: true)
            ShotWindow.check("the window's size again")
            // the session alerts note's picture: a group's rows, each with its bell, the one with its alerts off
            // selected, and that session's Alerts switch from its panel
            let waitRows = model.snap.rows(.waits)
            if let off = waitRows.first(where: { model.snap.alerts($0) == false }) {
                let aw = ShotWindow(contentRect: NSRect(x: ShotWindow.away, y: 0, width: 440, height: 252), styleMask: [.borderless], backing: .buffered, defer: false)
                aw.appearance = w.appearance
                aw.isReleasedWhenClosed = false
                aw.contentView = NSHostingView(rootView: VStack(alignment: .leading, spacing: 0) {
                    GroupHeader(group: .waits, count: waitRows.count)
                    ForEach(Array(waitRows.enumerated()), id: \.element.id) { i, r in
                        if i > 0 && r.id != off.id && waitRows[i - 1].id != off.id { Hairline().padding(.horizontal, 10) }
                        else if i > 0 { Color.clear.frame(height: 1) }
                        RowView(row: r, selected: r.id == off.id, alerts: model.snap.alerts(r), reach: model.snap.reach)
                    }
                    DetailView(model: model, row: off).alerts(false).padding(.horizontal, 10)
                    Spacer(minLength: 0)
                }.padding(.horizontal, 14).frame(width: 440, height: 252, alignment: .top).background(K.card).font(K.font(13)).foregroundColor(K.ink))
                aw.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
                Shot.capture(aw, to: "whats-new/session-alerts" + (look ? "-dark" : "") + ".png")
                aw.close()
            }
            model.selected = before
            // Reach me by's alerts off: the Settings box (the alerts-off note's picture), and a session's message kept in
            // the Kit on the Sessions page and the Events page. The log and the state go back as they were after.
            let log = (try? String(contentsOf: dir.appendingPathComponent("log"), encoding: .utf8)) ?? ""
            Sample.keep(dir)
            Reach.setAlerts(false)
            var off = facts
            off.reach.alerts = false
            model.fixedFacts = off
            model.reloadFacts()
            ShotWindow.key = true
            model.page = .settings
            Shot.redraw(w)
            let alerts = "/tmp/kit-shot-\(getpid())-alerts-settings\(look ? "-dark" : "").png"
            Shot.capture(w, to: alerts)
            ShotWindow.key = false
            Shot.crop(alerts, NSRect(x: 245, y: 356, width: 440, height: 280),
                      to: "whats-new/alerts-off" + (look ? "-dark" : "") + ".png")
            model.page = .sessions
            model.reload()
            model.selected = model.snap.rows.first { !$0.kept.isEmpty }?.id
            Shot.capture(w, to: "/tmp/kit-shot-\(getpid())-alerts-session\(look ? "-dark" : "").png")
            model.page = .events
            model.readEvents()
            RunLoop.main.run(until: Date().addingTimeInterval(1))
            model.openEvent = model.events.first { $0.text.hasPrefix("Message kept") }?.id
            RunLoop.main.run(until: Date().addingTimeInterval(0.3))
            Shot.capture(w, to: "/tmp/kit-shot-\(getpid())-alerts-events\(look ? "-dark" : "").png")
            model.openEvent = nil
            Reach.setAlerts(true)
            try? FileManager.default.removeItem(at: Kept.file)
            try? log.write(to: dir.appendingPathComponent("log"), atomically: true, encoding: .utf8)
            model.fixedFacts = facts
            model.reloadFacts()
            model.page = .sessions
            model.selected = before
            model.reload()
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
        shoot(view, dark: dark, to: path)
    }

    /// One state of the Phone box, alone, 440 points wide: a What's new note's picture.
    static func phoneBox(_ s: PhoneLink.Status, dark: Bool, to path: String) {
        let view = Box { PhoneRow(status: s, link: {}, toggle: {}) }
            .padding(16).frame(width: 440).background(K.card).font(K.font(13)).foregroundColor(K.ink)
        shoot(view, dark: dark, to: path)
    }

    /// A view in a window of its own, off the screen, captured at its fitting size; switches as they really are.
    static func shoot<V: View>(_ view: V, dark: Bool, to path: String) {
        let host = NSHostingView(rootView: view)
        let size = host.fittingSize
        let w = ShotWindow(contentRect: NSRect(x: ShotWindow.away, y: 0, width: size.width, height: size.height), styleMask: [.borderless], backing: .buffered, defer: false)
        w.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        w.isReleasedWhenClosed = false
        w.contentView = host
        w.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
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
        let w = ShotWindow(contentRect: NSRect(x: ShotWindow.away, y: 0, width: 1180, height: 760),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        w.titleVisibility = .hidden
        w.titlebarAppearsTransparent = true
        w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: KitRoot(model: model))
        w.setFrameOrigin(NSPoint(x: ShotWindow.away, y: 0))
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

    /// Shows the window off the screen, lets it draw, and draws it and its sheet into a 2x PNG in this process. The
    /// window server draws no window that is off every screen, so screencapture and ScreenCaptureKit can't capture it.
    static func capture(_ w: NSWindow, to path: String, wait: TimeInterval = 1.2) {
        ShotWindow.check(path + ", before")
        if w.sheetParent == nil { w.orderFrontRegardless() }
        ShotWindow.check(path)
        RunLoop.main.run(until: Date().addingTimeInterval(wait))
        ShotWindow.check(path)
        render(w, to: path)
        print("wrote \(path)")
    }

    /// One window's whole frame (its title bar's buttons too) drawn at 2x.
    static func image(_ w: NSWindow) -> CGImage? {
        guard let v = w.contentView?.superview ?? w.contentView else { return nil }
        let size = v.bounds.size
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                                   bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                   bytesPerRow: 0, bitsPerPixel: 0)!
        rep.size = size
        v.cacheDisplay(in: v.bounds, to: rep)
        return rep.cgImage
    }

    /// The window and its sheet, with the window server's round corners.
    static func render(_ w: NSWindow, to path: String) {
        guard let base = image(w) else { return }
        let size = w.frame.size, s: CGFloat = 2
        let ctx = CGContext(data: nil, width: base.width, height: base.height, bitsPerComponent: 8, bytesPerRow: 0,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        ctx.scaleBy(x: s, y: s)
        // the corners as the window server draws them: a window's and a sheet's
        func corners(_ r: CGRect, _ radius: CGFloat) {
            ctx.addPath(RoundedRectangle(cornerRadius: radius, style: .continuous).path(in: r).cgPath)
            ctx.clip()
        }
        ctx.saveGState()
        if w.styleMask.contains(.titled) { corners(CGRect(origin: .zero, size: size), 16) }
        ctx.draw(base, in: CGRect(origin: .zero, size: size))
        if let sheet = w.attachedSheet, let img = image(sheet) {
            let r = sheet.frame.offsetBy(dx: -w.frame.minX, dy: -w.frame.minY)
            corners(r, 26)
            ctx.draw(img, in: r)
        }
        ctx.restoreGState()
        let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
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

    /// Two messages kept in the Kit for an idle session while alerts are off (notify.py keep_in_kit()), and the log
    /// line of the newest, for the Events page.
    static func keep(_ dir: URL) {
        let now = Date().timeIntervalSince1970
        func item(_ id: String, ago: Double, _ subject: String, _ body: String, link: String = "") -> [String: Any] {
            ["id": id, "at": now - ago * 60, "cse": "cse_01Sample9", "title": "Rename report columns", "subject": subject, "body": body,
             "link": link, "url": "https://claude.ai/code/session_sample9", "from": "session", "why": "alerts are off"]
        }
        let items = [item("b1c2d3e4f5a6", ago: 95, "PR #42 waits for a review", "The new column names are in PR #42. CI passes. It waits for a review; I watch it and come back when it merges."),
                     item("a1b2c3d4e5f6", ago: 12, "PR #42 merged",
                          "The report columns have their new names. PR #42 merged and the deploy is done.\n\nNothing needed from you.",
                          link: "https://github.com/Sttark/sample/pull/42")]
        try? JSONSerialization.data(withJSONObject: ["items": items]).write(to: Kept.file)
        let lf = DateFormatter(); lf.dateFormat = "yyyy-MM-dd HH:mm:ss"
        let line = lf.string(from: Date().addingTimeInterval(-12 * 60)) + " notify Rename report columns kept a1b2c3d4e5f6: alerts are off | PR #42 merged\n"
        if let h = try? FileHandle(forWritingTo: dir.appendingPathComponent("log")) { h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close() }
    }

    static func write(_ dir: URL) {
        let now = Date().timeIntervalSince1970
        // The Log page's sample lines, oldest first as the hooks write them.
        let lf = DateFormatter(); lf.dateFormat = "yyyy-MM-dd HH:mm:ss"
        func logAt(_ m: Double) -> String { lf.string(from: Date().addingTimeInterval(-m * 60)) }
        var lines: [(Double, String)] = [
            (1500, "app    update: installed 1.160, restarting"),
            (1450, "wake   cse_01Sample7 \"Shift schedule\" stopped, not archived; sent high to start it"),
            (300, "change cse_01Sample9 ->low (1.9s) low - A simple rename across a few files | Rename the report columns to match the new names"),
            (190, "name   sid-sample-9 -> \"Rename report columns\" (2.0s) | Rename the report columns to match the new names"),
            (62, "agent  cse_01Sample4 Explore ->low (1.9s) low - A short file search. | Find the job board code"),
            (61, "agent  cse_01Sample4 general-purpose ->xhigh (2.2s) xhigh - A new page design with judgment calls. | Design the job rows"),
            (60, "agent  cse_01Sample4 fork low->high (2.0s) high - Code changes across a few files. | Build the press filters"),
            (52, "change cse_01Sample3 medium->low (2.1s) low - Routine edit with a clear plan. | Fix the typo in the dock door work order"),
            (41, "wait   07f324 cse_01Sample5 \"Slitter blade change\" set: a reply from the blade supplier, by Mon 9:00 AM | they answer overnight"),
            (33, "raise  cse_01Sample4 high->xhigh at 10 steps (1.8s) xhigh - Design question on a new job board. | Add a job board for Press 2"),
            (21, "limit  hold   sid-sample-6/a10a43cb at 80%: the 5-hour limit is at 80%, until 2:40 PM (Bash)"),
            (21, "limit  wait   sid-sample-6/a10a43cb at 80%: the 5-hour limit is at 80%, until 2:40 PM, with no model calls until it ends"),
            (16, "checkin cse_01Sample5 \"Slitter blade change\" shown in the Kit | Photos of the slitter blades and 1 more agent, working 15 min | It read the photos of blades 1 to 6 and found two dull blades. Next it reads blades 7 to 12."),
            (1, "checkin cse_01Sample5 \"Slitter blade change\" shown in the Kit | Photos of the slitter blades and 1 more agent, working 30 min | It read the photos of blades 7 to 12 and marked three blades to change. Next it writes the list for the technician."),
            (12, "notify Sttark Claude Kit email ok: sent to you@example.com; it arrives in about a minute | Slitter blade change: the supplier replied"),
            (9, "error  cse_01Sample8 judge failed: TimeoutExpired"),
            (6, "change cse_01Sample4 xhigh->high (2.4s) high - The layout is set; now the checks. | Show due dates on the rows"),
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
            session(2, "Rewinder PM checklist", "medium", ago: 41, app: ["unseen": true, "last_event_at": ago(41)]),
            session(3, "Dock door repair", "low", ago: 8, app: ["unseen": true, "last_event_at": ago(8)]),
            session(4, "Press 2 job board", "xhigh", ago: 0, reason: "Design question on a new job board", app: ["working": true], turn: 6),
            session(5, "Slitter blade change", "medium", ago: 1, reason: "Summarizes the agents' photos",
                    app: ["checked": now, "background": ["agents": 2, "bash": 0, "what": "Photos of the slitter blades", "since": now - 31 * 60]]),
            session(6, "Ink reorder", "high", ago: 0, manual: true, app: ["working": true], turn: 14),
            session(7, "Shift schedule", "high", ago: 30, reason: "Design work across several pages"),
            session(8, "Spare parts count", "medium", ago: 50),
            session(9, "Rename report columns", "low", ago: 190, reason: "A simple rename across a few files"),
            session(10, "Core supplier quote", "low", ago: 300, reason: "A simple check of the time and the mail", app: ["archived": true]),
        ]
        var sessions: [String: Any] = [:]
        for (k, v) in list { sessions[k] = v }
        let modes: [String: Any] = [
            "cse_01Sample7": ["mode": "hold", "at": 80, "sid": "sid-sample-7", "cse": "cse_01Sample7", "title": "Shift schedule", "by": "typed", "set_at": now - 3600],
            "cse_01Sample8": ["mode": "hold", "at": 60, "sid": "sid-sample-8", "cse": "cse_01Sample8", "title": "Spare parts count", "by": "menu", "set_at": now - 7200],
        ]
        let fiveHour = at(16, 40)
        var daysToSat = (7 - Calendar.current.component(.weekday, from: Date())) % 7   // Saturday is 7
        if daysToSat == 0 { daysToSat = 7 }
        let weekly = at(2, 0, daysAhead: daysToSat)
        let pid = Int(getpid())   // the app drops a row whose process is gone
        let pauses: [String: Any] = [
            "sid-sample-7": ["sid": "sid-sample-7", "cse": "cse_01Sample7", "title": "Shift schedule", "limit": "5-hour", "since": now - 3000,
                             "until": fiveHour.timeIntervalSince1970, "pid": pid, "what": "hold", "mode": "hold", "at": 80, "percent": 81],
            "sid-sample-7/toolu_1": ["sid": "sid-sample-7", "agent": "a1b2c3", "cse": "cse_01Sample7", "title": "Shift schedule", "limit": "5-hour",
                                     "since": now - 2990, "until": fiveHour.timeIntervalSince1970, "pid": pid, "what": "hold", "mode": "hold",
                                     "at": 80, "percent": 81],
            "sid-sample-8": ["sid": "sid-sample-8", "cse": "cse_01Sample8", "title": "Spare parts count", "limit": "weekly", "since": now - 5400,
                             "until": weekly.timeIntervalSince1970, "pid": pid, "what": "hold", "mode": "hold", "at": 60, "percent": 61],
        ]
        var daysToMon = (9 - Calendar.current.component(.weekday, from: Date())) % 7   // Monday is 2
        if daysToMon == 0 { daysToMon = 7 }
        let waits: [String: Any] = [
            "a1b2c3": ["id": "a1b2c3", "kind": "email-reply", "target": "18c0sample", "from": "supplier.example",
                       "what": "Supplier's reply to the deposit email", "why": "They said 2 workdays; later misses this week's slot",
                       "by": at(9, 0, daysAhead: daysToMon).timeIntervalSince1970, "set_at": now - 5 * 3600, "cse": "cse_01Sample10",
                       "title": "Core supplier quote", "session_url": "https://claude.ai/code/session_sample10",
                       "cwd": NSHomeDirectory() + "/src/purchasing"],
            "j1k2l3": ["id": "j1k2l3", "kind": "email-reply", "target": "18c1sample", "what": "Supplier's reply on the core size drawing",
                       "why": "Same supplier, the older thread", "by": at(9, 0, daysAhead: daysToMon).timeIntervalSince1970 + 3600,
                       "set_at": now - 5 * 3600, "cse": "cse_01Sample10", "title": "Core supplier quote",
                       "session_url": "https://claude.ai/code/session_sample10",
                       "failing": "the Workrouter connector did not load in the check (failed): a Claude outage or its sign-in",
                       "failing_since": now - 2 * 3600, "failures": 4],
            "d4e5f6": ["id": "d4e5f6", "kind": "pr", "target": "Sttark/example#12", "want": "merged", "what": "Merge of the report fix PR",
                       "why": "Reviews land within a day; Friday is short", "by": at(17, 0, daysAhead: 2).timeIntervalSince1970,
                       "set_at": now - 3600, "cse": "cse_01Sample11", "title": "Scrap report fix",
                       "url": "https://github.com/Sttark/example/pull/12", "session_url": "https://claude.ai/code/session_sample11"],
            "g7h8i9": ["id": "g7h8i9", "kind": "check-script", "what": "Film price under the last quote", "every": 7200,
                       "why": "The supplier sets new prices each month", "by": now + 40 * 86400, "set_at": now - 86400,
                       "cse": "cse_01Sample12", "title": "Film price watch", "session_url": "https://claude.ai/code/session_sample12"],
        ]
        // two sessions whose alerts the person turned off: the long film price watch, and an idle rename
        let alertsOff: [String: Any] = [
            "cse_01Sample12": ["at": now - 2 * 86400, "by": "window", "title": "Film price watch"],
            "cse_01Sample9": ["at": now - 3 * 3600, "by": "phone", "title": "Rename report columns"],
        ]
        let state: [String: Any] = [
            "paused": false, "limit_credits_all": false, "limit_modes": modes, "limit_pauses": pauses, "sessions": sessions,
            "alerts_off": alertsOff,
            "waits": waits, "reach": ["ways": ["chat"], "email": "name@sttark.com", "chat": "https://chat.googleapis.com/v1/spaces/sample"],
            "whats_new_seen": [String](),
            "models": [["id": "claude-sonnet-5-5", "label": "Sonnet 5.5"], ["id": "claude-haiku-5-5", "label": "Haiku 5.5"]],
        ]
        let usage: [String: Any] = ["at": now - 60, "usage": [
            "extra_usage": ["is_enabled": true],
            "limits": [["kind": "session", "percent": 100, "resets_at": iso(fiveHour), "is_active": true],
                       ["kind": "weekly_all", "percent": 64, "resets_at": iso(weekly), "is_active": false]]]]
        try! JSONSerialization.data(withJSONObject: state).write(to: dir.appendingPathComponent("state.json"))
        // the progress check-ins (checkin.py): the latest note of the blade change's work, which runs 31 min
        let checkins: [String: Any] = ["sessions": [
            "cse_01Sample5": ["start": now - 31 * 60, "seen": now - 20, "sent": now - 60, "n": 2, "note_at": now - 60,
                              "subject": "Photos of the slitter blades and 1 more agent, working 30 min",
                              "note": "It read the photos of blades 7 to 12 and marked three blades to change. Next it writes the list for the technician."],
        ]]
        try! JSONSerialization.data(withJSONObject: checkins).write(to: dir.appendingPathComponent("checkins.json"))
        try! JSONSerialization.data(withJSONObject: usage).write(to: dir.appendingPathComponent("usage.json"))
        // sessions that run only on this Mac, as migrate.py --scan lists them
        let local: [String: Any] = ["at": now, "sessions": [
            ["id": "5f1c2e7a-sample-local-1", "title": "Box label sizes", "cwd": NSHomeDirectory() + "/src/shipping", "where": "terminal",
             "last": now - 35 * 60, "transcript": "/sample/5f1c2e7a.jsonl", "model": "claude-opus-5-5", "pending": false],
            ["id": "9a3d4b8c-sample-local-2", "title": "Weekly plan", "cwd": NSHomeDirectory() + "/Documents/plans", "where": "desktop",
             "last": now - 3 * 3600, "transcript": "/sample/9a3d4b8c.jsonl", "model": "claude-opus-5-5", "pid": pid, "busy": false, "pending": false],
        ]]
        try! JSONSerialization.data(withJSONObject: local).write(to: dir.appendingPathComponent("local-sessions.json"))
        // archived sessions this Mac can bring back, as effort-hook.py archived() writes them; the Core supplier quote
        // has a Kit wait, so the page leaves it out (it shows under Waiting on someone else)
        func archived(_ n: Int, _ title: String, _ folder: String, _ when: Date, _ doing: String) -> [String: Any] {
            ["cse": "cse_01Sample\(n)", "title": title, "folder": NSHomeDirectory() + folder, "transcript": "/sample/arch-\(n).jsonl",
             "archived_at": when.timeIntervalSince1970, "url": "https://claude.ai/code/session_01Sample\(n)", "doing": doing]
        }
        let arch: [String: Any] = ["at": now - 40, "rev": "sample", "items": [
            archived(20, "Shipping label printer", "/src/shipping", at(10, 5), "Sent the new label size to the printer; the test print fits the box."),
            archived(10, "Core supplier quote", "/src/purchasing", at(9, 50), "Waits for the supplier's reply."),
            archived(21, "Supplier deposit", "/src/purchasing", at(9, 20), "Drafted the reply with the new ship date; it waits in Gmail."),
            archived(22, "Dryer belt change", "/src/maintenance", at(16, 40, daysAhead: -1), "Logged the new belt; the dryer runs at full speed again."),
            archived(23, "Press setup notes", "/src/docs", at(14, 10, daysAhead: -1), "Added the new plate sizes to the setup chapter."),
            archived(24, "Guard bracket print", "/src/fixtures", at(15, 30, daysAhead: -3), "Printed the test bracket; the guard fits the frame."),
            archived(25, "Weekly plan", "/Documents/plans", at(8, 45, daysAhead: -3), ""),
        ]]
        try! JSONSerialization.data(withJSONObject: arch).write(to: dir.appendingPathComponent("archived.json"))
        // Usage by session: what usage-scan.py writes, for made-up sessions over the last 30 days
        let days = (0..<30).map { SessionUsage.day(Date(), plus: $0 - 29) }
        // name, kind, Remote Control id, minutes since last active, its use a day in dollars, its agents' part, agents a day
        let made: [(String, String, String?, Double, Double, Double, Int)] = [
            ("Shift schedule", "session", "cse_01Sample7", 27, 126, 0.82, 11), ("Press 2 job board", "session", "cse_01Sample4", 3, 122, 0.95, 8),
            ("Slitter blade change", "session", "cse_01Sample5", 9, 38, 0.81, 4), ("Ink reorder", "session", "cse_01Sample6", 4, 33, 0.91, 4),
            ("Order page login", "session", "cse_01Sample1", 22, 17, 0.82, 3), ("Spare parts count", "session", "cse_01Sample8", 50, 16, 0.85, 3),
            ("Core supplier quote", "session", "cse_01Sample10", 300, 15, 0.36, 2), ("Film price watch", "session", "cse_01Sample12", 1500, 13, 0.78, 1),
            ("Scrap report fix", "session", "cse_01Sample11", 2900, 11, 0.70, 1), ("Shipping label printer", "session", "cse_01Sample20", 95, 9, 0.85, 1),
            ("Dryer belt change", "session", "cse_01Sample22", 1100, 8, 0.48, 1), ("Box label sizes", "local", nil, 35, 7, 0, 0),
            ("Dock door repair", "session", "cse_01Sample3", 8, 6, 0.30, 1), ("Rewinder PM checklist", "session", "cse_01Sample2", 41, 5, 0.40, 1),
            ("Sttark Claude Kit checks", "kit", nil, 60, 1.2, 0, 0), ("Rename report columns", "session", "cse_01Sample9", 190, 1.1, 0.2, 0),
            ("Runs in temporary folders", "temp", nil, 4000, 0.9, 0, 0)]
        // the kind of each one's work (usage-scan.py's WORK: 0 software, 1 design, 2 browser and admin, 3 small or mixed)
        let kindOf = [0, 0, 1, 2, 2, 2, 2, 3, 0, 1, 0, 3, 1, 2, 3, 0, 3]
        var cells: [[Any]] = [], agentRows: [[Any]] = [], work: [[Any]] = []
        for (i, x) in made.enumerated() {
            for d in 0..<30 {
                // a few busy days, some quiet ones, the same on every run
                let f = [1.0, 0.2, 0.0, 1.6, 0.7, 0.0, 2.3, 1.2, 0.4, 0.9][(d * 7 + i * 3) % 10]
                guard f > 0 else { continue }
                let usd = x.4 * f
                let opus = usd * (i % 3 == 0 ? 0.79 : 0.92), other = usd - opus
                for (m, v) in [(0, opus), (i % 3 == 0 ? 1 : 2, other)] where v > 0 {
                    cells.append([i, d, m, v * (1 - x.5), v * x.5, v * (1 - x.5) * 2.4e6, v * x.5 * 2.4e6])
                }
                if x.6 > 0 { agentRows.append([i, d, max(1, Int(Double(x.6) * f))]) }
                work.append([i, d, kindOf[i], (usd * 115).rounded()])   // about 2 minutes at work for each dollar, as on a busy Mac
            }
        }
        let byKey: [[String: Any]] = made.enumerated().map { i, x in
            ["key": x.2.map { "cse:" + $0 } ?? (x.1 == "local" ? "sid:5f1c2e7a-sample-local-1" : x.1), "kind": x.1, "cse": x.2 as Any? ?? NSNull(),
             "title": x.0, "last": now - x.3 * 60]
        }
        let usageList: [String: Any] = [
            "v": 1, "at": now - 20, "keep_days": 45, "days": days,
            "models": [["id": "claude-opus-5-5", "name": "Opus 5.5", "priced": true], ["id": "claude-fable-5-2", "name": "Fable 5.2", "priced": true],
                       ["id": "claude-haiku-5-5", "name": "Haiku 5.5", "priced": true]],
            "sessions": byKey, "rows": cells, "agents": agentRows, "unpriced": [String: Any](),
            "kinds": [["id": "software", "name": "Software", "x": 12], ["id": "design", "name": "Design", "x": 5],
                      ["id": "admin", "name": "Browser and admin", "x": 2.5], ["id": "small", "name": "Small or mixed", "x": 2]],
            "work": work]
        try? FileManager.default.createDirectory(at: dir.appendingPathComponent("usage"), withIntermediateDirectories: true)
        try! JSONSerialization.data(withJSONObject: usageList).write(to: dir.appendingPathComponent("usage/by-session.json"))
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
///
/// They stay off every screen. AppKit moves a titled window back onto a screen when it is ordered front, resized or
/// moved (`constrainFrameRect(_:to:)`), and slides a window onto a screen when a sheet opens on it. So the window's
/// own frame wins over the first, and any frame on a screen goes left of every screen before it is set; `check` stops
/// the tool if a window of it is ever on a screen. STTARK_SHOT_FRAMES=1 prints the frames.
final class ShotWindow: NSWindow {
    static var key = false
    static let log = ProcessInfo.processInfo.environment["STTARK_SHOT_FRAMES"] != nil
    @objc(hasKeyAppearance) func keyLook() -> Bool { ShotWindow.key }
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        if Self.log {
            let moved = super.constrainFrameRect(frameRect, to: screen)
            if moved != frameRect { print("frame kept: AppKit would move \(frameRect) to \(moved)") }
        }
        return frameRect
    }
    override func setFrame(_ frameRect: NSRect, display flag: Bool) { super.setFrame(Self.off(frameRect), display: flag) }
    override func setFrame(_ frameRect: NSRect, display flag: Bool, animate: Bool) {
        super.setFrame(Self.off(frameRect), display: flag, animate: false)
    }
    override func setFrameOrigin(_ point: NSPoint) { super.setFrameOrigin(Self.off(NSRect(origin: point, size: frame.size)).origin) }
    override func setFrameTopLeftPoint(_ point: NSPoint) {
        super.setFrameOrigin(Self.off(NSRect(x: point.x, y: point.y - frame.height, width: frame.width, height: frame.height)).origin)
    }

    /// The frame, moved left of every screen when it would be on one.
    static func off(_ r: NSRect) -> NSRect {
        guard NSScreen.screens.contains(where: { $0.frame.intersects(r) }) else { return r }
        if log { print("frame kept off: \(r) asked") }
        return NSRect(x: away, y: r.minY, width: r.width, height: r.height)
    }

    /// An x left of every screen, with room for the widest window.
    static var away: CGFloat { min(-9000, (NSScreen.screens.map(\.frame.minX).min() ?? 0) - 4000) }

    /// Checks each move of any window of the tool, the sheets too, as it occurs.
    static func watch() {
        NotificationCenter.default.addObserver(forName: NSWindow.didMoveNotification, object: nil, queue: nil) { _ in
            MainActor.assumeIsolated { check("a move") }
        }
    }

    /// Every window of the tool that shows, the sheets too, is off every screen; else the tool stops at once.
    static func check(_ when: String) {
        let screens = NSScreen.screens.map(\.frame)
        for w in NSApp.windows where w.isVisible {
            if log { print("frame \(when): \(type(of: w)) \(w.frame) screens \(screens)") }
            if screens.contains(where: { $0.intersects(w.frame) }) {
                FileHandle.standardError.write("stopped: a window is on a screen at \(w.frame) (\(when))\n".data(using: .utf8)!)
                exit(1)
            }
        }
    }
}
