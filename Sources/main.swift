import AppKit

// uninstall.sh: unlink this Mac from Kit on your phone and drop its key, then quit, with no menu bar app
if CommandLine.arguments.contains("--phone-unlink") { PhoneLink.unlinkAndQuit() }
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
Migrate.beforeStart()
WhatsNew.newInstall = !FileManager.default.fileExists(atPath: State.file.path)
ChromeWindow.registerDefault()
KitWindow.installMainMenu()
let controller = Controller()
controller.start()
Migrate.afterStart()
Limit.dropOldCredits()
note("started \(Updater.version)")
Setup.loginItem()
app.run()
