// Offscreen test harness: runs the screensaver view for a few seconds and
// snapshots it to a PNG so rendering can be verified without installing.
import AppKit
import ScreenSaver

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)

let outPath = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1] : "/tmp/pinterestsaver.png"
let seconds = CommandLine.arguments.count > 2
    ? (Double(CommandLine.arguments[2]) ?? 10) : 10

// Start small and grow mid-run: mimics macOS resizing the saver view after
// init on external displays, which must trigger a grid relayout.
let smallFrame = NSRect(x: 0, y: 0, width: 900, height: 600)
let fullFrame = NSRect(x: 0, y: 0, width: 1728, height: 1080)
guard let view = PinSaverView(frame: smallFrame, isPreview: false) else {
    print("FAIL: could not create view")
    exit(1)
}

let window = NSWindow(contentRect: fullFrame, styleMask: [.borderless],
                      backing: .buffered, defer: false)
window.contentView = view
view.frame = smallFrame
view.startAnimation()

var resized = false
let start = Date()
let deadline = Date(timeIntervalSinceNow: seconds)
while Date() < deadline {
    RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: view.animationTimeInterval))
    if !resized, Date().timeIntervalSince(start) > seconds * 0.6 {
        view.frame = fullFrame
        resized = true
        print("resized view to \(Int(fullFrame.width))x\(Int(fullFrame.height))")
    }
    view.animateOneFrame()
}

guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
    print("FAIL: no bitmap rep")
    exit(1)
}
view.cacheDisplay(in: view.bounds, to: rep)
guard let png = rep.representation(using: .png, properties: [:]) else {
    print("FAIL: no png")
    exit(1)
}
try! png.write(to: URL(fileURLWithPath: outPath))
print("OK wrote \(outPath)")
exit(0)
