import AppKit

/// Programmatic options sheet: feed field, speed slider, clock checkbox.
final class ConfigureSheetController: NSObject {

    let window: NSPanel
    private let feedField = NSTextField()
    private let cookieField = NSTextField()
    private let speedSlider = NSSlider(value: 26, minValue: 8, maxValue: 80, target: nil, action: nil)
    private let clockCheckbox = NSButton(checkboxWithTitle: "Show clock", target: nil, action: nil)
    private var onSave: ((PinSaverView.Settings) -> Void)?
    private var current = PinSaverView.Settings.load()

    override init() {
        window = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 440, height: 330),
                         styleMask: [.titled],
                         backing: .buffered,
                         defer: false)
        super.init()
        window.title = "Pin Options"
        // System Settings may open/close the sheet repeatedly; a released
        // window comes back as a dead handle and the sheet silently fails.
        window.isReleasedWhenClosed = false
        buildUI()
    }

    func load(settings: PinSaverView.Settings,
              onSave: @escaping (PinSaverView.Settings) -> Void) {
        current = settings
        self.onSave = onSave
        feedField.stringValue = settings.feed
        cookieField.stringValue = settings.sessionCookie
        speedSlider.doubleValue = settings.speed
        clockCheckbox.state = settings.showClock ? .on : .off
    }

    private func buildUI() {
        guard let content = window.contentView else { return }

        let title = label("Pinterest feed", size: 13, bold: true)
        let hint = label("Username (e.g. potterybarn), username/board, or a board URL.",
                         size: 11, bold: false)
        hint.textColor = .secondaryLabelColor

        feedField.placeholderString = "username or board URL"
        feedField.lineBreakMode = .byTruncatingTail

        let cookieTitle = label("Personal home feed (optional)", size: 13, bold: true)
        let cookieHint = label(
            "Paste your _pinterest_sess cookie from pinterest.com to show your own home feed instead. Leave empty to use the feed above.",
            size: 11, bold: false)
        cookieHint.textColor = .secondaryLabelColor
        cookieHint.lineBreakMode = .byWordWrapping
        cookieHint.maximumNumberOfLines = 3
        cookieField.placeholderString = "_pinterest_sess cookie value"
        cookieField.lineBreakMode = .byTruncatingTail

        let speedLabel = label("Scroll speed", size: 13, bold: true)

        let cancel = NSButton(title: "Cancel", target: self, action: #selector(cancelTapped))
        let ok = NSButton(title: "OK", target: self, action: #selector(okTapped))
        ok.keyEquivalent = "\r"
        cancel.keyEquivalent = "\u{1b}"

        let buttons = NSStackView(views: [cancel, ok])
        buttons.orientation = .horizontal
        buttons.spacing = 10

        let stack = NSStackView(views: [title, feedField, hint,
                                        cookieTitle, cookieField, cookieHint,
                                        speedLabel, speedSlider, clockCheckbox, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        stack.setCustomSpacing(2, after: feedField)
        stack.setCustomSpacing(16, after: hint)
        stack.setCustomSpacing(2, after: cookieField)
        stack.setCustomSpacing(16, after: cookieHint)
        stack.setCustomSpacing(16, after: clockCheckbox)
        stack.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 20),
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -20),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: content.bottomAnchor, constant: -20),
            feedField.widthAnchor.constraint(equalTo: stack.widthAnchor),
            cookieField.widthAnchor.constraint(equalTo: stack.widthAnchor),
            cookieHint.widthAnchor.constraint(equalTo: stack.widthAnchor),
            speedSlider.widthAnchor.constraint(equalTo: stack.widthAnchor),
            buttons.trailingAnchor.constraint(equalTo: stack.trailingAnchor)
        ])
    }

    private func label(_ text: String, size: CGFloat, bold: Bool) -> NSTextField {
        let l = NSTextField(labelWithString: text)
        l.font = bold ? .boldSystemFont(ofSize: size) : .systemFont(ofSize: size)
        return l
    }

    @objc private func okTapped() {
        current.feed = feedField.stringValue.isEmpty
            ? PinSaverView.defaultFeed
            : feedField.stringValue
        current.sessionCookie = cookieField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        current.speed = speedSlider.doubleValue
        current.showClock = clockCheckbox.state == .on
        onSave?(current)
        dismiss()
    }

    @objc private func cancelTapped() {
        dismiss()
    }

    private func dismiss() {
        if let parent = window.sheetParent {
            parent.endSheet(window)
        } else {
            window.orderOut(nil)
        }
    }
}
