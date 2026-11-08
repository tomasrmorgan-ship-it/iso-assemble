import Foundation

/// Compiled with the production helper. Never requests Accessibility access or
/// runs the interactive branch against the user's open Resolve project.
@main
enum ResolveViewerTests {
    struct Failure: Error, CustomStringConvertible {
        let description: String
    }

    static func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
        if !condition() { throw Failure(description: message) }
    }

    static func result(_ status: ResolveViewerStatus,
                       _ states: [String: Bool]) -> ResolveViewerResult {
        ResolveViewerResult(status: status, message: "Test observation", controlStates: states)
    }

    static func checkReportedOutcomes() throws {
        let ready = result(.ready, ["Timeline": true, "Full Extent Zoom": true,
                                   "Multicam": true, "Video Only": true])
        try require(ready.timelineFitted, "A confirmed full fit should be reported.")
        try require(!ready.visuallyVerified, "Control observations must not claim visual verification.")

        // A later camera-viewer failure must not erase independently confirmed
        // timeline fitting. This is the user-visible regression being fixed.
        let partial = result(.unavailable, ["Timeline": true, "Full Extent Zoom": true,
                                           "Inspector": false, "Multicam": false])
        try require(partial.timelineFitted, "A later viewer failure erased a confirmed fit.")
        try require(partial.status != .ready, "A partial fit must not claim full viewer readiness.")

        // The optional source-viewer Timeline selector can be hidden in single
        // viewer mode. It does not control the timeline's confirmed fit state.
        for states in [["Timeline": false, "Full Extent Zoom": true],
                       ["Full Extent Zoom": true]] {
            let fittedOnly = result(.unavailable, states)
            try require(fittedOnly.timelineFitted,
                        "An optional source-viewer selector incorrectly blocked a confirmed timeline fit.")
            try require(fittedOnly.status != .ready,
                        "Timeline fitting alone must not claim the multicam viewer is ready.")
        }
        for states in [["Timeline": true, "Full Extent Zoom": false],
                       ["Full Extent Zoom": false], ["Timeline": true], [:]] {
            let unknown = result(.ready, states)
            try require(!unknown.timelineFitted, "Missing/false full-extent observations were treated as a successful fit.")
            let before = unknown.controlStates
            _ = unknown.timelineFitted
            try require(unknown.controlStates == before, "Reading an outcome changed its observations.")
        }
        print("PASS: confirmed fit, partial viewer failure, and unknown-control outcomes")
    }

    static func prepareWithoutInteraction(_ expectedProject: String) throws -> ResolveViewerResult {
        var completionCount = 0
        var completionOnMain = false
        var progressMessages: [String] = []
        var completed: ResolveViewerResult?
        ResolveViewer.prepare(expectedProject: expectedProject, progress: { message in
            progressMessages.append(message)
        }, completion: { outcome in
            completionCount += 1
            completionOnMain = Thread.isMainThread
            completed = outcome
        })
        let deadline = Date().addingTimeInterval(5)
        while completed == nil && Date() < deadline {
            _ = RunLoop.main.run(mode: .default, before: Date().addingTimeInterval(0.02))
        }
        try require(completed != nil, "The real asynchronous helper did not finish within five seconds.")
        _ = RunLoop.main.run(mode: .default, before: Date().addingTimeInterval(0.05))
        try require(completionCount == 1, "The helper did not complete exactly once.")
        try require(completionOnMain, "The completion was not delivered on the main thread.")
        try require(progressMessages.isEmpty, "An early-exit request entered interactive viewer setup.")
        return completed!
    }

    static func checkRealEarlyExits() throws {
        let invalid = try prepareWithoutInteraction(" \n\t ")
        try require(invalid.status == .failed, "An empty project must fail before accessing Resolve.")
        try require(invalid.controlStates.isEmpty && !invalid.timelineFitted,
                    "An empty project reported controls that were never inspected.")
        try require(!invalid.visuallyVerified, "An early exit claimed visual verification.")
        print("PASS: actual prepare() empty-project asynchronous early exit")

        // A trusted test runner must not activate or click the user's editor.
        // Permission is observed only; this test never prompts or changes it.
        if ResolveViewer.hasAccessibilityPermission {
            print("SKIP: denied-permission test; this runner already has Accessibility trust. Interactive setup was not invoked.")
            return
        }
        let denied = try prepareWithoutInteraction("ISOAssemble_Noninteractive_Test")
        try require(denied.status == .needsPermission,
                    "The untrusted real helper did not return needsPermission.")
        try require(denied.controlStates.isEmpty && !denied.timelineFitted,
                    "The denied-permission path claimed a successful timeline fit.")
        try require(!denied.visuallyVerified, "Denied permission was reported as visually verified.")
        print("PASS: actual prepare() denied-permission path; no interactive setup or permission request")
    }

    static func main() {
        do {
            try checkReportedOutcomes()
            try checkRealEarlyExits()
            print("Resolve viewer tests passed. Granted-permission GUI automation is not tested by this harness.")
        } catch {
            FileHandle.standardError.write(Data("FAIL: \(error)\n".utf8))
            exit(1)
        }
    }
}
