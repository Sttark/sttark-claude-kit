import AppKit
import ServiceManagement
import UserNotifications

/// Looks for a newer version on GitHub, says so once, and installs it in place with one click.
/// The state and the hooks live outside the app, so they stay as they are.
final class Updater: NSObject, UNUserNotificationCenterDelegate {
    static let repo = "Sttark/sttark-claude-kit"
    static let asset = "SttarkClaudeKit.zip"

    struct Release { let build: Int; let version: String; let url: URL }
    private(set) var available: Release?
    private(set) var installing = false
    private var lastCheck = Date.distantPast
    var changed: () -> Void = {}

    static var build: Int { Int(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "") ?? 0 }
    static var version: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?" }

    func start() {
        UNUserNotificationCenter.current().delegate = self
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { self.check() }
        Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in self?.check() }
    }

    /// Also called when the menu opens; at most once an hour unless asked.
    func check(force: Bool = false, done: ((String) -> Void)? = nil) {
        guard force || Date().timeIntervalSince(lastCheck) > 3600 else { return }
        lastCheck = Date()
        var req = URLRequest(url: URL(string: "https://api.github.com/repos/\(Self.repo)/releases/latest")!)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.timeoutInterval = 20
        URLSession.shared.dataTask(with: req) { data, _, _ in
            let j = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            let tag = (j?["tag_name"] as? String ?? "").trimmingCharacters(in: CharacterSet(charactersIn: "v"))
            let build = Int(tag.split(separator: ".").last ?? "") ?? 0
            let link = (j?["assets"] as? [[String: Any]] ?? []).first { $0["name"] as? String == Self.asset }?["browser_download_url"] as? String
            DispatchQueue.main.async {
                guard j != nil else { done?("Couldn't reach GitHub. Try again later."); return }
                if build > Self.build, let link, let url = URL(string: link) {
                    self.available = Release(build: build, version: tag, url: url)
                    self.notifyOnce()
                    done?("Version \(tag) is ready.")
                } else {
                    self.available = nil
                    done?("You have the latest version (\(Self.version)).")
                }
                self.changed()
            }
        }.resume()
    }

    private func notifyOnce() {
        guard let r = available, UserDefaults.standard.integer(forKey: "notifiedBuild") < r.build else { return }
        UserDefaults.standard.set(r.build, forKey: "notifiedBuild")
        let c = UNUserNotificationCenter.current()
        c.requestAuthorization(options: [.alert]) { ok, _ in
            guard ok else { return }
            let n = UNMutableNotificationContent()
            n.title = "Sttark Claude Kit \(r.version) is ready"
            n.body = "Click to update. It takes a few seconds and keeps your settings."
            c.add(UNNotificationRequest(identifier: "update", content: n, trigger: nil))
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        let id = response.notification.request.identifier
        let url = response.notification.request.content.userInfo["url"] as? String ?? ""
        DispatchQueue.main.async {
            if id.hasPrefix("login") { Login.signIn() } else if id.hasPrefix("waiting") { Waiting.open(url) } else { self.install() }
        }
        done()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner])
    }

    /// Download, check it's signed by us, swap it in where this copy sits, and start it.
    func install() {
        guard let r = available, !installing else { return }
        installing = true
        changed()
        note("update: downloading \(r.version)")
        URLSession.shared.downloadTask(with: r.url) { zip, _, error in
            let result: String? = {
                guard let zip else { return "The download failed: \(error?.localizedDescription ?? "no file")" }
                let fm = FileManager.default
                let tmp = fm.temporaryDirectory.appendingPathComponent("SttarkClaudeKit-update-\(r.build)")
                try? fm.removeItem(at: tmp)
                try? fm.createDirectory(at: tmp, withIntermediateDirectories: true)
                guard Self.run("/usr/bin/ditto", ["-x", "-k", zip.path, tmp.path]).0 == 0 else { return "Couldn't unpack the download." }
                let new = tmp.appendingPathComponent("SttarkClaudeKit.app")
                guard Self.signedLikeThisApp(new) else { return "The download isn't signed by Sttark, so it wasn't installed." }
                let here = URL(fileURLWithPath: Bundle.main.bundlePath)
                let old = tmp.appendingPathComponent("previous.app")
                do {
                    try fm.moveItem(at: here, to: old)
                    do { try fm.moveItem(at: new, to: here) } catch { try? fm.moveItem(at: old, to: here); throw error }
                } catch {
                    return "Couldn't replace the app in \(here.deletingLastPathComponent().path): \(error.localizedDescription)"
                }
                return nil
            }()
            DispatchQueue.main.async {
                if let result {
                    note("update failed: \(result)")
                    self.installing = false
                    self.changed()
                    let a = NSAlert()
                    a.messageText = "Update didn't install"
                    a.informativeText = result + "\n\nYou can also download it from github.com/\(Self.repo)/releases."
                    NSApp.activate(ignoringOtherApps: true)
                    a.runModal()
                    return
                }
                note("update: installed \(r.version), restarting")
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/bin/sh")
                p.arguments = ["-c", "sleep 1; /usr/bin/open \"$0\"", Bundle.main.bundlePath]
                try? p.run()
                NSApp.terminate(nil)
            }
        }.resume()
    }

    /// The new copy has to pass the same signature rule as this one (the Sttark certificate and this app's ID).
    /// A build made on someone's own Mac has no certificate, so for that one only a valid signature and the ID are checked.
    static func signedLikeThisApp(_ app: URL) -> Bool {
        let (_, out) = run("/usr/bin/codesign", ["-d", "-r-", Bundle.main.bundlePath])
        // a build without a certificate prints its rule as a comment: "# designated => cdhash …"
        guard let line = out.split(separator: "\n").map({ $0.hasPrefix("# ") ? $0.dropFirst(2) : $0 })
                .first(where: { $0.hasPrefix("designated => ") }) else { return false }
        let rule = line.dropFirst(14)
        let id = Bundle.main.bundleIdentifier ?? ""
        let req = rule.contains("cdhash") ? "identifier \"\(id)\"" : String(rule)
        return run("/usr/bin/codesign", ["--verify", "--deep", "--strict", "-R=" + req, app.path]).0 == 0
    }

    @discardableResult
    static func run(_ tool: String, _ args: [String]) -> (Int32, String) {
        let p = Process(), pipe = Pipe()
        p.executableURL = URL(fileURLWithPath: tool)
        p.arguments = args
        p.standardOutput = pipe
        p.standardError = pipe
        guard (try? p.run()) != nil else { return (-1, "") }
        let d = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return (p.terminationStatus, String(data: d, encoding: .utf8) ?? "")
    }
}
