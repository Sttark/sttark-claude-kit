import AppKit
import SwiftUI

/// The window's Usage page: each session's share of the person's use in the period picked at the top of the list (Today,
/// 7 days, 30 days or Custom), the biggest first, with what the same work takes people (human work, an estimate), and the
/// selected session on the right: its share split between the session and its agents, its tokens, the agents it
/// started, its use at API prices, its time at work and its human work, a bar for each day and its models.
/// No folder or path shows. The data colors are the brand's blue for the session and a tint of it for its agents,
/// with a legend; never green, which means the main action and "you are here".
struct UsagePage: View {
    @ObservedObject var model: KitModel
    static let shown = 15

    var body: some View {
        let r = model.usageReport
        HStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    period.padding(.top, 12)
                    if model.usagePeriod.isCustom { range.padding(.top, 12) }
                    note.padding(.top, 12)
                    if r.lines.isEmpty {
                        Text(model.usageData.empty ? (model.usageReading ? "Reading your sessions' records…" : "No records of Claude Code use on this Mac yet.")
                             : "No use in this period.")
                            .foregroundColor(K.steel).padding(.top, 24).padding(.leading, 8)
                    } else {
                        totals(r).padding(.top, 12)
                        let top = r.lines.first?.usd ?? 1
                        let lines = model.usageAll ? r.lines : Array(r.lines.prefix(UsagePage.shown))
                        ForEach(Array(lines.enumerated()), id: \.element.id) { i, l in
                            if i > 0 && l.id != model.usageSelected && lines[i - 1].id != model.usageSelected {
                                Hairline().padding(.horizontal, 10)
                            } else if i > 0 { Color.clear.frame(height: 1) }
                            UsageRow(line: l, share: r.share(l.usd), top: top, selected: l.id == model.usageSelected, multiDay: r.from != r.to)
                                .onTapGesture { model.usageSelected = l.id }
                        }
                        more(r)
                    }
                    foot.padding(.top, 20)
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 16)
            }
            Rectangle().fill(K.hair).frame(width: 1)
            Group {
                if let l = r.lines.first(where: { $0.id == model.usageSelected }) {
                    UsageDetail(model: model, line: l, report: r).id(l.id + r.from + r.to)
                } else {
                    Text(r.lines.isEmpty ? "" : "Pick a session to see it here.").foregroundColor(K.steel).frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(width: min(K.z(340), 420))
            .background(K.panel)
        }
    }

    /// The period, at the top of the list (the top bar holds the search): a choice among a few, the chosen one in ink.
    var period: some View {
        let tags: [(SessionUsage.Period, String)] = [(.today, "Today"), (.week, "7 days"), (.month, "30 days")]
        return Segments(options: tags.map { ($0.0.key, $0.1) } + [("custom", "Custom")],
                        value: model.usagePeriod.isCustom ? "custom" : model.usagePeriod.key) { k in
            if k == "custom" {
                let s = SessionUsage.span(model.usagePeriod)
                if !model.usagePeriod.isCustom { model.setUsagePeriod(.custom(s.from, s.to)) }
            } else if let p = SessionUsage.Period(key: k) { model.setUsagePeriod(p) }
        }
        .frame(width: K.z(320))
        .accessibilityLabel("Period")
    }

    /// Custom: the first and last day, within the days the Kit keeps.
    var range: some View {
        let first = SessionUsage.date(model.usageData.days.first ?? "") ?? Date().addingTimeInterval(-44 * 86400)
        let last = Date()
        return HStack(spacing: 8) {
            Text("From")
            DatePicker("From", selection: model.customFrom, in: first...last, displayedComponents: .date).labelsHidden()
            Text("to")
            DatePicker("To", selection: model.customTo, in: first...last, displayedComponents: .date).labelsHidden()
            Spacer()
        }
        .font(K.font(13))
        .controlSize(K.control)
        .padding(.horizontal, 8)
    }

    /// What a share is, and what it is not.
    var note: some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: "info.circle").font(.system(size: 14 * K.zoom)).foregroundColor(K.infoMark).accessibilityHidden(true)
            (Text("Each bar is the session's share of ") + Text("your use").font(K.font(12.5, true))
             + Text(" in this period. It is not a percent of your limit: Anthropic gives only the total percent."))
                .font(K.font(12.5)).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(K.infoSoft, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(K.infoBorder))
    }

    /// "72 sessions · 8.1 billion tokens · agents did 80% · worth $3,106 at API prices", what the same work takes
    /// people ("Human work ≈ 1 person for 4.7 months · ≈ 20 people full time over these 7 days", with its ⓘ), and the
    /// legend.
    func totals(_ r: SessionUsage.Report) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            (Text("\(r.lines.count)").font(K.font(12.5, true)) + Text(r.lines.count == 1 ? " session · " : " sessions · ")
             + Text(SessionUsage.tokens(r.tokens) + " tokens · agents did ") + Text(SessionUsage.percent(r.share(r.agents))).font(K.font(12.5, true))
             + Text(" · worth " + SessionUsage.dollars(r.usd) + " at API prices"))
                .font(K.font(12.5)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
            if r.human > 0 { human(r) }
            UsageLegend()
        }
        .padding(.horizontal, 8)
        .padding(.bottom, 6)
    }

    /// "Human work ≈ 1 person for 4.7 months · ≈ 20 people full time over these 7 days", its ⓘ, and the note it opens.
    func human(_ r: SessionUsage.Report) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                (Text("Human work ").foregroundColor(K.steel) + Text("≈ " + SessionUsage.personWords(r.human)).font(K.font(13, true))
                 + Text(" · ").foregroundColor(K.steel)
                 + Text(SessionUsage.peopleWords(r.human, model.usagePeriod, from: r.from, to: r.to)).font(K.font(13, true)))
                    .font(K.font(13)).foregroundColor(K.ink).fixedSize(horizontal: false, vertical: true)
                InfoButton(open: model.note("usage-human"), label: "How human work is estimated")
            }
            InfoNote(text: SessionUsage.humanNote(model.usageData.kinds), open: model.note("usage-human"))
        }
    }

    @ViewBuilder func more(_ r: SessionUsage.Report) -> some View {
        if r.lines.count > UsagePage.shown {
            let rest = r.lines.dropFirst(UsagePage.shown)
            Hairline().padding(.horizontal, 10).padding(.top, 2)
            HStack {
                Text(model.usageAll ? "All \(r.lines.count) sessions"
                     : "\(rest.count) more session\(rest.count == 1 ? "" : "s") · " + SessionUsage.percent(r.share(rest.reduce(0) { $0 + $1.usd })) + " of your use")
                    .font(K.font(12.5)).foregroundColor(K.steel)
                Spacer()
                Button(model.usageAll ? "Show the top \(UsagePage.shown)" : "Show all") { model.usageAll.toggle() }
                    .controlSize(K.control)
            }
            .padding(.horizontal, 8).padding(.vertical, 10)
        }
    }

    var foot: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Only Claude Code's use on this Mac is here, from its sessions' records. Use in the Claude app, in the cloud or on other computers is not.")
            if !model.usageData.unpriced.isEmpty {
                Text("The Kit has no price for \(model.usageData.unpriced.keys.sorted().joined(separator: ", ")): its use counts at the price of its family until an update adds one.")
                    .foregroundColor(K.warnText)
            }
        }
        .font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
        .padding(.horizontal, 8)
    }
}

/// An ⓘ beside what it explains. It opens its note in place under it (InfoNote), which pushes what is below down;
/// the note closes from its own X or a second click on the ⓘ. Never a tooltip: nothing important hides behind hover.
struct InfoButton: View {
    @Binding var open: Bool
    let label: String
    var body: some View {
        Button { open.toggle() } label: {
            Image(systemName: open ? "info.circle.fill" : "info.circle").font(.system(size: 14 * K.zoom)).foregroundColor(K.infoMark)
                .frame(width: K.z(20), height: K.z(20)).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityValue(open ? "open" : "closed")
    }
}

/// The note an InfoButton opens, in place, with its own X.
struct InfoNote: View {
    let text: String
    @Binding var open: Bool
    var body: some View {
        if open {
            HStack(alignment: .top, spacing: 8) {
                Text(text).font(K.font(12.5)).foregroundColor(K.ink).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                Spacer(minLength: 0)
                Button { open = false } label: {
                    Image(systemName: "xmark").font(.system(size: 11 * K.zoom, weight: .semibold)).foregroundColor(K.steel)
                        .frame(width: K.z(20), height: K.z(20)).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close")
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(K.infoSoft, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(K.infoBorder))
        }
    }
}

/// The two data colors, named.
struct UsageLegend: View {
    var own: String = ""
    var agents: String = ""
    var body: some View {
        HStack(spacing: 14) {
            item(K.session, "The session" + (own.isEmpty ? "" : " " + own))
            item(K.agents, "Its agents" + (agents.isEmpty ? "" : " " + agents))
        }
        .font(K.font(12)).foregroundColor(K.steel)
    }

    func item(_ c: Color, _ words: String) -> some View {
        HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 2).fill(c).frame(width: 10, height: 10)
            Text(words)
        }
    }
}

/// A bar in two parts, the session's own use then its agents', with a 2 pt gap: `fraction` of the width.
struct UsageBar: View {
    let own: Double
    let agents: Double
    var fraction: Double = 1
    var body: some View {
        GeometryReader { g in
            let w = max(0, g.size.width * min(1, max(0, fraction)))
            let total = max(own + agents, 1e-12)
            let both = own > 0 && agents > 0
            let room = max(0, w - (both ? 2 : 0))
            HStack(spacing: 2) {
                if own > 0 { RoundedRectangle(cornerRadius: 2).fill(K.session).frame(width: max(2, room * own / total)) }
                if agents > 0 { RoundedRectangle(cornerRadius: 2).fill(K.agents).frame(width: max(2, room * agents / total)) }
            }
        }
        .accessibilityHidden(true)
    }
}

/// One session in the list: its name and share, when it was last active and how many agents it started, and its bar.
struct UsageRow: View {
    let line: SessionUsage.Line
    let share: Double
    let top: Double
    let selected: Bool
    let multiDay: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(line.session.title).font(K.font(13.5, true)).lineLimit(1)
                Spacer(minLength: 8)
                Text(SessionUsage.percent1(share)).font(K.font(13.5, true)).monospacedDigit()
            }
            Text(meta).font(K.font(12)).foregroundColor(K.steel).lineLimit(1)
            UsageBar(own: line.own, agents: line.agents, fraction: top > 0 ? line.usd / top : 0)
                .frame(height: 8)
                .padding(.top, 4)
                .help("The session: \(SessionUsage.percent(share * line.own / max(line.usd, 1e-12))) of your use · its agents: "
                      + "\(SessionUsage.percent(share * line.agents / max(line.usd, 1e-12))) of your use · "
                      + "\(SessionUsage.tokens(line.tokens)) tokens · \(SessionUsage.dollars(line.usd)) at API prices")
        }
        .padding(.horizontal, K.z(10))
        .padding(.vertical, K.z(8))
        .background(selected ? K.wash : .clear, in: RoundedRectangle(cornerRadius: 6))
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(line.session.title), \(SessionUsage.percent1(share)) of your use, \(meta)")
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    var meta: String {
        var parts: [String] = []
        if line.session.kind == "local" { parts.append("only on this Mac") }
        if let last = line.session.last { parts.append("last active " + SessionUsage.lastWords(last)) }
        if line.started > 0 { parts.append("\(line.started) agent\(line.started == 1 ? "" : "s")") }
        if line.human > 0 { parts.append("≈ " + SessionUsage.personWords(line.human)) }
        return parts.joined(separator: " · ")
    }
}

/// The selected session: its share and its split, tokens, agents started, its use at API prices, a bar for each day,
/// and its models. Open opens it in the Claude app, as on the Sessions page.
struct UsageDetail: View {
    @ObservedObject var model: KitModel
    let line: SessionUsage.Line
    let report: SessionUsage.Report

    var body: some View {
        let share = report.share(line.usd)
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 8) {
                    Text(line.session.title).font(K.font(19, true)).fixedSize(horizontal: false, vertical: true)
                    Spacer()
                    open
                }
                Text(what).font(K.font(12.5)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true).padding(.top, 3)
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(SessionUsage.percent1(share)).font(K.font(28, true)).monospacedDigit()
                    Text("of your use, " + SessionUsage.spanWords(from: report.from, to: report.to)).foregroundColor(K.steel)
                }
                .padding(.top, 14)
                UsageBar(own: line.own, agents: line.agents).frame(height: 10).padding(.top, 6)
                UsageLegend(own: SessionUsage.percent(line.own / max(line.usd, 1e-12)), agents: SessionUsage.percent(line.agents / max(line.usd, 1e-12)))
                    .padding(.top, 8)
                FactsBox(pairs: [("Tokens", SessionUsage.tokens(line.tokens)), ("Agents", "\(line.started) started"),
                                 ("At API prices", SessionUsage.dollars(line.usd))]
                         + (line.active > 0 ? [("At work", SessionUsage.hoursWords(line.active) + ", waits left out")] : []))
                    .padding(.top, 14)
                if line.human > 0 { human }
                if report.from != report.to { days }
                models
            }
            .padding(K.z(16))
            .textSelection(.enabled)
        }
        .controlSize(K.control)
    }

    @ViewBuilder var open: some View {
        if let cse = line.session.cse {
            Button { Waiting.open(Phone.link("", cse: cse), id: cse) } label: { Label("Open", systemImage: "arrow.up.right").labelStyle(TrailingIcon()) }
                .controlSize(K.control)
                .help("Opens this session in the Claude app.")
        } else if line.session.kind == "local", model.snapHas("local:" + line.session.key.dropFirst(4)) {
            Button("Show it") { model.selected = "local:" + line.session.key.dropFirst(4); model.page = .sessions }
                .controlSize(K.control)
                .help("Opens it on the Sessions page, under On this Mac only.")
        }
    }

    /// What the row is, and when it was last active.
    var what: String {
        let last = line.session.last.map { "last active " + SessionUsage.lastWords($0) } ?? ""
        let kind: String
        switch line.session.kind {
        case "local": kind = "Only on this Mac, with no Remote Control link"
        case "runs": kind = "Runs with no name and no link in this folder, as one row"
        case "kit": kind = "The Kit's own checks, such as wait checks"
        case "temp": kind = "Claude Code runs in temporary folders, such as tests"
        default: kind = ""
        }
        return [kind, last].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// What the session's work takes people: one person's time, people full time in the period, and its human hours
    /// by kind of work, with the ⓘ that says how it is estimated.
    var human: some View {
        let kinds = model.usageData.kinds
        let byKind = line.humanByKind.filter { $0.value >= 0.05 && kinds.indices.contains($0.key) }.sorted { $0.value > $1.value }
        let total = "≈ " + SessionUsage.hoursWords(line.human)
        // one kind: "≈ 261 h of software work"; more: "≈ 261 h of work: software 200 h, design 61 h"
        let split = byKind.count == 1 ? total + " of " + kinds[byKind[0].key].name.lowercased() + " work"
            : total + " of work" + (byKind.isEmpty ? "" : ": " + byKind.map { kinds[$0.key].name.lowercased() + " " + SessionUsage.hoursWords($0.value) }.joined(separator: ", "))
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text("Human work").font(K.font(13, true))
                InfoButton(open: model.note("usage-human-session"), label: "How human work is estimated")
                Spacer()
            }
            InfoNote(text: SessionUsage.humanNote(kinds), open: model.note("usage-human-session")).padding(.vertical, 3)
            Text("≈ " + SessionUsage.personWords(line.human)).font(K.font(17, true)).fixedSize(horizontal: false, vertical: true)
            Text(SessionUsage.peopleWords(line.human, model.usagePeriod, from: report.from, to: report.to))
                .font(K.font(12.5)).fixedSize(horizontal: false, vertical: true)
            Text(split).font(K.font(12)).foregroundColor(K.steel).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, 18)
    }

    /// A bar for each day of the period, the session's own use at the foot and its agents' above it.
    var days: some View {
        let list = report.dayList
        let top = list.map { (line.byDay[$0]?.own ?? 0) + (line.byDay[$0]?.agents ?? 0) }.max() ?? 0
        return VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline) {
                Text("Days").font(K.font(13, true))
                Spacer()
                Text("tallest day: " + SessionUsage.percent(line.usd > 0 ? top / line.usd : 0) + " of its use").font(K.font(12)).foregroundColor(K.steel)
            }
            .padding(.top, 18)
            GeometryReader { g in
                HStack(alignment: .bottom, spacing: list.count > 20 ? 1 : 2) {
                    ForEach(list, id: \.self) { d in
                        let v = line.byDay[d] ?? (0, 0)
                        let h = g.size.height
                        VStack(spacing: 1) {
                            Spacer(minLength: 0)
                            if v.agents > 0 { Rectangle().fill(K.agents).frame(height: max(1, h * v.agents / max(top, 1e-12))) }
                            if v.own > 0 { Rectangle().fill(K.session).frame(height: max(1, h * v.own / max(top, 1e-12))) }
                        }
                        .frame(maxWidth: .infinity)
                        .contentShape(Rectangle())
                        .help(dayHelp(d, v))
                    }
                }
            }
            .frame(height: K.z(110))
            Rectangle().fill(K.line).frame(height: 1)
            HStack {
                Text(SessionUsage.dayWords(list.first ?? report.from))
                Spacer()
                if list.count > 2 { Text(SessionUsage.dayWords(list[list.count / 2])); Spacer() }
                Text(SessionUsage.dayWords(list.last ?? report.to))
            }
            .font(K.font(12)).foregroundColor(K.steel)
        }
    }

    func dayHelp(_ d: String, _ v: (own: Double, agents: Double)) -> String {
        let s = v.own + v.agents
        guard s > 0 else { return SessionUsage.dayWords(d, weekday: true) + ": no use" }
        return SessionUsage.dayWords(d, weekday: true) + ": " + SessionUsage.percent(s / max(line.usd, 1e-12)) + " of this session's use · "
            + SessionUsage.percent(s / max(report.byDay[d] ?? s, 1e-12)) + " of all your use that day · agents " + SessionUsage.percent(v.agents / s)
            + " · " + SessionUsage.dollars(s)
    }

    /// Each model's part of the session's use, with its tokens and its use at API prices.
    var models: some View {
        let list = line.byModel.sorted { $0.value.usd > $1.value.usd }.filter { $0.value.usd > 0 }
        return VStack(alignment: .leading, spacing: 8) {
            Text("Models").font(K.font(13, true)).padding(.top, 18)
            ForEach(list, id: \.key) { m, v in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 8) {
                        Text(model.usageData.models.indices.contains(m) ? model.usageData.models[m].name : "?").frame(width: K.z(82), alignment: .leading)
                        GeometryReader { g in
                            ZStack(alignment: .leading) {
                                Capsule().fill(K.track)
                                Capsule().fill(K.steel).frame(width: g.size.width * min(1, v.usd / max(line.usd, 1e-12)))
                            }
                        }
                        .frame(height: 6)
                        Text(SessionUsage.percent(v.usd / max(line.usd, 1e-12))).font(K.font(13, true)).monospacedDigit().frame(width: K.z(46), alignment: .trailing)
                    }
                    Text(SessionUsage.tokens(v.tokens) + " tokens · " + SessionUsage.dollars(v.usd)).font(K.font(12)).foregroundColor(K.steel)
                }
            }
        }
    }
}
