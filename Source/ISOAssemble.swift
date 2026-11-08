import Cocoa

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let folder = NSTextField(string: "")
    let output = NSTextField(string: "")
    let project = NSTextField(string: "")
    let target = NSPopUpButton(frame: .zero, pullsDown: false)
    let mixReview = NSButton(checkboxWithTitle: "Rebuild mixes as linear dissolves; mark uncertain events for review", target: nil, action: nil)
    let mixNote = NSTextField(wrappingLabelWithString: "Resolve 21.1 or newer: original fader curves may be missing. Compare reconstructed dissolves and review markers with the preserved program reference.")
    var selectedATEM: String?
    var pendingProjectChoices: [String]?
    var premiereTimer: Timer?
    var pendingPremiere: (String,String)?
    let audio = NSPopUpButton(frame: .zero, pullsDown: false)
    let audioNote = NSTextField(wrappingLabelWithString: "All audio ISOs are imported. Only the primary source plays; camera switching does not change it.")
    let footer = NSTextField(wrappingLabelWithString: "Local processing • Original files stay untouched • Project output requires a supported editing app")
    var projectViews: [NSView] = []
    var audioPlanReady = false
    var plannedAudio: String?
    var isAudioMode: Bool { target.indexOfSelectedItem == 2 }
    let outputModeKeys = ["resolve", "premiere", "shared-audio"]
    var hasOutputMode: Bool { outputModeKeys.indices.contains(target.indexOfSelectedItem) }
    let status = NSTextField(wrappingLabelWithString: "Choose the root folder from your ATEM recording drive.")
    let summary = NSTextField(wrappingLabelWithString: "Camera angles, live cuts, recording gaps and all audio ISOs stay together.")
    let log = NSTextView()
    let progress = NSProgressIndicator()
    var choose: NSButton!, destination: NSButton!, create: NSButton!, reveal: NSButton!, rescan: NSButton!, checkMapping: NSButton!
    var process: Process?
    var buffer = ""
    var choices: [String] = []
    var scannedOutput = ""
    var successPath: String?
    var logHandle: FileHandle?
    var viewerButton: NSButton!
    var viewerProject: String?
    var viewerBusy = false
    var viewerReportFolder: String?
    var viewerNeedsPermission = false

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
        window = NSWindow(contentRect: NSRect(x: 0,y: 0,width: 860,height: 900), styleMask: [.titled,.closable,.miniaturizable], backing: .buffered, defer: false)
        window.title = "ISO Assemble"; window.center(); window.isReleasedWhenClosed = false
        let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 15
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 26)])
        let title = NSTextField(labelWithString: "ISO Assemble"); title.font = .systemFont(ofSize: 30, weight: .bold); stack.addArrangedSubview(title)
        let subtitle = NSTextField(labelWithString: "Your live edit. Every camera. Your chosen audio."); subtitle.font = .systemFont(ofSize: 14); subtitle.textColor = .secondaryLabelColor; stack.addArrangedSubview(subtitle)
        target.addItems(withTitles: ["DaVinci Resolve", "Adobe Premiere — Save As after import", "Camera files with shared audio", "Choose an output…"])
        let savedMode=UserDefaults.standard.string(forKey:"ISOAssembleOutputMode") ?? ""
        target.selectItem(at:outputModeKeys.firstIndex(of:savedMode) ?? 3)
        target.target=self; target.action=#selector(targetChanged); addRow(stack,"What would you like to create?",[target])
        mixReview.target=self; mixReview.action=#selector(mixChanged); stack.addArrangedSubview(mixReview)
        mixNote.font = .systemFont(ofSize: 11); mixNote.textColor = .secondaryLabelColor; stack.addArrangedSubview(mixNote); mixNote.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        choose = button("Choose Recording Folder…", #selector(pickFolder)); folder.placeholderString = "Select an ATEM recording folder"; folder.isEditable = false
        addRow(stack, "Recording folder", [folder,choose])
        destination = button("Choose…", #selector(pickOutput)); output.placeholderString = "Project files and validation report"; output.isEditable = false
        addRow(stack, "Save results to", [output,destination])
        project.placeholderString = "Project name"; let projectIndex = stack.arrangedSubviews.count; addRow(stack, "Project name", [project]); projectViews = Array(stack.arrangedSubviews.dropFirst(projectIndex))
        audio.addItem(withTitle: "Scan a recording folder first"); audio.isEnabled = false; audio.target=self; audio.action=#selector(audioChanged); addRow(stack, "Primary audio", [audio])
        audioNote.font = .systemFont(ofSize: 12); audioNote.textColor = .secondaryLabelColor; stack.addArrangedSubview(audioNote); audioNote.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        summary.font = .systemFont(ofSize: 14, weight: .medium); stack.addArrangedSubview(summary); summary.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        progress.style = .spinning; progress.controlSize = .small; progress.isDisplayedWhenStopped = false
        let statusRow = NSStackView(views: [progress,status]); statusRow.orientation = .horizontal; statusRow.spacing = 10; stack.addArrangedSubview(statusRow); statusRow.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.borderType = .bezelBorder; scroll.documentView = log
        log.isEditable = false; log.isSelectable = true; log.font = .monospacedSystemFont(ofSize: 11, weight: .regular); log.textContainerInset = NSSize(width: 8,height: 8); log.autoresizingMask = [.width]; log.textContainer?.widthTracksTextView = true
        stack.addArrangedSubview(scroll); scroll.heightAnchor.constraint(equalToConstant: 160).isActive = true; scroll.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        rescan = button("Scan Again", #selector(scanAgain)); rescan.isEnabled = false
        reveal = button("Show Results", #selector(showResults)); reveal.isEnabled = false
        create = button("Create New Resolve Project", #selector(buildProject)); create.bezelStyle = .rounded; create.keyEquivalent = "\r"; create.isEnabled = false
        checkMapping = button("Check Audio Mapping", #selector(checkAudioMapping)); checkMapping.isHidden = true; checkMapping.isEnabled = false
        viewerButton = button("Show Entire Edit", #selector(openMulticamViewer)); viewerButton.isHidden = true
        let buttons = NSStackView(views: [rescan,reveal,checkMapping,create,viewerButton]); buttons.spacing = 12; stack.addArrangedSubview(buttons)
        footer.font = .systemFont(ofSize: 11); footer.textColor = .secondaryLabelColor; stack.addArrangedSubview(footer); footer.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        targetChanged()
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
        if !FileManager.default.isExecutableFile(atPath: Bundle.main.resourceURL!.appendingPathComponent("runtime/ffmpeg/bin/ffmpeg").path) { failure("The bundled audio writer is missing. Reinstall ISO Assemble.") }
    }
    func append(_ text: String) { log.textStorage?.append(NSAttributedString(string: text,attributes: [.font:NSFont.monospacedSystemFont(ofSize: 11,weight: .regular)])); log.scrollToEndOfDocument(nil); if let d=text.data(using:.utf8) {try? logHandle?.write(contentsOf:d)} }
    func busy(_ processing: Bool) { let on = processing || viewerBusy; viewerButton?.isEnabled = !on && !viewerBusy; choose.isEnabled = !on && hasOutputMode; destination.isEnabled = !on && hasOutputMode; project.isEditable = !on; target.isEnabled = !on; mixReview.isEnabled = !on; audio.isEnabled = !on && !choices.isEmpty; rescan.isEnabled = !on && hasOutputMode && !folder.stringValue.isEmpty; checkMapping.isEnabled = !on && isAudioMode && !scannedOutput.isEmpty && audio.indexOfSelectedItem > 0; create.isEnabled = !on && hasOutputMode && !scannedOutput.isEmpty && (!isAudioMode || audioPlanReady); if on {progress.startAnimation(nil)} else {progress.stopAnimation(nil)} }
    func failure(_ message: String) { let first=String(message.split(separator:"\n",omittingEmptySubsequences:true).first ?? "Operation stopped."); status.stringValue = String(first.prefix(260)) + (first.count > 260 ? "… See the log for details." : ""); status.textColor = .systemRed; append("\n"+message+"\n") }
    @objc func pickFolder() {
        let p=NSOpenPanel(); p.canChooseDirectories=true; p.canChooseFiles=false; p.prompt="Scan Recording"; p.message=isAudioMode ? "Choose the recording root containing Video ISO Files and Audio Source Files. No ATEM project is required." : "Choose the root folder containing your ATEM project, Video ISO Files and Audio Source Files."
        if p.runModal() == .OK, let u=p.url { folder.stringValue=u.path; selectedATEM=nil; project.stringValue=u.lastPathComponent+"_ISO_Assemble"; if output.stringValue.isEmpty {output.stringValue=FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Movies/ISO Assemble/"+u.lastPathComponent).path}; scanAgain() }
    }
    @objc func pickOutput() {
        let p=NSOpenPanel(); p.canChooseDirectories=true; p.canChooseFiles=false; p.canCreateDirectories=true; p.prompt="Save Here"
        if p.runModal() == .OK, let u=p.url {output.stringValue=u.path; if !folder.stringValue.isEmpty {scanAgain()} }
    }
    @objc func scanAgain() {
        guard hasOutputMode && !folder.stringValue.isEmpty && !output.stringValue.isEmpty else {return}
        premiereTimer?.invalidate(); pendingPremiere=nil
        scannedOutput=""; choices=[]; audioPlanReady=false; plannedAudio=nil; audio.removeAllItems(); audio.addItem(withTitle:"Scanning…"); successPath=nil; reveal.isEnabled=false; viewerProject=nil; viewerNeedsPermission=false; viewerButton.isHidden=true
        log.string=""; status.textColor = .labelColor; summary.stringValue="Checking source files and recording boundaries…"
        var args=[isAudioMode ? "audio-scan" : "scan","--root",folder.stringValue,"--output",output.stringValue]
        if !isAudioMode, let selected=selectedATEM {args += ["--project",selected]}
        if target.indexOfSelectedItem == 0 && mixReview.state == .on {args += ["--mix-policy","linear-review"]}
        run(args)
    }
    @objc func mixChanged() {scannedOutput=""; if !folder.stringValue.isEmpty {scanAgain()} else {busy(false)}}
    @objc func audioChanged() {
        audioPlanReady=false; plannedAudio=nil
        if isAudioMode {status.textColor = .labelColor; summary.stringValue="Selected audio: " + (audio.titleOfSelectedItem ?? "Choose a source"); status.stringValue="Check the audio mapping before creating camera files."; successPath=nil}
        busy(process != nil)
    }
    @objc func checkAudioMapping() {
        guard isAudioMode, audio.indexOfSelectedItem > 0 else {failure("Choose your primary audio source first."); return}
        audioPlanReady=false; plannedAudio=nil; status.textColor = .labelColor
        run(["audio-plan","--root",folder.stringValue,"--output",scannedOutput,"--audio",choices[audio.indexOfSelectedItem-1]])
    }
    @objc func buildProject() {
        guard pendingPremiere == nil else {failure("Save the pending Premiere project first, or scan again to start a new conversion.");return}
        guard audio.indexOfSelectedItem > 0 else {failure("Choose your primary audio source first."); return}
        let source=choices[audio.indexOfSelectedItem-1]
        if isAudioMode {
            guard audioPlanReady && plannedAudio == source else {failure("Check Audio Mapping for the selected audio source first.");return}
            status.textColor = .labelColor
            run(["audio-build","--output",scannedOutput]);return
        }
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
        viewerProject=nil; viewerNeedsPermission=false; viewerButton.isHidden=true
        if hasOutputMode {UserDefaults.standard.set(outputModeKeys[target.indexOfSelectedItem],forKey:"ISOAssembleOutputMode")}
        else {UserDefaults.standard.removeObject(forKey:"ISOAssembleOutputMode")}
        create.title = !hasOutputMode ? "Create" : (isAudioMode ? "Create Camera Files" : (target.indexOfSelectedItem == 0 ? "Create New Resolve Project" : "Create Premiere Project"))
        create.keyEquivalent = isAudioMode || !hasOutputMode ? "" : "\r"
        checkMapping.isHidden = !isAudioMode; projectViews.forEach {$0.isHidden = isAudioMode || !hasOutputMode}
        mixReview.isHidden = target.indexOfSelectedItem != 0; mixNote.isHidden = mixReview.isHidden
        audioNote.stringValue = !hasOutputMode ? "Choose an editing project to reconstruct live cuts, or camera files to attach one WAV source to every angle." : (isAudioMode ? "The chosen WAV audio replaces camera audio in new MOV files. Video and timecode are kept. Import the new MOVs into your editor; the original ATEM project stays unchanged." : "All audio ISOs are imported. Only the primary source plays; camera switching does not change it.")
        footer.stringValue = !hasOutputMode ? "Local processing • Original files stay untouched" : (isAudioMode ? "Local processing • Original files stay untouched • No editing app required • Allow space for a new copy of every camera file" : "Local processing • Original files stay untouched • Resolve Studio 21+ (Mix: 21.1+) or Premiere 26.2")
        audioPlanReady=false; plannedAudio=nil; scannedOutput=""; successPath=nil; choices=[]; audio.removeAllItems(); audio.addItem(withTitle:"Scan a recording folder first")
        status.textColor = .labelColor
        summary.stringValue = !hasOutputMode ? "Select an output above to begin." : (isAudioMode ? "Original camera picture and timecode, with your chosen WAV audio." : "Camera angles, live cuts, recording gaps and all audio ISOs stay together.")
        status.stringValue = !hasOutputMode ? "Choose what you want to create before selecting a recording folder." : (isAudioMode ? "Choose the recording folder, select an audio ISO, then check the mapping." : "Choose a recording folder to prepare an editing project.")
        if hasOutputMode && !folder.stringValue.isEmpty {scanAgain()} else {busy(false)}
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
        var env=ProcessInfo.processInfo.environment; env["PATH"]=Bundle.main.resourceURL!.appendingPathComponent("runtime/ffmpeg/bin").path+":"+Bundle.main.resourceURL!.appendingPathComponent("runtime/ffprobe/bin").path+":/usr/bin:/bin:/usr/sbin:/sbin"; env["PYTHONUNBUFFERED"]="1"; env["PYTHONDONTWRITEBYTECODE"]="1"; env["PYTHONNOUSERSITE"]="1"; env.removeValue(forKey:"PYTHONPATH"); env.removeValue(forKey:"PYTHONHOME"); p.environment=env
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
            if type=="scanned" {scannedOutput=e["output"] as? String ?? "";audio.removeAllItems();audio.addItem(withTitle:"Choose primary audio…");choices=[];for c in e["choices"] as? [[String:String]] ?? [] {choices.append(c["id"]!);audio.addItem(withTitle:c["label"]!)};summary.stringValue="\(e["frameRate"] ?? "")  ·  \(e["cameras"] ?? 0) cameras  ·  \(e["clips"] ?? 0) ISO clips  ·  \(e["audioISOs"] ?? 0) audio ISOs  ·  \(e["sessions"] ?? 0) sessions  ·  \(e["cuts"] ?? 0) live cuts";status.stringValue="Scan complete. Choose primary audio. Create makes a fresh project every time.";for w in e["warnings"] as? [String] ?? [] {append("Timing note: "+w+"\n")};reveal.isEnabled=true}
            if type=="audio_scanned" {scannedOutput=e["output"] as? String ?? "";audio.removeAllItems();audio.addItem(withTitle:"Choose primary audio…");choices=[];for c in e["choices"] as? [[String:String]] ?? [] {if let id=c["id"],let label=c["label"] {choices.append(id);audio.addItem(withTitle:label)}};summary.stringValue="\(e["cameras"] ?? 0) cameras  ·  \(e["clips"] ?? 0) ISO clips  ·  \(e["audioISOs"] ?? 0) audio ISOs";status.stringValue="Choose the WAV source to attach to every camera, then Check Audio Mapping."}
            if type=="audio_plan" {plannedAudio=e["source"] as? String;audioPlanReady=plannedAudio != nil;summary.stringValue=e["summary"] as? String ?? "Audio mapping checked.";status.stringValue="Mapping passed. Create Camera Files will write and verify new MOVs. Existing files stay untouched.";append((e["details"] as? String ?? "")+"\n");reveal.isEnabled=true}
            if type=="premiere_ready" {openPremiere(e)}
            if type=="complete" {successPath=e["export"] as? String;status.textColor = .systemGreen;status.stringValue=e["message"] as? String ?? "Complete";append("Export: \(successPath ?? "")\nPrimary audio: \(e["audio"] ?? "")\n");reveal.isEnabled=true
                if e["prepareViewer"] as? Bool == true, let name=e["project"] as? String {
                    if let count=e["audioClips"] as? Int, let label=e["audio"] as? String {
                        audioNote.stringValue="Selected audio: "+label+" • \(count) clips on A1, independent of camera switching."
                    }
                    viewerProject=name;viewerReportFolder=e["output"] as? String ?? successPath.map{URL(fileURLWithPath:$0).deletingLastPathComponent().path};viewerButton.isHidden=false;prepareResolveViewer()
                }
            }
        }
    }
    @objc func openMulticamViewer() {
        guard !viewerBusy, process == nil, viewerProject != nil else {return}
        if !ResolveViewer.hasAccessibilityPermission {
            let alert=NSAlert();alert.messageText="Show the entire edit automatically"
            alert.informativeText="Enable ISO Assemble once in System Settings → Privacy & Security → Accessibility. This lets the app fit the entire Resolve timeline after every conversion, including every recording session and the gaps between them. Return to ISO Assemble after enabling it; the view will update automatically. Your DRP is already saved."
            alert.addButton(withTitle:"Open Permission Settings");alert.addButton(withTitle:"Use Manual Steps")
            if alert.runModal() == .alertFirstButtonReturn {viewerNeedsPermission=true;ResolveViewer.requestAccessibilityPermission()}
            else {append(ResolveViewer.manualFallback+"\n")}
            return
        }
        prepareResolveViewer()
    }
    func prepareResolveViewer() {
        guard let name=viewerProject, !viewerBusy else {return}
        viewerBusy=true;busy(process != nil)
        ResolveViewer.prepare(expectedProject:name,progress:{self.append($0+"\n")}) { result in
            self.viewerBusy=false;self.busy(self.process != nil)
            self.append(result.message+"\n")
            self.viewerNeedsPermission = result.status == .needsPermission
            self.viewerButton.title = self.viewerNeedsPermission ? "Enable Automatic View…" : "Show Entire Edit"
            let report:[String:Any] = ["project":name,"status":result.status.rawValue,"message":result.message,"controls":result.controlStates,"timeline_fitted":result.timelineFitted,"visually_verified":result.visuallyVerified,"manual_steps":result.manualFallback]
            if let data=try? JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]) {
                try? data.write(to:URL(fileURLWithPath:self.viewerReportFolder ?? self.scannedOutput).appendingPathComponent("Viewer Setup.json"),options:.atomic)
            }
            if result.status == .ready {
                self.status.stringValue="DRP saved. The entire edit is in view, including all sessions."
                self.status.textColor = .systemGreen
            } else if result.timelineFitted {
                self.status.stringValue="DRP saved. The entire edit is in view; multicam viewer setup is incomplete."
                self.status.textColor = .labelColor
            } else {
                self.status.stringValue = result.status == .needsPermission ? "DRP saved. Enable Automatic View once to show every session automatically." : "DRP saved. Click Show Entire Edit to fit every session into view."
                self.status.textColor = .labelColor
                self.append(result.manualFallback+"\n")
                if result.status == .needsPermission {
                    NSRunningApplication.runningApplications(withBundleIdentifier:"com.blackmagic-design.DaVinciResolve").first?.activate(options:[.activateIgnoringOtherApps])
                }
            }
        }
    }
    func applicationDidBecomeActive(_ notification: Notification) {
        guard viewerNeedsPermission, viewerProject != nil, !viewerBusy, process == nil,
              ResolveViewer.hasAccessibilityPermission else {return}
        viewerNeedsPermission=false
        prepareResolveViewer()
    }
    @objc func showResults() {if let path=successPath {NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:path)])} else {NSWorkspace.shared.open(URL(fileURLWithPath:output.stringValue))}}
    @objc func about() {let a=NSAlert();a.messageText="ISO Assemble";let version=Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? "";a.informativeText="ATEM multicam projects and camera files with shared audio.\nVersion \(version) • Apple Silicon\nNo Codex account, plugin or service required.";a.runModal()}
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {if process != nil || viewerBusy {let a=NSAlert();a.messageText="An operation is running";a.informativeText="Let this operation finish before quitting so files can be saved and verified.";a.runModal();return .terminateCancel};return .terminateNow}
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool{return true}
}
@main
enum ISOAssembleMain {
    static func main() {
        let app=NSApplication.shared
        let delegate=AppDelegate();app.delegate=delegate;app.run()
    }
}
