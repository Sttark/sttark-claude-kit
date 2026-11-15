// Tests what the Kit sends to the phone (Sources/Phone.swift) on a temporary STTARK_KIT_DIR and log, never the real
// ones. The sample state has every group the phone shows, waits of each kind, three holds (one with an agent), two
// agents in the background, idle and On this Mac only sessions (which stay on the Mac), and archived sessions.
// Marker words are planted in transcripts, prompts, replies, file and folder paths, wait targets, check scripts and
// their output, check-prompt questions, the log and the Reach me by settings; the test fails if any shows in a payload.
// Every payload is checked against phone/schema with the contract's own check (node phone/schema/check.mjs). The
// snapshot, the archived list and a delta are written to phone/fixtures/from-mac/ for the server and the pages, with
// the times moved to a fixed day, so the files change only when the builder does. It also tests when the Kit sends:
// the pacer with a made-up clock, and the feed on real writes to the state.
// Needs Node. Run from the repo root:
//   swiftc -parse-as-library -o /tmp/phone-test tools/phone-test.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/phone-test
import Foundation

@main struct PhoneTest {
    static var fails = 0
    static func check(_ name: String, _ ok: Bool) { print((ok ? "ok   " : "FAIL ") + name); if !ok { fails += 1 } }

    /// Planted in places that must never leave the Mac.
    static let markers = ["PROMPTMARK", "REPLYMARK", "TRANSCRIPTMARK", "PATHMARK", "TARGETMARK", "SCRIPTMARK", "OUTPUTMARK",
                          "QUESTIONMARK", "REACHMARK", "SUBJECTMARK", "FAILMARK", "DOINGMARK", "SNIPPETMARK", "LOGMARK",
                          "IDLEMARK", "LOCALMARK", "NOTEMARK"]
    /// The day the fixtures' times are moved to (the contract's own fixtures use it too).
    static let fixtureNow = 1_794_587_400

    static func main() {
        let fm = FileManager.default
        guard fm.fileExists(atPath: "phone/schema/check.mjs") else { print("Run from the repo root."); exit(2) }
        let dir = fm.temporaryDirectory.appendingPathComponent("kit-phonetest-\(getpid())")
        let kit = dir.appendingPathComponent("kit")
        try? fm.createDirectory(at: kit, withIntermediateDirectories: true)
        setenv("STTARK_KIT_DIR", kit.path, 1)
        setenv("STTARK_KIT_LOG", dir.appendingPathComponent("log").path, 1)
        let now = Int(Date().timeIntervalSince1970)
        let mac = Phone.Mac(name: "MacBook Pro", kit: "1.150", tz: "America/New_York", account: Phone.account("name@sttark.com"))
        var state = Sample.write(dir: dir, kit: kit, now: now)
        let payloads = dir.appendingPathComponent("payloads")
        try? fm.createDirectory(at: payloads, withIntermediateDirectories: true)
        var built: [(String, [String: Any])] = []   // every payload, for the leak check and the schema check

        // ---- the snapshot ----
        let snap = Phone.snapshot(now: Date(timeIntervalSince1970: Double(now)), mac: mac)
        built.append(("snapshot.full", snap))
        let rows = snap["rows"] as? [[String: Any]] ?? []
        func rowsIn(_ g: String) -> [String] { rows.filter { $0["group"] as? String == g }.compactMap { $0["cse"] as? String } }
        func row(_ cse: String) -> [String: Any] { rows.first { $0["cse"] as? String == cse } ?? [:] }
        func obj(_ v: Any?) -> [String: Any] { v as? [String: Any] ?? [:] }
        func list(_ v: Any?) -> [[String: Any]] { v as? [[String: Any]] ?? [] }
        func int(_ v: Any?) -> Int? { (v as? NSNumber).map { $0.intValue } }
        func isNull(_ v: Any?) -> Bool { v is NSNull }

        check("needs you: the two the minute's check found, oldest first, then the one only the Claude app lists",
              rowsIn("needs_you") == ["cse_01PhoneOrderLogin", "cse_01PhoneNozzle", "cse_01PhoneBinLabels"])
        check("claude working: the longest first, in a turn or with work in the background",
              rowsIn("working") == ["cse_01PhonePressColor", "cse_01PhoneHvac", "cse_01PhoneKitDesign", "cse_01PhoneCiWatch"])
        check("waiting on someone else: one row per session, by the first deadline",
              rowsIn("waiting") == ["cse_01PhonePressCheck", "cse_01PhoneProof", "cse_01PhoneRetry", "cse_01PhoneLaminator", "cse_01PhoneParts",
                                    "cse_01PhonePrice", "cse_01PhonePowder"])
        check("held at usage limit: the longest held first", rowsIn("held") == ["cse_01PhoneInventory", "cse_01PhoneSiteMap", "cse_01PhoneUsageReport"])
        check("only the four groups, in the phone's order", rows.map { $0["group"] as? String ?? "" }
              == Array(repeating: "needs_you", count: 3) + Array(repeating: "working", count: 4) + Array(repeating: "waiting", count: 7) + Array(repeating: "held", count: 3))
        let sentIds = Set(rows.compactMap { $0["cse"] as? String })
        check("idle sessions, a reply not opened and On this Mac only stay on the Mac",
              sentIds.isDisjoint(with: ["cse_01PhoneIdle", "cse_01PhoneUnseen", "cse_01PhoneBack"]) && !rows.contains { ($0["id"] as? String ?? "").hasPrefix("local:") })
        check("a wait or a hold of a session with no Remote Control id is left out (the schema needs its cse and link)",
              !rows.contains { ($0["id"] as? String ?? "").hasPrefix("wait:") || ($0["id"] as? String ?? "").hasPrefix("hold:") })

        let order = row("cse_01PhoneOrderLogin"), nozzle = row("cse_01PhoneNozzle"), bins = row("cse_01PhoneBinLabels")
        check("needs you: waited 22 min is late, 3 min is not", order["late"] as? Bool == true && nozzle["late"] as? Bool == false)
        check("needs you: the time it waits from, as Unix seconds", int(order["time_at"]) == now - 1320 && int(obj(order["session"])["waiting_since"]) == now - 1320)
        check("needs you: why, in the row and the session", order["sub"] as? String == "Needs you: a plan waits for your go-ahead"
              && obj(order["session"])["why"] as? String == "a plan waits for your go-ahead" && obj(order["session"])["needs_you"] as? Bool == true)
        check("a session only the Claude app lists: no level, and a link made from its id",
              isNull(obj(bins["session"])["level"]) && bins["url"] as? String == "https://claude.ai/code/session_01PhoneBinLabels")
        check("the Claude Code session id when the Mac knows it", order["sid"] as? String == "5b0c2f4e-1d7a-4c11-9e2b-3a6f8d0c1e21" && isNull(bins["sid"]))

        let hvac = row("cse_01PhoneHvac"), design = row("cse_01PhoneKitDesign"), press = row("cse_01PhonePressColor"), ci = row("cse_01PhoneCiWatch")
        let bg = obj(hvac["background"])
        check("two agents in the background: counted, with the newest one's task and since when",
              int(bg["agents"]) == 2 && int(bg["bash"]) == 0 && bg["what"] as? String == "Photos of the B unit heads" && int(bg["since"]) == now - 540
              && hvac["sub"] as? String == "2 agents working · Photos of the B unit heads" && int(hvac["time_at"]) == now - 540)
        check("a background command", int(obj(ci["background"])["bash"]) == 1 && ci["sub"] as? String == "1 background command · Watch the release build")
        check("in a turn: turn_at and the time are when the turn started; no background",
              int(obj(design["session"])["turn_at"]) == now - 360 && int(design["time_at"]) == now - 360 && isNull(design["background"])
              && isNull(obj(hvac["session"])["turn_at"]))
        check("effort: the level, Auto or Manual, and the reason", obj(design["session"])["level"] as? String == "xhigh"
              && obj(design["session"])["reason"] as? String == "Design question on a full app window"
              && obj(press["session"])["manual"] as? Bool == true && press["sub"] as? String == "Manual: you set the effort")
        let ciTitle = ci["title"] as? String ?? ""
        check("a long name is cut to 160 characters, with …", ciTitle.unicodeScalars.count <= 160 && ciTitle.hasSuffix("…") && ciTitle.hasPrefix("Rework the label press"))
        check("each session's usage setting: credits, hold at its percent, else follow",
              obj(press["limit_mode"])["mode"] as? String == "credits" && isNull(obj(press["limit_mode"])["at"])
              && obj(row("cse_01PhoneSiteMap")["limit_mode"])["mode"] as? String == "hold" && int(obj(row("cse_01PhoneSiteMap")["limit_mode"])["at"]) == 80
              && obj(design["limit_mode"])["mode"] as? String == "follow")

        let retry = row("cse_01PhoneRetry"), lam = row("cse_01PhoneLaminator"), parts = row("cse_01PhoneParts")
        let price = row("cse_01PhonePrice"), powder = row("cse_01PhonePowder"), pcheck = row("cse_01PhonePressCheck")
        func waitsOf(_ r: [String: Any]) -> [[String: Any]] { list(r["waits"]) }
        func wait(_ r: [String: Any], _ id: String) -> [String: Any] { waitsOf(r).first { $0["id"] as? String == id } ?? [:] }
        check("two pull requests: one row, both waits, by deadline", retry["sub"] as? String == "2 pull requests"
              && waitsOf(retry).map { $0["id"] as? String ?? "" } == ["a1b2c3", "d4e5f6"])
        check("a pull request: its own --what, else words with no number or repo",
              wait(retry, "a1b2c3")["what"] as? String == "Merge of the retry fix PR" && wait(retry, "d4e5f6")["what"] as? String == "Pull request closed"
              && wait(retry, "a1b2c3")["checks"] as? String == "The pull request on GitHub, every 5 min")
        check("a session still in the list keeps its session; an archived one has none",
              obj(retry["session"])["level"] as? String == "medium" && isNull(lam["session"]) && isNull(powder["session"]))
        check("two email replies, one check failing: a warning, not bold", lam["sub"] as? String == "2 email replies"
              && lam["sub_warn"] as? String == "1 check failing" && isNull(lam["sub_strong"]))
        let e1 = wait(lam, "b2c3d4"), e2 = wait(lam, "c3d4e5")
        check("an email reply: what, from, why, deadline and how it is checked (every 30 min after 3 hours)",
              e1["kind"] as? String == "email-reply" && e1["what"] as? String == "Supplier's reply to the deposit email" && e1["from"] as? String == "supplier.example"
              && e1["why"] as? String == "They said 2 workdays; later misses this week's slot" && int(e1["by"]) == now + 3 * 86400
              && e1["checks"] as? String == "Your email, for mail from supplier.example, every 30 min, 7 AM to 9 PM"
              && e1["failing"] as? Bool == false && isNull(e1["failing_since"]))
        check("a failing check: since when, never why; hourly after a day; no --what gives Email reply",
              e2["failing"] as? Bool == true && int(e2["failing_since"]) == now - 7200 && e2["what"] as? String == "Email reply"
              && e2["checks"] as? String == "Your email, every 1 hr, 7 AM to 9 PM" && isNull(e2["from"]))
        let proof = row("cse_01PhoneProof")
        check("an email address in --from goes up as its domain only: in from, the row's bold part and how it is checked",
              proof["sub_strong"] as? String == "from customer.example" && wait(proof, "e1f2a3")["from"] as? String == "customer.example"
              && wait(proof, "e1f2a3")["checks"] as? String == "Your email, for mail from customer.example, every 10 min, 7 AM to 9 PM"
              && proof["sub"] as? String == "Customer's go-ahead on the label proof")
        check("sender: an address's domain, else the name as given", Phone.sender("Dana <dana@supplier.com>") == "supplier.com"
              && Phone.sender("supplier.com") == "supplier.com" && Phone.sender("Dana Sales") == "Dana Sales" && Phone.sender("dana@").isEmpty)
        check("a check-prompt with no --what shows A yes/no check, never the question",
              parts["sub"] as? String == "A yes/no check" && wait(parts, "f6a7b8")["what"] as? String == "A yes/no check"
              && wait(parts, "f6a7b8")["checks"] as? String == "A short Haiku check, every 1 hr, 7 AM to 9 PM")
        check("a check-prompt with --what shows it", price["sub"] as? String == "Price drop on the laminator" && wait(price, "a7b8c9")["kind"] as? String == "check-prompt")
        check("a check script: its --what and its pace, never its path or output",
              wait(powder, "e5f6a7")["what"] as? String == "12 in of new snow at the resort" && wait(powder, "e5f6a7")["checks"] as? String == "The session's own check script, every 2 hr")
        check("a set time: its time is the deadline", pcheck["sub"] as? String == "A set time" && int(wait(pcheck, "b8c9d0")["by"]) == now + 7200
              && int(pcheck["time_at"]) == now + 7200 && wait(pcheck, "b8c9d0")["checks"] as? String == "The clock" && pcheck["late"] as? Bool == false)
        check("a wait's row links to its session", lam["url"] as? String == "https://claude.ai/code/session_01PhoneLaminator")
        check("a wait that came back is not listed", !waitsOf(retry).contains { $0["id"] as? String == "c9d0e1" } && !sentIds.contains("cse_01PhoneOld"))

        let site = obj(row("cse_01PhoneSiteMap")["hold"]), usageRow = obj(row("cse_01PhoneUsageReport")["hold"]), inv = obj(row("cse_01PhoneInventory")["hold"])
        check("a hold at its own percent, with one agent that holds too",
              site["hold"] as? Bool == true && int(site["at"]) == 80 && int(site["percent"]) == 81 && site["limit"] as? String == "5-hour limit"
              && int(site["agents"]) == 1 && int(site["until"]) == now + 7200 && int(site["since"]) == now - 3000
              && row("cse_01PhoneSiteMap")["sub"] as? String == "Hold 80% · 1 of its agents holds too")
        check("a wait at the usage limit", usageRow["hold"] as? Bool == false && int(usageRow["at"]) == 100 && int(usageRow["percent"]) == 100
              && row("cse_01PhoneUsageReport")["sub"] as? String == "Waits at the 5-hour limit" && int(row("cse_01PhoneUsageReport")["time_at"]) == now + 7200)
        check("one model's weekly limit is named as its bar is, and 64.5% goes as 64", inv["limit"] as? String == "Weekly, Opus" && int(inv["percent"]) == 64)

        let usage = obj(snap["usage"]), bars = list(usage["bars"])
        check("usage bars: the API's kind, the window's name, the percent and the reset",
              bars.map { $0["kind"] as? String ?? "" } == ["session", "weekly_all", "weekly_scoped"]
              && bars.map { $0["name"] as? String ?? "" } == ["5-hour limit", "Weekly", "Weekly, Opus"]
              && bars.map { int($0["percent"]) ?? -1 } == [100, 64, 64] && int(bars[0]["resets"]) == now + 7200 && int(usage["at"]) == now - 60)
        check("usage reached: the limit and until when", obj(usage["reached"])["name"] as? String == "5-hour limit" && int(obj(usage["reached"])["until"]) == now + 7200)
        check("reach: the names of the ways only, in the Kit's order", snap["reach"] as? [String] == ["email", "chat", "text", "mac"])
        check("flags", obj(snap["flags"])["paused"] as? Bool == false && obj(snap["flags"])["credits_all"] as? Bool == false)
        check("this Mac", obj(snap["mac"])["name"] as? String == "MacBook Pro" && obj(snap["mac"])["kit"] as? String == "1.150"
              && obj(snap["mac"])["tz"] as? String == "America/New_York" && obj(snap["mac"])["account"] as? String == Phone.account("name@sttark.com"))
        check("at: the time it was built", int(snap["at"]) == now)
        let text = String(data: Phone.json(snap), encoding: .utf8) ?? ""
        check("times and percents are whole numbers", text.range(of: #":-?[0-9]+\.[0-9]"#, options: .regularExpression) == nil)

        // ---- the archived list ----
        guard let v1 = Phone.archived() else { check("archived.json is read", false); finish(dir); return }
        check("archived: newest first; a session with an open wait, one the Claude app lists again, one whose conversation is gone, a bad id and a second copy are left out",
              v1.items.map(\.cse) == ["cse_01PhoneWeeklyPlan", "cse_01PhoneDoorPi", "cse_01PhoneLongTitle", "session_01PhoneBlinds", "cse_01PhoneTileFan"])
        check("archived: the folder's own name only, never a path", v1.items.map(\.folder) == ["src", "building", "", "blind_control", "tile-fan-onshape"])
        check("archived: no archive time (0) goes as null; a missing or foreign link is made from the id",
              v1.items.last?.archivedAt == nil && v1.items.last?.url == "https://claude.ai/code/session_01PhoneTileFan"
              && v1.items[3].url == "https://claude.ai/code/session_01PhoneBlinds")
        check("archived: a long name is cut to 160 characters", v1.items[2].title.unicodeScalars.count <= 160 && v1.items[2].title.hasSuffix("…"))
        let p1 = Phone.archivedPayload(v1)
        built.append(("archived.v1", p1))
        check("the snapshot names this list: its rev and count", snap["archived_rev"] as? String == v1.rev && int(snap["archived_count"]) == 5
              && p1["rev"] as? String == v1.rev && v1.rev != "0000stale0000rev")
        Sample.archived(dir: dir, kit: kit, version: 2)
        guard let v2 = Phone.archived() else { check("archived.json v2 is read", false); finish(dir); return }
        guard let delta = Phone.archivedDelta(from: v1, to: v2) else { check("a delta from v1 to v2", false); finish(dir); return }
        built.append(("archived.v2", Phone.archivedPayload(v2)))
        built.append(("archived-delta.v1-v2", delta))
        check("delta: from v1's rev to v2's, the new and the changed added (newest first), the gone removed",
              delta["base"] as? String == v1.rev && delta["rev"] as? String == v2.rev
              && list(delta["add"]).map { $0["cse"] as? String ?? "" } == ["cse_01PhoneHvacOld", "cse_01PhoneWeeklyPlan"]
              && delta["remove"] as? [String] == ["cse_01PhoneDoorPi"])
        var applied = Dictionary(uniqueKeysWithValues: p1["items"].map { list($0) }!.map { ($0["cse"] as? String ?? "", $0) })
        for x in list(delta["add"]) { applied[x["cse"] as? String ?? ""] = x }
        for c in delta["remove"] as? [String] ?? [] { applied.removeValue(forKey: c) }
        let want = Dictionary(uniqueKeysWithValues: v2.items.map { ($0.cse, $0.json) })
        check("delta: v1 with the delta is v2", Set(applied.keys) == Set(want.keys)
              && applied.allSatisfy { Phone.json($0.value) == Phone.json(want[$0.key] ?? [:]) })
        check("delta: none when nothing changed", Phone.archivedDelta(from: v2, to: v2) == nil)
        let snap2 = Phone.snapshot(now: Date(timeIntervalSince1970: Double(now)), mac: mac)
        built.append(("snapshot.archived-v2", snap2))
        check("the snapshot follows the new list", snap2["archived_rev"] as? String == v2.rev && int(snap2["archived_count"]) == 5)
        try? fm.removeItem(at: kit.appendingPathComponent("archived.json"))
        let noList = Phone.snapshot(mac: mac)
        built.append(("snapshot.no-archived", noList))
        check("no archived.json yet: no rev, a count of 0", isNull(noList["archived_rev"]) && int(noList["archived_count"]) == 0)
        Sample.archived(dir: dir, kit: kit, version: 1)

        // ---- labels, names and the account ----
        let thumbs = Phone.cut(String(repeating: "👍🏽", count: 100))
        check("cut counts characters as the schema does (an emoji with a skin tone is 2) and never splits one",
              thumbs.unicodeScalars.count <= 160 && thumbs.hasSuffix("…") && thumbs.dropLast().allSatisfy { $0 == "👍🏽" })
        check("cut: 160 stays, 161 becomes 159 and …", Phone.cut(String(repeating: "x", count: 160)).count == 160
              && Phone.cut(String(repeating: "x", count: 161)) == String(repeating: "x", count: 159) + "…")
        check("cut: line breaks and runs of spaces become one space", Phone.cut("Fix the\n\n  order\tpage ") == "Fix the order page")
        check("limit names as the bars name them", Phone.limitName("5-hour") == "5-hour limit" && Phone.limitName("weekly") == "Weekly"
              && Phone.limitName("Opus weekly") == "Weekly, Opus" && Phone.limitName("usage") == "Usage limit")
        let acct = Phone.account("name@sttark.com")
        check("account: a 16-digit hash, the same for the same login however it is typed, never the address",
              acct.count == 16 && acct.allSatisfy(Phone.hexDigits.contains) && Phone.account(" Name@Sttark.com") == acct
              && Phone.account("other@sttark.com") != acct && !acct.contains("name"))
        let odd = Phone.snapshot(mac: Phone.Mac(name: "", kit: "?", tz: "Not a zone!", account: "NAME@STTARK.COM"))
        check("this Mac's facts that do not fit the schema get safe values",
              obj(odd["mac"])["name"] as? String == "Mac" && obj(odd["mac"])["kit"] as? String == "0" && obj(odd["mac"])["tz"] as? String == "UTC"
              && obj(odd["mac"])["account"] as? String == Phone.account(""))
        built.append(("snapshot.odd-mac", odd))

        // ---- when to send: the pacer, with a made-up clock ----
        var pacer = Phone.Pacer()
        let t = Date(timeIntervalSince1970: 1_800_000_000)
        let a: [String: Any] = ["v": 1, "at": 1, "rows": [1]], a2: [String: Any] = ["v": 1, "at": 2, "rows": [1]], b: [String: Any] = ["v": 1, "at": 3, "rows": [2]]
        check("pacer: the first build goes up", pacer.offer(a, now: t) == .send)
        check("pacer: a build that differs only in its time sends nothing (the clock alone never sends)", pacer.offer(a2, now: t.addingTimeInterval(1)) == .same)
        check("pacer: a change 1.5 s after a send waits 0.5 s", pacer.offer(b, now: t.addingTimeInterval(1.5)) == .wait(0.5))
        check("pacer: the change goes up 2 s after the last send", pacer.offer(b, now: t.addingTimeInterval(2)) == .send)
        check("pacer: the same again sends nothing", pacer.offer(b, now: t.addingTimeInterval(10)) == .same)
        check("pacer: a build is due 5 minutes after the last one, not before",
              !pacer.buildDue(now: t.addingTimeInterval(10 + 299)) && pacer.buildDue(now: t.addingTimeInterval(10 + 300)))
        pacer.reset()
        check("pacer: after a new connection the whole snapshot goes up at once", pacer.offer(b, now: t.addingTimeInterval(10.5)) == .send)

        // ---- when to send: the feed, on real writes as the hooks make them ----
        var limit = state["limit_pauses"] as? [String: Any] ?? [:]
        limit.removeValue(forKey: "dead-sid")   // the builder already dropped it from the file
        state["limit_pauses"] = limit
        Sample.hookWrite(state, kit: kit)
        var sends: [(at: Date, payload: [String: Any])] = []
        var drift = 0   // a change no file write shows, as age changes a wait's words: only the timed build finds it
        let feed = Phone.Feed(pacer: Phone.Pacer(gap: 2, every: 2.5), build: {
            var p = Phone.snapshot(mac: mac)
            if drift > 0 { p["archived_count"] = drift }
            return p
        }, send: { sends.append((Date(), $0)) })
        func spin(_ s: Double) { RunLoop.main.run(until: Date().addingTimeInterval(s)) }
        func retitle(_ title: String) {   // a new name in the Claude app's list, as `effort-hook.py --list` writes it
            var al = state["app_list"] as? [String: Any] ?? [:]
            al["sessions"] = list(al["sessions"]).map { x -> [String: Any] in
                var y = x
                if y["id"] as? String == "cse_01PhoneKitDesign" { y["title"] = title }
                return y
            }
            state["app_list"] = al
            Sample.hookWrite(state, kit: kit)
        }
        func title(_ p: [String: Any]) -> String? { list(p["rows"]).first { $0["cse"] as? String == "cse_01PhoneKitDesign" }?["title"] as? String }
        Sync.start()
        spin(0.3)
        feed.start()
        check("feed: the whole snapshot at start", sends.count == 1)
        spin(0.5)
        retitle("Sttark Claude Kit, take 2")
        spin(2.2)
        check("feed: a change goes up, 2 s after the last send", sends.count == 2 && sends[1].at.timeIntervalSince(sends[0].at) >= 1.95
              && title(sends[1].payload) == "Sttark Claude Kit, take 2")
        retitle("Sttark Claude Kit, take 3")
        spin(0.3)
        retitle("Sttark Claude Kit, take 4")
        spin(2.5)
        check("feed: two changes within the gap make one send, with the newest", sends.count == 3
              && sends[2].at.timeIntervalSince(sends[1].at) >= 1.95 && title(sends[2].payload) == "Sttark Claude Kit, take 4")
        state["models"] = [["id": "claude-haiku-5-5", "label": "Haiku 5.5"]]
        Sample.hookWrite(state, kit: kit)
        spin(1.0)
        check("feed: a write the phone does not show sends nothing", sends.count == 3)
        drift = 42
        spin(3.0)
        check("feed: the timed build sends a change that no write showed", sends.count == 4 && int(sends[3].payload["archived_count"]) == 42)
        spin(3.0)
        check("feed: the timed build sends nothing when nothing changed", sends.count == 4)
        feed.stop()
        if let last = sends.last?.payload { built.append(("snapshot.feed", last)) }

        // ---- the empty state ----
        for f in ["state.json", "usage.json", "archived.json", "local-sessions.json"] { try? fm.removeItem(at: kit.appendingPathComponent(f)) }
        Sample.hookWrite(["reach": ["ways": [String](), "email": "empty@sttark.com"]], kit: kit)
        let empty = Phone.snapshot(mac: mac)
        built.append(("snapshot.empty", empty))
        check("an empty state: no rows, no usage read, no list", list(empty["rows"]).isEmpty && isNull(obj(empty["usage"])["at"])
              && list(obj(empty["usage"])["bars"]).isEmpty && isNull(obj(empty["usage"])["reached"]) && isNull(empty["archived_rev"]))

        // ---- nothing that must stay on the Mac shows ----
        var leaks: [String] = []
        for (name, p) in built {
            let low = (String(data: Phone.json(p), encoding: .utf8) ?? "").lowercased()
            for m in markers + [dir.path, "/users/", "/private/", "/var/folders", "/tmp/", "wait-scripts", ".jsonl", "@"] where low.contains(m.lowercased()) {
                leaks.append("\(name): \(m)")
            }
        }
        check("no marker, path or address in any of \(built.count) payloads" + (leaks.isEmpty ? "" : ": " + leaks.joined(separator: ", ")), leaks.isEmpty)

        // ---- the fixtures for the server and the pages ----
        let shift = now - fixtureNow
        let fixtures = [("snapshot.json", moved(snap, by: shift)), ("archived.json", p1), ("archived-delta.json", delta)]
        let out = URL(fileURLWithPath: "phone/fixtures/from-mac")
        try? fm.createDirectory(at: out, withIntermediateDirectories: true)
        for (name, p) in fixtures {
            let raw = payloads.appendingPathComponent("raw-" + name)
            try? Phone.json(p).write(to: raw)
            let before = try? Data(contentsOf: out.appendingPathComponent(name))
            let r = run(["node", "-e", "const fs=require('fs');const [a,b]=process.argv.slice(1);fs.writeFileSync(b,JSON.stringify(JSON.parse(fs.readFileSync(a,'utf8')),null,2)+'\\n')",
                         raw.path, out.appendingPathComponent(name).path])
            try? fm.removeItem(at: raw)
            let after = try? Data(contentsOf: out.appendingPathComponent(name))
            check("fixture phone/fixtures/from-mac/\(name) written" + (before == after ? " (unchanged)" : " (changed: commit it)"), r.0 == 0 && after != nil)
        }

        // ---- every payload against the schema, with the contract's own check ----
        for (name, p) in built { try? Phone.json(p, pretty: true).write(to: payloads.appendingPathComponent(name + ".json")) }
        let r = run(["node", "phone/schema/check.mjs", payloads.path])
        print(r.1.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "\n").map { "     " + $0 }.joined(separator: "\n"))
        check("every payload and fixture matches phone/schema, and a field planted in any object fails (node phone/schema/check.mjs)",
              r.0 == 0 && r.1.contains("Contract OK"))
        finish(dir)
    }

    static func finish(_ dir: URL) {
        try? FileManager.default.removeItem(at: dir)
        print(fails == 0 ? "all passed" : "\(fails) failed")
        exit(fails == 0 ? 0 : 1)
    }

    /// The snapshot with each time moved back by `shift` seconds: the fixture reads the same on every run.
    static func moved(_ v: Any, by shift: Int, key: String = "") -> Any {
        let times: Set<String> = ["at", "resets", "until", "time_at", "waiting_since", "turn_at", "since", "by", "failing_since"]
        if let d = v as? [String: Any] { return d.reduce(into: [String: Any]()) { $0[$1.key] = moved($1.value, by: shift, key: $1.key) } }
        if let a = v as? [Any] { return a.map { moved($0, by: shift) } }
        if times.contains(key), let n = v as? NSNumber, !(v is Bool), n.intValue >= 1_000_000_000 { return n.intValue - shift }
        return v
    }

    static func moved(_ p: [String: Any], by shift: Int) -> [String: Any] { moved(p as Any, by: shift) as? [String: Any] ?? [:] }

    /// Runs a command found on the PATH (node) and returns its exit code and output.
    static func run(_ args: [String]) -> (Int32, String) {
        let p = Process(), pipe = Pipe()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        p.arguments = args
        p.standardOutput = pipe
        p.standardError = pipe
        guard (try? p.run()) != nil else { return (-1, "") }
        let d = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        let out = String(data: d, encoding: .utf8) ?? ""
        if p.terminationStatus == 127 { print("Node is needed for the schema check: install it, then run the test again.") }
        return (p.terminationStatus, out)
    }
}

/// The sample state, as the hooks and the app write it, with a marker in every place that must stay on the Mac.
enum Sample {
    static func iso(_ t: Int) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date(timeIntervalSince1970: Double(t)))
    }

    /// A write as the hooks make it: a new file, then a rename over state.json.
    static func hookWrite(_ obj: [String: Any], kit: URL) {
        let tmp = kit.appendingPathComponent("state.json.tmp")
        try! JSONSerialization.data(withJSONObject: obj).write(to: tmp)
        _ = rename(tmp.path, kit.appendingPathComponent("state.json").path)
    }

    /// A saved conversation with a prompt, a reply and other lines that must never leave the Mac.
    static func transcript(_ url: URL, cse: String) {
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let lines = [
            #"{"type":"user","message":{"role":"user","content":"PROMPTMARK fix the order page"},"cwd":"/Users/sample/PATHMARK/src"}"#,
            #"{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"REPLYMARK done. TRANSCRIPTMARK"}]}}"#,
            #"{"type":"queue-operation","operation":"enqueue","content":"PROMPTMARK typed while it ran"}"#,
            #"{"type":"system","subtype":"bridge-session","bridgeSessionId":"\#(cse)"}"#,
        ]
        try? (lines.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    @discardableResult
    static func write(dir: URL, kit: URL, now: Int) -> [String: Any] {
        let projects = dir.appendingPathComponent("PATHMARK-projects/-Users-sample-PATHMARK-src")
        let pid = Int(getpid())   // the app drops a hold row whose process is gone
        func tp(_ sid: String, _ cse: String) -> String {
            let u = projects.appendingPathComponent(sid + ".jsonl")
            transcript(u, cse: cse)
            return u.path
        }
        // keys the hooks never write, as a builder that copied a whole entry would pick them up
        let planted: [String: Any] = ["prompt": "PROMPTMARK what the person typed", "last_reply": "REPLYMARK what Claude said",
                                      "cwd": "/Users/sample/PATHMARK/src", "output": "OUTPUTMARK"]
        func session(_ cse: String, sid: String, _ title: String, _ level: String, ago: Int, reason: String = "", manual: Bool = false,
                     app: [String: Any] = [:], turn: Int? = nil) -> (String, [String: Any]) {
            var a: [String: Any] = ["url": "https://claude.ai/code/session_" + cse.dropFirst(4), "working": false, "archived": false,
                                    "checked": now - 2, "unread": false, "seen": true]
            a.merge(app) { $1 }
            var x: [String: Any] = ["title": title, "level": level, "reason": reason, "manual": manual, "at": now - ago,
                                    "transcript": tp(sid, cse), "app": a]
            x.merge(planted) { a, _ in a }
            if let turn { x["turn_at"] = now - turn }
            return (cse, x)
        }
        let longTitle = "Rework the label press color profiles for the new matte stock, then compare each run against the reference prints and write up which settings changed and why they did"
        let list: [(String, [String: Any])] = [
            session("cse_01PhoneOrderLogin", sid: "5b0c2f4e-1d7a-4c11-9e2b-3a6f8d0c1e21", "Order page login", "high", ago: 1320, reason: "A plan with several steps",
                    app: ["needs": true, "why": "a plan waits for your go-ahead", "last_event_at": iso(now - 1320)]),
            session("cse_01PhoneNozzle", sid: "6c1d3e5f-2e8b-4d22-8f3c-4b7a9e1d2f32", "Nozzle check page", "medium", ago: 180, reason: "Page edits",
                    app: ["needs": true, "why": "it asks which head to test first", "last_event_at": iso(now - 180)]),
            session("cse_01PhoneKitDesign", sid: "7d2e4f6a-3f9c-4e33-9a4d-5c8b0f2e3a43", "Sttark Claude Kit", "xhigh", ago: 30,
                    reason: "Design question on a full app window", app: ["working": true], turn: 360),
            session("cse_01PhoneHvac", sid: "8e3f5a7b-4a0d-4f44-8b5e-6d9c1a3f4b54", "HVAC updates", "medium", ago: 60, reason: "Reads photos and compares them",
                    app: ["background": ["agents": 2, "bash": 0, "what": "Photos of the B unit heads", "since": now - 540]]),
            session("cse_01PhonePressColor", sid: "9f4a6b8c-5b1e-4a55-9c6f-7e0d2b4a5c65", "Press color", "high", ago: 20, manual: true,
                    app: ["working": true], turn: 840),
            session("cse_01PhoneCiWatch", sid: "0a5b7c9d-6c2f-4b66-8d7a-8f1e3c5b6d76", longTitle, "low", ago: 90, reason: "Waits for the build",
                    app: ["background": ["agents": 0, "bash": 1, "what": "Watch the release build", "since": now - 240]]),
            session("cse_01PhoneSiteMap", sid: "1b6c8d0e-7d3a-4c77-9e8b-9a2f4d6c7e87", "Site map plan", "high", ago: 3000, reason: "A plan for one map in all apps"),
            session("cse_01PhoneUsageReport", sid: "2c7d9e1f-8e4b-4d88-8f9c-0b3a5e7d8f98", "Usage report", "medium", ago: 1200, reason: "A short report"),
            session("cse_01PhoneInventory", sid: "3d8e0f2a-9f5c-4e99-9a0d-1c4b6f8e9a09", "Inventory photo cleanup", "medium", ago: 5400, reason: "Many small edits"),
            session("cse_01PhoneIdle", sid: "4e9f1a3b-0a6d-4faa-8b1e-2d5c7a9f0b1a", "IDLEMARK quarterly notes", "low", ago: 7200, reason: "IDLEMARK a short task"),
            session("cse_01PhoneUnseen", sid: "5f0a2b4c-1b7e-4abb-9c2f-3e6d8b0a1c2b", "IDLEMARK unread reply", "low", ago: 1800,
                    app: ["unseen": true, "unread": true, "seen": false, "last_event_at": iso(now - 1800)]),
            session("cse_01PhoneRetry", sid: "6a1b3c5d-2c8f-4bcc-8d3a-4f7e9c1b2d3c", "Usage report retry", "medium", ago: 3600, reason: "Small fix"),
        ]
        var sessions: [String: Any] = [:]
        for (k, v) in list { sessions[k] = v }
        func listed(_ id: String, _ title: String, _ bucket: String, _ ago: Int, unread: Bool = false, level: String = "") -> [String: Any] {
            ["id": id, "title": title, "bucket": bucket, "last": iso(now - ago), "unread": unread, "level": level]
        }
        let appList: [String: Any] = ["at": now - 4, "sessions": [
            listed("cse_01PhoneOrderLogin", "Order page login", "blocked", 1320, unread: true, level: "high"),
            listed("cse_01PhoneNozzle", "Nozzle check page", "blocked", 180, unread: true),
            listed("cse_01PhoneBinLabels", "Bin label sizes", "blocked", 720, unread: true),
            listed("cse_01PhoneKitDesign", "Sttark Claude Kit", "working", 30),
            listed("cse_01PhoneHvac", "HVAC updates", "idle", 60),
            listed("cse_01PhonePressColor", "Press color", "working", 20),
            listed("cse_01PhoneCiWatch", longTitle, "idle", 90),
            listed("cse_01PhoneSiteMap", "Site map plan", "idle", 3000),
            listed("cse_01PhoneUsageReport", "Usage report", "idle", 1200),
            listed("cse_01PhoneInventory", "Inventory photo cleanup", "idle", 5400),
            listed("cse_01PhoneIdle", "IDLEMARK quarterly notes", "idle", 7200),
            listed("cse_01PhoneUnseen", "IDLEMARK unread reply", "idle", 1800, unread: true),
            listed("cse_01PhoneRetry", "Usage report retry", "idle", 3600),
            listed("cse_01PhoneBack", "IDLEMARK brought back from the archive", "idle", 600),
        ]]
        func pause(_ cse: String, sid: String, _ title: String, limit: String, since: Int, until: Int, mode: String, at: Int, percent: Any,
                   agent: String? = nil, pid p: Int = pid) -> [String: Any] {
            var x: [String: Any] = ["sid": sid, "cse": cse, "title": title, "limit": limit, "since": now - since, "until": now + until,
                                    "pid": p, "what": mode == "hold" ? "hold" : "wait", "mode": mode, "at": at, "percent": percent]
            if let agent { x["agent"] = agent }
            return x
        }
        let pauses: [String: Any] = [
            "1b6c8d0e-7d3a-4c77-9e8b-9a2f4d6c7e87": pause("cse_01PhoneSiteMap", sid: "1b6c8d0e-7d3a-4c77-9e8b-9a2f4d6c7e87", "Site map plan",
                                                          limit: "5-hour", since: 3000, until: 7200, mode: "hold", at: 80, percent: 81),
            "1b6c8d0e-7d3a-4c77-9e8b-9a2f4d6c7e87/toolu_1": pause("cse_01PhoneSiteMap", sid: "1b6c8d0e-7d3a-4c77-9e8b-9a2f4d6c7e87", "Site map plan",
                                                                  limit: "5-hour", since: 2990, until: 7200, mode: "hold", at: 80, percent: 81, agent: "a1b2c3d4"),
            "2c7d9e1f-8e4b-4d88-8f9c-0b3a5e7d8f98": pause("cse_01PhoneUsageReport", sid: "2c7d9e1f-8e4b-4d88-8f9c-0b3a5e7d8f98", "Usage report",
                                                          limit: "5-hour", since: 1200, until: 7200, mode: "follow", at: 100, percent: 100),
            "3d8e0f2a-9f5c-4e99-9a0d-1c4b6f8e9a09": pause("cse_01PhoneInventory", sid: "3d8e0f2a-9f5c-4e99-9a0d-1c4b6f8e9a09", "Inventory photo cleanup",
                                                          limit: "Opus weekly", since: 5400, until: 3 * 86400, mode: "hold", at: 60, percent: 64.5),
            "dead-sid": pause("cse_01PhoneDead", sid: "dead-sid", "PATHMARK gone", limit: "5-hour", since: 100, until: 600, mode: "follow", at: 100,
                              percent: 100, pid: 999_999),
            "7e8f9a0b-term": pause("", sid: "7e8f9a0b-term", "Terminal session", limit: "5-hour", since: 600, until: 7200, mode: "follow", at: 100, percent: 100),
        ]
        let modes: [String: Any] = [
            "cse_01PhoneSiteMap": ["mode": "hold", "at": 80, "cse": "cse_01PhoneSiteMap", "sid": "1b6c8d0e-7d3a-4c77-9e8b-9a2f4d6c7e87",
                                   "title": "Site map plan", "by": "typed", "set_at": now - 3600],
            "cse_01PhoneInventory": ["mode": "hold", "at": 60, "cse": "cse_01PhoneInventory", "title": "Inventory photo cleanup", "by": "menu", "set_at": now - 7200],
            "cse_01PhonePressColor": ["mode": "credits", "cse": "cse_01PhonePressColor", "title": "Press color", "by": "menu", "set_at": now - 600],
        ]
        // the waits, with each one's target, script and question planted with markers
        let script = kit.appendingPathComponent("wait-scripts/e5f6a7.sh")
        try? FileManager.default.createDirectory(at: script.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? "#!/bin/zsh\necho SCRIPTMARK 3 in so far\nexit 1\n".write(to: script, atomically: true, encoding: .utf8)
        func wait(_ id: String, _ kind: String, cse: String, sid: String = "", _ title: String, why: String, by: Int?, setAgo: Int,
                  extra: [String: Any]) -> (String, [String: Any]) {
            var w: [String: Any] = ["id": id, "kind": kind, "why": why, "set_at": now - setAgo, "cse": cse, "sid": sid, "title": title,
                                    "transcript": projects.appendingPathComponent("waiting-\(id).jsonl").path, "cwd": "/Users/sample/PATHMARK/src",
                                    "session_url": cse.isEmpty ? "" : "https://claude.ai/code/session_" + cse.dropFirst(4),
                                    "prompt": "PROMPTMARK the Kit's message when it comes back"]
            w["by"] = by.map { now + $0 } as Any? ?? NSNull()
            w.merge(extra) { $1 }
            return (id, w)
        }
        let waitList: [(String, [String: Any])] = [
            wait("a1b2c3", "pr", cse: "cse_01PhoneRetry", sid: "6a1b3c5d-2c8f-4bcc-8d3a-4f7e9c1b2d3c", "Usage report retry",
                 why: "Sunday 5 PM: the reviewer merges within a day", by: 2 * 86400, setAgo: 3600,
                 extra: ["target": "Sttark/TARGETMARK-repo#12", "want": "merged", "what": "Merge of the retry fix PR",
                         "url": "https://github.com/Sttark/TARGETMARK-repo/pull/12"]),
            wait("d4e5f6", "pr", cse: "cse_01PhoneRetry", "Usage report retry", why: "The old branch closes after the merge", by: 2 * 86400 + 3600, setAgo: 3500,
                 extra: ["target": "Sttark/TARGETMARK-repo#13", "want": "closed", "url": "https://github.com/Sttark/TARGETMARK-repo/pull/13"]),
            wait("b2c3d4", "email-reply", cse: "cse_01PhoneLaminator", "Laminator quote", why: "They said 2 workdays; later misses this week's slot",
                 by: 3 * 86400, setAgo: 5 * 3600,
                 extra: ["target": "18cTARGETMARK01", "from": "Dana Sales <dana.sales@supplier.example>", "what": "Supplier's reply to the deposit email",
                         "subject": "SUBJECTMARK deposit"]),
            wait("e1f2a3", "email-reply", cse: "cse_01PhoneProof", "Label proof", why: "They sign off within a day", by: 86400, setAgo: 1800,
                 extra: ["target": "18cTARGETMARK04", "from": "buyer@customer.example", "what": "Customer's go-ahead on the label proof"]),
            wait("c3d4e5", "email-reply", cse: "cse_01PhoneLaminator", "Laminator quote", why: "Same supplier, the older thread",
                 by: 3 * 86400 + 3600, setAgo: 26 * 3600,
                 extra: ["target": "18cTARGETMARK02", "failing": "FAILMARK the Workrouter connector did not load in the check", "failing_since": now - 7200,
                         "failures": 4]),
            wait("e5f6a7", "check-script", cse: "cse_01PhonePowder", "Powder watch", why: "Ski season ends then", by: 40 * 86400, setAgo: 86400 - 600,
                 extra: ["source": "/Users/sample/PATHMARK/src/check-snow.sh", "script": script.path, "every": 7200,
                         "what": "12 in of new snow at the resort", "output": "OUTPUTMARK 3 in so far"]),
            wait("f6a7b8", "check-prompt", cse: "cse_01PhoneParts", "Supplier parts", why: "They promised Friday", by: 4 * 86400, setAgo: 7200,
                 extra: ["target": "Has QUESTIONMARK shipped the press parts?", "every": 3600]),
            wait("a7b8c9", "check-prompt", cse: "cse_01PhonePrice", "Laminator price", why: "The quote ends Monday", by: 5 * 86400, setAgo: 1800,
                 extra: ["target": "Is the QUESTIONMARK laminator price under 9000?", "every": 3600, "what": "Price drop on the laminator"]),
            wait("b8c9d0", "at", cse: "cse_01PhonePressCheck", "Press check", why: "Look at the press run at the end of the shift", by: nil, setAgo: 3600,
                 extra: ["at": now + 7200]),
            wait("c9d0e1", "email-reply", cse: "cse_01PhoneOld", "Old wait", why: "A reply came", by: 86400, setAgo: 9000,
                 extra: ["target": "18cTARGETMARK03", "stage": "back", "what": "SNIPPETMARK replied: deposit received", "back_at": now - 300]),
            wait("d0e1f2", "at", cse: "", "Terminal job", why: "A check from Terminal", by: nil, setAgo: 600, extra: ["at": now + 3 * 3600]),
        ]
        var waits: [String: Any] = [:]
        for (k, v) in waitList { waits[k] = v }
        let state: [String: Any] = [
            "paused": false, "limit_credits_all": false, "sessions": sessions, "app_list": appList, "limit_pauses": pauses, "limit_modes": modes,
            "waits": waits,
            "reach": ["ways": ["chat", "email", "mac", "text", "bogus"], "email": "reachmark.person@sttark.com", "phone": "+1 864 555 0100 REACHMARK",
                      "chat": "https://chat.googleapis.com/v1/spaces/REACHMARK"],
            "keep": ["env": "env_01Sample", "alone": ["cse_01PhoneLaminator": ["transcript": projects.appendingPathComponent("alone.jsonl").path,
                                                                              "title": "Laminator quote", "at": now - 600]]],
            "models": [["id": "claude-sonnet-5-5", "label": "Sonnet 5.5"]],
        ]
        hookWrite(state, kit: kit)
        let usage: [String: Any] = ["at": now - 60, "usage": [
            "extra_usage": ["is_enabled": true, "spend_limit_reached": false],
            "limits": [["kind": "session", "percent": 100, "resets_at": iso(now + 7200), "scope": NSNull(), "is_active": true],
                       ["kind": "weekly_all", "percent": 64, "resets_at": iso(now + 3 * 86400), "scope": NSNull(), "is_active": false],
                       ["kind": "weekly_scoped", "percent": 64.5, "resets_at": iso(now + 3 * 86400 + 3600),
                        "scope": ["model": ["id": NSNull(), "display_name": "Opus"], "surface": NSNull()], "is_active": false]]]]
        try! JSONSerialization.data(withJSONObject: usage).write(to: kit.appendingPathComponent("usage.json"))
        let local: [String: Any] = ["at": now, "sessions": [
            ["id": "5f1c2e7a-local-1", "title": "LOCALMARK bin label sizes", "cwd": "/Users/sample/PATHMARK/labels", "where": "terminal",
             "last": now - 2100, "transcript": projects.appendingPathComponent("local-1.jsonl").path, "pending": false]]]
        try! JSONSerialization.data(withJSONObject: local).write(to: kit.appendingPathComponent("local-sessions.json"))
        // what else the Kit keeps on this Mac: the log (with prompt starts), the reply checks' notes, a message waiting to go
        try? ("2026-11-15 10:02:48 change cse_01PhoneOrderLogin high->xhigh (2.2s) xhigh - LOGMARK | PROMPTMARK fix the login\n"
              + "2026-11-15 10:03:00 wait   e5f6a7 checked: NO, OUTPUTMARK\n").write(to: dir.appendingPathComponent("log"), atomically: true, encoding: .utf8)
        try? #"{"cse_01PhoneOrderLogin": [{"note": "NOTEMARK REPLYMARK"}]}"#.write(to: kit.appendingPathComponent("working-notes.json"), atomically: true, encoding: .utf8)
        let queue = kit.appendingPathComponent("notify-queue")
        try? FileManager.default.createDirectory(at: queue, withIntermediateDirectories: true)
        try? #"{"subject": "REPLYMARK", "body": "NOTEMARK", "phone": "REACHMARK", "ways": ["text"]}"#.write(to: queue.appendingPathComponent("x.json.hold"), atomically: true, encoding: .utf8)
        archived(dir: dir, kit: kit, version: 1)
        return state
    }

    /// archived.json as effort-hook.py writes it: full paths that stay on the Mac, the window's `doing`, and a stale rev.
    static func archived(dir: URL, kit: URL, version: Int) {
        let base = dir.appendingPathComponent("PATHMARK-archived")
        func item(_ cse: String, _ title: String, folder: String, at: Any, url: String? = nil, transcript: Bool = true) -> [String: Any] {
            let tp = base.appendingPathComponent(cse.replacingOccurrences(of: "/", with: "-") + ".jsonl")
            if transcript { Sample.transcript(tp, cse: cse) }
            return ["cse": cse, "title": title, "folder": folder, "transcript": tp.path, "archived_at": at,
                    "url": url ?? "https://claude.ai/code/session_" + cse.dropFirst(4), "doing": "DOINGMARK what it was doing"]
        }
        let long = "Compare the South B unit heads against the service report from September, find the one nearest the roll-up door, and write the plan for its wiring check"
        var items: [[String: Any]] = [
            item("cse_01PhoneWeeklyPlan", version == 1 ? "Weekly plan" : "Weekly plan, week 47", folder: base.path + "/home/src", at: 1_794_580_200),
            item("session_01PhoneBlinds", "Blinds Wi-Fi watchdog", folder: "/Users/sample/PATHMARK/blind_control", at: 1_794_155_400, url: "https://evil.example/x"),
            item("cse_01PhoneDoorPi", "Door Pi cutover", folder: "/Users/sample/PATHMARK/building/", at: 1_794_493_800),
            item("cse_01PhoneTileFan", "Tile fan print", folder: base.path + "/tile-fan-onshape", at: 0, url: ""),
            item("cse_01PhoneLongTitle", long + " and the parts to order", folder: "~", at: 1_794_328_200),
            item("cse_01PhoneLaminator", "Laminator quote", folder: "/Users/sample/PATHMARK/quotes", at: 1_794_500_000),
            item("cse_01PhoneGone", "PATHMARK gone", folder: "/Users/sample/PATHMARK/gone", at: 1_794_400_000, transcript: false),
            item("cse_01PhoneBack", "IDLEMARK brought back", folder: "/Users/sample/PATHMARK/src", at: 1_794_450_000),
            item("bad/cse", "PATHMARK bad id", folder: "/Users/sample/PATHMARK/src", at: 1_794_440_000),
            item("cse_01PhoneWeeklyPlan", "PATHMARK second copy", folder: "/Users/sample/PATHMARK/src", at: 1_794_430_000),
        ]
        if version == 2 {
            items.removeAll { $0["cse"] as? String == "cse_01PhoneDoorPi" }
            items.insert(item("cse_01PhoneHvacOld", "HVAC fan curve", folder: "/Users/sample/PATHMARK/hvac_automation", at: 1_794_587_700), at: 0)
        }
        let file: [String: Any] = ["at": Date().timeIntervalSince1970, "rev": "0000stale0000rev", "items": items]
        try! JSONSerialization.data(withJSONObject: file).write(to: kit.appendingPathComponent("archived.json"))
    }
}
