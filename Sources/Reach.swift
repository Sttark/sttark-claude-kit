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
        /// The Alerts switch at the top of Reach me by. Off: nothing alerts outside the Kit app; each message is kept on
        /// its session (Kept, notify.py keep_in_kit()). The ways and their settings stay as they are.
        var alerts = true
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
        return Settings(ways: ways, email: email, phone: r["phone"] as? String ?? "", chat: r["chat"] as? String ?? "",
                        alerts: r["alerts"] as? Bool ?? true)
    }

    /// Reach me by's Alerts switch, as notify.py alerts_on() reads it: on unless the person turned it off.
    static var alertsOn: Bool { settings().alerts }

    /// The Alerts switch in Settings. Off keeps the ways, the address, the phone number and the webhook, so on brings
    /// them back as they were.
    static func setAlerts(_ on: Bool) {
        save { $0["alerts"] = on }
        note("Reach me by: alerts \(on ? "on" : "off")")
    }

    /// What happens to a session's message, for the session's panel: "tells you by Email", or that it stays here.
    static func then(_ s: Settings) -> String {
        s.alerts && !s.ways.isEmpty ? "tells you by \(summary(s))" : "its message stays here, on the session"
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

    /// Every 2 seconds: each message claude-notify left for the app. With alerts off (a job that came in the moment
    /// they went off) nothing shows: notify.py keeps messages in the Kit app before they reach here.
    static func poll() {
        guard !busy, let files = try? FileManager.default.contentsOfDirectory(atPath: queue.path) else { return }
        let jobs = files.filter { $0.hasSuffix(".json") }
        guard !jobs.isEmpty else { return }
        let alerts = alertsOn
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
                    let (ok, words) = !alerts ? (false, "not shown: alerts are off")
                        : way == "mac" ? notice(job, id: String(name.dropLast(5))) : way == "text" ? text(job) : (false, "not the app's")
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

    /// A notice on this Mac; a click opens the link, or the session (in the Claude app when the Mac has it).
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
        n.userInfo = link.isEmpty ? ["url": job["url"] as? String ?? "", "id": job["cse"] as? String ?? ""] : ["url": link]
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

/// Each session's alerts: off unless the person turned them on for that session, with the bell on its row in the window
/// (or its Alerts switch) or on its page on the phone (KitActions.setAlerts). Each choice by hand, on or off, is
/// `alerts[<cse>] = {on, at, by, title}` in the state file, by the session's Remote Control id, so it lasts through
/// archive, unarchive, a Kit restart and a Mac restart. A session with no choice, a new one too, is off: nothing about it
/// goes out by any Reach me by way. notify.py held() gives "this session's alerts are off", so claude-notify's message and
/// the Kit's own (wait.py, watch.py) are kept on the session, as with Reach me by's Alerts switch off (Kept), and the
/// Needs you reminder goes neither to this Mac nor to the phone (Waiting.notifyDue). A session with no Remote Control id
/// has no switch, so nothing holds it back.
enum Alerts {
    static let key = "alerts"
    /// The store from when a session started on: `alerts_off[<cse>]`, only the sessions turned off. migrate() moves it
    /// to `alerts` once.
    static let oldKey = "alerts_off"

    /// A Remote Control id as the state file keys it: session_X is cse_X.
    static func cse(_ id: String) -> String { id.hasPrefix("session_") ? "cse_" + id.dropFirst(8) : id }

    /// The sessions whose alerts the person turned on, by Remote Control id.
    static func turnedOn(_ state: [String: Any]? = nil) -> Set<String> {
        Set(((state ?? State.read())[key] as? [String: Any] ?? [:]).compactMap { k, v in
            (v as? [String: Any])?["on"] as? Bool == true ? k : nil
        })
    }

    /// Whether a session's alerts are on: only when the person turned them on. A row with no Remote Control id has no
    /// switch, so it counts as on.
    static func on(_ id: String, in state: [String: Any]? = nil) -> Bool {
        let c = cse(id)
        return !c.hasPrefix("cse_") || turnedOn(state).contains(c)
    }

    /// An entry is dropped when its session was not used for this long and has no open wait, so the list stays short.
    static let keepDays: Double = 90

    /// Turns a session's alerts on or off, with who asked and the session's name then, for the log and the Events page.
    /// The choice is kept either way; returns false (and writes no log line) when the alerts were that way already.
    @discardableResult
    static func set(_ id: String, on: Bool, title: String, by origin: KitActions.Origin) -> Bool {
        let c = cse(id)
        guard c.hasPrefix("cse_") else { return false }
        var changed = false
        State.change { s in
            var all = s[key] as? [String: Any] ?? [:]
            let was = (all[c] as? [String: Any])?["on"] as? Bool
            guard was != on else { return }
            changed = (was == true) != on
            let now = Date().timeIntervalSince1970
            all[c] = ["on": on, "at": now, "by": origin.rawValue, "title": title] as [String: Any]
            let sessions = s["sessions"] as? [String: Any] ?? [:]
            let waiting = Set((s["waits"] as? [String: Any] ?? [:]).values.compactMap { ($0 as? [String: Any])?["cse"] as? String })
            for (k, v) in all where k != c && !waiting.contains(k) {
                let used = max(Limit.num((v as? [String: Any])?["at"]) ?? 0, Limit.num((sessions[k] as? [String: Any])?["at"]) ?? 0)
                if now - used > keepDays * 86400 { all.removeValue(forKey: k) }
            }
            s[key] = all
        }
        if changed { logLine("notify", "alerts \(on ? "on" : "off") for \(c) \"\(title)\" (\(origin.rawValue))") }
        return changed
    }

    /// Once, at the first launch with the old store in the state (`alerts_off`: only the sessions turned off, so a
    /// session with no entry there was on by default or turned on by hand). Its entries stay off, chosen by hand. A
    /// session whose last change in the log is "alerts on for" was turned on by hand, so it stays on. Every other
    /// session made no choice, so it is off from now on. Returns how many choices it kept, or nil with no old store.
    @discardableResult
    static func migrate(log: URL = logURL) -> (off: Int, on: Int)? {
        guard State.read()[oldKey] != nil else { return nil }
        // the last change of each session: "2026-11-18 10:43:21 notify alerts on for cse_01… "Name" (window)"
        var last: [String: (on: Bool, at: Double, title: String, by: String)] = [:]
        let text = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
        if text.contains(" alerts on for cse_") {
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH:mm:ss"
            let re = try! NSRegularExpression(pattern: #"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) notify +alerts (on|off) for (cse_\w+) "(.*)" \((window|phone)\)$"#,
                                              options: .anchorsMatchLines)
            let ns = text as NSString
            for m in re.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
                let g = { (i: Int) in ns.substring(with: m.range(at: i)) }
                last[g(3)] = (g(2) == "on", f.date(from: g(1))?.timeIntervalSince1970 ?? 0, g(4), g(5))
            }
        }
        var kept = (off: 0, on: 0)
        State.change { s in
            guard s[oldKey] != nil else { return }
            let old = s[oldKey] as? [String: Any] ?? [:]
            var all = s[key] as? [String: Any] ?? [:]
            for (c, v) in old where all[c] == nil {
                var x = v as? [String: Any] ?? [:]
                x["on"] = false
                all[c] = x
                kept.off += 1
            }
            for (c, l) in last where l.on && old[c] == nil && all[c] == nil {
                all[c] = ["on": true, "at": l.at, "by": l.by, "title": l.title] as [String: Any]
                kept.on += 1
            }
            s[key] = all
            s.removeValue(forKey: oldKey)
        }
        logLine("notify", "alerts of each session are off unless turned on: kept \(kept.off) turned off and \(kept.on) turned on by hand")
        return kept
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
        /// An email reply's mailbox when it is not the person's own (a shared one), its Gmail search, and how the Kit
        /// read it last: "mail" (directly, claude-mail), "model" (a Haiku run through Workrouter) or "sign-in" (it
        /// can't read that mailbox until someone signs in on this Mac).
        var mailbox = ""
        var query = ""
        var via = ""
        /// Seconds between checks the session asked for (0: the Kit's own pace), and when it was set.
        var every: Double = 0
        var setAt: Date? = nil
        /// The session's Remote Control id and link, and a link to what it watches (a pull request).
        var cse = ""
        /// The folder the session runs in (a full path; it stays on this Mac).
        var folder = ""
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
            x.mailbox = w["mailbox"] as? String ?? ""
            x.query = w["query"] as? String ?? ""
            x.via = w["via"] as? String ?? ""
            x.every = Limit.num(w["every"]) ?? 0
            x.failing = w["failing"] as? String ?? ""
            x.failingSince = Limit.num(w["failing_since"]).map { Date(timeIntervalSince1970: $0) }
            x.setAt = Limit.num(w["set_at"]).map { Date(timeIntervalSince1970: $0) }
            x.cse = w["cse"] as? String ?? ""
            x.folder = w["cwd"] as? String ?? ""
            x.sessionURL = w["session_url"] as? String ?? ""
            x.url = w["url"] as? String ?? ""
            return x
        }.filter { !$0.back }.sorted(by: before)
    }

    /// The one order of waits everywhere: deadline, then when it was set, then the session's name, then the wait's id.
    /// The state keeps waits in a dictionary, which has no order of its own, so every key is needed for one fixed
    /// order: with fewer, two waits with the same deadline change places from one read to the next.
    static func before(_ a: Wait, _ b: Wait) -> Bool {
        (a.by ?? .distantFuture, a.setAt ?? .distantFuture, a.title, a.id) < (b.by ?? .distantFuture, b.setAt ?? .distantFuture, b.title, b.id)
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
}
