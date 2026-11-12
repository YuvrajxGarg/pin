// Renders the Pin icon: "pin" in a heavy grotesk, the i dotted with a lime pin head.
// Same tile, gradient and type as Dwn and Tag so the apps read as a family.
//   swift assets/make_icon.swift <out.iconset>
import AppKit
import CoreText

let lime = NSColor(srgbRed: 0.80, green: 1.0, blue: 0.30, alpha: 1).cgColor

/// Draws "pin": a dotless i whose dot is a lime pin head. Returns drawn width.
/// (x, baseline) in y-up coordinates.
@discardableResult
func drawMark(_ cg: CGContext, x: CGFloat, baseline: CGFloat, size: CGFloat, color: CGColor, draw: Bool = true) -> CGFloat {
    let font = NSFont.systemFont(ofSize: size, weight: .black)
    let kern = -size * 0.055
    let attrs: [NSAttributedString.Key: Any] = [.font: font, .kern: kern, .foregroundColor: NSColor(cgColor: color)!]
    func width(_ t: String) -> CGFloat {
        CGFloat(CTLineGetTypographicBounds(CTLineCreateWithAttributedString(NSAttributedString(string: t, attributes: attrs)), nil, nil, nil))
    }
    let word = "p\u{0131}n"
    let textW = width(word) - size * 0.055
    guard draw else { return textW }

    let line = CTLineCreateWithAttributedString(NSAttributedString(string: word, attributes: attrs))
    cg.textPosition = CGPoint(x: x, y: baseline)
    CTLineDraw(line, cg)

    // Centre of the dotless i's stem.
    let stemStart = x + width("p")
    let stemW = width("\u{0131}") + kern
    let cx = stemStart + stemW / 2
    let r = size * 0.125
    let cy = baseline + font.xHeight + size * 0.08 + r
    let head = CGRect(x: cx - r, y: cy - r, width: r * 2, height: r * 2)
    cg.addEllipse(in: head)
    cg.setFillColor(lime)
    cg.fillPath()
    // A small highlight so the dot reads as a glossy pin head.
    cg.addEllipse(in: CGRect(x: cx - r * 0.55, y: cy + r * 0.05, width: r * 0.5, height: r * 0.42))
    cg.setFillColor(NSColor.white.withAlphaComponent(0.55).cgColor)
    cg.fillPath()
    return textW
}

func bitmap(_ w: Int, _ h: Int, _ body: (CGContext) -> Void) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: 0, bitsPerPixel: 0)!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = ctx
    body(ctx.cgContext)
    NSGraphicsContext.current = nil
    return rep.representation(using: .png, properties: [:])!
}

func appIcon(_ px: Int) -> Data {
    bitmap(px, px) { cg in
        let s = CGFloat(px)
        let inset = s * 0.098
        let tile = CGRect(x: inset, y: inset * 1.15, width: s - inset * 2, height: s - inset * 2)
        let radius = tile.width * 0.225
        let tilePath = CGPath(roundedRect: tile, cornerWidth: radius, cornerHeight: radius, transform: nil)

        cg.saveGState()
        cg.setShadow(offset: CGSize(width: 0, height: -s * 0.012), blur: s * 0.03, color: NSColor.black.withAlphaComponent(0.45).cgColor)
        cg.addPath(tilePath)
        cg.setFillColor(NSColor(white: 0.07, alpha: 1).cgColor)
        cg.fillPath()
        cg.restoreGState()

        cg.saveGState()
        cg.addPath(tilePath)
        cg.clip()
        let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                              colors: [NSColor(white: 0.17, alpha: 1).cgColor, NSColor(white: 0.05, alpha: 1).cgColor] as CFArray,
                              locations: [0, 1])!
        cg.drawLinearGradient(grad, start: CGPoint(x: 0, y: tile.maxY), end: CGPoint(x: 0, y: tile.minY), options: [])
        cg.restoreGState()

        cg.addPath(CGPath(roundedRect: tile.insetBy(dx: s * 0.002, dy: s * 0.002), cornerWidth: radius, cornerHeight: radius, transform: nil))
        cg.setStrokeColor(NSColor.white.withAlphaComponent(0.12).cgColor)
        cg.setLineWidth(max(1, s * 0.004))
        cg.strokePath()

        let size = tile.width * (px <= 32 ? 0.44 : 0.36)
        let white = NSColor(white: 0.97, alpha: 1).cgColor
        let w = drawMark(cg, x: 0, baseline: 0, size: size, color: white, draw: false)
        let xh = NSFont.systemFont(ofSize: size, weight: .black).xHeight
        cg.saveGState()
        cg.addPath(tilePath)
        cg.clip()
        drawMark(cg, x: tile.midX - w / 2, baseline: tile.midY - xh * 0.72, size: size, color: white)
        cg.restoreGState()
    }
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.iconset"
try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
for (name, px) in [("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64), ("128x128", 128),
                   ("128x128@2x", 256), ("256x256", 256), ("256x256@2x", 512), ("512x512", 512), ("512x512@2x", 1024)] {
    try! appIcon(px).write(to: URL(fileURLWithPath: "\(out)/icon_\(name).png"))
}
print("wrote \(out)")
