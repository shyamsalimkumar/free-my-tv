// A card at the top right of the Mac's screen, like a notification, with a note from the TV: its drawing and message.
// Script notifications can't hold a picture, hence a window of its own. A click opens the drawing in Preview; it
// closes by itself after 20 seconds. Run by note.py --get:
//
//     swift webos/note_popup.swift <drawing.png or ""> <title> <when> <message>
import AppKit

let args = CommandLine.arguments
guard args.count == 5 else { exit(2) }
let imagePath = args[1], title = args[2], when = args[3], message = args[4]

let app = NSApplication.shared
app.setActivationPolicy(.accessory)   // no Dock icon

let width: CGFloat = 380, pad: CGFloat = 14
let image = imagePath.isEmpty ? nil : NSImage(contentsOfFile: imagePath)
let imageHeight = image.map { ($0.size.height / max($0.size.width, 1)) * (width - 2 * pad) } ?? 0

func label(_ text: String, _ font: NSFont, _ color: NSColor, lines: Int = 1) -> NSTextField {
    let field = NSTextField(wrappingLabelWithString: text)
    field.font = font
    field.textColor = color
    field.maximumNumberOfLines = lines
    field.lineBreakMode = .byTruncatingTail
    field.preferredMaxLayoutWidth = width - 2 * pad
    return field
}

let head = label(title, .boldSystemFont(ofSize: 13), .labelColor)
let sub = label(when, .systemFont(ofSize: 11), .secondaryLabelColor)
let body = label(message, .systemFont(ofSize: 13), .labelColor, lines: 4)
let bodyHeight = message.isEmpty ? 0 : body.fittingSize.height
let height = pad + 18 + 16 + 8 + (image == nil ? 0 : imageHeight + 8) + (message.isEmpty ? 0 : bodyHeight + 4) + pad

let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: width, height: height),
                    styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
panel.level = .statusBar
panel.isOpaque = false
panel.backgroundColor = .clear
panel.hasShadow = true
panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

let card = NSVisualEffectView(frame: NSRect(x: 0, y: 0, width: width, height: height))
card.material = .popover
card.state = .active
card.wantsLayer = true
card.layer?.cornerRadius = 16
card.layer?.masksToBounds = true
panel.contentView = card

var y = height - pad
func place(_ view: NSView, _ h: CGFloat) {
    y -= h
    view.frame = NSRect(x: pad, y: y, width: width - 2 * pad, height: h)
    card.addSubview(view)
}
place(head, 18)
place(sub, 16)
y -= 8
if let image = image {
    let view = NSImageView(image: image)
    view.imageScaling = .scaleProportionallyUpOrDown
    view.wantsLayer = true
    view.layer?.cornerRadius = 8
    view.layer?.masksToBounds = true
    place(view, imageHeight)
    y -= 8
}
if !message.isEmpty { place(body, bodyHeight) }

/// A click anywhere on the card: the drawing in Preview, and the card goes.
class Click: NSView {
    override func mouseDown(with event: NSEvent) {
        if !imagePath.isEmpty { NSWorkspace.shared.open(URL(fileURLWithPath: imagePath)) }
        app.terminate(nil)
    }
}
card.addSubview(Click(frame: card.bounds))

if let screen = NSScreen.main?.visibleFrame {
    panel.setFrameOrigin(NSPoint(x: screen.maxX - width - 16, y: screen.maxY - height - 16))
}
panel.alphaValue = 0
panel.orderFrontRegardless()
NSAnimationContext.runAnimationGroup { $0.duration = 0.25; panel.animator().alphaValue = 1 }
DispatchQueue.main.asyncAfter(deadline: .now() + 20) { app.terminate(nil) }
app.run()
