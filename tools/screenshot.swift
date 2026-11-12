// Draws the README's pictures with the app's own code, from made-up sessions in a temporary folder. Nothing from
// this Mac's own state:
//   docs/menu.png             the menu: what needs you, the count in each group, Open Sttark Claude Kit
//   docs/window-sessions.png  the window's Sessions page, a session that waits on someone else selected
//   docs/window-settings.png  the window's Settings page
//   docs/window-news.png      the window's What's new page
//   docs/whats-new.png        the What's new popup, with this repo's notes
// Each is light. STTARK_SHOT_DARK=<folder> also draws the window and the popup in dark mode into that folder.
// The window and the popup are real windows, put off the screen and captured with screencapture, so they look as
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
        c.build(menu, facts, Inbox.snapshot())
        Draw.png(menu.items, hot: nil, menuBar: true, to: "docs/menu.png")

        let model = KitModel()
        model.fixedFacts = facts
        model.reload()
        model.reloadFacts()
        model.selected = model.snap.rows.first { $0.wait?.kind == "email-reply" }?.id
        let w = Shot.window(model)
        let tall = CGFloat(Double(ProcessInfo.processInfo.environment["STTARK_SHOT_HEIGHT"] ?? "") ?? 900)
        for look in [false, true] where !look || dark != nil {
            let folder = look ? dark! : "docs"
            w.appearance = NSAppearance(named: look ? .darkAqua : .aqua)
            model.page = .sessions
            Shot.capture(w, to: folder + "/window-sessions.png")
            model.page = .settings
            Shot.capture(w, to: folder + "/window-settings.png")
            model.page = .news
            Shot.capture(w, to: folder + "/window-news.png")
            let pop = NotesPanel(WhatsNew.all, unseen: true) {}
            pop.appearance = w.appearance
            pop.setFrame(NSRect(x: -9000, y: 0, width: NotesPanel.width, height: min(NotesPanel.fitHeight(WhatsNew.all), tall)), display: true)
            Shot.capture(pop, to: folder + "/whats-new.png")
            pop.close()
        }
        w.close()
    }

    /// The window as the app makes it, off the screen.
    static func window(_ model: KitModel) -> NSWindow {
        let w = NSWindow(contentRect: NSRect(x: -9000, y: 0, width: 1180, height: 760),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        w.titleVisibility = .hidden
        w.titlebarAppearsTransparent = true
        w.isReleasedWhenClosed = false
        w.contentView = NSHostingView(rootView: KitRoot(model: model))
        w.setFrameOrigin(NSPoint(x: -9000, y: 0))
        return w
    }

    /// Shows the window off the screen, lets it draw, and captures it with its own pixels.
    static func capture(_ w: NSWindow, to path: String) {
        w.orderFrontRegardless()
        RunLoop.main.run(until: Date().addingTimeInterval(1.2))
        let t = Process()
        t.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        t.arguments = ["-x", "-o", "-l\(w.windowNumber)", path]
        try! t.run()
        t.waitUntilExit()
        print("wrote \(path)")
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

    static var facts: MenuFacts {
        var f = MenuFacts(version: "1.140", serverInstalled: true,
                          serverFolder: FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("src").path,
                          bypass: true, chromeApprover: true, chromeWindow: true, fileLinks: true, names: true, profile: true,
                          profileLast: "10:45 AM, no change", workingRules: true)
        f.reach = Reach.Settings(ways: ["chat"], email: "name@sttark.com", phone: "", chat: "https://chat.googleapis.com/v1/spaces/sample")
        f.whatsNew = 2
        f.models = [("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-haiku-5-5", "Haiku 5.5")]
        f.model = "claude-sonnet-5-5"
        f.loginEnds = Date().addingTimeInterval(20 * 86400)
        f.lastCheck = Date().addingTimeInterval(-6 * 60)
        return f
    }

    static func write(_ dir: URL) {
        let now = Date().timeIntervalSince1970
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
            session(5, "HVAC updates", "medium", ago: 1, reason: "Summarizes the agents' photos", app: ["working": true], turn: 2),
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
    }
}

/// Draws menu items the way macOS shows them: a check column, the item's own title with its fonts, colors and tab,
/// indentation, separators, a submenu arrow, and the highlighted row with its submenu open beside it.
enum Draw {
    static let rowH: CGFloat = 24, sepH: CGFloat = 11, inset: CGFloat = 5, checkW: CGFloat = 22, indentW: CGFloat = 14
    static let panelFill = NSColor(white: 0.975, alpha: 1)
    static let beige = NSColor(red: 0.973, green: 0.961, blue: 0.949, alpha: 1)   // brand Beige-Light

    static func height(_ i: NSMenuItem) -> CGFloat {
        if i.isSeparatorItem { return sepH }
        let h = (i.attributedTitle ?? NSAttributedString(string: i.title)).size().height
        return max(h > 18 ? rowH : 20, ceil(h) + 6)
    }

    static func textWidth(_ i: NSMenuItem) -> CGFloat {
        guard let t = i.attributedTitle else { return 0 }
        let tabbed = t.string.contains("\t")
        return (tabbed ? Controller.tab : ceil(t.size().width)) + CGFloat(i.indentationLevel) * indentW
    }

    static func panelSize(_ items: [NSMenuItem]) -> NSSize {
        let w = inset * 2 + 6 + checkW + (items.map(textWidth).max() ?? 200)
            + (items.contains { $0.submenu != nil || !$0.keyEquivalent.isEmpty } ? 30 : 14)
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
        NSColor.black.withAlphaComponent(0.12).setStroke()
        NSBezierPath(roundedRect: r.insetBy(dx: 0.5, dy: 0.5), xRadius: 10, yRadius: 10).stroke()

        var y = origin.y + 5
        var rects: [NSRect] = []
        for (n, i) in items.enumerated() {
            let h = height(i)
            let row = NSRect(x: r.minX + inset, y: y, width: r.width - 2 * inset, height: h)
            rects.append(row)
            if i.isSeparatorItem {
                NSColor.black.withAlphaComponent(0.1).setFill()
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
                let x = row.minX + 6 + checkW + CGFloat(i.indentationLevel) * indentW
                t.draw(with: NSRect(x: x, y: y + (h - th) / 2, width: textWidth(i) + 4, height: th + 2),
                       options: [.usesLineFragmentOrigin])
                if i.submenu != nil {
                    let arrow = NSAttributedString(string: "›", attributes: [.font: NSFont.systemFont(ofSize: 17, weight: .medium),
                        .foregroundColor: isHot ? NSColor.white : NSColor.secondaryLabelColor])
                    arrow.draw(at: NSPoint(x: row.maxX - 8 - arrow.size().width, y: y + (h - arrow.size().height) / 2 - 1))
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
        NSAppearance(named: .aqua)!.performAsCurrentDrawingAppearance {
            beige.setFill()
            NSRect(x: 0, y: 0, width: w, height: h).fill()
            if menuBar {   // the menu bar, with the gauge as the app draws it
                NSColor(white: 0.93, alpha: 1).setFill()
                NSRect(x: 0, y: 0, width: w, height: 30).fill()
                NSColor.black.withAlphaComponent(0.1).setFill()
                NSBezierPath(roundedRect: NSRect(x: 24, y: 4, width: 34, height: 22), xRadius: 5, yRadius: 5).fill()
                let g = GaugeIcon.image("xhigh")
                let tinted = NSImage(size: g.size, flipped: false) { rect in
                    g.draw(in: rect)
                    NSColor.black.set()
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
