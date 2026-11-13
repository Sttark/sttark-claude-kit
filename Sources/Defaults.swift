import AppKit

/// The Kit sets every Mac up the way Sttark works with Claude. Each switch here is on unless the person turned it
/// off: on every launch, one that is off and was never turned off by hand comes on. Turning one off in Settings or
/// the menu records that ("turnedOff" in the app's settings), and the Kit never turns it back on; turning it on
/// again clears the record. A switch that was off before this came in counts as never chosen, so people who had
/// it off get it once, with one notice that says what came on and where to turn it off.
///
/// Claude Code's own phone notice settings (install-hooks.py --defaults) need no record: a value the person set,
/// true or false, is never changed; only a missing one is set.
enum KitDefaults {
    static let offKey = "turnedOff"
    static var test: Bool { ProcessInfo.processInfo.environment["STTARK_CLAUDE_KIT_TEST"] != nil }

    /// The switches the Kit turns on, with the names Settings shows.
    static let names = ["names": "Name sessions automatically", "profile": "Sync Claude profile instructions",
                        "fileLinks": "Links to files", "bypass": "Bypass permissions",
                        "chrome": "Approve Claude in Chrome"]
    static var desktopPrefs: String { hooksDir.appendingPathComponent("desktop-prefs.py").path }

    static func turnedOff(_ id: String) -> Bool {
        (UserDefaults.standard.stringArray(forKey: offKey) ?? []).contains(id)
    }

    /// Called by each switch: off records the person's choice; on clears it.
    static func chose(_ id: String, on: Bool) {
        var ids = (UserDefaults.standard.stringArray(forKey: offKey) ?? []).filter { $0 != id }
        if !on { ids.append(id) }
        UserDefaults.standard.set(ids, forKey: offKey)
        note("\(id) \(on ? "on" : "off") by you\(on ? "" : ": the Kit leaves it off")")
    }

    /// What should come on now: off, and never turned off by hand. The sync also needs the Claude app's sign-in.
    static func due(on: [String: Bool], claudeAppSignedIn: Bool) -> [String] {
        ["names", "profile", "fileLinks", "bypass", "chrome"].filter { id in
            on[id] == false && !turnedOff(id) && (id != "profile" || claudeAppSignedIn)
        }
    }

    /// On launch, after the hooks are installed. Shows one notice when anything came on.
    static func apply() {
        var came: [String] = []
        let push = Updater.run("/usr/bin/python3", [Bypass.installer, "--defaults"]).1
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if push != "unchanged" && !push.isEmpty {
            note("defaults: \(push)")
            came.append("Phone notices from Claude Code")
        }
        let ids = due(on: ["names": Names.on, "profile": ProfileSync.on, "fileLinks": FileLinks.on,
                           "bypass": Bypass.on, "chrome": ChromeApprover.on],
                      claudeAppSignedIn: ProfileSync.claudeAppSignedIn)
        let bypassParts = applyBypassSettings()
        if !bypassParts.isEmpty && !ids.contains("bypass") { came.append("Bypass permissions for every session") }
        for id in ids where id != "profile" {
            if test { note("defaults: would turn on \(id) (test)"); continue }
            if id == "names" { Names.set(true) }
            if id == "fileLinks" { FileLinks.set(true) }
            if id == "bypass" { Bypass.set(true) }
            if id == "chrome" { ChromeApprover.start() }
            came.append(id == "chrome" ? names[id]! + " (allow SttarkChromeApprover in System Settings > Privacy & Security > Accessibility)"
                        : id == "bypass" ? "Bypass permissions for every session" : names[id]!)
        }
        guard ids.contains("profile"), !test else {
            if ids.contains("profile") { note("defaults: would turn on profile (test)") }
            tell(came)
            return
        }
        ProfileSync.start { err in
            if let err { note("defaults: profile sync didn't start, tries again at the next launch: \(err)") }
            else { came.append(names["profile"]!) }
            tell(came)
        }
    }

    /// Claude Code's bypass keys and the Claude desktop app's settings, each set only when missing. The bypass parts
    /// follow the Bypass switch: none when the person turned it off. Runs on launch and every 10 minutes, because the
    /// desktop app can write its file again without a key the Kit set. Returns what was set.
    @discardableResult
    static func applyBypassSettings() -> [String] {
        var set: [String] = []
        let bypass = !turnedOff("bypass")
        if bypass {
            let r = Updater.run("/usr/bin/python3", [Bypass.installer, "--bypass-defaults", "on"]).1
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if r.hasPrefix("set") { note("defaults: \(r)"); set.append(r) }
        }
        let d = Updater.run("/usr/bin/python3", [desktopPrefs, "apply"] + (bypass ? ["--bypass"] : [])).1
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if d.hasPrefix("set") { note("defaults: Claude app \(d)"); if d.contains("bypass") { set.append(d) } }
        return set
    }

    /// The Bypass switch went off: take out the bypass keys the Kit set.
    static func bypassOff() {
        let r = Updater.run("/usr/bin/python3", [Bypass.installer, "--bypass-defaults", "off"]).1
        let d = Updater.run("/usr/bin/python3", [desktopPrefs, "bypass-off"]).1
        note("bypass off: \(r.trimmingCharacters(in: .whitespacesAndNewlines)); Claude app \(d.trimmingCharacters(in: .whitespacesAndNewlines))")
    }

    static func tell(_ came: [String]) {
        guard !came.isEmpty else { return }
        note("defaults: turned on " + came.joined(separator: ", "))
        if test { return }
        Updater.post("defaults", "Sttark Claude Kit set up how Sttark works with Claude",
                     "On now: \(came.joined(separator: "; ")). To turn one off, open Sttark Claude Kit > Settings. Click to open it.")
    }
}
