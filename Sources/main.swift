import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = Controller()
controller.start()
note("started \(Updater.version)")
Setup.loginItem()
app.run()
