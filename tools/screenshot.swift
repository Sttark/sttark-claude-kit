// Draws docs/menu.png for the README: the menu bar gauge (the app's own GaugeIcon) and the menu, with sample
// sessions and one hover tip, in light mode. Nothing from a real screen.
// Run: swiftc -parse-as-library -o /tmp/shot tools/screenshot.swift $(ls Sources/*.swift | grep -v main.swift) && /tmp/shot
import AppKit
import SwiftUI

struct Row: View {
    var title: String, right: String = "", check = false, chevron = false, dim = false, hot = false, bold = false
    var body: some View {
        HStack(spacing: 0) {
            Text(check ? "✓" : "").font(.system(size: 13, weight: .semibold)).frame(width: 22, alignment: .center)
            Text(title).font(.custom("Helvetica Neue", size: 14).weight(bold ? .semibold : .regular))
            Spacer(minLength: 24)
            if !right.isEmpty { Text(right).font(.custom("Helvetica Neue", size: 14).weight(.semibold)).foregroundStyle(hot ? .white.opacity(0.85) : .secondary) }
            if chevron { Image(systemName: "chevron.right").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary) }
        }
        .foregroundStyle(hot ? Color.white : dim ? Color.secondary : Color.primary)
        .padding(.horizontal, 6).frame(height: 24)
        .background(RoundedRectangle(cornerRadius: 5).fill(hot ? Color(nsColor: .controlAccentColor) : .clear))
        .padding(.horizontal, 5)
    }
}

struct Divider_: View {
    var body: some View { Rectangle().fill(Color.black.opacity(0.1)).frame(height: 1).padding(.horizontal, 14).padding(.vertical, 5) }
}

@main struct Shot {
    @MainActor static func main() {
        NSApplication.shared.appearance = NSAppearance(named: .aqua)
        let gauge = GaugeIcon.image("xhigh")
        let menu = VStack(alignment: .leading, spacing: 0) {
            Row(title: "Sttark Effort 1.28", dim: true)
            Divider_()
            Row(title: "Auto effort", check: true)
            Row(title: "Model: Sonnet 5.5", chevron: true)
            Divider_()
            Row(title: "Fix the login timeout on the order page", right: "Extra", check: true, hot: true)
            Row(title: "Rename report columns", right: "Low", check: true)
            Row(title: "Draft the press maintenance SOP", right: "Max · Manual")
            Divider_()
            Row(title: "Start sessions from the Claude app", check: true)
            Row(title: "Bypass permissions for server sessions", check: true)
            Row(title: "Approve Claude in Chrome", check: true)
            Row(title: "Name sessions automatically", check: true)
            Row(title: "Sync Claude profile instructions", check: true)
            Divider_()
            Row(title: "Sign in to Claude Code…")
            Row(title: "Open log")
            Row(title: "Check for updates")
            Divider_()
            Row(title: "Quit", right: "⌘Q")
        }
        .padding(.vertical, 5)
        .frame(width: 430)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(white: 0.975)))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.black.opacity(0.12)))
        .shadow(color: .black.opacity(0.18), radius: 14, y: 6)

        let tip = Text("Why Extra: Unknown cause across server and browser; needs careful debugging.\n\nAuto: Claude picks the effort. Click to set it yourself.")
            .font(.system(size: 11)).foregroundStyle(.primary).frame(width: 300, alignment: .leading)
            .padding(8).background(RoundedRectangle(cornerRadius: 5).fill(Color(white: 0.96)))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(Color.black.opacity(0.15)))
            .shadow(color: .black.opacity(0.12), radius: 6, y: 2)

        let view = VStack(alignment: .leading, spacing: 0) {
            // the menu bar, with the gauge as the app draws it
            HStack(spacing: 18) {
                Image(nsImage: gauge).renderingMode(.template).foregroundStyle(.black)
                    .padding(.horizontal, 6).padding(.vertical, 3)
                    .background(RoundedRectangle(cornerRadius: 5).fill(Color.black.opacity(0.1)))
                Spacer()
            }
            .padding(.horizontal, 24).frame(width: 790, height: 30, alignment: .leading)
            .background(Color(white: 0.93))
            ZStack(alignment: .topLeading) {
                menu.padding(.leading, 16).padding(.top, 4)
                tip.padding(.leading, 452).padding(.top, 150)
            }
            .frame(width: 790, height: 480, alignment: .topLeading)
        }
        .background(Color(red: 0.973, green: 0.961, blue: 0.949))   // brand Beige-Light

        let r = ImageRenderer(content: view)
        r.scale = 2
        guard let cg = r.cgImage else { fatalError("render failed") }
        let png = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:])!
        try! png.write(to: URL(fileURLWithPath: "docs/menu.png"))
        print("wrote docs/menu.png")
    }
}
