import AppKit
import UserNotifications

/// Warns before the Claude Code login runs out, and starts the sign-in for you.
/// The login lasts about a month (the end date is in the Keychain item Claude Code keeps, "Claude Code-credentials").
/// When it runs out, or Claude Code clears it, every Claude Code session and the server stop working until you
/// sign in again. Only the end date and whether the login is there are read; the login itself never leaves the Keychain.
enum Login {
    struct Info { let ends: Date?; let signedIn: Bool }
    static let warnings: [(TimeInterval, String)] = [(3 * 86400, "3 days"), (86400, "1 day"), (2 * 3600, "2 hours")]

    static func read() -> Info? {
        let r = Updater.run("/usr/bin/security", ["find-generic-password", "-s", "Claude Code-credentials", "-w"])
        guard r.0 == 0, let d = try? JSONSerialization.jsonObject(with: Data(r.1.utf8)) as? [String: Any],
              let o = d["claudeAiOauth"] as? [String: Any] else { return nil }
        let ms = o["refreshTokenExpiresAt"] as? Double ?? 0
        let ends = ms > 0 ? Date(timeIntervalSince1970: ms / 1000) : nil
        let has = { (k: String) in !((o[k] as? String) ?? "").isEmpty }
        return Info(ends: ends, signedIn: has("accessToken") && has("refreshToken") && (ends.map { $0 > Date() } ?? true))
    }

    /// Text for the menu when the login needs attention soon; nil when it's fine.
    static var urgent: String? {
        guard let i = read() else { return nil }
        if !i.signedIn { return "Claude Code is signed out: Sign in…" }
        guard let ends = i.ends, ends.timeIntervalSinceNow < warnings[0].0 else { return nil }
        return "Claude login ends \(relative(ends)): Sign in…"
    }

    static var tip: String {
        guard let i = read() else { return "Opens Terminal and starts Claude Code's sign-in. You finish it in the browser." }
        if !i.signedIn { return "Claude Code is signed out, so sessions and the server can't run. Opens Terminal and starts the sign-in; you finish it in the browser." }
        let f = DateFormatter(); f.dateStyle = .medium; f.timeStyle = .short
        return "Your Claude Code login lasts until \(i.ends.map(f.string) ?? "an unknown date"). Signing in again starts a new month. Opens Terminal; you finish in the browser."
    }

    static func relative(_ d: Date) -> String {
        let s = d.timeIntervalSinceNow
        if s < 3600 { return "in \(max(1, Int(s / 60))) min" }
        if s < 86400 { return "in \(Int(s / 3600)) hr" }
        let f = DateFormatter(); f.dateFormat = "EEE h:mm a"
        return f.string(from: d)
    }

    /// Hourly: when the login is gone, or ends within a day, the Kit starts the sign-in itself (no notice asks for a step).
    static func check() {
        guard let i = read() else { return }
        let d = UserDefaults.standard
        let key = "loginWarned-\(Int(i.ends?.timeIntervalSince1970 ?? 0))"
        var done = Set(d.stringArray(forKey: key) ?? [])
        // No step for the person to take: the Kit starts Claude Code's own sign-in, which opens the sign-in page in
        // the browser by itself (at most once every 6 hours); the person only approves it there.
        if !i.signedIn {
            if !done.contains("out") { done.insert("out"); d.set(Array(done), forKey: key); note("login: signed out, sign-in started") }
            Server.Fix.signIn()
            return
        }
        guard let ends = i.ends else { return }
        if ends.timeIntervalSinceNow < warnings[1].0 {
            if !done.contains("renew") { done.insert("renew"); d.set(Array(done), forKey: key); note("login: ends \(relative(ends)), sign-in started") }
            Server.Fix.signIn(endsSoon: true)
        }
    }

    /// Opens Terminal with Claude Code's sign-in command. It opens the browser, where you finish.
    static func signIn() {
        let f = supportDir.appendingPathComponent("Sign in to Claude Code.command")
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let script = """
        #!/bin/zsh
        # Started from the Sttark Claude Kit menu: signs Claude Code in again. Finish the steps in the browser.
        "\(home)/.local/bin/claude" auth login
        echo
        echo "Done. You can close this window."
        """
        try? script.write(to: f, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: f.path)
        note("sign-in started")
        NSWorkspace.shared.open(f)
    }
}
