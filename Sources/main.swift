import AppKit

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
Migrate.beforeStart()
let controller = Controller()
controller.start()
Migrate.afterStart()
note("started \(Updater.version)")
Setup.loginItem()
app.run()
