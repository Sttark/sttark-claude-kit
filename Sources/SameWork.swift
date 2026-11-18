import Foundation

/// One session for the same work (Resources/hooks/same-work.py): at a new session's first prompt, when an open session on
/// this Mac already does that work, Claude asks the person first whether the prompt goes there ("Send to <name>") or
/// stays ("Keep here"). Its log lines start with "same" (the Events page's Same work rows). On unless the person turns it
/// off in Settings ("sameWork" in KitDefaults' turned-off record). The hook reads "same_work" in the state file, which
/// the app writes at launch and at each change, since a running session keeps the hooks it started with.
enum SameWork {
    static let id = "sameWork"
    static var on: Bool { !KitDefaults.turnedOff(id) }

    static func tellHooks() {
        let v = on
        if State.read()["same_work"] as? Bool != v { State.change { $0["same_work"] = v } }
    }

    static func set(_ on: Bool) {
        KitDefaults.chose(id, on: on)
        tellHooks()
    }
}
