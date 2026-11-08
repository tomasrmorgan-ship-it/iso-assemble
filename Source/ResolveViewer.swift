import Cocoa
import ApplicationServices

enum ResolveViewerStatus: String {
    case ready
    case needsPermission
    case unavailable
    case interrupted
    case failed
}

struct ResolveViewerResult {
    let status: ResolveViewerStatus
    let message: String
    /// Only controls actually read during this attempt are included.
    let controlStates: [String: Bool]
    /// Accessibility readback is not a visual inspection of the angle grid.
    let visuallyVerified = false
    var manualFallback: String { ResolveViewer.manualFallback }
}

/// Call after the supported Resolve API has opened the intended project's Edit
/// page. This helper prepares viewer controls only; it never saves or changes a
/// project, and its result is independent of the completed DRP export.
enum ResolveViewer {
    static var hasAccessibilityPermission: Bool { AXIsProcessTrusted() }
    static let manualFallback = "In the intended project's Edit page, select Timeline, hide Inspector, enable Multicam beneath the viewer, choose Video Only to keep the independent audio mix, use Full Extent Zoom above the timeline, and show Media Pool. If only the program viewer remains, turn off Single Viewer Mode in Resolve's Workspace menu."

    private static let bundleID = "com.blackmagic-design.DaVinciResolve"
    private static let queue = DispatchQueue(label: "org.isoassemble.resolve-viewer", qos: .userInitiated)
    private static let desiredStates: [(String, Bool)] = [
        ("Timeline", true),
        ("Inspector", false),
        ("Multicam", true),
        ("Video Only", true),
        ("Full Extent Zoom", true),
        ("Media Pool", true)
    ]

    /// Invoke only from an explicit permission action in the app. The system
    /// prompt does not grant permission; the user must approve it in Settings.
    @discardableResult
    static func requestAccessibilityPermission() -> Bool {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    /// Runs asynchronously. Both progress and completion are delivered on main.
    /// No Accessibility prompt is displayed automatically.
    static func prepare(expectedProject: String,
                        progress: ((String) -> Void)? = nil,
                        completion: @escaping (ResolveViewerResult) -> Void) {
        queue.async {
            let result = prepareNow(expectedProject: expectedProject) { message in
                DispatchQueue.main.async { progress?(message) }
            }
            DispatchQueue.main.async { completion(result) }
        }
    }

    private struct Context {
        let app: NSRunningApplication
        let application: AXUIElement
        let expectedProject: String
        let deadline: TimeInterval
    }

    private enum Stop: Error {
        case unavailable(String)
        case interrupted(String)
        case failed(String)
    }

    private static var now: TimeInterval { ProcessInfo.processInfo.systemUptime }

    private static func onMain<T>(_ action: () -> T) -> T {
        if Thread.isMainThread { return action() }
        return DispatchQueue.main.sync(execute: action)
    }

    private static func prepareNow(expectedProject: String,
                                   progress: (String) -> Void) -> ResolveViewerResult {
        var states: [String: Bool] = [:]
        let project = expectedProject.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !project.isEmpty else {
            return ResolveViewerResult(status: .failed,
                message: "Viewer preparation needs the expected Resolve project name.", controlStates: states)
        }
        guard AXIsProcessTrusted() else {
            return ResolveViewerResult(status: .needsPermission,
                message: "Automatic viewer preparation needs Accessibility permission for ISO Assemble in System Settings → Privacy & Security → Accessibility. Enable it and retry, or prepare the viewer manually. " + manualFallback,
                controlStates: states)
        }
        let running = onMain {
            NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
                .filter { !$0.isTerminated }
        }
        guard running.count == 1, let app = running.first else {
            return ResolveViewerResult(status: .unavailable,
                message: "Viewer preparation needs one running Resolve application with the intended project open on Edit.",
                controlStates: states)
        }
        let application = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(application, 0.35)
        let context = Context(app: app, application: application,
                              expectedProject: project, deadline: now + 32)
        do {
            progress("Preparing Resolve's multicam viewer controls…")
            guard onMain({ app.activate(options: [.activateIgnoringOtherApps]) }) else {
                throw Stop.unavailable("Resolve could not be activated. Open the intended project's Edit page and retry.")
            }
            try waitForActivation(context)
            _ = try currentWindow(context)
            for (label, desired) in desiredStates {
                let control = try waitForControl(label, context: context, deadline: min(now + 5, context.deadline))
                if label == "Video Only" && booleanAttribute(control, kAXEnabledAttribute) != true {
                    throw Stop.unavailable("The multicam source-viewer controls are not enabled. Hide Inspector and turn off Single Viewer Mode, then retry. " + manualFallback)
                }
                guard let value = checkboxValue(control) else {
                    throw Stop.failed("The state of Resolve's \(label) control could not be read.")
                }
                states[label] = value
                if value != desired {
                    progress(desired ? "Enabling \(label)…" : "Hiding \(label)…")
                    try click(control, label: label, context: context)
                    try waitForValue(label, desired: desired, context: context, states: &states)
                    // Give Qt time to finish pane changes before finding the next control.
                    Thread.sleep(forTimeInterval: 0.18)
                    _ = try currentWindow(context)
                }
            }
            // Later pane changes can affect earlier controls. Read all states
            // again rather than treating a posted mouse click as success.
            for (label, desired) in desiredStates {
                let control = try waitForControl(label, context: context, deadline: min(now + 2, context.deadline))
                if label == "Video Only" && booleanAttribute(control, kAXEnabledAttribute) != true {
                    throw Stop.unavailable("The multicam source-viewer controls are no longer enabled. " + manualFallback)
                }
                guard let value = checkboxValue(control) else {
                    throw Stop.failed("Resolve's \(label) state could not be confirmed after preparing the viewer.")
                }
                states[label] = value
                guard value == desired else {
                    throw Stop.failed("Resolve changed its \(label) control while preparing the layout. Use the manual viewer steps or retry.")
                }
            }
            _ = try currentWindow(context)
            return ResolveViewerResult(status: .ready,
                message: "Viewer control states are confirmed: Timeline, Multicam, Video Only, Full Extent Zoom and Media Pool are on; Inspector is off. The Video Only source-viewer control is enabled. Visual appearance has not been inspected.",
                controlStates: states)
        } catch let error as Stop {
            switch error {
            case .unavailable(let message):
                return ResolveViewerResult(status: .unavailable, message: message, controlStates: states)
            case .interrupted(let message):
                return ResolveViewerResult(status: .interrupted, message: message, controlStates: states)
            case .failed(let message):
                return ResolveViewerResult(status: .failed, message: message, controlStates: states)
            }
        } catch {
            return ResolveViewerResult(status: .failed,
                message: "Viewer preparation stopped: \(error.localizedDescription)", controlStates: states)
        }
    }

    private static func waitForActivation(_ context: Context) throws {
        let deadline = min(now + 3, context.deadline)
        while now < deadline {
            if onMain({ NSWorkspace.shared.frontmostApplication?.processIdentifier }) == context.app.processIdentifier {
                return
            }
            if context.app.isTerminated { throw Stop.unavailable("Resolve closed before viewer preparation.") }
            Thread.sleep(forTimeInterval: 0.10)
        }
        throw Stop.unavailable("Resolve did not become the frontmost application. Activate it and retry viewer preparation.")
    }

    private static func currentWindow(_ context: Context) throws -> AXUIElement {
        guard now < context.deadline else {
            throw Stop.unavailable("Resolve's viewer controls did not become ready in time. Open Edit and retry, or use the manual steps.")
        }
        guard onMain({ NSWorkspace.shared.frontmostApplication?.processIdentifier }) == context.app.processIdentifier else {
            throw Stop.interrupted("Viewer preparation stopped because Resolve is no longer frontmost. Activate the intended project and retry.")
        }
        guard AXIsProcessTrusted() else {
            throw Stop.interrupted("Accessibility access changed during viewer preparation. Check ISO Assemble's permission before retrying.")
        }
        guard let value = attribute(context.application, kAXFocusedWindowAttribute),
              CFGetTypeID(value) == AXUIElementGetTypeID() else {
            throw Stop.unavailable("Resolve's focused project window could not be read. Open the intended project on Edit and retry.")
        }
        let window = value as! AXUIElement
        guard let title = stringAttribute(window, kAXTitleAttribute), title.contains(context.expectedProject) else {
            throw Stop.interrupted("Viewer preparation stopped because the focused Resolve window does not identify the expected project, \(context.expectedProject).")
        }
        return window
    }

    private static func waitForControl(_ label: String, context: Context,
                                       deadline: TimeInterval) throws -> AXUIElement {
        while now < deadline {
            let window = try currentWindow(context)
            let matches = try findControls(label, window: window, context: context, deadline: deadline)
            guard matches.count <= 1 else {
                throw Stop.failed("Resolve exposes more than one visible \(label) control. No control was selected automatically.")
            }
            if let match = matches.first { return match }
            Thread.sleep(forTimeInterval: 0.15)
        }
        throw Stop.unavailable("Resolve's \(label) control is not available in the expected Edit window. Use the manual viewer steps.")
    }

    private static func findControls(_ label: String, window: AXUIElement,
                                     context: Context, deadline: TimeInterval) throws -> [AXUIElement] {
        guard let windowBounds = bounds(window) else {
            throw Stop.unavailable("Resolve's project window bounds could not be read.")
        }
        var stack: [(AXUIElement, Int)] = [(window, 0)]
        var seen = Set<CFHashCode>()
        var matches: [AXUIElement] = []
        var visited = 0
        while let (element, depth) = stack.popLast() {
            guard now < deadline, now < context.deadline else {
                throw Stop.unavailable("Resolve's \(label) controls could not be inspected completely in time. No uncertain control was selected.")
            }
            if visited % 32 == 0 { _ = try currentWindow(context) }
            guard seen.insert(CFHash(element)).inserted else { continue }
            visited += 1
            guard visited <= 4_000, depth <= 40 else {
                throw Stop.unavailable("Resolve's accessibility layout is larger than expected. Use the manual viewer steps.")
            }
            if stringAttribute(element, kAXRoleAttribute) == (kAXCheckBoxRole as String),
               (stringAttribute(element, kAXDescriptionAttribute) == label ||
                stringAttribute(element, kAXTitleAttribute) == label),
               let rect = bounds(element), rect.width > 0, rect.height > 0,
               windowBounds.contains(CGPoint(x: rect.midX, y: rect.midY)) {
                matches.append(element)
            }
            if let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] {
                for child in children.reversed() { stack.append((child, depth + 1)) }
            }
        }
        return matches
    }

    private static func waitForValue(_ label: String, desired: Bool, context: Context,
                                     states: inout [String: Bool]) throws {
        let deadline = min(now + 4, context.deadline)
        while now < deadline {
            let control = try waitForControl(label, context: context, deadline: deadline)
            if let value = checkboxValue(control) {
                states[label] = value
                if value == desired { return }
            }
            Thread.sleep(forTimeInterval: 0.12)
        }
        throw Stop.failed("Resolve did not confirm the requested \(label) state. No further viewer controls were changed.")
    }

    private static func click(_ element: AXUIElement, label: String, context: Context) throws {
        let window = try currentWindow(context)
        guard booleanAttribute(element, kAXEnabledAttribute) == true,
              let rect = bounds(element), let windowRect = bounds(window),
              rect.width >= 2, rect.height >= 2 else {
            throw Stop.unavailable("Resolve's \(label) control is disabled or has no usable bounds.")
        }
        let center = CGPoint(x: rect.midX, y: rect.midY)
        guard windowRect.contains(center), center.x.isFinite, center.y.isFinite else {
            throw Stop.failed("Resolve's \(label) control is outside the verified project window.")
        }
        var display: CGDirectDisplayID = 0
        var count: UInt32 = 0
        guard CGGetDisplaysWithPoint(center, 1, &display, &count) == .success, count == 1 else {
            throw Stop.unavailable("Resolve's \(label) control is off screen. Move the project window onto a display and retry.")
        }
        guard hitMatches(element, at: center) else {
            throw Stop.interrupted("Resolve's \(label) control is covered or its position changed. Viewer preparation stopped before clicking.")
        }
        _ = try currentWindow(context)
        guard let source = CGEventSource(stateID: .hidSystemState),
              let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown,
                                 mouseCursorPosition: center, mouseButton: .left),
              let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp,
                               mouseCursorPosition: center, mouseButton: .left) else {
            throw Stop.failed("Could not prepare the native mouse event for Resolve's \(label) control.")
        }
        // Qt's AXPress can change the AX value without invoking the real UI
        // slot. Use the AX-derived center, then verify fresh AX state instead.
        down.setIntegerValueField(.mouseEventClickState, value: 1)
        up.setIntegerValueField(.mouseEventClickState, value: 1)
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
    }

    private static func hitMatches(_ expected: AXUIElement, at point: CGPoint) -> Bool {
        var hit: AXUIElement?
        let system = AXUIElementCreateSystemWide()
        AXUIElementSetMessagingTimeout(system, 0.35)
        guard AXUIElementCopyElementAtPosition(system, Float(point.x), Float(point.y), &hit) == .success else {
            return false
        }
        var current = hit
        for _ in 0..<20 {
            guard let element = current else { return false }
            if CFEqual(element, expected) { return true }
            guard let parent = attribute(element, kAXParentAttribute),
                  CFGetTypeID(parent) == AXUIElementGetTypeID() else { return false }
            current = (parent as! AXUIElement)
        }
        return false
    }

    private static func attribute(_ element: AXUIElement, _ key: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, key as CFString, &value) == .success else { return nil }
        return value
    }

    private static func stringAttribute(_ element: AXUIElement, _ key: String) -> String? {
        attribute(element, key) as? String
    }

    private static func booleanAttribute(_ element: AXUIElement, _ key: String) -> Bool? {
        guard let value = attribute(element, key) else { return nil }
        if let number = value as? NSNumber {
            if number.intValue == 0 { return false }
            if number.intValue == 1 { return true }
        }
        if let string = value as? String {
            if string == "0" { return false }
            if string == "1" { return true }
        }
        return nil
    }

    private static func checkboxValue(_ element: AXUIElement) -> Bool? {
        booleanAttribute(element, kAXValueAttribute)
    }

    private static func bounds(_ element: AXUIElement) -> CGRect? {
        guard let p = attribute(element, kAXPositionAttribute),
              let s = attribute(element, kAXSizeAttribute),
              CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
        let pointValue = p as! AXValue, sizeValue = s as! AXValue
        guard AXValueGetType(pointValue) == .cgPoint, AXValueGetType(sizeValue) == .cgSize else { return nil }
        var point = CGPoint.zero, size = CGSize.zero
        guard AXValueGetValue(pointValue, .cgPoint, &point), AXValueGetValue(sizeValue, .cgSize, &size),
              point.x.isFinite, point.y.isFinite, size.width.isFinite, size.height.isFinite,
              size.width > 0, size.height > 0 else { return nil }
        return CGRect(origin: point, size: size)
    }
}
