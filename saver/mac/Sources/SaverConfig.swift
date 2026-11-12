import Foundation

/// Where the saver keeps its settings and image cache. The saver runs inside
/// legacyScreenSaver's sandbox, so its Library is that app's container; the
/// (unsandboxed) control app reaches into the same container so both sides
/// share one config file and one cache.
enum SaverPaths {
    static let containerID = "com.apple.ScreenSaver.Engine.legacyScreenSaver"

    static var library: URL {
        // Test harnesses point this somewhere they can write without TCC.
        if let override = ProcessInfo.processInfo.environment["PINTEREST_SAVER_LIBRARY"] {
            return URL(fileURLWithPath: override, isDirectory: true)
        }
        let home = NSHomeDirectory()
        if home.contains("/Library/Containers/") {
            return URL(fileURLWithPath: home, isDirectory: true).appendingPathComponent("Library")
        }
        return URL(fileURLWithPath: realHome, isDirectory: true)
            .appendingPathComponent("Library/Containers/\(containerID)/Data/Library", isDirectory: true)
    }

    /// The user's actual home, even when NSHomeDirectory() is a container.
    static var realHome: String {
        if let pw = getpwuid(getuid()) { return String(cString: pw.pointee.pw_dir) }
        return NSHomeDirectory()
    }

    static var supportDir: URL {
        library.appendingPathComponent("Application Support/PinterestSaver", isDirectory: true)
    }
    static var configURL: URL { supportDir.appendingPathComponent("config.json") }
    static var cacheRoot: URL { library.appendingPathComponent("Caches/PinterestSaver", isDirectory: true) }
}

/// Settings shared by the saver, its Options sheet and the control app,
/// stored as JSON in the saver's container.
struct SaverSettings: Codable, Equatable {
    static let defaultFeed = "https://www.pinterest.com/pinterest/feed.rss"

    var feed = SaverSettings.defaultFeed
    var speed = 26.0            // points per second
    var showClock = true
    /// `_pinterest_sess` cookie; when set, the personal home feed is shown
    /// instead of the RSS feed above.
    var sessionCookie = ""
    /// Target column width in points; the grid fits as many as the screen allows.
    var columnWidth = 300.0
    var clock24h = false
    /// Cache file names the user hid; never shown and never re-downloaded.
    var hiddenPins: [String] = []

    init() {}

    // Decode key by key so configs written by older versions keep working.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let d = SaverSettings()
        feed = try c.decodeIfPresent(String.self, forKey: .feed) ?? d.feed
        speed = try c.decodeIfPresent(Double.self, forKey: .speed) ?? d.speed
        showClock = try c.decodeIfPresent(Bool.self, forKey: .showClock) ?? d.showClock
        sessionCookie = try c.decodeIfPresent(String.self, forKey: .sessionCookie) ?? d.sessionCookie
        columnWidth = try c.decodeIfPresent(Double.self, forKey: .columnWidth) ?? d.columnWidth
        clock24h = try c.decodeIfPresent(Bool.self, forKey: .clock24h) ?? d.clock24h
        hiddenPins = try c.decodeIfPresent([String].self, forKey: .hiddenPins) ?? d.hiddenPins
    }

    var usesHomeFeed: Bool { !sessionCookie.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    static func load() -> SaverSettings {
        if let data = try? Data(contentsOf: SaverPaths.configURL),
           let settings = try? JSONDecoder().decode(SaverSettings.self, from: data) {
            return settings
        }
        return migrateFromDefaults() ?? SaverSettings()
    }

    func save() throws {
        try FileManager.default.createDirectory(at: SaverPaths.supportDir, withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(self).write(to: SaverPaths.configURL, options: .atomic)
    }

    /// Versions before config.json kept settings in ScreenSaverDefaults, i.e.
    /// a ByHost plist in the container. Read that file directly so the app
    /// (which has a different defaults domain) can migrate it too.
    private static func migrateFromDefaults() -> SaverSettings? {
        let byHost = SaverPaths.library.appendingPathComponent("Preferences/ByHost", isDirectory: true)
        guard let files = try? FileManager.default.contentsOfDirectory(at: byHost, includingPropertiesForKeys: nil),
              let plist = files.first(where: { $0.lastPathComponent.hasPrefix("com.yuvraj.PinterestSaver.") }),
              let data = try? Data(contentsOf: plist),
              let dict = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any]
        else { return nil }
        var s = SaverSettings()
        if let v = dict["feed"] as? String, !v.isEmpty { s.feed = v }
        if let v = dict["speed"] as? Double { s.speed = v }
        if let v = dict["showClock"] as? Bool { s.showClock = v }
        if let v = dict["sessionCookie"] as? String { s.sessionCookie = v }
        try? s.save()
        return s
    }
}
