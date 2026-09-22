import Cocoa

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let folder = NSTextField(string: "")
    let output = NSTextField(string: "")
    let project = NSTextField(string: "")
    let target = NSPopUpButton(frame: .zero, pullsDown: false)
    var selectedATEM: String?
    var pendingProjectChoices: [String]?
    var premiereTimer: Timer?
    var pendingPremiere: (String,String)?
    let audio = NSPopUpButton(frame: .zero, pullsDown: false)
    let status = NSTextField(wrappingLabelWithString: "Choose the root folder from your ATEM recording drive.")
    let summary = NSTextField(wrappingLabelWithString: "Camera angles, live cuts, recording gaps and all audio ISOs stay together.")
    let log = NSTextView()
    let progress = NSProgressIndicator()
    var choose: NSButton!, destination: NSButton!, create: NSButton!, reveal: NSButton!, rescan: NSButton!
    var process: Process?
    var buffer = ""
    var choices: [String] = []
    var scannedOutput = ""
    var successPath: String?
    var logHandle: FileHandle?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu(); let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); appMenu.addItem(withTitle: "About ISO Assemble", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(.separator()); appMenu.addItem(withTitle: "Quit ISO Assemble", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); item.submenu = appMenu
        let editItem = NSMenuItem(); let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu; menu.addItem(editItem); NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0,y: 0,width: 800,height: 790), styleMask: [.titled,.closable,.miniaturizable], backing: .buffered, defer: false)
        window.title = "ISO Assemble"; window.center(); window.isReleasedWhenClosed = false
        let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 15
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 26)])
        let title = NSTextField(labelWithString: "ISO Assemble"); title.font = .systemFont(ofSize: 30, weight: .bold); stack.addArrangedSubview(title)
        let subtitle = NSTextField(labelWithString: "Your live edit. Every camera. Resolve or Premiere."); subtitle.font = .systemFont(ofSize: 14); subtitle.textColor = .secondaryLabelColor; stack.addArrangedSubview(subtitle)
        choose = button("Choose Recording Folder…", #selector(pickFolder)); folder.placeholderString = "Select an ATEM recording folder"; folder.isEditable = false
        addRow(stack, "Recording folder", [folder,choose])
        destination = button("Choose…", #selector(pickOutput)); output.placeholderString = "Project files and validation report"; output.isEditable = false
        addRow(stack, "Save results to", [output,destination])
        target.addItems(withTitles: ["DaVinci Resolve", "Adobe Premiere — Save As after import"]); target.target=self; target.action=#selector(targetChanged); addRow(stack,"Editing app",[target])
        project.placeholderString = "Resolve project name"; addRow(stack, "Project name", [project])
        audio.addItem(withTitle: "Scan a recording folder first"); audio.isEnabled = false; addRow(stack, "Primary audio", [audio])
        let note = NSTextField(wrappingLabelWithString: "All audio ISOs are imported. Only the primary source plays; camera switching does not change it."); note.font = .systemFont(ofSize: 12); note.textColor = .secondaryLabelColor; stack.addArrangedSubview(note); note.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        summary.font = .systemFont(ofSize: 14, weight: .medium); stack.addArrangedSubview(summary); summary.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        progress.style = .spinning; progress.controlSize = .small; progress.isDisplayedWhenStopped = false
        let statusRow = NSStackView(views: [progress,status]); statusRow.orientation = .horizontal; statusRow.spacing = 10; stack.addArrangedSubview(statusRow); statusRow.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder; scroll.documentView = log
        log.isEditable = false; log.isSelectable = true; log.font = .monospacedSystemFont(ofSize: 11, weight: .regular); log.textContainerInset = NSSize(width: 8,height: 8); log.autoresizingMask = [.width]; log.textContainer?.widthTracksTextView = true
        stack.addArrangedSubview(scroll); scroll.heightAnchor.constraint(equalToConstant: 160).isActive = true; scroll.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        rescan = button("Scan Again", #selector(scanAgain)); rescan.isEnabled = false
        reveal = button("Show Results", #selector(showResults)); reveal.isEnabled = false
        create = button("Create Resolve Project", #selector(buildProject)); create.bezelStyle = .rounded; create.keyEquivalent = "\r"; create.isEnabled = false
        let buttons = NSStackView(views: [rescan,reveal,create]); buttons.spacing = 12; stack.addArrangedSubview(buttons)
        let footer = NSTextField(wrappingLabelWithString: "Local processing • Original files stay untouched • Requires Resolve Studio 21 or Premiere 26.2"); footer.font = .systemFont(ofSize: 11); footer.textColor = .secondaryLabelColor; stack.addArrangedSubview(footer)
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        checkDependencies()
    }
    func button(_ title: String,_ action: Selector) -> NSButton { let b = NSButton(title: title,target: self,action: action); b.setContentHuggingPriority(.required, for: .horizontal); return b }
    func addRow(_ stack: NSStackView,_ title: String,_ controls: [NSView]) {
        let label = NSTextField(labelWithString: title); label.font = .systemFont(ofSize: 12,weight: .semibold); stack.addArrangedSubview(label)
        let row = NSStackView(views: controls); row.orientation = .horizontal; row.spacing = 10; row.distribution = .fill; stack.addArrangedSubview(row); row.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        controls[0].setContentHuggingPriority(.defaultLow,for: .horizontal); controls[0].setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    }
    func checkDependencies() {
        if !FileManager.default.isExecutableFile(atPath: Bundle.main.resourceURL!.appendingPathComponent("runtime/python/bin/python3.11").path) { failure("The bundled Python runtime is missing. Reinstall ISO Assemble.") }
        if !FileManager.default.isExecutableFile(atPath: Bundle.main.resourceURL!.appendingPathComponent("runtime/ffprobe/bin/ffprobe").path) { failure("The bundled media reader is missing. Reinstall ISO Assemble.") }
    }
    func append(_ text: String) { log.textStorage?.append(NSAttributedString(string: text,attributes: [.font:NSFont.monospacedSystemFont(ofSize: 11,weight: .regular)])); log.scrollToEndOfDocument(nil); if let d=text.data(using:.utf8) {try? logHandle?.write(contentsOf:d)} }
    func busy(_ on: Bool) { choose.isEnabled = !on; destination.isEnabled = !on; project.isEditable = !on; target.isEnabled = !on; audio.isEnabled = !on && !choices.isEmpty; rescan.isEnabled = !on && !folder.stringValue.isEmpty; create.isEnabled = !on && !scannedOutput.isEmpty; if on {progress.startAnimation(nil)} else {progress.stopAnimation(nil)} }
    func failure(_ message: String) { status.stringValue = message; status.textColor = .systemRed; append("\n"+message+"\n") }
    @objc func pickFolder() {
        let p=NSOpenPanel(); p.canChooseDirectories=true; p.canChooseFiles=false; p.prompt="Scan Recording"; p.message="Choose the root folder containing your ATEM project, Video ISO Files and Audio Source Files."
        if p.runModal() == .OK, let u=p.url { folder.stringValue=u.path; selectedATEM=nil; project.stringValue=u.lastPathComponent+"_ISO_Assemble"; if output.stringValue.isEmpty {output.stringValue=FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Movies/ISO Assemble/"+u.lastPathComponent).path}; scanAgain() }
    }
    @objc func pickOutput() {
        let p=NSOpenPanel(); p.canChooseDirectories=true; p.canChooseFiles=false; p.canCreateDirectories=true; p.prompt="Save Here"
        if p.runModal() == .OK, let u=p.url {output.stringValue=u.path; if !folder.stringValue.isEmpty {scanAgain()} }
    }
    @objc func scanAgain() {
        guard !folder.stringValue.isEmpty && !output.stringValue.isEmpty else {return}
        premiereTimer?.invalidate(); pendingPremiere=nil
        scannedOutput=""; choices=[]; audio.removeAllItems(); audio.addItem(withTitle:"Scanning…"); successPath=nil; reveal.isEnabled=false
        log.string=""; status.textColor = .labelColor; summary.stringValue="Checking source files and recording boundaries…"
        var args=["scan","--root",folder.stringValue,"--output",output.stringValue]
        if let selected=selectedATEM {args += ["--project",selected]}
        run(args)
    }
    @objc func buildProject() {
        guard pendingPremiere == nil else {failure("Save the pending Premiere project first, or scan again to start a new conversion.");return}
        guard audio.indexOfSelectedItem > 0 else {failure("Choose your primary audio source first."); return}
        let source=choices[audio.indexOfSelectedItem-1]
        guard !project.stringValue.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else {failure("Enter a project name.");return}
        status.textColor = .labelColor
        if target.indexOfSelectedItem == 1 {
            guard NSRunningApplication.runningApplications(withBundleIdentifier:"com.adobe.PremierePro.26").isEmpty else {failure("Quit Premiere before creating a new project. macOS otherwise imports XML into the open project. Save your work, quit Premiere, then retry.");return}
            guard NSWorkspace.shared.urlForApplication(withBundleIdentifier:"com.adobe.PremierePro.26") != nil else {failure("Adobe Premiere 26 is required for this output.");return}
            run(["premiere","--output",scannedOutput,"--name",project.stringValue,"--audio",source]);return
        }
        let url=URL(fileURLWithPath:"/Applications/DaVinci Resolve/DaVinci Resolve.app")
        guard FileManager.default.fileExists(atPath:url.path) else {failure("DaVinci Resolve is not installed in /Applications/DaVinci Resolve. Install Resolve Studio before creating the project.");return}
        NSWorkspace.shared.openApplication(at:url,configuration:NSWorkspace.OpenConfiguration()) { _,error in if let error=error {DispatchQueue.main.async{self.append("Resolve launch: \(error.localizedDescription)\n")}} }
        run(["create","--output",scannedOutput,"--name",project.stringValue,"--audio",source])
    }
    func chooseATEM(_ paths:[String]) {
        let alert=NSAlert();alert.messageText="Choose the ATEM edit to reconstruct"
        alert.informativeText="This recording folder contains more than one ATEM project. Select the original or repaired edit you want to use."
        let picker=NSPopUpButton(frame:NSRect(x:0,y:0,width:420,height:28));picker.addItems(withTitles:paths.map{URL(fileURLWithPath:$0).lastPathComponent})
        alert.accessoryView=picker;alert.addButton(withTitle:"Use Selected Project");alert.addButton(withTitle:"Cancel")
        if alert.runModal() == .alertFirstButtonReturn {selectedATEM=paths[picker.indexOfSelectedItem];append("Selected ATEM project: \(selectedATEM!)\n");scanAgain()}
        else {status.stringValue="Choose a recording folder or scan again when ready."}
    }
    @objc func targetChanged() {
        create.title = target.indexOfSelectedItem == 0 ? "Create Resolve Project" : "Create Premiere Project"
        if target.indexOfSelectedItem == 1 {status.stringValue="Premiere uses one multicam per camera-file boundary. Quit Premiere first. After import, Save As into your results folder; verification runs automatically."}
    }
    func openPremiere(_ e:[String:Any]) {
        guard let xml=e["xml"] as? String,let projectPath=e["project"] as? String,let name=e["name"] as? String,
              let app=NSWorkspace.shared.urlForApplication(withBundleIdentifier:"com.adobe.PremierePro.26") else {failure("Could not locate Premiere 26.");return}
        status.stringValue="In Premiere, use File → Save As: "+projectPath
        append(status.stringValue+"\nTechnical splices at file boundaries: \(e["splices"] ?? 0)\n")
        guard NSRunningApplication.runningApplications(withBundleIdentifier:"com.adobe.PremierePro.26").isEmpty else {failure("Premiere opened while preparing the XML. Quit it and retry to preserve existing projects.");return}
        pendingPremiere=(projectPath,name)
        NSWorkspace.shared.open([URL(fileURLWithPath:xml)],withApplicationAt:app,configuration:NSWorkspace.OpenConfiguration()) {_,error in
            if let error=error {DispatchQueue.main.async {self.failure("Premiere could not open the XML: \(error.localizedDescription)")}}
        }
        premiereTimer?.invalidate()
        premiereTimer=Timer.scheduledTimer(withTimeInterval:3,repeats:true) {timer in
            guard self.process == nil,let pending=self.pendingPremiere else{return}
            guard let attrs=try? FileManager.default.attributesOfItem(atPath:pending.0),let modified=attrs[.modificationDate] as? Date,Date().timeIntervalSince(modified)>2 else{return}
            timer.invalidate();self.pendingPremiere=nil
            self.run(["verify-premiere","--output",URL(fileURLWithPath:pending.0).deletingLastPathComponent().path,"--name",pending.1])
        }
    }
    func run(_ arguments:[String]) {
        guard process == nil else{return}; busy(true); buffer=""
        try? FileManager.default.createDirectory(atPath:output.stringValue,withIntermediateDirectories:true)
        let path=URL(fileURLWithPath:output.stringValue).appendingPathComponent("ISO Assemble.log").path
        if !FileManager.default.fileExists(atPath:path) {FileManager.default.createFile(atPath:path,contents:nil)}
        logHandle=FileHandle(forWritingAtPath:path); _ = try? logHandle?.seekToEnd()
        let p=Process(); p.executableURL=URL(fileURLWithPath:Bundle.main.resourceURL!.appendingPathComponent("runtime/python/bin/python3.11").path)
        p.arguments=["-u",Bundle.main.resourceURL!.appendingPathComponent("engine/app_engine.py").path]+arguments
        var env=ProcessInfo.processInfo.environment; env["PATH"]=Bundle.main.resourceURL!.appendingPathComponent("runtime/ffprobe/bin").path+":/usr/bin:/bin:/usr/sbin:/sbin"; env["PYTHONUNBUFFERED"]="1"; env["PYTHONDONTWRITEBYTECODE"]="1"; env["PYTHONNOUSERSITE"]="1"; env.removeValue(forKey:"PYTHONPATH"); env.removeValue(forKey:"PYTHONHOME"); p.environment=env
        let out=Pipe(), err=Pipe(); p.standardOutput=out;p.standardError=err
        out.fileHandleForReading.readabilityHandler = { handle in let data=handle.availableData; if !data.isEmpty {DispatchQueue.main.async {self.consume(data)}} }
        err.fileHandleForReading.readabilityHandler = { handle in let data=handle.availableData; if !data.isEmpty {DispatchQueue.main.async {self.append(String(decoding:data,as:UTF8.self))}} }
        p.terminationHandler = { task in
            out.fileHandleForReading.readabilityHandler=nil;err.fileHandleForReading.readabilityHandler=nil
            let rest=out.fileHandleForReading.readDataToEndOfFile();let errors=err.fileHandleForReading.readDataToEndOfFile()
            DispatchQueue.main.async {self.consume(rest);self.append(String(decoding:errors,as:UTF8.self));self.process=nil;self.busy(false);if task.terminationStatus != 0 && self.status.textColor != .systemRed {self.failure("Conversion stopped. Details are in the log above; your source files are unchanged.")};try? self.logHandle?.close();self.logHandle=nil;if let paths=self.pendingProjectChoices {self.pendingProjectChoices=nil;self.chooseATEM(paths)}}
        }
        process=p
        do {try p.run()} catch {process=nil;busy(false);failure(error.localizedDescription)}
    }
    func consume(_ data:Data) {
        buffer += String(decoding:data,as:UTF8.self)
        while let newline=buffer.firstIndex(of:"\n") {let line=String(buffer[..<newline]);buffer.removeSubrange(...newline); guard let d=line.data(using:.utf8), let e=(try? JSONSerialization.jsonObject(with:d)) as? [String:Any],let type=e["event"] as? String else {append(line+"\n");continue}
            if type=="project_choices" {pendingProjectChoices=e["paths"] as? [String]}
            if type=="progress" {status.stringValue=e["message"] as? String ?? "Working…";append(status.stringValue+"\n")}
            if type=="error" {failure(e["message"] as? String ?? "Unknown error")}
            if type=="scanned" {scannedOutput=e["output"] as? String ?? "";audio.removeAllItems();audio.addItem(withTitle:"Choose primary audio…");choices=[];for c in e["choices"] as? [[String:String]] ?? [] {choices.append(c["id"]!);audio.addItem(withTitle:c["label"]!)};summary.stringValue="\(e["cameras"] ?? 0) cameras  ·  \(e["clips"] ?? 0) ISO clips  ·  \(e["audioISOs"] ?? 0) audio ISOs  ·  \(e["cuts"] ?? 0) live cuts";status.stringValue="Scan complete. Choose primary audio, then create your editing project.";for w in e["warnings"] as? [String] ?? [] {append("Timing note: "+w+"\n")};reveal.isEnabled=true}
            if type=="premiere_ready" {openPremiere(e)}
            if type=="complete" {successPath=e["export"] as? String;status.textColor = .systemGreen;status.stringValue=e["message"] as? String ?? "Complete";append("Export: \(successPath ?? "")\nPrimary audio: \(e["audio"] ?? "")\n");reveal.isEnabled=true}
        }
    }
    @objc func showResults() {if let path=successPath {NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:path)])} else {NSWorkspace.shared.open(URL(fileURLWithPath:output.stringValue))}}
    @objc func about() {let a=NSAlert();a.messageText="ISO Assemble";a.informativeText="ATEM recordings → native editable multicam.\nVersion 1.1 • Apple Silicon\nNo Codex account, plugin or service required.";a.runModal()}
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {if process != nil {let a=NSAlert();a.messageText="A conversion is running";a.informativeText="Let this operation finish before quitting so Resolve can finish saving the project.";a.runModal();return .terminateCancel};return .terminateNow}
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool{return true}
}
let app=NSApplication.shared
let delegate=AppDelegate();app.delegate=delegate;app.run()
