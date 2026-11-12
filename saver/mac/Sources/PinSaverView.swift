import ScreenSaver
import AppKit

@objc(PinSaverView)
final class PinSaverView: ScreenSaverView {

    // MARK: - Settings

    static let moduleName = "com.yuvraj.PinterestSaver"

    /// Stored as config.json in the saver's container so the control app can
    /// edit it too; see SaverConfig.swift.
    typealias Settings = SaverSettings
    static let defaultFeed = SaverSettings.defaultFeed

    // MARK: - Masonry model

    private struct Tile {
        let image: NSImage
        var y: CGFloat
        let height: CGFloat
    }

    private final class Column {
        var x: CGFloat = 0
        var width: CGFloat = 0
        var tiles: [Tile] = []
        var speedFactor: CGFloat = 1
    }

    private var settings = Settings.load()
    private let loader = FeedLoader()
    private var images: [NSImage] = []
    /// Shuffle bag: every pooled image is dealt once per cycle, shared across
    /// all columns, so the same pin can't pop up in two columns at once.
    private var bag: [NSImage] = []
    /// Images currently visible in any column; the bag skips these.
    private var onScreen = Set<ObjectIdentifier>()
    private var columns: [Column] = []
    private var lastFrameTime: CFTimeInterval = 0
    /// Size the columns were last built for; the system can resize the view
    /// after init (external displays especially), which must trigger a
    /// relayout or the grid stays small inside a black view.
    private var lastLayoutSize: NSSize = .zero
    private var statusMessage = "Loading pins…"
    private var sheetController: ConfigureSheetController?

    private var gutter: CGFloat { isPreview ? 6 : 14 }
    private var cornerRadius: CGFloat { isPreview ? 3 : 12 }
    private var minImagesToStart: Int { isPreview ? 4 : 8 }
    private var loadStart = CACurrentMediaTime()
    private var columnTarget: CGFloat {
        isPreview ? 90 : CGFloat(min(max(settings.columnWidth, 120), 800))
    }

    /// Don't build the grid until the pool can roughly fill the screen
    /// without repeats — a large monitor shows 40+ tiles, and starting at 8
    /// images means the same few pins everywhere. After a 10s grace period,
    /// start with whatever arrived so a slow network never blanks the saver.
    private func requiredImagesToStart() -> Int {
        if CACurrentMediaTime() - loadStart > 10 { return minImagesToStart }
        let count = max(2, Int(bounds.width / columnTarget))
        let width = (bounds.width - gutter * CGFloat(count + 1)) / CGFloat(count)
        let tilesPerColumn = Int(bounds.height / (width * 1.15 + gutter)) + 2
        return max(minImagesToStart, min(count * tilesPerColumn, 60))
    }

    // MARK: - Lifecycle

    override init?(frame: NSRect, isPreview: Bool) {
        super.init(frame: frame, isPreview: isPreview)
        animationTimeInterval = 1.0 / 30.0
        wantsLayer = true
        startLoading()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        animationTimeInterval = 1.0 / 30.0
        startLoading()
    }

    private func startLoading() {
        loader.onImage = { [weak self] image, fresh in
            guard let self else { return }
            self.images.append(image)
            // Periodic refreshes keep adding pins; cap the pool so a long
            // run doesn't grow memory without bound (oldest rotate out).
            if self.images.count > 150 {
                let old = self.images.removeFirst()
                self.bag.removeAll { $0 === old }
            }
            if fresh {
                // New pins jump the queue: visible within the next few tiles
                // instead of after a full cycle through the pool.
                self.bag.insert(image, at: Int.random(in: 0...min(self.bag.count, 8)))
            } else {
                self.bag.append(image)
            }
        }
        loader.onStatus = { [weak self] message in
            guard let self else { return }
            if self.images.isEmpty { self.statusMessage = message }
        }
        loader.hiddenFiles = Set(settings.hiddenPins)
        loader.start(feedString: settings.feed, sessionCookie: settings.sessionCookie)
    }

    /// Applies new settings in place: a new source reloads the pool, a new
    /// tile size only rebuilds the columns.
    func apply(_ newSettings: Settings) {
        let sourceChanged = newSettings.feed != settings.feed
            || newSettings.sessionCookie != settings.sessionCookie
        let layoutChanged = newSettings.columnWidth != settings.columnWidth
        settings = newSettings
        loader.hiddenFiles = Set(newSettings.hiddenPins)
        if sourceChanged {
            images.removeAll()
            bag.removeAll()
            onScreen.removeAll()
            columns.removeAll()
            loadStart = CACurrentMediaTime()
            statusMessage = "Loading pins…"
            loader.start(feedString: newSettings.feed, sessionCookie: newSettings.sessionCookie)
        } else if layoutChanged {
            columns.removeAll()
            onScreen.removeAll()
        }
    }

    // MARK: - Animation

    override func startAnimation() {
        super.startAnimation()
        lastFrameTime = CACurrentMediaTime()
    }

    override func animateOneFrame() {
        let now = CACurrentMediaTime()
        var dt = CGFloat(now - lastFrameTime)
        lastFrameTime = now
        dt = min(max(dt, 0), 0.2)

        if !columns.isEmpty, bounds.size != lastLayoutSize {
            columns.removeAll()
            onScreen.removeAll()
        }
        if columns.isEmpty, images.count >= requiredImagesToStart() {
            buildColumns()
        }
        guard !columns.isEmpty else {
            setNeedsDisplay(bounds)
            return
        }

        let base = CGFloat(settings.speed) * (isPreview ? 0.35 : 1.0)
        for column in columns {
            let dy = base * column.speedFactor * dt
            for i in column.tiles.indices {
                column.tiles[i].y -= dy
            }
            // Drop tiles that scrolled fully above the top edge.
            while let first = column.tiles.first, first.y + first.height < -40 {
                onScreen.remove(ObjectIdentifier(first.image))
                column.tiles.removeFirst()
            }
            refill(column)
        }
        setNeedsDisplay(bounds)
    }

    private func buildColumns() {
        lastLayoutSize = bounds.size
        let count = max(2, Int(bounds.width / columnTarget))
        let totalGutter = gutter * CGFloat(count + 1)
        let width = (bounds.width - totalGutter) / CGFloat(count)
        columns = (0..<count).map { i in
            let c = Column()
            c.width = width
            c.x = gutter + CGFloat(i) * (width + gutter)
            c.speedFactor = 0.85 + CGFloat((i * 7919) % 100) / 100.0 * 0.3
            // Stagger the seam so columns don't start flush at the same y.
            var y = -CGFloat((i * 4831) % 120)
            while y < bounds.height + 40 {
                guard let tile = makeTile(for: c, y: y) else { break }
                c.tiles.append(tile)
                y += tile.height + gutter
            }
            return c
        }
    }

    private func refill(_ column: Column) {
        var bottom = column.tiles.last.map { $0.y + $0.height + gutter } ?? 0
        while bottom < bounds.height + 40 {
            guard let tile = makeTile(for: column, y: bottom) else { break }
            column.tiles.append(tile)
            bottom += tile.height + gutter
        }
    }

    private func makeTile(for column: Column, y: CGFloat) -> Tile? {
        guard let image = nextBagImage() else { return nil }
        let size = image.size
        guard size.width > 0 else { return nil }
        var height = column.width * size.height / size.width
        height = min(max(height, column.width * 0.55), column.width * 2.0)
        onScreen.insert(ObjectIdentifier(image))
        return Tile(image: image, y: y, height: height)
    }

    private func nextBagImage() -> NSImage? {
        guard !images.isEmpty else { return nil }
        if bag.isEmpty { bag = images.shuffled() }
        // Prefer an image that isn't already visible somewhere on screen.
        for i in bag.indices where !onScreen.contains(ObjectIdentifier(bag[i])) {
            return bag.remove(at: i)
        }
        // Pool smaller than the visible tile count: repeats are unavoidable.
        return bag.removeFirst()
    }

    // MARK: - Drawing

    override func draw(_ rect: NSRect) {
        NSColor(calibratedWhite: 0.06, alpha: 1).setFill()
        bounds.fill()

        if columns.isEmpty {
            drawStatus()
        } else {
            drawGrid()
        }
        if settings.showClock && !isPreview {
            drawClock()
        }
    }

    private func drawGrid() {
        guard let ctx = NSGraphicsContext.current else { return }
        for column in columns {
            for tile in column.tiles {
                // Flip: model y grows downward, view coords grow upward.
                let frame = NSRect(x: column.x,
                                   y: bounds.height - tile.y - tile.height,
                                   width: column.width,
                                   height: tile.height)
                guard frame.intersects(bounds.insetBy(dx: 0, dy: -60)) else { continue }
                ctx.saveGraphicsState()
                NSBezierPath(roundedRect: frame, xRadius: cornerRadius, yRadius: cornerRadius).addClip()
                drawAspectFill(tile.image, in: frame)
                ctx.restoreGraphicsState()
            }
        }
    }

    private func drawAspectFill(_ image: NSImage, in frame: NSRect) {
        let size = image.size
        guard size.width > 0, size.height > 0 else { return }
        let scale = max(frame.width / size.width, frame.height / size.height)
        let drawSize = NSSize(width: size.width * scale, height: size.height * scale)
        let origin = NSPoint(x: frame.midX - drawSize.width / 2,
                             y: frame.midY - drawSize.height / 2)
        image.draw(in: NSRect(origin: origin, size: drawSize),
                   from: .zero,
                   operation: .sourceOver,
                   fraction: 1,
                   respectFlipped: true,
                   hints: [.interpolation: NSImageInterpolation.high.rawValue])
    }

    private func drawStatus() {
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .center
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: isPreview ? 9 : 20, weight: .medium),
            .foregroundColor: NSColor(calibratedWhite: 0.55, alpha: 1),
            .paragraphStyle: paragraph
        ]
        let text = NSAttributedString(string: statusMessage, attributes: attrs)
        let size = text.size()
        text.draw(at: NSPoint(x: bounds.midX - size.width / 2, y: bounds.midY - size.height / 2))
    }

    private func drawClock() {
        let formatter = DateFormatter()
        formatter.dateFormat = settings.clock24h ? "HH:mm" : "h:mm"
        let time = formatter.string(from: Date())
        formatter.dateFormat = "EEE d MMM"
        let date = formatter.string(from: Date())

        let shadow = NSShadow()
        shadow.shadowColor = NSColor.black.withAlphaComponent(0.8)
        shadow.shadowBlurRadius = 16
        shadow.shadowOffset = .zero

        let timeAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 88, weight: .thin),
            .foregroundColor: NSColor.white.withAlphaComponent(0.92),
            .shadow: shadow
        ]
        let dateAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 22, weight: .regular),
            .foregroundColor: NSColor.white.withAlphaComponent(0.75),
            .shadow: shadow
        ]

        let timeText = NSAttributedString(string: time, attributes: timeAttrs)
        let dateText = NSAttributedString(string: date, attributes: dateAttrs)
        let dateSize = dateText.size()

        let margin: CGFloat = 56
        timeText.draw(at: NSPoint(x: margin, y: margin + dateSize.height + 6))
        dateText.draw(at: NSPoint(x: margin + 6, y: margin))
    }

    // MARK: - Configuration

    override var hasConfigureSheet: Bool { true }

    override var configureSheet: NSWindow? {
        if sheetController == nil {
            sheetController = ConfigureSheetController()
        }
        sheetController?.load(settings: settings) { [weak self] newSettings in
            guard let self else { return }
            try? newSettings.save()
            self.apply(newSettings)
        }
        return sheetController?.window
    }
}
