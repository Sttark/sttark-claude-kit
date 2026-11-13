import AppKit
import UserNotifications

/// "Reach me by": how a session's scheduled task gets its result to the person, through claude-notify
/// (Resources/hooks/notify.py). The choice is "reach" in the shared state file: the ways picked and the
/// address, phone number and Google Chat webhook they use. claude-notify sends email, Claude app and Google
/// Chat itself; the app sends the two that need its macOS permissions, a Mac notice and a text from Messages,
/// from the notify-queue folder, and writes back how each went.
enum Reach {
    static let ways = ["email", "push", "chat", "text", "mac"]
    static let names = ["email": "Email", "push": "Claude app", "chat": "Google Chat", "text": "Text message", "mac": "Mac notice"]
    static var queue: URL { supportDir.appendingPathComponent("notify-queue") }
    static var script: String { hooksDir.appendingPathComponent("notify.py").path }

    struct Settings {
        var ways: [String]
        var email: String
        var phone: String
        var chat: String
    }

    /// The address of the Claude Code login: the email default until the person sets one.
    static var loginEmail: String {
        let u = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".claude.json")
        let d = (try? JSONSerialization.jsonObject(with: Data(contentsOf: u))) as? [String: Any]
        return (d?["oauthAccount"] as? [String: Any])?["emailAddress"] as? String ?? ""
    }

    /// As notify.py reads it: with nothing picked yet, Email when the address is a Sttark one, else a Mac notice.
    static func settings(_ state: [String: Any] = State.read()) -> Settings {
        let r = state["reach"] as? [String: Any] ?? [:]
        let email = (r["email"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? loginEmail
        let ways = r["ways"] as? [String] ?? (email.lowercased().hasSuffix("@sttark.com") ? ["email"] : ["mac"])
        return Settings(ways: ways, email: email, phone: r["phone"] as? String ?? "", chat: r["chat"] as? String ?? "")
    }

    static func save(_ edit: @escaping (inout [String: Any]) -> Void) {
        State.change { s in
            var r = s["reach"] as? [String: Any] ?? [:]
            if r["ways"] == nil { r["ways"] = settings(s).ways }   // the default becomes a choice once anything changes
            edit(&r)
            s["reach"] = r
        }
    }

    static func toggle(_ way: String) {
        let on = !settings().ways.contains(way)
        save { r in
            var w = (r["ways"] as? [String] ?? []).filter { $0 != way }
            if on { w.append(way) }
            r["ways"] = ways.filter(w.contains)
        }
        note("Reach me by: \(names[way] ?? way) \(on ? "on" : "off")")
    }

    /// A way checked or unchecked in Settings. A way that needs a setting asks for it first.
    static func pick(_ way: String) {
        let r = settings()
        if !r.ways.contains(way), missing(way, r) != nil {
            let got = way == "email" ? askEmail() : way == "text" ? askPhone() : way == "chat" ? askChat() : true
            guard got else { return }
        }
        toggle(way)
    }

    static func set(_ key: String, _ value: String) {
        save { $0[key] = value }
        note("Reach me by: \(key == "chat" ? "Google Chat webhook" : key == "phone" ? "phone number" : "email address") \(value.isEmpty ? "cleared" : "set")")
    }

    /// The menu's line: "Reach me by: Email, Mac notice".
    static func summary(_ s: Settings) -> String {
        s.ways.isEmpty ? "nothing" : ways.filter(s.ways.contains).compactMap { names[$0] }.joined(separator: ", ")
    }

    /// Why a way can't send yet, or nil when it can.
    static func missing(_ way: String, _ s: Settings) -> String? {
        switch way {
        case "email": return s.email.lowercased().hasSuffix("@sttark.com") ? nil : "Needs your @sttark.com address"
        case "chat": return s.chat.hasPrefix("https://chat.googleapis.com/") ? nil : "Needs a space's webhook"
        case "text": return s.phone.isEmpty ? "Needs your phone number" : nil
        default: return nil
        }
    }

    // MARK: the app's part

    private static let work = DispatchQueue(label: "reach")
    private static var busy = false

    /// Every 2 seconds: each message claude-notify left for the app.
    static func poll() {
        guard !busy, let files = try? FileManager.default.contentsOfDirectory(atPath: queue.path) else { return }
        let jobs = files.filter { $0.hasSuffix(".json") }
        guard !jobs.isEmpty else { return }
        busy = true
        work.async {
            for name in jobs {
                let u = queue.appendingPathComponent(name)
                guard let d = try? Data(contentsOf: u), let job = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else {
                    try? FileManager.default.removeItem(at: u); continue
                }
                try? FileManager.default.removeItem(at: u)
                var answer: [String: [String: Any]] = [:]
                for way in job["ways"] as? [String] ?? [] {
                    let (ok, words) = way == "mac" ? notice(job, id: String(name.dropLast(5))) : way == "text" ? text(job) : (false, "not the app's")
                    answer[way] = ["ok": ok, "words": words]
                }
                if let out = try? JSONSerialization.data(withJSONObject: answer) {
                    try? out.write(to: queue.appendingPathComponent(String(name.dropLast(5)) + ".done"), options: .atomic)
                }
            }
            // answers nobody read (claude-notify gave up) don't pile up
            for f in (try? FileManager.default.contentsOfDirectory(atPath: queue.path)) ?? [] where f.hasSuffix(".done") {
                let u = queue.appendingPathComponent(f)
                if let t = (try? u.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate, -t.timeIntervalSinceNow > 60 {
                    try? FileManager.default.removeItem(at: u)
                }
            }
            DispatchQueue.main.async { busy = false }
        }
    }

    /// A notice on this Mac; a click opens the link, or the session.
    static func notice(_ job: [String: Any], id: String) -> (Bool, String) {
        let c = UNUserNotificationCenter.current()
        let sem = DispatchSemaphore(value: 0)
        var allowed = false
        c.requestAuthorization(options: [.alert, .sound]) { ok, _ in allowed = ok; sem.signal() }
        _ = sem.wait(timeout: .now() + 5)
        guard allowed else { return (false, "macOS doesn't allow Sttark Claude Kit's notices: System Settings > Notifications") }
        let n = UNMutableNotificationContent()
        n.title = job["subject"] as? String ?? ""
        let title = job["title"] as? String ?? ""
        if !title.isEmpty { n.subtitle = title }
        n.body = job["body"] as? String ?? ""
        n.sound = .default
        let link = job["link"] as? String ?? ""
        n.userInfo = ["url": link.isEmpty ? (job["url"] as? String ?? "") : link]
        c.add(UNNotificationRequest(identifier: "notify-\(id)", content: n, trigger: nil))
        return (true, "shown")
    }

    /// A text through Messages on this Mac, to the number set: iMessage, or SMS through the paired iPhone when
    /// the number has no iMessage. Messages starts hidden when it isn't running, so nothing comes in front.
    static func text(_ job: [String: Any]) -> (Bool, String) {
        let phone = (job["phone"] as? String ?? "").trimmingCharacters(in: .whitespaces)
        guard !phone.isEmpty else { return (false, "needs your phone number: set it under Reach me by in the menu") }
        if NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.MobileSMS").isEmpty {
            Updater.run("/usr/bin/open", ["-g", "-j", "-a", "Messages"])
            Thread.sleep(forTimeInterval: 3)
        }
        let r = Updater.run("/usr/bin/osascript", ["-e", messagesScript, phone, job["text"] as? String ?? ""])
        let out = r.1.trimmingCharacters(in: .whitespacesAndNewlines)
        return r.0 == 0 ? (true, "sent to \(phone) by \(out)") : (false, "Messages didn't send it: \(out.prefix(160))")
    }

    static let messagesScript = """
    on run {phone, msg}
        tell application "Messages"
            try
                set s to 1st account whose service type = iMessage
                send msg to participant phone of s
                return "iMessage"
            on error
                set s to 1st account whose service type = SMS
                send msg to participant phone of s
                return "SMS"
            end try
        end tell
    end run
    """

    // MARK: asking for a setting

    static func ask(_ title: String, _ info: String, _ value: String, placeholder: String) -> String? {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = info
        let f = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        f.stringValue = value
        f.placeholderString = placeholder
        a.accessoryView = f
        a.addButton(withTitle: "Save")
        a.addButton(withTitle: "Cancel")
        a.window.initialFirstResponder = f
        NSApp.activate(ignoringOtherApps: true)
        guard a.runModal() == .alertFirstButtonReturn else { return nil }
        return f.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func askEmail() -> Bool {
        guard let v = ask("Email address", "Messages from your sessions come to this address, from alerts@sttark.com. Only a @sttark.com address can get them.",
                          settings().email, placeholder: "name@sttark.com") else { return false }
        guard v.isEmpty || v.lowercased().hasSuffix("@sttark.com") else {
            let a = NSAlert(); a.messageText = "Only a @sttark.com address"; a.informativeText = "Sttark mail sends only to Sttark addresses. Nothing was changed."
            a.runModal(); return false
        }
        set("email", v); return !v.isEmpty
    }

    static func askPhone() -> Bool {
        guard let v = ask("Phone number", "Texts come from Messages on this Mac: an iMessage, or a text through your paired iPhone when the number has no iMessage. The first one asks you to let Sttark Claude Kit use Messages.",
                          settings().phone, placeholder: "+1 864 555 0100") else { return false }
        set("phone", v); return !v.isEmpty
    }

    static func askChat() -> Bool {
        guard let v = ask("Google Chat webhook", "In Google Chat, make a space with only you in it, then open the space's name > Apps & integrations > Webhooks > Add webhook, and paste its URL here. Set the space's notifications to All.",
                          settings().chat, placeholder: "https://chat.googleapis.com/v1/spaces/…") else { return false }
        guard v.isEmpty || v.hasPrefix("https://chat.googleapis.com/") else {
            let a = NSAlert(); a.messageText = "Not a Google Chat webhook"; a.informativeText = "A webhook URL starts with https://chat.googleapis.com/. Nothing was changed."
            a.runModal(); return false
        }
        set("chat", v); return !v.isEmpty
    }

    /// The menu's Send a test: a test through every way picked, then what happened.
    static func test() {
        DispatchQueue.global().async {
            let r = Updater.run("/usr/bin/python3", [script, "--test"])
            DispatchQueue.main.async {
                let a = NSAlert()
                a.messageText = r.0 == 0 ? "Test sent" : "The test didn't go out"
                a.informativeText = r.1.trimmingCharacters(in: .whitespacesAndNewlines)
                    .replacingOccurrences(of: "THE SESSION SENDS THIS ONE: call the PushNotification tool now (load it first with ToolSearch \"select:PushNotification\" when it is not loaded) with message: ",
                                          with: "only a session can send it, with its PushNotification tool; it would say ")
                NSApp.activate(ignoringOtherApps: true)
                a.runModal()
            }
        }
    }
}

/// Waits a session handed to the Kit with claude-wait (Resources/hooks/wait.py), so the person can archive the session.
/// wait.py --check runs every minute and brings the session back when the thing happens or at its deadline.
enum Waits {
    struct Wait {
        let id: String
        let title: String
        let what: String
        let why: String
        let by: Date?
        let back: Bool
        /// pr, at, email-reply, check-script or check-prompt, and what it watches.
        var kind = ""
        var target = ""
        var from = ""
        /// Seconds between checks the session asked for (0: the Kit's own pace), and when it was set.
        var every: Double = 0
        var setAt: Date? = nil
        /// The session's Remote Control id and link, and a link to what it watches (a pull request).
        var cse = ""
        var sessionURL = ""
        var url = ""
        /// Why its last check failed, and since when; empty while its checks work.
        var failing = ""
        var failingSince: Date? = nil
    }

    static var script: String { hooksDir.appendingPathComponent("wait.py").path }
    private static var running = false

    static func list(_ state: [String: Any] = State.read()) -> [Wait] {
        let all = state["waits"] as? [String: [String: Any]] ?? [:]
        return all.map { id, w in
            let kind = w["kind"] as? String ?? ""
            let target = w["target"] as? String ?? ""
            let at = Limit.num(w["at"]).map { Date(timeIntervalSince1970: $0) }
            let what = (w["what"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? (kind == "pr" ? "PR #\(target.split(separator: "#").last ?? "") \(w["want"] as? String ?? "")"
                : kind == "email-reply" ? "Email reply"
                : kind == "check-prompt" ? "Yes to: \(target)"
                : kind == "check-script" ? "Its check script"
                : at.map { "Check at \(Limit.clock($0))" } ?? "A time")
            var x = Wait(id: id, title: (w["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "A session",
                         what: what, why: w["why"] as? String ?? "",
                         by: Limit.num(w["by"]).map { Date(timeIntervalSince1970: $0) } ?? at,
                         back: w["stage"] as? String == "back")
            x.kind = kind
            x.target = target
            x.from = w["from"] as? String ?? ""
            x.every = Limit.num(w["every"]) ?? 0
            x.failing = w["failing"] as? String ?? ""
            x.failingSince = Limit.num(w["failing_since"]).map { Date(timeIntervalSince1970: $0) }
            x.setAt = Limit.num(w["set_at"]).map { Date(timeIntervalSince1970: $0) }
            x.cse = w["cse"] as? String ?? ""
            x.sessionURL = w["session_url"] as? String ?? ""
            x.url = w["url"] as? String ?? ""
            return x
        }.filter { !$0.back }.sorted { ($0.by ?? .distantFuture) < ($1.by ?? .distantFuture) }
    }

    /// Every minute: the check reads each pull request with gh and the clock; no model calls.
    static func check() {
        guard !running else { return }
        running = true
        DispatchQueue.global().async {
            Updater.run("/usr/bin/python3", [script, "--check"])
            DispatchQueue.main.async { running = false }
        }
    }

    static func run(_ args: [String]) {
        DispatchQueue.global().async { Updater.run("/usr/bin/python3", [script] + args) }
    }
}
