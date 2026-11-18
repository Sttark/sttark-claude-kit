import AppKit
import SwiftUI

/// The Kit's window: Sessions (the session inbox and one session's settings), Archived (the archived sessions this
/// Mac can bring back), Usage (each session's share of your use in a period), Settings (every one-time setting),
/// What's new and Events. It opens only when the person picks Open Sttark Claude Kit or a session in the menu, and only
/// then does the app come to the front: nothing here opens, activates or takes the keyboard by itself.
/// Colors are the brand tokens for light and dark, so the window follows the system look as it changes.
final class KitWindow: NSObject, NSWindowDelegate {
    static let shared = KitWindow()
    let model = KitModel()
    private(set) var window: NSWindow?
    private var timer: Timer?
    private var observer: NSObjectProtocol?

    /// The person is using the window now: it is the key window of the active app. An update waits for that.
    var inUse: Bool { NSApp.isActive && window?.isKeyWindow == true }

    /// Only from a click in the menu.
    /// `sheet`: with the What's new sheet on top.
    func show(_ page: KitModel.Page = .sessions, select: String? = nil, sheet: Bool = false, controller: Controller) {
        model.controller = controller
        model.page = page
        if let select { model.selected = select }
        model.reload()
        model.reloadFacts()
        let w = window ?? make()
        // While the window is open the Kit is a regular app: in the Dock and Command-Tab, with its menus. Only here,
        // after the person's click; it goes back to the menu bar only when the window closes.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        w.makeKeyAndOrderFront(nil)
        if page == .news { model.markNewsSeen() }
        if page == .events { model.readEvents() }
        if page == .archived { Archived.refresh(olderThan: 30) }
        if page == .usage { model.refreshUsage() }
        if sheet { model.openSheet() }
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in self?.tick() }
        if observer == nil {
            // a change on disk shows at once; the 3-second tick stays as a fallback
            observer = NotificationCenter.default.addObserver(forName: .kitStateChanged, object: nil, queue: .main) { [weak self] _ in
                guard let self, let w = self.window, w.isVisible else { return }
                self.model.reload()
                if self.model.page == .events { self.model.readEvents() }
            }
        }
        Sync.readList(minGap: 3)
        note("window: opened at \(page.rawValue)" + (select.map { " (\($0.prefix(12)))" } ?? ""))
    }

    private func make() -> NSWindow {
        let w = KitNSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 760),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                         backing: .buffered, defer: false)
        w.title = "Sttark Claude Kit"
        w.titleVisibility = .hidden
        w.titlebarAppearsTransparent = true
        w.isReleasedWhenClosed = false
        w.isRestorable = false   // an update's restart never brings it back by itself
        w.minSize = NSSize(width: 960, height: 600)
        w.contentView = NSHostingView(rootView: KitRoot(model: model))
        w.setFrameAutosaveName("SttarkClaudeKitWindow")
        if !w.setFrameUsingName("SttarkClaudeKitWindow") { w.center() }
        w.delegate = self
        window = w
        return w
    }

    /// Every 3 seconds while it shows: the sessions; the settings every 30 seconds, as they run commands.
    private var ticks = 0
    private func tick() {
        guard let w = window, w.isVisible else { return }
        model.reload()
        ticks += 1
        if model.page == .settings && ticks % 10 == 0 { model.reloadFacts() }
        if model.page == .events { model.readEvents() }
        if model.page == .usage && ticks % 20 == 0 { model.refreshUsage() }   // each minute: what the records gained
    }

    @objc func zoomIn() { model.zoom(by: 1) }
    @objc func zoomOut() { model.zoom(by: -1) }
    @objc func actualSize() { model.zoom(by: 0) }

    func windowWillClose(_ notification: Notification) {
        timer?.invalidate()
        timer = nil
        DispatchQueue.main.async { NSApp.setActivationPolicy(.accessory) }
    }

    /// The window is an accessory app's, with no menu bar of its own; these give it the usual keys
    /// (Copy and Paste in the search field, Command-W to close).
    static func installMainMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let app = NSMenu()
        app.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        app.addItem(.separator())
        app.addItem(withTitle: "Quit Sttark Claude Kit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = app
        main.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)
        let viewItem = NSMenuItem()
        let view = NSMenu(title: "View")
        for (title, key, sel) in [("Actual Size", "0", #selector(KitWindow.actualSize)), ("Zoom In", "=", #selector(KitWindow.zoomIn)),
                                  ("Zoom Out", "-", #selector(KitWindow.zoomOut))] {
            let i = view.addItem(withTitle: title, action: sel, keyEquivalent: key)
            i.target = KitWindow.shared
        }
        viewItem.submenu = view
        main.addItem(viewItem)
        NSApp.mainMenu = main
    }
}

/// Command-plus, Command-equals, Command-minus and Command-zero zoom the window, as in the Claude app, whether or
/// not the View menu gets the keys first.
final class KitNSWindow: NSWindow {
    override func performKeyEquivalent(with e: NSEvent) -> Bool {
        let mods = e.modifierFlags.intersection([.command, .option, .control])
        if mods == .command, let c = e.charactersIgnoringModifiers {
            switch c {
            case "=", "+": KitWindow.shared.model.zoom(by: 1); return true
            case "-", "_": KitWindow.shared.model.zoom(by: -1); return true
            case "0": KitWindow.shared.model.zoom(by: 0); return true
            default: break
            }
        }
        return super.performKeyEquivalent(with: e)
    }
}

/// What the window shows, read from the shared state. The settings run commands, so they're read off the main thread.
final class KitModel: ObservableObject {
    enum Page: String { case sessions, archived, usage, settings, news, events }
    @Published var page: Page = .sessions
    @Published var snap = Inbox.Snapshot()
    @Published var selected: String?
    @Published var search = ""
    @Published var facts = MenuFacts()
    @Published var factsRead = false
    @Published var usage = Usage()
    @Published var notes: [WhatsNew.Note] = []
    @Published var unseen = 0
    /// The What's new sheet, with the notes it shows.
    @Published var sheet: [WhatsNew.Note] = []
    /// A What's new picture shown bigger, over the page.
    @Published var big: WhatsNew.Note?
    @Published var zoom: CGFloat = K.zoom
    /// The Events page: what the Kit did, newest first, and its filters.
    @Published var events: [KitEvent] = []
    @Published var eventSearch = ""
    @Published var eventKind: KitEvent.Kind?
    @Published var eventSession: String?
    @Published var eventProblems = false
    @Published var eventRoutine = false
    @Published var openEvent: String?
    private var eventsStamp = ""
    private var eventsReading = false
    /// What the last Move to Remote Control said, over the session list: the moved row leaves its group at once.
    @Published var moveNote: (ok: Bool, words: String, at: Date)? = nil
    /// The session being moved now (its row id), and the one whose "close it there?" question shows.
    @Published var moving: String? = nil
    @Published var confirmMove: String? = nil
    /// The Archived page: the list, its search, the selected session, the one being brought back, and what the last
    /// Bring it back said (over the list, with its session's name, so Show it can open it on the Sessions page).
    @Published var archived = Archived.List()
    @Published var archivedSearch = ""
    @Published var archivedSelected: String?
    @Published var bringing: String? = nil
    @Published var backNote: (ok: Bool, words: String, at: Date, id: String, title: String)? = nil
    /// Kit on your phone, as PhoneLink last said: Settings draws the Phone box from it at once.
    @Published var phone = PhoneLink.Status()
    /// The Usage page: the scan's last result, the period, the selected session, all or the top 15, and whether a
    /// scan runs now.
    @Published var usageData = SessionUsage.Data()
    @Published var usagePeriod: SessionUsage.Period = .week
    @Published var usageSelected: String?
    @Published var usageAll = false
    @Published var usageReading = false
    /// The ⓘ notes that are open, by key (InfoButton and InfoNote).
    @Published var openNotes: Set<String> = []

    /// Whether the ⓘ note `key` is open, for an InfoButton and its InfoNote.
    func note(_ key: String) -> Binding<Bool> {
        Binding(get: { self.openNotes.contains(key) },
                set: { if $0 { self.openNotes.insert(key) } else { self.openNotes.remove(key) } })
    }
    weak var controller: Controller?
    /// A test draws the window from made-up facts and never runs a command.
    var fixedFacts: MenuFacts?

    func reload() {
        snap = Inbox.snapshot()
        usage = Usage.read()
        notes = WhatsNew.shown
        unseen = WhatsNew.unseen.count
        if selected == nil || !snap.rows.contains(where: { $0.id == selected }) { selected = snap.rows.first?.id }
        archived = Archived.read()
        let shown = archivedRows
        if archivedSelected == nil || !shown.contains(where: { $0.id == archivedSelected }) { archivedSelected = shown.first?.id }
    }

    /// The Archived page's search, as words; none when nothing is typed.
    var archivedWords: [String] { archivedSearch.lowercased().split(separator: " ").map(String.init) }

    /// The archived sessions the search matches (name, folder or what it was doing), newest first.
    var archivedRows: [Archived.Item] {
        let words = archivedWords
        return archived.items.filter { x in
            let hay = (x.title + " " + x.folderShort + " " + x.doing).lowercased()
            return words.allSatisfy { hay.contains($0) }
        }
    }

    /// While a search is typed: the sessions under Waiting on someone else that it matches (name, folder or what each
    /// wait is for). They are not in the archived list, since a session shows in one list only, so without them a
    /// search for an archived session that waits would say it is not on this Mac.
    var archivedWaitRows: [Inbox.Row] {
        let words = archivedWords
        guard !words.isEmpty else { return [] }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return snap.rows(.waits).filter { r in
            let hay = ([r.title, r.sub] + r.waits.flatMap { [$0.what, $0.folder.replacingOccurrences(of: home, with: "~")] })
                .joined(separator: " ").lowercased()
            return words.allSatisfy { hay.contains($0) }
        }
    }

    /// A session on the Sessions page, selected in its group. The Sessions search is cleared when it hides the row.
    func showOnSessions(_ id: String) {
        selected = id
        if let r = snap.rows.first(where: { $0.id == id }), !rows(r.group).contains(where: { $0.id == id }) { search = "" }
        page = .sessions
    }

    /// The same, by the day each was last active: "Today", "Yesterday", "Thursday, Nov 12".
    var archivedDays: [(day: String, items: [Archived.Item])] {
        var out: [(day: String, items: [Archived.Item])] = []
        let cal = Calendar.current, f = DateFormatter()
        f.dateFormat = "EEEE, MMM d"
        for x in archivedRows {
            let day = cal.isDateInToday(x.at) ? "Today" : cal.isDateInYesterday(x.at) ? "Yesterday" : f.string(from: x.at)
            if out.last?.day == day { out[out.count - 1].items.append(x) } else { out.append((day, [x])) }
        }
        return out
    }

    var archivedItem: Archived.Item? { archived.items.first { $0.id == archivedSelected } }

    /// The Usage page's period, added up; the selected session stays when it is in the new period, else the biggest.
    var usageReport: SessionUsage.Report {
        let s = SessionUsage.span(usagePeriod)
        return SessionUsage.report(usageData, from: s.from, to: s.to)
    }

    /// The last scan's result at once, then a scan of what the records gained (at most every 30 seconds).
    func refreshUsage() {
        usageData = SessionUsage.read()
        pickUsage()
        usageReading = true
        SessionUsage.refresh(olderThan: 30) { [weak self] in
            guard let self else { return }
            self.usageReading = false
            self.usageData = SessionUsage.read()
            self.pickUsage()
        }
    }

    func pickUsage() {
        let lines = usageReport.lines
        if usageSelected == nil || !lines.contains(where: { $0.id == usageSelected }) { usageSelected = lines.first?.id }
    }

    func setUsagePeriod(_ p: SessionUsage.Period) {
        usagePeriod = p
        usageAll = false
        pickUsage()
    }

    /// Custom's two days, as dates for the pickers.
    var customFrom: Binding<Date> {
        Binding(get: { SessionUsage.date(SessionUsage.span(self.usagePeriod).from) ?? Date() },
                set: { d in self.setUsagePeriod(SessionUsage.Period(key: SessionUsage.day(d) + ".." + SessionUsage.span(self.usagePeriod).to) ?? .week) })
    }
    var customTo: Binding<Date> {
        Binding(get: { SessionUsage.date(SessionUsage.span(self.usagePeriod).to) ?? Date() },
                set: { d in self.setUsagePeriod(SessionUsage.Period(key: SessionUsage.span(self.usagePeriod).from + ".." + SessionUsage.day(d)) ?? .week) })
    }

    /// Bring it back: the session goes back to the Claude app's list, and the Sessions page, on the same link.
    /// One that is not archived any more is in the list already, so that note is not a problem either.
    func bringBack(_ x: Archived.Item) {
        bringing = x.id
        backNote = nil
        KitActions.unarchive(cse: x.id, origin: .window) { [weak self] r in
            guard let self else { return }
            self.bringing = nil
            self.backNote = (r.reason == .ok || r.reason == .gone, r.words, Date(), x.id, x.title)
            self.changed()
        }
    }

    /// The events, read off the main thread, and only when a log changed since the last read.
    func readEvents() {
        let files = [logURL, KitLogs.all[1].url]
        let stamp = files.map { u -> String in
            let v = try? u.resourceValues(forKeys: [.fileSizeKey, .contentModificationDateKey])
            return "\(v?.fileSize ?? 0)/\(v?.contentModificationDate?.timeIntervalSince1970 ?? 0)"
        }.joined(separator: ",")
        guard stamp != eventsStamp, !eventsReading else { return }
        eventsReading = true
        DispatchQueue.global(qos: .userInitiated).async {
            let ev = Events.read()
            DispatchQueue.main.async {
                self.events = ev
                self.eventsStamp = stamp
                self.eventsReading = false
            }
        }
    }

    var eventMatches: [KitEvent] {
        let words = eventSearch.lowercased().split(separator: " ").map(String.init)
        return events.filter { e in
            if !eventRoutine && e.routine && e.level == .info { return false }
            if eventProblems && e.level == .info { return false }
            if let k = eventKind, e.kind != k && !(k == .problem && e.level != .info) { return false }
            if let n = eventSession, e.name != n { return false }
            if !words.isEmpty {
                let hay = ([e.name ?? "", e.text, e.kind.title] + e.detail).joined(separator: " ").lowercased()
                if !words.allSatisfy({ hay.contains($0) }) { return false }
            }
            return true
        }
    }
    var shownEvents: [KitEvent] { Array(eventMatches.prefix(1500)) }
    var shownEventsCut: Bool { eventMatches.count > 1500 }
    /// The sessions in the events, the most recent first.
    var eventSessionNames: [String] {
        var seen = Set<String>(), out: [String] = []
        for e in events { if let n = e.name, !seen.contains(n) { seen.insert(n); out.append(n) } }
        if let s = eventSession, !seen.contains(s) { out.insert(s, at: 0) }
        return out
    }
    var eventFiltered: Bool { eventKind != nil || eventSession != nil || eventProblems || eventRoutine || !eventSearch.isEmpty }
    func clearEventFilters() { eventKind = nil; eventSession = nil; eventProblems = false; eventRoutine = false; eventSearch = "" }
    func snapHas(_ cse: String) -> Bool { snap.rows.contains { $0.id == cse } }
    /// The session's name: to that session on the Sessions page when it is listed there, else its events only.
    func goToSession(_ e: KitEvent) {
        if let c = e.session, snapHas(c) { selected = c; page = .sessions }
        else { eventSession = e.name }
    }
    /// Problems in the last day, for the page's status line.
    var recentProblems: Int {
        let since = Date().addingTimeInterval(-86400)
        return events.filter { $0.level != .info && $0.last > since }.count
    }

    func reloadFacts() {
        if let f = fixedFacts { facts = f; factsRead = true; return }
        guard let u = controller?.updater else { return }
        DispatchQueue.global().async {
            let f = MenuFacts.current(u)
            DispatchQueue.main.async { self.facts = f; self.factsRead = true }
        }
    }

    /// After a change: the sessions now, and the settings once the command that made it has had time to finish.
    func changed() {
        reload()
        reloadFacts()
        Sync.readList()   // the Kit changed a session: the Claude app's list too
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { self.reload(); self.reloadFacts() }
    }

    func markNewsSeen() {
        WhatsNew.markSeen(WhatsNew.all, "the What's new page")
        unseen = 0
    }

    /// The sheet: the new notes, seen as soon as it opens.
    func openSheet() {
        let notes = WhatsNew.forSheet
        guard !notes.isEmpty else { page = .news; return }
        WhatsNew.markSeen(notes, "the sheet")
        unseen = WhatsNew.unseen.count
        sheet = notes
    }

    var row: Inbox.Row? { snap.rows.first { $0.id == selected } }

    /// 70% to 200% in steps of 10%, remembered across restarts; 0 is Actual Size.
    func zoom(by step: Int) {
        let z = step == 0 ? 1 : min(2, max(0.7, ((K.zoom * 10).rounded() + CGFloat(step)) / 10))
        guard z != K.zoom || step == 0 else { return }
        K.zoom = z
        UserDefaults.standard.set(Double(z), forKey: "kitZoom")
        zoom = z
    }

    func rows(_ g: Inbox.Group) -> [Inbox.Row] {
        let q = search.trimmingCharacters(in: .whitespaces).lowercased()
        return snap.rows(g).filter { q.isEmpty || $0.title.lowercased().contains(q) || $0.sub.lowercased().contains(q) }
    }
}

/// The 5-hour and weekly limits, from the usage the hooks read (usage.json, at most a minute old while sessions run).
struct Usage {
    struct Bar: Identifiable {
        let id: String; let name: String; let percent: Int; let resets: Date?
        /// The usage API's kind: session (the 5-hour limit), weekly_all, or weekly_scoped (one model's weekly limit).
        var kind = ""
    }
    var bars: [Bar] = []
    var at: Date?

    static func read() -> Usage {
        let f = supportDir.appendingPathComponent("usage.json")
        guard let c = (try? JSONSerialization.jsonObject(with: Data(contentsOf: f))) as? [String: Any],
              let u = c["usage"] as? [String: Any] else { return Usage() }
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var out = Usage(at: Limit.num(c["at"]).map { Date(timeIntervalSince1970: $0) })
        for (i, l) in (u["limits"] as? [[String: Any]] ?? []).enumerated() {
            let kind = l["kind"] as? String ?? ""
            let scope = l["scope"] as? [String: Any]
            // a model's own limit names its model as {"model": {"display_name": "Opus"}}
            let model = ((scope?["model"] as? [String: Any])?["display_name"] as? String
                         ?? scope?["model"] as? String ?? scope?["name"] as? String ?? "").capitalized
            let name = kind == "session" ? "5-hour limit" : kind == "weekly_all" ? "Weekly" : model.isEmpty ? "Weekly, one model" : "Weekly, \(model)"
            let r = (l["resets_at"] as? String).flatMap { iso.date(from: $0) ?? ISO8601DateFormatter().date(from: $0) }
            out.bars.append(Bar(id: "\(i)", name: name, percent: Int(Limit.num(l["percent"]) ?? 0), resets: r, kind: kind))
        }
        return out
    }
}

// MARK: look

/// The brand's tokens and type for the window, light and dark.
enum K {
    static let paper = Color(nsColor: Tokens.paper), card = Color(nsColor: Tokens.card), ink = Color(nsColor: Tokens.ink)
    static let steel = Color(nsColor: Tokens.steel), line = Color(nsColor: Tokens.line), hair = Color(nsColor: Tokens.hair)
    static let side = Color(nsColor: Tokens.side), panel = Color(nsColor: Tokens.panel), wash = Color(nsColor: Tokens.wash)
    static let gray = Color(nsColor: Tokens.gray), green = Color(nsColor: Tokens.green), greenText = Color(nsColor: Tokens.greenText)
    static let greenHover = Color(nsColor: Tokens.greenHover), highlight = Color(nsColor: Tokens.highlight)
    static let warnText = Color(nsColor: Tokens.warnText), warnMark = Color(nsColor: Tokens.warnMark)
    static let infoMark = Color(nsColor: Tokens.infoMark), track = Color(nsColor: Tokens.track)
    static let infoText = Color(nsColor: Tokens.infoText), infoSoft = Color(nsColor: Tokens.infoSoft), infoBorder = Color(nsColor: Tokens.infoBorder)
    /// Usage by session's data colors: a session's own use in the brand's blue, its agents' in a tint of it.
    static let session = Color(nsColor: Tokens.infoMark), agents = Color(nsColor: Tokens.agents)

    /// The window's zoom (View > Zoom In, Zoom Out, Actual Size): every size in the window is multiplied by it.
    static var zoom: CGFloat = {
        let z = UserDefaults.standard.double(forKey: "kitZoom")
        return z >= 0.7 && z <= 2 ? CGFloat(z) : 1
    }()

    /// A length at the window's zoom.
    static func z(_ x: CGFloat) -> CGFloat { (x * zoom).rounded() }

    /// Helvetica Neue, the guide's fallback for Founders Grotesk, at 400 or 600, at the window's zoom.
    static func font(_ size: CGFloat, _ semibold: Bool = false) -> Font {
        .custom("Helvetica Neue", size: size * zoom).weight(semibold ? .semibold : .regular)
    }

    /// The native controls' size for the zoom.
    static var control: ControlSize { zoom < 0.9 ? .small : zoom < 1.25 ? .large : .extraLarge }

    static let levels = ["low", "medium", "high", "xhigh", "max"]
}

/// A card: the card ground, a hairline border, 8 pt corners.
struct Box<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 0) { content }
            .background(K.card, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(K.hair))
    }
}

/// A line between two rows of a box.
struct Hairline: View {
    var body: some View { Rectangle().fill(K.hair).frame(height: 1) }
}

/// The one main action: green fill, white semibold; at 55% while it can't be used, as the guide's disabled button.
struct GreenButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { Green(configuration: configuration) }

    private struct Green: View {
        let configuration: ButtonStyleConfiguration
        @Environment(\.isEnabled) var enabled
        var body: some View {
            configuration.label
                .font(K.font(13, true))
                .foregroundColor(.white)
                .padding(.horizontal, 16)
                .frame(height: 30)
                .background(configuration.isPressed ? K.greenHover : K.green, in: RoundedRectangle(cornerRadius: 6))
                .opacity(enabled ? 1 : 0.55)
        }
    }
}

// MARK: the window

struct KitRoot: View {
    @ObservedObject var model: KitModel
    var body: some View {
        HStack(spacing: 0) {
            Sidebar(model: model).frame(width: min(K.z(220), 280))
            Rectangle().fill(K.hair).frame(width: 1)
            VStack(spacing: 0) {
                Header(model: model)
                Rectangle().fill(K.hair).frame(height: 1)
                switch model.page {
                case .sessions: SessionsPage(model: model)
                case .archived: ArchivedPage(model: model)
                case .usage: UsagePage(model: model)
                case .settings: SettingsPage(model: model)
                case .news: NewsPage(model: model)
                case .events: EventsPage(model: model)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(K.card)
        }
        .font(K.font(13))
        .foregroundColor(K.ink)
        .ignoresSafeArea()
        .id(model.zoom)   // a zoom change draws every view again at the new size
        .sheet(isPresented: Binding(get: { !model.sheet.isEmpty }, set: { if !$0 { model.sheet = [] } })) {
            NewsSheet(notes: model.sheet, onContinue: { model.sheet = [] },
                      onAll: { model.sheet = []; model.page = .news; model.markNewsSeen() })
        }
    }
}

struct Sidebar: View {
    @ObservedObject var model: KitModel
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Color.clear.frame(height: max(52, K.z(52)))   // the window's buttons
            nav(.sessions, "Sessions", "tray", badge: model.snap.count(.needs), strong: true)
            nav(.archived, "Archived", "archivebox")
            nav(.usage, "Usage", "chart.bar")
            nav(.settings, "Settings", "gearshape")
            nav(.news, "What's new", "sparkles", text: Updater.version == "?" ? "" : Updater.version)
            nav(.events, "Events", "list.bullet.rectangle")
            Spacer()
            UsageBox(usage: model.usage)
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 12)
        .frame(maxHeight: .infinity)
        .background(K.side)
    }

    func nav(_ p: KitModel.Page, _ title: String, _ icon: String, badge: Int = 0, strong: Bool = false, text: String = "") -> some View {
        let on = model.page == p
        return Button {
            model.page = p
            if p == .settings { model.reloadFacts() }
            if p == .news { model.markNewsSeen() }
            if p == .events { model.readEvents() }
            if p == .archived { Archived.refresh(olderThan: 30) }
            if p == .usage { model.refreshUsage() }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 13 * K.zoom)).foregroundColor(on ? K.greenText : K.steel).frame(width: K.z(18))
                Text(title).font(K.font(13.5, on))
                Spacer()
                if badge > 0 {
                    Text("\(badge)").font(K.font(12, true)).foregroundColor(Color(nsColor: Tokens.card))
                        .padding(.horizontal, 7).frame(minWidth: 20, minHeight: 18).background(K.ink, in: Capsule())
                        .accessibilityLabel("\(badge) need you")
                } else if !text.isEmpty {
                    Text(text).font(K.font(12, p == .news && model.unseen > 0)).foregroundColor(K.steel)
                }
            }
            .padding(.horizontal, K.z(10))
            .frame(height: K.z(30))
            .background(on ? K.wash : .clear, in: RoundedRectangle(cornerRadius: 6))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The usage limits, at the foot of the sidebar: a bar each, when it resets, and how old the read is.
struct UsageBox: View {
    let usage: Usage
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Rectangle().fill(K.hair).frame(height: 1).padding(.horizontal, -10)
            Text("USAGE").font(K.font(12, true)).tracking(0.7).foregroundColor(K.steel)
            if usage.bars.isEmpty {
                Text("No usage read yet. It is read while a session runs.").font(K.font(12)).foregroundColor(K.steel)
            }
            ForEach(usage.bars) { b in
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(b.name).font(K.font(12, true))
                        Spacer()
                        Text("\(b.percent)%").font(K.font(12, b.percent >= 100))
                    }
                    GeometryReader { g in
                        ZStack(alignment: .leading) {
                            Capsule().fill(K.track)
                            Capsule().fill(b.percent >= 100 ? K.warnMark : K.steel)
                                .frame(width: g.size.width * CGFloat(min(100, max(0, b.percent))) / 100)
                        }
                    }
                    .frame(height: 6)
                    if let r = b.resets { Text("Resets \(Limit.clock(r))").font(K.font(12)).foregroundColor(K.steel) }
                }
                .accessibilityElement(children: .combine)
            }
            if let at = usage.at {
                let old = -at.timeIntervalSinceNow > 15 * 60
                Text("Read \(Limit.clock(at))" + (old ? ", may be old" : "")).font(K.font(12)).foregroundColor(old ? K.warnText : K.steel)
            }
        }
        .padding(.horizontal, 10)
    }
}

struct Header: View {
    @ObservedObject var model: KitModel
    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(K.font(15, true))
                Text(subtitle).font(K.font(12)).foregroundColor(K.steel)
            }
            Spacer()
            if model.page == .sessions || model.page == .events || model.page == .archived {
                let text = model.page == .events ? $model.eventSearch : model.page == .archived ? $model.archivedSearch : $model.search
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").foregroundColor(K.steel)
                    TextField(model.page == .events ? "Search events" : model.page == .archived ? "Search archived sessions" : "Search sessions",
                              text: text).textFieldStyle(.plain).font(K.font(13))
                    if !text.wrappedValue.isEmpty {
                        Button { text.wrappedValue = "" } label: { Image(systemName: "xmark.circle.fill").foregroundColor(K.steel) }
                            .buttonStyle(.plain).accessibilityLabel("Clear search")
                    }
                }
                .padding(.horizontal, 8)
                .frame(width: K.z(220), height: K.z(28))
                .background(K.card, in: RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(K.gray))
            } else if model.page == .usage {
                // the period: a choice among a few, the chosen one in ink
                let tags: [(SessionUsage.Period, String)] = [(.today, "Today"), (.week, "7 days"), (.month, "30 days")]
                Segments(options: tags.map { ($0.0.key, $0.1) } + [("custom", "Custom")],
                         value: model.usagePeriod.isCustom ? "custom" : model.usagePeriod.key) { k in
                    if k == "custom" {
                        let s = SessionUsage.span(model.usagePeriod)
                        if !model.usagePeriod.isCustom { model.setUsagePeriod(.custom(s.from, s.to)) }
                    } else if let p = SessionUsage.Period(key: k) { model.setUsagePeriod(p) }
                }
                .frame(width: K.z(320))
                .accessibilityLabel("Period")
            }
        }
        .padding(.leading, K.z(20))
        .padding(.trailing, K.z(16))
        .frame(height: max(52, K.z(52)))
    }

    var title: String {
        switch model.page {
        case .sessions: return "Sessions"; case .archived: return "Archived"; case .usage: return "Usage by session"; case .settings: return "Settings"
        case .news: return "What's new"; case .events: return "Events"
        }
    }
    var subtitle: String {
        switch model.page {
        case .sessions: return model.snap.summary
        case .archived:
            guard let at = model.archived.at else { return "Reading the archived sessions…" }
            let old = -at.timeIntervalSinceNow > 15 * 60
            return "Newest first · read \(Limit.clock(at))" + (old ? ", may be old" : "")
        case .usage:
            let s = SessionUsage.span(model.usagePeriod)
            let read = model.usageData.at.map { " · read " + Limit.clock($0) } ?? ""
            return "Claude Code on this Mac · " + SessionUsage.spanWords(from: s.from, to: s.to) + read
        case .settings: return "Saved as you change them"
        case .news: return "What changed in the Kit in the last 7 days, newest first"
        case .events:
            let n = model.recentProblems
            return (n == 0 ? "No problems in the last day" : "\(n) problem\(n == 1 ? "" : "s") in the last day") + ". Newest first."
        }
    }
}

// MARK: sessions

struct SessionsPage: View {
    @ObservedObject var model: KitModel
    var body: some View {
        HStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if let n = model.moveNote, -n.at.timeIntervalSinceNow < 300 {
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: n.ok ? "checkmark.circle" : "exclamationmark.triangle")
                                .foregroundColor(n.ok ? K.infoMark : K.warnMark)
                            Text(n.words).font(K.font(12.5)).fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 4)
                            Button { model.moveNote = nil } label: { Image(systemName: "xmark") }
                                .buttonStyle(.borderless).help("Hide this message.")
                        }
                        .padding(10)
                        .background(K.wash, in: RoundedRectangle(cornerRadius: 6))
                        .padding(.top, 10)
                    }
                    let groups = Inbox.Group.allCases.filter { !model.rows($0).isEmpty }
                    if groups.isEmpty {
                        Text(model.search.isEmpty ? "No sessions in the last 12 hours." : "No session matches \"\(model.search)\".")
                            .foregroundColor(K.steel).padding(.top, 24).padding(.leading, 8)
                    }
                    ForEach(groups, id: \.self) { g in
                        GroupHeader(group: g, count: model.rows(g).count)
                        ForEach(Array(model.rows(g).enumerated()), id: \.element.id) { i, r in
                            if i > 0 && r.id != model.selected && model.rows(g)[i - 1].id != model.selected {
                                Hairline().padding(.horizontal, 10)
                            } else if i > 0 { Color.clear.frame(height: 1) }
                            RowView(row: r, selected: r.id == model.selected).onTapGesture { model.selected = r.id }
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 16)
            }
            Rectangle().fill(K.hair).frame(width: 1)
            Group {
                if let r = model.row { DetailView(model: model, row: r).id(r.id) } else {
                    Text("Pick a session to see it here.").foregroundColor(K.steel).frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(width: min(K.z(340), 420))
            .background(K.panel)
        }
    }
}

struct GroupHeader: View {
    let group: Inbox.Group
    let count: Int
    var body: some View {
        ListHeader(icon: group.symbol, title: group.title, count: count, column: group.column,
                   color: group == .needs ? K.warnMark : group == .working ? K.infoMark : K.steel)
    }
}

/// A list's group heading: its icon, its name and count, and the time column's name on the right.
struct ListHeader: View {
    let icon: String
    let title: String
    let count: Int
    let column: String
    var color = K.steel
    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 12 * K.zoom, weight: .medium)).foregroundColor(color)
            Text(title).font(K.font(12, true))
            Text("\(count)").font(K.font(12))
            Spacer()
            Text(column).font(K.font(12))
        }
        .foregroundColor(K.steel)
        .padding(.horizontal, 8)
        .padding(.top, 14)
        .padding(.bottom, 4)
    }
}

struct LevelChip: View {
    let level: String
    let manual: Bool
    var body: some View {
        Text(levelNames[level] ?? level).font(K.font(12, true))
            .padding(.horizontal, 6).frame(height: 17)
            .overlay(Capsule().strokeBorder(K.gray, style: StrokeStyle(lineWidth: 1, dash: manual ? [2, 2] : [])))
            .help(manual ? "Manual: you set this level" : "Auto: Claude picks the level")
    }
}

struct RowView: View {
    let row: Inbox.Row
    let selected: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(row.title).font(K.font(13.5, true)).lineLimit(1)
                        if let s = row.session, row.group == .working || row.group == .idle, levelNames[s.level] != nil {
                            LevelChip(level: s.level, manual: s.manual)
                        }
                    }
                    (Text(row.sub) + Text(row.subStrong.isEmpty ? "" : " · ") + Text(row.subStrong).foregroundColor(row.subWarn ? K.warnText : K.ink))
                        .font(K.font(12)).foregroundColor(K.steel).lineLimit(1).truncationMode(.tail)
                }
                Spacer(minLength: 8)
                Text(row.time).font(K.font(12, row.late)).foregroundColor(row.late ? K.warnText : K.steel)
            }
            // the latest check-in under both, the row's whole width, so more of the note shows
            if let n = row.checkin { CheckinLine(note: n) }
        }
        .padding(.horizontal, K.z(10))
        .padding(.vertical, K.z(6))
        .frame(minHeight: K.z(44))
        .background(selected ? K.wash : .clear, in: RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}

/// A working session's latest progress check-in on its row: its age, then the note, on one line.
struct CheckinLine: View {
    let note: Checkins.Note
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 5) {
            Image(systemName: "text.bubble").font(.system(size: 11 * K.zoom)).foregroundColor(K.infoMark)
            (Text(note.age + ": ").foregroundColor(K.steel) + Text(note.text).foregroundColor(K.ink))
                .font(K.font(12)).lineLimit(1).truncationMode(.tail)
        }
        .help(note.text)
    }
}

/// One session: what it is doing or waits on, and its own settings, moved here from the menu's submenus.
struct DetailView: View {
    @ObservedObject var model: KitModel
    let row: Inbox.Row

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 8) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(row.title).font(K.font(19, true)).fixedSize(horizontal: false, vertical: true)
                        StatusChip(text: status, warn: row.group == .needs || row.late || row.subWarn)
                    }
                    Spacer()
                    if !row.url.isEmpty || row.target?.cse.hasPrefix("cse_") == true {
                        Button { Waiting.open(row.url, id: row.session?.id ?? row.wait?.cse ?? row.hold?.cse ?? "") } label: { Label("Open", systemImage: "arrow.up.right").labelStyle(TrailingIcon()) }
                            .controlSize(K.control)
                            .help("Opens this session in the Claude app.")
                    }
                }
                facts
                if let n = row.checkin { checkin(n) }
                waitList
                actions
                if let s = row.session, row.wait == nil { effort(s) }
                if let t = row.target { usage(t) }
            }
            .padding(K.z(16))
            .textSelection(.enabled)
        }
        .controlSize(K.control)
    }

    var status: String {
        switch row.group {
        case .needs: return row.session?.needsYou == true ? "Needs you" : "Reply not opened"
        case .working: return "Claude working"
        case .waits:
            if row.waits.contains(where: { !$0.failing.isEmpty }) { return "Check failing" }
            return row.wait.map { $0.by.map { $0 < Date() } == true ? "Past its deadline" : $0.from.isEmpty || row.waits.count > 1 ? "Waiting on someone else" : "Waiting on \($0.from)" } ?? "Waiting"
        case .held: return row.hold?.hold == true ? "On hold at \(row.hold!.at)%" : "At the usage limit"
        case .idle: return "Idle"
        case .local: return row.local?.pending == true ? "Moves when its reply ends" : "On this Mac only"
        }
    }

    @ViewBuilder var facts: some View {
        let kv = pairs
        if !kv.isEmpty { FactsBox(pairs: kv).padding(.top, 12) }
    }

    var pairs: [(String, String)] {
        var p: [(String, String)] = []
        switch row.group {
        case .needs:
            if let s = row.session, let w = s.waitingSince {
                p.append(("Waiting for", "\(Waiting.ago(w)), since \(Limit.clock(w))"))
                p.append(("Why", s.needsYou ? (s.why.isEmpty ? "Claude needs you here." : s.why.prefix(1).uppercased() + s.why.dropFirst() + ".")
                                             : "Claude finished, and you haven't opened the reply yet."))
            }
        case .working:
            if let b = row.background {
                p.append(("Working for", "\(row.time), since \(Limit.clock(b.since)). The turn ended; its work goes on in the background."))
                p.append(("Running", b.words.prefix(1).uppercased() + b.words.dropFirst()))
                p.append(("Then", "Claude reads the results when they finish. The session then needs you or goes idle."))
            } else {
                p.append(("Working for", row.time.isEmpty ? "Started before the Kit kept turn times" : row.time))
            }
        case .waits:
            if row.waits.count > 1, let w = row.wait {
                p.append(("Waits on", Inbox.waitsWords(row.waits) + ". It comes back when any one ends, at a reply or at its deadline."))
                let ways = Reach.summary(model.snap.reach)
                p.append(("Then", w.cse.isEmpty ? "You get a message by \(ways); open the session yourself."
                                                : "Comes back to your list; tells you by \(ways)."))
            } else if let w = row.wait {
                p.append(("Waits on", w.what + (w.from.isEmpty ? "" : ", from \(w.from)")))
                if let by = w.by { p.append(("Deadline", Inbox.longDay(by))) }
                if !w.why.isEmpty { p.append(("Why then", w.why)) }
                p.append(("Kit checks", Inbox.checks(w)))
                if !w.failing.isEmpty { p.append(("Check failing", DetailView.failingWords(w))) }
                let ways = Reach.summary(model.snap.reach)
                p.append(("Then", w.cse.isEmpty ? "You get a message by \(ways); open the session yourself."
                                                : "Comes back to your list; tells you by \(ways)."))
            }
        case .held:
            if let h = row.hold {
                let level = h.percent.map { "the \(h.limit) limit was at \($0)% at \(Limit.clock(h.since))" }
                    ?? "the \(h.limit) limit reached it at \(Limit.clock(h.since))"
                p.append((h.hold ? "Holds at" : "Waits", h.hold ? "\(h.at)%: \(level)" : "Since \(Limit.clock(h.since)), for the \(h.limit) limit"))
                p.append(("Goes on", "\(Limit.clock(h.until)), when the limit resets, with no model calls until then"))
                if h.agents > 0 { p.append(("Agents", h.agents == 1 ? "1 of its agents holds too" : "\(h.agents) of its agents hold too")) }
            }
        case .idle:
            if let s = row.session { p.append(("Last active", "\(Waiting.ago(s.at)) ago, at \(Limit.clock(s.at))")) }
        case .local:
            if let x = row.local {
                p.append(("Runs", "Only on this Mac, in \(x.whereWords)" + (x.inDesktop ? ", under This computer" : "")
                          + ". Your phone and the Claude app's list don't show it."))
                p.append(("Now", x.pending ? "Open, and Claude is in a reply. It moves when the reply ends."
                                 : x.busy ? "Open in \(x.whereWords), and Claude is in a reply"
                                 : x.pid != nil ? "Open in \(x.whereWords)" : "Closed"))
                if !x.cwd.isEmpty { p.append(("Folder", x.folder)) }
                p.append(("Last active", "\(Waiting.ago(x.last)) ago, at \(Limit.clock(x.last))"))
            }
        }
        return p
    }

    /// "Since 8:01 AM: the Workrouter connector did not load … The Kit tries again every 10 min."
    static func failingWords(_ w: Waits.Wait) -> String {
        (w.failingSince.map { "Since \(Limit.clock($0)): " } ?? "") + w.failing + ". The Kit tries again every 10 min; the deadline still brings the session back."
    }

    /// A session with several waits: each one, with its deadline, its reason and how the Kit checks it.
    @ViewBuilder var waitList: some View {
        if row.waits.count > 1 {
            ForEach(row.waits, id: \.id) { w in
                Box {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(w.what + (w.from.isEmpty ? "" : ", from \(w.from)")).font(K.font(12.5, true)).fixedSize(horizontal: false, vertical: true)
                            Spacer(minLength: 6)
                            Button("Stop") { KitActions.stopWaits([w.id], origin: .window) { _ in model.changed() } }
                                .controlSize(.small).help("Drops this wait only. The session's other waits stay.")
                        }
                        if let by = w.by {
                            Text("Deadline " + Inbox.longDay(by)).font(K.font(12.5)).foregroundColor(by < Date() ? K.warnText : K.ink)
                        }
                        if !w.why.isEmpty { Text(w.why).font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true) }
                        Text(Inbox.checks(w)).font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
                        if !w.failing.isEmpty {
                            Text("Check failing. " + DetailView.failingWords(w)).font(K.font(12)).foregroundColor(K.warnText).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                }
                .padding(.top, 8)
            }
        }
    }

    @ViewBuilder var actions: some View {
        if let w = row.wait {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Button("Bring it back now") { KitActions.bringBack(wait: w.id, origin: .window) { _ in model.changed() } }
                        .help("Brings the session back to your list now, and it tells you where it stands.")
                    Button("Stop waiting") { KitActions.stopWaits((row.waits.isEmpty ? [w] : row.waits).map(\.id), origin: .window) { _ in model.changed() } }
                        .help(row.waits.count > 1 ? "Drops all its waits. The session stays where it is." : "Drops this wait. The session stays where it is.")
                }
                if w.kind == "pr", !w.url.isEmpty {
                    Button { Waiting.open(w.url) } label: { Label("Open the pull request", systemImage: "arrow.up.right").labelStyle(TrailingIcon()) }
                }
            }
            .controlSize(K.control)
            .padding(.top, 12)
        } else if let x = row.local {
            moveActions(x)
        } else if let h = row.hold {
            // the session's own setting below is the one control: to go on now, set it to Always use credits
            Text((h.hold ? "Holds at \(h.at)% until \(Limit.clock(h.until))." : "Waits at the \(h.limit) limit until \(Limit.clock(h.until)).")
                 + " To go on now, set this session to Always use credits below.")
                .font(K.font(12.5)).fixedSize(horizontal: false, vertical: true)
                .padding(.top, 12)
        }
    }

    /// On this Mac only: move it to Remote Control. A session open somewhere runs in one place only, so moving it
    /// closes it there: the Kit asks first. One in a reply moves when the reply ends.
    @ViewBuilder func moveActions(_ x: LocalSessions.Item) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if !x.pending {
                let moving = model.moving == row.id
                HStack(spacing: 8) {
                    Button(moving ? "Moving…" : "Move to Remote Control") { if x.pid != nil { model.confirmMove = row.id } else { startMove(x) } }
                        .buttonStyle(GreenButtonStyle())
                        .disabled(model.moving != nil)
                        .help("Starts this session again with Remote Control, with its whole conversation, in the same folder on this Mac.")
                    if moving { ProgressView().controlSize(.small) }
                }
            }
            Text("It keeps its whole conversation and its folder on this Mac. Then it shows on your phone and in the Claude app, and the Kit keeps it running after a restart."
                 + (x.inDesktop ? " The old entry stays under This computer in the desktop app: archive it there." : ""))
                .font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
        }
        .controlSize(K.control)
        .padding(.top, 12)
        .alert(x.busy ? "Move \"\(x.title)\" when Claude finishes this reply?" : "Close \"\(x.title)\" in \(x.whereWords) and move it?",
               isPresented: Binding(get: { model.confirmMove == row.id }, set: { if !$0 { model.confirmMove = nil } })) {
            Button(x.busy ? "Move When the Reply Ends" : "Close and Move") { startMove(x) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(x.busy ? "Claude is in a reply in \(x.whereWords). When the reply ends, the session closes there and opens with Remote Control, with its whole conversation."
                        : "A session runs in one place only. It closes in \(x.whereWords) and opens with Remote Control, with its whole conversation.")
        }
    }

    func startMove(_ x: LocalSessions.Item) {
        model.moving = row.id
        model.moveNote = nil
        LocalSessions.move(x) { [model] ok, words in
            model.moving = nil
            model.moveNote = (ok, words, Date())
            model.changed()
        }
    }

    /// A working session's latest progress check-in, whole, with when the Kit wrote it.
    func checkin(_ n: Checkins.Note) -> some View {
        let ago = Waiting.ago(n.at)
        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text("Last check-in").font(K.font(12.5, true))
                Spacer()
                Text((ago == "just now" ? "Just now" : ago + " ago") + ", at " + Limit.clock(n.at)).font(K.font(12)).foregroundColor(K.steel)
            }
            Box {
                Text(n.text).font(K.font(12.5)).fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 10).padding(.vertical, 7)
            }
            Text("A new one every 15 min while the work runs. Each one is also on the Events page.")
                .font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 20)
    }

    func effort(_ s: Session) -> some View {
        let auto = Binding<Bool>(get: { !s.manual }, set: { on in
            KitActions.setAuto(cse: s.id, on: on, origin: .window) { _ in
                model.controller?.refreshIcon()
                model.changed()
            }
        })
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Effort").font(K.font(12.5, true))
                Spacer()
                Toggle(isOn: auto) { Text("Auto").font(K.font(12.5)) }
                    .toggleStyle(.switch).controlSize(.mini)
                    .help(s.manual ? "Manual: you set this session's effort. Turn on to let Claude pick it again."
                                   : "On: Claude picks this session's effort for each task.")
            }
            Segments(options: K.levels.map { ($0, levelNames[$0]!) }, value: s.level) { level in
                guard level != s.level || !s.manual else { return }
                // as in the Claude app's effort picker: the session goes to Manual at the level picked
                KitActions.setLevel(cse: s.id, level: level, origin: .window) { _ in
                    model.changed()
                    model.controller?.refreshIcon()
                }
            }
            Text(s.manual ? "Manual: you set the effort. Pick a level, or turn Auto on to let Claude pick it."
                 : s.reason.isEmpty ? "Auto: Claude picks the level for each task. Pick one to set it yourself."
                 : "Why \(levelNames[s.level] ?? s.level): \(s.reason)")
                .font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 20)
    }

    func usage(_ t: Limit.Target) -> some View {
        let mode = Limit.mode(t)
        var choices = Limit.holdChoices
        if case .hold(let n) = mode, !choices.contains(n) { choices = (choices + [n]).sorted() }
        let pick = Binding<String>(get: { tag(mode) }, set: { v in
            let m: Limit.Mode = v == "follow" ? .follow : v == "credits" ? .credits : .hold(Int(v.dropFirst(5)) ?? Limit.defaultHold)
            KitActions.setLimit(cse: t.cse, sid: t.sid, mode: m, origin: .window) { _ in model.changed() }
        })
        return VStack(alignment: .leading, spacing: 6) {
            Text("At the usage limit").font(K.font(12.5, true))
            Picker("At the usage limit", selection: pick) {
                Text("Same as Settings (" + (model.snap.creditsAll ? "use credits at the limit" : "hold at the limit") + ")").tag("follow")
                Text("Always use credits").tag("credits")
                Divider()
                ForEach(choices, id: \.self) { n in Text("Never use credits; hold at \(n)%").tag("hold:\(n)") }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            Text(usageWords(mode)).font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 20)
    }

    func tag(_ m: Limit.Mode) -> String {
        switch m { case .follow: return "follow"; case .credits: return "credits"; case .hold(let n): return "hold:\(n)" }
    }

    func usageWords(_ m: Limit.Mode) -> String {
        switch m {
        case .follow: return model.snap.creditsAll ? "Settings: go on with usage credits at the limit."
                                                   : "Settings: hold at the limit, and go on by itself when it resets."
        case .credits: return "Goes on with usage credits at the limit, whatever Settings says."
        case .hold(let n): return n >= 100
            ? "Never uses usage credits. At the limit it holds with no model calls, and goes on by itself when the limit resets."
            : "Never uses usage credits. When the 5-hour or weekly limit reaches \(n)%, it holds with no model calls, and goes on by itself when the limit resets under \(n)%."
        }
    }
}

/// A session's facts in a box: a name on the left, its value on the right, a hairline between rows.
struct FactsBox: View {
    let pairs: [(String, String)]
    var body: some View {
        Box {
            ForEach(Array(pairs.enumerated()), id: \.offset) { i, p in
                if i > 0 { Hairline() }
                HStack(alignment: .top, spacing: 10) {
                    Text(p.0).foregroundColor(K.steel).frame(width: K.z(84), alignment: .leading)
                    Text(p.1).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                    Spacer(minLength: 0)
                }
                .font(K.font(12.5))
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
            }
        }
    }
}

struct TrailingIcon: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 5) { configuration.title; configuration.icon.font(.system(size: 11, weight: .semibold)) }
    }
}

struct StatusChip: View {
    let text: String
    var warn = false
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(warn ? K.warnMark : K.gray).frame(width: 6, height: 6)
            Text(text).font(K.font(12, true)).foregroundColor(warn ? K.warnText : K.steel).lineLimit(1)
        }
        .padding(.horizontal, 9)
        .frame(height: 22)
        .background(K.card, in: Capsule())
        .overlay(Capsule().strokeBorder(K.line))
    }
}

/// A choice among a few, the chosen one in ink (the guide's mark for a chosen option).
struct Segments: View {
    let options: [(String, String)]
    let value: String
    let pick: (String) -> Void
    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.0) { o in
                let on = o.0 == value
                Button { pick(o.0) } label: {
                    Text(o.1).font(K.font(12, on))
                        .foregroundColor(on ? Color(nsColor: Tokens.card) : K.ink)
                        .frame(maxWidth: .infinity).frame(height: K.z(24))
                        .background(on ? K.ink : .clear, in: RoundedRectangle(cornerRadius: 5))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(2)
        .background(K.track, in: RoundedRectangle(cornerRadius: 7))
    }
}

// MARK: archived

/// The archived sessions this Mac can bring back, by the day each was last active; the selected one on the right,
/// with Open and Bring it back, as on the Sessions page.
struct ArchivedPage: View {
    @ObservedObject var model: KitModel
    var body: some View {
        HStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if let n = model.backNote, -n.at.timeIntervalSinceNow < 300 { note(n) }
                    let days = model.archivedDays
                    let waits = model.archivedWaitRows
                    let searching = !model.archivedWords.isEmpty
                    if days.isEmpty && waits.isEmpty {
                        Text(model.archived.at == nil ? "Reading the archived sessions…"
                             : searching ? "No archived session matches \"\(model.archivedSearch)\"."
                             : "No archived sessions that this Mac can bring back.")
                            .foregroundColor(K.steel).padding(.top, 24).padding(.leading, 8)
                    }
                    ForEach(days, id: \.day) { d in
                        ListHeader(icon: "calendar", title: d.day, count: d.items.count, column: "Last active")
                        ForEach(Array(d.items.enumerated()), id: \.element.id) { i, x in
                            if i > 0 && x.id != model.archivedSelected && d.items[i - 1].id != model.archivedSelected {
                                Hairline().padding(.horizontal, 10)
                            } else if i > 0 { Color.clear.frame(height: 1) }
                            ArchivedRow(item: x, selected: x.id == model.archivedSelected).onTapGesture { model.archivedSelected = x.id }
                        }
                    }
                    if !waits.isEmpty {
                        // a session that waits is on the Sessions page, archived or not: the search finds it there
                        GroupHeader(group: .waits, count: waits.count)
                        Text("These are on the Sessions page. Click one to see it there.")
                            .font(K.font(12)).foregroundColor(K.steel).padding(.horizontal, 8).padding(.bottom, 4)
                        ForEach(Array(waits.enumerated()), id: \.element.id) { i, r in
                            if i > 0 { Hairline().padding(.horizontal, 10) }
                            RowView(row: r, selected: false).onTapGesture { model.showOnSessions(r.id) }
                                .help("Shows this session on the Sessions page.")
                        }
                    }
                    // under a search, only when nothing matched in either list: it says the session is not on this Mac
                    if model.archived.at != nil && (!searching || (days.isEmpty && waits.isEmpty)) {
                        Text("A session from another computer or the cloud is not here: its conversation is not on this Mac. The Claude app's archive has it.")
                            .font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 20).padding(.horizontal, 8)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 16)
            }
            Rectangle().fill(K.hair).frame(width: 1)
            Group {
                if let x = model.archivedItem { ArchivedDetail(model: model, item: x).id(x.id) } else {
                    Text(model.archivedRows.isEmpty && !model.archivedWaitRows.isEmpty ? "Click a session to see it on the Sessions page."
                         : "Pick a session to see it here.")
                        .foregroundColor(K.steel).multilineTextAlignment(.center).padding(.horizontal, 16)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(width: min(K.z(340), 420))
            .background(K.panel)
        }
    }

    /// What the last Bring it back said; Show it opens the session on the Sessions page.
    func note(_ n: (ok: Bool, words: String, at: Date, id: String, title: String)) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: n.ok ? "checkmark.circle" : "exclamationmark.triangle").foregroundColor(n.ok ? K.infoMark : K.warnMark)
            (Text(n.title).font(K.font(12.5, true)) + Text(": " + n.words).font(K.font(12.5))).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 4)
            if n.ok && model.snapHas(n.id) {
                Button("Show it") { model.selected = n.id; model.page = .sessions }
                    .controlSize(.small).help("Opens it on the Sessions page.")
            }
            Button { model.backNote = nil } label: { Image(systemName: "xmark") }
                .buttonStyle(.borderless).help("Hide this message.")
        }
        .padding(10)
        .background(K.wash, in: RoundedRectangle(cornerRadius: 6))
        .padding(.top, 10)
    }
}

struct ArchivedRow: View {
    let item: Archived.Item
    let selected: Bool
    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title).font(K.font(13.5, true)).lineLimit(1)
                if !item.doing.isEmpty {
                    Text(item.doing).font(K.font(12)).foregroundColor(K.steel).lineLimit(1).truncationMode(.tail)
                }
            }
            Spacer(minLength: 8)
            Text(ArchivedRow.time(item.at)).font(K.font(12)).foregroundColor(K.steel)
        }
        .padding(.horizontal, K.z(10))
        .padding(.vertical, K.z(6))
        .frame(minHeight: K.z(44))
        .background(selected ? K.wash : .clear, in: RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    /// The time of day: the day is the group's heading.
    static func time(_ d: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "h:mm a"
        return f.string(from: d)
    }
}

/// One archived session: Open, and Bring it back, which unarchives it on the same link with its whole conversation.
struct ArchivedDetail: View {
    @ObservedObject var model: KitModel
    let item: Archived.Item

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 8) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(item.title).font(K.font(19, true)).fixedSize(horizontal: false, vertical: true)
                        StatusChip(text: "Archived")
                    }
                    Spacer()
                    Button { Waiting.open(item.url, id: item.id) } label: { Label("Open", systemImage: "arrow.up.right").labelStyle(TrailingIcon()) }
                        .controlSize(K.control)
                        .help("Opens this session in the Claude app. It stays archived.")
                }
                FactsBox(pairs: pairs).padding(.top, 12)
                actions
            }
            .padding(K.z(16))
            .textSelection(.enabled)
        }
        .controlSize(K.control)
    }

    var pairs: [(String, String)] {
        var p: [(String, String)] = [("Last active", Inbox.longDay(item.at))]
        if !item.doing.isEmpty { p.append(("Was doing", item.doing)) }
        p.append(("Folder", item.folderShort.isEmpty ? "Not known" : item.folderShort))
        return p
    }

    @ViewBuilder var actions: some View {
        let busy = model.bringing == item.id
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Button(busy ? "Bringing it back…" : "Bring it back") { model.bringBack(item) }
                    .buttonStyle(GreenButtonStyle())
                    .disabled(model.bringing != nil)
                    .help("Unarchives this session and starts it again on the same link, with its whole conversation.")
                if busy { ProgressView().controlSize(.small) }
            }
            Text("It goes back to your list in the Claude app and on the Sessions page, on the same link, with its whole conversation. Nothing is sent to it.")
                .font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
        }
        .controlSize(K.control)
        .padding(.top, 12)
    }
}

// MARK: settings

struct SettingsPage: View {
    @ObservedObject var model: KitModel
    var f: MenuFacts { model.facts }
    var c: Controller? { model.controller }

    var body: some View {
        ScrollView {
            if !model.factsRead {
                ProgressView().controlSize(.small).padding(.top, 40).frame(maxWidth: .infinity)
            } else {
                HStack(alignment: .top, spacing: 24) {
                    VStack(alignment: .leading, spacing: 0) { effort; usage; reach; phone }.frame(maxWidth: .infinity)
                    VStack(alignment: .leading, spacing: 0) { sessions; chrome; mac }.frame(maxWidth: .infinity)
                }
                .padding(.horizontal, 28)
                .padding(.top, 8)
                .padding(.bottom, 24)
                .textSelection(.enabled)
            }
        }
    }

    func heading(_ s: String) -> some View {
        Text(s).font(K.font(12, true)).foregroundColor(K.steel).padding(.top, 16).padding(.bottom, 6).padding(.leading, 2)
    }

    /// A switch, saved at once through the menu's own action.
    func toggle(_ title: String, _ desc: String?, _ on: Bool, enabled: Bool = true, help: String = "", _ act: @escaping () -> Void) -> some View {
        SettingRow(title: title, desc: desc) {
            Toggle(title, isOn: Binding(get: { on }, set: { _ in act(); model.changed() }))
                .labelsHidden().toggleStyle(.switch).controlSize(.small).disabled(!enabled)
        }
        .help(help)
    }

    @ViewBuilder var effort: some View {
        heading("Effort")
        Box {
            toggle("Auto effort", f.paused ? "Off: every session keeps the level it has." : "Claude picks each session's effort for each task.",
                   !f.paused) { c?.togglePaused() }
            Hairline()
            SettingRow(title: "Model that picks the level", desc: "Haiku is faster and cheaper; Sonnet is slower and smarter.") {
                if f.models.isEmpty { Text("Not listed yet").foregroundColor(K.steel) } else {
                    Picker("Model", selection: Binding(get: { f.model }, set: { State.setModel($0); model.changed() })) {
                        ForEach(f.models, id: \.id) { m in Text(m.label).tag(m.id) }
                    }
                    .labelsHidden().pickerStyle(.menu).frame(width: 150)
                }
            }
            if !f.claudeFound {
                Hairline()
                SettingRow(title: "Claude Code isn't installed", desc: "Sttark Claude Kit needs it at ~/.local/bin/claude.", warn: true) { EmptyView() }
            }
        }
    }

    @ViewBuilder var usage: some View {
        heading("Usage limit")
        Box {
            toggle("Use credits at the usage limit",
                   f.creditsAll ? "On: at your 5-hour or weekly limit, sessions go on with usage credits. A session with its own setting keeps it."
                                : "Off: at your 5-hour or weekly limit, sessions hold and go on by themselves when it resets. A session with its own setting keeps it.",
                   f.creditsAll) { c?.toggleCredits() }
        }
    }

    @ViewBuilder var reach: some View {
        heading("Reach me by")
        Box {
            Text("When a session's wait ends, tell me by").font(K.font(12)).foregroundColor(K.steel)
                .padding(.horizontal, 12).padding(.vertical, 10)
            ForEach(Reach.ways, id: \.self) { way in
                Hairline()
                reachRow(way)
            }
            Hairline()
            HStack {
                Spacer()
                Button("Send a test") { Reach.test() }
                    .disabled(f.reach.ways.isEmpty)
                    .help("Sends a test message every way that's checked, then says how each went.")
            }
            .controlSize(K.control)
            .padding(.horizontal, 12).padding(.vertical, 9)
        }
    }

    func reachRow(_ way: String) -> some View {
        let r = f.reach
        let need = Reach.missing(way, r)
        let detail: String = {
            switch way {
            case "email": return r.email
            case "push": return "push to your phone"
            case "chat": return "webhook set"
            case "text": return r.phone
            default: return "click it to open the session"
            }
        }()
        let ask: (() -> Bool)? = way == "email" ? Reach.askEmail : way == "text" ? Reach.askPhone : way == "chat" ? Reach.askChat : nil
        return HStack(spacing: 10) {
            Toggle(Reach.names[way]!, isOn: Binding(get: { r.ways.contains(way) }, set: { _ in Reach.pick(way); model.changed() }))
                .toggleStyle(.checkbox).font(K.font(13))
            Spacer()
            if let need { Text(need).font(K.font(12)).foregroundColor(K.warnText) } else { Text(detail).font(K.font(12.5)).foregroundColor(K.steel).lineLimit(1) }
            if let ask {
                Button(need == nil ? "Change…" : "Set…") { _ = ask(); model.changed() }
            }
        }
        .padding(.horizontal, K.z(12))
        .frame(minHeight: K.z(40))
    }

    @ViewBuilder var phone: some View {
        heading("Phone")
        Box {
            PhoneRow(status: model.phone, link: { c?.linkPhone() }, toggle: { c?.toggleKitPhone() })
        }
    }

    @ViewBuilder var sessions: some View {
        heading("Sessions")
        Box {
            SettingRow(title: "Start sessions from the Claude app",
                       desc: f.serverElsewhere ? "A server set up outside Sttark Claude Kit already runs on this Mac."
                       : f.serverState?.0
                       ?? f.serverFolder.map { "Sessions start in " + $0.replacingOccurrences(of: FileManager.default.homeDirectoryForCurrentUser.path, with: "~") }
                       ?? "Start Claude Code sessions on this Mac from the Claude app on your phone or any computer.",
                       warn: f.serverState?.1 ?? false) {
                Toggle("Start sessions from the Claude app", isOn: Binding(get: { f.serverElsewhere || f.serverInstalled },
                                                                          set: { _ in c?.togglePhone(); model.changed() }))
                    .labelsHidden().toggleStyle(.switch).controlSize(.small)
            }
            Hairline()
            toggle("New sessions start on this Mac's server", "New Code sessions in the Claude app start on Remote Control, so your phone and the Kit see them.",
                   f.desktopDefault) { c?.toggleDesktopDefault() }
            Hairline()
            toggle("Bypass permissions for server sessions", "Lets sessions on this Mac's server run without asking. The Claude app doesn't offer it.",
                   f.bypass) { c?.toggleBypass() }
            Hairline()
            toggle("Name sessions automatically", "A short handle for each session's project or area. Never changes a name you set.",
                   f.names) { c?.toggleNames() }
            Hairline()
            toggle("Progress check-ins in the Kit", "While a session works 15 min or more: a short note on its row here and on your phone. No alerts.",
                   f.checkins, help: "Every 15 minutes: what got done, what is next, and anything it is stuck on, with its age. It shows in Sessions and in Kit on your phone, never as a message or notice. Turn it off to save the short Haiku calls.") { c?.toggleCheckins() }
            Hairline()
            toggle("Sttark working rules", "Rules in front of every prompt; a Simplified Technical English check on every reply.",
                   f.workingRules) { c?.toggleWorkingRules() }
            Hairline()
            toggle("Sync Claude profile instructions",
                   f.profileSettingUp ? "Setting up…" : f.profile ? (f.profileLast.map { "Last sync: " + $0 } ?? "On") : "Copies your Claude profile instructions into Claude Code.",
                   f.profile, enabled: !f.profileSettingUp) { c?.toggleProfile() }
        }
    }

    @ViewBuilder var chrome: some View {
        heading("Chrome and files")
        Box {
            SettingRow(title: "Claude window in Chrome",
                       desc: f.chromeWindowClosed ? "The Claude window is closed. Claude opens it again when it needs it." : "One window, a tab per session, never in front of you.") {
                HStack(spacing: 8) {
                    if f.chromeWindowClosed { Button("Open Claude window") { c?.openChromeWindow(); model.changed() } }
                    Toggle("Claude window in Chrome", isOn: Binding(get: { f.chromeWindow }, set: { _ in c?.toggleChromeWindow(); model.changed() }))
                        .labelsHidden().toggleStyle(.switch).controlSize(.small)
                }
            }
            Hairline()
            SettingRow(title: "Approve Claude in Chrome",
                       desc: f.needsAccessibility ? "Needs Accessibility permission for SttarkChromeApprover." : "Clicks Allow when Claude for Chrome asks to use a site.",
                       warn: f.needsAccessibility) {
                HStack(spacing: 8) {
                    if f.needsAccessibility { Button("Open Accessibility…") { c?.openAccessibility() } }
                    Toggle("Approve Claude in Chrome", isOn: Binding(get: { f.chromeApprover }, set: { _ in c?.toggleChrome(); model.changed() }))
                        .labelsHidden().toggleStyle(.switch).controlSize(.small)
                }
            }
            Hairline()
            toggle("Links to files", "A link instead of a file path, on this Mac or your phone.", f.fileLinks) { c?.toggleFileLinks() }
        }
    }

    @ViewBuilder var mac: some View {
        heading("This Mac")
        Box {
            SettingRow(title: "Sttark Claude Kit \(f.version)", desc: updateWords) {
                if f.installing { EmptyView() }
                else if let v = f.available { Button("Update to \(v)") { c?.update() } }
                else { Button("Check for updates") { c?.checkUpdates(); model.changed() } }
            }
            Hairline()
            SettingRow(title: "Claude Code login", desc: loginWords, warn: !f.signedIn || (f.loginEnds.map { $0.timeIntervalSinceNow < 3 * 86400 } ?? false)) {
                Button("Sign in…") { c?.signIn() }.help(f.loginTip)
            }
            Hairline()
            SettingRow(title: "Events", desc: "What the Kit did, in plain words, newest first") { Button("Show events") { model.page = .events; model.readEvents() } }
        }
    }

    var updateWords: String {
        if f.installing { return "Updating…" }
        if let v = f.available { return "Version \(v) is ready." }
        return "Up to date." + (f.lastCheck.map { " Checked \(Limit.clock($0))." } ?? "")
    }

    var loginWords: String {
        if !f.signedIn { return "Signed out: sessions and the server can't run." }
        guard let e = f.loginEnds else { return "Signed in" }
        let d = DateFormatter()
        d.dateFormat = "MMM d"
        return "Ends \(d.string(from: e))"
    }
}

/// Kit on your phone: the switch, what it does now (not linked, linking with this Mac's code, linked with the account
/// and when it last sent, and where Needs you notices go), and Link this Mac… while it is not linked. The window never
/// opens the browser by itself: only the button, or the link notice, does.
struct PhoneRow: View {
    let status: PhoneLink.Status
    var link: () -> Void
    var toggle: () -> Void
    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Kit on your phone").font(K.font(13))
                Text(status.words).font(K.font(12)).foregroundColor(status.warn ? K.warnText : K.steel)
                    .fixedSize(horizontal: false, vertical: true)
                if let notices = status.notices {
                    Text(notices).font(K.font(12)).foregroundColor(K.steel)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if status.stage == .linking, let code = status.code {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("Code").font(K.font(12)).foregroundColor(K.steel)
                        Text(code).font(K.font(17, true)).tracking(3).foregroundColor(K.ink)
                    }
                    .padding(.top, K.z(4))
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("This Mac's code: " + code.map(String.init).joined(separator: " "))
                }
            }
            Spacer(minLength: 8)
            HStack(spacing: 8) {
                if status.canLink {
                    // while the link page is open, the same button opens it again (a closed tab)
                    Button(status.stage == .linking ? "Open the page again" : "Link this Mac…", action: link)
                        .help("Opens the link page in your browser. Sign in with Google, then click Link.")
                }
                Toggle("Kit on your phone", isOn: Binding(get: { status.stage != .off }, set: { _ in toggle() }))
                    .labelsHidden().toggleStyle(.switch).controlSize(.small)
            }
            .controlSize(K.control)
        }
        .padding(.horizontal, K.z(12))
        .padding(.vertical, K.z(9))
        .frame(minHeight: K.z(44))
    }
}

/// A setting: its name and a line on what it does, and its control on the right.
struct SettingRow<Control: View>: View {
    let title: String
    let desc: String?
    var warn = false
    @ViewBuilder var control: Control
    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(K.font(13))
                if let desc, !desc.isEmpty {
                    Text(desc).font(K.font(12)).foregroundColor(warn ? K.warnText : K.steel).fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 8)
            control.controlSize(K.control)
        }
        .padding(.horizontal, K.z(12))
        .padding(.vertical, K.z(9))
        .frame(minHeight: K.z(44))
        // the height its words need at its width, whatever height the box offers: offered less, a row of two lines
        // kept only the least height and its words ran over its padding
        .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: what's new

struct NewsPage: View {
    @ObservedObject var model: KitModel
    var body: some View {
        ScrollView {
            Group {
                if model.notes.isEmpty { Text("No changes in the last 7 days.").foregroundColor(K.steel).padding(.top, 24) } else { rows }
            }
            .textSelection(.enabled)
            .padding(.horizontal, K.z(32))
            .padding(.vertical, K.z(28))
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(K.card)
        .overlay { if let b = model.big { BigPicture(note: b) { model.big = nil } } }
    }

    /// A heading for each update; each note's icon and words on the left, its picture on the right (below them
    /// when the window is narrow).
    var rows: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(WhatsNew.releases(model.notes), id: \.build) { r in
                HStack(spacing: 10) {
                    Text("\(r.notes[0].day.uppercased())  ·  VERSION \(r.notes[0].version)").font(K.font(12, true)).tracking(0.7).foregroundColor(K.steel)
                    Rectangle().fill(K.hair).frame(height: 1)
                }
                .padding(.bottom, K.z(20))
                VStack(alignment: .leading, spacing: K.z(36)) {
                    ForEach(r.notes, id: \.id) { n in
                        ViewThatFits(in: .horizontal) {
                            HStack(alignment: .top, spacing: K.z(32)) { words(n).frame(width: K.z(360), alignment: .leading); NoteImage(note: n) { model.big = $0 } }
                            VStack(alignment: .leading, spacing: K.z(16)) { words(n).frame(maxWidth: K.z(560), alignment: .leading); NoteImage(note: n) { model.big = $0 } }
                        }
                    }
                }
                .padding(.bottom, K.z(44))
            }
        }
    }

    func words(_ n: WhatsNew.Note) -> some View {
        HStack(alignment: .top, spacing: K.z(14)) {
            Image(systemName: n.icon ?? "sparkles").font(.system(size: 20 * K.zoom)).foregroundColor(K.greenText)
                .frame(width: K.z(26)).padding(.top, 1).accessibilityHidden(true)
            NoteText(note: n)
        }
    }
}
