// Draws the README's pictures of the menu with the app's own menu code (Sources/Menu.swift), from made-up sessions
// in a temporary folder, in light mode. Nothing from a real screen and nothing from this Mac's own state:
//   docs/menu.png   the whole menu, with one session's submenu open
//   docs/limit.png  sessions holding at the usage limit, and a session's usage setting open
// The times are drawn in a time zone where it is late morning, so the sample reset times read the same on every run.
// Run from the repo root:
//   swiftc -parse-as-library -o /tmp/shot tools/screenshot.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/shot
import AppKit

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

        NSApplication.shared.appearance = NSAppearance(named: .aqua)
        let c = Controller()
        let facts = MenuFacts(version: "1.125", serverInstalled: true, bypass: true, chromeApprover: true, chromeWindow: true,
                              fileLinks: true, names: true, profile: true, workingRules: true)

        // The whole menu, under the limit.
        Sample.write(dir, atLimit: false)
        let menu = NSMenu()
        c.build(menu, facts)
        let hot = menu.items.firstIndex { $0.attributedTitle?.string.hasPrefix("Fix the login") == true }
        Draw.png(menu.items, hot: hot, menuBar: true, to: "docs/menu.png")

        // At the limit: who holds, until when, and a session's own setting.
        Sample.write(dir, atLimit: true)
        let part = NSMenu()
        c.addLimit(part)
        part.addItem(.separator())
        c.addSessions(part, paused: false)
        let items = Array(part.items.drop { $0.isSeparatorItem })
        let open = items.lastIndex { $0.attributedTitle?.string.hasPrefix("Site map plan") == true }
        Draw.png(items, hot: open, menuBar: false, to: "docs/limit.png")
    }
}

/// Made-up sessions and usage, written where the app's code reads them.
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

    static func write(_ dir: URL, atLimit: Bool) {
        let now = Date().timeIntervalSince1970
        func session(_ title: String, _ level: String, _ sid: String, ago: Double, reason: String = "", manual: Bool = false) -> [String: Any] {
            ["title": title, "level": level, "reason": reason, "manual": manual, "at": now - ago * 60,
             "transcript": "/sample/\(sid).jsonl"]
        }
        let sessions: [String: Any] = [
            "cse_01Sample0000000000000001": session("Fix the login timeout on the order page", "xhigh", "5d1e0c7a-sample-0001", ago: 1,
                reason: "Unknown cause across server and browser; needs careful debugging."),
            "cse_01Sample0000000000000002": session("Rename report columns", "low", "9a3b44f2-sample-0002", ago: 6),
            "cse_01Sample0000000000000003": session("Site map plan", "high", "c41d9e08-sample-0003", ago: 9,
                reason: "Design work across several apps; a plan with drawings."),
            "cse_01Sample0000000000000004": session("Draft the press maintenance SOP", "max", "e7f2a915-sample-0004", ago: 14, manual: true),
            "cse_01Sample0000000000000005": session("Inventory photo cleanup", "medium", "2b8c6d31-sample-0005", ago: 20),
        ]
        let modes: [String: Any] = [
            "cse_01Sample0000000000000003": ["mode": "hold", "at": 80, "sid": "c41d9e08-sample-0003",
                                            "cse": "cse_01Sample0000000000000003", "title": "Site map plan", "by": "typed", "set_at": now - 3600],
            "cse_01Sample0000000000000005": ["mode": "hold", "at": 60, "sid": "2b8c6d31-sample-0005",
                                            "cse": "cse_01Sample0000000000000005", "title": "Inventory photo cleanup", "by": "menu", "set_at": now - 7200],
            "cse_01Sample0000000000000004": ["mode": "credits", "sid": "e7f2a915-sample-0004",
                                            "cse": "cse_01Sample0000000000000004", "title": "Draft the press maintenance SOP", "by": "command", "set_at": now - 600],
        ]
        let fiveHour = at(18, 0)
        var daysToSat = (7 - Calendar.current.component(.weekday, from: Date())) % 7   // Saturday is 7
        if daysToSat == 0 { daysToSat = 7 }
        let weekly = at(2, 0, daysAhead: daysToSat)
        let pid = Int(getpid())   // the menu drops a row whose process is gone
        let pauses: [String: Any] = !atLimit ? [:] : [
            "9a3b44f2-sample-0002": ["sid": "9a3b44f2-sample-0002", "cse": "cse_01Sample0000000000000002", "title": "Rename report columns",
                                     "limit": "5-hour", "since": now - 900, "until": fiveHour.timeIntervalSince1970, "pid": pid,
                                     "what": "wait", "mode": "follow", "at": 100, "percent": 100],
            "c41d9e08-sample-0003": ["sid": "c41d9e08-sample-0003", "cse": "cse_01Sample0000000000000003", "title": "Site map plan",
                                     "limit": "5-hour", "since": now - 3000, "until": fiveHour.timeIntervalSince1970, "pid": pid,
                                     "what": "hold", "mode": "hold", "at": 80, "percent": 81],
            "c41d9e08-sample-0003/toolu_01Sample0001": ["sid": "c41d9e08-sample-0003", "agent": "a1b2c3", "cse": "cse_01Sample0000000000000003",
                                            "title": "Site map plan", "limit": "5-hour", "since": now - 2990,
                                            "until": fiveHour.timeIntervalSince1970, "pid": pid, "what": "hold", "mode": "hold", "at": 80, "percent": 81],
            "2b8c6d31-sample-0005": ["sid": "2b8c6d31-sample-0005", "cse": "cse_01Sample0000000000000005", "title": "Inventory photo cleanup",
                                     "limit": "weekly", "since": now - 5400, "until": weekly.timeIntervalSince1970, "pid": pid,
                                     "what": "hold", "mode": "hold", "at": 60, "percent": 61],
        ]
        let state: [String: Any] = [
            "paused": false, "limit_credits_all": false, "limit_modes": modes, "limit_pauses": pauses, "sessions": sessions,
            "models": [["id": "claude-sonnet-5-5", "label": "Sonnet 5.5"], ["id": "claude-haiku-5-5", "label": "Haiku 5.5"]],
        ]
        let usage: [String: Any] = ["at": now, "usage": [
            "extra_usage": ["is_enabled": true],
            "limits": [["kind": "session", "percent": atLimit ? 100 : 42, "resets_at": iso(fiveHour), "is_active": true],
                       ["kind": "weekly_all", "percent": 63, "resets_at": iso(weekly), "is_active": false]]]]
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
