import Foundation
import AppKit
import CryptoKit

/// Fetches a Pinterest RSS feed, extracts pin image URLs, downloads them
/// (upgrading 236x thumbnails to 736x), and keeps a disk cache so the
/// screensaver has something to show instantly on later launches.
final class FeedLoader {

    /// Called on the main queue for each image; `fresh` is false for images
    /// preloaded from the disk cache, true for newly downloaded pins.
    var onImage: ((NSImage, _ fresh: Bool) -> Void)?
    /// Called on the main queue with a human-readable status (errors etc.).
    var onStatus: ((String) -> Void)?

    /// Re-fetch cadence while the saver is running; each home-feed request
    /// returns a fresh sample of ~30 pins, so new content keeps arriving.
    static let refreshInterval: TimeInterval = 600

    private let session: URLSession
    private var currentFeedURL: URL?
    private var currentCookie = ""
    private var refreshTimer: Timer?
    private let cacheRoot: URL
    /// Per-source subdirectory of cacheRoot ("home" or a hash of the feed
    /// URL), so switching sources never shows the previous source's pins.
    private var cacheDir: URL
    private var seenURLs = Set<String>()
    /// Cache files already turned into pool images this session (guarded by
    /// deliveredLock; touched from both the utility and URLSession queues).
    private var deliveredFiles = Set<String>()
    private let deliveredLock = NSLock()
    /// Cache file names the user hid; skipped on preload and never downloaded.
    var hiddenFiles = Set<String>()
    /// The control app only wants files on disk, not decoded preload images.
    var preloadCache = true

    init() {
        let config = URLSessionConfiguration.default
        config.httpAdditionalHeaders = [
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        ]
        config.timeoutIntervalForRequest = 20
        session = URLSession(configuration: config)

        cacheRoot = SaverPaths.cacheRoot
        cacheDir = cacheRoot
        try? FileManager.default.createDirectory(at: cacheRoot, withIntermediateDirectories: true)
    }

    private static func md5Hex(_ string: String) -> String {
        Insecure.MD5.hash(data: Data(string.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    /// Accepts a username ("someuser"), "user/board", a pinterest.com URL,
    /// or a full .rss URL, and returns the RSS feed URL.
    static func normalizeFeedURL(_ raw: String) -> URL? {
        var s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !s.isEmpty else { return nil }
        if s.hasSuffix(".rss") {
            if !s.hasPrefix("http") { s = "https://" + s }
            return URL(string: s)
        }
        if let u = URL(string: s), let host = u.host, host.contains("pinterest.") {
            var path = u.path
            while path.hasSuffix("/") { path.removeLast() }
            let parts = path.split(separator: "/").map(String.init)
            if parts.count == 1 {
                return URL(string: "https://www.pinterest.com/\(parts[0])/feed.rss")
            } else if parts.count >= 2 {
                return URL(string: "https://www.pinterest.com/\(parts[0])/\(parts[1]).rss")
            }
            return nil
        }
        while s.hasSuffix("/") { s.removeLast() }
        let parts = s.split(separator: "/").map(String.init)
        if parts.count == 1 {
            return URL(string: "https://www.pinterest.com/\(parts[0])/feed.rss")
        } else if parts.count >= 2 {
            return URL(string: "https://www.pinterest.com/\(parts[0])/\(parts[1]).rss")
        }
        return nil
    }

    /// Cache subdirectory for a source: "home" for the cookie feed, else a
    /// hash of the normalized feed URL.
    static func cacheDirectory(feedString: String, sessionCookie: String) -> URL {
        let cookie = sessionCookie.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = cookie.isEmpty
            ? md5Hex(normalizeFeedURL(feedString)?.absoluteString ?? feedString)
            : "home"
        return SaverPaths.cacheRoot.appendingPathComponent(key, isDirectory: true)
    }

    func start(feedString: String, sessionCookie: String = "") {
        let cookie = sessionCookie.trimmingCharacters(in: .whitespacesAndNewlines)
        let feedURL = FeedLoader.normalizeFeedURL(feedString)
        cacheDir = Self.cacheDirectory(feedString: feedString, sessionCookie: cookie)
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
        // A restart (new source, or the app's Refresh) must be able to fetch
        // and deliver everything again.
        seenURLs.removeAll()
        deliveredLock.lock()
        deliveredFiles.removeAll()
        deliveredLock.unlock()
        cleanupLegacyFlatCache()
        if preloadCache { loadCachedImages() }

        currentCookie = cookie
        currentFeedURL = feedURL
        if cookie.isEmpty && feedURL == nil {
            status("Invalid feed: \(feedString)")
            return
        }

        fetchOnce()
        if !cookie.isEmpty {
            // Startup burst: each home-feed call returns a different sample,
            // so a few spaced calls seed the grid with real variety.
            for delay in [6.0, 12.0] {
                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                    self?.fetchOnce()
                }
            }
        }
        scheduleRefresh()
    }

    /// One extra fetch on top of the schedule; the home feed returns a new
    /// sample each call, so this pulls in more pins.
    func fetchMore() {
        fetchOnce()
    }

    private func fetchOnce() {
        if !currentCookie.isEmpty {
            fetchHomeFeed(cookie: currentCookie)
        } else if let url = currentFeedURL {
            fetchFeed(url)
        }
    }

    private func scheduleRefresh() {
        refreshTimer?.invalidate()
        let timer = Timer(timeInterval: Self.refreshInterval, repeats: true) { [weak self] _ in
            self?.fetchOnce()
        }
        RunLoop.main.add(timer, forMode: .common)
        refreshTimer = timer
    }

    deinit {
        refreshTimer?.invalidate()
    }

    /// Early versions cached all sources into one flat directory; remove
    /// those files so they can't leak into the wrong source's grid.
    private func cleanupLegacyFlatCache() {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: cacheRoot, includingPropertiesForKeys: nil) else { return }
        for file in files where file.pathExtension == "img" {
            try? FileManager.default.removeItem(at: file)
        }
    }

    // MARK: - Cache

    private func loadCachedImages() {
        let files = (try? FileManager.default.contentsOfDirectory(
            at: cacheDir, includingPropertiesForKeys: [.contentModificationDateKey]))?.filter {
                $0.pathExtension == "img" && !hiddenFiles.contains($0.lastPathComponent)
            } ?? []
        DispatchQueue.global(qos: .utility).async { [weak self] in
            for file in files.shuffled().prefix(40) {
                guard let self else { return }
                self.markDelivered(file)
                guard let image = NSImage(contentsOf: file), image.size.width > 0 else { continue }
                self.deliver(image, fresh: false)
            }
        }
    }

    private func markDelivered(_ file: URL) {
        deliveredLock.lock()
        deliveredFiles.insert(file.lastPathComponent)
        deliveredLock.unlock()
    }

    private func wasDelivered(_ file: URL) -> Bool {
        deliveredLock.lock()
        defer { deliveredLock.unlock() }
        return deliveredFiles.contains(file.lastPathComponent)
    }

    private func cacheFile(for url: URL) -> URL {
        cacheDir.appendingPathComponent(Self.md5Hex(url.absoluteString) + ".img")
    }

    private func trimCache(keep: Int = 200) {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: cacheDir, includingPropertiesForKeys: [.contentModificationDateKey]) else { return }
        guard files.count > keep else { return }
        let sorted = files.sorted {
            let a = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let b = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return a < b
        }
        for file in sorted.prefix(files.count - keep) {
            try? FileManager.default.removeItem(at: file)
        }
    }

    // MARK: - Personal home feed (session cookie)

    /// Accepts either the bare `_pinterest_sess` value or a full cookie
    /// string. Session values are base64 and contain "=", so only an explicit
    /// "_pinterest_sess=" name marks an already-complete cookie string.
    static func cookieHeader(_ raw: String) -> String {
        raw.contains("_pinterest_sess=") ? raw : "_pinterest_sess=\(raw)"
    }

    private func authedRequest(_ url: URL, cookie: String) -> URLRequest {
        var req = URLRequest(url: url)
        req.setValue(Self.cookieHeader(cookie), forHTTPHeaderField: "Cookie")
        req.setValue("https://www.pinterest.com/", forHTTPHeaderField: "Referer")
        req.setValue("application/json, text/html", forHTTPHeaderField: "Accept")
        req.setValue("XMLHttpRequest", forHTTPHeaderField: "X-Requested-With")
        // Without the pws-handler header the resource router rejects the
        // request outright ("Invalid Resource Request").
        req.setValue("www/index.js", forHTTPHeaderField: "x-pinterest-pws-handler")
        req.setValue("/", forHTTPHeaderField: "x-pinterest-source-url")
        req.setValue("active", forHTTPHeaderField: "x-pinterest-appstate")
        return req
    }

    /// Pinterest's internal home-feed resource, the one the logged-in web app
    /// uses. Falls back to scraping the logged-in homepage HTML if it fails.
    private func fetchHomeFeed(cookie: String) {
        let options = #"{"options":{"field_set_key":"react_grid_pin","in_nux":false,"prependPartner":false},"context":{}}"#
        let encoded = options.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? ""
        guard let url = URL(string:
            "https://www.pinterest.com/resource/UserHomefeedResource/get/?source_url=%2F&data=\(encoded)") else {
            fetchHomepage(cookie: cookie)
            return
        }
        session.dataTask(with: authedRequest(url, cookie: cookie)) { [weak self] data, response, _ in
            guard let self else { return }
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            let urls = (200..<300).contains(code) ? Self.extractHomeFeedURLs(from: data) : []
            if urls.isEmpty {
                self.fetchHomepage(cookie: cookie)
            } else {
                self.downloadImages(urls)
            }
        }.resume()
    }

    /// Pin images sit at varying depths in the feed JSON depending on item
    /// type, so extract every pinimg URL from the raw text instead of walking
    /// the structure; downloadImages dedupes the resolution variants.
    static func extractHomeFeedURLs(from data: Data?) -> [URL] {
        guard let data, let text = String(data: data, encoding: .utf8) else { return [] }
        return extractImageURLs(from: text.replacingOccurrences(of: "\\/", with: "/"))
    }

    /// The logged-in homepage embeds the first batch of home-feed pins in its
    /// hydration JSON; the same pinimg regex used for RSS pulls them out.
    private func fetchHomepage(cookie: String) {
        guard let url = URL(string: "https://www.pinterest.com/") else { return }
        var req = authedRequest(url, cookie: cookie)
        req.setValue("text/html", forHTTPHeaderField: "Accept")
        req.setValue(nil, forHTTPHeaderField: "X-Requested-With")
        session.dataTask(with: req) { [weak self] data, _, error in
            guard let self else { return }
            if let error {
                self.status("Home feed error: \(error.localizedDescription)")
                return
            }
            guard let data, let html = String(data: data, encoding: .utf8) else {
                self.status("Home feed returned no data")
                return
            }
            let urls = Self.extractImageURLs(from: html)
            if urls.isEmpty {
                self.status("Couldn't load home feed — session cookie may be invalid or expired")
            } else {
                self.downloadImages(urls)
            }
        }.resume()
    }

    // MARK: - Feed

    private func fetchFeed(_ url: URL) {
        session.dataTask(with: url) { [weak self] data, response, error in
            guard let self else { return }
            if let error {
                self.status("Feed error: \(error.localizedDescription)")
                return
            }
            guard let data, let xml = String(data: data, encoding: .utf8) else {
                self.status("Feed returned no data")
                return
            }
            let urls = Self.extractImageURLs(from: xml)
            if urls.isEmpty {
                self.status("No pins found in feed")
                return
            }
            self.downloadImages(urls)
        }.resume()
    }

    static func extractImageURLs(from xml: String) -> [URL] {
        let pattern = #"https://i\.pinimg\.com/(?:[0-9]+x|originals)/[A-Za-z0-9/_\-]+\.(?:jpg|jpeg|png|gif|webp)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(xml.startIndex..., in: xml)
        var seen = Set<String>()
        var result: [URL] = []
        for match in regex.matches(in: xml, range: range) {
            guard let r = Range(match.range, in: xml) else { continue }
            let s = String(xml[r])
            if seen.insert(s).inserted, let u = URL(string: s) {
                result.append(u)
            }
        }
        return result
    }

    private func downloadImages(_ urls: [URL]) {
        for url in urls.prefix(120) {
            let hiRes = URL(string: url.absoluteString.replacingOccurrences(
                of: #"/(?:[0-9]+x|originals)/"#, with: "/736x/", options: .regularExpression)) ?? url
            guard seenURLs.insert(hiRes.absoluteString).inserted else { continue }

            let file = cacheFile(for: hiRes)
            if hiddenFiles.contains(file.lastPathComponent) { continue }
            if FileManager.default.fileExists(atPath: file.path) {
                // Pin from the current feed that's already on disk: it still
                // belongs in this activation's pool even though the random
                // preload pass didn't pick it.
                if !wasDelivered(file) {
                    markDelivered(file)
                    // Refresh mtime so current-feed pins aren't cache-evicted.
                    try? FileManager.default.setAttributes(
                        [.modificationDate: Date()], ofItemAtPath: file.path)
                    DispatchQueue.global(qos: .utility).async { [weak self] in
                        guard let image = NSImage(contentsOf: file), image.size.width > 0 else { return }
                        self?.deliver(image, fresh: false)
                    }
                }
                continue
            }

            markDelivered(file)
            download(hiRes, fallback: url, to: file)
        }
    }

    private func download(_ url: URL, fallback: URL?, to file: URL) {
        session.dataTask(with: url) { [weak self] data, response, _ in
            guard let self else { return }
            let ok = (response as? HTTPURLResponse).map { (200..<300).contains($0.statusCode) } ?? false
            guard ok, let data, let image = NSImage(data: data), image.size.width > 0 else {
                if let fallback, fallback != url {
                    self.download(fallback, fallback: nil, to: file)
                }
                return
            }
            try? data.write(to: file)
            self.trimCache()
            self.deliver(image, fresh: true)
        }.resume()
    }

    private func deliver(_ image: NSImage, fresh: Bool) {
        DispatchQueue.main.async { [weak self] in
            self?.onImage?(image, fresh)
        }
    }

    private func status(_ message: String) {
        DispatchQueue.main.async { [weak self] in
            self?.onStatus?(message)
        }
    }
}
