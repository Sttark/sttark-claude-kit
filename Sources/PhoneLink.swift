import AppKit
import CryptoKit
import Foundation
import Network
import Security

/// Kit on your phone, the link (phone/DESIGN.md, sections 2, 4, 5 and 6): the switch, this Mac's own key, linking the
/// Mac to the person's Sttark sign-in, and the one WebSocket the Kit keeps open to the server (`/mac` in
/// phone/asyncapi.yaml). What goes up is built in Phone.swift; an action that comes down runs in KitActions, the code
/// the window's buttons run. Main thread only, unless a function says otherwise.
///
/// - **Off:** nothing goes to the server. Turning it off tells the server to remove this Mac and drops the key.
/// - **On, not linked:** nothing goes up. One Mac notice, once; Link this Mac… in Settings. Only a click opens the
///   browser.
/// - **Linked:** the socket. On connect the server sends a challenge, the Kit signs it, and after `welcome` it sends
///   the whole snapshot, then each change (Phone.Feed). A ping every 25 seconds. After a drop it connects again at
///   once on wake or a network change, else after 1, 2, 4 … 60 seconds. `bye` before sleep, quit or an update.
///   4401 (removed on the phone) drops the key; 4403 (not on the roster) says why and tries again each hour.
/// - **Needs you reminders** (section 5): `welcome` and then each `phones` say how many of the person's phones can get a
///   push. Waiting.notifyDue asks `reminderPlace()` where a reminder goes: this Mac's notice when the person is at it
///   (`Presence`), else `remind` on the socket when it is up and a phone can get a push, else this Mac's notice. Never
///   both.
enum PhoneLink {
    // MARK: the server

    /// The server's address: the one place it is written. STTARK_PHONE_URL points the Kit at a local copy for tests.
    /// It may have a path (https://example.com/kit): the link API and the socket are under it. Nothing the Kit keeps
    /// names it (phone.json, the key), so a Mac linked at the server's first address, building.sttark.com/kit, keeps
    /// its link here: the same server, database and key.
    static let address = "https://kit.sttark.com"

    static var base: URL {
        let env = ProcessInfo.processInfo.environment["STTARK_PHONE_URL"] ?? ""
        if let u = URL(string: env), u.scheme == "http" || u.scheme == "https", u.host != nil { return u }
        return URL(string: address)!
    }

    /// The server as a person reads it: "kit.sttark.com", or "example.com/kit" for a path on another origin.
    static var shown: String {
        let b = base
        let path = b.path.hasSuffix("/") ? String(b.path.dropLast()) : b.path
        return (b.host ?? "") + (b.port.map { ":\($0)" } ?? "") + path
    }

    /// A path under the server, such as api/mac/link.
    static func url(_ path: String) -> URL { base.appendingPathComponent(path) }

    /// The socket: wss for https, ws for http (a local copy).
    static var socketURL: URL {
        var c = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        c.scheme = c.scheme == "https" ? "wss" : "ws"
        c.path = (c.path.hasSuffix("/") ? String(c.path.dropLast()) : c.path) + "/mac"
        c.query = nil
        c.fragment = nil
        return c.url!
    }

    // MARK: the switch

    /// On unless the person turned it off ("phone" in KitDefaults' turnedOff record). It sends nothing until the Mac
    /// is linked, and linking has its own notice, so it needs no "came on" notice.
    static var on: Bool { !KitDefaults.turnedOff("phone") }

    /// STTARK_PHONE_DRY=1: build each snapshot and log it, and connect to nothing.
    static var dry: Bool { ProcessInfo.processInfo.environment["STTARK_PHONE_DRY"] == "1" }

    // MARK: what the Kit keeps

    /// The link, in phone.json in the Kit's folder: this Mac's id and the kind of its key, the account it is linked
    /// to, and why it is not linked when the server said so. The key itself is never in it.
    struct Saved: Codable, Equatable {
        var mac: String?
        var kind: String?
        var email: String?
        var name: String?
        var linkedAt: Double?
        /// The person removed this Mac on the phone (4401): the key is gone, and the Kit does not link it again by itself.
        var removedAt: Double?
        /// Why the server does not take this Mac now (4403, or a Kit too old), in words for Settings.
        var refused: String?
        /// The link notice was shown. It shows once.
        var told: Bool?

        enum CodingKeys: String, CodingKey {
            case mac, kind, email, name, refused, told
            case linkedAt = "linked_at", removedAt = "removed_at"
        }

        var linked: Bool { mac != nil && email != nil && linkedAt != nil }
    }

    static var file: URL { supportDir.appendingPathComponent("phone.json") }
    private(set) static var saved = Saved()

    static func readSaved() -> Saved {
        guard let d = try? Data(contentsOf: file), let s = try? JSONDecoder().decode(Saved.self, from: d) else { return Saved() }
        return s
    }

    private static func save(_ edit: (inout Saved) -> Void) {
        var s = saved
        edit(&s)
        guard s != saved else { return }
        saved = s
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys, .prettyPrinted]
        if let d = try? enc.encode(s) { try? d.write(to: file, options: .atomic) }
    }

    // MARK: what Settings shows

    struct Status: Equatable {
        enum Stage: Equatable { case off, notLinked, linking, linked, removed, refused }
        var stage: Stage = .off
        /// The 4 letters the link page shows too, while a link page is open.
        var code: String?
        var email: String?
        var connected = false
        var lastSent: Date?
        /// Why it is not linked or not connected, in words, when something went wrong.
        var problem: String?
        var dry = false
        /// How many of the person's phones can get a push, as the server last said while connected.
        var phones: Int?

        /// The line under Kit on your phone.
        var words: String {
            let host = PhoneLink.shown
            switch stage {
            case .off: return "Nothing goes to \(host)."
            case .notLinked:
                if dry { return "Dry run: the Kit builds what it would send and logs it. Nothing goes to \(host)." }
                return problem ?? "Link this Mac with your Sttark sign-in to see your sessions on your phone."
            case .linking: return "Sign in on the link page, then click Link. If the page shows a code, it must be the same as this one."
            case .linked:
                var w = "Your sessions show at \(host), signed in as \(email ?? "your account")."
                if !connected, let p = problem { w += " Not connected: \(p). The Kit tries again by itself." }
                if let t = lastSent { w += " Last sent \(Limit.clock(t))." }
                return w
            case .removed: return "Removed from your phone. To see this Mac's sessions there again, link it again."
            case .refused: return problem ?? "\(host) does not take this Mac now."
            }
        }

        /// The words are a warning: something needs the person, or nothing goes up.
        var warn: Bool {
            switch stage {
            case .removed, .refused: return true
            case .notLinked: return problem != nil && !dry
            case .linked: return !connected && problem != nil
            default: return false
            }
        }

        /// Link this Mac… shows while the switch is on and the Mac is not linked.
        var canLink: Bool { [.notLinked, .linking, .removed].contains(stage) && !dry }

        /// The line on Needs you notices, while the Mac is linked; with what to do when the server says no phone gets
        /// them.
        var notices: String? {
            guard stage == .linked else { return nil }
            let line = "Needs you notices go to your phone when you are away from this Mac."
            return connected && phones == 0 ? line + " No phone gets them now: turn them on in Menu on your phone." : line
        }
    }

    private(set) static var status = Status()
    /// The window's model takes each new status (Menu.swift sets it).
    static var changed: (Status) -> Void = { _ in }
    /// A problem with the link now (the server did not answer, the link page expired), in words.
    private static var problem: String?

    private static func publish() {
        var s = Status()
        s.dry = dry
        if !on { s.stage = .off }
        else if page != nil { s.stage = .linking; s.code = page?.code }
        else if saved.linked { s.stage = saved.refused != nil ? .refused : .linked; s.email = saved.email }
        else if saved.removedAt != nil && problem == nil { s.stage = .removed }
        else { s.stage = .notLinked }
        s.connected = socket?.welcomed == true
        s.lastSent = lastSent
        s.phones = s.connected ? phones : nil
        s.problem = saved.refused ?? problem
        guard s != status else { return }
        status = s
        changed(s)
    }

    // MARK: this Mac's key

    /// This Mac's signing key: P-256 ECDSA over SHA-256, the signature in DER. Only the public half leaves the Mac.
    /// On a Mac with a Secure Enclave the key is made there and never leaves it: what the Kit saves is the Enclave's
    /// own wrapped form, useless on another Mac (phone-key.json in the Kit's folder, with a checksum, since CryptoKit
    /// stops the app on a damaged one). Other Macs keep the key in the Keychain, this device only. STTARK_PHONE_KEY
    /// points to a key file instead, for tests: the Keychain and the Enclave are never touched then.
    struct Key {
        /// Where the private half is: secure-enclave, keychain, or file (a test's).
        let kind: String
        /// The public key as SPKI DER, which the server keeps.
        let publicKey: Data
        let sign: (Data) throws -> Data

        /// As the server records it (link.v1.json): a test's key file is a software key, as in the Keychain.
        var serverKind: String { kind == "secure-enclave" ? "secure-enclave" : "keychain" }

        static var testFile: URL? {
            let p = ProcessInfo.processInfo.environment["STTARK_PHONE_KEY"] ?? ""
            return p.isEmpty ? nil : URL(fileURLWithPath: p)
        }
        static var enclaveFile: URL { supportDir.appendingPathComponent("phone-key.json") }
        static let service = "com.sttark.sttark-claude-kit.phone"

        private static func software(_ k: P256.Signing.PrivateKey, _ kind: String) -> Key {
            Key(kind: kind, publicKey: k.publicKey.derRepresentation, sign: { try k.signature(for: $0).derRepresentation })
        }

        private static func sum(_ d: Data) -> String { SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined() }

        /// A file only this user can read, written whole: a new file, then a rename over the old one.
        private static func write(_ d: Data, to u: URL) throws {
            let tmp = u.deletingLastPathComponent().appendingPathComponent("." + u.lastPathComponent + ".tmp")
            try? FileManager.default.removeItem(at: tmp)
            guard FileManager.default.createFile(atPath: tmp.path, contents: d, attributes: [.posixPermissions: 0o600]),
                  rename(tmp.path, u.path) == 0 else {
                try? FileManager.default.removeItem(at: tmp)
                throw CocoaError(.fileWriteUnknown)
            }
        }

        /// The key of this kind, when it is here and works on this Mac.
        static func load(_ kind: String?) -> Key? {
            if let f = testFile {
                guard kind == "file", let pem = try? String(contentsOf: f, encoding: .utf8),
                      let k = try? P256.Signing.PrivateKey(pemRepresentation: pem) else { return nil }
                return software(k, "file")
            }
            switch kind {
            case "secure-enclave":
                guard SecureEnclave.isAvailable, let d = try? Data(contentsOf: enclaveFile),
                      let j = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any],
                      let blob = (j["blob"] as? String).flatMap({ Data(base64Encoded: $0) }), j["sha256"] as? String == sum(blob),
                      let k = try? SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: blob),
                      (try? k.signature(for: Data("kit-mac-v1 key check".utf8))) != nil else { return nil }   // another Mac's
                return Key(kind: "secure-enclave", publicKey: k.publicKey.derRepresentation, sign: { try k.signature(for: $0).derRepresentation })
            case "keychain":
                var r: CFTypeRef?
                let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                        kSecAttrAccount as String: "key", kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
                guard SecItemCopyMatching(q as CFDictionary, &r) == errSecSuccess, let raw = r as? Data,
                      let k = try? P256.Signing.PrivateKey(rawRepresentation: raw) else { return nil }
                return software(k, "keychain")
            default:
                return nil
            }
        }

        static func make() throws -> Key {
            if let f = testFile {
                let k = P256.Signing.PrivateKey()
                try write(Data(k.pemRepresentation.utf8), to: f)
                return software(k, "file")
            }
            if SecureEnclave.isAvailable {
                var e: Unmanaged<CFError>?
                // usable while the screen is locked, from the first unlock after a restart: the Kit works when the person is away
                guard let ac = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly, .privateKeyUsage, &e) else {
                    throw e?.takeRetainedValue() ?? CocoaError(.featureUnsupported)
                }
                let k = try SecureEnclave.P256.Signing.PrivateKey(accessControl: ac)
                let blob = k.dataRepresentation
                try write(Phone.json(["v": 1, "blob": blob.base64EncodedString(), "sha256": sum(blob)]), to: enclaveFile)
                return Key(kind: "secure-enclave", publicKey: k.publicKey.derRepresentation, sign: { try k.signature(for: $0).derRepresentation })
            }
            let k = P256.Signing.PrivateKey()
            dropKeychain()
            let add: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                      kSecAttrAccount as String: "key", kSecAttrLabel as String: "Sttark Claude Kit: Kit on your phone",
                                      kSecValueData as String: k.rawRepresentation,
                                      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
            let r = SecItemAdd(add as CFDictionary, nil)
            guard r == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(r)) }
            return software(k, "keychain")
        }

        /// Drops the key of this kind. With STTARK_PHONE_KEY, only that file.
        static func drop(_ kind: String?) {
            if let f = testFile { try? FileManager.default.removeItem(at: f); return }
            try? FileManager.default.removeItem(at: enclaveFile)
            if kind == "keychain" { dropKeychain() }
        }

        private static func dropKeychain() {
            SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary)
        }
    }

    /// What the Mac signs to answer a challenge: "kit-mac-v1", its Mac id and the challenge, one per line.
    static func signed(mac: String, nonce: String) -> Data { Data("kit-mac-v1\n\(mac)\n\(nonce)".utf8) }

    /// A new random Mac id: "mac_" and 32 hex digits.
    static func newMacId() -> String {
        var b = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, b.count, &b)
        return "mac_" + b.map { String(format: "%02x", $0) }.joined()
    }

    // MARK: linking

    /// A link page the server made for this Mac: where the person signs in, the token the Kit polls with, and the 4
    /// letters both show. It works once, for 10 minutes.
    struct Page { let url: URL; let poll: String; let code: String; let until: Date }
    private(set) static var page: Page?
    private static var pollTimer: Timer?
    private static var polling = false
    private static var asking = false
    /// How the Kit opens a link page: in the browser, only from a person's click. Tests pass their own.
    static var openPage: (URL) -> Void = { NSWorkspace.shared.open($0) }

    /// Link this Mac… in Settings, or a click on the link notice: the Kit asks the server for a link page and opens it
    /// in the browser, then asks every 2 seconds whether the person linked it. A page that is still open opens again.
    /// The two calls are phone/schema/link.v1.json.
    /// `fromNotice`: a link page that cannot be had opens Settings, which says why, since nothing else shows.
    static func link(fromNotice: Bool = false) {
        guard on, !asking else { return }
        if let p = page, p.until.timeIntervalSinceNow > 30 { openPage(p.url); return }
        if dry { logLine("phone", "dry: would ask \(url("api/mac/link").absoluteString) for a link page"); return }
        ask(again: true, fromNotice: fromNotice)
    }

    /// POST api/mac/link with this Mac's id and the public half of its key, made now when there is none. A Mac id the
    /// server already knows (mac_taken) gets a new one, once.
    private static func ask(again: Bool, fromNotice: Bool) {
        var key = Key.load(saved.kind)
        if key == nil || saved.mac == nil {
            do {
                Key.drop(saved.kind)
                let k = try Key.make()
                key = k
                save { $0.mac = newMacId(); $0.kind = k.kind; $0.email = nil; $0.name = nil; $0.linkedAt = nil }
            } catch {
                problem = "This Mac could not make its key (\(error.localizedDescription))."
                logLine("phone", "link: no key: \(error.localizedDescription)")
                publish()
                return
            }
        }
        guard let k = key, let mac = saved.mac else { return }
        let m = Phone.Mac.current
        // the Claude Code login, when it is a Sttark one: Google's sign-in offers that account first
        let login = Reach.loginEmail.trimmingCharacters(in: .whitespaces).lowercased()
        let hint = login.hasSuffix("@sttark.com") && login.count <= 254 && !login.contains(" ") && login.filter({ $0 == "@" }).count == 1
        let body: [String: Any] = ["v": 1, "mac": mac, "name": Phone.cut(m.name, 80).nilIfEmpty ?? "Mac",
                                   "kit": Phone.versionLike(m.kit) ? m.kit : "0",
                                   "key": k.publicKey.base64EncodedString(), "kind": k.serverKind,
                                   "hint": hint ? login : NSNull()]
        var req = URLRequest(url: url("api/mac/link"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Phone.json(body)
        req.timeoutInterval = 20
        asking = true
        problem = nil
        publish()
        URLSession.shared.dataTask(with: req) { data, resp, err in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let j = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            DispatchQueue.main.async {
                asking = false
                guard on else { return }
                if code == 409, j?["error"] as? String == "mac_taken", again {
                    save { $0.mac = newMacId() }   // the same key, a new id
                    ask(again: false, fromNotice: fromNotice)
                    return
                }
                guard code == 200 || code == 201, let j, let p = Self.page(from: j) else {
                    let why = err.map(words) ?? (code == 429 ? "too many link pages were asked from this network; try again in 10 minutes"
                        : (j?["words"] as? String) ?? (code == 0 ? "no answer" : "it answered \(code)"))
                    problem = "Could not get a link page from \(shown): \(why)."
                    logLine("phone", "link: no page from \(shown): \(why)")
                    publish()
                    if fromNotice { NotificationCenter.default.post(name: .init("kitOpenSettings"), object: nil) }
                    return
                }
                page = p
                logLine("phone", "link page opened, code \(p.code), until \(Limit.clock(p.until))")
                publish()
                openPage(p.url)
                pollTimer?.invalidate()
                pollTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in poll() }
            }
        }.resume()
    }

    /// The server's answer to POST api/mac/link: the link page (on the server's own host, never another site), the
    /// poll token, the code and when the page ends.
    static func page(from j: [String: Any]) -> Page? {
        guard let raw = j["link"] as? String, let u = URL(string: raw), u.scheme == "https" || u.scheme == "http", u.host == base.host,
              let poll = j["poll"] as? String, (16...200).contains(poll.count), poll.allSatisfy(Phone.idChars.contains),
              let code = j["code"] as? String, (1...12).contains(code.count), code.allSatisfy({ $0.isLetter || $0.isNumber }) else { return nil }
        let until = Limit.num(j["expires_at"]).map { Date(timeIntervalSince1970: $0) } ?? Date().addingTimeInterval(600)
        return Page(url: u, poll: poll, code: code, until: until)
    }

    /// Every 2 seconds while a link page is open: has the person linked this Mac?
    private static func poll() {
        guard on, let p = page else { endPage(); return }
        if p.until < Date() {
            endPage()
            problem = "The link page ended before you linked this Mac. Click Link this Mac… to try again."
            logLine("phone", "link page ended, not linked")
            publish()
            return
        }
        guard !polling else { return }
        polling = true
        var req = URLRequest(url: url("api/mac/link/" + p.poll))
        req.timeoutInterval = 10
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let j = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            DispatchQueue.main.async {
                polling = false
                guard on, page?.poll == p.poll else { return }
                let state = j?["status"] as? String ?? (code == 404 || code == 410 ? "expired" : "")
                switch state {
                case "linked":
                    guard let email = j?["email"] as? String, !email.isEmpty else { return }
                    endPage()
                    save { s in
                        s.email = email
                        s.name = j?["name"] as? String
                        s.linkedAt = Date().timeIntervalSince1970
                        s.removedAt = nil
                        s.refused = nil
                    }
                    problem = nil
                    logLine("phone", "linked to \(email)")
                    publish()
                    backoff = 0
                    connect()
                case "expired":
                    endPage()
                    problem = "The link page ended before you linked this Mac. Click Link this Mac… to try again."
                    logLine("phone", "link page ended, not linked")
                    publish()
                default:
                    break   // waiting, or the server did not answer: ask again in 2 seconds
                }
            }
        }.resume()
    }

    private static func endPage() {
        pollTimer?.invalidate()
        pollTimer = nil
        page = nil
    }

    // MARK: the socket

    /// One connection to /mac. URLSession calls back on its own queue; each callback goes to the main thread, and one
    /// from a connection that is no longer the current one is dropped.
    final class Socket: NSObject, URLSessionWebSocketDelegate {
        let key: Key
        let mac: String
        private var session: URLSession?
        private var task: URLSessionWebSocketTask?
        var welcomed = false
        var welcomedAt: Date?
        var startedAt = Date()
        var pingOut: Date?
        var ended = false

        init(url: URL, key: Key, mac: String) {
            self.key = key
            self.mac = mac
            super.init()
            let cfg = URLSessionConfiguration.ephemeral
            cfg.waitsForConnectivity = false
            let s = URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
            let t = s.webSocketTask(with: url)
            t.maximumMessageSize = 1 << 20
            session = s
            task = t
        }

        func start() {
            task?.resume()
            receive()
        }

        private func receive() {
            task?.receive { [weak self] r in
                guard let self else { return }
                switch r {
                case .success(let m):
                    var text: String?
                    switch m {
                    case .string(let s): text = s
                    case .data(let d): text = String(data: d, encoding: .utf8)
                    @unknown default: text = nil
                    }
                    DispatchQueue.main.async { PhoneLink.received(text ?? "", on: self) }
                    self.receive()
                case .failure(let e):
                    let code = self.task?.closeCode.rawValue ?? 0
                    let reason = self.task?.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                    DispatchQueue.main.async { PhoneLink.ended(self, code: code, why: reason.isEmpty ? PhoneLink.words(e) : reason) }
                }
            }
        }

        /// One message, `{event, success, payload}`, as JSON with sorted keys.
        func send(_ event: String, _ payload: [String: Any], success: Bool = true, done: ((Error?) -> Void)? = nil) {
            let text = String(data: Phone.json(["event": event, "success": success, "payload": payload]), encoding: .utf8) ?? "{}"
            guard let task else { done?(CocoaError(.featureUnsupported)); return }
            task.send(.string(text)) { e in done?(e) }
        }

        func ping() {
            guard pingOut == nil, let task else { return }
            pingOut = Date()
            task.sendPing { [weak self] e in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if let e { PhoneLink.ended(self, code: 0, why: PhoneLink.words(e)) } else { self.pingOut = nil }
                }
            }
        }

        func close(_ code: URLSessionWebSocketTask.CloseCode = .normalClosure) {
            task?.cancel(with: code, reason: nil)
            session?.invalidateAndCancel()
            task = nil
            session = nil
        }

        func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith code: URLSessionWebSocketTask.CloseCode, reason: Data?) {
            let why = reason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
            DispatchQueue.main.async { PhoneLink.ended(self, code: code.rawValue, why: why.isEmpty ? "closed" : why) }
        }

        func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
            let code = (task as? URLSessionWebSocketTask)?.closeCode.rawValue ?? 0
            let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
            let why = status != 0 && status != 101 ? "\(PhoneLink.shown) answered \(status)" : error.map(PhoneLink.words) ?? "closed"
            DispatchQueue.main.async { PhoneLink.ended(self, code: code, why: why) }
        }
    }

    private(set) static var socket: Socket?
    /// Seconds before the next try; 0 tries at once. 1, 2, 4 … 60 after each failed try.
    private(set) static var backoff: TimeInterval = 0
    private static var retry: DispatchWorkItem?
    private static var asleep = false
    private static var feed: Phone.Feed?
    /// The archived list the server holds, as the Kit last sent it, so a change goes up as archived_delta.
    private static var held: Phone.ArchivedList?
    /// A phone page of the person is visible: the Kit reads the Claude app's session list every 10 seconds.
    private(set) static var watching = false
    private(set) static var lastSent: Date?
    /// Why the Kit sends bye when it quits: "update" while it restarts for an update.
    private static var byeWhy = "quit"
    /// Turning the switch off: the connection that tells the server to remove this Mac.
    private static var unlinking: (() -> Void)?
    /// The last reason a try failed, so the log gets each new reason once, not every try.
    private static var lastFail = ""
    private static var fails = 0
    private static var started = false
    private static var path: NWPathMonitor?
    private static var pathSeen = false

    /// Connects now, when the switch is on, the Mac is linked and nothing stops it. Each new connection starts fresh.
    static func connect() {
        retry?.cancel()
        retry = nil
        guard on || unlinking != nil, !dry, !asleep, socket == nil, saved.linked, let mac = saved.mac else { return }
        guard let key = Key.load(saved.kind) else {
            // the key did not come with the Mac's files (a new Mac), or it is gone: link again
            logLine("phone", "this Mac's key is gone or does not work here: link it again")
            Key.drop(saved.kind)
            save { s in s.mac = nil; s.kind = nil; s.email = nil; s.name = nil; s.linkedAt = nil }
            problem = "This Mac's key is gone, so it is not linked now. Click Link this Mac… to link it again."
            unlinking?()
            publish()
            return
        }
        let s = Socket(url: socketURL, key: key, mac: mac)
        socket = s
        s.start()
        // no welcome in 20 seconds: try again
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak s] in
            guard let s, socket === s, !s.welcomed else { return }
            ended(s, code: 0, why: "no answer in 20 seconds")
        }
    }

    /// One message from the server.
    static func received(_ text: String, on s: Socket) {
        guard socket === s, !s.ended else { return }
        guard let m = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any], let event = m["event"] as? String else {
            logLine("phone", "a message the Kit cannot read came from the server")
            return
        }
        let p = m["payload"] as? [String: Any] ?? [:]
        switch event {
        case "challenge":
            guard let nonce = p["nonce"] as? String, (16...128).contains(nonce.count), nonce.allSatisfy(Phone.idChars.contains) else {
                ended(s, code: 0, why: "the server's challenge was not right")
                return
            }
            do {
                let sig = try s.key.sign(signed(mac: s.mac, nonce: nonce)).base64EncodedString()
                let kit = Phone.versionLike(Updater.version) ? Updater.version : "0"
                s.send("auth", ["mac": s.mac, "sig": sig, "kit": kit])
            } catch {
                ended(s, code: 0, why: "this Mac's key did not sign: \(error.localizedDescription)")
            }
        case "welcome":
            s.welcomed = true
            s.welcomedAt = Date()
            problem = nil
            if saved.refused != nil { save { $0.refused = nil } }
            logLine("phone", "connected to \(shown)" + (fails > 0 ? " after \(fails) tr\(fails == 1 ? "y" : "ies")" : ""))
            fails = 0
            lastFail = ""
            if let done = unlinking {
                s.send("unlink", [:]) { _ in DispatchQueue.main.async { done() } }
                return
            }
            setWatching(p["watching"] as? Bool ?? false)
            setPhones(p["phones"])
            feed?.stop()
            let f = Phone.Feed(send: { send($0) })
            feed = f
            f.start()
            publish()
        case "watching":
            setWatching(p["on"] as? Bool ?? false)
        case "phones":
            setPhones(p["phones"])
        case "want_archived":
            sendArchived(have: p["have"] as? String)
        case "want_usage":
            // a phone shows the Usage tab with this period: the list after a scan of what the records gained
            let key = p["period"] as? String ?? ""
            guard SessionUsage.Period(key: key) != nil else {
                logLine("phone", "the server asked for a usage list of a period the Kit does not know")
                return
            }
            SessionUsage.refresh(olderThan: 60) {
                guard socket === s, s.welcomed, let payload = Phone.usage(period: key) else { return }
                s.send("usage", payload)
            }
        case "action":
            act(p) { reply in
                guard socket === s, s.welcomed else { return }
                s.send("result", reply["payload"] as? [String: Any] ?? [:], success: reply["success"] as? Bool ?? false)
                feed?.sendNext()   // the phone draws the truth after each action
            }
        case "error":
            let code = p["code"] as? String ?? "?", why = p["words"] as? String ?? ""
            logLine("phone", "the server refused a message: \(code)" + (why.isEmpty ? "" : ": \(why)"))
            if code == "old_version" {
                save { $0.refused = tooOld }
                publish()
            }
        default:
            break   // a message a newer server sends: nothing to do
        }
    }

    /// The connection ended: by the server (4401 removed, 4403 not on the roster), a drop, or the Kit itself.
    static func ended(_ s: Socket, code: Int, why: String) {
        guard !s.ended else { return }
        s.ended = true
        s.close()
        guard socket === s else { return }
        socket = nil
        feed?.stop()
        feed = nil
        setWatching(false)
        if let done = unlinking { done(); return }
        let lasted = s.welcomedAt.map { -$0.timeIntervalSinceNow } ?? 0
        if lasted > 30 { backoff = 0 }
        switch code {
        case 4401:
            logLine("phone", "removed from your phone (4401): the Kit dropped this Mac's key and does not link it again by itself")
            Key.drop(saved.kind)
            save { st in
                st.mac = nil; st.kind = nil; st.email = nil; st.name = nil; st.linkedAt = nil; st.refused = nil
                st.removedAt = Date().timeIntervalSince1970
            }
            problem = nil
            publish()
        case 4403:
            logLine("phone", "refused (4403): your account is not on the Sttark roster; the Kit tries again in an hour")
            save { $0.refused = notOnRoster }
            publish()
            schedule(after: 3600)
        case 4409:
            // another copy of the Kit with this Mac's key connected after this one: do not take it back every second
            problem = "another copy of the Kit on this Mac is connected"
            logLine("phone", "not connected: another copy of the Kit on this Mac took over the connection; the Kit tries again in a minute")
            publish()
            schedule(after: 60)
        default:
            problem = why
            fails += 1
            if why != lastFail { logLine("phone", "not connected: \(why); the Kit tries again") }
            lastFail = why
            publish()
            if saved.refused == tooOld { schedule(after: 3600) } else { later() }
        }
    }

    /// The next try after a drop: 1, 2, 4 … 60 seconds.
    private static func later() {
        backoff = backoff == 0 ? 1 : min(60, backoff * 2)
        schedule(after: backoff)
    }

    private static func schedule(after secs: TimeInterval) {
        retry?.cancel()
        let w = DispatchWorkItem { connect() }
        retry = w
        DispatchQueue.main.asyncAfter(deadline: .now() + secs, execute: w)
    }

    /// Now, not after the wait: on wake, a network change, or a new link.
    static func connectNow() {
        backoff = 0
        if socket == nil { connect() }
    }

    /// `welcome`'s and `phones`' count of the person's phones that can get a push. A change is logged.
    private static func setPhones(_ v: Any?) {
        guard let n = Limit.num(v).map({ Int($0) }), (0...50).contains(n) else { return }
        guard n != phones else { return }
        phones = n
        logLine("phone", "phones that get notices: \(n)")
        publish()
    }

    private static func setWatching(_ on: Bool) {
        guard on != watching else { return }
        watching = on
        if on { Sync.readList(minGap: 3) }
    }

    /// A snapshot the feed let go: first the archived list's changes when the server holds a list, so the snapshot's
    /// archived_rev names a list the server has.
    private static func send(_ p: [String: Any]) {
        if dry {
            let rows = (p["rows"] as? [Any])?.count ?? 0
            logLine("phone", "dry: snapshot with \(rows) row\(rows == 1 ? "" : "s"), \(Phone.json(p).count) bytes, sent nowhere")
            lastSent = Date()
            publish()
            return
        }
        guard let s = socket, s.welcomed else { return }
        if let h = held, let list = Phone.archived(), let d = Phone.archivedDelta(from: h, to: list) {
            s.send("archived_delta", d)
            held = list
        }
        s.send("snapshot", p)
        lastSent = Date()
        publish()
    }

    /// want_archived: the changes from the list the server has (`have`), else the whole list.
    private static func sendArchived(have: String?) {
        guard let s = socket, s.welcomed else { return }
        let list = Phone.archived() ?? Phone.ArchivedList()
        if let h = held, let have, have == h.rev, let d = Phone.archivedDelta(from: h, to: list) {
            s.send("archived_delta", d)
        } else {
            s.send("archived", Phone.archivedPayload(list))
        }
        held = list
    }

    // MARK: actions from the phone

    /// The words for each action in the log and on the Events page.
    static let acts = ["bring_back", "stop_waits", "set_level", "set_auto", "set_limit", "unarchive"]

    /// One action from the phone (server_to_mac.action): only the six the contract names, each run by its KitActions
    /// function with the origin phone. That function reads the state again when it runs, runs off the main thread,
    /// and answers on it. `reply` gets the whole result message; a `phone` line in the log says who asked and how it went.
    static func act(_ p: [String: Any], reply: @escaping ([String: Any]) -> Void) {
        guard let id = Phone.id(p["id"] as? String) else {
            logLine("phone", "an action with no id came from the server: nothing was run")
            return
        }
        let act = p["act"] as? String ?? ""
        let args = p["args"] as? [String: Any] ?? [:]
        let by = Phone.cut((p["by"] as? [String: Any])?["email"] as? String ?? "", 120).nilIfEmpty ?? "someone"
        var session = Phone.id(args["cse"] as? String) ?? ""
        func done(_ r: KitActions.Result) {
            let words = Phone.cut(safeWords(r.words))
            logLine("phone", "action \(acts.contains(act) ? act : "unknown") \(session.isEmpty ? "-" : session) by \(by): \(r.reason.rawValue): \(words)")
            var payload = r.json
            payload["id"] = id
            payload["words"] = words
            payload["before"] = r.before.map { values($0) } ?? NSNull()
            payload["after"] = r.after.map { values($0) } ?? NSNull()
            reply(["event": "result", "success": r.reason == .ok, "payload": payload])
        }
        func bad() { done(KitActions.Result(reason: .bad, words: KitActions.Words.bad)) }
        func waitSession(_ ids: [String]) -> String {
            let open = Waits.list()
            return open.first { ids.contains($0.id) }.map { $0.cse.isEmpty ? $0.id : $0.cse } ?? ids.first ?? ""
        }
        switch act {
        case "bring_back":
            guard let w = Phone.id(args["wait"] as? String) else { return bad() }
            session = waitSession([w])
            KitActions.bringBack(wait: w, origin: .phone, done: done)
        case "stop_waits":
            guard let raw = args["waits"] as? [Any], (1...20).contains(raw.count) else { return bad() }
            let ids = raw.compactMap { Phone.id($0 as? String) }
            guard ids.count == raw.count else { return bad() }
            session = waitSession(ids)
            KitActions.stopWaits(ids, origin: .phone, done: done)
        case "set_level":
            guard !session.isEmpty, let level = args["level"] as? String, Phone.levels.contains(level) else { return bad() }
            KitActions.setLevel(cse: session, level: level, origin: .phone, done: done)
        case "set_auto":
            guard !session.isEmpty, let on = strictBool(args["on"]) else { return bad() }
            KitActions.setAuto(cse: session, on: on, origin: .phone, done: done)
        case "set_limit":
            guard !session.isEmpty else { return bad() }
            var sid: String?
            if let s = args["sid"] as? String {
                guard let ok = Phone.id(s, max: 64, chars: Phone.sidChars) else { return bad() }
                sid = ok
            } else if !(args["sid"] is NSNull || args["sid"] == nil) { return bad() }
            let at = Limit.num(args["at"]).map { Int($0) }
            let mode: Limit.Mode
            switch args["mode"] as? String {
            case "follow": mode = .follow
            case "credits": mode = .credits
            case "hold":
                guard let n = at, (1...100).contains(n) else { return bad() }
                mode = .hold(n)
            default: return bad()
            }
            KitActions.setLimit(cse: session, sid: sid, mode: mode, origin: .phone, done: done)
        case "unarchive":
            guard !session.isEmpty else { return bad() }
            KitActions.unarchive(cse: session, origin: .phone, done: done)
        default:
            bad()
        }
    }

    /// A result's words with any file or folder path taken out: a hook's error text can name one, and a path never
    /// leaves the Mac (phone/DESIGN.md, section 3).
    static func safeWords(_ s: String) -> String {
        s.replacingOccurrences(of: #"(~|/(Users|private|var|tmp|Volumes|opt|Library|System|Applications|home))/[^\s'"),;]*"#,
                               with: "a file on this Mac", options: .regularExpression)
    }

    /// The schema's `state`: only the fields that apply, each as it allows (at most 20 waits, ids only).
    static func values(_ v: KitActions.Values) -> [String: Any] {
        var j = v.json
        if let w = v.waits { j["waits"] = Array(w.compactMap { Phone.id($0) }.prefix(20)) }
        if let l = v.level, !Phone.levels.contains(l) { j.removeValue(forKey: "level") }
        return j
    }

    /// true or false as JSON has it, never a number.
    static func strictBool(_ v: Any?) -> Bool? {
        guard let n = v as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return nil }
        return n.boolValue
    }

    // MARK: Needs you reminders

    /// How many of the person's phones can get a push: `welcome`'s `phones`, then each `phones` message.
    private(set) static var phones = 0

    /// Where a Needs you reminder goes (phone/DESIGN.md section 5).
    enum Place: String { case mac, phone }

    /// "No double notices", rule 3: this Mac's notice when the person is at the Mac; else the phone, when the socket
    /// is up and a phone of theirs can get a push; else this Mac's notice, as before there was a phone. Never both.
    static func place(atMac: Bool, connected: Bool, phones: Int) -> Place {
        !atMac && connected && phones > 0 ? .phone : .mac
    }

    /// Is the person at this Mac now (Presence.atMac)? Tests put their own.
    static var atMac: () -> Bool = { Presence.atMac() }

    /// Where a reminder due now goes.
    static func reminderPlace() -> Place {
        place(atMac: atMac(), connected: !dry && socket?.welcomed == true, phones: phones)
    }

    /// One `remind` per session (mac_to_server.remind): the server sends a push to each of the person's phones with
    /// notices on, unless a page of theirs shows or it sent that one already. `done` gets, on the main thread, the
    /// sessions whose message did not go, for this Mac's notice instead.
    static func remind(_ list: [Session], done: @escaping ([Session]) -> Void) {
        guard !dry, let s = socket, s.welcomed else { done(list); return }
        var failed: [Session] = []
        let group = DispatchGroup()
        for x in list {
            guard let cse = Phone.id(x.id), let since = Phone.time(x.waitingSince) as? Int else { failed.append(x); continue }
            group.enter()
            s.send("remind", ["cse": cse, "waiting_since": since, "title": Phone.cut(x.title), "why": Phone.label(x.why)]) { e in
                DispatchQueue.main.async {
                    if e != nil { failed.append(x) }
                    group.leave()
                }
            }
        }
        group.notify(queue: .main) { done(failed) }
    }

    // MARK: start, the switch, sleep and quit

    /// At launch (Menu.swift): reads the link, starts the socket when the Mac is linked, and shows the link notice
    /// once when it is not. Watches sleep, wake, the network and quit.
    static func start() {
        guard !started else { return }
        started = true
        saved = readSaved()
        let ws = NSWorkspace.shared.notificationCenter
        ws.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { _ in sleep() }
        ws.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in
            asleep = false
            connectNow()
        }
        let nc = NotificationCenter.default
        nc.addObserver(forName: NSApplication.willTerminateNotification, object: nil, queue: .main) { _ in bye(byeWhy) }
        nc.addObserver(forName: .init("kitWillUpdate"), object: nil, queue: .main) { _ in byeWhy = "update" }
        nc.addObserver(forName: .init("kitPhoneLink"), object: nil, queue: .main) { _ in link(fromNotice: true) }
        let m = NWPathMonitor()
        m.pathUpdateHandler = { p in
            let up = p.status == .satisfied
            DispatchQueue.main.async { networkChanged(up: up) }
        }
        m.start(queue: DispatchQueue(label: "phone-path"))
        path = m
        Timer.scheduledTimer(withTimeInterval: 25, repeats: true) { _ in keepAlive() }
        publish()
        guard on else { return }
        if dry { startDry(); return }
        if saved.linked { connect() }
        else if saved.told != true, saved.removedAt == nil, !KitDefaults.test, Bundle.main.bundleIdentifier != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 90) { tellOnce() }
        }
    }

    /// The one Mac notice: a click starts linking (Update.swift sends it here as kitPhoneLink).
    private static func tellOnce() {
        guard on, !saved.linked, saved.told != true, saved.removedAt == nil else { return }
        save { $0.told = true }
        Updater.post("phone-link", "Use the Kit on your phone", "Click to link this Mac with your Sttark sign-in.")
        logLine("phone", "notice: use the Kit on your phone")
    }

    /// STTARK_PHONE_DRY: the feed builds and logs each snapshot it would send.
    private static func startDry() {
        logLine("phone", "dry: builds and logs each snapshot, connects to nothing")
        let f = Phone.Feed(send: { send($0) })
        feed = f
        f.start()
        publish()
    }

    /// Every 25 seconds: a ping keeps the socket and the router's mapping open. No pong in 15 seconds ends the
    /// connection, and the Kit connects again.
    private static func keepAlive() {
        guard let s = socket, s.welcomed else { return }
        if let out = s.pingOut {
            if -out.timeIntervalSinceNow > 15 { ended(s, code: 0, why: "no answer to a ping") }
            return
        }
        s.ping()
    }

    /// The network changed: connect at once when the Kit is not connected; when it is, check the connection with a ping.
    static func networkChanged(up: Bool) {
        let first = !pathSeen
        pathSeen = true
        guard !first, up, on, saved.linked, !dry, !asleep else { return }
        if let s = socket {
            guard s.welcomed else { return }
            s.ping()
            DispatchQueue.main.asyncAfter(deadline: .now() + 6) {
                if socket === s, let out = s.pingOut, -out.timeIntervalSinceNow >= 5 { ended(s, code: 0, why: "the network changed") }
            }
        } else {
            connectNow()
        }
    }

    /// Before sleep: bye, then the socket closes until the Mac wakes. A connection not yet welcomed just closes.
    private static func sleep() {
        asleep = true
        retry?.cancel()
        retry = nil
        guard let s = socket else { return }
        if s.welcomed { bye("sleep"); return }
        s.ended = true
        s.close()
        socket = nil
        publish()
    }

    /// bye with why (sleep, quit or update), then the socket closes. Waits up to a second for the message to go,
    /// since the Mac sleeps or the app ends right after.
    static func bye(_ why: String) {
        guard let s = socket, s.welcomed else { return }
        let sem = DispatchSemaphore(value: 0)
        s.send("bye", ["why": why]) { _ in sem.signal() }
        _ = sem.wait(timeout: .now() + 1)
        logLine("phone", "bye: \(why)")
        s.ended = true
        s.close(.goingAway)
        socket = nil
        feed?.stop()
        feed = nil
        setWatching(false)
        publish()
    }

    /// Kit on your phone in Settings. Off tells the server to remove this Mac (when it can reach it in 10 seconds),
    /// drops the key and records the choice; on clears it, and the Mac links when the person clicks Link this Mac….
    static func set(_ want: Bool) {
        guard want != on else { return }
        KitDefaults.chose("phone", on: want)
        if want {
            save { $0.removedAt = nil; $0.refused = nil }
            problem = nil
            publish()
            if dry { startDry() }
            return
        }
        endPage()
        retry?.cancel()
        retry = nil
        var finished = false
        let finish = {
            guard !finished else { return }
            finished = true
            unlinking = nil
            if let s = socket { s.ended = true; s.close(); socket = nil }
            feed?.stop()
            feed = nil
            setWatching(false)
            Key.drop(saved.kind)
            let was = saved.email
            save { s in s.mac = nil; s.kind = nil; s.email = nil; s.name = nil; s.linkedAt = nil; s.refused = nil }
            problem = nil
            lastSent = nil
            logLine("phone", "turned off: " + (was.map { "this Mac is unlinked from \($0) and its key dropped" } ?? "nothing goes to the server"))
            publish()
        }
        guard saved.linked, !dry else { finish(); return }
        unlinking = finish
        DispatchQueue.main.asyncAfter(deadline: .now() + 10, execute: finish)
        if let s = socket, s.welcomed {
            s.send("unlink", [:]) { _ in DispatchQueue.main.async { finish() } }
        } else if socket == nil {
            connect()   // just to send unlink
        }
    }

    /// `SttarkClaudeKit --phone-unlink`, which uninstall.sh runs: tells the server to remove this Mac when it can reach
    /// it in 10 seconds, drops the key, and quits. It never starts the menu bar app.
    static func unlinkAndQuit() -> Never {
        saved = readSaved()
        let was = saved.email
        var done = false
        if saved.linked, !dry {
            unlinking = { done = true }
            connect()
            let end = Date().addingTimeInterval(10)
            while !done && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.1)) }
            unlinking = nil
            socket?.close()
        }
        Key.drop(saved.kind)
        save { s in s.mac = nil; s.kind = nil; s.email = nil; s.name = nil; s.linkedAt = nil; s.refused = nil }
        if let was { logLine("phone", "turned off: this Mac is unlinked from \(was) and its key dropped (uninstall)") }
        exit(0)
    }

    /// Settings' words when the server does not take this Mac: its person is not on the roster (4403), or this Kit
    /// is older than the server takes (old_version).
    static var notOnRoster: String { "Your account is not on the Sttark roster, so \(shown) does not take this Mac. The Kit tries again each hour." }
    static var tooOld: String { "This Kit is too old for \(shown). It updates by itself, then connects again." }

    /// Plain words for a network error.
    static func words(_ e: Error) -> String {
        guard let u = e as? URLError else { return e.localizedDescription }
        switch u.code {
        case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed: return "no network"
        case .cannotFindHost, .dnsLookupFailed: return "\(shown) was not found"
        case .cannotConnectToHost: return "\(shown) did not answer"
        case .timedOut: return "no answer in time"
        case .secureConnectionFailed, .serverCertificateUntrusted, .serverCertificateHasBadDate: return "the secure connection failed"
        case .badServerResponse: return "\(shown) did not take the connection"
        default: return u.localizedDescription
        }
    }
}

/// Whether the person is at this Mac, for where a Needs you reminder goes (phone/DESIGN.md section 5, rule 3): the
/// screen is on and unlocked, this login is the one on the screen, and a key, the mouse or the trackpad was used in the
/// last 2 minutes. Read when a reminder is due; it needs no permission.
enum Presence {
    static let recent: TimeInterval = 2 * 60

    static func atMac() -> Bool {
        let s = CGSessionCopyCurrentDictionary() as? [String: Any] ?? [:]
        if s["CGSSessionScreenIsLocked"] as? Bool == true { return false }
        if s[kCGSessionOnConsoleKey as String] as? Bool == false { return false }
        if CGDisplayIsAsleep(CGMainDisplayID()) != 0 { return false }
        guard let any = CGEventType(rawValue: ~0) else { return false }
        return CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: any) < recent
    }
}
