// Sttark Effort's Chrome approver: watches Google Chrome for the Claude for Chrome
// "New permissions required" window and approves it. Presses "Always allow actions on
// this site" when offered, else "Allow this action". Never presses Decline, and only acts
// inside the Claude extension's own pages, never on ordinary web pages. Runs at login when
// "Approve Claude in Chrome" is on in the Sttark Effort menu.
//
// Run with --dump to print what it sees in Claude windows instead of pressing anything.

import AppKit
import ApplicationServices

let chromeBundleID = "com.google.Chrome"
let extensionPrefix = "chrome-extension://fcoeoabgfenejglbffodgkkbkcdhcgfn/"
// Best first. Matched against the button's text, lowercased.
let approveLabels = ["always allow actions on this site", "allow this action"]
let neverPress = ["decline", "deny", "cancel", "stop"]
let pollSeconds = 0.4
let dumpMode = CommandLine.arguments.contains("--dump")

func log(_ message: String) {
    let stamp = ISO8601DateFormatter().string(from: Date())
    print("\(stamp) \(message)")
    fflush(stdout)
}

func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
    var result: AnyObject?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &result) == .success else { return nil }
    return result
}

func string(_ element: AXUIElement, _ name: String) -> String? {
    attribute(element, name) as? String
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    (attribute(element, kAXChildrenAttribute) as? [AXUIElement]) ?? []
}

func role(_ element: AXUIElement) -> String {
    string(element, kAXRoleAttribute) ?? ""
}

func url(_ element: AXUIElement) -> String {
    (attribute(element, "AXURL") as? NSURL)?.absoluteString ?? ""
}

// Visible text of an element: its own label, or its children's text if it has none.
func text(_ element: AXUIElement, depth: Int = 0) -> String {
    let own = [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute]
        .compactMap { string(element, $0) }
        .filter { !$0.isEmpty }
    if !own.isEmpty || depth > 4 { return own.joined(separator: " ") }
    return children(element).map { text($0, depth: depth + 1) }.filter { !$0.isEmpty }.joined(separator: " ")
}

// Web areas belonging to the Claude extension. Ordinary pages are skipped, not walked.
func extensionWebAreas(_ element: AXUIElement, budget: inout Int, into found: inout [AXUIElement]) {
    guard budget > 0 else { return }
    budget -= 1
    if role(element) == "AXWebArea" {
        if url(element).hasPrefix(extensionPrefix) { found.append(element) }
        return
    }
    for child in children(element) { extensionWebAreas(child, budget: &budget, into: &found) }
}

func buttonsAndText(_ element: AXUIElement, budget: inout Int,
                    buttons: inout [(AXUIElement, String)], words: inout [String]) {
    guard budget > 0 else { return }
    budget -= 1
    switch role(element) {
    case kAXButtonRole:
        buttons.append((element, text(element).lowercased()))
        return
    case kAXStaticTextRole:
        if let value = string(element, kAXValueAttribute), !value.isEmpty { words.append(value) }
    default:
        break
    }
    for child in children(element) { buttonsAndText(child, budget: &budget, buttons: &buttons, words: &words) }
}

func dumpTree(_ element: AXUIElement, depth: Int = 0) {
    guard depth < 25 else { return }
    let indent = String(repeating: "  ", count: depth)
    print("\(indent)\(role(element)) \"\(text(element, depth: 5))\" \(url(element))")
    for child in children(element) { dumpTree(child, depth: depth + 1) }
}

var accessibilityPid: pid_t = 0
var lastPress: [String: Date] = [:]
var lastUnknown = ""

func enableWebAccessibility(_ app: AXUIElement, pid: pid_t) {
    guard accessibilityPid != pid else { return }
    accessibilityPid = pid
    let manual = AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
    if manual != .success {
        AXUIElementSetAttributeValue(app, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
    }
}

func tick() {
    guard AXIsProcessTrusted() else { return }
    guard let chrome = NSRunningApplication.runningApplications(withBundleIdentifier: chromeBundleID).first else { return }
    let app = AXUIElementCreateApplication(chrome.processIdentifier)
    enableWebAccessibility(app, pid: chrome.processIdentifier)

    for window in (attribute(app, kAXWindowsAttribute) as? [AXUIElement]) ?? [] {
        let title = string(window, kAXTitleAttribute) ?? ""
        guard title.localizedCaseInsensitiveContains("claude") else { continue }
        if let last = lastPress[title], Date().timeIntervalSince(last) < 1 { continue }

        var budget = 400
        var areas: [AXUIElement] = []
        extensionWebAreas(window, budget: &budget, into: &areas)

        for area in areas {
            if dumpMode { print("== window \"\(title)\""); dumpTree(area); continue }

            var nodeBudget = 3000
            var buttons: [(AXUIElement, String)] = []
            var words: [String] = []
            buttonsAndText(area, budget: &nodeBudget, buttons: &buttons, words: &words)
            let safe = buttons.filter { button in !neverPress.contains { button.1.hasPrefix($0) } }

            let match = approveLabels.lazy.compactMap { label in safe.first { $0.1.contains(label) } }.first
            if let (button, label) = match {
                let result = AXUIElementPerformAction(button, kAXPressAction as CFString)
                lastPress[title] = Date()
                let summary = words.joined(separator: " ").prefix(200)
                log("pressed \"\(label)\" (result \(result.rawValue)): \(summary)")
            } else if !buttons.isEmpty && words.joined().localizedCaseInsensitiveContains("permission") {
                // A permission prompt we don't know how to answer yet. Log once so it can be added.
                let seen = buttons.map { $0.1 }.joined(separator: " | ")
                if seen != lastUnknown {
                    lastUnknown = seen
                    log("unknown prompt, buttons: \(seen) :: \(words.joined(separator: " ").prefix(200))")
                }
            }
        }
    }
    if dumpMode { exit(0) }
}

let trusted = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
log("started, accessibility access: \(trusted ? "yes" : "no, waiting for it in System Settings")")

if dumpMode {
    tick()
    exit(0)
}

var wasTrusted = trusted
Timer.scheduledTimer(withTimeInterval: pollSeconds, repeats: true) { _ in
    let now = AXIsProcessTrusted()
    if now != wasTrusted {
        wasTrusted = now
        accessibilityPid = 0
        log("accessibility access: \(now ? "granted" : "removed")")
    }
    tick()
}
RunLoop.main.run()
